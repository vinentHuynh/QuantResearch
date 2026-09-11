from __future__ import annotations

import csv
import io
import json
import re
import sqlite3
import subprocess
import sys
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field

from .analysis import ANALYSIS_ENGINE_VERSION, automated_research_analysis
from .charts import CHARTS, ROOT, chart_metadata, content_fingerprint, file_fingerprint
from .inventory import MIGRATION_CANDIDATES, catalog_audit
from .repository import RunRepository
from .validation import check, validate_completed_run
from strategy_engine.sessions import get_session
from .portfolio import (
    PortfolioRepository, build_decision, experiment_result, parse_import_payload,
    portfolio_snapshot, reproduce_decision, stable_hash, what_if_snapshot,
)


RUNS_ROOT = ROOT / "reports" / "dashboard_runs"
RUNS_ROOT.mkdir(parents=True, exist_ok=True)
REGISTRY_PATH = ROOT / "data" / "strategy_dashboard.sqlite3"
REPOSITORY = RunRepository(REGISTRY_PATH)
PORTFOLIO_REPOSITORY = PortfolioRepository(REGISTRY_PATH)
MAX_LOG_CHARS = 100_000


@dataclass(frozen=True)
class Parameter:
    key: str
    label: str
    kind: Literal["string", "number", "integer", "boolean", "date", "time", "select", "multiselect"]
    default: Any = None
    help: str = ""
    cli: str = ""
    choices: tuple[str, ...] = ()
    minimum: float | None = None
    maximum: float | None = None
    required: bool = False


@dataclass(frozen=True)
class StrategyDefinition:
    id: str
    name: str
    description: str
    script: str
    output_arg: str
    parameters: tuple[Parameter, ...]
    charts: tuple[str, ...]
    data_mode: Literal["snd", "one-minute", "five-minute", "adapter", "engine"]
    kind: Literal["strategy", "study", "utility"] = "strategy"
    reference_script: str | None = None
    timeframes: tuple[str, ...] = ("1m",)
    default_timeframe: str = "1m"
    legacy_ids: tuple[str, ...] = ()
    legacy_sources: tuple[str, ...] = ()
    sessions: tuple[str, ...] = ()
    default_session: str | None = None
    minimum_charts: int = 1
    maximum_charts: int = 1
    default_charts: tuple[str, ...] = ()


COMMON_DATES = (
    Parameter("start", "Start date", "date", None, "Leave blank to use the script default.", "--start"),
    Parameter("end", "End date", "date", None, "Inclusive analysis end date.", "--end"),
)

