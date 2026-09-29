"""Independent sampled raw-condition and exhaustive ledger audit for combinations.

This script imports no strategy module. It independently aggregates immutable
minute data, reconstructs formations/structure, and audits every declared case.
It does not select or rerun models and preserves failures and zero-trade cases.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import itertools
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / 'reports/snd-combinations-2026-09-26'
MINUTE = 60_000_000_000
FIVE = 5 * MINUTE


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def require_frozen_runtime(manifest, executing_files):
    """Reject workspace or imported code that differs from the frozen source.

    Snapshot integrity alone does not prove which Python file is executing.
    Call before computation and again before publishing the terminal audit.
    """
    expected = {entry['path']: entry['checksum'] for entry in manifest['files']}
    for relative, actual in executing_files.items():
        if relative not in expected or sha(actual) != expected[relative]:
            raise ValueError('Executing audit source differs from frozen manifest: ' + relative)


def ns(values):
    return pd.DatetimeIndex(pd.to_datetime(values, utc=True)).as_unit('ns').asi8


class Checks:
    def __init__(self, identity):
        self.result = dict(identity=identity, checks=0, failures=[], max_errors={})

    def require(self, name, condition):
        self.result['checks'] += 1
        if not bool(condition):
            self.result['failures'].append(name)

    def close(self, name, actual, expected, atol=1e-7):
        a, b = np.broadcast_arrays(np.asarray(actual, float), np.asarray(expected, float))
        finite = np.isfinite(a) & np.isfinite(b)
        error = float(np.max(np.abs(a[finite] - b[finite]))) if finite.any() else 0.0
        self.result['max_errors'][name] = error
        self.require(name, np.isclose(a, b, atol=atol, rtol=1e-11, equal_nan=True).all())

    def finish(self):
        self.result['passed'] = not self.result['failures']
        return self.result


def grouped(frame, width):
    output = frame.groupby(frame.index.floor(f'{width}min'), sort=True).agg(
        open=('open', 'first'), high=('high', 'max'), low=('low', 'min'), close=('close', 'last'),
        volume=('volume', 'sum'),
        count=('open', 'size'), first=('_stamp', 'first'), last=('_stamp', 'last'),
        begin=('_pos', 'first'), final=('_pos', 'last'),
        first_segment=('_segment', 'first'), segment=('_segment', 'last'))
    output['complete'] = ((output['count'] == width) & (output['first'] == output.index) &
        (output['last'] + pd.Timedelta(minutes=1) == output.index + pd.Timedelta(minutes=width)) &
        (output.first_segment == output.segment))
    return output


def direction(frame, pivot):
    """Strict pivots computed by centered windows, revealed after right bars."""
    result = np.zeros(len(frame), dtype=np.int8)
    high, low, close = (frame[key].to_numpy(float) for key in ('high', 'low', 'close'))
    segment = frame.segment.to_numpy()
    confirmed_high, confirmed_low = np.full(len(frame), np.nan), np.full(len(frame), np.nan)
    width = 2 * pivot + 1
    if len(frame) >= width:
        hi = np.lib.stride_tricks.sliding_window_view(high, width)
        lo = np.lib.stride_tricks.sliding_window_view(low, width)
        other = [i for i in range(width) if i != pivot]
        same = segment[2 * pivot:] == segment[:-2 * pivot]
        high_mask = same & (hi[:, pivot] > hi[:, other].max(axis=1))
        low_mask = same & (lo[:, pivot] < lo[:, other].min(axis=1))
        confirmed_high[2 * pivot:] = np.where(high_mask, hi[:, pivot], np.nan)
        confirmed_low[2 * pivot:] = np.where(low_mask, lo[:, pivot], np.nan)
    high_level, low_level, bias = np.nan, np.nan, 0
    for i in range(len(frame)):
        if i == 0 or segment[i] != segment[i - 1]:
            high_level, low_level, bias = np.nan, np.nan, 0
        if np.isfinite(confirmed_high[i]):
            high_level = confirmed_high[i]
        if np.isfinite(confirmed_low[i]):
            low_level = confirmed_low[i]
        if close[i] > high_level:
            bias, high_level = 1, np.nan
        if close[i] < low_level:
            bias, low_level = -1, np.nan
        result[i] = bias
    return result


def raw_market(dataset):
    lower = pd.Timestamp(dataset['start'], tz='UTC') - pd.Timedelta(days=30)
    upper = pd.Timestamp(dataset['end'], tz='UTC')
    chunks, identities = [], []
    for item in dataset['files']:
        digest = sha(item['path'])
        if digest != item['checksum']:
            raise ValueError('Raw source checksum mismatch: ' + item['path'])
        identities.append(dict(path=item['path'], checksum=digest))
        frame = pd.read_parquet(item['path'])
        frame.index = pd.to_datetime(frame.index, utc=True)
        chunks.append(frame.loc[(frame.index >= lower) & (frame.index < upper)].copy())
    frame = pd.concat(chunks).sort_index()
    if frame.empty or not frame.index.is_unique:
        raise ValueError('Empty/duplicate raw source')
    local = frame.index.tz_convert('America/New_York')
    minute = local.hour * 60 + local.minute
    trade_date = local.tz_localize(None).normalize() + pd.to_timedelta((minute >= 1080).astype(int), unit='D')
    frame = frame.loc[((minute >= 1080) | (minute < 1020)) & (trade_date.dayofweek < 5)].copy()
    contract = next((key for key in ('instrument_id', 'contract', 'symbol') if key in frame and frame[key].notna().any()), None)
    if contract:
        ids = frame[contract].ffill().astype(str)
        frame['_segment'] = ids.ne(ids.shift()).cumsum().to_numpy() - 1
    else:
        frame['_segment'] = 0
    frame['_pos'], frame['_stamp'] = np.arange(len(frame)), frame.index
    chart, hourly_all = grouped(frame, 5), grouped(frame, 60)
    return dict(source=frame, chart=chart, hourly=hourly_all.loc[hourly_all.complete].copy(),
                identities=identities, directions={}, quality={})


def raw_from_frame(source, identities=None):
    """Build the independent audit inputs from an already sliced minute frame.

    This helper neither imports a strategy nor applies a simulator-prepared
    chart. Caller must supply the intended warmup and scored raw interval.
    """
    frame = source.copy()
    frame.index = pd.to_datetime(frame.index, utc=True)
    if frame.empty or not frame.index.is_unique or not frame.index.is_monotonic_increasing:
        raise ValueError('Raw minute source must be nonempty, sorted and unique')
    local = frame.index.tz_convert('America/New_York')
    minute = local.hour * 60 + local.minute
    date = local.tz_localize(None).normalize() + pd.to_timedelta((minute >= 1080).astype(int), unit='D')
    frame = frame.loc[((minute >= 1080) | (minute < 1020)) & (date.dayofweek < 5)].copy()
    contract = next((k for k in ('instrument_id', 'contract', 'symbol') if k in frame and frame[k].notna().any()), None)
    if contract:
        labels = frame[contract].ffill().astype(str)
        frame['_segment'] = labels.ne(labels.shift()).cumsum().to_numpy() - 1
    else:
        frame['_segment'] = 0
    frame['_pos'], frame['_stamp'] = np.arange(len(frame)), frame.index
    chart, hourly = grouped(frame, 5), grouped(frame, 60)
    return dict(source=frame, chart=chart, hourly=hourly.loc[hourly.complete].copy(),
                identities=identities or [], directions={}, quality={})


def raw_quality(raw, z, zone_top, zone_bottom):
    """Direct twenty-bar reconstruction, independent of the strategy's rolling code.

    z identifies the THIRD formation candle's open. The BASE opens at z-2.
    No formation candle contributes to either historical denominator.
    """
    if z not in raw['quality']:
        chart = raw['chart']
        if 'complete_positions' not in raw:
            raw['complete_positions'] = np.flatnonzero(chart.complete.to_numpy(bool))
        complete = raw['complete_positions']
        end = int(np.searchsorted(complete, z - 2))
        before = complete[max(0, end - 21):end]
        segment = chart.segment.iloc[z]
        before = before[chart.segment.to_numpy()[before] == segment]
        atr = vol = np.nan
        if len(before) >= 20:
            selected = before[-20:]
            volume = chart.volume.to_numpy(float)[selected]
            vol = float(volume.mean()) if np.isfinite(volume).all() and volume.mean() > 0 else np.nan
        if len(before) >= 21:
            selected, preceding = before[-20:], before[-21:-1]
            high, low, close = (chart[k].to_numpy(float) for k in ('high', 'low', 'close'))
            values = np.maximum(high[selected] - low[selected], np.maximum(
                np.abs(high[selected] - close[preceding]), np.abs(low[selected] - close[preceding])))
            atr = float(values.mean()) if np.isfinite(values).all() and values.mean() > 0 else np.nan
        middle = chart.iloc[z - 1]
        raw['quality'][z] = dict(prior_atr20=atr, prior_volume20=vol,
            zone_width_atr=(zone_top - zone_bottom) / atr,
            departure_atr=abs(middle.close - middle.open) / atr,
            departure_rvol=middle.volume / vol)
    cached = raw['quality'][z]
    return {**cached, 'zone_width_atr': (zone_top - zone_bottom) / cached['prior_atr20']}


def structures(raw, pivot):
    if pivot not in raw['directions']:
        chart, hourly = raw['chart'], raw['hourly']
        bias = np.zeros(len(chart), dtype=int)
        bias[chart.complete.to_numpy()] = direction(chart.loc[chart.complete], pivot)
        htf = direction(hourly, pivot)
        lookup = np.searchsorted(ns(hourly.index) + 60 * MINUTE, ns(chart.index), side='right') - 1
        safe = np.maximum(lookup, 0)
        same_segment = hourly.segment.to_numpy()[safe] == chart.first_segment.to_numpy()
        hourly_bias = np.where((lookup >= 0) & same_segment, htf[safe], 0)
        raw['directions'][pivot] = bias, hourly_bias
    return raw['directions'][pivot]


def formations(chart, require_fvg, boundary="wick"):
    opened, closed, high, low = (chart[key].to_numpy(float) for key in ('open', 'close', 'high', 'low'))
    complete, segment, stamps = chart.complete.to_numpy(bool), chart.segment.to_numpy(), ns(chart.index)
    side = np.zeros(len(chart), dtype=int)
    consecutive = complete[2:] & complete[1:-1] & complete[:-2] & (stamps[2:] - stamps[:-2] == 2 * FIVE) & (segment[2:] == segment[:-2])
    demand = consecutive & (closed[:-2] < opened[:-2]) & (closed[1:-1] > opened[1:-1]) & ((low[2:] if require_fvg else closed[2:]) > high[:-2])
    supply = consecutive & (closed[:-2] > opened[:-2]) & (closed[1:-1] < opened[1:-1]) & ((high[2:] if require_fvg else closed[2:]) < low[:-2])
    side[2:] = demand.astype(int) - supply.astype(int)
    if boundary not in ("wick", "body"):
        raise ValueError("Unknown zone boundary")
    if boundary == "body":
        high, low = np.maximum(opened, closed), np.minimum(opened, closed)
    top, bottom = np.full(len(chart), np.nan), np.full(len(chart), np.nan)
    top[2:] = np.where(side[2:] == 1, high[:-2], np.maximum.reduce([high[:-2], high[1:-1], high[2:]]))
    bottom[2:] = np.where(side[2:] == 1, np.minimum.reduce([low[:-2], low[1:-1], low[2:]]), low[:-2])
    return side, top, bottom


def audit_raw_trades(trades, parameters, dataset, raw, fee=None, slippage_ticks=1,
                     diagnostics=None, identity="raw trade sample"):
    """Audit only supplied rows. Call audit_ledger separately on EVERY trade.

    No strategy imports or simulator output is used to reconstruct candles,
    features, pivots, boundaries, triggers or costs. Diagnostics must certify
    zero context-capacity discards because context reconstruction retains all
    raw active zones. This does not replay all intervening bracket paths.
    """
    check = Checks(identity)
    check.result.update(sampled_trades=len(trades), scope="supplied rows only")
    if trades.empty:
        check.result['note'] = 'No raw trades to inspect; zero-trade accounting is separate.'
        return check.finish()
    fee = float(dataset['fee'] if fee is None else fee)
    p, tick, point = parameters, float(dataset['tick_size']), float(dataset['point_value'])
    check.require('supported execution and stop model', dataset['execution_minutes'] == 1 and p['stop_model'] in ('zone', 'candle'))
    frame, chart = raw['source'], raw['chart']
    check.result['raw_sources'] = raw['identities']
    key = (bool(p['require_fvg']), p.get('zone_boundary', 'wick'))
    if key not in raw.setdefault('formation_cache', {}):
        raw['formation_cache'][key] = formations(chart, *key)
    side, top, bottom = raw['formation_cache'][key]
    bias, hourly = structures(raw, int(p['pivot_len']))
    if 'timestamp_cache' not in raw:
        raw['timestamp_cache'] = ns(chart.index), ns(frame.index)
    ts, source_times = raw['timestamp_cache']
    highs, lows, segments = chart.high.to_numpy(float), chart.low.to_numpy(float), chart.segment.to_numpy()
    source_high, source_low = frame.high.to_numpy(float), frame.low.to_numpy(float)
    epsilon = tick * 1e-7
    ttl = int(p['order_lifetime_bars'])
    price_mode = p['slippage_model'] == 'price'
    slip_points = tick * slippage_ticks
    check.require('context capacity supplied and never discards', diagnostics is not None and diagnostics.get('context_zones_discarded_capacity') == 0)
    expected_top, expected_bottom, expected_touch = [], [], []
    expected_trigger, expected_stop, expected_entry, expected_boundary = [], [], [], []
    expected_features = {name: [] for name in ('prior_atr20', 'prior_volume20', 'zone_width_atr', 'departure_atr', 'departure_rvol', 'signal_age_hours')}
    formation_ok, touch_ok, valid_ok, timeline_ok, structure_ok = [], [], [], [], []
    order_path_ok, expected_exit, expiry, exit_reached = [], [], [], []
    raw_entries, raw_exits = [], []
    for trade in trades.itertuples(index=False):
        born, signal = pd.Timestamp(trade.zone_time).value - FIVE, pd.Timestamp(trade.signal_time).value
        touch, entered = pd.Timestamp(trade.first_touch_time).value, pd.Timestamp(trade.entry_time).value
        exited = pd.Timestamp(trade.exit_time).value
        z, s = int(np.searchsorted(ts, born)), int(np.searchsorted(ts, signal - FIVE))
        t, e = int(np.searchsorted(ts, touch // FIVE * FIVE)), int(np.searchsorted(ts, entered // FIVE * FIVE))
        j = int(np.searchsorted(source_times, entered))
        if max(z, s, t, e) >= len(ts) or j >= len(frame):
            raise ValueError('Trade timestamp outside source')
        formation_ok.append(ts[z] == born and side[z] == trade.side)
        expected_top.append(top[z]); expected_bottom.append(bottom[z])
        quality = raw_quality(raw, z, top[z], bottom[z])
        for name, value in quality.items():
            expected_features[name].append(value)
        expected_features['signal_age_hours'].append((signal - born - FIVE) / (60 * MINUTE))
        overlaps = np.flatnonzero((lows[z + 1:s + 1] <= top[z] + epsilon) & (highs[z + 1:s + 1] >= bottom[z] - epsilon))
        first = z + 1 + int(overlaps[0]) if len(overlaps) else -1
        current_touch = lows[s] <= top[z] + epsilon and highs[s] >= bottom[z] - epsilon
        touch_ok.append(first == t and current_touch and chart.complete.iloc[s] and
                        (t == s if p['entry_eligibility'] == 'first_touch' else t <= s))
        sub = frame.iloc[int(chart.begin.iloc[t]):int(chart.final.iloc[t]) + 1]
        source_hits = np.flatnonzero((sub.low.to_numpy(float) <= top[z] + epsilon) & (sub.high.to_numpy(float) >= bottom[z] - epsilon))
        expected_touch.append(ns(sub.index)[source_hits[0]] if len(source_hits) else -1)
        valid_ok.append(s > z and e - z <= int(p['max_age']) and segments[z] == segments[e] and
            ((lows[z + 1:s + 1] >= bottom[z] - epsilon).all() if trade.side == 1 else (highs[z + 1:s + 1] <= top[z] + epsilon).all()))
        structure_ok.append(bias[z] == trade.side and bias[s] == trade.side and
            (not p['use_htf'] or (hourly[z] == trade.side and hourly[s] == trade.side and (hourly[s + 1:e + 1] == trade.side).all())))
        trigger = highs[s] + tick if trade.side == 1 else lows[s] - tick
        expected_trigger.append(trigger)
        anchor = (bottom[z] if trade.side == 1 else top[z]) if p['stop_model'] == 'zone' else (lows[s] if trade.side == 1 else highs[s])
        expected_stop.append(anchor - trade.side * tick)
        observed = frame.iloc[j]
        timeline_ok.append(source_times[j] == entered and signal <= entered < signal + ttl * FIVE and
            ((observed.high >= trigger - epsilon) if trade.side == 1 else (observed.low <= trigger + epsilon)))
        raw_entry = max(observed.open, trigger) if trade.side == 1 else min(observed.open, trigger)
        raw_entries.append(raw_entry)
        expected_entry.append(raw_entry + (trade.side * slip_points if price_mode else 0))
        expiry.append(signal + ttl * FIVE)
        order_begin = int(np.searchsorted(source_times, signal))
        before_entry_hi, before_entry_lo = source_high[order_begin:j], source_low[order_begin:j]
        order_path_ok.append(((before_entry_hi < trigger - epsilon).all() and (before_entry_lo >= bottom[z] - epsilon).all()) if trade.side == 1 else
                             ((before_entry_lo > trigger + epsilon).all() and (before_entry_hi <= top[z] + epsilon).all()))
        candidates = np.flatnonzero(side[max(0, s - int(p['max_age'])):s + 1] == -trade.side) + max(0, s - int(p['max_age']))
        boundaries = []
        for k in candidates:
            if segments[k] != segments[s]:
                continue
            alive = ((lows[k + 1:s + 1] >= bottom[k] - epsilon).all() if side[k] == 1 else (highs[k + 1:s + 1] <= top[k] + epsilon).all())
            ahead = top[k] >= trigger - epsilon if trade.side == 1 else bottom[k] <= trigger + epsilon
            if alive and ahead:
                boundaries.append(bottom[k] if trade.side == 1 else top[k])
        expected_boundary.append((min(boundaries) if trade.side == 1 else max(boundaries)) if boundaries else np.nan)
        if trade.exit_reason == 'target':
            raw_exit = trade.target
            x = int(np.searchsorted(source_times, exited))
            bar = frame.iloc[x]
            opened_entry = observed.open >= trigger - epsilon if trade.side == 1 else observed.open <= trigger + epsilon
            exit_reached.append(source_times[x] == exited and (x != j or opened_entry) and
                                (bar.high >= trade.target - epsilon if trade.side == 1 else bar.low <= trade.target + epsilon))
        elif trade.exit_reason == 'stop':
            x = int(np.searchsorted(source_times, exited))
            bar = frame.iloc[x]
            entered_at_open = observed.open >= trigger - epsilon if trade.side == 1 else observed.open <= trigger + epsilon
            established = x != j or entered_at_open
            raw_exit = (min(bar.open, trade.stop) if trade.side == 1 else max(bar.open, trade.stop)) if established else trade.stop
            exit_reached.append(source_times[x] == exited and
                                (bar.low <= trade.stop + epsilon if trade.side == 1 else bar.high >= trade.stop - epsilon))
        elif trade.exit_reason in ('end-of-test', 'contract-roll'):
            x = int(np.searchsorted(source_times, exited - MINUTE))
            if x >= len(frame) or source_times[x] != exited - MINUTE:
                raise ValueError('No source close for liquidation')
            raw_exit = frame.close.iloc[x]
            exit_reached.append(True)
        else:
            raise ValueError('Unexpected exit reason: ' + str(trade.exit_reason))
        raw_exits.append(raw_exit)
        expected_exit.append(raw_exit - (trade.side * slip_points if price_mode and trade.exit_reason != 'target' else 0))
    check.require('raw three-candle formation', all(formation_ok))
    for name, values in expected_features.items():
        check.close('independent raw feature: ' + name, trades[name], values)
    for parameter, feature, maximum in (
            ('max_zone_width_atr', 'zone_width_atr', True),
            ('min_departure_atr', 'departure_atr', False),
            ('min_departure_rvol', 'departure_rvol', False),
            ('max_touch_age_hours', 'signal_age_hours', True)):
        threshold = p.get(parameter)
        if threshold is not None:
            values = np.asarray(expected_features[feature])
            passed = values <= threshold if maximum else values >= threshold
            check.require('declared raw feature gate: ' + parameter, (np.isfinite(values) & passed).all())
    check.require('strict positive elapsed signal age', (np.asarray(expected_features['signal_age_hours']) > 0).all())
    check.close('raw selected zone top', trades.zone_top, expected_top)
    check.close('raw selected zone bottom', trades.zone_bottom, expected_bottom)
    check.require('raw first touch and signal physical overlap', all(touch_ok))
    check.require('raw first touch minute', np.array_equal(ns(trades.first_touch_time), np.asarray(expected_touch, dtype=np.int64)))
    check.require('no prior distal wick break, roll or expiry', all(valid_ok))
    check.require('independent chart and hourly alignment', all(structure_ok))
    check.close('raw selected overlap candle trigger', trades.entry_reference, expected_trigger)
    check.close('raw one-tick selected stop', trades.stop, expected_stop)
    check.require('raw entry within elapsed TTL and trigger hit', all(timeline_ok))
    check.require('no prior pending trigger or invalidation', all(order_path_ok))
    check.close('raw gap and slippage aware entry fill', trades.entry, expected_entry)
    check.close('raw exit fill with selected slippage mode', trades.exit, expected_exit)
    check.require('recorded bracket exit reached in observed source minute', all(exit_reached))
    check.close('recorded entry before slippage', trades.entry_price_before_slippage, raw_entries)
    check.close('recorded exit before slippage', trades.exit_price_before_slippage, raw_exits)
    check.require('recorded exclusive order expiry', np.array_equal(ns(trades.order_expiry_time), np.asarray(expiry, dtype=np.int64)))
    check.require('recorded order policy and lifetime', (trades.eligibility_policy == p['entry_eligibility']).all() and (trades.lifetime_bars == ttl).all())
    if diagnostics is not None:
        check.require('execution metadata declarations', diagnostics.get('slippage_model') == p['slippage_model'] and
                      diagnostics.get('entry_eligibility') == p['entry_eligibility'] and diagnostics.get('order_lifetime_bars') == ttl)
    check.close('raw nearest live opposing proximal', trades.opposing_boundary, expected_boundary)
    direction_values = trades.side.to_numpy(float)
    risk = direction_values * (trades.entry - trades.stop).to_numpy(float)
    check.require('positive risk and one contract', (risk > 0).all() and (trades.quantity.to_numpy() == direction_values).all() and np.isin(direction_values, [-1, 1]).all())
    check.close('risk', trades.risk, risk)
    check.close('initial risk alias', trades.initial_risk, risk)
    check.close('cash risk', trades.initial_risk_cash, risk * point)
    check.close('cash risk alias', trades.risk_cash, risk * point)
    check.close('gross cash', trades.gross_pnl, direction_values * (trades.exit - trades.entry).to_numpy(float) * point)
    cash_slip = 0 if price_mode else slip_points * point
    check.close('fees and no double counted slippage', trades.cost, 2 * fee + cash_slip * (1 + (trades.exit_reason != 'target').astype(int)))
    check.close('net cash', trades.net_pnl, trades.gross_pnl - trades.cost)
    check.close('net R', trades.net_r, trades.net_pnl / (risk * point))
    payout = direction_values * (trades.target - trades.entry).to_numpy(float)
    target_distance = risk * p['rr']
    check.require('target rounded toward entry under one tick', ((payout > 0) & (target_distance - payout >= -epsilon) & (target_distance - payout < tick + epsilon)).all())
    check.close('target tick grid', trades.target, np.rint(trades.target / tick) * tick, atol=tick * 1e-6)
    boundary = np.asarray(expected_boundary)
    room = np.where(np.isnan(boundary), np.inf, np.maximum(0, direction_values * (boundary - trades.entry)) / risk)
    check.close('actual entry opposing room', trades.opposing_room_r, room)
    check.require('declared room at fill', (room + 1e-9 >= p['min_opposing_room_r']).all())
    trigger_risk = direction_values * (trades.entry_reference - trades.stop).to_numpy(float)
    signal_room = np.where(np.isnan(boundary), np.inf, np.maximum(0, direction_values * (boundary - trades.entry_reference)) / trigger_risk)
    check.require('declared room at signal', (signal_room + 1e-9 >= p['min_opposing_room_r']).all())
    check.require('exits no earlier than entries', (ns(trades.exit_time) >= ns(trades.entry_time)).all())
    check.require('trades within scored interval', (ns(trades.entry_time) >= pd.Timestamp(dataset['start'], tz='UTC').value).all() and
                  (ns(trades.exit_time) <= pd.Timestamp(dataset['end'], tz='UTC').value).all())
    check.require('at most one trade per zone', not trades.duplicated(['zone_time', 'side', 'zone_top', 'zone_bottom']).any())
    check.require('signals outside warmup', (ns(trades.signal_time) - FIVE >= pd.Timestamp(dataset['start'], tz='UTC').value).all())
    if p['entry_eligibility'] == 'first_touch':
        check.require('first touch outside warmup', (ns(trades.first_touch_time) >= pd.Timestamp(dataset['start'], tz='UTC').value).all())
    check.require('one position at a time', len(trades) < 2 or (ns(trades.entry_time)[1:] >= ns(trades.exit_time)[:-1]).all())
    return check.finish()


def sample_indices(count, maximum=3):
    """Deterministic ordinal strata; never choose a sample by P&L or outcome."""
    if count < 0 or maximum < 1:
        raise ValueError('count must be nonnegative; maximum must be positive')
    if count <= maximum:
        return np.arange(count, dtype=np.int64)
    return np.unique(np.linspace(0, count - 1, maximum, dtype=np.int64))


def audit_ledger(trades, parameters, dataset, equity=None, summary=None,
                 fee=None, slippage_ticks=1, identity='full ledger',
                 equity_has_interval_increments=False):
    """Vector checks cover every supplied trade, including unselected samples.

    Compact daily marks must not claim five-minute maximum drawdown evidence.
    ``equity_has_interval_increments`` is opt-in: taking the final row each day
    does not turn its five-minute net_pnl column into a daily increment.
    ``summary`` supports full-history trades, net_pnl, cost, mean_net_r and
    terminal_equity; any provided field is independently recomputed.
    """
    check = Checks(identity)
    check.result.update(trades=len(trades), scope='every supplied trade')
    p = parameters
    tick, point = float(dataset['tick_size']), float(dataset['point_value'])
    fee = float(dataset['fee'] if fee is None else fee)
    capital = float(p.get('capital', 100000.0))
    cost = 0.0
    if not trades.empty:
        mandatory = ('entry_time', 'exit_time', 'side', 'quantity', 'entry', 'exit',
                     'stop', 'target', 'risk', 'risk_cash', 'gross_pnl', 'cost', 'net_pnl',
                     'net_r', 'zone_time', 'zone_top', 'zone_bottom', 'first_touch_time',
                     'signal_time', 'entry_reference', 'order_expiry_time', 'exit_reason',
                     'initial_risk', 'initial_risk_cash', 'signal_age_hours')
        missing = [name for name in mandatory if name not in trades]
        check.require('complete ledger schema', not missing)
        if missing:
            check.result['missing_columns'] = missing
            return check.finish()
        for name in ('entry', 'exit', 'stop', 'target', 'risk', 'risk_cash', 'gross_pnl',
                     'cost', 'net_pnl', 'net_r', 'zone_top', 'zone_bottom', 'quantity', 'side'):
            check.require('finite ' + name, np.isfinite(trades[name].to_numpy(float)).all())
        side, qty = trades.side.to_numpy(float), trades.quantity.to_numpy(float)
        check.require('signed whole contract quantity', (np.isin(side, (-1, 1)) & (qty * side > 0) & (qty == np.rint(qty))).all())
        check.require('search fixed-contract policy', p.get('sizing_mode', 'fixed_contracts') == 'fixed_contracts')
        check.close('declared fixed quantity', qty, side * p.get('contracts', 1))
        magnitude = np.abs(qty)
        risk = side * (trades.entry - trades.stop).to_numpy(float)
        check.require('strictly positive risk', (risk > 0).all())
        check.close('price risk', trades.risk, risk)
        check.close('price risk alias', trades.initial_risk, risk)
        check.close('cash risk', trades.risk_cash, risk * point * magnitude)
        check.close('cash risk alias', trades.initial_risk_cash, risk * point * magnitude)
        check.close('gross dollars', trades.gross_pnl, qty * (trades.exit - trades.entry).to_numpy(float) * point)
        slip_cash = 0 if p['slippage_model'] == 'price' else slippage_ticks * tick * point
        expected_cost = magnitude * (2 * fee + slip_cash * (1 + trades.exit_reason.ne('target').to_numpy(int)))
        check.close('fees and slippage dollars', trades.cost, expected_cost)
        check.close('net dollars', trades.net_pnl, trades.gross_pnl - trades.cost)
        check.close('net risk return', trades.net_r, trades.net_pnl / (risk * point * magnitude))
        check.require('recognized exit reasons', trades.exit_reason.isin(('target', 'stop', 'contract-roll', 'end-of-test')).all())
        ent, ext, sig, zon, first, expiry = (ns(trades[k]) for k in
            ('entry_time', 'exit_time', 'signal_time', 'zone_time', 'first_touch_time', 'order_expiry_time'))
        check.require('sorted entries', (np.diff(ent) >= 0).all())
        check.require('no overlapping positions', len(trades) < 2 or (ent[1:] >= ext[:-1]).all())
        check.require('exit follows entry', (ext >= ent).all())
        check.require('formation before touch before signal', ((zon <= first) & (first < sig) & (sig <= ent)).all())
        check.require('entry inside elapsed order lifetime', ((ent >= sig) & (ent < sig + int(p['order_lifetime_bars']) * FIVE)).all())
        check.require('correct order expiry', np.array_equal(expiry, sig + int(p['order_lifetime_bars']) * FIVE))
        check.require('one trade per zone', not trades.duplicated(['zone_time', 'side', 'zone_top', 'zone_bottom']).any())
        check.require('nonempty selected zone width', (trades.zone_top > trades.zone_bottom).all())
        check.close('elapsed signal age', trades.signal_age_hours, (sig - zon) / (60 * MINUTE))
        check.require('scored timestamps', (ent >= pd.Timestamp(dataset['start'], tz='UTC').value).all() and
                      (ext <= pd.Timestamp(dataset['end'], tz='UTC').value).all())
        check.require('signals outside warmup', (sig - FIVE >= pd.Timestamp(dataset['start'], tz='UTC').value).all())
        if p['entry_eligibility'] == 'first_touch':
            check.require('first touch signal bucket', ((first >= sig - FIVE) & (first < sig)).all())
        if 'eligibility_policy' in trades:
            check.require('recorded eligibility', trades.eligibility_policy.eq(p['entry_eligibility']).all())
        if 'lifetime_bars' in trades:
            check.require('recorded order lifetime', trades.lifetime_bars.eq(p['order_lifetime_bars']).all())
        payout = side * (trades.target - trades.entry).to_numpy(float)
        requested = risk * float(p['rr'])
        epsilon = tick * 1e-6
        check.require('rounded target distance', ((payout > 0) & (requested - payout >= -epsilon) & (requested - payout < tick + epsilon)).all())
        check.close('tick-aligned target', trades.target, np.rint(trades.target / tick) * tick, atol=epsilon)
        for parameter, feature, maximum in (
                ('max_zone_width_atr', 'zone_width_atr', True), ('min_departure_atr', 'departure_atr', False),
                ('min_departure_rvol', 'departure_rvol', False), ('max_touch_age_hours', 'signal_age_hours', True)):
            threshold = p.get(parameter)
            if threshold is not None:
                values = trades[feature].to_numpy(float)
                check.require('all-trade feature gate: ' + parameter, (np.isfinite(values) & (values <= threshold if maximum else values >= threshold)).all())
        if 'opposing_boundary' in trades and 'opposing_room_r' in trades:
            boundary = trades.opposing_boundary.to_numpy(float)
            room = np.where(np.isnan(boundary), np.inf, np.maximum(0, side * (boundary - trades.entry)) / risk)
            check.close('recorded opposing room', trades.opposing_room_r, room)
            check.require('fill room gate', (room + 1e-9 >= p['min_opposing_room_r']).all())
        cost = float(trades.cost.sum())
    net = float(trades.net_pnl.sum()) if len(trades) else 0.0
    if equity is not None:
        check.result['equity_rows'] = len(equity)
        check.require('nonempty equity', len(equity) > 0)
        if len(equity):
            check.require('ordered compact marks', (np.diff(ns(equity.timestamp)) > 0).all())
            check.require('finite marked equity', np.isfinite(equity.equity.to_numpy(float)).all())
            check.close('terminal cash reconciliation', equity.equity.iloc[-1], capital + net, atol=1e-5)
            if {'balance', 'unrealized_pnl'}.issubset(equity.columns):
                check.close('marked balance relation', equity.equity, equity.balance + equity.unrealized_pnl, atol=1e-5)
                check.close('terminal unrealized flat', equity.unrealized_pnl.iloc[-1], 0)
            if 'contracts' in equity:
                check.require('terminal position flat', equity.contracts.iloc[-1] == 0)
            if equity_has_interval_increments:
                check.close('mark interval increments', equity.net_pnl, np.diff(np.r_[capital, equity.equity]), atol=1e-5)
    if summary is not None:
        expected = dict(trades=len(trades), net_pnl=net, closed_net=net, cost=cost,
                        gross_pnl=net + cost, double_cost_closed_net=net - cost,
                        terminal_equity=capital + net)
        if len(trades):
            expected['mean_net_r'] = float(trades.net_r.mean())
        for name, value in expected.items():
            if name in summary:
                check.close('saved full-period summary: ' + name, summary[name], value, atol=1e-5)
    check.result.update(net_pnl=net, cost=cost)
    return check.finish()


def exact_reference_parity(reference_trades, actual_trades, reference_equity=None,
                           actual_equity=None, identity='reference parity'):
    """Every prior column must match exactly; compact marks cannot pass full parity."""
    check = Checks(identity)
    pairs = [('trades', reference_trades, actual_trades)]
    if reference_equity is not None or actual_equity is not None:
        check.require('both full equity ledgers supplied', reference_equity is not None and actual_equity is not None)
        if reference_equity is not None and actual_equity is not None:
            pairs.append(('equity', reference_equity, actual_equity))
    for name, reference, actual in pairs:
        try:
            pd.testing.assert_frame_equal(reference.reset_index(drop=True), actual.loc[:, reference.columns].reset_index(drop=True),
                                          check_exact=True, check_dtype=True)
            check.require('exact full prior columns: ' + name, True)
        except (AssertionError, KeyError) as error:
            check.require('exact full prior columns: ' + name, False)
            check.result.setdefault('differences', {})[name] = str(error)[:2000]
    return check.finish()


def audit_frozen_inputs(out):
    check = Checks('protocol, Cartesian grid and frozen source')
    protocol = read(out / 'protocol.json')
    manifest = read(out / 'source-manifest.json')
    configs = read(out / protocol['configurations_file'])
    protocol_hash = sha(out / 'protocol.json')
    grid_hash = sha(out / protocol['configurations_file'])
    check.require('protocol checksum', manifest['protocol_checksum'] == protocol_hash)
    check.require('grid protocol checksum', protocol['configurations_checksum'] == grid_hash)
    check.require('grid source checksum', manifest['configurations_checksum'] == grid_hash)
    check.require('source aggregate checksum', hashlib.sha256(json.dumps(manifest['files'], sort_keys=True).encode()).hexdigest() == manifest['source_hash'])
    for item in manifest['files']:
        path = (out / 'source' / item['path']).resolve()
        check.require('source path containment: ' + item['path'], path.is_relative_to((out / 'source').resolve()))
        check.require('source checksum: ' + item['path'], sha(path) == item['checksum'])
    own = next((f for f in manifest['files'] if f['path'] == 'scripts/audit-snd-combinations.py'), None)
    check.require('auditor matches frozen source', own is not None and own['checksum'] == sha(__file__))
    check.require('declared configuration count', len(configs) == protocol['expected_configurations'])
    check.require('unique configuration identities', len({c['config_id'] for c in configs}) == len(configs))
    check.require('unique parameter identities', len({c['parameter_hash'] for c in configs}) == len(configs))
    fields = list(protocol['grid'])
    expected = list(itertools.product(*protocol['grid'].values()))
    observed = [tuple(c['parameters'][k] for k in fields) for c in configs]
    check.require('complete ordered Cartesian grid', observed == expected)
    check.require('per-config canonical parameter hashes', all(c['parameter_hash'] == hashlib.sha256(
        json.dumps(c['parameters'], sort_keys=True, separators=(',', ':')).encode()).hexdigest() for c in configs))
    check.require('market case count', len(configs) * len(protocol['datasets']) == protocol['expected_market_cases'])
    return check.finish(), protocol, manifest, configs


def _compact(record):
    """Retain all failure labels, but do not repeat harmless exact-zero errors."""
    result = dict(record)
    result['max_errors'] = {k: v for k, v in result.get('max_errors', {}).items() if v > 1e-8}
    result.pop('raw_sources', None)
    return result


def audit_shard(folder, dataset, configs_by_id, raw, protocol_hash, source_hash, grid_hash):
    """Verify one immutable attempt; never conceal other failed attempts."""
    folder = Path(folder)
    check = Checks(dataset['symbol'] + '/' + folder.parent.name + '/' + folder.name)
    result, saved = read(folder / 'result.json'), read(folder / 'input.json')
    check.require('shard succeeded', result.get('status') == 'succeeded')
    if result.get('status') != 'succeeded':
        return dict(shard=check.finish(), cases=[], declared_ids=result.get('config_ids', []))
    for key, expected in (('protocol_checksum', protocol_hash), ('source_hash', source_hash)):
        check.require('result identity: ' + key, result.get(key) == expected)
        check.require('input identity: ' + key, saved.get(key) == expected)
    check.require('input configuration identity', saved.get('configurations_checksum') == grid_hash)
    check.require('result market', result.get('symbol') == dataset['symbol'])
    check.require('input market', saved.get('symbol') == dataset['symbol'])
    check.require('terminal shard status', read(folder / 'status.json').get('status') == 'succeeded')
    names = [a['name'] for a in result['artifacts']]
    required = {'cases.json', 'trades.parquet', 'equity-daily.parquet', 'periods.parquet', 'training.parquet', 'weekly.parquet'}
    check.require('complete unique output manifest', required.issubset(names) and len(names) == len(set(names)))
    for item in result['artifacts']:
        path = (folder / item['name']).resolve()
        check.require('output path containment: ' + item['name'], path.is_relative_to(folder.resolve()))
        check.require('output checksum: ' + item['name'], sha(path) == item['checksum'])
    cases = read(folder / 'cases.json')
    ids = [str(c['config_id']) for c in cases]
    check.require('unique case identities', len(ids) == len(set(ids)))
    check.require('result identities equal saved cases', ids == list(result['config_ids']))
    check.require('input identities equal saved cases', ids == saved.get('config_ids'))
    start, stop = saved.get('start_index'), saved.get('stop_index')
    bounds_valid = isinstance(start, int) and isinstance(stop, int) and 0 <= start < stop <= len(configs_by_id)
    check.require('valid configuration slice bounds', bounds_valid)
    check.require('exact declared configuration slice', bounds_valid and ids == list(configs_by_id)[start:stop])
    check.require('all configs predeclared', set(ids).issubset(configs_by_id))
    frames = {name: pd.read_parquet(folder / name) for name in required if name.endswith('.parquet')}
    for name, frame in frames.items():
        check.require('config column: ' + name, 'config_id' in frame)
        if 'config_id' in frame:
            check.require('no unexpected cases: ' + name, set(frame.config_id.dropna().astype(str)).issubset(ids))
            check.require('no missing config identity: ' + name, not frame.config_id.isna().any())
    trades, daily = frames['trades.parquet'], frames['equity-daily.parquet']
    tgroups = {str(k): g.drop(columns='config_id').reset_index(drop=True) for k, g in trades.groupby('config_id', sort=False)}
    egroups = {str(k): g.drop(columns='config_id').reset_index(drop=True) for k, g in daily.groupby('config_id', sort=False)}
    records = []
    for case in cases:
        cid = str(case['config_id'])
        entry = dict(config_id=cid, status=case['status'], passed=False, checks=0, failures=[])
        try:
            if case['status'] != 'succeeded':
                raise ValueError('Case did not succeed: ' + str(case['status']))
            config = configs_by_id[cid]
            t = tgroups.get(cid, trades.iloc[:0].drop(columns='config_id'))
            if cid not in egroups:
                raise ValueError('Missing equity even for a zero-trade configuration')
            e = egroups[cid]
            ledger = audit_ledger(t, config['parameters'], dataset, e, case.get('summary'),
                                  identity=dataset['symbol'] + '/' + cid, equity_has_interval_increments=True)
            sample = sample_indices(len(t))
            sampled = audit_raw_trades(t.iloc[sample].reset_index(drop=True), config['parameters'], dataset, raw,
                                       diagnostics=case.get('diagnostics'), identity=dataset['symbol'] + '/' + cid + '/raw-sample')
            entry.update(passed=ledger['passed'] and sampled['passed'], checks=ledger['checks'] + sampled['checks'],
                         failures=ledger['failures'] + sampled['failures'], trades=len(t), sampled_trades=len(sample),
                         sample_ordinals=sample.tolist(), ledger=_compact(ledger), raw_sample=_compact(sampled))
            diagnostic_count = case.get('diagnostics', {}).get('trades')
            if diagnostic_count != len(t):
                entry['passed'] = False
                entry['failures'].append('Diagnostic trade count does not match full shard ledger')
            entry['checks'] += 1
        except Exception as error:
            entry['failures'].append(type(error).__name__ + ': ' + str(error))
        records.append(entry)
    return dict(shard=_compact(check.finish()), cases=records, declared_ids=ids)


def _save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False), encoding='utf-8')


def audit_market(output, dataset, configurations, protocol, manifest, max_shards=None):
    """One market per process; no raw cache or output file is shared by workers."""
    out, symbol = Path(output), dataset['symbol']
    configs = {c['config_id']: c for c in configurations}
    result = dict(symbol=symbol, observed=[], raw_sources=[], failures=[], shards=[],
                  audited_cases=0, exhaustive_accounting_trades=0, raw_sampled_trades=0, total_checks=0)
    try:
        print('Independent raw-source preparation: ' + symbol, flush=True)
        raw = raw_market(dataset)
        result['raw_sources'] = raw['identities']
        shard_dirs = sorted((out / 'sweep' / symbol).glob('shard-*'))
        if max_shards:
            shard_dirs = shard_dirs[:max_shards]
        for shard in shard_dirs:
            attempts = sorted(shard.glob('attempt-*'))
            completed = [a for a in attempts if (a / 'result.json').is_file()]
            successes = [a for a in completed if read(a / 'result.json').get('status') == 'succeeded']
            attempt_status = [dict(path=str(a.relative_to(out)), status=read(a / 'result.json').get('status') if (a / 'result.json').is_file() else 'incomplete') for a in attempts]
            if len(successes) != 1:
                result['failures'].append(dict(identity=symbol + '/' + shard.name, failures=['Require exactly one successful attempt'], attempts=attempt_status))
                continue
            chosen = successes[0]
            try:
                report = audit_shard(chosen, dataset, configs, raw, manifest['protocol_checksum'], manifest['source_hash'], protocol['configurations_checksum'])
                report['attempts'] = attempt_status
                result['observed'].extend(report['declared_ids'])
                result['audited_cases'] += len(report['cases'])
                result['exhaustive_accounting_trades'] += sum(c.get('trades', 0) for c in report['cases'])
                result['raw_sampled_trades'] += sum(c.get('sampled_trades', 0) for c in report['cases'])
                result['total_checks'] += report['shard']['checks'] + sum(c['checks'] for c in report['cases'])
                if not report['shard']['passed']:
                    result['failures'].append(dict(identity=report['shard']['identity'], failures=report['shard']['failures']))
                result['failures'].extend(dict(identity=symbol + '/' + c['config_id'], failures=c['failures']) for c in report['cases'] if not c['passed'])
                destination = out / 'audit' / 'sweep' / symbol / (shard.name + '.json')
                _save(destination, report)
                result['shards'].append(dict(symbol=symbol, shard=shard.name, audit_path=str(destination.relative_to(out)), checksum=sha(destination), cases=len(report['cases'])))
                print(f"{symbol}/{shard.name}: {len(report['cases'])} cases; {sum(not c['passed'] for c in report['cases'])} case failures", flush=True)
            except Exception as error:
                result['failures'].append(dict(identity=str(chosen.relative_to(out)), failures=[type(error).__name__ + ': ' + str(error)]))
    except Exception as error:
        result['failures'].append(dict(identity=symbol, failures=[type(error).__name__ + ': ' + str(error)]))
    ids = result['observed']
    result['coverage'] = dict(observed=len(ids), unique=len(set(ids)), missing=sorted(set(configs) - set(ids)),
                             unexpected=sorted(set(ids) - set(configs)), duplicate_count=len(ids) - len(set(ids)))
    full = not result['coverage']['missing'] and not result['coverage']['unexpected'] and not result['coverage']['duplicate_count'] and result['audited_cases'] == len(configs)
    result.update(status='failed' if result['failures'] else ('passed' if full else 'incomplete'),
                  protocol_checksum=manifest['protocol_checksum'], source_hash=manifest['source_hash'])
    destination = out / 'audit' / 'sweep' / (symbol + '.json')
    _save(destination, result)
    result['market_audit_path'], result['market_audit_checksum'] = str(destination.relative_to(out)), sha(destination)
    return result


def aggregate_markets(records, protocol):
    """Combine coverage without counting duplicated markets or hiding failures."""
    failures = [failure for r in records for failure in r['failures']]
    if len({r['symbol'] for r in records}) != len(records):
        failures.append(dict(identity='market aggregation', failures=['Duplicate market audit records']))
    if any(r['symbol'] not in protocol['markets'] for r in records):
        failures.append(dict(identity='market aggregation', failures=['Undeclared market audit record']))
    coverage = {r['symbol']: r['coverage'] for r in records}
    counts = {key: sum(r[key] for r in records) for key in
              ('audited_cases', 'exhaustive_accounting_trades', 'raw_sampled_trades', 'total_checks')}
    complete = set(coverage) == set(protocol['markets']) and len(records) == len(protocol['markets']) and all(
        not c['missing'] and not c['unexpected'] and not c['duplicate_count'] for c in coverage.values()) and counts['audited_cases'] == protocol['expected_market_cases']
    return dict(**counts, complete_sweep=complete, coverage=coverage, failures=failures,
                raw_sources=[s for r in records for s in r['raw_sources']], shards=[s for r in records for s in r['shards']],
                market_audits=[dict(symbol=r['symbol'], status=r['status'], path=r.get('market_audit_path'),
                                   checksum=r.get('market_audit_checksum')) for r in records])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=DEFAULT_OUT)
    parser.add_argument('--symbol', action='append', help='Restrict a diagnostic audit; result remains explicitly partial.')
    parser.add_argument('--max-shards', type=int, help='Diagnostic limit per market, never a complete sweep audit.')
    parser.add_argument('--workers', type=int, choices=(1, 2, 3, 4), default=4, help='Independent market processes; default 4.')
    args = parser.parse_args()
    if args.max_shards is not None and args.max_shards < 1:
        parser.error('--max-shards must be positive')
    out = args.output.resolve()
    source, protocol, manifest, configurations = audit_frozen_inputs(out)
    runtime = {'scripts/audit-snd-combinations.py': __file__}
    require_frozen_runtime(manifest, runtime)
    selected_symbols = args.symbol or list(protocol['markets'])
    if not set(selected_symbols).issubset(protocol['markets']):
        parser.error('--symbol must be a declared market')
    datasets = [d for d in protocol['datasets'] if d['symbol'] in selected_symbols]
    records = []
    if args.workers == 1:
        records = [audit_market(str(out), d, configurations, protocol, manifest, args.max_shards) for d in datasets]
    else:
        with ProcessPoolExecutor(max_workers=min(args.workers, len(datasets))) as pool:
            futures = {pool.submit(audit_market, str(out), d, configurations, protocol, manifest, args.max_shards): d['symbol'] for d in datasets}
            for future in as_completed(futures):
                symbol = futures[future]
                try:
                    records.append(future.result())
                except Exception as error:
                    records.append(dict(symbol=symbol, observed=[], raw_sources=[], shards=[], status='failed',
                        failures=[dict(identity=symbol, failures=[type(error).__name__ + ': ' + str(error)])],
                        coverage=dict(observed=0, unique=0, missing=[c['config_id'] for c in configurations], unexpected=[], duplicate_count=0),
                        audited_cases=0, exhaustive_accounting_trades=0, raw_sampled_trades=0, total_checks=0))
    records.sort(key=lambda r: protocol['markets'].index(r['symbol']))
    combined = aggregate_markets(records, protocol)
    failures, complete = combined['failures'], combined['complete_sweep']
    if not source['passed']:
        failures.append(dict(identity=source['identity'], failures=source['failures']))
    result = dict(audited_at=datetime.now(timezone.utc).isoformat(),
        status='failed' if failures else ('passed' if complete else 'incomplete'),
        **combined, declared_cases=protocol['expected_market_cases'], workers=args.workers,
        protocol_checksum=manifest['protocol_checksum'], source_hash=manifest['source_hash'], script_checksum=sha(__file__),
        source_checks=source,
        scope='Search sweep only: every saved trade accounted for; raw conditions reconstructed for first/middle/last trade per configuration. Required controls and selected-fold validation are separate evidence.',
        limitations=['Raw reconstruction is sampled, not every trade or every intervening bracket path.',
            'Daily equity does not independently reconstruct exact five-minute drawdown; saved full-resolution metrics require reference parity.',
            'Zero context-capacity discards required and checked before nearest-zone reconstruction.',
            'This audit does not validate selection statistics, risk-budget policies, prospective outcomes or broker execution.'])
    result['total_checks'] += source['checks']
    require_frozen_runtime(manifest, runtime)
    _save(out / 'independent-sweep-audit.json', result)
    print(json.dumps({k: result[k] for k in ('status', 'complete_sweep', 'audited_cases', 'exhaustive_accounting_trades', 'raw_sampled_trades', 'total_checks')}, indent=2))
    return 0 if result['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
