# Relay /health Endpoint Enrichment (#21)

**Target repo:** `swing_trader` (deployed on VPS)
**Target files:** `relay/db/store.py`, `relay/app.py`

This document describes the changes needed in the swing_trader relay to support
proactive relay health monitoring from the trading_assistant orchestrator (#27).

## Current State

The relay `/health` endpoint returns only:

```json
{"status": "ok", "pending_events": 5}
```

This is insufficient for detecting degraded relay states (stale bots, disk
pressure, queue buildup per bot).

## Required Changes

### 1. `relay/db/store.py` — Add `get_stats()` method

Add a new method to the `EventStore` class:

```python
def get_stats(self) -> dict:
    """Return detailed stats for the /health endpoint."""
    conn = self._connect()
    try:
        # Per-bot pending counts
        rows = conn.execute(
            "SELECT bot_id, COUNT(*) as cnt FROM events WHERE acked = 0 GROUP BY bot_id"
        ).fetchall()
        per_bot_pending = {r["bot_id"]: r["cnt"] for r in rows}

        # Last event timestamp per bot
        rows = conn.execute(
            "SELECT bot_id, MAX(received_at) as last_at FROM events GROUP BY bot_id"
        ).fetchall()
        last_event_per_bot = {r["bot_id"]: r["last_at"] for r in rows}

        # Oldest pending event age
        row = conn.execute(
            "SELECT MIN(received_at) as oldest FROM events WHERE acked = 0"
        ).fetchone()
        oldest_pending_age_seconds = 0.0
        if row and row["oldest"]:
            try:
                oldest_dt = datetime.fromisoformat(row["oldest"])
                if oldest_dt.tzinfo is None:
                    oldest_dt = oldest_dt.replace(tzinfo=timezone.utc)
                oldest_pending_age_seconds = (
                    datetime.now(timezone.utc) - oldest_dt
                ).total_seconds()
            except (ValueError, TypeError):
                pass

        # DB file size
        import os
        try:
            db_size_bytes = os.path.getsize(self.db_path)
        except OSError:
            db_size_bytes = 0

        return {
            "per_bot_pending": per_bot_pending,
            "last_event_per_bot": last_event_per_bot,
            "oldest_pending_age_seconds": oldest_pending_age_seconds,
            "db_size_bytes": db_size_bytes,
        }
    finally:
        conn.close()
```

**Required imports** (add at top of file if not present):
```python
from datetime import datetime, timezone  # already imported
import os
```

### 2. `relay/app.py` — Enrich `/health` endpoint + track uptime

#### a. Track start time

In `create_relay_app()`, capture the start time in the factory scope:

```python
def create_relay_app(...) -> FastAPI:
    import time as _time
    _start_mono = _time.monotonic()
    # ... rest of factory
```

#### b. Replace `/health` endpoint

Replace the existing `/health` handler:

```python
@app.get("/health")
async def health():
    """Enriched health check endpoint."""
    pending = store.count_pending()
    stats = store.get_stats()
    uptime = _time.monotonic() - _start_mono
    return {
        "status": "ok",
        "pending_events": pending,
        "per_bot_pending": stats["per_bot_pending"],
        "last_event_per_bot": stats["last_event_per_bot"],
        "oldest_pending_age_seconds": stats["oldest_pending_age_seconds"],
        "db_size_bytes": stats["db_size_bytes"],
        "uptime_seconds": round(uptime, 1),
    }
```

## Expected Response Format

After these changes, `GET /health` returns:

```json
{
    "status": "ok",
    "pending_events": 8,
    "per_bot_pending": {"bot-a": 5, "bot-b": 3},
    "last_event_per_bot": {"bot-a": "2026-03-06T14:30:00+00:00", "bot-b": "2026-03-06T12:15:00+00:00"},
    "oldest_pending_age_seconds": 120.5,
    "db_size_bytes": 1048576,
    "uptime_seconds": 3600.0
}
```

## Testing

Add tests to `relay/tests/test_relay.py` (or a new `test_relay_health.py`):

1. **Enriched fields present** — verify all new keys in response
2. **Per-bot counts correct** — insert events for 2 bots, check counts
3. **Last event timestamps** — verify most recent timestamp per bot
4. **Oldest age** — insert old un-acked event, verify age > 0
5. **Empty DB returns zeros** — no events → `per_bot_pending: {}`, `oldest_pending_age_seconds: 0`

## Compatibility

The enriched `/health` response is a strict superset of the current response.
The `status` and `pending_events` fields remain unchanged, so the orchestrator's
existing health checks will continue to work while the new fields are adopted
by `MonitoringCheck.check_relay_health()` in trading_assistant.
