"""Python port; see PINE_AUDIT.md for source coverage and simulator limits."""

STRATEGY = {'version': '1.0.0',
 'execution_model': 'event-v1',
 'default_session': 'full-trading-day',
 'required_session': 'full-trading-day',
 'capabilities': ['equity', 'trades', 'positions'],
 'id': 'pine-overnight-drift',
 'name': 'Pine · Filtered overnight drift',
 'timeframes': ['5m', '15m'],
 'default_warmup_days': 180,
 'pine_sources': ['pine/overnight_drift_strategy.pine'],
 'legacy_sources': ['scripts/overnight/overnight_drift_backtest.py'],
 'description': 'Use the completed RTH close filter and overnight volatility sizing. Fill at the '
                'close of the first outside-RTH bar and exit at the first RTH bar close.',
 'migration_scope': "Preserves actual Pine bar-close timing, which differs from the header's ideal "
                    'RTH-close/RTH-open trades. Uses selected-dataset daily prices and economics; '
                    'no TradingView margin-call simulation.',
 'parameters': {'sizing_mode': {'type': 'enum',
                                'default': 'Vol-targeted',
                                'choices': ['Vol-targeted', 'Fixed contracts']},
                'contracts': {'type': 'integer', 'default': 1, 'minimum': 1, 'maximum': 100},
                'annual_risk': {'type': 'number', 'default': 0.2, 'minimum': 0.001, 'maximum': 2},
                'maximum_leverage': {'type': 'number', 'default': 2, 'minimum': 0.1, 'maximum': 10},
                'volatility_length': {'type': 'integer',
                                      'default': 60,
                                      'minimum': 5,
                                      'maximum': 500},
                'sleeve_count': {'type': 'integer', 'default': 4, 'minimum': 1, 'maximum': 20},
                'timezone': {'type': 'enum',
                             'default': 'America/New_York',
                             'choices': ['America/New_York', 'America/Chicago', 'UTC']},
                'rth_start': {'type': 'integer',
                              'default': 570,
                              'minimum': 0,
                              'maximum': 1439,
                              'description': 'Minutes after midnight in the selected timezone '
                                             '(09:30 = 570, 16:00 = 960).'},
                'rth_end': {'type': 'integer',
                            'default': 960,
                            'minimum': 0,
                            'maximum': 1439,
                            'description': 'Minutes after midnight in the selected timezone (09:30 '
                                           '= 570, 16:00 = 960).'},
                'trade_weekend': {'type': 'boolean', 'default': False},
                'close_rule': {'type': 'enum',
                               'default': 'Long after up close',
                               'choices': ['Long after up close',
                                           'Long after down close',
                                           'Long up / short down',
                                           'Strong close only (long)',
                                           'Always (no filter)']},
                'strong_threshold': {'type': 'number', 'default': 0.6, 'minimum': 0, 'maximum': 1}}}


def validate(parameters, request):
    from strategies._pine_models import validate as check
    check(parameters, request)


def create_strategy(bars, parameters, request):
    from strategies._pine_models import OvernightDrift
    return OvernightDrift(bars, parameters, request)

