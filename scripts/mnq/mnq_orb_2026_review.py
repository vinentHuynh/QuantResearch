"""2026 year-to-date review of the MNQ opening-range breakout.

The strategy is the one cell that survived the cross-instrument grid and its
stress panel: MNQ, 15-minute opening range off the 09:30 RTH open, stop at the
opposite range edge, 2R target, both directions, vol-scaled to tau=12%.

The point of this script is NOT to decide whether to keep trading it. Carver is
explicit that a year of results cannot do that: with a true Sharpe near 1.0, the
standard error over 0.6 years is roughly +/-1.6, so a losing stretch and a
winning stretch are both entirely ordinary. Changing a system on a year of P&L
is the single most common way retail traders destroy an edge they actually had.

What a year CAN tell you is whether the things that ARE estimable over months
have moved:

  * realised cost vs modelled cost
  * realised vol vs the risk target
  * the mechanical shape of the trade -- opening-range width relative to price,
    the mix of stop / target / close exits, the payoff ratio

Those are structural. If they look like every prior year, a drawdown is noise.
If they have shifted, that is a reason to look harder -- still not a reason to
switch the system off mid-stream.

So: 2026 is scored against the 2020-2025 distribution, and the drawdown is
scored against the 2x-tau expectation that was set BEFORE trading, not against
zero.

    .venv\\Scripts\\python.exe mnq_orb_2026_review.py
    .venv\\Scripts\\python.exe mnq_orb_2026_review.py --year 2025
"""
from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

from overnight_drift_carver_backtest import (
    ANNUALISE, INSTRUMENTS, REPORTS, TAU, carver_vol, cost_per_side,
    daily_closes, load_5m,
)
from orb_carver_backtest import orb_trades, rth_liquid_start

CELL = dict(or_min=15, exit_style="or_stop_2r", filt="both")


