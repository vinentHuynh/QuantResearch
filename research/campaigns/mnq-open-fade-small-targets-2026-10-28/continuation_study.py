"""Frozen descriptive MNQ first-threshold continuation event study.

Read-only input loading. The only historical outputs are written to this
campaign's new report directory. A matching frozen-protocol hash must be passed
explicitly before historical outcomes can be generated. No parameter selection
or strategy promotion occurs here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BASE = ROOT / "reports/mnq-ny-open-2026-10-28"
OUT = ROOT / "reports/mnq-open-fade-small-targets-2026-10-28"
THRESHOLDS = (40, 60, 80, 100, 120, 160)
HORIZONS = (60, 120)
BARRIERS = ("balanced_20", "balanced_initial_move")
BOOTSTRAP_DRAWS = 2000
BOOTSTRAP_SEED = 20261028
PERIODS = {
    "all_2019_2026": ("2019-05-06", "2026-09-03"),
    "development_2019_2023": ("2019-05-06", "2023-12-31"),
    "2024_onward": ("2024-01-01", "2026-09-03"),
    "2026_only": ("2026-01-01", "2026-09-03"),
}
EPS = 1e-9


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def safe(value):
    if isinstance(value, dict):
        return {str(k): safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [safe(v) for v in value]
    if isinstance(value, np.generic):
        return safe(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def load_sessions():
    """Reconstruct the prior study's exact cash-date sample without mutating it."""
    meta = json.loads((BASE / "summary.json").read_text())["metadata"]
    source = Path(meta["data_path"])
    if sha(source) != meta["sha256"]:
        raise ValueError("Immutable source checksum mismatch")
    raw = pd.read_parquet(source, columns=["open", "high", "low", "close", "instrument_id", "symbol"])
    assert not raw.index.has_duplicates and raw.index.is_monotonic_increasing
    assert set(raw.symbol.unique()) == {"MNQ.v.0"}
    raw = raw.tz_convert("America/New_York")
    morning = raw.between_time("09:30", "11:44").copy()
    morning["date"] = morning.index.strftime("%Y-%m-%d")
    groups = dict(tuple(morning.groupby("date")))
    calendar_dates = pd.read_csv(BASE / "cash_calendar.csv").cash_session.tolist()
    prior_dates = sorted(pd.read_csv(BASE / "opening_sessions.csv", usecols=["date"]).date.unique())
    sessions, exclusions = {}, []
    for date in calendar_dates:
        expected = pd.date_range(date + " 09:30", periods=135, freq="min", tz="America/New_York")
        frame = groups.get(date, morning.iloc[:0])
        missing = expected.difference(frame.index)
        if len(missing) or frame.instrument_id.nunique() != 1:
            exclusions.append({"date": date, "missing_minutes": len(missing),
                               "reason": "missing minutes" if len(missing) else "contract change"})
            continue
        assert frame.index.equals(expected.rename(frame.index.name))
        values = frame[["open", "high", "low", "close"]].to_numpy(dtype=float)
        assert np.isfinite(values).all()
        sessions[date] = values
    assert sorted(sessions) == prior_dates
    assert len(sessions) == meta["included_sessions"] == 1841
    assert {x["date"] for x in exclusions} == {x["date"] for x in meta["excluded_sessions"]}
    return sessions, meta, exclusions


def first_touch(bars, threshold):
    """Independent first-touch date/minute/direction audit, with open priority."""
    origin = float(bars[0, 0])
    for index, bar in enumerate(bars[:15]):
        opening, high, low = bar[:3]
        if opening >= origin + threshold - EPS:
            return index, "up", False
        if opening <= origin - threshold + EPS:
            return index, "down", False
        up, down = high >= origin + threshold - EPS, low <= origin - threshold + EPS
        if up or down:
            return index, "ambiguous" if up and down else "up" if up else "down", bool(up and down)
    return None, None, False


def category(result):
    reason = result["exit_reason"]
    if reason.startswith("stop"):
        return "continuation"
    if reason.startswith("target"):
        return "retracement"
    if reason.startswith("time"):
        return "neither"
    raise AssertionError(f"Filled threshold event has unexpected exit reason: {reason}")


