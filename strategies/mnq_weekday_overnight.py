"""Fixed Sun/Tue/Wed subset of the MNQ 18:00–06:00 overnight block."""

from datetime import timedelta

import pandas as pd


STRATEGY = {
    'schema_version': 2,
    'source_files': ['strategies/mnq_weekday_overnight.py'],
    'id': 'mnq-weekday-overnight',
    'name': 'MNQ · Sunday/Tuesday/Wednesday overnight',
    'version': '1.0.0',
    'execution_model': 'event-v1',
    'description': 'One MNQ contract long at the 18:00 ET reopen on Sunday, Tuesday, '
                   'and Wednesday; exit at the first open from 06:00 through 06:30 ET.',
    'timeframes': ['5m'],
    'default_session': 'full-trading-day',
    'required_session': 'full-trading-day',
    'default_warmup_days': 1,
    'capabilities': ['equity', 'trades', 'positions'],
    'legacy_sources': ['scripts/mnq/mnq_weekday_backtest.py'],
    'migration_scope': 'Fixed weekday arm only, not the original adaptive ranking or '
                       'NQ notional-rescaled comparison. Uses registered MNQ five-minute '
                       'bars, one contract and Workbench costs. An absent 06:00–06:30 '
                       'exit quote fails the run instead of dropping the night as the '
                       'retrospective source does. Weekdays were selected after viewing '
                       'the in-sample chart; source-ledger parity, rolls and executable '
                       'fills are not certified.',
    'parameters': {},
}


ENTRY_WEEKDAYS = frozenset((6, 1, 2))  # Sunday, Tuesday, Wednesday (Python weekday)
NEW_YORK = 'America/New_York'


def validate(parameters, request):
    if request['dataset']['symbol'] != 'MNQ':
        raise ValueError('The fixed-weekday source trades MNQ; NQ notional scaling is not ported')
    if request['session'] != 'full-trading-day' or request['timeframe'] != '5m':
        raise ValueError('Use five-minute full-trading-day MNQ bars')
    if request.get('delay_bars', 0):
        raise ValueError('Event-order delay bars are not supported')


class FixedWeekdayOvernight:
    def __init__(self, bars):
        self.next_open = pd.DatetimeIndex(bars.index).tz_convert(NEW_YORK)
        self.exit_date = None

    def on_close(self, i, bar, state):
        if not state['tradable'] or i + 1 >= len(self.next_open):
            return None

        next_open = self.next_open[i + 1]
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
                        'reason': 'weekday-overnight-exit'}
            return None

        if minute == 1080 and next_open.weekday() in ENTRY_WEEKDAYS:
            self.exit_date = next_open.date() + timedelta(days=1)
            return {'target': 1, 'timing': 'next-open',
                    'expires_at': next_open.isoformat(),
                    'reason': 'fixed-weekday-overnight-entry'}
        return None


def create_strategy(bars, parameters, request):
    validate(parameters, request)
    return FixedWeekdayOvernight(bars)
