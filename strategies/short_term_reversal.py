"""Daily reversal built from the workbench fixed-contract benchmark template."""

STRATEGY = {
    'schema_version': 2,
    'source_files': ['strategies/short_term_reversal.py'],
    'id': 'short-term-reversal',
    'name': 'Short-term reversal - prior-day selloff',
    'description': 'Buy the next open after a configurable daily selloff. Optional trend, close-location, shock-size and volatility filters; bounded holding period and rebound exit.',
    'version': '1.1.0',
    'timeframes': ['1d'],
    'capabilities': ['equity', 'trades', 'positions'],
    'default_session': 'new-york-rth',
    'required_session': 'new-york-rth',
    'default_warmup_days': 600,
    'warmup_bars': {'parameter': 'trend_lookback', 'offset': 1},
    'migration_scope': 'Benchmark-template fixed-contract model. RTH close-to-close signal fills next RTH open. Holding sessions count open-to-open intervals; optional fresh signals reset the holding clock, and a favorable close-to-close day can schedule an early next-open exit. ATR is the simple mean of true ranges through the PREVIOUS session, not including the signal shock. Maximum decline filters entries, not open-position losses. No intraday stop/target; overnight/weekend exposure, continuous roll gaps, daily-close drawdown, and final-close liquidation remain material limitations.',
    'parameters': {
        'decline_pct': {'type': 'number', 'default': 1.0, 'minimum': 0.1, 'maximum': 10, 'description': 'Strictly greater daily decline in percent; 1 means close-to-close return below -1%.'},
        'confluence': {'type': 'enum', 'default': 'trend', 'choices': ['none', 'weak-close', 'trend', 'trend-and-weak-close'], 'description': 'Optional weak close and/or price above the trailing trend average.'},
        'trend_lookback': {'type': 'integer', 'default': 200, 'minimum': 2, 'maximum': 500, 'description': 'Daily closes in the trend SMA; also the common initialization requirement for every variant.'},
        'close_fraction': {'type': 'number', 'default': 0.25, 'minimum': 0.05, 'maximum': 0.5, 'description': 'Weak close: bottom fraction of daily range; short symmetry uses the top fraction.'},
        'direction': {'type': 'enum', 'default': 'long-only', 'choices': ['long-only', 'long-short'], 'description': 'Optional symmetric short after a large up day, with strong close and below-trend filters as selected.'},
        'max_decline_pct': {'type': 'number', 'default': 0, 'minimum': 0, 'maximum': 30, 'description': 'Skip new entries after moves larger than this percent; 0 disables. Not a stop loss. Symmetric for shorts.'},
        'hold_sessions': {'type': 'integer', 'default': 1, 'minimum': 1, 'maximum': 10, 'description': 'Open-to-open holding intervals before exit; final sample bar liquidates at its close.'},
        'renew_on_signal': {'type': 'boolean', 'default': True, 'description': 'A new same-direction signal resets the holding clock; disabling imposes a hard holding limit.'},
        'exit_on_rebound': {'type': 'boolean', 'default': False, 'description': 'Exit next open after a favorable close-to-close day (up for long, down for short), before the holding limit.'},
        'min_atr_multiple': {'type': 'number', 'default': 0, 'minimum': 0, 'maximum': 5, 'description': 'Require the close-to-close move to exceed this multiple of prior-session ATR; 0 disables.'},
        'atr_period': {'type': 'integer', 'default': 20, 'minimum': 2, 'maximum': 100, 'description': 'Prior completed daily true ranges in simple ATR. Must be below trend_lookback when the ATR filter is enabled.'},
        'contracts': {'type': 'integer', 'default': 1, 'minimum': 1, 'maximum': 100},
    },
}


def validate(parameters, request):
    cap = parameters['max_decline_pct']
    if cap and cap <= parameters['decline_pct']:
        raise ValueError('max_decline_pct must be 0 (disabled) or greater than decline_pct')
    if parameters['min_atr_multiple'] and parameters['atr_period'] >= parameters['trend_lookback']:
        raise ValueError('ATR filter requires atr_period below trend_lookback for declared warmup coverage')


def signals(bars, parameters):
    import pandas as pd

    close = bars.close
    previous = close.shift(1)
    average = close.rolling(parameters['trend_lookback']).mean()
    day_range = bars.high - bars.low
    location = (close - bars.low) / day_range.where(day_range > 0)
    initialized = average.notna() & previous.gt(0) & close.gt(0)
    # Compare price changes directly to avoid cancellation at exact thresholds.
    threshold = previous * (parameters['decline_pct'] / 100)
    long = initialized & (previous - close).gt(threshold)
    short = initialized & (close - previous).gt(threshold)
    cap = parameters['max_decline_pct']
    if cap:
        within_cap = (close - previous).abs().le(previous * cap / 100)
        long &= within_cap
        short &= within_cap
    if parameters['min_atr_multiple']:
        true_range = pd.concat([day_range, (bars.high - previous).abs(), (bars.low - previous).abs()], axis=1).max(axis=1)
        prior_atr = true_range.rolling(parameters['atr_period']).mean().shift(1)
        large_move = prior_atr.gt(0) & (close - previous).abs().gt(prior_atr * parameters['min_atr_multiple'])
        long &= large_move
        short &= large_move
    mode = parameters['confluence']
    if mode in ('trend', 'trend-and-weak-close'):
        long &= close.gt(average)
        short &= close.lt(average)
    if mode in ('weak-close', 'trend-and-weak-close'):
        long &= location.le(parameters['close_fraction'])
        short &= location.ge(1 - parameters['close_fraction'])
    entry = pd.Series(0, index=bars.index)
    entry.loc[long] = 1
    if parameters['direction'] == 'long-short':
        entry.loc[short] = -1
    target = pd.Series(0.0, index=bars.index)
    side, remaining = 0, 0
    change = close - previous
    for i, signal in enumerate(entry.to_numpy()):
        expired = False
        if side:
            remaining -= 1
            rebound = parameters['exit_on_rebound'] and side * change.iloc[i] > 0
            if rebound:
                side, remaining, expired = 0, 0, True
            elif signal == side and parameters['renew_on_signal']:
                remaining = parameters['hold_sessions']
            elif remaining <= 0:
                side, remaining = 0, 0
                expired = not parameters['renew_on_signal']
        # A hard-limit/rebound exit always produces a flat target for one interval.
        # Opposite signals cannot reverse an existing position before its exit.
        if not side and not expired and signal:
            side, remaining = int(signal), parameters['hold_sessions']
        target.iloc[i] = side * parameters['contracts']
    return target
