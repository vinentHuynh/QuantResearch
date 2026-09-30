"""Causal NQ research adapter for the Wyckoff indicator's Auto entries.

The signal generator ports the indicator separately. This adapter adds explicit
next-open entries and research exits; it does not claim TradingView trade parity.
"""

from __future__ import annotations

import math

import pandas as pd

from strategies._wyckoff_core import generate_entries


STRATEGY = {
    'schema_version': 2,
    'source_files': ['strategies/wyckoff_nq.py', 'strategies/_wyckoff_core.py'],
    'id': 'wyckoff-nq',
    'name': 'Wyckoff [theUltimator5] - NQ research',
    'version': '0.1.0',
    'description': 'Completed-bar Wyckoff Auto entries on NQ with one-contract next-open fills and explicit research exits.',
    'migration_scope': 'Research port of the indicator Auto entry checks, with one selected chart timeframe and no MTF override. Pivot labels are actionable only on their confirmation bar. One fixed NQ contract per entry. Fixed-bar exits, optional ATR brackets, and optional extra-bar entry delay are workbench research rules, not rules supplied by the Pine indicator. ATR bracket levels are anchored to the signal or delayed-decision close, not the actual next-open fill, so gaps can change realized R; bracket exits require separate qualification. Next-open fills, one-minute bracket execution, fees, slippage, session filtering, and final liquidation follow the workbench simulator. TradingView parity is not certified.',
    'execution_model': 'event-v1',
    'timeframes': ['15m', '30m', '1h', '4h'],
    'default_session': 'full-trading-day',
    'required_session': 'full-trading-day',
    'default_warmup_days': 180,
    'capabilities': ['equity', 'trades', 'positions'],
    'pine_sources': ['pine/wyckoff_theultimator5.pine'],
    'parameters': {
        'strictness': {
            'type': 'enum', 'default': 'Standard',
            'choices': ['Conservative', 'Standard', 'Aggressive'],
            'description': 'The Pine indicator Auto entry strictness.',
        },
        'exit_policy': {
            'type': 'enum', 'default': 'fixed_bars',
            'choices': ['atr_bracket', 'fixed_bars'],
            'description': 'Research exit: ATR stop/target or maximum holding bars only.',
        },
        'holding_bars': {
            'type': 'integer', 'default': 24, 'minimum': 1, 'maximum': 200,
            'description': 'Exit at the close of this many selected bars after entry, unless a bracket exits first.',
        },
        'entry_delay_bars': {
            'type': 'integer', 'default': 0, 'minimum': 0, 'maximum': 1,
            'description': 'Extra completed chart bars to wait before submitting a next-open entry.',
        },
        'atr_length': {
            'type': 'integer', 'default': 14, 'minimum': 2, 'maximum': 100,
            'description': 'Completed chart bars in the Wilder-style ATR used for exits.',
        },
        'stop_atr': {
            'type': 'number', 'default': 1.5, 'minimum': 0.25, 'maximum': 10,
            'description': 'Initial stop distance as a multiple of ATR; applies to ATR bracket exits.',
        },
        'target_r': {
            'type': 'number', 'default': 2.0, 'minimum': 0.25, 'maximum': 10,
            'description': 'Initial target distance as a multiple of stop distance; applies to ATR bracket exits.',
        },
    },
}


def validate(parameters, request):
    if request['dataset']['symbol'] != 'NQ':
        raise ValueError('This Wyckoff research adapter requires the full-size NQ dataset')
    if request['session'] != 'full-trading-day':
        raise ValueError('This Wyckoff research adapter requires the full trading day')
    if request['timeframe'] not in STRATEGY['timeframes']:
        raise ValueError('Unsupported Wyckoff chart timeframe')
    if request.get('delay_bars', 0):
        raise ValueError('Event strategies do not support additional execution delay')


class WyckoffNQ:
    def __init__(self, bars, parameters, request):
        self.parameters = parameters
        self.request = request
        self.entries = generate_entries(bars, parameters['strictness'])
        if not isinstance(self.entries, pd.Series) or not self.entries.index.equals(bars.index):
            raise ValueError('Wyckoff entries must be a Series with exactly the chart-bar index')
        if not self.entries.isin((-1, 0, 1)).all():
            raise ValueError('Wyckoff entries must contain only -1, 0, or 1')
        previous_close = bars.close.shift(1)
        true_range = pd.concat([
            bars.high - bars.low,
            (bars.high - previous_close).abs(),
            (bars.low - previous_close).abs(),
        ], axis=1).max(axis=1)
        length = parameters['atr_length']
        self.atr = true_range.ewm(alpha=1 / length, adjust=False, min_periods=length).mean()
        self.entry_bar = None
        self.delayed_entry = None

    def _entry_order(self, direction, atr, reference_close):
        order = {'target': direction, 'timing': 'next-open', 'reason': 'Wyckoff Auto entry'}
        if self.parameters['exit_policy'] == 'atr_bracket':
            if not math.isfinite(atr) or atr <= 0:
                return None
            tick = float(self.request['dataset']['tick_size'])
            price_ticks = round(float(reference_close) / tick)
            stop_ticks = max(1, math.ceil(self.parameters['stop_atr'] * atr / tick))
            target_ticks = max(1, math.ceil(self.parameters['target_r'] * stop_ticks))
            stop = (price_ticks - direction * stop_ticks) * tick
            target = (price_ticks + direction * target_ticks) * tick
            order['bracket'] = (stop, target)
        return order

    def on_close(self, i, bar, state):
        if not state['tradable']:
            return None

        position = int(state['position'])
        if position:
            self.delayed_entry = None
            if self.entry_bar is None:
                # A next-open entry first exists during this selected chart bar.
                self.entry_bar = i
            if i - self.entry_bar + 1 >= self.parameters['holding_bars']:
                self.entry_bar = None
                return {'target': 0, 'timing': 'close', 'reason': 'maximum holding bars'}
            return None

        self.entry_bar = None
        if self.delayed_entry is not None:
            direction, signal_atr = self.delayed_entry
            self.delayed_entry = None
            return self._entry_order(direction, signal_atr, bar.close)

        direction = int(self.entries.iat[i])
        if not direction:
            return None
        signal_atr = float(self.atr.iat[i])
        if self.parameters['entry_delay_bars']:
            self.delayed_entry = (direction, signal_atr)
            return None
        return self._entry_order(direction, signal_atr, bar.close)


def create_strategy(bars, parameters, request):
    return WyckoffNQ(bars, parameters, request)
