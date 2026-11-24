"""Canonical four-speed trend decisions with workbench execution."""
STRATEGY = {
    'schema_version': 2,
    'source_files': ['strategies/multi_speed_momentum.py', 'strategies/_legacy_signals.py',
                     'strategy_engine/__init__.py', 'strategy_engine/catalog.py', 'strategy_engine/data.py',
                     'strategy_engine/sessions.py', 'workbench/__init__.py', 'workbench/dataset_reference.py'],
    'id': 'multi-speed-momentum', 'name': 'Multi-speed momentum', 'version': '1.2.0',
    'description': 'Four-speed momentum with next-open fills. One-hour NQ defaults to higher volatility with weaker price, or lower volatility with stronger price, at entry.',
    'timeframes': ['30m', '1h', '4h', '1d'], 'capabilities': ['equity', 'trades', 'positions'],
    'default_warmup_days': 600,
    'warmup_bars': {'parameter': 'lookback', 'multiplier': 4, 'offset': 1},
    'legacy_sources': ['scripts/cme/cme_time_series_momentum_backtest.py', 'strategy_engine/strategies/trend.py'],
    'migration_scope': 'Uses the canonical engine four-speed signal. Original CME proxy portfolio, lookbacks, volatility sizing, and NAV accounting are not reproduced.',
    'parameters': {
        'lookback': {'type': 'integer', 'default': 60, 'minimum': 2, 'maximum': 500, 'description': 'Other horizons are one-third, twice, and four times this many bars.'},
        'contracts': {'type': 'integer', 'default': 1, 'minimum': 1, 'maximum': 100},
        'nq_1h_regime_filter': {'type': 'boolean', 'default': True, 'description': 'Filter new NQ hourly entries using the prior calendar year’s medians. Turn off for original momentum entries.'},
    },
}


def validate(parameters, request):
    # The signals-v1 worker passes the run to preflight, then passes this same
    # resolved parameter copy to signals(). Saved parameters stay serializable.
    if (parameters['nq_1h_regime_filter'] and request['dataset']['symbol'] == 'NQ'
            and request['timeframe'] == '1h'):
        parameters['_regime_run'] = request


def _calibration_closes(bars, request):
    import pandas as pd
    from strategy_engine.data import session_bars
    from strategy_engine.sessions import get_session
    from workbench.dataset_reference import resolve_dataset_path

    # A late-year start or a short signal warmup can omit part of the prior
    # calendar year. Load that history only for classification, not for signals.
    start = pd.Timestamp(request['start'], tz='UTC')
    needed = pd.Timestamp(year=start.year - 2, month=12, day=1, tz='UTC')
    warmup_start = start - pd.Timedelta(days=request['warmup_days'])
    if warmup_start <= needed:
        return bars.close
    dataset = request['dataset']
    if request['protocol'] == 2:
        dataset = {**dataset, 'schema_version': 2}
    history = pd.read_parquet(resolve_dataset_path(dataset),
                              columns=['open', 'high', 'low', 'close'],
                              filters=[('ts_event', '>=', needed), ('ts_event', '<', warmup_start)])
    if history.empty:
        return bars.close
    prior = session_bars(history, get_session(request['session']), '1h').close
    return pd.concat([prior.loc[prior.index < bars.index[0]], bars.close])


def _eligible_at_decision(close, availability):
    import pandas as pd

    features = pd.DataFrame({
        'volatility': close.pct_change(fill_method=None).rolling(20).std(),
        'strength': close / close.rolling(20).mean() - 1,
    })
    years = close.index.tz_convert('UTC').year
    # Assign each historical observation to the open where it was known,
    # including the first bar after the New Year closure.
    medians = features.shift(1).groupby(years).median()
    next_year = pd.Series(years, index=close.index).shift(-1).reindex(availability.index)
    next_year = next_year.fillna(pd.to_datetime(availability, utc=True).dt.year)
    thresholds = medians.reindex(next_year.to_numpy(dtype=int) - 1)
    thresholds.index = availability.index
    current = features.loc[availability.index]
    higher_vol = current.volatility > thresholds.volatility
    stronger_price = current.strength > thresholds.strength
    return current.notna().all(axis=1) & thresholds.notna().all(axis=1) & (higher_vol != stronger_price)


def signals(bars, parameters):
    import pandas as pd
    from strategies._legacy_signals import momentum

    target = momentum(bars.close, parameters['lookback']) * parameters['contracts']
    request = parameters.get('_regime_run')
    if request is None or bars.empty:
        return target
    eligible = _eligible_at_decision(_calibration_closes(bars, request), bars.availability_time)
    new_leg = target.ne(target.shift())
    # The engine starts flat even if the signal was already long/short during
    # warmup. Test that first entry independently. Delay stress shifts orders.
    start = pd.Timestamp(request['start'], tz='UTC')
    first_decision = bars.index.searchsorted(start) - 1 - request.get('delay_bars', 0)
    if first_decision >= 0:
        new_leg.iloc[first_decision] = True
    accepted = eligible.astype('boolean').where(new_leg).ffill().fillna(False)
    return target.where(accepted, 0)
