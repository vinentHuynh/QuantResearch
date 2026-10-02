"""MGC immutable-cache registration and fixed overnight clock checks."""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from scripts.mgc.mgc_overnight_block_backtest import window_pnl
from strategies.mgc_overnight_block import STRATEGY, create_strategy
from workbench.contract import checksum, metadata, resolve_parameters
from workbench.datasets import ingest
from workbench.events import simulate_events


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('mgc_registration', ROOT / 'scripts/register-mgc-workbench.py')
registration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(registration)


def block_bars(include_exit=True):
    et = 'America/New_York'
    dates = [pd.Timestamp('2024-06-17 16:55', tz=et)]
    dates += list(pd.date_range('2024-06-17 18:00', periods=6, freq='5min', tz=et))
    dates += list(pd.date_range('2024-06-18 05:00', periods=12 if include_exit else 11,
                                freq='5min', tz=et))
    values = [(1000., 1000.)] + [(1001., 1001.)] * 6 + [(1002., 1002.)] * (12 if include_exit else 11)
    bars = pd.DataFrame({'open': [x for x, _ in values],
                         'high': [max(x, y) for x, y in values],
                         'low': [min(x, y) for x, y in values],
                         'close': [y for _, y in values]},
                        index=pd.DatetimeIndex(dates, name='event_time'))
    bars['availability_time'] = bars.index + pd.Timedelta(minutes=5)
    bars['session_id'] = 'full-trading-day'
    bars['session_date'] = ['2024-06-17'] + ['2024-06-18'] * (len(bars) - 1)
    return bars


def request(start='2024-06-17', end='2024-06-18'):
    return {'start': start, 'end': end, 'session': 'full-trading-day',
            'timeframe': '5m', 'dataset': {'symbol': 'MGC', 'tick_size': .1,
                                         'point_value': 10.},
            'capital': 100_000., 'fee': 0., 'slippage': .5, 'delay_bars': 0}


def replay(bars, req=None):
    req = req or request()
    return simulate_events(bars, create_strategy(bars, {}, req), req, return_signals=True)


class MGCOvernightBlockTests(unittest.TestCase):
    def test_adapter_metadata_and_fixed_rule(self):
        spec = metadata(ROOT / 'strategies/mgc_overnight_block.py', ROOT)
        self.assertEqual(spec['id'], 'mgc-overnight-block')
        self.assertEqual(resolve_parameters(STRATEGY, {}), {})
        self.assertEqual(spec['timeframes'], ['5m'])

    def test_source_named_block_parity_on_complete_hours(self):
        bars = block_bars()
        sess = (bars.index - pd.Timedelta(hours=18)).normalize()
        cells = bars.groupby([sess, bars.index.hour]).agg(
            o=('open', 'first'), c=('close', 'last'), n=('open', 'size'))
        cells = cells[cells.n >= 6]
        opens = cells.o.unstack(-1)
        closes = cells.c.unstack(-1)
        source = window_pnl(opens, closes, 18, 5, cost=1.)
        equity, trades, positions, signals = replay(bars)
        self.assertEqual(len(source), 1)
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades.iloc[0].entry, 1001.)
        self.assertEqual(trades.iloc[0].exit, 1002.)
        self.assertEqual(trades.iloc[0].exit_reason, '06:00-block-close')
        self.assertAlmostEqual(trades.iloc[0].net_pnl, float(source.iloc[0]))
        self.assertAlmostEqual(trades.net_pnl.sum(), equity.net_pnl.sum())
        self.assertEqual(int(positions.iloc[-1].contracts), 0)
        self.assertIn('18:00-block-open', set(signals.reason))

    def test_missing_scheduled_exit_quote_fails(self):
        bars = block_bars(include_exit=False)
        with self.assertRaisesRegex(ValueError, 'Missing MGC 05:55 closing quote'):
            replay(bars)

    def test_friday_arms_sunday_open_without_weekend_exposure(self):
        et = 'America/New_York'
        dates = [pd.Timestamp('2024-06-14 16:55', tz=et)]
        dates += list(pd.date_range('2024-06-16 18:00', periods=6, freq='5min', tz=et))
        dates += list(pd.date_range('2024-06-17 05:00', periods=12, freq='5min', tz=et))
        values = [1000.] + [1001.] * 6 + [1002.] * 12
        bars = pd.DataFrame({'open': values, 'high': values,
                             'low': values, 'close': values},
                            index=pd.DatetimeIndex(dates, name='event_time'))
        bars['availability_time'] = bars.index + pd.Timedelta(minutes=5)
        bars['session_id'] = 'full-trading-day'
        bars['session_date'] = ['2024-06-14'] + ['2024-06-17'] * 18
        _, trades, positions, _ = replay(bars, request('2024-06-14', '2024-06-17'))
        self.assertEqual(len(trades), 1)
        self.assertEqual(pd.Timestamp(trades.iloc[0].entry_time).tz_convert(et).strftime('%Y-%m-%d %H:%M'), '2024-06-16 18:00')
        self.assertEqual(trades.iloc[0].exit_reason, '06:00-block-close')
        self.assertEqual(int(positions.iloc[0].contracts), 0)
        self.assertAlmostEqual(trades.iloc[0].net_pnl, 9.)

    def test_wrong_instrument_rejected(self):
        bad = request()
        bad['dataset']['symbol'] = 'NQ'
        with self.assertRaisesRegex(ValueError, 'requires MGC'):
            create_strategy(block_bars(), {}, bad)


