from __future__ import annotations

import argparse
import ast
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

from .strategies.relative_value import LegEconomics
from .strategies.trend import TrendConfig, run as run_trend


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "reports" / "strategy_parity" / "latest.json"
TRACKED_EVIDENCE = ROOT / "strategy_engine" / "parity_evidence.json"
TREND_SOURCE = "strategy_engine/strategies/trend.py"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def extract_function(path: Path, function_name: str) -> Callable[..., Any]:
    """Compile one exact pure function from a dependency-heavy legacy script."""

    tree = ast.parse(path.read_text(), filename=str(path))
    matches = [
        node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name
    ]
    if len(matches) != 1 or isinstance(matches[0], ast.AsyncFunctionDef):
        raise ValueError(f"Expected one synchronous {function_name} function in {path}")
    module = ast.Module(body=[matches[0]], type_ignores=[])
    ast.fix_missing_locations(module)
    namespace: dict[str, Any] = {"np": np, "pd": pd}
    exec(compile(module, str(path), "exec"), namespace)
    return namespace[function_name]


def frozen_daily_fixture(rows: int = 180) -> tuple[pd.Series, pd.DataFrame, str]:
    index = pd.date_range(
        "2022-01-03 18:00", periods=rows, freq="B", tz="America/New_York",
        name="event_time",
    )
    step = np.arange(rows, dtype=float)
    values = 100.0 + 0.06 * step + 3.2 * np.sin(step / 7.0) + 1.4 * np.cos(step / 19.0)
    close = pd.Series(values, index=index, name="close")
    bars = pd.DataFrame({
        "open": close.shift(1).fillna(close.iloc[0]),
        "high": close + 0.5,
        "low": close - 0.5,
        "close": close,
        "session_id": "full-trading-day",
        "session_date": [timestamp.date().isoformat() for timestamp in index],
    }, index=index)
    fixture_hash = hashlib.sha256(close.to_csv().encode()).hexdigest()
    return close, bars, fixture_hash


def compare_series(
    expected: pd.Series,
    actual: pd.Series,
    *,
    tolerance: float = 1e-12,
) -> dict[str, Any]:
    expected_values = expected.astype(float).to_numpy()
    actual_values = actual.reindex(expected.index).astype(float).to_numpy()
    matched = np.isclose(expected_values, actual_values, atol=tolerance, rtol=0.0, equal_nan=True)
    finite = np.isfinite(expected_values) & np.isfinite(actual_values)
    error = np.abs(expected_values[finite] - actual_values[finite])
    return {
        "passed": bool(matched.all()),
        "rows": int(len(expected_values)),
        "mismatches": int((~matched).sum()),
        "max_absolute_error": float(error.max()) if len(error) else 0.0,
        "tolerance": tolerance,
    }


def canonical_held_direction(positions: pd.DataFrame, index: pd.DatetimeIndex) -> pd.Series:
    values = positions.copy()
    values.index = pd.to_datetime(values.pop("event_time"), utc=True)
    direction = np.sign(values.quantity.astype(float)).rename("canonical_direction")
    return direction.reindex(index).shift(1).fillna(0.0)


def canonical_returns(pnl: pd.DataFrame, index: pd.DatetimeIndex, capital: float) -> pd.Series:
    result = pd.Series(0.0, index=index, name="canonical_return")
    if pnl.empty:
        return result
    marked = pnl.assign(event_time=pd.to_datetime(pnl.period_end, utc=True)).groupby("event_time").net_pnl.sum()
    return marked.div(capital).reindex(index).fillna(0.0).rename("canonical_return")


def moving_average_case(close: pd.Series, bars: pd.DataFrame, fixture_hash: str) -> dict[str, Any]:
    legacy_path = ROOT / "scripts" / "es_nq" / "es_nq_backtest.py"
    legacy = extract_function(legacy_path, "sleeve_returns")
    lookback = 20
    capital = 100_000.0
    expected_return = legacy(close, lookback).rename("legacy_return")
    expected_direction = (close > close.rolling(lookback).mean()).astype(float).shift(1).fillna(0.0)
    pnl, _, positions = run_trend(
        bars,
        symbol="FROZEN",
        economics=LegEconomics(tick_size=0.25, point_value=1.0),
        config=TrendConfig("moving-average-trend", lookback=lookback, capital=capital, cost_ticks=0.0),
    )
    index = bars.index.tz_convert("UTC")
    comparisons = {
        "held_direction": compare_series(expected_direction.set_axis(index), canonical_held_direction(positions, index)),
        "daily_gross_return": compare_series(expected_return.set_axis(index), canonical_returns(pnl, index, capital)),
    }
    return parity_record(
        legacy_id="es-nq-trend",
        catalog_id="moving-average-trend",
        legacy_path=legacy_path,
        fixture_hash=fixture_hash,
        coverage="signal_and_return",
        comparisons=comparisons,
        blockers=[
            "Legacy portfolio parity still requires simultaneous ES/NQ sleeves and compounded NAV comparison.",
            "Legacy research used SPX/NDX cash proxies; the canonical runner uses selected Databento futures charts.",
        ],
    )


