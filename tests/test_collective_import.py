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
    def test_daily_risk_uses_full_saved_marks_and_starting_capital(self):
        risk = builder.daily_risk({'2024-01-01': 20, '2024-01-02': -30,
                                   '2025-01-01': 20}, 100)
        self.assertEqual(risk, {'max_drawdown_dollars': 30,
                                'max_drawdown': -0.25})
        self.assertEqual(builder.daily_risk({'2024-01-01': 20}, 100),
                         {'max_drawdown_dollars': 0, 'max_drawdown': 0})

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
                self.assertEqual(item['max_drawdown_dollars'], 0)
                self.assertEqual(item['max_drawdown'], 0)
                self.assertTrue(item['working']); self.assertFalse(item['feasible'])
                self.assertEqual(item['source_run_ids'], ['new-run'])
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

    def test_pinned_run_imports_exact_earlier_baseline_and_reports_bad_pins(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); state = root / 'data'; out = state / 'collective'; out.mkdir(parents=True)
            source = root / 'strategy.py'; source.write_text('# fixture strategy\n')
            strategy = {'id': 'fixture', 'name': 'Fixture strategy', 'file': 'strategy.py', 'file_hash': builder.sha(source)}
            earlier = '11111111-1111-4111-8111-111111111111'
            later = '22222222-2222-4222-8222-222222222222'
            training = '33333333-3333-4333-8333-333333333333'
            unknown = '44444444-4444-4444-8444-444444444444'
            def fixture_run(run_id, start, end, pnl, research=None):
                inp = {'strategy': strategy, 'dataset': {'symbol': 'ES'}, 'parameters': {'contracts': 1},
                       'timeframe': '1h', 'session': 'full-trading-day', 'capital': 1000, 'fee': 1,
                       'slippage': 1, 'start': start, 'end': end, 'source_hash': 'snapshot'}
                if research:inp['research'] = research
                folder = state / 'runs' / run_id; folder.mkdir(parents=True)
                (folder / 'input.json').write_text(json.dumps(inp))
                (folder / 'trades.csv').write_text(
                    f'entry_time,exit_time,net_pnl\n{start}T12:00:00Z,{end}T12:00:00Z,{pnl}\n')
                (folder / 'equity.csv').write_text(
                    f'timestamp,equity\n{start}T12:00:00Z,1000\n{end}T12:00:00Z,{1000+pnl}\n')
                (folder / 'manifest.json').write_text(json.dumps({
                    'artifacts': [{'name': name, 'checksum': builder.sha(folder / name)}
                                  for name in ('trades.csv', 'equity.csv')],
                    'metrics': {'net_pnl': pnl},
                }))
                return {'id': run_id, 'input': inp, 'created_at': end, 'status': 'Succeeded'}
            records = [
                fixture_run(earlier, '2024-01-01', '2024-01-10', 20),
                fixture_run(later, '2025-01-01', '2025-01-10', 40),
                fixture_run(training, '2023-01-01', '2023-01-10', 60,
                            {'role': 'Training', 'scenario': 'Training'}),
            ]
            with sqlite3.connect(state / 'workbench.sqlite3') as db:
                db.execute('CREATE TABLE records (kind TEXT, id TEXT, body TEXT)')
                db.executemany('INSERT INTO records VALUES (?,?,?)',
                               [('run', record['id'], json.dumps(record)) for record in records])
            db.close()
            (out / 'pinned-runs.json').write_text(json.dumps([earlier, later]))
            with patch.multiple(builder, ROOT=root, OUT=out, FIRST=root / 'missing-first',
                                EXPANDED=root / 'missing-expanded', SND=root / 'missing-snd'), \
                    patch.dict(os.environ, {'WORKBENCH_HOME': str(state)}), \
                    contextlib.redirect_stdout(io.StringIO()):
                builder.main()
                index = builder.read(out / 'index.json')
                self.assertEqual(index['errors'], [])
                self.assertEqual(len(index['items']), 2)
                by_run = {item['source_run_ids'][0]: item for item in index['items']}
                self.assertEqual(set(by_run), {earlier, later})
                self.assertEqual(by_run[earlier]['net_pnl'], 20)
                self.assertEqual(by_run[earlier]['source'], 'Pinned workbench')
                self.assertFalse(by_run[earlier]['working'])
                self.assertEqual(by_run[later]['net_pnl'], 40)
                self.assertEqual(sum(day['pnl'] for day in builder.read(out / by_run[earlier]['series_file'])['daily']), 20)
                index['items'] = [by_run[later]]
                index['sources'] = [{'name': 'existing campaign'}]
                index['errors'] = [{'key': 'existing', 'error': 'Preserved issue'}]
                index['condition_calibration'] = {'sources': [], 'marker': 'preserved'}
                builder.dump(out / 'index.json', index)
                result = builder.pinned_only()
                self.assertEqual(result['imported'], 1)
                quick = builder.read(out / 'index.json')
                self.assertEqual(len(quick['items']), 2)
                self.assertEqual(quick['sources'], index['sources'])
                self.assertEqual(quick['errors'], index['errors'])
                self.assertEqual(quick['condition_calibration'], index['condition_calibration'])
                self.assertEqual(next(item for item in quick['items'] if item['source_run_ids'] == [earlier])['net_pnl'], 20)
                self.assertEqual(builder.pinned_only()['already_present'], 2)
                self.assertEqual(builder.read(out / 'index.json'), quick)
                (out / 'pinned-runs.json').write_text(json.dumps([earlier, training, unknown]))
                with self.assertRaisesRegex(ValueError, 'not a baseline'):
                    builder.pinned_only()
                self.assertEqual(builder.read(out / 'index.json'), quick)
                with self.assertRaises(SystemExit):builder.main()
                rejected = builder.read(out / 'index.json')
                self.assertEqual(len(rejected['items']), 2)
                self.assertTrue(any(error['key'] == f'pinned:{training}' and 'not a baseline' in error['error']
                                    for error in rejected['errors']))
                self.assertTrue(any(error['key'] == f'pinned:{unknown}' and 'not in the workbench' in error['error']
                                    for error in rejected['errors']))

    def test_pinned_evaluation_fold_gets_single_run_history_beside_combined_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); state = root / 'data'; out = state / 'collective'; out.mkdir(parents=True)
            source = root / 'strategy.py'; source.write_text('# fixture strategy\n')
            strategy = {'id': 'fixture', 'name': 'Fixture strategy', 'file': 'strategy.py',
                        'file_hash': builder.sha(source)}
            first = '11111111-1111-4111-8111-111111111111'
            second = '22222222-2222-4222-8222-222222222222'
            def fixture_run(run_id, start, end, pnl):
                inp = {'strategy': strategy, 'dataset': {'symbol': 'NQ'}, 'parameters': {'contracts': 1},
                       'timeframe': '1d', 'session': 'full-trading-day', 'capital': 1000, 'fee': 1,
                       'slippage': 1, 'start': start, 'end': end, 'source_hash': 'snapshot',
                       'research': {'evaluation_id': 'evaluation', 'role': 'Test', 'scenario': 'Baseline'}}
                folder = state / 'runs' / run_id; folder.mkdir(parents=True)
                (folder / 'input.json').write_text(json.dumps(inp))
                (folder / 'trades.csv').write_text(
                    f'entry_time,exit_time,net_pnl\n{start}T12:00:00Z,{end}T12:00:00Z,{pnl}\n')
                (folder / 'equity.csv').write_text(
                    f'timestamp,equity\n{start}T12:00:00Z,1000\n{end}T12:00:00Z,{1000+pnl}\n')
                (folder / 'manifest.json').write_text(json.dumps({
                    'artifacts': [{'name': name, 'checksum': builder.sha(folder / name)}
                                  for name in ('trades.csv', 'equity.csv')],
                    'metrics': {'net_pnl': pnl},
                }))
                return {'id': run_id, 'input': inp, 'created_at': end, 'status': 'Succeeded'}
            records = [fixture_run(first, '2024-01-01', '2024-01-10', 20),
                       fixture_run(second, '2025-01-01', '2025-01-10', 40)]
            evaluation = {'id': 'evaluation', 'status': 'Succeeded',
                          'folds': [{'tests': [first]}, {'tests': [second]}],
                          'scenarios': [], 'result': {'scenarios': []}}
            with sqlite3.connect(state / 'workbench.sqlite3') as db:
                db.execute('CREATE TABLE records (kind TEXT, id TEXT, body TEXT)')
                db.executemany('INSERT INTO records VALUES (?,?,?)',
                               [('run', record['id'], json.dumps(record)) for record in records]
                               + [('evaluation', evaluation['id'], json.dumps(evaluation))])
            db.close()
            (out / 'pinned-runs.json').write_text(json.dumps([first]))
            with patch.multiple(builder, ROOT=root, OUT=out, FIRST=root / 'missing-first',
                                EXPANDED=root / 'missing-expanded', SND=root / 'missing-snd'), \
                    patch.dict(os.environ, {'WORKBENCH_HOME': str(state)}), \
                    contextlib.redirect_stdout(io.StringIO()):
                builder.main()
                index = builder.read(out / 'index.json')
                self.assertEqual(index['errors'], [])
                self.assertEqual(len(index['items']), 2)
                combined = next(item for item in index['items'] if len(item['source_run_ids']) == 2)
                exact = next(item for item in index['items'] if item['source_run_ids'] == [first])
                self.assertEqual(combined['net_pnl'], 60)
                self.assertEqual(combined['coverage'], [
                    {'start': '2024-01-01', 'end': '2024-01-10'},
                    {'start': '2025-01-01', 'end': '2025-01-10'},
                ])
                self.assertEqual(exact['source'], 'Pinned workbench')
                self.assertEqual(exact['net_pnl'], 20)
                self.assertEqual(exact['coverage'], [{'start': '2024-01-01', 'end': '2024-01-10'}])
                series = builder.read(out / exact['series_file'])
                self.assertEqual({trade['source_run'] for trade in series['trades']}, {first})
                self.assertEqual(sum(day['pnl'] for day in series['daily']), 20)
                builder.main()
                self.assertEqual({item['id'] for item in builder.read(out / 'index.json')['items']},
                                 {combined['id'], exact['id']})

    def test_pinned_only_collision_keeps_old_id_and_exact_id_through_full_refresh(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); state = root / 'data'; out = state / 'collective'; out.mkdir(parents=True)
            source = root / 'strategy.py'; source.write_text('# fixture strategy\n')
            run_id = '11111111-1111-4111-8111-111111111111'
            inp = {'strategy': {'id': 'fixture', 'name': 'Fixture strategy', 'file': 'strategy.py',
                                'file_hash': builder.sha(source)},
                   'dataset': {'symbol': 'NQ'}, 'parameters': {'contracts': 1},
                   'timeframe': '1d', 'session': 'full-trading-day', 'capital': 1000, 'fee': 1,
                   'slippage': 1, 'start': '2024-01-01', 'end': '2024-01-10', 'source_hash': 'snapshot'}
            folder = state / 'runs' / run_id; folder.mkdir(parents=True)
            (folder / 'input.json').write_text(json.dumps(inp))
            (folder / 'trades.csv').write_text(
                'entry_time,exit_time,net_pnl\n2024-01-01T12:00:00Z,2024-01-10T12:00:00Z,20\n')
            (folder / 'equity.csv').write_text(
                'timestamp,equity\n2024-01-01T12:00:00Z,1000\n2024-01-10T12:00:00Z,1020\n')
            (folder / 'manifest.json').write_text(json.dumps({
                'artifacts': [{'name': name, 'checksum': builder.sha(folder / name)}
                              for name in ('trades.csv', 'equity.csv')],
                'metrics': {'net_pnl': 20},
            }))
            record = {'id': run_id, 'input': inp, 'created_at': '2024-01-10', 'status': 'Succeeded'}
            with sqlite3.connect(state / 'workbench.sqlite3') as db:
                db.execute('CREATE TABLE records (kind TEXT, id TEXT, body TEXT)')
                db.execute('INSERT INTO records VALUES (?,?,?)', ('run', run_id, json.dumps(record)))
            db.close()
            (out / 'pinned-runs.json').write_text(json.dumps([run_id]))
            with patch.multiple(builder, ROOT=root, OUT=out, FIRST=root / 'missing-first',
                                EXPANDED=root / 'missing-expanded', SND=root / 'missing-snd'), \
                    patch.dict(os.environ, {'WORKBENCH_HOME': str(state)}), \
                    contextlib.redirect_stdout(io.StringIO()):
                base,payload = builder.prepare_pinned_run(run_id, record)
                (out / base['series_file']).write_bytes(payload)
                old = {**base, 'coverage': [{'start': '2023-01-01', 'end': '2024-01-10'}],
                       'latest_replay': {'start': '2024-01-11', 'end': '2024-01-12',
                                         'dataset_id': 'newer', 'extension_sha256': 'a'}}
                builder.dump(out / 'index.json', {'version': 1, 'items': [old], 'errors': [],
                                                   'sources': [], 'definitions': {}})
                self.assertEqual(builder.pinned_only()['imported'], 1)
                imported = builder.read(out / 'index.json')['items']
                exact = next(item for item in imported if builder.exact_run_item(item, run_id, record))
                self.assertNotEqual(exact['id'], old['id'])
                self.assertEqual(exact['key'], base['key'] + '__exact')
                self.assertEqual(builder.pinned_only()['already_present'], 1)
                builder.main()
                refreshed = builder.read(out / 'index.json')['items']
                self.assertIn(old['id'], {item['id'] for item in refreshed})
                self.assertIn(exact['id'], {item['id'] for item in refreshed})
                self.assertEqual(next(item for item in refreshed if item['id'] == exact['id'])['checksum'],
                                 exact['checksum'])


if __name__ == '__main__':
    unittest.main()
