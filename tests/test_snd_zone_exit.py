import unittest
import pandas as pd
from test_snd_adapter import bars, zone, REQUEST
from strategies._snd_model import SND
from strategies._snd_zone_exit import SNDZoneExit
from workbench.events import simulate_events


class SNDZoneExitTests(unittest.TestCase):
    def model(self, mode, data):
        model = SNDZoneExit(data, {'variant': 'phase6', 'contracts': 1, 'zone_exit': mode}, REQUEST)
        model.events = {}
        return model

    def test_long_touch_and_close_are_distinct_and_do_not_use_touch_price(self):
        data = bars(5)
        for mode, expected in [('touch', True), ('close-inside', False)]:
            model = self.model(mode, data)
            model.shorts = [zone(direction='short', proximal=101., distal=103.)]
            order = model.on_close(0, data.iloc[0], {'position': 1, 'tradable': True})
            self.assertEqual(order is not None, expected)
            if order:
                self.assertEqual(order['timing'], 'next-open')

    def test_short_close_inside_and_no_future_zone(self):
        data = bars(5)
        model = self.model('close-inside', data)
        model.events = {1: [zone(proximal=101., distal=99.)]}
        state = {'position': -1, 'tradable': True}
        self.assertIsNone(model.on_close(0, data.iloc[0], state))
        self.assertEqual(model.on_close(1, data.iloc[1], state)['target'], 0)

    def test_touch_survives_same_bar_invalidation_but_close_beyond_is_not_inside(self):
        data = bars(5)
        data.loc[data.index[0], ['high', 'close']] = [105., 104.]
        for mode, expected in [('touch', True), ('close-inside', False)]:
            model = self.model(mode, data)
            model.shorts = [zone(direction='short', proximal=101., distal=103.)]
            order = model.on_close(0, data.iloc[0], {'position': 1, 'tradable': True})
            self.assertEqual(order is not None, expected)
            self.assertEqual(model.shorts, [])

    def test_next_open_actual_fill_and_accounting(self):
        data = bars(5)
        data.loc[data.index[2], ['open', 'high', 'low', 'close']] = [102., 105., 101., 103.]
        data.loc[data.index[3], ['open', 'high', 'low', 'close']] = [104., 105., 103., 104.]
        model = self.model('close-inside', data)
        model.events = {0: [zone()], 2: [zone(2, direction='short', proximal=102., distal=106., width=4., activation_pos=2)]}
        equity, trades, _ = simulate_events(data, model, REQUEST, execution_bars=data)
        self.assertEqual(trades.iloc[0].exit_reason, 'snd-opposing-zone-close-inside')
        self.assertEqual(trades.iloc[0]['exit'], 104.)
        self.assertEqual(pd.Timestamp(trades.iloc[0].exit_time), data.index[3])
        self.assertAlmostEqual(trades.net_pnl.sum(), equity.equity.iloc[-1] - REQUEST['capital'])

    def test_baseline_exact_parity_and_stop_priority(self):
        data = bars(5)
        data.loc[data.index[2], 'low'] = 95.
        models = [SND(data, {'variant': 'phase6', 'contracts': 1}, REQUEST), self.model('baseline', data)]
        outputs = []
        for model in models:
            model.events = {0: [zone()], 2: [zone(2, direction='short', proximal=101., distal=103., activation_pos=2)]}
            outputs.append(simulate_events(data, model, REQUEST, execution_bars=data))
        for left, right in zip(*outputs):
            pd.testing.assert_frame_equal(left, right)
        for mode in ['touch', 'close-inside']:
            model = self.model(mode, data)
            model.events = {0: [zone()], 2: [zone(2, direction='short', proximal=101., distal=103., activation_pos=2)]}
            _, trades, _ = simulate_events(data, model, REQUEST, execution_bars=data)
            self.assertEqual(trades.iloc[0].exit_reason, 'stop')


if __name__ == '__main__':
    unittest.main()
