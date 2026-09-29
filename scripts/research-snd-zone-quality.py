"""Declare, freeze, and run a bounded supply/demand zone quality comparison."""
from __future__ import annotations
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import platform
import shutil
import sys
import time
import traceback
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'reports/snd-zone-quality-2026-09-25'
PRIOR = ROOT / 'reports/snd-fresh-retest-2026-09-24'

def now():
    return datetime.now(timezone.utc).isoformat()

def checksum(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda: f.read(1048576), b''):
            h.update(b)
    return h.hexdigest()

def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))

def save(path, obj):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(obj, indent=2, default=str, allow_nan=False), encoding='utf-8')

def declare(out):
    path = out / 'protocol.json'
    if path.exists():
        return read(path)
    previous = read(PRIOR / 'protocol.json')
    datasets = [next(d for d in previous['datasets'] if d['symbol'] == s) for s in ['MNQ','MGC','ES','CL']]
    variants = [
        ('baseline', {}, 'Reference'),
        ('width_le05', {'max_zone_width_atr': .5}, 'Narrower zone'),
        ('width_le10', {'max_zone_width_atr': 1.}, 'Width neighbor'),
        ('departure_ge10', {'min_departure_atr': 1.}, 'Stronger middle candle'),
        ('departure_ge15', {'min_departure_atr': 1.5}, 'Departure neighbor'),
        ('volume_ge15', {'min_departure_rvol': 1.5}, 'Higher middle-candle relative volume'),
        ('volume_ge20', {'min_departure_rvol': 2.}, 'Volume neighbor'),
        ('age_le1h', {'max_touch_age_hours': 1.}, 'Younger first-touch zone'),
        ('age_le4h', {'max_touch_age_hours': 4.}, 'Age neighbor'),
        ('without_room', {'min_opposing_room_r': 0.}, 'Remove opposing room'),
        ('without_hourly', {'use_htf': False}, 'Remove hourly alignment'),
        ('strict_fvg', {'require_fvg': True}, 'Require strict wick gap'),
    ]
    cases = []
    for d in datasets:
        original = next(c for c in previous['cases'] if c['symbol'] == d['symbol'] and c['variant'] == 'candidate')
        base = original['parameters'] | dict(require_fvg=False, entry_eligibility='first_touch', order_lifetime_bars=1, slippage_model='cash',
            max_zone_width_atr=None, min_departure_atr=None, min_departure_rvol=None, max_touch_age_hours=None)
        for name, changes, hypothesis in variants:
            cases.append(dict(symbol=d['symbol'], variant=name, hypothesis=hypothesis, parameters=base | changes,
                              fee=original['fee'], slippage_ticks=1))
    p = dict(declared_at=now(), question='Which candle-derived zone characteristics improve a fixed causal first-touch strategy across time and markets?',
        expected_cases=len(cases), datasets=datasets, cases=cases, capital=100000.,
        primary_market='MNQ', transfer_markets=['MGC','ES','CL'],
        periods={'early_2022_23':['2022-01-01','2024-01-01'], 'year_2024':['2024-01-01','2025-01-01'],
                 'year_2025':['2025-01-01','2026-01-01'], 'year_2026':['2026-01-01','2026-08-01'],
                 'later':['2025-01-01','2026-08-01']},
        selection='No fitting, ranking-based promotion, composite filter search, or post-result threshold changes. All 48 cases retained. Thresholds are coarse hypotheses, not optimized values.',
        prior_exposure='All scored history has been inspected in earlier repository research. Chronological slices are retrospective stability checks, never untouched holdouts. Baseline relaxed-FVG choice was informed by prior MNQ results.',
        features={
            'prior_atr20':'Mean of 20 complete 5m true ranges strictly before base open, using preceding same-contract complete close; no cross-roll history.',
            'zone_width_atr':'Wick zone width / prior_atr20.',
            'departure_atr':'Absolute middle-candle close minus open / prior_atr20. It is body displacement, not order-flow imbalance.',
            'departure_rvol':'Middle volume / mean of 20 complete 5m volumes before base. Simple trailing ratio, NOT seasonally adjusted RVOL.',
            'signal_age_hours':'Elapsed hours from zone confirmation to arming close, including closures. This tests first-touch age, not number of previous touches.'},
        execution='Same isolated entry engine: 5m completed formation, completed-hour alignment, causal pivots2, wick boundaries, relaxed close displacement, first physical touch only, stop entry next five minutes, zone stop, target1R, opposing room2R. One fixed contract. One-minute conservative stop-first ambiguity. Existing context zones unaffected by feature filters. Filters apply at arming, missing required features reject. All rules except each declared change fixed.',
        costs='Baseline per-side fees MNQ/MGC1.25, ES/CL2.50, one tick cash slippage on entry and nonlimit exit. Double total cash costs on saved trades as deterministic stress; fixed-contract decisions are cost-independent. This does not simulate different fills.',
        uncertainty=dict(method='Paired calendar-week moving-block bootstrap, blocks of4 consecutive weeks, seed20260925, 10000 replicates. Same resampled weeks for baseline and variants and across markets. Empty weeks retained. Compare variant minus baseline mean net R.',
            family='44 baseline contrasts in full and later history =88 comparisons, simultaneous95% max-standardized-deviation intervals within this campaign only. Does not correct the entire previous adaptive research history.',
            boundary='Exit cohorts use source-open times except contract-roll/end-of-test close timestamps; zero-denominator samples invalid; record usable replicates.',
            evidence_rule='Candidate evidence requires >=100 later trades, positive later mean netR, positive later cash PnL at double costs, and positive simultaneous interval lower bound for improvement over baseline. Neighbor and market consistency assessed without choosing winners.'),
        verification='All source/data/output hashes; per-case accounting/chronology/filter gates; exact common-column baseline parity to prior relaxed MNQ/MGC and strict controls on all4; raw-candle feature reconstruction. All failed and zero-trade attempts visible.',
        limitations='OHLCV cannot identify remaining orders or institutions. Retrospective reused data, correlated MNQ/ES, continuous unadjusted rolls, imperfect missing-bar metadata, idealized roll liquidation and gap cancellation, no queue or margin model, fixed contracts not equal risk. Study is conditional on this zone definition, not proof against matched arbitrary levels.',
        isolated_reason='Native Workbench event-v1 lacks the required stop-entry lifecycle; preserve source/input/ledger traceability separately.')
    save(path, p)
    print(f'Declared {len(cases)} cases at {path}', flush=True)
    return p

