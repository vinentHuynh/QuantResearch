import json
import os
import re
import runpy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from workbench.layout import LayoutError, load_layout


ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "shared" / "contracts"


class WorkbenchLayoutTests(unittest.TestCase):
    def test_checked_in_layout_resolves_shared_roots(self):
        layout = load_layout(ROOT, environ={})
        self.assertEqual(layout.schema_version, 1)
        self.assertEqual(layout.protocol_version, 2)
        self.assertEqual(layout.state_root, ROOT / "data" / "workbench")
        self.assertEqual(layout.artifacts_root, ROOT / "artifacts")
        self.assertEqual(layout.evidence_root, ROOT / "evidence")
        self.assertEqual(layout.contracts_root, CONTRACTS)
        self.assertIn(ROOT / "strategies", layout.source_roots)
        self.assertIn(ROOT / "src", layout.source_roots)
        self.assertIn(ROOT / "research", layout.source_roots)
        self.assertIn(ROOT / "tools", layout.source_roots)
        self.assertEqual(layout.source_aliases, {})
        self.assertEqual(
            layout.discovery_paths["strategy_adapters"],
            (ROOT / "strategies",),
        )

    def test_environment_overrides_only_mutable_roots(self):
        with tempfile.TemporaryDirectory() as directory:
            external = Path(directory) / "raw-artifacts"
            layout = load_layout(
                ROOT,
                environ={
                    "WORKBENCH_HOME": "tmp/layout-state",
                    "WORKBENCH_ARTIFACTS": str(external),
                },
            )
        self.assertEqual(layout.state_root, ROOT / "tmp" / "layout-state")
        self.assertEqual(layout.artifacts_root, external)
        self.assertEqual(layout.evidence_root, ROOT / "evidence")

    def test_repository_paths_cannot_escape_workspace(self):
        payload = json.loads((ROOT / "config" / "workbench-layout.json").read_text())
        payload["source_roots"][0] = "../strategies"
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            (workspace / "config").mkdir()
            (workspace / "config" / "workbench-layout.json").write_text(
                json.dumps(payload), encoding="utf-8"
            )
            with self.assertRaisesRegex(LayoutError, "repository-relative"):
                load_layout(workspace, environ={})

    def test_documented_orb_command_uses_overridden_roots_and_both_dataset_protocols(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            state = temporary / "state"
            artifacts = temporary / "artifacts"
            with patch.dict(
                os.environ,
                {
                    "WORKBENCH_HOME": str(state),
                    "WORKBENCH_ARTIFACTS": str(artifacts),
                },
            ):
                command = runpy.run_path(
                    str(ROOT / "scripts" / "analyze-orb-exits.py"),
                    run_name="documented_orb_command_test",
                )

            self.assertEqual(command["STATE_ROOT"], state.resolve())
            self.assertEqual(
                command["OUT"],
                artifacts.resolve() / "research" / "strategy-potential-2026",
            )
            self.assertEqual(
                command["dataset_file"](
                    {"schema_version": 2, "path": "datasets/example/bars.parquet"}
                ),
                state.resolve() / "datasets" / "example" / "bars.parquet",
            )
            legacy = temporary / "legacy-bars.parquet"
            self.assertEqual(
                command["dataset_file"]({"path": str(legacy)}),
                legacy.resolve(),
            )


class ContractSchemaTests(unittest.TestCase):
    expected = {
        "workbench-layout.v1.schema.json",
        "strategy-metadata.v2.schema.json",
        "run-input.v2.schema.json",
        "run-result.v2.schema.json",
        "dataset-manifest.v2.schema.json",
        "source-snapshot.v2.schema.json",
        "evidence-manifest.v2.schema.json",
        "sqlite-record-envelope.v2.schema.json",
    }

    def setUp(self):
        self.schemas = {
            path.name: json.loads(path.read_text(encoding="utf-8"))
            for path in CONTRACTS.glob("*.schema.json")
        }

    def test_contract_set_is_parseable_versioned_and_unique(self):
        self.assertTrue(self.expected.issubset(self.schemas))
        ids = []
        for name in self.expected:
            schema = self.schemas[name]
            self.assertEqual(
                schema["$schema"], "https://json-schema.org/draft/2020-12/schema"
            )
            self.assertTrue(schema["$id"].endswith(name))
            ids.append(schema["$id"])
        self.assertEqual(len(ids), len(set(ids)))

    def test_external_schema_references_resolve_locally(self):
        def references(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    if key == "$ref" and isinstance(item, str):
                        yield item
                    else:
                        yield from references(item)
            elif isinstance(value, list):
                for item in value:
                    yield from references(item)

        for name, schema in self.schemas.items():
            for reference in references(schema):
                if not reference.startswith("#"):
                    self.assertTrue(
                        (CONTRACTS / reference).is_file(),
                        f"{name} has unresolved reference {reference}",
                    )

    def test_v2_identity_and_evidence_fields_are_required(self):
        strategy = self.schemas["strategy-metadata.v2.schema.json"]
        run_input = self.schemas["run-input.v2.schema.json"]
        snapshot = self.schemas["source-snapshot.v2.schema.json"]
        evidence = self.schemas["evidence-manifest.v2.schema.json"]
        self.assertIn("source_files", strategy["required"])
        for field in ("execution_source_hash", "snapshot_hash", "app_build_hash"):
            self.assertIn(field, run_input["required"])
            self.assertIn(field, snapshot["required"])
        for field in (
            "campaign_id",
            "protocol_path",
            "summary_paths",
            "artifacts",
            "consumers",
        ):
            self.assertIn(field, evidence["required"])

    def test_relative_path_contract_rejects_absolute_and_parent_paths(self):
        pattern = self.schemas["source-snapshot.v2.schema.json"]["$defs"][
            "relativePath"
        ]["pattern"]
        self.assertIsNotNone(re.fullmatch(pattern, "strategies/example.py"))
        for invalid in ("/strategies/example.py", "C:/example.py", "../example.py"):
            self.assertIsNone(re.fullmatch(pattern, invalid), invalid)


if __name__ == "__main__":
    unittest.main()
