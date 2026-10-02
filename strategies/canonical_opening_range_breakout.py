"""One-minute, single-market event port of the canonical opening-range rule.

The historical source is ``strategy_engine/strategies/opening_range_breakout.py``.
See the frozen mapping in artifacts/research/adapter-expansion-2026-10-01/.
"""

STRATEGY = {
    'schema_version': 2,
    'source_files': [
        'strategies/canonical_opening_range_breakout.py',
        'strategies/_cme_index_calendar.py',
    ],
    'id': 'canonical-opening-range-breakout',
    'name': 'Canonical opening-range breakout',
    'version': '1.0.0',
    'execution_model': 'event-v1',
    'description': 'First completed close outside the New York RTH opening range; one '
                   'fixed contract, range-sized stop/target, and scheduled session exit.',
    'timeframes': ['1m'],
    'default_session': 'new-york-rth',
    'required_session': 'new-york-rth',
    'default_warmup_days': 0,
    'capabilities': ['equity', 'trades', 'positions'],
    'legacy_sources': ['strategy_engine/strategies/opening_range_breakout.py'],
    'migration_scope': 'Ports the unfiltered single-market canonical ORB close-break, '
                       'range stop/target, first-break-only and same-session exit rules. '
                       'Requires a complete 09:30 opening window and a scheduled closing '
                       'quote; incomplete opening windows are skipped and a missing held '
                       'exit quote fails the run. Suppresses a terminal-bar break, whose '
                       'entry and exit would share one close in the source. One-minute '
                       'OHLC brackets use stop-first collisions and gap-open fills, unlike '
                       'the source\'s exact level fills; workbench fees/slippage and '
                       'continuous-futures rolls also differ. Uses a frozen 2016-2026 '
                       'index calendar snapshot, not a point-in-time exchange archive.',
    'parameters': {
        'opening_range_minutes': {
            'type': 'integer', 'default': 15, 'minimum': 5, 'maximum': 60,
            'description': 'Complete one-minute bars from the 09:30 New York RTH open.',
        },
        'stop_multiple': {
            'type': 'number', 'default': 1.0, 'minimum': 0.25, 'maximum': 8.0,
            'description': 'Stop distance in opening-range units.',
        },
        'target_multiple': {
            'type': 'number', 'default': 2.0, 'minimum': 0.25, 'maximum': 16.0,
            'description': 'Target distance in opening-range units.',
        },
    },
}


def validate(parameters, request):
    from strategies._cme_index_calendar import FIRST_YEAR, LAST_YEAR

    if request['session'] != 'new-york-rth' or request['timeframe'] != '1m':
        raise ValueError('Canonical ORB requires one-minute New York RTH bars')
    if request['dataset']['symbol'] not in ('ES', 'NQ', 'MNQ', 'YM'):
        raise ValueError('Canonical ORB calendar mapping supports ES, NQ, MNQ, and YM only')
    for name in ('start', 'end'):
        year = int(request[name][:4])
        if not FIRST_YEAR <= year <= LAST_YEAR:
            raise ValueError(f'Canonical ORB calendar only covers {FIRST_YEAR}-{LAST_YEAR}')
    if request.get('delay_bars', 0):
        raise ValueError('Event-order delay is not supported; use a separate timing adapter')


class CanonicalORB:
    def __init__(self, bars, parameters, request):
        import numpy as np
        import pandas as pd

        self.parameters = parameters
        self.tick = float(request['dataset']['tick_size'])
        start = pd.Timestamp(request['start'], tz='UTC')
        end = pd.Timestamp(request['end'], tz='UTC') + pd.Timedelta(days=1)
        ready = pd.to_datetime(bars.availability_time, utc=True)
        scored = np.asarray((bars.index >= start) & (ready < end))
        indices = np.flatnonzero(scored)
        self.last_scored = int(indices[-1]) if len(indices) else -1
        self.day = None
        self.range_end = None
        self.close_at = None
        self.open_complete = False
        self.open_count = 0
        self.open_high = float('-inf')
        self.open_low = float('inf')
        self.attempted = False

    def _new_day(self, bar, state):
        import pandas as pd
        from strategies._cme_index_calendar import session_close_et

        if state['position'] or state.get('position_at_open'):
            raise ValueError('Missing scheduled RTH exit quote while a canonical ORB position was held')
        self.day = str(bar.session_date)
        start = pd.Timestamp(bar.name).tz_convert('America/New_York')
        declared = session_close_et(self.day)
        rth_close = pd.Timestamp(self.day + ' 16:00', tz='America/New_York')
        self.close_at = min(declared, rth_close) if declared is not None else None
        self.range_end = start + pd.Timedelta(minutes=self.parameters['opening_range_minutes'])
        self.open_complete = start.hour == 9 and start.minute == 30
        self.open_count = 0
        self.open_high = float('-inf')
        self.open_low = float('inf')
        self.attempted = False

    def on_close(self, i, bar, state):
        import pandas as pd

        if str(bar.session_date) != self.day:
            self._new_day(bar, state)
        ready = pd.Timestamp(bar.availability_time).tz_convert('America/New_York')
        opening = pd.Timestamp(bar.name).tz_convert('America/New_York')
        if self.close_at is None or not self.open_complete:
            return None
        if i == self.last_scored and ready < self.close_at and state['position']:
            raise ValueError('Data ends before the scheduled RTH exit quote while holding')
        if ready >= self.close_at:
            if state['position']:
                if ready != self.close_at:
                    raise ValueError('Missing scheduled RTH exit quote while a canonical ORB position was held')
                return {'target': 0, 'timing': 'close', 'reason': 'scheduled-session-close'}
            return None
        if opening < self.range_end:
            # Complete one-minute opening observations are required before a
            # breakout can be trusted; missing minutes never shrink the range.
            self.open_count += 1
            self.open_high = max(self.open_high, float(bar.high))
            self.open_low = min(self.open_low, float(bar.low))
            return None
        if (self.open_count != self.parameters['opening_range_minutes'] or
                self.attempted or state['position']):
            return None
        price = float(bar.close)
        side = 1 if price > self.open_high else -1 if price < self.open_low else 0
        if not side:
            return None
        self.attempted = True
        if i == self.last_scored and ready < self.close_at:
            raise ValueError('Data ends before the scheduled RTH exit quote after an entry signal')
        if not state['tradable']:
            return None
        risk = max(self.open_high - self.open_low, self.tick)
        stop = price - side * risk * self.parameters['stop_multiple']
        target = price + side * risk * self.parameters['target_multiple']
        return {
            'target': side,
            'timing': 'close',
            'bracket': (stop, target),
            'reason': 'canonical-opening-range-break',
        }


def create_strategy(bars, parameters, request):
    validate(parameters, request)
    return CanonicalORB(bars, parameters, request)
