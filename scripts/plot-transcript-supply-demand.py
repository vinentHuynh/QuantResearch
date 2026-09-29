"""Export figures from saved transcript ledgers; never reruns or selects rules."""
from pathlib import Path
import json
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'reports/transcript-supply-demand-2026-09-24'
plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 11, 'axes.spines.top': False,
                     'axes.spines.right': False, 'figure.facecolor': '#fafafa', 'axes.facecolor': '#fafafa'})

fig, axes = plt.subplots(2, 1, figsize=(11, 9), constrained_layout=True)
for name, color, label in [('baseline', '#146e9f', '1R baseline'), ('target_3r', '#bc6224', '3R sensitivity')]:
    f = pd.read_parquet(OUT / 'MGC' / name / 'equity.parquet')
    daily = f.assign(timestamp=pd.to_datetime(f.timestamp, utc=True)).set_index('timestamp').equity.resample('D').last().dropna()
    axes[0].plot(daily.index, daily.to_numpy() - 100000, label=label, color=color, linewidth=1.5)
axes[0].axhline(0, color='#777777', linewidth=.8)
axes[0].axvline(pd.Timestamp('2025-01-01', tz='UTC'), color='#999999', linestyle='--', linewidth=.8)
axes[0].axvline(pd.Timestamp('2026-01-01', tz='UTC'), color='#999999', linestyle='--', linewidth=.8)
axes[0].set(title='Micro gold: net marked P&L, one fixed contract', ylabel='USD after modeled costs')
axes[0].legend(loc='upper left', frameon=False)
axes[0].grid(axis='y', alpha=.15)
names = ['baseline', 'candle_stop', 'target_2r', 'target_3r', 'swing_1', 'swing_3', 'without_hourly_control', 'without_fvg_control']
labels = ['1R baseline', 'Previous-candle stop', '2R target', '3R target', '1-bar swings', '3-bar swings', 'No hourly filter (control)', 'No FVG filter (control)']
for i, name in enumerate(names):
    m = json.loads((OUT / 'MGC' / name / 'result.json').read_text())['periods']['all']
    value = m['mean_net_r']
    low, high = m['mean_r_95ci']
    axes[1].errorbar(value, i, xerr=np.array([[value - low], [high - value]]), fmt='o',
                     color='#146e9f' if i < 6 else '#888888', capsize=4)
axes[1].set_yticks(range(len(labels)), labels=labels)
axes[1].invert_yaxis()
axes[1].axvline(0, color='#444444', linewidth=1)
axes[1].set(title='Micro gold: all declared variants have negative mean net R',
            xlabel='Mean net R per trade with pointwise 95% weekly-bootstrap interval')
axes[1].grid(axis='x', alpha=.15)
fig.suptitle('Transcript supply / demand research | January 2022–July 2026', fontsize=15, fontweight='bold')
fig.savefig(OUT / 'gold-evidence.png', dpi=170)
plt.close(fig)

paths = [OUT / s / 'baseline/result.json' for s in ['MGC', 'GC', 'MNQ', 'NQ', 'ES', 'YM', 'CL']]
if all(p.exists() for p in paths):
    fig, ax = plt.subplots(figsize=(10, 4.5), constrained_layout=True)
    values = [json.loads(p.read_text())['periods']['all']['profit_factor'] for p in paths]
    labels = ['MGC', 'GC*', 'MNQ', 'NQ', 'ES', 'YM', 'CL']
    ax.bar(labels, values, color=['#146e9f' if v > 1 else '#bd6353' for v in values])
    ax.axhline(1, color='#444444', linestyle='--', linewidth=1)
    for i, v in enumerate(values):
        ax.text(i, v + .015, f'{v:.3f}', ha='center')
    ax.set(ylim=(0, max(values) + .15), ylabel='Net profit factor',
           title='Default 1R model across markets | correlated instruments, not independent replications')
    fig.supxlabel('*GC: September 2024–July 2026, 5m fills. Others: January 2022–July 2026, 1m fills.', fontsize=9)
    fig.savefig(OUT / 'baseline-markets.png', dpi=170)
    plt.close(fig)
print('Exported evidence figures to', OUT)
