"""Focused synthetic checks for the standalone higher-timeframe wick study."""

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "research-htf-wick-phases.py"
SPEC = importlib.util.spec_from_file_location("research_htf_wick_phases", SCRIPT)
study = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(study)


def config(**overrides):
    result = dict(symbol="MNQ", tick_size=.25, start="2025-01-01", end="2025-12-31",
                  coverage_fraction=.90, min_minutes={}, phase_bars=6, context_bars=20,
                  compact_atr=2.5, trend_atr=1., wick_skew=.10,
                  cooldown_bars=6, horizons=[3, 6], bootstrap_samples=200, seed=1729)
    result.update(overrides)
    return result


def candles(rows, timeframe="1h", ids=None, counts=None):
    if timeframe == "1h" and len(rows) < 23:
        extra = 23 - len(rows)
        rows = [*rows, *([rows[-1]] * extra)]
        if isinstance(ids, list):
            ids = [*ids, *([ids[-1]] * extra)]
        if isinstance(counts, list):
            counts = [*counts, *([counts[-1]] * extra)]
    start = pd.Timestamp("2025-01-05T18:00:00", tz="America/New_York")
    allowed_hours = {"1h": set(range(18, 24)) | set(range(0, 17)),
                     "4h": {18, 22, 2, 6, 10, 14}, "1d": {18}}[timeframe]
    clock = start
    stamps = []
    while len(stamps) < len(rows):
        day = clock.dayofweek
        if (clock.hour in allowed_hours and
                (day < 4 or day == 4 and clock.hour < 17 or day == 6 and clock.hour >= 18)):
            stamps.append(clock)
        clock += pd.Timedelta(hours=1)
    index = pd.DatetimeIndex(stamps).tz_convert("UTC")
    frame = pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=index, dtype=float)
    frame["minute_count"] = counts if counts is not None else {"1h": 60, "4h": 240, "1d": 1380}[timeframe]
    frame["instrument_id"] = ids if ids is not None else 101
    frame["contract_count"] = 1
    frame["is_roll_bar"] = False
    frame["symbol"] = "MNQ.v.0"
    return frame


def engineered_decline():
    rows = []
    for i in range(27):
        middle = 100 - .6 * i
        rows.append([middle + .05, middle + .6, middle - .6, middle])
    # Six compact bars with repeatedly long lower wicks after the decline.
    rows += [[84.4, 84.65, 83.4, 84.55] for _ in range(6)]
    rows += [[84.6, 85.1, 84.2, 84.8], [84.8, 87.2, 84.5, 86.8],
             [86.8, 87.3, 86.3, 87.]]
    rows += [[87., 87.4, 86.6, 87.1] for _ in range(70)]
    return candles(rows)


def mirror(frame, around=200.):
    reflected = frame.copy()
    reflected["open"] = around - frame.open
    reflected["close"] = around - frame.close
    reflected["high"] = around - frame.low
    reflected["low"] = around - frame.high
    return reflected


