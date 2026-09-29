"""Causal, descriptive study of higher-timeframe wick-phase proxies.

Default inputs are the session-aligned MNQ 1h, 4h and daily Parquet files built
from the local one-minute archive. Run from the repository root with:

    node scripts/python-command.mjs scripts/research-htf-wick-phases.py

Other pre-resampled files with the same schema can be supplied with repeated
``--input TF=PATH`` options. Timestamps must label bar opens in UTC. Contract
identity, roll-bar, and observed-minute columns are required so invalid spans
cannot silently be skipped. This study measures price behaviour, not trades or
institutional accumulation/distribution.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA = ROOT / "data" / "mnq_dom_sample" / "full_history" / "ohlcv-resampled"
TIMEFRAMES = ("1h", "4h", "1d")
TICK_SIZES = {"MNQ": .25, "ES": .25, "CL": .01}
HORIZONS = (3, 6)
COHORTS = (
    "accumulation_proxy", "downtrend_neutral", "downtrend_opposite",
    "distribution_proxy", "uptrend_neutral", "uptrend_opposite",
)
PERIODS = ("early_60pct", "middle_20pct", "late_20pct")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def finite_mean(values: list[float | None]) -> float | None:
    sample = [float(v) for v in values if v is not None and np.isfinite(v)]
    return float(np.mean(sample)) if sample else None


def finite_median(values: list[float | None]) -> float | None:
    sample = [float(v) for v in values if v is not None and np.isfinite(v)]
    return float(np.median(sample)) if sample else None


def bar_availability(index: pd.DatetimeIndex, timeframe: str) -> pd.DatetimeIndex:
    local = index.tz_convert("America/New_York")
    local_date = local.tz_localize(None).normalize()
    # A session runs from 18:00 ET to 17:00 ET on the following local day.
    close_date = local_date + pd.to_timedelta((local.hour >= 18).astype(int), unit="D")
    session_close = (close_date + pd.Timedelta(hours=17)).tz_localize("America/New_York").tz_convert("UTC")
    if timeframe == "1d":
        return session_close
    nominal_end = index + pd.Timedelta(hours=1 if timeframe == "1h" else 4)
    return pd.DatetimeIndex(np.minimum(nominal_end.asi8, session_close.asi8), tz="UTC")


def expected_minutes(index: pd.DatetimeIndex, timeframe: str) -> np.ndarray:
    if timeframe == "1h":
        return np.full(len(index), 60)
    if timeframe == "1d":
        return np.full(len(index), 1380)
    # The final 4h CME bucket opens at 14:00 ET and ends at 17:00 ET.
    local = index.tz_convert("America/New_York")
    return np.where(local.hour == 14, 180, 240)


def complete_session_rows(index: pd.DatetimeIndex, timeframe: str) -> tuple[np.ndarray, int]:
    """Require each represented CME session to contain every expected HTF slot."""
    local = index.tz_convert("America/New_York")
    session_date = local.tz_localize(None).normalize() + pd.to_timedelta((local.hour >= 18).astype(int), unit="D")
    slots = local.hour * 60 + local.minute
    expected = ({18 * 60} if timeframe == "1d" else
                {18 * 60, 22 * 60, 2 * 60, 6 * 60, 10 * 60, 14 * 60} if timeframe == "4h" else
                set(range(18 * 60, 24 * 60, 60)) | set(range(0, 17 * 60, 60)))
    good = np.zeros(len(index), dtype=bool)
    incomplete = 0
    groups = pd.Series(np.arange(len(index)), index=session_date)
    for _, positions in groups.groupby(level=0, sort=False):
        locations = positions.to_numpy(dtype=int)
        observed = slots[locations].tolist()
        if len(observed) == len(expected) and set(observed) == expected:
            good[locations] = True
        else:
            incomplete += 1
    return good, incomplete


def prepare(frame: pd.DataFrame, timeframe: str, coverage_fraction: float,
            minimum_minutes: int | None = None, expected_symbol: str | None = None) -> dict:
    if timeframe not in TIMEFRAMES:
        raise ValueError(f"Unsupported timeframe: {timeframe}")
    if not isinstance(frame.index, pd.DatetimeIndex) or frame.index.tz is None:
        raise ValueError("Parquet index must contain timezone-aware bar-open timestamps")
    if frame.empty or frame.index.has_duplicates or not frame.index.is_monotonic_increasing:
        raise ValueError("Bar-open timestamps must be nonempty, unique and sorted")
    required = {"open", "high", "low", "close", "minute_count", "instrument_id", "contract_count", "is_roll_bar", "symbol"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"Required candle/provenance columns are missing: {sorted(missing)}")
    index = frame.index.tz_convert("UTC")
    source_symbols = sorted({str(v).split(".")[0].upper() for v in frame.symbol.dropna().unique()})
    if expected_symbol is not None and source_symbols != [expected_symbol.upper()]:
        raise ValueError(f"Candle symbol {source_symbols} does not match declared {expected_symbol}")
    o, h, l, c = (pd.to_numeric(frame[k], errors="coerce").to_numpy(float) for k in ("open", "high", "low", "close"))
    count = pd.to_numeric(frame.minute_count, errors="coerce").to_numpy(float)
    contracts = pd.to_numeric(frame.contract_count, errors="coerce").to_numpy(float)
    ids = frame.instrument_id.astype("string").fillna("").to_numpy(str)
    roll = frame.is_roll_bar.fillna(True).to_numpy(bool)
    valid_ohlc = (np.isfinite(o) & np.isfinite(h) & np.isfinite(l) & np.isfinite(c)
                  & (h > l) & (h >= np.maximum.reduce([o, c, l]))
                  & (l <= np.minimum.reduce([o, c, h])))
    expected = expected_minutes(index, timeframe)
    required_minutes = (np.full(len(frame), minimum_minutes) if minimum_minutes is not None
                        else np.ceil(expected * coverage_fraction))
    complete = np.isfinite(count) & (count >= required_minutes)
    transitions = (frame.is_roll_transition.fillna(True).to_numpy(bool)
                   if "is_roll_transition" in frame else np.zeros(len(frame), dtype=bool))
    valid_contract = (contracts == 1) & ~roll & ~transitions & (ids != "")
    session_complete, incomplete_sessions = complete_session_rows(index, timeframe)
    valid = valid_ohlc & complete & valid_contract & session_complete
    tr = np.full(len(frame), np.nan)
    for i in range(1, len(frame)):
        if valid[i] and valid[i - 1] and ids[i] == ids[i - 1]:
            tr[i] = max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
    return dict(index=index, available=bar_availability(index, timeframe),
                o=o, h=h, l=l, c=c, ids=ids, valid=valid, tr=tr,
                quality=dict(rows=len(frame), invalid_ohlc=int((~valid_ohlc).sum()),
                             below_minute_count=int((~complete).sum()),
                             roll_or_unknown_contract=int((~valid_contract).sum()),
                             incomplete_session_rows=int((~session_complete).sum()),
                             incomplete_session_count=incomplete_sessions,
                             valid_rows=int(valid.sum()), coverage_fraction=coverage_fraction,
                             minimum_minutes_override=minimum_minutes,
                             expected_minute_counts=sorted(set(int(v) for v in expected)),
                             source_symbols=source_symbols))


def cohort_for(prior_trend_atr: float, wick_skew: float, trend_threshold: float, skew_threshold: float) -> str | None:
    if prior_trend_atr <= -trend_threshold:
        if wick_skew >= skew_threshold:
            return "accumulation_proxy"
        if wick_skew <= -skew_threshold:
            return "downtrend_opposite"
        return "downtrend_neutral"
    if prior_trend_atr >= trend_threshold:
        if wick_skew <= -skew_threshold:
            return "distribution_proxy"
        if wick_skew >= skew_threshold:
            return "uptrend_opposite"
        return "uptrend_neutral"
    return None


def period_for(i: int, cuts: tuple[int, int, int]) -> tuple[str, int]:
    if i < cuts[0]:
        return PERIODS[0], cuts[0]
    if i < cuts[1]:
        return PERIODS[1], cuts[1]
    return PERIODS[2], cuts[2]


def score_horizon(event: dict, market: dict, horizon: int, right_bound: int,
                  end_reason: str = "period_boundary") -> dict:
    """Score only subsequent positional rows; censor an entire horizon at faults."""
    i = int(event["signal_index"])
    stop = i + horizon
    prefix = f"h{horizon}_"
    blank = {prefix + k: None for k in (
        "first_hit_bar", "first_hit_time", "up_excursion_atr", "down_excursion_atr",
        "excursion_lean", "future_close_phase_location", "future_mean_close_phase_location",
        "future_close_phase_location_change", "future_closes_above_midpoint",
        "future_close_in_future_range", "end_time",
    )}
    if stop >= right_bound:
        return {prefix + "outcome": "incomplete", prefix + "censor_reason":
                end_reason, **blank}
    window = slice(i + 1, stop + 1)
    if np.any(market["ids"][window] != event["instrument_id"]):
        return {prefix + "outcome": "incomplete", prefix + "censor_reason": "contract_transition", **blank}
    if not np.all(market["valid"][window]):
        return {prefix + "outcome": "incomplete", prefix + "censor_reason": "invalid_future_bar", **blank}
    c0, atr = event["signal_close"], event["atr_prephase"]
    up_level, down_level = c0 + atr, c0 - atr
    outcome, first_hit = "neither", None
    for offset in range(1, horizon + 1):
        j = i + offset
        up = market["h"][j] >= up_level
        down = market["l"][j] <= down_level
        if up and down:
            outcome, first_hit = "ambiguous", offset
            break
        if up:
            outcome, first_hit = "up_first", offset
            break
        if down:
            outcome, first_hit = "down_first", offset
            break
    highs, lows, closes = market["h"][window], market["l"][window], market["c"][window]
    up_exc = max(0., float(highs.max() - c0)) / atr
    down_exc = max(0., float(c0 - lows.min())) / atr
    phase_low, phase_high = event["phase_low"], event["phase_high"]
    phase_span = phase_high - phase_low
    future_span = float(highs.max() - lows.min())
    midpoint = (phase_high + phase_low) / 2
    return {
        prefix + "outcome": outcome,
        prefix + "censor_reason": None,
        prefix + "first_hit_bar": first_hit,
        prefix + "first_hit_time": market["available"][i + first_hit].isoformat() if first_hit else None,
        prefix + "up_excursion_atr": up_exc,
        prefix + "down_excursion_atr": down_exc,
        prefix + "excursion_lean": (up_exc - down_exc) / (up_exc + down_exc) if up_exc + down_exc > 0 else 0.,
        prefix + "future_close_phase_location": float((closes[-1] - phase_low) / phase_span),
        prefix + "future_close_phase_location_change": float((closes[-1] - c0) / phase_span),
        prefix + "future_mean_close_phase_location": float(np.mean((closes - phase_low) / phase_span)),
        prefix + "future_closes_above_midpoint": float(np.mean(closes > midpoint)),
        prefix + "future_close_in_future_range": float((closes[-1] - lows.min()) / future_span) if future_span > 0 else None,
        prefix + "end_time": market["available"][stop].isoformat(),
    }


def detect_and_score(frame: pd.DataFrame, timeframe: str, config: dict) -> tuple[list[dict], dict]:
    market = prepare(frame, timeframe, config["coverage_fraction"],
                     config["min_minutes"].get(timeframe), config["symbol"])
    o, h, l, c = (market[k] for k in ("o", "h", "l", "c"))
    ids, valid, tr = (market[k] for k in ("ids", "valid", "tr"))
    n = len(frame)
    available = market["available"]
    analysis_first = int(available.searchsorted(pd.Timestamp(config["start"], tz="UTC")))
    analysis_right = int(available.searchsorted(pd.Timestamp(config["end"], tz="UTC") + pd.Timedelta(days=1)))
    analysis_count = analysis_right - analysis_first
    if analysis_count <= 0:
        raise ValueError("No completed candle availability times fall in the declared analysis interval")
    cuts = (analysis_first + int(analysis_count * .6),
            analysis_first + int(analysis_count * .8), analysis_right)
    phase_bars, context_bars = config["phase_bars"], config["context_bars"]
    events: list[dict] = []
    last_selected = -10**9
    for i in range(max(context_bars + phase_bars, analysis_first), analysis_right):
        a = i - phase_bars + 1
        context_a = a - context_bars
        previous = context_a - 1
        if previous < 0 or not np.all(valid[previous:i + 1]) or np.any(ids[previous:i + 1] != ids[i]):
            continue
        context_tr = tr[context_a:a]
        if not np.isfinite(context_tr).all():
            continue
        atr = float(np.mean(context_tr))
        if not np.isfinite(atr) or atr <= 0:
            continue
        phase_low, phase_high = float(l[a:i + 1].min()), float(h[a:i + 1].max())
        phase_span = phase_high - phase_low
        compactness = phase_span / atr
        if phase_span <= 0 or compactness > config["compact_atr"]:
            continue
        trend = float((c[a - 1] - c[previous]) / atr)
        if abs(trend) < config["trend_atr"]:
            continue
        upper = h[a:i + 1] - np.maximum(o[a:i + 1], c[a:i + 1])
        lower = np.minimum(o[a:i + 1], c[a:i + 1]) - l[a:i + 1]
        body = np.abs(c[a:i + 1] - o[a:i + 1])
        floored_body = np.maximum(body, config["tick_size"])
        ranges = h[a:i + 1] - l[a:i + 1]
        total_range, total_body = float(ranges.sum()), float(body.sum())
        upper_sum, lower_sum = float(upper.sum()), float(lower.sum())
        skew = (lower_sum - upper_sum) / total_range
        cohort = cohort_for(trend, skew, config["trend_atr"], config["wick_skew"])
        if cohort is None:
            continue
        period, right_bound = period_for(i, cuts)
        signal_body = float(body[-1])
        signal_range = float(ranges[-1])
        selected = i > last_selected + config["cooldown_bars"]
        event = dict(
            event_id=f"{timeframe}-{i}", timeframe=timeframe, candidate=True, selected=selected,
            signal_index=i, period=period, year=int(market["available"][i].year),
            month=market["available"][i].strftime("%Y-%m"),
            phase_start_time=market["index"][a].isoformat(),
            phase_end_time=market["available"][i].isoformat(),
            signal_bar_open_time=market["index"][i].isoformat(),
            context_end_time=market["available"][a - 1].isoformat(),
            instrument_id=ids[i], cohort=cohort,
            prior_trend_atr=trend, compactness_atr=compactness, atr_prephase=atr,
            phase_low=phase_low, phase_high=phase_high, phase_range=phase_span,
            phase_open=float(o[a]), signal_close=float(c[i]),
            phase_close_location=float((c[i] - phase_low) / phase_span),
            phase_mean_close_location=float(np.mean((c[a:i + 1] - l[a:i + 1]) / ranges)),
            phase_upper_wick=upper_sum, phase_lower_wick=lower_sum,
            phase_body=total_body, phase_total_candle_range=total_range,
            upper_share=upper_sum / total_range, lower_share=lower_sum / total_range,
            body_share=total_body / total_range, wick_skew=skew,
            upper_body_ratio=upper_sum / float(floored_body.sum()),
            lower_body_ratio=lower_sum / float(floored_body.sum()),
            mean_upper_body_ratio=float(np.mean(upper / floored_body)),
            mean_lower_body_ratio=float(np.mean(lower / floored_body)),
            zero_body_bars=int(np.sum(body == 0)),
            signal_open=float(o[i]), signal_high=float(h[i]), signal_low=float(l[i]),
            signal_upper_wick=float(upper[-1]), signal_lower_wick=float(lower[-1]),
            signal_body=signal_body, signal_body_share=signal_body / signal_range,
            signal_body_direction=int(np.sign(c[i] - o[i])),
            signal_open_location=float((o[i] - l[i]) / signal_range),
            signal_close_location=float((c[i] - l[i]) / signal_range),
            signal_upper_body_ratio=float(upper[-1] / max(signal_body, config["tick_size"])),
            signal_lower_body_ratio=float(lower[-1] / max(signal_body, config["tick_size"])),
        )
        if selected:
            last_selected = i
            boundary_reason = ("period_boundary" if period != PERIODS[-1] else
                               "analysis_end" if analysis_right < n else "data_end")
            for horizon in HORIZONS:
                event.update(score_horizon(event, market, horizon, right_bound, boundary_reason))
        events.append(event)
    return events, market["quality"] | dict(
        analysis_rows=analysis_count, bars_early=cuts[0] - analysis_first,
        bars_middle=cuts[1] - cuts[0], bars_late=cuts[2] - cuts[1],
        analysis_first_bar=market["index"][analysis_first].isoformat() if analysis_count else None,
        analysis_last_bar=market["index"][analysis_right - 1].isoformat() if analysis_count else None,
        first_bar=market["index"][0].isoformat(), last_bar=market["index"][-1].isoformat(),
        candidate_window_count=len(events), selected_episode_count=sum(e["selected"] for e in events),
    )


def group_statistics(rows: list[dict], horizon: int, direction: str) -> dict:
    selected = [r for r in rows if r["selected"]]
    prefix = f"h{horizon}_"
    outcomes = Counter(r.get(prefix + "outcome", "") for r in selected)
    up, down = outcomes["up_first"], outcomes["down_first"]
    decisive = up + down
    complete = [r for r in selected if r.get(prefix + "outcome") != "incomplete"]
    success = up if direction == "up" else down
    return dict(candidate_window_count=len(rows), selected_episode_count=len(selected),
                anatomy=dict(
                    median_phase_lower_body_ratio=finite_median([r["lower_body_ratio"] for r in selected]),
                    median_phase_upper_body_ratio=finite_median([r["upper_body_ratio"] for r in selected]),
                    median_lower_range_share=finite_median([r["lower_share"] for r in selected]),
                    median_upper_range_share=finite_median([r["upper_share"] for r in selected]),
                    median_wick_skew=finite_median([r["wick_skew"] for r in selected]),
                    median_signal_open_location=finite_median([r["signal_open_location"] for r in selected]),
                    median_signal_close_location=finite_median([r["signal_close_location"] for r in selected]),
                    median_phase_close_location=finite_median([r["phase_close_location"] for r in selected])),
                complete_horizon_count=len(complete), decisive_count=decisive,
                directional_success_count=success,
                directional_success_rate=success / decisive if decisive else None,
                up_first_rate=up / decisive if decisive else None,
                up_first=up, down_first=down, ambiguous=outcomes["ambiguous"],
                neither=outcomes["neither"], incomplete=outcomes["incomplete"],
                mean_excursion_lean=finite_mean([r.get(prefix + "excursion_lean") for r in complete]),
                median_excursion_lean=finite_median([r.get(prefix + "excursion_lean") for r in complete]),
                mean_future_close_phase_location=finite_mean([r.get(prefix + "future_close_phase_location") for r in complete]),
                median_future_close_phase_location=finite_median([r.get(prefix + "future_close_phase_location") for r in complete]),
                mean_future_close_phase_location_change=finite_mean([r.get(prefix + "future_close_phase_location_change") for r in complete]),
                median_future_close_phase_location_change=finite_median([r.get(prefix + "future_close_phase_location_change") for r in complete]),
                mean_future_closes_above_midpoint=finite_mean([r.get(prefix + "future_closes_above_midpoint") for r in complete]),
                mean_up_excursion_atr=finite_mean([r.get(prefix + "up_excursion_atr") for r in complete]),
                mean_down_excursion_atr=finite_mean([r.get(prefix + "down_excursion_atr") for r in complete]))


def direction_for(cohort: str) -> str:
    return "up" if cohort.startswith("downtrend") or cohort == "accumulation_proxy" else "down"


def month_block_difference(rows: list[dict], proxy: str, neutral: str, horizon: int,
                           samples: int, seed: int) -> dict:
    direction = direction_for(proxy)
    prefix = f"h{horizon}_"
    by_month: dict[str, list[int]] = {}
    for row in rows:
        if not row["selected"] or row["cohort"] not in (proxy, neutral):
            continue
        outcome = row.get(prefix + "outcome")
        if outcome not in ("up_first", "down_first"):
            continue
        bucket = by_month.setdefault(row["month"], [0, 0, 0, 0])
        arm = 0 if row["cohort"] == proxy else 1
        bucket[arm * 2] += int(outcome == ("up_first" if direction == "up" else "down_first"))
        bucket[arm * 2 + 1] += 1
    values = np.array(list(by_month.values()), dtype=int).reshape((-1, 4))
    total = values.sum(axis=0) if len(values) else np.zeros(4, dtype=int)
    diff = float(total[0] / total[1] - total[2] / total[3]) if total[1] and total[3] else None
    interval = None
    if len(values) >= 10 and total[1] >= 20 and total[3] >= 20:
        rng = np.random.default_rng(seed)
        draws = []
        for _ in range(samples):
            sums = values[rng.integers(0, len(values), len(values))].sum(axis=0)
            if sums[1] and sums[3]:
                draws.append(sums[0] / sums[1] - sums[2] / sums[3])
        if len(draws) >= samples * .9:
            interval = [float(v) for v in np.quantile(draws, [.025, .975])]
    return dict(proxy=proxy, neutral=neutral, expected_direction=direction,
                difference=diff, interval_95=interval, months_with_decisive_hits=len(values),
                proxy_decisive=int(total[1]), neutral_decisive=int(total[3]),
                bootstrap_samples=samples)


def summarize(events_by_timeframe: dict[str, list[dict]], quality: dict, config: dict,
              inputs: dict, source_hash: str) -> dict:
    result = dict(study="HTF wick-phase proxy event study", created_at=datetime.now(timezone.utc).isoformat(),
                  source_sha256=source_hash, inputs=inputs, config=config, quality=quality,
                  definitions={
                      "phase": "Six completed bars by default; only compact phases after a qualifying prephase trend enter the candidate set.",
                      "frozen_atr": "Mean of 20 true ranges strictly before phase start; each uses the preceding close from the same contract.",
                      "trend": "(Last prephase close minus close before the 20-bar context) / frozen ATR.",
                      "compactness_atr": "(Phase high minus phase low) / frozen ATR; at or below configured maximum.",
                      "wick_components": "For each candle: upper=high-max(open,close); lower=min(open,close)-low; body=abs(close-open). Shares divide phase sums by sum of candle ranges.",
                      "wick_skew": "(Sum lower wick minus sum upper wick) / sum candle ranges; positive means lower-wick dominance.",
                      "cohorts": "After a decline: positive skew=accumulation proxy, near-zero skew=downtrend neutral, negative skew=downtrend opposite. After a rise: negative skew=distribution proxy, near-zero skew=uptrend neutral, positive skew=uptrend opposite. Proxy labels do not identify order flow.",
                      "body_ratios": "Each candle uses wick/max(body,tick size), so dojis have a finite tick-size floor. The ledger reports signal-candle ratios, mean candle ratios, and phase wick sums divided by the sum of floored bodies.",
                      "close_location": "(Close-low)/(high-low) for signal candle; phase close location uses the whole phase range and is descriptive because it is related algebraically to wicks.",
                      "future_close_phase_location": "(Close at t+h minus frozen phase low)/(frozen phase high minus phase low); values outside 0 to 1 are retained.",
                      "future_close_phase_location_change": "Future close phase location minus signal close phase location; equals (future close minus signal close)/frozen phase range. This removes the signal's initial position in the phase range.",
                      "future_closes_above_midpoint": "Share of all future closes through t+h above the frozen phase midpoint.",
                      "first_hit": "From signal close, first future bar whose high reaches +1 frozen ATR or low reaches -1 frozen ATR within h=3/6 bars. Both thresholds in one HTF bar are ambiguous. No threshold is neither. Incomplete/roll/invalid/period-boundary horizons are censored.",
                      "directional_success_rate": "Expected-direction first hits / (up-first + down-first); ambiguous, neither and incomplete are reported separately and excluded from this denominator.",
                      "excursion_lean": "(up excursion minus down excursion)/(up excursion plus down excursion), with zero when both are zero; excursions use all h future bars and frozen ATR.",
                      "episode_selection": "Chronological greedy selection from all compact up/down-trend candidate windows, regardless of wick cohort; after a selected signal, skip the next cooldown_bars candidate endpoints. Selection never uses future outcomes.",
                      "periods": "Chronological 60/20/20 analysis-window bar segments are descriptive, not untouched holdouts. Outcomes cannot cross a segment's right boundary.",
                      "uncertainty": "Exploratory pointwise percentile intervals resample shared calendar-month blocks for proxy minus same-trend neutral decisive first-hit rate. No multiple-comparison adjustment.",
                  }, timeframes={},
                  limitations=["Previously inspected MNQ history; no untouched holdout or prospective evidence is claimed.",
                               "Overlapping candidate windows are counted, but primary rates use non-overlapping selected episodes.",
                               "Within-bar order is unknown when both ATR boundaries are reached by one HTF bar.",
                               "Minute-count gates are data-quality proxies. Every represented intraday session must contain all expected session-aligned bucket opens; a complete exchange holiday calendar is not reconstructed.",
                               "The proxy/control contrast is observational and can differ in close location, candle shape or market context. It is not trading profitability or institutional order-flow evidence."])
    for tf, rows in events_by_timeframe.items():
        tf_summary = dict(cohorts={}, periods={}, comparisons={})
        for cohort in COHORTS:
            subset = [r for r in rows if r["cohort"] == cohort]
            tf_summary["cohorts"][cohort] = {str(h): group_statistics(subset, h, direction_for(cohort)) for h in HORIZONS}
        for period in PERIODS:
            tf_summary["periods"][period] = {}
            for cohort in COHORTS:
                subset = [r for r in rows if r["period"] == period and r["cohort"] == cohort]
                tf_summary["periods"][period][cohort] = {str(h): group_statistics(subset, h, direction_for(cohort)) for h in HORIZONS}
        for proxy, neutral in (("accumulation_proxy", "downtrend_neutral"),
                               ("distribution_proxy", "uptrend_neutral")):
            key = f"{proxy}_minus_{neutral}"
            tf_summary["comparisons"][key] = {
                str(h): month_block_difference(rows, proxy, neutral, h,
                                               config["bootstrap_samples"],
                                               config["seed"] + HORIZONS.index(h) + (0 if proxy == "accumulation_proxy" else 10))
                for h in HORIZONS}
        result["timeframes"][tf] = tf_summary
    if any(item.get("resample_manifest") is None for item in inputs.values()):
        result["limitations"].append(
            "The prebuilt MNQ HTF files have no sibling resample manifest. Their exact file hashes and candle-level contract metadata are recorded, but the link to the upstream one-minute source is not independently certified here.")
    return result


def markdown_report(summary: dict) -> str:
    def pct(value):
        return "—" if value is None else f"{value * 100:.1f}%"
    def number(value):
        return "—" if value is None else f"{value:.3f}"
    lines = ["# Higher-timeframe wick-phase proxies", "",
             "Descriptive historical price study. Accumulation and distribution are names for observable wick/trend proxies, not identified institutional activity or trade signals.", "",
             "The primary comparison is the 4h proxy against compact phases following the **same prior-trend direction** with near-zero wick skew. One-hour is supporting; daily may be sparse. The 60/20/20 segments are descriptive because this history has been inspected previously.", "",
             "| Timeframe | Source bars | Analysis bars | Valid bars | Candidate windows | Selected episodes |",
             "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for tf, q in summary["quality"].items():
        lines.append(f"| {tf} | {q['rows']} | {q['analysis_rows']} | {q['valid_rows']} | {q['candidate_window_count']} | {q['selected_episode_count']} |")
    for tf, result in summary["timeframes"].items():
        lines += ["", f"## {tf} cohorts", "", "Expected direction is up after prior declines and down after prior rises. A decisive denominator includes only up-first and down-first; ambiguous, neither and incomplete are shown separately.", "",
                  "| Cohort | Horizon | Candidates | Episodes | Up first | Down first | Ambiguous | Neither | Incomplete | Expected-direction / decisive | Mean excursion lean | Mean future close in phase range | Mean location change |",
                  "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
        for cohort in COHORTS:
            for h in HORIZONS:
                s = result["cohorts"][cohort][str(h)]
                lines.append(f"| {cohort} | {h} | {s['candidate_window_count']} | {s['selected_episode_count']} | {s['up_first']} | {s['down_first']} | {s['ambiguous']} | {s['neither']} | {s['incomplete']} | {s['directional_success_count']}/{s['decisive_count']} ({pct(s['directional_success_rate'])}) | {number(s['mean_excursion_lean'])} | {number(s['mean_future_close_phase_location'])} | {number(s['mean_future_close_phase_location_change'])} |")
        lines += ["", "Wick/body and open/close anatomy of selected episodes (medians):", "",
                  "| Cohort | Lower/body | Upper/body | Lower share | Upper share | Wick skew | Signal open location | Signal close location |",
                  "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
        for cohort in COHORTS:
            a = result["cohorts"][cohort]["3"]["anatomy"]
            lines.append(f"| {cohort} | {number(a['median_phase_lower_body_ratio'])} | {number(a['median_phase_upper_body_ratio'])} | {number(a['median_lower_range_share'])} | {number(a['median_upper_range_share'])} | {number(a['median_wick_skew'])} | {number(a['median_signal_open_location'])} | {number(a['median_signal_close_location'])} |")
        lines += ["", "Proxy minus same-trend neutral (exploratory calendar-month block intervals):", "",
                  "| Comparison | Horizon | Difference | 95% interval | Decisive proxy / neutral | Months with decisive hits |",
                  "| --- | ---: | ---: | ---: | ---: | ---: |"]
        for key, horizons in result["comparisons"].items():
            for h in HORIZONS:
                item = horizons[str(h)]
                interval = item["interval_95"]
                shown = "—" if interval is None else f"[{pct(interval[0])}, {pct(interval[1])}]"
                lines.append(f"| {key} | {h} | {pct(item['difference'])} | {shown} | {item['proxy_decisive']} / {item['neutral_decisive']} | {item['months_with_decisive_hits']} |")
        lines += ["", "Chronological segments (descriptive; counts are decisive first hits):", "",
                  "| Segment | Horizon | Accumulation proxy | Downtrend neutral | Distribution proxy | Uptrend neutral |",
                  "| --- | ---: | ---: | ---: | ---: | ---: |"]
        for period in PERIODS:
            for h in HORIZONS:
                cells = []
                for cohort in ("accumulation_proxy", "downtrend_neutral", "distribution_proxy", "uptrend_neutral"):
                    s = result["periods"][period][cohort][str(h)]
                    cells.append(f"{s['directional_success_count']}/{s['decisive_count']} ({pct(s['directional_success_rate'])})")
                lines.append(f"| {period} | {h} | " + " | ".join(cells) + " |")
    lines += ["", "## Definitions and limitations", ""]
    for key, value in summary["definitions"].items():
        lines.append(f"- **{key.replace('_', ' ')}:** {value}")
    for item in summary["limitations"]:
        lines.append(f"- {item}")
    lines += ["", "`events.csv` includes every qualifying candidate, the outcome-independent selected flag, frozen features, timestamps, contract identity, per-horizon censor reasons, first-hit outcomes and future path measurements. `summary.json` includes cohort and chronological segment counts plus source/data hashes.", ""]
    return "\n".join(lines)


def parse_assignment(value: str, allowed: tuple[str, ...], label: str) -> tuple[str, str]:
    tf, separator, payload = value.partition("=")
    if not separator or tf not in allowed or not payload:
        raise argparse.ArgumentTypeError(f"{label} must be TF=VALUE for one of {', '.join(allowed)}")
    return tf, payload


def check_resample_manifest(path: Path, timeframe: str, symbol: str, file_hash: str) -> dict | None:
    manifest_path = path.parent / "resample_manifest.json"
    if not manifest_path.is_file():
        if symbol in ("ES", "CL"):
            raise ValueError(f"{symbol} input requires a resample_manifest.json beside {path}")
        return None
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    session = manifest.get("session", {})
    item = manifest.get("timeframes", {}).get(timeframe, {})
    if (manifest.get("symbol") != symbol or manifest.get("timestamp_label") != "bar_open_utc"
            or session.get("timezone") != "America/New_York"
            or session.get("open_time") != "18:00" or session.get("close_time") != "17:00"
            or session.get("id") != "full-trading-day"
            or item.get("sha256") != file_hash
            or Path(str(item.get("path", ""))).resolve() != path.resolve()):
        raise ValueError(f"Resample manifest does not match {symbol} {timeframe} input/session/hash")
    return dict(path=str(manifest_path), sha256=sha256_file(manifest_path),
                source_sha256=manifest.get("source", {}).get("sha256"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", action="append", default=[], metavar="TF=PARQUET",
                        help="Repeat for 1h, 4h, 1d; omit to use the local MNQ files")
    parser.add_argument("--min-minutes", action="append", default=[], metavar="TF=COUNT",
                        help="Override the fraction gate with an absolute observed-minute count for one timeframe")
    parser.add_argument("--min-coverage", "--coverage-fraction", dest="coverage_fraction", type=float, default=.90,
                        help="Required share of expected CME-session minutes per bar; default 0.90")
    parser.add_argument("--symbol", default="MNQ", help="Instrument label (tick size inferred for MNQ, ES, CL)")
    parser.add_argument("--tick-size", type=float, help="Explicit price tick size; required for other symbols")
    parser.add_argument("--start", default="2019-05-05", help="First UTC signal-availability date, inclusive")
    parser.add_argument("--end", default="2026-09-03", help="Last UTC signal-availability date, inclusive")
    parser.add_argument("--output-dir", type=Path, help="New directory for the CSV, JSON and Markdown artifacts")
    parser.add_argument("--phase-bars", type=int, default=6)
    parser.add_argument("--context-bars", type=int, default=20)
    parser.add_argument("--compact-atr", type=float, default=2.5)
    parser.add_argument("--trend-atr", type=float, default=1.)
    parser.add_argument("--wick-skew", type=float, default=.10)
    parser.add_argument("--cooldown-bars", type=int, default=6)
    parser.add_argument("--bootstrap-samples", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=1729)
    args = parser.parse_args()
    if args.phase_bars < 2 or args.context_bars < 2 or args.cooldown_bars < max(HORIZONS):
        parser.error("phase/context must have at least two bars; cooldown must cover the longest outcome horizon")
    if args.compact_atr <= 0 or args.trend_atr <= 0 or not 0 < args.wick_skew < 1:
        parser.error("compact/trend ATR must be positive and wick skew must be between 0 and 1")
    if args.bootstrap_samples < 200 or args.seed < 0:
        parser.error("bootstrap samples must be at least 200 and seed must be nonnegative")
    if not 0 < args.coverage_fraction <= 1:
        parser.error("coverage fraction must be greater than zero and at most one")
    if args.tick_size is None:
        args.tick_size = TICK_SIZES.get(args.symbol.upper())
    if args.tick_size is None or args.tick_size <= 0:
        parser.error("a positive --tick-size is required for this symbol")
    try:
        start, end = pd.Timestamp(args.start), pd.Timestamp(args.end)
        if start.tzinfo is not None or end.tzinfo is not None or start >= end:
            raise ValueError
        if start.strftime("%Y-%m-%d") != args.start or end.strftime("%Y-%m-%d") != args.end:
            raise ValueError
    except ValueError:
        parser.error("start/end must be chronological YYYY-MM-DD UTC dates")
    return args


def main() -> None:
    args = parse_args()
    inputs = {}
    for assignment in args.input:
        tf, payload = parse_assignment(assignment, TIMEFRAMES, "--input")
        if tf in inputs:
            raise ValueError(f"Duplicate input for {tf}")
        inputs[tf] = Path(payload).resolve()
    if not inputs:
        inputs = {tf: DEFAULT_DATA / f"candles_{tf}.parquet" for tf in TIMEFRAMES}
    min_minutes = {}
    for assignment in args.min_minutes:
        tf, payload = parse_assignment(assignment, TIMEFRAMES, "--min-minutes")
        if tf not in inputs:
            raise ValueError(f"No input for minimum-minute gate {tf}")
        value = int(payload)
        if value < 1:
            raise ValueError("Minimum observed minutes must be positive")
        min_minutes[tf] = value
    config = dict(symbol=args.symbol.upper(), tick_size=args.tick_size,
                  start=args.start, end=args.end, coverage_fraction=args.coverage_fraction,
                  phase_bars=args.phase_bars, context_bars=args.context_bars,
                  compact_atr=args.compact_atr, trend_atr=args.trend_atr,
                  wick_skew=args.wick_skew, cooldown_bars=args.cooldown_bars,
                  min_minutes=min_minutes, horizons=list(HORIZONS),
                  bootstrap_samples=args.bootstrap_samples, seed=args.seed)
    input_info, events, quality = {}, {}, {}
    for tf, path in inputs.items():
        if not path.is_file():
            raise FileNotFoundError(path)
        digest = sha256_file(path)
        input_info[tf] = dict(path=str(path), sha256=digest,
                              resample_manifest=check_resample_manifest(path, tf, config["symbol"], digest))
    source_hash = sha256_file(Path(__file__))
    destination = args.output_dir or (ROOT / "reports" / "htf-wick-phases" /
                                     (f"{config['symbol']}-q{int(args.coverage_fraction * 100)}-" +
                                      datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]))
    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=False)
    source_dir = destination / "source"
    source_dir.mkdir()
    source_snapshot = source_dir / Path(__file__).name
    shutil.copy2(Path(__file__), source_snapshot)
    if sha256_file(source_snapshot) != source_hash:
        raise RuntimeError("Source changed while its snapshot was being created")
    protocol = dict(study="HTF wick-phase proxy event study", registered_at=datetime.now(timezone.utc).isoformat(),
                    design_status="retrospective/exploratory; prior workspace research inspected history",
                    config=config, source_sha256=source_hash, source_snapshot=str(source_snapshot),
                    python=sys.version, pandas=pd.__version__, numpy=np.__version__,
                    inputs=input_info, expected_session_minutes={"1h": [60], "4h": [180, 240], "1d": [1380]})
    (destination / "protocol.json").write_text(json.dumps(protocol, indent=2) + "\n", encoding="utf-8")
    print(f"Registered protocol before outcome computation: {destination / 'protocol.json'}", flush=True)
    for tf, path in inputs.items():
        frame = pd.read_parquet(path)
        if not isinstance(frame.index, pd.DatetimeIndex) and "ts_event" in frame:
            frame = frame.set_index(pd.to_datetime(frame.pop("ts_event"), utc=True))
        events[tf], quality[tf] = detect_and_score(frame, tf, config)
        print(f"{tf}: {quality[tf]['candidate_window_count']} compact/trend candidates, "
              f"{quality[tf]['selected_episode_count']} selected episodes", flush=True)
    summary = summarize(events, quality, config, input_info, source_hash)
    if sha256_file(Path(__file__)) != source_hash:
        raise RuntimeError("Research source changed while outcomes were computed")
    for tf, item in input_info.items():
        if sha256_file(Path(item["path"])) != item["sha256"]:
            raise RuntimeError(f"{tf} data changed while outcomes were computed")
    all_events = [row for tf in inputs for row in events[tf]]
    pd.DataFrame(all_events).to_csv(destination / "events.csv", index=False)
    summary["artifacts"] = {"events.csv": sha256_file(destination / "events.csv")}
    (destination / "summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    (destination / "summary.md").write_text(markdown_report(summary), encoding="utf-8")
    (destination / "manifest.json").write_text(json.dumps({
        "source_sha256": source_hash, "data_sha256": {tf: item["sha256"] for tf, item in input_info.items()},
        "artifacts": {name: sha256_file(destination / name) for name in ("protocol.json", "source/research-htf-wick-phases.py", "events.csv", "summary.json", "summary.md")},
    }, indent=2) + "\n", encoding="utf-8")
    print(f"Artifacts: {destination}", flush=True)


if __name__ == "__main__":
    main()
