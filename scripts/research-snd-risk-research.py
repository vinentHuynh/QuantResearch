"""Declare, preview, freeze and execute the MNQ fixed-risk sizing experiment."""
from __future__ import annotations

import argparse
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
OUT = ROOT / 'reports/snd-risk-research-2026-09-25'
PRIOR = ROOT / 'reports/snd-entry-research-2026-09-25'


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


utils = module('snd_risk_campaign_helpers', ROOT / 'scripts/research-snd-entry-research.py')
checksum, save, read, now = utils.checksum, utils.save, utils.read, utils.now


def declare(out, primary_risk=100.0, cap=10):
    path = out / 'protocol.json'
    if path.exists():
        return read(path)
    previous = read(PRIOR / 'protocol.json')
    dataset = next(d for d in previous['datasets'] if d['symbol'] == 'MNQ')
    baseline = next(c for c in previous['cases'] if c['symbol'] == 'MNQ' and c['variant'] == 'relaxed_first_1')
    budgets = [primary_risk / 2, primary_risk, primary_risk * 2]
    modes = [('fixed_1', dict(sizing_mode='fixed_contracts', contracts=1)),
             *[(f'risk_{value:g}', dict(sizing_mode='fixed_risk', risk_budget=value, contracts=1)) for value in budgets]]
    scenarios = [
        ('cash_base', 'cash', 1, 1, 'relaxed_first_1'),
        ('cash_double', 'cash', 2, 2, 'relaxed_first_1_double_cost'),
        ('price_1', 'price', 1, 1, 'relaxed_first_1_price_1'),
        ('price_2_double_fee', 'price', 2, 2, 'relaxed_first_1_price_2_double_fee')]
    cases = []
    for scenario, slippage_mode, ticks, fee_multiple, old in scenarios:
        for sizing, changes in modes:
            parameters = baseline['parameters'] | dict(max_contracts=cap, risk_budget=primary_risk,
                record_events=False, finalize=True) | changes | dict(slippage_model=slippage_mode)
            cases.append(dict(symbol='MNQ', variant=sizing + '_' + scenario, sizing=sizing,
                scenario=scenario, parameters=parameters, fee=baseline['fee'] * fee_multiple,
                slippage_ticks=ticks, prior_control=old if sizing == 'fixed_1' else None))
    protocol = dict(declared_at=now(), strategy='SND relaxed-wick first-touch: fixed-dollar risk research',
        research_question='Does positive one-contract dollar performance survive causal whole-contract risk budgeting, costs and quantity limits?',
        datasets=[dataset], cases=cases, expected_cases=len(cases), capital=previous['capital'],
        periods=previous['periods'], primary_market='MNQ', primary_risk_budget=primary_risk,
        risk_budgets=budgets, max_contracts=cap, primary_case=f'risk_{primary_risk:g}_price_1',
        prior_campaign=str(PRIOR), prior_protocol_checksum=checksum(PRIOR / 'protocol.json'),
        prior_manifest_checksum=checksum(PRIOR / 'source-manifest.json'),
        rules=[
            'All signal rules frozen: relaxed formation, wick bounds, pivot2, aligned chart/hour directions, first touch, one elapsed five-minute order lifetime, one tick zone stop, target1R, opposing room2R, full session, age288/cap100, 30-day warmup.',
            'Fixed dollar budget, no compounding. At eligible arming use planned all-in stop loss per contract = directional(trigger-stop)*point_value + two slippage sides + two commissions. Both cash/price models include expected entry and stop exit costs.',
            'Quantity = min(contract cap, floor(risk budget / planned all-in stop loss per contract)). It is fixed when the order arms. A sub-one-contract budget skips the candidate and consumes its first touch; other eligible zones may be considered at that same close.',
            'Quantity never resizes using actual gap fill, future exit or end-of-trade information. Entry/stop gaps can exceed the planned budget; all actual modeled stop risk and realized loss overruns are reported. This budget is not a guaranteed loss cap.',
            'All per-contract fees, slippage, gross PnL, price-distance risk and marked exposure scale by the frozen integer quantity. net R divides trade net PnL by actual price-distance cash risk, excluding fees from the denominator as in prior reports.',
            'Zero-quantity decisions and cap effects are retained in sizing-decisions.csv. Declined trades can change later strategy availability; these are complete simulator reruns, not just multiplication of old trade results.',
            'Four fixed-contract controls must exactly reproduce the preceding campaign on every pre-existing trade column and complete equity frame.',
            'Fractional constant-risk figures on prior executed trades are diagnostic only: they reuse actual initial risk and cannot represent arm-time integer-contract orders or skipped-trade state changes.'
        ],
        declared_checks=dict(
            implementation='All cases reconcile; four exact prior controls; independently reconstructed quantity, risk, costs and marked equity; planned selected risk within budget and integer cap.',
            economic='Report positive/negative full and later marked net for each declared sizing/cost case. A robust historical sizing finding requires the primary $risk case to remain positive full and later in all four scenarios; no search or promotion based on which budget wins.',
            sampling='Report all zero-trade/failed cases, sample counts, quantity distribution, budget skips, cap use, risk overruns, confidence intervals and losing subperiods. No profitability conclusion from implementation checks alone.'),
        prior_exposure='Entire January2022-July2026 scored interval previously inspected. No new holdout claim. Later local August/September data is not used for this sizing experiment.',
        limitations='No margin, broker liquidation, queue, latency, capacity or multi-contract market impact model. Ten-contract cap is a research setting, not a margin approval. Continuous-contract roll liquidation and missing-minute ambiguity are inherited.',
        reason_for_isolated_runner='Native Workbench event-v1 lacks the exact stop-entry lifecycle; preserve linked immutable artifacts in this standalone campaign.')
    save(path, protocol)
    print(f'Declared {len(cases)} cases: {path}', flush=True)
    return protocol


