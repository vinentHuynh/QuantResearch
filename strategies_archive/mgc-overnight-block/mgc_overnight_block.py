"""Fixed long MGC 18:00–06:00 block from the local gold overnight study."""

STRATEGY = {
    'schema_version': 2,
    'source_files': ['strategies/mgc_overnight_block.py'],
    'id': 'mgc-overnight-block',
    'name': 'MGC overnight block 18:00–06:00',
    'version': '1.0.0',
    'execution_model': 'event-v1',
    'description': 'One MGC contract long from the first available 18:00-hour open '
                   'until the 05:55 bar close (06:00 New York), flat across the daily halt.',
    'timeframes': ['5m'],
    'default_session': 'full-trading-day',
    'required_session': 'full-trading-day',
    'default_warmup_days': 2,
    'capabilities': ['equity', 'trades', 'positions'],
    'legacy_sources': ['scripts/mgc/mgc_overnight_block_backtest.py'],
    'migration_scope': 'Ports only the pre-named long one-contract 18:00–06:00 MGC '
                       'clock block. A completed 16:55 bar schedules the first '
                       'available 18:00-hour open, and a completed 05:55 bar exits '
                       'at 06:00. Missing boundary quotes skip entry or fail a '
                       'held exit. The original study filters hour cells using '
                       'future bar counts; this causal adapter does not. Other '
                       'scanned windows, GC-rescaled history, and permutation '
                       'analyses are not ported. Workbench per-side costs, '
                       'continuous-roll levels, and absent instrument IDs limit '
                       'source ledger and executable-trade parity.',
    'parameters': {},
}


def validate(parameters, request):
    if (request['dataset']['symbol'] != 'MGC' or
            request['session'] != 'full-trading-day' or
            request['timeframe'] != '5m'):
        raise ValueError('MGC overnight block requires MGC five-minute full-trading-day bars')
    if (abs(request['dataset']['tick_size'] - 0.1) > 1e-9 or
            abs(request['dataset']['point_value'] - 10.) > 1e-9):
        raise ValueError('MGC overnight block requires 0.10 tick and $10/point economics')
    if request.get('delay_bars', 0):
        raise ValueError('Event-order delay is not supported for MGC overnight block')


class MGCOvernightBlock:
    def __init__(self, bars, request):
        import numpy as np
        import pandas as pd

        start = pd.Timestamp(request['start'], tz='UTC')
        end = pd.Timestamp(request['end'], tz='UTC') + pd.Timedelta(days=1)
        ready = pd.to_datetime(bars.availability_time, utc=True)
        scored = np.asarray((bars.index >= start) & (ready < end))
        indices = np.flatnonzero(scored)
        self.last_scored = int(indices[-1]) if len(indices) else -1
        self.holding_session = None

    def on_close(self, i, bar, state):
        import pandas as pd

        opening = pd.Timestamp(bar.name).tz_convert('America/New_York')
        ready = pd.Timestamp(bar.availability_time).tz_convert('America/New_York')
        if state['position']:
            session = str(bar.session_date)
            if self.holding_session is None:
                self.holding_session = session
            elif session != self.holding_session:
                raise ValueError('MGC overnight block carried past its scheduled 06:00 exit')
            if ready.hour == 6 and ready.minute == 0 and opening.hour == 5 and opening.minute == 55:
                self.holding_session = None
                return {'target': 0, 'timing': 'close', 'reason': '06:00-block-close'}
            if ((6 < ready.hour < 18) or (ready.hour == 6 and ready.minute > 0) or
                    i == self.last_scored):
                raise ValueError('Missing MGC 05:55 closing quote while holding')
            return None
        self.holding_session = None
        if not state['tradable']:
            return None
        if opening.hour == 16 and opening.minute == 55 and ready.hour == 17 and ready.minute == 0:
            from datetime import timedelta

            # The Friday 16:55 close arms Sunday's 18:00 reopen, but never
            # holds a position through the weekend seam. Build wall time in
            # New York so a DST-changing weekend does not shift the expiry.
            entry_date = opening.date() + timedelta(days=2 if opening.weekday() == 4 else 0)
            expiry = pd.Timestamp(entry_date.isoformat() + ' 18:59', tz='America/New_York')
            return {'target': 1, 'timing': 'next-open',
                    'expires_at': expiry.isoformat(),
                    'reason': '18:00-block-open'}
        return None


def create_strategy(bars, parameters, request):
    validate(parameters, request)
    return MGCOvernightBlock(bars, request)
