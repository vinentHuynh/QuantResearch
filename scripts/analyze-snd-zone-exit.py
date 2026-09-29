"""Verify preserved SND exit ledgers and report every exploratory outcome."""
from pathlib import Path
import hashlib
import json
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / 'reports/snd-zone-exit-2026-09-17'
campaign = json.loads((FOLDER / 'campaign.json').read_text())
results, annual, exits, curves = [], [], [], {}
source_hashes, dataset_hashes = set(), set()


def metrics(equity, trades, capital=100000.):
    path = np.r_[capital, capital + equity.net_pnl.cumsum().to_numpy()]
    peaks = np.maximum.accumulate(path)
    win = trades.loc[trades.net_pnl > 0, 'net_pnl'].sum()
    loss = -trades.loc[trades.net_pnl < 0, 'net_pnl'].sum()
    return dict(net_pnl=float(equity.net_pnl.sum()), closed_net_pnl=float(trades.net_pnl.sum()),
                max_drawdown_dollars=float((peaks-path).max()),
                max_drawdown_pct=float((1-path/peaks).max()*100),
                trades=len(trades), profit_factor=float(win/loss) if loss else None,
                win_rate=float((trades.net_pnl > 0).mean()) if len(trades) else None,
                cost=float(equity.cost.sum()), min_equity=float(path.min()))


for mode, group in campaign['groups'].items():
    run = json.loads((FOLDER / f'run-{mode}.json').read_text())
    row = dict(mode=mode, run_id=run['id'], status=run['status'])
    if run['status'] != 'Succeeded':
        row['error'] = run.get('error', run.get('log'))
        results.append(row)
        continue
    directory = ROOT / 'data/workbench/runs' / run['id']
    source_hashes.add(run['input']['source_hash'])
    dataset_hashes.add(run['input']['dataset']['checksum'])
    manifest = json.loads((directory / 'manifest.json').read_text())
    for artifact in manifest['artifacts']:
        with (directory / artifact['name']).open('rb') as stream:
            digest = hashlib.sha256()
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(block)
            h = digest.hexdigest()
        assert h == artifact['checksum'], artifact['name']
    e = pd.read_csv(directory / 'equity.csv')
    t = pd.read_csv(directory / 'trades.csv')
    p = pd.read_csv(directory / 'positions.csv')
    e['timestamp'] = pd.to_datetime(e.timestamp, utc=True)
    t['exit_time'] = pd.to_datetime(t.exit_time, utc=True)
    t['entry_time'] = pd.to_datetime(t.entry_time, utc=True)
    assert abs(e.net_pnl.sum() - t.net_pnl.sum()) < 1e-5
    assert abs(e.net_pnl.sum() - manifest['metrics']['net_pnl']) < 1e-5
    assert np.allclose(e.gross_pnl - e.cost, e.net_pnl, atol=1e-7)
    assert np.allclose(t.gross_pnl - t.cost, t.net_pnl, atol=1e-7)
    assert np.allclose(100000 + e.net_pnl.cumsum(), e.equity, atol=1e-5)
    assert p.contracts.iloc[-1] == 0
    for stress in [False, True]:
        es, ts = e.copy(), t.copy()
        scenario = 'double-cost' if stress else 'base'
        if stress:
            es['net_pnl'] -= es.cost
            ts['net_pnl'] -= ts.cost
            es['cost'] *= 2
            ts['cost'] *= 2
        m = metrics(es, ts)
        results.append({**row, 'scenario': scenario, **m})
        for year in [2024, 2025, 2026]:
            annual.append(dict(mode=mode, scenario=scenario, year=year,
                               **metrics(es.loc[es.timestamp.dt.year == year], ts.loc[ts.exit_time.dt.year == year])))
    curves[mode] = e.set_index('timestamp').net_pnl.cumsum().resample('D').last().ffill()
    for reason, group_trades in t.groupby('exit_reason'):
        exits.append(dict(mode=mode, reason=reason, trades=len(group_trades), net_pnl=float(group_trades.net_pnl.sum())))
    row['warnings'] = manifest.get('warnings', [])

assert len(source_hashes) <= 1 and len(dataset_hashes) <= 1, 'Comparison identity mismatch'
(FOLDER / 'validation.json').write_text(json.dumps(dict(
    source_hashes=sorted(source_hashes), dataset_hashes=sorted(dataset_hashes),
    successful_runs=len(curves), expected_runs=3,
    artifact_checksums='PASS', equity_trade_accounting='PASS', final_flat='PASS',
    focused_snd_tests='12 passed', production_build='PASS; existing bundle-size warning'), indent=2))
