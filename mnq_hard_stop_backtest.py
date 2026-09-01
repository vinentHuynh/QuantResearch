"""Fixed-dollar hard stop on the overnight block: does a $1,000 stop beat no stop?

The R:R grid tested stops in SIGMA units. This tests them in FIXED DOLLARS, which
is how a trader with a fixed loss tolerance actually thinks -- and how a prop
buffer actually binds. $1,000 on MNQ is 500 index points, roughly 4.5x the typical
overnight sigma of ~$220, so it is a disaster stop, not a trading stop.

Fills are simulated on the real 5-min path, pessimistically:
  * stop is a stop-market: if a bar OPENS through the level, fill at the open
    (gap-through, the realistic case for overnight news), else at the level;
  * one extra tick of slippage on every stop fill;
  * base 1-tick round trip on every night regardless.

Cross-era note: a stop fixed in today's dollars is not comparable to 2015, when
NQ traded near 4,400 and $1,000 was a far larger percentage move. The out-of-
sample column therefore scales the stop to the SAME PERCENTAGE move, matching how
the P&L itself is rescaled. Both the dollar-fixed and percent-fixed readings are
printed so the distinction is visible rather than buried.

Scoring is the paired t of (stopped - baseline) on identical nights, so market
noise cancels and only the stop's effect is measured.

    python mnq_hard_stop_backtest.py
    python mnq_hard_stop_backtest.py --pipeline    # add Lucid 50K impact
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path(__file__).with_name("data")
DPP, TICK = 2.0, 0.25
COST = TICK * DPP
NIGHT_HOURS = [18, 19, 20, 21, 22, 23, 0, 1, 2, 3, 4, 5]
STOPS = [500, 750, 1000, 1500, 2000, None]      # dollars per contract; None = no stop


def load_paths(fname: str):
    """Per session: entry price and the ordered 5-min OHLC path 18:00 -> 06:00."""
    d = pd.read_parquet(DATA / fname).sort_index()
    idx = d.index
    sess = (idx - pd.Timedelta(hours=18)).normalize()
    hrs = idx.hour
    keep = np.isin(hrs, NIGHT_HOURS)
    d = d[keep].copy()
    d["sess"] = sess[keep]
    out = []
    for s, g in d.groupby("sess"):
        if len(g) < 30:
            continue
        out.append((s, float(g["open"].iloc[0]),
                    g[["open", "high", "low", "close"]].to_numpy()))
    return out


def night_pnl(entry: float, path: np.ndarray, stop_pts: float | None) -> float:
    """$ P&L per contract for one night, gross of the base round-trip cost."""
    if stop_pts is None:
        return (path[-1][3] - entry) * DPP
    lvl = entry - stop_pts
    for o, h, l, c in path:
        if l <= lvl:
            fill = min(o, lvl) - TICK          # gap-through fills at the open
            return (fill - entry) * DPP
    return (path[-1][3] - entry) * DPP


def run(paths, stop_dollars, ref=None):
    """Returns Series of net $ P&L. ref set -> old era: scale P&L and the stop to %."""
    rows = {}
    for s, entry, path in paths:
        if stop_dollars is None:
            stop_pts = None
        else:
            pts = stop_dollars / DPP                       # 500 pts for $1,000
            stop_pts = pts * (entry / ref) if ref else pts  # same % move in the old era
        raw = night_pnl(entry, path, stop_pts)
        if ref is not None:
            raw = raw / entry * ref                        # rescale to today's notional
        rows[s] = raw - COST
    return pd.Series(rows)


def stats(p: pd.Series, base: pd.Series):
    a = p.values
    w, l = a[a > 0], a[a < 0]
    eq = p.cumsum()
    dd = float((eq - eq.cummax()).min())
    j = pd.concat([p, base], axis=1, keys=["c", "b"]).dropna()
    d = j["c"] - j["b"]
    t = d.mean() / d.std(ddof=1) * np.sqrt(len(d)) if d.std(ddof=1) > 0 else 0.0
    return {"mean": a.mean(), "yr": a.mean() * 252,
            "sharpe": a.mean() / a.std(ddof=1) * np.sqrt(252),
            "pf": w.sum() / abs(l.sum()), "dd": dd, "worst": a.min(),
            "hit": (a > 0).mean() * 100, "t": t, "delta": (a.mean() - base.mean()) * 252}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pipeline", action="store_true")
    ap.add_argument("--size", type=int, default=10)
    ap.add_argument("--sims", type=int, default=10000)
    args = ap.parse_args()

    pn = load_paths("MNQ_5min_databento.parquet")
    po = load_paths("NQ_5min_databento.parquet")
    ref = float(np.median([e for s, e, _ in pn if s.year >= 2024]))

    for name, paths, r in (("IN-SAMPLE MNQ 2020-2026", pn, None),
                           ("OUT-OF-SAMPLE NQ 2015-2020 (stop scaled to same %)", po, ref)):
        series = {s: run(paths, s, r) for s in STOPS}
        base = series[None]
        print(f"\n{'='*104}\n{name}  |  {len(base):,} nights")
        print(f"{'stop':<14}{'$/nt':>8}{'$/yr':>9}{'Shp':>7}{'PF':>7}{'hit%':>7}"
              f"{'MaxDD$':>9}{'worst':>9}{'stops':>7}{'%nights':>9}{'d$/yr':>9}{'pair-t':>8}")
        for s in STOPS:
            p = series[s]
            st = stats(p, base)
            if s is None:
                n_stop, pct = 0, 0.0
                tag = "none [std]"
            else:
                # a stopped night is one whose loss sits at/below the stop threshold
                thresh = -(s + TICK * DPP + COST) + 1e-9
                n_stop = int((p <= thresh).sum())
                pct = n_stop / len(p) * 100
                tag = f"${s:,}"
            print(f"{tag:<14}{st['mean']:>8.2f}{st['yr']:>9,.0f}{st['sharpe']:>7.2f}"
                  f"{st['pf']:>7.3f}{st['hit']:>7.1f}{st['dd']:>9,.0f}{st['worst']:>9,.0f}"
                  f"{n_stop:>7}{pct:>8.1f}%{st['delta']:>+9,.0f}{st['t']:>8.2f}")

        # what the $1,000 stop actually did on the nights it fired
        s1k = series[1000]
        fired = s1k < base - 1e-6
        if fired.any():
            saved = (s1k[fired] - base[fired])
            rec = (base[fired] > s1k[fired] + 1)          # would have ended better
            print(f"  $1,000 stop fired on {fired.sum()} nights: "
                  f"avg outcome vs holding ${saved.mean():+,.0f}/night, "
                  f"total ${saved.sum():+,.0f} | held-on would have been BETTER on "
                  f"{rec.sum()} of {fired.sum()} ({rec.mean()*100:.0f}%), "
                  f"and would have closed GREEN on {(base[fired] > 0).sum()}")

    if args.pipeline:
        from lucid_container_scan import pipeline
        rng = np.random.default_rng(7)
        print(f"\n{'='*104}\nLUCID 50K PIPELINE ({args.size} micro, combined eras)")
        print(f"{'stop':<14}{'E[net]':>9}{'med':>8}{'P>0':>6}{'busts':>7}{'p/outs':>8}")
        for s in STOPS:
            comb = np.concatenate([run(po, s, ref).values, run(pn, s, None).values])
            r = pipeline(comb, args.size, args.size, 250, args.sims, rng)
            tag = "none [std]" if s is None else f"${s:,}"
            print(f"{tag:<14}{r['net']:>9,.0f}{r['med']:>8,.0f}{r['p_pos']*100:>5.0f}%"
                  f"{r['busts']:>7.1f}{r['payouts']:>8.1f}")


if __name__ == "__main__":
    main()
