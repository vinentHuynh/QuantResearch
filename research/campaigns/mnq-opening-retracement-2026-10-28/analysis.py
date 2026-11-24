"""First opening-stretch retracement bounds; no assumed intraminute path."""
from __future__ import annotations

import argparse
import hashlib
import json
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = ROOT/'reports/mnq-opening-retracement-2026-10-28'
EXPECTED_PROTOCOL = 'd0516ab4e8d17c67e0f6cc9e2442d7d405129ed99b5bd2ae706c84b8d320970d'
METRICS = ('any_retracement', 'retracement_first', 'continuation_first', 'neither')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False)+'\n', encoding='utf-8')


def first_touch(bars, distance):
    origin = float(bars[0, 0])
    for i, (o, h, l, c) in enumerate(bars[:15]):
        if o >= origin+distance:
            return i, (1,), True
        if o <= origin-distance:
            return i, (-1,), True
        sides = tuple(s for s, hit in ((1, h >= origin+distance), (-1, l <= origin-distance)) if hit)
        if sides:
            return i, sides, False
    return None, (), False


def signed_bar(bar, origin, direction):
    o, h, l, c = map(float, bar)
    return ((o-origin)*direction, (h-origin if direction == 1 else origin-l),
            (l-origin if direction == 1 else origin-h), (c-origin)*direction)


def later_bar_outcomes(bar, target, stop):
    o, h, l, _ = bar
    if o <= target:
        return {'retracement'}
    if o >= stop:
        return {'continuation'}
    outcomes = set()
    if l <= target:
        outcomes.add('retracement')
    if h >= stop:
        outcomes.add('continuation')
    return outcomes or {'live'}


def branch_bounds(bars, distance, retracement, index, direction, at_open, both_first):
    origin = float(bars[0, 0])
    transformed = [signed_bar(b, origin, direction) for b in bars[index:15]]
    target, stop = distance-retracement, distance+distance/2
    o, h, l, c = transformed[0]
    # Both-first means the opposite band must occur after this branch's first
    # crossing. It therefore witnesses a retracement up to twice the distance.
    forced_target = c <= target or (both_first and retracement <= 2*distance)
    entry_target_possible = l <= target
    any_certain = (entry_target_possible if at_open else forced_target)
    any_certain = bool(any_certain or any(b[2] <= target for b in transformed[1:]))
    any_possible = bool(entry_target_possible or any(b[2] <= target for b in transformed[1:]))
    if at_open:
        states = later_bar_outcomes(transformed[0], target, stop)
    else:
        states = set()
        if entry_target_possible:
            states.add('retracement')
        if h >= stop:
            states.add('continuation')
        elif not forced_target:
            states.add('live')
        assert states
    for bar in transformed[1:]:
        if 'live' in states:
            states = (states-{'live'}) | later_bar_outcomes(bar, target, stop)
    states = (states-{'live'}) | ({'neither'} if 'live' in states else set())
    return {'direction': 'up' if direction == 1 else 'down',
            'any_certain': any_certain, 'any_possible': any_possible,
            'outcomes': sorted(states), 'entry_minute_target_possible': bool(entry_target_possible),
            'entry_minute_target_forced': bool(entry_target_possible if at_open else forced_target),
            'opening_beyond_continuation_barrier': bool(at_open and o >= stop)}


