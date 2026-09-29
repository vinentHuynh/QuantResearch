"""Exact direction inversion of verified ledgers; separately verify raw-bar simulation."""
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
PREVIOUS = ROOT / 'reports/vwap-full-2026-09-17'
OUT = ROOT / 'reports/vwap-inverse-2026-09-17'
OUT.mkdir(exist_ok=True)
originals = [r for r in json.loads((PREVIOUS/'results.json').read_text()) if r['status']=='Succeeded']
assert len(originals)==16
source = ROOT/'data/workbench/sources'/originals[0]['source_hash']
sys.path.insert(0,str(source))
from workbench.metrics import calculate

plan = {'declared_at':datetime.now(timezone.utc).isoformat(), 'method':'Exact signed-position inversion of checksum-verified original equity, trades and positions. Entry/exit times, prices, costs and turnover unchanged. Inverse gross=-original gross; inverse net=-original net-2*cost. Equity and risk recalculated from every bar, not by negating original equity or drawdown.', 'scope':'All 12 full-history variants, 2025 training, and 3 completed local 2026 scenarios from the earlier report. The recently completed app evaluation duplicates are not counted again.', 'bias':'Inverse hypothesis suggested after inspecting losses. All periods are historical and inspected; no fresh holdout, optimization or production eligibility claim.', 'verification':'Independently rebuild bars and original signals from frozen source, negate targets and run canonical simulate for default 5m full-history case.'}
if (OUT/'PLAN.json').exists():
    plan=json.loads((OUT/'PLAN.json').read_text())
else:
    (OUT/'PLAN.json').write_text(json.dumps(plan,indent=2))
rows=[]; curves={}
for original in originals:
    rid=original['id']; old=Path(original['artifact_dir']); new=OUT/rid; new.mkdir(exist_ok=True)
    manifest=json.loads((old/'manifest.json').read_text())
    request=json.loads((old/'input.json').read_text())
    for artifact in manifest['artifacts']:
        assert hashlib.sha256((old/artifact['name']).read_bytes()).hexdigest()==artifact['checksum']
    equity=pd.read_csv(old/'equity.csv'); trades=pd.read_csv(old/'trades.csv'); positions=pd.read_csv(old/'positions.csv')
    assert np.isclose(trades.net_pnl.sum(),original['metrics']['net_pnl'])
    old_equity=equity.copy()
    for frame in [equity,trades]:
        frame['gross_pnl']=-frame.gross_pnl
        frame['net_pnl']=frame.gross_pnl-frame.cost
    equity['equity']=request['capital']+equity.net_pnl.cumsum()
    trades['quantity']=-trades.quantity
    for col in ['contracts','intrabar_contracts']:
        positions[col]=-positions[col]
    assert np.allclose(equity.net_pnl,-old_equity.net_pnl-2*old_equity.cost)
    assert np.isclose(equity.net_pnl.sum(),trades.net_pnl.sum())
    metrics=calculate(equity,request['capital'],trades)
    assert np.isclose(metrics['net_pnl'],-original['metrics']['net_pnl']-2*original['metrics']['costs'])
    peak=equity.equity.cummax().clip(lower=request['capital'])
    wins=trades.loc[trades.net_pnl>0,'net_pnl']; losses=trades.loc[trades.net_pnl<0,'net_pnl']
    row={k:original[k] for k in ['group','id','timeframe','band','start','end','fee','slippage','delay','source_hash']}
    row.update(original_net_pnl=original['metrics']['net_pnl'],metrics=metrics,
               max_drawdown_dollars=float((peak-equity.equity).max()),
               profit_factor=float(wins.sum()/-losses.sum()) if len(losses) else None,
               win_rate=float(len(wins)/len(trades)),expectancy=float(trades.net_pnl.mean()),
               average_win=float(wins.mean()),average_loss=float(losses.mean()),
               minimum_equity=float(equity.equity.min()),
               yearly_net_pnl=equity.groupby(equity.timestamp.str[:4]).net_pnl.sum().to_dict(),
               net_without_top_10=float(trades.net_pnl.sum()-trades.net_pnl.nlargest(10).sum()),
               artifact_dir=str(new),method='exact inverse ledger replay',status='Verified')
    if original['group'].startswith('recent-local-'):
        row['declared_criteria_passed']=metrics['net_return']>=0 and abs(metrics['max_drawdown'])<=.35 and metrics['trades']>=100
    artifacts=[]
    for name,frame in [('equity',equity),('trades',trades),('positions',positions)]:
        file=new/f'{name}.csv';frame.to_csv(file,index=False)
        artifacts.append({'name':file.name,'checksum':hashlib.sha256(file.read_bytes()).hexdigest(),'rows':len(frame)})
    (new/'provenance.json').write_text(json.dumps({'original_input':request,'transform':plan['method'],'original_artifacts':manifest['artifacts']},indent=2))
    (new/'manifest.json').write_text(json.dumps({'method':plan['method'],'metrics':metrics,'artifacts':artifacts},indent=2))
    rows.append(row)
    if row['group']=='full-history': curves[f"{row['timeframe']} / {row['band']:.1%}"]=equity.groupby(equity.timestamp.str[:10]).equity.last()
