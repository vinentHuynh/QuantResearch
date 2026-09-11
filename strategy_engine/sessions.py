from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class SessionDefinition:
    id: str
    name: str
    timezone: str
    open_time: str
    close_time: str
    calendar: str = "weekday"
    trading_date_offset_days: int = 0

    @property
    def zone(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    @property
    def opens_at(self) -> time:
        return time.fromisoformat(self.open_time)

    @property
    def closes_at(self) -> time:
        return time.fromisoformat(self.close_time)

    @property
    def crosses_midnight(self) -> bool:
        return self.closes_at <= self.opens_at

    def open_datetime(self, trading_date: date) -> datetime:
        start_date = trading_date - timedelta(days=self.trading_date_offset_days)
        return datetime.combine(start_date, self.opens_at, self.zone)

    def close_datetime(self, trading_date: date) -> datetime:
        start_date = trading_date - timedelta(days=self.trading_date_offset_days)
        close_date = start_date + timedelta(days=1) if self.crosses_midnight else start_date
        return datetime.combine(close_date, self.closes_at, self.zone)

    def public(self) -> dict[str, str | bool | int]:
        return {**asdict(self), "crosses_midnight": self.crosses_midnight}


SESSIONS: dict[str, SessionDefinition] = {
    "new-york-rth": SessionDefinition(
        id="new-york-rth",
        name="New York RTH",
        timezone="America/New_York",
        open_time="09:30",
        close_time="16:00",
    ),
    "london": SessionDefinition(
        id="london",
        name="London",
        timezone="Europe/London",
        open_time="08:00",
        close_time="16:30",
    ),
    "asia": SessionDefinition(
        id="asia",
        name="Asia (Tokyo)",
        timezone="Asia/Tokyo",
        open_time="09:00",
        close_time="15:00",
    ),
    "globex-overnight": SessionDefinition(
        id="globex-overnight",
        name="Globex overnight",
        timezone="America/New_York",
        open_time="18:00",
        close_time="06:00",
        trading_date_offset_days=1,
    ),
    "full-trading-day": SessionDefinition(
        id="full-trading-day",
        name="Full trading day",
        timezone="America/New_York",
        open_time="18:00",
        close_time="17:00",
        trading_date_offset_days=1,
    ),
}


def get_session(session_id: str) -> SessionDefinition:
    try:
        return SESSIONS[session_id]
    except KeyError as exc:
        raise ValueError(f"Unknown session: {session_id}") from exc
