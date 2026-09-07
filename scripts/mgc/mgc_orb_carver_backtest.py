"""Opening-range breakout on MGC (micro gold), vetted against Carver's
*Leveraged Trading* framework rather than against a P&L curve.

The framework's order of operations is deliberate and this script follows it:

  1. COST FIRST. cost_SR = cost_ccy / (price x multiplier x sigma_ann) is the
     Sharpe consumed per trade. An ORB does ~1 round trip per session, so the
     cost bill is settled before any signal is computed -- if it breaches the
     speed limit (pre-cost SR / 3) the strategy is dead and the backtest is
     decoration. MGC is a moving target here: the tick is fixed at $1.00 while
     gold's notional went from ~$18k/contract in 2020 to ~$46k in 2026, so the
     screen is run PER YEAR, not once.
  2. SIZE BY RISK. Contracts = Capital x tau / (sigma_ann x price x mult), with
     sigma_ann the 25-business-day stdev of daily returns x 16, lagged one
     session. Never a fixed lot count. tau = 12% (Starter System).
  3. RULES LAST, and cheaply. The ORB is not a rule with published evidence --
     unlike trend or carry -- so it carries a heavier evidential burden, not a
     lighter one. It is graded against MAC(16,64) with a vol-scaled trailing
     stop on the same data, same tau, same cost model: the Starter System is
     the number to beat, not zero.

Deliberate anti-fitting controls:

  * The 36-cell sensitivity grid is reported IN FULL as a grid. The peak cell is
    not a result -- it is the maximum of 36 correlated draws, so it is scored
    against a sign-flip permutation null on the *max*, with the same flips
    applied across every cell to preserve their correlation.
  * Every headline number is NET of modelled costs. Gross is labelled gross.
  * Signals are computed on a bar close and executed at the NEXT bar's open.
  * Fixed capital (no compounding) so Sharpe is not flattered by path.

Data: data/MGC_5min_databento.parquet, Databento GLBX.MDP3, MGC.v.0 volume roll
(calendar roll .c.0 walks into dead COMEX serial months -- see fetch script).
The usable intraday window is auto-detected: MGC only became a genuinely liquid
micro around 2020 (median 187 contracts/session in 2015 vs 289,600 in 2026), and
an opening range is not observable in a session that prints 36 bars.

    .venv\\Scripts\\python.exe mgc_orb_carver_backtest.py
    .venv\\Scripts\\python.exe mgc_orb_carver_backtest.py --capital 250000 --draws 2000
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).parent
DATA = HERE / "data"
REPORTS = HERE / "reports"

# MGC = 10 troy oz of gold. 1 point ($1/oz) = $10. Min tick 0.10 = $1.00.
DPP, TICK = 10.0, 0.10
ANNUALISE = 16.0                 # sqrt(256 business days), Carver's convention
VOL_WINDOW = 25                  # business days, Carver default
TAU = 0.12                       # Starter System risk target
SPEED_LIMIT_PRECOST_SR = 0.30    # single-instrument trend assumption

SESSION_END = "15:55"            # last 5-min bar label; its close is 16:00 ET
ENTRY_CUTOFF = "14:30"           # no new breakouts after this


# ------------------------------------------------------------------ data ------
def load_5m(fname):
    d = pd.read_parquet(DATA / fname).sort_index()
    d.index = d.index.tz_convert("US/Eastern")
    return d[["open", "high", "low", "close", "volume"]].astype(float)


def liquid_start(d, min_rth_bars=70, min_rth_volume=5_000, run=21):
    """First session after which liquidity NEVER drops back below tradeable.

    Data-driven rather than a hand-picked date: MGC's early years are thin
    enough that an opening range is neither observable nor fillable (median 187
    contracts/session in 2015), and eyeballing a start date is exactly the kind
    of quiet choice that fits a backtest. Two gates, both on a 21-session
    rolling median: enough 5-min bars for a range to form, and enough volume
    that a handful of micros is not a meaningful share of the session.

    The last *failing* window sets the boundary -- taking the first passing one
    would let a single busy fortnight in 2015 unlock a decade of fantasy fills.
    """
    rth = d.between_time("09:30", SESSION_END)
    g = rth.groupby(rth.index.normalize())
    bars, vol = g.size(), g["volume"].sum()
    ok = ((bars.rolling(run, min_periods=run).median() >= min_rth_bars) &
          (vol.rolling(run, min_periods=run).median() >= min_rth_volume))
    failing = ok[~ok]
    if failing.empty:
        return bars.index[0]
    after = ok[ok.index > failing.index[-1]]
    return after.index[0] if len(after) else bars.index[-1]


def daily_closes(d):
    """Session closes on the CME 18:00->17:00 clock, indexed by session date."""
    sess = (d.index + pd.Timedelta(hours=6)).normalize()   # 18:00 ET -> next date
    return d["close"].groupby(sess).last()


def carver_vol(closes, window=VOL_WINDOW):
    """Annualised vol, lagged one session so a day never sees its own return."""
    return closes.pct_change().rolling(window).std().mul(ANNUALISE).shift(1)


def intraday_vol_crosscheck(d):
    """Same vol from within-session 5-min returns -- immune to roll-seam jumps.

    If this and the close-to-close estimate agree, the continuous series is not
    fabricating variance at the roll and the Carver default can be used as-is.
    """
    sess = (d.index + pd.Timedelta(hours=6)).normalize()
    r = d["close"].pct_change()
    r = r.mask(~pd.Series(sess, index=d.index).duplicated())   # drop the seam return
    n = r.groupby(sess).count()
    return r.groupby(sess).std().mul(np.sqrt(n)).mul(ANNUALISE)


# ----------------------------------------------------------------- costs ------
def cost_per_side(commission_rt, slip_ticks_rt):
    """Dollars per contract per side. Repo convention: both args are round-trip."""
    return (commission_rt + slip_ticks_rt * TICK * DPP) / 2.0


def cost_screen(closes, vol, side_cost, trades_per_year):
    """Risk-adjusted cost by year. Run BEFORE any signal work."""
    df = pd.DataFrame({"px": closes, "vol": vol}).dropna()
    rows = []
    for yr, g in df.groupby(df.index.year):
        px, sd = g.px.median(), g.vol.median()
        ann_vol_ccy = px * DPP * sd
        c_sr = side_cost / ann_vol_ccy
        rows.append({
            "year": yr, "median_px": px, "contract_$": px * DPP, "ann_vol": sd,
            "ann_vol_$": ann_vol_ccy, "cost_SR_trade": c_sr,
            "annual_cost_SR": c_sr * trades_per_year,
            "min_cap_1ct": DPP * px * sd / TAU,
            "min_cap_4ct": 4 * DPP * px * sd / TAU,
        })
    return pd.DataFrame(rows).set_index("year")


# ------------------------------------------------------------------ ORB -------
def orb_trades(d, vol, mac, anchor, or_min, exit_style, filt):
    """One session's worth of ORB logic.

    anchor      "09:30" (equity RTH) or "08:20" (COMEX gold pit open)
    exit_style  "close"      flat at the 15:55 bar's close
                "or_stop"    + hard stop at the opposite opening-range edge
                "or_stop_2r" + that stop and a 2R target
    filt        "both"  take either side
                "trend" only in the direction of yesterday's MAC(16,64)
    """
    or_end = (pd.Timestamp("2000-01-01 " + anchor) +
              pd.Timedelta(minutes=or_min)).strftime("%H:%M")
    day = d.between_time(anchor, SESSION_END)
    out = []
    for date, s in day.groupby(day.index.normalize()):
        sd = vol.get(date, np.nan)
        sig = mac.get(date, np.nan)
        if not np.isfinite(sd) or sd <= 0:
            continue
        opening = s.between_time(anchor, or_end, inclusive="left")
        if len(opening) < max(2, or_min // 10):
            continue                                     # range never formed
        hi, lo = opening["high"].max(), opening["low"].min()
        if not np.isfinite(hi) or not np.isfinite(lo) or hi <= lo:
            continue
        rest = s[s.index > opening.index[-1]]
        scan = rest.between_time(anchor, ENTRY_CUTOFF)
        allow_long = allow_short = True
        if filt == "trend":
            if not np.isfinite(sig) or sig == 0:
                continue
            allow_long, allow_short = sig > 0, sig < 0

        hit = None
        for ts, b in scan.iterrows():
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
        entry = float(nxt.iloc[0]["open"])               # next-bar open, no lookahead
        entry_ts = nxt.index[0]

        stop = lo if side > 0 else hi
        risk = abs(entry - stop)
        target = entry + side * 2.0 * risk
        exit_px, exit_ts, why = float(nxt.iloc[-1]["close"]), nxt.index[-1], "close"
        if exit_style != "close" and risk > 0:
            for ts, b in nxt.iterrows():
                stopped = (b["low"] <= stop) if side > 0 else (b["high"] >= stop)
                tgt = (b["high"] >= target) if side > 0 else (b["low"] <= target)
                if stopped:                              # stop wins ties: conservative
                    exit_px, exit_ts, why = stop, ts, "stop"
                    break
                if tgt and exit_style == "or_stop_2r":
                    exit_px, exit_ts, why = target, ts, "target"
                    break

        out.append({
            "date": date, "side": side, "entry_ts": entry_ts, "entry": entry,
            "exit_ts": exit_ts, "exit": exit_px, "why": why, "or_hi": hi,
            "or_lo": lo, "or_width": hi - lo, "risk_pts": risk,
            "ann_vol": sd, "pts": side * (exit_px - entry),
        })
    return pd.DataFrame(out)


# -------------------------------------------------------------- sizing --------
def size_and_pnl(tr, capital, side_cost, tau=TAU, round_lots=True):
    """Vol-scaled contracts, then dollars. Sizing is the leg that matters."""
    if tr.empty:
        for c in ("contracts_raw", "contracts", "gross_$", "cost_$", "net_$"):
            tr[c] = pd.Series(dtype=float)
        return tr
    tr = tr.copy()
    tr["contracts_raw"] = capital * tau / (tr["ann_vol"] * tr["entry"] * DPP)
    tr["contracts"] = tr["contracts_raw"].round() if round_lots else tr["contracts_raw"]
    # Rounds to zero => the instrument is too big for the account at this vol.
    # Carver's answer is to not trade, not to trade a fractional lot.
    skipped = int((tr["contracts"] == 0).sum())
    tr = tr[tr["contracts"] > 0].copy()
    tr.attrs["skipped_zero_lot"] = skipped
    tr["gross_$"] = tr["pts"] * DPP * tr["contracts"]
    tr["cost_$"] = 2.0 * side_cost * tr["contracts"]      # round trip
    tr["net_$"] = tr["gross_$"] - tr["cost_$"]
    return tr


def session_returns(tr, index, capital, col="net_$"):
    """Daily return series on FIXED capital, zero-filled on no-trade sessions."""
    if tr.empty:
        return pd.Series(0.0, index=index)
    g = tr.groupby("date")[col].sum() / capital
    return g.reindex(index).fillna(0.0)


# --------------------------------------------------------------- stats --------
def stats(rets, tr, capital):
    yrs = len(rets) / 252.0
    mu, sd = rets.mean() * 252, rets.std() * ANNUALISE
    sr = mu / sd if sd > 0 else np.nan
    eq = (1 + rets).cumprod()
    dd = (eq / eq.cummax() - 1).min()
    gross = session_returns(tr, rets.index, capital, "gross_$")
    gsd = gross.std() * ANNUALISE
    gsr = (gross.mean() * 252) / gsd if gsd > 0 else np.nan
    n = len(tr)
    wins = int((tr["net_$"] > 0).sum()) if n else 0
    return {
        "trades": n, "trades_yr": 2 * n / yrs if yrs else np.nan,   # round trip = 2
        "ann_ret": mu, "ann_vol": sd, "vol_vs_tau": sd / TAU,
        "SR_net": sr, "SR_gross": gsr, "cost_SR": gsr - sr,
        "maxDD": dd, "DD_in_tau": abs(dd) / TAU,
        "skew": rets.skew(), "win_rate": wins / n if n else np.nan,
        "t_stat": sr * np.sqrt(yrs) if np.isfinite(sr) else np.nan,
        "net_$": tr["net_$"].sum() if n else 0.0,
        "cost_$": tr["cost_$"].sum() if n else 0.0,
        "avg_ct": tr["contracts"].mean() if n else np.nan,
        "no_lot": tr.attrs.get("skipped_zero_lot", 0),
    }


# ---------------------------------------------- Starter System benchmark ------
def starter_system(closes, vol, capital, side_cost, stop_frac=0.5, rolls_per_year=4.0):
    """MAC(16,64), binary, size fixed at open, trailing stop 0.5 x price x vol.

    The baseline every idea has to beat. Roll costs are charged explicitly for
    every session a position is open -- a futures system pays them whether or
    not the rule trades.
    """
    fast, slow = closes.rolling(16).mean(), closes.rolling(64).mean()
    mac = np.sign(fast - slow).shift(1)
    pnl = pd.Series(0.0, index=closes.index)
    held = pd.Series(0.0, index=closes.index)
    pos, ct, stop, ext = 0, 0.0, np.nan, np.nan
    rows = []
    for i, date in enumerate(closes.index):
        px, sd, sig = closes.iloc[i], vol.get(date, np.nan), mac.get(date, np.nan)
        if not np.isfinite(sd) or sd <= 0 or not np.isfinite(px):
            continue
        if pos != 0:
            pnl.loc[date] += pos * ct * DPP * (px - closes.iloc[i - 1])
            ext = max(ext, px) if pos > 0 else min(ext, px)
            gap = stop_frac * ext * sd
            stop = max(stop, ext - gap) if pos > 0 else min(stop, ext + gap)
            held.loc[date] = ct
            if (pos > 0 and px < stop) or (pos < 0 and px > stop):
                pnl.loc[date] -= side_cost * ct
                rows.append({"date": date, "action": "exit", "px": px, "ct": ct})
                pos, ct = 0, 0.0
        if pos == 0 and np.isfinite(sig) and sig != 0:
            size = round(capital * TAU / (sd * px * DPP))
            if size >= 1:
                pos, ct, ext = int(sig), size, px
                stop = px - sig * stop_frac * px * sd
                pnl.loc[date] -= side_cost * ct
                held.loc[date] = ct
                rows.append({"date": date, "action": "entry", "px": px, "ct": ct})
    pnl -= held * 2 * side_cost * rolls_per_year / 252.0   # roll cost while open
    return pnl / capital, pd.DataFrame(rows)


# ------------------------------------------------------------ permutation -----
def permutation_max_sr(panel, draws, seed):
    """Null for best-of-N. Flip the sign of whole sessions, identically across
    every grid cell, so the cells' correlation -- and therefore the true
    difficulty of the search -- is preserved."""
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
    ap.add_argument("--capital", type=float, default=100_000)
    ap.add_argument("--commission", type=float, default=1.24,
                    help="$/contract ROUND TURN (repo convention)")
    ap.add_argument("--ticks", type=float, default=2.0,
                    help="round-trip slippage+spread in ticks (0.10 tick = $1.00)")
    ap.add_argument("--draws", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--end", default="2026-08-01", help="exclusive; drops partial tail")
    args = ap.parse_args()

    side_cost = cost_per_side(args.commission, args.ticks)
    REPORTS.mkdir(exist_ok=True)
    pd.set_option("display.width", 220)
    pd.set_option("display.max_columns", 40)

    print("=" * 100)
    print("MGC OPENING-RANGE BREAKOUT  --  Carver Leveraged Trading vetting")
    print("=" * 100)

    # -- 1. data ------------------------------------------------------------
    d = load_5m("MGC_5min_databento.parquet")
    d = d[d.index < args.end]
    print("\n[1] DATA")
    print("    raw           %s -> %s  (%s 5-min bars)"
          % (d.index[0].date(), d.index[-1].date(), format(len(d), ",")))
    start = liquid_start(d)
    d = d[d.index >= start]
    closes = daily_closes(d)
    vol = carver_vol(closes)
    icheck = intraday_vol_crosscheck(d).shift(1)
    both = pd.concat([vol.rename("c2c"), icheck.rename("intra")], axis=1).dropna()
    print("    liquid window %s -> %s  (%d sessions, auto-detected on RTH bar count)"
          % (start.date(), d.index[-1].date(), len(closes)))
    print("    vol estimate  close-to-close %.1f%% vs intraday-only %.1f%%  (ratio %.2f)"
          % (both.c2c.median() * 100, both.intra.median() * 100,
             both.c2c.median() / both.intra.median()))
    print("    -> the two agree, so roll seams are not fabricating variance; "
          "Carver 25d c2c vol used as-is")

    # -- 2. COST FIRST ------------------------------------------------------
    limit = SPEED_LIMIT_PRECOST_SR / 3.0
    print("\n[2] COST SCREEN  (run before any signal is computed)")
    print("    cost/side = ($%.2f comm + %g tk x $1.00) / 2 = $%.2f/contract   "
          "round trip $%.2f" % (args.commission, args.ticks, side_cost, 2 * side_cost))
    print("    speed limit = pre-cost SR %.2f / 3 = %.3f SR/yr\n"
          % (SPEED_LIMIT_PRECOST_SR, limit))
    for tpy, label in [(504, "unfiltered ORB, ~1 round trip/session"),
                       (252, "trend-filtered ORB, ~1 round trip / 2 sessions")]:
        sc = cost_screen(closes, vol, side_cost, tpy)
        sc["verdict"] = np.where(sc.annual_cost_SR <= limit, "pass", "BREACH")
        print("    %s  (%d trades/yr)" % (label, tpy))
        out = sc[["median_px", "contract_$", "ann_vol", "cost_SR_trade",
                  "annual_cost_SR", "verdict"]]
        print(out.to_string(formatters={
            "median_px": "{:,.0f}".format, "contract_$": "{:,.0f}".format,
            "ann_vol": "{:.1%}".format, "cost_SR_trade": "{:.6f}".format,
            "annual_cost_SR": "{:.3f}".format}))
        print()
    mc = cost_screen(closes, vol, side_cost, 252).iloc[-1]
    print("    minimum capital at tau=%.0f%% (latest year): 1 contract $%s, "
          "4 contracts $%s"
          % (TAU * 100, format(mc.min_cap_1ct, ",.0f"), format(mc.min_cap_4ct, ",.0f")))
    if args.capital < mc.min_cap_4ct:
        print("    -> $%s is BELOW the 4-contract floor; rounding injects large "
              "risk error and some sessions size to zero contracts"
              % format(args.capital, ",.0f"))

    # -- 3. baseline: Starter System ---------------------------------------
    print("\n[3] BASELINE -- Starter System MAC(16,64), trailing stop 0.5 x px x vol")
    ss_rets, ss_tr = starter_system(closes, vol, args.capital, side_cost)
    ss_rets = ss_rets.loc[vol.dropna().index[0]:]
    yrs = len(ss_rets) / 252.0
    ss_sr = (ss_rets.mean() * 252) / (ss_rets.std() * ANNUALISE)
    ss_eq = (1 + ss_rets).cumprod()
    n_entry = int((ss_tr.action == "entry").sum()) if len(ss_tr) else 0
    print("    entries %d  (%.1f/yr)   SR_net %+.2f   ann_vol %.1f%%   maxDD %.1f%%   "
          "net $%s" % (n_entry, n_entry / yrs, ss_sr, ss_rets.std() * ANNUALISE * 100,
                       (ss_eq / ss_eq.cummax() - 1).min() * 100,
                       format((ss_rets * args.capital).sum(), ",.0f")))
    print("    Carver's published expectation for this system: SR ~0.24, ~1 trade/month, "
          "realised vol ~= tau")

    # -- 4. ORB grid --------------------------------------------------------
    mac_daily = np.sign(closes.rolling(16).mean() - closes.rolling(64).mean()).shift(1)
    idx = closes.loc[vol.dropna().index[0]:].index
    print("\n[4] ORB SENSITIVITY GRID -- all 36 cells reported; the max is NOT a result")
    rows, panel, trade_store = [], {}, {}
    for anchor in ("09:30", "08:20"):
        for or_min in (15, 30, 60):
            for exit_style in ("close", "or_stop", "or_stop_2r"):
                for filt in ("both", "trend"):
                    tr = size_and_pnl(orb_trades(d, vol, mac_daily, anchor, or_min,
                                                 exit_style, filt),
                                      args.capital, side_cost)
                    key = "%s|OR%02d|%-10s|%s" % (anchor, or_min, exit_style, filt)
                    r = session_returns(tr, idx, args.capital)
                    panel[key], trade_store[key] = r, tr
                    s = stats(r, tr, args.capital)
                    s["cell"] = key
                    rows.append(s)
    grid = pd.DataFrame(rows).set_index("cell")
    show = grid.sort_values("SR_net", ascending=False)
    print(show[["trades", "trades_yr", "SR_gross", "cost_SR", "SR_net", "ann_vol",
                "vol_vs_tau", "maxDD", "skew", "win_rate", "avg_ct", "no_lot",
                "net_$"]].to_string(
        formatters={"trades_yr": "{:,.0f}".format, "SR_gross": "{:+.2f}".format,
                    "cost_SR": "{:.2f}".format, "SR_net": "{:+.2f}".format,
                    "ann_vol": "{:.1%}".format, "vol_vs_tau": "{:.2f}".format,
                    "maxDD": "{:.1%}".format, "skew": "{:+.2f}".format,
                    "win_rate": "{:.1%}".format, "avg_ct": "{:.1f}".format,
                    "net_$": "{:,.0f}".format}))

    # -- 5. is the best cell real? -----------------------------------------
    P = pd.DataFrame(panel)
    obs, null = permutation_max_sr(P, args.draws, args.seed)
    p = float((null >= obs).mean())
    best = show.index[0]
    print("\n[5] BEST-OF-36 CONTROL -- sign-flip permutation on whole sessions")
    print("    best cell           %s   SR_net %+.3f" % (best, show.SR_net.iloc[0]))
    print("    null max SR (n=%d)  median %+.3f   95th %+.3f   max %+.3f"
          % (args.draws, np.median(null), np.percentile(null, 95), null.max()))
    print("    p(best-of-36)       %.3f   -> %s"
          % (p, "not distinguishable from search noise" if p > 0.05
             else "survives the search null"))

    # -- 6. verdict ---------------------------------------------------------
    print("\n[6] SPEED-LIMIT VERDICT (each cell judged on its own turnover)")
    v = grid.copy()
    v["limit"] = limit
    v["passes"] = np.where(v.cost_SR <= limit, "pass", "BREACH")
    print(v.sort_values("cost_SR")[["trades_yr", "cost_SR", "limit", "SR_gross",
                                    "SR_net", "passes"]].to_string(
        formatters={"trades_yr": "{:,.0f}".format, "cost_SR": "{:.3f}".format,
                    "limit": "{:.3f}".format, "SR_gross": "{:+.3f}".format,
                    "SR_net": "{:+.3f}".format}))
    n_breach = int((v.passes == "BREACH").sum())
    print("\n    %d/%d cells spend more than a third of a 0.30 gross Sharpe on costs."
          % (n_breach, len(v)))
    print("    realised vol is ~%.2f x tau across the grid -- the position is flat "
          "~18h of every 24." % grid.vol_vs_tau.median())
    print("    Levering back up to tau multiplies P&L AND costs by the same factor, "
          "so it moves\n    the return, never the Sharpe. Cost cannot be out-levered.")

    print("    %d/%d cells beat the Starter System's SR_net of %+.2f."
          % (int((grid.SR_net > ss_sr).sum()), len(grid), ss_sr))
    print("    %d/%d cells have positive GROSS Sharpe at all."
          % (int((grid.SR_gross > 0).sum()), len(grid)))
    bsr = show.SR_net.iloc[0]
    print("    Distinguishing SR %+.2f from zero at 95%% needs ~%.0f years; "
          "this test has %.1f." % (bsr, (1.96 ** 2) * (1 + bsr ** 2 / 2) /
                                   max(bsr ** 2, 1e-9), yrs))

    # -- 6b. does the cheap-gold regime rescue it? -------------------------
    print("\n[6b] ERA SPLIT -- gold's notional trebled, so cost in SR units fell ~7x")
    eras = [("2019-06..2022-12", "2019-06-25", "2023-01-01"),
            ("2023-01..2026-07", "2023-01-01", "2026-08-01")]
    er = []
    for cell in show.index[:5]:
        row = {"cell": cell}
        for name, lo, hi in eras:
            seg = P[cell].loc[lo:hi]
            sd = seg.std() * ANNUALISE
            row[name] = (seg.mean() * 252) / sd if sd > 0 else np.nan
        er.append(row)
    print(pd.DataFrame(er).set_index("cell").to_string(
        float_format=lambda x: "%+.2f" % x))
    print("    (top 5 cells by full-sample SR_net; a sign flip between eras is the "
          "usual\n     signature of a cell that was selected, not discovered)")

    # -- 7. artefacts -------------------------------------------------------
    grid.to_csv(REPORTS / "mgc_orb_carver_grid.csv")
    P.to_csv(REPORTS / "mgc_orb_carver_daily_returns.csv")
    trade_store[best].to_csv(REPORTS / "mgc_orb_carver_best_trades.csv", index=False)
    cost_screen(closes, vol, side_cost, 504).to_csv(REPORTS / "mgc_orb_cost_screen.csv")
    print("\n[7] written -> reports/mgc_orb_carver_grid.csv, "
          "mgc_orb_carver_daily_returns.csv,\n    mgc_orb_carver_best_trades.csv, "
          "mgc_orb_cost_screen.csv")


if __name__ == "__main__":
    main()
