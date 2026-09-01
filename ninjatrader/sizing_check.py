"""What contract size will the two NinjaTrader strategies actually submit?

Replays the exact sizing arithmetic the NinjaScript uses --

    raw  = Capital * IDM * weight * tau / (sigma_ann * price * multiplier)
    lots = floor(raw + 0.5)          # C# Math.Round(..., MidpointRounding.AwayFromZero)
    skip if lots == 0

-- against the same vol series the backtests use, so the answer is the
distribution of order sizes, not a formula.

The two strategies differ only in tau: the ORB runs 12% (trade skew +0.84),
the overnight block runs 6% (12% halved for nightly skew -0.35).

    .venv\\Scripts\\python.exe ninjatrader\\sizing_check.py
    .venv\\Scripts\\python.exe ninjatrader\\sizing_check.py --capital 350000
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from overnight_drift_carver_backtest import (          # noqa: E402
    INSTRUMENTS, carver_vol, daily_closes, liquid_start, load_5m,
)

STRATEGIES = (("OrbCarver", 0.12), ("OvernightDriftCarver", 0.06))


def lots_of(capital, tau, idm, weight, vol, px, dpp):
    """The NinjaScript SizePosition(), vectorised. floor(x+0.5) == AwayFromZero."""
    raw = capital * idm * weight * tau / (vol * px * dpp)
    return raw, np.floor(raw + 0.5)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--insts", default="MNQ,MES,MGC")
    ap.add_argument("--capital", type=float, default=100_000)
    ap.add_argument("--idm", type=float, default=1.0)
    ap.add_argument("--weight", type=float, default=1.0)
    ap.add_argument("--end", default="2026-08-30")
    args = ap.parse_args()

    pd.set_option("display.width", 200)
    print("=" * 92)
    print("CONTRACT SIZE THE NINJATRADER STRATEGIES WILL SUBMIT")
    print("capital $%s   IDM %.2f   weight %.2f" % (format(args.capital, ",.0f"),
                                                    args.idm, args.weight))
    print("=" * 92)

    for name in [s.strip() for s in args.insts.split(",")]:
        fname, dpp, tick, _ = INSTRUMENTS[name]
        d = load_5m(fname, args.end)
        d = d[d.index >= liquid_start(d)]
        closes = daily_closes(d)
        vol = carver_vol(closes)
        df = pd.DataFrame({"px": closes, "vol": vol}).dropna()

        print("\n%s   $%.0f/pt   %s -> %s   %d sessions"
              % (name, dpp, df.index[0].date(), df.index[-1].date(), len(df)))
        print("-" * 92)

        for label, tau in STRATEGIES:
            raw, lots = lots_of(args.capital, tau, args.idm, args.weight,
                                df.vol, df.px, dpp)
            # sigma above which raw < 0.5 and the strategy skips the session
            skip_vol = args.capital * args.idm * args.weight * tau / (0.5 * df.px * dpp)

            rows = []
            for tag, m in (("all", df.index == df.index),
                           ("2024", df.index.year == 2024),
                           ("2025", df.index.year == 2025),
                           ("2026", df.index.year == 2026)):
                if not m.any():
                    continue
                lo, rw = lots[m], raw[m]
                counts = lo.value_counts(normalize=True)
                rows.append({
                    "window": tag, "sessions": int(m.sum()),
                    "median_px": df.px[m].median(), "median_vol": df.vol[m].median(),
                    "raw_med": rw.median(),
                    "skip_0": counts.get(0.0, 0.0), "lots_1": counts.get(1.0, 0.0),
                    "lots_2": counts.get(2.0, 0.0),
                    "lots_3+": float((lo >= 3).mean()),
                    "mean_lots": lo.mean(),
                    "vol_to_skip": skip_vol[m].median(),
                })
            R = pd.DataFrame(rows).set_index("window")
            print("  %s  (tau %.0f%%)" % (label, tau * 100))
            print(R.to_string(formatters={
                "median_px": "{:,.0f}".format, "median_vol": "{:.1%}".format,
                "raw_med": "{:.2f}".format, "skip_0": "{:.0%}".format,
                "lots_1": "{:.0%}".format, "lots_2": "{:.0%}".format,
                "lots_3+": "{:.0%}".format, "mean_lots": "{:.2f}".format,
                "vol_to_skip": "{:.0%}".format}))

        # Carver's 4-contract floor, at the latest prices
        px, sd = df.px.iloc[-1], df.vol.iloc[-1]
        print("  Carver 4-lot floor at %s px %s, sigma %.1f%%:"
              % (df.index[-1].date(), format(px, ",.0f"), sd * 100))
        for label, tau in STRATEGIES:
            print("    %-22s 1 lot $%-12s 4 lots $%s"
                  % (label, format(dpp * px * sd / tau, ",.0f"),
                     format(4 * dpp * px * sd / tau, ",.0f")))

    print("\n" + "=" * 92)
    print("skip_0   = sessions where the vol-implied size rounds to ZERO and the")
    print("           strategy takes no trade at all (it logs 'size rounds to zero').")
    print("vol_to_skip = the 25-day annualised vol above which that happens.")
    print("Carver's floor is 4 lots, so rounding error stays <= 12.5%. Below that the")
    print("system is quantised: at 1 lot it is a fixed-size system in a vol-target's")
    print("clothes, and the risk you actually run is whatever the rounding gives you.")


if __name__ == "__main__":
    main()
