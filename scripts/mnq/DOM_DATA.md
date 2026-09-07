# MNQ candle history and DOM samples

The archive lives in `data/mnq_dom_sample/` and is excluded from Git. It uses
Databento `GLBX.MDP3`, `MNQ.v.0` (highest previous-day volume), and unadjusted
prices with original instrument IDs.

| Data | Requested interval |
| --- | --- |
| One-minute OHLCV | May 5, 2019 22:00 UTC through September 4, 2026 00:00 UTC, end exclusive |
| Ten-level DOM (`mbp-10`) | July 8–12, 2024 trading week |
| Ten-level DOM (`mbp-10`) | February 10–14, 2025 trading week |
| Ten-level DOM (`mbp-10`) | August 17–21, 2026 trading week |

Each DOM week includes the Sunday 18:00 New York open through Friday 17:00
New York close. The 2025 week was randomly selected with seed `2026082025`;
the additional 2024 week used seed `2026082024`. Selection was uniform among
Monday–Friday weeks contained in each calendar year, without examining price
or strategy results. Reserve the 2024 week for a final check after strategy
rules are fixed; three weeks are a development sample, not broad validation.

## Files and loading

- `full_history/ohlcv-1m/candles_1m.parquet`: complete exported candle table.
- `<week>/mbp-10/<job-id>/*.dbn.zst`: original daily compressed DOM files.
- Each schema directory retains `job.json` with the paid batch job ID.
- `estimate.json` records the exact requests, estimates, random seeds, and
  continuous-symbol mappings; `contract_symbols.json` resolves dated instrument
  IDs to actual exchange contract symbols.
- After verification, `validation.json` records checksums, record counts,
  coverage, instrument consistency, and provider-reported charges.

Run these examples from the repository root using `.venv/bin/python`:

Install the recorded dependencies with
`.venv/bin/python -m pip install -r scripts/mnq/requirements-dom.txt` if recreating
the environment.

```python
from pathlib import Path
import databento as db
import pandas as pd

root = Path("data/mnq_dom_sample")
candles = pd.read_parquet(root / "full_history/ohlcv-1m/candles_1m.parquet")

for file in sorted((root / "2024-07-08/mbp-10").glob("*/*.dbn.zst")):
    for chunk in db.DBNStore.from_file(file).to_df(count=100_000):
        # UTC ts_recv index; ts_event and instrument_id are retained.
        # bid_ct_00...09 / ask_ct_00...09 are waiting order counts.
        # bid_sz_00...09 / ask_sz_00...09 are waiting contract quantities.
        # Process one chunk at a time; avoid loading the full DOM into memory.
        pass
```

Candle timestamps mark interval starts. A one-minute candle becomes complete
one minute after its timestamp. DOM has both event and receive timestamps;
the SDK uses `ts_recv` as its DataFrame index. Keep the timing choice explicit
when joining signals and never use completed-candle information before close.

Prices remain unadjusted. Do not aggregate a candle, carry a zone, or join DOM
across a change of instrument ID without an explicit rollover rule. Waiting
order counts and quantities cover only the ten displayed levels on each side;
they do not measure executed volume or hidden liquidity.

## Reusing the archive

`fetch_dom_sample.py estimate` calls only free metadata endpoints.
`fetch_dom_sample.py download --max-cost-usd APPROVED_AMOUNT` purchases only
missing requests, retains job IDs, and reuses existing downloads. The cap is a
check against the current estimate, not a provider-enforced billing limit.
Never delete `job.json` to resolve a failed download: that can cause a duplicate
purchase. An uncertain submission must be reconciled with the Download center
before retrying.

`verify_dom_sample.py` uses free metadata to verify every file against provider
hashes, scans the complete DOM archive for timestamp coverage and instrument
IDs, and checks candles for duplicates and invalid OHLC. Quote consistency
checks within that scan are sampled; the report does not assert that every
market-data event is economically correct.
