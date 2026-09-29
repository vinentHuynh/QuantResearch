"""Independent formation-first audit of every saved development detection."""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from workbench.event_study import PATTERNS, checksum, load_bars


def audit(study_id):
    folder = Path('data/workbench/event-studies') / study_id
    record = json.loads((folder/'study.json').read_text())
    protocol, plan = record['protocol'], record['plan']
    attempt = next(a for a in record['attempts'] if a['phase'] == 'development' and a['status'] == 'Succeeded')
    output = folder/attempt['id']
    manifest = json.loads((output/'manifest.json').read_text())
    for name, digest in manifest['artifacts'].items():
        assert checksum(output/name) == digest, f'Changed artifact {name}'
    events = json.loads((output/'events.json').read_text())['patterns']
    bars, _ = load_bars(protocol, plan['splits']['development']['end'])
    r = protocol['rules']
    previous = bars.close.shift()
    atr = pd.DataFrame({'range': bars.high-bars.low, 'up': abs(bars.high-previous), 'down': abs(bars.low-previous)}).max(axis=1).rolling(r['atr_period']).mean()
    expected = {}

    def save(key, anchor, confirmation, low, high):
        if confirmation < len(bars) and np.isfinite(atr.iloc[confirmation]) and atr.iloc[confirmation] > 0 and high > low:
            expected.setdefault((key, anchor), (confirmation, low, high, atr.iloc[confirmation]))

    # Enumerate base formations, then find their FIRST qualifying departure.
    for b in range(r['base_bars']-1, len(bars)):
        region = bars.iloc[b-r['base_bars']+1:b+1]
        low, high, scale = region.low.min(), region.high.max(), atr.iloc[b]
        if not np.isfinite(scale) or scale <= 0 or high-low > r['base_atr']*scale:
            continue
        for key, direction in [('demand_zone', 1), ('supply_zone', -1)]:
            threshold = high+r['departure_atr']*scale if direction == 1 else low-r['departure_atr']*scale
            for i in range(b+1, min(len(bars), b+r['departure_bars']+1)):
                if direction*(bars.close.iloc[i]-threshold) >= 0:
                    save(key, b, i, low, high)
                    break

    # Enumerate pivot candles; only two-sided strict extrema qualify.
    s = r['swing_bars']
    for anchor in range(s, len(bars)-s):
        region = bars.iloc[anchor-s:anchor+s+1]
        others = region.drop(bars.index[anchor])
        for key, value, valid in [('support', bars.low.iloc[anchor], bars.low.iloc[anchor] < others.low.min()),
                                  ('resistance', bars.high.iloc[anchor], bars.high.iloc[anchor] > others.high.max())]:
            if valid:
                half = r['level_width_atr']*atr.iloc[anchor+s]/2
                save(key, anchor, anchor+s, value-half, value+half)

    # Breakouts are vectorized from strictly preceding rolling highs/lows.
    prior_high = bars.high.shift().rolling(r['breakout_bars']).max()
    prior_low = bars.low.shift().rolling(r['breakout_bars']).min()
    for direction, key in [(1, 'bullish_order_block'), (-1, 'bearish_order_block')]:
        opposite = pd.Series(np.where(direction*(bars.close-bars.open) < 0, np.arange(len(bars)), np.nan), index=bars.index)
        last_opposite = opposite.ffill().shift()
        breakout = bars.close > prior_high if direction == 1 else bars.close < prior_low
        for i in np.flatnonzero(breakout):
            if i < max(r['breakout_bars'], r['ob_lookback']) or pd.isna(last_opposite.iloc[i]):
                continue
            j = int(last_opposite.iloc[i])
            if i-j <= r['ob_lookback'] and direction*(bars.close.iloc[i]-bars.close.iloc[j]) >= r['departure_atr']*atr.iloc[i]:
                save(key, j, i, bars.low.iloc[j], bars.high.iloc[j])

    # Three-candle gaps: strict separation of first and third candle ranges.
    for i in np.flatnonzero(bars.high.shift(2) < bars.low):
        save('bullish_fvg', int(i-2), int(i), bars.high.iloc[i-2], bars.low.iloc[i])
    for i in np.flatnonzero(bars.low.shift(2) > bars.high):
        save('bearish_fvg', int(i-2), int(i), bars.high.iloc[i], bars.low.iloc[i-2])

    actual = {(e['pattern'], e['anchor']): (e['confirmation'], e['low'], e['high'], e['atr']) for e in events}
    assert len(actual) == len(events), 'Duplicate recognition anchors'
    assert actual.keys() == expected.keys(), f'Missing {expected.keys()-actual.keys()}; extra {actual.keys()-expected.keys()}'
    for key in expected:
        assert np.allclose(actual[key], expected[key], rtol=0, atol=1e-9), (key, actual[key], expected[key])
    assert not record.get('final_opened_at'), 'Final split must stay closed'
    report = {'passed': True, 'study_id': study_id, 'events_audited': len(events), 'checks': ['complete detection set', 'no duplicates', 'first valid confirmation', 'zone bounds', 'frozen ATR', 'artifact checksums'],
              'patterns': [{'key': key, 'name': name, 'audited': sum(e['pattern'] == key for e in events)} for key, name, _, _ in PATTERNS]}
    target = Path('reports/pattern-recognition')/study_id
    target.mkdir(parents=True, exist_ok=True)
    (target/'recognition-audit.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    latest = json.loads(Path('reports/pattern-recognition-latest.json').read_text())
    audit(latest['study_id'])