WORKFLOWS: dict[str, StrategyDefinition] = {
    "snd-baseline": StrategyDefinition(
        "snd-baseline", "SND baseline", "Supply-and-demand zone baseline across selected chart timeframes.",
        "scripts/mnq/SND_baseline_backtest.py", "--output-dir",
        (
            *COMMON_DATES,
            Parameter("body_ratio", "Minimum body ratio", "number", .5, "Zone impulse candle body/range threshold.", "--body-ratio", minimum=.01, maximum=1),
            Parameter("max_tests", "Maximum zone tests", "integer", 2, "Touches allowed before a zone expires.", "--max-tests", minimum=1, maximum=20),
            Parameter("bounce_ticks", "Bounce confirmation (ticks)", "number", 300, "Required favorable move after a touch.", "--bounce-points", minimum=1, maximum=100_000),
            Parameter("stop_cap_ticks", "Stop cap (ticks)", "number", 400, "Maximum allowed stop distance.", "--stop-cap-points", minimum=1, maximum=100_000),
            Parameter("zone_stop_buffer_ticks", "Zone stop buffer (ticks)", "number", 4, "Distance beyond the distal zone edge.", "--zone-stop-buffer-points", minimum=0, maximum=10_000),
            Parameter("target_1h_ticks", "1h target (ticks)", "number", 400, "Profit target for 1h zones.", "--target-1h-ticks", minimum=1, maximum=100_000),
            Parameter("target_4h_ticks", "4h target (ticks)", "number", 800, "Profit target for 4h zones.", "--target-4h-ticks", minimum=1, maximum=100_000),
            Parameter("target_1d_ticks", "Daily target (ticks)", "number", 1600, "Profit target for daily zones.", "--target-1d-ticks", minimum=1, maximum=100_000),
            Parameter("cost_ticks", "Round-trip cost (ticks)", "number", 0, "Commission and slippage proxy.", "--cost-ticks", minimum=0, maximum=100),
        ),
        ("MNQ", "NQ", "ES", "YM", "CL"), "snd", timeframes=("1h", "4h", "1d"), default_timeframe="1h",
    ),
    "opening-pullback": StrategyDefinition(
        "opening-pullback", "Opening trend-pullback", "Five-minute setup construction with one-minute bracket fills.",
        "scripts/mnq/mnq_opening_trend_pullback_backtest.py", "--output-dir",
        (
            *COMMON_DATES,
            Parameter("account", "Account value", "number", 25_000, "Starting account value in dollars.", "--account", minimum=1000),
            Parameter("risk_dollars", "Risk per trade", "number", 100, "Maximum planned dollars at risk per trade.", "--risk-dollars", minimum=1),
            Parameter("minimum_rr", "Minimum reward/risk", "number", 1, "Minimum target-to-stop ratio.", "--minimum-rr", minimum=.1, maximum=20),
            Parameter("zone_atr", "Zone width (ATR)", "number", .1, "Zone half-width as a share of ATR.", "--zone-atr", minimum=.01, maximum=5),
            Parameter("commission_rt", "Round-trip commission", "number", 1.24, "Dollars per contract.", "--commission-rt", minimum=0),
            Parameter("slippage_ticks_rt", "Round-trip slippage", "number", 2, "Ticks per completed trade.", "--slippage-ticks-rt", minimum=0, maximum=100),
            Parameter("bias_flip_exit", "Exit on bias flip", "boolean", False, "Enable the optional early exit.", "--bias-flip-exit"),
        ),
        ("MNQ", "NQ", "ES", "YM"), "one-minute", timeframes=("1m",),
    ),
    "asia-fill": StrategyDefinition(
        "asia-fill", "Asia gap-fill", "NY-close to Asia-session gap-fill study and headline trading rule.",
        "scripts/mnq/mnq_asia_fill_strategy_backtest.py", "--out-dir",
        (
            *COMMON_DATES,
            Parameter("close_times", "Reference closes", "multiselect", ["16:00", "17:00"], "Close times included in the research grid.", "--close-times", ("16:00", "17:00"), required=True),
            Parameter("asia_start", "Asia start", "time", "18:00", "Session start in ET.", "--asia-start", required=True),
            Parameter("asia_end", "Asia end", "time", "00:00", "Session deadline in ET.", "--asia-end", required=True),
            Parameter("rule_side", "Headline side", "select", "Short", "Direction used by the headline rule.", "--rule-side", ("Long", "Short", "Both"), required=True),
            Parameter("rule_max_gap_bps", "Maximum gap (bps)", "number", 3, "Largest gap accepted by the headline rule.", "--rule-max-gap-bps", minimum=.01, maximum=100),
            Parameter("min_gap_ticks", "Minimum gap (ticks)", "number", 1, "Smallest gap included.", "--min-gap-points", minimum=1, maximum=100_000),
            Parameter("commission_rt", "Round-trip commission", "number", 1, "Dollars per contract.", "--commission-rt", minimum=0),
            Parameter("entry_slippage_ticks", "Entry slippage", "number", 1, "Adverse ticks at entry.", "--entry-slippage-ticks", minimum=0, maximum=100),
            Parameter("exit_slippage_ticks", "Exit slippage", "number", 1, "Adverse ticks on market exits.", "--exit-slippage-ticks", minimum=0, maximum=100),
            Parameter("bootstrap", "Bootstrap draws", "integer", 2000, "Resampling iterations.", "--bootstrap", minimum=100, maximum=100_000),
        ),
        ("MNQ", "NQ", "ES", "YM", "CL"), "five-minute", timeframes=("5m",), default_timeframe="5m",
    ),
    "market-profile": StrategyDefinition(
        "market-profile", "Market profile", "80% value-area rule and naked-POC revisit tests.",
        "scripts/mnq/mnq_market_profile_backtest.py", "--output-dir",
        (
            *COMMON_DATES,
            Parameter("rth_start", "RTH start", "time", "08:30", "Chicago time.", "--rth-start", required=True),
            Parameter("rth_end", "RTH end", "time", "15:00", "Chicago time.", "--rth-end", required=True),
            Parameter("bracket_minutes", "Bracket minutes", "integer", 30, "Market-profile bracket width.", "--bracket-minutes", minimum=5, maximum=120),
            Parameter("price_step_ticks", "Profile row (ticks)", "number", 4, "Price increments per profile row.", "--price-step", minimum=1, maximum=10_000),
            Parameter("va_percent", "Value-area fraction", "number", .7, "Fraction of activity included in value area.", "--va-percent", minimum=.01, maximum=.99),
            Parameter("profile_mode", "Profile mode", "select", "volume", "Volume or TPO profile.", "--profile-mode", ("volume", "tpo"), required=True),
            Parameter("accept_mode", "Acceptance mode", "select", "close", "Bracket close or complete range must be in value area.", "--accept-mode", ("close", "range"), required=True),
            Parameter("confirm_brackets", "Confirmation brackets", "integer", 2, "Consecutive accepted brackets.", "--confirm-brackets", minimum=1, maximum=12),
            Parameter("slippage_ticks", "Slippage per side", "number", 1, "Adverse ticks on each side.", "--slippage-ticks", minimum=0, maximum=100),
            Parameter("stop_buffer_ticks", "80% rule stop buffer (ticks)", "number", 20, "Distance beyond the entry-side value-area edge.", "--stop-buffer-points", minimum=0, maximum=100_000),
            Parameter("npoc_max_distance_ticks", "Maximum nPOC distance (ticks)", "number", 400, "Only trade nPOCs within this distance.", "--npoc-max-distance", minimum=1, maximum=1_000_000),
        ),
        ("MNQ", "NQ", "ES", "YM", "CL"), "one-minute", "study",
    ),
    "build-timeframes": StrategyDefinition(
        "build-timeframes", "Build chart timeframes", "Resample a one-minute archive for downstream chart/backtest use.",
        "scripts/mnq/build_mnq_timeframes.py", "--output-dir",
        (
            Parameter("timeframes", "Chart timeframes", "multiselect", ["5m", "30m", "1h", "4h", "1d"], "Bars to generate.", "--timeframes", ("5m", "30m", "1h", "4h", "1d"), required=True),
            Parameter("keep_partial_final", "Keep partial final bar", "boolean", False, "Keep the final incomplete candle.", "--keep-partial-final"),
        ),
        ("MNQ", "NQ", "ES", "YM", "CL"), "one-minute", "utility",
    ),
}


ADAPTER_BASE = (
    *COMMON_DATES,
    Parameter("capital", "Starting capital", "number", 100_000, "Capital used for normalized P&L.", "--capital", minimum=1_000),
    Parameter("cost_ticks", "Round-trip cost (ticks)", "number", 1, "Commission, spread, and slippage expressed as ticks.", "--cost-ticks", minimum=0, maximum=100),
)

POSITION_SIZING = Parameter(
    "quantity_mode", "Position quantity", "select", "fractional",
    "Fractional normalizes research exposure; whole_contracts truncates toward zero for executable quantities.",
    "--quantity-mode", ("fractional", "whole_contracts"), required=True,
)


def legacy_sources(*ids: str) -> tuple[str, ...]:
    by_id = {candidate.id: candidate.script for candidate in MIGRATION_CANDIDATES}
    return tuple(by_id[item] for item in ids)


