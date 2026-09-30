import unittest

import pandas as pd

from strategies.multi_touch_cluster_failure import MultiTouchClusterFailure


class MultiTouchClusterFailureTests(unittest.TestCase):
    def bars(self, sweep=True):
        rows = [dict(open=100., high=101., low=99., close=100., volume=1)
                for _ in range(60)]
        rows[20]['high'] = 102.
        rows[27]['high'] = 102.
        if sweep:
            rows[31].update(high=103., close=102.)
        else:
            rows[31].update(high=102., close=100.)
        index = pd.date_range('2024-01-01', periods=len(rows), freq='15min', tz='UTC')
        return pd.DataFrame(rows, index=index)

    def decisions(self, bars):
        model = MultiTouchClusterFailure(bars, {'dataset': {'tick_size': 0.25}})
        found = []
        for i, (_, bar) in enumerate(bars.iterrows()):
            decision = model.on_close(i, bar, {'position': 0, 'position_at_open': 0,
                                               'tradable': True})
            if decision is not None:
                found.append((i, decision))
        return found

    def test_second_pivot_must_confirm_before_later_sweep(self):
        found = self.decisions(self.bars())
        self.assertEqual(len(found), 1)
        index, decision = found[0]
        self.assertEqual(index, 31)
        self.assertEqual(decision['target'], -1)
        self.assertEqual(decision['timing'], 'next-open')
        self.assertEqual(decision['bracket'][0], 103.25)

    def test_shallow_first_visit_retires_cluster(self):
        bars = self.bars(sweep=False)
        bars.iloc[33, bars.columns.get_loc('high')] = 103.
        bars.iloc[33, bars.columns.get_loc('close')] = 102.
        self.assertEqual(self.decisions(bars), [])


if __name__ == '__main__':
    unittest.main()
