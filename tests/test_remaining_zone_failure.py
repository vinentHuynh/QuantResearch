import contextlib
import io
import unittest

import pandas as pd

from strategies.remaining_zone_failure import RemainingZoneFailure, complete_higher_bars, wall


class RemainingZoneFailureTests(unittest.TestCase):
    def bars(self, start='2024-01-02 05:00', count=120):
        index = pd.date_range(start, periods=count, freq='15min', tz='America/Chicago')
        bars = pd.DataFrame({'open': 100., 'high': 101., 'low': 99., 'close': 100., 'volume': 1}, index=index)
        bars['availability_time'] = index + pd.Timedelta(minutes=15)
        return bars

    def model(self, bars, mode):
        return RemainingZoneFailure(bars, {'detector': mode, 'zone_half_width_atr': 0.10, 'swing_sides': 2},
                                    {'dataset': {'tick_size': 0.25}, 'start': '2024-01-02', 'end': '2024-01-05'})

    def run_model(self, bars, mode):
        model = self.model(bars, mode)
        found = []
        with contextlib.redirect_stdout(io.StringIO()):
            for i, (stamp, bar) in enumerate(bars.iterrows()):
                decision = model.on_close(i, bar, {'position': 0, 'position_at_open': 0, 'tradable': True})
                if decision:
                    found.append((stamp, decision))
        return model, found

    def test_opening_windows_activate_only_after_window_and_first_sweep(self):
        for mode, signal in [('opening-15m', '08:45'), ('opening-30m', '09:00')]:
            bars = self.bars()
            stamp = pd.Timestamp('2024-01-02 ' + signal, tz='America/Chicago')
            bars.loc[stamp, ['open', 'high', 'low', 'close']] = [100., 102., 99.5, 101.]
            model, found = self.run_model(bars, mode)
            self.assertEqual(found[0][0], stamp)
            self.assertEqual(found[0][1]['target'], -1)
            self.assertEqual(found[0][1]['bracket'][0], 102.25)
            self.assertEqual(model.formations[0]['confirmed'], stamp.isoformat())

    def test_departure_requires_confirmed_pivot_and_declared_distance(self):
        bars = self.bars()
        bars.iloc[20, bars.columns.get_loc('high')] = 110.
        bars.iloc[25, bars.columns.get_indexer(['open', 'high', 'low', 'close'])] = [109., 111., 108., 110.]
        model, found = self.run_model(bars, 'departure-swing')
        upper = next(f for f in model.formations if f['price'] == 110.)
        self.assertEqual(upper['index'], 22)
        self.assertEqual(found[0][0], bars.index[25])
        self.assertEqual(found[0][1]['target'], -1)

    def test_role_flip_waits_for_break_then_trades_opposite_role(self):
        bars = self.bars()
        bars.iloc[20, bars.columns.get_loc('high')] = 110.
        bars.iloc[24, bars.columns.get_indexer(['open', 'high', 'low', 'close'])] = [100., 113., 99., 112.]
        bars.iloc[25, bars.columns.get_indexer(['open', 'high', 'low', 'close'])] = [111., 112., 109., 110.]
        model, found = self.run_model(bars, 'role-flip')
        upper = next(f for f in model.formations if f['price'] == 110.)
        self.assertEqual(upper['index'], 24)
        self.assertEqual(upper['side'], 1)
        self.assertEqual(found[0][0], bars.index[25])
        self.assertEqual(found[0][1]['target'], 1)

    def test_rolling_and_generic_levels_exclude_signal_bar_and_deduplicate(self):
        for mode in ['rolling-20', 'generic-prior-bar']:
            bars = self.bars()
            bars.iloc[20, bars.columns.get_indexer(['open', 'high', 'low', 'close'])] = [100., 102., 99.5, 101.]
            model, found = self.run_model(bars, mode)
            self.assertTrue(any(stamp == bars.index[20] and decision['target'] == -1 for stamp, decision in found))
            active = [(z['side'], z['price']) for z in model.zones]
            self.assertEqual(len(active), len(set(active)))

    def test_round_number_grid_has_fixed_step(self):
        bars = self.bars()
        bars[['open', 'high', 'low', 'close']] += 50.
        model, _ = self.run_model(bars, 'round-100')
        self.assertEqual({f['price'] for f in model.formations}, {100., 200.})

    def test_daily_pivots_use_completed_previous_cash_session(self):
        bars = self.bars('2024-01-02 08:30', 120)
        signal = wall('2024-01-03', 8, 30)
        bars.loc[signal, ['open', 'high', 'low', 'close']] = [100., 102., 99.5, 101.]
        model, found = self.run_model(bars, 'daily-pivots')
        self.assertEqual({f['price'] for f in model.formations}, {99., 101.})
        self.assertEqual(model.formations[0]['confirmed'], signal.isoformat())
        self.assertEqual(found[0][0], signal)
        self.assertEqual(model.formations[0]['source_end'], wall('2024-01-02', 15).isoformat())

    def test_higher_timeframe_pivot_requires_two_completed_right_bars(self):
        for mode, minutes in [('swing-1h', 60), ('swing-4h', 240)]:
            bars = self.bars('2024-01-02 17:00', 180)
            width = pd.Timedelta(minutes=minutes)
            source = wall('2024-01-02', 17) + 2 * width
            central = (bars.index >= source) & (bars.index < source + width)
            bars.loc[central, 'high'] = 110.
            model, _ = self.run_model(bars, mode)
            pivot = next(f for f in model.formations if f['price'] == 110.)
            expected = wall('2024-01-02', 17) + 5 * width
            self.assertEqual(pd.Timestamp(pivot['confirmed']), expected)
            self.assertEqual(pd.Timestamp(pivot['origin_time']), source)
            prefix = bars.loc[bars.availability_time < expected]
            early, _ = self.run_model(prefix, mode)
            self.assertFalse(any(f['price'] == 110. for f in early.formations))

    def test_missing_higher_timeframe_source_bar_rejects_bucket(self):
        bars = self.bars('2024-01-02 17:00', 40)
        original = complete_higher_bars(bars, 60)
        broken = complete_higher_bars(bars.drop(bars.index[1]), 60)
        self.assertEqual(len(broken), len(original) - 1)
        self.assertNotIn(original[0], broken)

    def test_future_price_and_prefix_causality_all_detectors(self):
        for mode in ['swing-1h', 'swing-4h', 'opening-15m', 'opening-30m', 'departure-swing',
                     'role-flip', 'rolling-20', 'round-100', 'daily-pivots', 'generic-prior-bar']:
            with self.subTest(mode=mode):
                bars = self.bars('2024-01-02 08:30', 180)
                _, full = self.run_model(bars, mode)
                changed = bars.copy()
                changed.iloc[80:, changed.columns.get_indexer(['open', 'high', 'low', 'close'])] = [500., 999., 1., 500.]
                full_model, _ = self.run_model(bars, mode)
                future, _ = self.run_model(changed, mode)
                prefix, _ = self.run_model(bars.iloc[:80], mode)
                earlier = [f for f in full_model.formations if f['index'] < 80]
                self.assertEqual(earlier, [f for f in future.formations if f['index'] < 80])
                self.assertEqual(earlier, prefix.formations)

    def test_shallow_first_touch_consumes_without_later_retry(self):
        bars = self.bars()
        stamp = wall('2024-01-02', 8, 45)
        bars.loc[stamp, ['open', 'high', 'low', 'close']] = [100., 101.1, 99.5, 100.]
        bars.loc[stamp + WIDTH_FOR_TEST, ['open', 'high', 'low', 'close']] = [100., 102., 99.5, 101.]
        _, found = self.run_model(bars, 'opening-15m')
        self.assertEqual(found, [])


WIDTH_FOR_TEST = pd.Timedelta(minutes=15)

if __name__ == '__main__':
    unittest.main()
