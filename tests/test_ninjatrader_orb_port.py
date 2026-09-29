"""Compile/execute the actual MNQ ORB C# core; no NT process or account is used."""
from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import unittest

import pandas as pd

from strategies._pine_models import IntradayORB

ROOT = Path(__file__).resolve().parents[1]
CSC = Path("C:/Windows/Microsoft.NET/Framework64/v4.0.30319/csc.exe")


def row(start, high=401., low=399., close=400., position=0, end_hour=17, end_minute=0, allow=True):
    start = pd.Timestamp(start)
    end = start + pd.Timedelta(minutes=5)
    session_date = start.normalize() + pd.Timedelta(days=int(start.hour >= 18))
    session_end = session_date + pd.Timedelta(hours=end_hour, minutes=end_minute)
    return ";".join(["bar", start.strftime("%Y-%m-%dT%H:%M:%S"), end.strftime("%Y-%m-%dT%H:%M:%S"),
                     session_end.strftime("%Y-%m-%dT%H:%M:%S"), str(high), str(low), str(close),
                     str(position), str(int(allow))])


def short_warmup(declining=False):
    prices = [100, 101, 102] if not declining else [102, 101, 100]
    rows = ["config;250;1;2;2;2;2"]
    for day, price in zip(pd.bdate_range("2024-01-02", periods=3), prices):
        rows.append(row(day + pd.Timedelta(hours=16, minutes=55), price + 1, price - 1, price))
    return rows


