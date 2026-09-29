"""Replay the frozen Expanded ES/NQ overnight baselines on September 2026 data.

This creates standalone evidence. It does not alter the frozen Expanded campaign,
the Workbench database, or the combined-portfolio catalog.
"""

from __future__ import annotations

from datetime import date
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from strategy_engine.data import session_bars  # noqa: E402
from strategy_engine.sessions import SESSIONS  # noqa: E402
from strategy_engine.strategies.session_drift import (  # noqa: E402
    SessionDriftConfig,
    run as drift,
)


CAMPAIGN = ROOT / "reports/expanded-search-2026-09-16"
REPORT = ROOT / "reports/combined-es-nq-refresh-2026-09-29/expanded"
FIRST_DATE = "2026-09-01"
BOUNDARY_DATE = "2026-08-31"
DATA_UPDATE_REPORTS = {
    "ES": ROOT / "reports/es-data-update-2026-09-29/result.json",
    "NQ": ROOT / "reports/nq-data-update-2026-09-29/result.json",
}
CATALOG_IDS = {
    "ES": "f24587940b6c8c81c877",
    "NQ": "3b3d1cfec7aac292801c",
}
SESSION = SESSIONS["globex-overnight"]
MINUTE = pd.Timedelta(minutes=1)


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def source_hashes(plan: dict) -> dict[str, dict[str, str | bool]]:
    names = (
        "strategy_engine/accounting.py",
        "strategy_engine/data.py",
        "strategy_engine/sessions.py",
        "strategy_engine/strategies/session_drift.py",
    )
    result = {}
    for name in names:
        frozen = plan["source_hashes"][name.replace("/", "\\")]
        current = sha256(ROOT / name)
        result[name] = {"frozen": frozen, "current": current, "matches_frozen": frozen == current}
    # The minute loader was optimized after the campaign. August trade parity
    # below checks the behavior that matters for this exact configuration.
    for name, hashes in result.items():
        if name != "strategy_engine/data.py" and not hashes["matches_frozen"]:
            raise RuntimeError(f"Frozen campaign source changed: {name}")
    return result


def registered_dataset(symbol: str, catalog: dict) -> tuple[dict, dict]:
    receipt = load_json(DATA_UPDATE_REPORTS[symbol])
    assert receipt["status"] == "complete" and receipt["workbench_registration_verified"]
    dataset = next(
        item for item in catalog["datasets"] if item["id"] == receipt["updated_dataset_id"]
    )
    original = next(
        item for item in catalog["datasets"] if item["id"] == receipt["base_dataset_id"]
    )
    assert dataset["symbol"] == original["symbol"] == symbol
    assert dataset["query"]["symbols"] == original["query"]["symbols"] == [f"{symbol}.v.0"]
    assert dataset["query"]["schema"] == original["query"]["schema"] == "ohlcv-1m"
    assert dataset["tick_size"] == original["tick_size"]
    assert dataset["point_value"] == original["point_value"]
    path = Path(dataset["path"])
    if sha256(path) != dataset["checksum"]:
        raise RuntimeError(f"Registered {symbol} bars fail their checksum")
    return dataset, receipt


def old_catalog_mark(symbol: str) -> tuple[float, dict]:
    folder = ROOT / "data/workbench/collective"
    index = load_json(folder / "index.json")
    item = next(row for row in index["items"] if row["id"] == CATALOG_IDS[symbol])
    assert item["symbol"] == symbol and item["source"] == "Expanded"
    assert item["end"] == BOUNDARY_DATE
    series_path = folder / item["series_file"]
    assert sha256(series_path) == item["checksum"]
    series = load_json(series_path)
    mark = next(row for row in series["daily"] if row["date"] == BOUNDARY_DATE)
    return float(mark["pnl"]), {
        "catalog_generated_at": index["generated_at"],
        "catalog_series_file": item["series_file"],
        "catalog_series_checksum": item["checksum"],
    }


def cost_config(dataset: dict, plan: dict) -> SessionDriftConfig:
    assert plan["capital"] == 100_000
    assert plan["costs"] == (
        "One full-size contract; $1.25/side plus one tick/side, "
        "represented as equivalent round-trip cost ticks."
    )
    tick = float(dataset["tick_size"])
    point = float(dataset["point_value"])
    return SessionDriftConfig(cost_ticks=2 + 2.5 / (tick * point))


