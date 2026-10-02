"""Build a read-only portfolio catalog from checksum-verified research ledgers.

No strategy is rerun or promoted here. Baseline configurations are deduplicated;
cost and execution stress runs are evidence, never additional portfolio sleeves.
"""
from __future__ import annotations
import argparse,hashlib,json,os,sys,sqlite3,tempfile
from contextlib import closing,contextmanager
from pathlib import Path
from uuid import UUID
import time
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))

from workbench.evidence import EvidenceCampaign,EvidenceRegistry,EvidenceRegistryError
from workbench.dataset_reference import resolve_dataset_path
from workbench.layout import load_layout

def state_root():
    configured=os.environ.get('WORKBENCH_HOME')
    return Path(configured).expanduser().resolve() if configured else load_layout(ROOT).state_root

OUT=state_root()/'collective'
COLLECTIVE_CAMPAIGNS=(
    'all-strategies-all-charts-2026-09-16',
    'expanded-search-2026-09-16',
    'snd-fresh-backtest-2026-09-16',
    'combined-es-nq-refresh-2026-09-29',
)
_EVIDENCE_CAMPAIGNS:dict[str,EvidenceCampaign]|None=None
# Retain the old module-level campaign constants as an explicit test-injection
# seam for one compatibility release. Normal CLI execution leaves them unset
# and must pass the tracked registry checks below.
FIRST:Path|None=None
EXPANDED:Path|None=None
SND:Path|None=None
REFRESH:Path|None=None

def _compat_campaign(campaign_id,path):
    root=Path(path)
    return EvidenceCampaign(campaign_id,1,root,root/'PLAN.json',root/'REPORT.md',('collective-catalog',),())

def _using_compat_overrides():
    return any(path is not None for path in (FIRST,EXPANDED,SND,REFRESH))

def configure_evidence():
    """Resolve and verify all evidence required for a complete catalog build."""
    global _EVIDENCE_CAMPAIGNS
    if _using_compat_overrides():
        if any(path is None for path in (FIRST,EXPANDED,SND)):
            raise EvidenceRegistryError('FIRST, EXPANDED and SND overrides must be provided together')
        refresh=REFRESH if REFRESH is not None else ROOT/'__missing-test-refresh__'
        return {
            COLLECTIVE_CAMPAIGNS[0]:_compat_campaign(COLLECTIVE_CAMPAIGNS[0],FIRST),
            COLLECTIVE_CAMPAIGNS[1]:_compat_campaign(COLLECTIVE_CAMPAIGNS[1],EXPANDED),
            COLLECTIVE_CAMPAIGNS[2]:_compat_campaign(COLLECTIVE_CAMPAIGNS[2],SND),
            COLLECTIVE_CAMPAIGNS[3]:_compat_campaign(COLLECTIVE_CAMPAIGNS[3],refresh),
        }
    if _EVIDENCE_CAMPAIGNS is None:
        registry=EvidenceRegistry(ROOT)
        loaded={}
        for campaign_id in COLLECTIVE_CAMPAIGNS:
            loaded[campaign_id]=registry.campaign(campaign_id,consumer='collective-catalog')
        _EVIDENCE_CAMPAIGNS=loaded
    return _EVIDENCE_CAMPAIGNS

def evidence_campaign(campaign_id):
    return configure_evidence()[campaign_id]

REFRESH_IDS={
    '72475d93c4667b888c79',  # ES Pine overnight block
    'f24587940b6c8c81c877',  # ES Globex overnight
    '0c4b6e885c9223b5373f',  # NQ Pine TSMOM ORB
    '3b3d1cfec7aac292801c',  # NQ Globex overnight
    '35b4fda895bf8ed0435c',  # NQ minute reversal
}
def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def pinned_run_ids():
    """Read exact baseline runs requested for a durable portfolio import."""
    path=OUT/'pinned-runs.json'
    if not path.exists():return [],[]
    try:values=read(path)
    except (OSError,ValueError) as ex:return [],[{'key':'pinned-runs','error':f'Cannot read pinned runs: {ex}'}]
    if not isinstance(values,list):
        return [],[{'key':'pinned-runs','error':'Pinned runs must be a JSON array of run IDs.'}]
    ids=[];errors=[];seen=set()
    for index,value in enumerate(values):
        key=f'pinned-runs[{index}]'
        if not isinstance(value,str):
            errors.append({'key':key,'error':'Run ID must be a canonical UUID string.'});continue
        try:canonical=str(UUID(value))
        except ValueError:canonical=''
        if canonical!=value:
            errors.append({'key':key,'error':'Run ID must be a canonical UUID string.'});continue
        if value in seen:
            errors.append({'key':key,'error':f'Duplicate pinned run ID: {value}'});continue
        seen.add(value);ids.append(value)
    return ids,errors
