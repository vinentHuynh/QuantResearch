"""Bounded remaining-zone screen with one shared, preserved failure-test engine."""
from __future__ import annotations

from collections import Counter
from datetime import timedelta
import json
import math

import numpy as np
import pandas as pd

from strategies._cme_index_calendar import session_close_et
from strategies.multi_touch_cluster_failure import MultiTouchClusterFailure

CT = 'America/Chicago'
WIDTH = pd.Timedelta(minutes=15)

STRATEGY = {
    'schema_version': 2,
    'source_files': ['strategies/remaining_zone_failure.py',
                     'strategies/multi_touch_cluster_failure.py',
                     'strategies/_cme_index_calendar.py'],
    'id': 'remaining-zone-failure',
    'name': 'Remaining zone detectors - common failure test',
    'version': '1.0.0',
    'description': 'Frozen initial screen of seven remaining level families and a previous-bar sweep benchmark under common trade mechanics.',
    'migration_scope': 'NQ 15m, one contract. Nine detector candidates plus one generic prior-bar benchmark, 80-chart-bar lifetime, +/-0.10 formation ATR, completed-bar arming, first armed physical visit consumed even outside regular hours, close inside zone, next contiguous open, sweep stop and 20-bar exit. Regular-hour entries; positions can carry. HTF candles contain all expected observed 15m bars, which does not prove minute completeness. Strict two-left/two-right swings activate after confirmation. No matched location control, tick-order proof, roll adjustment, extra event-entry delay, or untouched-holdout claim. Prior studies with different lifetimes/visits are descriptive comparisons only.',
    'execution_model': 'event-v1',
    'timeframes': ['15m'],
    'default_session': 'full-trading-day',
    'required_session': 'full-trading-day',
    'default_warmup_days': 30,
    'warmup_bars': {'parameter': 'swing_sides', 'multiplier': 64, 'offset': 14},
    'capabilities': ['equity', 'trades', 'positions'],
    'parameters': {
        'detector': {'type': 'enum', 'default': 'swing-1h',
                     'choices': ['swing-1h', 'swing-4h', 'opening-15m', 'opening-30m',
                                 'departure-swing', 'role-flip', 'rolling-20',
                                 'round-100', 'daily-pivots', 'generic-prior-bar'],
                     'description': 'Prespecified detector; all use the identical failure-test trade engine.'},
        'zone_half_width_atr': {'type': 'number', 'default': 0.10, 'minimum': 0.05, 'maximum': 0.20,
                               'description': 'Zone half-width frozen from completed formation ATR(14).'},
        'swing_sides': {'type': 'integer', 'default': 2, 'minimum': 2, 'maximum': 2,
                        'description': 'Frozen two-left/two-right swing confirmation; also declares conservative HTF warmup.'},
    },
}


def validate(parameters, request):
    if request['dataset']['symbol'] != 'NQ':
        raise ValueError('Frozen detector screen requires NQ')
    if request['timeframe'] != '15m' or request['session'] != 'full-trading-day':
        raise ValueError('Requires full-day 15m bars')
    if request.get('delay_bars', 0):
        raise ValueError('Additional event-order delay is unavailable')


def wall(day, hour, minute=0):
    return (pd.Timestamp(day) + pd.Timedelta(hours=hour, minutes=minute)).tz_localize(CT)


