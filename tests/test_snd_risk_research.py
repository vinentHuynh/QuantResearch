"""Risk sizing, frozen quantity, accounting and prospective snapshot fixtures."""
import unittest

import numpy as np
import pandas as pd

from strategies import _snd_entry_research as frozen
from strategies import _snd_risk_research as research


BASE = [(100, 101, 99, 99.5), (99.5, 104, 99.5, 103),
        (103, 104, 102, 103.5), (102, 103, 100, 102)]
FILL = (104, 105, 103.5, 104.5)
NO_TOUCH = (102, 103, 101.25, 102)


def prepare(rows, mirror=False, minute=False):
    source = pd.DataFrame(rows, columns=["open", "high", "low", "close"])
    if minute:
        source = source.loc[source.index.repeat(5)].reset_index(drop=True)
    source.index = pd.date_range("2026-01-05 12:00:00+00:00", periods=len(source), freq="1min" if minute else "5min")
    if mirror:
        prior = source.copy()
        source["open"], source["close"] = 250 - prior.open, 250 - prior.close
        source["high"], source["low"] = 250 - prior.low, 250 - prior.high
    return reprepare(source, 1 if minute else 5, -1 if mirror else 1)


def reprepare(source, execution_minutes=5, bias=1):
    data = research.prepare_data(source, 1, execution_minutes)
    data["chart"]["bias"] = data["chart"]["hourly_bias"] = bias
    return data


def run(data, model=research, end=None, fee=1, slippage_ticks=1, **options):
    return model.run_model(data, dict(pivot_len=1, execution_minutes=data["execution_minutes"], **options),
                          data["source"].index[0], end or data["source"].index[-1] + pd.Timedelta(minutes=data["execution_minutes"]),
                          tick_size=.25, point_value=2, fee=fee, slippage_ticks=slippage_ticks)


