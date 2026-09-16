"""Native workbench adapter for the source-derived SND research variants."""

STRATEGY = {
    'id': 'snd', 'name': 'SND - Supply and demand', 'version': '1.0.0',
    'execution_model': 'event-v1', 'timeframes': ['1m'],
    'default_session': 'full-trading-day', 'required_session': 'full-trading-day',
    'default_warmup_days': 60, 'capabilities': ['equity', 'trades', 'positions'],
    'description': 'SND zone retests: original multi-timeframe, Phase 6, or Phase 7 first-touch RVOL. One-minute execution with internally completed 1h, 4h and daily zones.',
    'legacy_sources': ['scripts/mnq/SND_baseline_backtest.py', 'scripts/mnq/SND_phase4_backtest.py', 'scripts/mnq/SND_phase7_relative_volume.py'],
    'pine_sources': ['SND.pine', 'SND_phase6_strategy.pine'],
    'migration_scope': 'Source-derived next-open research adapter, not certified Pine parity. Fixed contracts; original 100/200/400 PRICE POINT targets, 100-point stop cap and 1-point distal buffer retained on every market. Phase 6/7 require first physical touch and 2 structural R opposing room; Phase 7 freezes prior completed-bar RVOL at first touch (20 slot observations, minimum 10, band 0.75 <= RVOL < 1.25). Warmup consumes eligible zone tests without positions. Workbench session filtering, flat start, final liquidation and commission-only limit exits differ from the standalone research ledger. No Pine percent-risk sizing or touch-price entries.',
    'parameters': {
        'variant': {'type': 'enum', 'default': 'phase7_prior_5m', 'choices': ['original_multi_tf', 'phase6', 'phase7_prior_1m', 'phase7_prior_5m']},
        'contracts': {'type': 'integer', 'default': 1, 'minimum': 1, 'maximum': 100},
    },
}


def validate(parameters, request):
    if request['session'] != 'full-trading-day' or request['timeframe'] != '1m':
        raise ValueError('SND requires the full-trading-day session and 1m execution chart')
    if request.get('delay_bars', 0):
        raise ValueError('SND does not support additional execution delay')
    if parameters['variant'].startswith('phase7') and request['warmup_days'] < 30:
        raise ValueError('SND Phase 7 requires at least 30 calendar days of RVOL warmup')


def create_strategy(bars, parameters, request):
    from strategies._snd_model import SND
    return SND(bars, parameters, request)
