"""Market-neutral cross-sectional equity factor backtest on PWB factor signals.

Uses Stocks-Quarterly-FactorSignals (pre-computed 0-100 factor percentiles for
~22k US stocks incl. delisted, 1998-2026). Each quarter, for a factor: long the
top quintile (pctile >= 80), short the bottom quintile (<= 20), equal-weight,
dollar-neutral. Held one quarter forward. Market-neutral by construction, so a
crash hits both legs -> low directional drawdown (the goal).

No look-ahead: the signal at quarter-end t is earned on the return of quarter
t+1 (forward return via per-symbol shift). Forward returns are winsorized per
quarter at 1%/99% because the raw `returns` column has junk outliers (max 899).
Quarterly rebalance -> low turnover -> costs don't dominate (unlike intraday).

    python factor_ls_backtest.py --cost-bps 5 --start 2000-01-01
"""
import argparse
import os
from pathlib import Path

import numpy as np
import pandas as pd

_env = (Path(__file__).resolve().parents[2] / ".env")
for _l in (_env.read_text().splitlines() if _env.exists() else []):
    _l = _l.strip()
    if _l and "=" in _l and not _l.startswith("#"):
        _k, _v = _l.split("=", 1)
        os.environ.setdefault(_k.strip(), _v.strip())

import pwb_toolbox.datasets as pwb_ds

# style factors to test; sign note: high pctile = more of that exposure.
FACTORS = [
    "value", "profitability", "momentum", "small_size", "price_volatility",
    "earnings_consistency", "cash_flow", "solvency", "dividend_yield",
    "low_equity_issuance", "short_term_reversal", "illiquidity",
]
# composite of "good" exposures, value dropped (value winter), low-vol inverted
COMPOSITE = {"momentum": 1, "profitability": 1, "earnings_consistency": 1,
             "cash_flow": 1, "low_equity_issuance": 1, "price_volatility": -1}


def annualize(q):  # q = quarterly return series
    nav = (1 + q).cumprod()
    mean, sd = q.mean(), q.std(ddof=0)
    ann_ret = nav.iloc[-1] ** (4 / len(q)) - 1 if len(q) else np.nan
    sharpe = (mean / sd * np.sqrt(4)) if sd > 0 else np.nan
    dd = (nav / nav.cummax() - 1).min()
    return ann_ret, mean * 4, sd * np.sqrt(4), sharpe, abs(dd)


