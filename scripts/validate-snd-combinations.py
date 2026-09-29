"""Replay frozen chronological selections, execution stresses and integer sizing.

Selection must exist before evaluation starts. Every fold starts flat with30
calendar days of causal warmup. Validation never replaces a selected rule.
"""
from __future__ import annotations
import argparse
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
runner=module('combination_runner_validation',ROOT/'scripts/research-snd-combinations.py')

def selected_cases(selection,protocol,configs):
    """A deterministic list, including cash when training finds no eligible rule."""
    rows=[]
    for choice in selection['selections']:
        selected=choice['selected_id']
        parameters=configs[selected]['parameters'] if selected else None
        roles=[('reference',configs['c00000']['parameters'],'c00000'),('selected',parameters,selected)]
        roles += [(f'neighbor-{i}',parameters|delta if parameters else None,selected)
                  for i,delta in enumerate(protocol['validation_neighbors'])]
        roles += [(f'risk-{budget}',parameters|dict(sizing_mode='fixed_risk',risk_budget=float(budget),max_contracts=10)
                    if parameters else None,selected) for budget in [50,100,200]]
        for role,p,cid in roles:
            scenarios=protocol['validation_scenarios'][:1] if role.startswith('neighbor-') else protocol['validation_scenarios']
            for scenario in scenarios:
                rows.append(dict(symbol=choice['symbol'],fold_id=choice['fold_id'],start=choice['cutoff'],end=choice['test_end'],
                    role=role,config_id=cid,decision='selected' if p else 'cash',scenario=scenario['id'],
                    parameters=p|dict(slippage_model=scenario['slippage_model']) if p else None,
                    fee_multiple=scenario['fee_multiple'],slippage_ticks=scenario['slippage_ticks']))
    return rows

def cash_result(reference,case,capital):
    t=pd.DataFrame(columns=reference.TRADE_COLUMNS)
    stamps=pd.to_datetime([case['start'],case['end']],utc=True)
    e=pd.DataFrame(dict(timestamp=stamps,equity=capital,balance=capital,unrealized_pnl=0.,net_pnl=0.,contracts=0))
    return dict(trades=t,equity=e,diagnostics=dict(trades=0,decision='cash',warmup='No eligible training configuration'))

def summary(result,capital):
    t,e=result['trades'],result['equity']
    np.testing.assert_allclose(e.equity.iloc[-1]-capital,t.net_pnl.sum(),atol=1e-5,rtol=0)
    np.testing.assert_allclose(e.net_pnl.sum(),t.net_pnl.sum(),atol=1e-5,rtol=0)
    assert e.contracts.iloc[-1]==0
    metrics=runner.basic_trade_metrics(t)
    values=np.r_[capital,e.equity.to_numpy(float)]
    metrics.update(net_r_sum=float(t.net_r.sum()),net_pnl=float(values[-1]-capital),
        max_drawdown=float((np.maximum.accumulate(values)-values).max()),min_equity=float(values.min()),
        max_trade_loss=max(0.,float(-t.net_pnl.min())) if len(t) else 0.)
    if 'contracts_abs' in t:
        metrics.update(contracts_entered=int(t.contracts_abs.sum()),max_quantity=int(t.contracts_abs.max()) if len(t) else 0,
            maximum_planned_stop_loss=float(t.planned_stop_risk_cash.max()) if len(t) else 0.,
            maximum_actual_stop_loss=float(t.actual_stop_risk_cash.max()) if len(t) and 'actual_stop_risk_cash' in t else None,
            total_budget_overshoot=float(t.risk_budget_overshoot_cash.sum()) if len(t) else 0.)
    return metrics

