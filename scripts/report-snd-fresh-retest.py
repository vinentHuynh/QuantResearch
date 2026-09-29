"""Verify and report the frozen fresh-retest supply/demand experiment.

Reads saved ledgers only. Missing, failed, zero-trade and invalid cases remain
visible. --require-complete returns a failing exit code unless every declared
case succeeded and its artifacts/accounting/source identities verify.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'reports/snd-fresh-retest-2026-09-24'
HELPER = ROOT / 'scripts/report-transcript-supply-demand.py'
spec = importlib.util.spec_from_file_location('fresh_retest_period_helper', HELPER)
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)

FIELDS = [
    'trades', 'net_pnl', 'closed_trade_pnl', 'gross_pnl', 'costs',
    'profit_factor', 'win_rate', 'mean_net_r', 'expectancy',
    'double_cost_net', 'max_drawdown_dollars', 'max_drawdown', 'sharpe',
    'top_five_winner_net', 'net_excluding_top_five_winners',
    'median_holding_hours', 'max_holding_hours', 'fraction_held_over_24h',
    'minimum_risk_points', 'minimum_risk_cash', 'risk_at_most_one_tick_count',
    'net_r_below_minus_three_count', 'first', 'last',
]
NEARBY = ['pivot_1', 'pivot_3', 'target_075', 'target_125']


def checksum(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def clean(value):
    if isinstance(value, dict):
        return {str(key): clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(item) for item in value]
    if isinstance(value, np.generic):
        return clean(value.item())
    if isinstance(value, float) and not np.isfinite(value):
        return None
    if isinstance(value, (datetime, pd.Timestamp)):
        return value.isoformat()
    return value


def save(path, value):
    path.write_text(json.dumps(clean(value), indent=2, allow_nan=False), encoding='utf-8')


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def safely_beneath(folder, name):
    path = (folder / name).resolve()
    if not path.is_relative_to(folder.resolve()):
        raise ValueError(f'Artifact path escapes case directory: {name}')
    return path


def verify_sources(out, protocol_hash):
    path = out / 'source-manifest.json'
    checks = {'manifest_exists': path.is_file(), 'files': [], 'errors': []}
    if not path.exists():
        checks['errors'].append('Missing source-manifest.json')
        checks['verified'] = False
        return checks, None
    manifest = read_json(path)
    checks['manifest_checksum'] = checksum(path)
    checks['source_hash'] = manifest.get('source_hash')
    if manifest.get('protocol_checksum') != protocol_hash:
        checks['errors'].append('Manifest protocol checksum mismatch')
    files = manifest.get('files', [])
    if not files:
        checks['errors'].append('Source manifest contains no files')
    for item in files:
        relative = item['path']
        frozen = safely_beneath(out / 'source', relative)
        current = safely_beneath(ROOT, relative)
        row = {'path': relative, 'expected_checksum': item.get('checksum'),
               'frozen_checksum': checksum(frozen) if frozen.exists() else None,
               'current_checksum': checksum(current) if current.exists() else None}
        row['frozen_matches'] = row['frozen_checksum'] == row['expected_checksum']
        row['current_matches'] = row['current_checksum'] == row['expected_checksum']
        if not row['frozen_matches']:
            checks['errors'].append(f'Frozen source missing or changed: {relative}')
        if not row['current_matches']:
            checks['errors'].append(f'Current source differs from frozen source: {relative}')
        checks['files'].append(row)
    checks['verified'] = not checks['errors']
    return checks, manifest


def verify_case(folder, definition, dataset, protocol_hash, source_hash, capital):
    verification = {'symbol': definition['symbol'], 'variant': definition['variant'],
                    'artifacts': [], 'errors': [], 'accounting': {}}
    result_path = folder / 'result.json'
    if not result_path.exists():
        failure = folder / 'failed.json'
        verification['status'] = 'failed' if failure.exists() else 'missing'
        if failure.exists():
            verification['failure'] = read_json(failure)
            verification['artifacts'].append({'name': 'failed.json', 'checksum': checksum(failure)})
        return verification, None, None, None
    result = read_json(result_path)
    verification['artifacts'].append({'name': 'result.json', 'checksum': checksum(result_path)})
    if result.get('status') != 'succeeded':
        verification.update(status=result.get('status', 'failed'), failure=result)
        return verification, result, None, None
    if result.get('protocol_checksum') != protocol_hash:
        verification['errors'].append('Result protocol checksum mismatch')
    if not source_hash or result.get('source_hash') != source_hash:
        verification['errors'].append('Result source hash missing or mismatched')
    for key in ('symbol', 'variant'):
        if result.get(key) != definition[key]:
            verification['errors'].append(f'Result {key} differs from declared case')
    for key, expected in definition.get('parameters', {}).items():
        if result.get('parameters', {}).get(key) != expected:
            verification['errors'].append(f'Resolved parameter differs from declaration: {key}')
    artifacts = result.get('artifacts', [])
    if isinstance(artifacts, dict):
        artifacts = [{'name': name, 'checksum': digest} for name, digest in artifacts.items()]
    names = set()
    for item in artifacts:
        name = item['name']
        path = safely_beneath(folder, name)
        actual = checksum(path) if path.exists() else None
        matches = actual is not None and actual == item.get('checksum')
        verification['artifacts'].append({'name': name, 'checksum': actual,
                                          'expected_checksum': item.get('checksum'), 'matches': matches})
        names.add(name)
        if not matches:
            verification['errors'].append(f'Artifact missing or checksum mismatch: {name}')
    for name in ('trades.csv', 'equity.parquet'):
        if name not in names:
            verification['errors'].append(f'Required artifact absent from result manifest: {name}')
    # Hash auxiliary inputs/logs too, without pretending undeclared hashes were frozen.
    for path in sorted(folder.iterdir()):
        if path.is_file() and path.name not in names | {'result.json'}:
            verification['artifacts'].append({'name': path.name, 'checksum': checksum(path),
                                              'declared_in_result': False})
    if verification['errors']:
        verification['status'] = 'verification_failed'
        return verification, result, None, None
    trades, equity = pd.read_csv(folder / 'trades.csv'), pd.read_parquet(folder / 'equity.parquet')
    # An empty CSV has no values from which pandas can infer numeric dtypes.
    # Concentration/risk helpers still require typed columns for zero-trade cases.
    for field in ('gross_pnl', 'cost', 'net_pnl', 'net_r', 'risk', 'risk_cash', 'entry', 'stop', 'quantity'):
        if field in trades:
            trades[field] = pd.to_numeric(trades[field], errors='raise').astype(float)
    if equity.empty:
        raise ValueError('Equity ledger is empty')
    values = equity.equity.to_numpy(float)
    times = pd.to_datetime(equity.timestamp, utc=True)
    if not np.isfinite(values).all() or times.duplicated().any() or not times.is_monotonic_increasing:
        raise ValueError('Marked equity must be finite with strictly increasing unique timestamps')
    if len(trades):
        numeric = trades[['gross_pnl', 'cost', 'net_pnl', 'net_r', 'risk', 'entry', 'stop']].to_numpy(float)
        if not np.isfinite(numeric).all() or (trades.risk <= 0).any():
            raise ValueError('Trade economics must be finite and initial risks positive')
        np.testing.assert_allclose(trades.gross_pnl - trades.cost, trades.net_pnl, rtol=0, atol=1e-6)
        np.testing.assert_allclose(abs(trades.entry - trades.stop), trades.risk, rtol=0, atol=1e-6)
        np.testing.assert_allclose(trades.net_pnl / (trades.risk * dataset['point_value']), trades.net_r, rtol=1e-10, atol=1e-7)
        if 'risk_cash' in trades:
            np.testing.assert_allclose(trades.risk * dataset['point_value'], trades.risk_cash, rtol=0, atol=1e-6)
        if 'quantity' in trades and not (trades.quantity.abs() == 1).all():
            raise ValueError('Expected one fixed contract for every trade')
        if (pd.to_datetime(trades.exit_time, utc=True) < pd.to_datetime(trades.entry_time, utc=True)).any():
            raise ValueError('A trade exits before its entry')
    net = float(trades.net_pnl.sum())
    accounting = {'final_equity_minus_capital': float(values[-1] - capital),
                  'summed_trade_net_pnl': net,
                  'summed_gross_less_costs': float(trades.gross_pnl.sum() - trades.cost.sum()),
                  'absolute_reconciliation_error': abs(float(values[-1] - capital) - net),
                  'trade_count': len(trades), 'zero_trade_case': len(trades) == 0}
    np.testing.assert_allclose(values[-1] - capital, net, rtol=0, atol=1e-5)
    np.testing.assert_allclose(accounting['summed_gross_less_costs'], net, rtol=0, atol=1e-5)
    if 'net_pnl' in equity:
        np.testing.assert_allclose(equity.net_pnl.sum(), net, rtol=0, atol=1e-5)
    if {'balance', 'unrealized_pnl'}.issubset(equity):
        np.testing.assert_allclose(equity.balance + equity.unrealized_pnl, equity.equity, rtol=0, atol=1e-5)
        np.testing.assert_allclose(equity.unrealized_pnl.iloc[-1], 0, rtol=0, atol=1e-6)
    verification.update(status='succeeded', accounting=accounting)
    return verification, result, trades, equity


def summarize(trades, equity, dataset, bounds):
    metrics = helper.summarize_period(trades, equity, *(bounds or []))
    cohort = trades if bounds is None else trades.loc[helper.trade_mask(trades, helper.utc(bounds[0]), helper.utc(bounds[1]))]
    risk = cohort.risk.astype(float)
    tick = float(dataset['tick_size'])
    point_value = float(dataset['point_value'])
    metrics.update(
        double_cost_repricing_net=metrics.get('double_cost_net'),
        stress_basis='Reprice saved closed trades by subtracting their original costs once more; fills, risk and trade selection are unchanged. This is distinct from the double_cost simulator rerun.',
        drawdown_basis='Peak-to-trough loss from every saved observed 5m bucket-end equity mark, including the period starting mark; not an intrabar or daily-only drawdown.',
        minimum_risk_points=float(risk.min()) if len(risk) else None,
        minimum_risk_cash=float(risk.min() * point_value) if len(risk) else None,
        risk_points_01_quantile=float(risk.quantile(.01)) if len(risk) else None,
        median_risk_points=float(risk.median()) if len(risk) else None,
        risk_at_most_one_tick_count=int((risk <= tick + 1e-7).sum()),
        net_r_below_minus_three_count=int((cohort.net_r < -3).sum()),
        minimum_net_r=float(cohort.net_r.min()) if len(cohort) else None,
        maximum_net_r=float(cohort.net_r.max()) if len(cohort) else None,
        occupied_exit_weeks=int(pd.to_datetime(cohort.exit_time, utc=True).dt.strftime('%G-%V').nunique()),
    )
    if 'opposing_boundary' in cohort:
        metrics['no_observed_opposing_obstacle_trades'] = int(cohort.opposing_boundary.isna().sum())
        metrics['observed_opposing_obstacle_trades'] = int(cohort.opposing_boundary.notna().sum())
        metrics['opposing_room_null_definition'] = 'A missing opposing boundary and infinite room in the raw ledger mean no observed obstacle; they are not missing trade risk.'
    if len(cohort):
        worst = cohort.loc[cohort.net_r.nsmallest(5).index]
        fields = [name for name in ('entry_time', 'exit_time', 'risk', 'risk_cash', 'net_pnl', 'net_r', 'exit_reason') if name in worst]
        metrics['five_lowest_r_trades'] = worst[fields].to_dict('records')
        positive = cohort.loc[cohort.net_pnl > 0, 'net_pnl'].sum()
        metrics['top_five_share_of_winning_pnl'] = float(metrics.get('top_five_winner_net', 0) / positive) if positive else None
    return clean(metrics)


def gate_for(symbol, cases):
    by_variant = {case['variant']: case for case in cases if case['symbol'] == symbol}
    candidate = by_variant.get('candidate')
    gate = {'symbol': symbol, 'status': 'unavailable', 'eligible_for_working_label': False}
    if not candidate or candidate['status'] != 'succeeded':
        return gate
    periods = candidate['periods']
    later = periods.get('later_combined', {})
    ci = later.get('mean_r_95ci', [None, None])
    stress = by_variant.get('double_cost', {})
    stress_later = stress.get('periods', {}).get('later_combined', {}) if stress.get('status') == 'succeeded' else {}
    checks = {
        'positive_full_history_marked_pnl': ((periods['all'].get('net_pnl') or 0) > 0, periods['all'].get('net_pnl'), '> 0 USD'),
        'at_least_100_later_closed_trades': (later.get('trades', 0) >= 100, later.get('trades'), '>= 100'),
        'positive_2024_marked_pnl': ((periods.get('year_2024', {}).get('net_pnl') or 0) > 0, periods.get('year_2024', {}).get('net_pnl'), '> 0 USD'),
        'positive_2025_marked_pnl': ((periods.get('later_2025', {}).get('net_pnl') or 0) > 0, periods.get('later_2025', {}).get('net_pnl'), '> 0 USD'),
        'positive_jan_jul_2026_marked_pnl': ((periods.get('latest_2026', {}).get('net_pnl') or 0) > 0, periods.get('latest_2026', {}).get('net_pnl'), '> 0 USD'),
        'later_profit_factor_at_least_1_10': (later.get('profit_factor') is not None and later['profit_factor'] >= 1.10, later.get('profit_factor'), '>= 1.10'),
        'positive_later_true_double_cost_rerun': ((stress_later.get('net_pnl') or 0) > 0, stress_later.get('net_pnl'), '> 0 USD'),
        'later_week_cluster_mean_r_ci_lower_positive': (ci[0] is not None and ci[0] > 0, ci[0], '> 0 R'),
    }
    nearby = {}
    for name in NEARBY:
        case = by_variant.get(name, {})
        value = case.get('periods', {}).get('later_combined', {}).get('net_pnl') if case.get('status') == 'succeeded' else None
        nearby[name] = {'passed': value is not None and value > 0, 'later_marked_net_pnl': value, 'status': case.get('status', 'missing')}
    gate.update(status='evaluated', checks={key: {'passed': bool(passed), 'observed': value, 'threshold': threshold} for key, (passed, value, threshold) in checks.items()},
                all_numeric_checks_pass=all(item[0] for item in checks.values()), nearby_rule_checks=nearby,
                all_nearby_rules_positive=all(item['passed'] for item in nearby.values()),
                remaining_requirement='No automatic Working promotion. Historical numeric gates and nearby stability do not establish untouched holdout, forward performance, live execution or independently sized portfolio feasibility.')
    return gate


def number(value, digits=2, money=False):
    if value is None or isinstance(value, float) and not np.isfinite(value):
        return 'n/a'
    return ('$' if money else '') + f'{value:,.{digits}f}'


def table(headers, rows):
    return '\n'.join(['| ' + ' | '.join(headers) + ' |', '| ' + ' | '.join(['---'] * len(headers)) + ' |'] + ['| ' + ' | '.join(str(value).replace('|', '/') for value in row) + ' |' for row in rows])


def plot_candidates(out, ledgers, capital):
    if not ledgers:
        return None
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    count = len(ledgers)
    fig, axes = plt.subplots((count + 1) // 2, 2, figsize=(13, 3.3 * ((count + 1) // 2)), squeeze=False)
    for ax, (symbol, equity) in zip(axes.flat, ledgers.items()):
        # Plot every observed mark; visual downsampling cannot change reported risk.
        times = pd.to_datetime(equity.timestamp, utc=True)
        ax.plot(times, equity.equity.to_numpy() - capital, lw=.8, color='#175f99')
        ax.axhline(0, lw=.6, color='#777777')
        ax.axvline(pd.Timestamp('2025-01-01', tz='UTC'), color='#b56a22', linestyle='--', lw=.8)
        ax.set_title(symbol + ' | one contract')
        ax.set_ylabel('Cumulative net P&L (USD)')
        ax.grid(alpha=.18)
        ax.tick_params(axis='x', labelrotation=25)
    for ax in list(axes.flat)[count:]:
        ax.set_visible(False)
    fig.suptitle('Fresh retest candidate | observed marked equity\nDashed line: start of later historical checks; previously inspected data', fontsize=12)
    fig.tight_layout(rect=[0, 0, 1, .95])
    path = out / 'candidate-equity.png'
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path.name


def make_report(analysis):
    cases, gates = analysis['cases'], analysis['primary_gates']
    candidates = [case for case in cases if case['variant'] == 'candidate']
    complete = analysis['status'] == 'complete'
    passing = [symbol for symbol, gate in gates.items() if gate.get('all_numeric_checks_pass') and gate.get('all_nearby_rules_positive')]
    verdict = ('The candidate passed the declared historical numeric and nearby-rule checks on ' + ', '.join(passing) + '. This does not establish forward profitability.') if passing else 'The candidate has not passed the declared historical validation gates on either primary market.'
    if not complete:
        verdict = 'PARTIAL / UNVERIFIED RESEARCH: the declared campaign is incomplete or failed verification. No final validation conclusion is available.'
    lines = ['# Supply/demand fresh retest: frozen experiment', '', verdict, '',
             f"Generated {analysis['generated_at']}. Verified successful cases: {analysis['completed_case_count']}/{analysis['declared_case_count']}; zero-trade cases: {len(analysis['zero_trade_cases'])}.", '',
             '## Strategy and frozen scope', '',
             'The candidate combines the first physical touch, at least 2R of room to an active opposing zone (or no opposing zone), completed hourly directional alignment, and a stop one tick beyond the zone. It uses 5-minute zone formations and a 1R target from the actual gap-aware entry. A first-touch order is eligible only on the next 5-minute bar; a missed or blocked touch is consumed. One position and one fixed contract are allowed.', '',
             'FVG formation remains in the candidate because its dollar evidence was favorable, while its weaker mean-R evidence is tested explicitly by removing that requirement. No RVOL, large-departure or extra BOS filter is added. The hourly/5-minute trend definition still uses confirmed swing breaks. There is no opposing-zone exit, session-end exit or holding-time cap.', '',
             'All cases were declared before this campaign. Four variants run on every market (candidate, without_first_touch, without_room, legacy_control); the primary markets also test removing hourly alignment/FVG, nearby pivots and targets, doubled costs, and added slippage. The legacy control disables both new rules. Existing historical data has already been inspected; later periods are chronological checks, not fresh holdouts.', '',
             '## Candidate results: full available history', '',
             table(['Market', 'Status', 'Trades', 'Net P&L', 'Net PF', 'Mean net R', 'Observed max DD'], [[case['symbol'], case['status'], case.get('periods', {}).get('all', {}).get('trades', 'n/a'), number(case.get('periods', {}).get('all', {}).get('net_pnl'), money=True), number(case.get('periods', {}).get('all', {}).get('profit_factor')), number(case.get('periods', {}).get('all', {}).get('mean_net_r'), 3), number(case.get('periods', {}).get('all', {}).get('max_drawdown_dollars'), money=True)] for case in candidates]), '',
             'Each market is a separate $100,000 research account. Dollar outcomes across differently sized contracts are not directly comparable or summed into a portfolio.', '',
             '## Primary-market chronology and declared gates', '']
    for symbol, gate in gates.items():
        case = next((case for case in candidates if case['symbol'] == symbol), {})
        lines.extend([f'### {symbol}', '', table(['Period', 'Closed trades', 'Marked net P&L', 'Closed-trade net P&L', 'PF', 'Mean R [95% CI]', 'Observed max DD'], [[period, metrics.get('trades', 'n/a'), number(metrics.get('net_pnl'), money=True), number(metrics.get('closed_trade_pnl'), money=True), number(metrics.get('profit_factor')), number(metrics.get('mean_net_r'), 3) + ' [' + ', '.join(number(value, 3) for value in metrics.get('mean_r_95ci', [None, None])) + ']', number(metrics.get('max_drawdown_dollars'), money=True)] for period, metrics in case.get('periods', {}).items()]), ''])
        if gate.get('checks'):
            lines.extend([table(['Declared check', 'Observed', 'Threshold', 'Result'], [[name.replace('_', ' '), number(check['observed'], 3), check['threshold'], 'PASS' if check['passed'] else 'FAIL'] for name, check in gate['checks'].items()]), '', table(['Nearby rule', 'Later marked net P&L', 'Positive?'], [[name, number(check['later_marked_net_pnl'], money=True), 'PASS' if check['passed'] else 'FAIL / unavailable'] for name, check in gate['nearby_rule_checks'].items()]), ''])
        else:
            lines.extend(['Gate unavailable because the candidate is missing or unverified.', ''])
    lines.extend(['## Every declared variant: later January 2025–July 2026', '',
                  table(['Market', 'Variant', 'Status', 'Trades', 'Marked net', 'PF', 'Mean R', '95% CI'], [[case['symbol'], case['variant'], case['status'], case.get('periods', {}).get('later_combined', {}).get('trades', 'n/a'), number(case.get('periods', {}).get('later_combined', {}).get('net_pnl'), money=True), number(case.get('periods', {}).get('later_combined', {}).get('profit_factor')), number(case.get('periods', {}).get('later_combined', {}).get('mean_net_r'), 3), '[' + ', '.join(number(value, 3) for value in case.get('periods', {}).get('later_combined', {}).get('mean_r_95ci', [None, None])) + ']'] for case in cases]), '',
                  'Removal comparisons estimate what changed when one rule was disabled in this simulator. Trade selection and subsequent availability can also change, so differences are not paired causal treatment effects.', '',
                  '## Costs, concentration, holding time and small-risk diagnostics', '',
                  table(['Primary market', 'Base later closed net', 'Saved-trade double-cost repricing', 'True double-cost rerun: later marked net', 'Extra-slippage rerun: later marked net'], [[symbol, number(next((case for case in candidates if case['symbol'] == symbol), {}).get('periods', {}).get('later_combined', {}).get('closed_trade_pnl'), money=True), number(next((case for case in candidates if case['symbol'] == symbol), {}).get('periods', {}).get('later_combined', {}).get('double_cost_repricing_net'), money=True), number(next((case for case in cases if case['symbol'] == symbol and case['variant'] == 'double_cost'), {}).get('periods', {}).get('later_combined', {}).get('net_pnl'), money=True), number(next((case for case in cases if case['symbol'] == symbol and case['variant'] == 'extra_slippage'), {}).get('periods', {}).get('later_combined', {}).get('net_pnl'), money=True)] for symbol in analysis['primary_markets']]), '',
                  'Repricing subtracts the saved costs again and holds the original trades fixed. The actual stress rerun executes the simulator again with higher fees/slippage; the gate uses that rerun. This engine represents slippage as cash charges without changing reference fills or price risk, so cost-only reruns should preserve trade selection. They do not model liquidity-driven fill changes. Fees are per side, and adverse slippage is charged on entry and market/stop exits; target exits pay fees only.', '',
                  table(['Market', 'All-history net after removing five largest winners', 'Median / max holding hours', 'Min initial price risk', 'Risk <= 1 tick', 'Net R < -3'], [[case['symbol'], number(case.get('periods', {}).get('all', {}).get('net_excluding_top_five_winners'), money=True), number(case.get('periods', {}).get('all', {}).get('median_holding_hours')) + ' / ' + number(case.get('periods', {}).get('all', {}).get('max_holding_hours')), number(case.get('periods', {}).get('all', {}).get('minimum_risk_points'), 4), case.get('periods', {}).get('all', {}).get('risk_at_most_one_tick_count', 'n/a'), case.get('periods', {}).get('all', {}).get('net_r_below_minus_three_count', 'n/a')] for case in candidates]), '',
                  'Cash expectancy is mean USD per closed trade; mean net R averages each trade after dividing by its own initial risk in dollars. Fixed one-contract sizing weights wide-stop trades more in cash results. Positive cash and negative mean R can coexist. Small initial risks can amplify costs and gap losses in R; these diagnostics are disclosed rather than filtered after seeing results.', '',
                  'No time stop means some 5-minute setups can hold through many sessions. Maximum drawdown uses all saved observed 5-minute marks and the opening account mark, but cannot measure unobserved intrabar extremes. Yearly marked P&L includes open positions at the boundary; closed-trade P&L assigns whole trades by their exit and can differ.', '',
                  '## Execution diagnostics and verification', ''])
    for case in candidates:
        if case.get('diagnostics'):
            lines.extend([f"**{case['symbol']} candidate diagnostics:**", '', '```json', json.dumps(clean(case['diagnostics']), indent=2), '```', ''])
    if analysis['unavailable_cases']:
        lines.extend(['Cases requiring attention: ' + ', '.join(analysis['unavailable_cases']) + '.', ''])
    lines.extend(['Every declared artifact is checksum checked, auxiliary case files are hashed, and every successful case reconciles final marked equity, summed trade net P&L and gross P&L minus costs. Trade risk and net R are checked independently. Source snapshots and current source checksums are compared with the frozen manifest. Full details are in [verification.json](verification.json).', '',
                  'The 95% mean-R intervals use 2,000 seeded occupied-exit-week bootstrap draws, resampling weekly R totals and trade counts together. At least 20 trades and 10 occupied weeks are required. They are pointwise exploratory intervals; they do not correct for 40-case selection or preserve dependence across weeks.', '',
                  'Equity futures share common exposure, so cross-market agreement is not independent replication. Gold minute caches lack instrument IDs; exact continuous-contract roll effects cannot be identified. Identifiable futures rolls flatten and reset state. Missing intervals, bar ordering and conservative stop/target collision assumptions limit execution precision. January–July 2026 is a partial year. No automatic Working promotion or untouched-holdout claim is made.', '',
                  '## Reproducible artifacts', '',
                  '- [Frozen protocol](protocol.json) and [source manifest](source-manifest.json).',
                  '- [All case-period results](all-results.csv), including failed and zero-trade cases.',
                  '- [Structured analysis](analysis.json), full concentration/holding/risk records and gates.',
                  '- Per-market/per-variant result, trade and marked-equity ledgers remain unchanged.', ''])
    if analysis.get('chart'):
        lines.extend([f"![Candidate cumulative marked equity]({analysis['chart']})", ''])
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=OUT)
    parser.add_argument('--require-complete', action='store_true')
    args = parser.parse_args()
    out = args.output.resolve()
    protocol_path = out / 'protocol.json'
    protocol = read_json(protocol_path)
    protocol_hash = checksum(protocol_path)
    capital = float(protocol.get('capital', 100000))
    if capital != helper.driver.CAPITAL:
        raise ValueError('Period helper assumes capital 100000; refusing a silent rebase')
    definitions = {'all': None, **protocol['periods']}
    sources, manifest = verify_sources(out, protocol_hash)
    datasets = {dataset['symbol']: dataset for dataset in protocol['datasets']}
    cases, rows, verifications, candidate_ledgers = [], [], [], {}
    declared = [(case['symbol'], case['variant']) for case in protocol['cases']]
    if len(declared) != len(set(declared)):
        raise ValueError('Duplicate case definitions in frozen protocol')
    for definition in protocol['cases']:
        symbol, variant = definition['symbol'], definition['variant']
        folder = out / symbol / variant
        case = dict(symbol=symbol, variant=variant, parameters=definition.get('parameters'),
                    fee=definition.get('fee'), slippage_ticks=definition.get('slippage_ticks'))
        try:
            verification, original, trades, equity = verify_case(folder, definition, datasets[symbol], protocol_hash, (manifest or {}).get('source_hash'), capital)
            case['status'] = verification['status']
            case['diagnostics'] = (original or {}).get('diagnostics', {})
            if case['status'] == 'succeeded':
                case['periods'] = {period: summarize(trades, equity, datasets[symbol], bounds) for period, bounds in definitions.items()}
                case['zero_trade_case'] = len(trades) == 0
                if variant == 'candidate':
                    candidate_ledgers[symbol] = equity
            else:
                case['errors'] = verification.get('errors', [])
                case['failure'] = verification.get('failure')
        except Exception as exc:
            case.update(status='verification_failed', errors=[f'{type(exc).__name__}: {exc}'])
            verification = dict(symbol=symbol, variant=variant, status=case['status'], errors=case['errors'])
        for period in definitions:
            metrics = case.get('periods', {}).get(period, {})
            ci = metrics.get('mean_r_95ci', [None, None])
            rows.append(dict(symbol=symbol, variant=variant, period=period,
                             status=case['status'] if case['status'] != 'succeeded' else metrics.get('status', 'unavailable'),
                             zero_trade_case=case.get('zero_trade_case'),
                             **{field: metrics.get(field) for field in FIELDS},
                             ci_low=ci[0], ci_high=ci[1], double_cost_repricing_net=metrics.get('double_cost_repricing_net')))
        cases.append(case)
        verifications.append(verification)
    unavailable = [f"{case['symbol']}/{case['variant']} ({case['status']})" for case in cases if case['status'] != 'succeeded']
    status = 'complete' if not unavailable and sources['verified'] else 'partial_or_unverified'
    now = datetime.now(timezone.utc).isoformat()
    primary = protocol.get('primary_markets', ['MNQ', 'MGC'])
    analysis = dict(generated_at=now, status=status, declared_case_count=len(declared),
                    completed_case_count=sum(case['status'] == 'succeeded' for case in cases),
                    unavailable_cases=unavailable,
                    zero_trade_cases=[f"{case['symbol']}/{case['variant']}" for case in cases if case.get('zero_trade_case')],
                    protocol_checksum=protocol_hash, source_hash=(manifest or {}).get('source_hash'),
                    capital=capital, primary_markets=primary, period_definitions=definitions,
                    primary_gates={symbol: gate_for(symbol, cases) for symbol in primary},
                    datasets=protocol['datasets'], cases=cases,
                    equity_basis='Observed 5m bucket-close mark-to-market; period start is last mark at or before boundary.',
                    uncertainty='2000 draws; seed 24092026; occupied exit-week clusters; pointwise mean net R interval; >=20 trades and >=10 weeks.',
                    freshness='Previously inspected historical data; chronological later checks, not untouched holdouts.',
                    cash_vs_r='One fixed contract. Mean USD and equal-trade mean R have different risk weighting; no risk-targeted or margin-constrained sizing has been validated.',
                    eligible_for_working_label=False)
    verification = dict(generated_at=now, status=status, protocol_checksum=protocol_hash,
                        analyzer_checksum=checksum(Path(__file__)), period_helper_checksum=checksum(HELPER),
                        metric_driver_checksum=checksum(helper.DRIVER_PATH), sources=sources, cases=verifications)
    pd.DataFrame(rows).to_csv(out / 'all-results.csv', index=False)
    try:
        analysis['chart'] = plot_candidates(out, candidate_ledgers, capital)
    except ImportError as exc:
        analysis['chart'] = None
        analysis['chart_note'] = f'Optional matplotlib chart unavailable: {exc}'
    save(out / 'verification.json', verification)
    analysis['outputs'] = {name: checksum(out / name) for name in ('all-results.csv', 'verification.json')}
    if analysis.get('chart'):
        analysis['outputs'][analysis['chart']] = checksum(out / analysis['chart'])
    save(out / 'analysis.json', analysis)
    (out / 'REPORT.md').write_text(make_report(analysis), encoding='utf-8')
    print(f"{status}: {analysis['completed_case_count']}/{len(declared)} verified cases; {len(rows)} case-period rows.")
    for symbol, gate in analysis['primary_gates'].items():
        print(f"{symbol}: numeric gates={gate.get('all_numeric_checks_pass', False)}, nearby rules={gate.get('all_nearby_rules_positive', False)}")
    if args.require_complete and status != 'complete':
        print('Incomplete/unverified declared experiment: ' + '; '.join(unavailable + sources['errors']), file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
