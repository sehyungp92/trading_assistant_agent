# K Stock Trader Instrumentation Implementation Guide

Date: 2026-05-31

Audience: Codex or another coding agent implementing the optimal
instrumentation target in `_references/k_stock_trader/`.

Primary source guide:
`docs/2026-05-30-optimal-trading-repo-instrumentation-guide.md`

Reference repo audited:
`_references/k_stock_trader/`

## 1. Purpose

This guide translates the optimal trading-repo instrumentation target into a
concrete implementation plan for the current `k_stock_trader` repo.

The repo is not blank. It already has a serious instrumentation foundation and
a separate live runtime evidence system:

- a legacy/general `instrumentation/` package with trade, missed opportunity,
  process score, filter, indicator, market snapshot, order, heartbeat, daily
  snapshot, sidecar, and config-change emitters;
- current production-oriented KRX equity strategies `KALCB` and `OLR` under
  the combined `deployment/olr_kalcb/` runtime;
- a paper/live runtime session recorder that writes decision, strategy action,
  portfolio arbitration, OMS intent, order event, fill event, trade outcome,
  state snapshot, market bar, artifact, and resource-plan evidence;
- a centralized OMS with intent-based ordering, KIS execution, risk checks,
  strategy allocations, reconciliation, Postgres audit tables, and dashboard
  views;
- KIS resource planning, artifact readiness, strategy config fingerprints, and
  paper replay parity checks.

The goal is therefore not to bolt on another logger. The goal is to upgrade
and connect the existing evidence surfaces into the optimal assistant-facing
contract required by `trading_assistant` for:

- daily and weekly diagnostics;
- monthly authoritative validation;
- live/backtest decision parity;
- structural strategy and portfolio change review;
- attribution across strategy config, artifact hash, portfolio policy, KIS
  resource plan, OMS risk state, allocation state, account state, broker
  execution, and deployment identity.

The key current-state finding is:

`k_stock_trader` already has rich local evidence, but it is split across two
truth surfaces. The legacy `instrumentation/` package is mainly wired into
`strategy_pcim`, while the active `KALCB`/`OLR` runtime uses
`PaperSessionRecorder` and the OMS/Postgres audit path. Optimal implementation
means canonicalizing and forwarding the active runtime and OMS evidence, while
retrofitting the legacy instrumentation package so every event uses the same
lineage, identity, sidecar, and assistant event contract.

## 2. Current-State Verdict

| Surface | Current state | Optimal target |
|---|---|---|
| `instrumentation/src/event_metadata.py` | Has deterministic `event_id`, `bot_id`, exchange/local timestamps, clock skew, `data_source_id`, `event_type`, `payload_key`, optional `bar_id`. | Extend without breaking callers: add schema version, strategy/family/portfolio/account lineage, deployment/config/code IDs, `trace_id`, `decision_id`, `logical_event_id`, and `revision`. |
| `instrumentation/src/trade_logger.py` | Rich completed trade payload with signal, filters, sizing, slippage, latency, MFE/MAE, drawdown, experiment fields. | Add full lineage, KALCB/OLR artifact/config IDs, OMS/KIS order and fill IDs, `decision_id`, `action_ref`, `intent_id`, portfolio and allocation versions. |
| `instrumentation/src/missed_opportunity.py` | Captures blocked signals and rewrites JSONL rows when outcomes are backfilled. | Stop rewriting sent rows. Append revision events with stable `logical_event_id`; include portfolio/risk block context and full lineage. |
| `instrumentation/src/sidecar.py` | Watches useful directories, batches, signs, gzips, retries, and skips entry-stage trades. Payload is sent as a JSON string. | Keep the sidecar, but forward canonical envelope lineage, support payload object locally, add new event dirs, and handle revision events correctly. |
| `instrumentation/facade.py` | Fail-open facade used heavily by `strategy_pcim/main.py`. | Keep it, but use it as a compatibility facade. Do not make it the sole KALCB/OLR integration layer. |
| `deployment/olr_kalcb/session_capture.py` | Strong paper/live evidence bundle and replay hash contract. | Treat this as a primary producer of assistant telemetry. Export its streams to canonical events. |
| `deployment/olr_kalcb/session_driver.py` | Creates deterministic `event_ref`, records runtime inputs, decisions, no-actions, route results, state snapshots, fills, and trade outcomes. | Add assistant event emission at these same points with lineage and join keys. |
| `deployment/olr_kalcb/action_router.py` | Records strategy actions, portfolio arbitration, OMS intents, and order results. | Convert each route decision into first-class `decision_event`, `portfolio_rule`, `order`, and `risk/OMS` evidence. |
| `deployment/olr_kalcb/market_data_coordinator.py` | Records KIS subscription and resource-window events. | Forward market data lease and suppression events as assistant telemetry with resource-plan lineage. |
| `oms/oms_core.py` and `oms/persistence.py` | Rich OMS state is persisted to Postgres and logs, but mostly not forwarded to the assistant. | Add a fail-open OMS event emitter or outbox for risk decisions, order lifecycle, fills, reconciliation, position/allocation snapshots, risk controls, and heartbeats. |
| `oms/risk.py` | Returns a compact `RiskResult`; detailed rule evaluations are not preserved. | Add a risk trace while preserving behavior. Emit thresholds, observed values, decision, modifiers, and blocking positions. |
| `config/oms_config.yaml` | Strategy budgets only list `PCIM`; active KALCB/OLR budgets are not represented there. | Either add explicit `KALCB`/`OLR` budgets or emit a risk-config snapshot proving that no strategy-specific budget applied. |
| `instrumentation/src/config_watcher.py` | Watches stale module names from older strategy families. | Replace or augment with file/effective-config snapshotting for KALCB/OLR runtime configs, portfolio policy, OMS config, sector map, artifact manifests, and deployment metadata. |

## 3. Implementation Principle

Use the repo's existing instrumentation and runtime evidence. Do not replace
them.

Make the implementation surgical:

- preserve `instrumentation/src/*` and `instrumentation/facade.py`;
- preserve `PaperSessionRecorder` and the session hash contract;
- preserve OMS persistence and dashboard views;
- enrich existing payloads rather than renaming fields wholesale;
- add canonical fields beside existing aliases such as `pair`, `symbol`,
  `param_set_id`, `parameter_set_id`, `strategy_type`, `strategy_id`,
  `event_ref`, and `decision_ref`;
- never change strategy decisions, sizing, order routing, OMS approvals, or
  KIS requests while adding instrumentation;
- make every instrumentation write fail-open and bounded;
- never emit KIS secrets, raw account numbers, HMAC secrets, database DSNs, or
  broker tokens.

The target invariant is:

For every live strategy decision and every OMS transformation of that decision,
the assistant can answer which strategy, artifact, config, deployment, KIS
resource plan, portfolio policy, risk config, account alias, allocation state,
decision callback, market bar, portfolio rule, OMS intent, KIS order, fill,
and reconciliation state produced the final outcome.

## 4. Target Architecture

Implement one shared assistant event contract with three producer surfaces:

1. `instrumentation/` compatibility events.
2. `deployment/olr_kalcb/` runtime session evidence.
3. `oms/` risk, order, fill, allocation, reconciliation, and heartbeat events.

Add small shared modules instead of copying event-building logic into every
call site:

```text
instrumentation/src/
  event_contract.py          # canonical event type names, priority, schema versions
  lineage.py                 # LineageContext and builders from env/runtime/OMS/config
  event_writer.py            # bounded, fail-open JSONL writer
  event_envelope.py          # payload/envelope normalization for sidecar
  config_snapshot.py         # effective config hashing and redaction
  deployment_logger.py       # startup/reload/deploy events
  runtime_exporter.py        # adapters for PaperSessionRecorder streams
  oms_exporter.py            # OMS event emitter/outbox helpers
  position_snapshot.py       # position snapshot payloads
  portfolio_snapshot.py      # portfolio snapshot payloads
  allocation_snapshot.py     # allocation snapshot payloads
  risk_decision.py           # risk decision trace payloads
```

