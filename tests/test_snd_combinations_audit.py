"""Mutation and geometry checks for the independent combination auditor."""
import importlib.util
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

import numpy as np
import pandas as pd

from strategies import _snd_combination_reference as reference
from test_snd_zone_quality import source_frame, HISTORY


SPEC = importlib.util.spec_from_file_location('combination_audit', Path(__file__).resolve().parents[1] / 'scripts/audit-snd-combinations.py')
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


def fixture(boundary='wick', stop='zone', mirror=False, **changes):
    # Strict swing at i21 is known at i22; middle formation candle breaks it.
    rows = HISTORY + [(100, 102, 99, 100), (100, 101, 99, 100),
        (100, 101, 99, 99.5), (99.5, 104, 99.5, 103),
        (103, 104, 102, 103.5), (102, 103, 100, 102), (104, 115, 103.5, 110)]
    frame = source_frame(rows, mirror=mirror, minute=True)
    parameters = reference.DEFAULTS | dict(pivot_len=1, use_htf=False, zone_boundary=boundary, stop_model=stop) | changes
    result = reference.run_model(frame, parameters, '2026-01-05', '2026-01-06', .25, 2, 1, 1)
    dataset = dict(start='2026-01-05', end='2026-01-06', tick_size=.25, point_value=2,
                   fee=1, execution_minutes=1, symbol='FIXTURE')
    return frame, parameters, dataset, result