def load_market(d):
    lo, hi = pd.Timestamp(d['start'],tz='UTC')-pd.Timedelta(days=30), pd.Timestamp(d['end'],tz='UTC')
    frames=[]
    for item in d['files']:
        assert checksum(item['path']) == item['checksum'], 'Dataset changed'
        f=pd.read_parquet(item['path'])
        f.index=pd.to_datetime(f.index,utc=True)
        frames.append(f.loc[(f.index>=lo)&(f.index<hi)].copy())
    frame=pd.concat(frames).sort_index()
    assert len(frame) and frame.index.is_unique
    return frame

def preview(out,p):
    rows=[]
    for d in p['datasets']:
        f=load_market(d)
        a=f[['open','high','low','close']].to_numpy(float)
        assert np.isfinite(a).all() and not (a[:,1]<a.max(axis=1)).any() and not (a[:,2]>a.min(axis=1)).any()
        assert 'volume' in f and np.isfinite(f.volume).all() and (f.volume>=0).all()
        assert f.index[0] < pd.Timestamp(d['start'],tz='UTC')
        rows.append(dict(symbol=d['symbol'], rows=len(f), first=str(f.index[0]),last=str(f.index[-1])))
    save(out/'preview.json',dict(status='passed',checked_at=now(),protocol_checksum=checksum(out/'protocol.json'),datasets=rows))
    print(json.dumps(rows),flush=True)

def freeze(out):
    if (out/'source-manifest.json').exists():
        return verify_source(out)
    paths=['scripts/research-snd-zone-quality.py','strategies/_snd_zone_quality.py','strategies/_snd_entry_research.py',
           'tests/test_snd_zone_quality.py','tests/test_snd_entry_research.py']
    paths += [str(x.relative_to(ROOT)).replace('\\','/') for x in (ROOT/'strategy_engine').glob('*.py')]
    files=[]
    for name in paths:
        src,dst=ROOT/name,out/'source'/name
        dst.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(src,dst)
        files.append(dict(path=name,checksum=checksum(src)))
    digest=hashlib.sha256(json.dumps(files,sort_keys=True).encode()).hexdigest()
    save(out/'source-manifest.json',dict(frozen_at=now(),protocol_checksum=checksum(out/'protocol.json'),source_hash=digest,files=files))
    save(out/'environment.json',dict(python=sys.version,platform=platform.platform(),numpy=np.__version__,pandas=pd.__version__))
    return verify_source(out)

