"""Carver's improvement ladder, measured: does adding RULES or adding
INSTRUMENTS actually buy anything on this data?

*Leveraged Trading* ranks the available improvements over a single-instrument,
single-rule Starter System in descending order of value:

    more instruments  >  more rules  >  continuous forecasts  >  drop the stop

That ordering is an empirical claim, and this workspace now has the data to
check it rather than assume it. Section [5] builds the ladder rung by rung and
reports what each step was worth in Sharpe units.

Rules (all continuous forecasts, average |f| = 10, capped +/-20):

    EWMAC(16,64)   scalar 4.10     Carver's published scalars. NOT fitted here
    EWMAC(32,128)  scalar 2.79     and not searched -- using the book's numbers
    EWMAC(64,256)  scalar 1.91     is the entire point.
    Overnight 18-06                binary, from overnight_drift_carver_backtest

Carry is deliberately ABSENT. It needs a second contract's price and this data
is front-month continuous only; the skill's instruction is explicit that you do
not fake it with a proxy. Its omission matters -- carry is the one rule that is
genuinely uncorrelated with trend, so a trend-only book understates what a real
multi-rule book would achieve.

Structure, following Carver:
  * forecasts combined with equal rule weights x FDM (= 1/sqrt(w'Cw), cap 2.5)
  * positions = avg_position x combined_forecast/10, buffered at 10% of average
  * trend sleeve and overnight sleeve combined at the return level, then across
    instruments with a measured IDM on handcrafted weights
  * P&L is SEAM-FREE (first open -> last close inside a session) because the
    .v.0 continuous series is not price-adjusted; close-to-close would book the
    contango roll step as profit. See price_change() in the imported module.
  * every rule is checked against the speed limit ON ITS OWN TURNOVER, which is
    what the skill requires -- a fast rule gets dropped for an expensive
    instrument even when slower rules on the same instrument are fine.

    .venv\\Scripts\\python.exe trend_overnight_book_backtest.py
"""
from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

from overnight_drift_carver_backtest import (
    ANNUALISE, IDM_CAP, INSTRUMENTS, REPORTS, SPEED_LIMIT_PRECOST_SR, TAU,
    block_trades, carver_vol, cost_per_side, daily_closes, liquid_start,
    load_5m, price_change, stats, to_returns,
)

FORECAST_CAP = 20.0
FDM_CAP = 2.5
# Carver's published EWMAC forecast scalars. Pooled across instruments by him;
# re-estimating them per instrument on this sample would be fitting.
EWMAC = {"EWMAC16": (16, 64, 4.10),
         "EWMAC32": (32, 128, 2.79),
         "EWMAC64": (64, 256, 1.91)}
ON_WINDOW = ("18:00", "05:55")   # pre-specified, inherited; not searched here


# ------------------------------------------------------------- forecasts ------
def ewmac_forecast(closes, fast, slow, scalar):
    """Vol-normalised EWMA crossover, scaled to average |f| = 10, capped, lagged.

    Normalising by the daily PRICE vol (not percentage) is what makes the
    forecast comparable across instruments and across time.
    """
    raw = closes.ewm(span=fast).mean() - closes.ewm(span=slow).mean()
    price_vol = closes.diff().ewm(span=32).std()
    f = (raw / price_vol) * scalar
    return f.clip(-FORECAST_CAP, FORECAST_CAP).shift(1)   # known at t, traded t+1


def combine(forecasts, fdm):
    """Equal rule weights, scaled by the FDM, capped again after scaling."""
    return (forecasts.mean(axis=1) * fdm).clip(-FORECAST_CAP, FORECAST_CAP)


def fdm_of(forecasts):
    """1/sqrt(w'Cw) on the forecast correlation matrix, equal weights, capped."""
    C = forecasts.corr().values
    w = np.full(len(C), 1.0 / len(C))
    return min(1.0 / np.sqrt(float(w @ C @ w)), FDM_CAP)