Extend local data directories to include every optimal event type:

```text
instrumentation/data/
  trades/
  missed/
  orders/
  fills/
  filter_decisions/
  indicators/
  snapshots/
  decisions/
  strategy_actions/
  portfolio_rules/
  risk_decisions/
  positions/
  allocations/
  portfolio/
  config_snapshots/
  config_changes/
  deployments/
  resource_plans/
  market_data/
  reconciliations/
  heartbeats/
  bot_errors/
  errors/
  daily/
  .sidecar_buffer/
```

The assistant-facing sidecar should watch both legacy directories and the new
runtime/OMS export directories. Keep the existing sidecar retry, HMAC, gzip,
and duplicate handling.

## 5. Canonical Identity And Lineage

### 5.1 Default Identity Values

Use these repo-specific defaults unless deployment config overrides them:

| Field | Default or source |
|---|---|
| `bot_id` | `k_stock_trader` |
| `family_id` | `krx_equity` for KALCB/OLR production events; `krx_pcim_research` for PCIM research events if PCIM remains instrumented |
| `portfolio_id` | `olr_kalcb` for the combined runtime portfolio |
| `account_alias` | `KIS_ACCOUNT_ALIAS`, `ACCOUNT_ALIAS`, or a stable non-secret value such as `kis_primary` |
| `strategy_id` | `KALCB`, `OLR`, `PCIM`, or `_UNKNOWN_` when the OMS cannot attribute drift |
| `data_source_id` | `kis_rest`, `kis_websocket`, `postgres_oms`, `runtime_session`, or `offline_replay` |
| `exchange` | `KRX` |
| `asset_class` | `kr_equity` |
| `currency` | `KRW` |
| `timezone` | `Asia/Seoul` |

### 5.2 Required Lineage Fields

Monthly-critical strategy, runtime, portfolio, and OMS events should carry:

| Field | Requirement |
|---|---|
| `strategy_id` | Required for strategy-attributed events |
| `family_id` | Required when known |
| `portfolio_id` | Required for runtime, OMS, portfolio, allocation, risk, and order events |
| `account_alias` | Required for OMS/portfolio events; never raw KIS account secrets |
| `strategy_version` | Required for authoritative validation |
| `config_version` | Required for strategy behavior attribution |
| `portfolio_config_version` | Required for portfolio arbitration attribution |
| `risk_config_version` | Required for OMS/risk attribution |
| `allocation_version` | Required for allocation and sizing attribution |
| `strategy_registry_version` | Recommended for active strategy set attribution |
| `deployment_id` | Required and stable for the running deployment |
| `parameter_set_id` | Required when strategy parameters affect decisions |
| `experiment_id` | Empty string unless a test/shadow/deployment experiment is active |
| `variant_id` | Empty string unless an experiment variant is active |
| `code_sha` | Required for authoritative validation |
| `proposal_ids` | Include when a `trading_assistant` proposal caused deployment |
| `suggestion_ids` | Include when a suggestion tracker item caused deployment |

If a value is missing, emit the event anyway and also emit a `bot_error` or
heartbeat warning with `lineage_gap=true`. Missing lineage must block
authoritative monthly validation, but it must not block trading.

### 5.3 Join Keys

Preserve and propagate existing join keys. Do not replace them with a new
random UUID layer.

| Existing key | Source | Use |
|---|---|---|
| `bar_id` | `MarketBar` symbol/timeframe/timestamp or metadata | Joins signal, decision, filter, indicator, market, and replay rows |
| `event_ref` | `RuntimeSessionDriver._event_ref()` | Runtime input identity |
| `decision_ref` | `RuntimeActionRouter.record_decisions()` | Decision event identity |
| `action_ref` | `RuntimeActionRouter._prepare_action()` | Strategy action identity |
| `provisional_order_ref` | `ActionCollector.submit()` | Stable runtime order identity before broker/OMS order ID exists |
| `portfolio_decision_ref` | `RuntimeActionRouter._route_prepared_action()` | Portfolio arbitration decision identity |
| `intent_id` | `oms.intent.Intent` | OMS intent identity |
| `idempotency_key` | `oms.intent.Intent` | OMS dedup identity |
| `oms_order_id` | Postgres `orders.oms_order_id` | OMS persistent order UUID |
| `kis_order_id` | KIS broker order ID | Broker order identity |
| `kis_order_date` | KIS broker order date | Needed to disambiguate KIS IDs |
| `kis_exec_id` | Postgres `fills.kis_exec_id` | Fill dedup identity |
| `trade_id` | Runtime/OMS trade lifecycle | Completed trade identity |
| `artifact_hash` | KALCB/OLR candidate snapshots | Strategy artifact attribution |
| `source_fingerprint` | KALCB/OLR artifacts and bars | Data/artifact source attribution |
| `kis_resource_plan_hash` | `KISResourcePlan.plan_hash` | KIS resource budget attribution |

### 5.4 Event IDs And Revisions

Keep the existing deterministic event ID formula:

```python
raw = f"{bot_id}|{exchange_timestamp.isoformat()}|{event_type}|{payload_key}"
event_id = sha256(raw.encode("utf-8")).hexdigest()[:16]
```

Add two fields for mutable logical facts:

- `logical_event_id`: stable identity for the real-world opportunity, trade,
  config snapshot, or allocation state.
- `revision`: integer, starting at 0.

Use a different `payload_key` per revision when a backfill updates an earlier
logical event:

```text
missed opportunity revision 0:
  logical_event_id = "KALCB:005930:2026-05-31T09:35:00+09:00:spread_gate"
  payload_key = "{logical_event_id}:rev:0"

missed opportunity revision 1:
  logical_event_id = same as above
  payload_key = "{logical_event_id}:rev:1"
```

This is essential because the relay deduplicates by `event_id`. Rewriting a
previous JSONL row or reusing the same event ID can cause backfilled outcomes
to disappear.

## 6. Sidecar Contract

Update `instrumentation/src/sidecar.py` after the shared envelope helpers
exist.

Required changes:

- keep support for JSONL and daily JSON files;
- keep skip-forwarding entry-stage `trade` records as canonical performance
  trades;
- add watched directories for `decisions`, `strategy_actions`,
  `portfolio_rules`, `risk_decisions`, `fills`, `positions`, `allocations`,
  `portfolio`, `config_snapshots`, `deployments`,
  `resource_plans`, `market_data`, and `reconciliations`;
- preserve HMAC and gzip behavior;
- preserve 409 duplicate handling as success;
- duplicate lineage fields at the envelope level when present in payload;
- include `scope` as `strategy`, `portfolio`, `oms`, or `family`;
- support `payload` as an object in local files and serialize to canonical JSON
  string only at the wire boundary if the relay still expects a string;
- expose sidecar diagnostics in `heartbeat` events.

Recommended event priority overrides:

| Event type | Priority |
|---|---:|
| `bot_error`, `error`, `risk_halt`, `reconciliation_alert` | 0 |
| `deployment`, `config_snapshot`, `daily_snapshot`, `session_closeout` | 1 |
| `trade`, `fill` | 2 |
| `missed_opportunity`, `order`, `portfolio_rule`, `risk_decision`, `parameter_change` | 3 |
| `decision_event`, `strategy_action`, `indicator_snapshot`, `filter_decision`, `market_snapshot`, `position_snapshot`, `allocation_snapshot`, `portfolio_snapshot`, `resource_plan`, `market_data_subscription` | 4 |
| `heartbeat` | 5 |

## 7. Retrofit The Existing `instrumentation/` Package

