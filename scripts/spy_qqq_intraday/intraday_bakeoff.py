"""Intraday strategy bake-off on cached SPY/QQQ 5-min RTH bars (2024->now).

Each strategy -> per-session net return -> 50/50 portfolio -> NAV. Costs modeled
per side (bps). Flat overnight except the overnight-drift track. Same caveats:
SPY/QQQ proxy for ES/NQ, no futures leverage/roll/margin.

Usage: python intraday_bakeoff.py --cost-bps 1.0 --start 2024-01-01
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from pwb_toolbox.performance.metrics import (
    sharpe_ratio, annualized_volatility, cagr, max_drawdown,
)

DATA = Path(__file__).with_name("data")
SYMS = ["SPY", "QQQ"]


def load(sym):
    df = pd.read_parquet(DATA / f"{sym}_5min.parquet")
    df.index = pd.to_datetime(df.index)
    return df.sort_index().between_time("09:30", "15:59")


# ---- strategies: return (gross daily Series, net daily Series, n_trades) ------
def s_overnight(df, cost):
    g = df.groupby(df.index.normalize())
    op, cl = g["open"].first(), g["close"].last()
    on = op / cl.shift(1) - 1               # buy prior close, sell open
    gross = on.dropna()
    net = gross - 2 * cost
    return gross, net, len(net)


def s_intraday(df, cost):
    g = df.groupby(df.index.normalize())
    op, cl = g["open"].first(), g["close"].last()
    gross = (cl / op - 1).dropna()
    net = gross - 2 * cost
    return gross, net, len(net)


def s_buyhold(df, cost):
    g = df.groupby(df.index.normalize())
    cl = g["close"].last()
    gross = cl.pct_change().dropna()
    return gross, gross, 0                  # hold: no per-day cost


def s_gap_fade(df, cost, thr=0.003):
    g = df.groupby(df.index.normalize())
    op, cl = g["open"].first(), g["close"].last()
    hi, lo = g["high"].max(), g["low"].min()
    prev = cl.shift(1)
    gap = op / prev - 1
    trade = gap.abs() > thr
    ret = pd.Series(0.0, index=op.index)
    # gap DOWN -> long, target prev close (above); reach if hi>=prev
    dn = trade & (gap < 0)
    ret[dn] = np.where(hi[dn] >= prev[dn], prev[dn] / op[dn] - 1, cl[dn] / op[dn] - 1)
    # gap UP -> short, target prev close (below); reach if lo<=prev
    up = trade & (gap > 0)
    ret[up] = np.where(lo[up] <= prev[up], (op[up] - prev[up]) / op[up], (op[up] - cl[up]) / op[up])
    gross = ret.dropna()
    net = gross.copy()
    net[trade.reindex(net.index).fillna(False)] -= 2 * cost
    return gross, net, int(trade.sum())


def s_last_hour(df, cost):
    at3 = df.between_time("15:00", "15:00")["close"]
    at3.index = at3.index.normalize()
    g = df.groupby(df.index.normalize())
    op, cl = g["open"].first(), g["close"].last()
    day_move = at3 / op - 1
    direction = np.sign(day_move)
    gross = (direction * (cl / at3 - 1)).dropna()
    net = gross - 2 * cost
    return gross, net, len(net)


def s_orb_long(df, cost):
    rows = []
    for day, gday in df.groupby(df.index.normalize()):
        gday = gday.sort_index()
        if len(gday) < 3:
            continue
        first, rest = gday.iloc[0], gday.iloc[1:]
        if first["close"] <= first["open"]:   # long-only: skip down opens
            rows.append((day, 0.0, False)); continue
        entry, stop = rest["open"].iloc[0], first["low"]
        exit_px = rest["close"].iloc[-1]
        for _, b in rest.iterrows():
            if b["low"] <= stop:
                exit_px = stop; break
        rows.append((day, exit_px / entry - 1, True))
    s = pd.DataFrame(rows, columns=["day", "r", "t"]).set_index("day")
    gross = s["r"]
    net = gross - s["t"].astype(float) * 2 * cost
    return gross, net, int(s["t"].sum())


def s_vwap_rev(df, cost, band=0.002):
    daily_net, daily_gross = {}, {}
    ntr = 0
    for day, gday in df.groupby(df.index.normalize()):
        gday = gday.sort_index()
        tp = (gday["high"] + gday["low"] + gday["close"]) / 3
        pv = (tp * gday["volume"]).cumsum()
        vol = gday["volume"].cumsum().replace(0, np.nan)
        vwap = pv / vol
        dev = (gday["close"] / vwap - 1).values
        n = len(gday)
        pos = np.zeros(n)
        p = 0.0
        for i in range(n):
            d = dev[i]
            if np.isnan(d):
                pos[i] = p; continue
            if p == 0:
                p = 1.0 if d < -band else (-1.0 if d > band else 0.0)
            elif p == 1 and d >= 0:
                p = 0.0
            elif p == -1 and d <= 0:
                p = 0.0
            pos[i] = p
        bar_ret = gday["close"].pct_change().fillna(0.0).values
        held = np.concatenate([[0.0], pos[:-1]])
        gr = held * bar_ret
        turn = np.abs(np.diff(np.concatenate([[0.0], pos])))
        cst = turn * cost
        ntr += int((turn > 0).sum())
        daily_gross[day] = float(np.prod(1 + gr) - 1)
        daily_net[day] = float(np.prod(1 + (gr - cst)) - 1)
    gross = pd.Series(daily_gross).sort_index()
    net = pd.Series(daily_net).sort_index()
    return gross, net, ntr


STRATS = {
    "Overnight drift": s_overnight,
    "VWAP reversion": s_vwap_rev,
    "Gap fade": s_gap_fade,
    "Last-hour momentum": s_last_hour,
    "ORB long-only": s_orb_long,
    "Intraday (open->close)": s_intraday,
    "Buy & hold": s_buyhold,
}


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

    data = {s: load(s) for s in SYMS}
    rng = data["SPY"].index
    print(f"\nIntraday bake-off | SPY+QQQ 5-min 50/50 | {rng.min().date()}->"
          f"{rng.max().date()} | cost {args.cost_bps}bps/side | ${args.balance:,.0f}\n")
    hdr = (f"{'Strategy':<24}{'Trades':>7}{'GrShrp':>8}{'NetShrp':>8}"
           f"{'CAGR':>8}{'Vol':>7}{'MaxDD':>8}{'End$':>12}")
    print(hdr); print("-" * len(hdr))

    rows = []
    for name, fn in STRATS.items():
        per_sym_net, per_sym_gross, trades = [], [], 0
        for s in SYMS:
            gr, net, nt = fn(data[s], cost)
            per_sym_gross.append(gr); per_sym_net.append(net); trades += nt
        net = pd.concat(per_sym_net, axis=1).fillna(0.0)
        net = net[net.index >= start].mean(axis=1)
        gr = pd.concat(per_sym_gross, axis=1).fillna(0.0)
        gr = gr[gr.index >= start].mean(axis=1)
        nav = args.balance * (1 + net).cumprod()
        gsh, _, _, _ = stats((args.balance * (1 + gr).cumprod()).tolist())
        nsh, cg, vol, dd = stats(nav.tolist())
        rows.append((name, trades, gsh, nsh, cg, vol, dd, nav.iloc[-1]))

    for name, tr, gsh, nsh, cg, vol, dd, end in sorted(rows, key=lambda r: -r[3]):
        print(f"{name:<24}{tr:>7}{gsh:>8.2f}{nsh:>8.2f}"
              f"{cg*100:>7.1f}%{vol*100:>6.1f}%{dd*100:>7.1f}%{end:>12,.0f}")


if __name__ == "__main__":
    main()
