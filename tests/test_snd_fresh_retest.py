"""Independent lifecycle, room, chronology and accounting fixtures; no tuning."""
import unittest

import numpy as np
import pandas as pd

from strategies import _snd_fresh_retest as fresh
from strategies import _transcript_supply_demand as original


BASE = [(100, 101, 99, 99.5), (99.5, 104, 99.5, 103),
        (103, 104, 102, 103.5), (102, 103, 100, 102)]


def prepared(rows, mirror=False, minute=False):
    frame = pd.DataFrame(rows, columns=["open", "high", "low", "close"])
    if minute:
        frame = frame.loc[frame.index.repeat(5)].reset_index(drop=True)
    frame.index = pd.date_range("2026-01-05 12:00:00+00:00", periods=len(frame),
                                freq="1min" if minute else "5min")
    if mirror:
        old = frame.copy()
        frame["open"], frame["close"] = 250 - old.open, 250 - old.close
        frame["high"], frame["low"] = 250 - old.low, 250 - old.high
    result = fresh.prepare_data(frame, pivot_len=1, execution_minutes=1 if minute else 5)
    result["chart"]["bias"] = -1 if mirror else 1
    result["chart"]["hourly_bias"] = -1 if mirror else 1
    return result


def run(data, start=None, end=None, model=fresh, **options):
    params = dict(pivot_len=1, execution_minutes=data["execution_minutes"])
    params.update(options)
    return model.run_model(data, params, start or data["source"].index[0],
                           end or data["source"].index[-1] + pd.Timedelta(minutes=data["execution_minutes"]),
                           tick_size=.25, point_value=2, fee=1, slippage_ticks=1)


def context_fixture(last, boundary=114, mirror=False):
    # Opposing supply forms while long bias remains in force. This is valid
    # context, despite never being an eligible short entry-zone formation.
    b = boundary
    context = [(b + .5, b + 2, b, b + 1),
               (b + 1, b + 1.5, b - 4, b - 3),
               (b - 4, b - 3, b - 5, b - 4)]
    return prepared(context + BASE + last, mirror=mirror)


