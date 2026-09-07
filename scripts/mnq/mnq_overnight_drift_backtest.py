"""Overnight-drift harvest on REAL MNQ futures (6-hour bars), not cash proxies.

`overnight_drift_backtest.py` tested the idea on SPX/NDX cash indices: those carry
no financing, so the measured drift was gross of what a futures holder actually
pays. This rerun uses a TradingView export of CME_MINI:MNQ1! at 360-minute bars,
which is *difference back-adjusted* — roll gaps are spliced out, so point changes
are the true P&L of holding a rolled micro-Nasdaq position, with the cost of carry
already embedded in the price path. The drift measured here is net of financing.

Bar grid (America/New_York), four 6h blocks per session:
    18:00 -> 00:00  Asia        (Sunday bar carries the weekend gap)
    00:00 -> 06:00  London
    06:00 -> 12:00  NY morning  (contains the 09:30 RTH open)
    12:00 -> 18:00  NY afternoon(contains the 16:00 RTH close)

6h resolution cannot express the textbook 16:00->09:30 overnight window, so
"overnight" here is the Globex night 18:00 -> 06:00 and "day" is 06:00 -> 18:00.
The per-block attribution below shows where the return actually lives without
imposing either definition.

Sizing mirrors overnight_drift_backtest.py so the two are directly comparable:
vol-target on the *lagged* point volatility of the block being harvested, leverage
cap on notional, nothing used that is realized inside the block itself.

Costs are charged in TICKS, which is the honest unit for a real contract:
MNQ = $2.00/index point, 0.25pt tick = $0.50. A round trip of `c` ticks removes
0.25*c points from every traded block, whatever the sizing.

    python mnq_overnight_drift_backtest.py
    python mnq_overnight_drift_backtest.py --cost-ticks 2 --start 2023-01-01
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# Reuse the proxy run's metric definitions so numbers are apples-to-apples.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "overnight"))
from overnight_drift_backtest import perf, line

CSV = (Path(__file__).resolve().parents[2] / "data") / "CME_MINI_MNQ1!, 360_58b55.csv"
TZ = "America/New_York"
POINT_VALUE = 2.0      # MNQ: $2 per index point
TICK = 0.25            # index points per tick ($0.50)
BLOCKS = {18: "Asia (18-00)", 0: "London (00-06)", 6: "NY am (06-12)", 12: "NY pm (12-18)"}


def load_blocks(path: Path) -> pd.DataFrame:
    """Pivot 6h bars into one row per 18:00-anchored session, one column per block.

    Sessions without all four blocks (holidays, the truncated first/last week) are
    dropped so every sleeve trades the same calendar.
    """
    raw = pd.read_csv(path)
    ts = pd.to_datetime(raw["time"], utc=True, format="ISO8601").dt.tz_convert(TZ)
    d = pd.DataFrame({"ts": ts, "open": raw["open"], "high": raw["high"],
                      "low": raw["low"], "close": raw["close"]}).sort_values("ts")
    d["hour"] = d["ts"].dt.hour
    # a session runs 18:00 -> 18:00, so shift back 18h before taking the date
    d["session"] = (d["ts"] - pd.Timedelta(hours=18)).dt.normalize().dt.tz_localize(None)
    if not set(d["hour"]).issubset(BLOCKS):
        raise ValueError(f"unexpected bar hours: {sorted(set(d['hour']) - set(BLOCKS))}")

    wide = d.pivot_table(index="session", columns="hour",
                         values=["open", "close"], aggfunc="last")
    wide.columns = [f"{v}_{h}" for v, h in wide.columns]
    need = [f"{v}_{h}" for v in ("open", "close") for h in BLOCKS]
    wide = wide.dropna(subset=need).sort_index()

    # per-block point moves, plus the two aggregates and the 24h total
    for h in BLOCKS:
        wide[f"blk_{h}"] = wide[f"close_{h}"] - wide[f"open_{h}"]
    wide["overnight"] = wide["close_0"] - wide["open_18"]     # 18:00 -> 06:00
    wide["day"] = wide["close_12"] - wide["open_6"]           # 06:00 -> 18:00
    wide["full"] = wide["close_12"] - wide["open_18"]         # 24h hold
    wide["ref_price"] = wide["close_12"]                      # session close, for notional
    wide["dow"] = wide.index.dayofweek
    return wide


def sleeve(point_move: pd.Series, ref_price: pd.Series, vol_window: int,
           asset_vol: float, max_lev: float, cost_ticks: float):
    """Vol-targeted sleeve for one block, with cost charged in ticks per round trip.

    exposure is a fraction of equity per index point; sizing uses the lagged point
    vol and lagged price, so block-t return uses nothing realized inside block t.
    Cost in points = TICK * cost_ticks is subtracted from the harvested move, which
    is equivalent to charging it per contract at any position size.
    """
    pvol = point_move.rolling(vol_window, min_periods=vol_window).std(ddof=0).shift(1)
    prev_price = ref_price.shift(1).abs()
    exposure = (asset_vol / np.sqrt(252)) / pvol
    notional = (exposure * prev_price).clip(0.0, max_lev)
    exposure = (notional / prev_price.replace(0.0, np.nan)).where(prev_price.ne(0.0), exposure)

    gross = (exposure * point_move).fillna(0.0)
    net = (exposure * (point_move - TICK * cost_ticks)).fillna(0.0)
    contracts = (exposure * 100_000.0 / POINT_VALUE)  # informational, at $100k equity
    return gross, net, exposure, contracts


def tstat(x: pd.Series) -> float:
    x = x.dropna()
    return float(x.mean() / x.std(ddof=1) * np.sqrt(len(x))) if len(x) > 2 else np.nan


def main() -> None:
    ap = argparse.ArgumentParser(description="Overnight drift on real MNQ 6h bars.")
    ap.add_argument("--csv", default=str(CSV))
    ap.add_argument("--balance", type=float, default=100_000.0)
    ap.add_argument("--start", default=None)
    ap.add_argument("--end", default=None)
    ap.add_argument("--vol-window", type=int, default=60)
    ap.add_argument("--asset-vol", type=float, default=0.20)
    ap.add_argument("--max-leverage", type=float, default=2.0)
    ap.add_argument("--cost-ticks", type=float, default=1.0,
                    help="round-trip cost in ticks (1 tick = 0.25pt = $0.50)")
    args = ap.parse_args()

    w = load_blocks(Path(args.csv))
    win = w.copy()
    if args.start:
        win = win[win.index >= pd.Timestamp(args.start)]
    if args.end:
        win = win[win.index <= pd.Timestamp(args.end)]

    print("\nOVERNIGHT DRIFT | REAL MNQ FUTURES (back-adjusted, 6h bars)")
    print("=" * 84)
    print(f"Period: {win.index[0].date()} -> {win.index[-1].date()} "
          f"({len(win):,} sessions) | ${POINT_VALUE:.0f}/pt, {TICK}pt tick")
    print(f"Vol target {args.asset_vol:.0%} | max {args.max_leverage:.1f}x | "
          f"vol window {args.vol_window} | round-trip cost {args.cost_ticks:g} ticks "
          f"({TICK*args.cost_ticks:.2f} pt = ${TICK*args.cost_ticks*POINT_VALUE:.2f}/contract)\n")

    # ---- raw attribution: where does the return actually live? -----------------
    print("RAW POINT ATTRIBUTION (no sizing, no cost) — 1 contract held every session")
    print(f"{'block':<16}{'tot pts':>10}{'$P&L':>11}{'mean':>8}{'sd':>8}{'t-stat':>8}{'hit%':>7}")
    for key, label in [(f"blk_{h}", BLOCKS[h]) for h in (18, 0, 6, 12)] + \
                      [("overnight", "OVERNIGHT 18-06"), ("day", "DAY 06-18"), ("full", "FULL 24h")]:
        s = win[key]
        print(f"{label:<16}{s.sum():>10,.0f}{s.sum()*POINT_VALUE:>11,.0f}{s.mean():>8.2f}"
              f"{s.std():>8.1f}{tstat(s):>8.2f}{(s > 0).mean()*100:>7.1f}")

    # ---- vol-targeted sleeves --------------------------------------------------
    sleeves = {}
    for key in ("overnight", "day", "full"):
        g, n, e, c = sleeve(w[key], w["ref_price"], args.vol_window,
                            args.asset_vol, args.max_leverage, args.cost_ticks)
        sleeves[key] = {"gross": g.loc[win.index], "net": n.loc[win.index],
                        "exp": e.loc[win.index], "contracts": c.loc[win.index]}

    print(f"\nVOL-TARGETED SLEEVES (${args.balance:,.0f} equity)")
    print(line("Overnight (net)", perf(sleeves["overnight"]["net"], args.balance)))
    print(line("Overnight (gross)", perf(sleeves["overnight"]["gross"], args.balance)))
    print(line("Full 24h buy&hold", perf(sleeves["full"]["net"], args.balance)))
    print(line("Day only (net)", perf(sleeves["day"]["net"], args.balance)))
    med_c = sleeves["overnight"]["contracts"].median()
    print(f"\n  median size: {med_c:.1f} MNQ contracts "
          f"(~${med_c*win['ref_price'].median()*POINT_VALUE:,.0f} notional on ${args.balance:,.0f})")

    # ---- cost sensitivity, in the unit that matters for a real contract --------
    print("\nCOST SENSITIVITY (overnight sleeve)")
    print(f"{'ticks RT':<10}{'$/contract':>12}{'~bps':>8}{'Sharpe':>9}{'CAGR':>8}")
    px = win["ref_price"].median()
    for t in (0.0, 0.5, 1.0, 2.0, 4.0, 8.0):
        _, n, _, _ = sleeve(w["overnight"], w["ref_price"], args.vol_window,
                            args.asset_vol, args.max_leverage, t)
        s = perf(n.loc[win.index], args.balance)
        print(f"{t:<10.1f}{TICK*t*POINT_VALUE:>12.2f}{TICK*t/px*1e4:>8.2f}"
              f"{s['sharpe']:>9.2f}{s['cagr']*100:>7.1f}%")

    # ---- calendar --------------------------------------------------------------
    print("\nCALENDAR RETURNS (%)")
    cal = pd.DataFrame({"Overnight": sleeves["overnight"]["net"],
                        "Full24h": sleeves["full"]["net"],
                        "Day": sleeves["day"]["net"]})
    cal = cal.groupby(cal.index.year).apply(lambda f: (1 + f).prod() - 1)
    print((cal * 100).round(2).to_string())

    # ---- weekend-hold check ---------------------------------------------------
    # A session is anchored at 18:00, so the session dated Sunday is *Monday's*
    # trading day and its overnight block carries the Fri-close -> Sun-open gap.
    TRADING_DAY = {6: "Mon (wknd)", 0: "Tue", 1: "Wed", 2: "Thu", 3: "Fri"}
    print("\nOVERNIGHT BY TRADING DAY (session anchored 18:00; Sun session = Mon's day)")
    print(f"{'day':<12}{'n':>6}{'tot pts':>10}{'mean':>8}{'t-stat':>8}{'hit%':>7}{'net Shp':>9}")
    for dow in (6, 0, 1, 2, 3):
        m = win["dow"] == dow
        s = win.loc[m, "overnight"]
        if not len(s):
            continue
        only = sleeves["overnight"]["net"].where(m, 0.0)
        print(f"{TRADING_DAY[dow]:<12}{len(s):>6}{s.sum():>10,.0f}{s.mean():>8.2f}"
              f"{tstat(s):>8.2f}{(s > 0).mean()*100:>7.1f}{perf(only, args.balance)['sharpe']:>9.2f}")
    ex_wknd = sleeves["overnight"]["net"].where(win["dow"] != 6, 0.0)
    print("\n  " + line("ON ex-weekend hold", perf(ex_wknd, args.balance)))
    print("  " + line("ON weekend only", perf(
        sleeves["overnight"]["net"].where(win["dow"] == 6, 0.0), args.balance)))


if __name__ == "__main__":
    main()
