"""Test the Market Profile folklore on MNQ: the 80% rule and naked-POC revisits.

Two widely repeated claims are checked against the local one-minute MNQ archive
(Databento GLBX.MDP3, MNQ.v.0, May 2019 - September 2026):

  1. "80% rule" -- if price opens outside the prior session's value area, trades
     back inside it, and holds there for two consecutive 30-minute periods, there
     is roughly an 80% chance it traverses the full value area.
  2. "Naked POC" -- roughly 80% of untouched prior-session POCs are revisited
     within 10 sessions.

Neither claim has a published dataset behind it, so this script does three
things a vendor stat sheet does not: it reports Wilson intervals rather than a
bare percentage, it runs every headline number against a matched control that
strips out the mechanical part of the result, and it converts the signal into a
costed trade ledger.

Profiles are built on the RTH session (08:30-15:00 America/Chicago), under both
volume and TPO definitions, so the answer does not hinge on one vendor's
value-area convention. Prices are back-adjusted at the 29 contract rolls so that
prior-session levels stay comparable across a roll.

Run from the repository root:

    .venv/bin/python scripts/mnq/mnq_market_profile_backtest.py
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = ROOT / "data" / "mnq_dom_sample" / "full_history"
DEFAULT_ONE_MINUTE = DATA_ROOT / "ohlcv-1m" / "candles_1m.parquet"
DEFAULT_OUTPUT_DIR = ROOT / "reports" / "mnq_market_profile"

TIMEZONE = "America/Chicago"
TICK_SIZE = 0.25
SESSION_OFFSET = pd.Timedelta(hours=7)  # 17:00 CT starts the next session date
OHLCV = ["open", "high", "low", "close", "volume"]
PROFILE_MODES = ("volume", "tpo")
ACCEPT_MODES = ("close", "range")
SURVIVAL_LAGS = (1, 2, 3, 5, 10, 20, 50)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--one-minute", type=Path, default=DEFAULT_ONE_MINUTE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--start", default=None, help="first session, ISO date")
    parser.add_argument("--end", default=None, help="last session, ISO date")

    parser.add_argument("--rth-start", default="08:30", help="RTH open, America/Chicago")
    parser.add_argument("--rth-end", default="15:00", help="RTH close, America/Chicago")
    parser.add_argument("--bracket-minutes", type=int, default=30)
    parser.add_argument("--min-rth-minutes", type=int, default=380,
                        help="sessions with fewer RTH minutes are holidays/half days")
    parser.add_argument("--price-step", type=float, default=1.0,
                        help="profile row height in index points")
    parser.add_argument("--va-percent", type=float, default=0.70)
    parser.add_argument("--profile-mode", choices=PROFILE_MODES, default="volume",
                        help="value-area definition used for the trade ledgers")
    parser.add_argument("--accept-mode", choices=ACCEPT_MODES, default="close",
                        help="close: bracket close inside VA; range: whole bracket inside")
    parser.add_argument("--confirm-brackets", type=int, default=2,
                        help="consecutive accepting brackets the rule requires")
    parser.add_argument("--no-roll-adjust", action="store_true",
                        help="leave contract roll gaps in the price series")

    parser.add_argument("--stop-buffer-points", type=float, default=5.0,
                        help="80%% rule stop sits this far beyond the entry-side VA edge")
    parser.add_argument("--point-value", type=float, default=2.0, help="MNQ $/point")
    parser.add_argument("--commission-per-side", type=float, default=1.25)
    parser.add_argument("--slippage-ticks", type=float, default=1.0, help="per side")

    parser.add_argument("--max-lag", type=int, default=60,
                        help="forward sessions scanned for a naked-POC revisit")
    parser.add_argument("--npoc-touch-scope", choices=("full", "rth"), default="full",
                        help="full: any Globex trade; rth: day-session trades only")
    parser.add_argument("--npoc-max-distance", type=float, default=100.0,
                        help="nPOC trade only taken when the target is this close at the open")
    parser.add_argument("--npoc-stop-multiple", type=float, default=1.0,
                        help="nPOC trade stop, as a multiple of the distance to target")
    return parser.parse_args()


def parse_clock(value: str) -> int:
    hours, minutes = value.split(":")
    total = int(hours) * 60 + int(minutes)
    if not 0 <= total <= 24 * 60:
        raise ValueError(f"Clock time out of range: {value}")
    return total


def validate_args(args: argparse.Namespace) -> None:
    if parse_clock(args.rth_start) >= parse_clock(args.rth_end):
        raise ValueError("--rth-start must precede --rth-end")
    span = parse_clock(args.rth_end) - parse_clock(args.rth_start)
    if span % args.bracket_minutes:
        raise ValueError("RTH span must divide evenly into --bracket-minutes")
    if not 0.0 < args.va_percent < 1.0:
        raise ValueError("--va-percent must lie strictly between 0 and 1")
    for name in ("price_step", "point_value", "npoc_max_distance"):
        if getattr(args, name) <= 0:
            raise ValueError(f"--{name.replace('_', '-')} must be positive")
    for name in ("stop_buffer_points", "commission_per_side", "slippage_ticks",
                 "npoc_stop_multiple"):
        if getattr(args, name) < 0:
            raise ValueError(f"--{name.replace('_', '-')} must not be negative")
    if args.max_lag < 1:
        raise ValueError("--max-lag must be at least 1")
    if args.confirm_brackets < 1:
        raise ValueError("--confirm-brackets must be at least 1")


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------

def load_minutes(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"MNQ one-minute parquet not found: {path}")
    frame = pd.read_parquet(path, columns=OHLCV + ["instrument_id"]).sort_index()
    if not isinstance(frame.index, pd.DatetimeIndex) or frame.index.tz is None:
        raise ValueError("Source index must be a timezone-aware DatetimeIndex")
    if frame.index.has_duplicates:
        raise ValueError("Source contains duplicate timestamps")
    if frame[OHLCV].isna().any().any():
        raise ValueError("Source contains missing OHLCV values")
    invalid = (
        (frame["high"] < frame[["open", "close", "low"]].max(axis=1))
        | (frame["low"] > frame[["open", "close", "high"]].min(axis=1))
    )
    if invalid.any():
        raise ValueError(f"Source contains {int(invalid.sum())} invalid OHLC bars")
    return frame


def roll_adjustment(frame: pd.DataFrame) -> tuple[np.ndarray, list[dict[str, Any]]]:
    """Back-adjust to the final contract using the gap at each instrument change.

    The volume-rolled series switches instrument between two adjacent one-minute
    bars, always outside RTH, so the gap measured across that boundary is the
    calendar spread plus one minute of drift.
    """
    ids = frame["instrument_id"].to_numpy()
    close = frame["close"].to_numpy()
    changes = np.flatnonzero(ids[1:] != ids[:-1]) + 1
    adjustment = np.zeros(len(frame), dtype=float)
    rolls: list[dict[str, Any]] = []
    for pos in changes:
        gap = round((close[pos] - close[pos - 1]) / TICK_SIZE) * TICK_SIZE
        adjustment[:pos] += gap
        rolls.append({
            "timestamp": frame.index[pos].isoformat(),
            "from_instrument": int(ids[pos - 1]),
            "to_instrument": int(ids[pos]),
            "gap_points": gap,
        })
    return adjustment, rolls


def prepare(args: argparse.Namespace) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    frame = load_minutes(args.one_minute)
    adjustment, rolls = roll_adjustment(frame)
    if args.no_roll_adjust:
        adjustment = np.zeros(len(frame), dtype=float)
    for column in ("open", "high", "low", "close"):
        frame[column] = frame[column].to_numpy() + adjustment

    local = frame.index.tz_convert(TIMEZONE)
    frame["session"] = (local + SESSION_OFFSET).normalize().tz_localize(None)
    minute_of_day = local.hour * 60 + local.minute
    rth_start, rth_end = parse_clock(args.rth_start), parse_clock(args.rth_end)
    frame["is_rth"] = (minute_of_day >= rth_start) & (minute_of_day < rth_end)
    frame["bracket"] = np.where(
        frame["is_rth"], (minute_of_day - rth_start) // args.bracket_minutes, -1
    )

    if args.start is not None:
        frame = frame[frame["session"] >= pd.Timestamp(args.start)]
    if args.end is not None:
        frame = frame[frame["session"] <= pd.Timestamp(args.end)]
    if frame.empty:
        raise ValueError("No bars remain after applying the session window")
    return frame, rolls


# --------------------------------------------------------------------------
# Profiles
# --------------------------------------------------------------------------

@dataclass
class SessionProfile:
    session: pd.Timestamp
    minutes: int
    valid: bool
    open: float
    high: float
    low: float
    close: float
    volume: float
    levels: dict[str, dict[str, float]]  # profile mode -> poc/vah/val

    def poc(self, mode: str) -> float:
        return self.levels[mode]["poc"]

    def value_area(self, mode: str) -> tuple[float, float]:
        entry = self.levels[mode]
        return entry["val"], entry["vah"]


def value_area_bounds(counts: np.ndarray, poc_index: int, fraction: float) -> tuple[int, int]:
    """Steidlmayer expansion: repeatedly take the richer of the two adjacent pairs."""
    total = float(counts.sum())
    if total <= 0.0:
        return poc_index, poc_index
    target = total * fraction
    running = float(counts[poc_index])
    size = len(counts)
    up, down = poc_index + 1, poc_index - 1
    while running < target and (up < size or down >= 0):
        up_sum = float(counts[up:up + 2].sum()) if up < size else -1.0
        down_sum = float(counts[max(down - 1, 0):down + 1].sum()) if down >= 0 else -1.0
        if up_sum >= down_sum:
            running += up_sum
            up += 2
        else:
            running += down_sum
            down -= 2
    return max(down + 1, 0), min(up - 1, size - 1)


def spread_evenly(low_index: np.ndarray, high_index: np.ndarray, weight: np.ndarray,
                  base: int, size: int) -> np.ndarray:
    """Accumulate weight spread uniformly across each bar's rows, via a difference array."""
    diff = np.zeros(size + 1, dtype=float)
    share = weight / (high_index - low_index + 1).astype(float)
    np.add.at(diff, low_index - base, share)
    np.add.at(diff, high_index - base + 1, -share)
    return np.cumsum(diff)[:size]


