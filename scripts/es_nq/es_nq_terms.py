"""ES+NQ strategies sliced by US presidential term (regime buckets).

Reuses the strategy set from es_nq_strategies.py. Signals are computed on the
full warmed series (from 2011), then sliced per term so indicators are valid.
Gross of costs. Same cash-index proxy caveat.

Usage: python es_nq_terms.py --balance 100000
"""
import argparse

import pandas as pd

from es_nq_strategies import STRATS, SYMBOLS, load, stats

TERMS = [
    ("Obama II", "2013-01-20", "2017-01-20"),
    ("Trump I", "2017-01-20", "2021-01-20"),
    ("Biden", "2021-01-20", "2025-01-20"),
    ("Trump II", "2025-01-20", None),  # to latest
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--balance", type=float, default=100_000)
    args = ap.parse_args()

    data = {n: load(s) for n, s in SYMBOLS.items()}
    common = data["ES"].index.intersection(data["NQ"].index)
    last = common[-1]

    # full-series portfolio daily returns per strategy (computed once)
    port = {}
    for name, fn in STRATS.items():
        port[name] = pd.concat(
            [fn(data[n]).reindex(common) for n in SYMBOLS], axis=1
        ).mean(axis=1)

    # bounds per term
    bounds = []
    for label, s, e in TERMS:
        start = pd.Timestamp(s)
        end = pd.Timestamp(e) if e else last + pd.Timedelta(days=1)
        bounds.append((label, start, end))

    def slice_ret(r, start, end):
        return r[(r.index >= start) & (r.index < end)]

    # regime context: SPX buy-hold total return per term
    spx_ret = data["ES"]["close"].pct_change()
    print(f"\nES+NQ by presidency | 50/50 | ${args.balance:,.0f} start each term | GROSS of costs")
    print("Regime (SPX total return):")
    for label, start, end in bounds:
        r = slice_ret(spx_ret, start, end)
        tot = (1 + r).prod() - 1 if len(r) else float("nan")
        rng = f"{start.date()} -> {min(end - pd.Timedelta(days=1), last).date()}"
        print(f"  {label:<10} {rng}   SPX {tot*100:+6.1f}%")

    def matrix(metric_name, fmt, pick):
        cols = "".join(f"{lbl:>12}" for lbl, _, _ in bounds)
        print(f"\n{metric_name} by term:")
        print(f"{'Strategy':<26}{cols}")
        print("-" * (26 + 12 * len(bounds)))
        # order rows by average Sharpe across terms (best first)
        order = sorted(
            STRATS,
            key=lambda nm: -pd.Series(
                [stats(build(port[nm], b))[0] for b in bounds]
            ).mean(),
        )
        for nm in order:
            cells = ""
            for b in bounds:
                v = pick(stats(build(port[nm], b)))
                cells += f"{fmt(v):>12}"
            print(f"{nm:<26}{cells}")

    def build(r, b):
        _, start, end = b
        rr = slice_ret(r, start, end)
        nav = args.balance * (1 + rr).cumprod()
        return nav.tolist() if len(nav) > 5 else [args.balance, args.balance]

    matrix("Sharpe", lambda v: f"{v:.2f}", lambda s: s[0])
    matrix("CAGR", lambda v: f"{v*100:.1f}%", lambda s: s[1])
    matrix("MaxDD", lambda v: f"{v*100:.1f}%", lambda s: s[3])


if __name__ == "__main__":
    main()
