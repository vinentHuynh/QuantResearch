"""Overnight-drift on REAL CME futures (Databento 5-min) with tick-based costs.

Long the Globex overnight (RTH close -> next RTH open), flat during the RTH day.
Uses the actual overnight session, not a close->open proxy. Costs charged in
TICKS (a 1-tick round trip), the honest way for futures. Reports overnight vs
intraday vs full-day-hold, a tick cost sweep, the t-stat, and the per-1-contract
overnight dollar P&L distribution for fixed-contract tail analysis.

Data is Databento continuous (unadjusted), so roll days create spurious level
jumps; daily returns are winsorized at 0.5/99.5% to remove those. The RAW worst
overnight nights are printed separately so real news gaps stay visible.

    python futures_overnight_backtest.py --symbols MES,MNQ --ticks 1
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from pwb_toolbox.performance.metrics import (
    sharpe_ratio, annualized_volatility, cagr, max_drawdown,
)

DATA = (Path(__file__).resolve().parents[2] / "data")
# root -> (tick size in points, $ per point)
SPECS = {"MES": (0.25, 5.0), "MNQ": (0.25, 2.0), "ES": (0.25, 50.0),
         "NQ": (0.25, 20.0), "CL": (0.01, 1000.0), "GC": (0.10, 100.0)}
RTH = ("09:30", "15:59")


def load(sym):
    df = pd.read_parquet(DATA / f"{sym}_5min_databento.parquet")
    df.index = pd.to_datetime(df.index)
    return df.sort_index()


def sessions(df):
    rth = df.between_time(*RTH)
    g = rth.groupby(rth.index.normalize())
    o = g["open"].first()
    c = g["close"].last()
    return pd.DataFrame({"open": o, "close": c}).dropna()


def stats(nav):
    depth, _ = max_drawdown(nav)
    return sharpe_ratio(nav), cagr(nav), annualized_volatility(nav), abs(depth)


def wins(s, lo=0.005, hi=0.995):
    return s.clip(s.quantile(lo), s.quantile(hi))


def run(sym, ticks, start):
    tick, dpp = SPECS[sym]
    s = sessions(load(sym))
    s = s[s.index >= pd.Timestamp(start).tz_localize(s.index.tz)]
    prev_c = s["close"].shift(1)
    on_pts = s["open"] - prev_c                     # overnight point move (1 contract)
    on_ret = wins((s["open"] / prev_c - 1).dropna())
    id_ret = wins((s["close"] / s["open"] - 1).dropna())
    bh_ret = wins((s["close"] / prev_c - 1).dropna())
    cost = ticks * tick                             # round-trip cost in points
    on_cost = (cost / prev_c).reindex(on_ret.index)
    id_cost = (cost / s["open"]).reindex(id_ret.index)
    on_net = (on_ret - on_cost).dropna()
    id_net = (id_ret - id_cost).dropna()
    return sym, tick, dpp, on_net, id_net, bh_ret, on_pts.dropna()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default="MES,MNQ")
    ap.add_argument("--ticks", type=float, default=1.0, help="round-trip cost in ticks")
    ap.add_argument("--start", default="2024-08-12")
    ap.add_argument("--balance", type=float, default=100_000)
    args = ap.parse_args()
    syms = [s.strip().upper() for s in args.symbols.split(",")]

    print(f"\nOVERNIGHT DRIFT on REAL CME FUTURES (Databento) | cost {args.ticks} tick RT | "
          f"from {args.start}\n")
    hdr = f"{'Sym  track':<16}{'Sharpe':>8}{'CAGR':>8}{'Vol':>7}{'MaxDD':>8}{'t-stat':>8}"
    print(hdr); print("-" * len(hdr))

    for sym in syms:
        sym, tick, dpp, on_net, id_net, bh_ret, on_pts = run(sym, args.ticks, args.start)

        def rep(tag, r):
            nav = (args.balance * (1 + r).cumprod()).tolist()
            sh, cg, vol, dd = stats(nav)
            t = r.mean() / (r.std(ddof=0) / np.sqrt(len(r))) if r.std(ddof=0) > 0 else np.nan
            print(f"{sym+' '+tag:<16}{sh:>8.2f}{cg*100:>7.1f}%{vol*100:>6.1f}%{dd*100:>7.1f}%{t:>8.2f}")

        rep("overnight", on_net)
        rep("intraday", id_net)
        rep("buy&hold", bh_ret)

        # Dollar P&L of holding ONE contract overnight.
        pnl = on_pts * dpp                          # $ per 1 contract per night
        worst = pnl.nsmallest(5)
        print(f"   1-contract overnight $P&L: mean ${pnl.mean():+.1f}/night  "
              f"std ${pnl.std():.0f}  worst ${pnl.min():.0f}")
        for lim in (250, 500):
            frac = (pnl < -lim).mean() * 100
            print(f"     nights worse than -${lim}: {frac:.1f}%  "
                  f"({int((pnl < -lim).sum())} of {len(pnl)})")
        print(f"   worst 5 nights (raw, incl. any roll days): "
              f"{', '.join(f'${x:.0f}' for x in worst)}")
        print()

    # tick cost sweep on overnight
    print("OVERNIGHT tick-cost sweep (Sharpe)")
    print(f"{'ticks RT':<10}" + "".join(f"{s:>9}" for s in syms))
    for tk in (0, 1, 2, 4, 8):
        row = f"{tk:<10}"
        for sym in syms:
            _, _, _, on_net, _, _, _ = run(sym, tk, args.start)
            nav = (args.balance * (1 + on_net).cumprod()).tolist()
            row += f"{sharpe_ratio(nav):>9.2f}"
        print(row)


if __name__ == "__main__":
    main()