def adapter_strategy(
    strategy_id: str,
    name: str,
    description: str,
    parameters: tuple[Parameter, ...],
    timeframes: tuple[str, ...],
    default_timeframe: str,
    legacy_ids: tuple[str, ...],
    *,
    script: str = "scripts/dashboard_compatible_strategy.py",
    data_mode: Literal["adapter", "engine"] = "adapter",
    sessions: tuple[str, ...] = (),
    default_session: str | None = None,
    minimum_charts: int = 1,
    maximum_charts: int = 1,
    default_charts: tuple[str, ...] = (),
) -> StrategyDefinition:
    sources = legacy_sources(*legacy_ids)
    return StrategyDefinition(
        strategy_id, name, description, script, "--output-dir",
        parameters, tuple(CHARTS), data_mode, reference_script=sources[0] if sources else None,
        timeframes=timeframes, default_timeframe=default_timeframe,
        legacy_ids=legacy_ids, legacy_sources=sources,
        sessions=sessions, default_session=default_session,
        minimum_charts=minimum_charts, maximum_charts=maximum_charts, default_charts=default_charts,
    )


WORKFLOWS.update({
    "multi-speed-momentum": adapter_strategy(
        "multi-speed-momentum", "Multi-speed time-series momentum",
        "Long/short momentum combined across four lookbacks on the selected chart and bar timeframe.",
        (*ADAPTER_BASE, POSITION_SIZING, Parameter("lookback", "Base lookback (bars)", "integer", 60, "Other speeds are one-third, two, and four times this value.", "--lookback", minimum=5, maximum=504)),
        ("30m", "1h", "4h", "1d"), "1d", ("cme-tsmom",),
        script="strategy_engine/runner.py", data_mode="engine",
        sessions=("full-trading-day", "new-york-rth", "london", "asia"), default_session="full-trading-day",
    ),
    "moving-average-trend": adapter_strategy(
        "moving-average-trend", "Moving-average trend",
        "Long while the selected chart closes above its moving average; flat otherwise.",
        (*ADAPTER_BASE, POSITION_SIZING, Parameter("lookback", "Moving-average lookback (bars)", "integer", 60, "Number of selected-timeframe bars in the moving average.", "--lookback", minimum=5, maximum=504)),
        ("30m", "1h", "4h", "1d"), "1d", ("es-nq-trend",),
        script="strategy_engine/runner.py", data_mode="engine",
        sessions=("full-trading-day", "new-york-rth", "london", "asia"), default_session="full-trading-day",
    ),
    "cross-sectional-momentum": adapter_strategy(
        "cross-sectional-momentum", "Cross-sectional momentum",
        "Ranks every available chart at the selected timeframe and holds an equal-risk long/short basket.",
        (*ADAPTER_BASE, POSITION_SIZING, Parameter("lookback", "Ranking lookback (bars)", "integer", 60, "Bars used to rank chart momentum.", "--lookback", minimum=5, maximum=504)),
        ("1h", "4h", "1d"), "1d", ("commodity-xsec", "factor-ls"),
        script="strategy_engine/runner.py", data_mode="engine",
        sessions=("full-trading-day", "new-york-rth", "london", "asia"), default_session="full-trading-day",
        minimum_charts=3, maximum_charts=len(CHARTS), default_charts=tuple(CHARTS),
    ),
    "pairs-mean-reversion": adapter_strategy(
        "pairs-mean-reversion", "Pairs mean reversion",
        "Trades the selected chart against another available chart using a rolling log-price z-score.",
        (*ADAPTER_BASE, POSITION_SIZING, Parameter("lookback", "Z-score lookback (bars)", "integer", 60, "Bars used for the rolling spread mean and deviation.", "--lookback", minimum=5, maximum=504)),
        ("30m", "1h", "4h", "1d"), "1d", ("spy-qqq-pairs",),
        script="strategy_engine/runner.py", data_mode="engine",
        sessions=("full-trading-day", "new-york-rth", "london", "asia"), default_session="full-trading-day",
        minimum_charts=2, maximum_charts=2, default_charts=("MNQ", "NQ"),
    ),
    "prior-range-fill": adapter_strategy(
        "prior-range-fill", "Prior-range fill",
        "Fades a gap after price trades back to the selected market session's prior high or low.",
        ADAPTER_BASE, ("1m", "5m", "15m", "30m", "1h"), "5m", ("level-fill",),
        script="strategy_engine/runner.py", data_mode="engine",
        sessions=("new-york-rth", "london", "asia"), default_session="new-york-rth",
    ),
    "opening-range-breakout": adapter_strategy(
        "opening-range-breakout", "Opening-range breakout",
        "Trades the first completed-bar close outside the selected market session's opening range with bracket exits.",
        (*ADAPTER_BASE,
         Parameter("opening_range_minutes", "Opening range (minutes)", "integer", 15, "Initial session range before entries are allowed.", "--opening-range-minutes", minimum=5, maximum=120),
         Parameter("stop_multiple", "Stop distance (R)", "number", 1, "Stop as a multiple of opening-range risk.", "--stop-multiple", minimum=.1, maximum=20),
         Parameter("target_multiple", "Target distance (R)", "number", 2, "Target as a multiple of opening-range risk.", "--target-multiple", minimum=.1, maximum=50)),
        ("1m", "5m", "15m", "30m"), "5m",
        ("tsmom-orb", "mgc-orb", "asia-orb", "etf-orb", "multi-orb", "pdh-pdl-orb"),
        script="strategy_engine/runner.py", data_mode="engine",
        sessions=("new-york-rth", "london", "asia"), default_session="new-york-rth",
    ),
    "overnight-session": adapter_strategy(
        "overnight-session", "Session drift",
        "Holds the selected market session with optional prior-session direction, range filter, and bracket exits.",
        (*ADAPTER_BASE,
         Parameter("direction_model", "Direction model", "select", "Long", "Always long or follow the prior-session direction.", "--direction-model", ("Long", "Prior trend"), required=True),
         Parameter("bracket_exit", "Use bracket exit", "boolean", False, "Exit early at the configured stop or target.", "--bracket-exit"),
         Parameter("max_prior_range_pct", "Maximum prior range (%)", "number", 0, "Skip wide prior sessions; zero disables this filter.", "--max-prior-range-pct", minimum=0, maximum=100),
         Parameter("stop_multiple", "Stop distance (R)", "number", 1, "Stop as a multiple of prior-session range risk.", "--stop-multiple", minimum=.1, maximum=20),
         Parameter("target_multiple", "Target distance (R)", "number", 2, "Target as a multiple of prior-session range risk.", "--target-multiple", minimum=.1, maximum=50)),
        ("1m", "5m", "15m", "30m", "1h"), "5m",
        ("trend-overnight-book", "mgc-overnight", "mnq-overnight", "futures-overnight", "mes-overnight", "overnight-best", "overnight-bracket", "overnight-conditional", "overnight-proxy", "overnight-carver", "overnight-filtered"),
        script="strategy_engine/runner.py", data_mode="engine",
        sessions=("globex-overnight", "new-york-rth", "london", "asia"), default_session="globex-overnight",
    ),
})


