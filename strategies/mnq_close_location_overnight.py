"""MNQ overnight block conditioned on the completed same-day RTH close location."""

from datetime import timedelta
import math

import pandas as pd


STRATEGY = {
    'schema_version': 2,
    'source_files': ['strategies/mnq_close_location_overnight.py'],
    'id': 'mnq-close-location-overnight',
    'name': 'MNQ · RTH close-location overnight',
    'version': '1.0.0',
    'execution_model': 'event-v1',
    'description': 'One-contract 18:00–06:00 ET MNQ long only when that day’s '
                   'RTH close is at or below 80% of its own high-low range.',
    'timeframes': ['5m'],
    'default_session': 'full-trading-day',
    'required_session': 'full-trading-day',
    'default_warmup_days': 10,
    'capabilities': ['equity', 'trades', 'positions'],
    'legacy_sources': ['scripts/mnq/mnq_close_location_backtest.py'],
    'migration_scope': 'Ports only the source’s fixed CLV≤0.8 trading arm, not its '
                       'correlation study, alternate cutoffs or notional-rescaled '
                       '2015–2019 NQ comparison. Uses completed same-day RTH bars '
                       'and one MNQ contract. Missing 06:00–06:30 exit quotes fail '
                       'the run instead of retrospectively dropping a night. '
                       'Source-ledger parity, rolls and executable fills are not certified.',
    'parameters': {},
}


NEW_YORK = 'America/New_York'
CLV_CEILING = 0.8


def validate(parameters, request):
    if request['dataset']['symbol'] != 'MNQ':
        raise ValueError('The fixed CLV arm trades MNQ; NQ notional scaling is not ported')
    if request['session'] != 'full-trading-day' or request['timeframe'] != '5m':
        raise ValueError('Use five-minute full-trading-day MNQ bars')
    if request.get('delay_bars', 0):
        raise ValueError('Event-order delay bars are not supported')


class CloseLocationOvernight:
    def __init__(self, bars):
        self.starts = pd.DatetimeIndex(bars.index).tz_convert(NEW_YORK)
        self.current_date = None
        self.current = None
        self.previous = None
        self.exit_date = None

    def _observe_rth(self, start, bar):
        minute = start.hour * 60 + start.minute
        if not 570 <= minute < 960:
            return
        day = start.date()
        if day != self.current_date:
            if self.current and self.current['high'] > self.current['low']:
                self.previous = self.current
            self.current_date = day
            self.current = {
                'open': float(bar.open), 'high': float(bar.high),
                'low': float(bar.low), 'close': float(bar.close),
            }
        else:
            self.current['high'] = max(self.current['high'], float(bar.high))
            self.current['low'] = min(self.current['low'], float(bar.low))
            self.current['close'] = float(bar.close)

    def _eligible(self, entry_day):
        day, prior = self.current, self.previous
        if self.current_date != entry_day or day is None or prior is None:
            return False
        if not all(math.isfinite(value) for value in (*day.values(), *prior.values())):
            return False
        if day['high'] <= day['low'] or prior['high'] <= prior['low']:
            return False
        if day['open'] <= 0 or day['close'] <= 0 or prior['close'] <= 0:
            return False
        clv = (day['close'] - day['low']) / (day['high'] - day['low'])
        return math.isfinite(clv) and clv <= CLV_CEILING

    def on_close(self, i, bar, state):
        self._observe_rth(self.starts[i], bar)
        if not state['tradable'] or i + 1 >= len(self.starts):
            return None

        next_open = self.starts[i + 1]
        minute = next_open.hour * 60 + next_open.minute
        if state['position']:
            if self.exit_date is None:
                raise ValueError('Overnight position has no scheduled exit date')
            if next_open.date() > self.exit_date or (
                    next_open.date() == self.exit_date and minute > 390):
                raise ValueError('Missing 06:00–06:30 ET overnight exit quote')
            if next_open.date() == self.exit_date and 360 <= minute <= 390:
                self.exit_date = None
                return {'target': 0, 'timing': 'next-open',
                        'expires_at': next_open.isoformat(),
                        'reason': 'close-location-overnight-exit'}
            return None

        if minute == 1080 and self._eligible(next_open.date()):
            self.exit_date = next_open.date() + timedelta(days=1)
            return {'target': 1, 'timing': 'next-open',
                    'expires_at': next_open.isoformat(),
                    'reason': 'clv-at-or-below-0.8'}
        return None


def create_strategy(bars, parameters, request):
    validate(parameters, request)
    return CloseLocationOvernight(bars)
