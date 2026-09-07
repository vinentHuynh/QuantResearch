"""Pull CME futures bars from Databento -> local parquet in data/.

Reads DATABENTO_API_KEY from .env. Uses the GLBX.MDP3 dataset (CME Globex) and
continuous front-month symbols (e.g. ES.c.0 = calendar-rolled front month, the
Databento equivalent of TradingView's ES1!). Databento's native OHLCV schemas
are 1s/1m/1h/1d, so for 5m/15m we pull 1m and resample.

NOTE: Databento Historical is usage-billed. This spends money. Bars come back in
UTC; we store them tz-aware in US/Eastern to match the session logic used by the
Pine indicators and the SPY/QQQ backtests.

    python databento_fetch.py --symbols ES,NQ --timeframe 5min \
        --start 2022-01-01 --end 2026-08-09 --roll c
"""
import argparse
import os
from pathlib import Path

import pandas as pd

_env = (Path(__file__).resolve().parents[2] / ".env")
for _l in (_env.read_text().splitlines() if _env.exists() else []):
    _l = _l.strip()
    if _l and "=" in _l and not _l.startswith("#"):
        _k, _v = _l.split("=", 1)
        os.environ.setdefault(_k.strip(), _v.strip())

import databento as db

DATASET = "GLBX.MDP3"
AGG = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}


def fetch(client, root, roll, start, end, timeframe):
    cont = f"{root}.{roll}.0"                       # e.g. ES.c.0 front-month continuous
    data = client.timeseries.get_range(
        dataset=DATASET, symbols=[cont], stype_in="continuous",
        schema="ohlcv-1m", start=start, end=end,
    )
    df = data.to_df()
    if df.empty:
        print(f"{root}: no data returned"); return None
    df = df[["open", "high", "low", "close", "volume"]].copy()
    # ts_event index is UTC -> convert to US/Eastern for session alignment
    df.index = df.index.tz_convert("US/Eastern")
    if timeframe != "1min":
        df = df.resample(timeframe).agg(AGG).dropna(subset=["open"])
    return df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default="ES,NQ", help="comma list of roots, e.g. ES,NQ,GC,CL")
    ap.add_argument("--timeframe", default="5min", help="1min,5min,15min,30min,1h")
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--roll", default="c", choices=["c", "v", "n"],
                    help="continuous roll rule: c=calendar, v=volume, n=open interest")
    ap.add_argument("--dry-run", action="store_true", help="print the request, don't fetch")
    args = ap.parse_args()

    key = os.environ.get("DATABENTO_API_KEY")
    if not key:
        raise SystemExit("DATABENTO_API_KEY not set in .env")
    roots = [s.strip().upper() for s in args.symbols.split(",")]

    print(f"Databento {DATASET} | {roots} | {args.roll}.0 continuous | "
          f"ohlcv-1m -> {args.timeframe} | {args.start} -> {args.end}")
    if args.dry_run:
        # estimate cost before spending
        client = db.Historical(key)
        for r in roots:
            try:
                cost = client.metadata.get_cost(
                    dataset=DATASET, symbols=[f"{r}.{args.roll}.0"],
                    stype_in="continuous", schema="ohlcv-1m",
                    start=args.start, end=args.end)
                print(f"  {r}: estimated cost ${cost:.4f}")
            except Exception as e:
                print(f"  {r}: cost estimate failed: {e}")
        print("dry run — nothing fetched.")
        return

    client = db.Historical(key)
    OUT = Path("data"); OUT.mkdir(exist_ok=True)
    for r in roots:
        df = fetch(client, r, args.roll, args.start, args.end, args.timeframe)
        if df is None:
            continue
        path = OUT / f"{r}_{args.timeframe}_databento.parquet"
        df.to_parquet(path)
        print(f"{r}: {len(df):,} {args.timeframe} bars "
              f"{df.index.min()} .. {df.index.max()} -> {path}")
    print("DONE")


if __name__ == "__main__":
    main()