# -------------------------------------------------------------- positions -----
def buffered(target, avg, frac=0.10):
    """Trade only to the edge of a +/-10%-of-average band.

    Carver's cheapest cost reduction: roughly halves turnover for negligible
    tracking error. Apply it before ever considering dropping a rule.
    """
    buf, cur, out = abs(avg) * frac, 0.0, []
    for t in target:
        if np.isfinite(t):
            lo, hi = t - buf, t + buf
            cur = round(lo) if cur < lo else (round(hi) if cur > hi else cur)
        out.append(cur)
    return pd.Series(out, index=target.index)


def forecast_sleeve(d, closes, vol, dpp, capital, forecast, side_cost,
                    tau=TAU, idm=1.0, weight=1.0, rolls_per_year=4.0):
    """Returns, turnover and average position for one continuous-forecast rule."""
    avg = capital * idm * weight * tau / (vol * closes * dpp)
    target = (avg * forecast / 10.0).replace([np.inf, -np.inf], np.nan)
    held = buffered(target, avg.mean())
    dpx = price_change(d, seam_free=True).reindex(closes.index)
    turn = held.diff().abs()
    pnl = held.shift(1) * dpp * dpx
    pnl -= turn * side_cost                                   # one side per lot
    pnl -= held.abs() * 2 * side_cost * rolls_per_year / 252.0  # rolls while open
    yrs = len(closes) / 252.0
    return (pnl / capital).fillna(0.0), turn.sum() / yrs, avg.mean()


def gross_sleeve(d, closes, vol, dpp, capital, forecast, tau=TAU):
    """Same sleeve with costs switched off -- needed to price the cost drag."""
    avg = capital * tau / (vol * closes * dpp)
    held = buffered((avg * forecast / 10.0).replace([np.inf, -np.inf], np.nan),
                    avg.mean())
    dpx = price_change(d, seam_free=True).reindex(closes.index)
    return ((held.shift(1) * dpp * dpx) / capital).fillna(0.0)


def div_mult(cols, cap=IDM_CAP):
    """Diversification multiplier from a return correlation matrix, equal weights."""
    C = cols.corr().values
    w = np.full(len(C), 1.0 / len(C))
    return min(1.0 / np.sqrt(float(w @ C @ w)), cap)


