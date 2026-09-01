"""Map shard index -> datetime range for the tail, to find the 2024-2026 shards.
Downloads only 'datetime' + 'symbol' columns per shard to cut transfer."""
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
files = requests.get(
    "https://data.paperswithbacktest.com/v1/datasets/Stocks-1Min-Price",
    params={"pwb_api_key": KEY, "split": "train"}, timeout=30,
).json()["files"]


def peek(i):
    resp = requests.get(files[i], timeout=600)
    mb = len(resp.content) / 1e6
    # read only needed columns to keep memory low
    df = pd.read_parquet(io.BytesIO(resp.content), columns=["symbol", "datetime"])
    dmin, dmax = df["datetime"].min(), df["datetime"].max()
    spy = (df["symbol"] == "SPY").sum()
    qqq = (df["symbol"] == "QQQ").sum()
    print(f"shard {i:3d}: {mb:6.0f}MB  {dmin} -> {dmax}  SPYrows={spy} QQQrows={qqq}",
          flush=True)
    return dmin, dmax


for i in [150, 170, 180, 185, 190, 195, 197]:
    peek(i)
