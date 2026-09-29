"""Reconcile the frozen SND validation audit's four empty-maximum mismatches.

This is a read-only check of the frozen campaign. It writes only two new,
deterministic supplementary artifacts and does not change the original audit,
source snapshot, validation results, or trade ledgers.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports/snd-combinations-2026-09-26"
FAILURE = "sizing summary maximum_actual_stop_loss"
EXCEPTIONS = {
    f"CL/2024/risk-50/{scenario}"
    for scenario in ("cash_base", "cash_double", "price_1", "price_2_double_fee")
}


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def within(relative: str) -> Path:
    path = (OUT / relative.replace("\\", "/")).resolve()
    assert path.is_relative_to(OUT.resolve()), f"Path escapes campaign: {relative}"
    return path


def identity(case: dict) -> str:
    return "/".join(str(case[key]) for key in ("symbol", "fold_id", "role", "scenario"))


def save_unchanged_or_new(path: Path, content: str) -> None:
    if path.exists():
        assert path.read_text(encoding="utf-8") == content, f"Existing output differs: {path}"
        return
    with path.open("x", encoding="utf-8", newline="\n") as target:
        target.write(content)


def main() -> None:
    original_path = OUT / "independent-validation-audit.json"
    original = read_json(original_path)
    assert original["status"] == "failed"
    assert original["complete_validation"] is True
    assert original["expected_cases"] == original["audited_cases"] == 312
    assert original["source_checks"]["passed"] and not original["source_checks"]["failures"]
    assert original["identity_checks"]["passed"] and not original["identity_checks"]["failures"]
    assert len(original["records"]) == 312
    assert {row["identity"] for row in original["records"] if not row["passed"]} == EXCEPTIONS
    assert len(original["failures"]) == len(EXCEPTIONS) == 4
    assert {row["identity"] for row in original["failures"]} == EXCEPTIONS
    assert all(row["failures"] == [FAILURE] for row in original["failures"])
    assert (sum(row["checks"] for row in original["records"])
            + original["source_checks"]["checks"]
            + original["identity_checks"]["checks"] == original["total_checks"] == 35686)

    plan = read_json(OUT / "validation-plan.json")
    completion = read_json(OUT / "validation-results.json")
    assert plan["expected_cases"] == completion["expected_cases"] == completion["completed_cases"] == 312
    assert completion["status"] == "succeeded"
    planned = {identity(row): row for row in plan["cases"]}
    completed = {identity(row): row for row in completion["cases"]}
    assert len(planned) == len(completed) == 312
    assert set(planned) == set(completed) == {row["identity"] for row in original["records"]}
    assert all(row["status"] == "succeeded" for row in completed.values())

    manifest = read_json(OUT / "source-manifest.json")
    frozen = {row["path"]: row["checksum"] for row in manifest["files"]}
    source_hashes = {}
    for name in ("scripts/validate-snd-combinations.py", "scripts/audit-snd-combination-validation.py"):
        path = within("source/" + name)
        assert sha256(path) == frozen[name], f"Frozen source changed: {name}"
        source_hashes[name] = frozen[name]
    runner_source = within("source/scripts/validate-snd-combinations.py").read_text(encoding="utf-8")
    auditor_source = within("source/scripts/audit-snd-combination-validation.py").read_text(encoding="utf-8")
    assert "maximum_actual_stop_loss=float(t.actual_stop_risk_cash.max()) if len(t) and 'actual_stop_risk_cash' in t else None" in runner_source
    assert "maximum_actual_stop_loss=float(trades.actual_stop_risk_cash.max()) if len(trades) else 0." in auditor_source

    checked_artifacts = 0
    reconciled = []
    for record in original["records"]:
        case_id = record["identity"]
        detail_path = within(record["path"])
        assert sha256(detail_path) == record["checksum"], f"Audit record changed: {case_id}"
        detail = read_json(detail_path)
        assert detail["identity"] == case_id
        assert detail["checks"] == record["checks"]
        assert detail["passed"] == record["passed"]
        assert detail["artifact_checks"]["passed"] and not detail["artifact_checks"]["failures"]
        assert all(component["passed"] and not component["failures"]
                   for component in detail["components"].values())
        if case_id in EXCEPTIONS:
            assert detail["failures"] == [FAILURE]
        else:
            assert detail["passed"] is True and detail["failures"] == []

        case = planned[case_id]
        folder = within("validation/" + case_id)
        saved_input = read_json(folder / "input.json")
        result = read_json(folder / "result.json")
        status = read_json(folder / "status.json")
        assert status["status"] == result["status"] == "succeeded"
        for key, value in case.items():
            assert saved_input[key] == result[key] == value, f"Case identity changed: {case_id}/{key}"
        assert completed[case_id]["summary"] == result["summary"]
        names = [item["name"] for item in result["artifacts"]]
        assert len(names) == len(set(names)) and {"trades.parquet", "equity.parquet"} <= set(names)
        for item in result["artifacts"]:
            artifact = (folder / item["name"]).resolve()
            assert artifact.is_relative_to(folder.resolve())
            assert sha256(artifact) == item["checksum"], f"Validation artifact changed: {case_id}/{item['name']}"
            checked_artifacts += 1

        if case_id in EXCEPTIONS:
            assert set(names) == {"trades.parquet", "equity.parquet", "sizing-decisions.parquet"}
            trades = pd.read_parquet(folder / "trades.parquet")
            decisions = pd.read_parquet(folder / "sizing-decisions.parquet")
            equity = pd.read_parquet(folder / "equity.parquet")
            assert trades.empty and result["summary"]["trades"] == 0
            assert not decisions.empty and decisions["quantity_selected"].eq(0).all()
            assert result["diagnostics"]["sizing_decisions"] == len(decisions)
            assert result["diagnostics"]["trades"] == 0
            assert result["summary"]["maximum_actual_stop_loss"] is None
            assert result["summary"]["contracts_entered"] == 0
            assert result["summary"]["total_budget_overshoot"] == 0
            capital = float(case["parameters"]["capital"])
            assert len(equity) > 0
            assert np.allclose(equity["equity"].to_numpy(float), capital, rtol=0, atol=1e-7)
            assert np.allclose(equity["net_pnl"].to_numpy(float), 0, rtol=0, atol=1e-7)
            assert equity["contracts"].eq(0).all()
            reconciled.append({
                "identity": case_id,
                "audit_record_checksum": record["checksum"],
                "result_checksum": sha256(folder / "result.json"),
                "trades": 0,
                "zero_quantity_decisions": len(decisions),
                "maximum_actual_stop_loss": None,
                "original_failure": FAILURE,
            })

    assert len(reconciled) == 4
    payload = {
        "status": "passed_narrow_supplement",
        "scope": "Reconcile only four empty-set maximum_actual_stop_loss representation mismatches; the frozen audit remains failed.",
        "original_audit_status": original["status"],
        "original_audit_checksum": sha256(original_path),
        "validation_plan_checksum": sha256(OUT / "validation-plan.json"),
        "validation_results_checksum": sha256(OUT / "validation-results.json"),
        "frozen_source_checksums": source_hashes,
        "audit_cases_verified": len(original["records"]),
        "original_checks_verified": original["total_checks"],
        "other_cases_passed": len(original["records"]) - len(reconciled),
        "validation_artifact_files_checksum_verified": checked_artifacts,
        "zero_trade_cases": sorted(reconciled, key=lambda row: row["identity"]),
        "interpretation": "The maximum of actual stop losses is undefined when no trade exists. The runner encodes it as null; the auditor expected zero. All four cases have no fills, all sizing decisions select zero contracts, constant flat equity, and no other audit failure.",
        "limits": "This supplement does not rewrite or mark the original independent-validation-audit.json as passed, recalculate trades, resolve unrelated methodology, or supply prospective evidence.",
    }
    json_text = json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n"
    md_text = (
        "# Supplementary audit: four zero-trade stop-loss maxima\n\n"
        "The [frozen independent validation audit](independent-validation-audit.json) remains **failed**. "
        "This supplementary check isolates its four failures to `CL/2024/risk-50` under the four declared cost/fill scenarios. "
        "The runner stores `maximum_actual_stop_loss: null` when a case has no trades; the frozen auditor expected `0.0`. "
        "The maximum of an empty set is undefined, so `null` correctly communicates that no stop loss was observed.\n\n"
        f"All {payload['audit_cases_verified']} original case-audit records and {payload['validation_artifact_files_checksum_verified']} saved validation artifact files passed checksum checks. "
        f"The other {payload['other_cases_passed']} cases passed their original audit checks. "
        "In each of the four exceptions, the original ledger, raw equity, sizing-decision, and artifact subchecks passed. "
        "Their trade ledgers are empty, every sizing decision selects zero contracts, and equity stays flat. "
        "Each case has exactly one original failure: `sizing summary maximum_actual_stop_loss`.\n\n"
        "This is a narrow interpretation of the preserved evidence. It does not change the original audit status, frozen scripts, results, "
        "the family-wide uncertainty limit, or the absence of prospective observations. See [machine-readable checks](supplementary-zero-trade-audit.json).\n\n"
        "Reproduce from the repository root with:\n\n"
        "```powershell\n.venv/Scripts/python.exe scripts/supplement-snd-combination-zero-trade-audit.py\n```\n"
    )
    save_unchanged_or_new(OUT / "supplementary-zero-trade-audit.json", json_text)
    save_unchanged_or_new(OUT / "supplementary-zero-trade-audit.md", md_text)
    print(f"Supplementary check passed: 4 isolated empty-set mismatches; {checked_artifacts} artifact hashes verified.")


if __name__ == "__main__":
    main()
