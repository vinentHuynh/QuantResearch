"""What happens if you remove the worst nights -- and can any rule remove them in advance?

Two halves, and the second is the one that matters.

PART 1 (HINDSIGHT): drop the worst N nights and watch the metrics soar. This is
cheating and is labelled as such: you cannot know which nights those are until
after they happen. It is included because the symmetric control -- dropping the
BEST N nights -- is printed beside it. If the two are comparable in size, the
distribution has no special "removable" bad tail; it is just a distribution, and
the exercise tells you nothing you can trade.

PART 2 (EX-ANTE): every filter here uses only information available BEFORE the
18:00 entry, and is scored on two axes at once:
  * how many of the 20 worst nights it actually dodged, and
  * what it cost in forgone good nights.
A filter only helps if it dodges disasters faster than it sheds edge. Both eras
are shown; a filter that works in one and not the other is noise, which is the
default outcome for this kind of search (see the window-scan permutation study).

    python mnq_tail_exclusion_report.py
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path(__file__).with_name("data")
DPP, TICK = 2.0, 0.25
COST = TICK * DPP


def build(fname: str, ref: float | None):
    d = pd.read_parquet(DATA / fname).sort_index()
    idx = d.index
    sess = (idx - pd.Timedelta(hours=18)).normalize()
    cell = d.groupby([sess, idx.hour]).agg(o=("open", "first"), c=("close", "last"),
                                           h=("high", "max"), l=("low", "min"),
                                           n=("open", "size"))
    cell = cell[cell["n"] >= 6]
    o, c = cell["o"].unstack(-1), cell["c"].unstack(-1)
    hi, lo = cell["h"].unstack(-1), cell["l"].unstack(-1)

    j = pd.concat([o[18], c[5]], axis=1, keys=["entry", "exit"]).dropna()
    raw = j["exit"] - j["entry"]
    pnl = (raw / j["entry"] * ref if ref else raw) * DPP - COST

    f = pd.DataFrame({"pnl": pnl, "entry": j["entry"]})
    # --- ex-ante features: all known at 18:00, all from the PRIOR day session ---
    day_ret = (c[16] - o[6]).reindex(f.index)                 # prior 06-16 move
    day_rng = (hi[[6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16]].max(axis=1)
               - lo[[6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16]].min(axis=1)).reindex(f.index)
    if ref is not None:
        day_ret = day_ret / f["entry"] * ref
        day_rng = day_rng / f["entry"] * ref
    f["day_ret"] = day_ret * DPP
    f["day_rng"] = day_rng * DPP
    f["vol20"] = f["pnl"].rolling(20).std().shift(1)          # lagged realised vol
    f["rng20"] = f["day_rng"].rolling(20).mean().shift(1)
    f["sma50"] = f["entry"].rolling(50).mean().shift(1)
    f["dow"] = f.index.dayofweek
    return f.dropna()


def line(tag, p: pd.Series, base: pd.Series):
    a = p.values
    w, l = a[a > 0], a[a < 0]
    eq = p.cumsum()
    dd = float((eq - eq.cummax()).min())
    return (f"{tag:<30}{len(a):>6}{a.mean():>8.2f}{a.mean()*252:>9,.0f}"
            f"{a.mean()/a.std(ddof=1)*np.sqrt(252):>7.2f}"
            f"{w.sum()/abs(l.sum()):>7.3f}{dd:>9,.0f}{a.min():>8,.0f}"
            f"{(a.mean()-base.mean())*252:>+10,.0f}")


def main() -> None:
    ap = argparse.ArgumentParser()
    args = ap.parse_args()

    fn = build("MNQ_5min_databento.parquet", None)
    ref = float(fn["entry"].loc["2024-01-01":].median())
    fo = build("NQ_5min_databento.parquet", ref)

    for name, f in (("IN-SAMPLE MNQ 2020-2026", fn),
                    ("OUT-OF-SAMPLE NQ 2015-2020 (scaled)", fo)):
        p = f["pnl"]
        print(f"\n{'='*98}\nPART 1 — HINDSIGHT REMOVAL (not tradeable) | {name}")
        print(f"{'variant':<30}{'n':>6}{'$/nt':>8}{'$/yr':>9}{'Shp':>7}{'PF':>7}"
              f"{'MaxDD$':>9}{'worst':>8}{'d$/yr':>10}")
        print(line("baseline (everything)", p, p))
        for k in (1, 5, 10, 20):
            print(line(f"drop worst {k}", p.drop(p.nsmallest(k).index), p))
        for k in (1, 5, 10, 20):
            print(line(f"drop BEST {k}  [control]", p.drop(p.nlargest(k).index), p))
        print(line("drop worst 10 AND best 10", p.drop(p.nsmallest(10).index)
                                                  .drop(p.nlargest(10).index, errors="ignore"), p))

    # ---- PART 2: ex-ante filters, scored on both eras ------------------------
    print(f"\n{'='*98}\nPART 2 — EX-ANTE FILTERS (only pre-18:00 information)")
    print("Scored on: does it dodge the 20 worst nights, and what does it cost?\n")
    hdr = (f"{'filter (skip the night when...)':<38}"
           f"{'|--- MNQ 2020-26 ---':<34}{'|--- NQ 2015-20 ---':<30}")
    print(hdr)
    print(f"{'':<38}{'%skip':>7}{'dodged':>8}{'$/yr':>9}{'d':>9}"
          f"{'%skip':>8}{'dodged':>8}{'$/yr':>9}{'d':>9}")

    def filters(f):
        return {
            "prior day fell >1%": f["day_ret"] < -0.01 * f["entry"] * DPP,
            "prior day fell >2%": f["day_ret"] < -0.02 * f["entry"] * DPP,
            "prior day rose >1%": f["day_ret"] > 0.01 * f["entry"] * DPP,
            "realised vol in top 20%": f["vol20"] > f["vol20"].quantile(0.80),
            "realised vol in top 10%": f["vol20"] > f["vol20"].quantile(0.90),
            "prior day range > 2x avg": f["day_rng"] > 2 * f["rng20"],
            "price below 50-day avg": f["entry"] < f["sma50"],
            "Monday (weekend gap behind)": f["dow"] == 6,
        }

    worst_sets = {id(fn): set(fn["pnl"].nsmallest(20).index),
                  id(fo): set(fo["pnl"].nsmallest(20).index)}
    rows = {}
    for f in (fn, fo):
        for tag, mask in filters(f).items():
            mask = mask.fillna(False)
            kept = f.loc[~mask, "pnl"]
            dodged = len(worst_sets[id(f)] & set(f.index[mask]))
            rows.setdefault(tag, []).append(
                (mask.mean() * 100, dodged, kept.mean() * 252,
                 (kept.mean() - f["pnl"].mean()) * 252))
    for tag, (a, b) in rows.items():
        print(f"{tag:<38}{a[0]:>6.0f}%{a[1]:>7}/20{a[2]:>9,.0f}{a[3]:>+9,.0f}"
              f"{b[0]:>7.0f}%{b[1]:>7}/20{b[2]:>9,.0f}{b[3]:>+9,.0f}")

    print("\nd = change in $/yr per contract vs trading every night. A filter is only")
    print("worth it if d is positive in BOTH eras, not just where it was discovered.")


if __name__ == "__main__":
    main()
