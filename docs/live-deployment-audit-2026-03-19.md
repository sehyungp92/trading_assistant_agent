# Live Deployment Audit

Date: 2026-03-19

## Scope

This audit focused on code paths that matter most in live operation:

- orchestrator startup, scheduling, queueing, worker execution, monitoring, and HTTP control plane
- notification delivery and channel adapters
- persistence layers used by the approval, suggestion, deployment, and experiment loops
- learning-loop data integrity

I re-reviewed this report against the current codebase, the current tests, and targeted repros. This version supersedes the earlier draft where the repo had been partially overstated in a few places.

Out of scope:

- the separately deployed relay service itself is not present in this repository
- external infrastructure hardening outside this repo (reverse proxy, firewall rules, process supervision)

## Executive Summary

The repository is still not ready for exposed live deployment in its current form.

The highest-risk problems remain:

1. notification delivery is not deployment-safe
2. event processing is not exclusive
3. the FastAPI control plane has no built-in authentication

The second pass changed two important details from the earlier version:

- relay read-side API key support already exists in the current repo and is covered by tests
- the brain already handles the event types previously called out in the relay integration note, and targeted tests cover them

Those corrections do not change the deployment verdict, because the notification, queue, and control-plane issues are still strong enough to block unattended or exposed live operation.

## Second-Pass Corrections

### What the earlier draft overstated

- `VPSReceiver` already supports `X-Api-Key` relay auth in current code: `orchestrator/adapters/vps_receiver.py:23-55`, `orchestrator/app.py:796-803`, `tests/test_vps_receiver.py:245-340`
- the brain already routes the relay event types that an older integration document described as missing: `orchestrator/orchestrator_brain.py`, `tests/test_orchestrator_brain.py:91-187`

### What this revision adds

- a fresh deployment with Telegram configured still starts with zero enabled notification channels unless preferences are seeded manually
- direct Telegram approval-card flows in the autonomous pipeline bypass the generic dispatcher and are therefore not covered by the main notification breakage
- the relay issue in this repo is now better described as config/doc drift plus dead adaptive polling, not missing API-key support

## Verification Summary

### Full test suite

Command run:

```bash
pytest tests/ -q
```

Result:

```text
2800 passed in 509.60s (0:08:29)
```

### Second-pass targeted verification

Command run:

```bash
pytest tests/test_vps_receiver.py tests/test_orchestrator_brain.py tests/test_monitoring.py -q
```

Result:

```text
40 passed in 10.68s
```

### Targeted repros

1. Concurrent worker execution processed the same event twice:

```text
{'alert_calls': ['evt-1', 'evt-1'], 'call_count': 2, 'pending': 0}
```

2. Mixed outcome rows doubled scorecard sample size for a single suggestion:

```text
{'scores': [{'bot_id': 'bot1', 'category': 'exit_timing', 'win_rate': 1.0, 'avg_pnl_delta': 100.0, 'sample_size': 2, 'confidence_multiplier': 1.0}]}
```

3. Heartbeat parsing crashed on a naive timestamp:

```text
{'ok': False, 'error': 'TypeError', 'detail': "can't subtract offset-naive and offset-aware datetimes"}
```

4. Listing sessions on a fresh install crashed:

```text
{'error': 'FileNotFoundError', 'detail': "[WinError 3] ... missing_base"}
```

5. Unauthenticated control-plane requests succeeded:

```text
{'get_agent_preferences': 200, 'put_notification_preferences': 200}
```

6. Real Telegram dispatch through the current generic notification pipeline failed:

```text
TelegramBotAdapter send failed after 3 attempts: string indices must be integers, not 'str'
```

7. A fresh app with Telegram configured had a registered adapter but zero enabled notification channels:

```text
{'registered_adapters': ['telegram'], 'prefs_channels': 0}
```

## Risk Matrix

