"""Locate SPY/QQQ across the 199 1-min shards using parquet footers only.

Reads per-shard column statistics (min/max of `symbol`) via HTTP range reads —
kilobytes per file, not the full 375MB shard. Prints which shards can contain
SPY/QQQ so we only download those.
"""
import os
from pathlib import Path

import duckdb
import requests

env = Path(".env")
for line in env.read_text().splitlines():
    line = line.strip()
    if line and "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())
KEY = os.environ["PWB_API_KEY"]

r = requests.get(
    "https://data.paperswithbacktest.com/v1/datasets/Stocks-1Min-Price",
    params={"pwb_api_key": KEY, "split": "train"}, timeout=30,
)
r.raise_for_status()
files = r.json()["files"]
print("shards:", len(files))

con = duckdb.connect()
con.execute("INSTALL httpfs; LOAD httpfs;")

# schema + sample from shard 0
print("\n--- schema (shard 0) ---")
print(con.execute(f"DESCRIBE SELECT * FROM read_parquet('{files[0]}')").fetchdf().to_string())
print("\n--- 3 rows (shard 0) ---")
print(con.execute(f"SELECT * FROM read_parquet('{files[0]}') LIMIT 3").fetchdf().to_string())

# per-shard symbol min/max from footer stats
print("\n--- symbol range per shard (footer stats) ---")
hits = {"SPY": [], "QQQ": []}
for i, url in enumerate(files):
    try:
        md = con.execute(
            "SELECT min(stats_min_value) mn, max(stats_max_value) mx "
            "FROM parquet_metadata(?) WHERE path_in_schema='symbol'", [url]
        ).fetchone()
        mn, mx = md
        for sym in hits:
            if mn is not None and mx is not None and mn <= sym <= mx:
                hits[sym].append(i)
        if i < 5 or i % 40 == 0:
            print(f"shard {i:3d}: symbol [{mn} .. {mx}]", flush=True)
    except Exception as e:
        print(f"shard {i:3d}: ERR {repr(e)[:80]}", flush=True)

print("\nSPY candidate shards:", hits["SPY"])
print("QQQ candidate shards:", hits["QQQ"])
