import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from workbench.evidence import EvidenceRegistry, EvidenceRegistryError


ROOT = Path(__file__).resolve().parents[1]


class EvidenceRegistryContractTests(unittest.TestCase):
    def fixture(self, folder: Path):
        evidence = folder / "evidence"
        manifests = evidence / "manifests"
        artifacts = folder / "artifacts"
        target = artifacts / "research" / "fixture" / "summary.json"
        manifests.mkdir(parents=True)
        target.parent.mkdir(parents=True)
        target.write_bytes(b"{}")
        (evidence / "registry.json").write_text(json.dumps({
            "schema_version": 1,
            "campaigns": [{"campaign_id": "fixture", "manifest": "manifests/fixture.json"}],
        }), encoding="utf-8")
        manifest = {
            "schema_version": 2,
            "campaign_id": "fixture",
            "created_at": "2026-09-29T00:00:00Z",
            "protocol_path": "research/fixture/summary.json",
            "summary_paths": ["research/fixture/summary.json"],
            "artifacts": [{
                "role": "summary",
                "relative_path": "research/fixture/summary.json",
                "bytes": 2,
                "sha256": hashlib.sha256(b"{}").hexdigest(),
            }],
            "consumers": ["test"],
        }
        manifest_path = manifests / "fixture.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        return evidence / "registry.json", artifacts, manifest_path, manifest

    def test_complete_v2_manifest_is_verified(self):
        with tempfile.TemporaryDirectory() as directory:
            registry, artifacts, _, _ = self.fixture(Path(directory))
            campaign = EvidenceRegistry(
                ROOT, registry_path=registry, artifacts_root=artifacts
            ).campaign("fixture", consumer="test")
            self.assertEqual(campaign.file("summary").read_bytes(), b"{}")

    def test_v2_manifest_is_closed_and_requires_created_at(self):
        for mutation in ("missing_created_at", "extra_field", "extra_artifact_field"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                registry, artifacts, manifest_path, manifest = self.fixture(Path(directory))
                if mutation == "missing_created_at":
                    del manifest["created_at"]
                elif mutation == "extra_field":
                    manifest["extra"] = True
                else:
                    manifest["artifacts"][0]["extra"] = True
                manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
                with self.assertRaises(EvidenceRegistryError):
                    EvidenceRegistry(
                        ROOT, registry_path=registry, artifacts_root=artifacts
                    ).campaign("fixture", consumer="test")

    def test_logical_paths_must_be_canonical(self):
        for value in ("a//b", "a/./b", "C:foo", "../foo", "a\\b"):
            with self.subTest(value=value), self.assertRaises(EvidenceRegistryError):
                EvidenceRegistry._safe_relative(value, "fixture")


if __name__ == "__main__":
    unittest.main()
