"""Causal and execution checks for the frozen AW NQ Workbench adapter."""

from contextlib import redirect_stdout
import importlib.util
import io
from pathlib import Path
import sys
import unittest

import pandas as pd

from strategies import aw_model_nq
from workbench.contract import metadata, resolve_parameters
from workbench.events import simulate_events


ROOT = Path(__file__).resolve().parents[1]
CT = 'America/Chicago'


def request():
    return {'dataset': {'symbol': 'NQ', 'tick_size': .25, 'point_value': 20},
            'timeframe': '1m', 'session': 'full-trading-day',
            'start': '2024-03-12', 'end': '2024-03-12',
            'capital': 100000, 'fee': 2.5, 'slippage': 1}


def params(**changes):
    return resolve_parameters(aw_model_nq.STRATEGY, changes)


def fixture(sweep_start='08:30'):
    previous = pd.date_range('2024-03-11 08:30', '2024-03-11 14:59', freq='min', tz=CT)
    overnight = pd.date_range('2024-03-11 17:00', '2024-03-12 08:29', freq='min', tz=CT)
    morning = pd.date_range('2024-03-12 08:30', '2024-03-12 10:49', freq='min', tz=CT)
    index = previous.append(overnight).append(morning)
    bars = pd.DataFrame({'open': 99.75, 'high': 100.25,
                         'low': 99.5, 'close': 100.0,
                         'volume': 10}, index=index)
    bars['availability_time'] = index + pd.Timedelta(minutes=1)
    bars.loc[pd.Timestamp('2024-03-11 09:00', tz=CT), 'high'] = 105.0
    bars.loc[pd.Timestamp('2024-03-11 09:01', tz=CT), 'low'] = 90.0
    bars.loc[pd.Timestamp('2024-03-11 17:05', tz=CT), 'low'] = 95.0
    # Two rising confirmed pivot highs and lows before the morning sweep.
    for wall, column, value in [
        ('07:30', 'low', 97.5), ('07:39', 'high', 100.75),
        ('07:48', 'low', 98.5), ('07:57', 'high', 101.0),
        ('08:09', 'low', 99.0), ('08:18', 'high', 101.25),
    ]:
        bars.loc[pd.Timestamp('2024-03-12 ' + wall, tz=CT), column] = value
    start = pd.Timestamp('2024-03-12 ' + sweep_start, tz=CT)
    bars.loc[start, 'high'] = 101.75
    # First complete 3m bar after the sweep is the FVG's first candle.
    middle = start + pd.Timedelta(minutes=6)
    bars.loc[middle, 'low'] = 98.0
    bars.loc[middle + pd.Timedelta(minutes=2), 'close'] = 98.25
    third_start = middle + pd.Timedelta(minutes=3)
    for stamp in pd.date_range(third_start, periods=3, freq='min'):
        bars.loc[stamp, ['open', 'high', 'low', 'close']] = [98.5, 99.25, 98.0, 98.25]
    touch = third_start + pd.Timedelta(minutes=3)
    bars.loc[touch, ['open', 'high', 'low', 'close']] = [98.5, 99.5, 98.5, 99.0]
    fill = touch + pd.Timedelta(minutes=1)
    bars.loc[fill, ['open', 'high', 'low', 'close']] = [99.0, 99.25, 98.75, 98.75]
    bars.loc[fill + pd.Timedelta(minutes=1), ['open', 'high', 'low', 'close']] = [98.75, 99.0, 94.75, 95.0]
    return bars


def replay_to(model, bars, stop):
    orders = []
    for i, (timestamp, row) in enumerate(bars.iterrows()):
        if timestamp > stop:
            break
        order = model.on_close(i, row, {'position': 0, 'position_at_open': 0,
                                         'tradable': True, 'equity': 100000})
        if order is not None:
            orders.append((timestamp, order))
    return orders


