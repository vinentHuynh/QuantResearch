from __future__ import annotations

import unittest
import json
import tempfile
from pathlib import Path

from strategy_engine.parity import load_verified_evidence, run_suite


class ParityTests(unittest.TestCase):
    def test_frozen_legacy_calculations_match_canonical_coverage(self) -> None:
        report = run_suite()
        self.assertTrue(report["all_comparisons_passed"])
        self.assertEqual(report["partial_parity_verified"], 2)
        self.assertEqual(report["full_parity_verified"], 0)
        self.assertEqual(
            {item["legacy_id"] for item in report["results"]},
            {"cme-tsmom", "es-nq-trend"},
        )
        self.assertTrue(all(item["full_parity_blockers"] for item in report["results"]))

    def test_tracked_evidence_is_current(self) -> None:
        evidence = load_verified_evidence()
        self.assertEqual(set(evidence), {"cme-tsmom", "es-nq-trend"})

    def test_changed_source_invalidates_tracked_evidence(self) -> None:
        root = Path(__file__).resolve().parents[1]
        tracked = json.loads((root / "strategy_engine" / "parity_evidence.json").read_text())
        paths = {
            tracked["harness"],
            *(item["legacy_source"] for item in tracked["results"]),
            *(item["canonical_source"] for item in tracked["results"]),
        }
        with tempfile.TemporaryDirectory() as folder:
            isolated = Path(folder)
            for relative in paths:
                target = isolated / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((root / relative).read_bytes())
            evidence_path = isolated / "strategy_engine" / "parity_evidence.json"
            evidence_path.write_text(json.dumps(tracked))
            self.assertEqual(set(load_verified_evidence(isolated)), {"cme-tsmom", "es-nq-trend"})
            canonical = isolated / "strategy_engine" / "strategies" / "trend.py"
            canonical.write_text(canonical.read_text() + "\n# changed after parity review\n")
            self.assertEqual(load_verified_evidence(isolated), {})


if __name__ == "__main__":
    unittest.main()
