"""Describe each rule's matched effect across all declared combination backgrounds.

These are sensitivity summaries, not independent observations or extra unadjusted
hypothesis tests. Each pair changes exactly one concept, with all others fixed.
"""
from __future__ import annotations
import argparse
import importlib.util
from pathlib import Path
import sys
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('combination_factor_runner',ROOT/'scripts/research-snd-combinations.py')
r=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=r
spec.loader.exec_module(r)

def matched_pairs(configs,grid,key,level):
    keys=list(grid)
    lookup={tuple(c['parameters'][k] for k in keys):c['config_id'] for c in configs}
    rows=[]
    for config in configs:
        p=config['parameters']
        if p[key]!=grid[key][0]: continue
        alternate=tuple(level if k==key else p[k] for k in keys)
        rows.append((config['config_id'],lookup[alternate]))
    assert len(rows)==len(configs)//len(grid[key])
    return rows

def effect_summary(frame,pairs,minimum_trades):
    baseline=frame.loc[[a for a,b in pairs]].reset_index(drop=True)
    changed=frame.loc[[b for a,b in pairs]].reset_index(drop=True)
    valid=(baseline.trades>=minimum_trades)&(changed.trades>=minimum_trades)&baseline.mean_net_r.notna()&changed.mean_net_r.notna()
    a,b=baseline.loc[valid],changed.loc[valid]
    delta_r=b.mean_net_r-a.mean_net_r
    delta_cash=b.closed_net-a.closed_net
    return dict(declared_pairs=len(pairs),both_meet_trade_minimum=int(valid.sum()),minimum_trades_each=minimum_trades,
        median_delta_mean_net_r=float(delta_r.median()) if len(a) else None,
        lower_quartile_delta_mean_net_r=float(delta_r.quantile(.25)) if len(a) else None,
        upper_quartile_delta_mean_net_r=float(delta_r.quantile(.75)) if len(a) else None,
        fraction_improved_mean_net_r=float((delta_r>0).mean()) if len(a) else None,
        fraction_improved_cash_net=float((delta_cash>0).mean()) if len(a) else None,
        median_delta_cash_net=float(delta_cash.median()) if len(a) else None,
        median_trade_count_ratio=float((b.trades/a.trades).median()) if len(a) else None,
        median_baseline_mean_net_r=float(a.mean_net_r.median()) if len(a) else None,
        median_changed_mean_net_r=float(b.mean_net_r.median()) if len(a) else None)

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output',type=Path,default=r.OUT)
    args=ap.parse_args()
    out=args.output.resolve()
    manifest=r.verify_source(out)
    r.verify_executing_file(manifest,'scripts/summarize-snd-combination-factors.py',__file__)
    protocol=r.read(out/'protocol.json')
    configs=r.read(out/'configurations.json')
    rows=[]
    for symbol in protocol['markets']:
        frames=[]
        for shard in sorted((out/'sweep'/symbol).glob('shard-*')):
            successes=[a for a in shard.glob('attempt-*') if (a/'result.json').exists() and r.read(a/'result.json')['status']=='succeeded']
            assert len(successes)==1,'Require one successful preserved attempt per shard'
            attempt=successes[0]
            result=r.read(attempt/'result.json')
            assert all(result[k]==manifest[k] for k in ['protocol_checksum','source_hash','configurations_checksum'])
            saved=next(a for a in result['artifacts'] if a['name']=='periods.parquet')
            assert r.checksum(attempt/'periods.parquet')==saved['checksum']
            frames.append(pd.read_parquet(attempt/'periods.parquet'))
        assert frames,'No completed sweep'
        frame=pd.concat(frames,ignore_index=True)
        for period in ['all','later']:
            data=frame.loc[frame.period==period].set_index('config_id')
            assert data.index.is_unique and set(data.index)=={c['config_id'] for c in configs}
            for key,levels in protocol['grid'].items():
                for value in levels[1:]:
                    pairs=matched_pairs(configs,protocol['grid'],key,value)
                    for minimum in [1,100]:
                        rows.append(dict(symbol=symbol,period=period,rule=key,baseline_level=levels[0],changed_level=value,
                            **effect_summary(data,pairs,minimum)))
    result=pd.DataFrame(rows)
    r.verify_source(out)
    r.verify_executing_file(manifest,'scripts/summarize-snd-combination-factors.py',__file__)
    result.to_csv(out/'factor-effects.csv',index=False)
    r.save(out/'factor-effects.json',dict(status='succeeded',protocol_checksum=manifest['protocol_checksum'],source_hash=manifest['source_hash'],
        created_at=r.now(),rows=len(rows),artifact_checksum=r.checksum(out/'factor-effects.csv'),
        interpretation='Descriptive matched one-rule changes across allotherdeclaredsettings. Configurations share data andtrades; pair counts arenotindependent evidence. Differences do not establish causality, universal invalidity or future profit. Both anytrades and>=100each subsets retained. No winner substitution.',
        records=rows))
    print(f'{len(rows)} descriptive rule contrasts saved.',flush=True)

if __name__=='__main__': main()
