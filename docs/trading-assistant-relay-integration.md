# Trading Assistant Relay Integration Changes

> Historical relay-integration note. Rows that mention `wfo_trigger` or
> `SPAWN_WFO` describe legacy wiring that has since been disabled; current
> strategy-learning triggers should use monthly validation.

**Target repo:** `trading_assistant`
**Target files:** `orchestrator/adapters/vps_receiver.py`, `orchestrator/orchestrator_brain.py`, `orchestrator/config.py`, `orchestrator/app.py`, `orchestrator/db/schema.sql`

This document describes the changes needed in the trading_assistant repo to fully
integrate with the swing_trader relay after the March 2026 relay hardening pass.
Two issues require attention: API key authentication on read endpoints, and
unhandled event types routed to LOG_UNKNOWN.

---

## Issue 1: VPSReceiver Needs `X-Api-Key` Header

### Background

The relay now supports optional API key authentication on its read and admin
endpoints. When the relay's `RELAY_API_KEY` environment variable is set:

- `GET /events` → requires `X-Api-Key` header, returns 401 without it
- `POST /ack` → requires `X-Api-Key` header, returns 401 without it
- `POST /admin/purge` → requires `X-Api-Key` header, returns 401 without it
- `GET /health` → remains unauthenticated (open for monitoring)
- `POST /events` (ingest) → unchanged, uses HMAC-SHA256 via `X-Signature`

The VPSReceiver currently sends **no authentication headers** on `GET /events`
or `POST /ack`. If the relay operator enables `RELAY_API_KEY`, every poll will
fail with 401 and the entire event pipeline silently stops flowing.

### Current State

File: `orchestrator/adapters/vps_receiver.py`

```python
# Line 68-70 — no auth headers
async with self._make_client() as client:
    resp = await client.get("/events", params=params)
    resp.raise_for_status()

# Line 97 — no auth headers
await client.post("/ack", json={"watermark": last_event_id})
```

File: `orchestrator/config.py`

```python
# Line 14 — relay_hmac_secret exists but is unused in VPSReceiver
relay_hmac_secret: str = ""
# No relay_api_key field
```

### Required Changes

#### 1. `orchestrator/config.py` — Add `relay_api_key` field

Add a new config field alongside the existing relay settings:

```python
class AppConfig(BaseModel):
    relay_url: str = ""
    relay_hmac_secret: str = ""
    relay_api_key: str = ""          # ← NEW: API key for GET /events, POST /ack
    # ... rest of fields
```

In `from_env()`, load from environment:

```python
relay_api_key=os.environ.get("RELAY_API_KEY", ""),
```

#### 2. `orchestrator/adapters/vps_receiver.py` — Accept and send API key

Update the constructor to accept `api_key`:

```python
class VPSReceiver:
    def __init__(
        self,
        relay_url: str,
        local_queue: EventQueue,
        watermark_key: str = "relay",
        timeout: float = 30.0,
        min_poll_seconds: int = 10,
        max_poll_seconds: int = 300,
        *,
        api_key: str = "",                       # ← NEW
        latency_tracker=None,
        _client_factory: Callable[[], Any] | None = None,
    ) -> None:
        self._relay_url = relay_url
        self._api_key = api_key                  # ← NEW
        # ... rest unchanged
```

Update `_make_client()` to include the header on every request:

```python
def _make_client(self) -> httpx.AsyncClient:
    if self._client_factory:
        return self._client_factory()
    headers = {}
    if self._api_key:
        headers["X-Api-Key"] = self._api_key
    return httpx.AsyncClient(
        base_url=self._relay_url,
        timeout=self._timeout,
        headers=headers,
    )
```

This approach injects the header at the client level so `GET /events`,
`POST /ack`, and any future endpoints automatically include it.

#### 3. `orchestrator/app.py` — Wire the new parameter

Update the VPSReceiver instantiation (around line 187):