def pick_poc(counts: np.ndarray) -> int:
    """Highest row; ties break toward the volume-weighted centre of the profile."""
    candidates = np.flatnonzero(counts == counts.max())
    if len(candidates) == 1:
        return int(candidates[0])
    weights = counts.sum()
    centre = float((np.arange(len(counts)) * counts).sum() / weights) if weights else 0.0
    return int(candidates[np.argmin(np.abs(candidates - centre))])


def build_profiles(frame: pd.DataFrame, args: argparse.Namespace) -> list[SessionProfile]:
    rth = frame[frame["is_rth"]]
    step = args.price_step
    low_index = np.rint(rth["low"].to_numpy() / step).astype(np.int64)
    high_index = np.rint(rth["high"].to_numpy() / step).astype(np.int64)
    volume = rth["volume"].to_numpy().astype(float)
    bracket = rth["bracket"].to_numpy()

    profiles: list[SessionProfile] = []
    codes, sessions = pd.factorize(rth["session"], sort=True)
    order = np.argsort(codes, kind="stable")
    starts = np.searchsorted(codes[order], np.arange(len(sessions)), side="left")
    stops = np.searchsorted(codes[order], np.arange(len(sessions)), side="right")

    for session_id, session in enumerate(sessions):
        rows = order[starts[session_id]:stops[session_id]]
        if len(rows) == 0:
            continue
        lo, hi = low_index[rows], high_index[rows]
        base, top = int(lo.min()), int(hi.max())
        size = top - base + 1

        volume_counts = spread_evenly(lo, hi, volume[rows], base, size)

        tpo_counts = np.zeros(size, dtype=float)
        brackets = bracket[rows]
        for value in np.unique(brackets):
            member = brackets == value
            span_lo, span_hi = int(lo[member].min()), int(hi[member].max())
            tpo_counts[span_lo - base:span_hi - base + 1] += 1.0

        levels: dict[str, dict[str, float]] = {}
        for mode, counts in (("volume", volume_counts), ("tpo", tpo_counts)):
            poc_index = pick_poc(counts)
            val_index, vah_index = value_area_bounds(counts, poc_index, args.va_percent)
            levels[mode] = {
                "poc": (base + poc_index) * step,
                "val": (base + val_index) * step,
                "vah": (base + vah_index) * step,
            }

        opens = rth["open"].to_numpy()[rows]
        closes = rth["close"].to_numpy()[rows]
        profiles.append(SessionProfile(
            session=session,
            minutes=len(rows),
            valid=len(rows) >= args.min_rth_minutes,
            open=float(opens[0]),
            high=float(rth["high"].to_numpy()[rows].max()),
            low=float(rth["low"].to_numpy()[rows].min()),
            close=float(closes[-1]),
            volume=float(volume[rows].sum()),
            levels=levels,
        ))
    return profiles


