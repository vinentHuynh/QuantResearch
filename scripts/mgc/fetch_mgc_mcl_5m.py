"""Pull MGC + MCL 5-minute bars from Databento GLBX.MDP3 into data/.

Databento's native OHLCV schemas are 1s/1m/1h/1d, so 5m is built by pulling
ohlcv-1m and resampling. Continuous front-month symbols (MGC.c.0) are used,
volume-rolled by default (MGC.v.0) so the series always tracks the most-traded
contract; calendar roll walks into dead serial months.

Fetches year-by-year so a failure part way through doesn't lose everything, and
merges with any existing parquet for the symbol (existing bars win on overlap).

    python fetch_mgc_mcl_5m.py --symbols MGC,MCL --start 2015-01-01
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
# first date each contract has data on GLBX (micros listed later than the bigs)
INCEPTION = {"MGC": "2010-06-06", "MCL": "2021-07-12", "MES": "2019-05-06", "MNQ": "2019-05-06"}


def fetch_1m(client, root, start, end, cache, roll):
    """One year-ish slice of ohlcv-1m as a UTC-indexed frame, or None if empty.

    Every slice is cached to disk the instant it arrives -- these bytes are
    billed, so a crash later in the run must not throw them away.
    """
    cached = cache / f"{root}.{roll}.0_{start}_{end}_1m.parquet"
    if cached.exists():
        print(f"    (cached {cached.name})")
        return pd.read_parquet(cached)
    data = client.timeseries.get_range(
        dataset=DATASET, symbols=[f"{root}.{roll}.0"], stype_in="continuous",
        schema="ohlcv-1m", start=start, end=end,
    )
    df = data.to_df()
    if df.empty:
        return None
    df = df[["open", "high", "low", "close", "volume"]]
    df.to_parquet(cached)
    return df


def available_end(client):
    """Live edge of GLBX.MDP3. A date-only `end` means end-of-day to Databento,
    so anything at/after today trips 422 dataset_unavailable_range."""
    rng = client.metadata.get_dataset_range(dataset=DATASET)
    return pd.Timestamp(rng["end"]).tz_convert("UTC").floor("D")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default="MGC,MCL")
    ap.add_argument("--start", default="2015-01-01")
    ap.add_argument("--end", default=None, help="default: last fully available day")
    ap.add_argument("--timeframe", default="5min")
    ap.add_argument("--roll", default="v", choices=["c", "v", "n"],
                    help="continuous roll: v=volume (default), c=calendar, n=open interest. "
                         "Use v -- calendar roll steps into dead serial months (MGC Sep/Nov etc. "
                         "trade single-digit lots), which silently guts the series.")
    ap.add_argument("--out", default=None,
                    help="explicit output parquet (single symbol only); default data/<ROOT>_<tf>_databento.parquet")
    args = ap.parse_args()

    key = os.environ.get("DATABENTO_API_KEY")
    if not key:
        raise SystemExit("DATABENTO_API_KEY not set in .env")
    client = db.Historical(key)
    OUT = (Path(__file__).resolve().parents[2] / "data"); OUT.mkdir(exist_ok=True)
    cache = OUT / "_dbn_cache"; cache.mkdir(exist_ok=True)
    live_edge = available_end(client)

    for root in [s.strip().upper() for s in args.symbols.split(",")]:
        path = Path(args.out) if args.out else OUT / f"{root}_{args.timeframe}_databento.parquet"
        have = pd.read_parquet(path) if path.exists() else None
        if have is not None:
            print(f"{root}: existing {len(have):,} bars {have.index.min()} .. {have.index.max()}")

        # clamp the request to when the contract actually existed
        start = max(pd.Timestamp(args.start), pd.Timestamp(INCEPTION.get(root, args.start)))
        end = min(pd.Timestamp(args.end) if args.end else live_edge.tz_localize(None),
                  live_edge.tz_localize(None))
        edges = list(pd.date_range(start, end, freq="YS")) # year boundaries inside the range
        bounds = sorted({start, *edges, end})

        chunks = []
        for lo, hi in zip(bounds[:-1], bounds[1:]):
            lo_s, hi_s = lo.strftime("%Y-%m-%d"), hi.strftime("%Y-%m-%d")
            # skip windows already fully covered by the existing file
            if have is not None:
                covered = have.index.tz_convert("UTC")
                if covered.min() <= lo.tz_localize("UTC") and hi.tz_localize("UTC") <= covered.max():
                    print(f"  {root} {lo_s}..{hi_s}: already covered, skip")
                    continue
            try:
                df = fetch_1m(client, root, lo_s, hi_s, cache, args.roll)
            except Exception as ex:
                print(f"  {root} {lo_s}..{hi_s}: FAILED {ex}", flush=True)
                continue
            n = 0 if df is None else len(df)
            print(f"  {root} {lo_s}..{hi_s}: {n:,} 1m bars", flush=True)
            if df is not None:
                chunks.append(df)

        if not chunks and have is None:
            print(f"{root}: nothing fetched, no existing file -- skipping"); continue

        if chunks:
            new = pd.concat(chunks).sort_index()
            new = new[~new.index.duplicated(keep="last")]
            new.index = new.index.tz_convert("US/Eastern")
            if args.timeframe != "1min":
                new = new.resample(args.timeframe).agg(AGG).dropna(subset=["open"])
        else:
            new = None

        merged = new if have is None else (have if new is None else
                 pd.concat([new[~new.index.isin(have.index)], have]).sort_index())
        merged.to_parquet(path)
        print(f"{root}: {len(merged):,} {args.timeframe} bars "
              f"{merged.index.min()} .. {merged.index.max()} -> {path}\n", flush=True)
    print("DONE")


if __name__ == "__main__":
    main()
