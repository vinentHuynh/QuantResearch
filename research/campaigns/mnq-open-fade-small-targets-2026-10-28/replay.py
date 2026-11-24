"""Audited one-minute OHLC replay for a cash-open distance fade.

This module has no data loading, parameter search, or workbench registration.
Every input row is an observed minute, starting at 09:30 America/New_York.
The caller must establish cash-session membership and complete minute coverage.

Unknown paths are explicit: initial two-band ordering branches are compared by
net points, and stop/target collisions use the declared pessimistic/optimistic
policy. This is a bound on unresolved OHLC ordering, not a causal trade selector.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np


ENTRY_CUTOFF = 15  # Actual entry minute must be strictly before 09:45.
EPS = 1e-9


def _base(mode, trigger, horizon, policy, delay_bars, cost, target_points, stop_points):
    return {
        "mode": mode, "trigger": float(trigger), "horizon": int(horizon),
        "policy": policy, "delay_bars": int(delay_bars),
        "round_trip_cost_points": float(cost),
        "target_points": float(target_points), "stop_points": float(stop_points),
        "filled": False, "status": "no_trigger", "gross_points": 0.0,
        "net_points": 0.0, "entry_idx": None, "exit_idx": None,
        "entry_price": None, "exit_price": None, "side": 0,
        "exit_reason": "no_trigger", "trigger_idx": None,
        "confirmation_idx": None, "deadline_idx": None,
        "entry_at_open": None, "exit_at_open": None,
        "held_minutes": 0.0, "exit_clock_idx": None,
        "direction_ambiguous": False, "entrybar_target_ambiguous": False,
        "bracket_collision": False, "bar0trigger": False,
        "trade_possible": False, "trade_certain": False,
        "stop_price": None, "target_price": None,
        "first_direction": None, "branches": [],
        "deadline_gap_exit": False,
    }


def _finish(record, idx, price, reason, *, at_open=False, deadline_gap=False):
    record = dict(record)
    record["exit_idx"] = int(idx)
    record["exit_price"] = float(price)
    record["exit_reason"] = reason
    record["exit_at_open"] = bool(at_open)
    record["deadline_gap_exit"] = bool(deadline_gap)
    record["exit_clock_idx"] = int(idx) if at_open else int(idx)+1
    record["held_minutes"] = float(record["exit_clock_idx"]-record["entry_idx"])
    record["gross_points"] = float(record["side"]*(price-record["entry_price"]))
    record["net_points"] = record["gross_points"]-record["round_trip_cost_points"]
    record["status"] = "traded"
    return record


def _opening_exit(record, idx, opening, *, deadline=False):
    """Known opening gaps precede all extremes and the scheduled flatten."""
    s, stop, target = record["side"], record["stop_price"], record["target_price"]
    if s*(opening-stop) <= EPS:
        return _finish(record, idx, opening, "stop_gap", at_open=True,
                       deadline_gap=deadline)
    if s*(opening-target) >= -EPS:
        # Omit favorable opening-gap improvement for the target limit.
        return _finish(record, idx, target, "target_gap", at_open=True,
                       deadline_gap=deadline)
    return None


def _bar_exit(record, idx, bar, *, intrabar_entry=False,
              forced_post_entry_target=False):
    s = record["side"]
    stop, target = record["stop_price"], record["target_price"]
    low, high, close = float(bar[2]), float(bar[1]), float(bar[3])
    stop_hit = low <= stop+EPS if s > 0 else high >= stop-EPS
    target_hit = high >= target-EPS if s > 0 else low <= target+EPS
    if stop_hit and target_hit:
        record["bracket_collision"] = True
        if intrabar_entry and not (forced_post_entry_target or s*(close-target) >= -EPS):
            record["entrybar_target_ambiguous"] = True
        is_target = record["policy"] == "favorable"
        return _finish(record, idx, target if is_target else stop,
                       "target_collision" if is_target else "stop_collision")
    if stop_hit:
        return _finish(record, idx, stop, "stop")
    if not target_hit:
        return None
    # The entry-minute favorable extreme may have occurred before the entry.
    # Its close beyond target, or a later opposite-band first hit, proves the
    # target was crossed after entry. An opening entry has no such uncertainty.
    guaranteed = (not intrabar_entry or forced_post_entry_target or
                  s*(close-target) >= -EPS)
    if not guaranteed:
        record["entrybar_target_ambiguous"] = True
        if record["policy"] == "conservative":
            return None
    return _finish(record, idx, target,
                   "target" if guaranteed else "target_entry_ambiguous")


def _branch(bars, template, trigger_idx, side, *, both_first=False):
    r = dict(template, branches=[])
    r["trigger_idx"] = int(trigger_idx)
    r["bar0trigger"] = trigger_idx == 0
    r["side"] = int(side)
    r["first_direction"] = "down" if side > 0 else "up"
    r["status"] = "armed_no_fill"
    r["exit_reason"] = "no_confirmation"
    opening = float(bars[0, 0])
    level = opening-side*r["trigger"]
    entry_idx = None
    if r["mode"] == "touch":
        entry_idx = trigger_idx+r["delay_bars"]
        if entry_idx >= ENTRY_CUTOFF:
            r["exit_reason"] = "entry_cutoff"
            return r
        if r["delay_bars"]:
            entry_price = float(bars[entry_idx, 0])
            at_open = True
        else:
            entry_price = level
            at_open = side*(float(bars[trigger_idx, 0])-level) <= EPS
    else:
        for i in range(trigger_idx, ENTRY_CUTOFF):
            # Strictly back inside the breached level, not necessarily between
            # both bands, and not necessarily on the original side of the open.
            if side*(float(bars[i, 3])-level) > EPS:
                r["confirmation_idx"] = int(i)
                entry_idx = i+1+r["delay_bars"]
                break
        if entry_idx is None:
            return r
        if entry_idx >= ENTRY_CUTOFF:
            r["exit_reason"] = "entry_cutoff"
            return r
        entry_price = float(bars[entry_idx, 0])
        at_open = True
    r.update(filled=True, status="traded", trade_possible=True, trade_certain=True,
             entry_idx=int(entry_idx), entry_price=float(entry_price),
             entry_at_open=bool(at_open), deadline_idx=int(entry_idx+r["horizon"]))
    r["stop_price"] = float(entry_price-side*r["stop_points"])
    r["target_price"] = float(entry_price+side*r["target_points"])
    # A touch gap can already be beyond its nominal-entry stop. This known gap
    # must be resolved before any later favorable extreme in the same minute.
    if at_open:
        result = _opening_exit(r, entry_idx, float(bars[entry_idx, 0]))
        if result is not None:
            return result
    result = _bar_exit(r, entry_idx, bars[entry_idx], intrabar_entry=not at_open,
                       forced_post_entry_target=bool(both_first and
                                                    r["mode"] == "touch" and
                                                    not r["delay_bars"] and
                                                    r["target_points"] <= 2*r["trigger"]+EPS))
    if result is not None:
        return result
    for i in range(entry_idx+1, r["deadline_idx"]+1):
        result = _opening_exit(r, i, float(bars[i, 0]), deadline=i == r["deadline_idx"])
        if result is not None:
            return result
        if i == r["deadline_idx"]:
            return _finish(r, i, float(bars[i, 0]), "time_exit", at_open=True)
        result = _bar_exit(r, i, bars[i])
        if result is not None:
            return result
    raise AssertionError("Every filled trade must close no later than its deadline")


def simulate_day(ohlc: np.ndarray, *, mode: str, trigger: float, horizon: int,
                 policy: str = "conservative", delay_bars: int = 0,
                 round_trip_cost_points: float = 1.12,
                 target_points: float | None = None,
                 stop_points: float | None = None) -> dict[str, Any]:
    """Return a trade or explicit no-trade record for one complete cash day.

    Parameters
    ----------
    ohlc:
        Minute rows in open/high/low/close order, starting at 09:30 ET. At least
        15+horizon rows are required (135 for two hours), so the final possible
        entry minute 09:44 has its 11:44 boundary-open quote.
    mode:
        ``touch`` enters at the first threshold touch; ``confirm`` waits for a
        completed close strictly inside the first breached level then enters
        at the following minute's open.
    delay_bars:
        Zero is baseline. One delays a touch to the following minute's open,
        or adds one minute to the normal confirmation next-open entry.
    policy:
        Conservative/favorable ordering of OHLC ambiguities. A dual-trigger
        bar creates two arm branches, selected by net points including costs.
        ``branches`` retains both records; ``trade_possible`` and
        ``trade_certain`` preserve ambiguous fill counts.
    target_points, stop_points:
        Positive, finite, quarter-point-aligned distances from the nominal
        entry price. Each independently defaults to trigger/2 when omitted.

    All filled trades have fixed stop/target distances from the nominal fill
    price. Stop gaps fill at the opening quote; target gaps retain
    the target price. At the deadline open, a known bracket gap is resolved
    before a remaining position is flattened. No deadline high/low is read.

    Touch entries inside a minute use its START as the holding-clock proxy;
    actual holding can therefore be up to one minute shorter than requested.
    Intrabar exit timestamps are represented by minute completion, while
    ``exit_idx`` identifies the observed bar. Gross/net values are index points.
    """
    if mode not in ("touch", "confirm"):
        raise ValueError("mode must be touch or confirm")
    if policy not in ("conservative", "favorable"):
        raise ValueError("policy must be conservative or favorable")
    if type(delay_bars) is not int or delay_bars not in (0, 1):
        raise ValueError("delay_bars must be 0 or 1")
    if type(horizon) is not int or horizon not in (60, 120):
        raise ValueError("horizon must be 60 or 120")
    if not isinstance(trigger, (int, float)) or not math.isfinite(trigger) or trigger <= 0:
        raise ValueError("trigger must be finite and positive")
    if not math.isclose(trigger/.25, round(trigger/.25), abs_tol=1e-8):
        raise ValueError("trigger must align with the 0.25-point MNQ tick")
    if not math.isfinite(round_trip_cost_points) or round_trip_cost_points < 0:
        raise ValueError("round_trip_cost_points must be finite and nonnegative")
    distances = {}
    for name, value in (("target_points", target_points), ("stop_points", stop_points)):
        value = trigger/2 if value is None else value
        if (isinstance(value, (bool, np.bool_)) or
                not isinstance(value, (int, float, np.number)) or
                not math.isfinite(value) or value <= 0):
            raise ValueError(f"{name} must be finite and positive")
        if not math.isclose(float(value)/.25, round(float(value)/.25),
                            rel_tol=0., abs_tol=1e-8):
            raise ValueError(f"{name} must align with the 0.25-point MNQ tick")
        distances[name] = float(value)
    bars = np.asarray(ohlc, dtype=float)
    if bars.ndim != 2 or bars.shape[1] != 4 or len(bars) < ENTRY_CUTOFF+horizon:
        raise ValueError("Expected complete minute OHLC with at least 15+horizon rows")
    if not np.isfinite(bars).all():
        raise ValueError("OHLC values must be finite")
    if np.any(bars[:, 1] < bars[:, [0, 2, 3]].max(axis=1)-EPS) or np.any(
            bars[:, 2] > bars[:, [0, 1, 3]].min(axis=1)+EPS):
        raise ValueError("Invalid OHLC ordering")
    template = _base(mode, trigger, horizon, policy, delay_bars,
                     round_trip_cost_points, **distances)
    origin = float(bars[0, 0])
    upper, lower = origin+trigger, origin-trigger
    for i in range(ENTRY_CUTOFF):
        op, hi, lo = (float(v) for v in bars[i, :3])
        if op >= upper-EPS:
            return _branch(bars, template, i, -1)
        if op <= lower+EPS:
            return _branch(bars, template, i, 1)
        hit_upper, hit_lower = hi >= upper-EPS, lo <= lower+EPS
        if hit_upper and hit_lower:
            branches = [_branch(bars, template, i, side, both_first=True)
                        for side in (-1, 1)]
            choose = min if policy == "conservative" else max
            selected = choose(branches, key=lambda r: (r["net_points"],
                                                       r["gross_points"]))
            result = dict(selected)
            result.update(direction_ambiguous=True,
                          trade_possible=any(b["filled"] for b in branches),
                          trade_certain=all(b["filled"] for b in branches),
                          branches=branches)
            return result
        if hit_upper or hit_lower:
            return _branch(bars, template, i, -1 if hit_upper else 1)
    return template
