"""Recompute the default inverse from raw bars and compare every output row."""
import hashlib
import json
import sys
from importlib.metadata import version
from pathlib import Path
import pandas as pd

root=Path(__file__).resolve().parents[1]
out=root/'reports/vwap-inverse-2026-09-17'
rid='403829a6-2b3c-461e-93a3-6bd62a776b49'
request=json.loads((root/'data/workbench/runs'/rid/'input.json').read_text())
source=Path(request['source_dir'])
sys.path.insert(0,str(source))
from strategy_engine.data import session_bars
from strategy_engine.sessions import get_session
from strategies.vwap_reversion import signals
from workbench.worker import simulate

sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
assert sha(Path(request['dataset']['path']))==request['dataset']['checksum']
for name,digest in json.loads((source/'sources.json').read_text()).items():assert sha(source/name)==digest
for package in json.loads((source/'environment.json').read_text())['dependencies']:assert version(package['name'])==package['version']
print('Preserved data, source and environment verified',flush=True)
start=pd.Timestamp(request['start'],tz='UTC')-pd.Timedelta(days=request['warmup_days'])
end=pd.Timestamp(request['end'],tz='UTC')+pd.Timedelta(days=1)
raw=pd.read_parquet(request['dataset']['path'],filters=[('ts_event','>=',start),('ts_event','<',end)])
bars=session_bars(raw,get_session(request['session']),request['timeframe'])
print(f'Built {len(bars):,} bars; computing negated signals and independent accounting',flush=True)
targets=-signals(bars.copy(),request['parameters'])
equity,trades,positions=simulate(bars,targets,request)
fresh=out/'raw-bar-verification';fresh.mkdir(exist_ok=True)
artifacts=[]
for name,frame in [('equity',equity),('trades',trades),('positions',positions)]:
    expected=pd.read_csv(out/rid/f'{name}.csv')
    pd.testing.assert_frame_equal(frame.reset_index(drop=True),expected,check_dtype=False,check_exact=False,rtol=1e-12,atol=1e-8)
    path=fresh/f'{name}.csv';frame.to_csv(path,index=False)
    artifacts.append({'name':name,'rows':len(frame),'checksum':sha(path)})
result={'status':'Passed','original_run_id':rid,'source_hash':request['source_hash'],'test':'Independent raw-bar signal inversion and canonical engine simulation match every derived equity, trade and position row.','net_pnl':float(trades.net_pnl.sum()),'trades':len(trades),'bars':len(equity),'artifacts':artifacts}
(out/'raw-bar-verification.json').write_text(json.dumps(result,indent=2))
print(json.dumps(result),flush=True)
