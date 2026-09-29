"""Isolated frozen-source replays; never write to app-owned run folders or database."""
import json
import subprocess
import sys
import uuid
from pathlib import Path

root = Path(__file__).resolve().parents[1]
out = root / 'reports/vwap-full-2026-09-17'
evaluation = json.loads((out / 'evaluation.json').read_text())
records = []
for run in evaluation['runs']:
    if run['input']['research']['role'] != 'Test':
        continue
    identifier = str(uuid.uuid4())
    folder = out / 'local-replays' / identifier
    folder.mkdir(parents=True)
    request = dict(run['input'])
    request['id'] = identifier
    request['research'] = {**request['research'], 'execution_location': 'isolated local replay', 'queued_workbench_run_id': run['id']}
    path = folder / 'input.json'
    path.write_text(json.dumps(request, indent=2))
    record = dict(id=identifier, status='Running', input=request, artifact_dir=str(folder), queued_workbench_run_id=run['id'])
    print(f"Replaying {request['research']['scenario']} from frozen source", flush=True)
    with (folder / 'process.log').open('w') as log:
        result = subprocess.run([sys.executable, '-m', 'workbench.worker', str(path)], cwd=request['source_dir'], stdout=log, stderr=subprocess.STDOUT, timeout=1800)
    if result.returncode == 0 and (folder / 'manifest.json').exists():
        record['status'] = 'Succeeded'
        record['result'] = json.loads((folder / 'manifest.json').read_text())
        metrics = record['result']['metrics']
        record['declared_criteria_passed'] = metrics['net_return'] >= 0 and abs(metrics['max_drawdown']) <= .35 and metrics['trades'] >= 100
        print(json.dumps({'scenario':request['research']['scenario'], 'pnl':metrics['net_pnl'], 'drawdown':metrics['max_drawdown'], 'trades':metrics['trades'], 'criteria_passed':record['declared_criteria_passed']}), flush=True)
    else:
        record['status'] = 'Failed'
        record['error'] = (folder / 'process.log').read_text()
    records.append(record)
    (out / 'local-replays.json').write_text(json.dumps(records, indent=2))
assert len(records) == 3 and all(r['status'] == 'Succeeded' for r in records)
