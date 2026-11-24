"""Synthetic, independently specified scenarios. No historical data is read."""
from pathlib import Path
import importlib.util
import unittest

import numpy as np

spec = importlib.util.spec_from_file_location("open_fade_replay", Path(__file__).with_name("replay.py"))
replay = importlib.util.module_from_spec(spec)
spec.loader.exec_module(replay)


def bars(price=100.):
    return np.tile([price, price, price, price], (135, 1)).astype(float)


def run(data, **kwargs):
    return replay.simulate_day(data, mode=kwargs.pop("mode", "touch"),
                               trigger=40., horizon=kwargs.pop("horizon", 60), **kwargs)


def mirror(data):
    return np.column_stack((200-data[:, 0], 200-data[:, 2],
                            200-data[:, 1], 200-data[:, 3]))


class ReplayChecks(unittest.TestCase):
    def test_no_trigger_is_explicit_zero_record(self):
        r = run(bars())
        self.assertFalse(r["filled"])
        self.assertEqual(r["status"], "no_trigger")
        self.assertEqual(r["gross_points"], 0.)
        self.assertEqual(r["net_points"], 0.)

    def test_exact_touch_in_first_bar_then_guaranteed_target(self):
        d = bars(130.)
        d[0] = [100, 140, 95, 115]
        r = run(d)
        self.assertTrue(r["filled"])
        self.assertTrue(r["bar0trigger"])
        self.assertEqual((r["entry_idx"], r["exit_idx"]), (0, 0))
        self.assertEqual((r["entry_price"], r["exit_price"]), (140., 120.))
        self.assertEqual(r["gross_points"], 20.)
        self.assertAlmostEqual(r["net_points"], 18.88)
        self.assertFalse(r["entrybar_target_ambiguous"])

    def test_entrybar_target_may_precede_entry(self):
        d = bars(130.)
        d[0] = [100, 145, 95, 130]
        a, b = run(d), run(d, policy="favorable")
        self.assertEqual(a["exit_reason"], "time_exit")
        self.assertEqual(a["gross_points"], 10.)
        self.assertEqual(b["gross_points"], 20.)
        self.assertTrue(a["entrybar_target_ambiguous"])
        self.assertTrue(b["entrybar_target_ambiguous"])

    def test_entrybar_target_exact_close_is_guaranteed(self):
        d = bars()
        d[0] = [100, 145, 95, 120]
        self.assertEqual(run(d)["exit_reason"], "target")

    def test_entrybar_stop_target_collision(self):
        d = bars(140.)
        d[0] = [100, 165, 90, 140]
        a, b = run(d), run(d, policy="favorable")
        self.assertEqual(a["gross_points"], -20.)
        self.assertEqual(b["gross_points"], 20.)
        self.assertTrue(a["bracket_collision"])
        self.assertTrue(b["bracket_collision"])

    def test_entry_gap_past_stop_wins_before_target_for_both_policies(self):
        d = bars(130.)
        d[0] = [100, 105, 95, 100]
        d[1] = [170, 180, 50, 100]
        for policy in ("conservative", "favorable"):
            r = run(d, policy=policy)
            self.assertEqual(r["side"], -1)
            self.assertFalse(r["direction_ambiguous"])
            self.assertTrue(r["entry_at_open"])
            self.assertEqual(r["exit_reason"], "stop_gap")
            self.assertEqual(r["exit_price"], 170.)
            self.assertEqual(r["gross_points"], -30.)

    def test_open_entry_target_hit_does_not_need_close_proof(self):
        d = bars(130.)
        d[0] = [100, 105, 95, 100]
        d[1] = [145, 150, 115, 145]
        r = run(d)
        self.assertTrue(r["entry_at_open"])
        self.assertEqual(r["exit_reason"], "target")

    def test_future_collision_and_open_gap_ordering(self):
        d = bars(130.)
        d[0] = [100, 145, 95, 130]
        d[1] = [130, 165, 115, 135]
        self.assertEqual(run(d)["exit_reason"], "stop_collision")
        # Favorable policy already takes ambiguous entry-minute target.
        d[0] = [100, 135, 95, 130]
        d[1] = [140, 145, 130, 135]  # Exact known opening entry.
        d[2] = [130, 165, 115, 135]
        self.assertEqual(run(d, policy="favorable")["exit_reason"], "target_collision")
        d[2] = [110, 170, 100, 150]
        self.assertEqual(run(d)["exit_reason"], "target_gap")
        self.assertEqual(run(d)["exit_price"], 120.)

    def test_deadline_open_excludes_future_range(self):
        d = bars(130.)
        d[0] = [100, 145, 95, 130]
        d[60] = [135, 180, 80, 150]
        r = run(d)
        self.assertEqual(r["exit_idx"], 60)
        self.assertEqual(r["exit_price"], 135.)
        self.assertEqual(r["exit_reason"], "time_exit")
        self.assertEqual(r["held_minutes"], 60.)

    def test_deadline_existing_bracket_gap_precedes_flatten(self):
        d = bars(130.)
        d[0] = [100, 145, 95, 130]
        d[60] = [110, 180, 80, 150]
        r = run(d)
        self.assertEqual(r["exit_reason"], "target_gap")
        self.assertEqual(r["exit_price"], 120.)
        self.assertTrue(r["deadline_gap_exit"])
        d[60] = [170, 180, 80, 150]
        r = run(d)
        self.assertEqual(r["exit_reason"], "stop_gap")
        self.assertEqual(r["exit_price"], 170.)

    def test_two_hour_last_allowed_entry_has_required_open(self):
        d = bars(130.)
        d[0] = [100, 105, 95, 100]
        d[14] = [130, 145, 125, 135]
        d[134] = [132, 180, 80, 150]
        r = run(d, horizon=120)
        self.assertEqual((r["entry_idx"], r["exit_idx"]), (14, 134))
        self.assertEqual(r["exit_price"], 132.)

    def test_no_new_trigger_at_cutoff(self):
        d = bars()
        d[15] = [100, 160, 40, 100]
        self.assertFalse(run(d)["filled"])

    def test_confirmation_samebar_next_open(self):
        d = bars(135.)
        d[0] = [100, 145, 95, 130]
        r = run(d, mode="confirm")
        self.assertEqual((r["trigger_idx"], r["confirmation_idx"], r["entry_idx"]), (0, 0, 1))
        self.assertEqual(r["entry_price"], 135.)
        self.assertEqual(r["stop_price"], 155.)
        self.assertEqual(r["target_price"], 115.)

    def test_confirmation_strict_close_and_later_confirmation(self):
        d = bars(135.)
        d[0] = [100, 145, 95, 140]  # Equality does not confirm.
        d[1] = [140, 150, 135, 145]
        d[2] = [145, 150, 130, 135]
        r = run(d, mode="confirm")
        self.assertEqual((r["confirmation_idx"], r["entry_idx"]), (2, 3))

    def test_confirmation_can_close_beyond_the_opposite_band(self):
        d = bars(50.)
        d[0] = [100, 145, 95, 140]
        d[1] = [140, 145, 45, 50]
        r = run(d, mode="confirm")
        self.assertEqual((r["side"], r["confirmation_idx"], r["entry_idx"]), (-1, 1, 2))

    def test_confirmation_never_returns_inside(self):
        d = bars(145.)
        d[0] = [100, 145, 95, 145]
        r = run(d, mode="confirm")
        self.assertFalse(r["filled"])
        self.assertEqual(r["status"], "armed_no_fill")
        self.assertEqual(r["exit_reason"], "no_confirmation")

    def test_confirmation_cannot_fill_at_cutoff(self):
        d = bars(145.)
        d[0] = [100, 145, 95, 145]
        d[14] = [145, 145, 130, 135]
        r = run(d, mode="confirm")
        self.assertFalse(r["filled"])
        self.assertEqual(r["confirmation_idx"], 14)
        self.assertEqual(r["exit_reason"], "entry_cutoff")

    def test_touch_delay_uses_next_open_price_and_cutoff(self):
        d = bars(135.)
        d[0] = [100, 145, 95, 130]
        r = run(d, delay_bars=1)
        self.assertEqual((r["entry_idx"], r["entry_price"]), (1, 135.))
        d = bars(130.)
        d[0] = [100, 105, 95, 100]
        d[14] = [130, 145, 125, 135]
        self.assertEqual(run(d, delay_bars=1)["exit_reason"], "entry_cutoff")

    def test_confirmation_extra_delay(self):
        d = bars(135.)
        d[0] = [100, 145, 95, 130]
        d[2] = [132, 138, 125, 135]
        r = run(d, mode="confirm", delay_bars=1)
        self.assertEqual((r["entry_idx"], r["entry_price"]), (2, 132.))

    def test_confirmation_extra_delay_crosses_entry_cutoff(self):
        d = bars(145.)
        d[0] = [100, 145, 95, 145]
        d[13] = [145, 145, 130, 135]
        self.assertTrue(run(d, mode="confirm")["filled"])
        delayed = run(d, mode="confirm", delay_bars=1)
        self.assertFalse(delayed["filled"])
        self.assertEqual(delayed["confirmation_idx"], 13)
        self.assertEqual(delayed["exit_reason"], "entry_cutoff")

    def test_dual_trigger_direction_branches_and_post_entry_target(self):
        d = bars(130.)
        d[0] = [100, 145, 55, 130]
        # Each assumed first threshold precedes the other threshold; this
        # proves the interior target is post-entry for each branch.
        r = run(d)
        self.assertTrue(r["direction_ambiguous"])
        self.assertEqual(len(r["branches"]), 2)
        self.assertTrue(r["trade_certain"])
        self.assertEqual(r["gross_points"], 20.)
        self.assertTrue(all(not b["entrybar_target_ambiguous"] for b in r["branches"]))

    def test_dual_confirmation_nofill_is_a_real_zero_cost_branch(self):
        d = bars(145.)
        d[0] = [100, 145, 55, 145]
        # Upper-first never confirms; lower-first confirms and fills long145.
        d[1] = [145, 170, 140, 165]
        a = run(d, mode="confirm")
        b = run(d, mode="confirm", policy="favorable")
        self.assertTrue(a["direction_ambiguous"])
        self.assertFalse(a["filled"])
        self.assertEqual(a["net_points"], 0.)
        self.assertTrue(a["trade_possible"])
        self.assertFalse(a["trade_certain"])
        self.assertTrue(b["filled"])
        self.assertAlmostEqual(b["net_points"], 18.88)
        # If fees exceed the winning branch's gross return, the worst branch
        # changes to the filled trade and the best branch becomes no fill.
        a = run(d, mode="confirm", round_trip_cost_points=25.)
        b = run(d, mode="confirm", policy="favorable", round_trip_cost_points=25.)
        self.assertTrue(a["filled"])
        self.assertEqual(a["net_points"], -5.)
        self.assertFalse(b["filled"])

    def test_dual_direction_one_branch_can_stop_before_other_band(self):
        d = bars(130.)
        d[0] = [100, 170, 55, 130]
        a, b = run(d), run(d, policy="favorable")
        self.assertEqual(a["side"], -1)
        self.assertEqual(a["gross_points"], -20.)
        self.assertEqual(b["gross_points"], 20.)
        self.assertTrue(a["direction_ambiguous"])
        self.assertTrue(a["bracket_collision"])

    def test_mirrored_price_paths(self):
        examples = []
        d = bars(130.); d[0] = [100, 145, 95, 130]; examples.append(d)
        d = bars(130.); d[0] = [100, 165, 90, 140]; examples.append(d)
        d = bars(135.); d[0] = [100, 145, 95, 130]; examples.append(d)
        for d in examples:
            for mode in ("touch", "confirm"):
                for policy in ("conservative", "favorable"):
                    for delay in (0, 1):
                        a = run(d, mode=mode, policy=policy, delay_bars=delay)
                        b = run(mirror(d), mode=mode, policy=policy, delay_bars=delay)
                        for key in ("filled", "gross_points", "net_points", "entry_idx", "exit_idx", "exit_reason", "held_minutes"):
                            self.assertEqual(a[key], b[key], (mode, policy, delay, key))
                        self.assertEqual(a["side"], -b["side"])

    def test_invalid_input_rejected(self):
        with self.assertRaises(ValueError): run(bars()[:70])
        d = bars(); d[10, 1] = 90.
        with self.assertRaises(ValueError): run(d)
        d = bars(); d[5, 0] = np.nan
        with self.assertRaises(ValueError): run(d)


if __name__ == "__main__":
    unittest.main(verbosity=2)
