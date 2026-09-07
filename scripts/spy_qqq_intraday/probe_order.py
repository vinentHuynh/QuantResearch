"""Download a few 1-min shards fully (no range support) and reveal ordering:
is the dataset sharded by symbol or by date? Decides how to fetch SPY/QQQ.
"""
import io
import os
from pathlib import Path

import pandas as pd
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
files = r.json()["files"]


def peek(i):
    url = files[i]
    resp = requests.get(url, timeout=300)
    df = pd.read_parquet(io.BytesIO(resp.content))
    syms = df["symbol"].unique() if "symbol" in df.columns else []
    dcol = "datetime" if "datetime" in df.columns else ("date" if "date" in df.columns else None)
    drange = (str(df[dcol].min()), str(df[dcol].max())) if dcol else ("?", "?")
    print(f"shard {i}: {len(df):,} rows, cols={list(df.columns)}")
    print(f"  n_symbols={len(syms)}  first10={sorted(map(str,syms))[:10]}")
    print(f"  SPY in shard: {'SPY' in set(map(str,syms))}   QQQ in shard: {'QQQ' in set(map(str,syms))}")
    print(f"  {dcol} range: {drange[0]} -> {drange[1]}", flush=True)


for i in [0, 198]:
    peek(i)
