"""Pure, auditable analysis primitives for the declared SND combination search.

The runner owns protocol/input verification and fold replay. These functions never
select from a later evaluation period or silently turn reused history into a
holdout. An exit ledger may identify a censored open trade, but its later exit
price, P&L, cost and outcome must not affect reconstructed training performance.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
import argparse
import hashlib
import json
import math
import os
from pathlib import Path

import numpy as np
import pandas as pd


FORCED_CLOSE_REASONS = frozenset(("contract-roll", "end-of-test", "training-cutoff"))
ENTRY_FIELDS = frozenset((
    "entry_time", "side", "quantity", "entry", "stop", "target", "risk", "risk_cash",
    "zone_time", "zone_top", "zone_bottom", "ambiguous_entry", "execution_minutes",
    "first_touch_time", "signal_time", "entry_reference", "opposing_boundary",
    "opposing_room_r", "initial_risk", "initial_risk_cash", "target_requested_rr",
    "target_effective_rr", "order_expiry_time", "eligibility_policy", "lifetime_bars",
    "entry_price_before_slippage", "prior_atr20", "prior_volume20", "zone_width_atr",
    "departure_atr", "departure_rvol", "signal_age_hours", "boundary_model",
    "zone_boundary", "entry_bar_target_ignored",
))


def utc(value):
    timestamp = pd.Timestamp(value)
    return timestamp.tz_localize("UTC") if timestamp.tzinfo is None else timestamp.tz_convert("UTC")


def _finite(value):
    try:
        return value is not None and math.isfinite(float(value))
    except (ValueError, TypeError):
        return False


def effective_exit_times(trades, execution_minutes=1):
    """Ledger bar-end times; a backdated roll additionally needs discovery proof.

    Ordinary source-open exits require their bar close. Contract-roll timestamps
    are the prior close, not the later source candle that reveals the transition;
    causal_training_trades separately censors an undiscovered terminal roll.
    """
    times = pd.to_datetime(trades["exit_time"], utc=True)
    forced = trades["exit_reason"].isin(FORCED_CLOSE_REASONS)
    resolution = (pd.to_numeric(trades["execution_minutes"])
                  if "execution_minutes" in trades else execution_minutes)
    return times + pd.to_timedelta(np.where(forced, 0, resolution), unit="min")


def exit_cohort_times(trades):
    """Forced closes at a boundary belong to the interval just completed."""
    times = pd.to_datetime(trades["exit_time"], utc=True)
    forced = trades["exit_reason"].isin(FORCED_CLOSE_REASONS)
    return times - pd.to_timedelta(forced.astype(int), unit="ns")


def causal_training_trades(
    full_trades, start, cutoff, *, last_source_open, last_source_close,
    point_value, tick_size, fee, slippage_ticks=1, execution_minutes=1,
    slippage_model="cash",
):
    """Reconstruct the exact flat-ended training prefix from a causal full ledger.

    The caller must independently load the last complete raw source candle and
    prove prefix parity against the reference engine with identical scored start,
    prepared-history conventions, and warmup. This method assumes one position at
    a time, fixed one-contract economics and immutable entry risk.

    `last_source_open` is its opening timestamp; `last_source_close` is its price.
    No unfinished source candle, future close price or future exit cost is used.
    """
    lo, hi = utc(start), utc(cutoff)
    if hi <= lo or execution_minutes <= 0:
        raise ValueError("Require positive interval and source resolution")
    if slippage_model not in ("cash", "price"):
        raise ValueError("Unknown slippage model")
    if point_value <= 0 or tick_size <= 0 or fee < 0 or slippage_ticks < 0:
        raise ValueError("Invalid contract economics")
    t = full_trades.copy()
    required = {"entry_time", "exit_time", "exit_reason", "side", "entry", "risk_cash"}
    if not required.issubset(t.columns):
        raise ValueError("Ledger lacks required entry/exit fields")
    if t.empty:
        return t
    entry_times = pd.to_datetime(t["entry_time"], utc=True)
    source_open = utc(last_source_open)
    source_end = source_open + pd.Timedelta(minutes=execution_minutes)
    if source_open < lo or source_end > hi or not _finite(last_source_close):
        raise ValueError("Raw liquidation candle must be complete within training")
    # Every observed trade entry must occur in a completed source interval.
    observed_entry = (entry_times >= lo) & (entry_times < hi)
    if (entry_times[observed_entry] > source_open).any():
        raise ValueError("Ledger entry exceeds independently supplied source coverage")
    observed_exit = effective_exit_times(t, execution_minutes) <= hi
    # A roll is discovered at the next contract's source candle but the engine
    # stamps liquidation at the preceding source close. With no later completed
    # candle, its future reason/outcome metadata is not yet observable. There can
    # be no intervening full-ledger source candle between that stamp and the
    # discovering roll candle, so a strictly later independently observed close
    # is sufficient proof. Reconstruct undiscovered rolls like any open position.
    undiscovered_roll = t["exit_reason"].eq("contract-roll") & (pd.to_datetime(t["exit_time"], utc=True) >= source_end)
    observed_exit &= ~undiscovered_roll
    completed = t.loc[observed_entry & observed_exit].copy()
    outstanding = t.loc[observed_entry & ~observed_exit]
    if len(outstanding) > 1:
        raise ValueError("More than one censored open position")
    if outstanding.empty:
        return completed.reset_index(drop=True)
    opened = outstanding.iloc[0]
    side, entry, risk_cash = float(opened.side), float(opened.entry), float(opened.risk_cash)
    if side not in (-1., 1.) or not all(_finite(x) for x in (entry, risk_cash)) or risk_cash <= 0:
        raise ValueError("Invalid known entry state")
    if "quantity" in opened and float(opened.quantity) != side:
        raise ValueError("Only one fixed contract is supported")
    slip_price = slippage_ticks * tick_size if slippage_model == "price" else 0.
    cash_slip = slippage_ticks * tick_size * point_value if slippage_model == "cash" else 0.
    exit_price = float(last_source_close) - side * slip_price
    gross = side * (exit_price - entry) * point_value
    cost = 2. * (fee + cash_slip)
    # Whitelist entry-time fields so future outcome metadata cannot escape.
    replacement = {key: opened[key] for key in sorted(ENTRY_FIELDS) if key in opened.index}
    replacement.update(exit_time=source_end, exit=exit_price, exit_reason="training-cutoff",
                       exit_price_before_slippage=float(last_source_close),
                       gross_pnl=gross, cost=cost, net_pnl=gross - cost,
                       net_r=(gross - cost) / risk_cash, ambiguous_exit=False)
    replacement_frame = pd.DataFrame([replacement])
    return (replacement_frame if completed.empty else
            pd.concat([completed, replacement_frame], ignore_index=True))


def calendar_week_arrays(trades, start, end, *, master_start=None, master_end=None):
    """Sum trade R/count/cost in calendar weeks, retaining empty master weeks.

    Period masks are applied before aggregation. Thus a partial first week does
    not accidentally include earlier trades when using shared master weights.
    """
    lo, hi = utc(start), utc(end)
    master_lo, master_hi = utc(master_start or start), utc(master_end or end)
    if not master_lo <= lo < hi <= master_hi:
        raise ValueError("Period must lie inside a positive master calendar")
    first = (master_lo - pd.Timedelta(days=master_lo.weekday())).normalize()
    weeks = int(((master_hi - pd.Timedelta(nanoseconds=1)) - first).days // 7) + 1
    totals = np.zeros((weeks, 3), dtype=float)
    if not trades.empty:
        times = exit_cohort_times(trades)
        chosen = (times >= lo) & (times < hi)
        cohort = trades.loc[chosen]
        rows = ((times[chosen] - first).dt.total_seconds() // (7 * 86400)).astype(int)
        r = pd.to_numeric(cohort["net_r"]).to_numpy(float)
        if not np.isfinite(r).all():
            raise ValueError("Nonfinite trade R in scored cohort")
        cost_r = (cohort.cost.to_numpy(float) / cohort.risk_cash.to_numpy(float)
                  if {"cost", "risk_cash"}.issubset(cohort.columns) else np.zeros(len(cohort)))
        np.add.at(totals[:, 0], rows, r)
        np.add.at(totals[:, 1], rows, 1.)
        np.add.at(totals[:, 2], rows, cost_r)
    return dict(sum_r=totals[:, 0], counts=totals[:, 1], cost_r=totals[:, 2],
                first_week=first.isoformat())


def weekly_cluster_se(sum_r, counts):
    """SE of trade-weighted mean R, clustering within calendar weeks.

    This ranking approximation treats weeks as independent. It is not the final
    four-week block-bootstrap inference and does not correct model selection.
    """
    sums, n = np.asarray(sum_r, float), np.asarray(counts, float)
    if sums.ndim != 1 or sums.shape != n.shape or not np.isfinite(sums).all() or not np.isfinite(n).all() or (n < 0).any():
        raise ValueError("Invalid weekly sums/counts")
    if len(n) < 2 or n.sum() <= 0 or np.count_nonzero(n) < 2:
        return None
    mean = sums.sum() / n.sum()
    residual = sums - mean * n
    return float(np.sqrt(len(n) / (len(n) - 1) * np.dot(residual, residual)) / n.sum())


def training_metrics(censored_trades, start, cutoff):
    """Summarize already-censored, liquidated training; never pass future trades."""
    lo, hi = utc(start), utc(cutoff)
    if not censored_trades.empty:
        if (pd.to_datetime(censored_trades.entry_time, utc=True) < lo).any() or (effective_exit_times(censored_trades) > hi).any():
            raise ValueError("Training ledger contains out-of-period trade state")
    arrays = calendar_week_arrays(censored_trades, lo, hi)
    n = len(censored_trades)
    recent_start = max(lo, hi - pd.DateOffset(years=1))
    recent = int((exit_cohort_times(censored_trades) >= recent_start).sum()) if n else 0
    total_r = float(censored_trades.net_r.sum()) if n else 0.
    net = float(censored_trades.net_pnl.sum()) if n else 0.
    costs = float(censored_trades.cost.sum()) if n else 0.
    return dict(trades=n, recent_trades=recent, occupied_weeks=int(np.count_nonzero(arrays["counts"])),
                net_r_sum=total_r, mean_net_r=total_r / n if n else None,
                closed_net=net, double_cost_closed_net=net - costs,
                weekly_cluster_se=weekly_cluster_se(arrays["sum_r"], arrays["counts"]),
                cost=costs, start=lo.isoformat(), cutoff=hi.isoformat())


def select_candidate(records, *, min_trades=200, min_recent_trades=50, z=1.645, tie_tolerance=1e-10):
    """Frozen training-only selector; no eligible model means cash.

    Records have config_id, enabled_filters, and training_metrics fields. A
    positive LCB is deliberately NOT a selection gate. The ranking score is not
    an individual or family significance claim.
    """
    if len({r["config_id"] for r in records}) != len(records):
        raise ValueError("Duplicate configuration IDs")
    evaluated, eligible = [], []
    for source in records:
        row = dict(source)
        reasons = []
        if row.get("trades", 0) < min_trades:
            reasons.append("insufficient_training_trades")
        if row.get("recent_trades", 0) < min_recent_trades:
            reasons.append("insufficient_recent_trades")
        if not _finite(row.get("mean_net_r")) or row["mean_net_r"] <= 0:
            reasons.append("nonpositive_mean_net_r")
        if not _finite(row.get("double_cost_closed_net")) or row["double_cost_closed_net"] <= 0:
            reasons.append("nonpositive_double_cost_cash")
        if not _finite(row.get("weekly_cluster_se")) or row["weekly_cluster_se"] < 0:
            reasons.append("unavailable_cluster_se")
        if row.get("status", "succeeded") != "succeeded":
            reasons.append("case_not_succeeded")
        row["selection_score"] = (float(row["mean_net_r"] - z * row["weekly_cluster_se"])
                                  if _finite(row.get("mean_net_r")) and _finite(row.get("weekly_cluster_se")) else None)
        row["eligible"] = not reasons
        row["ineligibility_reasons"] = reasons
        evaluated.append(row)
        if row["eligible"]:
            eligible.append(row)
    if not eligible:
        return dict(selected_id=None, selected=None, eligible_count=0, decision="cash", records=evaluated)
    top = max(row["selection_score"] for row in eligible)
    tied = [row for row in eligible if row["selection_score"] >= top - tie_tolerance]
    selected = min(tied, key=lambda row: (int(row["enabled_filters"]), str(row["config_id"])))
    return dict(selected_id=selected["config_id"], selected=selected,
                eligible_count=len(eligible), decision="selected", records=evaluated)


def moving_block_weights(weeks, replicates, seed=20260926, block_weeks=4):
    if weeks < 1 or replicates < 2 or block_weeks < 1:
        raise ValueError("Positive weeks/block length and at least two draws required")
    rng = np.random.default_rng(seed)
    length = min(block_weeks, weeks)
    starts = rng.integers(0, weeks - length + 1, size=(replicates, math.ceil(weeks / length)))
    indices = (starts[:, :, None] + np.arange(length)).reshape(replicates, -1)[:, :weeks]
    weights = np.zeros((replicates, weeks), dtype=float)
    np.add.at(weights, (np.repeat(np.arange(replicates), weeks), indices.ravel()), 1.)
    return weights


def family_bootstrap(
    period_matrices: Mapping, comparisons: Sequence, *, replicates=10000,
    seed=20260926, block_weeks=4, confidence=.95, chunk_size=128,
    min_usable=.99, min_jointly_usable=.95, weights=None,
):
    """Chunked simultaneous intervals with one shared calendar resampling law.

    Each period maps to (weekly_sum_r, weekly_counts), two equally shaped
    [master weeks, configurations] matrices. Mask trades to that period BEFORE
    aggregating on the common master calendar. Comparisons contain period,
    candidate column, baseline column (None tests against zero), and an ID.

    Memory scales with draws*weeks and draws*chunk_size, not draws*family_size.
    Degenerate/sparse estimates are unavailable, never zero-width discoveries.
    Intervals only adjust this supplied family; prior adaptive research remains.
    """
    if not period_matrices or not comparisons:
        return dict(records=[], family_size=len(comparisons), calibrated=False,
                    estimable_comparisons=0, critical_value=None)
    if not 0 < confidence < 1 or chunk_size < 1:
        raise ValueError("Invalid confidence or chunk size")
    matrices = {}
    shape = None
    for period, pair in period_matrices.items():
        sums, counts = (np.asarray(a, dtype=float) for a in pair)
        if sums.ndim != 2 or sums.shape != counts.shape or (shape is not None and sums.shape != shape):
            raise ValueError("All periods require the same two-dimensional master calendar")
        if not np.isfinite(sums).all() or not np.isfinite(counts).all() or (counts < 0).any():
            raise ValueError("Nonfinite weekly inputs or negative counts")
        shape = sums.shape
        matrices[period] = (sums, counts)
    if weights is None:
        weights = moving_block_weights(shape[0], replicates, seed, block_weeks)
    else:
        weights = np.asarray(weights, float)
        if weights.shape != (replicates, shape[0]) or not np.isfinite(weights).all() or (weights < 0).any():
            raise ValueError("Invalid supplied shared weights")
    for c in comparisons:
        if c["period"] not in matrices or not 0 <= c["candidate"] < shape[1] or (c.get("baseline") is not None and not 0 <= c["baseline"] < shape[1]):
            raise ValueError("Comparison refers to unavailable period/configuration")

    def draw_chunk(indices):
        result = np.full((replicates, len(indices)), np.nan)
        observed = np.full(len(indices), np.nan)
        for period, (sums, counts) in matrices.items():
            positions = [j for j, ix in enumerate(indices) if comparisons[ix]["period"] == period]
            if not positions:
                continue
            columns = sorted({col for j in positions for col in
                              (comparisons[indices[j]]["candidate"], comparisons[indices[j]].get("baseline"))
                              if col is not None})
            column_map = {col: j for j, col in enumerate(columns)}
            den = weights @ counts[:, columns]
            means = np.divide(weights @ sums[:, columns], den,
                              out=np.full_like(den, np.nan), where=den > 0)
            total = counts[:, columns].sum(axis=0)
            centers = np.divide(sums[:, columns].sum(axis=0), total,
                                out=np.full(len(columns), np.nan), where=total > 0)
            for j in positions:
                c = comparisons[indices[j]]
                a, b = column_map[c["candidate"]], c.get("baseline")
                result[:, j] = means[:, a] - (means[:, column_map[b]] if b is not None else 0.)
                observed[j] = centers[a] - (centers[column_map[b]] if b is not None else 0.)
        return result, observed

    family = len(comparisons)
    centers, errors = np.full(family, np.nan), np.full(family, np.nan)
    usable_counts = np.zeros(family, dtype=int)
    valid = np.zeros(family, dtype=bool)
    jointly_finite = np.ones(replicates, dtype=bool)
    for first in range(0, family, chunk_size):
        indices = list(range(first, min(first + chunk_size, family)))
        draw, center = draw_chunk(indices)
        finite = np.isfinite(draw)
        usable = finite.sum(axis=0)
        # Calculate sample variances without all-NaN warnings.
        sums = np.where(finite, draw, 0.).sum(axis=0)
        means = np.divide(sums, usable, out=np.zeros(len(indices)), where=usable > 0)
        squared = np.where(finite, (draw - means) ** 2, 0.).sum(axis=0)
        variance = np.divide(squared, usable - 1, out=np.full(len(indices), np.nan), where=usable > 1)
        sd = np.sqrt(variance)
        good = np.isfinite(center) & np.isfinite(sd) & (sd > 1e-12) & (usable / replicates >= min_usable)
        centers[indices], errors[indices], usable_counts[indices], valid[indices] = center, sd, usable, good
        jointly_finite &= finite[:, good].all(axis=1)
    calibrated = bool(valid.any() and jointly_finite.mean() >= min_jointly_usable)
    critical = None
    if calibrated:
        maxima = np.zeros(replicates)
        valid_indices = np.flatnonzero(valid).tolist()
        for first in range(0, len(valid_indices), chunk_size):
            indices = valid_indices[first:first + chunk_size]
            draw, _ = draw_chunk(indices)
            statistic = np.abs((draw - centers[indices]) / errors[indices])
            # Invalid draws are discarded globally after all family members.
            maxima = np.maximum(maxima, np.max(np.where(np.isfinite(statistic), statistic, 0.), axis=1))
        critical = float(np.quantile(maxima[jointly_finite], confidence))
    rows = []
    for j, c in enumerate(comparisons):
        estimable = bool(valid[j] and calibrated)
        rows.append(dict(**c, estimate=float(centers[j]) if np.isfinite(centers[j]) else None,
                         standard_error=float(errors[j]) if estimable else None,
                         ci_low=float(centers[j] - critical * errors[j]) if estimable else None,
                         ci_high=float(centers[j] + critical * errors[j]) if estimable else None,
                         usable_bootstraps=int(usable_counts[j]), estimable=estimable))
    return dict(records=rows, family_size=family, calibrated=calibrated,
                estimable_comparisons=sum(row["estimable"] for row in rows),
                individually_usable_comparisons=int(valid.sum()), jointly_usable=int(jointly_finite.sum()),
                jointly_discarded_fraction=float(1 - jointly_finite.mean()),
                critical_value=critical, confidence=confidence, replicates=replicates,
                seed=seed, block_weeks=block_weeks, chunk_size=chunk_size)


def fold_gates(
    folds, *, min_total_trades=200, min_trades_by_fold=None,
    require_each_fold_positive=False, ci_low=None, stress_results=(),
    required_stresses=("price_2ticks",),
):
    """Explicit retrospective gates; never select a replacement after failure.

    Fold rows need name,trades,net_r_sum,closed_net,double_cost_closed_net.
    Stress rows need name,mean_net_r,closed_net,status. Require all specified
    stresses to exist; absent output is not a pass. No risk-sizing parity claim.
    """
    names = [row["name"] for row in folds]
    if len(set(names)) != len(names):
        raise ValueError("Duplicate fold names")
    minimums = min_trades_by_fold or {}
    n = sum(row["trades"] for row in folds)
    total_r = sum(row["net_r_sum"] for row in folds)
    net = sum(row["closed_net"] for row in folds)
    doubled = sum(row["double_cost_closed_net"] for row in folds)
    stresses = {row["name"]: row for row in stress_results}
    gates = dict(
        all_requested_folds_present=all(name in names for name in minimums),
        sufficient_total_trades=n >= min_total_trades,
        sufficient_fold_trades=all(next((r["trades"] for r in folds if r["name"] == name), -1) >= threshold
                                   for name, threshold in minimums.items()),
        positive_mean_net_r=bool(n > 0 and _finite(total_r) and total_r > 0),
        positive_net_cash=bool(_finite(net) and net > 0),
        positive_double_cost_cash=bool(_finite(doubled) and doubled > 0),
        simultaneous_interval_positive=bool(_finite(ci_low) and ci_low > 0),
        each_fold_positive=bool(not require_each_fold_positive or
                                all(r["net_r_sum"] > 0 and r["double_cost_closed_net"] > 0 for r in folds)),
    )
    for name in required_stresses:
        stress = stresses.get(name, {})
        gates["stress_" + name] = bool(stress.get("status") == "succeeded" and
            _finite(stress.get("mean_net_r")) and stress["mean_net_r"] > 0 and
            _finite(stress.get("closed_net")) and stress["closed_net"] > 0)
    return dict(passed=all(gates.values()), gates=gates, trades=n,
                mean_net_r=total_r / n if n else None, closed_net=net,
                double_cost_closed_net=doubled,
                evidence_label="retrospective_candidate" if all(gates.values()) else "not_confirmed")


def protocol_validation_gates(protocol, scenario_folds, *, conditional_mean_r_ci_low, neighbor_folds):
    """Exact frozen economic gates, separately from implementation/risk audits.

    scenario_folds maps the four scenario IDs to complete fold rows. Neighbor
    paths map neighbor-0..5 to baseline-cost fold rows. A row has fold_id, status,
    trades, net_r_sum, closed_net. Cash is a valid terminal replay with zero
    economics. The interval is conditional on the selected path, not a family
    selection correction. No per-fold mean-R or doubled-cost gate is invented.
    """
    fold_ids = [fold["id"] for fold in protocol["folds"]]
    scenario_ids = [scenario["id"] for scenario in protocol["validation_scenarios"]]
    neighbor_ids = [f"neighbor-{i}" for i in range(len(protocol["validation_neighbors"]))]

    def complete(rows):
        ids = [row["fold_id"] for row in rows]
        return (len(ids) == len(set(ids)) and set(ids) == set(fold_ids) and
                all(row.get("status") in ("succeeded", "cash") for row in rows))

    def total(rows, field):
        values = [row.get(field) for row in rows]
        return sum(values) if all(_finite(value) for value in values) else None

    base = scenario_folds.get("cash_base", [])
    base_complete = complete(base)
    count, r_sum = total(base, "trades"), total(base, "net_r_sum")
    minima = {fold_id: (25 if fold_id == "2026_jan_jul" else 50) for fold_id in fold_ids}
    base_by_id = {row["fold_id"]: row for row in base}
    scenario_nets = {name: total(scenario_folds.get(name, []), "closed_net") for name in scenario_ids}
    positive_neighbors = [name for name in neighbor_ids if complete(neighbor_folds.get(name, []))
                          and _finite(total(neighbor_folds[name], "closed_net"))
                          and total(neighbor_folds[name], "closed_net") > 0]
    gates = dict(
        all_scenario_folds_present=all(complete(scenario_folds.get(name, [])) for name in scenario_ids),
        sufficient_pooled_trades=bool(base_complete and _finite(count) and count >= 200),
        sufficient_each_fold_trades=bool(base_complete and all(base_by_id[name]["trades"] >= minimum
                                           for name, minimum in minima.items())),
        pooled_baseline_mean_net_r_positive=bool(base_complete and _finite(count) and count > 0 and _finite(r_sum) and r_sum > 0),
        pooled_net_positive_all_four_scenarios=all(_finite(value) and value > 0 for value in scenario_nets.values()),
        baseline_cash_positive_each_fold=bool(base_complete and all(_finite(row.get("closed_net")) and row["closed_net"] > 0 for row in base)),
        conditional_mean_r_interval_positive=bool(_finite(conditional_mean_r_ci_low) and conditional_mean_r_ci_low > 0),
        five_of_six_neighbor_paths_cash_positive=bool(len(neighbor_ids) == 6 and len(positive_neighbors) >= 5),
    )
    passed = all(gates.values())
    return dict(passed=passed, gates=gates, pooled_baseline_trades=count,
                pooled_baseline_mean_net_r=r_sum / count if _finite(count) and count > 0 and _finite(r_sum) else None,
                scenario_pooled_net=scenario_nets, positive_neighbor_paths=positive_neighbors,
                conditional_mean_r_ci_low=conditional_mean_r_ci_low,
                evidence_label="retrospective_economic_candidate" if passed else "not_confirmed",
                note="Conditional selected-path interval; full-family screening is separate. Implementation and stateful risk audits are still required for any feasible-candidate claim.")


def checksum(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1048576), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _json_clean(value):
    if isinstance(value, Mapping):
        return {str(key): _json_clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_clean(item) for item in value]
    if isinstance(value, np.generic):
        return _json_clean(value.item())
    if isinstance(value, float) and not np.isfinite(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return value


def save_json(path, payload, *, immutable=False):
    path = Path(path)
    payload = _json_clean(payload)
    if path.exists() and immutable:
        if read_json(path) != payload:
            raise ValueError("Preserved analysis differs; use a separate output path: " + str(path))
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp-" + str(os.getpid()))
    temporary.write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


SHARD_ARTIFACTS = ("cases.json", "trades.parquet", "equity-daily.parquet",
                   "periods.parquet", "training.parquet", "weekly.parquet")
QUALITY_FILTERS = ("max_zone_width_atr", "min_departure_atr",
                   "min_departure_rvol", "max_touch_age_hours")


def verify_campaign(output, *, require_complete=True):
    """Verify preserved identities/artifact bytes and exact market/grid coverage.

    This is a manifest and grid-completeness check. Independent engine, prefix,
    fill and accounting audits remain separately required by the protocol.
    """
    output = Path(output).resolve()
    protocol = read_json(output / "protocol.json")
    configs = read_json(output / protocol.get("configurations_file", "configurations.json"))
    manifest = read_json(output / "source-manifest.json")
    protocol_hash, config_hash = checksum(output / "protocol.json"), checksum(output / "configurations.json")
    if protocol_hash != manifest["protocol_checksum"] or config_hash != manifest["configurations_checksum"] or config_hash != protocol["configurations_checksum"]:
        raise ValueError("Frozen protocol/configuration identity mismatch")
    digest = hashlib.sha256(json.dumps(manifest["files"], sort_keys=True).encode()).hexdigest()
    if digest != manifest["source_hash"]:
        raise ValueError("Source manifest identity mismatch")
    _verify_analysis_identity({"manifest": manifest})
    for source in manifest["files"]:
        if checksum(output / "source" / source["path"]) != source["checksum"]:
            raise ValueError("Frozen source changed: " + source["path"])
    ids = [row["config_id"] for row in configs]
    if len(set(ids)) != len(ids) or len(ids) != protocol["expected_configurations"]:
        raise ValueError("Configuration universe is missing or duplicated")
    markets = protocol["markets"]
    if len(set(markets)) != len(markets) or len(ids) * len(markets) != protocol["expected_market_cases"]:
        raise ValueError("Declared market/grid count mismatch")
    expected = {(market, config_id) for market in markets for config_id in ids}
    seen, shards, cases, unfinished = set(), [], [], []
    for market in markets:
        for shard in sorted((output / "sweep" / market).glob("shard-*")):
            # Preserve every attempt; never quietly choose a retry after selection.
            attempts = sorted(shard.glob("attempt-*"))
            successes = []
            for attempt in attempts:
                if not (attempt / "result.json").exists():
                    unfinished.append(dict(path=str(attempt.relative_to(output)), status="unfinished"))
                    continue
                result = read_json(attempt / "result.json")
                if result.get("status") != "succeeded":
                    prior_cases = read_json(attempt / "cases.json") if (attempt / "cases.json").exists() else []
                    unfinished.append(dict(path=str(attempt.relative_to(output)), status=result.get("status", "unknown"),
                        declared_config_ids=result.get("config_ids", []),
                        case_status_counts={state: sum(row.get("status") == state for row in prior_cases)
                                            for state in ("succeeded", "failed")},
                        artifact_verification="Not used for primary grid coverage; preserved attempt remains visible"))
                    continue
                successes.append((attempt, result))
            if len(successes) > 1:
                raise ValueError("Ambiguous multiple successful attempts: " + str(shard))
            if not successes:
                continue
            attempt, result = successes[0]
            if attempt != attempts[-1]:
                raise ValueError("Newer unresolved attempt follows a successful shard: " + str(shard))
            inp, status = read_json(attempt / "input.json"), read_json(attempt / "status.json")
            if status.get("status") != "succeeded":
                raise ValueError("Shard result/status disagree: " + str(attempt))
            for payload in (inp, result):
                if payload.get("protocol_checksum") != protocol_hash or payload.get("source_hash") != manifest["source_hash"]:
                    raise ValueError("Shard identity mismatch: " + str(attempt))
            input_market = inp.get("symbol", inp.get("dataset", {}).get("symbol", market))
            if input_market != market:
                raise ValueError("Shard market mismatch")
            artifacts = {item["name"]: item["checksum"] for item in result.get("artifacts", [])}
            if not set(SHARD_ARTIFACTS).issubset(artifacts):
                raise ValueError("Shard artifact manifest incomplete: " + str(attempt))
            for name in SHARD_ARTIFACTS:
                if checksum(attempt / name) != artifacts[name]:
                    raise ValueError("Shard artifact changed: " + str(attempt / name))
            shard_cases = read_json(attempt / "cases.json")
            if not isinstance(shard_cases, list):
                raise ValueError("cases.json must contain a case list")
            shard_ids = [row["config_id"] for row in shard_cases]
            declared_ids = inp.get("config_ids")
            if declared_ids is not None and set(declared_ids) != set(shard_ids):
                raise ValueError("Shard input/case configuration mismatch")
            if "config_ids" in result and set(result["config_ids"]) != set(shard_ids):
                raise ValueError("Shard result/case configuration mismatch")
            for row in shard_cases:
                key = (market, row["config_id"])
                if key not in expected or key in seen:
                    raise ValueError("Unknown or duplicate grid case: " + str(key))
                seen.add(key)
                cases.append(dict(row, symbol=market))
            shards.append(dict(symbol=market, path=attempt, config_ids=shard_ids,
                               result_checksum=checksum(attempt / "result.json")))
    failed = [row for row in cases if row.get("status") != "succeeded"]
    missing = sorted(expected - seen)
    complete = not missing and not failed and len(seen) == len(expected)
    # Older interrupted/failed attempts are preserved but a verified successful
    # retry resolves their grid cells; an unresolved attempt never does.
    coverage = dict(complete=complete, expected=len(expected), accounted=len(seen),
                    succeeded=len(cases) - len(failed), failed=len(failed), missing=len(missing),
                    missing_ids=[dict(symbol=symbol, config_id=config_id) for symbol, config_id in missing],
                    other_attempts=unfinished, verified_shards=len(shards),
                    protocol_checksum=protocol_hash, source_hash=manifest["source_hash"],
                    configurations_checksum=config_hash,
                    analysis_source_checksum=checksum(__file__),
                    historical_failed_attempts=sum(row["status"] == "failed" for row in unfinished),
                    historical_failed_case_attempts=sum(row.get("case_status_counts", {}).get("failed", 0) for row in unfinished),
                    scope="Artifact identity and exact grid coverage; separate mechanical audits remain required")
    if require_complete and not complete:
        raise ValueError(f"Grid incomplete: {len(missing)} missing and {len(failed)} failed cases; selection unavailable")
    return dict(output=output, protocol=protocol, configs=configs, manifest=manifest,
                shards=shards, cases=cases, coverage=coverage)


def write_progress_report(campaign):
    _verify_analysis_identity(campaign)
    output, p = campaign["output"], campaign["protocol"]
    coverage = campaign["coverage"]
    save_json(output / "grid-coverage.json", coverage)
    lines = ["# Declared combination grid: execution progress", "",
             f"{coverage['accounted']:,} of {coverage['expected']:,} grid cases accounted for; "
             f"{coverage['succeeded']:,} succeeded, {coverage['failed']:,} failed, {coverage['missing']:,} missing.", "",
             f"Preserved earlier failed attempts: {coverage['historical_failed_attempts']:,}, containing {coverage['historical_failed_case_attempts']:,} failed case attempts. Details remain in grid-coverage.json.", "",
             "This report verifies successful shard artifact identities and grid coverage. Engine audits, chronological selection, execution stresses and economic validation are separate requirements.", "",
             "| Market | Recorded | Succeeded | Failed | Zero-trade successes |",
             "| --- | --- | --- | --- | --- |"]
    for market in p["markets"]:
        rows = [row for row in campaign["cases"] if row["symbol"] == market]
        succeeded = [row for row in rows if row.get("status") == "succeeded"]
        zero = sum(row.get("summary", {}).get("trades") == 0 for row in succeeded)
        lines.append(f"| {market} | {len(rows):,} | {len(succeeded):,} | {len(rows)-len(succeeded):,} | {zero:,} |")
    lines += ["", "The finite grid and prior research exposure are recorded in [protocol.json](protocol.json). All dates are retrospective; completion of these simulations does not establish future profitability.", ""]
    (output / "GRID-PROGRESS.md").write_text("\n".join(lines), encoding="utf-8")


def write_selections(campaign):
    if not campaign["coverage"]["complete"]:
        raise ValueError("Complete verified grid required before selection")
    _verify_analysis_identity(campaign)
    p, configs = campaign["protocol"], campaign["configs"]
    by_id = {row["config_id"]: row for row in configs}
    expected_folds = {row["id"]: row for row in p["folds"]}
    gathered = {market: [] for market in p["markets"]}
    for shard in campaign["shards"]:
        frame = pd.read_parquet(shard["path"] / "training.parquet")
        required = {"config_id", "fold_id", "trades", "recent_trades", "mean_net_r",
                    "double_cost_closed_net", "weekly_cluster_se", "enabled_filters", "cutoff"}
        if not required.issubset(frame.columns):
            raise ValueError("Training artifact lacks selection fields")
        expected = {(config_id, fold_id) for config_id in shard["config_ids"] for fold_id in expected_folds}
        found = list(zip(frame.config_id, frame.fold_id))
        if len(found) != len(set(found)) or set(found) != expected:
            raise ValueError("Training artifact is missing, duplicate, or outside declared cases/folds")
        for row in frame.to_dict("records"):
            fold = expected_folds[row["fold_id"]]
            if utc(row["cutoff"]) != utc(fold["cutoff"]) or ("start" in row and utc(row["start"]) != utc(fold["training_start"])):
                raise ValueError("Training prefix boundary mismatch")
            activated = sum(by_id[row["config_id"]]["parameters"].get(key) is not None for key in QUALITY_FILTERS)
            if int(row["enabled_filters"]) != activated:
                raise ValueError("Training simplicity tie-break differs from declared quality filters")
        gathered[shard["symbol"]].extend(frame.to_dict("records"))
    selections, decisions = [], []
    for market in p["markets"]:
        for fold in p["folds"]:
            rows = [row for row in gathered[market] if row["fold_id"] == fold["id"]]
            if len(rows) != len(configs):
                raise ValueError("Incomplete training family")
            choice = select_candidate(rows, min_trades=200, min_recent_trades=50, z=1.645)
            decisions.extend(dict(row, symbol=market) for row in choice.pop("records"))
            selected_id = choice["selected_id"]
            selections.append(dict(symbol=market, fold_id=fold["id"], **fold, **choice,
                parameters=by_id[selected_id]["parameters"] if selected_id is not None else None,
                parameter_hash=by_id[selected_id].get("parameter_hash") if selected_id is not None else None))
    payload = dict(protocol_checksum=campaign["coverage"]["protocol_checksum"],
        source_hash=campaign["coverage"]["source_hash"],
        configurations_checksum=campaign["coverage"]["configurations_checksum"],
        analysis_source_checksum=checksum(__file__),
        training_only=True, complete_grid_verified=True,
        audit_counts={key: campaign["coverage"][key] for key in
                      ("expected", "accounted", "succeeded", "failed", "missing", "verified_shards",
                       "historical_failed_attempts", "historical_failed_case_attempts", "other_attempts")},
        note="Retrospective frozen training selection. Later evaluation is not used in ranking; no cash decision is replaced by a later winner.",
        selections=selections)
    _verify_analysis_identity(campaign)
    save_json(campaign["output"] / "selection.json", payload, immutable=True)
    pd.DataFrame(decisions).to_parquet(campaign["output"] / "selection-training-scores.parquet", index=False)
    return payload


def write_family_analysis(campaign, *, replicates=2000, chunk_size=128):
    if not campaign["coverage"]["complete"]:
        raise ValueError("Complete verified grid required before family inference")
    _verify_analysis_identity(campaign)
    if replicates < 2000:
        raise ValueError("At least 2000 resamples required for the declared family screen")
    p, configs = campaign["protocol"], campaign["configs"]
    datasets = {row["symbol"]: row for row in p["datasets"]}
    bounds = {(datasets[market]["start"], datasets[market]["end"]) for market in p["markets"]}
    if len(bounds) != 1:
        raise ValueError("Shared family calendar requires common dataset score boundaries")
    start, end = next(iter(bounds))
    first = (utc(start) - pd.Timedelta(days=utc(start).weekday())).normalize()
    n_weeks = int(((utc(end) - pd.Timedelta(nanoseconds=1)) - first).days // 7) + 1
    columns = {(market, row["config_id"]): i * len(configs) + j
               for i, market in enumerate(p["markets"]) for j, row in enumerate(configs)}
    matrices = {period: (np.zeros((n_weeks, len(columns))), np.zeros((n_weeks, len(columns))))
                for period in ("all", "later")}
    for shard in campaign["shards"]:
        frame = pd.read_parquet(shard["path"] / "weekly.parquet",
                                columns=["period", "week", "config_id", "net_r_sum", "trades"])
        if set(frame.period) != set(matrices) or set(frame.config_id) != set(shard["config_ids"]):
            raise ValueError("Weekly artifact lacks exact all/later period coverage")
        if frame.duplicated(["period", "week", "config_id"]).any() or len(frame) != 2 * n_weeks * len(shard["config_ids"]):
            raise ValueError("Weekly artifact must retain every empty master-calendar week")
        dates = pd.to_datetime(frame.week, utc=True)
        elapsed = (dates - first).dt.total_seconds().to_numpy()
        week_index = (elapsed // (7 * 86400)).astype(int)
        if (elapsed % (7 * 86400) != 0).any() or (week_index < 0).any() or (week_index >= n_weeks).any():
            raise ValueError("Weekly artifact uses a different master calendar")
        col_index = np.array([columns[shard["symbol"], value] for value in frame.config_id])
        values, counts = frame.net_r_sum.to_numpy(float), frame.trades.to_numpy(float)
        if not np.isfinite(values).all() or not np.isfinite(counts).all() or (counts < 0).any() or (counts % 1 != 0).any() or ((counts == 0) & (values != 0)).any():
            raise ValueError("Invalid weekly sums/counts")
        for period, (sums, n) in matrices.items():
            mask = frame.period.to_numpy() == period
            sums[week_index[mask], col_index[mask]] = values[mask]
            n[week_index[mask], col_index[mask]] = counts[mask]
    comparisons = []
    for period in matrices:
        for market in p["markets"]:
            baseline = columns[market, "c00000"]
            for config in configs:
                candidate = columns[market, config["config_id"]]
                for comparator, reference in (("baseline", baseline), ("zero", None)):
                    comparisons.append(dict(id=f"{period}/{market}/{config['config_id']}/{comparator}",
                        symbol=market, config_id=config["config_id"], comparator=comparator,
                        period=period, candidate=candidate, baseline=reference))
    result = family_bootstrap(matrices, comparisons, replicates=replicates,
                              block_weeks=4, seed=20260926, chunk_size=chunk_size)
    records = result.pop("records")
    target = campaign["output"] / f"family-bootstrap-r{replicates}"
    metadata = dict(**result, protocol_checksum=campaign["coverage"]["protocol_checksum"],
        source_hash=campaign["coverage"]["source_hash"], analysis_source_checksum=checksum(__file__),
        calendar_start=first.isoformat(), calendar_weeks=n_weeks,
        minimum_empirical_tail_step=1 / replicates,
        critical_quantile_probability_mc_se=math.sqrt(.95 * .05 / max(result.get("jointly_usable", 0), 1)),
        note="Simultaneous retrospective screen of the complete declared fixed-configuration family against both c00000 and zero in all/later periods. Shared calendar weights preserve market, policy and nested-period dependence. This does not correct earlier adaptive research or prove prospective performance. The Monte Carlo SE describes probability-scale resolution, not the standard error of the critical value.")
    parquet = target.with_suffix(".parquet")
    temporary = parquet.with_name(parquet.name + ".tmp-" + str(os.getpid()))
    pd.DataFrame(records).to_parquet(temporary, index=False)
    metadata.update(records_file=parquet.name, records_checksum=checksum(temporary), records_count=len(records))
    _verify_analysis_identity(campaign)
    save_json(target.with_suffix(".json"), metadata, immutable=True)
    os.replace(temporary, parquet)
    return metadata


def _verify_analysis_identity(campaign):
    expected = next((row["checksum"] for row in campaign["manifest"]["files"]
                     if row["path"] == "scripts/analyze-snd-combinations.py"), None)
    if expected is None or checksum(__file__) != expected:
        raise ValueError("Run the analysis source preserved in this campaign's frozen manifest")


def _verify_output_script_identity(campaign, payload, path, field):
    """Check recorded producing-script identities whenever artifacts supply one."""
    if field not in payload:
        return
    expected = next((row["checksum"] for row in campaign["manifest"]["files"] if row["path"] == path), None)
    if expected is None or payload[field] != expected:
        raise ValueError("Retained output script identity mismatch: " + path)


def stitched_equity_metrics(fold_equities, capital=100000.):
    """Carry cash P&L between flat-start folds; preserve every saved equity mark."""
    carry = float(capital)
    marks, times = [carry], []
    previous_end = None
    for fold in sorted(fold_equities, key=lambda row: utc(row["start"])):
        start, end, frame = utc(fold["start"]), utc(fold["end"]), fold["equity"]
        if previous_end is not None and start < previous_end:
            raise ValueError("Overlapping validation folds")
        stamps = pd.to_datetime(frame.timestamp, utc=True)
        values = frame.equity.to_numpy(float)
        if frame.empty or not np.isfinite(values).all() or not stamps.is_monotonic_increasing or stamps.duplicated().any() or (stamps < start).any() or (stamps > end).any():
            raise ValueError("Invalid fold equity marks")
        if frame.contracts.iloc[-1] != 0:
            raise ValueError("Validation fold must end flat")
        marks.append(carry)
        marks.extend((carry + values - capital).tolist())
        times.extend([start.isoformat()] + [stamp.isoformat() for stamp in stamps])
        carry += float(values[-1] - capital)
        previous_end = end
    path = np.asarray(marks)
    peaks = np.maximum.accumulate(path)
    return dict(net_pnl=float(path[-1] - capital), final_equity=float(path[-1]),
                max_drawdown=float((peaks - path).max()), min_equity=float(path.min()),
                max_drawdown_fraction=float(np.max(np.divide(peaks - path, peaks,
                    out=np.zeros_like(path), where=peaks > 0))), marked_observations=len(path) - 1)


def read_validation_cases(campaign):
    output, protocol = campaign["output"], campaign["protocol"]
    selected = read_json(output / "selection.json")
    _verify_output_script_identity(campaign, selected, "scripts/analyze-snd-combinations.py", "analysis_source_checksum")
    plan, completed = read_json(output / "validation-plan.json"), read_json(output / "validation-results.json")
    identities = {key: campaign["coverage"][key] for key in
                  ("protocol_checksum", "source_hash", "configurations_checksum")}
    identities["selection_checksum"] = checksum(output / "selection.json")
    for payload in (plan, completed):
        if any(payload.get(key) != value for key, value in identities.items()):
            raise ValueError("Validation identity differs from preserved selection/source")
    if completed.get("status") != "succeeded":
        raise ValueError("Validation results are not complete")
    expected_choices = {(market, fold["id"]) for market in protocol["markets"] for fold in protocol["folds"]}
    choices = {(row["symbol"], row["fold_id"]): row for row in selected["selections"]}
    if len(choices) != len(selected["selections"]) or set(choices) != expected_choices:
        raise ValueError("Selection market/fold coverage differs from protocol")
    roles = ["reference", "selected"] + [f"risk-{n}" for n in (50, 100, 200)]
    expected = {(market, fold, role, scenario["id"]) for market, fold in choices
                for role in roles for scenario in protocol["validation_scenarios"]}
    expected |= {(market, fold, f"neighbor-{i}", "cash_base") for market, fold in choices
                 for i in range(len(protocol["validation_neighbors"]))}

    def key(row):
        return tuple(row[name] for name in ("symbol", "fold_id", "role", "scenario"))

    planned = {key(row): row for row in plan["cases"]}
    results = {key(row): row for row in completed["cases"]}
    if len(planned) != len(plan["cases"]) or len(results) != len(completed["cases"]) or set(planned) != expected or set(results) != expected:
        raise ValueError("Missing, duplicate or unexpected validation cases")
    if plan.get("expected_cases") != len(expected) or completed.get("expected_cases") != len(expected) or completed.get("completed_cases") != len(expected):
        raise ValueError("Validation case-count declaration mismatch")
    loaded = []
    for case_key in sorted(expected):
        market, fold, role, scenario = case_key
        record, intended = results[case_key], planned[case_key]
        folder = output / "validation" / market / fold / role / scenario
        disk, inp, status = read_json(folder / "result.json"), read_json(folder / "input.json"), read_json(folder / "status.json")
        if disk != record or record.get("status") != "succeeded" or status.get("status") != "succeeded":
            raise ValueError("Validation saved case/status mismatch: " + str(folder))
        for payload in (record, inp):
            if any(payload.get(name) != value for name, value in identities.items()) or any(payload.get(name) != value for name, value in intended.items()):
                raise ValueError("Validation case differs from frozen plan")
        choice = choices[market, fold]
        if utc(record["start"]) != utc(choice["cutoff"]) or utc(record["end"]) != utc(choice["test_end"]):
            raise ValueError("Validation fold differs from training-only selection")
        if record["config_id"] != ("c00000" if role == "reference" else choice["selected_id"]):
            raise ValueError("Validation substituted a different selected configuration")
        artifacts = {item["name"]: item["checksum"] for item in record["artifacts"]}
        if not {"trades.parquet", "equity.parquet"}.issubset(artifacts):
            raise ValueError("Validation trade/equity artifacts missing")
        for name, digest in artifacts.items():
            if checksum(folder / name) != digest:
                raise ValueError("Validation artifact changed: " + str(folder / name))
        trades, equity = pd.read_parquet(folder / "trades.parquet"), pd.read_parquet(folder / "equity.parquet")
        cash = float(trades.net_pnl.sum())
        np.testing.assert_allclose(cash, equity.equity.iloc[-1] - protocol["capital"], rtol=0, atol=1e-5)
        np.testing.assert_allclose(cash, equity.net_pnl.sum(), rtol=0, atol=1e-5)
        np.testing.assert_allclose(cash, record["summary"]["closed_net"], rtol=0, atol=1e-5)
        if len(trades) != record["summary"]["trades"]:
            raise ValueError("Validation summary trade count mismatch")
        if len(trades):
            np.testing.assert_allclose(trades.gross_pnl - trades.cost, trades.net_pnl, rtol=0, atol=1e-6)
            np.testing.assert_allclose(trades.net_pnl / trades.risk_cash, trades.net_r, rtol=0, atol=1e-10)
            if (pd.to_datetime(trades.entry_time, utc=True) < utc(record["start"])).any() or (effective_exit_times(trades) > utc(record["end"])).any():
                raise ValueError("Validation trades cross a scoring boundary")
        if record["decision"] == "cash" and (len(trades) or cash != 0):
            raise ValueError("Cash selection contains fabricated trades or P&L")
        loaded.append(dict(record, folder=str(folder.relative_to(output)), trades_frame=trades, equity_frame=equity))
    return loaded


def collect_audit_evidence(campaign):
    output, expected = campaign["output"], campaign["coverage"]
    preflight = read_json(output / "preflight.json")
    sweep = read_json(output / "independent-sweep-audit.json")
    validation = read_json(output / "independent-validation-audit.json")
    for name, payload in (("preflight", preflight), ("sweep", sweep), ("validation", validation)):
        if payload.get("status") not in ("passed", "failed"):
            raise ValueError("Audit is not terminal: " + name)
        if payload.get("protocol_checksum") != expected["protocol_checksum"]:
            raise ValueError("Audit protocol identity mismatch: " + name)
    for name, payload in (("sweep", sweep), ("validation", validation)):
        if payload.get("source_hash") != expected["source_hash"]:
            raise ValueError("Audit source identity mismatch: " + name)
    if validation.get("selection_checksum") != checksum(output / "selection.json"):
        raise ValueError("Validation audit selection identity mismatch")
    frozen = {row["path"]: row["checksum"] for row in campaign["manifest"]["files"]}
    _verify_output_script_identity(campaign, sweep, "scripts/audit-snd-combinations.py", "script_checksum")
    _verify_output_script_identity(campaign, validation, "scripts/audit-snd-combination-validation.py", "script_checksum")
    source_match = all(frozen.get(path) == digest for path, digest in preflight.get("source_files", {}).items())
    controls, detail_matches = [], True
    market_entries = {row["symbol"]: row for row in preflight.get("markets", [])}
    if set(market_entries) != set(campaign["protocol"]["markets"]):
        detail_matches = False
    for market in campaign["protocol"]["markets"]:
        entry = market_entries.get(market, {})
        if not entry.get("artifact") or not entry.get("artifact_checksum"):
            detail_matches = False
            continue
        path = output / entry["artifact"]
        if not path.is_file() or checksum(path) != entry["artifact_checksum"]:
            raise ValueError("Preflight detail checksum mismatch: " + market)
        detail = read_json(path)
        records = detail.get("records", [])
        detail_matches &= (detail.get("status") == "passed" and detail.get("symbol") == market
                           and len(records) == entry.get("checks") and all(row.get("status") == "passed" for row in records))
        controls.extend(dict(row, symbol=market) for row in records)
    counts = {kind: dict(observed=sum(row.get("kind") == kind for row in controls),
                        passed=sum(row.get("kind") == kind and row.get("status") == "passed" for row in controls))
              for kind in ("frozen_full_history_control", "crossed_reference", "causal_prefix")}
    supplemental = {}
    for name in ("synthetic-grid-parity", "risk-reference-parity"):
        payload = read_json(output / (name + ".json"))
        if payload.get("status") not in ("passed", "failed", "incomplete"):
            raise ValueError("Implementation check is not terminal: " + name)
        if payload.get("protocol_checksum") != expected["protocol_checksum"] or payload.get("configurations_checksum") != expected["configurations_checksum"]:
            raise ValueError("Implementation check declaration mismatch: " + name)
        if "attempt_artifact" in payload:
            path = output / payload["attempt_artifact"]
            if not path.is_file() or checksum(path) != payload.get("attempt_checksum"):
                raise ValueError("Implementation attempt checksum mismatch: " + name)
            if read_json(path) != {key: value for key, value in payload.items() if key not in ("attempt_artifact", "attempt_checksum")}:
                raise ValueError("Implementation summary differs from preserved attempt: " + name)
        for previous in payload.get("prior_attempts", []):
            path = output / previous["artifact"]
            if not path.is_file() or checksum(path) != previous["checksum"]:
                raise ValueError("Preserved implementation attempt changed: " + name)
        sources = payload.get("source_files", {})
        payload["frozen_source_matches"] = bool(sources) and all(frozen.get(path) == digest for path, digest in sources.items())
        supplemental[name] = payload
    synthetic = supplemental["synthetic-grid-parity"]
    synthetic_ok = (synthetic.get("status") == "passed" and synthetic["frozen_source_matches"]
        and synthetic.get("complete_grid") is True and not synthetic.get("failures")
        and synthetic.get("declared_configurations") == campaign["protocol"]["expected_configurations"]
        and synthetic.get("completed_configurations") == synthetic.get("declared_configurations")
        and synthetic.get("expected_comparisons", 0) > 0
        and synthetic.get("expected_comparisons") == synthetic.get("completed_comparisons") == synthetic.get("passed_comparisons"))
    risk = supplemental["risk-reference-parity"]
    expected_risk = {(market, variant) for market in campaign["protocol"]["markets"] for variant in ("wick_baseline", "body_strict")}
    observed_risk = {(row.get("symbol"), row.get("variant")) for row in risk.get("records", [])}
    risk_ok = (risk.get("status") == "passed" and risk["frozen_source_matches"] and risk.get("source_unchanged") is True
        and len(risk.get("records", [])) == len(expected_risk) and observed_risk == expected_risk
        and all(row.get("status") == "passed" for row in risk.get("records", [])))
    validation_cases = len(campaign["protocol"]["markets"]) * len(campaign["protocol"]["folds"]) * (
        5 * len(campaign["protocol"]["validation_scenarios"]) + len(campaign["protocol"]["validation_neighbors"]))
    all_passed = (all(payload.get("status") == "passed" for payload in (preflight, sweep, validation))
                  and bool(preflight.get("source_files")) and source_match and detail_matches
                  and bool(sweep.get("complete_sweep")) and sweep.get("audited_cases") == expected["expected"]
                  and bool(validation.get("complete_validation")) and validation.get("audited_cases") == validation_cases
                  and synthetic_ok and risk_ok)
    return dict(all_passed=all_passed, preflight=preflight, preflight_source_matches=source_match,
                preflight_details_match=bool(detail_matches), observed_controls=counts, sweep=sweep, validation=validation,
                synthetic_grid=synthetic, synthetic_grid_passed=bool(synthetic_ok),
                risk_reference=risk, risk_reference_passed=bool(risk_ok))


def validation_summary(campaign, loaded, *, conditional_replicates=10000):
    protocol = campaign["protocol"]
    capital = protocol["capital"]
    start, end = min(utc(row["cutoff"]) for row in protocol["folds"]), max(utc(row["test_end"]) for row in protocol["folds"])
    pooled, fold_rows, trades_by_path = [], [], {}
    paths = sorted({(row["symbol"], row["role"], row["scenario"]) for row in loaded})
    for symbol, role, scenario in paths:
        rows = sorted([row for row in loaded if (row["symbol"], row["role"], row["scenario"]) == (symbol, role, scenario)], key=lambda row: utc(row["start"]))
        if {row["fold_id"] for row in rows} != {fold["id"] for fold in protocol["folds"]}:
            raise ValueError("Pooled path lacks a declared fold")
        frames = [row["trades_frame"] for row in rows if len(row["trades_frame"])]
        trades = pd.concat(frames, ignore_index=True) if frames else rows[0]["trades_frame"].iloc[:0].copy()
        trades_by_path[symbol, role, scenario] = trades
        metrics = stitched_equity_metrics([dict(start=row["start"], end=row["end"], equity=row["equity_frame"]) for row in rows], capital)
        n, r_sum, cost = len(trades), float(trades.net_r.sum()), float(trades.cost.sum())
        closed_net = float(trades.net_pnl.sum())
        np.testing.assert_allclose(metrics["net_pnl"], closed_net, rtol=0, atol=1e-5)
        pooled.append(dict(symbol=symbol, role=role, scenario=scenario, trades=n, net_r_sum=r_sum,
            mean_net_r=r_sum / n if n else None, closed_net=closed_net, cost=cost,
            cash_folds=sum(row["decision"] == "cash" for row in rows), **metrics))
        for row in rows:
            t = row["trades_frame"]
            fold_rows.append(dict(symbol=symbol, fold_id=row["fold_id"], role=role, scenario=scenario,
                config_id=row["config_id"], decision=row["decision"], status="cash" if row["decision"] == "cash" else row["status"],
                trades=len(t), net_r_sum=float(t.net_r.sum()), closed_net=float(t.net_pnl.sum()),
                mean_net_r=float(t.net_r.mean()) if len(t) else None,
                max_drawdown=row["summary"]["max_drawdown"], max_trade_loss=row["summary"].get("max_trade_loss"),
                total_budget_overshoot=row["summary"].get("total_budget_overshoot"), folder=row["folder"]))
    by_path = {(row["symbol"], row["role"], row["scenario"]): row for row in pooled}
    markets, contrasts = [], []
    for symbol in protocol["markets"]:
        selected = trades_by_path[symbol, "selected", "cash_base"]
        reference = trades_by_path[symbol, "reference", "cash_base"]
        arrays = [calendar_week_arrays(t, start, end) for t in (selected, reference)]
        sums, counts = (np.column_stack([row[key] for row in arrays]) for key in ("sum_r", "counts"))
        matrices = {"stitched": (sums, counts)}
        weights = moving_block_weights(len(sums), conditional_replicates, seed=20260926, block_weeks=4)
        intervals = {}
        for name, baseline in (("selected_mean_r", None), ("selected_minus_reference_mean_r", 1)):
            inference = family_bootstrap(matrices, [dict(id=name, period="stitched", candidate=0, baseline=baseline)],
                replicates=conditional_replicates, weights=weights, block_weeks=4)
            row = inference["records"][0]
            row.update(symbol=symbol, inference="Conditional pointwise four-week block-bootstrap interval on the frozen selected path; not selection-adjusted", replicates=conditional_replicates)
            intervals[name] = row
            contrasts.append(row)
        scenarios = {scenario["id"]: [row for row in fold_rows if row["symbol"] == symbol and row["role"] == "selected" and row["scenario"] == scenario["id"]]
                     for scenario in protocol["validation_scenarios"]}
        neighbors = {f"neighbor-{i}": [row for row in fold_rows if row["symbol"] == symbol and row["role"] == f"neighbor-{i}"]
                     for i in range(len(protocol["validation_neighbors"]))}
        gates = protocol_validation_gates(protocol, scenarios,
            conditional_mean_r_ci_low=intervals["selected_mean_r"]["ci_low"], neighbor_folds=neighbors)
        risk = by_path[symbol, "risk-100", "price_2_double_fee"]
        risk_pass = bool(risk["trades"] > 0 and risk["closed_net"] > 0 and risk["min_equity"] > 0)
        selected_metrics, ref_metrics = by_path[symbol, "selected", "cash_base"], by_path[symbol, "reference", "cash_base"]
        markets.append(dict(symbol=symbol, economic_gates=gates, conditional_intervals=intervals,
            risk100_adverse_cash_pass=risk_pass, selected=selected_metrics, reference=ref_metrics,
            selected_minus_reference_cash=selected_metrics["closed_net"] - ref_metrics["closed_net"],
            risk100_adverse=risk))
    return dict(markets=markets, pooled_paths=pooled, fold_rows=fold_rows, conditional_intervals=contrasts,
                conditional_replicates=conditional_replicates,
                note="Fold equity is stitched by carrying cash P&L across each independently flat-start replay. Conditional inference is not a correction for choosing models or for prior research; full-family screens are separately reported.")


def _md_table(headers, rows):
    return "\n".join(["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"] +
                     ["| " + " | ".join(str(value) for value in row) + " |" for row in rows])


def _fmt(value, digits=2):
    return f"{value:,.{digits}f}" if _finite(value) else "unavailable"


def write_validation_report(campaign):
    if not campaign["coverage"]["complete"]:
        raise ValueError("Complete grid required before final validation reporting")
    _verify_analysis_identity(campaign)
    loaded = read_validation_cases(campaign)
    audits = collect_audit_evidence(campaign)
    summary = validation_summary(campaign, loaded, conditional_replicates=10000)
    output, protocol, coverage = campaign["output"], campaign["protocol"], campaign["coverage"]
    # The family screen is mandatory but reported independently of conditional
    # selected-path intervals. Require one unambiguous, verified analysis file.
    family_files = sorted(output.glob("family-bootstrap-r*.json"))
    if not family_files:
        raise ValueError("Full-family screen required before final report")
    families = []
    for path in family_files:
        family = read_json(path)
        if family.get("protocol_checksum") != coverage["protocol_checksum"] or family.get("source_hash") != coverage["source_hash"] or family.get("analysis_source_checksum") != checksum(__file__):
            raise ValueError("Family screen identity mismatch")
        expected_size = protocol["expected_market_cases"] * 4
        parquet = path.with_suffix(".parquet")
        if family.get("family_size") != expected_size or family.get("records_count") != expected_size or not parquet.is_file():
            raise ValueError("Family screen does not cover the declared universe")
        if family.get("records_checksum") != checksum(parquet):
            raise ValueError("Family-screen result artifact changed")
        family["file"] = path.name
        families.append(family)
    factors = read_json(output / "factor-effects.json")
    _verify_output_script_identity(campaign, factors, "scripts/summarize-snd-combination-factors.py", "script_checksum")
    if factors.get("status") != "succeeded" or factors.get("protocol_checksum") != coverage["protocol_checksum"] or factors.get("source_hash") != coverage["source_hash"] or factors.get("artifact_checksum") != checksum(output / "factor-effects.csv"):
        raise ValueError("Matched factor summaries are missing or changed")
    factor_rows = factors.get("records", [])
    expected_factor_rows = len(protocol["markets"]) * 4 * sum(len(levels) - 1 for levels in protocol["grid"].values())
    if len(factor_rows) != factors.get("rows") or len(factor_rows) != expected_factor_rows:
        raise ValueError("Incomplete descriptive factor contrasts")
    for market in summary["markets"]:
        market["historical_candidate"] = bool(market["economic_gates"]["passed"])
        market["implementation_checks_passed"] = bool(audits["all_passed"])
    payload = dict(protocol_checksum=coverage["protocol_checksum"], source_hash=coverage["source_hash"],
        selection_checksum=checksum(output / "selection.json"), validation_results_checksum=checksum(output / "validation-results.json"),
        analysis_source_checksum=checksum(__file__), audit_counts=coverage, audits=audits,
        families=families, factors=factors, validation=summary, feasible_or_prospective_claim=False)
    _verify_analysis_identity(campaign)
    save_json(output / "validation-analysis.json", payload, immutable=True)
    pd.DataFrame(summary["pooled_paths"]).to_csv(output / "validation-pooled-paths.csv", index=False)
    pd.DataFrame(summary["fold_rows"]).to_csv(output / "validation-folds.csv", index=False)
    pd.DataFrame(summary["conditional_intervals"]).to_csv(output / "validation-conditional-intervals.csv", index=False)
    counts = audits["observed_controls"]
    lines = ["# Supply/demand combinations: historical validation", "",
        f"All {coverage['expected']:,} declared core market/configuration cases are accounted for, with {coverage['succeeded']:,} successful current results. The frozen training-only selector was replayed in {len(loaded):,} validation cases.", "",
        f"{sum(row['historical_candidate'] for row in summary['markets'])} of {len(summary['markets'])} markets passed the frozen historical economic gates. Implementation checks and the adverse risk-100 sizing diagnostic are reported separately; an economic pass can still fail that sizing stress. This is retrospective evidence on previously inspected history; no result establishes prospective or live feasibility.", "",
        "## What the rule combinations show", "",
        "The following fixed view uses January 2025–July 2026 and requires at least 100 trades on both sides of each matched rule change. Each cell is median change in mean net R, followed by the eligible pair count. All other configuration settings are held fixed within a pair. Shared data and trades make these descriptive sensitivity summaries, not independent tests, causal effects or universal rules.", "",
        _md_table(["Rule change"] + protocol["markets"], [
            [f"{rule}: {levels[0]} → {value}"] + [
                next((f"{_fmt(row['median_delta_mean_net_r'],4)} ({row['both_meet_trade_minimum']:,})" for row in factor_rows
                      if row["symbol"] == market and row["period"] == "later" and row["rule"] == rule
                      and row["changed_level"] == value and row["minimum_trades_each"] == 100), "unavailable")
                for market in protocol["markets"]]
            for rule, levels in protocol["grid"].items() for value in levels[1:]]), "",
        "All full/later and any-trade/100-trade comparisons, quartiles, cash changes and trade-frequency effects remain in [factor-effects.csv](factor-effects.csv). The training selector was frozen before these descriptions; these aggregates do not promote candidates.", "",
        "## Selected paths and matched reference", "",
        "Each fold starts flat. Dollar P&L uses the stated contract sizing; mean R measures return relative to each trade's initial stop risk. They need not agree. Drawdown uses stitched saved five-minute equity marks, including cross-fold losses.", "",
        _md_table(["Market", "Trades", "Selected net $", "Reference net $", "Difference $", "Mean net R", "Worst drawdown $", "Economic gates", "Implementation", "Risk-100 adverse"],
            [[row["symbol"], row["selected"]["trades"], _fmt(row["selected"]["closed_net"]), _fmt(row["reference"]["closed_net"]),
              _fmt(row["selected_minus_reference_cash"]), _fmt(row["selected"]["mean_net_r"], 4), _fmt(row["selected"]["max_drawdown"]),
              "passed" if row["historical_candidate"] else "not confirmed",
              "passed" if row["implementation_checks_passed"] else "not confirmed",
              "supported" if row["risk100_adverse_cash_pass"] else "failed"] for row in summary["markets"]]), "",
        "## Conditional uncertainty", "",
        "These pointwise 95% intervals use 10,000 four-week calendar-block draws, retaining empty weeks. The reference contrast shares the same sampled weeks. They are conditional on the already selected paths and are **not selection-adjusted**. The complete fixed-configuration family screen is separate.", "",
        _md_table(["Market", "Selected mean R interval", "Selected − reference mean R interval"],
            [[row["symbol"], f"[{_fmt(row['conditional_intervals']['selected_mean_r']['ci_low'],4)}, {_fmt(row['conditional_intervals']['selected_mean_r']['ci_high'],4)}]",
              f"[{_fmt(row['conditional_intervals']['selected_minus_reference_mean_r']['ci_low'],4)}, {_fmt(row['conditional_intervals']['selected_minus_reference_mean_r']['ci_high'],4)}]"] for row in summary["markets"]]), "",
        "## Every validation path", "",
        _md_table(["Market", "Role", "Scenario", "Trades", "Net $", "Mean R", "Worst drawdown $", "Cash folds"],
            [[row["symbol"], row["role"], row["scenario"], row["trades"], _fmt(row["closed_net"]), _fmt(row["mean_net_r"],4), _fmt(row["max_drawdown"]), row["cash_folds"]] for row in summary["pooled_paths"]]), "",
        "Risk-50/100/200 paths rerun integer contract sizing with the requested per-entry cash risk budget and a ten-contract cap. Costs and adverse prices can change fills and later opportunities. Budgets are not guaranteed loss caps under gaps. The risk-100 price_2_double_fee diagnostic requires positive pooled cash P&L, at least one trade and positive minimum marked equity. A failure remains explicit even if the separate frozen economic gates pass; it provides no support for using that sizing budget. Passing does not establish margin, capacity or brokerage feasibility.", "",
        "## Fold outcomes", "",
        _md_table(["Market", "Fold", "Selected config", "Decision", "Trades", "Base net $", "Base mean R"],
            [[row["symbol"], row["fold_id"], row["config_id"] or "none", row["decision"], row["trades"], _fmt(row["closed_net"]), _fmt(row["mean_net_r"],4)]
             for row in summary["fold_rows"] if row["role"] == "selected" and row["scenario"] == "cash_base"]), "",
        "## Verification and complete search accounting", "",
        f"Preflight status: **{audits['preflight']['status']}**; frozen-source match: **{audits['preflight_source_matches']}**. Observed passed controls: "
        f"{counts['frozen_full_history_control']['passed']}/{counts['frozen_full_history_control']['observed']} full-history controls, "
        f"{counts['crossed_reference']['passed']}/{counts['crossed_reference']['observed']} crossed-rule comparisons, and "
        f"{counts['causal_prefix']['passed']}/{counts['causal_prefix']['observed']} causal-prefix checks.", "",
        f"Synthetic declared-grid parity: **{audits['synthetic_grid']['status']}**, frozen-source match **{audits['synthetic_grid']['frozen_source_matches']}**; "
        f"{audits['synthetic_grid'].get('passed_comparisons',0):,}/{audits['synthetic_grid'].get('expected_comparisons',0):,} fixture/configuration comparisons, "
        f"{audits['synthetic_grid'].get('nonzero_configurations',0):,} configurations with at least one reference trade. "
        f"{len(audits['synthetic_grid'].get('prior_attempts',[]))} prior synthetic attempts remain preserved. "
        "These use controlled chart/hourly bias and compare complete trade/equity output; they do not prove all possible price paths. Details: [synthetic-grid-parity.json](synthetic-grid-parity.json).", "",
        f"Full-history risk/reference fixed-one parity: **{audits['risk_reference']['status']}**, frozen-source match **{audits['risk_reference']['frozen_source_matches']}**; "
        f"{sum(row.get('status') == 'passed' for row in audits['risk_reference'].get('records',[]))}/{len(audits['risk_reference'].get('records',[]))} observed controls, "
        f"{sum(row.get('trades',0) for row in audits['risk_reference'].get('records',[])):,} exact common-column trades and "
        f"{sum(row.get('equity_rows',0) for row in audits['risk_reference'].get('records',[])):,} exact equity rows. "
        "The independently prepared engines agree for those fixed-one controls; this does not establish an edge under cash-risk sizing. Details: [risk-reference-parity.json](risk-reference-parity.json).", "",
        f"Independent sweep audit: **{audits['sweep']['status']}**; {audits['sweep'].get('audited_cases','unreported')} audited cases, "
        f"{audits['sweep'].get('exhaustive_accounting_trades','unreported')} accounted trades and {audits['sweep'].get('raw_sampled_trades','unreported')} raw-reconstructed samples. "
        "Raw reconstruction is sampled; it does not certify every intrabar price path.", "",
        f"Independent validation audit: **{audits['validation']['status']}**. Its exact checks, failures and limitations remain in [independent-validation-audit.json](independent-validation-audit.json).", "",
        f"The ledger preserves {coverage['historical_failed_attempts']} earlier failed shard attempts and {coverage['historical_failed_case_attempts']} failed case attempts. "
        "Zero-trade and cash outcomes remain present. Complete identities, rejected training configurations, scenario paths and gate failures are retained in the linked artifacts.", "",
        "## Full-family screen", "",
        _md_table(["Artifact", "Comparisons", "Draws", "Estimable", "Calibrated", "Empirical tail step"],
            [[f"[{row['file']}]({row['file']})", row["family_size"], row["replicates"], row["estimable_comparisons"], row["calibrated"], _fmt(row["minimum_empirical_tail_step"],6)] for row in families]), "",
        "This simultaneous screen includes every declared market/configuration against c00000 and zero in full/later history, including unavailable degenerate comparisons. It adjusts that supplied family only, not earlier adaptive research. No post-result threshold, runner-up replacement, or neighbor substitution is authorized by this report.", "",
        "## Limits and preserved prospective work", "",
        "The strategy definition, costs, labels and prior exposure are fixed in [protocol.json](protocol.json). All scored history was previously researched. OHLC data cannot establish unfilled institutional orders, exact tick order, queue position, capacity or margin. Continuous unadjusted rolls, idealized roll liquidation, gaps and missing observations remain execution limitations. MNQ and ES are correlated markets.", "",
        "The MGC source lacks usable contract-roll metadata. Its zero detected rolls therefore do not demonstrate an absence of contract transitions; roll-specific liquidation/reset behavior cannot be reconstructed reliably from that metadata. The observed full-history controls detect 19 rolls for MNQ/ES and 56 for CL.", "",
        "The existing September 26, 04:30 UTC MNQ prospective freeze is preserved. This campaign neither changes that freeze nor turns already inspected local data into new prospective evidence.", "",
        "Artifacts: [selection](selection.json), [all training scores](selection-training-scores.parquet), [complete validation analysis](validation-analysis.json), [pooled paths](validation-pooled-paths.csv), [all fold/scenario results](validation-folds.csv), [conditional intervals](validation-conditional-intervals.csv), [grid coverage](grid-coverage.json), [independent sweep audit](independent-sweep-audit.json).", ""]
    report = "\n".join(lines)
    (output / "REPORT.md").write_text(report, encoding="utf-8")
    (output / "RESULTS.md").write_text(report, encoding="utf-8")
    write_progress_report(campaign)
    return dict(validation_cases=len(loaded), markets=len(summary["markets"]), historical_candidates=sum(row["historical_candidate"] for row in summary["markets"]), audits_passed=audits["all_passed"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1] / "reports/snd-combinations-2026-09-26")
    parser.add_argument("--selection", action="store_true")
    parser.add_argument("--family", action="store_true")
    parser.add_argument("--report-partial", action="store_true")
    parser.add_argument("--validation-report", action="store_true")
    parser.add_argument("--replicates", type=int, default=2000)
    parser.add_argument("--chunk-size", type=int, default=128)
    args = parser.parse_args()
    if not any((args.selection, args.family, args.report_partial, args.validation_report)):
        parser.error("Choose --selection, --family, --report-partial, or --validation-report")
    campaign = verify_campaign(args.output, require_complete=args.selection or args.family or args.validation_report)
    if args.report_partial:
        write_progress_report(campaign)
    summary = dict(coverage={key: value for key, value in campaign["coverage"].items()
                             if key not in ("missing_ids", "other_attempts")})
    if args.selection:
        selected = write_selections(campaign)
        summary["selections"] = [dict(symbol=row["symbol"], fold_id=row["fold_id"], selected_id=row["selected_id"], eligible_count=row["eligible_count"])
                                  for row in selected["selections"]]
    if args.family:
        summary["family"] = write_family_analysis(campaign, replicates=args.replicates, chunk_size=args.chunk_size)
    if args.validation_report:
        summary["validation"] = write_validation_report(campaign)
    _verify_analysis_identity(campaign)
    print(json.dumps(_json_clean(summary), indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
