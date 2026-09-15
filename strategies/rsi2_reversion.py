"""Consolidated RSI(2) signal from the ES/NQ strategy bakeoff."""
STRATEGY = {
    'id': 'rsi2-reversion', 'name': 'RSI(2) trend-filtered reversion', 'version': '1.0.0',
    'description': 'Long when simple RSI(2) is below the entry threshold and price is above its moving average; exit above the RSI exit threshold.',
    'timeframes': ['1d'], 'capabilities': ['equity', 'trades', 'positions'],
    'default_warmup_days': 400,
    'legacy_sources': ['scripts/es_nq/es_nq_strategies.py'],
    'migration_scope': 'Ports s_rsi2 decisions, including its zero-loss RSI convention. Uses selected futures, fixed whole contracts and next-open fills; original cash-index NAV differs.',
    'parameters': {
        'trend_lookback': {'type': 'integer', 'default': 200, 'minimum': 2, 'maximum': 500},
        'entry_rsi': {'type': 'number', 'default': 10, 'minimum': 0, 'maximum': 100},
        'exit_rsi': {'type': 'number', 'default': 70, 'minimum': 0, 'maximum': 100},
        'contracts': {'type': 'integer', 'default': 1, 'minimum': 1, 'maximum': 100},
    },
}


def validate(parameters, request):
    if parameters['entry_rsi'] >= parameters['exit_rsi']:
        raise ValueError('entry_rsi must be below exit_rsi')
    if request['warmup_days'] < parameters['trend_lookback'] * 2:
        raise ValueError('Use at least twice trend_lookback in warmup days for daily indicators')


def signals(bars, parameters):
    from strategies._legacy_signals import rsi_reversion
    return rsi_reversion(bars.close, parameters['trend_lookback'], parameters['entry_rsi'], parameters['exit_rsi']) * parameters['contracts']