class MGCRegistrationTests(unittest.TestCase):
    def test_immutable_protocol_dataset_and_catalog_rescan(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache = root / 'data/_dbn_cache'
            cache.mkdir(parents=True)
            index = pd.date_range('2024-06-17 18:00', periods=10, freq='1min', tz='UTC', name='ts_event')
            values = pd.Series(range(10), index=index, dtype=float) + 2300.
            frame = pd.DataFrame({'open': values, 'high': values, 'low': values,
                                  'close': values, 'volume': 1}, index=index)
            frame.iloc[:5].to_parquet(cache / 'MGC.v.0_2024-01-01_2024-06-18_1m.parquet')
            frame.iloc[5:].to_parquet(cache / 'MGC.v.0_2024-06-18_2025-01-01_1m.parquet')
            reference = frame.tz_convert('US/Eastern').resample('5min').agg({
                'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'})
            reference_path = root / registration.REFERENCE
            reference_path.parent.mkdir(parents=True, exist_ok=True)
            reference.to_parquet(reference_path)
            destination = root / 'state/datasets'
            record = registration.register(root, destination)
            self.assertEqual(record['rows'], 10)
            self.assertEqual(record['timeframe'], '1m')
            self.assertEqual(record['point_value'], 10.)
            published = destination.parent / record['path']
            self.assertEqual(checksum(published), record['checksum'])
            filtered = pd.read_parquet(published, filters=[
                ('ts_event', '>=', index[2]), ('ts_event', '<', index[5])])
            self.assertEqual(len(filtered), 3)
            self.assertEqual(registration.register(root, destination)['id'], record['id'])
            refreshed = ingest(root, destination)
            self.assertEqual([d['id'] for d in refreshed['datasets']], [record['id']])

    def test_mismatched_five_minute_reference_blocks_publication(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache = root / 'data/_dbn_cache'
            cache.mkdir(parents=True)
            index = pd.date_range('2024-06-17 18:00', periods=5, freq='1min', tz='UTC', name='ts_event')
            frame = pd.DataFrame({'open': 2300., 'high': 2300., 'low': 2300.,
                                  'close': 2300., 'volume': 1}, index=index)
            frame.to_parquet(cache / 'MGC.v.0_2024-01-01_2025-01-01_1m.parquet')
            ref = frame.tz_convert('US/Eastern').resample('5min').first()
            ref.loc[:, 'close'] = 2301.
            path = root / registration.REFERENCE
            path.parent.mkdir(parents=True, exist_ok=True)
            ref.to_parquet(path)
            destination = root / 'state/datasets'
            with self.assertRaisesRegex(ValueError, 'does not reproduce'):
                registration.register(root, destination)
            self.assertFalse(destination.exists())


if __name__ == '__main__':
    unittest.main()