The existing package is valuable. Upgrade it to the canonical contract so PCIM
and any future direct strategy integration remain compatible with KALCB/OLR
runtime telemetry.

### 7.1 `event_metadata.py`

Change `EventMetadata` additively:

- keep current fields and `compute_event_id()`;
- add optional `schema_version`;
- add optional `strategy_id`, `family_id`, `portfolio_id`, `account_alias`;
- add optional `strategy_version`, `config_version`,
  `portfolio_config_version`, `risk_config_version`, `allocation_version`,
  `strategy_registry_version`, `deployment_id`, `parameter_set_id`,
  `experiment_id`, `variant_id`, `code_sha`;
- add optional `trace_id`, `decision_id`, `logical_event_id`, `revision`;
- add `scope`;
- add `exchange`, `asset_class`, `currency`, and `timezone` defaults for KRX.

Add helper constructors:

- `create_event_metadata(...)` for generic events;
- `create_revision_metadata(...)` for mutable backfills;
- `metadata_from_runtime(...)` for runtime session rows;
- `metadata_from_oms(...)` for OMS events.

### 7.2 `trade_logger.py`

Keep the current `TradeEvent` shape and add fields:

- `event_type: "trade"`;
- `schema_version: "trade_event_v2"`;
- top-level lineage fields from `LineageContext`;
- `bar_id`, `trace_id`, `decision_id`, `event_ref`, `decision_ref`;
- `action_ref`, `provisional_order_ref`, `portfolio_decision_ref`;
- `intent_id`, `idempotency_key`, `oms_order_id`, `kis_order_id`,
  `kis_order_date`;
- `entry_fill_id`, `exit_fill_id`, `entry_kis_exec_id`, `exit_kis_exec_id`;
- `entry_order_event_refs`, `exit_order_event_refs`;
- `artifact_hash`, `source_fingerprint`, `candidate_hash`,
  `kis_resource_plan_hash`;
- `portfolio_policy_hash`;
- KRX fields: `exchange`, `market`, `krx_trade_date`, `currency`;
- portfolio fields: `allocation_version`, `portfolio_config_version`,
  `risk_config_version`, `strategy_registry_version`;
- trade accounting fields: `commission`, `tax`, `fees_paid`, `gross_pnl`,
  `net_pnl`, `realized_pnl_krw`.

Do not make the strategy engines call `on_entry_fill()` directly for KALCB/OLR
unless the fill is known. The active runtime should derive completed trade
events from OMS fills and `trade_outcomes.jsonl`, then enrich from the original
decision/action metadata.

### 7.3 `missed_opportunity.py`

Current implementation rewrites JSONL rows in `_update_event()`. Replace that
with append-only revisions.

Implementation details:

- compute `logical_event_id` from strategy, symbol, bar ID or signal time,
  signal ID, side, and blocker;
- write revision 0 when the signal is blocked;
- write revision 1+ when outcomes are backfilled;
- keep all previous fields for compatibility;
- add `blocked_scope` with values such as `strategy_filter`,
  `portfolio_rule`, `oms_risk`, `resource_plan`, `market_data`, or
  `execution`;
- include `portfolio_decision_ref`, `risk_decision_id`, `blocking_positions`,
  and `resource_conflict_type` when the miss is caused by portfolio/OMS;
- add KALCB and OLR simulation policies to
  `instrumentation/config/simulation_policies.yaml`;
- include KRX assumptions: long-only equities, KRW, KRX session, VI/cooldown
  effects when known, close-auction assumptions for OLR, commissions/taxes, and
  no funding.

### 7.4 `filter_logger.py` And `indicator_logger.py`

Add:

- `event_metadata`;
- `schema_version`;
- `strategy_id`;
- `family_id`;
- `portfolio_id`;
- `decision_id`;
- `event_ref`;
- `bar_id`;
- `trace_id`;
- lineage fields;
- `filter_group` such as `entry`, `exit`, `portfolio`, `risk`, or
  `data_quality`;
- `threshold_operator`;
- `margin_pct` or `distance_to_threshold`;
- `input_refs` for indicator values or bars used by the gate.

Update event IDs to avoid same-symbol/same-filter collisions. Use:

```text
{strategy_id}:{symbol}:{bar_id}:{signal_id}:{filter_name}:{sequence}
```

### 7.5 `order_logger.py`

Add OMS and KIS fields:

- `intent_id`;
- `idempotency_key`;
- `action_ref`;
- `provisional_order_ref`;
- `portfolio_decision_ref`;
- `oms_order_id`;
- `kis_order_id`;
- `kis_order_date`;
- `kis_exec_id` when status is fill-related;
- `status_before`;
- `status_after`;
- `broker_status`;
- `order_submitted_at`;
- `oms_received_at`;
- `fill_ts`;
- `cancel_after_sec`;
- `branch`;
- `execution_style`, including `CLOSE_AUCTION`;
- `risk_decision_id`;
- `risk_reason`;
- `resource_conflict_type`.

Use `order` events for lifecycle states and `fill` events for fills. Keep
order status events even when there is no fill.

### 7.6 `heartbeat.py`

Extend heartbeat payloads with:

- lineage summary;
- runtime mode: `artifact_only_stage1`, `artifact_only`, `dry_run`, `paper`,
  or `live`;
- active strategies;
- session recorder root;
- sidecar diagnostics;
- OMS health;
- KIS circuit breaker state;
- reconciliation status;
- allocation drift count;
- pending order count;
- resource plan hash;
- current artifact hashes;
- `lineage_gap` and missing lineage fields;
- `instrumentation_queue_depth`;
- `last_successful_forward_at`.

Emit at stable intervals and on startup/shutdown.

### 7.7 `daily_snapshot.py`

The current daily snapshot is mono-strategy oriented. Preserve it, but add a
portfolio-aware KALCB/OLR path.

Add:

- `schema_version`;
- `event_metadata`;
- lineage summary;
- `portfolio_id`;
- `account_alias`;
- `per_strategy_summary` for `KALCB` and `OLR`;
- `per_family_summary` for `krx_equity`;
- `portfolio_summary`;
- `resource_plan_summary`;
- `oms_summary`;
- `allocation_summary`;
- `risk_summary`;
- `lineage_gap`;
- `data_completeness`;
- `session_manifest_path`;
- `parity_report_path` when available.

The daily snapshot should reconcile to:

- completed trade events;
- OMS trades table or `trade_outcomes.jsonl`;
- `risk_daily_strategy`;
- `risk_daily_portfolio`;
- session recorder closeout metrics.

### 7.8 `process_scorer.py`

Keep current KRX-specific scoring, but map root causes to the assistant's
canonical taxonomy while preserving local aliases.

Recommended mapping:

| Current tag | Canonical tag |
|---|---|
| `high_entry_slippage` | `slippage_spike` |
| `high_exit_slippage` | `slippage_spike` |
| `risk_limit_breach` | `risk_cap_hit` |
| `stale_data` | `data_gap` |
| `execution_timeout` | `latency_spike` |
| `partial_fill` | `order_reject` or `normal_loss`, depending on outcome |
| `spread_blow_out` | `slippage_spike` |
| `wrong_direction` | `regime_mismatch` or `weak_signal`, depending on evidence |

Also add positive tags where evidence supports them:

- `good_execution`;
- `regime_aligned`;
- `strong_signal`;
- `filter_saved_bad`;
- `normal_win`;
- `normal_loss`;
- `exceptional_win`.

Do not delete existing root-cause values because tests or old reports may rely
on them. Emit both `root_causes` and `canonical_root_causes`.

### 7.9 `config_watcher.py`

The current watcher tracks stale module names. Replace it with effective file
and object snapshots.

Watch and hash:

