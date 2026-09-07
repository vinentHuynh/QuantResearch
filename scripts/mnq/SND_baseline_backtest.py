"""Reproduce SND's default zone-retest baseline on MNQ one-minute data.

Zones are formed from closed 1h, 4h, and session-daily candles. The one-minute
archive drives invalidation, retests, entries, and exits. This intentionally
keeps SND's current mechanics--including fixed point targets, the 100-point
stop cap, higher-timeframe priority, two-test limit, and conservative stop-first
handling when a one-minute bar touches both stop and target.

Default run from the repository root:

    .venv/bin/python scripts/mnq/SND_baseline_backtest.py

To reproduce SND's currently configured date window while retaining earlier
bars as zone warm-up history:

    .venv/bin/python scripts/mnq/SND_baseline_backtest.py \
        --start 2026-01-01T23:00:00Z --end 2026-05-30T21:00:00Z \
        --output-dir reports/SND_baseline_2026_window
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import math
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = ROOT / "data" / "mnq_dom_sample" / "full_history"
DEFAULT_ONE_MINUTE = DATA_ROOT / "ohlcv-1m" / "candles_1m.parquet"
DEFAULT_TIMEFRAME_DIR = DATA_ROOT / "ohlcv-resampled"
DEFAULT_OUTPUT_DIR = ROOT / "reports" / "SND_baseline"
OHLCV = ["open", "high", "low", "close", "volume"]
TIMEZONE = "America/Chicago"
TICK_SIZE = 0.25
TF_RANK = {"1h": 60, "4h": 240, "1d": 1440}
TF_TARGET = {"1h": 100.0, "4h": 200.0, "1d": 400.0}
TF_LABEL = {"1h": "1h", "4h": "4h", "1d": "Daily"}


@dataclass
class Zone:
    zone_id: int
    direction: str
    timeframe: str
    rank: int
    formed_at: pd.Timestamp
    available_at: pd.Timestamp
    activation_pos: int
    proximal: float
    distal: float
    width: float
    prior_body: float
    impulse_body: float
    prior_open: float
    prior_high: float
    prior_low: float
    prior_close: float
    impulse_open: float
    impulse_high: float
    impulse_low: float
    impulse_close: float
    formation_volume: int
    minute_count: int
    roll_formation: bool
    state: str = "pending"
    ready: bool = True
    test_count: int = 0
    executed_count: int = 0
    last_test_pos: int = -1
    removed_at: pd.Timestamp | None = None
    removal_reason: str | None = None
    physical_touch_count: int = 0
    touching_previous_bar: bool = False


@dataclass
class ActiveTrade:
    trade_id: int
    zone: Zone
    direction: str
    test_number: int
    entry_pos: int
    entry_time: pd.Timestamp
    entry: float
    stop: float
    target: float
    risk_points: float
    session: str
    mfe_points: float = 0.0
    mae_points: float = 0.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--one-minute", type=Path, default=DEFAULT_ONE_MINUTE)
    parser.add_argument("--timeframe-dir", type=Path, default=DEFAULT_TIMEFRAME_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--symbol", default="MNQ", help="chart/instrument label")
    parser.add_argument("--tick-size", type=float, default=0.25)
    parser.add_argument("--timeframes", default="1h,4h,1d")
    parser.add_argument("--start", default=None, help="first allowed entry timestamp")
    parser.add_argument("--end", default=None, help="last allowed entry timestamp")
    parser.add_argument("--body-ratio", type=float, default=0.50)
    parser.add_argument("--max-zones", type=int, default=50)
    parser.add_argument("--max-tests", type=int, default=2)
    parser.add_argument("--bounce-points", type=float, default=75.0)
    parser.add_argument("--min-zone-age-bars", type=int, default=1)
    parser.add_argument("--min-bars-between-tests", type=int, default=5)
    parser.add_argument("--min-bars-in-trade", type=int, default=1)
    parser.add_argument("--stop-cap-points", type=float, default=100.0)
    parser.add_argument("--zone-stop-buffer-points", type=float, default=1.0)
    parser.add_argument("--point-value", type=float, default=2.0,
                        help="MNQ dollars per index point; SND's NQ display uses 20")
    parser.add_argument("--cost-ticks", type=float, default=0.0,
                        help="round-trip cost in the selected chart's ticks")
    parser.add_argument("--target-1h-ticks", type=float, default=400.0)
    parser.add_argument("--target-4h-ticks", type=float, default=800.0)
    parser.add_argument("--target-1d-ticks", type=float, default=1600.0)
    return parser.parse_args()


def parse_timestamp(value: str | None) -> pd.Timestamp | None:
    if value is None:
        return None
    result = pd.Timestamp(value)
    if result.tz is None:
        raise ValueError(f"Timestamp must include a timezone: {value}")
    return result.tz_convert("UTC")


def validate_args(args: argparse.Namespace) -> list[str]:
    timeframes = [part.strip().lower() for part in args.timeframes.split(",") if part.strip()]
    unknown = sorted(set(timeframes) - TF_RANK.keys())
    if unknown:
        raise ValueError(f"Unsupported timeframes: {', '.join(unknown)}")
    if not timeframes:
        raise ValueError("At least one timeframe is required")
    for name in ("body_ratio", "bounce_points", "stop_cap_points", "point_value"):
        if getattr(args, name) <= 0:
            raise ValueError(f"--{name.replace('_', '-')} must be positive")
    for name in ("max_zones", "max_tests", "min_zone_age_bars",
                 "min_bars_between_tests", "min_bars_in_trade"):
        if getattr(args, name) < 0:
            raise ValueError(f"--{name.replace('_', '-')} cannot be negative")
    if args.max_zones < 1 or args.max_tests < 1:
        raise ValueError("--max-zones and --max-tests must be at least one")
    return list(dict.fromkeys(timeframes))


def load_bars(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Missing candle file: {path}")
    frame = pd.read_parquet(path).sort_index()
    missing = sorted(set(OHLCV) - set(frame.columns))
    if missing:
        raise ValueError(f"{path} is missing columns: {missing}")
    if not isinstance(frame.index, pd.DatetimeIndex) or frame.index.tz is None:
        raise ValueError(f"{path} needs a timezone-aware DatetimeIndex")
    if frame.empty or frame.index.has_duplicates or not frame.index.is_monotonic_increasing:
        raise ValueError(f"{path} is empty, duplicated, or unsorted")
    if frame[OHLCV].isna().any().any():
        raise ValueError(f"{path} contains missing OHLCV values")
    return frame


def candle_end(index: pd.DatetimeIndex, timeframe: str) -> pd.DatetimeIndex:
    if timeframe == "1d":
        local = index.tz_convert("America/New_York")
        return (local + pd.DateOffset(days=1)).tz_convert("UTC")
    return index.tz_convert("UTC") + pd.Timedelta(minutes=TF_RANK[timeframe])


def detect_zones(
    frames: dict[str, pd.DataFrame],
    execution_index: pd.DatetimeIndex,
    body_ratio: float,
) -> list[Zone]:
    candidates: list[dict[str, Any]] = []
    execution_ns = execution_index.asi8

    for timeframe, frame in frames.items():
        previous = frame.shift(1)
        impulse_body = (frame["close"] - frame["open"]).abs()
        prior_body = (previous["close"] - previous["open"]).abs()
        large_enough = (impulse_body > 0) & (prior_body <= body_ratio * impulse_body)
        demand = large_enough & (previous["open"] > previous["close"]) & (
            frame["close"] > frame["open"]
        )
        supply = large_enough & (previous["close"] > previous["open"]) & (
            frame["open"] > frame["close"]
        )
        ends = candle_end(frame.index, timeframe)

        for direction, mask in (("long", demand), ("short", supply)):
            positions = np.flatnonzero(mask.to_numpy())
            for pos in positions:
                available_at = ends[pos]
                activation_pos = int(np.searchsorted(execution_ns, available_at.value, side="left"))
                current = frame.iloc[pos]
                prior = previous.iloc[pos]
                proximal = float(prior["open"])
                distal = float(min(prior["low"], current["low"])) if direction == "long" else float(
                    max(prior["high"], current["high"])
                )
                roll_formation = bool(current.get("is_roll_bar", False)) or bool(
                    prior.get("is_roll_bar", False)
                )
                if "instrument_id" in frame.columns:
                    roll_formation = roll_formation or int(current["instrument_id"]) != int(
                        prior["instrument_id"]
                    )
                candidates.append({
                    "direction": direction,
                    "timeframe": timeframe,
                    "rank": TF_RANK[timeframe],
                    "formed_at": frame.index[pos].tz_convert("UTC"),
                    "available_at": available_at,
                    "activation_pos": activation_pos,
                    "proximal": proximal,
                    "distal": distal,
                    "width": abs(proximal - distal),
                    "prior_body": float(prior_body.iloc[pos]),
                    "impulse_body": float(impulse_body.iloc[pos]),
                    "prior_open": float(prior["open"]),
                    "prior_high": float(prior["high"]),
                    "prior_low": float(prior["low"]),
                    "prior_close": float(prior["close"]),
                    "impulse_open": float(current["open"]),
                    "impulse_high": float(current["high"]),
                    "impulse_low": float(current["low"]),
                    "impulse_close": float(current["close"]),
                    "formation_volume": int(current["volume"]),
                    "minute_count": int(current.get("minute_count", 0)),
                    "roll_formation": roll_formation,
                })

    # SND processes 1h before 4h before Daily. Each new zone is prepended to
    # its side's array, so later/higher timeframes are newest on timestamp ties.
    candidates.sort(key=lambda row: (row["available_at"], row["rank"]))
    return [Zone(zone_id=i + 1, **row) for i, row in enumerate(candidates)]


def session_name(timestamp: pd.Timestamp) -> str:
    local = timestamp.tz_convert(TIMEZONE)
    minute = local.hour * 60 + local.minute
    if minute >= 17 * 60 or minute < 2 * 60:
        return "Asia"
    if minute < 8 * 60 + 30:
        return "London"
    return "New York"


def within_entry_period(
    timestamp: pd.Timestamp,
    start: pd.Timestamp | None,
    end: pd.Timestamp | None,
) -> bool:
    return (start is None or timestamp >= start) and (end is None or timestamp <= end)


def no_trade_window(timestamp: pd.Timestamp) -> bool:
    local = timestamp.tz_convert(TIMEZONE)
    minute = local.hour * 60 + local.minute
    return 15 * 60 <= minute < 16 * 60


def forced_close_crossing(timestamp: pd.Timestamp, previous: pd.Timestamp | None) -> bool:
    if previous is None:
        return False
    current_local = timestamp.tz_convert(TIMEZONE)
    previous_local = previous.tz_convert(TIMEZONE)
    current_minute = current_local.hour * 60 + current_local.minute
    previous_minute = previous_local.hour * 60 + previous_local.minute
    return previous_minute < 15 * 60 <= current_minute


def select_candidate(
    zones: list[Zone],
    direction: str,
    pos: int,
    high: float,
    low: float,
    close: float,
    args: argparse.Namespace,
    entry_filter: Callable[[Zone], bool] | None = None,
) -> Zone | None:
    selected: Zone | None = None
    selected_distance = math.inf

    for zone in zones:
        touched = low <= zone.proximal and high >= zone.distal if direction == "long" else (
            high >= zone.proximal and low <= zone.distal
        )
        enough_bars = zone.last_test_pos < 0 or pos - zone.last_test_pos >= args.min_bars_between_tests
        if not zone.ready:
            bounced = close >= zone.proximal + args.bounce_points if direction == "long" else (
                close <= zone.proximal - args.bounce_points
            )
            if bounced and not touched and enough_bars:
                zone.ready = True

        old_enough = pos - (zone.activation_pos - 1) >= args.min_zone_age_bars
        eligible = (
            touched
            and zone.ready
            and old_enough
            and enough_bars
            and zone.test_count + 1 <= args.max_tests
            and (entry_filter is None or entry_filter(zone))
        )
        if not eligible:
            continue

        distance = abs(close - zone.proximal)
        if selected is None or zone.rank > selected.rank or (
            zone.rank == selected.rank and distance < selected_distance
        ):
            selected = zone
            selected_distance = distance

    return selected


def consume_test(zone: Zone, pos: int, timestamp: pd.Timestamp) -> dict[str, Any]:
    zone.test_count += 1
    zone.last_test_pos = pos
    zone.ready = False
    return {
        "zone_id": zone.zone_id,
        "direction": zone.direction,
        "timeframe": TF_LABEL[zone.timeframe],
        "test_number": zone.test_count,
        "test_time": timestamp,
        "executed": False,
        "not_executed_reason": None,
    }


def trade_levels(zone: Zone, args: argparse.Namespace) -> tuple[float, float, float]:
    if zone.direction == "long":
        zone_break_stop = zone.distal - args.zone_stop_buffer_points
    else:
        zone_break_stop = zone.distal + args.zone_stop_buffer_points
    zone_stop_points = abs(zone.proximal - zone_break_stop)
    risk_points = min(zone_stop_points, args.stop_cap_points)
    stop = zone.proximal - risk_points if zone.direction == "long" else zone.proximal + risk_points
    target_points = {
        "1h": args.target_1h_ticks,
        "4h": args.target_4h_ticks,
        "1d": args.target_1d_ticks,
    }[zone.timeframe] * args.tick_size
    target = zone.proximal + target_points if zone.direction == "long" else (
        zone.proximal - target_points
    )
    return stop, target, risk_points


def close_trade(
    trade: ActiveTrade,
    exit_time: pd.Timestamp,
    exit_price: float,
    reason: str,
    both_hit: bool,
    args: argparse.Namespace,
) -> dict[str, Any]:
    points = exit_price - trade.entry if trade.direction == "long" else trade.entry - exit_price
    gross_pnl = points * args.point_value
    cost = args.cost_ticks * TICK_SIZE * args.point_value
    pnl = gross_pnl - cost
    local_entry = trade.entry_time.tz_convert(TIMEZONE)
    return {
        "trade_id": trade.trade_id,
        "zone_id": trade.zone.zone_id,
        "direction": trade.direction,
        "timeframe": TF_LABEL[trade.zone.timeframe],
        "zone_formed_at": trade.zone.formed_at,
        "zone_available_at": trade.zone.available_at,
        "zone_proximal": trade.zone.proximal,
        "zone_distal": trade.zone.distal,
        "zone_width": trade.zone.width,
        "roll_formation": trade.zone.roll_formation,
        "test_number": trade.test_number,
        "entry_time": trade.entry_time,
        "entry_price": trade.entry,
        "stop_price": trade.stop,
        "target_price": trade.target,
        "risk_points": trade.risk_points,
        "exit_time": exit_time,
        "exit_price": exit_price,
        "exit_reason": reason,
        "both_stop_and_target_hit": both_hit,
        "points": points,
        "r_multiple": points / trade.risk_points,
        "gross_pnl": gross_pnl,
        "cost": cost,
        "pnl": pnl,
        "mfe_points": trade.mfe_points,
        "mae_points": trade.mae_points,
        "duration_minutes": (exit_time - trade.entry_time).total_seconds() / 60.0,
        "session": trade.session,
        "entry_year": local_entry.year,
        "entry_weekday": local_entry.day_name(),
        "entry_hour_ct": local_entry.hour,
    }


def simulate(
    minute: pd.DataFrame,
    zones: list[Zone],
    start: pd.Timestamp | None,
    end: pd.Timestamp | None,
    args: argparse.Namespace,
    entry_filter: Callable[[Zone, list[Zone], list[Zone]], bool] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, int]]:
    index = minute.index.tz_convert("UTC")
    opens = minute["open"].to_numpy(dtype=float)
    highs = minute["high"].to_numpy(dtype=float)
    lows = minute["low"].to_numpy(dtype=float)
    closes = minute["close"].to_numpy(dtype=float)
    events: dict[int, list[Zone]] = {}
    for zone in zones:
        if zone.activation_pos < len(index):
            events.setdefault(zone.activation_pos, []).append(zone)

    active_long: list[Zone] = []
    active_short: list[Zone] = []
    active_trade: ActiveTrade | None = None
    trades: list[dict[str, Any]] = []
    tests: list[dict[str, Any]] = []
    audit = {
        "capacity_removed": 0,
        "invalidated": 0,
        "tests_consumed": 0,
        "tests_outside_entry_period": 0,
        "tests_in_no_trade_window": 0,
        "opposite_side_tests_consumed": 0,
        "range_end_trade_cancellations": 0,
        "both_stop_and_target_hit": 0,
    }
    next_trade_id = 1

    for pos, timestamp in enumerate(index):
        previous_timestamp = index[pos - 1] if pos else None
        open_price = opens[pos]
        high = highs[pos]
        low = lows[pos]
        close = closes[pos]

        # Activate zones in SND's timeframe call order, prepending each one.
        for zone in events.get(pos, ()):
            zone.state = "active"
            side = active_long if zone.direction == "long" else active_short
            side.insert(0, zone)
            if len(side) > args.max_zones:
                removed = side.pop()
                removed.state = "removed"
                removed.removed_at = timestamp
                removed.removal_reason = "capacity"
                audit["capacity_removed"] += 1

        # Wick-or-close mode: a strict break of the distal boundary invalidates.
        previous_close = closes[pos - 1] if pos else np.nan
        kept_short: list[Zone] = []
        for zone in active_short:
            if high > zone.distal:
                zone.state = "invalidated"
                zone.removed_at = timestamp
                zone.removal_reason = (
                    "gap" if previous_close <= zone.distal and open_price > zone.distal else "wick_or_close"
                )
                audit["invalidated"] += 1
            else:
                kept_short.append(zone)
        active_short = kept_short

        kept_long: list[Zone] = []
        for zone in active_long:
            if low < zone.distal:
                zone.state = "invalidated"
                zone.removed_at = timestamp
                zone.removal_reason = (
                    "gap" if previous_close >= zone.distal and open_price < zone.distal else "wick_or_close"
                )
                audit["invalidated"] += 1
            else:
                kept_long.append(zone)
        active_long = kept_long

        # Track physical touch episodes independently from SND's selected
        # tests. A maintenance/weekend gap begins a new episode.
        time_contiguous = (
            previous_timestamp is not None
            and timestamp - previous_timestamp == pd.Timedelta(minutes=1)
        )
        for zone in active_long + active_short:
            touched = low <= zone.proximal and high >= zone.distal if zone.direction == "long" else (
                high >= zone.proximal and low <= zone.distal
            )
            if touched and (not time_contiguous or not zone.touching_previous_bar):
                zone.physical_touch_count += 1
            zone.touching_previous_bar = touched

        passes = None if entry_filter is None else (
            lambda zone: entry_filter(zone, active_long, active_short)
        )

        trade_was_active = active_trade is not None
        selected_long: Zone | None = None
        selected_short: Zone | None = None
        selected_test_rows: list[tuple[Zone, dict[str, Any]]] = []

        # SND updates rearming on every bar, but only selects tests when flat.
        if trade_was_active:
            select_candidate(active_long, "long", pos, high, low, close, args, passes)
            select_candidate(active_short, "short", pos, high, low, close, args, passes)
        else:
            selected_long = select_candidate(active_long, "long", pos, high, low, close, args, passes)
            selected_short = select_candidate(active_short, "short", pos, high, low, close, args, passes)
            if selected_long is not None:
                row = consume_test(selected_long, pos, timestamp)
                tests.append(row)
                selected_test_rows.append((selected_long, row))
                audit["tests_consumed"] += 1
            if selected_short is not None:
                row = consume_test(selected_short, pos, timestamp)
                tests.append(row)
                selected_test_rows.append((selected_short, row))
                audit["tests_consumed"] += 1

        # Date-range end cancels an open trade in SND without an outcome.
        if active_trade is not None and end is not None and timestamp > end:
            active_trade = None
            audit["range_end_trade_cancellations"] += 1

        if active_trade is not None:
            if active_trade.direction == "long":
                active_trade.mfe_points = max(active_trade.mfe_points, max(high - active_trade.entry, 0.0))
                active_trade.mae_points = max(active_trade.mae_points, max(active_trade.entry - low, 0.0))
                stop_hit = low <= active_trade.stop
                target_hit = high >= active_trade.target
            else:
                active_trade.mfe_points = max(active_trade.mfe_points, max(active_trade.entry - low, 0.0))
                active_trade.mae_points = max(active_trade.mae_points, max(high - active_trade.entry, 0.0))
                stop_hit = high >= active_trade.stop
                target_hit = low <= active_trade.target

            can_exit = pos - active_trade.entry_pos >= args.min_bars_in_trade
            timed = can_exit and forced_close_crossing(timestamp, previous_timestamp) and not stop_hit and not target_hit
            if can_exit and (stop_hit or target_hit or timed):
                both_hit = stop_hit and target_hit
                if stop_hit:  # SND resolves an ambiguous bar against the trade.
                    exit_price, reason = active_trade.stop, "stop"
                elif target_hit:
                    exit_price, reason = active_trade.target, "target"
                else:
                    exit_price, reason = close, "timed_close"
                trades.append(close_trade(active_trade, timestamp, exit_price, reason, both_hit, args))
                if both_hit:
                    audit["both_stop_and_target_hit"] += 1
                active_trade = None

        # A trade that was active at the beginning of this bar blocks new entry,
        # even if it exits during the bar. That matches f_count_tests ordering.
        if not trade_was_active and active_trade is None and selected_test_rows:
            period_allowed = within_entry_period(timestamp, start, end)
            window_allowed = not no_trade_window(timestamp)
            chosen = selected_long if selected_long is not None else selected_short

            for zone, row in selected_test_rows:
                if not period_allowed:
                    row["not_executed_reason"] = "outside_entry_period"
                    audit["tests_outside_entry_period"] += 1
                elif not window_allowed:
                    row["not_executed_reason"] = "no_trade_window"
                    audit["tests_in_no_trade_window"] += 1
                elif zone is not chosen:
                    row["not_executed_reason"] = "long_priority"
                    audit["opposite_side_tests_consumed"] += 1
                else:
                    row["executed"] = True

            if period_allowed and window_allowed and chosen is not None:
                stop, target, risk_points = trade_levels(chosen, args)
                chosen.executed_count += 1
                active_trade = ActiveTrade(
                    trade_id=next_trade_id,
                    zone=chosen,
                    direction=chosen.direction,
                    test_number=chosen.test_count,
                    entry_pos=pos,
                    entry_time=timestamp,
                    entry=chosen.proximal,
                    stop=stop,
                    target=target,
                    risk_points=risk_points,
                    session=session_name(timestamp),
                )
                next_trade_id += 1

        if pos and pos % 1_000_000 == 0:
            print(f"  processed {pos:,}/{len(index):,} one-minute bars", flush=True)

    # SND normally closes intraday at 15:00 CT. Preserve a diagnostic if an
    # unusual final partial day leaves a position open rather than inventing a fill.
    audit["open_trade_at_data_end"] = int(active_trade is not None)
    for zone in active_long + active_short:
        zone.state = "active_at_end"

    return pd.DataFrame(trades), pd.DataFrame(tests), audit


def zones_frame(zones: list[Zone]) -> pd.DataFrame:
    return pd.DataFrame([
        {
            "zone_id": zone.zone_id,
            "direction": zone.direction,
            "timeframe": TF_LABEL[zone.timeframe],
            "formed_at": zone.formed_at,
            "available_at": zone.available_at,
            "proximal": zone.proximal,
            "distal": zone.distal,
            "width": zone.width,
            "prior_body": zone.prior_body,
            "impulse_body": zone.impulse_body,
            "body_ratio": zone.prior_body / zone.impulse_body,
            "prior_open": zone.prior_open,
            "prior_high": zone.prior_high,
            "prior_low": zone.prior_low,
            "prior_close": zone.prior_close,
            "impulse_open": zone.impulse_open,
            "impulse_high": zone.impulse_high,
            "impulse_low": zone.impulse_low,
            "impulse_close": zone.impulse_close,
            "formation_volume": zone.formation_volume,
            "minute_count": zone.minute_count,
            "roll_formation": zone.roll_formation,
            "tests_consumed": zone.test_count,
            "trades_executed": zone.executed_count,
            "state": zone.state,
            "removed_at": zone.removed_at,
            "removal_reason": zone.removal_reason,
        }
        for zone in zones
    ])


def max_drawdown(values: pd.Series) -> float:
    equity = values.cumsum()
    # Include starting equity of zero so an initial losing run counts as drawdown.
    peaks = equity.cummax().clip(lower=0.0)
    return float((equity - peaks).min()) if len(equity) else 0.0


def summarize(group: pd.DataFrame) -> pd.Series:
    count = len(group)
    wins = int((group["pnl"] >= 0).sum()) if count else 0
    gross_wins = float(group.loc[group["pnl"] > 0, "pnl"].sum()) if count else 0.0
    gross_losses = float(-group.loc[group["pnl"] < 0, "pnl"].sum()) if count else 0.0
    return pd.Series({
        "trades": count,
        "wins": wins,
        "losses": count - wins,
        "win_rate": wins / count if count else np.nan,
        "avg_points": group["points"].mean() if count else np.nan,
        "total_points": group["points"].sum() if count else 0.0,
        "avg_r": group["r_multiple"].mean() if count else np.nan,
        "total_pnl": group["pnl"].sum() if count else 0.0,
        "avg_pnl": group["pnl"].mean() if count else np.nan,
        "profit_factor": gross_wins / gross_losses if gross_losses else np.nan,
        "max_drawdown": max_drawdown(group["pnl"]) if count else 0.0,
        "avg_mfe_points": group["mfe_points"].mean() if count else np.nan,
        "avg_mae_points": group["mae_points"].mean() if count else np.nan,
    })


def grouped_summary(trades: pd.DataFrame, column: str) -> pd.DataFrame:
    rows = []
    for value, group in trades.groupby(column, sort=True):
        row = summarize(group.sort_values("exit_time")).to_dict()
        row[column] = value
        rows.append(row)
    columns = [column, "trades", "wins", "losses", "win_rate", "avg_points",
               "total_points", "avg_r", "total_pnl", "avg_pnl", "profit_factor",
               "max_drawdown", "avg_mfe_points", "avg_mae_points"]
    result = pd.DataFrame(rows).reindex(columns=columns)
    for count_column in ("trades", "wins", "losses"):
        if count_column in result:
            result[count_column] = result[count_column].astype(int)
    return result


def format_number(value: float, kind: str = "number") -> str:
    if pd.isna(value):
        return "n/a"
    if kind == "percent":
        return f"{value:.1%}"
    if kind == "money":
        return f"${value:,.2f}"
    return f"{value:,.2f}"


def write_report(
    output_dir: Path,
    zones: pd.DataFrame,
    tests: pd.DataFrame,
    trades: pd.DataFrame,
    audit: dict[str, int],
    args: argparse.Namespace,
    start: pd.Timestamp | None,
    end: pd.Timestamp | None,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    zones.to_parquet(output_dir / "zones.parquet", index=False)
    tests.to_parquet(output_dir / "zone_tests.parquet", index=False)
    trades.to_parquet(output_dir / "trades.parquet", index=False)

    ordered = trades.sort_values("exit_time").reset_index(drop=True)
    overall = summarize(ordered)
    groupings = {
        "annual": "entry_year",
        "by_timeframe": "timeframe",
        "by_direction": "direction",
        "by_test": "test_number",
        "by_session": "session",
        "by_exit_reason": "exit_reason",
    }
    tables: dict[str, pd.DataFrame] = {}
    for filename, column in groupings.items():
        table = grouped_summary(ordered, column)
        table.to_csv(output_dir / f"{filename}.csv", index=False)
        tables[filename] = table

    summary = {
        "method": "SND default logic; 1-minute execution",
        "entry_period": {"start": str(start), "end": str(end)},
        "parameters": {
            "symbol": args.symbol,
            "tick_size": args.tick_size,
            "timeframes": args.timeframes,
            "body_ratio": args.body_ratio,
            "max_zones_per_side": args.max_zones,
            "max_tests": args.max_tests,
            "bounce_points": args.bounce_points,
            "min_zone_age_bars_1m": args.min_zone_age_bars,
            "min_bars_between_tests_1m": args.min_bars_between_tests,
            "min_bars_in_trade_1m": args.min_bars_in_trade,
            "stop_cap_points": args.stop_cap_points,
            "zone_stop_buffer_points": args.zone_stop_buffer_points,
            "point_value": args.point_value,
            "cost_ticks": args.cost_ticks,
            "target_ticks": {
                "1h": args.target_1h_ticks,
                "4h": args.target_4h_ticks,
                "1d": args.target_1d_ticks,
            },
        },
        "zones": {
            "total": len(zones),
            "demand": int((zones["direction"] == "long").sum()),
            "supply": int((zones["direction"] == "short").sum()),
            "roll_formation": int(zones["roll_formation"].sum()),
        },
        "tests": {
            "consumed": len(tests),
            "executed": int(tests["executed"].sum()) if len(tests) else 0,
        },
        "performance": {key: None if pd.isna(value) else float(value)
                        for key, value in overall.items()},
        "audit": audit,
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")

    report = f"""# SND {args.symbol} baseline

