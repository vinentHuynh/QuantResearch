"""Can the two Carver strategies live inside a LucidPro container?

A prop container asks a different question from Carver. Carver asks "how big,
given volatility"; a container asks "will you touch this floor". So this script
drops the vol targeting entirely and asks only the container's question: at a
FIXED contract count, does the equity path touch the trailing max-loss limit
before it reaches the evaluation target?

That is not a compromise, it is what the container forces. Below roughly $190k
the vol-implied size rounds to one lot or zero on every one of these contracts,
so a prop account runs a fixed-size system no matter what the sizing formula
says. Read every number here as describing THAT system, not the one that was
backtested.

Size is swept rather than fixed at one, because each plan's max size scales with
the account while the profit target scales faster than the loss buffer
(target/MLL is 1.25x on the 25K but 2.0x on the 100K and 150K). One lot is not
the fair test of a bigger plan.

MLL mechanics modelled (from lucid_container_scan.py / lucid_prop_year_sim.py,
which sourced them from the published LucidPro cards):
  * the limit trails the peak END-OF-DAY balance by the buffer
  * it stops trailing once it reaches the initial balance ("initial trail"),
    so the floor in P&L terms is min(peak - MLL, 0)
  * both strategies are flat at every EOD close, so intraday excursions cannot
    breach anything -- only realised EOD P&L can. That is the one structural
    reason these rules suit this container at all.

    .venv\\Scripts\\python.exe ninjatrader\\prop_fit_check.py
    .venv\\Scripts\\python.exe ninjatrader\\prop_fit_check.py --sizes 1,2,3
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from overnight_drift_carver_backtest import (            # noqa: E402
    INSTRUMENTS, block_trades, carver_vol, cost_per_side, daily_closes,
    liquid_start, load_5m,
)
from orb_carver_backtest import orb_trades, rth_liquid_start   # noqa: E402

# Published LucidPro eval rules: plan -> (profit target, max loss limit, max micros)
PLANS = {
    "25K":  (1250.0, 1000.0, 20),
    "50K":  (3000.0, 2000.0, 40),
    "100K": (6000.0, 3000.0, 60),
    "150K": (9000.0, 4500.0, 100),
}

RULES = (("orb", "ORB OR15/2R"), ("on", "Overnight 18-06"))


def per_contract_pnl(inst, rule, end):
    """Net $ per session for exactly ONE contract, after costs.

    `pts` is already per-contract, so the capital passed to the backtest only has
    to be large enough that no session is dropped on a zero-lot round; it never
    reaches the numbers returned here.
    """
    fname, dpp, tick, _ = INSTRUMENTS[inst]
    d = load_5m(fname, end)

    if rule == "orb":
        d = d[d.index >= rth_liquid_start(d)]
        side_cost = cost_per_side(1.24, 2.0, tick, dpp)      # breakouts cross
        closes = daily_closes(d)
        vol = carver_vol(closes)
        mac = np.sign(closes.rolling(16).mean() - closes.rolling(64).mean()).shift(1)
        tr = orb_trades(d, vol, mac, dpp, 15, "or_stop_2r", "both",
                        10_000_000, side_cost)
    else:
        d = d[d.index >= liquid_start(d)]
        side_cost = cost_per_side(1.24, 1.0, tick, dpp)      # clock-time market orders
        closes = daily_closes(d)
        vol = carver_vol(closes)
        tr = block_trades(d, vol, dpp, "18:00", "05:55", 10_000_000, side_cost)

    net = tr["pts"] * dpp - 2.0 * side_cost
    return pd.Series(net.values, index=tr["date"] if "date" in tr else tr.index)


def worst_trailing_dd(x):
    """Deepest peak-to-trough of the cumulative EOD balance, in dollars."""
    eq = np.cumsum(x)
    return float((eq - np.maximum.accumulate(np.maximum(eq, 0))).min())


def simulate(pnl, mll, target, sessions, sims, rng):
    """Bootstrap trader-years through the EOD-trailing floor.

    Returns the share reaching `target` first, breaching the floor first, or
    doing neither inside the horizon.
    """
    draws = rng.choice(pnl, size=(sims, sessions), replace=True)
    eq = np.zeros(sims)
    peak = np.zeros(sims)
    passed = np.zeros(sims, dtype=bool)
    blown = np.zeros(sims, dtype=bool)

    for t in range(sessions):
        live = ~(passed | blown)
        if not live.any():
            break
        eq[live] += draws[live, t]
        floor = np.minimum(peak - mll, 0.0)
        blown |= live & (eq <= floor)
        passed |= live & ~blown & (eq >= target)
        peak = np.maximum(peak, np.maximum(eq, 0.0))

    return passed.mean(), blown.mean(), 1 - passed.mean() - blown.mean()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", default="1,2,3,4,6,8",
                    help="contract counts to sweep. Plan caps sit far above these, "
                         "so the binding constraint is the MLL, not the cap.")
    ap.add_argument("--sessions", type=int, default=250)
    ap.add_argument("--sims", type=int, default=20000)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--end", default="2026-08-30")
    args = ap.parse_args()

    sizes = [int(x) for x in args.sizes.split(",")]
    rng = np.random.default_rng(args.seed)

    print("=" * 104)
    print("LUCIDPRO CONTAINER FIT  --  fixed contract count, no vol targeting")
    print("%d sessions per trial, %s trials. Size swept over %s."
          % (args.sessions, format(args.sims, ","), sizes))
    print("=" * 104)

    pnl = {}
    for rule, _ in RULES:
        for inst in ("MNQ", "MES"):
            pnl[(rule, inst)] = per_contract_pnl(inst, rule, args.end).dropna().values

    print("\nPER-CONTRACT CHARACTER (whole sample, 1 lot)")
    ch = pd.DataFrame([
        {"strategy": lb, "inst": i, "sessions": len(pnl[(r, i)]),
         "mean_$": pnl[(r, i)].mean(), "sd_$": pnl[(r, i)].std(),
         "worst_day": pnl[(r, i)].min(), "hist_maxDD": worst_trailing_dd(pnl[(r, i)])}
        for r, lb in RULES for i in ("MNQ", "MES")]).set_index(["strategy", "inst"])
    print(ch.to_string(formatters={
        "mean_$": "{:+,.2f}".format, "sd_$": "{:,.2f}".format,
        "worst_day": "{:+,.0f}".format, "hist_maxDD": "{:+,.0f}".format}))

    rows = []
    for plan, (tgt, mll, cap) in PLANS.items():
        for rule, label in RULES:
            for inst in ("MNQ", "MES"):
                v = pnl[(rule, inst)]
                best = None
                for n in sizes:
                    if n > cap:
                        continue
                    pas, blo, non = simulate(v * n, mll, tgt,
                                             args.sessions, args.sims, rng)
                    if best is None or pas > best[1]:
                        best = (n, pas, blo, non)
                rows.append({"plan": plan, "strategy": label, "inst": inst,
                             "MLL": mll, "target": tgt, "best_n": best[0],
                             "pass": best[1], "breach": best[2], "neither": best[3],
                             "histDD_at_n": worst_trailing_dd(v * best[0])})

    R = pd.DataFrame(rows).set_index(["plan", "strategy", "inst"])
    print("\nBEST CONTRACT COUNT PER PLAN (size chosen to maximise pass rate)")
    print(R.to_string(formatters={
        "MLL": "{:,.0f}".format, "target": "{:,.0f}".format,
        "pass": "{:.1%}".format, "breach": "{:.1%}".format,
        "neither": "{:.1%}".format, "histDD_at_n": "{:+,.0f}".format}))

    print("\n  histDD_at_n is the deepest peak-to-trough the ACTUAL equity curve ran")
    print("  at that contract count over 2020-2026. Where it is worse than MLL, the")
    print("  container would have terminated the account somewhere in real history --")
    print("  the bootstrap only says how often per year.")
    print("  'neither' is the eval expiring unreached: another fee for the same edge.")


if __name__ == "__main__":
    main()