def curve_stats(net, sessions, capital):
    r = (net.groupby(net.index).sum() / capital).reindex(sessions).fillna(0.0)
    eq = (1 + r).cumprod()
    sd = r.std() * ANNUALISE
    return {"net_$": net.sum(), "SR": (r.mean() * 252) / sd if sd else np.nan,
            "ann_vol": sd, "maxDD": (eq / eq.cummax() - 1).min(),
            "sessions": len(sessions)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=2026)
    ap.add_argument("--capital", type=float, default=100_000)
    ap.add_argument("--commission", type=float, default=1.24)
    ap.add_argument("--ticks", type=float, default=2.0)
    ap.add_argument("--end", default="2026-08-08", help="exclusive")
    args = ap.parse_args()
    pd.set_option("display.width", 200)

    fname, dpp, tick, _ = INSTRUMENTS["MNQ"]
    side_cost = cost_per_side(args.commission, args.ticks, tick, dpp)
    d = load_5m(fname, args.end)
    d = d[d.index >= rth_liquid_start(d)]
    closes = daily_closes(d)
    vol = carver_vol(closes)
    mac = np.sign(closes.rolling(16).mean() - closes.rolling(64).mean()).shift(1)
    tr = orb_trades(d, vol, mac, dpp, CELL["or_min"], CELL["exit_style"],
                    CELL["filt"], args.capital, side_cost)
    tr = tr.set_index("date")
    sessions = closes.loc[vol.dropna().index[0]:].index

    yr = args.year
    cur = tr[tr.index.year == yr]
    prior = tr[tr.index.year < yr]
    s_cur = sessions[sessions.year == yr]
    s_prior = sessions[sessions.year < yr]

    print("=" * 92)
    print("MNQ ORB %d REVIEW  --  OR%d / %s / %s, tau=%.0f%%, $%s"
          % (yr, CELL["or_min"], CELL["exit_style"], CELL["filt"], TAU * 100,
             format(args.capital, ",.0f")))
    print("=" * 92)
    print("data through %s (exclusive end %s)" % (d.index[-1].date(), args.end))

    # -- 1. headline --------------------------------------------------------
    a = curve_stats(cur["net_$"], s_cur, args.capital)
    b = curve_stats(prior["net_$"], s_prior, args.capital)
    print("\n[1] %d YTD vs 2020-%d" % (yr, yr - 1))
    print("    %-14s %12s %12s" % ("", "%d YTD" % yr, "2020-%d" % (yr - 1)))
    for k, f in (("net_$", "${:,.0f}"), ("SR", "{:+.2f}"), ("ann_vol", "{:.1%}"),
                 ("maxDD", "{:.1%}"), ("sessions", "{:,.0f}")):
        print("    %-14s %12s %12s" % (k, f.format(a[k]), f.format(b[k])))

    # -- 2. month by month --------------------------------------------------
    print("\n[2] %d MONTH BY MONTH" % yr)
    m = cur.groupby(cur.index.month).agg(
        trades=("net_$", "size"), net=("net_$", "sum"),
        win_rate=("net_$", lambda s: (s > 0).mean()))
    m["cum"] = m.net.cumsum()
    print(m.to_string(formatters={"net": "${:,.0f}".format,
                                  "cum": "${:,.0f}".format,
                                  "win_rate": "{:.1%}".format}))

    # -- 3. is the MACHINE the same? ---------------------------------------
    print("\n[3] STRUCTURE -- the estimable things, %d vs prior" % yr)

    def shape(t):
        mix = t.why.value_counts(normalize=True)
        w = t["net_$"] > 0
        return {"trades/yr": len(t) / (len(t.index.unique()) / 252.0)
                if len(t) else np.nan,
                "win_rate": w.mean(),
                "payoff": -t["net_$"][w].mean() / t["net_$"][~w].mean()
                if (~w).any() else np.nan,
                "OR width %px": (t.or_width / t.entry).median() * 100,
                "stop %": mix.get("stop", 0) * 100,
                "target %": mix.get("target", 0) * 100,
                "close %": mix.get("close", 0) * 100,
                "avg contracts": t.contracts.mean(),
                "% sized to 1 lot": 100 * (t.contracts == 1).mean(),
                # cost as a share of gross is meaningless when gross is negative
                # (it prints a large negative and reads like a cost blow-out that
                # never happened), so cost is reported per contract traded.
                "cost $/contract": t["cost_$"].sum() / t.contracts.sum()}

    S = pd.DataFrame({"%d" % yr: shape(cur), "2020-%d" % (yr - 1): shape(prior)})
    S["delta"] = S.iloc[:, 0] - S.iloc[:, 1]
    print(S.to_string(float_format=lambda v: "%8.2f" % v))

    # -- 4. is this drawdown unusual? --------------------------------------
    print("\n[4] IS %d UNUSUAL? -- %d-session windows drawn from 2020-%d"
          % (yr, len(s_cur), yr - 1))
    daily_prior = (prior["net_$"].groupby(prior.index).sum()
                   .reindex(s_prior).fillna(0.0))
    k = len(s_cur)
    if len(daily_prior) > k:
        windows = np.array([daily_prior.values[i:i + k].sum()
                            for i in range(len(daily_prior) - k)])
        obs = a["net_$"]
        pct = 100.0 * (windows < obs).mean()
        print("    %d YTD net           ${:,.0f}".replace("{:,.0f}", "%s")
              % (yr, format(obs, ",.0f")))
        print("    prior %d-session windows: worst $%s, 5th $%s, median $%s, "
              "95th $%s, best $%s"
              % (k, format(windows.min(), ",.0f"),
                 format(np.percentile(windows, 5), ",.0f"),
                 format(np.median(windows), ",.0f"),
                 format(np.percentile(windows, 95), ",.0f"),
                 format(windows.max(), ",.0f")))
        print("    -> %d sits at the %.0fth percentile of history. %s"
              % (yr, pct,
                 "Inside the normal range." if pct > 5 else
                 "Below the 5th percentile -- worth a hard look, still not proof."))
        print("    %.0f%% of prior windows this long were also negative."
              % (100.0 * (windows < 0).mean()))

    # -- 5. the expectation set in advance ---------------------------------
    print("\n[5] AGAINST THE EXPECTATION SET BEFORE TRADING")
    print("    Planned: a %.0f%% drawdown is ORDINARY (2 x tau), %.0f%% planned for."
          % (2 * TAU * 100, 3 * TAU * 100))
    print("    %d worst drawdown so far: %.1f%%  ->  %s"
          % (yr, a["maxDD"] * 100,
             "well inside plan" if abs(a["maxDD"]) < 2 * TAU else "at the plan"))
    full = curve_stats(tr["net_$"], sessions, args.capital)
    yrs_c = len(s_cur) / 252.0
    se = np.sqrt((1 + full["SR"] ** 2 / 2) / yrs_c)
    print("    SE(SR) over %.1f years = %.2f. A one-year Sharpe carries a +/-%.1f "
          "band, so\n    %d's result is not evidence about the edge in either "
          "direction." % (yrs_c, se, 1.96 * se, yr))
    print("    Full sample including %d: SR %+.2f, net $%s, maxDD %.1f%%"
          % (yr, full["SR"], format(full["net_$"], ",.0f"), full["maxDD"] * 100))

    # -- 5b. the problem that is NOT a P&L problem -------------------------
    print("\n[5b] QUANTISATION -- the strategy is outgrowing the account")
    raw = args.capital * TAU / (tr.ann_vol * tr.entry * dpp)
    q = pd.DataFrame({"med_px": tr.entry, "raw_lots": raw,
                      "lots": tr.contracts,
                      "one_lot": (tr.contracts == 1).astype(float)})
    by = q.groupby(q.index.year).agg(med_px=("med_px", "median"),
                                     raw_lots=("raw_lots", "median"),
                                     lots=("lots", "median"),
                                     pct_1lot=("one_lot", "mean"))
    by["pct_1lot"] *= 100
    by["min_cap_4lot"] = tr.groupby(tr.index.year).apply(
        lambda t: 4 * (t.entry * dpp * t.ann_vol).median() / TAU)
    print(by.to_string(formatters={"med_px": "{:,.0f}".format,
                                   "raw_lots": "{:.2f}".format,
                                   "lots": "{:.0f}".format,
                                   "pct_1lot": "{:.0f}%".format,
                                   "min_cap_4lot": "${:,.0f}".format}))
    print("    MNQ has roughly tripled since 2020 while the account has not, so the"
          "\n    vol-scaling has quietly stopped working: at $%s a majority of %d's"
          "\n    trades round to exactly ONE lot, which is a fixed-size system "
          "wearing a\n    vol-target's clothes. Carver's floor is 4 lots (rounding "
          "error <= 12.5%%);\n    that now needs $%s. This is a capital problem, "
          "not a signal problem --\n    and unlike the P&L, it is worth acting on."
          % (format(args.capital, ",.0f"), yr,
             format(by.min_cap_4lot.iloc[-1], ",.0f")))

    # -- 6. artefacts -------------------------------------------------------
    out = cur.reset_index()[["date", "side", "entry", "exit", "why", "or_width",
                             "contracts", "gross_$", "cost_$", "net_$"]]
    out.to_csv(REPORTS / ("mnq_orb_%d_trades.csv" % yr), index=False)
    m.to_csv(REPORTS / ("mnq_orb_%d_monthly.csv" % yr))
    print("\n[6] written -> reports/mnq_orb_%d_trades.csv, mnq_orb_%d_monthly.csv"
          % (yr, yr))


if __name__ == "__main__":
    main()
