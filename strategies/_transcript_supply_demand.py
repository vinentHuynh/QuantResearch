"""Isolated, causal research implementation of the supplied S/D transcript.

This deliberately does not replace the repository's older SND strategy. Prices
are unadjusted source prices; commission and adverse slippage are cash charges.
Intervals are half open [start, end), and bar timestamps denote their opens.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from strategy_engine.sessions import get_session


MINUTE_NS = 60_000_000_000
DEFAULTS = dict(pivot_len=2, stop_model="zone", rr=1.0, use_htf=True,
                require_fvg=True, max_age=288, max_active=100,
                execution_minutes=1, warmup_days=30, capital=100_000.0)
TRADE_COLUMNS = ["entry_time", "exit_time", "side", "quantity", "entry", "exit",
                 "stop", "target", "risk", "risk_cash", "gross_pnl", "cost",
                 "net_pnl", "net_r", "exit_reason", "zone_time", "zone_top",
                 "zone_bottom", "ambiguous_entry", "ambiguous_exit",
                 "entry_bar_target_ignored", "execution_minutes"]


def _utc(value):
    stamp = pd.Timestamp(value)
    return stamp.tz_localize("UTC") if stamp.tz is None else stamp.tz_convert("UTC")


def _ns(index):
    return index.as_unit("ns").asi8


def _structure(frame, pivot_len=2):
    """Strict symmetric pivots, available only after right-hand bars close.

    A newly confirmed swing replaces the prior swing of that side. Each swing
    can cause one close-confirmed break. A roll resets every piece of state.
    """
    size = len(frame)
    out = np.zeros(size, dtype=np.int8)
    if not size:
        return out
    p = int(pivot_len)
    if p < 1:
        raise ValueError("pivot_len must be positive")
    high, low, close = (frame[x].to_numpy(float) for x in ("high", "low", "close"))
    segments = frame.segment.to_numpy(np.int64)
    swing_high = swing_low = np.nan
    high_used = low_used = False
    bias, segment_begin = 0, 0
    # Strict comparisons also reject equal highs/lows, avoiding platform pivot
    # tie-breaking differences. The loop has O(N * pivot_len) work.
    for i in range(size):
        if i == 0 or segments[i] != segments[i - 1]:
            swing_high = swing_low = np.nan
            high_used = low_used = False
            bias, segment_begin = 0, i
        if i - segment_begin >= 2 * p:
            c = i - p
            candidate_high, candidate_low = high[c], low[c]
            is_high = is_low = True
            for j in range(c - p, i + 1):
                if j != c:
                    is_high &= candidate_high > high[j]
                    is_low &= candidate_low < low[j]
            if is_high:
                swing_high, high_used = candidate_high, False
            if is_low:
                swing_low, low_used = candidate_low, False
        if not high_used and close[i] > swing_high:
            bias, high_used = 1, True
        if not low_used and close[i] < swing_low:
            bias, low_used = -1, True
        out[i] = bias
    return out


def _aggregate(source, width, execution_minutes):
    """Keep observed buckets, flag incomplete ones, and retain fill mappings."""
    stamps = _ns(source.index)
    keys = stamps // (width * MINUTE_NS) * (width * MINUTE_NS)
    starts = np.r_[0, np.flatnonzero(keys[1:] != keys[:-1]) + 1]
    stops = np.r_[starts[1:], len(source)]
    segments = source.segment.to_numpy(np.int64)
    opens, highs, lows, closes = (source[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    counts = stops - starts
    first_segments, last_segments = segments[starts], segments[stops - 1]
    complete = ((counts == width // execution_minutes) &
                (stamps[starts] == keys[starts]) &
                (stamps[stops - 1] + execution_minutes * MINUTE_NS == keys[starts] + width * MINUTE_NS) &
                (first_segments == last_segments))
    return pd.DataFrame({"open": opens[starts], "high": np.maximum.reduceat(highs, starts),
                         "low": np.minimum.reduceat(lows, starts), "close": closes[stops - 1],
                         "source_start": starts, "source_stop": stops,
                         "source_count": counts, "complete": complete,
                         "segment": last_segments,
                         "crosses_roll": first_segments != last_segments},
                        index=pd.to_datetime(keys[starts], utc=True))


def prepare_data(minute_frame, pivot_len=2, execution_minutes=1):
    """Prepare once and reuse across experiments; never mutate the input.

    Returns a dictionary with source, chart (all observed 5m buckets), hourly
    (complete 1h bars), pivot_len, execution_minutes and diagnostics. Chart
    ``complete`` must be true to make decisions; ``source_start/source_stop``
    map each bucket to the original-resolution candles used for execution.
    Native 5m source is supported, explicitly retaining its larger ambiguity.
    """
    if int(execution_minutes) not in (1, 5):
        raise ValueError("execution_minutes must be 1 or 5")
    execution_minutes = int(execution_minutes)
    frame = minute_frame.copy()
    frame.columns = [str(x).lower() for x in frame.columns]
    if not isinstance(frame.index, pd.DatetimeIndex):
        timestamp = next((k for k in ("ts_event", "timestamp", "datetime", "date", "event_time") if k in frame), None)
        if timestamp is None:
            raise ValueError("A DatetimeIndex or timestamp column is required")
        frame.index = pd.to_datetime(frame.pop(timestamp), utc=True)
    elif frame.index.tz is None:
        frame.index = frame.index.tz_localize("UTC")
    else:
        frame.index = frame.index.tz_convert("UTC")
    if frame.empty or not frame.index.is_unique or not frame.index.is_monotonic_increasing:
        raise ValueError("Source must be nonempty with sorted, unique timestamps")
    if (_ns(frame.index) % (execution_minutes * MINUTE_NS)).any():
        raise ValueError("Source timestamps must align with the declared resolution")
    required = ["open", "high", "low", "close"]
    if any(k not in frame for k in required):
        raise ValueError("Source is missing OHLC columns")
    prices = frame[required].to_numpy(float)
    if not np.isfinite(prices).all() or (prices[:, 1] < prices.max(axis=1)).any() or (prices[:, 2] > prices.min(axis=1)).any():
        raise ValueError("Source contains nonfinite or invalid OHLC prices")
    session = get_session("full-trading-day")
    local = frame.index.tz_convert(session.timezone)
    minutes = local.hour * 60 + local.minute
    opening = session.opens_at.hour * 60 + session.opens_at.minute
    closing = session.closes_at.hour * 60 + session.closes_at.minute
    trading_date = local.tz_localize(None).normalize() + pd.to_timedelta((minutes >= opening).astype(int), unit="D")
    allowed = ((minutes >= opening) | (minutes < closing)) & (trading_date.dayofweek < 5)
    excluded = int((~allowed).sum())
    frame = frame.loc[allowed].copy()
    if frame.empty:
        raise ValueError("No source bars in full-trading-day session")
    contract_column = next((k for k in ("instrument_id", "contract", "symbol") if k in frame and frame[k].notna().any()), None)
    if contract_column:
        # Missing metadata does not create an artificial contract transition.
        ids = frame[contract_column].ffill().astype(str).to_numpy()
        changes = np.r_[False, ids[1:] != ids[:-1]]
    else:
        changes = np.zeros(len(frame), dtype=bool)
    frame["segment"] = np.cumsum(changes).astype(np.int64)
    chart = _aggregate(frame, 5, execution_minutes)
    hourly_all = _aggregate(frame, 60, execution_minutes)
    hourly = hourly_all.loc[hourly_all.complete].copy()
    hourly["bias"] = _structure(hourly, pivot_len)
    chart["bias"] = 0
    valid = chart.complete.to_numpy()
    chart.loc[valid, "bias"] = _structure(chart.loc[valid], pivot_len)
    completed = _ns(hourly.index) + 60 * MINUTE_NS
    lookup = np.searchsorted(completed, _ns(chart.index), side="right") - 1
    htf = np.zeros(len(chart), dtype=np.int8)
    if len(hourly):
        safe = np.maximum(lookup, 0)
        # Use the contract present at the OPEN, not the final contract of a
        # bucket that happens to contain a later roll.
        opening_segments = frame.segment.to_numpy()[chart.source_start.to_numpy(int)]
        same_contract = hourly.segment.to_numpy()[safe] == opening_segments
        usable = (lookup >= 0) & same_contract
        htf[usable] = hourly.bias.to_numpy()[safe[usable]]
    chart["hourly_bias"] = htf
    diagnostics = dict(source_rows=len(frame), excluded_session_rows=excluded,
                       observed_5m_buckets=len(chart), complete_5m_bars=int(valid.sum()),
                       incomplete_5m_buckets=int((~valid).sum()), complete_hourly_bars=len(hourly),
                       incomplete_hourly_buckets=int((~hourly_all.complete).sum()),
                       contract_metadata=contract_column, detected_rolls=int(changes.sum()),
                       bars_crossing_roll=int(chart.crosses_roll.sum()),
                       execution_minutes=execution_minutes,
                       source_gaps=int((np.diff(_ns(frame.index)) > execution_minutes * MINUTE_NS).sum()),
                       partial_bar_policy="No decisions on incomplete 5m/hour bars; risk executes on all available source bars.")
    return dict(source=frame, chart=chart, hourly=hourly, pivot_len=int(pivot_len),
                execution_minutes=execution_minutes, diagnostics=diagnostics)


def run_model(minute_frame, parameters, start, end, tick_size, point_value,
              fee=2.5, slippage_ticks=1):
    """Execute one fixed contract with explicit source-candle chronology.

    ``end`` is exclusive, including when supplied as a date-only string. Supply
    at least 30 preceding calendar days for warmup; insufficient coverage is
    reported. A prepared dictionary from ``prepare_data`` avoids reaggregation.
    Costs are per side. Targets pay commission only, stops/market orders also
    pay the specified adverse slippage in cash, without distorting price risk.
    """
    p = {**DEFAULTS, **parameters}
    if p["stop_model"] not in ("zone", "candle") or p["rr"] <= 0:
        raise ValueError("stop_model must be zone/candle and rr must be positive")
    if tick_size <= 0 or point_value <= 0 or fee < 0 or slippage_ticks < 0:
        raise ValueError("Invalid contract economics")
    if int(p["max_age"]) < 1 or not 1 <= int(p["max_active"]) <= 100:
        raise ValueError("max_age must be positive and max_active must be 1..100")
    start, end = _utc(start), _utc(end)
    if end <= start:
        raise ValueError("end must follow start")
    if isinstance(minute_frame, dict):
        prepared = minute_frame
        if "execution_minutes" in parameters and int(parameters["execution_minutes"]) != prepared["execution_minutes"]:
            raise ValueError("Prepared source resolution disagrees with parameters")
        if int(p["pivot_len"]) != prepared["pivot_len"]:
            prepared = prepare_data(prepared["source"], int(p["pivot_len"]), prepared["execution_minutes"])
    else:
        prepared = prepare_data(minute_frame, int(p["pivot_len"]), int(p["execution_minutes"]))
    source, chart = prepared["source"], prepared["chart"]
    execution_minutes = prepared["execution_minutes"]
    delta_ns = execution_minutes * MINUTE_NS
    st, en = start.value, end.value
    stamps, chart_stamps = _ns(source.index), _ns(chart.index)
    warmup = st - int(p["warmup_days"]) * 24 * 60 * MINUTE_NS
    # Indicators are prepared on the supplied history. The strategy lifecycle
    # starts at the requested warmup boundary; scored positions begin flat.
    first_bucket = max(0, int(np.searchsorted(chart_stamps, warmup, side="left")))
    last_bucket = int(np.searchsorted(chart_stamps, en, side="left"))
    so, sh, sl, sc = (source[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    segments = source.segment.to_numpy(np.int64)
    co, ch, cl, cc = (chart[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    complete = chart.complete.to_numpy(bool)
    chart_bias, hourly_bias = chart.bias.to_numpy(int), chart.hourly_bias.to_numpy(int)
    chart_segments = chart.segment.to_numpy(np.int64)
    begins, stops = chart.source_start.to_numpy(int), chart.source_stop.to_numpy(int)
    slip_cash = float(slippage_ticks) * tick_size * point_value
    entry_cost = fee + slip_cash
    # Decimal futures ticks (for example 0.1) are not exact binary floats.
    # This tolerance is far smaller than one tick and only resolves arithmetic
    # noise at mathematically equal trigger, bracket and zone boundaries.
    price_epsilon = float(tick_size) * 1e-7
    diagnostics = {**prepared["diagnostics"], "zones_created": 0, "zone_invalidations": 0,
                   "zones_expired": 0, "zones_discarded_capacity": 0, "zone_touches": 0,
                   "entry_orders_armed": 0, "orders_cancelled_bias": 0,
                   "ambiguous_entry_count": 0, "ambiguous_exit_count": 0,
                   "entry_bar_targets_ignored": 0, "roll_liquidations": 0,
                   "scored_source_rows": 0, "scored_5m_buckets": 0,
                   "insufficient_warmup": bool(stamps[0] > warmup),
                   "start_inclusive": start.isoformat(), "end_exclusive": end.isoformat(),
                   "warmup_days_requested": int(p["warmup_days"]),
                   "warmup_trades": "No warmup fills; structure, zones and touches initialize before flat scoring start.",
                   "roll_policy": "Contract transitions flatten at prior source close and reset zones/structure; prior-close roll liquidation is an idealized data adjustment, not an executable roll-timing signal.",
                   "sizing": "one fixed contract", "fee_per_side": fee,
                   "slippage_ticks_per_market_or_stop_side": slippage_ticks}
    zones, trades, equity = [], [], []
    active = order = None
    balance = float(p["capital"])
    last_segment = None
    last_source = None
    last_scored_source = None
    previous_equity = balance

    def finish(price, when, reason, ambiguous=False):
        nonlocal active, balance
        exit_cost = fee + (0.0 if reason == "target" else slip_cash)
        gross = active["side"] * (price - active["entry"]) * point_value
        cost = entry_cost + exit_cost
        balance += gross - exit_cost  # Entry cash cost was charged at entry.
        active.update(exit_time=pd.Timestamp(when, tz="UTC"), exit=float(price),
                      gross_pnl=gross, cost=cost, net_pnl=gross - cost,
                      net_r=(gross - cost) / active["risk_cash"],
                      exit_reason=reason, ambiguous_exit=bool(ambiguous))
        trades.append(active)
        if ambiguous:
            diagnostics["ambiguous_exit_count"] += 1
        active = None

    for i in range(first_bucket, last_bucket):
        bucket_time = chart_stamps[i]
        scored_bucket = False
        exited_bucket = False
        if order is not None and i - order["zone"]["created_index"] > int(p["max_age"]):
            order = None
        # The latest closed hour becomes available at this chart bar's open.
        # A cancellation preserves the zone's touched state for later rearming.
        if order is not None and p["use_htf"] and hourly_bias[i] != order["side"]:
            diagnostics["orders_cancelled_bias"] += 1
            order = None
        for j in range(begins[i], stops[i]):
            when = stamps[j]
            if when + delta_ns > en:
                break
            if last_segment is not None and segments[j] != last_segment:
                if active is not None:
                    finish(sc[last_source], stamps[last_source] + delta_ns, "contract-roll")
                    diagnostics["roll_liquidations"] += 1
                    exited_bucket = True
                zones, order = [], None
            last_segment, last_source = segments[j], j
            if when < st:
                continue
            scored_bucket = True
            last_scored_source = j
            diagnostics["scored_source_rows"] += 1
            just_entered = False
            entered_at_open = False
            if active is None and order is not None and not exited_bucket:
                side, trigger, zone = order["side"], order["trigger"], order["zone"]
                triggered = sh[j] >= trigger - price_epsilon if side == 1 else sl[j] <= trigger + price_epsilon
                invalidated = sl[j] < zone["bottom"] - price_epsilon if side == 1 else sh[j] > zone["top"] + price_epsilon
                if triggered:
                    entry = max(so[j], trigger) if side == 1 else min(so[j], trigger)
                    stop = order["stop"]
                    risk = side * (entry - stop)
                    if risk > 0:
                        entered_at_open = so[j] >= trigger - price_epsilon if side == 1 else so[j] <= trigger + price_epsilon
                        active = dict(entry_time=pd.Timestamp(when, tz="UTC"), side=side,
                                      quantity=side, entry=entry, stop=stop,
                                      target=entry + side * risk * float(p["rr"]),
                                      risk=risk, risk_cash=risk * point_value,
                                      zone_time=pd.Timestamp(zone["created_time"], tz="UTC"),
                                      zone_top=zone["top"], zone_bottom=zone["bottom"],
                                      ambiguous_entry=bool(invalidated), ambiguous_exit=False,
                                      entry_bar_target_ignored=False,
                                      execution_minutes=execution_minutes)
                        balance -= entry_cost
                        just_entered = True
                        zone["used"] = True
                        if invalidated:
                            diagnostics["ambiguous_entry_count"] += 1
                    order = None
                elif invalidated:
                    zone["invalid"] = True
                    order = None
            if active is not None:
                side, stop, target = active["side"], active["stop"], active["target"]
                stop_hit = sl[j] <= stop + price_epsilon if side == 1 else sh[j] >= stop - price_epsilon
                target_hit = sh[j] >= target - price_epsilon if side == 1 else sl[j] <= target + price_epsilon
                # A minute that triggers intrabar cannot prove its favorable
                # extreme occurred after entry. Adverse stops remain possible.
                target_allowed = not just_entered or entered_at_open
                if just_entered and not target_allowed and target_hit:
                    active["entry_bar_target_ignored"] = True
                    diagnostics["entry_bar_targets_ignored"] += 1
                established_at_open = not just_entered or entered_at_open
                stop_gap = established_at_open and (so[j] <= stop + price_epsilon if side == 1 else so[j] >= stop - price_epsilon)
                target_gap = established_at_open and (so[j] >= target - price_epsilon if side == 1 else so[j] <= target + price_epsilon)
                # The open precedes both extremes. A target already marketable
                # at that open must exit before a later adverse wick. Favorable
                # limit gaps conservatively receive the limit, not improvement.
                if stop_gap:
                    finish(so[j], when, "stop")
                    exited_bucket = True
                elif target_gap:
                    finish(target, when, "target")
                    exited_bucket = True
                elif stop_hit:
                    # On intrabar entry the source open occurred before entry;
                    # it cannot be used as the stop fill. Established brackets
                    # and entries at the open do incur adverse opening gaps.
                    price = (min(so[j], stop) if side == 1 else max(so[j], stop)) if not just_entered or entered_at_open else stop
                    finish(price, when, "stop", ambiguous=target_hit)
                    exited_bucket = True
                elif target_hit and target_allowed:
                    finish(target, when, "target")
                    exited_bucket = True
        if bucket_time + 5 * MINUTE_NS > en:
            break
        # Every observed wick can invalidate a zone even when this source bucket
        # lacks enough candles to serve as a valid setup/structure candle.
        retained = []
        for zone in zones:
            invalid = zone["invalid"] or (cl[i] < zone["bottom"] - price_epsilon if zone["side"] == 1 else ch[i] > zone["top"] + price_epsilon)
            if invalid:
                diagnostics["zone_invalidations"] += 1
            elif i - zone["created_index"] > int(p["max_age"]):
                diagnostics["zones_expired"] += 1
            elif not zone["used"]:
                if complete[i] and i > zone["created_index"] and not zone["touched"] and cl[i] <= zone["top"] + price_epsilon and ch[i] >= zone["bottom"] - price_epsilon:
                    zone["touched"] = True
                    diagnostics["zone_touches"] += 1
                retained.append(zone)
        zones, order = retained, None
        if complete[i]:
            bias = chart_bias[i]
            aligned = bias != 0 and (not p["use_htf"] or hourly_bias[i] == bias)
            continuous_three = (i >= 2 and complete[i - 1] and complete[i - 2] and
                                bucket_time - chart_stamps[i - 2] == 10 * MINUTE_NS and
                                chart_segments[i] == chart_segments[i - 2])
            if aligned and continuous_three:
                long_pattern = (cc[i - 2] < co[i - 2] and cc[i - 1] > co[i - 1] and
                                (cl[i] > ch[i - 2] if p["require_fvg"] else cc[i] > ch[i - 2]))
                short_pattern = (cc[i - 2] > co[i - 2] and cc[i - 1] < co[i - 1] and
                                 (ch[i] < cl[i - 2] if p["require_fvg"] else cc[i] < cl[i - 2]))
                if (bias == 1 and long_pattern) or (bias == -1 and short_pattern):
                    top = ch[i - 2] if bias == 1 else max(ch[i - 2:i + 1])
                    bottom = min(cl[i - 2:i + 1]) if bias == 1 else cl[i - 2]
                    zones.append(dict(side=bias, top=top, bottom=bottom,
                                      created_index=i, created_time=bucket_time + 5 * MINUTE_NS,
                                      touched=False, used=False, invalid=False))
                    diagnostics["zones_created"] += 1
                    if len(zones) > int(p["max_active"]):
                        del zones[0]
                        diagnostics["zones_discarded_capacity"] += 1
            # Rolling break-of-candle stop entries, latest eligible zone first.
            # A zone may retain its original touch while bias temporarily differs.
            if active is None and aligned:
                for zone in reversed(zones):
                    if zone["side"] == bias and zone["touched"] and i > zone["created_index"]:
                        trigger = ch[i] + tick_size if bias == 1 else cl[i] - tick_size
                        anchor = (zone["bottom"] if bias == 1 else zone["top"]) if p["stop_model"] == "zone" else (cl[i] if bias == 1 else ch[i])
                        stop = anchor - bias * tick_size
                        if bias * (trigger - stop) > 0:
                            order = dict(side=bias, trigger=trigger, stop=stop, zone=zone)
                            diagnostics["entry_orders_armed"] += 1
                            break
        if scored_bucket:
            unrealized = 0.0 if active is None else active["side"] * (sc[last_scored_source] - active["entry"]) * point_value
            marked = balance + unrealized
            equity.append(dict(timestamp=pd.Timestamp(stamps[last_scored_source] + delta_ns, tz="UTC"),
                               equity=marked, balance=balance, unrealized_pnl=unrealized,
                               net_pnl=marked - previous_equity,
                               contracts=0 if active is None else active["side"]))
            previous_equity = marked
            diagnostics["scored_5m_buckets"] += 1
    if active is not None and last_scored_source is not None:
        j = last_scored_source
        finish(sc[j], stamps[j] + delta_ns, "end-of-test")
    if last_scored_source is not None:
        final_when = pd.Timestamp(stamps[last_scored_source] + delta_ns, tz="UTC")
        # The final marked row must reconcile exactly to realized trade PnL.
        if equity and equity[-1]["timestamp"] == final_when:
            previous_mark = equity[-2]["equity"] if len(equity) > 1 else float(p["capital"])
            equity[-1].update(equity=balance, balance=balance, unrealized_pnl=0.0,
                              net_pnl=balance - previous_mark, contracts=0)
        else:
            equity.append(dict(timestamp=final_when, equity=balance, balance=balance,
                               unrealized_pnl=0.0, net_pnl=balance - previous_equity, contracts=0))
    trade_frame = pd.DataFrame(trades, columns=TRADE_COLUMNS)
    equity_frame = pd.DataFrame(equity, columns=["timestamp", "equity", "balance", "unrealized_pnl", "net_pnl", "contracts"])
    diagnostics["trades"] = len(trade_frame)
    diagnostics["accounting_error"] = float(balance - float(p["capital"]) - trade_frame.net_pnl.sum())
    return dict(trades=trade_frame, equity=equity_frame, diagnostics=diagnostics,
                parameters={**p, "execution_minutes": execution_minutes})


def fvg_fill_study(prepared, horizon_hours=72):
    """Descriptive all-FVG fill study, separate from strategy profitability.

    A full fill reaches the first candle's wick after gap confirmation. Events
    crossing a contract roll or the data end before their deadline are censored.
    Missing source intervals remain a limitation: unobserved touches are unknown.
    """
    chart = prepared["chart"]
    stamps, segment = _ns(chart.index), chart.segment.to_numpy(np.int64)
    hi, lo = chart.high.to_numpy(float), chart.low.to_numpy(float)
    complete = chart.complete.to_numpy(bool)
    horizon = int(float(horizon_hours) * 60 * MINUTE_NS)
    records = []
    if len(chart) < 4:
        return pd.DataFrame(records)
    segment_ends = np.r_[np.flatnonzero(segment[1:] != segment[:-1]), len(chart) - 1]
    final_by_segment = {int(segment[i]): stamps[i] + 5 * MINUTE_NS for i in segment_ends}
    for i in range(2, len(chart) - 1):
        if not complete[i - 2:i + 1].all() or stamps[i] - stamps[i - 2] != 10 * MINUTE_NS or segment[i] != segment[i - 2]:
            continue
        side = 1 if lo[i] > hi[i - 2] else (-1 if hi[i] < lo[i - 2] else 0)
        if not side:
            continue
        confirmed = stamps[i] + 5 * MINUTE_NS
        deadline = confirmed + horizon
        observed_until = final_by_segment[int(segment[i])]
        censored = observed_until < deadline
        stop = int(np.searchsorted(stamps, min(deadline, observed_until), side="left"))
        distal = hi[i - 2] if side == 1 else lo[i - 2]
        hits = np.flatnonzero(lo[i + 1:stop] <= distal if side == 1 else hi[i + 1:stop] >= distal)
        filled = bool(len(hits))
        fill_index = i + 1 + int(hits[0]) if filled else None
        records.append(dict(confirmation_time=pd.Timestamp(confirmed, tz="UTC"), side=side,
                            horizon_hours=float(horizon_hours), full_fill=filled,
                            censored=bool(censored), eligible=not censored,
                            hours_to_fill=(stamps[fill_index] + 5 * MINUTE_NS - confirmed) / (60 * MINUTE_NS) if filled else np.nan))
    return pd.DataFrame(records)
