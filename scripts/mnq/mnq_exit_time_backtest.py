"""Exit clock test: 00:00 and 01:00 ET vs the 06:00 baseline, same 18:00 entry.

The block always enters at the 18:00 ET reopen. The only thing changed here is WHEN it
goes flat. Three headline arms:

    midnight  18:00 -> 00:00 ET   (6h)
    1am       18:00 -> 01:00 ET   (7h)
    base      18:00 -> 06:00 ET   (12h, the validated window)

Motive: the hourly drift map (mnq_hourly_drift_report.py) found the overnight bias is
not spread evenly -- 23:00-02:00 carries it in both eras while 03:00-05:00 carries
nothing -- so a shorter window might keep the paying hours and skip the dead ones. The
giveback report separately found the overnight high clusters at the 18:00 and 05:00
hours, which cuts the other way.

Cutting the window is not free: the position no longer spans the hours where the drift
compounds, and the same 1-tick round trip is charged over a smaller move.

A clock scan of every exit hour is printed underneath the headline table. It is there
to stop a single lucky clock from reading as a discovery -- an exit hour is only
interesting if its neighbours agree and the other era agrees. Reading the max off that
scan and calling it the answer is exactly the optimisation the permutation test in
mnq_window_scan_backtest.py already rejected.

Exits are wall-clock, DST-correct (a fixed +6h would drift an hour twice a year), and
fill at the open of the bar on the boundary, the same convention the entry uses. Nights
whose exit bar is missing (holidays, early closes) are dropped from every arm together,
so all arms trade the identical night set and the paired t is honest.

Cross-era: NQ 2015-2019 P&L is rescaled to today's notional, as everywhere in this repo.

    python mnq_exit_time_backtest.py
    python mnq_exit_time_backtest.py --chart
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
TZ = "US/Eastern"
HEADLINE = [6, 7, 12]                      # hours held: 00:00, 01:00, 06:00 exits
SCAN = [3, 4, 5, 6, 7, 8, 9, 10, 11, 12]   # every exit hour 21:00 -> 06:00

C_BLUE, C_ORANGE, C_AQUA = "#2a78d6", "#eb6834", "#1baf7a"
INK, INK2, GRIDC = "#0b0b0b", "#52514e", "#d8d7d2"


def label(hours: int) -> str:
    return f"{(18 + hours) % 24:02d}:00"


def sessions(fname: str, holds) -> pd.DataFrame:
    """Entry at the 18:00 open; exit at the open of the bar on each hold's boundary.

    Wall-clock arithmetic (naive + tz_localize) keeps 00:00 meaning midnight on both
    sides of a DST switch instead of drifting an hour.
    """
    d = pd.read_parquet(DATA / fname).sort_index()
    idx = d.index
    op = d["open"]
    entries = idx[(idx.hour == 18) & (idx.minute == 0)]

    rows = []
    for t0 in entries:
        n0 = t0.tz_localize(None)
        i0 = int(idx.searchsorted(t0))
        rec = {"sess": n0.normalize(), "entry": float(op.loc[t0])}
        ok = True
        for h in holds:
            # add the hours on the WALL CLOCK, then re-localize: a tz-aware +6h would
            # land on 01:00 instead of midnight on the two DST-switch nights
            want = (n0 + pd.Timedelta(hours=h)).tz_localize(
                TZ, ambiguous=True, nonexistent="shift_forward")
            j = int(idx.searchsorted(want))            # first bar at/after the boundary
            if j >= len(idx) or idx[j] - want > pd.Timedelta(minutes=30):
                ok = False                             # holiday / early close: no fill
                break
            rec[f"exit_{h}"] = float(op.iloc[j])
            rec[f"high_{h}"] = float(d["high"].iloc[i0:j + 1].max())
            rec[f"low_{h}"] = float(d["low"].iloc[i0:j + 1].min())
        if ok:
            rows.append(rec)
    return pd.DataFrame(rows).set_index("sess")


def pnl(s: pd.DataFrame, h: int, ref: float | None) -> pd.Series:
    raw = (s[f"exit_{h}"] - s["entry"]) * DPP
    if ref is not None:                                # old era -> today's notional
        raw = raw / s["entry"] * ref
    return raw - COST


def stats(p: pd.Series, base: pd.Series) -> dict:
    a = p.to_numpy()
    w, l = a[a > 0], a[a < 0]
    eq = p.cumsum()
    d = (p - base).dropna()
    sd = d.std(ddof=1)
    return {"mean": a.mean(), "yr": a.mean() * 252,
            "sharpe": a.mean() / a.std(ddof=1) * np.sqrt(252),
            "pf": w.sum() / abs(l.sum()) if len(l) else np.inf,
            "dd": float((eq - eq.cummax()).min()), "worst": a.min(), "best": a.max(),
            "hit": (a > 0).mean() * 100, "sd": a.std(ddof=1),
            "t": d.mean() / sd * np.sqrt(len(d)) if sd > 0 else 0.0,
            "delta": (a.mean() - base.mean()) * 252}


def table(s, name, ref, holds, base_h=12, header=True):
    base = pnl(s, base_h, ref)
    if header:
        print(f"\n{'='*108}\n{name}  |  {len(s):,} nights  "
              f"{s.index[0].date()} -> {s.index[-1].date()}")
    print(f"{'exit':<11}{'hrs':>5}{'$/nt':>8}{'$/yr':>9}{'Shp':>7}{'PF':>7}{'hit%':>7}"
          f"{'sd$':>8}{'MaxDD$':>9}{'worst':>9}{'best':>8}{'d$/yr':>9}{'pair-t':>8}")
    out = {}
    for h in holds:
        p = pnl(s, h, ref)
        st = stats(p, base)
        tag = label(h) + (" [std]" if h == base_h else "")
        print(f"{tag:<11}{h:>5}{st['mean']:>8.2f}{st['yr']:>9,.0f}{st['sharpe']:>7.2f}"
              f"{st['pf']:>7.3f}{st['hit']:>7.1f}{st['sd']:>8.0f}{st['dd']:>9,.0f}"
              f"{st['worst']:>9,.0f}{st['best']:>8,.0f}{st['delta']:>+9,.0f}"
              f"{st['t']:>8.2f}")
        out[h] = p
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chart", action="store_true")
    args = ap.parse_args()
    REPORTS.mkdir(exist_ok=True)

    holds = sorted(set(HEADLINE + SCAN))
    mnq = sessions("MNQ_5min_databento.parquet", holds)
    nq = sessions("NQ_5min_databento.parquet", holds)
    nq = nq[nq.index < mnq.index[0]]
    ref = float(np.median(mnq.loc[mnq.index.year >= 2024, "entry"]))

    m = table(mnq, "IN-SAMPLE  MNQ 2020-2026", None, HEADLINE)
    n = table(nq, f"OUT-OF-SAMPLE  NQ 2015-2019 (rescaled to today's notional, "
              f"ref {ref:,.0f})", ref, HEADLINE)

    print(f"\n{'-'*108}\nCLOCK SCAN -- every exit hour, in-sample. Neighbours must agree "
          "or it is noise, not a window.")
    table(mnq, "", None, SCAN, header=False)
    print(f"\n{'-'*108}\nCLOCK SCAN -- out of sample")
    table(nq, "", ref, SCAN, header=False)

    # what the shorter windows actually give up: the 00:00 -> 06:00 leg on its own
    for s, r, nm in ((mnq, None, "MNQ"), (nq, ref, "NQ OOS")):
        for h in (6, 7):
            leg = (s["exit_12"] - s[f"exit_{h}"]) * DPP
            if r is not None:
                leg = leg / s["entry"] * r
            t = leg.mean() / leg.std(ddof=1) * np.sqrt(len(leg))
            print(f"  {nm}: the {label(h)}->06:00 leg alone is ${leg.mean():+.2f}/night "
                  f"(t {t:+.2f}, {(leg > 0).mean()*100:.1f}% positive) -- this is what "
                  f"the {label(h)} exit walks away from")

    if args.chart:
        chart(mnq, nq, ref, REPORTS / "mnq_exit_time.png")


def chart(mnq, nq, ref, out):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FuncFormatter

    plt.rcParams.update({
        "figure.facecolor": "#fcfcfb", "axes.facecolor": "#fcfcfb",
        "axes.edgecolor": GRIDC, "axes.labelcolor": INK2, "text.color": INK,
        "xtick.color": INK2, "ytick.color": INK2, "grid.color": GRIDC,
        "font.size": 9, "axes.titlesize": 10, "axes.titleweight": "bold",
        "axes.spines.top": False, "axes.spines.right": False,
    })
    fig, ax = plt.subplots(2, 2, figsize=(15, 9.4))
    fig.suptitle("MNQ overnight block: 00:00 and 01:00 exits vs the 06:00 baseline",
                 fontsize=14, fontweight="bold", x=0.012, ha="left", y=0.985)
    fig.text(0.012, 0.952, "same 18:00 ET entry in every arm, only the exit clock "
             "changes | fills at the boundary bar's open, 1-tick round trip charged | "
             "MNQ \\$2/pt, NQ 2015-2019 rescaled to today's notional",
             fontsize=9.5, color=INK2, ha="left")
    for a in ax.ravel():
        a.grid(True, axis="y", lw=0.6, alpha=0.7)
        a.set_axisbelow(True)
    arms = ((6, C_AQUA, "00:00 exit (6h)"), (7, C_ORANGE, "01:00 exit (7h)"),
            (12, C_BLUE, "06:00 exit (12h, base)"))
    dollars = FuncFormatter(lambda v, _: f"${v:,.0f}")

    # 1 -- equity curves, in sample
    a = ax[0, 0]
    ends = []
    for h, col, lab in arms:
        eq = pnl(mnq, h, None).cumsum()
        a.plot(eq.index, eq.values, color=col, lw=2)
        ends.append((eq.iloc[-1], col, f"{lab}  \\${eq.iloc[-1]:,.0f}"))
    span = pnl(mnq, 12, None).cumsum()
    a.set_xlim(span.index[0], span.index[-1] + pd.Timedelta(days=560))
    lo, hi = a.get_ylim()
    for i, (_, col, txt) in enumerate(sorted(ends, reverse=True)):
        a.annotate(txt, (span.index[-1], hi - (i + 1) * (hi - lo) * 0.08), xytext=(8, 0),
                   textcoords="offset points", ha="left", color=col, fontsize=8.5,
                   fontweight="bold")
    a.yaxis.set_major_formatter(dollars)
    a.set_title("1. Cumulative $ per contract, MNQ 2020-2026")
    a.set_ylabel("cumulative net $")

    # 2 -- underwater curves
    a = ax[0, 1]
    for h, col, lab in arms:
        eq = pnl(mnq, h, None).cumsum()
        a.plot(eq.index, (eq - eq.cummax()).values, color=col, lw=1.6, label=lab)
    a.yaxis.set_major_formatter(dollars)
    a.set_title("2. Drawdown from peak -- a shorter night is not a calmer one")
    a.set_ylabel("$ below the running peak")
    a.legend(frameon=False, loc="lower left")

    # 3 -- mean $/night by year, both eras on one timeline
    a = ax[1, 0]
    years, series = [], {h: [] for h, _, _ in arms}
    for df, r in ((nq, ref), (mnq, None)):
        for y, g in df.groupby(df.index.year):
            years.append(y)
            for h, _, _ in arms:
                series[h].append(pnl(g, h, r).mean())
    x = np.arange(len(years))
    for k, (h, col, lab) in enumerate(arms):
        a.bar(x + (k - 1) * 0.27, series[h], width=0.26, color=col, label=lab)
    a.axvline(len(nq.index.year.unique()) - 0.5, color=INK2, lw=1.2, ls="--")
    a.annotate("NQ (OOS)  |  MNQ", (len(nq.index.year.unique()) - 0.5, a.get_ylim()[1]),
               xytext=(4, -10), textcoords="offset points", color=INK2, fontsize=8,
               fontweight="bold")
    a.axhline(0, color=INK2, lw=1)
    a.set_xticks(x, years, fontsize=8)
    a.yaxis.set_major_formatter(dollars)
    a.set_title("3. Mean $ per night by year -- 2015-2019 out of sample, then in sample")
    a.set_ylabel("mean $ per night")
    a.legend(frameon=False, ncol=3, fontsize=8)

    # 4 -- the clock scan: every exit hour, both eras
    a = ax[1, 1]
    hrs = SCAN
    for df, r, col, lab in ((mnq, None, C_BLUE, "MNQ 2020-2026"),
                            (nq, ref, C_ORANGE, "NQ 2015-2019 (OOS)")):
        y = [pnl(df, h, r).mean() for h in hrs]
        a.plot(hrs, y, color=col, lw=2, marker="o", ms=6, label=lab)
    for h, col, lab in arms:
        a.axvline(h, color=col, lw=1.2, ls=":")
        a.annotate(label(h), (h, a.get_ylim()[0]), xytext=(3, 6),
                   textcoords="offset points", color=col, fontsize=8, fontweight="bold")
    a.axhline(0, color=INK2, lw=1)
    a.set_xticks(hrs, [label(h) for h in hrs], fontsize=8)
    a.yaxis.set_major_formatter(dollars)
    a.set_title("4. Clock scan: mean night for every exit hour")
    a.set_xlabel("exit hour, ET (entry always 18:00)")
    a.set_ylabel("mean $ per night")
    a.legend(frameon=False, loc="upper left")

    fig.tight_layout(rect=(0, 0, 1, 0.94))
    fig.savefig(out, dpi=140)
    plt.close(fig)
    print(f"\nchart -> {out}")


if __name__ == "__main__":
    main()