def compare_frozen_august(symbol: str, bars: pd.DataFrame, dataset: dict, config: SessionDriftConfig) -> int:
    replay, _ = drift(
        bars.loc[bars.session_date.between("2026-08-01", BOUNDARY_DATE)],
        symbol=symbol,
        tick_size=dataset["tick_size"],
        point_value=dataset["point_value"],
        config=config,
    )
    frozen_path = (
        CAMPAIGN
        / "runs"
        / f"2026__overnight-session__{symbol}__1m__globex-overnight__baseline"
        / "trades.csv"
    )
    frozen = pd.read_csv(frozen_path)
    frozen = frozen.loc[frozen.session_date.between("2026-08-01", BOUNDARY_DATE)].reset_index(drop=True)
    replay = replay.reset_index(drop=True)
    if len(frozen) != len(replay):
        raise RuntimeError(f"{symbol} August parity failed: trade counts differ")
    for column in ("entry_time", "exit_time", "session_id", "session_date", "symbol", "side", "quantity", "reason"):
        if frozen[column].astype(str).tolist() != replay[column].astype(str).tolist():
            raise RuntimeError(f"{symbol} August parity failed: {column}")
    for column in ("entry", "exit", "gross_pnl", "cost", "net_pnl"):
        np.testing.assert_allclose(frozen[column], replay[column], rtol=0, atol=1e-8)
    return len(replay)


def eligible_sessions(bars: pd.DataFrame, dataset: dict) -> tuple[list[str], list[dict]]:
    last_day = pd.Timestamp(dataset["last"]).tz_convert(SESSION.timezone).date().isoformat()
    groups = {key: day for key, day in bars.groupby("session_date", sort=True)}
    checks = []
    complete = []
    for day in pd.bdate_range(FIRST_DATE, last_day):
        session_date = day.date().isoformat()
        expected_open = pd.Timestamp(SESSION.open_datetime(date.fromisoformat(session_date)))
        expected_close = pd.Timestamp(SESSION.close_datetime(date.fromisoformat(session_date)))
        expected = pd.date_range(expected_open, expected_close - MINUTE, freq=MINUTE)
        observed = groups.get(session_date)
        if observed is None or observed.empty:
            checks.append({"session_date": session_date, "complete": False, "reason": "no bars"})
            continue
        missing = expected.difference(observed.index)
        exact_endpoints = observed.index[0] == expected_open and observed.index[-1] == expected_close - MINUTE
        valid = exact_endpoints and observed.index.is_unique and observed.index.is_monotonic_increasing
        checks.append({
            "session_date": session_date,
            "complete": bool(valid),
            "reason": "complete endpoints" if valid else "missing session boundary",
            "expected_open_utc": expected_open.tz_convert("UTC").isoformat(),
            "expected_close_utc": expected_close.tz_convert("UTC").isoformat(),
            "first_bar_utc": observed.index[0].tz_convert("UTC").isoformat(),
            "last_bar_utc": observed.index[-1].tz_convert("UTC").isoformat(),
            "observed_minutes": len(observed),
            "internal_missing_minutes_utc": [stamp.tz_convert("UTC").isoformat() for stamp in missing],
        })
        if valid:
            complete.append(session_date)
    if not complete or complete[0] != FIRST_DATE:
        raise RuntimeError("The first new overnight session is incomplete")
    if any(not row["complete"] for row in checks[:-1]):
        raise RuntimeError("An incomplete session occurs before the last available session")
    return complete, checks


def utc_marked_daily(
    source: pd.DataFrame, trades: pd.DataFrame, last_session: str, point_value: float
) -> tuple[float, dict[str, float]]:
    # Match the original Expanded importer: UTC date-end source closes and
    # half the recorded round-trip cost while a position is still open.
    prices = source.close.groupby(source.index.floor("D")).last()
    prices = prices.loc[BOUNDARY_DATE:last_session]
    if BOUNDARY_DATE not in prices.index.strftime("%Y-%m-%d"):
        raise RuntimeError("No UTC close for the boundary date")
    marks: dict[str, float] = {}
    entries = pd.to_datetime(trades.entry_time, utc=True)
    exits = pd.to_datetime(trades.exit_time, utc=True)
    for timestamp, close in prices.items():
        cutoff = timestamp + pd.Timedelta(days=1)
        closed = trades.loc[exits < cutoff, "net_pnl"].sum()
        active = trades.loc[(entries < cutoff) & (exits >= cutoff)]
        if len(active) > 1:
            raise RuntimeError("The frozen overnight configuration has overlapping positions")
        open_pnl = 0.0
        if len(active):
            row = active.iloc[0]
            direction = 1 if row.side == "long" else -1
            open_pnl = direction * (float(close) - float(row.entry)) * point_value - float(row.cost) / 2
        marks[timestamp.strftime("%Y-%m-%d")] = round(float(closed + open_pnl), 8)
    boundary = marks.pop(BOUNDARY_DATE)
    daily = {}
    previous = boundary
    for day, mark in marks.items():
        daily[day] = round(mark - previous, 8)
        previous = mark
    if not daily or list(daily)[-1] != last_session:
        raise RuntimeError("Marked dates do not reach the final complete session")
    if abs(boundary + sum(daily.values()) - trades.net_pnl.sum()) > 1e-6:
        raise RuntimeError("Boundary correction and marked daily P&L do not reconcile")
    return boundary, daily


