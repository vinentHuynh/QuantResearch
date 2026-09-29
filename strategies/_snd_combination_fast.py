"""Numeric state-machine acceleration of the combination reference engine.

No fixed-ledger filtering: each configuration owns its positions, pending order,
zone usage and context state. Numba is optional for development; BACKEND states
whether the identical numeric loop is compiled. Full reference-shaped output is
the initial public interface. This module does not alter any frozen reference.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from strategies import _snd_combination_reference as reference

try:
    from numba import njit
    BACKEND = "numba"
except ImportError:
    BACKEND = "python-numeric"

    def njit(*args, **kwargs):
        def decorate(function):
            return function
        return decorate


DEFAULTS = reference.DEFAULTS
TRADE_COLUMNS = reference.TRADE_COLUMNS
FORMATION_FEATURES = reference.FORMATION_FEATURES
QUALITY_PARAMETERS = reference.QUALITY_PARAMETERS
MINUTE_NS = reference.MINUTE_NS
prepare_data = reference.prepare_data

COUNTERS = (
    "zones_created", "zone_invalidations", "zones_expired", "zones_discarded_capacity",
    "zone_touches", "physical_first_touches", "first_touches_warmup",
    "first_touches_busy_or_exit", "first_touches_misaligned", "first_touches_incomplete",
    "orders_expired", "room_rejections_at_signal", "room_rejections_at_fill",
    "nonpositive_risk_rejections", "nonpositive_target_rejections", "context_zones_created",
    "context_zone_invalidations", "context_zones_expired", "context_zones_discarded_capacity",
    "entry_orders_armed", "orders_cancelled_bias", "orders_cancelled_zone",
    "ambiguous_entry_count", "ambiguous_exit_count", "entry_bar_targets_ignored",
    "roll_liquidations", "scored_source_rows", "scored_5m_buckets",
    "quality_rejections_at_signal", "quality_missing_rejections_at_signal",
    "max_zone_width_atr_rejections_at_signal", "max_zone_width_atr_missing_at_signal",
    "min_departure_atr_rejections_at_signal", "min_departure_atr_missing_at_signal",
    "min_departure_rvol_rejections_at_signal", "min_departure_rvol_missing_at_signal",
    "max_touch_age_hours_rejections_at_signal", "max_touch_age_hours_missing_at_signal")

# Trade floats are in public column order. Timestamps are stored separately as
# int64 nanoseconds; casting epoch nanoseconds through float loses precision.
TIME_COLUMNS = ("entry_time", "exit_time", "zone_time", "first_touch_time",
                "signal_time", "order_expiry_time")
FLOAT_COLUMNS = tuple(c for c in TRADE_COLUMNS
                      if c not in TIME_COLUMNS + ("exit_reason", "eligibility_policy"))
FLOAT_INDEX = {name: i for i, name in enumerate(FLOAT_COLUMNS)}
REASONS = ("stop", "target", "contract-roll", "end-of-test")


@njit(cache=True)
def _room(side, entry, stop, boundary):
    risk = side * (entry - stop)
    if risk <= 0:
        return -np.inf
    return np.inf if np.isnan(boundary) else max(0.0, side * (boundary - entry)) / risk


@njit(cache=True)
def _target(value, side, tick, epsilon):
    units = value / tick
    if abs(value - round(units) * tick) <= epsilon:
        return value
    ticks = np.floor(units + epsilon / tick) if side == 1 else np.ceil(units - epsilon / tick)
    return float(ticks * tick)


@njit(cache=True)
def _close_trade(price, when, reason, ambiguous, af, at, balance,
                 fee, charged_slip, slip_price, entry_cost, point_value,
                 trade_values, trade_times, reasons, counters):
    before = price
    if reason != 1:
        price -= af[0] * slip_price
    exit_cost = fee + (0.0 if reason == 1 else charged_slip)
    gross = af[0] * (price - af[2]) * point_value
    cost = entry_cost + exit_cost
    balance += gross - exit_cost
    at[1] = when
    af[3], af[8], af[9], af[10] = price, gross, cost, gross - cost
    af[11], af[15], af[27] = (gross - cost) / af[7], 1.0 if ambiguous else 0.0, before
    trade_values.append(af.copy())
    trade_times.append(at.copy())
    reasons.append(reason)
    if ambiguous:
        counters[23] += 1
    return balance


@njit(cache=True, error_model="numpy")
def _simulate(stamps, sp, segments, cstamps, cp, complete, cbias, hbias,
              csegments, begins, stops, features, first_bucket, last_bucket,
              st, en, execution_minutes, capital, tick, point_value, fee,
              slippage_ticks, price_slippage, body, stop_zone, use_htf,
              require_fvg, first_touch, lifetime, max_age, max_active, rr,
              minimum_room, thresholds):
    """Stateful OHLC simulation; numerical operations match reference order."""
    n = len(cstamps)
    counters = np.zeros(len(COUNTERS), dtype=np.int64)
    top = np.zeros(n)
    bottom = np.zeros(n)
    zside = np.zeros(n, dtype=np.int64)
    first_index = np.full(n, -1, dtype=np.int64)
    first_time = np.full(n, -1, dtype=np.int64)
    last_index = np.full(n, -1, dtype=np.int64)
    last_time = np.full(n, -1, dtype=np.int64)
    used = np.zeros(n, dtype=np.bool_)
    invalid = np.zeros(n, dtype=np.bool_)
    touched = np.zeros(n, dtype=np.bool_)
    zones = np.empty(max_active + 1, dtype=np.int64)
    context = np.empty(max_active + 1, dtype=np.int64)
    nz = nc = 0
    trade_values = [np.empty(34, dtype=np.float64)]
    trade_values.pop()
    trade_times = [np.empty(6, dtype=np.int64)]
    trade_times.pop()
    reasons = [np.int64(0)]
    reasons.pop()
    evalues = np.empty((last_bucket - first_bucket + 1, 5), dtype=np.float64)
    etimes = np.empty(last_bucket - first_bucket + 1, dtype=np.int64)
    ne = 0
    af = np.zeros(34)
    at = np.zeros(6, dtype=np.int64)
    active = False
    order_zone = -1
    order_side = 0
    order_trigger = order_stop = order_boundary = order_age = 0.0
    order_signal = order_expiry = np.int64(0)
    balance = capital
    previous_equity = capital
    last_segment = last_source = last_scored = -1
    delta = execution_minutes * MINUTE_NS
    epsilon = tick * 1e-7
    slip_cash = float(slippage_ticks) * tick * point_value
    slip_price = float(slippage_ticks) * tick if price_slippage else 0.0
    charged_slip = 0.0 if price_slippage else slip_cash
    entry_cost = fee + charged_slip

    for i in range(first_bucket, last_bucket):
        bucket_time = cstamps[i]
        scored_bucket = exited_bucket = False
        busy_bucket = active
        if order_zone >= 0 and bucket_time >= order_expiry:
            counters[10] += 1
            order_zone = -1
        if order_zone >= 0 and i - order_zone > max_age:
            counters[21] += 1
            order_zone = -1
        if order_zone >= 0 and use_htf and hbias[i] != order_side:
            counters[20] += 1
            order_zone = -1
        for j in range(begins[i], stops[i]):
            when = stamps[j]
            if when + delta > en:
                break
            if last_segment >= 0 and segments[j] != last_segment:
                if active:
                    balance = _close_trade(sp[last_source, 3], stamps[last_source] + delta,
                        2, False, af, at, balance, fee, charged_slip, slip_price,
                        entry_cost, point_value, trade_values, trade_times, reasons, counters)
                    active = False
                    counters[25] += 1
                    exited_bucket = True
                nz = nc = 0
                order_zone = -1
            last_segment, last_source = segments[j], j
            if when < st:
                continue
            scored_bucket = True
            last_scored = j
            counters[26] += 1
            just_entered = entered_at_open = False
            if not active and order_zone >= 0 and not exited_bucket:
                side, trigger, z = order_side, order_trigger, order_zone
                triggered = sp[j, 1] >= trigger - epsilon if side == 1 else sp[j, 2] <= trigger + epsilon
                invalidated = sp[j, 2] < bottom[z] - epsilon if side == 1 else sp[j, 1] > top[z] + epsilon
                if triggered:
                    before = max(sp[j, 0], trigger) if side == 1 else min(sp[j, 0], trigger)
                    entry = before + side * slip_price
                    stop = order_stop
                    risk = side * (entry - stop)
                    target = _target(entry + side * risk * rr, side, tick, epsilon)
                    room = _room(side, entry, stop, order_boundary)
                    if risk <= 0:
                        counters[13] += 1
                    elif minimum_room != 0 and room + 1e-12 < minimum_room:
                        counters[12] += 1
                    elif side * (target - entry) <= epsilon:
                        counters[14] += 1
                    else:
                        entered_at_open = sp[j, 0] >= trigger - epsilon if side == 1 else sp[j, 0] <= trigger + epsilon
                        af[:] = 0.0
                        af[0], af[1], af[2], af[4], af[5] = side, side, entry, stop, target
                        af[6], af[7] = risk, risk * point_value
                        af[12], af[13], af[14] = top[z], bottom[z], 1.0 if invalidated else 0.0
                        af[17], af[18], af[19], af[20] = execution_minutes, trigger, order_boundary, room
                        af[21], af[22], af[23], af[24] = risk, risk * point_value, rr, side * (target - entry) / risk
                        af[25], af[26], af[33] = lifetime, before, order_age
                        for k in range(5):
                            af[28 + k] = features[z, k]
                        if body:
                            af[30] = (top[z] - bottom[z]) / features[z, 0]
                        at[0], at[2], at[3], at[4], at[5] = when, cstamps[z] + 5 * MINUTE_NS, first_time[z], order_signal, order_expiry
                        active = just_entered = busy_bucket = True
                        balance -= entry_cost
                        used[z] = True
                        if invalidated:
                            counters[22] += 1
                    order_zone = -1
                elif invalidated:
                    invalid[z] = True
                    counters[21] += 1
                    order_zone = -1
            if active:
                side, stop, target = af[0], af[4], af[5]
                stop_hit = sp[j, 2] <= stop + epsilon if side == 1 else sp[j, 1] >= stop - epsilon
                target_hit = sp[j, 1] >= target - epsilon if side == 1 else sp[j, 2] <= target + epsilon
                target_allowed = not just_entered or entered_at_open
                if just_entered and not target_allowed and target_hit:
                    af[16] = 1.0
                    counters[24] += 1
                established = not just_entered or entered_at_open
                stop_gap = established and (sp[j, 0] <= stop + epsilon if side == 1 else sp[j, 0] >= stop - epsilon)
                target_gap = established and (sp[j, 0] >= target - epsilon if side == 1 else sp[j, 0] <= target + epsilon)
                reason = -1
                price = 0.0
                ambiguous = False
                if stop_gap:
                    price, reason = sp[j, 0], 0
                elif target_gap:
                    price, reason = target, 1
                elif stop_hit:
                    price = (min(sp[j, 0], stop) if side == 1 else max(sp[j, 0], stop)) if established else stop
                    reason, ambiguous = 0, target_hit
                elif target_hit and target_allowed:
                    price, reason = target, 1
                if reason >= 0:
                    balance = _close_trade(price, when, reason, ambiguous, af, at, balance,
                        fee, charged_slip, slip_price, entry_cost, point_value,
                        trade_values, trade_times, reasons, counters)
                    active = False
                    exited_bucket = True

        if bucket_time + 5 * MINUTE_NS > en:
            break
        retained = 0
        for q in range(nz):
            z = zones[q]
            overlaps = i > z and cp[i, 2] <= top[z] + epsilon and cp[i, 1] >= bottom[z] - epsilon
            if overlaps:
                hit_time = bucket_time
                for j in range(begins[i], stops[i]):
                    if sp[j, 2] <= top[z] + epsilon and sp[j, 1] >= bottom[z] - epsilon:
                        hit_time = stamps[j]
                        break
                last_index[z], last_time[z] = i, hit_time
            if overlaps and first_index[z] == -1:
                first_index[z], first_time[z] = i, last_time[z]
                counters[5] += 1
                counters[6] += int(first_time[z] < st)
                counters[7] += int(busy_bucket or exited_bucket)
                counters[9] += int(not complete[i])
                counters[8] += int(cbias[i] != zside[z] or (use_htf and hbias[i] != zside[z]))
            bad = invalid[z] or (cp[i, 2] < bottom[z] - epsilon if zside[z] == 1 else cp[i, 1] > top[z] + epsilon)
            if bad:
                counters[1] += 1
            elif i - z > max_age:
                counters[2] += 1
            elif not used[z]:
                if overlaps and not touched[z]:
                    touched[z] = True
                    counters[4] += 1
                zones[retained] = z
                retained += 1
        nz = retained
        if order_zone >= 0 and bucket_time + 5 * MINUTE_NS >= order_expiry:
            counters[10] += 1
            order_zone = -1
        if order_zone >= 0:
            found = False
            for q in range(nz):
                found = found or zones[q] == order_zone
            if not found:
                counters[21] += 1
                order_zone = -1
        retained = 0
        for q in range(nc):
            z = context[q]
            bad = cp[i, 2] < bottom[z] - epsilon if zside[z] == 1 else cp[i, 1] > top[z] + epsilon
            if bad:
                counters[16] += 1
            elif i - z > max_age:
                counters[17] += 1
            else:
                context[retained] = z
                retained += 1
        nc = retained
        if complete[i]:
            bias = cbias[i]
            aligned = bias != 0 and (not use_htf or hbias[i] == bias)
            continuous = (i >= 2 and complete[i - 1] and complete[i - 2]
                          and bucket_time - cstamps[i - 2] == 10 * MINUTE_NS
                          and csegments[i] == csegments[i - 2])
            if continuous:
                long_pattern = (cp[i - 2, 3] < cp[i - 2, 0] and cp[i - 1, 3] > cp[i - 1, 0]
                                and (cp[i, 2] > cp[i - 2, 1] if require_fvg else cp[i, 3] > cp[i - 2, 1]))
                short_pattern = (cp[i - 2, 3] > cp[i - 2, 0] and cp[i - 1, 3] < cp[i - 1, 0]
                                 and (cp[i, 1] < cp[i - 2, 2] if require_fvg else cp[i, 3] < cp[i - 2, 2]))
                side = 1 if long_pattern else (-1 if short_pattern else 0)
                if side != 0:
                    hi0 = max(cp[i - 2, 0], cp[i - 2, 3]) if body else cp[i - 2, 1]
                    hi1 = max(cp[i - 1, 0], cp[i - 1, 3]) if body else cp[i - 1, 1]
                    hi2 = max(cp[i, 0], cp[i, 3]) if body else cp[i, 1]
                    lo0 = min(cp[i - 2, 0], cp[i - 2, 3]) if body else cp[i - 2, 2]
                    lo1 = min(cp[i - 1, 0], cp[i - 1, 3]) if body else cp[i - 1, 2]
                    lo2 = min(cp[i, 0], cp[i, 3]) if body else cp[i, 2]
                    top[i] = hi0 if side == 1 else max(hi0, hi1, hi2)
                    bottom[i] = min(lo0, lo1, lo2) if side == 1 else lo0
                    zside[i] = side
                    context[nc] = i
                    nc += 1
                    counters[15] += 1
                    if nc > max_active:
                        for q in range(nc - 1):
                            context[q] = context[q + 1]
                        nc -= 1
                        counters[18] += 1
                if aligned and side == bias:
                    zones[nz] = i
                    nz += 1
                    counters[0] += 1
                    if nz > max_active:
                        discarded = zones[0]
                        for q in range(nz - 1):
                            zones[q] = zones[q + 1]
                        nz -= 1
                        counters[3] += 1
                        if order_zone == discarded:
                            counters[21] += 1
                            order_zone = -1
            eligible_bucket = scored_bucket and not exited_bucket and not busy_bucket
            if not active and order_zone < 0 and aligned and eligible_bucket:
                for q in range(nz - 1, -1, -1):
                    z = zones[q]
                    fresh = ((first_index[z] == i and first_time[z] >= st) if first_touch
                             else (last_index[z] == i and last_time[z] >= st))
                    if zside[z] == bias and touched[z] and i > z and fresh:
                        trigger = cp[i, 1] + tick if bias == 1 else cp[i, 2] - tick
                        anchor = ((bottom[z] if bias == 1 else top[z]) if stop_zone
                                  else (cp[i, 2] if bias == 1 else cp[i, 1]))
                        stop = anchor - bias * tick
                        if bias * (trigger - stop) > 0:
                            boundary = np.nan
                            for x in range(nc):
                                c = context[x]
                                if zside[c] == bias:
                                    continue
                                if bias == 1 and top[c] >= trigger - epsilon:
                                    if np.isnan(boundary) or bottom[c] < boundary:
                                        boundary = bottom[c]
                                elif bias == -1 and bottom[c] <= trigger + epsilon:
                                    if np.isnan(boundary) or top[c] > boundary:
                                        boundary = top[c]
                            room = _room(bias, trigger, stop, boundary)
                            if minimum_room > 0 and room + 1e-12 < minimum_room:
                                counters[11] += 1
                                continue
                            age = (bucket_time - cstamps[z]) / (60 * MINUTE_NS)
                            failed = missing_any = False
                            for k in range(4):
                                if np.isnan(thresholds[k]):
                                    continue
                                if k == 0:
                                    value = (top[z] - bottom[z]) / features[z, 0] if body else features[z, 2]
                                elif k == 1:
                                    value = features[z, 3]
                                elif k == 2:
                                    value = features[z, 4]
                                else:
                                    value = age
                                missing = not np.isfinite(value)
                                if missing or (value > thresholds[k] if k == 0 or k == 3 else value < thresholds[k]):
                                    failed = True
                                    missing_any = missing_any or missing
                                    counters[30 + 2 * k] += 1
                                    counters[31 + 2 * k] += int(missing)
                            if failed:
                                counters[28] += 1
                                counters[29] += int(missing_any)
                                continue
                            order_zone, order_side = z, bias
                            order_trigger, order_stop, order_boundary, order_age = trigger, stop, boundary, age
                            order_signal = bucket_time + 5 * MINUTE_NS
                            order_expiry = bucket_time + (lifetime + 1) * 5 * MINUTE_NS
                            counters[19] += 1
                            break
        if scored_bucket:
            unrealized = 0.0 if not active else af[0] * (sp[last_scored, 3] - af[2]) * point_value
            marked = balance + unrealized
            etimes[ne] = stamps[last_scored] + delta
            evalues[ne, 0], evalues[ne, 1], evalues[ne, 2] = marked, balance, unrealized
            evalues[ne, 3], evalues[ne, 4] = marked - previous_equity, af[0] if active else 0
            ne += 1
            previous_equity = marked
            counters[27] += 1
    if active and last_scored >= 0:
        balance = _close_trade(sp[last_scored, 3], stamps[last_scored] + delta,
            3, False, af, at, balance, fee, charged_slip, slip_price,
            entry_cost, point_value, trade_values, trade_times, reasons, counters)
    if last_scored >= 0:
        final_when = stamps[last_scored] + delta
        if ne > 0 and etimes[ne - 1] == final_when:
            previous_mark = evalues[ne - 2, 0] if ne > 1 else capital
            evalues[ne - 1, 0], evalues[ne - 1, 1], evalues[ne - 1, 2] = balance, balance, 0.0
            evalues[ne - 1, 3], evalues[ne - 1, 4] = balance - previous_mark, 0.0
        else:
            etimes[ne] = final_when
            evalues[ne, 0], evalues[ne, 1], evalues[ne, 2] = balance, balance, 0.0
            evalues[ne, 3], evalues[ne, 4] = balance - previous_equity, 0.0
            ne += 1
    return trade_values, trade_times, reasons, evalues[:ne], etimes[:ne], counters, balance


def run_model(minute_frame, parameters, start, end, tick_size, point_value,
              fee=2.5, slippage_ticks=1):
    """Reference-compatible full ledger/mark output from the compiled loop."""
    p = {**DEFAULTS, **parameters}
    if isinstance(minute_frame, dict):
        prepared = minute_frame
        if int(p["pivot_len"]) != prepared["pivot_len"]:
            prepared = prepare_data(prepared["source"], int(p["pivot_len"]), prepared["execution_minutes"])
    else:
        prepared = prepare_data(minute_frame, int(p["pivot_len"]), int(p["execution_minutes"]))
    # Execute the reference's exact validation and diagnostic metadata setup on
    # an empty chart, never its simulation loop. Preserve original source and
    # preparation diagnostics, and never mutate the shared prepared frames.
    metadata = reference.run_model({**prepared, "chart": prepared["chart"].iloc[:0]},
                                  parameters, start, end, tick_size, point_value,
                                  fee, slippage_ticks)
    p = metadata["parameters"]
    source, chart = prepared["source"], prepared["chart"]
    start, end = reference._utc(start), reference._utc(end)
    stamps, cstamps = reference._ns(source.index), reference._ns(chart.index)
    warmup = start.value - int(p["warmup_days"]) * 24 * 60 * MINUTE_NS
    first = max(0, int(np.searchsorted(cstamps, warmup, side="left")))
    last = int(np.searchsorted(cstamps, end.value, side="left"))
    if last <= first:
        return metadata
    features = np.column_stack([chart[name].to_numpy(float) if name in chart
                                else np.full(len(chart), np.nan) for name in FORMATION_FEATURES])
    result = _simulate(
        stamps, source[["open", "high", "low", "close"]].to_numpy(float),
        source.segment.to_numpy(np.int64), cstamps,
        chart[["open", "high", "low", "close"]].to_numpy(float),
        chart.complete.to_numpy(bool), chart.bias.to_numpy(np.int64),
        chart.hourly_bias.to_numpy(np.int64), chart.segment.to_numpy(np.int64),
        chart.source_start.to_numpy(np.int64), chart.source_stop.to_numpy(np.int64),
        features, first, last, start.value, end.value, p["execution_minutes"],
        float(p["capital"]), float(tick_size), float(point_value), float(fee),
        float(slippage_ticks), p["slippage_model"] == "price", p["zone_boundary"] == "body",
        p["stop_model"] == "zone", bool(p["use_htf"]), bool(p["require_fvg"]),
        p["entry_eligibility"] == "first_touch", int(p["order_lifetime_bars"]),
        int(p["max_age"]), int(p["max_active"]), float(p["rr"]),
        float(p["min_opposing_room_r"]),
        np.array([np.nan if p[name] is None else p[name] for name in QUALITY_PARAMETERS], dtype=float))
    trade_values, trade_times, reasons, evalues, etimes, counters, balance = result
    from strategies._snd_combination_fast_io import frames_from_arrays
    trades, equity = frames_from_arrays(trade_values, trade_times, reasons, evalues, etimes, p)
    diagnostics = metadata["diagnostics"]
    diagnostics.update({name: int(value) for name, value in zip(COUNTERS, counters)})
    diagnostics["trades"] = len(trades)
    diagnostics["accounting_error"] = float(balance - float(p["capital"]) - trades.net_pnl.sum())
    return dict(trades=trades, equity=equity, diagnostics=diagnostics, parameters=p)
