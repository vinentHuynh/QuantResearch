"""Execute the actual C# clock core against Python source decisions and edge cases."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest

import pandas as pd

from strategies._pine_models import OvernightBlock
from strategy_engine.strategies.session_drift import SessionDriftConfig, run


ROOT = Path(__file__).resolve().parents[1]
CSC = Path("C:/Windows/Microsoft.NET/Framework64/v4.0.30319/csc.exe")


@unittest.skipUnless(CSC.exists(), "Windows .NET Framework C# compiler required")
class NinjaTraderOvernightPorts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="mnq-overnight-check-")
        cls.exe = Path(cls.temp.name) / "overnight-check.exe"
        subprocess.run([str(CSC), "/nologo", "/target:exe", "/langversion:5", f"/out:{cls.exe}",
                        str(ROOT / "ninjatrader/WorkbenchMnqOvernightRules.cs"),
                        str(ROOT / "ninjatrader/tests/OvernightRulesHarness.cs")], check=True, capture_output=True, text=True)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def evaluate(self, rows):
        result = subprocess.run([str(self.exe)], input="\n".join(rows) + "\n", check=True,
                                capture_output=True, text=True)
        return result.stdout.splitlines()

    def test_block_matches_python_regular_boundaries_and_weekend(self):
        idx = pd.date_range("2024-03-07 16:30", "2024-03-11 06:00", freq="15min", tz="America/New_York")
        local = idx.tz_localize(None)
        minute = local.hour * 60 + local.minute
        session_day = local.normalize() + pd.to_timedelta((minute >= 18 * 60).astype(int), unit="D")
        idx = idx[((minute < 17 * 60) | (minute >= 18 * 60)) & (session_day.weekday < 5)]
        bars = pd.DataFrame({"open": 100., "high": 101., "low": 99., "close": 100.,
                             "availability_time": idx + pd.Timedelta(minutes=15)}, index=idx)
        parameters = dict(entry_hour=17, entry_minute=0, exit_hour=6, exit_minute=0,
                          contracts=1, timezone="America/New_York")
        model = OvernightBlock(bars, parameters, {})
        position = 0
        expected, rows = [], []
        for i, (_, bar) in enumerate(bars.iterrows()):
            rows.append(f"block;{bar.availability_time.strftime('%Y-%m-%d %H:%M:%S')};{position}")
            decision = model.on_close(i, bar, {"tradable": True, "position": position})
            target = decision["target"] if decision else position
            expected.append(str(1 if target > position else -1 if target < position else 0))
            position = target
        self.assertEqual(self.evaluate(rows), expected)
        self.assertGreater(expected.count("1"), 1)

    def test_block_preserves_observed_transitions_without_invented_filters(self):
        self.assertEqual(self.evaluate([
            "block;2024-01-07 18:15:00;0", "block;2024-01-08 05:45:00;0",
            "block;2024-01-08 16:30:00;0", "block;2024-01-08 17:00:00;0",
            "block;2024-01-09 16:45:00;0", "block;2024-01-09 17:00:00;0",
            "block;2024-01-09 17:00:00;0", "block;2024-01-10 06:00:00;1",
        ]), ["1", "0", "0", "1", "0", "1", "0", "-1"])

    def test_session_matches_frozen_conservative_entry_schedule(self):
        source = ROOT / "research/campaigns/expanded-search-2026-09-16/expanded.py"
        spec = importlib.util.spec_from_file_location("mnq_frozen_expanded", source)
        expanded = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(expanded)
        idx = pd.date_range("2024-01-07 18:00", "2024-01-08 05:59", freq="1min", tz="America/New_York")
        bars = pd.DataFrame({"open": 100., "high": 101., "low": 99., "close": 100., "volume": 1,
                             "availability_time": idx + pd.Timedelta(minutes=1),
                             "session_date": "2024-01-08", "session_id": "globex-overnight"}, index=idx)
        native, _ = run(bars, symbol="NQ", tick_size=.25, point_value=20,
                        config=SessionDriftConfig(cost_ticks=2.5))
        conservative = expanded.conservative({
            "strategy": "overnight-session", "symbol": "NQ",
            "tick_size": .25, "point_value": 20,
        }, bars, native)
        entry = pd.Timestamp(conservative.iloc[0].entry_time).tz_convert("America/New_York")
        exit_time = pd.Timestamp(conservative.iloc[0].exit_time).tz_convert("America/New_York")
        rows = [f"session;{close.strftime('%Y-%m-%d %H:%M:%S')};{int(close > entry)}"
                for close in bars.availability_time]
        actions = self.evaluate(rows)
        self.assertEqual([bars.availability_time.iloc[i] for i, a in enumerate(actions) if a == "1"], [entry])
        self.assertEqual([bars.availability_time.iloc[i] for i, a in enumerate(actions) if a == "-1"], [exit_time])

    def test_session_does_not_chase_or_repeat_entry(self):
        self.assertEqual(self.evaluate([
            "session;2024-01-07 18:02:00;0", "session;2024-01-08 18:01:00;0",
            "session;2024-01-08 18:01:00;0", "session;2024-01-09 05:59:00;1",
            "session;2024-01-09 06:00:00;1", "session;2024-01-12 18:01:00;0",
            "session;2024-01-13 18:01:00;0",
        ]), ["0", "1", "0", "0", "-1", "0", "0"])

    def test_session_missing_exit_bar_flattens_first_observed_later_bar(self):
        self.assertEqual(self.evaluate([
            "session;2024-01-07 18:01:00;0", "session;2024-01-08 18:01:00;1",
        ]), ["1", "-1"])

    def test_eastern_conversion_uses_dst_and_platform_timezone(self):
        self.assertEqual(self.evaluate([
            "zone;2024-03-08 23:01:00;UTC", "zone;2024-03-10 22:01:00;UTC",
            "zone;2024-11-01 22:01:00;UTC", "zone;2024-11-03 23:01:00;UTC",
            "zone;2024-07-01 17:01:00;Central Standard Time",
        ]), ["2024-03-08 18:01:00", "2024-03-10 18:01:00", "2024-11-01 18:01:00",
             "2024-11-03 18:01:00", "2024-07-01 18:01:00"])


if __name__ == "__main__":
    unittest.main()
