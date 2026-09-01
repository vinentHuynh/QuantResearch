"""Fixed take-profit on the overnight block, with the 06:00 timed exit as backstop.

Theory under test: the giveback report (mnq_overnight_giveback_report.py) showed the
06:00 close sits a median 43 pts / mean 67 pts under the night's own high. If some of
that ceiling is reachable, a resting limit at +$100 / +$200 / +$300 should collect it.

Targets are in DOLLARS PER CONTRACT, which is how a target is actually set: on MNQ at
$2/pt, $100 = 50 index points, $200 = 100 pts, $300 = 150 pts.

Rules, one position per night, long only:
  * entry  = 18:00 ET reopen open (same fill every other script in this repo uses);
  * TP     = resting limit at entry + tp/$2 points, live for the whole window;
  * exit   = 06:00 ET if the limit never fills. The clock always wins in the end.

Fill realism (the whole answer lives here):
  * a limit only fills when trade prints a tick THROUGH it -- high >= level + tick --
    so nights that merely tag the level to the tick are counted as misses (queue risk);
  * a gap-up bar that OPENS above the level fills at the open, which is better than
    the level, and that gift is kept because it is real;
  * base 1-tick round trip charged on every night in every arm, so cost never decides
    the comparison.

Truncation is the point of the test: a TP caps winners but does nothing about losers,
so it can only help if the capped upside is worth less than the nights it rescues from
a later fade. The scoring is a paired t of (TP arm - baseline) on identical nights --
market noise cancels and only the TP's effect is measured. The counterfactual line
prints what the capped nights went on to do, which is where truncation usually dies.

Cross-era: NQ 2015-2020 traded near 4,400, so a 100-pt TP there is a completely
different trade. The out-of-sample arm scales every TP to the SAME PERCENT move and
rescales P&L to today's notional, exactly as mnq_hard_stop_backtest.py does.

    python mnq_takeprofit_backtest.py
    python mnq_takeprofit_backtest.py --chart
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path(__file__).with_name("data")
REPORTS = Path(__file__).with_name("reports")
DPP, TICK = 2.0, 0.25
COST = TICK * DPP
NIGHT_HOURS = [18, 19, 20, 21, 22, 23, 0, 1, 2, 3, 4, 5]
HEADLINE = [100, 200, 300, None]                       # $/contract; None = timed exit
GRID = [50, 100, 150, 200, 300, 400, 500, 750, 1000, None]

C_BLUE, C_ORANGE, C_AQUA, C_YELLOW = "#2a78d6", "#eb6834", "#1baf7a", "#eda100"
INK, INK2, GRIDC = "#0b0b0b", "#52514e", "#d8d7d2"


def load_paths(fname: str, min_bars: int = 120):
    """Per session: date, entry price, ordered 5-min OHLC path 18:00 -> 06:00."""
    d = pd.read_parquet(DATA / fname).sort_index()
    idx = d.index
    keep = np.isin(idx.hour, NIGHT_HOURS)
    d = d[keep].copy()
    d["sess"] = (idx[keep] - pd.Timedelta(hours=18)).normalize()
    out = []
    for s, g in d.groupby("sess"):
        if len(g) < min_bars:
            continue
        out.append((s, float(g["open"].iloc[0]),
                    g[["open", "high", "low", "close"]].to_numpy()))
    return out


def night_pnl(entry: float, path: np.ndarray, tp_pts: float | None) -> tuple[float, bool]:
    """($ P&L per contract gross of the base round trip, did the limit fill)."""
    if tp_pts is None:
        return (path[-1][3] - entry) * DPP, False
    lvl = entry + tp_pts
    for o, h, l, c in path:
        if h >= lvl + TICK:                     # must trade THROUGH the limit
            fill = max(o, lvl)                  # gap-up opens above -> better fill
            return (fill - entry) * DPP, True
    return (path[-1][3] - entry) * DPP, False


def run(paths, tp, ref=None):
    """Net $ P&L per night; tp in $/contract.

    ref set -> old era: the target is scaled to the SAME PERCENT move (a $200 target on
    NQ at 4,400 is a far bigger move than on MNQ at 24,000) and P&L is rescaled to
    today's notional, so the two eras are comparable rather than merely both present.
    """
    pnl, hit = {}, {}
    for s, entry, path in paths:
        pts = None if tp is None else tp / DPP
        tp_pts = None if tp is None else (pts * (entry / ref) if ref else pts)
        raw, filled = night_pnl(entry, path, tp_pts)
        if ref is not None:
            raw = raw / entry * ref
        pnl[s], hit[s] = raw - COST, filled
    return pd.Series(pnl), pd.Series(hit)


def stats(p: pd.Series, base: pd.Series) -> dict:
    a = p.values
    w, l = a[a > 0], a[a < 0]
    eq = p.cumsum()
    j = pd.concat([p, base], axis=1, keys=["c", "b"]).dropna()
    d = j["c"] - j["b"]
    sd = d.std(ddof=1)
    return {"mean": a.mean(), "yr": a.mean() * 252,
            "sharpe": a.mean() / a.std(ddof=1) * np.sqrt(252),
            "pf": w.sum() / abs(l.sum()) if len(l) else np.inf,
            "dd": float((eq - eq.cummax()).min()), "worst": a.min(),
            "best": a.max(), "hit": (a > 0).mean() * 100,
            "t": d.mean() / sd * np.sqrt(len(d)) if sd > 0 else 0.0,
            "delta": (a.mean() - base.mean()) * 252}


def era(name, paths, ref, levels):
    series = {tp: run(paths, tp, ref) for tp in levels}
    base = series[None][0]
    print(f"\n{'='*112}\n{name}  |  {len(base):,} nights")
    print(f"{'TP $/ctr':<17}{'$/nt':>8}{'$/yr':>9}{'Shp':>7}{'PF':>7}{'hit%':>7}{'MaxDD$':>9}"
          f"{'worst':>9}{'best':>9}{'fills':>7}{'%nts':>7}{'d$/yr':>9}{'pair-t':>8}")
    for tp in levels:
        p, filled = series[tp]
        st = stats(p, base)
        tag = "none [std]" if tp is None else f"+${tp:,} ({tp/DPP:.0f}p)"
        print(f"{tag:<17}{st['mean']:>8.2f}{st['yr']:>9,.0f}{st['sharpe']:>7.2f}"
              f"{st['pf']:>7.3f}{st['hit']:>7.1f}{st['dd']:>9,.0f}{st['worst']:>9,.0f}"
              f"{st['best']:>9,.0f}{filled.sum():>7}{filled.mean()*100:>6.1f}%"
              f"{st['delta']:>+9,.0f}{st['t']:>8.2f}")

    print("  counterfactual on the nights the limit filled "
          "(what capping actually cost or saved):")
    for tp in [t for t in levels if t is not None]:
        p, filled = series[tp]
        f = filled[filled].index
        if len(f) == 0:
            continue
        diff = p[f] - base[f]                     # + = TP helped, - = TP truncated
        better = (base[f] > p[f] + 1e-6)
        print(f"    +${tp:<5,} filled {len(f):>4} nights | vs holding "
              f"${diff.mean():+7,.0f}/night, ${diff.sum():+9,.0f} total | holding beat "
              f"the TP on {better.sum():>4}/{len(f)} ({better.mean()*100:>3.0f}%) | "
              f"those nights closed ${base[f].mean():+7,.0f} avg")
    return series


def chart(mnq_series, nq_series, grid, out):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FuncFormatter, PercentFormatter

    plt.rcParams.update({
        "figure.facecolor": "#fcfcfb", "axes.facecolor": "#fcfcfb",
        "axes.edgecolor": GRIDC, "axes.labelcolor": INK2, "text.color": INK,
        "xtick.color": INK2, "ytick.color": INK2, "grid.color": GRIDC,
        "font.size": 9, "axes.titlesize": 10, "axes.titleweight": "bold",
        "axes.spines.top": False, "axes.spines.right": False,
    })
    fig, ax = plt.subplots(2, 2, figsize=(14.5, 9))
    fig.suptitle("MNQ overnight block: fixed take-profit vs the 06:00 timed exit",
                 fontsize=14, fontweight="bold", x=0.012, ha="left", y=0.985)
    fig.text(0.012, 0.953, "long the 18:00 ET reopen, resting limit at +$X per contract "
             "(fills only on a tick through it), flat at 06:00 either way | MNQ $2/pt so "
             "$100 = 50 index points | 1-tick round trip charged in every arm",
             fontsize=9.5, color=INK2, ha="left")
    for a in ax.ravel():
        a.grid(True, axis="y", lw=0.6, alpha=0.7)
        a.set_axisbelow(True)
    lvls = [t for t in grid if t is not None]
    dollars = FuncFormatter(lambda v, _: f"${v:,.0f}")

    # 1 -- $/night across the TP grid, both eras, vs their own baselines
    a = ax[0, 0]
    for series, col, lab in ((mnq_series, C_BLUE, "MNQ 2020-2026"),
                             (nq_series, C_ORANGE, "NQ 2015-2019 (OOS, TP scaled to %)")):
        y = [series[t][0].mean() for t in lvls]
        a.plot(lvls, y, color=col, lw=2, marker="o", ms=6, label=lab)
        a.axhline(series[None][0].mean(), color=col, lw=1.2, ls=":")
        a.annotate(f"{lab.split()[0]} timed exit  ${series[None][0].mean():.2f}",
                   (lvls[0], series[None][0].mean()), xytext=(2, 5),
                   textcoords="offset points", ha="left", color=col, fontsize=8,
                   fontweight="bold")
    a.yaxis.set_major_formatter(dollars)
    a.xaxis.set_major_formatter(dollars)
    a.set_title("1. Mean night, target by target, against the do-nothing baseline")
    a.set_xlabel("take-profit ($ per contract above entry)")
    a.set_ylabel("mean $ per night, per contract")
    a.legend(frameon=False, loc="lower right")

    # 2 -- equity curves, headline levels, in-sample
    a = ax[1, 0]
    ends = []
    for tp, col in ((None, C_BLUE), (100, C_ORANGE), (200, C_AQUA), (300, C_YELLOW)):
        eq = mnq_series[tp][0].cumsum()
        a.plot(eq.index, eq.values, color=col, lw=2)
        # escape every $: a pair of them on one line is read as mathtext
        tag = "timed exit only" if tp is None else "+\\$%d TP" % tp
        ends.append((eq.iloc[-1], col, f"{tag}  \\${eq.iloc[-1]:,.0f}"))
    # label in the right margin, spread vertically so the four never collide
    span = mnq_series[None][0].cumsum()
    a.set_xlim(span.index[0], span.index[-1] + pd.Timedelta(days=430))
    lo, hi = a.get_ylim()
    for i, (_, col, txt) in enumerate(sorted(ends, reverse=True)):
        a.annotate(txt, (span.index[-1], hi - (i + 1) * (hi - lo) * 0.075),
                   xytext=(8, 0), textcoords="offset points", ha="left",
                   color=col, fontsize=8.5, fontweight="bold")
    a.yaxis.set_major_formatter(dollars)
    a.set_title("2. Cumulative $ per contract, MNQ 2020-2026")
    a.set_ylabel("cumulative net $")

    # 3 -- how often each limit ever fills
    a = ax[0, 1]
    y = [mnq_series[t][1].mean() * 100 for t in lvls]
    bars = a.bar([f"${v}" for v in lvls], y, color=C_BLUE, width=0.72)
    for tp, col in ((100, C_ORANGE), (200, C_AQUA), (300, C_YELLOW)):
        bars[lvls.index(tp)].set_color(col)
    for i, v in enumerate(y):
        a.annotate(f"{v:.0f}%", (i, v), xytext=(0, 3), textcoords="offset points",
                   ha="center", fontsize=8, color=INK2)
    a.yaxis.set_major_formatter(PercentFormatter())
    a.set_title("3. Share of nights the limit ever fills")
    a.set_xlabel("take-profit ($ per contract)")
    a.set_ylabel("% of nights")

    # 4 -- what the capped nights went on to do
    a = ax[1, 1]
    base = mnq_series[None][0]
    cost, saved = [], []
    for t in lvls:
        p, f = mnq_series[t]
        i = f[f].index
        d = p[i] - base[i]
        cost.append(d[d < 0].sum())
        saved.append(d[d > 0].sum())
    a.bar([f"${v}" for v in lvls], saved, color=C_AQUA, width=0.72,
          label="saved: night faded after the fill")
    a.bar([f"${v}" for v in lvls], cost, color=C_ORANGE, width=0.72,
          label="lost: night kept going without you")
    net = np.array(saved) + np.array(cost)
    a.plot(range(len(lvls)), net, color=INK, lw=2, marker="o", ms=5, label="net")
    a.axhline(0, color=INK2, lw=1)
    a.yaxis.set_major_formatter(dollars)
    a.set_title("4. Truncation ledger on the nights that filled")
    a.set_xlabel("take-profit ($ per contract)")
    a.set_ylabel("total $ per contract vs holding to 06:00")
    a.legend(frameon=False, loc="lower left", fontsize=8)

    fig.tight_layout(rect=(0, 0, 1, 0.94))
    fig.savefig(out, dpi=140)
    plt.close(fig)
    print(f"\nchart -> {out}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chart", action="store_true")
    ap.add_argument("--min-bars", type=int, default=120)
    args = ap.parse_args()
    REPORTS.mkdir(exist_ok=True)

    pn = load_paths("MNQ_5min_databento.parquet", args.min_bars)
    po = [r for r in load_paths("NQ_5min_databento.parquet", args.min_bars)
          if r[0] < pn[0][0]]
    ref = float(np.median([e for s, e, _ in pn if s.year >= 2024]))

    levels = sorted({*GRID, *HEADLINE} - {None}, key=float) + [None]
    mnq = era("IN-SAMPLE  MNQ 2020-2026", pn, None, levels)
    nq = era(f"OUT-OF-SAMPLE  NQ 2015-2019 (TP scaled to the same % move, "
             f"ref {ref:,.0f})", po, ref, levels)

    if args.chart:
        chart(mnq, nq, levels, REPORTS / "mnq_takeprofit.png")


if __name__ == "__main__":
    main()