```python
if config.relay_url:
    vps_receiver = VPSReceiver(
        relay_url=config.relay_url,
        local_queue=queue,
        latency_tracker=latency_tracker,
        api_key=config.relay_api_key,            # ← NEW
    )
```

#### 4. `.env.example` — Document the new variable

Add alongside the existing relay settings:

```bash
# Relay connection
RELAY_URL=https://relay.yourvps.com
RELAY_HMAC_SECRET=                    # HMAC for bot→relay ingest (X-Signature)
RELAY_API_KEY=                        # API key for orchestrator→relay reads (X-Api-Key)
```

### Compatibility

When `RELAY_API_KEY` is empty (the default on both relay and trading_assistant),
behavior is unchanged — no header is sent, no header is checked. The feature is
opt-in on both sides. To enable:

1. Set `RELAY_API_KEY=<some-secret>` on the relay VPS
2. Set `RELAY_API_KEY=<same-secret>` on the trading_assistant machine
3. Restart both services

### Testing

Add tests to the VPSReceiver test file:

1. **API key sent in headers** — mock client, verify `X-Api-Key` header present
2. **No API key when empty** — verify no `X-Api-Key` header when `api_key=""`
3. **401 triggers poll failure path** — verify `poll()` returns 0 and increments
   `_consecutive_failures` on 401 response

### Monitoring Consideration

The `check_relay_health()` method in `orchestrator/monitoring.py` calls
`GET /health` which remains unauthenticated, so monitoring is unaffected.
No changes needed to the monitoring check.

---

## Issue 2: Unhandled Event Types Routed to LOG_UNKNOWN

### Background

Three bot VPSes forward events through the relay:

| Bot | Event Types Emitted |
|-----|---------------------|
| **swing_trader** | `trade`, `missed_opportunity`, `error`, `coordinator_action`, `process_quality`, `daily_snapshot`, `post_exit`, `order`, `heartbeat` |
| **momentum_trader** | `trade`, `missed_opportunity`, `error`, `process_quality`, `daily_snapshot`, `order`, `heartbeat`, `portfolio_rule` |
| **k_stock_trader** | `trade`, `missed_opportunity`, `error`, `process_quality`, `daily_snapshot`, `order`, `heartbeat`, `bot_error`, `market_snapshot`, `exit_movement` |

The brain currently handles these event types:

| Event Type | Handler | Action |
|------------|---------|--------|
| `trade` | `_handle_trade` | `QUEUE_FOR_DAILY` |
| `missed_opportunity` | `_handle_missed_opportunity` | `QUEUE_FOR_DAILY` |
| `error` | `_handle_error` | Severity-based routing |
| `heartbeat` | `_handle_heartbeat` | `UPDATE_HEARTBEAT` |
| `coordinator_action` | `_handle_coordinator_action` | `QUEUE_FOR_DAILY` |
| `daily_analysis_trigger` | `_handle_daily_analysis_trigger` | `SPAWN_DAILY_ANALYSIS` |
| `weekly_summary_trigger` | `_handle_weekly_summary_trigger` | `SPAWN_WEEKLY_SUMMARY` |
| `wfo_trigger` | `_handle_wfo_trigger` | `SPAWN_WFO` |
| `notification_trigger` | `_handle_notification_trigger` | `SEND_NOTIFICATION` |

**Unhandled types** (all three bots combined):

| Event Type | Emitted By | Current Behavior | Events/Day (est.) |
|------------|------------|------------------|-------------------|
| `daily_snapshot` | all 3 bots | LOG_UNKNOWN | 3 (one per bot) |
| `order` | all 3 bots | LOG_UNKNOWN | 20-80 |
| `process_quality` | all 3 bots | LOG_UNKNOWN | 5-20 |
| `post_exit` | swing_trader | LOG_UNKNOWN | 2-10 |
| `bot_error` | k_stock_trader | LOG_UNKNOWN | 0-5 |
| `portfolio_rule` | momentum_trader | LOG_UNKNOWN | 0-3 |
| `market_snapshot` | k_stock_trader | LOG_UNKNOWN | 5-15 |
| `exit_movement` | k_stock_trader | LOG_UNKNOWN | 2-10 |

