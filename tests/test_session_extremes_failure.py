import unittest

import pandas as pd

from strategies.session_extremes_failure import SessionExtremesFailure, wall


class SessionExtremesFailureTests(unittest.TestCase):
    def bars(self, source='prior-day', mirror=False, shallow=False):
        index = pd.date_range('2024-01-02 08:30', '2024-01-04 16:00',
                              freq='15min', tz='America/Chicago', inclusive='left')
        index = index[(index.hour < 16) | (index.hour >= 17)]
        bars = pd.DataFrame({'open': 100., 'high': 101., 'low': 99.,
                             'close': 100., 'volume': 1}, index=index)
        bars['availability_time'] = index + pd.Timedelta(minutes=15)
        bars.loc[wall('2024-01-02', 10), 'high'] = 110.
        bars.loc[wall('2024-01-03', 3), 'high'] = 106.
        price = 110. if source == 'prior-day' else 106.
        bars.loc[wall('2024-01-03', 8, 30), ['open', 'high', 'low', 'close']] = (
            price - 1, price - 0.1 if shallow else price + 1, price - 2,
            price - 1 if shallow else price)
        bars.loc[wall('2024-01-03', 9), ['open', 'high', 'low', 'close']] = (
            price - 1, price + 1, price - 2, price)
        if mirror:
            original = bars.copy()
            bars['high'], bars['low'] = 200. - original.low, 200. - original.high
            bars['open'], bars['close'] = 200. - original.open, 200. - original.close
        return bars

    def run_model(self, bars, source='prior-day'):
        model = SessionExtremesFailure(
            bars, {'level_source': source, 'zone_half_width_atr': 0.10},
            {'dataset': {'tick_size': 0.25}})
        found = []
        for i, (stamp, bar) in enumerate(bars.iterrows()):
            decision = model.on_close(i, bar, {'position': 0, 'position_at_open': 0,
                                              'tradable': True})
            if decision is not None:
                found.append((stamp, decision))
        return model, found

    def test_both_sources_use_different_frozen_extremes(self):
        for source, stop in [('prior-day', 111.25), ('overnight', 107.25)]:
            with self.subTest(source=source):
                model, found = self.run_model(self.bars(source), source)
                self.assertEqual(len(found), 1)
                stamp, decision = found[0]
                self.assertEqual(stamp, wall('2024-01-03', 8, 30))
                self.assertEqual(decision['target'], -1)
                self.assertEqual(decision['bracket'][0], stop)
                self.assertEqual(decision['expires_at'], wall('2024-01-03', 8, 45))
                self.assertEqual(model.reference_days[stamp.date()]['high'], stop - 1.25)

    def test_long_short_symmetry(self):
        _, shorts = self.run_model(self.bars())
        _, longs = self.run_model(self.bars(mirror=True))
        self.assertEqual(len(longs), 1)
        self.assertEqual(longs[0][1]['target'], 1)
        self.assertEqual(longs[0][1]['bracket'][0], 200. - shorts[0][1]['bracket'][0])

    def test_shallow_first_touch_consumes_level(self):
        for source in ['prior-day', 'overnight']:
            with self.subTest(source=source):
                _, found = self.run_model(self.bars(source, shallow=True), source)
                self.assertEqual(found, [])

    def test_missing_source_bar_rejects_reference_without_stale_fallback(self):
        for source, missing in [('prior-day', wall('2024-01-02', 12)),
                                ('overnight', wall('2024-01-03', 2))]:
            with self.subTest(source=source):
                model, found = self.run_model(self.bars(source).drop(missing), source)
                self.assertNotIn(wall('2024-01-03', 0).date(), model.reference_days)
                self.assertEqual(found, [])

    def test_future_changes_and_prefix_do_not_change_first_signal(self):
        for source in ['prior-day', 'overnight']:
            bars = self.bars(source)
            cutoff = wall('2024-01-03', 8, 30)
            _, full = self.run_model(bars, source)
            changed = bars.copy()
            later = changed.index > cutoff
            changed.loc[later, ['open', 'high', 'low', 'close']] = [500., 999., 1., 500.]
            _, future = self.run_model(changed, source)
            _, prefix = self.run_model(bars.loc[:cutoff], source)
            self.assertEqual(full[0], future[0])
            self.assertEqual(full[0], prefix[0])

    def test_source_end_and_holiday_regular_close(self):
        model, _ = self.run_model(self.bars('overnight'), 'overnight')
        day = wall('2024-01-03', 0).date()
        self.assertEqual(model.reference_days[day]['source_end'], wall(day, 8, 30))
        index = pd.date_range('2024-11-27 08:30', '2024-11-29 16:00', freq='15min', tz='America/Chicago')
        bars = pd.DataFrame({'open': 100., 'high': 101., 'low': 99., 'close': 100.}, index=index)
        bars['availability_time'] = index + pd.Timedelta(minutes=15)
        model, _ = self.run_model(bars)
        self.assertEqual(model.windows[wall('2024-11-28', 0).date()][1], wall('2024-11-28', 12))
        self.assertEqual(model.reference_days[wall('2024-11-29', 0).date()]['source_end'], wall('2024-11-28', 12))

    def test_dst_overnight_wall_times(self):
        self.assertEqual(wall('2024-03-11', 8, 30) - wall('2024-03-10', 17), pd.Timedelta(hours=15.5))
        self.assertEqual(wall('2024-11-04', 8, 30) - wall('2024-11-03', 17), pd.Timedelta(hours=15.5))


if __name__ == '__main__':
    unittest.main()
