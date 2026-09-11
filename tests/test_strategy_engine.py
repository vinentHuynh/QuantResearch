from __future__ import annotations

import unittest

import pandas as pd

from strategy_engine.data import session_bars
from strategy_engine.sessions import SESSIONS
from strategy_engine.strategies.opening_range_breakout import OpeningRangeBreakoutConfig, run
from strategy_engine.strategies.prior_range_fill import PriorRangeFillConfig, run as run_prior_range
from strategy_engine.strategies.relative_value import LegEconomics, RelativeValueConfig, run as run_relative_value
from strategy_engine.strategies.session_drift import SessionDriftConfig, run as run_session_drift
from strategy_engine.strategies.trend import TrendConfig, run as run_trend


def synthetic_session(session_id: str) -> pd.DataFrame:
    session = SESSIONS[session_id]
    start = pd.Timestamp("2026-06-15", tz=session.timezone) + pd.Timedelta(
        hours=session.opens_at.hour,
        minutes=session.opens_at.minute,
    )
    index = pd.date_range(start, periods=45, freq="1min").tz_convert("UTC")
    closes = [100.0] * 15 + [101.0] * 30
    return pd.DataFrame(
        {
            "open": closes,
            "high": [value + 0.25 for value in closes],
            "low": [value - 0.25 for value in closes],
            "close": closes,
            "volume": 1,
        },
        index=index,
    )


