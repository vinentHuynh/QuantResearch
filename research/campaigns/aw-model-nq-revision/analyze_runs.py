"""Read-only, independent accounting audit for the frozen AW revision.

Run from anywhere with ``python analyze_runs.py``. Campaign inputs and generated
reports live in the raw artifact store, while this reusable implementation stays
in the tracked research tree. Workbench run inputs, logs and artifacts are read
only. Every declared variant is shown, including missing launches and failed
jobs.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
import hashlib
from itertools import zip_longest
import json
import math
from pathlib import Path
import re
import sqlite3
import statistics
import sys
from typing import Any
from zoneinfo import ZoneInfo


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))
from workbench.layout import load_layout


LAYOUT = load_layout(ROOT)
WORKBENCH_HOME = LAYOUT.state_root
ARTIFACTS_ROOT = LAYOUT.artifacts_root
CAMPAIGN_ROOT = ARTIFACTS_ROOT / "research" / "aw-model-nq-2026-09-29" / "revision"
RUNS_ROOT = WORKBENCH_HOME / "runs"
REGISTRY = WORKBENCH_HOME / "workbench.sqlite3"
CHICAGO = ZoneInfo("America/Chicago")
ARTIFACTS = ("trades.csv", "equity.csv", "signals.csv", "positions.csv", "process.log")
MONEY_EPS = 0.011
PRICE_EPS = 1e-7
DST_SUPERSESSION = ("Prior source used fixed elapsed-time 2H bins across DST, "
                    "excluding about 397 eligible development mornings; "
                    "its performance is superseded by the corrected-source rerun.")
STRICT_GUARD_SUPERSESSION = (
    "Second development source corrected DST but lacked two conservative guards: "
    "reject a next-open fill beyond its structural stop, and exclude an older "
    "2H FVG vote when an intervening candle is missing. It is superseded by "
    "the final pre-holdout strict-guard campaign.")
CALENDAR_SUPERSESSION = ("Prior source lacked the official September 2026 "
                         "NFP, CPI, and FOMC calendar extension; the frozen "
                         "holdout-source rerun supersedes it.")


def numeric(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def close(a: Any, b: Any, tolerance: float = MONEY_EPS) -> bool:
    left, right = numeric(a), numeric(b)
    return left is not None and right is not None and abs(left - right) <= tolerance


def parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return result if result.tzinfo is not None else None


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path, errors: list[str]) -> dict[str, Any] | None:
    try:
        content = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        errors.append(f"Could not read {path.name}: {exc}")
        return None
    if not isinstance(content, dict):
        errors.append(f"{path.name} is not a JSON object")
        return None
    return content


def read_csv(path: Path, required: set[str], errors: list[str]) -> list[dict[str, str]] | None:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            headers = list(reader.fieldnames or [])
            if not required.issubset(headers):
                errors.append(f"{path.name} lacks columns {sorted(required - set(headers))}")
                return None
            if len(headers) != len(set(headers)):
                errors.append(f"{path.name} has duplicate column names")
                return None
            return list(reader)
    except (OSError, UnicodeError, csv.Error) as exc:
        errors.append(f"Could not read {path.name}: {exc}")
        return None


def decode_registry_record(kind: str, record_id: str, raw: str) -> dict[str, Any]:
    """Read legacy records and validated protocol-v2 SQLite envelopes."""
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("record body is not an object")
    if (payload.get("schema_version") == 2
            and ("kind" in payload or "body" in payload)):
        if (set(payload) != {"schema_version", "kind", "id", "body"}
                or not isinstance(payload.get("kind"), str)
                or payload.get("kind") != kind
                or not isinstance(payload.get("id"), str)
                or payload.get("id") != record_id):
            raise ValueError("record envelope identity mismatch")
        value = payload.get("body")
        if not isinstance(value, dict):
            raise ValueError("record envelope value is not an object")
        return value
    return payload


def registry_runs(path: Path) -> dict[str, dict[str, Any]]:
    if not path.is_file():
        return {}
    with sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=5) as db:
        return {run_id: decode_registry_record("run", run_id, body) for run_id, body in
                db.execute("SELECT id, body FROM records WHERE kind='run'")}


def validate_manifest(folder: Path, manifest: dict[str, Any], errors: list[str]) -> dict[str, Any]:
    artifact_list = manifest.get("artifacts")
    if not isinstance(artifact_list, list):
        errors.append("Manifest artifacts is not a list")
        artifact_list = []
    checks: dict[str, Any] = {}
    names = [item.get("name") for item in artifact_list if isinstance(item, dict)]
    if len(names) != len(set(names)):
        errors.append("Manifest has duplicate artifact names")
    entries = {item.get("name"): item for item in artifact_list if isinstance(item, dict)}
    for name in ARTIFACTS:
        path = folder / name
        entry = entries.get(name)
        expected = entry.get("checksum") if isinstance(entry, dict) else None
        if not isinstance(expected, str) or len(expected) != 64:
            errors.append(f"Manifest lacks SHA-256 for {name}")
            checks[name] = {"match": False, "reason": "missing checksum"}
            continue
        if not path.is_file():
            errors.append(f"Missing {name}")
            checks[name] = {"match": False, "expected": expected, "reason": "missing file"}
            continue
        actual = sha256(path)
        match = actual == expected.lower()
        checks[name] = {"match": match, "expected": expected, "actual": actual}
        if not match:
            errors.append(f"SHA-256 mismatch for {name}")
    return checks


def log_records(path: Path, errors: list[str]) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    entries: list[dict[str, Any]] = []
    funnels: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8", errors="replace") as stream:
            for line_number, line in enumerate(stream, 1):
                for marker, sink in (("AW_ENTRY ", entries), ("AW_FUNNEL ", funnels)):
                    offset = line.find(marker)
                    if offset < 0:
                        continue
                    try:
                        value = json.loads(line[offset + len(marker):])
                    except json.JSONDecodeError:
                        errors.append(f"Malformed {marker.strip()} on process.log line {line_number}")
                        continue
                    if not isinstance(value, dict):
                        errors.append(f"Non-object {marker.strip()} on process.log line {line_number}")
                    else:
                        sink.append(value)
    except OSError as exc:
        errors.append(f"Could not read process.log: {exc}")
    if len(funnels) != 1:
        errors.append(f"Expected one AW_FUNNEL, found {len(funnels)}")
    return entries, funnels[0] if len(funnels) == 1 else None


def profit_factor(values: list[float]) -> float | None:
    gains = sum(value for value in values if value > 0)
    losses = -sum(value for value in values if value < 0)
    return gains / losses if losses else None


def audit_equity_and_positions(equity_path: Path, positions_path: Path,
                               capital: float, errors: list[str]) -> dict[str, Any] | None:
    """Stream the million-row marks and position series without retaining them."""
    peak = capital
    worst_cash = worst_fraction = 0.0
    worst_cash_peak = worst_cash_trough = capital
    worst_cash_peak_time = worst_cash_trough_time = None
    worst_fraction_peak = worst_fraction_trough = capital
    worst_fraction_peak_time = worst_fraction_trough_time = None
    peak_time = None
    previous: datetime | None = None
    first_stamp = last_stamp = None
    gross = costs = bar_net = 0.0
    final = final_contracts = None
    count = 0
    try:
        with equity_path.open("r", encoding="utf-8-sig", newline="") as eq_file, \
             positions_path.open("r", encoding="utf-8-sig", newline="") as pos_file:
            eq_reader, pos_reader = csv.DictReader(eq_file), csv.DictReader(pos_file)
            eq_headers, pos_headers = set(eq_reader.fieldnames or ()), set(pos_reader.fieldnames or ())
            eq_required = {"timestamp", "equity", "gross_pnl", "cost", "net_pnl"}
            pos_required = {"timestamp", "contracts", "intrabar_contracts", "turnover_contracts"}
            if not eq_required <= eq_headers or not pos_required <= pos_headers:
                errors.append("Equity or positions CSV lacks required columns")
                return None
            for index, (row, position) in enumerate(zip_longest(eq_reader, pos_reader), 2):
                if row is None or position is None:
                    errors.append("Equity and positions have different observation counts")
                    return None
                if row["timestamp"] != position["timestamp"]:
                    errors.append(f"Equity and positions timestamps differ at row {index}")
                    return None
                stamp = parse_time(row.get("timestamp"))
                equity = numeric(row.get("equity"))
                g, c, n = (numeric(row.get(name)) for name in ("gross_pnl", "cost", "net_pnl"))
                contracts = numeric(position.get("contracts"))
                if stamp is None or None in (equity, g, c, n, contracts):
                    errors.append(f"Invalid equity or positions row {index}")
                    return None
                if previous is not None and stamp <= previous:
                    errors.append(f"Equity times are not increasing at row {index}")
                    return None
                if not close(g - c, n, 1e-5):
                    errors.append(f"Gross/cost/net mismatch in equity.csv row {index}")
                    return None
                if first_stamp is None:
                    first_stamp = row["timestamp"]
                last_stamp = row["timestamp"]
                previous = stamp
                final, final_contracts = equity, contracts
                count += 1
                gross += g
                costs += c
                bar_net += n
                if equity > peak:
                    peak, peak_time = equity, row["timestamp"]
                cash_drawdown = equity - peak
                if cash_drawdown < worst_cash:
                    worst_cash = cash_drawdown
                    worst_cash_peak, worst_cash_trough = peak, equity
                    worst_cash_peak_time, worst_cash_trough_time = peak_time, row["timestamp"]
                if peak > 0:
                    fractional_drawdown = equity / peak - 1
                    if fractional_drawdown < worst_fraction:
                        worst_fraction = fractional_drawdown
                        worst_fraction_peak, worst_fraction_trough = peak, equity
                        worst_fraction_peak_time, worst_fraction_trough_time = peak_time, row["timestamp"]
    except (OSError, UnicodeError, csv.Error) as exc:
        errors.append(f"Could not stream equity/positions CSV: {exc}")
        return None
    if count == 0:
        errors.append("equity.csv is empty")
        return None
    if not close(final - capital, bar_net):
        errors.append("Final equity minus capital differs from summed bar net P&L")
    if not close(final_contracts, 0, 1e-9):
        errors.append("Final position is not flat")
    return {
        "observations": count, "first": first_stamp, "last": last_stamp,
        "final_equity": final, "net_pnl": final - capital,
        "gross_pnl": gross, "costs": costs,
        "max_marked_drawdown_usd": worst_cash,
        "max_marked_drawdown_fraction": worst_fraction,
        "max_marked_drawdown_usd_peak_equity": worst_cash_peak,
        "max_marked_drawdown_usd_trough_equity": worst_cash_trough,
        "max_marked_drawdown_usd_peak_time": worst_cash_peak_time,
        "max_marked_drawdown_usd_trough_time": worst_cash_trough_time,
        "max_marked_drawdown_fraction_peak_equity": worst_fraction_peak,
        "max_marked_drawdown_fraction_trough_equity": worst_fraction_trough,
        "max_marked_drawdown_fraction_peak_time": worst_fraction_peak_time,
        "max_marked_drawdown_fraction_trough_time": worst_fraction_trough_time,
    }


def audit_trades(rows: list[dict[str, str]], signals: list[dict[str, str]],
                 log_entries: list[dict[str, Any]], risk_budget: float,
                 errors: list[str]) -> dict[str, Any]:
    submissions: dict[str, list[dict[str, str]]] = defaultdict(list)
    fills: dict[str, list[dict[str, str]]] = defaultdict(list)
    closes: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in signals:
        order_id = row.get("order_id") or ""
        if row.get("event") == "submitted" and numeric(row.get("target")) not in (None, 0):
            submissions[order_id].append(row)
        elif row.get("event") == "filled":
            fills[order_id].append(row)
        elif row.get("event") == "closed":
            closes[order_id].append(row)
    logs: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in log_entries:
        logs[str(record.get("order_id") or "")].append(record)
    for order_id, records in logs.items():
        if not order_id or len(records) != 1:
            errors.append(f"AW_ENTRY has missing or duplicate order_id {order_id!r}")
            continue
        record = records[0]
        logged_side = numeric(record.get("side"))
        originals = [item for item in submissions.get(order_id, []) if
                     item.get("signal_id") == record.get("signal_id") and
                     close(item.get("original_stop"), record.get("stop"), PRICE_EPS) and
                     close(item.get("original_target"), record.get("target"), PRICE_EPS) and
                     logged_side in (-1, 1) and numeric(item.get("target")) is not None and
                     numeric(item.get("target")) * logged_side > 0]
        if len(originals) != 1:
            errors.append(f"AW_ENTRY {order_id} has {len(originals)} exact submitted signal rows")
    for order_id in submissions:
        if order_id not in logs:
            errors.append(f"Submitted order {order_id} lacks an AW_ENTRY log record")
    nets: list[float] = []
    rs: list[float] = []
    gross = costs = 0.0
    reasons: Counter[str] = Counter()
    years: dict[str, dict[str, float | int]] = defaultdict(lambda: {"trades": 0, "net_pnl": 0.0, "sum_net_r": 0.0})
    used_orders: set[str] = set()
    linked = 0
    matched_examples: list[dict[str, Any]] = []
    for index, row in enumerate(rows, 2):
        label = f"trades.csv row {index}"
        order_id = row.get("order_id") or ""
        signal_id = row.get("signal_id") or ""
        entry_time, exit_time = parse_time(row.get("entry_time")), parse_time(row.get("exit_time"))
        entry, exit_price, stop, target = (numeric(row.get(name)) for name in
                                           ("entry", "exit", "original_stop", "original_target"))
        quantity, point, risk = (numeric(row.get(name)) for name in
                                  ("quantity", "point_value", "initial_risk_cash"))
        net, trade_gross, trade_cost = (numeric(row.get(name)) for name in
                                        ("net_pnl", "gross_pnl", "cost"))
        nq, mnq = numeric(row.get("nq_contracts")), numeric(row.get("mnq_contracts"))
        if (not order_id or not signal_id or None in
            (entry_time, exit_time, entry, exit_price, stop, target, quantity, point,
             risk, net, trade_gross, trade_cost, nq, mnq)):
            errors.append(f"{label} has missing or invalid required trade fields")
            continue
        if order_id in used_orders:
            errors.append(f"Duplicate filled order_id {order_id}")
        used_orders.add(order_id)
        if exit_time < entry_time:
            errors.append(f"{label} exits before entry")
        if quantity == 0 or quantity != int(quantity) or point <= 0:
            errors.append(f"{label} has invalid position size or point value")
            continue
        if point != 2 or nq != int(nq) or mnq != int(mnq) or nq < 0 or mnq < 0 or 10 * nq + mnq != abs(quantity):
            errors.append(f"{label} NQ/MNQ mix does not reconcile to micro-equivalent quantity")
        signed = 1 if quantity > 0 else -1
        if signed * (entry - stop) <= 0 or signed * (target - entry) <= 0:
            errors.append(f"{label} original stop/target do not bracket entry")
        calculated_risk = abs(entry - stop) * abs(quantity) * point
        if not close(calculated_risk, risk, 1e-6) or risk <= 0:
            errors.append(f"{label} initial_risk_cash does not match fill and original stop")
        if risk > risk_budget + 1e-6:
            errors.append(f"{label} initial structural risk exceeds frozen ${risk_budget:g} cap")
        if not close(trade_gross - trade_cost, net):
            errors.append(f"{label} gross minus cost differs from net")
        if not close((exit_price - entry) * quantity * point, trade_gross):
            errors.append(f"{label} price movement and contract size do not reproduce gross P&L")
        fee, slip = numeric(row.get("fee_per_side")), numeric(row.get("slippage_ticks"))
        if fee is None or slip is None or fee < 0 or slip < 0:
            errors.append(f"{label} lacks valid commission/slippage economics")
        else:
            entry_market = not bool(row.get("requested_limit"))
            exit_market = row.get("exit_reason") != "limit"
            expected_cost = abs(quantity) * (2 * fee +
                    (int(entry_market) + int(exit_market)) * slip * 0.25 * point)
            if not close(expected_cost, trade_cost):
                errors.append(f"{label} cost differs from two-sided commission and charged market/stop slippage")
        submit = [item for item in submissions.get(order_id, []) if
                  item.get("signal_id") == signal_id and
                  close(item.get("original_stop"), stop, PRICE_EPS) and
                  close(item.get("original_target"), target, PRICE_EPS)]
        filled = [item for item in fills.get(order_id, []) if
                  item.get("signal_id") == signal_id and
                  close(item.get("fill_price"), entry, PRICE_EPS) and
                  close(item.get("original_stop"), stop, PRICE_EPS) and
                  close(item.get("original_target"), target, PRICE_EPS) and
                  parse_time(item.get("event_time")) == entry_time]
        closed = [item for item in closes.get(order_id, []) if
                  item.get("signal_id") == signal_id and
                  close(item.get("fill_price"), exit_price, PRICE_EPS) and
                  parse_time(item.get("event_time")) == exit_time]
        logged = [item for item in logs.get(order_id, []) if
                  item.get("signal_id") == signal_id and
                  close(item.get("stop"), stop, PRICE_EPS) and
                  close(item.get("target"), target, PRICE_EPS) and
                  numeric(item.get("side")) == signed]
        if len(submit) != 1 or len(filled) != 1 or len(closed) != 1 or len(logged) != 1:
            errors.append(f"{label} exact order/stop/target link: submitted={len(submit)}, filled={len(filled)}, closed={len(closed)}, AW_ENTRY={len(logged)}")
        else:
            linked += 1
            if len(matched_examples) < 5:
                matched_examples.append({"order_id": order_id, "signal_id": signal_id,
                                         "entry": entry, "original_stop": stop,
                                         "original_target": target, "risk_cash": risk})
        if row.get("requested_limit") and numeric(row.get("requested_limit")) is not None:
            if not close(entry, row["requested_limit"], PRICE_EPS):
                errors.append(f"{label} limit fill differs from requested limit")
        gross += trade_gross
        costs += trade_cost
        nets.append(net)
        if risk > 0:
            rs.append(net / risk)
        reasons[row.get("exit_reason") or "(blank)"] += 1
        year = str(entry_time.astimezone(CHICAGO).year)
        years[year]["trades"] += 1
        years[year]["net_pnl"] += net
        years[year]["sum_net_r"] += net / risk if risk > 0 else 0
    if len(fills) != len(used_orders):
        errors.append("Filled order IDs and closed trade IDs have different counts")
    for order_id in fills:
        if order_id not in used_orders:
            errors.append(f"Filled signal {order_id} has no completed trade")
    for order_id in closes:
        if order_id not in used_orders:
            errors.append(f"Closed signal {order_id} has no completed trade")
    return {
        "trade_count": len(rows), "audited_trade_count": len(nets), "linked_trade_count": linked,
        "submitted_entry_orders": len(submissions),
        "unfilled_or_rejected_entry_orders": len(set(submissions) - used_orders),
        "aw_entry_log_count": len(log_entries), "gross_pnl": gross, "costs": costs,
        "net_pnl": sum(nets), "profit_factor": profit_factor(nets),
        "win_rate": sum(value > 0 for value in nets) / len(nets) if nets else None,
        "mean_net_r": statistics.mean(rs) if rs else None,
        "median_net_r": statistics.median(rs) if rs else None,
        "sum_net_r": sum(rs) if rs else None,
        "net_r_profit_factor": profit_factor(rs),
        "exit_reason_counts": dict(sorted(reasons.items())),
        "yearly_by_chicago_entry": dict(sorted(years.items())),
        "matched_examples": matched_examples,
    }


def check_inputs(input_data: dict[str, Any], receipt: dict[str, Any],
                 plan: dict[str, Any], interval: dict[str, Any],
                 variant: dict[str, Any], errors: list[str]) -> None:
    run_id = receipt["run_id"]
    dataset = input_data.get("dataset") or {}
    strategy = input_data.get("strategy") or {}
    expected_parameters = {**plan["common_parameters"], **variant["parameters"]}
    fields = {
        "id": run_id, "start": interval["start"], "end": interval["end"],
        "timeframe": plan["timeframe"], "session": plan["session"],
        "capital": plan["capital"], "fee": variant["fee"],
        "slippage": variant["slippage"], "warmup_days": plan["warmup_days"],
        "stage": plan["stage"], "timeout": plan["timeout"],
        "delay_bars": plan["delay_bars"],
    }
    for name, expected in fields.items():
        actual = input_data.get(name)
        if (not close(actual, expected, 1e-8) if isinstance(expected, (int, float))
                else actual != expected):
            errors.append(f"Run input {name} differs from plan: {actual!r} vs {expected!r}")
    for name, expected in expected_parameters.items():
        actual = (input_data.get("parameters") or {}).get(name)
        if (not close(actual, expected, 1e-8) if isinstance(expected, (int, float)) and not isinstance(expected, bool)
                else actual != expected):
            errors.append(f"Run parameter {name} differs from frozen plan")
    if dataset.get("id") != plan["dataset_id"] or dataset.get("symbol") != "NQ":
        errors.append("Dataset identity differs from frozen NQ plan")
    if strategy.get("id") != plan["strategy_id"]:
        errors.append("Strategy identity differs from frozen plan")
    if receipt.get("source_hash") and input_data.get("source_hash") != receipt["source_hash"]:
        errors.append("Receipt source hash differs from run input")
    if receipt.get("strategy_file_hash") and strategy.get("file_hash") != receipt["strategy_file_hash"]:
        errors.append("Receipt strategy hash differs from run input")
    if receipt.get("dataset_id") and dataset.get("id") != receipt["dataset_id"]:
        errors.append("Receipt dataset ID differs from run input")


def analyze_attempt(receipt: dict[str, Any], plan: dict[str, Any],
                    interval: dict[str, Any], variant: dict[str, Any],
                    runs_root: Path, registry: dict[str, dict[str, Any]]) -> dict[str, Any]:
    run_id = receipt.get("run_id")
    result: dict[str, Any] = {"interval": interval["label"], "variant": variant["label"],
                              "run_id": run_id, "registry_status": None,
                              "audit_status": "pending", "errors": [], "warnings": [],
                              "receipt_source_hash": receipt.get("source_hash"),
                              "receipt_strategy_file_hash": receipt.get("strategy_file_hash"),
                              "campaign": receipt.get("campaign")}
    errors: list[str] = result["errors"]
    if not isinstance(run_id, str) or not run_id or Path(run_id).name != run_id:
        errors.append("Invalid run ID in receipt")
        result["audit_status"] = "invalid_receipt"
        return result
    registered = registry.get(run_id)
    state = registered.get("status") if registered else None
    result["registry_status"] = state
    if registered is None:
        result["warnings"].append("No Workbench registry record; state inferred from files only")
    folder = runs_root / run_id
    if not folder.is_dir():
        result["audit_status"] = "failed" if state == "Failed" else "pending"
        errors.append("Run folder missing")
        result["registry_error"] = registered.get("error") if registered else None
        return result
    input_data = load_json(folder / "input.json", errors)
    if input_data:
        check_inputs(input_data, receipt, plan, interval, variant, errors)
        result["source_hash"] = input_data.get("source_hash")
        result["strategy_file_hash"] = (input_data.get("strategy") or {}).get("file_hash")
        result["dataset_checksum"] = (input_data.get("dataset") or {}).get("checksum")
    if state in ("Queued", "Running"):
        result["audit_status"] = state.lower()
        result["errors"] = [item for item in errors if not item.startswith("Could not read manifest")]
        return result
    if state == "Failed":
        result["audit_status"] = "failed"
        result["registry_error"] = registered.get("error")
        result["warnings"].append("Failed runs are retained; partial artifacts are not performance evidence")
        return result
    manifest = load_json(folder / "manifest.json", errors)
    if manifest is None:
        result["audit_status"] = "pending_or_unverified" if state is None else "incomplete"
        return result
    if manifest.get("run_id") != run_id:
        errors.append("Manifest run ID differs from receipt")
    if registered and state == "Succeeded" and registered.get("result") != manifest:
        errors.append("Published manifest differs from Workbench registry result")
    checks = validate_manifest(folder, manifest, errors)
    result["artifact_checks"] = checks
    if not all(item.get("match") for item in checks.values()):
        result["audit_status"] = "invalid"
        return result
    required_trades = {"entry_time", "exit_time", "quantity", "entry", "exit",
                       "gross_pnl", "cost", "net_pnl", "exit_reason", "signal_id", "order_id",
                       "original_stop", "original_target", "point_value", "initial_risk_cash",
                       "nq_contracts", "mnq_contracts"}
    trades = read_csv(folder / "trades.csv", required_trades, errors)
    signals = read_csv(folder / "signals.csv", {"event_time", "event", "signal_id", "order_id",
                                                      "target", "original_stop", "original_target", "fill_price"}, errors)
    if trades is None or signals is None:
        result["audit_status"] = "invalid"
        return result
    artifact_rows = {item["name"]: item.get("rows") for item in manifest.get("artifacts", [])
                     if isinstance(item, dict) and item.get("name") in ARTIFACTS}
    for name, rows in (("trades.csv", trades), ("signals.csv", signals)):
        if artifact_rows.get(name) != len(rows):
            errors.append(f"Manifest row count differs from {name}")
    log_entries, funnel = log_records(folder / "process.log", errors)
    capital = numeric(input_data.get("capital")) if input_data else None
    if capital is None:
        errors.append("Run capital unavailable")
        result["audit_status"] = "invalid"
        return result
    eq = audit_equity_and_positions(folder / "equity.csv", folder / "positions.csv", capital, errors)
    if eq:
        for name in ("equity.csv", "positions.csv"):
            if artifact_rows.get(name) != eq["observations"]:
                errors.append(f"Manifest row count differs from {name}")
    tr = audit_trades(trades, signals, log_entries, float(plan["common_parameters"]["risk_budget"]), errors)
    result.update({"equity": eq, "trades": tr, "funnel": funnel,
                   "funnel_scope": "warmup_and_scored_bars",
                   "signal_event_counts": dict(sorted(Counter(row["event"] for row in signals).items())),
                   "manifest_metrics": {name: (manifest.get("metrics") or {}).get(name) for name in
                                        ("net_pnl", "trades", "costs", "observations", "max_drawdown")},
                   "manifest_warnings": manifest.get("warnings", [])})
    if eq:
        for label, a, b in (("Trade vs equity net P&L", tr["net_pnl"], eq["net_pnl"]),
                            ("Trade vs equity gross P&L", tr["gross_pnl"], eq["gross_pnl"]),
                            ("Trade vs equity costs", tr["costs"], eq["costs"])):
            if not close(a, b):
                errors.append(f"{label} does not reconcile")
        metrics = manifest.get("metrics") or {}
        for name, own in (("net_pnl", tr["net_pnl"]), ("trades", tr["trade_count"]),
                          ("costs", tr["costs"]), ("observations", eq["observations"])):
            if not close(metrics.get(name), own):
                errors.append(f"Manifest {name} differs from independent calculation")
        if not close(metrics.get("max_drawdown"), eq["max_marked_drawdown_fraction"], 1e-7):
            errors.append("Manifest max_drawdown differs from independent equity calculation")
    if state not in ("Succeeded", None):
        result["warnings"].append(f"Workbench registry still reports {state}")
    result["audit_status"] = "invalid" if errors else "verified"
    return result


def classify_attempts(receipts: list[dict[str, Any]],
                      attempts: list[dict[str, Any]],
                      primary_hash: str | None,
                      supersession_reason: str = DST_SUPERSESSION,
                      reasons_by_hash: dict[str, str] | None = None) -> str | None:
    """Select only the latest run of the interval's explicitly frozen source."""
    eligible = [index for index, receipt in enumerate(receipts)
                if primary_hash and receipt.get("source_hash") == primary_hash]
    def chronology(index: int) -> tuple[datetime, int]:
        stamp = parse_time(receipts[index].get("created_at"))
        return (stamp or datetime.min.replace(tzinfo=timezone.utc), index)
    primary_index = max(eligible, key=chronology) if eligible else None
    primary_run_id = attempts[primary_index].get("run_id") if primary_index is not None else None
    for index, (receipt, attempt) in enumerate(zip(receipts, attempts)):
        source_hash = receipt.get("source_hash")
        attempt["attempt_number_for_variant"] = index + 1
        attempt["selection"] = "primary" if index == primary_index else "superseded"
        if index == primary_index:
            attempt["superseded_reason"] = None
        elif receipt.get("superseded_reason"):
            attempt["superseded_reason"] = receipt["superseded_reason"]
        elif primary_hash and source_hash == primary_hash:
            attempt["superseded_reason"] = (
                f"Earlier frozen-source attempt; later attempt {primary_run_id} is primary.")
        elif primary_hash and source_hash != primary_hash:
            attempt["superseded_reason"] = (reasons_by_hash or {}).get(source_hash, supersession_reason)
        else:
            attempt["selection"] = "awaiting_primary_source_declaration"
            attempt["superseded_reason"] = (
                "The interval's primary source hash and rerun are pending.")
    return primary_run_id


