"""Where is the optimal stop -- and is that optimum real or an artefact of a few nights?

Asking "what is the best stop" invites a single number, but a stop at $1,000 only
engages on ~0.5% of nights, so the whole comparison rests on a handful of
observations. A point estimate from that is meaningless without knowing its
sampling error, which is what this measures.

Three passes:
  1. FINE SWEEP of stop levels in both eras -- the shape of the curve matters far
     more than its argmax. A flat plateau means "anything in this band", a sharp
     peak that differs between eras means "noise".
  2. BOOTSTRAP THE ARGMAX: resample nights with replacement, re-find the best stop
     each time, and report the distribution. A stable optimum gives a tight
     cluster; an artefact gives a spread across the whole grid.
  3. HONEST CROSS-ERA TEST: take the optimum discovered in one era, apply it to
     the other, and see what survives. This is the only number with any claim to
     predictive meaning.

Path simulation and fills are identical to mnq_hard_stop_backtest.py (gap-aware
stop-market fills, 1 extra tick of stop slippage, 1-tick base round trip). The old
era's stop is scaled to the same PERCENTAGE move so the two eras are comparable.

    python mnq_optimal_stop_search.py
    python mnq_optimal_stop_search.py --boots 2000
"""
from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

from mnq_hard_stop_backtest import load_paths, run, DPP

GRID = list(range(200, 3001, 50)) + [None]       # dollars per contract


def curves(paths, ref, grid):
    """{stop: Series of nightly $}, aligned on a common index."""
    out = {s: run(paths, s, ref) for s in grid}
    idx = out[None].index
    return {s: v.reindex(idx) for s, v in out.items()}, idx


def summarise(series: dict, s):
    a = series[s].values
    return a.mean() * 252, a.mean() / a.std(ddof=1) * np.sqrt(252)


def bar(v, lo, hi, width=44):
    n = int(round((v - lo) / (hi - lo) * width)) if hi > lo else 0
    return "#" * max(0, min(width, n))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--boots", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=11)
    args = ap.parse_args()

    pn = load_paths("MNQ_5min_databento.parquet")
    po = load_paths("NQ_5min_databento.parquet")
    ref = float(np.median([e for s, e, _ in pn if s.year >= 2024]))

    cur_n, idx_n = curves(pn, None, GRID)
    cur_o, idx_o = curves(po, ref, GRID)
    base_n = cur_n[None].values.mean() * 252
    base_o = cur_o[None].values.mean() * 252

    # ---- 1. the shape of the curve -------------------------------------------
    print(f"\n{'='*92}\n1. FINE SWEEP — $/yr per contract by stop level (### = relative height)")
    show = [s for s in GRID if s is None or s % 250 == 0]
    yn = {s: summarise(cur_n, s)[0] for s in show}
    yo = {s: summarise(cur_o, s)[0] for s in show}
    lo = min(list(yn.values()) + list(yo.values()))
    hi = max(list(yn.values()) + list(yo.values()))
    print(f"{'stop':<10}{'MNQ 20-26':>11}{'':<3}{'NQ 15-20':>10}{'':<3}{'both>base?':>11}   shape (MNQ)")
    for s in show:
        tag = "none" if s is None else f"${s:,}"
        both = "yes" if (yn[s] > base_n and yo[s] > base_o) else ""
        print(f"{tag:<10}{yn[s]:>11,.0f}{'':<3}{yo[s]:>10,.0f}{'':<3}{both:>11}   {bar(yn[s], lo, hi)}")

    # ---- 2. bootstrap the argmax ---------------------------------------------
    rng = np.random.default_rng(args.seed)
    grid_live = [s for s in GRID if s is not None]
    for nm, cur, idx in (("MNQ 2020-2026", cur_n, idx_n), ("NQ 2015-2020", cur_o, idx_o)):
        M = np.column_stack([cur[s].values for s in grid_live])   # nights x stops
        base = cur[None].values
        n = M.shape[0]
        best, beat = [], 0
        for _ in range(args.boots):
            draw = rng.integers(0, n, n)
            means = M[draw].mean(axis=0)
            k = int(np.argmax(means))
            best.append(grid_live[k])
            if means[k] > base[draw].mean():
                beat += 1
        b = pd.Series(best)
        print(f"\n{'='*92}\n2. BOOTSTRAP OF THE OPTIMUM — {nm} ({args.boots:,} resamples)")
        print(f"   median optimal stop ${b.median():,.0f} | "
              f"80% of resamples fall between ${b.quantile(0.10):,.0f} and ${b.quantile(0.90):,.0f}")
        print(f"   the 'best' stop landed on {b.nunique()} different values out of "
              f"{len(grid_live)} grid points")
        print(f"   share of resamples where the best stop beat NO stop at all: "
              f"{beat/args.boots*100:.0f}%")
        top = b.value_counts().head(5)
        print("   most frequent optima: " +
              ", ".join(f"${v:,} ({c/args.boots*100:.0f}%)" for v, c in top.items()))

    # ---- 3. cross-era honesty test -------------------------------------------
    print(f"\n{'='*92}\n3. CROSS-ERA TEST (the only predictive number here)")
    best_n = max(grid_live, key=lambda s: cur_n[s].values.mean())
    best_o = max(grid_live, key=lambda s: cur_o[s].values.mean())
    print(f"   best on MNQ 2020-26  = ${best_n:,}  ->  applied to NQ 2015-20: "
          f"${summarise(cur_o, best_o)[0]:,.0f} best-case vs "
          f"${summarise(cur_o, best_n)[0]:,.0f} using MNQ's pick "
          f"(no-stop baseline ${base_o:,.0f})")
    print(f"   best on NQ 2015-20   = ${best_o:,}  ->  applied to MNQ 2020-26: "
          f"${summarise(cur_n, best_o)[0]:,.0f} "
          f"(no-stop baseline ${base_n:,.0f})")

    # plateau: every stop within $50/yr of the best, in BOTH eras
    ok = [s for s in grid_live
          if summarise(cur_n, s)[0] > base_n - 50 and summarise(cur_o, s)[0] > base_o - 50]
    if ok:
        print(f"\n   BAND that costs < $50/yr vs no-stop in BOTH eras: "
              f"${min(ok):,} to ${max(ok):,}")
    sig = [s for s in grid_live
           if summarise(cur_n, s)[0] > base_n and summarise(cur_o, s)[0] > base_o]
    if sig:
        print(f"   BAND that actually beats no-stop in BOTH eras: ${min(sig):,} to ${max(sig):,}"
              f"  (best-in-both by total: ${max(sig, key=lambda s: summarise(cur_n,s)[0]+summarise(cur_o,s)[0]):,})")


if __name__ == "__main__":
    main()