- `config/kalcb.yaml`;
- `config/olr_kalcb/olr_deployment_universe_103.yaml`;
- `config/olr_kalcb/portfolio_policy.conservative.json`;
- `config/olr/sector_map.yaml`;
- `config/oms_config.yaml`;
- `config/optimization/kalcb.yaml`;
- `config/optimization/olr.yaml`;
- active artifact snapshots under `data/strategy/kalcb` and
  `data/strategy/olr`;
- runtime `strategy_config_summaries`;
- `kis_resource_plan.json`;
- relevant environment settings after redaction.

Emit both:

- `config_snapshot` on startup and reload;
- `parameter_change` for diffs.

## 8. Integrate The Active KALCB/OLR Runtime

The active runtime already records the evidence the assistant needs. The work
is to export it canonically.

### 8.1 Add A Runtime Exporter

Add an exporter such as `instrumentation/src/runtime_exporter.py`.

Responsibilities:

- accept a `LineageContext`;
- write assistant events through `EventWriter`;
- convert session recorder rows into canonical payloads;
- never raise into runtime code;
- deduplicate only by deterministic `event_id`;
- retain raw session row under `runtime_evidence` when useful.

Suggested public methods:

```python
class RuntimeAssistantExporter:
    def emit_session_started(self, plan, manifest_payload): ...
    def emit_runtime_event_input(self, row): ...
    def emit_decision_event(self, row): ...
    def emit_no_action(self, row): ...
    def emit_strategy_action(self, row): ...
    def emit_portfolio_rule(self, row): ...
    def emit_oms_intent(self, row): ...
    def emit_order_result(self, row): ...
    def emit_fill_event(self, row): ...
    def emit_trade_outcome(self, row): ...
    def emit_state_snapshot(self, row): ...
    def emit_subscription_event(self, row): ...
    def emit_resource_route_suppression(self, row): ...
    def emit_session_closeout(self, plan, manifest_payload): ...
```

The exporter can live under `instrumentation/src/` and be imported from the
runtime. If import fails, runtime must continue with only local session capture.

### 8.2 Hook `prepare_runtime_session()`

File:
`_references/k_stock_trader/deployment/olr_kalcb/runtime.py`

After `session_recorder.write_manifest(...)`, emit:

- `deployment`;
- `config_snapshot`;
- `portfolio_policy_snapshot`;
- `resource_plan`;
- `portfolio_snapshot` for initial account/positions;
- `allocation_snapshot` for initial per-strategy allocations;
- `position_snapshot` for initial positions;
- `state_snapshot` for KALCB and OLR pre-start state.

The existing manifest already includes:

- `mode`;
- `strategy_ids`;
- `strategy_configs`;
- `portfolio_enabled`;
- `portfolio_policy_config`;
- `portfolio_policy_hash`;
- `sector_map`;
- `staged_artifacts`;
- `kis_resource_plan_hash`;
- `kis_resource_plan_path`;
- `initial_account_state`;
- `initial_positions`.

Use these values as lineage, not as a separate source of truth.

### 8.3 Hook OLR Final Enablement

File:
`_references/k_stock_trader/deployment/olr_kalcb/runtime.py`

`RuntimeSessionPlan.enable_olr_final()` already stages the final OLR artifact
and rewrites the runtime manifest. Emit:

- `deployment` or `runtime_stage_change` with `status="olr_final_enabled"`;
- `config_snapshot` for the approved OLR final config;
- `resource_plan` revision with the new `kis_resource_plan_hash`;
- `state_snapshot` for OLR initial state;
- `portfolio_snapshot` showing the portfolio state at enablement.

This event is important because OLR has a two-stage day: stage1 pre-session
artifact and final 14:30 KST artifact.

### 8.4 Hook `RuntimeSessionDriver._begin_event()`

File:
`_references/k_stock_trader/deployment/olr_kalcb/session_driver.py`

This method already writes a `runtime_event_input` row to
`decision_stream.jsonl`. Also emit a canonical `decision_event` or
`runtime_event_input` event with:

- `strategy_id`;
- `event_ref`;
- `event_type` (`bar`, `fill`, `timer`, `order_event`);
- `event_sequence`;
- `timestamp`;
- `payload_hash`;
- `event_input_hash`;
- `bar_hash` and `bar_row_key` for bar events;
- `bar_id`;
- `source_artifact_hash`;
- `source_fingerprint`;
- lineage;
- `portfolio_context_hash` if available.

Use `event_ref` as a core join key. Do not generate a separate unrelated
decision identity.

### 8.5 Hook `RuntimeActionRouter.record_decisions()`

File:
`_references/k_stock_trader/deployment/olr_kalcb/action_router.py`

This method writes `decision_event` rows and computes `decision_ref`. Export
each row as canonical `decision_event`.

Include:

- original `DecisionEvent` fields;
- `decision_ref`;
- `event_ref`;
- `event_type`;
- `decision_code`;
- `reason`;
- `state_snapshot_ref`;
- action summaries;
- action refs if known;
- full metadata, after redaction;
- lineage.

For no-action rows from `_record_no_action()`, emit the same event type with:

- `decision_code="NO_ACTION"`;
- `reason_code`;
- `action_count=0`.

No-action events matter. They let replay prove that a bar was evaluated and
correctly produced no order.

### 8.6 Hook `RuntimeActionRouter._route_prepared_action()`

File:
`_references/k_stock_trader/deployment/olr_kalcb/action_router.py`

This is the portfolio/OMS transformation point.

Emit `strategy_action` after `strategy_actions.jsonl` is written:

- `action_ref`;
- `event_ref`;
- `decision_ref`;
- `strategy_action_hash`;
- `strategy_id`;
- `symbol`;
- `action_type`;
- `source_artifact_hash`;
- `source_fingerprint`;
- `candidate_hash`;
- original action payload;
- lineage.

Emit `portfolio_rule` after `portfolio_arbitration.jsonl` is written:

- `portfolio_decision_ref`;
- `action_ref`;
- `strategy_id`;
- `symbol`;
- `side`;
- `decision`: `accepted`, `blocked`, `resized`, or `deferred`;
- `reason_code`;
- `policy_hash`;
- `policy_config`;
- `requested_qty`;
- `approved_qty`;
- `requested_notional`;
- `approved_notional`;
- `sector`;
- current strategy, symbol, sector, and portfolio exposure;
- current cash and equity;
- admitted batch reservations;
- pending router reservations;
- source artifact hashes;
- lineage.

Emit `order` or `oms_intent` when `oms_intents.jsonl` is written:

- normalized intent payload;
- `intent_id`;
- `idempotency_key`;
- `event_ref`;
- `action_ref`;
- `provisional_order_ref`;
- `portfolio_decision_ref`;
- `dry_run`;
- `submitted_to_broker`;
- lineage.

Emit an `order` event after the OMS result row is written:

- `intent_id`;
- `order_id`;
- `status`;
- `message`;
- `modified_qty`;
- `cooldown_until`;
- `blocking_positions`;
- `resource_conflict_type`;
- `oms_received_at`;
- `order_submitted_at`;
- `portfolio_decision_ref`;
- lineage.

### 8.7 Hook Fills And Trade Outcomes

File:
`_references/k_stock_trader/deployment/olr_kalcb/session_driver.py`

`handle_fill()` already writes `runtime_fill_event`, applies portfolio context,
and `_record_trade_outcome()` writes `trade_outcomes.jsonl` for sell fills.

Export:

- `fill` for every fill event;
- `trade` when `_record_trade_outcome()` creates a realized outcome;
- `position_snapshot` after applying the fill;
- `allocation_snapshot` after applying the fill.

The trade event should merge:

- `trade_outcomes.jsonl` row;
- original entry metadata from strategy state;
- fill metadata;
- route metadata such as `portfolio_decision_ref`, `intent_id`, and
  `broker_order_id`;
- artifact/config/resource lineage from the runtime plan.

### 8.8 Hook Market Data Resource Events

File:
`_references/k_stock_trader/deployment/olr_kalcb/market_data_coordinator.py`

