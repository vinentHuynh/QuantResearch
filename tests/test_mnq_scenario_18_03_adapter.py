"""Hour-cell completeness and source-price parity for one MNQ grid row."""

import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from strategies.mnq_scenario_18_03 import Scenario1803, validate
from workbench.contract import discover, metadata
from workbench.events import simulate_events


ROOT = Path(__file__).resolve().parents[1]
REQUEST = {
    'start': '2026-01-02', 'end': '2026-01-07', 'capital': 10000.,
    'fee': 0., 'slippage': .5, 'warmup_days': 1, 'session': 'full-trading-day',
    'timeframe': '5m', 'dataset': {'symbol': 'MNQ', 'point_value': 2., 'tick_size': .25},
}


def hour(day, clock, count, first_open, last_close):
    index = pd.date_range(f'{day} {clock}:00', periods=count, freq='5min',
                          tz='America/New_York')
    return [(time, first_open + i / 10, last_close if i == count - 1 else first_open + i / 10)
            for i, time in enumerate(index)]


def bars(rows):
    index = pd.DatetimeIndex([r[0] for r in rows])
    opening = [float(r[1]) for r in rows]
    closing = [float(r[2]) for r in rows]
    return pd.DataFrame({
        'open': opening, 'high': [max(o, c) + 1 for o, c in zip(opening, closing)],
        'low': [min(o, c) - 1 for o, c in zip(opening, closing)],
        'close': closing, 'volume': 100., 'session_id': 'full-trading-day',
        'session_date': (index.tz_localize(None) + pd.Timedelta(hours=6)).strftime('%Y-%m-%d'),
        'availability_time': index + pd.Timedelta(minutes=5),
    }, index=index)


HISTORY = bars([
    (pd.Timestamp('2026-01-02 16:55', tz='America/New_York'), 99, 99),
    *hour('2026-01-04', '18', 12, 100, 101),
    *hour('2026-01-05', '02', 12, 104, 105),
    (pd.Timestamp('2026-01-05 03:00', tz='America/New_York'), 115, 115),
    (pd.Timestamp('2026-01-05 16:55', tz='America/New_York'), 109, 109),
    *hour('2026-01-05', '18', 5, 110, 111),   # too few entry-hour bars
    *hour('2026-01-06', '02', 12, 114, 115),
    (pd.Timestamp('2026-01-06 16:55', tz='America/New_York'), 119, 119),
    *hour('2026-01-06', '18', 12, 120, 121),
    *hour('2026-01-07', '02', 6, 124, 125),
])


class MnqScenario1803AdapterTests(unittest.TestCase):
    def test_discovery_links_grid_with_fixed_row_and_restricts_market(self):
        spec = metadata(ROOT / 'strategies/mnq_scenario_18_03.py', ROOT)
        self.assertEqual(spec['parameters'], {})
        self.assertEqual(spec['legacy_sources'], ['scripts/mnq/mnq_scenario_grid.py'])
        result = discover(ROOT)
        self.assertEqual(result['errors'], [])
        source = next(e for e in result['library']['entries']
                      if e['path'] == 'scripts/mnq/mnq_scenario_grid.py')
        self.assertEqual([a['id'] for a in source['adapters']], ['mnq-scenario-18-03'])
        with self.assertRaisesRegex(ValueError, 'MNQ'):
            validate({}, {**REQUEST, 'dataset': {**REQUEST['dataset'], 'symbol': 'NQ'}})

    def test_first_hour_open_last_hour_close_and_minimum_six_bars(self):
        equity, trades, _ = simulate_events(HISTORY, Scenario1803(HISTORY), REQUEST)
        self.assertEqual(len(trades), 2)
        self.assertEqual(trades.entry.tolist(), [100., 120.])
        self.assertEqual(trades.exit.tolist(), [105., 125.])
        self.assertEqual(trades.net_pnl.tolist(), [9.5, 9.5])
        self.assertEqual([pd.Timestamp(t).tz_convert('America/New_York').hour
                          for t in trades.exit_time], [3, 2])
        # The first exit is the 02:55 bar close at 03:00, not the 03:00 bar open (115).
        self.assertEqual(trades.exit.iloc[0], 105.)
        self.assertAlmostEqual(trades.net_pnl.sum(), equity.net_pnl.sum())

    def test_prices_and_cost_match_original_grid_row(self):
        path = ROOT / 'scripts/mnq/mnq_scenario_grid.py'
        spec = importlib.util.spec_from_file_location('mnq_source_scenario_grid', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with patch('pandas.read_parquet', return_value=HISTORY):
            opening, closing = module.load_cells('synthetic.parquet')
        expected = module.scenario_pnl(opening, closing, 18, 2, False)
        _, trades, _ = simulate_events(HISTORY, Scenario1803(HISTORY), REQUEST)
        self.assertEqual(len(expected), 2)
        self.assertEqual(expected.tolist(), trades.net_pnl.tolist())


if __name__ == '__main__':
    unittest.main()
