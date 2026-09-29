"""Independent behavioral fixtures for frozen-order lifetimes and price stress."""
import unittest

import numpy as np
import pandas as pd

from strategies import _snd_entry_research as research
from strategies import _snd_fresh_retest as frozen


BASE = [(100, 101, 99, 99.5), (99.5, 104, 99.5, 103),
        (103, 104, 102, 103.5), (102, 103, 100, 102)]
NO_TOUCH = (102, 103, 101.25, 102)
RETOUCH = (102, 102.5, 100, 102)
FILL = (104, 105, 103.5, 104.5)


def prepare(rows, mirror=False, minute=False):
    frame = pd.DataFrame(rows, columns=["open", "high", "low", "close"])
    if minute:
        frame = frame.loc[frame.index.repeat(5)].reset_index(drop=True)
    frame.index = pd.date_range("2026-01-05 12:00:00+00:00", periods=len(frame),
                                freq="1min" if minute else "5min")
    if mirror:
        old = frame.copy()
        frame["open"], frame["close"] = 250 - old.open, 250 - old.close
        frame["high"], frame["low"] = 250 - old.low, 250 - old.high
    return reprepare(frame, 1 if minute else 5, -1 if mirror else 1)


def reprepare(source, execution_minutes=5, bias=1):
    data = research.prepare_data(source, 1, execution_minutes)
    data["chart"]["bias"] = data["chart"]["hourly_bias"] = bias
    return data


def run(data, model=research, start=None, end=None, fee=1, slippage_ticks=1, **options):
    params = dict(pivot_len=1, execution_minutes=data["execution_minutes"], **options)
    return model.run_model(data, params, start or data["source"].index[0],
                           end or data["source"].index[-1] + pd.Timedelta(minutes=data["execution_minutes"]),
                           tick_size=.25, point_value=2, fee=fee, slippage_ticks=slippage_ticks)


