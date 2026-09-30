from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from dashboard_api.main import WORKFLOWS, build_command, strategy_catalog, strategy_catalog_audit


class RunnerCatalogTests(unittest.TestCase):
    def test_catalog_contains_one_entry_per_implemented_mechanism(self) -> None:
        catalog = strategy_catalog()
        ids = [item["id"] for item in catalog]

        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(ids), 10)
        self.assertIn("opening-range-breakout", ids)
        self.assertNotIn("mgc-orb", ids)
        self.assertNotIn("asia-orb", ids)
        audit = strategy_catalog_audit()
        self.assertEqual(audit["counts"]["migration_candidates"], 0)
        self.assertEqual(audit["counts"]["canonical_pending_parity"], 21)
        self.assertEqual(audit["counts"]["canonical_partial_parity"], 2)
        self.assertEqual(audit["counts"]["canonical_parity_verified"], 0)
        self.assertEqual(audit["counts"]["compatibility_adapters"], 0)
        self.assertEqual(len(audit["specific_strategies"]), 23)
        self.assertEqual(audit["counts"]["all_scripts"], 106)
        self.assertEqual(len(audit["script_inventory"]), 106)
        self.assertEqual(audit["counts"]["pine_scripts"], 17)
        self.assertEqual(audit["counts"]["ninjatrader_scripts"], 6)
        evidence = {
            item["id"]: item["parity_evidence"]
            for item in audit["specific_strategies"] if item["parity_evidence"]
        }
        self.assertEqual(set(evidence), {"cme-tsmom", "es-nq-trend"})
        self.assertTrue(all(item["passed"] for item in evidence.values()))

        orb = next(item for item in catalog if item["id"] == "opening-range-breakout")
        self.assertEqual([session["id"] for session in orb["sessions"]], ["new-york-rth", "london", "asia"])
        self.assertEqual(orb["default_session"], "new-york-rth")
        self.assertNotIn("session", [parameter["key"] for parameter in orb["parameters"]])

    def test_timeframe_is_validated_and_passed_to_generic_runner(self) -> None:
        definition = WORKFLOWS["opening-range-breakout"]
        with tempfile.TemporaryDirectory() as directory:
            command, _ = build_command(definition, "MNQ", "15m", {}, Path(directory))

        self.assertEqual(command[command.index("--timeframe") + 1], "15m")
        self.assertEqual(command[command.index("--session-id") + 1], "new-york-rth")
        self.assertEqual(command[1:4], ["-m", "strategy_engine.runner", "--strategy-id"])
        self.assertNotIn("--five-minute", command)
        with self.assertRaisesRegex(ValueError, "does not support"):
            build_command(definition, "MNQ", "1d", {}, Path("unused"))

    def test_session_is_validated_and_passed_as_a_run_input(self) -> None:
        definition = WORKFLOWS["opening-range-breakout"]
        with tempfile.TemporaryDirectory() as directory:
            command, parameters = build_command(
                definition, "MNQ", "5m", {}, Path(directory), "london",
            )
        self.assertEqual(command[command.index("--session-id") + 1], "london")
        self.assertNotIn("session", parameters)
        with self.assertRaisesRegex(ValueError, "selected session"):
            build_command(definition, "MNQ", "5m", {}, Path("unused"), "sydney")

    def test_next_canonical_strategies_use_named_sessions(self) -> None:
        expected = {
            "multi-speed-momentum": ("full-trading-day", "1d"),
            "moving-average-trend": ("full-trading-day", "1d"),
            "prior-range-fill": ("new-york-rth", "5m"),
            "overnight-session": ("globex-overnight", "5m"),
        }
        for strategy_id, (session_id, timeframe) in expected.items():
            with self.subTest(strategy=strategy_id):
                definition = WORKFLOWS[strategy_id]
                with tempfile.TemporaryDirectory() as directory:
                    command, _ = build_command(definition, "MNQ", timeframe, {}, Path(directory))
                self.assertEqual(definition.data_mode, "engine")
                self.assertEqual(command[command.index("--session-id") + 1], session_id)
                self.assertNotIn("--entry-time", command)
                self.assertNotIn("--exit-time", command)

    def test_multi_chart_strategies_receive_explicit_leg_metadata(self) -> None:
        definition = WORKFLOWS["cross-sectional-momentum"]
        with tempfile.TemporaryDirectory() as directory:
            command, _ = build_command(
                definition, "MNQ", "1d", {}, Path(directory), "full-trading-day",
                ["MNQ", "NQ", "ES"],
            )
        self.assertEqual(command.count("--leg-json"), 3)
        self.assertNotIn("--peer-data", command)
        with self.assertRaisesRegex(ValueError, "requires 3-5 charts"):
            build_command(
                definition, "MNQ", "1d", {}, Path("unused"), "full-trading-day",
                ["MNQ", "NQ"],
            )

        pairs = WORKFLOWS["pairs-mean-reversion"]
        with self.assertRaisesRegex(ValueError, "requires 2 charts"):
            build_command(pairs, "MNQ", "1d", {}, Path("unused"), "full-trading-day", ["MNQ"])

    def test_every_strategy_has_a_valid_default_timeframe(self) -> None:
        for definition in WORKFLOWS.values():
            if definition.kind == "strategy":
                self.assertIn(definition.default_timeframe, definition.timeframes)

    def test_position_strategies_expose_explicit_contract_sizing(self) -> None:
        definition = WORKFLOWS["moving-average-trend"]
        quantity = next(parameter for parameter in definition.parameters if parameter.key == "quantity_mode")
        self.assertEqual(quantity.default, "fractional")
        self.assertEqual(quantity.choices, ("fractional", "whole_contracts"))
        with tempfile.TemporaryDirectory() as directory:
            command, parameters = build_command(
                definition, "MNQ", "1d", {"quantity_mode": "whole_contracts"}, Path(directory),
            )
        self.assertEqual(command[command.index("--quantity-mode") + 1], "whole_contracts")
        self.assertEqual(parameters["quantity_mode"], "whole_contracts")


if __name__ == "__main__":
    unittest.main()
