"""Read all frozen zone-factor ledgers; compare chronology and joint uncertainty."""
from __future__ import annotations
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'reports/snd-zone-quality-2026-09-25'
spec=importlib.util.spec_from_file_location('quality_driver',ROOT/'scripts/research-snd-zone-quality.py')
driver=importlib.util.module_from_spec(spec)
spec.loader.exec_module(driver)
read,save,checksum=driver.read,driver.save,driver.checksum

def cohort_mask(t,lo,hi):
    x=pd.to_datetime(t.exit_time,utc=True)
    close=t.exit_reason.isin(['contract-roll','end-of-test'])
    return ((~close)&(x>=lo)&(x<hi)) | (close&(x>lo)&(x<=hi))

def metrics(t,e,bounds,capital=100000.):
    lo,hi=(pd.Timestamp(x,tz='UTC') for x in bounds)
    c=t.loc[cohort_mask(t,lo,hi)]
    et=pd.to_datetime(e.timestamp,utc=True)
    part=e.loc[(et>lo)&(et<=hi),'equity'].to_numpy()
    before=e.loc[et<=lo,'equity']
    initial=float(before.iloc[-1]) if len(before) else capital
    path=np.r_[initial,part]
    winners=float(c.loc[c.net_pnl>0,'net_pnl'].sum())
    losses=float(-c.loc[c.net_pnl<0,'net_pnl'].sum())
    cash=float(c.net_pnl.sum())
    return dict(trades=len(c),net_pnl=float(path[-1]-initial),closed_net=cash,
        double_cost_closed_net=float((c.net_pnl-c.cost).sum()),mean_net_r=float(c.net_r.mean()) if len(c) else None,
        profit_factor=winners/losses if losses else None,win_rate=float((c.net_pnl>0).mean()) if len(c) else None,
        max_drawdown=float((np.maximum.accumulate(path)-path).max()),cost=float(c.cost.sum()),
        median_risk_cash=float(c.risk_cash.median()) if len(c) else None,
        net_without_top5=cash-float(c.nlargest(5,'net_pnl').loc[lambda f:f.net_pnl>0,'net_pnl'].sum()))

