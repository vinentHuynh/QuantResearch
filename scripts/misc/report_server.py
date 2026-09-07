"""Local dashboard for the Carver backtest reports.

Stdlib HTTP server, no framework and no CDN -- charts are hand-rolled inline SVG
so the page works offline and the colours come from CSS custom properties rather
than being baked into a raster.

    .venv\\Scripts\\python.exe report_server.py
    .venv\\Scripts\\python.exe report_server.py --port 8899 --no-open

CSVs are re-read on every request, so re-running a backtest and hitting refresh
shows the new numbers -- no restart needed.

Palette is the dataviz reference instance, validated with its own tool:
4-slot categorical passes every gate in both modes (worst adjacent CVD dE 9.1
light / 8.4 dark). Two light-mode slots sit under 3:1 on the light surface, so
the relief rule applies and every series carries a direct label plus a table
view. Sharpe bars use the documented diverging pair (blue/red, gray midpoint)
because the number's job is POLARITY -- did it make money or lose it.
"""
from __future__ import annotations

import argparse
import html
import math
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import numpy as np
import pandas as pd

REPORTS = (Path(__file__).resolve().parents[2] / "reports")

CAT = ["var(--series-1)", "var(--series-2)", "var(--series-3)", "var(--series-4)",
       "var(--series-5)", "var(--series-6)", "var(--series-7)", "var(--series-8)"]

PAGES = [("/", "Overview"), ("/howto", "How to trade it"),
         ("/orb", "Opening range"), ("/overnight", "Overnight drift"),
         ("/book", "Rule book"), ("/raw", "Raw reports")]


# ------------------------------------------------------------------ data ------
def read(name, **kw):
    p = REPORTS / name
    return pd.read_csv(p, **kw) if p.exists() else None


def curves(name):
    """Daily-return panel -> equity curves, indexed by date."""
    df = read(name, index_col=0, parse_dates=True)
    if df is None or df.empty:
        return None
    return (1 + df.fillna(0.0)).cumprod()


def sr(series):
    s = series.dropna()
    return (s.mean() * 252) / (s.std() * 16) if len(s) > 2 and s.std() else float("nan")


# ------------------------------------------------------------------ svg -------
def _fmt(v, kind):
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return "n/a"
    if kind == "pct":
        return "%.1f%%" % (v * 100)
    if kind == "sr":
        return "%+.2f" % v
    if kind == "x":
        return "%.2fx" % v
    if kind == "pct0":
        return "%.0f%%" % v
    if kind == "money":
        return "${:,.0f}".format(v)
    return "{:,.0f}".format(v)


def line_chart(frame, title, subtitle="", ylab="growth of 1", height=300,
               logy=False, fmt="x", xlabels=None):
    """Multi-series line chart with crosshair + tooltip and direct end-labels.

    Direct labels are not decoration here -- two light-mode palette slots fall
    under 3:1 on the light surface, and the relief rule makes labels mandatory
    rather than optional.
    """
    if frame is None or frame.empty:
        return "<p class='empty'>no data</p>"
    frame = frame.dropna(how="all")
    cols = list(frame.columns)[:8]
    W, H = 900, height
    ml, mr, mt, mb = 52, 132, 14, 30
    pw, ph = W - ml - mr, H - mt - mb
    vals = frame[cols].values.astype(float)
    lo, hi = np.nanmin(vals), np.nanmax(vals)
    if logy:
        lo, hi = max(lo, 1e-6), max(hi, 1e-6)
        f = lambda v: math.log10(max(v, 1e-6))
        lo_t, hi_t = f(lo), f(hi)
    else:
        f = lambda v: v
        lo_t, hi_t = lo, hi
    if hi_t == lo_t:
        hi_t = lo_t + 1
    pad = (hi_t - lo_t) * 0.06
    lo_t, hi_t = lo_t - pad, hi_t + pad
    n = len(frame)
    x = lambda i: ml + pw * (i / max(n - 1, 1))
    y = lambda v: mt + ph * (1 - (f(v) - lo_t) / (hi_t - lo_t))

    parts = ['<svg class="chart" viewBox="0 0 %d %d" role="img" '
             'aria-label="%s">' % (W, H, html.escape(title))]
    # gridlines + y axis
    for k in range(5):
        t = lo_t + (hi_t - lo_t) * k / 4
        yy = mt + ph * (1 - k / 4)
        v = (10 ** t) if logy else t
        parts.append('<line class="grid" x1="%d" y1="%.1f" x2="%d" y2="%.1f"/>'
                     % (ml, yy, ml + pw, yy))
        parts.append('<text class="tick" x="%d" y="%.1f" text-anchor="end">%s</text>'
                     % (ml - 8, yy + 4, _fmt(v, fmt)))
    # x ticks -- dates by default, but a non-time axis must label itself honestly
    ticks = range(n) if (xlabels and n <= 8) else [int((n - 1) * k / 4)
                                                  for k in range(5)]
    for i in ticks:
        lab = str(xlabels[i]) if xlabels else frame.index[i].strftime("%Y-%m")
        parts.append('<text class="tick" x="%.1f" y="%d" text-anchor="middle">%s</text>'
                     % (x(i), H - 10, html.escape(lab)))
    # series
    for j, c in enumerate(cols):
        s = frame[c].astype(float).values
        pts = " ".join("%.1f,%.1f" % (x(i), y(s[i])) for i in range(n)
                       if math.isfinite(s[i]))
        parts.append('<polyline class="ln" points="%s" stroke="%s"/>'
                     % (pts, CAT[j % len(CAT)]))
        parts.append('<text class="endlab" x="%.1f" y="%.1f" fill="%s">%s</text>'
                     % (ml + pw + 8, y(s[-1]) + 4, CAT[j % len(CAT)],
                        html.escape(str(c)[:20])))
    parts.append('<line class="cross" x1="0" y1="%d" x2="0" y2="%d" '
                 'style="display:none"/>' % (mt, mt + ph))
    parts.append('<rect class="hit" x="%d" y="%d" width="%d" height="%d" '
                 'fill="transparent"/>' % (ml, mt, pw, ph))
    parts.append("</svg>")
    payload = {"n": n, "ml": ml, "pw": pw,
               "dates": ([str(v) for v in xlabels] if xlabels else
                         [d.strftime("%Y-%m-%d") for d in frame.index]),
               "cols": [str(c) for c in cols],
               "vals": [[None if not math.isfinite(v) else round(float(v), 4)
                         for v in frame[c].values] for c in cols],
               "colors": [CAT[j % len(CAT)] for j in range(len(cols))]}
    return _figure(title, subtitle, "".join(parts), payload, ylab)