@dataclass
class RunRecord:
    id: str
    strategy_id: str
    strategy_name: str
    status: Literal["queued", "running", "completed", "failed"]
    parameters: dict[str, Any]
    command: list[str]
    output_dir: str
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    return_code: int | None = None
    log: str = ""
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    summary: dict[str, Any] | None = None
    validation_status: Literal["pending", "data_validated", "rejected"] = "pending"
    validation_checks: list[dict[str, Any]] = field(default_factory=list)
    research_status: Literal["not_reviewed"] = "not_reviewed"
    automated_analysis: dict[str, Any] | None = None


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    strategy_id: str
    chart_id: Optional[str] = None
    chart_ids: List[str] = Field(default_factory=list)
    timeframe: Optional[str] = None
    session_id: Optional[str] = None
    parameters: dict[str, Any] = Field(default_factory=dict)


class PortfolioPayload(BaseModel):
    model_config = ConfigDict(extra="allow")


class ObservationImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    strategy_version_id: str
    source: str
    records: Optional[List[Dict[str, Any]]] = None
    csv: Optional[str] = None


class DecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cutoff: Optional[str] = None
    effective_time: Optional[str] = None


class AlertActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["acknowledge", "resolve"]
    note: Optional[str] = None


RUNS: dict[str, RunRecord] = {}
LOCK = threading.Lock()
EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="dashboard-run")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def public_parameter(param: Parameter) -> dict[str, Any]:
    value = asdict(param)
    value.pop("cli")
    value["choices"] = list(value["choices"])
    return value


def serialize_run(record: RunRecord, include_log: bool = True) -> dict[str, Any]:
    value = asdict(record)
    if not include_log:
        value.pop("log")
    return value


def persist(record: RunRecord) -> None:
    output = ROOT / record.output_dir
    output.mkdir(parents=True, exist_ok=True)
    payload = serialize_run(record)
    (output / "dashboard_run.json").write_text(json.dumps(payload, indent=2, default=str))
    REPOSITORY.save(payload)


