"""Build a read-only portfolio catalog from checksum-verified research ledgers.

No strategy is rerun or promoted here. Baseline configurations are deduplicated;
cost and execution stress runs are evidence, never additional portfolio sleeves.
"""
from __future__ import annotations
import hashlib,json,os,sys,sqlite3
from pathlib import Path
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
OUT=Path(os.environ.get('WORKBENCH_HOME',ROOT/'data/workbench'))/'collective'
REPORTS=ROOT/'reports'
FIRST=REPORTS/'all-strategies-all-charts-2026-09-16'
EXPANDED=REPORTS/'expanded-search-2026-09-16'
SND=REPORTS/'snd-fresh-backtest-2026-09-16'
def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()
def dump(p,obj):
    text=json.dumps(obj,allow_nan=False,separators=(',',':'))
    tmp=Path(str(p)+'.tmp');tmp.write_text(text,encoding='utf-8');tmp.replace(p)
def verified(folder,names):
    manifest=read(folder/'manifest.json')
    hashes={a['name']:a['checksum'] for a in manifest['artifacts']} if 'artifacts' in manifest else manifest
    for name in names:
        if name not in hashes or sha(folder/name)!=hashes[name]:raise ValueError(f'Artifact checksum mismatch: {folder/name}')
    return manifest
def normalize(t,pnl='net_pnl'):
    if t.empty:return []
    a=pd.to_datetime(t.entry_time,utc=True);z=pd.to_datetime(t.exit_time,utc=True)
    assert (a<=z).all() and np.isfinite(t[pnl]).all()
    return [{'entry':x.isoformat(),'exit':y.isoformat(),'pnl':round(float(v),8)} for x,y,v in zip(a,z,t[pnl])]
def daily(equity,capital=100000):
    equity=equity.sort_index()
    assert equity.index.is_unique and np.isfinite(equity).all()
    e=equity.groupby(equity.index.floor('D')).last()
    p=e.diff();p.iloc[0]=e.iloc[0]-capital
    return {d.strftime('%Y-%m-%d'):round(float(v),8) for d,v in p.items()}

def canonical_run(run_id):
    f=Path(os.environ.get('WORKBENCH_HOME',ROOT/'data/workbench'))/'runs'/run_id
    manifest=verified(f,['trades.csv','equity.csv']);inp=read(f/'input.json')
    t=pd.read_csv(f/'trades.csv');e=pd.read_csv(f/'equity.csv')
    assert abs(t.net_pnl.sum()-manifest['metrics']['net_pnl'])<.01
    assert abs(e.equity.iloc[-1]-inp['capital']-t.net_pnl.sum())<.01
    marks=daily(pd.Series(e.equity.to_numpy(),index=pd.to_datetime(e.timestamp,utc=True)),inp['capital'])
    return normalize(t),marks,inp

PRICE_CACHE={}
def market_closes(symbol):
    if symbol not in PRICE_CACHE:
        inv=read(FIRST/'inventory.json');d=next(x for x in inv['datasets'] if x['symbol']==symbol)
        p=Path(d['path']);assert sha(p)==d['checksum']
        bars=pd.read_parquet(p,columns=['close']);idx=pd.to_datetime(bars.index,utc=True)+pd.Timedelta(minutes=1)
        PRICE_CACHE[symbol]=pd.Series(bars.close.to_numpy(),index=idx).groupby(idx.floor('D')).last()
    return PRICE_CACHE[symbol]
