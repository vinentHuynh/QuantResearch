import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
import pandas as pd

from strategies import multi_speed_momentum as strategy
from workbench.contract import resolve_parameters
from workbench.worker import simulate


class MomentumEntryFilterTests(unittest.TestCase):
    def setUp(self):
        dates = pd.date_range('2023-12-01', '2025-01-16', freq='h', tz='UTC')
        rng = np.random.default_rng(40)
        close = 1000 + rng.normal(size=len(dates)).cumsum()
        self.bars = pd.DataFrame({'open': close - .1, 'close': close,
                                  'availability_time': dates + pd.Timedelta(hours=1)}, index=dates)
        self.request = {'start': '2025-01-01', 'end': '2025-01-15', 'warmup_days': 600,
                        'timeframe': '1h', 'session': 'full-trading-day', 'protocol': 1,
                        'dataset': {'symbol': 'NQ', 'tick_size': .25, 'point_value': 20},
                        'capital': 100000, 'fee': 1.25, 'slippage': 1}

    def targets(self, request, **overrides):
        params = resolve_parameters(strategy.STRATEGY, {'lookback': 5, **overrides})
        strategy.validate(params, request)
        return strategy.signals(self.bars, params)

    def test_default_matches_entry_regimes_and_preserves_the_entire_trade(self):
        _, all_trades, _ = simulate(self.bars, self.targets(self.request, nq_1h_regime_filter=False), self.request)
        _, filtered, _ = simulate(self.bars, self.targets(self.request), self.request)
        close = self.bars.close
        vol = close.pct_change().rolling(20).std().shift()
        strength = (close / close.rolling(20).mean() - 1).shift()
        entries = pd.to_datetime(all_trades.entry_time, utc=True)
        allowed = ((vol.loc[entries] > vol.loc['2024'].median()) !=
                   (strength.loc[entries] > strength.loc['2024'].median()))
        self.assertGreater(allowed.sum(), 0)
        self.assertLess(allowed.sum(), len(all_trades))
        pd.testing.assert_frame_equal(filtered, all_trades.loc[allowed.to_numpy()].reset_index(drop=True))

    def test_other_markets_and_timeframes_keep_original_signals(self):
        baseline = self.targets(self.request, nq_1h_regime_filter=False)
        for symbol, timeframe in [('MNQ', '1h'), ('ES', '1h'), ('NQ', '30m'), ('NQ', '4h'), ('NQ', '1d')]:
            with self.subTest(symbol=symbol, timeframe=timeframe):
                request = {**self.request, 'dataset': {'symbol': symbol}, 'timeframe': timeframe}
                pd.testing.assert_series_equal(self.targets(request), baseline)

    def test_short_warmup_reads_prior_year_from_the_registered_dataset(self):
        from strategy_engine.data import session_bars
        from strategy_engine.sessions import get_session

        with TemporaryDirectory() as directory:
            path = Path(directory) / 'prices.parquet'
            raw = self.bars[['open', 'close']].copy()
            raw['high'] = raw.close
            raw['low'] = raw.open
            # The bars are already at exact hourly boundaries, so a single
            # observation per source hour has the same last price.
            raw.index.name = 'ts_event'
            raw.to_parquet(path)
            session = get_session(self.request['session'])
            full = session_bars(raw, session, '1h')
            short = full.loc[full.index >= pd.Timestamp('2024-12-30', tz='UTC')]
            request = {**self.request, 'warmup_days': 2, 'dataset': {'symbol': 'NQ', 'path': str(path)}}
            extended = strategy._calibration_closes(short, request)
            pd.testing.assert_series_equal(extended, full.close, check_freq=False)