def validate_parameter(param: Parameter, raw: Any) -> Any:
    if raw is None or raw == "":
        if param.required and param.default is None:
            raise ValueError(f"{param.label} is required")
        return param.default
    if param.kind in {"number", "integer"}:
        if isinstance(raw, bool):
            raise ValueError(f"{param.label} must be numeric")
        try:
            value = int(raw) if param.kind == "integer" else float(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{param.label} must be numeric") from exc
        if param.minimum is not None and value < param.minimum:
            raise ValueError(f"{param.label} must be at least {param.minimum}")
        if param.maximum is not None and value > param.maximum:
            raise ValueError(f"{param.label} must be no more than {param.maximum}")
        return value
    if param.kind == "boolean":
        if not isinstance(raw, bool):
            raise ValueError(f"{param.label} must be true or false")
        return raw
    if param.kind == "multiselect":
        if not isinstance(raw, list) or not raw:
            raise ValueError(f"{param.label} must contain at least one choice")
        if any(item not in param.choices for item in raw):
            raise ValueError(f"{param.label} contains an unsupported choice")
        return list(dict.fromkeys(raw))
    value = str(raw)
    if param.kind == "select" and value not in param.choices:
        raise ValueError(f"{param.label} is not an allowed choice")
    if param.kind == "date" and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError(f"{param.label} must be YYYY-MM-DD")
    if param.kind == "time" and not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
        raise ValueError(f"{param.label} must be HH:MM")
    if len(value) > 200:
        raise ValueError(f"{param.label} is too long")
    return value


def build_command(definition: StrategyDefinition, chart_id: str, timeframe: Optional[str], supplied: dict[str, Any], run_dir: Path, session_id: Optional[str] = None, chart_ids: Optional[list[str]] = None) -> tuple[list[str], dict[str, Any]]:
    selected_chart_ids = list(dict.fromkeys(chart_ids or [chart_id]))
    if not definition.minimum_charts <= len(selected_chart_ids) <= definition.maximum_charts:
        required = str(definition.minimum_charts) if definition.minimum_charts == definition.maximum_charts else f"{definition.minimum_charts}-{definition.maximum_charts}"
        raise ValueError(f"{definition.name} requires {required} charts")
    invalid_charts = [item for item in selected_chart_ids if item not in definition.charts]
    if invalid_charts:
        raise ValueError(f"{definition.name} is not approved for {', '.join(invalid_charts)}")
    unavailable = [item for item in selected_chart_ids if item not in CHARTS or not CHARTS[item].path_1m().is_file()]
    if unavailable:
        raise ValueError(f"Chart dataset {', '.join(unavailable)} is unavailable")
    chart = CHARTS[selected_chart_ids[0]]
    selected_timeframe = timeframe or definition.default_timeframe
    if selected_timeframe not in definition.timeframes:
        raise ValueError(f"{definition.name} does not support the {selected_timeframe} timeframe")
    selected_session = session_id or definition.default_session
    if definition.sessions:
        if selected_session not in definition.sessions:
            raise ValueError(f"{definition.name} does not support the selected session")
        get_session(selected_session)
    known = {p.key for p in definition.parameters}
    unknown = set(supplied) - known
    if unknown:
        raise ValueError(f"Unknown parameters: {', '.join(sorted(unknown))}")
    if definition.data_mode == "engine":
        command = [
            sys.executable, "-m", "strategy_engine.runner",
            "--strategy-id", definition.id,
            definition.output_arg, str(run_dir),
            "--one-minute", str(chart.path_1m()),
            "--timeframe", selected_timeframe,
            "--session-id", str(selected_session),
        ]
        for item in selected_chart_ids:
            leg = CHARTS[item]
            command.extend(["--leg-json", json.dumps({
                "id": leg.id,
                "symbol": leg.symbol,
                "path": str(leg.path_1m()),
                "tick_size": leg.tick_size,
                "point_value": leg.point_value,
            }, separators=(",", ":"))])
    else:
        command = [sys.executable, str(ROOT / definition.script), definition.output_arg, str(run_dir)]
    if definition.data_mode == "snd":
        command.extend(["--one-minute", str(chart.path_1m()), "--timeframe-dir", str(ROOT / chart.timeframe_dir)])
        command.extend(["--timeframes", selected_timeframe])
    elif definition.data_mode == "one-minute":
        input_arg = "--input" if definition.id == "build-timeframes" else "--data" if definition.id == "opening-pullback" else "--one-minute"
        command.extend([input_arg, str(chart.path_1m())])
    elif definition.data_mode == "five-minute":
        five_minute = chart.path_for_timeframe("5m")
        if not five_minute.is_file():
            raise ValueError(f"{chart_id} has no prepared five-minute dataset")
        command.extend(["--data", str(five_minute)])
    elif definition.data_mode == "adapter":
        peers = ",".join(
            f"{peer.symbol}={peer.path_1m()}" for peer in CHARTS.values()
            if peer.path_1m().is_file()
        )
        command.extend([
            "--strategy-id", definition.id,
            "--one-minute", str(chart.path_1m()),
            "--timeframe", selected_timeframe,
            "--peer-data", peers,
        ])
    if definition.id != "build-timeframes":
        command.extend(["--symbol", chart.symbol, "--tick-size", str(chart.tick_size), "--point-value", str(chart.point_value)])
    validated: dict[str, Any] = {}
    for param in definition.parameters:
        value = validate_parameter(param, supplied.get(param.key, param.default))
        validated[param.key] = value
        if value is None or value == "" or (param.kind == "boolean" and not value):
            continue
        command.append(param.cli)
        if param.kind != "boolean":
            formatted = ",".join(value) if param.kind == "multiselect" else str(value)
            if param.key in {"bounce_ticks", "stop_cap_ticks", "zone_stop_buffer_ticks", "min_gap_ticks", "price_step_ticks", "stop_buffer_ticks", "npoc_max_distance_ticks"}:
                formatted = str(float(value) * chart.tick_size)
            if definition.id == "snd-baseline" and param.kind == "date":
                boundary = "23:59:59" if param.key == "end" else "00:00:00"
                formatted = datetime.fromisoformat(f"{value}T{boundary}").replace(tzinfo=ZoneInfo("America/New_York")).isoformat()
            command.append(formatted)
    return command, validated


def artifact_kind(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".png", ".jpg", ".jpeg", ".webp", ".svg"}: return "image"
    if suffix == ".csv": return "table"
    if suffix == ".json": return "json"
    if suffix in {".html", ".htm"}: return "html"
    if suffix in {".md", ".txt", ".log"}: return "text"
    return "file"


def collect_artifacts(run_id: str, run_dir: Path) -> list[dict[str, Any]]:
    result = []
    for path in sorted(run_dir.rglob("*")):
        if not path.is_file() or path.name == "dashboard_run.json": continue
        relative = path.relative_to(run_dir).as_posix()
        result.append({"name": relative, "kind": artifact_kind(path), "size": path.stat().st_size, "url": f"/api/runs/{run_id}/files/{relative}"})
    return result


def load_summary(run_dir: Path) -> dict[str, Any] | None:
    candidates = [
        run_dir / "summary.json",
        *run_dir.glob("*summary*.json"),
        run_dir / "run.json",
        run_dir / "resample_manifest.json",
    ]
    for path in candidates:
        if path.is_file():
            try:
                value = json.loads(path.read_text())
                return value if isinstance(value, dict) else {"result": value}
            except (OSError, json.JSONDecodeError):
                pass
    return None


def execute_run(run_id: str) -> None:
    with LOCK:
        record = RUNS[run_id]
        record.status = "running"
        record.started_at = utc_now()
        persist(record)
    try:
        process = subprocess.run(record.command, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60 * 60)
        log = process.stdout[-MAX_LOG_CHARS:]
        output_dir = ROOT / record.output_dir
        with LOCK:
            record.log = log
            record.return_code = process.returncode
            record.status = "completed" if process.returncode == 0 else "failed"
            record.finished_at = utc_now()
            record.artifacts = collect_artifacts(run_id, output_dir)
            record.summary = load_summary(output_dir)
            record.validation_status, record.validation_checks = validate_completed_run(
                return_code=record.return_code,
                output_dir=output_dir,
                artifacts=record.artifacts,
                summary=record.summary,
            )
            record.automated_analysis = automated_research_analysis(
                summary=record.summary,
                parameters=record.parameters,
                validation_status=record.validation_status,
                validation_checks=record.validation_checks,
            )
            persist(record)
    except Exception as exc:
        with LOCK:
            record.status = "failed"
            record.finished_at = utc_now()
            record.log = f"{type(exc).__name__}: {exc}"
            output_dir = ROOT / record.output_dir
            record.artifacts = collect_artifacts(run_id, output_dir)
            record.validation_status, record.validation_checks = validate_completed_run(
                return_code=record.return_code,
                output_dir=output_dir,
                artifacts=record.artifacts,
                summary=record.summary,
            )
            record.automated_analysis = automated_research_analysis(
                summary=record.summary,
                parameters=record.parameters,
                validation_status=record.validation_status,
                validation_checks=record.validation_checks,
            )
            persist(record)


def load_existing_runs() -> None:
    payloads = REPOSITORY.load()
    known_ids = {payload.get("id") for payload in payloads}
    for pattern in ("*/dashboard_run.json", "*/run.json"):
        for path in RUNS_ROOT.glob(pattern):
            try:
                raw = json.loads(path.read_text())
                if not raw.get("id") or not raw.get("strategy_id") or raw["id"] in known_ids:
                    continue
                payloads.append(raw)
                known_ids.add(raw["id"])
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                continue
    for raw in payloads:
        try:
            raw.setdefault("validation_status", "pending")
            raw.setdefault("validation_checks", [])
            raw.setdefault("research_status", "not_reviewed")
            raw.setdefault("automated_analysis", None)
            if raw.get("status") in {"queued", "running"}:
                raw["status"] = "failed"
                raw["log"] = (raw.get("log") or "") + "\nAPI restarted before this run finished."
                raw["finished_at"] = utc_now()
                raw["validation_status"] = "rejected"
                raw["validation_checks"] = [check(
                    "execution", "fail", "API restarted before this run finished."
                )]
            elif raw.get("status") in {"completed", "failed"} and raw["validation_status"] == "pending":
                output_dir = ROOT / raw["output_dir"]
                raw["artifacts"] = collect_artifacts(raw["id"], output_dir)
                raw["summary"] = load_summary(output_dir)
                raw["validation_status"], raw["validation_checks"] = validate_completed_run(
                    return_code=raw.get("return_code"),
                    output_dir=output_dir,
                    artifacts=raw["artifacts"],
                    summary=raw["summary"],
                )
            if raw.get("status") in {"completed", "failed"} and (
                not isinstance(raw["automated_analysis"], dict)
                or raw["automated_analysis"].get("engine_version") != ANALYSIS_ENGINE_VERSION
            ):
                raw["automated_analysis"] = automated_research_analysis(
                    summary=raw.get("summary"),
                    parameters=raw.get("parameters", {}),
                    validation_status=raw["validation_status"],
                    validation_checks=raw["validation_checks"],
                )
            record = RunRecord(**raw)
            RUNS[record.id] = record
            persist(record)
        except (KeyError, OSError, ValueError, TypeError, json.JSONDecodeError):
            continue


for definition in WORKFLOWS.values():
    if definition.kind == "strategy":
        PORTFOLIO_REPOSITORY.ensure_strategy(
            strategy_id=definition.id,
            name=definition.name,
            code_hash=content_fingerprint(ROOT / definition.script),
        )

load_existing_runs()
app = FastAPI(title="Strategy Health Dashboard API", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"], allow_methods=["*"], allow_headers=["*"])


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "python": sys.executable,
        "strategies": sum(definition.kind == "strategy" for definition in WORKFLOWS.values()),
        "workflows": len(WORKFLOWS),
        "run_registry": str(REGISTRY_PATH.relative_to(ROOT)),
    }


@app.get("/api/strategies")
def strategy_catalog() -> list[dict[str, Any]]:
    return [{
        "id": d.id, "name": d.name, "description": d.description, "kind": d.kind,
        "charts": list(d.charts), "timeframes": list(d.timeframes),
        "default_timeframe": d.default_timeframe, "legacy_ids": list(d.legacy_ids),
        "legacy_sources": list(d.legacy_sources),
        "sessions": [get_session(session_id).public() for session_id in d.sessions],
        "default_session": d.default_session,
        "minimum_charts": d.minimum_charts, "maximum_charts": d.maximum_charts,
        "default_charts": list(d.default_charts),
        "parameters": [public_parameter(p) for p in d.parameters],
    } for d in WORKFLOWS.values() if d.kind == "strategy"]


@app.get("/api/catalog-audit")
def strategy_catalog_audit() -> dict[str, Any]:
    return catalog_audit(ROOT, WORKFLOWS)


@app.get("/api/charts")
def chart_catalog() -> list[dict[str, Any]]:
    return [chart_metadata(chart) for chart in CHARTS.values()]


@app.get("/api/portfolio")
def get_portfolio(cutoff: Optional[str] = None) -> dict[str, Any]:
    try:
        return portfolio_snapshot(PORTFOLIO_REPOSITORY, cutoff)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get("/api/portfolio/settings")
def get_portfolio_settings() -> dict[str, Any]:
    return PORTFOLIO_REPOSITORY.settings()


@app.put("/api/portfolio/settings")
def update_portfolio_settings(request: PortfolioPayload) -> dict[str, Any]:
    try:
        return PORTFOLIO_REPOSITORY.update_settings(request.model_dump(exclude_unset=True))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get("/api/portfolio/strategy-versions")
def list_strategy_versions() -> list[dict[str, Any]]:
    return PORTFOLIO_REPOSITORY.strategies()


@app.post("/api/portfolio/strategy-versions", status_code=201)
def create_strategy_version(request: PortfolioPayload) -> dict[str, Any]:
    try:
        return PORTFOLIO_REPOSITORY.create_strategy(request.model_dump(exclude_unset=True))
    except sqlite3.IntegrityError as exc:
        raise HTTPException(409, "That immutable strategy version already exists") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get("/api/portfolio/eligibility-assessments")
def list_eligibility_assessments(strategy_version_id: Optional[str] = None) -> list[dict[str, Any]]:
    return PORTFOLIO_REPOSITORY.eligibility_history(strategy_version_id)


@app.post("/api/portfolio/eligibility-assessments", status_code=201)
def create_eligibility_assessment(request: PortfolioPayload) -> dict[str, Any]:
    try:
        return PORTFOLIO_REPOSITORY.assess_eligibility(request.model_dump(exclude_unset=True))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get("/api/portfolio/strategy-versions/{version_id:path}")
def get_strategy_version(version_id: str) -> dict[str, Any]:
    strategy = PORTFOLIO_REPOSITORY.strategy(version_id)
    if not strategy:
        raise HTTPException(404, "Strategy version not found")
    snapshot = portfolio_snapshot(PORTFOLIO_REPOSITORY)
    assessment = next((item for item in snapshot["strategies"] if item["id"] == version_id), None)
    return {"strategy": strategy, "assessment": assessment, "eligibility_history": PORTFOLIO_REPOSITORY.eligibility_history(version_id),
            "observations": PORTFOLIO_REPOSITORY.observations(version_id)[-500:]}


@app.post("/api/portfolio/import", status_code=201)
def import_portfolio_observations(request: ObservationImportRequest) -> dict[str, Any]:
    try:
        rows = parse_import_payload(request.model_dump(exclude_none=True))
        result = PORTFOLIO_REPOSITORY.import_observations(
            strategy_version_id=request.strategy_version_id, rows=rows, source=request.source,
        )
        snapshot = portfolio_snapshot(PORTFOLIO_REPOSITORY)
        result["assessment"] = next((item for item in snapshot["strategies"] if item["id"] == request.strategy_version_id), None)
        return result
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.post("/api/portfolio/decisions", status_code=201)
def create_portfolio_decision(request: DecisionRequest) -> dict[str, Any]:
    try:
        decision = build_decision(PORTFOLIO_REPOSITORY, request.cutoff, request.effective_time)
        saved = PORTFOLIO_REPOSITORY.save_decision(decision)
        for proposal in saved["proposals"]:
            if proposal["health"] in {"Breached", "Unknown"}:
                PORTFOLIO_REPOSITORY.upsert_alert(
                    strategy_version_id=proposal["id"], code=proposal["reason_codes"][0],
                    severity="critical" if proposal["health"] == "Breached" else "warning",
                    title=f"{proposal['name']}: {proposal['health']}",
                    detail=", ".join(proposal["reason_codes"]), evidence={"decision_id": saved["id"]},
                )
            if proposal["eligibility"] != "Qualified" and proposal["current_exposure"]:
                PORTFOLIO_REPOSITORY.upsert_alert(
                    strategy_version_id=proposal["id"], code="INELIGIBLE_EXISTING_EXPOSURE", severity="critical",
                    title=f"{proposal['name']}: exposure needs review",
                    detail="Existing exposure is recorded for a version that is not Qualified.", evidence={"decision_id": saved["id"]},
                )
        return saved
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get("/api/portfolio/decisions")
def list_portfolio_decisions(limit: int = 100) -> list[dict[str, Any]]:
    return PORTFOLIO_REPOSITORY.decisions(limit)


@app.get("/api/portfolio/decisions/{decision_id}")
def get_portfolio_decision(decision_id: str) -> dict[str, Any]:
    decision = next((item for item in PORTFOLIO_REPOSITORY.decisions(1000) if item["id"] == decision_id), None)
    if not decision:
        raise HTTPException(404, "Decision not found")
    return decision


@app.post("/api/portfolio/decisions/{decision_id}/reproduce")
def reproduce_portfolio_decision(decision_id: str) -> dict[str, Any]:
    decision = get_portfolio_decision(decision_id)
    material = decision.get("input_snapshot")
    actual_hash = stable_hash(material) if material else None
    result = reproduce_decision(decision)
    return {"decision_id": decision_id, **result, "input_snapshot_intact": actual_hash == decision["snapshot_hash"],
            "expected_snapshot_hash": decision["snapshot_hash"], "actual_snapshot_hash": actual_hash,
            "calculation_version": decision["calculation_version"]}


@app.get("/api/portfolio/alerts")
def list_portfolio_alerts() -> list[dict[str, Any]]:
    return PORTFOLIO_REPOSITORY.alerts()


@app.post("/api/portfolio/alerts/{alert_id}")
def update_portfolio_alert(alert_id: str, request: AlertActionRequest) -> dict[str, Any]:
    try:
        return PORTFOLIO_REPOSITORY.update_alert(alert_id, request.action, request.note)
    except ValueError as exc:
        raise HTTPException(404 if "not found" in str(exc).lower() else 422, str(exc)) from exc


@app.get("/api/portfolio/overrides")
def list_portfolio_overrides() -> list[dict[str, Any]]:
    return PORTFOLIO_REPOSITORY.overrides()


@app.post("/api/portfolio/overrides", status_code=201)
def create_portfolio_override(request: PortfolioPayload) -> dict[str, Any]:
    try:
        return PORTFOLIO_REPOSITORY.create_override(request.model_dump(exclude_unset=True))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get("/api/portfolio/experiments")
def list_portfolio_experiments() -> list[dict[str, Any]]:
    return PORTFOLIO_REPOSITORY.experiments()


@app.post("/api/portfolio/experiments", status_code=201)
def create_portfolio_experiment(request: PortfolioPayload) -> dict[str, Any]:
    try:
        return experiment_result(PORTFOLIO_REPOSITORY, request.model_dump(exclude_unset=True))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get("/api/portfolio/experiments/{experiment_id}/reviews")
def list_experiment_reviews(experiment_id: str) -> list[dict[str, Any]]:
    return PORTFOLIO_REPOSITORY.experiment_reviews(experiment_id)


@app.post("/api/portfolio/experiments/{experiment_id}/reviews", status_code=201)
def review_portfolio_experiment(experiment_id: str, request: PortfolioPayload) -> dict[str, Any]:
    try:
        return PORTFOLIO_REPOSITORY.review_experiment(experiment_id, request.model_dump(exclude_unset=True))
    except ValueError as exc:
        raise HTTPException(404 if "not found" in str(exc).lower() else 422, str(exc)) from exc


@app.post("/api/portfolio/what-if")
def portfolio_what_if(request: PortfolioPayload) -> dict[str, Any]:
    try:
        return what_if_snapshot(PORTFOLIO_REPOSITORY, request.model_dump(exclude_unset=True))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get("/api/portfolio/export")
def export_portfolio(kind: Literal["decisions", "strategies", "alerts", "experiments"] = "decisions", format: Literal["json", "csv"] = "json") -> Any:
    records = {"decisions": PORTFOLIO_REPOSITORY.decisions, "strategies": PORTFOLIO_REPOSITORY.strategies,
               "alerts": PORTFOLIO_REPOSITORY.alerts, "experiments": PORTFOLIO_REPOSITORY.experiments}[kind]()
    if format == "json":
        return records
    output = io.StringIO()
    keys = sorted(set().union(*(item.keys() for item in records))) if records else []
    writer = csv.DictWriter(output, fieldnames=keys)
    writer.writeheader()
    for record in records:
        writer.writerow({key: json.dumps(record[key]) if isinstance(record.get(key), (dict, list)) else record.get(key) for key in keys})
    return PlainTextResponse(output.getvalue(), media_type="text/csv", headers={"Content-Disposition": f"attachment; filename={kind}.csv"})


@app.post("/api/runs", status_code=202)
def create_run(request: RunRequest) -> dict[str, Any]:
    definition = WORKFLOWS.get(request.strategy_id)
    if not definition:
        raise HTTPException(404, "Unknown strategy")
    if definition.kind != "strategy":
        raise HTTPException(422, f"{definition.name} is a {definition.kind}, not a strategy")
    run_id = f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
    run_dir = RUNS_ROOT / run_id
    selected_chart_ids = list(dict.fromkeys(
        request.chart_ids
        or ([request.chart_id] if request.chart_id else [])
        or definition.default_charts
        or definition.charts[:1]
    ))
    primary_chart_id = selected_chart_ids[0] if selected_chart_ids else ""
    try:
        command, validated = build_command(
            definition, primary_chart_id, request.timeframe, request.parameters, run_dir,
            request.session_id, selected_chart_ids,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    selected_timeframe = request.timeframe or definition.default_timeframe
    selected_session = request.session_id or definition.default_session
    validated = {"chart_id": primary_chart_id, "chart_ids": selected_chart_ids, "timeframe": selected_timeframe, **validated}
    if selected_session:
        validated["session_id"] = selected_session
    display_parts = [definition.name, "/".join(selected_chart_ids), selected_timeframe]
    if selected_session:
        display_parts.append(get_session(selected_session).name)
    record = RunRecord(run_id, definition.id, " · ".join(display_parts), "queued", validated, command, str(run_dir.relative_to(ROOT)), utc_now())
    run_dir.mkdir(parents=True, exist_ok=True)
    reference_path = ROOT / definition.reference_script if definition.reference_script else None
    legacy_source_records = [
        {"id": legacy_id, "script": source, "sha256": content_fingerprint(ROOT / source)}
        for legacy_id, source in zip(definition.legacy_ids, definition.legacy_sources)
        if (ROOT / source).is_file()
    ]
    (run_dir / "reproducibility.json").write_text(json.dumps({
        "run_id": run_id,
        "strategy": definition.id,
        "strategy_script": definition.script,
        "strategy_sha256": content_fingerprint(ROOT / definition.script),
        "reference_script": definition.reference_script,
        "reference_strategy_sha256": content_fingerprint(reference_path) if reference_path else None,
        "consolidated_legacy_sources": legacy_source_records,
        "chart": chart_metadata(CHARTS[primary_chart_id]),
        "charts": [chart_metadata(CHARTS[item]) for item in selected_chart_ids],
        "session": get_session(selected_session).public() if selected_session else None,
        "dataset_identity": file_fingerprint(CHARTS[primary_chart_id].path_1m()),
        "dataset_sha256": content_fingerprint(CHARTS[primary_chart_id].path_1m()),
        "dataset_identities": {item: file_fingerprint(CHARTS[item].path_1m()) for item in selected_chart_ids},
        "dataset_sha256s": {item: content_fingerprint(CHARTS[item].path_1m()) for item in selected_chart_ids},
        "parameters": validated,
        "created_at": record.created_at,
    }, indent=2))
    with LOCK:
        RUNS[run_id] = record
        persist(record)
    EXECUTOR.submit(execute_run, run_id)
    return serialize_run(record)


@app.get("/api/runs")
def list_runs(limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    with LOCK:
        values = sorted(RUNS.values(), key=lambda run: run.created_at, reverse=True)
        limit, offset = max(1, min(limit, 500)), max(0, offset)
        return [serialize_run(run, include_log=False) for run in values[offset:offset + limit]]


@app.get("/api/runs/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
    with LOCK:
        record = RUNS.get(run_id)
        if not record: raise HTTPException(404, "Run not found")
        return serialize_run(record)


@app.get("/api/runs/{run_id}/revisions")
def get_run_revisions(run_id: str) -> list[dict[str, Any]]:
    if run_id not in RUNS:
        raise HTTPException(404, "Run not found")
    return REPOSITORY.revisions(run_id)


@app.get("/api/runs/{run_id}/files/{file_path:path}")
def get_artifact(run_id: str, file_path: str) -> FileResponse:
    record = RUNS.get(run_id)
    if not record: raise HTTPException(404, "Run not found")
    base = (ROOT / record.output_dir).resolve()
    target = (base / file_path).resolve()
    if not target.is_relative_to(base) or not target.is_file() or target.name == "dashboard_run.json":
        raise HTTPException(404, "Artifact not found")
    return FileResponse(target)


@app.get("/api/runs/{run_id}/preview/{file_path:path}")
def preview_artifact(run_id: str, file_path: str, limit: int = 100) -> dict[str, Any]:
    record = RUNS.get(run_id)
    if not record: raise HTTPException(404, "Run not found")
    base = (ROOT / record.output_dir).resolve()
    target = (base / file_path).resolve()
    if not target.is_relative_to(base) or not target.is_file() or target.name == "dashboard_run.json":
        raise HTTPException(404, "Artifact not found")
    limit = max(1, min(limit, 500))
    if target.suffix.lower() == ".csv":
        with target.open(newline="", errors="replace") as handle:
            reader = csv.DictReader(handle)
            rows = [row for _, row in zip(range(limit), reader)]
            return {"kind": "table", "columns": reader.fieldnames or [], "rows": rows, "truncated": target.stat().st_size > 0 and len(rows) == limit}
    if target.suffix.lower() == ".json":
        return {"kind": "json", "value": json.loads(target.read_text())}
    if target.suffix.lower() in {".md", ".txt", ".log"}:
        return {"kind": "text", "value": target.read_text(errors="replace")[:MAX_LOG_CHARS]}
    raise HTTPException(415, "Preview is available for CSV, JSON, Markdown, and text files")