class RiskSizingTests(unittest.TestCase):
    def assert_accounting(self, result):
        trades, equity = result["trades"], result["equity"]
        self.assertAlmostEqual(result["diagnostics"]["accounting_error"], 0)
        np.testing.assert_allclose(trades.gross_pnl - trades.cost, trades.net_pnl)
        np.testing.assert_allclose(trades.net_pnl / trades.risk_cash, trades.net_r)
        self.assertAlmostEqual(equity.net_pnl.sum(), equity.equity.iloc[-1] - 100000)
        if result["parameters"]["finalize"]:
            self.assertAlmostEqual(trades.net_pnl.sum(), equity.equity.iloc[-1] - 100000)

    def test_whole_contract_floor_cap_and_cost_reserve_both_slippage_modes(self):
        # trigger 103.25, stop 98.75 => 9 cash distance + 1 slippage + 2 fees.
        for mode in ("cash", "price"):
            for budget, cap, expected, capped in ((35.99, 10, 2, False), (36, 10, 3, False), (100, 3, 3, True)):
                result = run(prepare(BASE + [FILL]), sizing_mode="fixed_risk", risk_budget=budget,
                             max_contracts=cap, slippage_model=mode)
                decision = result["sizing_decisions"].iloc[0]
                trade = result["trades"].iloc[0]
                self.assertEqual(decision.planned_stop_risk_per_contract, 12)
                self.assertEqual(decision.quantity_selected, expected)
                self.assertEqual(trade.contracts_abs, expected)
                self.assertEqual(trade.planned_stop_risk_cash, 12 * expected)
                self.assertEqual(trade.quantity_capped, capped)
                self.assert_accounting(result)

    def test_quantity_below_one_rejects_before_arming_and_consumes_first_touch(self):
        result = run(prepare(BASE + [(102, 102.5, 100, 102), FILL]),
                     sizing_mode="fixed_risk", risk_budget=11.99, record_events=True)
        self.assertTrue(result["trades"].empty)
        self.assertEqual(result["diagnostics"]["entry_orders_armed"], 0)
        self.assertEqual(result["diagnostics"]["sizing_rejections"], 1)
        self.assertEqual(len(result["sizing_decisions"]), 1)
        self.assertEqual(result["sizing_decisions"].quantity_selected.iloc[0], 0)
        self.assertIn("risk-budget-below-one-contract", result["events"].reason.to_list())

    def test_rejected_large_risk_trade_leaves_slot_for_later_small_zone(self):
        rows = BASE + [FILL, (103.5, 104, 102.75, 103), (103, 105.5, 103, 105),
                       (105, 105.5, 104.5, 105), (104.5, 104.75, 103.5, 104),
                       (105, 105.5, 104.75, 105.25)]
        data = prepare(rows)
        one = run(data)
        fixed_risk = run(data, sizing_mode="fixed_risk", risk_budget=10)
        self.assertEqual(len(one["trades"]), 1)
        self.assertEqual(len(fixed_risk["trades"]), 1)
        self.assertNotEqual(one["trades"].zone_time.iloc[0], fixed_risk["trades"].zone_time.iloc[0])
        self.assertEqual(fixed_risk["diagnostics"]["sizing_rejections"], 1)
        self.assertEqual(fixed_risk["trades"].contracts_abs.iloc[0], 1)

    def test_gap_does_not_resize_and_actual_risk_overshoot_is_reported(self):
        for mode in ("cash", "price"):
            for mirror in (False, True):
                result = run(prepare(BASE + [NO_TOUCH, (110, 111, 109, 110)], mirror=mirror),
                             sizing_mode="fixed_risk", risk_budget=36, order_lifetime_bars=3,
                             slippage_model=mode)
                trade = result["trades"].iloc[0]
                self.assertEqual(trade.contracts_abs, 3)
                self.assertEqual(abs(trade.quantity), 3)
                self.assertEqual(trade.planned_stop_risk_cash, 36)
                self.assertEqual(trade.actual_stop_risk_per_contract, 25.5)
                self.assertEqual(trade.actual_stop_risk_cash, 76.5)
                self.assertEqual(trade.risk_budget_overshoot_cash, 40.5)
                self.assertEqual(result["diagnostics"]["risk_budget_overshoot_entries"], 1)
                self.assert_accounting(result)

    def test_multi_contract_targets_and_stops_scale_without_changing_net_r(self):
        for mode in ("cash", "price"):
            for mirror in (False, True):
                for tail in ([FILL, (111, 112, 110, 111)], [FILL, (97, 98, 96, 97)]):
                    data = prepare(BASE + tail, mirror=mirror)
                    single, multi = run(data, slippage_model=mode), run(data, slippage_model=mode, contracts=4)
                    a, b = single["trades"].iloc[0], multi["trades"].iloc[0]
                    for column in ("risk_cash", "initial_risk_cash", "gross_pnl", "cost", "net_pnl"):
                        self.assertEqual(b[column], a[column] * 4)
                    self.assertEqual(b.net_r, a.net_r)
                    self.assertEqual(b.quantity, -4 if mirror else 4)
                    self.assert_accounting(multi)

    def test_fixed_contract_defaults_match_full_frozen_ledgers_exactly(self):
        rng = np.random.default_rng(53946)
        opened = 100 + rng.normal(0, .7, 1200).cumsum()
        closed = opened + rng.normal(0, .5, 1200)
        data = prepare(list(zip(opened, np.maximum(opened, closed) + rng.uniform(.1, 1, 1200),
                                np.minimum(opened, closed) - rng.uniform(.1, 1, 1200), closed)))
        for mode in ("cash", "price"):
            for fvg in (False, True):
                for eligibility in ("first_touch", "any_touch"):
                    options = dict(slippage_model=mode, require_fvg=fvg, entry_eligibility=eligibility,
                                   order_lifetime_bars=3, min_opposing_room_r=0)
                    old, new = run(data, model=frozen, **options), run(data, **options)
                    self.assertGreater(len(old["trades"]), 0)
                    pd.testing.assert_frame_equal(old["trades"], new["trades"][frozen.TRADE_COLUMNS], check_exact=True)
                    pd.testing.assert_frame_equal(old["equity"], new["equity"], check_exact=True)

    def test_invalid_sizing_parameters_reject(self):
        for options in (dict(sizing_mode="fractional"), dict(contracts=0), dict(contracts=1.1),
                        dict(contracts=True), dict(max_contracts=0), dict(risk_budget=0),
                        dict(risk_budget=np.inf), dict(record_events=1), dict(finalize="false")):
            with self.assertRaises(ValueError):
                run(prepare(BASE + [FILL]), **options)


