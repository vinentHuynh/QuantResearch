"""Python port; see PINE_AUDIT.md for source coverage and simulator limits."""

STRATEGY = {'version': '1.0.0',
 'execution_model': 'event-v1',
 'default_session': 'full-trading-day',
 'required_session': 'full-trading-day',
 'capabilities': ['equity', 'trades', 'positions'],
 'id': 'pine-daily-tsmom',
 'name': 'Pine · Daily TSMOM rebalance',
 'timeframes': ['15m'],
 'default_warmup_days': 600,
 'pine_sources': ['pine/cme_tsmom_single_market_strategy.pine'],
 'legacy_sources': ['scripts/cme/cme_time_series_momentum_backtest.py'],
 'description': 'Completed daily 20/60/120/252 votes, point-volatility sizing, and a rebalance at '
                'the first 15-minute close of each Globex session.',
 'migration_scope': 'Historical Pine decision/timing port. Daily bars and signal use the selected '
                    'futures dataset, not a separate signal symbol or TradingView settlement feed. '
                    'Whole contracts; no TradingView margin-call emulation. Live request.security '
                    'repaint behavior is not reproduced.',
 'parameters': {'fast_length': {'type': 'integer', 'default': 20, 'minimum': 2, 'maximum': 500},
                'medium_length': {'type': 'integer', 'default': 60, 'minimum': 2, 'maximum': 500},
                'slow_length': {'type': 'integer', 'default': 120, 'minimum': 2, 'maximum': 500},
                'annual_length': {'type': 'integer', 'default': 252, 'minimum': 2, 'maximum': 500},
                'sizing_mode': {'type': 'enum',
                                'default': 'Vol-targeted',
                                'choices': ['Vol-targeted', 'Fixed contracts']},
                'contracts': {'type': 'integer', 'default': 1, 'minimum': 1, 'maximum': 100},
                'annual_risk': {'type': 'number', 'default': 0.2, 'minimum': 0.001, 'maximum': 2},
                'maximum_leverage': {'type': 'number', 'default': 2, 'minimum': 0.1, 'maximum': 10},
                'volatility_length': {'type': 'integer',
                                      'default': 60,
                                      'minimum': 5,
                                      'maximum': 500},
                'sleeve_count': {'type': 'integer', 'default': 1, 'minimum': 1, 'maximum': 20},
                'rounding': {'type': 'enum', 'default': 'Nearest', 'choices': ['Nearest', 'Down']}}}


def validate(parameters, request):
    from strategies._pine_models import validate as check
    check(parameters, request)


def create_strategy(bars, parameters, request):
    from strategies._pine_models import DailyTrend
    return DailyTrend(bars, parameters, request)