def analyze_day(bars, distance, retracement):
    bars = np.asarray(bars, dtype=float)
    if bars.ndim != 2 or bars.shape[1] != 4 or len(bars) < 15:
        raise ValueError('Need at least fifteen OHLC rows')
    if distance not in (40, 60, 80) or retracement not in (5, 10, 15):
        raise ValueError('Outside frozen levels')
    used = bars[:15]
    if not np.isfinite(used).all() or not (used > 0).all():
        raise ValueError('OHLC must be finite and positive')
    if not ((used[:, 1] >= used[:, [0, 2, 3]].max(axis=1)).all()
            and (used[:, 2] <= used[:, [0, 1, 3]].min(axis=1)).all()):
        raise ValueError('Invalid OHLC')
    i, sides, at_open = first_touch(used, distance)
    row = {'threshold_points': distance, 'retracement_points': retracement,
           'continuation_points': distance/2, 'triggered': i is not None,
           'touch_minute_index': i, 'first_direction': 'none', 'direction_ambiguous': len(sides) > 1,
           'trigger_at_minute_open': at_open, 'cash_open': float(used[0, 0]),
           'branches': [], 'outcomes': []}
    for metric in METRICS:
        row[metric+'_certain'] = row[metric+'_possible'] = 0
    if i is None:
        return row
    branches = [branch_bounds(used, distance, retracement, i, side, at_open, len(sides) > 1) for side in sides]
    outcomes = set().union(*(set(b['outcomes']) for b in branches))
    row.update(first_direction='ambiguous' if len(sides) > 1 else branches[0]['direction'],
               branches=branches, outcomes=sorted(outcomes),
               any_retracement_certain=int(all(b['any_certain'] for b in branches)),
               any_retracement_possible=int(any(b['any_possible'] for b in branches)))
    for metric, outcome in [('retracement_first', 'retracement'), ('continuation_first', 'continuation'), ('neither', 'neither')]:
        row[metric+'_certain'] = int(outcomes == {outcome})
        row[metric+'_possible'] = int(outcome in outcomes)
    assert row['retracement_first_certain'] <= row['any_retracement_certain']
    assert row['retracement_first_possible'] <= row['any_retracement_possible']
    return row


def load_sessions(protocol):
    source = Path(protocol['data_path'])
    assert sha(source) == protocol['data_sha256'], 'Source checksum mismatch'
    assert sha(protocol['calendar_path']) == protocol['calendar_sha256'], 'Calendar checksum mismatch'
    raw = pd.read_parquet(source, columns=['open', 'high', 'low', 'close', 'instrument_id', 'symbol'])
    assert raw.index.is_monotonic_increasing and not raw.index.has_duplicates
    assert set(raw.symbol.unique()) == {'MNQ.v.0'}
    morning = raw.tz_convert('America/New_York').between_time('09:30', '09:44').copy()
    morning['date'] = morning.index.strftime('%Y-%m-%d')
    groups = dict(tuple(morning.groupby('date')))
    dates = pd.read_csv(protocol['calendar_path']).cash_session.tolist()
    sessions, excluded = {}, []
    for date in dates:
        expected = pd.date_range(date+' 09:30', periods=15, freq='min', tz='America/New_York')
        frame = groups.get(date, morning.iloc[:0])
        missing = expected.difference(frame.index)
        reason = 'missing minutes' if len(missing) else 'contract change' if frame.instrument_id.nunique() != 1 else None
        if reason:
            excluded.append({'date': date, 'reason': reason, 'missing_minutes': len(missing),
                             'missing_times': ';'.join(missing.strftime('%H:%M'))})
            continue
        assert frame.index.equals(expected.rename(frame.index.name))
        values = frame[['open', 'high', 'low', 'close']].to_numpy(dtype=float)
        assert np.isfinite(values).all() and (values > 0).all()
        assert np.allclose(values*4, np.round(values*4), atol=1e-8, rtol=0)
        assert (values[:,1] >= values[:,[0,2,3]].max(axis=1)).all()
        assert (values[:,2] <= values[:,[0,1,3]].min(axis=1)).all()
        sessions[date] = values
    preview = {'source_sha256': sha(source), 'protocol_sha256': sha(HERE/'protocol.json'),
               'raw_rows': len(raw), 'cash_calendar_dates': len(dates), 'included_sessions': len(sessions),
               'first_session': min(sessions), 'last_session': max(sessions), 'excluded_sessions': excluded,
               'available_minutes_per_included_session': 15, 'historical_outcomes_scored': False}
    return sessions, excluded, preview