class LifecycleTests(unittest.TestCase):
    def test_later_bucket_fill_separates_lifetime_from_touch_eligibility(self):
        data = prepare(BASE + [NO_TOUCH, FILL])
        for eligibility in ("first_touch", "any_touch"):
            one = run(data, entry_eligibility=eligibility, order_lifetime_bars=1)
            three = run(data, entry_eligibility=eligibility, order_lifetime_bars=3)
            self.assertEqual(len(one["trades"]), 0)
            self.assertEqual(len(three["trades"]), 1)
            trade = three["trades"].iloc[0]
            self.assertEqual(trade.signal_time, data["chart"].index[4])
            self.assertEqual(trade.order_expiry_time, data["chart"].index[4] + pd.Timedelta(minutes=15))
            self.assertEqual(trade.entry_time, data["chart"].index[5])
            self.assertEqual(trade.lifetime_bars, 3)
            self.assertEqual(trade.eligibility_policy, eligibility)

    def test_expiry_is_exclusive_after_exact_n_buckets(self):
        for lifetime in (1, 3, 6):
            accepted = prepare(BASE + [NO_TOUCH] * (lifetime - 1) + [FILL])
            expired = prepare(BASE + [NO_TOUCH] * lifetime + [FILL])
            self.assertEqual(len(run(accepted, order_lifetime_bars=lifetime)["trades"]), 1)
            result = run(expired, order_lifetime_bars=lifetime)
            self.assertEqual(len(result["trades"]), 0)
            self.assertEqual(result["diagnostics"]["orders_expired"], 1)

    def test_absent_buckets_consume_elapsed_lifetime(self):
        for minutes, expected in ((10, 1), (15, 0), (3 * 24 * 60, 0)):
            data = prepare(BASE + [FILL])
            source = data["source"].copy()
            stamps = source.index.to_list()
            stamps[-1] += pd.Timedelta(minutes=minutes)
            source.index = pd.DatetimeIndex(stamps)
            result = run(reprepare(source), order_lifetime_bars=3)
            self.assertEqual(len(result["trades"]), expected)

    def test_pending_trigger_and_expiry_are_not_refreshed_by_retouch(self):
        data = prepare(BASE + [RETOUCH, (102, 103, 100, 102), FILL])
        result = run(data, entry_eligibility="any_touch", order_lifetime_bars=3)
        self.assertEqual(len(result["trades"]), 1)
        self.assertEqual(result["diagnostics"]["entry_orders_armed"], 1)
        trade = result["trades"].iloc[0]
        self.assertEqual(trade.entry_time, data["chart"].index[6])
        self.assertEqual(trade.entry_reference, 103.25)
        self.assertEqual(trade.stop, 98.75)
        self.assertEqual(trade.signal_time, data["chart"].index[4])
        self.assertEqual(trade.order_expiry_time, data["chart"].index[4] + pd.Timedelta(minutes=15))

    def test_any_touch_can_arm_from_final_lifetime_bucket_after_expiry(self):
        data = prepare(BASE + [NO_TOUCH, NO_TOUCH, RETOUCH, (102.75, 103, 102, 102.75)])
        result = run(data, entry_eligibility="any_touch", order_lifetime_bars=3)
        self.assertEqual(len(result["trades"]), 1)
        self.assertEqual(result["diagnostics"]["entry_orders_armed"], 2)
        self.assertEqual(result["diagnostics"]["orders_expired"], 1)
        trade = result["trades"].iloc[0]
        self.assertEqual(trade.entry_reference, 102.75)
        self.assertEqual(trade.signal_time, data["chart"].index[7])
        self.assertEqual(trade.order_expiry_time, data["chart"].index[7] + pd.Timedelta(minutes=15))

    def test_another_zones_first_touch_at_expiry_close_can_arm(self):
        # A's unusually tall touch candle freezes a high trigger. B forms
        # below it while that order waits, then first touches in A's final
        # lifetime bucket. Expiry releases the order slot at this close.
        rows = BASE[:3] + [(110, 120, 100, 102),
                          (110, 111, 108, 109), (109, 115, 109, 114),
                          (114, 115, 112, 114), (112, 114, 110, 112),
                          (114.25, 115, 113, 114.5)]
        data = prepare(rows)
        for eligibility in ("first_touch", "any_touch"):
            result = run(data, entry_eligibility=eligibility, order_lifetime_bars=4)
            self.assertEqual(len(result["trades"]), 1)
            self.assertEqual(result["diagnostics"]["orders_expired"], 1)
            trade = result["trades"].iloc[0]
            self.assertEqual(trade.zone_time, data["chart"].index[7])
            self.assertEqual(trade.first_touch_time, data["chart"].index[7])
            self.assertEqual(trade.signal_time, data["chart"].index[8])
            self.assertEqual(trade.entry_reference, 114.25)

    def test_any_touch_rearms_after_missed_first_order_only_on_overlap(self):
        data = prepare(BASE + [RETOUCH, (102.75, 103, 102, 102.75)])
        first = run(data)
        later = run(data, entry_eligibility="any_touch")
        self.assertEqual(len(first["trades"]), 0)
        self.assertEqual(len(later["trades"]), 1)
        trade = later["trades"].iloc[0]
        self.assertEqual(trade.entry_reference, 102.75)
        self.assertEqual(trade.first_touch_time, data["chart"].index[3])
        self.assertEqual(trade.signal_time, data["chart"].index[5])

    def test_old_touched_flag_cannot_rearm_without_current_overlap(self):
        data = prepare(BASE + [NO_TOUCH, FILL])
        result = run(data, entry_eligibility="any_touch")
        self.assertEqual(len(result["trades"]), 0)
        self.assertEqual(result["diagnostics"]["entry_orders_armed"], 1)

    def test_later_touch_can_recover_misaligned_or_warmup_first_touch(self):
        for obstruction in ("bias", "hourly_bias", "warmup"):
            data = prepare(BASE + [RETOUCH, FILL])
            options = {}
            if obstruction == "warmup":
                options["start"] = data["chart"].index[4]
            else:
                data["chart"].iloc[3, data["chart"].columns.get_loc(obstruction)] = -1
            self.assertEqual(len(run(data, **options)["trades"]), 0)
            result = run(data, entry_eligibility="any_touch", **options)
            self.assertEqual(len(result["trades"]), 1)
            self.assertEqual(result["trades"].signal_time.iloc[0], data["chart"].index[5])

    def test_incomplete_touch_consumes_first_but_cannot_arm_any(self):
        data = prepare(BASE + [RETOUCH, FILL], minute=True)
        data = reprepare(data["source"].drop(data["source"].index[17]), 1)
        self.assertEqual(len(run(data)["trades"]), 0)
        later = run(data, entry_eligibility="any_touch")
        self.assertEqual(len(later["trades"]), 1)
        self.assertEqual(later["trades"].signal_time.iloc[0], data["chart"].index[5])
        self.assertEqual(later["diagnostics"]["first_touches_incomplete"], 1)

    def test_hourly_change_cancels_but_chart_change_does_not_cancel_pending(self):
        for column, trades in (("hourly_bias", 0), ("bias", 1)):
            data = prepare(BASE + [NO_TOUCH, FILL])
            data["chart"].iloc[5, data["chart"].columns.get_loc(column)] = -1
            result = run(data, order_lifetime_bars=3)
            self.assertEqual(len(result["trades"]), trades)
            self.assertEqual(result["diagnostics"]["orders_cancelled_bias"], 1 - trades)

    def test_zone_invalidation_age_expiry_and_roll_cancel_pending(self):
        invalid = prepare(BASE + [(100, 103, 98, 100), FILL])
        aged = prepare(BASE + [NO_TOUCH, FILL])
        rolled = prepare(BASE + [NO_TOUCH, FILL])
        source = rolled["source"].copy()
        source["instrument_id"] = [10] * 5 + [20]
        rolled = reprepare(source)
        for data, extra in ((invalid, {}), (aged, {"max_age": 2}), (rolled, {})):
            self.assertEqual(len(run(data, order_lifetime_bars=3, **extra)["trades"]), 0)

    def test_any_touch_cannot_rearm_on_same_bucket_as_exit(self):
        # B is touched in the same bucket in which A targets; later overlap
        # may rearm B, but no order can be armed at the exit bucket close.
        rows = BASE + [FILL, (105, 106, 104, 104.5), (104.5, 109, 104.5, 108),
                       (108, 109, 107, 108.5), (107, 110, 105, 108),
                       (111, 112, 110, 111)]
        result = run(prepare(rows), entry_eligibility="any_touch", order_lifetime_bars=3)
        self.assertEqual(len(result["trades"]), 1)
        self.assertEqual(result["diagnostics"]["entry_orders_armed"], 1)


