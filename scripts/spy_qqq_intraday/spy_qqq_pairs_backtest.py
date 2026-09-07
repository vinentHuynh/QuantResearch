"""Intraday SPY-QQQ pairs (relative value) on cached 5-min RTH bars, 2024->now.

Market-neutral by construction: trade the log price ratio log(QQQ)-log(SPY),
fading its rolling z-score. When the ratio is stretched high (QQQ rich vs SPY),
SHORT QQQ / LONG SPY; when stretched low, the reverse. Dollar-neutral (0.5 each
leg), flat overnight and flat by the close. A market crash hits both legs, so
directional drawdown is hedged out -- the point of the exercise.

Signal is decided at bar close and earned on the NEXT bar (position lagged), so
no look-ahead. Overnight gaps are removed from returns and no position is held
across the close.

Usage: python spy_qqq_pairs_backtest.py --cost-bps 1.0 --start 2024-01-01
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from pwb_toolbox.performance.metrics import (
    sharpe_ratio, annualized_volatility, cagr, max_drawdown,
)

DATA = Path(__file__).with_name("data")


def load(sym):
    df = pd.read_parquet(DATA / f"{sym}_5min.parquet")
    df.index = pd.to_datetime(df.index)
    return df.sort_index().between_time("09:30", "15:59")["close"].astype(float)


def run(spy, qqq, W, z_entry, z_exit, cost):
    """Return (daily_ret Series, n_trades, pct_in_mkt, beta_vs_spy)."""
    df = pd.concat({"spy": spy, "qqq": qqq}, axis=1).dropna()
    day = df.index.normalize()
    first_of_day = day != np.roll(day, 1)
    first_of_day[0] = True
    last_of_day = day != np.roll(day, -1)
    last_of_day[-1] = True

    s = np.log(df["qqq"]) - np.log(df["spy"])          # log price ratio
    m = s.rolling(W).mean()
    sd = s.rolling(W).std(ddof=0)
    z = ((s - m) / sd).to_numpy()

    n = len(df)
    pos = np.zeros(n)
    p = 0.0
    for i in range(n):
        if first_of_day[i]:
            p = 0.0                                     # start each day flat
        zi = z[i]
        if not np.isnan(zi):
            if p == 0.0:
                if zi >= z_entry:
                    p = -1.0                            # ratio high -> short QQQ/long SPY
                elif zi <= -z_entry:
                    p = 1.0                             # ratio low  -> long QQQ/short SPY
            elif p == 1.0 and zi >= -z_exit:
                p = 0.0
            elif p == -1.0 and zi <= z_exit:
                p = 0.0
        if last_of_day[i]:
            p = 0.0                                     # flat by the close
        pos[i] = p

    r_spy = df["spy"].pct_change().to_numpy()
    r_qqq = df["qqq"].pct_change().to_numpy()
    r_spy[first_of_day] = 0.0                           # drop overnight gaps
    r_qqq[first_of_day] = 0.0
    spread_ret = 0.5 * r_qqq - 0.5 * r_spy             # return of long-QQQ/short-SPY unit

    held = np.concatenate([[0.0], pos[:-1]])
    held[first_of_day] = 0.0                            # no carry across the night
    gross = held * spread_ret
    turnover = np.abs(np.diff(np.concatenate([[0.0], pos])))
    cost_arr = turnover * cost                          # $1 gross per unit, cost per side
    net = gross - cost_arr

    # reversion = fade the ratio (held as built); momentum = same timing, flipped
    net_rev = gross - cost_arr
    net_mom = -gross - cost_arr
    out = pd.DataFrame({"rev": net_rev, "mom": net_mom, "r_spy": r_spy},
                       index=df.index)
    g = out.groupby(out.index.normalize())
    d_rev = g.apply(lambda x: (1 + x["rev"]).prod() - 1)
    d_mom = g.apply(lambda x: (1 + x["mom"]).prod() - 1)
    d_spy = g.apply(lambda x: (1 + x["r_spy"]).prod() - 1)
    trades = int(((pos != 0) & (np.concatenate([[0.0], pos[:-1]]) == 0)).sum())
    pct_in = float((held != 0).mean())
    j = pd.concat({"m": d_mom, "b": d_spy}, axis=1).dropna()
    beta_mom = np.cov(j["m"], j["b"])[0, 1] / np.var(j["b"]) if len(j) > 5 else np.nan
    return d_rev, d_mom, trades, pct_in, beta_mom


def stats(nav):
    depth, _ = max_drawdown(nav)
    return sharpe_ratio(nav), cagr(nav), annualized_volatility(nav), abs(depth)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--balance", type=float, default=100_000)
    ap.add_argument("--start", type=str, default="2024-01-01")
    ap.add_argument("--cost-bps", type=float, default=1.0)
    args = ap.parse_args()
    cost = args.cost_bps / 1e4
    start = pd.Timestamp(args.start)

    spy, qqq = load("SPY"), load("QQQ")
    print(f"\nIntraday SPY-QQQ pairs (market-neutral) | 5-min | "
          f"{spy.index.min().date()}->{spy.index.max().date()} | "
          f"cost {args.cost_bps}bps/side | ${args.balance:,.0f}\n")
    hdr = (f"{'W/entry/exit':<15}{'Trades':>7}{'%inMkt':>8}"
           f"{'RevShrp':>9}{'MomShrp':>9}{'MomCAGR':>9}{'MomDD':>8}{'MomBeta':>9}{'MomEnd$':>12}")
    print(hdr); print("-" * len(hdr))

    configs = [(40, 2.0, 0.5), (40, 1.5, 0.5), (40, 2.5, 0.5),
               (20, 2.0, 0.5), (60, 2.0, 0.5)]
    for W, ze, zx in configs:
        d_rev, d_mom, trades, pct_in, beta_mom = run(spy, qqq, W, ze, zx, cost)
        d_rev, d_mom = d_rev[d_rev.index >= start], d_mom[d_mom.index >= start]
        sh_rev = stats((args.balance * (1 + d_rev).cumprod()).tolist())[0]
        nav_m = args.balance * (1 + d_mom).cumprod()
        sh_m, cg_m, vol_m, dd_m = stats(nav_m.tolist())
        print(f"{f'{W}/{ze}/{zx}':<15}{trades:>7}{pct_in*100:>7.0f}%"
              f"{sh_rev:>9.2f}{sh_m:>9.2f}{cg_m*100:>8.1f}%{dd_m*100:>7.1f}%"
              f"{beta_mom:>9.2f}{nav_m.iloc[-1]:>12,.0f}")


if __name__ == "__main__":
    main()
