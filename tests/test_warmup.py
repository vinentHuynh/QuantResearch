import tempfile
import unittest
from pathlib import Path

import pandas as pd

from workbench.contract import metadata
from workbench.warmup import coverage, preview, required_bars, warning


class WarmupTests(unittest.TestCase):
    def setUp(self):
        self.spec = metadata(Path('strategies/multi_speed_momentum.py'))
        self.request = {'start': '2026-01-06', 'warmup_days': 1}

    def test_momentum_requires_all_four_horizons_plus_origin(self):
        self.assertEqual(required_bars(self.spec, {'lookback': 60}), 241)
        self.assertEqual(required_bars(self.spec, {'lookback': 2}), 9)

    def test_only_fully_loaded_and_available_prior_bars_count(self):
        index = pd.to_datetime(['2026-01-04T23:00Z', '2026-01-05T23:00Z', '2026-01-05T23:30Z', '2026-01-06T00:00Z'])
        bars = pd.DataFrame({'availability_time': pd.to_datetime([
            '2026-01-05T01:00Z', '2026-01-06T00:00Z', '2026-01-06T00:30Z', '2026-01-06T01:00Z'])}, index=index)
        result = coverage(bars, self.request, self.spec, {'lookback': 2})
        self.assertEqual(result['available_bars'], 1)
        self.assertEqual(result['status'], 'insufficient')
        self.assertIn('9 required', warning(result))

    def test_exact_threshold_and_undeclared_are_distinct(self):
        index = pd.date_range('2026-01-05T12:00Z', periods=9, freq='h')
        bars = pd.DataFrame({'availability_time': index + pd.Timedelta(hours=1)}, index=index)
        result = coverage(bars, self.request, self.spec, {'lookback': 2})
        self.assertEqual(result['status'], 'sufficient')
        self.assertIsNone(warning(result))
        self.assertEqual(coverage(bars, self.request, {}, {})['status'], 'undeclared')

    def test_preview_uses_session_data_and_resolves_each_sweep(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'bars.parquet'
            index = pd.date_range('2026-01-05T14:30Z', periods=12, freq='min', name='ts_event')
            pd.DataFrame({column: 100. for column in ['open', 'high', 'low', 'close']}, index=index).to_parquet(path)
            request = {**self.request, 'strategy': self.spec, 'parameters': {'lookback': 2},
                       'dataset': {'path': str(path), 'checksum': 'fixture', 'id': 'fixture', 'symbol': 'TEST'},
                       'session': 'new-york-rth', 'timeframe': '1m'}
            results = preview([request, {**request, 'parameters': {'lookback': 3}}, {**request, 'warmup_days': 0}])
            self.assertEqual([r['available_bars'] for r in results], [12, 12, 0])
            self.assertEqual([r['status'] for r in results], ['sufficient', 'insufficient', 'insufficient'])

    def test_metadata_rejects_invalid_history_rules(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'strategy.py'
            for rule in [{'parameter': 'missing'}, {'parameter': 'lookback', 'multiplier': True},
                         {'parameter': 'lookback', 'offset': -1}, {'parameter': 'lookback', 'surprise': 1}]:
                path.write_text('STRATEGY = ' + repr({**self.spec, 'warmup_bars': rule}))
                with self.assertRaises(ValueError):
                    metadata(path)


if __name__ == '__main__':
    unittest.main()
