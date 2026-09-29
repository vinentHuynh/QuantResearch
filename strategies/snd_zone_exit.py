"""Exploratory SND opposing-zone exits, preserving the original entry model."""
STRATEGY = {
    'id': 'snd-zone-exit', 'name': 'SND - Opposing zone exit experiment', 'version': '1.0.0',
    'execution_model': 'event-v1', 'timeframes': ['1m'],
    'default_session': 'full-trading-day', 'required_session': 'full-trading-day',
    'default_warmup_days': 60, 'capabilities': ['equity', 'trades', 'positions'],
    'description': 'Compare baseline SND with opposing-zone touch or close-inside signals, exiting at the next minute open.',
    'migration_scope': 'Exploratory fixed-contract SND exit experiment. Original stops, targets, scheduled closes and entry rules retained. Zone exits inspect all active 1h/4h/daily opposing zones available at the start of the signal minute, before that minute invalidates zones. Touch includes crossing or gapping beyond the proximal edge; close-inside requires an inclusive close between proximal and distal. Exit fills next available minute open, never retrospectively at the zone price. No Pine percentage-risk sizing, margin liquidation or TradingView parity.',
    'parameters': {
        'variant': {'type': 'enum', 'default': 'phase7_prior_1m', 'choices': ['original_multi_tf', 'phase6', 'phase7_prior_1m', 'phase7_prior_5m']},
        'contracts': {'type': 'integer', 'default': 1, 'minimum': 1, 'maximum': 100},
        'zone_exit': {'type': 'enum', 'default': 'close-inside', 'choices': ['baseline', 'touch', 'close-inside']},
    },
}


def validate(parameters, request):
    from strategies.snd import validate as validate_snd
    validate_snd(parameters, request)


def create_strategy(bars, parameters, request):
    from strategies._snd_zone_exit import SNDZoneExit
    return SNDZoneExit(bars, parameters, request)
