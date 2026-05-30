"""CME equity-index futures calendar approximation for manifest diagnostics."""

from __future__ import annotations

from datetime import date, datetime, timezone

from .core import CalendarDefinition


CALENDAR_ID = "cme_equity_index_futures_v1"


def calendar_definition() -> CalendarDefinition:
    return CalendarDefinition(
        calendar_id=CALENDAR_ID,
        timezone="America/Chicago",
        session_open="17:00",
        session_close="16:00",
        weekdays=(0, 1, 2, 3, 4),
        holidays=frozenset(
            {
                date(2026, 1, 1),
                date(2026, 1, 19),
                date(2026, 2, 16),
                date(2026, 4, 3),
                date(2026, 5, 25),
                date(2026, 6, 19),
                date(2026, 7, 3),
                date(2026, 9, 7),
                date(2026, 11, 26),
                date(2026, 12, 25),
            }
        ),
        version="v1",
        market="cme_futures",
        source="CME holiday policy seed; verify against final exchange calendar before authority",
        generated_at=datetime.now(timezone.utc).isoformat(),
    )

