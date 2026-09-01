"""Anatomy of the losing nights in the MNQ overnight block.

The strategy wins ~55% of nights, so ~45% lose. This profiles those losses: how
big, how clustered, how predictable, where in the window they accrue, and how much
of the drawdown they own. Written to answer "what do the bad nights look like and
can I see one coming", which is the risk question the headline stats hide.

Everything is reported on BOTH eras (MNQ 2020-26 in-sample, NQ 2015-20 out of
sample, rescaled to today's notional). Any pattern that appears in one era and not
the other is noise -- that has already happened repeatedly in this workspace, so
the two columns sit side by side rather than pooled.

Predictability tests are deliberately framed as "would knowing X have helped",
with the honest baseline printed next to each. Prior work already established that
conditioning the direction fails (5 rules, all worse than always-long); this asks
the narrower question of whether losses are merely *concentrated* somewhere.

    python mnq_losing_nights_report.py
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path(__file__).with_name("data")
DPP, TICK = 2.0, 0.25
COST = TICK * DPP
ENTRY_H, EXIT_H = 18, 5              # 18:00 -> 06:00 ET


def load_cells(fname: str):
    d = pd.read_parquet(DATA / fname).sort_index()
    idx = d.index
    sess = (idx - pd.Timedelta(hours=18)).normalize()
    cell = d.groupby([sess, idx.hour]).agg(o=("open", "first"), c=("close", "last"),
                                           h=("high", "max"), l=("low", "min"),
                                           n=("open", "size"))
    cell = cell[cell["n"] >= 6]
    return cell


def night_frame(cell: pd.DataFrame, ref: float | None) -> pd.DataFrame:
    o, c = cell["o"].unstack(-1), cell["c"].unstack(-1)
    lo = cell["l"].unstack(-1)
    j = pd.concat([o[ENTRY_H], c[EXIT_H]], axis=1, keys=["entry", "exit"]).dropna()
    pnl = (j["exit"] - j["entry"])
    if ref is not None:
        pnl = pnl / j["entry"] * ref
    f = pd.DataFrame({"entry": j["entry"], "pnl": pnl * DPP - COST})
    # worst point reached during the hold (min low across the night's hours)
    night_hours = [18, 19, 20, 21, 22, 23, 0, 1, 2, 3, 4, 5]
    mins = lo[night_hours].min(axis=1).reindex(j.index)
    mae = (mins - j["entry"])
    if ref is not None:
        mae = mae / j["entry"] * ref
    f["mae"] = mae * DPP                       # max adverse excursion, $
    f["dow"] = f.index.dayofweek               # 6=Sun-anchored = Monday's day
    f["year"] = f.index.year
    return f.dropna()


def hour_attrib(cell: pd.DataFrame, ref, mask_index):
    """Per-hour $ contribution, restricted to the given sessions."""
    o = cell["o"].unstack(-1)
    seq = [18, 19, 20, 21, 22, 23, 0, 1, 2, 3, 4, 5]
    bounds = [o[h] for h in seq] + [cell["c"].unstack(-1)[5]]
    P = pd.concat(bounds, axis=1).dropna()
    P = P.loc[P.index.intersection(mask_index)]
    steps = P.diff(axis=1).iloc[:, 1:]
    if ref is not None:
        steps = steps.div(P.iloc[:, 0], axis=0) * ref
    return (steps * DPP).mean(), seq


def streaks(is_win: np.ndarray) -> dict:
    """Lengths of consecutive LOSING runs. (numpy bools fail `is False`, so use not.)"""
    runs, run = [], 0
    for w in is_win:
        if not bool(w):
            run += 1
        elif run:
            runs.append(run)
            run = 0
    if run:
        runs.append(run)
    r = pd.Series(runs, dtype=float)
    if r.empty:
        return {"max": 0, "mean": 0.0, "n": 0, "ge3": 0, "ge5": 0}
    return {"max": int(r.max()), "mean": float(r.mean()), "n": len(r),
            "ge3": int((r >= 3).sum()), "ge5": int((r >= 5).sum())}


def report(name: str, f: pd.DataFrame, cell: pd.DataFrame, ref):
    p = f["pnl"]
    loss, win = p[p < 0], p[p > 0]
    print(f"\n{'='*94}\n{name}  |  {len(p):,} nights\n{'='*94}")

    print(f"FREQUENCY   losing nights {len(loss):,} ({len(loss)/len(p)*100:.1f}%)   "
          f"winning {len(win):,} ({len(win)/len(p)*100:.1f}%)")
    print(f"MAGNITUDE   avg loss ${loss.mean():,.0f}   avg win ${win.mean():,.0f}   "
          f"ratio {abs(win.mean()/loss.mean()):.3f}   PF {win.sum()/abs(loss.sum()):.3f}")
    print(f"            median loss ${loss.median():,.0f}   median win ${win.median():,.0f}")

    q = loss.quantile([0.5, 0.25, 0.10, 0.05, 0.01]).round(0)
    print(f"LOSS TAIL   p50 ${q.loc[0.5]:,.0f}  p25 ${q.loc[0.25]:,.0f}  "
          f"p10 ${q.loc[0.10]:,.0f}  p5 ${q.loc[0.05]:,.0f}  p1 ${q.loc[0.01]:,.0f}  "
          f"worst ${loss.min():,.0f}")
    tot = abs(loss.sum())
    for k in (0.01, 0.05, 0.10):
        n = max(1, int(len(loss) * k))
        print(f"            worst {k*100:>4.0f}% of losing nights ({n:>3}) = "
              f"{abs(loss.nsmallest(n).sum())/tot*100:>4.1f}% of all losses, "
              f"${abs(loss.nsmallest(n).sum()):,.0f}")

    st = streaks((p > 0).values)
    print(f"CLUSTERING  longest losing streak {st['max']} nights | "
          f"{st['ge3']} streaks >=3, {st['ge5']} >=5 | mean streak {st['mean']:.2f}")
    sign = (p > 0).astype(int)
    ac = sign.autocorr(1)
    p_loss = (p < 0).mean()
    p_loss_given_loss = (p.shift(1) < 0).pipe(lambda m: (p[m] < 0).mean())
    print(f"            P(loss) = {p_loss*100:.1f}%   P(loss | prior night lost) = "
          f"{p_loss_given_loss*100:.1f}%   sign autocorr(1) = {ac:+.3f}")
    r_ac = p.autocorr(1)
    print(f"            $ autocorr(1) = {r_ac:+.3f}  "
          f"(near zero = no momentum/reversal to trade)")

    print(f"MAE         on losing nights, avg worst-point ${f.loc[p < 0, 'mae'].mean():,.0f}; "
          f"on WINNING nights avg worst-point ${f.loc[p > 0, 'mae'].mean():,.0f}")
    deep = (f["mae"] < -500)
    if deep.any():
        rec = (p[deep] > 0).mean()
        print(f"            nights that traded ${-500} or worse mid-hold: {deep.sum():,} "
              f"({deep.mean()*100:.1f}%), of which {rec*100:.1f}% still closed GREEN")

    print("BY YEAR     " + "  ".join(
        f"{y}:{(g<0).mean()*100:.0f}%" for y, g in p.groupby(f["year"])))
    dmap = {6: "Mon", 0: "Tue", 1: "Wed", 2: "Thu", 3: "Fri"}
    print("BY WEEKDAY  " + "  ".join(
        f"{dmap.get(d,d)}:{(g<0).mean()*100:.0f}%/${g.mean():+.0f}"
        for d, g in p.groupby(f["dow"]) if d in dmap))

    m, seq = hour_attrib(cell, ref, p[p < 0].index)
    m.index = [f"{h:02d}" for h in seq]
    print("HOURLY on LOSING nights ($ per hour): " +
          "  ".join(f"{h}:{v:+.0f}" for h, v in m.items()))


def main() -> None:
    ap = argparse.ArgumentParser(description="Losing-night anatomy for the overnight block.")
    args = ap.parse_args()

    cn = load_cells("MNQ_5min_databento.parquet")
    co = load_cells("NQ_5min_databento.parquet")
    fn = night_frame(cn, None)
    ref = float(fn["entry"].loc["2024-01-01":].median())
    fo = night_frame(co, ref)

    report("IN-SAMPLE  MNQ 2020-2026", fn, cn, None)
    report("OUT-OF-SAMPLE  NQ 2015-2020 (scaled to today's notional)", fo, co, ref)

    print(f"\n{'='*94}\nWORST 10 NIGHTS, IN-SAMPLE (session date = the evening you entered)")
    w = fn.nsmallest(10, "pnl")
    for d, row in w.iterrows():
        print(f"  {d.date()}  ${row['pnl']:>8,.0f}   worst point mid-hold ${row['mae']:>8,.0f}")


if __name__ == "__main__":
    main()