def summarize(events, sessions, protocol):
    rows = []
    for name, (start, end) in protocol['periods'].items():
        part = events[events.date.between(start, end)]
        total = sum(start <= d <= end for d in sessions)
        for (distance, target), sample in part.groupby(['threshold_points', 'retracement_points'], sort=True):
            triggered = sample[sample.triggered]
            n = len(triggered)
            row = {'period': name, 'threshold_points': int(distance), 'retracement_points': int(target),
                   'continuation_points': float(distance/2), 'cash_sessions': total, 'triggered_sessions': n,
                   'no_trigger_sessions': total-n, 'trigger_rate_pct': 100*n/total,
                   'ambiguous_first_direction_sessions': int(triggered.direction_ambiguous.sum()), 'sparse': n < 100}
            for metric in METRICS:
                for bound in ('certain', 'possible'):
                    key = metric+'_'+bound
                    row[key+'_count'] = int(triggered[key].sum())
                    row[key+'_pct'] = 100*row[key+'_count']/n if n else None
            rows.append(row)
    return rows


def make_breakdowns(events, keys):
    rows = []
    levels = [('up', 'down', 'ambiguous') if k == 'first_direction' else sorted(events[k].unique()) for k in keys]
    for group in product(*levels):
        mask = events.triggered.copy()
        for key, value in zip(keys, group):
            mask &= events[key] == value
        frame = events[mask]
        row = {k: (int(v) if isinstance(v, np.integer) else v) for k, v in zip(keys, group)}
        row['triggered_sessions'] = len(frame)
        row['sparse'] = len(frame) < 100
        for metric in METRICS:
            for bound in ('certain', 'possible'):
                key = metric+'_'+bound
                row[key+'_count'] = int(frame[key].sum())
                row[key+'_pct'] = 100*row[key+'_count']/len(frame) if len(frame) else None
        rows.append(row)
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--protocol-sha256', required=True)
    parser.add_argument('--preview', action='store_true')
    args = parser.parse_args()
    assert args.protocol_sha256 == sha(HERE/'protocol.json') == EXPECTED_PROTOCOL
    protocol = json.loads((HERE/'protocol.json').read_text(encoding='utf-8'))
    sessions, excluded, preview = load_sessions(protocol)
    OUT.mkdir(parents=True, exist_ok=True)
    write_json(OUT/'preview.json', preview)
    if args.preview:
        print(json.dumps(preview))
        return
    rows = []
    for date, bars in sessions.items():
        for distance in protocol['thresholds_points']:
            for target in protocol['retracements_points']:
                result = analyze_day(bars, distance, target)
                result.update(date=date, year=int(date[:4]))
                result['branches'] = json.dumps(result['branches'], separators=(',', ':'))
                result['outcomes'] = '|'.join(result['outcomes'])
                rows.append(result)
    events = pd.DataFrame(rows)
    assert not events.duplicated(['date', 'threshold_points', 'retracement_points']).any()
    events.to_csv(OUT/'events.csv', index=False)
    pd.DataFrame(excluded).to_csv(OUT/'excluded_sessions.csv', index=False)
    summaries = summarize(events, sessions, protocol)
    pd.DataFrame(summaries).to_csv(OUT/'percentages.csv', index=False)
    yearly = make_breakdowns(events, ['year', 'threshold_points', 'retracement_points'])
    direction = make_breakdowns(events, ['first_direction', 'threshold_points', 'retracement_points'])
    pd.DataFrame(yearly).to_csv(OUT/'yearly_percentages.csv', index=False)
    pd.DataFrame(direction).to_csv(OUT/'direction_percentages.csv', index=False)
    write_json(OUT/'summary.json', {'study_id': protocol['study_id'], 'data': {**preview, 'historical_outcomes_scored': True},
               'status': 'descriptive historical bounds; no trade backtest', 'summary_rows': summaries,
               'yearly_rows': yearly, 'direction_rows': direction,
               'source_sha256': sha(HERE/'analysis.py'), 'protocol_sha256': sha(HERE/'protocol.json'),
               'source_documentation': 'https://databento.com/docs/schemas/ohlcv'})
    write_json(OUT/'protocol.json', protocol)
    print(json.dumps({'event_rows': len(events), 'summary_rows': len(summaries),
                      'all_history': [r for r in summaries if r['period'] == 'all_history']}))


if __name__ == '__main__':
    main()