class PriceSlippageTests(unittest.TestCase):
    def assert_accounting(self, result):
        trades, equity = result["trades"], result["equity"]
        self.assertAlmostEqual(result["diagnostics"]["accounting_error"], 0)
        self.assertAlmostEqual(equity.equity.iloc[-1] - 100000, trades.net_pnl.sum())
        self.assertAlmostEqual(equity.net_pnl.sum(), trades.net_pnl.sum())
        np.testing.assert_allclose(trades.gross_pnl - trades.cost, trades.net_pnl)
        np.testing.assert_allclose(trades.net_pnl / trades.risk_cash, trades.net_r)

    def test_shifted_entry_recomputes_risk_target_and_fee_only_cost(self):
        for mirror in (False, True):
            result = run(prepare(BASE + [FILL, (111, 112, 110, 111)], mirror=mirror),
                         slippage_model="price", slippage_ticks=2)
            trade = result["trades"].iloc[0]
            self.assertEqual(trade.entry_price_before_slippage, 146 if mirror else 104)
            self.assertEqual(trade.entry, 145.5 if mirror else 104.5)
            self.assertEqual(trade.risk, 5.75)
            self.assertEqual(trade.target, 139.75 if mirror else 110.25)
            self.assertEqual(trade.exit_reason, "target")
            self.assertEqual(trade.exit, trade.target)
            self.assertEqual(trade.exit_price_before_slippage, trade.target)
            self.assertEqual(trade.cost, 2)
            self.assertEqual(trade.net_pnl, 9.5)
            self.assert_accounting(result)

    def test_price_slippage_rechecks_room_after_actual_entry(self):
        b = 112.5
        context = [(b + .5, b + 2, b, b + 1),
                   (b + 1, b + 1.5, b - 4, b - 3), (b - 4, b - 3, b - 5, b - 4)]
        for mirror in (False, True):
            data = prepare(context + BASE + [(103, 104, 102, 103.5)], mirror=mirror)
            accepted = run(data)
            rejected = run(data, slippage_model="price")
            self.assertEqual(len(accepted["trades"]), 1)
            self.assertEqual(len(rejected["trades"]), 0)
            self.assertEqual(rejected["diagnostics"]["room_rejections_at_fill"], 1)

    def test_market_exits_shift_adversely_without_double_charging(self):
        for tail, reason, raw_exit in (([FILL], "end-of-test", 104.5),
                                      ([FILL, (97, 98, 96, 97)], "stop", 97),
                                      ([(102, 110, 98, 104)], "stop", 98.75)):
            results = []
            for mirror in (False, True):
                result = run(prepare(BASE + tail, mirror=mirror), slippage_model="price")
                trade = result["trades"].iloc[0]
                self.assertEqual(trade.exit_reason, reason)
                self.assertEqual(trade.exit_price_before_slippage, 250 - raw_exit if mirror else raw_exit)
                self.assertEqual(trade.exit, 250 - raw_exit + .25 if mirror else raw_exit - .25)
                self.assertEqual(trade.cost, 2)
                self.assert_accounting(result)
                results.append(trade)
            self.assertEqual(results[0].net_pnl, results[1].net_pnl)

    def test_intrabar_entry_remains_intrabar_after_shift(self):
        data = prepare(BASE + [(102, 111, 101, 106)])
        result = run(data, slippage_model="price")
        trade = result["trades"].iloc[0]
        self.assertEqual(trade.entry_price_before_slippage, 103.25)
        self.assertEqual(trade.entry, 103.5)
        self.assertTrue(trade.entry_bar_target_ignored)
        self.assertEqual(trade.exit_reason, "end-of-test")

    def test_source_open_entry_remains_open_entry_despite_shifted_fill(self):
        data = prepare(BASE + [(103.25, 109, 102, 106)])
        result = run(data, slippage_model="price")
        trade = result["trades"].iloc[0]
        self.assertEqual(trade.entry_price_before_slippage, 103.25)
        self.assertEqual(trade.entry, 103.5)
        self.assertFalse(trade.entry_bar_target_ignored)
        self.assertEqual(trade.exit_reason, "target")

    def test_price_fills_may_be_outside_ohlc_and_do_not_move_trigger(self):
        data = prepare(BASE + [(103.25, 103.25, 102, 103)])
        result = run(data, slippage_model="price", slippage_ticks=4)
        trade = result["trades"].iloc[0]
        self.assertEqual(trade.entry_reference, 103.25)
        self.assertEqual(trade.entry, 104.25)
        self.assertGreater(trade.entry, data["chart"].high.iloc[-1])
        self.assertIn("outside OHLC", result["diagnostics"]["slippage_policy"])

    def test_roll_liquidation_applies_market_exit_slippage(self):
        data = prepare(BASE + [FILL, (150, 160, 149, 155)])
        source = data["source"].copy()
        source["instrument_id"] = [10] * 5 + [20]
        result = run(reprepare(source), slippage_model="price")
        trade = result["trades"].iloc[0]
        self.assertEqual(trade.exit_reason, "contract-roll")
        self.assertEqual(trade.exit_price_before_slippage, 104.5)
        self.assertEqual(trade.exit, 104.25)
        self.assertEqual(trade.cost, 2)
        self.assert_accounting(result)


