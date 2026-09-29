"""Verify and report the frozen relaxed-FVG execution/entry research campaign.

Reads saved ledgers only; never chooses parameters or reruns a historical model.
All declared failures and zero-trade cases remain visible. Inherited accounting,
period conventions and uncertainty helpers are frozen with the execution source.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import inspect
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'reports/snd-entry-research-2026-09-25'
BODY_HELPER = ROOT / 'scripts/report-snd-body-retest.py'
spec = importlib.util.spec_from_file_location('entry_research_identity_helper', BODY_HELPER)
identity = importlib.util.module_from_spec(spec)
spec.loader.exec_module(identity)
helper = identity.helper
checksum, clean, save, read = helper.checksum, helper.clean, helper.save, helper.read_json
number, table = helper.number, helper.table
SYMBOLS = ['MNQ', 'MGC', 'NQ']
FACTORS = ['relaxed_first_1', 'relaxed_first_3', 'relaxed_any_1', 'relaxed_any_3']
STRICT_FACTORS = ['strict_control', 'strict_first_3', 'strict_any_1', 'strict_any_3']
NEIGHBORS = ['relaxed_pivot_1', 'relaxed_pivot_3', 'relaxed_target_075',
             'relaxed_target_125', 'relaxed_room_15', 'relaxed_room_25']
STRESSES = ['relaxed_first_1', 'relaxed_first_1_double_cost',
            'relaxed_first_1_price_1', 'relaxed_first_1_price_2',
            'relaxed_first_1_price_2_double_fee']
FIELDS = list(dict.fromkeys(helper.FIELDS + ['median_risk_points',
                     'modeled_execution_costs', 'embedded_price_slippage', 'recorded_cash_costs']))
DELTA_FIELDS = ['trades', 'net_pnl', 'profit_factor', 'mean_net_r',
                'max_drawdown_dollars', 'modeled_execution_costs']
PERIOD_LABELS = {'all': 'Full history: January 2022–July 2026',
                 'development': 'January 2022–December 2024',
                 'year_2024': 'Calendar 2024', 'later_2025': 'Calendar 2025',
                 'latest_2026': 'January–July 2026',
                 'later_combined': 'Later history: January 2025–July 2026'}


def expected_cases():
    common = [*STRICT_FACTORS, *FACTORS, 'relaxed_first_1_double_cost']
    return {(s, v) for s in SYMBOLS for v in common} | {
        ('MNQ', v) for v in [*[name + '_double_cost' for name in FACTORS[1:]],
                            *[name + '_price_2' for name in FACTORS],
                            'relaxed_first_1_price_1', 'relaxed_first_1_price_2_double_fee',
                            *NEIGHBORS]}


def prior_variant(symbol, variant):
    if variant == 'strict_control':
        return 'candidate'
    if variant == 'relaxed_first_1' and symbol in ('MNQ', 'MGC'):
        return 'without_fvg'
    return None


def parity_check(definition, trades, equity, protocol, previous, prior_manifest, prior_out):
    symbol, variant = definition['symbol'], definition['variant']
    old_variant = prior_variant(symbol, variant)
    record = dict(symbol=symbol, variant=variant, prior_variant=old_variant,
                  status='unavailable', errors=[])
    if trades is None or equity is None or not previous or not prior_manifest:
        record['errors'].append('Current or previous verified ledgers are unavailable')
        return record
    try:
        old_def = next(c for c in previous['cases'] if (c['symbol'], c['variant']) == (symbol, old_variant))
        old_data = next(d for d in previous['datasets'] if d['symbol'] == symbol)
        new_data = next(d for d in protocol['datasets'] if d['symbol'] == symbol)
        parameters = definition['parameters']
        defaults = {'zone_boundary': 'wick', 'entry_eligibility': 'first_touch',
                    'order_lifetime_bars': 1, 'slippage_model': 'cash'}
        checks = {
            'dataset_identity': identity.dataset_identity(old_data) == identity.dataset_identity(new_data),
            'capital': previous.get('capital') == protocol.get('capital'),
            'periods': previous.get('periods') == protocol.get('periods'),
            'shared_parameters': all(parameters.get(k) == v for k, v in old_def['parameters'].items()),
            'new_default_parameters': all(parameters.get(k, v) == v for k, v in defaults.items()),
            'fee': definition.get('fee') == old_def.get('fee'),
            'slippage_ticks': definition.get('slippage_ticks') == old_def.get('slippage_ticks'),
        }
        record['protocol_alignment'] = checks
        record['errors'].extend('Prior/new inputs differ: ' + k for k, passed in checks.items() if not passed)
        verification, _, old_trades, old_equity = helper.verify_case(
            prior_out / symbol / old_variant, old_def, old_data,
            checksum(prior_out / 'protocol.json'), prior_manifest.get('source_hash'), float(previous['capital']))
        record['prior_verification'] = verification
        if verification['status'] != 'succeeded':
            record['errors'].append('Prior artifact/accounting verification failed')
        else:
            for name, old, new in [('trades.csv', old_trades, trades), ('equity.parquet', old_equity, equity)]:
                item = dict(prior_rows=len(old), new_rows=len(new), compared_columns=list(old.columns),
                            new_audit_columns=[c for c in new.columns if c not in old.columns])
                try:
                    # New audit columns are allowed, but every original column is exact.
                    pd.testing.assert_frame_equal(old, new.loc[:, old.columns], check_exact=True, check_dtype=True)
                    if name == 'equity.parquet' and list(old.columns) != list(new.columns):
                        raise AssertionError('Equity column schema changed')
                    item['all_prior_columns_exact'] = True
                except (AssertionError, KeyError) as error:
                    item['all_prior_columns_exact'] = False
                    item['difference'] = str(error)[:1800]
                    record['errors'].append('Exact prior ledger mismatch: ' + name)
                record[name] = item
        record['status'] = 'verified' if not record['errors'] else 'verification_failed'
    except Exception as error:
        record.update(status='verification_failed', errors=record['errors'] + [f'{type(error).__name__}: {error}'])
    return record


def summarize(trades, equity, dataset, bounds, parameters):
    metrics = helper.summarize(trades, equity, dataset, bounds)
    cohort = trades if bounds is None else trades.loc[helper.helper.trade_mask(
        trades, helper.helper.utc(bounds[0]), helper.helper.utc(bounds[1]))]
    embedded = 0.
    if parameters.get('slippage_model', 'cash') == 'price':
        embedded = float(((cohort.entry - cohort.entry_price_before_slippage).abs() +
                          (cohort.exit - cohort.exit_price_before_slippage).abs()).sum() * dataset['point_value'])
        # In price mode the inherited repricing statistic doubles fees only.
        metrics.pop('double_cost_net', None)
        metrics.pop('double_cost_repricing_net', None)
        metrics['stress_basis'] = 'Separate price-fill stress reruns; no saved-trade doubled-total-cost statistic is reported for price mode.'
    metrics.update(recorded_cash_costs=float(cohort.cost.sum()), embedded_price_slippage=embedded,
                   modeled_execution_costs=float(cohort.cost.sum()) + embedded)
    return clean(metrics)


def summarize_cached(out, definition, trades, equity, dataset, definitions, protocol_hash, source_hash):
    folder = out / definition['symbol'] / definition['variant']
    identity_data = dict(protocol=protocol_hash, source=source_hash,
                         trades=checksum(folder / 'trades.csv'), equity=checksum(folder / 'equity.parquet'),
                         local_summary=hashlib.sha256(inspect.getsource(summarize).encode()).hexdigest(),
                         periods=definitions)
    key = hashlib.sha256(json.dumps(identity_data, sort_keys=True).encode()).hexdigest()
    path = out / 'analysis-cache' / (definition['symbol'] + '-' + definition['variant'] + '-' + key + '.json')
    if path.is_file():
        cached = read(path)
        if cached.get('identity') == identity_data:
            return cached['periods']
    periods = {name: summarize(trades, equity, dataset, bounds, definition['parameters'])
               for name, bounds in definitions.items()}
    path.parent.mkdir(parents=True, exist_ok=True)
    save(path, dict(identity=identity_data, periods=periods))
    return periods


def factorial_contrasts(cases, periods):
    index = {(c['symbol'], c['variant']): c for c in cases}
    contrasts = [('lifetime_at_first_touch', 0, 1), ('lifetime_at_any_touch', 2, 3),
                 ('eligibility_at_one_bar', 0, 2), ('eligibility_at_three_bars', 1, 3)]
    rows = []
    for symbol in SYMBOLS:
        scenarios = [('strict', '', STRICT_FACTORS), ('relaxed', '', FACTORS)]
        if symbol == 'MNQ':
            scenarios.extend([('relaxed', suffix, FACTORS) for suffix in ['_double_cost', '_price_2']])
        for gap, suffix, factors in scenarios:
            for name, before_index, after_index in contrasts:
                before, after = factors[before_index], factors[after_index]
                a, b = index.get((symbol, before + suffix), {}), index.get((symbol, after + suffix), {})
                for period in periods:
                    am, bm = a.get('periods', {}).get(period, {}), b.get('periods', {}).get(period, {})
                    row = dict(symbol=symbol, gap=gap, scenario=suffix.lstrip('_') or 'base_cash', contrast=name,
                               period=period, before=before + suffix, after=after + suffix,
                               before_status=a.get('status', 'missing'), after_status=b.get('status', 'missing'))
                    for field in DELTA_FIELDS:
                        av, bv = am.get(field), bm.get(field)
                        row['before_' + field], row['after_' + field] = av, bv
                        row['delta_' + field] = bv - av if av is not None and bv is not None else None
                    rows.append(clean(row))
            for period in periods:
                metrics = [index.get((symbol, v + suffix), {}).get('periods', {}).get(period, {}) for v in factors]
                row = dict(symbol=symbol, gap=gap, scenario=suffix.lstrip('_') or 'base_cash', contrast='interaction', period=period,
                           definition='(any3 - any1) - (first3 - first1); descriptive difference of simulator differences')
                for field in DELTA_FIELDS:
                    values = [m.get(field) for m in metrics]
                    row['delta_' + field] = values[3] - values[2] - values[1] + values[0] if all(v is not None for v in values) else None
                rows.append(clean(row))
    return rows


def primary_checks(cases, protocol):
    """Only the predeclared targeted stability checks; never a Working label."""
    index = {c['variant']: c for c in cases if c['symbol'] == 'MNQ'}
    checks = {}
    declared = protocol.get('targeted_stability_checks', {})
    baseline = index.get('relaxed_first_1', {}).get('periods', {}).get('later_combined', {})
    count = baseline.get('trades')
    checks['baseline_later_trade_count'] = dict(observed=count, threshold='>= 100', passed=count is not None and count >= 100)
    for variant in declared.get('required_stress_cases', STRESSES[1:]):
        for period in ['all', 'later_combined']:
            value = index.get(variant, {}).get('periods', {}).get(period, {}).get('net_pnl')
            checks[variant + '_' + period + '_positive_net'] = dict(
                observed=value, threshold='> 0 USD marked net', passed=value is not None and value > 0)
    for variant in declared.get('neighbor_cases', NEIGHBORS):
        metrics = index.get(variant, {}).get('periods', {}).get('later_combined', {})
        value, count = metrics.get('net_pnl'), metrics.get('trades')
        checks[variant + '_later_positive_net'] = dict(observed=value, threshold='> 0 USD marked net', passed=value is not None and value > 0)
        checks[variant + '_later_trade_count'] = dict(observed=count, threshold='>= 100', passed=count is not None and count >= 100)
    return checks


def result_rows(cases, period, symbol=None, variants=None):
    rows = []
    for case in cases:
        if symbol and case['symbol'] != symbol or variants and case['variant'] not in variants:
            continue
        m = case.get('periods', {}).get(period, {})
        ci = m.get('mean_r_95ci', [None, None])
        rows.append([case['symbol'], case['variant'], case['status'], m.get('trades', 'n/a'),
                     number(m.get('net_pnl'), money=True), number(m.get('profit_factor')),
                     number(m.get('max_drawdown_dollars'), money=True), number(m.get('mean_net_r'), 3),
                     '[' + ', '.join(number(v, 3) for v in ci) + ']', number(m.get('modeled_execution_costs'), money=True)])
    return rows


HEADERS = ['Market', 'Case', 'Status', 'Trades', 'Marked net', 'Net PF', 'Max DD', 'Mean net R', '95% CI', 'Modeled costs']


def make_charts(out, ledgers, capital):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    outputs = []
    sets = [('mnq-execution-stress.png', ['strict_control', *STRESSES],
             'MNQ | relaxed-FVG execution stress'),
            ('mnq-entry-factorial.png', [*STRICT_FACTORS, *FACTORS], 'MNQ | touch eligibility × frozen order lifetime')]
    for filename, variants, title in sets:
        fig, ax = plt.subplots(figsize=(13, 6))
        for variant in variants:
            equity = ledgers.get(('MNQ', variant))
            if equity is not None:
                ax.plot(pd.to_datetime(equity.timestamp, utc=True), equity.equity.to_numpy() - capital,
                        linewidth=.85, label=variant)
        ax.axhline(0, color='#777777', linewidth=.7)
        ax.axvline(pd.Timestamp('2025-01-01', tz='UTC'), color='#888888', linestyle='--', linewidth=.8)
        ax.set_title(title + '\nOne contract; costs included; previously inspected history')
        ax.set_ylabel('Cumulative marked net P&L (USD)')
        ax.grid(alpha=.2)
        ax.legend(fontsize=8, loc='upper left')
        fig.tight_layout()
        fig.savefig(out / filename, dpi=150)
        plt.close(fig)
        outputs.append(filename)
    return outputs


def make_report(analysis):
    cases = analysis['cases']
    lines = ['# Supply/demand: relaxed-FVG stress and entry-rule experiment', '',
             ('All declared runs and evidence checks completed. Historical results remain exploratory.'
              if analysis['status'] == 'complete' else 'PARTIAL / UNVERIFIED: do not draw a final validation conclusion.'), '',
             f"Verified cases: {analysis['completed_case_count']}/{analysis['declared_case_count']}. Exact prior controls: {analysis['verified_parity_count']}/5. Generated {analysis['generated_at']}.", '',
             '## Scope and rules', '',
             'MNQ is the declared primary market; MGC and NQ are transfer checks. All use the same January 2022–July 2026 history, a separate $100,000 account and one fixed contract. All 42 cases were declared before execution. No settings are selected from these outcomes.', '',
             'Wick zone boundaries, confirmed 5-minute/hourly swing alignment, a stop one tick beyond the zone, a 1R target, and at least 2R of opposing room remain the reference rules. Relaxed FVG means the third candle closes beyond the first candle’s wick; its entire wick need not remain beyond it. Strict control retains the full wick gap.', '',
             'The entry factorial independently varies first-touch versus any-touch eligibility, and a frozen order lifetime of one versus three 5-minute bars. Any-touch may arm on the first or a later completed overlapping candle, including consecutive candles still inside the zone. It requires an actual overlap rather than the old continuously rolling trigger. One filled trade consumes the zone. Active pending levels never refresh: three-bar orders keep their original trigger, stop and opposing boundary.', '',
             'At the close of the final lifetime bar, the old order expires first. Any-touch may then rearm using that now-completed overlapping bar; first-touch may arm a different newly touched zone at the same expiry close. Existing alignment, invalidation and availability rules still apply.', '',
             '## Test 1: primary execution and cost stress', '',
             'Cash mode charges modeled slippage without moving fills. Its doubled-cost case reruns with twice the fees and slippage but does not itself test execution-price changes. Price mode moves entry and non-limit exit fills adversely by one or two ticks; target limit exits have no slippage. It recalculates actual initial risk, target and opposing room, and charges fees separately so slippage is not counted twice.', '',
             'Modeled costs below include recorded cash charges plus the embedded entry/exit price impact in price mode. These costs are already included in net P&L and must not be subtracted again. Embedded slippage is an attribution on each executed trade, not the difference in total P&L versus another run; changing fills can alter subsequent trade selection.', '']
    for period in ['all', 'year_2024', 'later_2025', 'latest_2026', 'later_combined']:
        lines.extend(['### ' + PERIOD_LABELS[period], '', table(HEADERS, result_rows(cases, period, 'MNQ', STRESSES)), ''])
    if analysis.get('primary_checks'):
        verdict = ('PASS' if analysis['targeted_stability_passed'] else 'FAIL') if analysis['status'] == 'complete' else 'UNVERIFIED'
        lines.extend(['### Declared historical checks', '',
                      '**Targeted historical stability: ' + verdict + '.** This is not an overall profitability or forward-validation verdict.', '',
                      table(['Check', 'Observed', 'Required', 'Result'],
                            [[name.replace('_', ' '), str(item.get('observed')), item.get('threshold', ''),
                              'PASS' if item.get('passed') else 'FAIL / unavailable']
                             for name, item in analysis['primary_checks'].items()]), '',
                      'These checks address historical robustness only; passing would not establish an untouched holdout or live feasibility.', ''])
    lines.extend(['### Six one-factor neighboring settings', '',
                  'Pivot lengths 1 and 3, target multiples 0.75R and 1.25R, and room requirements 1.5R and 2.5R change one setting at a time from relaxed first-touch/one-bar cash mode. They are sensitivity checks, not a search for a new winner.', ''])
    for period in ['all', 'later_combined']:
        lines.extend(['**' + PERIOD_LABELS[period] + '**', '',
                      table(HEADERS, result_rows(cases, period, 'MNQ', ['relaxed_first_1', *NEIGHBORS])), ''])
    lines.extend(['## Test 2: independently varying eligibility and order lifetime', '',
                  'Compare first1→first3 and any1→any3 to examine lifetime at fixed eligibility; compare first1→any1 and first3→any3 to examine eligibility at fixed lifetime. Differences include changed trade selection and later position availability, so they are descriptive simulator contrasts, not paired causal treatment effects.', ''])
    for symbol in SYMBOLS:
        scenarios = [('strict', '', STRICT_FACTORS), ('relaxed', '', FACTORS)]
        if symbol == 'MNQ':
            scenarios.extend([('relaxed', suffix, FACTORS) for suffix in ['_double_cost', '_price_2']])
        for gap, suffix, factors in scenarios:
            lines.extend(['### ' + symbol + ' — ' + gap + ' FVG — ' + (suffix.lstrip('_') or 'base cash costs'), ''])
            for period in ['all', 'later_combined']:
                lines.extend(['**' + PERIOD_LABELS[period] + '**', '',
                              table(HEADERS, result_rows(cases, period, symbol, [v + suffix for v in factors])), '',
                              table(['Fixed-factor contrast', 'Net Δ', 'Trades Δ', 'PF Δ', 'Mean R Δ', 'DD Δ'],
                                    [[r['contrast'], number(r.get('delta_net_pnl'), money=True), number(r.get('delta_trades'), 0),
                                      number(r.get('delta_profit_factor')), number(r.get('delta_mean_net_r'), 3),
                                      number(r.get('delta_max_drawdown_dollars'), money=True)]
                                     for r in analysis['contrasts'] if r['symbol'] == symbol and r['gap'] == gap and r['scenario'] ==
                                     (suffix.lstrip('_') or 'base_cash') and r['period'] == period]), ''])
    lines.extend(['Positive drawdown delta means a larger loss from peak to trough. Interaction is (any3−any1)−(first3−first1); nonlinear statistics such as PF are descriptive differences only. No inferential claim is attached to these contrasts.', '',
                  '## All declared cases across all periods', '',
                  'Marked P&L and drawdown use every saved observed 5-minute bucket-end mark and the period opening mark. Trade count, profit factor, mean R, confidence intervals and modeled costs use trades closed in the period, so period cash totals need not equal marked P&L.', ''])
    for period in analysis['period_definitions']:
        lines.extend(['### ' + PERIOD_LABELS.get(period, period), '', table(HEADERS, result_rows(cases, period)), ''])
    lines.extend(['## Evidence checks and limitations', '',
                  table(['Market', 'Current control', 'Prior frozen case', 'Exact prior-column/equity equality'],
                        [[p['symbol'], p['variant'], p['prior_variant'], p['status']] for p in analysis['baseline_parity']]), '',
                  'Control comparison requires matching data checksums, economics, periods and shared parameters; all prior trade columns must be exact and the complete equity schema/values must match. New trade audit columns are allowed. Every result, trade/equity artifact, frozen source and current input file is checksum verified; accounting reconciles to final marked equity.', ''])
    audit = analysis.get('independent_audit')
    if audit:
        lines.extend([f"The independent audit reports **{audit.get('status')}**; matching protocol/source identity: **{audit.get('identity_matches')}**. Its detailed scope, checks and limitations are in [independent-audit.json](independent-audit.json).", ''])
    for error in analysis['verification_errors']:
        lines.append('- Verification issue: ' + error)
    for case in analysis['unavailable_cases']:
        lines.append('- Unavailable case: ' + case)
    lines.extend(['',
                  'All observations were previously inspected. Later periods are chronological checks, not fresh holdouts. The seeded 2,000-draw occupied-exit-week mean-R intervals are pointwise and do not adjust for the many variants or preserve dependence between weeks. A positive dollar result can coexist with negative mean net R because one-contract cash returns put more weight on wide-risk trades.', '',
                  'Price slippage is a deterministic stress assumption, not a liquidity, latency, queue or partial-fill model. Intraminute path ambiguity is treated conservatively by the inherited simulator. Drawdown cannot reveal unobserved intrabar extremes. Positions can last across sessions because no holding-time or session-end exit was introduced.', '',
                  'Continuous-contract roll gaps and incomplete minutes remain data limitations. Identifiable contract transitions use the inherited prior-close liquidation/reset; MGC lacks contract identifiers. NQ and MNQ share market exposure and do not constitute independent replications. Cross-market dollar totals should not be ranked or combined into a portfolio. The Pine indicator and previous strategy/report artifacts are unchanged.', '',
                  '## Reproducible artifacts', '',
                  '- [Frozen protocol](protocol.json) and [execution source manifest](source-manifest.json).',
                  '- [Every case-period metric](all-results.csv) and [fixed-factor contrasts](factorial-contrasts.csv).',
                  '- [Structured analysis](analysis.json) and [artifact/accounting/parity verification](verification.json).',
                  '- Per-market/per-case trade, marked-equity, parameter and result files are preserved alongside this report.', ''])
    for chart in analysis.get('charts', []):
        lines.extend([f'![{chart}]({chart})', ''])
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=OUT)
    parser.add_argument('--require-complete', action='store_true')
    args = parser.parse_args()
    out = args.output.resolve()
    protocol = read(out / 'protocol.json')
    protocol_hash = checksum(out / 'protocol.json')
    capital = float(protocol['capital'])
    if capital != helper.helper.driver.CAPITAL:
        raise ValueError('Inherited metrics require capital 100000')
    definitions = {'all': None, **protocol['periods']}
    analyzer_bytes = Path(__file__).read_bytes()
    analyzer_hash = hashlib.sha256(analyzer_bytes).hexdigest()
    snapshot = out / 'analysis-source' / (Path(__file__).stem + '-' + analyzer_hash[:16] + '.py')
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    if snapshot.exists() and snapshot.read_bytes() != analyzer_bytes:
        raise ValueError('Analysis snapshot path collision')
    snapshot.write_bytes(analyzer_bytes)
    sources, manifest = identity.check_source_set(out, protocol_hash)
    frozen_names = {item['path'].replace('\\', '/') for item in (manifest or {}).get('files', [])}
    if 'scripts/report-snd-body-retest.py' not in frozen_names:
        sources['errors'].append('Body identity helper was not frozen')
        sources['verified'] = False
    datasets_verified = identity.check_dataset_files(protocol['datasets'])
    prior_checks, previous, prior_manifest, prior_out = identity.prior_campaign(protocol)
    errors = [label + ': ' + error for label, checked in [('sources', sources), ('prior', prior_checks)] for error in checked['errors']]
    if not datasets_verified['verified']:
        errors.append('One or more dataset checksums do not match')
    declared = [(case['symbol'], case['variant']) for case in protocol['cases']]
    if len(declared) != len(set(declared)) or set(declared) != expected_cases() or len(declared) != 42:
        errors.append('Case declaration differs from the complete fixed 42-case plan')
    datasets = {d['symbol']: d for d in protocol['datasets']}
    cases, verifications, parity, rows, ledgers = [], [], [], [], {}
    for definition in protocol['cases']:
        symbol, variant = definition['symbol'], definition['variant']
        case = dict(symbol=symbol, variant=variant, parameters=definition['parameters'],
                    fee=definition.get('fee'), slippage_ticks=definition.get('slippage_ticks'))
        trades = equity = None
        try:
            verification, result, trades, equity = helper.verify_case(
                out / symbol / variant, definition, datasets[symbol], protocol_hash,
                (manifest or {}).get('source_hash'), capital)
            case.update(status=verification['status'], diagnostics=(result or {}).get('diagnostics', {}))
            if case['status'] == 'succeeded':
                for field, value in [('fee_per_side', definition['fee']),
                                     ('slippage_ticks_per_market_or_stop_side', definition['slippage_ticks'])]:
                    if case['diagnostics'].get(field) != value:
                        raise ValueError('Declared/resolved execution costs differ: ' + field)
                case['periods'] = summarize_cached(out, definition, trades, equity, datasets[symbol],
                                                  definitions, protocol_hash, (manifest or {}).get('source_hash'))
                case['zero_trade_case'] = len(trades) == 0
                if symbol == 'MNQ' and variant in [*STRICT_FACTORS, *STRESSES, *FACTORS]:
                    ledgers[(symbol, variant)] = equity
            else:
                case.update(errors=verification.get('errors', []), failure=verification.get('failure'))
        except Exception as error:
            case.update(status='verification_failed', errors=[f'{type(error).__name__}: {error}'])
            verification = dict(symbol=symbol, variant=variant, status=case['status'], errors=case['errors'])
            trades = equity = None
        if prior_variant(symbol, variant):
            check = parity_check(definition, trades, equity, protocol, previous, prior_manifest, prior_out)
            parity.append(check)
            if check['status'] != 'verified':
                errors.append(f'{symbol}/{variant}: prior parity {check["status"]}')
        for period in definitions:
            metrics = case.get('periods', {}).get(period, {})
            ci = metrics.get('mean_r_95ci', [None, None])
            rows.append(dict(symbol=symbol, variant=variant, period=period, status=case['status'],
                             zero_trade_case=case.get('zero_trade_case'),
                             **{field: metrics.get(field) for field in FIELDS}, ci_low=ci[0], ci_high=ci[1]))
        cases.append(case)
        verifications.append(verification)
        print(f'{symbol}/{variant}: {case["status"]}', flush=True)
    if len(parity) != 5:
        errors.append('Expected five exact prior control comparisons')
    audit_path = out / 'independent-audit.json'
    audit_summary = None
    if audit_path.is_file():
        audit = read(audit_path)
        matches = audit.get('protocol_checksum') == protocol_hash and audit.get('source_manifest_checksum') == checksum(out / 'source-manifest.json')
        audit_summary = dict(status=audit.get('status'), checksum=checksum(audit_path), identity_matches=matches,
                             declared_cases=audit.get('declared_cases'), total_checks=audit.get('total_checks'))
        if not matches or audit.get('status') not in ('passed', 'succeeded', 'complete', 'verified'):
            errors.append('Independent audit failed, is incomplete, or does not match this evidence chain')
    else:
        errors.append('Independent audit is not available yet')
    unavailable = [f"{c['symbol']}/{c['variant']} ({c['status']})" for c in cases if c['status'] != 'succeeded']
    status = 'complete' if not errors and not unavailable else 'partial_or_unverified'
    now = datetime.now(timezone.utc).isoformat()
    analysis = dict(generated_at=now, status=status, declared_case_count=len(declared),
                    completed_case_count=sum(c['status'] == 'succeeded' for c in cases),
                    protocol_checksum=protocol_hash, source_hash=(manifest or {}).get('source_hash'),
                    capital=capital, primary_markets=['MNQ'], transfer_markets=['MGC', 'NQ'],
                    period_definitions=definitions, datasets=protocol['datasets'], cases=cases,
                    contrasts=factorial_contrasts(cases, definitions), baseline_parity=parity,
                    verified_parity_count=sum(p['status'] == 'verified' for p in parity),
                    zero_trade_cases=[f"{c['symbol']}/{c['variant']}" for c in cases if c.get('zero_trade_case')],
                    unavailable_cases=unavailable, verification_errors=errors,
                    independent_audit=audit_summary, eligible_for_working_label=False,
                    freshness='Previously inspected history; no untouched holdout or prospective validation.')
    analysis['primary_checks'] = primary_checks(cases, protocol)
    analysis['targeted_stability_passed'] = status == 'complete' and all(item['passed'] for item in analysis['primary_checks'].values())
    verification = dict(generated_at=now, status=status, protocol_checksum=protocol_hash,
                        analyzer_checksum=analyzer_hash, analyzer_snapshot=str(snapshot.relative_to(out)),
                        analyzer_snapshot_checksum=checksum(snapshot),
                        analyzer_scope='Reporter captured at analysis time; execution and inherited metric/identity helpers frozen before runs.',
                        sources=sources, dataset_inputs=datasets_verified, prior_campaign=prior_checks,
                        cases=verifications, baseline_parity=parity, independent_audit=audit_summary, errors=errors)
    pd.DataFrame(rows).to_csv(out / 'all-results.csv', index=False)
    pd.DataFrame(analysis['contrasts']).to_csv(out / 'factorial-contrasts.csv', index=False)
    analysis['charts'] = make_charts(out, ledgers, capital)
    save(out / 'verification.json', verification)
    analysis['outputs'] = {name: checksum(out / name) for name in ['all-results.csv', 'factorial-contrasts.csv', 'verification.json', *analysis['charts']]}
    save(out / 'analysis.json', analysis)
    (out / 'REPORT.md').write_text(make_report(analysis), encoding='utf-8')
    print(f"{status}: {analysis['completed_case_count']}/{len(declared)} verified cases; {analysis['verified_parity_count']}/5 exact controls; {len(rows)} case-period rows.")
    if args.require_complete and status != 'complete':
        print('; '.join(errors + unavailable), file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