def expanded_run(r):
    f=EXPANDED/'runs'/r['run'];verified(f,['trades.csv','equity.csv','result.json']);t=pd.read_csv(f/'trades.csv')
    assert abs(t.net_pnl.sum()-r['net_pnl'])<.01
    # Reconstruct UTC daily open equity from the recorded positions and source closes.
    prices=market_closes(r['symbol']).loc[r['start']:r['end']]
    cutoffs=(prices.index+pd.Timedelta(days=1)).asi8
    t=t.sort_values('exit_time').reset_index(drop=True)
    entries=pd.DatetimeIndex(pd.to_datetime(t.entry_time,utc=True)).asi8
    exits=pd.DatetimeIndex(pd.to_datetime(t.exit_time,utc=True)).asi8
    if len(t):
        assert (entries[1:]>exits[:-1]).all()
        closed=np.r_[0.,t.net_pnl.cumsum().to_numpy()][np.searchsorted(exits,cutoffs,side='left')]
        loc=np.searchsorted(entries,cutoffs,side='left')-1
        active=(loc>=0)&(exits[np.maximum(loc,0)]>=cutoffs)
        sign=np.where(t.side=='long',1.,-1.)
        point={'NQ':20,'ES':50,'YM':5,'CL':1000}[r['symbol']]
        closed[active]+=sign[loc[active]]*(prices.to_numpy()[active]-t.entry.to_numpy()[loc[active]])*t.quantity.to_numpy()[loc[active]]*point-t.cost.to_numpy()[loc[active]]/2
    else:closed=np.zeros(len(prices))
    assert abs(closed[-1]-r['net_pnl'])<.01
    return normalize(t),daily(pd.Series(100000+closed,index=prices.index))

