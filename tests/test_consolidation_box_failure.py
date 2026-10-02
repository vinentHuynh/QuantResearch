import contextlib
import io
import unittest

import pandas as pd

from strategies.consolidation_box_failure import ConsolidationBoxFailure


class ConsolidationBoxFailureTests(unittest.TestCase):
    def bars(self, shallow=False, mirror=False):
        index = pd.date_range('2024-01-02 08:30', periods=60, freq='15min', tz='America/Chicago')
        bars = pd.DataFrame({'open': 100., 'high': 101., 'low': 99., 'close': 100., 'volume': 1}, index=index)
        bars['availability_time'] = index + pd.Timedelta(minutes=15)
        bars.iloc[14, bars.columns.get_indexer(['open', 'high', 'low', 'close'])] = (
            100., 101.1 if shallow else 102., 99.5, 100. if shallow else 101.)
        bars.iloc[16, bars.columns.get_indexer(['open', 'high', 'low', 'close'])] = (100., 102., 99.5, 101.)
        if mirror:
            original = bars.copy()
            bars['high'], bars['low'] = 200. - original.low, 200. - original.high
            bars['open'], bars['close'] = 200. - original.open, 200. - original.close
        return bars

    def run_model(self, bars, tradable=True):
        model = ConsolidationBoxFailure(bars,
            {'box_bars': 8, 'max_range_atr': 2., 'zone_half_width_atr': 0.10},
            {'dataset': {'tick_size': 0.25}, 'start': '2024-01-02', 'end': '2024-01-03'})
        found = []
        with contextlib.redirect_stdout(io.StringIO()):
            for i, (stamp, bar) in enumerate(bars.iterrows()):
                decision = model.on_close(i, bar, {'position': 0, 'position_at_open': 0, 'tradable': tradable})
                if decision is not None:
                    found.append((stamp, decision))
        return model, found

    def test_box_is_frozen_before_first_sweep_and_not_redrawn_each_bar(self):
        model, found = self.run_model(self.bars())
        self.assertEqual(model.box_count, 1)
        self.assertEqual(len(found), 1)
        stamp, decision = found[0]
        self.assertEqual(stamp, self.bars().index[14])
        self.assertEqual(decision['target'], -1)
        self.assertEqual(decision['bracket'][0], 102.25)
        self.assertEqual(decision['expires_at'], self.bars().availability_time.iloc[14])
        self.assertIn('box-failure:13:100.80:101.20', decision['reason'])

    def test_long_short_symmetry(self):
        _, shorts = self.run_model(self.bars())
        _, longs = self.run_model(self.bars(mirror=True))
        self.assertEqual(len(longs), 1)
        self.assertEqual(longs[0][1]['target'], 1)
        self.assertEqual(longs[0][1]['bracket'][0], 200. - shorts[0][1]['bracket'][0])

    def test_shallow_first_visit_retires_the_edge(self):
        _, found = self.run_model(self.bars(shallow=True))
        self.assertEqual(found, [])

    def test_trending_window_is_not_compact(self):
        bars = self.bars()
        for column in ['open', 'high', 'low', 'close']:
            bars[column] = [i * 5. + (101. if column == 'high' else 99. if column == 'low' else 100.) for i in range(len(bars))]
        model, found = self.run_model(bars)
        self.assertEqual(model.box_count, 0)
        self.assertEqual(found, [])

    def test_missing_formation_candle_rejects_initial_box(self):
        bars = self.bars().drop(self.bars().index[10])
        _, found = self.run_model(bars)
        self.assertFalse(any(stamp == self.bars().index[14] for stamp, _ in found))

    def test_future_price_perturbation_and_prefix_preserve_signal(self):
        bars = self.bars()
        _, original = self.run_model(bars)
        changed = bars.copy()
        changed.iloc[15:, changed.columns.get_indexer(['open', 'high', 'low', 'close'])] = [500., 999., 1., 500.]
        _, future = self.run_model(changed)
        _, prefix = self.run_model(bars.iloc[:15])
        self.assertEqual(original[0], future[0])
        self.assertEqual(original[0], prefix[0])

    def test_nonregular_first_visit_consumes_zone_without_entry(self):
        bars = self.bars()
        bars.index = pd.date_range('2024-01-02 02:00', periods=len(bars), freq='15min', tz='America/Chicago')
        bars['availability_time'] = bars.index + pd.Timedelta(minutes=15)
        model, found = self.run_model(bars)
        self.assertEqual(found, [])
        self.assertGreaterEqual(model.funnel['consumed_edges'], 1)

    def test_warmup_cannot_submit_entries(self):
        _, found = self.run_model(self.bars(), tradable=False)
        self.assertEqual(found, [])


if __name__ == '__main__':
    unittest.main()
