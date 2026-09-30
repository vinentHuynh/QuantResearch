from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from strategy_engine.parity import load_verified_evidence


@dataclass(frozen=True)
class MigrationCandidate:
    id: str
    name: str
    family: str
    script: str
    source: str
    reason: str


MIGRATION_CANDIDATES = (
    MigrationCandidate("cme-tsmom", "CME time-series momentum", "Trend", "scripts/cme/cme_time_series_momentum_backtest.py", "PWB daily proxies", "Strategy is real, but it does not yet read the normalized Databento chart contract."),
    MigrationCandidate("commodity-xsec", "Commodity cross-sectional momentum", "Cross-sectional", "scripts/cme/commodity_xsec_momentum_backtest.py", "PWB daily front months", "Requires a multi-instrument daily dataset rather than one selected chart."),
    MigrationCandidate("factor-ls", "Equity factor long/short", "Market neutral", "scripts/cme/factor_ls_backtest.py", "PWB equity factors", "Requires its factor panel and is not a futures-chart strategy."),
    MigrationCandidate("trend-overnight-book", "Trend + overnight diversified book", "Portfolio", "scripts/cme/trend_overnight_book_backtest.py", "Mixed CME daily and intraday inputs", "Requires multi-instrument selection and a portfolio-level runner contract."),
    MigrationCandidate("es-nq-trend", "ES/NQ long-flat trend", "Trend", "scripts/es_nq/es_nq_backtest.py", "PWB cash-index proxies", "Needs conversion from proxy data to the normalized Databento futures inputs."),
    MigrationCandidate("level-fill", "Prior-range and extreme level fills", "Mean reversion", "scripts/es_nq/es_nq_level_fill_backtest.py", "PWB index and commodity proxies", "Needs conversion to prepared Databento futures and standardized report output."),
    MigrationCandidate("tsmom-orb", "TSMOM-filtered intraday ORB", "Opening range", "scripts/cme/tsmom_intraday_orb_backtest.py", "SPY/QQQ proxy bars", "Needs actual futures inputs and a runner output contract."),
    MigrationCandidate("mgc-orb", "MGC opening-range breakout", "Opening range", "scripts/mgc/mgc_orb_carver_backtest.py", "Instrument-specific Databento 5m", "Needs MGC in the shared chart catalog and standardized output paths."),
    MigrationCandidate("mgc-overnight", "MGC overnight block", "Overnight", "scripts/mgc/mgc_overnight_block_backtest.py", "Instrument-specific Databento 5m", "Needs MGC in the chart catalog and chart-agnostic arguments."),
    MigrationCandidate("asia-orb", "Asia-session opening-range breakout", "Opening range", "scripts/orb/orb_asia_carver_backtest.py", "MNQ Databento 5m", "Needs chart-agnostic session parameters and standardized report output."),
    MigrationCandidate("etf-orb", "SPY/QQQ opening-range breakout", "Opening range", "scripts/orb/orb_backtest.py", "Cached ETF bars", "A real strategy, but outside the futures chart/data contract."),
    MigrationCandidate("multi-orb", "Cross-instrument opening-range breakout", "Opening range", "scripts/orb/orb_carver_backtest.py", "Instrument-specific Databento 5m", "Needs multi-chart selection and standardized report output."),
    MigrationCandidate("mnq-overnight", "MNQ overnight drift", "Overnight", "scripts/mnq/mnq_overnight_drift_backtest.py", "TradingView 6h export", "TradingView dependency must be replaced with prepared Databento bars."),
    MigrationCandidate("futures-overnight", "CME futures overnight drift", "Overnight", "scripts/overnight/futures_overnight_backtest.py", "Legacy Databento 5m files", "Needs the shared chart paths, contract metadata, and report output contract."),
    MigrationCandidate("mes-overnight", "MES overnight drift", "Overnight", "scripts/overnight/mes_overnight_drift_backtest.py", "Instrument-specific Databento 5m", "Needs MES in the chart catalog and chart-agnostic arguments."),
    MigrationCandidate("overnight-best", "Selective overnight level-exit strategy", "Overnight", "scripts/overnight/overnight_best_backtest.py", "MES/MNQ Databento 5m", "Needs chart-agnostic inputs and a standardized parameter/output contract."),
    MigrationCandidate("overnight-bracket", "Overnight prior-level bracket", "Overnight", "scripts/overnight/overnight_bracket_backtest.py", "MES/MNQ Databento 5m", "Needs chart-agnostic inputs and standardized report output."),
    MigrationCandidate("overnight-conditional", "Conditional overnight direction", "Overnight", "scripts/overnight/overnight_conditional_backtest.py", "MES/MNQ Databento 5m", "Needs its pre-specified condition rules exposed through the runner."),
    MigrationCandidate("overnight-proxy", "Risk-scaled overnight drift", "Overnight", "scripts/overnight/overnight_drift_backtest.py", "PWB cash and commodity proxies", "Needs replacement with prepared Databento futures before runner registration."),
    MigrationCandidate("overnight-carver", "Vol-scaled multi-instrument overnight book", "Portfolio", "scripts/overnight/overnight_drift_carver_backtest.py", "Instrument-specific Databento 5m", "Requires multi-chart selection and portfolio-level outputs."),
    MigrationCandidate("overnight-filtered", "Regime-filtered overnight strategy", "Overnight", "scripts/overnight/overnight_filtered_backtest.py", "MES/MNQ Databento 5m", "Needs chart-agnostic filters and standardized report output."),
    MigrationCandidate("pdh-pdl-orb", "Prior-day range gated ORB", "Opening range", "scripts/spy_qqq_intraday/pdh_pdl_range_backtest.py", "Cached ETF bars", "A costed strategy family, but its current dataset is outside the futures chart contract."),
    MigrationCandidate("spy-qqq-pairs", "SPY/QQQ intraday pairs", "Relative value", "scripts/spy_qqq_intraday/spy_qqq_pairs_backtest.py", "Cached ETF bars", "A real strategy, but outside the futures chart/data contract."),
)


