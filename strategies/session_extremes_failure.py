"""Prior regular-session and overnight extremes with the frozen failure trigger."""
from __future__ import annotations

from collections import Counter
from datetime import timedelta

import numpy as np
import pandas as pd

from strategies._cme_index_calendar import session_close_et
from strategies.multi_touch_cluster_failure import MultiTouchClusterFailure

CT = 'America/Chicago'
WIDTH = pd.Timedelta(minutes=15)

STRATEGY = {
    'schema_version': 2,
    'source_files': ['strategies/session_extremes_failure.py',
                     'strategies/multi_touch_cluster_failure.py',
                     'strategies/_cme_index_calendar.py'],
    'id': 'session-extremes-failure',
    'name': 'Session extremes failure test',
    'version': '1.0.0',
    'description': 'Compare prior regular-session and overnight extremes with the existing first-visit sweep and close-inside-zone failure test.',
    'migration_scope': 'NQ 15m, one contract. Prior day is the previous scheduled 08:30-15:00 CT regular session, shortened by the frozen CME index calendar; overnight is previous calendar day 17:00 to 08:30 CT. Require contiguous observed 15m source windows, not tick or minute completeness. Zones freeze at 08:30 using pre-open ATR; entries only during the regular session. First armed physical visit consumes a zone even without a trade; same close-inside-zone trigger, next-open entry, sweep-extreme stop and 20-bar exit as multi-touch cluster. Positions may carry beyond the regular close. Unadjusted continuous rolls, OHLC stop ordering, no matched generic-failure control, and no event entry-delay stress remain limitations.',
    'execution_model': 'event-v1',
    'timeframes': ['15m'],
    'default_session': 'full-trading-day',
    'required_session': 'full-trading-day',
    'default_warmup_days': 30,
    'capabilities': ['equity', 'trades', 'positions'],
    'parameters': {
        'level_source': {'type': 'enum', 'default': 'prior-day',
                         'choices': ['prior-day', 'overnight'],
                         'description': 'Previous regular-session extremes or completed overnight extremes.'},
        'zone_half_width_atr': {'type': 'number', 'default': 0.10,
                               'minimum': 0.05, 'maximum': 0.20,
                               'description': 'Half-width frozen from the last completed pre-open ATR(14).'},
    },
}


def validate(parameters, request):
    if request['dataset']['symbol'] != 'NQ':
        raise ValueError('Frozen session-extremes campaign requires NQ')
    if request['timeframe'] != '15m' or request['session'] != 'full-trading-day':
        raise ValueError('Requires full-day 15m bars to construct overnight levels')
    if request.get('delay_bars', 0):
        raise ValueError('Event strategies do not support execution delay')


def wall(day, hour, minute=0):
    # Build local wall clocks before localization, avoiding 24h arithmetic at DST.
    return (pd.Timestamp(day) + pd.Timedelta(hours=hour, minutes=minute)).tz_localize(CT)


class SessionExtremesFailure(MultiTouchClusterFailure):
    def __init__(self, bars, parameters, request):
        super().__init__(bars, request)
        self.source = parameters['level_source']
        self.half_width = float(parameters['zone_half_width_atr'])
        self.local = bars.index.tz_convert(CT)
        self.ready = pd.DatetimeIndex(pd.to_datetime(bars.availability_time, utc=True)).tz_convert(CT)
        self.bars = bars
        self.day = None
        self.funnel = Counter()
        self.windows = {}
        self.reference_days = {}
        for day in sorted(set(self.local.date)):
            close = session_close_et(day)
            if close is None:
                continue
            regular_close = min(wall(day, 15), close.tz_convert(CT))
            opening = wall(day, 8, 30)
            if regular_close <= opening:
                continue
            self.windows[day] = (opening, regular_close)
            if self.source == 'overnight':
                begin, finish = wall(day - timedelta(days=1), 17), opening
            else:
                prior = day - timedelta(days=1)
                for _ in range(7):
                    previous_close = session_close_et(prior)
                    if previous_close is not None and previous_close.tz_convert(CT) > wall(prior, 8, 30):
                        break
                    prior -= timedelta(days=1)
                else:
                    continue
                begin = wall(prior, 8, 30)
                finish = min(wall(prior, 15), previous_close.tz_convert(CT))
            a, b = self.local.searchsorted(begin), self.local.searchsorted(finish)
            expected = pd.date_range(begin, finish, freq='15min', inclusive='left')
            if len(expected) == 0 or not self.local[a:b].equals(expected):
                continue
            if not (self.ready[a:b] == expected + WIDTH).all():
                continue
            self.reference_days[day] = {
                'high': float(bars.high.iloc[a:b].max()),
                'low': float(bars.low.iloc[a:b].min()),
                'source_end': finish,
            }

    def _pivot(self, i, side):
        # Replace only the level detector. The inherited trade trigger stays frozen.
        pass

    def on_close(self, i, bar, state):
        day = self.local[i].date()
        window = self.windows.get(day)
        eligible = (window is not None and window[0] <= self.local[i] < window[1]
                    and self.ready[i] < window[1])
        if day != self.day:
            self.day = day
            self.zones = []
        if window is not None and self.local[i] == window[0]:
            self.funnel['regular_sessions'] += 1
            reference = self.reference_days.get(day)
            if (reference is not None and i > 0 and self.ready[i - 1] == window[0]
                    and np.isfinite(self.atr[i - 1]) and self.atr[i - 1] > 0
                    and reference['source_end'] <= self.local[i]):
                self.funnel['sessions_with_levels'] += 1
                half = self.half_width * self.atr[i - 1]
                for side, key in ((-1, 'high'), (1, 'low')):
                    price = reference[key]
                    lower, upper = price - half, price + half
                    armed = self.close[i - 1] > upper if side == 1 else self.close[i - 1] < lower
                    self.zones.append({'side': side, 'low': lower, 'high': upper,
                                       'confirmed': i - 1, 'expires': i + 80,
                                       'armed': bool(armed)})
            else:
                self.funnel['sessions_missing_reference_or_preopen'] += 1
        if not eligible:
            # Still process inherited position/time-exit state, without new entries.
            saved, self.zones = self.zones, []
            decision = super().on_close(i, bar, state)
            self.zones = saved if window is not None and self.local[i] < window[1] else []
            return decision
        before = len(self.zones)
        decision = super().on_close(i, bar, state)
        self.funnel['consumed_zones'] += before - len(self.zones)
        if decision is not None and decision['target'] != 0:
            self.funnel['submitted_entries'] += 1
            decision['reason'] = decision['reason'].replace('cluster-failure:', f'{self.source}-failure:')
            decision['signal_id'] = decision['order_id'] = f'{self.source}-{i}-{self.signal_count}'
            # Known at signal completion; missing later bars expire the pending entry.
            decision['expires_at'] = self.ready[i]
        return decision


def create_strategy(bars, parameters, request):
    return SessionExtremesFailure(bars, parameters, request)