Export every `SubscriptionEvent` as `market_data_subscription`:

- `strategy_id`;
- `lease_name`;
- `symbol`;
- `action`;
- `registration_type`;
- `ws_used_before`;
- `ws_used_after`;
- `ws_budget`;
- `kis_resource_plan_hash`;
- `market_data_source`;
- `reason_code`;
- lineage.

Export route suppressions from `_record_resource_route_suppression()` as
`resource_route_suppression` or `market_data_subscription` with
`action="suppressed"`. These explain missed bars and strategy no-action
periods caused by resource-plan windows.

### 8.9 Hook Session Closeout

File:
`_references/k_stock_trader/deployment/olr_kalcb/session_capture.py`

`PaperSessionRecorder.close_session()` seals the hash contract. After closeout,
emit:

- `session_closeout`;
- `daily_snapshot`;
- `portfolio_snapshot`;
- `position_snapshot`;
- `allocation_snapshot`;
- `resource_plan` final state.

Include:

- `hash_contract_version`;
- `hash_contract_status`;
- `expected_hashes_complete`;
- `closeout_missing_required_files`;
- `closeout_missing_required_dirs`;
- `closeout_missing_artifact_evidence`;
- `closeout_missing_resource_plan`;
- `closeout_missing_hash_groups`;
- `session_metrics`;
- `expected_hashes`.

## 9. Instrument The OMS

The OMS is production truth for risk, orders, fills, allocations, positions,
and reconciliation. Postgres persistence is not enough because the assistant
ingests sidecar events. Add a fail-open OMS event emitter.

### 9.1 Add `OMSEventEmitter`

Add `instrumentation/src/oms_exporter.py` or `oms/instrumentation.py`.

Requirements:

- writes JSONL under `instrumentation/data/`;
- has no dependency on Postgres availability;
- never raises into OMS logic;
- uses the same `LineageContext`;
- can be disabled by config;
- has bounded write failures and emits a heartbeat warning if unavailable.

Recommended integration:

- create emitter in `oms/server.py` lifespan after config and `oms_id` are
  loaded;
- pass emitter into `OMSCore`;
- store it as `self.event_emitter`;
- every emit call is wrapped in a local helper such as `_emit_oms_event()`.

### 9.2 Add Risk Decision Traces

File:
`_references/k_stock_trader/oms/risk.py`

`RiskGateway.check()` currently returns only a compact `RiskResult`. Add a
trace structure while preserving current behavior.

Recommended dataclasses:

```python
@dataclass
class RiskRuleEvaluation:
    rule_name: str
    result: str              # pass | reject | modify | defer
    threshold: Any = None
    observed: Any = None
    reason: str = ""
    modified_qty: int | None = None
    blocking_positions: list[dict] | None = None
    resource_conflict_type: str = ""

@dataclass
class RiskTrace:
    trace_id: str
    evaluations: list[RiskRuleEvaluation]
    final_decision: str
    final_reason: str
```

Attach `trace` to `RiskResult`. Every existing check should append a rule
evaluation:

- `equity_loaded`;
- `safe_mode`;
- `flatten_in_progress`;
- `halt_new_entries`;
- `paused_strategy`;
- `frozen_symbol`;
- `daily_loss_warn`;
- `daily_loss_halt`;
- `max_positions_count`;
- `gross_exposure`;
- `regime_exposure_cap`;
- `per_symbol_position_pct`;
- `sector_cap`;
- `strategy_budget_positions`;
- `strategy_budget_risk`;
- `vi_cooldown`.

Emit `risk_decision` from `OMSCore._process_intent()` after `risk.check()`.

Payload should include:

- intent identity;
- final decision;
- final reason;
- final approved/modified quantity;
- every rule evaluation;
- thresholds and observed values;
- blocking positions;
- current state summary;
- `risk_config_version`;
- lineage.

### 9.3 Emit Intent Lifecycle

File:
`_references/k_stock_trader/oms/oms_core.py`

Emit:

- `oms_intent_received` at the start of `submit_intent()`;
- `oms_intent_duplicate` when idempotency returns a cached result;
- `oms_intent_validation_failed` when `intent.validate()` fails;
- `risk_decision` after `RiskGateway.check()`;
- `oms_arbitration_decision` after `ArbitrationEngine.arbitrate()`;
- `order_plan` after `OrderPlanner` creates a plan;
- `order` for submit accepted/rejected/deferred/executed;
- `bot_error` for unexpected adapter exceptions.

Each event must include:

- `intent_id`;
- `idempotency_key`;
- `intent_type`;
- `strategy_id`;
- `symbol`;
- `desired_qty`;
- `target_qty`;
- `urgency`;
- `time_horizon`;
- constraints;
- risk payload;
- signal hash;
- safe redacted metadata.

### 9.4 Emit Order And Fill Lifecycle

Files:

- `_references/k_stock_trader/oms/oms_core.py`
- `_references/k_stock_trader/oms/persistence.py`

Emit `order` events at:

- order planned;
- broker submit attempted;
- broker submit rejected;
- broker submit accepted;
- working order persisted;
- partial fill;
- fill;
- inferred fill;
- timeout cancel;
- EOD cancel;
- cancel rejected;
- order missing from broker;
- terminal status update.

Emit `fill` events in `_apply_fill()` with:

- `kis_exec_id`;
- `order_id`;
- `oms_order_id`;
- `intent_id`;
- `strategy_id`;
- `symbol`;
- `side`;
- `qty`;
- `price`;
- `fill_ts`;
- `commission`;
- `tax`;
- `inferred`;
- previous and new allocation;
- realized PnL for sell fills;
- lineage.

Do not rely only on Postgres `fills` rows. The assistant needs sidecar-visible
fill evidence.

### 9.5 Emit Position And Allocation Snapshots

Files:

- `_references/k_stock_trader/oms/oms_core.py`
- `_references/k_stock_trader/oms/state.py`

Emit `position_snapshot` and `allocation_snapshot`:

- after initial reconciliation;
- after every fill;
- after drift repair or freeze;
- at a throttled interval during reconciliation;
- at EOD cleanup;
- at shutdown.

Position payload:

- `portfolio_id`;
- `account_alias`;
- `symbol`;
- `real_qty`;
- `avg_price`;
- `current_price`;
- `hard_stop_px`;
- `frozen`;
- working orders count;
- entry lock owner/until;
- cooldown and VI cooldown;
- total allocated qty;
- drift;
- `_UNKNOWN_` allocation if present.

Allocation payload:

- `strategy_id`;
- `symbol`;
- `qty`;
- `cost_basis`;
- `entry_ts`;
- `soft_stop_px`;
- `time_stop_ts`;
- `entry_intent_id`;
- realized/unrealized PnL if known;
- allocation version;
- lineage.

### 9.6 Emit Reconciliation Events

File:
`_references/k_stock_trader/oms/oms_core.py`

The current `_check_allocation_drift()` logic is important. Emit
`reconciliation_alert` or `reconciliation_event` when:

- position sync changes broker qty;
- working order is missing from broker;
- inferred fill is created;
- positive drift is assigned to `_UNKNOWN_`;
- negative drift is auto-corrected;
- symbol is frozen;
- symbol is unfrozen;
- admin resolves drift;
- EOD cleanup cancels or finalizes orders.

Each event should include:

- before/after values;
- action;
- reason;
- strategy IDs involved;
- symbol;
- drift amount;
- frozen before/after;
- manual/admin flag;
- lineage.

### 9.7 Emit Risk Control Changes

File:
`_references/k_stock_trader/oms/server.py`

Emit events from endpoints:

