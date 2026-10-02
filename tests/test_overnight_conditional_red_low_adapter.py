"""Signal and fill checks for the fixed prior-RTH conditional branch."""

import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from strategies.overnight_conditional_red_low import RedLowCloseOvernight, validate
from workbench.contract import discover, metadata
from workbench.events import simulate_events


ROOT = Path(__file__).resolve().parents[1]
REQUEST = {
    'start': '2026-01-02', 'end': '2026-01-08', 'capital': 10000.,
    'fee': 0., 'slippage': .5, 'warmup_days': 1, 'session': 'full-trading-day',
    'timeframe': '5m', 'dataset': {'symbol': 'MNQ', 'point_value': 2., 'tick_size': .25},
}


def bars(rows):
    index = pd.DatetimeIndex([r[0] for r in rows]).tz_localize('America/New_York')
    opening, high, low, close = ([float(r[i]) for r in rows] for i in range(1, 5))
    return pd.DataFrame({
        'open': opening, 'high': high, 'low': low, 'close': close,
        'volume': 100., 'session_id': 'full-trading-day',
        'session_date': (index.tz_localize(None) + pd.Timedelta(hours=6)).strftime('%Y-%m-%d'),
        'availability_time': index + pd.Timedelta(minutes=5),
    }, index=index)


def day(date, opening, closing, high=120, low=100):
    return [(f'{date} 09:25', opening, opening + 1, opening - 1, opening),
            (f'{date} 09:30', opening, high, low, opening),
            (f'{date} 15:55', opening, high, low, closing)]


HISTORY = bars([
    *day('2026-01-02', 100, 104, 110, 90),  # green: Friday would enter
    ('2026-01-04 18:00', 105, 106, 104, 105),
    *day('2026-01-05', 100, 105, 110, 90),  # green: enter at 105
    *day('2026-01-06', 114, 110, 120, 100), # red, mid-close: enter at 110
    *day('2026-01-07', 112, 104, 120, 100), # red, low-close: flat
    *day('2026-01-08', 106, 106, 120, 100),
])


class ConditionalOvernightAdapterTests(unittest.TestCase):
    def test_discovery_links_fixed_branch_and_enforces_mnq(self):
        spec = metadata(ROOT / 'strategies/overnight_conditional_red_low.py', ROOT)
        self.assertEqual(spec['parameters'], {})
        self.assertEqual(spec['legacy_sources'],
                         ['scripts/overnight/overnight_conditional_backtest.py'])
        found = discover(ROOT)
        self.assertEqual(found['errors'], [])
        source = next(e for e in found['library']['entries']
                      if e['path'] == 'scripts/overnight/overnight_conditional_backtest.py')
        self.assertEqual([a['id'] for a in source['adapters']],
                         ['overnight-conditional-red-low'])
        with self.assertRaisesRegex(ValueError, 'MNQ'):
            validate({}, {**REQUEST, 'dataset': {**REQUEST['dataset'], 'symbol': 'NQ'}})

    def test_source_rule_and_raw_close_to_open_fills(self):
        source_path = ROOT / 'scripts/overnight/overnight_conditional_backtest.py'
        spec = importlib.util.spec_from_file_location('overnight_conditional_source', source_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with patch('pandas.read_parquet', return_value=HISTORY.copy()):
            f = module.features('MNQ')
        direction = pd.Series(
            (~((f.green == False) & (f['loc'] < .33))).astype(int), index=f.index)
        self.assertEqual(direction.loc[pd.Timestamp('2026-01-05', tz='America/New_York')], 1)
        self.assertEqual(direction.loc[pd.Timestamp('2026-01-06', tz='America/New_York')], 1)
        self.assertEqual(direction.loc[pd.Timestamp('2026-01-07', tz='America/New_York')], 1)
        self.assertEqual(direction.loc[pd.Timestamp('2026-01-08', tz='America/New_York')], 0)

        equity, trades, _ = simulate_events(HISTORY, RedLowCloseOvernight(HISTORY, REQUEST), REQUEST)
        self.assertEqual(len(trades), 3)
        self.assertEqual(trades.entry.tolist(), [104., 105., 110.])
        self.assertEqual(trades.exit.tolist(), [100., 114., 112.])
        self.assertEqual(trades.net_pnl.tolist(), [-8.5, 17.5, 3.5])
        self.assertAlmostEqual(trades.net_pnl.sum(), equity.net_pnl.sum())

    def test_zero_range_stays_long_and_missing_rth_open_blocks(self):
        zero = bars([
            *day('2026-01-05', 100, 100, 100, 100),
            *day('2026-01-06', 101, 101),
        ])
        zero_request = {**REQUEST, 'start': '2026-01-05', 'end': '2026-01-06'}
        _, trades, _ = simulate_events(zero, RedLowCloseOvernight(zero, zero_request),
                                       zero_request)
        self.assertEqual(len(trades), 1)
        self.assertEqual((trades.entry.iloc[0], trades.exit.iloc[0]), (100., 101.))

        missing = bars([
            *day('2026-01-05', 100, 105, 110, 90),
            ('2026-01-06 09:25', 107, 108, 106, 107),
            ('2026-01-06 09:35', 108, 109, 107, 108),
        ])
        with self.assertRaisesRegex(ValueError, 'Missing next RTH 09:30'):
            simulate_events(missing, RedLowCloseOvernight(missing, REQUEST), REQUEST)


if __name__ == '__main__':
    unittest.main()
