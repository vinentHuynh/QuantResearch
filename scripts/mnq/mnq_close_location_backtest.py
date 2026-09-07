"""Does where the day session CLOSED predict the overnight block that follows?

For a night entered at 18:00 ET on date D, the "session that just ended" is D's RTH
(09:30-16:00 ET, two hours earlier), and "the previous day" is D-1's RTH. Every feature
below is therefore known before the entry -- nothing here can be hindsight.

Features tested (all measured on D's close):

  clv            close location in D's OWN range: (C-L)/(H-L), 0 = closed on the low
  day_ret        D's RTH return, open -> close, %
  vs_pdc         D's close vs D-1's close, %          (day-over-day)
  vs_pd_range    D's close placed in D-1's range: 0 = at D-1's low, 1 = at D-1's high,
                 <0 = closed below the prior day's low, >1 = above the prior day's high
  pd_zone        the categorical version: below PDL / inside / above PDH
  seam_gap       the 16:00 close -> 18:00 reopen gap, %  (the entry price vs the close)
  range_pct      D's RTH range / close, % -- a vol control, not a location measure

Prior work on the OLD close->open version of this trade (overnight_loss_profile.py)
reported the edge was dead when the prior day closed near its high and strongest after
weakness. This retests that claim on the actual 18:00->06:00 block, in both eras, and
scores it the way a claim like that has to be scored: a bucket effect only counts if it
appears in-sample AND out-of-sample with the same sign.

The rank correlations are the headline -- buckets can be sliced until something appears,
a Spearman on the whole sample cannot.

    python mnq_close_location_backtest.py
    python mnq_close_location_backtest.py --chart
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

DATA = (Path(__file__).resolve().parents[2] / "data")
REPORTS = (Path(__file__).resolve().parents[2] / "reports")
DPP, TICK = 2.0, 0.25
COST = TICK * DPP
TZ = "US/Eastern"
FEATURES = [("clv", "Close location in own range"),
            ("day_ret", "RTH day return %"),
            ("vs_pdc", "Close vs prior close %"),
            ("vs_pd_range", "Close placed in prior day's range"),
            ("seam_gap", "16:00 close -> 18:00 reopen gap %"),
            ("range_pct", "RTH range % (vol control)")]

C_BLUE, C_ORANGE, C_AQUA = "#2a78d6", "#eb6834", "#1baf7a"
INK, INK2, GRIDC, SURF = "#0b0b0b", "#52514e", "#d8d7d2", "#fcfcfb"


def build(fname: str, ref: float | None) -> pd.DataFrame:
    d = pd.read_parquet(DATA / fname).sort_index()
    idx = d.index
    op = d["open"].to_numpy()

    rth = d[((idx.hour == 9) & (idx.minute >= 30)) |
            (idx.hour.isin([10, 11, 12, 13, 14, 15]))]
    day = rth.groupby(rth.index.tz_localize(None).normalize()).agg(
        o=("open", "first"), h=("high", "max"), l=("low", "min"), c=("close", "last"))
    day = day[day["h"] > day["l"]]
    day["clv"] = (day["c"] - day["l"]) / (day["h"] - day["l"])
    day["day_ret"] = (day["c"] / day["o"] - 1) * 100
    day["vs_pdc"] = (day["c"] / day["c"].shift(1) - 1) * 100
    pdh, pdl = day["h"].shift(1), day["l"].shift(1)
    day["vs_pd_range"] = (day["c"] - pdl) / (pdh - pdl)
    day["range_pct"] = (day["h"] - day["l"]) / day["c"] * 100

    rows = []
    for t0 in idx[(idx.hour == 18) & (idx.minute == 0)]:
        n0 = t0.tz_localize(None)
        want = (n0 + pd.Timedelta(hours=12)).tz_localize(
            TZ, ambiguous=True, nonexistent="shift_forward")
        j = int(idx.searchsorted(want))
        if j >= len(idx) or idx[j] - want > pd.Timedelta(minutes=30):
            continue
        key = n0.normalize()
        if key not in day.index:
            continue
        s = day.loc[key]
        if not np.isfinite(s[["clv", "day_ret", "vs_pdc", "vs_pd_range"]].to_numpy()).all():
            continue
        entry = float(op[int(idx.searchsorted(t0))])
        raw = (float(op[j]) - entry) * DPP
        if ref is not None:
            raw = raw / entry * ref
        rows.append({"sess": key, "pnl": raw - COST, "entry": entry,
                     "clv": s["clv"], "day_ret": s["day_ret"], "vs_pdc": s["vs_pdc"],
                     "vs_pd_range": s["vs_pd_range"], "range_pct": s["range_pct"],
                     "seam_gap": (entry / s["c"] - 1) * 100,
                     "pd_zone": ("below PDL" if s["vs_pd_range"] < 0 else
                                 "above PDH" if s["vs_pd_range"] > 1 else "inside")})
    return pd.DataFrame(rows).set_index("sess")


def tstat(a: np.ndarray) -> float:
    sd = a.std(ddof=1)
    return float(a.mean() / sd * np.sqrt(len(a))) if sd > 0 and len(a) > 1 else 0.0


def corr_table(m: pd.DataFrame, q: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for f, name in FEATURES:
        rs, ps = [], []
        for df in (m, q):
            d = df.dropna(subset=[f])
            rho = d[f].corr(d["pnl"], method="spearman")
            n = len(d)
            rs.append(rho)
            ps.append(rho * np.sqrt(n - 2) / np.sqrt(1 - rho ** 2))   # t of the rho
        rows.append({"feature": name, "IS rho": rs[0], "IS t": ps[0],
                     "OOS rho": rs[1], "OOS t": ps[1],
                     "agree": "yes" if rs[0] * rs[1] > 0 else "NO"})
    return pd.DataFrame(rows).set_index("feature")


def quintiles(df: pd.DataFrame, f: str) -> pd.DataFrame:
    d = df.dropna(subset=[f])
    lab = pd.qcut(d[f], 5, labels=["Q1", "Q2", "Q3", "Q4", "Q5"], duplicates="drop")
    g = d.groupby(lab, observed=True)
    return pd.DataFrame({"n": g.size(), "lo": g[f].min(), "hi": g[f].max(),
                         "mean": g["pnl"].mean(),
                         "hit": g["pnl"].apply(lambda s: (s > 0).mean() * 100),
                         "t": g["pnl"].apply(lambda s: tstat(s.to_numpy()))})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chart", action="store_true")
    args = ap.parse_args()
    REPORTS.mkdir(exist_ok=True)

    m = build("MNQ_5min_databento.parquet", None)
    tmp = build("NQ_5min_databento.parquet", None)
    ref = float(np.median(m.loc[m.index.year >= 2024, "entry"]))
    q = build("NQ_5min_databento.parquet", ref)
    q = q[q.index < m.index[0]]

    print(f"\n{'='*100}\nMNQ 2020-2026 {len(m):,} nights (in sample), mean ${m['pnl'].mean():.2f}"
          f"  |  NQ 2015-2019 {len(q):,} nights (OOS), mean ${q['pnl'].mean():.2f}")

    print(f"\n{'-'*100}\nRANK CORRELATION of each feature with the night's P&L")
    print(f"{'feature':<36}{'IS rho':>9}{'IS t':>8}{'OOS rho':>10}{'OOS t':>8}{'sign agrees':>13}")
    ct = corr_table(m, q)
    for name, r in ct.iterrows():
        print(f"{name:<36}{r['IS rho']:>9.3f}{r['IS t']:>8.2f}{r['OOS rho']:>10.3f}"
              f"{r['OOS t']:>8.2f}{r['agree']:>13}")

    for f, name in FEATURES:
        print(f"\n{'-'*100}\n{name}  ({f}) -- quintiles")
        print(f"{'':<4}{'IS n':>7}{'range':>20}{'IS $/nt':>10}{'IS hit%':>9}{'IS t':>7}"
              f"{'  ':<3}{'OOS n':>7}{'OOS $/nt':>10}{'OOS hit%':>10}{'OOS t':>8}")
        qi, qo = quintiles(m, f), quintiles(q, f)
        for k in qi.index:
            a, b = qi.loc[k], qo.loc[k] if k in qo.index else None
            rng = f"{a['lo']:.2f} .. {a['hi']:.2f}"
            line = (f"{k:<4}{a['n']:>7,}{rng:>20}{a['mean']:>10.2f}{a['hit']:>9.1f}"
                    f"{a['t']:>7.2f}{'  ':<3}")
            line += (f"{b['n']:>7,}{b['mean']:>10.2f}{b['hit']:>10.1f}{b['t']:>8.2f}"
                     if b is not None else f"{'-':>35}")
            print(line)

    print(f"\n{'-'*100}\nClose vs the PREVIOUS day's range (categorical)")
    print(f"{'zone':<12}{'IS n':>7}{'IS $/nt':>10}{'IS hit%':>9}{'IS t':>7}"
          f"{'  ':<3}{'OOS n':>7}{'OOS $/nt':>10}{'OOS hit%':>10}{'OOS t':>8}")
    for z in ("below PDL", "inside", "above PDH"):
        a, b = m[m["pd_zone"] == z]["pnl"], q[q["pd_zone"] == z]["pnl"]
        print(f"{z:<12}{len(a):>7,}{a.mean():>10.2f}{(a > 0).mean()*100:>9.1f}"
              f"{tstat(a.to_numpy()):>7.2f}{'  ':<3}{len(b):>7,}{b.mean():>10.2f}"
              f"{(b > 0).mean()*100:>10.1f}{tstat(b.to_numpy()):>8.2f}")

    # the specific prior claim: skip nights that closed in the top of their own range
    print(f"\n{'-'*100}\nTHE PRIOR CLAIM: 'the edge is dead when the day closed near its high'")
    for cut in (0.8, 0.7, 0.6):
        print(f"  skip nights with clv > {cut:.1f}:", end="")
        for df, tag in ((m, "IS"), (q, "OOS")):
            k = df[df["clv"] <= cut]["pnl"]
            print(f"   {tag} ${k.mean():>6.2f}/nt on {len(k):>5,} nights "
                  f"(all ${df['pnl'].mean():.2f}, t {tstat(k.to_numpy()):+.2f})", end="")
        print()

    if args.chart:
        chart(m, q, ct, REPORTS / "mnq_close_location.png")


def chart(m, q, ct, out):
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
    fig, ax = plt.subplots(2, 3, figsize=(17, 9.2))
    fig.suptitle("Does where the day session closed predict the overnight block?",
                 fontsize=14, fontweight="bold", x=0.011, ha="left", y=0.985)
    fig.text(0.011, 0.952, "night = long 18:00 ET reopen, flat 06:00 ET open, 1-tick "
             "round trip | every feature measured on the RTH session that ended at "
             "16:00, two hours before entry | MNQ 2020-2026 in sample, NQ 2015-2019 "
             "out of sample", fontsize=9.5, color=INK2, ha="left")
    for a in ax.ravel():
        a.grid(True, axis="y", lw=0.6, alpha=0.7)
        a.set_axisbelow(True)
    dollars = FuncFormatter(lambda v, _: f"${v:,.0f}")

    def bars(a, f, title, xlabels=None):
        for df, col, lab, off in ((m, C_BLUE, "MNQ (IS)", -0.2),
                                  (q, C_ORANGE, "NQ (OOS)", 0.2)):
            b = quintiles(df, f)
            a.bar(np.arange(len(b)) + off, b["mean"].values, width=0.38, color=col,
                  label=lab)
            if col == C_BLUE:
                for i, (mu, t) in enumerate(zip(b["mean"].values, b["t"].values)):
                    a.annotate(f"t {t:.1f}", (i - 0.2, mu),
                               xytext=(0, 3 if mu >= 0 else -11),
                               textcoords="offset points", ha="center", fontsize=7,
                               color=INK2)
        a.axhline(0, color=INK2, lw=1)
        a.set_xticks(range(5), xlabels or ["Q1 low", "Q2", "Q3", "Q4", "Q5 high"],
                     fontsize=8)
        a.yaxis.set_major_formatter(dollars)
        a.set_title(title)
        a.legend(frameon=False, fontsize=8)

    bars(ax[0, 0], "clv", "1. Close location in its own range\n(Q1 = closed on the low)")
    bars(ax[0, 1], "day_ret", "2. RTH day return\n(Q1 = biggest down day)")
    bars(ax[0, 2], "vs_pd_range", "3. Close placed in the PRIOR day's range")

    # 4 -- categorical zone
    a = ax[1, 0]
    zones = ["below PDL", "inside", "above PDH"]
    for df, col, lab, off in ((m, C_BLUE, "MNQ (IS)", -0.2), (q, C_ORANGE, "NQ (OOS)", 0.2)):
        vals, ns = [], []
        for z in zones:
            s = df[df["pd_zone"] == z]["pnl"]
            vals.append(s.mean())
            ns.append(len(s))
        a.bar(np.arange(3) + off, vals, width=0.38, color=col, label=lab)
        for i, (v, n) in enumerate(zip(vals, ns)):
            a.annotate(f"n={n:,}", (i + off, v), xytext=(0, 3 if v >= 0 else -11),
                       textcoords="offset points", ha="center", fontsize=7, color=INK2)
    a.axhline(0, color=INK2, lw=1)
    a.set_xticks(range(3), zones, fontsize=8)
    a.yaxis.set_major_formatter(dollars)
    a.set_title("4. Close vs the previous day's range")
    a.legend(frameon=False, fontsize=8)

    # 5 -- seam gap
    bars(ax[1, 1], "seam_gap", "5. 16:00 close -> 18:00 reopen gap\n(Q1 = gapped down)")

    # 6 -- rank correlations, both eras
    a = ax[1, 2]
    names = [n.replace(" (vol control)", "") for n in ct.index]
    y = np.arange(len(names))
    a.grid(True, axis="x", lw=0.6, alpha=0.7)
    a.barh(y - 0.2, ct["IS rho"], height=0.38, color=C_BLUE, label="MNQ (IS)")
    a.barh(y + 0.2, ct["OOS rho"], height=0.38, color=C_ORANGE, label="NQ (OOS)")
    a.axvline(0, color=INK2, lw=1)
    for v, c in ((0.05, C_AQUA), (-0.05, C_AQUA)):
        a.axvline(v, color=c, lw=1, ls=":")
    a.annotate("|rho| = 0.05", (0.05, len(names) - 0.4), xytext=(4, 0),
               textcoords="offset points", color=C_AQUA, fontsize=8, fontweight="bold")
    a.set_yticks(y, [n if len(n) < 30 else n[:28] + "…" for n in names], fontsize=8)
    a.invert_yaxis()
    a.set_title("6. Spearman rank correlation with night P&L")
    a.set_xlabel("rho")
    a.legend(frameon=False, fontsize=8, loc="lower right")

    fig.tight_layout(rect=(0, 0, 1, 0.94))
    fig.savefig(out, dpi=140)
    plt.close(fig)
    print(f"\nchart -> {out}")


if __name__ == "__main__":
    main()