def bar_chart(labels, values, title, subtitle="", fmt="sr", height=None,
              diverging=True):
    """Horizontal bars. Diverging blue/red because the value's job is POLARITY.

    4px rounded ends on the data side, square against the baseline; a 2px
    surface gap between adjacent bars.
    """
    if not len(labels):
        return "<p class='empty'>no data</p>"
    vals = [float(v) if v is not None and math.isfinite(float(v)) else 0.0
            for v in values]
    rowh, gap = 22, 2
    W = 900
    ml, mr, mt = 260, 70, 8
    H = height or (mt * 2 + len(vals) * (rowh + gap))
    pw = W - ml - mr
    lo, hi = min(min(vals), 0.0), max(max(vals), 0.0)
    span = (hi - lo) or 1.0
    zero = ml + pw * (0 - lo) / span
    parts = ['<svg class="chart" viewBox="0 0 %d %d" role="img" '
             'aria-label="%s">' % (W, H, html.escape(title))]
    parts.append('<line class="grid zero" x1="%.1f" y1="%d" x2="%.1f" y2="%d"/>'
                 % (zero, mt, zero, H - mt))
    for i, (lab, v) in enumerate(zip(labels, vals)):
        yy = mt + i * (rowh + gap)
        xv = ml + pw * (v - lo) / span
        x0, x1 = (zero, xv) if v >= 0 else (xv, zero)
        col = ("var(--pos)" if v >= 0 else "var(--neg)") if diverging else CAT[0]
        r = 4
        parts.append('<rect class="bar" x="%.1f" y="%d" width="%.1f" height="%d" '
                     'fill="%s" rx="%d" data-lab="%s" data-val="%s"/>'
                     % (x0, yy, max(x1 - x0, 1.5), rowh - 4, col, r,
                        html.escape(str(lab)), _fmt(v, fmt)))
        parts.append('<text class="rowlab" x="%d" y="%d" text-anchor="end">%s</text>'
                     % (ml - 10, yy + rowh - 8, html.escape(str(lab)[:42])))
        parts.append('<text class="rowval" x="%.1f" y="%d">%s</text>'
                     % ((x1 + 6) if v >= 0 else (x0 - 6), yy + rowh - 8,
                        _fmt(v, fmt)))
    parts.append("</svg>")
    return _figure(title, subtitle, "".join(parts), None, "")


def _figure(title, subtitle, svg, payload, ylab):
    import json
    d = (" data-chart='%s'" % html.escape(json.dumps(payload), quote=True)) \
        if payload else ""
    sub = ("<p class='sub'>%s</p>" % subtitle) if subtitle else ""
    return ("<figure class='fig'%s><figcaption><h3>%s</h3>%s</figcaption>"
            "<div class='plot'>%s<div class='tip' hidden></div></div>"
            "</figure>" % (d, html.escape(title), sub, svg))


