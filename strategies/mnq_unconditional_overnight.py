"""One-contract MNQ long from the RTH close to the next RTH open."""

import pandas as pd


STRATEGY = {
    'schema_version': 2,
    'source_files': ['strategies/mnq_unconditional_overnight.py'],
    'id': 'mnq-unconditional-overnight',
    'name': 'MNQ - Unconditional RTH close-to-open',
    'version': '1.0.0',
    'execution_model': 'event-v1',
    'description': 'Long one MNQ at each complete 16:00 ET RTH close, then exit at '
                   'the next RTH 09:30 open; control for conditional overnight rules.',
    'timeframes': ['5m'],
    'default_session': 'full-trading-day',
    'required_session': 'full-trading-day',
    'default_warmup_days': 1,
    'capabilities': ['equity', 'trades', 'positions'],
    'legacy_sources': ['scripts/overnight/futures_overnight_backtest.py'],
    'migration_scope': 'Ports the raw one-MNQ-contract RTH-close to next-RTH-open '
                       'trade only. Requires exact 09:30 and 15:55 ET bars and '
                       'suppresses an entry on the final scored RTH date. The '
                       'retrospective source uses available partial-session clocks '
                       'and winsorizes percentage-return reporting. Workbench uses '
                       'raw fixed-contract P&L and explicit execution costs. '
                       'Other markets, intraday/buy-and-hold comparisons, rolls, '
                       'and executable close/open fills are not certified.',
    'parameters': {},
}


NEW_YORK = 'America/New_York'


def validate(parameters, request):
    if request['dataset']['symbol'] != 'MNQ':
        raise ValueError('This one-contract control requires MNQ data')
    if request['session'] != 'full-trading-day' or request['timeframe'] != '5m':
        raise ValueError('Use five-minute full-trading-day MNQ bars')
    if request.get('delay_bars', 0):
        raise ValueError('Event-order delay bars are not supported')


class UnconditionalOvernight:
    def __init__(self, bars, request):
        self.starts = pd.DatetimeIndex(bars.index).tz_convert(NEW_YORK)
        minute = self.starts.hour * 60 + self.starts.minute
        scored = ((bars.index >= pd.Timestamp(request['start'], tz='UTC')) &
                  (pd.to_datetime(bars.availability_time, utc=True) <
                   pd.Timestamp(request['end'], tz='UTC') + pd.Timedelta(days=1)))
        rth_dates = self.starts[scored & (minute >= 570) & (minute < 960)].date
        self.last_scored_rth_date = max(rth_dates) if len(rth_dates) else None
        self.rth_date = None
        self.saw_rth_open = False
        self.entry_date = None

    def on_close(self, i, bar, state):
        start = self.starts[i]
        minute = start.hour * 60 + start.minute
        if 570 <= minute < 960:
            if start.date() != self.rth_date:
                self.rth_date = start.date()
                self.saw_rth_open = minute == 570
            elif minute == 570:
                self.saw_rth_open = True
        if not state['tradable']:
            return None

        if state['position']:
            if self.entry_date is None:
                raise ValueError('Overnight position has no entry RTH date')
            if i + 1 >= len(self.starts):
                return None
            upcoming = self.starts[i + 1]
            next_minute = upcoming.hour * 60 + upcoming.minute
            if upcoming.date() > self.entry_date and next_minute == 570:
                self.entry_date = None
                return {'target': 0, 'timing': 'next-open',
                        'expires_at': upcoming.isoformat(),
                        'reason': 'next-rth-open'}
            if upcoming.date() > self.entry_date and 570 < next_minute < 960:
                raise ValueError('Missing next RTH 09:30 ET exit quote')
            return None

        if ((start.hour, start.minute) == (15, 55) and self.saw_rth_open and
                start.date() != self.last_scored_rth_date):
            self.entry_date = start.date()
            return {'target': 1, 'timing': 'close',
                    'reason': 'unconditional-rth-overnight'}
        return None


def create_strategy(bars, parameters, request):
    validate(parameters, request)
    return UnconditionalOvernight(bars, request)