class AWModelNQTests(unittest.TestCase):
    def test_discovery_and_nq_one_minute_guard(self):
        spec = metadata(ROOT / 'strategies' / 'aw_model_nq.py')
        self.assertEqual(spec['id'], 'aw-model-nq')
        self.assertEqual(spec['execution_model'], 'event-v1')
        aw_model_nq.validate(params(), request())
        for change in ({'dataset': {'symbol': 'MNQ', 'tick_size': .25}},
                       {'session': 'new-york-rth'}, {'timeframe': '5m'},
                       {'delay_bars': 1}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                aw_model_nq.validate(params(), {**request(), **change})

    def test_workbench_unregistered_module_loader(self):
        path = ROOT / 'strategies' / 'aw_model_nq.py'
        previous = sys.modules.pop('user_strategy', None)
        try:
            spec = importlib.util.spec_from_file_location('user_strategy', path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            self.assertNotIn('user_strategy', sys.modules)
            model = module.create_strategy(fixture(), params(bias_required=False), request())
            self.assertEqual(model.days[pd.Timestamp('2024-03-12').date()].onh, 101.25)
        finally:
            if previous is not None:
                sys.modules['user_strategy'] = previous

    def test_full_sequence_submits_next_open_bracket_then_hits_erl(self):
        bars = fixture()
        model = aw_model_nq.create_strategy(bars, params(bias_required=False), request())
        day = pd.Timestamp('2024-03-12').date()
        self.assertIn(day, model.days)
        self.assertEqual(model.days[day].onh, 101.25)
        self.assertEqual(model.days[day].onl, 95.0)
        with redirect_stdout(io.StringIO()) as output:
            _, trades, _ = simulate_events(bars, model, request())
        self.assertEqual(len(trades), 1, output.getvalue())
        trade = trades.iloc[0]
        self.assertEqual(pd.Timestamp(trade.entry_time).tz_convert(CT),
                         pd.Timestamp('2024-03-12 08:43', tz=CT))
        self.assertEqual(trade.entry, 99.0)
        self.assertEqual(trade.exit, 95.0)
        self.assertEqual(trade.exit_reason, 'limit')
        self.assertIn('"stop": 102.0', output.getvalue())
        self.assertIn('"target": 95.0', output.getvalue())
        self.assertIn('AW_FUNNEL ', output.getvalue())

    def test_future_prices_do_not_change_pre_sweep_snapshot_or_earlier_state(self):
        bars = fixture()
        altered = bars.copy()
        altered.loc[pd.Timestamp('2024-03-12 08:36', tz=CT):,
                    ['high', 'low', 'close']] = [200.0, 50.0, 120.0]
        baseline = aw_model_nq.create_strategy(bars, params(bias_required=False), request())
        future = aw_model_nq.create_strategy(altered, params(bias_required=False), request())
        day = pd.Timestamp('2024-03-12').date()
        self.assertEqual(baseline.days[day], future.days[day])
        stop = pd.Timestamp('2024-03-12 08:35', tz=CT)
        with redirect_stdout(io.StringIO()):
            self.assertEqual(replay_to(baseline, bars, stop),
                             replay_to(future, altered, stop))
        self.assertEqual(baseline.funnel, future.funnel)
        self.assertEqual(baseline.candidate, future.candidate)

    def test_overnight_extrema_remain_eligible_at_0830_open(self):
        bars = fixture()
        model = aw_model_nq.create_strategy(bars, params(bias_required=False), request())
        with redirect_stdout(io.StringIO()):
            replay_to(model, bars, pd.Timestamp('2024-03-12 08:29', tz=CT))
        self.assertEqual(model.day, pd.Timestamp('2024-03-12').date())
        self.assertNotIn('ONH', model.taken)
        self.assertNotIn('ONL', model.taken)
        self.assertNotIn('ONH', model.taken_at_three_start)
        self.assertNotIn('ONL', model.taken_at_three_start)

    def test_partial_preopen_two_hour_candle_can_fill_htf_gap(self):
        index = pd.date_range('2024-03-11 17:00', periods=5, freq='2h', tz=CT)
        htf = pd.DataFrame({
            'open': [106, 102, 98, 97, 96],
            'high': [107, 104, 99, 98, 97],
            'low': [105, 101, 95, 94, 93],
            'close': [106, 102, 98, 97, 96],
        }, index=index)
        empty = pd.DataFrame(columns=['high', 'low'])
        partial = pd.DataFrame({'high': [102], 'low': [96]})
        self.assertTrue(aw_model_nq._untouched_fvg_votes(htf, 92, empty)[0])
        self.assertFalse(aw_model_nq._untouched_fvg_votes(htf, 92, partial)[0])

    def test_early_declared_close_blocks_sweep_and_touch(self):
        bars = fixture()
        model = aw_model_nq.create_strategy(bars, params(bias_required=False), request())
        model.day = pd.Timestamp('2024-03-12').date()
        model.day_cutoff = pd.Timestamp('2024-03-12 08:30', tz=CT)
        model.candidate = aw_model_nq.Candidate(
            -1, 'ONH', 101.25, 99.0, 101.75,
            pd.Timestamp('2024-03-12 08:33', tz=CT), phase='gap',
            gap_low=99.25, gap_high=99.5,
            gap_ready=pd.Timestamp('2024-03-12 08:42', tz=CT))
        touch = pd.Series({'open': 99.0, 'high': 99.5,
                           'low': 98.5, 'close': 99.0})
        self.assertIsNone(model._entry_on_touch(touch, {'position': 0,
                                                         'position_at_open': 0,
                                                         'tradable': True},
                                                pd.Timestamp('2024-03-12 08:43', tz=CT)))
        self.assertIsNone(model.candidate)

    def test_prior_valid_short_cash_session_supplies_next_day_levels(self):
        early = pd.date_range('2024-11-29 08:30', '2024-11-29 12:14', freq='min', tz=CT)
        overnight = pd.date_range('2024-12-01 17:00', '2024-12-02 08:29', freq='min', tz=CT)
        index = early.append(overnight)
        bars = pd.DataFrame({'open': 99.75, 'high': 100.25,
                             'low': 99.5, 'close': 100.0}, index=index)
        bars['availability_time'] = index + pd.Timedelta(minutes=1)
        bars.loc[pd.Timestamp('2024-11-29 09:00', tz=CT), 'high'] = 105.0
        bars.loc[pd.Timestamp('2024-11-29 09:01', tz=CT), 'low'] = 95.0
        htf = aw_model_nq._complete_resample(bars, '2h', '1h')
        levels = aw_model_nq._daily_levels(bars, htf)
        monday = levels[pd.Timestamp('2024-12-02').date()]
        self.assertEqual(monday.pdh, 105.0)
        self.assertEqual(monday.pdl, 95.0)

    def test_incomplete_immediately_prior_cash_session_is_not_replaced_by_older_day(self):
        bars = fixture().drop(pd.Timestamp('2024-03-11 09:10', tz=CT))
        friday = pd.date_range('2024-03-08 08:30', '2024-03-08 14:59', freq='min', tz=CT)
        older = pd.DataFrame({'open': 99.75, 'high': 110.0,
                              'low': 80.0, 'close': 100.0,
                              'volume': 10}, index=friday)
        older['availability_time'] = friday + pd.Timedelta(minutes=1)
        bars = pd.concat([older, bars]).sort_index()
        htf = aw_model_nq._complete_resample(bars, '2h', '1h')
        levels = aw_model_nq._daily_levels(bars, htf)
        self.assertNotIn(pd.Timestamp('2024-03-12').date(), levels)

    def test_first_touch_minute_cannot_use_pivot_taken_inside_current_three(self):
        bars = fixture()
        model = aw_model_nq.create_strategy(bars, params(bias_required=False), request())
        day = pd.Timestamp('2024-03-12').date()
        model._new_day(day, {'position': 0})
        model.open_pivot_lows = [(96.5, pd.Timestamp('2024-03-12 08:30', tz=CT))]
        model.candidate = aw_model_nq.Candidate(
            -1, 'ONH', 101.25, 99.0, 101.75,
            pd.Timestamp('2024-03-12 08:33', tz=CT), phase='gap',
            gap_low=99.25, gap_high=99.5,
            gap_ready=pd.Timestamp('2024-03-12 08:42', tz=CT))
        stamp = pd.Timestamp('2024-03-12 08:42', tz=CT)
        i = bars.index.get_loc(stamp)
        touch = bars.iloc[i].copy()
        touch['low'] = 96.5
        with redirect_stdout(io.StringIO()):
            order = model._step(i, touch, {'position': 0,
                                            'position_at_open': 0,
                                            'tradable': True, 'equity': 100000})
        self.assertIsNotNone(order)
        self.assertEqual(order['target'], -1)
        self.assertIsNone(model.plan.internal)

    def test_completed_three_minute_sweep_after_cutoff_is_ignored(self):
        bars = fixture(sweep_start='10:30')
        model = aw_model_nq.create_strategy(bars, params(bias_required=False), request())
        with redirect_stdout(io.StringIO()):
            _, trades, _ = simulate_events(bars, model, request())
        self.assertTrue(trades.empty)
        self.assertEqual(model.funnel['neckline_sweeps'], 0)

    def test_missing_immediate_next_minute_expires_touch_order(self):
        bars = fixture()
        bars = bars.drop(pd.Timestamp('2024-03-12 08:43', tz=CT))
        model = aw_model_nq.create_strategy(bars, params(bias_required=False), request())
        with redirect_stdout(io.StringIO()) as output:
            _, trades, _ = simulate_events(bars, model, request())
        self.assertTrue(trades.empty)
        self.assertEqual(model.funnel['submitted_entries'], 1)
        self.assertIn('Expired next-open order', output.getvalue())

    def test_no_fvg_touch_order_after_1030(self):
        bars = fixture()
        model = aw_model_nq.create_strategy(bars, params(bias_required=False), request())
        model.day = pd.Timestamp('2024-03-12').date()
        model.day_cutoff = model._cutoff(model.day)
        model.candidate = aw_model_nq.Candidate(
            -1, 'ONH', 101.25, 99.0, 101.75,
            pd.Timestamp('2024-03-12 08:33', tz=CT),
            phase='gap', gap_low=99.25, gap_high=99.5,
            gap_ready=pd.Timestamp('2024-03-12 08:42', tz=CT))
        touch = pd.Series({'open': 99.0, 'high': 99.5,
                           'low': 98.5, 'close': 99.0})
        result = model._entry_on_touch(touch, {'position': 0,
                                                'position_at_open': 0,
                                                'tradable': True},
                                       pd.Timestamp('2024-03-12 10:31', tz=CT))
        self.assertIsNone(result)
        self.assertIsNone(model.candidate)


if __name__ == '__main__':
    unittest.main()