def candle_chart(bars, t, title, subtitle=""):
    """One real session, annotated with the trade the backtest actually took.

    The candles are CONTEXT, so they carry no hue at all -- up bars are hollow,
    down bars filled, which is shape encoding and survives any colour vision.
    Colour is spent only on the three lines that ARE the strategy: entry, stop,
    target. Those three sit in the 6-8 CVD warn band against each other, so each
    also gets its own dash pattern and a permanent right-edge label; identity
    never rests on hue alone.
    """
    n = len(bars)
    if not n:
        return "<p class='empty'>no data</p>"
    W, H = 900, 340
    ml, mr, mt, mb = 58, 122, 16, 30
    pw, ph = W - ml - mr, H - mt - mb
    levels = [t["or_hi"], t["or_lo"], t["entry"], t["stop"], t["target"]]
    lo = min(float(bars.low.min()), *levels)
    hi = max(float(bars.high.max()), *levels)
    pad = (hi - lo) * 0.06 or 1.0
    lo, hi = lo - pad, hi + pad
    x = lambda i: ml + pw * (i + 0.5) / n
    y = lambda v: mt + ph * (1 - (v - lo) / (hi - lo))
    cw = max(pw / n * 0.62, 1.4)
    idx = list(bars.index)
    pos = {ts: i for i, ts in enumerate(idx)}
    or_bars = 3                                    # 15-minute range on 5-min bars

    p = ['<svg class="chart" viewBox="0 0 %d %d" role="img" aria-label="%s">'
         % (W, H, html.escape(title))]
    for k in range(5):
        v = lo + (hi - lo) * k / 4
        yy = y(v)
        p.append('<line class="grid" x1="%d" y1="%.1f" x2="%d" y2="%.1f"/>'
                 % (ml, yy, ml + pw, yy))
        p.append('<text class="tick" x="%d" y="%.1f" text-anchor="end">%s</text>'
                 % (ml - 8, yy + 4, "{:,.0f}".format(v)))
    for k in range(0, n, 12):
        p.append('<text class="tick" x="%.1f" y="%d" text-anchor="middle">%s</text>'
                 % (x(k), H - 10, idx[k].strftime("%H:%M")))

    # opening range: the box you are watching, and its two levels extended
    p.append('<rect class="orbox" x="%.1f" y="%.1f" width="%.1f" height="%.1f"/>'
             % (ml, y(t["or_hi"]), x(or_bars - 1) - ml + cw,
                max(y(t["or_lo"]) - y(t["or_hi"]), 1)))
    for lv in (t["or_hi"], t["or_lo"]):
        p.append('<line class="orline" x1="%.1f" y1="%.1f" x2="%d" y2="%.1f"/>'
                 % (ml, y(lv), ml + pw, y(lv)))
    p.append('<text class="orlab" x="%.1f" y="%.1f">opening range 09:30-09:45</text>'
             % (ml + 2, y(t["or_hi"]) - 6))

    # candles
    for i, (ts, b) in enumerate(bars.iterrows()):
        up = b["close"] >= b["open"]
        p.append('<line class="wick" x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f"/>'
                 % (x(i), y(b["high"]), x(i), y(b["low"])))
        top, bot = y(max(b["open"], b["close"])), y(min(b["open"], b["close"]))
        p.append('<rect class="cd %s" x="%.1f" y="%.1f" width="%.1f" '
                 'height="%.1f"/>' % ("up" if up else "dn", x(i) - cw / 2, top,
                                      cw, max(bot - top, 1.4)))

    ei = pos.get(t["entry_ts"], 0)
    xi = pos.get(t["exit_ts"], n - 1)
    # the bar whose CLOSE triggered the signal -- you fill on the NEXT one
    si = pos.get(t["sig_ts"], max(ei - 1, 0))
    p.append('<rect class="sigbar" x="%.1f" y="%d" width="%.1f" height="%d"/>'
             % (x(si) - cw / 2 - 1, mt, cw + 2, ph))

    for lv, cls, lab in ((t["entry"], "entry", "ENTRY"),
                         (t["stop"], "stop", "STOP"),
                         (t["target"], "target", "TARGET")):
        p.append('<line class="lvl %s" x1="%.1f" y1="%.1f" x2="%d" y2="%.1f"/>'
                 % (cls, x(ei), y(lv), ml + pw, y(lv)))
        p.append('<text class="lvllab %s" x="%d" y="%.1f">%s %s</text>'
                 % (cls, ml + pw + 7, y(lv) + 4, lab, "{:,.0f}".format(lv)))
    p.append('<circle class="mk entry" cx="%.1f" cy="%.1f" r="5"/>'
             % (x(ei), y(t["entry"])))
    p.append('<circle class="mk exitmk" cx="%.1f" cy="%.1f" r="5"/>'
             % (x(xi), y(t["exit"])))
    p.append('<text class="note" x="%.1f" y="%.1f" text-anchor="middle">fill</text>'
             % (x(ei), y(t["entry"]) + 20))
    p.append('<text class="note" x="%.1f" y="%.1f" text-anchor="middle">exit %s</text>'
             % (x(xi), y(t["exit"]) - 12, t["why"]))
    p.append("</svg>")
    return _figure(title, subtitle, "".join(p), None, "")


def grouped_bars(df, title, subtitle="", fmt="pct1"):
    """Two measures that are BOTH percentages of their own total -> one axis.

    A dual axis here would let the two bars be scaled independently, which is
    exactly the comparison the chart exists to make honestly.
    """
    if df is None or df.empty:
        return "<p class='empty'>no data</p>"
    cats, series = list(df.index), list(df.columns)
    W = 900
    ml, mr, mt, mb = 90, 24, 12, 52
    rowh = 54
    H = mt + len(cats) * rowh + mb
    pw = W - ml - mr
    top = float(np.nanmax(df.values)) * 1.12 or 1.0
    p = ['<svg class="chart" viewBox="0 0 %d %d" role="img" aria-label="%s">'
         % (W, H, html.escape(title))]
    for i, c in enumerate(cats):
        y0 = mt + i * rowh
        p.append('<text class="rowlab" x="%d" y="%d" text-anchor="end">%s</text>'
                 % (ml - 10, y0 + 30, html.escape(str(c))))
        for j, s in enumerate(series):
            v = float(df.loc[c, s])
            bh = 18
            yy = y0 + j * (bh + 2) + 2
            w = max(pw * v / top, 1.5)
            p.append('<rect class="bar" x="%d" y="%d" width="%.1f" height="%d" '
                     'fill="%s" rx="4" data-lab="%s" data-val="%.1f%%"/>'
                     % (ml, yy, w, bh, CAT[j], html.escape("%s - %s" % (c, s)), v))
            p.append('<text class="rowval" x="%.1f" y="%d">%.0f%%</text>'
                     % (ml + w + 6, yy + 13, v))
    for j, s in enumerate(series):
        p.append('<rect x="%d" y="%d" width="10" height="10" rx="2" fill="%s"/>'
                 % (ml + j * 200, H - 26, CAT[j]))
        p.append('<text class="tick" x="%d" y="%d">%s</text>'
                 % (ml + 16 + j * 200, H - 17, html.escape(str(s))))
    p.append("</svg>")
    return _figure(title, subtitle, "".join(p), None, "")


def table(df, fmts=None, title=None, max_rows=200):
    """Table view. Required relief for the sub-3:1 light-mode palette slots."""
    if df is None or df.empty:
        return "<p class='empty'>no data</p>"
    fmts = fmts or {}
    df = df.head(max_rows)
    head = "".join("<th>%s</th>" % html.escape(str(c)) for c in
                   ([df.index.name or ""] + list(df.columns)))
    rows = []
    for idx, r in df.iterrows():
        cells = ["<th scope='row'>%s</th>" % html.escape(str(idx))]
        for c in df.columns:
            v = r[c]
            if c in fmts and isinstance(v, (int, float, np.floating)) \
                    and math.isfinite(float(v)):
                # "{}"-style where a thousands separator is wanted (% has no ","),
                # "%"-style everywhere else.
                txt = fmts[c].format(v) if fmts[c].startswith("{") else fmts[c] % v
            elif isinstance(v, (float, np.floating)):
                txt = "n/a" if not math.isfinite(float(v)) else "%.3f" % v
            else:
                txt = str(v)
            cls = ""
            if isinstance(v, (int, float, np.floating)) and math.isfinite(float(v)):
                cls = " class='neg'" if float(v) < 0 else ""
            cells.append("<td%s>%s</td>" % (cls, html.escape(txt)))
        rows.append("<tr>%s</tr>" % "".join(cells))
    cap = ("<caption>%s</caption>" % html.escape(title)) if title else ""
    return ("<div class='tw'><table>%s<thead><tr>%s</tr></thead><tbody>%s</tbody>"
            "</table></div>" % (cap, head, "".join(rows)))