### Impact

Each unhandled event traverses the full pipeline:

```
Strategy → Kit → JSONL → Sidecar → Relay (stored in SQLite, uses disk) →
VPSReceiver (pulled, stored in local EventQueue) → Worker → Brain →
LOG_UNKNOWN (logger.warning, then acked and discarded)
```

This wastes:
- **Relay disk**: ~40-140 events/day stored, polled, and acked for nothing
- **VPSReceiver bandwidth**: pulls events it will immediately discard
- **Local EventQueue rows**: stored, processed, acked — all no-ops
- **Log noise**: WARNING-level messages for every unhandled event

### Current LOG_UNKNOWN Behavior

File: `orchestrator/orchestrator_brain.py:166-167`

```python
def _handle_unknown(self, event_id: str, bot_id: str, event: dict) -> list[Action]:
    return [Action(type=ActionType.LOG_UNKNOWN, event_id=event_id, bot_id=bot_id)]
```

File: `orchestrator/worker.py:171-172`

```python
elif action.type == ActionType.LOG_UNKNOWN:
    logger.warning("Unknown event type from %s: %s", action.bot_id, action.event_id)
```

The event is warned about, acked, and gone forever.

### Required Changes

#### 1. `orchestrator/orchestrator_brain.py` — Add handlers for useful types

Add handlers for event types that feed into daily/weekly analysis. These are
the same pattern as `_handle_trade` — queue them for batch analysis:

```python
def _handle_daily_snapshot(self, event_id: str, bot_id: str, event: dict) -> list[Action]:
    """Route daily snapshots to daily analysis queue.

    Daily snapshots contain end-of-day aggregate stats (total_trades, win_rate,
    gross_pnl, net_pnl, max_drawdown, profit_factor, regime breakdown).
    Consumed by the daily metrics pipeline alongside trade events.
    """
    return [Action(type=ActionType.QUEUE_FOR_DAILY, event_id=event_id, bot_id=bot_id)]

def _handle_order(self, event_id: str, bot_id: str, event: dict) -> list[Action]:
    """Route order lifecycle events to daily analysis queue.

    Order events track the full lifecycle: SUBMITTED → FILLED/REJECTED/CANCELLED.
    Contains: order_id, pair, side, order_type, status, requested_qty, filled_qty,
    fill_price, slippage_bps. Linked to parent trade_id.
    Consumed by execution quality analysis in the daily pipeline.
    """
    return [Action(type=ActionType.QUEUE_FOR_DAILY, event_id=event_id, bot_id=bot_id)]

def _handle_process_quality(self, event_id: str, bot_id: str, event: dict) -> list[Action]:
    """Route process quality scores to daily analysis queue.

    Process quality scores are deterministic quality assessments independent of PnL.
    Includes root cause taxonomy when quality is poor.
    Consumed by the daily pipeline for process discipline tracking.
    """
    return [Action(type=ActionType.QUEUE_FOR_DAILY, event_id=event_id, bot_id=bot_id)]

def _handle_bot_error(self, event_id: str, bot_id: str, event: dict) -> list[Action]:
    """Route bot-level errors through the severity-based error pipeline.

    bot_error events from k_stock_trader are explicit trading errors
    (as opposed to instrumentation errors). They carry the same severity
    field as regular error events and should follow the same routing.
    """
    return self._handle_error(event_id, bot_id, event)

def _handle_post_exit(self, event_id: str, bot_id: str, event: dict) -> list[Action]:
    """Route post-exit price tracking to daily analysis queue.

    Post-exit events record price movement after trade exits, enabling
    'left on the table' analysis. Consumed by the daily pipeline.
    """
    return [Action(type=ActionType.QUEUE_FOR_DAILY, event_id=event_id, bot_id=bot_id)]

def _handle_portfolio_rule(self, event_id: str, bot_id: str, event: dict) -> list[Action]:
    """Route portfolio rule events to daily analysis queue.

    Cross-strategy coordination events from momentum_trader.
    Similar to coordinator_action events from swing_trader.
    """
    return [Action(type=ActionType.QUEUE_FOR_DAILY, event_id=event_id, bot_id=bot_id)]

def _handle_market_snapshot(self, event_id: str, bot_id: str, event: dict) -> list[Action]:
    """Route market snapshot events to daily analysis queue.

    Market microstructure snapshots captured at entry/exit from k_stock_trader.
    Contains: spread, depth, volume profile. Enriches execution quality analysis.
    """
    return [Action(type=ActionType.QUEUE_FOR_DAILY, event_id=event_id, bot_id=bot_id)]

def _handle_exit_movement(self, event_id: str, bot_id: str, event: dict) -> list[Action]:
    """Route exit movement tracking to daily analysis queue.

    Post-exit price movement from k_stock_trader. Similar to post_exit
    from swing_trader. Tracks price after exit for regret analysis.
    """
    return [Action(type=ActionType.QUEUE_FOR_DAILY, event_id=event_id, bot_id=bot_id)]
```