| Severity | Finding | Deployment Impact |
|----------|---------|-------------------|
| Critical | Notification delivery is not deployment-safe | Alerts/reports may never reach the operator |
| Critical | Event queue has no exclusive claim/lease semantics | Same event can execute multiple times |
| Critical | FastAPI control plane has no built-in auth | Remote users can mutate state and trigger actions |
| High | Outcome measurement writes two schemas into one file | Learning and calibration data become distorted |
| High | JSONL trackers are not concurrency-safe | Lost updates and inconsistent approval/deployment state |
| Medium | Relay integration/docs are partially stale and adaptive polling is dead code | Operator confusion and avoidable polling inefficiency |
| Medium | Heartbeat parsing crashes on naive timestamps | Monitoring loop can fail instead of alerting |
| Medium | `/sessions` crashes on a fresh install | Operational endpoint is brittle |
| Medium | Conversation chain cleanup is defined but never scheduled | Slow memory growth over long uptime |

## Detailed Findings

### Critical 1: Notification delivery is not deployment-safe

#### Evidence

- A fresh app loads `NotificationPreferences()` when no prefs file exists: `orchestrator/app.py:123-130`
- `NotificationPreferences` defaults to an empty `channels` list, so the dispatcher has no eligible targets by default: `schemas/notifications.py:56-73`
- Channel adapters are still registered from env config, which means a deployment can look configured while delivery is effectively disabled until prefs are written separately: `orchestrator/app.py:192-235`
- Confirmed repro with Telegram configured on first boot:

```text
{'registered_adapters': ['telegram'], 'prefs_channels': 0}
```

- The main handler path builds a `NotificationPayload` and calls the dispatcher, but ignores the returned `DeliveryResult` list: `orchestrator/handlers.py:2123-2139`, `comms/dispatcher.py:70-97`
- For `BaseChannel` adapters, the dispatcher passes `(payload, cfg)` into `send_with_retry(...)`, which forwards arbitrary args directly into `_send(...)`: `comms/dispatcher.py:87-88`, `comms/base_channel.py:55-77`
- The concrete adapters do not share that contract:
  - Telegram `_send(text, keyboard)`: `comms/telegram_bot.py:126-137`
  - Email `_send(to, subject, html_body, attachment_paths)`: `comms/email_adapter.py:35-56`
  - Discord `_send(content)` with `_channel` never initialized in `_start()`: `comms/discord_bot.py:25-40`
- The real Telegram path fails immediately when exercised through the generic dispatcher:

```text
TelegramBotAdapter send failed after 3 attempts: string indices must be integers, not 'str'
```

- `EMAIL_TO` is loaded into config, but the registered `EmailAdapter` is built without a default recipient, and the per-channel schema has no email-specific destination field beyond `chat_id`: `orchestrator/config.py:137-142`, `orchestrator/config.py:197-202`, `orchestrator/app.py:221-232`, `schemas/notifications.py:37-43`

#### What already exists in the codebase

- The renderer layer exists (`comms/renderer.py`, `comms/telegram_renderer.py`)
- Channel health reporting exists: `comms/dispatcher.py:52-68`
- Some direct Telegram flows already work because they bypass the dispatcher and call `telegram_bot.send_message(...)` directly; the autonomous approval path is covered by tests: `tests/test_autonomous_integration.py:91-105`, `tests/test_autonomous_integration.py:296-314`

#### Why the current tests missed the main problem

- Dispatcher and integration tests mostly use mocked `ChannelAdapter` objects with a `send(payload, cfg)` contract: `tests/test_dispatcher.py:24-155`, `tests/test_comms_integration.py:26-88`
- They do not exercise the real `BaseChannel` adapters behind the dispatcher
- Existing tests also accept empty default notification preferences as normal behavior: `tests/test_comms_integration.py:169-194`

#### Impact

- Fresh installs can silently send no notifications at all even when Telegram/Discord/SMTP env vars are set
- Daily reports, weekly summaries, alerts, and rollback notifications can fail on the generic delivery path
- Discord is not merely miswired at the dispatcher boundary; it is not actually initialized for sending
- Delivery failures do not currently promote the app to degraded state or block startup, because handler code ignores the dispatch results