def classify_script(path: Path, root: Path, classified_paths: set[str]) -> str:
    relative = path.relative_to(root).as_posix()
    name = path.stem.lower()
    if path.suffix == ".pine":
        try:
            source = path.read_text(errors="ignore")
        except OSError:
            source = ""
        return "platform_strategy" if "strategy(" in source else "platform_indicator"
    if path.suffix == ".cs":
        return "platform_strategy"
    if path.suffix == ".ps1":
        return "validation"
    if relative in classified_paths:
        return "registered_workflow"
    if any(token in name for token in ("fetch", "download")):
        return "data_ingestion"
    if any(token in name for token in ("build", "export")):
        return "data_transform"
    if any(token in name for token in ("verify", "parity", "crosscheck", "smoke_test", "sizing_check", "prop_fit_check")):
        return "validation"
    if any(token in name for token in ("report", "dashboard", "playbook", "loss_profile")):
        return "report"
    if any(token in name for token in ("search", "scan", "screen", "bakeoff", "scenario", "probe", "review", "recency", "phase")):
        return "research_study"
    if "backtest" in name or "strategy" in name or name.endswith("_sim"):
        return "strategy_or_variant"
    return "support"


def catalog_audit(root: Path, workflows: dict[str, Any]) -> dict[str, Any]:
    python_scripts = list((root / "scripts").rglob("*.py"))
    ready = [definition for definition in workflows.values() if definition.kind == "strategy"]
    studies = [definition for definition in workflows.values() if definition.kind == "study"]
    utilities = [definition for definition in workflows.values() if definition.kind == "utility"]
    owners = {
        legacy_id: definition
        for definition in workflows.values()
        for legacy_id in getattr(definition, "legacy_ids", ())
    }
    parity_evidence = load_verified_evidence(root)
    specific_strategies = []
    for candidate in MIGRATION_CANDIDATES:
        owner = owners.get(candidate.id)
        evidence = parity_evidence.get(candidate.id)
        if owner is None:
            status = "unmapped"
        elif getattr(owner, "data_mode", None) == "engine":
            if evidence and evidence.get("coverage") == "full":
                status = "canonical_parity_verified"
            elif evidence:
                status = "canonical_partial_parity"
            else:
                status = "canonical_pending_parity"
        else:
            status = "compatibility_adapter"
        specific_strategies.append({
            **asdict(candidate),
            "catalog_id": getattr(owner, "id", None),
            "catalog_name": getattr(owner, "name", None),
            "status": status,
            "parity_evidence": evidence,
        })
    migration_candidates = [
        item for item in specific_strategies if item["status"] in {"compatibility_adapter", "unmapped"}
    ]
    classified_paths = {
        definition.script for definition in workflows.values()
    } | {candidate.script for candidate in MIGRATION_CANDIDATES}
    source_files = [
        *python_scripts,
        *root.glob("*.pine"),
        *(root / "pine").rglob("*.pine"),
        *(path for path in (root / "ninjatrader").rglob("*") if path.suffix in {".py", ".cs", ".ps1"}),
    ]
    script_inventory = [
        {
            "path": path.relative_to(root).as_posix(),
            "language": {".py": "Python", ".pine": "Pine", ".cs": "C#", ".ps1": "PowerShell"}.get(path.suffix, path.suffix),
            "role": classify_script(path, root, classified_paths),
        }
        for path in sorted(source_files)
    ]
    role_counts: dict[str, int] = {}
    for item in script_inventory:
        role_counts[item["role"]] = role_counts.get(item["role"], 0) + 1
    return {
        "counts": {
            "runner_ready": len(ready),
            "migration_candidates": len(migration_candidates),
            "research_studies": len(studies),
            "data_utilities": len(utilities),
            "other_support_scripts": sum(
                path.relative_to(root).as_posix() not in classified_paths for path in python_scripts
            ),
            "python_scripts": len(python_scripts),
            "pine_scripts": sum(path.suffix == ".pine" for path in source_files),
            "ninjatrader_scripts": sum(path.is_relative_to(root / "ninjatrader") for path in source_files),
            "all_scripts": len(source_files),
            "canonical_pending_parity": sum(item["status"] == "canonical_pending_parity" for item in specific_strategies),
            "canonical_partial_parity": sum(item["status"] == "canonical_partial_parity" for item in specific_strategies),
            "canonical_parity_verified": sum(item["status"] == "canonical_parity_verified" for item in specific_strategies),
            "compatibility_adapters": sum(item["status"] == "compatibility_adapter" for item in specific_strategies),
            "unmapped_strategies": sum(item["status"] == "unmapped" for item in specific_strategies),
        },
        "migration_candidates": migration_candidates,
        "specific_strategies": specific_strategies,
        "script_inventory": script_inventory,
        "script_role_counts": role_counts,
        "research_studies": [
            {"id": item.id, "name": item.name, "script": item.script, "description": item.description}
            for item in studies
        ],
        "data_utilities": [
            {"id": item.id, "name": item.name, "script": item.script, "description": item.description}
            for item in utilities
        ],
    }
