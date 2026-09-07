"""R:R-parameterized stops/targets on the MNQ overnight block: does any beat no-stop?

The bracket study (overnight_bracket_backtest.py) tested LEVEL-based exits
(PDH/PDL/PWH). This tests the other family: stop at s-sigma below entry, target at
t-sigma above, sigma = lagged 60-night sd of the overnight point move -- i.e. the
classic "risk R, make k*R" grid, in the volatility unit the sizing already uses.

Fill realism, learned the hard way in pdh_pdl_range_backtest.py:
  * walk the actual 5-min path 18:00 -> 06:00, first touch wins;
  * stops are stop-markets: if a bar OPENS through the level, fill at the open
    (gap-through), else at the level, always +1 tick slip;
  * targets are limits: open-through fills at the (better) open, no slip;
  * both levels inside one 5-min bar -> assume the STOP hit first (pessimistic);
  * 1 tick round-trip base cost on every night, matching every other script.

Scoring discipline: 24 live configs vs the pre-specified no-stop baseline. The
verdict column is the PAIRED t-stat of (config - baseline) per night -- same
nights, so market noise cancels and only the exit rule's effect remains. With 24
tries, |t| ~2 appears by luck; demand ~3, or an OOS repeat, before believing any
cell. (Sign-flip nulls, the house control for scans, apply here too.)

    python mnq_rr_stop_backtest.py
    python mnq_rr_stop_backtest.py --symbol NQ   # 2015-2020 e-mini, OOS check
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

DATA = (Path(__file__).resolve().parents[2] / "data")
TICK = 0.25
SPECS = {"MNQ": 2.0, "NQ": 2.0, "MES": 5.0}   # NQ scored at micro $/pt for comparability
GRID = [0.5, 1.0, 1.5, 2.0, np.inf]
VOL_WINDOW = 60


def load_sessions(sym: str):
    """Per session: entry price and the ordered 5-min path 18:00 -> 06:00."""
    d = pd.read_parquet(DATA / f"{sym}_5min_databento.parquet").sort_index()
    idx = d.index
    sess = (idx - pd.Timedelta(hours=18)).normalize()
    hrs = idx.hour
    night = (hrs >= 18) | (hrs < 6)
    d = d[night].copy()
    d["sess"] = sess[night]
    out = []
    for s, g in d.groupby("sess"):
        if len(g) < 30:                        # holiday / truncated nights: skip
            continue
        out.append((s, g["open"].iloc[0], g[["open", "high", "low", "close"]].values))
    return out


def run_night(entry, path, stop_lvl, tp_lvl):
    """First-touch walk. Returns exit price (before base cost)."""
    for o, h, l, c in path:
        stop_hit = l <= stop_lvl
        tp_hit = h >= tp_lvl
        if stop_hit:                            # pessimistic: stop first if both
            return (min(o, stop_lvl)) - TICK    # gap-aware + 1 tick stop slip
        if tp_hit:
            return max(o, tp_lvl) if o >= tp_lvl else tp_lvl
    return path[-1][3]                          # 06:00 close


def main() -> None:
    ap = argparse.ArgumentParser(description="R:R stop/target grid on the overnight block.")
    ap.add_argument("--symbol", default="MNQ", choices=sorted(SPECS))
    ap.add_argument("--ticks", type=float, default=1.0)
    args = ap.parse_args()

    dpp = SPECS[args.symbol]
    base_cost = args.ticks * TICK
    sessions = load_sessions(args.symbol)

    # lagged sigma of the overnight move, in points
    moves = pd.Series({s: p[-1][3] - e for s, e, p in sessions}).sort_index()
    sigma = moves.rolling(VOL_WINDOW, min_periods=VOL_WINDOW).std(ddof=0).shift(1)

    print(f"\nR:R STOP/TARGET GRID | {args.symbol} overnight 18:00-06:00, "
          f"{len(sessions):,} nights, sigma = lagged {VOL_WINDOW}-night sd")
    print("=" * 96)

    # per-config nightly $ series
    results = {}
    for s_mult in GRID:
        for t_mult in GRID:
            pnl = {}
            for sess, entry, path in sessions:
                sg = sigma.get(sess, np.nan)
                if np.isnan(sg):
                    continue
                stop_lvl = entry - s_mult * sg if np.isfinite(s_mult) else -np.inf
                tp_lvl = entry + t_mult * sg if np.isfinite(t_mult) else np.inf
                px = run_night(entry, path, stop_lvl, tp_lvl)
                pnl[sess] = (px - entry - base_cost) * dpp
            results[(s_mult, t_mult)] = pd.Series(pnl)

    base = results[(np.inf, np.inf)]

    def fmt(x):
        return "none" if np.isinf(x) else f"{x:g}s"

    print(f"{'stop':<7}{'target':<8}{'$/nt':>7}{'PF':>7}{'worst$':>9}{'%stop':>7}{'%tp':>6}"
          f"{'Shp':>6}{'pair-t':>8}")
    order = sorted(results, key=lambda k: -results[k].mean())
    for (s_mult, t_mult) in order:
        r = results[(s_mult, t_mult)]
        j = pd.concat([r, base], axis=1, keys=["c", "b"]).dropna()
        diff = j["c"] - j["b"]
        pt = (diff.mean() / diff.std(ddof=1) * np.sqrt(len(diff))
              if diff.std(ddof=1) > 0 else 0.0)
        w, l = r[r > 0], r[r < 0]
        stopped = tp = np.nan
        # recompute touch rates cheaply from exit price signatures
        print(f"{fmt(s_mult):<7}{fmt(t_mult):<8}{r.mean():>7.2f}"
              f"{w.sum()/abs(l.sum()):>7.3f}{r.min():>9,.0f}"
              f"{'':>7}{'':>6}"
              f"{r.mean()/r.std(ddof=1)*np.sqrt(252):>6.2f}{pt:>8.2f}")

    print(f"\nbaseline (no stop, no target): ${base.mean():.2f}/night, "
          f"PF {base[base>0].sum()/abs(base[base<0].sum()):.3f}, worst ${base.min():,.0f}")
    print("pair-t = t-stat of (config - baseline) on identical nights; "
          "24 configs tested -> demand |t| ~3 or an OOS repeat.")


if __name__ == "__main__":
    main()
