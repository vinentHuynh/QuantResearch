"""Trailing exit on the overnight block: does riding the high beat the 06:00 clock?

Fixed take-profits were answered in mnq_takeprofit_backtest.py -- every level lost,
both eras, because a target truncates the right tail of a drift edge whose entire P&L
IS the right tail. A trail is the other way to chase the giveback: it caps nothing on
the upside and only exits after the market has already come off a high.

Rules, one long per night:
  * entry = 18:00 ET reopen open;
  * a stop rides at (running high - trail), the running high starting at the entry;
  * optional arm: the trail only turns on once open profit has reached +$arm, so the
    first hours cannot stop you out on ordinary noise;
  * 06:00 ET flat if the trail never fires. The clock is still the backstop.

No-lookahead convention (this decides the result, so it is explicit):
  * the stop level on a bar is built from the running high AS OF THE PREVIOUS BAR
    CLOSE. A bar that makes a new high and then falls through the stop is not allowed
    to raise the stop first -- inside a 5-min bar the order of high and low is unknown,
    and crediting the high would be lookahead;
  * a bar that OPENS below the level fills at the open (gap-through, the realistic
    overnight-news case), else at the level;
  * one extra tick of slippage on every stop fill, plus the base 1-tick round trip
    charged in every arm including the baseline.

Trails are in DOLLARS PER CONTRACT (MNQ $2/pt: $200 = 100 index points). The NQ
2015-2019 arm scales every trail to the same PERCENT move and rescales P&L to today's
notional, the standard cross-era treatment in this repo.

Scoring is the paired t of (trail arm - baseline) on identical nights.

    python mnq_trailing_stop_backtest.py
    python mnq_trailing_stop_backtest.py --chart
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from mnq_takeprofit_backtest import DPP, TICK, COST, load_paths, stats

REPORTS = (Path(__file__).resolve().parents[2] / "reports")
TRAILS = [50, 100, 150, 200, 300, 400, 500, 750, None]      # $/contract; None = timed
ARMS = [0, 100, 200, 300, 500]                              # $ profit before trail arms
HEADLINE = [100, 200, 400]

C_BLUE, C_ORANGE, C_AQUA, C_YELLOW = "#2a78d6", "#eb6834", "#1baf7a", "#eda100"
INK, INK2, GRIDC = "#0b0b0b", "#52514e", "#d8d7d2"


def night_pnl(entry, path, trail_pts, arm_pts=0.0):
    """($ P&L gross of the base round trip, trail fired, bars held)."""
    if trail_pts is None:
        return (path[-1][3] - entry) * DPP, False, len(path)
    run_high = entry                       # running high as of the previous bar close
    for i, (o, h, l, c) in enumerate(path):
        if run_high - entry >= arm_pts:    # armed on last bar's information only
            lvl = run_high - trail_pts
            if l <= lvl:
                fill = min(o, lvl) - TICK
                return (fill - entry) * DPP, True, i + 1
        run_high = max(run_high, h)
    return (path[-1][3] - entry) * DPP, False, len(path)


def run(paths, trail, arm=0, ref=None):
    """Net $ per night. ref set -> old era: trail/arm scaled to %, P&L to today's notional."""
    pnl, fired, held = {}, {}, {}
    for s, entry, path in paths:
        scale = (entry / ref) if ref else 1.0
        t_pts = None if trail is None else trail / DPP * scale
        a_pts = arm / DPP * scale
        raw, f, n = night_pnl(entry, path, t_pts, a_pts)
        if ref is not None:
            raw = raw / entry * ref
        pnl[s], fired[s], held[s] = raw - COST, f, n
    return pd.Series(pnl), pd.Series(fired), pd.Series(held)


