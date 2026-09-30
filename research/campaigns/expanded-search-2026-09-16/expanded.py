"""Additional canonical-family research. Original implementations remain unchanged."""
from __future__ import annotations
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import numpy as np
import pandas as pd

SOURCE_DIR=Path(__file__).resolve().parent
ROOT=SOURCE_DIR.parents[2]
sys.path.insert(0,str(ROOT))
from workbench.layout import load_layout

def environment_path(name,fallback):
    value=os.environ.get(name)
    if not value:return fallback.resolve()
    candidate=Path(value).expanduser()
    return (candidate if candidate.is_absolute() else ROOT/candidate).resolve()

ARTIFACTS_ROOT=load_layout(ROOT).artifacts_root
FOLDER=environment_path('AW_EXPANDED_CAMPAIGN_DIR',ARTIFACTS_ROOT/'research/expanded-search-2026-09-16')
INVENTORY_PATH=environment_path('AW_EXPANDED_INVENTORY',ARTIFACTS_ROOT/'research/all-strategies-all-charts-2026-09-16/inventory.json')
from strategy_engine.catalog import STRATEGIES
from strategy_engine.sessions import SESSIONS
from strategy_engine.data import session_bars
from strategy_engine.strategies.opening_range_breakout import run as orb, OpeningRangeBreakoutConfig
from strategy_engine.strategies.prior_range_fill import run as fill, PriorRangeFillConfig
from strategy_engine.strategies.session_drift import run as drift, SessionDriftConfig

FAMILIES=['opening-range-breakout','prior-range-fill','overnight-session']
CAPITAL=100_000
INVENTORY=None
DATA={}

def ensure_inventory():
    global INVENTORY,DATA
    if INVENTORY is None:
        INVENTORY=json.loads(INVENTORY_PATH.read_text(encoding='utf-8'))
        if not isinstance(INVENTORY,dict) or not isinstance(INVENTORY.get('datasets'),list):
            raise ValueError(f'Invalid dataset inventory: {INVENTORY_PATH}')
        DATA={d['symbol']:d for d in INVENTORY['datasets']}
    return INVENTORY

def market_data(cfg):
    if 'tick_size' in cfg and 'point_value' in cfg:return cfg
    ensure_inventory()
    return DATA[cfg['symbol']]

def dump(path,value):
    Path(path).write_text(json.dumps(value,indent=2,allow_nan=False,default=str),encoding='utf-8')

def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()

def configs():
    ensure_inventory()
    return [dict(key='__'.join([s,m,tf,session]),strategy=s,symbol=m,timeframe=tf,session=session)
            for s in FAMILIES for m in DATA for session in STRATEGIES[s].sessions for tf in STRATEGIES[s].timeframes]