# --------------------------------------------------------------------------
# Per-session bar views
# --------------------------------------------------------------------------

@dataclass
class SessionBars:
    times: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    open: np.ndarray
    bracket: np.ndarray
    bracket_close: np.ndarray
    bracket_high: np.ndarray
    bracket_low: np.ndarray
    bracket_end: np.ndarray  # last bar position of each bracket, -1 when absent


def build_session_bars(frame: pd.DataFrame, args: argparse.Namespace) -> dict[pd.Timestamp, SessionBars]:
    rth = frame[frame["is_rth"]]
    span = parse_clock(args.rth_end) - parse_clock(args.rth_start)
    n_brackets = span // args.bracket_minutes
    bars: dict[pd.Timestamp, SessionBars] = {}
    for session, group in rth.groupby("session", sort=True):
        bracket = group["bracket"].to_numpy()
        close = group["close"].to_numpy()
        high = group["high"].to_numpy()
        low = group["low"].to_numpy()
        bracket_close = np.full(n_brackets, np.nan)
        bracket_high = np.full(n_brackets, np.nan)
        bracket_low = np.full(n_brackets, np.nan)
        bracket_end = np.full(n_brackets, -1, dtype=np.int64)
        for value in np.unique(bracket):
            member = np.flatnonzero(bracket == value)
            bracket_close[value] = close[member[-1]]
            bracket_high[value] = high[member].max()
            bracket_low[value] = low[member].min()
            bracket_end[value] = member[-1]
        bars[session] = SessionBars(
            times=group.index.to_numpy(),
            high=high, low=low, close=close, open=group["open"].to_numpy(),
            bracket=bracket,
            bracket_close=bracket_close, bracket_high=bracket_high,
            bracket_low=bracket_low, bracket_end=bracket_end,
        )
    return bars


def first_touch(bars: SessionBars, start: int, level: float, side: int) -> int:
    """First bar at or after `start` trading to `level`; side +1 needs a high, -1 a low."""
    if side > 0:
        hit = np.flatnonzero(bars.high[start:] >= level)
    else:
        hit = np.flatnonzero(bars.low[start:] <= level)
    return int(hit[0] + start) if len(hit) else -1


def simulate_bracket(bars: SessionBars, start: int, side: int, stop_level: float,
                     target: float) -> tuple[str, float, int]:
    """Walk forward to the RTH close. A bar spanning both levels is booked as a stop."""
    for pos in range(start, len(bars.close)):
        if side > 0:
            if bars.low[pos] <= stop_level:
                return "stop", stop_level, pos
            if bars.high[pos] >= target:
                return "target", target, pos
        else:
            if bars.high[pos] >= stop_level:
                return "stop", stop_level, pos
            if bars.low[pos] <= target:
                return "target", target, pos
    last = len(bars.close) - 1
    return "session_close", float(bars.close[last]), last


