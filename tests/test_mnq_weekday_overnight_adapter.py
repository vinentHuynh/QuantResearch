"""Exact clock, weekday, and source-ledger checks for the fixed MNQ arm."""

import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from strategies.mnq_weekday_overnight import FixedWeekdayOvernight, create_strategy, validate
from workbench.contract import discover, metadata
from workbench.events import simulate_events


ROOT = Path(__file__).resolve().parents[1]
REQUEST = {
    'start': '2026-01-01', 'end': '2026-01-09', 'capital': 10000.,
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


WEEK = bars([
    ('2026-01-02 16:55', 99),
    ('2026-01-04 18:00', 100), ('2026-01-05 05:55', 103), ('2026-01-05 06:00', 105),
    ('2026-01-05 16:55', 110),
    ('2026-01-05 18:00', 111), ('2026-01-06 05:55', 113), ('2026-01-06 06:00', 115),
    ('2026-01-06 16:55', 120),
    ('2026-01-06 18:00', 121), ('2026-01-07 05:55', 125), ('2026-01-07 06:00', 126),
    ('2026-01-07 16:55', 130),
    ('2026-01-07 18:00', 131), ('2026-01-08 05:55', 135), ('2026-01-08 06:00', 136),
    ('2026-01-08 16:55', 140),
    ('2026-01-08 18:00', 141), ('2026-01-09 05:55', 143), ('2026-01-09 06:00', 145),
])


class MnqWeekdayOvernightAdapterTests(unittest.TestCase):
    def test_discovery_links_exact_source_and_restricts_market(self):
        spec = metadata(ROOT / 'strategies/mnq_weekday_overnight.py', ROOT)
        self.assertEqual(spec['legacy_sources'], ['scripts/mnq/mnq_weekday_backtest.py'])
        self.assertEqual(spec['parameters'], {})
        result = discover(ROOT)
        self.assertEqual(result['errors'], [])
        source = next(entry for entry in result['library']['entries']
                      if entry['path'] == 'scripts/mnq/mnq_weekday_backtest.py')
        self.assertEqual([a['id'] for a in source['adapters']], ['mnq-weekday-overnight'])
        with self.assertRaisesRegex(ValueError, 'MNQ'):
            validate({}, {**REQUEST, 'dataset': {**REQUEST['dataset'], 'symbol': 'NQ'}})
        with self.assertRaisesRegex(ValueError, 'five-minute'):
            validate({}, {**REQUEST, 'session': 'globex-overnight'})

    def test_only_source_weekdays_trade_at_exact_bar_opens(self):
        equity, trades, _ = simulate_events(WEEK, create_strategy(WEEK, {}, REQUEST), REQUEST)
        self.assertEqual(len(trades), 3)
        self.assertEqual(trades.entry.tolist(), [100., 121., 131.])
        self.assertEqual(trades.exit.tolist(), [105., 126., 136.])
        self.assertEqual([pd.Timestamp(t).tz_convert('America/New_York').weekday()
                          for t in trades.entry_time], [6, 1, 2])
        self.assertEqual([pd.Timestamp(t).tz_convert('America/New_York').hour
                          for t in trades.exit_time], [6, 6, 6])
        self.assertEqual(trades.net_pnl.tolist(), [9.5, 9.5, 9.5])
        self.assertAlmostEqual(trades.net_pnl.sum(), equity.net_pnl.sum())

    def test_matches_original_fixed_arm_prices_and_one_tick_cost(self):
        path = ROOT / 'scripts/mnq/mnq_exit_time_backtest.py'
        spec = importlib.util.spec_from_file_location('mnq_source_exit_time', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with patch('pandas.read_parquet', return_value=WEEK):
            source = module.sessions('synthetic.parquet', [12])
        source = source[source.index.dayofweek.isin((6, 1, 2))]
        _, trades, _ = simulate_events(WEEK, FixedWeekdayOvernight(WEEK), REQUEST)
        self.assertEqual(source.entry.tolist(), trades.entry.tolist())
        self.assertEqual(source.exit_12.tolist(), trades.exit.tolist())
        self.assertEqual(module.pnl(source, 12, None).tolist(), trades.net_pnl.tolist())

    def test_dst_weekend_entry_uses_sunday_not_friday_date(self):
        data = bars([
            ('2026-03-06 16:55', 100), ('2026-03-08 18:00', 150),
            ('2026-03-09 05:55', 154), ('2026-03-09 06:00', 155),
        ])
        _, trades, _ = simulate_events(data, FixedWeekdayOvernight(data),
                                       {**REQUEST, 'start': '2026-03-06', 'end': '2026-03-09'})
        self.assertEqual(len(trades), 1)
        self.assertEqual((trades.entry.iloc[0], trades.exit.iloc[0]), (150., 155.))
        self.assertEqual(pd.Timestamp(trades.entry_time.iloc[0]).utcoffset().total_seconds(),
                         -4 * 3600)

    def test_missing_exit_quote_is_data_blocker_not_late_fill(self):
        data = bars([
            ('2026-01-02 16:55', 100), ('2026-01-04 18:00', 101),
            ('2026-01-05 05:55', 102), ('2026-01-05 06:35', 103),
        ])
        with self.assertRaisesRegex(ValueError, 'Missing 06:00–06:30'):
            simulate_events(data, FixedWeekdayOvernight(data), REQUEST)


if __name__ == '__main__':
    unittest.main()