def complete_higher_bars(bars, minutes):
    """Aggregate from each 17:00 CT session open; release only complete buckets."""
    local = bars.index.tz_convert(CT)
    session_days = [stamp.date() + timedelta(days=1) if stamp.hour >= 17 else stamp.date() for stamp in local]
    rows = []
    span = pd.Timedelta(minutes=minutes)
    frame = bars[['high', 'low']].copy()
    frame.index = local
    frame['_ready'] = pd.to_datetime(bars.availability_time, utc=True).to_numpy()
    for day, group in frame.groupby(session_days, sort=True):
        opening = wall(day - timedelta(days=1), 17)
        bucket = ((group.index - opening) // span).astype(int)
        for number, pieces in group.groupby(bucket):
            start = opening + int(number) * span
            expected = pd.date_range(start, periods=minutes // 15, freq='15min')
            ready = pd.DatetimeIndex(pd.to_datetime(pieces['_ready'], utc=True)).tz_convert(CT)
            if not pieces.index.equals(expected) or not (ready == expected + WIDTH).all():
                continue
            rows.append({'open_time': start, 'ready': start + span,
                         'high': float(pieces.high.max()), 'low': float(pieces.low.min())})
    return rows


class RemainingZoneFailure(MultiTouchClusterFailure):
    def __init__(self, bars, parameters, request):
        super().__init__(bars, request)
        self.detector = parameters['detector']
        self.half_width = float(parameters['zone_half_width_atr'])
        self.bars = bars
        self.local = bars.index.tz_convert(CT)
        self.ready = pd.DatetimeIndex(pd.to_datetime(bars.availability_time, utc=True)).tz_convert(CT)
        self.scored_start = pd.Timestamp(request['start'], tz='UTC')
        self.scored_end = pd.Timestamp(request['end'], tz='UTC') + pd.Timedelta(days=1)
        scored = (bars.index >= self.scored_start) & (self.ready < self.scored_end)
        self.last_scored = int(np.flatnonzero(scored)[-1]) if scored.any() else -1
        self.windows = {}
        self.daily = {}
        self.pending = []
        self.zone_serial = 0
        self.total_births = 0
        self.funnel = Counter()
        self.formations = []
        self.signals_audit = []
        for day in sorted(set(self.local.date)):
            declared = session_close_et(day)
            if declared is None:
                continue
            opening, closing = wall(day, 8, 30), min(wall(day, 15), declared.tz_convert(CT))
            if closing <= opening:
                continue
            self.windows[day] = (opening, closing)
            a, b = self.local.searchsorted(opening), self.local.searchsorted(closing)
            expected = pd.date_range(opening, closing, freq='15min', inclusive='left')
            if self.local[a:b].equals(expected) and (self.ready[a:b] == expected + WIDTH).all():
                self.daily[day] = {'high': float(self.high[a:b].max()), 'low': float(self.low[a:b].min()),
                                   'close': float(self.close[b - 1]), 'end': closing}
        minutes = 60 if self.detector == 'swing-1h' else 240
        self.higher = complete_higher_bars(bars, minutes) if self.detector.startswith('swing-') else []
        self.higher_cursor = 0

    def _scored(self, i):
        return self.local[i] >= self.scored_start and self.ready[i] < self.scored_end

    def _continuous(self, begin, finish):
        if begin < 0:
            return False
        opens = self.local[begin:finish + 1]
        return bool((self.ready[begin:finish + 1] == opens + WIDTH).all()
                    and (np.diff(opens.asi8) == WIDTH.value).all())

    def _add(self, i, side, price, source, source_end, origin_time=None):
        if not np.isfinite(self.atr[i]) or self.atr[i] <= 0:
            return
        if source_end > self.ready[i]:
            raise ValueError('Level source is not available at formation')
        if any(z['side'] == side and abs(z['price'] - price) < self.tick / 2 for z in self.zones):
            return
        half = self.half_width * self.atr[i]
        lower, upper = price - half, price + half
        armed = self.close[i] > upper if side == 1 else self.close[i] < lower
        self.zone_serial += 1
        zone = {'side': side, 'low': lower, 'high': upper, 'price': price,
                'confirmed': i, 'expires': i + 80, 'armed': bool(armed),
                'zone_id': self.zone_serial, 'source': source, 'source_end': source_end}
        self.zones.append(zone)
        self.total_births += 1
        if self._scored(i):
            self.funnel['levels_formed'] += 1
        self.formations.append({'zone_id': self.zone_serial, 'index': i,
                                'confirmed': self.ready[i].isoformat(), 'side': side,
                                'price': price, 'low': lower, 'high': upper,
                                'atr': float(self.atr[i]), 'source': source,
                                'source_end': source_end.isoformat(),
                                'origin_time': (origin_time or source_end).isoformat()})

    def _new_swings(self, i):
        j = i - 2
        if j < 2 or not self._continuous(j - 2, i) or not np.isfinite(self.atr[i]):
            return []
        found = []
        for side, values in ((1, self.low), (-1, self.high)):
            neighbours = np.r_[values[j - 2:j], values[j + 1:i + 1]]
            if (values[j] < neighbours.min() if side == 1 else values[j] > neighbours.max()):
                found.append({'side': side, 'price': float(values[j]), 'confirmed': i,
                              'atr': float(self.atr[i]), 'origin_time': self.local[j]})
        return found

    def _pivot(self, i, side):
        if side != 1 or not np.isfinite(self.atr[i]) or self.atr[i] <= 0:
            return
        mode = self.detector
        if mode.startswith('swing-'):
            while self.higher_cursor < len(self.higher) and self.higher[self.higher_cursor]['ready'] <= self.ready[i]:
                q = self.higher_cursor
                self.higher_cursor += 1
                if q < 4:
                    continue
                j = q - 2
                for direction, key in ((1, 'low'), (-1, 'high')):
                    price = self.higher[j][key]
                    neighbours = [self.higher[k][key] for k in [j - 2, j - 1, j + 1, q]]
                    if (price < min(neighbours) if direction == 1 else price > max(neighbours)):
                        self._add(i, direction, price, mode, self.higher[q]['ready'], self.higher[j]['open_time'])
        elif mode in ['opening-15m', 'opening-30m']:
            day = self.local[i].date()
            window = self.windows.get(day)
            length = 1 if mode == 'opening-15m' else 2
            if window is not None and self.ready[i] == window[0] + length * WIDTH and self.ready[i] < window[1]:
                a = i - length + 1
                if a >= 0 and self.local[a] == window[0] and self._continuous(a, i):
                    self._add(i, 1, float(self.low[a:i + 1].min()), mode, self.ready[i], window[0])
                    self._add(i, -1, float(self.high[a:i + 1].max()), mode, self.ready[i], window[0])
        elif mode in ['departure-swing', 'role-flip']:
            new = self._new_swings(i)
            candidates = self.pending + new if mode == 'departure-swing' else self.pending
            retained = []
            for origin in candidates:
                if i > origin['confirmed'] + (40 if mode == 'departure-swing' else 80):
                    continue
                direction, price = origin['side'], origin['price']
                if mode == 'departure-swing':
                    qualified = direction * (self.close[i] - price) >= 1.5 * origin['atr']
                    output_side = direction
                else:
                    qualified = -direction * (self.close[i] - price) >= self.half_width * origin['atr'] + self.tick
                    output_side = -direction
                if qualified:
                    self._add(i, output_side, price, mode, self.ready[i], origin['origin_time'])
                else:
                    retained.append(origin)
            self.pending = retained + (new if mode == 'role-flip' else [])
        elif mode in ['rolling-20', 'generic-prior-bar']:
            count = 20 if mode == 'rolling-20' else 1
            a = i - count + 1
            if self._continuous(a, i):
                self._add(i, 1, float(self.low[a:i + 1].min()), mode, self.ready[i], self.local[a])
                self._add(i, -1, float(self.high[a:i + 1].max()), mode, self.ready[i], self.local[a])
        elif mode == 'round-100':
            below = math.floor(self.close[i] / 100.) * 100.
            self._add(i, 1, below, mode, self.ready[i])
            self._add(i, -1, below + 100., mode, self.ready[i])
        elif mode == 'daily-pivots':
            day = self.ready[i].date()
            if day not in self.windows or self.ready[i] != self.windows[day][0]:
                return
            prior = day - timedelta(days=1)
            for _ in range(7):
                declared = session_close_et(prior)
                if declared is not None and declared.tz_convert(CT) > wall(prior, 8, 30):
                    break
                prior -= timedelta(days=1)
            record = self.daily.get(prior)
            if record is None or record['end'] > self.ready[i]:
                return
            pivot = (record['high'] + record['low'] + record['close']) / 3.
            self._add(i, 1, 2 * pivot - record['high'], mode, record['end'])
            self._add(i, -1, 2 * pivot - record['low'], mode, record['end'])

    def on_close(self, i, bar, state):
        window = self.windows.get(self.local[i].date())
        regular = window is not None and window[0] <= self.local[i] < window[1] and self.ready[i] < window[1]
        expired = sum(i > z['expires'] for z in self.zones)
        before, births = len(self.zones), self.total_births
        decision = super().on_close(i, bar, {**state, 'tradable': bool(state['tradable'] and regular)})
        if self._scored(i):
            self.funnel['expired_levels'] += expired
            self.funnel['consumed_levels'] += before + self.total_births - births - len(self.zones) - expired
        if decision is not None and decision['target'] != 0:
            self.funnel['submitted_entries'] += 1
            decision['reason'] = decision['reason'].replace('cluster-failure:', self.detector + '-failure:')
            decision['signal_id'] = decision['order_id'] = f'{self.detector}-{i}-{self.signal_count}'
            decision['expires_at'] = self.ready[i]
            self.signals_audit.append({'index': i, 'signal_id': decision['signal_id'],
                                      'timestamp': self.ready[i].isoformat(), 'side': decision['target'],
                                      'atr': float(self.atr[i]), 'reason': decision['reason']})
        if i == self.last_scored:
            print('Remaining detector funnel: ' + json.dumps(dict(self.funnel), sort_keys=True), flush=True)
        return decision


def create_strategy(bars, parameters, request):
    return RemainingZoneFailure(bars, parameters, request)