(OUT/'results.json').write_text(json.dumps(rows,indent=2))
pd.DataFrame([{k:v for k,v in r.items() if not isinstance(v,(list,dict))}|{k:v for k,v in r['metrics'].items() if k!='monthly'} for r in rows]).to_csv(OUT/'results.csv',index=False)
fig,axes=plt.subplots(2,1,figsize=(12,8),sharex=True)
for label,daily in curves.items():
    dates=pd.to_datetime(daily.index)
    axes[0].plot(dates,daily.values-100000,label=label,linewidth=1)
    axes[1].plot(dates,daily.values-np.maximum.accumulate(np.maximum(daily.values,100000)),linewidth=1)
axes[0].set_ylabel('Cumulative net P&L ($)');axes[0].legend(ncol=3);axes[0].axhline(0,color='black',linewidth=.7)
axes[1].set_ylabel('Daily-close drawdown ($)')
for ax in axes:ax.grid(alpha=.2)
fig.suptitle('Inverse VWAP | NQ | one contract | identical fills and costs\nJune 7, 2010–September 3, 2026')
fig.tight_layout();fig.savefig(OUT/'equity-drawdown.png',dpi=150);plt.close(fig)
cash=lambda v: ('-' if v<0 else '')+f'${abs(v):,.0f}'
lines=['# Inverse VWAP reversion','',
       'Five of six main full-history inverses are profitable after costs. The 0.2% band produces $146,790 on 5m bars and $179,205 on 30m bars, with maximum marked drawdowns of $119,095 and $127,385. Profit factors are only 1.035 and 1.056. Every main inverse loses money in the 2026 portion of its continuous history.', '',
       'For 5m / 0.2%, doubled costs reduce net profit to $19,530. Removing the ten largest winners leaves a $47,900 loss; the same diagnostic leaves a $9,600 loss for 30m / 0.2%. This shows dependence on a small number of large winners, not an executable trade-removal rule. The frozen 2026 5m / 0.4% inverse loses $56,110 at baseline costs; all three recent inverse scenarios fail the original evaluation criteria.', '',
       plan['method'],'',plan['bias'],'',
       'This buys above VWAP and sells below VWAP at the same triggers where reversion took the opposite side. Exit decisions remain the original VWAP crossing/session-reset decisions. It is an exact inverse, not a redesigned momentum strategy.','',
       'NQ, June 7, 2010–September 3, 2026; one contract; $100,000 initial capital; New York RTH signals; baseline $2.50 per side plus one tick slippage per side ($15 round trip). No strategy source or app evidence was changed.','',
       '| Test | Chart | Band | Original net | Inverse net | Inverse max DD | PF | Win rate | Trades |',
       '|---|---|---:|---:|---:|---:|---:|---:|---:|']
for r in rows:
    lines.append(f"| {r['group']} | {r['timeframe']} | {r['band']:.1%} | {cash(r['original_net_pnl'])} | {cash(r['metrics']['net_pnl'])} | {cash(r['max_drawdown_dollars'])} | {r['profit_factor']:.3f} | {r['win_rate']:.1%} | {r['metrics']['trades']} |")
lines+=['','## Default 0.2% band by year','','| Year | 5m inverse | 30m inverse |','|---|---:|---:|']
defaults={r['timeframe']:r for r in rows if r['group']=='full-history' and r['band']==.002}
for year,value in defaults['5m']['yearly_net_pnl'].items():lines.append(f"| {year} | {cash(value)} | {cash(defaults['30m']['yearly_net_pnl'][year])} |")
verification_path=OUT/'raw-bar-verification.json'
if verification_path.exists():
    verification=json.loads(verification_path.read_text())
    assert verification['status']=='Passed'
    lines+=['','## Independent verification','',
            f"Fresh simulation from the checksum-verified raw dataset and frozen VWAP source matched every equity, position and trade row for the 5m / 0.2% full-history inverse: {verification['bars']:,} scored bars, {verification['trades']:,} trades, {cash(verification['net_pnl'])} net. All other comparisons use exact ledger inversion under the same symmetric accounting model."]
lines+=['','## Limits and interpretation','',
        '- Costs remain negative on both sides. Simply negating original net profit overstates inverse profit by twice the total fees and slippage.',
        '- Exact ledger inversion relies on this fixed-contract, symmetric-cost, next-open model. No cash constraint, margin liquidation, borrowing, market impact, asymmetric fills or position-dependent sizing is introduced.',
        '- Positions can carry overnight/weekends; these are RTH signal bars, not guaranteed day trades. Continuous unadjusted futures roll gaps and missing bars remain relevant. The table uses all scored bar-close marks; the chart uses daily-close drawdown.',
        '- Inverse selection occurred after observing original losses. Positive full-history P&L is exploratory evidence. Recent-period losses and every stress/neighbor result remain disclosed.',
        '- Annual P&L comes from continuous marked equity, including carried positions; standalone 2026 starts flat and can differ. First/last calendar years are partial.',
        '- Derived ledgers and provenance are saved under each original run ID within this report directory. They are local research artifacts, not new workbench runs or eligibility awards. Original app evaluation duplicates are not counted twice.',
        '', '![Inverse equity](equity-drawdown.png)', '',
        'Artifacts: [results.csv](results.csv), [full metrics](results.json), [plan](PLAN.json), [raw-bar verification](raw-bar-verification.json).']
(OUT/'REPORT.md').write_text('\n'.join(lines)+'\n')
print(json.dumps([{k:r[k] for k in ['group','timeframe','band','max_drawdown_dollars','profit_factor','win_rate']}|{'pnl':r['metrics']['net_pnl'],'drawdown_pct':r['metrics']['max_drawdown']} for r in rows],indent=2))
