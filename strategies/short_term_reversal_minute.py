"""Daily reversal signals with causal minute scheduling and overnight marks."""

STRATEGY = {
    'id': 'short-term-reversal-minute',
    'name': 'Short-term reversal - minute execution',
    'version': '1.0.0',
    'execution_model': 'event-v1',
    'description': 'Prior RTH selloff above a daily trend average; next-session minute-open execution, one-session hold and one mandatory flat session. Full trading-day minute equity.',
    'timeframes': ['1m'],
    'default_session': 'full-trading-day',
    'required_session': 'full-trading-day',
    'capabilities': ['equity', 'trades', 'positions'],
    'default_warmup_days': 600,
    'migration_scope': 'Same long-only daily signal as short-term-reversal v1.1 with trend filter, one-session hold and renewal disabled (one mandatory flat interval). Completed 09:30-16:00 New York RTH bars generate signals; partial current days never contribute. A completed minute at/after 09:30 plus the configured offset schedules a next-open fill. Late new entries are suppressed; entry orders expire after the lateness allowance, exit orders expire at that RTH close and are resubmitted at subsequent opening windows. Warmup never synthesizes a position. Full-trading-day minute marks include overnight but exclude 17:00-18:00 and weekends. Native warmup is undeclared because minute counts cannot prove daily initialization; the model separately requires sufficient completed pre-start RTH days. No authoritative holiday calendar, per-contract roll execution, intraminute stop/target, or margin model. Prior daily-shift failure remains unresolved; not an automatic status promotion.',
    'parameters': {
        'decline_pct': {'type': 'number', 'default': 1.25, 'minimum': 0.1, 'maximum': 10, 'description': 'Strictly greater completed RTH close-to-close decline, in percent.'},
        'trend_lookback': {'type': 'integer', 'default': 200, 'minimum': 2, 'maximum': 500, 'description': 'Completed RTH closes in the simple moving average.'},
        'open_delay_minutes': {'type': 'integer', 'default': 0, 'minimum': 0, 'maximum': 30, 'description': 'Scheduled entry AND exit minutes after 09:30 New York; fills use the next available minute open.'},
        'max_entry_lateness_minutes': {'type': 'integer', 'default': 5, 'minimum': 0, 'maximum': 30, 'description': 'Suppress a new long if its scheduling minute arrives later than this tolerance. Exits still flatten at the next available open. Future quote gaps remain an execution limitation.'},
        'contracts': {'type': 'integer', 'default': 1, 'minimum': 1, 'maximum': 100},
    },
}


def validate(parameters, request):
    if request['session'] != 'full-trading-day' or request['timeframe'] != '1m':
        raise ValueError('Use 1m full-trading-day bars for overnight equity marking')
    if request['warmup_days'] < parameters['trend_lookback'] * 3:
        raise ValueError('Use at least three calendar warmup days per daily trend observation; actual daily coverage still requires audit')


def completed_rth_days(bars):
    """Aggregate only sessions whose nominal 16:00 completion is already available."""
    import pandas as pd

    index = bars.index.tz_convert('America/New_York')
    minutes = index.hour * 60 + index.minute
    mask = (index.dayofweek < 5) & (minutes >= 570) & (minutes < 960)
    rth = bars.loc[mask, ['open', 'high', 'low', 'close']].copy()
    if rth.empty:
        return rth
    rth.index = index[mask]
    daily = rth.groupby(rth.index.normalize()).agg({'open':'first', 'high':'max', 'low':'min', 'close':'last'})
    daily.index = daily.index + pd.Timedelta(hours=9, minutes=30)
    daily['availability_time'] = daily.index + pd.Timedelta(hours=6, minutes=30)
    # A day partly loaded at the left boundary must not count as a complete day.
    left = index[0]
    daily = daily.loc[(daily.index >= left) & (daily.availability_time <= pd.Timestamp(bars.availability_time.iloc[-1]))]
    return daily


def schedule(bars, parameters):
    """Return causal scheduling updates for audit and for the signal runner."""
    import numpy as np
    import pandas as pd
    from strategies.short_term_reversal import STRATEGY as DAILY, signals as daily_signals
    from workbench.contract import resolve_parameters

    columns = ['decision_index', 'decision_time', 'signal_time', 'target', 'lateness_minutes']
    days = completed_rth_days(bars)
    if days.empty:
        return pd.DataFrame(columns=columns)
    p = resolve_parameters(DAILY, {'decline_pct':parameters['decline_pct'], 'trend_lookback':parameters['trend_lookback'],
                                  'confluence':'trend', 'hold_sessions':1, 'renew_on_signal':False,
                                  'exit_on_rebound':False, 'contracts':parameters['contracts']})
    decisions = daily_signals(days, p)
    ready = pd.DatetimeIndex(pd.to_datetime(bars.availability_time, utc=True)).tz_convert('America/New_York')
    minute = ready.hour * 60 + ready.minute
    due = 570 + parameters['open_delay_minutes']
    # Select the first COMPLETED minute at/after the deadline on each weekday.
    candidates = np.flatnonzero((ready.dayofweek < 5) & (minute >= due) & (minute < 960))
    if not len(candidates):
        return pd.DataFrame(columns=columns)
    dates = ready[candidates].normalize()
    candidates = candidates[~dates.duplicated()]
    known = pd.DatetimeIndex(days.availability_time)
    latest = known.searchsorted(ready[candidates], side='right') - 1
    rows=[]
    for position, source in zip(candidates, latest):
        lateness = int(minute[position]-due)
        target = int(decisions.iloc[source]) if source >= 0 else 0
        if lateness > parameters['max_entry_lateness_minutes']:
            target = 0
        rows.append({'decision_index':int(position),'decision_time':ready[position],
                     'signal_time':known[source] if source>=0 else pd.NaT,
                     'target':target,'lateness_minutes':lateness})
    return pd.DataFrame(rows, columns=columns)


def signals(bars, parameters):
    import pandas as pd
    target = pd.Series(float('nan'), index=bars.index)
    updates = schedule(bars, parameters)
    if not updates.empty:
        target.iloc[updates.decision_index.to_numpy(dtype=int)] = updates.target.to_numpy(dtype=float)
    return target.ffill().fillna(0.0)


class MinuteReversal:
    def __init__(self, bars, parameters):
        self.parameters = parameters
        self.updates = {int(r.decision_index):r for r in schedule(bars, parameters).itertuples()}

    def on_close(self, i, bar, state):
        import pandas as pd
        update = self.updates.get(i)
        if not state['tradable'] or update is None or update.target == state['position']:
            return None
        date = pd.Timestamp(update.decision_time).normalize()
        deadline = date + pd.Timedelta(minutes=570+self.parameters['open_delay_minutes']+self.parameters['max_entry_lateness_minutes']) if update.target else date+pd.Timedelta(hours=16)
        return {'target':int(update.target), 'timing':'next-open', 'expires_at':deadline.isoformat(),
                'reason':'scheduled-reversal-entry' if update.target else 'scheduled-reversal-exit'}


def create_strategy(bars, parameters, request):
    import pandas as pd
    days = completed_rth_days(bars)
    count = int((pd.to_datetime(days.availability_time, utc=True) < pd.Timestamp(request['start'], tz='UTC')).sum()) if not days.empty else 0
    required = parameters['trend_lookback'] + 1
    if count < required:
        raise ValueError(f'Daily RTH warmup insufficient: {count} completed days before scoring; {required} required')
    print(f'Validated daily RTH warmup: {count} completed days; {required} required', flush=True)
    return MinuteReversal(bars, parameters)