def freeze(out):
    if (out / 'source-manifest.json').exists():
        return utils.verify_source(out)
    previous = read(PRIOR / 'source-manifest.json')
    paths = list(dict.fromkeys([x['path'] for x in previous['files']] + [
        'strategies/_snd_risk_research.py', 'tests/test_snd_risk_research.py',
        'scripts/research-snd-risk-research.py', 'scripts/audit-snd-risk-research.py']))
    for path in paths:
        if not (ROOT / path).is_file():
            raise FileNotFoundError('Source incomplete before freeze: ' + path)
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


def run(out, protocol):
    manifest = utils.verify_source(out)
    preview = read(out / 'preview.json')
    assert preview['status'] == 'passed' and preview['protocol_checksum'] == manifest['protocol_checksum']
    sys.path.insert(0, str(out / 'source'))
    model = module('frozen_snd_risk_model', out / 'source/strategies/_snd_risk_research.py')
    dataset = protocol['datasets'][0]
    frame = utils.load_market(dataset)
    prepared = model.prepare_data(frame, pivot_len=2, execution_minutes=1)
    outcomes = []
    for case in protocol['cases']:
        folder = out / case['symbol'] / case['variant']
        if (folder / 'result.json').exists():
            outcomes.append(read(folder / 'result.json')['status'])
            print(case['variant'] + ': existing attempt preserved', flush=True)
            continue
        if folder.exists() and any(folder.iterdir()):
            raise RuntimeError('Interrupted attempt preserved; use a new campaign: ' + str(folder))
        folder.mkdir(parents=True, exist_ok=True)
        started, clock = now(), time.monotonic()
        identity = dict(protocol_checksum=manifest['protocol_checksum'], source_hash=manifest['source_hash'])
        save(folder / 'input.json', dict(**case, dataset=dataset, **identity))
        save(folder / 'status.json', dict(status='running', started_at=started))
        try:
            result = model.run_model(prepared, case['parameters'], dataset['start'], dataset['end'],
                dataset['tick_size'], dataset['point_value'], case['fee'], case['slippage_ticks'])
            trades, equity, decisions = result['trades'], result['equity'], result['sizing_decisions']
            np.testing.assert_allclose(equity.equity.iloc[-1] - protocol['capital'], trades.net_pnl.sum(), atol=1e-5, rtol=0)
            np.testing.assert_allclose(equity.net_pnl.sum(), trades.net_pnl.sum(), atol=1e-5, rtol=0)
            np.testing.assert_allclose(trades.gross_pnl - trades.cost, trades.net_pnl, atol=1e-7, rtol=0)
            assert equity.contracts.iloc[-1] == 0
            trades.to_csv(folder / 'trades.csv', index=False)
            equity.to_parquet(folder / 'equity.parquet', index=False)
            decisions.to_csv(folder / 'sizing-decisions.csv', index=False)
            artifacts = [dict(name=name, checksum=checksum(folder / name)) for name in ['trades.csv', 'equity.parquet', 'sizing-decisions.csv']]
            payload = dict(status='succeeded', symbol=case['symbol'], variant=case['variant'], started_at=started,
                completed_at=now(), elapsed_seconds=time.monotonic() - clock, parameters=result['parameters'],
                diagnostics=result['diagnostics'], artifacts=artifacts, **identity)
            save(folder / 'result.json', payload)
            save(folder / 'status.json', dict(status='succeeded', completed_at=payload['completed_at']))
            outcomes.append('succeeded')
            print(f'{case["variant"]}: {len(trades)} trades; net ${trades.net_pnl.sum():,.2f}; {payload["elapsed_seconds"]:.1f}s', flush=True)
        except Exception as error:
            (folder / 'error.log').write_text(traceback.format_exc(), encoding='utf-8')
            save(folder / 'result.json', dict(status='failed', symbol=case['symbol'], variant=case['variant'],
                started_at=started, completed_at=now(), error=str(error), artifacts=[], **identity))
            outcomes.append('failed')
            print(case['variant'] + ': FAILED ' + str(error), flush=True)
    save(out / 'completion.json', dict(completed_at=now(), statuses=outcomes))
    if any(value != 'succeeded' for value in outcomes):
        raise SystemExit(1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=OUT)
    parser.add_argument('--primary-risk', type=float, default=100.)
    parser.add_argument('--max-contracts', type=int, default=10)
    for action in ['declare', 'preview', 'freeze', 'run']:
        parser.add_argument('--' + action, action='store_true')
    args = parser.parse_args()
    if not np.isfinite(args.primary_risk) or args.primary_risk <= 0 or not 1 <= args.max_contracts <= 100:
        raise ValueError('Risk must be positive; cap must be 1..100')
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    protocol = declare(out, args.primary_risk, args.max_contracts) if args.declare else read(out / 'protocol.json')
    if args.preview:
        utils.preview(out, protocol)
    if args.freeze:
        freeze(out)
    if args.run:
        run(out, protocol)


if __name__ == '__main__':
    main()
