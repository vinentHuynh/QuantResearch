"""One-time fetch of SPY/QQQ 1-min bars -> resample to 5-min -> local parquet.

The PWB 1-min dataset has no date filter (symbol-only), so the first pull is
heavy. This caches 5-min bars to data/ so downstream backtests never re-download.

Usage: python fetch_intraday.py
"""
import os
import time
from pathlib import Path

import pandas as pd

_env = (Path(__file__).resolve().parents[2] / ".env")
if _env.exists():
    for _l in _env.read_text().splitlines():
        _l = _l.strip()
        if _l and not _l.startswith("#") and "=" in _l:
            _k, _v = _l.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

import pwb_toolbox.datasets as pwb_ds

OUT = (Path(__file__).resolve().parents[2] / "data")
OUT.mkdir(exist_ok=True)
AGG = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}


def fetch(sym: str) -> None:
    t = time.time()
    df = pwb_ds.load_dataset("Stocks-1Min-Price", symbols=[sym])
    print(f"{sym}: 1-min rows={len(df):,} cols={list(df.columns)} "
          f"range {df['date'].min()} -> {df['date'].max()} ({time.time()-t:.0f}s)",
          flush=True)
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    have = [c for c in AGG if c in df.columns]
    five = df[have].resample("5min").agg({c: AGG[c] for c in have}).dropna(how="all")
    five = five[five["open"].notna()]  # drop empty (overnight) buckets
    path = OUT / f"{sym}_5min.parquet"
    five.to_parquet(path)
    print(f"{sym}: 5-min rows={len(five):,} saved -> {path}", flush=True)


if __name__ == "__main__":
    for s in ["SPY", "QQQ"]:
        fetch(s)
    print("DONE", flush=True)
