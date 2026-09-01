"""Test the container-inversion idea: in a prop account with capped downside,
does per-night velocity beat tail control?

`lucid_prop_year_sim.py` hinted the wider 18-06 window matches or beats 23-04
inside the Lucid 50K container, reversing the cash-account ranking. This runs the
idea to ground three ways, all on the 50K Pro rules (target +$3,000 / MLL $2,000
EOD-trailing locking at initial balance / payout $500, 40% consistency, 3-day
cycle, caps $2,000 first, $2,500 after, 90/10, $140 reset):

1. TRACK SCAN -- every clock block from mnq_time_block_backtest.py through the
   full year pipeline at equal contract counts. If the inversion is real, ranking
   by E[net] should follow mean $/night, not Sharpe.
2. EDGE vs OPTION DECOMPOSITION -- each track rerun with its mean removed. The
   zero-edge E[net] is pure container value (cheap resets against the firm's
   drawdown); it should scale with the track's VARIANCE, not its edge. Edge
   contribution = real minus zero-edge.
3. PHASE SIZING GRID -- different contract counts in eval vs funded. The
   container logic says risk is asymmetric across phases: in eval you hold an
   option (bust costs $140), once funded you hold a cushion worth real payouts.
   If that's right, big-eval/small-funded should beat symmetric sizing.

Same caveats as the parent sim: iid bootstrap (no clustered disasters), payout
caps assumed from the published policy, firms police reset-farming. This is a
study of the rule geometry, not a business plan.

    python lucid_container_scan.py
    python lucid_container_scan.py --sims 40000
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path(__file__).with_name("data")

# (entry hour, exit hour) -> first open of entry hour to last close of exit hour
TRACKS = {
    "Asia 18-00":    (18, 23),
    "London 00-06":  (0, 5),
    "NY am 06-12":   (6, 11),
    "NY pm 12-18":   (12, 16),
    "23:00-04:00":   (23, 3),
    "OVERNIGHT 18-06": (18, 5),
    "DAY 06-18":     (6, 16),
    "FULL 24h":      (18, 16),
}

# 50K Pro plan
EVAL_TGT, MLL, PAYOUT_TGT = 3000.0, 2000.0, 500.0
FIRST_COST, RESET_COST = 140.40, 140.00
FIRST_CAP, CYCLE_CAP, SPLIT = 2000.0, 2500.0, 0.90


def track_pnl(sym: str, a: int, b: int, dpp: float, tick: float = 0.25) -> np.ndarray:
    d = pd.read_parquet(DATA / f"{sym}_5min_databento.parquet").sort_index()
    d = d[d.index >= pd.Timestamp("2020-01-02").tz_localize(d.index.tz)]
    idx = d.index
    sess = (idx - pd.Timedelta(hours=18)).normalize()
    cell = d.groupby([sess, idx.hour]).agg(o=("open", "first"), c=("close", "last"),
                                           n=("open", "size"))
    cell = cell[cell["n"] >= 6]
    o, c = cell["o"].unstack(-1), cell["c"].unstack(-1)
    return ((c[b] - o[a]).dropna() * dpp - tick * dpp).values


def pipeline(pnl: np.ndarray, eval_ct: int, funded_ct: int, nights: int,
             sims: int, rng, retain: float = 0.0) -> dict:
    """One-year eval->funded->payout->reset loop with phase-dependent size."""
    draws = rng.choice(pnl, size=(sims, nights), replace=True)

    funded = np.zeros(sims, dtype=bool)
    eq = np.zeros(sims); peak = np.zeros(sims)
    cyc_base = np.zeros(sims); cyc_days = np.zeros(sims); cyc_maxday = np.zeros(sims)
    acct_payouts = np.zeros(sims)
    fees = np.full(sims, FIRST_COST); paid = np.zeros(sims)
    n_bust = np.zeros(sims); n_payouts = np.zeros(sims); funded_nights = np.zeros(sims)
    n_pass = np.zeros(sims)

    for t in range(nights):
        pl = draws[:, t] * np.where(funded, funded_ct, eval_ct)
        eq += pl
        peak = np.maximum(peak, np.maximum(eq, 0.0))
        floor = np.minimum(peak - MLL, 0.0)

        funded_nights += funded
        cyc_days += funded
        cyc_maxday = np.where(funded, np.maximum(cyc_maxday, np.maximum(pl, 0.0)),
                              cyc_maxday)

        dead = eq <= floor
        if dead.any():
            n_bust += dead
            fees += dead * RESET_COST
            for arr in (eq, peak, cyc_base, cyc_days, cyc_maxday, acct_payouts):
                arr[dead] = 0.0
            funded &= ~dead

        passed = (~funded) & (~dead) & (eq >= EVAL_TGT)
        if passed.any():
            n_pass += passed
            funded |= passed
            for arr in (eq, peak, cyc_base, cyc_days, cyc_maxday, acct_payouts):
                arr[passed] = 0.0

        cyc_profit = eq - cyc_base
        ok = (funded & ~dead & (eq - retain >= PAYOUT_TGT) & (cyc_days >= 3)
              & (cyc_maxday <= 0.40 * np.maximum(cyc_profit, 1e-9)))
        if ok.any():
            cap = np.where(acct_payouts == 0, FIRST_CAP, CYCLE_CAP)
            w = np.where(ok, np.minimum(eq - retain, cap), 0.0)
            paid += w * SPLIT
            n_payouts += ok
            acct_payouts += ok
            eq -= w
            cyc_base = np.where(ok, eq, cyc_base)
            cyc_days = np.where(ok, 0.0, cyc_days)
            cyc_maxday = np.where(ok, 0.0, cyc_maxday)

    net = paid - fees
    return {"net": net.mean(), "med": np.median(net), "p_pos": (net > 0).mean(),
            "paid": paid.mean(), "fees": fees.mean(), "busts": n_bust.mean(),
            "payouts": n_payouts.mean(), "funded_frac": funded_nights.mean() / nights,
            "passes": n_pass.mean(),
            "p5": np.percentile(net, 5), "p25": np.percentile(net, 25),
            "p75": np.percentile(net, 75), "p95": np.percentile(net, 95),
            "never_funded": (n_pass == 0).mean()}


def main() -> None:
    ap = argparse.ArgumentParser(description="Container-inversion scan on Lucid 50K.")
    ap.add_argument("--symbol", default="MNQ")
    ap.add_argument("--nights", type=int, default=250)
    ap.add_argument("--sims", type=int, default=20000)
    ap.add_argument("--size", type=int, default=10, help="micros for the track scan")
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    rng = np.random.default_rng(args.seed)
    dpp = 2.0 if args.symbol == "MNQ" else 5.0
    pnls = {k: track_pnl(args.symbol, a, b, dpp) for k, (a, b) in TRACKS.items()}

    print(f"\nCONTAINER-INVERSION SCAN | {args.symbol}, Lucid 50K Pro rules, "
          f"{args.size} micro, {args.nights} nights, {args.sims:,} sims")
    print("=" * 96)

    # ---- 1 + 2: track scan with zero-edge decomposition ------------------------
    print(f"{'track':<18}{'$/nt':>7}{'sd$':>6}{'Shp':>6}{'E[net]':>9}{'med':>8}"
          f"{'P>0':>6}{'zeroE':>8}{'edge$':>8}{'busts':>7}{'p/outs':>7}")
    rows = []
    for k, p in pnls.items():
        r = pipeline(p, args.size, args.size, args.nights, args.sims, rng)
        z = pipeline(p - p.mean(), args.size, args.size, args.nights, args.sims, rng)
        shp = p.mean() / p.std() * np.sqrt(252)
        rows.append((k, p.mean(), p.std(), shp, r, z))
        print(f"{k:<18}{p.mean():>7.1f}{p.std():>6.0f}{shp:>6.2f}{r['net']:>9,.0f}"
              f"{r['med']:>8,.0f}{r['p_pos']*100:>5.0f}%{z['net']:>8,.0f}"
              f"{r['net']-z['net']:>8,.0f}{r['busts']:>7.1f}{r['payouts']:>7.1f}")

    # rank agreement: does E[net] follow mean $/night or Sharpe?
    df = pd.DataFrame({"mean": [r[1] for r in rows], "sharpe": [r[3] for r in rows],
                       "net": [r[4]["net"] for r in rows]})
    print(f"\n  rank corr of E[net] with mean $/night: "
          f"{df['net'].corr(df['mean'], method='spearman'):+.2f}   "
          f"with Sharpe: {df['net'].corr(df['sharpe'], method='spearman'):+.2f}")

    # ---- 3: phase sizing grid on the two candidate windows ---------------------
    for track in ("OVERNIGHT 18-06", "23:00-04:00"):
        p = pnls[track]
        print(f"\nPHASE SIZING GRID — {track} (rows: eval micros, cols: funded micros), E[net]")
        sizes = (5, 10, 20, 40)
        print(f"{'':<8}" + "".join(f"{c:>9}" for c in sizes))
        best = (None, -1e18)
        for es in sizes:
            row = f"{es:<8}"
            for fs in sizes:
                r = pipeline(p, es, fs, args.nights, args.sims, rng)
                row += f"{r['net']:>9,.0f}"
                if r["net"] > best[1]:
                    best = ((es, fs, r), r["net"])
            print(row)
        es, fs, r = best[0]
        print(f"  best: eval {es} / funded {fs} -> E[net] ${r['net']:,.0f}, "
              f"med ${r['med']:,.0f}, P>0 {r['p_pos']*100:.0f}%, busts {r['busts']:.1f}, "
              f"payouts {r['payouts']:.1f}, funded {r['funded_frac']*100:.0f}% of nights")


if __name__ == "__main__":
    main()
