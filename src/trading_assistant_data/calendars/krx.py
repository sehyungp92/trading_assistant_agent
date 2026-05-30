"""KRX equities calendar with explicit holiday-file requirement."""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import yaml

from .core import CalendarDefinition


CALENDAR_ID = "krx_equities_v1"


def calendar_definition(holidays_path: Path | None = None) -> CalendarDefinition:
    holidays = _load_holidays(holidays_path) if holidays_path else set()
    return CalendarDefinition(
        calendar_id=CALENDAR_ID,
        timezone="Asia/Seoul",
        session_open="09:00",
        session_close="15:20",
        weekdays=(0, 1, 2, 3, 4),
        holidays=frozenset(holidays),
        version="v1",
        market="krx_equity",
        source="KRX market closing calendar; no weekday-only fallback is authoritative",
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


def _load_holidays(path: Path) -> set[date]:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    holidays: set[date] = set()
    for dates in payload.values():
        if not isinstance(dates, list):
            continue
        for item in dates:
            holidays.add(date.fromisoformat(str(item)))
    return holidays