def stat(label, value, note=""):
    return ("<div class='stat'><span class='k'>%s</span>"
            "<span class='v'>%s</span><span class='n'>%s</span></div>"
            % (html.escape(label), html.escape(str(value)), html.escape(note)))


# ------------------------------------------------------------------ pages -----
def page_overview():
    o = []
    S = read("orb_carver_summary.csv", index_col=0)
    ov = read("overnight_carver_summary.csv", index_col=0)
    L = read("book_ladder.csv", index_col=0)

    best = "n/a"
    if S is not None:
        best = "%+.2f" % S.best_SR_net.max()
    o.append("<section class='stats'>")
    o.append(stat("Best ORB (MNQ)", best, "net Sharpe, 6.6 yr, p=0.03"))
    if ov is not None and "MNQ ON 18-06" in ov.index:
        o.append(stat("Overnight MNQ 18-06", "%+.2f" % ov.loc["MNQ ON 18-06", "SR_net"],
                      "net Sharpe"))
    if L is not None:
        o.append(stat("Full rule book", "%+.2f" % L.SR_net.iloc[-2],
                      "4 instruments, 95% CI [-0.08, +1.27]"))
    o.append(stat("Risk target", "12%", "Carver Starter System tau"))
    o.append("</section>")

    o.append("<p class='lede'>Three studies, one framework. Every number is net of "
             "modelled costs, vol-scaled to a 12% risk target, and computed on "
             "seam-free P&amp;L so a roll step is never booked as profit.</p>")

    c = curves("orb_carver_daily_returns.csv")
    if c is not None:
        pick = [x for x in c.columns if "OR15|or_stop_2r|both" in x.replace(" ", "")]
        if pick:
            o.append(line_chart(c[pick].rename(columns=lambda s: s.split()[0]),
                                "Opening-range breakout, best cell per instrument",
                                "OR15 / stop+2R / both directions. Growth of 1 on "
                                "fixed capital.", logy=True))
    b = curves("book_daily_returns.csv")
    if b is not None:
        pick = [x for x in ("BOOK full4", "BOOK trend4", "COMBO MNQ", "TREND MNQ")
                if x in b.columns]
        if pick:
            o.append(line_chart(b[pick], "Rule book: trend, overnight, and both",
                                "Vol-scaled sleeves combined with a measured IDM.",
                                logy=True))
    if S is not None:
        o.append(table(S, {"years": "%.1f", "apriori_cost_SR": "%.3f",
                           "measured_cost_SR": "%.3f", "understated_x": "%.1fx",
                           "best_SR_net": "%+.2f", "p_best": "%.3f",
                           "starter_SR": "%+.2f"},
                       "ORB cross-instrument summary"))
    return "".join(o)


def page_orb():
    o = ["<p class='lede'>Anchor fixed at the 09:30 RTH open. 18 cells per "
         "instrument, scored against a sign-flip permutation null on the maximum. "
         "MNQ is the only instrument where the result survives its stress panel.</p>"]
    S = read("orb_carver_summary.csv", index_col=0)
    if S is not None:
        o.append(table(S, {"years": "%.1f", "apriori_cost_SR": "%.3f",
                           "measured_cost_SR": "%.3f", "understated_x": "%.1fx",
                           "best_SR_net": "%+.2f", "p_best": "%.3f",
                           "starter_SR": "%+.2f"}, "Summary"))
    for inst in ("MNQ", "MES", "MGC"):
        g = read("orb_carver_grid_%s.csv" % inst, index_col=0)
        if g is None:
            continue
        o.append("<h2>%s</h2>" % inst)
        gs = g.sort_values("SR_net")
        o.append(bar_chart(list(gs.index), list(gs.SR_net),
                           "%s — net Sharpe by grid cell" % inst,
                           "Blue positive, red negative. All 18 cells shown; the "
                           "maximum of 18 correlated draws is not a result."))
        o.append(table(g.sort_values("SR_net", ascending=False),
                       {"trades_yr": "%.0f", "SR_gross": "%+.2f", "cost_SR": "%.3f",
                        "SR_net": "%+.2f", "ann_vol": "%.3f", "maxDD": "%.3f",
                        "skew": "%+.2f", "avg_ct": "%.1f", "net_$": "{:,.0f}"},
                       "%s grid" % inst))
    st = read("orb_carver_stress.csv")
    if st is not None:
        piv = st.pivot(index="test", columns="inst", values="SR")
        order = ["cost 1 tk", "cost 2 tk", "cost 4 tk", "cost 6 tk", "cost 8 tk",
                 "cost 12 tk", "stop slip +0 tk", "stop slip +1 tk",
                 "stop slip +2 tk", "stop slip +4 tk", "1st half", "2nd half",
                 "ex-COVID", "drop best 5", "drop best 20"]
        piv = piv.reindex([x for x in order if x in piv.index])
        cost = piv.loc[[i for i in piv.index if i.startswith("cost")]]
        if not cost.empty:
            # Magnitude against a PARAMETER, not against time -- so the x axis
            # labels itself with tick counts. Faking a date axis here would be a
            # lie about what the horizontal direction means.
            ticks = [int(i.split()[1]) for i in cost.index]
            o.append(line_chart(
                cost.reset_index(drop=True),
                "Cost sweep: Sharpe vs round-trip slippage",
                "MNQ still pays at 12 ticks; MES and MGC are gone by 4-6. This is "
                "the test that separates a real edge from a flattered one.",
                fmt="sr", height=260, xlabels=["%d tk" % t for t in ticks]))
        o.append(table(piv, {c: "%+.2f" for c in piv.columns}, "Stress panel"))
    return "".join(o)