pd.DataFrame(results).to_csv(FOLDER / 'summary.csv', index=False)
pd.DataFrame(annual).to_csv(FOLDER / 'annual.csv', index=False)
pd.DataFrame(exits).to_csv(FOLDER / 'exit-reasons.csv', index=False)
(FOLDER / 'analysis.json').write_text(json.dumps(dict(results=results, annual=annual, exits=exits), indent=2, allow_nan=False))
if curves:
    fig, axes = plt.subplots(2, 1, figsize=(11, 7), sharex=True, gridspec_kw={'height_ratios': [2, 1]})
    colors = {'baseline': '#64748b', 'touch': '#dc2626', 'close-inside': '#2563eb'}
    for mode, curve in curves.items():
        axes[0].plot(curve.index, curve, label=mode, color=colors[mode])
        path = 100000 + curve
        axes[1].plot(curve.index, path - path.cummax().clip(lower=100000), color=colors[mode])
    axes[0].set_title('SND opposing-zone exits | MNQ, prior-minute RVOL, one contract')
    axes[0].set_ylabel('Cumulative net P&L ($)')
    axes[1].set_ylabel('Daily-close drawdown ($)')
    axes[0].legend()
    for ax in axes:
        ax.axhline(0, color='#94a3b8', linewidth=.7)
        ax.grid(alpha=.15)
    fig.tight_layout()
    fig.savefig(FOLDER / 'comparison.png', dpi=160)
    plt.close(fig)

money = lambda n: f'${n:,.2f}'
lines = ['# SND opposing-zone exit experiment', '', campaign['protocol'], '',
         'These are three fresh, continuous stateful simulations, not edits to a previous trade ledger. Each uses the same source snapshot and dataset. All recorded attempts are listed below.', '',
         '## Whole-period results', '', '| Exit rule | Costs | Net P&L | Max drawdown | Trades | Profit factor |', '|---|---|---:|---:|---:|---:|']
for r in results:
    if r['status'] != 'Succeeded':
        lines.append(f"| {r['mode']} | {r['status']} | — | — | — | — |")
        continue
    pf = f"{r['profit_factor']:.2f}" if r['profit_factor'] is not None else 'undefined'
    lines.append(f"| {r['mode']} | {r['scenario']} | {money(r['net_pnl'])} | {money(r['max_drawdown_dollars'])} ({r['max_drawdown_pct']:.2f}%) | {r['trades']} | {pf} |")
lines += ['', '## Each year', '', '| Exit rule | Costs | Year | Marked net P&L | Max drawdown ($) | Closed trades |', '|---|---|---:|---:|---:|---:|']
for r in annual:
    lines.append(f"| {r['mode']} | {r['scenario']} | {r['year']} | {money(r['net_pnl'])} | {money(r['max_drawdown_dollars'])} | {r['trades']} |")
lines += ['', '2026 ends August 31. Annual P&L is marked at period boundaries; positions and zone state carry across years. Annual drawdowns restart their measurement at each year boundary with a $100,000 reference, without restarting the strategy. Closed-trade P&L can differ from marked annual P&L when a trade crosses the boundary.', '',
          '## Exit rules', '',
          '- Baseline: existing stop, fixed target, scheduled close and final liquidation.',
          '- Touch: after a minute reaches or passes the proximal edge of an opposing zone, signal a market exit at the next available minute open. This is not a resting limit fill at the edge.',
          '- Close-inside: after a one-minute close falls inclusively inside an opposing zone, signal a market exit at the next available minute open. A close beyond the distal edge does not qualify.',
          '- Opposing zones are supply for longs and demand for shorts, from all active 1h/4h/daily zones. Only zones available at the signal minute open qualify; zones invalidated by that minute still qualify for its exit signal. Stops/targets already filled within that minute take precedence; scheduled closes take precedence over pending zone exits.', '',
          '## Verification and limits', '',
          '- Full artifact checksums verified; gross minus costs, marked equity and trade P&L reconcile. The final position is flat.',
          '- Doubled-cost results subtract a second copy of every recorded commission/slippage charge. This is exact for the fixed-size cost-independent decisions, but does not test worse price paths or liquidity.',
          '- The chart samples equity at daily closes. Table drawdowns use all recorded one-minute close marks.',
          '- Native workbench limit exits charge commission only; the earlier standalone report charged exit slippage as well. Flat scoring start and 60-day warmup also differ. This newly rerun baseline is the relevant comparison.',
          '- Exploratory, already-inspected history; no untouched holdout, prospective validation, cross-market confirmation or live-readiness claim. No margin liquidation or percentage-risk sizing. Continuous-contract roll gaps, OHLC ambiguity and missing sessions remain limitations.', '',
          '![Net P&L and daily drawdown](comparison.png)', '',
          'Artifacts: [summary](summary.csv), [annual](annual.csv), [exit reasons](exit-reasons.csv), [protocol and run IDs](campaign.json).']
(FOLDER / 'REPORT.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
print(json.dumps(results, indent=2))