def event_bounds(conservative, favorable):
    """Zero-cost symmetric fade payoff ordering gives barrier category bounds."""
    assert conservative["filled"] == favorable["filled"]
    assert conservative["filled"]
    assert conservative["gross_points"] <= favorable["gross_points"] + EPS
    ccat, fcat = category(conservative), category(favorable)
    certain_continuation = int(fcat == "continuation")
    possible_continuation = int(ccat == "continuation")
    certain_retracement = int(ccat == "retracement")
    possible_retracement = int(fcat == "retracement")
    certain_neither = int(ccat == fcat == "neither")
    ambiguous = int(ccat != fcat)
    assert certain_continuation <= possible_continuation
    assert certain_retracement <= possible_retracement
    assert certain_continuation + certain_retracement + certain_neither + ambiguous == 1
    return {"continuation_certain": certain_continuation,
            "continuation_possible": possible_continuation,
            "retracement_certain": certain_retracement,
            "retracement_possible": possible_retracement,
            "neither_certain": certain_neither, "outcome_ambiguous": ambiguous,
            "conservative_fade_category": ccat, "favorable_fade_category": fcat}


def assert_raw_witness(result, bars, threshold, distance):
    """Cross-check nominal levels and recorded exits directly against source OHLC."""
    side = result["side"]
    entry = bars[0, 0] - side * threshold
    assert abs(result["entry_price"] - entry) < EPS
    assert abs(result["stop_price"] - (entry - side * distance)) < EPS
    assert abs(result["target_price"] - (entry + side * distance)) < EPS
    opening, high, low, close = bars[result["exit_idx"]]
    reason = result["exit_reason"]
    if reason.startswith("stop"):
        assert (low <= result["stop_price"] + EPS) if side > 0 else (high >= result["stop_price"] - EPS)
        if result["exit_at_open"]:
            assert side * (opening - result["stop_price"]) <= EPS
            assert abs(result["exit_price"] - opening) < EPS
        else:
            assert abs(result["exit_price"] - result["stop_price"]) < EPS
    elif reason.startswith("target"):
        assert (high >= result["target_price"] - EPS) if side > 0 else (low <= result["target_price"] + EPS)
        if result["exit_at_open"]:
            assert side * (opening - result["target_price"]) >= -EPS
        assert abs(result["exit_price"] - result["target_price"]) < EPS
    else:
        assert reason == "time_exit" and result["exit_at_open"]
        assert result["exit_idx"] == result["entry_idx"] + result["horizon"]
        assert -distance + EPS < side * (opening - entry) < distance - EPS
        assert abs(result["exit_price"] - opening) < EPS


def simulate_events(sessions, simulate_day):
    records = []
    for threshold in THRESHOLDS:
        for date, bars in sessions.items():
            touch_idx, direction, direction_ambiguous = first_touch(bars, threshold)
            if touch_idx is None:
                continue
            for horizon in HORIZONS:
                for barrier in BARRIERS:
                    distance = 20 if barrier == "balanced_20" else threshold
                    results = {}
                    for policy in ("conservative", "favorable"):
                        result = simulate_day(bars, mode="touch", trigger=threshold,
                                              horizon=horizon, policy=policy,
                                              delay_bars=0, round_trip_cost_points=0,
                                              target_points=distance, stop_points=distance)
                        assert result["filled"] and result["entry_idx"] == touch_idx
                        assert result["trigger_idx"] == touch_idx
                        assert result["direction_ambiguous"] == direction_ambiguous
                        assert result["exit_idx"] <= touch_idx + horizon
                        if not direction_ambiguous:
                            assert result["first_direction"] == direction
                        assert_raw_witness(result, bars, threshold, distance)
                        results[policy] = result
                    conservative, favorable = results["conservative"], results["favorable"]
                    row = {"date": date, "month": date[:7], "year": int(date[:4]),
                           "threshold_points": threshold, "horizon_minutes": horizon,
                           "barrier_definition": barrier, "barrier_distance_points": distance,
                           "cash_open": float(bars[0, 0]), "touch_minute_index": touch_idx,
                           "touch_minute_et": f"{(570 + touch_idx)//60:02d}:{(570 + touch_idx)%60:02d}",
                           "deadline_minute_index": touch_idx + horizon,
                           "first_direction": direction, "direction_ambiguous": direction_ambiguous,
                           **event_bounds(conservative, favorable)}
                    if direction_ambiguous:
                        row["deadline_signed_displacement_points"] = np.nan
                        row["deadline_beyond_threshold"] = np.nan
                    else:
                        sign = 1 if direction == "up" else -1
                        signed = sign * (bars[touch_idx + horizon, 0] - bars[0, 0]) - threshold
                        row["deadline_signed_displacement_points"] = float(signed)
                        row["deadline_beyond_threshold"] = int(signed > EPS)
                    for policy, result in results.items():
                        prefix = policy + "_fade_"
                        for field in ("entry_idx", "entry_price", "entry_at_open", "side",
                                      "exit_idx", "exit_reason", "exit_price", "exit_at_open",
                                      "gross_points", "entrybar_target_ambiguous", "bracket_collision"):
                            row[prefix + field] = result[field]
                        row[prefix + "branches"] = json.dumps(safe(result.get("branches", [])), separators=(",", ":"))
                    records.append(row)
        print(f"Completed continuation threshold {threshold}", flush=True)
    events = pd.DataFrame(records)
    assert not events.duplicated(["date", "threshold_points", "horizon_minutes", "barrier_definition"]).any()
    return events


