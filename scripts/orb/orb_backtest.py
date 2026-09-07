"""Opening-Range Breakout (ORB) on SPY/QQQ 5-min bars. Intraday, flat by close.

Reads local 5-min parquet from fetch_intraday.py (data/{SYM}_5min.parquet).

Rules (per session, one trade/day):
  - Opening range = first `--or-min` minutes of the regular session.
  - Direction = sign of the opening range (last OR close vs first OR open).
  - Entry = open of the first bar AFTER the opening range, in that direction.
  - Stop  = opposite extreme of the opening range (long: OR low, short: OR high).
  - Exit  = stop hit intraday, else the session's last bar close (EOD).
  - Costs = --cost-bps per side (spread+commission), charged on entry and exit.

Return per trade is on full notional (unlevered); daily return = that trade,
0 otherwise. Reports gross and net, plus buy&hold over the same window.

Usage: python orb_backtest.py --start 2024-01-01 --or-min 5 --cost-bps 1.0
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from pwb_toolbox.performance.metrics import (
    sharpe_ratio, annualized_volatility, cagr, max_drawdown,
)

DATA = (Path(__file__).resolve().parents[2] / "data")
RTH_START, RTH_END = "09:30", "16:00"   # regular session (Eastern), assumes ET bars


def load_5min(sym: str) -> pd.DataFrame:
    df = pd.read_parquet(DATA / f"{sym}_5min.parquet")
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)
    # if tz-aware, convert to US/Eastern; if naive, assume already Eastern
    if df.index.tz is not None:
        df.index = df.index.tz_convert("US/Eastern")
    df = df.between_time(RTH_START, "15:59")   # RTH only, drop 16:00 stub
    return df.sort_index()


def orb_daily_returns(df: pd.DataFrame, or_min: int, cost_bps: float):
    """Return (daily_ret Series, trades DataFrame) for one symbol."""
    cost = cost_bps / 1e4
    n_or = max(1, or_min // 5)              # number of 5-min bars in opening range
    rows = []
    for day, g in df.groupby(df.index.normalize()):
        g = g.sort_index()
        if len(g) < n_or + 2:
            continue
        orng = g.iloc[:n_or]
        rest = g.iloc[n_or:]
        or_hi, or_lo = orng["high"].max(), orng["low"].min()
        direction = np.sign(orng["close"].iloc[-1] - orng["open"].iloc[0])
        if direction == 0 or or_hi == or_lo:
            continue
        entry = rest["open"].iloc[0]
        stop = or_lo if direction > 0 else or_hi
        exit_px, exit_reason = rest["close"].iloc[-1], "eod"
        for _, bar in rest.iterrows():
            if direction > 0 and bar["low"] <= stop:
                exit_px, exit_reason = stop, "stop"
                break
            if direction < 0 and bar["high"] >= stop:
                exit_px, exit_reason = stop, "stop"
                break
        gross = direction * (exit_px / entry - 1)
        net = gross - 2 * cost
        risk = abs(entry - stop) / entry
        rows.append({
            "date": day, "dir": direction, "entry": entry, "stop": stop,
            "exit": exit_px, "reason": exit_reason,
            "gross": gross, "net": net,
            "R": (gross / risk) if risk > 0 else 0.0,
        })
    t = pd.DataFrame(rows).set_index("date")
    return t


def stats(nav):
    depth, _ = max_drawdown(nav)
    return sharpe_ratio(nav), cagr(nav), annualized_volatility(nav), abs(depth)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--balance", type=float, default=100_000)
    ap.add_argument("--start", type=str, default="2024-01-01")
    ap.add_argument("--end", type=str, default=None)
    ap.add_argument("--or-min", type=int, default=5, help="opening range minutes")
    ap.add_argument("--cost-bps", type=float, default=1.0, help="cost per side, bps")
    ap.add_argument("--symbols", type=str, default="SPY,QQQ")
    args = ap.parse_args()
    syms = args.symbols.split(",")
    start = pd.Timestamp(args.start)
    end = pd.Timestamp(args.end) if args.end else None

    trades = {}
    for s in syms:
        df = load_5min(s)
        # diagnostic once: confirm session detection
        tod = df.index.time
        print(f"[{s}] 5-min bars={len(df):,}  session {min(tod)}–{max(tod)}  "
              f"~{len(df)/max(1,df.index.normalize().nunique()):.0f} bars/day  "
              f"range {df.index.min().date()}->{df.index.max().date()}")
        t = orb_daily_returns(df, args.or_min, args.cost_bps)
        t = t[t.index >= start]
        if end is not None:
            t = t[t.index <= end]
        trades[s] = t

    print(f"\nORB {args.or_min}-min | {syms} | {args.start}->"
          f"{args.end or 'now'} | cost {args.cost_bps}bps/side\n")
    hdr = (f"{'Track':<20}{'Trades':>7}{'Win%':>7}{'AvgR':>7}"
           f"{'Sharpe':>8}{'CAGR':>8}{'MaxDD':>8}{'End$':>13}")
    print(hdr); print("-" * len(hdr))

    def report(name, t, ret_col):
        idx = t.index
        daily = t[ret_col]
        nav = args.balance * (1 + daily).cumprod()
        sh, cg, vol, dd = stats(nav.tolist())
        win = (t["gross"] > 0).mean() * 100
        print(f"{name:<20}{len(t):>7}{win:>6.1f}%{t['R'].mean():>7.2f}"
              f"{sh:>8.2f}{cg*100:>7.1f}%{dd*100:>7.1f}%{nav.iloc[-1]:>13,.0f}")

    # per symbol, gross and net
    for s in syms:
        report(f"{s} ORB gross", trades[s], "gross")
        report(f"{s} ORB net", trades[s], "net")

    # 50/50 combined net
    combo = pd.concat({s: trades[s]["net"] for s in syms}, axis=1).fillna(0.0)
    combo_ret = combo.mean(axis=1)
    nav = args.balance * (1 + combo_ret).cumprod()
    sh, cg, vol, dd = stats(nav.tolist())
    print("-" * len(hdr))
    print(f"{'50/50 ORB net':<20}{len(combo):>7}{'':>7}{'':>7}"
          f"{sh:>8.2f}{cg*100:>7.1f}%{dd*100:>7.1f}%{nav.iloc[-1]:>13,.0f}")

    # buy & hold benchmark over same window
    for s in syms:
        df = load_5min(s)
        daily_close = df["close"].resample("1D").last().dropna()
        daily_close = daily_close[(daily_close.index >= start)]
        if end is not None:
            daily_close = daily_close[daily_close.index <= end]
        bh = args.balance * (daily_close / daily_close.iloc[0])
        sh, cg, vol, dd = stats(bh.tolist())
        print(f"{s+' buy&hold':<20}{'':>7}{'':>7}{'':>7}"
              f"{sh:>8.2f}{cg*100:>7.1f}%{dd*100:>7.1f}%{bh.iloc[-1]:>13,.0f}")


if __name__ == "__main__":
    main()
