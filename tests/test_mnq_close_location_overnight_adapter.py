"""Causal RTH feature and price-ledger checks for the MNQ CLV≤0.8 arm."""

import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from strategies.mnq_close_location_overnight import CloseLocationOvernight, validate
from workbench.contract import discover, metadata
from workbench.events import simulate_events


ROOT = Path(__file__).resolve().parents[1]
REQUEST = {
    'start': '2026-01-02', 'end': '2026-01-08', 'capital': 10000.,
    'fee': 0., 'slippage': .5, 'warmup_days': 10, 'session': 'full-trading-day',
    'timeframe': '5m', 'dataset': {'symbol': 'MNQ', 'point_value': 2., 'tick_size': .25},
}


def bars(rows):
    index = pd.DatetimeIndex([r[0] for r in rows]).tz_localize('America/New_York')
    return pd.DataFrame({
        'open': [float(r[1]) for r in rows],
        'high': [float(r[2]) for r in rows],
        'low': [float(r[3]) for r in rows],
        'close': [float(r[4]) for r in rows],
        'volume': 100., 'session_id': 'full-trading-day',
        'session_date': (index.tz_localize(None) + pd.Timedelta(hours=6)).strftime('%Y-%m-%d'),
        'availability_time': index + pd.Timedelta(minutes=5),
    }, index=index)


def rth(day, final):
    return [(f'{day} 09:30', 100, 110, 90, 100),
            (f'{day} 15:55', 100, 110, 90, final),
            (f'{day} 16:55', final, final + 1, final - 1, final)]


def night(day, entry, following, exit_price):
    return [(f'{day} 18:00', entry, entry + 1, entry - 1, entry),
            (f'{following} 05:55', exit_price, exit_price + 1, exit_price - 1, exit_price),
            (f'{following} 06:00', exit_price, exit_price + 1, exit_price - 1, exit_price)]


HISTORY = bars([
    *rth('2026-01-02', 100),
    *night('2026-01-04', 199, '2026-01-05', 204),  # Sunday has no same-day RTH
    *rth('2026-01-05', 106),                       # CLV = 0.8 (included)
    *night('2026-01-05', 200, '2026-01-06', 205),
    *rth('2026-01-06', 108),                       # CLV = 0.9 (excluded)
    *night('2026-01-06', 210, '2026-01-07', 215),
    *rth('2026-01-07', 96),                        # CLV = 0.3 (included)
    *night('2026-01-07', 220, '2026-01-08', 225),
])


class MnqCloseLocationAdapterTests(unittest.TestCase):
    def test_discovery_links_narrow_source_and_enforces_mnq_five_minute(self):
        spec = metadata(ROOT / 'strategies/mnq_close_location_overnight.py', ROOT)
        self.assertEqual(spec['parameters'], {})
        self.assertEqual(spec['legacy_sources'], ['scripts/mnq/mnq_close_location_backtest.py'])
        found = discover(ROOT)
        self.assertEqual(found['errors'], [])
        source = next(e for e in found['library']['entries']
                      if e['path'] == 'scripts/mnq/mnq_close_location_backtest.py')
        self.assertEqual([a['id'] for a in source['adapters']], ['mnq-close-location-overnight'])
        with self.assertRaisesRegex(ValueError, 'MNQ'):
            validate({}, {**REQUEST, 'dataset': {**REQUEST['dataset'], 'symbol': 'NQ'}})
        with self.assertRaisesRegex(ValueError, 'five-minute'):
            validate({}, {**REQUEST, 'timeframe': '15m'})

    def test_fixed_threshold_accepts_boundary_and_skips_high_close_and_sunday(self):
        equity, trades, _ = simulate_events(HISTORY, CloseLocationOvernight(HISTORY), REQUEST)
        self.assertEqual(len(trades), 2)
        self.assertEqual(trades.entry.tolist(), [200., 220.])
        self.assertEqual(trades.exit.tolist(), [205., 225.])
        self.assertEqual(trades.net_pnl.tolist(), [9.5, 9.5])
        self.assertAlmostEqual(trades.net_pnl.sum(), equity.net_pnl.sum())

    def test_prices_and_nominal_cost_match_original_fixed_arm(self):
        path = ROOT / 'scripts/mnq/mnq_close_location_backtest.py'
        spec = importlib.util.spec_from_file_location('mnq_source_close_location', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with patch('pandas.read_parquet', return_value=HISTORY):
            source = module.build('synthetic.parquet', None)
        source = source[source.clv <= .8]
        _, trades, _ = simulate_events(HISTORY, CloseLocationOvernight(HISTORY), REQUEST)
        self.assertEqual(source.entry.tolist(), trades.entry.tolist())
        self.assertEqual(source.pnl.tolist(), trades.net_pnl.tolist())

    def test_same_day_rth_is_required_and_missing_exit_blocks(self):
        data = bars([
            *rth('2026-01-02', 100),
            *night('2026-01-04', 199, '2026-01-05', 204),
        ])
        _, trades, _ = simulate_events(data, CloseLocationOvernight(data), REQUEST)
        self.assertTrue(trades.empty)

        broken = bars([
            *rth('2026-01-02', 100),
            *rth('2026-01-05', 96),
            ('2026-01-05 18:00', 200, 201, 199, 200),
            ('2026-01-06 05:55', 201, 202, 200, 201),
            ('2026-01-06 06:35', 202, 203, 201, 202),
        ])
        with self.assertRaisesRegex(ValueError, 'Missing 06:00–06:30'):
            simulate_events(broken, CloseLocationOvernight(broken), REQUEST)


if __name__ == '__main__':
    unittest.main()
