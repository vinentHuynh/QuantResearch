"""Preserved full factorial supply/demand research and chronological validation.

The finite grid is exhaustive for declared concepts/levels, not every possible
strategy or continuous parameter. All history is previously inspected.
"""
from __future__ import annotations
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import importlib.util
import itertools
import json
import os
from pathlib import Path
import platform
import shutil
import sys
import time
import traceback
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'reports/snd-combinations-2026-09-26'
PRIOR=ROOT/'reports/snd-zone-quality-2026-09-25'
GRID={
    'max_zone_width_atr':[None,.5,1.],
    'min_departure_atr':[None,1.,1.5],
    'min_departure_rvol':[None,1.5,2.],
    'max_touch_age_hours':[None,1.,4.],
    'use_htf':[True,False],
    'require_fvg':[False,True],
    'min_opposing_room_r':[2.,0.],
    'entry_eligibility':['first_touch','any_touch'],
    'order_lifetime_bars':[1,3],
    'stop_model':['zone','candle'],
    'zone_boundary':['wick','body'],
}

def now(): return datetime.now(timezone.utc).isoformat()

def checksum(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(1048576),b''): h.update(b)
    return h.hexdigest()

def clean(x):
    if isinstance(x,dict): return {str(k):clean(v) for k,v in x.items()}
    if isinstance(x,(tuple,list)): return [clean(v) for v in x]
    if isinstance(x,np.generic): return clean(x.item())
    if isinstance(x,float) and not np.isfinite(x): return None
    if isinstance(x,(datetime,pd.Timestamp)): return x.isoformat()
    return x

def read(path): return json.loads(Path(path).read_text(encoding='utf-8'))

def save(path,value):
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.name+'.tmp-'+str(os.getpid()))
    tmp.write_text(json.dumps(clean(value),indent=2,allow_nan=False),encoding='utf-8')
    os.replace(tmp,path)

def load_module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    m=importlib.util.module_from_spec(spec)
    sys.modules[name]=m
    spec.loader.exec_module(m)
    return m

