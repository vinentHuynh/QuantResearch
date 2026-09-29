"""Convert numeric-kernel output to the exact public reference frame schemas."""
from __future__ import annotations

import numpy as np
import pandas as pd

from strategies._snd_combination_reference import TRADE_COLUMNS


TIME_COLUMNS = ("entry_time", "exit_time", "zone_time", "first_touch_time",
                "signal_time", "order_expiry_time")
FLOAT_COLUMNS = tuple(name for name in TRADE_COLUMNS
                      if name not in TIME_COLUMNS + ("exit_reason", "eligibility_policy"))
REASONS = ("stop", "target", "contract-roll", "end-of-test")
INTEGER_COLUMNS = ("side", "quantity", "execution_minutes", "lifetime_bars")
BOOLEAN_COLUMNS = ("ambiguous_entry", "ambiguous_exit", "entry_bar_target_ignored")
EQUITY_VALUE_COLUMNS = ("equity", "balance", "unrealized_pnl", "net_pnl", "contracts")
EQUITY_COLUMNS = ("timestamp", *EQUITY_VALUE_COLUMNS)


def frames_from_arrays(trade_values, trade_times, trade_reasons,
                       equity_values, equity_times, parameters):
    """Build frames without routing nanosecond timestamps through floating point.

    The kernel returns lists (including Numba lists) of per-trade arrays and
    pretrimmed equity arrays. Empty frames retain the reference's all-object
    schema; populated integer, bool and UTC nanosecond columns are explicit.
    Missing opposing boundaries remain float NaN, as in the reference engine.
    """
    size = len(trade_values)
    if len(trade_times) != size or len(trade_reasons) != size:
        raise ValueError("Trade values, times and reasons have different lengths")
    if size:
        values = np.asarray(list(trade_values), dtype=np.float64)
        times = np.asarray(list(trade_times), dtype=np.int64)
        reasons = np.asarray(list(trade_reasons), dtype=np.int64)
        if values.shape != (size, len(FLOAT_COLUMNS)) or times.shape != (size, len(TIME_COLUMNS)) or reasons.shape != (size,):
            raise ValueError("Unexpected numeric trade schema")
        if np.any((reasons < 0) | (reasons >= len(REASONS))):
            raise ValueError("Unknown numeric trade exit reason")
        columns = {name: values[:, i] for i, name in enumerate(FLOAT_COLUMNS)}
        for name in INTEGER_COLUMNS:
            columns[name] = columns[name].astype(np.int64)
        for name in BOOLEAN_COLUMNS:
            columns[name] = columns[name].astype(bool)
        for i, name in enumerate(TIME_COLUMNS):
            columns[name] = pd.to_datetime(times[:, i], unit="ns", utc=True)
        columns["exit_reason"] = np.asarray(REASONS, dtype=object)[reasons]
        columns["eligibility_policy"] = np.full(size, parameters["entry_eligibility"], dtype=object)
        trades = pd.DataFrame(columns, columns=TRADE_COLUMNS)
    else:
        trades = pd.DataFrame(columns=TRADE_COLUMNS)

    equity_size = len(equity_times)
    if len(equity_values) != equity_size:
        raise ValueError("Equity values and times have different lengths")
    if equity_size:
        values = np.asarray(equity_values, dtype=np.float64)
        times = np.asarray(equity_times, dtype=np.int64)
        if values.shape != (equity_size, len(EQUITY_VALUE_COLUMNS)) or times.shape != (equity_size,):
            raise ValueError("Unexpected numeric equity schema")
        columns = {name: values[:, i] for i, name in enumerate(EQUITY_VALUE_COLUMNS)}
        columns["contracts"] = columns["contracts"].astype(np.int64)
        columns["timestamp"] = pd.to_datetime(times, unit="ns", utc=True)
        equity = pd.DataFrame(columns, columns=EQUITY_COLUMNS)
    else:
        equity = pd.DataFrame(columns=EQUITY_COLUMNS)
    return trades, equity