def monthly_ci(events, all_dates):
    """Percentile cluster bootstrap of ratios, retaining zero-event months."""
    months = sorted({date[:7] for date in all_dates})
    occupied = events.month.nunique() if len(events) else 0
    if len(events) < 100 or occupied < 10:
        result = {key: None for key in ("continuation_certain_ci_low_pct", "continuation_certain_ci_high_pct",
                                       "continuation_possible_ci_low_pct", "continuation_possible_ci_high_pct")}
        result.update(bootstrap_months=len(months), occupied_event_months=occupied,
                      bootstrap_nonempty_draws=0, sparse_evidence=True,
                      interval_suppression_reason="fewer than 100 events or 10 occupied event months")
        return result
    counts = events.groupby("month").agg(n=("date", "size"),
                                         lower=("continuation_certain", "sum"),
                                         upper=("continuation_possible", "sum")).reindex(months, fill_value=0)
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    indices = rng.integers(0, len(months), size=(BOOTSTRAP_DRAWS, len(months)))
    totals = counts.to_numpy(dtype=float)[indices].sum(axis=1)
    valid = totals[:, 0] > 0
    rates = totals[valid, 1:] / totals[valid, 0, None] * 100
    if not len(rates):
        raise AssertionError("All cluster bootstrap draws had empty denominators")
    interval = np.percentile(rates, [2.5, 97.5], axis=0)
    return {"continuation_certain_ci_low_pct": float(interval[0, 0]),
            "continuation_certain_ci_high_pct": float(interval[1, 0]),
            "continuation_possible_ci_low_pct": float(interval[0, 1]),
            "continuation_possible_ci_high_pct": float(interval[1, 1]),
            "bootstrap_months": len(months), "occupied_event_months": occupied,
            "bootstrap_nonempty_draws": int(valid.sum()), "sparse_evidence": False,
            "interval_suppression_reason": ""}


def summarize(events, all_dates, *, with_ci):
    n = len(events)
    row = {"cash_sessions": len(all_dates), "n": n,
           "threshold_reached_pct": n / len(all_dates) * 100 if all_dates else np.nan}
    for indicator in ("continuation_certain", "continuation_possible", "retracement_certain",
                      "retracement_possible", "neither_certain", "outcome_ambiguous", "direction_ambiguous"):
        count = int(events[indicator].sum()) if n else 0
        row[indicator + "_n"] = count
        row[indicator + "_pct"] = count / n * 100 if n else np.nan
    assert row["continuation_certain_n"] <= row["continuation_possible_n"] <= n
    assert row["retracement_certain_n"] <= row["retracement_possible_n"] <= n
    assert sum(row[x + "_n"] for x in ("continuation_certain", "retracement_certain", "neither_certain", "outcome_ambiguous")) == n
    known = events[~events.direction_ambiguous] if n else events
    row["terminal_direction_known_n"] = len(known)
    row["deadline_beyond_threshold_pct_of_direction_known"] = float(known.deadline_beyond_threshold.mean() * 100) if len(known) else np.nan
    row["deadline_signed_displacement_mean_points"] = float(known.deadline_signed_displacement_points.mean()) if len(known) else np.nan
    row["deadline_signed_displacement_median_points"] = float(known.deadline_signed_displacement_points.median()) if len(known) else np.nan
    if with_ci:
        row.update(monthly_ci(events, all_dates))
    row["minimum_n_100_met"] = n >= 100
    return row


