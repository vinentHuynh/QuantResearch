"""Full statistical profile of the MNQ opening-range breakout.

Descriptive statistics only -- this script does not search, fit, or select
anything. It profiles the ONE cell that survived the cross-instrument grid and
its stress panel: MNQ, 15-minute range off the 09:30 RTH open, stop at the
opposite range edge, 2R target, both directions, vol-scaled to tau = 12%.

Every table reports COUNT and PERCENT together, because either alone misleads:
a 71% win rate on 7 trades is noise, and a 1,600-trade sample with no rate
attached says nothing about whether it worked.

One caveat that applies to every breakdown below: these are IN-SAMPLE splits of
a single 6.6-year run. Day-of-week, month and year tables in particular will
show spread that is mostly sampling noise -- with ~320 trades per weekday the
standard error on a win rate near 46% is about 2.8 percentage points, so gaps
smaller than ~6 points are not differences. They are printed to characterise the
strategy, NOT to find a filter. Every filter this workspace has tried to build
from such a table has failed out of sample.

    .venv\\Scripts\\python.exe mnq_orb_stats_report.py
"""
from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

from overnight_drift_carver_backtest import ANNUALISE, REPORTS, TAU
import orb_playbook as P

DOW = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]


def pct_table(g, total, extra=None):
    """Count + percent + performance for a grouping. The house format."""
    out = pd.DataFrame({
        "trades": g.size(),
        "% of trades": g.size() / total * 100,
        "win %": g["net_$"].apply(lambda s: (s > 0).mean() * 100),
        "avg R": g["R_mult"].mean(),
        "avg $": g["net_$"].mean(),
        "total $": g["net_$"].sum(),
        "% of profit": g["net_$"].sum() / g["net_$"].sum().abs().sum() * 100,
    })
    if extra is not None:
        for k, v in extra.items():
            out[k] = v
    return out


