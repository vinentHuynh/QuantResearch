"""Additive RSI(2) experiment with explicit zero-gain/loss conventions."""

STRATEGY = {
    'id': 'rsi2-reversion-corrected',
    'name': 'RSI(2) reversion - corrected rebound exit',
    'version': '1.0.0',
    'description': 'Daily simple RSI(2) reversion above a trend average. An all-gain window has RSI 100, an all-loss window 0, and a flat window 50.',
    'timeframes': ['1d'],
    'capabilities': ['equity', 'trades', 'positions'],
    'default_warmup_days': 600,
    'warmup_bars': {'parameter': 'trend_lookback', 'offset': 1},
    'legacy_sources': ['scripts/es_nq/es_nq_strategies.py'],
    'migration_scope': 'Separate research variant of rsi2-reversion; the legacy adapter and its evidence remain unchanged. Retains simple rolling two-change RSI, strict entry/exit thresholds, long-only trend-filtered entries, fixed whole contracts and next-open fills. Defines RSI as 100 when gains are positive and losses zero, 0 for only losses, and 50 when both are zero. This changes rebound exits and may change later entries. Declared warmup conservatively requires trend_lookback+1 completed daily bars, including at least three closes for RSI. Warmup initializes decision state; scoring starts flat. No maximum holding period, stop, margin model, or continuous-contract roll correction.',
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


def simple_rsi2(close):
    """Two completed price changes; missing history stays uninitialized."""
    change = close.diff()
    gains = change.clip(lower=0).rolling(2).mean()
    losses = (-change.clip(upper=0)).rolling(2).mean()
    # Preserve the legacy arithmetic where the denominator is nonzero;
    # only the previously undefined all-gain and flat windows change.
    value = 100 - 100 / (1 + gains / losses.where(losses.ne(0)))
    value = value.mask(losses.eq(0) & gains.gt(0), 100.0)
    return value.mask(losses.eq(0) & gains.eq(0), 50.0)


def signals(bars, parameters):
    import numpy as np
    import pandas as pd

    close = bars.close
    rsi = simple_rsi2(close)
    average = close.rolling(parameters['trend_lookback']).mean()
    enter = rsi.lt(parameters['entry_rsi']) & close.gt(average)
    leave = rsi.gt(parameters['exit_rsi'])
    target = pd.Series(np.where(enter, 1.0, np.where(leave, 0.0, np.nan)), index=bars.index)
    return target.ffill().fillna(0.0) * parameters['contracts']
