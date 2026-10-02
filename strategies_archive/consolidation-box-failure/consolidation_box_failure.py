"""Causal consolidation-box edges with the preserved failure-test trigger."""
from __future__ import annotations

from collections import Counter
import json

import numpy as np
import pandas as pd

from strategies._cme_index_calendar import session_close_et
from strategies.multi_touch_cluster_failure import MultiTouchClusterFailure

CT = 'America/Chicago'
WIDTH = pd.Timedelta(minutes=15)

STRATEGY = {
    'schema_version': 2,
    'source_files': ['strategies/consolidation_box_failure.py',
                     'strategies/multi_touch_cluster_failure.py',
                     'strategies/_cme_index_calendar.py'],
    'id': 'consolidation-box-failure',
    'name': 'Consolidation box failure test',
    'version': '1.0.0',
    'description': 'Fade the first armed sweep and close inside a frozen zone at an objectively compact eight-bar range edge.',
    'migration_scope': 'NQ 15m full-day formation, calendar-adjusted regular-hour entries, one contract. Eight consecutive completed candles with high-low span <=2 completed ATR(14); one new box per false-to-true compact-range episode. Freeze each edge +/-0.10 formation ATR for 80 subsequent chart bars. First armed touch consumes the edge, including overnight or while another position is open. No same-formation-bar entry. Same close-inside-zone trigger, next contiguous open, sweep-extreme stop and 20-bar exit as the original cluster test. Calendar and DST are preserved. Observed 15m continuity does not certify minute completeness. No matched generic-failure control, roll adjustment, tick-level ordering or event entry-delay stress.',
    'execution_model': 'event-v1',
    'timeframes': ['15m'],
    'default_session': 'full-trading-day',
    'required_session': 'full-trading-day',
    'default_warmup_days': 30,
    'warmup_bars': {'parameter': 'box_bars', 'multiplier': 1, 'offset': 14},
    'capabilities': ['equity', 'trades', 'positions'],
    'parameters': {
        'box_bars': {'type': 'integer', 'default': 8, 'minimum': 4, 'maximum': 32,
                     'description': 'Completed consecutive 15m candles defining a box.'},
        'max_range_atr': {'type': 'number', 'default': 2.0, 'minimum': 0.5, 'maximum': 4.0,
                          'description': 'Maximum box high-low span in completed formation ATR(14).'},
        'zone_half_width_atr': {'type': 'number', 'default': 0.10, 'minimum': 0.05, 'maximum': 0.20,
                               'description': 'Edge-zone half-width in frozen formation ATR.'},
    },
}


def validate(parameters, request):
    if request['dataset']['symbol'] != 'NQ':
        raise ValueError('Frozen consolidation campaign requires NQ')
    if request['timeframe'] != '15m' or request['session'] != 'full-trading-day':
        raise ValueError('Requires full-day 15m bars')
    if request.get('delay_bars', 0):
        raise ValueError('Event strategies do not support execution delay')


class ConsolidationBoxFailure(MultiTouchClusterFailure):
    def __init__(self, bars, parameters, request):
        super().__init__(bars, request)
        self.box_bars = int(parameters['box_bars'])
        self.max_range_atr = float(parameters['max_range_atr'])
        self.half_width = float(parameters['zone_half_width_atr'])
        self.local = bars.index.tz_convert(CT)
        self.ready = pd.DatetimeIndex(pd.to_datetime(bars.availability_time, utc=True)).tz_convert(CT)
        self.compact = False
        self.box_count = 0
        self.funnel = Counter()
        self.scored_start = pd.Timestamp(request['start'], tz='UTC')
        self.scored_end = pd.Timestamp(request['end'], tz='UTC') + pd.Timedelta(days=1)
        valid = (bars.index >= self.scored_start) & (self.ready < self.scored_end)
        self.last_scored = int(np.flatnonzero(valid)[-1]) if valid.any() else -1
        self.windows = {}
        for day in sorted(set(self.local.date)):
            declared = session_close_et(day)
            if declared is None:
                continue
            midnight = pd.Timestamp(day).tz_localize(CT)
            opening = midnight + pd.Timedelta(hours=8, minutes=30)
            closing = min(midnight + pd.Timedelta(hours=15), declared.tz_convert(CT))
            if closing > opening:
                self.windows[day] = (opening, closing)

    def _pivot(self, i, side):
        if side != 1:
            return
        begin = i - self.box_bars + 1
        if begin < 0 or not np.isfinite(self.atr[i]) or self.atr[i] <= 0:
            self.compact = False
            return
        opens, ready = self.local[begin:i + 1], self.ready[begin:i + 1]
        continuous = ((ready == opens + WIDTH).all() and
                      (np.diff(opens.asi8) == WIDTH.value).all())
        upper = float(self.high[begin:i + 1].max())
        lower = float(self.low[begin:i + 1].min())
        compact = bool(continuous and upper - lower <= self.max_range_atr * self.atr[i])
        new_episode = compact and not self.compact
        self.compact = compact
        if not new_episode:
            return
        self.box_count += 1
        scored = self.local[i] >= self.scored_start and self.ready[i] < self.scored_end
        if scored:
            self.funnel['boxes_formed'] += 1
        half = self.half_width * self.atr[i]
        for direction, price in ((1, lower), (-1, upper)):
            lo, hi = price - half, price + half
            armed = self.close[i] > hi if direction == 1 else self.close[i] < lo
            self.zones.append({'side': direction, 'low': lo, 'high': hi,
                               'confirmed': i, 'expires': i + 80,
                               'armed': bool(armed), 'box_id': self.box_count})

    def on_close(self, i, bar, state):
        window = self.windows.get(self.local[i].date())
        regular = (window is not None and window[0] <= self.local[i] < window[1]
                   and self.ready[i] < window[1])
        scored = self.local[i] >= self.scored_start and self.ready[i] < self.scored_end
        expired = sum(i > zone['expires'] for zone in self.zones)
        before = len(self.zones)
        previous_boxes = self.box_count
        decision = super().on_close(i, bar, {**state, 'tradable': bool(state['tradable'] and regular)})
        added = 2 * (self.box_count - previous_boxes)
        if scored:
            self.funnel['expired_edges'] += expired
            self.funnel['consumed_edges'] += before + added - len(self.zones) - expired
        if decision is not None and decision['target'] != 0:
            self.funnel['submitted_entries'] += 1
            decision['reason'] = decision['reason'].replace('cluster-failure:', 'box-failure:')
            decision['signal_id'] = decision['order_id'] = f'box-{i}-{self.signal_count}'
            decision['expires_at'] = self.ready[i]
        if i == self.last_scored:
            print('Consolidation detector funnel: ' + json.dumps(dict(self.funnel), sort_keys=True), flush=True)
        return decision


def create_strategy(bars, parameters, request):
    return ConsolidationBoxFailure(bars, parameters, request)