def fast_bars(source,session,tf):
    """Vectorized local-date labels; aggregation matches canonical session_bars."""
    local=source.tz_convert(session.timezone)
    minute=local.index.hour*60+local.index.minute
    start=session.opens_at.hour*60+session.opens_at.minute
    end=session.closes_at.hour*60+session.closes_at.minute
    mask=(minute>=start)|(minute<end) if session.crosses_midnight else (minute>=start)&(minute<end)
    local=local.loc[mask].copy(); minute=minute[mask]
    dates=local.index.tz_localize(None).normalize()
    if session.crosses_midnight:
        dates=dates+pd.to_timedelta(np.where(minute>=start,session.trading_date_offset_days,session.trading_date_offset_days-1),unit='D')
    else:dates=dates+pd.Timedelta(days=session.trading_date_offset_days)
    weekday=dates.weekday<5;local=local.loc[weekday];dates=dates[weekday]
    width=pd.Timedelta(minutes=int(tf[:-1])) if tf.endswith('m') else pd.Timedelta(hours=int(tf[:-1]))
    pieces=[]
    for date,day in local.groupby(dates,sort=True):
        opening=pd.Timestamp(session.open_datetime(date.date()));closing=pd.Timestamp(session.close_datetime(date.date()))
        day=day.loc[(day.index>=opening)&(day.index<closing)]
        if day.empty:continue
        bucket=((day.index-opening)//width).astype(int)
        r=day.groupby(bucket).agg({'open':'first','high':'max','low':'min','close':'last','volume':'sum'})
        r.index=pd.DatetimeIndex([opening+int(i)*width for i in r.index],name='event_time')
        r['availability_time']=[min(t+width,closing) for t in r.index]
        r['session_id']=session.id;r['session_date']=date.date().isoformat();pieces.append(r)
    return pd.concat(pieces).sort_index()

def prepare(symbol):
    ensure_inventory()
    d=DATA[symbol];assert sha(d['path'])==d['checksum']
    source=pd.read_parquet(d['path'])
    if not isinstance(source.index,pd.DatetimeIndex):source=source.set_index(pd.to_datetime(source.pop('ts_event'),utc=True))
    source=source.loc[(source.index>=pd.Timestamp('2017-12-01',tz='UTC'))&(source.index<pd.Timestamp('2026-09-01',tz='UTC'))]
    assert source.index.is_monotonic_increasing and source.index.is_unique
    folder=FOLDER/'bars'/symbol;folder.mkdir(parents=True,exist_ok=True)
    checks=[]
    for session_id in ['new-york-rth','london','asia','globex-overnight']:
        session=SESSIONS[session_id]
        for tf in ['1m','5m','15m','30m','1h']:
            out=fast_bars(source,session,tf)
            sample=source.loc['2024-03-08':'2024-03-12']
            expected=session_bars(sample,session,tf)
            actual=fast_bars(sample,session,tf)
            pd.testing.assert_frame_equal(actual,expected,check_freq=False)
            checks.append(f'{session_id}/{tf}: exact canonical resampling parity across March DST transition')
            out.to_parquet(folder/f'{session_id}__{tf}.parquet')
        print(f'Prepared {symbol} {session_id}',flush=True)
    dump(folder/'validation.json',{'source_checksum':d['checksum'],'checks':checks})
    return symbol

def load(cfg,start,end):
    b=pd.read_parquet(FOLDER/'bars'/cfg['symbol']/f"{cfg['session']}__{cfg['timeframe']}.parquet")
    # One month preserves previous-session context while all scored entries stay within the declared dates.
    warm=(pd.Timestamp(start)-pd.Timedelta(days=30)).date().isoformat()
    return b.loc[b.session_date.between(warm,end)]

def native(cfg,bars,cost_factor=1):
    d=market_data(cfg);tick=d['tick_size'];point=d['point_value']
    cost_ticks=cost_factor*(2+2.5/(tick*point))
    kw=dict(symbol=cfg['symbol'],tick_size=tick,point_value=point)
    if cfg['strategy']=='prior-range-fill':return fill(bars,config=PriorRangeFillConfig(cost_ticks=cost_ticks),**kw)
    if cfg['strategy']=='overnight-session':return drift(bars,config=SessionDriftConfig(cost_ticks=cost_ticks),**kw)
    opening=pd.read_parquet(FOLDER/'bars'/cfg['symbol']/f"{cfg['session']}__1m.parquet")
    # Calling the unchanged session-local function by day avoids repeated whole-history scans.
    days={date:day for date,day in opening.groupby('session_date',sort=False)}
    trades=[];signals=[]
    for date,day in bars.groupby('session_date',sort=True):
        t,s=orb(day,opening_bars=days[date],config=OpeningRangeBreakoutConfig(cost_ticks=cost_ticks),**kw)
        if len(t):trades.append(t)
        if len(s):signals.append(s)
    return (pd.concat(trades,ignore_index=True) if trades else pd.DataFrame(),pd.concat(signals,ignore_index=True) if signals else pd.DataFrame())

def conservative(cfg,bars,trades):
    """Declared next-open timing stress, gap-aware stops and stop-first ties. No reselection."""
    if trades.empty:return trades.copy()
    d=market_data(cfg);point=d['point_value'];tick=d['tick_size']
    groups={date:day for date,day in bars.groupby('session_date',sort=False)}
    opening=None
    if cfg['strategy']=='opening-range-breakout':
        op=pd.read_parquet(FOLDER/'bars'/cfg['symbol']/f"{cfg['session']}__1m.parquet")
        opening={date:day for date,day in op.groupby('session_date',sort=False)}
    rows=[]
    for original in trades.to_dict('records'):
        day=groups[original['session_date']]
        if cfg['strategy']=='overnight-session':pos=1
        else:
            avail=pd.to_datetime(day.availability_time,utc=True)
            matches=np.flatnonzero(pd.DatetimeIndex(avail).asi8==pd.Timestamp(original['entry_time']).value)
            if not len(matches):raise ValueError('Entry availability not found')
            pos=int(matches[0])+1
        if pos>=len(day):continue
        entry=float(day.iloc[pos].open);side=1 if original['side']=='long' else -1
        price=float(day.iloc[-1].close);exit_time=day.iloc[-1].availability_time;reason='session_close'
        if opening is not None:
            od=opening[original['session_date']];initial=od.loc[od.index<od.index[0]+pd.Timedelta(minutes=15)]
            risk=max(float(initial.high.max()-initial.low.min()),tick)
            stop=entry-side*risk;target=entry+side*2*risk
            for timestamp,bar in day.iloc[pos:].iterrows():
                stop_gap=(bar.open<=stop) if side==1 else (bar.open>=stop)
                stop_hit=(bar.low<=stop) if side==1 else (bar.high>=stop)
                target_hit=(bar.high>=target) if side==1 else (bar.low<=target)
                if stop_gap or stop_hit or target_hit:
                    price=float(bar.open) if stop_gap else stop if stop_hit else target
                    reason='gap_stop' if stop_gap else 'stop' if stop_hit else 'target';exit_time=bar.availability_time;break
        row={**original,'entry_time':day.index[pos].tz_convert('UTC').isoformat(),'entry':entry,'exit':price,'exit_time':pd.Timestamp(exit_time).tz_convert('UTC').isoformat(),'reason':reason}
        row['gross_pnl']=side*(price-entry)*point;row['net_pnl']=row['gross_pnl']-row['cost'];rows.append(row)
    return pd.DataFrame(rows,columns=trades.columns)

def metrics(trades,bars,start,end):
    calendar=sorted(bars.loc[bars.session_date.between(start,end),'session_date'].unique())
    daily=pd.DataFrame(index=pd.Index(calendar,name='session_date'))
    sums=trades.groupby('session_date')[['gross_pnl','cost','net_pnl']].sum() if len(trades) else pd.DataFrame(columns=['gross_pnl','cost','net_pnl'])
    daily=daily.join(sums).fillna(0);daily['equity']=CAPITAL+daily.net_pnl.cumsum()
    values=np.r_[CAPITAL,daily.equity.to_numpy()];peak=np.maximum.accumulate(values);dd=float(np.min(values/peak-1))
    returns=daily.net_pnl.to_numpy()/np.r_[CAPITAL,daily.equity.to_numpy()[:-1]]
    sharpe=float(np.mean(returns)/np.std(returns,ddof=1)*np.sqrt(252)) if np.std(returns,ddof=1)>0 and values.min()>0 else None
    wins=float(trades.loc[trades.net_pnl>0,'net_pnl'].sum()) if len(trades) else 0
    losses=-float(trades.loc[trades.net_pnl<0,'net_pnl'].sum()) if len(trades) else 0
    annual=daily.net_pnl.groupby(daily.index.str[:4]).sum().to_dict()
    result=dict(net_pnl=float(daily.net_pnl.sum()),gross_pnl=float(daily.gross_pnl.sum()),cost=float(daily.cost.sum()),drawdown=dd,drawdown_basis='session-close realized equity; excludes intratrade adverse excursions',sharpe=sharpe,trades=len(trades),positive_years=sum(v>0 for v in annual.values()),annual=annual,min_equity=float(values.min()),profit_factor=wins/losses if losses else None,win_rate=float((trades.net_pnl>0).mean()) if len(trades) else None,net_without_best5=float(trades.net_pnl.sum()-trades.net_pnl.nlargest(5).sum()) if len(trades) else 0)
    assert np.isfinite(daily.to_numpy()).all()
    assert abs(result['gross_pnl']-result['cost']-result['net_pnl'])<1e-5
    assert abs(float(daily.equity.iloc[-1])-CAPITAL-result['net_pnl'])<1e-5
    return result,daily

def execute(cfg,start,end,phase):
    bars=load(cfg,start,end);trades,signals=native(cfg,bars)
    if len(trades):trades=trades.loc[trades.session_date.between(start,end)].copy()
    scenarios={'baseline':trades}
    if phase!='screen':
        costs=trades.copy()
        if len(costs):costs['cost']*=2;costs['net_pnl']=costs.gross_pnl-costs.cost
        scenarios['double_cost']=costs
        scenarios['conservative_execution']=conservative(cfg,bars,trades)
    rows=[]
    for scenario,t in scenarios.items():
        if t.empty:t=pd.DataFrame(columns=['session_date','gross_pnl','cost','net_pnl'])
        m,daily=metrics(t,bars,start,end)
        name=f'{phase}__{cfg["key"]}__{scenario}';folder=FOLDER/'runs'/name;folder.mkdir(parents=True,exist_ok=True)
        t.to_csv(folder/'trades.csv',index=False);daily.to_csv(folder/'equity.csv')
        r={**cfg,'run':name,'phase':phase,'scenario':scenario,'start':start,'end':end,**m}
        dump(folder/'result.json',r)
        dump(folder/'manifest.json',{p.name:sha(p) for p in folder.iterdir() if p.name!='manifest.json'})
        rows.append(r)
    return rows

def eligible(r):
    return r['net_pnl']>0 and r['sharpe'] is not None and r['sharpe']>=.25 and r['drawdown']>=-.35 and r['positive_years']>=4 and r['trades']>=60 and r['net_pnl']>r['cost']

def main():
    global FOLDER,INVENTORY_PATH,INVENTORY,DATA
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=['prepare','screen','follow'])
    parser.add_argument('--campaign-dir',type=Path,default=FOLDER,help='Raw campaign artifact directory')
    parser.add_argument('--inventory',type=Path,default=INVENTORY_PATH,help='Dataset inventory JSON')
    args=parser.parse_args()
    FOLDER=args.campaign_dir.resolve();INVENTORY_PATH=args.inventory.resolve();INVENTORY=None;DATA={}
    os.environ['AW_EXPANDED_CAMPAIGN_DIR']=str(FOLDER);os.environ['AW_EXPANDED_INVENTORY']=str(INVENTORY_PATH)
    FOLDER.mkdir(parents=True,exist_ok=True);ensure_inventory()
    if args.stage=='prepare':
        plan=dict(created_at=pd.Timestamp.now(tz='UTC').isoformat(),harness_sha256=sha(__file__),configs=configs(),screen=['2018-01-01','2023-12-31'],later=[['2024-01-01','2024-12-31'],['2025-01-01','2025-12-31'],['2026-01-01','2026-08-31']],capital=CAPITAL,costs='One full-size contract; $1.25/side plus one tick/side, represented as equivalent round-trip cost ticks.',selection='Positive net, Sharpe >=0.25, session-close DD <=35%, at least 60 trades, 4/6 positive years, profit exceeds baseline costs. One highest-Sharpe timeframe/session per family/market; finer timeframe breaks ties; no replacement.',later_criteria='Every baseline, doubled-cost and conservative-execution scenario positive, session-close DD <=35%, at least 10 trades. Intratrade risk must be reviewed separately.',source_hashes={str(p.relative_to(ROOT)):sha(p) for p in (ROOT/'strategy_engine').rglob('*.py')},datasets=INVENTORY['datasets'],limitations=['Existing canonical variants; not certified full legacy parity.','Closed-trade accounting underestimates intratrade drawdown.','Unadjusted continuous contracts, no margin liquidation.','Previously inspected later history; not untouched holdout.','Whole-session ORB range begins at first observed minute; incomplete sessions need review.','Direct function reuse avoids a runner/config signature mismatch for session drift. No engine source changes.'])
        assert not (FOLDER/'PLAN.json').exists(),'Do not overwrite frozen plan'
        dump(FOLDER/'PLAN.json',plan)
        with ProcessPoolExecutor(max_workers=2) as pool:
            for f in as_completed([pool.submit(prepare,s) for s in DATA]):print('Prepared market',f.result(),flush=True)
        return
    if args.stage=='screen':tasks=[(c,'2018-01-01','2023-12-31','screen') for c in configs()]
    else:
        selected=json.loads((FOLDER/'FROZEN_SELECTIONS.json').read_text(encoding='utf-8'))['selections']
        tasks=[(c,start,end,str(start[:4])) for c in selected for start,end in [('2024-01-01','2024-12-31'),('2025-01-01','2025-12-31'),('2026-01-01','2026-08-31')]]
    rows=[]
    with ProcessPoolExecutor(max_workers=2) as pool:
        futures={pool.submit(execute,*task):task for task in tasks}
        for f in as_completed(futures):
            rows.extend(f.result());print(f'{args.stage}: {len(rows)} saved results; completed {futures[f][0]["key"]}',flush=True)
    rows.sort(key=lambda r:r['run']);dump(FOLDER/f'{args.stage}-results.json',rows);pd.DataFrame(rows).to_csv(FOLDER/f'{args.stage}-results.csv',index=False)
    if args.stage=='screen':
        selected=[]
        tf_order={'1m':0,'5m':1,'15m':2,'30m':3,'1h':4}
        for strategy in FAMILIES:
            for symbol in DATA:
                possible=[r for r in rows if r['strategy']==strategy and r['symbol']==symbol and eligible(r)]
                possible.sort(key=lambda r:(-round(r['sharpe'],10),tf_order[r['timeframe']],r['session']))
                if possible:selected.append({k:possible[0][k] for k in ['key','strategy','symbol','timeframe','session']})
        dump(FOLDER/'FROZEN_SELECTIONS.json',{'selected_at':pd.Timestamp.now(tz='UTC').isoformat(),'selections':selected})
        print('Frozen selections:',json.dumps(selected),flush=True)
    print('Stage complete:',args.stage,flush=True)

if __name__=='__main__':main()