class StrategyEngineTests(unittest.TestCase):
    def test_orb_runs_same_strategy_across_named_sessions(self) -> None:
        for session_id in ("new-york-rth", "london", "asia"):
            with self.subTest(session=session_id):
                session = SESSIONS[session_id]
                bars = session_bars(synthetic_session(session_id), session, "5m")
                trades, signals = run(
                    bars,
                    opening_bars=session_bars(synthetic_session(session_id), session, "1m"),
                    symbol="TEST",
                    tick_size=0.25,
                    point_value=2.0,
                    config=OpeningRangeBreakoutConfig(opening_range_minutes=15),
                )
                self.assertEqual(len(trades), 1)
                self.assertEqual(len(signals), 1)
                self.assertEqual(trades.iloc[0].session_id, session_id)
                self.assertEqual(trades.iloc[0].side, "long")

    def test_resampling_is_anchored_to_each_local_session_open(self) -> None:
        for session_id in ("new-york-rth", "london", "asia"):
            with self.subTest(session=session_id):
                session = SESSIONS[session_id]
                bars = session_bars(synthetic_session(session_id), session, "15m")
                first = bars.index[0]
                self.assertEqual(first.hour, session.opens_at.hour)
                self.assertEqual(first.minute, session.opens_at.minute)
                self.assertEqual(bars.iloc[0].session_date, "2026-06-15")

    def test_opening_range_uses_one_minute_bars_on_a_wider_execution_timeframe(self) -> None:
        session = SESSIONS["new-york-rth"]
        source = synthetic_session("new-york-rth")
        execution = session_bars(source, session, "30m")
        opening = session_bars(source, session, "1m")
        trades, _ = run(
            execution,
            opening_bars=opening,
            symbol="TEST",
            tick_size=0.25,
            point_value=2.0,
            config=OpeningRangeBreakoutConfig(opening_range_minutes=15),
        )
        self.assertEqual(len(trades), 1)

    def test_prior_range_fill_fades_a_gap_from_the_prior_boundary(self) -> None:
        session = SESSIONS["new-york-rth"]
        first_start = pd.Timestamp("2026-06-15 09:30", tz=session.timezone)
        second_start = pd.Timestamp("2026-06-16 09:30", tz=session.timezone)
        first_index = pd.date_range(first_start, periods=30, freq="1min").tz_convert("UTC")
        second_index = pd.date_range(second_start, periods=30, freq="1min").tz_convert("UTC")
        first = pd.DataFrame({"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0}, index=first_index)
        second_close = [102.0] * 10 + [100.5] * 20
        second = pd.DataFrame({
            "open": second_close,
            "high": [value + 0.25 for value in second_close],
            "low": [value - 0.25 for value in second_close],
            "close": second_close,
        }, index=second_index)
        bars = session_bars(pd.concat([first, second]), session, "5m")
        trades, signals = run_prior_range(
            bars,
            symbol="TEST",
            tick_size=0.25,
            point_value=2.0,
            config=PriorRangeFillConfig(),
        )
        self.assertEqual(len(trades), 1)
        self.assertEqual(len(signals), 1)
        self.assertEqual(trades.iloc[0].side, "short")
        self.assertEqual(trades.iloc[0].entry, 101.0)

    def test_globex_session_labels_sunday_evening_as_monday(self) -> None:
        session = SESSIONS["globex-overnight"]
        index = pd.date_range("2026-06-14 18:00", periods=144, freq="5min", tz=session.timezone).tz_convert("UTC")
        close = pd.Series(range(len(index)), index=index, dtype=float) + 100.0
        source = pd.DataFrame({
            "open": close,
            "high": close + 0.25,
            "low": close - 0.25,
            "close": close,
        }, index=index)
        bars = session_bars(source, session, "5m")
        trades, signals = run_session_drift(
            bars,
            symbol="TEST",
            tick_size=0.25,
            point_value=2.0,
            config=SessionDriftConfig(),
        )
        self.assertEqual(bars.iloc[0].session_date, "2026-06-15")
        self.assertEqual(len(trades), 1)
        self.assertEqual(len(signals), 1)
        self.assertEqual(trades.iloc[0].side, "long")

    def test_pairs_and_cross_sectional_strategies_use_explicit_legs(self) -> None:
        session = SESSIONS["new-york-rth"]
        index = pd.date_range("2026-06-15 09:30", periods=12, freq="5min", tz=session.timezone)

        def bars(values: list[float]) -> pd.DataFrame:
            return pd.DataFrame({
                "open": values,
                "high": [value + 0.25 for value in values],
                "low": [value - 0.25 for value in values],
                "close": values,
                "session_id": session.id,
                "session_date": "2026-06-15",
            }, index=index)

        universe = {
            "UP": bars([100 + step * 2 for step in range(12)]),
            "MID": bars([100 + step for step in range(12)]),
            "DOWN": bars([100 - step for step in range(12)]),
        }
        economics = {symbol: LegEconomics(0.25, 2.0) for symbol in universe}
        cross_trades, _, cross_positions = run_relative_value(
            universe,
            economics,
            RelativeValueConfig("cross-sectional-momentum", lookback=3),
        )
        self.assertGreater(len(cross_trades), 0)
        self.assertEqual(set(cross_positions.symbol), set(universe))
        cross_targets = cross_positions.pivot(index="event_time", columns="symbol", values="quantity")
        expected_cross_cost = float(cross_targets.diff().abs().iloc[1:].sum().sum() * 0.25 * 2.0 / 2.0)
        self.assertAlmostEqual(float(cross_trades.cost.sum()), expected_cross_cost)
        _, _, whole_cross_positions = run_relative_value(
            universe,
            economics,
            RelativeValueConfig("cross-sectional-momentum", lookback=3, quantity_mode="whole_contracts"),
        )
        whole_cross_targets = whole_cross_positions.pivot(index="event_time", columns="symbol", values="quantity")
        self.assertTrue(bool((whole_cross_targets == whole_cross_targets.apply(lambda column: column.map(int))).all().all()))
        self.assertTrue(bool((whole_cross_targets.abs() <= cross_targets.abs()).all().all()))

        pair_universe = {
            "UP": bars([100, 100, 100, 105, 100, 112, 101, 120, 103, 125, 104, 130]),
            "DOWN": bars([100] * 12),
        }
        pair_economics = {key: economics[key] for key in pair_universe}
        pair_trades, _, pair_positions = run_relative_value(
            pair_universe,
            pair_economics,
            RelativeValueConfig("pairs-mean-reversion", lookback=3),
        )
        self.assertGreater(len(pair_trades), 0)
        position_panel = pair_positions.pivot(index="event_time", columns="symbol", values="quantity")
        self.assertTrue(bool((position_panel["UP"] * position_panel["DOWN"] < 0).any()))

    def test_trend_strategies_lag_signals_and_emit_chart_positions(self) -> None:
        session = SESSIONS["new-york-rth"]
        index = pd.date_range("2026-06-15 09:30", periods=30, freq="5min", tz=session.timezone)
        values = [100.0 + step for step in range(len(index))]
        bars = pd.DataFrame({
            "open": values,
            "high": [value + 0.25 for value in values],
            "low": [value - 0.25 for value in values],
            "close": values,
            "session_id": session.id,
            "session_date": "2026-06-15",
        }, index=index)
        economics = LegEconomics(0.25, 2.0)
        for strategy_id in ("multi-speed-momentum", "moving-average-trend"):
            with self.subTest(strategy=strategy_id):
                pnl, signals, positions = run_trend(
                    bars,
                    symbol="TEST",
                    economics=economics,
                    config=TrendConfig(strategy_id, lookback=5),
                )
                self.assertGreater(len(pnl), 0)
                self.assertEqual(set(positions.symbol), {"TEST"})
                self.assertEqual(float(positions.iloc[:4].quantity.abs().sum()), 0.0)
                self.assertGreater(float(positions.iloc[4:].quantity.max()), 0.0)
                first_target = pd.to_datetime(positions.loc[positions.quantity.ne(0), "event_time"].iloc[0])
                first_held = pd.to_datetime(pnl.loc[pnl.quantity.ne(0), "period_end"].iloc[0])
                self.assertGreater(first_held, first_target)
                self.assertTrue(signals.reason.str.endswith("at_close").all())
                target_turnover = positions.quantity.diff().abs().iloc[1:].sum()
                expected_cost = float(target_turnover * economics.tick_size * economics.point_value / 2.0)
                self.assertAlmostEqual(float(pnl.cost.sum()), expected_cost)

    def test_whole_contract_trend_sizing_is_integer_and_conservative(self) -> None:
        session = SESSIONS["new-york-rth"]
        index = pd.date_range("2026-06-15 09:30", periods=30, freq="5min", tz=session.timezone)
        values = [100.0 + step for step in range(len(index))]
        bars = pd.DataFrame({
            "open": values, "high": values, "low": values, "close": values,
            "session_id": session.id, "session_date": "2026-06-15",
        }, index=index)
        economics = LegEconomics(0.25, 2.0)
        _, _, fractional = run_trend(
            bars, symbol="TEST", economics=economics,
            config=TrendConfig("moving-average-trend", lookback=5, quantity_mode="fractional"),
        )
        _, _, whole = run_trend(
            bars, symbol="TEST", economics=economics,
            config=TrendConfig("moving-average-trend", lookback=5, quantity_mode="whole_contracts"),
        )
        self.assertTrue(bool(whole.quantity.map(float.is_integer).all()))
        self.assertTrue(bool((whole.quantity.abs() <= fractional.quantity.abs()).all()))

    def test_intraday_trend_flattens_before_excluded_session_gap(self) -> None:
        session = SESSIONS["new-york-rth"]
        first = pd.date_range("2026-06-15 09:30", periods=3, freq="1h", tz=session.timezone)
        second = pd.date_range("2026-06-16 09:30", periods=3, freq="1h", tz=session.timezone)
        index = first.append(second)
        values = [100.0, 101.0, 102.0, 150.0, 151.0, 152.0]
        bars = pd.DataFrame({
            "open": values, "high": values, "low": values, "close": values,
            "session_id": session.id,
            "session_date": ["2026-06-15"] * 3 + ["2026-06-16"] * 3,
        }, index=index)
        pnl, _, positions = run_trend(
            bars, symbol="TEST", economics=LegEconomics(0.25, 2.0),
            config=TrendConfig("moving-average-trend", lookback=2, cost_ticks=0.0),
        )
        self.assertEqual(float(positions.loc[positions.session_date.eq("2026-06-15")].iloc[-1].quantity), 0.0)
        next_open_mark = pnl.loc[pd.to_datetime(pnl.period_end).eq(second[0].tz_convert("UTC"))].iloc[0]
        self.assertEqual(float(next_open_mark.quantity), 0.0)
        self.assertEqual(float(next_open_mark.gross_pnl), 0.0)


if __name__ == "__main__":
    unittest.main()
