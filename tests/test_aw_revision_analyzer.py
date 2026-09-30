"""Focused checks for the independent AW revision artifact audit."""

from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest


SCRIPT = (Path(__file__).resolve().parents[1] / "research" / "campaigns" /
          "aw-model-nq-revision" / "analyze_runs.py")
SPEC = importlib.util.spec_from_file_location("aw_revision_analyzer", SCRIPT)
assert SPEC and SPEC.loader
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def test_manifest_checksum_includes_signal_and_process_log(tmp_path: Path) -> None:
    for name in AUDIT.ARTIFACTS:
        (tmp_path / name).write_text(name, encoding="utf-8")
    manifest = {"artifacts": [{"name": name, "checksum": AUDIT.sha256(tmp_path / name)}
                              for name in AUDIT.ARTIFACTS]}
    errors: list[str] = []
    checks = AUDIT.validate_manifest(tmp_path, manifest, errors)
    assert not errors
    assert all(item["match"] for item in checks.values())
    (tmp_path / "process.log").write_text("altered", encoding="utf-8")
    errors = []
    checks = AUDIT.validate_manifest(tmp_path, manifest, errors)
    assert checks["process.log"]["match"] is False
    assert any("process.log" in error for error in errors)


def test_exact_signal_link_risk_and_costs() -> None:
    trade = {
        "entry_time": "2022-05-10T10:03:00-04:00", "exit_time": "2022-05-10T13:42:00-04:00",
        "quantity": "-3", "entry": "12470.5", "exit": "12468.5",
        "original_stop": "12547.25", "original_target": "12102.25",
        "point_value": "2", "initial_risk_cash": "460.5",
        "gross_pnl": "12", "cost": "9", "net_pnl": "3",
        "exit_reason": "stop", "signal_id": "setup-1", "order_id": "order-1",
        "nq_contracts": "0", "mnq_contracts": "3",
        "fee_per_side": "1.25", "slippage_ticks": "1", "requested_limit": "12470.5",
    }
    signals = [
        {"event": "submitted", "order_id": "order-1", "signal_id": "setup-1",
         "target": "-3", "original_stop": "12547.25", "original_target": "12102.25"},
        {"event": "filled", "order_id": "order-1", "signal_id": "setup-1",
         "event_time": "2022-05-10T10:03:00-04:00", "fill_price": "12470.5",
         "original_stop": "12547.25", "original_target": "12102.25"},
        {"event": "closed", "order_id": "order-1", "signal_id": "setup-1",
         "event_time": "2022-05-10T13:42:00-04:00", "fill_price": "12468.5",
         "original_stop": "12547.25", "original_target": "12102.25"},
    ]
    logs = [{"order_id": "order-1", "signal_id": "setup-1", "side": -1,
             "stop": 12547.25, "target": 12102.25}]
    errors: list[str] = []
    result = AUDIT.audit_trades([trade], signals, logs, 500, errors)
    assert not errors
    assert result["linked_trade_count"] == 1
    assert result["mean_net_r"] == 3 / 460.5
    bad_signals = [dict(signals[0]), dict(signals[1], original_stop="12547.5"), dict(signals[2])]
    errors = []
    result = AUDIT.audit_trades([trade], bad_signals, logs, 500, errors)
    assert result["linked_trade_count"] == 0
    assert any("exact order/stop/target link" in error for error in errors)


def test_marked_drawdown_uses_prior_equity_peak(tmp_path: Path) -> None:
    times = ["2022-05-10T10:00:00-04:00", "2022-05-10T10:01:00-04:00",
             "2022-05-10T10:02:00-04:00"]
    write_csv(tmp_path / "equity.csv", [
        {"timestamp": times[0], "equity": 100000, "gross_pnl": 0, "cost": 0, "net_pnl": 0},
        {"timestamp": times[1], "equity": 100100, "gross_pnl": 100, "cost": 0, "net_pnl": 100},
        {"timestamp": times[2], "equity": 100080, "gross_pnl": -20, "cost": 0, "net_pnl": -20},
    ])
    write_csv(tmp_path / "positions.csv", [
        {"timestamp": stamp, "contracts": 0, "intrabar_contracts": 0,
         "turnover_contracts": 0} for stamp in times
    ])
    errors: list[str] = []
    result = AUDIT.audit_equity_and_positions(tmp_path / "equity.csv",
                                               tmp_path / "positions.csv", 100000, errors)
    assert not errors
    assert result["max_marked_drawdown_usd"] == -20
    assert abs(result["max_marked_drawdown_fraction"] + 20 / 100100) < 1e-12
    assert result["max_marked_drawdown_usd_peak_equity"] == 100100
    assert result["max_marked_drawdown_usd_trough_equity"] == 100080


