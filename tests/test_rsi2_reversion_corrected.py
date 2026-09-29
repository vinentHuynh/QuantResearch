import unittest

import numpy as np
import pandas as pd

from strategies._legacy_signals import rsi_reversion
from strategies.rsi2_reversion_corrected import STRATEGY, signals, simple_rsi2, validate
from workbench.contract import resolve_parameters
from workbench.warmup import required_bars
from workbench.worker import simulate


class CorrectedRSI2Tests(unittest.TestCase):
    def bars(self):
        index = pd.date_range('2024-01-02 09:30', periods=8, freq='B', tz='America/New_York')
        close = np.array([80., 100., 99., 98., 99., 101., 102., 103.])
        opening = np.array([80., 80., 100., 99., 98., 99., 101., 102.])
        return pd.DataFrame({'open': opening, 'high': np.maximum(opening, close) + 1,
                             'low': np.minimum(opening, close) - 1, 'close': close,
                             'availability_time': index + pd.Timedelta(hours=6, minutes=30)}, index=index)

    def params(self, **changes):
        return resolve_parameters(STRATEGY, {'trend_lookback': 4, **changes})

    def test_rebound_exits_after_two_up_closes_and_preserves_legacy(self):
        bars = self.bars()
        target = signals(bars, self.params())
        self.assertEqual(target.tolist(), [0, 0, 0, 1, 1, 0, 0, 0])
        legacy = rsi_reversion(bars.close, 4, 10, 70)
        self.assertEqual(legacy.tolist(), [0, 0, 0, 1, 1, 1, 1, 1])

    def test_zero_gain_loss_and_flat_windows_are_defined_after_initialization(self):
        for prices, expected in [([10., 11., 12.], 100.), ([12., 11., 10.], 0.),
                                 ([10., 10., 10.], 50.), ([10., 11., 10.], 50.)]:
            with self.subTest(prices=prices):
                result = simple_rsi2(pd.Series(prices))
                self.assertTrue(result.iloc[:2].isna().all())
                self.assertEqual(result.iloc[-1], expected)

    def test_rebound_exit_fills_next_open_and_reconciles_costs(self):
        bars = self.bars()
        request = {'start': '2024-01-01', 'end': '2024-02-01', 'capital': 100000,
                   'dataset': {'point_value': 20, 'tick_size': .25}, 'fee': 2.5, 'slippage': 1}
        equity, trades, _ = simulate(bars, signals(bars, self.params()), request)
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades.iloc[0].entry_time, bars.index[4].isoformat())
        self.assertEqual(trades.iloc[0].exit_time, bars.index[6].isoformat())
        self.assertAlmostEqual(trades.iloc[0].net_pnl, (101 - 98) * 20 - 15)
        self.assertAlmostEqual(equity.iloc[-1].equity - 100000, trades.net_pnl.sum())

    def test_prefixes_and_future_changes_preserve_past_decisions(self):
        bars = self.bars()
        parameters = self.params(contracts=3)
        expected = signals(bars, parameters)
        for length in range(1, len(bars) + 1):
            pd.testing.assert_series_equal(signals(bars.iloc[:length], parameters), expected.iloc[:length])
        changed = bars.copy()
        changed.loc[changed.index[6]:, 'close'] = [5., 500.]
        pd.testing.assert_series_equal(signals(changed, parameters).iloc[:6], expected.iloc[:6])
        self.assertTrue(expected.isin([0., 3.]).all())

    def test_threshold_validation_and_conservative_daily_warmup(self):
        for changes in [{'entry_rsi': 70}, {'entry_rsi': 80, 'exit_rsi': 70}]:
            with self.assertRaises(ValueError):
                validate(self.params(**changes), {})
        self.assertEqual(required_bars(STRATEGY, self.params(trend_lookback=2)), 3)
        self.assertEqual(required_bars(STRATEGY, self.params(trend_lookback=200)), 201)


if __name__ == '__main__':
    unittest.main()
