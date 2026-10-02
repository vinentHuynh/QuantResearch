"""Exact RTH-clock, source-price, and score-boundary checks for MNQ control."""

import importlib.util
import unittest
from pathlib import Path

import pandas as pd

from strategies.mnq_unconditional_overnight import UnconditionalOvernight, validate
from strategies.overnight_conditional_red_low import RedLowCloseOvernight
from workbench.contract import discover, metadata
from workbench.events import simulate_events


ROOT = Path(__file__).resolve().parents[1]
REQUEST = {
    'start': '2023-12-28', 'end': '2023-12-29', 'capital': 10000.,
    'fee': 0., 'slippage': .5, 'warmup_days': 1, 'session': 'full-trading-day',
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


class UnconditionalOvernightAdapterTests(unittest.TestCase):
    def test_discovery_and_market_scope(self):
        spec = metadata(ROOT / 'strategies/mnq_unconditional_overnight.py', ROOT)
        self.assertEqual(spec['parameters'], {})
        self.assertEqual(spec['legacy_sources'],
                         ['scripts/overnight/futures_overnight_backtest.py'])
        found = discover(ROOT)
        self.assertEqual(found['errors'], [])
        source = next(e for e in found['library']['entries']
                      if e['path'] == 'scripts/overnight/futures_overnight_backtest.py')
        self.assertIn('mnq-unconditional-overnight', [a['id'] for a in source['adapters']])
        with self.assertRaisesRegex(ValueError, 'MNQ'):
            validate({}, {**REQUEST, 'dataset': {**REQUEST['dataset'], 'symbol': 'ES'}})
        with self.assertRaisesRegex(ValueError, 'five-minute'):
            validate({}, {**REQUEST, 'timeframe': '1m'})

    def test_source_prices_and_one_tick_raw_contract_pnl(self):
        history = bars([
            ('2023-12-28 09:30', 100, 120, 90, 100),
            ('2023-12-28 15:55', 100, 120, 90, 104),
            ('2023-12-28 18:00', 105, 105, 105, 105),
            ('2023-12-29 09:25', 107, 107, 107, 107),
            ('2023-12-29 09:30', 109, 110, 108, 109),
            ('2023-12-29 15:55', 109, 111, 108, 110),
            ('2023-12-29 16:00', 111, 111, 111, 111),
        ])
        source_path = ROOT / 'scripts/overnight/futures_overnight_backtest.py'
        spec = importlib.util.spec_from_file_location('futures_overnight_source', source_path)
        source = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(source)
        sessions = source.sessions(history)
        self.assertEqual(sessions.close.iloc[0], 104.)
        self.assertEqual(sessions.open.iloc[1], 109.)

        equity, trades, _ = simulate_events(history, UnconditionalOvernight(history, REQUEST), REQUEST)
        self.assertEqual(len(trades), 1)
        self.assertEqual((trades.entry.iloc[0], trades.exit.iloc[0]),
                         (sessions.close.iloc[0], sessions.open.iloc[1]))
        entry_time = pd.Timestamp(trades.entry_time.iloc[0]).tz_convert('America/New_York')
        exit_time = pd.Timestamp(trades.exit_time.iloc[0]).tz_convert('America/New_York')
        self.assertEqual(entry_time.strftime('%Y-%m-%d %H:%M'), '2023-12-28 16:00')
        self.assertEqual(exit_time.strftime('%Y-%m-%d %H:%M'), '2023-12-29 09:30')
        self.assertEqual(trades.exit_reason.iloc[0], 'next-rth-open')
        self.assertEqual(trades.net_pnl.iloc[0], 9.5)  # 5 points * $2 - one $0.50 tick
        self.assertAlmostEqual(equity.net_pnl.sum(), trades.net_pnl.sum())

        _, conditional_trades, _ = simulate_events(
            history, RedLowCloseOvernight(history, REQUEST), REQUEST)
        self.assertEqual(conditional_trades[['entry', 'exit']].values.tolist(),
                         trades[['entry', 'exit']].values.tolist())
        self.assertEqual(conditional_trades.net_pnl.tolist(), trades.net_pnl.tolist())

    def test_unconditional_enters_on_red_low_close_conditional_skips(self):
        request = {**REQUEST, 'start': '2023-12-27'}
        history = bars([
            ('2023-12-27 09:30', 100, 120, 90, 100),
            ('2023-12-27 15:55', 100, 120, 90, 92),  # red and CLV 2/30
            ('2023-12-28 09:25', 93, 93, 93, 93),
            ('2023-12-28 09:30', 95, 95, 95, 95),
            ('2023-12-28 15:55', 95, 96, 94, 95),
            ('2023-12-29 09:25', 97, 97, 97, 97),
            ('2023-12-29 09:30', 98, 98, 98, 98),
        ])
        _, control, _ = simulate_events(history, UnconditionalOvernight(history, request), request)
        _, conditional, _ = simulate_events(
            history, RedLowCloseOvernight(history, request), request)
        self.assertEqual(control.entry.tolist(), [92., 95.])
        self.assertEqual(conditional.entry.tolist(), [95.])

    def test_missing_next_rth_open_is_technical_failure(self):
        history = bars([
            ('2023-12-28 09:30', 100, 100, 100, 100),
            ('2023-12-28 15:55', 100, 101, 99, 100),
            ('2023-12-29 09:25', 102, 102, 102, 102),
            ('2023-12-29 09:35', 103, 103, 103, 103),
        ])
        with self.assertRaisesRegex(ValueError, 'Missing next RTH 09:30'):
            simulate_events(history, UnconditionalOvernight(history, REQUEST), REQUEST)


if __name__ == '__main__':
    unittest.main()
