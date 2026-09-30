"""Causal fixed-clock implementation of Gao/Baltussen closing-window momentum."""

STRATEGY = {
    'schema_version': 2,
    'source_files': ['strategies/market_intraday_momentum.py'],
    'id': 'market-intraday-momentum',
    'name': 'Market intraday momentum - last 30 minutes',
    'version': '1.0.1',
    'execution_model': 'event-v1',
    'description': 'Trade the final 30 minutes in the direction of the return since the previous close. Includes Baltussen rest-of-day and Gao first-half-hour signals; long and short, flat at the configured close.',
    'timeframes': ['1m', '5m'],
    'default_session': 'new-york-rth',
    'required_session': 'new-york-rth',
    'default_warmup_days': 10,
    'capabilities': ['equity', 'trades', 'positions'],
    'migration_scope': 'Research adaptation, not paper replication. New York fixed clock: equity close 16:00, CL close 14:30; Gao observation at 10:00 (CL 09:30 open is an explicit adaptation). Signal includes overnight return. Completed signal bar schedules an exact-time next-open entry with expiry; scheduled close-price exit pays fees/slippage. Delay preserves the original signal. No gamma observations, volatility selection, auction/settlement execution, holiday/early-close calendar, roll-neutral prices, or margin model. Missing signal/entry quotes skip entry; missing exit quotes fail the run instead of silently carrying overnight. Stale prior closes older than four calendar days and nonpositive prices suppress entry. Five-minute bars use nominal completion and may contain missing underlying minutes; compare 1m execution checks. Fixed clocks on early-close days are not exchange-calendar replication.',
    'parameters': {
        'signal_mode': {'type': 'enum', 'default': 'rest-of-day', 'choices': ['rest-of-day', 'first-half-hour'], 'description': 'Baltussen: prior close to entry decision; Gao: prior close to 10:00 New York.'},
        'close_time': {'type': 'enum', 'default': '16:00', 'choices': ['16:00', '14:30'], 'description': '16:00 for equity index futures; 14:30 for CL. New York local clock, DST aware.'},
        'holding_minutes': {'type': 'enum', 'default': '30', 'choices': ['25', '30', '35'], 'description': 'Scheduled window before close; neighbors are sensitivity tests.'},
        'entry_delay_minutes': {'type': 'enum', 'default': '0', 'choices': ['0', '5'], 'description': 'Execution stress: delay entry five minutes while retaining the original signal.'},
        'minimum_move_bps': {'type': 'number', 'default': 0, 'minimum': 0, 'maximum': 500, 'description': 'Strict absolute signal threshold in basis points. Zero trades every nonzero eligible signal.'},
        'contracts': {'type': 'integer', 'default': 1, 'minimum': 1, 'maximum': 100},
    },
}


def validate(parameters, request):
    if request['session'] != 'new-york-rth' or request['timeframe'] not in STRATEGY['timeframes']:
        raise ValueError('Use 1m or 5m new-york-rth bars')
    symbol = request['dataset']['symbol']
    expected = '14:30' if symbol == 'CL' else '16:00'
    if symbol not in ('ES', 'MES', 'NQ', 'MNQ', 'YM', 'CL'):
        raise ValueError('Market clock is not specified for this symbol')
    if parameters['close_time'] != expected:
        raise ValueError(f'{symbol} requires close_time={expected}')


class IntradayMomentum:
    def __init__(self, bars, parameters):
        import pandas as pd
        self.p = parameters
        ready = pd.DatetimeIndex(pd.to_datetime(bars.availability_time, utc=True)).tz_convert('America/New_York')
        self.ready = ready
        self.last_index = len(bars)-1
        self.dates = ready.date
        self.minutes = ready.hour * 60 + ready.minute
        hour, minute = map(int, parameters['close_time'].split(':'))
        self.close_minute = hour * 60 + minute
        self.signal_minute = self.close_minute - int(parameters['holding_minutes'])
        self.entry_minute = self.signal_minute + int(parameters['entry_delay_minutes'])
        self.day = self.prior_date = None
        self.prior_close = None
        self.signal = None
        self.signal_return = None
        self.attempted = False

    def on_close(self, i, bar, state):
        date, minute = self.dates[i], int(self.minutes[i])
        if state['position'] and (self.day != date or minute > self.close_minute):
            raise ValueError('Missing scheduled closing quote while holding: cannot certify intraday exit')
        if state['position'] and i == self.last_index and minute < self.close_minute:
            raise ValueError('Data ends before scheduled closing quote while holding')
        if date != self.day:
            self.day, self.signal, self.signal_return, self.attempted = date, None, None, False
        if minute == self.close_minute:
            self.prior_close, self.prior_date = float(bar.close), date
            if state['tradable'] and state['position']:
                return {'target': 0, 'timing': 'close', 'reason': 'scheduled-market-close'}
            return None
        observation = self.signal_minute if self.p['signal_mode'] == 'rest-of-day' else 600
        if minute == observation:
            if (self.prior_close is not None and self.prior_close > 0 and bar.close > 0
                    and 0 < (date - self.prior_date).days <= 4):
                self.signal_return = float(bar.close) / self.prior_close - 1
                if abs(self.signal_return) * 10000 > self.p['minimum_move_bps']:
                    self.signal = self.p['contracts'] * (1 if self.signal_return > 0 else -1)
        if (state['tradable'] and not state['position'] and not self.attempted
                and minute == self.entry_minute and self.signal is not None):
            self.attempted = True
            return {'target': self.signal, 'timing': 'next-open',
                    'expires_at': self.ready[i].isoformat(), 'reason': 'closing-momentum-entry'}
        return None


def create_strategy(bars, parameters, request):
    validate(parameters, request)
    return IntradayMomentum(bars, parameters)
