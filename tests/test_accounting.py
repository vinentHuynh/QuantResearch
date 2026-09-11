from __future__ import annotations

import unittest

import pandas as pd

from strategy_engine.accounting import (
    PNL_COLUMNS,
    POSITION_COLUMNS,
    closed_trade_ledgers,
    performance_metrics,
    position_ledgers,
    session_equity,
)
from strategy_engine.strategies.opening_range_breakout import TRADE_COLUMNS


class AccountingTests(unittest.TestCase):
    def test_equity_and_sharpe_include_sessions_without_trades(self) -> None:
        index = pd.date_range("2026-01-05", periods=3, freq="B", tz="UTC")
        bars = pd.DataFrame({
            "close": [100.0, 101.0, 102.0],
            "session_date": [timestamp.date().isoformat() for timestamp in index],
        }, index=index)
        pnl = pd.DataFrame([{
            "period_start": index[0].isoformat(), "period_end": index[1].isoformat(),
            "availability_time": index[1].isoformat(), "session_id": "test",
            "session_date": index[1].date().isoformat(), "symbol": "TEST", "quantity": 1.0,
            "gross_pnl": 10.0, "cost": 0.0, "net_pnl": 10.0,
        }], columns=PNL_COLUMNS)
        trades = pd.DataFrame([{
            "entry_time": index[0].isoformat(), "exit_time": index[1].isoformat(),
            "session_id": "test", "session_date": index[1].date().isoformat(), "symbol": "TEST",
            "side": "long", "entry": 100.0, "exit": 110.0, "quantity": 1.0,
            "gross_pnl": 10.0, "cost": 0.0, "net_pnl": 10.0, "reason": "test",
        }], columns=TRADE_COLUMNS)
        orders, _, positions = closed_trade_ledgers(trades)
        equity = session_equity(bars, pnl, 100.0)
        metrics = performance_metrics(
            equity=equity, trades=trades, pnl=pnl, positions=positions,
            orders=orders, capital=100.0,
        )
        self.assertEqual(equity.net_pnl.tolist(), [0.0, 10.0, 0.0])
        self.assertEqual(metrics["sessions"], 3)
        self.assertEqual(metrics["active_sessions"], 1)
        self.assertEqual(metrics["trades"], 1)
        self.assertEqual(metrics["orders"], 2)
        self.assertAlmostEqual(float(metrics["sharpe"]), 9.16515138991168)

    def test_position_marks_become_closed_exposure_episodes(self) -> None:
        index = pd.date_range("2026-01-05", periods=4, freq="D", tz="UTC")
        positions = pd.DataFrame([
            {"event_time": timestamp.isoformat(), "session_id": "test", "session_date": timestamp.date().isoformat(),
             "symbol": "TEST", "quantity": quantity, "price": price}
            for timestamp, quantity, price in zip(index, [0.0, 1.0, 1.0, 0.0], [100.0, 101.0, 106.0, 108.0])
        ], columns=POSITION_COLUMNS)
        pnl = pd.DataFrame([
            {"period_start": index[i - 1].isoformat(), "period_end": index[i].isoformat(),
             "availability_time": index[i].isoformat(), "session_id": "test", "session_date": index[i].date().isoformat(),
             "symbol": "TEST", "quantity": [0.0, 1.0, 1.0][i - 1], "gross_pnl": [0.0, 5.0, 2.0][i - 1],
             "cost": [1.0, 0.0, 1.0][i - 1], "net_pnl": [-1.0, 5.0, 1.0][i - 1]}
            for i in range(1, 4)
        ], columns=PNL_COLUMNS)
        trades, orders, fills = position_ledgers(positions, pnl)
        self.assertEqual(len(trades), 1)
        self.assertEqual(len(orders), 2)
        self.assertEqual(len(fills), 2)
        self.assertEqual(float(trades.iloc[0].gross_pnl), 7.0)
        self.assertEqual(float(trades.iloc[0].cost), 2.0)
        self.assertEqual(float(trades.iloc[0].net_pnl), 5.0)


if __name__ == "__main__":
    unittest.main()
