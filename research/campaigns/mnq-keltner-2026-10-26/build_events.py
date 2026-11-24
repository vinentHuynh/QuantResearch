"""Frozen MNQ Keltner study: causal features, matched controls, minute outcomes.

Run ``python build_events.py --self-test`` before ``python build_events.py``.
This is an event study, not an executable strategy or P&L backtest.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
CAMPAIGN = Path(__file__).resolve().parent
OUTPUT = ROOT / "artifacts" / "mnq-keltner-2026-10-26"
MINUTE_NS = 60_000_000_000
HORIZONS = (15, 60, 120)
BARRIERS = ((0.5, "05"), (1.0, "10"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ns(index) -> np.ndarray:
    return pd.DatetimeIndex(index).as_unit("ns").asi8


def split_labels(index, protocol):
    times = ns(index)
    labels = np.full(len(times), "outside", dtype=object)
    ends = np.zeros(len(times), dtype=np.int64)
    for name, (start, end) in protocol["splits_utc"].items():
        start_ns, end_ns = pd.Timestamp(start).value, pd.Timestamp(end).value
        mask = (times >= start_ns) & (times < end_ns)
        labels[mask], ends[mask] = name, end_ns
    return labels, ends


def time_labels(index):
    local = pd.DatetimeIndex(index).tz_convert("America/Chicago")
    minutes = local.hour * 60 + local.minute
    bucket = np.select(
        [(minutes >= 510) & (minutes < 600),
         (minutes >= 600) & (minutes < 780),
         (minutes >= 780) & (minutes < 900),
         (minutes >= 900) & (minutes < 960)],
        ["opening", "midday", "afternoon", "post_cash"],
        default="overnight",
    )
    date = local.tz_localize(None).normalize() + pd.to_timedelta((minutes >= 1020).astype(int), unit="D")
    return bucket, date.strftime("%Y-%m-%d").to_numpy(), date.year.to_numpy()


def load_minutes(protocol):
    dataset = ROOT / "data" / "workbench" / "datasets" / protocol["dataset_id"]
    path = dataset / "bars.parquet"
    checksum = sha256(path)
    if checksum != protocol["dataset_sha256"]:
        raise ValueError("Dataset checksum differs from frozen protocol")
    frame = pd.read_parquet(path)
    if frame.index.tz is None or not frame.index.is_monotonic_increasing or frame.index.has_duplicates:
        raise ValueError("Expected ordered unique timezone-aware minute timestamps")
    frame.index = frame.index.tz_convert("UTC")
    if (ns(frame.index) % MINUTE_NS != 0).any():
        raise ValueError("Input contains timestamps off minute boundaries")
    prices = frame[["open", "high", "low", "close"]]
    if not np.isfinite(prices.to_numpy()).all():
        raise ValueError("Nonfinite input prices")
    if ((frame.high < prices.max(axis=1)) | (frame.low > prices.min(axis=1))).any():
        raise ValueError("Invalid OHLC")
    if set(frame.symbol.unique()) != {"MNQ.v.0"}:
        raise ValueError("Expected actual MNQ.v.0 data")
    local = frame.index.tz_convert("America/Chicago")
    minute = local.hour * 60 + local.minute
    trading_date = local.tz_localize(None).normalize() + pd.to_timedelta((minute >= 1020).astype(int), unit="D")
    keep = ((minute < 960) | (minute >= 1020)) & (trading_date.dayofweek < 5)
    audit = {
        "path": str(path), "sha256": checksum, "native_rows": len(frame),
        "first": str(frame.index[0]), "last": str(frame.index[-1]),
        "excluded_maintenance_or_weekend_rows": int((~keep).sum()),
        "gaps_over_one_minute": int((frame.index.to_series().diff() > pd.Timedelta(minutes=1)).sum()),
        "contract_changes": int(frame.instrument_id.ne(frame.instrument_id.shift()).sum() - 1),
        "manifest": json.loads((dataset / "dataset.json").read_text(encoding="utf-8")),
    }
    return frame.loc[keep, ["open", "high", "low", "close", "volume", "instrument_id"]].copy(), audit


def build_bars(minutes, timeframe, protocol):
    grouped = minutes.groupby(minutes.index.floor(f"{timeframe}min"), sort=True)
    bars = grouped.agg(open=("open", "first"), high=("high", "max"), low=("low", "min"),
                       close=("close", "last"), volume=("volume", "sum"),
                       minute_count=("close", "size"), instrument_id=("instrument_id", "last"),
                       instrument_count=("instrument_id", "nunique"))
    bars.index.name = "timestamp"
    if (bars.instrument_count > 1).any():
        raise ValueError("Mixed-contract aggregated candle requires explicit handling")
    bars["complete"] = bars.minute_count.eq(timeframe)
    bars["contract_segment"] = bars.instrument_id.ne(bars.instrument_id.shift()).cumsum()
    bars["bar_in_contract"] = bars.groupby("contract_segment").cumcount()
    bars["decision_time"] = bars.index + pd.Timedelta(minutes=timeframe)
    length = int(protocol["indicator"]["ema_length"])
    atr_length = int(protocol["indicator"]["atr_length"])
    previous_close = bars.groupby("contract_segment").close.shift()
    bars["tr"] = pd.concat([bars.high - bars.low, (bars.high - previous_close).abs(),
                             (bars.low - previous_close).abs()], axis=1).max(axis=1)
    bars["ema"] = bars.groupby("contract_segment", sort=False).close.transform(
        lambda s: s.ewm(span=length, adjust=False).mean())
    bars["atr"] = bars.groupby("contract_segment", sort=False).tr.transform(
        lambda s: s.rolling(atr_length, min_periods=atr_length).mean())
    bars["prebar_atr"] = bars.groupby("contract_segment").atr.shift()
    bars["slope_raw"] = (bars.groupby("contract_segment").ema.shift(1) -
                          bars.groupby("contract_segment").ema.shift(6)) / bars.prebar_atr
    width = float(protocol["indicator"]["multiplier"]) * bars.atr
    bars["upper"], bars["lower"] = bars.ema + width, bars.ema - width
    bars["upper_breach"], bars["lower_breach"] = bars.high.gt(bars.upper), bars.low.lt(bars.lower)
    bars["dual_breach"] = bars.upper_breach & bars.lower_breach
    bars["close_side"] = np.sign(bars.close - bars.ema).astype(np.int8)
    warmup = int(protocol["indicator"]["warmup_bars_per_contract"])
    # 100 completed prior observations initialize the signal and preceding candle.
    bars["warmed"] = bars.bar_in_contract.ge(warmup)
    prior_ok = (bars.complete.shift(1, fill_value=False) & bars.warmed.shift(1, fill_value=False)
                & bars.contract_segment.eq(bars.contract_segment.shift(1)))
    bars["eligible"] = (bars.complete & bars.warmed & prior_ok & bars.atr.gt(0)
                          & bars.prebar_atr.gt(0) & np.isfinite(bars.slope_raw))
    bars["time_bucket"], bars["day"], bars["year"] = time_labels(bars.index)
    bars["split"], bars["split_end_ns"] = split_labels(bars.index, protocol)
    bars["eligible"] &= bars.split.ne("outside")
    bars["bar_index"] = np.arange(len(bars), dtype=np.int64)
    return bars


def build_event_features(bars, timeframe):
    breach = bars.upper_breach | bars.lower_breach
    mask = bars.eligible & breach & ~bars.dual_breach
    events = bars.loc[mask].copy()
    events["side"] = np.where(events.upper_breach, 1, -1).astype(np.int8)
    side = events.side.to_numpy()
    band = np.where(side > 0, events.upper, events.lower)
    outside = side * (events.close.to_numpy() - band) > 0
    events["type"] = np.where(outside, "close_outside", "wick_only")
    previous_upper = bars.upper_breach.shift(1, fill_value=False).loc[mask].to_numpy()
    previous_lower = bars.lower_breach.shift(1, fill_value=False).loc[mask].to_numpy()
    events["episode_start"] = ~np.where(side > 0, previous_upper, previous_lower)
    prior_above = bars.close.gt(bars.upper).shift(1, fill_value=False).loc[mask].to_numpy()
    prior_below = bars.close.lt(bars.lower).shift(1, fill_value=False).loc[mask].to_numpy()
    events["first_close_outside"] = outside & ~np.where(side > 0, prior_above, prior_below)
    extreme = np.where(side > 0, events.high, events.low)
    outer_body = np.where(side > 0, np.maximum(events.open, events.close), np.minimum(events.open, events.close))
    events["extreme_extension_points"] = side * (extreme - band)
    events["close_extension_points"] = np.maximum(side * (events.close.to_numpy() - band), 0.0)
    events["signed_close_extension_atr"] = side * (events.close.to_numpy() - band) / events.atr
    events["outer_wick_points"] = side * (extreme - outer_body)
    outside_wick_start = np.where(side > 0, np.maximum(outer_body, band), np.minimum(outer_body, band))
    events["wick_portion_outside_points"] = np.maximum(side * (extreme - outside_wick_start), 0.0)
    events["range_points"] = events.high - events.low
    events["body_points"] = (events.close - events.open).abs()
    for feature in ("extreme_extension", "close_extension", "outer_wick", "wick_portion_outside", "range", "body"):
        events[f"{feature}_atr"] = events[f"{feature}_points"] / events.atr
        events[f"{feature}_prebar_atr"] = events[f"{feature}_points"] / events.prebar_atr
    events["body_fraction"] = events.body_points / events.range_points
    events["outer_wick_fraction"] = events.outer_wick_points / events.range_points
    events["directional_close_location"] = np.where(side > 0, events.close - events.low, events.high - events.close) / events.range_points
    events["prebar_ema_slope_atr"] = side * events.slope_raw
    events["open_outside"] = side * (events.open.to_numpy() - band) > 0
    events["frozen_band"] = band
    events["timeframe"] = f"{timeframe}m"
    events["event_id"] = [f"{timeframe}m-{int(i)}" for i in events.bar_index]
    events = events.reset_index()
    return events


def select_controls(bars, events):
    """Use feature-only historical matching; no outcome is read by this function."""
    candidate_ok = (bars.eligible & ~bars.upper_breach & ~bars.lower_breach).to_numpy()
    candidates = np.flatnonzero(candidate_ok)
    slope = bars.slope_raw.to_numpy()
    prebar_atr = bars.prebar_atr.to_numpy()
    log_atr = np.full(len(bars), np.nan)
    np.log(prebar_atr, out=log_atr, where=prebar_atr > 0)
    splits = bars.split.to_numpy()
    buckets = bars.time_bucket.to_numpy()
    directions = bars.close_side.to_numpy()
    control_index = np.full(len(events), -1, dtype=np.int64)
    match_distance = np.full(len(events), np.nan)
    for row in np.flatnonzero(events.episode_start.to_numpy()):
        i = int(events.bar_index.iloc[row])
        side = int(events.side.iloc[row])
        lo, hi = np.searchsorted(candidates, [max(0, i - 2000), i])
        pool = candidates[lo:hi]
        pool = pool[(splits[pool] == splits[i]) & (buckets[pool] == buckets[i]) & (directions[pool] == directions[i])]
        if not len(pool):
            continue
        ds = np.abs(side * slope[pool] - side * slope[i])
        da = np.abs(log_atr[pool] - log_atr[i])
        accept = (ds <= 0.75) & (da <= 0.35)
        pool, distance = pool[accept], (ds + da)[accept]
        if not len(pool):
            continue
        # Reverse pool so np.argmin chooses the latest earlier candle on exact ties.
        winner = len(pool) - 1 - int(np.argmin(distance[::-1]))
        control_index[row], match_distance[row] = pool[winner], distance[winner]
    return control_index, match_distance


def minute_outcomes(minutes, probes, chunk_size=4096):
    """Compute passage outcomes from next-minute open, without candle path guesses.

    probes needs decision_time, instrument_id, split_end_ns, atr, side, ema,
    frozen_band and type. A full horizon is mandatory even if a barrier hit early.
    """
    columns = {}
    for horizon in HORIZONS:
        for _, code in BARRIERS:
            columns[f"outcome_{code}_{horizon}"] = np.full(len(probes), "incomplete", dtype=object)
        for key in ("ret_atr", "ret_points", "ema_touch", "band_return", "mfe_reversion_atr", "mfe_continuation_atr"):
            columns[f"{key}_{horizon}"] = np.full(len(probes), np.nan)
        columns[f"complete_{horizon}"] = np.zeros(len(probes), dtype=bool)
        columns[f"incomplete_reason_{horizon}"] = np.full(len(probes), "", dtype=object)
    columns["entry_price"] = np.full(len(probes), np.nan)
    columns["entry_time"] = np.full(len(probes), np.datetime64("NaT"), dtype="datetime64[ns]")
    if not len(probes):
        return pd.DataFrame(columns)
    times = ns(minutes.index)
    mo, mh, ml, mc = [minutes[c].to_numpy(dtype=float) for c in ("open", "high", "low", "close")]
    ids = minutes.instrument_id.to_numpy()
    changes = np.r_[0, np.cumsum(ids[1:] != ids[:-1])]
    decisions = ns(probes.decision_time)
    starts = np.searchsorted(times, decisions)
    pids = probes.instrument_id.to_numpy()
    split_ends = probes.split_end_ns.to_numpy(dtype=np.int64)
    atr = probes.atr.to_numpy(dtype=float)
    sides = probes.side.to_numpy(dtype=np.int8)
    ema = probes.ema.to_numpy(dtype=float)
    band = probes.frozen_band.to_numpy(dtype=float)
    is_close = probes.type.eq("close_outside").to_numpy()
    for left in range(0, len(probes), chunk_size):
        right = min(left + chunk_size, len(probes))
        sl = slice(left, right)
        start = starts[sl]
        safe_start = np.minimum(start, len(times) - 1)
        exact = (start < len(times)) & (times[safe_start] == decisions[sl])
        entry = mo[safe_start]
        columns["entry_price"][sl] = np.where(exact, entry, np.nan)
        columns["entry_time"][sl] = np.where(exact, decisions[sl], np.iinfo(np.int64).min).astype("datetime64[ns]")
        offsets = start[:, None] + np.arange(max(HORIZONS))[None, :]
        safe = np.minimum(offsets, len(times) - 1)
        sign, scale = sides[sl, None], atr[sl, None]
        signed_open = sign * (mo[safe] - entry[:, None]) / scale
        cont_extreme = np.where(sign > 0, mh[safe], ml[safe])
        rev_extreme = np.where(sign > 0, ml[safe], mh[safe])
        continuation = sign * (cont_extreme - entry[:, None]) / scale
        reversion = -sign * (rev_extreme - entry[:, None]) / scale
        for horizon in HORIZONS:
            last = start + horizon - 1
            safe_last = np.minimum(last, len(times) - 1)
            length_ok = last < len(times)
            clock_ok = (times[safe_last] - decisions[sl]) == (horizon - 1) * MINUTE_NS
            contract_ok = (ids[safe_start] == pids[sl]) & (changes[safe_last] == changes[safe_start])
            split_ok = decisions[sl] + horizon * MINUTE_NS <= split_ends[sl]
            valid = exact & length_ok & clock_ok & contract_ok & split_ok
            columns[f"complete_{horizon}"][sl] = valid
            reasons = np.select([~exact, ~length_ok, ~clock_ok, ~contract_ok, ~split_ok],
                                ["no_next_minute", "end_of_data", "missing_clock_minute", "contract_roll", "split_boundary"], default="")
            columns[f"incomplete_reason_{horizon}"][sl] = reasons
            signed_ret = sides[sl] * (mc[safe_last] - entry)
            columns[f"ret_points_{horizon}"][sl] = np.where(valid, signed_ret, np.nan)
            columns[f"ret_atr_{horizon}"][sl] = np.where(valid, signed_ret / atr[sl], np.nan)
            rev_max = np.maximum(reversion[:, :horizon].max(axis=1), 0.0)
            cont_max = np.maximum(continuation[:, :horizon].max(axis=1), 0.0)
            columns[f"mfe_reversion_atr_{horizon}"][sl] = np.where(valid, rev_max, np.nan)
            columns[f"mfe_continuation_atr_{horizon}"][sl] = np.where(valid, cont_max, np.nan)
            min_directional_price = np.min(sign * rev_extreme[:, :horizon], axis=1)
            ema_contact = min_directional_price <= sides[sl] * ema[sl]
            band_contact = min_directional_price <= sides[sl] * band[sl]
            columns[f"ema_touch_{horizon}"][sl] = np.where(valid, ema_contact.astype(float), np.nan)
            columns[f"band_return_{horizon}"][sl] = np.where(valid & is_close[sl], band_contact.astype(float), np.nan)
            for distance, code in BARRIERS:
                open_cont = signed_open[:, :horizon] >= distance
                open_rev = signed_open[:, :horizon] <= -distance
                hit_cont = continuation[:, :horizon] >= distance
                hit_rev = reversion[:, :horizon] >= distance
                touched = open_cont | open_rev | hit_cont | hit_rev
                touched_any = touched.any(axis=1)
                first = touched.argmax(axis=1)
                rows = np.arange(right - left)
                # Opening price is chronologically known; otherwise retain dual hit.
                labels = np.select(
                    [open_cont[rows, first], open_rev[rows, first],
                     hit_cont[rows, first] & hit_rev[rows, first], hit_cont[rows, first], hit_rev[rows, first]],
                    ["continuation", "reversion", "ambiguous", "continuation", "reversion"], default="unresolved")
                labels[~touched_any] = "unresolved"
                labels[~valid] = "incomplete"
                columns[f"outcome_{code}_{horizon}"][sl] = labels
    result = pd.DataFrame(columns)
    result["entry_time"] = pd.to_datetime(result.entry_time, utc=True)
    return result


def attach_controls(minutes, bars, events, indices, distance):
    matched = indices >= 0
    # A rare wick candle may close across the EMA. Matching follows its actual
    # close-vs-EMA sign; the hypothetical control outcome follows its breach side.
    # Keep (candle, outcome side) probes separate if the same candle serves both.
    keys = np.column_stack([indices[matched], events.side.to_numpy()[matched]])
    unique = np.unique(keys, axis=0)
    controls = bars.iloc[unique[:, 0]].copy().reset_index()
    controls["side"] = unique[:, 1]
    controls["control_id"] = [f"{events.timeframe.iloc[0]}-{int(i)}-{int(s)}" for i, s in unique]
    controls["frozen_band"] = np.where(controls.side > 0, controls.upper, controls.lower)
    controls["type"] = "control_nonbreach"
    controls["prebar_ema_slope_atr"] = controls.side * controls.slope_raw
    outcomes = minute_outcomes(minutes, controls)
    control_ledger = pd.concat([controls, outcomes], axis=1)
    lookup = control_ledger.set_index(["bar_index", "side"], drop=False)
    selected_columns = ["timestamp", "decision_time", "day", "year", "time_bucket", "split", "instrument_id",
                        "atr", "prebar_atr", "prebar_ema_slope_atr", "ema", "side", "control_id", *outcomes.columns]
    event_keys = pd.MultiIndex.from_arrays([indices, events.side.to_numpy()], names=["bar_index", "side"])
    paired = lookup.reindex(event_keys)[selected_columns].reset_index(drop=True).add_prefix("control_")
    paired = paired.rename(columns={"control_control_id": "control_id"})
    paired["control_bar_index"] = np.where(matched, indices, np.nan)
    paired["control_match_distance"] = distance
    paired["control_matched"] = matched
    # Unmatched strings remain missing, never interpreted as unresolved outcomes.
    return pd.concat([events.reset_index(drop=True), paired], axis=1), control_ledger


def timeframe_audit(bars, events, controls, timeframe):
    groups = {}
    for bucket, subset in bars.groupby("time_bucket", observed=True):
        event_subset = events.loc[events.time_bucket.eq(bucket)]
        groups[bucket] = {
            "chart_bars": len(subset), "partial_chart_bars": int((~subset.complete).sum()),
            "eligible_chart_bars": int(subset.eligible.sum()),
            "dual_breaches_excluded": int((subset.eligible & subset.dual_breach).sum()),
            "all_events": len(event_subset), "episodes": int(event_subset.episode_start.sum()),
            "episodes_matched": int(event_subset.control_matched.sum()),
            "episodes_complete_60": int((event_subset.episode_start & event_subset.complete_60).sum()),
        }
    return {
        "timeframe": f"{timeframe}m", "bars": len(bars),
        "complete_bars": int(bars.complete.sum()), "partial_bars": int((~bars.complete).sum()),
        "eligible_bars": int(bars.eligible.sum()),
        "breaches_before_quality_filter": int((bars.upper_breach | bars.lower_breach).sum()),
        "eligible_dual_breaches_excluded": int((bars.eligible & bars.dual_breach).sum()),
        "events": len(events), "episodes": int(events.episode_start.sum()),
        "first_close_events": int(events.first_close_outside.sum()),
        "matched_episodes": int(events.control_matched.sum()), "unique_control_probes": len(controls),
        "unique_controls": int(controls.bar_index.nunique()),
        "max_control_reuse": int(events.control_bar_index.value_counts().max()) if len(controls) else 0,
        "eligibility_by_time_bucket": groups,
        "incomplete_reasons": {str(h): events[f"incomplete_reason_{h}"].value_counts().to_dict() for h in HORIZONS},
        "outcome_status_counts": {f"{code}_{h}": events[f"outcome_{code}_{h}"].value_counts().to_dict()
                                  for h in HORIZONS for _, code in BARRIERS},
        "bar_label": "UTC candle open; decision_time is candle close and entry-minute open",
        "warmup": "Signal and preceding candle each have at least 100 prior aggregated bars in their contract segment",
        "extension_definition": "close_extension is clipped to zero for inside closes; signed_close_extension_atr also exported",
        "slope_definition": "side * (EMA[t-1] - EMA[t-6]) / ATR[t-1]",
        "control_direction_definition": "Match the actual sign of event close minus event EMA. Control passage direction remains the event breach side. Unique control probes use (bar_index, breach side); all reuses share original calendar date.",
        "wick_events_closing_across_ema": int((events.side.ne(events.close_side)).sum()),
    }


def self_test():
    """Synthetic causality, clock-boundary, gap, roll, and passage-order checks."""
    index = pd.date_range("2024-01-02T14:00:00Z", periods=300, freq="min")
    base = pd.DataFrame({"open": 100., "high": 100.1, "low": 99.9, "close": 100.,
                         "volume": 1, "instrument_id": 1}, index=index)
    probe = pd.DataFrame({"decision_time": [index[10]], "instrument_id": [1],
                          "split_end_ns": [index[-1].value + MINUTE_NS], "atr": [1.], "side": [1],
                          "ema": [99.], "frozen_band": [99.75], "type": ["close_outside"]})
    assert minute_outcomes(base, probe).outcome_05_60.iloc[0] == "unresolved"
    both = base.copy(); both.loc[index[11], ["high", "low"]] = [101., 99.]
    assert minute_outcomes(both, probe).outcome_05_60.iloc[0] == "ambiguous"
    both.loc[index[11], "open"] = 100.6
    assert minute_outcomes(both, probe).outcome_05_60.iloc[0] == "continuation"
    both.loc[index[11], "open"] = 99.4
    assert minute_outcomes(both, probe).outcome_05_60.iloc[0] == "reversion"
    lower_probe = probe.copy(); lower_probe["side"] = -1
    assert minute_outcomes(both, lower_probe).outcome_05_60.iloc[0] == "continuation"
    signal_only = base.copy(); signal_only.loc[index[9], ["high", "low"]] = [200., 1.]
    assert minute_outcomes(signal_only, probe).outcome_05_60.iloc[0] == "unresolved"
    missing = base.drop(index[30])
    missing_result = minute_outcomes(missing, probe)
    assert missing_result.outcome_05_15.iloc[0] == "unresolved"
    assert missing_result.outcome_05_60.iloc[0] == "incomplete"
    rolled = base.copy(); rolled.loc[index[30]:, "instrument_id"] = 2
    assert minute_outcomes(rolled, probe).incomplete_reason_60.iloc[0] == "contract_roll"
    split_probe = probe.copy(); split_probe["split_end_ns"] = index[30].value
    assert minute_outcomes(base, split_probe).incomplete_reason_60.iloc[0] == "split_boundary"
    # A complete 15-minute horizon includes minutes t through t+14 only.
    boundary = base.copy(); boundary.loc[index[25], "high"] = 101.
    assert minute_outcomes(boundary, probe).outcome_05_15.iloc[0] == "unresolved"
    assert minute_outcomes(boundary, probe).outcome_05_60.iloc[0] == "continuation"
    # EMA contact on next-minute entry already beyond the level is a reach/pass.
    contacts = probe.copy(); contacts["ema"] = 100.05
    assert minute_outcomes(base, contacts).ema_touch_60.iloc[0] == 1
    protocol = {"splits_utc": {"development": ["2024-01-01T00:00:00Z", "2025-01-01T00:00:00Z"]},
                "indicator": {"ema_length": 20, "atr_length": 20, "multiplier": 2.25, "warmup_bars_per_contract": 100}}
    long_index = pd.date_range("2024-01-02T00:00:00Z", periods=1200, freq="min")
    long = pd.DataFrame({"open": np.arange(1200)*.01+100, "high": np.arange(1200)*.01+100.2,
                         "low": np.arange(1200)*.01+99.8, "close": np.arange(1200)*.01+100.1,
                         "volume": 1, "instrument_id": 1}, index=long_index)
    a = build_bars(long, 5, protocol)
    mutated = long.copy(); mutated.loc[long_index[900]:, ["open", "high", "low", "close"]] += 1000
    b = build_bars(mutated, 5, protocol)
    pd.testing.assert_frame_equal(a.iloc[:180], b.iloc[:180])
    # EMA and ATR reset at a contract roll rather than inheriting a huge roll gap.
    rolled_long = long.copy(); rolled_long.loc[long_index[600]:, "instrument_id"] = 2
    rolled_long.loc[long_index[600]:, ["open", "high", "low", "close"]] += 1000
    roll_bars = build_bars(rolled_long, 5, protocol)
    assert roll_bars.ema.iloc[120] == roll_bars.close.iloc[120]
    assert np.isnan(roll_bars.atr.iloc[120])
    assert not roll_bars.eligible.iloc[220]
    assert roll_bars.eligible.iloc[221]
    # Current bucket with a missing minute cannot qualify as a signal.
    partial = build_bars(long.drop(long_index[701]), 5, protocol)
    assert not partial.complete.iloc[140] and not partial.eligible.iloc[140]
    # Wide upper-wick event closing below EMA matches a below-EMA control.
    match_bars = pd.DataFrame({"eligible": [True, True, True], "upper_breach": [False, False, True],
                              "lower_breach": [False, False, False], "slope_raw": [0., 0., 0.],
                              "prebar_atr": [1., 1., 1.], "split": ["development"]*3,
                              "time_bucket": ["overnight"]*3, "close_side": [-1, 1, -1]})
    match_events = pd.DataFrame({"episode_start": [True], "bar_index": [2], "side": [1]})
    assert select_controls(match_bars, match_events)[0][0] == 0
    print("Synthetic causality/passage/boundary/roll/completeness checks passed", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    self_test()
    if args.self_test:
        return
    protocol_path = CAMPAIGN / "protocol.json"
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    if not protocol.get("frozen_before_outcomes"):
        raise ValueError("Study protocol must be frozen before outcomes")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    source_hash = sha256(Path(__file__))
    protocol_hash = sha256(protocol_path)
    shutil.copy2(protocol_path, OUTPUT / "protocol.json")
    shutil.copy2(Path(__file__), OUTPUT / "build_events.py")
    minutes, data_audit = load_minutes(protocol)
    minute_splits, _ = split_labels(minutes.index, protocol)
    _, minute_days, _ = time_labels(minutes.index)
    calendar = {name: sorted(set(minute_days[minute_splits == name])) for name in protocol["splits_utc"]}
    (OUTPUT / "calendar.json").write_text(json.dumps(calendar, indent=2), encoding="utf-8")
    audit = {"study_id": protocol["study_id"], "protocol_sha256": protocol_hash,
             "generator_sha256": source_hash, "dataset": data_audit, "timeframes": {},
             "synthetic_checks_passed": True, "python": sys.version,
             "numpy": np.__version__, "pandas": pd.__version__}
    for timeframe in protocol["timeframes_minutes"]:
        print(f"Building {timeframe}m completed-bar features", flush=True)
        bars = build_bars(minutes, timeframe, protocol)
        events = build_event_features(bars, timeframe)
        print(f"Matching earlier controls for {int(events.episode_start.sum()):,} episode events", flush=True)
        indices, distance = select_controls(bars, events)
        print(f"Computing minute outcomes for {len(events):,} breach candles", flush=True)
        outcomes = minute_outcomes(minutes, events)
        events = pd.concat([events, outcomes], axis=1)
        events, controls = attach_controls(minutes, bars, events, indices, distance)
        events.to_parquet(OUTPUT / f"events_{timeframe}m.parquet", index=False)
        controls.to_parquet(OUTPUT / f"controls_{timeframe}m.parquet", index=False)
        events.to_csv(OUTPUT / f"events_{timeframe}m.csv.gz", index=False, compression="gzip")
        controls.to_csv(OUTPUT / f"controls_{timeframe}m.csv.gz", index=False, compression="gzip")
        audit["timeframes"][f"{timeframe}m"] = timeframe_audit(bars, events, controls, timeframe)
        (OUTPUT / "audit.json").write_text(json.dumps(audit, indent=2), encoding="utf-8")
        print(f"Saved {timeframe}m: {len(events):,} events and {len(controls):,} unique controls", flush=True)
    if sha256(protocol_path) != protocol_hash or sha256(Path(__file__)) != source_hash:
        raise ValueError("Protocol or generator changed while running")
    print(f"Finished. Evidence: {OUTPUT}", flush=True)


if __name__ == "__main__":
    main()