- `/api/v1/risk/regime`;
- `/api/v1/risk/vi-cooldown`;
- `/api/v1/risk/safe-mode`;
- `/api/v1/admin/flatten-all`;
- `/api/v1/admin/eod-cleanup`;
- `/api/v1/admin/pause-strategy/{strategy_id}`;
- `/api/v1/admin/resume-strategy/{strategy_id}`;
- `/api/v1/admin/resolve-drift`;
- `/api/v1/admin/correct-allocation`.

These are portfolio/risk behavior changes. They must be attributable even when
they are manual.

## 10. Portfolio-Level Instrumentation

Portfolio-level telemetry is the largest difference between old reporting and
the optimal learning loop.

### 10.1 Portfolio Arbitration Events

The current `PortfolioArbitrationPolicy` is compact and useful, but the
assistant needs full state and thresholds.

For every routed action, emit `portfolio_rule` with:

- `portfolio_decision_ref`;
- `policy_hash`;
- `portfolio_policy_config`;
- `strategy_priority`;
- `strategy_id`;
- `symbol`;
- `side`;
- `decision`;
- `reason_code`;
- `intended_qty`;
- `final_qty`;
- `intended_notional`;
- `final_notional`;
- `cash`;
- `equity`;
- `current_portfolio_exposure`;
- `current_strategy_exposure`;
- `current_symbol_exposure`;
- `current_sector_exposure`;
- `current_strategy_symbol_qty`;
- `current_symbol_qty`;
- `admitted_gross`;
- `admitted_symbol`;
- `admitted_sector`;
- `pending_reservations`;
- `max_gross_notional`;
- `max_symbol_notional`;
- `max_sector_notional`;
- `candidate_rank`;
- `candidate_score_band`;
- `route_family`;
- source artifact hashes;
- lineage.

Map current reason codes into assistant-friendly categories:

| Current reason | Category |
|---|---|
| `accepted` | `accepted` |
| `accepted_exit_reduces_exposure` | `accepted` |
| `resized_to_capacity` | `portfolio_resized` |
| `resized_to_existing_exposure` | `portfolio_resized` |
| `zero_quantity_or_notional` | `sizing_block` |
| `missing_or_zero_account_state` | `account_state_gap` |
| `duplicate_symbol_conflict` | `symbol_collision` |
| `capital_or_exposure_limit` | `risk_cap_hit` |
| `capacity_below_min_quantity` | `risk_cap_hit` |
| `exit_capacity_below_min_quantity` | `position_state_gap` |
| `unsupported_short_or_unmatched_exit` | `position_state_gap` |

### 10.2 Portfolio Snapshot

Emit `portfolio_snapshot`:

- at runtime startup;
- after `PortfolioContextProvider.refresh()`;
- after every fill;
- after risk-control changes;
- after reconciliation;
- at EOD closeout.

Payload:

- `portfolio_id`;
- `account_alias`;
- `equity_krw`;
- `buyable_cash_krw`;
- `daily_pnl_krw`;
- `daily_pnl_pct`;
- `gross_exposure_krw`;
- `gross_exposure_pct`;
- `positions_count`;
- `working_orders_count`;
- `safe_mode`;
- `halt_new_entries`;
- `flatten_in_progress`;
- `regime`;
- `regime_exposure_cap`;
- `allocation_drift_count`;
- `sector_exposures`;
- `strategy_exposures`;
- `symbol_exposures`;
- `pending_reservations`;
- `portfolio_config_version`;
- `risk_config_version`;
- `allocation_version`;
- lineage.

### 10.3 Approval-Ready Closeout Scope

For the `approval_ready` path, emit closeout evidence that ties the runtime
session to decisions, actions, OMS intents, fills, reconciliation, artifacts,
configs, and resource-plan state. Do not make monitoring-only analytics part
of the approval gate. Sector exposure should be present in portfolio-rule and
risk-decision payloads when it affects a decision.

## 11. Config, Artifact, And Deployment Instrumentation

### 11.1 Effective Config Snapshots

Add `instrumentation/src/config_snapshot.py`.

Compute hashes from effective runtime config, not just raw file bytes.

Recommended versions:

- `config_version`: hash of effective KALCB/OLR strategy configs and runtime
  config summaries;
- `portfolio_config_version`: hash of
  `PortfolioPolicyConfig`/`portfolio_policy.conservative.json`;
- `risk_config_version`: hash of `RiskConfig` built from `oms_config.yaml`;
- `allocation_version`: hash of active OMS allocations and configured capital
  allocation assumptions;
- `strategy_registry_version`: hash of active strategy IDs, family mapping,
  runtime mode, and artifact stages;
- `kis_resource_plan_hash`: already computed by `KISResourcePlan`;
- `parameter_set_id`: per-strategy hash of strategy parameters that affect
  decisions.

Snapshot payload should include:

- versions and hashes;
- effective configs;
- source files and file hashes;
- artifact summaries;
- redacted environment inputs;
- redacted keys list;
- generated timestamp;
- lineage.

### 11.2 Deployment Events

Emit `deployment` at:

- OMS startup;
- runtime session creation;
- OLR final enablement;
- config reload;
- paper/live mode change;
- shutdown.

Required fields:

- `deployment_id`;
- `bot_id`;
- `portfolio_id`;
- `account_alias`;
- `mode`;
- `strategy_ids`;
- `strategy_version`;
- `config_version`;
- `portfolio_config_version`;
- `risk_config_version`;
- `allocation_version`;
- `strategy_registry_version`;
- `kis_resource_plan_hash`;
- `code_sha`;
- `artifact_hashes`;
- `source_fingerprints`;
- `status`;
- `deployed_at` or event timestamp;
- `source`;
- `proposal_ids`;
- `suggestion_ids`.

Do not generate a new `deployment_id` per event. It should be stable for a
code/config/artifact deployment. A process restart with identical code/config
can keep the same deployment ID and emit `status="restarted"`.

### 11.3 Approval-Grade Deployment Metadata Emitter

The `deployment` event is assistant telemetry. `approval_ready` also requires a
dedicated runtime-emitted metadata artifact that can be imported into
`trading_assistant_backtest/contracts/k_stock_olr_kalcb/deployment_metadata.json`.
Generate it from the running KALCB/OLR bot or VPS process, not from a local
assistant checkout.

Required fields:

```json
{
  "metadata_source": "live_bot_runtime_deployment_metadata_v1",
  "emission_environment": "production_vps",
  "repo_url": "https://github.com/<owner>/<repo>",
  "source_control_origin": "https://github.com/<owner>/<repo>",
  "deployed_commit_sha": "<git commit sha>",
  "source_control_commit_sha": "<same git commit sha>",
  "source_control_worktree_clean": true,
  "bot_id": "k_stock_trader",
  "portfolio_id": "olr_kalcb",
  "strategy_id": "OLR_KALCB",
  "config_hash": "<effective KALCB/OLR runtime config hash>",
  "strategy_version": "<deployed OLR/KALCB strategy version>",
  "config_version": "<effective OLR/KALCB config version>",
  "deployment_id": "<stable deployment id>",
  "telemetry_schema_version": "olr_kalcb_decision_stream_v1",
  "strategy_plugin_contract_path": "trading_assistant_backtest/contracts/k_stock_olr_kalcb/strategy_plugin_contract.json",
  "strategy_plugin_contract_hash": "<sha256 of final strategy_plugin_contract.json>",
  "emitted_at_utc": "YYYY-MM-DDTHH:MM:SSZ",
  "live_runtime_started_at_utc": "YYYY-MM-DDTHH:MM:SSZ",
  "runtime_entrypoint": "<module:function or command>",
  "runtime_instance_id": "<stable process/session id>",
  "runtime_host_fingerprint": "<non-secret host fingerprint>",
  "dry_run": false
}
```

