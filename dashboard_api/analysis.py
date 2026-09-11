from __future__ import annotations

from typing import Any


PERFORMANCE_KEYS = {
    "net_dollars", "net_profit_dollars", "total_pnl", "total_dollars", "total_net_pnl_dollars",
    "profit_factor", "sharpe", "sharpe_ratio", "max_drawdown",
    "max_drawdown_dollars", "max_drawdown_pct_initial", "win_rate",
}
ANALYSIS_ENGINE_VERSION = "1.2"


def first_number(mapping: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
    return None


def first_value(summary: dict[str, Any], *keys: str) -> Any:
    containers = [
        summary.get("statistics"), summary.get("performance"), summary.get("metrics"), summary,
    ]
    for container in containers:
        if not isinstance(container, dict):
            continue
        for key in keys:
            value = container.get(key)
            if value is not None:
                return value
    return None


def performance_sections(summary: dict[str, Any]) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    candidates: list[tuple[str, dict[str, Any]]] = []

    def walk(name: str, value: dict[str, Any]) -> None:
        candidates.append((name, value))
        for key, child in value.items():
            if isinstance(child, dict):
                walk(f"{name} / {key}" if name else str(key), child)

    walk("result", summary)
    seen: set[int] = set()
    for name, value in candidates:
        if id(value) in seen or not PERFORMANCE_KEYS.intersection(value):
            continue
        seen.add(id(value))
        sections.append({
            "name": name.replace("_", " "),
            "trades": first_number(value, "trades", "trade_count"),
            "active_sessions": first_number(value, "active_sessions"),
            "orders": first_number(value, "orders"),
            "pnl_observations": first_number(value, "pnl_observations"),
            "pnl_frequency": value.get("pnl_frequency"),
            "net_pnl": first_number(value, "net_dollars", "net_profit_dollars", "total_pnl", "total_dollars", "total_net_pnl_dollars"),
            "profit_factor": first_number(value, "profit_factor"),
            "sharpe": first_number(value, "sharpe", "sharpe_ratio"),
            "win_rate": first_number(value, "win_rate"),
            "max_drawdown": first_number(value, "max_drawdown_pct_initial", "max_drawdown_pct", "max_drawdown_dollars", "max_drawdown"),
        })
    return sections


def find_cost_inputs(value: Any, prefix: str = "") -> list[tuple[str, float]]:
    found: list[tuple[str, float]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if any(word in str(key).lower() for word in ("commission", "slippage", "cost")):
                if isinstance(child, (int, float)) and not isinstance(child, bool):
                    found.append((path, float(child)))
            elif isinstance(child, dict):
                found.extend(find_cost_inputs(child, path))
    return found


def has_research_evidence(value: Any, terms: tuple[str, ...]) -> bool:
    def meaningful(child: Any) -> bool:
        if isinstance(child, dict):
            return any(meaningful(item) for item in child.values())
        if isinstance(child, (list, tuple, set)):
            return any(meaningful(item) for item in child)
        return child not in (None, "")

    if not isinstance(value, dict):
        return False
    for key, child in value.items():
        if meaningful(child) and any(term in str(key).lower() for term in terms):
            return True
        if isinstance(child, dict) and has_research_evidence(child, terms):
            return True
    return False


def period_has_boundaries(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and isinstance(value.get("start"), str)
        and bool(value["start"])
        and isinstance(value.get("end"), str)
        and bool(value["end"])
    )


def assessment_check(
    code: str, name: str, state: str, observed: str, requirement: str,
    rationale: str, response: str,
) -> dict[str, str]:
    return {
        "code": code, "name": name, "state": state, "observed": observed,
        "requirement": requirement, "rationale": rationale, "response": response,
    }


def automated_research_analysis(
    *, summary: dict[str, Any] | None, parameters: dict[str, Any],
    validation_status: str, validation_checks: list[dict[str, Any]],
) -> dict[str, Any]:
    summary = summary or {}
    sections = performance_sections(summary)
    sessions = first_value(summary, "sessions", "profile_grade_sessions")
    sessions = int(sessions) if isinstance(sessions, (int, float)) else None
    # Nested performance sections commonly describe the same population. Use the
    # largest declared section rather than double-counting overlapping summaries.
    trade_values = [section["trades"] for section in sections if section["trades"] is not None]
    total_trades = int(max(trade_values)) if trade_values else None
    checks: list[dict[str, str]] = []

    technical_state = "pass" if validation_status == "data_validated" else "fail"
    checks.append(assessment_check(
        "REPRO", "Reproducibility", technical_state,
        f"{validation_status.replace('_', ' ')}; {sum(item.get('state') == 'pass' for item in validation_checks)} technical checks passed",
        "Successful execution, complete provenance, valid data contract, and stored artifacts.",
        "Research interpretation is unreliable when its inputs cannot be reproduced.",
        "Resolve failed technical checks before using the result." if technical_state == "fail" else "No technical action required.",
    ))

    if total_trades is None:
        coverage_state, coverage_observed, coverage_response = "unknown", "No standardized trade count", "Add trade count and coverage dates to the strategy summary."
    elif total_trades == 0:
        session_label = f"{sessions} sessions" if sessions is not None else "session count unavailable"
        coverage_state, coverage_observed, coverage_response = "watch", f"{session_label}; zero trades", "Extend the window or verify that signals can trigger."
    else:
        coverage_state = "watch" if sessions is None or sessions < 60 or total_trades < 30 else "pass"
        primary = max(
            (section for section in sections if section["trades"] is not None),
            key=lambda section: section["trades"],
            default={},
        )
        activity = primary.get("active_sessions")
        orders = primary.get("orders")
        coverage_observed = f"{total_trades:,} closed trades"
        if activity is not None and sessions is not None:
            coverage_observed += f"; active in {int(activity):,} of {sessions:,} sessions"
        elif sessions is not None:
            coverage_observed += f" across {sessions:,} sessions"
        if orders is not None:
            coverage_observed += f"; {int(orders):,} orders"
        coverage_response = "Expand the evaluation window; this screening flag is not a universal acceptance threshold." if coverage_state == "watch" else "Treat trade count as coverage, not proof of independent evidence."
    checks.append(assessment_check(
        "COVER", "Evidence coverage", coverage_state, coverage_observed,
        "Coverage and trading activity must be explicit and appropriate to the strategy horizon.",
        "There is no universal minimum sample; the dashboard reports what is actually available.", coverage_response,
    ))

    cost_inputs = find_cost_inputs(summary)
    positive_costs = [(name, value) for name, value in cost_inputs if value > 0]
    if positive_costs:
        cost_state = "pass"
        cost_observed = ", ".join(f"{name.split('.')[-1]}={value:g}" for name, value in positive_costs[:4])
        cost_response = "Stress these assumptions before research acceptance."
    elif cost_inputs:
        cost_state, cost_observed, cost_response = "watch", "Cost fields are present but set to zero", "Run a non-zero commission and slippage sensitivity."
    else:
        cost_state, cost_observed, cost_response = "unknown", "No explicit commission, slippage, or cost input found", "Add explicit execution-cost assumptions to the summary."
    checks.append(assessment_check(
        "ECON", "Complete economics", cost_state, cost_observed,
        "Net results must include realistic fees, spread, and slippage.",
        "A gross backtest can describe signals but cannot establish a tradeable edge.", cost_response,
    ))

    negative_sections = [section for section in sections if (section["net_pnl"] is not None and section["net_pnl"] < 0) or (section["profit_factor"] is not None and section["profit_factor"] < 1)]
    positive_sections = [section for section in sections if (section["net_pnl"] is not None and section["net_pnl"] > 0) and (section["profit_factor"] is None or section["profit_factor"] >= 1)]
    if sections and len(negative_sections) == len(sections):
        edge_state, edge_observed = "fail", "All reported performance sections are negative or have profit factor below 1."
        edge_response = "Do not promote this version; review the hypothesis and assumptions."
    elif positive_sections and negative_sections:
        edge_state, edge_observed = "watch", "Reported variants disagree: some are positive and some are negative."
        edge_response = "Predeclare the primary rule and evaluate it on an untouched period."
    elif positive_sections:
        edge_state, edge_observed = "watch", "Positive net evidence is present, but it is not independently validated."
        edge_response = "Keep provisional until chronology, uncertainty, and robustness checks pass."
    else:
        edge_state, edge_observed = "unknown", "No standardized net P&L or profit-factor evidence is available."
        edge_response = "Emit net performance metrics in the strategy summary."
    checks.append(assessment_check(
        "EDGE", "Evidence of edge", edge_state, edge_observed,
        "Economically useful net performance on a predeclared evaluation period.",
        "Positive in-sample output alone never qualifies a strategy.", edge_response,
    ))

    drawdowns = [(section["name"], section["max_drawdown"]) for section in sections if section["max_drawdown"] is not None]
    risk_state = "watch" if drawdowns else "unknown"
    risk_observed = "; ".join(f"{name}: {value:,.2f} (source unit)" for name, value in drawdowns[:4]) if drawdowns else "No standardized drawdown metric"
    checks.append(assessment_check(
        "RISK", "Known risk behavior", risk_state, risk_observed,
        "Drawdown and risk must be compared with a predeclared strategy-specific limit.",
        "A measured drawdown is descriptive until an acceptance limit is registered.",
        "Register a risk limit and stress scenarios." if drawdowns else "Add drawdown and risk metrics to the summary.",
    ))

    out_of_sample = summary.get("out_of_sample")
    reported_oos = isinstance(out_of_sample, dict) and (
        bool(out_of_sample.get("performance"))
        or (isinstance(out_of_sample.get("test_years"), (int, float)) and out_of_sample["test_years"] > 0)
    )
    declared_split = (
        period_has_boundaries(summary.get("development_period"))
        and period_has_boundaries(summary.get("evaluation_period"))
    )
    chronology = reported_oos or declared_split
    checks.append(assessment_check(
        "CHRON", "Credible chronology", "pass" if chronology else "unknown",
        "Development/evaluation split reported" if chronology else "No development and untouched evaluation split reported",
        "Selection and evaluation periods must be fixed before reading evaluation results.",
        "Full-history output cannot be treated as out-of-sample evidence.",
        "Preserve the current result, then declare a future or untouched evaluation window." if not chronology else "Verify cutoff timestamps against the run record.",
    ))

    robustness = has_research_evidence(summary, ("walk_forward", "sensitivity", "bootstrap", "robustness"))
    checks.append(assessment_check(
        "ROBUST", "Robustness", "watch" if robustness else "unknown",
        "Robustness-related output detected" if robustness else "No neighboring-parameter, subperiod, or walk-forward output detected",
        "The result should not depend on one fragile parameter or period.",
        "Robustness evidence is reviewed separately from headline performance.",
        "Inspect and register the robustness evidence." if robustness else "Run predeclared neighboring-parameter and chronological tests.",
    ))

    if technical_state == "fail":
        status, headline, next_action = "blocked", "Technical validation failed, so the research result is not interpretable.", "Fix the failed data or reproducibility checks and rerun."
    elif edge_state == "fail":
        status, headline, next_action = "negative_evidence", "The run is reproducible, but its reported performance does not support an edge.", "Do not promote this version. Preserve the run and investigate the hypothesis, costs, and parameter design."
    elif total_trades == 0:
        status, headline, next_action = "smoke_test", "The code ran successfully, but no trades were generated in the selected window.", "Use a representative window or verify signal conditions before assessing performance."
    elif edge_state == "watch":
        status, headline, next_action = "provisional", "The result is suitable for research review, not strategy approval.", "Declare chronology and acceptance limits, then run out-of-sample and robustness tests."
    else:
        status, headline, next_action = "incomplete", "The run completed, but the report lacks enough standardized evidence for automated interpretation.", "Add standardized performance, coverage, cost, and risk fields to the strategy summary."

    return {
        "engine_version": ANALYSIS_ENGINE_VERSION,
        "status": status,
        "headline": headline,
        "next_action": next_action,
        "research_status": "not_reviewed",
        "chart_id": parameters.get("chart_id"),
        "sections": sections,
        "checks": checks,
    }
