"""Verify PWB environment: load .env, pull a small dataset, compute a metric."""
import os
from pathlib import Path

# minimal .env loader (no extra dependency)
env = Path(__file__).with_name(".env")
if env.exists():
    for line in env.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

import pwb_toolbox.datasets as pwb_ds
from pwb_toolbox.performance.metrics import sharpe_ratio, cagr, max_drawdown

df = pwb_ds.load_dataset("Stocks-Daily-Price", symbols=["AAPL", "MSFT"])
print("rows:", len(df))
print(df.tail(3).to_string())

prices = pwb_ds.get_pricing(["SPY"], fields=["close"], start_date="2015-01-01")
vals = prices["close"].dropna().tolist() if "close" in prices else prices.iloc[:, 0].dropna().tolist()
print("SPY points:", len(vals))
print("SPY buy-hold sharpe:", round(sharpe_ratio(vals), 3))
print("SPY cagr:", round(cagr(vals), 4))
depth, dur = max_drawdown(vals)
print("SPY max drawdown:", round(abs(depth), 4))
print("OK — environment works.")