class ProspectiveSnapshotTests(unittest.TestCase):
    def test_as_of_open_position_is_marked_without_end_liquidation(self):
        result = run(prepare(BASE + [FILL]), contracts=3, finalize=False, record_events=True)
        self.assertTrue(result["trades"].empty)
        state = result["open_state"]
        self.assertIsNotNone(state["active"])
        self.assertEqual(state["active"]["quantity"], 3)
        self.assertEqual(state["balance"], 100000 - 1.5 * 3)
        self.assertEqual(state["unrealized_pnl"], .5 * 2 * 3)
        self.assertEqual(state["equity"], 99998.5)
        self.assertEqual(result["equity"].contracts.iloc[-1], 3)
        self.assertAlmostEqual(result["diagnostics"]["accounting_error"], 0)
        self.assertNotIn("exit", result["events"].event_type.to_list())

    def test_as_of_pending_quantity_trigger_and_expiry_are_retained(self):
        result = run(prepare(BASE + [NO_TOUCH]), sizing_mode="fixed_risk", risk_budget=36,
                     order_lifetime_bars=3, finalize=False, record_events=True)
        pending = result["open_state"]["pending"]
        self.assertEqual(pending["contracts_abs"], 3)
        self.assertEqual(pending["trigger"], 103.25)
        self.assertEqual(pd.Timestamp(pending["expiry_time"], tz="UTC"), pd.Timestamp("2026-01-05T12:35Z"))
        self.assertEqual(result["events"].event_type.to_list(), ["zone_created", "signal", "order_armed"])

    def test_journal_uses_known_close_times_and_unique_stable_ids(self):
        data = prepare(BASE + [FILL, (111, 112, 110, 111)], minute=True)
        first = run(data, record_events=True, finalize=False)
        second = run(data, record_events=True, finalize=False)
        pd.testing.assert_frame_equal(first["events"], second["events"], check_exact=True)
        events = first["events"]
        self.assertTrue(events.event_id.is_unique)
        self.assertTrue((events.observed_time >= events.event_time).all())
        entry = events.loc[events.event_type.eq("entry")].iloc[0]
        self.assertEqual(entry.observed_time - entry.event_time, pd.Timedelta(minutes=1))
        created = events.loc[events.event_type.eq("zone_created")].iloc[0]
        self.assertEqual(created.observed_time, pd.Timestamp("2026-01-05T12:15Z"))

    def test_nonfinal_events_equity_and_closed_trades_match_under_prefix_extension(self):
        rows = BASE + [NO_TOUCH, FILL, (111, 112, 110, 111)] + [(110, 112, 109, 111)] * 5 + BASE + [FILL]
        full = prepare(rows, minute=True)
        options = dict(record_events=True, finalize=False, order_lifetime_bars=3,
                       sizing_mode="fixed_risk", risk_budget=36, slippage_model="price")
        extended = run(full, **options)
        for cutoff in (18, 20, 23, 25, 29, 36, 55, 66):
            source = full["source"].iloc[:cutoff]
            end = source.index[-1] + pd.Timedelta(minutes=1)
            prefix = run(reprepare(source, 1), end=end, **options)
            bounded = run(full, end=end, **options)
            pd.testing.assert_frame_equal(prefix["events"], bounded["events"], check_exact=True)
            pd.testing.assert_frame_equal(prefix["trades"], bounded["trades"], check_exact=True)
            pd.testing.assert_frame_equal(prefix["equity"], bounded["equity"], check_exact=True)
            expected = extended["events"].loc[extended["events"].observed_time.le(end)].reset_index(drop=True)
            pd.testing.assert_frame_equal(prefix["events"], expected, check_exact=True)

    def test_roll_exit_is_observed_when_new_contract_bar_arrives(self):
        data = prepare(BASE + [FILL, (150, 160, 149, 155)])
        source = data["source"].copy()
        source["instrument_id"] = [10] * 5 + [20]
        result = run(reprepare(source), record_events=True, finalize=False)
        event = result["events"].loc[result["events"].event_type.eq("exit")].iloc[0]
        self.assertEqual(event.reason, "contract-roll")
        self.assertEqual(event.event_time, pd.Timestamp("2026-01-05T12:25Z"))
        self.assertEqual(event.observed_time, pd.Timestamp("2026-01-05T12:30Z"))


if __name__ == "__main__":
    unittest.main()