This is SND's default two-candle zone logic executed on the {args.symbol}
one-minute path. It is a research baseline, not a claim of tradable performance.

## Headline

| Metric | Result |
| --- | ---: |
| Zones formed | {len(zones):,} |
| Tests consumed | {len(tests):,} |
| Trades | {int(overall['trades']):,} |
| Win rate | {format_number(overall['win_rate'], 'percent')} |
| Average points | {format_number(overall['avg_points'])} |
| Average R | {format_number(overall['avg_r'])} |
| Total points | {format_number(overall['total_points'])} |
| Total P&L | {format_number(overall['total_pnl'], 'money')} |
| Profit factor | {format_number(overall['profit_factor'])} |
| Max drawdown | {format_number(overall['max_drawdown'], 'money')} |

P&L uses {args.symbol} at ${args.point_value:g}/point, tick size {args.tick_size:g}, and {args.cost_ticks:g} round-trip cost ticks.

## Baseline caveats retained from SND

- A zone needs only the two-candle body pattern; it does not require BOS, an order
  block, relative volume, displacement/ATR, FVG, or swing confirmation.
- Entries fill at the proximal line whenever a one-minute range overlaps the zone.
- The stop is capped at {args.stop_cap_points:g} points and may therefore sit inside a wide zone.
- A test can be consumed outside the enabled date/no-trade window.
- If both sides qualify on one bar, SND consumes both tests and prioritizes the long.
- If stop and target occur in the same one-minute bar, the stop wins.
- Continuous-contract roll formations are retained but flagged.