def market_run(out_name,d,cases,identity,retry_failed=False):
    out=Path(out_name)
    manifest=runner.verify_source(out)
    runner.verify_executing_file(manifest,'scripts/validate-snd-combinations.py',__file__)
    sys.path.insert(0,str(out/'source'))
    reference=module('validation_reference',out/'source/strategies/_snd_combination_reference.py')
    risk=module('validation_risk',out/'source/strategies/_snd_combination_risk.py')
    source=runner.load_market(d)
    prepared={}
    summaries=[]
    for case in cases:
        if case['symbol']!=d['symbol']: continue
        folder=out/'validation'/case['symbol']/case['fold_id']/case['role']/case['scenario']
        if (folder/'result.json').exists():
            old=runner.read(folder/'result.json')
            assert all(old[k]==v for k,v in identity.items()),'Existing validation identity differs'
            if old['status']=='succeeded':
                for item in old['artifacts']: assert runner.checksum(folder/item['name'])==item['checksum']
                summaries.append(old)
                continue
            raise RuntimeError('Failed validation attempt preserved: '+str(folder))
        if folder.exists() and any(folder.iterdir()):
            raise RuntimeError('Incomplete validation attempt preserved: '+str(folder))
        folder.mkdir(parents=True,exist_ok=True)
        runner.save(folder/'input.json',dict(**case,**identity,dataset=d))
        runner.save(folder/'status.json',dict(status='running',started_at=runner.now()))
        started=time.monotonic()
        try:
            parameters=case['parameters']
            if parameters is None:
                result=cash_result(reference,case,100000.)
            else:
                key=(case['fold_id'],parameters['pivot_len'])
                if key not in prepared:
                    lo=pd.Timestamp(case['start'],tz='UTC')-pd.Timedelta(days=30)
                    hi=pd.Timestamp(case['end'],tz='UTC')
                    # Truncating the supplied source also proves indicators cannot
                    # observe any future fold candles.
                    raw=source.loc[(source.index>=lo)&(source.index<hi)]
                    prepared[key]=reference.prepare_data(raw,pivot_len=parameters['pivot_len'],execution_minutes=1)
                model=risk if case['role'].startswith('risk-') else reference
                fee=(1.25 if d['symbol'] in ('MNQ','MGC') else 2.50)*case['fee_multiple']
                result=model.run_model(prepared[key],parameters,case['start'],case['end'],d['tick_size'],d['point_value'],fee,case['slippage_ticks'])
            metrics=summary(result,100000.)
            names=[]
            for key,name in [('trades','trades.parquet'),('equity','equity.parquet'),('sizing_decisions','sizing-decisions.parquet')]:
                if key in result:
                    result[key].to_parquet(folder/name,index=False,compression='zstd')
                    names.append(name)
            record=dict(status='succeeded',**case,**identity,summary=metrics,diagnostics=result['diagnostics'],
                completed_at=runner.now(),elapsed_seconds=time.monotonic()-started,
                artifacts=[dict(name=name,checksum=runner.checksum(folder/name)) for name in names])
        except Exception as error:
            (folder/'error.log').write_text(traceback.format_exc(),encoding='utf-8')
            record=dict(status='failed',**case,**identity,error=str(error),elapsed_seconds=time.monotonic()-started)
        runner.save(folder/'result.json',record)
        runner.save(folder/'status.json',dict(status=record['status'],completed_at=runner.now()))
        summaries.append(record)
        print(f'{d["symbol"]}/{case["fold_id"]}/{case["role"]}/{case["scenario"]}: {record["status"]}',flush=True)
        if record['status']!='succeeded': raise RuntimeError('Validation failed: '+str(folder))
    return summaries

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output',type=Path,default=runner.OUT)
    ap.add_argument('--workers',type=int,default=4)
    args=ap.parse_args()
    out=args.output.resolve()
    manifest=runner.verify_source(out)
    runner.verify_executing_file(manifest,'scripts/validate-snd-combinations.py',__file__)
    protocol=runner.read(out/'protocol.json')
    selection=runner.read(out/'selection.json')
    identity={k:manifest[k] for k in ['protocol_checksum','source_hash','configurations_checksum']}
    assert all(selection[k]==v for k,v in identity.items()),'Selection identity changed'
    assert selection['training_only'] and selection['complete_grid_verified']
    identity['selection_checksum']=runner.checksum(out/'selection.json')
    expected={(d['symbol'],fold['id']) for d in protocol['datasets'] for fold in protocol['folds']}
    actual=[(s['symbol'],s['fold_id']) for s in selection['selections']]
    assert len(actual)==len(set(actual)) and set(actual)==expected
    configs={c['config_id']:c for c in runner.read(out/'configurations.json')}
    cases=selected_cases(selection,protocol,configs)
    assert len(cases)==312
    plan=dict(**identity,expected_cases=len(cases),cases=cases,
        sizing_policy='Budgets50/100/200cashunits perentry; quantity floorbudget/allinplannedstoprisk,cap10. Quantityfrozenatarm. Cost/fillchanges rerunfullstate; no posthoc ledgerrescaling. Budget isnotguaranteed undergaps.')
    if (out/'validation-plan.json').exists():
        existing=runner.read(out/'validation-plan.json')
        assert all(existing.get(k)==v for k,v in plan.items()),'Existing validation plan differs'
    else:
        runner.save(out/'validation-plan.json',dict(declared_at=runner.now(),**plan))
    summaries=[]
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for job in as_completed([pool.submit(market_run,str(out),d,cases,identity) for d in protocol['datasets']]):
            summaries.extend(job.result())
    assert runner.checksum(out/'selection.json')==identity['selection_checksum'],'Selection changed during evaluation'
    runner.verify_source(out)
    runner.verify_executing_file(manifest,'scripts/validate-snd-combinations.py',__file__)
    runner.save(out/'validation-results.json',dict(status='succeeded',**identity,completed_at=runner.now(),
        cases=summaries,expected_cases=len(cases),completed_cases=len(summaries)))
    print(f'{len(summaries)} chronological validation cases completed.',flush=True)

if __name__=='__main__': main()
