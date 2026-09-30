import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_script(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {filename}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SQLiteRecordConsumerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.orb = load_script(
                "audit_tsmom_orb_calendar_results",
                "audit-tsmom-orb-calendar-results.py",
            )
        cls.wyckoff = load_script(
                "wyckoff_matched_control",
                "wyckoff_matched_control.py",
            )
        cls.collective = load_script(
                "build_collective",
                "build-collective.py",
            )
        cls.decoders = {
            "orb calendar audit": cls.orb.decode_sqlite_record,
            "wyckoff matched control": cls.wyckoff.decode_sqlite_record,
            "collective catalog": cls.collective.decode_sqlite_record,
        }

    def test_protocol_v2_logical_paths_and_v1_absolute_paths_remain_readable(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory).resolve()
            logical_dataset = home / "datasets" / "fixture.parquet"
            logical_snapshot = home / "sources" / "fixture"
            v2 = {
                "protocol": 2,
                "dataset": {"schema_version": 2, "path": "datasets/fixture.parquet"},
            }
            self.assertEqual(self.wyckoff.dataset_path(v2, home), logical_dataset)
            self.assertEqual(
                self.orb.source_snapshot_path(
                    {"source_snapshot": "sources/fixture"}, home
                ),
                logical_snapshot,
            )
            absolute_dataset = home / "legacy.parquet"
            absolute_snapshot = home / "legacy-source"
            self.assertEqual(
                self.wyckoff.dataset_path(
                    {"dataset": {"path": str(absolute_dataset)}}, home
                ),
                absolute_dataset,
            )
            self.assertEqual(
                self.orb.source_snapshot_path(
                    {"source_dir": str(absolute_snapshot)}, home
                ),
                absolute_snapshot,
            )

    def test_legacy_unwrapped_rows_remain_readable(self):
        body = {"id": "legacy", "status": "Succeeded"}
        for name, decode in self.decoders.items():
            with self.subTest(consumer=name):
                self.assertEqual(decode("run", "legacy", json.dumps(body)), body)

    def test_protocol_v2_rows_are_validated_and_unwrapped(self):
        body = {"id": "current", "status": "Succeeded"}
        envelope = {
            "schema_version": 2,
            "kind": "run",
            "id": "current",
            "body": body,
        }
        for name, decode in self.decoders.items():
            with self.subTest(consumer=name):
                self.assertEqual(decode("run", "current", json.dumps(envelope)), body)

    def test_unwrapped_domain_v2_bodies_are_not_mistaken_for_envelopes(self):
        body = {
            "schema_version": 2,
            "id": "dataset-v2",
            "path": "datasets/bars.parquet",
        }
        for name, decode in self.decoders.items():
            with self.subTest(consumer=name):
                self.assertEqual(
                    decode("dataset", "dataset-v2", json.dumps(body)), body
                )

    def test_malformed_protocol_v2_rows_are_rejected(self):
        invalid = {
            "wrong kind": {
                "schema_version": 2,
                "kind": "evaluation",
                "id": "current",
                "body": {},
            },
            "wrong id": {
                "schema_version": 2,
                "kind": "run",
                "id": "other",
                "body": {},
            },
            "nonobject body": {
                "schema_version": 2,
                "kind": "run",
                "id": "current",
                "body": [],
            },
            "unapproved field": {
                "schema_version": 2,
                "kind": "run",
                "id": "current",
                "body": {},
                "extra": True,
            },
        }
        for consumer, decode in self.decoders.items():
            for case, envelope in invalid.items():
                with self.subTest(consumer=consumer, case=case):
                    with self.assertRaisesRegex(ValueError, "Invalid protocol-v2"):
                        decode("run", "current", json.dumps(envelope))

    def test_nonobject_legacy_rows_are_rejected(self):
        for name, decode in self.decoders.items():
            with self.subTest(consumer=name):
                with self.assertRaisesRegex(ValueError, "Invalid protocol-v1"):
                    decode("run", "legacy", "[]")


if __name__ == "__main__":
    unittest.main()
