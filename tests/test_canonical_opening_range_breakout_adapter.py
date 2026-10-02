"""Focused parity and data-quality tests for the canonical ORB event adapter."""

from __future__ import annotations

import unittest
from pathlib import Path

import pandas as pd

from strategy_engine.strategies.opening_range_breakout import (
    OpeningRangeBreakoutConfig,
    run as source_run,
)
from strategies.canonical_opening_range_breakout import STRATEGY, create_strategy
from workbench.contract import metadata, resolve_parameters
from workbench.events import simulate_events


ROOT = Path(__file__).resolve().parents[1]


def fixture_day(day: str, *, breakout: bool, close_time: str = '15:59',
                collision: bool = False, missing_opening: bool = False) -> pd.DataFrame:
    start = pd.Timestamp(day + ' 09:30', tz='America/New_York')
    opening = list(pd.date_range(start, periods=15, freq='1min'))
    if missing_opening:
        opening.pop(6)
    times = [*opening, start + pd.Timedelta(minutes=15),
             start + pd.Timedelta(minutes=16),
             pd.Timestamp(day + ' ' + close_time, tz='America/New_York')]
    rows = []
    for index, timestamp in enumerate(times):
        if index < len(opening):
            rows.append((100., 101., 99., 100.))
        elif index == len(opening):
            rows.append((100., 101.5 if breakout else 101., 100.,
                         101.25 if breakout else 100.))
        elif index == len(opening) + 1:
            if breakout:
                rows.append((101.25, 106. if collision else 101.5,
                             98. if collision else 100.5, 101.25))
            else:
                rows.append((100., 101., 99., 100.))
        else:
            rows.append((101.25 if breakout else 100., 102. if breakout else 101.,
                         100., 102. if breakout else 100.))
    bars = pd.DataFrame(rows, columns=['open', 'high', 'low', 'close'],
                        index=pd.DatetimeIndex(times, name='event_time'))
    bars['availability_time'] = bars.index + pd.Timedelta(minutes=1)
    bars['session_id'] = 'new-york-rth'
    bars['session_date'] = day
    return bars


def request(start='2024-06-17', end='2024-06-18'):
    return {
        'start': start, 'end': end, 'session': 'new-york-rth', 'timeframe': '1m',
        'dataset': {'symbol': 'NQ', 'tick_size': 0.25, 'point_value': 2.0},
        'capital': 100_000., 'fee': 0., 'slippage': 0., 'delay_bars': 0,
    }


def replay(bars: pd.DataFrame, req=None):
    req = req or request()
    parameters = resolve_parameters(STRATEGY, {})
    model = create_strategy(bars, parameters, req)
    return simulate_events(bars, model, req, return_signals=True)


class CanonicalOpeningRangeBreakoutAdapterTests(unittest.TestCase):
    def test_metadata_declares_complete_execution_sources(self):
        spec = metadata(ROOT / 'strategies/canonical_opening_range_breakout.py', ROOT)
        self.assertEqual(spec['id'], 'canonical-opening-range-breakout')
        self.assertEqual(spec['schema_version'], 2)
        self.assertIn('strategies/_cme_index_calendar.py', spec['source_files'])

    def test_close_break_and_scheduled_exit_match_source_without_costs(self):
        bars = pd.concat([
            fixture_day('2024-06-17', breakout=False),
            fixture_day('2024-06-18', breakout=True),
        ])
        source_trades, _ = source_run(
            bars, symbol='NQ', tick_size=0.25, point_value=2.,
            config=OpeningRangeBreakoutConfig(cost_ticks=0.),
        )
        equity, trades, positions, signals = replay(bars)
        self.assertEqual(len(source_trades), 1)
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades.iloc[0].entry, source_trades.iloc[0].entry)
        self.assertEqual(trades.iloc[0].exit, source_trades.iloc[0].exit)
        self.assertEqual(trades.iloc[0].exit_reason, 'scheduled-session-close')
        self.assertAlmostEqual(trades.iloc[0].net_pnl, source_trades.iloc[0].net_pnl)
        self.assertAlmostEqual(trades.net_pnl.sum(), equity.net_pnl.sum())
        self.assertEqual(int(positions.iloc[-1].contracts), 0)
        self.assertIn('canonical-opening-range-break', set(signals.reason))

    def test_stop_first_collision_matches_source(self):
        bars = fixture_day('2024-06-18', breakout=True, collision=True)
        source_trades, _ = source_run(
            bars, symbol='NQ', tick_size=0.25, point_value=2.,
            config=OpeningRangeBreakoutConfig(cost_ticks=0.),
        )
        _, trades, _, _ = replay(bars)
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades.iloc[0].exit_reason, 'stop')
        self.assertEqual(trades.iloc[0].exit, source_trades.iloc[0].exit)
        self.assertAlmostEqual(trades.iloc[0].net_pnl, source_trades.iloc[0].net_pnl)

    def test_declared_early_close_exits_at_quote(self):
        bars = fixture_day('2024-07-03', breakout=True, close_time='13:14')
        _, trades, _, _ = replay(bars, request('2024-07-03', '2024-07-03'))
        self.assertEqual(len(trades), 1)
        self.assertEqual(pd.Timestamp(trades.iloc[0].exit_time).tz_convert('America/New_York').strftime('%H:%M'), '13:15')

    def test_incomplete_opening_window_is_suppressed(self):
        bars = fixture_day('2024-06-18', breakout=True, missing_opening=True)
        _, trades, _, _ = replay(bars)
        self.assertEqual(len(trades), 0)

    def test_missing_held_close_quote_fails(self):
        opened = fixture_day('2024-06-18', breakout=True).iloc[:-1]
        next_day = fixture_day('2024-06-20', breakout=False).iloc[:1]
        bars = pd.concat([opened, next_day])
        with self.assertRaisesRegex(ValueError, 'Missing scheduled RTH exit quote'):
            replay(bars, request('2024-06-18', '2024-06-20'))

    def test_truncated_last_day_does_not_end_of_test_liquidate_early(self):
        bars = fixture_day('2024-06-18', breakout=True).iloc[:-1]
        with self.assertRaisesRegex(ValueError, 'Data ends before the scheduled RTH exit quote'):
            replay(bars, request('2024-06-18', '2024-06-18'))

    def test_rejects_unsupported_market_and_session(self):
        bars = fixture_day('2024-06-18', breakout=True)
        for key, value in [('session', 'full-trading-day'),
                           ('timeframe', '5m'), ('dataset', {'symbol': 'CL', 'tick_size': 0.01})]:
            bad = request()
            bad[key] = value
            with self.assertRaises(ValueError):
                create_strategy(bars, resolve_parameters(STRATEGY, {}), bad)


if __name__ == '__main__':
    unittest.main()
