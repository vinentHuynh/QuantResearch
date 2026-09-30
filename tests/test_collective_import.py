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
    def test_refresh_extensions_uses_configured_workbench_home(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = root / 'isolated-state'
            refresh = root / 'refresh'
            data_file = state / 'datasets' / 'fixture.parquet'
            data_file.parent.mkdir(parents=True)
            data_file.write_bytes(b'isolated dataset fixture')
            checksum = builder.sha(data_file)
            dataset = {
                'schema_version': 2,
                'id': 'isolated-dataset',
                'symbol': 'NQ',
                'path': 'datasets/fixture.parquet',
                'checksum': checksum,
            }
            (state / 'datasets' / 'catalog.json').write_text(
                json.dumps({'datasets': [dataset], 'errors': []}),
                encoding='utf-8',
            )
            for index, identity in enumerate(sorted(builder.REFRESH_IDS)):
                folder = refresh / f'extension-{index}'
                folder.mkdir(parents=True)
                (folder / 'extension.json').write_text(json.dumps({
                    'catalog_id': identity,
                    'dataset_id': dataset['id'],
                    'dataset_checksum': checksum,
                }), encoding='utf-8')
            missing_production = root / 'must-not-be-read'
            with patch.multiple(
                builder,
                ROOT=missing_production,
                FIRST=root / 'first',
                EXPANDED=root / 'expanded',
                SND=root / 'snd',
                REFRESH=refresh,
            ), patch.dict(os.environ, {'WORKBENCH_HOME': str(state)}):
                extensions = builder.refresh_extensions()
            self.assertEqual(set(extensions), builder.REFRESH_IDS)

    def test_portfolio_extension_replaces_forced_boundary_exit_once(self):
        synthetic = {
            'entry': '2026-08-31T22:00:00+00:00',
            'exit': '2026-08-31T23:55:00+00:00',
            'pnl': 47.5, 'quantity': 1, 'cost': 27.5,
            'exit_reason': 'end-of-test', 'synthetic_exit': True,
        }
        natural = {
            'entry': '2026-08-31T22:00:00+00:00',
            'exit': '2026-09-01T10:00:00+00:00',
            'pnl': 100.0, 'quantity': 1, 'cost': 27.5,
            'exit_reason': 'signal', 'synthetic_exit': False,
        }
        old = [('2026-08-01', '2026-08-31', [synthetic], {'2026-08-31': 47.5})]
        extension = {
            'catalog_id': 'fixture', 'start': '2026-09-01', 'end': '2026-09-02',
            'trades': [natural], 'daily': {'2026-09-01': 62.5, '2026-09-02': 0.0},
            'boundary_correction': {
                'date': '2026-08-31', 'remove_trade': synthetic,
                'original_daily_pnl': 47.5, 'delta_pnl': -10.0,
                'corrected_daily_pnl': 37.5,
            },
        }
        merged = builder.extend_segments(old, extension)
        self.assertEqual(old[0][2], [synthetic], 'Frozen source history stays intact')
        self.assertEqual(merged[0][2], [])
        self.assertEqual(merged[0][3]['2026-08-31'], 37.5)
        self.assertEqual(merged[1][2], [natural])
        self.assertEqual(sum(sum(days.values()) for _, _, _, days in merged), 100.0)
        broken = {**extension, 'daily': {'2026-09-01': 63.5}}
        with self.assertRaisesRegex(ValueError, 'does not reconcile'):
            builder.extend_segments(old, broken)

    def test_exit_provenance_keeps_forced_winners_and_losers_out_of_natural_sample(self):
        import pandas as pd
        t=pd.DataFrame({'entry_time':['2026-01-01T00:00:00Z']*4,'exit_time':['2026-01-02T00:00:00Z']*4,'net_pnl':[10,-20,30,-40],'exit_reason':['end-of-test','end-of-test','signal',None]})
        rows=builder.normalize(t)
        self.assertEqual([r.get('synthetic_exit') for r in rows],[True,True,False,None])
        self.assertEqual(sum(r['pnl'] for r in rows),-20)
        self.assertEqual(rows[0]['exit_provenance'],'recorded')

    def test_normalize_preserves_actual_contracts_and_costs_without_guessing(self):
        import pandas as pd
        t=pd.DataFrame({'entry_time':['2026-01-01T00:00:00Z']*2,'exit_time':['2026-01-02T00:00:00Z']*2,'net_pnl':[10,20],'quantity':[-2,1],'cost':[5,3]})
        rows=builder.normalize(t)
        self.assertEqual([r['quantity'] for r in rows],[2,1])
        self.assertEqual([r['cost'] for r in rows],[5,3])
        self.assertNotIn('quantity',builder.normalize(t.drop(columns=['quantity']))[0])

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
            dataset = {'id': 'dataset-v2', 'symbol': 'ES', 'last': '2026-01-10T23:59:00Z'}
            envelope = lambda kind, identifier, body: json.dumps({
                'schema_version': 2, 'kind': kind, 'id': identifier, 'body': body,
            })
            with sqlite3.connect(state / 'workbench.sqlite3') as db:
                db.execute('CREATE TABLE records (kind TEXT, id TEXT, body TEXT)')
                db.executemany('INSERT INTO records VALUES (?,?,?)', [
                    ('run', record['id'], envelope('run', record['id'], record)),
                    ('evaluation', evaluation['id'], envelope('evaluation', evaluation['id'], evaluation)),
                    ('dataset', dataset['id'], envelope('dataset', dataset['id'], dataset)),
                    ('preset', 'legacy-v1', json.dumps({'id': 'legacy-v1', 'name': 'Legacy row'})),
                ])
            db.close()
            with patch.multiple(builder, ROOT=root, OUT=state / 'collective', FIRST=root / 'missing-first', EXPANDED=root / 'missing-expanded', SND=root / 'missing-snd'), patch.dict(os.environ, {'WORKBENCH_HOME': str(state)}), contextlib.redirect_stdout(io.StringIO()):
                builder.main()
                index = builder.read(state / 'collective/index.json'); self.assertEqual(index['errors'], [])
                self.assertEqual(index['market_data_through']['ES'], dataset['last'])
                self.assertEqual(len(index['items']), 1)
                item = index['items'][0]; self.assertEqual(item['capital'], 1000); self.assertEqual(item['net_pnl'], 40)
                self.assertTrue(item['working']); self.assertFalse(item['feasible'])
                data = builder.read(state / 'collective' / item['series_file']); self.assertEqual(sum(d['pnl'] for d in data['daily']), 40)
                self.assertEqual(data['provenance_version'],2)
                self.assertTrue(data['daily'][-1]['terminal'])
                self.assertFalse(data['daily'][0]['terminal'])
                self.assertTrue(data['trades'][0]['synthetic_exit'])
                self.assertEqual(data['trades'][0]['exit_provenance'],'legacy-worker-timing')
                self.assertEqual(data['trades'][0]['source_run'],'new-run')
                (run / 'trades.csv').write_text((run / 'trades.csv').read_text().replace(',40', ',400000'))
                with self.assertRaises(SystemExit): builder.main()
                rejected = builder.read(state / 'collective/index.json'); self.assertEqual(rejected['items'], []); self.assertIn('checksum mismatch', rejected['errors'][0]['error'])


if __name__ == '__main__':
    unittest.main()
