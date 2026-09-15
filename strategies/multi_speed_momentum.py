"""Canonical four-speed trend decisions with workbench execution."""
STRATEGY = {
    'id': 'multi-speed-momentum', 'name': 'Multi-speed momentum', 'version': '1.0.0',
    'description': 'Long/short consensus of four completed-bar momentum horizons. Fixed contracts and next-open fills.',
    'timeframes': ['30m', '1h', '4h', '1d'], 'capabilities': ['equity', 'trades', 'positions'],
    'legacy_sources': ['scripts/cme/cme_time_series_momentum_backtest.py', 'strategy_engine/strategies/trend.py'],
    'migration_scope': 'Uses the canonical engine four-speed signal. Original CME proxy portfolio, lookbacks, volatility sizing, and NAV accounting are not reproduced.',
    'parameters': {
        'lookback': {'type': 'integer', 'default': 60, 'minimum': 2, 'maximum': 500, 'description': 'Other horizons are one-third, twice, and four times this many bars.'},
        'contracts': {'type': 'integer', 'default': 1, 'minimum': 1, 'maximum': 100},
    },
}


def signals(bars, parameters):
    from strategies._legacy_signals import momentum
    return momentum(bars.close, parameters['lookback']) * parameters['contracts']