class FreshTouchTests(unittest.TestCase):
    def test_first_touch_arms_next_bucket_and_exports_audit_fields(self):
        data = prepared(BASE + [(104, 105, 103.5, 104.5)])
        result = run(data)
        self.assertEqual(len(result["trades"]), 1)
        trade = result["trades"].iloc[0]
        self.assertEqual(trade.first_touch_time, data["chart"].index[3])
        self.assertEqual(trade.signal_time, data["chart"].index[4])
        self.assertEqual(trade.entry_reference, 103.25)
        self.assertEqual(trade.entry, 104)
        self.assertEqual(trade.initial_risk, 5.25)
        self.assertEqual(trade.initial_risk_cash, 10.5)
        self.assertTrue(np.isinf(trade.opposing_room_r))

    def test_no_second_bucket_rearming_after_missed_order(self):
        data = prepared(BASE + [(102, 103, 101, 102), (104, 105, 103.5, 104.5)])
        fresh_result = run(data)
        legacy = run(data, first_touch_only=False, min_opposing_room_r=0)
        self.assertEqual(len(fresh_result["trades"]), 0)
        self.assertEqual(len(legacy["trades"]), 1)
        self.assertEqual(fresh_result["diagnostics"]["entry_orders_armed"], 1)
        self.assertEqual(fresh_result["diagnostics"]["orders_expired"], 1)

    def test_warmup_first_touch_is_permanently_consumed(self):
        data = prepared(BASE + [(104, 105, 103.5, 104.5), (103, 104, 100, 103)])
        result = run(data, start=data["chart"].index[4])
        self.assertEqual(len(result["trades"]), 0)
        self.assertEqual(result["diagnostics"]["entry_orders_armed"], 0)
        self.assertEqual(result["diagnostics"]["first_touches_warmup"], 1)

    def test_misaligned_first_touch_is_permanently_consumed(self):
        for column in ("bias", "hourly_bias"):
            data = prepared(BASE + [(102, 103, 101, 102), (104, 105, 103.5, 104.5)])
            data["chart"].iloc[3, data["chart"].columns.get_loc(column)] = -1
            result = run(data)
            self.assertEqual(len(result["trades"]), 0)
            self.assertEqual(result["diagnostics"]["entry_orders_armed"], 0)
            self.assertEqual(result["diagnostics"]["first_touches_misaligned"], 1)

    def test_first_touch_before_midbucket_scoring_start_stays_consumed(self):
        data = prepared(BASE + [(104, 105, 103.5, 104.5)], minute=True)
        result = run(data, start=data["source"].index[17])
        self.assertEqual(len(result["trades"]), 0)
        self.assertEqual(result["diagnostics"]["entry_orders_armed"], 0)
        self.assertEqual(result["diagnostics"]["first_touches_warmup"], 1)

    def test_incomplete_first_touch_is_permanently_consumed(self):
        data = prepared(BASE + [(102, 103, 100, 102), (104, 105, 103.5, 104.5)], minute=True)
        source = data["source"].drop(index=data["source"].index[17])
        data = fresh.prepare_data(source, 1, 1)
        data["chart"]["bias"] = data["chart"]["hourly_bias"] = 1
        result = run(data)
        self.assertFalse(data["chart"].complete.iloc[3])
        self.assertEqual(len(result["trades"]), 0)
        self.assertEqual(result["diagnostics"]["entry_orders_armed"], 0)
        self.assertEqual(result["diagnostics"]["first_touches_incomplete"], 1)

    def test_first_touch_while_busy_or_exiting_cannot_rearm_later(self):
        # Zone B is confirmed at index 7 while A is open; B's first touch at
        # index 8 coincides with A's target. Both busy and exit block arming.
        rows = BASE + [(104, 105, 103.5, 104.5),
                       (105, 106, 104, 104.5), (104.5, 109, 104.5, 108),
                       (108, 109, 107, 108.5), (107, 110, 105, 108),
                       (108, 109, 105, 108), (110, 111, 109.5, 110.5)]
        result = run(prepared(rows))
        self.assertEqual(len(result["trades"]), 1)
        self.assertEqual(result["trades"].exit_reason.iloc[0], "target")
        self.assertGreaterEqual(result["diagnostics"]["first_touches_busy_or_exit"], 1)
        self.assertEqual(result["diagnostics"]["entry_orders_armed"], 1)

    def test_order_expires_across_missing_next_bucket(self):
        data = prepared(BASE + [(104, 105, 103.5, 104.5)])
        source = data["source"].copy()
        stamps = source.index.to_list()
        stamps[-1] += pd.Timedelta(minutes=5)
        source.index = pd.DatetimeIndex(stamps)
        data = fresh.prepare_data(source, 1, 5)
        data["chart"]["bias"] = data["chart"]["hourly_bias"] = 1
        result = run(data)
        self.assertEqual(len(result["trades"]), 0)
        self.assertEqual(result["diagnostics"]["orders_expired"], 1)

    def test_hourly_cancellation_does_not_preserve_fresh_eligibility(self):
        data = prepared(BASE + [(104, 105, 103.5, 104.5),
                                (102, 103, 100, 102), (104, 105, 103.5, 104.5)])
        data["chart"].iloc[4, data["chart"].columns.get_loc("hourly_bias")] = -1
        result = run(data)
        self.assertEqual(len(result["trades"]), 0)
        self.assertEqual(result["diagnostics"]["orders_cancelled_bias"], 1)


