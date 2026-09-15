import ast
import importlib.util
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from workbench.contract import discover
from strategies._legacy_signals import rsi_reversion, vwap_reversion, momentum

ROOT = Path(__file__).resolve().parents[1]


def original_functions(path, names):
    """Exercise original pure functions without importing dataset/credential setup."""
    tree = ast.parse((ROOT / path).read_text(encoding='utf-8'))
    selected = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    if len(selected) != len(names):
        raise AssertionError('Original rule function missing')
    namespace = {'np': np, 'pd': pd}
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(path), 'exec'), namespace)
    return namespace


class StrategyLibraryTests(unittest.TestCase):
    def test_inventory_covers_all_original_sources_and_preserves_collections(self):
        result = discover(ROOT)
        self.assertEqual(result['errors'], [])
        entries = {e['path']: e for e in result['library']['entries']}
        expected = [*ROOT.glob('*.py'), *(ROOT / 'scripts').rglob('*.py'), *(ROOT / 'ninjatrader').rglob('*.py'), *(ROOT / 'strategy_engine/strategies').glob('*.py')]
        for path in expected:
            if path.name != '__init__.py' and '__pycache__' not in path.parts:
                self.assertIn(path.relative_to(ROOT).as_posix(), entries)
        for filename in ('es_nq/es_nq_strategies', 'spy_qqq_intraday/intraday_bakeoff', 'cme/short_horizon_backtest', 'mnq/SND_phase5_combinations'):
            self.assertEqual(entries[f'scripts/{filename}.py']['role'], 'Rule collection')
        for strategy in result['strategies']:
            for source in strategy.get('legacy_sources', []):
                self.assertIn(source, entries)
                self.assertIn(strategy['id'], [a['id'] for a in entries[source]['adapters']])
        self.assertEqual(entries['scripts/cme/factor_ls_backtest.py']['status'], 'Adapter required')

    def test_discovery_is_non_executing_and_picks_up_new_sources(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'scripts').mkdir()
            file = root / 'scripts/new_backtest.py'
            file.write_text('raise RuntimeError("do not execute")\ndef trading_rule(): pass\n')
            first = discover(root)['library']['entries'][0]
            self.assertEqual(first['functions'], ['trading_rule'])
            file.write_text('raise RuntimeError("changed, still do not execute")')
            second = discover(root)['library']['entries'][0]
            self.assertEqual(first['id'], second['id'])
            self.assertNotEqual(first['file_hash'], second['file_hash'])

    def test_invalid_lineage_is_reported_without_hiding_valid_strategies(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'strategies').mkdir()
            good = {'id': 'good-strategy', 'name': 'Good', 'description': 'Test', 'parameters': {}, 'timeframes': ['1h']}
            (root / 'strategies/good.py').write_text('STRATEGY = ' + repr(good))
            for field in ({'legacy_sources': None}, {'legacy_sources': ['../outside.py']}, {'legacy_sources': ['scripts/missing.py']}, {'default_warmup_days': True}):
                (root / 'strategies/bad.py').write_text('STRATEGY = ' + repr({**good, 'id': 'bad-strategy', **field}))
                result = discover(root)
                self.assertEqual([s['id'] for s in result['strategies']], ['good-strategy'])
                self.assertEqual(len(result['errors']), 1)

    def test_rsi_signal_matches_original_return_generator(self):
        source = original_functions('scripts/es_nq/es_nq_strategies.py', {'rsi', 's_rsi2'})
        rng = np.random.default_rng(913)
        index = pd.date_range('2018-01-01', periods=1500, freq='B')
        close = pd.Series(100 * np.exp(np.cumsum(rng.normal(.0008, .013, len(index)))), index=index)
        expected = source['s_rsi2'](pd.DataFrame({'close': close}))
        target = rsi_reversion(close, 200, 10, 70)
        self.assertGreater(target.sum(), 0)
        pd.testing.assert_series_equal((target.shift(1) * close.pct_change()).fillna(0), expected)

    def test_vwap_state_matches_original_intraday_gross_returns(self):
        source = original_functions('scripts/spy_qqq_intraday/intraday_bakeoff.py', {'s_vwap_rev'})
        index = pd.date_range('2025-01-06 09:30', periods=72, freq='5min').append(pd.date_range('2025-01-07 09:30', periods=72, freq='5min'))
        close = 100 + np.sin(np.arange(len(index)) / 4) * 3
        bars = pd.DataFrame({'open': close, 'high': close + .3, 'low': close - .4, 'close': close, 'volume': 500., 'session_date': index.date}, index=index)
        expected, _, _ = source['s_vwap_rev'](bars, 0, band=.002)
        target = vwap_reversion(bars, .002)
        actual = {}
        for day, group in bars.groupby(bars.index.normalize()):
            held = target.loc[group.index].shift(1).fillna(0)
            actual[day] = float((1 + held * group.close.pct_change().fillna(0)).prod() - 1)
        pd.testing.assert_series_equal(pd.Series(actual), expected)

    def test_momentum_matches_canonical_signal_levels(self):
        from strategy_engine.strategies.trend import TrendConfig, run
        from strategy_engine.strategies.relative_value import LegEconomics
        index = pd.date_range('2025-01-01', periods=100, tz='UTC')
        close = 100 + np.sin(np.arange(100) / 5) * 10
        bars = pd.DataFrame({'close': close, 'session_id': 'daily', 'session_date': index.date, 'availability_time': index + pd.Timedelta(days=1)}, index=index)
        _, decisions, _ = run(bars, symbol='TEST', economics=LegEconomics(.25, 2), config=TrendConfig('multi-speed-momentum', lookback=5))
        expected = np.sign(decisions.set_index(pd.to_datetime(decisions.event_time)).level).reindex(bars.availability_time).fillna(0).to_numpy()
        np.testing.assert_array_equal(momentum(bars.close, 5), expected)

    def test_all_adapters_are_causal_and_bounded(self):
        index = pd.date_range('2024-01-01', periods=900, freq='h', tz='UTC')
        close = 100 + np.arange(900) * .01 + np.sin(np.arange(900) / 3) * 3
        bars = pd.DataFrame({'open': close, 'close': close, 'high': close + .5, 'low': close - .5, 'volume': 100., 'session_id': 'test', 'session_date': index.date, 'availability_time': index + pd.Timedelta(hours=1)}, index=index)
        for spec in discover(ROOT)['strategies']:
            if spec.get('execution_model') == 'event-v1':
                continue  # Stateful event ports have dedicated execution/causality tests.
            module_spec = importlib.util.spec_from_file_location(spec['id'], ROOT / spec['file'])
            module = importlib.util.module_from_spec(module_spec)
            module_spec.loader.exec_module(module)
            parameters = {k: v['default'] for k, v in spec['parameters'].items()}
            whole = module.signals(bars.copy(), parameters)
            prefix = module.signals(bars.iloc[:550].copy(), parameters)
            with self.subTest(strategy=spec['id']):
                pd.testing.assert_series_equal(whole.iloc[:550], prefix)
                self.assertTrue(np.isfinite(whole).all())
                self.assertTrue((whole.abs() <= 100).all())
                self.assertTrue((whole == np.trunc(whole)).all())


if __name__ == '__main__':
    unittest.main()
