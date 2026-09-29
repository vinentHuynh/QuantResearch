"""Independent raw-candle, feature, ledger and control audit for zone quality.

This script imports no strategy module. It independently aggregates immutable
minute data, reconstructs formations/structure, and audits every declared case.
It does not select or rerun models and preserves failures and zero-trade cases.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / 'reports/snd-zone-quality-2026-09-25'
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
    return raw['quality'][z]


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


def formations(chart, require_fvg):
    opened, closed, high, low = (chart[key].to_numpy(float) for key in ('open', 'close', 'high', 'low'))
    complete, segment, stamps = chart.complete.to_numpy(bool), chart.segment.to_numpy(), ns(chart.index)
    side = np.zeros(len(chart), dtype=int)
    consecutive = complete[2:] & complete[1:-1] & complete[:-2] & (stamps[2:] - stamps[:-2] == 2 * FIVE) & (segment[2:] == segment[:-2])
    demand = consecutive & (closed[:-2] < opened[:-2]) & (closed[1:-1] > opened[1:-1]) & ((low[2:] if require_fvg else closed[2:]) > high[:-2])
    supply = consecutive & (closed[:-2] > opened[:-2]) & (closed[1:-1] < opened[1:-1]) & ((high[2:] if require_fvg else closed[2:]) < low[:-2])
    side[2:] = demand.astype(int) - supply.astype(int)
    top, bottom = np.full(len(chart), np.nan), np.full(len(chart), np.nan)
    top[2:] = np.where(side[2:] == 1, high[:-2], np.maximum.reduce([high[:-2], high[1:-1], high[2:]]))
    bottom[2:] = np.where(side[2:] == 1, np.minimum.reduce([low[:-2], low[1:-1], low[2:]]), low[:-2])
    return side, top, bottom


def audit_case(out, case, dataset, capital, raw):
    check = Checks(case['symbol'] + '/' + case['variant'])
    folder = out / case['symbol'] / case['variant']
    result, saved = read(folder / 'result.json'), read(folder / 'input.json')
    check.require('case succeeded', result.get('status') == 'succeeded')
    if result.get('status') != 'succeeded':
        return check.finish()
    check.result['result_checksum'] = sha(folder / 'result.json')
    check.require('input declaration', saved['parameters'] == case['parameters'] and saved['dataset'] == dataset)
    check.require('cost declaration', saved['fee'] == case['fee'] and saved['slippage_ticks'] == case['slippage_ticks'])
    check.require('result parameters', result['parameters'] == case['parameters'])
    check.require('result costs', result['fee'] == case['fee'] and result['slippage_ticks'] == case['slippage_ticks'])
    check.require('result protocol hash', result['protocol_checksum'] == sha(out / 'protocol.json'))
    check.require('result source hash', result['source_hash'] == read(out / 'source-manifest.json')['source_hash'])
    check.require('input protocol hash', saved['protocol_checksum'] == result['protocol_checksum'])
    check.require('input source hash', saved['source_hash'] == result['source_hash'])
    check.require('required output manifest entries', {item['name'] for item in result['artifacts']} == {'trades.csv', 'equity.parquet'})
    for item in result['artifacts']:
        path = (folder / item['name']).resolve()
        if not path.is_relative_to(folder.resolve()):
            raise ValueError('Artifact escapes case folder')
        check.require('artifact checksum: ' + item['name'], sha(path) == item['checksum'])
    trades, equity = pd.read_csv(folder / 'trades.csv'), pd.read_parquet(folder / 'equity.parquet')
    check.result.update(trades=len(trades), equity_rows=len(equity))
    check.require('recorded trade count', result['diagnostics']['trades'] == len(trades))
    check.require('strictly increasing marks', len(equity) > 0 and (np.diff(ns(equity.timestamp)) > 0).all())
    check.close('marked increments', equity.net_pnl, np.diff(np.r_[capital, equity.equity]), atol=1e-5)
    check.close('marked balance relation', equity.equity, equity.balance + equity.unrealized_pnl, atol=1e-5)
    check.close('final realized reconciliation', equity.equity.iloc[-1] - capital, trades.net_pnl.sum(), atol=1e-5)
    check.require('final position flat', equity.contracts.iloc[-1] == 0)
    check.close('final unrealized flat', equity.unrealized_pnl.iloc[-1], 0)
    if trades.empty:
        check.result['note'] = 'Zero-trade case retained; no raw trade geometries available.'
        return check.finish()
    p, tick, point = case['parameters'], float(dataset['tick_size']), float(dataset['point_value'])
    check.require('supported execution and fixed zone stop', dataset['execution_minutes'] == 1 and p['stop_model'] == 'zone')
    frame, chart = raw['source'], raw['chart']
    check.result['raw_sources'] = raw['identities']
    side, top, bottom = formations(chart, p['require_fvg'])
    bias, hourly = structures(raw, int(p['pivot_len']))
    ts, source_times = ns(chart.index), ns(frame.index)
    highs, lows, segments = chart.high.to_numpy(float), chart.low.to_numpy(float), chart.segment.to_numpy()
    source_high, source_low = frame.high.to_numpy(float), frame.low.to_numpy(float)
    epsilon = tick * 1e-7
    ttl = int(p['order_lifetime_bars'])
    price_mode = p['slippage_model'] == 'price'
    slip_points = tick * case['slippage_ticks']
    check.require('context capacity never discards', result['diagnostics']['context_zones_discarded_capacity'] == 0)
    expected_top, expected_bottom, expected_touch = [], [], []
    expected_trigger, expected_stop, expected_entry, expected_boundary = [], [], [], []
    expected_features = {name: [] for name in ('prior_atr20', 'prior_volume20', 'zone_width_atr', 'departure_atr', 'departure_rvol', 'signal_age_hours')}
    formation_ok, touch_ok, valid_ok, timeline_ok, structure_ok = [], [], [], [], []
    order_path_ok, expected_exit, expiry = [], [], []
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
        expected_stop.append(bottom[z] - tick if trade.side == 1 else top[z] + tick)
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
        elif trade.exit_reason == 'stop':
            x = int(np.searchsorted(source_times, exited))
            bar = frame.iloc[x]
            entered_at_open = observed.open >= trigger - epsilon if trade.side == 1 else observed.open <= trigger + epsilon
            established = x != j or entered_at_open
            raw_exit = (min(bar.open, trade.stop) if trade.side == 1 else max(bar.open, trade.stop)) if established else trade.stop
        elif trade.exit_reason in ('end-of-test', 'contract-roll'):
            x = int(np.searchsorted(source_times, exited - MINUTE))
            if x >= len(frame) or source_times[x] != exited - MINUTE:
                raise ValueError('No source close for liquidation')
            raw_exit = frame.close.iloc[x]
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
    check.close('raw wick zone top', trades.zone_top, expected_top)
    check.close('raw wick zone bottom', trades.zone_bottom, expected_bottom)
    check.require('raw first touch and signal physical overlap', all(touch_ok))
    check.require('raw first touch minute', np.array_equal(ns(trades.first_touch_time), np.asarray(expected_touch, dtype=np.int64)))
    check.require('no prior distal wick break, roll or expiry', all(valid_ok))
    check.require('independent chart and hourly alignment', all(structure_ok))
    check.close('raw selected overlap candle trigger', trades.entry_reference, expected_trigger)
    check.close('raw one-tick zone stop', trades.stop, expected_stop)
    check.require('raw entry within elapsed TTL and trigger hit', all(timeline_ok))
    check.require('no prior pending trigger or invalidation', all(order_path_ok))
    check.close('raw gap and slippage aware entry fill', trades.entry, expected_entry)
    check.close('raw exit fill with selected slippage mode', trades.exit, expected_exit)
    check.close('recorded entry before slippage', trades.entry_price_before_slippage, raw_entries)
    check.close('recorded exit before slippage', trades.exit_price_before_slippage, raw_exits)
    check.require('recorded exclusive order expiry', np.array_equal(ns(trades.order_expiry_time), np.asarray(expiry, dtype=np.int64)))
    check.require('recorded order policy and lifetime', (trades.eligibility_policy == p['entry_eligibility']).all() and (trades.lifetime_bars == ttl).all())
    check.require('execution metadata declarations', result['diagnostics']['slippage_model'] == p['slippage_model'] and
                  result['diagnostics']['entry_eligibility'] == p['entry_eligibility'] and
                  result['diagnostics']['order_lifetime_bars'] == ttl)
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
    check.close('fees and no double counted slippage', trades.cost, 2 * case['fee'] + cash_slip * (1 + (trades.exit_reason != 'target').astype(int)))
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


def audit_sources(out):
    check = Checks('frozen campaign/source identity')
    manifest = read(out / 'source-manifest.json')
    check.require('frozen protocol checksum', manifest['protocol_checksum'] == sha(out / 'protocol.json'))
    aggregate = hashlib.sha256(json.dumps(manifest['files'], sort_keys=True).encode()).hexdigest()
    check.require('aggregate source hash', manifest['source_hash'] == aggregate)
    for item in manifest['files']:
        path = (out / 'source' / item['path']).resolve()
        check.require('source path containment: ' + item['path'], path.is_relative_to((out / 'source').resolve()))
        check.require('frozen source checksum: ' + item['path'], sha(path) == item['checksum'])
    return check.finish()


def audit_controls(out, protocol):
    """Check the full original schemas, not selected matching trade attributes."""
    records, prior_verified = [], {}
    definitions = [(d['symbol'], 'strict_fvg', 'snd-fresh-retest-2026-09-24', 'candidate')
                   for d in protocol['datasets']]
    definitions += [(symbol, 'baseline', 'snd-entry-research-2026-09-25', 'relaxed_first_1')
                    for symbol in ('MNQ', 'MGC')]
    for symbol, variant, prior_name, prior_variant in definitions:
        check = Checks(f'control {symbol}/{variant} == {prior_name}/{prior_variant}')
        try:
            previous = ROOT / 'reports' / prior_name
            prior_protocol = read(previous / 'protocol.json')
            if prior_name not in prior_verified:
                prior_verified[prior_name] = audit_sources(previous)
            check.require('prior frozen source identity', prior_verified[prior_name]['passed'])
            old_data = next(d for d in prior_protocol['datasets'] if d['symbol'] == symbol)
            current_data = next(d for d in protocol['datasets'] if d['symbol'] == symbol)
            check.require('identical source data and economics', old_data == current_data)
            old_def = next(c for c in prior_protocol['cases'] if c['symbol'] == symbol and c['variant'] == prior_variant)
            current_def = next(c for c in protocol['cases'] if c['symbol'] == symbol and c['variant'] == variant)
            check.require('identical shared parameters', all(current_def['parameters'].get(k) == v for k, v in old_def['parameters'].items()))
            check.require('quality filters disabled for controls', all(current_def['parameters'][k] is None for k in
                ('max_zone_width_atr', 'min_departure_atr', 'min_departure_rvol', 'max_touch_age_hours')))
            check.require('identical fees and slippage', all(old_def[k] == current_def[k] for k in ('fee', 'slippage_ticks')))
            check.require('identical declared capital', prior_protocol['capital'] == protocol['capital'])
            old_folder, new_folder = previous / symbol / prior_variant, out / symbol / variant
            old_result = read(old_folder / 'result.json')
            check.require('prior case succeeded', old_result['status'] == 'succeeded')
            check.require('prior case protocol identity', old_result['protocol_checksum'] == sha(previous / 'protocol.json'))
            check.require('prior case source identity', old_result['source_hash'] == read(previous / 'source-manifest.json')['source_hash'])
            for item in old_result['artifacts']:
                check.require('prior artifact hash: ' + item['name'], sha(old_folder / item['name']) == item['checksum'])
            check.result['compared'] = []
            for name in ('trades.csv', 'equity.parquet'):
                load = pd.read_csv if name.endswith('.csv') else pd.read_parquet
                old, new = load(old_folder / name), load(new_folder / name)
                comparison = dict(artifact=name, prior_rows=len(old), current_rows=len(new), compared_columns=list(old.columns))
                try:
                    pd.testing.assert_frame_equal(old, new.loc[:, old.columns], check_exact=True, check_dtype=True)
                    check.require('exact prior schema values: ' + name, True)
                    if name == 'equity.parquet':
                        check.require('exact equity columns', list(old.columns) == list(new.columns))
                except (AssertionError, KeyError) as error:
                    check.require('exact prior schema values: ' + name, False)
                    comparison['difference'] = str(error)[:2000]
                check.result['compared'].append(comparison)
        except Exception as error:
            check.require(type(error).__name__ + ': ' + str(error), False)
        records.append(check.finish())
        print(check.result['identity'] + ': ' + ('passed' if check.result['passed'] else str(check.result['failures'])), flush=True)
    return records, prior_verified


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    out = args.output.resolve()
    protocol, records = read(out / 'protocol.json'), []
    source_checks = audit_sources(out)
    controls, prior_source_checks = audit_controls(out, protocol)
    for dataset in protocol['datasets']:
        print('Reading immutable raw candles: ' + dataset['symbol'], flush=True)
        try:
            raw = raw_market(dataset)
        except Exception as error:
            raw = None
            raw_error = type(error).__name__ + ': ' + str(error)
        for case in [c for c in protocol['cases'] if c['symbol'] == dataset['symbol']]:
            identity = case['symbol'] + '/' + case['variant']
            try:
                if raw is None:
                    raise ValueError(raw_error)
                record = audit_case(out, case, dataset, protocol['capital'], raw)
            except Exception as error:
                record = dict(identity=identity, passed=False, checks=0, failures=[type(error).__name__ + ': ' + str(error)])
            records.append(record)
            print(identity + ': ' + ('passed' if record['passed'] else 'FAILED ' + str(record['failures'])), flush=True)
        del raw
    checked = [source_checks, *prior_source_checks.values(), *controls, *records]
    failures = [dict(identity=r['identity'], failures=r['failures']) for r in checked if not r['passed']]
    if len(records) != protocol['expected_cases'] or len(records) != len(protocol['cases']):
        failures.append(dict(identity='protocol', failures=['Missing declared cases']))
    script_hash = sha(__file__)
    frozen_script = out / 'audit-source' / ('audit-snd-zone-quality-' + script_hash[:16] + '.py')
    frozen_script.parent.mkdir(exist_ok=True)
    if not frozen_script.exists():
        shutil.copyfile(__file__, frozen_script)
    if sha(frozen_script) != script_hash:
        raise ValueError('Audit source snapshot is not exact')
    result = dict(audited_at=datetime.now(timezone.utc).isoformat(), status='passed' if not failures else 'failed',
        script_checksum=sha(__file__), protocol_checksum=sha(out / 'protocol.json'),
        source_manifest_checksum=sha(out / 'source-manifest.json'), declared_cases=len(protocol['cases']),
        total_checks=sum(r['checks'] for r in checked), failures=failures, records=records,
        source_checks=source_checks, controls=controls, prior_source_checks=prior_source_checks,
        audit_source_snapshot=str(frozen_script.relative_to(out)),
        scope='Frozen source/data/output hashes and six exact historical controls. Independent raw source grouping, twenty complete pre-base true ranges/volumes, width and departure ratios, elapsed signal age and declared feature gates. Strict/relaxed formation, chart/hour structure, wick bounds, first physical touch, selected overlap trigger, elapsed TTL, pending validity, gap/slippage fills, opposing room, target rounding, ledger accounting and costs.',
        limitations=['Checks recorded exits and raw fill prices, but does not replay every possible intervening bracket exit; dedicated execution tests cover chronology.',
            'Context reconstruction assumes no capacity discards; explicitly checked for every case.',
            'Observed source cannot establish unobserved intraminute event order, queue priority, fill probability, or prospective profitability.'])
    (out / 'independent-audit.json').write_text(json.dumps(result, indent=2, allow_nan=False), encoding='utf-8')
    print(json.dumps({key: result[key] for key in ('status', 'declared_cases', 'total_checks', 'failures')}, indent=2))
    return 0 if not failures else 1


if __name__ == '__main__':
    raise SystemExit(main())