def configurations(base,grid=GRID):
    result=[]
    for i,values in enumerate(itertools.product(*grid.values())):
        p=base|dict(zip(grid,values))
        digest=hashlib.sha256(json.dumps(p,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        result.append(dict(config_id=f'c{i:05d}',parameter_hash=digest,parameters=p))
    assert len({x['parameter_hash'] for x in result})==len(result)
    return result

def declare(out):
    if (out/'protocol.json').exists(): return read(out/'protocol.json')
    prior=read(PRIOR/'protocol.json')
    base=next(c['parameters'] for c in prior['cases'] if c['symbol']=='MNQ' and c['variant']=='baseline')|{'zone_boundary':'wick'}
    configs=configurations(base)
    assert len(configs)==10368
    out.mkdir(parents=True,exist_ok=True)
    save(out/'configurations.json',configs)
    p=dict(declared_at=now(),objective='Test every combination of the declared supply/demand concepts and validate historical implementation, selection, economics, sensitivity and transfer without claiming unavailable prospective evidence.',
        scope='Full Cartesian product of11 dimensions,10,368 configurations/market on4 markets. Fixed target1R,pivot2,fullsession,onecontract,zoneage288/cap100,30daywarmup. Targets/pivots are separate post-selection sensitivity checks. No claim to exhaust arbitrary continuous values, news/session rules, or every possible trading system.',
        grid=GRID,configurations_file='configurations.json',configurations_checksum=checksum(out/'configurations.json'),
        expected_configurations=10368,expected_market_cases=41472,markets=['MNQ','MGC','ES','CL'],datasets=prior['datasets'],
        inherited_protocol_checksum=checksum(PRIOR/'protocol.json'),capital=100000.,
        base_costs='Percontractperside fee MNQ/MGC1.25,ES/CL2.50;1tick cashslip entry/nonlimitexit; targetlimits commissiononly. Onefixedcontract decisions costindependent; doublecashcost can be repriced exactly for same fills.',
        boundaries='Wick/body geometry applies to entry AND opposing context. Formation conditions remain strict wickgap versus relaxedclose displacement. Physical touches, invalidation and triggers always use raw wicks. Selected-boundary width/ATR is frozen at formation; prebase ATR andvolume exclude entire3barformation.',
        folds=[dict(id='2024',training_start='2022-01-01',cutoff='2024-01-01',test_end='2025-01-01'),
               dict(id='2025',training_start='2022-01-01',cutoff='2025-01-01',test_end='2026-01-01'),
               dict(id='2026_jan_jul',training_start='2022-01-01',cutoff='2026-01-01',test_end='2026-08-01')],
        training='Causal fullrun prefixes: only exited trades observed by cutoff plus liquidation of the atmostone stillopen trade at last observed source close bycutoff with exitcost. Verify reconstruction against exact prefix reruns before using selection. Never use later exitprice/PnL. Same initialJan2022 flatstart30daywarmup. Fold reruns start flat at cutoff with causal30daywarmup; no inherited training position/order.',
        selection=dict(eligibility='Atleast200 training trades,atleast50 inlast12months,positive mean netR andpositive doubledcashcost trainingnet. Zero/failed/sparse configurations remain visible. Noeligible candidate means holdcash; no relaxation.',
            rank='Largest mean_net_R minus1.645*calendarweekcluster standarderror. Then fewer activated quality filters, then stable config_id. Selection is recorded before selectedfold test is launched. No ranking by subsequent outcomes.',
            reference='c00000: relaxedwick,firsttouch,TTL1,zonestop,hourlyalignment,room2,allqualityfiltersdisabled.',
            research_exposure='Rules,thresholds andthese historical markets were previously researched. This is retrospective walkforward selection, not a pristine holdout. The entire trial family is retained; no overall future validation claim.'),
        validation_scenarios=[dict(id='cash_base',slippage_model='cash',fee_multiple=1,slippage_ticks=1),
            dict(id='cash_double',slippage_model='cash',fee_multiple=2,slippage_ticks=2),
            dict(id='price_1',slippage_model='price',fee_multiple=1,slippage_ticks=1),
            dict(id='price_2_double_fee',slippage_model='price',fee_multiple=2,slippage_ticks=2)],
        validation_neighbors=[{'rr':.75},{'rr':1.25},{'rr':2.},{'rr':3.},{'pivot_len':1},{'pivot_len':3}],
        validation_rules='Selected configurations and unchanged reference rerun eachfold flat under4executioncostscenarios. Selectedmodels also6target/pivotneighbors. Save all selectedcases even ifnegative. Neighbors never replace selectedparameters. Fullstateful integer-risk sizing stresses required for any claimed feasible candidate; earlier riskcampaign is contextual only.',
        confidence='Family-aware calendarweek blockbootstrap with common resampledblocks; fixedseed20260926 and4weekblocks. Report selection-aware stitchedfoldperformance and fullfamily retrospective screens separately. Degenerate/sparse samples unavailable. Neither one winning combination nor ordinary unadjusted singlewinnerconfidence establishes edge.',
        gates='Implementation: exact reference parity, causalprefix reconstruction, no futurefeature contamination, allgridcellsaccountedfor, checksummed source/data/artifacts, full accounting. Historicaleconomics: positive pooled selectedfold meanR,positive pooled net underall4scenarios,atleast200pooledtrades and50perannualfold/25partialfold,positive cashbaselineineachfold,positive4weekbootstrap95%lowerbound onpooledmeanR,5of6neighborpathspositivepooled. Transfer separately bymarket; MNQ/ES correlated. All remain historicalonly. Prospective review requires genuinelyunseen source and frozenmodel; localdata presently cannot supply it.',
        preservation='Originalstrategies,reports,andthe existing Sep26 04:30UTC MNQ prospectivefreeze remain unchanged. No brokerorders or productionpromotion.',
        outputs='Sharded fulltradeledgers,daily marked equity,exact5m drawdown/chronologicalprefixmetrics,allattempts,failures/zerotrades,complete configurationmatrix,deterministic selections,stresses,source/datahashes,independentaudit and finalreport.',
        limitations='No new local data beyondSep3; goldAug24. Priorhistoryreused. OHLC cannot establish tickorder,queue,capacity,margin orinstitutionalintent. Roll liquidation andgapcancellationidealized. Fullhistorical completion doesnotmean entire future/livevalidity.')
    save(out/'protocol.json',p)
    print(f'Declared {len(configs)} configurations per market; {p["expected_market_cases"]} market cases.',flush=True)
    return p

def load_market(d):
    lo=pd.Timestamp(d['start'],tz='UTC')-pd.Timedelta(days=30)
    hi=pd.Timestamp(d['end'],tz='UTC')
    frames=[]
    for item in d['files']:
        assert checksum(item['path'])==item['checksum'],'Source changed: '+item['path']
        f=pd.read_parquet(item['path'])
        f.index=pd.to_datetime(f.index,utc=True)
        frames.append(f.loc[(f.index>=lo)&(f.index<hi)].copy())
    f=pd.concat(frames).sort_index()
    assert len(f) and f.index.is_unique
    return f

def preview(out,p):
    configs=read(out/'configurations.json')
    assert checksum(out/'configurations.json')==p['configurations_checksum']
    assert len(configs)==p['expected_configurations'] and len(configs)*len(p['datasets'])==p['expected_market_cases']
    rows=[]
    for d in p['datasets']:
        f=load_market(d)
        a=f[['open','high','low','close']].to_numpy(float)
        assert np.isfinite(a).all() and not(a[:,1]<a.max(axis=1)).any() and not(a[:,2]>a.min(axis=1)).any()
        assert 'volume' in f and np.isfinite(f.volume).all() and (f.volume>=0).all()
        assert f.index[0]<=pd.Timestamp(d['start'],tz='UTC')-pd.Timedelta(days=30)
        rows.append(dict(symbol=d['symbol'],rows=len(f),first=str(f.index[0]),last=str(f.index[-1])))
    save(out/'preview.json',dict(status='passed',checked_at=now(),protocol_checksum=checksum(out/'protocol.json'),datasets=rows,expected_cases=p['expected_market_cases'],free_disk_bytes=shutil.disk_usage(out).free))
    print(json.dumps(rows),flush=True)

def freeze(out):
    if (out/'source-manifest.json').exists(): return verify_source(out)
    preflight=read(out/'preflight.json')
    assert preflight['status']=='passed','Pass engine/control preflight before freezing'
    assert preflight['protocol_checksum']==checksum(out/'protocol.json')
    assert {m['symbol'] for m in preflight['markets']}=={'MNQ','MGC','ES','CL'}
    for path,digest in preflight['source_files'].items():
        assert checksum(ROOT/path)==digest,'Source changed after preflight: '+path
    for item in preflight['markets']:
        assert item['status']=='passed' and checksum(out/item['artifact'])==item['artifact_checksum']
    risk_check=read(out/'risk-reference-parity.json')
    assert risk_check['status']=='passed' and risk_check['passed_cases']==risk_check['expected_cases']==8
    assert risk_check['protocol_checksum']==checksum(out/'protocol.json')
    for path,digest in risk_check['source_files'].items():
        assert checksum(ROOT/path)==digest,'Risk source changed after parity: '+path
    grid_check=read(out/'synthetic-grid-parity.json')
    assert grid_check['status']=='passed' and grid_check['complete_grid']
    assert grid_check['declared_configurations']==read(out/'protocol.json')['expected_configurations']
    assert grid_check['passed_comparisons']==grid_check['expected_comparisons']
    assert grid_check['protocol_checksum']==checksum(out/'protocol.json')
    assert grid_check['configurations_checksum']==checksum(out/'configurations.json')
    for path,digest in grid_check['source_files'].items():
        assert checksum(ROOT/path)==digest,'Grid parity source changed: '+path
    paths=['scripts/research-snd-combinations.py','scripts/analyze-snd-combinations.py',
        'scripts/check-snd-combinations.py','scripts/validate-snd-combinations.py',
        'scripts/check-snd-combination-grid.py',
        'scripts/check-snd-combination-risk.py',
        'scripts/summarize-snd-combination-factors.py',
        'scripts/audit-snd-combination-validation.py',
        'scripts/audit-snd-combinations.py','strategies/_snd_combination_reference.py',
        'strategies/_snd_combination_fast.py','strategies/_snd_combination_fast_io.py',
        'strategies/_snd_combination_risk.py','strategies/_snd_risk_research.py','strategies/_snd_zone_quality.py',
        'strategies/_snd_entry_research.py','strategies/_snd_body_retest.py','strategies/_snd_fresh_retest.py',
        'tests/test_snd_combination_reference.py','tests/test_snd_combination_fast.py','tests/test_snd_combination_fast_io.py',
        'tests/test_snd_combinations_analysis.py','tests/test_snd_combinations_audit.py',
        'tests/test_snd_combinations_runner.py','tests/test_snd_combination_risk.py',
        'tests/test_snd_combination_grid.py',
        'tests/test_snd_combination_validation_audit.py',
        'tests/test_snd_zone_quality.py','tests/test_snd_entry_research.py']
    paths += [str(x.relative_to(ROOT)).replace('\\','/') for x in (ROOT/'strategy_engine').glob('*.py')]
    missing=[x for x in paths if not (ROOT/x).is_file()]
    if missing: raise FileNotFoundError('Finish source before freeze: '+', '.join(missing))
    files=[]
    for name in paths:
        dst=out/'source'/name
        dst.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(ROOT/name,dst)
        files.append(dict(path=name,checksum=checksum(dst)))
    identity=hashlib.sha256(json.dumps(files,sort_keys=True).encode()).hexdigest()
    import numba, llvmlite, scipy, pyarrow
    save(out/'environment.json',dict(python=sys.version,platform=platform.platform(),numpy=np.__version__,
        pandas=pd.__version__,numba=numba.__version__,llvmlite=llvmlite.__version__,scipy=scipy.__version__,pyarrow=pyarrow.__version__))
    save(out/'source-manifest.json',dict(frozen_at=now(),protocol_checksum=checksum(out/'protocol.json'),
        configurations_checksum=checksum(out/'configurations.json'),source_hash=identity,files=files,
        environment_checksum=checksum(out/'environment.json')))
    return verify_source(out)

def verify_source(out):
    m=read(out/'source-manifest.json')
    assert checksum(out/'protocol.json')==m['protocol_checksum'],'Protocol changed'
    assert checksum(out/'configurations.json')==m['configurations_checksum'],'Configuration grid changed'
    assert checksum(out/'environment.json')==m['environment_checksum'],'Environment record changed'
    assert hashlib.sha256(json.dumps(m['files'],sort_keys=True).encode()).hexdigest()==m['source_hash']
    for f in m['files']:
        assert checksum(out/'source'/f['path'])==f['checksum'],'Source snapshot changed: '+f['path']
    verify_executing_file(m,'scripts/research-snd-combinations.py',__file__)
    return m


def verify_executing_file(manifest,relative_path,executing_path):
    expected=next(f['checksum'] for f in manifest['files'] if f['path']==relative_path)
    assert checksum(executing_path)==expected,'Executing source differs from frozen source: '+relative_path

def daily_equity(e,capital):
    """Last close mark per UTC day, with reconciled daily changes."""
    if not len(e): return e.copy()
    # The midnight close belongs to the candle/day that just ended.
    stamps=pd.to_datetime(e.timestamp,utc=True)
    keys=(stamps-pd.Timedelta(nanoseconds=1)).dt.floor('D')
    result=e.loc[~keys.duplicated(keep='last')].copy().reset_index(drop=True)
    result['net_pnl']=np.diff(np.r_[capital,result.equity.to_numpy(float)])
    return result

def closed_mask(t,lo,hi):
    x=pd.to_datetime(t.exit_time,utc=True)
    close=t.exit_reason.isin(['contract-roll','end-of-test'])
    return ((~close)&(x>=lo)&(x<hi)) | (close&(x>lo)&(x<=hi))

def basic_trade_metrics(t):
    n=len(t)
    wins=float(t.loc[t.net_pnl>0,'net_pnl'].sum())
    losses=float(-t.loc[t.net_pnl<0,'net_pnl'].sum())
    holding=(pd.to_datetime(t.exit_time,utc=True)-pd.to_datetime(t.entry_time,utc=True)).dt.total_seconds()/3600 if n else pd.Series(dtype=float)
    return dict(trades=n,closed_net=float(t.net_pnl.sum()),gross_pnl=float(t.gross_pnl.sum()),cost=float(t.cost.sum()),
        double_cost_closed_net=float((t.net_pnl-t.cost).sum()),mean_net_r=float(t.net_r.mean()) if n else None,
        mean_double_cost_r=float(((t.net_pnl-t.cost)/t.risk_cash).mean()) if n else None,
        profit_factor=wins/losses if losses else None,win_rate=float((t.net_pnl>0).mean()) if n else None,
        median_risk_cash=float(t.risk_cash.median()) if n else None,
        median_holding_hours=float(holding.median()) if n else None,max_holding_hours=float(holding.max()) if n else None,
        net_without_top5=float(t.net_pnl.sum()-t.loc[t.net_pnl>0,'net_pnl'].nlargest(5).sum()) if n else 0.)

PERIODS={'all':['2022-01-01','2026-08-01'],'early_2022_23':['2022-01-01','2024-01-01'],
         'year_2024':['2024-01-01','2025-01-01'],'year_2025':['2025-01-01','2026-01-01'],
         'year_2026':['2026-01-01','2026-08-01'],'later':['2025-01-01','2026-08-01']}

def period_metrics(t,e,capital):
    stamps=pd.to_datetime(e.timestamp,utc=True)
    values=e.equity.to_numpy(float)
    rows=[]
    for name,bounds in PERIODS.items():
        lo,hi=(pd.Timestamp(v,tz='UTC') for v in bounds)
        a=int(stamps.searchsorted(lo,side='right'))
        b=int(stamps.searchsorted(hi,side='right'))
        initial=float(values[a-1]) if a else capital
        path=np.r_[initial,values[a:b]]
        c=t.loc[closed_mask(t,lo,hi)]
        rows.append(dict(period=name,**basic_trade_metrics(c),net_pnl=float(path[-1]-initial),
            max_drawdown=float((np.maximum.accumulate(path)-path).max()),min_equity=float(path.min()),
            marked_observations=b-a))
    return rows

def weekly_metrics(t,start='2022-01-01',end='2026-08-01'):
    first=pd.Timestamp(start,tz='UTC')
    first=(first-pd.Timedelta(days=first.weekday())).normalize()
    n=int(((pd.Timestamp(end,tz='UTC')-pd.Timedelta(nanoseconds=1))-first).days//7)+1
    values=np.zeros((n,5))
    if len(t):
        stamps=pd.to_datetime(t.exit_time,utc=True)-pd.to_timedelta(t.exit_reason.isin(['contract-roll','end-of-test']).astype(int),unit='ns')
        indices=((stamps-first).dt.total_seconds()//(7*86400)).astype(int).to_numpy()
        for j,v in enumerate([t.net_r.to_numpy(),t.cost.to_numpy()/t.risk_cash.to_numpy(),
                             np.ones(len(t)),t.net_pnl.to_numpy(),t.cost.to_numpy()]):
            np.add.at(values[:,j],indices,v)
    result=pd.DataFrame(values,columns=['net_r_sum','cost_r_sum','trades','net_pnl','cost'])
    result['week']=pd.date_range(first,periods=n,freq='7D')
    return result


def process_alive(pid):
    """Read process state without sending a Windows signal."""
    if not pid: return False
    if os.name=='nt':
        import ctypes
        from ctypes import wintypes
        kernel=ctypes.windll.kernel32
        kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
        kernel.OpenProcess.restype=wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes=[wintypes.HANDLE,ctypes.POINTER(wintypes.DWORD)]
        kernel.CloseHandle.argtypes=[wintypes.HANDLE]
        handle=kernel.OpenProcess(0x1000,False,int(pid))
        if not handle: return False
        try:
            value=ctypes.c_ulong()
            return bool(kernel.GetExitCodeProcess(handle,ctypes.byref(value))) and value.value==259
        finally: kernel.CloseHandle(handle)
    try: os.kill(int(pid),0)
    except ProcessLookupError: return False
    return True


ARTIFACTS=['cases.json','trades.parquet','equity-daily.parquet','periods.parquet','training.parquet','weekly.parquet']


def existing_attempt(folder,identity,ids,retry_failed=False):
    attempts=sorted(folder.glob('attempt-*')) if folder.exists() else []
    if not attempts: return None,folder/'attempt-000'
    latest=attempts[-1]
    if (latest/'result.json').exists():
        r=read(latest/'result.json')
        assert all(r.get(k)==v for k,v in identity.items()),'Attempt identity mismatch'
        assert r['config_ids']==ids,'Shard configuration mismatch'
        if r['status']=='succeeded':
            for item in r['artifacts']:
                assert checksum(latest/item['name'])==item['checksum'],'Artifact modified: '+str(latest/item['name'])
            assert set(x['name'] for x in r['artifacts'])==set(ARTIFACTS)
            assert read(latest/'status.json')['status']=='succeeded'
            return r,latest
        if not retry_failed: return r,latest
    else:
        status=read(latest/'status.json') if (latest/'status.json').exists() else {}
        if process_alive(status.get('pid')):
            raise RuntimeError('Attempt still running; do not duplicate: '+str(latest))
        if not retry_failed:
            raise RuntimeError('Interrupted attempt preserved; resume with --retry-failed: '+str(latest))
    return None,folder/f'attempt-{int(latest.name.split("-")[-1])+1:03d}'


def case_tables(config,dataset,prepared,source,model,analysis,protocol):
    p=config['parameters']
    fee=1.25 if dataset['symbol'] in ('MNQ','MGC') else 2.50
    result=model.run_model(prepared,p,dataset['start'],dataset['end'],dataset['tick_size'],dataset['point_value'],fee,1)
    t,e=result['trades'],result['equity']
    capital=protocol['capital']
    np.testing.assert_allclose(e.equity.iloc[-1]-capital,t.net_pnl.sum(),atol=1e-5,rtol=0)
    np.testing.assert_allclose(e.net_pnl.sum(),t.net_pnl.sum(),atol=1e-5,rtol=0)
    np.testing.assert_allclose(t.gross_pnl.to_numpy(float)-t.cost.to_numpy(float),
                               t.net_pnl.to_numpy(float),atol=1e-7,rtol=0)
    assert e.contracts.iloc[-1]==0
    periods=pd.DataFrame(period_metrics(t,e,capital))
    daily=daily_equity(e,capital)
    training=[]
    for fold in protocol['folds']:
        cutoff=pd.Timestamp(fold['cutoff'],tz='UTC')
        position=int(source.index.searchsorted(cutoff-pd.Timedelta(minutes=1),side='right'))-1
        assert position>=0
        last=source.iloc[position]
        censored=analysis.causal_training_trades(t,fold['training_start'],fold['cutoff'],
            last_source_open=last.name,last_source_close=float(last.close),point_value=dataset['point_value'],
            tick_size=dataset['tick_size'],fee=fee,slippage_ticks=1)
        training.append(dict(fold_id=fold['id'],enabled_filters=sum(p[k] is not None for k in list(GRID)[:4]),
            **analysis.training_metrics(censored,fold['training_start'],fold['cutoff'])))
    weekly=[]
    for period in ['all','later']:
        lo,hi=(pd.Timestamp(v,tz='UTC') for v in PERIODS[period])
        w=weekly_metrics(t.loc[closed_mask(t,lo,hi)])
        w['period']=period
        weekly.append(w)
    tables={'trades.parquet':t,'equity-daily.parquet':daily,'periods.parquet':periods,
            'training.parquet':pd.DataFrame(training),'weekly.parquet':pd.concat(weekly,ignore_index=True)}
    for table in tables.values(): table['config_id']=config['config_id']
    return tables,dict(diagnostics=result['diagnostics'],summary=periods.loc[periods.period=='all'].iloc[0].to_dict())


def shard_partition(count,shard_size,max_shards=None,offset=0,stride=1):
    """Disjoint worker ownership without changing retained shard identities."""
    assert shard_size>0 and stride>0 and 0<=offset<stride
    total=(count+shard_size-1)//shard_size
    if max_shards is not None:
        assert max_shards>0
        total=min(total,max_shards)
    return [(shard,shard*shard_size) for shard in range(offset,total,stride)]


def run_market(out_name,d,shard_size=64,max_shards=None,retry_failed=False,offset=0,stride=1):
    out=Path(out_name)
    protocol,manifest=read(out/'protocol.json'),verify_source(out)
    identity={k:manifest[k] for k in ['protocol_checksum','source_hash','configurations_checksum']}
    sys.path.insert(0,str(out/'source'))
    model=load_module('frozen_combination_fast',out/'source/strategies/_snd_combination_fast.py')
    analysis=load_module('frozen_combination_analysis',out/'source/scripts/analyze-snd-combinations.py')
    configs=read(out/'configurations.json')
    source=prepared=None
    reports=[]
    for shard,index in shard_partition(len(configs),shard_size,max_shards,offset,stride):
        group=configs[index:index+shard_size]
        ids=[c['config_id'] for c in group]
        folder=out/'sweep'/d['symbol']/f'shard-{shard:04d}'
        completed,attempt=existing_attempt(folder,identity,ids,retry_failed)
        if completed:
            reports.append(dict(shard=shard,status=completed['status'],resumed=True))
            continue
        if shutil.disk_usage(out).free<5*1024**3:
            raise RuntimeError('Less than5GiB free; stop before creating new shard')
        if source is None:
            source=load_market(d)
            prepared=model.prepare_data(source,pivot_len=2,execution_minutes=1)
        attempt.mkdir(parents=True,exist_ok=False)
        started=now()
        save(attempt/'input.json',dict(symbol=d['symbol'],dataset=d,**identity,config_ids=ids,
            start_index=index,stop_index=index+len(group),shard_size=shard_size))
        save(attempt/'status.json',dict(status='running',started_at=started,pid=os.getpid(),completed_cases=0))
        cases=[]
        accumulators={name:[] for name in ARTIFACTS if name.endswith('.parquet')}
        for config in group:
            clock=time.monotonic()
            try:
                tables,summary=case_tables(config,d,prepared,source,model,analysis,protocol)
                for name,table in tables.items(): accumulators[name].append(table)
                row=dict(config_id=config['config_id'],status='succeeded',elapsed_seconds=time.monotonic()-clock,**summary)
            except Exception as error:
                (attempt/(config['config_id']+'-error.log')).write_text(traceback.format_exc(),encoding='utf-8')
                row=dict(config_id=config['config_id'],status='failed',error=str(error),elapsed_seconds=time.monotonic()-clock)
            cases.append(row)
            save(attempt/'status.json',dict(status='running',started_at=started,pid=os.getpid(),
                 completed_cases=len(cases),last_config=config['config_id']))
        save(attempt/'cases.json',cases)
        for name,frames in accumulators.items():
            nonempty=[frame for frame in frames if len(frame)]
            table=(pd.concat(nonempty,ignore_index=True) if nonempty else
                   frames[0].copy() if frames else pd.DataFrame({'config_id':pd.Series(dtype=str)}))
            table.to_parquet(attempt/name,index=False,compression='zstd')
        status='succeeded' if all(c['status']=='succeeded' for c in cases) else 'failed'
        result=dict(status=status,symbol=d['symbol'],config_ids=ids,**identity,started_at=started,completed_at=now(),
            artifacts=[dict(name=name,checksum=checksum(attempt/name)) for name in ARTIFACTS])
        save(attempt/'result.json',result)
        save(attempt/'status.json',dict(status=status,started_at=started,completed_at=now(),completed_cases=len(cases),pid=os.getpid()))
        reports.append(dict(shard=shard,status=status,resumed=False))
        print(f'{d["symbol"]} shard{shard:04d}: {status}; {index+len(group)}/{len(configs)} configs; '+
              f'{sum(c["elapsed_seconds"] for c in cases):.1f}s',flush=True)
        if status!='succeeded':
            raise RuntimeError('Shard failure preserved; inspect before continuing: '+str(attempt))
    return dict(symbol=d['symbol'],shards=reports,requested_cases=min(len(configs),(max_shards or 10**9)*shard_size))


def sweep(out,protocol,workers=4,shard_size=64,max_shards=None,retry_failed=False,markets=None):
    manifest=verify_source(out)
    check=read(out/'preview.json')
    assert check['status']=='passed' and check['protocol_checksum']==manifest['protocol_checksum']
    preflight=read(out/'preflight.json')
    frozen_hashes={f['path']:f['checksum'] for f in manifest['files']}
    assert preflight['status']=='passed' and all(frozen_hashes[k]==v for k,v in preflight['source_files'].items())
    datasets=[d for d in protocol['datasets'] if markets is None or d['symbol'] in markets]
    summaries=[]
    partitions=max(1,workers//len(datasets))
    with ProcessPoolExecutor(max_workers=workers) as pool:
        jobs=[pool.submit(run_market,str(out),d,shard_size,max_shards,retry_failed,offset,partitions)
              for d in datasets for offset in range(partitions)]
        for job in as_completed(jobs): summaries.append(job.result())
    merged=[]
    for d in datasets:
        parts=[r for r in summaries if r['symbol']==d['symbol']]
        shards=sorted([shard for part in parts for shard in part['shards']],key=lambda r:r['shard'])
        expected=[shard for shard,_ in shard_partition(protocol['expected_configurations'],shard_size,max_shards)]
        assert [r['shard'] for r in shards]==expected,'Duplicate or missing worker shard'
        assert len({r['requested_cases'] for r in parts})==1
        merged.append(dict(symbol=d['symbol'],shards=shards,requested_cases=parts[0]['requested_cases']))
    summaries=merged
    verify_source(out)
    complete=len(datasets)==4 and all(s['requested_cases']==protocol['expected_configurations'] and
        all(r['status']=='succeeded' for r in s['shards']) for s in summaries)
    filename='completion.json' if complete else 'partial-completion.json'
    save(out/filename,dict(status='complete' if complete else 'partial',completed_at=now(),markets=summaries,
        protocol_checksum=manifest['protocol_checksum'],source_hash=manifest['source_hash']))
    print('All declared core cases completed.' if complete else 'Requested partial sweep completed.',flush=True)

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output',type=Path,default=OUT)
    for name in ['declare','preview','freeze','run','retry-failed']:
        ap.add_argument('--'+name,action='store_true')
    ap.add_argument('--workers',type=int,choices=range(1,9),default=4)
    ap.add_argument('--shard-size',type=int,default=64)
    ap.add_argument('--max-shards',type=int)
    ap.add_argument('--markets',nargs='+',choices=['MNQ','MGC','ES','CL'])
    args=ap.parse_args()
    if args.shard_size<1 or args.max_shards is not None and args.max_shards<1:
        ap.error('Shard size and optional max-shards must be positive')
    out=args.output.resolve()
    p=declare(out) if args.declare else read(out/'protocol.json')
    if args.preview: preview(out,p)
    if args.freeze: freeze(out)
    if args.run: sweep(out,p,args.workers,args.shard_size,args.max_shards,args.retry_failed,args.markets)

if __name__=='__main__': main()
