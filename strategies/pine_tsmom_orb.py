"""Python port; see PINE_AUDIT.md for source coverage and simulator limits."""

STRATEGY = {'schema_version': 2,
 'source_files': ['strategies/pine_tsmom_orb.py', 'strategies/_pine_models.py', 'strategies/_cme_index_calendar.py'],
 'version': '1.1.0',
 'execution_model': 'event-v1',
 'default_session': 'full-trading-day',
 'required_session': 'full-trading-day',
 'capabilities': ['equity', 'trades', 'positions'],
 'id': 'pine-tsmom-orb',
 'name': 'Pine · TSMOM intraday ORB',
 'timeframes': ['5m'],
 'default_warmup_days': 600,
 'pine_sources': ['pine/cme_tsmom_intraday_orb_strategy.pine'],
 'legacy_sources': ['scripts/cme/tsmom_intraday_orb_backtest.py'],
 'description': 'Daily direction-filtered ORB with signal-close entries, a dollar-risk budget, '
                'stop/target brackets, one attempt per session, and calendar-aware session exits.',
 'migration_scope': 'Pine rules port with one-minute bracket execution. Stop wins ties within a '
                    'minute; gap fills use the opening price. No TradingView sub-minute Bar '
                    'Magnifier or order-fill recalculation emulation. A rejected risk-sized '
                    'attempt still consumes the session. Version 1.1 uses the frozen NinjaTrader '
                    'CME US Index Futures ETH calendar (2016-2026): close at the earlier of the '
                    'normal flatten-start bar completion or five minutes before scheduled close; '
                    'no entries thereafter. Missing held exit quotes fail the replay instead of '
                    'creating overnight performance. Opening ranges reset every session. Calendar '
                    'is a current historical snapshot, not a point-in-time exchange archive; '
                    'NQ/MNQ scope only. Original pre-fix runs remain separate evidence.',
 'parameters': {'fast_length': {'type': 'integer', 'default': 20, 'minimum': 2, 'maximum': 500},
                'medium_length': {'type': 'integer', 'default': 60, 'minimum': 2, 'maximum': 500},
                'slow_length': {'type': 'integer', 'default': 120, 'minimum': 2, 'maximum': 500},
                'annual_length': {'type': 'integer', 'default': 252, 'minimum': 2, 'maximum': 500},
                'timezone': {'type': 'enum',
                             'default': 'America/New_York',
                             'choices': ['America/New_York', 'America/Chicago', 'UTC']},
                'minimum_score': {'type': 'number', 'default': 0.5, 'minimum': 0, 'maximum': 1},
                'opening_start': {'type': 'integer',
                                  'default': 570,
                                  'minimum': 0,
                                  'maximum': 1439,
                                  'description': 'Minutes after midnight in the selected timezone '
                                                 '(09:30 = 570, 16:00 = 960).'},
                'opening_end': {'type': 'integer',
                                'default': 585,
                                'minimum': 0,
                                'maximum': 1439,
                                'description': 'Minutes after midnight in the selected timezone '
                                               '(09:30 = 570, 16:00 = 960).'},
                'entry_start': {'type': 'integer',
                                'default': 585,
                                'minimum': 0,
                                'maximum': 1439,
                                'description': 'Minutes after midnight in the selected timezone '
                                               '(09:30 = 570, 16:00 = 960).'},
                'entry_end': {'type': 'integer',
                              'default': 900,
                              'minimum': 0,
                              'maximum': 1439,
                              'description': 'Minutes after midnight in the selected timezone '
                                             '(09:30 = 570, 16:00 = 960).'},
                'flatten_start': {'type': 'integer',
                                  'default': 945,
                                  'minimum': 0,
                                  'maximum': 1439,
                                  'description': 'Minutes after midnight in the selected timezone '
                                                 '(09:30 = 570, 16:00 = 960).'},
                'flatten_end': {'type': 'integer',
                                'default': 960,
                                'minimum': 0,
                                'maximum': 1439,
                                'description': 'Minutes after midnight in the selected timezone '
                                               '(09:30 = 570, 16:00 = 960).'},
                'risk_budget': {'type': 'number', 'default': 75, 'minimum': 1, 'maximum': 100000},
                'maximum_contracts': {'type': 'integer',
                                      'default': 20,
                                      'minimum': 1,
                                      'maximum': 20},
                'reward_risk': {'type': 'number', 'default': 2, 'minimum': 0.25, 'maximum': 20},
                'require_close_break': {'type': 'boolean', 'default': True},
                'execution_timing': {'type': 'enum', 'default': 'close', 'choices': ['close', 'next-open'],
                                     'description': 'Original close fills or explicit next-open execution stress for the NinjaTrader port; bracket levels remain signal-close based.'}}}


def validate(parameters, request):
    from strategies._pine_models import validate as check
    check(parameters, request)
    if request.get('dataset', {}).get('symbol') not in ('NQ', 'MNQ'):
        raise ValueError('Calendar-corrected TSMOM ORB currently supports NQ and MNQ only')


def create_strategy(bars, parameters, request):
    from strategies._pine_models import IntradayORB
    return IntradayORB(bars, parameters, request)

