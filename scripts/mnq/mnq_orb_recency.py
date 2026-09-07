"""MNQ ORB performance over trailing windows: 3 months, 6 months, 1 year, all.

Recency tables are the most misread output in trading. The whole point of this
script is to print the error bars NEXT TO the numbers, because a 3-month Sharpe
carries a standard error of roughly +/-2.0 -- wider than any result it could
possibly show. Over three months a true Sharpe of 1.0 produces observed values
anywhere from about -1 to +3 with ordinary luck.

So: read the COUNTS and the STRUCTURE (win rate, exit mix, payoff), which
stabilise quickly. Do not read the Sharpe or the annualised return on any window
under about two years, and do not compare windows to each other as if the
difference meant something. The bottom of the output prints exactly how big a
difference would have to be before it did.

    .venv\\Scripts\\python.exe mnq_orb_recency.py
"""
from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

from overnight_drift_carver_backtest import ANNUALISE, REPORTS, TAU
import orb_playbook as P

WINDOWS = [("3 months", 91), ("6 months", 182), ("1 year", 365), ("all", None)]


def slice_stats(tr, sess_idx, capital, label):
    n = len(tr)
    if n == 0:
        return None
    net = tr["net_$"]
    w = net > 0
    r = (net.groupby(tr.date).sum() / capital).reindex(sess_idx).fillna(0.0)
    yrs = len(sess_idx) / 252.0
    sd = r.std() * ANNUALISE
    sr = (r.mean() * 252) / sd if sd else np.nan
    eq = (1 + r).cumprod()
    se = np.sqrt((1 + (sr ** 2) / 2) / yrs) if yrs > 0 and np.isfinite(sr) else np.nan
    return {
        "window": label,
        "from": str(tr.date.min().date()),
        "to": str(tr.date.max().date()),
        "sessions": len(sess_idx),
        "trades": n,
        "win %": w.mean() * 100,
        "hit 2R %": (tr.why == "target").mean() * 100,
        "stopped %": (tr.why == "stop").mean() * 100,
        "flat-at-close %": (tr.why == "close").mean() * 100,
        "long %": (tr.side > 0).mean() * 100,
        "avg R": tr.R_mult.mean(),
        "payoff": -net[w].mean() / net[~w].mean() if (~w).any() and w.any() else np.nan,
        "avg $": net.mean(),
        "total $": net.sum(),
        "ann vol %": sd * 100,
        "maxDD %": (eq / eq.cummax() - 1).min() * 100,
        "SR": sr,
        "SE(SR)": se,
        "SR 95% lo": sr - 1.96 * se if np.isfinite(se) else np.nan,
        "SR 95% hi": sr + 1.96 * se if np.isfinite(se) else np.nan,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--capital", type=float, default=100_000)
    ap.add_argument("--asof", default=None, help="YYYY-MM-DD; default = last bar")
    args = ap.parse_args()
    pd.set_option("display.width", 220)

    d, tr, dpp, tick, side_cost = P._load()
    tr = tr.copy()
    tr["R_pts"] = (tr.entry - tr.stop).abs()
    tr["R_mult"] = tr.pts / tr.R_pts
    rth = d.between_time("09:30", "15:55")
    sessions = rth.groupby(rth.index.normalize()).size().index
    asof = pd.Timestamp(args.asof).tz_localize(sessions.tz) if args.asof \
        else sessions.max()

    print("=" * 108)
    print("MNQ ORB  --  TRAILING WINDOWS   (OR15 | stop+2R | both | tau=%.0f%%)"
          % (TAU * 100))
    print("as of %s" % asof.date())
    print("=" * 108)

    rows = []
    for label, days in WINDOWS:
        if days is None:
            sub, sidx = tr, sessions
        else:
            cut = asof - pd.Timedelta(days=days)
            sub = tr[tr.date > cut]
            sidx = sessions[sessions > cut]
        s = slice_stats(sub, sidx, args.capital, label)
        if s:
            rows.append(s)
    R = pd.DataFrame(rows).set_index("window")

    head = ["from", "to", "sessions", "trades", "win %", "avg R", "payoff",
            "avg $", "total $"]
    print("\n[1] HEADLINE")
    print(R[head].to_string(formatters={
        "sessions": "{:,.0f}".format, "trades": "{:,.0f}".format,
        "win %": "{:.1f}%".format, "avg R": "{:+.3f}".format,
        "payoff": "{:.2f}".format, "avg $": "${:,.0f}".format,
        "total $": "${:,.0f}".format}))

    print("\n[2] STRUCTURE  -- these stabilise fast and are worth reading")
    print(R[["trades", "win %", "hit 2R %", "stopped %", "flat-at-close %",
             "long %"]].to_string(formatters={
        "trades": "{:,.0f}".format, "win %": "{:.1f}%".format,
        "hit 2R %": "{:.1f}%".format, "stopped %": "{:.1f}%".format,
        "flat-at-close %": "{:.1f}%".format, "long %": "{:.1f}%".format}))

    print("\n[3] RISK AND SHARPE  -- read the interval, not the point estimate")
    print(R[["ann vol %", "maxDD %", "SR", "SE(SR)", "SR 95% lo",
             "SR 95% hi"]].to_string(formatters={
        "ann vol %": "{:.1f}%".format, "maxDD %": "{:.1f}%".format,
        "SR": "{:+.2f}".format, "SE(SR)": "{:.2f}".format,
        "SR 95% lo": "{:+.2f}".format, "SR 95% hi": "{:+.2f}".format}))

    print("\n[4] HOW MUCH WOULD A DIFFERENCE HAVE TO BE TO MEAN ANYTHING?")
    full = R.loc["all"]
    for label in R.index:
        if label == "all":
            continue
        row = R.loc[label]
        diff = row["SR"] - full["SR"]
        joint = np.sqrt(row["SE(SR)"] ** 2 + full["SE(SR)"] ** 2)
        print("    %-9s SR %+.2f vs all-sample %+.2f -> gap %+.2f, needs %s%.2f "
              "to be significant.  %s"
              % (label, row["SR"], full["SR"], diff, "+/-", 1.96 * joint,
                 "NOT distinguishable" if abs(diff) < 1.96 * joint
                 else "distinguishable"))
    print("\n    A 3-month window cannot tell you anything about a Sharpe near 1."
          "\n    Watch the win rate and exit mix in [2] instead -- those move on "
          "hundreds of\n    trades rather than on a handful of lucky sessions.")

    R.to_csv(REPORTS / "mnq_orb_recency.csv")
    print("\n[5] written -> reports/mnq_orb_recency.csv")


if __name__ == "__main__":
    main()
