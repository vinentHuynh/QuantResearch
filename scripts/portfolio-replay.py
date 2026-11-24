"""Verify and publish background portfolio histories without changing research runs.

The workbench worker executes run-backed strategies. This script checks its
immutable artifacts against the selected history and publishes a derived series.
The two Expanded Overnight Session books use their frozen session_drift rules.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sqlite3
import sys
from contextlib import closing
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
_spec=importlib.util.spec_from_file_location('portfolio_catalog_builder',ROOT/'scripts/build-collective.py')
builder=importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(builder)

from strategy_engine.data import session_bars
from strategy_engine.sessions import SESSIONS
from strategy_engine.strategies.session_drift import SessionDriftConfig,run as drift

OVERNIGHT_IDS={'f24587940b6c8c81c877':'ES','3b3d1cfec7aac292801c':'NQ'}
OVERNIGHT_ECONOMICS={'ES':(.25,50),'NQ':(.25,20)}
LEGACY_NQ_MOMENTUM_ID='f095fc8e4b66ac71d82d'
LEGACY_NQ_MOMENTUM_RUN='0e7f5f5c-37e1-4fc4-9619-8d999ba3fcdd'
PINNED_HISTORY_REPLAYS={
    '9931ee9bcd2f35500f8f':{'strategy_id':'rsi2-reversion','timeframe':'1d',
                            'source_run_id':'169a5692-dbb4-4000-8792-fc69d70bf092'},
    'f9323ec642ba74a3de10':{'strategy_id':'multi-speed-momentum','timeframe':'1h',
                            'source_run_id':'74a20599-8397-40a9-8f04-120a5a25b9e3'},
}
SESSION=SESSIONS['globex-overnight']
ONE_MINUTE=pd.Timedelta(minutes=1)
FROZEN=ROOT/'reports/expanded-search-2026-09-16'

def read_index_item(item_id):
    index=builder.read(builder.OUT/'index.json')
    item=next((value for value in index['items'] if value['id']==item_id),None)
    if not item:raise ValueError(f'Portfolio item is missing: {item_id}')
    path=builder.OUT/item['series_file']
    if not path.is_file() or builder.sha(path)!=item['checksum']:
        raise ValueError(f'Current portfolio series checksum changed: {item_id}')
    series=builder.read(path)
    if series.get('id')!=item_id or series.get('coverage')!=item['coverage']:
        raise ValueError('Current portfolio series identity or coverage changed')
    return index,item,series

def sqlite_record(kind,record_id):
    database=builder.state_root()/'workbench.sqlite3'
    if not database.is_file():raise ValueError('Workbench record database is missing')
    with closing(sqlite3.connect(database.resolve().as_uri()+'?mode=ro',uri=True)) as connection:
        row=connection.execute('SELECT body FROM records WHERE kind=? AND id=?',(kind,record_id)).fetchone()
    if not row:raise ValueError(f'Workbench {kind} record is missing: {record_id}')
    return builder.decode_sqlite_record(kind,record_id,row[0])

def checked_dataset(dataset_id,symbol,end,require_complete_day=True):
    dataset=sqlite_record('dataset',dataset_id)
    if dataset['symbol']!=symbol:raise ValueError('Replay dataset symbol differs from the selected book')
    path=builder.dataset_file(dataset)
    if not path.is_file() or builder.sha(path)!=dataset['checksum']:
        raise ValueError('Replay dataset checksum changed')
    if require_complete_day and pd.Timestamp(dataset['last'])<pd.Timestamp(end,tz='UTC')+pd.Timedelta(days=1)-ONE_MINUTE:
        raise ValueError('Replay dataset has no complete UTC cutoff day')
    return dataset,path

def check_source_snapshot(inp):
    reference=inp.get('source_snapshot') or inp.get('source_dir')
    if not reference:raise ValueError('Frozen source snapshot reference is missing')
    root=Path(reference)
    if inp.get('protocol')==2:
        if root.is_absolute() or '..' in root.parts:
            raise ValueError('Frozen source snapshot reference is not logical')
        home=builder.state_root().resolve()
        root=(home/root).resolve()
        if not root.is_relative_to(home):raise ValueError('Frozen source snapshot escapes workbench state')
    else:root=root.resolve()
    if not root.is_dir():raise ValueError('Frozen source snapshot is unavailable')
    source=root/inp['strategy']['file']
    if not source.is_file() or builder.sha(source)!=inp['strategy']['file_hash']:
        raise ValueError('Frozen strategy source checksum changed')
    sources=root/'sources.json'
    if sources.exists():
        for name,digest in builder.read(sources).items():
            path=root/name
            if not path.is_file() or builder.sha(path)!=digest:
                raise ValueError(f'Frozen source dependency changed: {name}')
    if inp.get('protocol')==2:
        snapshot=builder.read(root/'snapshot.json')
        for field in ('snapshot_hash','execution_source_hash','app_build_hash'):
            if snapshot.get(field)!=inp.get(field):raise ValueError(f'Frozen source {field} changed')

def match_run_input(replay,baseline,item):
    marker=replay.get('portfolio_replay')
    if not isinstance(marker,dict) or marker.get('item_id')!=item['id']:
        raise ValueError('Run is not marked for this portfolio item')
    if marker.get('source_run_id') not in item.get('source_run_ids',[]):
        raise ValueError('Replay source run is not part of the original book')
    fixed=('protocol','start','timeframe','session','parameters','capital','fee','slippage',
           'warmup_days','delay_bars','source_hash','source_dir','source_snapshot',
           'execution_source_hash','snapshot_hash','app_build_hash')
    for field in fixed:
        if replay.get(field)!=baseline.get(field):
            raise ValueError(f'Replay changed frozen run setting: {field}')
    if replay['strategy']!=baseline['strategy']:
        raise ValueError('Replay changed the frozen strategy source')
    if replay['dataset']['symbol']!=baseline['dataset']['symbol'] or replay['dataset']['symbol']!=item['symbol']:
        raise ValueError('Replay changed the book market')
    if replay['start']>item['end'] or replay['end']<=item['end']:
        raise ValueError('Replay does not span the current history and a newer day')
    if replay['capital']!=item['capital'] or replay['parameters']!=item['parameters']:
        raise ValueError('Replay accounting or parameters differ from the catalog')
    check_source_snapshot(replay)


def can_replay_legacy_nq_momentum(item):
    return (item.get('id')==LEGACY_NQ_MOMENTUM_ID and
            item.get('key')=='multi-speed-momentum__NQ__1h' and
            item.get('source')=='Workbench' and item.get('symbol')=='NQ' and
            item.get('timeframe')=='1h' and
            item.get('source_run_ids')==[LEGACY_NQ_MOMENTUM_RUN])

def pinned_history_replay(item):
    spec=PINNED_HISTORY_REPLAYS.get(item.get('id'))
    if not spec:return None
    key=f"{spec['strategy_id']}__NQ__{spec['timeframe']}__pinned__{spec['source_run_id']}"
    if (item.get('key')==key and item.get('source')=='Pinned workbench' and
            item.get('symbol')=='NQ' and item.get('timeframe')==spec['timeframe'] and
            item.get('session')=='full-trading-day' and
            item.get('source_run_ids')==[spec['source_run_id']]):return spec
    return None


def verify_pinned_dataset_prefix(item,baseline,dataset,path):
    """A known pinned history may extend only its original, unchanged data."""
    spec=pinned_history_replay(item)
    if (not spec or baseline['strategy']['id']!=spec['strategy_id'] or
            baseline['timeframe']!=spec['timeframe'] or baseline['session']!='full-trading-day'):
        raise ValueError('Pinned replay differs from the exact saved configuration')
    previous=baseline['dataset']
    registered=sqlite_record('dataset',previous['id'])
    for field in ('symbol','checksum','first','last'):
        if previous.get(field)!=registered.get(field):
            raise ValueError(f'Pinned baseline dataset differs from its registration: {field}')
    previous_path=builder.dataset_file(registered)
    if not previous_path.is_file() or builder.sha(previous_path)!=previous['checksum']:
        raise ValueError('Pinned baseline dataset checksum changed')
    if pd.Timestamp(dataset['first'])!=pd.Timestamp(previous['first']):
        raise ValueError('Pinned replay changed the available original warmup history')
    if pd.Timestamp(dataset['last'])<pd.Timestamp(previous['last']):
        raise ValueError('Pinned replay dataset does not cover the original data')
    original=pd.read_parquet(previous_path)
    prefix=pd.read_parquet(path,filters=[('ts_event','<=',pd.Timestamp(previous['last']))])
    try:pd.testing.assert_frame_equal(prefix,original)
    except AssertionError as error:
        raise ValueError('Pinned replay changed the original dataset prefix') from error
    return {'dataset_id':previous['id'],'dataset_checksum':previous['checksum'],
            'first':previous['first'],'last':previous['last'],'rows':len(original),
            'original_prefix_verified':True}


def trade_key(trade):
    return (pd.Timestamp(trade['entry']).isoformat(),pd.Timestamp(trade['exit']).isoformat(),
            round(float(trade['pnl']),6),trade.get('exit_reason'),
            round(float(trade.get('quantity',0)),6),round(float(trade.get('cost',0)),6))

def trade_exit_day(trade):
    return pd.Timestamp(trade['exit']).tz_convert('UTC').strftime('%Y-%m-%d')

def verify_overlap(old,new,start,end,terminal_continues=True):
    """Require parity through the old period, except its forced final close."""
    old_days={row['date']:float(row['pnl']) for row in old['daily'] if start<=row['date']<=end}
    new_days={row['date']:float(row['pnl']) for row in new['daily'] if start<=row['date']<=end}
    if not old_days or set(old_days)!=set(new_days):
        raise ValueError('Replay overlap dates differ from the saved marked history')
    terminal_day=max(old_days)
    forced=([trade for trade in old['trades'] if trade.get('synthetic_exit') and trade_exit_day(trade)==terminal_day]
            if terminal_continues else [])
    if len(forced)>1:raise ValueError('More than one synthetic terminal trade needs correction')
    for day,value in old_days.items():
        if day==terminal_day and forced:continue
        if not np.isclose(value,new_days[day],rtol=0,atol=.01):
            raise ValueError(f'Replay marked P&L diverged on {day}')
    old_trades=[trade_key(trade) for trade in old['trades']
                if start<=trade_exit_day(trade)<=end and trade not in forced]
    new_trades=[trade_key(trade) for trade in new['trades']
                if start<=trade_exit_day(trade)<=end]
    if old_trades!=new_trades:
        raise ValueError('Replay trades diverged from the saved overlapping history')
    return {'terminal_day':terminal_day if forced else None,
            'removed_synthetic_pnl':round(sum(float(t['pnl']) for t in forced),8),
            'terminal_mark_delta':round(new_days[terminal_day]-old_days[terminal_day],8) if forced else 0.0,
            'overlap_days':len(old_days),'overlap_trades':len(old_trades)}

def verify_overnight_overlap(old,new,start,end,source,trades,tick_size,point):
    """Explain one new overnight entry's mark on the old final UTC day.

    A formerly incomplete next session was absent from the old trade ledger.
    Once complete, its entry can precede the old midnight cutoff. Only that
    actual entry's verified mark may change; old fills and earlier marks must
    still agree. Never alter the original series while performing this check.
    """
    old_days={row['date']:float(row['pnl']) for row in old['daily'] if start<=row['date']<=end}
    new_days={row['date']:float(row['pnl']) for row in new['daily'] if start<=row['date']<=end}
    if not old_days or set(old_days)!=set(new_days) or end not in old_days:
        return verify_overlap(old,new,start,end,terminal_continues=False)
    delta=new_days[end]-old_days[end]
    if np.isclose(delta,0,rtol=0,atol=.01):
        return verify_overlap(old,new,start,end,terminal_continues=False)
    cutoff=pd.Timestamp(end,tz='UTC')+pd.Timedelta(days=1)
    entries=pd.to_datetime(trades.entry_time,utc=True)
    exits=pd.to_datetime(trades.exit_time,utc=True)
    active=trades.loc[(entries>=cutoff-pd.Timedelta(days=1))&(entries<cutoff)&(exits>=cutoff)]
    if len(active)!=1:
        raise ValueError('Overnight terminal mark has no unique new crossing session')
    trade=active.iloc[0]
    session_date=date.fromisoformat(str(trade.session_date))
    entry=pd.Timestamp(trade.entry_time)
    exit=pd.Timestamp(trade.exit_time)
    if (entry!=pd.Timestamp(SESSION.open_datetime(session_date)) or
            exit!=pd.Timestamp(SESSION.close_datetime(session_date)) or
            trade.side!='long' or trade.quantity!=1 or trade.reason!='session_close'):
        raise ValueError('Overnight boundary trade differs from the frozen session rules')
    expected_cost=2*float(tick_size)*float(point)+2.5
    if (not np.isfinite([tick_size,point,trade.entry,trade.exit,trade.cost,trade.net_pnl]).all() or
            tick_size<=0 or point<=0 or
            not np.isclose(float(trade.cost),expected_cost,rtol=0,atol=1e-8)):
        raise ValueError('Overnight boundary trade has invalid frozen economics')
    mark_time=cutoff-ONE_MINUTE
    if any(stamp not in source.index for stamp in (entry,exit-ONE_MINUTE,mark_time)):
        raise ValueError('Overnight boundary entry, exit, or UTC close bar is missing')
    if (not np.isclose(float(source.loc[entry,'open']),float(trade.entry),rtol=0,atol=1e-8) or
            not np.isclose(float(source.loc[exit-ONE_MINUTE,'close']),float(trade.exit),rtol=0,atol=1e-8) or
            not np.isclose((float(trade.exit)-float(trade.entry))*point-float(trade.cost),
                           float(trade.net_pnl),rtol=0,atol=1e-8)):
        raise ValueError('Overnight boundary trade does not match its source bars')
    normalized={'entry':trade.entry_time,'exit':trade.exit_time,'pnl':float(trade.net_pnl),
                'quantity':1,'cost':float(trade.cost),'exit_reason':'session_close'}
    if (sum(trade_key(t)==trade_key(normalized) for t in new['trades'])!=1 or
            any(pd.Timestamp(t['entry'])==entry for t in old['trades'])):
        raise ValueError('Overnight boundary trade is not a newly completed session')
    close=float(source.loc[mark_time,'close'])
    carry=(close-float(trade.entry))*point-float(trade.cost)/2
    if not np.isfinite(carry) or not np.isclose(delta,carry,rtol=0,atol=.01):
        raise ValueError('Overnight terminal mark differs from the actual crossing position')
    adjusted={**old,'daily':[dict(row,pnl=float(row['pnl'])+carry) if row['date']==end else dict(row)
                             for row in old['daily']]}
    audit=verify_overlap(adjusted,new,start,end,terminal_continues=False)
    audit.update(terminal_day=end,terminal_mark_delta=round(carry,8),overnight_boundary_carry={
        'entry':entry.isoformat(),'exit':exit.isoformat(),'entry_price':float(trade.entry),
        'mark_time':mark_time.isoformat(),'mark_price':close,'point_value':point,
        'entry_cost':float(trade.cost)/2,'old_daily_pnl':old_days[end],
        'new_daily_pnl':new_days[end],'verified_mark_delta':round(carry,8)})
    return audit


def replace_tail(item,old,replay,start,end,source_run=None,*,overnight_context=None):
    if end<=item['end']:raise ValueError('Replay does not extend the portfolio history')
    audit=(verify_overlap(old,replay,start,item['end']) if overnight_context is None else
           verify_overnight_overlap(old,replay,start,item['end'],**overnight_context))
    prefix_days=[dict(row) for row in old['daily'] if row['date']<start]
    prefix_trades=[dict(trade) for trade in old['trades'] if trade_exit_day(trade)<start]
    coverage=[dict(part) for part in old['coverage'] if part['end']<start]
    if coverage and coverage[-1]['end']>=start:
        raise ValueError('Replay start overlaps a frozen earlier segment')
    segment=f'{start}/{end}'
    tail_days=[dict(row,segment=segment,terminal=row['date']==end)
               for row in replay['daily'] if start<=row['date']<=end]
    if not tail_days or tail_days[-1]['date']!=end:raise ValueError('Replay has no final marked day')
    tail_trades=[dict(trade,segment=segment,**({'source_run':source_run} if source_run else {}))
                 for trade in replay['trades'] if trade_exit_day(trade)>=start]
    for row in prefix_days:row['terminal']=False
    merged={'id':item['id'],'provenance_version':2,
            'daily':prefix_days+tail_days,'trades':sorted(prefix_trades+tail_trades,key=lambda t:(t['entry'],t['exit'])),
            'coverage':coverage+[{'start':start,'end':end}]}
    if len({row['date'] for row in merged['daily']})!=len(merged['daily']):
        raise ValueError('Replay produced duplicate marked days')
    marked=sum(float(row['pnl']) for row in merged['daily'])
    closed=sum(float(row['pnl']) for row in merged['trades'])
    if not np.isclose(marked,closed,rtol=0,atol=.01):
        raise ValueError(f'Replay marked and trade P&L do not reconcile: {marked} vs {closed}')
    return merged,audit

def item_for_series(item,series,metadata):
    payload=json.dumps(series,allow_nan=False,separators=(',',':')).encode('utf-8')
    checksum=hashlib.sha256(payload).hexdigest()
    filename=f"{item['id']}-{checksum[:16]}.json"
    days=series['daily'];cumulative=0.;curve=[0.]
    for row in days:
        cumulative+=float(row['pnl']);curve.append(cumulative)
    stride=max(1,(len(curve)+47)//48)
    chart=[round(value,6) for value in curve[::stride]]
    if chart[-1]!=round(curve[-1],6):chart.append(round(curve[-1],6))
    reasons=list(item.get('reasons',[]))
    note='Later dates are portfolio tracking replays; the original research evaluation remains frozen.'
    if note not in reasons:reasons.append(note)
    updated={**item,'end':series['coverage'][-1]['end'],'coverage':series['coverage'],
             'series_file':filename,'checksum':checksum,'net_pnl':round(cumulative,6),
             **builder.daily_risk({row['date']:float(row['pnl']) for row in days},item['capital']),
             'recent_pnl':round(sum(float(row['pnl']) for row in days if row['date']>='2024-01-01'),6),
             'trades':len(series['trades']),'chart_points':chart,'reasons':reasons,
             'verified_replay':metadata}
    return updated,payload

def publish(item_id,original_checksum,series,metadata,audit):
    with builder.catalog_lock():
        index,item,current=read_index_item(item_id)
        if item['checksum']!=original_checksum:
            raise ValueError('Portfolio history changed while the replay was running; retry verification')
        updated,payload=item_for_series(item,series,metadata)
        path=builder.OUT/updated['series_file']
        if path.exists():
            if builder.sha(path)!=updated['checksum']:raise ValueError('Immutable replay series name collided')
        else:builder.write_bytes_atomic(path,payload)
        overlays_path=builder.OUT/'verified-replays.json'
        overlays=builder.read(overlays_path) if overlays_path.exists() else {}
        if not isinstance(overlays,dict):raise ValueError('Verified replay overlay is invalid')
        base_checksum=overlays.get(item_id,{}).get('base_checksum',item['checksum'])
        overlays[item_id]={'base_checksum':base_checksum,'item':updated,'audit':audit}
        # The overlay is the durable recovery point; the catalog is the current
        # read model. A crash after this write is repaired by Refresh evidence.
        builder.dump(overlays_path,overlays)
        index['items']=[updated if row['id']==item_id else row for row in index['items']]
        index['generated_at']=pd.Timestamp.now(tz='UTC').isoformat()
        builder.dump(builder.OUT/'index.json',index)
    return {'item_id':item_id,'end':updated['end'],'checksum':updated['checksum'],
            'dataset_id':metadata['dataset_id'],'audit':audit}

def publish_run(item_id,run_id):
    _,item,old=read_index_item(item_id)
    pinned=pinned_history_replay(item)
    if (item.get('source') not in ('Current workbench','Workbench') and not pinned) or not item.get('source_run_ids') \
            or (item['source']=='Workbench' and not item.get('latest_replay') and
                not can_replay_legacy_nq_momentum(item)):
        raise ValueError('This book requires a manual update')
    record=sqlite_record('run',run_id)
    if record['status']!='Succeeded':raise ValueError('Portfolio replay run did not succeed')
    replay=record['input'];marker=replay.get('portfolio_replay') or {}
    source_id=marker.get('source_run_id')
    baseline=sqlite_record('run',source_id)['input'] if source_id else {}
    match_run_input(replay,baseline,item)
    dataset,dataset_path=checked_dataset(replay['dataset']['id'],item['symbol'],replay['end'])
    if replay['dataset']['checksum']!=dataset['checksum']:
        raise ValueError('Run dataset differs from its registration')
    prefix_audit=verify_pinned_dataset_prefix(item,baseline,dataset,dataset_path) if pinned else None
    required_first=pd.Timestamp(replay['start'],tz='UTC')-pd.Timedelta(days=replay['warmup_days'])
    if pd.Timestamp(dataset['first'])>required_first:
        if (not pinned or pinned['strategy_id']!='rsi2-reversion' or
                pd.Timestamp(dataset['first'])>pd.Timestamp(replay['start'],tz='UTC')):
            raise ValueError('Replay dataset lacks the full warmup and scored history')
        prefix_audit['preserved_warmup_shortfall']={
            'declared_start':required_first.isoformat(),'available_start':dataset['first']}
    previous=baseline['dataset']
    for field in ('source','currency','tick_size','point_value'):
        if field in previous and dataset.get(field)!=previous[field]:
            raise ValueError(f'Replay dataset changed the frozen market contract: {field}')
    if previous.get('query') and dataset.get('query'):
        for field in ('dataset','schema','symbols','stype_in','stype_out'):
            if dataset['query'].get(field)!=previous['query'].get(field):
                raise ValueError(f'Replay dataset changed the frozen market query: {field}')
    folder=builder.state_root()/'runs'/run_id
    manifest=builder.verified(folder,['trades.csv','equity.csv'])
    if manifest.get('run_id') not in (None,run_id):raise ValueError('Run manifest ID differs')
    saved=builder.read(folder/'input.json')
    if saved!=replay:raise ValueError('Run input file differs from its saved record')
    trades,marks,_=builder.canonical_run(run_id)
    marks={day:value for day,value in marks.items() if replay['start']<=day<=replay['end']}
    if not marks:raise ValueError('Replay has no marked dates')
    end=max(marks)
    rows=[{'date':day,'pnl':value} for day,value in sorted(marks.items())]
    candidate={'daily':rows,'trades':trades}
    if end<item['end']:raise ValueError('Replay dataset does not cover the saved portfolio end')
    if end==item['end']:
        verify_overlap(old,candidate,replay['start'],item['end'],terminal_continues=False)
        return {'item_id':item_id,'no_new_session':True,'end':item['end'],
                'dataset_id':dataset['id'],'dataset_checksum':dataset['checksum']}
    combined,audit=replace_tail(item,old,candidate,replay['start'],end,run_id)
    if prefix_audit:audit['preserved_baseline_data']=prefix_audit
    metadata={'dataset_id':dataset['id'],'dataset_checksum':dataset['checksum'],
              'end':end,'artifact_sha256':builder.sha(folder/'manifest.json'),
              'published_at':pd.Timestamp.now(tz='UTC').isoformat(),'source_run_id':run_id}
    return publish(item_id,item['checksum'],combined,metadata,audit)

def verify_frozen_overnight(symbol):
    plan=builder.read(FROZEN/'PLAN.json')
    selections=builder.read(FROZEN/'FROZEN_SELECTIONS.json')['selections']
    key=f'overnight-session__{symbol}__1m__globex-overnight'
    if not any(row['key']==key for row in selections):raise ValueError('Overnight book was not frozen')
    if plan['capital']!=100000 or plan['costs']!=(
        'One full-size contract; $1.25/side plus one tick/side, '
        'represented as equivalent round-trip cost ticks.'):
        raise ValueError('Frozen overnight costs or capital changed')
    for name in ('strategy_engine/accounting.py','strategy_engine/sessions.py',
                 'strategy_engine/strategies/session_drift.py'):
        expected=plan['source_hashes'][name.replace('/','\\')]
        if builder.sha(ROOT/name)!=expected:raise ValueError(f'Frozen overnight source changed: {name}')
    return plan,key

def complete_overnight_sessions(bars,start,cutoff):
    groups={name:group for name,group in bars.groupby('session_date',sort=True)}
    complete=[]
    for day in pd.bdate_range(start,cutoff):
        name=day.date().isoformat();part=groups.get(name)
        expected_open=pd.Timestamp(SESSION.open_datetime(day.date()))
        expected_close=pd.Timestamp(SESSION.close_datetime(day.date()))-ONE_MINUTE
        if part is None or part.empty:
            # A final absent session can be a holiday or a weekend cutoff. An
            # internal absent session is a data gap without a trusted calendar.
            if complete and not any(name<key<=cutoff for key in groups):break
            raise ValueError(f'Overnight session is missing: {name}')
        if part.index[0]!=expected_open or part.index[-1]!=expected_close \
                or not part.index.is_unique or not part.index.is_monotonic_increasing:
            raise ValueError(f'Overnight session lacks complete endpoints: {name}')
        complete.append(name)
    if not complete or complete[0]!=start:raise ValueError('First replay overnight session is incomplete')
    return complete

def overnight_daily(source,trades,start,end,point):
    boundary=(date.fromisoformat(start)-timedelta(days=1)).isoformat()
    prices=source.close.groupby(source.index.floor('D')).last().loc[boundary:end]
    entries=pd.to_datetime(trades.entry_time,utc=True)
    exits=pd.to_datetime(trades.exit_time,utc=True)
    cumulative={}
    for stamp,close in prices.items():
        cutoff=stamp+pd.Timedelta(days=1)
        closed=float(trades.loc[exits<cutoff,'net_pnl'].sum())
        active=trades.loc[(entries<cutoff)&(exits>=cutoff)]
        if len(active)>1:raise ValueError('Overnight replay has overlapping positions')
        if len(active):
            trade=active.iloc[0]
            closed+=(1 if trade.side=='long' else -1)*(float(close)-float(trade.entry))*point-float(trade.cost)/2
        cumulative[stamp.strftime('%Y-%m-%d')]=round(closed,8)
    if boundary not in cumulative:raise ValueError('Overnight boundary UTC mark is missing')
    prior=cumulative.pop(boundary)
    daily={}
    for day,mark in cumulative.items():
        if day>=start:
            daily[day]=round(mark-prior,8)
        prior=mark
    if not daily or max(daily)!=end:raise ValueError('Overnight replay does not reach its final session')
    if not np.isclose(prior,float(trades.net_pnl.sum()),rtol=0,atol=.01):
        raise ValueError('Overnight marked and trade P&L do not reconcile')
    return daily

def run_overnight(item_id,dataset_id,cutoff,publish_result=True):
    symbol=OVERNIGHT_IDS.get(item_id)
    if not symbol:raise ValueError('Item is not a supported Expanded Overnight Session book')
    _,item,old=read_index_item(item_id)
    plan,key=verify_frozen_overnight(symbol)
    if item['source']!='Expanded' or item['key']!=key or item['capital']!=plan['capital']:
        raise ValueError('Overnight book identity differs from its frozen campaign')
    dataset,path=checked_dataset(dataset_id,symbol,cutoff,require_complete_day=publish_result)
    if dataset['query']['schema']!='ohlcv-1m' or dataset['query']['symbols']!=[f'{symbol}.v.0']:
        raise ValueError('Overnight dataset contract differs from the frozen market')
    if (float(dataset['tick_size']),float(dataset['point_value']))!=OVERNIGHT_ECONOMICS[symbol]:
        raise ValueError('Overnight dataset contract economics changed')
    start=item['coverage'][-1]['start']
    if pd.Timestamp(dataset['first'])>pd.Timestamp(start,tz='UTC')-pd.Timedelta(days=4):
        raise ValueError('Overnight dataset lacks the full overlapping history')
    source=pd.read_parquet(path,columns=['open','high','low','close','volume'],
                           filters=[('ts_event','>=',pd.Timestamp(start,tz='UTC')-pd.Timedelta(days=4)),
                                    ('ts_event','<',pd.Timestamp(cutoff,tz='UTC')+pd.Timedelta(days=1))])
    if source.empty or not source.index.is_unique or not source.index.is_monotonic_increasing or source.index.tz is None:
        raise ValueError('Overnight source timestamps are invalid')
    if not np.isfinite(source[['open','high','low','close']]).all().all():
        raise ValueError('Overnight source OHLC is invalid')
    bars=session_bars(source,SESSION,'1m')
    complete=complete_overnight_sessions(bars.loc[bars.session_date>=start],start,cutoff)
    end=complete[-1]
    config=SessionDriftConfig(cost_ticks=2+2.5/(float(dataset['tick_size'])*float(dataset['point_value'])))
    selected=bars.loc[bars.session_date.between(start,end)]
    trades,_=drift(selected,symbol=symbol,tick_size=dataset['tick_size'],
                   point_value=dataset['point_value'],config=config)
    if trades.session_date.tolist()!=complete or not (trades.reason=='session_close').all() \
            or not (trades.quantity==1).all():
        raise ValueError('Overnight replay departed from one-contract session-close rules')
    if not np.allclose(trades.gross_pnl-trades.cost,trades.net_pnl,rtol=0,atol=1e-8):
        raise ValueError('Overnight replay trade accounting differs')
    daily=overnight_daily(source,trades,start,end,float(dataset['point_value']))
    normalized=[{'entry':row.entry_time,'exit':row.exit_time,'pnl':round(float(row.net_pnl),8),
                 'quantity':int(row.quantity),'cost':round(float(row.cost),8),
                 'exit_reason':row.reason,'synthetic_exit':False}
                for row in trades.itertuples()]
    candidate={'daily':[{'date':day,'pnl':value} for day,value in sorted(daily.items())],
               'trades':normalized}
    overlap_context={'source':source,'trades':trades,'tick_size':float(dataset['tick_size']),
                     'point':float(dataset['point_value'])}
    if not publish_result:
        return verify_overnight_overlap(old,candidate,start,item['end'],**overlap_context)
    if end<item['end']:raise ValueError('Overnight dataset does not cover the saved portfolio end')
    if end==item['end']:
        verify_overnight_overlap(old,candidate,start,item['end'],**overlap_context)
        return {'item_id':item_id,'no_new_session':True,'end':item['end'],
                'dataset_id':dataset_id,'dataset_checksum':dataset['checksum']}
    combined,audit=replace_tail(item,old,candidate,start,end,overnight_context=overlap_context)
    series_payload=json.dumps(combined,allow_nan=False,separators=(',',':')).encode('utf-8')
    metadata={'dataset_id':dataset_id,'dataset_checksum':dataset['checksum'],'end':end,
              'artifact_sha256':hashlib.sha256(series_payload).hexdigest(),
              'published_at':pd.Timestamp.now(tz='UTC').isoformat()}
    return publish(item_id,item['checksum'],combined,metadata,audit)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    actions=parser.add_subparsers(dest='action',required=True)
    run=actions.add_parser('publish-run');run.add_argument('--item-id',required=True);run.add_argument('--run-id',required=True)
    night=actions.add_parser('run-overnight');night.add_argument('--item-id',required=True)
    night.add_argument('--dataset-id',required=True);night.add_argument('--end',required=True)
    args=parser.parse_args()
    try:
        result=(publish_run(args.item_id,args.run_id) if args.action=='publish-run'
                else run_overnight(args.item_id,args.dataset_id,args.end))
        print(json.dumps(result,allow_nan=False))
    except Exception as error:
        print(json.dumps({'error':str(error)},allow_nan=False),file=sys.stderr)
        raise SystemExit(1)

if __name__=='__main__':main()