# --------------------------------------------------------------------------
# The 80% rule
# --------------------------------------------------------------------------

def bracket_accepts(bars: SessionBars, index: int, val: float, vah: float, mode: str) -> bool:
    if bars.bracket_end[index] < 0:
        return False
    if mode == "close":
        return val <= bars.bracket_close[index] <= vah
    return bool(bars.bracket_low[index] >= val and bars.bracket_high[index] <= vah)


def eighty_rule_events(profiles: list[SessionProfile], bars: dict[pd.Timestamp, SessionBars],
                       mode: str, accept: str, args: argparse.Namespace,
                       confirm: int | None = None) -> pd.DataFrame:
    """One row per session that opened outside the prior value area and was accepted back.

    `confirm` is how many consecutive brackets must accept. The rule as taught uses
    two; running it with one isolates what the confirmation is actually worth.
    """
    confirm = args.confirm_brackets if confirm is None else confirm
    cost_points = (
        2.0 * args.commission_per_side / args.point_value
        + 2.0 * args.slippage_ticks * TICK_SIZE
    )
    rows: list[dict[str, Any]] = []
    for index in range(1, len(profiles)):
        today, prior = profiles[index], profiles[index - 1]
        if not (today.valid and prior.valid):
            continue
        val, vah = prior.value_area(mode)
        width = vah - val
        if width <= 0:
            continue
        session_bars = bars[today.session]

        if today.open > vah:
            side, target, entry_edge = -1, val, vah
        elif today.open < val:
            side, target, entry_edge = 1, vah, val
        else:
            continue

        n_brackets = len(session_bars.bracket_close)
        trigger = -1
        for candidate in range(n_brackets - confirm):
            if all(bracket_accepts(session_bars, candidate + offset, val, vah, accept)
                   for offset in range(confirm)):
                trigger = candidate + confirm - 1
                break
        if trigger < 0:
            continue

        entry_pos = int(session_bars.bracket_end[trigger])
        entry = float(session_bars.close[entry_pos])
        stop_level = entry_edge - side * args.stop_buffer_points
        # Did the traverse already happen while the setup was still forming?
        early_pos = first_touch(session_bars, 0, target, side)
        touch_pos = first_touch(session_bars, entry_pos + 1, target, side)

        outcome, exit_price, _ = simulate_bracket(
            session_bars, entry_pos + 1, side, stop_level, target
        )
        gross = side * (exit_price - entry)
        rows.append({
            "session": today.session,
            "year": today.session.year,
            "confirm_brackets": confirm,
            "direction": "short" if side < 0 else "long",
            "side": side,
            "prior_val": val,
            "prior_vah": vah,
            "va_width": width,
            "open": today.open,
            "trigger_bracket": trigger,
            "entry_time": pd.Timestamp(session_bars.times[entry_pos]),
            "entry": entry,
            "target": target,
            "stop": stop_level,
            "distance_points": abs(entry - target),
            "distance_rel": abs(entry - target) / width,
            "traversed": touch_pos >= 0,
            "traversed_bars": touch_pos - entry_pos if touch_pos >= 0 else np.nan,
            "traversed_before_trigger": bool(0 <= early_pos <= entry_pos),
            "outcome": outcome,
            "exit_price": exit_price,
            "gross_points": gross,
            "net_points": gross - cost_points,
            "net_dollars": (gross - cost_points) * args.point_value,
        })
    return pd.DataFrame(rows)


def control_observations(profiles: list[SessionProfile], bars: dict[pd.Timestamp, SessionBars],
                         mode: str) -> pd.DataFrame:
    """Sessions that opened *inside* the prior value area, sampled at every bracket close.

    These carry the mechanical part of the 80% claim -- price sitting inside a
    balance area tends to reach an edge before the bell whatever the setup -- so
    they are what the rule has to beat.
    """
    rows: list[dict[str, Any]] = []
    for index in range(1, len(profiles)):
        today, prior = profiles[index], profiles[index - 1]
        if not (today.valid and prior.valid):
            continue
        val, vah = prior.value_area(mode)
        width = vah - val
        if width <= 0 or not (val <= today.open <= vah):
            continue
        session_bars = bars[today.session]
        n_brackets = len(session_bars.bracket_close)
        for bracket in range(n_brackets - 1):
            end = int(session_bars.bracket_end[bracket])
            if end < 0:
                continue
            price = float(session_bars.bracket_close[bracket])
            if not val <= price <= vah:
                continue
            for side, target in ((-1, val), (1, vah)):
                rows.append({
                    "session": today.session,
                    "year": today.session.year,
                    "side": side,
                    "trigger_bracket": bracket,
                    "distance_rel": abs(price - target) / width,
                    "traversed": first_touch(session_bars, end + 1, target, side) >= 0,
                })
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------
# Naked POC
# --------------------------------------------------------------------------

