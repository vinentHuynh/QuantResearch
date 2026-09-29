"""Inference failure modes, shared resampling, and exit-cohort accounting."""
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import warnings

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "snd_zone_quality_report", ROOT / "scripts/report-snd-zone-quality.py"
)
report = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(report)

CASES = [
    {"symbol": "A", "variant": "baseline"},
    {"symbol": "A", "variant": "filter"},
]


def trades(dates=(), values=(), reasons=None):
    return pd.DataFrame({
        "exit_time": pd.to_datetime(list(dates), utc=True),
        "exit_reason": list(reasons) if reasons is not None else ["target"] * len(dates),
        "net_r": np.asarray(values, dtype=float),
    })


def weekly(values, start="2025-01-06"):
    dates = pd.date_range(start, periods=len(values), freq="7D", tz="UTC")
    return trades(dates, values)


def compare(frames, periods, cases=CASES, reps=1000):
    # Empty samples deliberately exercise nanstd's undefined variance path.
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="Degrees of freedom <= 0 for slice.")
        return report.simultaneous_contrasts(cases, frames, periods, reps=reps)


class BootstrapInferenceTests(unittest.TestCase):
    def test_zero_trades_are_unavailable_and_json_serializable(self):
        bounds = {"all": ["2025-01-06", "2025-04-28"]}
        populated = weekly(np.linspace(-1, 1, 16))
        for frames in ([populated, trades()], [trades(), trades()]):
            with self.subTest(both_empty=all(frame.empty for frame in frames)):
                records, metadata = compare(frames, bounds)
                self.assertIsNone(records[0]["delta_mean_r"])
                self.assertIsNone(records[0]["ci_low"])
                self.assertIsNone(records[0]["ci_high"])
                self.assertEqual(records[0]["usable_bootstraps"], 0)
                self.assertFalse(metadata["calibrated"])
                self.assertEqual(metadata["estimable_comparisons"], 0)
                # Production save rejects non-standard NaN JSON values.
                json.dumps({"records": records, "metadata": metadata}, allow_nan=False)

    def test_positive_degenerate_contrast_cannot_receive_passing_interval(self):
        cases = CASES + [
            {"symbol": "B", "variant": "baseline"},
            {"symbol": "B", "variant": "filter"},
        ]
        frames = [weekly([0.] * 16), weekly([1.] * 16),
                  weekly([0.] * 16), weekly(np.arange(16) / 16)]
        records, metadata = compare(
            frames, {"all": ["2025-01-06", "2025-04-28"]}, cases
        )
        degenerate, ordinary = records
        self.assertEqual(degenerate["delta_mean_r"], 1.)
        self.assertIsNone(degenerate["ci_low"])
        self.assertIsNone(degenerate["ci_high"])
        self.assertIsNone(degenerate["standard_error"])
        self.assertNotEqual(degenerate["estimability"], "estimable")
        self.assertFalse(degenerate["ci_low"] is not None and degenerate["ci_low"] > 0)
        self.assertEqual(ordinary["estimability"], "estimable")
        self.assertTrue(metadata["calibrated"])
        self.assertEqual(metadata["estimable_comparisons"], 1)

    def test_sparse_zero_denominator_draws_abstain_instead_of_conditioning(self):
        frames = [weekly(np.zeros(16)), trades(["2025-01-06", "2025-03-03"], [-1., 1.])]
        # One of four draws contains neither sparse observation. Nonempty
        # draws have variable contrasts, so sparsity is the rejection reason.
        weights = np.zeros((4, 16))
        weights[0, 0], weights[1, 8] = 16, 16
        weights[2, [0, 8]], weights[3, 4] = 8, 16
        with patch.object(report, "block_weights", return_value=weights):
            records, metadata = compare(
                frames, {"all": ["2025-01-06", "2025-04-28"]}, reps=4
            )
        self.assertEqual(records[0]["usable_bootstraps"], 3)
        self.assertIsNone(records[0]["ci_low"])
        self.assertFalse(metadata["calibrated"])

    def test_identical_periods_have_identical_uncertainty(self):
        frames = [weekly(np.sin(np.arange(16))), weekly(np.arange(16) / 8)]
        bounds = ["2025-01-06", "2025-04-28"]
        records, metadata = compare(frames, {"all": bounds, "later": bounds})
        self.assertTrue(metadata["calibrated"])
        first = {key: value for key, value in records[0].items() if key != "period"}
        second = {key: value for key, value in records[1].items() if key != "period"}
        self.assertEqual(first, second)

    def test_nested_period_uses_same_master_calendar_draw(self):
        frames = [weekly(np.zeros(8)), weekly(np.arange(8))]
        # Four explicit full-calendar draws have the same total week count.
        # Their later components imply means [5.5, 5.5, 4.5, 6.5].
        weights = np.array([
            [1, 1, 1, 1, 1, 1, 1, 1],
            [2, 2, 0, 0, 1, 1, 1, 1],
            [1, 1, 1, 1, 2, 2, 0, 0],
            [0, 0, 2, 2, 0, 0, 2, 2],
        ], dtype=float)
        periods = {"all": ["2025-01-06", "2025-03-03"],
                   "later": ["2025-02-03", "2025-03-03"]}
        with patch.object(report, "block_weights", return_value=weights) as draw:
            records, metadata = compare(frames, periods, reps=4)
        draw.assert_called_once()
        self.assertEqual(draw.call_args.args[0:2], (8, 4))
        self.assertTrue(metadata["calibrated"])
        self.assertEqual(records[0]["delta_mean_r"], 3.5)
        self.assertEqual(records[1]["delta_mean_r"], 5.5)
        self.assertAlmostEqual(records[0]["standard_error"], np.sqrt(.5))
        self.assertAlmostEqual(records[1]["standard_error"], np.sqrt(2 / 3))

    def test_empty_calendar_weeks_and_trade_weighted_ratio_are_preserved(self):
        baseline = trades(["2025-01-06"] * 3 + ["2025-01-20"], [1., 1., 1., -1.])
        variant = trades(["2025-01-06", "2025-01-20", "2025-01-20"], [2., 0., 0.])
        bounds = ["2025-01-06", "2025-02-03"]
        sums, counts = report.week_arrays([baseline, variant], bounds)
        np.testing.assert_array_equal(sums, [[3, 2], [0, 0], [-1, 0], [0, 0]])
        np.testing.assert_array_equal(counts, [[3, 1], [0, 0], [1, 2], [0, 0]])
        records, _ = compare([baseline, variant], {"all": bounds})
        # 2/3 - 2/4. Averaging the occupied weekly means would instead give 1.
        self.assertAlmostEqual(records[0]["delta_mean_r"], 1 / 6)
        self.assertEqual(records[0]["calendar_weeks"], 4)


