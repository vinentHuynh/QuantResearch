"""Adapter for the repository's canonical moving-average signal calculation."""

STRATEGY = {
    'id': 'moving-average',
    'name': 'Moving-average trend',
    'description': 'Existing canonical long/flat trend signal, with next-bar-open fills and fixed whole contracts.',
    'version': '1.0.0',
    'timeframes': ['5m', '15m', '30m', '1h', '4h', '1d'],
    'capabilities': ['equity', 'trades', 'positions'],
    'legacy_sources': ['scripts/es_nq/es_nq_backtest.py', 'scripts/es_nq/es_nq_strategies.py', 'strategy_engine/strategies/trend.py'],
    'migration_scope': 'Consolidates long/flat moving-average decisions. Original cash-index portfolios and notional-return accounting are not reproduced.',
    'parameters': {
        'lookback': {'type': 'integer', 'default': 20, 'minimum': 2, 'maximum': 500, 'description': 'Completed bars in the moving average.'},
        'contracts': {'type': 'integer', 'default': 1, 'minimum': 1, 'maximum': 100, 'description': 'Fixed whole contracts; no leverage targeting.'},
    },
}


def signals(bars, parameters):
    from strategy_engine.strategies.trend import TrendConfig, run
    from strategy_engine.strategies.relative_value import LegEconomics
    import pandas as pd
    _, decisions, _ = run(bars, symbol='SIGNAL', economics=LegEconomics(0.25, 1),
                         config=TrendConfig('moving-average-trend', lookback=parameters['lookback']))
    values = pd.Series(0.0, index=pd.to_datetime(bars.availability_time, utc=True))
    if not decisions.empty:
        levels = decisions.set_index(pd.to_datetime(decisions.event_time, utc=True)).level
        values = (levels.reindex(values.index).fillna(0) > 0).astype(float) * parameters['contracts']
    return pd.Series(values.to_numpy(), index=bars.index)
