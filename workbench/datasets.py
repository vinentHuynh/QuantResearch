"""Stream Databento daily ZIP members into immutable Parquet versions."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZipFile

import databento as db
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from .contract import checksum

ECONOMICS = {'NQ': (.25, 20), 'ES': (.25, 50), 'YM': (1, 5), 'CL': (.01, 1000)}
IMPORT_VERSION = '1'


def ingest(root, destination):
    destination.mkdir(parents=True, exist_ok=True)
    records, errors = [], []
    for archive in sorted((root / 'data').rglob('*.zip')):
        try:
            digest = checksum(archive)
            version = digest + '-v' + IMPORT_VERSION
            folder = destination / version
            manifest = folder / 'dataset.json'
            if manifest.exists():
                records.append(json.loads(manifest.read_text()))
                print(f'Already registered: {archive.name}', flush=True)
                continue
            with ZipFile(archive) as zip_file:
                metadata = json.loads(zip_file.read('metadata.json'))
                query = metadata['query']
                if query['schema'] != 'ohlcv-1m' or len(query['symbols']) != 1:
                    raise ValueError('Adapter requires one continuous symbol and ohlcv-1m')
                symbol = query['symbols'][0].split('.')[0]
                if symbol not in ECONOMICS:
                    raise ValueError(f'Add explicit tick size and point value for {symbol}')
                folder.mkdir(exist_ok=True)
                temporary = folder / 'bars.partial.parquet'
                writer, previous, previous_id, first, rows, gaps, rolls = None, None, None, None, 0, 0, 0
                members = sorted(n for n in zip_file.namelist() if n.endswith('.dbn.zst'))
                if not members:
                    raise ValueError('Archive contains no DBN bars')
                try:
                    for i, name in enumerate(members):
                        frame = db.DBNStore.from_bytes(zip_file.read(name)).to_df()
                        if frame.empty:
                            continue
                        frame = frame[['open', 'high', 'low', 'close', 'volume', 'instrument_id']]
                        if not frame.index.is_monotonic_increasing or frame.index.has_duplicates:
                            raise ValueError(f'Unordered or duplicated timestamps in {name}')
                        if previous is not None and frame.index[0] <= previous:
                            raise ValueError(f'Overlapping members at {name}')
                        prices = frame[['open', 'high', 'low', 'close']]
                        if not np.isfinite(prices.to_numpy()).all() or (frame.volume < 0).any():
                            raise ValueError(f'Nonfinite OHLC or negative volume in {name}')
                        if (frame.high < prices.max(axis=1)).any() or (frame.low > prices.min(axis=1)).any():
                            raise ValueError(f'Inconsistent OHLC in {name}')
                        gaps += int((frame.index.to_series().diff() > pd.Timedelta(minutes=1)).sum())
                        if previous is not None and frame.index[0] - previous > pd.Timedelta(minutes=1):
                            gaps += 1
                        rolls += int((frame.instrument_id.diff().iloc[1:] != 0).sum())
                        if previous_id is not None and frame.instrument_id.iloc[0] != previous_id:
                            rolls += 1
                        previous_id = frame.instrument_id.iloc[-1]
                        first = first or frame.index[0].isoformat()
                        previous = frame.index[-1]
                        table = pa.Table.from_pandas(frame)
                        if writer is None:
                            writer = pq.ParquetWriter(temporary, table.schema, compression='zstd')
                        writer.write_table(table)
                        rows += len(frame)
                        if i % 500 == 0:
                            print(f'{symbol}: {i + 1}/{len(members)} daily files, {rows:,} bars', flush=True)
                finally:
                    if writer:
                        writer.close()
                if not rows:
                    raise ValueError('Empty dataset')
                final = folder / 'bars.parquet'
                os.replace(temporary, final)
                tick, point = ECONOMICS[symbol]
                record = {
                    'id': version, 'symbol': symbol, 'source': query['dataset'],
                    'path': str(final.resolve()), 'checksum': checksum(final),
                    'archive': str(archive.relative_to(root)), 'archive_checksum': digest,
                    'rows': rows, 'first': first, 'last': previous.isoformat(),
                    'timeframe': '1m', 'timezone': 'UTC', 'session': 'CME Globex', 'currency': 'USD',
                    'tick_size': tick, 'point_value': point, 'query': query,
                    'acquired_at': datetime.fromtimestamp(archive.stat().st_mtime, timezone.utc).isoformat(),
                    'registered_at': datetime.now(timezone.utc).isoformat(),
                    'quality': {'duplicates': 0, 'unordered': 0, 'invalid_ohlc': 0, 'gaps_over_one_minute': gaps, 'contract_changes': rolls},
                    'warnings': [
                        'Continuous volume-rolled prices are unadjusted. Roll gaps can affect signals and P&L; no roll-neutral performance claim.',
                        'Gaps include closures and no-trade minutes; an exchange holiday calendar and historical revision timestamps are unavailable.',
                        'Acquisition time uses local archive modification time, not a verified vendor download receipt.',
                    ],
                }
                manifest.write_text(json.dumps(record, indent=2), encoding='utf-8')
                records.append(record)
                print(f'Registered {symbol}: {rows:,} bars', flush=True)
        except Exception as exc:
            errors.append({'archive': str(archive), 'error': str(exc)})
            print(f'Import error: {archive.name}: {exc}', flush=True)
    result = {'datasets': records, 'errors': errors}
    (destination / 'catalog.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    return result


if __name__ == '__main__':
    import sys
    ingest(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve())
