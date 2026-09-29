"""Verify frozen candidate artifacts and recompute risk from complete minute paths."""
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
folder = Path(sys.argv[1]).resolve()
campaign = json.loads((folder / 'campaign.json').read_text())
status = json.loads((folder / 'latest-status.json').read_text())
replica = '--replica' in sys.argv
native_home = ROOT / 'data/workbench'
if replica:
    replication = json.loads((folder / 'replication.json').read_text())
    native_home = Path(replication['home'])
    native_status = json.loads((folder / 'replication-status.json').read_text())
    status['native'] = [dict(id=r['id'], status=r['status']) for r in native_status['runs']]
cache = folder / 'audits'
cache.mkdir(exist_ok=True)


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def path_metrics(paths, capital=100000):
    peak = capital
    ending = capital
    worst = 0.0
    worst_dollars = 0.0
    worst_time = None
    yearly = {}
    rows = 0
    previous_time = None
    for path in paths:
        offset = ending - capital
        for chunk in pd.read_csv(path, usecols=['timestamp', 'equity', 'net_pnl'], chunksize=250000):
            times = pd.to_datetime(chunk.timestamp, utc=True)
            assert times.is_monotonic_increasing and not times.duplicated().any()
            assert previous_time is None or times.iloc[0] > previous_time
            previous_time = times.iloc[-1]
            values = chunk.equity.to_numpy(dtype=float) + offset
            assert np.isfinite(values).all()
            assert abs((ending + chunk.net_pnl.sum()) - values[-1]) < 1e-5
            peaks = np.maximum.accumulate(np.r_[peak, values])[1:]
            dd = values / peaks - 1
            idx = int(np.argmin(dd))
            if dd[idx] < worst:
                worst = float(dd[idx])
                worst_time = str(times.iloc[idx])
            worst_dollars = max(worst_dollars, float((peaks - values).max()))
            peak = float(peaks[-1])
            ending = float(values[-1])
            rows += len(chunk)
            for year, pnl in chunk.net_pnl.groupby(times.dt.year).sum().items():
                yearly[str(year)] = yearly.get(str(year), 0.0) + float(pnl)
    return dict(net_pnl=ending-capital, max_drawdown=worst, max_drawdown_dollars=worst_dollars,
                trough_utc=worst_time, observations=rows, yearly_pnl=yearly)


audits = []
for row in [*status['continuous'], *status['native']]:
    if row['status'] != 'Succeeded':
        continue
    run_id = row['id']
    run_folder = (native_home if row in status['native'] else ROOT / 'data/workbench') / 'runs' / run_id
    manifest_path = run_folder / 'manifest.json'
    manifest_hash = digest(manifest_path)
    cached = cache / f'{run_id}.json'
    if cached.exists():
        audit = json.loads(cached.read_text())
        assert audit['manifest_checksum'] == manifest_hash
        audits.append(audit)
        continue
    manifest = json.loads(manifest_path.read_text())
    inp = json.loads((run_folder / 'input.json').read_text())
    assert inp['strategy']['file_hash'] == campaign['source']['adapter']
    snapshot = Path(inp['source_dir'])
    assert digest(snapshot / 'strategies/short_term_reversal_minute.py') == campaign['source']['adapter']
    assert digest(snapshot / 'strategies/short_term_reversal.py') == campaign['source']['daily_helper']
    assert inp['dataset']['checksum'] == campaign['dataset']['checksum']
    for artifact in manifest['artifacts']:
        assert digest(run_folder / artifact['name']) == artifact['checksum'], (run_id, artifact['name'])
    trades = pd.read_csv(run_folder / 'trades.csv')
    pnl = trades.net_pnl
    assert np.allclose((trades.exit-trades.entry)*trades.quantity*inp['dataset']['point_value']-trades.cost, pnl)
    m = path_metrics([run_folder / 'equity.csv'], inp['capital'])
    assert abs(pnl.sum()-m['net_pnl']) < 1e-5
    assert abs(m['net_pnl']-manifest['metrics']['net_pnl']) < 1e-5
    assert abs(m['max_drawdown']-manifest['metrics']['max_drawdown']) < 1e-10
    assert len(trades) == manifest['metrics']['trades']
    loss = -float(pnl[pnl < 0].sum())
    audit = dict(id=run_id, offset=inp['parameters']['open_delay_minutes'], fee=inp['fee'], slippage=inp['slippage'],
                 research=inp.get('research'), source_hash=inp['source_hash'], manifest_checksum=manifest_hash,
                 **m, trades=len(trades), profit_factor=float(pnl[pnl > 0].sum())/loss if loss else None,
                 win_rate=float((pnl > 0).mean()) if len(trades) else None,
                 largest_loss=float(pnl.min()) if len(trades) else None,
                 net_without_best_10_trades=float(pnl.sum()-pnl.nlargest(10).sum()),
                 passed=m['net_pnl'] > 0 and len(trades) >= 60 and abs(m['max_drawdown']) <= .2)
    cached.write_text(json.dumps(audit, indent=2))
    audits.append(audit)
    print(f'Verified {run_id}: offset {audit["offset"]}, {len(trades)} trades, net {m["net_pnl"]:,.2f}, DD {abs(m["max_drawdown"]):.2%}', flush=True)

report = dict(verified_runs=len(audits), runs=audits, scenarios=[])
evaluation_file = folder / ('replication-evaluation.json' if replica else 'evaluation.json')
if evaluation_file.exists():
    evaluation = json.loads(evaluation_file.read_text())
    for scenario in evaluation.get('result', {}).get('scenarios', []):
        children = sorted([a for a in audits if a['research'] and a['research']['role'] == 'Test' and a['research']['scenario'] == scenario['name']], key=lambda a: a['research']['fold'])
        assert len(children) == 6
        metrics = path_metrics([native_home / 'runs' / r['id'] / 'equity.csv' for r in children])
        assert abs(metrics['net_pnl']-scenario['metrics']['net_pnl']) < 1e-5
        assert abs(metrics['max_drawdown']-scenario['metrics']['max_drawdown']) < 1e-10
        report['scenarios'].append(dict(name=scenario['name'], outcome=scenario['outcome'], **metrics, trades=sum(r['trades'] for r in children)))
(folder / ('replication-audit.json' if replica else 'audit.json')).write_text(json.dumps(report, indent=2))
print(json.dumps({'verified_runs': len(audits), 'scenarios': report['scenarios']}, indent=2))
