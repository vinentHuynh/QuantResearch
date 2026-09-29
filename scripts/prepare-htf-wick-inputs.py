"""Build higher-timeframe wick-study bars from a registered Workbench 1m series.

The full trading day is the repository's 18:00–17:00 New York session.
Timestamps label bar opens in UTC. Mixed-contract and source-edge sessions are
retained with explicit flags so an analysis can exclude them without losing
the audit trail.

Example:
    .venv/Scripts/python.exe scripts/prepare-htf-wick-inputs.py \
        --input data/workbench/datasets/<version>/bars.parquet \
        --symbol ES --output-dir reports/htf-wick/inputs/ES \
        --timeframes 1h,4h,1d
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from strategy_engine.sessions import get_session  # noqa: E402


SESSION = get_session("full-trading-day")
TIMEFRAMES = {"1h": pd.Timedelta(hours=1), "4h": pd.Timedelta(hours=4), "1d": None}
OHLCV = ["open", "high", "low", "close", "volume"]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def selected_timeframes(value: str) -> list[str]:
    names = [part.strip().lower() for part in value.split(",") if part.strip()]
    if not names or set(names) - TIMEFRAMES.keys():
        raise ValueError("--timeframes must contain one or more of 1h,4h,1d")
    return list(dict.fromkeys(names))


def load_registered_source(path: Path, symbol: str) -> tuple[pd.DataFrame, dict, str]:
    if not path.is_file():
        raise FileNotFoundError(path)
    manifest_path = path.parent / "dataset.json"
    if not manifest_path.is_file():
        raise ValueError(f"Registered Workbench dataset.json missing beside {path}")
    record = json.loads(manifest_path.read_text(encoding="utf-8"))
    if record.get("symbol", "").upper() != symbol.upper() or record.get("timeframe") != "1m":
        raise ValueError("Dataset symbol/timeframe does not match --symbol and 1m")
    digest = sha256(path)
    if record.get("checksum") != digest:
        raise ValueError("Source checksum differs from registered dataset.json")

    frame = pd.read_parquet(path)
    if not isinstance(frame.index, pd.DatetimeIndex):
        if "ts_event" not in frame:
            raise ValueError("Source needs a DatetimeIndex or ts_event column")
        frame = frame.set_index(pd.to_datetime(frame.pop("ts_event"), utc=True))
    if frame.index.tz is None or frame.empty:
        raise ValueError("Source timestamps must be timezone-aware and nonempty")
    frame.index = frame.index.tz_convert("UTC")
    if not frame.index.is_monotonic_increasing or frame.index.has_duplicates:
        raise ValueError("Source timestamps must be ordered and unique")
    if (frame.index.asi8 % 60_000_000_000 != 0).any():
        raise ValueError("Source timestamps must label whole-minute opens")
    required = set(OHLCV + ["instrument_id"])
    if required - set(frame):
        raise ValueError(f"Source missing columns: {sorted(required - set(frame))}")
    if frame[list(required)].isna().any().any():
        raise ValueError("Source has missing OHLCV or instrument IDs")
    prices = frame[["open", "high", "low", "close"]]
    if (not np.isfinite(prices.to_numpy(dtype=float)).all()
            or (frame.volume < 0).any()
            or (frame.high < prices.max(axis=1)).any()
            or (frame.low > prices.min(axis=1)).any()):
        raise ValueError("Source has invalid OHLCV")
    if record.get("rows") != len(frame):
        raise ValueError("Source row count differs from registered dataset.json")
    return frame, record, digest


def session_rows(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DatetimeIndex, pd.DatetimeIndex]:
    """Keep repository full-day minutes and return each minute's session open/date."""
    local = frame.index.tz_convert(SESSION.timezone)
    minutes = local.hour * 60 + local.minute
    opening = SESSION.opens_at.hour * 60 + SESSION.opens_at.minute
    closing = SESSION.closes_at.hour * 60 + SESSION.closes_at.minute
    allowed = (minutes >= opening) | (minutes < closing)
    wall_dates = local.tz_localize(None).normalize()
    trading_dates = wall_dates + pd.to_timedelta((minutes >= opening).astype(int), unit="D")
    allowed &= trading_dates.dayofweek < 5

    chosen = frame.loc[allowed, OHLCV + ["instrument_id"]].copy()
    if chosen.empty:
        raise ValueError("No minutes fall in the full trading day")
    dates = trading_dates[allowed]
    # The session definition owns this 18:00 anchor; localizing each wall-clock
    # open handles the UTC offset on both sides of daylight-saving changes.
    naive_open = dates - pd.Timedelta(days=SESSION.trading_date_offset_days)
    naive_open += pd.Timedelta(minutes=opening)
    starts = naive_open.tz_localize(SESSION.timezone).tz_convert("UTC")
    return chosen, starts, dates


