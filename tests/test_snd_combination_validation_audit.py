"""Independent marked equity and saved decision mutation checks."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

import numpy as np
import pandas as pd

from strategies import _snd_combination_reference as reference
from strategies import _snd_combination_risk as risk
from test_snd_combinations_audit import fixture

SPEC = importlib.util.spec_from_file_location('validation_independent_audit', Path(__file__).resolve().parents[1] / 'scripts/audit-snd-combination-validation.py')
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


def summary(r):
    t, e = r['trades'], r['equity']
    path = np.r_[100000, e.equity.to_numpy(float)]
    m = dict(trades=len(t), net_pnl=float(t.net_pnl.sum()), closed_net=float(t.net_pnl.sum()),
        gross_pnl=float(t.gross_pnl.sum()), cost=float(t.cost.sum()), double_cost_closed_net=float((t.net_pnl-t.cost).sum()),
        net_r_sum=float(t.net_r.sum()), mean_net_r=float(t.net_r.mean()) if len(t) else None,
        max_drawdown=float((np.maximum.accumulate(path)-path).max()), min_equity=float(path.min()),
        max_trade_loss=max(0, -float(t.net_pnl.min())) if len(t) else 0)
    if 'contracts_abs' in t:
        m.update(contracts_entered=int(t.contracts_abs.sum()), max_quantity=int(t.contracts_abs.max()) if len(t) else 0,
            maximum_planned_stop_loss=float(t.planned_stop_risk_cash.max()) if len(t) else 0,
            maximum_actual_stop_loss=float(t.actual_stop_risk_cash.max()) if len(t) else 0,
            total_budget_overshoot=float(t.risk_budget_overshoot_cash.sum()) if len(t) else 0)
    return m


def example(boundary='wick', stop='zone', mode='cash', budget=36, source=None, **options):
    frame, p, d, _ = fixture(boundary, stop)
    if source is not None:
        frame = source
    p = p | dict(slippage_model=mode, sizing_mode='fixed_risk', risk_budget=budget, max_contracts=10) | options
    r = risk.run_model(frame, p, d['start'], d['end'], d['tick_size'], d['point_value'], d['fee'], 1)
    c = dict(symbol=d['symbol'], fold_id='fixture', start=d['start'], end=d['end'], role='risk-100',
             config_id='c00000', decision='selected', scenario=mode, parameters=p, fee_multiple=1, slippage_ticks=1)
    return c, d, r, audit.base.raw_from_frame(frame)


def inspect(c, d, r, raw):
    return audit.audit_case(c, d, r['trades'], r['equity'], summary(r), r['diagnostics'], raw, r.get('sizing_decisions'))


class ValidationAuditTests(unittest.TestCase):
    def test_all_quantity_and_raw_marked_equity_checks_accept_crossed_rules(self):
        for boundary in ('wick', 'body'):
            for stop in ('zone', 'candle'):
                for mode in ('cash', 'price'):
                    with self.subTest(boundary=boundary, stop=stop, mode=mode):
                        c, d, r, raw = example(boundary, stop, mode, min_departure_atr=1, max_touch_age_hours=1)
                        record = inspect(c, d, r, raw)
                        self.assertTrue(record['passed'], record['failures'])

    def test_zero_quantity_has_raw_signal_but_never_order_or_fill(self):
        c, d, r, raw = example(budget=.01)
        self.assertEqual(len(r['sizing_decisions']), 1)
        self.assertTrue(r['trades'].empty)
        record = inspect(c, d, r, raw)
        self.assertTrue(record['passed'], record['failures'])
        r['sizing_decisions'].loc[0, 'quantity_selected'] = 1
        self.assertIn('sizing: decision capped whole quantity', inspect(c, d, r, raw)['failures'])

    def test_posthoc_rescaling_cannot_pass_frozen_order_join(self):
        c, d, r, raw = example()
        factor = 2.
        for column in ('quantity', 'contracts_abs', 'risk_cash', 'initial_risk_cash', 'gross_pnl', 'cost', 'net_pnl',
                       'planned_stop_risk_cash', 'actual_stop_risk_cash'):
            r['trades'][column] *= factor
        r['trades']['risk_budget_overshoot_cash'] = np.maximum(0, r['trades'].actual_stop_risk_cash - c['parameters']['risk_budget'])
        for column in ('balance', 'equity'):
            r['equity'][column] = 100000 + (r['equity'][column] - 100000) * factor
        for column in ('unrealized_pnl', 'net_pnl', 'contracts'):
            r['equity'][column] *= factor
        failures = inspect(c, d, r, raw)['failures']
        self.assertIn('sizing: fill preserves armed contracts_abs', failures)
        self.assertNotIn('accounting: actual net dollars', failures)

    def test_self_consistent_false_trigger_still_fails_raw_decision(self):
        c, d, r, raw = example(budget=.01)
        dec = r['sizing_decisions']
        dec['trigger'] += .25
        dec['planned_stop_risk_per_contract'] += .5
        failures = inspect(c, d, r, raw)['failures']
        self.assertIn('sizing: raw decision trigger', failures)
        self.assertNotIn('sizing: decision all-in planned loss', failures)

    def test_intermediate_equity_mutation_and_missing_mark_are_detected(self):
        c, d, r, raw = example()
        r['equity'].loc[5, ['equity', 'balance']] += 1
        r['equity']['net_pnl'] = np.diff(np.r_[100000, r['equity'].equity])
        failures = inspect(c, d, r, raw)['failures']
        self.assertIn('accounting: independent full-resolution equity', failures)
        r['equity'] = r['equity'].drop(index=5).reset_index(drop=True)
        failures = inspect(c, d, r, raw)['failures']
        self.assertIn('accounting: every observed scored five-minute mark retained', failures)

    def test_roll_liquidation_cash_observed_on_next_contract_bar(self):
        frame, _, _, _ = fixture()
        frame.iloc[-5:, frame.columns.get_indexer(['open', 'high', 'low', 'close'])] = [104, 105, 103.5, 104.5]
        frame['instrument_id'] = 10
        new = frame.iloc[[-1]].copy()
        new.index = pd.DatetimeIndex([frame.index[-1] + pd.Timedelta(minutes=11)])
        new[['open', 'high', 'low', 'close']] = [150, 151, 149, 150]
        new['instrument_id'] = 20
        c, d, r, raw = example(source=pd.concat([frame, new]))
        self.assertIn('contract-roll', r['trades'].exit_reason.to_list())
        t = r['trades'].iloc[0]
        self.assertGreater(audit.observed_exits(r['trades'], raw)[0], pd.Timestamp(t.exit_time).value)
        record = inspect(c, d, r, raw)
        self.assertTrue(record['passed'], record['failures'])

    def test_cash_validation_and_tampered_artifact_hash(self):
        c, d, r, raw = example()
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            identities = dict(protocol_checksum='p', source_hash='s', configurations_checksum='g', selection_checksum='c')
            for name, key in [('trades.parquet', 'trades'), ('equity.parquet', 'equity'), ('sizing-decisions.parquet', 'sizing_decisions')]:
                r[key].to_parquet(folder / name, index=False)
            names = ['trades.parquet', 'equity.parquet', 'sizing-decisions.parquet']
            audit.base._save(folder / 'input.json', dict(c, **identities, dataset=d))
            audit.base._save(folder / 'status.json', dict(status='succeeded'))
            audit.base._save(folder / 'result.json', dict(c, **identities, status='succeeded', summary=summary(r),
                diagnostics=r['diagnostics'], artifacts=[dict(name=name, checksum=audit.base.sha(folder/name)) for name in names]))
            record = audit.audit_artifact(folder, c, d, raw, identities)
            self.assertTrue(record['passed'], record['failures'])
            r['sizing_decisions'].to_parquet(folder / 'sizing-decisions.parquet', index=False, compression=None)
            record = audit.audit_artifact(folder, c, d, raw, identities)
            self.assertIn('artifact hash sizing-decisions.parquet', record['failures'])
        c = dict(c, decision='cash', parameters=None)
        empty = pd.DataFrame(columns=reference.TRADE_COLUMNS)
        equity = pd.DataFrame(dict(timestamp=pd.to_datetime([c['start'], c['end']], utc=True),
            equity=100000, balance=100000, unrealized_pnl=0, net_pnl=0, contracts=0))
        record = audit.audit_case(c, d, empty, equity, dict(trades=0, net_pnl=0, max_drawdown=0), {}, raw)
        self.assertTrue(record['passed'], record['failures'])

    def test_declared_plan_retains_cash_neighbors_and_all_risk_stresses(self):
        p = dict(reference.DEFAULTS)
        protocol = dict(datasets=[dict(symbol='MNQ')], folds=[dict(id='2024', cutoff='2024-01-01', test_end='2025-01-01')],
            validation_neighbors=[dict(rr=x) for x in (.75, 1.25, 2, 3)] + [dict(pivot_len=x) for x in (1, 3)],
            validation_scenarios=[dict(id='a', slippage_model='cash', fee_multiple=1, slippage_ticks=1),
                dict(id='b', slippage_model='cash', fee_multiple=2, slippage_ticks=2),
                dict(id='c', slippage_model='price', fee_multiple=1, slippage_ticks=1),
                dict(id='d', slippage_model='price', fee_multiple=2, slippage_ticks=2)])
        selection = dict(selections=[dict(symbol='MNQ', fold_id='2024', selected_id=None, cutoff='2024-01-01', test_end='2025-01-01')])
        cases = audit.declared_cases(selection, protocol, {'c00000': dict(parameters=p)})
        self.assertEqual(len(cases), 26)
        self.assertEqual(sum(c['decision'] == 'cash' for c in cases), 22)
        self.assertEqual(len(set(audit.identity(c) for c in cases)), 26)


if __name__ == '__main__':
    unittest.main()
