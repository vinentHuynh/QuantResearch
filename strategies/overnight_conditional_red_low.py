"""Prior-RTH red-and-low-close gate for an MNQ close-to-next-open long."""

import math

import pandas as pd


STRATEGY = {
    'schema_version': 2,
    'source_files': ['strategies/overnight_conditional_red_low.py'],
    'id': 'overnight-conditional-red-low',
    'name': 'MNQ - Overnight except red low-close RTH',
    'version': '1.0.0',
    'execution_model': 'event-v1',
    'description': 'Long one MNQ from the completed 16:00 ET RTH close to the next '
                   'RTH 09:30 open, except after a red day closing below 33% of its range.',
    'timeframes': ['5m'],
    'default_session': 'full-trading-day',
    'required_session': 'full-trading-day',
    'default_warmup_days': 1,
    'capabilities': ['equity', 'trades', 'positions'],
    'legacy_sources': ['scripts/overnight/overnight_conditional_backtest.py'],
    'migration_scope': 'Ports the pre-specified Long, flat if red+lo-close direction '
                       'rule on complete-clock MNQ RTH sessions only. Excludes the '
                       'source full-sample winsorization, quantile-based wild-day '
                       'rule, approximate return-denominator cost and other markets. '
                       'Missing 09:30 exit quotes fail rather than silently carrying '
                       'a position. Rolls and executable close/open fills are unverified.',
    'parameters': {},
}


NEW_YORK = 'America/New_York'


def validate(parameters, request):
    if request['dataset']['symbol'] != 'MNQ':
        raise ValueError('This single-market branch requires MNQ data')
    if request['session'] != 'full-trading-day' or request['timeframe'] != '5m':
        raise ValueError('Use five-minute full-trading-day MNQ bars')
    if request.get('delay_bars', 0):
        raise ValueError('Event-order delay bars are not supported')


class RedLowCloseOvernight:
    def __init__(self, bars, request):
        self.starts = pd.DatetimeIndex(bars.index).tz_convert(NEW_YORK)
        minute = self.starts.hour * 60 + self.starts.minute
        scored = ((bars.index >= pd.Timestamp(request['start'], tz='UTC')) &
                  (pd.to_datetime(bars.availability_time, utc=True) <
                   pd.Timestamp(request['end'], tz='UTC') + pd.Timedelta(days=1)))
        rth_dates = self.starts[scored & (minute >= 570) & (minute < 960)].date
        self.last_scored_rth_date = max(rth_dates) if len(rth_dates) else None
        self.rth_date = None
        self.rth = None
        self.entry_date = None

    def _observe_rth(self, start, bar):
        minute = start.hour * 60 + start.minute
        if not 570 <= minute < 960:
            return
        date = start.date()
        if date != self.rth_date:
            self.rth_date = date
            self.rth = {
                'open': float(bar.open), 'high': float(bar.high),
                'low': float(bar.low), 'close': float(bar.close),
                'saw_open': minute == 570,
            }
        else:
            self.rth['high'] = max(self.rth['high'], float(bar.high))
            self.rth['low'] = min(self.rth['low'], float(bar.low))
            self.rth['close'] = float(bar.close)

    def _long_direction(self):
        day = self.rth
        if day is None or not day['saw_open']:
            return False
        opening, high, low, closing = (day[k] for k in ('open', 'high', 'low', 'close'))
        if not all(math.isfinite(v) for v in (opening, high, low, closing)) or opening <= 0:
            return False
        # Source uses np.where((green == False) & (loc < 0.33), 0, 1).
        # A zero-range day's location is NaN, so it remains long.
        low_close = high > low and (closing - low) / (high - low) < .33
        return not (closing <= opening and low_close)

    def on_close(self, i, bar, state):
        start = self.starts[i]
        self._observe_rth(start, bar)
        if not state['tradable']:
            return None

        if state['position']:
            if self.entry_date is None:
                raise ValueError('Overnight position has no entry RTH date')
            if i + 1 >= len(self.starts):
                return None  # The Workbench marks a final partial trade separately.
            upcoming = self.starts[i + 1]
            minute = upcoming.hour * 60 + upcoming.minute
            if upcoming.date() > self.entry_date and minute == 570:
                self.entry_date = None
                return {'target': 0, 'timing': 'next-open',
                        'expires_at': upcoming.isoformat(),
                        'reason': 'next-rth-open'}
            if upcoming.date() > self.entry_date and 570 < minute < 960:
                raise ValueError('Missing next RTH 09:30 ET exit quote')
            return None

        if ((start.hour, start.minute) == (15, 55) and self._long_direction() and
                start.date() != self.last_scored_rth_date):
            self.entry_date = start.date()
            return {'target': 1, 'timing': 'close',
                    'reason': 'prior-rth-not-red-and-low-close'}
        return None


def create_strategy(bars, parameters, request):
    validate(parameters, request)
    return RedLowCloseOvernight(bars, request)
