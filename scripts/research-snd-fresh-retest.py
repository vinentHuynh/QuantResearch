"""Declare, preview, freeze, and execute the new SND fresh-retest experiment.

No parameter selection or broker access. Existing strategies and runs remain
untouched. Stop entries require the separately preserved research simulator.
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
DEFAULT_OUT = ROOT / 'reports/snd-fresh-retest-2026-09-24'
BASE = dict(pivot_len=2, stop_model='zone', rr=1.0, use_htf=True,
            require_fvg=True, max_age=288, max_active=100,
            first_touch_only=True, min_opposing_room_r=2.0,
            execution_minutes=1, warmup_days=30, capital=100000.0)
COMMON = {'candidate': {}, 'without_first_touch': {'first_touch_only': False},
          'without_room': {'min_opposing_room_r': 0.0},
          'legacy_control': {'first_touch_only': False, 'min_opposing_room_r': 0.0}}
EXTRA = {'without_hourly': {'use_htf': False}, 'without_fvg': {'require_fvg': False},
         'pivot_1': {'pivot_len': 1}, 'pivot_3': {'pivot_len': 3},
         'target_075': {'rr': .75}, 'target_125': {'rr': 1.25},
         'double_cost': {}, 'extra_slippage': {}}


def now():
    return datetime.now(timezone.utc).isoformat()


def checksum(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, default=str, allow_nan=False), encoding='utf-8')


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def declare(out):
    path = out / 'protocol.json'
    if path.exists():
        return read(path)
    previous = read(ROOT / 'reports/transcript-supply-demand-2026-09-24/protocol.json')
    symbols = ['MNQ', 'MGC', 'NQ', 'ES', 'YM', 'CL']
    datasets = [next(d for d in previous['datasets'] if d['symbol'] == symbol) for symbol in symbols]
    for dataset in datasets:
        assert dataset['execution_minutes'] == 1
        for item in dataset['files']:
            if checksum(item['path']) != item['checksum']:
                raise ValueError('Dataset identity mismatch: ' + item['path'])
    cases = []
    for dataset in datasets:
        variants = COMMON | (EXTRA if dataset['symbol'] in ['MNQ', 'MGC'] else {})
        for name, changes in variants.items():
            cases.append(dict(symbol=dataset['symbol'], variant=name,
                              parameters=BASE | changes,
                              fee=dataset['fee'] * (2 if name == 'double_cost' else 1),
                              slippage_ticks=2 if name in ['double_cost', 'extra_slippage'] else 1))
    protocol = dict(declared_at=now(), strategy='SND fresh retest with hourly alignment',
        research_question='Do a strict first-touch entry and opposing room improve the transcript baseline after costs, without choosing a winning market or parameter retrospectively?',
        primary_markets=['MNQ', 'MGC'], transfer_markets=['NQ', 'ES', 'YM', 'CL'],
        excluded_market='GC omitted because its five-minute execution history is not comparable to the six one-minute series.',
        datasets=datasets, cases=cases, expected_cases=len(cases), capital=100000.0,
        periods={'development': ['2022-01-01', '2025-01-01'],
                 'year_2024': ['2024-01-01', '2025-01-01'],
                 'later_2025': ['2025-01-01', '2026-01-01'],
                 'latest_2026': ['2026-01-01', '2026-08-01'],
                 'later_combined': ['2025-01-01', '2026-08-01']},
        prior_exposure='All scored dates have already been inspected in prior research. No untouched holdout or prospective validation claim. New rules are frozen before this campaign and are not retuned after results.',
        rules=[
            'Completed consecutive five-minute transcript formations; causal two-sided pivots; hourly direction from the hour completed at the chart candle open.',
            'Entry zone forms only with aligned five-minute and hourly direction; entry arming also requires alignment.',
            'Demand uses bearish base, bullish middle and third-candle wick gap; supply mirrors. No additional BOS, high volume, RVOL, impulse-size or width requirement.',
            'First physical chart-candle overlap consumes freshness, including warmup, busy, misaligned and incomplete candles. Formation candle cannot touch its own zone.',
            'Only a complete first-touch candle may arm an entry: buy one tick above its high or sell one tick below its low. The order lives for the next five-minute bucket only and cannot rearm later.',
            'Zone-based stop one tick beyond distal; 1R target from actual gap-adjusted entry. No automatic opposing-zone exit.',
            'Off-grid targets in new-strategy configurations are rounded toward entry to an executable tick and effective RR is recorded. The legacy control retains exact original arithmetic for parity.',
            'Separate opposing-context zones use the same formation geometry regardless directional alignment. Nearest opposing proximal ahead of entry is the obstacle; overlap means zero room.',
            'Require at least 2 actual stop-risk units to the obstacle, or no obstacle. Freeze the obstacle at arming and recheck against the actual gap-adjusted entry.',
            'One fixed contract, one open position, full trading-day session, 288 observed-chart-bucket zone expiry, 100-zone caps, 30 calendar days warmup, final liquidation.',
            'Control without first touch retains the transcript rolling-entry mechanism. Control with both new filters off must reproduce prior transcript trade/accounting behavior.',
            'One-minute stop/target chronology; ambiguous intraminute collisions favor stops. Unknown favorable movement on an intrabar entry candle is not credited.',
            'Inherited contract-roll handling is an idealized prior-close adjustment, not a causal tradable roll order. Gold has no retained IDs; unknown rolls remain a limitation.'
        ],
        fees='Per contract per side: MNQ/MGC $1.25, NQ/ES/YM/CL $2.50. One adverse tick cash charge on entry and stop/market exit, commission only on target limits.',
        stress='Actual full reruns on both primaries with double fees and slippage; separate reruns with two ticks but base commission. Fixed-size decisions are cost independent; arithmetic repricing is also checked.',
        primary_gates=['positive full-history net P&L', 'at least 100 closed trades in 2025 through July 2026',
                       'positive marked P&L in 2024, 2025 and January-July 2026 separately',
                       'later net profit factor >=1.10', 'positive actual doubled-cost later marked P&L',
                       'later weekly-cluster mean-net-R 95% interval lower bound >0'],
        sensitivity_gate='Nearby pivots 1/3 and targets .75/1.25 must have positive later P&L on a primary before calling that primary robust. Counts and all failed neighbors remain visible.',
        promotion='No automated Working/feasible promotion. Retrospective numeric pass remains distinct from independent forward validation.',
        uncertainty='2000 seeded resamples of occupied exit weeks; pointwise and exploratory, not adjusted for 40 cases or longer dependence.',
        sizing='One contract, not equal-dollar-risk or percentage-risk sizing. Report both dollars and net R; do not rank contract sizes by dollars.',
        frozen_selection='All 40 cases and two primary instruments fixed before results; no post-result winner selection.',
        reason_for_isolated_runner='Native Workbench event-v1 lacks stop-entry orders. Preserve existing stop-entry semantics and actual-entry R rather than substitute next-open entries.')
    save(path, protocol)
    print(f'Declared {len(cases)} cases before results: {path}', flush=True)
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
        rows.append(dict(symbol=dataset['symbol'], source_rows=len(frame), first=str(frame.index[0]), last=str(frame.index[-1]),
                         warmup_calendar_days=(pd.Timestamp(dataset['start'], tz='UTC') - frame.index[0]).total_seconds() / 86400,
                         jobs=sum(c['symbol'] == dataset['symbol'] for c in protocol['cases'])))
        del frame, prices
    result = dict(status='passed', checked_at=now(), protocol_checksum=checksum(out / 'protocol.json'),
                  expected_cases=len(protocol['cases']), datasets=rows,
                  note='Data structure, checksums and declared job count only; no strategy outcomes inspected.')
    save(out / 'preview.json', result)
    print(json.dumps(result, indent=2), flush=True)


def freeze(out):
    if (out / 'source-manifest.json').exists():
        verify_source(out)
        print('Existing frozen source verified.', flush=True)
        return
    paths = ['strategies/_snd_fresh_retest.py', 'strategies/_transcript_supply_demand.py',
             'scripts/research-snd-fresh-retest.py', 'scripts/report-snd-fresh-retest.py',
             'scripts/report-transcript-supply-demand.py', 'scripts/analyze-transcript-supply-demand.py',
             'workbench/metrics.py', 'workbench/contract.py', 'tests/test_snd_fresh_retest.py',
             'tests/test_transcript_supply_demand.py']
    paths += [str(p.relative_to(ROOT)).replace('\\', '/') for p in (ROOT / 'strategy_engine').glob('*.py')]
    files = []
    for relative in paths:
        source = ROOT / relative
        if not source.exists():
            raise FileNotFoundError('Wait for completed source before freezing: ' + relative)
        destination = out / 'source' / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        files.append(dict(path=relative, checksum=checksum(source)))
    digest = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
    save(out / 'source-manifest.json', dict(frozen_at=now(), protocol_checksum=checksum(out / 'protocol.json'),
                                          source_hash=digest, files=files))
    save(out / 'environment.json', dict(python=sys.version, platform=platform.platform(), numpy=np.__version__, pandas=pd.__version__))
    print('Frozen source ' + digest, flush=True)


def verify_source(out):
    manifest = read(out / 'source-manifest.json')
    assert manifest['protocol_checksum'] == checksum(out / 'protocol.json'), 'Protocol changed'
    for item in manifest['files']:
        assert checksum(out / 'source' / item['path']) == item['checksum'], 'Snapshot changed: ' + item['path']
    return manifest


def run_market(out_name, dataset):
    out = Path(out_name)
    protocol, manifest = read(out / 'protocol.json'), verify_source(out)
    sys.path.insert(0, str(out / 'source'))
    spec = importlib.util.spec_from_file_location('frozen_fresh_model', out / 'source/strategies/_snd_fresh_retest.py')
    model = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(model)
    frame = load_market(dataset)
    prepared = {}
    outcomes = []
    for case in [c for c in protocol['cases'] if c['symbol'] == dataset['symbol']]:
        folder = out / case['symbol'] / case['variant']
        if (folder / 'result.json').exists():
            outcomes.append(read(folder / 'result.json')['status'])
            print(f'{case["symbol"]}/{case["variant"]}: existing attempt preserved', flush=True)
            continue
        folder.mkdir(parents=True, exist_ok=True)
        started, clock = now(), time.monotonic()
        identity = dict(protocol_checksum=manifest['protocol_checksum'], source_hash=manifest['source_hash'])
        save(folder / 'input.json', dict(**case, dataset=dataset, **identity))
        save(folder / 'status.json', dict(status='running', started_at=started))
        try:
            pivot = case['parameters']['pivot_len']
            if pivot not in prepared:
                prepared[pivot] = model.prepare_data(frame, pivot_len=pivot, execution_minutes=1)
            result = model.run_model(prepared[pivot], case['parameters'], dataset['start'], dataset['end'],
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
            del result, trades, equity
            if pivot != 2:
                del prepared[pivot]
        except Exception as error:
            trace = traceback.format_exc()
            (folder / 'error.log').write_text(trace, encoding='utf-8')
            save(folder / 'result.json', dict(status='failed', symbol=case['symbol'], variant=case['variant'],
                 started_at=started, completed_at=now(), error=str(error), artifacts=[], **identity))
            print(f'{case["symbol"]}/{case["variant"]}: FAILED {error}', flush=True)
            outcomes.append('failed')
    return dict(symbol=dataset['symbol'], statuses=outcomes)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=DEFAULT_OUT)
    parser.add_argument('--declare', action='store_true')
    parser.add_argument('--preview', action='store_true')
    parser.add_argument('--freeze', action='store_true')
    parser.add_argument('--run', action='store_true')
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
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            tasks = {pool.submit(run_market, str(out), d): d['symbol'] for d in protocol['datasets']}
            for task in as_completed(tasks):
                print(json.dumps(task.result()), flush=True)
        print('All declared market workers completed. Run report-snd-fresh-retest.py --require-complete.', flush=True)


if __name__ == '__main__':
    main()
