"""Session VWAP decision state from the ETF intraday bakeoff."""
STRATEGY = {
    'id': 'vwap-reversion', 'name': 'Session VWAP reversion', 'version': '1.0.0',
    'description': 'Fade deviations from cumulative session VWAP; return to flat when price crosses VWAP. Decision state resets each session.',
    'timeframes': ['5m', '15m', '30m'], 'capabilities': ['equity', 'trades', 'positions'],
    'legacy_sources': ['scripts/spy_qqq_intraday/intraday_bakeoff.py'],
    'migration_scope': 'Ports s_vwap_rev decision state. Uses selected futures and next-open accounting; positions can carry across excluded-session gaps until the next available fill. Original ETF session returns differ.',
    'parameters': {
        'band': {'type': 'number', 'default': 0.002, 'minimum': 0.00001, 'maximum': 0.1, 'description': 'Fractional deviation from VWAP (0.002 = 0.2%).'},
        'contracts': {'type': 'integer', 'default': 1, 'minimum': 1, 'maximum': 100},
    },
}


def signals(bars, parameters):
    from strategies._legacy_signals import vwap_reversion
    return vwap_reversion(bars, parameters['band']) * parameters['contracts']