def build_occupancy(frame: pd.DataFrame, args: argparse.Namespace,
                    scope: str) -> dict[pd.Timestamp, tuple[int, np.ndarray]]:
    """Rows actually traded in each session, at profile resolution.

    A level counts as revisited only when some one-minute bar spans it, which is
    stricter than asking whether it fell inside the session's high-low range.
    """
    source = frame if scope == "full" else frame[frame["is_rth"]]
    step = args.price_step
    work = pd.DataFrame({
        "session": source["session"].to_numpy(),
        "low": np.rint(source["low"].to_numpy() / step).astype(np.int64),
        "high": np.rint(source["high"].to_numpy() / step).astype(np.int64),
    })
    occupancy: dict[pd.Timestamp, tuple[int, np.ndarray]] = {}
    for session, group in work.groupby("session", sort=True):
        low, high = group["low"].to_numpy(), group["high"].to_numpy()
        base, top = int(low.min()), int(high.max())
        diff = np.zeros(top - base + 2, dtype=np.int32)
        np.add.at(diff, low - base, 1)
        np.add.at(diff, high - base + 1, -1)
        occupancy[session] = (base, np.cumsum(diff)[:top - base + 1] > 0)
    return occupancy


def traded_at(entry: tuple[int, np.ndarray] | None, index: int) -> bool:
    if entry is None:
        return False
    base, mask = entry
    offset = index - base
    return 0 <= offset < len(mask) and bool(mask[offset])


def kaplan_meier(lags: np.ndarray, events: np.ndarray, horizons: tuple[int, ...]) -> dict[int, float]:
    """Revisit probability by lag, right-censoring levels the sample outruns."""
    survival = 1.0
    result: dict[int, float] = {}
    for lag in range(1, max(horizons) + 1):
        at_risk = int(np.sum(lags >= lag))
        failures = int(np.sum((lags == lag) & events))
        if at_risk:
            survival *= 1.0 - failures / at_risk
        if lag in horizons:
            result[lag] = 1.0 - survival
    return result


def level_definitions(mode: str, seed: int = 20260905) -> dict[str, Any]:
    rng = np.random.default_rng(seed)
    return {
        "poc": lambda p: p.poc(mode),
        "vah": lambda p: p.value_area(mode)[1],
        "val": lambda p: p.value_area(mode)[0],
        "range_mid": lambda p: (p.high + p.low) / 2.0,
        "close_mirror": lambda p: 2.0 * p.close - p.poc(mode),
        "random_in_range": lambda p: float(rng.uniform(p.low, p.high)),
    }


