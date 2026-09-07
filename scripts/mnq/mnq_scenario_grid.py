"""Full backtest of every candidate entry/exit scenario surfaced by the clock sweeps.

The entry and exit sweeps scored one hour at a time holding the other end fixed.
This runs the actual named scenarios end to end -- equity curve, drawdown, tail
counts, both eras, and what each does inside the Lucid 50K container -- so the
choice is made on complete backtests rather than one summary column.

Scenario naming: "16:00*" means the prior afternoon (position is held through the
17:00-18:00 CME halt, and across Friday->Sunday weekends). Unstarred entries are
same-Globex-session, flat at every EOD settlement.

Eras: MNQ 2020-2026 (in-sample, where the windows were chosen) and NQ 2015-2020
(out-of-sample, priced at micro $2/pt and rescaled to today's notional so dollar
figures are comparable). Pooled t uses both.

Per-contract accounting throughout, 1 tick round trip. MaxDD is the worst valley
in cumulative per-contract dollars -- the number that decides whether an account
survives, unlike a percentage against arbitrary chart capital.

    python mnq_scenario_grid.py
    python mnq_scenario_grid.py --pipeline     # add the Lucid 50K column (slow)
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

DATA = (Path(__file__).resolve().parents[2] / "data")
DPP, TICK = 2.0, 0.25
COST = TICK * DPP                       # $0.50 round trip per contract

# (label, entry hour, exit hour, entry taken from the PRIOR afternoon)
SCENARIOS = [
    ("18:00 -> 06:00  [system]", 18, 5, False),
    ("18:00 -> 03:00",           18, 2, False),
    ("18:00 -> 08:00",           18, 7, False),
    ("18:00 -> 16:00  [full 24h]", 18, 16, False),
    ("19:00 -> 06:00",           19, 5, False),
    ("20:00 -> 08:00",           20, 7, False),
    ("23:00 -> 04:00  [demoted]", 23, 3, False),
    ("23:00 -> 06:00",           23, 5, False),
    ("02:00 -> 06:00",            2, 5, False),
    ("16:00* -> 06:00 [NY close]", 16, 5, True),
    ("16:00* -> 02:00",          16, 1, True),
    ("16:00* -> 09:00 [textbook ON]", 16, 8, True),
    ("14:00* -> 06:00",          14, 5, True),
]


def load_cells(fname: str):
    d = pd.read_parquet(DATA / fname).sort_index()
    idx = d.index
    sess = (idx - pd.Timedelta(hours=18)).normalize()
    cell = d.groupby([sess, idx.hour]).agg(o=("open", "first"), c=("close", "last"),
                                           n=("open", "size"))
    cell = cell[cell["n"] >= 6]
    return cell["o"].unstack(-1), cell["c"].unstack(-1)


def scenario_pnl(o, c, eh, xh, prior, ref=None):
    """Per-night $ P&L per contract, net of cost. ref set -> rescale to today's notional."""
    ent = o[eh].shift(1) if prior else o[eh]
    j = pd.concat([ent, c[xh]], axis=1).dropna()
    entry, exit_ = j.iloc[:, 0], j.iloc[:, 1]
    if ref is None:
        return pd.Series((exit_ - entry).values * DPP - COST, index=j.index)
    return pd.Series(((exit_ - entry) / entry).values * ref * DPP - COST, index=j.index)


def maxdd(pnl: pd.Series) -> float:
    eq = pnl.cumsum()
    return float((eq - eq.cummax()).min())


