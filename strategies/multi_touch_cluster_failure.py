"""Causal two-pivot level failure test for NQ historical research."""

from __future__ import annotations

import numpy as np
import pandas as pd


STRATEGY = {
    'schema_version': 2,
    'source_files': ['strategies/multi_touch_cluster_failure.py'],
    'id': 'multi-touch-cluster-failure',
    'name': 'Multi-touch cluster failure test',
    'version': '1.0.0',
    'description': 'Fade the first sweep and close back inside a level formed by two confirmed, nearby 15-minute pivots.',
    'migration_scope': 'One frozen mechanical interpretation of a multi-touch failure test. Strict 2-left/2-right pivots, two-pivot cluster, first physical revisit, next-open entry, sweep-extreme stop, 20-bar time exit. Fixed one NQ contract. No discretionary significance, order book, true intraminute trigger sequence, or independent matched-location control. The event runner resolves stops with one-minute OHLC, uses stop-first ambiguity and charges configured costs. Continuous unadjusted contract rolls remain a limitation.',
    'execution_model': 'event-v1',
    'timeframes': ['15m'],
    'default_session': 'full-trading-day',
    'required_session': 'full-trading-day',
    'default_warmup_days': 30,
    'capabilities': ['equity', 'trades', 'positions'],
    'parameters': {},
}


def validate(parameters, request):
    if request['dataset']['symbol'] != 'NQ':
        raise ValueError('This frozen experiment requires NQ')
    if request['timeframe'] != '15m' or request['session'] != 'full-trading-day':
        raise ValueError('This frozen experiment requires full-day 15m bars')
    if request.get('delay_bars', 0):
        raise ValueError('Event-v1 does not support execution delay')


class MultiTouchClusterFailure:
    """Decide from completed bars; a pivot is known two bars after its extreme."""

    def __init__(self, bars, request):
        previous = bars.close.shift(1)
        true_range = pd.concat([
            bars.high - bars.low,
            (bars.high - previous).abs(),
            (bars.low - previous).abs(),
        ], axis=1).max(axis=1)
        self.atr = true_range.rolling(14, min_periods=14).mean().to_numpy(float)
        self.high = bars.high.to_numpy(float)
        self.low = bars.low.to_numpy(float)
        self.close = bars.close.to_numpy(float)
        self.tick = float(request['dataset']['tick_size'])
        self.pivots = {1: [], -1: []}
        self.zones = []
        self.active_signal = None
        self.signal_count = 0

    def _pivot(self, i, side):
        j = i - 2
        if j < 2 or not np.isfinite(self.atr[i]) or self.atr[i] <= 0:
            return
        series = self.low if side == 1 else self.high
        price = series[j]
        neighbours = np.r_[series[j-2:j], series[j+1:i+1]]
        if (price >= neighbours.min() if side == 1 else price <= neighbours.max()):
            return
        previous = next((pivot for pivot in reversed(self.pivots[side])
                         if 4 <= j - pivot[0] <= 40 and
                         abs(price - pivot[1]) <= 0.25 * self.atr[i]), None)
        self.pivots[side].append((j, float(price)))
        self.pivots[side] = [pivot for pivot in self.pivots[side] if j - pivot[0] <= 40]
        if previous is None:
            return
        lower = min(price, previous[1]) - 0.10 * self.atr[i]
        upper = max(price, previous[1]) + 0.10 * self.atr[i]
        self.zones.append({'side': side, 'low': float(lower), 'high': float(upper),
                           'confirmed': i, 'expires': i + 80, 'armed': False})

    def on_close(self, i, bar, state):
        position = int(state['position'])
        time_exit = position and self.active_signal is not None and i >= self.active_signal + 20
        if not position and self.active_signal is not None and i > self.active_signal:
            self.active_signal = None

        decision = None
        retained = []
        for zone in self.zones:
            if i > zone['expires']:
                continue
            side, lower, upper = zone['side'], zone['low'], zone['high']
            if not zone['armed']:
                zone['armed'] = (self.close[i] > upper if side == 1 else self.close[i] < lower)
                retained.append(zone)
                continue
            previous_close = self.close[i-1]
            approaching = (previous_close > upper and float(bar.open) > upper if side == 1 else
                           previous_close < lower and float(bar.open) < lower)
            touches = (float(bar.low) <= upper if side == 1 else float(bar.high) >= lower)
            if not touches:
                retained.append(zone)
                continue
            # The first physical visit consumes the zone, including shallow visits.
            swept = (float(bar.low) <= lower - self.tick if side == 1 else
                     float(bar.high) >= upper + self.tick)
            reclaimed = lower <= float(bar.close) <= upper
            if not (approaching and swept and reclaimed and decision is None and
                    not position and not state.get('position_at_open') and state['tradable']):
                continue
            stop = (float(bar.low) - self.tick if side == 1 else
                    float(bar.high) + self.tick)
            # A remote bracket target enables the runner's intraminute stop model;
            # the declared exit is the time exit unless an extraordinary move hits it.
            remote = float(bar.close) + side * 1000 * self.atr[i]
            self.signal_count += 1
            signal_id = f'cluster-{i}-{self.signal_count}'
            decision = {'target': int(side), 'timing': 'next-open',
                        'bracket': (stop, remote),
                        'max_structural_risk_cash': 1_000_000_000.,
                        'signal_id': signal_id, 'order_id': signal_id,
                        'reason': f'cluster-failure:{zone["confirmed"]}:{lower:.2f}:{upper:.2f}'}
            self.active_signal = i
        self.zones = retained
        self._pivot(i, 1)
        self._pivot(i, -1)
        if time_exit:
            self.active_signal = None
            return {'target': 0, 'timing': 'close', 'reason': '20-bar-time-exit'}
        return decision


def create_strategy(bars, parameters, request):
    return MultiTouchClusterFailure(bars, request)