`metadata_source` must be `live_bot_runtime_deployment_metadata_v1` or
`vps_live_bot_runtime_deployment_metadata_v1`. `emission_environment` must be
`live_bot`, `vps`, `paper_vps`, or `production_vps`; prefer `paper_vps` or
`production_vps` when emitted on a VPS. `repo_url` and
`source_control_origin` must be the same real Git remote, never `local://`.
`source_control_worktree_clean` must be `true`. `source_control_commit_sha`
must match `deployed_commit_sha`.

Promotion rule:

Do not set `k_stock_olr_kalcb` to `maturity = "approval_ready"` until this
metadata artifact exists, its contract hash matches the final contract file,
the deployed SHA matches `live_repo_commit_sha`, and the five validation tests
still pass.

### 11.4 OMS Config Caveat

`config/oms_config.yaml` currently lists a `PCIM` strategy budget, while the
active combined runtime is `KALCB`/`OLR`. For optimal instrumentation, make this
explicit.

Preferred implementation:

- add `KALCB` and `OLR` budget entries if the OMS is meant to enforce
  strategy-specific budgets for them;
- compute `risk_config_version` after defaults and these budgets are applied;
- emit a `config_snapshot` proving the budget state.

If KALCB/OLR intentionally rely only on portfolio policy and global OMS risk
limits, do not invent budgets. Emit a `risk_config_warning` or config snapshot
field:

```json
{
  "active_strategy_budget_status": {
    "KALCB": "missing_uses_global_limits",
    "OLR": "missing_uses_global_limits"
  }
}
```

## 12. KRX And KIS Specific Requirements

Add KRX/KIS-specific fields where relevant:

- `exchange: "KRX"`;
- `currency: "KRW"`;
- six-digit symbol strings with zero padding;
- KST timestamps and UTC timestamps;
- `krx_trade_date`;
- trading session phase: `pre_open`, `regular`, `close_auction`,
  `post_close`, `closed`;
- VI/cooldown state when known;
- KIS order fields: `kis_order_id`, `kis_order_date`, `branch`;
- KIS execution fields: `kis_exec_id`, fill timestamp, fill quantity, fill
  price;
- KRX tax/commission fields;
- `execution_style`, especially `CLOSE_AUCTION` for OLR;
- `auction_fill_time`, `auction_nonfill_key`, and close-auction assumptions;
- bid/ask availability flag because KRX bid/ask may not be available for all
  paths.

Do not emit crypto-only fields such as funding/open interest as meaningful
values for KRX equities. It is fine to keep compatibility fields as `null` or
`0.0`, but do not let them imply that funding was evaluated.

## 13. Event Catalog For This Repo

| Event type | Producer | Implementation target |
|---|---|---|
| `deployment` | Runtime and OMS startup/reload | New `deployment_logger.py`; emit startup, OLR final enablement, shutdown. |
| `config_snapshot` | Runtime and OMS config loaders | New effective-config snapshotter; hash strategy, portfolio, risk, allocation, registry, resource plan. |
| `resource_plan` | `kis_resource_plan.py` and runtime session | Export `KISResourcePlan.to_json_dict()` with plan hash and lineage. |
| `market_data_subscription` | `market_data_coordinator.py` | Export subscription, release, rejection, external source, and suppression rows. |
| `decision_event` | `RuntimeActionRouter.record_decisions()` and no-action path | Export every strategy decision/no-action with `decision_ref`, `event_ref`, bar, artifact, and config lineage. |
| `strategy_action` | `RuntimeActionRouter._route_prepared_action()` | Export normalized action before portfolio arbitration and OMS submission. |
| `portfolio_rule` | `PortfolioArbitrationPolicy` via action router | Export accepted/blocked/resized decisions with thresholds and state. |
| `risk_decision` | `RiskGateway.check()` via OMS core | Add rule trace and export final risk decision. |
| `oms_intent` | Runtime action router and OMS core | Export intent creation, duplicate, validation failure, finalization. |
| `order` | Runtime order results and OMS order lifecycle | Export order submit/result/status/cancel/timeout/terminal events. |
| `fill` | OMS `_apply_fill()` and runtime `handle_fill()` | Export actual and inferred fills with KIS/OMS IDs and allocation changes. |
| `trade` | Runtime trade outcomes and legacy trade logger | Export completed trades only as canonical performance events. |
| `missed_opportunity` | Legacy logger plus runtime/portfolio/OMS blocks | Append revision events for strategy, portfolio, risk, resource, and execution blocks. |
| `filter_decision` | Legacy filter logger and strategy decision metadata | Emit first-class filter/gate rows for long gate chains. |
| `indicator_snapshot` | Legacy indicator logger and strategy metadata | Emit compact signal/indicator state around decision bars. |
| `market_snapshot` | Legacy market snapshot and runtime bars | Emit entry/exit/decision market context, including source fingerprint. |
| `position_snapshot` | OMS reconciliation and runtime context | Emit per-symbol broker position state and drift. |
| `allocation_snapshot` | OMS fill/reconciliation/admin paths | Emit per-strategy virtual allocation state. |
| `portfolio_snapshot` | Runtime/OMS heartbeat/reconciliation | Emit portfolio exposure, cash, equity, PnL, risk flags, sector exposure. |
| `daily_snapshot` | Existing daily builder plus runtime closeout | Emit bot/portfolio daily rollup with lineage and parity status. |
| `reconciliation_event` | OMS reconciliation | Emit drift, inferred fills, freeze/unfreeze, admin correction, EOD cleanup. |
| `heartbeat` | Legacy facade, runtime, OMS | Emit liveness and sidecar/OMS/KIS diagnostics. |
| `bot_error` | Runtime, OMS, sidecar, legacy facade | Emit structured trading-relevant errors and lineage gaps. |

## 14. KALCB And OLR Field Mapping

### 14.1 KALCB

Useful source metadata already exists in
`strategy_kalcb/core/logic.py`:

- `candidate_rank`;
- `frontier_rank`;
- `frontier_initial_active`;
- `frontier_role`;
- `frontier_selection_mode`;
- `frontier_selection_score`;
- `entry_route`;
- `entry_route_attempts`;
- `source_artifact_hash`;
- `candidate_hash`;
- `filter_decisions`;
- `gate_decisions`;
- `risk_per_share`;
- `stop_price`;
- `daily_atr`;
- `sector`;
- `regime_tier`;
- `core_version`.

Map these into:

- `decision_event.metadata`;
- `strategy_action.action.metadata`;
- `trade.strategy_params_at_entry`;
- `trade.sizing_inputs`;
- `trade.market_conditions_at_entry`;
- `trade.portfolio_state_at_entry`;
- `missed_opportunity.filter_decisions`.

KALCB blocked entry results from `_rejected(...)` should become
`missed_opportunity` only when the candidate had a real setup/signal and a gate
blocked it. Do not emit missed opportunities for every symbol with no signal.

### 14.2 OLR

Useful source metadata exists in `strategy_olr/core/logic.py`:

- `source_artifact_hash`;
- `source_fingerprint`;
- `candidate_rank`;
- `candidate_score`;
- `candidate_hash`;
- `sector`;
- `afternoon_score_band_rule`;
- `trade_entry_plan`;
- `trade_exit_plan`;
- `auction_fill_time`;
- `auction_adverse_bps`;
- `auction_nonfill_rate`;
- `auction_nonfill_key`;
- `expiry_ts`;
- `allocation_weight`;
- `close_to_close_label_pct`;
- `next_session_mfe_label_pct`;
- `daily_atr`;
- `risk_per_share`;
- `estimated_entry_price`;
- `entry_submission_time`;
- `entry_submission_close`;
- `target_notional`;
- `available_cash_before_entry`;
- `pending_entry_reserved_notional`;
- `entry_cost_buffer_pct`;
- `protective_stop_price`.

Map these into:

- `decision_event.metadata`;
- `strategy_action.action.metadata`;
- `trade.sizing_inputs`;
- `trade.strategy_params_at_entry`;
- `trade.market_conditions_at_entry`;
- `order.execution_style`;
- `order.expiry_ts`;
- `missed_opportunity.simulation_policy`.