def multi_speed_case(close: pd.Series, bars: pd.DataFrame, fixture_hash: str) -> dict[str, Any]:
    legacy_path = ROOT / "scripts" / "cme" / "cme_time_series_momentum_backtest.py"
    legacy = extract_function(legacy_path, "build_market_model")
    lookback = 12
    lookbacks = (4, 12, 24, 48)
    model = legacy(close, lookbacks, 12, 0.20, 2.0)
    _, signals, positions = run_trend(
        bars,
        symbol="FROZEN",
        economics=LegEconomics(tick_size=0.25, point_value=1.0),
        config=TrendConfig("multi-speed-momentum", lookback=lookback, capital=100_000.0, cost_ticks=0.0),
    )
    index = bars.index.tz_convert("UTC")
    signal_values = signals.copy()
    signal_values.index = pd.to_datetime(signal_values.pop("event_time"), utc=True)
    actual_score = signal_values.level.astype(float).reindex(index)
    expected_score = model.score.set_axis(index)
    expected_direction = np.sign(model.score.shift(1).set_axis(index)).fillna(0.0)
    comparisons = {
        "lagged_four_horizon_score": compare_series(expected_score, actual_score),
        "held_direction": compare_series(expected_direction, canonical_held_direction(positions, index)),
    }
    return parity_record(
        legacy_id="cme-tsmom",
        catalog_id="multi-speed-momentum",
        legacy_path=legacy_path,
        fixture_hash=fixture_hash,
        coverage="signal",
        comparisons=comparisons,
        blockers=[
            "Canonical sizing is fixed-capital contract normalization; the legacy model targets point volatility.",
            "Legacy portfolio parity still requires its multi-market proxy universe and basis-point cost model.",
        ],
    )


def parity_record(
    *,
    legacy_id: str,
    catalog_id: str,
    legacy_path: Path,
    fixture_hash: str,
    coverage: str,
    comparisons: dict[str, dict[str, Any]],
    blockers: list[str],
) -> dict[str, Any]:
    canonical_path = ROOT / TREND_SOURCE
    return {
        "legacy_id": legacy_id,
        "catalog_id": catalog_id,
        "passed": all(item["passed"] for item in comparisons.values()),
        "coverage": coverage,
        "fixture": {"id": "deterministic-daily-trend-v1", "sha256": fixture_hash, "rows": 180},
        "legacy_source": str(legacy_path.relative_to(ROOT)),
        "legacy_sha256": sha256(legacy_path),
        "canonical_source": TREND_SOURCE,
        "canonical_sha256": sha256(canonical_path),
        "comparisons": comparisons,
        "full_parity_blockers": blockers,
    }


def run_suite() -> dict[str, Any]:
    close, bars, fixture_hash = frozen_daily_fixture()
    results = [
        moving_average_case(close, bars, fixture_hash),
        multi_speed_case(close, bars, fixture_hash),
    ]
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "harness": "strategy_engine/parity.py",
        "harness_sha256": sha256(Path(__file__)),
        "all_comparisons_passed": all(item["passed"] for item in results),
        "full_parity_verified": sum(item["passed"] and item["coverage"] == "full" for item in results),
        "partial_parity_verified": sum(item["passed"] and item["coverage"] != "full" for item in results),
        "results": results,
    }


def load_verified_evidence(root: Path = ROOT) -> dict[str, dict[str, Any]]:
    path = root / "strategy_engine" / "parity_evidence.json"
    if not path.is_file():
        return {}
    try:
        evidence = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    harness = root / str(evidence.get("harness", ""))
    if not harness.is_file() or evidence.get("harness_sha256") != sha256(harness):
        return {}
    verified: dict[str, dict[str, Any]] = {}
    for result in evidence.get("results", []):
        if not isinstance(result, dict) or not result.get("passed"):
            continue
        legacy = root / str(result.get("legacy_source", ""))
        canonical = root / str(result.get("canonical_source", ""))
        if (
            legacy.is_file()
            and canonical.is_file()
            and result.get("legacy_sha256") == sha256(legacy)
            and result.get("canonical_sha256") == sha256(canonical)
        ):
            verified[str(result["legacy_id"])] = result
    return verified


def main() -> None:
    parser = argparse.ArgumentParser(description="Run frozen legacy-to-canonical parity comparisons")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    report = run_suite()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    if not report["all_comparisons_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
