"""Deterministic unscored formation review before launching scored candidates."""
from pathlib import Path
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from strategies.remaining_zone_failure import RemainingZoneFailure, STRATEGY
from strategy_engine.data import session_bars
from strategy_engine.sessions import get_session

folder = Path(__file__).resolve().parent
dataset = json.loads((folder / 'dataset.json').read_text(encoding='utf-8-sig'))
start, end = pd.Timestamp('2021-12-01', tz='UTC'), pd.Timestamp('2021-12-29', tz='UTC')
frame = pd.read_parquet(dataset['path'], filters=[('ts_event', '>=', start), ('ts_event', '<', end)])
bars = session_bars(frame, get_session('full-trading-day'), '15m')
fig, axes = plt.subplots(5, 2, figsize=(16, 19), constrained_layout=True)
review = []
for ax, mode in zip(axes.flat, STRATEGY['parameters']['detector']['choices']):
    model = RemainingZoneFailure(bars, {'detector': mode, 'zone_half_width_atr': 0.10, 'swing_sides': 2},
                                 {'dataset': dataset, 'start': '2022-01-01', 'end': '2024-12-31'})
    for i, (_, bar) in enumerate(bars.iterrows()):
        assert model.on_close(i, bar, {'position': 0, 'tradable': False}) is None
    for formation in model.formations:
        assert pd.Timestamp(formation['source_end']) <= pd.Timestamp(formation['confirmed'])
    item = {'detector': mode, 'unscored_formations': len(model.formations), 'source_release_check': True}
    if not model.formations:
        item['review'] = 'No detection in the prespecified preview; synthetic detector fixtures remain available.'
        ax.text(0.5, 0.5, 'No December preview formation', ha='center')
    else:
        formation = model.formations[0]
        i = formation['index']
        begin, finish = max(0, i - 24), min(len(bars), i + 17)
        sample = bars.iloc[begin:finish]
        x = np.arange(len(sample))
        ax.vlines(x, sample.low, sample.high, color='#8294a6', linewidth=1)
        ax.plot(x, sample.close, color='#193d6a', linewidth=1.2)
        ax.axhspan(formation['low'], formation['high'], color='#e6a23c', alpha=0.28)
        ax.axhline(formation['price'], color='#a86406', linewidth=1)
        ax.axvline(i - begin + 0.5, color='#c33447', linestyle='--', label='Formation close')
        positions = [0, i - begin, len(sample) - 1]
        ax.set_xticks(positions, [sample.index[k].tz_convert('America/Chicago').strftime('%m/%d %H:%M') for k in positions], fontsize=8)
        ax.set_ylabel('NQ price')
        ax.legend(fontsize=8, loc='best')
        item['first_formation'] = formation
        item['review'] = 'First deterministic warmup-era formation; source available by activation; fixed zone and causal release reviewed.'
    ax.set_title(mode, fontsize=12)
    ax.grid(alpha=0.15)
    review.append(item)
fig.suptitle('Remaining detectors: first December 2021 formation per candidate\nWarmup-era detection review; no scored strategy results', fontsize=17)
fig.savefig(folder / 'formation-review.png', dpi=140)
plt.close(fig)
(folder / 'detection-review.json').write_text(json.dumps(review, indent=2))
print(json.dumps([{'detector': r['detector'], 'formations': r['unscored_formations']} for r in review]))
