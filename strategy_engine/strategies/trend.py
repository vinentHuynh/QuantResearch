from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..accounting import PNL_COLUMNS, POSITION_COLUMNS, SIGNAL_COLUMNS, bar_availability
from ..sizing import QuantityMode, size_contracts
from .relative_value import LegEconomics


@dataclass(frozen=True)
class TrendConfig:
    strategy_id: str
    lookback: int = 60
    capital: float = 100_000.0
    cost_ticks: float = 1.0
    quantity_mode: QuantityMode = "fractional"


def run(
    bars: pd.DataFrame,
    *,
    symbol: str,
    economics: LegEconomics,
    config: TrendConfig,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Run a lagged single-chart trend rule on already sessionized bars."""

    if bars.empty:
        return (
            pd.DataFrame(columns=PNL_COLUMNS),
            pd.DataFrame(columns=SIGNAL_COLUMNS),
            pd.DataFrame(columns=POSITION_COLUMNS),
        )
    if config.lookback < 2:
        raise ValueError("Trend lookback must be at least two bars")

    close = bars.close.astype(float)
    if config.strategy_id == "multi-speed-momentum":
        speeds = tuple(dict.fromkeys((max(2, config.lookback // 3), config.lookback, config.lookback * 2, config.lookback * 4)))
        raw_signal = pd.concat(
            [np.sign(close.pct_change(speed)).rename(str(speed)) for speed in speeds],
            axis=1,
        ).mean(axis=1, skipna=False)
        target_direction = np.sign(raw_signal)
        reason = "multi_speed_momentum_at_close"
    elif config.strategy_id == "moving-average-trend":
        moving_average = close.rolling(config.lookback, min_periods=config.lookback).mean()
        raw_signal = (close / moving_average) - 1.0
        target_direction = (raw_signal > 0).astype(float).where(moving_average.notna())
        reason = "close_above_moving_average_at_close"
    else:
        raise ValueError(f"Unsupported trend strategy: {config.strategy_id}")

    # The close creates a target position for the next bar. Intraday variants
    # flatten at the selected session close so excluded-session gaps earn no P&L.
    if bars.session_date.value_counts().max() > 1:
        session_ends = bars.session_date.ne(bars.session_date.shift(-1))
        target_direction.loc[session_ends] = 0.0
    raw_target_contracts = target_direction.mul(config.capital).div(close * economics.point_value).fillna(0.0)
    target_contracts = size_contracts(raw_target_contracts, config.quantity_mode)
    held_contracts = target_contracts.shift(1).fillna(0.0)
    gross = held_contracts.mul(close.diff()).mul(economics.point_value).fillna(0.0)
    turnover = target_contracts.diff().abs().fillna(target_contracts.abs())
    # cost_ticks is a round-trip convention. Each unit of one-way target
    # turnover therefore receives half of the declared round-trip cost.
    cost = turnover * economics.tick_size * economics.point_value * config.cost_ticks / 2.0
    availability = bar_availability(bars)

    pnl_rows: list[dict[str, object]] = []
    signal_rows: list[dict[str, object]] = []
    position_rows: list[dict[str, object]] = []
    prior_timestamp: pd.Timestamp | None = None
    for timestamp in bars.index:
        timestamp_utc = availability.loc[timestamp].isoformat()
        session_id = bars.at[timestamp, "session_id"]
        session_date = bars.at[timestamp, "session_date"]
        quantity = float(target_contracts.loc[timestamp])
        price = float(close.loc[timestamp])
        position_rows.append({
            "event_time": timestamp_utc,
            "session_id": session_id,
            "session_date": session_date,
            "symbol": symbol,
            "quantity": quantity,
            "price": price,
        })
        level = raw_signal.loc[timestamp]
        if pd.notna(level):
            signal_rows.append({
                "event_time": timestamp_utc,
                "session_id": session_id,
                "session_date": session_date,
                "symbol": symbol,
                "side": "long" if target_direction.loc[timestamp] > 0 else "short" if target_direction.loc[timestamp] < 0 else "flat",
                "level": float(level),
                "reason": reason,
            })
        if prior_timestamp is not None:
            held_quantity = float(held_contracts.loc[timestamp])
            gross_value = float(gross.loc[timestamp])
            cost_value = float(cost.loc[timestamp])
            pnl_rows.append({
                "period_start": availability.loc[prior_timestamp].isoformat(),
                "period_end": timestamp_utc,
                "availability_time": timestamp_utc,
                "session_id": session_id,
                "session_date": session_date,
                "symbol": symbol,
                "quantity": held_quantity,
                "gross_pnl": gross_value,
                "cost": cost_value,
                "net_pnl": gross_value - cost_value,
            })
        prior_timestamp = timestamp

    return (
        pd.DataFrame(pnl_rows, columns=PNL_COLUMNS),
        pd.DataFrame(signal_rows, columns=SIGNAL_COLUMNS),
        pd.DataFrame(position_rows, columns=POSITION_COLUMNS),
    )
