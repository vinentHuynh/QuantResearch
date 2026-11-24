"""Immediate opening-level scalps on an explicitly ordered trade-event stream.

Research benchmark only: a trigger fills at that observed trade price with zero
modeled latency, not a verified bid/ask execution. Input completeness, queue
position and executable fills are not certified. No historical data is loaded.
"""
from __future__ import annotations

import argparse
from collections import deque
import csv
from datetime import datetime, time, timedelta
import json
import math
from numbers import Integral, Real
from pathlib import Path
from zoneinfo import ZoneInfo


NY = ZoneInfo("America/New_York")
POLICIES = ("all_open", "after_two_minutes", "low_directional_progress")
MAX_ENTRIES = 3
POINT_VALUE = 2.0
LOOKBACK_SECONDS = 120
MAX_PROGRESS = .35


class IncompleteSessionError(ValueError):
    """The required opening reference or deadline execution mark is absent."""
    def __init__(self, message, result):
        super().__init__(message)
        self.result = result


def _timestamp(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Every timestamp must be timezone-aware")
    return value.astimezone(NY)


def _price(value, label="price"):
    if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value) or value <= 0:
        raise ValueError(f"{label} must be finite and positive")
    value = float(value)
    if not math.isclose(value/.25, round(value/.25), rel_tol=0., abs_tol=1e-8):
        raise ValueError(f"{label} must align with the 0.25-point MNQ tick")
    return value


def _normalize(events):
    result, previous, session_date = [], None, None
    for index, row in enumerate(events):
        timestamp, price = _timestamp(row["timestamp"]), _price(row["price"])
        if previous is not None and timestamp < previous:
            raise ValueError("Trade events must be chronological; equal timestamps retain supplied order")
        if session_date is None:
            session_date = timestamp.date()
        if timestamp.date() != session_date:
            raise ValueError("Supply one New York calendar date per call")
        result.append((index, timestamp, price))
        previous = timestamp
    if not result:
        raise ValueError("At least one timestamped trade record is required")
    return result, session_date


def _feature(history, timestamp):
    """History includes the current event and the latest boundary anchor."""
    boundary = timestamp-timedelta(seconds=LOOKBACK_SECONDS)
    current_index, _, current_price = history[-1]
    available = history[0][1] <= boundary
    feature = {"lookback_seconds": LOOKBACK_SECONDS, "current_event_index": current_index,
               "current_timestamp": timestamp.isoformat(), "current_price": current_price,
               "boundary_timestamp": boundary.isoformat(), "anchor_available": available,
               "anchor_event_index": None, "anchor_timestamp": None, "anchor_price": None,
               "anchor_age_seconds": None, "anchor_staleness_seconds": None,
               "range_low": None, "range_high": None, "range_points": None,
               "absolute_progress_points": None, "directional_progress": None,
               "positive_width": False, "low_progress_pass": False}
    if not available:
        return feature
    index, anchor_time, anchor_price = history[0]
    values = [r[2] for r in history]
    low, high = min(values), max(values)
    width, progress = high-low, abs(current_price-anchor_price)
    feature.update(anchor_event_index=index, anchor_timestamp=anchor_time.isoformat(),
                   anchor_price=anchor_price, anchor_age_seconds=(timestamp-anchor_time).total_seconds(),
                   anchor_staleness_seconds=(boundary-anchor_time).total_seconds(),
                   range_low=low, range_high=high, range_points=width,
                   absolute_progress_points=progress, positive_width=width > 0,
                   directional_progress=progress/width if width else None,
                   # Both operands are exact quarter-point multiples. Integer
                   # cross multiplication keeps the inclusive 0.35 boundary
                   # from becoming an accidental floating-point rejection.
                   low_progress_pass=bool(width > 0 and 20*progress <= 7*width))
    return feature


def _policy_reason(policy, timestamp, warmup_at, feature):
    if policy == "all_open":
        return None
    if timestamp < warmup_at:
        return "before_09_32"
    if policy == "after_two_minutes":
        return None
    if not feature["anchor_available"]:
        return "missing_120_second_anchor"
    if not feature["positive_width"]:
        return "zero_observed_range"
    if not feature["low_progress_pass"]:
        return "directional_progress_above_0_35"
    return None


