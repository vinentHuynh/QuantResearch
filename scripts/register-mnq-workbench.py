"""Register the existing MNQ minute cache as a checksummed workbench dataset.

Run from the repository root with the project Python. No download is performed.
"""
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import shutil
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from workbench.contract import checksum


def main():
    source = ROOT / 'data/mnq_dom_sample/full_history/ohlcv-1m/candles_1m.parquet'
    destination = ROOT / 'data/workbench/datasets'
    digest = checksum(source)
    version = digest + '-mnq-cache-v1'
    folder = destination / version
    manifest = folder / 'dataset.json'
    if manifest.exists():
        record = json.loads(manifest.read_text(encoding='utf-8'))
        if checksum(record['path']) != record['checksum']:
            raise ValueError('Registered MNQ cache checksum mismatch')
    else:
        frame = pd.read_parquet(source)
        prices = frame[['open', 'high', 'low', 'close']]
        if frame.empty or frame.index.name != 'ts_event' or str(frame.index.tz) != 'UTC':
            raise ValueError('Expected nonempty UTC ts_event minute data')
        if frame.index.has_duplicates or not frame.index.is_monotonic_increasing:
            raise ValueError('Unordered or duplicated MNQ timestamps')
        if not np.isfinite(prices.to_numpy()).all() or not np.isfinite(frame.volume).all() or (frame.volume < 0).any():
            raise ValueError('Invalid MNQ price or volume')
        if (frame.high < prices.max(axis=1)).any() or (frame.low > prices.min(axis=1)).any():
            raise ValueError('Inconsistent MNQ OHLC')
        folder.mkdir(parents=True, exist_ok=True)
        partial = folder / 'bars.partial.parquet'
        shutil.copyfile(source, partial)
        if checksum(partial) != digest:
            raise ValueError('MNQ cache changed during registration')
        final = folder / 'bars.parquet'
        os.replace(partial, final)
        record = {
            'id': version, 'symbol': 'MNQ', 'source': 'Local MNQ historical cache',
            'path': str(final.resolve()), 'checksum': digest,
            'archive': source.relative_to(ROOT).as_posix(), 'archive_checksum': digest,
            'rows': len(frame), 'first': frame.index[0].isoformat(), 'last': frame.index[-1].isoformat(),
            'timeframe': '1m', 'timezone': 'UTC', 'session': 'CME Globex', 'currency': 'USD',
            'tick_size': .25, 'point_value': 2.,
            'query': {'symbols': ['MNQ'], 'schema': 'ohlcv-1m', 'provenance': 'Existing local cache; original vendor request not reconstructed'},
            'acquired_at': datetime.fromtimestamp(source.stat().st_mtime, timezone.utc).isoformat(),
            'registered_at': datetime.now(timezone.utc).isoformat(),
            'quality': {'duplicates': 0, 'unordered': 0, 'invalid_ohlc': 0,
                        'gaps_over_one_minute': int((frame.index.to_series().diff() > pd.Timedelta(minutes=1)).sum()),
                        'contract_changes': int((frame.instrument_id.diff().iloc[1:] != 0).sum())},
            'warnings': ['Registered from the existing MNQ cache. Original vendor query and acquisition receipt are not verified.',
                         'Continuous unadjusted contracts: roll gaps can affect signals and P&L.',
                         'Missing minutes include closures and no-trade minutes; no holiday-calendar completeness claim.'],
        }
        manifest.write_text(json.dumps(record, indent=2), encoding='utf-8')
    catalog_path = destination / 'catalog.json'
    catalog = json.loads(catalog_path.read_text(encoding='utf-8')) if catalog_path.exists() else {'datasets': [], 'errors': []}
    catalog['datasets'] = [d for d in catalog['datasets'] if d['id'] != version] + [record]
    partial_catalog = destination / 'catalog.partial.json'
    partial_catalog.write_text(json.dumps(catalog, indent=2), encoding='utf-8')
    os.replace(partial_catalog, catalog_path)
    print(json.dumps({'id': version, 'symbol': 'MNQ', 'rows': record['rows']}))


if __name__ == '__main__':
    main()
