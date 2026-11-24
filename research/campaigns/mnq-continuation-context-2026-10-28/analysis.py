"""Frozen, bounded context analysis of preserved continuation event bounds.

No price replay or entry selection occurs here. Preview verifies preserved
sources and the causal feature table before a separately authorized run step.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = ROOT / "reports/mnq-continuation-context-2026-10-28"
EXPECTED_PROTOCOL = "f75660b25d8ae441e42a00e66c10c43514712dd63268e42fff315da9eabaa820"
EXPECTED_EVENTS = "83f4ea0c1d7db8b57610388c89c8312ff16b13e5357bd84c0a7324c171027f78"
EXPECTED_PRIOR_SUMMARY = "9d88245cbc94e1f162b9aabf25b080f04e3fee522a70a10536758a5c630f966d"
EVENT_SOURCE = ROOT / "reports/mnq-open-fade-small-targets-2026-10-28/continuation_events.csv"
PRIOR_SUMMARY = EVENT_SOURCE.with_name("continuation_summary.csv")
SESSION_SOURCE = ROOT / "reports/mnq-ny-open-2026-10-28/opening_sessions.csv"
EVENT_KEY = ["date", "threshold_points", "horizon_minutes", "barrier_definition"]
INDICATORS = ["continuation_certain", "continuation_possible", "retracement_certain",
              "retracement_possible", "neither_certain", "outcome_ambiguous", "direction_ambiguous"]
FAMILY_COLUMNS = {"hit_time": "hit_time_bin", "relative_stretch": "relative_stretch_bin"}
BINS = {"hit_time": ["09:30-09:34", "09:35-09:39", "09:40-09:44"],
        "relative_stretch": ["below_0.75x", "0.75_to_below_1.25x", "at_least_1.25x"]}
PERIODS = {"development": ("2019-05-06", "2023-12-31"),
           "chronological_check": ("2024-01-01", "2026-09-03")}


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


def write_json(path, value):
    Path(path).write_text(json.dumps(safe(value), indent=2, allow_nan=False), encoding="utf-8")


def hit_bucket(index):
    if not isinstance(index, (int, np.integer)) or not 0 <= index <= 14:
        raise ValueError("Hit minute must be an integer in [0, 14]")
    return BINS["hit_time"][index//5]


def relative_bucket(value):
    if pd.isna(value):
        return None
    if not math.isfinite(value) or value < 0:
        raise ValueError("Relative stretch must be finite and nonnegative")
    return BINS["relative_stretch"][0 if value < .75 else 1 if value < 1.25 else 2]


def make_session_context(openings):
    d = openings.loc[openings.window == 15].copy().sort_values("date").reset_index(drop=True)
    if d.date.duplicated().any() or not (d.range_pts > 0).all():
        raise ValueError("Need unique, positive-range cash sessions")
    d["prior20_median_range_pts"] = d.range_pts.rolling(20, min_periods=20).median().shift(1)
    d["reference_first_date"] = d.date.shift(20)
    d["reference_last_date"] = d.date.shift(1).where(d.prior20_median_range_pts.notna())
    d["reference_session_count"] = np.where(d.prior20_median_range_pts.notna(), 20, 0)
    d["relative_stretch_available"] = d.prior20_median_range_pts.notna()
    return d


def load_verified(protocol_hash):
    actual_protocol = sha(HERE/"protocol.json")
    if actual_protocol != EXPECTED_PROTOCOL or protocol_hash != actual_protocol:
        raise ValueError("Frozen protocol hash mismatch")
    protocol = json.loads((HERE/"protocol.json").read_text())
    assert protocol["periods"] == {k: list(v) for k, v in PERIODS.items()}
    assert sha(EVENT_SOURCE) == EXPECTED_EVENTS
    assert sha(PRIOR_SUMMARY) == EXPECTED_PRIOR_SUMMARY
    manifest_path = SESSION_SOURCE.with_name("evidence_manifest.json")
    manifest = json.loads(manifest_path.read_text())
    expected_session = next(x["sha256"] for x in manifest["files"] if x["name"] == SESSION_SOURCE.name)
    assert sha(SESSION_SOURCE) == expected_session
    source_hashes = {str(p.relative_to(ROOT)).replace("\\", "/"): sha(p)
                     for p in [EVENT_SOURCE, PRIOR_SUMMARY, SESSION_SOURCE, manifest_path]}
    e = pd.read_csv(EVENT_SOURCE)
    assert not e.duplicated(EVENT_KEY).any()
    e = e[e.threshold_points.isin([40, 60, 80])].copy()
    assert set(e.horizon_minutes) == {60, 120}
    assert set(e.barrier_definition) == {"balanced_20", "balanced_initial_move"}
    for column in INDICATORS:
        assert e[column].isin([0, 1, False, True]).all()
        e[column] = e[column].astype(int)
    assert (e.continuation_certain <= e.continuation_possible).all()
    assert (e.retracement_certain <= e.retracement_possible).all()
    assert (e.continuation_certain+e.retracement_certain+e.neither_certain+e.outcome_ambiguous == 1).all()
    openings = pd.read_csv(SESSION_SOURCE)
    s = make_session_context(openings)
    assert len(s) == 1841 and s.relative_stretch_available.sum() == 1821
    feature_columns = ["date", "prior20_median_range_pts", "reference_first_date",
                       "reference_last_date", "reference_session_count", "relative_stretch_available"]
    e = e.merge(s[feature_columns], on="date", how="left", validate="many_to_one")
    assert e.relative_stretch_available.notna().all()
    e["relative_stretch"] = e.threshold_points/e.prior20_median_range_pts
    e["hit_time_bin"] = e.touch_minute_index.map(hit_bucket)
    e["relative_stretch_bin"] = e.relative_stretch.map(relative_bucket)
    e = e.sort_values(EVENT_KEY).reset_index(drop=True)
    return protocol, source_hashes, s, e


def verify_prior_aggregates(events):
    prior = pd.read_csv(PRIOR_SUMMARY)
    periods = {"all_2019_2026": ("2019-05-06", "2026-09-03"),
               "development_2019_2023": PERIODS["development"],
               "2024_onward": PERIODS["chronological_check"],
               "2026_only": ("2026-01-01", "2026-09-03")}
    checked = 0
    for _, row in prior[prior.threshold_points.isin([40, 60, 80])].iterrows():
        start, end = periods[row.period]
        g = events[(events.date >= start) & (events.date <= end) &
                   (events.threshold_points == row.threshold_points) &
                   (events.horizon_minutes == row.horizon_minutes) &
                   (events.barrier_definition == row.barrier_definition)]
        assert len(g) == int(row.n)
        for flag in INDICATORS:
            assert int(g[flag].sum()) == int(row[flag+"_n"])
            assert abs(g[flag].mean()*100-row[flag+"_pct"]) < 1e-8
        checked += 1
    assert checked == 48
    return checked


def month_plan(period, draws=20000, seed=20261028):
    start, end = PERIODS[period]
    months = pd.period_range(start[:7], end[:7], freq="M").astype(str).tolist()
    rng = np.random.default_rng(seed)
    weights = rng.multinomial(len(months), np.full(len(months), 1/len(months)), size=draws)
    assert np.all(weights.sum(axis=1) == len(months))
    return {"months": months, "weights": weights.astype(np.int16), "draws": draws, "seed": seed}


def bootstrap_draws(group, plan):
    counts = group.groupby("month").agg(n=("date", "size"), lower=("continuation_certain", "sum"),
                                        upper=("continuation_possible", "sum")).reindex(plan["months"], fill_value=0)
    totals = plan["weights"] @ counts.to_numpy(dtype=float)
    valid = totals[:, 0] > 0
    rates = np.full((len(totals), 2), np.nan)
    rates[valid] = totals[valid, 1:]/totals[valid, 0, None]*100
    return rates, valid


def uncertainty(group, plan, *, primary=False):
    rates, valid = bootstrap_draws(group, plan)
    n, occupied = len(group), int(group.month.nunique())
    failures = []
    if n < 100:
        failures.append("fewer than 100 events")
    if occupied < 12:
        failures.append("fewer than 12 occupied months")
    if valid.mean() < .99:
        failures.append("fewer than 99% nonempty bootstrap draws")
    result = {"occupied_event_months": occupied, "bootstrap_months": len(plan["months"]),
              "bootstrap_draws": len(valid), "bootstrap_valid_draws": int(valid.sum()),
              "bootstrap_empty_draws": int((~valid).sum()),
              "sample_sufficient": n >= 100 and occupied >= 12,
              "intervals_available": not failures, "suppression_reasons": failures,
              "continuation_certain_ci_low_pct": None, "continuation_certain_ci_high_pct": None,
              "continuation_possible_ci_low_pct": None, "continuation_possible_ci_high_pct": None,
              "bonferroni_lower_certain_pct": None}
    if not failures:
        ci = np.quantile(rates[valid], [.025, .975], axis=0)
        result.update(continuation_certain_ci_low_pct=float(ci[0, 0]),
                      continuation_certain_ci_high_pct=float(ci[1, 0]),
                      continuation_possible_ci_low_pct=float(ci[0, 1]),
                      continuation_possible_ci_high_pct=float(ci[1, 1]))
        if primary:
            result["bonferroni_lower_certain_pct"] = float(np.quantile(rates[valid, 0], .05/18))
    return result


def summarize(group, meta, plan, *, primary=False):
    n = len(group)
    row = dict(meta, n=n, primary_cell=bool(primary))
    for flag in INDICATORS:
        row[flag+"_n"] = int(group[flag].sum())
        row[flag+"_pct"] = float(group[flag].mean()*100) if n else None
    row["covariate_available_n"] = int(group.relative_stretch.notna().sum())
    for col in ["relative_stretch", "prior20_median_range_pts"]:
        for stat in ["mean", "median"]:
            vals = group[col].dropna()
            row[col+"_"+stat] = float(getattr(vals, stat)()) if len(vals) else None
    row.update(uncertainty(group, plan, primary=primary))
    lower = row["bonferroni_lower_certain_pct"]
    row["primary_period_majority_pass"] = bool(primary and lower is not None and lower > 50)
    row["primary_two_period_majority_pass"] = False
    row["primary_failure_reasons"] = [] if not primary or row["primary_period_majority_pass"] else (
        row["suppression_reasons"] if not row["intervals_available"] else ["adjusted lower certain-continuation bound does not exceed 50%"])
    return row


def available_events(events, family):
    return events if family == "hit_time" else events[events.relative_stretch_available]


def tables(events, sessions, plans):
    contexts, baselines, contrasts = [], [], []
    partition_checks = 0
    for period, (start, end) in PERIODS.items():
        ep = events[(events.date >= start) & (events.date <= end)]
        cash = sessions[(sessions.date >= start) & (sessions.date <= end)]
        for threshold in [40, 60, 80]:
            for horizon in [60, 120]:
                for barrier in ["balanced_20", "balanced_initial_move"]:
                    group = ep[(ep.threshold_points == threshold) & (ep.horizon_minutes == horizon) &
                               (ep.barrier_definition == barrier)]
                    primary = horizon == 60 and barrier == "balanced_20"
                    for family, column in FAMILY_COLUMNS.items():
                        g = available_events(group, family)
                        meta = {"period": period, "start": start, "end": end,
                                "threshold_points": threshold, "horizon_minutes": horizon,
                                "barrier_definition": barrier, "context_family": family,
                                "cash_sessions": len(cash), "baseline_event_n": len(g),
                                "warmup_events_excluded": len(group)-len(g)}
                        baselines.append(summarize(g, meta, plans[period], primary=False))
                        parts = []
                        for bucket in BINS[family]:
                            sub = g[g[column] == bucket]
                            contexts.append(summarize(sub, dict(meta, context_bin=bucket), plans[period], primary=primary))
                            parts.append(sub)
                        assert sum(len(x) for x in parts) == len(g)
                        for flag in INDICATORS:
                            assert sum(int(x[flag].sum()) for x in parts) == int(g[flag].sum())
                        partition_checks += 1
                        if primary:
                            A, B = (BINS[family][0], BINS[family][2]) if family == "hit_time" else (
                                BINS[family][2], BINS[family][0])
                            ga, gb = g[g[column] == A], g[g[column] == B]
                            ra, va = bootstrap_draws(ga, plans[period])
                            rb, vb = bootstrap_draws(gb, plans[period])
                            valid = va & vb
                            reasons = []
                            for label, sub in [("A", ga), ("B", gb)]:
                                if len(sub) < 100: reasons.append(label+" fewer than 100 events")
                                if sub.month.nunique() < 12: reasons.append(label+" fewer than 12 occupied months")
                            if valid.mean() < .99: reasons.append("fewer than 99% jointly nonempty draws")
                            row = {"period": period, "threshold_points": threshold, "context_family": family,
                                   "A_bin": A, "B_bin": B, "A_n": len(ga), "B_n": len(gb),
                                   "A_occupied_months": int(ga.month.nunique()), "B_occupied_months": int(gb.month.nunique()),
                                   "lower_difference_pp": float(ga.continuation_certain.mean()-gb.continuation_possible.mean())*100 if len(ga) and len(gb) else None,
                                   "upper_difference_pp": float(ga.continuation_possible.mean()-gb.continuation_certain.mean())*100 if len(ga) and len(gb) else None,
                                   "lower_endpoint_ci_low_pp": None, "lower_endpoint_ci_high_pp": None,
                                   "upper_endpoint_ci_low_pp": None, "upper_endpoint_ci_high_pp": None,
                                   "intervals_available": not reasons, "suppression_reasons": reasons,
                                   "bootstrap_valid_draws": int(valid.sum()), "bootstrap_empty_draws": int((~valid).sum())}
                            if not reasons:
                                differences = np.column_stack((ra[valid, 0]-rb[valid, 1], ra[valid, 1]-rb[valid, 0]))
                                ci = np.quantile(differences, [.025, .975], axis=0)
                                row.update(lower_endpoint_ci_low_pp=float(ci[0, 0]), lower_endpoint_ci_high_pp=float(ci[1, 0]),
                                           upper_endpoint_ci_low_pp=float(ci[0, 1]), upper_endpoint_ci_high_pp=float(ci[1, 1]))
                            contrasts.append(row)
    assert len(contexts) == 144 and len(baselines) == 48 and len(contrasts) == 12
    for row in contexts:
        if row["primary_cell"]:
            pair = [x for x in contexts if x["primary_cell"] and
                    all(x[k] == row[k] for k in ["threshold_points", "context_family", "context_bin"])]
            assert len(pair) == 2
            row["primary_two_period_majority_pass"] = all(x["primary_period_majority_pass"] for x in pair)
    yearly = []
    for year, g in sessions.groupby("year"):
        row = {"year": int(year), "n": len(g), "first_date": g.date.min(), "last_date": g.date.max(),
               "range_pts_mean": float(g.range_pts.mean()), "range_pts_median": float(g.range_pts.median()),
               "range_pts_p25": float(g.range_pts.quantile(.25)), "range_pts_p75": float(g.range_pts.quantile(.75)),
               "range_bps_median": float(g.range_bps.median()),
               "prior20_median_range_pts_mean": float(g.prior20_median_range_pts.mean()),
               "prior20_median_range_pts_median": float(g.prior20_median_range_pts.median()),
               "partial_year": int(year) in (2019, 2026)}
        yearly.append(row)
    return contexts, baselines, contrasts, yearly, partition_checks


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--stage", choices=["preview", "run"], required=True)
    ap.add_argument("--protocol-sha256", required=True)
    ap.add_argument("--preview-sha256")
    args = ap.parse_args()
    protocol, sources, sessions, events = load_verified(args.protocol_sha256)
    from check_analysis import run_focused_checks
    checks = run_focused_checks(sessions)
    prior_count = verify_prior_aggregates(events)
    OUT.mkdir(parents=True, exist_ok=True)
    preview = {"study_id": protocol["study_id"], "protocol_sha256": EXPECTED_PROTOCOL,
               "source_checksums": sources, "script_sha256": sha(__file__),
               "cash_sessions": len(sessions), "event_rows": len(events),
               "warmup_session_count": int((~sessions.relative_stretch_available).sum()),
               "warmup_dates": sessions.loc[~sessions.relative_stretch_available, "date"].tolist(),
               "first_available_reference_date": sessions.loc[sessions.relative_stretch_available, "date"].iloc[0],
               "context_rows_expected": 144, "baseline_rows_expected": 48, "contrast_rows_expected": 12,
               "shared_bootstrap_draws_per_period": 20000, "seed": 20261028,
               "prior_aggregate_rows_reconciled": prior_count, "focused_checks": checks,
               "price_replays": 0, "new_entry_thresholds": []}
    if args.stage == "preview":
        write_json(OUT/"preview.json", preview)
        print(json.dumps({"preview_sha256": sha(OUT/"preview.json"), **preview}, indent=2))
        return
    if not args.preview_sha256 or sha(OUT/"preview.json") != args.preview_sha256:
        raise ValueError("Run requires the inspected preview SHA-256")
    if json.loads((OUT/"preview.json").read_text()) != safe(preview):
        raise ValueError("Sources or implementation changed after preview; regenerate preview")
    plans = {period: month_plan(period) for period in PERIODS}
    contexts, baselines, contrasts, yearly, partition_checks = tables(events, sessions, plans)
    verification = {"status": "passed", "protocol_sha256_verified": True,
                    "source_checksums_verified": True, "prior_aggregate_rows_reconciled": prior_count,
                    "unique_enriched_events": len(events), "all_outcome_partition_identities": True,
                    "context_partition_checks": partition_checks, "context_summary_rows": len(contexts),
                    "baseline_summary_rows": len(baselines), "fixed_contrast_rows": len(contrasts),
                    "warmup_session_count": 20, "focused_checks": checks,
                    "shared_month_weights_with_zero_event_months": True,
                    "old_sources_unchanged": all(sha(ROOT/path) == digest for path, digest in sources.items())}
    assert verification["old_sources_unchanged"]
    data_tables = {"context_summary": contexts, "baseline_summary": baselines,
                   "fixed_contrasts": contrasts, "yearly_ranges": yearly}
    for name, rows in data_tables.items():
        pd.DataFrame(rows).to_csv(OUT/(name+".csv"), index=False)
    events.to_csv(OUT/"enriched_events.csv", index=False)
    sessions.to_csv(OUT/"session_context.csv", index=False)
    write_json(OUT/"verification.json", verification)
    np.savez_compressed(OUT/"bootstrap_weights.npz", **{period: plan["weights"] for period, plan in plans.items()})
    primary = [r for r in contexts if r["primary_cell"]]
    supported = [{k: r[k] for k in ["threshold_points", "context_family", "context_bin"]}
                 for r in primary if r["period"] == "development" and r["primary_two_period_majority_pass"]]
    findings = {"supported_primary_contexts": supported, "supported_primary_context_count": len(supported),
                "primary_period_cells": len(primary),
                "primary_period_cells_with_intervals": sum(r["intervals_available"] for r in primary),
                "primary_period_cells_passing_adjusted_bound": sum(r["primary_period_majority_pass"] for r in primary),
                "contrast_rows_with_intervals": sum(r["intervals_available"] for r in contrasts),
                "strategy_selection_or_promotion": False,
                "causal_effect_claim": False}
    summary = {"study_id": protocol["study_id"], "protocol": protocol, "lineage": preview,
               "findings": findings, "verification": verification, **data_tables,
               "bootstrap": {p: {"months": x["months"], "draws": x["draws"], "seed": x["seed"]}
                             for p, x in plans.items()}}
    write_json(OUT/"summary.json", summary)
    write_json(OUT/"protocol.json", protocol)
    print(json.dumps(findings, indent=2))
    print(pd.DataFrame(primary)[["period", "threshold_points", "context_family", "context_bin", "n",
                               "continuation_certain_pct", "continuation_possible_pct", "outcome_ambiguous_pct",
                               "bonferroni_lower_certain_pct", "primary_two_period_majority_pass"]].to_string(index=False))


if __name__ == "__main__":
    main()
