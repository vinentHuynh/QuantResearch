"""Causal resting-entry and audit-ledger checks for event-v1."""
import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from workbench.contract import checksum
from workbench.events import simulate_events
from workbench.worker import main as run_worker


REQUEST = {
    'start': '2026-01-05', 'end': '2026-01-06', 'capital': 100000.,
    'fee': 2., 'slippage': 1.,
    'dataset': {'symbol': 'NQ', 'point_value': 20., 'tick_size': .25},
}


def bars(minutes, opens, highs, lows, closes=None, width=1):
    index = pd.DatetimeIndex([f'2026-01-05 {minute}' for minute in minutes], tz='America/Chicago')
    return pd.DataFrame({
        'open': opens, 'high': highs, 'low': lows,
        'close': closes if closes is not None else opens,
        'availability_time': index + pd.Timedelta(minutes=width),
    }, index=index)


class Orders:
    def __init__(self, orders):
        self.orders = orders
        self.states = []

    def on_close(self, i, bar, state):
        self.states.append(state.copy())
        return self.orders.get(i) if state['tradable'] else None


def buy(**changes):
    order = {
        'timing': 'limit', 'target': 1, 'limit_price': 100.,
        'bracket': (95., 110.), 'signal_id': 'setup-1', 'order_id': 'setup-1:gap-touch',
        'expires_at': pd.Timestamp('2026-01-05 09:34', tz='America/Chicago'),
    }
    order.update(changes)
    return order


