"""Full-history fixed-one risk/reference parity for eight predeclared controls.

Four declared markets cross the unchanged wick baseline and strict body zones.
No winner is selected and no performance ranking is performed by this checker.
Each engine prepares its own raw data; complete prior trade columns and every
equity row must match exactly, including dtypes. Failed attempts are preserved.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import time
import traceback

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def checksum(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False), encoding='utf-8')


def stamp():
    return datetime.now(timezone.utc).isoformat()


def market_check(dataset, parameters, output):
    from strategies import _snd_combination_reference as reference
    from strategies import _snd_combination_risk as risk
    begin = time.monotonic()
    low = pd.Timestamp(dataset['start'], tz='UTC') - pd.Timedelta(days=30)
    high = pd.Timestamp(dataset['end'], tz='UTC')
    records, sources = [], []
    try:
        frames = []
        for item in dataset['files']:
            digest = checksum(item['path'])
            if digest != item['checksum']:
                raise ValueError('Raw data checksum mismatch: ' + item['path'])
            sources.append(dict(path=item['path'], checksum=digest))
            frame = pd.read_parquet(item['path'])
            frame.index = pd.to_datetime(frame.index, utc=True)
            frames.append(frame.loc[(frame.index >= low) & (frame.index < high)].copy())
        source = pd.concat(frames).sort_index()
        if source.empty or not source.index.is_unique:
            raise ValueError('Raw interval must be nonempty and have unique timestamps')
        first = reference.prepare_data(source, pivot_len=parameters['pivot_len'], execution_minutes=1)
        second = risk.prepare_data(source, pivot_len=parameters['pivot_len'], execution_minutes=1)
        for name in ('source', 'chart', 'hourly'):
            pd.testing.assert_frame_equal(first[name], second[name], check_exact=True, check_dtype=True)
        for variant, changes in [('wick_baseline', dict(zone_boundary='wick', require_fvg=False)),
                                 ('body_strict', dict(zone_boundary='body', require_fvg=True))]:
            p = dict(parameters, **changes)
            p.update(max_zone_width_atr=None, min_departure_atr=None, min_departure_rvol=None, max_touch_age_hours=None)
            started = time.monotonic()
            row = dict(symbol=dataset['symbol'], variant=variant, parameters=p,
                risk_parameters=dict(p, sizing_mode='fixed_contracts', contracts=1), start=dataset['start'], end=dataset['end'],
                fee=dataset['fee'], slippage_ticks=1)
            try:
                args = (p, dataset['start'], dataset['end'], dataset['tick_size'], dataset['point_value'], dataset['fee'], 1)
                old = reference.run_model(first, *args)
                new = risk.run_model(second, row['risk_parameters'], *args[1:])
                pd.testing.assert_frame_equal(old['trades'], new['trades'].loc[:, old['trades'].columns], check_exact=True, check_dtype=True)
                pd.testing.assert_frame_equal(old['equity'], new['equity'], check_exact=True, check_dtype=True)
                row.update(status='passed', trades=len(old['trades']), equity_rows=len(old['equity']),
                    common_trade_columns=list(old['trades'].columns), equity_columns=list(old['equity'].columns),
                    checked_prepared_frames=['source', 'chart', 'hourly'], detected_rolls=old['diagnostics']['detected_rolls'])
            except Exception:
                row.update(status='failed', error=traceback.format_exc())
            row['elapsed_seconds'] = time.monotonic() - started
            records.append(row)
            print(dataset['symbol'] + '/' + variant + ': ' + row['status'], flush=True)
        for item in sources:
            if checksum(item['path']) != item['checksum']:
                raise ValueError('Raw source changed during parity run: ' + item['path'])
        result = dict(symbol=dataset['symbol'], status='passed' if all(r['status']=='passed' for r in records) else 'failed',
                      records=records, raw_sources=sources, source_rows=len(source), elapsed_seconds=time.monotonic()-begin)
    except Exception:
        result = dict(symbol=dataset['symbol'], status='failed', records=records, raw_sources=sources,
                      error=traceback.format_exc(), elapsed_seconds=time.monotonic()-begin)
    destination = Path(output) / (dataset['symbol'] + '.json')
    save(destination, result)
    result['artifact'], result['artifact_checksum'] = str(destination), checksum(destination)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT/'reports/snd-combinations-2026-09-26')
    parser.add_argument('--workers', type=int, choices=(1,2,3,4), default=4)
    args = parser.parse_args()
    out = args.output.resolve()
    protocol = read(out/'protocol.json')
    configurations = read(out/'configurations.json')
    baseline = next(c['parameters'] for c in configurations if c['config_id']=='c00000')
    paths = ['scripts/check-snd-combination-risk.py', 'strategies/_snd_combination_reference.py', 'strategies/_snd_combination_risk.py']
    paths += sorted(str(p.relative_to(ROOT)).replace('\\','/') for p in (ROOT/'strategy_engine').glob('*.py'))
    hashes = {p:checksum(ROOT/p) for p in paths}
    started = stamp()
    attempt = out/'risk-reference-parity'/('attempt-'+started.replace(':','').replace('.',''))
    records = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(market_check, d, baseline, str(attempt)):d['symbol'] for d in protocol['datasets']}
        for future in as_completed(futures):
            try:
                records.append(future.result())
            except Exception:
                records.append(dict(symbol=futures[future], status='failed', records=[], error=traceback.format_exc()))
    records.sort(key=lambda r:protocol['markets'].index(r['symbol']))
    unchanged = hashes == {p:checksum(ROOT/p) for p in paths}
    cases = [case for market in records for case in market['records']]
    complete = len(cases)==8 and {r['symbol'] for r in records}==set(protocol['markets'])
    result = dict(status='passed' if unchanged and complete and all(r['status']=='passed' for r in records) else 'failed',
        started_at=started, completed_at=stamp(), protocol_checksum=checksum(out/'protocol.json'),
        configurations_checksum=checksum(out/'configurations.json'), source_files=hashes, source_unchanged=unchanged,
        expected_cases=8, executed_cases=len(cases), passed_cases=sum(r['status']=='passed' for r in cases),
        records=cases, markets=records,
        scope='Full-history fixed-one parity on four declared markets crossed with wick baseline and strict body zones, quality filters disabled. Each engine independently prepares raw candles. Every common trade value, dtype and equity row matches exactly; no candidate is selected.')
    save(attempt/'result.json', result)
    save(out/'risk-reference-parity.json', result)
    print(json.dumps({k:result[k] for k in ('status','expected_cases','executed_cases','passed_cases')}, indent=2), flush=True)
    return 0 if result['status']=='passed' else 1


if __name__=='__main__':
    raise SystemExit(main())
