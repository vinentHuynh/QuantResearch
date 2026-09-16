import contextlib
import importlib.util
import io
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('collective_import', Path(__file__).parents[1] / 'scripts/build-collective.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class CollectiveImportTests(unittest.TestCase):
    def test_new_workbench_baseline_uses_real_capital_and_rejects_corruption(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); state = root / 'data'; run = state / 'runs' / 'new-run'; run.mkdir(parents=True)
            source = root / 'strategy.py'; source.write_text('# fixture strategy\n')
            strategy = {'id': 'new-strategy', 'name': 'New strategy', 'file': 'strategy.py', 'file_hash': builder.sha(source)}
            inp = {'strategy': strategy, 'dataset': {'symbol': 'ES'}, 'parameters': {'contracts': 1}, 'timeframe': '1h', 'session': 'full-trading-day', 'capital': 1000, 'fee': 1, 'slippage': 1, 'start': '2026-01-01', 'end': '2026-01-10', 'source_hash': 'snapshot', 'research': {'evaluation_id': 'evaluation', 'role': 'Test', 'scenario': 'Baseline'}}
            (run / 'input.json').write_text(json.dumps(inp))
            (run / 'trades.csv').write_text('entry_time,exit_time,net_pnl\n2026-01-01T12:00:00Z,2026-01-02T12:00:00Z,40\n')
            (run / 'equity.csv').write_text('timestamp,equity\n2026-01-01T12:00:00Z,1000\n2026-01-02T12:00:00Z,1040\n')
            manifest = {'artifacts': [{'name': name, 'checksum': builder.sha(run / name)} for name in ['trades.csv', 'equity.csv']], 'metrics': {'net_pnl': 40}}
            (run / 'manifest.json').write_text(json.dumps(manifest))
            record = {'id': 'new-run', 'input': inp, 'created_at': '2026-01-11', 'status': 'Succeeded'}
            scenarios = ['Baseline', 'Higher costs', 'Delayed execution']
            evaluation = {'id': 'evaluation', 'status': 'Succeeded', 'folds': [{'tests': ['new-run']}], 'scenarios': scenarios, 'result': {'scenarios': [{'name': name, 'outcome': 'Meets criteria', 'metrics': {'net_pnl': 40}} for name in scenarios]}}
            with sqlite3.connect(state / 'workbench.sqlite3') as db:
                db.execute('CREATE TABLE records (kind TEXT, body TEXT)')
                db.executemany('INSERT INTO records VALUES (?,?)', [('run', json.dumps(record)), ('evaluation', json.dumps(evaluation))])
            db.close()
            with patch.multiple(builder, ROOT=root, OUT=state / 'collective', FIRST=root / 'missing-first', EXPANDED=root / 'missing-expanded', SND=root / 'missing-snd'), patch.dict(os.environ, {'WORKBENCH_HOME': str(state)}), contextlib.redirect_stdout(io.StringIO()):
                builder.main()
                index = builder.read(state / 'collective/index.json'); self.assertEqual(index['errors'], [])
                self.assertEqual(len(index['items']), 1)
                item = index['items'][0]; self.assertEqual(item['capital'], 1000); self.assertEqual(item['net_pnl'], 40)
                self.assertTrue(item['working']); self.assertFalse(item['feasible'])
                data = builder.read(state / 'collective' / item['series_file']); self.assertEqual(sum(d['pnl'] for d in data['daily']), 40)
                (run / 'trades.csv').write_text((run / 'trades.csv').read_text().replace(',40', ',400000'))
                with self.assertRaises(SystemExit): builder.main()
                rejected = builder.read(state / 'collective/index.json'); self.assertEqual(rejected['items'], []); self.assertIn('checksum mismatch', rejected['errors'][0]['error'])


if __name__ == '__main__':
    unittest.main()