#### Recommendation

- Seed notification preferences from configured adapters on first boot
- Standardize the adapter contract to one end-to-end model:
  - either render before dispatch and make all adapters accept rendered channel-native content
  - or make all adapters accept `NotificationPayload` plus `ChannelConfig` and render internally
- Treat an empty eligible-channel set as a deployment misconfiguration, not a successful no-op
- Wire delivery results and channel health into startup checks, `/health`, or degraded-state signaling
- Disable or complete the Discord and email paths until they have a fully defined contract

### Critical 2: Event processing is not exclusive, so the same event can execute twice

#### Evidence

- Queue reads pending rows without claiming them: `orchestrator/db/queue.py:81-88`
- Worker processes whatever `peek()` returns and only marks the event after downstream handlers complete: `orchestrator/worker.py:63-108`
- `recover_stale()` assumes events can be in `processing`, but no production path actually sets that state: `orchestrator/db/queue.py:150-161`
- The worker is reachable from both the scheduler job and the manual `/process` endpoint:
  - scheduler wiring: `orchestrator/scheduler.py`, `orchestrator/app.py:1571-1578`
  - manual endpoint: `orchestrator/app.py:1804-1808`

Confirmed repro:

```text
{'alert_calls': ['evt-1', 'evt-1'], 'call_count': 2, 'pending': 0}
```

#### Impact

- duplicate notifications
- duplicate triage or analysis runs
- double-applied feedback handling
- repeated raw event persistence
- non-idempotent downstream automation executed twice

This is a real live-deployment issue because it only takes one overlapping scheduler tick, manual trigger, or future multi-worker setup to trigger it.

#### Recommendation

- Replace `peek()` with an atomic claim step such as:
  - `UPDATE ... SET status='processing' ... RETURNING ...`
  - or a transactional claim query with a lease timestamp
- Add a worker-level single-flight guard if only one local consumer is intended
- Add regression tests that run two `process_batch()` calls concurrently against a real queue

### Critical 3: The HTTP control plane exposes mutating and internal endpoints with no built-in authentication

#### Evidence

- The FastAPI app defines administrative and mutating endpoints with no auth dependencies or middleware in the app: `orchestrator/app.py:1741-1978`
- Examples of unauthenticated mutation surfaces:
  - `/ingest`: `orchestrator/app.py:1781-1791`
  - `/process`: `orchestrator/app.py:1804-1808`
  - `/events/dead-letter/{event_id}/reprocess`: `orchestrator/app.py:1834-1840`
  - `/agent/preferences`: `orchestrator/app.py:1842-1855`
  - `/notifications/preferences`: `orchestrator/app.py:1857-1868`
  - `/feedback`: `orchestrator/app.py:1870-1894`
  - `/subagents/{agent_id}/cancel`: `orchestrator/app.py:1905-1910`
- Unauthenticated internal read/state surfaces are also exposed:
  - `/events/stream`: `orchestrator/app.py:1810-1828`
  - `/events/pending`: `orchestrator/app.py:1793-1795`
  - `/events/dead-letter`: `orchestrator/app.py:1830-1832`
  - `/sessions`: `orchestrator/app.py:1896-1898`
  - `/subagents`: `orchestrator/app.py:1900-1903`
  - `/learning/dashboard`: `orchestrator/app.py:1913-1976`

Confirmed repro:

```text
{'get_agent_preferences': 200, 'put_notification_preferences': 200}
```

#### Impact

- anyone who can reach the service can inject events, mutate preferences, submit synthetic feedback, requeue dead letters, trigger processing, inspect live event streams, and cancel subagents
- if this service is exposed beyond a tightly private network, this is a deployment blocker

#### Recommendation

- Add built-in API authentication for all non-health endpoints
- Split public-read endpoints from admin/mutation endpoints
- Require explicit deployment config for trusted ingress rather than assuming a private network
- Document the threat model in the repo instead of leaving it implicit

