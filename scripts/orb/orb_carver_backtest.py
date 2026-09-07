"""Opening-range breakout across instruments, vetted under Carver's *Leveraged
Trading* framework. Supersedes mgc_orb_carver_backtest.py, which was MGC-only
and reported the a-priori cost screen as its verdict.

Two corrections from the overnight work are baked in here:

  1. THE SPEED-LIMIT VERDICT IS THE MEASURED DRAG, NOT THE FORMULA.
     cost_ccy / (price x mult x sigma_ann) divides by the risk of holding the
     instrument CONTINUOUSLY. An ORB is flat ~18h of every 24, so it realises
     only a fraction of that risk while paying the full ticket. On the overnight
     block the formula understated the true drag by 3.5x and flipped a 'pass'
     into a BREACH. The formula is reported as a LOWER BOUND; SR_gross - SR_net
     is the number that decides.
  2. Session grouping is on the CME 18:00->17:00 clock, so the vol estimate a
     session is sized with is genuinely the prior settlement's. (An ORB never
     crosses a roll seam, so the seam-free P&L correction does not apply here --
     it is intraday by construction.)

The anchor is FIXED at the RTH open. That is what an opening-range breakout
means; making it a searchable parameter would be inventing degrees of freedom.
The grid varies the three things a practitioner actually chooses -- range
length, exit, and whether to filter by trend -- giving 18 cells per instrument,
scored against a sign-flip permutation null on the maximum.

Prior from this workspace that this test is up against: the 06:00-12:00 block,
which contains the RTH open and carries the highest volatility of the day, has
a measured Sharpe of ~0.05 on MNQ. An ORB trades precisely that block. A
positive result here would be surprising and should be treated as such.

    .venv\\Scripts\\python.exe orb_carver_backtest.py
    .venv\\Scripts\\python.exe orb_carver_backtest.py --insts MNQ --draws 2000
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "overnight"))
from overnight_drift_carver_backtest import (
    ANNUALISE, INSTRUMENTS, REPORTS, SPEED_LIMIT_PRECOST_SR, TAU,
    carver_vol, cost_per_side, daily_closes, load_5m, session_key,
    starter_system, stats,
)

RTH_OPEN, RTH_LAST = "09:30", "15:55"   # last 5-min bar label; its close is 16:00
ENTRY_CUTOFF = "14:30"
OR_MINUTES = (15, 30, 60)
EXITS = ("close", "or_stop", "or_stop_2r")
FILTERS = ("both", "trend")


# ------------------------------------------------------------------ data ------
def rth_liquid_start(d, min_bars=70, min_volume=5_000, run=21):
    """First session after which RTH liquidity NEVER drops back below tradeable.

    Gated on the RTH window specifically, not the whole 24h session: an ORB
    needs depth in the opening hours, and an instrument can be liquid overnight
    while being untradeable at 09:35. The LAST failing window sets the boundary
    -- taking the first passing one lets one busy fortnight unlock years of
    unfillable history.
    """
    rth = d.between_time(RTH_OPEN, RTH_LAST)
    g = rth.groupby(session_key(rth.index))
    bars, vol = g.size(), g["volume"].sum()
    ok = ((bars.rolling(run, min_periods=run).median() >= min_bars) &
          (vol.rolling(run, min_periods=run).median() >= min_volume))
    failing = ok[~ok]
    if failing.empty:
        return bars.index[0]
    after = ok[ok.index > failing.index[-1]]
    return after.index[0] if len(after) else bars.index[-1]


# ------------------------------------------------------------------ ORB -------
def orb_trades(d, vol, mac, dpp, or_min, exit_style, filt, capital, side_cost,
               tau=TAU):
    """One ORB variant, sized by vol. Signal on a bar close, filled next open."""
    or_end = (pd.Timestamp("2000-01-01 " + RTH_OPEN) +
              pd.Timedelta(minutes=or_min)).strftime("%H:%M")
    day = d.between_time(RTH_OPEN, RTH_LAST)
    out = []
    for date, s in day.groupby(session_key(day.index)):
        sd, sig = vol.get(date, np.nan), mac.get(date, np.nan)
        if not np.isfinite(sd) or sd <= 0:
            continue
        opening = s.between_time(RTH_OPEN, or_end, inclusive="left")
        if len(opening) < max(2, or_min // 10):
            continue
        hi, lo = opening["high"].max(), opening["low"].min()
        if not np.isfinite(hi) or not np.isfinite(lo) or hi <= lo:
            continue
        rest = s[s.index > opening.index[-1]]
        allow_long = allow_short = True
        if filt == "trend":
            if not np.isfinite(sig) or sig == 0:
                continue
            allow_long, allow_short = sig > 0, sig < 0

        hit = None
        for ts, b in rest.between_time(RTH_OPEN, ENTRY_CUTOFF).iterrows():
            if b["close"] > hi and allow_long:
                hit = (ts, 1)
                break
            if b["close"] < lo and allow_short:
                hit = (ts, -1)
                break
        if hit is None:
            continue
        sig_ts, side = hit
        nxt = rest[rest.index > sig_ts]
        if nxt.empty:
            continue
        entry = float(nxt.iloc[0]["open"])
        entry_ts = nxt.index[0]
        stop = lo if side > 0 else hi
        risk = abs(entry - stop)
        target = entry + side * 2.0 * risk
        exit_px, why = float(nxt.iloc[-1]["close"]), "close"
        exit_ts = nxt.index[-1]
        if exit_style != "close" and risk > 0:
            for ts, b in nxt.iterrows():
                stopped = (b["low"] <= stop) if side > 0 else (b["high"] >= stop)
                tgt = (b["high"] >= target) if side > 0 else (b["low"] <= target)
                if stopped:                      # stop wins ties: conservative
                    # GAP-AWARE FILL. A stop is a market order on trigger: if the
                    # bar OPENED through the level, you are filled at the open,
                    # not at the level you asked for. Assuming the exact level
                    # always fills is the single most dangerous bug in intraday
                    # level backtests -- this workspace has already seen it
                    # manufacture a Sharpe of 3.80 that collapsed to zero once
                    # fills were made gap-aware.
                    o = float(b["open"])
                    exit_px = min(stop, o) if side > 0 else max(stop, o)
                    why = "stop" if exit_px == stop else "stop_gap"
                    exit_ts = ts
                    break
                if tgt and exit_style == "or_stop_2r":
                    # A target is a resting LIMIT: a gap through it still fills
                    # at the limit price, so no adjustment is warranted here.
                    exit_px, why, exit_ts = target, "target", ts
                    break
        out.append({"date": date, "side": side, "entry": entry, "exit": exit_px,
                    "why": why, "or_width": hi - lo, "ann_vol": sd,
                    "or_hi": hi, "or_lo": lo, "stop": stop, "target": target,
                    "entry_ts": entry_ts, "exit_ts": exit_ts, "sig_ts": sig_ts,
                    "pts": side * (exit_px - entry)})
    tr = pd.DataFrame(out)
    if tr.empty:
        return tr
    tr["contracts"] = (capital * tau / (tr.ann_vol * tr.entry * dpp)).round()
    skipped = int((tr.contracts == 0).sum())     # too big for the account
    tr = tr[tr.contracts > 0].copy()
    tr.attrs["skipped_zero_lot"] = skipped
    tr["gross_$"] = tr.pts * dpp * tr.contracts
    tr["cost_$"] = 2.0 * side_cost * tr.contracts
    tr["net_$"] = tr["gross_$"] - tr["cost_$"]
    return tr


def to_returns(tr, index, capital, col="net_$"):
    if tr.empty:
        return pd.Series(0.0, index=index)
    return (tr.groupby("date")[col].sum() / capital).reindex(index).fillna(0.0)


def sr_of(tr, idx, capital, dpp, tick, commission_rt, ticks_rt, extra_stop_ticks=0.0):
    """Sharpe of one variant's trades under an arbitrary cost assumption.

    extra_stop_ticks is charged ONLY on stop exits. A stop is a market order
    fired into the move that just went against you, so it is the fill most
    likely to be worse than the model -- and the one a backtest flatters most.
    """
    if tr.empty:
        return np.nan
    rt = commission_rt + ticks_rt * tick * dpp
    net = tr["gross_$"] - tr.contracts * rt
    net -= tr.contracts * np.where(tr.why.str.startswith("stop"),
                                   extra_stop_ticks * tick * dpp, 0.0)
    r = (net.groupby(tr.date).sum() / capital).reindex(idx).fillna(0.0)
    return (r.mean() * 252) / (r.std() * ANNUALISE) if r.std() else np.nan


def stress(tr, idx, capital, dpp, tick, commission_rt, base_ticks, label, inst):
    """Everything that separates a real edge from a flattered one, in one block."""
    print("  [stress] %s" % label)
    rec = []
    sweep = [sr_of(tr, idx, capital, dpp, tick, commission_rt, t)
             for t in (1, 2, 4, 6, 8, 12)]
    print("    cost sweep, ticks RT   1:%+.2f  2:%+.2f  4:%+.2f  6:%+.2f  8:%+.2f  "
          "12:%+.2f" % tuple(sweep))
    rec += [{"inst": inst, "test": "cost %d tk" % t, "SR": v}
            for t, v in zip((1, 2, 4, 6, 8, 12), sweep)]
    stops = [sr_of(tr, idx, capital, dpp, tick, commission_rt, base_ticks, e)
             for e in (0, 1, 2, 4)]
    print("    extra slippage on STOP exits only, ticks  0:%+.2f  1:%+.2f  2:%+.2f  "
          "4:%+.2f" % tuple(stops))
    rec += [{"inst": inst, "test": "stop slip +%d tk" % e, "SR": v}
            for e, v in zip((0, 1, 2, 4), stops)]
    half = idx[len(idx) // 2]
    a, b = tr[tr.date < half], tr[tr.date >= half]
    sr_a = sr_of(a, idx[idx < half], capital, dpp, tick, commission_rt, base_ticks)
    sr_b = sr_of(b, idx[idx >= half], capital, dpp, tick, commission_rt, base_ticks)
    rec += [{"inst": inst, "test": "1st half", "SR": sr_a},
            {"inst": inst, "test": "2nd half", "SR": sr_b}]
    print("    split sample            1st half %+.2f (%s..)   2nd half %+.2f (%s..)"
          % (sr_of(a, idx[idx < half], capital, dpp, tick, commission_rt, base_ticks),
             str(idx[0].date()),
             sr_of(b, idx[idx >= half], capital, dpp, tick, commission_rt, base_ticks),
             str(half.date())))
    cov = (tr.date >= "2020-02-15") & (tr.date <= "2020-04-30")
    keep = idx[(idx < "2020-02-15") | (idx > "2020-04-30")]
    rec.append({"inst": inst, "test": "ex-COVID",
                "SR": sr_of(tr[~cov], keep, capital, dpp, tick, commission_rt,
                            base_ticks)})
    print("    ex-COVID (Feb-Apr 2020) %+.2f   [%d of %d trades removed]"
          % (sr_of(tr[~cov], keep, capital, dpp, tick, commission_rt, base_ticks),
             int(cov.sum()), len(tr)))
    daily = tr.groupby("date")["net_$"].sum().sort_values(ascending=False)
    for k in (5, 20):
        drop = daily.index[:k]
        v = sr_of(tr[~tr.date.isin(drop)], idx.difference(drop), capital, dpp,
                  tick, commission_rt, base_ticks)
        print("    drop best %2d sessions   %+.2f   [they are %.0f%% of total P&L]"
              % (k, v,
                 100 * daily.iloc[:k].sum() / daily.sum() if daily.sum() else np.nan))
        rec.append({"inst": inst, "test": "drop best %d" % k, "SR": v})
    return rec


def permutation_max_sr(panel, draws, seed):
    """Null for best-of-N: flip whole sessions, identically across every cell,
    so the cells' correlation -- the real difficulty of the search -- survives."""
    rng = np.random.default_rng(seed)
    x = panel.values
    sd0 = x.std(0)
    obs = np.nanmax(np.where(sd0 > 0, x.mean(0) * 252 / (sd0 * ANNUALISE), np.nan))
    null = np.empty(draws)
    for k in range(draws):
        y = x * rng.choice([-1.0, 1.0], size=len(x))[:, None]
        sd = y.std(0)
        null[k] = np.nanmax(np.where(sd > 0, y.mean(0) * 252 / (sd * ANNUALISE), np.nan))
    return obs, null


