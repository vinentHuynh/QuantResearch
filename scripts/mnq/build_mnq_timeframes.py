"""Build session-aligned MNQ candles from the local Databento 1-minute archive.

The source is the volume-rolled MNQ.v.0 continuous series. Intraday and daily
bars are anchored to the CME equity-index futures session open at 18:00
America/New_York (17:00 America/Chicago). Output timestamps are bar-open times
stored in UTC.

Default outputs:

    data/mnq_dom_sample/full_history/ohlcv-resampled/candles_5m.parquet
    data/mnq_dom_sample/full_history/ohlcv-resampled/candles_30m.parquet
    data/mnq_dom_sample/full_history/ohlcv-resampled/candles_1h.parquet
    data/mnq_dom_sample/full_history/ohlcv-resampled/candles_4h.parquet
    data/mnq_dom_sample/full_history/ohlcv-resampled/candles_1d.parquet

Run from the repository root:

    .venv/bin/python scripts/mnq/build_mnq_timeframes.py
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT = (
    ROOT
    / "data"
    / "mnq_dom_sample"
    / "full_history"
    / "ohlcv-1m"
    / "candles_1m.parquet"
)
DEFAULT_OUTPUT_DIR = DEFAULT_INPUT.parents[1] / "ohlcv-resampled"
SESSION_TIMEZONE = "America/New_York"
SESSION_OFFSET = pd.Timedelta(hours=18)
ONE_MINUTE = pd.Timedelta(minutes=1)
OHLCV = ["open", "high", "low", "close", "volume"]

# Output name -> pandas resampling rule. These all begin at the 18:00 session
# anchor. For 5m/30m/1h that is also the ordinary wall-clock boundary.
TIMEFRAMES = {
    "5m": "5min",
    "30m": "30min",
    "1h": "1h",
    "4h": "4h",
    "1d": "1D",
}
TIMEFRAME_MINUTES = {"5m": 5, "30m": 30, "1h": 60, "4h": 240, "1d": 1440}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--timeframes",
        default=",".join(TIMEFRAMES),
        help=f"comma-separated subset of: {','.join(TIMEFRAMES)}",
    )
    parser.add_argument(
        "--keep-partial-final",
        action="store_true",
        help="retain the final candle even when the source request ends mid-bar",
    )
    return parser.parse_args()


def requested_timeframes(value: str) -> list[str]:
    names = [part.strip().lower() for part in value.split(",") if part.strip()]
    unknown = sorted(set(names) - TIMEFRAMES.keys())
    if unknown:
        raise ValueError(f"Unknown timeframes: {', '.join(unknown)}")
    if not names:
        raise ValueError("At least one timeframe is required")
    return list(dict.fromkeys(names))


def load_source(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"MNQ one-minute parquet not found: {path}")

    frame = pd.read_parquet(path).sort_index()
    missing = sorted(set(OHLCV) - set(frame.columns))
    if missing:
        raise ValueError(f"Source is missing columns: {', '.join(missing)}")
    if not isinstance(frame.index, pd.DatetimeIndex):
        raise ValueError("Source index must be a DatetimeIndex")
    if frame.index.tz is None:
        raise ValueError("Source timestamps must be timezone-aware")
    if frame.empty:
        raise ValueError("Source contains no rows")
    if frame.index.has_duplicates:
        raise ValueError("Source contains duplicate timestamps")
    if frame[OHLCV].isna().any().any():
        raise ValueError("Source contains missing OHLCV values")
    if (
        (frame["high"] < frame[["open", "close", "low"]].max(axis=1))
        | (frame["low"] > frame[["open", "close", "high"]].min(axis=1))
    ).any():
        raise ValueError("Source contains invalid OHLC ordering")

    return frame


def request_bounds(path: Path, frame: pd.DataFrame) -> tuple[pd.Timestamp, pd.Timestamp, str]:
    """Return the requested half-open source interval when job metadata exists."""
    job_path = path.parent / "job.json"
    if job_path.exists():
        job = json.loads(job_path.read_text())
        request = job.get("request", {})
        if request.get("start") and request.get("end"):
            return (
                pd.Timestamp(request["start"]).tz_convert("UTC"),
                pd.Timestamp(request["end"]).tz_convert("UTC"),
                str(job_path),
            )

    # A Databento OHLCV timestamp is the beginning of its one-minute interval.
    # This fallback is exact when the last requested minute contains a trade.
    return (
        frame.index.min().tz_convert("UTC"),
        frame.index.max().tz_convert("UTC") + ONE_MINUTE,
        "inferred from first/last source bar",
    )


def aggregate(frame: pd.DataFrame, rule: str) -> pd.DataFrame:
    local = frame.tz_convert(SESSION_TIMEZONE)
    aggregations: dict[str, Any] = {
        "open": ("open", "first"),
        "high": ("high", "max"),
        "low": ("low", "min"),
        "close": ("close", "last"),
        "volume": ("volume", "sum"),
        "minute_count": ("close", "count"),
    }
    if "instrument_id" in local.columns:
        aggregations["instrument_id"] = ("instrument_id", "last")
        aggregations["contract_count"] = ("instrument_id", "nunique")
    if "symbol" in local.columns:
        aggregations["symbol"] = ("symbol", "last")

    # Build buckets in local wall-clock time. Pandas' ordinary timezone-aware
    # resample uses elapsed-time bins, which makes a 4h grid drift by one hour
    # after DST. Removing the timezone while flooring keeps every session on
    # the intended 18:00, 22:00, 02:00, 06:00, 10:00, 14:00 ET grid.
    wall_clock = local.index.tz_localize(None)
    bucket_wall_clock = (wall_clock - SESSION_OFFSET).floor(rule) + SESSION_OFFSET
    buckets = bucket_wall_clock.tz_localize(
        SESSION_TIMEZONE, ambiguous="infer", nonexistent="shift_forward"
    )
    bars = local.groupby(buckets, sort=True).agg(**aggregations).copy()

    # Restore compact integer dtypes after aggregation.
    bars["volume"] = bars["volume"].astype("uint64")
    bars["minute_count"] = bars["minute_count"].astype("uint16")
    if "instrument_id" in bars:
        bars["instrument_id"] = bars["instrument_id"].astype("uint32")
        bars["contract_count"] = bars["contract_count"].astype("uint8")
        bars["is_roll_bar"] = bars["contract_count"] > 1

    bars.index.name = "ts_event"
    return bars.tz_convert("UTC")


def bar_ends(index: pd.DatetimeIndex, timeframe: str) -> pd.DatetimeIndex:
    local = index.tz_convert(SESSION_TIMEZONE)
    if timeframe == "1d":
        # DateOffset preserves the 18:00 local wall-clock anchor across DST.
        return (local + pd.DateOffset(days=1)).tz_convert("UTC")
    return index + pd.Timedelta(TIMEFRAMES[timeframe])


def validate_bars(bars: pd.DataFrame, timeframe: str) -> None:
    if bars.empty:
        raise ValueError(f"No {timeframe} bars were generated")
    if not bars.index.is_monotonic_increasing or bars.index.has_duplicates:
        raise ValueError(f"{timeframe} output timestamps are invalid")
    if bars[OHLCV].isna().any().any():
        raise ValueError(f"{timeframe} output contains missing OHLCV values")
    if (
        (bars["high"] < bars[["open", "close", "low"]].max(axis=1))
        | (bars["low"] > bars[["open", "close", "high"]].min(axis=1))
    ).any():
        raise ValueError(f"{timeframe} output contains invalid OHLC ordering")
    if not (bars["minute_count"] > 0).all():
        raise ValueError(f"{timeframe} output contains empty candles")

    local_wall_clock = bars.index.tz_convert(SESSION_TIMEZONE).tz_localize(None)
    shifted = local_wall_clock - SESSION_OFFSET
    minute_of_day = shifted.hour * 60 + shifted.minute
    if (minute_of_day % TIMEFRAME_MINUTES[timeframe] != 0).any():
        raise ValueError(f"{timeframe} output is not aligned to the 18:00 ET session")


def write_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_parquet(temporary)
    temporary.replace(path)


def main() -> None:
    args = parse_args()
    timeframes = requested_timeframes(args.timeframes)
    source = load_source(args.input)
    requested_start, requested_end, bounds_source = request_bounds(args.input, source)

    print(
        f"MNQ 1m: {len(source):,} bars | {source.index.min()} .. "
        f"{source.index.max()}"
    )
    print(f"Requested interval: [{requested_start}, {requested_end}) | {bounds_source}")
    print(f"Session anchor: 18:00 {SESSION_TIMEZONE}; output timestamps: UTC")

    manifest: dict[str, Any] = {
        "input": str(args.input),
        "source_rows": len(source),
        "source_first_bar": str(source.index.min()),
        "source_last_bar": str(source.index.max()),
        "requested_start": str(requested_start),
        "requested_end": str(requested_end),
        "session_timezone": SESSION_TIMEZONE,
        "session_start": "18:00",
        "timestamp_label": "bar_open",
        "output_timezone": "UTC",
        "timeframes": {},
    }

    for timeframe in timeframes:
        bars = aggregate(source, TIMEFRAMES[timeframe])
        partial_dropped = 0
        if not args.keep_partial_final:
            complete = bar_ends(bars.index, timeframe) <= requested_end
            partial_dropped = int((~complete).sum())
            bars = bars.loc[complete]

        validate_bars(bars, timeframe)
        output = args.output_dir / f"candles_{timeframe}.parquet"
        write_parquet(bars, output)
        roll_bars = int(bars.get("is_roll_bar", pd.Series(dtype=bool)).sum())
        manifest["timeframes"][timeframe] = {
            "rule": TIMEFRAMES[timeframe],
            "rows": len(bars),
            "first_bar": str(bars.index.min()),
            "last_bar": str(bars.index.max()),
            "partial_final_bars_dropped": partial_dropped,
            "roll_bars": roll_bars,
            "path": str(output),
        }
        print(
            f"{timeframe:>3}: {len(bars):>9,} bars | {bars.index.min()} .. "
            f"{bars.index.max()} | rolls={roll_bars} -> {output}"
        )

    manifest_path = args.output_dir / "resample_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Manifest -> {manifest_path}")


if __name__ == "__main__":
    main()