def stats(p: pd.Series) -> dict:
    a = p.values
    w, l = a[a > 0], a[a < 0]
    return {
        "n": len(a), "mean": a.mean(), "sd": a.std(ddof=1),
        "pf": w.sum() / abs(l.sum()) if len(l) else np.inf,
        "hit": (a > 0).mean() * 100,
        "sharpe": a.mean() / a.std(ddof=1) * np.sqrt(252),
        "t": a.mean() / a.std(ddof=1) * np.sqrt(len(a)),
        "worst": a.min(), "maxdd": maxdd(p),
        "yr": a.mean() * 252,
        "lt1k": (a < -1000).sum(), "lt2k": (a < -2000).sum(),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Full scenario grid for the overnight block.")
    ap.add_argument("--pipeline", action="store_true", help="add Lucid 50K E[net] (slow)")
    ap.add_argument("--size", type=int, default=10)
    ap.add_argument("--sims", type=int, default=10000)
    args = ap.parse_args()

    o_new, c_new = load_cells("MNQ_5min_databento.parquet")
    o_old, c_old = load_cells("NQ_5min_databento.parquet")
    ref = float(o_new[18].loc["2024-01-01":].median())

    rows = []
    for label, eh, xh, prior in SCENARIOS:
        pn = scenario_pnl(o_new, c_new, eh, xh, prior)
        po = scenario_pnl(o_old, c_old, eh, xh, prior, ref=ref)
        pool = np.concatenate([po.values, pn.values])
        rows.append((label, stats(pn), stats(po),
                     pool.mean() / pool.std(ddof=1) * np.sqrt(len(pool))))

    print(f"\nSCENARIO BACKTESTS | 1 MNQ contract, net 1 tick | old era scaled to "
          f"{ref:,.0f} notional")
    print("=" * 118)
    print(f"{'scenario':<30}{'hrs':>4}|{'$/nt':>7}{'$/yr':>8}{'Shp':>6}{'PF':>6}"
          f"{'hit%':>6}{'MaxDD$':>9}{'worst':>8}{'<-1k':>6}|{'OOS $/nt':>9}{'OOS Shp':>8}"
          f"{'OOS PF':>7}|{'pool t':>7}")
    for (label, eh, xh, prior), (lb, sn, so, pt) in zip(SCENARIOS, rows):
        hrs = (xh + 1 - eh) % 24
        print(f"{label:<30}{hrs:>4}|{sn['mean']:>7.2f}{sn['yr']:>8,.0f}{sn['sharpe']:>6.2f}"
              f"{sn['pf']:>6.3f}{sn['hit']:>6.1f}{sn['maxdd']:>9,.0f}{sn['worst']:>8,.0f}"
              f"{sn['lt1k']:>6}|{so['mean']:>9.2f}{so['sharpe']:>8.2f}{so['pf']:>7.3f}"
              f"|{pt:>7.2f}")

    print("\nRISK-PER-DOLLAR VIEW (in-sample; MaxDD is the account-killing number)")
    print(f"{'scenario':<30}{'$/yr':>8}{'MaxDD$':>9}{'yr/DD':>7}{'sd$':>6}"
          f"{'<-1k':>6}{'<-2k':>6}{'EOD flat?':>11}")
    for (label, eh, xh, prior), (lb, sn, so, pt) in zip(SCENARIOS, rows):
        flat = "no (holds)" if prior else "yes"
        print(f"{label:<30}{sn['yr']:>8,.0f}{sn['maxdd']:>9,.0f}"
              f"{sn['yr']/abs(sn['maxdd']):>7.2f}{sn['sd']:>6.0f}{sn['lt1k']:>6}"
              f"{sn['lt2k']:>6}{flat:>11}")

    if args.pipeline:
        from lucid_container_scan import pipeline
        rng = np.random.default_rng(7)
        print(f"\nLUCID 50K PIPELINE ({args.size} micro, {args.sims:,} sims, combined eras)")
        print(f"{'scenario':<30}{'E[net]':>9}{'med':>8}{'P>0':>6}{'busts':>7}{'p/outs':>8}")
        for (label, eh, xh, prior) in SCENARIOS:
            pn = scenario_pnl(o_new, c_new, eh, xh, prior).values
            po = scenario_pnl(o_old, c_old, eh, xh, prior, ref=ref).values
            r = pipeline(np.concatenate([po, pn]), args.size, args.size, 250,
                         args.sims, rng)
            print(f"{label:<30}{r['net']:>9,.0f}{r['med']:>8,.0f}{r['p_pos']*100:>5.0f}%"
                  f"{r['busts']:>7.1f}{r['payouts']:>8.1f}")


if __name__ == "__main__":
    main()