def page_overnight():
    o = ["<p class='lede'>Pre-specified 18:00-06:00 and 23:00-04:00 blocks — no "
         "window searched. Block P&amp;L runs first open to last close inside the "
         "block, so roll seams are never held.</p>"]
    R = read("overnight_carver_summary.csv", index_col=0)
    if R is not None:
        keep = [c for c in ("years", "trades_yr", "SR_gross", "cost_SR", "SR_net",
                            "ann_vol", "vol_vs_tau", "maxDD", "skew", "win_rate",
                            "net_$") if c in R.columns]
        rs = R[keep].sort_values("SR_net", ascending=False)
        o.append(bar_chart(list(rs.index), list(rs.SR_net),
                           "Net Sharpe by strategy", "Seam-free P&L. "
                           "[c2c] rows price the same book close-to-close, which "
                           "books the contango roll step as profit."))
        o.append(table(rs, {"years": "%.1f", "trades_yr": "%.0f",
                            "SR_gross": "%+.2f", "cost_SR": "%.3f",
                            "SR_net": "%+.2f", "ann_vol": "%.3f",
                            "vol_vs_tau": "%.2f", "maxDD": "%.3f",
                            "skew": "%+.2f", "win_rate": "%.3f", "net_$": "{:,.0f}"},
                       "All strategies"))
    c = curves("overnight_carver_daily_returns.csv")
    if c is not None:
        pick = [x for x in ("MNQ ON 18-06", "MES ON 18-06", "MGC ON 18-06",
                            "MCL ON 18-06") if x in c.columns]
        if pick:
            o.append(line_chart(c[pick], "Overnight block 18:00-06:00 by instrument",
                                "Growth of 1, vol-scaled to tau=12%.", logy=True))
        pick = [x for x in c.columns if x.startswith("BOOK")][:4]
        if pick:
            o.append(line_chart(c[pick], "Books", "Handcrafted weights x measured IDM.",
                                logy=True))
    cs = read("overnight_carver_cost_screen.csv", index_col=0)
    if cs is not None:
        o.append(table(cs, {"contract_$": "{:,.0f}", "ann_vol": "%.3f",
                            "ann_vol_$": "{:,.0f}", "cost_SR_trade": "%.6f",
                            "cost@504": "%.3f", "min_cap_1ct": "{:,.0f}",
                            "min_cap_4ct": "{:,.0f}"},
                       "Cost screen (a-priori — a LOWER bound for part-time rules)"))
    return "".join(o)


def page_book():
    o = ["<p class='lede'>Carver ranks improvements: more instruments &gt; more "
         "rules &gt; continuous forecasts. Each rung below is the previous rung "
         "plus one change, so the step column is meaningful.</p>"]
    L = read("book_ladder.csv", index_col=0)
    if L is not None:
        o.append(bar_chart(list(L.index), list(L.SR_net),
                           "The improvement ladder", "Net Sharpe at each rung."))
        o.append(table(L, {"SR_net": "%+.2f", "step": "%+.2f", "ann_vol": "%.3f",
                           "vol_vs_tau": "%.2f", "maxDD": "%.3f",
                           "DD_in_tau": "%.1f", "skew": "%+.2f"}, "Ladder"))
    RU = read("book_rule_speed_limit.csv")
    if RU is not None and {"inst", "rule"} <= set(RU.columns):
        RU = RU.set_index(["inst", "rule"])
        o.append(table(RU, {"lots_traded_yr": "{:,.0f}", "avg_pos": "%.1f",
                            "cost_SR": "%.3f", "SR_gross": "%+.2f",
                            "SR_net": "%+.2f"},
                       "Speed limit per rule per instrument"))
    b = curves("book_daily_returns.csv")
    if b is not None:
        pick = [x for x in b.columns if x.startswith("TREND")][:4]
        if pick:
            o.append(line_chart(b[pick], "Trend sleeves", "EWMAC 16/64 + 32/128 + "
                                "64/256, published scalars, FDM ~1.07.", logy=True))
        pick = [x for x in b.columns if x.startswith("COMBO")][:4]
        if pick:
            o.append(line_chart(b[pick], "Trend + overnight, per instrument",
                                "50/50 sleeves x measured diversification "
                                "multiplier.", logy=True))
    return "".join(o)


def page_raw():
    o = ["<p class='lede'>Console output exactly as the scripts produced it.</p>"]
    for f in sorted(REPORTS.glob("*_report.txt")):
        o.append("<details><summary>%s</summary><pre>%s</pre></details>"
                 % (html.escape(f.name),
                    html.escape(f.read_text(errors="replace"))))
    return "".join(o)