class OpposingRoomTests(unittest.TestCase):
    def test_independent_context_can_reject_while_opposite_entry_bias_absent(self):
        data = context_fixture([(104, 105, 103.5, 104.5)], boundary=112)
        result = run(data)
        self.assertEqual(result["diagnostics"]["zones_created"], 1)
        self.assertEqual(result["diagnostics"]["context_zones_created"], 2)
        self.assertEqual(result["diagnostics"]["room_rejections_at_signal"], 1)
        self.assertEqual(len(result["trades"]), 0)

    def test_nearest_forward_boundary_and_entry_inside_zone(self):
        context = [dict(side=-1, bottom=111, top=114),
                   dict(side=-1, bottom=120, top=124),
                   dict(side=-1, bottom=90, top=95),
                   dict(side=1, bottom=98, top=100)]
        self.assertEqual(fresh._opposing_boundary(context, 1, 105), 111)
        self.assertEqual(fresh._opposing_boundary(context, 1, 112), 111)
        self.assertEqual(fresh._room_r(1, 112, 108, 111), 0)
        self.assertEqual(fresh._opposing_boundary(context, 1, 115), 120)
        self.assertIsNone(fresh._opposing_boundary(context, 1, 125))

    def test_room_rechecks_actual_gap_entry_on_both_sides(self):
        for mirror in (False, True):
            accepted = run(context_fixture([(103, 104, 102, 103.5)], mirror=mirror))
            rejected = run(context_fixture([(104, 105, 103.5, 104.5)], mirror=mirror))
            self.assertEqual(len(accepted["trades"]), 1)
            self.assertAlmostEqual(accepted["trades"].opposing_room_r.iloc[0], 10.75 / 4.5)
            self.assertEqual(rejected["diagnostics"]["room_rejections_at_fill"], 1)
            self.assertEqual(len(rejected["trades"]), 0)

    def test_gap_past_frozen_obstacle_is_rejected_without_lookahead(self):
        for mirror in (False, True):
            data = context_fixture([(117, 118, 116.5, 117.5)], mirror=mirror)
            result = run(data)
            self.assertEqual(len(result["trades"]), 0)
            self.assertEqual(result["diagnostics"]["room_rejections_at_fill"], 1)
            self.assertEqual(result["diagnostics"]["context_zone_invalidations"], 1)

    def test_newly_completed_opposing_context_blocks_same_close_signal(self):
        rows = BASE[:2] + [(103.5, 104, 102, 103),
                          (99.1, 99.25, 99, 99.2), (100, 101, 99.5, 100.5)]
        result = run(prepared(rows))
        self.assertEqual(result["diagnostics"]["context_zones_created"], 2)
        self.assertEqual(result["diagnostics"]["room_rejections_at_signal"], 1)
        self.assertEqual(len(result["trades"]), 0)

    def test_room_filter_disabled_preserves_gap_trade(self):
        data = context_fixture([(117, 118, 116.5, 117.5)])
        result = run(data, min_opposing_room_r=0)
        self.assertEqual(len(result["trades"]), 1)
        self.assertEqual(result["trades"].opposing_room_r.iloc[0], 0)