def era(name, paths, ref, arm=0):
    series = {t: run(paths, t, arm, ref) for t in TRAILS}
    base = series[None][0]
    print(f"\n{'='*114}\n{name}  |  {len(base):,} nights  |  trail arms at "
          f"{'entry (always on)' if arm == 0 else f'+${arm} open profit'}")
    print(f"{'trail $/ctr':<16}{'$/nt':>8}{'$/yr':>9}{'Shp':>7}{'PF':>7}{'hit%':>7}"
          f"{'MaxDD$':>9}{'worst':>9}{'best':>9}{'fires':>7}{'%nts':>7}{'hrs':>6}"
          f"{'d$/yr':>9}{'pair-t':>8}")
    for t in TRAILS:
        p, fired, held = series[t]
        st = stats(p, base)
        tag = "none [std]" if t is None else f"${t:,} ({t/DPP:.0f}p)"
        hrs = held[fired].mean() * 5 / 60 if fired.any() else np.nan
        print(f"{tag:<16}{st['mean']:>8.2f}{st['yr']:>9,.0f}{st['sharpe']:>7.2f}"
              f"{st['pf']:>7.3f}{st['hit']:>7.1f}{st['dd']:>9,.0f}{st['worst']:>9,.0f}"
              f"{st['best']:>9,.0f}{fired.sum():>7}{fired.mean()*100:>6.1f}%{hrs:>6.1f}"
              f"{st['delta']:>+9,.0f}{st['t']:>8.2f}")

    print("  on the nights the trail fired (what the early exit actually did):")
    for t in [x for x in TRAILS if x is not None]:
        p, fired, _ = series[t]
        f = fired[fired].index
        if len(f) == 0:
            continue
        d = p[f] - base[f]
        better = base[f] > p[f] + 1e-6
        print(f"    ${t:<5,} fired {len(f):>4} nights | vs holding ${d.mean():+7,.0f}"
              f"/night, ${d.sum():+9,.0f} total | holding beat the trail on "
              f"{better.sum():>4}/{len(f)} ({better.mean()*100:>3.0f}%) | trail exit "
              f"${p[f].mean():+6,.0f} avg vs ${base[f].mean():+6,.0f} held")
    return series


def arm_grid(paths, ref, label):
    """Trail width x arm threshold: does delaying the trail rescue it?"""
    base = run(paths, None, 0, ref)[0]
    print(f"\n{'-'*114}\n{label}: mean $/night by trail width (rows) x arm threshold "
          f"(cols), pair-t vs the timed exit in brackets   [baseline ${base.mean():.2f}]")
    print(f"{'trail':<10}" + "".join(f"{'arm +$'+str(a):>21}" for a in ARMS))
    for t in [x for x in TRAILS if x is not None]:
        cells = []
        for a in ARMS:
            p = run(paths, t, a, ref)[0]
            st = stats(p, base)
            cells.append(f"{st['mean']:>13.2f} [{st['t']:>5.2f}]")
        print(f"${t:<9,}" + "".join(f"{c:>21}" for c in cells))


