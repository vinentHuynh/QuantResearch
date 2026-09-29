"""Launch and inspect the declared NQ-only Wyckoff research through Workbench.

This script deliberately has no final-period launch mode. Freeze a selected
configuration and documented criteria before a separate final evaluation.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / 'reports' / 'wyckoff-nq-2026-09-28'
API = 'http://127.0.0.1:8001/api/workbench'
DATASET = 'f47a454bc68f406890870d40be4517b1a85bf95c4604d8ba9298fc1aee09fba3-v1'


def api(method: str, suffix: str, payload: dict | None = None):
    data = None if payload is None else json.dumps(payload).encode('utf-8')
    request = Request(API + suffix, data=data, method=method)
    if data is not None:
        request.add_header('Content-Type', 'application/json')
    with urlopen(request, timeout=120) as response:
        return json.load(response)


def request_for(group: str) -> dict:
    common = {
        'strategy_id': 'wyckoff-nq',
        'dataset_id': DATASET,
        'timeframe': '30m',
        'session': 'full-trading-day',
        'stage': 'Exploratory',
        'capital': 100000,
        'fee': 2.5,
        'slippage': 1,
        'warmup_days': 180,
        'timeout': 1800,
        'parameters': {
            'strictness': 'Standard',
            'exit_policy': 'fixed_bars',
            'holding_bars': 24,
            'entry_delay_bars': 0,
        },
        'hypothesis': (
            'Wyckoff Pine Auto entries on NQ: test whether confirmed chart-timeframe '
            'alerts lead to positive next-open forward outcomes after explicit costs. '
            'Fixed-bar exits are research additions; Pine parity not certified.'
        ),
    }
    if group == 'pilot':
        return {**common, 'start': '2020-01-01', 'end': '2022-12-31'}
    if group == 'development':
        return {
            **common,
            'start': '2011-01-01',
            'end': '2022-12-31',
            'timeframes': ['30m', '1h'],
            'sweep': {
                'strictness': ['Aggressive', 'Standard', 'Conservative'],
                'holding_bars': [8, 24, 48],
            },
        }
    raise ValueError(group)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('group', choices=['pilot', 'development'])
    parser.add_argument('--launch', action='store_true', help='Launch after preview; omit for read-only preview')
    parser.add_argument('--status', action='store_true', help='Inspect a previously launched group')
    args = parser.parse_args()
    REPORT.mkdir(parents=True, exist_ok=True)
    record = REPORT / f'{args.group}-launch.json'
    if args.status:
        saved = json.loads(record.read_text(encoding='utf-8'))
        rows = []
        for run_id in saved['run_ids']:
            run = api('GET', f'/runs/{run_id}')
            result = run.get('result') or {}
            rows.append({
                'id': run_id,
                'status': run.get('status'),
                'timeframe': run['input']['timeframe'],
                'parameters': run['input']['parameters'],
                'metrics': result.get('metrics'),
                'error': result.get('error') or run.get('error'),
            })
        (REPORT / f'{args.group}-status.json').write_text(json.dumps(rows, indent=2), encoding='utf-8')
        for row in rows:
            print(row['id'], row['status'], row['timeframe'], row['parameters'])
        return
    if args.launch and record.exists():
        raise SystemExit(f'Already launched: {record}')
    api('POST', '/discover', {})
    payload = request_for(args.group)
    preview = api('POST', '/preview', payload)
    print(json.dumps({'jobs': preview['jobs'], 'parameters': preview['parameters'], 'warmup': preview['warmup']}, indent=2))
    (REPORT / f'{args.group}-preview.json').write_text(json.dumps(preview, indent=2), encoding='utf-8')
    if args.launch:
        runs = api('POST', '/runs', payload)
        saved = {
            'group': args.group,
            'request': payload,
            'run_ids': [run['id'] for run in runs],
        }
        record.write_text(json.dumps(saved, indent=2), encoding='utf-8')
        print(f'Launched {len(runs)} runs; IDs saved to {record}')


if __name__ == '__main__':
    main()