def fmt(df):
    f = {}
    for c in df.columns:
        if c in ("trades",):
            f[c] = "{:,.0f}".format
        elif "%" in c:
            f[c] = "{:.1f}%".format
        elif c.startswith("avg R") or c == "avg R":
            f[c] = "{:+.2f}".format
        elif "$" in c:
            f[c] = "${:,.0f}".format
        else:
            f[c] = "{:.2f}".format
    return df.to_string(formatters=f)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--capital", type=float, default=100_000)
    args = ap.parse_args()
    pd.set_option("display.width", 200)

    d, tr, dpp, tick, side_cost = P._load()
    tr = tr.copy()
    tr["R_pts"] = (tr.entry - tr.stop).abs()
    tr["R_mult"] = tr.pts / tr.R_pts               # realised R, signed
    tr["R_$"] = tr.R_pts * dpp * tr.contracts
    tr["dow"] = tr.date.dt.dayofweek
    tr["year"] = tr.date.dt.year
    tr["month"] = tr.date.dt.month
    tr["cross"] = tr.date.dt.normalize().map(P._crossings())
    n = len(tr)

    rth = d.between_time("09:30", "15:55")
    all_sess = rth.groupby(rth.index.normalize()).size().index
    n_sess = len(all_sess)
    yrs = n_sess / 252.0
    net = tr["net_$"]
    wins = net > 0

    print("=" * 92)
    print("MNQ OPENING-RANGE BREAKOUT  --  STATISTICAL PROFILE")
    print("OR15 | stop at opposite edge | 2R target | both directions | tau=%.0f%%"
          % (TAU * 100))
    print("=" * 92)

    # ------------------------------------------------------------- coverage --
    print("\n[1] COVERAGE")
    print("    %s -> %s    %.1f years" % (all_sess[0].date(), all_sess[-1].date(), yrs))
    print("    %-34s %6d" % ("RTH sessions in sample", n_sess))
    print("    %-34s %6d   %5.1f%%" % ("sessions that produced a trade", n,
                                       100 * n / n_sess))
    print("    %-34s %6d   %5.1f%%" % ("sessions with no breakout / no lot",
                                       n_sess - n, 100 * (n_sess - n) / n_sess))
    print("    %-34s %6.0f" % ("trades per year", n / yrs))

    # -------------------------------------------------------- profitability --
    print("\n[2] PROFITABILITY")
    print("    %-34s %6d   %5.1f%%   <- of days traded"
          % ("profitable days", int(wins.sum()), 100 * wins.mean()))
    print("    %-34s %6d   %5.1f%%"
          % ("losing days", int((~wins).sum()), 100 * (~wins).mean()))
    print("    %-34s %6d   %5.1f%%   <- of ALL sessions in the sample"
          % ("profitable days", int(wins.sum()), 100 * wins.sum() / n_sess))
    print("    %-34s  $%s" % ("total net", format(net.sum(), ",.0f")))
    print("    %-34s  $%s / $%s" % ("avg win / avg loss",
                                    format(net[wins].mean(), ",.0f"),
                                    format(net[~wins].mean(), ",.0f")))
    print("    %-34s  %.2f" % ("payoff ratio",
                               -net[wins].mean() / net[~wins].mean()))
    print("    %-34s  %+.3f R" % ("expectancy per trade", tr.R_mult.mean()))
    print("    %-34s  $%s" % ("expectancy per trade", format(net.mean(), ",.2f")))
    eq = (1 + (net.groupby(tr.date).sum() / args.capital)).cumprod()
    print("    %-34s  %.1f%%" % ("max drawdown",
                                 (eq / eq.cummax() - 1).min() * 100))

    # ------------------------------------------------------ R distribution ---
    print("\n[3] RETURN DISTRIBUTION IN R  (R = entry-to-stop distance)")
    bins = [-np.inf, -1.0, -0.75, -0.5, -0.25, 0, 0.25, 0.5, 1.0, 1.5, 2.0, np.inf]
    labs = ["<= -1R (full stop)", "-1.0 to -0.75", "-0.75 to -0.5",
            "-0.5 to -0.25", "-0.25 to 0", "0 to +0.25", "+0.25 to +0.5",
            "+0.5 to +1R", "+1R to +1.5", "+1.5 to +2R", ">= +2R (target)"]
    b = pd.cut(tr.R_mult, bins, labels=labs, right=False)
    dist = pd.DataFrame({
        "trades": tr.groupby(b, observed=False).size(),
        "% of trades": tr.groupby(b, observed=False).size() / n * 100,
        "total $": tr.groupby(b, observed=False)["net_$"].sum()})
    dist["cum %"] = dist["% of trades"].cumsum()
    print(dist.to_string(formatters={
        "trades": "{:,.0f}".format, "% of trades": "{:.1f}%".format,
        "cum %": "{:.1f}%".format, "total $": "${:,.0f}".format}))

    print("\n    threshold summary")
    for thr, lab in [(-1.0, "reached the full -1R stop"), (0.0, "any profit"),
                     (0.5, "beat +0.5R"), (1.0, "beat +1R"),
                     (1.5, "beat +1.5R"), (1.99, "reached the +2R target")]:
        if thr < 0:
            m = tr.R_mult <= thr + 1e-9
        else:
            m = tr.R_mult >= thr
        print("      %-28s %6d   %5.1f%%" % (lab, int(m.sum()), 100 * m.mean()))

    # ----------------------------------------------------------- exit types --
    print("\n[4] HOW TRADES END")
    g = tr.groupby("why")
    ex = pct_table(g, n)
    ex["% of gross profit"] = g["net_$"].apply(lambda s: s[s > 0].sum()) / \
        net[wins].sum() * 100
    print(fmt(ex.drop(columns=["% of profit"])))

    # -------------------------------------------------------- long vs short --
    print("\n[5] LONG vs SHORT")
    tr["dir"] = np.where(tr.side > 0, "long", "short")
    ls = pct_table(tr.groupby("dir"), n)
    ls["hit 2R %"] = tr.groupby("dir")["why"].apply(
        lambda s: (s == "target").mean() * 100)
    ls["stopped %"] = tr.groupby("dir")["why"].apply(
        lambda s: (s == "stop").mean() * 100)
    print(fmt(ls))

    # -------------------------------------------------------- day of week ----
    print("\n[6] DAY OF WEEK")
    dw = pct_table(tr.groupby("dow"), n)
    dw.index = [DOW[i] for i in dw.index]
    dw["hit 2R %"] = list(tr.groupby("dow")["why"].apply(
        lambda s: (s == "target").mean() * 100))
    se = np.sqrt(0.4637 * (1 - 0.4637) / tr.groupby("dow").size()) * 100
    dw["win% std err"] = list(se)
    print(fmt(dw))
    print("    Spread across weekdays is %.1f pts of win rate against a ~%.1f pt "
          "standard error.\n    Treat as noise unless a gap exceeds roughly 3x "
          "that." % (dw["win %"].max() - dw["win %"].min(), se.mean()))

    # ------------------------------------------------------------- by year ---
    print("\n[7] BY YEAR")
    yr = pct_table(tr.groupby("year"), n)
    yr["hit 2R %"] = list(tr.groupby("year")["why"].apply(
        lambda s: (s == "target").mean() * 100))
    print(fmt(yr))

    # ------------------------------------------------------------ by month ---
    print("\n[8] BY CALENDAR MONTH")
    mo = pct_table(tr.groupby("month"), n)
    mo.index = [pd.Timestamp(2000, m, 1).strftime("%b") for m in mo.index]
    print(fmt(mo))

    # ------------------------------------------------------ session character --
    print("\n[9] BY SESSION CHARACTER  (times price crossed its own range)")
    tr["bucket"] = pd.cut(tr.cross, [-1, 2, 5, 9, 10_000],
                          labels=["calm 0-2", "normal 3-5", "busy 6-9", "chop 10+"])
    ch = pct_table(tr.groupby("bucket", observed=True), n)
    ch["hit 2R %"] = list(tr.groupby("bucket", observed=True)["why"].apply(
        lambda s: (s == "target").mean() * 100))
    print(fmt(ch))
    print("    Only knowable AFTER the close -- explanatory, not tradeable.")

    # ---------------------------------------------------------- entry hour ---
    print("\n[10] ENTRY TIME")
    tr["ehour"] = pd.to_datetime(tr.entry_ts).dt.strftime("%H:%M").str[:2] + ":00"
    eh = pct_table(tr.groupby("ehour"), n)
    print(fmt(eh))

    # ------------------------------------------------------------- streaks ---
    print("\n[11] STREAKS AND TAILS")
    sign = np.sign(net.values)
    runs, cur = [], 0
    for s in sign:
        if s > 0:
            cur = cur + 1 if cur > 0 else 1
        else:
            cur = cur - 1 if cur < 0 else -1
        runs.append(cur)
    runs = np.array(runs)
    print("    longest winning streak   %d trades" % runs.max())
    print("    longest losing streak    %d trades" % abs(runs.min()))
    daily = net.groupby(tr.date).sum().sort_values(ascending=False)
    for k in (1, 5, 10, 20, 50):
        print("    top %-3d sessions          $%-10s %5.1f%% of total profit"
              % (k, format(daily.iloc[:k].sum(), ",.0f"),
                 100 * daily.iloc[:k].sum() / daily.sum()))
    print("    best single session      $%s" % format(daily.iloc[0], ",.0f"))
    print("    worst single session     $%s" % format(daily.iloc[-1], ",.0f"))
    print("    skew of daily returns    %+.2f" % net.groupby(tr.date).sum().skew())

    # --------------------------------------------------------------- files ---
    tr.to_csv(REPORTS / "mnq_orb_all_trades.csv", index=False)
    dist.to_csv(REPORTS / "mnq_orb_R_distribution.csv")
    dw.to_csv(REPORTS / "mnq_orb_dayofweek.csv")
    yr.to_csv(REPORTS / "mnq_orb_byyear.csv")
    print("\n[12] written -> reports/mnq_orb_all_trades.csv, "
          "mnq_orb_R_distribution.csv,\n     mnq_orb_dayofweek.csv, "
          "mnq_orb_byyear.csv")


if __name__ == "__main__":
    main()
