"""Freeze and run one matched experiment: candle-body versus wick zone boundaries.

The original strategies and frozen campaigns are preserved. This separate
stop-entry simulator is used because native event-v1 has no stop-entry order.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import platform
import shutil
import sys
import time
import traceback

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / 'reports/snd-body-retest-2026-09-24'
PRIOR = ROOT / 'reports/snd-fresh-retest-2026-09-24'


def now():
    return datetime.now(timezone.utc).isoformat()


def checksum(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, default=str, allow_nan=False), encoding='utf-8')


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def declare(out):
    path = out / 'protocol.json'
    if path.exists():
        return read(path)
    previous = read(PRIOR / 'protocol.json')
    cases = []
    for dataset in previous['datasets']:
        symbol = dataset['symbol']
        assert dataset['execution_minutes'] == 1
        baseline = next(c for c in previous['cases'] if c['symbol'] == symbol and c['variant'] == 'candidate')
        for variant, boundary, stress in [('wick_control', 'wick', False), ('body', 'body', False)] + (
                [('wick_double_cost', 'wick', True), ('body_double_cost', 'body', True)]
                if symbol in previous['primary_markets'] else []):
            cases.append(dict(symbol=symbol, variant=variant,
                parameters=baseline['parameters'] | {'zone_boundary': boundary},
                fee=baseline['fee'] * (2 if stress else 1),
                slippage_ticks=baseline['slippage_ticks'] * (2 if stress else 1)))
    assert len(cases) == 16
    protocol = dict(declared_at=now(), strategy='SND fresh retest: body versus wick boundaries',
        research_question='Does replacing wick zone boundaries with open/close candle-body boundaries improve the frozen fresh-retest strategy after costs?',
        user_clarification='Candle-body boundaries only. Wick touch, wick invalidation and wick FVG stay unchanged.',
        datasets=previous['datasets'], cases=cases, expected_cases=len(cases),
        primary_markets=previous['primary_markets'], transfer_markets=previous['transfer_markets'],
        capital=previous['capital'], periods=previous['periods'],
        prior_campaign=str(PRIOR), prior_protocol_checksum=checksum(PRIOR / 'protocol.json'),
        prior_manifest_checksum=checksum(PRIOR / 'source-manifest.json'),
        rules=[
            'Wick control exactly retains the frozen fresh-retest candidate; no additional filters or tuning.',
            'Body high=max(open,close); body low=min(open,close). Demand top=base body high, bottom=lowest body low of all three formation candles. Supply top=highest body high of all three, bottom=base body low.',
            'Apply body geometry to both aligned entry zones and independent opposing context zones.',
            'Keep wick-gap qualification, strict confirmed pivots and hourly direction known at each 5-minute candle open.',
            'Keep physical wick touches and wick invalidation, now evaluated against the selected boundaries. This is not close-based invalidation.',
            'Keep first-touch-only arming, next-5-minute-only stop entry one tick beyond touch-candle wick, stop one tick beyond zone distal, actual-entry 1R target and at least 2R opposing room.',
            'Keep one fixed contract, full session, 30-day warmup, 288 observed-candle expiry, 100-zone caps, identical costs and one-minute conservative execution.',
            'No Pine changes. No trading or deployment. Preserve all attempts, controls and failures.'
        ],
        comparison='Report all six markets, full history, 2024, 2025, January-July 2026 and pooled later history; compare net cash, drawdown, PF, win rate, net R, trades, risk and costs.',
        stress='True reruns doubling both commission and slippage for BOTH boundary definitions on MNQ and MGC.',
        validation='Baseline trade and equity parity against prior frozen candidate is required; verify artifact hashes, accounting, price risk, next-bar timing and geometry.',
        interpretation='This is a matched rule comparison, not a parameter search or independent validation campaign. A positive improvement is not itself a profitability/robustness pass. Changing geometry also changes trade paths and cash-risk weighting.',
        prior_exposure=previous['prior_exposure'],
        limitations='Previously inspected history; fixed contracts are not equal-risk sizing. Existing feed, incomplete-minute, unadjusted-roll, gap rejection, intraminute ordering and fill assumptions persist. No untouched holdout, broker fidelity or Working badge.')
    save(path, protocol)
    print(f'Declared {len(cases)} cases: {path}', flush=True)
    return protocol


def load_market(dataset):
    lower = pd.Timestamp(dataset['start'], tz='UTC') - pd.Timedelta(days=30)
    upper = pd.Timestamp(dataset['end'], tz='UTC')
    chunks = []
    for item in dataset['files']:
        if checksum(item['path']) != item['checksum']:
            raise ValueError('Frozen data changed: ' + item['path'])
        frame = pd.read_parquet(item['path'])
        frame.index = pd.to_datetime(frame.index, utc=True)
        chunks.append(frame.loc[(frame.index >= lower) & (frame.index < upper)].copy())
    frame = pd.concat(chunks).sort_index()
    if frame.empty or not frame.index.is_unique:
        raise ValueError('Empty or overlapping source; no silent deduplication')
    return frame


def preview(out, protocol):
    rows = []
    for dataset in protocol['datasets']:
        frame = load_market(dataset)
        prices = frame[['open', 'high', 'low', 'close']].to_numpy(float)
        assert np.isfinite(prices).all()
        assert not (prices[:, 1] < prices.max(axis=1)).any()
        assert not (prices[:, 2] > prices.min(axis=1)).any()
        assert frame.index[0] < pd.Timestamp(dataset['start'], tz='UTC')
        rows.append(dict(symbol=dataset['symbol'], source_rows=len(frame), first=str(frame.index[0]), last=str(frame.index[-1]),
                         warmup_calendar_days=(pd.Timestamp(dataset['start'], tz='UTC') - frame.index[0]).total_seconds() / 86400,
                         jobs=sum(c['symbol'] == dataset['symbol'] for c in protocol['cases'])))
    checked = dict(status='passed', checked_at=now(), protocol_checksum=checksum(out / 'protocol.json'),
                   expected_cases=len(protocol['cases']), datasets=rows,
                   note='Data checksums, OHLC, timestamps, warmup and declared jobs verified before strategy outcomes.')
    save(out / 'preview.json', checked)
    print(json.dumps(checked, indent=2), flush=True)


def freeze(out):
    if (out / 'source-manifest.json').exists():
        verify_source(out)
        return
    paths = ['strategies/_snd_body_retest.py', 'strategies/_snd_fresh_retest.py',
        'strategies/_transcript_supply_demand.py', 'scripts/research-snd-body-retest.py',
        'scripts/report-snd-fresh-retest.py',
        'scripts/report-transcript-supply-demand.py', 'scripts/analyze-transcript-supply-demand.py',
        'workbench/metrics.py', 'workbench/contract.py', 'tests/test_snd_body_retest.py',
        'tests/test_snd_fresh_retest.py', 'tests/test_transcript_supply_demand.py']
    paths += [str(p.relative_to(ROOT)).replace('\\', '/') for p in (ROOT / 'strategy_engine').glob('*.py')]
    missing = [p for p in paths if not (ROOT / p).is_file()]
    if missing:
        raise FileNotFoundError('Complete source before freezing: ' + ', '.join(missing))
    files = []
    for relative in paths:
        source, destination = ROOT / relative, out / 'source' / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        files.append(dict(path=relative, checksum=checksum(source)))
    digest = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
    save(out / 'source-manifest.json', dict(frozen_at=now(), protocol_checksum=checksum(out / 'protocol.json'), source_hash=digest, files=files))
    save(out / 'environment.json', dict(python=sys.version, platform=platform.platform(), numpy=np.__version__, pandas=pd.__version__))
    print('Frozen source ' + digest, flush=True)


def verify_source(out):
    manifest = read(out / 'source-manifest.json')
    assert manifest['protocol_checksum'] == checksum(out / 'protocol.json'), 'Protocol changed'
    for item in manifest['files']:
        assert checksum(out / 'source' / item['path']) == item['checksum'], 'Snapshot changed: ' + item['path']
        assert checksum(ROOT / item['path']) == item['checksum'], 'Working source changed: ' + item['path']
    return manifest


def run_market(out_name, dataset):
    out = Path(out_name)
    protocol, manifest = read(out / 'protocol.json'), verify_source(out)
    sys.path.insert(0, str(out / 'source'))
    spec = importlib.util.spec_from_file_location('frozen_body_model', out / 'source/strategies/_snd_body_retest.py')
    model = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(model)
    frame = load_market(dataset)
    prepared = model.prepare_data(frame, pivot_len=2, execution_minutes=1)
    outcomes = []
    for case in [c for c in protocol['cases'] if c['symbol'] == dataset['symbol']]:
        folder = out / case['symbol'] / case['variant']
        if (folder / 'result.json').exists():
            outcomes.append(read(folder / 'result.json')['status'])
            print(f'{case["symbol"]}/{case["variant"]}: existing attempt preserved', flush=True)
            continue
        if folder.exists() and any(folder.iterdir()):
            raise RuntimeError('Interrupted attempt preserved; choose a new output directory: ' + str(folder))
        folder.mkdir(parents=True, exist_ok=True)
        started, clock = now(), time.monotonic()
        identity = dict(protocol_checksum=manifest['protocol_checksum'], source_hash=manifest['source_hash'])
        save(folder / 'input.json', dict(**case, dataset=dataset, **identity))
        save(folder / 'status.json', dict(status='running', started_at=started))
        try:
            result = model.run_model(prepared, case['parameters'], dataset['start'], dataset['end'],
                                     dataset['tick_size'], dataset['point_value'], case['fee'], case['slippage_ticks'])
            trades, equity = result['trades'], result['equity']
            assert len(equity) > 0
            np.testing.assert_allclose(equity.equity.iloc[-1] - protocol['capital'], trades.net_pnl.sum(), atol=1e-5, rtol=0)
            np.testing.assert_allclose(equity.net_pnl.sum(), trades.net_pnl.sum(), atol=1e-5, rtol=0)
            np.testing.assert_allclose(trades.gross_pnl - trades.cost, trades.net_pnl, atol=1e-7, rtol=0)
            assert equity.contracts.iloc[-1] == 0
            trades.to_csv(folder / 'trades.csv', index=False)
            equity.to_parquet(folder / 'equity.parquet', index=False)
            artifacts = [dict(name=name, checksum=checksum(folder / name)) for name in ['trades.csv', 'equity.parquet']]
            payload = dict(status='succeeded', symbol=case['symbol'], variant=case['variant'], started_at=started,
                           completed_at=now(), elapsed_seconds=time.monotonic() - clock,
                           parameters=result['parameters'], diagnostics=result['diagnostics'], artifacts=artifacts, **identity)
            save(folder / 'result.json', payload)
            save(folder / 'status.json', dict(status='succeeded', completed_at=payload['completed_at']))
            print(f'{case["symbol"]}/{case["variant"]}: {len(trades)} trades; net ${trades.net_pnl.sum():,.2f}; {payload["elapsed_seconds"]:.1f}s', flush=True)
            outcomes.append('succeeded')
        except Exception as error:
            (folder / 'error.log').write_text(traceback.format_exc(), encoding='utf-8')
            save(folder / 'result.json', dict(status='failed', symbol=case['symbol'], variant=case['variant'],
                 started_at=started, completed_at=now(), error=str(error), artifacts=[], **identity))
            print(f'{case["symbol"]}/{case["variant"]}: FAILED {error}', flush=True)
            outcomes.append('failed')
    return dict(symbol=dataset['symbol'], statuses=outcomes)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=DEFAULT_OUT)
    for action in ('declare', 'preview', 'freeze', 'run'):
        parser.add_argument('--' + action, action='store_true')
    parser.add_argument('--workers', type=int, default=2, choices=[1, 2])
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    protocol = declare(out) if args.declare else read(out / 'protocol.json')
    if args.preview:
        preview(out, protocol)
    if args.freeze:
        freeze(out)
    if args.run:
        manifest = verify_source(out)
        checked = read(out / 'preview.json')
        assert checked['status'] == 'passed' and checked['protocol_checksum'] == manifest['protocol_checksum']
        summaries = []
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            jobs = [pool.submit(run_market, str(out), d) for d in protocol['datasets']]
            for job in as_completed(jobs):
                result = job.result()
                summaries.append(result)
                print(json.dumps(result), flush=True)
        save(out / 'completion.json', dict(completed_at=now(), markets=summaries))
        if any(s != 'succeeded' for r in summaries for s in r['statuses']):
            raise SystemExit(1)
        print('All declared cases completed. Run report-snd-body-retest.py --require-complete.', flush=True)


if __name__ == '__main__':
    main()
