"""Independent raw-source geometry and ledger audit; no strategy imports.

Reads immutable source candles and every declared result. Writes only the
independent-audit.json report, retaining both failed checks and zero-trade cases.
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
DEFAULT_OUT = ROOT / 'reports/snd-body-retest-2026-09-24'
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


def raw_market(dataset):
    """Independent pandas grouping and explicit full-trading-day calendar."""
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
    frame['_pos'] = np.arange(len(frame))
    frame['_stamp'] = frame.index
    chart = frame.groupby(frame.index.floor('5min'), sort=True).agg(
        open=('open', 'first'), high=('high', 'max'), low=('low', 'min'), close=('close', 'last'),
        count=('open', 'size'), first=('_stamp', 'first'), last=('_stamp', 'last'),
        begin=('_pos', 'first'), final=('_pos', 'last'),
        first_segment=('_segment', 'first'), segment=('_segment', 'last'))
    chart['complete'] = ((chart['count'] == 5) & (chart['first'] == chart.index) &
        (chart['last'] + pd.Timedelta(minutes=1) == chart.index + pd.Timedelta(minutes=5)) &
        (chart.first_segment == chart.segment))
    return frame, chart, identities


def formations(chart, boundary):
    """All context formations, without a direction filter or trade lifecycle."""
    opened, closed, high, low = (chart[key].to_numpy(float) for key in ('open', 'close', 'high', 'low'))
    complete, segment, stamps = chart.complete.to_numpy(bool), chart.segment.to_numpy(), ns(chart.index)
    side = np.zeros(len(chart), dtype=int)
    consecutive = complete[2:] & complete[1:-1] & complete[:-2] & (stamps[2:] - stamps[:-2] == 2 * FIVE) & (segment[2:] == segment[:-2])
    demand = consecutive & (closed[:-2] < opened[:-2]) & (closed[1:-1] > opened[1:-1]) & (low[2:] > high[:-2])
    supply = consecutive & (closed[:-2] > opened[:-2]) & (closed[1:-1] < opened[1:-1]) & (high[2:] < low[:-2])
    side[2:] = demand.astype(int) - supply.astype(int)
    hi = np.maximum(opened, closed) if boundary == 'body' else high
    lo = np.minimum(opened, closed) if boundary == 'body' else low
    top, bottom = np.full(len(chart), np.nan), np.full(len(chart), np.nan)
    top[2:] = np.where(side[2:] == 1, hi[:-2], np.maximum.reduce([hi[:-2], hi[1:-1], hi[2:]]))
    bottom[2:] = np.where(side[2:] == 1, np.minimum.reduce([lo[:-2], lo[1:-1], lo[2:]]), lo[:-2])
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
    check.require('result protocol hash', result['protocol_checksum'] == sha(out / 'protocol.json'))
    manifest = read(out / 'source-manifest.json')
    check.require('result source hash', result['source_hash'] == manifest['source_hash'])
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
    if trades.empty:
        check.result['note'] = 'Zero-trade case retained; no raw trade geometries available.'
        return check.finish()
    p, tick, point = case['parameters'], float(dataset['tick_size']), float(dataset['point_value'])
    check.require('audited fixed formation rules', p['require_fvg'] and p['first_touch_only'] and p['stop_model'] == 'zone' and p['rr'] == 1 and p['min_opposing_room_r'] == 2)
    frame, chart, identities = raw
    check.result['raw_sources'] = identities
    side, top, bottom = formations(chart, p['zone_boundary'])
    ts = ns(chart.index)
    highs, lows = chart.high.to_numpy(float), chart.low.to_numpy(float)
    segments = chart.segment.to_numpy()
    source_times = ns(frame.index)
    epsilon = tick * 1e-7
    check.require('context capacity never discards', result['diagnostics']['context_zones_discarded_capacity'] == 0)
    # The direct historical scan below is valid only when no capacity eviction
    # occurred; any such occurrence explicitly fails the audit above.
    expected_top, expected_bottom, expected_touch = [], [], []
    expected_trigger, expected_stop, expected_entry, expected_boundary = [], [], [], []
    formation_ok, touch_ok, valid_ok, timeline_ok = [], [], [], []
    for trade in trades.itertuples(index=False):
        born = pd.Timestamp(trade.zone_time).value - FIVE
        signal = pd.Timestamp(trade.signal_time).value
        touch = pd.Timestamp(trade.first_touch_time).value
        entered = pd.Timestamp(trade.entry_time).value
        z, s = int(np.searchsorted(ts, born)), int(np.searchsorted(ts, signal - FIVE))
        t = int(np.searchsorted(ts, touch // FIVE * FIVE))
        j = int(np.searchsorted(source_times, entered))
        if z >= len(ts) or s >= len(ts) or t >= len(ts) or j >= len(frame):
            raise ValueError('Trade timestamp outside source')
        formation_ok.append(ts[z] == born and side[z] == trade.side)
        expected_top.append(top[z]); expected_bottom.append(bottom[z])
        overlaps = np.flatnonzero((lows[z + 1:s + 1] <= top[z] + epsilon) & (highs[z + 1:s + 1] >= bottom[z] - epsilon))
        first = z + 1 + int(overlaps[0]) if len(overlaps) else -1
        touch_ok.append(first == t and t == s and chart.complete.iloc[t])
        sub = frame.iloc[int(chart.begin.iloc[t]):int(chart.final.iloc[t]) + 1]
        source_hits = np.flatnonzero((sub.low.to_numpy(float) <= top[z] + epsilon) & (sub.high.to_numpy(float) >= bottom[z] - epsilon))
        expected_touch.append(ns(sub.index)[source_hits[0]] if len(source_hits) else -1)
        valid_ok.append(s > z and s - z <= int(p['max_age']) and segments[z] == segments[s] and
            ((lows[z + 1:s + 1] >= bottom[z] - epsilon).all() if trade.side == 1 else (highs[z + 1:s + 1] <= top[z] + epsilon).all()))
        trigger = highs[t] + tick if trade.side == 1 else lows[t] - tick
        expected_trigger.append(trigger)
        expected_stop.append(bottom[z] - tick if trade.side == 1 else top[z] + tick)
        observed = frame.iloc[j]
        timeline_ok.append(source_times[j] == entered and signal <= entered < signal + FIVE and
            ((observed.high >= trigger - epsilon) if trade.side == 1 else (observed.low <= trigger + epsilon)))
        expected_entry.append(max(observed.open, trigger) if trade.side == 1 else min(observed.open, trigger))
        # Reconstruct independent context from all eligible formations in the
        # preceding observed-bar age window, including this signal-close event.
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
    check.require('raw three-candle formation and wick FVG', all(formation_ok))
    check.close('raw selected zone top', trades.zone_top, expected_top)
    check.close('raw selected zone bottom', trades.zone_bottom, expected_bottom)
    check.require('raw first overlap is signal candle', all(touch_ok))
    check.require('raw first touch minute', np.array_equal(ns(trades.first_touch_time), np.asarray(expected_touch, dtype=np.int64)))
    check.require('no prior distal wick break, roll or expiry', all(valid_ok))
    check.close('raw touch-candle trigger', trades.entry_reference, expected_trigger)
    check.close('raw one-tick zone stop', trades.stop, expected_stop)
    check.require('raw entry trigger in next bucket', all(timeline_ok))
    check.close('raw gap-aware entry fill', trades.entry, expected_entry)
    check.close('raw nearest live opposing proximal', trades.opposing_boundary, expected_boundary)
    direction = trades.side.to_numpy(float)
    risk = direction * (trades.entry - trades.stop).to_numpy(float)
    check.require('positive risk and one contract', (risk > 0).all() and (trades.quantity.to_numpy() == direction).all() and np.isin(direction, [-1, 1]).all())
    check.close('risk', trades.risk, risk)
    check.close('initial risk alias', trades.initial_risk, risk)
    check.close('cash risk', trades.initial_risk_cash, risk * point)
    check.close('gross cash', trades.gross_pnl, direction * (trades.exit - trades.entry).to_numpy(float) * point)
    slip = tick * point * case['slippage_ticks']
    check.close('fees and slippage', trades.cost, 2 * case['fee'] + slip * (1 + (trades.exit_reason != 'target').astype(int)))
    check.close('net cash', trades.net_pnl, trades.gross_pnl - trades.cost)
    check.close('net R', trades.net_r, trades.net_pnl / (risk * point))
    payout = direction * (trades.target - trades.entry).to_numpy(float)
    check.require('1R target rounded toward entry under one tick', ((payout > 0) & (risk - payout >= -epsilon) & (risk - payout < tick + epsilon)).all())
    check.close('target tick grid', trades.target, np.rint(trades.target / tick) * tick, atol=tick * 1e-6)
    boundary = np.asarray(expected_boundary)
    room = np.where(np.isnan(boundary), np.inf, np.maximum(0, direction * (boundary - trades.entry)) / risk)
    check.close('actual entry opposing room', trades.opposing_room_r, room)
    check.require('2R room at fill', (room + 1e-9 >= 2).all())
    trigger_risk = direction * (trades.entry_reference - trades.stop).to_numpy(float)
    signal_room = np.where(np.isnan(boundary), np.inf, np.maximum(0, direction * (boundary - trades.entry_reference)) / trigger_risk)
    check.require('2R room at signal', (signal_room + 1e-9 >= 2).all())
    check.require('exits no earlier than entries', (ns(trades.exit_time) >= ns(trades.entry_time)).all())
    check.require('one fresh entry per zone', not trades.duplicated(['zone_time', 'side', 'zone_top', 'zone_bottom']).any())
    check.require('first touch outside warmup', (ns(trades.first_touch_time) >= pd.Timestamp(dataset['start'], tz='UTC').value).all())
    return check.finish()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    out = args.output.resolve()
    protocol = read(out / 'protocol.json')
    records = []
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
    if len(records) != 16 or protocol['expected_cases'] != 16:
        failures.append(dict(identity='protocol', failures=['Expected all 16 declared cases']))
    result = dict(audited_at=datetime.now(timezone.utc).isoformat(), status='passed' if not failures else 'failed',
        script_checksum=sha(__file__), protocol_checksum=sha(out / 'protocol.json'),
        source_manifest_checksum=sha(out / 'source-manifest.json'), declared_cases=len(protocol['cases']),
        total_checks=sum(r['checks'] for r in records), failures=failures, records=records,
        scope='Independent raw-source grouping, formation geometry and wick FVG, first physical touch, pre-signal wick validity, trigger/stop/fill, live opposing context and 2R room; ledger accounting, cost and timing.',
        limitations=['Does not independently reconstruct swing/hourly direction or every exit path; exact wick-control parity is verified by the separate reporter.',
            'Context reconstruction assumes no capacity discards; this is checked for every case.',
            'Observed source data cannot establish unobserved intraminute event order or prospective profitability.'])
    (out / 'independent-audit.json').write_text(json.dumps(result, indent=2, allow_nan=False), encoding='utf-8')
    print(json.dumps({key: result[key] for key in ('status', 'declared_cases', 'total_checks', 'failures')}, indent=2))
    return 0 if not failures else 1


if __name__ == '__main__':
    raise SystemExit(main())
