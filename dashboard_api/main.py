from __future__ import annotations

import csv
import json
import re
import subprocess
import sys
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from .charts import CHARTS, ROOT, chart_metadata, content_fingerprint, file_fingerprint


RUNS_ROOT = ROOT / "reports" / "dashboard_runs"
RUNS_ROOT.mkdir(parents=True, exist_ok=True)
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
    data_mode: Literal["snd", "one-minute", "five-minute"]


COMMON_DATES = (
    Parameter("start", "Start date", "date", None, "Leave blank to use the script default.", "--start"),
    Parameter("end", "End date", "date", None, "Inclusive analysis end date.", "--end"),
)

STRATEGIES: dict[str, StrategyDefinition] = {
    "snd-baseline": StrategyDefinition(
        "snd-baseline", "SND baseline", "Supply-and-demand zone baseline across selected chart timeframes.",
        "scripts/mnq/SND_baseline_backtest.py", "--output-dir",
        (
            Parameter("timeframes", "Chart timeframes", "multiselect", ["1h", "4h", "1d"], "One or more source chart timeframes.", "--timeframes", ("1h", "4h", "1d"), required=True),
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
        ("MNQ", "NQ", "ES", "YM", "CL"), "snd",
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
        ("MNQ", "NQ", "ES", "YM"), "one-minute",
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
        ("MNQ", "NQ", "ES", "YM", "CL"), "five-minute",
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
        ("MNQ", "NQ", "ES", "YM", "CL"), "one-minute",
    ),
    "build-timeframes": StrategyDefinition(
        "build-timeframes", "Build chart timeframes", "Resample a one-minute archive for downstream chart/backtest use.",
        "scripts/mnq/build_mnq_timeframes.py", "--output-dir",
        (
            Parameter("timeframes", "Chart timeframes", "multiselect", ["5m", "30m", "1h", "4h", "1d"], "Bars to generate.", "--timeframes", ("5m", "30m", "1h", "4h", "1d"), required=True),
            Parameter("keep_partial_final", "Keep partial final bar", "boolean", False, "Keep the final incomplete candle.", "--keep-partial-final"),
        ),
        ("MNQ", "NQ", "ES", "YM", "CL"), "one-minute",
    ),
}


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


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    strategy_id: str
    chart_id: str
    parameters: dict[str, Any] = Field(default_factory=dict)


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
    (output / "run.json").write_text(json.dumps(serialize_run(record), indent=2, default=str))


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


def build_command(definition: StrategyDefinition, chart_id: str, supplied: dict[str, Any], run_dir: Path) -> tuple[list[str], dict[str, Any]]:
    if chart_id not in definition.charts:
        raise ValueError(f"{definition.name} is not approved for {chart_id}")
    chart = CHARTS.get(chart_id)
    if not chart or not chart.path_1m().is_file():
        raise ValueError(f"Chart dataset {chart_id} is unavailable")
    known = {p.key for p in definition.parameters}
    unknown = set(supplied) - known
    if unknown:
        raise ValueError(f"Unknown parameters: {', '.join(sorted(unknown))}")
    command = [sys.executable, str(ROOT / definition.script), definition.output_arg, str(run_dir)]
    if definition.data_mode == "snd":
        command.extend(["--one-minute", str(chart.path_1m()), "--timeframe-dir", str(ROOT / chart.timeframe_dir)])
    elif definition.data_mode == "one-minute":
        input_arg = "--input" if definition.id == "build-timeframes" else "--data" if definition.id == "opening-pullback" else "--one-minute"
        command.extend([input_arg, str(chart.path_1m())])
    else:
        five_minute = chart.path_for_timeframe("5m")
        if not five_minute.is_file():
            raise ValueError(f"{chart_id} has no prepared five-minute dataset")
        command.extend(["--data", str(five_minute)])
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
        if not path.is_file() or path.name == "run.json": continue
        relative = path.relative_to(run_dir).as_posix()
        result.append({"name": relative, "kind": artifact_kind(path), "size": path.stat().st_size, "url": f"/api/runs/{run_id}/files/{relative}"})
    return result


def load_summary(run_dir: Path) -> dict[str, Any] | None:
    candidates = [run_dir / "summary.json", *run_dir.glob("*summary*.json")]
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
            persist(record)
    except Exception as exc:
        with LOCK:
            record.status = "failed"
            record.finished_at = utc_now()
            record.log = f"{type(exc).__name__}: {exc}"
            persist(record)


def load_existing_runs() -> None:
    for path in RUNS_ROOT.glob("*/run.json"):
        try:
            raw = json.loads(path.read_text())
            if raw.get("status") in {"queued", "running"}:
                raw["status"] = "failed"
                raw["log"] = (raw.get("log") or "") + "\nAPI restarted before this run finished."
                raw["finished_at"] = utc_now()
            RUNS[raw["id"]] = RunRecord(**raw)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            continue


load_existing_runs()
app = FastAPI(title="Strategy Health Dashboard API", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"], allow_methods=["*"], allow_headers=["*"])


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "python": sys.executable, "strategies": len(STRATEGIES)}


@app.get("/api/strategies")
def strategy_catalog() -> list[dict[str, Any]]:
    return [{"id": d.id, "name": d.name, "description": d.description, "charts": list(d.charts), "parameters": [public_parameter(p) for p in d.parameters]} for d in STRATEGIES.values()]


@app.get("/api/charts")
def chart_catalog() -> list[dict[str, Any]]:
    return [chart_metadata(chart) for chart in CHARTS.values()]


@app.post("/api/runs", status_code=202)
def create_run(request: RunRequest) -> dict[str, Any]:
    definition = STRATEGIES.get(request.strategy_id)
    if not definition:
        raise HTTPException(404, "Unknown strategy")
    run_id = f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
    run_dir = RUNS_ROOT / run_id
    try:
        command, validated = build_command(definition, request.chart_id, request.parameters, run_dir)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    validated = {"chart_id": request.chart_id, **validated}
    record = RunRecord(run_id, definition.id, f"{definition.name} · {request.chart_id}", "queued", validated, command, str(run_dir.relative_to(ROOT)), utc_now())
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "reproducibility.json").write_text(json.dumps({
        "run_id": run_id,
        "strategy": definition.id,
        "strategy_script": definition.script,
        "strategy_sha256": content_fingerprint(ROOT / definition.script),
        "chart": chart_metadata(CHARTS[request.chart_id]),
        "dataset_identity": file_fingerprint(CHARTS[request.chart_id].path_1m()),
        "dataset_sha256": content_fingerprint(CHARTS[request.chart_id].path_1m()),
        "parameters": validated,
        "created_at": record.created_at,
    }, indent=2))
    with LOCK:
        RUNS[run_id] = record
        persist(record)
    EXECUTOR.submit(execute_run, run_id)
    return serialize_run(record)


