"""Data dashboard for the MNQ overnight drift block, 18:00 -> 06:00 ET.

Descriptive only -- this is the anatomy of the validated window, not a search for a new
rule. Every panel is the same trade (long the 18:00 reopen, flat at the 06:00 open, one
tick round trip) sliced a different way, in both eras:

    in sample       MNQ 5-min, 2020-01-01 -> 2026-08-06
    out of sample   NQ  5-min, 2015-01-01 -> 2019-12-30, rescaled to today's notional

Conditioning panels (prior night, prior RTH day, vol regime, trend) are LAGGED -- every
bucket key is known before the 18:00 entry, so no panel can be read as hindsight. They
are shown to describe the distribution, not to propose filters: the prior work
(overnight_loss_profile.py, overnight_filtered_backtest.py) already found bucket
selection does not survive train/test.

Writes reports/drift/: four figures, the per-night CSV, and index.html with every table
rendered from the same run -- so the page can never disagree with the data.

    python mnq_overnight_drift_dashboard.py
    python mnq_overnight_drift_dashboard.py --serve 8900
"""
from __future__ import annotations

import argparse
import html
from pathlib import Path

import numpy as np
import pandas as pd

DATA = (Path(__file__).resolve().parents[2] / "data")
OUT = (Path(__file__).resolve().parents[2] / "reports") / "drift"
DPP, TICK = 2.0, 0.25
COST = TICK * DPP
TZ = "US/Eastern"
HOLD_H = 12                       # 18:00 -> 06:00
BARS = 144                        # 5-min bars in the window

C_BLUE, C_ORANGE, C_AQUA, C_YELLOW = "#2a78d6", "#eb6834", "#1baf7a", "#eda100"
INK, INK2, GRIDC, SURF = "#0b0b0b", "#52514e", "#d8d7d2", "#fcfcfb"
DIVERGING = ["#104281", "#2a78d6", "#9ec5f4", "#f0efec", "#f3b4b4", "#e34948", "#8f1f1f"]


# ---------------------------------------------------------------- data ----------
def build(fname: str) -> tuple[pd.DataFrame, np.ndarray]:
    """Per-night frame + the mean intranight path (cumulative points from entry)."""
    d = pd.read_parquet(DATA / fname).sort_index()
    idx = d.index
    op, hi, lo, cl = (d[c].to_numpy() for c in ("open", "high", "low", "close"))

    # --- daily RTH context, all lagged one day when used ---
    rth = d[((idx.hour == 9) & (idx.minute >= 30)) | (idx.hour.isin([10, 11, 12, 13, 14, 15]))]
    day = rth.groupby(rth.index.tz_localize(None).normalize()).agg(
        d_open=("open", "first"), d_close=("close", "last"))
    day["d_ret"] = (day["d_close"] / day["d_open"] - 1) * 100
    day["sma50"] = day["d_close"].rolling(50).mean()
    day["trend"] = (day["d_close"] / day["sma50"] - 1) * 100

    entries = idx[(idx.hour == 18) & (idx.minute == 0)]
    rows, paths = [], []
    for t0 in entries:
        n0 = t0.tz_localize(None)
        want = (n0 + pd.Timedelta(hours=HOLD_H)).tz_localize(
            TZ, ambiguous=True, nonexistent="shift_forward")
        i0 = int(idx.searchsorted(t0))
        j = int(idx.searchsorted(want))
        if j >= len(idx) or idx[j] - want > pd.Timedelta(minutes=30):
            continue
        seg = slice(i0, j + 1)
        entry = float(op[i0])
        prev = day[day.index < n0]                       # strictly before the entry day
        rows.append({
            "sess": n0.normalize(), "entry": entry, "exit": float(op[j]),
            "high": float(hi[seg].max()), "low": float(lo[seg].min()),
            "bars": j - i0,
            "prior_day_ret": float(prev["d_ret"].iloc[-1]) if len(prev) else np.nan,
            "trend": float(prev["trend"].iloc[-1]) if len(prev) else np.nan,
        })
        p = (cl[i0:j] - entry)                            # path in points from entry
        paths.append(np.interp(np.linspace(0, 1, BARS), np.linspace(0, 1, len(p)), p)
                     if len(p) else np.full(BARS, np.nan))

    n = pd.DataFrame(rows).set_index("sess")
    n["mfe"] = n["high"] - n["entry"]
    n["mae"] = n["entry"] - n["low"]
    return n, np.vstack(paths)


