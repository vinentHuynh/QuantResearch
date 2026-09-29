"""Verify full VWAP ledgers and produce the campaign report without changing runs."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'reports/vwap-full-2026-09-17'
campaign = json.loads((OUT / 'campaign.json').read_text())
evaluation = json.loads((OUT / 'evaluation.json').read_text())
items = [(group, json.loads((OUT / f'run-{rid}.json').read_text()))
         for group, value in campaign['groups'].items() for rid in value['ids']]
items += [('recent-' + run['input']['research']['role'], run) for run in evaluation.get('runs', [])]
local_replays = json.loads((OUT / 'local-replays.json').read_text()) if (OUT / 'local-replays.json').exists() else []
items += [('recent-local-' + run['input']['research']['scenario'], run) for run in local_replays]
rows, curves = [], {}
for group, run in items:
    inp = run['input']
    row = dict(group=group, id=run['id'], status=run['status'], timeframe=inp['timeframe'],
               band=inp['parameters']['band'], start=inp['start'], end=inp['end'],
               fee=inp['fee'], slippage=inp['slippage'], delay=inp.get('delay_bars', 0),
               source_hash=inp['source_hash'])
    if run['status'] != 'Succeeded':
        row['error'] = run.get('error'); rows.append(row); continue
    folder = Path(run['artifact_dir']) if 'artifact_dir' in run else ROOT / 'data/workbench/runs' / run['id']
    if 'artifact_dir' in run:
        row['execution_location'] = 'isolated local replay of exact frozen inputs'
        row['queued_workbench_run_id'] = run['queued_workbench_run_id']
        row['declared_criteria_passed'] = run['declared_criteria_passed']
    manifest = json.loads((folder / 'manifest.json').read_text())
    for artifact in manifest['artifacts']:
        assert hashlib.sha256((folder / artifact['name']).read_bytes()).hexdigest() == artifact['checksum']
    equity = pd.read_csv(folder / 'equity.csv')
    trades = pd.read_csv(folder / 'trades.csv')
    capital = inp['capital']; metrics = manifest['metrics']
    pnl = trades.net_pnl.sum()
    assert np.isclose(pnl, metrics['net_pnl'], atol=.0001)
    assert np.isclose(equity.net_pnl.sum(), pnl, atol=.0001)
    assert np.isclose(equity.equity.iloc[-1] - capital, pnl, atol=.0001)
    assert np.isclose(trades.cost.sum(), metrics['costs'], atol=.0001)
    assert len(trades) == metrics['trades']
    peak = equity.equity.cummax().clip(lower=capital)
    dd = peak - equity.equity
    assert np.isclose((equity.equity / peak - 1).min(), metrics['max_drawdown'], atol=1e-8)
    wins = trades.loc[trades.net_pnl > 0, 'net_pnl']; losses = trades.loc[trades.net_pnl < 0, 'net_pnl']
    overnight = trades.entry_time.str[:10] != trades.exit_time.str[:10]
    holding_hours = (pd.to_datetime(trades.exit_time, utc=True) - pd.to_datetime(trades.entry_time, utc=True)).dt.total_seconds() / 3600
    years = equity.groupby(equity.timestamp.str[:4]).net_pnl.sum().to_dict()
    months = equity.groupby(equity.timestamp.str[:7]).net_pnl.sum().to_dict()
    row.update(metrics=metrics, artifact_dir=str(folder), max_drawdown_dollars=float(dd.max()),
               profit_factor=float(wins.sum() / -losses.sum()) if len(losses) else None,
               win_rate=float(len(wins) / len(trades)) if len(trades) else None,
               expectancy=float(pnl / len(trades)) if len(trades) else None,
               gross_pnl=float(trades.gross_pnl.sum()),
               average_holding_hours=float(holding_hours.mean()), maximum_holding_hours=float(holding_hours.max()),
               average_win=float(wins.mean()) if len(wins) else None,
               average_loss=float(losses.mean()) if len(losses) else None,
               largest_win=float(trades.net_pnl.max()), largest_loss=float(trades.net_pnl.min()),
               yearly_net_pnl=years, monthly_net_pnl=months,
               overnight_trades=int(overnight.sum()), overnight_net_pnl=float(trades.loc[overnight, 'net_pnl'].sum()),
               same_day_net_pnl=float(trades.loc[~overnight, 'net_pnl'].sum()),
               long_net_pnl=float(trades.loc[trades.quantity > 0, 'net_pnl'].sum()),
               short_net_pnl=float(trades.loc[trades.quantity < 0, 'net_pnl'].sum()),
               net_without_top_10=float(pnl - trades.net_pnl.nlargest(10).sum()),
               minimum_equity=float(equity.equity.min()), warnings=manifest.get('warnings', []),
               artifact_verification='All artifact SHA256 checks and ledger reconciliation passed')
    rows.append(row)
    if group == 'full-history':
        daily = equity.groupby(equity.timestamp.str[:10]).equity.last()
        curves[f"{inp['timeframe']} / {row['band']:.1%}"] = daily
    pd.DataFrame([{'year':y,'net_pnl':v} for y,v in years.items()]).to_csv(OUT / f'yearly-{run["id"]}.csv',index=False)
for baseline in [r for r in rows if r['group']=='full-history' and r['timeframe']=='5m']:
    stress = next(r for r in rows if r['group']=='higher-costs' and r['band']==baseline['band'])
    if 'metrics' in baseline and 'metrics' in stress:
        assert np.isclose(stress['metrics']['net_pnl'], baseline['metrics']['net_pnl'] - baseline['metrics']['costs'])
(OUT / 'results.json').write_text(json.dumps(rows, indent=2))
pd.DataFrame([{k:v for k,v in r.items() if not isinstance(v,(dict,list))} | r.get('metrics', {}) for r in rows]).drop(columns=['monthly'],errors='ignore').to_csv(OUT / 'results.csv',index=False)
fig, axes = plt.subplots(2,1,figsize=(12,9),sharex=True)
for label, daily in curves.items():
    dates = pd.to_datetime(daily.index)
    axes[0].plot(dates, daily.values-100000, label=label, linewidth=1)
    axes[1].plot(dates, daily.values-np.maximum.accumulate(np.maximum(daily.values,100000)), linewidth=1)
axes[0].axhline(0,color='black',linewidth=.7); axes[0].set_ylabel('Cumulative net P&L ($)'); axes[0].legend(ncol=3)
axes[1].set_ylabel('Daily-close drawdown ($)'); axes[1].set_xlabel('Historical date')
for ax in axes: ax.grid(alpha=.2)
fig.suptitle('NQ session VWAP reversion | one contract | costs included\nJune 2010–September 3, 2026; RTH signals may carry overnight')
fig.tight_layout(); fig.savefig(OUT/'equity-drawdown.png',dpi=160); plt.close(fig)
cash = lambda x: ('-' if x < 0 else '') + f'${abs(x):,.0f}' if x is not None else 'n/a'
main = [r for r in rows if r['group'] == 'full-history']
verdict = ('All six main full-history configurations lost money after costs. These results do not support this implementation as a profitable full-history strategy under the declared assumptions.'
           if len(main) == 6 and all(r.get('metrics', {}).get('net_pnl', 1) < 0 for r in main)
           else 'See the complete attempt table for performance and execution status; incomplete records are not passing evidence.')
lines = ['# VWAP reversion full backtest','',f"Report generated {datetime.now(timezone.utc).isoformat()}. App status below is a snapshot at report generation.",'',verdict,'',campaign['protocol'],'',
         'All results below are current-source historical simulations, with every attempted run retained. Exact inputs and source hashes are in campaign.json and results.json. Artifact checksums, trade/equity P&L, costs, counts and drawdowns were independently reconciled for each successful run. The repository original-rule parity test and synthetic prefix/future-price perturbation checks passed; see signal-checks.json.','',
         'Two source snapshot hashes were captured during launch. Their only difference is the concurrent addition of an unrelated reversal audit script; all existing VWAP, helper, and engine source files match. See final-verification.json.','',
         '## All attempts','', '| Test | Dates | Chart | Band | Status | Net P&L | Max DD | Trades | PF | Win rate |',
         '|---|---|---|---:|---|---:|---:|---:|---:|---:|']
for r in rows:
    m=r.get('metrics',{})
    pf = f"{r['profit_factor']:.3f}" if r.get('profit_factor') is not None else 'n/a'
    wr = f"{r['win_rate']:.1%}" if r.get('win_rate') is not None else 'n/a'
    lines.append(f"| {r['group']} (fee {r['fee']}, slip {r['slippage']}, delay {r['delay']}) | {r['start']} to {r['end']} | {r['timeframe']} | {r['band']:.1%} | {r['status']} | {cash(m.get('net_pnl'))} | {cash(r.get('max_drawdown_dollars'))} | {m.get('trades','-')} | {pf} | {wr} |")
lines += ['', '## Five-minute full-history annual results','', '| Year | Default 0.2% | Prior 0.4% |','|---|---:|---:|']
base = [r for r in rows if r['group']=='full-history' and r['timeframe']=='5m' and 'metrics' in r]
if len(base)==2:
    base.sort(key=lambda r:r['band'])
    for year in base[0]['yearly_net_pnl']:
        lines.append(f"| {year} | {cash(base[0]['yearly_net_pnl'][year])} | {cash(base[1]['yearly_net_pnl'][year])} |")
lines += ['', 'Annual figures attribute the continuous full-history marked equity path and include carried positions at year boundaries. Standalone yearly runs start flat and liquidate at their final close, so their P&L can differ.', '', '## Exposure and concentration','']
for r in base:
    lines += [f"- {r['band']:.1%} band: {r['overnight_trades']:,} trades cross a New York calendar date; these contribute {cash(r['overnight_net_pnl'])}, versus {cash(r['same_day_net_pnl'])} for same-day trades. Long trades: {cash(r['long_net_pnl'])}; short trades: {cash(r['short_net_pnl'])}. Removing the ten largest winning trades leaves {cash(r['net_without_top_10'])}. Minimum marked equity: {cash(r['minimum_equity'])}. Longest trade: {r['maximum_holding_hours']:.1f} hours."]
lines += ['', 'These are after-the-fact trade partitions. Losing trades can remain open while winners exit at VWAP; excluding overnight trades from a ledger would select outcomes. A same-day exit or long-only rule would require a separate backtest and is not validated here.']
lines += ['', '## Recent evaluation','', f"Evaluation ID: `{evaluation['id']}`. Execution status: {evaluation['status']}. Exactly one candidate was frozen; training cannot choose a different parameter. 2025 is training; January 1–September 3, 2026 is scored. These periods have been inspected previously and are not fresh holdouts.",'']
if local_replays:
    lines += ['The three test scenarios were delayed behind an unrelated research batch. Additional local replays use the exact queued inputs and frozen source/environment, with new IDs and artifacts isolated under local-replays/. The worker verified data/source/dependency checksums. These do not update workbench evaluation status. The original app attempts remain visible above and may still be queued/running. The original protocol has 16 attempts; these three duplicate replays bring the disclosed total to 19. Local pass/fail uses the same frozen criteria (nonnegative return, drawdown no greater than 35%, at least 100 trades).','']
    for run in local_replays:
        m = run.get('result', {}).get('metrics', {})
        lines.append(f"- Local {run['input']['research']['scenario']}: {cash(m.get('net_pnl'))}; drawdown {abs(m.get('max_drawdown', 0)):.2%}; trades {m.get('trades')}; declared criteria passed: {run.get('declared_criteria_passed')}.")
for scenario in (evaluation.get('result') or {}).get('scenarios',[]):
    lines.append(f"- {scenario['name']}: {cash(scenario['metrics']['net_pnl'])}; outcome: {json.dumps(scenario.get('outcome'))}.")
lines += ['', '## Assumptions and limits','',
          '- Session VWAP uses cumulative selected-bar typical price times volume divided by cumulative volume. Long below the negative band, short above the positive band; exit decision at a VWAP crossing. No stop-loss or profit-target bracket. Decision state resets each session, but the execution model can carry the position across overnight/weekend gaps until a subsequent selected-bar fill.',
          '- Signals use completed bars; standard fills occur at next available selected-bar open. Delay stress adds one more bar. Each run begins flat and liquidates at its final scored close. Baseline round-trip costs are $15 per NQ contract ($5 commission plus $10 slippage). Stress doubles both components.',
          '- Fixed one-contract sizing with $100,000 initial capital; no compounding, broker margin, financing, or liquidation simulation. If equity falls below zero, the engine continues; such a path is not financeable with the stated initial capital.',
          '- Continuous futures prices are unadjusted and can contain roll gaps. Missing-bar and exchange-holiday completeness is not certified. Bar-close maximum drawdown omits intrabar extremes. The plot uses daily-close drawdown; the table uses every scored bar.',
          '- Full-history starts at dataset inception, so there is no pre-start warmup. This VWAP initializes within each session and has no multi-day lookback; warmup coverage is undeclared, not certified by preview. First and last years are partial.',
          '- The 0.4% band comes from earlier research and carries selection bias. This campaign does not tune parameters, select a new winner, or claim untouched validation. Nearby bands and chart intervals are disclosed diagnostics, not independent evidence.',
          '', '![Equity and drawdown](equity-drawdown.png)', '',
          'Artifacts: [all results](results.csv), [full results and yearly/monthly attribution](results.json), [campaign and run IDs](campaign.json), [recent evaluation](evaluation.json).']
(OUT/'REPORT.md').write_text('\n'.join(lines)+'\n')
print(json.dumps([{k:r.get(k) for k in ['group','timeframe','band','status','max_drawdown_dollars','profit_factor','win_rate']} | {'pnl':r.get('metrics',{}).get('net_pnl'),'trades':r.get('metrics',{}).get('trades')} for r in rows],indent=2))
