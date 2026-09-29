"""Verify and report the isolated candle-body versus wick-boundary experiment.

Reads saved ledgers; never reruns or selects parameters. Every declared case,
including failed and zero-trade cases, remains visible. --require-complete also
requires exact trade/equity parity against the prior frozen wick campaign.
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
OUT = ROOT / 'reports/snd-body-retest-2026-09-24'
PRIOR = ROOT / 'reports/snd-fresh-retest-2026-09-24'
HELPER_PATH = ROOT / 'scripts/report-snd-fresh-retest.py'
spec = importlib.util.spec_from_file_location('body_retest_fresh_report_helper', HELPER_PATH)
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)

checksum, clean, save, read = helper.checksum, helper.clean, helper.save, helper.read_json
number, table = helper.number, helper.table
FIELDS = list(dict.fromkeys(helper.FIELDS + ['median_risk_points', 'double_cost_repricing_net']))
COMPARE_FIELDS = ['trades', 'net_pnl', 'closed_trade_pnl', 'profit_factor', 'win_rate',
                  'max_drawdown_dollars', 'mean_net_r', 'median_risk_points', 'costs',
                  'double_cost_repricing_net']
SYMBOLS = ['MNQ', 'MGC', 'NQ', 'ES', 'YM', 'CL']
PERIOD_LABELS = {'all': 'Full history: January 2022–July 2026',
                 'development': 'January 2022–December 2024',
                 'year_2024': 'Calendar 2024', 'later_2025': 'Calendar 2025',
                 'latest_2026': 'January–July 2026',
                 'later_combined': 'Later history: January 2025–July 2026'}
REQUIRED_SOURCES = [
    'scripts/report-snd-fresh-retest.py',
    'scripts/report-transcript-supply-demand.py', 'scripts/analyze-transcript-supply-demand.py',
    'workbench/metrics.py', 'workbench/contract.py',
]


def check_source_set(out, protocol_hash):
    checks, manifest = helper.verify_sources(out, protocol_hash)
    if manifest:
        files = manifest.get('files', [])
        aggregate = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
        checks['computed_source_hash'] = aggregate
        if aggregate != manifest.get('source_hash'):
            checks['errors'].append('Source manifest aggregate identity mismatch')
        frozen_names = {item['path'].replace('\\', '/') for item in files}
        for name in REQUIRED_SOURCES:
            if name not in frozen_names:
                checks['errors'].append('Reporting dependency was not frozen: ' + name)
    checks['verified'] = not checks['errors']
    return checks, manifest


def check_dataset_files(datasets):
    checks, seen = [], {}
    for dataset in datasets:
        for item in dataset['files']:
            path = Path(item['path'])
            if str(path) not in seen:
                seen[str(path)] = checksum(path) if path.is_file() else None
            actual = seen[str(path)]
            checks.append(dict(symbol=dataset['symbol'], path=str(path),
                               expected_checksum=item['checksum'], checksum=actual,
                               verified=actual is not None and actual == item['checksum']))
    return dict(verified=bool(checks) and all(row['verified'] for row in checks), files=checks)


def prior_campaign(protocol):
    """Verify the prior frozen evidence, without requiring old working files."""
    path = Path(protocol.get('prior_campaign', str(PRIOR))) / 'protocol.json'
    checks = dict(protocol_path=str(path), errors=[], frozen_files=[])
    if not protocol.get('prior_protocol_checksum'):
        checks['errors'].append('New protocol does not anchor the prior protocol checksum')
    if not path.is_file():
        checks['errors'].append('Prior protocol is missing')
        checks['verified'] = False
        return checks, None, None, path.parent
    actual = checksum(path)
    checks['protocol_checksum'] = actual
    checks['expected_protocol_checksum'] = protocol.get('prior_protocol_checksum')
    if actual != protocol.get('prior_protocol_checksum'):
        checks['errors'].append('Prior protocol checksum does not match new declaration')
    previous = read(path)
    manifest_path = path.parent / 'source-manifest.json'
    if not manifest_path.is_file():
        checks['errors'].append('Prior source manifest is missing')
        checks['verified'] = False
        return checks, previous, None, path.parent
    manifest = read(manifest_path)
    checks['manifest_checksum'] = checksum(manifest_path)
    checks['expected_manifest_checksum'] = protocol.get('prior_manifest_checksum')
    if checks['manifest_checksum'] != protocol.get('prior_manifest_checksum'):
        checks['errors'].append('Prior source manifest differs from new declaration')
    checks['source_hash'] = manifest.get('source_hash')
    if manifest.get('protocol_checksum') != actual:
        checks['errors'].append('Prior manifest protocol identity mismatch')
    files = manifest.get('files', [])
    aggregate = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
    if not files or aggregate != manifest.get('source_hash'):
        checks['errors'].append('Prior source aggregate identity mismatch')
    for item in files:
        frozen = helper.safely_beneath(path.parent / 'source', item['path'])
        digest = checksum(frozen) if frozen.is_file() else None
        passed = digest is not None and digest == item['checksum']
        checks['frozen_files'].append(dict(path=item['path'], checksum=digest,
                                          expected_checksum=item['checksum'], verified=passed))
        if not passed:
            checks['errors'].append('Prior frozen source missing or changed: ' + item['path'])
    checks['verified'] = not checks['errors']
    return checks, previous, manifest, path.parent


def dataset_identity(dataset):
    return {key: dataset.get(key) for key in
            ('symbol', 'start', 'end', 'tick_size', 'point_value', 'execution_minutes')} | {
                'file_checksums': [item['checksum'] for item in dataset.get('files', [])]}


def baseline_parity(definition, trades, equity, protocol, previous, prior_manifest, prior_out):
    """Exact saved ledger equality after both evidence chains verify."""
    symbol, variant = definition['symbol'], definition['variant']
    prior_variant = 'candidate' if variant == 'wick_control' else 'double_cost'
    record = dict(symbol=symbol, variant=variant, prior_variant=prior_variant,
                  status='unavailable', errors=[])
    if trades is None or equity is None or not previous or not prior_manifest:
        record['errors'].append('New or prior verified ledgers are unavailable')
        return record
    try:
        old_definition = next(case for case in previous['cases']
                              if (case['symbol'], case['variant']) == (symbol, prior_variant))
        old_dataset = next(dataset for dataset in previous['datasets'] if dataset['symbol'] == symbol)
        new_dataset = next(dataset for dataset in protocol['datasets'] if dataset['symbol'] == symbol)
        comparisons = {
            'dataset_identity': dataset_identity(old_dataset) == dataset_identity(new_dataset),
            'capital': previous.get('capital') == protocol.get('capital'),
            'periods': previous.get('periods') == protocol.get('periods'),
            'wick_boundary': definition['parameters'].get('zone_boundary') == 'wick',
            'parameters_except_boundary': {key: value for key, value in definition['parameters'].items()
                                            if key != 'zone_boundary'} == old_definition['parameters'],
            'fee': definition.get('fee') == old_definition.get('fee'),
            'slippage_ticks': definition.get('slippage_ticks') == old_definition.get('slippage_ticks'),
        }
        record['protocol_alignment'] = comparisons
        record['errors'].extend('Prior/new input mismatch: ' + key for key, valid in comparisons.items() if not valid)
        verification, result, old_trades, old_equity = helper.verify_case(
            prior_out / symbol / prior_variant, old_definition, old_dataset,
            checksum(prior_out / 'protocol.json'), prior_manifest.get('source_hash'), float(previous['capital']))
        record['prior_verification'] = verification
        if verification['status'] != 'succeeded':
            record['errors'].append('Prior case failed artifact/accounting verification')
        else:
            for name, old, new in [('trades.csv', old_trades, trades), ('equity.parquet', old_equity, equity)]:
                identity = dict(prior_rows=len(old), new_rows=len(new))
                try:
                    pd.testing.assert_frame_equal(old, new, check_exact=True, check_dtype=True,
                                                  check_index_type=True, check_column_type=True)
                    identity['exact_values_and_schema'] = True
                except AssertionError as error:
                    identity['exact_values_and_schema'] = False
                    identity['difference'] = str(error)[:2000]
                    record['errors'].append('Prior/new exact ledger mismatch: ' + name)
                record[name] = identity
        record['status'] = 'verified' if not record['errors'] else 'verification_failed'
    except Exception as error:
        record['status'] = 'verification_failed'
        record['errors'].append(f'{type(error).__name__}: {error}')
    return record


def numeric_delta(body, wick):
    if body is None or wick is None:
        return None
    result = body - wick
    return float(result) if np.isfinite(result) else None


def comparisons(cases, definitions):
    index = {(case['symbol'], case['variant']): case for case in cases}
    rows = []
    for symbol in SYMBOLS:
        for scenario, wick_name, body_name in [('base_cost', 'wick_control', 'body'),
                                               ('double_cost', 'wick_double_cost', 'body_double_cost')]:
            if scenario == 'double_cost' and symbol not in ['MNQ', 'MGC']:
                continue
            wick, body = index.get((symbol, wick_name), {}), index.get((symbol, body_name), {})
            for period in definitions:
                wm, bm = wick.get('periods', {}).get(period, {}), body.get('periods', {}).get(period, {})
                row = dict(symbol=symbol, scenario=scenario, period=period,
                           wick_status=wick.get('status', 'missing'), body_status=body.get('status', 'missing'),
                           wick_zero_trade_case=wick.get('zero_trade_case'), body_zero_trade_case=body.get('zero_trade_case'))
                for field in COMPARE_FIELDS:
                    row['wick_' + field], row['body_' + field] = wm.get(field), bm.get(field)
                    row['delta_' + field] = numeric_delta(bm.get(field), wm.get(field))
                row['delta_win_rate_percentage_points'] = numeric_delta(
                    None if bm.get('win_rate') is None else 100 * bm['win_rate'],
                    None if wm.get('win_rate') is None else 100 * wm['win_rate'])
                rows.append(clean(row))
    return rows


def plot_comparison(out, ledgers, capital):
    if not ledgers:
        return None
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(3, 2, figsize=(14, 12), squeeze=False)
    for ax, symbol in zip(axes.flat, SYMBOLS):
        plotted = False
        for variant, color, label in [('wick_control', '#526a8a', 'Wick control'),
                                       ('body', '#e17b25', 'Candle bodies')]:
            equity = ledgers.get((symbol, variant))
            if equity is None:
                continue
            plotted = True
            ax.plot(pd.to_datetime(equity.timestamp, utc=True), equity.equity.to_numpy() - capital,
                    lw=.8, color=color, label=label)
        ax.axhline(0, lw=.6, color='#777777')
        ax.axvline(pd.Timestamp('2025-01-01', tz='UTC'), color='#999999', linestyle='--', lw=.8)
        ax.set_title(symbol + (' | one contract' if plotted else ' | verified evidence unavailable'))
        ax.set_ylabel('Cumulative net P&L (USD)')
        ax.grid(alpha=.18)
        ax.tick_params(axis='x', labelrotation=25)
        if plotted:
            ax.legend(loc='best', fontsize=8)
    fig.suptitle('Wick versus candle-body zones | observed marked equity\nPreviously inspected history; dashed line starts January 2025', fontsize=12)
    fig.tight_layout(rect=[0, 0, 1, .95])
    name = 'wick-vs-body-equity.png'
    fig.savefig(out / name, dpi=150)
    plt.close(fig)
    return name


def percent(value):
    return 'n/a' if value is None else number(100 * value, 1) + '%'


def result_rows(cases, period, variants=('wick_control', 'body')):
    rows = []
    for case in cases:
        if case['variant'] not in variants:
            continue
        m = case.get('periods', {}).get(period, {})
        rows.append([case['symbol'], case['variant'], case['status'], m.get('trades', 'n/a'),
                     number(m.get('net_pnl'), money=True), number(m.get('profit_factor')),
                     percent(m.get('win_rate')), number(m.get('max_drawdown_dollars'), money=True),
                     number(m.get('mean_net_r'), 3), number(m.get('median_risk_points'), 3),
                     number(m.get('costs'), money=True), number(m.get('double_cost_repricing_net'), money=True)])
    return rows


def make_report(analysis):
    complete = analysis['status'] == 'complete'
    verdict = ('All declared cases and baseline parity checks verified. This is a descriptive comparison of one boundary change on previously inspected history, not new forward validation.' if complete else
               'PARTIAL / UNVERIFIED: a declared case, source/input identity or baseline-parity check did not verify. These tables must not be treated as a completed comparison.')
    lines = ['# Candle-body versus wick supply/demand zones', '', verdict, '',
             f"Generated {analysis['generated_at']}. Verified cases: {analysis['completed_case_count']}/{analysis['declared_case_count']}; zero-trade cases: {len(analysis['zero_trade_cases'])}; exact prior-control ledger matches: {analysis['verified_parity_count']}/{analysis['expected_parity_count']}.", '',
             '## The isolated change', '',
             'Only zone boundaries change. For each formation candle, body high is max(open, close) and body low is min(open, close). Demand runs from the first candle\'s body high to the lowest body low of all three candles. Supply runs from the first candle\'s body low to the highest body high of all three. This applies to both aligned entry zones and the separate opposing-zone context pool.', '',
             'The three-candle qualification still requires the original wick fair-value gap and original candle colors. Swing structure, completed-hour alignment, wick-based physical touches and wick invalidation remain unchanged. This is not close-only invalidation: a wick through a body-defined distal boundary still invalidates that zone.', '',
             'The first physical return consumes eligibility. Only the completed first-touch bar may arm a stop entry one tick beyond its high/low for the next 5-minute bar. The stop remains one tick beyond the zone; target is 1R from actual gap-aware entry, with at least 2R of room to the nearest opposing zone (or no observed obstacle). Smaller zones can change touches, invalidation, risk, opposing room and subsequent trade availability. They do not merely rescale the same trades.', '',
             'Six markets use the same January 2022–July 2026 data and one fixed contract per separate $100,000 research account. Both primaries, MNQ and MGC, also rerun both boundaries at twice the commission and slippage. All 16 cases are declared before execution; no parameter search or new pass/fail profitability threshold is introduced.', '',
             '## Descriptive findings', '']
    base = [row for row in analysis['comparisons'] if row['scenario'] == 'base_cost' and row['period'] == 'all']
    if complete:
        higher = [row['symbol'] for row in base if row['delta_net_pnl'] is not None and row['delta_net_pnl'] > 0]
        lower = [row['symbol'] for row in base if row['delta_net_pnl'] is not None and row['delta_net_pnl'] < 0]
        lower_r = [row['symbol'] for row in base if row['delta_mean_net_r'] is not None and row['delta_mean_net_r'] < 0]
        lines.extend([f"Body boundaries increased full-history marked net P&L on {len(higher)}/6 markets ({', '.join(higher) or 'none'}) and decreased it on {len(lower)}/6 ({', '.join(lower) or 'none'}). Higher than the control does not mean positive or robust.", ''])
        lines.extend([f"Mean net R declined on {len(lower_r)}/6 markets ({', '.join(lower_r) or 'none'}). Dollar improvements and risk-normalized results therefore need separate assessment; this experiment does not support a general improvement from switching to candle bodies.", ''])
    for symbol in analysis['primary_markets']:
        all_row = next((r for r in base if r['symbol'] == symbol), {})
        later = next((r for r in analysis['comparisons'] if r['symbol'] == symbol and r['scenario'] == 'base_cost' and r['period'] == 'later_combined'), {})
        lines.extend([f"- **{symbol}:** full-history wick {number(all_row.get('wick_net_pnl'), money=True)}, body {number(all_row.get('body_net_pnl'), money=True)}, difference {number(all_row.get('delta_net_pnl'), money=True)}. Later-history wick {number(later.get('wick_net_pnl'), money=True)}, body {number(later.get('body_net_pnl'), money=True)}, difference {number(later.get('delta_net_pnl'), money=True)}."])
    lines.extend(['', '## Direct comparisons by period', '',
                  'Net P&L and drawdown use observed marked equity. PF, win rate, mean R, costs and median initial risk use trades closed in that period. Median risk is in instrument price points. The last column reprices those same saved trades with their original costs charged once more; it is not a new execution run.', ''])
    headers = ['Market', 'Boundary', 'Status', 'Trades', 'Marked net', 'Net PF', 'Win rate', 'Max DD', 'Mean net R', 'Median risk', 'Costs', 'Saved-trade 2× cost net']
    for period in analysis['period_definitions']:
        lines.extend(['### ' + PERIOD_LABELS.get(period, period), '',
                      table(headers, result_rows(analysis['cases'], period)), '',
                      '**Body minus wick:** positive DD means a larger drawdown; win-rate change is percentage points.', '',
                      table(['Market', 'Trades Δ', 'Net Δ', 'PF Δ', 'Win pp Δ', 'DD Δ', 'Mean R Δ', 'Median risk Δ', 'Costs Δ'],
                            [[r['symbol'], number(r.get('delta_trades'), 0), number(r.get('delta_net_pnl'), money=True),
                              number(r.get('delta_profit_factor')), number(r.get('delta_win_rate_percentage_points')),
                              number(r.get('delta_max_drawdown_dollars'), money=True), number(r.get('delta_mean_net_r'), 3),
                              number(r.get('delta_median_risk_points'), 3), number(r.get('delta_costs'), money=True)]
                             for r in analysis['comparisons'] if r['scenario'] == 'base_cost' and r['period'] == period]), ''])
    lines.extend(['## Actual doubled-cost reruns on both primary markets', '',
                  'These are full simulator reruns at twice the fee and slippage, distinct from saved-trade repricing. The inherited engine charges slippage in cash rather than shifting reference fills. Costs therefore do not alter fixed-size trade selection, but these runs do not model liquidity-driven fill changes. Base fees are per side: MNQ/MGC $1.25, other markets $2.50; base slippage is one adverse tick on entry and stop/market exits, with commission only on target exits.', ''])
    for period in analysis['period_definitions']:
        lines.extend(['### ' + PERIOD_LABELS.get(period, period), '',
                      table(headers, result_rows(analysis['cases'], period, ('wick_double_cost', 'body_double_cost'))), '',
                      table(['Market', 'Body minus wick net', 'PF Δ', 'Mean R Δ', 'DD Δ'],
                            [[r['symbol'], number(r.get('delta_net_pnl'), money=True), number(r.get('delta_profit_factor')),
                              number(r.get('delta_mean_net_r'), 3), number(r.get('delta_max_drawdown_dollars'), money=True)]
                             for r in analysis['comparisons'] if r['scenario'] == 'double_cost' and r['period'] == period]), ''])
    lines.extend(['## Cases and control parity', '',
                  table(['Market', 'Case', 'Status', 'Zero trades?', 'Trades', 'Entry zones created', 'Context zones created'],
                        [[c['symbol'], c['variant'], c['status'], c.get('zero_trade_case', 'unavailable'),
                          c.get('periods', {}).get('all', {}).get('trades', 'n/a'),
                          c.get('diagnostics', {}).get('zones_created', 'n/a'),
                          c.get('diagnostics', {}).get('context_zones_created', 'n/a')] for c in analysis['cases']]), '',
                  table(['Market', 'New control', 'Prior case', 'Exact trade/equity parity'],
                        [[p['symbol'], p['variant'], p['prior_variant'], p['status']] for p in analysis['baseline_parity']]), '',
                  'The eight control comparisons verify original artifact checksums and accounting, prior frozen source identity, matched data file checksums/date spans/contract economics, matched parameters except the explicit wick default, and exact values/schema for every trade and equity ledger column. Serialization hashes are recorded separately; ledger equality is exact, without a numeric tolerance.', ''])
    if analysis['unavailable_cases']:
        lines.extend(['Cases requiring attention: ' + '; '.join(analysis['unavailable_cases']) + '.', ''])
    if analysis['verification_errors']:
        lines.extend(['Verification issues:', ''] + ['- ' + item for item in analysis['verification_errors']] + [''])
    if analysis.get('independent_audit'):
        audit = analysis['independent_audit']
        lines.extend([f"The [independent raw-source audit](independent-audit.json) reports **{audit['status']}**, {audit.get('total_checks', 'n/a')} grouped checks across {audit.get('declared_cases', 'n/a')} cases. It reconstructs formation geometry, first touches, stops/entries, nearest live opposing room and accounting from saved raw prices. Its stated scope does not include independent swing/hourly-direction reconstruction or full exit-path replay. Audit identity matches this protocol and execution source manifest: {audit['identity_matches']}.", ''])
    lines.extend(['## Interpretation and limits', '',
                  'Narrower body zones need a deeper return and allow earlier wick invalidation. Their stops, targets and opposing room change together under the existing zone-based rules. The difference estimates the effect of substituting the boundary definition in this simulator; it is not a paired causal effect on identical trades.', '',
                  'This remains previously inspected historical evidence. There is no untouched holdout or forward-validation claim. Correlated equity futures are not independent replications. Contract sizes differ, so dollar results should not be ranked across markets or summed as a portfolio. One-contract cash averages weight wide-risk trades differently from equal-trade mean R.', '',
                  'Drawdown measures saved observed 5-minute marks, including the period opening mark, and cannot capture unobserved intrabar extremes. Marked yearly P&L includes open-position changes; closed-trade statistics assign whole trades by their exit convention. January–July 2026 is a partial year. No holding-time cap or session-end exit is added.', '',
                  'Incomplete buckets cannot create or arm zones but observed wicks can consume freshness and invalidate them. Intraminute stop/target ambiguity remains conservative. Identifiable contract transitions use the inherited idealized prior-close liquidation/reset; gold data lack contract IDs, so unidentified unadjusted roll effects remain. The existing indicator is not changed by this experiment.', '',
                  'Structured analysis also includes seeded 2,000-draw occupied-exit-week mean-R intervals, concentration, holding-time and small-risk diagnostics inherited from the earlier report. These exploratory pointwise intervals are not adjusted for case selection or dependence across weeks.', '',
                  '## Reproducible evidence', '',
                  '- [Frozen protocol](protocol.json) and [source manifest](source-manifest.json).',
                  '- [Direct comparisons and deltas](comparison.csv), [all case-period results](all-results.csv).',
                  '- [Structured analysis](analysis.json) and [source, accounting and exact parity verification](verification.json).',
                  '- Per-market/per-case trade, marked-equity and result files remain available beside this report.', ''])
    if analysis.get('chart'):
        lines.extend([f"![Wick versus body cumulative marked equity]({analysis['chart']})", ''])
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=OUT)
    parser.add_argument('--require-complete', action='store_true')
    args = parser.parse_args()
    out = args.output.resolve()
    protocol = read(out / 'protocol.json')
    protocol_hash = checksum(out / 'protocol.json')
    capital = float(protocol.get('capital', 100000))
    if capital != helper.helper.driver.CAPITAL:
        raise ValueError('Period helper assumes capital 100000; refusing a silent rebase')
    definitions = {'all': None, **protocol['periods']}
    analyzer_bytes = Path(__file__).read_bytes()
    analyzer_digest = hashlib.sha256(analyzer_bytes).hexdigest()
    analyzer_source = out / 'analysis-source' / (Path(__file__).stem + '-' + analyzer_digest[:16] + '.py')
    analyzer_source.parent.mkdir(parents=True, exist_ok=True)
    if analyzer_source.exists() and analyzer_source.read_bytes() != analyzer_bytes:
        raise ValueError('Existing analysis source differs; preserve it and use a distinct report output folder')
    analyzer_source.write_bytes(analyzer_bytes)
    sources, manifest = check_source_set(out, protocol_hash)
    dataset_checks = check_dataset_files(protocol['datasets'])
    old_checks, previous, prior_manifest, prior_out = prior_campaign(protocol)
    datasets = {dataset['symbol']: dataset for dataset in protocol['datasets']}
    declared = [(case['symbol'], case['variant']) for case in protocol['cases']]
    if len(declared) != len(set(declared)):
        raise ValueError('Duplicate case definitions in frozen protocol')
    expected = {(s, v) for s in SYMBOLS for v in ('wick_control', 'body')} | {
        (s, v) for s in ['MNQ', 'MGC'] for v in ('wick_double_cost', 'body_double_cost')}
    errors = []
    if set(declared) != expected or protocol.get('expected_cases', len(declared)) != len(declared):
        errors.append('Declared cases differ from the expected complete 16-case experiment')
    for label, checks in [('sources', sources), ('prior campaign', old_checks)]:
        errors.extend(label + ': ' + message for message in checks['errors'])
    if not dataset_checks['verified']:
        errors.append('One or more input data files failed checksum verification')
    cases, rows, verifications, parity, ledgers = [], [], [], [], {}
    for definition in protocol['cases']:
        symbol, variant = definition['symbol'], definition['variant']
        folder = out / symbol / variant
        case = dict(symbol=symbol, variant=variant, parameters=definition.get('parameters'),
                    fee=definition.get('fee'), slippage_ticks=definition.get('slippage_ticks'))
        trades = equity = None
        try:
            verification, original, trades, equity = helper.verify_case(
                folder, definition, datasets[symbol], protocol_hash, (manifest or {}).get('source_hash'), capital)
            case['status'] = verification['status']
            case['diagnostics'] = (original or {}).get('diagnostics', {})
            if case['status'] == 'succeeded':
                for field, expected_value in [('fee_per_side', definition.get('fee')),
                                              ('slippage_ticks_per_market_or_stop_side', definition.get('slippage_ticks'))]:
                    if case['diagnostics'].get(field) != expected_value:
                        raise ValueError('Resolved cost differs from declared cost: ' + field)
                case['periods'] = {period: helper.summarize(trades, equity, datasets[symbol], bounds)
                                   for period, bounds in definitions.items()}
                case['zero_trade_case'] = len(trades) == 0
                if variant in ('wick_control', 'body'):
                    ledgers[(symbol, variant)] = equity
            else:
                case['errors'] = verification.get('errors', [])
                case['failure'] = verification.get('failure')
        except Exception as error:
            case.update(status='verification_failed', errors=[f'{type(error).__name__}: {error}'])
            verification = dict(symbol=symbol, variant=variant, status=case['status'], errors=case['errors'])
            trades = equity = None
        if variant in ('wick_control', 'wick_double_cost'):
            check = baseline_parity(definition, trades, equity, protocol, previous, prior_manifest, prior_out)
            if trades is not None:
                for name in ('trades.csv', 'equity.parquet'):
                    if name in check:
                        new_hash, old_hash = checksum(folder / name), checksum(prior_out / symbol / check['prior_variant'] / name)
                        check[name].update(new_checksum=new_hash, prior_checksum=old_hash, byte_identical=new_hash == old_hash)
            parity.append(check)
            if check['status'] != 'verified':
                errors.append(f'{symbol}/{variant}: prior control parity {check["status"]}')
        for period in definitions:
            metrics = case.get('periods', {}).get(period, {})
            ci = metrics.get('mean_r_95ci', [None, None])
            rows.append(dict(symbol=symbol, variant=variant, period=period,
                             status=case['status'] if case['status'] != 'succeeded' else metrics.get('status', 'unavailable'),
                             zero_trade_case=case.get('zero_trade_case'),
                             **{field: metrics.get(field) for field in FIELDS}, ci_low=ci[0], ci_high=ci[1]))
        cases.append(case)
        verifications.append(verification)
    unavailable = [f"{case['symbol']}/{case['variant']} ({case['status']})" for case in cases if case['status'] != 'succeeded']
    if len(parity) != 8:
        errors.append('Expected eight prior-control parity comparisons')
    status = 'complete' if not unavailable and not errors else 'partial_or_unverified'
    now = datetime.now(timezone.utc).isoformat()
    analysis = dict(generated_at=now, status=status, declared_case_count=len(declared),
                    completed_case_count=sum(case['status'] == 'succeeded' for case in cases),
                    unavailable_cases=unavailable, verification_errors=errors,
                    zero_trade_cases=[f"{case['symbol']}/{case['variant']}" for case in cases if case.get('zero_trade_case')],
                    protocol_checksum=protocol_hash, source_hash=(manifest or {}).get('source_hash'),
                    capital=capital, primary_markets=protocol.get('primary_markets', ['MNQ', 'MGC']),
                    period_definitions=definitions, datasets=protocol['datasets'], cases=cases,
                    comparisons=comparisons(cases, definitions), baseline_parity=parity,
                    verified_parity_count=sum(check['status'] == 'verified' for check in parity), expected_parity_count=8,
                    equity_basis='Observed 5m bucket-close marks; period start is last mark at or before boundary.',
                    freshness='Previously inspected history; descriptive chronological checks, not untouched holdouts.',
                    boundary_scope='Open-close envelope only; applied to entry and opposing context. Wick FVG, touches and invalidation unchanged.',
                    eligible_for_working_label=False)
    audit_path = out / 'independent-audit.json'
    if audit_path.is_file():
        audit = read(audit_path)
        analysis['independent_audit'] = {
            'status': audit.get('status', 'unknown'), 'checksum': checksum(audit_path),
            'declared_cases': audit.get('declared_cases'), 'total_checks': audit.get('total_checks'),
            'identity_matches': audit.get('protocol_checksum') == protocol_hash and
                                audit.get('source_manifest_checksum') == checksum(out / 'source-manifest.json'),
        }
    verification = dict(generated_at=now, status=status, protocol_checksum=protocol_hash,
                        analyzer_checksum=checksum(Path(__file__)), report_helper_checksum=checksum(HELPER_PATH),
                        analyzer_snapshot=str(analyzer_source.relative_to(out)),
                        analyzer_snapshot_checksum=checksum(analyzer_source),
                        analyzer_scope='Reporting source captured at analysis time, after execution; model and inherited metric helpers were frozen before execution.',
                        period_helper_checksum=checksum(helper.HELPER), metric_driver_checksum=checksum(helper.helper.DRIVER_PATH),
                        sources=sources, dataset_inputs=dataset_checks, prior_campaign=old_checks,
                        cases=verifications, baseline_parity=parity, errors=errors,
                        independent_audit=analysis.get('independent_audit'))
    pd.DataFrame(rows).to_csv(out / 'all-results.csv', index=False)
    pd.DataFrame(analysis['comparisons']).to_csv(out / 'comparison.csv', index=False)
    try:
        analysis['chart'] = plot_comparison(out, ledgers, capital)
    except ImportError as error:
        analysis['chart'] = None
        analysis['chart_note'] = f'Optional matplotlib chart unavailable: {error}'
    save(out / 'verification.json', verification)
    analysis['outputs'] = {name: checksum(out / name) for name in ('all-results.csv', 'comparison.csv', 'verification.json')}
    if analysis.get('chart'):
        analysis['outputs'][analysis['chart']] = checksum(out / analysis['chart'])
    save(out / 'analysis.json', analysis)
    (out / 'REPORT.md').write_text(make_report(analysis), encoding='utf-8')
    print(f"{status}: {analysis['completed_case_count']}/{len(declared)} verified cases; {analysis['verified_parity_count']}/8 exact controls; {len(rows)} case-period rows.")
    if args.require_complete and status != 'complete':
        print('Incomplete/unverified experiment: ' + '; '.join(unavailable + errors), file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
