"""Export cached Databento 5-minute bars into NinjaTrader 8 import format.

NinjaTrader's Historical Data import expects one line per bar:

    yyyyMMdd HHmmss;open;high;low;close;volume

WHICH TIME ZONE NINJATRADER WANTS IS THE ONE THING TO VERIFY BY HAND.
The parquet is stored US/Eastern. NinjaTrader's documented convention is the
INSTRUMENT'S EXCHANGE time zone, which for CME products is US/Central -- one
hour behind Eastern. Get this wrong and every session boundary in both
strategies shifts by an hour, silently: the opening range would be built from
08:30-08:45 bars and the overnight block would run 17:00-05:00. Nothing would
error; the results would just be wrong.

So this writes a ONE-WEEK sample in both zones. Import one, put it on a chart,
and check where the RTH open actually lands before committing 464k bars.

    .venv\\Scripts\\python.exe ninjatrader\\export_for_nt.py --sample
    .venv\\Scripts\\python.exe ninjatrader\\export_for_nt.py --tz US/Central
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from overnight_drift_carver_backtest import INSTRUMENTS, load_5m   # noqa: E402

OUT = Path(__file__).resolve().parent / "nt_import"


def write_nt(d, path):
    """yyyyMMdd HHmmss;O;H;L;C;V -- NinjaTrader 8 minute-bar import format."""
    lines = (
        d.index.strftime("%Y%m%d %H%M%S")
        + ";" + d.open.map("{:.2f}".format)
        + ";" + d.high.map("{:.2f}".format)
        + ";" + d.low.map("{:.2f}".format)
        + ";" + d.close.map("{:.2f}".format)
        + ";" + d.volume.astype("int64").astype(str)
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="ascii", newline="\r\n")
    return len(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--inst", default="MNQ")
    ap.add_argument("--tz", default="US/Central",
                    help="US/Central is CME exchange time and NinjaTrader's "
                         "documented convention. Verify with --sample first.")
    ap.add_argument("--name", default=None,
                    help="NinjaTrader instrument name. Defaults to <INST>CONT -- "
                         "import into a CUSTOM instrument, not a real contract "
                         "month, so NinjaTrader does not try to roll it.")
    ap.add_argument("--sample", action="store_true",
                    help="write one week in BOTH time zones and stop")
    ap.add_argument("--end", default="2026-08-30")
    args = ap.parse_args()

    fname, dpp, tick, _ = INSTRUMENTS[args.inst]
    d = load_5m(fname, args.end)
    name = args.name or (args.inst + "CONT")

    print("%s  %s bars  %s -> %s  (stored %s)"
          % (args.inst, format(len(d), ","), d.index[0], d.index[-1], d.index.tz))
    print("NinjaTrader instrument to create: %s   tick %.2f   point value $%.0f"
          % (name, tick, dpp))

    if args.sample:
        # NinjaTrader parses the instrument and price type OUT OF THE FILENAME,
        # so both samples must be called <name>.Last.txt and therefore have to
        # live in separate folders.
        wk = d[(d.index >= "2026-06-01") & (d.index < "2026-06-08")]
        for tz in ("US/Eastern", "US/Central"):
            s = wk.tz_convert(tz)
            p = OUT / ("sample_" + tz.replace("/", "-")) / ("%s.Last.txt" % name)
            n = write_nt(s, p)
            print("  %-12s %5d bars -> %s"
                  % (tz, n, p.relative_to(OUT.parent)))
            print("               first bar %s"
                  % s.index[0].strftime("%Y%m%d %H%M%S"))
        print("\nImport ONE of these, chart it, and confirm the 09:30 bar is the RTH")
        print("open (a clear volume jump). Then re-run without --sample using the tz")
        print("that lined up.")
        return

    s = d.tz_convert(args.tz)
    p = OUT / ("%s.Last.txt" % name)
    n = write_nt(s, p)
    print("\n  wrote %s bars -> %s  (%.1f MB, %s)"
          % (format(n, ","), p, p.stat().st_size / 1e6, args.tz))


if __name__ == "__main__":
    main()