### High 1: Outcome measurement writes two schemas into the same `outcomes.jsonl`

#### Evidence

- The app first writes a legacy `SuggestionOutcome` row through `SuggestionTracker.record_outcome(...)`: `orchestrator/app.py:937-945`
- It then appends the full `OutcomeMeasurement` object into the same `outcomes.jsonl`: `orchestrator/app.py:947-951`
- `SuggestionScorer` reads all rows from `outcomes.jsonl` and groups every row by `suggestion_id` with no dedupe: `skills/suggestion_scorer.py:31-92`
- `ContextBuilder.load_outcome_measurements()` also loads the file raw and returns every row: `analysis/context_builder.py:148-157`

Confirmed repro:

```text
{'scores': [{'bot_id': 'bot1', 'category': 'exit_timing', 'win_rate': 1.0, 'avg_pnl_delta': 100.0, 'sample_size': 2, 'confidence_multiplier': 1.0}]}
```

#### Impact

- category scorecards can double-count a single suggestion
- confidence multipliers can be inflated or suppressed incorrectly
- prompt context can include duplicated or schema-inconsistent outcome records
- long-term calibration and learning decisions become untrustworthy

#### Recommendation

- Choose one canonical schema per file
- If both legacy and enriched representations are needed, split them into separate files
- Add a migration or reader shim that deduplicates by `suggestion_id`
- Add tests that assert one measured suggestion yields one scored outcome

### High 2: JSONL-backed state stores are not concurrency-safe

#### Evidence

- `SuggestionTracker` uses load-modify-rewrite and append patterns with no lock at all: `skills/suggestion_tracker.py:27-35`, `skills/suggestion_tracker.py:94-97`, `skills/suggestion_tracker.py:112-149`
- `ApprovalTracker`, `DeploymentMonitor`, and `ExperimentManager` each allocate `asyncio.Lock()`, but production methods do not use it:
  - approval tracker lock: `skills/approval_tracker.py:23-25`
  - deployment monitor lock: `skills/deployment_monitor.py:39-45`
  - experiment manager lock: `skills/experiment_manager.py:30-35`
- A repo-wide test search only finds cleanup/lock-style wiring around these components, not real production locking behavior

#### Impact

- lost updates during concurrent writes
- approval count races for double-approval flows
- deployment or experiment records overwritten by stale snapshots
- suggestion lifecycle regressions when multiple scheduled tasks or callbacks update the same file

#### Recommendation

- Either:
  - make these stores properly async and guard all read-modify-write operations with the existing locks
  - or move these records to SQLite where transactional updates are easier to reason about
- Add concurrent-write tests against the real production APIs, not just lock existence tests

### Medium 1: Relay integration is mostly present, but adaptive polling is dead code and the config/docs are stale

#### Evidence

- `VPSReceiver` already accepts `api_key` and injects `X-Api-Key` headers: `orchestrator/adapters/vps_receiver.py:23-55`
- The app already wires `relay_api_key`: `orchestrator/app.py:796-803`
- Targeted tests already cover the API-key behavior: `tests/test_vps_receiver.py:245-340`
- The brain already routes the previously flagged bot event types, and targeted tests cover them: `tests/test_orchestrator_brain.py:91-187`
- `VPSReceiver` maintains `current_poll_interval` and adapts it based on traffic: `orchestrator/adapters/vps_receiver.py:57-63`, `orchestrator/adapters/vps_receiver.py:107-113`
- Scheduler wiring still uses a fixed configured interval from `SchedulerConfig.relay_poll_interval_seconds`: `orchestrator/scheduler.py:57-59`, `orchestrator/scheduler.py:141-150`, `orchestrator/scheduler.py:341-349`
- The orchestrator config and docs still advertise `RELAY_HMAC_SECRET` even though this repo only uses `RELAY_API_KEY` on the read side:
  - config fields: `orchestrator/config.py:130-142`, `orchestrator/config.py:190-202`
  - `.env.example`: `.env.example:40-44`
  - README still marks `RELAY_HMAC_SECRET` as required and describes notifications as if channel env config alone is sufficient: `README.md:29`, `README.md:188`, `README.md:195-198`