def survival_study(profiles: list[SessionProfile], occupancy: dict[pd.Timestamp, tuple[int, np.ndarray]],
                   args: argparse.Namespace, mode: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    step = args.price_step
    masks = [occupancy.get(profile.session) for profile in profiles]
    total = len(profiles)

    rows: list[dict[str, Any]] = []
    for name, resolve in level_definitions(mode).items():
        for index, profile in enumerate(profiles):
            if not profile.valid:
                continue
            price = float(resolve(profile))
            bucket = int(round(price / step))
            reach = min(args.max_lag, total - 1 - index)
            lag, event = reach, False
            for step_ahead in range(1, reach + 1):
                if traded_at(masks[index + step_ahead], bucket):
                    lag, event = step_ahead, True
                    break
            rows.append({
                "level_type": name,
                "session": profile.session,
                "year": profile.session.year,
                "price": price,
                "distance_from_close": abs(price - profile.close),
                "lag": lag,
                "revisited": event,
            })
    detail = pd.DataFrame(rows)

    summary: list[dict[str, Any]] = []
    for name, group in detail.groupby("level_type", sort=False):
        curve = kaplan_meier(group["lag"].to_numpy(), group["revisited"].to_numpy(), SURVIVAL_LAGS)
        record = {
            "level_type": name,
            "levels": len(group),
            "median_distance_from_close": float(group["distance_from_close"].median()),
        }
        record.update({f"revisit_by_{lag}": curve[lag] for lag in SURVIVAL_LAGS})
        summary.append(record)
    return detail, pd.DataFrame(summary)


def npoc_trades(profiles: list[SessionProfile], bars: dict[pd.Timestamp, SessionBars],
                occupancy: dict[pd.Timestamp, tuple[int, np.ndarray]],
                args: argparse.Namespace, mode: str) -> pd.DataFrame:
    """Fade toward the nearest untouched prior POC at the RTH open, flat by the bell."""
    cost_points = (
        2.0 * args.commission_per_side / args.point_value
        + 2.0 * args.slippage_ticks * TICK_SIZE
    )
    step = args.price_step
    naked: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []

    for profile in profiles:
        session_bars = bars[profile.session]
        if profile.valid and naked:
            entry = float(session_bars.open[0])
            distances = np.array([abs(item["price"] - entry) for item in naked])
            nearest = naked[int(np.argmin(distances))]
            distance = float(np.min(distances))
            if 0.0 < distance <= args.npoc_max_distance:
                side = 1 if nearest["price"] > entry else -1
                target = float(nearest["price"])
                stop_level = entry - side * args.npoc_stop_multiple * distance
                outcome, exit_price, _ = simulate_bracket(
                    session_bars, 0, side, stop_level, target
                )
                gross = side * (exit_price - entry)
                rows.append({
                    "session": profile.session,
                    "year": profile.session.year,
                    "direction": "long" if side > 0 else "short",
                    "entry": entry,
                    "target": target,
                    "stop": stop_level,
                    "distance_points": distance,
                    "npoc_age_sessions": nearest["age"],
                    "npoc_session": nearest["session"],
                    "outcome": outcome,
                    "exit_price": exit_price,
                    "gross_points": gross,
                    "net_points": gross - cost_points,
                    "net_dollars": (gross - cost_points) * args.point_value,
                })

        mask = occupancy.get(profile.session)
        naked = [item for item in naked if not traded_at(mask, item["bucket"])]
        for item in naked:
            item["age"] += 1
        if profile.valid:
            price = profile.poc(mode)
            naked.append({
                "session": profile.session,
                "price": price,
                "bucket": int(round(price / step)),
                "age": 1,
            })
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------
# Statistics
# --------------------------------------------------------------------------

def wilson_interval(successes: int, trials: int, z: float = 1.959964) -> tuple[float, float]:
    if trials == 0:
        return float("nan"), float("nan")
    rate = successes / trials
    denominator = 1.0 + z * z / trials
    centre = rate + z * z / (2.0 * trials)
    spread = z * math.sqrt(rate * (1.0 - rate) / trials + z * z / (4.0 * trials * trials))
    return (centre - spread) / denominator, (centre + spread) / denominator


def normal_sf(value: float) -> float:
    return 0.5 * math.erfc(value / math.sqrt(2.0))


def two_proportion_p(success_a: int, trials_a: int, success_b: int, trials_b: int) -> float:
    if min(trials_a, trials_b) == 0:
        return float("nan")
    pooled = (success_a + success_b) / (trials_a + trials_b)
    variance = pooled * (1.0 - pooled) * (1.0 / trials_a + 1.0 / trials_b)
    if variance <= 0.0:
        return float("nan")
    z = (success_a / trials_a - success_b / trials_b) / math.sqrt(variance)
    return 2.0 * normal_sf(abs(z))


def standardised_control(events: pd.DataFrame, controls: pd.DataFrame,
                         bins: int = 4) -> dict[str, Any]:
    """Re-weight the control sessions to the treatment's own setup geometry.

    Cells are (trigger bracket, direction, quartile of distance-to-target). Without
    this the comparison mostly measures that the rule fires when the far edge
    happens to be close. Events landing in a cell no control session reaches are
    dropped from *both* sides, so the two rates always describe the same cells.
    """
    empty = {"matched_events": 0, "coverage": float("nan"), "expected_rate": float("nan"),
             "observed_rate": float("nan"), "p_value": float("nan")}
    if events.empty or controls.empty:
        return empty

    edges = np.unique(np.quantile(controls["distance_rel"], np.linspace(0.0, 1.0, bins + 1)))
    if len(edges) < 2:
        return empty
    edges[0], edges[-1] = -np.inf, np.inf
    keys = ["trigger_bracket", "side", "bin"]

    control_cells = controls.assign(
        bin=pd.cut(controls["distance_rel"], edges, labels=False).astype(int)
    ).groupby(keys, observed=True)["traversed"].agg(["sum", "count"])
    control_rate = (control_cells["sum"] / control_cells["count"]).rename("rate")

    event_cells = events.assign(
        bin=pd.cut(events["distance_rel"], edges, labels=False).astype(int)
    )
    matched = control_rate.reindex(
        pd.MultiIndex.from_frame(event_cells[keys])
    ).to_numpy()
    keep = ~np.isnan(matched)
    trials = int(keep.sum())
    if trials == 0:
        return empty

    observed = int(events["traversed"].to_numpy()[keep].sum())
    expected_rate = float(matched[keep].mean())
    return {
        "matched_events": trials,
        "coverage": trials / len(events),
        "control_observations": int(control_cells["count"].sum()),
        "observed_rate": observed / trials,
        "expected_rate": expected_rate,
        "lift": observed / trials - expected_rate,
        # Control observations are heavily clustered -- eleven brackets and two
        # directions from each session -- so the control arm is given the same
        # effective sample size as the treatment rather than its raw row count.
        # That keeps the test conservative instead of crediting it false precision.
        "p_value": two_proportion_p(
            observed, trials, int(round(expected_rate * trials)), trials
        ),
    }


def summarise_trades(trades: pd.DataFrame, point_value: float) -> dict[str, Any]:
    if trades.empty:
        return {"trades": 0}
    net = trades["net_points"].to_numpy()
    wins, losses = net[net > 0.0], net[net < 0.0]
    equity = np.cumsum(net) * point_value
    drawdown = equity - np.maximum.accumulate(np.concatenate([[0.0], equity]))[1:]
    years = max((trades["session"].max() - trades["session"].min()).days / 365.25, 1e-9)
    return {
        "trades": int(len(trades)),
        "trades_per_year": len(trades) / years,
        "win_rate": float((net > 0.0).mean()),
        "avg_points": float(net.mean()),
        "total_points": float(net.sum()),
        "total_dollars": float(net.sum() * point_value),
        "profit_factor": float(wins.sum() / abs(losses.sum())) if losses.size else float("inf"),
        "max_drawdown_dollars": float(drawdown.min()),
        "t_statistic": float(net.mean() / (net.std(ddof=1) / math.sqrt(len(net))))
        if len(net) > 1 and net.std(ddof=1) > 0 else float("nan"),
    }


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------

def markdown_table(headers: list[str], rows: list[list[str]], align_right_from: int = 1) -> str:
    separators = [
        "---" if index < align_right_from else "---:" for index in range(len(headers))
    ]
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(separators) + " |"]
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return "\n".join(lines)


def percent(value: float) -> str:
    return "n/a" if value != value else f"{value * 100:.1f}%"


