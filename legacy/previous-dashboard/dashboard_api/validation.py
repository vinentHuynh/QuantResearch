from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def check(code: str, state: str, message: str, **evidence: Any) -> dict[str, Any]:
    return {"code": code, "state": state, "message": message, "evidence": evidence}


def extract_sample(summary: dict[str, Any] | None) -> tuple[int | None, int | None]:
    if not summary:
        return None, None
    metrics = summary.get("statistics") or summary.get("performance") or summary
    sessions = metrics.get("sessions")
    if sessions is None:
        sessions = summary.get("profile_grade_sessions")
    trades = metrics.get("trades")
    if isinstance(trades, float):
        trades = int(trades)
    return sessions if isinstance(sessions, int) else None, trades if isinstance(trades, int) else None


def validate_completed_run(
    *, return_code: int | None, output_dir: Path, artifacts: list[dict[str, Any]],
    summary: dict[str, Any] | None,
) -> tuple[str, list[dict[str, Any]]]:
    checks: list[dict[str, Any]] = []
    execution_ok = return_code == 0
    checks.append(check("execution", "pass" if execution_ok else "fail",
                        "Strategy process completed successfully." if execution_ok else "Strategy process failed.",
                        return_code=return_code))

    provenance_path = output_dir / "reproducibility.json"
    provenance_ok = False
    provenance: dict[str, Any] = {}
    if provenance_path.is_file():
        try:
            provenance = json.loads(provenance_path.read_text())
            hashes = (provenance.get("dataset_sha256", ""), provenance.get("strategy_sha256", ""))
            charts = provenance.get("charts")
            dataset_hashes = provenance.get("dataset_sha256s")
            multi_chart_ok = True
            if isinstance(charts, list) and charts:
                chart_ids = [item.get("id") for item in charts if isinstance(item, dict)]
                multi_chart_ok = (
                    len(chart_ids) == len(charts)
                    and len(set(chart_ids)) == len(chart_ids)
                    and isinstance(dataset_hashes, dict)
                    and set(dataset_hashes) == set(chart_ids)
                    and all(
                        isinstance(dataset_hashes[chart_id], str)
                        and re.fullmatch(r"[0-9a-f]{64}", dataset_hashes[chart_id])
                        for chart_id in chart_ids
                    )
                )
            provenance_ok = (
                all(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) for value in hashes)
                and isinstance(provenance.get("chart"), dict)
                and isinstance(provenance.get("parameters"), dict)
                and multi_chart_ok
            )
        except (OSError, json.JSONDecodeError):
            pass
    checks.append(check("reproducibility", "pass" if provenance_ok else "fail",
                        "Dataset, strategy code, chart metadata, and parameters are fingerprinted." if provenance_ok else "Reproducibility metadata is missing or incomplete."))

    chart = provenance.get("chart", {})
    charts = provenance.get("charts")
    charts_to_validate = charts if isinstance(charts, list) and charts else [chart]
    dataset_ok = bool(charts_to_validate) and all(
        isinstance(item, dict)
        and item.get("available") is True
        and isinstance(item.get("rows"), int)
        and item["rows"] > 0
        and "databento" in str(item.get("source", "")).lower()
        and bool(item.get("first_bar"))
        and bool(item.get("last_bar"))
        for item in charts_to_validate
    )
    checks.append(check("dataset_contract", "pass" if dataset_ok else "fail",
                        "Every registered Databento one-minute dataset has coverage metadata." if dataset_ok else "Dataset source or coverage metadata is incomplete for one or more charts.",
                        source=chart.get("source"), rows=chart.get("rows"),
                        first_bar=chart.get("first_bar"), last_bar=chart.get("last_bar"), charts=len(charts_to_validate)))

    report_artifacts = [item for item in artifacts if item.get("name") != "reproducibility.json"]
    safe_artifacts = []
    resolved_output = output_dir.resolve()
    for item in report_artifacts:
        name = item.get("name")
        if not isinstance(name, str):
            continue
        candidate = (output_dir / name).resolve()
        if candidate.is_relative_to(resolved_output) and candidate.is_file():
            safe_artifacts.append(item)
    artifacts_ok = len(safe_artifacts) > 0
    checks.append(check("artifacts", "pass" if artifacts_ok else "fail",
                        f"{len(safe_artifacts)} report artifacts were verified on disk." if artifacts_ok else "No verifiable report artifacts were produced.",
                        registered=len(report_artifacts), verified=len(safe_artifacts)))

    structured_ok = summary is not None
    checks.append(check("structured_result", "pass" if structured_ok else "watch",
                        "A machine-readable result summary is available." if structured_ok else "No standard summary was found; inspect the report manually."))

    sessions, trades = extract_sample(summary)
    if sessions is None:
        sample_state, sample_message = "watch", "Sample coverage could not be read from the strategy summary."
    elif sessions < 60:
        sample_state, sample_message = "watch", f"Only {sessions} sessions were evaluated; this is a smoke test, not research evidence."
    else:
        sample_state, sample_message = "pass", f"The report covers {sessions:,} sessions."
    if trades == 0:
        sample_state = "watch"
        sample_message += " The strategy generated no trades in this window."
    checks.append(check("sample_coverage", sample_state, sample_message, sessions=sessions, trades=trades))

    hard_failure = any(item["state"] == "fail" for item in checks)
    status = "rejected" if hard_failure else "data_validated"
    return status, checks
