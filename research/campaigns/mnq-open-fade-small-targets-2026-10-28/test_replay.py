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

    def test_small_target_with_unchanged_stop(self):
        d = bars(130.)
        d[0] = [100, 145, 95, 120]
        for points in (5., 10., 15.):
            for policy in ("conservative", "favorable"):
                r = run(d, target_points=points, policy=policy)
                self.assertEqual((r["target_points"], r["stop_points"]), (points, 20.))
                self.assertEqual((r["target_price"], r["stop_price"]), (140.-points, 160.))
                self.assertEqual(r["gross_points"], points)
                self.assertAlmostEqual(r["net_points"], points-1.12)

    def test_asymmetric_stop_target_collision(self):
        d = bars(130.)
        d[0] = [100, 150, 95, 130]
        a = run(d, target_points=30., stop_points=5.)
        b = run(d, target_points=30., stop_points=5., policy="favorable")
        self.assertEqual(a["gross_points"], -5.)
        self.assertEqual(b["gross_points"], 30.)
        self.assertTrue(a["bracket_collision"])

    def test_distances_exist_on_no_fill_and_are_independently_defaulted(self):
        a = run(bars(), target_points=5.)
        b = run(bars(), stop_points=5.)
        self.assertEqual((a["target_points"], a["stop_points"]), (5., 20.))
        self.assertEqual((b["target_points"], b["stop_points"]), (20., 5.))
        self.assertFalse(a["filled"])

    def test_invalid_bracket_distances_rejected(self):
        for field in ("target_points", "stop_points"):
            for invalid in (0., -1., float("nan"), float("inf"), .1, True, "5"):
                with self.subTest(field=field, invalid=invalid):
                    with self.assertRaises(ValueError):
                        run(bars(), **{field: invalid})
        # Tick-valid trigger can have a non-tick half-distance; no rounding is
        # performed implicitly when defaults resolve to such a value.
        with self.assertRaises(ValueError):
            replay.simulate_day(bars(), mode="touch", trigger=40.25, horizon=60)
        r = run(bars(), target_points=np.float64(5.25), stop_points=np.int64(20))
        self.assertEqual(r["target_points"], 5.25)

    def test_dual_trigger_target_at_opposite_band_is_guaranteed(self):
        d = bars()
        d[0] = [100, 155, 45, 100]
        r = run(d, target_points=80., stop_points=200.)
        self.assertEqual(r["gross_points"], 80.)
        self.assertFalse(r["entrybar_target_ambiguous"])
        self.assertTrue(all(b["target_points"] == 80. for b in r["branches"]))

    def test_dual_trigger_target_beyond_opposite_band_not_forced(self):
        d = bars()
        d[0] = [100, 155, 45, 100]
        a = run(d, target_points=90., stop_points=200.)
        b = run(d, target_points=90., stop_points=200., policy="favorable")
        self.assertTrue(a["entrybar_target_ambiguous"])
        self.assertEqual(a["exit_reason"], "time_exit")
        self.assertEqual(a["gross_points"], 40.)
        self.assertEqual(b["gross_points"], 90.)

    def test_asymmetric_gap_stop_and_target_no_improvement(self):
        d = bars(130.)
        d[0] = [100, 105, 95, 100]
        d[1] = [148, 160, 110, 145]
        for policy in ("conservative", "favorable"):
            r = run(d, target_points=10., stop_points=5., policy=policy)
            self.assertEqual(r["exit_reason"], "stop_gap")
            self.assertEqual(r["gross_points"], -8.)
        d[1] = [140, 145, 136, 140]
        d[2] = [125, 150, 120, 140]
        r = run(d, target_points=5., stop_points=20.)
        self.assertEqual(r["exit_reason"], "target_gap")
        self.assertEqual(r["gross_points"], 5.)

    def test_small_target_deadline_gap_caps_profit(self):
        d = bars(140.)
        d[0] = [100, 145, 95, 140]
        d[60] = [130, 180, 80, 150]
        r = run(d, target_points=5., stop_points=20.)
        self.assertEqual(r["exit_reason"], "target_gap")
        self.assertTrue(r["deadline_gap_exit"])
        self.assertEqual(r["gross_points"], 5.)

    def test_small_target_fee_aware_ambiguous_no_fill_branch(self):
        d = bars(145.)
        d[0] = [100, 145, 55, 145]
        d[1] = [145, 170, 140, 165]
        a = run(d, mode="confirm", target_points=5., round_trip_cost_points=6.)
        b = run(d, mode="confirm", target_points=5., round_trip_cost_points=6.,
                policy="favorable")
        self.assertTrue(a["filled"])
        self.assertEqual(a["net_points"], -1.)
        self.assertFalse(b["filled"])
        self.assertEqual(b["net_points"], 0.)
        self.assertTrue(all(x["target_points"] == 5. for x in a["branches"]))

    def test_asymmetric_brackets_mirror(self):
        d = bars(130.)
        d[0] = [100, 150, 95, 130]
        for mode in ("touch", "confirm"):
            for policy in ("conservative", "favorable"):
                for delay in (0, 1):
                    a = run(d, mode=mode, policy=policy, delay_bars=delay,
                            target_points=5., stop_points=30.)
                    b = run(mirror(d), mode=mode, policy=policy, delay_bars=delay,
                            target_points=5., stop_points=30.)
                    for key in ("filled", "gross_points", "net_points", "entry_idx",
                                "exit_idx", "exit_reason", "target_points", "stop_points"):
                        self.assertEqual(a[key], b[key], (mode, policy, delay, key))
                    self.assertEqual(a["side"], -b["side"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
