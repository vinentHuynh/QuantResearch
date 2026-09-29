"""Independent causal and execution fixtures for the transcript research model."""
import unittest

import numpy as np
import pandas as pd

from strategies._transcript_supply_demand import _structure, prepare_data, run_model


def candles(rows, frequency="5min", start="2026-01-05 12:00:00+00:00"):
    result = pd.DataFrame(rows, columns=["open", "high", "low", "close"])
    result.index = pd.date_range(start, periods=len(result), freq=frequency)
    result["volume"] = 1.0
    return result


def execution_fixture(last_rows, mirror=False):
    # Bearish base -> bullish displacement -> FVG; later contact arms the
    # previous candle's high + one tick. Fix structure to isolate execution.
    rows = [(100, 101, 99, 99.5), (99.5, 104, 99.5, 103),
            (103, 104, 102, 103.5), (102, 103, 100, 102)] + last_rows
    frame = candles(rows)
    if mirror:
        original = frame.copy()
        frame["open"] = 200 - original.open
        frame["high"] = 200 - original.low
        frame["low"] = 200 - original.high
        frame["close"] = 200 - original.close
    prepared = prepare_data(frame, pivot_len=1, execution_minutes=5)
    prepared["chart"]["bias"] = -1 if mirror else 1
    prepared["chart"]["hourly_bias"] = -1 if mirror else 1
    return prepared


def execute(prepared, start=None, end=None, **extra):
    source = prepared["source"]
    parameters = dict(pivot_len=1, execution_minutes=5, use_htf=True,
                      stop_model="zone", rr=1.0)
    parameters.update(extra)
    return run_model(prepared, parameters,
                     start or source.index[0],
                     end or source.index[-1] + pd.Timedelta(minutes=5),
                     tick_size=.25, point_value=2, fee=1, slippage_ticks=1)


class StructureCausalityTests(unittest.TestCase):
    def test_pivot_needs_right_bar_and_close_break(self):
        frame = candles([(9, 10, 8, 9), (10, 12, 9, 10),
                         (10, 11, 8, 10), (11, 13, 10, 11.5),
                         (12, 14, 11, 12.5)])
        frame["segment"] = 0
        # At index 2, the pivot at index 1 is finally known. A wick at
        # index 3 does not count; index 4 closes through its price.
        self.assertEqual(_structure(frame, 1).tolist(), [0, 0, 0, 0, 1])

    def test_structure_prefix_and_contract_reset(self):
        rng = np.random.default_rng(1701)
        close = 100 + rng.normal(size=200).cumsum()
        frame = pd.DataFrame(dict(high=close + rng.uniform(.2, 1, 200),
                                  low=close - rng.uniform(.2, 1, 200),
                                  close=close, segment=0))
        frame.loc[130:, "segment"] = 1
        full = _structure(frame, 2)
        for size in (5, 17, 69, 130, 131, 149, 199):
            np.testing.assert_array_equal(_structure(frame.iloc[:size], 2), full[:size])
        self.assertEqual(full[130], 0)

    def test_completed_hour_available_only_from_next_hour_open(self):
        hour_rows = [(9, 10, 8, 9), (10, 12, 9, 10),
                     (10, 11, 8, 10), (12, 14, 11, 13),
                     (13, 15, 12, 14)]
        # Repeating each valid OHLC tuple 60 times yields deliberately simple
        # hourly extrema; source timestamps still progress one minute at a time.
        frame = candles([row for row in hour_rows for _ in range(60)], "1min")
        prepared = prepare_data(frame, 1, 1)
        self.assertEqual(prepared["hourly"].bias.iloc[3], 1)
        chart = prepared["chart"]
        self.assertTrue((chart.loc[:"2026-01-05 15:55", "hourly_bias"] == 0).all())
        self.assertEqual(chart.loc["2026-01-05 16:00", "hourly_bias"], 1)
        for size in (181, 239, 240, 241, 275):
            prefix = prepare_data(frame.iloc[:size], 1, 1)
            complete = prefix["chart"].loc[prefix["chart"].complete]
            pd.testing.assert_series_equal(complete.bias, chart.loc[complete.index, "bias"])
            pd.testing.assert_series_equal(complete.hourly_bias, chart.loc[complete.index, "hourly_bias"])

    def test_missing_minute_cannot_create_complete_chart_bar(self):
        frame = candles([(100, 101, 99, 100)] * 10, "1min")
        frame = frame.drop(frame.index[3])
        prepared = prepare_data(frame, 1, 1)
        self.assertEqual(prepared["chart"].complete.tolist(), [False, True])
        self.assertEqual(prepared["diagnostics"]["incomplete_5m_buckets"], 1)

    def test_bad_source_is_rejected_without_silent_deduplication(self):
        frame = candles([(100, 101, 99, 100)] * 3)
        with self.assertRaisesRegex(ValueError, "sorted, unique"):
            prepare_data(pd.concat([frame, frame.iloc[-1:]]), 1, 5)
        frame.iloc[0, frame.columns.get_loc("high")] = 98
        with self.assertRaisesRegex(ValueError, "invalid OHLC"):
            prepare_data(frame, 1, 5)


