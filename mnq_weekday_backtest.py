"""Overnight block traded only on Sunday, Tuesday and Wednesday entries.

Same trade as always -- long the 18:00 ET reopen, flat at the 06:00 open, 1-tick round
trip -- but skipping Monday and Thursday entries. (There is no Friday or Saturday
entry: CME is shut from Friday 17:00 to Sunday 18:00.)

The arms:
    ALL          every night, the validated baseline
    SUN+TUE+WED  the requested subset
    MON+THU      the complement, shown because a subset is only meaningful next to
                 what it discarded

Two honesty tests ride along, because those three weekdays were chosen by looking at
the in-sample weekday chart -- which is selection, not a hypothesis:

  1. OUT OF SAMPLE. The same fixed Sun/Tue/Wed rule applied to NQ 2015-2019, an era
     that had no vote in choosing it.
  2. WALK-FORWARD. Each year, rank the weekdays on all PRIOR data only, trade that
     year's top three, repeat. If weekday is a real property of the market this beats
     trading everything; if it is noise it does not.

Also reported: all 10 possible three-weekday combinations ranked in both eras, with the
rank correlation between them. That number is the whole question -- if in-sample
weekday ranking does not predict out-of-sample weekday ranking, no weekday filter is
knowledge, however good the backtest of the chosen one looks.

Annualisation uses each arm's OWN trade count (a subset that trades 150 nights a year
cannot be annualised at 252), so $/yr and Sharpe are comparable across arms.

    python mnq_weekday_backtest.py
    python mnq_weekday_backtest.py --chart
"""
from __future__ import annotations

import argparse
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd

from mnq_exit_time_backtest import DPP, sessions, pnl

