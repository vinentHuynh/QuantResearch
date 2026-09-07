"""One year of the Lucid Pro pipeline: buy eval -> pass -> take payouts -> rebuy on failure.

Models the actual published rules for LucidPro 50K and 100K, trading the overnight
block sleeve from mnq_time_block_backtest.py at a fixed micro contract count.

Rules modelled (from the Lucid pricing / funded-rules cards):
  50K  eval: target +$3,000, max loss limit $2,000, EOD trail, DLL off, <=40 micro
       funded: payout profit target $500, MLL $2,000, 40% consistency, 3 days to payout
  100K eval: target +$6,000, MLL $3,000, EOD trail, DLL off, <=60 micro
       funded: payout profit target $750, MLL $3,000, 40% consistency, 3 days to payout
  Eval cost $140.40 / $225.40 first, $140 / $225 per reset. Funded activation free.

Trailing mechanics. The MLL trails the peak END-OF-DAY balance by the buffer and
stops trailing once it reaches the initial balance ("initial trail"), so the floor
in P&L terms is min(peak - buffer, 0). The strategy is flat at every EOD close, so
the EOD balance is just realised P&L -- intraday excursions cannot breach anything,
which is the single biggest reason this container suits this strategy.

Payouts do NOT reset the MLL: the balance drops and the floor stays. That is what
makes "take the profit every time" self-limiting, and why `retain` is swept.

The 40% consistency rule is enforced, not waved at: a payout is blocked until the
largest single winning day in the cycle is <= 40% of the cycle's profit, which
often forces the cycle well past the nominal payout target.

    python lucid_prop_year_sim.py
    python lucid_prop_year_sim.py --window 18-06 --sims 40000
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

DATA = (Path(__file__).resolve().parents[2] / "data")
WINDOWS = {"23-04": (23, 3), "18-06": (18, 5)}
PLANS = {
    #        eval_tgt  mll   payout_tgt  first_cost  reset  max_micro
    "50K":  (3000.0, 2000.0,  500.0, 140.40, 140.00, 40),
    "100K": (6000.0, 3000.0,  750.0, 225.40, 225.00, 60),
}


def nightly_pnl(sym: str, window: str, dpp: float, tick: float) -> np.ndarray:
    """Per-contract $ P&L per night, net of a 1-tick round trip."""
    d = pd.read_parquet(DATA / f"{sym}_5min_databento.parquet").sort_index()
    d = d[d.index >= pd.Timestamp("2020-01-02").tz_localize(d.index.tz)]
    idx = d.index
    sess = (idx - pd.Timedelta(hours=18)).normalize()
    cell = d.groupby([sess, idx.hour]).agg(o=("open", "first"), c=("close", "last"),
                                           n=("open", "size"))
    cell = cell[cell["n"] >= 6]
    o, c = cell["o"].unstack(-1), cell["c"].unstack(-1)
    a, b = WINDOWS[window]
    return ((c[b] - o[a]).dropna() * dpp - tick * dpp).values


def simulate(pnl: np.ndarray, n_ct: int, plan: tuple, retain: float, split: float,
             nights: int, sims: int, rng, first_cap: float, cycle_cap: float) -> dict:
    """Run `sims` independent trader-years through the eval -> funded -> reset loop.

    first_cap / cycle_cap bound a single withdrawal. Without them the model says to
    max out size, because a blown account costs only the reset fee while the firm
    eats the drawdown -- the caps are the firm's defence against that.
    """
    eval_tgt, mll, payout_tgt, first_cost, reset_cost, _ = plan
    draws = rng.choice(pnl, size=(sims, nights), replace=True) * n_ct

    funded = np.zeros(sims, dtype=bool)      # False = in eval, True = funded
    eq = np.zeros(sims)                      # P&L vs the account's starting balance
    peak = np.zeros(sims)                    # peak EOD balance (>= 0)
    cyc_base = np.zeros(sims)                # equity at the start of the payout cycle
    cyc_days = np.zeros(sims)
    cyc_maxday = np.zeros(sims)

    fees = np.full(sims, first_cost)
    paid = np.zeros(sims)
    n_pass = np.zeros(sims)                  # evals passed
    n_bust = np.zeros(sims)                  # accounts lost
    n_payouts = np.zeros(sims)
    acct_payouts = np.zeros(sims)            # payouts taken on the CURRENT account
    funded_nights = np.zeros(sims)

    for t in range(nights):
        pl = draws[:, t]
        eq += pl
        peak = np.maximum(peak, np.maximum(eq, 0.0))
        floor = np.minimum(peak - mll, 0.0)   # trail stops at the initial balance

        funded_nights += funded
        cyc_days += funded
        cyc_maxday = np.where(funded, np.maximum(cyc_maxday, np.maximum(pl, 0.0)), cyc_maxday)

        # --- account blown: pay a reset and start a fresh eval -------------------
        dead = eq <= floor
        if dead.any():
            n_bust += dead
            fees += dead * reset_cost
            funded = np.where(dead, False, funded)
            eq = np.where(dead, 0.0, eq)
            peak = np.where(dead, 0.0, peak)
            cyc_base = np.where(dead, 0.0, cyc_base)
            cyc_days = np.where(dead, 0.0, cyc_days)
            cyc_maxday = np.where(dead, 0.0, cyc_maxday)
            acct_payouts = np.where(dead, 0.0, acct_payouts)

        # --- eval passed: funded account starts flat, activation is free ---------
        passed = (~funded) & (~dead) & (eq >= eval_tgt)
        if passed.any():
            n_pass += passed
            funded = funded | passed
            eq = np.where(passed, 0.0, eq)
            peak = np.where(passed, 0.0, peak)
            cyc_base = np.where(passed, 0.0, cyc_base)
            cyc_days = np.where(passed, 0.0, cyc_days)
            cyc_maxday = np.where(passed, 0.0, cyc_maxday)
            acct_payouts = np.where(passed, 0.0, acct_payouts)

        # --- payout: profit target, >=3 days, and the 40% consistency rule -------
        cyc_profit = eq - cyc_base
        ok = (funded & ~dead
              & (eq - retain >= payout_tgt)
              & (cyc_days >= 3)
              & (cyc_maxday <= 0.40 * np.maximum(cyc_profit, 1e-9)))
        if ok.any():
            cap = np.where(acct_payouts == 0, first_cap, cycle_cap)
            w = np.where(ok, np.minimum(eq - retain, cap), 0.0)
            paid += w * split
            n_payouts += ok
            acct_payouts += ok
            eq = np.where(ok, eq - w, eq)          # capped: the excess stays in
            cyc_base = np.where(ok, eq, cyc_base)
            cyc_days = np.where(ok, 0.0, cyc_days)
            cyc_maxday = np.where(ok, 0.0, cyc_maxday)

    net = paid - fees
    return {"net": net.mean(), "net_med": np.median(net), "paid": paid.mean(),
            "fees": fees.mean(), "p_profit": (net > 0).mean(),
            "passes": n_pass.mean(), "busts": n_bust.mean(),
            "payouts": n_payouts.mean(), "funded_frac": funded_nights.mean() / nights,
            "p5": np.percentile(net, 5), "p95": np.percentile(net, 95)}


def main() -> None:
    ap = argparse.ArgumentParser(description="One-year Lucid Pro pipeline simulation.")
    ap.add_argument("--window", default="23-04", choices=sorted(WINDOWS))
    ap.add_argument("--symbol", default="MNQ")
    ap.add_argument("--nights", type=int, default=250)
    ap.add_argument("--sims", type=int, default=20000)
    ap.add_argument("--split", type=float, default=0.90,
                    help="trader's share of payouts (Lucid Pro is 90/10)")
    ap.add_argument("--first-cap", type=float, default=2000.0,
                    help="cap on the first payout from an account")
    ap.add_argument("--cycle-cap", type=float, default=2500.0,
                    help="cap on each subsequent payout")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    rng = np.random.default_rng(args.seed)
    dpp = 2.0 if args.symbol == "MNQ" else 5.0
    pnl = nightly_pnl(args.symbol, args.window, dpp, 0.25)

    print(f"\nLUCID PRO — ONE YEAR, {args.symbol} {args.window} ET OVERNIGHT BLOCK")
    print("=" * 94)
    print(f"{args.nights} nights | {args.sims:,} simulated years | payout split "
          f"{args.split:.0%} | per-contract edge ${pnl.mean():.2f}/night, sd ${pnl.std():.0f}")
    print("Consistency 40% enforced, 3-day payout cycle, EOD trail locking at the "
          "initial balance.\n")

    for plan_name, plan in PLANS.items():
        eval_tgt, mll, payout_tgt, first_cost, reset_cost, max_micro = plan
        sizes = [s for s in (5, 10, 15, 20, 30, 40, 60) if s <= max_micro]
        print(f"--- {plan_name} PRO | eval +${eval_tgt:,.0f} vs ${mll:,.0f} MLL | "
              f"payout ${payout_tgt:,.0f} | ${first_cost:.2f} + ${reset_cost:.0f}/reset | "
              f"max {max_micro} micro ---")
        print(f"{'size':<6}{'retain':>8}{'E[net]':>10}{'med':>9}{'P(net>0)':>10}"
              f"{'E[paid]':>9}{'E[fees]':>9}{'pass':>6}{'bust':>6}{'p/outs':>8}{'%funded':>9}")
        for n_ct in sizes:
            for retain in (0.0, 1000.0):
                r = simulate(pnl, n_ct, plan, retain, args.split, args.nights,
                             args.sims, rng, args.first_cap, args.cycle_cap)
                print(f"{n_ct:<6}{retain:>8,.0f}{r['net']:>10,.0f}{r['net_med']:>9,.0f}"
                      f"{r['p_profit']*100:>9.0f}%{r['paid']:>9,.0f}{r['fees']:>9,.0f}"
                      f"{r['passes']:>6.1f}{r['busts']:>6.1f}{r['payouts']:>8.1f}"
                      f"{r['funded_frac']*100:>8.0f}%")
        print()


if __name__ == "__main__":
    main()
