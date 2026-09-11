from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from ..accounting import bar_availability


TRADE_COLUMNS = [
    "entry_time", "exit_time", "session_id", "session_date", "symbol", "side",
    "entry", "exit", "quantity", "gross_pnl", "cost", "net_pnl", "reason",
]


@dataclass(frozen=True)
class OpeningRangeBreakoutConfig:
    opening_range_minutes: int = 15
    stop_multiple: float = 1.0
    target_multiple: float = 2.0
    cost_ticks: float = 1.0


def run(
    bars: pd.DataFrame,
    *,
    opening_bars: pd.DataFrame | None = None,
    symbol: str,
    tick_size: float,
    point_value: float,
    config: OpeningRangeBreakoutConfig,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows: list[dict[str, object]] = []
    signal_rows: list[dict[str, object]] = []
    if bars.empty:
        return pd.DataFrame(columns=TRADE_COLUMNS), pd.DataFrame(
            columns=["event_time", "session_id", "session_date", "symbol", "side", "level", "reason"]
        )
    opening_source = bars if opening_bars is None else opening_bars
    availability = bar_availability(bars)
    for session_date, day in bars.groupby("session_date", sort=True):
        source_day = opening_source.loc[opening_source.session_date == session_date]
        if source_day.empty:
            continue
        session_open = source_day.index[0]
        range_end = session_open + pd.Timedelta(minutes=config.opening_range_minutes)
        opening = source_day.loc[source_day.index < range_end]
        later = day.loc[day.index >= range_end]
        if opening.empty or later.empty:
            continue
        opening_high = float(opening.high.max())
        opening_low = float(opening.low.min())
        candidates = later.loc[(later.close > opening_high) | (later.close < opening_low)]
        if candidates.empty:
            continue
        entry_time = candidates.index[0]
        entry = float(candidates.iloc[0].close)
        side = 1 if entry > opening_high else -1
        side_name = "long" if side > 0 else "short"
        risk = max(opening_high - opening_low, tick_size)
        stop = entry - side * risk * config.stop_multiple
        target = entry + side * risk * config.target_multiple
        after = later.loc[entry_time:]
        exit_price = float(after.iloc[-1].close)
        exit_time = after.index[-1]
        reason = "session_close"
        for timestamp, bar in after.iloc[1:].iterrows():
            stop_hit = bool(bar.low <= stop) if side > 0 else bool(bar.high >= stop)
            target_hit = bool(bar.high >= target) if side > 0 else bool(bar.low <= target)
            if stop_hit or target_hit:
                exit_price, exit_time, reason = (
                    (stop, timestamp, "stop") if stop_hit else (target, timestamp, "target")
                )
                break
        gross = side * (exit_price - entry) * point_value
        cost = config.cost_ticks * tick_size * point_value
        signal_rows.append({
            "event_time": availability.loc[entry_time].isoformat(),
            "session_id": day.iloc[0].session_id,
            "session_date": session_date,
            "symbol": symbol,
            "side": side_name,
            "level": opening_high if side > 0 else opening_low,
            "reason": "opening_range_break",
        })
        rows.append({
            "entry_time": availability.loc[entry_time].isoformat(),
            "exit_time": availability.loc[exit_time].isoformat(),
            "session_id": day.iloc[0].session_id,
            "session_date": session_date,
            "symbol": symbol,
            "side": side_name,
            "entry": entry,
            "exit": exit_price,
            "quantity": 1,
            "gross_pnl": gross,
            "cost": cost,
            "net_pnl": gross - cost,
            "reason": reason,
        })
    return pd.DataFrame(rows, columns=TRADE_COLUMNS), pd.DataFrame(signal_rows)
