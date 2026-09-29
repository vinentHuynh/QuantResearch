"""Isolated S/D combination research with stateful whole-contract risk sizing.

Fixed-one defaults reproduce the combination reference. Body geometry and causal
quality gates are applied before whole-contract sizing at each eligible signal. Entry eligibility
and order lifetime are independent: first-touch or any physical touch, and a
fixed number of elapsed five-minute buckets. Live orders retain their original
trigger, stop, opposing boundary and expiry; missing buckets consume lifetime.
Cash slippage preserves baseline execution. Price slippage instead worsens
market/stop fills and recomputes entry risk, targets and room using actual fills.
These are idealized OHLC stresses, possibly outside the observed bar range,
not a tick/queue simulation. Targets remain exact limit fills. Roll liquidation
at the prior source close remains an idealized adjustment. Intervals are half
open [start, end), and source timestamps denote bar opens.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import hashlib

from strategy_engine.sessions import get_session


MINUTE_NS = 60_000_000_000
DEFAULTS = dict(pivot_len=2, stop_model="zone", rr=1.0, use_htf=True,
                require_fvg=True, max_age=288, max_active=100,
                execution_minutes=1, warmup_days=30, capital=100_000.0,
                first_touch_only=True, min_opposing_room_r=2.0,
                entry_eligibility="first_touch", order_lifetime_bars=1,
                slippage_model="cash", sizing_mode="fixed_contracts", contracts=1,
                risk_budget=100.0, max_contracts=10, record_events=False,
                finalize=True, max_zone_width_atr=None, min_departure_atr=None,
                min_departure_rvol=None, max_touch_age_hours=None, zone_boundary="wick")
QUALITY_PARAMETERS = ("max_zone_width_atr", "min_departure_atr",
                      "min_departure_rvol", "max_touch_age_hours")
FORMATION_FEATURES = ("prior_atr20", "prior_volume20", "zone_width_atr",
                      "departure_atr", "departure_rvol")

TRADE_COLUMNS = ["entry_time", "exit_time", "side", "quantity", "entry", "exit",
                 "stop", "target", "risk", "risk_cash", "gross_pnl", "cost",
                 "net_pnl", "net_r", "exit_reason", "zone_time", "zone_top",
                 "zone_bottom", "ambiguous_entry", "ambiguous_exit",
                 "entry_bar_target_ignored", "execution_minutes",
                 "first_touch_time", "signal_time", "entry_reference",
                 "opposing_boundary", "opposing_room_r", "initial_risk",
                 "initial_risk_cash", "target_requested_rr", "target_effective_rr",
                 "order_expiry_time", "eligibility_policy", "lifetime_bars",
                 "entry_price_before_slippage", "exit_price_before_slippage",
                 "sizing_mode", "contracts_abs", "risk_budget",
                 "planned_stop_risk_per_contract", "planned_stop_risk_cash",
                 "actual_stop_risk_per_contract", "actual_stop_risk_cash",
                 "risk_budget_overshoot_cash", "quantity_capped", "order_id", "zone_id",
                 *FORMATION_FEATURES, "signal_age_hours"]
EVENT_COLUMNS = ["event_id", "event_type", "observed_time", "event_time",
                 "zone_id", "order_id", "side", "reason", "details"]
SIZING_DECISION_COLUMNS = ["observed_time", "zone_id", "side", "trigger", "stop",
                           "planned_stop_risk_per_contract", "quantity_uncapped",
                           "quantity_selected", "quantity_capped", "risk_budget",
                           "sizing_mode", "rejection_reason", "order_id"]


def _positive_integer(value, name):
    if isinstance(value, (bool, str)) or not np.isfinite(value) or int(value) != value or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return int(value)


def _planned_quantity(parameters, trigger, stop, point_value, fee, slip_cash):
    """Freeze quantity at signal from the all-in nongap stop-loss estimate.

    Both cash and price modes reserve entry and stop-exit adverse slippage plus
    both commissions. Whole-contract flooring can reject a signal. The fixed
    budget does not compound; neither margin nor account buying power is modeled.
    """
    per_contract = abs(trigger - stop) * point_value + 2 * slip_cash + 2 * fee
    if parameters["sizing_mode"] == "fixed_contracts":
        return int(parameters["contracts"]), per_contract, False
    uncapped = int(np.floor(float(parameters["risk_budget"]) / per_contract))
    return min(int(parameters["max_contracts"]), uncapped), per_contract, uncapped > int(parameters["max_contracts"])


def _opposing_boundary(context, side, entry, epsilon=0.0):
    """Nearest active opposite proximal ahead, or containing entry; causal only.

    A zone wholly behind entry cannot obstruct the forward target path. A zone
    containing entry returns its proximal boundary, yielding zero/negative room.
    None means there is no currently observed opposing obstacle ahead.
    """
    candidates = []
    for zone in context:
        if zone["side"] == side:
            continue
        if side == 1 and zone["top"] >= entry - epsilon:
            candidates.append(zone["bottom"])
        elif side == -1 and zone["bottom"] <= entry + epsilon:
            candidates.append(zone["top"])
    if not candidates:
        return None
    return min(candidates) if side == 1 else max(candidates)


def _room_r(side, entry, stop, boundary):
    risk = side * (entry - stop)
    if risk <= 0:
        return -np.inf
    return np.inf if boundary is None else max(0.0, side * (boundary - entry)) / risk


def _round_target_toward_entry(target, side, tick_size, epsilon):
    """Conservative executable limit: floor longs, ceil shorts to a tick.

    Retain an already aligned raw value to avoid changing floating arithmetic
    for the original integer-R baseline. Epsilon only handles binary noise.
    """
    units = target / tick_size
    if abs(target - round(units) * tick_size) <= epsilon:
        return target
    ticks = np.floor(units + epsilon / tick_size) if side == 1 else np.ceil(units - epsilon / tick_size)
    return float(ticks * tick_size)


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
    volume = (pd.to_numeric(source["volume"], errors="coerce").to_numpy(float, copy=True)
              if "volume" in source else np.full(len(source), np.nan))
    # Missing, negative or nonfinite volume is unavailable, never zero-imputed.
    volume[~np.isfinite(volume) | (volume < 0)] = np.nan
    return pd.DataFrame({"open": opens[starts], "high": np.maximum.reduceat(highs, starts),
                         "low": np.minimum.reduceat(lows, starts), "close": closes[stops - 1],
                         "volume": np.add.reduceat(volume, starts),
                         "source_start": starts, "source_stop": stops,
                         "source_count": counts, "complete": complete,
                         "segment": last_segments,
                         "crosses_roll": first_segments != last_segments},
                        index=pd.to_datetime(keys[starts], utc=True))


def _add_quality_features(chart):
    """Features at each potential three-bar formation's confirmation close.

    Reference means contain the 20 complete bars strictly before the BASE open,
    excluding all three formation bars. True range uses the preceding complete
    same-segment close. The first bar after a roll has no usable true range;
    therefore ATR first becomes available after 21 complete historical bars.
    Missing chart buckets consume elapsed age but not a complete-bar lookback.
    Volume is a simple activity ratio, NOT adjusted for intraday seasonality.
    """
    valid = chart.loc[chart.complete]
    segment = valid.segment
    previous_close = valid.close.groupby(segment, sort=False).shift(1)
    tr = pd.Series(np.maximum.reduce([
        (valid.high - valid.low).to_numpy(float),
        (valid.high - previous_close).abs().to_numpy(float),
        (valid.low - previous_close).abs().to_numpy(float)]), index=valid.index)

    def before_open_mean(values):
        return values.groupby(segment, sort=False).transform(
            lambda block: block.rolling(20, min_periods=20).mean().shift(1))

    # Reindex first so shift(2) means the actual base of the observed three-bar
    # formation. Continuity/complete/segment gates then reject invalid triples.
    prior_atr = before_open_mean(tr).reindex(chart.index).shift(2)
    prior_volume = before_open_mean(valid.volume).reindex(chart.index).shift(2)
    continuous = (chart.complete & chart.complete.shift(1, fill_value=False)
                  & chart.complete.shift(2, fill_value=False)
                  & (chart.index.to_series().diff(2) == pd.Timedelta(minutes=10))
                  & (chart.segment == chart.segment.shift(2)))
    prior_atr = prior_atr.where(continuous & (prior_atr > 0))
    prior_volume = prior_volume.where(continuous & (prior_volume > 0))
    long_base = chart.close.shift(2) < chart.open.shift(2)
    short_base = chart.close.shift(2) > chart.open.shift(2)
    width = pd.Series(np.nan, index=chart.index)
    width.loc[long_base] = (chart.high.shift(2) - chart.low.rolling(3).min()).loc[long_base]
    width.loc[short_base] = (chart.high.rolling(3).max() - chart.low.shift(2)).loc[short_base]
    chart["prior_atr20"] = prior_atr
    chart["prior_volume20"] = prior_volume
    chart["zone_width_atr"] = width / prior_atr
    chart["departure_atr"] = (chart.close.shift(1) - chart.open.shift(1)).abs() / prior_atr
    chart["departure_rvol"] = chart.volume.shift(1) / prior_volume


def _quality_rejections(zone, signal_age_hours, parameters):
    """Return every failed enabled rule; absent measurements fail closed."""
    failures = []
    for parameter, feature, upper_bound in (
            ("max_zone_width_atr", "zone_width_atr", True),
            ("min_departure_atr", "departure_atr", False),
            ("min_departure_rvol", "departure_rvol", False),
            ("max_touch_age_hours", "signal_age_hours", True)):
        threshold = parameters[parameter]
        if threshold is None:
            continue
        value = signal_age_hours if feature == "signal_age_hours" else zone.get(feature, np.nan)
        if not np.isfinite(value):
            failures.append((parameter, True))
        elif (value > threshold if upper_bound else value < threshold):
            failures.append((parameter, False))
    return failures


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
    _add_quality_features(chart)
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
    """Execute whole contracts with explicit source-candle chronology.

    ``end`` is exclusive, including when supplied as a date-only string. Supply
    at least 30 preceding calendar days for warmup; insufficient coverage is
    reported. A prepared dictionary from ``prepare_data`` avoids reaggregation.
    Costs are per side. Cash mode charges adverse slippage without distorting
    fills. Price mode moves market/stop fills adversely and charges only fees.
    Target limits receive their exact price in either mode.
    """
    p = {**DEFAULTS, **parameters}
    if p["zone_boundary"] not in ("wick", "body"):
        raise ValueError("zone_boundary must be wick/body")
    if p["sizing_mode"] not in ("fixed_contracts", "fixed_risk"):
        raise ValueError("sizing_mode must be fixed_contracts or fixed_risk")
    p["contracts"] = _positive_integer(p["contracts"], "contracts")
    p["max_contracts"] = _positive_integer(p["max_contracts"], "max_contracts")
    if not np.isfinite(p["risk_budget"]) or p["risk_budget"] <= 0:
        raise ValueError("risk_budget must be positive and finite")
    if not isinstance(p["record_events"], bool) or not isinstance(p["finalize"], bool):
        raise ValueError("record_events and finalize must be booleans")
    if p["first_touch_only"] is not True:
        raise ValueError("Legacy first_touch_only=False is unsupported; use entry_eligibility")
    if p["entry_eligibility"] not in ("first_touch", "any_touch"):
        raise ValueError("entry_eligibility must be first_touch or any_touch")
    lifetime = p["order_lifetime_bars"]
    if isinstance(lifetime, (bool, str)) or not np.isfinite(lifetime) or int(lifetime) != lifetime or lifetime < 1:
        raise ValueError("order_lifetime_bars must be a positive integer")
    lifetime = int(lifetime)
    p["order_lifetime_bars"] = lifetime
    if p["slippage_model"] not in ("cash", "price"):
        raise ValueError("slippage_model must be cash or price")
    if p["stop_model"] not in ("zone", "candle") or p["rr"] <= 0:
        raise ValueError("stop_model must be zone/candle and rr must be positive")
    if tick_size <= 0 or point_value <= 0 or fee < 0 or slippage_ticks < 0:
        raise ValueError("Invalid contract economics")
    if int(p["max_age"]) < 1 or not 1 <= int(p["max_active"]) <= 100:
        raise ValueError("max_age must be positive and max_active must be 1..100")
    if not np.isfinite(p["min_opposing_room_r"]) or p["min_opposing_room_r"] < 0:
        raise ValueError("min_opposing_room_r must be finite and nonnegative")
    for name in QUALITY_PARAMETERS:
        value = p[name]
        if value is not None:
            if isinstance(value, (bool, str)) or not np.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be None or finite and nonnegative")
            p[name] = float(value)
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
    zone_high = np.maximum(co, cc) if p["zone_boundary"] == "body" else ch
    zone_low = np.minimum(co, cc) if p["zone_boundary"] == "body" else cl
    complete = chart.complete.to_numpy(bool)
    chart_bias, hourly_bias = chart.bias.to_numpy(int), chart.hourly_bias.to_numpy(int)
    chart_segments = chart.segment.to_numpy(np.int64)
    quality_values = {name: (chart[name].to_numpy(float) if name in chart
                            else np.full(len(chart), np.nan)) for name in FORMATION_FEATURES}
    begins, stops = chart.source_start.to_numpy(int), chart.source_stop.to_numpy(int)
    slip_cash = float(slippage_ticks) * tick_size * point_value
    slip_price = float(slippage_ticks) * tick_size if p["slippage_model"] == "price" else 0.0
    charged_slip_cash = slip_cash if p["slippage_model"] == "cash" else 0.0
    entry_cost = fee + charged_slip_cash
    # Decimal futures ticks (for example 0.1) are not exact binary floats.
    # This tolerance is far smaller than one tick and only resolves arithmetic
    # noise at mathematically equal trigger, bracket and zone boundaries.
    price_epsilon = float(tick_size) * 1e-7
    diagnostics = {**prepared["diagnostics"], "zones_created": 0, "zone_invalidations": 0,
                   "zones_expired": 0, "zones_discarded_capacity": 0, "zone_touches": 0,
                   "physical_first_touches": 0, "first_touches_warmup": 0,
                   "first_touches_busy_or_exit": 0, "first_touches_misaligned": 0,
                   "first_touches_incomplete": 0, "orders_expired": 0,
                   "room_rejections_at_signal": 0, "room_rejections_at_fill": 0,
                   "nonpositive_risk_rejections": 0,
                   "nonpositive_target_rejections": 0,
                   "context_zones_created": 0, "context_zone_invalidations": 0,
                   "context_zones_expired": 0, "context_zones_discarded_capacity": 0,
                   "entry_orders_armed": 0, "orders_cancelled_bias": 0,
                   "orders_cancelled_zone": 0,
                   "ambiguous_entry_count": 0, "ambiguous_exit_count": 0,
                   "entry_bar_targets_ignored": 0, "roll_liquidations": 0,
                   "scored_source_rows": 0, "scored_5m_buckets": 0,
                   "insufficient_warmup": bool(stamps[0] > warmup),
                   "start_inclusive": start.isoformat(), "end_exclusive": end.isoformat(),
                   "warmup_days_requested": int(p["warmup_days"]),
                   "warmup_trades": "No warmup fills; structure, zones and touches initialize before flat scoring start.",
                   "roll_policy": "Contract transitions flatten at prior source close and reset zones/structure; prior-close roll liquidation is an idealized data adjustment, not an executable roll-timing signal.",
                   "sizing": p["sizing_mode"], "fee_per_side": fee,
                   "sizing_policy": "Whole quantity frozen at arm; fixed risk floors budget divided by trigger-to-stop loss plus both fees and both adverse market/stop slippages, then caps quantity. Zero quantity skips this candidate. No margin or compounding; gaps can exceed budget.",
                   "sizing_rejections": 0, "quantity_capped_orders": 0,
                   "risk_budget_overshoot_entries": 0, "risk_budget_overshoot_cash": 0.0,
                   "planned_stop_risk_cash_entered": 0.0,
                   "actual_stop_risk_cash_entered": 0.0,
                   "contracts_entered": 0,
                   "slippage_ticks_per_market_or_stop_side": slippage_ticks,
                   "entry_eligibility": p["entry_eligibility"],
                   "order_lifetime_bars": lifetime,
                   "order_lifetime_policy": "Exclusive expiry is signal time plus N elapsed five-minute buckets; missing buckets consume lifetime. Pending trigger, stop and opposing boundary never refresh.",
                   "slippage_model": p["slippage_model"],
                   "slippage_policy": ("Adverse price fills for stop/market entries and exits; targets at exact limits, fee-only cash costs. Idealized fills can lie outside OHLC; no tick/queue simulation." if p["slippage_model"] == "price" else "Original reference fills; adverse slippage charged in cash on market/stop sides, with targets fee-only."),
                   "fresh_touch_policy": ("First observed physical overlap consumes eligibility regardless of warmup, position, bias or missing source bars; only that complete, tradable bucket can arm." if p["entry_eligibility"] == "first_touch" else "Each later complete physically overlapping bucket may arm if flat, aligned, scored, and without a pending order or same-bucket exit; earlier touches do not permanently consume eligibility."),
                   "opposing_room_policy": "Independent same-geometry zones; nearest opposing proximal frozen at signal, rechecked against actual gap fill and risk; no known opposing zone means unlimited room.",
                   "target_tick_policy": "Off-grid targets round toward entry to an executable tick; already aligned targets retain raw arithmetic.",
                   "partial_bar_policy": "Incomplete buckets cannot arm or create zones, but observed wicks consume first touches and invalidate existing zones."}
    diagnostics.update(quality_rejections_at_signal=0,
                       quality_missing_rejections_at_signal=0,
                       quality_feature_policy="Formation snapshots: prior20 complete 5m true ranges and volumes strictly before base open, same contract segment; true range requires a previous complete same-segment close. Width uses the selected wick/body zone geometry; departure is absolute middle-candle body. RVOL is not seasonally adjusted. Enabled filters reject missing/nonfinite values only at candidate arming; context and physical-touch lifecycle remain intact.",
                       quality_age_policy="Elapsed clock hours from formation confirmation close to signal/arming close; absent buckets and session closures consume age.")
    for name in QUALITY_PARAMETERS:
        diagnostics[f"{name}_rejections_at_signal"] = 0
        diagnostics[f"{name}_missing_at_signal"] = 0
    zones, context, trades, equity = [], [], [], []
    active = order = None
    balance = float(p["capital"])
    last_segment = None
    last_source = None
    last_scored_source = None
    previous_equity = balance
    events, sizing_decisions = [], []

    def emit(kind, observed, event_time=None, zone=None, pending=None, reason=None, **details):
        if not p["record_events"]:
            return
        observed = int(observed)
        if observed > en:
            raise AssertionError("Journal cannot observe future events")
        zone = zone if zone is not None else (pending["zone"] if pending is not None else None)
        identity = f"{len(events)}|{kind}|{observed}|{zone.get('zone_id') if zone else ''}|{pending.get('order_id') if pending else ''}|{reason}"
        events.append(dict(event_id=hashlib.sha256(identity.encode()).hexdigest()[:24],
                           event_type=kind, observed_time=pd.Timestamp(observed, tz="UTC"),
                           event_time=pd.Timestamp(observed if event_time is None else int(event_time), tz="UTC"),
                           zone_id=zone.get("zone_id") if zone else details.get("zone_id"),
                           order_id=pending.get("order_id") if pending else details.get("order_id"),
                           side=zone["side"] if zone else details.get("side"), reason=reason,
                           details=details))

    def cancel_order(kind, observed, reason):
        nonlocal order
        if order is not None:
            emit(kind, observed, pending=order, reason=reason, trigger=order["trigger"],
                 stop=order["stop"], contracts_abs=order["contracts_abs"])
            order = None

    def finish(price, when, reason, ambiguous=False, observed=None):
        nonlocal active, balance
        price_before_slippage = price
        if reason != "target":
            price -= active["side"] * slip_price
        quantity = active["contracts_abs"]
        exit_cost = (fee + (0.0 if reason == "target" else charged_slip_cash)) * quantity
        gross = active["side"] * (price - active["entry"]) * point_value * quantity
        cost = entry_cost * quantity + exit_cost
        balance += gross - exit_cost  # Entry cash cost was charged at entry.
        active.update(exit_time=pd.Timestamp(when, tz="UTC"), exit=float(price),
                      gross_pnl=gross, cost=cost, net_pnl=gross - cost,
                      net_r=(gross - cost) / active["risk_cash"],
                      exit_reason=reason, ambiguous_exit=bool(ambiguous),
                      exit_price_before_slippage=float(price_before_slippage))
        trades.append(active)
        emit("exit", when if observed is None else observed, event_time=when,
             reason=reason, **active)
        if ambiguous:
            diagnostics["ambiguous_exit_count"] += 1
        active = None

    for i in range(first_bucket, last_bucket):
        bucket_time = chart_stamps[i]
        scored_bucket = False
        exited_bucket = False
        busy_bucket = active is not None
        if order is not None and bucket_time >= order["expiry_time"]:
            diagnostics["orders_expired"] += 1
            cancel_order("order_expired", order["expiry_time"], "lifetime")
        if order is not None and i - order["zone"]["created_index"] > int(p["max_age"]):
            diagnostics["orders_cancelled_zone"] += 1
            cancel_order("order_cancelled", bucket_time, "zone-age")
        # The latest closed hour becomes available at this chart bar's open.
        # A cancellation preserves the zone's touched state for later rearming.
        if order is not None and p["use_htf"] and hourly_bias[i] != order["side"]:
            diagnostics["orders_cancelled_bias"] += 1
            cancel_order("order_cancelled", bucket_time, "hourly-bias")
        for j in range(begins[i], stops[i]):
            when = stamps[j]
            if when + delta_ns > en:
                break
            if last_segment is not None and segments[j] != last_segment:
                if active is not None:
                    finish(sc[last_source], stamps[last_source] + delta_ns, "contract-roll", observed=when + delta_ns)
                    diagnostics["roll_liquidations"] += 1
                    exited_bucket = True
                cancel_order("order_cancelled", when + delta_ns, "contract-roll")
                for zone in zones:
                    emit("zone_removed", when + delta_ns, zone=zone, reason="contract-roll")
                zones, context = [], []
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
                    entry_before_slippage = max(so[j], trigger) if side == 1 else min(so[j], trigger)
                    entry = entry_before_slippage + side * slip_price
                    stop = order["stop"]
                    risk = side * (entry - stop)
                    target = entry + side * risk * float(p["rr"])
                    if p["first_touch_only"] or p["min_opposing_room_r"] > 0:
                        target = _round_target_toward_entry(target, side, tick_size, price_epsilon)
                    room = _room_r(side, entry, stop, order["opposing_boundary"])
                    room_ok = (p["min_opposing_room_r"] == 0 or
                               room + 1e-12 >= p["min_opposing_room_r"])
                    if risk <= 0:
                        diagnostics["nonpositive_risk_rejections"] += 1
                        emit("signal_skipped", when + delta_ns, event_time=when, pending=order, reason="nonpositive-risk-at-fill")
                    elif not room_ok:
                        diagnostics["room_rejections_at_fill"] += 1
                        emit("signal_skipped", when + delta_ns, event_time=when, pending=order, reason="opposing-room-at-fill", opposing_room_r=room)
                    elif side * (target - entry) <= price_epsilon:
                        diagnostics["nonpositive_target_rejections"] += 1
                        emit("signal_skipped", when + delta_ns, event_time=when, pending=order, reason="nonpositive-target-at-fill")
                    else:
                        entered_at_open = so[j] >= trigger - price_epsilon if side == 1 else so[j] <= trigger + price_epsilon
                        quantity = order["contracts_abs"]
                        actual_per_contract = risk * point_value + 2 * fee + (2 * slip_cash if p["slippage_model"] == "cash" else slip_cash)
                        actual_stop_risk = actual_per_contract * quantity
                        budget = float(p["risk_budget"]) if p["sizing_mode"] == "fixed_risk" else np.nan
                        overshoot = max(0.0, actual_stop_risk - budget) if p["sizing_mode"] == "fixed_risk" else np.nan
                        active = dict(entry_time=pd.Timestamp(when, tz="UTC"), side=side,
                                      quantity=side * quantity, entry=entry, stop=stop,
                                      target=target,
                                      risk=risk, risk_cash=risk * point_value * quantity,
                                      zone_time=pd.Timestamp(zone["created_time"], tz="UTC"),
                                      zone_top=zone["top"], zone_bottom=zone["bottom"],
                                      ambiguous_entry=bool(invalidated), ambiguous_exit=False,
                                      entry_bar_target_ignored=False,
                                      execution_minutes=execution_minutes,
                                      first_touch_time=pd.Timestamp(zone["first_touch_time"], tz="UTC"),
                                      signal_time=pd.Timestamp(order["signal_time"], tz="UTC"),
                                      entry_reference=trigger,
                                      opposing_boundary=(np.nan if order["opposing_boundary"] is None else order["opposing_boundary"]),
                                      opposing_room_r=room, initial_risk=risk,
                                      initial_risk_cash=risk * point_value * quantity,
                                      target_requested_rr=float(p["rr"]),
                                      target_effective_rr=side * (target - entry) / risk,
                                      order_expiry_time=pd.Timestamp(order["expiry_time"], tz="UTC"),
                                      eligibility_policy=p["entry_eligibility"], lifetime_bars=lifetime,
                                      entry_price_before_slippage=entry_before_slippage,
                                      sizing_mode=p["sizing_mode"], contracts_abs=quantity,
                                      risk_budget=budget,
                                      planned_stop_risk_per_contract=order["planned_stop_risk_per_contract"],
                                      planned_stop_risk_cash=order["planned_stop_risk_per_contract"] * quantity,
                                      actual_stop_risk_per_contract=actual_per_contract,
                                      actual_stop_risk_cash=actual_stop_risk,
                                      risk_budget_overshoot_cash=overshoot,
                                      quantity_capped=order["quantity_capped"],
                                      order_id=order["order_id"], zone_id=zone["zone_id"],
                                      **{name: zone[name] for name in FORMATION_FEATURES},
                                      signal_age_hours=order["signal_age_hours"])
                        balance -= entry_cost * quantity
                        diagnostics["contracts_entered"] += quantity
                        diagnostics["planned_stop_risk_cash_entered"] += active["planned_stop_risk_cash"]
                        diagnostics["actual_stop_risk_cash_entered"] += actual_stop_risk
                        if p["sizing_mode"] == "fixed_risk":
                            diagnostics["risk_budget_overshoot_entries"] += int(overshoot > 1e-9)
                            diagnostics["risk_budget_overshoot_cash"] += overshoot
                        emit("entry", when + delta_ns, event_time=when, **active)
                        just_entered = True
                        busy_bucket = True
                        zone["used"] = True
                        if invalidated:
                            diagnostics["ambiguous_entry_count"] += 1
                    order = None
                elif invalidated:
                    zone["invalid"] = True
                    diagnostics["orders_cancelled_zone"] += 1
                    cancel_order("order_cancelled", when + delta_ns, "zone-wick-invalidation")
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
                    finish(so[j], when, "stop", observed=when + delta_ns)
                    exited_bucket = True
                elif target_gap:
                    finish(target, when, "target", observed=when + delta_ns)
                    exited_bucket = True
                elif stop_hit:
                    # On intrabar entry the source open occurred before entry;
                    # it cannot be used as the stop fill. Established brackets
                    # and entries at the open do incur adverse opening gaps.
                    price = (min(so[j], stop) if side == 1 else max(so[j], stop)) if not just_entered or entered_at_open else stop
                    finish(price, when, "stop", ambiguous=target_hit, observed=when + delta_ns)
                    exited_bucket = True
                elif target_hit and target_allowed:
                    finish(target, when, "target", observed=when + delta_ns)
                    exited_bucket = True
        if bucket_time + 5 * MINUTE_NS > en:
            break
        # Every observed wick can invalidate a zone even when this source bucket
        # lacks enough candles to serve as a valid setup/structure candle.
        retained = []
        for zone in zones:
            overlaps = (i > zone["created_index"] and cl[i] <= zone["top"] + price_epsilon
                        and ch[i] >= zone["bottom"] - price_epsilon)
            if overlaps:
                hit = np.flatnonzero((sl[begins[i]:stops[i]] <= zone["top"] + price_epsilon) &
                                     (sh[begins[i]:stops[i]] >= zone["bottom"] - price_epsilon))
                zone["last_touch_index"] = i
                zone["last_touch_time"] = int(stamps[begins[i] + int(hit[0])]) if len(hit) else int(bucket_time)
            if overlaps and zone["first_touch_index"] is None:
                zone["first_touch_index"] = i
                # The source candle open identifies the interval containing the
                # first observed touch; its intrabar instant is not knowable.
                zone["first_touch_time"] = zone["last_touch_time"]
                diagnostics["physical_first_touches"] += 1
                diagnostics["first_touches_warmup"] += int(zone["first_touch_time"] < st)
                diagnostics["first_touches_busy_or_exit"] += int(busy_bucket or exited_bucket)
                diagnostics["first_touches_incomplete"] += int(not complete[i])
                diagnostics["first_touches_misaligned"] += int(chart_bias[i] != zone["side"] or
                    (p["use_htf"] and hourly_bias[i] != zone["side"]))
            fresh_here = (zone["first_touch_index"] == i if p["entry_eligibility"] == "first_touch" else overlaps)
            if fresh_here and not zone["used"]:
                skip_reason = ("warmup" if bucket_time + 5 * MINUTE_NS <= st else
                               "position-or-same-bucket-exit" if busy_bucket or exited_bucket else
                               "incomplete-candle" if not complete[i] else
                               "bias-misaligned" if chart_bias[i] != zone["side"] or (p["use_htf"] and hourly_bias[i] != zone["side"]) else
                               "pending-order" if order is not None and bucket_time + 5 * MINUTE_NS < order["expiry_time"] else None)
                if skip_reason:
                    emit("signal_skipped", bucket_time + 5 * MINUTE_NS, zone=zone, reason=skip_reason)
            invalid = zone["invalid"] or (cl[i] < zone["bottom"] - price_epsilon if zone["side"] == 1 else ch[i] > zone["top"] + price_epsilon)
            if invalid:
                diagnostics["zone_invalidations"] += 1
                emit("zone_removed", bucket_time + 5 * MINUTE_NS, zone=zone, reason="wick-invalidation")
            elif i - zone["created_index"] > int(p["max_age"]):
                diagnostics["zones_expired"] += 1
                emit("zone_removed", bucket_time + 5 * MINUTE_NS, zone=zone, reason="zone-age")
            elif not zone["used"]:
                if (complete[i] or p["first_touch_only"]) and overlaps and not zone["touched"]:
                    zone["touched"] = True
                    diagnostics["zone_touches"] += 1
                retained.append(zone)
        if order is not None and bucket_time + 5 * MINUTE_NS >= order["expiry_time"]:
            diagnostics["orders_expired"] += 1
            cancel_order("order_expired", order["expiry_time"], "lifetime")
        if order is not None and not any(zone is order["zone"] for zone in retained):
            diagnostics["orders_cancelled_zone"] += 1
            cancel_order("order_cancelled", bucket_time + 5 * MINUTE_NS, "zone-removed")
        zones = retained
        retained_context = []
        for zone in context:
            invalid = cl[i] < zone["bottom"] - price_epsilon if zone["side"] == 1 else ch[i] > zone["top"] + price_epsilon
            if invalid:
                diagnostics["context_zone_invalidations"] += 1
            elif i - zone["created_index"] > int(p["max_age"]):
                diagnostics["context_zones_expired"] += 1
            else:
                retained_context.append(zone)
        context = retained_context
        if complete[i]:
            bias = chart_bias[i]
            aligned = bias != 0 and (not p["use_htf"] or hourly_bias[i] == bias)
            continuous_three = (i >= 2 and complete[i - 1] and complete[i - 2] and
                                bucket_time - chart_stamps[i - 2] == 10 * MINUTE_NS and
                                chart_segments[i] == chart_segments[i - 2])
            if continuous_three:
                long_pattern = (cc[i - 2] < co[i - 2] and cc[i - 1] > co[i - 1] and
                                (cl[i] > ch[i - 2] if p["require_fvg"] else cc[i] > ch[i - 2]))
                short_pattern = (cc[i - 2] > co[i - 2] and cc[i - 1] < co[i - 1] and
                                 (ch[i] < cl[i - 2] if p["require_fvg"] else cc[i] < cl[i - 2]))
                pattern_side = 1 if long_pattern else (-1 if short_pattern else 0)
                if pattern_side:
                    top = zone_high[i - 2] if pattern_side == 1 else max(zone_high[i - 2:i + 1])
                    bottom = min(zone_low[i - 2:i + 1]) if pattern_side == 1 else zone_low[i - 2]
                    context.append(dict(side=pattern_side, top=top, bottom=bottom,
                                        created_index=i, created_time=bucket_time + 5 * MINUTE_NS))
                    diagnostics["context_zones_created"] += 1
                    if len(context) > int(p["max_active"]):
                        del context[0]
                        diagnostics["context_zones_discarded_capacity"] += 1
                if aligned and pattern_side == bias:
                    zones.append(dict(side=bias, top=top, bottom=bottom,
                                      zone_id=f"{int(chart_segments[i])}:{bias}:{int(bucket_time + 5 * MINUTE_NS)}",
                                      created_index=i, created_time=bucket_time + 5 * MINUTE_NS,
                                      touched=False, used=False, invalid=False,
                                      first_touch_index=None, first_touch_time=None,
                                      last_touch_index=None, last_touch_time=None,
                                      **{name: ((top - bottom) / quality_values["prior_atr20"][i]
                                               if name == "zone_width_atr" and p["zone_boundary"] == "body"
                                               else quality_values[name][i]) for name in FORMATION_FEATURES}))
                    diagnostics["zones_created"] += 1
                    emit("zone_created", bucket_time + 5 * MINUTE_NS, zone=zones[-1],
                         top=top, bottom=bottom, require_fvg=bool(p["require_fvg"]))
                    if len(zones) > int(p["max_active"]):
                        emit("zone_removed", bucket_time + 5 * MINUTE_NS, zone=zones[0], reason="capacity")
                        del zones[0]
                        diagnostics["zones_discarded_capacity"] += 1
                        if order is not None and not any(zone is order["zone"] for zone in zones):
                            diagnostics["orders_cancelled_zone"] += 1
                            cancel_order("order_cancelled", bucket_time + 5 * MINUTE_NS, "zone-capacity")
            # Eligibility and lifetime are independent. No live order refresh,
            # no warmup arms, no rearm after a fill/exit in this bucket.
            eligible_bucket = scored_bucket and not exited_bucket and not busy_bucket
            if active is None and order is None and aligned and eligible_bucket:
                for zone in reversed(zones):
                    fresh = ((zone["first_touch_index"] == i and zone["first_touch_time"] >= st)
                             if p["entry_eligibility"] == "first_touch" else
                             (zone["last_touch_index"] == i and zone["last_touch_time"] >= st))
                    if zone["side"] == bias and zone["touched"] and i > zone["created_index"] and fresh:
                        trigger = ch[i] + tick_size if bias == 1 else cl[i] - tick_size
                        anchor = (zone["bottom"] if bias == 1 else zone["top"]) if p["stop_model"] == "zone" else (cl[i] if bias == 1 else ch[i])
                        stop = anchor - bias * tick_size
                        emit("signal", bucket_time + 5 * MINUTE_NS, zone=zone,
                             trigger=trigger, stop=stop)
                        if bias * (trigger - stop) > 0:
                            boundary = _opposing_boundary(context, bias, trigger, price_epsilon)
                            room = _room_r(bias, trigger, stop, boundary)
                            if p["min_opposing_room_r"] > 0 and room + 1e-12 < p["min_opposing_room_r"]:
                                diagnostics["room_rejections_at_signal"] += 1
                                emit("signal_skipped", bucket_time + 5 * MINUTE_NS, zone=zone,
                                     reason="opposing-room-at-signal", opposing_room_r=room)
                                continue
                            signal_age_hours = (bucket_time + 5 * MINUTE_NS - zone["created_time"]) / (60 * MINUTE_NS)
                            failures = _quality_rejections(zone, signal_age_hours, p)
                            if failures:
                                diagnostics["quality_rejections_at_signal"] += 1
                                diagnostics["quality_missing_rejections_at_signal"] += int(any(missing for _, missing in failures))
                                for name, missing in failures:
                                    diagnostics[f"{name}_rejections_at_signal"] += 1
                                    diagnostics[f"{name}_missing_at_signal"] += int(missing)
                                continue
                            quantity, planned_per_contract, capped = _planned_quantity(p, trigger, stop, point_value, fee, slip_cash)
                            uncapped = int(np.floor(float(p["risk_budget"]) / planned_per_contract)) if p["sizing_mode"] == "fixed_risk" else quantity
                            order_id = f"{zone['zone_id']}:{int(bucket_time + 5 * MINUTE_NS)}"
                            sizing_decisions.append(dict(observed_time=pd.Timestamp(bucket_time + 5 * MINUTE_NS, tz="UTC"),
                                zone_id=zone["zone_id"], side=bias, trigger=trigger, stop=stop,
                                planned_stop_risk_per_contract=planned_per_contract,
                                quantity_uncapped=uncapped, quantity_selected=quantity,
                                quantity_capped=capped, risk_budget=float(p["risk_budget"]) if p["sizing_mode"] == "fixed_risk" else np.nan,
                                sizing_mode=p["sizing_mode"], rejection_reason="risk-budget-below-one-contract" if quantity == 0 else None,
                                order_id=order_id if quantity else None))
                            if quantity == 0:
                                diagnostics["sizing_rejections"] += 1
                                emit("signal_skipped", bucket_time + 5 * MINUTE_NS, zone=zone,
                                     reason="risk-budget-below-one-contract", planned_stop_risk_per_contract=planned_per_contract,
                                     risk_budget=float(p["risk_budget"]))
                                continue
                            order = dict(side=bias, trigger=trigger, stop=stop, zone=zone,
                                         contracts_abs=quantity, planned_stop_risk_per_contract=planned_per_contract,
                                         quantity_capped=capped, order_id=order_id,
                                         signal_time=int(bucket_time + 5 * MINUTE_NS),
                                         expiry_time=int(bucket_time + (lifetime + 1) * 5 * MINUTE_NS),
                                         opposing_boundary=boundary, signal_age_hours=signal_age_hours)
                            diagnostics["entry_orders_armed"] += 1
                            diagnostics["quantity_capped_orders"] += int(capped)
                            emit("order_armed", bucket_time + 5 * MINUTE_NS, pending=order,
                                 trigger=trigger, stop=stop, contracts_abs=quantity,
                                 planned_stop_risk_per_contract=planned_per_contract,
                                 planned_stop_risk_cash=planned_per_contract * quantity,
                                 quantity_capped=capped, expiry_time=pd.Timestamp(order["expiry_time"], tz="UTC"),
                                 opposing_boundary=boundary)
                            break
                        else:
                            emit("signal_skipped", bucket_time + 5 * MINUTE_NS, zone=zone, reason="nonpositive-risk-at-signal")
        if scored_bucket:
            unrealized = 0.0 if active is None else active["side"] * (sc[last_scored_source] - active["entry"]) * point_value * active["contracts_abs"]
            marked = balance + unrealized
            equity.append(dict(timestamp=pd.Timestamp(stamps[last_scored_source] + delta_ns, tz="UTC"),
                               equity=marked, balance=balance, unrealized_pnl=unrealized,
                               net_pnl=marked - previous_equity,
                               contracts=0 if active is None else active["quantity"]))
            previous_equity = marked
            diagnostics["scored_5m_buckets"] += 1
    if order is not None and order["expiry_time"] <= en:
        diagnostics["orders_expired"] += 1
        cancel_order("order_expired", order["expiry_time"], "lifetime")
    if p["finalize"] and active is not None and last_scored_source is not None:
        j = last_scored_source
        finish(sc[j], stamps[j] + delta_ns, "end-of-test")
    final_unrealized = (0.0 if active is None or last_scored_source is None else
                        active["side"] * (sc[last_scored_source] - active["entry"]) * point_value * active["contracts_abs"])
    final_mark = balance + final_unrealized
    final_contracts = 0 if active is None else active["quantity"]
    if last_scored_source is not None:
        final_when = pd.Timestamp(stamps[last_scored_source] + delta_ns, tz="UTC")
        # An as-of snapshot retains actual unrealized PnL and entry costs. A
        # finalized historical run instead reconciles to closed-trade PnL.
        if equity and equity[-1]["timestamp"] == final_when:
            previous_mark = equity[-2]["equity"] if len(equity) > 1 else float(p["capital"])
            equity[-1].update(equity=final_mark, balance=balance, unrealized_pnl=final_unrealized,
                              net_pnl=final_mark - previous_mark, contracts=final_contracts)
        else:
            equity.append(dict(timestamp=final_when, equity=final_mark, balance=balance,
                               unrealized_pnl=final_unrealized, net_pnl=final_mark - previous_equity, contracts=final_contracts))
    trade_frame = pd.DataFrame(trades, columns=TRADE_COLUMNS)
    equity_frame = pd.DataFrame(equity, columns=["timestamp", "equity", "balance", "unrealized_pnl", "net_pnl", "contracts"])
    diagnostics["trades"] = len(trade_frame)
    open_entry_cost = 0.0 if active is None else entry_cost * active["contracts_abs"]
    diagnostics["accounting_error"] = float(balance - float(p["capital"]) - trade_frame.net_pnl.sum() + open_entry_cost)
    diagnostics["open_position_entry_cost"] = open_entry_cost
    diagnostics["finalized"] = p["finalize"]
    diagnostics["event_count"] = len(events)
    diagnostics["sizing_decisions"] = len(sizing_decisions)
    open_state = dict(as_of=end, last_mark_time=(None if last_scored_source is None else pd.Timestamp(stamps[last_scored_source] + delta_ns, tz="UTC")),
                      balance=balance, equity=final_mark, unrealized_pnl=final_unrealized,
                      active=None if active is None else dict(active),
                      pending=None if order is None else {**order, "zone": dict(order["zone"])},
                      zones=[dict(zone) for zone in zones], context=[dict(zone) for zone in context])
    return dict(trades=trade_frame, equity=equity_frame, diagnostics=diagnostics,
                events=pd.DataFrame(events, columns=EVENT_COLUMNS), open_state=open_state,
                sizing_decisions=pd.DataFrame(sizing_decisions, columns=SIZING_DECISION_COLUMNS),
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
