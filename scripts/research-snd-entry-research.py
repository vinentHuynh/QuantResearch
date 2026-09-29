"""Freeze and run relaxed-FVG robustness and separated touch/order-lifetime tests.

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
DEFAULT_OUT = ROOT / 'reports/snd-entry-research-2026-09-25'
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
    datasets = [next(d for d in previous['datasets'] if d['symbol'] == symbol) for symbol in ['MNQ', 'MGC', 'NQ']]
    cases = []
    matrix = [('first_1', 'first_touch', 1), ('first_3', 'first_touch', 3),
              ('any_1', 'any_touch', 1), ('any_3', 'any_touch', 3)]
    for dataset in datasets:
        symbol = dataset['symbol']
        original = next(c for c in previous['cases'] if c['symbol'] == symbol and c['variant'] == 'candidate')
        base = original['parameters'] | dict(entry_eligibility='first_touch', order_lifetime_bars=1, slippage_model='cash')
        def add(name, changes=None, fee_multiple=1, ticks=1, group='entry_factorial'):
            cases.append(dict(symbol=symbol, variant=name, group=group,
                              parameters=base | (changes or {}), fee=original['fee'] * fee_multiple, slippage_ticks=ticks))
        for strict in [True, False]:
            for suffix, eligibility, lifetime in matrix:
                name = ('strict_' if strict else 'relaxed_') + suffix
                if name == 'strict_first_1':
                    name = 'strict_control'
                add(name, dict(require_fvg=strict, entry_eligibility=eligibility, order_lifetime_bars=lifetime))
        add('relaxed_first_1_double_cost', dict(require_fvg=False), fee_multiple=2, ticks=2, group='cash_cost_stress')
        if symbol == 'MNQ':
            for suffix, eligibility, lifetime in matrix:
                common = dict(require_fvg=False, entry_eligibility=eligibility, order_lifetime_bars=lifetime)
                if suffix != 'first_1':
                    add('relaxed_' + suffix + '_double_cost', common, fee_multiple=2, ticks=2, group='cash_cost_stress')
                add('relaxed_' + suffix + '_price_2', common | dict(slippage_model='price'), ticks=2, group='price_fill_stress')
            add('relaxed_first_1_price_1', dict(require_fvg=False, slippage_model='price'), ticks=1, group='price_fill_stress')
            add('relaxed_first_1_price_2_double_fee', dict(require_fvg=False, slippage_model='price'), fee_multiple=2, ticks=2, group='price_fill_stress')
            for name, changes in [('pivot_1', {'pivot_len': 1}), ('pivot_3', {'pivot_len': 3}),
                    ('target_075', {'rr': .75}), ('target_125', {'rr': 1.25}),
                    ('room_15', {'min_opposing_room_r': 1.5}), ('room_25', {'min_opposing_room_r': 2.5})]:
                add('relaxed_' + name, dict(require_fvg=False) | changes, group='nearby_setting')
    assert len(cases) == 42
    protocol = dict(declared_at=now(), strategy='SND relaxed-FVG stress and entry-mechanics experiment',
        research_question='Test 1: does the stronger observed relaxed-FVG MNQ variant survive actual cost/fill stresses and nearby settings? Test 2: independently measure first-touch eligibility versus frozen order lifetime.',
        primary_markets=['MNQ'], transfer_markets=['MGC', 'NQ'], datasets=datasets, cases=cases, expected_cases=len(cases),
        capital=previous['capital'], periods=previous['periods'],
        prior_campaign=str(PRIOR), prior_protocol_checksum=checksum(PRIOR / 'protocol.json'),
        prior_manifest_checksum=checksum(PRIOR / 'source-manifest.json'),
        rules=[
            'Wick boundaries for every case. Strict FVG uses current low above base high (demand) or current high below base low (supply). Relaxed formation uses current close beyond the same base wick. Candle direction, confirmation and consecutive-bar rules unchanged.',
            'Both 5m and completed-hour structure align at formation and arming; pivots confirmed causally; nearest opposing context and zone-stop rules unchanged.',
            'First-touch eligibility allows arming only at the original complete physical-first-touch candle close. Warmup, busy, incomplete and misaligned touches remain consumed.',
            'Any-touch eligibility permits arming on later complete physical-overlap candle closes while the zone is unused and valid. It does not reuse the legacy rolling trigger when price is no longer touching.',
            'Separate order lifetime 1 versus 3: freeze trigger, stop and opposing obstacle at arming; valid from next 5m open until exclusive signal_time + N*5min. Elapsed gaps/weekends consume lifetime. Never refresh or replace an active pending order.',
            'Both eligibility modes use identical scoring/warmup/position/exit blocking. Any-touch may rearm after expiry/cancellation only at a qualifying overlapping close; first-touch cannot.',
            'Pending orders cancel on hourly-direction mismatch, distal wick invalidation, zone age expiry, contract roll, fill or rejected fill. Five-minute trend remains an arming condition, not a retroactive intrabar cancellation.',
            'Cash slippage mode exactly preserves the prior model; true doubled-cost simulations rerun state with 2x commissions and 2x slippage cash charges.',
            'Price slippage mode adds adverse ticks to gap-aware entry fill and subtracts adverse ticks from nonlimit exits. Targets fill at their limit. Fee-only cash charges avoid double counting; target, risk and 2R room use the actual shifted entry.',
            'Price stress is a deterministic fill scenario; it may print outside a bar range. It is not a queue/liquidity model. Keep original opening-trigger chronology even if shifted fill is outside OHLC.',
            'Zone stop, 1R target, room2R, one fixed contract, full session, age288, cap100, 30-day warmup and conservative one-minute exit ordering unchanged except declared one-at-a-time neighbors.'
        ],
        comparisons='For each market and each fixed FVG definition, compare first_1 vs first_3 (lifetime), first_1 vs any_1 (eligibility), first_3 vs any_3 (eligibility at 3 bars), and any_1 vs any_3 (lifetime at any touch). MNQ relaxed matrix also checked under doubled cash costs and adverse2tick price fills.',
        targeted_stability_checks=dict(
            definition='A targeted robustness check, not an overall profitability/forward-validation pass; original failed2024 and confidence intervals remain reported.',
            required_stress_cases=['relaxed_first_1_double_cost', 'relaxed_first_1_price_1', 'relaxed_first_1_price_2', 'relaxed_first_1_price_2_double_fee'],
            stress_rule='Each required MNQ case must have positive full-history and later2025-Jul2026 marked net PnL.',
            neighbor_cases=['relaxed_pivot_1','relaxed_pivot_3','relaxed_target_075','relaxed_target_125','relaxed_room_15','relaxed_room_25'],
            neighbor_rule='All six one-at-a-time neighbors must have positive later net PnL and at least100 later closed trades.',
            sample_rule='Relaxed first1 baseline must have at least100 later closed trades.',
            entry_test='Descriptive factorial contrasts; do not promote the highest observed cash result or search new settings after outcomes.'),
        validation='Exact common-column trade/equity parity to prior strict candidate on all3 markets and prior relaxed-FVG case on MNQ/MGC; baseline original first-touch semantics required. Source/input/artifact hashes, accounting, TTL timestamps and independent raw-condition audit.',
        known_pretest_evidence='MNQ relaxed-FVG full mean netR slightlynegative, 2024 net-293, later meanRinterval includeszero. This campaign cannot erase that evidence. NQ relaxed-FVG not tested in fresh campaign.',
        prior_exposure=previous['prior_exposure'],
        limitations='Previously inspected history, one contract rather than equal-risk sizing, related NQ/MNQ exposure, unadjusted rolls, missing minutes, idealized roll liquidation and price-protection cancellation; no broker queue/margin or live-readiness claim.',
        reason_for_isolated_runner='Native Workbench event-v1 lacks stop-entry orders. Preserve explicit stop-entry/order-expiry semantics and link all source/data artifacts separately.')
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
    paths = ['strategies/_snd_entry_research.py', 'strategies/_snd_fresh_retest.py',
        'strategies/_transcript_supply_demand.py', 'scripts/research-snd-entry-research.py', 'scripts/report-snd-body-retest.py',
        'scripts/report-snd-fresh-retest.py', 'scripts/audit-snd-entry-research.py',
        'scripts/report-transcript-supply-demand.py', 'scripts/analyze-transcript-supply-demand.py',
        'workbench/metrics.py', 'workbench/contract.py', 'tests/test_snd_entry_research.py',
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
    spec = importlib.util.spec_from_file_location('frozen_entry_model', out / 'source/strategies/_snd_entry_research.py')
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
        if folder.exists() and any(folder.iterdir()):
            raise RuntimeError('Interrupted attempt preserved; choose a new output directory: ' + str(folder))
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
            if pivot != 2:
                del prepared[pivot]
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
        print('All declared cases completed. Run report-snd-entry-research.py --require-complete.', flush=True)


if __name__ == '__main__':
    main()