#### 2. `orchestrator/orchestrator_brain.py` — Register handlers in `_handlers` dict

Update the `_handlers` class variable (around line 181):

```python
_handlers: dict = {
    # --- Existing handlers (unchanged) ---
    "trade": _handle_trade,
    "missed_opportunity": _handle_missed_opportunity,
    "error": _handle_error,
    "heartbeat": _handle_heartbeat,
    "daily_analysis_trigger": _handle_daily_analysis_trigger,
    "weekly_summary_trigger": _handle_weekly_summary_trigger,
    "wfo_trigger": _handle_wfo_trigger,
    "notification_trigger": _handle_notification_trigger,
    "coordinator_action": _handle_coordinator_action,

    # --- New handlers for bot event types ---
    "daily_snapshot": _handle_daily_snapshot,
    "order": _handle_order,
    "process_quality": _handle_process_quality,
    "bot_error": _handle_bot_error,
    "post_exit": _handle_post_exit,
    "portfolio_rule": _handle_portfolio_rule,
    "market_snapshot": _handle_market_snapshot,
    "exit_movement": _handle_exit_movement,
}
```

### Design Rationale

All new handlers route to `QUEUE_FOR_DAILY` because:

1. **These events are consumed by the daily analysis pipeline.** The daily
   metrics assembler already aggregates trade, missed_opportunity, and
   coordinator_action events per bot per day. Adding order/snapshot/quality
   events to the same queue means the daily analysis prompt has richer context
   without any changes to the worker dispatch logic.

2. **No new `ActionType` values needed.** The worker already knows how to
   handle `QUEUE_FOR_DAILY` — it increments `daily_queue_counts[bot_id]` and
   the daily analysis trigger consumes them. The new event types just contribute
   to the count.

3. **`bot_error` reuses `_handle_error`.** k_stock_trader's `bot_error` events
   carry the same `severity` field (CRITICAL/HIGH/MEDIUM/LOW) as regular `error`
   events, so the severity-based routing (ALERT_IMMEDIATE, SPAWN_TRIAGE,
   QUEUE_FOR_DAILY, QUEUE_FOR_WEEKLY) applies identically.

4. **No handler needed for types that are purely diagnostic.** If a future bot
   emits a type not in this list, it falls through to LOG_UNKNOWN. This is
   acceptable for truly novel event types — the warning log serves as a signal
   to add a handler.

### Alternative: Filter at Sidecar Level

Instead of (or in addition to) adding brain handlers, each bot's sidecar can
be configured to only forward types the brain understands. The swing_trader
relay hardening pass added a `forward_event_types` config option:

```yaml
# instrumentation/config/instrumentation_config.yaml (swing_trader example)
sidecar:
  forward_event_types:
    - trade
    - missed_opportunity
    - error
    - coordinator_action
    - heartbeat
    - daily_snapshot
    - order
```

This reduces relay storage, network bandwidth, and VPSReceiver processing.
However, adding brain handlers is recommended because:

- It's a single change point (brain) vs three (each bot's sidecar config)
- Events already in transit are handled rather than silently dropped
- Future analysis pipelines can consume the richer event stream

**Recommended approach: Add brain handlers AND configure `forward_event_types`
on each sidecar to filter out truly useless types (if any emerge).**

### Testing

Add tests to the brain test file:

1. **Each new event type routes correctly:**
   ```python
   def test_daily_snapshot_queued_for_daily(self):
       event = {"event_id": "ds1", "bot_id": "bot1", "event_type": "daily_snapshot", "payload": "{}"}
       actions = brain.decide(event)
       assert len(actions) == 1
       assert actions[0].type == ActionType.QUEUE_FOR_DAILY
   ```

2. **bot_error follows error severity routing:**
   ```python
   def test_bot_error_critical_alerts_immediately(self):
       event = {
           "event_id": "be1", "bot_id": "bot1", "event_type": "bot_error",
           "payload": '{"severity": "CRITICAL", "error_type": "connection_lost"}',
       }
       actions = brain.decide(event)
       assert actions[0].type == ActionType.ALERT_IMMEDIATE
   ```

3. **Unknown types still LOG_UNKNOWN:**
   ```python
   def test_truly_unknown_type_still_logged(self):
       event = {"event_id": "u1", "bot_id": "bot1", "event_type": "some_future_type", "payload": "{}"}
       actions = brain.decide(event)
       assert actions[0].type == ActionType.LOG_UNKNOWN
   ```

4. **Worker daily_queue_counts increments for new types:**
   Verify that `worker.daily_queue_counts["bot1"]` increases when processing
   `daily_snapshot`, `order`, `process_quality`, etc.

---

## Event Type Reference (Complete)

After both changes are applied, the full event type routing map is:

| Event Type | Source Bot(s) | Brain Handler | Action | Worker Behavior |
|------------|---------------|---------------|--------|-----------------|
| `trade` | all 3 | `_handle_trade` | `QUEUE_FOR_DAILY` | Count for daily analysis |
| `missed_opportunity` | all 3 | `_handle_missed_opportunity` | `QUEUE_FOR_DAILY` | Count for daily analysis |
| `error` | all 3 | `_handle_error` | Severity-based | CRITICAL→alert, HIGH→triage, MED→daily, LOW→weekly |
| `heartbeat` | all 3 | `_handle_heartbeat` | `UPDATE_HEARTBEAT` | Write `{bot_id}.heartbeat` file |
| `coordinator_action` | swing_trader | `_handle_coordinator_action` | `QUEUE_FOR_DAILY` | Count for daily analysis |
| `daily_snapshot` | all 3 | `_handle_daily_snapshot` | `QUEUE_FOR_DAILY` | Count for daily analysis |
| `order` | all 3 | `_handle_order` | `QUEUE_FOR_DAILY` | Count for daily analysis |
| `process_quality` | all 3 | `_handle_process_quality` | `QUEUE_FOR_DAILY` | Count for daily analysis |
| `bot_error` | k_stock_trader | `_handle_bot_error` | Severity-based | Same as `error` handler |
| `post_exit` | swing_trader | `_handle_post_exit` | `QUEUE_FOR_DAILY` | Count for daily analysis |
| `portfolio_rule` | momentum_trader | `_handle_portfolio_rule` | `QUEUE_FOR_DAILY` | Count for daily analysis |
| `market_snapshot` | k_stock_trader | `_handle_market_snapshot` | `QUEUE_FOR_DAILY` | Count for daily analysis |
| `exit_movement` | k_stock_trader | `_handle_exit_movement` | `QUEUE_FOR_DAILY` | Count for daily analysis |
| `daily_analysis_trigger` | scheduler | `_handle_daily_analysis_trigger` | `SPAWN_DAILY_ANALYSIS` | Invoke Claude CLI for analysis |
| `weekly_summary_trigger` | scheduler | `_handle_weekly_summary_trigger` | `SPAWN_WEEKLY_SUMMARY` | Invoke Claude CLI for summary |
| `wfo_trigger` | scheduler | `_handle_wfo_trigger` | `SPAWN_WFO` | Invoke walk-forward optimization |
| `notification_trigger` | scheduler | `_handle_notification_trigger` | `SEND_NOTIFICATION` | Dispatch via comms channels |
| *(unknown)* | — | `_handle_unknown` | `LOG_UNKNOWN` | `logger.warning()`, ack, discard |