def week_arrays(trades,bounds):
    lo,hi=(pd.Timestamp(x,tz='UTC') for x in bounds)
    first=(lo-pd.Timedelta(days=lo.weekday())).normalize()
    last=(hi-pd.Timedelta(nanoseconds=1))
    n=int((last-first).days//7)+1
    sums=np.zeros((n,len(trades)))
    counts=np.zeros_like(sums)
    for k,t in enumerate(trades):
        c=t.loc[cohort_mask(t,lo,hi)]
        x=pd.to_datetime(c.exit_time,utc=True)-pd.to_timedelta(c.exit_reason.isin(['contract-roll','end-of-test']).astype(int),unit='ns')
        ix=((x-first).dt.total_seconds()//(7*86400)).astype(int).to_numpy()
        np.add.at(sums[:,k],ix,c.net_r.to_numpy())
        np.add.at(counts[:,k],ix,1)
    return sums,counts

def block_weights(n,reps,rng,length=4):
    length=min(length,n)
    starts=rng.integers(0,n-length+1,size=(reps,int(np.ceil(n/length))))
    ix=(starts[:,:,None]+np.arange(length)).reshape(reps,-1)[:,:n]
    weights=np.zeros((reps,n))
    np.add.at(weights,(np.repeat(np.arange(reps),n),ix.ravel()),1)
    return weights

def simultaneous_contrasts(cases,trades,periods,reps=10000):
    rng=np.random.default_rng(20260925)
    baseline={c['symbol']:i for i,c in enumerate(cases) if c['variant']=='baseline'}
    variants=[i for i,c in enumerate(cases) if c['variant']!='baseline']
    base_ix=[baseline[cases[i]['symbol']] for i in variants]
    records,draws=[],[]
    full_bounds=periods['all']
    master_sums,_=week_arrays(trades,full_bounds)
    master_weights=block_weights(len(master_sums),reps,rng)
    master_start=pd.Timestamp(full_bounds[0],tz='UTC')
    master_start=(master_start-pd.Timedelta(days=master_start.weekday())).normalize()
    for period,bounds in periods.items():
        sums,counts=week_arrays(trades,bounds)
        period_start=pd.Timestamp(bounds[0],tz='UTC')
        period_start=(period_start-pd.Timedelta(days=period_start.weekday())).normalize()
        offset=int((period_start-master_start).days//7)
        # One shared full-calendar bootstrap draw preserves dependence between
        # nested full/later samples as well as between markets and policies.
        weights=master_weights[:,offset:offset+len(sums)]
        denominators=weights@counts
        means=np.divide(weights@sums,denominators,out=np.full_like(denominators,np.nan),where=denominators>0)
        totals=counts.sum(axis=0)
        obs=np.divide(sums.sum(axis=0),totals,out=np.full(len(totals),np.nan),where=totals>0)
        diff=means[:,variants]-means[:,base_ix]
        for j,i in enumerate(variants):
            records.append(dict(symbol=cases[i]['symbol'],variant=cases[i]['variant'],period=period,
                delta_mean_r=float(obs[i]-obs[base_ix[j]]),calendar_weeks=len(sums),
                usable_bootstraps=int(np.isfinite(diff[:,j]).sum())))
        draws.append(diff)
    boot=np.concatenate(draws,axis=1)
    center=np.array([x['delta_mean_r'] for x in records])
    sd=np.nanstd(boot,axis=0,ddof=1)
    usable=np.isfinite(boot).mean(axis=0)
    valid=np.isfinite(center)&np.isfinite(sd)&(sd>1e-12)&(usable>=.99)
    complete=np.isfinite(boot[:,valid]).all(axis=1)
    calibrated=bool(valid.any() and complete.mean()>=.95)
    critical=None
    if calibrated:
        maxima=np.max(np.abs((boot[complete][:,valid]-center[valid])/sd[valid]),axis=1)
        critical=float(np.quantile(maxima,.95))
    for j,r in enumerate(records):
        if not valid[j] or not calibrated:
            r.update(ci_low=None,ci_high=None,standard_error=None,estimability='Unavailable: empty/sparse sample, degenerate variance, or excessive jointly invalid draws')
            if not np.isfinite(center[j]): r['delta_mean_r']=None
        else:
            r.update(ci_low=float(center[j]-critical*sd[j]),ci_high=float(center[j]+critical*sd[j]),standard_error=float(sd[j]),estimability='estimable')
    return records,dict(seed=20260925,replicates=reps,block_weeks=4,family_size=len(records),jointly_usable=int(complete.sum()),critical_value=critical,
        estimable_comparisons=int(valid.sum()),calibrated=calibrated,jointly_discarded_fraction=float(1-complete.mean()),
        method='Noncircular moving-block full-calendar-week bootstrap; same weights restricted to later weeks preserve nested-period dependence. Simultaneous max-standardized-deviation intervals. Full and later periods share a single 88-comparison maximum. Require99% usable draws per contrast and95% jointly; degenerate variance unavailable. Approximate retrospective inference, not a correction for earlier adaptive research.')

def fmt(x,d=2):
    return 'n/a' if x is None or not np.isfinite(x) else f'{x:,.{d}f}'

def table(headers,rows):
    return '\n'.join(['| '+' | '.join(headers)+' |','| '+' | '.join(['---']*len(headers))+' |']+['| '+' | '.join(map(str,r))+' |' for r in rows])

def main():
    p=read(OUT/'protocol.json')
    manifest=driver.verify_source(OUT)
    for d in p['datasets']:
        for f in d['files']: assert checksum(f['path'])==f['checksum']
    periods={'all':['2022-01-01','2026-08-01'],**p['periods']}
    rows,trades,checks=[],[],[]
    for c in p['cases']:
        folder=OUT/c['symbol']/c['variant']
        r=read(folder/'result.json')
        if r['status']!='succeeded': raise ValueError('Campaign contains failed/incomplete case: '+str(folder))
        assert r['protocol_checksum']==manifest['protocol_checksum'] and r['source_hash']==manifest['source_hash']
        inp=read(folder/'input.json')
        assert all(inp[k]==v for k,v in c.items())
        for a in r['artifacts']: assert checksum(folder/a['name'])==a['checksum']
        t,e=pd.read_csv(folder/'trades.csv'),pd.read_parquet(folder/'equity.parquet')
        np.testing.assert_allclose(e.equity.iloc[-1]-p['capital'],t.net_pnl.sum(),rtol=0,atol=1e-5)
        np.testing.assert_allclose(t.gross_pnl-t.cost,t.net_pnl,rtol=0,atol=1e-6)
        np.testing.assert_allclose(t.net_pnl/t.risk_cash,t.net_r,rtol=0,atol=1e-10)
        assert (pd.to_datetime(t.exit_time,utc=True)>=pd.to_datetime(t.entry_time,utc=True)).all()
        for name,bounds in periods.items(): rows.append(dict(symbol=c['symbol'],variant=c['variant'],period=name,**metrics(t,e,bounds,p['capital'])))
        trades.append(t)
        checks.append(dict(symbol=c['symbol'],variant=c['variant'],status='verified',trades=len(t),quality_rejections=r['diagnostics'].get('quality_rejections_at_signal',0)))
    comparisons,method=simultaneous_contrasts(p['cases'],trades,{'all':periods['all'],'later':periods['later']})
    df=pd.DataFrame(rows)
    idx={(x['symbol'],x['variant'],x['period']):x for x in rows}
    for r in comparisons:
        x=idx[r['symbol'],r['variant'],r['period']]
        b=idx[r['symbol'],'baseline',r['period']]
        r.update(trades=x['trades'],delta_closed_net=x['closed_net']-b['closed_net'],delta_double_cost_net=x['double_cost_closed_net']-b['double_cost_closed_net'],
            passes_declared_candidate_check=bool(r['period']=='later' and x['trades']>=100 and x['mean_net_r'] is not None and x['mean_net_r']>0 and x['double_cost_closed_net']>0 and r['ci_low'] is not None and r['ci_low']>0))
    df.to_csv(OUT/'all-results.csv',index=False)
    pd.DataFrame(comparisons).to_csv(OUT/'factor-contrasts.csv',index=False)
    save(OUT/'analysis.json',dict(cases=checks,metrics=rows,contrasts=comparisons,uncertainty=method))
    save(OUT/'verification.json',dict(status='passed',checks=checks,source_hash=manifest['source_hash'],protocol_checksum=manifest['protocol_checksum']))
    snapshot=OUT/'analysis-source'/('report-snd-zone-quality-'+checksum(__file__)[:16]+'.py')
    snapshot.parent.mkdir(exist_ok=True)
    shutil.copy2(__file__,snapshot)
    lines=['# Supply/demand zone quality: bounded historical comparison','',
        'All 48 declared stateful simulations completed. No filters were combined or thresholds selected after results. These are January 2022–July 2026 retrospective checks on previously inspected history; they are not a fresh holdout.',
        '',f"The declared candidate criterion passed for {sum(r['passes_declared_candidate_check'] for r in comparisons)} of 44 later-period contrasts. A pass would require at least 100 later trades, positive mean net R, positive cash profit at doubled costs, and a simultaneous uncertainty interval supporting improvement over baseline. Passing this retrospective criterion would still require independent confirmation.",
        '', 'Dollar P&L uses one contract; mean R divides each net trade by its initial stop risk. They answer different questions. An improved mean R can remain negative. Reported yearly trade cohorts use exit dates; positions can cross period boundaries. Marked P&L separately includes boundary-crossing exposure.',
        '', '## Baselines across markets','',table(['Market','Trades','Net $','PF','Mean net R','Doubled costs $','Max drawdown $'],[
            [s,x['trades'],fmt(x['net_pnl']),fmt(x['profit_factor'],3),fmt(x['mean_net_r'],4),fmt(x['double_cost_closed_net']),fmt(x['max_drawdown'])]
            for s in ['MNQ','MGC','ES','CL'] for x in [idx[s,'baseline','all']]]),
        '', '## Every factor, full history','', 'ATR is the mean true range of 20 complete five-minute candles before the three-candle formation. Departure measures the middle candle body. Volume is a trailing ratio, not seasonally adjusted RVOL. Age is elapsed time from formation confirmation to entry arming.', '']
    for s in ['MNQ','MGC','ES','CL']:
        lines += ['### '+s,'',table(['Variant','Trades','Net $','Mean net R','Double cost $','Drawdown $'],[
            [x['variant'],x['trades'],fmt(x['net_pnl']),fmt(x['mean_net_r'],4),fmt(x['double_cost_closed_net']),fmt(x['max_drawdown'])]
            for x in rows if x['symbol']==s and x['period']=='all']),'']
    lines += ['## Later stability and multiple comparisons','',
        'Later means January 2025–July 2026. Intervals below cover the variant-minus-baseline mean net R contrast. The four-week moving-block bootstrap retains empty calendar weeks, pairs baseline/variant weeks, and applies a simultaneous correction across all 88 full/later contrasts. It does not account for the entire earlier research search. Blocks are a dependence approximation; long holds and regime changes remain limitations.','',
        table(['Market','Variant','Later trades','Later net $','Later mean R','Delta R','Simultaneous 95% interval'],[
            [r['symbol'],r['variant'],r['trades'],fmt(idx[r['symbol'],r['variant'],'later']['net_pnl']),fmt(idx[r['symbol'],r['variant'],'later']['mean_net_r'],4),fmt(r['delta_mean_r'],4),f"[{fmt(r['ci_low'],4)}, {fmt(r['ci_high'],4)}]"] for r in comparisons if r['period']=='later']),
        '', 'Every period and metric is in [all-results.csv](all-results.csv); all contrasts are in [factor-contrasts.csv](factor-contrasts.csv). Separate 2022–2023, 2024, 2025 and January–July 2026 slices are retained. [Protocol](protocol.json) specifies the complete family and inference before results.',
        '', '## Interpretation boundaries','',
        'The baseline uses relaxed displacement, wick zones, confirmed five-minute and hourly direction, first physical touch, a five-minute stop-entry lifetime, one-tick zone stop buffer, 1R target, and at least 2R opposing room. Strict FVG, hourly removal, and room removal each change one rule. Formation filters preserve context zones. Filtering changes later position availability, so contrasts are strategy-policy effects rather than identical-trade causal effects.',
        '', 'Baseline costs are $1.25 per side for MNQ/MGC and $2.50 for ES/CL, plus one tick of cash slippage on entry and stop/market exits; target limits pay fees only. Double-cost figures subtract the recorded cost again. Fixed-contract decisions are cost-independent, making that repricing exact for unchanged fills. Adverse fill mechanics were tested separately in the prior entry campaign.',
        '', 'MNQ and ES are correlated equity exposure. Gold and crude offer different asset classes but do not establish universal transfer. OHLCV cannot prove institutional orders remain at a level. Continuous contracts, missing observations, idealized roll liquidation/gap cancellation, conservative minute-bar ambiguity, and no queue or margin model limit execution realism. This campaign does not establish that zones outperform matched arbitrary price levels.',
        '', 'See [primary-source literature](literature.md), the [prior rule audit](../supply-demand-rule-audit-2026-09-24/REPORT.md), and [entry mechanics](../snd-entry-research-2026-09-25/REPORT.md). Independent raw-candle audit is recorded separately in independent-audit.json. Existing strategy/Pine settings are preserved.']
    (OUT/'RESULTS.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.colors import TwoSlopeNorm
    variants=[c['variant'] for c in p['cases'] if c['symbol']=='MNQ']
    labels={'baseline':'Baseline','width_le05':'Width ≤ 0.5 ATR','width_le10':'Width ≤ 1.0 ATR',
            'departure_ge10':'Departure ≥ 1.0 ATR','departure_ge15':'Departure ≥ 1.5 ATR',
            'volume_ge15':'Volume ratio ≥ 1.5','volume_ge20':'Volume ratio ≥ 2.0',
            'age_le1h':'Age ≤ 1 hour','age_le4h':'Age ≤ 4 hours','without_room':'Remove opposing room',
            'without_hourly':'Remove hourly alignment','strict_fvg':'Require strict FVG'}
    fig,axs=plt.subplots(1,2,figsize=(13,7),layout='constrained')
    all_values=np.array([idx[s,v,q]['mean_net_r'] for q in ['all','later'] for v in variants for s in ['MNQ','MGC','ES','CL']],dtype=float)
    norm=TwoSlopeNorm(vmin=min(-.4,float(np.nanmin(all_values))),vcenter=0,vmax=max(.1,float(np.nanmax(all_values))))
    for ax,period,title in zip(axs,['all','later'],['2022–July 2026','2025–July 2026']):
        data=np.array([[idx[s,v,period]['mean_net_r'] for s in ['MNQ','MGC','ES','CL']] for v in variants],dtype=float)
        im=ax.imshow(data,cmap='RdYlGn',norm=norm)
        ax.set_xticks(range(4),['MNQ','MGC','ES','CL'])
        ax.set_yticks(range(len(variants)),[labels[v] for v in variants])
        ax.set_title(title)
        for i in range(len(variants)):
            for j,s in enumerate(['MNQ','MGC','ES','CL']):
                ax.text(j,i,f"{data[i,j]:.3f}\nn={idx[s,variants[i],period]['trades']}",ha='center',va='center',fontsize=7)
        fig.colorbar(im,ax=ax,shrink=.7,label='Mean net R / trade')
    fig.suptitle('Supply/demand quality factors: per-risk results after costs\nFixed thresholds; reused history; no optimized combination')
    fig.savefig(OUT/'factor-comparison.png',dpi=170)
    plt.close(fig)
    print(json.dumps(dict(cases=len(checks),contrasts=len(comparisons),candidate_checks_passed=sum(r['passes_declared_candidate_check'] for r in comparisons),uncertainty=method),indent=2))

if __name__=='__main__': main()
