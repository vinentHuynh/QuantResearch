from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from .sessions import SessionDefinition


TIMEFRAMES: dict[str, pd.Timedelta] = {
    "1m": pd.Timedelta(minutes=1),
    "5m": pd.Timedelta(minutes=5),
    "15m": pd.Timedelta(minutes=15),
    "30m": pd.Timedelta(minutes=30),
    "1h": pd.Timedelta(hours=1),
    "4h": pd.Timedelta(hours=4),
    "1d": pd.Timedelta(days=1),
}


def load_ohlcv(path: Path, start: str | None = None, end: str | None = None) -> pd.DataFrame:
    frame = pd.read_parquet(path)
    if not isinstance(frame.index, pd.DatetimeIndex):
        timestamp = next(
            (name for name in ("ts_event", "event_time", "timestamp", "datetime", "date") if name in frame),
            None,
        )
        if timestamp is None:
            raise ValueError(f"{path} has no DatetimeIndex or timestamp column")
        frame = frame.set_index(pd.to_datetime(frame.pop(timestamp), utc=True))
    elif frame.index.tz is None:
        frame.index = frame.index.tz_localize("UTC")
    else:
        frame.index = frame.index.tz_convert("UTC")
    frame.columns = [str(column).lower() for column in frame.columns]
    required = {"open", "high", "low", "close"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"{path} is missing OHLC columns: {sorted(missing)}")
    frame = frame.sort_index()[~frame.index.duplicated(keep="last")]
    if start:
        frame = frame.loc[frame.index >= pd.Timestamp(start, tz="UTC")]
    if end:
        frame = frame.loc[frame.index < pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=1)]
    if frame.empty:
        raise ValueError("No bars remain in the selected date window")
    return frame


def _trading_date(timestamp: pd.Timestamp, session: SessionDefinition) -> date | None:
    local_time = timestamp.time().replace(tzinfo=None)
    local_date = timestamp.date()
    if session.crosses_midnight:
        if local_time >= session.opens_at:
            return local_date + timedelta(days=session.trading_date_offset_days)
        if local_time < session.closes_at:
            return local_date - timedelta(days=1) + timedelta(days=session.trading_date_offset_days)
        return None
    if session.opens_at <= local_time < session.closes_at:
        return local_date + timedelta(days=session.trading_date_offset_days)
    return None


def session_bars(frame: pd.DataFrame, session: SessionDefinition, timeframe: str) -> pd.DataFrame:
    """Filter to a session and aggregate bars from that session's local open."""

    if timeframe not in TIMEFRAMES:
        raise ValueError(f"Unsupported timeframe: {timeframe}")
    local = frame.tz_convert(session.timezone)
    grouped_rows: list[pd.DataFrame] = []
    session_dates = pd.Series(
        [_trading_date(timestamp, session) for timestamp in local.index],
        index=local.index,
        dtype="object",
    )
    local = local.loc[session_dates.notna()].copy()
    session_dates = session_dates.loc[local.index]
    aggregation: dict[str, str] = {"open": "first", "high": "max", "low": "min", "close": "last"}
    if "volume" in local.columns:
        aggregation["volume"] = "sum"
    width = TIMEFRAMES[timeframe]
    for trading_date, day in local.groupby(session_dates, sort=True):
        if trading_date.weekday() >= 5:
            continue
        session_open = pd.Timestamp(session.open_datetime(trading_date))
        session_close = pd.Timestamp(session.close_datetime(trading_date))
        day = day.loc[(day.index >= session_open) & (day.index < session_close)]
        if day.empty:
            continue
        bucket = ((day.index - session_open) // width).astype(int)
        resampled = day.groupby(bucket).agg(aggregation)
        resampled.index = pd.DatetimeIndex(
            [session_open + int(number) * width for number in resampled.index],
            name="event_time",
        )
        resampled["availability_time"] = [
            min(timestamp + width, session_close) for timestamp in resampled.index
        ]
        resampled["session_id"] = session.id
        resampled["session_date"] = trading_date.isoformat()
        grouped_rows.append(resampled)
    if not grouped_rows:
        columns = [*aggregation, "availability_time", "session_id", "session_date"]
        return pd.DataFrame(columns=columns, index=pd.DatetimeIndex([], tz=session.zone, name="event_time"))
    return pd.concat(grouped_rows).sort_index()