---

## Priority Coercion Note

The relay now accepts both integer and string priorities on ingest. Bots send
different formats:

| Bot | Priority Format | Example Values |
|-----|----------------|----------------|
| swing_trader | integers | `1` (error), `3` (trade), `4` (analytics) |
| momentum_trader | integers | `0` (error), `2` (trade), `5` (heartbeat) |
| k_stock_trader | strings | `"critical"`, `"high"`, `"normal"`, `"low"` |

The relay coerces strings to integers before storage:

| String | Integer |
|--------|---------|
| `"critical"` | `0` |
| `"high"` | `1` |
| `"normal"` | `3` |
| `"low"` | `4` |
| *(unknown)* | `3` |

Events are served in priority order (`ORDER BY priority ASC, id ASC`), so
critical errors from k_stock_trader are delivered before normal trades from
any bot. No changes needed in trading_assistant for this — the relay handles
coercion transparently.

---

## Local EventQueue: No Priority Column

The local EventQueue schema (`orchestrator/db/schema.sql`) does not store
priority:

```sql
CREATE TABLE IF NOT EXISTS events (
    event_id        TEXT PRIMARY KEY,
    bot_id          TEXT NOT NULL,
    event_type      TEXT NOT NULL,
    payload         TEXT NOT NULL,
    exchange_timestamp TEXT NOT NULL,
    received_at     TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending',
    -- ... no priority column
);
```

This is acceptable because:

1. The relay serves events in priority order, so the VPSReceiver pulls
   high-priority events first within each poll batch.
2. The local `peek()` query uses `ORDER BY created_at ASC`, which preserves
   the pull order since events are inserted sequentially.
3. After initial delivery, local re-processing order doesn't need priority
   because the worker processes all pending events in each batch.

If priority-based local processing becomes important (e.g., for debugging or
selective reprocessing), add the column via migration:

```sql
ALTER TABLE events ADD COLUMN priority INTEGER NOT NULL DEFAULT 3;
```

And update `enqueue_batch()` in `orchestrator/db/queue.py` to store it.
This is a future enhancement, not a blocker.

---

## Verification Steps

After applying both changes:

1. **API key auth:**
   - Set `RELAY_API_KEY=test-key` on relay, restart
   - Set `RELAY_API_KEY=test-key` on trading_assistant, restart
   - Verify `VPSReceiver.poll()` returns events (not 0)
   - Remove the key from trading_assistant, verify poll returns 0 (401)

2. **Event type routing:**
   - Emit a `daily_snapshot` event via a bot sidecar
   - Verify it flows through relay → VPSReceiver → brain → `QUEUE_FOR_DAILY`
   - Check `worker.daily_queue_counts` includes the bot_id
   - Emit a `bot_error` with `severity: CRITICAL`
   - Verify brain routes to `ALERT_IMMEDIATE`

3. **No regressions:**
   - `pytest tests/` — all 740+ tests pass
   - `trade`, `error`, `heartbeat` events still route correctly
   - Unknown event types still produce LOG_UNKNOWN warning