#### Impact

- the adaptive polling state adds complexity without changing real scheduler cadence
- operators can be misled by stale repo-level config/docs
- this is primarily a correctness/documentation drift issue in this repo, not evidence that API-key relay auth is missing today

#### Recommendation

- Either wire adaptive poll intervals into the scheduler or remove the unused state and tests
- Clarify in repo docs that bot ingest uses HMAC on the relay side while this orchestrator uses API-key auth for relay reads
- Remove or clearly mark `RELAY_HMAC_SECRET` as not used by the orchestrator process itself

### Medium 2: Monitoring can crash on naive heartbeat timestamps

#### Evidence

- `_read_heartbeats()` parses with `datetime.fromisoformat(...)` and subtracts from an aware UTC `now` without normalizing naive timestamps: `orchestrator/monitoring.py:93-108`
- It catches `ValueError` and `OSError`, but not the `TypeError` raised by mixing naive and aware datetimes

Confirmed repro:

```text
{'ok': False, 'error': 'TypeError', 'detail': "can't subtract offset-naive and offset-aware datetimes"}
```

#### Impact

- a malformed or naive heartbeat file can crash monitoring instead of generating an alert
- the exact failure mode is worst when the monitoring system is needed most

#### Recommendation

- Normalize naive timestamps to UTC before subtraction
- Catch `TypeError` here as a malformed-heartbeat condition
- Add a regression test for naive heartbeat files

### Medium 3: `/sessions` can crash on a fresh install

#### Evidence

- `SessionStore.list_sessions()` iterates `self._base_dir` unconditionally when no `agent_type` is provided: `orchestrator/session_store.py:149-170`
- If the base directory does not exist yet, this raises `FileNotFoundError`
- Existing session-store tests cover populated stores only, not a brand-new empty base dir: `tests/test_session_store.py:15-100`

Confirmed repro:

```text
{'error': 'FileNotFoundError', 'detail': "[WinError 3] ... missing_base"}
```

#### Impact

- the `/sessions` endpoint is brittle on new deployments or after data cleanup
- operational tooling should degrade to `[]`, not `500`

#### Recommendation

- Guard `list_sessions()` with `if not self._base_dir.exists(): return []`
- Add an endpoint test for a brand-new data directory

### Medium 4: Conversation-chain cleanup exists but is never scheduled

#### Evidence

- `ConversationTracker` accumulates chains in memory and provides `cleanup_expired()`: `orchestrator/conversation_tracker.py:17-83`
- Repo-wide usage shows creation and extension wiring, but cleanup is not scheduled in production code

#### Impact

- slow but unbounded memory growth over long uptime
- more pronounced in noisy environments with many feedback or chained events

#### Recommendation

- Run cleanup periodically from the monitoring loop or during `begin_chain()` / `extend_chain()`
- Track chain count in `/metrics`

## Recommended Remediation Order

1. Fix notification bootstrap and the dispatcher/adapters contract, then add real adapter integration tests.
2. Add queue claim/lease semantics and concurrency tests for `process_batch()`.
3. Put authentication in front of the control plane and default unsafe endpoints off unless explicitly enabled.
4. Split or normalize outcome measurement storage so one suggestion produces one canonical outcome record.
5. Move JSONL lifecycle stores to transactional persistence or actually use the existing locks.
6. Clean up the medium issues before broad rollout, especially heartbeat parsing and `/sessions`.

## Deployment Verdict

Current verdict: do not expose this service to a network or rely on it for unattended live operations until the critical findings are fixed.

For a private, supervised, single-operator environment, the codebase is close in many areas and the test coverage is strong, but the current production wiring still has a few high-leverage failure modes that can undermine trust exactly when the system is supposed to help.
