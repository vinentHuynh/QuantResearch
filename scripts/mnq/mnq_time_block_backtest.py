"""Backtest each 6-hour clock block of the MNQ session as its own strategy.

Follow-up to `mnq_overnight_drift_backtest.py`, which split the day into four 6h
blocks using a 4.6-year TradingView export and could only do raw attribution. This
runs the same blocks as *tradeable sleeves* on Databento 5-min MNQ back to 2020,
so every block gets a real equity curve, cost charge, drawdown and t-stat over
6.6 years instead of 4.6.

    18:00 -> 00:00  Asia
    00:00 -> 06:00  London
    06:00 -> 12:00  NY am   (contains the 09:30 RTH open)
    12:00 -> 18:00  NY pm   (contains the 16:00 RTH close)

Each block is entered at its first print and exited at its last, long-only, one
round trip per session. Aggregates: OVERNIGHT = 18:00->06:00, DAY = 06:00->18:00,
FULL = 18:00->18:00.

Data notes. Databento continuous is *unadjusted*, so contract rolls show up as
level jumps -- but 81 of the 92 jumps >60pts sit exactly at the 18:00 boundary,
and block returns run first-open -> last-close *inside* a block, so roll and
weekend gaps fall between blocks and are never harvested. That also means no
sleeve here holds through the Friday->Sunday gap: the Asia block buys at the
Sunday reopen, after it. Returns are still winsorized at 0.5/99.5% for the risk
stats (house convention, matches futures_overnight_backtest.py) with raw worst
nights printed separately so real news gaps stay visible.

Costs are charged in TICKS (MNQ: 0.25pt tick = $0.50, $2/point).

    python mnq_time_block_backtest.py
    python mnq_time_block_backtest.py --ticks 2 --start 2023-01-01
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from pwb_toolbox.performance.metrics import (
    sharpe_ratio, annualized_volatility, cagr, max_drawdown,
)

DATA = (Path(__file__).resolve().parents[2] / "data")
SPECS = {"MNQ": (0.25, 2.0), "MES": (0.25, 5.0)}
BLOCK_NAMES = {0: "Asia 18-00", 1: "London 00-06", 2: "NY am 06-12", 3: "NY pm 12-18"}
MIN_BARS = 30          # of 72 possible 5-min bars; drops holidays and half sessions


def load_blocks(sym: str, min_bars: int) -> pd.DataFrame:
    """One row per 18:00-anchored session, first-open/last-close per 6h block."""
    df = pd.read_parquet(DATA / f"{sym}_5min_databento.parquet").sort_index()
    idx = df.index
    sess = (idx - pd.Timedelta(hours=18)).normalize()
    blk = ((idx.hour - 18) % 24) // 6
    g = df.groupby([sess, blk])
    cell = pd.DataFrame({"open": g["open"].first(), "close": g["close"].last(),
                         "n": g.size()})
    cell = cell[cell["n"] >= min_bars]
    wide = cell.unstack(level=-1)
    wide.columns = [f"{v}_{b}" for v, b in wide.columns]
    need = [f"{v}_{b}" for v in ("open", "close") for b in BLOCK_NAMES]
    wide = wide.dropna(subset=need).sort_index()
    wide.index = pd.DatetimeIndex(wide.index).tz_localize(None)
    return wide


def tracks(wide: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Per-track entry price, exit price and point move (1 contract, long)."""
    spec = {**{BLOCK_NAMES[b]: (f"open_{b}", f"close_{b}") for b in BLOCK_NAMES},
            "OVERNIGHT 18-06": ("open_0", "close_1"),
            "DAY 06-18": ("open_2", "close_3"),
            "FULL 24h": ("open_0", "close_3")}
    return {k: pd.DataFrame({"entry": wide[o], "exit": wide[c],
                             "pts": wide[c] - wide[o]})
            for k, (o, c) in spec.items()}


def wins(s: pd.Series, lo=0.005, hi=0.995) -> pd.Series:
    return s.clip(s.quantile(lo), s.quantile(hi))


def sleeve(ret: pd.Series, cost: pd.Series, vol_window: int,
           target: float, max_lev: float) -> pd.Series:
    """Vol-targeted long-only sleeve; leverage uses lagged vol only."""
    lev = (target / np.sqrt(252)) / ret.rolling(vol_window, min_periods=vol_window).std(ddof=0)
    lev = lev.shift(1).clip(0.0, max_lev)
    return (lev * (ret - cost)).fillna(0.0)


def stats(r: pd.Series, balance: float) -> dict:
    nav = (balance * (1 + r.fillna(0.0)).cumprod())
    norm = (nav / balance).tolist()
    depth, _ = max_drawdown(norm)
    return {"sharpe": sharpe_ratio(norm), "cagr": cagr(norm),
            "vol": annualized_volatility(norm), "maxdd": abs(depth),
            "end": nav.iloc[-1]}


def tstat(x: pd.Series) -> float:
    x = x.dropna()
    return float(x.mean() / x.std(ddof=1) * np.sqrt(len(x))) if len(x) > 2 else np.nan