@unittest.skipUnless(CSC.exists(), "Windows .NET Framework C# compiler required")
class NinjaTraderOrbPort(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="mnq-orb-check-")
        cls.exe = Path(cls.temp.name) / "orb-check.exe"
        subprocess.run([str(CSC), "/nologo", "/target:exe", "/langversion:5", f"/out:{cls.exe}",
                        str(ROOT / "ninjatrader/WorkbenchMnqTsmomOrbCore.cs"),
                        str(ROOT / "ninjatrader/tests/TsmomOrbHarness.cs")], check=True, capture_output=True, text=True)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def evaluate(self, rows):
        result = subprocess.run([str(self.exe)], input="\n".join(rows) + "\n", check=True,
                                capture_output=True, text=True)
        return [line.split(";") for line in result.stdout.splitlines()]

    def test_default_daily_score_and_regular_decisions_match_python(self):
        records = []
        #253 completed ETH sessions are needed for close minus close[252].
        for i, day in enumerate(pd.bdate_range("2023-01-03", periods=253)):
            records.append((day + pd.Timedelta(hours=16, minutes=55), 101. + i, 99. + i, 100. + i))
        for minute, high, low, close in [(570, 401, 399, 400), (575, 402, 399, 401),
                                          (580, 403, 400, 402), (585, 405, 402, 404),
                                          (590, 406, 403, 405), (940, 406, 403, 405),
                                          (945, 406, 403, 405)]:
            records.append((pd.Timestamp("2024-01-03") + pd.Timedelta(minutes=minute), high, low, close))
        index = pd.DatetimeIndex([r[0] for r in records]).tz_localize("America/New_York")
        bars = pd.DataFrame({"open": [r[3] for r in records], "high": [r[1] for r in records],
                             "low": [r[2] for r in records], "close": [r[3] for r in records],
                             "availability_time": index + pd.Timedelta(minutes=5),
                             "session_date": index.strftime("%Y-%m-%d")}, index=index)
        p = dict(fast_length=20, medium_length=60, slow_length=120, annual_length=252, minimum_score=.5,
                 timezone="America/New_York", opening_start=570, opening_end=585, entry_start=585,
                 entry_end=900, flatten_start=945, flatten_end=960, risk_budget=250,
                 maximum_contracts=1, reward_risk=2., require_close_break=True)
        model = IntradayORB(bars, p, {"dataset": {"point_value": 2.}})
        position = 0
        inputs, expected = [], []
        for i, (stamp, bar) in enumerate(bars.iterrows()):
            inputs.append(row(stamp.tz_localize(None), bar.high, bar.low, bar.close, position))
            decision = model.on_close(i, bar, {"tradable": True, "position": position})
            if decision is None:
                expected.append(("None", 0, 0., 0.))
            elif decision["target"] == 0:
                expected.append(("Flatten", 0, 0., 0.))
                position = 0
            else:
                position = decision["target"]
                expected.append(("Long" if position > 0 else "Short", abs(position), *decision["bracket"]))
        actual = self.evaluate(inputs)
        self.assertEqual([(r[0], int(r[1]), float(r[2]), float(r[3])) for r in actual], expected)
        self.assertEqual(actual[-7][4], "1")
        self.assertEqual(actual[-7][6], "253")
        self.assertEqual([r[0] for r in actual[-4:]], ["Long", "None", "None", "Flatten"])

    def test_strict_close_break_and_signal_close_bracket(self):
        actual = self.evaluate(short_warmup() + [
            row("2024-01-05 09:30", 401, 399, 400),
            row("2024-01-05 09:45", 402, 400, 401),  # touch/equality does not qualify
            row("2024-01-05 09:50", 403, 401, 402),
        ])
        self.assertEqual(actual[-2][0], "None")
        self.assertEqual(actual[-1][:4], ["Long", "1", "399", "408"])

    def test_short_direction_and_bracket(self):
        actual = self.evaluate(short_warmup(True) + [
            row("2024-01-05 09:30", 401, 399, 400),
            row("2024-01-05 09:45", 399, 397, 398),
        ])
        self.assertEqual(actual[-1][:5], ["Short", "1", "401", "392", "-1"])

    def test_budget_preserves_125_point_cutoff_and_rejected_attempt_consumes_day(self):
        base = short_warmup() + [row("2024-01-05 09:30", 401, 300, 400)]
        accepted = self.evaluate(base + [row("2024-01-05 09:45", 426, 400, 425)])
        self.assertEqual(accepted[-1][:4], ["Long", "1", "300", "675"])
        rejected = self.evaluate(base + [row("2024-01-05 09:45", 427, 400, 426),
                                        row("2024-01-05 09:50", 420, 400, 410)])
        self.assertEqual([r[0] for r in rejected[-2:]], ["RiskSkipped", "None"])

    def test_early_close_deadline_exits_before_close_and_blocks_new_entry(self):
        base = short_warmup() + [row("2024-01-05 09:30", end_hour=13),
                                row("2024-01-05 09:45", 403, 400, 402, end_hour=13)]
        actual = self.evaluate(base + [row("2024-01-05 12:45", position=1, end_hour=13),
                                      row("2024-01-05 12:50", position=1, end_hour=13)])
        self.assertEqual([r[0] for r in actual[-2:]], ["None", "Flatten"])
        self.assertEqual(actual[-1][5], "2024-01-05T12:55:00")
        blocked = self.evaluate(short_warmup() + [row("2024-01-05 09:30", end_hour=13),
                                                row("2024-01-05 12:50", 403, 400, 402, end_hour=13)])
        self.assertEqual(blocked[-1][0], "None")

    def test_missing_flat_window_catches_up_and_unexpected_carry_is_explicit(self):
        base = short_warmup() + [row("2024-01-05 09:30"), row("2024-01-05 09:45", 403, 400, 402)]
        actual = self.evaluate(base + [row("2024-01-05 16:10", position=1),
                                      row("2024-01-07 18:00", position=1)])
        self.assertEqual([r[0] for r in actual[-2:]], ["Flatten", "EmergencyFlatten"])

    def test_missing_next_days_or_does_not_reuse_old_range(self):
        actual = self.evaluate(short_warmup() + [row("2024-01-05 09:30"),
                                                row("2024-01-08 09:45", 410, 400, 405)])
        self.assertEqual(actual[-1][0], "None")
        self.assertEqual(actual[-1][7:9], ["NaN", "NaN"])

    def test_partial_opening_range_remains_observed_source_rule(self):
        actual = self.evaluate(short_warmup() + [row("2024-01-05 09:40"),
                                                row("2024-01-05 09:45", 403, 400, 402)])
        self.assertEqual(actual[-1][0], "Long")

    def test_daily_signal_does_not_use_current_intraday_close_or_publish_holiday_early(self):
        actual = self.evaluate(short_warmup() + [
            row("2024-01-05 09:30", 102, 98, 100, end_hour=13),
            row("2024-01-05 12:50", 102, 90, 91, end_hour=13),
            row("2024-01-07 18:00", 95, 90, 94),
        ])
        self.assertEqual([r[4] for r in actual[-3:]], ["1", "1", "-1"])
        self.assertEqual([r[6] for r in actual[-3:]], ["3", "3", "4"])

    def test_platform_clock_dst_conversion_and_ambiguous_time(self):
        actual = self.evaluate([
            "zone;2024-03-08T14:50:00;UTC", "zone;2024-03-11T13:50:00;UTC",
            "zone;2024-11-01T13:50:00;UTC", "zone;2024-11-04T14:50:00;UTC",
            "zone;2024-07-01T08:50:00;Central Standard Time",
            "zone;2024-11-03T01:30:00;Eastern Standard Time",
        ])
        for output, day in zip(actual[:5], ["2024-03-08", "2024-03-11", "2024-11-01", "2024-11-04", "2024-07-01"]):
            self.assertEqual(output, [day + "T09:50:00", day + "T09:45:00"])
        self.assertEqual(actual[5], ["INVALID_TIME"])


if __name__ == "__main__":
    unittest.main()
