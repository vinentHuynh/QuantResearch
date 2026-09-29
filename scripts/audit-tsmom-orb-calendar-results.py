"""Read-only audit of the recorded ORB calendar repair campaign.

Run again while jobs progress. Every campaign attempt is retained; this script
does not start, retag, delete or modify runs. Partial reports are intentional.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from strategies._cme_index_calendar import CALENDAR_VERSION, SOURCE_SHA256, session_close_et

REPORT = ROOT / 'reports/tsmom-orb-fix-2026-09-29'
STATE = Path(os.environ.get('WORKBENCH_HOME', ROOT / 'data/workbench'))
TERMINAL = {'Succeeded', 'Failed', 'Cancelled', 'Canceled', 'Timed out', 'Interrupted'}
SOURCE_FILES = ['strategies/pine_tsmom_orb.py', 'strategies/_pine_models.py',
                'strategies/_cme_index_calendar.py', 'workbench/events.py']


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def normalized_expiry(text):
    """Recognize only the two reviewed exclusive-boundary expression changes."""
    return text.replace('(self.session_ends[key] - pd.Timedelta(nanoseconds=1)).isoformat()',
                        'self.session_ends[key].isoformat()').replace(
                            '(deadline - pd.Timedelta(nanoseconds=1)).isoformat()',
                            'deadline.isoformat()')


def source_identity(inp):
    snapshot = Path(inp['source_dir'])
    files = {}
    for name in SOURCE_FILES:
        old, current = snapshot / name, ROOT / name
        files[name] = {'snapshot_sha256': sha(old) if old.exists() else None,
                       'current_sha256': sha(current),
                       'snapshot_path': str(old)}
        files[name]['matches_current'] = files[name]['snapshot_sha256'] == files[name]['current_sha256']
    exact = all(row['matches_current'] for row in files.values())
    other_equal = all(row['matches_current'] for name, row in files.items()
                      if name != 'strategies/_pine_models.py')
    old_models = snapshot / 'strategies/_pine_models.py'
    only_expiry = other_equal and old_models.exists() and normalized_expiry(
        old_models.read_text(encoding='utf-8')) == normalized_expiry(
            (ROOT / 'strategies/_pine_models.py').read_text(encoding='utf-8'))
    timing = inp['parameters'].get('execution_timing', 'close')
    return {'bundle_source_hash': inp['source_hash'], 'files': files,
            'exact_current_source': exact, 'only_reviewed_expiry_boundary_difference': bool(only_expiry and not exact),
            'current_execution_behavior_supported': bool(exact or (timing == 'close' and only_expiry)),
            'note': ('Exact current source.' if exact else
                     'Only reviewed expiry expressions differ; close-mode execution does not read them.'
                     if timing == 'close' and only_expiry else
                     'Earlier next-open boundary revision; retain as superseded evidence, not current confirmation.'
                     if only_expiry else 'Source differs; inspect hashes before claiming current validation.')}


def json_trade(row, entry, exit_time, close):
    return {'entry_et': entry.isoformat(), 'exit_et': exit_time.isoformat(),
            'scheduled_close_et': close.isoformat() if close is not None else None,
            'net_pnl': float(row.net_pnl), 'exit_reason': str(row.get('exit_reason', '')),
            'quantity': int(row.quantity)}


def audit_run(label, run, request=None):
    result = {'case': label, 'run_id': run.get('id'), 'status': run.get('status', 'Missing'),
              'created_at': run.get('created_at'), 'started_at': run.get('started_at'),
              'ended_at': run.get('ended_at'), 'audit_state': 'pending', 'failures': []}
    inp = run.get('input', request or {})
    result['settings'] = {key: inp.get(key) for key in ['start', 'end', 'timeframe', 'session',
                          'capital', 'fee', 'slippage', 'warmup_days', 'parameters', 'source_hash']}
    result['symbol'] = inp.get('dataset', {}).get('symbol', label.split('-')[0])
    if result['status'] != 'Succeeded':
        if result['status'] in TERMINAL or result['status'] == 'Missing':
            result['audit_state'] = 'failed'
            result['failures'].append('Run did not succeed: ' + result['status'])
        result['run_error'] = run.get('error') or run.get('result', {}).get('error')
        return result, None
    folder = STATE / 'runs' / run['id']
    try:
        inp = read(folder / 'input.json')
        manifest = read(folder / 'manifest.json')
        result['source'] = source_identity(inp)
        result['manifest_sha256'] = sha(folder / 'manifest.json')
        expected = {a['name']: a['checksum'] for a in manifest['artifacts']}
        result['artifact_checks'] = {}
        for name in ['trades.csv', 'equity.csv', 'positions.csv']:
            observed = sha(folder / name)
            result['artifact_checks'][name] = {'expected_sha256': expected.get(name),
                                              'actual_sha256': observed,
                                              'verified': observed == expected.get(name)}
        if not all(a['verified'] for a in result['artifact_checks'].values()):
            raise ValueError('Recorded artifact checksum mismatch')
        trades = pd.read_csv(folder / 'trades.csv')
        equity = pd.read_csv(folder / 'equity.csv')
        values = equity.equity.to_numpy(dtype=float)
        if not len(values) or not np.isfinite(values).all():
            raise ValueError('Empty or nonfinite equity ledger')
        capital = float(inp['capital'])
        peaks = np.maximum.accumulate(np.r_[capital, values])[1:]
        drawdowns = values / peaks - 1.0
        net = float(trades.net_pnl.sum())
        marks_net = float(values[-1] - capital)
        metrics = manifest['metrics']
        reconcile = {'trades_equal_manifest': len(trades) == metrics['trades'],
                     'trade_pnl_equals_manifest': abs(net - metrics['net_pnl']) < .01,
                     'trade_pnl_equals_final_equity': abs(net - marks_net) < .01,
                     'drawdown_equals_manifest': abs(float(drawdowns.min()) - metrics['max_drawdown']) < 1e-10,
                     'equity_sum_equals_final_equity': abs(float(equity.net_pnl.sum()) - marks_net) < .01}
        result['reconciliation'] = reconcile
        entries = pd.to_datetime(trades.entry_time, utc=True).dt.tz_convert('America/New_York')
        exits = pd.to_datetime(trades.exit_time, utc=True).dt.tz_convert('America/New_York')
        carries, after_close, at_close, closed_entries = [], [], [], []
        calendar_rows = []
        for index, row in trades.iterrows():
            entry, exit_time = entries.iloc[index], exits.iloc[index]
            close = session_close_et(entry.date())
            detail = json_trade(row, entry, exit_time, close)
            calendar_rows.append(detail)
            if entry.date() != exit_time.date():
                carries.append(detail)
            if close is None or entry >= close:
                closed_entries.append(detail)
            if close is None or exit_time > close:
                after_close.append(detail)
            if close is not None and exit_time == close:
                at_close.append(detail)
        planned_points = float(inp['parameters']['risk_budget']) / float(inp['dataset']['point_value'])
        result['cost_and_sizing'] = {
            'contracts_cap': inp['parameters']['maximum_contracts'],
            'risk_budget_usd': inp['parameters']['risk_budget'],
            'point_value_usd': inp['dataset']['point_value'],
            'one_contract_planned_stop_distance_cutoff_points': planned_points,
            'fee_per_contract_per_side_usd': inp['fee'],
            'slippage_ticks_per_market_or_stop_side': inp['slippage'],
            'market_round_trip_assumed_cost_usd': 2 * (inp['fee'] + inp['slippage'] * inp['dataset']['tick_size'] * inp['dataset']['point_value']),
            'note': 'Limit exits pay commission only. Planned risk is a sizing filter, not a guarantee against stop gaps.'}
        result['metrics'] = {'net_pnl': net, 'trades': len(trades), 'max_drawdown': float(drawdowns.min()),
                             'max_drawdown_dollars': float((peaks - values).max()),
                             'equity_marks': len(values), 'costs': float(trades.cost.sum()),
                             'accounting': 'Recorded bar-close marked equity; does not bound intrabar adverse excursion.'}
        result['calendar_audit'] = {'overnight_carry_count': len(carries), 'after_close_count': len(after_close),
                                    'at_close_count': len(at_close), 'closed_session_entry_count': len(closed_entries),
                                    'overnight_carries': carries, 'after_close_trades': after_close,
                                    'closed_session_entries': closed_entries}
        checks = {'positive_net_pnl': net > 0, 'minimum_10_trades': len(trades) >= 10,
                  'marked_drawdown_at_most_35_percent': float(drawdowns.min()) >= -.35,
                  'zero_after_scheduled_close': not after_close,
                  'zero_overnight_carries': not carries, 'zero_closed_session_entries': not closed_entries,
                  'reconciled_ledgers': all(reconcile.values()), 'verified_artifacts': True,
                  'matching_125_point_sizing_cutoff': math.isclose(planned_points, 125.0)
                  and inp['parameters']['maximum_contracts'] == 1}
        result['checks'] = checks
        result['failures'] = [name for name, passed in checks.items() if not passed]
        result['audit_state'] = 'passed' if not result['failures'] else 'failed'
        result['calendar_trades'] = calendar_rows
        return result, trades
    except Exception as error:
        result['audit_state'] = 'failed'
        result['failures'].append(str(error))
        return result, None


def money(value):
    return '—' if value is None else ('-' if value < 0 else '') + f'${abs(value):,.2f}'


def main():
    campaign = read(REPORT / 'campaign.json')
    selection = read(ROOT / 'ninjatrader/working_nq_to_mnq/selection.json')
    old_orb = next(item for item in selection['selected'] + selection['excluded']
                   if item['strategy_id'] == 'pine-tsmom-orb')
    old_ids = [r['run_id'] for r in old_orb['baseline_runs'] if r['input']['start'] >= '2024-01-01']
    ids = list(dict.fromkeys([group['run_id'] for group in campaign['groups'].values()] + old_ids))
    with sqlite3.connect((STATE / 'workbench.sqlite3').resolve().as_uri() + '?mode=ro', uri=True) as connection:
        records = {run_id: json.loads(body) for run_id, body in connection.execute(
            "SELECT id,body FROM records WHERE kind='run' AND id IN (" + ','.join('?' for _ in ids) + ')', ids)}
    results = []
    for label, group in campaign['groups'].items():
        run = records.get(group['run_id'], {'id': group['run_id'], 'status': 'Missing'})
        result, _ = audit_run(label, run, group['request'])
        result['role'] = 'earlier next-open attempt; retained, superseded by strict expiry' if label == 'MNQ-next-open' else 'current campaign case'
        results.append(result)
    by_case = {r['case']: r for r in results}
    comparisons, original_carries = [], []
    for old_id in old_ids:
        run = records[old_id]
        year = run['input']['start'][:4]
        old, _ = audit_run('original-NQ-' + year, run)
        fixed = by_case.get('NQ-' + year + '-baseline', {})
        comparisons.append({'year': year, 'original_run_id': old_id, 'original': old,
                            'fixed_case': fixed.get('case'), 'fixed_run_id': fixed.get('run_id'),
                            'fixed_audit_state': fixed.get('audit_state'), 'fixed_metrics': fixed.get('metrics'),
                            'fixed_calendar_audit': fixed.get('calendar_audit'),
                            'net_pnl_change': fixed['metrics']['net_pnl'] - old['metrics']['net_pnl']
                            if 'metrics' in fixed and 'metrics' in old else None})
        for carry in old.get('calendar_audit', {}).get('overnight_carries', []):
            matches = [trade for trade in fixed.get('calendar_trades', []) if trade['entry_et'] == carry['entry_et']]
            original_carries.append({'original_run_id': old_id, 'original': carry, 'fixed_run_id': fixed.get('run_id'),
                                     'fixed_matching_entry_trades': matches,
                                     'resolution': 'pending' if fixed.get('audit_state') == 'pending' else
                                     'no matching revised entry' if not matches else
                                     'exited before scheduled close' if all(t['scheduled_close_et'] is not None and
                                      pd.Timestamp(t['exit_et']) < pd.Timestamp(t['scheduled_close_et']) for t in matches)
                                     else 'requires review'})
    current = [r for r in results if r['case'] != 'MNQ-next-open']
    all_terminal = all(r['status'] in TERMINAL for r in results)
    current_all_pass = bool(current) and all(r['audit_state'] == 'passed' for r in current)
    current_source_supported = bool(current) and all(r.get('source', {}).get('current_execution_behavior_supported', False) for r in current)
    report = {'generated_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'read_mode': 'Current workbench SQLite read-only snapshot; original runs untouched.',
              'campaign_file_sha256': sha(REPORT / 'campaign.json'), 'campaign': campaign,
              'calendar_version': CALENDAR_VERSION, 'calendar_xml_sha256': SOURCE_SHA256,
              'source_files_current_sha256': {name: sha(ROOT / name) for name in SOURCE_FILES},
              'all_attempts_terminal': all_terminal, 'attempt_count': len(results),
              'current_case_count': len(current), 'current_cases_all_checks_pass': current_all_pass,
              'current_source_behavior_supported': current_source_supported,
              'status_counts': {status: sum(r['status'] == status for r in results) for status in sorted({r['status'] for r in results})},
              'results': results, 'nq_original_vs_fixed': comparisons,
              'original_nine_carry_resolutions': original_carries,
              'conclusion': ('Current campaign cases pass declared historical checks.' if current_all_pass and current_source_supported else
                             'Campaign incomplete; active and failed attempts remain visible.' if not all_terminal else
                             'One or more declared checks or source confirmations failed; do not promote.'),
              'limitations': ['Previously inspected periods; historical regression, not a fresh holdout.',
                              'NinjaTrader native fills and live order handling remain separate from Python results.',
                              'Frozen installed calendar is not a point-in-time exchange archive.',
                              'The earlier next-open attempt is retained separately from strict-expiry confirmation.',
                              'MNQ uses its own feed and economics; its P&L is not NQ P&L divided by ten.']}
    (REPORT / 'results.json').write_text(json.dumps(report, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    lines = ['# TSMOM ORB calendar repair: recorded results', '', report['conclusion'], '',
             f"Updated {report['generated_at_utc']}. {len(results)} attempts; {len(current)} current cases. Statuses: " +
             ', '.join(f'{k}: {v}' for k, v in report['status_counts'].items()) + '.', '',
             'The original 20/60/120/252 momentum, 0.5 threshold, 15-minute opening range, 2R target and one-contract cap were retained. NQ uses a $2,500 planned-risk filter and MNQ $250: both allow at most 125 points of planned stop distance for one contract. This is not a maximum-loss guarantee.', '',
             '| Case | Status | Net P&L | Trades | Marked DD | After close | Check |',
             '| --- | --- | ---: | ---: | ---: | ---: | --- |']
    for row in results:
        metric = row.get('metrics', {}); calendar = row.get('calendar_audit', {})
        dd = f"{metric['max_drawdown']:.2%}" if metric else '—'
        lines.append(f"| {row['case']} | {row['status']} | {money(metric.get('net_pnl'))} | {metric.get('trades', '—')} | {dd} | {calendar.get('after_close_count', '—')} | {row['audit_state']} |")
    lines += ['', '`MNQ-next-open` is the earlier inclusive-expiry attempt. `MNQ-next-open-strict-expiry` is the current confirmation; the earlier result remains visible. Close-mode cases use the earlier snapshot, which differs only in expiry expressions that close fills do not evaluate.', '',
              'Baseline per-side fees/slippage: NQ $1.25 + one 0.25-point tick; MNQ $0.62 + one 0.25-point tick. Double-cost cases double both. Limit exits pay commission only. Equity drawdown uses recorded bar-close marks, not intrabar extrema.', '',
              '## Original NQ baselines versus repaired baselines', '',
              '| Year | Original net | Repaired net | Difference | Original carries | Repaired carries |',
              '| --- | ---: | ---: | ---: | ---: | ---: |']
    for row in comparisons:
        original = row['original']; fixed = row.get('fixed_metrics') or {}; fixed_cal = row.get('fixed_calendar_audit') or {}
        lines.append(f"| {row['year']} | {money(original.get('metrics', {}).get('net_pnl'))} | {money(fixed.get('net_pnl'))} | {money(row['net_pnl_change'])} | {original.get('calendar_audit', {}).get('overnight_carry_count', '—')} | {fixed_cal.get('overnight_carry_count', '—')} |")
    lines += ['', '## The nine previously carried trades', '',
              '| Entry ET | Original exit ET | Repaired exit ET | Resolution |',
              '| --- | --- | --- | --- |']
    for row in original_carries:
        original = row['original']; matches = row['fixed_matching_entry_trades']
        fixed_exits = ', '.join(t['exit_et'] for t in matches) or '—'
        lines.append(f"| {original['entry_et']} | {original['exit_et']} | {fixed_exits} | {row['resolution']} |")
    failures = [row for row in results if row['failures']]
    if failures:
        lines += ['', '## Unresolved checks', '']
        lines.extend(f"- {row['case']}: {'; '.join(row['failures'])}" for row in failures)
    lines += ['', 'All attempt IDs, exact source and artifact hashes, reconciliation results and calendar checks are in [results.json](results.json). Original selection provenance remains in [selection.json](../../ninjatrader/working_nq_to_mnq/selection.json).', '',
              'These are historical regression results from previously inspected data. They do not establish untouched holdout performance or NinjaTrader live execution parity. No original runs were retagged or modified.', '']
    (REPORT / 'RESULTS.md').write_text('\n'.join(lines), encoding='utf-8')
    print(json.dumps({key: report[key] for key in ['all_attempts_terminal', 'attempt_count', 'status_counts',
                                                 'current_cases_all_checks_pass', 'current_source_behavior_supported', 'conclusion']}, indent=2))


if __name__ == '__main__':
    main()
