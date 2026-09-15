import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from workbench.contract import discover, metadata, resolve_parameters
from workbench.metrics import calculate
from workbench.worker import simulate
from workbench.compare import compare


class WorkbenchTests(unittest.TestCase):
    def setUp(self):
        self.bars = pd.DataFrame({'open': [100., 101., 105., 102.], 'close': [101., 103., 102., 106.]}, index=pd.date_range('2026-01-05 14:30', periods=4, freq='1min', tz='UTC'))
        self.bars['availability_time'] = self.bars.index + pd.Timedelta(minutes=1)
        self.request = {'start': '2026-01-05', 'end': '2026-01-05', 'capital': 1000., 'fee': 1., 'slippage': 1., 'dataset': {'tick_size': .25, 'point_value': 2}}

    def test_next_open_costs_and_marked_equity_reconcile(self):
        eq, trades, positions = simulate(self.bars, pd.Series([1, 1, 0, 0], index=self.bars.index), self.request)
        # Buy 101 next open, sell 102 fourth open: $2 gross - $3 costs.
        self.assertAlmostEqual(eq.equity.iloc[-1], 999.)
        self.assertAlmostEqual(eq.cost.sum(), 3.)
        self.assertAlmostEqual(eq.net_pnl.sum(), trades.net_pnl.sum())
        self.assertEqual(len(trades), 1)
        self.assertEqual(positions.contracts.iloc[-1], 0)
        self.assertGreater(eq.equity.iloc[1], eq.equity.iloc[-1])

    def test_resize_and_reverse_costs_reconcile(self):
        for signals in ([1, 2, 1, 0], [1, -2, -1, 0], [2, 1, 0, 0]):
            eq, trades, _ = simulate(self.bars, pd.Series(signals, index=self.bars.index), self.request)
            self.assertAlmostEqual(eq.net_pnl.sum(), trades.net_pnl.sum())
            self.assertAlmostEqual(eq.cost.sum(), trades.cost.sum())

    def test_no_trades_has_undefined_sharpe(self):
        eq, trades, _ = simulate(self.bars, pd.Series(0, index=self.bars.index), self.request)
        metrics = calculate(eq, 1000., trades)
        self.assertIsNone(metrics['sharpe'])
        self.assertEqual(metrics['trades'], 0)
        self.assertEqual(metrics['net_return'], 0)

    def test_future_signal_cannot_change_earlier_equity(self):
        first, _, _ = simulate(self.bars, pd.Series([1, 1, 0, 0], index=self.bars.index), self.request)
        second, _, _ = simulate(self.bars, pd.Series([1, 1, 3, 0], index=self.bars.index), self.request)
        np.testing.assert_allclose(first.equity.iloc[:3], second.equity.iloc[:3])

    def test_unavailable_signal_cannot_fill(self):
        self.bars.loc[self.bars.index[0], 'availability_time'] += pd.Timedelta(minutes=1)
        eq, _, positions = simulate(self.bars, pd.Series([1, 0, 0, 0], index=self.bars.index), self.request)
        self.assertEqual(eq.equity.iloc[-1], 1000.)
        self.assertFalse(positions.contracts.any())

    def test_drawdown_keeps_initial_capital_and_monthly_peak(self):
        frame = pd.DataFrame({'timestamp': ['2026-01-30T20:00:00Z', '2026-02-02T20:00:00Z', '2026-02-03T20:00:00Z'], 'equity': [1100., 900., 950.]})
        result = calculate(frame, 1000.)
        self.assertAlmostEqual(result['max_drawdown'], 900 / 1100 - 1)
        self.assertEqual(result['underwater_bars'], 2)
        self.assertEqual(result['current_underwater_bars'], 2)
        frame.equity = [900., 900., 900.]
        self.assertAlmostEqual(calculate(frame, 1000.)['max_drawdown'], -.1)

    def test_discovery_does_not_execute_and_skips_template(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory) / 'strategies'; folder.mkdir()
            (folder / 'example.py').write_text("STRATEGY = {'id': 'example', 'name': 'Example', 'description': 'Test', 'parameters': {}, 'timeframes': ['1h']}\nraise RuntimeError('must not execute')")
            (folder / '_template.py').write_text('invalid Python!')
            result = discover(Path(directory))
            self.assertEqual(len(result['strategies']), 1)
            self.assertEqual(result['errors'], [])

    def test_parameter_validation_rejects_unknown_and_boolean_integer(self):
        spec = metadata(Path('strategies/_template.py'))
        for values in ({'lookback': True}, {'lookback': 0}, {'surprise': 3}, {'contracts': 1.5}):
            with self.assertRaises(ValueError):
                resolve_parameters(spec, values)

    def test_aligned_comparison_refuses_missing_observations(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = []
            for name, dates in [('a', ['2026-01-01', '2026-01-02', '2026-01-03', '2026-01-04']), ('b', ['2026-01-01', '2026-01-03', '2026-01-04'])]:
                folder = Path(directory) / name; folder.mkdir()
                (folder / 'input.json').write_text(json.dumps({'id': name, 'capital': 1000.}))
                pd.DataFrame({'timestamp': dates, 'equity': [1000.] * len(dates)}).to_csv(folder / 'equity.csv', index=False)
                paths.append(folder / 'input.json')
            with self.assertRaisesRegex(ValueError, 'calendars differ'):
                compare(paths)

    def test_template_signal_is_causal(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('template', 'strategies/_template.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        bars = self.bars.copy()
        parameters = {'lookback': 2, 'contracts': 1, 'allow_short': True}
        first = module.signals(bars, parameters)
        bars.loc[bars.index[-1], 'close'] = 10000
        second = module.signals(bars, parameters)
        pd.testing.assert_series_equal(first.iloc[:-1], second.iloc[:-1])

    def test_existing_strategy_adapter_is_causal(self):
        from strategies.moving_average import signals
        from strategy_engine.data import session_bars
        from strategy_engine.sessions import get_session
        index = pd.date_range('2026-01-05 14:30', periods=240, freq='1min', tz='UTC')
        close = 100 + np.sin(np.arange(240) / 10)
        source = pd.DataFrame({'open': close, 'high': close + 1, 'low': close - 1, 'close': close, 'volume': 10}, index=index)
        bars = session_bars(source, get_session('new-york-rth'), '5m')
        first = signals(bars, {'lookback': 2, 'contracts': 1})
        bars.loc[bars.index[-1], 'close'] = 10000
        second = signals(bars, {'lookback': 2, 'contracts': 1})
        pd.testing.assert_series_equal(first.iloc[:-1], second.iloc[:-1])


if __name__ == '__main__':
    unittest.main()