def fmt_cash(value: Any) -> str:
    amount = numeric(value)
    if amount is None:
        return "—"
    return f"−${abs(amount):,.2f}" if amount < 0 else f"${amount:,.2f}"


def fmt_float(value: Any) -> str:
    amount = numeric(value)
    return f"{amount:.3f}" if amount is not None else "—"


def report_markdown(out: dict[str, Any]) -> str:
    lines = ["# AW Reversal NQ revised run audit", "",
             "All frozen variants and every launch attempt are shown. Development was previously inspected; the reserved years are historical, not prospective validation. Values are independently reconstructed from checksummed Workbench artifacts. A dash means undefined or unavailable. AW_FUNNEL counters include pre-start warmup and are diagnostic, not scored-period candidate frequencies.", ""]
    corrected_hash = out.get("corrected_source_hash")
    holdout_hash = out.get("holdout_source_hash")
    lines += [f"Development primary source: `{corrected_hash}`." if corrected_hash else
              "**Development primary source hash pending.**",
              f"Holdout primary source: `{holdout_hash}`." if holdout_hash else
              "**Calendar-extended holdout source hash pending.**",
              f"Final revised strategy file hash: `{out.get('corrected_strategy_file_hash') or 'pending'}`.",
              "Development attempts from the initial DST-shifted campaign and the second DST-corrected campaign are both superseded by the strict-guard v3 snapshot. Only the latest attempt matching its interval's declared source hash is primary. Every earlier attempt remains in the history. The final revised strategy file hash must agree between development and holdout campaigns.", ""]
    if out.get("campaign_warnings"):
        lines += ["Campaign notes:", "", *[f"- {warning}" for warning in out["campaign_warnings"]], ""]
    for interval in out["intervals"]:
        lines += [f"## {interval['label']}", "",
                  f"Declared primary source: `{interval.get('primary_source_hash') or 'pending'}`.", "",
                  "### Primary frozen-source comparison", "",
                  "| Variant | Run ID | Audit status | Trades | Net | Mean net R | PF | Peak-to-trough marked DD | Costs | Signal links |",
                  "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
        for item in interval["variants"]:
            run = next((attempt for attempt in item["attempts"]
                        if attempt.get("run_id") == item.get("primary_run_id")), None)
            tr = run.get("trades") if run else None
            eq = run.get("equity") if run else None
            tr, eq = tr or {}, eq or {}
            links = (f"{tr.get('linked_trade_count', 0)}/{tr.get('trade_count', 0)}" if tr else "—")
            status = run["audit_status"] if run else "awaiting frozen-source run"
            lines.append(f"| {item['label']} | {run.get('run_id') if run else '—'} | {status} | "
                         f"{tr.get('trade_count', '—')} | {fmt_cash(tr.get('net_pnl'))} | "
                         f"{fmt_float(tr.get('mean_net_r'))} | {fmt_float(tr.get('profit_factor'))} | "
                         f"{fmt_cash(eq.get('max_marked_drawdown_usd'))} | "
                         f"{fmt_cash(tr.get('costs'))} | {links} |")
        lines += ["", "### Complete attempt history", "",
                  "| Variant | Attempt | Run ID | Source hash | Selection | Audit status | Trades | Net | Mean net R | Peak-to-trough marked DD | Reason |",
                  "| --- | ---: | --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- |"]
        for item in interval["variants"]:
            for run in item["attempts"]:
                tr, eq = run.get("trades") or {}, run.get("equity") or {}
                source_hash = run.get("receipt_source_hash") or "unavailable"
                reason = run.get("superseded_reason") or "—"
                lines.append(f"| {item['label']} | {run.get('attempt_number_for_variant', '—')} | "
                             f"{run.get('run_id') or '—'} | `{source_hash[:12]}` | "
                             f"{run.get('selection', 'unclassified')} | {run['audit_status']} | "
                             f"{tr.get('trade_count', '—')} | {fmt_cash(tr.get('net_pnl'))} | "
                             f"{fmt_float(tr.get('mean_net_r'))} | "
                             f"{fmt_cash(eq.get('max_marked_drawdown_usd'))} | {reason} |")
        if not any(item["attempts"] for item in interval["variants"]):
            lines.append("| — | — | — | — | — | not launched | — | — | — | — | — |")
        lines.append("")
    lines += ["## Audit details", "",
              "Profit factor is undefined when no losses occur or no trades occur. Marked drawdown is the drop from the preceding marked equity peak, including unrealized profit giveback; its percentage uses that peak as the denominator. It is not loss from entry or initial stop risk. Net R uses each fill's actual initial structural risk. NQ/MNQ sizing is the declared NQ-price micro-equivalent proxy.", ""]
    for interval in out["intervals"]:
        for item in interval["variants"]:
            for run in item["attempts"]:
                if run["audit_status"] == "not_launched":
                    continue
                tr = run.get("trades") or {}
                lines += [f"### {interval['label']} / {item['label']} / {run.get('run_id', 'no ID')}", "",
                          f"Selection: **{run.get('selection', 'unclassified')}**; audit: **{run['audit_status']}**; Workbench: {run.get('registry_status') or 'unavailable'}.",
                          f"Source hash: `{run.get('receipt_source_hash') or 'unavailable'}`; strategy file hash: `{run.get('receipt_strategy_file_hash') or 'unavailable'}`; campaign: {run.get('campaign') or 'unlabeled'}.", ""]
                if run.get("superseded_reason"):
                    lines += [f"Supersession: {run['superseded_reason']}", ""]
                if tr:
                    lines += [f"Gross {fmt_cash(tr.get('gross_pnl'))}; costs {fmt_cash(tr.get('costs'))}; net {fmt_cash(tr.get('net_pnl'))}. "
                              f"Mean / sum net R {fmt_float(tr.get('mean_net_r'))} / {fmt_float(tr.get('sum_net_r'))}. "
                              f"Signal links {tr.get('linked_trade_count', 0)}/{tr.get('trade_count', 0)}; "
                              f"submitted orders without fills {tr.get('unfilled_or_rejected_entry_orders', 0)}.", ""]
                    reasons = tr.get("exit_reason_counts") or {}
                    lines += ["Exit reasons: " + (", ".join(f"{key} {count}" for key, count in reasons.items()) or "none") + ".", ""]
                    for year, summary in (tr.get("yearly_by_chicago_entry") or {}).items():
                        lines += [f"- {year} Chicago entry year: {summary['trades']} trades, {fmt_cash(summary['net_pnl'])}, sum net R {fmt_float(summary['sum_net_r'])}"]
                    if tr.get("yearly_by_chicago_entry"):
                        lines.append("")
                eq = run.get("equity") or {}
                if eq:
                    lines += [f"Max marked peak-to-trough drawdown {fmt_cash(eq.get('max_marked_drawdown_usd'))} "
                              f"({fmt_float(100 * eq['max_marked_drawdown_fraction'])}% of prior peak): "
                              f"{fmt_cash(eq.get('max_marked_drawdown_usd_peak_equity'))} at "
                              f"{eq.get('max_marked_drawdown_usd_peak_time')} to "
                              f"{fmt_cash(eq.get('max_marked_drawdown_usd_trough_equity'))} at "
                              f"{eq.get('max_marked_drawdown_usd_trough_time')}.", ""]
                if run.get("funnel") is not None:
                    lines += ["Funnel: " + ", ".join(f"{key}={value}" for key, value in sorted(run["funnel"].items())) + ".", ""]
                if run.get("registry_error"):
                    lines += [f"Workbench error: {run['registry_error']}", ""]
                if run["errors"]:
                    lines += ["Audit errors:", "", *[f"- {error}" for error in run["errors"]], ""]
                if run["warnings"]:
                    lines += ["Audit notes:", "", *[f"- {warning}" for warning in run["warnings"]], ""]
    return "\n".join(lines).rstrip() + "\n"


def numeric_report_markdown(out: dict[str, Any]) -> str:
    """Final report's numerical sections; interpretation is written separately."""
    lines = ["# AW Reversal NQ: audited backtest numbers", "",
             "The tables below include every frozen variant in each declared period. The 2022–August 2026 interval was already inspected and is development evidence. September 2026 and 2020–21 are historical holdouts, not prospective live results.", "",
             "## Frozen run identities", "",
             f"- Final development source: `{out.get('corrected_source_hash') or 'pending'}`",
             f"- Holdout source: `{out.get('holdout_source_hash') or 'pending'}`",
             f"- Initial superseded source: `{out.get('superseded_source_hash') or 'pending'}`",
             f"- DST-corrected superseded source: `{out.get('dst_corrected_source_hash') or 'pending'}`",
             f"- Final strategy file: `{out.get('corrected_strategy_file_hash') or 'pending'}`",
             f"- Source hashes retained across all attempts: {len(out.get('source_hashes') or [])}",
             "- Planned initial structural risk: $500 per trade. Net R divides each trade's net P&L by its actual initial structural risk.",
             "- Profit factor is undefined without losing trades. Peak-to-trough marked drawdown includes open P&L and is shown as a negative dollar change.", ""]
    for interval in out["intervals"]:
        lines += [f"## {interval['label']}: primary campaign", "",
                  f"Primary source: `{interval.get('primary_source_hash') or 'pending'}`.", "",
                  "| Variant | Run | Audit | Trades | Gross | Costs | Net | PF | Mean net R | Sum net R | Peak-to-trough marked DD | Linked fills |",
                  "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
        for item in interval["variants"]:
            run = next((a for a in item["attempts"] if a.get("run_id") == item.get("primary_run_id")), None)
            tr, eq = (run.get("trades") or {}, run.get("equity") or {}) if run else ({}, {})
            links = f"{tr.get('linked_trade_count', 0)}/{tr.get('trade_count', 0)}" if tr else "—"
            lines.append(f"| {item['label']} | {run.get('run_id') if run else '—'} | "
                         f"{run['audit_status'] if run else 'not launched'} | {tr.get('trade_count', '—')} | "
                         f"{fmt_cash(tr.get('gross_pnl'))} | {fmt_cash(tr.get('costs'))} | "
                         f"{fmt_cash(tr.get('net_pnl'))} | {fmt_float(tr.get('profit_factor'))} | "
                         f"{fmt_float(tr.get('mean_net_r'))} | {fmt_float(tr.get('sum_net_r'))} | "
                         f"{fmt_cash(eq.get('max_marked_drawdown_usd'))} | {links} |")
        lines += ["", "### Signal funnel (warmup inclusive)", "",
                  "Workbench calls the strategy during pre-start warmup, so these counters cover warmup and scored bars together. They are diagnostic counts, not scored-period candidate frequencies.", "",
                  "| Variant | Prepared days | Neckline sweeps | Strong MSS | Strict FVG | Reward gate rejects | Submitted | Filled |",
                  "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
        for item in interval["variants"]:
            run = next((a for a in item["attempts"] if a.get("run_id") == item.get("primary_run_id")), None)
            funnel = run.get("funnel") if run else None
            values = [str(funnel.get(key, 0)) if funnel is not None else "—" for key in
                      ("prepared_days", "neckline_sweeps", "strong_mss", "confirmed_gap",
                       "reward_gate_rejections", "submitted_entries", "filled_entries")]
            lines.append(f"| {item['label']} | " + " | ".join(values) + " |")
        lines.append("")
    lines += ["## Complete attempt history", "",
              "The first campaign's DST-shifted 2H clock and the second campaign's two missing conservative guards make their development results superseded. All results remain below, including failed, zero-trade, and incomplete attempts.", "",
              "| Period | Variant | Attempt | Campaign | Selection | Run ID | Source hash | Audit | Trades | Net | Mean net R | Superseded reason |",
              "| --- | --- | ---: | --- | --- | --- | --- | --- | ---: | ---: | ---: | --- |"]
    for interval in out["intervals"]:
        for item in interval["variants"]:
            for run in item["attempts"]:
                tr = run.get("trades") or {}
                lines.append(f"| {interval['label']} | {item['label']} | "
                             f"{run.get('attempt_number_for_variant', '—')} | {run.get('campaign') or 'initial'} | "
                             f"{run.get('selection', 'unclassified')} | {run.get('run_id') or '—'} | "
                             f"`{(run.get('receipt_source_hash') or 'unavailable')[:12]}` | "
                             f"{run['audit_status']} | {tr.get('trade_count', '—')} | "
                             f"{fmt_cash(tr.get('net_pnl'))} | {fmt_float(tr.get('mean_net_r'))} | "
                             f"{run.get('superseded_reason') or '—'} |")
    attempted = [run for interval in out["intervals"] for item in interval["variants"]
                 for run in item["attempts"]]
    verified = [run for run in attempted if run["audit_status"] == "verified"]
    primary = [run for run in attempted if run.get("selection") == "primary"]
    primary_verified = sum(run["audit_status"] == "verified" for run in primary)
    all_hashes = sum(all((run.get("artifact_checks") or {}).get(name, {}).get("match") is True
                         for name in ARTIFACTS) for run in verified)
    linked = sum((run.get("trades") or {}).get("linked_trade_count", 0) for run in verified)
    trade_count = sum((run.get("trades") or {}).get("trade_count", 0) for run in verified)
    status_counts = Counter(run["audit_status"] for run in attempted)
    lines += ["", "## Integrity and accounting", "",
              f"- Launch attempts retained: {len(attempted)}; audit statuses: " +
              ", ".join(f"{name} {count}" for name, count in sorted(status_counts.items())) + ".",
              f"- Primary runs independently verified: {primary_verified}/{len(primary)}.",
              f"- Verified runs with matching SHA-256 for trades.csv, equity.csv, signals.csv, positions.csv, and process.log: {all_hashes}/{len(verified)}.",
              f"- Exact submitted/fill/close/AW_ENTRY-to-trade links among verified runs: {linked}/{trade_count} trades.",
              "- Each verified run also reconciles trade gross, costs, net P&L, actual initial risk, marked equity, and published manifest metrics.",
              f"- Plan errors: {len(out.get('plan_errors') or [])}. " +
              ("; ".join(out['plan_errors']) if out.get('plan_errors') else "None."), "",
              "See [the frozen protocol](PROTOCOL.md), [run plan](RUN_PLAN.json), [launch receipts](LAUNCH_RECEIPTS.json), [complete machine-readable audit](RESULTS.json), and [detailed attempt ledger](REPORT_DRAFT.md).", ""]
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-root", type=Path, default=RUNS_ROOT)
    parser.add_argument("--registry", type=Path, default=REGISTRY)
    parser.add_argument(
        "--campaign-dir",
        type=Path,
        default=CAMPAIGN_ROOT,
        help="Directory containing RUN_PLAN.json and LAUNCH_RECEIPTS.json",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Report destination (defaults to --campaign-dir)",
    )
    parser.add_argument("--write-numeric-report", action="store_true",
                        help="Write REPORT.md numerical sections after every primary run is terminal")
    args = parser.parse_args()
    runs_root = args.runs_root.resolve()
    campaign_dir = args.campaign_dir.resolve()
    output_dir = (args.output_dir or campaign_dir).resolve()
    if output_dir == runs_root or runs_root in output_dir.parents:
        parser.error("Reports must be written outside the Workbench runs tree")
    errors: list[str] = []
    plan_path = campaign_dir / "RUN_PLAN.json"
    receipts_path = campaign_dir / "LAUNCH_RECEIPTS.json"
    plan = load_json(plan_path, errors)
    receipts = load_json(receipts_path, errors)
    if plan is None or receipts is None:
        parser.error("; ".join(errors))
    registry = registry_runs(args.registry)
    receipt_list = receipts.get("attempts")
    if not isinstance(receipt_list, list):
        parser.error("LAUNCH_RECEIPTS.json attempts is not a list")
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    interval_names = {item["label"] for item in plan["intervals_in_order"]}
    variant_names = {item["label"] for item in plan["variants_in_order"]}
    for item in receipt_list:
        if not isinstance(item, dict):
            errors.append("Non-object launch receipt")
            continue
        key = (item.get("interval"), item.get("variant"))
        if key[0] not in interval_names or key[1] not in variant_names:
            errors.append(f"Receipt for undeclared combination {key!r}")
            continue
        grouped[key].append(item)
    source_hashes = sorted({item.get("source_hash") for item in receipt_list
                            if isinstance(item, dict) and isinstance(item.get("source_hash"), str)})
    strategy_hashes = sorted({item.get("strategy_file_hash") for item in receipt_list
                              if isinstance(item, dict) and isinstance(item.get("strategy_file_hash"), str)})
    run_ids = [item.get("run_id") for item in receipt_list if isinstance(item, dict)]
    if len(run_ids) != len(set(run_ids)):
        errors.append("A run ID appears more than once in launch receipts")
    frozen_hashes: dict[str, str | None] = {}
    for field in ("superseded_source_hash", "dst_corrected_source_hash",
                  "corrected_source_hash", "holdout_source_hash",
                  "dst_corrected_strategy_file_hash", "corrected_strategy_file_hash"):
        value = plan.get(field)
        if value is not None and (not isinstance(value, str) or
                                  not re.fullmatch(r"[0-9a-fA-F]{64}", value)):
            errors.append(f"RUN_PLAN.json {field} must be a 64-character SHA-256 hex string")
            value = None
        frozen_hashes[field] = value.lower() if value else None
    corrected_hash = frozen_hashes["corrected_source_hash"]
    holdout_hash = frozen_hashes["holdout_source_hash"]
    old_hash = frozen_hashes["superseded_source_hash"]
    dst_hash = frozen_hashes["dst_corrected_source_hash"]
    final_strategy_hash = frozen_hashes["corrected_strategy_file_hash"]
    dst_strategy_hash = frozen_hashes["dst_corrected_strategy_file_hash"]
    declared_dev_hashes = [value for value in (old_hash, dst_hash, corrected_hash) if value]
    if len(declared_dev_hashes) != len(set(declared_dev_hashes)):
        errors.append("Declared development campaign source hashes are not distinct")
    for source_hash, strategy_hash, campaign_name in (
            (dst_hash, dst_strategy_hash, "DST-corrected v2"),
            (corrected_hash, final_strategy_hash, "strict-guard v3")):
        if not source_hash or not strategy_hash:
            continue
        for item in receipt_list:
            if (isinstance(item, dict) and item.get("source_hash") == source_hash and
                    item.get("strategy_file_hash") != strategy_hash):
                errors.append(f"{campaign_name} receipt {item.get('run_id')} strategy file hash differs from plan")
    campaign_warnings: list[str] = []
    if corrected_hash is None:
        campaign_warnings.append("Corrected development source hash is not yet declared")
    elif corrected_hash not in source_hashes:
        campaign_warnings.append("Declared corrected development source has no launch receipt yet")
    if holdout_hash is None:
        campaign_warnings.append("Calendar-extended holdout source hash is not yet declared")
    elif holdout_hash not in source_hashes:
        campaign_warnings.append("Declared holdout source has no launch receipt yet")
    if len(source_hashes) > 1:
        campaign_warnings.append("Multiple source hashes are retained intentionally; each attempt remains separately audited")
    active_hashes = {value for value in (corrected_hash, holdout_hash) if value}
    active_strategy_hashes = sorted({item.get("strategy_file_hash") for item in receipt_list
                                     if isinstance(item, dict) and item.get("source_hash") in active_hashes
                                     and isinstance(item.get("strategy_file_hash"), str)})
    if len(active_strategy_hashes) > 1:
        errors.append("Corrected development and calendar-extended holdout campaigns use different strategy file hashes")
    if final_strategy_hash and any(value != final_strategy_hash for value in active_strategy_hashes):
        errors.append("Final campaign strategy file hash differs from RUN_PLAN.json corrected_strategy_file_hash")
    output: dict[str, Any] = {
        "plan": str(plan_path), "receipts": str(receipts_path),
        "runs_root": str(runs_root), "audit_generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_hashes": source_hashes, "strategy_file_hashes": strategy_hashes,
        "corrected_source_hash": corrected_hash, "holdout_source_hash": holdout_hash,
        "superseded_source_hash": old_hash, "dst_corrected_source_hash": dst_hash,
        "corrected_strategy_file_hash": final_strategy_hash,
        "active_strategy_file_hashes": active_strategy_hashes,
        "campaign_warnings": campaign_warnings,
        "plan_errors": errors, "intervals": [],
    }
    for interval in plan["intervals_in_order"]:
        is_development = interval["label"] == "inspected_development"
        primary_hash = corrected_hash if is_development else holdout_hash
        supersession_reason = DST_SUPERSESSION if is_development else CALENDAR_SUPERSESSION
        reasons_by_hash = ({old_hash: DST_SUPERSESSION, dst_hash: STRICT_GUARD_SUPERSESSION}
                           if is_development else {})
        variants = []
        for variant in plan["variants_in_order"]:
            selected_receipts = grouped[(interval["label"], variant["label"])]
            attempts = [analyze_attempt(receipt, plan, interval, variant, runs_root, registry)
                        for receipt in selected_receipts]
            primary_run_id = classify_attempts(selected_receipts, attempts, primary_hash,
                                               supersession_reason, reasons_by_hash)
            variants.append({"label": variant["label"], "primary_run_id": primary_run_id,
                             "attempts": attempts})
        output["intervals"].append({"label": interval["label"], "evidence": interval.get("evidence"),
                                     "primary_source_hash": primary_hash, "variants": variants})
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "RESULTS.json").write_text(json.dumps(output, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    (output_dir / "REPORT_DRAFT.md").write_text(report_markdown(output), encoding="utf-8")
    if args.write_numeric_report:
        primary = [next((attempt for attempt in item["attempts"]
                         if attempt.get("run_id") == item.get("primary_run_id")), None)
                   for interval in output["intervals"] for item in interval["variants"]]
        if any(run is None or run["audit_status"] in
               ("pending", "queued", "running", "pending_or_unverified", "incomplete")
               for run in primary):
            parser.error("Cannot write final numerical report until all primary runs are terminal")
        report_path = output_dir / "REPORT.md"
        if report_path.exists():
            parser.error("REPORT.md already exists; preserve its interpretation and edit it explicitly")
        report_path.write_text(numeric_report_markdown(output), encoding="utf-8")
    summary = Counter(run["audit_status"] for interval in output["intervals"]
                      for variant in interval["variants"] for run in variant["attempts"])
    print(f"Audited {sum(summary.values())} launched attempts: {dict(summary)}")
    print(f"Wrote {output_dir / 'RESULTS.json'} and {output_dir / 'REPORT_DRAFT.md'}")
    return 1 if errors or summary.get("invalid", 0) else 0


if __name__ == "__main__":
    raise SystemExit(main())
