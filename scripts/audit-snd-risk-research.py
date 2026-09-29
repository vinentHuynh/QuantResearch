"""Independent source-candle, frozen quantity and accounting audit for SND risk research.

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

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / 'reports/snd-risk-research-2026-09-25'
PRIOR = ROOT / 'reports/snd-entry-research-2026-09-25'
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
                identities=identities, directions={})


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


def audit_marks(check, trades, equity, raw, capital, point, fee, slip_cash):
    """Rebuild every mark from ledger cash events and independently read closes.

    Intraminute fills occur after a mark bearing the minute's opening stamp.
    End-of-test liquidation applies at the final close. A contract-roll exit is
    dated at the old contract's final close but its cash is recognized when the
    next source row reveals the transition, matching the documented adjustment.
    """
    marks, source_times = ns(equity.timestamp), ns(raw['source'].index)
    changes, positions, bases = (np.zeros(len(marks), dtype=float) for _ in range(3))
    valid_events = True
    for trade in trades.itertuples(index=False):
        quantity = float(trade.quantity)
        count = abs(quantity)
        entry_cost = count * (fee + slip_cash)
        exit_cost = count * (fee + (0 if trade.exit_reason == 'target' else slip_cash))
        opened, closed = pd.Timestamp(trade.entry_time).value, pd.Timestamp(trade.exit_time).value
        opening = int(np.searchsorted(marks, opened, side='right'))
        if trade.exit_reason == 'end-of-test':
            closing = int(np.searchsorted(marks, closed, side='left'))
        elif trade.exit_reason == 'contract-roll':
            new_source = int(np.searchsorted(source_times, closed, side='left'))
            closing = int(np.searchsorted(marks, source_times[new_source], side='right'))
        else:
            closing = int(np.searchsorted(marks, closed, side='right'))
        if max(opening, closing) >= len(marks):
            valid_events = False
            continue
        changes[opening] -= entry_cost
        changes[closing] += trade.gross_pnl - exit_cost
        positions[opening] += quantity
        positions[closing] -= quantity
        bases[opening] += quantity * trade.entry
        bases[closing] -= quantity * trade.entry
    close_indices = np.searchsorted(source_times, marks - MINUTE)
    valid_closes = (close_indices < len(source_times)).all()
    if valid_closes:
        valid_closes = np.array_equal(source_times[close_indices], marks - MINUTE)
    check.require('every equity mark maps to an observed source close', valid_closes)
    check.require('all ledger cash events map to equity marks', valid_events)
    if valid_closes and valid_events:
        balance = capital + np.cumsum(changes)
        quantity = np.cumsum(positions)
        unrealized = (quantity * raw['source'].close.to_numpy(float)[close_indices] - np.cumsum(bases)) * point
        check.close('independent marked signed contracts', equity.contracts, quantity)
        check.close('independent marked realized balance', equity.balance, balance, atol=1e-5)
        check.close('independent marked unrealized cash', equity.unrealized_pnl, unrealized, atol=1e-5)
        check.close('independent full marked equity', equity.equity, balance + unrealized, atol=1e-5)


def audit_sizing(check, trades, parameters, point, fee, slip_cash):
    q = trades.contracts_abs.to_numpy(float)
    side = trades.side.to_numpy(float)
    planned_per = np.abs(trades.entry_reference - trades.stop).to_numpy(float) * point + 2 * fee + 2 * slip_cash
    risk_mode = parameters['sizing_mode'] == 'fixed_risk'
    if risk_mode:
        uncapped = np.floor(float(parameters['risk_budget']) / planned_per)
        expected = np.minimum(int(parameters['max_contracts']), uncapped)
        capped = uncapped > int(parameters['max_contracts'])
        check.close('recorded fixed dollar budget', trades.risk_budget, parameters['risk_budget'])
        check.require('planned loss stays within frozen budget', (planned_per * q <= float(parameters['risk_budget']) + 1e-7).all())
    else:
        expected = np.full(len(q), int(parameters['contracts']))
        capped = np.zeros(len(q), dtype=bool)
        check.require('no budget claimed for fixed contracts', trades.risk_budget.isna().all())
    check.require('sizing mode declaration', (trades.sizing_mode == parameters['sizing_mode']).all())
    check.require('positive integral whole contract count', ((q >= 1) & (q == np.floor(q))).all())
    check.close('quantity frozen from signal trigger, not fill', q, expected)
    check.close('signed quantity matches direction', trades.quantity, side * q)
    check.require('quantity cap flag', np.array_equal(trades.quantity_capped.to_numpy(bool), capped))
    check.close('cost inclusive planned risk per contract', trades.planned_stop_risk_per_contract, planned_per)
    check.close('cost inclusive planned position risk', trades.planned_stop_risk_cash, q * planned_per)
    actual_per = trades.risk.to_numpy(float) * point + 2 * fee + slip_cash * (2 if parameters['slippage_model'] == 'cash' else 1)
    check.close('actual entry stop risk per contract', trades.actual_stop_risk_per_contract, actual_per)
    check.close('actual entry total stop risk', trades.actual_stop_risk_cash, q * actual_per)
    if risk_mode:
        overshoot = np.maximum(0, q * actual_per - float(parameters['risk_budget']))
        check.close('gap risk budget overshoot', trades.risk_budget_overshoot_cash, overshoot)
    else:
        check.require('no budget overshoot claimed for fixed contracts', trades.risk_budget_overshoot_cash.isna().all())
    check.require('nonempty unique order identities', trades.order_id.notna().all() and trades.order_id.is_unique)
    check.require('nonempty unique traded zone identities', trades.zone_id.notna().all() and trades.zone_id.is_unique)


def prior_parity(check, folder, case):
    p = case['parameters']
    if p['sizing_mode'] != 'fixed_contracts' or int(p['contracts']) != 1:
        return
    mapping = {('cash', 1.25, 1): 'relaxed_first_1', ('cash', 2.5, 2): 'relaxed_first_1_double_cost',
               ('price', 1.25, 1): 'relaxed_first_1_price_1', ('price', 1.25, 2): 'relaxed_first_1_price_2',
               ('price', 2.5, 2): 'relaxed_first_1_price_2_double_fee'}
    variant = mapping.get((p['slippage_model'], case['fee'], case['slippage_ticks']))
    if variant is None or case['symbol'] != 'MNQ':
        check.require('fixed-contract control has known prior parity mapping', False)
        return
    prior = PRIOR / case['symbol'] / variant
    old_trades, new_trades = pd.read_csv(prior / 'trades.csv'), pd.read_csv(folder / 'trades.csv')
    old_equity, new_equity = pd.read_parquet(prior / 'equity.parquet'), pd.read_parquet(folder / 'equity.parquet')
    for name, old, new in [('trade columns', old_trades, new_trades), ('all equity marks', old_equity, new_equity)]:
        try:
            pd.testing.assert_frame_equal(new[old.columns], old, check_exact=True, check_dtype=False)
            check.require('exact prior control parity: ' + name, True)
        except AssertionError as error:
            check.require('exact prior control parity: ' + name, False)
            check.result.setdefault('parity_errors', []).append(str(error)[:500])
    check.result['prior_control'] = str(prior)


def audit_decisions(check, folder, trades, parameters, diagnostics, raw, tick, point, fee, slip_cash):
    decisions = pd.read_csv(folder / 'sizing-decisions.csv')
    check.result['sizing_decisions'] = len(decisions)
    check.require('all sizing decisions counted', len(decisions) == diagnostics['sizing_decisions'])
    if decisions.empty:
        check.require('no trade without sizing decisions', trades.empty)
        return
    p, q = parameters, decisions.quantity_selected.to_numpy(float)
    plan = np.abs(decisions.trigger - decisions.stop).to_numpy(float) * point + 2 * fee + 2 * slip_cash
    risk_mode = p['sizing_mode'] == 'fixed_risk'
    uncapped = np.floor(float(p['risk_budget']) / plan) if risk_mode else np.full(len(q), int(p['contracts']))
    expected = np.minimum(int(p['max_contracts']), uncapped) if risk_mode else uncapped
    cap = uncapped > int(p['max_contracts']) if risk_mode else np.zeros(len(q), dtype=bool)
    check.close('every decision all-in risk including skips', decisions.planned_stop_risk_per_contract, plan)
    check.close('every decision uncapped floor', decisions.quantity_uncapped, uncapped)
    check.close('every decision selected quantity including skips', q, expected)
    check.require('every decision cap flag', np.array_equal(decisions.quantity_capped.to_numpy(bool), cap))
    check.require('decision mode matches declaration', (decisions.sizing_mode == p['sizing_mode']).all())
    check.require('decision budget matches declaration', np.isclose(decisions.risk_budget, p['risk_budget']).all() if risk_mode else decisions.risk_budget.isna().all())
    zero = q == 0
    check.require('zero quantity always explicitly declined', ((decisions.rejection_reason == 'risk-budget-below-one-contract') == zero).all())
    check.require('zero quantity never creates an order', np.array_equal(decisions.order_id.isna().to_numpy(), zero))
    check.require('skip count independently reconciles', zero.sum() == diagnostics['sizing_rejections'])
    check.require('armed order count independently reconciles', (~zero).sum() == diagnostics['entry_orders_armed'])
    check.require('capped armed order count independently reconciles', (cap & ~zero).sum() == diagnostics['quantity_capped_orders'])
    check.require('at most one order armed per close', decisions.loc[~zero, 'observed_time'].is_unique)
    if p['entry_eligibility'] == 'first_touch':
        check.require('declined first touch never resized or retried', decisions.zone_id.is_unique)
    known = decisions.loc[~zero].set_index('order_id')
    check.require('all executed orders have an armed sizing decision', trades.order_id.isin(known.index).all())
    if not trades.empty and trades.order_id.isin(known.index).all():
        matched = known.loc[trades.order_id]
        check.close('execution retained armed count', trades.contracts_abs, matched.quantity_selected)
        check.close('execution retained armed per-contract risk', trades.planned_stop_risk_per_contract, matched.planned_stop_risk_per_contract)
        check.require('execution retained arm timestamp', np.array_equal(ns(trades.signal_time), ns(matched.observed_time)))
        check.require('execution retained armed zone identity', np.array_equal(trades.zone_id.to_numpy(), matched.zone_id.to_numpy()))
    chart = raw['chart']
    stamps, highs, lows = ns(chart.index), chart.high.to_numpy(float), chart.low.to_numpy(float)
    side, top, bottom = formations(chart, p['require_fvg'])
    bias, hourly = structures(raw, int(p['pivot_len']))
    epsilon = tick * 1e-7
    legal, triggers, stops = [], [], []
    for row in decisions.itertuples(index=False):
        segment, zone_side, creation = (int(value) for value in row.zone_id.split(':'))
        born, signal = creation - FIVE, pd.Timestamp(row.observed_time).value
        z, s = int(np.searchsorted(stamps, born)), int(np.searchsorted(stamps, signal - FIVE))
        if max(z, s) >= len(stamps):
            raise ValueError('Decision timestamp outside raw source')
        overlaps = np.flatnonzero((lows[z + 1:s + 1] <= top[z] + epsilon) & (highs[z + 1:s + 1] >= bottom[z] - epsilon))
        first = z + 1 + int(overlaps[0]) if len(overlaps) else -1
        valid = (stamps[z] == born and stamps[s] == signal - FIVE and side[z] == row.side == zone_side and
            chart.segment.iloc[z] == chart.segment.iloc[s] == segment and 0 < s - z <= int(p['max_age']) and
            chart.complete.iloc[s] and bias[z] == row.side and bias[s] == row.side and
            (not p['use_htf'] or hourly[z] == hourly[s] == row.side) and
            (first == s if p['entry_eligibility'] == 'first_touch' else first <= s) and
            ((lows[z + 1:s + 1] >= bottom[z] - epsilon).all() if row.side == 1 else (highs[z + 1:s + 1] <= top[z] + epsilon).all()))
        legal.append(valid)
        triggers.append(highs[s] + tick if row.side == 1 else lows[s] - tick)
        stops.append(bottom[z] - tick if row.side == 1 else top[z] + tick)
    check.require('independent raw eligible zone/first-touch geometry for every sizing decision', all(legal))
    check.close('independent raw trigger for every sizing decision', decisions.trigger, triggers)
    check.close('independent raw stop for every sizing decision', decisions.stop, stops)


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
    check.require('result protocol hash', result['protocol_checksum'] == sha(out / 'protocol.json'))
    check.require('result source hash', result['source_hash'] == read(out / 'source-manifest.json')['source_hash'])
    for item in result['artifacts']:
        path = (folder / item['name']).resolve()
        if not path.is_relative_to(folder.resolve()):
            raise ValueError('Artifact escapes case folder')
        check.require('artifact checksum: ' + item['name'], sha(path) == item['checksum'])
    trades, equity = pd.read_csv(folder / 'trades.csv'), pd.read_parquet(folder / 'equity.parquet')
    check.result.update(trades=len(trades), equity_rows=len(equity))
    check.require('strictly increasing marks', len(equity) > 0 and (np.diff(ns(equity.timestamp)) > 0).all())
    check.close('marked increments', equity.net_pnl, np.diff(np.r_[capital, equity.equity]), atol=1e-5)
    check.close('marked balance relation', equity.equity, equity.balance + equity.unrealized_pnl, atol=1e-5)
    check.close('final realized reconciliation', equity.equity.iloc[-1] - capital, trades.net_pnl.sum(), atol=1e-5)
    check.require('final position flat', equity.contracts.iloc[-1] == 0)
    check.close('final unrealized flat', equity.unrealized_pnl.iloc[-1], 0)
    prior_parity(check, folder, case)
    p, tick, point = case['parameters'], float(dataset['tick_size']), float(dataset['point_value'])
    audit_decisions(check, folder, trades, p, result['diagnostics'], raw, tick, point, case['fee'], tick * case['slippage_ticks'] * point)
    audit_marks(check, trades, equity, raw, capital, point, case['fee'], 0 if p['slippage_model'] == 'price' else tick * case['slippage_ticks'] * point)
    if trades.empty:
        check.result['note'] = 'Zero-trade case retained; no raw trade geometries available.'
        return check.finish()
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
    audit_sizing(check, trades, p, point, case['fee'], slip_points * point)
    check.require('context capacity never discards', result['diagnostics']['context_zones_discarded_capacity'] == 0)
    expected_top, expected_bottom, expected_touch = [], [], []
    expected_trigger, expected_stop, expected_entry, expected_boundary = [], [], [], []
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
    quantity = np.abs(trades.quantity.to_numpy(float))
    check.require('positive risk and valid direction', (risk > 0).all() and np.isin(direction_values, [-1, 1]).all())
    check.close('risk', trades.risk, risk)
    check.close('initial risk alias', trades.initial_risk, risk)
    check.close('cash risk', trades.initial_risk_cash, risk * point * quantity)
    check.close('cash risk alias', trades.risk_cash, risk * point * quantity)
    check.close('gross cash', trades.gross_pnl, direction_values * (trades.exit - trades.entry).to_numpy(float) * point * quantity)
    cash_slip = 0 if price_mode else slip_points * point
    check.close('fees and no double counted slippage', trades.cost, quantity * (2 * case['fee'] + cash_slip * (1 + (trades.exit_reason != 'target').astype(int))))
    check.close('net cash', trades.net_pnl, trades.gross_pnl - trades.cost)
    check.close('net R', trades.net_r, trades.net_pnl / (risk * point * quantity))
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
    check.require('at most one trade per zone', not trades.duplicated(['zone_time', 'side', 'zone_top', 'zone_bottom']).any())
    check.require('signals outside warmup', (ns(trades.signal_time) - FIVE >= pd.Timestamp(dataset['start'], tz='UTC').value).all())
    if p['entry_eligibility'] == 'first_touch':
        check.require('first touch outside warmup', (ns(trades.first_touch_time) >= pd.Timestamp(dataset['start'], tz='UTC').value).all())
    check.require('one position at a time', len(trades) < 2 or (ns(trades.entry_time)[1:] >= ns(trades.exit_time)[:-1]).all())
    return check.finish()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    out = args.output.resolve()
    protocol, records = read(out / 'protocol.json'), []
    integrity = Checks('protocol and source integrity')
    manifest = read(out / 'source-manifest.json')
    integrity.require('source snapshot bound to protocol', manifest['protocol_checksum'] == sha(out / 'protocol.json'))
    integrity.require('source hash independently reconstructed', manifest['source_hash'] == hashlib.sha256(json.dumps(manifest['files'], sort_keys=True).encode()).hexdigest())
    integrity.require('declared case identities unique', len({(c['symbol'], c['variant']) for c in protocol['cases']}) == len(protocol['cases']))
    for item in manifest['files']:
        integrity.require('frozen source checksum: ' + item['path'], sha(out / 'source' / item['path']) == item['checksum'])
    records.append(integrity.finish())
    for dataset in protocol['datasets']:
        raw = raw_market(dataset)
        for case in [c for c in protocol['cases'] if c['symbol'] == dataset['symbol']]:
            identity = case['symbol'] + '/' + case['variant']
            try:
                record = audit_case(out, case, dataset, protocol['capital'], raw)
            except Exception as error:
                record = dict(identity=identity, passed=False, checks=0, failures=[type(error).__name__ + ': ' + str(error)])
            records.append(record)
            print(identity + ': ' + ('passed' if record['passed'] else 'FAILED ' + str(record['failures'])), flush=True)
        del raw
    failures = [dict(identity=r['identity'], failures=r['failures']) for r in records if not r['passed']]
    if len(records) - 1 != protocol['expected_cases'] or len(records) - 1 != len(protocol['cases']):
        failures.append(dict(identity='protocol', failures=['Missing declared cases']))
    result = dict(audited_at=datetime.now(timezone.utc).isoformat(), status='passed' if not failures else 'failed',
        script_checksum=sha(__file__), protocol_checksum=sha(out / 'protocol.json'),
        source_manifest_checksum=sha(out / 'source-manifest.json'), declared_cases=len(protocol['cases']),
        total_checks=sum(r['checks'] for r in records), failures=failures, records=records,
        scope='Independent source grouping, strict/relaxed formation, chart/hour structure, wick bounds, first physical touch, selected overlap trigger, elapsed TTL, pending validity, gap/slippage fills, opposing room, target rounding, frozen arm-time contract sizing, planned/actual stop risk, gap budget overruns, quantity-scaled accounting, every equity mark, exact prior controls and source integrity.',
        limitations=['Checks recorded exits and raw fill prices, but does not replay every possible intervening bracket exit; dedicated execution tests cover chronology.',
            'Context reconstruction assumes no capacity discards; explicitly checked for every case.',
            'Observed source cannot establish unobserved intraminute event order, queue priority, fill probability, or prospective profitability.'])
    (out / 'independent-audit.json').write_text(json.dumps(result, indent=2, allow_nan=False), encoding='utf-8')
    print(json.dumps({key: result[key] for key in ('status', 'declared_cases', 'total_checks', 'failures')}, indent=2))
    return 0 if not failures else 1


if __name__ == '__main__':
    raise SystemExit(main())
