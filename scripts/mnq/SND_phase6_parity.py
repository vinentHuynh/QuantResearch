"""Compare a TradingView Phase 6 chart-data export with the frozen Python ledger."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REFERENCE = ROOT / "reports" / "SND_phase6" / "pine_parity_reference_2026.csv"
PARITY_START = pd.Timestamp("2026-01-01 23:00:00", tz="UTC")
PARITY_END = pd.Timestamp("2026-05-30 21:00:00", tz="UTC")


def find_column(frame: pd.DataFrame, needle: str) -> str:
    matches = [column for column in frame.columns if needle.lower() in column.lower()]
    if len(matches) != 1:
        raise ValueError(f"Expected one column containing {needle!r}; found {matches}")
    return matches[0]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tradingview_csv", type=Path)
    parser.add_argument("--reference", type=Path, default=DEFAULT_REFERENCE)
    parser.add_argument("--output", type=Path, default=ROOT / "reports" / "SND_phase6" / "parity_result.json")
    args = parser.parse_args()

    raw = pd.read_csv(args.tradingview_csv)
    reference = pd.read_csv(args.reference)
    time_column = find_column(raw, "time")
    entry_column = find_column(raw, "p6 · entry")
    exit_column = find_column(raw, "p6 · exit")
    direction_column = find_column(raw, "p6 · direction")
    raw[time_column] = pd.to_datetime(raw[time_column], utc=True)
    reference["entry_time"] = pd.to_datetime(reference.entry_time, utc=True)
    reference["exit_time"] = pd.to_datetime(reference.exit_time, utc=True)

    entries = raw.loc[raw[entry_column].notna(), [time_column, entry_column, direction_column]].reset_index(drop=True)
    exits = raw.loc[raw[exit_column].notna(), [time_column, exit_column]].reset_index(drop=True)
    observed = pd.DataFrame({
        "entry_time": entries[time_column],
        "entry_price": entries[entry_column],
        "direction": np.where(entries[direction_column] > 0, "long", "short"),
    })
    observed["exit_time"] = exits[time_column]
    observed["exit_price"] = exits[exit_column]
    # Phase 6 runs continuously for paper-forward collection. Restrict the
    # exported all-time signals to the frozen historical comparison window.
    observed = observed.loc[
        observed.entry_time.between(PARITY_START, PARITY_END)
    ].reset_index(drop=True)

    paired = min(len(reference), len(observed))
    ref = reference.iloc[:paired].reset_index(drop=True)
    obs = observed.iloc[:paired].reset_index(drop=True)
    mismatches = {
        "entry_time": int((ref.entry_time != obs.entry_time).sum()),
        "entry_price": int((~np.isclose(ref.entry_price, obs.entry_price, atol=0.01)).sum()),
        "direction": int((ref.direction != obs.direction).sum()),
        "exit_time": int((ref.exit_time != obs.exit_time).sum()),
        "exit_price": int((~np.isclose(ref.exit_price, obs.exit_price, atol=0.01)).sum()),
    }
    passed = len(reference) == len(observed) and not any(mismatches.values())
    result = {
        "status": "pass" if passed else "fail",
        "reference_trades": len(reference),
        "observed_entries": len(entries),
        "observed_exits": len(exits),
        "paired_trades": paired,
        "mismatches": mismatches,
        "note": "A failure can reflect Pine logic or a feed/continuous-contract mismatch; inspect the first mismatch before changing rules.",
    }
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if passed else 1)


if __name__ == "__main__":
    main()