class ExecutionAndAccountingTests(unittest.TestCase):
    def assert_reconciles(self, result):
        trades, equity = result["trades"], result["equity"]
        self.assertAlmostEqual(result["diagnostics"]["accounting_error"], 0)
        self.assertAlmostEqual(trades.net_pnl.sum(), equity.equity.iloc[-1] - 100000)
        self.assertAlmostEqual(equity.net_pnl.sum(), trades.net_pnl.sum())
        np.testing.assert_allclose(trades.gross_pnl - trades.cost, trades.net_pnl)
        np.testing.assert_allclose(trades.net_pnl / trades.risk_cash, trades.net_r)
        self.assertEqual(equity.contracts.iloc[-1], 0)

    def test_gap_entry_reanchors_actual_risk_and_final_liquidation(self):
        prepared = execution_fixture([(104, 105, 103.5, 104.5)])
        result = execute(prepared)
        self.assertEqual(len(result["trades"]), 1)
        trade = result["trades"].iloc[0]
        self.assertEqual(trade.entry, 104)
        self.assertEqual(trade.stop, 98.75)
        self.assertEqual(trade.risk, 5.25)
        self.assertEqual(trade.risk_cash, 10.5)
        self.assertEqual(trade.target, 109.25)
        self.assertEqual(trade.exit_reason, "end-of-test")
        self.assertEqual(trade.cost, 3)
        self.assert_reconciles(result)

    def test_intrabar_entry_ignores_unordered_favorable_extreme(self):
        result = execute(execution_fixture([(102, 109, 101, 104)]))
        trade = result["trades"].iloc[0]
        self.assertEqual(trade.entry, 103.25)
        self.assertEqual(trade.target, 107.75)
        self.assertTrue(trade.entry_bar_target_ignored)
        self.assertEqual(trade.exit_reason, "end-of-test")
        self.assert_reconciles(result)

    def test_ambiguous_entry_and_exit_use_stop_first(self):
        result = execute(execution_fixture([(102, 110, 98, 104)]))
        trade = result["trades"].iloc[0]
        self.assertEqual(trade.exit_reason, "stop")
        self.assertEqual(trade.exit, 98.75)
        self.assertTrue(trade.ambiguous_entry)
        self.assertTrue(trade.ambiguous_exit)
        self.assertEqual(result["diagnostics"]["ambiguous_entry_count"], 1)
        self.assert_reconciles(result)

    def test_established_stop_gap_uses_open(self):
        result = execute(execution_fixture([(104, 105, 103.5, 104.5),
                                            (97, 98, 96, 97)]))
        trade = result["trades"].iloc[0]
        self.assertEqual(trade.exit_reason, "stop")
        self.assertEqual(trade.exit, 97)
        self.assert_reconciles(result)

    def test_decimal_tick_boundary_survives_binary_rounding(self):
        # 103.2 + .1 is 103.30000000000001 in binary floating arithmetic.
        prepared = execution_fixture([(103, 103.3, 102, 103.2)])
        prepared["source"].iloc[3, prepared["source"].columns.get_loc("high")] = 103.2
        prepared["chart"].iloc[3, prepared["chart"].columns.get_loc("high")] = 103.2
        result = run_model(prepared, dict(pivot_len=1, execution_minutes=5),
                           prepared["source"].index[0],
                           prepared["source"].index[-1] + pd.Timedelta(minutes=5),
                           tick_size=.1, point_value=10, fee=1, slippage_ticks=1)
        self.assertEqual(len(result["trades"]), 1)
        self.assertAlmostEqual(result["trades"].entry.iloc[0], 103.3)
        self.assert_reconciles(result)

    def test_target_at_known_open_precedes_later_stop(self):
        result = execute(execution_fixture([(104, 105, 103.5, 104.5),
                                            (110, 111, 98, 100)]))
        trade = result["trades"].iloc[0]
        self.assertEqual(trade.exit_reason, "target")
        self.assertEqual(trade.exit, 109.25)
        self.assertFalse(trade.ambiguous_exit)
        self.assertEqual(trade.cost, 2.5)
        self.assert_reconciles(result)

    def test_long_short_mirror_symmetry(self):
        rows = [(104, 105, 103.5, 104.5), (106, 110, 105, 109)]
        long = execute(execution_fixture(rows))["trades"].iloc[0]
        short = execute(execution_fixture(rows, mirror=True))["trades"].iloc[0]
        self.assertEqual(long.side, -short.side)
        for column in ("risk", "risk_cash", "gross_pnl", "cost", "net_pnl", "net_r"):
            self.assertAlmostEqual(long[column], short[column])

    def test_start_is_flat_and_end_is_exclusive(self):
        prepared = execution_fixture([(104, 105, 103.5, 104.5),
                                      (106, 107, 105.5, 106),
                                      (110, 111, 109, 110)])
        start = prepared["source"].index[5]
        end = prepared["source"].index[6]
        result = execute(prepared, start=start, end=end)
        trades = result["trades"]
        self.assertTrue((trades.entry_time >= start).all())
        self.assertTrue((trades.entry_time < end).all())
        self.assertTrue((trades.exit_time <= end).all())
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades.entry.iloc[0], 106)
        self.assertEqual(trades.exit_reason.iloc[0], "end-of-test")
        self.assert_reconciles(result)

    def test_contract_roll_liquidates_and_clears_preexisting_zones(self):
        prepared = execution_fixture([(104, 105, 103.5, 104.5),
                                      (150, 160, 149, 155),
                                      (151, 161, 148, 154)])
        source = prepared["source"].drop(columns="segment")
        source["instrument_id"] = [10] * 5 + [20] * 2
        prepared = prepare_data(source, 1, 5)
        prepared["chart"]["bias"] = 1
        prepared["chart"]["hourly_bias"] = 1
        result = execute(prepared)
        self.assertEqual(len(result["trades"]), 1)
        self.assertEqual(result["trades"].exit_reason.iloc[0], "contract-roll")
        self.assertEqual(result["trades"].exit.iloc[0], 104.5)
        self.assertEqual(result["diagnostics"]["roll_liquidations"], 1)
        self.assert_reconciles(result)


if __name__ == "__main__":
    unittest.main()