def aggregate(frame: pd.DataFrame, timeframe: str, symbol: str) -> pd.DataFrame:
    if timeframe not in TIMEFRAMES:
        raise ValueError(f"Unsupported timeframe: {timeframe}")
    chosen, session_starts, trading_dates = session_rows(frame)
    if timeframe == "1d":
        buckets = session_starts
    else:
        elapsed = chosen.index - session_starts
        buckets = session_starts + (elapsed // TIMEFRAMES[timeframe]) * TIMEFRAMES[timeframe]

    bars = chosen.groupby(buckets, sort=True).agg(
        open=("open", "first"), high=("high", "max"), low=("low", "min"),
        close=("close", "last"), volume=("volume", "sum"),
        minute_count=("close", "count"),
        first_instrument_id=("instrument_id", "first"),
        instrument_id=("instrument_id", "last"),
        contract_count=("instrument_id", "nunique"),
    )
    bars.index = pd.DatetimeIndex(bars.index, name="ts_event").tz_convert("UTC")
    bars["is_roll_bar"] = bars.contract_count > 1
    bars["is_roll_transition"] = bars.first_instrument_id.ne(bars.instrument_id.shift())
    bars.iloc[0, bars.columns.get_loc("is_roll_transition")] = False
    bars = bars.drop(columns="first_instrument_id")
    bars["symbol"] = symbol.upper()

    # Source-edge sessions can be cut off by an archive's request interval;
    # later studies should exclude these even if a surviving bar looks complete.
    first_date, last_date = trading_dates[0], trading_dates[-1]
    local_bars = bars.index.tz_convert(SESSION.timezone)
    local_dates = local_bars.tz_localize(None).normalize()
    local_minutes = local_bars.hour * 60 + local_bars.minute
    session_dates = local_dates + pd.to_timedelta((local_minutes >= 18 * 60).astype(int), unit="D")
    bars["session_date"] = session_dates.strftime("%Y-%m-%d")
    bars["is_source_edge_session"] = (session_dates == first_date) | (session_dates == last_date)
    bars = bars[
        OHLCV + ["minute_count", "instrument_id", "contract_count", "is_roll_bar", "symbol",
                 "is_roll_transition", "session_date", "is_source_edge_session"]
    ]

    if bars[OHLCV].isna().any().any() or (bars.high < bars[["open", "close", "low"]].max(axis=1)).any():
        raise ValueError(f"Invalid aggregated {timeframe} OHLCV")
    if not bars.index.is_unique or not bars.index.is_monotonic_increasing:
        raise ValueError(f"Invalid aggregated {timeframe} timestamps")
    return bars


def build(input_path: Path, symbol: str, output_dir: Path, timeframes: list[str]) -> dict:
    frame, source_record, source_digest = load_registered_source(input_path, symbol)
    outputs = {name: output_dir / f"candles_{name}.parquet" for name in timeframes}
    manifest_path = output_dir / "resample_manifest.json"
    existing = [str(path) for path in [*outputs.values(), manifest_path] if path.exists()]
    if existing:
        raise FileExistsError(f"Refusing to overwrite existing outputs: {existing}")
    manifest = {
        "schema_version": 1,
        "symbol": symbol.upper(),
        "source": {
            "path": str(input_path.resolve()), "dataset_id": source_record.get("id"),
            "sha256": source_digest, "rows": len(frame),
            "first_bar": frame.index[0].isoformat(), "last_bar": frame.index[-1].isoformat(),
            "registered_manifest": str((input_path.parent / "dataset.json").resolve()),
        },
        "session": SESSION.public(),
        "timestamp_label": "bar_open_utc",
        "roll_policy": "Retain and flag mixed-contract bars; also flag first bar after an instrument change.",
        "minute_count_policy": "Observed traded one-minute rows, not proof of a complete session.",
        "timeframes": {},
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, path in outputs.items():
        bars = aggregate(frame, name, symbol)
        temporary = path.with_suffix(".parquet.tmp")
        bars.to_parquet(temporary)
        temporary.replace(path)
        manifest["timeframes"][name] = {
            "path": str(path.resolve()), "sha256": sha256(path), "rows": len(bars),
            "first_bar": bars.index[0].isoformat(), "last_bar": bars.index[-1].isoformat(),
            "roll_bars": int(bars.is_roll_bar.sum()),
            "roll_transitions": int(bars.is_roll_transition.sum()),
            "source_edge_bars": int(bars.is_source_edge_session.sum()),
        }
    temporary_manifest = manifest_path.with_suffix(".json.tmp")
    temporary_manifest.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    temporary_manifest.replace(manifest_path)
    return manifest


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--timeframes", default="1h,4h,1d")
    args = parser.parse_args(argv)
    manifest = build(args.input, args.symbol, args.output_dir, selected_timeframes(args.timeframes))
    print(json.dumps({"symbol": manifest["symbol"], "timeframes": manifest["timeframes"]}, indent=2))


if __name__ == "__main__":
    main()
