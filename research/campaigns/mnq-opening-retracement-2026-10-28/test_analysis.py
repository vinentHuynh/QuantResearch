import importlib.util
from pathlib import Path
import unittest

import numpy as np

SPEC = importlib.util.spec_from_file_location('retracement_analysis', Path(__file__).with_name('analysis.py'))
analysis = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(analysis)


def bars(first, *following):
    rows = [first, *following]
    rows += [[rows[-1][3]]*4 for _ in range(15-len(rows))]
    return np.array(rows, dtype=float)


class TestRetracementBounds(unittest.TestCase):
    def test_pretrigger_extreme_is_only_possible(self):
        r = analysis.analyze_day(bars([20000,20050,20000,20045]), 40, 10)
        self.assertEqual((r['any_retracement_certain'],r['any_retracement_possible']), (0,1))
        self.assertEqual(set(r['outcomes']), {'retracement','neither'})

    def test_later_retracement_resolves_pretrigger_uncertainty(self):
        r = analysis.analyze_day(bars([20000,20050,20000,20045], [20045,20050,20025,20040]), 40, 10)
        self.assertEqual(r['outcomes'], ['retracement'])
        self.assertEqual(r['any_retracement_certain'], 1)

    def test_retracement_after_stop_is_not_guaranteed_target_first(self):
        r = analysis.analyze_day(bars([20000,20070,20000,20025]), 40, 10)
        self.assertEqual(r['any_retracement_certain'], 1)
        self.assertEqual(set(r['outcomes']), {'retracement','continuation'})

    def test_both_bands_force_retracement_without_stop(self):
        r = analysis.analyze_day(bars([20000,20050,19950,20000]), 40, 10)
        self.assertTrue(r['direction_ambiguous'])
        self.assertEqual(r['any_retracement_certain'], 1)
        self.assertEqual(r['outcomes'], ['retracement'])

    def test_both_direction_branches_are_retained(self):
        r = analysis.analyze_day(bars([20000,20070,19950,20000]), 40, 10)
        self.assertEqual(len(r['branches']), 2)
        self.assertEqual(r['any_retracement_certain'], 1)
        self.assertEqual(set(r['outcomes']), {'retracement','continuation'})

    def test_opening_trigger_makes_its_extremes_posttrigger(self):
        r = analysis.analyze_day(bars([20000]*4, [20045,20050,20025,20045]), 40, 10)
        self.assertTrue(r['trigger_at_minute_open'])
        self.assertEqual(r['any_retracement_certain'], 1)
        self.assertEqual(r['outcomes'], ['retracement'])

    def test_gap_beyond_nominal_stop_has_open_priority(self):
        r = analysis.analyze_day(bars([20000]*4, [20065,20070,20020,20040]), 40, 10)
        self.assertEqual(r['outcomes'], ['continuation'])
        self.assertEqual(r['any_retracement_certain'], 1)

    def test_intrabar_stop_removes_live(self):
        r = analysis.analyze_day(bars([20000,20035,20000,20035], [20035,20070,20034,20065]), 40, 10)
        self.assertEqual(r['outcomes'], ['continuation'])
        self.assertEqual(r['any_retracement_possible'], 0)

    def test_later_open_priority_and_collision(self):
        first = [[20000,20035,20000,20035], [20035,20045,20034,20040]]
        r = analysis.analyze_day(bars(*first, [20025,20070,20020,20040]), 40, 10)
        self.assertEqual(r['outcomes'], ['retracement'])
        r = analysis.analyze_day(bars(*first, [20065,20070,20020,20040]), 40, 10)
        self.assertEqual(r['outcomes'], ['continuation'])
        r = analysis.analyze_day(bars(*first, [20040,20070,20020,20040]), 40, 10)
        self.assertEqual(set(r['outcomes']), {'retracement','continuation'})

    def test_no_trigger_and_deadline_exclusion(self):
        b = bars([20000,20035,20000,20035])
        self.assertFalse(analysis.analyze_day(b,40,10)['triggered'])
        b[14] = [20035,20045,20034,20040]
        before = analysis.analyze_day(b,40,10)
        self.assertEqual(before['outcomes'], ['neither'])
        after = analysis.analyze_day(np.vstack([b,[20000,20100,19900,20000]]),40,10)
        self.assertEqual(before, after)

    def test_mirrored_prices_preserve_bounds(self):
        b = bars([20000,20070,20000,20045], [20045,20055,20025,20050])
        mirror = 40000-b[:,[0,2,1,3]]
        a, c = analysis.analyze_day(b,40,10), analysis.analyze_day(mirror,40,10)
        self.assertEqual(a['outcomes'], c['outcomes'])
        for key in analysis.METRICS:
            for bound in ('certain','possible'):
                self.assertEqual(a[key+'_'+bound], c[key+'_'+bound])

    def test_random_observed_paths_are_covered_by_bounds(self):
        rng = np.random.default_rng(20261028)
        for _ in range(400):
            price = 20000 + np.r_[0,np.cumsum(rng.integers(-80,81,size=119))]*.25
            groups = price.reshape(15,8)
            b = np.c_[groups[:,0],groups.max(axis=1),groups.min(axis=1),groups[:,-1]]
            for d in (40,60,80):
                eligible = np.flatnonzero(abs(price-price[0]) >= d)
                for t in (5,10,15):
                    r = analysis.analyze_day(b,d,t)
                    self.assertEqual(r['triggered'], bool(len(eligible)))
                    if not len(eligible):
                        continue
                    idx = eligible[0]
                    signed = (price[idx:]-price[0])*np.sign(price[idx]-price[0])
                    actual_any = int((signed <= d-t).any())
                    self.assertLessEqual(r['any_retracement_certain'], actual_any)
                    self.assertLessEqual(actual_any, r['any_retracement_possible'])
                    actual = 'neither'
                    for value in signed:
                        if value >= d+d/2:
                            actual = 'continuation'
                            break
                        if value <= d-t:
                            actual = 'retracement'
                            break
                    self.assertIn(actual, r['outcomes'])


if __name__ == '__main__':
    unittest.main()
