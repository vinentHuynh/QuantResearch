"""Build SPY/QQQ 5-min RTH bars for 2024->now from the 1-min shards.

The PWB endpoint blocks HTTP range reads, so each ~500MB monthly shard must be
downloaded whole. We stream it to a temp file, use pyarrow row-group pruning to
pull only SPY/QQQ rows (symbols are sorted A->Z per shard, so this is cheap in
memory), delete the raw file, and move on. Result cached as small parquet.

Shards 167-198 cover ~2023-12 .. 2026-07. Output filtered to date >= START.
"""
import os
import tempfile
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq
import requests

START = "2024-01-01"
SHARDS = range(167, 199)          # 2023-12 .. 2026-07 (inclusive)
SYMS = ["SPY", "QQQ"]
KEEP = ["symbol", "datetime", "adj_open", "adj_high", "adj_low", "adj_close", "volume"]
REN = {"adj_open": "open", "adj_high": "high", "adj_low": "low", "adj_close": "close"}

env = Path(".env")
for line in env.read_text().splitlines():
    line = line.strip()
    if line and "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())
KEY = os.environ["PWB_API_KEY"]
OUT = Path("data"); OUT.mkdir(exist_ok=True)

files = requests.get(
    "https://data.paperswithbacktest.com/v1/datasets/Stocks-1Min-Price",
    params={"pwb_api_key": KEY, "split": "train"}, timeout=30,
).json()["files"]

parts = []
for i in SHARDS:
    tmp = Path(tempfile.gettempdir()) / f"shard_{i}.parquet"
    # stream to disk (don't hold 500MB in RAM)
    with requests.get(files[i], timeout=900, stream=True) as r:
        r.raise_for_status()
        with open(tmp, "wb") as fh:
            for chunk in r.iter_content(chunk_size=1 << 20):
                fh.write(chunk)
    mb = tmp.stat().st_size / 1e6
    # pyarrow filtered read: only SPY/QQQ row groups
    tbl = pq.read_table(tmp, columns=KEEP,
                        filters=[("symbol", "in", SYMS)])
    df = tbl.to_pandas()
    tmp.unlink()
    parts.append(df)
    print(f"shard {i:3d}: {mb:5.0f}MB -> kept {len(df):>6} SPY/QQQ rows "
          f"({df['datetime'].min()} .. {df['datetime'].max()})", flush=True)

full = pd.concat(parts, ignore_index=True).rename(columns=REN)
full["datetime"] = pd.to_datetime(full["datetime"])

for sym in SYMS:
    d = full[full["symbol"] == sym].set_index("datetime").sort_index()
    d = d[["open", "high", "low", "close", "volume"]].astype(float)
    d = d[d.index >= pd.Timestamp(START)]
    d = d.between_time("09:30", "15:59")           # regular session only (ET)
    agg = {"open": "first", "high": "max", "low": "min",
           "close": "last", "volume": "sum"}
    five = d.resample("5min").agg(agg).dropna(subset=["open"])
    five = five.between_time("09:30", "15:59")
    path = OUT / f"{sym}_5min.parquet"
    five.to_parquet(path)
    print(f"{sym}: {len(d):,} 1-min RTH -> {len(five):,} 5-min bars, "
          f"{five.index.min()} .. {five.index.max()} -> {path}", flush=True)

print("DONE", flush=True)
