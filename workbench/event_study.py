"""Causal price-pattern event studies. Executed from an immutable source snapshot."""
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from workbench.dataset_reference import resolve_dataset_path


DEFAULTS = dict(atr_period=14, base_bars=3, base_atr=1., departure_bars=3,
                departure_atr=1.5, ob_lookback=5, breakout_bars=20, swing_bars=2,
                level_width_atr=.25, return_bars=50, reaction_bars=20,
                rejection_atr=1., failure_atr=.25, seed=1729, bootstrap_samples=1000,
                match_caliper=1., cluster_bars=100)
FAMILIES = ['support_resistance', 'supply_demand', 'order_block', 'fvg']
PATTERNS = [
    ('support', 'Support', 'support_resistance', 1),
    ('resistance', 'Resistance', 'support_resistance', -1),
    ('demand_zone', 'Demand zone', 'supply_demand', 1),
    ('supply_zone', 'Supply zone', 'supply_demand', -1),
    ('bullish_order_block', 'Bullish order block', 'order_block', 1),
    ('bearish_order_block', 'Bearish order block', 'order_block', -1),
    ('bullish_fvg', 'Bullish FVG', 'fvg', 1),
    ('bearish_fvg', 'Bearish FVG', 'fvg', -1),
]


def checksum(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False), encoding='utf-8')


def load_bars(protocol, end=None):
    # The shared session implementation is copied into the study snapshot.
    from strategy_engine.data import session_bars
    from strategy_engine.sessions import get_session
    dataset = protocol['dataset']
    dataset_path = resolve_dataset_path(dataset)
    if checksum(dataset_path) != dataset['checksum']:
        raise ValueError('Dataset checksum changed')
    start = pd.Timestamp(protocol['start'], tz='UTC')
    stop = pd.Timestamp(end).tz_convert('UTC') if end else pd.Timestamp(protocol['end'], tz='UTC') + pd.Timedelta(days=1)
    source = pd.read_parquet(dataset_path, filters=[('ts_event', '>=', start), ('ts_event', '<', stop)])
    if not isinstance(source.index, pd.DatetimeIndex):
        source.index = pd.to_datetime(source.pop('ts_event'), utc=True)
    if not source.index.is_unique or not source.index.is_monotonic_increasing:
        raise ValueError('Source timestamps must be unique and sorted')
    session = get_session(protocol['session'])
    fine = session_bars(source, session, '1m')
    bars = session_bars(source, session, protocol['timeframe'])
    # A partial right-hand bar is never available. Left partial bars are discarded too.
    last = min(stop, source.index[-1] + pd.Timedelta(minutes=1)) if len(source) else stop
    bars = bars.loc[(bars.index >= start) & (bars.availability_time <= last)]
    if bars.empty:
        raise ValueError('No completed candles in the selected interval')
    values = bars[['open', 'high', 'low', 'close']].to_numpy(float)
    if not np.isfinite(values).all() or (bars.high < bars[['open', 'close', 'low']].max(axis=1)).any() or (bars.low > bars[['open', 'close', 'high']].min(axis=1)).any():
        raise ValueError('Invalid OHLC data')
    return bars, fine


def preview(protocol):
    bars, _ = load_bars(protocol)
    n = len(bars)
    cuts = [0, int(n * .6), int(n * .8), n]
    minimum = max(100, protocol['rules']['return_bars'] + protocol['rules']['reaction_bars'] + 30)
    if min(np.diff(cuts)) < minimum:
        raise ValueError(f'Each split needs at least {minimum} completed candles; select more history')
    splits = {}
    for name, a, b in zip(['development', 'validation', 'final'], cuts[:-1], cuts[1:]):
        splits[name] = dict(start=bars.index[a].isoformat(), end=bars.availability_time.iloc[b-1].isoformat(), bars=b-a, offset=a)
    return dict(splits=splits, bars=n, source_checksum=protocol['dataset']['checksum'])


def features(bars, rules):
    prev = bars.close.shift(1)
    tr = pd.concat([bars.high-bars.low, (bars.high-prev).abs(), (bars.low-prev).abs()], axis=1).max(axis=1)
    # Explicit simple moving ATR of completed candles; frozen at confirmation.
    atr = tr.rolling(rules['atr_period'], min_periods=rules['atr_period']).mean().to_numpy()
    close = bars.close.to_numpy(float)
    scale = np.where(atr > 0, atr, np.nan)
    trend = (bars.close-bars.close.shift(20)).to_numpy()/scale
    move = (bars.close-bars.close.shift(3)).to_numpy()/scale
    return atr, close, trend, move


