"""Focused workbench checks for the Wyckoff NQ execution wrapper."""

from pathlib import Path
import unittest
from unittest.mock import patch

import pandas as pd

from strategies import wyckoff_nq
from workbench.contract import metadata
from workbench.events import simulate_events


ROOT = Path(__file__).resolve().parents[1]


def bars_fixture():
    index = pd.date_range('2024-01-02 09:30', periods=26, freq='15min', tz='America/New_York')
    bars = pd.DataFrame({
        'open': 100.0, 'high': 101.0, 'low': 99.0,
        'close': 100.0, 'volume': 100,
    }, index=index)
    bars['availability_time'] = index + pd.Timedelta(minutes=15)
    return bars


def request_fixture():
    return {
        'dataset': {'symbol': 'NQ', 'tick_size': 0.25, 'point_value': 20},
        'session': 'full-trading-day', 'timeframe': '15m',
        'start': '2024-01-02', 'end': '2024-01-02',
        'capital': 100000, 'fee': 2.5, 'slippage': 1,
    }


def parameters_fixture(**edits):
    parameters = {key: spec['default'] for key, spec in wyckoff_nq.STRATEGY['parameters'].items()}
    return {**parameters, **edits}


class WyckoffNQAdapterTests(unittest.TestCase):
    def test_discovery_metadata_and_original_pine_source(self):
        spec = metadata(ROOT / 'strategies' / 'wyckoff_nq.py')
        self.assertEqual(spec['id'], 'wyckoff-nq')
        self.assertEqual(spec['execution_model'], 'event-v1')
        self.assertEqual(spec['default_warmup_days'], 180)
        self.assertTrue((ROOT / spec['pine_sources'][0]).is_file())

    def test_validation_restricts_market_session_and_timeframe(self):
        parameters = parameters_fixture()
        request = request_fixture()
        wyckoff_nq.validate(parameters, request)
        for change in ({'dataset': {'symbol': 'MNQ'}},
                       {'session': 'new-york-rth'}, {'timeframe': '5m'},
                       {'delay_bars': 1}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                wyckoff_nq.validate(parameters, {**request, **change})

    def test_fixed_hold_fills_next_open_and_exits_at_declared_bar_close(self):
        bars = bars_fixture()
        signal = pd.Series(0, index=bars.index)
        signal.iat[20] = 1
        for delay in (0, 1):
            with self.subTest(entry_delay_bars=delay):
                parameters = parameters_fixture(exit_policy='fixed_bars', holding_bars=2,
                                                entry_delay_bars=delay)
                with patch.object(wyckoff_nq, 'generate_entries', return_value=signal):
                    model = wyckoff_nq.create_strategy(bars, parameters, request_fixture())
                _, trades, _ = simulate_events(bars, model, request_fixture())
                self.assertEqual(len(trades), 1)
                self.assertEqual(pd.Timestamp(trades.iloc[0].entry_time), bars.index[21 + delay])
                self.assertEqual(pd.Timestamp(trades.iloc[0].exit_time),
                                 bars.iloc[22 + delay].availability_time)
                self.assertEqual(trades.iloc[0].exit_reason, 'maximum holding bars')

    def test_bracket_at_signal_does_not_use_future_bar(self):
        bars = bars_fixture()
        altered = bars.copy()
        altered.iloc[22, altered.columns.get_loc('high')] = 200
        signal = pd.Series(0, index=bars.index)
        signal.iat[20] = -1
        parameters = parameters_fixture(exit_policy='atr_bracket', stop_atr=1.5, target_r=2)
        orders = []
        with patch.object(wyckoff_nq, 'generate_entries', return_value=signal):
            for source in (bars, altered):
                model = wyckoff_nq.create_strategy(source, parameters, request_fixture())
                orders.append(model.on_close(20, source.iloc[20],
                                             {'position': 0, 'tradable': True}))
        self.assertEqual(orders[0], orders[1])
        self.assertEqual(orders[0]['target'], -1)
        self.assertEqual(orders[0]['bracket'], (103.0, 94.0))


if __name__ == '__main__':
    unittest.main()
