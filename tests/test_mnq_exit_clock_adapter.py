"""Source-ledger parity and missing-quote behavior for the three frozen clocks."""

import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from strategies.mnq_exit_clock import ExitClock, create_strategy, validate
from workbench.contract import metadata
from workbench.events import simulate_events


ROOT = Path(__file__).resolve().parents[1]
REQUEST = {
    'start': '2026-01-02', 'end': '2026-01-05', 'capital': 10000.,
    'fee': 0., 'slippage': .5, 'warmup_days': 1, 'session': 'full-trading-day',
    'timeframe': '5m', 'dataset': {'symbol': 'MNQ', 'point_value': 2., 'tick_size': .25},
}


def bars(rows):
    index = pd.DatetimeIndex([row[0] for row in rows]).tz_localize('America/New_York')
    opening = [float(row[1]) for row in rows]
    return pd.DataFrame({
        'open': opening, 'high': [price + 1 for price in opening],
        'low': [price - 1 for price in opening], 'close': opening,
        'volume': 100., 'session_id': 'full-trading-day',
        'session_date': (index.tz_localize(None) + pd.Timedelta(hours=6)).strftime('%Y-%m-%d'),
        'availability_time': index + pd.Timedelta(minutes=5),
    }, index=index)


NIGHT = bars([
    ('2026-01-02 16:55', 99), ('2026-01-04 18:00', 100),
    ('2026-01-04 23:55', 101), ('2026-01-05 00:00', 103),
    ('2026-01-05 00:55', 104), ('2026-01-05 01:00', 105),
    ('2026-01-05 05:55', 106), ('2026-01-05 06:00', 107),
])


class ExitClockAdapterTests(unittest.TestCase):
    def test_three_headline_arms_match_original_boundary_prices_and_cost(self):
        source_path = ROOT / 'scripts/mnq/mnq_exit_time_backtest.py'
        spec = importlib.util.spec_from_file_location('mnq_exit_source', source_path)
        source = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(source)
        with patch('pandas.read_parquet', return_value=NIGHT):
            original = source.sessions('synthetic.parquet', [6, 7, 12])
        for hold, clock in ((6, '00:00'), (7, '01:00'), (12, '06:00')):
            with self.subTest(clock=clock):
                _, trades, _ = simulate_events(
                    NIGHT, create_strategy(NIGHT, {'exit_clock': clock}, REQUEST), REQUEST)
                self.assertEqual(len(trades), 1)
                self.assertEqual(trades.entry.tolist(), original.entry.tolist())
                self.assertEqual(trades.exit.tolist(), original[f'exit_{hold}'].tolist())
                self.assertEqual(trades.net_pnl.tolist(), source.pnl(original, hold, None).tolist())

    def test_missing_exit_quote_fails_instead_of_filling_late(self):
        missing = bars([
            ('2026-01-02 16:55', 99), ('2026-01-04 18:00', 100),
            ('2026-01-05 05:55', 102), ('2026-01-05 06:35', 103),
        ])
        with self.assertRaisesRegex(ValueError, 'Missing exit quote'):
            simulate_events(missing, ExitClock(missing, '06:00'), REQUEST)

    def test_metadata_and_market_restriction(self):
        spec = metadata(ROOT / 'strategies/mnq_exit_clock.py', ROOT)
        self.assertEqual(spec['legacy_sources'], ['scripts/mnq/mnq_exit_time_backtest.py'])
        self.assertEqual(spec['parameters']['exit_clock']['choices'], ['00:00', '01:00', '06:00'])
        with self.assertRaisesRegex(ValueError, 'MNQ'):
            validate({'exit_clock': '06:00'},
                     {**REQUEST, 'dataset': {**REQUEST['dataset'], 'symbol': 'NQ'}})


if __name__ == '__main__':
    unittest.main()
