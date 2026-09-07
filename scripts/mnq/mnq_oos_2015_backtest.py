"""Out-of-sample test of the MNQ overnight windows on 2015-2020 NQ data.

Every window choice in this workspace (18:00-06:00, 23:00-04:00, the block
ranking) was made looking only at 2020-2026 data. The 2015-2020 NQ pull existed
nowhere in that process, so this is a true out-of-sample test: if the overnight
drift is a stable feature of the index rather than a COVID-era artifact, it
should already be present in 2015-2019.

MNQ only launched May 2019, so the pre-2020 instrument is the e-mini NQ.
Identical index, identical points; a "micro contract" of that era is simulated at
MNQ's $2/point. Liquidity/costs differ (NQ tick is the same 0.25pt but $5 on the
e-mini); costs here stay at 1 MNQ tick ($0.50 RT) for comparability.

Scale trap, handled explicitly: NQ traded ~4,400-8,000 in 2015-2019 vs ~20-30k in
2024-26, so raw dollar P&L per contract is 3-5x smaller in the old era. Feeding
raw old-era dollars into the Lucid pipeline (fixed $2,000/$3,000 barriers) would
fake safety. For the pipeline, each era's nightly RETURN is applied to today's
contract notional -- "what if that era's dynamics recurred at today's prices" --
via points * (ref_price / entry_price) * $2/pt with ref_price = the 2024-26
median. Attribution tables show both native and scaled units.

    python mnq_oos_2015_backtest.py
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from lucid_container_scan import pipeline  # the Lucid 50K year sim

DATA = (Path(__file__).resolve().parents[2] / "data")
DPP = 2.0                      # micro $/pt, both eras
COST_PTS = 0.25                # 1 tick RT
TRACKS = {
    "Asia 18-00":      (18, 23),
    "London 00-06":    (0, 5),
    "NY am 06-12":     (6, 11),
    "NY pm 12-18":     (12, 16),
    "23:00-04:00":     (23, 3),
    "OVERNIGHT 18-06": (18, 5),
    "FULL 24h":        (18, 16),
}


def load_cells(fname: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    d = pd.read_parquet(DATA / fname).sort_index()
    idx = d.index
    sess = (idx - pd.Timedelta(hours=18)).normalize()
    cell = d.groupby([sess, idx.hour]).agg(o=("open", "first"), c=("close", "last"),
                                           n=("open", "size"))
    cell = cell[cell["n"] >= 6]
    return cell["o"].unstack(-1), cell["c"].unstack(-1)


def track_frames(o: pd.DataFrame, c: pd.DataFrame) -> dict[str, pd.DataFrame]:
    out = {}
    for k, (a, b) in TRACKS.items():
        f = pd.DataFrame({"entry": o[a], "exit": c[b]}).dropna()
        f["pts"] = f["exit"] - f["entry"]
        out[k] = f
    return out


def tstat(x: np.ndarray) -> float:
    return float(x.mean() / x.std(ddof=1) * np.sqrt(len(x)))


def pf(x: np.ndarray) -> float:
    return x[x > 0].sum() / abs(x[x < 0].sum())


def main() -> None:
    ap = argparse.ArgumentParser(description="2015-2020 OOS test of the overnight windows.")
    ap.add_argument("--sims", type=int, default=20000)
    ap.add_argument("--size", type=int, default=10, help="micros in the pipeline runs")
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    rng = np.random.default_rng(args.seed)
    o_old, c_old = load_cells("NQ_5min_databento.parquet")      # 2015-2020
    o_new, c_new = load_cells("MNQ_5min_databento.parquet")     # 2020-2026
    old, new = track_frames(o_old, c_old), track_frames(o_new, c_new)
    ref_price = float(new["OVERNIGHT 18-06"]["entry"]
                      .loc["2024-01-01":].median())

    print("\nOUT-OF-SAMPLE: 2015-2020 NQ vs 2020-2026 MNQ (window chosen on 2020-26 ONLY)")
    print("=" * 100)
    print(f"Old era: {old['FULL 24h'].index.min().date()} -> "
          f"{old['FULL 24h'].index.max().date()} | scale reference price "
          f"{ref_price:,.0f} (2024-26 median)\n")

    # ---- per-era attribution ---------------------------------------------------
    hdr = (f"{'track':<17}{'n':>6}{'$/nt':>7}{'t':>6}{'PF':>7}{'hit%':>6}"
           f"{'| n':>7}{'$/nt':>7}{'t':>6}{'PF':>7}{'hit%':>6}{'| scl$/nt':>10}{'sclSd':>7}")
    print(f"{'':<17}{'------- 2015-2020 (native $) -------':^39}"
          f"{'------- 2020-2026 -------':^33}{'2015-20 scaled':^18}")
    print(hdr)
    for k in TRACKS:
        po = old[k]["pts"].values * DPP - COST_PTS * DPP
        pn = new[k]["pts"].values * DPP - COST_PTS * DPP
        scl = (old[k]["pts"] / old[k]["entry"]).values * ref_price * DPP - COST_PTS * DPP
        print(f"{k:<17}{len(po):>6}{po.mean():>7.2f}{tstat(po):>6.2f}{pf(po):>7.3f}"
              f"{(po > 0).mean()*100:>6.1f}{len(pn):>7}{pn.mean():>7.1f}{tstat(pn):>6.2f}"
              f"{pf(pn):>7.3f}{(pn > 0).mean()*100:>6.1f}{scl.mean():>10.1f}{scl.std():>7.0f}")

    # ---- yearly overnight, old era --------------------------------------------
    on = old["OVERNIGHT 18-06"]
    yr = (on["pts"] * DPP).groupby(on.index.year)
    print("\nOVERNIGHT 18-06, 2015-2019 by year (native $, 1 micro-equivalent):")
    for y, s in yr:
        print(f"  {y}: total ${s.sum():>7,.0f}  mean ${s.mean():>6.2f}  t={tstat(s.values):>5.2f}"
              f"  hit {(s > 0).mean()*100:.1f}%")

    # ---- pipeline: same model, three data regimes ------------------------------
    print(f"\nLUCID 50K PIPELINE ({args.size} micro symmetric, {args.sims:,} sims, "
          f"old era scaled to today's notional)")
    print(f"{'data regime':<26}{'track':<17}{'E[net]':>9}{'med':>8}{'P>0':>6}"
          f"{'busts':>7}{'p/outs':>7}")
    for k in ("OVERNIGHT 18-06", "23:00-04:00"):
        scl_old = ((old[k]["pts"] / old[k]["entry"]).values * ref_price * DPP
                   - COST_PTS * DPP)
        pn = new[k]["pts"].values * DPP - COST_PTS * DPP
        regimes = {"2015-2020 only (OOS)": scl_old,
                   "2020-2026 only": pn,
                   "2015-2026 combined": np.concatenate([scl_old, pn])}
        for nm, p in regimes.items():
            r = pipeline(p, args.size, args.size, 250, args.sims, rng)
            print(f"{nm:<26}{k:<17}{r['net']:>9,.0f}{r['med']:>8,.0f}"
                  f"{r['p_pos']*100:>5.0f}%{r['busts']:>7.1f}{r['payouts']:>7.1f}")


if __name__ == "__main__":
    main()