def main() -> None:
    ap = argparse.ArgumentParser(description="6h clock-block sleeves on real MNQ.")
    ap.add_argument("--symbol", default="MNQ", choices=sorted(SPECS))
    ap.add_argument("--ticks", type=float, default=1.0, help="round-trip cost in ticks")
    ap.add_argument("--start", default="2020-01-02")
    ap.add_argument("--end", default=None)
    ap.add_argument("--balance", type=float, default=100_000.0)
    ap.add_argument("--vol-window", type=int, default=60)
    ap.add_argument("--target-vol", type=float, default=0.20)
    ap.add_argument("--max-leverage", type=float, default=2.0)
    args = ap.parse_args()

    tick, dpp = SPECS[args.symbol]
    wide = load_blocks(args.symbol, MIN_BARS)
    wide = wide[wide.index >= pd.Timestamp(args.start)]
    if args.end:
        wide = wide[wide.index <= pd.Timestamp(args.end)]
    tr = tracks(wide)
    cost_pts = args.ticks * tick

    print(f"\n{args.symbol} 6-HOUR CLOCK BLOCKS AS STANDALONE SLEEVES (Databento 5-min)")
    print("=" * 92)
    print(f"Period: {wide.index[0].date()} -> {wide.index[-1].date()} "
          f"({len(wide):,} sessions) | ${dpp:.0f}/pt, {tick}pt tick")
    print(f"Cost {args.ticks:g} tick RT ({cost_pts:.2f}pt = ${cost_pts*dpp:.2f}/contract) | "
          f"vol target {args.target_vol:.0%}, max {args.max_leverage:.1f}x, "
          f"{args.vol_window}-session window\n")

    order = [BLOCK_NAMES[b] for b in range(4)] + ["OVERNIGHT 18-06", "DAY 06-18", "FULL 24h"]

    # ---- raw, 1 contract, no sizing -------------------------------------------
    print("RAW: 1 CONTRACT HELD EVERY SESSION (no sizing, no cost)")
    print(f"{'track':<16}{'tot pts':>10}{'$P&L':>11}{'mean$':>8}{'sd$':>8}"
          f"{'t-stat':>8}{'hit%':>7}{'worst$':>9}")
    for k in order:
        p = tr[k]["pts"].dropna()
        print(f"{k:<16}{p.sum():>10,.0f}{p.sum()*dpp:>11,.0f}{p.mean()*dpp:>8.1f}"
              f"{p.std()*dpp:>8.0f}{tstat(p):>8.2f}{(p > 0).mean()*100:>7.1f}"
              f"{p.min()*dpp:>9,.0f}")

    # ---- vol-targeted, net of cost --------------------------------------------
    nets = {}
    print(f"\nVOL-TARGETED SLEEVES, NET (${args.balance:,.0f} equity)")
    print(f"{'track':<16}{'Sharpe':>8}{'CAGR':>9}{'Vol':>7}{'MaxDD':>8}{'end $':>13}")
    for k in order:
        t = tr[k]
        ret = wins((t["exit"] / t["entry"] - 1).dropna())
        cost = (cost_pts / t["entry"]).reindex(ret.index)
        nets[k] = sleeve(ret, cost, args.vol_window, args.target_vol, args.max_leverage)
        s = stats(nets[k], args.balance)
        print(f"{k:<16}{s['sharpe']:>8.2f}{s['cagr']*100:>8.1f}%{s['vol']*100:>6.1f}%"
              f"{s['maxdd']*100:>7.1f}%{s['end']:>13,.0f}")

    # ---- regime stability: does any block survive out of its own half? --------
    mid = wide.index[len(wide) // 2]
    print(f"\nSPLIT-SAMPLE Sharpe (first half -> {mid.date()} -> second half)")
    print(f"{'track':<16}{'1st half':>10}{'2nd half':>10}{'full':>8}")
    for k in order:
        r = nets[k]
        a, b = r[r.index <= mid], r[r.index > mid]
        print(f"{k:<16}{stats(a, args.balance)['sharpe']:>10.2f}"
              f"{stats(b, args.balance)['sharpe']:>10.2f}"
              f"{stats(r, args.balance)['sharpe']:>8.2f}")

    # ---- calendar --------------------------------------------------------------
    print("\nCALENDAR RETURNS (%, net)")
    cal = pd.DataFrame({k: nets[k] for k in order})
    cal = cal.groupby(cal.index.year).apply(lambda f: (1 + f).prod() - 1)
    print((cal * 100).round(1).to_string())

    # ---- cost sweep ------------------------------------------------------------
    print("\nTICK-COST SWEEP (Sharpe)")
    print(f"{'track':<16}" + "".join(f"{t:>8}" for t in (0, 1, 2, 4, 8)))
    for k in order:
        t = tr[k]
        ret = wins((t["exit"] / t["entry"] - 1).dropna())
        row = f"{k:<16}"
        for tk in (0, 1, 2, 4, 8):
            c = (tk * tick / t["entry"]).reindex(ret.index)
            row += f"{stats(sleeve(ret, c, args.vol_window, args.target_vol, args.max_leverage), args.balance)['sharpe']:>8.2f}"
        print(row)

    # ---- prop-account tail: 1 contract, unsized --------------------------------
    print(f"\n1-CONTRACT TAIL ({args.symbol}, raw $)")
    print(f"{'track':<16}{'worst':>9}{'<-$250':>8}{'<-$500':>8}")
    for k in order:
        p = tr[k]["pts"].dropna() * dpp
        print(f"{k:<16}{p.min():>9,.0f}"
              + "".join(f"{(p < -lim).mean()*100:>7.1f}%" for lim in (250, 500)))


if __name__ == "__main__":
    main()