def page_howto():
    import orb_playbook as P
    o = ["<p class='lede'>Every chart on this page is a real session the backtest "
         "traded, annotated with the fills it actually took. The three examples "
         "sit near the <em>median</em> outcome for their exit type, so this is the "
         "ordinary case, not a highlight reel.</p>"]

    h = P.headline()
    o.append("<section class='stats'>")
    o.append(stat("Win rate", "%.0f%%" % (h["win_rate"] * 100), "it loses more often than it wins"))
    o.append(stat("Payoff", "%.2f" % h["payoff"], "avg win / avg loss"))
    o.append(stat("Trades", "%d" % h["trades"], "~243/yr, 96% of sessions"))
    o.append(stat("Median range", "%.0f pts" % h["median_or_pts"], "the 09:30-09:45 box"))
    o.append("</section>")

    o.append("""<h2>The rules</h2><ol class='rules'>
<li><b>09:30-09:45</b> — mark the high and low of the first three 5-minute bars.
    That box is the opening range.</li>
<li><b>Wait for a bar to CLOSE outside it.</b> Above the high means long, below
    the low means short. Whichever happens first is the trade; there is no
    directional opinion.</li>
<li><b>Fill on the NEXT bar's open.</b> You cannot trade the close that generated
    your signal — that is the single most common way a backtest lies.</li>
<li><b>Stop at the opposite edge of the range.</b> Long from a high break stops
    at the range low. That distance is 1R.</li>
<li><b>Target 2R</b>, as a resting limit.</li>
<li><b>Flat at 16:00</b> if neither level is reached. One attempt per day, no
    re-entry. No new entries after 14:30.</li>
</ol>""")

    for grp in ("long", "short", "chop"):
        head, blurb = P.GROUPS[grp]
        o.append("<h2>%s</h2><p class='lede'>%s</p>" % (head, blurb))
        for bars, t in P.sessions(grp):
            side = "LONG" if t["side"] > 0 else "SHORT"
            o.append(candle_chart(
                bars, t,
                "%s — %s, exit at %s" % (t["date_str"], side, t["why"]),
                "%s &nbsp;·&nbsp; range %.0f pts &nbsp;·&nbsp; 1R = %.0f pts = "
                "$%.0f on %d contract%s &nbsp;·&nbsp; crossed the range "
                "<b>%d×</b> &nbsp;·&nbsp; result <b>$%+.0f</b>"
                % (t["caption"], t["or_width"], t["risk_pts"], t["risk_$"],
                   t["contracts"], "" if t["contracts"] == 1 else "s",
                   t["cross"], t["net_$"])))

    o.append("<h2>What chop actually costs — and why you can't dodge it</h2>")
    ct = P.chop_table()
    o.append(bar_chart(list(ct.index.astype(str)), list(ct["avg $"]),
                       "Average P&L per trade, by how many times the session "
                       "crossed its own opening range",
                       "Blue positive, red negative. A 'crossing' is the close "
                       "flipping from inside the range to outside, or back.",
                       fmt="money"))
    o.append(table(ct, {"% of days": "%.0f%%", "win %": "%.0f%%",
                        "hit 2R %": "%.0f%%", "stopped %": "%.0f%%",
                        "avg $": "${:,.0f}", "total $": "${:,.0f}"},
                   "Performance by session character"))
    o.append("<p class='lede'>On the calmest 21% of days — price breaks out and "
             "never comes back — it wins <b>93%</b> of the time and hits 2R on 41%. "
             "On the choppiest 25% it wins <b>12%</b> of the time and is stopped on "
             "73%. Those chop days cost <b>−$90,966</b> against a total profit of "
             "$47,920. The strategy is not 'a breakout edge'; it is one clean-trend "
             "edge big enough to survive a chop tax.</p>")

    tab, corr = P.chop_predictability()
    o.append(table(tab, {"median crossings": "%.0f", "win %": "%.0f%%",
                         "avg $": "${:,.0f}", "total $": "${:,.0f}"},
                   "Can the opening range width predict the chop? (quartiles of "
                   "range width as %% of price)"))
    o.append("<p class='lede'>No. Correlation between the range width you can see "
             "at 09:45 and the number of crossings that follow is <b>%.3f</b> — "
             "nothing. All four width quartiles are profitable and nearly "
             "identical. <b>The crossing count is only knowable after the close</b>, "
             "so the chop table above explains the P&amp;L; it is not a filter you "
             "can trade. Anyone selling you a 'skip the choppy days' rule is "
             "selling hindsight.</p>" % corr)

    o.append("<h2>Why it makes money losing 54% of the time</h2>")
    o.append(grouped_bars(P.exit_mix(),
                          "Share of trades vs share of gross profit, by exit",
                          "Both bars are percentages of their own total, so they "
                          "share one axis. Stops produce 43% of all trades and 0% "
                          "of the profit; the 2R target fires on 15% of trades and "
                          "pays over half the profit."))
    o.append("<p class='lede'>That is the whole engine. You pay a stream of small "
             "stop-outs to still be holding on the ~1 day in 7 that breaks out and "
             "runs. Take away the 2R exits and the strategy is a loser — which is "
             "also why 20 of 1,656 sessions carry 66% of the P&amp;L, and why the "
             "skew is +0.84. It is a convexity trade wearing a day-trading "
             "costume.</p>")

    o.append("<h2>Sizing — and the problem with it now</h2>")
    o.append("<p class='lede'>Contracts are never chosen by feel: "
             "<code>lots = round(capital × 12% ÷ (σ_ann × price × $2))</code>, "
             "with σ from the prior settlement. But MNQ has tripled since 2020 "
             "while the account has not.</p>")
    st = P.sizing_table()
    o.append(bar_chart(list(st.index.astype(str)), list(st.pct_one_lot),
                       "Share of trades that round to exactly ONE contract",
                       "At $100k. Once this is high the vol-scaling has stopped "
                       "working and you are running a fixed-size system.",
                       fmt="pct0", diverging=False))
    o.append(table(st, {"MNQ_price": "{:,.0f}", "ann_vol": "%.2f",
                        "exact_lots": "%.2f", "traded_lots": "%.0f",
                        "pct_one_lot": "%.0f%%", "min_cap_4_lots": "{:,.0f}"},
                   "Sizing by year, $100k account"))
    o.append("<p class='lede'>Carver's floor is 4 contracts (rounding error ≤ "
             "12.5%). On MNQ today that needs <b>$338k</b>. Below it you are "
             "accepting the risk error the whole framework exists to remove — and "
             "the fix is capital, never a higher risk target.</p>")
    return "".join(o)


ROUTES = {"/": page_overview, "/orb": page_orb, "/overnight": page_overnight,
          "/book": page_book, "/howto": page_howto, "/raw": page_raw}


