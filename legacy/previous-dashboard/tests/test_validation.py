from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from dashboard_api.analysis import automated_research_analysis
from dashboard_api.validation import extract_sample, validate_completed_run
from dashboard_api.repository import RunRepository


class ValidationRegressionTests(unittest.TestCase):
    def test_run_updates_preserve_immutable_revisions(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            repository = RunRepository(Path(folder) / "runs.sqlite3")
            payload = {"id": "run-1", "strategy_id": "alpha", "status": "running", "validation_status": "pending",
                       "created_at": "2026-01-01T00:00:00Z", "finished_at": None, "output_dir": "reports/test",
                       "parameters": {}, "validation_checks": [], "artifacts": []}
            repository.save(payload)
            repository.save({**payload, "status": "completed", "finished_at": "2026-01-01T00:01:00Z"})
            self.assertEqual(repository.load()[0]["status"], "completed")
            self.assertEqual([item["payload"]["status"] for item in repository.revisions("run-1")], ["running", "completed"])

    def test_zero_sessions_are_not_converted_to_unknown(self) -> None:
        self.assertEqual(extract_sample({"sessions": 0, "trades": 0}), (0, 0))

    def test_null_chronology_field_does_not_pass(self) -> None:
        result = automated_research_analysis(
            summary={"statistics": {"trades": 50, "net_dollars": 10}, "evaluation_period": None},
            parameters={}, validation_status="data_validated", validation_checks=[],
        )
        chronology = next(check for check in result["checks"] if check["code"] == "CHRON")
        self.assertEqual(chronology["state"], "unknown")

    def test_empty_evaluation_period_does_not_pass_chronology(self) -> None:
        result = automated_research_analysis(
            summary={"evaluation_period": {"start": None, "end": None}},
            parameters={}, validation_status="data_validated", validation_checks=[],
        )
        chronology = next(check for check in result["checks"] if check["code"] == "CHRON")
        self.assertEqual(chronology["state"], "unknown")

    def test_overlapping_performance_sections_are_not_summed(self) -> None:
        result = automated_research_analysis(
            summary={"statistics": {"trades": 50, "net_dollars": 10}, "alternative": {"trades": 50, "net_dollars": 8}},
            parameters={}, validation_status="data_validated", validation_checks=[],
        )
        coverage = next(check for check in result["checks"] if check["code"] == "COVER")
        self.assertIn("50 closed trades", coverage["observed"])

    def test_evaluation_window_without_development_split_is_not_credible_chronology(self) -> None:
        result = automated_research_analysis(
            summary={"evaluation_period": {"start": "2024-01-01", "end": "2025-01-01"}},
            parameters={}, validation_status="data_validated", validation_checks=[],
        )
        chronology = next(check for check in result["checks"] if check["code"] == "CHRON")
        self.assertEqual(chronology["state"], "unknown")

    def test_declared_development_and_evaluation_periods_pass_chronology(self) -> None:
        result = automated_research_analysis(
            summary={
                "development_period": {"start": "2020-01-01", "end": "2023-12-31"},
                "evaluation_period": {"start": "2024-01-01", "end": "2025-01-01"},
            },
            parameters={}, validation_status="data_validated", validation_checks=[],
        )
        chronology = next(check for check in result["checks"] if check["code"] == "CHRON")
        self.assertEqual(chronology["state"], "pass")

    def test_fake_hash_and_missing_artifact_fail_validation(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "reproducibility.json").write_text(json.dumps({
                "dataset_sha256": "x" * 64, "strategy_sha256": "y" * 64,
                "chart": {"available": True, "rows": 1, "source": "Databento", "first_bar": "a", "last_bar": "b"},
                "parameters": {},
            }))
            status, checks = validate_completed_run(
                return_code=0, output_dir=root, artifacts=[{"name": "missing.csv"}], summary={"sessions": 60, "trades": 1},
            )
            self.assertEqual(status, "rejected")
            self.assertEqual(next(item for item in checks if item["code"] == "reproducibility")["state"], "fail")
            self.assertEqual(next(item for item in checks if item["code"] == "artifacts")["state"], "fail")

    def test_multichart_validation_requires_every_dataset_hash(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "summary.json").write_text("{}")
            chart = {
                "available": True, "rows": 10, "source": "Databento",
                "first_bar": "2026-01-01", "last_bar": "2026-01-02",
            }
            (root / "reproducibility.json").write_text(json.dumps({
                "dataset_sha256": "a" * 64, "strategy_sha256": "b" * 64,
                "chart": {"id": "A", **chart},
                "charts": [{"id": "A", **chart}, {"id": "B", **chart}],
                "dataset_sha256s": {"A": "a" * 64},
                "parameters": {},
            }))
            status, checks = validate_completed_run(
                return_code=0, output_dir=root, artifacts=[{"name": "summary.json"}],
                summary={"sessions": 60, "trades": 1},
            )
            self.assertEqual(status, "rejected")
            self.assertEqual(next(item for item in checks if item["code"] == "reproducibility")["state"], "fail")


if __name__ == "__main__":
    unittest.main()