def chart(mnq, nq, out):
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
    fig.suptitle("MNQ overnight block: trailing exit vs the 06:00 timed exit",
                 fontsize=14, fontweight="bold", x=0.012, ha="left", y=0.985)
    fig.text(0.012, 0.953, "long the 18:00 ET reopen, stop riding the running high by "
             "\\$X per contract (level from the PREVIOUS bar's high -- no intrabar "
             "lookahead), flat at 06:00 if it never fires | MNQ \\$2/pt, 1 tick "
             "slippage on stop fills", fontsize=9.5, color=INK2, ha="left")
    for a in ax.ravel():
        a.grid(True, axis="y", lw=0.6, alpha=0.7)
        a.set_axisbelow(True)
    lvls = [t for t in TRAILS if t is not None]
    dollars = FuncFormatter(lambda v, _: f"${v:,.0f}")

    # 1 -- $/night vs trail width, both eras
    a = ax[0, 0]
    for series, col, lab in ((mnq, C_BLUE, "MNQ 2020-2026"),
                             (nq, C_ORANGE, "NQ 2015-2019 (OOS, trail scaled to %)")):
        a.plot(lvls, [series[t][0].mean() for t in lvls], color=col, lw=2,
               marker="o", ms=6, label=lab)
        b = series[None][0].mean()
        a.axhline(b, color=col, lw=1.2, ls=":")
        a.annotate(f"{lab.split()[0]} timed exit  ${b:.2f}", (lvls[0], b), xytext=(2, 5),
                   textcoords="offset points", ha="left", color=col, fontsize=8,
                   fontweight="bold")
    a.yaxis.set_major_formatter(dollars)
    a.xaxis.set_major_formatter(dollars)
    a.set_title("1. Mean night by trail width, against doing nothing")
    a.set_xlabel("trail ($ per contract off the running high)")
    a.set_ylabel("mean $ per night, per contract")
    a.legend(frameon=False, loc="lower right")

    # 2 -- equity curves
    a = ax[1, 0]
    ends = []
    for t, col in ((None, C_BLUE), (HEADLINE[0], C_ORANGE),
                   (HEADLINE[1], C_AQUA), (HEADLINE[2], C_YELLOW)):
        eq = mnq[t][0].cumsum()
        a.plot(eq.index, eq.values, color=col, lw=2)
        tag = "timed exit only" if t is None else "\\$%d trail" % t
        ends.append((eq.iloc[-1], col, f"{tag}  \\${eq.iloc[-1]:,.0f}"))
    span = mnq[None][0].cumsum()
    a.set_xlim(span.index[0], span.index[-1] + pd.Timedelta(days=430))
    lo, hi = a.get_ylim()
    for i, (_, col, txt) in enumerate(sorted(ends, reverse=True)):
        a.annotate(txt, (span.index[-1], hi - (i + 1) * (hi - lo) * 0.075),
                   xytext=(8, 0), textcoords="offset points", ha="left", color=col,
                   fontsize=8.5, fontweight="bold")
    a.yaxis.set_major_formatter(dollars)
    a.set_title("2. Cumulative $ per contract, MNQ 2020-2026")
    a.set_ylabel("cumulative net $")

    # 3 -- how often it fires, and how early it ends the night
    a = ax[0, 1]
    fires = [mnq[t][1].mean() * 100 for t in lvls]
    bars = a.bar([f"${v}" for v in lvls], fires, color=C_BLUE, width=0.72)
    for t, col in zip(HEADLINE, (C_ORANGE, C_AQUA, C_YELLOW)):
        bars[lvls.index(t)].set_color(col)
    for i, (t, v) in enumerate(zip(lvls, fires)):
        p, f, held = mnq[t]
        a.annotate(f"{v:.0f}%\n{held[f].mean()*5/60:.1f}h", (i, v), xytext=(0, 3),
                   textcoords="offset points", ha="center", fontsize=8, color=INK2)
    a.yaxis.set_major_formatter(PercentFormatter())
    a.set_ylim(0, 108)
    a.set_title("3. Share of nights the trail fires (and mean hours held when it does)")
    a.set_xlabel("trail ($ per contract)")
    a.set_ylabel("% of nights")

    # 4 -- ledger on the nights it fired
    a = ax[1, 1]
    base = mnq[None][0]
    saved, lost = [], []
    for t in lvls:
        p, f, _ = mnq[t]
        i = f[f].index
        d = p[i] - base[i]
        saved.append(d[d > 0].sum())
        lost.append(d[d < 0].sum())
    a.bar([f"${v}" for v in lvls], saved, color=C_AQUA, width=0.72,
          label="saved: night kept falling after the exit")
    a.bar([f"${v}" for v in lvls], lost, color=C_ORANGE, width=0.72,
          label="lost: night recovered without you")
    a.plot(range(len(lvls)), np.array(saved) + np.array(lost), color=INK, lw=2,
           marker="o", ms=5, label="net")
    a.axhline(0, color=INK2, lw=1)
    a.yaxis.set_major_formatter(dollars)
    a.set_title("4. Trailing ledger on the nights it fired")
    a.set_xlabel("trail ($ per contract)")
    a.set_ylabel("total $ per contract vs holding to 06:00")
    a.legend(frameon=False, loc="lower right", fontsize=8)

    fig.tight_layout(rect=(0, 0, 1, 0.94))
    fig.savefig(out, dpi=140)
    plt.close(fig)
    print(f"\nchart -> {out}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chart", action="store_true")
    ap.add_argument("--arm", type=int, default=0, help="$ open profit before the trail arms")
    ap.add_argument("--min-bars", type=int, default=120)
    args = ap.parse_args()
    REPORTS.mkdir(exist_ok=True)

    pn = load_paths("MNQ_5min_databento.parquet", args.min_bars)
    po = [r for r in load_paths("NQ_5min_databento.parquet", args.min_bars)
          if r[0] < pn[0][0]]
    ref = float(np.median([e for s, e, _ in pn if s.year >= 2024]))

    mnq = era("IN-SAMPLE  MNQ 2020-2026", pn, None, args.arm)
    nq = era(f"OUT-OF-SAMPLE  NQ 2015-2019 (scaled to the same % move, ref {ref:,.0f})",
             po, ref, args.arm)
    arm_grid(pn, None, "IN-SAMPLE MNQ")
    arm_grid(po, ref, "OUT-OF-SAMPLE NQ")

    if args.chart:
        chart(mnq, nq, REPORTS / "mnq_trailing_stop.png")


if __name__ == "__main__":
    main()
