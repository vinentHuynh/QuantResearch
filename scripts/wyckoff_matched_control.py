"""Read-only, approximate matched-entry control for one NQ Wyckoff fixed-hold run.

For each completed trade, compare its recorded net P&L with entries sampled from
the same local year, weekday, and chart-bar time. Controls keep the trade's
direction, quantity, holding-bar count, and recorded round-trip cost. They are
excluded near continuous-contract changes and the observed entry dates.

This is a timing comparison, not an independent strategy backtest or a formal
test of a trading edge. It does not match volatility, trend, or setup context.
It never changes Workbench records or writes an output file.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from uuid import UUID

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from strategy_engine.data import session_bars  # noqa: E402
from strategy_engine.sessions import get_session  # noqa: E402
from workbench.contract import checksum  # noqa: E402


def _load_run(run_id: str) -> tuple[dict, pd.DataFrame]:
    UUID(run_id)  # Also prevents using an arbitrary path as the run identifier.
    db = ROOT / "data/workbench/workbench.sqlite3"
    with sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True) as conn:
        row = conn.execute("SELECT body FROM records WHERE kind='run' AND id=?", (run_id,)).fetchone()
    if row is None:
        raise ValueError(f"Run {run_id} was not found")
    run = json.loads(row[0])
    request = run["input"]
    if run["status"] != "Succeeded" or request["strategy"]["id"] != "wyckoff-nq":
        raise ValueError("Expected a succeeded wyckoff-nq run")
    if request["dataset"]["symbol"] != "NQ" or request["parameters"]["exit_policy"] != "fixed_bars":
        raise ValueError("Expected NQ data and a fixed_bars exit policy")
    folder = ROOT / "data/workbench/runs" / run_id
    artifact = next(a for a in run["result"]["artifacts"] if a["name"] == "trades.csv")
    trade_path = folder / "trades.csv"
    if checksum(trade_path) != artifact["checksum"]:
        raise ValueError("The saved trades.csv checksum differs from the run record")
    return run, pd.read_csv(trade_path)


def _load_market(request: dict, roll_pad: pd.Timedelta) -> tuple[pd.DataFrame, np.ndarray]:
    start = pd.Timestamp(request["start"], tz="UTC") - max(roll_pad, pd.Timedelta(days=7))
    stop = pd.Timestamp(request["end"], tz="UTC") + pd.Timedelta(days=1) + max(roll_pad, pd.Timedelta(days=7))
    raw = pd.read_parquet(
        request["dataset"]["path"],
        filters=[("ts_event", ">=", start), ("ts_event", "<", stop)],
    )
    if raw.empty or "instrument_id" not in raw:
        raise ValueError("NQ minute bars or contract identifiers are missing")
    switch = raw.instrument_id.ne(raw.instrument_id.shift())
    switch.iloc[0] = False  # The first loaded row is not an observed roll.
    roll_ns = raw.index[switch].tz_convert("UTC").asi8
    bars = session_bars(raw, get_session(request["session"]), request["timeframe"])
    if bars.empty:
        raise ValueError("No chart bars were reconstructed")
    return bars, np.asarray(roll_ns, dtype=np.int64)


def _near_event(start_ns: np.ndarray, stop_ns: np.ndarray, event_ns: np.ndarray, pad_ns: int) -> np.ndarray:
    """True when any event is inside each [start-pad, stop+pad] interval."""
    left = np.searchsorted(event_ns, start_ns - pad_ns, side="left")
    right = np.searchsorted(event_ns, stop_ns + pad_ns, side="right")
    return right > left


def analyze(run_id: str, draws: int, seed: int, roll_pad_hours: float) -> dict:
    if draws < 100 or roll_pad_hours < 0:
        raise ValueError("draws must be at least 100 and roll_pad_hours nonnegative")
    run, trades = _load_run(run_id)
    request = run["input"]
    hold = int(request["parameters"]["holding_bars"])
    pad = pd.Timedelta(hours=roll_pad_hours)
    bars, roll_ns = _load_market(request, pad)
    entry_ns = bars.index.tz_convert("UTC").asi8
    ready_ns = pd.DatetimeIndex(bars.availability_time).tz_convert("UTC").asi8
    scored_start = pd.Timestamp(request["start"], tz="UTC").value
    scored_stop = (pd.Timestamp(request["end"], tz="UTC") + pd.Timedelta(days=1)).value
    valid = (entry_ns >= scored_start) & (ready_ns < scored_stop)
    valid &= np.arange(len(bars)) + hold - 1 < len(bars)
    end_index = np.minimum(np.arange(len(bars)) + hold - 1, len(bars) - 1)
    valid &= ready_ns[end_index] < scored_stop
    valid &= ~_near_event(entry_ns, ready_ns[end_index], roll_ns, pad.value)

    completed = trades.loc[trades.exit_reason.eq("maximum holding bars")].copy()
    excluded_exit = len(trades) - len(completed)
    if completed.empty:
        raise ValueError("No completed fixed-hold trades exist in this run")
    actual_ns = pd.to_datetime(completed.entry_time, utc=True).astype("int64").to_numpy()
    actual_index = np.searchsorted(entry_ns, actual_ns)
    if np.any(actual_index >= len(bars)) or np.any(entry_ns[actual_index] != actual_ns):
        raise ValueError("A recorded trade entry was not found in reconstructed chart bars")
    expected_exit = ready_ns[actual_index + hold - 1]
    saved_exit = pd.to_datetime(completed.exit_time, utc=True).astype("int64").to_numpy()
    if np.any(expected_exit != saved_exit):
        raise ValueError("A recorded trade does not match the requested holding-bar exit")
    if not np.allclose(bars.open.to_numpy()[actual_index], completed.entry.to_numpy(), atol=0.01):
        raise ValueError("Recorded entry prices differ from reconstructed chart opens")
    if not np.allclose(bars.close.to_numpy()[actual_index + hold - 1], completed.exit.to_numpy(), atol=0.01):
        raise ValueError("Recorded exit prices differ from reconstructed chart closes")

    actual_good = valid[actual_index]
    excluded_roll = int((~actual_good).sum())
    completed = completed.loc[actual_good].reset_index(drop=True)
    actual_index = actual_index[actual_good]
    if completed.empty:
        raise ValueError("All actual trades are roll-adjacent or outside complete chart windows")

    # Avoid using the observed setup's nearby bars as randomized controls.
    exclusion_pad = pd.Timedelta(hours=48).value
    eligible = valid & ~_near_event(entry_ns, entry_ns, np.sort(actual_ns), exclusion_pad)
    local = bars.index
    years = local.year.to_numpy()
    weekdays = local.dayofweek.to_numpy()
    minute_of_day = (local.hour * 60 + local.minute).to_numpy()
    opens = bars.open.to_numpy(dtype=float)
    closes = bars.close.to_numpy(dtype=float)
    point = float(request["dataset"]["point_value"])
    rng = np.random.default_rng(seed)
    sampled = np.zeros(draws, dtype=float)
    groups: list[dict] = []

    for row, index in zip(completed.itertuples(index=False), actual_index):
        match = eligible & (years == years[index]) & (minute_of_day == minute_of_day[index])
        strict = match & (weekdays == weekdays[index])
        pool = np.flatnonzero(strict if strict.sum() >= 20 else match)
        if len(pool) < 10:
            raise ValueError(f"Too few time/year-matched controls for entry {row.entry_time}: {len(pool)}")
        quantity = int(row.quantity)
        cost = float(row.cost)
        outcomes = quantity * (closes[pool + hold - 1] - opens[pool]) * point - cost
        picks = rng.integers(0, len(outcomes), size=draws)
        sampled += outcomes[picks] / len(completed)
        groups.append({
            "entry_time": row.entry_time,
            "direction": "long" if quantity > 0 else "short",
            "actual_net": round(float(row.net_pnl), 2),
            "matching": "same year, weekday and local chart-bar time" if len(strict.nonzero()[0]) >= 20 else "same year and local chart-bar time",
            "eligible_control_entries": len(pool),
            "control_mean_net": round(float(outcomes.mean()), 2),
        })

    actual_mean = float(completed.net_pnl.mean())
    control_mean = float(sampled.mean())
    return {
        "run_id": run_id,
        "design": "Approximate randomized entry-time control; same NQ chart bars, direction, quantity, holding bars and round-trip cost; local year/weekday/time matched where available; no setup-context or volatility matching.",
        "seed": seed,
        "draws": draws,
        "timeframe": request["timeframe"],
        "holding_bars": hold,
        "roll_pad_hours": roll_pad_hours,
        "recorded_trades": len(trades),
        "included_trades": len(completed),
        "excluded_nonstandard_exits": excluded_exit,
        "excluded_roll_adjacent_actual_trades": excluded_roll,
        "actual_mean_net_per_trade": round(actual_mean, 2),
        "control_mean_net_per_trade": round(control_mean, 2),
        "actual_minus_control_mean": round(actual_mean - control_mean, 2),
        "control_mean_95pct_randomization_range": [round(float(v), 2) for v in np.quantile(sampled, [0.025, 0.975])],
        "fraction_randomized_means_at_least_actual": round(float(np.mean(sampled >= actual_mean)), 4),
        "match_groups": groups,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_id", help="UUID of a succeeded wyckoff-nq fixed_bars run")
    parser.add_argument("--draws", type=int, default=10000)
    parser.add_argument("--seed", type=int, default=20260928)
    parser.add_argument("--roll-pad-hours", type=float, default=48.0)
    args = parser.parse_args()
    print(json.dumps(analyze(args.run_id, args.draws, args.seed, args.roll_pad_hours), indent=2))


if __name__ == "__main__":
    main()
