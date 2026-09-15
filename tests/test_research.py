import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from workbench.contract import checksum
from workbench.research import assign_states, episode_summary, stitch, evaluate, entry_bar_indices
from unittest.mock import patch
from workbench.worker import simulate


class ResearchTests(unittest.TestCase):
    def test_event_entry_at_close_stays_in_its_execution_bar(self):
        times = pd.date_range('2025-01-02 15:00', periods=3, freq='5min', tz='UTC')
        event = pd.DataFrame({'entry_time': [times[0], times[0]], 'entry_bar_close': [times[0], times[1]]})
        self.assertEqual(entry_bar_indices(times, event).tolist(), [0, 1])
        signal = pd.DataFrame({'entry_time': [times[0]]})
        self.assertEqual(entry_bar_indices(times, signal).tolist(), [1])
        event.loc[0, 'entry_bar_close'] = times[-1] + pd.Timedelta(minutes=5)
        with self.assertRaisesRegex(ValueError, 'Cannot attribute'):
            entry_bar_indices(times, event)

    def test_two_scenario_event_evaluation_does_not_invent_delay_results(self):
        evaluation = {'candidates': [{'capital': 1000, 'strategy': {'execution_model': 'event-v1'}}], 'folds': [{}],
                      'scenarios': ['Baseline', 'Higher costs'], 'min_test_trades': 1, 'min_return': 0,
                      'max_drawdown': .35, 'inspected_overlap': []}
        runs = [{'input': {'research': {'scenario': name}}, 'result': {}} for name in evaluation['scenarios']]
        eq = pd.DataFrame({'timestamp': ['2025-01-02', '2025-01-03'], 'equity': [1000, 1010]})
        metrics = {'trades': 1, 'net_return': .01, 'max_drawdown': -.01}
        with tempfile.TemporaryDirectory() as directory, patch('workbench.research.stitch', return_value=(eq, metrics)):
            result = evaluate({'evaluation': evaluation, 'runs': runs}, Path(directory))
            self.assertEqual([s['name'] for s in result['scenarios']], evaluation['scenarios'])
            self.assertTrue(any('delay is unsupported' in w for w in result['warnings']))
            with self.assertRaisesRegex(ValueError, 'Incomplete scenario'):
                evaluate({'evaluation': evaluation, 'runs': runs[:1]}, Path(directory))

    def bars(self):
        index = pd.date_range('2026-01-01', periods=240, freq='1h', tz='UTC')
        price = 100 + np.sin(np.arange(240) / 6) + np.arange(240) / 50
        return pd.DataFrame({'open': price, 'close': price + .1, 'availability_time': index + pd.Timedelta(hours=1)}, index=index)

    def test_training_threshold_and_prior_labels_ignore_future_prices(self):
        for feature in ['volatility', 'trend']:
            bars = self.bars()
            first, labels, threshold, _ = assign_states(bars, feature, 5, .5, '2026-01-01', '2026-01-04')
            bars.loc[bars.index >= '2026-01-07', 'close'] *= 100
            second, next_labels, next_threshold, _ = assign_states(bars, feature, 5, .5, '2026-01-01', '2026-01-04')
            self.assertEqual(threshold, next_threshold)
            pd.testing.assert_series_equal(first.loc[:'2026-01-06'], second.loc[:'2026-01-06'])
            pd.testing.assert_series_equal(labels.loc[:'2026-01-06'], next_labels.loc[:'2026-01-06'])

    def test_current_bar_price_cannot_change_current_state_feature(self):
        bars = self.bars()
        first, _, _, _ = assign_states(bars, 'trend', 5, .5, '2026-01-01', '2026-01-04')
        bars.loc[bars.index[-1], 'close'] = 50000
        second, _, _, _ = assign_states(bars, 'trend', 5, .5, '2026-01-01', '2026-01-04')
        self.assertEqual(first.iloc[-1], second.iloc[-1])

    def test_nonpositive_price_features_stay_unknown(self):
        bars = self.bars()
        bars.loc[bars.index[150:160], 'close'] = -1
        _, labels, _, _ = assign_states(bars, 'volatility', 5, .5, '2026-01-01', '2026-01-04')
        self.assertEqual(labels.iloc[155], 'Unknown')

    def test_cost_and_delay_scenarios_change_execution_as_declared(self):
        bars = self.bars().iloc[:5]
        targets = pd.Series([1, 1, 0, 0, 0], index=bars.index)
        request = {'start': '2026-01-01', 'end': '2026-01-01', 'capital': 1000., 'fee': 1., 'slippage': 1., 'dataset': {'tick_size': .25, 'point_value': 2}}
        base, trades, _ = simulate(bars, targets, request)
        stress, stress_trades, _ = simulate(bars, targets, {**request, 'fee': 2., 'slippage': 2.})
        _, delayed, _ = simulate(bars, targets, {**request, 'delay_bars': 1})
        self.assertAlmostEqual(stress.cost.sum(), 2 * base.cost.sum())
        self.assertAlmostEqual(stress.net_pnl.sum(), base.net_pnl.sum() - base.cost.sum())
        self.assertEqual(trades.entry_time.iloc[0], stress_trades.entry_time.iloc[0])
        self.assertEqual(pd.Timestamp(delayed.entry_time.iloc[0]) - pd.Timestamp(trades.entry_time.iloc[0]), pd.Timedelta(hours=1))

    def test_stitch_does_not_reset_equity_peaks_between_folds(self):
        with tempfile.TemporaryDirectory() as directory:
            runs = []
            for fold, (dates, pnl) in enumerate([(['2026-01-05', '2026-01-06'], [100., 100.]), (['2026-01-07', '2026-01-08'], [-100., -100.])]):
                folder = Path(directory) / str(fold); folder.mkdir()
                pd.DataFrame({'timestamp': dates, 'net_pnl': pnl, 'equity': 1000 + np.cumsum(pnl), 'cost': [0., 0.]}).to_csv(folder / 'equity.csv', index=False)
                pd.DataFrame({'net_pnl': [sum(pnl)]}).to_csv(folder / 'trades.csv', index=False)
                runs.append({'folder': str(folder), 'input': {'capital': 1000., 'research': {'fold': fold}}, 'result': {'artifacts': [{'name': name, 'checksum': checksum(folder / name)} for name in ['equity.csv', 'trades.csv']]}})
            combined, metrics = stitch(runs, 1000.)
            self.assertEqual(combined.equity.tolist(), [1100., 1200., 1100., 1000.])
            self.assertAlmostEqual(metrics['max_drawdown'], 1000 / 1200 - 1)
            self.assertEqual(metrics['net_pnl'], 0.)
            with self.assertRaisesRegex(ValueError, 'Overlapping'):
                stitch([runs[0], runs[0]], 1000.)

    def test_episodes_and_uncertainty_do_not_treat_adjacent_bars_as_trials(self):
        frame = pd.DataFrame({'state': ['Higher'] * 20, 'fold': [0] * 10 + [1] * 10, 'net_pnl': 1., 'cost': .1, 'intrabar_contracts': 1, 'entry_count': 0})
        summary = episode_summary(frame, 42)[0]
        self.assertEqual(summary['observations'], 20)
        self.assertEqual(summary['episodes'], 2)
        self.assertIsNone(summary['mean_episode_pnl_interval_95'])
        frame['state'] = ['Higher', 'Lower'] * 10
        self.assertEqual(episode_summary(frame, 42), episode_summary(frame, 42))
        self.assertIsNotNone(episode_summary(frame, 42)[0]['mean_episode_pnl_interval_95'])


if __name__ == '__main__':
    unittest.main()
