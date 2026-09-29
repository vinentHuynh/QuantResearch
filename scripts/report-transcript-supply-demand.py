"""Correct period reporting from frozen transcript-research ledgers.

This does not rerun or alter the model, protocol, source snapshot, per-case
result.json, or original all-results.csv. Source candle times denote opens;
equity marks and roll/final liquidations denote source candle closes.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DRIVER_PATH = ROOT / 'scripts/analyze-transcript-supply-demand.py'
spec = importlib.util.spec_from_file_location('transcript_research_driver', DRIVER_PATH)
driver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(driver)
OUT = driver.OUT
CLOSE_TIME_REASONS = {'contract-roll', 'end-of-test'}


def utc(value):
    stamp = pd.Timestamp(value)
    return stamp.tz_localize('UTC') if stamp.tz is None else stamp.tz_convert('UTC')


def trade_mask(trades, lower, upper):
    """Intrabar-open exits use [lo,hi); closing-price exits use (lo,hi]."""
    exits = pd.to_datetime(trades.exit_time, utc=True)
    at_close = trades.exit_reason.isin(CLOSE_TIME_REASONS)
    open_exits = ~at_close & (exits >= lower) & (exits < upper)
    close_exits = at_close & (exits > lower) & (exits <= upper)
    return open_exits | close_exits


def summarize_period(trades, equity, lower=None, upper=None):
    if lower is None:
        part, cohort = equity.copy(), trades.copy()
        starting_mark = driver.CAPITAL
    else:
        lower, upper = utc(lower), utc(upper)
        times = pd.to_datetime(equity.timestamp, utc=True)
        # The midnight close belongs to the source candle that ended there.
        part = equity.loc[(times > lower) & (times <= upper)].copy()
        prior = equity.loc[times <= lower, 'equity']
        starting_mark = float(prior.iloc[-1]) if len(prior) else driver.CAPITAL
        part['equity'] += driver.CAPITAL - starting_mark
        cohort = trades.loc[trade_mask(trades, lower, upper)].copy()
    if part.empty:
        return dict(status='no_observations', trades=len(cohort),
                    closed_trade_pnl=float(cohort.net_pnl.sum()))
    result = driver.summarize(cohort, part)
    top_five = cohort.loc[cohort.net_pnl > 0].nlargest(5, 'net_pnl')
    top_five_total = float(top_five.net_pnl.sum())
    holding = (pd.to_datetime(cohort.exit_time, utc=True) - pd.to_datetime(cohort.entry_time, utc=True)).dt.total_seconds() / 3600 if 'entry_time' in cohort else pd.Series(dtype=float)
    if len(holding) and (holding < 0).any():
        raise ValueError('A closed trade exits before its entry')
    record_fields = [field for field in ('entry_time', 'exit_time', 'side', 'entry', 'exit', 'risk', 'net_pnl', 'net_r', 'exit_reason') if field in cohort]
    longest = cohort.loc[holding.idxmax(), record_fields].to_dict() if len(holding) else None
    result.update(status='succeeded', closed_trade_pnl=float(cohort.net_pnl.sum()),
                  cash_expectancy_per_closed_trade=result['expectancy'],
                  mean_r_per_closed_trade=result['mean_net_r'],
                  period_start_equity=starting_mark,
                  equity_basis='Mark-to-market change, including positions crossing period boundaries.',
                  trade_basis='Whole closed trades assigned by exit timestamp convention; not allocated across years.',
                  stress_basis='Closed-trade net P&L minus original closed-trade costs again; not period MTM.',
                  top_five_winner_net=top_five_total,
                  net_excluding_top_five_winners=float(cohort.net_pnl.sum()) - top_five_total,
                  top_five_winning_trades=top_five[record_fields].to_dict(orient='records'),
                  median_holding_hours=float(holding.median()) if len(holding) else None,
                  max_holding_hours=float(holding.max()) if len(holding) else None,
                  fraction_held_over_24h=float((holding > 24).mean()) if len(holding) else None,
                  trades_held_over_24h=int((holding > 24).sum()),
                  net_from_trades_held_over_24h=float(cohort.loc[holding > 24, 'net_pnl'].sum()) if len(holding) else 0.,
                  longest_trade=longest)
    return result


def gate_for(case):
    """Report primary numeric gates; never infer qualitative robustness."""
    if not case or case['status'] != 'succeeded':
        return dict(status='unavailable', eligible_for_working_label=False)
    periods = case['periods']
    later = periods['later_combined']
    year25, year26 = periods['later_2025'], periods['latest_2026']
    ci = later.get('mean_r_95ci', [None, None])
    checks = {
        'at_least_100_later_closed_trades': later.get('trades', 0) >= 100,
        'positive_2025_marked_pnl': (year25.get('net_pnl') or 0) > 0,
        'positive_jan_jul_2026_marked_pnl': (year26.get('net_pnl') or 0) > 0,
        'later_profit_factor_at_least_1_10': later.get('profit_factor') is not None and later['profit_factor'] >= 1.10,
        'positive_later_double_cost_closed_pnl': (later.get('double_cost_net') or 0) > 0,
        'later_week_cluster_mean_r_ci_lower_positive': ci[0] is not None and ci[0] > 0,
    }
    return dict(status='evaluated', primary_numeric_checks=checks,
                all_primary_numeric_checks_pass=all(checks.values()),
                eligible_for_working_label=False,
                remaining_requirement='Nearby-rule stability, sufficiently independent market support, and forward evidence require separate assessment. No winner is selected here.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--require-complete', action='store_true',
                        help='Fail before writing corrected artifacts if any declared case is missing.')
    args = parser.parse_args()
    protocol = json.loads((OUT / 'protocol.json').read_text(encoding='utf-8'))
    definitions = {'all': None, **protocol['periods'],
                   'later_combined': ['2025-01-01', protocol['periods']['latest_2026'][1]]}
    cases, rows, changes = [], [], []
    fields = ['trades', 'net_pnl', 'closed_trade_pnl', 'gross_pnl', 'costs',
              'profit_factor', 'win_rate', 'mean_net_r', 'expectancy',
              'cash_expectancy_per_closed_trade', 'mean_r_per_closed_trade',
              'double_cost_net', 'max_drawdown_dollars', 'sharpe', 'first', 'last',
              'top_five_winner_net', 'net_excluding_top_five_winners',
              'median_holding_hours', 'max_holding_hours', 'fraction_held_over_24h']
    for dataset in protocol['datasets']:
        symbol = dataset['symbol']
        for variant in protocol['variants']:
            folder = OUT / symbol / variant
            required = [folder / name for name in ('result.json', 'trades.csv', 'equity.parquet')]
            if not all(path.exists() for path in required):
                cases.append(dict(symbol=symbol, variant=variant, status='failed_or_incomplete'))
                rows.extend(dict(symbol=symbol, variant=variant, period=period,
                                 status='failed_or_incomplete') for period in definitions)
                continue
            original = json.loads(required[0].read_text(encoding='utf-8'))
            trades = pd.read_csv(required[1])
            equity = pd.read_parquet(required[2])
            np.testing.assert_allclose(equity.equity.iloc[-1] - driver.CAPITAL,
                                       trades.net_pnl.sum(), rtol=0, atol=1e-5)
            np.testing.assert_allclose(trades.gross_pnl.sum() - trades.cost.sum(),
                                       trades.net_pnl.sum(), rtol=0, atol=1e-5)
            periods = {}
            for period, bounds in definitions.items():
                metrics = summarize_period(trades, equity, *(bounds or []))
                periods[period] = metrics
                row = dict(symbol=symbol, variant=variant, period=period,
                           status=metrics['status'], **{field: metrics.get(field) for field in fields})
                ci = metrics.get('mean_r_95ci', [None, None])
                row.update(ci_low=ci[0], ci_high=ci[1])
                rows.append(row)
                before = original.get('periods', {}).get(period)
                if before:
                    for field in ('net_pnl', 'closed_trade_pnl', 'trades'):
                        previous, current = before.get(field), metrics.get(field)
                        if previous is not None and current is not None and not np.isclose(previous, current, rtol=0, atol=1e-7):
                            changes.append(dict(symbol=symbol, variant=variant, period=period,
                                                field=field, original=previous, corrected=current,
                                                delta=current - previous))
            # All-history totals must remain identical to the frozen run.
            np.testing.assert_allclose(periods['all']['net_pnl'], original['periods']['all']['net_pnl'],
                                       rtol=0, atol=1e-5)
            case = dict(symbol=symbol, variant=variant, status='succeeded', periods=periods,
                        diagnostics=original.get('diagnostics', {}),
                        source_artifacts={str(path.relative_to(OUT)): driver.checksum(path) for path in required})
            cases.append(case)

    missing = [f"{case['symbol']}/{case['variant']}" for case in cases if case['status'] != 'succeeded']
    if args.require_complete and missing:
        raise RuntimeError('Declared cases are incomplete: ' + ', '.join(missing))
    now = datetime.now(timezone.utc).isoformat()
    analyzer_checksum = driver.checksum(Path(__file__))
    correction = dict(generated_at=now, analyzer=str(Path(__file__).relative_to(ROOT)),
        analyzer_checksum=analyzer_checksum, protocol_checksum=driver.checksum(OUT / 'protocol.json'),
        summary_helper_checksum=driver.checksum(DRIVER_PATH),
        original_artifacts_preserved=['all-results.csv', '<symbol>/<variant>/result.json', 'protocol.json', 'source/'],
        changes=[
            'Equity period masks corrected from [lo,hi) to (lo,hi], because marks timestamp source candle closes.',
            'Period starting mark is the last mark at or before lo, not strictly before lo.',
            'Intrabar-open target/stop exits use [lo,hi); closing-price contract-roll/end-of-test exits use (lo,hi].',
            'Added combined later 2025-through-July-2026 period for the existing candidate gate.',
            'Explicitly distinguish fixed-one-contract cash expectancy from risk-normalized mean net R.',
            'Added top-five-winner concentration and observed holding-duration diagnostics without changing exits.',
            'All-history totals reconcile to original frozen results; model and parameters are unchanged.'
        ], numerical_changes=changes,
        note='Boundary corrections may produce no numerical change when markets were closed at exact cutoffs.',
        missing_cases=missing)
    table = pd.DataFrame(rows)
    table.to_csv(OUT / 'corrected-results.csv', index=False)
    gaps = {}
    for dataset in protocol['datasets']:
        file = OUT / dataset['symbol'] / 'fvg-72h.json'
        if file.exists():
            gaps[dataset['symbol']] = dict(summary=json.loads(file.read_text(encoding='utf-8')),
                                          source_checksum=driver.checksum(file))
    primary_cases = {case['variant']: case for case in cases if case['symbol'] == 'MGC'}
    report = dict(generated_at=now, status='complete' if not missing else 'partial',
        declared_case_count=len(protocol['datasets']) * len(protocol['variants']),
        completed_case_count=sum(case['status'] == 'succeeded' for case in cases),
        missing_cases=missing, period_definitions=definitions,
        period_labels={'development': '2022-2024 (GC only begins September 2024)',
                       'later_2025': 'Calendar 2025', 'latest_2026': 'January-July 2026, partial year',
                       'later_combined': 'January 2025-July 2026'},
        economics='One fixed contract per trade. Cash expectancy is USD per closed trade. Mean net R divides each trade by its own initial price risk times point value; these have different weighting and can differ in sign.',
        freshness='Historical exploratory assessment. Later periods are chronological checks, not untouched prospective holdouts; data ends before August 2026.',
        uncertainty='2000 seeded occupied-exit-week bootstrap draws, resampling weekly total net R and trade count together. Pointwise intervals do not adjust for variant/market multiplicity or preserve dependence across weeks.',
        replication='Seven market series are not seven independent tests: MGC/GC and MNQ/NQ overlap economically, and ES/YM/NQ share equity-market exposure.',
        holding_caution='The transcript specifies no time stop or session-end liquidation. A five-minute setup can therefore hold for days or weeks. Long MGC/GC positions may cross unidentifiable continuous-contract rolls; concentration and duration are reported, not tuned away.',
        gap_study_caution='The 72 elapsed-hour horizon fits inside source file endpoints, but internal missing intervals are not proven fully observed. Original descriptive study retains roll effects, including identifiable rolls, and overlapping events; full-fill rate is not trade win rate.',
        correction=correction, datasets=protocol['datasets'],
        primary_mgc_numeric_gates={name: gate_for(primary_cases.get(name)) for name in protocol['variants']},
        cases=cases, fvg_72h=gaps,
        outputs={'corrected-results.csv': driver.checksum(OUT / 'corrected-results.csv')})
    driver.save(OUT / 'analysis-corrections.json', correction)
    driver.save(OUT / 'report-data.json', report)
    print(f"Corrected reporting: {report['completed_case_count']}/{report['declared_case_count']} cases; "
          f"{len(rows)} case-period rows; {len(changes)} numerical boundary changes.")
    print(table.loc[(table.variant == 'baseline') & (table.period == 'all')].to_string(index=False))


if __name__ == '__main__':
    main()
