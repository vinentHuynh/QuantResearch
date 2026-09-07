"""Cross-sectional commodity futures momentum (Miffre-Rallis) on PWB data.

New futures edge, distinct from single-market trend and market-neutral WITHIN
commodities (low correlation to equities -> diversifier / low DD). Each month,
rank ~18 liquid commodity front-month continuous series by trailing 12-month
return (risk-adjusted); long the top third, short the bottom third, equal
weight. Held one month forward (no look-ahead). Compared to a time-series
momentum version and a long-only equal-weight basket.

Data note: PWB commodities are FRONT-MONTH only (no 2nd contract), so true
term-structure carry is not computable -- this uses price momentum, not basis.
Monthly forward returns winsorized per month (2%/98%) for robustness (e.g. the
2020 oil dislocation).

    python commodity_xsec_momentum_backtest.py --lookback 12 --frac 0.33
"""
import argparse
import os
from pathlib import Path

import numpy as np
import pandas as pd

_env = Path(__file__).with_name(".env")
for _l in (_env.read_text().splitlines() if _env.exists() else []):
    _l = _l.strip()
    if _l and "=" in _l and not _l.startswith("#"):
        _k, _v = _l.split("=", 1)
        os.environ.setdefault(_k.strip(), _v.strip())

import pwb_toolbox.datasets as pwb_ds
from pwb_toolbox.performance.metrics import (
    sharpe_ratio, annualized_volatility, cagr, max_drawdown,
)

# clean, well-known liquid commodity front-month futures
UNIVERSE = {
    "CL1": "WTI crude", "HO1": "heating oil", "XB1": "gasoline", "NG1": "nat gas",
    "GC1": "gold", "SI1": "silver", "HG1": "copper", "PL1": "platinum",
    "C1": "corn", "W1": "wheat", "S1": "soybeans", "O1": "oats",
    "SB1": "sugar", "KC1": "coffee", "CC1": "cocoa", "CT1": "cotton",
    "LC1": "live cattle", "LH1": "lean hogs", "FC1": "feeder cattle",
}


def monthly_closes(symbols):
    raw = pwb_ds.load_dataset("Commodities-Daily-Price", symbols=symbols)
    raw["date"] = pd.to_datetime(raw["date"])
    raw = raw.dropna(subset=["symbol", "date", "close"])
    px = {}
    for s in symbols:
        d = (raw.loc[raw["symbol"].eq(s)].drop_duplicates("date", keep="last")
             .sort_values("date").set_index("date")["close"].astype(float))
        if len(d) > 260:
            px[s] = d.resample("ME").last()
    return pd.DataFrame(px)


def spx_monthly():
    raw = pwb_ds.load_dataset("Indices-Daily-Price", symbols=["SPX"])
    raw["date"] = pd.to_datetime(raw["date"])
    d = raw.sort_values("date").set_index("date")["close"].astype(float)
    return d.resample("ME").last().pct_change()


def stats(nav):
    depth, _ = max_drawdown(nav)
    return sharpe_ratio(nav), cagr(nav), annualized_volatility(nav), abs(depth)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--balance", type=float, default=100_000)
    ap.add_argument("--start", default="2000-01-01")
    ap.add_argument("--lookback", type=int, default=12, help="momentum months")
    ap.add_argument("--frac", type=float, default=0.33, help="long/short fraction")
    ap.add_argument("--cost-bps", type=float, default=10.0, help="round-trip on churn")
    args = ap.parse_args()
    cost = args.cost_bps / 1e4

    px = monthly_closes(list(UNIVERSE))
    rets = px.pct_change()
    # winsorize monthly returns per date (commodities have wild months)
    rets = rets.apply(lambda row: row.clip(row.quantile(0.02), row.quantile(0.98)),
                      axis=1)
    L = args.lookback
    mom = px.shift(1) / px.shift(L) - 1.0                     # 12-1 momentum
    vol = rets.rolling(12, min_periods=6).std()
    radj = mom / vol                                          # risk-adjusted momentum
    fwd = rets.shift(-1)                                      # next-month return

    idx = px.index
    xs_rows, ts_rows, lo_rows, dates = [], [], [], []
    for t in idx:
        sig = radj.loc[t].dropna()
        f = fwd.loc[t]
        if len(sig) < 8:
            continue
        k = max(1, int(len(sig) * args.frac))
        ranked = sig.sort_values()
        shorts = ranked.index[:k]
        longs = ranked.index[-k:]
        v = vol.loc[t]

        def leg(names):  # inverse-vol weighted forward return (equal risk)
            w = (1.0 / v[names]).replace([np.inf, -np.inf], np.nan).dropna()
            fr = f[w.index].dropna()
            w = w[fr.index]
            return np.nan if w.sum() == 0 else float((w / w.sum() * fr).sum())

        lf, sf = leg(longs), leg(shorts)
        if np.isnan(lf) or np.isnan(sf):
            continue
        xs = (lf - sf) - 2 * (k / len(sig)) * cost            # L/S, churn-cost proxy
        # time-series momentum: long positive-momentum, short negative
        tsig = mom.loc[t].dropna()
        tf = f[tsig.index]
        ts = (np.sign(tsig) * tf).mean() - cost
        lo = f[tsig.index].mean()                             # long-only EW basket
        xs_rows.append(xs); ts_rows.append(ts); lo_rows.append(lo); dates.append(t)

    xs = pd.Series(xs_rows, index=dates)
    ts = pd.Series(ts_rows, index=dates)
    lo = pd.Series(lo_rows, index=dates)
    spx = spx_monthly().reindex(xs.index)

    start = pd.Timestamp(args.start)
    def cut(s): return s[s.index >= start]
    xs, ts, lo, spx = cut(xs), cut(ts), cut(lo), cut(spx)

    print(f"\nCROSS-SECTIONAL COMMODITY MOMENTUM | {len(UNIVERSE)} futures | "
          f"{xs.index.min().date()}->{xs.index.max().date()} | monthly | "
          f"L={args.lookback} frac={args.frac:.0%} cost {args.cost_bps}bps")
    print("Front-month only (no term-structure carry). Winsorized monthly returns.\n")
    hdr = f"{'Strategy':<28}{'Sharpe':>8}{'CAGR':>8}{'Vol':>7}{'MaxDD':>8}{'CorrSPX':>9}{'End$':>12}"
    print(hdr); print("-" * len(hdr))

    def report(name, s):
        # monthly sharpe -> annualize via helper convention (uses sqrt(252) on the
        # NAV of these monthly points, so recompute annualization for monthly here)
        mean, sd = s.mean(), s.std(ddof=0)
        sh = mean / sd * np.sqrt(12) if sd > 0 else np.nan
        nav = args.balance * (1 + s).cumprod()
        cg = (nav.iloc[-1] / args.balance) ** (12 / len(s)) - 1
        vol_a = sd * np.sqrt(12)
        depth, _ = max_drawdown((nav / args.balance).tolist())
        j = pd.concat({"a": s, "b": spx}, axis=1).dropna()
        corr = j["a"].corr(j["b"]) if len(j) > 6 else np.nan
        print(f"{name:<28}{sh:>8.2f}{cg*100:>7.1f}%{vol_a*100:>6.1f}%"
              f"{abs(depth)*100:>7.1f}%{corr:>9.2f}{nav.iloc[-1]:>12,.0f}")

    report("X-sec momentum L/S", xs)
    report("Time-series momentum", ts)
    report("Long-only EW basket", lo)
    report("SPX (reference)", spx.fillna(0.0))


if __name__ == "__main__":
    main()