def metric_rows(stats: dict[str, Any]) -> list[list[str]]:
    rows: list[list[str]] = []
    for key, value in stats.items():
        if key.endswith("_rate"):
            text = percent(value)
        elif isinstance(value, float):
            text = f"{value:,.2f}"
        else:
            text = f"{value:,}"
        rows.append([key.replace("_", " ").capitalize(), text])
    return rows


def rule_variant_rows(profiles: list[SessionProfile], bars: dict[pd.Timestamp, SessionBars],
                      args: argparse.Namespace) -> tuple[list[list[str]], dict[str, pd.DataFrame]]:
    rows: list[list[str]] = []
    ledgers: dict[str, pd.DataFrame] = {}
    for mode in PROFILE_MODES:
        for accept in ACCEPT_MODES:
            events = eighty_rule_events(profiles, bars, mode, accept, args)
            ledgers[f"{mode}_{accept}"] = events
            trials = len(events)
            hits = int(events["traversed"].sum()) if trials else 0
            low, high = wilson_interval(hits, trials)
            clean = events[~events["traversed_before_trigger"]] if trials else events
            clean_rate = float(clean["traversed"].mean()) if len(clean) else float("nan")
            rows.append([
                f"{mode} / {accept}",
                f"{trials:,}",
                percent(hits / trials) if trials else "n/a",
                f"{percent(low)} - {percent(high)}",
                f"{len(clean):,}",
                percent(clean_rate),
            ])
    return rows, ledgers


def write_report(path: Path, sections: list[str]) -> None:
    path.write_text("\n\n".join(sections).rstrip() + "\n")


