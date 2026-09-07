"""Evaluate the locked Phase 6 paper-forward log without changing its rules."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LOG = ROOT / "reports" / "sarah_phase6" / "paper_forward_log.csv"
DEFAULT_OUTPUT = ROOT / "reports" / "sarah_phase6" / "paper_forward_result.json"
TZ = "America/Chicago"


def as_bool(series: pd.Series) -> pd.Series:
    values = series.astype(str).str.strip().str.lower()
    return values.map({"true": True, "1": True, "yes": True, "false": False, "0": False, "no": False})


def clustered_mean_ci(frame: pd.DataFrame, repetitions: int = 10_000) -> tuple[float, float]:
    local_day = pd.to_datetime(frame.signal_time_utc, utc=True).dt.tz_convert(TZ).dt.date
    daily = frame.assign(day=local_day).groupby("day").net_pnl.agg(["sum", "size"])
    if daily.empty:
        return float("nan"), float("nan")
    rng = np.random.default_rng(6006)
    samples = rng.integers(0, len(daily), size=(repetitions, len(daily)))
    pnl = daily["sum"].to_numpy()[samples].sum(axis=1)
    trades = daily["size"].to_numpy()[samples].sum(axis=1)
    means = pnl / trades
    return tuple(float(value) for value in np.quantile(means, [0.025, 0.975]))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", nargs="?", type=Path, default=DEFAULT_LOG)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    frame = pd.read_csv(args.log)
    if frame.empty:
        result = {"status": "not started", "signals": 0, "completed_trades": 0}
    else:
        recorded = as_bool(frame.executed)
        reconciliation = float(recorded.notna().mean())
        completed = frame.loc[recorded.eq(True) & frame.net_pnl.notna()].copy()
        completed["net_pnl"] = pd.to_numeric(completed.net_pnl)
        wins = completed.loc[completed.net_pnl > 0, "net_pnl"].sum()
        losses = -completed.loc[completed.net_pnl < 0, "net_pnl"].sum()
        pf = float(wins / losses) if losses > 0 else float("nan")
        ci_low, ci_high = clustered_mean_ci(completed)
        count = len(completed)
        gates_pass = count >= 500 and pf > 1 and ci_low > 0 and reconciliation >= 0.95
        status = "pass" if gates_pass else "final gate failed" if count >= 500 else "interim" if count >= 300 else "collecting"
        result = {
            "status": status,
            "signals": len(frame),
            "completed_trades": count,
            "signal_record_reconciliation": reconciliation,
            "net_profit_factor": pf,
            "mean_net_pnl": float(completed.net_pnl.mean()) if count else float("nan"),
            "clustered_bootstrap_95_ci_mean_net_pnl": [ci_low, ci_high],
            "interim_review_at": 300,
            "final_gate_at": 500,
        }
    args.output.write_text(json.dumps(result, indent=2, allow_nan=True) + "\n")
    print(json.dumps(result, indent=2, allow_nan=True))


if __name__ == "__main__":
    main()
