"""Recorded 15m/4h NQ-only expansion of the declared Wyckoff development grid."""

from __future__ import annotations

import argparse
import json

from wyckoff_nq_campaign import REPORT, api, request_for


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--launch', action='store_true')
    parser.add_argument('--status', action='store_true')
    args = parser.parse_args()
    REPORT.mkdir(parents=True, exist_ok=True)
    record_path = REPORT / 'expansion-launch.json'
    if args.status:
        saved = json.loads(record_path.read_text(encoding='utf-8'))
        for run_id in saved['run_ids']:
            run = api('GET', f'/runs/{run_id}')
            metrics = (run.get('result') or {}).get('metrics') or {}
            print(run_id, run['status'], run['input']['timeframe'],
                  run['input']['parameters']['strictness'],
                  run['input']['parameters']['holding_bars'],
                  metrics.get('trades'), metrics.get('net_pnl'))
        return
    if args.launch and record_path.exists():
        raise SystemExit(f'Already launched: {record_path}')
    payload = request_for('development')
    payload['timeframes'] = ['15m', '4h']
    payload['hypothesis'] += ' Additional timeframe search after 30m Aggressive/8-bar passed the weak development screen.'
    api('POST', '/discover', {})
    preview = api('POST', '/preview', payload)
    if preview['jobs'] != 18:
        raise ValueError(f'Expected 18 expansion jobs, got {preview["jobs"]}')
    (REPORT / 'expansion-preview.json').write_text(json.dumps(preview, indent=2), encoding='utf-8')
    print(f'Previewed {preview["jobs"]} jobs on 15m/4h NQ')
    if args.launch:
        launched = api('POST', '/runs', payload)
        saved = {'group': 'expansion', 'request': payload,
                 'run_ids': [run['id'] for run in launched]}
        record_path.write_text(json.dumps(saved, indent=2), encoding='utf-8')
        print(f'Launched {len(launched)} runs; IDs saved to {record_path}')


if __name__ == '__main__':
    main()
