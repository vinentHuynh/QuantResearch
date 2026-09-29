"""Prelaunch full-history controls, crossed-rule parity and cutoff reconstruction."""
from __future__ import annotations
import argparse
import hashlib
from concurrent.futures import ProcessPoolExecutor, as_completed
import importlib.util
from pathlib import Path
import sys
import time
import traceback
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    result=importlib.util.module_from_spec(spec)
    sys.modules[name]=result
    spec.loader.exec_module(result)
    return result
runner=module('combination_runner',ROOT/'scripts/research-snd-combinations.py')

def csv_trades(path):
    frame=pd.read_csv(path,float_precision='round_trip')
    for key in frame:
        if key.endswith('_time'): frame[key]=pd.to_datetime(frame[key],utc=True)
    return frame

def compare(old,new,exact=True):
    for field in ['trades','equity']:
        left,right=old[field],new[field]
        assert set(left.columns).issubset(right.columns),(field,'missing columns')
        pd.testing.assert_frame_equal(left.reset_index(drop=True),right[left.columns].reset_index(drop=True),
            check_dtype=False,check_exact=exact,atol=1e-10,rtol=0)

def frame_digest(frame):
    return hashlib.sha256(pd.util.hash_pandas_object(frame,index=True).to_numpy().tobytes()).hexdigest()