OLR has a specific close-auction path. Always include the entry plan, exit plan,
auction assumptions, and nonfill key when the event was generated by the OLR
close-auction logic.

## 15. Testing Plan

Add tests before or alongside implementation. The goal is to keep the work
surgical and prevent silent regressions.

### 15.1 Unit Tests

Add or extend tests under `_references/k_stock_trader/tests/instrumentation/`:

- `test_lineage_context.py`: env/config/runtime lineage resolution, redaction,
  stable hashes, missing lineage warnings.
- `test_event_metadata.py`: event ID stability, revision IDs, bar IDs, trace
  IDs, backwards compatibility.
- `test_event_writer.py`: fail-open writes, date partitions, bounded errors.
- `test_sidecar_envelope.py`: new watched dirs, envelope lineage duplication,
  object payload serialization, priorities, HMAC payload stability.
- `test_missed_revisions.py`: backfill appends revision 1 and does not rewrite
  revision 0.
- `test_runtime_exporter.py`: session rows become canonical `decision_event`,
  `strategy_action`, `portfolio_rule`, `order`, `fill`, and `trade`.
- `test_oms_exporter.py`: OMS emits fail-open JSONL events and redacts secrets.
- `test_risk_trace.py`: every risk rule produces a trace row and final decision
  matches existing behavior.
- `test_config_snapshot.py`: KALCB/OLR/OMS/portfolio config hashes are stable;
  secrets are redacted.
- `test_portfolio_rule_payload.py`: accepted, blocked, and resized decisions
  include requested/approved sizing and threshold state.
- `test_root_cause_mapping.py`: local and canonical root causes are both
  emitted.

### 15.2 Runtime Integration Tests

Add tests under `_references/k_stock_trader/tests/deployment/olr_kalcb/`:

- a dry-run session with no trades emits deployment, config, resource plan,
  heartbeat, runtime input, no-action decision, portfolio snapshot, and closeout;
- a synthetic accepted KALCB entry emits decision, action, portfolio rule,
  OMS intent, order result, fill, allocation snapshot, and position snapshot;
- a synthetic portfolio block emits `portfolio_rule` and
  `missed_opportunity` with `blocked_scope="portfolio_rule"`;
- a synthetic OMS risk reject emits `risk_decision`, `order`, and
  `missed_opportunity` with `blocked_scope="oms_risk"`;
- OLR final enablement emits deployment/config/resource revision events;
- market data route suppression emits a resource or market-data event.

### 15.3 OMS Integration Tests

Add tests under `_references/k_stock_trader/tests/oms/`:

- submit intent accepted path emits intent, risk, order, and heartbeat events;
- submit intent rejected path emits risk trace and order reject;
- duplicate idempotency path emits duplicate intent event;
- partial fill and full fill emit fill events and allocation snapshots;
- inferred fill emits `inferred=true`;
- positive drift assigns `_UNKNOWN_`, freezes symbol, and emits
  reconciliation and allocation snapshots;
- admin correction emits risk-control/reconciliation events.

### 15.4 End-To-End Assistant Contract Test

Create one synthetic KALCB/OLR day in dry-run mode:

1. Start runtime session with KALCB and OLR.
2. Process at least one completed bar.
3. Produce one no-action decision.
4. Produce one accepted action.
5. Produce one portfolio block or OMS risk block.
6. Simulate one fill and one completed trade outcome.
7. Close the session.
8. Let sidecar read unsent events.
9. Validate payloads against assistant schemas where schemas exist.
10. Validate optimal fields through local contract tests where assistant
    schemas are not yet widened.

Acceptance should require:

- every event has `event_id`, `bot_id`, `event_type`, `exchange_timestamp`,
  `local_timestamp`, `data_source_id`, `schema_version`;
- monthly-critical events have `strategy_version`, `config_version`,
  `deployment_id`, and `code_sha`;
- portfolio/OMS events have `portfolio_config_version`,
  `risk_config_version`, `allocation_version`, and `portfolio_id`;
- decision/order/trade events are joinable through `event_ref`,
  `decision_ref`, `action_ref`, `portfolio_decision_ref`, `intent_id`,
  `order_id`, and `trade_id`;
- sidecar forwards events in priority order and resumes after restart;
- instrumentation failures do not fail the trading/runtime tests.

## 16. Suggested Implementation Order

1. Add shared `LineageContext`, event metadata extensions, event writer, event
   envelope helpers, and tests.
2. Extend sidecar directory mapping and envelope output while preserving current
   assistant schema tests.
3. Add config/deployment snapshotting and emit startup snapshots from runtime
   and OMS.
4. Add runtime exporter and hook `prepare_runtime_session()`,
   `record_decisions()`, `_record_no_action()`, `_route_prepared_action()`,
   fill handling, market data events, and closeout.
5. Add OMS emitter, risk traces, intent/order/fill/reconciliation/risk-control
   events.
6. Retrofit legacy `TradeLogger`, `MissedOpportunityLogger`, `OrderLogger`,
   `FilterLogger`, `IndicatorLogger`, `HeartbeatEmitter`, and
   `DailySnapshotBuilder`.
7. Add portfolio, position, and allocation snapshot builders tied to startup,
   fills, reconciliation, risk-control changes, and closeout.
8. Add KALCB/OLR simulation policies and root-cause mapping.
9. Run unit tests, runtime integration tests, OMS integration tests, and one
   end-to-end sidecar contract test.
10. Only after telemetry is stable, consider assistant-side schema widening for
    any new optimal event types that do not yet have first-class Pydantic
    schemas.

## 17. What Not To Do

Do not:

- replace `PaperSessionRecorder` with a parallel assistant-only recorder;
- make KALCB/OLR strategy engines call legacy facade hooks for fills before
  OMS confirms fills;
- rely on Postgres as the only assistant evidence source;
- rewrite JSONL rows after they may have been sidecar-forwarded;
- use random event IDs for deterministic trading facts;
- create a new deployment ID for every event;
- block OMS risk checks or KIS order submission on telemetry writes;
- emit raw KIS account numbers, app keys, secrets, HMAC values, or DSNs;
- treat OLR stage1 and final artifacts as the same deployment state;
- claim KALCB/OLR strategy budgets exist in OMS config unless they actually do.
- add monitoring-only analytics outside the lifecycle evidence listed above as
  approval blockers.

## 18. Definition Of Done

The implementation is complete when a synthetic KALCB/OLR dry-run or paper
session can produce a complete assistant evidence bundle:

- deployment and config snapshots exist;
- resource plan and artifact lineage exist;
- runtime decisions and no-actions are emitted;
- strategy actions are emitted;
- portfolio arbitration decisions are emitted with full state and thresholds;
- OMS risk decisions are emitted with rule traces;
- order and fill lifecycle events are emitted with OMS/KIS IDs;
- completed trades link back to decision, action, portfolio, OMS, order, fill,
  artifact, config, and deployment lineage;
- missed opportunities include strategy, portfolio, or OMS block context and
  append revision events for backfills;
- position, allocation, and portfolio snapshots exist for startup, fills,
  reconciliation, risk-control changes, and closeout;
- approval-grade `deployment_metadata.json` is emitted by the live bot/VPS;
- daily snapshot includes lineage and parity/closeout status;
- heartbeats include sidecar, runtime, OMS, KIS, and lineage diagnostics;
- sidecar forwards every event type safely;
- all instrumentation failures are non-fatal;
- tests prove event identity stability, lineage coverage, sidecar delivery,
  runtime/OMS hook coverage, and no trading behavior changes.

At that point `k_stock_trader` is not merely "instrumented." It is producing
the production-truth evidence contract required for the new optimal learning
loop at both the strategy level and the portfolio/OMS level.
