"""Synthetic session, roll, and provenance checks for HTF wick inputs."""

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "prepare-htf-wick-inputs.py"
SPEC = importlib.util.spec_from_file_location("prepare_htf_wick_inputs", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class PrepareHtfWickInputsTests(unittest.TestCase):
    def test_last_four_hour_bucket_covers_three_session_hours(self):
        index = pd.date_range(
            "2024-03-10T22:00:00Z", "2024-03-11T21:00:00Z",
            freq="min", inclusive="left", name="ts_event",
        )
        frame = pd.DataFrame({
            "open": 100, "high": 101, "low": 99, "close": 100,
            "volume": 1, "instrument_id": 12,
        }, index=index)
        result = MODULE.aggregate(frame, "4h", "ES")
        self.assertEqual(result.minute_count.tolist(), [240, 240, 240, 240, 240, 180])
        self.assertEqual(result.index[-1], pd.Timestamp("2024-03-11T18:00:00Z"))
        self.assertFalse(result.is_roll_bar.any())

    def test_full_day_dst_roll_and_maintenance_gap(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            dataset = root / "dataset"
            dataset.mkdir()
            source = dataset / "bars.parquet"
            index = pd.DatetimeIndex([
                "2024-03-07T23:00:00Z",  # Thursday 18:00 EST, Friday session
                "2024-03-08T03:59:00Z",  # Thursday 22:59 EST
                "2024-03-10T22:00:00Z",  # Sunday 18:00 EDT
                "2024-03-10T22:01:00Z",  # same hour, new contract
                "2024-03-11T20:59:00Z",  # Monday 16:59 EDT, last 4h bucket
                "2024-03-11T21:00:00Z",  # maintenance break, excluded
                "2024-03-11T22:00:00Z",  # next trading session
            ], name="ts_event")
            bars = pd.DataFrame({
                "open": [100, 101, 103, 102, 105, 999, 106],
                "high": [102, 103, 104, 105, 106, 1000, 107],
                "low": [99, 100, 101, 100, 104, 998, 105],
                "close": [101, 102, 102, 104, 105, 999, 106],
                "volume": [2, 3, 4, 5, 6, 99, 7],
                "instrument_id": [1, 1, 1, 2, 2, 2, 2],
            }, index=index)
            bars.to_parquet(source)
            (dataset / "dataset.json").write_text(json.dumps({
                "id": "synthetic-es-v1", "symbol": "ES", "timeframe": "1m",
                "checksum": MODULE.sha256(source), "rows": len(bars),
            }), encoding="utf-8")

            output = root / "output"
            manifest = MODULE.build(source, "ES", output, ["1h", "4h", "1d"])
            self.assertEqual(manifest["source"]["sha256"], MODULE.sha256(source))
            one_hour = pd.read_parquet(output / "candles_1h.parquet")
            four_hour = pd.read_parquet(output / "candles_4h.parquet")
            daily = pd.read_parquet(output / "candles_1d.parquet")
            self.assertEqual(one_hour.index.tz.zone, "UTC")
            self.assertEqual(list(daily.columns[:10]), [
                "open", "high", "low", "close", "volume", "minute_count",
                "instrument_id", "contract_count", "is_roll_bar", "symbol",
            ])
            self.assertIn(pd.Timestamp("2024-03-07T23:00:00Z"), daily.index)
            self.assertIn(pd.Timestamp("2024-03-10T22:00:00Z"), daily.index)
            sunday = daily.loc[pd.Timestamp("2024-03-10T22:00:00Z")]
            self.assertEqual(int(sunday.volume), 15)  # no maintenance-break 99
            self.assertEqual(int(sunday.minute_count), 3)
            self.assertEqual(int(sunday.contract_count), 2)
            self.assertTrue(sunday.is_roll_bar)
            self.assertEqual(sunday.session_date, "2024-03-11")
            self.assertFalse(sunday.is_source_edge_session)
            early_four = four_hour.loc[pd.Timestamp("2024-03-10T22:00:00Z")]
            self.assertEqual(int(early_four.minute_count), 2)
            self.assertTrue(early_four.is_roll_bar)
            self.assertIn(pd.Timestamp("2024-03-11T18:00:00Z"), four_hour.index)
            self.assertEqual(int(four_hour.loc[pd.Timestamp("2024-03-11T18:00:00Z")].minute_count), 1)
            self.assertEqual(int(one_hour.loc[pd.Timestamp("2024-03-10T22:00:00Z")].contract_count), 2)
            self.assertTrue((daily.high < 900).all())
            self.assertEqual(manifest["timeframes"]["1d"]["roll_bars"], 1)
            self.assertEqual(manifest["timeframes"]["1d"]["rows"], 3)
            with self.assertRaises(FileExistsError):
                MODULE.build(source, "ES", output, ["1d"])


if __name__ == "__main__":
    unittest.main()