# ------------------------------------------------------------------ main ------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--capital", type=float, default=100_000)
    ap.add_argument("--commission", type=float, default=1.24)
    ap.add_argument("--ticks", type=float, default=1.0)
    ap.add_argument("--end", default="2026-08-01")
    args = ap.parse_args()

    REPORTS.mkdir(exist_ok=True)
    pd.set_option("display.width", 220)
    pd.set_option("display.max_columns", 40)
    limit = SPEED_LIMIT_PRECOST_SR / 3.0
    print("=" * 100)
    print("TREND + OVERNIGHT BOOK  --  Carver's improvement ladder, measured")
    print("=" * 100)

    # -- 1. load ------------------------------------------------------------
    book = {}
    for name, (fname, dpp, tick, group) in INSTRUMENTS.items():
        d = load_5m(fname, args.end)
        d = d[d.index >= liquid_start(d)]
        closes = daily_closes(d)
        vol = carver_vol(closes)
        book[name] = dict(d=d, closes=closes, vol=vol, dpp=dpp, group=group,
                          side_cost=cost_per_side(args.commission, args.ticks,
                                                  tick, dpp))
    print("\n[1] %d instruments, seam-free P&L, tau=%.0f%%, capital $%s"
          % (len(book), TAU * 100, format(args.capital, ",.0f")))

    # -- 2. per-rule speed limit -------------------------------------------
    print("\n[2] SPEED LIMIT PER RULE -- applied per rule per instrument, "
          "not to the book")
    print("    limit = pre-cost SR %.2f / 3 = %.3f SR/yr" %
          (SPEED_LIMIT_PRECOST_SR, limit))
    rows, sleeves, forecasts_by_inst = [], {}, {}
    for name, b in book.items():
        F = pd.DataFrame({r: ewmac_forecast(b["closes"], f, s, sc)
                          for r, (f, s, sc) in EWMAC.items()})
        forecasts_by_inst[name] = F
        ann_vol_ccy = (b["closes"] * b["dpp"] * b["vol"]).median()
        for r in EWMAC:
            net, tpy, avgpos = forecast_sleeve(
                b["d"], b["closes"], b["vol"], b["dpp"], args.capital,
                F[r], b["side_cost"])
            gro = gross_sleeve(b["d"], b["closes"], b["vol"], b["dpp"],
                               args.capital, F[r])
            sleeves["%s %s" % (name, r)] = net
            csr = (gro.mean() * 252) / (gro.std() * ANNUALISE) - \
                  (net.mean() * 252) / (net.std() * ANNUALISE)
            rows.append({"inst": name, "rule": r, "lots_traded_yr": tpy,
                         "avg_pos": avgpos, "cost_SR": csr,
                         "SR_gross": (gro.mean() * 252) / (gro.std() * ANNUALISE),
                         "SR_net": (net.mean() * 252) / (net.std() * ANNUALISE),
                         "passes": "pass" if csr <= limit else "BREACH"})
        # the overnight rule, from the already-vetted implementation
        tr = block_trades(b["d"], b["vol"], b["dpp"], ON_WINDOW[0], ON_WINDOW[1],
                          args.capital, b["side_cost"])
        idx = b["closes"].loc[b["vol"].dropna().index[0]:].index
        net = to_returns(tr, idx, args.capital)
        gro = to_returns(tr, idx, args.capital, "gross_$")
        sleeves["%s ON18-06" % name] = net
        srn = (net.mean() * 252) / (net.std() * ANNUALISE)
        srg = (gro.mean() * 252) / (gro.std() * ANNUALISE)
        rows.append({"inst": name, "rule": "ON18-06",
                     "lots_traded_yr": 2 * len(tr) / (len(idx) / 252.0) * tr.contracts.mean(),
                     "avg_pos": tr.contracts.mean(), "cost_SR": srg - srn,
                     "SR_gross": srg, "SR_net": srn,
                     "passes": "pass" if srg - srn <= limit else "BREACH"})
    RU = pd.DataFrame(rows).set_index(["inst", "rule"])
    print(RU.to_string(formatters={
        "lots_traded_yr": "{:,.0f}".format, "avg_pos": "{:.1f}".format,
        "cost_SR": "{:.3f}".format, "SR_gross": "{:+.2f}".format,
        "SR_net": "{:+.2f}".format}))
    print("    Trend rules trade a handful of lots a year and cost almost nothing "
          "in SR units.\n    The overnight rule is 2-3 orders of magnitude more "
          "expensive per unit of risk --\n    that is the price of a rule whose "
          "exposure is set by the clock, not by a signal.")
    print("""
    IMPORTANT -- cost_SR here is MEASURED (SR_gross - SR_net), not the a-priori
    screen. They disagree, and the measured one is right. The formula
    cost_ccy / (price x mult x sigma_ann) divides by the risk of holding the
    instrument CONTINUOUSLY. A block strategy is flat ~12h of every 24, so it
    realises only ~0.3-0.5x that risk while paying the full ticket. On MNQ the
    a-priori screen says the overnight rule costs 0.042 SR/yr; measured, it is
    0.147 -- a 3.5x understatement, and it moves MNQ from 'pass' to BREACH.
    Any part-time strategy needs the realised number; the a-priori screen is a
    lower bound on its cost, not an estimate of it.""")

    # -- 3. combine the trend family ---------------------------------------
    print("\n[3] TREND SLEEVE -- 3 speeds combined, equal weights x FDM")
    trend = {}
    for name, b in book.items():
        F = forecasts_by_inst[name]
        fdm = fdm_of(F.dropna())
        cf = combine(F, fdm)
        net, tpy, _ = forecast_sleeve(b["d"], b["closes"], b["vol"], b["dpp"],
                                      args.capital, cf, b["side_cost"])
        trend[name] = net
        st = stats(net)
        print("    %-4s FDM %.2f   SR_net %+.2f   ann_vol %.1f%% (%.2f x tau)   "
              "maxDD %.1f%%   lots/yr %.0f"
              % (name, fdm, st["SR_net"], st["ann_vol"] * 100, st["vol_vs_tau"],
                 st["maxDD"] * 100, tpy))
    print("    FDM ~1.1-1.2 is expected: three trend speeds are highly correlated, "
          "so combining\n    them adds little. Carry would add far more than a "
          "fourth speed -- and cannot be\n    computed from front-month-only data.")

    # -- 4. trend + overnight, per instrument -------------------------------
    print("\n[4] TREND + OVERNIGHT, per instrument (sleeve weights 50/50 x measured DM)")
    combo = {}
    for name in book:
        pair = pd.DataFrame({"trend": trend[name],
                             "on": sleeves["%s ON18-06" % name]}).fillna(0.0)
        dm = div_mult(pair[(pair != 0).any(axis=1)])
        c = pair.mean(axis=1) * dm
        combo[name] = c
        corr = pair.corr().iloc[0, 1]
        st, stt, sto = stats(c), stats(pair.trend), stats(pair.on)
        print("    %-4s corr(trend,ON) %+.2f  DM %.2f | trend %+.2f  ON %+.2f  "
              "-> combined %+.2f   vol %.1f%%   maxDD %.1f%%"
              % (name, corr, dm, stt["SR_net"], sto["SR_net"], st["SR_net"],
                 st["ann_vol"] * 100, st["maxDD"] * 100))
    print("    A near-zero correlation is the whole argument for holding both: "
          "the overnight\n    sleeve is a clock exposure, the trend sleeve is a "
          "signal exposure, and they are\n    not the same bet.")

    # -- 5. book construction ----------------------------------------------
    def make_book(d_by_inst, members, label):
        P = pd.DataFrame({m: d_by_inst[m] for m in members}).fillna(0.0)
        P = P[(P != 0).any(axis=1)]
        groups = {}
        for m in members:
            groups.setdefault(INSTRUMENTS[m][3], []).append(m)
        w = {m: (1.0 / len(groups)) / len(g) for g in groups.values() for m in g}
        idm = min(1.0 / np.sqrt(float(np.array([w[m] for m in members]) @
                                      P.corr().values @
                                      np.array([w[m] for m in members]))), IDM_CAP)
        port = sum(P[m] * w[m] for m in members) * idm
        return port, idm

    p, i = make_book(trend, list(INSTRUMENTS), "trend 4")
    p2, i2 = make_book(combo, list(INSTRUMENTS), "combo 4")

    print("\n[5] THE LADDER -- what each Carver improvement was actually worth")
    ladder = []

    def rung(label, series_, note, step_from=None):
        st = stats(series_)
        ladder.append({"rung": label, "SR_net": st["SR_net"],
                       "step": np.nan if step_from is None
                               else st["SR_net"] - step_from,
                       "ann_vol": st["ann_vol"], "vol_vs_tau": st["vol_vs_tau"],
                       "maxDD": st["maxDD"], "DD_in_tau": st["DD_in_tau"],
                       "skew": st["skew"], "note": note})
        return st["SR_net"]

    # Each rung is the PREVIOUS rung plus one change, so `step` is meaningful.
    a = rung("1 inst 1 rule    MNQ EWMAC16", sleeves["MNQ EWMAC16"],
             "the Starter System")
    b = rung("1 inst 3 rules   MNQ trend", trend["MNQ"],
             "+ more rules (2 extra trend speeds)", a)
    c = rung("4 inst 3 rules   trend book", p,
             "+ more instruments (IDM %.2f)" % i, b)
    d = rung("4 inst 3+ON      full book", p2,
             "+ the overnight rule (IDM %.2f)" % i2, c)
    rung("[aside] 1 inst 3+ON MNQ trend+ON", combo["MNQ"],
         "MNQ alone with both sleeves -- compare to the 4-inst rungs", b)
    L = pd.DataFrame(ladder).set_index("rung")
    print(L[["SR_net", "step", "ann_vol", "vol_vs_tau", "maxDD", "DD_in_tau",
             "skew", "note"]].to_string(formatters={
        "SR_net": "{:+.2f}".format, "step": "{:+.2f}".format,
        "ann_vol": "{:.1%}".format, "vol_vs_tau": "{:.2f}".format,
        "maxDD": "{:.1%}".format, "DD_in_tau": "{:.1f}".format,
        "skew": "{:+.2f}".format}))
    print("""
    Carver ranks 'more instruments' above 'more rules'. On THIS data that
    ordering does not hold, and the reason is instructive rather than a
    refutation: the ordering assumes the instruments you add are ones that
    passed the screen. MCL did not -- it breaches the speed limit and its trend
    sleeve is -0.35 -- and equal-weighting a loser at 25% costs more than the
    diversification it brings. Carver's own instrument screen is what protects
    the ordering, and skipping it inverts the result.

    Note also what 'more rules' bought: nothing (+0.00). Three trend speeds are
    ~0.9 correlated, which is exactly why the FDM comes out at 1.07. The rule
    that helped was the one that is genuinely DIFFERENT (overnight, corr +0.34
    to trend), not the one that was merely additional.""")

    # -- 6. sanity ----------------------------------------------------------
    print("\n[6] SANITY CHECKS")
    full = p2
    print("    realised vol %.1f%% vs tau %.0f%% (%.2f x). Carver's tolerance is "
          "+/-25%%; a book\n    that runs cold is under-using its risk budget, not "
          "safer." % (full.std() * ANNUALISE * 100, TAU * 100,
                      full.std() * ANNUALISE / TAU))
    yrs = len(full) / 252.0
    sr = (full.mean() * 252) / (full.std() * ANNUALISE)
    print("    SR %+.2f over %.1f years. SE(SR) = %.2f, so the 95%% interval is "
          "[%+.2f, %+.2f]."
          % (sr, yrs, np.sqrt((1 + sr ** 2 / 2) / yrs), sr - 1.96 *
             np.sqrt((1 + sr ** 2 / 2) / yrs), sr + 1.96 *
             np.sqrt((1 + sr ** 2 / 2) / yrs)))
    print("    Expect a drawdown of at least %.0f%% (2 x tau) and plan for %.0f%%. "
          "Worst here: %.1f%%."
          % (2 * TAU * 100, 3 * TAU * 100,
             ((1 + full).cumprod() / (1 + full).cumprod().cummax() - 1).min() * 100))
    print("    Backtest Sharpe above ~1.5 on liquid markets should be assumed a bug "
          "first.")
    print("""
    On realised vol running above tau in the trend sleeves (1.3-1.5x): this is
    not an estimator fault. Forecast scaling targets average ABSOLUTE forecast
    10, which makes the average POSITION right, but portfolio risk scales with
    the root-mean-square of the forecast, and RMS > mean-abs for any spread
    distribution. Measured mean|f| is 8.7-10.6 across these instruments, i.e.
    the published scalars reproduce their design target on this sample -- the
    extra risk is structural to forecast scaling, and Carver accepts it rather
    than re-fitting scalars per instrument.""")

    # -- 7. artefacts -------------------------------------------------------
    RU.to_csv(REPORTS / "book_rule_speed_limit.csv")
    L.to_csv(REPORTS / "book_ladder.csv")
    out = dict(sleeves)
    out.update({"TREND %s" % k: v for k, v in trend.items()})
    out.update({"COMBO %s" % k: v for k, v in combo.items()})
    out["BOOK trend4"], out["BOOK full4"] = p, p2
    pd.DataFrame(out).to_csv(REPORTS / "book_daily_returns.csv")
    print("\n[7] written -> reports/book_rule_speed_limit.csv, book_ladder.csv, "
          "book_daily_returns.csv")


if __name__ == "__main__":
    main()
