"""Python port; see PINE_AUDIT.md for source coverage and simulator limits."""

STRATEGY = {'version': '1.0.0',
 'execution_model': 'event-v1',
 'default_session': 'full-trading-day',
 'required_session': 'full-trading-day',
 'capabilities': ['equity', 'trades', 'positions'],
 'id': 'pine-overnight-block',
 'name': 'Pine · Overnight block',
 'timeframes': ['5m', '15m'],
 'pine_sources': ['pine/overnight_block_strategy.pine', 'pine/overnight_block_indicator.pine'],
 'legacy_sources': ['scripts/mnq/mnq_time_block_backtest.py',
                    'scripts/mnq/mnq_window_scan_backtest.py'],
 'description': 'Clock-window transition orders evaluated at the bar close, filled at the next '
                'open. Default 17:00 arming captures the 18:00 CME reopen.',
 'migration_scope': 'Ports the Pine clock/order rules, including boundary-only entries. Scoring '
                    'starts flat; no entry midway through an existing hold window. Costs and '
                    'contract economics use the run inputs.',
 'parameters': {'entry_hour': {'type': 'integer', 'default': 17, 'minimum': 0, 'maximum': 23},
                'entry_minute': {'type': 'integer', 'default': 0, 'minimum': 0, 'maximum': 59},
                'exit_hour': {'type': 'integer', 'default': 6, 'minimum': 0, 'maximum': 23},
                'exit_minute': {'type': 'integer', 'default': 0, 'minimum': 0, 'maximum': 59},
                'contracts': {'type': 'integer', 'default': 1, 'minimum': 1, 'maximum': 100},
                'timezone': {'type': 'enum',
                             'default': 'America/New_York',
                             'choices': ['America/New_York', 'America/Chicago', 'UTC']}}}


def validate(parameters, request):
    from strategies._pine_models import validate as check
    check(parameters, request)


def create_strategy(bars, parameters, request):
    from strategies._pine_models import OvernightBlock
    return OvernightBlock(bars, parameters, request)

