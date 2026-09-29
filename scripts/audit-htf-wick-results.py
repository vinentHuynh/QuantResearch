#!/usr/bin/env python3
"""Independently audit a frozen higher-timeframe wick-phase result directory.

Reads the saved protocol, ledger, summary, and original parquet inputs. It never
imports or runs the study source and writes nothing into the frozen result.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections import Counter
from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd


ET = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")
PERIODS = ("early_60pct", "middle_20pct", "late_20pct")
COHORTS = (
    "accumulation_proxy", "downtrend_neutral", "downtrend_opposite",
    "distribution_proxy", "uptrend_neutral", "uptrend_opposite",
)
# The first frozen study version labeled a final analysis boundary as a generic
# period boundary when the source contained later bars. Its successor records
# that distinct condition as analysis_end. The saved source checksum selects
# the versioned expectation without consulting the ledger's claimed reason.
LEGACY_CENSOR_SOURCE_SHA256 = "9cf01c7401a5d11981e1913e0f8dc13af85792b486d4c9b73711c122fcc77b32"


class Audit:
    def __init__(self) -> None:
        self.failures: list[str] = []
        self.failure_count = 0

    def check(self, condition: bool, message: str) -> None:
        if not condition:
            self.failure_count += 1
            if len(self.failures) < 30:
                self.failures.append(message)

    def number(self, actual: object, expected: float | None, label: str) -> None:
        if expected is None:
            self.check(pd.isna(actual), f"{label}: expected blank, got {actual}")
            return
        try:
            value = float(actual)
            good = math.isclose(value, expected, rel_tol=1e-10, abs_tol=1e-8)
        except (TypeError, ValueError):
            good = False
        self.check(good, f"{label}: expected {expected}, got {actual}")

    def same(self, actual: object, expected: object, label: str) -> None:
        if expected is None:
            self.check(pd.isna(actual), f"{label}: expected blank, got {actual}")
        else:
            self.check(str(actual) == str(expected), f"{label}: expected {expected}, got {actual}")

    def timestamp(self, actual: object, expected: pd.Timestamp | None, label: str) -> None:
        if expected is None:
            self.check(pd.isna(actual), f"{label}: expected blank, got {actual}")
            return
        try:
            good = pd.Timestamp(actual) == expected
        except (TypeError, ValueError):
            good = False
        self.check(good, f"{label}: expected {expected}, got {actual}")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def input_integrity(root: Path, protocol: dict, summary: dict, manifest: dict, audit: Audit) -> None:
    saved_source = root / "source" / "research-htf-wick-phases.py"
    source_hash = sha256(saved_source)
    audit.check(Path(protocol["source_snapshot"]).resolve() == saved_source.resolve(),
                "protocol source snapshot path differs from the frozen source")
    for where, recorded in (("protocol", protocol["source_sha256"]),
                            ("summary", summary["source_sha256"]),
                            ("manifest", manifest["source_sha256"])):
        audit.check(recorded == source_hash, f"{where} source hash mismatch")
    for name, recorded in manifest["artifacts"].items():
        path = root / name
        audit.check(path.is_file() and sha256(path) == recorded, f"artifact hash mismatch: {name}")
    audit.check(protocol["config"] == summary["config"], "protocol/summary config mismatch")
    audit.check(set(protocol["inputs"]) == set(summary["inputs"]) == set(manifest["data_sha256"]),
                "protocol/summary/manifest timeframe mismatch")
    audit.check(set(summary["timeframes"]) == set(protocol["inputs"]),
                "summary timeframe set differs from inputs")
    for tf, entry in protocol["inputs"].items():
        source = Path(entry["path"])
        digest = sha256(source)
        for where, recorded in (("protocol", entry["sha256"]),
                                ("summary", summary["inputs"][tf]["sha256"]),
                                ("manifest", manifest["data_sha256"][tf])):
            audit.check(recorded == digest, f"{tf} {where} input hash mismatch")
        audit.check(Path(summary["inputs"][tf]["path"]).resolve() == source.resolve(),
                    f"{tf} summary input path mismatch")
        resample = entry.get("resample_manifest")
        audit.check(resample == summary["inputs"][tf].get("resample_manifest"),
                    f"{tf} resample provenance mismatch")
        if resample:
            provenance = Path(resample["path"])
            audit.check(sha256(provenance) == resample["sha256"],
                        f"{tf} resample manifest hash mismatch")
            source_manifest = load_json(provenance)
            audit.check(source_manifest["timeframes"][tf]["sha256"] == digest,
                        f"{tf} resample manifest input hash mismatch")
            audit.check(source_manifest["source"]["sha256"] == resample["source_sha256"],
                        f"{tf} underlying source hash claim mismatch")


def prepared_bars(frame: pd.DataFrame, timeframe: str, cfg: dict) -> dict:
    """Construct quality and close-availability data without study helpers."""
    if not isinstance(frame.index, pd.DatetimeIndex) or frame.index.tz is None:
        raise ValueError(f"{timeframe}: missing timezone-aware bar-open index")
    if frame.index.has_duplicates or not frame.index.is_monotonic_increasing:
        raise ValueError(f"{timeframe}: bar-open index must be sorted and unique")
    index = frame.index.tz_convert("UTC")
    local = index.tz_convert(ET)
    n = len(frame)
    prices = frame[["open", "high", "low", "close"]].to_numpy(float)
    op, hi, lo, cl = prices.T
    ids = frame.instrument_id.astype("string").fillna("").to_numpy(str)
    contract_count = pd.to_numeric(frame.contract_count, errors="coerce").to_numpy(float)
    minute_count = pd.to_numeric(frame.minute_count, errors="coerce").to_numpy(float)
    expected_minutes = np.full(n, {"1h": 60, "4h": 240, "1d": 1380}[timeframe])
    if timeframe == "4h":
        expected_minutes[local.hour == 14] = 180
    minimum = cfg["min_minutes"].get(timeframe)
    required = minimum if minimum is not None else np.ceil(expected_minutes * cfg["coverage_fraction"])
    prices_good = (np.isfinite(prices).all(axis=1) & (hi > lo)
                   & (hi >= np.maximum.reduce([op, cl, lo]))
                   & (lo <= np.minimum.reduce([op, cl, hi])))
    roll = frame.is_roll_bar.fillna(True).to_numpy(bool)
    transition = (frame.is_roll_transition.fillna(True).to_numpy(bool)
                  if "is_roll_transition" in frame else np.zeros(n, dtype=bool))
    contract_good = (contract_count == 1) & ~roll & ~transition & (ids != "")

    # Each represented exchange session must have its complete set of bar opens.
    # Daily bars use the single 18:00 ET open; intraday sets end at 14:00/16:00.
    slots = {"1h": set(range(18, 24)) | set(range(0, 17)),
             "4h": {18, 22, 2, 6, 10, 14}, "1d": {18}}[timeframe]
    session_dates = [stamp.date() + timedelta(days=int(stamp.hour >= 18)) for stamp in local]
    by_session: dict[object, list[int]] = {}
    for j, date in enumerate(session_dates):
        by_session.setdefault(date, []).append(j)
    full_session = np.zeros(n, dtype=bool)
    for locations in by_session.values():
        observed = {(local[j].hour, local[j].minute) for j in locations}
        if len(locations) == len(slots) and observed == {(hour, 0) for hour in slots}:
            full_session[locations] = True
    valid = prices_good & (minute_count >= required) & contract_good & full_session

    # The timestamp at which each completed candle becomes observable.
    close_by_date = {date: pd.Timestamp(datetime.combine(date, time(17), ET)).tz_convert(UTC)
                     for date in by_session}
    availability = []
    for j, stamp in enumerate(index):
        close = close_by_date[session_dates[j]]
        nominal = (stamp + pd.Timedelta(hours=1 if timeframe == "1h" else 4)
                   if timeframe != "1d" else close)
        availability.append(min(nominal, close))
    available = pd.DatetimeIndex(availability)
    return dict(index=index, available=available, open=op, high=hi, low=lo, close=cl,
                ids=ids, valid=valid)


def classify(trend: float, skew: float, cfg: dict) -> str:
    threshold = cfg["wick_skew"]
    if trend <= -cfg["trend_atr"]:
        return ("accumulation_proxy" if skew >= threshold else
                "downtrend_opposite" if skew <= -threshold else "downtrend_neutral")
    if trend >= cfg["trend_atr"]:
        return ("distribution_proxy" if skew <= -threshold else
                "uptrend_opposite" if skew >= threshold else "uptrend_neutral")
    raise ValueError("selected candidate has an insufficient prior trend")


def analysis_bounds(bars: dict, cfg: dict) -> tuple[int, tuple[int, int, int]]:
    start = pd.Timestamp(cfg["start"], tz="UTC")
    end = pd.Timestamp(cfg["end"], tz="UTC") + pd.Timedelta(days=1)
    left = int(bars["available"].searchsorted(start))
    right = int(bars["available"].searchsorted(end))
    count = right - left
    return left, (left + int(count * .6), left + int(count * .8), right)


def period_and_right(i: int, cuts: tuple[int, int, int]) -> tuple[str, int]:
    for name, right in zip(PERIODS, cuts):
        if i < right:
            return name, right
    raise ValueError(f"event index {i} lies beyond analysis range")


def independent_event(row: pd.Series, bars: dict, cfg: dict, cuts: tuple[int, int, int],
                      source_sha256: str, audit: Audit) -> dict:
    tf, i = row["timeframe"], int(row["signal_index"])
    prefix = f"{tf} index {i}"
    phase_start = i - cfg["phase_bars"] + 1
    context_start = phase_start - cfg["context_bars"]
    preceding = context_start - 1
    audit.check(preceding >= 0, f"{prefix}: missing pre-context close")
    audit.check(bool(np.all(bars["valid"][preceding:i + 1])),
                f"{prefix}: invalid context/phase bar")
    audit.check(bool(np.all(bars["ids"][preceding:i + 1] == bars["ids"][i])),
                f"{prefix}: context/phase crosses contracts")
    op, hi, lo, cl = (bars[k] for k in ("open", "high", "low", "close"))

    # Compute each true range from the strictly prephase context and its own
    # previous close. No signal or future candle enters this normalization.
    true_ranges = [max(hi[j] - lo[j], abs(hi[j] - cl[j - 1]), abs(lo[j] - cl[j - 1]))
                   for j in range(context_start, phase_start)]
    atr = sum(true_ranges) / cfg["context_bars"]
    low = float(min(lo[phase_start:i + 1]))
    high = float(max(hi[phase_start:i + 1]))
    span = high - low
    trend = float((cl[phase_start - 1] - cl[preceding]) / atr)
    upper = sum(hi[j] - max(op[j], cl[j]) for j in range(phase_start, i + 1))
    lower = sum(min(op[j], cl[j]) - lo[j] for j in range(phase_start, i + 1))
    total_range = sum(hi[j] - lo[j] for j in range(phase_start, i + 1))
    skew = float((lower - upper) / total_range)
    cohort = classify(trend, skew, cfg)
    period, right = period_and_right(i, cuts)
    audit.check(span > 0 and span / atr <= cfg["compact_atr"] + 1e-12,
                f"{prefix}: selected phase fails compactness")
    for name, value in (("atr_prephase", atr), ("phase_low", low),
                        ("phase_high", high), ("phase_range", span),
                        ("compactness_atr", span / atr),
                        ("prior_trend_atr", trend), ("wick_skew", skew),
                        ("phase_upper_wick", upper), ("phase_lower_wick", lower),
                        ("phase_total_candle_range", total_range),
                        ("signal_close", cl[i]),
                        ("phase_close_location", (cl[i] - low) / span)):
        audit.number(row[name], float(value), f"{prefix} {name}")
    for name, value in (("cohort", cohort), ("period", period),
                        ("instrument_id", bars["ids"][i]),
                        ("event_id", f"{tf}-{i}")):
        audit.same(row[name], value, f"{prefix} {name}")
    audit.timestamp(row["phase_start_time"], bars["index"][phase_start],
                    f"{prefix} phase_start_time")
    audit.timestamp(row["phase_end_time"], bars["available"][i],
                    f"{prefix} phase_end_time")
    audit.timestamp(row["signal_bar_open_time"], bars["index"][i],
                    f"{prefix} signal_bar_open_time")
    audit.timestamp(row["context_end_time"], bars["available"][phase_start - 1],
                    f"{prefix} context_end_time")

    scored: dict[int, dict] = {}
    for horizon in cfg["horizons"]:
        key = f"h{horizon}_"
        end = i + horizon
        reason = None
        if end >= right:
            if period != PERIODS[-1]:
                reason = "period_boundary"
            elif right == len(cl):
                reason = "data_end"
            elif source_sha256 == LEGACY_CENSOR_SOURCE_SHA256:
                reason = "period_boundary"
            else:
                reason = "analysis_end"
        elif np.any(bars["ids"][i + 1:end + 1] != bars["ids"][i]):
            reason = "contract_transition"
        elif not np.all(bars["valid"][i + 1:end + 1]):
            reason = "invalid_future_bar"
        if reason:
            audit.same(row[key + "outcome"], "incomplete", f"{prefix} {key}outcome")
            audit.same(row[key + "censor_reason"], reason, f"{prefix} {key}censor_reason")
            audit.number(row[key + "future_close_phase_location_change"], None,
                         f"{prefix} {key}location_change")
            scored[horizon] = dict(outcome="incomplete", location_change=None)
            continue

        upper_barrier, lower_barrier = cl[i] + atr, cl[i] - atr
        outcome, first = "neither", None
        for step in range(1, horizon + 1):
            reached_up = hi[i + step] >= upper_barrier
            reached_down = lo[i + step] <= lower_barrier
            if reached_up or reached_down:
                outcome = ("ambiguous" if reached_up and reached_down else
                           "up_first" if reached_up else "down_first")
                first = step
                break
        change = float((cl[end] - cl[i]) / span)
        future_location = float((cl[end] - low) / span)
        audit.same(row[key + "outcome"], outcome, f"{prefix} {key}outcome")
        audit.same(row[key + "censor_reason"], None, f"{prefix} {key}censor_reason")
        audit.number(row[key + "first_hit_bar"], first, f"{prefix} {key}first_hit_bar")
        audit.timestamp(row[key + "first_hit_time"], bars["available"][i + first] if first else None,
                        f"{prefix} {key}first_hit_time")
        audit.number(row[key + "future_close_phase_location_change"], change,
                     f"{prefix} {key}location_change")
        audit.number(row[key + "future_close_phase_location"], future_location,
                     f"{prefix} {key}future_location")
        audit.timestamp(row[key + "end_time"], bars["available"][end],
                        f"{prefix} {key}end_time")
        scored[horizon] = dict(outcome=outcome, location_change=change)
    return dict(cohort=cohort, period=period, scored=scored)


def reconcile_group(rows: pd.DataFrame, selected: list[dict], saved: dict,
                    horizon: int, cohort: str, label: str, audit: Audit) -> None:
    outcomes = Counter(e["scored"][horizon]["outcome"] for e in selected)
    up, down = outcomes["up_first"], outcomes["down_first"]
    decisive = up + down
    direction = "up_first" if cohort.startswith("downtrend") or cohort == "accumulation_proxy" else "down_first"
    expected = {
        "candidate_window_count": len(rows), "selected_episode_count": len(selected),
        "complete_horizon_count": len(selected) - outcomes["incomplete"],
        "decisive_count": decisive, "directional_success_count": outcomes[direction],
        "up_first": up, "down_first": down, "ambiguous": outcomes["ambiguous"],
        "neither": outcomes["neither"], "incomplete": outcomes["incomplete"],
    }
    for name, value in expected.items():
        audit.check(saved[name] == value, f"{label} {name}: expected {value}, got {saved[name]}")
    if decisive:
        audit.number(saved["directional_success_rate"], outcomes[direction] / decisive,
                     f"{label} directional_success_rate")
    else:
        audit.check(saved["directional_success_rate"] is None,
                    f"{label} directional_success_rate must be null")
    changes = [e["scored"][horizon]["location_change"] for e in selected
               if e["scored"][horizon]["location_change"] is not None]
    audit.number(saved["mean_future_close_phase_location_change"],
                 float(np.mean(changes)) if changes else None, f"{label} mean location change")
    audit.number(saved["median_future_close_phase_location_change"],
                 float(np.median(changes)) if changes else None, f"{label} median location change")


def audit_results(root: Path) -> dict:
    audit = Audit()
    protocol = load_json(root / "protocol.json")
    summary = load_json(root / "summary.json")
    manifest = load_json(root / "manifest.json")
    input_integrity(root, protocol, summary, manifest, audit)
    cfg = protocol["config"]
    ledger = pd.read_csv(root / "events.csv")
    audit.check(not ledger.empty, "event ledger is empty")
    audit.check(not ledger.event_id.duplicated().any(), "duplicate event IDs")
    audit.check(set(ledger.timeframe) == set(protocol["inputs"]), "ledger timeframe set mismatch")
    audit.check(ledger.candidate.eq(True).all(), "ledger contains a noncandidate row")
    report = {}

    for tf, entry in protocol["inputs"].items():
        frame = pd.read_parquet(Path(entry["path"]))
        if not isinstance(frame.index, pd.DatetimeIndex) and "ts_event" in frame:
            frame = frame.set_index(pd.to_datetime(frame.pop("ts_event"), utc=True))
        bars = prepared_bars(frame, tf, cfg)
        analysis_left, cuts = analysis_bounds(bars, cfg)
        rows = ledger.loc[ledger.timeframe == tf].sort_values("signal_index")
        audit.check(rows.signal_index.is_unique, f"{tf}: duplicate signal indices")
        audit.check(rows.signal_index.is_monotonic_increasing, f"{tf}: unordered signal indices")
        audit.check(rows.signal_index.between(analysis_left, cuts[-1] - 1).all(),
                    f"{tf}: candidate outside analysis window")
        last_selected = -10**9
        independently_selected: list[dict] = []
        selected_by_period: dict[str, list[dict]] = {p: [] for p in PERIODS}
        selected_by_cohort: dict[str, list[dict]] = {c: [] for c in COHORTS}
        for _, row in rows.iterrows():
            i = int(row.signal_index)
            expected_selected = i > last_selected + cfg["cooldown_bars"]
            audit.check(bool(row.selected) == expected_selected,
                        f"{tf} index {i}: selected flag violates greedy cooldown")
            if expected_selected:
                last_selected = i
                recomputed = independent_event(row, bars, cfg, cuts,
                                               protocol["source_sha256"], audit)
                independently_selected.append(recomputed)
                selected_by_period[recomputed["period"]].append(recomputed)
                selected_by_cohort[recomputed["cohort"]].append(recomputed)
        quality = summary["quality"][tf]
        audit.check(quality["candidate_window_count"] == len(rows),
                    f"{tf} summary candidate count mismatch")
        audit.check(quality["selected_episode_count"] == len(independently_selected),
                    f"{tf} summary selected count mismatch")
        for cohort in COHORTS:
            subset = rows.loc[rows.cohort == cohort]
            for horizon in cfg["horizons"]:
                saved = summary["timeframes"][tf]["cohorts"][cohort][str(horizon)]
                reconcile_group(subset, selected_by_cohort[cohort], saved, horizon, cohort,
                                f"{tf}/{cohort}/h{horizon}", audit)
        for period in PERIODS:
            for cohort in COHORTS:
                subset = rows.loc[(rows.period == period) & (rows.cohort == cohort)]
                selected = [e for e in selected_by_period[period] if e["cohort"] == cohort]
                for horizon in cfg["horizons"]:
                    saved = summary["timeframes"][tf]["periods"][period][cohort][str(horizon)]
                    reconcile_group(subset, selected, saved, horizon, cohort,
                                    f"{tf}/{period}/{cohort}/h{horizon}", audit)
        report[tf] = {"candidate_rows": len(rows), "selected_events": len(independently_selected),
                      "complete_horizons": {str(h): sum(e["scored"][h]["outcome"] != "incomplete"
                                                        for e in independently_selected)
                                            for h in cfg["horizons"]}}
    return {"status": "passed" if audit.failure_count == 0 else "failed",
            "result_dir": str(root), "timeframes": report,
            "mismatch_count": audit.failure_count, "mismatches": audit.failures}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("result_dir", type=Path, help="Frozen HTF wick-phase result directory")
    args = parser.parse_args()
    try:
        result = audit_results(args.result_dir.resolve())
    except Exception as exc:
        result = {"status": "error", "result_dir": str(args.result_dir.resolve()),
                  "error": f"{type(exc).__name__}: {exc}"}
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
