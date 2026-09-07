"""How far off the overnight block's HIGH does the block close?

The block strategy (overnight_block_strategy.pine) buys the 18:00 ET reopen and
exits at 06:00 ET -- it takes the CLOSE of the window, never the high. This report
measures the gap between the two:

    giveback = window high - window close          (points, $, and % of entry)

plus the two numbers that give it meaning:

    MFE      = window high  - entry (18:00 open)   the best the night ever offered
    realized = window close - entry                what the block actually pays
    capture  = realized / MFE                      share of the run kept to 06:00

Points are not comparable across eras (NQ ~4,400 in 2015 vs ~24,000 in 2026), so
every cross-era number is also printed as % of the entry price. The NQ 2015-2020
file is the same out-of-sample era used by the rest of this workspace.

A night is kept only if it has >= --min-bars of the 144 5-min bars in 18:00->06:00,
so holidays and half sessions cannot fake a small high.

    python mnq_overnight_giveback_report.py
    python mnq_overnight_giveback_report.py --min-bars 144   # full nights only
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path(__file__).with_name("data")
REPORTS = Path(__file__).with_name("reports")
DPP = 2.0                                      # MNQ $ per index point
NIGHT_HOURS = [18, 19, 20, 21, 22, 23, 0, 1, 2, 3, 4, 5]

# dataviz reference palette, light surface: slot 1 blue, 2 orange, 3 aqua
C_BLUE, C_ORANGE, C_AQUA = "#2a78d6", "#eb6834", "#1baf7a"
INK, INK2, GRID = "#0b0b0b", "#52514e", "#d8d7d2"


def nights(fname: str, min_bars: int) -> pd.DataFrame:
    """One row per 18:00->06:00 ET session: entry, high, low, close, timing."""
    d = pd.read_parquet(DATA / fname).sort_index()
    idx = d.index
    keep = np.isin(idx.hour, NIGHT_HOURS)
    d = d[keep].copy()
    d["sess"] = (idx[keep] - pd.Timedelta(hours=18)).normalize()

    rows = []
    for s, g in d.groupby("sess"):
        if len(g) < min_bars:
            continue
        hi_i = int(np.argmax(g["high"].to_numpy()))
        lo_i = int(np.argmin(g["low"].to_numpy()))
        t0 = g.index[0]
        rows.append({
            "sess": s,
            "entry": float(g["open"].iloc[0]),
            "high": float(g["high"].iloc[hi_i]),
            "low": float(g["low"].iloc[lo_i]),
            "close": float(g["close"].iloc[-1]),
            "bars": len(g),
            # minutes from the 18:00 open to the bar that printed the extreme
            "t_high": (g.index[hi_i] - t0).total_seconds() / 60.0,
            "t_low": (g.index[lo_i] - t0).total_seconds() / 60.0,
        })

    n = pd.DataFrame(rows).set_index("sess")
    n["giveback"] = n["high"] - n["close"]
    n["mfe"] = n["high"] - n["entry"]
    n["mae"] = n["entry"] - n["low"]
    n["realized"] = n["close"] - n["entry"]
    n["range"] = n["high"] - n["low"]
    n["gb_pct"] = n["giveback"] / n["entry"] * 100
    n["mfe_pct"] = n["mfe"] / n["entry"] * 100
    n["real_pct"] = n["realized"] / n["entry"] * 100
    n["gb_share_range"] = n["giveback"] / n["range"].replace(0, np.nan)
    n["capture"] = np.where(n["mfe"] > 0, n["realized"] / n["mfe"], np.nan)
    return n


def describe(n: pd.DataFrame, name: str) -> None:
    g, m, r = n["giveback"], n["mfe"], n["realized"]
    qs = [0.1, 0.25, 0.5, 0.75, 0.9, 0.95, 0.99]
    print(f"\n{'='*100}\n{name}  |  {len(n):,} nights  "
          f"{n.index[0].date()} -> {n.index[-1].date()}")
    print(f"{'metric':<26}{'mean':>10}{'median':>10}{'sd':>10}{'min':>10}{'max':>10}")
    for lab, s in (("giveback  high-close pts", g), ("MFE  high-entry pts", m),
                   ("realized close-entry pts", r), ("night range pts", n["range"])):
        print(f"{lab:<26}{s.mean():>10.1f}{s.median():>10.1f}{s.std():>10.1f}"
              f"{s.min():>10.1f}{s.max():>10.1f}")

    print(f"\n  giveback quantiles      " + "".join(f"{int(q*100):>9}%" for q in qs))
    print(f"    points                " + "".join(f"{g.quantile(q):>10.1f}" for q in qs))
    print(f"    $ / micro             " + "".join(f"{g.quantile(q)*DPP:>10.0f}" for q in qs))
    print(f"    % of entry            " + "".join(
        f"{n['gb_pct'].quantile(q):>10.2f}" for q in qs))

    print(f"\n  mean giveback ${g.mean()*DPP:,.0f}/night vs mean realized "
          f"${r.mean()*DPP:+,.0f}/night  ->  the close leaves "
          f"{g.mean()/max(m.mean(), 1e-9)*100:.0f}% of the average run on the table")
    print(f"  giveback in %: mean {n['gb_pct'].mean():.3f}%  median "
          f"{n['gb_pct'].median():.3f}%  |  MFE mean {n['mfe_pct'].mean():.3f}%  "
          f"realized mean {n['real_pct'].mean():+.3f}%")
    print(f"  giveback is {n['gb_share_range'].median()*100:.0f}% of the night's "
          f"range at the median; close within 1 tick of the high on "
          f"{(g <= 0.25).mean()*100:.1f}% of nights, "
          f"{(g >= 100).mean()*100:.1f}% of nights give back >=100 pts")
    print(f"  capture (realized/MFE, MFE>0): median {n['capture'].median():.2f}  "
          f"mean {n['capture'].mean():.2f} (mean is meaningless -- small MFE nights "
          f"blow up the ratio)  |  nights closing in the top 10% of their own run: "
          f"{(n['capture'] > 0.9).mean()*100:.0f}%")
    print(f"  high prints in the first 2h on {(n['t_high'] <= 120).mean()*100:.0f}% "
          f"of nights, in the last 2h on {(n['t_high'] >= 600).mean()*100:.0f}%; "
          f"median t_high {n['t_high'].median():.0f} min after 18:00")


def chart(n: pd.DataFrame, out: Path, title: str) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FuncFormatter, PercentFormatter

    plt.rcParams.update({
        "figure.facecolor": "#fcfcfb", "axes.facecolor": "#fcfcfb",
        "axes.edgecolor": GRID, "axes.labelcolor": INK2, "text.color": INK,
        "xtick.color": INK2, "ytick.color": INK2, "grid.color": GRID,
        "font.size": 9, "axes.titlesize": 10, "axes.titleweight": "bold",
        "axes.spines.top": False, "axes.spines.right": False,
    })
    fig, ax = plt.subplots(2, 3, figsize=(16.5, 9.2))
    fig.suptitle(title, fontsize=14, fontweight="bold", x=0.012, ha="left", y=0.985)
    fig.text(0.012, 0.952, "giveback = window high - window close, per 18:00->06:00 ET "
             f"session | MNQ $2/pt | {len(n):,} nights "
             f"{n.index[0].date()} to {n.index[-1].date()}",
             fontsize=9.5, color=INK2, ha="left")
    for a in ax.ravel():
        a.grid(True, axis="y", lw=0.6, alpha=0.7)
        a.set_axisbelow(True)

    # 1 -- giveback distribution
    a = ax[0, 0]
    g = n["giveback"]
    a.hist(g, bins=np.linspace(0, g.quantile(0.99), 60), color=C_BLUE, alpha=0.9)
    a.axvline(g.median(), color=C_ORANGE, lw=2)
    a.axvline(g.mean(), color=INK, lw=2, ls="--")
    a.annotate(f"median {g.median():.0f} pts  (${g.median()*DPP:,.0f})",
               (g.median(), a.get_ylim()[1]*0.93), xytext=(6, 0),
               textcoords="offset points", color=C_ORANGE, fontweight="bold")
    a.annotate(f"mean {g.mean():.0f} pts", (g.mean(), a.get_ylim()[1]*0.80),
               xytext=(6, 0), textcoords="offset points", color=INK)
    a.set_title("1. How far below the high the block closes")
    a.set_xlabel("high - close (index points)")
    a.set_ylabel("nights")

    # 2 -- what the night offered vs what the close paid
    a = ax[0, 1]
    lim = float(np.nanpercentile(n["mfe"], 99))
    a.scatter(n["mfe"], n["realized"], s=9, color=C_BLUE, alpha=0.28, lw=0)
    a.plot([0, lim], [0, lim], color=C_ORANGE, lw=2, label="exit at the high (ceiling)")
    a.axhline(0, color=INK2, lw=1)
    a.set_xlim(0, lim)
    a.set_ylim(-lim, lim)
    a.set_title("2. Run offered (MFE) vs kept at 06:00")
    a.set_xlabel("high - entry (points)")
    a.set_ylabel("close - entry (points)")
    a.legend(frameon=False, loc="lower right")
    a.annotate("gap to the line = giveback", (lim*0.52, lim*0.20), color=INK2)

    # 3 -- when the high prints
    a = ax[0, 2]
    hrs = ((n["t_high"] // 60).astype(int) + 18) % 24
    cnt = hrs.value_counts().reindex(NIGHT_HOURS, fill_value=0)
    share = cnt / cnt.sum() * 100
    bars = a.bar(range(len(cnt)), share.values, color=C_BLUE, width=0.78)
    top = int(np.argmax(share.values))
    bars[top].set_color(C_ORANGE)
    a.annotate(f"{share.values[top]:.0f}%", (top, share.values[top]), xytext=(0, 4),
               textcoords="offset points", ha="center", color=C_ORANGE,
               fontweight="bold")
    a.set_xticks(range(len(cnt)))
    a.set_xticklabels([f"{h:02d}" for h in NIGHT_HOURS], fontsize=8)
    a.yaxis.set_major_formatter(PercentFormatter())
    a.set_title("3. Hour the overnight high prints (ET)")
    a.set_xlabel("hour of the block")
    a.set_ylabel("share of nights")

    # 4 -- giveback vs realized, by year (points are era-dependent, so use %)
    a = ax[1, 0]
    yr = n.groupby(n.index.year)
    med_gb, med_re = yr["gb_pct"].median(), yr["real_pct"].median()
    x = np.arange(len(med_gb))
    a.bar(x - 0.2, med_gb.values, width=0.38, color=C_BLUE, label="giveback")
    a.bar(x + 0.2, med_re.values, width=0.38, color=C_AQUA, label="realized (close-entry)")
    a.axhline(0, color=INK2, lw=1)
    a.set_xticks(x)
    a.set_xticklabels(med_gb.index, fontsize=8)
    a.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:.2f}%"))
    a.set_title("4. Median giveback vs median take, by year (% of entry)")
    a.set_ylabel("% of entry price")
    a.legend(frameon=False)
    for xi, v in zip(x, med_gb.values):
        a.annotate(f"{v:.2f}", (xi - 0.2, v), xytext=(0, 3), textcoords="offset points",
                   ha="center", fontsize=7.5, color=INK2)

    # 5 -- capture ratio
    a = ax[1, 1]
    cap = n["capture"].dropna().clip(-2, 1)
    a.hist(cap, bins=np.linspace(-2, 1, 60), color=C_BLUE, alpha=0.9)
    a.axvline(cap.median(), color=C_ORANGE, lw=2)
    a.axvline(0, color=INK2, lw=1)
    a.annotate(f"median {cap.median():.2f}", (cap.median(), a.get_ylim()[1]*0.93),
               xytext=(-6, 0), textcoords="offset points", ha="right",
               color=C_ORANGE, fontweight="bold")
    a.set_title("5. Share of the run kept to the close  (realized / MFE)")
    a.set_xlabel("capture ratio (clipped at -2; 1.0 = closed on the high)")
    a.set_ylabel("nights")

    # 6 -- ECDF with the levels a stop/target actually sits at
    a = ax[1, 2]
    s = np.sort(g.values)
    a.plot(s, np.arange(1, len(s) + 1) / len(s) * 100, color=C_BLUE, lw=2)
    a.set_xlim(0, float(np.percentile(s, 99)))
    a.yaxis.set_major_formatter(PercentFormatter())
    for lvl, col in ((50, C_AQUA), (100, C_ORANGE), (200, INK)):
        p = (g <= lvl).mean() * 100
        a.axvline(lvl, color=col, lw=1.4, ls=":")
        a.annotate(f"{lvl} pts (${lvl*DPP:,.0f})\n{p:.0f}% of nights below",
                   (lvl, p), xytext=(7, -14), textcoords="offset points",
                   color=col, fontsize=8, fontweight="bold")
    a.set_title("6. Cumulative: nights giving back at most X")
    a.set_xlabel("high - close (points)")
    a.set_ylabel("share of nights")

    fig.tight_layout(rect=(0, 0, 1, 0.94))
    fig.savefig(out, dpi=140)
    plt.close(fig)
    print(f"\nchart -> {out}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-bars", type=int, default=120,
                    help="min 5-min bars in the 144-bar window (default 120)")
    ap.add_argument("--no-oos", action="store_true", help="skip the NQ 2015-2020 era")
    args = ap.parse_args()
    REPORTS.mkdir(exist_ok=True)

    mnq = nights("MNQ_5min_databento.parquet", args.min_bars)
    describe(mnq, "IN-SAMPLE  MNQ 5-min, 18:00->06:00 ET")
    mnq.to_csv(REPORTS / "mnq_overnight_giveback.csv")
    chart(mnq, REPORTS / "mnq_overnight_giveback.png",
          "MNQ overnight block: distance from the window high to the window close")

    if not args.no_oos:
        nq = nights("NQ_5min_databento.parquet", args.min_bars)
        nq = nq[nq.index < mnq.index[0]]
        describe(nq, "OUT-OF-SAMPLE  NQ 5-min (pre-MNQ era), 18:00->06:00 ET")
        print("\n  cross-era check (% of entry, points are not comparable):"
              f"\n    median giveback   MNQ {mnq['gb_pct'].median():.3f}%   "
              f"NQ {nq['gb_pct'].median():.3f}%"
              f"\n    median capture    MNQ {mnq['capture'].median():.2f}      "
              f"NQ {nq['capture'].median():.2f}")

    print(f"\nper-night table -> {REPORTS / 'mnq_overnight_giveback.csv'}")


if __name__ == "__main__":
    main()
