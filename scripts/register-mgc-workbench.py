"""Register the preserved MGC minute cache as an immutable Workbench dataset.

The local five-minute file is the full-series parity oracle. This script performs
no download, and it is intentionally separate from the live API's registration.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from workbench.contract import checksum
from workbench.datasets import logical_dataset_path


SOURCE_PATTERN = 'MGC.v.0_*_1m.parquet'
REFERENCE = 'data/MGC_5min_databento.parquet'
VERSION_SUFFIX = '-mgc-cache-v1'
FIELDS = ['open', 'high', 'low', 'close', 'volume']


def _cache(root: Path):
    paths = sorted((root / 'data/_dbn_cache').glob(SOURCE_PATTERN))
    if not paths:
        raise ValueError('No preserved MGC.v.0 one-minute cache shards')
    manifest = [[path.relative_to(root).as_posix(), checksum(path)] for path in paths]
    fingerprint = hashlib.sha256(json.dumps(manifest, separators=(',', ':')).encode()).hexdigest()
    frames = []
    previous = None
    for path in paths:
        frame = pd.read_parquet(path)
        if (frame.empty or frame.index.name != 'ts_event' or str(frame.index.tz) != 'UTC' or
                not frame.index.is_unique or not frame.index.is_monotonic_increasing or
                not set(FIELDS).issubset(frame.columns) or
                (previous is not None and frame.index[0] <= previous)):
            raise ValueError(f'Invalid MGC minute cache shard: {path.name}')
        if (frame.index.asi8 % 60_000_000_000 != 0).any():
            raise ValueError(f'Non-minute timestamps in MGC cache shard: {path.name}')
        prices = frame[['open', 'high', 'low', 'close']]
        if (not np.isfinite(frame[FIELDS].to_numpy()).all() or
                (prices <= 0).any().any() or (frame.volume < 0).any() or
                (frame.high < prices.max(axis=1)).any() or
                (frame.low > prices.min(axis=1)).any()):
            raise ValueError(f'Invalid MGC OHLCV in cache shard: {path.name}')
        previous = frame.index[-1]
        frames.append(frame[FIELDS])
    return pd.concat(frames), manifest, fingerprint


def _assert_five_minute_parity(minute: pd.DataFrame, reference: Path):
    if not reference.is_file():
        raise ValueError('MGC five-minute reference is missing')
    expected = pd.read_parquet(reference)
    if (expected.empty or not expected.index.is_unique or
            not expected.index.is_monotonic_increasing or
            not set(FIELDS).issubset(expected.columns)):
        raise ValueError('Invalid MGC five-minute reference')
    actual = minute.tz_convert('US/Eastern').resample('5min').agg({
        'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last',
        'volume': 'sum',
    }).dropna(subset=['open'])
    if (not actual.index.equals(expected.index) or
            not np.array_equal(actual[FIELDS].to_numpy(), expected[FIELDS].to_numpy())):
        raise ValueError('MGC minute cache does not reproduce the five-minute reference')


def register(root: Path, destination: Path):
    root, destination = root.resolve(), destination.resolve()
    minute, shards, fingerprint = _cache(root)
    reference = root / REFERENCE
    _assert_five_minute_parity(minute, reference)
    reference_digest = checksum(reference)
    version = fingerprint + VERSION_SUFFIX
    folder = destination / version
    final = folder / 'bars.parquet'
    manifest_path = folder / 'dataset.json'
    if manifest_path.exists():
        record = json.loads(manifest_path.read_text(encoding='utf-8'))
        if (record.get('id') != version or
                record.get('provenance', {}).get('reference_sha256') != reference_digest or
                record.get('provenance', {}).get('source_shards') != shards or
                not final.is_file() or checksum(final) != record.get('checksum')):
            raise ValueError('Existing immutable MGC dataset no longer matches its source or manifest')
    else:
        folder.mkdir(parents=True, exist_ok=True)
        partial = folder / 'bars.partial.parquet'
        minute.to_parquet(partial, compression='zstd')
        if not pd.read_parquet(partial, columns=['open']).index.equals(minute.index):
            partial.unlink(missing_ok=True)
            raise ValueError('MGC cached dataset lost timestamps during publication')
        os.replace(partial, final)
        record = {
            'schema_version': 2,
            'id': version, 'symbol': 'MGC',
            'source': 'Preserved local Databento MGC.v.0 minute cache',
            'path': logical_dataset_path(destination, final),
            'checksum': checksum(final),
            'archive': REFERENCE, 'archive_checksum': reference_digest,
            'rows': len(minute), 'first': minute.index[0].isoformat(),
            'last': minute.index[-1].isoformat(),
            'timeframe': '1m', 'timezone': 'UTC', 'session': 'CME Globex',
            'currency': 'USD', 'tick_size': 0.1, 'point_value': 10.,
            'registered_at': datetime.now(timezone.utc).isoformat(),
            'query': {'dataset': 'GLBX.MDP3', 'schema': 'ohlcv-1m',
                      'symbols': ['MGC.v.0'],
                      'provenance': 'Existing local cache; vendor receipt unavailable'},
            'provenance': {'source_shards': shards, 'source_fingerprint': fingerprint,
                           'reference_sha256': reference_digest,
                           'five_minute_parity': 'all timestamps and OHLCV values exact'},
            'quality': {'duplicates': 0, 'unordered': 0, 'invalid_ohlc': 0,
                        'gaps_over_one_minute': int((minute.index.to_series().diff() >
                                                    pd.Timedelta(minutes=1)).sum())},
            'warnings': [
                'Original Databento acquisition receipt and historical revisions are not verified.',
                'Continuous volume-rolled prices are unadjusted; the cache lacks instrument_id, so roll timing cannot be audited.',
                'No-trade minutes and exchange closures are absent; five-minute source parity does not prove quote completeness.',
            ],
        }
        temporary = folder / 'dataset.partial.json'
        temporary.write_text(json.dumps(record, indent=2), encoding='utf-8')
        os.replace(temporary, manifest_path)
    destination.mkdir(parents=True, exist_ok=True)
    catalog_path = destination / 'catalog.json'
    catalog = json.loads(catalog_path.read_text(encoding='utf-8')) if catalog_path.exists() else {
        'datasets': [], 'errors': [],
    }
    existing = next((row for row in catalog['datasets'] if row['id'] == version), None)
    if existing is not None and existing.get('checksum') != record['checksum']:
        raise ValueError('Catalog MGC dataset checksum conflicts with immutable manifest')
    catalog['datasets'] = [row for row in catalog['datasets'] if row['id'] != version] + [record]
    temporary_catalog = destination / 'catalog.partial.json'
    temporary_catalog.write_text(json.dumps(catalog, indent=2), encoding='utf-8')
    os.replace(temporary_catalog, catalog_path)
    return record


if __name__ == '__main__':
    record = register(ROOT, ROOT / 'data/workbench/datasets')
    print(json.dumps({'id': record['id'], 'symbol': record['symbol'],
                      'rows': record['rows'], 'checksum': record['checksum']}))
