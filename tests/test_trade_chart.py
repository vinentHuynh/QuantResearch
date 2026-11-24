import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from workbench.contract import checksum
from workbench.trade_chart import attach_fills, chart_day


class TradeChartTest(unittest.TestCase):
    def setUp(self):
        self.trade = {"entry": "2026-01-05T23:55:00Z", "exit": "2026-01-06T00:05:00Z", "pnl": 12.5}
        self.row = {"entry_time": self.trade["entry"], "exit_time": self.trade["exit"], "net_pnl": 12.5,
                    "entry": 100.25, "exit": 99.5, "quantity": -1, "order_id": "A"}

    def test_overnight_fill_preserves_short_side_and_actual_bracket_changes(self):
        ledger = pd.DataFrame([{**self.row, "original_stop": 102, "original_target": 97}])
        signals = pd.DataFrame([
            dict(event="bracket_updated", event_time="2026-01-06T00:01:00Z", order_id="A", new_stop=100, new_target=97),
            dict(event="bracket_updated", event_time="2026-01-06T00:03:00Z", order_id="B", new_stop=50, new_target=10),
        ])
        attach_fills([self.trade], ledger, signals)
        self.assertEqual((self.trade["side"], self.trade["entryPrice"], self.trade["exitPrice"]), ("short", 100.25, 99.5))
        self.assertEqual((self.trade["stop"], self.trade["target"]), (102, 97))
        self.assertEqual([v["stop"] for v in self.trade["changes"]], [100])

    def test_unrecorded_brackets_and_ambiguous_fills_stay_unavailable(self):
        ledger = pd.DataFrame([self.row])
        attach_fills([self.trade], ledger)
        self.assertNotIn("stop", self.trade)
        self.assertNotIn("target", self.trade)
        for candidates in [pd.concat([ledger, ledger]), ledger.assign(net_pnl=50)]:
            trade = {k: self.trade[k] for k in ("entry", "exit", "pnl")}
            attach_fills([trade], candidates)
            self.assertNotIn("entryPrice", trade)

    def test_imported_direction_and_price_columns(self):
        ledger = pd.DataFrame([{
            "entry_time": self.trade["entry"], "exit_time": self.trade["exit"],
            "pnl": 12.5, "direction": "short", "quantity": 2,
            "entry_price": 100.25, "exit_price": 99.5, "stop_price": 101.5, "target_price": 98,
        }])
        attach_fills([self.trade], ledger)
        self.assertEqual(self.trade["side"], "short")
        self.assertEqual(self.trade["quantity"], 2)
        self.assertEqual((self.trade["entryPrice"], self.trade["exitPrice"]), (100.25, 99.5))
        self.assertEqual((self.trade["stop"], self.trade["target"]), (101.5, 98))

    def test_day_reads_only_utc_candles_from_the_recorded_dataset(self):
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            dates = pd.date_range("2026-01-05T23:59Z", periods=3, freq="min", name="ts_event")
            path = home / "prices.parquet"
            pd.DataFrame({"open": 100., "high": 102., "low": 99., "close": 101.}, index=dates).to_parquet(path)
            dataset = {"id": "prices", "schema_version": 2, "path": path.name, "checksum": checksum(path)}
            span = {"start": "2026-01-05", "end": "2026-01-06"}
            request = {"day": span["end"], "item": {"source": "Workbench", "coverage": [span]},
                       "runs": [{"id": "sample", "dataset": dataset}], "datasets": [dataset], "trades": []}
            result = chart_day(request, home)
            self.assertEqual([c["time"] for c in result["candles"]], [int(t.timestamp() * 1000) for t in dates[1:]])
            self.assertFalse(result["reference"])
            self.assertEqual(result["notes"], [])
            path.write_bytes(b"changed dataset")
            changed = chart_day(request, home)
            self.assertEqual(changed["candles"], [])
            self.assertTrue(changed["notes"])
