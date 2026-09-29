"""Prospective evidence tests use synthetic data, never performance claims."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("snd_forward_test_module", ROOT / "scripts/forward-snd-frozen.py")
forward = importlib.util.module_from_spec(spec)
spec.loader.exec_module(forward)


def bars(start="2026-01-05T12:00:00Z", periods=5, freq="1min"):
    index = pd.date_range(start, periods=periods, freq=freq)
    return pd.DataFrame(dict(open=100., high=101., low=99., close=100., volume=1., instrument_id="contract_a"), index=index)


def empty():
    return pd.DataFrame(columns=forward.BAR_COLUMNS + ["received_at", "capture_class"], index=pd.DatetimeIndex([], tz="UTC"))


def protocol():
    return dict(start="2026-01-05T12:00:00+00:00", warmup_days=30, max_delay_seconds=120, max_prestart_gap_minutes=72*60)


class InputTests(unittest.TestCase):
    def test_standard_csv_and_contract_alias(self):
        frame = bars().rename(columns={"instrument_id": "contract"}).reset_index(names="ts_event")
        frame.ts_event = frame.ts_event.astype(str)
        result = forward.normalize(frame)
        self.assertEqual(str(result.index.tz), "UTC")
        self.assertEqual(list(result.columns), forward.BAR_COLUMNS)

    def test_reject_naive_unordered_duplicate_missing_contract_and_invalid_ohlc(self):
        source = bars()
        cases = [source.set_axis(source.index.tz_localize(None)), source.iloc[::-1],
                 pd.concat([source, source.iloc[-1:]]), source.drop(columns="instrument_id"), source.assign(high=98)]
        for frame in cases:
            with self.subTest(columns=list(frame)), self.assertRaises(ValueError):
                forward.normalize(frame)

    def test_receipt_classification_and_no_prestart_performance(self):
        incoming = bars("2026-01-05T11:59:00Z", 5)
        combined, added, _ = forward.merge_append(empty(), incoming, pd.Timestamp("2026-01-05T12:04:00Z"), protocol())
        self.assertEqual(added.capture_class.tolist(), ["prestart_context", "delayed_replay", "timely_ohlc_simulation", "timely_ohlc_simulation", "timely_ohlc_simulation"])
        self.assertEqual(len(combined), 5)

    def test_exact_overlap_does_not_change_receipt_or_duplicate(self):
        accepted, _, _ = forward.merge_append(empty(), bars(), pd.Timestamp("2026-01-05T12:05:00Z"), protocol())
        result, added, overlaps = forward.merge_append(accepted, bars(periods=6), pd.Timestamp("2026-01-05T12:06:00Z"), protocol())
        self.assertEqual((len(added), overlaps, len(result)), (1, 5, 6))
        pd.testing.assert_frame_equal(result.iloc[:5], accepted)

    def test_revision_rejects_entire_batch_without_changing_original(self):
        accepted, _, _ = forward.merge_append(empty(), bars(), pd.Timestamp("2026-01-05T12:05:00Z"), protocol())
        original = accepted.copy()
        incoming = bars(periods=6)
        incoming.loc[incoming.index[0], "volume"] = 2
        with self.assertRaisesRegex(ValueError, "Revision quarantined"):
            forward.merge_append(accepted, incoming, pd.Timestamp("2026-01-05T12:06:00Z"), protocol())
        pd.testing.assert_frame_equal(accepted, original)

    def test_missing_poststart_bar_cannot_be_inserted_later(self):
        source = bars().drop(bars().index[2])
        accepted, _, _ = forward.merge_append(empty(), source, pd.Timestamp("2026-01-05T12:05:00Z"), protocol())
        with self.assertRaisesRegex(ValueError, "Late insertion"):
            forward.merge_append(accepted, bars(), pd.Timestamp("2026-01-05T12:06:00Z"), protocol(), allow_context_backfill=True)

    def test_prestart_context_can_fill_gap_only_before_simulation(self):
        source = bars("2026-01-04T12:00:00Z").iloc[[0, 4]]
        accepted, _, _ = forward.merge_append(empty(), source, pd.Timestamp("2026-01-05T12:05:00Z"), protocol())
        missing = bars("2026-01-04T12:01:00Z", 3)
        with self.assertRaisesRegex(ValueError, "Late insertion"):
            forward.merge_append(accepted, missing, pd.Timestamp("2026-01-05T12:06:00Z"), protocol())
        result, added, _ = forward.merge_append(accepted, missing, pd.Timestamp("2026-01-05T12:06:00Z"), protocol(), allow_context_backfill=True)
        self.assertEqual(len(added), 3)
        self.assertTrue(result.index.is_monotonic_increasing)
        self.assertTrue((added.capture_class == "prestart_context").all())

    def test_unfinished_bars_are_retained_raw_but_not_accepted_early(self):
        accepted, _, _ = forward.merge_append(empty(), bars(), pd.Timestamp("2026-01-05T12:03:30Z"), protocol())
        self.assertEqual(len(accepted), 3)
        result, added, _ = forward.merge_append(accepted, bars(), pd.Timestamp("2026-01-05T12:05:00Z"), protocol())
        self.assertEqual((len(result), len(added)), (5, 2))

    def test_warmup_blocks_stale_and_large_missing_history(self):
        source = bars("2025-12-06T12:00:00Z", periods=30, freq="1D")
        self.assertTrue(forward.warmup_status(source, protocol())["ready"])
        self.assertFalse(forward.warmup_status(source.iloc[:9], protocol())["ready"])
        self.assertFalse(forward.warmup_status(pd.concat([source.iloc[:5], source.iloc[-15:]]), protocol())["ready"])


class JournalTests(unittest.TestCase):
    def init(self, out):
        return forward.init(out, clock="2026-01-05T11:59:31Z")

    def test_freeze_ceil_boundary_and_detect_protocol_or_source_tampering(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / "experiment"
            frozen = self.init(out)
            self.assertEqual(frozen["start"], pd.Timestamp("2026-01-05T12:00:00Z"))
            self.assertEqual(frozen["review_after"], pd.Timestamp("2026-04-05T12:00:00Z"))
            self.assertEqual(frozen["variants"]["risk_100_max10"]["risk_budget"], 100)
            forward.verify(out)
            with self.assertRaises(ValueError):
                self.init(out)
            path = out / "source/strategies/_snd_risk_research.py"
            path.write_text(path.read_text() + "\n# tampered\n")
            with self.assertRaisesRegex(ValueError, "Frozen source changed"):
                forward.verify(out)

    def test_empty_checks_are_chained_and_keep_waiting_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / "experiment"
            self.init(out)
            with patch.object(forward, "discover", return_value=([], [])):
                first = forward.check(out, clock="2026-01-05T12:00:00Z")
                second = forward.check(out, clock="2026-01-06T12:00:00Z")
            self.assertEqual(first["simulation"]["status"], "waiting_for_complete_warmup")
            self.assertEqual(second["accepted_rows"], 0)
            self.assertEqual(len(forward.verify(out)), 2)
            with patch.object(forward, "discover", return_value=([], [])), self.assertRaisesRegex(ValueError, "Clock regressed"):
                forward.check(out, clock="2026-01-05T13:00:00Z")
            first_path = out / "checks/000001/check.json"
            first_path.write_text(first_path.read_text() + " ")
            with self.assertRaisesRegex(ValueError, "Check content changed"):
                forward.verify(out)

    def test_changed_driver_or_environment_cannot_change_frozen_replay(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / "experiment"
            self.init(out)
            changed_driver = Path(temp) / "changed.py"
            changed_driver.write_text("# different driver\n")
            with patch.object(forward, "__file__", str(changed_driver)), self.assertRaisesRegex(ValueError, "Executing driver differs"):
                forward.verify(out)
            with patch.object(forward.pd, "__version__", "different"), self.assertRaisesRegex(ValueError, "differs from frozen environment"):
                forward.verify(out)

    def test_check_preserves_changed_raw_source_and_quarantines_revision(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / "experiment"
            self.init(out)
            src = Path(temp) / "input.parquet"
            bars().to_parquet(src)
            candidates = ([dict(path=str(src), origin="test")], [])
            with patch.object(forward, "discover", return_value=candidates):
                first = forward.check(out, clock="2026-01-05T12:05:00Z")
                bars().assign(volume=2).to_parquet(src)
                second = forward.check(out, clock="2026-01-05T12:06:00Z")
            self.assertEqual(first["accepted_rows"], 5)
            self.assertEqual(second["ingestions"][0]["status"], "quarantined")
            self.assertEqual(second["accepted_rows"], 5)
            self.assertEqual(len(list((out / "inputs").glob("*"))), 2)
            self.assertEqual(len(forward.verify(out)), 2)

    def test_real_model_nonfinalized_replay_extension_keeps_prior_events(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / "experiment"
            self.init(out)
            src = Path(temp) / "input.parquet"
            # Synthetic stable prices yield no trading claim, but exercise actual
            # frozen model, event snapshots, coverage and extension consistency.
            source = bars("2025-12-06T12:00:00Z", periods=30*24*60+10)
            source.iloc[:-5].to_parquet(src)
            candidates = ([dict(path=str(src), origin="test")], [])
            with patch.object(forward, "discover", return_value=candidates):
                first = forward.check(out, clock="2026-01-05T12:05:00Z")
                source.to_parquet(src)
                second = forward.check(out, clock="2026-01-05T12:10:00Z")
            self.assertEqual(first["simulation"]["status"], "prospective_simulation_updated", first["errors"])
            self.assertEqual(second["simulation"]["status"], "prospective_simulation_updated", second["errors"])
            self.assertEqual(second["poststart_rows"], 10)
            self.assertEqual(len(forward.verify(out)), 2)
            for name in ["fixed_one", "risk_100_max10"]:
                state = forward.read(out / "checks/000002" / name / "open-state.json")
                self.assertIsNone(state["active"])
                self.assertEqual(second["simulation"]["variants"][name]["closed_trades"], 0)


if __name__ == "__main__":
    unittest.main()