def build_tables(events, all_dates):
    main, yearly, directions = [], [], []
    dimensions = ["threshold_points", "horizon_minutes", "barrier_definition", "barrier_distance_points"]
    for keys, group in events.groupby(dimensions, sort=True):
        identity = dict(zip(dimensions, keys))
        for period, (start, end) in PERIODS.items():
            sample = group[(group.date >= start) & (group.date <= end)]
            dates = [date for date in all_dates if start <= date <= end]
            row = dict(identity, period=period, start=start, end=end, **summarize(sample, dates, with_ci=True))
            ci_low = row.get("continuation_certain_ci_low_pct")
            row["primary_continuation_evidence_flag"] = bool(identity["barrier_definition"] == "balanced_20" and
                row["minimum_n_100_met"] and ci_low is not None and ci_low > 50)
            main.append(row)
            if identity["barrier_definition"] == "balanced_20":
                for direction in ("up", "down"):
                    directed = sample[sample.first_direction == direction]
                    drow = dict(identity, period=period, start=start, end=end, direction=direction,
                                direction_ambiguous_excluded_n=int(sample.direction_ambiguous.sum()),
                                **summarize(directed, dates, with_ci=True))
                    drow["threshold_reached_pct"] = np.nan  # Not an unconditional threshold probability.
                    directions.append(drow)
        if identity["barrier_definition"] == "balanced_20":
            for year in range(2019, 2027):
                sample = group[group.year == year]
                dates = [date for date in all_dates if int(date[:4]) == year]
                yearly.append(dict(identity, year=year, **summarize(sample, dates, with_ci=True)))
    return pd.DataFrame(main), pd.DataFrame(yearly), pd.DataFrame(directions)


