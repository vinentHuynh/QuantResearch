"""Descriptive return to NY open after the first stretch, before 09:45 ET."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = ROOT / 'reports/mnq-return-to-open-2026-10-28'
PROTOCOL_HASH = '0492fdc39ba3c6e57e2541f5b25a759e7925022c180d2e94d5500ba9e1cac059'
LOADER_HASH = '22d59c6564ba586b2abeb79a5fb3133a1cc0809bbdfd1566bb300ddad5bb3411'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def load_prior():
    path = HERE.parent / 'mnq-opening-retracement-2026-10-28/analysis.py'
    assert sha(path) == LOADER_HASH
    spec = importlib.util.spec_from_file_location('audited_opening_loader', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def analyze(bars, distance, prior):
    bars = np.asarray(bars, dtype=float)[:15]
    assert bars.shape == (15, 4)
    origin = float(bars[0, 0])
    index, directions, at_open = prior.first_touch(bars, distance)
    row = {'threshold_points': distance, 'cash_open': origin,
           'triggered': index is not None, 'trigger_minute_index': index,
           'trigger_minute_et': f'09:{30+index:02d}' if index is not None else '',
           'first_direction': 'none', 'direction_ambiguous': len(directions) > 1,
           'trigger_at_minute_first_print': at_open,
           'return_certain': 0, 'return_possible': 0, 'branches': []}
    if index is None:
        return row
    branches = []
    for direction in directions:
        signed = [prior.signed_bar(b, origin, direction) for b in bars[index:]]
        _, _, low, close = signed[0]
        later_return = any(b[2] <= 0 for b in signed[1:])
        # With either band first, the opposite band in this same minute must
        # follow it and therefore crosses the open. Other extrema may precede it.
        forced_in_trigger = (at_open and low <= 0) or close <= 0 or len(directions) > 1
        certain = bool(later_return or forced_in_trigger)
        possible = bool(later_return or low <= 0)
        assert certain <= possible
        branches.append({'direction': 'up' if direction == 1 else 'down',
                         'return_certain': certain, 'return_possible': possible,
                         'later_minute_return': bool(later_return),
                         'trigger_minute_return_forced': bool(forced_in_trigger)})
    row.update(first_direction='ambiguous' if len(directions) > 1 else branches[0]['direction'],
               return_certain=int(all(b['return_certain'] for b in branches)),
               return_possible=int(any(b['return_possible'] for b in branches)), branches=branches)
    return row


def checks(prior):
    def scenario(first, rest):
        return np.array([first] + [rest] * 14, dtype=float)
    cases = [
        (scenario([1000, 1045, 1000, 1042], [1042, 1046, 1038, 1043]), (0, 1)),
        (scenario([1000, 1045, 995, 999], [1002, 1003, 1001, 1002]), (1, 1)),
        (scenario([1000, 1045, 1000, 1042], [1042, 1046, 999, 1043]), (1, 1)),
        (scenario([1000, 1045, 955, 1020], [1020, 1022, 1018, 1020]), (1, 1)),
    ]
    late = scenario([1000, 1005, 995, 1003], [1003, 1008, 1001, 1004])
    late[14] = [1004, 1045, 1002, 1042]
    cases.append((late, (0, 0)))
    known_open = late.copy()
    known_open[14] = [1045, 1048, 999, 1042]
    cases.append((known_open, (1, 1)))
    for bars, expected in cases:
        result = analyze(bars, 40, prior)
        assert (result['return_certain'], result['return_possible']) == expected
        reflected = 2000 - bars[:, [0, 2, 1, 3]]
        result_down = analyze(reflected, 40, prior)
        assert (result_down['return_certain'], result_down['return_possible']) == expected
        after_deadline = np.vstack([bars, [1040, 1100, 900, 1000]])
        assert analyze(after_deadline, 40, prior) == result
    return {'synthetic_scenarios': len(cases), 'direction_symmetry': True, '09_45_excluded': True}


def main():
    protocol_path = HERE / 'protocol_v2.json'
    assert sha(protocol_path) == PROTOCOL_HASH
    protocol = json.loads(protocol_path.read_text())
    prior = load_prior()
    verification = checks(prior)
    loader_protocol = {**protocol, 'calendar_path': protocol['cash_calendar_path'],
                       'calendar_sha256': protocol['cash_calendar_sha256']}
    sessions, exclusions, preview = prior.load_sessions(loader_protocol)
    preview['loader_protocol_sha256'] = preview.pop('protocol_sha256')
    preview['active_protocol_sha256'] = PROTOCOL_HASH
    rows = []
    for date, bars in sessions.items():
        for distance in protocol['threshold_points']:
            row = analyze(bars, distance, prior)
            # Independently implemented prior generic retracement routine agrees
            # when the retracement size equals the original stretch distance.
            if row['triggered']:
                index, sides, at_open = prior.first_touch(bars, distance)
                reference = [prior.branch_bounds(bars, distance, distance, index, s, at_open,
                                                 len(sides) > 1) for s in sides]
                assert row['return_certain'] == all(b['any_certain'] for b in reference)
                assert row['return_possible'] == any(b['any_possible'] for b in reference)
            row['branches'] = json.dumps(row['branches'], separators=(',', ':'))
            rows.append({'date': date, **row})
    events = pd.DataFrame(rows)
    assert not events.duplicated(['date', 'threshold_points']).any()
    summaries = []
    for period, (start, end) in protocol['periods'].items():
        period_events = events[events.date.between(start, end)]
        total = period_events.date.nunique()
        for distance in protocol['threshold_points']:
            triggered = period_events[(period_events.threshold_points == distance) & period_events.triggered]
            for direction in ('all', 'up', 'down', 'ambiguous'):
                part = triggered if direction == 'all' else triggered[triggered.first_direction == direction]
                n = len(part)
                certain, possible = int(part.return_certain.sum()), int(part.return_possible.sum())
                summaries.append({'period': period, 'direction': direction, 'threshold_points': distance,
                                  'cash_sessions': total, 'triggered_sessions': n,
                                  'no_trigger_sessions': total-len(triggered),
                                  'return_certain_count': certain, 'return_possible_count': possible,
                                  'return_certain_pct': 100*certain/n if n else None,
                                  'return_possible_pct': 100*possible/n if n else None,
                                  'unresolved_order_count': possible-certain,
                                  'definitely_no_return_count': n-possible,
                                  'sparse': n < 100})
    OUT.mkdir(exist_ok=True, parents=True)
    events.to_csv(OUT / 'events.csv', index=False)
    pd.DataFrame(summaries).to_csv(OUT / 'percentages.csv', index=False)
    pd.DataFrame(exclusions).to_csv(OUT / 'excluded_sessions.csv', index=False)
    write_json(OUT / 'definition.json', protocol)
    preview['historical_outcomes_scored'] = True
    write_json(OUT / 'summary.json', {'study_id': protocol['study_id'], 'data': preview,
                                    'summary_rows': summaries, 'checks': verification,
                                    'source_sha256': sha(__file__)})
    manifest = {f.name: sha(f) for f in OUT.iterdir() if f.is_file() and f.name != 'artifact_manifest.json'}
    write_json(OUT / 'artifact_manifest.json', manifest)
    print(json.dumps({'coverage': preview, 'summary': [s for s in summaries if s['direction'] == 'all'],
                      'checks': verification}, indent=2))


if __name__ == '__main__':
    main()