class WickPhaseStudyTests(unittest.TestCase):
    def test_features_are_causal_and_mirror_symmetrical(self):
        original = engineered_decline()
        rules = config(compact_atr=1.1)
        events, _ = study.detect_and_score(original, "1h", rules)
        at_32 = next(e for e in events if e["signal_index"] == 32)
        self.assertEqual(at_32["cohort"], "accumulation_proxy")
        self.assertGreater(at_32["wick_skew"], .1)
        self.assertLess(at_32["prior_trend_atr"], -1.)
        self.assertGreater(at_32["signal_open_location"], 0.)
        self.assertGreater(at_32["signal_close_location"], at_32["signal_open_location"])
        self.assertAlmostEqual(at_32["h3_future_close_phase_location_change"],
                               (original.close.iloc[35] - original.close.iloc[32]) / at_32["phase_range"])
        self.assertGreater(at_32["h3_future_close_phase_location"], 1.)

        changed_future = original.copy()
        changed_future.loc[changed_future.index[33:], ["open", "high", "low", "close"]] += 50
        changed, _ = study.detect_and_score(changed_future, "1h", rules)
        same_signal = next(e for e in changed if e["signal_index"] == 32)
        for field in ("cohort", "selected", "atr_prephase", "prior_trend_atr", "wick_skew", "phase_close_location"):
            self.assertEqual(same_signal[field], at_32[field], field)

        mirrored, _ = study.detect_and_score(mirror(original), "1h", rules)
        reflected = next(e for e in mirrored if e["signal_index"] == 32)
        self.assertEqual(reflected["cohort"], "distribution_proxy")
        self.assertEqual(reflected["selected"], at_32["selected"])
        self.assertAlmostEqual(reflected["wick_skew"], -at_32["wick_skew"])
        self.assertAlmostEqual(reflected["prior_trend_atr"], -at_32["prior_trend_atr"])
        self.assertEqual(reflected["h3_outcome"], "down_first")
        self.assertEqual(at_32["h3_outcome"], "up_first")

    def test_greedy_episodes_do_not_overlap_outcome_horizons(self):
        events, quality = study.detect_and_score(engineered_decline(), "1h", config(compact_atr=100., trend_atr=.1))
        selected = [e["signal_index"] for e in events if e["selected"]]
        self.assertGreater(len(selected), 1)
        self.assertEqual(quality["candidate_window_count"], len(events))
        self.assertEqual(quality["selected_episode_count"], len(selected))
        self.assertTrue(all(b - a > 6 for a, b in zip(selected, selected[1:])))

    def test_roll_or_invalid_future_bar_censors_without_skipping(self):
        frame = candles([[100, 100.5, 99.5, 100]] * 7)
        frame.loc[frame.index[2:], "instrument_id"] = 202
        market = study.prepare(frame, "1h", .9)
        event = dict(signal_index=0, instrument_id="101", signal_close=100., atr_prephase=1.,
                     phase_low=99., phase_high=101., phase_close_location=.5)
        result = study.score_horizon(event, market, 3, len(frame))
        self.assertEqual(result["h3_outcome"], "incomplete")
        self.assertEqual(result["h3_censor_reason"], "contract_transition")
        frame.loc[frame.index[2:], "instrument_id"] = 101
        frame.loc[frame.index[1], "minute_count"] = 1
        market = study.prepare(frame, "1h", .9)
        result = study.score_horizon(event, market, 3, len(frame))
        self.assertEqual(result["h3_censor_reason"], "invalid_future_bar")

    def test_first_hit_ambiguity_and_location_change(self):
        frame = candles([[100, 100.5, 99.5, 100], [100, 101.5, 98.5, 100.2],
                         [100.2, 100.5, 99.8, 100], [100, 100.4, 99.7, 100]])
        market = study.prepare(frame, "1h", .9)
        event = dict(signal_index=0, instrument_id="101", signal_close=100., atr_prephase=1.,
                     phase_low=99., phase_high=101., phase_close_location=.5)
        result = study.score_horizon(event, market, 3, len(frame))
        self.assertEqual(result["h3_outcome"], "ambiguous")
        self.assertEqual(result["h3_first_hit_bar"], 1)
        self.assertAlmostEqual(result["h3_future_close_phase_location_change"], 0.)
        self.assertAlmostEqual(result["h3_excursion_lean"], 0.)
        self.assertEqual(study.score_horizon(event, market, 3, 3)["h3_censor_reason"], "period_boundary")

    def test_tick_floor_and_session_minute_coverage(self):
        frame = engineered_decline()
        frame.loc[frame.index[32], ["open", "close"]] = 84.5
        events, _ = study.detect_and_score(frame, "1h", config())
        event = next(e for e in events if e["signal_index"] == 32)
        self.assertEqual(event["signal_body"], 0.)
        self.assertEqual(event["signal_lower_body_ratio"], event["signal_lower_wick"] / .25)
        self.assertTrue(np.isfinite(event["upper_body_ratio"]))

        # A normal final 4h CME bucket has 180 expected minutes, not 240.
        index = pd.DatetimeIndex([pd.Timestamp(f"2025-01-0{5 if hour in (18, 22) else 6}T{hour:02d}:00:00", tz="America/New_York")
                                  for hour in (18, 22, 2, 6, 10, 14)]).tz_convert("UTC")
        four = pd.DataFrame([[100, 101, 99, 100]] * 6,
                            columns=["open", "high", "low", "close"], index=index)
        four["minute_count"] = [240, 240, 240, 240, 170, 170]
        four["instrument_id"] = 1
        four["contract_count"] = 1
        four["is_roll_bar"] = False
        four["symbol"] = "MNQ.v.0"
        market = study.prepare(four, "4h", .9)
        self.assertEqual(market["valid"].tolist(), [True, True, True, True, False, True])
        self.assertEqual(market["available"][-1], pd.Timestamp("2025-01-06T17:00:00", tz="America/New_York"))
        self.assertEqual(study.bar_availability(index[:1], "1d")[0],
                         pd.Timestamp("2025-01-06T17:00:00", tz="America/New_York"))

    def test_missing_bucket_invalidates_entire_session(self):
        frame = candles([[100, 101, 99, 100]] * 46)
        frame = frame.drop(frame.index[5])
        market = study.prepare(frame, "1h", .9)
        self.assertEqual(market["quality"]["incomplete_session_count"], 1)
        self.assertEqual(market["quality"]["incomplete_session_rows"], 22)
        self.assertFalse(market["valid"][:22].any())
        self.assertTrue(market["valid"][22:].all())
        event = dict(signal_index=0, instrument_id="101", signal_close=100., atr_prephase=1.,
                     phase_low=99., phase_high=101., phase_close_location=.5)
        self.assertEqual(study.score_horizon(event, market, 3, len(frame))["h3_censor_reason"], "invalid_future_bar")

    def test_protocol_is_registered_before_failed_analysis(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            input_path = root / "in.parquet"
            output_path = root / "result"
            bad = pd.DataFrame({"open": [1.], "high": [2.], "low": [0.], "close": [1.]},
                               index=pd.DatetimeIndex([pd.Timestamp("2025-01-06T18:00:00Z")]))
            bad.to_parquet(input_path)
            argv = [str(SCRIPT), "--input", f"1h={input_path}", "--output-dir", str(output_path)]
            with patch.object(sys, "argv", argv):
                with self.assertRaisesRegex(ValueError, "Required candle/provenance columns"):
                    study.main()
            protocol_path = output_path / "protocol.json"
            self.assertTrue(protocol_path.is_file())
            protocol = json.loads(protocol_path.read_text())
            self.assertEqual(protocol["design_status"], "retrospective/exploratory; prior workspace research inspected history")
            self.assertEqual(protocol["inputs"]["1h"]["sha256"], study.sha256_file(input_path))
            self.assertEqual(protocol["source_sha256"], study.sha256_file(output_path / "source" / SCRIPT.name))


if __name__ == "__main__":
    unittest.main()