# ------------------------------------------------------------------ shell -----
CSS = """
:root{color-scheme:light;--surface-0:#f6f5f2;--surface-1:#fcfcfb;--border:#e2e0d9;
--text-primary:#0b0b0b;--text-secondary:#52514e;--text-muted:#7a7873;
--series-1:#2a78d6;--series-2:#eb6834;--series-3:#1baf7a;--series-4:#eda100;
--series-5:#e87ba4;--series-6:#008300;--series-7:#4a3aa7;--series-8:#e34948;
--pos:#2a78d6;--neg:#e34948;--grid:#e8e6df;}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){color-scheme:dark;
--surface-0:#121211;--surface-1:#1a1a19;--border:#33332f;
--text-primary:#fff;--text-secondary:#c3c2b7;--text-muted:#8d8c83;
--series-1:#3987e5;--series-2:#d95926;--series-3:#199e70;--series-4:#c98500;
--series-5:#d55181;--series-6:#008300;--series-7:#9085e9;--series-8:#e66767;
--pos:#3987e5;--neg:#e66767;--grid:#2a2a27;}}
:root[data-theme=dark]{color-scheme:dark;--surface-0:#121211;--surface-1:#1a1a19;
--border:#33332f;--text-primary:#fff;--text-secondary:#c3c2b7;--text-muted:#8d8c83;
--series-1:#3987e5;--series-2:#d95926;--series-3:#199e70;--series-4:#c98500;
--series-5:#d55181;--series-6:#008300;--series-7:#9085e9;--series-8:#e66767;
--pos:#3987e5;--neg:#e66767;--grid:#2a2a27;}
*{box-sizing:border-box}
body{margin:0;background:var(--surface-0);color:var(--text-primary);
font:15px/1.55 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;}
header{position:sticky;top:0;z-index:5;background:var(--surface-0);
border-bottom:1px solid var(--border);padding:14px 28px;display:flex;
gap:22px;align-items:baseline;flex-wrap:wrap}
header b{font-size:15px;letter-spacing:-.01em}
nav{display:flex;gap:16px;flex-wrap:wrap}
nav a{color:var(--text-secondary);text-decoration:none;font-size:14px;
padding-bottom:2px;border-bottom:2px solid transparent}
nav a:hover{color:var(--text-primary)}
nav a.on{color:var(--text-primary);border-bottom-color:var(--series-1)}
main{max-width:980px;margin:0 auto;padding:26px 28px 80px}
h2{font-size:19px;margin:38px 0 6px;letter-spacing:-.01em}
h3{font-size:15px;margin:0;letter-spacing:-.01em}
.lede{color:var(--text-secondary);max-width:70ch;margin:4px 0 22px}
.stats{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:22px}
.stat{background:var(--surface-1);border:1px solid var(--border);border-radius:10px;
padding:12px 16px;min-width:150px;display:flex;flex-direction:column;gap:2px}
.stat .k{font-size:12px;color:var(--text-muted);text-transform:uppercase;
letter-spacing:.05em}
.stat .v{font-size:25px;font-variant-numeric:tabular-nums;letter-spacing:-.02em}
.stat .n{font-size:12px;color:var(--text-secondary)}
.fig{margin:0 0 26px;background:var(--surface-1);border:1px solid var(--border);
border-radius:12px;padding:16px 18px 10px}
figcaption{margin-bottom:10px}
.sub{margin:3px 0 0;color:var(--text-secondary);font-size:13px;max-width:74ch}
.plot{position:relative}
.chart{width:100%;height:auto;display:block;overflow:visible}
.grid{stroke:var(--grid);stroke-width:1}
.grid.zero{stroke:var(--text-muted);stroke-width:1}
.tick{fill:var(--text-muted);font-size:11px;font-variant-numeric:tabular-nums}
.ln{fill:none;stroke-width:2;stroke-linejoin:round;stroke-linecap:round}
.endlab{font-size:11.5px;font-weight:600}
.rowlab{fill:var(--text-secondary);font-size:11.5px;
font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
.rowval{fill:var(--text-secondary);font-size:11.5px;font-variant-numeric:tabular-nums}
.bar{stroke:var(--surface-1);stroke-width:2}
.bar:hover{opacity:.82}
.cross{stroke:var(--text-muted);stroke-width:1;stroke-dasharray:3 3}
.tip{position:absolute;pointer-events:none;background:var(--surface-1);
border:1px solid var(--border);border-radius:8px;padding:8px 10px;font-size:12.5px;
box-shadow:0 6px 22px rgba(0,0,0,.16);min-width:130px;z-index:3}
.tip .d{color:var(--text-muted);margin-bottom:4px}
.tip .r{display:flex;justify-content:space-between;gap:14px}
.tip .r i{width:8px;height:8px;border-radius:2px;display:inline-block;margin-right:6px}
.tip b{font-variant-numeric:tabular-nums;font-weight:600}
.tw{overflow-x:auto;margin:0 0 26px;border:1px solid var(--border);
border-radius:12px;background:var(--surface-1)}
table{border-collapse:collapse;width:100%;font-size:12.5px}
caption{text-align:left;padding:13px 14px 9px;font-weight:600;font-size:13px}
th,td{padding:6px 12px;text-align:right;white-space:nowrap;
border-top:1px solid var(--border);font-variant-numeric:tabular-nums}
thead th{color:var(--text-muted);font-weight:500;text-align:right;
position:sticky;top:0;background:var(--surface-1)}
tbody th{text-align:left;font-weight:500;color:var(--text-secondary);
font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
td.neg{color:var(--neg)}
details{margin-bottom:10px;background:var(--surface-1);border:1px solid var(--border);
border-radius:10px;padding:10px 14px}
summary{cursor:pointer;font-weight:600;font-size:13.5px}
pre{overflow-x:auto;font-size:11.5px;line-height:1.45;color:var(--text-secondary)}
.empty{color:var(--text-muted);font-style:italic}
.wick{stroke:var(--text-muted);stroke-width:1;opacity:.75}
.cd{stroke:var(--text-muted);stroke-width:1.2;opacity:.85}
.cd.up{fill:var(--surface-1)}
.cd.dn{fill:var(--text-muted)}
.orbox{fill:var(--series-1);opacity:.10;stroke:var(--series-1);
stroke-width:1;stroke-dasharray:3 3}
.orline{stroke:var(--text-muted);stroke-width:1;stroke-dasharray:1 4;opacity:.85}
.orlab{fill:var(--text-secondary);font-size:10.5px}
.sigbar{fill:var(--text-muted);opacity:.14}
.lvl{stroke-width:2;fill:none}
.lvl.entry{stroke:var(--series-1)}
.lvl.stop{stroke:var(--neg);stroke-dasharray:7 4}
.lvl.target{stroke:var(--series-3);stroke-dasharray:2 3}
.lvllab{font-size:10.5px;font-weight:700;letter-spacing:.02em}
.lvllab.entry{fill:var(--series-1)}
.lvllab.stop{fill:var(--neg)}
.lvllab.target{fill:var(--series-3)}
.mk{stroke:var(--surface-1);stroke-width:2}
.mk.entry{fill:var(--series-1)}
.mk.exitmk{fill:var(--surface-1);stroke:var(--text-primary)}
.note{fill:var(--text-secondary);font-size:10px}
.rules{max-width:74ch;color:var(--text-secondary);line-height:1.7;
padding-left:20px;margin:0 0 26px}
.rules b{color:var(--text-primary)}
code{background:var(--surface-1);border:1px solid var(--border);border-radius:4px;
padding:1px 5px;font-size:12.5px}
.tog{margin-left:auto;background:var(--surface-1);color:var(--text-secondary);
border:1px solid var(--border);border-radius:7px;padding:5px 11px;cursor:pointer;
font-size:12.5px}
"""