def ls_returns(df, score, fwd, cost, borrow_annual=0.0):
    """Quarterly top-minus-bottom-quintile return for one score column.

    Net of: transaction cost on quarterly name churn (both legs) and a short-leg
    borrow fee (borrow_annual, charged per quarter on the $1 short notional).
    Also returns the long-only top-quintile return (no borrow, has market beta).
    """
    rows = []
    prev_long, prev_short = set(), set()
    for dt, g in df.groupby("datetime"):
        s = g[[score, fwd, "symbol"]].dropna()
        if len(s) < 50:
            continue
        hi = s[s[score] >= 80]
        lo = s[s[score] <= 20]
        if len(hi) < 5 or len(lo) < 5:
            continue
        long_ret, short_ret = hi[fwd].mean(), lo[fwd].mean()
        lset, sset = set(hi["symbol"]), set(lo["symbol"])
        turn = 0.0
        if prev_long:
            turn = (len(lset - prev_long) / max(len(lset), 1)
                    + len(sset - prev_short) / max(len(sset), 1)) / 2
        prev_long, prev_short = lset, sset
        ls = ((long_ret - short_ret)
              - turn * (cost / 1e4)          # churn transaction cost, both legs
              - borrow_annual / 4.0)         # short-leg borrow, per quarter
        rows.append((dt, ls, long_ret))
    r = pd.DataFrame(rows, columns=["dt", "ls", "long"]).set_index("dt")
    return r["ls"], r["long"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2000-01-01")
    ap.add_argument("--cost-bps", type=float, default=5.0,
                    help="round-trip cost bps applied to quarterly name churn")
    ap.add_argument("--borrow-bps-annual", type=float, default=200.0,
                    help="annual short-leg borrow fee in bps (default 2%%)")
    args = ap.parse_args()
    borrow = args.borrow_bps_annual / 1e4

    df = pwb_ds.load_dataset("Stocks-Quarterly-FactorSignals")
    df["datetime"] = pd.to_datetime(df["datetime"])
    df = df.sort_values(["symbol", "datetime"])
    df["fwd"] = df.groupby("symbol")["returns"].shift(-1)   # next-quarter return
    # winsorize forward returns per quarter (raw col has junk outliers)
    df["fwd"] = df.groupby("datetime")["fwd"].transform(
        lambda x: x.clip(x.quantile(0.01), x.quantile(0.99)))
    df = df[df["datetime"] >= pd.Timestamp(args.start)]

    # market proxy: equal-weight mean forward return of the universe each quarter
    mkt = df.groupby("datetime")["fwd"].mean().dropna()

    # composite score: mean of ORIENTED percentiles (low-vol inverted), needing
    # at least 4 of the 6 present so a stock missing one factor still scores.
    oriented = []
    for f, sign in COMPOSITE.items():
        col = df[f].astype(float)
        oriented.append(col if sign > 0 else (100.0 - col))
    O = pd.concat(oriented, axis=1)
    df["composite"] = O.mean(axis=1).where(O.notna().sum(axis=1) >= 4)

    print(f"\nMARKET-NEUTRAL FACTOR L/S | PWB factor signals | "
          f"{df['datetime'].min().date()}->{df['datetime'].max().date()} | quarterly")
    print(f"Net of churn cost {args.cost_bps}bps + short borrow "
          f"{args.borrow_bps_annual:.0f}bps/yr\n")
    hdr = (f"{'Factor (top-bottom)':<22}{'Qtrs':>5}{'AnnRet':>8}{'Vol':>7}"
           f"{'Sharpe':>8}{'MaxDD':>8}{'Beta':>7}{'Hit%':>6}")
    print(hdr); print("-" * len(hdr))

    def report(name, ls):
        ann_ret, _, vol, sh, dd = annualize(ls)
        j = pd.concat({"a": ls, "b": mkt}, axis=1).dropna()
        beta = np.cov(j["a"], j["b"])[0, 1] / np.var(j["b"]) if len(j) > 8 else np.nan
        hit = (ls > 0).mean() * 100
        print(f"{name:<22}{len(ls):>5}{ann_ret*100:>7.1f}%{vol*100:>6.1f}%"
              f"{sh:>8.2f}{dd*100:>7.1f}%{beta:>7.2f}{hit:>6.0f}")

    for f in FACTORS:
        ls, _ = ls_returns(df, f, "fwd", args.cost_bps, borrow)
        report(f, ls)
    print("-" * len(hdr))
    comp_ls, comp_long = ls_returns(df, "composite", "fwd", args.cost_bps, borrow)
    report("COMPOSITE L/S", comp_ls)
    report("COMPOSITE long-only", comp_long)     # no borrow, carries market beta
    _, mkt_ann, mkt_vol, mkt_sh, mkt_dd = annualize(mkt)
    print(f"{'Market (EW univ)':<22}{len(mkt):>5}{mkt_ann*100:>7.1f}%{mkt_vol*100:>6.1f}%"
          f"{mkt_sh:>8.2f}{mkt_dd*100:>7.1f}%{1.00:>7.2f}{(mkt>0).mean()*100:>6.0f}")

    print("\nCOMPOSITE L/S — short-borrow sensitivity")
    print(f"{'borrow bps/yr':<16}{'Sharpe':>8}{'AnnRet':>8}{'MaxDD':>8}")
    for b in (0, 100, 200, 400, 800):
        ls, _ = ls_returns(df, "composite", "fwd", args.cost_bps, b / 1e4)
        ann_ret, _, _, sh, dd = annualize(ls)
        print(f"{b:<16}{sh:>8.2f}{ann_ret*100:>7.1f}%{dd*100:>7.1f}%")

    # 2x-levered market-neutral composite: same Sharpe, meaningful $ return
    lev = 2.0
    lev_ls = comp_ls * lev
    ann_ret, _, vol, sh, dd = annualize(lev_ls)
    print(f"\nCOMPOSITE L/S x{lev:.0f} leverage: AnnRet {ann_ret*100:.1f}%  "
          f"Vol {vol*100:.1f}%  Sharpe {sh:.2f}  MaxDD {dd*100:.1f}%")


if __name__ == "__main__":
    main()
