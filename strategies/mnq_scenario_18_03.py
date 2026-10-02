"""Fixed MNQ 18:00-to-03:00 arm from the historical clock-scenario grid."""

from collections import defaultdict

import pandas as pd


STRATEGY = {
    'schema_version': 2,
    'source_files': ['strategies/mnq_scenario_18_03.py'],
    'id': 'mnq-scenario-18-03',
    'name': 'MNQ · 18:00–03:00 clock scenario',
    'version': '1.0.0',
    'execution_model': 'event-v1',
    'description': 'One MNQ contract from the first 18:xx bar open to the last '
                   '02:xx bar close, with the source grid’s six-bars-per-hour gate.',
    'timeframes': ['5m'],
    'default_session': 'full-trading-day',
    'required_session': 'full-trading-day',
    'default_warmup_days': 1,
    'capabilities': ['equity', 'trades', 'positions'],
    'legacy_sources': ['scripts/mnq/mnq_scenario_grid.py'],
    'migration_scope': 'Ports only the fixed 18:00–03:00 row of a 13-scenario '
                       'historical grid. The six-bars-per-hour inclusion gate uses '
                       'future bar availability timestamps and is retrospective, '
                       'not a live causal filter. Uses one MNQ contract and Workbench '
                       'costs. The NQ notional-rescaled era, other clock rows, '
                       'source-ledger parity, rolls and executable fills are not certified.',
    'parameters': {},
}


def validate(parameters, request):
    if request['dataset']['symbol'] != 'MNQ':
        raise ValueError('The fixed grid arm trades MNQ; NQ notional scaling is not ported')
    if request['session'] != 'full-trading-day' or request['timeframe'] != '5m':
        raise ValueError('Use five-minute full-trading-day MNQ bars')
    if request.get('delay_bars', 0):
        raise ValueError('Event-order delay bars are not supported')


class Scenario1803:
    def __init__(self, bars):
        self.starts = pd.DatetimeIndex(bars.index).tz_convert('America/New_York')
        session = (self.starts - pd.Timedelta(hours=18)).normalize()
        cells = defaultdict(list)
        for i, (key, start) in enumerate(zip(session, self.starts)):
            if start.hour in (18, 2):
                cells[(key, start.hour)].append(i)
        self.entries = set()
        self.exits = set()
        for key, hour in cells:
            if hour != 18:
                continue
            entry, exit_ = cells[(key, 18)], cells.get((key, 2), ())
            if len(entry) >= 6 and len(exit_) >= 6:
                self.entries.add(entry[0])
                self.exits.add(exit_[-1])

    def on_close(self, i, bar, state):
        if not state['tradable']:
            return None
        if state['position'] and i in self.exits:
            return {'target': 0, 'timing': 'close', 'reason': 'last-02-hour-bar-close'}
        if not state['position'] and i + 1 in self.entries:
            return {'target': 1, 'timing': 'next-open',
                    'expires_at': self.starts[i + 1].isoformat(),
                    'reason': 'first-18-hour-bar-open'}
        return None


def create_strategy(bars, parameters, request):
    validate(parameters, request)
    return Scenario1803(bars)
