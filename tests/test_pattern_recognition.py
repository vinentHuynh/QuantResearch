"""Plan-derived recognition fixtures: all eight patterns, boundaries and causality."""
import unittest

import numpy as np
import pandas as pd

from workbench.event_study import DEFAULTS, PATTERNS, PatternRecognizers, detect


def frame(tail, prefix=30):
    rows = [[100, 100.5, 99.5, 100]]*prefix + tail
    index = pd.date_range('2025-01-06T14:00:00Z', periods=len(rows), freq='15min')
    bars = pd.DataFrame(rows, columns=['open', 'high', 'low', 'close'], index=index, dtype=float)
    bars['availability_time'] = index+pd.Timedelta(minutes=15)
    return bars


def mirror(bars):
    result = bars.copy()
    result.open, result.close = 200-bars.open, 200-bars.close
    result.high, result.low = 200-bars.low, 200-bars.high
    return result


def recognized(bars, key, rules=None, anchor=None):
    events, _ = detect(bars, {**DEFAULTS, **(rules or {})})
    return [e for e in events if e['pattern'] == key and (anchor is None or e['anchor'] == anchor)]


class PatternRecognitionTests(unittest.TestCase):
    def test_demand_and_supply_full_base_bounds_and_first_confirmation(self):
        bars = frame([[100.1, 100.2, 99.9, 100]]*3 + [[100, 103, 100, 102.5], [102.5, 104, 102, 103.5]])
        for data, key, expected in [(bars, 'demand_zone', (99.9, 100.2)), (mirror(bars), 'supply_zone', (99.8, 100.1))]:
            with self.subTest(pattern=key):
                found = recognized(data, key, anchor=32)
                self.assertEqual(len(found), 1)
                e = found[0]
                self.assertEqual(e['confirmation'], 33)
                self.assertAlmostEqual(e['low'], expected[0])
                self.assertAlmostEqual(e['high'], expected[1])
                self.assertEqual(e['recognition']['base_start'], 30)
                self.assertEqual(recognized(data.iloc[:33], key, anchor=32), [])

    def test_zone_wick_is_not_a_confirming_close(self):
        bars = frame([[100.1, 100.2, 99.9, 100]]*3 + [[100, 104, 99.9, 100.5]])
        for data, key in [(bars, 'demand_zone'), (mirror(bars), 'supply_zone')]:
            with self.subTest(pattern=key):
                self.assertEqual(recognized(data, key, anchor=32), [])

    def test_zone_rejects_wide_base(self):
        bars = frame([[100, 102, 98, 100]]*3 + [[100, 110, 100, 109]])
        for data, key in [(bars, 'demand_zone'), (mirror(bars), 'supply_zone')]:
            with self.subTest(pattern=key):
                self.assertEqual(recognized(data, key, anchor=32), [])

    def test_zone_departure_deadline_is_inclusive(self):
        base = [[100.1, 100.2, 99.9, 100]]*3
        for lag in [1, 2, 3, 4]:
            bars = frame(base + [[100, 100.4, 99.9, 100.1]]*(lag-1) + [[100, 104, 100, 103]])
            for data, key in [(bars, 'demand_zone'), (mirror(bars), 'supply_zone')]:
                with self.subTest(pattern=key, lag=lag):
                    found = recognized(data, key, anchor=32)
                    self.assertEqual(bool(found), lag <= 3)
                    if found:
                        self.assertEqual(found[0]['confirmation'], 32+lag)

    def test_zone_exact_atr_threshold_and_one_tick_below(self):
        bars = frame([[100.1, 100.5, 99.5, 100]]*3 + [[100, 102.5, 100, 102]])
        for data, key in [(bars, 'demand_zone'), (mirror(bars), 'supply_zone')]:
            with self.subTest(pattern=key):
                found = recognized(data, key, anchor=32)
                self.assertEqual(len(found), 1)
                self.assertEqual(found[0]['recognition']['base_width_atr'], 1)
                self.assertEqual(found[0]['recognition']['departure_atr'], 1.5)
                changed = data.copy()
                changed.iloc[-1, changed.columns.get_loc('close')] -= .01 if key == 'demand_zone' else -.01
                self.assertEqual(recognized(changed, key, anchor=32), [])

    def test_order_blocks_use_last_opposite_colour_full_range(self):
        bars = frame([[100.3, 100.4, 99.7, 99.9], [99.9, 100.3, 99.8, 100.2],
                      [100.2, 100.3, 99.8, 100], [100, 100.4, 99.9, 100.3], [100.3, 104, 100, 103]])
        for data, key in [(bars, 'bullish_order_block'), (mirror(bars), 'bearish_order_block')]:
            with self.subTest(pattern=key):
                e = recognized(data, key)[-1]
                self.assertEqual((e['anchor'], e['confirmation']), (32, 34))
                self.assertEqual(e['low'], data.low.iloc[32])
                self.assertEqual(e['high'], data.high.iloc[32])
                self.assertEqual(recognized(data.iloc[:34], key), [])

    def test_order_block_requires_breakout_not_just_departure(self):
        bars = frame([[100.2, 100.3, 99.7, 99.8], [99.8, 104, 99.8, 103]])
        bars.iloc[20, bars.columns.get_loc('high')] = 110
        for data, key in [(bars, 'bullish_order_block'), (mirror(bars), 'bearish_order_block')]:
            with self.subTest(pattern=key):
                self.assertEqual(recognized(data, key), [])

    def test_order_block_breakout_must_be_strict_close(self):
        bars = frame([[100.2, 100.3, 99.7, 99.8], [99.8, 102, 99.8, 100.5]])
        for data, key in [(bars, 'bullish_order_block'), (mirror(bars), 'bearish_order_block')]:
            with self.subTest(pattern=key):
                self.assertEqual(recognized(data, key, {'departure_atr': .1}), [])

    def test_order_block_requires_departure_not_just_breakout(self):
        bars = frame([[100.2, 100.3, 99.7, 99.8], [99.8, 101, 99.8, 100.6]])
        for data, key in [(bars, 'bullish_order_block'), (mirror(bars), 'bearish_order_block')]:
            with self.subTest(pattern=key):
                self.assertEqual(recognized(data, key), [])

    def test_order_block_no_opposite_or_doji_does_not_qualify(self):
        bars = frame([[100, 100.3, 99.7, 100]]*5 + [[100, 104, 100, 103]])
        self.assertEqual(recognized(bars, 'bullish_order_block'), [])
        self.assertEqual(recognized(mirror(bars), 'bearish_order_block'), [])

    def test_order_block_lookback_five_inclusive_six_excluded(self):
        for lag in [5, 6]:
            bars = frame([[100.2, 100.3, 99.7, 99.8]] + [[100, 100.4, 99.9, 100.2]]*(lag-1) + [[100, 104, 100, 103]])
            for data, key in [(bars, 'bullish_order_block'), (mirror(bars), 'bearish_order_block')]:
                with self.subTest(pattern=key, lag=lag):
                    self.assertEqual(bool(recognized(data, key)), lag == 5)

    def test_fvgs_exact_bounds_and_third_close_availability(self):
        bars = frame([[100, 100.5, 99.5, 100], [100, 102, 99.8, 101.5], [101.5, 102, 101, 101.8]])
        for data, key, edges in [(bars, 'bullish_fvg', (100.5, 101)), (mirror(bars), 'bearish_fvg', (99, 99.5))]:
            with self.subTest(pattern=key):
                e = recognized(data, key, anchor=30)[0]
                self.assertEqual((e['low'], e['high']), edges)
                self.assertEqual(e['confirmation'], 32)
                self.assertEqual(e['timestamp'], data.availability_time.iloc[32].isoformat())
                self.assertEqual(recognized(data.iloc[:32], key, anchor=30), [])

    def test_fvg_touching_edges_and_overlap_are_not_gaps(self):
        for low in [100.5, 100.4]:
            bars = frame([[100, 100.5, 99.5, 100], [100, 102, 99.8, 101.5], [101.5, 102, low, 101.8]])
            for data, key in [(bars, 'bullish_fvg'), (mirror(bars), 'bearish_fvg')]:
                with self.subTest(pattern=key, edge=low):
                    self.assertEqual(recognized(data, key, anchor=30), [])

    def test_swing_confirmation_waits_two_right_candles(self):
        bars = frame([[100, 100.5, 98, 99], [99, 100.5, 99, 100], [100, 100.5, 99.4, 100]])
        for data, key in [(bars, 'support'), (mirror(bars), 'resistance')]:
            with self.subTest(pattern=key):
                e = recognized(data, key, anchor=30)[0]
                self.assertEqual(e['confirmation'], 32)
                self.assertAlmostEqual(e['high']-e['low'], .25*e['atr'])
                level = data.low.iloc[30] if key == 'support' else data.high.iloc[30]
                self.assertAlmostEqual((e['high']+e['low'])/2, level)
                self.assertEqual(recognized(data.iloc[:32], key, anchor=30), [])

    def test_swing_ties_or_a_lower_right_low_do_not_qualify(self):
        for low in [98, 97.5]:
            bars = frame([[100, 100.5, 98, 99], [99, 100.5, low, 100], [100, 100.5, 99.4, 100]])
            self.assertEqual(recognized(bars, 'support', anchor=30), [])
            self.assertEqual(recognized(mirror(bars), 'resistance', anchor=30), [])

    def test_fvg_does_not_wait_for_unrelated_breakout_lookback(self):
        bars = frame([[101, 102, 101, 101.5]], prefix=14)
        found = recognized(bars, 'bullish_fvg', {'breakout_bars': 100})
        self.assertEqual(found[0]['confirmation'], 14)

    def test_all_eight_recognizers_are_prefix_causal_and_mirror_symmetric(self):
        rng = np.random.default_rng(71)
        close = 100+np.cumsum(rng.normal(0, .8, 400))
        bars = frame([[c+(.1 if i % 2 else -.1), c+.3, c-.3, c] for i, c in enumerate(close)], prefix=0)
        rules = {**DEFAULTS, 'base_atr': 2}
        full, _ = detect(bars, rules)
        short, _ = detect(bars.iloc[:200], rules)
        self.assertEqual(short, [e for e in full if e['confirmation'] < 200])
        inverse, _ = detect(mirror(bars), rules)
        for key, _, family, direction in PATTERNS:
            with self.subTest(pattern=key):
                original = [e for e in full if e['pattern'] == key]
                self.assertTrue(original, f'Fixture must exercise {key}')
                mirrored = [e for e in inverse if e['family'] == family and e['direction'] == -direction]
                self.assertEqual([(e['anchor'], e['confirmation']) for e in original], [(e['anchor'], e['confirmation']) for e in mirrored])
                for a, b in zip(original, mirrored):
                    self.assertAlmostEqual(a['low'], 200-b['high'])
                    self.assertAlmostEqual(a['atr'], b['atr'])

    def test_zero_atr_and_insufficient_history_never_form_patterns(self):
        bars = frame([[100, 100, 100, 100]]*50, prefix=0)
        self.assertEqual(detect(bars, DEFAULTS)[0], [])
        short = frame([[100, 102, 98, 100]]*2, prefix=0)
        recognizers = PatternRecognizers(short, DEFAULTS)
        for key, _, _, _ in PATTERNS:
            with self.subTest(pattern=key):
                self.assertEqual(getattr(recognizers, key)(1), [])


if __name__ == '__main__':
    unittest.main()