def price(n: pd.DataFrame, ref: float | None) -> pd.DataFrame:
    """Net $ per night (+ lagged regime keys). ref set -> rescale old era to today."""
    n = n.copy()
    raw = (n["exit"] - n["entry"]) * DPP
    if ref is not None:
        raw = raw / n["entry"] * ref
    n["pnl"] = raw - COST
    n["mfe_usd"] = n["mfe"] * DPP * (ref / n["entry"] if ref is not None else 1)
    n["mae_usd"] = n["mae"] * DPP * (ref / n["entry"] if ref is not None else 1)
    n["prior_night"] = n["pnl"].shift(1)
    n["vol20"] = n["pnl"].rolling(20).std().shift(1)      # lagged: known before entry
    n["dow"] = n.index.dayofweek
    n["year"] = n.index.year
    n["month"] = n.index.month
    return n


def headline(p: pd.Series) -> dict:
    a = p.to_numpy()
    w, l = a[a > 0], a[a < 0]
    eq = p.cumsum()
    sd = a.std(ddof=1)
    streaks = (p > 0).astype(int)
    grp = (streaks != streaks.shift()).cumsum()
    runs = streaks.groupby(grp).agg(["first", "size"])
    return {
        "nights": len(a), "mean": a.mean(), "median": float(np.median(a)),
        "yr": a.mean() * 252, "sd": sd, "sharpe": a.mean() / sd * np.sqrt(252),
        "t": a.mean() / sd * np.sqrt(len(a)),
        "pf": w.sum() / abs(l.sum()), "hit": (a > 0).mean() * 100,
        "dd": float((eq - eq.cummax()).min()), "worst": a.min(), "best": a.max(),
        "avg_win": w.mean(), "avg_loss": l.mean(),
        "win_streak": int(runs[runs["first"] == 1]["size"].max()),
        "loss_streak": int(runs[runs["first"] == 0]["size"].max()),
        "total": a.sum(),
    }


def buckets(n: pd.DataFrame, col: str, q: int = 5) -> pd.DataFrame:
    d = n.dropna(subset=[col])
    lab = pd.qcut(d[col], q, labels=[f"Q{i+1}" for i in range(q)], duplicates="drop")
    g = d.groupby(lab, observed=True)["pnl"]
    out = pd.DataFrame({"n": g.size(), "mean": g.mean(), "hit": g.apply(lambda s: (s > 0).mean() * 100),
                        "lo": d.groupby(lab, observed=True)[col].min(),
                        "hi": d.groupby(lab, observed=True)[col].max()})
    out["t"] = g.apply(lambda s: s.mean() / s.std(ddof=1) * np.sqrt(len(s)))
    return out


# ---------------------------------------------------------------- figures -------
def _style():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({
        "figure.facecolor": SURF, "axes.facecolor": SURF, "axes.edgecolor": GRIDC,
        "axes.labelcolor": INK2, "text.color": INK, "xtick.color": INK2,
        "ytick.color": INK2, "grid.color": GRIDC, "font.size": 9,
        "axes.titlesize": 10, "axes.titleweight": "bold",
        "axes.spines.top": False, "axes.spines.right": False,
    })
    return plt


