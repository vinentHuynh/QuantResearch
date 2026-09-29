"""Read-only full-artifact audit and research summary; never changes run evidence."""
import csv
import hashlib
import json
from pathlib import Path
from urllib.request import urlopen
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'reports/workbench-review-2026-09-16'
OUT.mkdir(parents=True, exist_ok=True)
state = json.load(urlopen('http://127.0.0.1:8001/api/workbench/state'))
(OUT / 'state-after.json').write_text(json.dumps(state), encoding='utf-8')
rows, failures, annual = [], [], []
dataset_checks = []
for dataset in state['datasets']:
    digest = hashlib.sha256()
    with Path(dataset['path']).open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    dataset_checks.append(dict(symbol=dataset['symbol'], id=dataset['id'], verified=digest.hexdigest() == dataset['checksum'],
                               rows=dataset['rows'], first=dataset['first'], last=dataset['last']))
for index, run in enumerate(state['runs']):
    inp = run['input']
    row = dict(id=run['id'], status=run['status'], strategy=inp['strategy']['id'], symbol=inp['dataset']['symbol'],
               timeframe=inp['timeframe'], start=inp['start'], end=inp['end'], warmup_days=inp['warmup_days'], parameters=json.dumps(inp['parameters'], sort_keys=True))
    try:
        if run['status'] != 'Succeeded':
            raise ValueError(run.get('error') or run['status'])
        folder = ROOT / 'data/workbench/runs' / run['id']
        manifest = json.loads((folder / 'manifest.json').read_text())
        for artifact in manifest['artifacts']:
            digest = hashlib.sha256()
            with (folder / artifact['name']).open('rb') as handle:
                for block in iter(lambda: handle.read(1024 * 1024), b''):
                    digest.update(block)
            assert digest.hexdigest() == artifact['checksum'], artifact['name'] + ' checksum mismatch'
        trades = pd.read_csv(folder / 'trades.csv')
        equity = pd.read_csv(folder / 'equity.csv', usecols=['timestamp', 'equity'])
        pnl = pd.to_numeric(trades.net_pnl).astype(float)
        net = float(pnl.sum())
        assert np.isclose(net, manifest['metrics']['net_pnl'], atol=.0001, rtol=0), 'Trade P&L mismatch'
        assert np.isclose(float(equity.equity.iloc[-1]) - inp['capital'], net, atol=.0001, rtol=0), 'Equity mismatch'
        wins, losses = pnl[pnl > 0], pnl[pnl < 0]
        row.update(verified=True, net_pnl=net, trades=len(trades), costs=manifest['metrics']['costs'],
                   drawdown=manifest['metrics']['max_drawdown'], sharpe=manifest['metrics']['sharpe'],
                   profit_factor=float(wins.sum() / -losses.sum()) if len(losses) else None,
                   win_rate=float((pnl > 0).mean()) if len(trades) else None,
                   expectancy=float(pnl.mean()) if len(trades) else None,
                   without_best_five=float(net - pnl.nlargest(5).sum()), insolvent=bool((equity.equity <= 0).any()))
        year_pnl = equity.equity.diff()
        year_pnl.iloc[0] = equity.equity.iloc[0] - inp['capital']
        for year, amount in year_pnl.groupby(pd.to_datetime(equity.timestamp, utc=True).dt.year).sum().items():
            annual.append(dict(id=run['id'], strategy=row['strategy'], symbol=row['symbol'], timeframe=row['timeframe'], year=int(year), marked_pnl=float(amount)))
    except Exception as error:
        row.update(verified=False, error=str(error))
        failures.append(dict(id=run['id'], error=str(error)))
    rows.append(row)
    if (index + 1) % 25 == 0:
        print(f'Audited {index + 1}/{len(state["runs"])} runs; issues {len(failures)}', flush=True)
pd.DataFrame(rows).to_csv(OUT / 'all-runs-audited.csv', index=False)
pd.DataFrame(annual).to_csv(OUT / 'annual-marked-pnl.csv', index=False)
pd.DataFrame(state['library']['entries']).to_csv(OUT / 'source-inventory.csv', index=False)
summary = dict(runs=len(rows), verified=sum(r.get('verified', False) for r in rows), failures=failures,
               datasets=len(state['datasets']), strategies=len(state['strategies']), source_files=len(state['library']['entries']),
               evaluations=len(state['evaluations']), regimes=len(state['regimes']), dataset_checks=dataset_checks)
(OUT / 'artifact-audit.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
print(json.dumps(summary), flush=True)