def synthetic_mapping_checks(simulate_day):
    def flat():
        return np.repeat(np.array([[1000., 1000., 1000., 1000.]]), 135, axis=0)
    checks = []
    # First up touch at +40, then a known +20 continuation before any -20 return.
    bars = flat(); bars[1:] = [1040., 1040., 1040., 1040.]
    bars[0] = [1000., 1040., 1000., 1040.]
    bars[1] = [1040., 1065., 1035., 1060.]
    # The entry bar itself can have a pre-entry return extreme: favorable fade
    # may already retrace. Use an entry opening gap for an unambiguous test.
    bars[0] = [1000., 1005., 995., 1000.]
    bars[1] = [1040., 1065., 1035., 1060.]
    pair = [simulate_day(bars, mode="touch", trigger=40, horizon=60, policy=p,
                         round_trip_cost_points=0, target_points=20, stop_points=20)
            for p in ("conservative", "favorable")]
    bound = event_bounds(*pair)
    assert bound["continuation_certain"] == bound["continuation_possible"] == 1
    checks.append("Known continuation maps to fade stop in both policies")
    bars[1] = [1040., 1045., 1015., 1020.]
    pair = [simulate_day(bars, mode="touch", trigger=40, horizon=60, policy=p,
                         round_trip_cost_points=0, target_points=20, stop_points=20)
            for p in ("conservative", "favorable")]
    bound = event_bounds(*pair)
    assert bound["retracement_certain"] == bound["retracement_possible"] == 1
    checks.append("Known retracement maps to fade target in both policies")
    bars[1] = [1040., 1065., 1015., 1040.]
    pair = [simulate_day(bars, mode="touch", trigger=40, horizon=60, policy=p,
                         round_trip_cost_points=0, target_points=20, stop_points=20)
            for p in ("conservative", "favorable")]
    bound = event_bounds(*pair)
    assert bound["continuation_certain"] == 0 and bound["continuation_possible"] == 1
    checks.append("Same-minute collision yields continuation interval zero to one")
    bars[1:] = [1040., 1045., 1035., 1040.]
    pair = [simulate_day(bars, mode="touch", trigger=40, horizon=60, policy=p,
                         round_trip_cost_points=0, target_points=20, stop_points=20)
            for p in ("conservative", "favorable")]
    bound = event_bounds(*pair)
    assert bound["neither_certain"] == 1 and bound["continuation_possible"] == 0
    checks.append("Time unresolved event remains in denominator")
    bars = flat(); bars[0] = [1000., 1041., 959., 1000.]
    pair = [simulate_day(bars, mode="touch", trigger=40, horizon=60, policy=p,
                         round_trip_cost_points=0, target_points=40, stop_points=40)
            for p in ("conservative", "favorable")]
    bound = event_bounds(*pair)
    assert all(result["direction_ambiguous"] for result in pair)
    assert bound["retracement_certain"] == 1 and bound["outcome_ambiguous"] == 0
    checks.append("Ambiguous initial direction can retain a certain pooled category")
    return checks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--synthetic-only", action="store_true")
    parser.add_argument("--protocol-sha256", help="Required matching coordinator-frozen protocol hash for historical run")
    args = parser.parse_args()
    sys.path.insert(0, str(HERE))
    from replay import simulate_day
    checks = synthetic_mapping_checks(simulate_day)
    if args.synthetic_only:
        print(json.dumps({"synthetic_mapping_checks": checks, "passed": len(checks)}))
        return
    protocol_path = HERE / "protocol.json"
    if not protocol_path.exists() or not args.protocol_sha256 or sha(protocol_path) != args.protocol_sha256:
        raise ValueError("Historical outcomes require the matching frozen protocol hash")
    protocol = json.loads(protocol_path.read_text())
    assert protocol["continuation_study"]["thresholds_points"] == list(THRESHOLDS)
    assert protocol["continuation_study"]["horizons_minutes"] == list(HORIZONS)
    sessions, meta, exclusions = load_sessions()
    events = simulate_events(sessions, simulate_day)
    summary, yearly, directions = build_tables(events, sorted(sessions))
    OUT.mkdir(parents=True, exist_ok=True)
    for name, frame in (("continuation_events", events), ("continuation_summary", summary),
                        ("continuation_yearly", yearly), ("continuation_directions", directions)):
        frame.to_csv(OUT / (name + ".csv"), index=False)
    result = {"study": "MNQ first-opening-threshold continuation probabilities",
              "method": {"thresholds_points": THRESHOLDS, "first_touch_cutoff_minutes": 15,
                         "horizons_minutes_after_touch_minute_start": HORIZONS,
                         "primary_barriers": "20 points farther in initial direction versus 20-point retracement",
                         "secondary_barriers": "Another full initial threshold move versus return to cash open",
                         "denominator": "Every first-threshold event; no decisive-outcome conditioning",
                         "continuation_lower": "Favorable-fade policy stop indicator: continuation certain under both endpoint policies",
                         "continuation_upper": "Conservative-fade policy stop indicator: continuation possible under either endpoint policy",
                         "ambiguous_direction": "Included in pooled bounds; excluded from up/down and terminal-direction summaries",
                         "clock": "Touch minute start plus 60/120 minutes; boundary open is read, deadline high/low are not; up to one minute shorter than exact touch time",
                         "bootstrap": {"method": "Whole calendar month cluster percentile bootstrap of event ratios; includes zero-event months",
                                       "draws": BOOTSTRAP_DRAWS, "seed": BOOTSTRAP_SEED, "percentiles": [2.5, 97.5],
                                       "suppress_when": "Fewer than 100 events or 10 occupied event months"},
                         "claim_rule": "Primary balanced-20 only, n >= 100, at least 10 occupied months and certain-continuation 95% lower CI > 50%",
                         "inference_scope": "Pointwise exploratory intervals; no multiplicity adjustment; thresholds share days; no universal optimal level or fresh holdout claim",
                         "terminal_metric": "Deadline opening quote relative to initial threshold in the first-touch direction; not conditioned on barrier outcome"},
              "provenance": {"data_version": meta["data_version"], "data_sha256": meta["sha256"],
                             "data_path": meta["data_path"], "first_session": min(sessions), "last_session": max(sessions),
                             "included_sessions": len(sessions), "excluded_sessions": exclusions,
                             "prior_calendar_sha256": sha(BASE / "cash_calendar.csv"),
                             "protocol_sha256": sha(protocol_path), "source_sha256": sha(__file__),
                             "replay_sha256": sha(HERE / "replay.py"), "protocol": protocol},
              "checks": {"synthetic_mapping_checks": checks,
                         "every_trigger_crosschecked_against_raw_ohlc": True,
                         "every_exit_crosschecked_against_raw_ohlc_and_levels": True,
                         "per_event_and_group_subset_bounds_asserted": True,
                         "all_prior_cash_dates_reconciled": True,
                         "events": len(events)},
              "summary": summary.to_dict("records"),
              "yearly": yearly.to_dict("records"),
              "directions": directions.to_dict("records")}
    (OUT / "continuation_summary.json").write_text(json.dumps(safe(result), indent=2), encoding="utf-8")
    print(json.dumps({"events": len(events), "summary_rows": len(summary), "output": str(OUT)}))


if __name__ == "__main__":
    main()