# ------------------------------------------------------------------ main ------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--insts", default="MNQ,MES,MGC")
    ap.add_argument("--capital", type=float, default=100_000)
    ap.add_argument("--commission", type=float, default=1.24)
    ap.add_argument("--ticks", type=float, default=2.0,
                    help="round-trip slippage+spread, ticks (breakouts cross)")
    ap.add_argument("--draws", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--end", default="2026-08-01")
    args = ap.parse_args()

    REPORTS.mkdir(exist_ok=True)
    pd.set_option("display.width", 220)
    pd.set_option("display.max_columns", 40)
    limit = SPEED_LIMIT_PRECOST_SR / 3.0
    print("=" * 100)
    print("OPENING-RANGE BREAKOUT  --  Carver Leveraged Trading vetting")
    print("=" * 100)
    print("\nAnchor fixed at the %s RTH open (that is what an ORB is). Grid varies "
          "range length,\nexit and trend filter only: %d cells per instrument."
          % (RTH_OPEN, len(OR_MINUTES) * len(EXITS) * len(FILTERS)))

    summary, all_grids, all_panels, all_stress = [], {}, {}, []
    for name in [s.strip() for s in args.insts.split(",")]:
        fname, dpp, tick, group = INSTRUMENTS[name]
        side_cost = cost_per_side(args.commission, args.ticks, tick, dpp)
        d = load_5m(fname, args.end)
        start = rth_liquid_start(d)
        d = d[d.index >= start]
        closes = daily_closes(d)
        vol = carver_vol(closes)
        mac = np.sign(closes.rolling(16).mean() - closes.rolling(64).mean()).shift(1)
        idx = closes.loc[vol.dropna().index[0]:].index
        yrs = len(idx) / 252.0

        print("\n" + "=" * 100)
        print("%s   %s -> %s   %d sessions (%.1f yr)   $%.0f/pt   tick $%.2f   "
              "cost/side $%.2f"
              % (name, start.date(), d.index[-1].date(), len(idx), yrs, dpp,
                 tick * dpp, side_cost))
        print("=" * 100)

        # -- cost, a-priori (lower bound only) -----------------------------
        px, sd = closes.median(), vol.median()
        ann_vol_ccy = px * dpp * sd
        apriori = side_cost / ann_vol_ccy * 504
        print("  [cost] median contract $%s, ann vol %.1f%% -> ann_vol_$ %s"
              % (format(px * dpp, ",.0f"), sd * 100, format(ann_vol_ccy, ",.0f")))
        print("         a-priori drag at 504 trades/yr = %.3f SR/yr  (LOWER BOUND -- "
              "an ORB is\n         flat ~18h/day, so the realised drag below is the "
              "verdict). Limit %.3f." % (apriori, limit))
        print("         minimum capital: 1 contract $%s, 4 contracts $%s"
              % (format(dpp * px * sd / TAU, ",.0f"),
                 format(4 * dpp * px * sd / TAU, ",.0f")))

        # -- Starter System baseline ---------------------------------------
        ss, n_ss = starter_system(d, vol, dpp, args.capital, side_cost)
        ss = ss.loc[idx[0]:]
        ss_sr = (ss.mean() * 252) / (ss.std() * ANNUALISE)
        print("  [baseline] Starter System MAC(16,64): SR_net %+.2f, %d entries "
              "(%.1f/yr), ann vol %.1f%%" % (ss_sr, n_ss, n_ss / yrs,
                                             ss.std() * ANNUALISE * 100))

        # -- grid ----------------------------------------------------------
        rows, panel, trade_store = [], {}, {}
        for or_min in OR_MINUTES:
            for ex in EXITS:
                for fl in FILTERS:
                    tr = orb_trades(d, vol, mac, dpp, or_min, ex, fl,
                                    args.capital, side_cost)
                    key = "OR%02d|%-10s|%s" % (or_min, ex, fl)
                    trade_store[key] = tr
                    r = to_returns(tr, idx, args.capital)
                    panel[key] = r
                    g = to_returns(tr, idx, args.capital, "gross_$")
                    srn = (r.mean() * 252) / (r.std() * ANNUALISE) if r.std() else np.nan
                    srg = (g.mean() * 252) / (g.std() * ANNUALISE) if g.std() else np.nan
                    st = stats(r)
                    rows.append({"cell": key, "trades": len(tr),
                                 "trades_yr": 2 * len(tr) / yrs,
                                 "SR_gross": srg, "cost_SR": srg - srn,
                                 "SR_net": srn, "ann_vol": st["ann_vol"],
                                 "maxDD": st["maxDD"], "skew": st["skew"],
                                 "avg_ct": tr.contracts.mean() if len(tr) else np.nan,
                                 "net_$": tr["net_$"].sum() if len(tr) else 0.0})
        G = pd.DataFrame(rows).set_index("cell").sort_values("SR_net", ascending=False)
        G["passes"] = np.where(G.cost_SR <= limit, "pass", "BREACH")
        all_grids[name] = G
        print("\n" + G.to_string(formatters={
            "trades_yr": "{:,.0f}".format, "SR_gross": "{:+.2f}".format,
            "cost_SR": "{:.3f}".format, "SR_net": "{:+.2f}".format,
            "ann_vol": "{:.1%}".format, "maxDD": "{:.1%}".format,
            "skew": "{:+.2f}".format, "avg_ct": "{:.1f}".format,
            "net_$": "{:,.0f}".format}))

        # -- best-of-N control ---------------------------------------------
        obs, null = permutation_max_sr(pd.DataFrame(panel), args.draws, args.seed)
        p = float((null >= obs).mean())
        best = G.index[0]
        print("\n  [search null] best %s  SR_net %+.3f | null max median %+.3f, "
              "95th %+.3f -> p = %.3f  %s"
              % (best, G.SR_net.iloc[0], np.median(null), np.percentile(null, 95),
                 p, "(search noise)" if p > 0.05 else "(survives)"))
        n_breach = int((G.passes == "BREACH").sum())
        print("  [verdict] %d/%d cells breach the speed limit on MEASURED drag; "
              "%d/%d beat the\n            Starter System's %+.2f; %d/%d are "
              "positive gross."
              % (n_breach, len(G), int((G.SR_net > ss_sr).sum()), len(G), ss_sr,
                 int((G.SR_gross > 0).sum()), len(G)))
        all_stress += stress(trade_store[best], idx, args.capital, dpp, tick,
                             args.commission, args.ticks,
                             "%s  %s" % (name, best), name)
        for k, v in panel.items():
            all_panels["%s %s" % (name, k.replace(" ", ""))] = v
        summary.append({"inst": name, "years": yrs, "apriori_cost_SR": apriori,
                        "measured_cost_SR": G.cost_SR.median(),
                        "understated_x": G.cost_SR.median() / apriori,
                        "best_SR_net": G.SR_net.iloc[0], "p_best": p,
                        "starter_SR": ss_sr,
                        "cells_pass": int((G.passes == "pass").sum()),
                        "cells_beat_starter": int((G.SR_net > ss_sr).sum())})

    S = pd.DataFrame(summary).set_index("inst")
    print("\n" + "=" * 100)
    print("CROSS-INSTRUMENT SUMMARY")
    print("=" * 100)
    print(S.to_string(formatters={
        "years": "{:.1f}".format, "apriori_cost_SR": "{:.3f}".format,
        "measured_cost_SR": "{:.3f}".format, "understated_x": "{:.1f}x".format,
        "best_SR_net": "{:+.2f}".format, "p_best": "{:.3f}".format,
        "starter_SR": "{:+.2f}".format}))
    print("\n  understated_x is how far the a-priori cost formula falls short of the "
          "realised drag.\n  It is >1 for every instrument because an ORB pays a full "
          "ticket for a fraction of a\n  day's risk -- the single most important "
          "correction when screening part-time rules.")

    print("\n  ON THE SPEED LIMIT AND CIRCULARITY")
    for n, g in all_grids.items():
        b = g.iloc[0]
        print("    %-4s measured drag %.3f vs the 0.30-prior limit %.3f -> %s.   "
              "But this cell's\n         own gross SR is %+.2f, which would imply a "
              "limit of %.3f -> %s."
              % (n, b.cost_SR, limit, "BREACH" if b.cost_SR > limit else "pass",
                 b.SR_gross, b.SR_gross / 3.0,
                 "BREACH" if b.cost_SR > b.SR_gross / 3 else "pass"))
    print("    The limit is deliberately set from a PRIOR (0.30 for a single-"
          "instrument rule), not\n    from the backtest's own gross, because using "
          "the backtest to justify its own costs\n    is how an overfit result "
          "launders itself. Read 'BREACH' as: this only works if the\n    gross edge "
          "is real, and the gross edge is the part you cannot verify.")

    print("\n  ESTIMATION ERROR ON THE HEADLINE")
    for n, g in all_grids.items():
        sr, y = g.SR_net.iloc[0], S.loc[n, "years"]
        se = np.sqrt((1 + sr ** 2 / 2) / y)
        print("    %-4s SR %+.2f over %.1f yr -> SE %.2f, 95%% CI [%+.2f, %+.2f]"
              % (n, sr, y, se, sr - 1.96 * se, sr + 1.96 * se))

    for n, g in all_grids.items():
        g.to_csv(REPORTS / ("orb_carver_grid_%s.csv" % n))
    S.to_csv(REPORTS / "orb_carver_summary.csv")
    pd.DataFrame(all_panels).to_csv(REPORTS / "orb_carver_daily_returns.csv")
    pd.DataFrame(all_stress).set_index(["inst", "test"]).to_csv(
        REPORTS / "orb_carver_stress.csv")
    print("\n  written -> reports/orb_carver_grid_<INST>.csv, orb_carver_summary.csv,"
          "\n             orb_carver_daily_returns.csv, orb_carver_stress.csv")


if __name__ == "__main__":
    main()
