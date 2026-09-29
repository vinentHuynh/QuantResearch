import unittest

import numpy as np
import pandas as pd

from strategies.short_term_reversal import STRATEGY, signals, validate
from workbench.contract import resolve_parameters
from workbench.worker import simulate


class ShortTermReversalTests(unittest.TestCase):
    def bars(self):
        index = pd.date_range('2024-01-01 09:30', periods=7, freq='B', tz='America/New_York')
        close = np.array([100., 101., 102., 99., 100., 103., 104.])
        return pd.DataFrame({'open': [100., 100., 101., 101., 98., 102., 103.],
                             'high': np.maximum(close, 104.), 'low': close - .1,
                             'close': close, 'availability_time': index + pd.Timedelta(hours=6, minutes=30)}, index=index)

    def params(self, **edits):
        return resolve_parameters(STRATEGY, {'trend_lookback': 2, 'confluence': 'none', **edits})

    def test_signal_is_not_shifted_and_fills_next_open(self):
        bars = self.bars()
        target = signals(bars, self.params())
        self.assertEqual(target.tolist(), [0, 0, 0, 1, 0, 0, 0])
        request = {'start': '2024-01-01', 'end': '2024-01-31', 'capital': 100000,
                   'dataset': {'point_value': 20, 'tick_size': .25}, 'fee': 2.5, 'slippage': 1}
        equity, trades, positions = simulate(bars, target, request)
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades.iloc[0].entry_time, bars.index[4].isoformat())
        self.assertEqual(trades.iloc[0].exit_time, bars.index[5].isoformat())
        self.assertEqual(trades.iloc[0].net_pnl, (102 - 98) * 20 - 15)
        self.assertAlmostEqual(equity.iloc[-1].equity - 100000, trades.net_pnl.sum())

    def test_future_changes_do_not_change_past_decisions(self):
        bars = self.bars()
        for mode in STRATEGY['parameters']['confluence']['choices']:
            p = self.params(confluence=mode, direction='long-short')
            original = signals(bars, p)
            for length in range(2, len(bars) + 1):
                pd.testing.assert_series_equal(original.iloc[:length], signals(bars.iloc[:length], p))

    def test_trend_filter_blocks_below_average_and_short_is_optional(self):
        bars = self.bars()
        self.assertEqual(signals(bars, self.params(confluence='trend')).iloc[3], 0)
        self.assertEqual(signals(bars, self.params(direction='long-short')).iloc[5], -1)
        self.assertEqual(signals(bars, self.params()).iloc[5], 0)

    def test_weak_close_rejects_recovered_close_and_zero_range(self):
        bars = self.bars()
        self.assertEqual(signals(bars, self.params(confluence='weak-close')).iloc[3], 1)
        bars.loc[bars.index[3], 'low'] = 80
        self.assertEqual(signals(bars, self.params(confluence='weak-close')).iloc[3], 0)
        bars.loc[bars.index[3], ['high', 'low']] = 99
        self.assertEqual(signals(bars, self.params(confluence='weak-close')).iloc[3], 0)

    def test_initialization_and_strict_threshold(self):
        bars = self.bars()
        self.assertTrue((signals(bars, self.params(trend_lookback=200)) == 0).all())
        bars.loc[bars.index[2], 'close'] = 100
        bars.loc[bars.index[3], 'close'] = 99.5
        self.assertEqual(signals(bars, self.params(decline_pct=.5)).iloc[3], 0)

    def test_holding_period_and_rebound_exit(self):
        bars = self.bars()
        self.assertEqual(signals(bars, self.params(hold_sessions=3)).tolist(), [0, 0, 0, 1, 1, 1, 0])
        self.assertEqual(signals(bars, self.params(hold_sessions=3, exit_on_rebound=True)).tolist(), [0, 0, 0, 1, 0, 0, 0])

    def test_hard_limit_does_not_silently_renew(self):
        bars = self.bars()
        bars['close'] = [100., 100., 98., 96., 94., 92., 90.]
        self.assertEqual(signals(bars, self.params(hold_sessions=2, renew_on_signal=False)).tolist(), [0, 0, 1, 1, 0, 1, 1])
        self.assertEqual(signals(bars, self.params(hold_sessions=2)).tolist(), [0, 0, 1, 1, 1, 1, 1])

    def test_crash_cap_and_invalid_combinations(self):
        self.assertEqual(signals(self.bars(), self.params(max_decline_pct=2)).iloc[3], 0)
        for edits in [{'max_decline_pct': 1}, {'min_atr_multiple': .5, 'atr_period': 20}]:
            with self.assertRaises(ValueError):
                validate(self.params(**edits), {})

    def test_atr_excludes_the_signal_day_and_extended_state_is_causal(self):
        bars = self.bars()
        bars['high'] = bars.close + .1
        bars['low'] = bars.close - .1
        p = self.params(trend_lookback=3, atr_period=2, min_atr_multiple=1.5, hold_sessions=3)
        self.assertEqual(signals(bars, p).iloc[3], 1)
        bars.loc[bars.index[3], 'high'] = 1000
        self.assertEqual(signals(bars, p).iloc[3], 1)
        for length in range(2, len(bars) + 1):
            pd.testing.assert_series_equal(signals(bars, p).iloc[:length], signals(bars.iloc[:length], p))


if __name__ == '__main__':
    unittest.main()