def baseline_run(record):
    inp=record['input'];research=inp.get('research')
    # Tracking replays are a derived portfolio history, never another
    # development baseline or an evaluation fold.
    if inp.get('portfolio_replay') or record.get('portfolio_replay'):return False
    if research:return research.get('role')=='Test' and research.get('scenario')=='Baseline'
    tags=(record.get('tags') or '').lower()
    return not inp.get('delay_bars',0) and not any(word in tags for word in ('stress','sensitivity','benchmark'))
def decode_sqlite_record(kind,record_id,raw):
    """Read protocol-v1 rows and validate protocol-v2 record envelopes."""
    value=json.loads(raw)
    if (isinstance(value,dict) and value.get('schema_version')==2
            and ('kind' in value or 'body' in value)):
        if (set(value)!={'schema_version','kind','id','body'}
                or not isinstance(value.get('kind'),str)
                or value.get('kind')!=kind
                or not isinstance(value.get('id'),str)
                or value.get('id')!=record_id
                or not isinstance(value.get('body'),dict)):
            raise ValueError(f'Invalid protocol-v2 SQLite envelope for {kind}/{record_id}')
        return value['body']
    if not isinstance(value,dict):
        raise ValueError(f'Invalid protocol-v1 SQLite record for {kind}/{record_id}')
    return value
def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()
def dataset_file(record):
    return resolve_dataset_path(record,state_root())
def dump(p,obj):
    write_bytes_atomic(Path(p),json.dumps(obj,allow_nan=False,separators=(',',':')).encode('utf-8'))
def write_bytes_atomic(path,payload):
    """Publish a complete file from the same directory as its destination."""
    temp=None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent,prefix=path.name+'.',suffix='.tmp',delete=False) as handle:
            temp=Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        temp.replace(path)
    finally:
        if temp:temp.unlink(missing_ok=True)

@contextmanager
def catalog_lock():
    """Serialize catalog publication with concurrent background replays."""
    OUT.mkdir(parents=True,exist_ok=True)
    with (OUT/'.publish.lock').open('a+b') as handle:
        if handle.tell()==0:
            handle.write(b'0')
            handle.flush()
        until=time.monotonic()+30
        while True:
            try:
                if os.name=='nt':
                    import msvcrt
                    handle.seek(0);msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic()>=until:raise TimeoutError('Timed out waiting for portfolio catalog publication')
                time.sleep(.1)
        try:yield
        finally:
            if os.name=='nt':
                handle.seek(0);msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
            else:fcntl.flock(handle.fileno(),fcntl.LOCK_UN)

def apply_verified_overlays(items,prior_items,errors):
    """Reapply immutable verified histories after the frozen evidence refresh."""
    pointer=OUT/'verified-replays.json'
    if not pointer.exists():return items
    overlays=read(pointer)
    if not isinstance(overlays,dict):raise ValueError('Verified replay overlay must be an object')
    by_id={item['id']:item for item in items}
    previous={item['id']:item for item in prior_items}
    for identity,overlay in overlays.items():
        if not isinstance(overlay,dict) or not isinstance(overlay.get('item'),dict):
            errors.append({'key':f'replay:{identity}','error':'Invalid verified replay overlay'})
            continue
        saved=overlay['item'];base=by_id.get(identity)
        try:
            if saved['id']!=identity or not saved.get('verified_replay'):
                raise ValueError('Replay identity or provenance is missing')
            path=OUT/saved['series_file']
            if not path.is_file() or sha(path)!=saved['checksum']:
                raise ValueError('Verified replay series checksum changed')
            provenance=saved['verified_replay']
            if provenance.get('end')!=saved['end'] or not provenance.get('dataset_checksum'):
                raise ValueError('Verified replay provenance differs from the catalog')
            source_run=provenance.get('source_run_id')
            if source_run:
                manifest=state_root()/'runs'/source_run/'manifest.json'
                if not manifest.is_file() or sha(manifest)!=provenance.get('artifact_sha256'):
                    raise ValueError('Verified replay run manifest checksum changed')
            elif provenance.get('artifact_sha256')!=saved['checksum']:
                raise ValueError('Verified overnight series provenance differs')
            if base is None or base['checksum']!=overlay.get('base_checksum'):
                raise ValueError('Frozen catalog source changed; replay needs verification again')
            by_id[identity]=saved
        except (KeyError,ValueError) as ex:
            errors.append({'key':f'replay:{identity}','error':str(ex)})
            old=previous.get(identity)
            if old and old.get('verified_replay') and (OUT/old['series_file']).is_file() and sha(OUT/old['series_file'])==old['checksum']:
                by_id[identity]=old
    return list(by_id.values())
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
    rows=[{'entry':x.isoformat(),'exit':y.isoformat(),'pnl':round(float(v),8)} for x,y,v in zip(a,z,t[pnl])]
    reason_column=next((c for c in ('exit_reason','reason') if c in t.columns),None)
    if reason_column:
        for row,value in zip(rows,t[reason_column]):
            if pd.isna(value) or not str(value).strip():continue
            reason=str(value).strip()
            row['exit_reason']=reason
            row['synthetic_exit']=reason.lower().replace('_','-').replace(' ','-') in ('end-of-test','end-of-data','end-of-backtest','final-liquidation')
            row['exit_provenance']='recorded'
    # Keep actual source quantities; never infer one contract from a strategy name.
    for column in ('quantity','cost'):
        if column not in t.columns:continue
        for row,value in zip(rows,t[column]):
            if not np.isfinite(value):continue
            value=abs(float(value)) if column=='quantity' else float(value)
            if column=='quantity' and (value<=0 or not value.is_integer()):continue
            if column=='cost' and value<0:continue
            row[column]=value
    return rows
