"""Independent daily-warmup and native minute-schedule parity before launch."""
import json
from pathlib import Path

import numpy as np
import pandas as pd

from strategies.short_term_reversal_minute import STRATEGY, completed_rth_days, schedule
from strategy_engine.data import session_bars
from strategy_engine.sessions import get_session
from workbench.contract import checksum, resolve_parameters

ROOT=Path(__file__).resolve().parents[1]
FOLDER=ROOT/'reports/nq-reversal-minute-2026-09-17'
FOLDER.mkdir(exist_ok=True)
e=json.loads((ROOT/'reports/nq-reversal-development-2026-09-17/shorter-hold-followup/evaluation.json').read_text())
dataset=e['candidates'][0]['dataset']
assert checksum(dataset['path'])==dataset['checksum']
start=pd.Timestamp('2020-09-05',tz='UTC'); end=pd.Timestamp('2026-09-04',tz='UTC')
raw=pd.read_parquet(dataset['path'],filters=[('ts_event','>=',start-pd.Timedelta(days=600)),('ts_event','<',end)])
print(f'Building full-session minute bars from {len(raw):,} source rows',flush=True)
bars=session_bars(raw,get_session('full-trading-day'),'1m')
days=completed_rth_days(bars)
p=resolve_parameters(STRATEGY,{})
count=int((pd.to_datetime(days.availability_time,utc=True)<start).sum())
assert count>=p['trend_lookback']+1
old=pd.concat([pd.read_csv(ROOT/'data/workbench/runs'/r['id']/'trades.csv') for r in e['runs']
               if r['input']['research']['role']=='Test' and r['input']['research']['scenario']=='Baseline'],ignore_index=True)
expected=json.loads((ROOT/'reports/nq-reversal-development-2026-09-17/review/results.json').read_text())
results=[]
for delay in [0,1,5,15]:
    settings={**p,'open_delay_minutes':delay}
    mask=(bars.index>=start)&(pd.to_datetime(bars.availability_time,utc=True)<end)
    updates=schedule(bars,settings)
    held=0; entry_positions=[];exit_positions=[];expired=[]
    for row in updates.itertuples():
        pos=int(row.decision_index)
        if not mask.iloc[pos] or row.target==held or pos+1>=len(bars):
            continue
        deadline=row.decision_time.normalize()+pd.Timedelta(minutes=570+delay+settings['max_entry_lateness_minutes']) if row.target else row.decision_time.normalize()+pd.Timedelta(hours=16)
        if bars.index[pos+1]>deadline:
            expired.append({'decision':row.decision_time.isoformat(),'next_quote':bars.index[pos+1].isoformat(),'target':int(row.target)})
            continue
        if not mask.iloc[pos+1]:continue
        (entry_positions if row.target else exit_positions).append(pos+1)
        held=int(row.target)
    entries=bars.iloc[entry_positions];exits=bars.iloc[exit_positions]
    comparison=pd.DataFrame({'entry':entries.index.astype(str),'exit':exits.index.astype(str)})
    comparison.to_csv(FOLDER/f'preflight-schedule-{delay}m.csv',index=False)
    assert len(entries)==len(exits)==len(old)==130, (delay,len(entries),len(exits))
    assert held==0
    assert (entries.index.to_numpy()==(pd.to_datetime(old.entry_time,utc=True)+pd.Timedelta(minutes=delay)).to_numpy()).all()
    assert (exits.index.to_numpy()==(pd.to_datetime(old.exit_time,utc=True)+pd.Timedelta(minutes=delay)).to_numpy()).all()
    pnl=float(((exits.open.to_numpy()-entries.open.to_numpy())*dataset['point_value']-15).sum())
    prior=next(s for s in expected['scenarios'] if s['delay_minutes']==delay)
    assert abs(pnl-prior['net_pnl'])<1e-6
    selected=updates.loc[updates.decision_time>=start]
    results.append({'delay_minutes':delay,'expected_trades':130,'net_pnl':pnl,
                    'late_scheduling_days':int(selected.lateness_minutes.gt(0).sum()),
                    'entry_schedules':int(selected.target.gt(0).sum()),'expired_orders':expired})
    print(results[-1],flush=True)
report={'completed_at':pd.Timestamp.now(tz='UTC').isoformat(),'dataset_checksum':dataset['checksum'],
        'adapter_checksum':checksum(ROOT/'strategies/short_term_reversal_minute.py'),
        'daily_helper_checksum':checksum(ROOT/'strategies/short_term_reversal.py'),
        'completed_warmup_rth_days':count,'required_rth_days':p['trend_lookback']+1,
        'scored_minute_bars':int(mask.sum()),'parity':results,
        'note':'Schedule rebuilt from prices, never from saved trades. Independent parity comparison uses the previous diagnostic only after recomputing. No delay selected.'}
(FOLDER/'preflight.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report,indent=2),flush=True)