def fig_performance(m, q, out):
    plt = _style()
    from matplotlib.ticker import FuncFormatter
    dollars = FuncFormatter(lambda v, _: f"${v:,.0f}")
    fig, ax = plt.subplots(2, 2, figsize=(14.5, 8.4))
    for a in ax.ravel():
        a.grid(True, axis="y", lw=0.6, alpha=0.7)
        a.set_axisbelow(True)

    a = ax[0, 0]
    for s, col, lab in ((q["pnl"], C_ORANGE, "NQ 2015-2019 (OOS)"),
                        (m["pnl"], C_BLUE, "MNQ 2020-2026")):
        eq = s.cumsum()
        a.plot(eq.index, eq.values, color=col, lw=2, label=f"{lab}  \\${eq.iloc[-1]:,.0f}")
    a.yaxis.set_major_formatter(dollars)
    a.set_title("Cumulative net $ per contract")
    a.legend(frameon=False, loc="upper left")

    a = ax[0, 1]
    for s, col, lab in ((q["pnl"], C_ORANGE, "NQ (OOS)"), (m["pnl"], C_BLUE, "MNQ")):
        eq = s.cumsum()
        a.fill_between(eq.index, (eq - eq.cummax()).values, 0, color=col, alpha=0.5, lw=0)
    a.yaxis.set_major_formatter(dollars)
    a.set_title("Drawdown from peak")

    a = ax[1, 0]
    for s, col in ((q["pnl"], C_ORANGE), (m["pnl"], C_BLUE)):
        r = s.rolling(250).mean()
        a.plot(r.index, r.values, color=col, lw=2)
    a.axhline(0, color=INK2, lw=1)
    a.yaxis.set_major_formatter(dollars)
    a.set_title("Rolling 250-night mean $ per night")

    a = ax[1, 1]
    for s, col in ((q["pnl"], C_ORANGE), (m["pnl"], C_BLUE)):
        r = s.rolling(250).mean() / s.rolling(250).std() * np.sqrt(252)
        a.plot(r.index, r.values, color=col, lw=2)
    a.axhline(0, color=INK2, lw=1)
    a.axhline(1, color=C_AQUA, lw=1.2, ls=":")
    a.annotate("Sharpe 1.0", (r.index[len(r)//3], 1), xytext=(0, 4),
               textcoords="offset points", color=C_AQUA, fontsize=8, fontweight="bold")
    a.set_title("Rolling 250-night annualised Sharpe")

    fig.tight_layout()
    fig.savefig(out, dpi=140)
    plt.close(fig)


def fig_distribution(m, q, pm, pq, refscale, out):
    plt = _style()
    from matplotlib.ticker import FuncFormatter, PercentFormatter
    dollars = FuncFormatter(lambda v, _: f"${v:,.0f}")
    fig, ax = plt.subplots(2, 2, figsize=(14.5, 8.4))
    for a in ax.ravel():
        a.grid(True, axis="y", lw=0.6, alpha=0.7)
        a.set_axisbelow(True)

    a = ax[0, 0]
    v = m["pnl"]
    a.hist(v.clip(-800, 800), bins=np.linspace(-800, 800, 80), color=C_BLUE, alpha=0.9)
    a.axvline(0, color=INK2, lw=1)
    a.axvline(v.mean(), color=C_ORANGE, lw=2)
    a.annotate(f"mean \\${v.mean():.2f}\nmedian \\${v.median():.2f}",
               (v.mean(), a.get_ylim()[1] * 0.82), xytext=(8, 0),
               textcoords="offset points", color=C_ORANGE, fontweight="bold", fontsize=8.5)
    a.xaxis.set_major_formatter(dollars)
    a.set_title("MNQ nightly P&L distribution (clipped +/- \\$800)")
    a.set_ylabel("nights")

    a = ax[0, 1]
    for s, col, lab in ((q["pnl"], C_ORANGE, "NQ (OOS)"), (m["pnl"], C_BLUE, "MNQ")):
        x = np.sort(s.to_numpy())
        a.plot(x, np.arange(1, len(x) + 1) / len(x) * 100, color=col, lw=2, label=lab)
    a.axvline(0, color=INK2, lw=1)
    a.set_xlim(-900, 900)
    a.xaxis.set_major_formatter(dollars)
    a.yaxis.set_major_formatter(PercentFormatter())
    a.set_title("Cumulative distribution of nightly P&L")
    a.legend(frameon=False, loc="upper left")

    a = ax[1, 0]
    x = np.arange(BARS) * 5 / 60
    for path, col, lab, sc in ((pq, C_ORANGE, "NQ (OOS)", refscale),
                               (pm, C_BLUE, "MNQ", 1.0)):
        a.plot(x, np.nanmean(path, axis=0) * DPP * sc, color=col, lw=2, label=lab)
    a.axhline(0, color=INK2, lw=1)
    a.set_xticks(range(0, 13, 2), [f"{(18+h) % 24:02d}:00" for h in range(0, 13, 2)])
    a.yaxis.set_major_formatter(dollars)
    a.set_title("Mean cumulative P&L inside the night (where the money accrues)")
    a.set_xlabel("hours from the 18:00 entry")
    a.legend(frameon=False, loc="upper left")

    a = ax[1, 1]
    hrs = list(range(12))
    for path, col, lab, sc, off in ((pm, C_BLUE, "MNQ", 1.0, -0.2),
                                    (pq, C_ORANGE, "NQ (OOS)", refscale, 0.2)):
        mean_path = np.nanmean(path, axis=0) * DPP * sc
        step = [mean_path[min((h + 1) * 12, BARS - 1)] - mean_path[max(h * 12 - 1, 0)]
                for h in hrs]
        a.bar(np.array(hrs) + off, step, width=0.38, color=col, label=lab)
    a.axhline(0, color=INK2, lw=1)
    a.set_xticks(hrs, [f"{(18+h) % 24:02d}" for h in hrs])
    a.yaxis.set_major_formatter(dollars)
    a.set_title("Contribution by hour of the night")
    a.set_xlabel("hour, ET")
    a.legend(frameon=False)

    fig.tight_layout()
    fig.savefig(out, dpi=140)
    plt.close(fig)


def fig_seasonality(m, q, out):
    plt = _style()
    from matplotlib.colors import LinearSegmentedColormap, TwoSlopeNorm
    from matplotlib.ticker import FuncFormatter
    dollars = FuncFormatter(lambda v, _: f"${v:,.0f}")
    fig, ax = plt.subplots(2, 2, figsize=(14.5, 8.4))
    for a in ax.ravel():
        a.grid(True, axis="y", lw=0.6, alpha=0.7)
        a.set_axisbelow(True)

    a = ax[0, 0]
    both = pd.concat([q.assign(era="NQ"), m.assign(era="MNQ")])
    piv = both.pivot_table(index="year", columns="month", values="pnl", aggfunc="mean")
    piv = piv.reindex(columns=range(1, 13))
    v = np.nanmax(np.abs(piv.to_numpy()))
    cmap = LinearSegmentedColormap.from_list("div", DIVERGING[::-1])
    im = a.imshow(piv.to_numpy(), cmap=cmap, norm=TwoSlopeNorm(0, -v, v), aspect="auto")
    for i in range(piv.shape[0]):
        for j in range(piv.shape[1]):
            val = piv.to_numpy()[i, j]
            if np.isfinite(val):
                a.text(j, i, f"{val:.0f}", ha="center", va="center", fontsize=6.8,
                       color="#ffffff" if abs(val) > v * 0.55 else INK)
    a.set_xticks(range(12), ["J", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D"])
    a.set_yticks(range(len(piv.index)), piv.index, fontsize=7.5)
    a.set_title("Mean $ per night by year x month (2015-19 = OOS)")
    a.grid(False)
    fig.colorbar(im, ax=a, fraction=0.03, pad=0.02, format=dollars)

    a = ax[0, 1]
    names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    for df, col, lab, off in ((m, C_BLUE, "MNQ", -0.2), (q, C_ORANGE, "NQ (OOS)", 0.2)):
        g = df.groupby("dow")["pnl"].mean()
        a.bar(g.index + off, g.values, width=0.38, color=col, label=lab)
    a.axhline(0, color=INK2, lw=1)
    a.set_xticks(range(7), names)
    a.yaxis.set_major_formatter(dollars)
    a.set_title("Mean $ per night by entry weekday (Sun = Globex reopen)")
    a.legend(frameon=False)

    a = ax[1, 0]
    for df, col, lab, off in ((m, C_BLUE, "MNQ", -0.2), (q, C_ORANGE, "NQ (OOS)", 0.2)):
        g = df.groupby("month")["pnl"].mean()
        a.bar(g.index + off, g.values, width=0.38, color=col, label=lab)
    a.axhline(0, color=INK2, lw=1)
    a.set_xticks(range(1, 13), ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], fontsize=8)
    a.yaxis.set_major_formatter(dollars)
    a.set_title("Mean $ per night by calendar month")
    a.legend(frameon=False)

    a = ax[1, 1]
    yrs, vals, cols = [], [], []
    for df, col in ((q, C_ORANGE), (m, C_BLUE)):
        g = df.groupby("year")["pnl"].mean()
        yrs += list(g.index)
        vals += list(g.values)
        cols += [col] * len(g)
    a.bar(range(len(yrs)), vals, color=cols, width=0.72)
    for i, v2 in enumerate(vals):
        a.annotate(f"{v2:.0f}", (i, v2), xytext=(0, 3 if v2 >= 0 else -11),
                   textcoords="offset points", ha="center", fontsize=7.5, color=INK2)
    a.axhline(0, color=INK2, lw=1)
    a.set_xticks(range(len(yrs)), yrs, fontsize=8)
    a.yaxis.set_major_formatter(dollars)
    a.set_title("Mean $ per night by year (orange = out of sample)")

    fig.tight_layout()
    fig.savefig(out, dpi=140)
    plt.close(fig)


def fig_conditioning(m, q, out):
    plt = _style()
    from matplotlib.ticker import FuncFormatter
    dollars = FuncFormatter(lambda v, _: f"${v:,.0f}")
    fig, ax = plt.subplots(2, 2, figsize=(14.5, 8.4))
    specs = [("prior_night", "Prior night's P&L quintile"),
             ("prior_day_ret", "Prior RTH day return quintile"),
             ("vol20", "Vol regime: sd of last 20 nights (lagged)"),
             ("trend", "Trend: prior close vs its 50-day average")]
    for a, (col, title) in zip(ax.ravel(), specs):
        a.grid(True, axis="y", lw=0.6, alpha=0.7)
        a.set_axisbelow(True)
        for df, c, lab, off in ((m, C_BLUE, "MNQ", -0.2), (q, C_ORANGE, "NQ (OOS)", 0.2)):
            b = buckets(df, col)
            a.bar(np.arange(len(b)) + off, b["mean"].values, width=0.38, color=c, label=lab)
            if c == C_BLUE:
                for i, (mu, t) in enumerate(zip(b["mean"].values, b["t"].values)):
                    a.annotate(f"t {t:.1f}", (i - 0.2, mu),
                               xytext=(0, 3 if mu >= 0 else -11), textcoords="offset points",
                               ha="center", fontsize=7, color=INK2)
        a.axhline(0, color=INK2, lw=1)
        a.set_xticks(range(5), ["Q1 low", "Q2", "Q3", "Q4", "Q5 high"])
        a.yaxis.set_major_formatter(dollars)
        a.set_title(title)
        a.legend(frameon=False, fontsize=8)
    fig.tight_layout()
    fig.savefig(out, dpi=140)
    plt.close(fig)


# ---------------------------------------------------------------- html ---------
def tbl(df: pd.DataFrame, fmts: dict, cls="") -> str:
    head = "".join(f"<th>{html.escape(str(c))}</th>" for c in df.columns)
    body = []
    for i, r in df.iterrows():
        cells = []
        for c in df.columns:
            v = r[c]
            f = fmts.get(c)
            s = f(v) if f and pd.notna(v) else ("—" if pd.isna(v) else str(v))
            k = "pos" if isinstance(v, (int, float, np.floating)) and pd.notna(v) and \
                c in ("mean", "pnl", "t", "total", "$/night") and v > 0 else \
                ("neg" if isinstance(v, (int, float, np.floating)) and pd.notna(v) and
                 c in ("mean", "pnl", "t", "total", "$/night") and v < 0 else "")
            cells.append(f'<td class="{k}">{s}</td>')
        body.append(f"<tr><th>{html.escape(str(i))}</th>{''.join(cells)}</tr>")
    return (f'<div class="scroll"><table class="{cls}"><thead><tr><th></th>{head}</tr>'
            f"</thead><tbody>{''.join(body)}</tbody></table></div>")


D0 = lambda v: f"${v:,.0f}"
D2 = lambda v: f"${v:,.2f}"
F2 = lambda v: f"{v:,.2f}"
F1 = lambda v: f"{v:,.1f}"
INT = lambda v: f"{v:,.0f}"


def write_html(m, q, hm, hq, path: Path) -> None:
    qs = [0.01, 0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95, 0.99]
    quant = pd.DataFrame({"MNQ 2020-2026": m["pnl"].quantile(qs).values,
                          "NQ 2015-2019 (OOS)": q["pnl"].quantile(qs).values},
                         index=[f"p{int(x*100)}" for x in qs])

    stat_rows = [("Nights", "nights", INT), ("Total $", "total", D0),
                 ("Mean $/night", "mean", D2), ("Median $/night", "median", D2),
                 ("Annualised $ (252)", "yr", D0), ("sd $/night", "sd", D0),
                 ("Sharpe", "sharpe", F2), ("t-stat", "t", F2),
                 ("Profit factor", "pf", F2), ("Hit rate %", "hit", F1),
                 ("Avg win $", "avg_win", D0), ("Avg loss $", "avg_loss", D0),
                 ("Best night", "best", D0), ("Worst night", "worst", D0),
                 ("Max drawdown", "dd", D0), ("Longest win streak", "win_streak", INT),
                 ("Longest loss streak", "loss_streak", INT)]
    stats = pd.DataFrame({"MNQ 2020-2026": [f(hm[k]) for _, k, f in stat_rows],
                          "NQ 2015-2019 (OOS)": [f(hq[k]) for _, k, f in stat_rows]},
                         index=[n for n, _, _ in stat_rows])

    yr = pd.concat([q.assign(e="NQ (OOS)"), m.assign(e="MNQ")]).groupby(["e", "year"])["pnl"]
    yearly = pd.DataFrame({"nights": yr.size(), "$/night": yr.mean(),
                           "total $": yr.sum(), "hit %": yr.apply(lambda s: (s > 0).mean() * 100),
                           "worst": yr.min(), "best": yr.max()})
    yearly.index = [f"{e} {y}" for e, y in yearly.index]

    dow = m.groupby("dow")["pnl"].agg(["size", "mean", "sum"])
    dow.index = [["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][i] for i in dow.index]
    dow.columns = ["nights", "$/night", "total $"]

    tails = pd.concat([m.nsmallest(10, "pnl")[["pnl", "mfe_usd", "mae_usd"]],
                       m.nlargest(10, "pnl")[["pnl", "mfe_usd", "mae_usd"]]])
    tails.columns = ["net $", "best moment $", "worst moment $"]
    tails.index = [d.strftime("%Y-%m-%d") for d in tails.index]

    cond = {}
    for col, nm in (("prior_night", "Prior night P&L"), ("prior_day_ret", "Prior RTH day %"),
                    ("vol20", "20-night vol (lagged)"), ("trend", "Close vs 50d avg %")):
        b = buckets(m, col)
        b.index = [f"{nm} {i}" for i in b.index]
        cond[col] = b
    condall = pd.concat(cond.values())[["n", "lo", "hi", "mean", "hit", "t"]]
    condall.columns = ["nights", "bucket low", "bucket high", "$/night", "hit %", "t"]

    F = {"nights": INT, "$/night": D2, "total $": D0, "hit %": F1, "worst": D0,
         "best": D0, "net $": D0, "best moment $": D0, "worst moment $": D0,
         "bucket low": F2, "bucket high": F2, "t": F2,
         "MNQ 2020-2026": D0, "NQ 2015-2019 (OOS)": D0}

    doc = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Overnight Drift Data</title>
<style>
:root{{color-scheme:light;--s0:#f5f4f1;--s1:#fcfcfb;--s2:#efeeea;--t1:#0b0b0b;
 --t2:#52514e;--t3:#77756f;--line:#dedcd6;--blue:#2a78d6;--good:#0ca30c;--crit:#d03b3b}}
@media (prefers-color-scheme:dark){{:root:not([data-theme="light"]){{color-scheme:dark;
 --s0:#141413;--s1:#1a1a19;--s2:#232322;--t1:#fff;--t2:#c3c2b7;--t3:#94938a;
 --line:#33322f;--blue:#3987e5;--good:#0ca30c;--crit:#e66767}}}}
:root[data-theme="dark"]{{color-scheme:dark;--s0:#141413;--s1:#1a1a19;--s2:#232322;
 --t1:#fff;--t2:#c3c2b7;--t3:#94938a;--line:#33322f;--blue:#3987e5;--crit:#e66767}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--s0);color:var(--t1);
 font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}}
.wrap{{max-width:1240px;margin:0 auto;padding:34px 20px 80px}}
h1{{font-size:27px;margin:0 0 6px;letter-spacing:-.02em}}
h2{{font-size:19px;margin:44px 0 4px;letter-spacing:-.01em}}
.meta{{color:var(--t3);font-size:12.5px;font-variant-numeric:tabular-nums;margin:0 0 6px}}
.cap{{color:var(--t3);font-size:12.5px;margin:6px 0 0}}
.tiles{{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px;margin:18px 0}}
.tile{{background:var(--s1);border:1px solid var(--line);border-radius:9px;padding:12px 14px}}
.tile .k{{font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--t3)}}
.tile .v{{font-size:23px;font-weight:650;margin-top:3px;font-variant-numeric:tabular-nums;
 letter-spacing:-.02em}}
.tile .n{{font-size:12px;color:var(--t2);margin-top:2px}}
.scroll{{overflow-x:auto;margin:14px 0;border:1px solid var(--line);border-radius:9px}}
table{{border-collapse:collapse;width:100%;font-size:13px;background:var(--s1);
 font-variant-numeric:tabular-nums}}
th,td{{padding:6px 12px;text-align:right;border-bottom:1px solid var(--line);white-space:nowrap}}
tbody th{{text-align:left;font-weight:500;color:var(--t2)}}
thead th{{background:var(--s2);color:var(--t2);font-size:12px;font-weight:620;
 text-transform:uppercase;letter-spacing:.04em;text-align:right}}
tbody tr:last-child td,tbody tr:last-child th{{border-bottom:none}}
.pos{{color:var(--good)}}.neg{{color:var(--crit)}}
img{{width:100%;height:auto;display:block;border:1px solid var(--line);border-radius:9px;
 background:#fcfcfb;margin-top:14px}}
.grid2{{display:grid;grid-template-columns:1fr 1fr;gap:18px}}
@media(max-width:900px){{.grid2{{grid-template-columns:1fr}}}}
code{{font-family:ui-monospace,Consolas,monospace;font-size:12.5px;background:var(--s2);
 padding:1px 5px;border-radius:4px}}
footer{{color:var(--t3);font-size:12.5px;margin-top:40px;border-top:1px solid var(--line);
 padding-top:16px}}
</style></head><body><div class="wrap">

<h1>MNQ overnight drift — data sheet</h1>
<p class="meta">Long 18:00 ET reopen → flat 06:00 ET open · 1-tick round trip charged ·
MNQ {m.index[0].date()} → {m.index[-1].date()} ({hm['nights']:,} nights, in sample) ·
NQ {q.index[0].date()} → {q.index[-1].date()} ({hq['nights']:,} nights, out of sample,
rescaled to today's notional)</p>

<div class="tiles">
  <div class="tile"><div class="k">$ / night</div><div class="v">{hm['mean']:.2f}</div>
    <div class="n">OOS {hq['mean']:.2f}</div></div>
  <div class="tile"><div class="k">t-stat</div><div class="v">{hm['t']:.2f}</div>
    <div class="n">OOS {hq['t']:.2f}</div></div>
  <div class="tile"><div class="k">Sharpe</div><div class="v">{hm['sharpe']:.2f}</div>
    <div class="n">OOS {hq['sharpe']:.2f}</div></div>
  <div class="tile"><div class="k">Profit factor</div><div class="v">{hm['pf']:.2f}</div>
    <div class="n">OOS {hq['pf']:.2f}</div></div>
  <div class="tile"><div class="k">Hit rate</div><div class="v">{hm['hit']:.1f}%</div>
    <div class="n">OOS {hq['hit']:.1f}%</div></div>
  <div class="tile"><div class="k">Max DD</div><div class="v">{hm['dd']:,.0f}</div>
    <div class="n">OOS {hq['dd']:,.0f}</div></div>
  <div class="tile"><div class="k">Worst night</div><div class="v">{hm['worst']:,.0f}</div>
    <div class="n">OOS {hq['worst']:,.0f}</div></div>
  <div class="tile"><div class="k">sd / night</div><div class="v">{hm['sd']:,.0f}</div>
    <div class="n">OOS {hq['sd']:,.0f}</div></div>
</div>

<h2>1 · Performance</h2>
<img src="drift_performance.png" alt="Equity, drawdown, rolling mean and rolling Sharpe">
<p class="cap">Equity and drawdown per contract; rolling 250-night mean and annualised Sharpe.</p>
{tbl(stats, {}, "stats")}

<h2>2 · Distribution and where the money accrues</h2>
<img src="drift_distribution.png" alt="P&L distribution, CDF, intranight path, hourly contribution">
<div class="grid2">
<div><p class="cap">Nightly P&amp;L quantiles, $ per contract</p>{tbl(quant, F)}</div>
<div><p class="cap">By entry weekday, MNQ</p>{tbl(dow, F)}</div>
</div>

<h2>3 · Seasonality</h2>
<img src="drift_seasonality.png" alt="Year-month heatmap, weekday, month, year bars">
<p class="cap">Per-year detail, both eras</p>
{tbl(yearly, F)}

<h2>4 · Lagged regime buckets</h2>
<img src="drift_conditioning.png" alt="Quintile buckets by prior night, prior day, vol, trend">
<p class="cap">Every key is known before the 18:00 entry. Descriptive — prior work found
bucket selection does not survive train/test.</p>
{tbl(condall, F)}

<h2>5 · Tails — 10 worst and 10 best nights (MNQ)</h2>
{tbl(tails, F)}

<footer>Generated by <code>mnq_overnight_drift_dashboard.py</code> ·
per-night data: <a href="drift_nights.csv">drift_nights.csv</a> ·
regenerate and refresh to update every number and chart on this page.</footer>
</div></body></html>"""
    path.write_text(doc, encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--serve", type=int, default=0, help="serve the report on this port")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    mnq_raw, pm = build("MNQ_5min_databento.parquet")
    nq_raw, pq = build("NQ_5min_databento.parquet")
    keep = np.asarray(nq_raw.index < mnq_raw.index[0])
    nq_raw, pq = nq_raw[keep], pq[keep]
    ref = float(np.median(mnq_raw.loc[mnq_raw.index.year >= 2024, "entry"]))

    m = price(mnq_raw, None)
    q = price(nq_raw, ref)
    hm, hq = headline(m["pnl"]), headline(q["pnl"])
    refscale = ref / float(np.median(nq_raw["entry"]))

    fig_performance(m, q, OUT / "drift_performance.png")
    fig_distribution(m, q, pm, pq, refscale, OUT / "drift_distribution.png")
    fig_seasonality(m, q, OUT / "drift_seasonality.png")
    fig_conditioning(m, q, OUT / "drift_conditioning.png")
    m.to_csv(OUT / "drift_nights.csv")
    write_html(m, q, hm, hq, OUT / "index.html")

    print(f"MNQ  {hm['nights']:,} nights  ${hm['mean']:.2f}/nt  t {hm['t']:.2f}  "
          f"Sharpe {hm['sharpe']:.2f}  PF {hm['pf']:.2f}  hit {hm['hit']:.1f}%  "
          f"DD ${hm['dd']:,.0f}")
    print(f"NQ   {hq['nights']:,} nights  ${hq['mean']:.2f}/nt  t {hq['t']:.2f}  "
          f"Sharpe {hq['sharpe']:.2f}  PF {hq['pf']:.2f}  hit {hq['hit']:.1f}%  "
          f"DD ${hq['dd']:,.0f}")
    print(f"report -> {OUT / 'index.html'}")

    if args.serve:
        import functools
        import http.server
        import socketserver
        h = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(OUT))
        with socketserver.TCPServer(("127.0.0.1", args.serve), h) as srv:
            print(f"serving http://127.0.0.1:{args.serve}/  (ctrl-c to stop)")
            srv.serve_forever()


if __name__ == "__main__":
    main()