def daily(equity,capital=100000):
    equity=equity.sort_index()
    assert equity.index.is_unique and np.isfinite(equity).all()
    e=equity.groupby(equity.index.floor('D')).last()
    p=e.diff();p.iloc[0]=e.iloc[0]-capital
    return {d.strftime('%Y-%m-%d'):round(float(v),8) for d,v in p.items()}

def daily_risk(marks,capital):
    """Full daily-close drawdown from an independent book's starting capital."""
    if not np.isfinite(capital) or capital<=0 or not marks:
        raise ValueError('Saved history has no valid capital or daily marks.')
    equity=peak=float(capital)
    drawdown_dollars=0.0
    drawdown=0.0
    for _,pnl in sorted(marks.items()):
        if not np.isfinite(pnl):raise ValueError('Saved history has invalid daily P&L.')
        equity+=float(pnl)
        peak=max(peak,equity)
        drawdown_dollars=max(drawdown_dollars,peak-equity)
        drawdown=min(drawdown,equity/peak-1)
    return {'max_drawdown_dollars':round(drawdown_dollars,6),
            'max_drawdown':round(drawdown,12)}

def canonical_run(run_id):
    f=state_root()/'runs'/run_id
    manifest=verified(f,['trades.csv','equity.csv']);inp=read(f/'input.json')
    t=pd.read_csv(f/'trades.csv');e=pd.read_csv(f/'equity.csv')
    assert abs(t.net_pnl.sum()-manifest['metrics']['net_pnl'])<.01
    assert abs(e.equity.iloc[-1]-inp['capital']-t.net_pnl.sum())<.01
    marks=daily(pd.Series(e.equity.to_numpy(),index=pd.to_datetime(e.timestamp,utc=True)),inp['capital'])
    normalized=normalize(t)
    # Legacy signal workers lacked reasons. Their documented final-close
    # liquidation is identifiable from the last equity timestamp. Never
    # rewrite the original ledger; retain the inference in derived metadata.
    if 'exit_reason' not in t.columns and 'reason' not in t.columns:
        final=pd.to_datetime(e.timestamp.iloc[-1],utc=True)
        for row in normalized:
            terminal=pd.Timestamp(row['exit'])==final
            row.update(exit_reason='end-of-test' if terminal else 'signal',synthetic_exit=terminal,exit_provenance='legacy-worker-timing')
    for row in normalized:row.update(source_run=run_id,source_version=inp.get('source_hash','unknown'))
    return normalized,marks,inp

