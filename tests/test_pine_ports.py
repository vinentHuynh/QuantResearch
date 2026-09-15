import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from workbench.contract import discover, metadata, resolve_parameters
from workbench.events import simulate_events
from strategies._pine_models import OvernightBlock, OvernightDrift, DailyTrend, IntradayORB, daily_features

ROOT = Path(__file__).resolve().parents[1]


def params(name, **changes):
    return resolve_parameters(metadata(ROOT / f'strategies/pine_{name}.py'), changes)


def bars(times, opens=None, closes=None, highs=None, lows=None):
    index = pd.DatetimeIndex(times).tz_localize('America/New_York')
    opening = np.array(opens if opens is not None else [100.] * len(index))
    closing = np.array(closes if closes is not None else opening)
    return pd.DataFrame({'open': opening, 'high': highs if highs is not None else np.maximum(opening, closing) + 1,
                         'low': lows if lows is not None else np.minimum(opening, closing) - 1, 'close': closing,
                         'volume': 100., 'session_id': 'full-trading-day',
                         'session_date': (index.tz_localize(None) + pd.Timedelta(hours=6)).strftime('%Y-%m-%d'),
                         'availability_time': index + pd.Timedelta(minutes=5)}, index=index)


REQUEST = {'start': '2026-01-01', 'end': '2026-12-31', 'capital': 1000., 'fee': 0., 'slippage': 0., 'warmup_days': 600,
           'dataset': {'point_value': 2., 'tick_size': .25}, 'session': 'full-trading-day'}


class Orders:
    def __init__(self, orders):
        self.orders = orders

    def on_close(self, i, bar, state):
        return self.orders.get(i) if state['tradable'] else None


