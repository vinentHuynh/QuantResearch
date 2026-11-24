"""Synthetic-only causal and state-machine checks; no market file is loaded."""
from collections import deque
from datetime import datetime, timedelta
import importlib.util
from pathlib import Path
import unittest
from zoneinfo import ZoneInfo

spec = importlib.util.spec_from_file_location("opening_scalp_replay", Path(__file__).with_name("replay.py"))
replay = importlib.util.module_from_spec(spec)
spec.loader.exec_module(replay)
START = datetime(2026, 10, 28, 9, 30, tzinfo=ZoneInfo("America/New_York"))


def ticks(pairs):
    return [{"timestamp": START+timedelta(seconds=seconds), "price": price} for seconds, price in pairs]


def mark(price):
    return {"timestamp": START+timedelta(minutes=15), "price": price}


def run(pairs, **kwargs):
    return replay.simulate_session(ticks(pairs), trigger_points=kwargs.pop("trigger_points", 40),
                                  target_points=kwargs.pop("target_points", 5), **kwargs)


class PrototypeChecks(unittest.TestCase):
    def test_immediate_entry_and_later_target_within_same_minute(self):
        r = run([(0, 100), (1, 140), (2, 134)])
        t = r["trades"][0]
        self.assertEqual((t["entry_event_index"], t["exit_event_index"]), (1, 2))
        self.assertEqual((t["entry_price"], t["exit_price"]), (140., 135.))
        self.assertEqual(t["gross_points"], 5.)
        self.assertAlmostEqual(t["net_dollars"], 7.76)

    def test_actual_observed_crossing_price_anchors_gap_entry(self):
        r = run([(0, 100), (1, 150), (2, 144)])
        t = r["trades"][0]
        self.assertEqual((t["crossed_level"], t["entry_price"], t["target_price"]), (140., 150., 145.))

    def test_equal_timestamps_keep_supplied_order(self):
        r = run([(0, 100), (1, 140), (1, 135)])
        t = r["trades"][0]
        self.assertEqual(t["held_seconds"], 0.)
        self.assertGreater(t["exit_event_index"], t["entry_event_index"])

    def test_same_minute_ohlc_can_have_two_different_outcomes(self):
        target_first = run([(0, 100), (1, 140), (2, 135), (3, 165), (4, 140)])
        stop_first = run([(0, 100), (1, 140), (2, 165), (3, 135), (4, 140)], deadline_mark=mark(140))
        self.assertEqual(target_first["trades"][0]["exit_reason"], "target")
        self.assertEqual(stop_first["trades"][0]["exit_reason"], "stop_gap")
        self.assertNotEqual(target_first["trades"][0]["gross_points"], stop_first["trades"][0]["gross_points"])

    def test_three_entry_cap_and_no_same_event_rearm(self):
        r = run([(0, 100), (1, 140), (2, 135), (3, 130), (4, 140),
                 (5, 135), (6, 130), (7, 140), (8, 135), (9, 130), (10, 140)])
        self.assertEqual(r["entry_count"], 3)
        self.assertEqual(r["trade_count"], 3)
        self.assertEqual([t["entry_event_index"] for t in r["trades"]], [1, 4, 7])
        self.assertEqual([a["event_index"] for a in r["event_audit"] if a["event"] == "rearmed"], [3, 6])

    def test_identical_ohlc_one_stop_or_three_targets(self):
        stopped = [20000, 19999, 20040, 20060, 20061, 20030]
        scalped = [20000, 19999, 20040, 20030, 20035, 20040,
                   20030, 20035, 20040, 20030, 20061, 20030]
        ohlc = lambda prices: (prices[0], max(prices), min(prices), prices[-1])
        self.assertEqual(ohlc(stopped), ohlc(scalped))
        a = run(list(enumerate(stopped)), target_points=10)
        b = run(list(enumerate(scalped)), target_points=10)
        self.assertEqual([t["exit_reason"] for t in a["trades"]], ["stop"])
        self.assertEqual([t["exit_reason"] for t in b["trades"]], ["target"]*3)
        self.assertAlmostEqual(a["net_dollars"], -42.24)
        self.assertAlmostEqual(b["net_dollars"], 53.28)

    def test_exit_inside_band_does_not_itself_rearm(self):
        r = run([(0, 100), (1, 140), (2, 135), (3, 140), (4, 130), (5, 140)], deadline_mark=mark(140))
        self.assertEqual([t["entry_event_index"] for t in r["trades"]], [1, 5])

    def test_gap_from_one_outside_band_to_other_cannot_rearm(self):
        r = run([(0, 100), (1, 140), (2, 165), (3, 55), (4, 60), (5, 70)])
        self.assertEqual(r["entry_count"], 1)

    def test_warmup_rejected_cross_requires_reset_and_fresh_cross(self):
        r = run([(0, 100), (60, 140), (120, 141), (121, 139), (122, 140), (123, 135)],
                policy="after_two_minutes")
        self.assertEqual(r["rejected_crossings"][0]["reason"], "before_09_32")
        self.assertEqual(r["trades"][0]["entry_event_index"], 4)

    def test_low_progress_exact_point_35_boundary(self):
        r = run([(0, 100), (10, 160), (20, 40), (30, 100), (119, 130), (120, 142), (121, 136)],
                policy="low_directional_progress")
        t = r["trades"][0]
        self.assertEqual(t["entry_feature"]["directional_progress"], .35)
        self.assertTrue(t["entry_feature"]["low_progress_pass"])
        self.assertEqual(t["entry_price"], 142.)

    def test_low_progress_above_boundary_rejects_without_later_chase(self):
        r = run([(0, 100), (10, 160), (20, 40), (30, 100), (119, 130),
                 (120, 142.25), (121, 142), (122, 141)], policy="low_directional_progress")
        self.assertEqual(r["entry_count"], 0)
        self.assertEqual(r["rejected_crossings"][-1]["reason"], "directional_progress_above_0_35")

    def test_boundary_anchor_uses_last_equal_timestamp_record(self):
        r = run([(0, 100), (0, 105), (10, 160), (20, 40), (30, 100), (119, 130), (120, 142), (121, 136)],
                policy="low_directional_progress")
        f = r["trades"][0]["entry_feature"]
        self.assertEqual((f["anchor_event_index"], f["anchor_price"]), (1, 105.))

    def test_missing_120_second_anchor_and_zero_width(self):
        r = run([(5, 100), (100, 130), (120, 140)], policy="low_directional_progress")
        self.assertEqual(r["entry_count"], 0)
        self.assertEqual(r["rejected_crossings"][0]["reason"], "missing_120_second_anchor")
        f = replay._feature(deque([(0, START, 100.), (1, START+timedelta(seconds=120), 100.)]), START+timedelta(seconds=120))
        self.assertFalse(f["positive_width"])
        self.assertFalse(f["low_progress_pass"])

    def test_exact_boundary_is_stable_across_tick_aligned_ranges(self):
        for width in (5., 15., 45., 65., 120.):
            current = 100+width*7/20
            f = replay._feature(deque([(0, START, 100.),
                                       (1, START+timedelta(seconds=1), 100+width),
                                       (2, START+timedelta(seconds=120), current)]),
                                START+timedelta(seconds=120))
            self.assertTrue(f["low_progress_pass"], width)

    def test_old_anchor_staleness_is_disclosed(self):
        r = run([(0, 100), (10, 160), (20, 40), (30, 100), (239, 130), (240, 140)],
                policy="low_directional_progress", deadline_mark=mark(140))
        f = r["rejected_crossings"][-1]["feature"]
        self.assertEqual(f["anchor_timestamp"], (START+timedelta(seconds=30)).isoformat())
        self.assertEqual(f["anchor_staleness_seconds"], 90.)

    def test_no_entry_at_deadline(self):
        r = run([(0, 100), (899, 130), (900, 140), (901, 50)])
        self.assertEqual(r["entry_count"], 0)

    def test_explicit_deadline_mark_flattens_without_inferring_brackets(self):
        r = run([(0, 100), (899, 140), (900, 200), (901, 50)], deadline_mark=mark(130))
        t = r["trades"][0]
        self.assertEqual(t["exit_timestamp"], (START+timedelta(seconds=900)).isoformat())
        self.assertEqual(t["exit_reason"], "deadline_flatten")
        self.assertEqual(t["exit_price"], 130.)
        self.assertTrue(r["deadline_mark_used"])

    def test_missing_deadline_mark_does_not_use_later_tick(self):
        with self.assertRaises(replay.IncompleteSessionError) as caught:
            run([(0, 100), (899, 140), (900, 200), (901, 50)])
        result = caught.exception.result
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(result["final_position"], -1)
        self.assertEqual(result["trade_count"], 0)

    def test_stop_gap_uses_adverse_observed_price(self):
        r = run([(0, 100), (1, 140), (2, 170)])
        t = r["trades"][0]
        self.assertEqual((t["exit_reason"], t["exit_price"], t["gross_points"]), ("stop_gap", 170., -30.))

    def test_future_perturbation_does_not_change_earlier_feature_or_entry(self):
        common = [(0, 100), (10, 160), (20, 40), (30, 100), (119, 130), (120, 142)]
        a = run(common+[(121, 136), (500, 110)], policy="low_directional_progress")
        b = run(common+[(121, 170), (500, 90)], policy="low_directional_progress")
        for key in ("entry_event_index", "entry_price", "entry_timestamp", "entry_feature"):
            self.assertEqual(a["trades"][0][key], b["trades"][0][key])

    def test_history_includes_held_and_exit_records(self):
        r = run([(0, 100), (1, 140), (2, 170), (3, 100), (119, 130), (120, 140)],
                deadline_mark=mark(140))
        self.assertEqual(r["trades"][1]["entry_feature"]["range_high"], 170.)

    def test_mirrored_paths_preserve_accounting(self):
        pairs = [(0, 100), (1, 140), (2, 135), (3, 130), (4, 140), (5, 165)]
        a = run(pairs)
        b = run([(t, 200-p) for t, p in pairs])
        self.assertEqual(a["gross_points"], b["gross_points"])
        self.assertEqual(a["net_dollars"], b["net_dollars"])
        for x, y in zip(a["trades"], b["trades"]):
            self.assertEqual(x["side"], -y["side"])
            self.assertEqual(x["exit_reason"], y["exit_reason"])

    def test_all_27_frozen_configurations_are_callable(self):
        for policy in replay.POLICIES:
            for distance in (40, 60, 80):
                for target in (5, 10, 15):
                    r = run([(0, 200), (120, 200+distance), (121, 200+distance-target)],
                            trigger_points=distance, target_points=target, policy=policy)
                    self.assertEqual(r["status"], "complete")
                    if policy == "low_directional_progress":
                        self.assertEqual(r["entry_count"], 0)
                    else:
                        self.assertEqual(r["trades"][0]["gross_points"], target)

    def test_bad_data_and_marks_rejected(self):
        with self.assertRaises(ValueError): run([(0, 100), (-1, 140)])
        with self.assertRaises(ValueError): run([(0, 100.1)])
        with self.assertRaises(ValueError): run([(0, float("nan"))])
        with self.assertRaises(ValueError): run([(0, 0)])
        with self.assertRaises(ValueError): replay.simulate_session([{"timestamp": "2026-10-28T09:30:00", "price": 100}], trigger_points=40, target_points=5)
        with self.assertRaises(replay.IncompleteSessionError): run([(60, 100), (120, 140)])
        with self.assertRaises(ValueError): run([(0, 100)], deadline_mark={"timestamp": START+timedelta(seconds=901), "price": 100})


if __name__ == "__main__":
    unittest.main(verbosity=2)