class ParityAndCausalityTests(unittest.TestCase):
    def test_cash_defaults_exactly_preserve_frozen_full_ledgers_and_equity(self):
        rng = np.random.default_rng(40817)
        opened = 100 + rng.normal(0, .7, 1500).cumsum()
        closed = opened + rng.normal(0, .5, 1500)
        data = prepare(list(zip(opened, np.maximum(opened, closed) + rng.uniform(.1, 1, 1500),
                                np.minimum(opened, closed) - rng.uniform(.1, 1, 1500), closed)))
        for fvg in (True, False):
            for room in (0, 2):
                for htf in (True, False):
                    options = dict(require_fvg=fvg, min_opposing_room_r=room, use_htf=htf)
                    baseline, candidate = run(data, model=frozen, **options), run(data, **options)
                    self.assertGreater(len(baseline["trades"]), 0)
                    pd.testing.assert_frame_equal(candidate["trades"][frozen.TRADE_COLUMNS], baseline["trades"], check_exact=True)
                    pd.testing.assert_frame_equal(candidate["equity"], baseline["equity"], check_exact=True)

    def test_new_modes_are_causal_under_prefix_extension(self):
        rows = BASE + [NO_TOUCH, FILL, (110, 111, 109, 110)]
        rows += [(110, 112, 109, 111)] * 5 + BASE + [FILL]
        full = prepare(rows, minute=True)
        for eligibility in ("first_touch", "any_touch"):
            for cutoff in (20, 25, 30, 36, 55, 66):
                source = full["source"].iloc[:cutoff]
                prefix = reprepare(source, 1)
                end = source.index[-1] + pd.Timedelta(minutes=1)
                options = dict(end=end, order_lifetime_bars=3, entry_eligibility=eligibility, slippage_model="price")
                result_full, result_prefix = run(full, **options), run(prefix, **options)
                pd.testing.assert_frame_equal(result_full["trades"], result_prefix["trades"], check_exact=True)
                pd.testing.assert_frame_equal(result_full["equity"], result_prefix["equity"], check_exact=True)

    def test_invalid_research_parameters_reject(self):
        data = prepare(BASE + [FILL])
        for options in (dict(first_touch_only=False), dict(entry_eligibility="rolling"),
                        dict(order_lifetime_bars=0), dict(order_lifetime_bars=-1),
                        dict(order_lifetime_bars=1.5), dict(order_lifetime_bars=True),
                        dict(order_lifetime_bars="3"), dict(slippage_model="both")):
            with self.assertRaises(ValueError):
                run(data, **options)


if __name__ == "__main__":
    unittest.main()