class PinePortTests(unittest.TestCase):
    def test_audit_accounts_for_every_pine_and_reuses_snd(self):
        result = discover(ROOT)
        entries = {e['path']: e for e in result['library']['entries'] if e['path'].endswith('.pine')}
        self.assertEqual(len(entries), 17)
        self.assertEqual(sum(e['role'] == 'Pine strategy' for e in entries.values()), 5)
        self.assertEqual(entries['SND_phase6_strategy.pine']['status'], 'Existing Python engine')
        self.assertTrue(entries['SND_phase6_strategy.pine']['python_counterparts'])
        self.assertEqual(entries['pine/ib.pine']['status'], 'Indicator only')
        for entry in entries.values():
            if entry['role'] == 'Pine strategy' and entry['path'] != 'SND_phase6_strategy.pine':
                self.assertEqual(len(entry['adapters']), 1)

    def test_close_fill_never_earns_signal_bar_move(self):
        data = bars(['2026-01-05 09:30', '2026-01-05 09:35', '2026-01-05 09:40'], [90, 110, 112], [100, 111, 115])
        eq, trades, _ = simulate_events(data, Orders({0: {'target': 1}}), {**REQUEST, 'fee': 1., 'slippage': 1.})
        self.assertEqual(eq.gross_pnl.iloc[0], 0)
        self.assertEqual(trades.entry.iloc[0], 100)
        self.assertEqual(pd.Timestamp(trades.entry_bar_close.iloc[0]), data.availability_time.iloc[0])
        self.assertEqual(trades.net_pnl.sum(), 27.)  # 15 points * $2 less $3 round trip
        self.assertAlmostEqual(eq.net_pnl.sum(), trades.net_pnl.sum())

    def test_pending_block_order_fills_reopen_and_clock_exit(self):
        data = bars(['2026-01-05 16:55', '2026-01-05 18:00', '2026-01-06 05:55', '2026-01-06 06:00'], [100, 110, 120, 125])
        model = OvernightBlock(data, params('overnight_block'), REQUEST)
        _, trades, _ = simulate_events(data, model, REQUEST)
        self.assertEqual(trades.entry.iloc[0], 110)
        self.assertEqual(trades.exit.iloc[0], 125)
        self.assertEqual(pd.Timestamp(trades.entry_time.iloc[0]).hour, 18)
        self.assertEqual(pd.Timestamp(trades.entry_bar_close.iloc[0]), data.availability_time.iloc[1])
        self.assertEqual(pd.Timestamp(trades.exit_time.iloc[0]).hour, 6)
        # A test beginning after the window opened does not fabricate an entry.
        _, trades, _ = simulate_events(data, OvernightBlock(data, params('overnight_block'), REQUEST), {**REQUEST, 'start': '2026-01-05 23:00'})
        self.assertTrue(trades.empty)

    def test_block_pending_weekend_order_survives_dst_without_weekend_exposure(self):
        data = bars(['2026-03-06 16:55', '2026-03-08 18:00', '2026-03-09 05:55', '2026-03-09 06:00'], [100, 150, 155, 160])
        eq, trades, _ = simulate_events(data, OvernightBlock(data, params('overnight_block'), REQUEST), REQUEST)
        self.assertEqual(trades.entry.iloc[0], 150)
        self.assertEqual(trades.net_pnl.sum(), 20.)  # No profit from the $50 weekend gap.
        self.assertEqual(pd.Timestamp(trades.entry_time.iloc[0]).utcoffset().total_seconds(), -4 * 3600)
        self.assertEqual(eq.gross_pnl.sum(), 20.)

    def test_all_event_ports_are_prefix_causal_before_final_liquidation(self):
        times = []
        for date in pd.bdate_range('2026-02-02', periods=10):
            first = date - pd.Timedelta(days=1) + pd.Timedelta(hours=18)
            times.extend(pd.date_range(first, periods=276, freq='5min'))
        wave = np.arange(len(times))
        close = 100 + .003 * wave + np.sin(wave / 17) * 3
        data = bars(times, opens=close, closes=close + .2)
        for cls, name in [(OvernightBlock, 'overnight_block'), (DailyTrend, 'daily_tsmom'), (OvernightDrift, 'overnight_drift'), (IntradayORB, 'tsmom_orb')]:
            p = params(name)
            if 'sizing_mode' in p:
                p['sizing_mode'] = 'Fixed contracts'
            for key in ('fast_length', 'medium_length', 'slow_length', 'annual_length', 'volatility_length'):
                if key in p:
                    p[key] = 2
            part = data.iloc[:2200]
            full_eq, _, _ = simulate_events(data, cls(data, p, REQUEST), REQUEST)
            part_eq, _, _ = simulate_events(part, cls(part, p, REQUEST), REQUEST)
            with self.subTest(port=name):
                pd.testing.assert_frame_equal(full_eq.iloc[:2199], part_eq.iloc[:-1])

    def test_bracket_is_not_active_before_close_entry(self):
        data = bars(['2026-01-05 09:30', '2026-01-05 09:35'], highs=[150, 101], lows=[50, 94])
        eq, trades, _ = simulate_events(data, Orders({0: {'target': 1, 'bracket': (95, 110)}}), REQUEST)
        self.assertEqual(eq.gross_pnl.iloc[0], 0.)
        self.assertEqual(trades.exit.iloc[0], 95.)
        self.assertEqual(trades.exit_reason.iloc[0], 'stop')

    def test_minute_chronology_and_stop_first_ties(self):
        data = bars(['2026-01-05 09:30', '2026-01-05 09:35'], highs=[101, 111], lows=[99, 90])
        minute = bars(['2026-01-05 09:35', '2026-01-05 09:36'], highs=[111, 101], lows=[99, 90])
        req = {**REQUEST, 'fee': 1., 'slippage': 2.}
        _, trades, _ = simulate_events(data, Orders({0: {'target': 1, 'bracket': (95, 110)}}), req, minute)
        self.assertEqual(trades.exit.iloc[0], 110.)
        self.assertEqual(trades.cost.iloc[0], 3.)  # entry fee + $1 slip, limit fee only
        minute.iloc[0, minute.columns.get_loc('low')] = 94
        _, trades, _ = simulate_events(data, Orders({0: {'target': 1, 'bracket': (95, 110)}}), req, minute)
        self.assertEqual(trades.exit.iloc[0], 95.)
        self.assertEqual(trades.cost.iloc[0], 4.)

    def test_gap_stop_and_resizing_ledgers_reconcile(self):
        data = bars(['2026-01-05 09:30', '2026-01-05 09:35', '2026-01-05 09:40'], [100, 90, 95])
        eq, trades, _ = simulate_events(data, Orders({0: {'target': 1, 'bracket': (95, 110)}}), REQUEST)
        self.assertEqual(trades.exit.iloc[0], 90.)
        self.assertEqual(eq.net_pnl.sum(), -20.)
        eq, trades, _ = simulate_events(data, Orders({0: {'target': 1}, 1: {'target': 2}, 2: {'target': -1}}), {**REQUEST, 'fee': 1.})
        self.assertAlmostEqual(eq.net_pnl.sum(), trades.net_pnl.sum())
        self.assertAlmostEqual(eq.cost.sum(), trades.cost.sum())
        self.assertEqual(eq.cost.sum(), 6.)

    def test_completed_daily_publication_is_causal_and_lagged(self):
        times = []
        for date in pd.bdate_range('2026-02-01', periods=15):
            times.extend([date - pd.Timedelta(days=1) + pd.Timedelta(hours=18), date + pd.Timedelta(hours=16, minutes=55)])
        values = 100 + np.sin(np.arange(len(times))) * 10 + np.arange(len(times))
        data = bars(times, closes=values)
        p = params('daily_tsmom', fast_length=2, medium_length=3, slow_length=4, annual_length=5, volatility_length=5)
        whole = daily_features(data, p)
        prefix = daily_features(data.iloc[:-1], p)
        pd.testing.assert_frame_equal(whole.iloc[:-1], prefix)
        self.assertEqual(whole.daily_close.iloc[-1], data.close.iloc[-3])
        self.assertEqual(whole.daily_close.iloc[-2], data.close.iloc[-3])

    def test_daily_rebalance_and_equity_sizing_only_on_first_bar(self):
        data = bars(['2026-01-05 18:00', '2026-01-05 18:05', '2026-01-06 18:00'])
        p = params('daily_tsmom', sizing_mode='Fixed contracts', contracts=2)
        model = DailyTrend(data, p, REQUEST)
        model.known.loc[:, 'exposure'] = [1., -1., -1.]
        state = {'position': 0, 'equity': 1000., 'tradable': True}
        self.assertEqual(model.on_close(0, data.iloc[0], state)['target'], 2)
        self.assertIsNone(model.on_close(1, data.iloc[1], state))
        self.assertEqual(model.on_close(2, data.iloc[2], state)['target'], -2)
        model.p['sizing_mode'] = 'Vol-targeted'
        self.assertEqual(model.on_close(0, data.iloc[0], state)['target'], 5)
        self.assertEqual(model.on_close(0, data.iloc[0], {**state, 'equity': 2000.})['target'], 10)

    def test_drift_fills_first_outside_and_first_rth_bar_closes(self):
        data = bars(['2026-01-05 09:30', '2026-01-05 15:55', '2026-01-05 16:00', '2026-01-06 09:30'], [100, 101, 103, 110], [101, 102, 104, 111])
        p = params('overnight_drift', sizing_mode='Fixed contracts')
        _, trades, _ = simulate_events(data, OvernightDrift(data, p, REQUEST), REQUEST)
        self.assertEqual(trades.entry.iloc[0], 104.)
        self.assertEqual(pd.Timestamp(trades.entry_time.iloc[0]).strftime('%H:%M'), '16:05')
        self.assertEqual(trades.exit.iloc[0], 111.)
        self.assertEqual(pd.Timestamp(trades.exit_time.iloc[0]).strftime('%H:%M'), '09:35')

    def test_orb_risk_rejection_consumes_attempt_and_flatten_is_1545_bar_close(self):
        data = bars(['2026-01-05 09:30', '2026-01-05 09:35', '2026-01-05 09:40', '2026-01-05 09:45', '2026-01-05 09:50', '2026-01-05 15:45'], closes=[100, 100, 100, 120, 102, 103])
        p = params('tsmom_orb', risk_budget=1)
        model = IntradayORB(data, p, REQUEST)
        model.known.loc[:, 'score'] = 1.
        state = {'position': 0, 'equity': 1000., 'tradable': True}
        for i in range(4):
            self.assertIsNone(model.on_close(i, data.iloc[i], state))
        self.assertTrue(model.attempted)
        model.p['risk_budget'] = 10000
        self.assertIsNone(model.on_close(4, data.iloc[4], state))
        self.assertEqual(model.on_close(5, data.iloc[5], {**state, 'position': 1})['target'], 0)


if __name__ == '__main__':
    unittest.main()
