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
class SessionDriftConfig:
    direction_model: str = "Long"
    bracket_exit: bool = False
    max_prior_range_pct: float = 0.0
    stop_multiple: float = 1.0
    target_multiple: float = 2.0
    cost_ticks: float = 1.0


def run(
    bars: pd.DataFrame,
    *,
    symbol: str,
    tick_size: float,
    point_value: float,
    config: SessionDriftConfig,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Hold a named session using only information available before its entry."""

    rows: list[dict[str, object]] = []
    signal_rows: list[dict[str, object]] = []
    availability = bar_availability(bars)
    grouped = [(session_date, day) for session_date, day in bars.groupby("session_date", sort=True)]
    for index, (session_date, day) in enumerate(grouped):
        if len(day) < 2:
            continue
        prior = grouped[index - 1][1] if index > 0 else None
        side = 1
        prior_range = None
        if prior is not None:
            prior_range = float(prior.high.max() - prior.low.min())
            if config.direction_model == "Prior trend":
                side = 1 if float(prior.iloc[-1].close) >= float(prior.iloc[0].open) else -1
        elif config.direction_model == "Prior trend" or config.max_prior_range_pct > 0 or config.bracket_exit:
            continue
        entry_time = day.index[0]
        entry = float(day.iloc[0].open)
        if config.max_prior_range_pct > 0:
            if prior_range is None or prior_range > entry * config.max_prior_range_pct / 100:
                continue
        exit_time = day.index[-1]
        exit_price = float(day.iloc[-1].close)
        reason = "session_close"
        if config.bracket_exit:
            if prior_range is None:
                continue
            risk = max(prior_range * 0.25, tick_size)
            stop = entry - side * risk * config.stop_multiple
            target = entry + side * risk * config.target_multiple
            for timestamp, bar in day.iloc[1:].iterrows():
                stop_hit = bool(bar.low <= stop) if side > 0 else bool(bar.high >= stop)
                target_hit = bool(bar.high >= target) if side > 0 else bool(bar.low <= target)
                if stop_hit or target_hit:
                    exit_price, exit_time, reason = (
                        (stop, timestamp, "stop") if stop_hit else (target, timestamp, "target")
                    )
                    break
        cost = config.cost_ticks * tick_size * point_value
        gross = side * (exit_price - entry) * point_value
        side_name = "long" if side > 0 else "short"
        common = {
            "session_id": day.iloc[0].session_id,
            "session_date": session_date,
            "symbol": symbol,
            "side": side_name,
        }
        signal_rows.append({
            "event_time": entry_time.tz_convert("UTC").isoformat(),
            **common,
            "level": entry,
            "reason": "session_entry",
        })
        rows.append({
            "entry_time": entry_time.tz_convert("UTC").isoformat(),
            "exit_time": availability.loc[exit_time].isoformat(),
            **common,
            "entry": entry,
            "exit": exit_price,
            "quantity": 1,
            "gross_pnl": gross,
            "cost": cost,
            "net_pnl": gross - cost,
            "reason": reason,
        })
    return pd.DataFrame(rows, columns=TRADE_COLUMNS), pd.DataFrame(signal_rows, columns=SIGNAL_COLUMNS)
