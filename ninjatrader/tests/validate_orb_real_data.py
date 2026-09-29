"""Trace Python's real MNQ event replay and compare the actual compiled C# core.

Bounded regression: Jan-Jun2026 plus600 calendar days of warmup. Uses every
available source bar in that interval, first auditing it against the frozen NT
ETH calendar. No filtering of calendar mismatches or failed decisions is allowed.
This verifies decision parity, not NinjaTrader order fills or profitability.
Run from the repository: .venv/Scripts/python.exe ninjatrader/tests/validate_orb_real_data.py
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from strategies._cme_index_calendar import session_close_et, TEMPLATE_VERSION
from strategies._pine_models import IntradayORB
from strategies.pine_tsmom_orb import STRATEGY
from strategy_engine.data import session_bars
from strategy_engine.sessions import get_session
from workbench.contract import resolve_parameters
from workbench.events import simulate_events

REPORT = ROOT / "reports/tsmom-orb-fix-2026-09-29/orb-core-realdata.json"
CORE = ROOT / "ninjatrader/WorkbenchMnqTsmomOrbCore.cs"
HARNESS = ROOT / "ninjatrader/tests/TsmomOrbHarness.cs"
CSC = Path("C:/Windows/Microsoft.NET/Framework64/v4.0.30319/csc.exe")
SOURCES = [CORE, HARNESS, Path(__file__), ROOT / "strategies/_pine_models.py", ROOT / "strategies/pine_tsmom_orb.py",
           ROOT / "strategies/_cme_index_calendar.py", ROOT / "workbench/events.py"]


def digests():
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in SOURCES}


def et_stamp(value):
    return pd.Timestamp(value).tz_convert("America/New_York").strftime("%Y-%m-%dT%H:%M:%S")


def save(report):
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, allow_nan=False), flush=True)


class TracedModel:
    def __init__(self, original, ends, inputs, expected):
        self.original = original
        self.ends = ends
        self.inputs = inputs
        self.expected = expected
        self.rows = 0
        self.actions = Counter()
        self.held_rows = 0

    def on_close(self, i, bar, state):
        attempted = self.original.attempted
        decision = self.original.on_close(i, bar, state)
        action, quantity, stop, target = "None", 0, 0.0, 0.0
        if decision is not None:
            target_position = decision["target"]
            if target_position == 0:
                action = "Flatten"
            else:
                action = "Long" if target_position > 0 else "Short"
                quantity = abs(target_position)
                stop, target = decision["bracket"]
        elif not attempted and self.original.attempted and state["tradable"]:
            action = "RiskSkipped"
        score = self.original.known.score.iloc[i]
        end = self.ends[str(bar.session_date)]
        self.inputs.write(";".join(["bar", et_stamp(bar.name), et_stamp(bar.availability_time), et_stamp(end),
                                    repr(float(bar.high)), repr(float(bar.low)), repr(float(bar.close)),
                                    str(state["position"]), str(int(state["tradable"]))]) + "\n")
        self.expected.write(";".join([str(i), et_stamp(bar.name), action, str(quantity), repr(float(stop)),
                                      repr(float(target)), repr(float(score))]) + "\n")
        self.rows += 1
        self.actions[action] += 1
        self.held_rows += int(state["position"] != 0)
        if self.rows % 50000 == 0:
            print(f"Traced {self.rows:,} original Python event decisions", flush=True)
        return decision


def equal_number(left, right):
    a, b = float(left), float(right)
    return (math.isnan(a) and math.isnan(b)) or math.isclose(a, b, rel_tol=0.0, abs_tol=1e-9)


def main():
    before = digests()
    history = []
    if REPORT.exists():
        previous_report = json.loads(REPORT.read_text(encoding="utf-8"))
        history = previous_report.get("validation_history", [])
        if previous_report.get("result") == "FAIL" and previous_report.get("mismatch_counts") == {"stop": 50, "target": 50}:
            history.append(dict(checked_at=previous_report["checked_at"], result="TEST_COMPARATOR_CORRECTED",
                                original_mismatch_counts=previous_report["mismatch_counts"],
                                explanation="The original comparator compared nonexistent Python brackets (zero placeholders) with C# diagnostic candidates on50 zero-quantity RiskSkipped results. All actions/quantities/scores matched. Brackets are now compared only for submitted entries; strategy/core unchanged."))
    dataset = next((ROOT / "data/workbench/datasets").glob("*mnq-cache-v1/bars.parquet"))
    parameters = resolve_parameters(STRATEGY, dict(risk_budget=250, maximum_contracts=1, execution_timing="close"))
    request = dict(start="2026-01-01", end="2026-06-30", warmup_days=600, capital=100000.,
                   fee=1.25, slippage=1, dataset=dict(point_value=2., tick_size=.25))
    start = pd.Timestamp(request["start"], tz="UTC") - pd.Timedelta(days=request["warmup_days"])
    end = pd.Timestamp(request["end"], tz="UTC") + pd.Timedelta(days=1)
    frame = pd.read_parquet(dataset, filters=[("ts_event", ">=", start), ("ts_event", "<", end)],
                            columns=["open", "high", "low", "close", "volume"])
    bars = session_bars(frame, get_session("full-trading-day"), "5m")
    ends = {str(day): session_close_et(day) for day in bars.session_date.unique()}
    # Raw workbench bars are not silently filtered to make them resemble NT.
    closed_day = np.array([ends[str(day)] is None for day in bars.session_date])
    past_close = np.array([ends[str(day)] is not None and pd.Timestamp(ready) > ends[str(day)]
                          for day, ready in zip(bars.session_date, bars.availability_time)])
    outside = bars.loc[closed_day | past_close]
    report = dict(checked_at=datetime.now(timezone.utc).isoformat(), result="RUNNING",
                  scope="Actual compiled C# core vs original Python event decisions on identical historical MNQ inputs; no NT fill/performance validation",
                  interval=dict(start=request["start"], end=request["end"], warmup_days=600),
                  dataset_path=str(dataset.relative_to(ROOT)), calendar_template_version=TEMPLATE_VERSION,
                  python_strategy_version=STRATEGY["version"], parameters=parameters,
                  validation_history=history,
                  source_sha256=before, source_minutes=len(frame), five_minute_bars=len(bars),
                  calendar_audit=dict(outside_template_bars=len(outside),
                                      by_session={str(k): int(v) for k, v in outside.groupby("session_date").size().items()},
                                      first_examples=[dict(time=str(t), session_date=str(r.session_date))
                                                      for t, r in outside.head(20).iterrows()]))
    print(f"Loaded {len(frame):,} minutes / {len(bars):,} five-minute bars; outside calendar: {len(outside)}", flush=True)
    if len(outside):
        report.update(result="CALENDAR_INPUT_MISMATCH", limitation="Unfiltered generic ETH data contains bars NT's calendar would exclude; parity was not fabricated by deleting them.")
        save(report)
        return 1
    with tempfile.TemporaryDirectory(prefix="mnq-orb-real-check-") as temporary:
        folder = Path(temporary)
        exe, fixture, expected_path, actual_path = (folder / name for name in
                                                    ["orb-replay.exe", "input.txt", "expected.txt", "actual.txt"])
        subprocess.run([str(CSC), "/nologo", "/warnaserror+", "/langversion:5", f"/out:{exe}",
                        str(CORE), str(HARNESS)], check=True)
        with fixture.open("w", encoding="utf-8") as inputs, expected_path.open("w", encoding="utf-8") as expected:
            traced = TracedModel(IntradayORB(bars, parameters, request), ends, inputs, expected)
            try:
                _, trades, _ = simulate_events(bars, traced, request, execution_bars=frame)
            except Exception as exc:
                report.update(result="PYTHON_REPLAY_FAILED", traced_bars=traced.rows,
                              error=f"{type(exc).__name__}: {exc}")
                save(report)
                return 1
        with fixture.open("r", encoding="utf-8") as inputs, actual_path.open("w", encoding="utf-8") as actual:
            completed = subprocess.run([str(exe)], stdin=inputs, stdout=actual, stderr=subprocess.PIPE, text=True)
        if completed.returncode:
            report.update(result="CSHARP_REPLAY_FAILED", traced_bars=traced.rows, error=completed.stderr)
            save(report)
            return 1
        counts, examples = Counter(), []
        compared = 0
        with expected_path.open(encoding="utf-8") as expected, actual_path.open(encoding="utf-8") as actual:
            for expected_line in expected:
                want = expected_line.strip().split(";")
                got = actual.readline().strip().split(";")
                if len(got) != 9:
                    counts["missing_or_invalid_actual_row"] += 1
                    if len(examples) < 20: examples.append(dict(index=int(want[0]), time=want[1], expected=want[2:], actual=got))
                    continue
                failures = []
                for name, left, right in [("action", want[2], got[0]), ("quantity", want[3], got[1])]:
                    if left != right: failures.append(name)
                numbers = [("daily_score", want[6], got[4])]
                # Python emits no bracket/order for a risk skip. C# retains the
                # unused candidate prices for diagnostics; these are not orders.
                if want[2] in ("Long", "Short"):
                    numbers += [("stop", want[4], got[2]), ("target", want[5], got[3])]
                for name, left, right in numbers:
                    if not equal_number(left, right): failures.append(name)
                counts.update(failures)
                if failures and len(examples) < 20:
                    examples.append(dict(index=int(want[0]), time=want[1], fields=failures,
                                         expected=want[2:], actual=got[:5]))
                compared += 1
            extra = sum(1 for _ in actual)
            if extra: counts["extra_actual_rows"] += extra
        unchanged = before == digests()
        report.update(result="PASS" if not counts and unchanged else "FAIL", traced_bars=traced.rows,
                      compared_bars=compared, held_position_decisions=traced.held_rows,
                      python_action_counts=dict(traced.actions), completed_python_trades=len(trades),
                      submitted_entry_brackets_compared=traced.actions["Long"] + traced.actions["Short"],
                      risk_skips_with_no_submitted_bracket=traced.actions["RiskSkipped"],
                      mismatch_counts=dict(counts), first_mismatches=examples, source_unchanged_during_test=unchanged,
                      limitations=["Core receives the original Python simulator's actual pre-decision position and tradable state; it does not emulate NT order lifecycle.",
                                   "Only submitted entry brackets are compared; zero-quantity risk skips have no Python bracket order. NT submits market orders for subsequent quotes and may fill differently.",
                                   "No calendar bars were removed. Native NT data vendor, merge policy and template updates can still change input prices.",
                                   "This is previously inspected historical regression, not a new holdout or profitability conclusion."])
        save(report)
        return 0 if report["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