def market_check(out_name,d):
    out=Path(out_name)
    from strategies import _snd_combination_fast as fast
    from strategies import _snd_combination_reference as reference
    analysis=module('combination_analysis',ROOT/'scripts/analyze-snd-combinations.py')
    protocol=runner.read(out/'protocol.json')
    source=runner.load_market(d)
    raw_digest=frame_digest(source)
    prepared=fast.prepare_data(source,pivot_len=2,execution_minutes=1)
    reference_prepared=reference.prepare_data(source.copy(deep=True),pivot_len=2,execution_minutes=1)
    prepared_digests={key:frame_digest(prepared[key]) for key in ['source','chart','hourly']}
    fee=1.25 if d['symbol'] in ('MNQ','MGC') else 2.50
    records=[]
    baseline=None
    for campaign,variants in [('snd-zone-quality-2026-09-25',None),('snd-body-retest-2026-09-24',['body'])]:
        origin=ROOT/'reports'/campaign
        prior=runner.read(origin/'protocol.json')
        for case in prior['cases']:
            if case['symbol']!=d['symbol'] or variants is not None and case['variant'] not in variants: continue
            started=time.monotonic()
            parameters=case['parameters']
            result=fast.run_model(prepared,parameters,d['start'],d['end'],d['tick_size'],d['point_value'],case['fee'],case['slippage_ticks'])
            folder=origin/d['symbol']/case['variant']
            old={'trades':csv_trades(folder/'trades.csv'),'equity':pd.read_parquet(folder/'equity.parquet')}
            compare(old,result)
            if campaign.startswith('snd-zone-quality') and case['variant']=='baseline': baseline=result
            records.append(dict(kind='frozen_full_history_control',campaign=campaign,variant=case['variant'],
                trades=len(result['trades']),status='passed',elapsed_seconds=time.monotonic()-started))
            print(f'{d["symbol"]} frozen {case["variant"]}: exact parity',flush=True)
    base=runner.read(out/'configurations.json')[0]['parameters']
    # Fixed identities selected without inspecting outcomes; cover interactions
    # absent from the one-factor campaign over a full calendar year.
    configs=runner.read(out/'configurations.json')
    indices=[15,31,63,95,127,777,1295,2591,3887,5183,7775,10367]
    for index in indices:
        config=configs[index]
        p=config['parameters']
        for mode in ['cash','price'] if index in [127,10367] else ['cash']:
            p=p|dict(slippage_model=mode)
            args=(p,'2024-01-01','2025-01-01',d['tick_size'],d['point_value'],fee,1)
            expected=reference.run_model(reference_prepared,*args)
            actual=fast.run_model(prepared,*args)
            compare(expected,actual)
            records.append(dict(kind='crossed_reference',config_id=config['config_id'],slippage_model=mode,
                status='passed',trades=len(actual['trades'])))
    # All declared training boundaries plus a cutoff inside an actual position.
    cutoffs=[fold['cutoff'] for fold in protocol['folds']]
    duration=(pd.to_datetime(baseline['trades'].exit_time,utc=True)-pd.to_datetime(baseline['trades'].entry_time,utc=True))
    long=baseline['trades'].loc[duration>=pd.Timedelta(minutes=20)]
    if len(long): cutoffs.append((pd.Timestamp(long.iloc[len(long)//2].entry_time)+pd.Timedelta(minutes=7)).isoformat())
    for cutoff in cutoffs:
        hi=analysis.utc(cutoff)
        raw=source.loc[source.index+pd.Timedelta(minutes=1)<=hi].copy()
        last=raw.iloc[-1]
        censored=analysis.causal_training_trades(baseline['trades'],d['start'],cutoff,
            last_source_open=last.name,last_source_close=last.close,point_value=d['point_value'],tick_size=d['tick_size'],fee=fee)
        expected=reference.run_model(raw,base,d['start'],cutoff,d['tick_size'],d['point_value'],fee,1)
        original=expected['trades'].copy()
        censored.loc[censored.exit_reason=='training-cutoff','exit_reason']='end-of-test'
        pd.testing.assert_frame_equal(original,censored[original.columns],check_dtype=False,check_exact=True)
        records.append(dict(kind='causal_prefix',cutoff=cutoff,status='passed',trades=len(original),
                            raw_last_source_open=str(last.name)))
    assert frame_digest(source)==raw_digest,'Prepared/run API mutated raw input'
    assert prepared_digests=={key:frame_digest(prepared[key]) for key in prepared_digests},'Fast execution mutated prepared candles/features'
    details=dict(status='passed',symbol=d['symbol'],records=records)
    filename=f'{d["symbol"]}-'+runner.now().replace(':','').replace('.','')+'.json'
    destination=out/'preflight'/filename
    runner.save(destination,details)
    runner.save(out/'preflight'/f'{d["symbol"]}.json',details)
    return dict(symbol=d['symbol'],status='passed',checks=len(records),
                artifact=str(destination.relative_to(out)),artifact_checksum=runner.checksum(destination))

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output',type=Path,default=runner.OUT)
    ap.add_argument('--workers',type=int,default=4)
    args=ap.parse_args()
    out=args.output.resolve()
    protocol=runner.read(out/'protocol.json')
    paths=['strategies/_snd_combination_fast.py','strategies/_snd_combination_fast_io.py','strategies/_snd_combination_reference.py',
           'scripts/research-snd-combinations.py','scripts/analyze-snd-combinations.py','scripts/check-snd-combinations.py']
    hashes={name:runner.checksum(ROOT/name) for name in paths}
    results=[]
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures={pool.submit(market_check,str(out),d):d['symbol'] for d in protocol['datasets']}
        for f in as_completed(futures):
            try: results.append(f.result())
            except Exception:
                results.append(dict(symbol=futures[f],status='failed',error=traceback.format_exc()))
    assert hashes=={name:runner.checksum(ROOT/name) for name in paths},'Source changed during preflight'
    result=dict(status='passed' if all(r['status']=='passed' for r in results) else 'failed',
        completed_at=runner.now(),protocol_checksum=runner.checksum(out/'protocol.json'),source_files=hashes,markets=results,
        scope='52 frozen full-history controls,56 crossed-rule full-year comparisons,12 declared prefixes plus actual open-position censoring.')
    destination=out/'preflight'/('attempt-'+runner.now().replace(':','').replace('.','')+'.json')
    runner.save(destination,result)
    runner.save(out/'preflight.json',result)
    print(result['status'],flush=True)
    return 0 if result['status']=='passed' else 1

if __name__=='__main__': raise SystemExit(main())
