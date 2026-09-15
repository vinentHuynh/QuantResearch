"""Copy to strategies/my_strategy.py, change the id, then edit signals().

The workbench discovers the file automatically (within a few seconds).
No frontend or backend registry edits are required. Files starting with _ are
helpers/templates and are not registered. Use only trusted local Python here.

signals() returns desired signed WHOLE contracts at each completed bar.
The runner shifts these decisions to the NEXT bar open, marks equity at each
bar close, charges fees/slippage on every quantity change, and liquidates at
the final close. Positions carry across excluded session gaps (including
overnight). Never shift the signal yourself. Return zero during warmup.
Use trailing calculations only; no negative shifts or centered rolling windows.
Local helpers belong in strategies/ and are preserved in source snapshots.
"""

STRATEGY = {
    'id': 'my-strategy',
    'name': 'My strategy',
    'description': 'Replace with the mechanism and hypothesis being tested.',
    'version': '1.0.0',
    'timeframes': ['5m', '15m', '30m', '1h', '4h', '1d'],
    'capabilities': ['equity', 'trades', 'positions'],
    # Optional: paths of original scripts consolidated by this adapter. These
    # link the adapter from the auto-indexed Python library. State exactly which
    # rules were ported and how execution differs; a link is not a parity claim.
    'legacy_sources': [],
    'migration_scope': '',
    'default_warmup_days': 30,
    'parameters': {
        'lookback': {'type': 'integer', 'default': 20, 'minimum': 2, 'maximum': 500, 'description': 'Completed bars in the moving average.'},
        'contracts': {'type': 'integer', 'default': 1, 'minimum': 1, 'maximum': 100, 'description': 'Fixed whole contracts.'},
        'allow_short': {'type': 'boolean', 'default': False, 'description': 'Hold short below the moving average.'},
    },
}


def signals(bars, parameters):
    """bars: timezone-aware bar-open index; OHLCV + availability_time; warmup included."""
    import pandas as pd
    average = bars.close.rolling(parameters['lookback']).mean()
    target = pd.Series(0.0, index=bars.index)
    target.loc[bars.close > average] = parameters['contracts']
    if parameters['allow_short']:
        target.loc[bars.close < average] = -parameters['contracts']
    return target
