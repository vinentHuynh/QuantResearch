"""MNQ overnight exit-clock experiment with boundary-open fills."""

from datetime import timedelta

import pandas as pd


STRATEGY = {
    'schema_version': 2,
    'source_files': ['strategies/mnq_exit_clock.py'],
    'id': 'mnq-exit-clock',
    'name': 'MNQ · overnight exit clocks',
    'version': '1.0.0',
    'execution_model': 'event-v1',
    'description': 'One MNQ contract long at the 18:00 ET reopen; compare predeclared '
                   '00:00, 01:00 and 06:00 next-day exit clocks.',
    'timeframes': ['5m'],
    'default_session': 'full-trading-day',
    'required_session': 'full-trading-day',
    'default_warmup_days': 1,
    'capabilities': ['equity', 'trades', 'positions'],
    'legacy_sources': ['scripts/mnq/mnq_exit_time_backtest.py'],
    'migration_scope': 'Ports the three predeclared headline clocks, not the exploratory '
                       'hour scan or historical NQ notional-rescaled comparison. The '
                       'original retrospective study drops nights whose exit quote '
                       'is over 30 minutes late, jointly across arms; this executable '
                       'adapter fails such a replay rather than using future quote '
                       'availability to remove an entered trade. Uses registered MNQ '
                       'bars, which are not identical to the source five-minute file.',
    'parameters': {
        'exit_clock': {'type': 'enum', 'default': '06:00',
                       'choices': ['00:00', '01:00', '06:00']},
    },
}


NEW_YORK = 'America/New_York'


def validate(parameters, request):
    if request['dataset']['symbol'] != 'MNQ':
        raise ValueError('This source trades one MNQ contract; NQ notional scaling is not ported')
    if request['session'] != 'full-trading-day' or request['timeframe'] != '5m':
        raise ValueError('Use five-minute full-trading-day MNQ bars')
    if request.get('delay_bars', 0):
        raise ValueError('Event-order delay bars are not supported')
    if parameters['exit_clock'] not in STRATEGY['parameters']['exit_clock']['choices']:
        raise ValueError('Unsupported exit clock')


class ExitClock:
    def __init__(self, bars, exit_clock):
        self.next_open = pd.DatetimeIndex(bars.index).tz_convert(NEW_YORK)
        self.exit_minute = int(exit_clock[:2]) * 60
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
                    next_open.date() == self.exit_date and minute > self.exit_minute + 30):
                raise ValueError(f'Missing exit quote within 30 minutes of '
                                 f'{self.exit_date} {self.exit_minute // 60:02d}:00 ET')
            if next_open.date() == self.exit_date and (
                    self.exit_minute <= minute <= self.exit_minute + 30):
                self.exit_date = None
                return {'target': 0, 'timing': 'next-open',
                        'expires_at': next_open.isoformat(),
                        'reason': f'exit-clock-{self.exit_minute // 60:02d}'}
            return None

        if minute == 18 * 60:
            self.exit_date = next_open.date() + timedelta(days=1)
            return {'target': 1, 'timing': 'next-open',
                    'expires_at': next_open.isoformat(),
                    'reason': 'overnight-18-open'}
        return None


def create_strategy(bars, parameters, request):
    validate(parameters, request)
    return ExitClock(bars, parameters['exit_clock'])