class EventLimitEntryTests(unittest.TestCase):
    def test_touch_only_does_not_fill_and_entry_minute_cannot_credit_target(self):
        data = bars(['09:30', '09:31', '09:32', '09:33', '09:34'],
                    [101., 101., 101., 105., 110.],
                    [102., 102., 112., 111., 111.],
                    [100., 100., 99.75, 101., 109.])
        model = Orders({0: buy()})
        equity, trades, positions, signals = simulate_events(data, model, REQUEST, return_signals=True)
        self.assertEqual(len(trades), 1)
        trade = trades.iloc[0]
        self.assertEqual(trade.entry, 100.)
        self.assertEqual(trade.exit, 110.)
        self.assertEqual(pd.Timestamp(trade.entry_time), pd.Timestamp('2026-01-05 09:33', tz='America/Chicago'))
        self.assertEqual(pd.Timestamp(trade.exit_time), pd.Timestamp('2026-01-05 09:34', tz='America/Chicago'))
        self.assertEqual(trade.signal_id, 'setup-1')
        self.assertEqual(trade.order_id, 'setup-1:gap-touch')
        self.assertEqual(trade.original_stop, 95.)
        self.assertEqual(trade.original_target, 110.)
        self.assertEqual(trade.requested_limit, 100.)
        self.assertEqual(trade.net_pnl, 196.)  # Limit entry/exit: commission, no market slippage.
        self.assertAlmostEqual(equity.net_pnl.sum(), trades.net_pnl.sum())
        self.assertEqual(signals.event.tolist(), ['submitted', 'filled', 'closed'])
        self.assertEqual(model.states[2]['entry_price'], 100.)
        self.assertEqual(model.states[2]['order_id'], 'setup-1:gap-touch')
        self.assertEqual(model.states[1]['working_order_id'], 'setup-1:gap-touch')
        self.assertEqual(positions.intrabar_contracts.iloc[2], 1)

    def test_limit_is_not_active_on_decision_bar_and_stop_wins_entry_minute(self):
        model_bars = bars(['09:30', '09:33', '09:36'],
                          [101., 101., 97.], [111., 111., 98.], [94., 94., 96.],
                          width=3)
        minute = bars(['09:33', '09:34', '09:35'],
                      [101., 101., 100.], [111., 102., 101.], [94., 99., 99.])
        _, trades, _, signals = simulate_events(model_bars, Orders({0: buy()}),
                                                {**REQUEST, 'slippage': 0.}, minute,
                                                return_signals=True)
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades.iloc[0].entry, 100.)
        self.assertGreaterEqual(pd.Timestamp(trades.iloc[0].entry_time),
                                pd.Timestamp('2026-01-05 09:33', tz='America/Chicago'))
        self.assertEqual(trades.iloc[0].exit, 95.)
        self.assertEqual(trades.iloc[0].exit_reason, 'stop')
        self.assertEqual(trades.iloc[0].net_pnl, -104.)
        self.assertEqual(signals.event.tolist(), ['submitted', 'filled', 'closed'])

    def test_short_limit_and_gap_through_stop_are_conservative(self):
        data = bars(['09:30', '09:31', '09:32'],
                    [99., 103., 100.], [100., 103., 101.], [98., 89., 89.])
        sell = {'timing': 'limit', 'target': -1, 'limit_price': 100.,
                'bracket': (105., 90.), 'signal_id': 'short-1', 'order_id': 'short-1:limit'}
        _, trades, _, signals = simulate_events(data, Orders({0: sell}),
                                                {**REQUEST, 'slippage': 0.}, return_signals=True)
        self.assertEqual(trades.iloc[0].entry, 100.)
        self.assertEqual(trades.iloc[0].exit, 90.)
        self.assertEqual(trades.iloc[0].exit_reason, 'limit')
        self.assertEqual(signals.event.tolist(), ['submitted', 'filled', 'closed'])

        # A buy limit becomes marketable on an opening gap below its stop. The
        # engine grants no improvement on entry and exits at the worse open.
        long_gap = bars(['09:30', '09:31', '09:32'],
                        [101., 94., 94.], [102., 95., 95.], [100., 93., 93.])
        _, trades, _, _ = simulate_events(long_gap, Orders({0: buy()}),
                                          {**REQUEST, 'slippage': 0.}, return_signals=True)
        self.assertEqual(trades.iloc[0].entry, 100.)
        self.assertEqual(trades.iloc[0].exit, 94.)
        self.assertEqual(trades.iloc[0].exit_reason, 'stop')

    def test_bracket_amendment_can_reuse_active_order_id_without_changing_original_stop(self):
        data = bars(['09:30', '09:31', '09:32', '09:33'],
                    [101., 99.5, 101., 102.], [102., 101., 103., 103.],
                    [100., 99.5, 100., 101.])
        model = Orders({0: buy(), 1: {'target': 1, 'bracket': (100., 110.),
                                      'order_id': 'setup-1:gap-touch', 'signal_id': 'setup-1'}})
        _, trades, _, signals = simulate_events(data, model, REQUEST, return_signals=True)
        self.assertEqual(trades.iloc[0].original_stop, 95.)
        updated = signals.loc[signals.event == 'bracket_updated'].iloc[0]
        self.assertEqual(updated.order_id, 'setup-1:gap-touch')
        self.assertEqual(updated.original_stop, 95.)
        self.assertEqual(updated.new_stop, 100.)

    def test_next_open_risk_cap_rejects_gapped_fill_using_actual_price_and_point_value(self):
        data = bars(['09:30', '09:31', '09:32'],
                    [100., 110., 110.], [101., 111., 111.], [99., 109., 109.])
        order = {'timing': 'next-open', 'target': 1, 'bracket': (95., 130.),
                 'signal_id': 'risk-setup', 'order_id': 'risk-order',
                 'max_structural_risk_cash': 250.}
        model = Orders({0: order})
        equity, trades, _, signals = simulate_events(data, model, REQUEST, return_signals=True)
        self.assertTrue(trades.empty)
        self.assertEqual(signals.event.tolist(), ['submitted', 'rejected'])
        self.assertEqual(signals.iloc[1].reason, 'structural-risk-cap')
        self.assertEqual(signals.iloc[1].structural_risk_cash, 300.)
        self.assertEqual(signals.iloc[1].max_structural_risk_cash, 250.)
        self.assertEqual(model.states[1]['entry_filled_this_bar'], None)
        self.assertEqual(equity.net_pnl.sum(), 0.)

        # Five micro contracts on the same NQ price path risk $150, so they fill.
        model = Orders({0: {**order, 'target': 5, 'point_value': 2., 'fee': .7,
                            'contract_label': 'MNQ'}})
        _, trades, _, signals = simulate_events(data, model, REQUEST, return_signals=True)
        self.assertEqual(trades.iloc[0].initial_risk_cash, 150.)
        self.assertEqual(trades.iloc[0].max_structural_risk_cash, 250.)
        self.assertEqual(model.states[1]['entry_filled_this_bar'],
                         {'order_id': 'risk-order', 'signal_id': 'risk-setup'})
        self.assertEqual(signals.event.tolist(), ['submitted', 'filled', 'closed'])

    def test_uncapped_next_open_preserves_legacy_gap_stop_fill(self):
        data = bars(['09:30', '09:31', '09:32'],
                    [100., 94., 94.], [101., 95., 95.], [99., 93., 93.])
        order = {'timing': 'next-open', 'target': 1, 'bracket': (95., 110.),
                 'signal_id': 'legacy-gap', 'order_id': 'legacy-gap-order'}
        equity, trades, _, signals = simulate_events(
            data, Orders({0: order}), {**REQUEST, 'slippage': 0.},
            return_signals=True)
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades.iloc[0].entry, 94.)
        self.assertEqual(trades.iloc[0].exit, 94.)
        self.assertEqual(trades.iloc[0].exit_reason, 'stop')
        self.assertEqual(trades.iloc[0].net_pnl, -4.)
        self.assertAlmostEqual(equity.net_pnl.sum(), trades.net_pnl.sum())
        self.assertEqual(signals.event.tolist(), ['submitted', 'filled', 'closed'])

    def test_next_open_rejects_entry_after_gap_through_structural_stop(self):
        long_gap = bars(['09:30', '09:31', '09:32'],
                        [100., 94., 94.], [101., 95., 95.], [99., 93., 93.])
        long_order = {'timing': 'next-open', 'target': 1, 'bracket': (95., 110.),
                      'signal_id': 'long-gap', 'order_id': 'long-gap-order',
                      'max_structural_risk_cash': 500.}
        _, long_trades, _, long_signals = simulate_events(
            long_gap, Orders({0: long_order}), REQUEST, return_signals=True)
        self.assertTrue(long_trades.empty)
        self.assertEqual(long_signals.event.tolist(), ['submitted', 'rejected'])
        self.assertEqual(long_signals.iloc[1].reason, 'entry-through-structural-stop')

        short_gap = bars(['09:30', '09:31', '09:32'],
                         [100., 106., 106.], [101., 107., 107.], [99., 105., 105.])
        short_order = {'timing': 'next-open', 'target': -1, 'bracket': (105., 90.),
                       'signal_id': 'short-gap', 'order_id': 'short-gap-order',
                       'max_structural_risk_cash': 500.}
        _, short_trades, _, short_signals = simulate_events(
            short_gap, Orders({0: short_order}), REQUEST, return_signals=True)
        self.assertTrue(short_trades.empty)
        self.assertEqual(short_signals.event.tolist(), ['submitted', 'rejected'])
        self.assertEqual(short_signals.iloc[1].reason, 'entry-through-structural-stop')

    def test_nq_mnq_mix_is_exact_and_auditable(self):
        data = bars(['09:30', '09:31', '09:32'],
                    [100., 100., 101.], [101., 102., 102.], [99., 99., 100.])
        order = {'timing': 'next-open', 'target': 13, 'bracket': (95., 110.),
                 'signal_id': 'mixed-risk', 'order_id': 'mixed-risk:open',
                 'point_value': 2., 'fee': (2.5 + 3 * .7) / 13,
                 'contract_label': 'NQ+MNQ', 'nq_contracts': 1, 'mnq_contracts': 3}
        _, trades, _, signals = simulate_events(data, Orders({0: order}),
                                                REQUEST, return_signals=True)
        trade = trades.iloc[0]
        self.assertEqual((trade.nq_contracts, trade.mnq_contracts), (1, 3))
        self.assertEqual(trade.quantity, 13)
        self.assertEqual(trade.point_value, 2.)
        self.assertEqual(trade.initial_risk_cash, 130.)
        self.assertEqual(signals.loc[signals.event == 'filled', 'nq_contracts'].iloc[0], 1)
        self.assertEqual(signals.loc[signals.event == 'filled', 'mnq_contracts'].iloc[0], 3)
        with self.assertRaisesRegex(ValueError, 'NQ/MNQ mix'):
            simulate_events(data, Orders({0: {**order, 'target': 12}}), REQUEST)

    def test_fill_notice_survives_same_bar_stop(self):
        data = bars(['09:30', '09:31', '09:32'],
                    [100., 100., 96.], [101., 101., 97.], [99., 94., 95.])
        order = {'timing': 'next-open', 'target': 1, 'bracket': (95., 110.),
                 'signal_id': 'fast-stop', 'order_id': 'fast-stop-order',
                 'max_structural_risk_cash': 500.}
        model = Orders({0: order})
        _, trades, _, signals = simulate_events(data, model, REQUEST, return_signals=True)
        self.assertEqual(trades.iloc[0].exit_reason, 'stop')
        self.assertEqual(model.states[1]['position'], 0)
        self.assertEqual(model.states[1]['entry_filled_this_bar'],
                         {'order_id': 'fast-stop-order', 'signal_id': 'fast-stop'})
        self.assertEqual(signals.event.tolist(), ['submitted', 'filled', 'closed'])

    def test_close_entry_notice_arrives_at_next_callback(self):
        data = bars(['09:30', '09:31', '09:32'],
                    [100., 100., 100.], [101., 101., 101.], [99., 99., 99.])
        model = Orders({0: {'target': 1, 'bracket': (95., 110.),
                            'signal_id': 'close-signal', 'order_id': 'close-order'}})
        _, trades, _, _ = simulate_events(data, model, REQUEST, return_signals=True)
        self.assertIsNone(model.states[0]['entry_filled_this_bar'])
        self.assertEqual(model.states[1]['entry_filled_this_bar'],
                         {'order_id': 'close-order', 'signal_id': 'close-signal'})
        self.assertEqual(trades.iloc[0].order_id, 'close-order')

    def test_expiry_and_cancel_prevent_later_fills(self):
        data = bars(['09:30', '09:31', '09:32', '09:33'],
                    [101.] * 4, [102.] * 4, [100., 100., 100., 99.75])
        expiry = pd.Timestamp('2026-01-05 09:32', tz='America/Chicago')
        _, trades, _, signals = simulate_events(data, Orders({0: buy(expires_at=expiry)}),
                                                REQUEST, return_signals=True)
        self.assertTrue(trades.empty)
        self.assertEqual(signals.event.tolist(), ['submitted', 'expired'])
        _, trades, _, signals = simulate_events(
            data, Orders({0: buy(), 1: {'timing': 'cancel', 'order_id': 'setup-1:gap-touch'}}),
            REQUEST, return_signals=True)
        self.assertTrue(trades.empty)
        self.assertEqual(signals.event.tolist(), ['submitted', 'cancelled'])

    def test_mnq_economics_proxy_marks_and_charges_the_active_instrument(self):
        data = bars(['09:30', '09:31', '09:32', '09:33'],
                    [101., 99.5, 101., 111.], [102., 101., 111., 112.],
                    [100., 99.5, 100., 109.])
        order = buy(target=5, point_value=2., fee=.7, slippage_ticks=1., contract_label='MNQ')
        equity, trades, _, signals = simulate_events(data, Orders({0: order}), REQUEST, return_signals=True)
        self.assertEqual(len(trades), 1)
        trade = trades.iloc[0]
        self.assertEqual(trade.quantity, 5)
        self.assertEqual(trade.point_value, 2.)
        self.assertEqual(trade.fee_per_side, .7)
        self.assertEqual(trade.contract_label, 'MNQ')
        self.assertEqual(trade.cost, 7.)
        self.assertEqual(trade.net_pnl, 93.)
        self.assertAlmostEqual(equity.net_pnl.sum(), trades.net_pnl.sum())
        self.assertEqual(signals.loc[signals.event == 'submitted', 'point_value'].iloc[0], 2.)
        self.assertEqual(signals.loc[signals.event == 'filled', 'point_value'].iloc[0], 2.)

    def test_duplicate_ids_rejected_and_auto_ids_are_reproducible(self):
        data = bars(['09:30', '09:31', '09:32'],
                    [100.] * 3, [101.] * 3, [99.] * 3)
        with self.assertRaisesRegex(ValueError, 'Duplicate event order ID'):
            simulate_events(data, Orders({0: {'target': 0, 'order_id': 'repeat'},
                                          1: {'target': 0, 'order_id': 'repeat'}}), REQUEST)
        outputs = [simulate_events(data, Orders({0: {'target': 1}}), REQUEST,
                                   return_signals=True)[1:] for _ in range(2)]
        pd.testing.assert_frame_equal(outputs[0][0], outputs[1][0])
        pd.testing.assert_frame_equal(outputs[0][2], outputs[1][2])

    def test_worker_publishes_checksummed_signals_and_id_linked_trades(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / 'strategy.py'
            source.write_text('''\
STRATEGY = {'id': 'limit-test', 'name': 'Limit Test', 'description': 'Fixture',
            'version': '1', 'timeframes': ['1m'], 'parameters': {},
            'execution_model': 'event-v1'}
class Model:
    def on_close(self, i, bar, state):
        if i == 0 and state['tradable']:
            return {'timing': 'limit', 'target': 1, 'limit_price': 100.,
                    'bracket': (95., 110.), 'signal_id': 'signal-x',
                    'order_id': 'order-x'}
def create_strategy(bars, parameters, request):
    return Model()
''', encoding='utf-8')
            (root / 'environment.json').write_text(json.dumps({'dependencies': []}), encoding='utf-8')
            data = bars(['09:30', '09:31', '09:32', '09:33'],
                        [101., 101., 105., 110.], [102., 102., 111., 111.],
                        [100., 99.75, 101., 109.], [101., 101., 110., 110.])
            data.index = data.index.tz_convert('UTC').rename('ts_event')
            data = data.drop(columns=['availability_time'])
            data['volume'] = 1
            data_path = root / 'bars.parquet'
            data.to_parquet(data_path)
            run = root / 'run'
            run.mkdir()
            request = {
                'protocol': 1, 'id': 'limit-worker-fixture', 'source_dir': str(root),
                'strategy': {'file': source.name, 'file_hash': checksum(source)},
                'dataset': {'id': 'fixture', 'symbol': 'NQ', 'path': str(data_path),
                            'checksum': checksum(data_path), 'point_value': 20.,
                            'tick_size': .25, 'warnings': []},
                'parameters': {}, 'timeframe': '1m', 'session': 'full-trading-day',
                'start': '2026-01-05', 'end': '2026-01-05', 'warmup_days': 0,
                'capital': 100000., 'fee': 2., 'slippage': 1.,
            }
            request_file = run / 'input.json'
            request_file.write_text(json.dumps(request), encoding='utf-8')
            run_worker(request_file)
            manifest = json.loads((run / 'manifest.json').read_text(encoding='utf-8'))
            entry = {artifact['name']: artifact for artifact in manifest['artifacts']}
            self.assertIn('signals.csv', entry)
            self.assertEqual(entry['signals.csv']['checksum'], checksum(run / 'signals.csv'))
            self.assertEqual(entry['signals.csv']['rows'], 3)
            trades = pd.read_csv(run / 'trades.csv')
            self.assertEqual(trades.iloc[0].signal_id, 'signal-x')
            self.assertEqual(trades.iloc[0].order_id, 'order-x')
            self.assertEqual(trades.iloc[0].original_stop, 95.)
            self.assertEqual(trades.iloc[0].original_target, 110.)


if __name__ == '__main__':
    unittest.main()