def simulate_session(events, *, trigger_points, target_points, policy="all_open",
                     round_trip_cost_dollars=2.24, deadline_mark=None, contracts=1):
    """Replay one supplied session; never infer unseen intraminute records.

    ``events`` is an iterable of timestamp/price mappings. Timestamps must carry
    a timezone and be nondecreasing; duplicate timestamps retain input order.
    A record in the 09:30 minute is required for the opening reference. Earlier
    records are validated but ignored. All records at/after 09:45 are ignored
    for signals and bracket exits.

    ``deadline_mark`` is an optional mapping containing an exact 09:45 timestamp
    and positive tick-aligned price. It is used only to flatten an open position
    at that clock event, with priority over brackets. It cannot establish a
    previous target/stop touch. Missing it while holding raises
    IncompleteSessionError carrying the incomplete result in ``.result``.

    Entries fill immediately at the observed crossing price, including gaps;
    stops are D/2 away and targets T away from this fill. Later records alone can
    exit. Stop gaps use the adverse observed price; targets receive their stated
    limit with no favorable improvement. After any exit or rejected crossing,
    a subsequent inside-band record must re-arm before a later crossing enters.
    One record can never exit, re-arm and enter again. At most three entries.

    ``contracts`` is a fixed positive whole-number quantity for every position
    in this session. All contracts enter and exit together. The existing
    ``round_trip_cost_dollars`` argument is PER CONTRACT; dollar P&L and costs
    scale with quantity. ``gross_points`` remains the unscaled price move;
    ``contract_points`` records that move times quantity. No depth, market
    impact, partial fills or quantity-dependent slippage is modeled.

    Low-progress context uses the last observed price at/before t-120 seconds
    and the range from that anchor through the current observed record. No
    future record, completed-current-candle value, or assumed intrabar path is
    used. An old anchor across a feed gap remains disclosed, not silently fresh.
    """
    if trigger_points not in (40, 60, 80) or isinstance(trigger_points, bool):
        raise ValueError("trigger_points must be 40, 60 or 80")
    if target_points not in (5, 10, 15) or isinstance(target_points, bool):
        raise ValueError("target_points must be 5, 10 or 15")
    if policy not in POLICIES:
        raise ValueError("Unknown frozen policy")
    if isinstance(contracts, bool) or not isinstance(contracts, Integral) or contracts <= 0:
        raise ValueError("contracts must be a positive whole-number integer")
    contracts = int(contracts)
    if isinstance(round_trip_cost_dollars, bool) or not isinstance(round_trip_cost_dollars, Real) or not math.isfinite(round_trip_cost_dollars) or round_trip_cost_dollars < 0:
        raise ValueError("Round-trip costs must be finite and nonnegative")
    source, session_date = _normalize(events)
    opens_at = datetime.combine(session_date, time(9, 30), NY)
    opening_minute_end = opens_at+timedelta(minutes=1)
    warmup_at, deadline = opens_at+timedelta(minutes=2), opens_at+timedelta(minutes=15)
    result = {"status": "complete", "coverage_status": "unverified_supplied_event_sequence",
              "execution_model": "zero-latency observed-trade-price research benchmark",
              "execution_fills_verified": False, "session_date": str(session_date),
              "policy": policy, "trigger_points": float(trigger_points), "target_points": float(target_points),
              "stop_points": float(trigger_points)/2, "contracts": contracts, "point_value_dollars": POINT_VALUE,
              "max_entries": MAX_ENTRIES, "round_trip_cost_dollars": float(round_trip_cost_dollars),
              "round_trip_cost_per_contract_dollars": float(round_trip_cost_dollars),
              "round_trip_cost_per_position_dollars": float(round_trip_cost_dollars)*contracts,
              "quantity_execution_assumption": "identical observed-price fills; no depth, impact or partial fills",
              "opens_at": opens_at.isoformat(), "deadline": deadline.isoformat(),
              "opening_reference_timestamp": None, "opening_reference_event_index": None,
              "opening_price": None, "entry_count": 0, "trade_count": 0,
              "trades": [], "rejected_crossings": [], "event_audit": [],
              "gross_points": 0., "contract_points": 0., "gross_dollars": 0., "costs_dollars": 0., "net_dollars": 0.,
              "final_position": 0, "final_position_contracts": 0, "pending_position": None, "observed_predeadline_events": 0,
              "ignored_before_open_events": sum(t < opens_at for _, t, _ in source),
              "ignored_at_or_after_deadline_events": sum(t >= deadline for _, t, _ in source),
              "deadline_mark_used": False, "last_predeadline_timestamp": None}
    active_source = [r for r in source if opens_at <= r[1] < deadline]
    if not active_source or active_source[0][1] >= opening_minute_end:
        result.update(status="incomplete", incomplete_reason="missing_09_30_opening_reference")
        raise IncompleteSessionError("A supplied trade in the 09:30 minute is required", result)
    mark_price = None
    if deadline_mark is not None:
        if _timestamp(deadline_mark["timestamp"]) != deadline:
            raise ValueError("Deadline mark must be timestamped exactly 09:45 on this session date")
        mark_price = _price(deadline_mark["price"], "deadline mark")
    first_index, first_time, origin = active_source[0]
    upper, lower = origin+trigger_points, origin-trigger_points
    result.update(opening_reference_timestamp=first_time.isoformat(), opening_reference_event_index=first_index,
                  opening_price=origin, upper_band=upper, lower_band=lower)
    result["event_audit"].append({"event": "opening_reference", "event_index": first_index,
                                  "timestamp": first_time.isoformat(), "price": origin})
    position, armed, previous_price = None, True, None
    history = deque()

    def close_position(index, timestamp, observed_price, fill_price, reason):
        nonlocal position, armed
        trade = dict(position)
        gross_points = trade["side"]*(fill_price-trade["entry_price"])
        contract_points = gross_points*contracts
        cost_dollars = float(round_trip_cost_dollars)*contracts
        trade.update(exit_event_index=index, exit_timestamp=timestamp.isoformat(),
                     observed_exit_price=float(observed_price), exit_price=float(fill_price),
                     exit_reason=reason, gross_points=float(gross_points),
                     contract_points=float(contract_points),
                     gross_dollars=float(contract_points*POINT_VALUE),
                     cost_per_contract_dollars=float(round_trip_cost_dollars),
                     cost_dollars=cost_dollars,
                     net_dollars=float(contract_points*POINT_VALUE-cost_dollars),
                     held_seconds=(timestamp-_timestamp(trade["entry_timestamp"])).total_seconds())
        result["trades"].append(trade)
        result["event_audit"].append({"event": "exit", "event_index": index,
                                      "timestamp": timestamp.isoformat(), "observed_price": float(observed_price),
                                      "fill_price": float(fill_price), "reason": reason,
                                      "entry_number": trade["entry_number"]})
        position, armed = None, False

    for index, timestamp, price in active_source:
        # Ingest every observed record, including held positions and exits.
        history.append((index, timestamp, price))
        boundary = timestamp-timedelta(seconds=LOOKBACK_SECONDS)
        while len(history) > 1 and history[1][1] <= boundary:
            history.popleft()  # Preserve the LAST record at/before the boundary.
        result["observed_predeadline_events"] += 1
        result["last_predeadline_timestamp"] = timestamp.isoformat()
        old_price, previous_price = previous_price, price
        if position is not None:
            assert index > position["entry_event_index"]
            side = position["side"]
            if side*(price-position["stop_price"]) <= 0:
                reason = "stop" if price == position["stop_price"] else "stop_gap"
                close_position(index, timestamp, price, price, reason)
            elif side*(price-position["target_price"]) >= 0:
                close_position(index, timestamp, price, position["target_price"], "target")
            continue  # An exit record cannot also re-arm or enter.
        if result["entry_count"] >= MAX_ENTRIES:
            continue
        if not armed:
            if lower < price < upper:
                armed = True
                result["event_audit"].append({"event": "rearmed", "event_index": index,
                                              "timestamp": timestamp.isoformat(), "price": price})
            continue  # Re-arm requires a later record for a new crossing.
        if old_price is None:
            continue
        side = -1 if old_price < upper <= price else 1 if old_price > lower >= price else 0
        if not side:
            continue
        feature = _feature(history, timestamp)
        rejected = _policy_reason(policy, timestamp, warmup_at, feature)
        crossing = {"event_index": index, "timestamp": timestamp.isoformat(), "price": price,
                    "side": side, "crossed_level": upper if side < 0 else lower,
                    "feature": feature}
        armed = False
        if rejected is not None:
            crossing["reason"] = rejected
            result["rejected_crossings"].append(crossing)
            result["event_audit"].append({"event": "cross_rejected", **crossing})
            continue
        result["entry_count"] += 1
        position = {"entry_number": result["entry_count"], "entry_event_index": index,
                    "entry_timestamp": timestamp.isoformat(), "entry_price": price,
                    "side": side, "contracts": contracts, "crossed_level": crossing["crossed_level"],
                    "target_points": float(target_points), "stop_points": float(trigger_points)/2,
                    "target_price": price+side*target_points, "stop_price": price-side*trigger_points/2,
                    "entry_policy": policy, "entry_feature": feature}
        result["event_audit"].append({"event": "entry", **crossing, "entry_number": result["entry_count"]})
    if position is not None:
        if mark_price is None:
            result.update(status="incomplete", incomplete_reason="missing_exact_09_45_deadline_mark",
                          pending_position=dict(position), final_position=position["side"],
                          final_position_contracts=position["side"]*contracts)
        else:
            close_position(None, deadline, mark_price, mark_price, "deadline_flatten")
            result["deadline_mark_used"] = True
    result["trade_count"] = len(result["trades"])
    for key in ("gross_points", "contract_points", "gross_dollars", "cost_dollars", "net_dollars"):
        destination = "costs_dollars" if key == "cost_dollars" else key
        result[destination] = float(sum(t[key] for t in result["trades"]))
    assert result["entry_count"] <= MAX_ENTRIES
    assert all(t["entry_timestamp"] < result["deadline"] for t in result["trades"])
    if result["status"] == "incomplete":
        raise IncompleteSessionError("An open position needs an explicit exact 09:45 deadline mark", result)
    assert result["entry_count"] == result["trade_count"]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("events_csv", type=Path, help="CSV columns timestamp,price; timezone-aware ISO timestamps")
    parser.add_argument("--trigger", type=int, choices=(40, 60, 80), required=True)
    parser.add_argument("--target", type=int, choices=(5, 10, 15), required=True)
    parser.add_argument("--policy", choices=POLICIES, default="all_open")
    parser.add_argument("--contracts", type=int, default=1, help="Fixed whole-contract quantity per position; default1")
    parser.add_argument("--round-trip-cost", type=float, default=2.24, help="Round-trip dollars PER CONTRACT")
    parser.add_argument("--deadline-timestamp")
    parser.add_argument("--deadline-price", type=float)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if (args.deadline_timestamp is None) != (args.deadline_price is None):
        parser.error("Supply both deadline timestamp and price, or neither")
    with args.events_csv.open(newline="", encoding="utf-8") as stream:
        events = [{"timestamp": r["timestamp"], "price": float(r["price"])} for r in csv.DictReader(stream)]
    mark = None if args.deadline_timestamp is None else {"timestamp": args.deadline_timestamp, "price": args.deadline_price}
    exit_code = 0
    try:
        result = simulate_session(events, trigger_points=args.trigger, target_points=args.target,
                                  policy=args.policy, round_trip_cost_dollars=args.round_trip_cost,
                                  deadline_mark=mark, contracts=args.contracts)
    except IncompleteSessionError as exc:
        result, exit_code = exc.result, 2
    text = json.dumps(result, indent=2, allow_nan=False)
    if args.output:
        args.output.write_text(text+"\n", encoding="utf-8")
    else:
        print(text)
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
