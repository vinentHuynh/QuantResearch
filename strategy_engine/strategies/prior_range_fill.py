from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from ..accounting import bar_availability


TRADE_COLUMNS = [
    "entry_time", "exit_time", "session_id", "session_date", "symbol", "side",
    "entry", "exit", "quantity", "gross_pnl", "cost", "net_pnl", "reason",
]
SIGNAL_COLUMNS = [
    "event_time", "session_id", "session_date", "symbol", "side", "level", "reason",
]


@dataclass(frozen=True)
class PriorRangeFillConfig:
    cost_ticks: float = 1.0


def run(
    bars: pd.DataFrame,
    *,
    symbol: str,
    tick_size: float,
    point_value: float,
    config: PriorRangeFillConfig,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Fade a gap after price first trades back to the prior session boundary."""

    rows: list[dict[str, object]] = []
    signal_rows: list[dict[str, object]] = []
    availability = bar_availability(bars)
    grouped = [(session_date, day) for session_date, day in bars.groupby("session_date", sort=True)]
    for index in range(1, len(grouped)):
        _, prior = grouped[index - 1]
        session_date, today = grouped[index]
        prior_high = float(prior.high.max())
        prior_low = float(prior.low.min())
        session_open = float(today.iloc[0].open)
        if session_open > prior_high:
            touches = today.loc[today.low <= prior_high]
            side, level = -1, prior_high
        elif session_open < prior_low:
            touches = today.loc[today.high >= prior_low]
            side, level = 1, prior_low
        else:
            continue
        if touches.empty:
            continue
        entry_time = touches.index[0]
        exit_time = today.index[-1]
        exit_price = float(today.iloc[-1].close)
        gross = side * (exit_price - level) * point_value
        cost = config.cost_ticks * tick_size * point_value
        side_name = "long" if side > 0 else "short"
        common = {
            "session_id": today.iloc[0].session_id,
            "session_date": session_date,
            "symbol": symbol,
            "side": side_name,
        }
        signal_rows.append({
            "event_time": availability.loc[entry_time].isoformat(),
            **common,
            "level": level,
            "reason": "prior_range_backfill",
        })
        rows.append({
            "entry_time": availability.loc[entry_time].isoformat(),
            "exit_time": availability.loc[exit_time].isoformat(),
            **common,
            "entry": level,
            "exit": exit_price,
            "quantity": 1,
            "gross_pnl": gross,
            "cost": cost,
            "net_pnl": gross - cost,
            "reason": "session_close",
        })
    return pd.DataFrame(rows, columns=TRADE_COLUMNS), pd.DataFrame(signal_rows, columns=SIGNAL_COLUMNS)