class CombinationAuditTests(unittest.TestCase):
    def test_executing_source_guard_rejects_workspace_or_helper_drift(self):
        with tempfile.TemporaryDirectory() as temporary:
            first, second = Path(temporary) / 'audit.py', Path(temporary) / 'helper.py'
            first.write_text('original audit', encoding='utf-8')
            second.write_text('original helper', encoding='utf-8')
            manifest = dict(files=[dict(path='scripts/audit.py', checksum=audit.sha(first)),
                                   dict(path='scripts/helper.py', checksum=audit.sha(second))])
            runtime = {'scripts/audit.py': first, 'scripts/helper.py': second}
            audit.require_frozen_runtime(manifest, runtime)
            second.write_text('changed after work began', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'helper.py'):
                audit.require_frozen_runtime(manifest, runtime)
            with self.assertRaisesRegex(ValueError, 'missing.py'):
                audit.require_frozen_runtime(manifest, {'scripts/missing.py': first})

    def test_raw_geometry_crosses_boundary_stop_and_direction(self):
        for boundary in ('wick', 'body'):
            for stop in ('zone', 'candle'):
                for mirror in (False, True):
                    with self.subTest(boundary=boundary, stop=stop, mirror=mirror):
                        frame, parameters, dataset, result = fixture(boundary, stop, mirror)
                        self.assertGreater(len(result['trades']), 0)
                        record = audit.audit_raw_trades(result['trades'], parameters, dataset,
                            audit.raw_from_frame(frame), diagnostics=result['diagnostics'])
                        self.assertTrue(record['passed'], record['failures'])

    def test_body_width_cache_does_not_reuse_wick_width(self):
        frame, _, _, _ = fixture()
        raw = audit.raw_from_frame(frame)
        z = 25
        wick = audit.formations(raw['chart'], True, 'wick')
        body = audit.formations(raw['chart'], True, 'body')
        first = audit.raw_quality(raw, z, wick[1][z], wick[2][z])
        second = audit.raw_quality(raw, z, body[1][z], body[2][z])
        self.assertEqual(first['prior_atr20'], second['prior_atr20'])
        self.assertGreater(first['zone_width_atr'], second['zone_width_atr'])
        self.assertEqual(second['zone_width_atr'], (body[1][z] - body[2][z]) / second['prior_atr20'])

    def test_raw_audit_rejects_false_width_and_candle_stop(self):
        frame, p, d, r = fixture('body', 'candle')
        raw = audit.raw_from_frame(frame)
        corrupt = r['trades'].copy()
        corrupt.loc[0, 'zone_width_atr'] += .1
        record = audit.audit_raw_trades(corrupt, p, d, raw, diagnostics=r['diagnostics'])
        self.assertIn('independent raw feature: zone_width_atr', record['failures'])
        corrupt = r['trades'].copy()
        corrupt.loc[0, 'stop'] = corrupt.loc[0, 'zone_bottom'] - d['tick_size']
        record = audit.audit_raw_trades(corrupt, p, d, raw, diagnostics=r['diagnostics'])
        self.assertIn('raw one-tick selected stop', record['failures'])

    def test_raw_audit_requires_capacity_evidence(self):
        frame, p, d, r = fixture()
        record = audit.audit_raw_trades(r['trades'], p, d, audit.raw_from_frame(frame))
        self.assertIn('context capacity supplied and never discards', record['failures'])

    def test_full_accounting_accepts_reference_and_catches_ledger_corruption(self):
        _, p, d, r = fixture()
        good = audit.audit_ledger(r['trades'], p, d, r['equity'], equity_has_interval_increments=True)
        self.assertTrue(good['passed'], good['failures'])
        bad = r['trades'].copy()
        bad.loc[0, 'net_pnl'] += 1
        failures = audit.audit_ledger(bad, p, d, r['equity'])['failures']
        self.assertIn('net dollars', failures)
        self.assertIn('terminal cash reconciliation', failures)

    def test_price_slippage_not_charged_twice(self):
        _, p, d, r = fixture(slippage_model='price')
        good = audit.audit_ledger(r['trades'], p, d, r['equity'])
        self.assertTrue(good['passed'], good['failures'])
        bad = r['trades'].copy()
        bad['cost'] += .5
        self.assertIn('fees and slippage dollars', audit.audit_ledger(bad, p, d)['failures'])

    def test_quality_gate_and_expiry_corruption_detected(self):
        _, p, d, r = fixture()
        blocked = p | {'max_zone_width_atr': 0.0}
        self.assertIn('all-trade feature gate: max_zone_width_atr', audit.audit_ledger(r['trades'], blocked, d)['failures'])
        bad = r['trades'].copy()
        bad['order_expiry_time'] += pd.Timedelta(minutes=5)
        self.assertIn('correct order expiry', audit.audit_ledger(bad, p, d)['failures'])

    def test_zero_trade_case_and_terminal_reconciliation(self):
        _, p, d, r = fixture(max_zone_width_atr=0)
        self.assertEqual(len(r['trades']), 0)
        self.assertTrue(audit.audit_ledger(r['trades'], p, d, r['equity'])['passed'])
        bad = r['equity'].copy()
        bad.loc[bad.index[-1], 'equity'] += 1
        self.assertIn('terminal cash reconciliation', audit.audit_ledger(r['trades'], p, d, bad)['failures'])

    def test_sampling_is_deterministic_ordinal_and_unique(self):
        self.assertEqual(audit.sample_indices(0).tolist(), [])
        self.assertEqual(audit.sample_indices(2).tolist(), [0, 1])
        self.assertEqual(audit.sample_indices(10).tolist(), [0, 4, 9])
        self.assertEqual(audit.sample_indices(11).tolist(), [0, 5, 10])

    def test_exact_parity_rejects_dropped_rows_or_different_values(self):
        _, _, _, r = fixture()
        t, e = r['trades'], r['equity']
        self.assertTrue(audit.exact_reference_parity(t, t, e, e)['passed'])
        self.assertFalse(audit.exact_reference_parity(t, t, e, e.iloc[::2])['passed'])
        bad = t.copy(); bad.loc[0, 'entry'] += .25
        self.assertFalse(audit.exact_reference_parity(t, bad)['passed'])

    def test_artifact_layout_accounts_for_traded_and_zero_trade_cases(self):
        frame, p, d, traded = fixture('body', 'candle')
        _, p0, _, empty = fixture('body', 'candle', max_zone_width_atr=0)
        configs = {'c0': {'parameters': p}, 'c1': {'parameters': p0}}
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary) / 'shard-0000' / 'attempt-000'
            folder.mkdir(parents=True)
            frames, cases = {}, []
            for cid, r in [('c0', traded), ('c1', empty)]:
                daily = r['equity'].iloc[[-1]].copy()
                daily['net_pnl'] = daily.equity - p['capital']
                for name, table in [('trades.parquet', r['trades']), ('equity-daily.parquet', daily)]:
                    frames.setdefault(name, []).append(table.assign(config_id=cid))
                for name in ('periods.parquet', 'training.parquet', 'weekly.parquet'):
                    frames.setdefault(name, []).append(pd.DataFrame({'config_id': [cid]}))
                cases.append(dict(config_id=cid, status='succeeded', diagnostics=r['diagnostics'],
                                  summary=dict(trades=len(r['trades']), net_pnl=float(r['trades'].net_pnl.sum()))))
            for name, tables in frames.items():
                pd.concat(tables, ignore_index=True).to_parquet(folder / name, index=False)
            audit._save(folder / 'cases.json', cases)
            identity = dict(protocol_checksum='protocol', source_hash='source', configurations_checksum='grid')
            audit._save(folder / 'input.json', dict(**identity, symbol=d['symbol'], config_ids=list(configs), start_index=0, stop_index=2))
            audit._save(folder / 'status.json', dict(status='succeeded'))
            artifact_names = ['cases.json', *frames]
            result = dict(**identity, status='succeeded', symbol=d['symbol'], config_ids=list(configs),
                          artifacts=[dict(name=name, checksum=audit.sha(folder / name)) for name in artifact_names])
            audit._save(folder / 'result.json', result)
            raw = audit.raw_from_frame(frame)
            good = audit.audit_shard(folder, d, configs, raw, 'protocol', 'source', 'grid')
            self.assertTrue(good['shard']['passed'], good['shard']['failures'])
            self.assertTrue(all(c['passed'] for c in good['cases']), good['cases'])
            self.assertEqual([c['sampled_trades'] for c in good['cases']], [1, 0])
            # A rewritten artifact is detected even though its contents remain valid JSON.
            (folder / 'cases.json').write_text(json.dumps(cases), encoding='utf-8')
            bad = audit.audit_shard(folder, d, configs, raw, 'protocol', 'source', 'grid')
            self.assertIn('output checksum: cases.json', bad['shard']['failures'])
            saved = audit.read(folder / 'input.json')
            saved['start_index'] = 1
            audit._save(folder / 'input.json', saved)
            bad = audit.audit_shard(folder, d, configs, raw, 'protocol', 'source', 'grid')
            self.assertIn('exact declared configuration slice', bad['shard']['failures'])

    def test_market_aggregation_retains_failure_and_duplicate_coverage(self):
        protocol = dict(markets=['MNQ', 'MGC'], expected_market_cases=4)
        common = dict(observed=['c0', 'c1'], raw_sources=[], shards=[], status='passed', failures=[],
                      audited_cases=2, exhaustive_accounting_trades=10, raw_sampled_trades=6, total_checks=20,
                      coverage=dict(observed=2, unique=2, missing=[], unexpected=[], duplicate_count=0))
        records = [dict(common, symbol=s) for s in protocol['markets']]
        combined = audit.aggregate_markets(records, protocol)
        self.assertTrue(combined['complete_sweep'])
        self.assertEqual(combined['total_checks'], 40)
        self.assertFalse(audit.aggregate_markets(records[:1], protocol)['complete_sweep'])
        duplicate = audit.aggregate_markets([records[0], records[0]], protocol)
        self.assertFalse(duplicate['complete_sweep'])
        self.assertIn('Duplicate market audit records', duplicate['failures'][0]['failures'])
        records[1] = dict(records[1], status='failed', failures=[dict(identity='MGC/attempt-000', failures=['checksum'])])
        self.assertEqual(audit.aggregate_markets(records, protocol)['failures'], records[1]['failures'])

    def test_parallel_cli_preserves_missing_market_cases_as_incomplete(self):
        frame, parameters, dataset, _ = fixture()
        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary)
            source = out / 'minute.parquet'
            frame.to_parquet(source)
            dataset = dict(dataset, files=[dict(path=str(source), checksum=audit.sha(source))])
            configurations = [dict(config_id='c0', parameters=parameters,
                parameter_hash=hashlib.sha256(json.dumps(parameters, sort_keys=True, separators=(',', ':')).encode()).hexdigest())]
            audit._save(out / 'configurations.json', configurations)
            protocol = dict(configurations_file='configurations.json', configurations_checksum=audit.sha(out / 'configurations.json'),
                expected_configurations=1, expected_market_cases=1, markets=[dataset['symbol']], datasets=[dataset],
                grid=dict(zone_boundary=['wick']))
            audit._save(out / 'protocol.json', protocol)
            script = out / 'source/scripts/audit-snd-combinations.py'
            script.parent.mkdir(parents=True)
            shutil.copy2(audit.__file__, script)
            files = [dict(path='scripts/audit-snd-combinations.py', checksum=audit.sha(script))]
            audit._save(out / 'source-manifest.json', dict(files=files,
                source_hash=hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest(),
                protocol_checksum=audit.sha(out / 'protocol.json'), configurations_checksum=protocol['configurations_checksum']))
            process = subprocess.run([sys.executable, audit.__file__, '--output', str(out), '--workers', '2'],
                                     text=True, capture_output=True, timeout=30)
            self.assertEqual(process.returncode, 1, process.stderr)
            result = audit.read(out / 'independent-sweep-audit.json')
            self.assertEqual(result['status'], 'incomplete')
            self.assertFalse(result['complete_sweep'])
            self.assertEqual(result['failures'], [])
            self.assertEqual(result['coverage'][dataset['symbol']]['missing'], ['c0'])
            self.assertTrue((out / 'audit/sweep' / (dataset['symbol'] + '.json')).is_file())


if __name__ == '__main__':
    unittest.main()