JS = """
document.querySelector('.tog').onclick=()=>{
  const r=document.documentElement, d=r.getAttribute('data-theme')==='dark';
  r.setAttribute('data-theme', d?'light':'dark');
};
document.querySelectorAll('.fig[data-chart]').forEach(fig=>{
  const cfg=JSON.parse(fig.dataset.chart), svg=fig.querySelector('svg'),
        tip=fig.querySelector('.tip'), cross=svg.querySelector('.cross'),
        hit=svg.querySelector('.hit');
  if(!hit) return;
  const show=e=>{
    const b=svg.getBoundingClientRect(), vb=svg.viewBox.baseVal,
          ux=(e.clientX-b.left)/b.width*vb.width;
    let i=Math.round((ux-cfg.ml)/cfg.pw*(cfg.n-1));
    i=Math.max(0,Math.min(cfg.n-1,i));
    const x=cfg.ml+cfg.pw*(i/Math.max(cfg.n-1,1));
    cross.setAttribute('x1',x); cross.setAttribute('x2',x);
    cross.style.display='';
    let h='<div class="d">'+cfg.dates[i]+'</div>';
    cfg.cols.forEach((c,j)=>{const v=cfg.vals[j][i];
      h+='<div class="r"><span><i style="background:'+cfg.colors[j]+'"></i>'+c+
         '</span><b>'+(v==null?'n/a':v.toFixed(2)+'x')+'</b></div>';});
    tip.innerHTML=h; tip.hidden=false;
    const px=x/vb.width*b.width;
    tip.style.left=Math.min(Math.max(px+14,0),b.width-tip.offsetWidth-4)+'px';
    tip.style.top='8px';
  };
  hit.addEventListener('mousemove',show);
  hit.addEventListener('mouseleave',()=>{tip.hidden=true;cross.style.display='none';});
});
document.querySelectorAll('.bar').forEach(b=>{
  const fig=b.closest('.fig'), tip=fig.querySelector('.tip');
  b.addEventListener('mousemove',e=>{
    const r=fig.querySelector('.plot').getBoundingClientRect();
    tip.innerHTML='<div class="d">'+b.dataset.lab+'</div><div class="r"><span>net Sharpe</span><b>'+b.dataset.val+'</b></div>';
    tip.hidden=false;
    tip.style.left=Math.min(e.clientX-r.left+14,r.width-tip.offsetWidth-4)+'px';
    tip.style.top=(e.clientY-r.top+12)+'px';
  });
  b.addEventListener('mouseleave',()=>{tip.hidden=true;});
});
"""


def shell(path, body):
    nav = "".join('<a href="%s"%s>%s</a>' % (p, " class='on'" if p == path else "", n)
                  for p, n in PAGES)
    return ("<!doctype html><html lang='en'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<title>Carver backtests</title><style>%s</style></head><body>"
            "<header><b>Carver backtests</b><nav>%s</nav>"
            "<button class='tog'>theme</button></header>"
            "<main>%s</main><script>%s</script></body></html>"
            % (CSS, nav, body, JS))


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urlparse(self.path).path.rstrip("/") or "/"
        fn = ROUTES.get(path)
        if fn is None:
            self.send_error(404, "no such page")
            return
        try:
            body = fn()
        except Exception as exc:                      # a broken CSV must not 500
            body = ("<p class='lede'>This page failed to render: <code>%s</code>."
                    " Re-run the backtest that produces its CSVs.</p>"
                    % html.escape(repr(exc)))
        out = shell(path, body).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(out)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a):
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--no-open", action="store_true")
    args = ap.parse_args()
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    url = "http://%s:%d/" % (args.host, args.port)
    print("Carver backtest dashboard -> %s" % url)
    print("reports dir: %s" % REPORTS)
    print("Ctrl-C to stop. CSVs are re-read per request, so refresh after a re-run.")
    if not args.no_open:
        threading.Timer(0.6, webbrowser.open, args=(url,)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    main()