class PatternRecognizers:
    """Eight named recognizers evaluated at a completed candle's close.

    Methods return formation candidates only; detect() applies first-confirmation
    deduplication. Every read is restricted to indices at or before `i`.
    """
    def __init__(self, bars, rules):
        self.rules = rules
        self.o, self.h, self.l, self.c = (bars[k].to_numpy(float) for k in ['open', 'high', 'low', 'close'])
        self.feat = features(bars, rules)
        self.atr = self.feat[0]

    def _ready(self, i, lookback=0):
        return 0 <= i < len(self.c) and i >= lookback and np.isfinite(self.atr[i]) and self.atr[i] > 0

    @staticmethod
    def _candidate(anchor, low, high, **evidence):
        return dict(anchor=int(anchor), low=float(low), high=float(high),
                    recognition={key: float(value) for key, value in evidence.items()})

    def _swing(self, i, direction):
        r = self.rules
        s = r['swing_bars']
        if not self._ready(i, 2*s):
            return []
        j = i-s
        values = self.l if direction == 1 else -self.h
        neighbours = min(values[j-s:j].min(), values[j+1:i+1].min())
        if values[j] >= neighbours:
            return []
        level = self.l[j] if direction == 1 else self.h[j]
        width = r['level_width_atr']*self.atr[i]/2
        return [self._candidate(j, level-width, level+width, swing_price=level,
                                left_candles=s, right_candles=s, full_width_atr=r['level_width_atr'])]

    def support(self, i):
        return self._swing(i, 1)

    def resistance(self, i):
        return self._swing(i, -1)

    def _zone(self, i, direction):
        r = self.rules
        if not self._ready(i, r['base_bars']):
            return []
        result = []
        for lag in range(1, r['departure_bars']+1):
            b, a = i-lag, i-lag-r['base_bars']+1
            if a < 0 or not np.isfinite(self.atr[b]) or self.atr[b] <= 0:
                continue
            lo, hi = self.l[a:b+1].min(), self.h[a:b+1].max()
            width = (hi-lo)/self.atr[b]
            distance = direction*(self.c[i]-(hi if direction == 1 else lo))/self.atr[b]
            if hi > lo and width <= r['base_atr'] and distance >= r['departure_atr']:
                result.append(self._candidate(b, lo, hi, base_start=a, base_end=b,
                              base_width_atr=width, base_atr=self.atr[b], departure_atr=distance,
                              departure_candles=lag))
        return result

    def demand_zone(self, i):
        return self._zone(i, 1)

    def supply_zone(self, i):
        return self._zone(i, -1)

    def _order_block(self, i, direction):
        r = self.rules
        if not self._ready(i, max(r['breakout_bars'], r['ob_lookback'])):
            return []
        opposite = [j for j in range(i-r['ob_lookback'], i) if direction*(self.c[j]-self.o[j]) < 0]
        if not opposite:
            return []
        j = opposite[-1]
        level = self.h[i-r['breakout_bars']:i].max() if direction == 1 else self.l[i-r['breakout_bars']:i].min()
        distance = direction*(self.c[i]-self.c[j])/self.atr[i]
        if direction*(self.c[i]-level) <= 0 or distance < r['departure_atr']:
            return []
        return [self._candidate(j, self.l[j], self.h[j], candle_open=self.o[j], candle_close=self.c[j],
                                departure_atr=distance, breakout_level=level,
                                confirmation_close=self.c[i], candles_since_anchor=i-j)]

    def bullish_order_block(self, i):
        return self._order_block(i, 1)

    def bearish_order_block(self, i):
        return self._order_block(i, -1)

    def _fvg(self, i, direction):
        if not self._ready(i, 2):
            return []
        lo, hi = (self.h[i-2], self.l[i]) if direction == 1 else (self.h[i], self.l[i-2])
        if lo >= hi:
            return []
        return [self._candidate(i-2, lo, hi, first_candle=i-2, third_candle=i,
                                gap_width_atr=(hi-lo)/self.atr[i])]

    def bullish_fvg(self, i):
        return self._fvg(i, 1)

    def bearish_fvg(self, i):
        return self._fvg(i, -1)