def main() -> None:
    args = parse_args()
    validate_args(args)
    output = args.output_dir
    output.mkdir(parents=True, exist_ok=True)

    frame, rolls = prepare(args)
    profiles = build_profiles(frame, args)
    bars = build_session_bars(frame, args)
    valid = [p for p in profiles if p.valid]
    print(f"sessions {len(profiles):,} | profile-grade {len(valid):,} | rolls {len(rolls)}")

    variant_rows, ledgers = rule_variant_rows(profiles, bars, args)
    primary_key = f"{args.profile_mode}_{args.accept_mode}"
    events = ledgers[primary_key]
    controls = control_observations(profiles, bars, args.profile_mode)
    comparison = standardised_control(events, controls)
    unconfirmed = eighty_rule_events(
        profiles, bars, args.profile_mode, args.accept_mode, args, confirm=1
    )
    unconfirmed_comparison = standardised_control(unconfirmed, controls)
    print(f"80% rule signals {len(events):,} | traverse "
          f"{percent(events['traversed'].mean()) if len(events) else 'n/a'} | "
          f"matched control {percent(comparison['expected_rate'])}")

    occupancy = build_occupancy(frame, args, args.npoc_touch_scope)
    survival_detail, survival = survival_study(profiles, occupancy, args, args.profile_mode)
    print("nPOC revisit by 10 sessions: " + ", ".join(
        f"{row.level_type} {percent(row.revisit_by_10)}" for row in survival.itertuples()
    ))

    npoc_ledger = npoc_trades(profiles, bars, occupancy, args, args.profile_mode)
    rule_stats = summarise_trades(events, args.point_value)
    npoc_stats = summarise_trades(npoc_ledger, args.point_value)

    # ---- artefacts -------------------------------------------------------
    for name, ledger in ledgers.items():
        ledger.to_csv(output / f"eighty_rule_events_{name}.csv", index=False)
    controls.to_csv(output / "eighty_rule_controls.csv", index=False)
    unconfirmed.to_csv(output / "eighty_rule_events_unconfirmed.csv", index=False)
    survival_detail.to_csv(output / "npoc_survival_detail.csv", index=False)
    survival.to_csv(output / "npoc_survival_summary.csv", index=False)
    npoc_ledger.to_csv(output / "npoc_trades.csv", index=False)

    by_year = pd.DataFrame()
    if len(events):
        by_year = events.groupby("year").agg(
            signals=("traversed", "size"),
            traverse_rate=("traversed", "mean"),
            net_points=("net_points", "sum"),
            win_rate=("net_points", lambda column: float((column > 0).mean())),
        ).reset_index()
        by_year.to_csv(output / "eighty_rule_by_year.csv", index=False)

    config = {
        "sessions": len(profiles),
        "profile_grade_sessions": len(valid),
        "first_session": str(profiles[0].session.date()) if profiles else None,
        "last_session": str(profiles[-1].session.date()) if profiles else None,
        "rolls": rolls,
        "arguments": {key: str(value) for key, value in vars(args).items()},
        "eighty_rule": rule_stats,
        "eighty_rule_control": comparison,
        "eighty_rule_unconfirmed_control": unconfirmed_comparison,
        "npoc_trade": npoc_stats,
        "cost_points_round_trip": 2.0 * args.commission_per_side / args.point_value
        + 2.0 * args.slippage_ticks * TICK_SIZE,
    }
    (output / "run.json").write_text(json.dumps(config, indent=2, default=str))

    # ---- report ----------------------------------------------------------
    cost_points = config["cost_points_round_trip"]
    span = f"{profiles[0].session.date()} to {profiles[-1].session.date()}"
    sections = [
        "# MNQ Market Profile folklore: the 80% rule and naked POCs",
        f"MNQ one-minute data, {span}, {len(profiles):,} sessions "
        f"({len(valid):,} full-length RTH sessions used for profiles). RTH is "
        f"{args.rth_start}-{args.rth_end} America/Chicago. Value area is "
        f"{args.va_percent:.0%} at a {args.price_step:g}-point row. Prices are "
        f"back-adjusted across {len(rolls)} contract rolls. Round-trip cost is "
        f"{cost_points:.2f} points (${cost_points * args.point_value:.2f}).",

        "## 1. The 80% rule\n\n"
        "Setup: RTH opens outside the prior session's value area, price re-enters, "
        "and two consecutive 30-minute brackets accept inside it. Success is price "
        "reaching the far value-area edge before the same session's close.",
        markdown_table(
            ["Value area / acceptance", "Signals", "Traverse", "95% Wilson", "Excl. early", "Rate"],
            variant_rows,
        ),
        "*Excl. early* drops sessions that had already reached the far edge before "
        "the signal completed.",

        "### Against matched controls\n\n"
        f"Two things have to be separated from the rule. First, price sitting inside a "
        f"balance area tends to reach an edge before the bell whatever the setup: the "
        f"control set is sessions that opened *inside* the prior value area, sampled at "
        f"every bracket close, in both directions ({comparison.get('control_observations', 0):,} "
        f"observations). Second, the rule's distinguishing ingredient is the two-period "
        f"confirmation, so the same scan is run requiring only one accepting bracket. "
        f"Control rates are re-weighted to each setup's own mix of trigger bracket, "
        f"direction, and quartile of distance-to-target, so the comparison is not a "
        f"restatement of how far the far edge happened to be. Control rows are "
        f"clustered by session, so the control arm is scored at the treatment's "
        f"sample size and the p-values are conservative.",
        markdown_table(
            ["Setup", "Signals", "Matched", "Traverse", "Matched control", "Lift", "p"],
            [
                [label, f"{len(ledger):,}", f"{entry['matched_events']:,}",
                 percent(entry["observed_rate"]), percent(entry["expected_rate"]),
                 f"{entry['lift'] * 100:+.1f} pp" if "lift" in entry else "n/a",
                 f"{entry['p_value']:.3f}" if entry["p_value"] == entry["p_value"] else "n/a"]
                for label, ledger, entry in (
                    ("Two accepting brackets (the rule)", events, comparison),
                    ("One accepting bracket (no confirmation)", unconfirmed,
                     unconfirmed_comparison),
                )
            ],
        ),

        "### Traded, with costs\n\n"
        f"Enter at the close of the second accepting bracket, target the far value-area "
        f"edge, stop {args.stop_buffer_points:g} points beyond the edge price re-entered "
        f"through, flat at the RTH close. A bar spanning both levels is booked as a stop.",
        markdown_table(["Metric", "Result"], metric_rows(rule_stats)),
    ]

    if not by_year.empty:
        sections.extend([
            "### By year",
            markdown_table(
                ["Year", "Signals", "Traverse", "Win rate", "Net points"],
                [[str(int(row.year)), f"{int(row.signals):,}", percent(row.traverse_rate),
                  percent(row.win_rate), f"{row.net_points:+,.1f}"]
                 for row in by_year.itertuples()],
            ),
        ])

    sections.extend([
        "## 2. Naked POC revisits\n\n"
        f"Each full-length RTH session contributes one POC. A level is revisited when "
        f"a later session actually trades it ({args.npoc_touch_scope} scope), scanning up "
        f"to {args.max_lag} sessions -- holiday sessions count toward the lag and can "
        f"themselves revisit a level -- and right-censoring at the end of the sample. The "
        f"control levels come from the same sessions: the value-area edges, the range "
        f"midpoint, a uniform draw from the range, and the POC reflected through the "
        f"session close, which holds distance-from-close fixed.",
        markdown_table(
            ["Level", "Count", "Median dist. from close"]
            + [f"<= {lag}" for lag in SURVIVAL_LAGS],
            [[row.level_type, f"{int(row.levels):,}", f"{row.median_distance_from_close:.0f}"]
             + [percent(getattr(row, f"revisit_by_{lag}")) for lag in SURVIVAL_LAGS]
             for row in survival.itertuples()],
        ),

        "### Traded, with costs\n\n"
        f"At each RTH open, if the nearest untouched prior POC is within "
        f"{args.npoc_max_distance:g} points, enter toward it, target the level, stop "
        f"{args.npoc_stop_multiple:g}x the distance the other way, flat at the RTH close.",
        markdown_table(["Metric", "Result"], metric_rows(npoc_stats)),

        "## Method notes and limits\n\n"
        "- Value areas are built from one-minute OHLCV, spreading each bar's volume "
        "evenly across the rows it spans; true tick or bid/ask volume would move the "
        "POC by a row or two on some days.\n"
        "- The prior session is the previous full-length RTH session; holiday and "
        "half sessions are excluded from profile formation and from trading.\n"
        "- Levels are compared across contract rolls using a back-adjusted series. "
        "Re-run with `--no-roll-adjust` to see the sensitivity.\n"
        "- One sample, one instrument, one venue era. The controls, not the headline "
        "rate, are the part of this worth trusting.\n"
        "- Low-volume-node acceleration is not tested here.",
    ])

    write_report(output / "report.md", sections)
    print(f"wrote {output}")


if __name__ == "__main__":
    main()