def prepare_pinned_run(run_id,record,exact_variant=False):
    """Build one history in memory after checking the run and its saved ledger."""
    if record['status']!='Succeeded':raise ValueError('Pinned run did not succeed.')
    if not baseline_run(record):raise ValueError('Pinned run is not a baseline test.')
    trades,marks,inp=canonical_run(run_id)
    recorded=record['input']
    for field in ('start','end','timeframe','session','parameters','capital','fee','slippage','source_hash'):
        if inp.get(field)!=recorded.get(field):
            raise ValueError(f'Pinned run input differs from its ledger: {field}')
    if inp['strategy']['id']!=recorded['strategy']['id'] or inp['dataset']['symbol']!=recorded['dataset']['symbol']:
        raise ValueError('Pinned run strategy or market differs from its ledger.')
    start,end=inp['start'],inp['end']
    included={date:value for date,value in marks.items() if start<=date<=end}
    if not included:raise ValueError('Pinned run has no scored daily history.')
    key=f"{inp['strategy']['id']}__{inp['dataset']['symbol']}__{inp['timeframe']}__pinned__{run_id}"
    if exact_variant:key+='__exact'
    identity=hashlib.sha256(('Pinned workbench|'+key).encode()).hexdigest()[:20]
    segment=f'{start}/{end}'
    last=max(included)
    series={'id':identity,'provenance_version':2,
            'daily':[{'date':date,'pnl':pnl,'segment':segment,'terminal':date==last}
                     for date,pnl in sorted(included.items())],
            'trades':[dict(trade,segment=segment) for trade in sorted(trades,key=lambda trade:(trade['entry'],trade['exit']))],
            'coverage':[{'start':start,'end':end}]}
    payload=json.dumps(series,allow_nan=False,separators=(',',':')).encode('utf-8')
    checksum=hashlib.sha256(payload).hexdigest()
    filename=f'{identity}-{checksum[:16]}.json'
    cumulative=0.0;curve=[0.0]
    for _,value in sorted(included.items()):
        cumulative+=value;curve.append(cumulative)
    stride=max(1,(len(curve)+47)//48)
    chart=[round(value,6) for value in curve[::stride]]
    if chart[-1]!=round(curve[-1],6):chart.append(round(curve[-1],6))
    benchmark=inp['strategy']['id']=='buy-hold'
    item={'id':identity,'key':key,'name':inp['strategy']['name'],
          'symbol':inp['dataset']['symbol'],'timeframe':inp['timeframe'],'session':inp['session'],
          'source':'Pinned workbench','start':start,'end':end,'coverage':series['coverage'],
          'capital':inp['capital'],'working':False,'feasible':False,'benchmark':benchmark,
          'tested':bool(end>='2026-08-31'),
          'reasons':['Pinned historical baseline; importing it does not establish validation or practical readiness.'],
          'parameters':inp['parameters'],'net_pnl':round(sum(included.values()),6),
          **daily_risk(included,inp['capital']),
          'recent_pnl':round(sum(value for date,value in included.items() if date>='2024-01-01'),6),
          'trades':len(trades),'chart_points':chart,'series_file':filename,
          'checksum':checksum,'source_run_ids':[run_id]}
    return item,payload

def exact_run_item(item,run_id,record):
    return (item.get('source_run_ids')==[run_id]
            and item.get('coverage')==[{'start':record['input']['start'],'end':record['input']['end']}]
            and not item.get('latest_replay') and not item.get('verified_replay'))

def pinned_only():
    """Append verified exact histories without rebuilding the campaign catalog."""
    index_path=OUT/'index.json'
    if not index_path.exists():raise ValueError('No existing collective catalog; run the full refresh first.')
    index=read(index_path)
    if not isinstance(index,dict) or not isinstance(index.get('items'),list):
        raise ValueError('Existing collective catalog is invalid.')
    pins,errors=pinned_run_ids()
    if errors:raise ValueError(json.dumps(errors))
    if not pins:return {'imported':0,'already_present':0,'configurations':len(index['items'])}
    database=OUT.parent/'workbench.sqlite3'
    if not database.exists():raise ValueError('Workbench run ledger is missing.')
    prepared=[];already_present=0
    identities={item['id'] for item in index['items']}
    with closing(sqlite3.connect(database.resolve().as_uri()+'?mode=ro',uri=True)) as connection:
        for run_id in pins:
            row=connection.execute('SELECT body FROM records WHERE kind=? AND id=?',('run',run_id)).fetchone()
            if not row:raise ValueError(f'Pinned run is not in the workbench run ledger: {run_id}')
            record=decode_sqlite_record('run',run_id,row[0])
            if record['status']!='Succeeded':raise ValueError(f'Pinned run did not succeed: {run_id}')
            if not baseline_run(record):raise ValueError(f'Pinned run is not a baseline test: {run_id}')
            existing=next((item for item in index['items'] if exact_run_item(item,run_id,record)),None)
            if existing:
                file=OUT/existing['series_file']
                if sha(file)!=existing['checksum']:
                    raise ValueError(f'Existing history checksum changed: {file}')
                already_present+=1
                continue
            item,payload=prepare_pinned_run(run_id,record)
            if item['id'] in identities:
                # Older pinned histories can carry different coverage or a
                # later replay. Keep their identity and add a distinct exact
                # singleton for the frozen run.
                item,payload=prepare_pinned_run(run_id,record,exact_variant=True)
            if item['id'] in identities:
                raise ValueError(f'Pinned history ID collides with an existing item: {item["id"]}')
            identities.add(item['id'])
            prepared.append((item,payload))
    if not prepared:return {'imported':0,'already_present':already_present,'configurations':len(index['items'])}
    with catalog_lock():
        # Another background replay may have published while the pinned ledger
        # was being checked. Merge into its latest catalog under the same lock.
        index=read(index_path)
        current={item['id']:item for item in index['items']}
        for item,payload in prepared:
            if item['id'] in current:
                raise ValueError(f'Pinned history ID changed during import: {item["id"]}')
            path=OUT/item['series_file']
            if path.exists():
                if sha(path)!=item['checksum']:
                    raise ValueError(f'Saved pinned history checksum changed: {path}')
            else:write_bytes_atomic(path,payload)
        index['items'].extend(item for item,_ in prepared)
        index['generated_at']=pd.Timestamp.now(tz='UTC').isoformat()
        dump(index_path,index)
        return {'imported':len(prepared),'already_present':already_present,
                'configurations':len(index['items'])}

PRICE_CACHE={}
def market_closes(symbol):
    if symbol not in PRICE_CACHE:
        first=evidence_campaign('all-strategies-all-charts-2026-09-16').root
        inv=read(first/'inventory.json');d=next(x for x in inv['datasets'] if x['symbol']==symbol)
        p=Path(d['path']);assert sha(p)==d['checksum']
        bars=pd.read_parquet(p,columns=['close']);idx=pd.to_datetime(bars.index,utc=True)+pd.Timedelta(minutes=1)
        PRICE_CACHE[symbol]=pd.Series(bars.close.to_numpy(),index=idx).groupby(idx.floor('D')).last()
    return PRICE_CACHE[symbol]
def expanded_run(r):
    expanded=evidence_campaign('expanded-search-2026-09-16').root
    f=expanded/'runs'/r['run'];verified(f,['trades.csv','equity.csv','result.json']);t=pd.read_csv(f/'trades.csv')
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


def refresh_extensions():
    """Load the five completed replays together, never a partial portfolio refresh."""
    folder=evidence_campaign('combined-es-nq-refresh-2026-09-29').root
    if _using_compat_overrides() and not folder.exists():return {}
    files=sorted(folder.rglob('extension.json'))
    if not files:raise ValueError(f'ES/NQ portfolio refresh contains no extensions: {folder}')
    found={}
    for path in files:
        extension=read(path);identity=extension['catalog_id']
        if identity in found:raise ValueError(f'Duplicate portfolio extension: {identity}')
        if identity not in REFRESH_IDS:raise ValueError(f'Unexpected portfolio extension: {identity}')
        extension['_file']=str(path)
        found[identity]=extension
    if set(found)!=REFRESH_IDS:
        raise ValueError(f'Incomplete ES/NQ portfolio refresh: missing {sorted(REFRESH_IDS-set(found))}')
    datasets=read(state_root()/'datasets/catalog.json')['datasets']
    by_id={dataset['id']:dataset for dataset in datasets}
    checked=set()
    for identity,extension in found.items():
        dataset=by_id[extension['dataset_id']]
        if dataset['checksum']!=extension['dataset_checksum']:
            raise ValueError(f'Portfolio extension dataset checksum changed: {identity}')
        if dataset['id'] not in checked:
            if sha(dataset_file(dataset))!=dataset['checksum']:
                raise ValueError(f'Portfolio extension dataset file changed: {dataset["id"]}')
            checked.add(dataset['id'])
    return found


def extend_segments(segments, extension):
    """Apply a checked tail while retaining frozen source runs and catalog IDs."""
    if not extension:return segments
    ordered=[(start,end,list(trades),dict(marks)) for start,end,trades,marks in sorted(segments)]
    start,end=extension['start'],extension['end']
    if not ordered or not start<=end or pd.Timestamp(start)-pd.Timestamp(ordered[-1][1])!=pd.Timedelta(days=1):
        raise ValueError(f'Portfolio extension does not adjoin old coverage: {extension["catalog_id"]}')
    removed_pnl=0.0
    boundary=extension.get('boundary_correction')
    if boundary:
        date=boundary['date']
        if date!=ordered[-1][1] or date not in ordered[-1][3]:
            raise ValueError('Portfolio boundary correction does not match old terminal mark')
        delta=float(boundary['delta_pnl'])
        if not np.isfinite(delta):raise ValueError('Invalid portfolio boundary correction')
        old=ordered[-1]
        original=boundary.get('original_daily_pnl',boundary.get('prior_pnl'))
        if original is not None and not np.isclose(old[3][date],original,atol=1e-6):
            raise ValueError('Old boundary mark differs from the replay provenance')
        old[3][date]+=delta
        corrected=boundary.get('corrected_daily_pnl',boundary.get('corrected_pnl'))
        if corrected is not None and not np.isclose(old[3][date],corrected,atol=1e-6):
            raise ValueError('Corrected portfolio boundary mark does not reconcile')
        remove=boundary.get('remove_trade')
        if remove:
            matching=[i for i,trade in enumerate(old[2]) if all(trade.get(k)==remove.get(k) for k in ('entry','exit','pnl','exit_reason'))]
            if len(matching)!=1 or not old[2][matching[0]].get('synthetic_exit'):
                raise ValueError('Expected one recorded synthetic boundary trade')
            removed_pnl=float(old[2].pop(matching[0])['pnl'])
    else:delta=0.0
    marks=extension['daily']
    if not marks or any(not(start<=date<=end) or not np.isfinite(value) for date,value in marks.items()):
        raise ValueError('Invalid portfolio extension daily marks')
    trades=extension['trades']
    for trade in trades:
        if not all(k in trade for k in ('entry','exit','pnl','quantity','cost','exit_reason')):
            raise ValueError('Portfolio extension trade lacks accounting fields')
        if trade['entry']>trade['exit'] or not np.isfinite([trade['pnl'],trade['quantity'],trade['cost']]).all():
            raise ValueError('Invalid portfolio extension trade')
        if trade.get('synthetic_exit'):
            raise ValueError('Fresh portfolio extension has a forced terminal exit')
    if not np.isclose(delta+sum(marks.values()),sum(t['pnl'] for t in trades)-removed_pnl,atol=.01):
        raise ValueError(f'Portfolio extension P&L does not reconcile: {extension["catalog_id"]}')
    ordered.append((start,end,trades,marks))
    return ordered

def main():
    try:
        campaigns=configure_evidence()
    except EvidenceRegistryError as ex:
        print(json.dumps({'error':'Evidence registry validation failed','detail':str(ex)},indent=2),file=sys.stderr)
        raise SystemExit(2)
    first=campaigns['all-strategies-all-charts-2026-09-16'].root
    expanded=campaigns['expanded-search-2026-09-16'].root
    snd=campaigns['snd-fresh-backtest-2026-09-16'].root
    refresh=campaigns['combined-es-nq-refresh-2026-09-29'].root
    OUT.mkdir(parents=True,exist_ok=True);items=[];errors=[];sources=[]
    prior_index=read(OUT/'index.json') if (OUT/'index.json').exists() else {}
    prior_items=prior_index.get('items',[]) if isinstance(prior_index,dict) else []
    extensions=refresh_extensions()
    if extensions:
        sources.append({'name':'ES/NQ September replay','path':str(refresh),'checksums':{identity:sha(extension['_file']) for identity,extension in extensions.items()}})
    def save(key,name,symbol,tf,session,source,segments,working=False,feasible=False,reasons=None,benchmark=False,parameters=None,capital=100000,source_run_ids=None):
        trades=[];marks={};coverage=[];mark_metadata={}
        identity=hashlib.sha256((source+'|'+key).encode()).hexdigest()[:20]
        extension=extensions.get(identity)
        segments=extend_segments(segments,extension)
        for start,end,tt,dd in sorted(segments):
            if coverage and start<=coverage[-1]['end']:raise ValueError('Overlapping source windows')
            coverage.append({'start':start,'end':end})
            segment=f'{start}/{end}'
            trades.extend([dict(t,segment=segment) for t in tt])
            terminal=max((d for d in dd if start<=d<=end),default=None)
            for date,value in dd.items():
                if start<=date<=end:
                    if date in marks:raise ValueError('Duplicate daily P&L')
                    marks[date]=value
                    mark_metadata[date]={'segment':segment,'terminal':date==terminal}
        trades.sort(key=lambda t:(t['entry'],t['exit']))
        if extension:
            # An extended source no longer ends at its earlier terminal mark.
            previous=segments[-2][1]
            if previous in mark_metadata:mark_metadata[previous]['terminal']=False
        series={'id':identity,'provenance_version':2,'daily':[{'date':d,'pnl':v,**mark_metadata[d]} for d,v in sorted(marks.items())],'trades':trades,'coverage':coverage}
        payload=json.dumps(series,allow_nan=False,separators=(',',':')).encode();checksum=hashlib.sha256(payload).hexdigest()
        filename=f'{identity}-{checksum[:16]}.json';target=OUT/filename
        if not target.exists():target.write_bytes(payload)
        recent=sum(v for d,v in marks.items() if d>='2024-01-01')
        curve=[0.0];cumulative=0.0
        for _,value in sorted(marks.items()):
            cumulative+=value;curve.append(cumulative)
        stride=max(1,(len(curve)+47)//48)
        chart_points=[round(value,6) for value in curve[::stride]]
        if chart_points[-1]!=round(curve[-1],6):chart_points.append(round(curve[-1],6))
        notes=[*(reasons or [])]
        if extension:notes.append('September 2026 extension is an exploratory replay on newer ES/NQ data; earlier evaluation status does not validate the new period.')
        items.append({'id':identity,'key':key,'name':name,'symbol':symbol,'timeframe':tf,'session':session,'source':source,'start':coverage[0]['start'],'end':coverage[-1]['end'],'coverage':coverage,'capital':capital,'working':bool(working and not benchmark),'feasible':bool(feasible and not benchmark),'benchmark':benchmark,'tested':bool(coverage[-1]['end']>='2026-08-31'),'reasons':notes,'parameters':parameters or {},'net_pnl':round(sum(marks.values()),6),**daily_risk(marks,capital),'recent_pnl':round(recent,6),'trades':len(trades),'chart_points':chart_points,'series_file':filename,'checksum':checksum,**({'latest_replay':{'start':extension['start'],'end':extension['end'],'dataset_id':extension['dataset_id'],'extension_sha256':sha(extension['_file'])}} if extension else {})})
        if source_run_ids:items[-1]['source_run_ids']=list(source_run_ids)
    if (first/'report-data.json').exists():
        report=read(first/'report-data.json');sources.append({'name':'Workbench campaign','path':str(first/'report-data.json'),'checksum':sha(first/'report-data.json')})
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
                save(key,names.get(r['strategy'],r['strategy']),r['symbol'],r['timeframe'],r['session'],'Workbench',segments,working,feasible,reasons,r['strategy']=='buy-hold',r['parameters'],source_run_ids=[q['run_id'] for q in [r]+(f['baseline_rows'] if f else [])])
            except Exception as ex:errors.append({'key':key,'error':str(ex)})
    if (expanded/'screen-results.json').exists():
        conclusions={r['key']:r for r in read(expanded/'conclusions.json')};later=read(expanded/'follow-results.json');sources.append({'name':'Expanded search','path':str(expanded/'conclusions.json'),'checksum':sha(expanded/'conclusions.json')})
        for r in read(expanded/'screen-results.json'):
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
    if (snd/'results.json').exists():
        decisions={(r['symbol'],r['variant']):r for r in read(snd/'decisions.json')};sources.append({'name':'Fresh SND','path':str(snd/'results.json'),'checksum':sha(snd/'results.json')})
        labels={'original_multi_tf':'SND original','phase6':'SND Phase 6','phase7_prior_1m':'SND prior-1m RVOL','phase7_prior_5m':'SND prior-5m RVOL'}
        for r in read(snd/'results.json'):
            if r['execution']!='next_open':continue
            try:
                f=snd/'runs'/f"{r['symbol']}__{r['variant']}__next_open";verified(f,['trades.parquet','daily-equity.csv','result.json'])
                t=pd.read_parquet(f/'trades.parquet');e=pd.read_csv(f/'daily-equity.csv',index_col=0);e.index=pd.to_datetime(e.index,utc=True)
                marks=daily(100000+e.pnl);start='2019-05-06' if r['symbol']=='MNQ' else '2018-01-01';end='2026-08-31'
                t=t[(t.exit_time>=pd.Timestamp(start,tz='UTC'))&(t.exit_time<pd.Timestamp('2026-09-01',tz='UTC'))]
                decision=decisions[(r['symbol'],r['variant'])]
                save(f"{r['symbol']}__{r['variant']}",labels[r['variant']],r['symbol'],'1h / 4h / 1d' if r['variant']=='original_multi_tf' else '1h','1m execution / all sessions','SND',[(start,end,normalize(t,'pnl'),marks)],decision['pass'],False,decision['failures']+['Next-open simulation, one contract. Pine percentage-risk sizing and TradingView parity are untested.'],parameters=r['parameters'])
            except Exception as ex:errors.append({'key':r['symbol']+'__'+r['variant'],'error':str(ex)})
    # New workbench runs also enter the catalog on refresh. Report campaigns
    # retain their richer historical review; their existing runs are not added twice.
    database=OUT.parent/'workbench.sqlite3'
    pins,pin_errors=pinned_run_ids();errors.extend(pin_errors)
    market_data_through={}
    if database.exists():
        with sqlite3.connect(database.resolve().as_uri()+'?mode=ro',uri=True) as connection:
            records=[(kind,decode_sqlite_record(kind,record_id,body)) for kind,record_id,body in connection.execute('SELECT kind,id,body FROM records')]
        connection.close()
        for kind,record in records:
            if kind=='dataset' and record.get('last'):
                symbol=record['symbol'];market_data_through[symbol]=max(market_data_through.get(symbol,''),record['last'])
        runs={r['id']:r for kind,r in records if kind=='run'}
        evaluations={r['id']:r for kind,r in records if kind=='evaluation'}
        known=set()
        if (first/'terminal-runs.json').exists():
            terminal=read(first/'terminal-runs.json')
            known={r['id'] for r in terminal} if isinstance(terminal,list) else set(terminal)
        groups={}
        for r in runs.values():
            if r['id'] in known or r['status']!='Succeeded':continue
            inp=r['input']
            if not baseline_run(r):continue
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
                save(key+'__'+hashlib.sha256(signature.encode()).hexdigest()[:10],name,inp['dataset']['symbol'],inp['timeframe'],inp['session'],'Current workbench',segments,working,False,reasons,inp['strategy']['id']=='buy-hold',inp['parameters'],capital=inp['capital'],source_run_ids=[run['id'] for run in baseline])
            except Exception as ex:errors.append({'key':key,'error':str(ex)})
        for run_id in pins:
            try:
                run=runs.get(run_id)
                if not run:raise ValueError('Pinned run is not in the workbench run ledger.')
                if run['status']!='Succeeded':raise ValueError('Pinned run did not succeed.')
                if not baseline_run(run):raise ValueError('Pinned run is not a baseline test.')
                exact_key=(f"{run['input']['strategy']['id']}__{run['input']['dataset']['symbol']}__"
                           f"{run['input']['timeframe']}__pinned__{run_id}__exact")
                keep_variant=any(item.get('key')==exact_key and exact_run_item(item,run_id,run)
                                 for item in prior_items)
                if not keep_variant and any(exact_run_item(item,run_id,run) for item in items):continue
                item,payload=prepare_pinned_run(run_id,run)
                old_collision=next((old for old in prior_items if old.get('id')==item['id']
                                    and not exact_run_item(old,run_id,run)),None)
                if old_collision and not any(current['id']==item['id'] for current in items):
                    # Preserve an older non-exact pinned choice and its ID.
                    items.append(old_collision)
                if keep_variant or any(current['id']==item['id'] for current in items):
                    item,payload=prepare_pinned_run(run_id,run,exact_variant=True)
                if any(current['id']==item['id'] for current in items):
                    raise ValueError(f'Pinned history ID collides with an existing item: {item["id"]}')
                path=OUT/item['series_file']
                if path.exists():
                    if sha(path)!=item['checksum']:raise ValueError(f'Saved pinned history checksum changed: {path}')
                else:write_bytes_atomic(path,payload)
                items.append(item)
            except Exception as ex:errors.append({'key':f'pinned:{run_id}','error':str(ex)})
    elif pins:
        errors.append({'key':'pinned-runs','error':'Workbench run ledger is missing; pinned runs cannot be imported.'})
    index={'version':1,'generated_at':pd.Timestamp.now(tz='UTC').isoformat(),'items':items,'errors':errors,'sources':sources,'definitions':{'working':'All available later-period baseline, cost and declared execution/risk checks passed. Unresolved tests remain visible.','feasible':'Working plus completed execution and parameter-sensitivity checks with no known session-exit flag. Historical research checklist only; not live approval.','pnl':'UTC calendar days, net of recorded fees and slippage. Independent strategy books; no position netting, shared margin or portfolio resizing.'}}
    index['market_data_through']=market_data_through
    if isinstance(prior_index,dict) and prior_index:
        prior=prior_index.get('condition_calibration')
        if prior and all(any(i['id']==s['id'] and i['checksum']==s['checksum'] for i in items) for s in prior.get('sources',[])):
            index['condition_calibration']=prior
    # A full manual evidence refresh regenerates the frozen baseline. Tracking
    # histories live in a separate, checksum-verified overlay and survive it.
    with catalog_lock():
        latest=read(OUT/'index.json') if (OUT/'index.json').exists() else {}
        index['items']=apply_verified_overlays(index['items'],latest.get('items',[]) if isinstance(latest,dict) else [],index['errors'])
        dump(OUT/'index.json',index)
    print(json.dumps({'configurations':len(items),'working':sum(i['working'] for i in items),'feasible':sum(i['feasible'] for i in items),'errors':errors},indent=2))
    if errors:sys.exit(1)
if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pinned-only',action='store_true',help='Import pinned runs into the existing catalog')
    args=parser.parse_args()
    if args.pinned_only:
        try:print(json.dumps(pinned_only(),indent=2))
        except Exception as ex:
            print(json.dumps({'error':'Pinned history import failed','detail':str(ex)},indent=2),file=sys.stderr)
            raise SystemExit(1)
    else:main()
