import unittest
from pathlib import Path

import pandas as pd

from strategies.market_intraday_momentum import STRATEGY, IntradayMomentum, validate
from workbench.contract import metadata, resolve_parameters
from workbench.events import simulate_events


class IntradayMomentumTests(unittest.TestCase):
    def params(self, **changes):
        return resolve_parameters(STRATEGY, changes)

    def bars(self, freq='5min'):
        pieces = []
        for day, price in [('2024-03-08', 100.), ('2024-03-11', 102.), ('2024-03-12', 99.)]:
            index = pd.date_range(day+' 09:30', day+' 15:59', freq=freq, tz='America/New_York')
            b = pd.DataFrame({'open': price, 'high': price+2, 'low': price-2, 'close': price,
                              'availability_time': index+pd.Timedelta(freq)}, index=index)
            b.loc[b.index[-1], 'close'] = price+1
            pieces.append(b)
        return pd.concat(pieces)

    def run_model(self, bars=None, **changes):
        bars = self.bars() if bars is None else bars
        request = {'start': '2024-03-08', 'end': '2024-03-12', 'capital': 100000,
                   'fee': 2.5, 'slippage': 1, 'dataset': {'symbol': 'ES', 'point_value': 50, 'tick_size': .25}}
        return simulate_events(bars, IntradayMomentum(bars, self.params(**changes)), request)

    def decisions(self, bars, **changes):
        model = IntradayMomentum(bars, self.params(**changes))
        return [model.on_close(i, bar, {'position': 0, 'tradable': True}) for i, (_, bar) in enumerate(bars.iterrows())]

    def test_discovery_and_parameter_validation(self):
        spec = metadata(Path('strategies/market_intraday_momentum.py'))
        self.assertEqual(spec['id'], 'market-intraday-momentum')
        for change in ({'contracts': 0}, {'signal_mode': 'unknown'}, {'minimum_move_bps': -1}):
            with self.assertRaises(ValueError):
                self.params(**change)
        request = {'session': 'new-york-rth', 'timeframe': '5m', 'dataset': {'symbol': 'CL'}}
        with self.assertRaises(ValueError):
            validate(self.params(), request)
        validate(self.params(close_time='14:30'), request)
        for key, value in [('session', 'full-trading-day'), ('timeframe', '1d'), ('dataset', {'symbol': 'ZN'})]:
            with self.assertRaises(ValueError):
                validate(self.params(), {**request, key: value})

    def test_long_short_exact_window_dst_cost_and_reconciliation(self):
        equity, trades, positions = self.run_model()
        self.assertEqual(list(trades.quantity), [1, -1])
        self.assertEqual(list(trades.gross_pnl), [50., -50.])
        self.assertEqual(list(trades.cost), [30., 30.])
        self.assertAlmostEqual(equity.equity.iloc[-1]-100000, trades.net_pnl.sum())
        self.assertAlmostEqual(equity.cost.sum(), trades.cost.sum())
        for t in trades.itertuples():
            entry, exit = pd.Timestamp(t.entry_time), pd.Timestamp(t.exit_time)
            self.assertEqual((entry.hour, entry.minute), (15, 30))
            self.assertEqual((exit.hour, exit.minute), (16, 0))
            self.assertEqual(entry.date(), exit.date())
            self.assertEqual(entry.utcoffset().total_seconds(), -4*3600)
            self.assertEqual(t.exit_reason, 'scheduled-market-close')
        self.assertTrue((positions.loc[pd.to_datetime(positions.timestamp, utc=True).dt.hour == 20, 'contracts'] == 0).all())

    def test_gao_includes_overnight_and_differs_from_rest_of_day(self):
        bars = self.bars()
        bars.loc['2024-03-11 09:55', 'close'] = 100.
        self.assertEqual(self.run_model(bars, signal_mode='first-half-hour')[1].quantity.iloc[0], -1)
        self.assertEqual(self.run_model(bars)[1].quantity.iloc[0], 1)

    def test_delay_preserves_original_signal(self):
        bars = self.bars()
        bars.loc['2024-03-11 15:30', 'close'] = 90.
        t = self.run_model(bars, entry_delay_minutes='5')[1].iloc[0]
        self.assertEqual(t.quantity, 1)
        self.assertEqual(pd.Timestamp(t.entry_time).minute, 35)
        self.assertEqual(pd.Timestamp(t.exit_time).hour, 16)

    def test_window_neighbors_and_contract_scaling(self):
        for window, entry_minute in [('25', 35), ('35', 25)]:
            t = self.run_model(holding_minutes=window, contracts=2)[1].iloc[0]
            self.assertEqual(pd.Timestamp(t.entry_time).minute, entry_minute)
            self.assertEqual(t.quantity, 2)
            self.assertEqual(t.cost, 60.)

    def test_cl_clock(self):
        bars = self.bars()
        trades = self.run_model(bars, close_time='14:30')[1]
        self.assertEqual(len(trades), 2)
        self.assertTrue(all(pd.Timestamp(t).hour == 14 and pd.Timestamp(t).minute == 0 for t in trades.entry_time))
        self.assertTrue(all(pd.Timestamp(t).hour == 14 and pd.Timestamp(t).minute == 30 for t in trades.exit_time))

    def test_prefix_and_future_perturbation_causality(self):
        bars = self.bars()
        for mode in ['rest-of-day', 'first-half-hour']:
            full = self.decisions(bars, signal_mode=mode)
            for size in [80, 100, 150, 180]:
                self.assertEqual(full[:size], self.decisions(bars.iloc[:size], signal_mode=mode))
            changed = bars.copy()
            changed.iloc[151:, changed.columns.get_indexer(['open', 'high', 'low', 'close'])] = 999.
            self.assertEqual(full[:151], self.decisions(changed, signal_mode=mode)[:151])

    def test_missing_entry_expires_without_late_or_overnight_fill(self):
        bars = self.bars().drop(pd.Timestamp('2024-03-11 15:30', tz='America/New_York'))
        trades = self.run_model(bars)[1]
        self.assertEqual(len(trades), 1)
        self.assertEqual(pd.Timestamp(trades.entry_time.iloc[0]).day, 12)

    def test_missing_signal_skips_day(self):
        bars = self.bars().drop(pd.Timestamp('2024-03-11 15:25', tz='America/New_York'))
        self.assertEqual(len(self.run_model(bars)[1]), 1)

    def test_missing_exit_fails_instead_of_hiding_overnight(self):
        bars = self.bars().drop(pd.Timestamp('2024-03-11 15:55', tz='America/New_York'))
        with self.assertRaisesRegex(ValueError, 'Missing scheduled closing quote'):
            self.run_model(bars)

    def test_terminal_partial_session_cannot_force_an_early_exit(self):
        bars = self.bars().loc[:'2024-03-12 15:45']
        with self.assertRaisesRegex(ValueError, 'Data ends before scheduled closing quote'):
            self.run_model(bars)

    def test_zero_threshold_nonpositive_and_no_prior_close(self):
        bars = self.bars()
        bars.loc[:, ['open', 'high', 'low', 'close']] = 100.
        self.assertTrue(self.run_model(bars)[1].empty)
        bars.loc['2024-03-08 15:55', 'close'] = -1.
        self.assertTrue(self.run_model(bars)[1].empty)
        self.assertTrue(self.run_model(minimum_move_bps=500)[1].empty)

    def test_stale_previous_close_suppresses_signal(self):
        bars = self.bars()
        bars = bars.loc[:'2024-03-11'].copy()
        monday = bars.index.date == pd.Timestamp('2024-03-11').date()
        moved = bars.loc[monday].copy()
        moved.index += pd.Timedelta(days=2)
        moved['availability_time'] += pd.Timedelta(days=2)
        joined = pd.concat([bars.loc[~monday], moved])
        self.assertTrue(all(d is None for d in self.decisions(joined)))

    def test_one_minute_and_five_minute_trade_parity(self):
        for mode in ['rest-of-day', 'first-half-hour']:
            a = self.run_model(self.bars('1min'), signal_mode=mode)[1]
            b = self.run_model(self.bars(), signal_mode=mode)[1]
            pd.testing.assert_frame_equal(a.drop(columns='entry_bar_close'), b.drop(columns='entry_bar_close'))

    def test_warmup_does_not_create_a_position(self):
        bars = self.bars()
        model = IntradayMomentum(bars, self.params())
        for i, (_, bar) in enumerate(bars.iterrows()):
            self.assertIsNone(model.on_close(i, bar, {'position': 0, 'tradable': False}))


if __name__ == '__main__':
    unittest.main()
