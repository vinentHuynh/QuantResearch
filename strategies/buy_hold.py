"""Shared passive benchmark from the index and ETF strategy bakeoffs."""
STRATEGY = {
    'id': 'buy-hold', 'name': 'Buy and hold benchmark', 'version': '1.0.0',
    'description': 'Hold a fixed long position after the first completed bar; liquidate at the evaluation end.',
    'timeframes': ['5m', '15m', '30m', '1h', '4h', '1d'], 'capabilities': ['equity', 'trades', 'positions'],
    'legacy_sources': ['scripts/es_nq/es_nq_strategies.py', 'scripts/spy_qqq_intraday/intraday_bakeoff.py', 'scripts/spy_qqq_intraday/pdh_pdl_range_backtest.py'],
    'migration_scope': 'Consolidates the passive long benchmark only. Fixed futures contracts with explicit entry/exit costs replace the original proxy-return benchmark.',
    'parameters': {'contracts': {'type': 'integer', 'default': 1, 'minimum': 1, 'maximum': 100}},
}


def signals(bars, parameters):
    import pandas as pd
    return pd.Series(float(parameters['contracts']), index=bars.index)
