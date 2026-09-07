"""Build SND Phase 2 zone and retest research datasets.

This script does not change the Phase 1 trading rules. It enriches every zone
with formation-time information and creates an independent ledger of physical
zone-touch episodes. All formation features use information available no later
than the close of the impulse candle. Forward reaction labels begin with the
first one-minute candle after the touch candle closes.

Run from the repository root:

    .venv/bin/python scripts/mnq/SND_phase2_dataset.py
"""

from __future__ import annotations

import argparse
import html
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = ROOT / "data" / "mnq_dom_sample" / "full_history"
DEFAULT_MINUTE = DATA_ROOT / "ohlcv-1m" / "candles_1m.parquet"
DEFAULT_TF_DIR = DATA_ROOT / "ohlcv-resampled"
DEFAULT_PHASE1 = ROOT / "reports" / "SND_baseline"
DEFAULT_OUTPUT = ROOT / "reports" / "SND_phase2"
TIMEZONE = "America/Chicago"
SESSION_OPEN_MINUTE = 17 * 60
TF_MINUTES = {"1h": 60, "4h": 240, "Daily": 1440}
TF_FILE = {"1h": "1h", "4h": "4h", "Daily": "1d"}
HORIZONS = {"15m": 15, "30m": 30, "1h": 60, "4h": 240}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--one-minute", type=Path, default=DEFAULT_MINUTE)
    parser.add_argument("--timeframe-dir", type=Path, default=DEFAULT_TF_DIR)
    parser.add_argument("--phase1-dir", type=Path, default=DEFAULT_PHASE1)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--atr-length", type=int, default=14)
    parser.add_argument("--rvol-lookback", type=int, default=20)
    parser.add_argument("--rvol-min-periods", type=int, default=10)
    parser.add_argument("--swing-left", type=int, default=3)
    parser.add_argument("--swing-right", type=int, default=3)
    parser.add_argument("--zone-stop-buffer", type=float, default=1.0)
    parser.add_argument("--SND-stop-cap", type=float, default=100.0)
    return parser.parse_args()