def detect(bars, rules):
    recognizers = PatternRecognizers(bars, rules)
    events, used = [], set()
    methods = [(key, family, direction, getattr(recognizers, key)) for key, _, family, direction in PATTERNS]
    for i in range(len(bars)):
        for pattern, family, direction, recognize in methods:
            for candidate in recognize(i):
                key = (pattern, candidate['anchor'])
                if key in used:
                    continue
                used.add(key)
                events.append(dict(id=len(events), family=family, pattern=pattern, direction=direction,
                                   confirmation=i, atr=float(recognizers.atr[i]),
                                   timestamp=bars.availability_time.iloc[i].isoformat(), **candidate))
    return events, recognizers.feat


def match_controls(events, bars, feat, rules, first):
    """Match using formation features only. No future prices/outcomes enter selection."""
    atr, c, trend, move = feat
    h, l = bars.high.to_numpy(), bars.low.to_numpy()
    sessions = np.asarray(bars.index.hour // 4)
    excluded = {(e['family'], e['direction'], e['confirmation']) for e in events}
    controls = []
    for e in events:
        i, d, scale = e['confirmation'], e['direction'], e['atr']
        width = (e['high']-e['low'])/scale
        distance = d*(c[i]-(e['high'] if d == 1 else e['low']))/scale
        e['match_id'] = None
        if distance < 0:  # Price has already crossed through the nominated region.
            continue
        if e['family'] == 'order_block':
            # Same departure and breakout, different pre-move candle, nearest width/distance.
            pool = [j for j in range(max(0, i-rules['ob_lookback']), i) if j != e['anchor'] and h[j] > l[j]]
            options = [(abs((h[j]-l[j])/scale-width) + abs(d*(c[i]-(h[j] if d == 1 else l[j]))/scale-distance), j) for j in pool
                       if d*(c[i]-(h[j] if d == 1 else l[j])) >= 0 and (h[j] != e['high'] or l[j] != e['low'])]
            if not options:
                continue
            score, anchor = min(options)
            if score > rules['match_caliper']:
                continue
            j, lo, hi = i, l[anchor], h[anchor]
        else:
            # Prior timestamp pool, same split/session/direction; deterministic bounded search.
            pool = np.arange(max(first, i-2000), i)
            pool = pool[(sessions[pool] == sessions[i]) & np.isfinite(trend[pool]) & (atr[pool] > 0)]
            pool = np.array([j for j in pool if (e['family'], d, int(j)) not in excluded], dtype=int)
            if e['family'] == 'fvg':
                pool = pool[(d*move[pool] >= rules['departure_atr'])]
            if not len(pool):
                continue
            delta = np.column_stack([np.abs(np.log(atr[pool]/scale)), np.abs(trend[pool]-trend[i])/2,
                                     np.abs(move[pool]-move[i])/2])
            acceptable = (delta <= rules['match_caliper']).all(axis=1)
            pool, delta = pool[acceptable], delta[acceptable]
            if not len(pool):
                continue
            k = int(np.argmin(delta.sum(axis=1)))
            j, score = int(pool[k]), float(delta[k].sum())
            # Geometric placement matches normalized distance and width exactly.
            near = c[j]-d*distance*atr[j]
            lo, hi = (near-width*atr[j], near) if d == 1 else (near, near+width*atr[j])
        control = dict(e, id=f"c{e['id']}", confirmation=int(j), anchor=int(j), low=float(lo), high=float(hi),
                       atr=float(atr[j]), timestamp=bars.availability_time.iloc[j].isoformat(),
                       pattern_id=e['id'], match_score=float(score), match_id=e['id'], recognition={})
        e['match_id'] = control['id']
        e['match_score'] = float(score)
        controls.append(control)
    return controls


def measure(event, bars, fine, rules, end):
    """Use chronological minute bars; unresolved ordering within a minute stays ambiguous."""
    e = dict(event)
    i, d, scale = e['confirmation'], e['direction'], e['atr']
    near, far = (e['high'], e['low']) if d == 1 else (e['low'], e['high'])
    target, stop = near+d*rules['rejection_atr']*scale, far-d*rules['failure_atr']*scale
    last = min(end, i+rules['return_bars']+1)
    high, low = bars.high.to_numpy(), bars.low.to_numpy()
    touched = [j for j in range(i+1, last) if low[j] <= e['high'] and high[j] >= e['low']]
    e.update(return_complete=i+rules['return_bars'] < end, returned=bool(touched), touch=None,
             outcome='not_returned' if i+rules['return_bars'] < end else 'incomplete',
             near=False, midpoint=False, far=False, age=None, visits=0, reactions=[],
             mfe=None, mae=None, excursion_complete=False, sequence='1m')
    # Filling means reaching/passing each edge, even across a price gap. Touch requires traded overlap.
    for label, level in [('near', near), ('midpoint', (near+far)/2), ('far', far)]:
        e[label] = bool(np.any(low[i+1:last] <= level) if d == 1 else np.any(high[i+1:last] >= level))
    if not touched:
        return e
    touch = touched[0]
    e.update(touch=touch, age=touch-i)
    # A visit starts after at least one entire candle outside the zone.
    visits = [j for j in touched if j-1 not in touched]
    e['visits'] = len(visits)
    for visit in visits:
        finish = min(end, visit+rules['reaction_bars'])
        start_time, end_time = bars.index[visit], bars.availability_time.iloc[finish-1]
        a, b = fine.index.searchsorted(start_time), fine.index.searchsorted(end_time)
        path = fine.iloc[a:b]
        entered, outcome, mfe, mae = False, None, 0., 0.
        for row in path.itertuples():
            newly_entered = False
            if not entered:
                if not (row.low <= e['high'] and row.high >= e['low']):
                    continue
                entered = newly_entered = True
            favorable = (row.high-near)/scale if d == 1 else (near-row.low)/scale
            adverse = (near-row.low)/scale if d == 1 else (row.high-near)/scale
            # Touch-minute extrema could precede the touch; exclude them from excursions.
            if not newly_entered:
                mfe, mae = max(mfe, favorable), max(mae, adverse)
            if outcome:
                continue
            good = row.high >= target if d == 1 else row.low <= target
            bad = row.low <= stop if d == 1 else row.high >= stop
            open_good = d*(row.open-target) >= 0
            open_bad = d*(row.open-stop) <= 0
            if newly_entered:
                # A far-boundary breach in a touch minute is conservatively ambiguous,
                # because price may have opened beyond it before returning to the zone.
                if good or bad:
                    outcome = 'ambiguous'
            elif open_good:
                outcome = 'rejection'
            elif open_bad:
                outcome = 'failure'
            elif good and bad:
                outcome = 'ambiguous'
            elif good:
                outcome = 'rejection'
            elif bad:
                outcome = 'failure'
        complete = visit+rules['reaction_bars'] <= end
        outcome = outcome or ('unresolved' if complete and entered else 'incomplete')
        reaction = dict(visit=visit, age=visit-i, outcome=outcome, mfe=mfe if entered else None,
                        mae=mae if entered else None, complete=complete)
        e['reactions'].append(reaction)
        if visit == touch:
            e.update(outcome=outcome, mfe=reaction['mfe'], mae=reaction['mae'], excursion_complete=complete)
    return e


def rates(events):
    complete = [e for e in events if e['return_complete']]
    touched = [e for e in events if e['returned']]
    resolved = [e for e in touched if e['outcome'] in ['rejection', 'failure', 'unresolved']]
    def rate(key):
        return sum(e[key] for e in complete)/len(complete) if complete else None
    counts = {name: sum(e['outcome'] == name for e in events) for name in ['rejection', 'failure', 'unresolved', 'ambiguous', 'incomplete', 'not_returned']}
    quantiles = {}
    for name in ['mfe', 'mae']:
        sample = [e[name] for e in touched if e['excursion_complete'] and e[name] is not None]
        quantiles[name] = [float(v) for v in np.quantile(sample, [.1, .5, .9])] if sample else None
    return dict(detected=len(events), revisited=len(touched), return_denominator=len(complete),
                reaction_denominator=len(resolved), return_rate=rate('returned'),
                rejection_rate=counts['rejection']/len(resolved) if resolved else None,
                failure_rate=counts['failure']/len(resolved) if resolved else None,
                unresolved_rate=counts['unresolved']/len(resolved) if resolved else None,
                fill_rates={k: rate(k) for k in ['near', 'midpoint', 'far']}, counts=counts, distributions=quantiles)


def comparison(patterns, controls, rules, metric):
    def eligible(e):
        return e['outcome'] in ['rejection', 'failure', 'unresolved'] if metric == 'rejection' else e['return_complete']
    def value(e):
        return float(e['outcome'] == 'rejection') if metric == 'rejection' else float(e['returned'] if metric == 'return' else e[metric])
    if not patterns or not controls:
        return dict(difference=None, interval_95=None, clusters=0, pattern_n=0, control_n=0)
    # Common chronological blocks for BOTH samples preserve reuse and local clustering.
    all_events = patterns+controls
    max_index = max(e['confirmation'] for e in all_events)
    block_count = max_index//rules['cluster_bars']+1
    counts = np.zeros((block_count, 4))
    for arm, rows in enumerate([patterns, controls]):
        for e in rows:
            if eligible(e):
                block = e['confirmation']//rules['cluster_bars']
                counts[block, arm*2] += value(e)
                counts[block, arm*2+1] += 1
    counts = counts[counts.sum(axis=1) > 0]
    total = counts.sum(axis=0)
    diff = total[0]/total[1]-total[2]/total[3] if total[1] and total[3] else None
    interval = None
    if len(counts) >= 10 and min(total[1], total[3]) >= 20:
        rng = np.random.default_rng(rules['seed'])
        samples = []
        for _ in range(rules['bootstrap_samples']):
            v = counts[rng.integers(0, len(counts), len(counts))].sum(axis=0)
            if v[1] and v[3]:
                samples.append(v[0]/v[1]-v[2]/v[3])
        if len(samples) >= rules['bootstrap_samples']*.9:
            interval = [float(x) for x in np.quantile(samples, [.025, .975])]
    return dict(difference=float(diff) if diff is not None else None, interval_95=interval,
                clusters=len(counts), pattern_n=int(total[1]), control_n=int(total[3]))


def summarize(events, controls, rules):
    result = []
    for family in FAMILIES:
        rows = [e for e in events if e['family'] == family]
        matched = [e for e in rows if e['match_id'] is not None]
        peers = [e for e in controls if e['family'] == family]
        comparisons = {k: comparison(matched, peers, rules, k) for k in ['rejection', 'return', 'midpoint', 'far']}
        ci = comparisons['rejection']['interval_95']
        evidence = ('Inconclusive: insufficient independent time blocks or observations' if ci is None else
                    'Stronger reactions than matched controls' if ci[0] > 0 else
                    'Weaker reactions than matched controls' if ci[1] < 0 else
                    'No demonstrated rejection advantage; interval includes zero')
        groups = {}
        for label, subset in [('bullish', [e for e in rows if e['direction'] == 1]),
                              ('bearish', [e for e in rows if e['direction'] == -1]),
                              ('age_1_10', [e for e in rows if e['age'] is not None and e['age'] <= 10]),
                              ('age_11_plus', [e for e in rows if e['age'] is not None and e['age'] > 10])]:
            groups[label] = rates(subset)
        periods = {period: rates([e for e in rows if e['timestamp'][:7] == period]) for period in sorted({e['timestamp'][:7] for e in rows})}
        visits = []
        for number in range(3):
            reactions = [e['reactions'][number] for e in rows if len(e['reactions']) > number]
            visits.append(dict(visit=number+1, n=len(reactions), counts={k: sum(r['outcome'] == k for r in reactions) for k in ['rejection', 'failure', 'unresolved', 'ambiguous', 'incomplete']}))
        result.append(dict(family=family, pattern=rates(rows), control=rates(peers), matched=len(matched),
                           unmatched=len(rows)-len(matched), comparisons=comparisons, evidence=evidence,
                           groups=groups, periods=periods, visits=visits, overlaps=sum(e.get('overlap', False) for e in rows)))
    return result


def study(protocol, plan, phase, folder):
    split = plan['splits'][phase]
    bars, fine = load_bars(protocol, split['end'])
    rules = protocol['rules']
    first = int(bars.index.searchsorted(pd.Timestamp(split['start'])))
    end = len(bars)
    if end-first != split['bars']:
        raise ValueError('Split candle count changed from the saved preview')
    print(f'{phase}: {end-first} scored candles', flush=True)
    events, feat = detect(bars, rules)
    events = [e for e in events if e['confirmation'] >= first]
    controls = match_controls(events, bars, feat, rules, first)
    # Flag rectangles overlapping in price and in their active observation windows.
    active = []
    for e in events:
        active = [p for p in active if p['confirmation']+rules['return_bars'] >= e['confirmation']]
        e['overlap'] = False
        for p in active:
            if p['low'] <= e['high'] and p['high'] >= e['low']:
                p['overlap'] = e['overlap'] = True
        active.append(e)
    events = [measure(e, bars, fine, rules, end) for e in events]
    controls = [measure(e, bars, fine, rules, end) for e in controls]
    recognized = []
    for key, name, family, direction in PATTERNS:
        rows = [e for e in events if e['pattern'] == key]
        peers = [e for e in controls if e['pattern'] == key]
        matched = [e for e in rows if e['match_id'] is not None]
        recognized.append(dict(key=key, name=name, family=family, direction=direction,
                               pattern=rates(rows), control=rates(peers), matched=len(matched),
                               comparisons={metric: comparison(matched, peers, rules, metric)
                                            for metric in ['return', 'rejection', 'far']}))
    result = dict(phase=phase, split=split, summaries=summarize(events, controls, rules),
                  recognition_version=2, recognizers=recognized,
                  sample_policy='Up to two seeded random detections per recognizer, without outcome selection.',
                  warnings=[*protocol['dataset'].get('warnings', []),
                    'Matched observational comparisons do not establish institutional orders or trading profitability.',
                    'Reaction rates exclude ambiguous/incomplete outcomes; their counts remain visible. Return/fill rates require the full return window.',
                    'Excursions exclude the touch minute and use full reaction windows only; reported movements are lower-bound observations.',
                    'Pointwise 95% time-block bootstrap intervals are exploratory, not multiplicity-adjusted. Blocks may not capture longer dependence.',
                    'A reserved split is not a fresh holdout if this history was previously inspected elsewhere.',
                    'Visits after the first are descriptive and may overlap. Controls can be reused; matching does not remove all confounding.'],
                  samples=[])
    rng = np.random.default_rng(rules['seed'])
    for key, _, _, _ in PATTERNS:
        candidates = [e for e in events if e['pattern'] == key]
        for k in rng.choice(len(candidates), min(2, len(candidates)), replace=False):
            e = candidates[int(k)]
            a = max(0, e['anchor']-max(5, rules['breakout_bars']))
            b = min(end, e['confirmation']+rules['return_bars']+rules['reaction_bars']+1)
            candles = [dict(index=j, timestamp=bars.index[j].isoformat(), **{key: float(bars.iloc[j][key]) for key in ['open', 'high', 'low', 'close']}) for j in range(a, b)]
            result['samples'].append(dict(event=e, candles=candles))
    folder = Path(folder)
    write_json(folder/'result.json', result)
    write_json(folder/'events.json', dict(patterns=events, controls=controls))
    flat = [{k: v for k, v in e.items() if k not in ['reactions', 'recognition']} |
            {f'recognition_{k}': v for k, v in e.get('recognition', {}).items()} | {'arm': arm}
            for arm, rows in [('pattern', events), ('control', controls)] for e in rows]
    pd.DataFrame(flat, columns=None if flat else ['id', 'family', 'arm', 'outcome']).to_csv(folder/'events.csv', index=False)
    write_json(folder/'manifest.json', dict(protocol=protocol, plan=plan, phase=phase,
               python=sys.version, numpy=np.__version__, pandas=pd.__version__,
               artifacts={name: checksum(folder/name) for name in ['result.json', 'events.json', 'events.csv']}))
    print(f'Completed: {len(events)} detections; {len(controls)} matched controls', flush=True)


if __name__ == '__main__':
    payload = json.loads(Path(sys.argv[2]).read_text(encoding='utf-8'))
    if sys.argv[1] == 'preview':
        write_json(sys.argv[3], preview(payload))
    else:
        study(payload['protocol'], payload['plan'], payload['phase'], sys.argv[3])
