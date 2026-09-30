"""Focused rule and accounting checks for the post-audit AW revision."""

from contextlib import redirect_stdout
import io
import unittest

import pandas as pd

from strategies import aw_model_nq_revised as aw
from strategies._aw_news_calendar import news_gate
from test_aw_model_nq import CT, fixture, request
from workbench.contract import metadata, resolve_parameters
from workbench.events import simulate_events


def parameters(**changes):
    return resolve_parameters(aw.STRATEGY, changes)


def replay(style='first-touch', **changes):
    bars = fixture()
    params = parameters(bias_policy='unrestricted', entry_style=style,
                        min_rr_early=0.0, min_rr_primary=0.0, **changes)
    model = aw.create_strategy(bars, params, request())
    model.days[pd.Timestamp('2024-03-12').date()].htf_mid = 0.0
    with redirect_stdout(io.StringIO()):
        equity, trades, _, signals = simulate_events(
            bars, model, request(), return_signals=True)
    return model, equity, trades, signals


class AWRevisedTests(unittest.TestCase):
    def test_metadata_and_news_release_gate(self):
        self.assertEqual(metadata('strategies/aw_model_nq_revised.py')['id'],
                         'aw-model-nq-revised')
        at_open = pd.Timestamp('2024-03-20 08:30', tz=CT)
        self.assertFalse(news_gate(at_open.date(), at_open)[0])  # FOMC
        self.assertTrue(news_gate(pd.Timestamp('2024-03-12').date(),
                                  pd.Timestamp('2024-03-12 08:30', tz=CT))[0])  # CPI released
        self.assertFalse(news_gate(pd.Timestamp('2024-03-12').date(),
                                   pd.Timestamp('2024-03-12 07:29', tz=CT))[0])
        self.assertFalse(news_gate(pd.Timestamp('2026-09-16').date(),
                                   pd.Timestamp('2026-09-16 09:00', tz=CT))[0])
        self.assertTrue(news_gate(pd.Timestamp('2026-09-04').date(),
                                  pd.Timestamp('2026-09-04 08:30', tz=CT))[0])
        self.assertTrue(news_gate(pd.Timestamp('2026-09-11').date(),
                                  pd.Timestamp('2026-09-11 08:30', tz=CT))[0])

    def test_first_touch_uses_resting_limit_and_exact_micro_equivalent_risk(self):
        model, equity, trades, signals = replay()
        self.assertEqual(len(trades), 1)
        trade = trades.iloc[0]
        self.assertEqual(trade.entry, 99.25)
        self.assertEqual(trade.original_stop, 102.0)
        self.assertEqual(trade.original_target, 95.0)
        self.assertEqual(trade.point_value, 2.0)
        self.assertEqual(abs(trade.quantity),
                         10 * trade.nq_contracts + trade.mnq_contracts)
        self.assertLessEqual(trade.initial_risk_cash, 500.0)
        self.assertEqual(trade.signal_id,
                         signals.loc[signals.event == 'submitted', 'signal_id'].iloc[0])
        self.assertEqual(trade.order_id,
                         signals.loc[signals.event == 'filled', 'order_id'].iloc[0])
        self.assertAlmostEqual(trades.net_pnl.sum(), equity.net_pnl.sum())
        self.assertEqual(model.funnel['filled_entries'], 1)

    def test_half_gap_limit_is_deeper_and_can_remain_unfilled(self):
        _, _, first, first_signals = replay('first-touch')
        _, _, half, half_signals = replay('half-gap')
        self.assertEqual(len(first), 1)
        self.assertEqual(len(half), 0)
        first_price = first_signals.loc[first_signals.event == 'submitted',
                                        'requested_limit'].iloc[0]
        half_price = half_signals.loc[half_signals.event == 'submitted',
                                      'requested_limit'].iloc[0]
        self.assertEqual(first_price, 99.25)
        self.assertEqual(half_price, 99.5)

    def test_deeper_resweep_before_break_sets_the_structural_stop(self):
        bars = fixture()
        bars.loc[pd.Timestamp('2024-03-12 08:34', tz=CT), 'high'] = 102.25
        params = parameters(bias_policy='unrestricted', min_rr_early=0.0,
                            min_rr_primary=0.0)
        model = aw.create_strategy(bars, params, request())
        model.days[pd.Timestamp('2024-03-12').date()].htf_mid = 0.0
        with redirect_stdout(io.StringIO()):
            _, trades, _, signals = simulate_events(
                bars, model, request(), return_signals=True)
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades.iloc[0].original_stop, 102.5)
        self.assertLessEqual(trades.iloc[0].initial_risk_cash, 500.0)
        self.assertEqual(signals.loc[signals.event == 'submitted',
                                     'original_stop'].iloc[0], 102.5)

    def test_causal_confirmation_open_uses_execution_risk_cap(self):
        _, _, trades, signals = replay('fvg-confirmation-open')
        self.assertEqual(len(trades), 1)
        self.assertLessEqual(trades.iloc[0].initial_risk_cash, 500.0)
        self.assertEqual(trades.iloc[0].entry,
                         signals.loc[signals.event == 'filled', 'fill_price'].iloc[0])

    def test_location_gate_and_roll_segmentation(self):
        bars = fixture()
        model = aw.create_strategy(bars, parameters(bias_policy='unrestricted'), request())
        with redirect_stdout(io.StringIO()):
            _, trades, _ = simulate_events(bars, model, request())
        self.assertEqual(len(trades), 0)
        self.assertGreaterEqual(model.funnel['location_gate_rejections'] +
                                model.funnel['reward_gate_rejections'], 1)

        rolled = bars.copy()
        rolled['instrument_id'] = 2
        rolled.loc[rolled.index < pd.Timestamp('2024-03-11 17:00', tz=CT),
                   'instrument_id'] = 1
        htf = aw._complete_resample(rolled, '2h', '1h')
        self.assertNotIn(pd.Timestamp('2024-03-12').date(),
                         aw._daily_levels(rolled, htf))

    def test_missing_overnight_or_recent_two_hour_candle_skips_day(self):
        base = fixture()
        day = pd.Timestamp('2024-03-12').date()
        six = pd.date_range('2024-03-11 18:00', periods=6, freq='min', tz=CT)
        too_sparse = base.drop(six)
        self.assertNotIn(day, aw._daily_levels(
            too_sparse, aw._complete_resample(too_sparse, '2h', '1h')))

        recent_gap = base.drop(pd.Timestamp('2024-03-12 04:30', tz=CT))
        self.assertNotIn(day, aw._daily_levels(
            recent_gap, aw._complete_resample(recent_gap, '2h', '1h')))

    def test_one_and_three_minute_signal_modes_have_separate_completed_candles(self):
        bars = fixture()
        one = aw.create_strategy(bars, parameters(signal_timeframe='1m'), request())
        three = aw.create_strategy(bars, parameters(signal_timeframe='3m'), request())
        self.assertEqual(one.body_lookback, 60)
        self.assertEqual(three.body_lookback, 20)
        self.assertGreater(len(one.three), len(three.three))
        self.assertEqual(one.signal_width, pd.Timedelta(minutes=1))
        self.assertEqual(three.signal_width, pd.Timedelta(minutes=3))

    def test_two_hour_clock_anchor_is_stable_across_dst(self):
        winter = pd.date_range('2022-01-03 05:00', periods=120, freq='min', tz=CT)
        summer = pd.date_range('2022-07-05 05:00', periods=120, freq='min', tz=CT)
        index = winter.append(summer)
        bars = pd.DataFrame({'open': 100.0, 'high': 101.0,
                             'low': 99.0, 'close': 100.0,
                             'instrument_id': 1}, index=index)
        two = aw._complete_resample(bars, '2h', '1h')
        self.assertEqual(len(two), 2)
        self.assertEqual(two.index[0], pd.Timestamp('2022-01-03 05:00', tz=CT))
        self.assertEqual(two.index[1], pd.Timestamp('2022-07-05 05:00', tz=CT))
        self.assertEqual(two.ready.iloc[0], pd.Timestamp('2022-01-03 07:00', tz=CT))
        self.assertEqual(two.ready.iloc[1], pd.Timestamp('2022-07-05 07:00', tz=CT))

    def test_missing_two_hour_candle_cannot_create_synthetic_fvg_vote(self):
        index = pd.DatetimeIndex([
            pd.Timestamp('2024-03-12 01:00', tz=CT),
            pd.Timestamp('2024-03-12 03:00', tz=CT),
            pd.Timestamp('2024-03-12 07:00', tz=CT),
        ])
        htf = pd.DataFrame({'high': [101.0, 102.0, 105.0],
                            'low': [99.0, 100.0, 104.0]}, index=index)
        partial = pd.DataFrame(columns=['high', 'low'])
        self.assertEqual(aw._untouched_fvg_votes(htf, 102.5, partial),
                         (False, False))

    def test_missing_later_two_hour_candle_invalidates_old_untouched_fvg(self):
        index = pd.DatetimeIndex([
            pd.Timestamp(f'2024-03-12 {hour:02d}:00', tz=CT)
            for hour in (1, 3, 5, 9, 11)
        ])
        htf = pd.DataFrame({'high': [101.0, 102.0, 105.0, 105.0, 105.0],
                            'low': [99.0, 100.0, 104.0, 104.0, 104.0]}, index=index)
        partial = pd.DataFrame(columns=['high', 'low'])
        self.assertEqual(aw._untouched_fvg_votes(htf, 102.5, partial),
                         (False, False))


if __name__ == '__main__':
    unittest.main()
