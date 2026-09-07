"""Locate the MNQ overnight edge on the clock, with an honest overfitting control.

`mnq_time_block_backtest.py` showed the 18:00->06:00 Globex night carries the drift
and the 06:00-12:00 block carries none. This drills into the hour and asks whether
a *tighter* contiguous window beats the a-priori 18:00->06:00 -- which is exactly
the kind of question a naive scan answers wrongly, because searching 276 windows
finds a great one in pure noise.

Three things are reported, in increasing order of how much they should be trusted:

1. HOURLY ATTRIBUTION -- descriptive, one row per tradeable hour.
2. THE SCAN -- every contiguous window, best and worst by Sharpe.
3. THE CONTROLS, which decide whether (2) means anything:
   a. Sign-flip permutation null. Each session's whole vector of hourly moves is
      multiplied by a random +/-1, which destroys drift while preserving the
      within-session covariance and volatility. Re-running the scan on 400 such
      draws gives the distribution of "best window Sharpe" under no edge at all.
      The real best window has to clear that, not zero.
   b. Split-sample. Pick the best window on the first half only, then trade it on
      the second half (and the reverse). Also reports the rank correlation between
      in-sample and out-of-sample Sharpe across all 276 windows -- if that is ~0,
      the scan has no predictive content whatever the top of the table says.

Window returns are exact: a window a->b is priced first-open(a) -> last-close(b-1)
using the session's boundary prices, so every inter-hour seam is included. The
17:00 ET maintenance halt has no bars and is skipped; the clock therefore runs
18:00 -> 16:00 (23 hours) anchored on the 18:00 Globex open.

    python mnq_window_scan_backtest.py
    python mnq_window_scan_backtest.py --symbol MES --sims 1000
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from pwb_toolbox.performance.metrics import (
    sharpe_ratio, annualized_volatility, cagr, max_drawdown,
)

DATA = Path(__file__).with_name("data")
SPECS = {"MNQ": (0.25, 2.0), "MES": (0.25, 5.0)}
# 18:00-anchored trading clock; 17:00 is the CME maintenance halt (no bars)
CLOCK = [18, 19, 20, 21, 22, 23, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16]
BOUNDS = [f"{h:02d}:00" for h in CLOCK] + ["17:00"]   # 24 boundaries, 23 segments
MIN_BARS = 6                                           # of 12 five-min bars per hour


def boundary_prices(sym: str) -> pd.DataFrame:
    """Per session, the 24 clock-boundary prices that define every window."""
    df = pd.read_parquet(DATA / f"{sym}_5min_databento.parquet").sort_index()
    idx = df.index
    sess = (idx - pd.Timedelta(hours=18)).normalize()
    cell = df.groupby([sess, idx.hour]).agg(o=("open", "first"), c=("close", "last"),
                                            n=("open", "size"))
    cell = cell[cell["n"] >= MIN_BARS]
    o = cell["o"].unstack(-1)
    c = cell["c"].unstack(-1)
    cols = [o[h] for h in CLOCK] + [c[CLOCK[-1]]]      # opens, then the final close
    P = pd.concat(cols, axis=1)
    P.columns = BOUNDS
    P = P.dropna().sort_index()
    P.index = pd.DatetimeIndex(P.index).tz_localize(None)
    return P


def all_window_sharpes(logret: np.ndarray) -> np.ndarray:
    """Annualized Sharpe of every contiguous window, from one covariance matrix.

    With C the cumulative log return across boundaries, window (a,b) equals
    C[:,b]-C[:,a], so mean and variance for all pairs come from the mean vector and
    covariance of C -- no per-window loop.
    """
    C = np.concatenate([np.zeros((logret.shape[0], 1)), logret.cumsum(axis=1)], axis=1)
    m = C.mean(axis=0)
    V = np.cov(C, rowvar=False)
    mean = m[None, :] - m[:, None]                      # [a,b] = m[b]-m[a]
    var = np.diag(V)[None, :] + np.diag(V)[:, None] - 2 * V
    with np.errstate(invalid="ignore", divide="ignore"):
        sh = mean / np.sqrt(np.where(var > 0, var, np.nan)) * np.sqrt(252)
    return sh                                           # (24,24), valid where b>a


def sleeve(ret: pd.Series, cost: pd.Series, window: int, target: float,
           max_lev: float) -> pd.Series:
    lev = (target / np.sqrt(252)) / ret.rolling(window, min_periods=window).std(ddof=0)
    return (lev.shift(1).clip(0.0, max_lev) * (ret - cost)).fillna(0.0)


def stats(r: pd.Series, balance: float) -> dict:
    nav = (balance * (1 + r.fillna(0.0)).cumprod())
    norm = (nav / balance).tolist()
    depth, _ = max_drawdown(norm)
    return {"sharpe": sharpe_ratio(norm), "cagr": cagr(norm),
            "vol": annualized_volatility(norm), "maxdd": abs(depth)}


def window_net(P: pd.DataFrame, a: int, b: int, cost_pts: float, args) -> pd.Series:
    ret = P.iloc[:, b] / P.iloc[:, a] - 1
    lo, hi = ret.quantile(0.005), ret.quantile(0.995)
    ret = ret.clip(lo, hi)
    return sleeve(ret, cost_pts / P.iloc[:, a], args.vol_window, args.target_vol,
                  args.max_leverage)


def main() -> None:
    ap = argparse.ArgumentParser(description="Hour-level window scan for the MNQ night.")
    ap.add_argument("--symbol", default="MNQ", choices=sorted(SPECS))
    ap.add_argument("--ticks", type=float, default=1.0)
    ap.add_argument("--start", default="2020-01-02")
    ap.add_argument("--balance", type=float, default=100_000.0)
    ap.add_argument("--vol-window", type=int, default=60)
    ap.add_argument("--target-vol", type=float, default=0.20)
    ap.add_argument("--max-leverage", type=float, default=2.0)
    ap.add_argument("--sims", type=int, default=400, help="sign-flip permutation draws")
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    tick, dpp = SPECS[args.symbol]
    cost_pts = args.ticks * tick
    P = boundary_prices(args.symbol)
    P = P[P.index >= pd.Timestamp(args.start)]
    n = len(P)

    print(f"\n{args.symbol} CLOCK-WINDOW SCAN (Databento 5-min, hourly boundaries)")
    print("=" * 90)
    print(f"Period: {P.index[0].date()} -> {P.index[-1].date()} ({n:,} complete sessions) | "
          f"cost {args.ticks:g} tick RT (${cost_pts*dpp:.2f})\n")

    # ---- 1. hourly attribution -------------------------------------------------
    print("HOURLY ATTRIBUTION (1 contract, open->open, no cost)")
    print(f"{'hour ET':<10}{'tot $':>10}{'mean$':>8}{'sd$':>7}{'t-stat':>8}{'hit%':>7}{'Shp':>7}")
    seg_pts = P.diff(axis=1).iloc[:, 1:] * 1.0          # boundary-to-boundary points
    for k, h in enumerate(CLOCK):
        s = seg_pts.iloc[:, k].dropna() * dpp
        t = s.mean() / s.std(ddof=1) * np.sqrt(len(s))
        print(f"{BOUNDS[k]+'-'+BOUNDS[k+1]:<10}{s.sum():>10,.0f}{s.mean():>8.1f}"
              f"{s.std():>7.0f}{t:>8.2f}{(s > 0).mean()*100:>7.1f}"
              f"{s.mean()/s.std(ddof=1)*np.sqrt(252):>7.2f}")

    # ---- 2. the scan -----------------------------------------------------------
    logret = np.log(P.values[:, 1:] / P.values[:, :-1])
    sh = all_window_sharpes(logret)
    pairs = [(a, b) for a in range(len(BOUNDS)) for b in range(a + 1, len(BOUNDS))]
    ranked = sorted(pairs, key=lambda ab: -sh[ab[0], ab[1]])
    print(f"\nSCAN OF ALL {len(pairs)} CONTIGUOUS WINDOWS (unlevered gross Sharpe)")
    print(f"{'rank':<6}{'window':<16}{'hrs':>5}{'Sharpe':>8}")
    for i, (a, b) in enumerate(ranked[:8], 1):
        print(f"{i:<6}{BOUNDS[a]+'->'+BOUNDS[b]:<16}{b-a:>5}{sh[a, b]:>8.2f}")
    print("  ...")
    for (a, b) in ranked[-3:]:
        print(f"{'':<6}{BOUNDS[a]+'->'+BOUNDS[b]:<16}{b-a:>5}{sh[a, b]:>8.2f}")
    a0, b0 = BOUNDS.index("18:00"), BOUNDS.index("06:00")
    print(f"\n  a-priori 18:00->06:00 = {sh[a0, b0]:.2f} "
          f"(rank {ranked.index((a0, b0))+1} of {len(pairs)})")

    # ---- 3a. permutation null --------------------------------------------------
    rng = np.random.default_rng(args.seed)
    best_real = sh[ranked[0][0], ranked[0][1]]
    null_best, null_apriori = np.empty(args.sims), np.empty(args.sims)
    for i in range(args.sims):
        flip = rng.choice([-1.0, 1.0], size=(logret.shape[0], 1))
        s_i = all_window_sharpes(logret * flip)
        null_best[i] = np.nanmax(s_i)
        null_apriori[i] = s_i[a0, b0]
    p_best = (null_best >= best_real).mean()
    p_apriori = (null_apriori >= sh[a0, b0]).mean()
    print(f"\nSIGN-FLIP PERMUTATION NULL ({args.sims} draws, drift destroyed, vol preserved)")
    print(f"  best-of-{len(pairs)} Sharpe under null: median {np.median(null_best):.2f}, "
          f"95th pct {np.percentile(null_best, 95):.2f}, max {null_best.max():.2f}")
    print(f"  observed best window ({BOUNDS[ranked[0][0]]}->{BOUNDS[ranked[0][1]]}) "
          f"= {best_real:.2f}  ->  p = {p_best:.3f}")
    print(f"  observed 18:00->06:00 = {sh[a0, b0]:.2f}  ->  p = {p_apriori:.3f} "
          f"(single pre-specified window, no search penalty)")

    # ---- 3b. split-sample ------------------------------------------------------
    mid = n // 2
    sh1 = all_window_sharpes(logret[:mid])
    sh2 = all_window_sharpes(logret[mid:])
    v1 = np.array([sh1[a, b] for a, b in pairs])
    v2 = np.array([sh2[a, b] for a, b in pairs])
    ok = np.isfinite(v1) & np.isfinite(v2)
    rho = pd.Series(v1[ok]).corr(pd.Series(v2[ok]), method="spearman")
    b1 = pairs[int(np.nanargmax(v1))]
    b2 = pairs[int(np.nanargmax(v2))]
    print(f"\nSPLIT-SAMPLE (first {mid} sessions -> {P.index[mid].date()} -> last {n-mid})")
    print(f"  rank corr of window Sharpe, 1st half vs 2nd half: rho = {rho:+.2f}")
    print(f"  best on 1st half {BOUNDS[b1[0]]}->{BOUNDS[b1[1]]}: "
          f"{sh1[b1]:.2f} in-sample -> {sh2[b1]:.2f} out-of-sample")
    print(f"  best on 2nd half {BOUNDS[b2[0]]}->{BOUNDS[b2[1]]}: "
          f"{sh2[b2]:.2f} in-sample -> {sh1[b2]:.2f} out-of-sample")
    print(f"  a-priori 18:00->06:00: {sh1[a0, b0]:.2f} / {sh2[a0, b0]:.2f} (1st / 2nd half)")

    # ---- tradeable comparison, net + vol targeted ------------------------------
    print(f"\nTRADEABLE COMPARISON (vol-targeted, net {args.ticks:g} tick)")
    print(f"{'window':<16}{'Sharpe':>8}{'CAGR':>9}{'Vol':>7}{'MaxDD':>8}{'worst$':>9}")
    cands = [(a0, b0), ranked[0], b1, b2, (BOUNDS.index("18:00"), BOUNDS.index("03:00")),
             (BOUNDS.index("00:00"), BOUNDS.index("06:00"))]
    seen = set()
    for a, b in cands:
        if (a, b) in seen:
            continue
        seen.add((a, b))
        r = window_net(P, a, b, cost_pts, args)
        st = stats(r, args.balance)
        worst = ((P.iloc[:, b] - P.iloc[:, a]) * dpp).min()
        print(f"{BOUNDS[a]+'->'+BOUNDS[b]:<16}{st['sharpe']:>8.2f}{st['cagr']*100:>8.1f}%"
              f"{st['vol']*100:>6.1f}%{st['maxdd']*100:>7.1f}%{worst:>9,.0f}")


if __name__ == "__main__":
    main()
