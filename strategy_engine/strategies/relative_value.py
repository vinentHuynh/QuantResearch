from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..accounting import PNL_COLUMNS, POSITION_COLUMNS, SIGNAL_COLUMNS, bar_availability
from ..sizing import QuantityMode, size_contracts


@dataclass(frozen=True)
class LegEconomics:
    tick_size: float
    point_value: float


@dataclass(frozen=True)
class RelativeValueConfig:
    strategy_id: str
    lookback: int = 60
    capital: float = 100_000.0
    cost_ticks: float = 1.0
    quantity_mode: QuantityMode = "fractional"


def run(
    bars_by_symbol: dict[str, pd.DataFrame],
    economics: dict[str, LegEconomics],
    config: RelativeValueConfig,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    panel = pd.concat(
        {symbol: bars.close.rename(symbol) for symbol, bars in bars_by_symbol.items()},
        axis=1,
    ).dropna()
    if panel.empty:
        return (
            pd.DataFrame(columns=PNL_COLUMNS),
            pd.DataFrame(columns=SIGNAL_COLUMNS),
            pd.DataFrame(columns=POSITION_COLUMNS),
        )
    if config.strategy_id == "pairs-mean-reversion":
        if len(panel.columns) != 2:
            raise ValueError("Pairs mean reversion requires exactly two charts")
        first, second = panel.columns
        spread = np.log(panel[first]) - np.log(panel[second])
        zscore = (spread - spread.rolling(config.lookback).mean()) / spread.rolling(config.lookback).std()
        position = -np.sign(zscore).where(zscore.abs() >= 1.0, 0.0).fillna(0.0)
        weights = pd.DataFrame({first: 0.5 * position, second: -0.5 * position}, index=panel.index)
        signal_level = zscore
        reason = "spread_zscore_at_close"
    elif config.strategy_id == "cross-sectional-momentum":
        if len(panel.columns) < 3:
            raise ValueError("Cross-sectional momentum requires at least three charts")
        score = panel.pct_change(config.lookback)
        ranks = score.rank(axis=1, pct=True)
        weights = (ranks >= 0.67).astype(float) - (ranks <= 0.33).astype(float)
        weights = weights.div(weights.abs().sum(axis=1), axis=0).fillna(0.0)
        signal_level = score.abs().max(axis=1)
        reason = "cross_sectional_rank_at_close"
    else:
        raise ValueError(f"Unsupported relative-value strategy: {config.strategy_id}")

    point_values = pd.Series({symbol: economics[symbol].point_value for symbol in panel.columns})
    tick_values = pd.Series({symbol: economics[symbol].tick_size * economics[symbol].point_value for symbol in panel.columns})
    reference_bars = next(iter(bars_by_symbol.values()))
    session_ids = reference_bars.session_id.reindex(panel.index)
    session_dates = reference_bars.session_date.reindex(panel.index)
    availability = bar_availability(reference_bars).reindex(panel.index)
    if session_dates.value_counts().max() > 1:
        session_ends = session_dates.ne(session_dates.shift(-1))
        weights.loc[session_ends] = 0.0
    raw_target_contracts = weights.mul(config.capital).div(panel.mul(point_values), axis=1).fillna(0.0)
    target_contracts = size_contracts(raw_target_contracts, config.quantity_mode)
    held_contracts = target_contracts.shift(1).fillna(0.0)
    gross = held_contracts.mul(panel.diff()).mul(point_values, axis=1).fillna(0.0)
    turnover = target_contracts.diff().abs().fillna(target_contracts.abs())
    # cost_ticks is a round-trip convention. Each unit of one-way target
    # turnover therefore receives half of the declared round-trip cost.
    cost = turnover.mul(tick_values, axis=1) * config.cost_ticks / 2.0

    joined_symbol = "/".join(panel.columns)
    pnl_rows: list[dict[str, object]] = []
    signal_rows: list[dict[str, object]] = []
    position_rows: list[dict[str, object]] = []
    prior_timestamp: pd.Timestamp | None = None
    for timestamp in panel.index:
        timestamp_utc = availability.loc[timestamp].isoformat()
        for symbol in panel.columns:
            position_rows.append({
                "event_time": timestamp_utc,
                "session_id": session_ids.loc[timestamp],
                "session_date": session_dates.loc[timestamp],
                "symbol": symbol,
                "quantity": float(target_contracts.loc[timestamp, symbol]),
                "price": float(panel.loc[timestamp, symbol]),
            })
            if prior_timestamp is not None:
                quantity = float(held_contracts.loc[timestamp, symbol])
                gross_value = float(gross.loc[timestamp, symbol])
                cost_value = float(cost.loc[timestamp, symbol])
                pnl_rows.append({
                    "period_start": availability.loc[prior_timestamp].isoformat(),
                    "period_end": timestamp_utc,
                    "availability_time": timestamp_utc,
                    "session_id": session_ids.loc[timestamp],
                    "session_date": session_dates.loc[timestamp],
                    "symbol": symbol,
                    "quantity": quantity,
                    "gross_pnl": gross_value,
                    "cost": cost_value,
                    "net_pnl": gross_value - cost_value,
                })
        if pd.notna(signal_level.loc[timestamp]):
            signal_rows.append({
                "event_time": timestamp_utc,
                "session_id": session_ids.loc[timestamp],
                "session_date": session_dates.loc[timestamp],
                "symbol": joined_symbol,
                "side": "portfolio",
                "level": float(signal_level.loc[timestamp]),
                "reason": reason,
            })
        prior_timestamp = timestamp
    return (
        pd.DataFrame(pnl_rows, columns=PNL_COLUMNS),
        pd.DataFrame(signal_rows, columns=SIGNAL_COLUMNS),
        pd.DataFrame(position_rows, columns=POSITION_COLUMNS),
    )
