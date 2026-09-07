"""ES + NQ trend-following backtest (daily, long/flat).

Proxy note: trades the CASH indices SPX (ES underlying) and NDX (NQ underlying)
from PWB Indices-Daily-Price. No roll/financing/multiplier — NAV is a notional
equity curve, not a real futures account. Use it to judge the SIGNAL, not P&L to
the tick.

Strategy: 200-day SMA regime filter per instrument. Long full sleeve when
close > SMA200, else flat (cash, 0% return). Two equal sleeves (50/50), daily
rebalance. No leverage, no shorting.

Split: in-sample <= CUTOFF, out-of-sample after. Chosen before looking at
results (see README section 6 of the backtest guide) and kept fixed.

Usage:
    python es_nq_backtest.py --balance 100000 --sma 200 --start 1990-01-01
"""
import argparse
import os
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

# --- load .env (PWB_API_KEY) without extra deps ------------------------------
_env = Path(__file__).with_name(".env")
if _env.exists():
    for _line in _env.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

import pwb_toolbox.datasets as pwb_ds
from pwb_toolbox.performance.metrics import (
    sharpe_ratio,
    annualized_volatility,
    cagr,
    max_drawdown,
)

SYMBOLS = {"ES": "SPX", "NQ": "NDX"}  # instrument -> index ticker
CUTOFF = date(2015, 1, 1)             # in/out-of-sample split, fixed upfront


def load_close(index_symbol: str, start: str) -> pd.Series:
    df = pwb_ds.load_dataset("Indices-Daily-Price", symbols=[index_symbol])
    df["date"] = pd.to_datetime(df["date"])
    df = df[df["date"] >= pd.Timestamp(start)].sort_values("date")
    return df.set_index("date")["close"].astype(float)


def sleeve_returns(close: pd.Series, sma_window: int) -> pd.Series:
    """Daily strategy return for one instrument: hold when yesterday's close
    was above its SMA, else 0 (flat). Signal lagged one day — no look-ahead."""
    sma = close.rolling(sma_window).mean()
    signal = (close > sma).astype(float).shift(1)  # act next day
    daily_ret = close.pct_change()
    return (signal * daily_ret).fillna(0.0)


def stats(nav: list[float]) -> dict:
    depth, dur = max_drawdown(nav)
    return {
        "sharpe": sharpe_ratio(nav),
        "cagr": cagr(nav),
        "vol": annualized_volatility(nav),
        "maxdd": abs(depth),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--balance", type=float, default=100_000, help="initial balance")
    ap.add_argument("--sma", type=int, default=200, help="SMA trend window (days)")
    ap.add_argument("--start", type=str, default="1990-01-01")
    args = ap.parse_args()

    # per-instrument daily strategy returns, aligned on common dates
    rets = {}
    for name, sym in SYMBOLS.items():
        rets[name] = sleeve_returns(load_close(sym, args.start), args.sma)
    R = pd.DataFrame(rets).dropna(how="all").fillna(0.0)

    # 50/50 equal-weight portfolio, rebalanced daily
    port_ret = R.mean(axis=1)

    # build NAV from initial balance
    nav = args.balance * (1 + port_ret).cumprod()
    nav_list = nav.tolist()

    # buy-and-hold benchmark (same 50/50, always invested)
    bh_ret = pd.DataFrame(
        {n: load_close(s, args.start).pct_change() for n, s in SYMBOLS.items()}
    ).reindex(R.index).fillna(0.0).mean(axis=1)
    bh_nav = (args.balance * (1 + bh_ret).cumprod()).tolist()

    # in / out-of-sample split
    idx = nav.index
    is_mask = idx <= pd.Timestamp(CUTOFF)
    oos_mask = idx > pd.Timestamp(CUTOFF)

    def _report(title, series_vals):
        s = stats(series_vals)
        print(f"{title:<22} end=${series_vals[-1]:>14,.0f}  "
              f"Sharpe={s['sharpe']:.2f}  CAGR={s['cagr']*100:5.1f}%  "
              f"Vol={s['vol']*100:4.1f}%  MaxDD={s['maxdd']*100:4.1f}%")

    print(f"\nES+NQ trend (SMA{args.sma}, 50/50, long/flat) | "
          f"start={args.start}  init=${args.balance:,.0f}")
    print(f"period {idx[0].date()} -> {idx[-1].date()}  ({len(idx)} days)\n")

    _report("Strategy (full)", nav_list)
    _report("Buy & hold (full)", bh_nav)
    print()
    _report(f"Strategy IS (<= {CUTOFF})", nav[is_mask].tolist())
    _report("Strategy OOS (after)", nav[oos_mask].tolist())


if __name__ == "__main__":
    main()