@app.get("/api/runs")
def list_runs() -> list[dict[str, Any]]:
    with LOCK:
        values = sorted(RUNS.values(), key=lambda run: run.created_at, reverse=True)
        return [serialize_run(run, include_log=False) for run in values[:50]]


@app.get("/api/runs/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
    with LOCK:
        record = RUNS.get(run_id)
        if not record: raise HTTPException(404, "Run not found")
        return serialize_run(record)


@app.get("/api/runs/{run_id}/files/{file_path:path}")
def get_artifact(run_id: str, file_path: str) -> FileResponse:
    record = RUNS.get(run_id)
    if not record: raise HTTPException(404, "Run not found")
    base = (ROOT / record.output_dir).resolve()
    target = (base / file_path).resolve()
    if not target.is_relative_to(base) or not target.is_file() or target.name == "run.json":
        raise HTTPException(404, "Artifact not found")
    return FileResponse(target)


@app.get("/api/runs/{run_id}/preview/{file_path:path}")
def preview_artifact(run_id: str, file_path: str, limit: int = 100) -> dict[str, Any]:
    record = RUNS.get(run_id)
    if not record: raise HTTPException(404, "Run not found")
    base = (ROOT / record.output_dir).resolve()
    target = (base / file_path).resolve()
    if not target.is_relative_to(base) or not target.is_file(): raise HTTPException(404, "Artifact not found")
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