class CohortBoundaryTests(unittest.TestCase):
    def test_source_open_and_forced_close_timestamps_partition_exactly_once(self):
        frame = trades(
            ["2025-01-06", "2025-01-06", "2025-01-13", "2025-01-13"],
            [1., 2., 3., 4.],
            ["stop", "contract-roll", "target", "end-of-test"],
        )
        periods = [["2024-12-30", "2025-01-06"],
                   ["2025-01-06", "2025-01-13"],
                   ["2025-01-13", "2025-01-20"]]
        selected = []
        for bounds, expected_indices, expected_sum in zip(periods, [[1], [0, 3], [2]], [2., 5., 3.]):
            lo, hi = [pd.Timestamp(date, tz="UTC") for date in bounds]
            indices = frame.index[report.cohort_mask(frame, lo, hi)].tolist()
            self.assertEqual(indices, expected_indices)
            selected.extend(indices)
            sums, counts = report.week_arrays([frame], bounds)
            self.assertEqual(sums.shape, (1, 1))
            self.assertEqual(sums.sum(), expected_sum)
            self.assertEqual(counts.sum(), len(expected_indices))
        self.assertEqual(sorted(selected), list(frame.index))

    def test_marked_pnl_and_closed_trade_cohorts_remain_distinct(self):
        frame = trades(["2025-01-08"], [1.])
        frame["net_pnl"], frame["cost"], frame["risk_cash"] = 10., 2., 10.
        equity = pd.DataFrame({
            "timestamp": pd.to_datetime(["2025-01-06", "2025-01-08", "2025-01-13"], utc=True),
            "equity": [100005., 100010., 100010.],
        })
        result = report.metrics(frame, equity, ["2025-01-06", "2025-01-13"])
        # Five dollars of this trade were already marked at the boundary.
        self.assertEqual(result["net_pnl"], 5.)
        self.assertEqual(result["closed_net"], 10.)
        self.assertEqual(result["double_cost_closed_net"], 8.)


if __name__ == "__main__":
    unittest.main()