def test_corrected_source_selects_latest_and_keeps_prior_attempts() -> None:
    old = "a" * 64
    corrected = "b" * 64
    receipts = [
        {"run_id": "old", "source_hash": old, "created_at": "2026-09-29T10:00:00Z"},
        {"run_id": "new-one", "source_hash": corrected, "created_at": "2026-09-29T11:00:00Z"},
        {"run_id": "new-two", "source_hash": corrected, "created_at": "2026-09-29T12:00:00Z"},
    ]
    attempts = [{"run_id": item["run_id"], "audit_status": "verified", "errors": [], "warnings": [],
                 "receipt_source_hash": item["source_hash"]} for item in receipts]
    selected = AUDIT.classify_attempts(receipts, attempts, corrected)
    assert selected == "new-two"
    assert [item["selection"] for item in attempts] == ["superseded", "superseded", "primary"]
    assert "DST" in attempts[0]["superseded_reason"]
    assert "new-two" in attempts[1]["superseded_reason"]
    assert len(attempts) == 3
    output = {"corrected_source_hash": corrected, "campaign_warnings": [],
              "intervals": [{"label": "inspected_development", "variants": [
                  {"label": "aligned_first_touch_be", "primary_run_id": selected, "attempts": attempts}]}]}
    report = AUDIT.report_markdown(output)
    assert "new-two" in report and "new-one" in report and "old" in report
    assert "Prior source used fixed elapsed-time 2H bins" in report
    numeric_report = AUDIT.numeric_report_markdown(output)
    assert "new-two" in numeric_report and "new-one" in numeric_report and "old" in numeric_report
    assert "Complete attempt history" in numeric_report
    pending = [{"run_id": "old", "receipt_source_hash": old}]
    assert AUDIT.classify_attempts(receipts[:1], pending, None) is None
    assert pending[0]["selection"] == "awaiting_primary_source_declaration"
    holdout = [{"run_id": "old-holdout", "source_hash": old,
                "created_at": "2026-09-29T10:00:00Z"},
               {"run_id": "new-holdout", "source_hash": corrected,
                "created_at": "2026-09-29T11:00:00Z"}]
    holdout_attempts = [{"run_id": receipt["run_id"]} for receipt in holdout]
    assert AUDIT.classify_attempts(holdout, holdout_attempts, corrected,
                                   AUDIT.CALENDAR_SUPERSESSION) == "new-holdout"
    assert "September 2026" in holdout_attempts[0]["superseded_reason"]


def test_three_development_campaigns_get_distinct_supersession_reasons() -> None:
    first, second, final = "a" * 64, "b" * 64, "c" * 64
    receipts = [{"run_id": label, "source_hash": source, "created_at": f"2026-09-29T0{index}:00:00Z"}
                for index, (label, source) in enumerate(
                    (("first", first), ("second", second), ("final", final)), 1)]
    attempts = [{"run_id": item["run_id"]} for item in receipts]
    selected = AUDIT.classify_attempts(receipts, attempts, final,
                                       reasons_by_hash={first: AUDIT.DST_SUPERSESSION,
                                                        second: AUDIT.STRICT_GUARD_SUPERSESSION})
    assert selected == "final"
    assert [item["selection"] for item in attempts] == ["superseded", "superseded", "primary"]
    assert "fixed elapsed-time" in attempts[0]["superseded_reason"]
    assert "two conservative guards" in attempts[1]["superseded_reason"]


def test_registry_decoder_accepts_legacy_and_protocol_v2_records() -> None:
    legacy = {"id": "legacy-run", "status": "Succeeded"}
    assert AUDIT.decode_registry_record("run", "legacy-run", json.dumps(legacy)) == legacy
    current = {"id": "current-run", "status": "Succeeded"}
    envelope = {
        "schema_version": 2,
        "kind": "run",
        "id": "current-run",
        "body": current,
    }
    assert AUDIT.decode_registry_record("run", "current-run", json.dumps(envelope)) == current
    envelope["extra"] = True
    try:
        AUDIT.decode_registry_record("run", "current-run", json.dumps(envelope))
    except ValueError as exc:
        assert "identity mismatch" in str(exc)
    else:
        raise AssertionError("protocol-v2 envelope with an extra field was accepted")
    envelope.pop("extra")
    envelope["id"] = "different-run"
    try:
        AUDIT.decode_registry_record("run", "current-run", json.dumps(envelope))
    except ValueError as exc:
        assert "identity mismatch" in str(exc)
    else:
        raise AssertionError("mismatched protocol-v2 envelope was accepted")


def test_registry_corruption_is_not_silently_treated_as_no_history(tmp_path: Path) -> None:
    database = tmp_path / "workbench.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE records (kind TEXT, id TEXT, body TEXT)")
        connection.execute(
            "INSERT INTO records VALUES (?,?,?)",
            ("run", "broken", json.dumps({
                "schema_version": 2,
                "kind": "run",
                "id": "broken",
                "body": {},
                "extra": True,
            })),
        )
    try:
        AUDIT.registry_runs(database)
    except ValueError as exc:
        assert "identity mismatch" in str(exc)
    else:
        raise AssertionError("corrupt registry history was silently omitted")


class AnalyzerTests(unittest.TestCase):
    def test_manifest_checksum_includes_signal_and_process_log(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            test_manifest_checksum_includes_signal_and_process_log(Path(directory))

    def test_exact_signal_link_risk_and_costs(self) -> None:
        test_exact_signal_link_risk_and_costs()

    def test_marked_drawdown_uses_prior_equity_peak(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            test_marked_drawdown_uses_prior_equity_peak(Path(directory))

    def test_corrected_source_selects_latest_and_keeps_prior_attempts(self) -> None:
        test_corrected_source_selects_latest_and_keeps_prior_attempts()

    def test_three_development_campaigns_get_distinct_supersession_reasons(self) -> None:
        test_three_development_campaigns_get_distinct_supersession_reasons()

    def test_registry_decoder_accepts_legacy_and_protocol_v2_records(self) -> None:
        test_registry_decoder_accepts_legacy_and_protocol_v2_records()

    def test_registry_corruption_is_not_silently_treated_as_no_history(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            test_registry_corruption_is_not_silently_treated_as_no_history(Path(directory))
