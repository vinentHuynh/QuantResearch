"""Exact numeric-output reconstruction, including empty and Numba-list schemas."""
import unittest

import numpy as np
import pandas as pd
from numba.typed import List

from strategies import _snd_combination_reference as reference
from strategies import _snd_combination_fast_io as adapter
from test_snd_zone_quality import fixture, run


def arrays(trades, equity):
    values = [row.copy() for row in trades[list(adapter.FLOAT_COLUMNS)].to_numpy(float)]
    times = [row.copy() for row in np.column_stack([pd.to_datetime(trades[name], utc=True).astype("int64") for name in adapter.TIME_COLUMNS])]
    reasons = [np.int64(adapter.REASONS.index(reason)) for reason in trades.exit_reason]
    return values, times, reasons, equity[list(adapter.EQUITY_VALUE_COLUMNS)].to_numpy(float), pd.to_datetime(equity.timestamp, utc=True).astype("int64").to_numpy()


class FastIOTests(unittest.TestCase):
    def test_roundtrips_reference_frames_for_sides_geometry_and_eligibility(self):
        for mirror in (False, True):
            for boundary in ("wick", "body"):
                for eligibility in ("first_touch", "any_touch"):
                    with self.subTest(mirror=mirror, boundary=boundary, eligibility=eligibility):
                        result = run(fixture(mirror=mirror, minute=True), model=reference,
                                     zone_boundary=boundary, entry_eligibility=eligibility)
                        self.assertGreater(len(result["trades"]), 0)
                        trades, equity = adapter.frames_from_arrays(*arrays(result["trades"], result["equity"]), result["parameters"])
                        pd.testing.assert_frame_equal(trades, result["trades"], check_exact=True)
                        pd.testing.assert_frame_equal(equity, result["equity"], check_exact=True)
                        self.assertEqual(trades.opposing_boundary.dtype, np.dtype("float64"))

    def test_numba_lists_all_reasons_and_nanosecond_precision(self):
        result = run(fixture(minute=True), model=reference)
        trades = pd.concat([result["trades"]] * 4, ignore_index=True)
        trades["exit_reason"] = adapter.REASONS
        for column in adapter.TIME_COLUMNS:
            trades[column] += pd.to_timedelta(np.arange(4) + 1, unit="ns")
        trades["ambiguous_entry"] = [True, False, True, False]
        trades["ambiguous_exit"] = [False, True, False, True]
        trades["entry_bar_target_ignored"] = True
        values = arrays(trades, result["equity"])
        typed = []
        for collection in values[:3]:
            rows = List()
            for row in collection:
                rows.append(row)
            typed.append(rows)
        actual, equity = adapter.frames_from_arrays(*typed, *values[3:], result["parameters"])
        pd.testing.assert_frame_equal(actual, trades, check_exact=True)
        pd.testing.assert_frame_equal(equity, result["equity"], check_exact=True)

    def test_empty_frames_keep_reference_object_schemas_and_nonempty_equity(self):
        result = run(fixture(minute=True), model=reference, max_zone_width_atr=0.)
        self.assertTrue(result["trades"].empty)
        trades, equity = adapter.frames_from_arrays(*arrays(result["trades"], result["equity"]), result["parameters"])
        pd.testing.assert_frame_equal(trades, result["trades"], check_exact=True)
        pd.testing.assert_frame_equal(equity, result["equity"], check_exact=True)
        trades, equity = adapter.frames_from_arrays([], [], [], np.empty((0, 5)), np.empty(0, dtype=np.int64), {})
        pd.testing.assert_frame_equal(trades, pd.DataFrame(columns=reference.TRADE_COLUMNS), check_exact=True)
        pd.testing.assert_frame_equal(equity, pd.DataFrame(columns=adapter.EQUITY_COLUMNS), check_exact=True)

    def test_inconsistent_lengths_unknown_reason_and_bad_width_fail(self):
        row = np.zeros(len(adapter.FLOAT_COLUMNS))
        times = np.zeros(len(adapter.TIME_COLUMNS), dtype=np.int64)
        for values, stamps, reasons in (([row], [], [0]), ([row], [times], [-1]),
                                        ([row[:-1]], [times], [0])):
            with self.assertRaises(ValueError):
                adapter.frames_from_arrays(values, stamps, reasons, [], [], {"entry_eligibility": "first_touch"})


if __name__ == "__main__":
    unittest.main()
