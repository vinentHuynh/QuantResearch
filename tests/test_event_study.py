import unittest

import numpy as np
import pandas as pd

from workbench.event_study import DEFAULTS, comparison, detect, features, match_controls, measure, rates


def candles(rows, minutes=1):
    index = pd.date_range('2025-01-06T14:00:00Z', periods=len(rows), freq=f'{minutes}min')
    result = pd.DataFrame(rows, columns=['open', 'high', 'low', 'close'], index=index, dtype=float)
    result['availability_time'] = index + pd.Timedelta(minutes=minutes)
    return result


def event(direction=1, confirmation=0):
    return dict(id=0, family='fvg', direction=direction, confirmation=confirmation,
                anchor=0, low=99., high=100., atr=1., timestamp='2025-01-06', match_id=None)


class EventStudyTests(unittest.TestCase):
    def setUp(self):
        self.rules = {**DEFAULTS, 'return_bars': 3, 'reaction_bars': 3}

    def test_confirmation_candle_cannot_touch(self):
        bars = candles([[99.5, 102, 98, 101], *([[102, 103, 101, 102]]*5)])
        outcome = measure(event(), bars, bars, self.rules, len(bars))
        self.assertFalse(outcome['returned'])
        self.assertEqual(outcome['outcome'], 'not_returned')

    def test_success_and_failure_are_mirrored(self):
        bars = candles([[102, 103, 101, 102], [100.2, 100.3, 99.5, 100], [100, 101.2, 99.8, 101], [101, 101.5, 100.5, 101]])
        good = measure(event(), bars, bars, self.rules, len(bars))
        self.assertEqual(good['outcome'], 'rejection')
        mirrored = bars.copy()
        for key in ['open', 'close']:
            mirrored[key] = 199-bars[key]
        mirrored.high, mirrored.low = 199-bars.low, 199-bars.high
        other = measure(event(-1), mirrored, mirrored, self.rules, len(bars))
        self.assertEqual(other['outcome'], 'rejection')
        self.assertEqual(other['age'], good['age'])

    def test_adverse_first_and_unresolved(self):
        bars = candles([[102, 103, 101, 102], [100.2, 100.3, 99.5, 100], [99.4, 100, 98.5, 99], [99, 102, 99, 101]])
        self.assertEqual(measure(event(), bars, bars, self.rules, 4)['outcome'], 'failure')
        bars.iloc[2:4, :4] = [99.8, 100.2, 99.5, 100]
        self.assertEqual(measure(event(), bars, bars, self.rules, 4)['outcome'], 'unresolved')

    def test_same_minute_both_boundaries_is_ambiguous(self):
        bars = candles([[102, 103, 101, 102], [100.1, 100.3, 99.5, 100], [100, 102, 98, 100], [100, 100.2, 99.5, 100]])
        self.assertEqual(measure(event(), bars, bars, self.rules, 4)['outcome'], 'ambiguous')

    def test_touch_minute_target_may_precede_touch(self):
        bars = candles([[102, 103, 101, 102], [101.5, 102, 99.5, 100], [100, 100.2, 99.5, 100], [100, 100.2, 99.5, 100]])
        self.assertEqual(measure(event(), bars, bars, self.rules, 4)['outcome'], 'ambiguous')

    def test_finer_sequence_resolves_coarse_collision(self):
        bars = candles([[102, 103, 101, 102], [100.2, 102, 98, 99], [99, 100, 98, 99], [99, 100, 98, 99]], 3)
        fine = candles([[102, 103, 101, 102]]*3 + [[100.2, 100.3, 99.5, 100], [100, 102, 99.8, 101], [101, 101, 98, 99]] + [[99, 100, 98, 99]]*6)
        self.assertEqual(measure(event(), bars, fine, self.rules, 4)['outcome'], 'rejection')

    def test_incomplete_and_split_boundary(self):
        bars = candles([[102, 103, 101, 102], [100.2, 100.3, 99.5, 100], [100, 102, 99.5, 101]])
        truncated = measure(event(), bars, bars, self.rules, 2)
        self.assertEqual(truncated['outcome'], 'incomplete')
        self.assertFalse(truncated['return_complete'])
        self.assertFalse(truncated['excursion_complete'])
        summary = rates([truncated])
        self.assertIsNone(summary['return_rate'])
        self.assertIsNone(summary['rejection_rate'])

    def test_fill_is_separate_from_rejection(self):
        bars = candles([[102, 103, 101, 102], [100.2, 100.3, 99, 99.5], [99.5, 100, 98, 99], [99, 100, 98, 99]])
        outcome = measure(event(), bars, bars, self.rules, 4)
        self.assertTrue(outcome['far'])
        self.assertEqual(outcome['outcome'], 'failure')

    def test_repeated_visits_need_an_outside_candle(self):
        bars = candles([[102, 103, 101, 102], [100.2, 100.3, 99.5, 100], [100, 100.2, 99.5, 100], [101.5, 102, 101, 101.5], [100.2, 100.3, 99.5, 100], [100, 100.2, 99.5, 100]])
        result = measure(event(), bars, bars, {**self.rules, 'return_bars': 5}, 6)
        self.assertEqual(result['visits'], 2)

    def test_detection_is_prefix_causal(self):
        rng = np.random.default_rng(123)
        closes = 100+np.cumsum(rng.normal(0, 1, 300))
        bars = candles([[c-.2, c+.5, c-.5, c] for c in closes])
        full, _ = detect(bars, DEFAULTS)
        short, _ = detect(bars.iloc[:180], DEFAULTS)
        self.assertEqual(short, [e for e in full if e['confirmation'] < 180])
        self.assertTrue(any(e['family'] == 'fvg' for e in full))
        self.assertTrue(any(e['family'] == 'support_resistance' for e in full))

    def test_supply_demand_and_order_block_confirm_after_departure(self):
        bars = candles([[100, 100.5, 99.5, 100]]*30 + [[100.1, 100.2, 99.9, 100], [100.1, 100.2, 99.9, 100], [100.1, 100.2, 99.9, 100], [100, 103, 100, 102.5]])
        events, _ = detect(bars, DEFAULTS)
        zones = [e for e in events if e['family'] in ['supply_demand', 'order_block']]
        self.assertEqual({e['family'] for e in zones}, {'supply_demand', 'order_block'})
        self.assertTrue(all(e['confirmation'] == 33 and e['direction'] == 1 for e in zones))

    def test_matching_does_not_use_future_outcomes(self):
        rng = np.random.default_rng(44)
        close = 100+np.cumsum(rng.normal(0, .3, 350))
        bars = candles([[c-.1, c+.4, c-.4, c] for c in close])
        all_events, feat = detect(bars, DEFAULTS)
        early = [e for e in all_events if e['confirmation'] < 200]
        peers = match_controls(early, bars, feat, DEFAULTS, 25)
        bars.iloc[200:, :4] += 2000
        _, changed_feat = detect(bars, DEFAULTS)
        other = match_controls(early, bars, changed_feat, DEFAULTS, 25)
        self.assertEqual(peers, other)
        self.assertTrue(all(e['confirmation'] >= 25 for e in peers))

    def test_bootstrap_is_clustered_and_deterministic(self):
        def observations(outcome):
            return [dict(confirmation=i*100, outcome=outcome, return_complete=True, returned=True) for i in range(30)]
        patterns, controls = observations('rejection'), observations('failure')
        result = comparison(patterns, controls, DEFAULTS, 'rejection')
        self.assertEqual(result['difference'], 1.)
        self.assertEqual(result['interval_95'], [1., 1.])
        self.assertEqual(result, comparison(patterns, controls, DEFAULTS, 'rejection'))
        for e in patterns+controls:
            e['confirmation'] = 1
        self.assertIsNone(comparison(patterns, controls, DEFAULTS, 'rejection')['interval_95'])


if __name__ == '__main__':
    unittest.main()