## Engine audit

```json
{json.dumps(audit, indent=2)}
```

CSV summaries and Parquet zone/test/trade ledgers are in this directory.
"""
    (output_dir / "report.md").write_text(report)


def main() -> None:
    global TICK_SIZE
    args = parse_args()
    if args.tick_size <= 0:
        raise ValueError("--tick-size must be positive")
    TICK_SIZE = args.tick_size
    timeframes = validate_args(args)
    start = parse_timestamp(args.start)
    end = parse_timestamp(args.end)
    if start is not None and end is not None and end < start:
        raise ValueError("--end must not precede --start")

    print("Loading one-minute execution data...", flush=True)
    minute = load_bars(args.one_minute)
    frames = {
        timeframe: load_bars(args.timeframe_dir / f"candles_{timeframe}.parquet")
        for timeframe in timeframes
    }
    print("Detecting closed-candle zones...", flush=True)
    zones = detect_zones(frames, minute.index, args.body_ratio)
    counts = pd.Series([TF_LABEL[z.timeframe] for z in zones]).value_counts().to_dict()
    print(f"Detected {len(zones):,} zones: {counts}", flush=True)
    print("Simulating SND's retest engine on one-minute bars...", flush=True)
    trades, tests, audit = simulate(minute, zones, start, end, args)
    zones_table = zones_frame(zones)
    print(f"Writing {len(trades):,} trades and {len(tests):,} consumed tests...", flush=True)
    write_report(args.output_dir, zones_table, tests, trades, audit, args, start, end)
    overall = summarize(trades.sort_values("exit_time"))
    print(
        f"DONE | trades={len(trades):,} | win={overall['win_rate']:.1%} | "
        f"avg={overall['avg_points']:.2f} pts | total={overall['total_points']:,.2f} pts | "
        f"PF={overall['profit_factor']:.2f} -> {args.output_dir}"
    )


if __name__ == "__main__":
    main()
