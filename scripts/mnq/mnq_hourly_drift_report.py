"""Is "the overnight session trends long" safe to assume for ANY hold over an hour?

The block backtests only ever tested one window, 18:00->06:00 ET. That is not enough
to justify treating overnight longs as a tailwind for other strategies. This report
asks the general version:

  1. clock-hour drift -- mean return of every hour of the 24h day, MNQ and (out of
     sample) NQ, in basis points so the eras are comparable;
  2. the hold grid -- start hour x hold length (1,2,3,4,6,8,12h), mean $ per trade and
     its t-stat, so a strategy holding N hours from hour H can look up its own cell;
  3. signal vs noise -- drift per hold divided by the sd of that same hold, which is
     what decides whether the bias is tradable or merely present;
  4. era stability -- 2020-2022 vs 2023-2026 vs NQ 2015-2019, because a drift measured
     only through one bull run is a fact about that bull run.

Hourly bars are built from the 5-min file (open = first, close = last, hours with
fewer than 10 of 12 bars dropped). A hold is only counted when its bars are
contiguous on the clock, so nothing spans the 17:00-18:00 CME halt or a weekend.

No costs are charged anywhere here -- this measures the market's own bias, not a
strategy. Any real strategy pays the round trip on top.

    python mnq_hourly_drift_report.py
    python mnq_hourly_drift_report.py --chart
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path(__file__).with_name("data")
REPORTS = Path(__file__).with_name("reports")
DPP = 2.0
HOLDS = [1, 2, 3, 4, 6, 8, 12]
NIGHT = [18, 19, 20, 21, 22, 23, 0, 1, 2, 3, 4, 5]
DAY = [9, 10, 11, 12, 13, 14, 15]

C_BLUE, C_ORANGE, C_AQUA, C_YELLOW = "#2a78d6", "#eb6834", "#1baf7a", "#eda100"
INK, INK2, GRIDC = "#0b0b0b", "#52514e", "#d8d7d2"
# diverging: blue pole <-> red pole, neutral gray midpoint (never a hue at the middle)
DIVERGING = ["#104281", "#2a78d6", "#9ec5f4", "#f0efec", "#f3b4b4", "#e34948", "#8f1f1f"]


def hourly(fname: str) -> pd.DataFrame:
    """5-min bars -> clock-hour bars with per-hour return in points and bps."""
    d = pd.read_parquet(DATA / fname).sort_index()
    h = d.resample("1h").agg(open=("open", "first"), close=("close", "last"),
                             n=("close", "count"))
    h = h[h["n"] >= 10].copy()
    h["pts"] = h["close"] - h["open"]
    h["bps"] = (h["close"] / h["open"] - 1) * 1e4
    h["hour"] = h.index.hour
    return h


def tstat(x: np.ndarray) -> float:
    sd = x.std(ddof=1)
    return float(x.mean() / sd * np.sqrt(len(x))) if sd > 0 and len(x) > 1 else 0.0


def by_hour(h: pd.DataFrame) -> pd.DataFrame:
    g = h.groupby("hour")
    out = pd.DataFrame({
        "n": g.size(),
        "mean_bps": g["bps"].mean(),
        "sd_bps": g["bps"].std(ddof=1),
        "mean_usd": g["pts"].mean() * DPP,
        "win": g["bps"].apply(lambda s: (s > 0).mean() * 100),
        "t": g["bps"].apply(lambda s: tstat(s.to_numpy())),
    })
    return out


def holds(h: pd.DataFrame) -> dict:
    """{(start_hour, length): dict of stats} over contiguous clock-hour runs."""
    idx = h.index.to_numpy()
    op, cl, hr = h["open"].to_numpy(), h["close"].to_numpy(), h["hour"].to_numpy()
    res = {}
    for L in HOLDS:
        if len(h) <= L:
            continue
        # contiguity: last bar of the run must start exactly L-1 hours after the first
        ok = (idx[L - 1:] - idx[:len(idx) - L + 1]) == np.timedelta64(L - 1, "h")
        pts = cl[L - 1:] - op[:len(op) - L + 1]
        bps = (cl[L - 1:] / op[:len(op) - L + 1] - 1) * 1e4
        start = hr[:len(hr) - L + 1]
        for s in range(24):
            m = ok & (start == s)
            if m.sum() < 100:
                continue
            b, p = bps[m], pts[m]
            res[(s, L)] = {"n": int(m.sum()), "usd": float(p.mean() * DPP),
                           "bps": float(b.mean()), "sd_bps": float(b.std(ddof=1)),
                           "t": tstat(b), "win": float((b > 0).mean() * 100),
                           "ratio": float(b.mean() / b.std(ddof=1))}
    return res


def print_hours(tab: pd.DataFrame, name: str) -> None:
    print(f"\n{'='*96}\n{name}: drift by clock hour (ET)")
    print(f"{'hr':<5}{'n':>7}{'mean bps':>11}{'sd bps':>9}{'mean $':>9}{'win%':>7}"
          f"{'t':>7}   {'session'}")
    order = list(range(18, 24)) + list(range(0, 18))
    for hh in order:
        if hh not in tab.index:
            continue
        r = tab.loc[hh]
        tag = "OVERNIGHT" if hh in NIGHT else ("RTH" if hh in DAY else "")
        star = " *" if abs(r["t"]) >= 2 else ""
        print(f"{hh:<5}{int(r['n']):>7}{r['mean_bps']:>11.2f}{r['sd_bps']:>9.1f}"
              f"{r['mean_usd']:>9.2f}{r['win']:>7.1f}{r['t']:>7.2f}   {tag}{star}")


def print_holds(res: dict, name: str) -> None:
    print(f"\n{'-'*96}\n{name}: hold grid -- mean $ per trade [t-stat], long, no costs")
    print(f"{'start':<7}" + "".join(f"{str(L)+'h':>16}" for L in HOLDS))
    for s in list(range(18, 24)) + list(range(0, 18)):
        cells = [res.get((s, L)) for L in HOLDS]
        if not any(cells):
            continue
        row = "".join(f"{c['usd']:>10.2f} [{c['t']:>4.1f}]" if c else f"{'-':>16}"
                      for c in cells)
        print(f"{s:02d}:00  {row}")


def summarize(h: pd.DataFrame, res: dict, name: str) -> None:
    night = h[h["hour"].isin(NIGHT)]
    day = h[h["hour"].isin(DAY)]
    print(f"\n  {name}: overnight hours mean {night['bps'].mean():+.2f} bps/h "
          f"(t {tstat(night['bps'].to_numpy()):+.2f}, {len(night):,} hours) | "
          f"RTH hours mean {day['bps'].mean():+.2f} bps/h "
          f"(t {tstat(day['bps'].to_numpy()):+.2f}, {len(day):,} hours)")
    for L in (1, 2, 4, 12):
        cells = [v for (s, l), v in res.items() if l == L and s in NIGHT]
        if not cells:
            continue
        w = np.array([c["n"] for c in cells], float)
        m = np.average([c["bps"] for c in cells], weights=w)
        rt = np.average([c["ratio"] for c in cells], weights=w)
        wn = np.average([c["win"] for c in cells], weights=w)
        print(f"    overnight {L:>2}h holds: {m:+.2f} bps mean, win {wn:.1f}%, "
              f"drift/sd {rt:+.3f}  -> drift is {abs(rt)*100:.1f}% of one "
              f"standard deviation of the same trade")


def chart(mnq_h, nq_h, mnq_res, nq_res, out):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import LinearSegmentedColormap, TwoSlopeNorm
    from matplotlib.ticker import FuncFormatter

    plt.rcParams.update({
        "figure.facecolor": "#fcfcfb", "axes.facecolor": "#fcfcfb",
        "axes.edgecolor": GRIDC, "axes.labelcolor": INK2, "text.color": INK,
        "xtick.color": INK2, "ytick.color": INK2, "grid.color": GRIDC,
        "font.size": 9, "axes.titlesize": 10, "axes.titleweight": "bold",
        "axes.spines.top": False, "axes.spines.right": False,
    })
    fig, ax = plt.subplots(2, 2, figsize=(15, 9.4))
    fig.suptitle("Is the overnight long bias safe to assume for holds over an hour?",
                 fontsize=14, fontweight="bold", x=0.012, ha="left", y=0.985)
    fig.text(0.012, 0.952, "MNQ 5-min 2020-2026 in sample, NQ 2015-2019 out of sample | "
             "returns in bps so the eras compare | long only, no costs charged -- this "
             "is the market's bias, not a strategy", fontsize=9.5, color=INK2, ha="left")
    order = list(range(18, 24)) + list(range(0, 18))
    x = np.arange(len(order))

    # 1 -- drift by clock hour, both eras
    a = ax[0, 0]
    a.grid(True, axis="y", lw=0.6, alpha=0.7)
    a.set_axisbelow(True)
    for tab, col, lab, off in ((mnq_h, C_BLUE, "MNQ 2020-2026", -0.2),
                               (nq_h, C_ORANGE, "NQ 2015-2019 (OOS)", 0.2)):
        y = [tab["mean_bps"].get(hh, np.nan) for hh in order]
        a.bar(x + off, y, width=0.38, color=col, label=lab)
    a.axhline(0, color=INK2, lw=1)
    a.axvspan(-0.6, 11.6, color=C_AQUA, alpha=0.07)
    a.annotate("overnight block 18:00-06:00", (0.2, a.get_ylim()[1] * 0.9),
               color=INK2, fontsize=8.5, fontweight="bold")
    a.set_xticks(x)
    a.set_xticklabels([f"{hh:02d}" for hh in order], fontsize=7.5)
    a.set_title("1. Mean return by clock hour (ET) -- the bias is not spread evenly")
    a.set_xlabel("hour of day, ET")
    a.set_ylabel("mean return, bps per hour")
    a.legend(frameon=False, ncol=2)

    # 2 -- hold grid heatmap, MNQ
    a = ax[0, 1]
    cmap = LinearSegmentedColormap.from_list("div", DIVERGING[::-1])
    grid = np.full((len(order), len(HOLDS)), np.nan)
    for i, s in enumerate(order):
        for j, L in enumerate(HOLDS):
            c = mnq_res.get((s, L))
            if c:
                grid[i, j] = c["usd"]
    v = np.nanmax(np.abs(grid))
    im = a.imshow(grid, cmap=cmap, norm=TwoSlopeNorm(0, -v, v), aspect="auto")
    for i, s in enumerate(order):
        for j, L in enumerate(HOLDS):
            c = mnq_res.get((s, L))
            if not c:
                continue
            a.text(j, i, f"{c['usd']:.0f}" + ("*" if abs(c["t"]) >= 2 else ""),
                   ha="center", va="center", fontsize=7.5,
                   color="#ffffff" if abs(c["usd"]) > v * 0.55 else INK)
    a.set_xticks(range(len(HOLDS)), [f"{L}h" for L in HOLDS])
    a.set_yticks(range(len(order)), [f"{hh:02d}:00" for hh in order], fontsize=7.5)
    a.set_title("2. MNQ mean $ per long trade by start hour x hold (* |t| >= 2)")
    a.set_xlabel("hold length")
    a.set_ylabel("entry hour, ET")
    a.grid(False)
    fig.colorbar(im, ax=a, fraction=0.035, pad=0.02,
                 format=FuncFormatter(lambda t, _: f"${t:,.0f}"))

    # 3 -- win rate vs hold length, overnight starts vs RTH starts
    a = ax[1, 0]
    a.grid(True, axis="y", lw=0.6, alpha=0.7)
    a.set_axisbelow(True)
    for res, hrs, col, lab in ((mnq_res, NIGHT, C_BLUE, "MNQ overnight starts"),
                               (mnq_res, DAY, C_ORANGE, "MNQ RTH starts"),
                               (nq_res, NIGHT, C_AQUA, "NQ overnight starts (OOS)")):
        y = []
        for L in HOLDS:
            c = [v for (s, l), v in res.items() if l == L and s in hrs]
            w = np.array([q["n"] for q in c], float)
            y.append(np.average([q["win"] for q in c], weights=w) if c else np.nan)
        a.plot(HOLDS, y, color=col, lw=2, marker="o", ms=6, label=lab)
        a.annotate(f"{y[-1]:.0f}%", (HOLDS[-1], y[-1]), xytext=(6, 0),
                   textcoords="offset points", color=col, fontsize=8.5,
                   fontweight="bold")
    a.axhline(50, color=INK2, lw=1, ls="--")
    a.annotate("coin flip", (HOLDS[0], 50), xytext=(0, 4), textcoords="offset points",
               color=INK2, fontsize=8)
    a.set_title("3. Share of long holds that end green")
    a.set_xlabel("hold length (hours)")
    a.set_ylabel("% of trades")
    a.legend(frameon=False, loc="lower right")

    # 4 -- drift as a share of the same trade's own sd
    a = ax[1, 1]
    a.grid(True, axis="y", lw=0.6, alpha=0.7)
    a.set_axisbelow(True)
    for res, col, lab in ((mnq_res, C_BLUE, "MNQ 2020-2026"),
                          (nq_res, C_ORANGE, "NQ 2015-2019 (OOS)")):
        y = []
        for L in HOLDS:
            c = [v for (s, l), v in res.items() if l == L and s in NIGHT]
            w = np.array([q["n"] for q in c], float)
            y.append(np.average([q["ratio"] for q in c], weights=w) if c else np.nan)
        a.plot(HOLDS, y, color=col, lw=2, marker="o", ms=6, label=lab)
        a.annotate(f"{y[-1]:.3f}", (HOLDS[-1], y[-1]), xytext=(6, 0),
                   textcoords="offset points", color=col, fontsize=8.5,
                   fontweight="bold")
    a.axhline(0, color=INK2, lw=1)
    a.set_title("4. Overnight drift per trade, as a fraction of that trade's own sd")
    a.set_xlabel("hold length (hours)")
    a.set_ylabel("mean / sd of the same hold")
    a.legend(frameon=False)
    a.annotate("a 12h hold's drift is a rounding error next to its own noise:\n"
               "the bias is real in aggregate, invisible in any single trade",
               (HOLDS[0], 0.02), fontsize=8.5, color=INK2)

    fig.tight_layout(rect=(0, 0, 1, 0.94))
    fig.savefig(out, dpi=140)
    plt.close(fig)
    print(f"\nchart -> {out}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chart", action="store_true")
    args = ap.parse_args()
    REPORTS.mkdir(exist_ok=True)

    mnq = hourly("MNQ_5min_databento.parquet")
    nq = hourly("NQ_5min_databento.parquet")
    nq = nq[nq.index < mnq.index[0]]

    mh, nh = by_hour(mnq), by_hour(nq)
    mr, nr = holds(mnq), holds(nq)
    print_hours(mh, "IN-SAMPLE  MNQ 2020-2026")
    print_hours(nh, "OUT-OF-SAMPLE  NQ 2015-2019")
    print_holds(mr, "IN-SAMPLE MNQ")
    print_holds(nr, "OUT-OF-SAMPLE NQ")

    print(f"\n{'='*96}\nSUMMARY")
    summarize(mnq, mr, "MNQ 2020-2026")
    summarize(nq, nr, "NQ 2015-2019 (OOS)")
    for lo, hi in ((2020, 2022), (2023, 2026)):
        sub = mnq[(mnq.index.year >= lo) & (mnq.index.year <= hi)]
        summarize(sub, holds(sub), f"MNQ {lo}-{hi}")

    if args.chart:
        chart(mh, nh, mr, nr, REPORTS / "mnq_hourly_drift.png")


if __name__ == "__main__":
    main()
