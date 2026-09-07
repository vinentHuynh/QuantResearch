"""Bake-off: higher-Sharpe systematic strategies on ES (SPX) + NQ (NDX).

Same proxy caveat as es_nq_backtest.py: trades cash indices, GROSS of costs.
Overnight/RSI2/TOM trade often -> cost-sensitive; read Sharpe as an upper bound.

Each strategy -> daily return per instrument -> 50/50 portfolio -> NAV from
--balance. Signals lagged (no look-ahead). Reports full-period + OOS (>2015).

Usage: python es_nq_strategies.py --balance 100000
"""
import argparse
import os
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

_env = (Path(__file__).resolve().parents[2] / ".env")
if _env.exists():
    for _l in _env.read_text().splitlines():
        _l = _l.strip()
        if _l and not _l.startswith("#") and "=" in _l:
            _k, _v = _l.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

import pwb_toolbox.datasets as pwb_ds
from pwb_toolbox.performance.metrics import (
    sharpe_ratio, annualized_volatility, cagr, max_drawdown,
)

SYMBOLS = {"ES": "SPX", "NQ": "NDX"}
WARMUP = "2011-01-01"  # load from here so SMA200 etc. are warm by eval start


def load(sym: str) -> pd.DataFrame:
    df = pwb_ds.load_dataset("Indices-Daily-Price", symbols=[sym])
    df["date"] = pd.to_datetime(df["date"])
    df = df[df["date"] >= pd.Timestamp(WARMUP)].sort_values("date").set_index("date")
    return df[["open", "high", "low", "close"]].astype(float)


def rsi(close: pd.Series, n: int) -> pd.Series:
    d = close.diff()
    up = d.clip(lower=0).rolling(n).mean()
    dn = (-d.clip(upper=0)).rolling(n).mean()
    rs = up / dn.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


# --- strategy return generators: DataFrame(o,h,l,c) -> daily return series ----
def s_buyhold(df):
    return df["close"].pct_change().fillna(0.0)


def s_trend(df, w=200):
    c = df["close"]
    sig = (c > c.rolling(w).mean()).astype(float).shift(1)
    return (sig * c.pct_change()).fillna(0.0)


def s_overnight(df):
    return (df["open"] / df["close"].shift(1) - 1).fillna(0.0)


def s_intraday(df):
    return (df["close"] / df["open"] - 1).fillna(0.0)


def s_rsi2(df):
    c = df["close"]
    r = rsi(c, 2)
    sma = c.rolling(200).mean()
    enter = (r < 10) & (c > sma)
    exit_ = r > 70
    raw = pd.Series(np.where(enter, 1.0, np.where(exit_, 0.0, np.nan)), index=c.index)
    pos = raw.ffill().fillna(0.0).shift(1)
    return (pos * c.pct_change()).fillna(0.0)


def s_tom(df):
    c = df["close"]
    ret = c.pct_change()
    m = c.index.to_period("M")
    g = pd.Series(c.index, index=c.index).groupby(m)
    rank_first = g.cumcount()                       # 0,1,2,... within month
    rank_last = g.cumcount(ascending=False)         # ...,2,1,0
    hold = ((rank_first < 3) | (rank_last == 0)).astype(float)  # first 3 + last day
    return (hold.shift(1).fillna(0.0) * ret).fillna(0.0)


def s_voltrend(df, w=200, target=0.10, cap=1.5):
    c = df["close"]
    ret = c.pct_change()
    sig = (c > c.rolling(w).mean()).astype(float)
    rv = ret.rolling(20).std() * np.sqrt(252)
    lev = (target / rv).clip(0, cap)
    pos = (sig * lev).shift(1)
    return (pos * ret).fillna(0.0)


STRATS = {
    "Buy & hold": s_buyhold,
    "Trend SMA200": s_trend,
    "Overnight (close->open)": s_overnight,
    "Intraday (open->close)": s_intraday,
    "RSI(2) mean-rev": s_rsi2,
    "Turn-of-month": s_tom,
    "Vol-targeted trend": s_voltrend,
}


def stats(vals):
    depth, _ = max_drawdown(vals)
    return sharpe_ratio(vals), cagr(vals), annualized_volatility(vals), abs(depth)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--balance", type=float, default=100_000)
    ap.add_argument("--start", type=str, default="2024-01-01",
                    help="evaluation start (indicators warmed from 2022)")
    args = ap.parse_args()
    eval_start = pd.Timestamp(args.start)

    data = {name: load(sym) for name, sym in SYMBOLS.items()}
    common = data["ES"].index.intersection(data["NQ"].index)

    print(f"\nES+NQ strategy bake-off | 50/50 | init=${args.balance:,.0f} | "
          f"eval {eval_start.date()} -> {common[-1].date()}  (GROSS of costs)\n")
    hdr = f"{'Strategy':<26}{'End $':>14}{'Sharpe':>8}{'CAGR':>8}{'Vol':>7}{'MaxDD':>8}"
    print(hdr)
    print("-" * len(hdr))

    rows = []
    for name, fn in STRATS.items():
        # compute signal on full warmed series, THEN slice to eval window
        port = pd.concat([fn(data[n]).reindex(common) for n in SYMBOLS], axis=1).mean(axis=1)
        port = port[port.index >= eval_start]
        nav = args.balance * (1 + port).cumprod()
        sh, cg, vol, dd = stats(nav.tolist())
        rows.append((name, nav.iloc[-1], sh, cg, vol, dd))

    for name, end, sh, cg, vol, dd in sorted(rows, key=lambda r: -r[2]):
        print(f"{name:<26}{end:>14,.0f}{sh:>8.2f}{cg*100:>7.1f}%{vol*100:>6.1f}%"
              f"{dd*100:>7.1f}%")


if __name__ == "__main__":
    main()