REPORTS = Path(__file__).with_name("reports")
HOLD = 12                                   # 18:00 -> 06:00
DOW = {6: "Sun", 0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu"}
PICK = [6, 1, 2]                            # Sunday, Tuesday, Wednesday
REST = [0, 3]

C_BLUE, C_ORANGE, C_AQUA, C_YELLOW = "#2a78d6", "#eb6834", "#1baf7a", "#eda100"
INK, INK2, GRIDC, SURF = "#0b0b0b", "#52514e", "#d8d7d2", "#fcfcfb"


def nightly(fname: str, ref: float | None) -> pd.DataFrame:
    s = sessions(fname, [HOLD])
    out = pd.DataFrame({"pnl": pnl(s, HOLD, ref)})
    out["dow"] = out.index.dayofweek
    out["year"] = out.index.year
    return out


def stats(p: pd.Series, span_years: float) -> dict:
    a = p.to_numpy()
    if len(a) < 2:
        return {}
    w, l = a[a > 0], a[a < 0]
    eq = p.cumsum()
    sd = a.std(ddof=1)
    per_yr = len(a) / span_years
    return {"n": len(a), "n_yr": per_yr, "mean": a.mean(), "yr": a.mean() * per_yr,
            "sharpe": a.mean() / sd * np.sqrt(per_yr), "pf": w.sum() / abs(l.sum()),
            "hit": (a > 0).mean() * 100, "dd": float((eq - eq.cummax()).min()),
            "worst": a.min(), "t": a.mean() / sd * np.sqrt(len(a)), "total": a.sum()}


def welch(x: pd.Series, y: pd.Series) -> float:
    """Two-sample t: these are different nights, so a paired t is not available."""
    a, b = x.to_numpy(), y.to_numpy()
    se = np.sqrt(a.var(ddof=1) / len(a) + b.var(ddof=1) / len(b))
    return float((a.mean() - b.mean()) / se) if se > 0 else 0.0


def span(df: pd.DataFrame) -> float:
    return (df.index[-1] - df.index[0]).days / 365.25


def arms_table(df: pd.DataFrame, name: str) -> None:
    y = span(df)
    print(f"\n{'='*104}\n{name}  |  {len(df):,} nights over {y:.1f} years")
    print(f"{'arm':<16}{'nights':>8}{'nt/yr':>7}{'$/nt':>8}{'$/yr':>9}{'Shp':>7}{'PF':>7}"
          f"{'hit%':>7}{'MaxDD$':>9}{'worst':>9}{'total$':>10}{'own t':>8}")
    rows = {"ALL [std]": df, "SUN+TUE+WED": df[df["dow"].isin(PICK)],
            "MON+THU": df[df["dow"].isin(REST)]}
    for tag, d in rows.items():
        st = stats(d["pnl"], y)
        print(f"{tag:<16}{st['n']:>8,}{st['n_yr']:>7.0f}{st['mean']:>8.2f}{st['yr']:>9,.0f}"
              f"{st['sharpe']:>7.2f}{st['pf']:>7.3f}{st['hit']:>7.1f}{st['dd']:>9,.0f}"
              f"{st['worst']:>9,.0f}{st['total']:>10,.0f}{st['t']:>8.2f}")
    w = welch(rows["SUN+TUE+WED"]["pnl"], rows["MON+THU"]["pnl"])
    print(f"  SUN+TUE+WED vs MON+THU: two-sample t = {w:+.2f} "
          f"({'significant' if abs(w) >= 2 else 'NOT significant'} at |t| >= 2)")

    print(f"\n{'weekday':<10}{'nights':>8}{'$/night':>10}{'total$':>10}{'hit%':>8}{'t':>7}")
    for k in (6, 0, 1, 2, 3):
        d = df[df["dow"] == k]
        st = stats(d["pnl"], y)
        print(f"{DOW[k]:<10}{st['n']:>8,}{st['mean']:>10.2f}{st['total']:>10,.0f}"
              f"{st['hit']:>8.1f}{st['t']:>7.2f}")


def triples(m: pd.DataFrame, q: pd.DataFrame) -> pd.DataFrame:
    """All 10 three-weekday sets, ranked in each era. Does the ranking carry over?"""
    rows = []
    for c in combinations([6, 0, 1, 2, 3], 3):
        rows.append({
            "set": "+".join(DOW[k] for k in sorted(c, key=lambda z: (z != 6, z))),
            "IS $/nt": m[m["dow"].isin(c)]["pnl"].mean(),
            "OOS $/nt": q[q["dow"].isin(c)]["pnl"].mean(),
        })
    t = pd.DataFrame(rows)
    t["IS rank"] = t["IS $/nt"].rank(ascending=False).astype(int)
    t["OOS rank"] = t["OOS $/nt"].rank(ascending=False).astype(int)
    return t.sort_values("IS rank")


def walk_forward(comb: pd.DataFrame, k: int = 3) -> pd.DataFrame:
    """Each year: rank weekdays on prior years only, trade that year's top k."""
    years = sorted(comb["year"].unique())
    out = []
    for y in years[2:]:                       # need at least two years of history
        past = comb[comb["year"] < y]
        pick = past.groupby("dow")["pnl"].mean().nlargest(k).index.tolist()
        cur = comb[comb["year"] == y]
        sel = cur[cur["dow"].isin(pick)]
        out.append({"year": y, "picked": "+".join(DOW[d] for d in sorted(pick)),
                    "adaptive $/nt": sel["pnl"].mean(), "all $/nt": cur["pnl"].mean(),
                    "static STW $/nt": cur[cur["dow"].isin(PICK)]["pnl"].mean(),
                    "n": len(sel)})
    return pd.DataFrame(out).set_index("year")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chart", action="store_true")
    args = ap.parse_args()
    REPORTS.mkdir(exist_ok=True)

    m = nightly("MNQ_5min_databento.parquet", None)
    q_all = sessions("NQ_5min_databento.parquet", [HOLD])
    ref = float(np.median(sessions("MNQ_5min_databento.parquet", [HOLD])
                          .query("index.dt.year >= 2024")["entry"]))
    q = nightly("NQ_5min_databento.parquet", ref)
    q = q[q.index < m.index[0]]

    arms_table(m, "IN-SAMPLE  MNQ 2020-2026")
    arms_table(q, f"OUT-OF-SAMPLE  NQ 2015-2019 (rescaled, ref {ref:,.0f})")

    t = triples(m, q)
    rho = t["IS $/nt"].corr(t["OOS $/nt"], method="spearman")
    print(f"\n{'-'*104}\nALL 10 THREE-WEEKDAY SETS -- in-sample rank vs out-of-sample rank")
    print(f"{'set':<16}{'IS $/nt':>10}{'IS rank':>9}{'OOS $/nt':>11}{'OOS rank':>10}")
    for _, r in t.iterrows():
        star = "  <-- requested" if r["set"] == "Sun+Tue+Wed" else ""
        print(f"{r['set']:<16}{r['IS $/nt']:>10.2f}{r['IS rank']:>9}"
              f"{r['OOS $/nt']:>11.2f}{r['OOS rank']:>10}{star}")
    print(f"  Spearman rank correlation IS vs OOS = {rho:+.2f}  "
          f"({'weekday choice carries over' if rho > 0.5 else 'weekday choice does NOT carry over'})")

    comb = pd.concat([q, m]).sort_index()
    wf = walk_forward(comb)
    print(f"\n{'-'*104}\nWALK-FORWARD -- weekdays ranked on prior years only, top 3 traded")
    print(f"{'year':<7}{'picked':<18}{'adaptive $/nt':>15}{'all-nights $/nt':>17}"
          f"{'static STW $/nt':>17}")
    for y, r in wf.iterrows():
        print(f"{y:<7}{r['picked']:<18}{r['adaptive $/nt']:>15.2f}"
              f"{r['all $/nt']:>17.2f}{r['static STW $/nt']:>17.2f}")
    print(f"{'MEAN':<7}{'':<18}{wf['adaptive $/nt'].mean():>15.2f}"
          f"{wf['all $/nt'].mean():>17.2f}{wf['static STW $/nt'].mean():>17.2f}")
    beat = (wf["adaptive $/nt"] > wf["all $/nt"]).mean() * 100
    print(f"  adaptive beat all-nights in {beat:.0f}% of years")

    if args.chart:
        chart(m, q, t, wf, rho, REPORTS / "mnq_weekday.png")


def chart(m, q, tri, wf, rho, out):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FuncFormatter

    plt.rcParams.update({
        "figure.facecolor": SURF, "axes.facecolor": SURF, "axes.edgecolor": GRIDC,
        "axes.labelcolor": INK2, "text.color": INK, "xtick.color": INK2,
        "ytick.color": INK2, "grid.color": GRIDC, "font.size": 9, "axes.titlesize": 10,
        "axes.titleweight": "bold", "axes.spines.top": False, "axes.spines.right": False,
    })
    fig, ax = plt.subplots(2, 2, figsize=(15, 9.2))
    fig.suptitle("MNQ overnight block: Sunday + Tuesday + Wednesday entries only",
                 fontsize=14, fontweight="bold", x=0.012, ha="left", y=0.985)
    fig.text(0.012, 0.952, "same 18:00 ET entry and 06:00 exit, only the set of entry "
             "weekdays changes | the three weekdays were chosen from the in-sample "
             "chart, so panels 3 and 4 test whether that choice is knowledge or fitting",
             fontsize=9.5, color=INK2, ha="left")
    for a in ax.ravel():
        a.grid(True, axis="y", lw=0.6, alpha=0.7)
        a.set_axisbelow(True)
    dollars = FuncFormatter(lambda v, _: f"${v:,.0f}")

    # 1 -- equity, in sample
    a = ax[0, 0]
    ends = []
    for sel, col, lab in ((None, C_BLUE, "ALL nights"), (PICK, C_AQUA, "SUN+TUE+WED"),
                          (REST, C_ORANGE, "MON+THU")):
        s = m["pnl"] if sel is None else m[m["dow"].isin(sel)]["pnl"]
        eq = s.cumsum()
        a.plot(eq.index, eq.values, color=col, lw=2)
        ends.append((eq.iloc[-1], col, f"{lab}  \\${eq.iloc[-1]:,.0f}"))
    a.set_xlim(m.index[0], m.index[-1] + pd.Timedelta(days=620))
    lo, hi = a.get_ylim()
    for i, (_, col, txt) in enumerate(sorted(ends, reverse=True)):
        a.annotate(txt, (m.index[-1], hi - (i + 1) * (hi - lo) * 0.08), xytext=(8, 0),
                   textcoords="offset points", ha="left", color=col, fontsize=8.5,
                   fontweight="bold")
    a.yaxis.set_major_formatter(dollars)
    a.set_title("1. Cumulative $ per contract, MNQ 2020-2026")
    a.set_ylabel("cumulative net $")

    # 2 -- weekday means, both eras
    a = ax[0, 1]
    ks = [6, 0, 1, 2, 3]
    for df, col, lab, off in ((m, C_BLUE, "MNQ 2020-2026", -0.2),
                              (q, C_ORANGE, "NQ 2015-2019 (OOS)", 0.2)):
        vals = [df[df["dow"] == k]["pnl"].mean() for k in ks]
        bars = a.bar(np.arange(len(ks)) + off, vals, width=0.38, color=col, label=lab)
        for i, k in enumerate(ks):
            if k not in PICK:
                bars[i].set_alpha(0.42)
    a.axhline(0, color=INK2, lw=1)
    a.set_xticks(range(len(ks)), [DOW[k] for k in ks])
    a.yaxis.set_major_formatter(dollars)
    a.set_title("2. Mean $ per night by weekday (solid = the chosen three)")
    a.legend(frameon=False)

    # 3 -- does weekday ranking survive the era change?
    a = ax[1, 0]
    a.grid(True, lw=0.6, alpha=0.7)
    a.scatter(tri["IS $/nt"], tri["OOS $/nt"], s=70, color=C_BLUE, zorder=3,
              edgecolor=SURF, lw=1.5)
    for _, r in tri.iterrows():
        hit = r["set"] == "Sun+Tue+Wed"
        a.annotate(r["set"], (r["IS $/nt"], r["OOS $/nt"]), xytext=(7, -3),
                   textcoords="offset points", fontsize=8,
                   color=C_ORANGE if hit else INK2,
                   fontweight="bold" if hit else "normal")
        if hit:
            a.scatter([r["IS $/nt"]], [r["OOS $/nt"]], s=140, facecolor="none",
                      edgecolor=C_ORANGE, lw=2, zorder=4)
    a.axhline(q["pnl"].mean(), color=INK2, lw=1, ls=":")
    a.axvline(m["pnl"].mean(), color=INK2, lw=1, ls=":")
    a.annotate("all-nights baseline", (m["pnl"].mean(), a.get_ylim()[0]), xytext=(4, 8),
               textcoords="offset points", color=INK2, fontsize=8)
    a.xaxis.set_major_formatter(dollars)
    a.yaxis.set_major_formatter(dollars)
    a.set_title(f"3. Each of the 10 weekday triples: in sample vs out of sample "
                f"(Spearman {rho:+.2f})")
    a.set_xlabel("MNQ 2020-2026, mean $ per night")
    a.set_ylabel("NQ 2015-2019, mean $ per night")

    # 4 -- walk-forward
    a = ax[1, 1]
    x = np.arange(len(wf))
    a.bar(x - 0.27, wf["all $/nt"], width=0.26, color=C_BLUE, label="all nights")
    a.bar(x, wf["adaptive $/nt"], width=0.26, color=C_AQUA,
          label="top 3 weekdays from prior years")
    a.bar(x + 0.27, wf["static STW $/nt"], width=0.26, color=C_ORANGE,
          label="static SUN+TUE+WED")
    a.axhline(0, color=INK2, lw=1)
    a.set_xticks(x, wf.index, fontsize=8)
    a.yaxis.set_major_formatter(dollars)
    a.set_title("4. Walk-forward by year -- weekday chosen only on prior data")
    a.set_ylabel("mean $ per night")
    a.legend(frameon=False, fontsize=8)

    fig.tight_layout(rect=(0, 0, 1, 0.94))
    fig.savefig(out, dpi=140)
    plt.close(fig)
    print(f"\nchart -> {out}")


if __name__ == "__main__":
    main()