class CausalityAndAccountingTests(unittest.TestCase):
    def assert_reconciles(self, result):
        trades, equity = result["trades"], result["equity"]
        self.assertAlmostEqual(result["diagnostics"]["accounting_error"], 0)
        self.assertAlmostEqual(trades.net_pnl.sum(), equity.equity.iloc[-1] - 100000)
        self.assertAlmostEqual(equity.net_pnl.sum(), trades.net_pnl.sum())
        np.testing.assert_allclose(trades.gross_pnl - trades.cost, trades.net_pnl)
        np.testing.assert_allclose(trades.net_pnl / trades.initial_risk_cash, trades.net_r)
        self.assertEqual(equity.contracts.iloc[-1], 0)

    def test_costs_ambiguity_stops_targets_and_mirror_accounting(self):
        for rows in ([(104, 105, 103.5, 104.5)],
                     [(102, 110, 98, 104)],
                     [(102, 109, 101, 104)],
                     [(104, 105, 103.5, 104.5), (97, 98, 96, 97)],
                     [(104, 105, 103.5, 104.5), (110, 111, 98, 100)]):
            long = run(prepared(BASE + rows))
            short = run(prepared(BASE + rows, mirror=True))
            self.assertEqual(len(long["trades"]), 1)
            self.assertEqual(len(short["trades"]), 1)
            self.assert_reconciles(long)
            self.assert_reconciles(short)
            for key in ("risk", "gross_pnl", "cost", "net_pnl", "net_r"):
                self.assertAlmostEqual(long["trades"][key].iloc[0], short["trades"][key].iloc[0])

    def test_fractional_rr_targets_round_toward_entry_on_both_sides(self):
        for rr, target in ((.75, 107.75), (1.25, 110.5)):
            for mirror in (False, True):
                data = prepared(BASE + [(104, 105, 103.5, 104.5),
                                        (112, 113, 111, 112.5)], mirror=mirror)
                result = run(data, rr=rr)
                trade = result["trades"].iloc[0]
                expected = 250 - target if mirror else target
                self.assertAlmostEqual(trade.target, expected)
                self.assertAlmostEqual(trade.target / .25, round(trade.target / .25))
                self.assertEqual(trade.target_requested_rr, rr)
                self.assertAlmostEqual(trade.target_effective_rr, (target - 104) / 5.25)
                self.assertLessEqual(trade.target_effective_rr, rr)
                self.assertEqual(trade.exit_reason, "target")
                self.assertAlmostEqual(trade.net_r, trade.target_effective_rr - trade.cost / trade.risk_cash)
                self.assert_reconciles(result)

    def test_rounding_that_removes_positive_target_distance_rejects_entry(self):
        for mirror in (False, True):
            result = run(prepared(BASE + [(104, 105, 103.5, 104.5)], mirror=mirror), rr=.01)
            self.assertEqual(len(result["trades"]), 0)
            self.assertEqual(result["diagnostics"]["nonpositive_target_rejections"], 1)
            self.assertEqual(result["equity"].equity.iloc[-1], 100000)

    def test_exact_original_baseline_parity_when_new_rules_disabled(self):
        rng = np.random.default_rng(40817)
        opened = 100 + rng.normal(0, .7, 1500).cumsum()
        closed = opened + rng.normal(0, .5, 1500)
        rows = list(zip(opened, np.maximum(opened, closed) + rng.uniform(.1, 1, 1500),
                        np.minimum(opened, closed) - rng.uniform(.1, 1, 1500), closed))
        data = prepared(rows)
        for fvg in (True, False):
            for stop_model in ("zone", "candle"):
                for htf in (True, False):
                    options = dict(require_fvg=fvg, stop_model=stop_model, use_htf=htf,
                                   rr=1.0, first_touch_only=False, min_opposing_room_r=0)
                    baseline = run(data, model=original, **options)
                    candidate = run(data, **options)
                    self.assertGreater(len(baseline["trades"]), 0)
                    pd.testing.assert_frame_equal(candidate["trades"][original.TRADE_COLUMNS], baseline["trades"])
                    pd.testing.assert_frame_equal(candidate["equity"], baseline["equity"])

    def test_future_source_cannot_change_prefix_trades_or_equity(self):
        rows = BASE + [(104, 105, 103.5, 104.5), (110, 111, 109, 110)]
        rows += [(110, 112, 109, 111)] * 5 + BASE + [(104, 105, 103.5, 104.5)]
        full = prepared(rows, minute=True)
        for cutoff in (20, 25, 30, 36, 55, 66):
            source = full["source"].iloc[:cutoff]
            prefix = fresh.prepare_data(source, 1, 1)
            prefix["chart"]["bias"] = prefix["chart"]["hourly_bias"] = 1
            end = source.index[-1] + pd.Timedelta(minutes=1)
            result_full = run(full, end=end)
            result_prefix = run(prefix, end=end)
            pd.testing.assert_frame_equal(result_full["trades"], result_prefix["trades"])
            pd.testing.assert_frame_equal(result_full["equity"], result_prefix["equity"])

    def test_roll_clears_zones_and_keeps_idealized_liquidation_explicit(self):
        data = prepared(BASE + [(104, 105, 103.5, 104.5), (150, 160, 149, 155)])
        source = data["source"].copy()
        source["instrument_id"] = [10] * 5 + [20]
        data = fresh.prepare_data(source, 1, 5)
        data["chart"]["bias"] = data["chart"]["hourly_bias"] = 1
        result = run(data)
        self.assertEqual(result["trades"].exit_reason.iloc[0], "contract-roll")
        self.assertEqual(result["trades"].exit.iloc[0], 104.5)
        self.assertIn("idealized", result["diagnostics"]["roll_policy"])
        self.assert_reconciles(result)


if __name__ == "__main__":
    unittest.main()
