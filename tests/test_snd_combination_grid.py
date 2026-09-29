"""Synthetic fixture intent, oracle isolation and retained failure accounting."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import importlib.util
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("combination_grid_check", ROOT / "scripts/check-snd-combination-grid.py")
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


def config():
    return dict(config_id="c00000", parameter_hash="unit-test", parameters=checker.reference.DEFAULTS | dict(require_fvg=False))


@contextmanager
def temporary_fast_module(value):
    """Restore only our key, retaining lazy imports and their native registries."""
    name = "strategies._snd_combination_fast"
    missing = object()
    previous = sys.modules.get(name, missing)
    sys.modules[name] = value
    try:
        yield
    finally:
        if previous is missing:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = previous


class SyntheticGridTests(unittest.TestCase):
    def test_fixture_intent_including_threshold_separation_and_adverse_exits(self):
        checks = checker.fixture_checks([config()])
        self.assertEqual(len(checker.fixture_definitions()), 13)
        self.assertTrue(any("intermediate quality" in text for text in checks))
        self.assertEqual(sum("expected simultaneous-bracket" in text for text in checks), 4)

    def test_independent_prepared_inputs_detect_silent_mutation(self):
        def mutating(data, *args, **kwargs):
            result = checker.reference.run_model(data, *args, **kwargs)
            data["chart"].iloc[0, data["chart"].columns.get_loc("bias")] = 77
            return result
        fake = types.SimpleNamespace(run_model=mutating)
        with tempfile.TemporaryDirectory() as directory, temporary_fast_module(fake):
            row = checker.check_fixture(checker.fixture_definitions()[0], [config()], str(Path(directory) / "mismatches"))
        self.assertEqual(row["passed_comparisons"], 1)
        self.assertEqual(row["status"], "failed")
        self.assertEqual(len(row["input_failures"]), 1)
        self.assertEqual(row["input_failures"][0]["engine"], "fast")

    def test_failed_attempt_and_artifact_are_preserved_after_successful_retry(self):
        definition = checker.fixture_definitions()[0]
        source = "scripts/check-snd-combination-grid.py"
        sources = {source: checker.checksum(ROOT / source)}
        def wrong(data, *args, **kwargs):
            result = checker.reference.run_model(data, *args, **kwargs)
            result["equity"].loc[0, "equity"] += 1.
            return result
        fake = types.SimpleNamespace(run_model=wrong)
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            checker.save(out / "protocol.json", {"test": True})
            checker.save(out / "configurations.json", [config()])
            with patch.object(checker, "fixture_definitions", return_value=[definition]), \
                 patch.object(checker, "fixture_checks", return_value=[]), \
                 patch.object(checker, "source_identity", return_value=sources), \
                 patch.object(checker, "ProcessPoolExecutor", ThreadPoolExecutor), \
                 temporary_fast_module(fake):
                first = checker.parity(out, [config()], 1)
                self.assertEqual(first["status"], "failed")
                pointer = checker.read(out / "synthetic-grid-parity.json")
                first_artifact = out / pointer["attempt_artifact"]
                digest = checker.checksum(first_artifact)
                mismatch = next((out / first["attempt_directory"]).glob("mismatches/*/*/mismatch.json"))
                mismatch_digest = checker.checksum(mismatch)
                with self.assertRaisesRegex(ValueError, "Existing synthetic attempt preserved"):
                    checker.parity(out, [config()], 1)
                fake.run_model = checker.reference.run_model
                second = checker.parity(out, [config()], 1, new_attempt=True)
                self.assertEqual(second["status"], "passed")
                self.assertEqual(len(second["prior_attempts"]), 1)
                self.assertEqual(second["prior_attempts"][0]["failed_comparisons"], 1)
                self.assertEqual(checker.checksum(first_artifact), digest)
                self.assertEqual(checker.checksum(mismatch), mismatch_digest)

    def test_fake_module_scope_preserves_unrelated_lazy_imports(self):
        name = "synthetic_grid_lazy_import_sentinel"
        marker = types.ModuleType(name)
        try:
            with temporary_fast_module(types.SimpleNamespace()):
                sys.modules[name] = marker
            self.assertIs(sys.modules[name], marker)
        finally:
            sys.modules.pop(name, None)


if __name__ == "__main__":
    unittest.main()
