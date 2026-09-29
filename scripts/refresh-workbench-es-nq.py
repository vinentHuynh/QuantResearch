"""Replay three frozen Workbench configurations on the September ES/NQ datasets.

This writes independent, checksum-verified report artifacts. It never registers
runs, changes the Workbench database, or rewrites the original evidence. The ES
overnight replay overlaps August 30-31 so its prior forced exit can be replaced
in a derived portfolio history without changing the frozen run.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "reports/combined-es-nq-refresh-2026-09-29/workbench"
RUNS = ROOT / "data/workbench/runs"
DATASETS = ROOT / "data/workbench/datasets"

SLEEVES = (
    {
        "name": "es-pine-overnight-block",
        "folder": "es-pine-overnight-block-aug28-overlap",
        "catalog_id": "72475d93c4667b888c79",
        "prior_run": "dd35c85a-8538-476d-94b3-14f9b8819536",
        "dataset_id": "1080435cff09b12010922b0eabec55edb424380a67a10c35eeff7c1955326161-v1",
        "replay_start": "2026-08-28",
        "extension_start": "2026-09-01",
        "end": "2026-09-29",
        "strategy_id": "pine-overnight-block",
    },
    {
        "name": "nq-pine-tsmom-orb",
        "catalog_id": "0c4b6e885c9223b5373f",
        "prior_run": "ae550398-6f1c-47fc-90fe-f503671982b4",
        "dataset_id": "3b9114199a2f6f0e51b70a63edc43de00940ae5df8d047b3aaa6aa8424aac9f1-v1",
        "replay_start": "2026-09-01",
        "extension_start": "2026-09-01",
        "end": "2026-09-28",
        "strategy_id": "pine-tsmom-orb",
    },
    {
        "name": "nq-short-term-reversal-minute",
        "catalog_id": "35b4fda895bf8ed0435c",
        "prior_run": "143882f0-4482-41f2-9548-a5fb7fe195db",
        "dataset_id": "3b9114199a2f6f0e51b70a63edc43de00940ae5df8d047b3aaa6aa8424aac9f1-v1",
        "replay_start": "2026-09-04",
        "extension_start": "2026-09-04",
        "end": "2026-09-28",
        "strategy_id": "short-term-reversal-minute",
    },
)


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def write_json(path: Path, value: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False), encoding="utf-8")
    temporary.replace(path)


def utc(value: object) -> pd.Timestamp:
    return pd.Timestamp(value).tz_convert("UTC")


def daily_marks(equity: pd.DataFrame, capital: float) -> dict[str, float]:
    times = pd.to_datetime(equity["timestamp"], utc=True)
    values = pd.Series(equity["equity"].to_numpy(dtype=float), index=times)
    closing = values.groupby(values.index.floor("D")).last()
    pnl = closing.diff()
    pnl.iloc[0] = closing.iloc[0] - capital
    return {day.strftime("%Y-%m-%d"): round(float(value), 8) for day, value in pnl.items()}


def normalized_trades(trades: pd.DataFrame, source_run: str) -> list[dict]:
    rows = []
    for trade in trades.to_dict("records"):
        quantity = abs(float(trade["quantity"]))
        cost = float(trade["cost"])
        pnl = float(trade["net_pnl"])
        if quantity <= 0 or not quantity.is_integer() or cost < 0 or not np.isfinite([quantity, cost, pnl]).all():
            raise ValueError("Invalid trade quantity, cost, or P&L")
        rows.append({
            "entry": utc(trade["entry_time"]).isoformat(),
            "exit": utc(trade["exit_time"]).isoformat(),
            "pnl": round(pnl, 8),
            "quantity": int(quantity),
            "cost": round(cost, 8),
            "exit_reason": str(trade["exit_reason"]),
            "synthetic_exit": str(trade["exit_reason"]).lower() == "end-of-test",
            "exit_provenance": "recorded",
            "source_run": source_run,
        })
    return rows


def verified_artifacts(folder: Path, request: dict) -> tuple[dict, pd.DataFrame, pd.DataFrame]:
    manifest_path = folder / "manifest.json"
    if not manifest_path.exists():
        raise ValueError(f"Missing published manifest: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest["run_id"] != request["id"]:
        raise ValueError("Manifest run ID does not match replay request")
    for artifact in manifest["artifacts"]:
        path = folder / artifact["name"]
        if digest(path) != artifact["checksum"]:
            raise ValueError(f"Artifact checksum mismatch: {path}")
    equity = pd.read_csv(folder / "equity.csv")
    trades = pd.read_csv(folder / "trades.csv")
    positions = pd.read_csv(folder / "positions.csv")
    counts = {item["name"]: item["rows"] for item in manifest["artifacts"]}
    if len(equity) != counts["equity.csv"] or len(trades) != counts["trades.csv"] or len(positions) != counts["positions.csv"]:
        raise ValueError("Artifact row count mismatch")
    net = float(manifest["metrics"]["net_pnl"])
    if not np.isclose(net, float(trades["net_pnl"].sum()), atol=1e-6):
        raise ValueError("Trade ledger does not reconcile with manifest")
    if not np.isclose(net, float(equity["equity"].iloc[-1]) - request["capital"], atol=1e-6):
        raise ValueError("Marked equity does not reconcile with manifest")
    if not np.isclose(net, float(equity["net_pnl"].sum()), atol=1e-6):
        raise ValueError("Daily bar P&L does not reconcile with manifest")
    return manifest, equity, trades


def replay(config: dict, output: Path) -> dict:
    folder = output / config.get("folder", config["name"])
    folder.mkdir(parents=True, exist_ok=True)
    original_path = RUNS / config["prior_run"] / "input.json"
    original = json.loads(original_path.read_text(encoding="utf-8"))
    dataset_path = DATASETS / config["dataset_id"] / "dataset.json"
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    if dataset["id"] != config["dataset_id"] or dataset["symbol"] != original["dataset"]["symbol"]:
        raise ValueError("Updated dataset identity or market differs from frozen input")
    if original["strategy"]["id"] != config["strategy_id"]:
        raise ValueError("Frozen strategy identity differs from expected sleeve")
    if dataset["last"][:10] < config["end"]:
        raise ValueError("Updated dataset does not cover the requested replay end")
    source = Path(original["source_dir"]) / original["strategy"]["file"]
    if digest(source) != original["strategy"]["file_hash"]:
        raise ValueError("Frozen strategy file checksum mismatch")
    if digest(Path(dataset["path"])) != dataset["checksum"]:
        raise ValueError("Updated dataset checksum mismatch")

    request = dict(original)
    request.update({
        "id": f"{config['name']}-{config['replay_start']}-to-{config['end']}",
        "dataset": dataset,
        "start": config["replay_start"],
        "end": config["end"],
        "stage": "Exploratory",
        "hypothesis": "Frozen-source historical extension of previously reviewed portfolio sleeve; dates were already observed.",
    })
    request.pop("research", None)
    request.pop("experiment_id", None)
    input_path = folder / "input.json"
    if input_path.exists() and json.loads(input_path.read_text(encoding="utf-8")) != request:
        raise ValueError(f"Existing replay input differs: {input_path}")
    if not input_path.exists():
        write_json(input_path, request)

    if not (folder / "manifest.json").exists():
        env = os.environ.copy()
        env.pop("WORKBENCH_SUPERVISOR_FILE", None)
        env.pop("WORKBENCH_SUPERVISOR_TOKEN", None)
        env["PYTHONPATH"] = str(original["source_dir"])
        command = [sys.executable, "-m", "workbench.worker", str(input_path)]
        print(f"Replaying {config['name']} using frozen source {original['source_hash'][:12]}", flush=True)
        process = subprocess.Popen(command, cwd=original["source_dir"], env=env,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, encoding="utf-8", errors="replace")
        with (folder / "process.log").open("w", encoding="utf-8") as log:
            assert process.stdout is not None
            for line in process.stdout:
                print(f"[{config['name']}] {line}", end="", flush=True)
                log.write(line)
        if process.wait() != 0:
            raise RuntimeError(f"Frozen worker failed for {config['name']}; see {folder / 'process.log'}")

    manifest, equity, trades = verified_artifacts(folder, request)
    normalized = normalized_trades(trades, request["id"])
    marks = daily_marks(equity, float(request["capital"]))
    start = config["extension_start"]
    extension_trades = [trade for trade in normalized if trade["exit"][:10] >= start]
    extension_daily = {day: pnl for day, pnl in marks.items() if start <= day <= config["end"]}
    if not extension_daily:
        raise ValueError("No marked observations in extension interval")
    if any(trade["synthetic_exit"] for trade in extension_trades):
        raise ValueError(f"Extension ends with a synthetic liquidation: {config['name']}")

    provenance = {
        "frozen_run_id": config["prior_run"],
        "frozen_input_sha256": digest(original_path),
        "frozen_source_hash": original["source_hash"],
        "frozen_strategy_file": original["strategy"]["file"],
        "frozen_strategy_file_sha256": original["strategy"]["file_hash"],
        "frozen_strategy_version": original["strategy"]["version"],
        "updated_dataset_id": dataset["id"],
        "updated_dataset_sha256": dataset["checksum"],
        "updated_data_last_bar": dataset["last"],
        "replay_input_sha256": digest(input_path),
        "replay_manifest_sha256": digest(folder / "manifest.json"),
    }
    notes = [
        "The original Workbench run, evaluation, and catalog history remain unchanged.",
        "The original source snapshot and execution environment were used; this is an already observed historical extension, not a new holdout.",
        "The full replay trade, equity, and position ledgers reconcile to the manifest and retain their checksums.",
    ]
    extension = {
        "version": 1,
        "catalog_id": config["catalog_id"],
        "strategy_id": config["strategy_id"],
        "symbol": dataset["symbol"],
        "start": start,
        "end": config["end"],
        "replay_start": config["replay_start"],
        "trades": extension_trades,
        "daily": extension_daily,
        "dataset_id": dataset["id"],
        "dataset_checksum": dataset["checksum"],
        "frozen_source": provenance,
        "validation_notes": notes,
        "replay_metrics": manifest["metrics"],
    }

    if config["name"] == "es-pine-overnight-block":
        old_trades = pd.read_csv(RUNS / config["prior_run"] / "trades.csv")
        old_equity = pd.read_csv(RUNS / config["prior_run"] / "equity.csv")
        old_marks = daily_marks(old_equity, float(original["capital"]))
        if not np.isclose(old_marks["2026-08-30"], marks["2026-08-30"], atol=1e-6):
            raise ValueError("August 30 overlap does not reproduce frozen daily P&L")
        old_normalized = normalized_trades(old_trades, config["prior_run"])
        old_aug30 = [t for t in old_normalized if t["exit"][:10] == "2026-08-31" and t["entry"][:10] == "2026-08-30"]
        new_aug30 = [t for t in normalized if t["exit"][:10] == "2026-08-31" and t["entry"][:10] == "2026-08-30"]
        if len(old_aug30) != 1 or len(new_aug30) != 1 or old_aug30 != [{**new_aug30[0], "source_run": config["prior_run"]}]:
            raise ValueError("August 30 overnight overlap trade does not reproduce frozen ledger")
        synthetic = [t for t in old_normalized if t["synthetic_exit"] and t["entry"][:10] == "2026-08-31"]
        bridge = [t for t in normalized if t["entry"][:10] == "2026-08-31" and t["exit"][:10] == "2026-09-01"]
        if len(synthetic) != 1 or len(bridge) != 1 or bridge[0] not in extension_trades:
            raise ValueError("Expected one old synthetic exit and one natural bridge trade")
        correction = {
            "date": "2026-08-31",
            "remove_trade": synthetic[0],
            "delta_pnl": round(marks["2026-08-31"] - old_marks["2026-08-31"], 8),
            "original_daily_pnl": old_marks["2026-08-31"],
            "corrected_daily_pnl": marks["2026-08-31"],
            "replacement_trade": bridge[0],
            "replacement_trade_already_in_extension": True,
            "verified_unchanged_overlap_daily": {"2026-08-30": marks["2026-08-30"]},
            "instruction": "In a derived portfolio history, remove only the specified old synthetic trade, replace the August 31 daily mark, then append extension trades and daily marks. Do not alter the original frozen run or catalog file.",
        }
        trade_change = sum(trade["pnl"] for trade in extension_trades) - synthetic[0]["pnl"]
        marked_change = sum(extension_daily.values()) + correction["delta_pnl"]
        if not np.isclose(trade_change, marked_change, atol=1e-6):
            raise ValueError("ES boundary correction does not reconcile trade and marked P&L")
        correction["reconciled_net_change"] = round(trade_change, 8)
        extension["boundary_correction"] = correction
        write_json(folder / "boundary_correction.json", correction)

    write_json(folder / "extension.json", extension)
    print(f"Validated {config['name']}: {len(extension_trades)} trades, {len(extension_daily)} UTC marks, {start}–{config['end']}", flush=True)
    return {
        "name": config["name"], "catalog_id": config["catalog_id"],
        "extension_file": str(folder / "extension.json"),
        "trades": len(extension_trades), "marked_days": len(extension_daily),
        "start": start, "end": config["end"],
        "replay_net_pnl": manifest["metrics"]["net_pnl"],
        "extension_daily_pnl": round(sum(extension_daily.values()), 8),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    results = [replay(config, output) for config in SLEEVES]
    write_json(output / "summary.json", {"version": 1, "sleeves": results})
    print(json.dumps(results, indent=2), flush=True)


if __name__ == "__main__":
    main()
