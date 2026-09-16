from pathlib import Path
from types import SimpleNamespace
import unittest

import numpy as np
import pandas as pd

from strategies.snd import STRATEGY, validate
from strategies._snd_model import SND, slot_rvol
from workbench.contract import discover
from workbench.events import simulate_events

ROOT = Path(__file__).resolve().parents[1]
REQUEST = {'start': '2026-01-01', 'end': '2026-01-31', 'capital': 100000.,
           'fee': 1.25, 'slippage': 1., 'dataset': {'point_value': 2., 'tick_size': .25},
           'session': 'full-trading-day', 'timeframe': '1m', 'warmup_days': 60}


def bars(count=10):
    index = pd.date_range('2026-01-05 14:00', periods=count, freq='min', tz='UTC')
    return pd.DataFrame({'open': 100., 'high': 101., 'low': 99., 'close': 100.,
                         'volume': 100., 'availability_time': index + pd.Timedelta(minutes=1)}, index=index)


def zone(identity=1, **changes):
    return SimpleNamespace(**{**dict(zone_id=identity, direction='long', timeframe='1h', rank=60,
        proximal=100., distal=98., width=2., activation_pos=0, ready=True,
        test_count=0, last_test_pos=-1, physical_touch_count=0, touching_previous_bar=False), **changes})


class SNDAdapterTests(unittest.TestCase):
    def test_discovery_and_validation(self):
        catalog = discover(ROOT)
        self.assertEqual(catalog['errors'], [])
        self.assertIn('snd', [s['id'] for s in catalog['strategies']])
        for path in STRATEGY['legacy_sources'] + STRATEGY['pine_sources']:
            entry = next(e for e in catalog['library']['entries'] if e['path'] == path)
            self.assertIn('snd', [s['id'] for s in entry['adapters']])
        for changes in ({'timeframe': '5m'}, {'session': 'new-york-rth'}, {'warmup_days': 0}, {'delay_bars': 1}):
            with self.assertRaises(ValueError):
                validate({'variant': 'phase7_prior_5m'}, {**REQUEST, **changes})

    def test_next_open_stop_blocks_exit_bar_reentry_and_reconciles(self):
        data = bars(5)
        data.loc[data.index[1], ['open', 'low']] = [95., 94.]
        model = SND(data, {'variant': 'phase6', 'contracts': 2}, REQUEST)
        first, second = zone(), zone(2, proximal=96., distal=90., width=6., activation_pos=1)
        model.events = {0: [first], 1: [second]}
        equity, trades, _ = simulate_events(data, model, REQUEST, execution_bars=data)
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades.iloc[0].entry, 95.)
        self.assertEqual(trades.iloc[0]['exit'], 95.)
        self.assertEqual(trades.iloc[0].exit_reason, 'stop')
        self.assertEqual(second.test_count, 0)
        self.assertAlmostEqual(trades.net_pnl.sum(), -7.)
        self.assertAlmostEqual(equity.equity.iloc[-1] - REQUEST['capital'], trades.net_pnl.sum())

    def test_first_touch_rvol_is_frozen_while_busy(self):
        data = bars()
        model = SND(data, {'variant': 'phase7_prior_1m', 'contracts': 1}, REQUEST)
        z = zone()
        model.events = {0: [z]}
        model.rvol = np.array([.8] + [2.] * 9)
        busy = {'position': 1, 'position_at_open': 1, 'tradable': True}
        self.assertIsNone(model.on_close(0, data.iloc[0], busy))
        order = model.on_close(1, data.iloc[1], {**busy, 'position': 0, 'position_at_open': 0})
        self.assertEqual(order['target'], 1)
        self.assertEqual(model.first_rvol[z.zone_id], .8)
        self.assertEqual(z.physical_touch_count, 1)

    def test_wick_invalidation_precedes_touch_and_warmup_consumes_no_orders(self):
        data = bars()
        model = SND(data, {'variant': 'phase6', 'contracts': 1}, REQUEST)
        broken, valid = zone(distal=99.5), zone(2)
        model.events = {0: [broken, valid]}
        self.assertIsNone(model.on_close(0, data.iloc[0], {'position': 0, 'tradable': False}))
        self.assertNotIn(broken, model.longs)
        self.assertEqual(broken.physical_touch_count, 0)
        self.assertEqual(valid.test_count, 1)

    def test_slot_rvol_uses_only_prior_observations(self):
        index = pd.date_range('2025-12-01 15:00', periods=25, freq='D', tz='UTC')
        data = pd.DataFrame({'volume': [100.] * 24 + [1000.]}, index=index)
        values = slot_rvol(data, 1)
        self.assertTrue(values.iloc[:10].isna().all())
        self.assertEqual(values.iloc[10], 1.)
        self.assertEqual(values.iloc[-1], 10.)

    def test_future_bars_cannot_change_completed_zones_or_decisions(self):
        data = bars(480)
        wave = 100 + np.sin(np.arange(480) / 23) * 5
        data['open'], data['close'] = wave, wave + np.cos(np.arange(480) / 23)
        data['high'] = data[['open', 'close']].max(axis=1) + .1
        data['low'] = data[['open', 'close']].min(axis=1) - .1
        changed = data.copy()
        changed.loc[changed.index[300]:, ['open', 'close', 'high', 'low']] += 500
        for variant in STRATEGY['parameters']['variant']['choices']:
            left = SND(data, {'variant': variant, 'contracts': 1}, REQUEST)
            right = SND(changed, {'variant': variant, 'contracts': 1}, REQUEST)
            self.assertTrue(sum(len(v) for k, v in left.events.items() if k < 300) > 0)
            for i in range(300):
                state = {'position': 0, 'tradable': True}
                self.assertEqual(left.on_close(i, data.iloc[i], state), right.on_close(i, changed.iloc[i], state))

    def test_no_trade_window_and_timed_exit(self):
        data = bars(2)
        data.index = pd.date_range('2026-01-05 20:59', periods=2, freq='min', tz='UTC')
        data['availability_time'] = data.index + pd.Timedelta(minutes=1)
        model = SND(data, {'variant': 'phase6', 'contracts': 1}, REQUEST)
        model.events = {1: [zone(activation_pos=1)]}
        self.assertIsNone(model.on_close(1, data.iloc[1], {'position': 0, 'tradable': True}))
        order = model.on_close(1, data.iloc[1], {'position': 1, 'tradable': True})
        self.assertEqual(order, {'target': 0, 'timing': 'close', 'reason': 'snd-timed-close'})


if __name__ == '__main__':
    unittest.main()
