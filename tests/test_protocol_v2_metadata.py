import hashlib
import ast
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from workbench.contract import discover, metadata
from workbench.library import find_entry, inventory


ROOT = Path(__file__).resolve().parents[1]
BASELINE_STRATEGY_IDS = {
    "aw-model-nq",
    "buy-hold",
    "market-intraday-momentum",
    "moving-average",
    "multi-speed-momentum",
    "pine-daily-tsmom",
    "pine-overnight-block",
    "pine-overnight-drift",
    "pine-tsmom-orb",
    "rsi2-reversion",
    "rsi2-reversion-corrected",
    "short-term-reversal",
    "short-term-reversal-minute",
    "snd",
    "snd-zone-exit",
    "vwap-reversion",
    "wyckoff-nq",
}


def strategy_literal(*, include_sources=True, **changes):
    value = {
        "schema_version": 2,
        "id": "fixture-strategy",
        "name": "Fixture",
        "description": "Static metadata fixture.",
        "version": "1.0.0",
        "timeframes": ["1h"],
        "capabilities": ["equity", "trades", "positions"],
        "parameters": {},
        "source_files": ["strategies/fixture.py"],
    }
    if not include_sources:
        value.pop("source_files")
    value.update(changes)
    return "STRATEGY = " + repr(value) + "\n"


class ProtocolV2MetadataTests(unittest.TestCase):
    def test_checked_in_discovery_is_exact_and_has_valid_execution_sources(self):
        result = discover(ROOT)
        self.assertEqual(result["errors"], [])
        tracked_files = set(
            subprocess.check_output(
                ["git", "ls-files"],
                cwd=ROOT,
                text=True,
            ).splitlines()
        )
        tracked_strategies = [
            strategy
            for strategy in result["strategies"]
            if strategy["file"] in tracked_files
        ]
        self.assertEqual(
            {strategy["id"] for strategy in tracked_strategies},
            BASELINE_STRATEGY_IDS,
        )
        tracked_library = [
            entry
            for entry in result["library"]["entries"]
            if entry["path"] in tracked_files
        ]
        self.assertEqual(len(tracked_library), 171)
        self.assertEqual(
            sum(entry["path"].endswith(".pine") for entry in tracked_library),
            21,
        )
        for strategy in tracked_strategies:
            with self.subTest(strategy=strategy["id"]):
                self.assertEqual(strategy["schema_version"], 2)
                self.assertIn(strategy["file"], strategy["source_files"])
                self.assertEqual(strategy["source_files"], sorted(set(strategy["source_files"])))
                for source in strategy["source_files"]:
                    self.assertNotIn("\\", source)
                    self.assertNotIn("..", Path(source).parts)
                    self.assertTrue((ROOT / source).is_file(), source)

        by_id = {strategy["id"]: strategy for strategy in tracked_strategies}
        self.assertIn("strategy_engine/accounting.py", by_id["moving-average"]["source_files"])
        self.assertIn("scripts/mnq/SND_baseline_backtest.py", by_id["snd"]["source_files"])

    def test_v2_rejects_missing_invalid_and_incomplete_source_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            strategies = root / "strategies"
            strategies.mkdir()
            (strategies / "helper.py").write_text("VALUE = 1\n", encoding="utf-8")
            adapter = strategies / "fixture.py"

            invalid = {
                "missing declaration": None,
                "missing file": ["strategies/fixture.py", "strategies/missing.py"],
                "parent escape": ["strategies/fixture.py", "../outside.py"],
                "absolute": ["strategies/fixture.py", "C:/outside.py"],
                "backslash": ["strategies/fixture.py", "strategies\\helper.py"],
                "adapter omitted": ["strategies/helper.py"],
            }
            for label, source_files in invalid.items():
                values = {} if source_files is None else {"source_files": source_files}
                if source_files is None:
                    text = strategy_literal(include_sources=False)
                else:
                    text = strategy_literal(**values)
                adapter.write_text(text, encoding="utf-8")
                with self.subTest(case=label), self.assertRaises(ValueError):
                    metadata(adapter, root)

            adapter.write_text(
                "from strategies.helper import VALUE\n" + strategy_literal(),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "missing local execution dependencies"):
                metadata(adapter, root)

    def test_protocol_v1_snapshot_without_source_files_is_normalized_in_memory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            strategies = root / "strategies"
            strategies.mkdir()
            (strategies / "helper.py").write_text("VALUE = 1\n", encoding="utf-8")
            adapter = strategies / "fixture.py"
            legacy = strategy_literal(include_sources=False, schema_version=1)
            adapter.write_text(
                "from strategies.helper import VALUE\n" + legacy,
                encoding="utf-8",
            )

            result = metadata(adapter, root)
            self.assertEqual(result["schema_version"], 2)
            self.assertEqual(
                result["source_files"],
                ["strategies/fixture.py", "strategies/helper.py"],
            )
            self.assertNotIn("source_files", ast.literal_eval(legacy.removeprefix("STRATEGY = ")))

    def test_library_has_move_stable_ids_and_readable_path_id_aliases(self):
        result = discover(ROOT)
        entries = result["library"]["entries"]
        source_ids = [entry["source_id"] for entry in entries]
        self.assertEqual(len(source_ids), len(set(source_ids)))
        for entry in entries:
            self.assertIn(entry["id"], entry["aliases"])
            self.assertIn(entry["path"], entry["path_aliases"])
            self.assertIs(find_entry(entries, entry["id"]), entry)
            self.assertIs(find_entry(entries, entry["source_id"]), entry)
            self.assertIs(find_entry(entries, entry["path"]), entry)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "config").mkdir()
            layout = json.loads(
                (ROOT / "config" / "workbench-layout.json").read_text(encoding="utf-8")
            )
            layout["source_roots"] = ["scripts", "research"]
            layout["discovery_paths"] = {
                "strategy_adapters": ["strategies"],
                "python_library": ["scripts", "research"],
                "pine_library": ["pine"],
            }
            layout["source_aliases"] = {
                "python:campaign.py": ["scripts/campaign.py"]
            }
            (root / "config" / "workbench-layout.json").write_text(
                json.dumps(layout), encoding="utf-8"
            )
            original = root / "scripts" / "campaign.py"
            original.parent.mkdir()
            original.write_text("def run():\n    pass\n", encoding="utf-8")
            first = inventory(root, [])["entries"][0]
            moved = root / "research" / original.name
            moved.parent.mkdir()
            original.rename(moved)
            second = inventory(root, [])["entries"][0]
            self.assertEqual(first["source_id"], second["source_id"])
            self.assertNotEqual(first["id"], second["id"])
            self.assertEqual(
                first["id"], hashlib.sha256(b"scripts/campaign.py").hexdigest()[:20]
            )
            self.assertIs(find_entry([second], first["id"]), second)
            self.assertIs(find_entry([second], "scripts/campaign.py"), second)


if __name__ == "__main__":
    unittest.main()