def load_frame(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Required input not found: {path}")
    frame = pd.read_parquet(path).sort_index()
    if not isinstance(frame.index, pd.DatetimeIndex) or frame.index.tz is None:
        raise ValueError(f"Expected timezone-aware DatetimeIndex: {path}")
    if frame.empty or frame.index.has_duplicates:
        raise ValueError(f"Input is empty or has duplicate timestamps: {path}")
    required = {"open", "high", "low", "close", "volume"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"Missing columns in {path}: {missing}")
    return frame


def session_slot(index: pd.DatetimeIndex, width_minutes: int) -> np.ndarray:
    local = index.tz_convert(TIMEZONE)
    wall_minute = local.hour * 60 + local.minute
    return ((wall_minute - SESSION_OPEN_MINUTE) % (24 * 60)) // width_minutes


def past_only_slot_rvol(
    volume: pd.Series,
    slots: np.ndarray,
    lookback: int,
    min_periods: int,
) -> tuple[pd.Series, pd.Series]:
    work = pd.DataFrame({"volume": volume.astype(float).to_numpy(), "slot": slots}, index=volume.index)
    baseline = work.groupby("slot", sort=False)["volume"].transform(
        lambda values: values.shift(1).rolling(lookback, min_periods=min_periods).mean()
    )
    rvol = work["volume"] / baseline.replace(0.0, np.nan)
    return baseline.rename("volume_baseline"), rvol.rename("rvol")


def wilder_atr(frame: pd.DataFrame, length: int) -> pd.Series:
    previous_close = frame["close"].shift(1)
    true_range = pd.concat(
        [
            frame["high"] - frame["low"],
            (frame["high"] - previous_close).abs(),
            (frame["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    # Past and current bars only; the current value is known at candle close.
    return true_range.ewm(alpha=1.0 / length, adjust=False, min_periods=length).mean()


def prior_confirmed_swings(
    frame: pd.DataFrame,
    left: int,
    right: int,
) -> tuple[pd.Series, pd.Series]:
    window = left + right + 1
    highs = frame["high"]
    lows = frame["low"]
    pivot_high = highs.where(highs.eq(highs.rolling(window, center=True).max()))
    pivot_low = lows.where(lows.eq(lows.rolling(window, center=True).min()))
    # A pivot becomes observable `right` bars after its center. Shift once more
    # so an impulse is compared only with swings confirmed before it began.
    known_high = pivot_high.shift(right).ffill().shift(1)
    known_low = pivot_low.shift(right).ffill().shift(1)
    return known_high.rename("prior_swing_high"), known_low.rename("prior_swing_low")


def timeframe_features(frame: pd.DataFrame, label: str, args: argparse.Namespace) -> pd.DataFrame:
    result = frame.copy()
    result["atr14"] = wilder_atr(result, args.atr_length)
    slots = session_slot(result.index, TF_MINUTES[label])
    baseline, rvol = past_only_slot_rvol(
        result["volume"], slots, args.rvol_lookback, args.rvol_min_periods
    )
    result["session_slot"] = slots
    result["volume_baseline"] = baseline
    result["formation_rvol"] = rvol
    swing_high, swing_low = prior_confirmed_swings(result, args.swing_left, args.swing_right)
    result["prior_swing_high"] = swing_high
    result["prior_swing_low"] = swing_low
    result["bullish_fvg"] = result["low"] > result["high"].shift(2)
    result["bearish_fvg"] = result["high"] < result["low"].shift(2)
    result["bullish_fvg_points"] = (result["low"] - result["high"].shift(2)).clip(lower=0.0)
    result["bearish_fvg_points"] = (result["low"].shift(2) - result["high"]).clip(lower=0.0)
    result["prior_volume"] = result["volume"].shift(1)
    return result


def enrich_zones(
    zones: pd.DataFrame,
    frames: dict[str, pd.DataFrame],
    args: argparse.Namespace,
) -> pd.DataFrame:
    result = zones.copy()
    feature_rows: list[dict[str, Any]] = []
    for zone in result.itertuples(index=False):
        source = frames[zone.timeframe]
        timestamp = pd.Timestamp(zone.formed_at)
        if timestamp not in source.index:
            raise ValueError(f"Zone {zone.zone_id} formation candle is missing: {timestamp}")
        row = source.loc[timestamp]
        candle_range = float(row.high - row.low)
        atr = float(row.atr14) if pd.notna(row.atr14) else math.nan
        direction = zone.direction
        swing_level = row.prior_swing_high if direction == "long" else row.prior_swing_low
        bos = bool(row.close > swing_level) if direction == "long" and pd.notna(swing_level) else (
            bool(row.close < swing_level) if direction == "short" and pd.notna(swing_level) else False
        )
        break_points = (
            float(row.close - swing_level) if direction == "long" and bos else
            float(swing_level - row.close) if direction == "short" and bos else 0.0
        )
        fvg = bool(row.bullish_fvg) if direction == "long" else bool(row.bearish_fvg)
        fvg_points = float(row.bullish_fvg_points) if direction == "long" else float(
            row.bearish_fvg_points
        )
        close_strength = (
            (float(row.close) - float(row.low)) / candle_range if direction == "long" else
            (float(row.high) - float(row.close)) / candle_range
        ) if candle_range > 0 else math.nan
        feature_rows.append({
            "zone_id": zone.zone_id,
            "atr14": atr,
            "zone_width_atr": zone.width / atr if atr > 0 else math.nan,
            "impulse_body_atr": zone.impulse_body / atr if atr > 0 else math.nan,
            "impulse_range_atr": candle_range / atr if atr > 0 else math.nan,
            "impulse_body_fraction": zone.impulse_body / candle_range if candle_range > 0 else math.nan,
            "impulse_close_strength": close_strength,
            "formation_rvol": float(row.formation_rvol) if pd.notna(row.formation_rvol) else math.nan,
            "formation_volume_baseline": float(row.volume_baseline) if pd.notna(row.volume_baseline) else math.nan,
            "prior_volume": int(row.prior_volume) if pd.notna(row.prior_volume) else None,
            "session_slot": int(row.session_slot),
            "prior_confirmed_swing": float(swing_level) if pd.notna(swing_level) else math.nan,
            "bos": bos,
            "bos_break_points": break_points,
            "bos_break_atr": break_points / atr if atr > 0 else math.nan,
            "fvg": fvg,
            "fvg_points": fvg_points,
            "fvg_atr": fvg_points / atr if atr > 0 else math.nan,
        })
    features = pd.DataFrame(feature_rows)
    result = result.merge(features, on="zone_id", how="left", validate="one_to_one")
    return add_zone_context(result, args)


def add_zone_context(zones: pd.DataFrame, args: argparse.Namespace) -> pd.DataFrame:
    result = zones.copy()
    ranks = result["timeframe"].map(TF_MINUTES).to_numpy()
    directions = result["direction"].to_numpy()
    proximal = result["proximal"].to_numpy(dtype=float)
    distal = result["distal"].to_numpy(dtype=float)
    available = pd.to_datetime(result["available_at"], utc=True)
    removed = pd.to_datetime(result["removed_at"], utc=True)
    available_ns = available.astype("int64").to_numpy()
    removed_ns = removed.astype("int64").to_numpy()
    nat = np.iinfo(np.int64).min

    nested_counts = np.zeros(len(result), dtype=np.int16)
    highest_parent = np.zeros(len(result), dtype=np.int16)
    opposing_room = np.full(len(result), np.nan)

    for i in range(len(result)):
        active = (available_ns <= available_ns[i]) & (
            (removed_ns == nat) | (removed_ns > available_ns[i])
        )
        same = active & (directions == directions[i]) & (ranks > ranks[i])
        if directions[i] == "long":
            contained = same & (proximal[i] <= proximal) & (distal[i] >= distal)
            opposing = active & (directions == "short") & (proximal > proximal[i])
            distances = proximal[opposing] - proximal[i]
        else:
            contained = same & (proximal[i] >= proximal) & (distal[i] <= distal)
            opposing = active & (directions == "long") & (proximal < proximal[i])
            distances = proximal[i] - proximal[opposing]
        nested_counts[i] = int(contained.sum())
        if contained.any():
            highest_parent[i] = int(ranks[contained].max())
        if len(distances):
            opposing_room[i] = float(distances.min())

    result["nested_htf_count"] = nested_counts
    rank_label = {60: "1h", 240: "4h", 1440: "Daily", 0: None}
    result["highest_parent_timeframe"] = [rank_label[int(value)] for value in highest_parent]
    result["opposing_room_at_formation_points"] = opposing_room
    structural_risk = result["width"] + args.zone_stop_buffer
    result["opposing_room_at_formation_r"] = opposing_room / structural_risk
    return result


def minute_features(minute: pd.DataFrame, five: pd.DataFrame, args: argparse.Namespace) -> tuple[pd.DataFrame, pd.DataFrame]:
    result = minute.copy()
    minute_slots = session_slot(result.index, 1)
    baseline, rvol = past_only_slot_rvol(
        result["volume"], minute_slots, args.rvol_lookback, args.rvol_min_periods
    )
    result["minute_rvol"] = rvol

    five_result = five.copy()
    five_slots = session_slot(five_result.index, 5)
    _, five_rvol = past_only_slot_rvol(
        five_result["volume"], five_slots, args.rvol_lookback, args.rvol_min_periods
    )
    five_result["five_minute_rvol"] = five_rvol
    five_result["feature_available_at"] = five_result.index.tz_convert("UTC") + pd.Timedelta(minutes=5)
    return result, five_result[["feature_available_at", "five_minute_rvol"]]


def touch_episodes(
    zones: pd.DataFrame,
    minute: pd.DataFrame,
) -> pd.DataFrame:
    index_ns = minute.index.tz_convert("UTC").asi8
    highs = minute["high"].to_numpy(dtype=float)
    lows = minute["low"].to_numpy(dtype=float)
    events: list[dict[str, Any]] = []

    for number, zone in enumerate(zones.itertuples(index=False), start=1):
        start = int(np.searchsorted(index_ns, pd.Timestamp(zone.available_at).value, side="left"))
        if pd.notna(zone.removed_at):
            end = int(np.searchsorted(index_ns, pd.Timestamp(zone.removed_at).value, side="left"))
        else:
            end = len(index_ns)
        if start >= end:
            continue
        if zone.direction == "long":
            touched = (lows[start:end] <= zone.proximal) & (highs[start:end] >= zone.distal)
        else:
            touched = (highs[start:end] >= zone.proximal) & (lows[start:end] <= zone.distal)
        # Array adjacency is not necessarily time adjacency around maintenance
        # breaks, weekends, or missing bars. A gap always starts a new episode.
        timestamps = index_ns[start:end]
        gap_before = np.r_[True, np.diff(timestamps) != pd.Timedelta(minutes=1).value]
        gap_after = np.r_[gap_before[1:], True]
        starts = np.flatnonzero(touched & (gap_before | np.r_[True, ~touched[:-1]]))
        if not len(starts):
            continue
        ends = np.flatnonzero(touched & (gap_after | np.r_[~touched[1:], True]))
        previous_end = start - 1
        for touch_number, (relative_start, relative_end) in enumerate(zip(starts, ends), start=1):
            touch_pos = start + int(relative_start)
            episode_end = start + int(relative_end)
            departure_start = previous_end + 1
            if touch_pos > departure_start:
                if zone.direction == "long":
                    departure = max(float(highs[departure_start:touch_pos].max() - zone.proximal), 0.0)
                else:
                    departure = max(float(zone.proximal - lows[departure_start:touch_pos].min()), 0.0)
            else:
                departure = 0.0
            events.append({
                "zone_id": zone.zone_id,
                "direction": zone.direction,
                "timeframe": zone.timeframe,
                "touch_number": touch_number,
                "touch_pos": touch_pos,
                "episode_end_pos": episode_end,
                "touch_time": minute.index[touch_pos].tz_convert("UTC"),
                "touch_confirmed_at": minute.index[touch_pos].tz_convert("UTC") + pd.Timedelta(minutes=1),
                "episode_end_time": minute.index[episode_end].tz_convert("UTC") + pd.Timedelta(minutes=1),
                "episode_bars": episode_end - touch_pos + 1,
                "bars_away_before_touch": touch_pos - departure_start,
                "departure_before_touch_points": departure,
                "departure_before_touch_zone_widths": departure / zone.width if zone.width > 0 else math.nan,
            })
            previous_end = episode_end
        if number % 2_000 == 0:
            print(f"  scanned {number:,}/{len(zones):,} zones for touch episodes", flush=True)
    return pd.DataFrame(events).sort_values(["touch_time", "zone_id"]).reset_index(drop=True)


def add_touch_features(
    retests: pd.DataFrame,
    zones: pd.DataFrame,
    minute: pd.DataFrame,
    five_features: pd.DataFrame,
    phase1_tests: pd.DataFrame,
    args: argparse.Namespace,
) -> pd.DataFrame:
    result = retests.merge(
        zones[[
            "zone_id", "formed_at", "available_at", "removed_at", "removal_reason",
            "proximal", "distal", "width", "atr14", "roll_formation",
            "nested_htf_count", "bos", "fvg", "formation_rvol",
        ]],
        on="zone_id",
        how="left",
        validate="many_to_one",
        suffixes=("", "_zone"),
    )
    positions = result["touch_pos"].to_numpy(dtype=int)
    opens = minute["open"].to_numpy(dtype=float)[positions]
    highs = minute["high"].to_numpy(dtype=float)[positions]
    lows = minute["low"].to_numpy(dtype=float)[positions]
    closes = minute["close"].to_numpy(dtype=float)[positions]
    volumes = minute["volume"].to_numpy()[positions]
    minute_rvol = minute["minute_rvol"].to_numpy(dtype=float)[positions]
    ranges = highs - lows
    is_long = result["direction"].eq("long").to_numpy()
    directional_body = np.where(is_long, closes - opens, opens - closes)
    rejection_wick = np.where(is_long, np.minimum(opens, closes) - lows, highs - np.maximum(opens, closes))
    close_strength = np.divide(
        np.where(is_long, closes - lows, highs - closes),
        ranges,
        out=np.full(len(result), np.nan),
        where=ranges > 0,
    )
    result["touch_open"] = opens
    result["touch_high"] = highs
    result["touch_low"] = lows
    result["touch_close"] = closes
    result["touch_volume"] = volumes
    result["touch_minute_rvol"] = minute_rvol
    result["touch_directional_body_points"] = directional_body
    result["touch_rejection_wick_points"] = rejection_wick
    result["touch_rejection_wick_fraction"] = np.divide(
        rejection_wick, ranges, out=np.full(len(result), np.nan), where=ranges > 0
    )
    result["touch_close_strength"] = close_strength
    result["touch_reclaims_proximal"] = np.where(
        is_long, closes >= result["proximal"].to_numpy(), closes <= result["proximal"].to_numpy()
    )
    result["age_minutes"] = (
        pd.to_datetime(result["touch_time"], utc=True) - pd.to_datetime(result["available_at"], utc=True)
    ).dt.total_seconds() / 60.0
    result["minutes_to_removal"] = (
        pd.to_datetime(result["removed_at"], utc=True) - pd.to_datetime(result["touch_time"], utc=True)
    ).dt.total_seconds() / 60.0

    # Most recent fully completed 5m candle; current partial 5m volume is never used.
    lookup = result[["touch_time"]].copy().sort_values("touch_time")
    five_lookup = five_features.sort_values("feature_available_at")
    merged = pd.merge_asof(
        lookup,
        five_lookup,
        left_on="touch_time",
        right_on="feature_available_at",
        direction="backward",
    )
    result.loc[lookup.index, "prior_5m_rvol"] = merged["five_minute_rvol"].to_numpy()

    # Associate SND's consumed tests with their enclosing physical touch episode.
    result["SND_tests_in_episode"] = 0
    result["SND_trade_executed"] = False
    result["SND_not_executed_reason"] = None
    tests_by_zone = {
        int(zone_id): group.sort_values("test_time")
        for zone_id, group in phase1_tests.groupby("zone_id")
    }
    for idx, row in result.iterrows():
        tests = tests_by_zone.get(int(row.zone_id))
        if tests is None:
            continue
        inside = tests[
            (tests["test_time"] >= row.touch_time) & (tests["test_time"] < row.episode_end_time)
        ]
        if len(inside):
            result.at[idx, "SND_tests_in_episode"] = len(inside)
            result.at[idx, "SND_trade_executed"] = bool(inside["executed"].any())
            reasons = sorted({str(value) for value in inside["not_executed_reason"].dropna()})
            result.at[idx, "SND_not_executed_reason"] = ",".join(reasons) if reasons else None
    return add_opposing_room(result, zones, args)


def add_opposing_room(
    retests: pd.DataFrame,
    zones: pd.DataFrame,
    args: argparse.Namespace,
) -> pd.DataFrame:
    result = retests.sort_values("touch_time").copy()
    zone_rows = zones.sort_values("available_at").reset_index(drop=True)
    removals = zones[zones["removed_at"].notna()].sort_values("removed_at").reset_index(drop=True)
    active: dict[int, Any] = {}
    activation_cursor = 0
    removal_cursor = 0
    rooms: list[float] = []

    for row in result.itertuples(index=False):
        timestamp = pd.Timestamp(row.touch_time)
        while activation_cursor < len(zone_rows) and pd.Timestamp(
            zone_rows.iloc[activation_cursor].available_at
        ) <= timestamp:
            zone = zone_rows.iloc[activation_cursor]
            active[int(zone.zone_id)] = zone
            activation_cursor += 1
        while removal_cursor < len(removals) and pd.Timestamp(
            removals.iloc[removal_cursor].removed_at
        ) <= timestamp:
            active.pop(int(removals.iloc[removal_cursor].zone_id), None)
            removal_cursor += 1

        if row.direction == "long":
            distances = [
                float(zone.proximal - row.proximal)
                for zone in active.values()
                if zone.direction == "short" and zone.proximal > row.proximal
            ]
        else:
            distances = [
                float(row.proximal - zone.proximal)
                for zone in active.values()
                if zone.direction == "long" and zone.proximal < row.proximal
            ]
        rooms.append(min(distances) if distances else math.nan)

    result["opposing_room_at_touch_points"] = rooms
    structural_risk = result["width"] + args.zone_stop_buffer
    result["structural_risk_points"] = structural_risk
    result["SND_risk_points"] = structural_risk.clip(upper=args.SND_stop_cap)
    result["opposing_room_at_touch_r"] = result["opposing_room_at_touch_points"] / structural_risk
    return result.sort_index()


def add_forward_labels(
    retests: pd.DataFrame,
    minute: pd.DataFrame,
) -> pd.DataFrame:
    result = retests.copy()
    index = minute.index.tz_convert("UTC")
    index_ns = index.asi8
    highs = minute["high"].to_numpy(dtype=float)
    lows = minute["low"].to_numpy(dtype=float)

    for label in HORIZONS:
        result[f"forward_bars_{label}"] = 0
        result[f"mfe_points_{label}"] = np.nan
        result[f"mae_points_{label}"] = np.nan
        result[f"mfe_r_{label}"] = np.nan
        result[f"mae_r_{label}"] = np.nan

    result["hit_1r_before_stop_4h"] = False
    result["hit_2r_before_stop_4h"] = False
    result["first_4h_barrier"] = "none"
    result["minutes_to_first_4h_barrier"] = np.nan

    for count, (idx, row) in enumerate(result.iterrows(), start=1):
        confirmation = pd.Timestamp(row.touch_confirmed_at)
        start = int(np.searchsorted(index_ns, confirmation.value, side="left"))
        direction = row.direction
        entry = float(row.proximal)
        risk = float(row.structural_risk_points)

        for label, minutes in HORIZONS.items():
            end_time = confirmation + pd.Timedelta(minutes=minutes)
            end = int(np.searchsorted(index_ns, end_time.value, side="left"))
            if start >= end:
                continue
            window_high = highs[start:end]
            window_low = lows[start:end]
            if direction == "long":
                mfe = max(float(window_high.max() - entry), 0.0)
                mae = max(float(entry - window_low.min()), 0.0)
            else:
                mfe = max(float(entry - window_low.min()), 0.0)
                mae = max(float(window_high.max() - entry), 0.0)
            result.at[idx, f"forward_bars_{label}"] = end - start
            result.at[idx, f"mfe_points_{label}"] = mfe
            result.at[idx, f"mae_points_{label}"] = mae
            result.at[idx, f"mfe_r_{label}"] = mfe / risk
            result.at[idx, f"mae_r_{label}"] = mae / risk

        end_4h = int(np.searchsorted(
            index_ns, (confirmation + pd.Timedelta(hours=4)).value, side="left"
        ))
        if start < end_4h:
            window_high = highs[start:end_4h]
            window_low = lows[start:end_4h]
            if direction == "long":
                stop_hits = np.flatnonzero(window_low <= entry - risk)
                one_hits = np.flatnonzero(window_high >= entry + risk)
                two_hits = np.flatnonzero(window_high >= entry + 2 * risk)
            else:
                stop_hits = np.flatnonzero(window_high >= entry + risk)
                one_hits = np.flatnonzero(window_low <= entry - risk)
                two_hits = np.flatnonzero(window_low <= entry - 2 * risk)
            stop_pos = int(stop_hits[0]) if len(stop_hits) else None
            one_pos = int(one_hits[0]) if len(one_hits) else None
            two_pos = int(two_hits[0]) if len(two_hits) else None
            one_before = one_pos is not None and (stop_pos is None or one_pos < stop_pos)
            two_before = two_pos is not None and (stop_pos is None or two_pos < stop_pos)
            result.at[idx, "hit_1r_before_stop_4h"] = one_before
            result.at[idx, "hit_2r_before_stop_4h"] = two_before
            candidates = [("stop", stop_pos), ("1r", one_pos)]
            candidates = [(name, position) for name, position in candidates if position is not None]
            if candidates:
                # Stop first on a same-minute ambiguity, matching the baseline convention.
                name, position = min(candidates, key=lambda value: (value[1], 0 if value[0] == "stop" else 1))
                result.at[idx, "first_4h_barrier"] = name
                barrier_time = index[start + position] + pd.Timedelta(minutes=1)
                result.at[idx, "minutes_to_first_4h_barrier"] = (
                    barrier_time - confirmation
                ).total_seconds() / 60.0
        if count % 10_000 == 0:
            print(f"  labeled {count:,}/{len(result):,} retests", flush=True)
    return result


def finalize_zone_outcomes(zones: pd.DataFrame, retests: pd.DataFrame) -> pd.DataFrame:
    result = zones.copy()
    grouped = retests.groupby("zone_id")
    counts = grouped.size().rename("physical_retest_count")
    first = grouped["touch_time"].min().rename("first_retest_at")
    result = result.merge(counts, on="zone_id", how="left").merge(first, on="zone_id", how="left")
    result["physical_retest_count"] = result["physical_retest_count"].fillna(0).astype(int)
    result["minutes_to_first_retest"] = (
        pd.to_datetime(result["first_retest_at"], utc=True) - pd.to_datetime(result["available_at"], utc=True)
    ).dt.total_seconds() / 60.0
    result["lifespan_minutes"] = (
        pd.to_datetime(result["removed_at"], utc=True) - pd.to_datetime(result["available_at"], utc=True)
    ).dt.total_seconds() / 60.0
    result["invalidated"] = result["removal_reason"].isin(["wick_or_close", "gap"])
    return result


def summary_tables(zones: pd.DataFrame, retests: pd.DataFrame) -> dict[str, pd.DataFrame]:
    formation = zones.groupby("timeframe").agg(
        zones=("zone_id", "size"),
        bos_rate=("bos", "mean"),
        fvg_rate=("fvg", "mean"),
        nested_rate=("nested_htf_count", lambda values: (values > 0).mean()),
        median_body_atr=("impulse_body_atr", "median"),
        median_width_atr=("zone_width_atr", "median"),
        median_rvol=("formation_rvol", "median"),
        retested_rate=("physical_retest_count", lambda values: (values > 0).mean()),
    )
    retest = retests.groupby("timeframe").agg(
        retests=("zone_id", "size"),
        first_touch_share=("touch_number", lambda values: (values == 1).mean()),
        reclaim_rate=("touch_reclaims_proximal", "mean"),
        hit_1r_4h=("hit_1r_before_stop_4h", "mean"),
        hit_2r_4h=("hit_2r_before_stop_4h", "mean"),
        median_mfe_r_4h=("mfe_r_4h", "median"),
        median_mae_r_4h=("mae_r_4h", "median"),
        median_age_minutes=("age_minutes", "median"),
    )
    return {"formation": formation, "retest": retest}


def html_table(frame: pd.DataFrame, percent_columns: set[str]) -> str:
    headers = "".join(f"<th>{html.escape(str(column).replace('_', ' '))}</th>" for column in frame.columns)
    rows = []
    for idx, row in frame.iterrows():
        cells = []
        for column, value in row.items():
            if pd.isna(value):
                text = "n/a"
            elif column in percent_columns:
                text = f"{value:.1%}"
            elif column in {"zones", "retests"}:
                text = f"{int(value):,}"
            else:
                text = f"{value:,.2f}"
            cells.append(f"<td>{text}</td>")
        rows.append(f"<tr><th>{html.escape(str(idx))}</th>{''.join(cells)}</tr>")
    return f"<div class='scroll'><table><thead><tr><th>timeframe</th>{headers}</tr></thead><tbody>{''.join(rows)}</tbody></table></div>"


def write_outputs(
    zones: pd.DataFrame,
    retests: pd.DataFrame,
    args: argparse.Namespace,
) -> None:
    args.output_dir.mkdir(parents=True, exist_ok=True)
    zones.to_parquet(args.output_dir / "zones_enriched.parquet", index=False)
    retests.to_parquet(args.output_dir / "retests_enriched.parquet", index=False)
    tables = summary_tables(zones, retests)
    for name, table in tables.items():
        table.to_csv(args.output_dir / f"{name}_summary.csv")

    feature_dictionary = {
        "timing": {
            "formation_features": "Known by the close of the source-timeframe impulse candle.",
            "touch_features": "Known by touch_confirmed_at, one minute after the touch candle begins.",
            "forward_labels": "Start at touch_confirmed_at and are never entry-time features.",
        },
        "rvol": f"Volume divided by the mean of the prior {args.rvol_lookback} observations in the same session-time slot; minimum {args.rvol_min_periods}.",
        "swings": f"Pivot with {args.swing_left} left and {args.swing_right} right bars; BOS uses only pivots confirmed before the impulse bar.",
        "structural_risk": f"Zone width plus {args.zone_stop_buffer:g} point; separate from SND's {args.SND_stop_cap:g}-point capped risk.",
        "touch_episode": "A continuous run of one-minute candles intersecting a still-active zone counts once.",
        "forward_window": "MFE/MAE and barrier labels use the first bars after the touch candle closes.",
    }
    (args.output_dir / "feature_dictionary.json").write_text(json.dumps(feature_dictionary, indent=2) + "\n")

    pct_formation = {"bos_rate", "fvg_rate", "nested_rate", "retested_rate"}
    pct_retest = {"first_touch_share", "reclaim_rate", "hit_1r_4h", "hit_2r_4h"}
    overall = {
        "zones": len(zones),
        "retests": len(retests),
        "zones_retested": int((zones.physical_retest_count > 0).sum()),
        "bos_zones": int(zones.bos.sum()),
        "fvg_zones": int(zones.fvg.sum()),
        "nested_zones": int((zones.nested_htf_count > 0).sum()),
        "SND_executed_episodes": int(retests.SND_trade_executed.sum()),
        "one_r_successes": int(retests.hit_1r_before_stop_4h.sum()),
    }
    (args.output_dir / "summary.json").write_text(json.dumps(overall, indent=2) + "\n")

    style = """
    :root{color-scheme:light;--bg:#f5f6f8;--panel:#fff;--text:#121826;--muted:#687386;--line:#dfe3e8;--blue:#4c8bf5}
    @media(prefers-color-scheme:dark){:root{color-scheme:dark;--bg:#101216;--panel:#181b21;--text:#f4f6f8;--muted:#9aa4b2;--line:#303640;--blue:#70a4ff}}
    *{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
    main{max-width:1120px;margin:auto;padding:36px 20px 80px}h1{font-size:30px;letter-spacing:-.03em;margin:4px 0}h2{margin:38px 0 4px;font-size:20px}
    .eyebrow{text-transform:uppercase;letter-spacing:.1em;font-size:11px;font-weight:700;color:var(--blue)}.lead,.note{color:var(--muted);max-width:850px}
    .tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(145px,1fr));gap:10px;margin:20px 0}.tile{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:13px 15px}
    .tile span{display:block;color:var(--muted);font-size:11px;text-transform:uppercase}.tile strong{display:block;font-size:22px;margin-top:3px}.scroll{overflow:auto;border:1px solid var(--line);border-radius:10px;margin:12px 0}
    table{border-collapse:collapse;width:100%;background:var(--panel);font-variant-numeric:tabular-nums}th,td{padding:8px 11px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}thead th{color:var(--muted);font-size:10px;text-transform:uppercase;background:color-mix(in srgb,var(--panel) 82%,var(--line))}th:first-child{text-align:left}tbody tr:last-child>*{border-bottom:0}
    code{background:color-mix(in srgb,var(--panel) 80%,var(--line));padding:2px 5px;border-radius:4px}.method{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px 16px}.method li{margin:7px 0}
    """
    tiles = "".join(
        f"<div class='tile'><span>{label}</span><strong>{value:,}</strong></div>"
        for label, value in [
            ("Zones", overall["zones"]), ("Touch episodes", overall["retests"]),
            ("Zones retested", overall["zones_retested"]), ("BOS zones", overall["bos_zones"]),
            ("FVG zones", overall["fvg_zones"]), ("HTF nested", overall["nested_zones"]),
        ]
    )
    page = f"""<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
    <title>SND Phase 2 feature dataset</title><style>{style}</style></head><body><main>
    <div class='eyebrow'>MNQ · SND strategy lab</div><h1>Phase 2 feature dataset</h1>
    <p class='lead'>The baseline trades are unchanged. This report describes the point-in-time zone and retest information prepared for controlled confluence experiments.</p>
    <div class='tiles'>{tiles}</div>
    <h2>Formation coverage</h2><p class='note'>Features fixed when the source candle closes; no later zone outcome is used.</p>
    {html_table(tables['formation'], pct_formation)}
    <h2>Retest reactions</h2><p class='note'>Independent physical touch episodes, including events SND did not trade.</p>
    {html_table(tables['retest'], pct_retest)}
    <h2>Point-in-time contract</h2><div class='method'><ul>
    <li>Formation RVOL uses only earlier volume from the same session-time slot.</li>
    <li>BOS uses only swings confirmed before the impulse candle.</li>
    <li>A continuous overlap with a zone is one touch episode.</li>
    <li>Touch-candle rejection is available one minute after the touch begins.</li>
    <li>MFE/MAE and 1R/2R outcomes begin after that confirmation time and are labels, never filters.</li>
    <li>Contract-roll formations remain in the data but carry <code>roll_formation=true</code>.</li>
    </ul></div>
    <h2>Outputs</h2><div class='method'><code>zones_enriched.parquet</code> · <code>retests_enriched.parquet</code> · summary CSVs · <code>feature_dictionary.json</code></div>
    </main></body></html>"""
    (args.output_dir / "index.html").write_text(page)


def main() -> None:
    args = parse_args()
    if args.atr_length < 1 or args.rvol_lookback < 1 or args.rvol_min_periods < 1:
        raise ValueError("ATR and RVOL lengths must be positive")
    if args.swing_left < 1 or args.swing_right < 1:
        raise ValueError("Swing left/right must be positive")

    print("Loading Phase 1 ledgers and candle data...", flush=True)
    zones = pd.read_parquet(args.phase1_dir / "zones.parquet")
    tests = pd.read_parquet(args.phase1_dir / "zone_tests.parquet")
    for column in ("formed_at", "available_at", "removed_at"):
        zones[column] = pd.to_datetime(zones[column], utc=True)
    tests["test_time"] = pd.to_datetime(tests["test_time"], utc=True)

    raw_frames = {
        label: load_frame(args.timeframe_dir / f"candles_{TF_FILE[label]}.parquet")
        for label in TF_MINUTES
    }
    frames = {
        label: timeframe_features(frame, label, args)
        for label, frame in raw_frames.items()
    }
    print("Enriching formation-time zone records...", flush=True)
    zones = enrich_zones(zones, frames, args)

    minute_raw = load_frame(args.one_minute)
    five_raw = load_frame(args.timeframe_dir / "candles_5m.parquet")
    print("Calculating past-only intraday RVOL...", flush=True)
    minute, five_features = minute_features(minute_raw, five_raw, args)
    print("Finding independent physical touch episodes...", flush=True)
    retests = touch_episodes(zones, minute)
    print(f"Found {len(retests):,} touch episodes; adding entry-time features...", flush=True)
    retests = add_touch_features(retests, zones, minute, five_features, tests, args)
    print("Adding forward reaction labels...", flush=True)
    retests = add_forward_labels(retests, minute)
    zones = finalize_zone_outcomes(zones, retests)
    print("Writing Phase 2 datasets and HTML coverage report...", flush=True)
    write_outputs(zones, retests, args)
    print(
        f"DONE | zones={len(zones):,} | retests={len(retests):,} | "
        f"columns={len(retests.columns)} -> {args.output_dir}"
    )


if __name__ == "__main__":
    main()
