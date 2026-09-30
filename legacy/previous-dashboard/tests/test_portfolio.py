from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from dashboard_api.portfolio import (
    PortfolioRepository, build_decision, experiment_result, metrics_for, parse_time, reproduce_decision,
    portfolio_snapshot, return_rows, stable_hash,
    what_if_snapshot,
)


class PortfolioEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.repository = PortfolioRepository(Path(self.temporary.name) / "dashboard.sqlite3")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def strategy(self, strategy_id: str = "alpha", *, hard_limit: float | None = None, qualified: bool = True) -> dict:
        return self.repository.create_strategy({
            "strategy_id": strategy_id, "name": strategy_id.title(), "version": "v1",
            "eligibility": "Qualified" if qualified else "Provisional",
            "acceptance_profile": {"objective": "fixture"} if qualified else None,
            "reviewer": "test owner" if qualified else None,
            "selection_date": "2025-01-01" if qualified else None,
            "code_hash": "a" * 64, "base_allocation": 0.4, "exposure_cap": 0.5,
            "hard_drawdown_limit": hard_limit,
        })

    def configure(self) -> None:
        self.repository.update_settings({
            "calendar": "fixture-weekdays", "review_cadence": "month-end", "staleness_days": 30,
            "portfolio_volatility_budget": 0.20, "volatility_floor": 0.05, "gross_exposure_limit": 1.0,
            "margin_limit": 100000.0,
            "outage_procedure": "hold existing exposure and investigate", "decision_owner": "test owner",
            "policy_version": "fixture-policy-v1", "policy_state": "Approved for allocation proposals",
        })

    def returns(self, strategy_id: str, values: list[float], *, history_type: str = "live", start_day: int = 1) -> None:
        rows = []
        for index, value in enumerate(values):
            day = start_day + index
            rows.append({
                "event_time": f"2026-01-{day:02d}T21:00:00Z", "availability_time": f"2026-01-{day:02d}T22:00:00Z",
                "observation_type": "return", "history_type": history_type, "net_return": value,
            })
        result = self.repository.import_observations(strategy_version_id=strategy_id, rows=rows, source="test fixture")
        self.assertEqual(result["rejected"], 0)

    def test_unknown_is_not_zero_target(self) -> None:
        strategy = self.strategy(qualified=False)
        snapshot = portfolio_snapshot(self.repository, "2026-01-05T00:00:00Z")
        item = next(value for value in snapshot["strategies"] if value["id"] == strategy["id"])
        self.assertEqual(item["health"], "Unknown")
        self.assertEqual(item["allocation_state"], "No current proposal")
        self.assertIsNone(item["proposed_exposure"])

    def test_hard_breach_produces_explicit_pause_even_without_configuration(self) -> None:
        strategy = self.strategy(hard_limit=0.10)
        self.returns(strategy["id"], [0.0, -0.20])
        snapshot = portfolio_snapshot(self.repository, "2026-01-03T00:00:00Z")
        item = next(value for value in snapshot["strategies"] if value["id"] == strategy["id"])
        self.assertEqual(item["health"], "Breached")
        self.assertEqual(item["allocation_state"], "Paused")
        self.assertEqual(item["proposed_exposure"], 0.0)

    def test_future_observations_do_not_change_earlier_snapshot(self) -> None:
        strategy = self.strategy()
        self.configure()
        self.returns(strategy["id"], [0.01, -0.005], history_type="reference")
        self.returns(strategy["id"], [0.01, -0.005], history_type="live")
        first = build_decision(self.repository, "2026-01-03T00:00:00Z")
        result = self.repository.import_observations(strategy_version_id=strategy["id"], source="future", rows=[{
            "event_time": "2026-02-01T21:00:00Z", "availability_time": "2026-02-01T22:00:00Z",
            "observation_type": "return", "history_type": "live", "net_return": 0.50,
        }])
        self.assertEqual(result["accepted"], 1)
        second = build_decision(self.repository, "2026-01-03T00:00:00Z")
        self.assertEqual(first["snapshot_hash"], second["snapshot_hash"])
        self.assertEqual(first["proposals"], second["proposals"])

    def test_cash_flow_adjusted_equity_return(self) -> None:
        observations = [
            {"event_time": "2026-01-01T00:00:00Z", "observation_type": "return", "history_type": "live", "equity": 100.0},
            {"event_time": "2026-01-02T00:00:00Z", "observation_type": "return", "history_type": "live", "equity": 150.0, "cash_flow": 50.0},
        ]
        rows = return_rows(observations, "live")
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(rows[0]["net_return"], 0.0)

    def test_reference_and_live_histories_are_separate(self) -> None:
        strategy = self.strategy()
        self.returns(strategy["id"], [0.01, 0.02], history_type="reference")
        self.returns(strategy["id"], [-0.01, -0.02], history_type="live", start_day=5)
        snapshot = portfolio_snapshot(self.repository, "2026-01-10T00:00:00Z")
        item = next(value for value in snapshot["strategies"] if value["id"] == strategy["id"])
        self.assertEqual(item["history_coverage"], {"live": 2, "paper": 0, "reference": 2, "backtest": 0})
        self.assertNotEqual(item["live_equity_curve"][-1]["equity"], item["reference_equity_curve"][-1]["equity"])

    def test_strategy_versions_and_settings_are_append_only(self) -> None:
        strategy = self.strategy()
        with self.assertRaises(sqlite3.IntegrityError):
            self.repository.create_strategy({**strategy})
        first_version = self.repository.settings()["version"]
        self.repository.update_settings({"calendar": "CME"})
        self.assertGreater(self.repository.settings()["version"], first_version)
        self.assertEqual(self.repository.strategy(strategy["id"])["code_hash"], "a" * 64)

    def test_eligibility_decisions_are_append_only_without_rewriting_version(self) -> None:
        strategy = self.repository.create_strategy({
            "strategy_id": "candidate", "name": "Candidate", "version": "v1", "eligibility": "Provisional",
            "selection_date": "2025-01-01", "code_hash": "b" * 64,
        })
        accepted = self.repository.assess_eligibility({
            "strategy_version_id": strategy["id"], "eligibility": "Qualified", "reviewer": "owner",
            "evidence_strength": "Moderate", "acceptance_profile": {"objective": "positive net edge under stressed costs"},
            "evidence_snapshot": {"run_id": "sealed-run", "net_sharpe": 0.5}, "reason_codes": ["RECORDED_ACCEPTANCE"],
        })
        self.assertEqual(accepted["eligibility"], "Qualified")
        self.assertEqual(self.repository.strategy(strategy["id"])["eligibility"], "Provisional")
        self.assertEqual(self.repository.strategies()[0]["eligibility"], "Qualified")
        rejected = self.repository.assess_eligibility({
            "strategy_version_id": strategy["id"], "eligibility": "Rejected", "reviewer": "owner",
            "evidence_strength": "Strong", "evidence_snapshot": {"reason": "failed forward test"},
        })
        self.assertEqual(rejected["eligibility"], "Rejected")
        self.assertEqual(len(self.repository.eligibility_history(strategy["id"])), 2)
        self.assertEqual(self.repository.strategies()[0]["eligibility"], "Rejected")

    def test_decision_reproduction_material_is_sealed(self) -> None:
        strategy = self.strategy()
        self.returns(strategy["id"], [0.01, 0.01], history_type="live")
        decision = build_decision(self.repository, "2026-01-03T00:00:00Z")
        self.repository.save_decision(decision)
        loaded = self.repository.decisions()[0]
        self.assertEqual(stable_hash(loaded["input_snapshot"]), loaded["snapshot_hash"])
        self.assertEqual(loaded["proposals"][0]["proposed_exposure"], None)
        reproduced = reproduce_decision(loaded)
        self.assertTrue(reproduced["reproduced"])
        self.assertEqual(reproduced["expected_output_hash"], reproduced["actual_output_hash"])

    def test_effective_time_cannot_precede_cutoff(self) -> None:
        self.strategy()
        with self.assertRaises(ValueError):
            build_decision(self.repository, "2026-01-03T00:00:00Z", "2026-01-02T00:00:00Z")

    def test_review_status_uses_prior_decision_without_placing_orders(self) -> None:
        self.strategy()
        self.configure()
        before = portfolio_snapshot(self.repository, "2026-01-03T00:00:00Z")
        self.assertTrue(before["portfolio"]["review_due"])
        decision = build_decision(self.repository, "2026-01-03T00:00:00Z")
        self.repository.save_decision(decision)
        after = portfolio_snapshot(self.repository, "2026-01-03T12:00:00Z")
        self.assertFalse(after["portfolio"]["review_due"])
        self.assertNotIn("review_due", decision["portfolio"])

    def test_removing_a_hedge_recalculates_and_can_increase_risk(self) -> None:
        alpha, hedge = self.strategy("alpha"), self.strategy("hedge")
        self.configure()
        values = [0.01, -0.01, 0.012, -0.008, 0.009, -0.011]
        for strategy, series in ((alpha, values), (hedge, [-value for value in values])):
            self.returns(strategy["id"], series, history_type="reference")
            self.returns(strategy["id"], series, history_type="live", start_day=10)
        baseline = portfolio_snapshot(self.repository, "2026-01-20T00:00:00Z")
        changed = what_if_snapshot(self.repository, {"cutoff": "2026-01-20T00:00:00Z", "paused_strategy_ids": [hedge["id"]]})
        self.assertGreater(changed["what_if"]["portfolio_volatility"], baseline["portfolio"]["portfolio_volatility"])
        self.assertGreater(changed["what_if"]["unallocated_capital"], baseline["portfolio"]["unallocated_capital"])

    def test_metrics_preserve_zero_coverage_and_drawdown(self) -> None:
        empty = metrics_for([], parse_time("2026-01-03T00:00:00Z"), None)
        self.assertEqual(empty["days_observed"], 0)
        self.assertIsNone(empty["current_drawdown"])

    def test_experiment_promotion_requires_evaluation_and_forward_paper_evidence(self) -> None:
        strategy = self.strategy()
        self.returns(strategy["id"], [0.002 if index % 3 else -0.001 for index in range(20)], history_type="reference")
        experiment = experiment_result(self.repository, {
            "name": "fixture policy", "intended_mechanism": "fixture", "primary_objective": "reduce drawdown",
            "minimum_meaningful_improvement": "1%", "acceptable_return_sacrifice": "2%", "strategy_version_ids": [strategy["id"]],
            "start": "2026-01-01T00:00:00Z", "end": "2026-01-31T23:59:59Z", "resizing_cost_bps": 1,
            "cost_stress_bps": 2, "state": "Approved for allocation proposals",
        })
        self.assertEqual(experiment["state"], "Exploratory")
        with self.assertRaises(ValueError):
            self.repository.review_experiment(experiment["id"], {"state": "Approved for allocation proposals", "reviewer": "owner"})
        paper = self.repository.review_experiment(experiment["id"], {
            "state": "Approved for paper proposals", "reviewer": "owner", "untouched_evaluation_evidence": {"run": "outer-test"},
        })
        self.assertEqual(paper["state"], "Approved for paper proposals")
        allocation = self.repository.review_experiment(experiment["id"], {
            "state": "Approved for allocation proposals", "reviewer": "owner",
            "untouched_evaluation_evidence": {"run": "outer-test"}, "forward_paper_evidence": {"run": "paper-1"},
        })
        self.assertEqual(allocation["state"], "Approved for allocation proposals")
        self.assertEqual(self.repository.experiments()[0]["state"], "Approved for allocation proposals")


if __name__ == "__main__":
    unittest.main()