def verify_source(out):
    m=read(out/'source-manifest.json')
    assert checksum(out/'protocol.json') == m['protocol_checksum']
    for item in m['files']:
        assert checksum(out/'source'/item['path']) == item['checksum'], item['path']
    return m

def run_market(out_name,d):
    out=Path(out_name)
    p,m=read(out/'protocol.json'),verify_source(out)
    sys.path.insert(0,str(out/'source'))
    spec=importlib.util.spec_from_file_location('frozen_zone_quality',out/'source/strategies/_snd_zone_quality.py')
    model=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(model)
    prepared=model.prepare_data(load_market(d),pivot_len=2,execution_minutes=1)
    statuses=[]
    for case in [c for c in p['cases'] if c['symbol']==d['symbol']]:
        folder=out/case['symbol']/case['variant']
        if (folder/'result.json').exists():
            statuses.append(read(folder/'result.json')['status'])
            continue
        if folder.exists() and any(folder.iterdir()):
            raise RuntimeError('Preserve interrupted attempt; use new output directory: '+str(folder))
        folder.mkdir(parents=True,exist_ok=True)
        identity=dict(protocol_checksum=m['protocol_checksum'],source_hash=m['source_hash'])
        save(folder/'input.json',dict(**case,dataset=d,**identity))
        started,clock=now(),time.monotonic()
        save(folder/'status.json',dict(status='running',started_at=started))
        try:
            r=model.run_model(prepared,case['parameters'],d['start'],d['end'],d['tick_size'],d['point_value'],case['fee'],case['slippage_ticks'])
            t,e=r['trades'],r['equity']
            np.testing.assert_allclose(e.equity.iloc[-1]-p['capital'],t.net_pnl.sum(),atol=1e-5,rtol=0)
            np.testing.assert_allclose(e.net_pnl.sum(),t.net_pnl.sum(),atol=1e-5,rtol=0)
            np.testing.assert_allclose(t.gross_pnl-t.cost,t.net_pnl,atol=1e-7,rtol=0)
            assert e.contracts.iloc[-1]==0
            t.to_csv(folder/'trades.csv',index=False)
            e.to_parquet(folder/'equity.parquet',index=False)
            save(folder/'result.json',dict(status='succeeded',**case,diagnostics=r['diagnostics'],started_at=started,completed_at=now(),elapsed_seconds=time.monotonic()-clock,
                artifacts=[dict(name=n,checksum=checksum(folder/n)) for n in ['trades.csv','equity.parquet']],**identity))
            statuses.append('succeeded')
            print(f"{d['symbol']}/{case['variant']}: {len(t)} trades; net ${t.net_pnl.sum():,.2f}",flush=True)
        except Exception as error:
            (folder/'error.log').write_text(traceback.format_exc(),encoding='utf-8')
            save(folder/'result.json',dict(status='failed',error=str(error),started_at=started,completed_at=now(),**identity))
            statuses.append('failed')
            print(f"{d['symbol']}/{case['variant']}: FAILED {error}",flush=True)
        save(folder/'status.json',dict(status=statuses[-1],completed_at=now()))
    return dict(symbol=d['symbol'],statuses=statuses)

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output',type=Path,default=OUT)
    for a in ['declare','preview','freeze','run']:
        ap.add_argument('--'+a,action='store_true')
    ap.add_argument('--workers',type=int,choices=[1,2],default=2)
    args=ap.parse_args()
    out=args.output.resolve()
    p=declare(out) if args.declare else read(out/'protocol.json')
    if args.preview: preview(out,p)
    if args.freeze: freeze(out)
    if args.run:
        m=verify_source(out)
        check=read(out/'preview.json')
        assert check['status']=='passed' and check['protocol_checksum']==m['protocol_checksum']
        summaries=[]
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            for job in as_completed([pool.submit(run_market,str(out),d) for d in p['datasets']]):
                summaries.append(job.result())
        save(out/'completion.json',dict(completed_at=now(),markets=summaries))
        if any(s!='succeeded' for r in summaries for s in r['statuses']): raise SystemExit(1)
        print('All declared cases completed.',flush=True)

if __name__=='__main__': main()
