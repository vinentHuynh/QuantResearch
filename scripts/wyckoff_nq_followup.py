"""Launch one explicitly chosen Wyckoff NQ selection or final check.

This command never chooses parameters. Each label is single-use and keeps the
preview, exact request, launch response, and any error under the report folder.

Example:
    .venv/Scripts/python.exe scripts/wyckoff_nq_followup.py selection \
      --label standard-30m-8-base --reference-run-id UUID \
      --timeframe 30m --strictness Standard --holding-bars 8 \
      --hypothesis "Frozen candidate from the completed development grid"
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from urllib import error, request
import uuid


ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / 'reports' / 'wyckoff-nq-2026-09-28' / 'followup'
DATASET_SYMBOL = 'NQ'
STRATEGY_ID = 'wyckoff-nq'
SOURCE_FILES = (
    'strategies/wyckoff_nq.py',
    'strategies/_wyckoff_core.py',
    'pine/wyckoff_theultimator5.pine',
    'workbench/events.py',
    'workbench/worker.py',
    'workbench/metrics.py',
    'strategy_engine/data.py',
    'strategy_engine/sessions.py',
)
PHASES = {
    'selection': ('2023-01-01', '2024-12-31', 'Exploratory', '2022-12-31'),
    'final': ('2025-01-01', '2026-09-03', 'Evaluation', '2024-12-31'),
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _api(base: str, method: str, path: str, payload: dict | None = None):
    data = None if payload is None else json.dumps(payload).encode('utf-8')
    req = request.Request(base.rstrip('/') + path, data=data, method=method,
                          headers={'Content-Type': 'application/json'})
    try:
        with request.urlopen(req, timeout=180) as response:
            return json.load(response)
    except error.HTTPError as exc:
        detail = exc.read().decode('utf-8', errors='replace')
        raise RuntimeError(f'{method} {path}: HTTP {exc.code}: {detail}') from exc


def _reference_files(run_id: str) -> tuple[dict, dict]:
    canonical = str(uuid.UUID(run_id))
    input_path = ROOT / 'data' / 'workbench' / 'runs' / canonical / 'input.json'
    original = json.loads(input_path.read_text(encoding='utf-8'))
    if original['strategy']['id'] != STRATEGY_ID or original['dataset']['symbol'] != DATASET_SYMBOL:
        raise ValueError('Reference run must be a completed Wyckoff NQ run')
    manifest_path = input_path.parent / 'manifest.json'
    if not manifest_path.is_file():
        raise ValueError('Reference run has no completed manifest')
    source_dir = Path(original['source_dir'])
    digests = {}
    for relative in SOURCE_FILES:
        frozen = source_dir / Path(relative)
        live = ROOT / Path(relative)
        if not frozen.is_file() or not live.is_file():
            raise ValueError(f'Missing required source file: {relative}')
        reference_digest = _sha256(frozen)
        if _sha256(live) != reference_digest:
            raise ValueError(f'Source changed since reference run: {relative}')
        digests[relative] = reference_digest
    return original, digests


def _write_record(path: Path, record: dict, first: bool = False) -> None:
    encoded = json.dumps(record, indent=2, allow_nan=False) + '\n'
    if first:
        # Exclusive creation makes labels single-use, including failed previews.
        with path.open('x', encoding='utf-8') as handle:
            handle.write(encoded)
        return
    temporary = path.with_suffix('.tmp')
    temporary.write_text(encoded, encoding='utf-8')
    os.replace(temporary, path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=PHASES)
    parser.add_argument('--label', required=True,
                        help='Unique lowercase label for this selection or final attempt')
    parser.add_argument('--reference-run-id', required=True,
                        help='Completed Wyckoff NQ run whose detector/simulator source files are frozen')
    parser.add_argument('--dataset-id', help='Exact NQ dataset version; required if multiple are registered')
    parser.add_argument('--timeframe', required=True, choices=['15m', '30m', '1h', '4h'])
    parser.add_argument('--strictness', required=True,
                        choices=['Aggressive', 'Standard', 'Conservative'])
    parser.add_argument('--holding-bars', required=True, type=int, choices=[8, 24, 48])
    parser.add_argument('--entry-delay-bars', type=int, choices=[0, 1], default=0)
    parser.add_argument('--cost-case', choices=['base', 'double'], default='base')
    parser.add_argument('--hypothesis', required=True,
                        help='Why this exact configuration is being tested')
    parser.add_argument('--criteria', default='',
                        help='Frozen pass criteria, required for the final phase')
    parser.add_argument('--api', default='http://127.0.0.1:8001')
    args = parser.parse_args()

    if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,79}', args.label):
        parser.error('--label must use 1-80 lowercase letters, digits, hyphens, or underscores')
    if args.phase == 'final' and not args.criteria.strip():
        parser.error('--criteria is required for the frozen final check')
    if args.entry_delay_bars and args.cost_case == 'double':
        # Combining both stressors is a new experiment; make it an explicit
        # separately declared protocol instead of silently expanding this one.
        parser.error('Use delay and doubled costs as separate declared checks')
    if not args.hypothesis.strip():
        parser.error('--hypothesis must be nonempty')

    reference, source_digests = _reference_files(args.reference_run_id)
    _api(args.api, 'POST', '/api/workbench/discover', {})
    state = _api(args.api, 'GET', '/api/workbench/state?view=summary')
    strategies = [s for s in state['strategies'] if s['id'] == STRATEGY_ID]
    if len(strategies) != 1:
        raise ValueError('Wyckoff NQ adapter is not uniquely discovered')
    if strategies[0]['file_hash'] != source_digests['strategies/wyckoff_nq.py']:
        raise ValueError('Live discovered adapter checksum differs from reference source')
    datasets = [d for d in state['datasets'] if d['symbol'] == DATASET_SYMBOL]
    if args.dataset_id:
        datasets = [d for d in datasets if d['id'] == args.dataset_id]
    if len(datasets) != 1:
        raise ValueError('Choose one registered NQ dataset explicitly with --dataset-id')
    dataset = datasets[0]
    if dataset['id'] != reference['dataset']['id']:
        raise ValueError('Dataset version differs from the reference run')

    start, end, stage, development_end = PHASES[args.phase]
    fee, slippage = (2.5, 1) if args.cost_case == 'base' else (5.0, 2)
    parameters = {
        'strictness': args.strictness,
        'exit_policy': 'fixed_bars',
        'holding_bars': args.holding_bars,
        'entry_delay_bars': args.entry_delay_bars,
        'atr_length': 14,
        'stop_atr': 1.5,
        'target_r': 2.0,
    }
    payload = {
        'strategy_id': STRATEGY_ID, 'dataset_id': dataset['id'],
        'start': start, 'end': end,
        'timeframe': args.timeframe, 'session': 'full-trading-day',
        'stage': stage, 'development_end': development_end,
        'criteria': args.criteria.strip(),
        'parameters': parameters,
        'capital': 100000, 'fee': fee, 'slippage': slippage,
        'warmup_days': 180, 'delay_bars': 0, 'timeout': 1800,
        'hypothesis': f'Wyckoff NQ {args.phase} [{args.label}]: {args.hypothesis.strip()}',
    }
    record_path = REPORTS / args.phase / f'{args.label}.json'
    record_path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        'label': args.label, 'phase': args.phase,
        'created_at': _utc_now(), 'status': 'started',
        'reference_run_id': reference['id'],
        'reference_source_hash': reference['source_hash'],
        'locked_file_sha256': source_digests,
        'request': payload,
    }
    _write_record(record_path, record, first=True)
    try:
        preview = _api(args.api, 'POST', '/api/workbench/preview', payload)
        record['preview'] = preview
        record['status'] = 'previewed'
        _write_record(record_path, record)
        if preview.get('jobs') != 1 or preview.get('parameters') != [parameters]:
            raise ValueError('Preview did not resolve exactly the requested single configuration')
        record['status'] = 'launching'
        _write_record(record_path, record)
        launched = _api(args.api, 'POST', '/api/workbench/runs', payload)
        if not isinstance(launched, list) or len(launched) != 1:
            raise ValueError('Launch did not return exactly one run')
        record['launch_response'] = launched
        record['run_ids'] = [item['id'] for item in launched]
        record['source_hash'] = launched[0]['input']['source_hash']
        record['status'] = 'launched'
        _write_record(record_path, record)
    except Exception as exc:
        record['status'] = 'error'
        record['error'] = str(exc)
        _write_record(record_path, record)
        raise
    print(json.dumps({'record': str(record_path), 'run_ids': record['run_ids'],
                      'source_hash': record['source_hash']}, indent=2))


if __name__ == '__main__':
    main()