def main():
    OUT.mkdir(parents=True,exist_ok=True);items=[];errors=[];sources=[]
    def save(key,name,symbol,tf,session,source,segments,working=False,feasible=False,reasons=None,benchmark=False,parameters=None,capital=100000):
        trades=[];marks={};coverage=[]
        for start,end,tt,dd in sorted(segments):
            if coverage and start<=coverage[-1]['end']:raise ValueError('Overlapping source windows')
            coverage.append({'start':start,'end':end})
            trades.extend(tt)
            for date,value in dd.items():
                if start<=date<=end:
                    if date in marks:raise ValueError('Duplicate daily P&L')
                    marks[date]=value
        trades.sort(key=lambda t:(t['entry'],t['exit']))
        identity=hashlib.sha256((source+'|'+key).encode()).hexdigest()[:20]
        series={'id':identity,'daily':[{'date':d,'pnl':v} for d,v in sorted(marks.items())],'trades':trades,'coverage':coverage}
        payload=json.dumps(series,allow_nan=False,separators=(',',':')).encode();checksum=hashlib.sha256(payload).hexdigest()
        filename=f'{identity}-{checksum[:16]}.json';target=OUT/filename
        if not target.exists():target.write_bytes(payload)
        recent=sum(v for d,v in marks.items() if d>='2024-01-01')
        items.append({'id':identity,'key':key,'name':name,'symbol':symbol,'timeframe':tf,'session':session,'source':source,'start':coverage[0]['start'],'end':coverage[-1]['end'],'coverage':coverage,'capital':capital,'working':bool(working and not benchmark),'feasible':bool(feasible and not benchmark),'benchmark':benchmark,'tested':bool(coverage[-1]['end']>='2026-08-31'),'reasons':reasons or [],'parameters':parameters or {},'net_pnl':round(sum(marks.values()),6),'recent_pnl':round(recent,6),'trades':len(trades),'series_file':filename,'checksum':checksum})
    if (FIRST/'report-data.json').exists():
        report=read(FIRST/'report-data.json');sources.append({'name':'Workbench campaign','path':str(FIRST/'report-data.json'),'checksum':sha(FIRST/'report-data.json')})
        follow={r['key']:r for r in report['followups']}
        names={r['id']:r['name'] for r in report['overview']}
        for r in report['screen']:
            key=r['key'].removeprefix('screen__');f=follow.get(key);segments=[]
            try:
                for q in [r]+(f['baseline_rows'] if f else []):
                    tt,dd,inp=canonical_run(q['run_id']);segments.append((q['start'],q['end'],tt,dd))
                working=bool(f and f['complete'] and f['pass']);reasons=[]
                if not f:reasons.append('Screening only; later years and stress checks are not complete.')
                elif not working:reasons.append('Failed one or more later profit, risk or sample-size checks.')
                if r['strategy'].startswith('pine-'):reasons.append('Event-order delay sensitivity is untested.')
                if f and not f['sensitivity_positive']:reasons.append('Nearby parameter sensitivity includes a losing result.')
                if f and f['carry_trades']:reasons.append('Unexpected session carry requires exit-rule review.')
                feasible=working and f['sensitivity_positive'] and not f['carry_trades'] and not r['strategy'].startswith('pine-')
                if feasible:reasons.append('Later base, cost and delayed-execution scenarios plus nearby parameter checks passed; small samples and roll/margin assumptions still apply.')
                save(key,names.get(r['strategy'],r['strategy']),r['symbol'],r['timeframe'],r['session'],'Workbench',segments,working,feasible,reasons,r['strategy']=='buy-hold',r['parameters'])
            except Exception as ex:errors.append({'key':key,'error':str(ex)})
    if (EXPANDED/'screen-results.json').exists():
        conclusions={r['key']:r for r in read(EXPANDED/'conclusions.json')};later=read(EXPANDED/'follow-results.json');sources.append({'name':'Expanded search','path':str(EXPANDED/'conclusions.json'),'checksum':sha(EXPANDED/'conclusions.json')})
        for r in read(EXPANDED/'screen-results.json'):
            try:
                segments=[];c=conclusions.get(r['key'])
                for q in [r]+sorted([x for x in later if x['key']==r['key'] and x['scenario']=='baseline'],key=lambda x:x['start']):
                    tt,dd=expanded_run(q);segments.append((q['start'],q['end'],tt,dd))
                working=bool(c and c['numeric_pass'] and c['risk_pass']);reasons=['Literal cross-market settings; contract rolls and live margin are not modeled.']
                if not c:reasons.append('Screening only; later years and stress checks are not complete.')
                elif not working:reasons+=c['failures']+c['risk_failures']
                else:reasons.append('Three recent periods passed base, double-cost, conservative-execution and marked-risk checks. Parameter sensitivity and prospective validation remain untested.')
                # No full parameter-sensitivity campaign was performed for these rules.
                save(r['key'],r['strategy'].replace('-',' ').title(),r['symbol'],r['timeframe'],r['session'],'Expanded',segments,working,False,reasons)
            except Exception as ex:errors.append({'key':r['key'],'error':str(ex)})
    if (SND/'results.json').exists():
        decisions={(r['symbol'],r['variant']):r for r in read(SND/'decisions.json')};sources.append({'name':'Fresh SND','path':str(SND/'results.json'),'checksum':sha(SND/'results.json')})
        labels={'original_multi_tf':'SND original','phase6':'SND Phase 6','phase7_prior_1m':'SND prior-1m RVOL','phase7_prior_5m':'SND prior-5m RVOL'}
        for r in read(SND/'results.json'):
            if r['execution']!='next_open':continue
            try:
                f=SND/'runs'/f"{r['symbol']}__{r['variant']}__next_open";verified(f,['trades.parquet','daily-equity.csv','result.json'])
                t=pd.read_parquet(f/'trades.parquet');e=pd.read_csv(f/'daily-equity.csv',index_col=0);e.index=pd.to_datetime(e.index,utc=True)
                marks=daily(100000+e.pnl);start='2019-05-06' if r['symbol']=='MNQ' else '2018-01-01';end='2026-08-31'
                t=t[(t.exit_time>=pd.Timestamp(start,tz='UTC'))&(t.exit_time<pd.Timestamp('2026-09-01',tz='UTC'))]
                decision=decisions[(r['symbol'],r['variant'])]
                save(f"{r['symbol']}__{r['variant']}",labels[r['variant']],r['symbol'],'1h / 4h / 1d' if r['variant']=='original_multi_tf' else '1h','1m execution / all sessions','SND',[(start,end,normalize(t,'pnl'),marks)],decision['pass'],False,decision['failures']+['Next-open simulation, one contract. Pine percentage-risk sizing and TradingView parity are untested.'],parameters=r['parameters'])
            except Exception as ex:errors.append({'key':r['symbol']+'__'+r['variant'],'error':str(ex)})
    # New workbench runs also enter the catalog on refresh. Report campaigns
    # retain their richer historical review; their existing runs are not added twice.
    database=OUT.parent/'workbench.sqlite3'
    if database.exists():
        with sqlite3.connect(database.resolve().as_uri()+'?mode=ro',uri=True) as connection:
            records=[(kind,json.loads(body)) for kind,body in connection.execute('SELECT kind,body FROM records')]
        connection.close()
        runs={r['id']:r for kind,r in records if kind=='run'}
        evaluations={r['id']:r for kind,r in records if kind=='evaluation'}
        known=set()
        if (FIRST/'terminal-runs.json').exists():
            terminal=read(FIRST/'terminal-runs.json')
            known={r['id'] for r in terminal} if isinstance(terminal,list) else set(terminal)
        groups={}
        for r in runs.values():
            if r['id'] in known or r['status']!='Succeeded':continue
            inp=r['input'];research=inp.get('research',{})
            if research and (research.get('role')!='Test' or research.get('scenario')!='Baseline'):continue
            if not research and (inp.get('delay_bars',0) or any(word in (r.get('tags') or '').lower() for word in ['stress','sensitivity','benchmark'])):continue
            signature=json.dumps({k:inp.get(k) for k in ['timeframe','session','parameters','source_hash','capital','fee','slippage','warmup_days','delay_bars']}|{'strategy':inp['strategy']['id'],'symbol':inp['dataset']['symbol']},sort_keys=True)
            prior=groups.get(signature)
            if not prior or (inp['end'],r['created_at'])>(prior['input']['end'],prior['created_at']):groups[signature]=r
        for signature,r in groups.items():
            inp=r['input'];key=f"{inp['strategy']['id']}__{inp['dataset']['symbol']}__{inp['timeframe']}"
            try:
                e=evaluations.get(inp.get('research',{}).get('evaluation_id'));baseline=[]
                if e:
                    if e['status']!='Succeeded':continue
                    baseline=[runs[f['tests'][0]] for f in e['folds']]
                else:baseline=[r]
                segments=[]
                for run in baseline:
                    tt,dd,params=canonical_run(run['id']);segments.append((params['start'],params['end'],tt,dd))
                    assert params['capital']==inp['capital'],'Fold capital differs; cannot sum these books'
                scenarios=e.get('result',{}).get('scenarios',[]) if e else []
                required=set(e.get('scenarios',['Baseline','Higher costs','Delayed execution'])) if e else set()
                working=bool(scenarios and required<={s['name'] for s in scenarios} and all(s['outcome']=='Meets criteria' and s['metrics']['net_pnl']>0 for s in scenarios))
                reasons=['Latest completed workbench baseline. Parameter sensitivity and prospective validation are not established by this import.']
                old=[i for i in items if i['source']=='Workbench' and i['key']==key and i['parameters']==inp['parameters'] and i['session']==inp['session']]
                if any(i['tested'] and not i['working'] for i in old):working=False;reasons.append('Earlier matching later-period failures remain unresolved.')
                if not working:reasons.append('No complete passing multi-scenario evaluation establishes working status.')
                source=ROOT/inp['strategy']['file']
                if not source.exists() or sha(source)!=inp['strategy']['file_hash']:working=False;reasons.append('The current strategy adapter differs from the tested source.')
                items[:]=[i for i in items if i not in old]
                name=inp['strategy']['name']
                if inp['strategy']['id']=='snd':name+=' / '+inp['parameters']['variant'].replace('_',' ')
                save(key+'__'+hashlib.sha256(signature.encode()).hexdigest()[:10],name,inp['dataset']['symbol'],inp['timeframe'],inp['session'],'Current workbench',segments,working,False,reasons,inp['strategy']['id']=='buy-hold',inp['parameters'],capital=inp['capital'])
            except Exception as ex:errors.append({'key':key,'error':str(ex)})
    index={'version':1,'generated_at':pd.Timestamp.now(tz='UTC').isoformat(),'items':items,'errors':errors,'sources':sources,'definitions':{'working':'All available later-period baseline, cost and declared execution/risk checks passed. Unresolved tests remain visible.','feasible':'Working plus completed execution and parameter-sensitivity checks with no known session-exit flag. Historical research checklist only; not live approval.','pnl':'UTC calendar days, net of recorded fees and slippage. Independent strategy books; no position netting, shared margin or portfolio resizing.'}}
    dump(OUT/'index.json',index)
    print(json.dumps({'configurations':len(items),'working':sum(i['working'] for i in items),'feasible':sum(i['feasible'] for i in items),'errors':errors},indent=2))
    if errors:sys.exit(1)
if __name__=='__main__':main()