def run_symbol(symbol: str, plan: dict, dataset_catalog: dict, hashes: dict) -> dict:
    dataset, receipt = registered_dataset(symbol, dataset_catalog)
    source = pd.read_parquet(
        dataset["path"],
        columns=["open", "high", "low", "close", "volume"],
        filters=[("ts_event", ">=", pd.Timestamp("2026-07-30", tz="UTC"))],
    )
    if source.empty or not source.index.is_unique or not source.index.is_monotonic_increasing:
        raise RuntimeError(f"Invalid {symbol} source timestamps")
    if str(source.index.tz) != "UTC" or not np.isfinite(source[["open", "high", "low", "close"]]).all().all():
        raise RuntimeError(f"Invalid {symbol} source OHLC")
    bars = session_bars(source, SESSION, "1m")
    config = cost_config(dataset, plan)
    august_parity_trades = compare_frozen_august(symbol, bars, dataset, config)
    complete, checks = eligible_sessions(bars.loc[bars.session_date >= FIRST_DATE], dataset)
    last_session = complete[-1]
    selected_bars = bars.loc[bars.session_date.between(FIRST_DATE, last_session)]
    trades, signals = drift(
        selected_bars,
        symbol=symbol,
        tick_size=dataset["tick_size"],
        point_value=dataset["point_value"],
        config=config,
    )
    if len(trades) != len(complete) or not trades.session_date.tolist() == complete:
        raise RuntimeError(f"{symbol} replay did not create one trade per complete session")
    if not (trades.reason == "session_close").all() or not (trades.quantity == 1).all():
        raise RuntimeError(f"{symbol} replay departed from the frozen one-contract session-close rules")
    if not np.allclose(trades.gross_pnl - trades.cost, trades.net_pnl, rtol=0, atol=1e-8):
        raise RuntimeError(f"{symbol} trade ledger does not reconcile")
    for row in trades.itertuples():
        day = selected_bars.loc[selected_bars.session_date == row.session_date]
        expected_close = pd.Timestamp(SESSION.close_datetime(date.fromisoformat(row.session_date)))
        if pd.Timestamp(row.entry_time) != day.index[0].tz_convert("UTC"):
            raise RuntimeError(f"{symbol} entry timing mismatch")
        if pd.Timestamp(row.exit_time) != expected_close.tz_convert("UTC"):
            raise RuntimeError(f"{symbol} exit timing mismatch")
    boundary_delta, daily = utc_marked_daily(source, trades, last_session, float(dataset["point_value"]))
    prior_mark, prior_source = old_catalog_mark(symbol)
    normalized = [
        {
            "entry": row.entry_time,
            "exit": row.exit_time,
            "pnl": round(float(row.net_pnl), 8),
            "quantity": int(row.quantity),
            "cost": round(float(row.cost), 8),
            "exit_reason": row.reason,
        }
        for row in trades.itertuples()
    ]
    folder = REPORT / symbol
    folder.mkdir(parents=True, exist_ok=True)
    trades.to_csv(folder / "trades.csv", index=False)
    signals.to_csv(folder / "signals.csv", index=False)
    pd.DataFrame([{"date": day, "pnl": value} for day, value in daily.items()]).to_csv(
        folder / "daily.csv", index=False
    )
    write_json(folder / "sessions.json", checks)
    extension = {
        "catalog_id": CATALOG_IDS[symbol],
        "key": f"overnight-session__{symbol}__1m__globex-overnight",
        "symbol": symbol,
        "start": FIRST_DATE,
        "end": last_session,
        "trades": normalized,
        "daily": daily,
        "boundary_correction": {
            "date": BOUNDARY_DATE,
            "prior_pnl": round(prior_mark, 8),
            "delta_pnl": round(boundary_delta, 8),
            "corrected_pnl": round(prior_mark + boundary_delta, 8),
        },
        "dataset_id": dataset["id"],
        "dataset_checksum": dataset["checksum"],
        "source_hashes": hashes,
        "validation": {
            "august_frozen_trade_parity": august_parity_trades,
            "complete_overnight_sessions": len(complete),
            "excluded_incomplete_sessions": [row["session_date"] for row in checks if not row["complete"]],
            "internal_missing_trade_minutes": sum(len(row.get("internal_missing_minutes_utc", [])) for row in checks if row["complete"]),
            "gross_pnl": round(float(trades.gross_pnl.sum()), 8),
            "cost": round(float(trades.cost.sum()), 8),
            "net_pnl": round(float(trades.net_pnl.sum()), 8),
            "marked_reconciliation_error": round(boundary_delta + sum(daily.values()) - float(trades.net_pnl.sum()), 8),
            "notes": [
                "Complete means the first 18:00 and last 05:59 New York one-minute bars are present; internal no-trade minutes are listed in sessions.json.",
                "The final incomplete NQ overnight session is excluded, including its open exposure.",
                "Boundary correction is the incremental UTC Aug 31 open-position mark absent from the frozen sleeve; it does not replace that day's original P&L.",
                "This is a frozen-rule historical replay, not a new evaluation or live signal.",
            ],
        },
        "provenance": {
            "frozen_campaign_plan": str((CAMPAIGN / "PLAN.json").relative_to(ROOT)),
            "frozen_campaign_plan_sha256": sha256(CAMPAIGN / "PLAN.json"),
            "frozen_campaign_selections": str((CAMPAIGN / "FROZEN_SELECTIONS.json").relative_to(ROOT)),
            "frozen_campaign_selections_sha256": sha256(CAMPAIGN / "FROZEN_SELECTIONS.json"),
            "dataset_update_report": str(DATA_UPDATE_REPORTS[symbol].relative_to(ROOT)),
            "dataset_update_report_sha256": sha256(DATA_UPDATE_REPORTS[symbol]),
            "dataset_first_utc": dataset["first"],
            "dataset_last_utc": dataset["last"],
            "dataset_query": dataset["query"],
            "original_dataset_id": receipt["base_dataset_id"],
            "original_catalog": prior_source,
            "replay_script": str(Path(__file__).relative_to(ROOT)),
            "replay_script_sha256": sha256(Path(__file__)),
            "cost_ticks": config.cost_ticks,
            "capital_usd": plan["capital"],
            "session": SESSION.public(),
        },
    }
    write_json(folder / "extension.json", extension)
    artifacts = ["trades.csv", "signals.csv", "daily.csv", "sessions.json", "extension.json"]
    write_json(folder / "manifest.json", {name: sha256(folder / name) for name in artifacts})
    return {
        "symbol": symbol,
        "start": FIRST_DATE,
        "end": last_session,
        "trades": len(trades),
        "net_pnl": round(float(trades.net_pnl.sum()), 8),
        "boundary_delta_pnl": round(boundary_delta, 8),
        "incomplete_sessions_excluded": extension["validation"]["excluded_incomplete_sessions"],
        "dataset_id": dataset["id"],
        "extension": str((folder / "extension.json").relative_to(ROOT)),
    }


def main() -> None:
    plan = load_json(CAMPAIGN / "PLAN.json")
    selections = load_json(CAMPAIGN / "FROZEN_SELECTIONS.json")["selections"]
    for symbol in DATA_UPDATE_REPORTS:
        expected = f"overnight-session__{symbol}__1m__globex-overnight"
        assert any(item["key"] == expected for item in selections), f"{symbol} was not frozen"
    hashes = source_hashes(plan)
    dataset_catalog = load_json(ROOT / "data/workbench/datasets/catalog.json")
    REPORT.mkdir(parents=True, exist_ok=True)
    summary = [run_symbol(symbol, plan, dataset_catalog, hashes) for symbol in DATA_UPDATE_REPORTS]
    write_json(REPORT / "result.json", {
        "purpose": "Standalone extension of frozen Expanded overnight ES/NQ baselines",
        "results": summary,
        "catalog_modified": False,
        "frozen_campaign_modified": False,
    })
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
