# Optimal Trading Repo Instrumentation Guide

Date: 2026-05-30

Audience: Codex or another coding agent implementing instrumentation in a
trading repo that currently has no instrumentation.

Consuming system: `trading_assistant`

## 1. Purpose

This guide defines the optimal instrumentation layer a trading repo should
implement so `trading_assistant` can ingest live bot evidence, run daily and
weekly diagnostics, and participate in the monthly full-fidelity validation
loop.

The goal is not more logging. The goal is an evidence contract:

- every important live trading decision is observable;
- every trade and missed opportunity has enough context for diagnosis;
- every event can be mapped to the exact strategy, config, deployment, code
  version, data source, and bar that produced it;
- every portfolio, family, allocation, risk, and OMS decision that changes a
  strategy intent is observable;
- monthly validation can decide whether a strategy is authoritative-ready,
  diagnostics-only, or blocked by missing lineage;
- structural strategy changes can prove decision-level live/backtest parity
  before scoring, approval packets, or deployment;
- portfolio-level proposals can be attributed to the exact allocation, risk,
  coordination, heat-cap, drawdown-tier, and strategy-registry state that was
  live when the evidence was produced.

Implement the instrumentation as a read-only, non-fatal observer. It must never
place orders, cancel orders, mutate trading decisions, block the hot path, or
hide trading errors.

## 2. Target Role In The New Learning Loop

The trading repo has a different role in the target state than in older
reporting-only designs.

Old role:

- emit trade logs, errors, and maybe daily summaries;
- help the assistant explain what happened;
- support lightweight weekly diagnostics and before/after comparisons.

New role:

- remain production truth for live strategy behavior;
- remain production truth for live portfolio and OMS behavior that transforms
  strategy intent into actual orders;
- emit structured telemetry with complete lineage;
- expose or share strategy decision logic so a backtest/replay repo can prove
  decision-level equivalence;
- provide deployment and config version identifiers required for monthly
  attribution;
- produce enough decision telemetry to compare live and replay behavior for
  signals, filters, entries, exits, stops, sizing, risk blocks, allocation
  gates, heat caps, drawdown tiers, symbol collisions, and cross-strategy
  coordination.

The trading repo is not the control plane and not the experiment lab:

- `trading_assistant` is the control plane. It owns schedules, evidence
  ingestion, ledgers, approval routing, monthly manifests, and verdicts.
- `trading_assistant_backtest` or another configured backtest host is the
  experiment lab. It owns full-fidelity replay, phased-auto, OOS repair,
  candidate scoring, and artifact emission.
- The trading repo is production truth. It owns live strategy code, live config
  schema, live portfolio/risk config schema, live event emission, and
  decision-level parity hooks.

## 3. Non-Negotiable Constraints

Instrumentation must obey these constraints:

- Additive only: do not change strategy behavior while adding telemetry.
- Non-fatal: all instrumentation calls must be wrapped so failures never stop
  trading.
- Bounded: file writes, queues, retries, and buffers must have limits.
- Deterministic identity: event IDs must be stable for the same logical event.
- Time aligned: exchange timestamp, local timestamp, clock skew, data source,
  and bar ID must be captured where available.
- Lineage-first: monthly-critical events must include strategy/config/deployment
  lineage.
- Secret-safe: never write API keys, broker tokens, account secrets, or raw
  credentials into event payloads.
- Account-safe: use stable account aliases, never raw broker account numbers
  unless the deployment explicitly permits them.
- Replay-safe: live decision events must be normalized enough to compare against
  replay output.
- Approval-safe: instrumentation must not auto-approve, auto-deploy, or route
  live trading commands.

## 4. Recommended Package Layout

For a repo with no instrumentation, add a package similar to:

```text
instrumentation/
  __init__.py
  config/
    instrumentation_config.yaml
    process_scoring_rules.yaml
    simulation_policies.yaml
  src/
    __init__.py
    bootstrap.py
    facade.py
    event_metadata.py
    event_writer.py
    sidecar.py
    trade_logger.py
    missed_opportunity.py
    order_logger.py
    filter_decision.py
    indicator_logger.py
    market_snapshot.py
    orderbook_logger.py
    process_scorer.py
    daily_snapshot.py
    family_snapshot.py
    position_snapshot.py
    portfolio_snapshot.py
    allocation_snapshot.py
    risk_decision.py
    correlation_snapshot.py
    sector_exposure.py
    heartbeat.py
    error_logger.py
    config_snapshot.py
    config_watcher.py
    deployment_logger.py
    decision_capture.py
    parity_export.py
  tests/
    test_event_metadata.py
    test_trade_logger.py
    test_missed_opportunity.py
    test_order_logger.py
    test_filter_decision.py
    test_daily_snapshot.py
    test_family_snapshot.py
    test_portfolio_snapshot.py
    test_risk_decision.py
    test_allocation_snapshot.py
    test_sidecar.py
    test_lineage_contract.py
    test_decision_capture.py
    test_parity_contract.py
```

Local event data should be written under a configurable `data_dir`:

```text
instrumentation/data/
  trades/trades_YYYY-MM-DD.jsonl
  missed/missed_YYYY-MM-DD.jsonl
  orders/orders_YYYY-MM-DD.jsonl
  filter_decisions/filter_decisions_YYYY-MM-DD.jsonl
  indicators/indicators_YYYY-MM-DD.jsonl
  orderbook/orderbook_YYYY-MM-DD.jsonl
  portfolio_rules/portfolio_rules_YYYY-MM-DD.jsonl
  positions/positions_YYYY-MM-DD.jsonl
  portfolio/portfolio_snapshots_YYYY-MM-DD.jsonl
  family/family_snapshots_YYYY-MM-DD.jsonl
  allocations/allocations_YYYY-MM-DD.jsonl
  exposure/exposure_YYYY-MM-DD.jsonl
  snapshots/snapshots_YYYY-MM-DD.jsonl
  daily/daily_YYYY-MM-DD.json
  errors/errors_YYYY-MM-DD.jsonl
  heartbeats/heartbeat_YYYY-MM-DD.jsonl
  config_changes/config_changes_YYYY-MM-DD.jsonl
  deployments/deployments_YYYY-MM-DD.jsonl
  decisions/decisions_YYYY-MM-DD.jsonl
  post_exit/post_exit_YYYY-MM-DD.jsonl
  .sidecar_buffer/watermark.json
```

Use date-partitioned files so the sidecar can forward incrementally and so
operators can inspect evidence without a database.

## 5. Configuration Contract

Add `instrumentation/config/instrumentation_config.yaml`:

```yaml
schema_version: instrumentation_config_v1
enabled: true
bot_id: ""
family_id: ""
portfolio_id: "default"
account_alias: ""
data_dir: "instrumentation/data"
data_source_id: ""
default_timezone: "UTC"

lineage:
  require_strategy_version: true
  require_config_version: true
  require_deployment_id: true
  require_code_sha: true
  fail_open_when_missing: true

sidecar:
  relay_url: ""
  hmac_secret_env: "INSTRUMENTATION_HMAC_SECRET"
  batch_size: 50
  poll_interval_seconds: 30
  retry_max: 5
  retry_backoff_base_seconds: 10
  use_gzip: true
  buffer_dir: "instrumentation/data/.sidecar_buffer"

rotation:
  max_file_age_days: 30
  max_disk_mb: 500

heartbeat:
  interval_seconds: 30
  gap_multiplier: 2.5

snapshots:
  market_snapshot_interval_seconds: 60
  orderbook_depth_bps: 10
  position_snapshot_interval_seconds: 300
  portfolio_snapshot_interval_seconds: 300
  emit_family_snapshots: true
  emit_allocation_snapshots: true
  exposure_unit: "pct_equity"

backfill:
  missed_opportunity_enabled: true
  post_exit_enabled: true
  max_hold_bars: 300
```

Allow environment variables to override deployment-specific values:

- `BOT_ID`
- `STRATEGY_ID`
- `FAMILY_ID`
- `PORTFOLIO_ID`
- `ACCOUNT_ALIAS`
- `STRATEGY_VERSION`
- `CONFIG_VERSION`
- `PORTFOLIO_CONFIG_VERSION`
- `RISK_CONFIG_VERSION`
- `ALLOCATION_VERSION`
- `STRATEGY_REGISTRY_VERSION`
- `DEPLOYMENT_ID`
- `PARAMETER_SET_ID`
- `EXPERIMENT_ID`
- `VARIANT_ID`
- `CODE_SHA`
- `INSTRUMENTATION_RELAY_URL`
- `INSTRUMENTATION_HMAC_SECRET`
- `INSTRUMENTATION_DATA_DIR`

If a lineage value is missing, emit the event anyway but also emit a warning
heartbeat or error. Missing lineage blocks authoritative monthly validation, but
instrumentation should not block live trading.

## 6. Event Envelope

Every event should have two layers:

1. A local payload written to JSON/JSONL.
2. A sidecar envelope sent to the relay.

Local payloads should include `event_metadata` or top-level identity fields.
The sidecar envelope should be normalized to:

```json
{
  "event_id": "16_hex_chars",
  "bot_id": "stock_trader",
  "event_type": "trade",
  "priority": 2,
  "payload": "{\"trade_id\":\"...\"}",
  "exchange_timestamp": "2026-05-30T14:30:00+00:00",
  "scope": "strategy",
  "strategy_id": "US_ORB_v1",
  "family_id": "stock",
  "portfolio_id": "live_portfolio",
  "strategy_version": "US_ORB_v1.4.2",
  "config_version": "cfg_2026_05_30_001",
  "portfolio_config_version": "pcfg_2026_05_30_001",
  "risk_config_version": "risk_2026_05_30_001",
  "allocation_version": "alloc_2026_05_30_001",
  "deployment_id": "dep_2026_05_30_abc123",
  "parameter_set_id": "param_9e6a1f3b",
  "experiment_id": "",
  "variant_id": "",
  "code_sha": "abcdef1234567890"
}
```

The relay may only require `event_id`, `bot_id`, `event_type`, `payload`, and
`exchange_timestamp`, but duplicate lineage at the envelope level when possible.
`payload` may be a JSON object in local files and a canonical JSON string on
the wire. This lets the assistant preserve lineage even when payloads are
nested or stored as JSON strings.

Envelope duplication is not a substitute for payload fields. Put all important
identity and lineage fields inside the payload itself, especially `family_id`,
`portfolio_id`, `account_alias`, `portfolio_config_version`,
`risk_config_version`, `allocation_version`, and `strategy_registry_version`.
The current assistant path already preserves known strategy lineage from the
envelope, but portfolio lineage should not depend on envelope-only copying.

Use `scope` to make event intent explicit:

| Scope | Use |
|---|---|
| `strategy` | A single strategy decision, signal, order, trade, or missed opportunity |
| `family` | A family-level snapshot or coordination decision across related strategies |
| `portfolio` | Allocation, heat, exposure, drawdown, or cross-family portfolio state |
| `oms` | Order-management, broker, reconciliation, and risk-gateway events |

Recommended event priorities:

| Event type | Priority | Reason |
|---|---:|---|
| `error`, `bot_error`, `risk_halt` | 0 | Urgent triage |
| `daily_snapshot`, `deployment`, `parameter_change` | 1 | State and lineage |
| `trade`, `trade_exit` | 2 | Core performance evidence |
| `missed_opportunity`, `order`, `filter_decision`, `portfolio_rule`, `risk_decision` | 3 | Diagnostic evidence |
| `indicator_snapshot`, `orderbook_context`, `market_snapshot`, `position_snapshot`, `portfolio_snapshot`, `allocation_snapshot`, `post_exit`, `decision_event` | 4 | Enrichment and parity |
| `heartbeat` | 5 | Operational liveness |

## 7. Event Identity And Metadata

Implement a shared `EventMetadata` helper.

Required metadata fields:

| Field | Required | Description |
|---|---|---|
| `event_id` | yes | SHA-256 event identity, truncated to 16 hex chars |
| `bot_id` | yes | Stable producing bot/process ID used by `trading_assistant` |
| `strategy_id` | monthly-critical for strategy events | Strategy or sleeve within a multi-strategy bot |
| `family_id` | required for family/portfolio attribution | Strategy family such as swing, momentum, stock, crypto, or a repo-specific family |
| `portfolio_id` | required for portfolio events | Stable portfolio/account grouping, not a raw account secret |
| `event_type` | yes | Canonical event type |
| `payload_key` | yes | Stable logical key within event type |
| `exchange_timestamp` | yes | Exchange or broker event timestamp |
| `local_timestamp` | yes | Local machine timestamp when recorded |
| `clock_skew_ms` | yes | `exchange_timestamp - local_timestamp` in milliseconds |
| `data_source_id` | yes | Broker/feed/source identifier |
| `bar_id` | recommended | Symbol/timeframe/bar-open identifier |
| `trace_id` | recommended | Correlates signal, order, fill, trade, and decision events |
| `schema_version` | yes | Producer event schema version |

Event ID formula:

```python
raw = f"{bot_id}|{exchange_timestamp.isoformat()}|{event_type}|{payload_key}"
event_id = sha256(raw.encode("utf-8")).hexdigest()[:16]
```

Payload keys should be stable:

- trade entry: `"{trade_id}:entry"`
- completed trade: `"{trade_id}:exit"`
- missed opportunity: `"{signal_id}:{bar_id}:{blocked_by}"`
- order lifecycle: `"{order_id}:{status}"`
- filter decision: `"{signal_id}:{filter_name}:{bar_id}"`
- heartbeat: `"{strategy_id}:{timestamp_floor}"`
- deployment: `"{deployment_id}:{status}"`
- parameter change: `"{config_version}:{param_name}"`
- portfolio rule: `"{trace_id}:{rule_name}:{result}:{bar_id}"`
- position snapshot: `"{portfolio_id}:{timestamp_floor}"`
- allocation snapshot: `"{portfolio_id}:{allocation_version}:{timestamp_floor}"`
- decision event: `"{strategy_id}:{decision_code}:{bar_id}:{sequence}"`

Do not use random UUIDs for `event_id`. A separate `trace_id` can be random.

## 8. Lineage Contract

Lineage is the most important difference between old telemetry and the new
monthly validation target state.

Monthly-critical events must include:

| Field | Requirement | Notes |
|---|---|---|
| `strategy_id` | always | Stable strategy identity, not a display label |
| `family_id` | always when known | Stable family identity for portfolio grouping and family snapshots |
| `portfolio_id` | always for portfolio/OMS events | Stable portfolio grouping or account alias |
| `strategy_version` | always for authoritative validation | Version of strategy behavior or strategy package |
| `config_version` | always for authoritative validation | Hash or version of active config |
| `portfolio_config_version` | always for portfolio attribution | Hash/version of heat caps, allocation constraints, drawdown tiers, coordination rules |
| `risk_config_version` | always for OMS/risk attribution | Hash/version of risk-gateway and portfolio-rule settings |
| `allocation_version` | always for allocation attribution | Hash/version of live family/bot/strategy capital weights |
| `strategy_registry_version` | recommended | Hash/version of the strategy-to-family registry and active strategy set |
| `deployment_id` | always for authoritative validation | Current deployment/run ID, even if no change is in flight |
| `parameter_set_id` | recommended | Hash of strategy parameters at decision time |
| `experiment_id` | when applicable | A/B or shadow experiment identity |
| `variant_id` | when applicable | Experiment variant or candidate ID |
| `signal_generation_version` | recommended | Version of signal extraction logic/features |
| `code_sha` | always for authoritative validation | Commit SHA of production trading repo |
| `proposal_ids` | when applicable | Assistant proposal IDs that led to deployment |
| `suggestion_ids` | when applicable | Suggestion tracker IDs that led to deployment |

The assistant's lineage audit treats `strategy_version`, `config_version`, and
`deployment_id` as the required monthly lineage fields. Missing values can turn
a strategy into `insufficient_lineage` and block authoritative monthly verdicts.
For portfolio-level analysis, those three fields are not enough. A portfolio or
OMS event should also carry `portfolio_config_version`, `risk_config_version`,
`allocation_version`, and `strategy_registry_version` when available, otherwise
allocation, heat-cap, drawdown-tier, and coordination outcomes cannot be cleanly
attributed.

Recommended scope rules:

| Event scope | Identity fields |
|---|---|
| Strategy events | `bot_id`, `strategy_id`, `family_id`, strategy lineage, portfolio/risk lineage if it affected sizing or approval |
| Family events | `bot_id` or `portfolio_id`, `family_id`, `strategy_registry_version`, family allocation/risk lineage |
| Portfolio events | `portfolio_id`, `account_alias`, `allocation_version`, `portfolio_config_version`, `risk_config_version`, `strategy_registry_version` |
| OMS events | `bot_id`, `strategy_id` if known, `portfolio_id`, `risk_config_version`, order/risk trace fields |

### 8.1 Computing `config_version`

Compute `config_version` from the effective runtime config, not just the source
file text. Include defaults, environment overrides, broker/execution settings,
and strategy-specific parameters. If the repo has separable portfolio, risk, or
allocation configs, compute their own hashes too and either include them in
`config_version` or emit them beside it as `portfolio_config_version`,
`risk_config_version`, and `allocation_version`.

Recommended formula:

```python
effective_config = build_effective_config()
canonical = json.dumps(effective_config, sort_keys=True, default=str)
config_version = "cfg_" + sha256(canonical.encode("utf-8")).hexdigest()[:16]
```

Store a matching config snapshot:

```json
{
  "event_type": "config_snapshot",
  "bot_id": "stock_trader",
  "strategy_id": "US_ORB_v1",
  "config_version": "cfg_0123456789abcdef",
  "strategy_version": "US_ORB_v1.4.2",
  "deployment_id": "dep_2026_05_30_abc123",
  "portfolio_config_version": "pcfg_0123456789abcdef",
  "risk_config_version": "risk_0123456789abcdef",
  "allocation_version": "alloc_0123456789abcdef",
  "strategy_registry_version": "registry_0123456789abcdef",
  "code_sha": "abcdef1234567890",
  "effective_config": {
    "strategy": {"risk_pct": 0.005, "stop_atr": 1.5},
    "portfolio": {"heat_cap_R": 8.0, "family_allocations": {"stock": 0.33}},
    "risk": {"symbol_collision_action": "half_size"}
  },
  "redacted_keys": ["BROKER_API_KEY"],
  "generated_at": "2026-05-30T08:00:00+00:00"
}
```

### 8.2 Computing `parameter_set_id`

Compute `parameter_set_id` from the subset of parameters that can affect a
strategy decision. It can equal `config_version` for simple repos, but separate
it when portfolio config, broker config, and strategy config change on different
cadences.

```python
strategy_params = build_strategy_param_subset()
canonical = json.dumps(strategy_params, sort_keys=True, default=str)
parameter_set_id = "param_" + sha256(canonical.encode("utf-8")).hexdigest()[:16]
```

### 8.3 Deployment Identity

Emit a deployment event at startup and when deployment state changes:

```json
{
  "event_type": "deployment",
  "deployment_id": "dep_2026_05_30_abc123",
  "bot_id": "stock_trader",
  "strategy_id": "US_ORB_v1",
  "status": "deployed",
  "strategy_version": "US_ORB_v1.4.2",
  "config_version": "cfg_0123456789abcdef",
  "parameter_set_id": "param_1111222233334444",
  "code_sha": "abcdef1234567890",
  "deployed_at": "2026-05-30T08:00:00+00:00",
  "source": "startup_detected",
  "pr_url": "",
  "proposal_ids": [],
  "suggestion_ids": []
}
```

`deployment_id` should be stable for a running production deployment. Do not
generate a new deployment ID for every event or every process restart unless the
actual deployed code/config changed.

Portfolio/risk config reloads should emit their own deployment or config events
even when strategy code did not change. A heat-cap edit, drawdown-tier edit,
family-allocation edit, symbol-collision rule edit, or strategy-registry edit
can materially change live behavior and must be attributable.

## 9. Required Event Types

This section defines the optimal event surface for a fresh trading repo.

### 9.1 Completed Trade Event

Emit a canonical `trade` event when a trade is completed. Optional entry-stage
events can be emitted as `trade_entry`, but the canonical performance event is
the completed trade.

Required fields:

```json
{
  "schema_version": "trade_event_v1",
  "event_type": "trade",
  "event_metadata": {},
  "trade_id": "US_ORB_v1:AAPL:20260530:001",
  "bot_id": "stock_trader",
  "strategy_id": "US_ORB_v1",
  "family_id": "stock",
  "portfolio_id": "live_portfolio",
  "account_alias": "ibkr_stock_live",
  "strategy_version": "US_ORB_v1.4.2",
  "config_version": "cfg_0123456789abcdef",
  "portfolio_config_version": "pcfg_0123456789abcdef",
  "risk_config_version": "risk_0123456789abcdef",
  "allocation_version": "alloc_0123456789abcdef",
  "deployment_id": "dep_2026_05_30_abc123",
  "parameter_set_id": "param_1111222233334444",
  "experiment_id": "",
  "variant_id": "",
  "code_sha": "abcdef1234567890",
  "pair": "AAPL",
  "side": "LONG",
  "entry_time": "2026-05-30T13:35:00+00:00",
  "exit_time": "2026-05-30T15:55:00+00:00",
  "entry_price": 100.25,
  "exit_price": 102.10,
  "position_size": 100,
  "position_size_quote": 10025.0,
  "currency": "USD",
  "pnl": 185.0,
  "pnl_pct": 1.845,
  "fees_paid": 2.50,
  "entry_signal": "opening_range_breakout",
  "entry_signal_strength": 0.82,
  "signal_id": "sig_20260530_AAPL_0935",
  "exit_reason": "TAKE_PROFIT",
  "market_regime": "bull_trend",
  "macro_regime": "G",
  "stress_level_at_entry": 0.12,
  "active_filters": ["spread", "volume", "risk_cap"],
  "passed_filters": ["spread", "volume", "risk_cap"],
  "filter_decisions": [],
  "sizing_inputs": {
    "target_risk_pct": 0.005,
    "account_equity": 100000.0,
    "unit_risk_dollars": 500.0,
    "requested_qty": 100,
    "approved_qty": 100,
    "size_multiplier": 1.0,
    "sizing_model": "fixed_fractional"
  },
  "strategy_params_at_entry": {},
  "portfolio_state_at_entry": {
    "portfolio_exposure_pct": 0.35,
    "family_exposure_pct": 0.12,
    "symbol_exposure_pct": 0.04,
    "directional_exposure_R": {"LONG": 3.2, "SHORT": 0.6},
    "heat_used_R": 3.8,
    "heat_cap_R": 8.0,
    "open_positions_count": 7,
    "correlated_pairs_detail": [],
    "active_portfolio_rules": ["directional_cap", "symbol_collision"]
  },
  "market_conditions_at_entry": {},
  "process_quality_score": 94,
  "root_causes": ["regime_aligned", "good_execution", "normal_win"],
  "mfe_r": 2.1,
  "mae_r": -0.3,
  "exit_efficiency": 0.72,
  "entry_fill_details": {},
  "exit_fill_details": {},
  "entry_slippage_bps": 1.2,
  "exit_slippage_bps": 2.1,
  "entry_latency_ms": 85,
  "exit_latency_ms": 90,
  "post_exit_1h_price": null,
  "post_exit_4h_price": null,
  "post_exit_backfill_status": "pending"
}
```

The event should include the effective strategy parameters at entry. If the full
config is large, include a compact subset in `strategy_params_at_entry` and emit
a separate `config_snapshot` event keyed by `config_version`.

For portfolio-level learning, `portfolio_state_at_entry` is not optional
decoration. It is the evidence that distinguishes "the strategy chose not to
trade" from "the portfolio layer resized or constrained the trade." Include
open-position overlap, sibling positions, family allocation, heat usage,
drawdown-tier state, and rule names whenever that data exists.

### 9.2 Missed Opportunity Event

Emit `missed_opportunity` when a real setup or signal was present but a filter,
risk gate, coordination rule, or execution constraint blocked the trade.

Do not emit missed opportunities for every "no signal" bar. Emit them when
there was enough signal quality that the assistant can learn about opportunity
cost or filter effectiveness.

Required fields:

```json
{
  "schema_version": "missed_opportunity_event_v1",
  "event_type": "missed_opportunity",
  "event_metadata": {},
  "bot_id": "stock_trader",
  "strategy_id": "US_ORB_v1",
  "family_id": "stock",
  "portfolio_id": "live_portfolio",
  "strategy_version": "US_ORB_v1.4.2",
  "config_version": "cfg_0123456789abcdef",
  "portfolio_config_version": "pcfg_0123456789abcdef",
  "risk_config_version": "risk_0123456789abcdef",
  "allocation_version": "alloc_0123456789abcdef",
  "deployment_id": "dep_2026_05_30_abc123",
  "parameter_set_id": "param_1111222233334444",
  "code_sha": "abcdef1234567890",
  "pair": "AAPL",
  "side": "LONG",
  "signal": "opening_range_breakout",
  "signal_id": "sig_20260530_AAPL_0935",
  "signal_strength": 0.76,
  "signal_time": "2026-05-30T13:35:00+00:00",
  "blocked_by": "spread_gate",
  "block_reason": "spread_bps_above_threshold",
  "margin_pct": -14.3,
  "hypothetical_entry": 100.25,
  "market_regime": "bull_trend",
  "filter_decisions": [],
  "sizing_inputs": {},
  "coordination_context": {
    "rule_name": "symbol_collision",
    "result": "block",
    "current_family_exposure_pct": 0.18,
    "current_directional_risk_R": 7.6,
    "cap_R": 8.0,
    "sibling_positions": []
  },
  "simulation_policy": {},
  "confidence": 0.0,
  "simulation_confidence": 0.0,
  "outcome_1h": null,
  "outcome_4h": null,
  "outcome_24h": null,
  "would_have_hit_tp": null,
  "would_have_hit_sl": null,
  "backfill_status": "pending"
}
```

Backfill outcomes later using local market data:

- 1h price and PnL estimate;
- 4h price and PnL estimate;
- 24h price and PnL estimate, if relevant;
- would-have-hit TP/SL under the simulation policy;
- confidence and assumption tags.

Counterfactual missed-opportunity outcomes are diagnostic. They do not replace
monthly full-fidelity replay.

### 9.3 Filter Decision Event

Embed `filter_decisions` inside trade and missed-opportunity events. Also emit
standalone `filter_decision` events when a strategy has a long gate pipeline or
when per-bar filter analysis matters.

Canonical filter decision shape:

```json
{
  "filter_name": "spread_gate",
  "passed": false,
  "threshold": 8.0,
  "actual_value": 9.1,
  "margin_pct": -13.75,
  "reason": "spread_bps_above_threshold",
  "context": {"spread_bps": 9.1, "session": "RTH"}
}
```

Use a consistent `filter_name` taxonomy. Do not alternate between
`spread`, `spread_gate`, and `max_spread_filter` for the same concept.

### 9.4 Order Lifecycle Event

Emit `order` events for all material order states:

- intent created;
- risk approved;
- risk rejected;
- routed;
- acknowledged;
- working;
- partial fill;
- filled;
- cancelled;
- expired;
- rejected;
- risk halt;
- coordination block.

Required fields:

```json
{
  "schema_version": "order_event_v1",
  "event_type": "order",
  "event_metadata": {},
  "order_id": "ord_123",
  "client_order_id": "US_ORB_v1_AAPL_20260530_001",
  "bot_id": "stock_trader",
  "strategy_id": "US_ORB_v1",
  "family_id": "stock",
  "portfolio_id": "live_portfolio",
  "strategy_version": "US_ORB_v1.4.2",
  "config_version": "cfg_0123456789abcdef",
  "portfolio_config_version": "pcfg_0123456789abcdef",
  "risk_config_version": "risk_0123456789abcdef",
  "allocation_version": "alloc_0123456789abcdef",
  "deployment_id": "dep_2026_05_30_abc123",
  "parameter_set_id": "param_1111222233334444",
  "code_sha": "abcdef1234567890",
  "pair": "AAPL",
  "side": "LONG",
  "order_type": "LIMIT",
  "status": "FILLED",
  "requested_qty": 100,
  "filled_qty": 100,
  "requested_price": 100.24,
  "fill_price": 100.25,
  "slippage_bps": 1.0,
  "reject_reason": "",
  "timestamp": "2026-05-30T13:35:02+00:00",
  "latency_ms": 85,
  "risk_result": "approved",
  "risk_reason": "",
  "requested_risk_R": 0.5,
  "approved_risk_R": 0.5,
  "requested_notional": 10025.0,
  "approved_notional": 10025.0,
  "portfolio_rule_trace_id": "abc123def4567890",
  "related_trade_id": "US_ORB_v1:AAPL:20260530:001",
  "trace_id": "abc123def4567890"
}
```

Order events are crucial for diagnosing slippage, latency, partial fills, order
rejects, and mismatches between strategy intent and broker execution.

### 9.5 Daily Snapshot

Emit one final `daily_snapshot` per bot or strategy after the local market close
plus a configurable delay. Intraday snapshots are allowed with
`snapshot_kind = "intraday"`, but final snapshots should be stable.

Required fields:

```json
{
  "schema_version": "daily_snapshot_v1",
  "event_type": "daily_snapshot",
  "date": "2026-05-30",
  "bot_id": "stock_trader",
  "strategy_id": "US_ORB_v1",
  "family_id": "stock",
  "portfolio_id": "live_portfolio",
  "strategy_version": "US_ORB_v1.4.2",
  "config_version": "cfg_0123456789abcdef",
  "portfolio_config_version": "pcfg_0123456789abcdef",
  "risk_config_version": "risk_0123456789abcdef",
  "allocation_version": "alloc_0123456789abcdef",
  "deployment_id": "dep_2026_05_30_abc123",
  "parameter_set_id": "param_1111222233334444",
  "code_sha": "abcdef1234567890",
  "timestamp": "2026-05-30T21:00:00+00:00",
  "snapshot_kind": "final",
  "total_trades": 5,
  "win_count": 3,
  "loss_count": 2,
  "gross_pnl": 420.0,
  "net_pnl": 405.0,
  "total_fees": 15.0,
  "win_rate": 0.6,
  "avg_win": 180.0,
  "avg_loss": -67.5,
  "profit_factor": 4.0,
  "max_drawdown_pct": 1.7,
  "sharpe_rolling_30d": 1.25,
  "sortino_rolling_30d": 1.7,
  "calmar_rolling_30d": 2.4,
  "exposure_pct": 0.35,
  "missed_count": 8,
  "missed_would_have_won": 2,
  "avg_process_quality": 88.2,
  "root_cause_distribution": {},
  "regime_breakdown": {},
  "per_strategy_summary": {},
  "per_family_summary": {},
  "portfolio_summary": {
    "portfolio_net_pnl": 405.0,
    "portfolio_exposure_pct": 0.35,
    "heat_used_R": 3.8,
    "heat_cap_R": 8.0,
    "portfolio_daily_stop_R": 4.0,
    "active_family_allocations": {"stock": 0.33, "momentum": 0.33, "swing": 0.34}
  },
  "experiment_breakdown": {},
  "lineage_summary": {},
  "lineage_gap": false,
  "error_count": 0,
  "uptime_pct": 99.8,
  "data_gaps": 0,
  "heartbeat_count": 780,
  "regime_context": null,
  "applied_regime_config": null
}
```

Daily snapshots are useful for monitoring and prompt context. They are not the
authoritative final measurement for material strategy changes.

For multi-strategy or multi-bot portfolios, also emit final family and
portfolio snapshots. The assistant's portfolio skills expect enough evidence to
build `PortfolioRiskCard`, `FamilyDailySnapshot`, `PortfolioRollingMetrics`,
drawdown-correlation analysis, and allocation recommendations. A repo that
only emits per-strategy daily snapshots cannot support reliable portfolio-level
improvement proposals.

### 9.6 Error Event

Emit `error` or `bot_error` events for exceptions and operational failures.

Fields:

- `error_type`;
- `message`;
- `severity`: `low`, `medium`, `high`, `critical`;
- `category`: `connection_lost`, `order_reject`, `data_gap`, `runtime_error`,
  `broker_error`, `instrumentation_error`, etc.;
- `stack_trace`, when available;
- `source_file` and `function`, when useful;
- `context`, redacted;
- lineage fields.

Instrumentation-internal errors should be tagged as `instrumentation_error` and
should not interrupt trading.

### 9.7 Heartbeat Event

Emit heartbeat events at a stable interval.

Include:

- bot and strategy IDs;
- lineage fields;
- process start time;
- uptime seconds;
- loop status;
- broker/feed connection status;
- last bar timestamp per symbol/timeframe;
- queue depths;
- sidecar diagnostics;
- open positions summary;
- portfolio exposure summary;
- active allocation, heat-cap, drawdown-tier, and risk-config versions;
- last decision code, if available;
- recent error counts.

Heartbeats let the assistant detect missing telemetry, stale deployments,
or sidecar outages before they distort monthly evidence.

### 9.8 Parameter Change And Config Snapshot Events

Emit `parameter_change` when a runtime parameter changes and `config_snapshot`
on startup/deployment.

`parameter_change` fields:

- `param_name`;
- `old_value`;
- `new_value`;
- `change_source`: `pr_merge`, `manual`, `hot_reload`, `experiment`;
- `config_file` or config path;
- `config_version_before`;
- `config_version_after`;
- `commit_sha`;
- `pr_url`;
- `deployment_id`;
- `portfolio_config_version_before` and `portfolio_config_version_after`, for
  portfolio config edits;
- `risk_config_version_before` and `risk_config_version_after`, for OMS/risk
  rule edits;
- `allocation_version_before` and `allocation_version_after`, for capital
  allocation edits;
- `approval_request_id`, when applicable.

Do not emit secrets. Redact sensitive keys before hashing or storing snapshots
if the raw values are secret.

### 9.9 Deployment Event

Emit `deployment` events:

- at process startup;
- after a deployment is detected;
- after a config hot reload;
- after a rollback;
- when a pending deployment is stale or mismatched.

Statuses:

- `startup_detected`;
- `pending_merge`;
- `merged`;
- `deploying`;
- `deployed`;
- `rollback_started`;
- `rolled_back`;
- `stale`;
- `mismatch_detected`.

Deployment events connect PRs, approvals, commits, config versions, and live
telemetry.

### 9.10 Indicator Snapshot

Emit `indicator_snapshot` at important decision points, not necessarily every
bar for every symbol.

Use it for:

- signal fired;
- signal rejected;
- entry decision;
- exit decision;
- unusual filter block;
- regime transition;
- diagnostics sampling.

Include:

- symbol/pair;
- timeframe;
- bar ID;
- indicator dict;
- signal name;
- signal strength;
- decision: `enter`, `skip`, `exit`, `manage`;
- lineage fields.

### 9.11 Market Snapshot And Order Book Context

Emit `market_snapshot` and `orderbook_context` around entry and exit decisions
when available.

Market snapshot:

- bid;
- ask;
- mid;
- last trade;
- spread bps;
- volume;
- ATR or volatility proxy;
- funding rate;
- open interest;
- session;
- corporate action or adjustment status, if equity data.

Order book context:

- best bid/ask;
- depth within configured bps;
- imbalance ratio;
- related trade/order ID;
- entry/exit context.

### 9.12 Portfolio Rule Event

Emit `portfolio_rule` or `risk_decision` whenever portfolio or OMS-level logic
blocks, scales, or alters a strategy intent. Also emit sampled pass events for
important rules when volume is high enough that logging every pass would be too
large.

Examples:

- gross exposure cap;
- per-symbol cap;
- sector cap;
- correlation crowding;
- daily loss limit;
- cooldown;
- max concurrent positions;
- allocation lock;
- strategy disabled by regime.

These events are important because otherwise a strategy may look like it
under-traded when the real cause was portfolio coordination.

Canonical shape:

```json
{
  "schema_version": "portfolio_rule_event_v1",
  "event_type": "portfolio_rule",
  "scope": "portfolio",
  "bot_id": "stock_trader",
  "strategy_id": "US_ORB_v1",
  "family_id": "stock",
  "portfolio_id": "live_portfolio",
  "account_alias": "ibkr_stock_live",
  "trace_id": "abc123def4567890",
  "signal_id": "sig_20260530_AAPL_0935",
  "order_id": "",
  "rule_name": "symbol_collision",
  "result": "block",
  "action": "block",
  "reason": "sibling strategy already holds AAPL",
  "symbol": "AAPL",
  "direction": "LONG",
  "requested_qty": 100,
  "approved_qty": 0,
  "requested_risk_R": 0.5,
  "approved_risk_R": 0.0,
  "size_multiplier": 0.0,
  "thresholds": {"symbol_collision_action": "block", "directional_cap_R": 8.0},
  "state_before": {
    "portfolio_exposure_pct": 0.35,
    "family_exposure_pct": 0.12,
    "directional_risk_R": {"LONG": 7.6, "SHORT": 0.8},
    "heat_used_R": 7.6,
    "drawdown_pct": 0.04
  },
  "state_after": {
    "portfolio_exposure_pct": 0.35,
    "family_exposure_pct": 0.12,
    "directional_risk_R": {"LONG": 7.6, "SHORT": 0.8},
    "heat_used_R": 7.6,
    "drawdown_pct": 0.04
  },
  "sibling_positions": [
    {
      "sibling_strategy_id": "IARIC_v1",
      "symbol": "AAPL",
      "direction": "LONG",
      "notional": 9000.0,
      "same_symbol": true
    }
  ],
  "strategy_version": "US_ORB_v1.4.2",
  "config_version": "cfg_0123456789abcdef",
  "portfolio_config_version": "pcfg_0123456789abcdef",
  "risk_config_version": "risk_0123456789abcdef",
  "allocation_version": "alloc_0123456789abcdef",
  "deployment_id": "dep_2026_05_30_abc123",
  "timestamp": "2026-05-30T13:35:00+00:00"
}
```

Use `result = "pass"`, `"block"`, `"scale"`, `"halt"`, or `"warn"`.
Preserve both requested and approved sizing so the assistant can measure
opportunity cost and distinguish hard constraints from soft reductions.

### 9.13 Position And Portfolio Snapshot Events

Emit `position_snapshot` and `portfolio_snapshot` events at a bounded interval,
at strategy startup, after fills, and near daily close.

`position_snapshot` should include:

- `portfolio_id`, `account_alias`, `bot_id`, `family_id`, and `strategy_id`;
- symbol, direction, quantity, average price, mark price, notional, unrealized
  PnL, realized PnL, fees, and currency;
- entry time, last update time, and source table or broker source;
- stop, target, trailing-stop, and risk-at-stop when known;
- sector/industry/asset-class tags when relevant;
- lineage fields and config versions.

`portfolio_snapshot` should include:

- account equity, cash, buying power, margin used, and currency;
- gross/net exposure by symbol, direction, sector, family, and strategy;
- heat used and heat cap in R and percent-of-equity terms;
- daily/weekly loss-stop usage;
- open position count and max concurrent position limits;
- drawdown tier state and applied size multiplier;
- family allocation targets and realized allocation drift;
- correlation/crowding summary when available.

These snapshots power portfolio risk cards, sector concentration, allocation
drift, drawdown correlation, and concurrent-position analysis. They must be
bounded and redacted, but they should be rich enough to reconstruct portfolio
state at any material decision time.

### 9.14 Allocation Snapshot Event

Emit `allocation_snapshot` when allocations load, change, or are reconciled.

Required fields:

- `portfolio_id`;
- `allocation_version`;
- `portfolio_config_version`;
- `risk_config_version`, when risk rules share the same allocation surface;
- `strategy_registry_version`;
- family, bot, and strategy target weights;
- observed weights from current equity/notional;
- drift by family/bot/strategy;
- min/max allocation constraints;
- max single rebalance constraint;
- source of change: `startup`, `manual`, `assistant_proposal`, `hot_reload`,
  `rollback`, or `broker_reconcile`;
- proposal IDs, suggestion IDs, approval IDs, and PR/commit references when
  applicable.

Portfolio allocation proposals cannot be evaluated cleanly unless the assistant
knows what weights were intended, what weights were actually live, and when the
change became active.

### 9.15 Family Daily Snapshot Event

Emit `family_daily_snapshot` for each strategy family after local close.

Required fields:

- `family_id`, `portfolio_id`, date, timezone, and snapshot kind;
- strategy IDs active in the family;
- total net PnL, gross PnL, fees, trade count, win/loss count, win rate, profit
  factor, max drawdown, average exposure, and active strategy count;
- family allocation target, realized allocation, and allocation drift;
- blocks/scales by portfolio rule;
- concurrent-position counts and same-symbol overlaps;
- sector or symbol concentration for the family;
- lineage summary and gap flags.

Family snapshots let the assistant compare swing, momentum, stock, crypto, or
other families without forcing every portfolio insight through individual bot
summaries.

### 9.16 Correlation, Sector, And Concurrent Exposure Events

Emit or derive bounded daily summaries for:

- `correlation_snapshot`: pairwise strategy/bot/family PnL correlation,
  drawdown correlation, lookback window, sample count, and threshold breaches;
- `sector_exposure`: exposure by sector/industry/asset class, long/short split,
  HHI/concentration score, symbols and strategies contributing to each sector;
- `concurrent_position_analysis`: same-symbol, same-direction, opposite-side,
  and correlated-symbol overlaps at entry time.

These are portfolio-level learning features, not just dashboard niceties. They
are the evidence behind `correlation_crowding`, allocation rebalancing,
coordination rules, and sector-cap proposals.

### 9.17 Pipeline Funnel Snapshot

For strategies with multi-stage funnels, emit periodic `pipeline_funnel`
snapshots.

Example funnel:

```json
{
  "signals_generated": 120,
  "setups_qualified": 48,
  "confirmations_passed": 21,
  "risk_approved": 14,
  "entries_taken": 11,
  "wins": 6,
  "losses": 5,
  "per_symbol_breakdown": {},
  "assessment": "volume gate is main blocker"
}
```

This helps weekly diagnosis without granting weekly analysis authority over
monthly candidate selection.

### 9.18 Regime Transition Event

Emit `regime_transition` if the repo owns or consumes a regime classifier.

Include:

- `from_regime`;
- `to_regime`;
- confidence;
- stress level, if applicable;
- computed timestamp;
- applied config or rule changes;
- lineage fields.

Do not invent predictive regime fields unless the model actually predicts
future regime transitions. Concurrent classifiers should be instrumented as
concurrent context only.

### 9.19 Decision Event For Parity

Emit or export normalized `decision_event` records for parity.

Shape:

```json
{
  "schema_version": "decision_event_v1",
  "event_type": "decision_event",
  "bot_id": "stock_trader",
  "strategy_id": "US_ORB_v1",
  "family_id": "stock",
  "portfolio_id": "live_portfolio",
  "strategy_version": "US_ORB_v1.4.2",
  "config_version": "cfg_0123456789abcdef",
  "portfolio_config_version": "pcfg_0123456789abcdef",
  "risk_config_version": "risk_0123456789abcdef",
  "allocation_version": "alloc_0123456789abcdef",
  "deployment_id": "dep_2026_05_30_abc123",
  "parameter_set_id": "param_1111222233334444",
  "code_sha": "abcdef1234567890",
  "code": "ENTRY_REJECTED",
  "decision_kind": "filter",
  "ts": "2026-05-30T13:35:00+00:00",
  "symbol": "AAPL",
  "timeframe": "5m",
  "bar_id": "AAPL:5m:2026-05-30T13:35:00+00:00",
  "state_ref": "state_abc123",
  "emitted_actions": [],
  "details": {
    "filter_name": "spread_gate",
    "threshold": 8.0,
    "actual_value": 9.1,
    "reason": "spread_bps_above_threshold"
  },
  "trace_id": "abc123def4567890"
}
```

Decision events must be deterministic enough that a replay run can emit the same
decision stream for the same bars, fills, order updates, config, and code SHA.
At portfolio level, decision events should also represent heat-cap checks,
drawdown-tier sizing, allocation locks, direction filters, symbol collisions,
correlation caps, family contract caps, and coordinator cooldowns. Use the same
`trace_id` as the originating signal/order so strategy and portfolio decisions
can be replayed as one chain.

## 10. Process Quality And Root Cause Taxonomy

Each completed trade should have:

- `process_quality_score`: integer 0 to 100;
- `root_causes`: controlled taxonomy list;
- `evidence_refs`: optional references to fields or events that explain score.

Use the assistant taxonomy:

- `regime_mismatch`
- `weak_signal`
- `strong_signal`
- `late_entry`
- `early_exit`
- `premature_stop`
- `slippage_spike`
- `good_execution`
- `filter_blocked_good`
- `filter_saved_bad`
- `risk_cap_hit`
- `data_gap`
- `order_reject`
- `latency_spike`
- `correlation_crowding`
- `funding_adverse`
- `funding_favorable`
- `regime_aligned`
- `normal_loss`
- `normal_win`
- `exceptional_win`

Keep scoring deterministic. Models may later interpret evidence, but bots
should not call an LLM to assign process quality.

## 11. Strategy Hook Map

Add instrumentation at these hook points.

Startup:

- load instrumentation config;
- compute `code_sha`;
- compute effective config;
- compute `config_version` and `parameter_set_id`;
- compute `portfolio_config_version`, `risk_config_version`,
  `allocation_version`, and `strategy_registry_version`;
- resolve `deployment_id`;
- emit `deployment` with `startup_detected` or `deployed`;
- emit `config_snapshot`;
- emit `allocation_snapshot`;
- emit initial `portfolio_snapshot` and open `position_snapshot` records;
- start sidecar;
- start heartbeat.

Per bar:

- begin instrumentation bar cycle;
- record bar ID and data source;
- capture market/regime context when cheap;
- emit sampled indicator snapshots if configured;
- record data gaps.

Signal evaluation:

- assign `signal_id`;
- record signal factors and strength;
- record filter/gate decisions in order;
- if signal is blocked after setup qualification, emit `missed_opportunity`;
- emit decision events for important pass/block outcomes.

Risk and portfolio coordination:

- record risk check inputs;
- emit risk decision or portfolio rule event;
- link risk events to `signal_id`, `trace_id`, and potential `order_id`.
- record requested vs approved quantity, notional, risk, and size multiplier;
- record portfolio state before and after approval;
- capture sibling positions and same-symbol/correlated-symbol overlap;
- emit decision events for heat cap, drawdown tier, symbol collision,
  directional cap, family contract cap, and allocation lock outcomes.

Order intent and routing:

- emit order intent created;
- emit risk approved/rejected;
- emit routed/acked/working/rejected/cancelled/filled events;
- capture latency and slippage when known.

Entry fill:

- freeze entry context;
- record strategy params, sizing inputs, portfolio state, market snapshot,
  order book, fill details, and initial stop/risk;
- emit optional `trade_entry` diagnostic event.

Position management:

- emit decision events for stop moves, partial exits, add-ons, time stops,
  overnight decisions, trailing rule changes, and risk reductions;
- update MFE/MAE tracking from bars.

Exit decision and fill:

- emit exit decision event;
- emit order lifecycle events;
- compute completed trade metrics;
- score process quality;
- emit canonical `trade`;
- schedule post-exit backfill.

Daily close:

- run missed-opportunity backfills;
- finalize post-exit backfills when available;
- build daily snapshot;
- build family daily snapshots;
- build portfolio snapshot, allocation drift summary, rule-block summary,
  sector exposure summary, and concurrent-position summary;
- compute or export correlation and drawdown-overlap summaries when enough
  history is available;
- flush sidecar.

Shutdown:

- emit heartbeat or lifecycle event with shutdown reason;
- stop sidecar cleanly;
- flush writers.

## 12. Sidecar Requirements

The sidecar should:

- read local JSON/JSONL files incrementally;
- wrap events into the relay envelope;
- sort by priority;
- send batches to `/events`;
- HMAC-sign canonical JSON with SHA-256;
- optionally gzip payloads;
- persist watermarks atomically only after successful send;
- retry with exponential backoff;
- expose diagnostics in heartbeat;
- not delete unsent evidence prematurely;
- prune old local files only after configured age/size limits.

Sidecar diagnostics should include:

- buffer depth;
- relay reachable;
- last successful forward time;
- total forwarded;
- last error;
- oldest unsent event age;
- local disk usage;
- active relay URL host, without secrets.

Never block strategy execution on sidecar delivery.

## 13. Market Data And Coverage

The trading repo does not need to own the canonical monthly market-data sync
unless it is the only reliable source for a feed. However, it should support
the target monthly loop by emitting enough metadata for data alignment:

- `data_source_id` on every event;
- `bar_id` on every bar-linked event;
- symbol, timeframe, and session metadata;
- exchange timestamps;
- data gap events;
- corporate-action/adjustment metadata when relevant;
- feed reconnect and stale-bar heartbeat fields.

If the trading repo exports market data as fallback, write parquet or another
structured format plus a coverage manifest containing:

- market;
- symbol;
- timeframe;
- data source;
- start/end timestamps;
- bar count;
- missing bars;
- timezone/session info;
- checksum;
- source version.

The assistant/backtest reproducibility contract should rely on data manifests,
config versions, and code SHAs, not on committing large data files to git.

## 14. Decision-Level Parity

For the target monthly loop, PnL similarity is not enough. Structural candidates
must prove decision-level parity between live strategy logic and replay logic.

The trading repo should make this possible by one of two approaches.

Preferred approach:

- extract strategy logic into a pure or mostly pure strategy core;
- live runtime imports the same core;
- backtest/replay imports the same core;
- brokers, feeds, clocks, and persistence are adapters around the core.

Acceptable approach:

- keep live strategy code in the trading repo;
- expose a stable decision adapter that can feed historical bars, fills, and
  order updates into the live logic;
- make the backtest repo compare its adapter output to the live adapter output.

Decision parity must cover:

- signals;
- filter/gate decisions;
- entry requests;
- order intent fields;
- risk approvals/rejections;
- position sizing;
- portfolio rule pass/block/scale decisions;
- allocation locks and target-weight constraints;
- heat-cap and drawdown-tier decisions;
- symbol, sector, family, and correlation caps;
- stop placement;
- stop movement;
- partial exits;
- full exits;
- cooldowns and coordination blocks;
- session/time rules;
- data-gap behavior.

Parity artifacts should include:

- `decision_stream_live.jsonl`;
- `decision_stream_replay.jsonl`;
- `decision_parity_report.json`;
- `strategy_plugin_contract.json` or equivalent live/backtest adapter contract;
- trade count match rate;
- signal match rate;
- filter match rate;
- entry match rate;
- exit match rate;
- stop/sizing/risk-block match rates;
- portfolio-rule and allocation-gate match rates;
- PnL, cost, and drawdown deltas;
- missing explanation counts.

Live decision event codes should be stable. Avoid free-form decision code churn.

For portfolio-level structural changes, the replay harness must load the same
effective portfolio config, risk config, allocation weights, drawdown tiers,
coordination rules, and strategy registry that were live. A strategy plugin that
ignores the portfolio layer is diagnostics-only for allocation or coordination
proposals, even if its individual entry/exit logic replays correctly.

## 15. Agent Implementation Phases

Use these phases when implementing from scratch.

### Phase 0: Reconnaissance

Read the trading repo and identify:

- strategy entry points;
- strategy IDs;
- config load path;
- broker/feed adapters;
- order lifecycle;
- risk and portfolio controls;
- allocation, strategy-registry, and family-configuration sources;
- position sources used by portfolio/risk rules;
- trade state model;
- position management logic;
- daily close or scheduler hooks;
- data storage paths;
- deployment mechanism;
- test framework.

Do not edit strategy logic in this phase.

### Phase 1: Instrumentation Skeleton

Add:

- config file;
- metadata helper;
- atomic JSONL writer;
- error logger;
- heartbeat emitter;
- sidecar with watermarks, HMAC, retry, gzip, and diagnostics;
- tests for metadata and sidecar.

Acceptance:

- sidecar can run with no relay URL without crashing;
- missing HMAC warns in dev and fails only if the repo's deployment policy
  explicitly requires it;
- instrumentation failures are caught and reported.

### Phase 2: Lineage Foundation

Add:

- code SHA resolver;
- effective config snapshot;
- config hash/version;
- portfolio, risk, allocation, and strategy-registry hash/version;
- parameter-set hash;
- deployment ID resolver;
- startup deployment event;
- config snapshot event;
- lineage compatibility test.

Acceptance:

- startup emits deployment and config snapshot;
- startup emits allocation and portfolio/risk config lineage when applicable;
- trade/missed/order events can inherit the same lineage values;
- tests fail if `strategy_version`, `config_version`, or `deployment_id` is
  missing from monthly-critical events.

### Phase 3: Trade And Order Instrumentation

Add:

- trade entry context freeze;
- completed trade logger;
- order lifecycle logger;
- slippage/latency capture;
- MFE/MAE tracking;
- process quality scorer;
- root cause taxonomy validation.

Acceptance:

- a synthetic trade produces a valid completed `trade` event;
- order events link to trade and trace IDs;
- process score is 0 to 100;
- root causes are in the controlled taxonomy.

### Phase 4: Signal, Filter, And Missed Opportunity Instrumentation

Add:

- signal IDs;
- signal factors;
- ordered filter decision capture;
- missed opportunity logger;
- hypothetical entry calculation;
- backfill worker;
- simulation policy file.

Acceptance:

- blocked qualified signals emit `missed_opportunity`;
- all active filters are represented;
- backfills update or supersede pending missed events without duplicate logical
  records;
- passed signals do not incorrectly emit missed opportunities.

### Phase 5: Daily Snapshot And Health

Add:

- daily snapshot builder;
- family daily snapshot builder;
- portfolio snapshot builder;
- rolling stats;
- per-strategy summary;
- per-family summary;
- allocation drift summary;
- experiment breakdown;
- root-cause distribution;
- heartbeat gap detection;
- sidecar diagnostics in heartbeat.

Acceptance:

- final daily snapshot is written after market close;
- daily totals match trade JSONL;
- family and portfolio totals reconcile with per-strategy files;
- uptime and error counts are included;
- missing optional data produces empty/null fields, not crashes.

### Phase 6: Portfolio, OMS, And Enriched Context

Add as relevant:

- indicator snapshots;
- order book context;
- market snapshots;
- portfolio rule events;
- risk decision events;
- position snapshots;
- portfolio snapshots;
- allocation snapshots;
- family snapshots;
- sector exposure summaries;
- concurrent-position snapshots;
- correlation and drawdown-overlap summaries;
- regime context;
- pipeline funnel snapshots;
- post-exit price tracking.

Acceptance:

- enriched context links to trade/signal/order IDs;
- portfolio events link requested vs approved strategy intent;
- family and portfolio snapshots can build portfolio risk cards and rolling
  portfolio metrics;
- allocation snapshots can explain what target weights were live;
- portfolio rule events make every block, halt, and size reduction attributable;
- sampling is bounded;
- large nested payloads do not overwhelm sidecar batches.

### Phase 7: Decision Parity Hooks

Add:

- normalized `DecisionEvent` model;
- decision capture helpers;
- pure core adapter or live decision adapter;
- replay export command;
- parity fixture tests.

Acceptance:

- a fixture can feed bars/fills/order updates into live strategy logic and
  produce a normalized decision stream;
- replay can compare live and replay decision streams;
- parity report includes match rates for signals, filters, entries, exits,
  stops, sizing, risk blocks, portfolio rules, and allocation gates.

### Phase 8: End-To-End Relay Compatibility

Add:

- local sidecar integration test;
- relay envelope compatibility test;
- assistant-schema compatibility test if `trading_assistant` schemas are
  available as a dev dependency or copied fixture.

Acceptance:

- one synthetic trading day produces trade, missed, order, heartbeat, daily,
  family, portfolio, allocation, config, deployment, and error fixtures;
- sidecar forwards them in priority order;
- duplicate events are idempotent;
- payloads validate against the assistant-side contract.

## 16. Compatibility Tests For `trading_assistant`

Add tests that construct payloads and validate the expected assistant fields.

Minimum test cases:

- `TradeEvent` includes `bot_id`, `strategy_id`, `trade_id`, entry/exit times,
  PnL, process score, root causes, and lineage.
- `MissedOpportunityEvent` includes `bot_id`, `strategy_id`, signal details,
  `blocked_by`, `filter_decisions`, and lineage.
- `DailySnapshot` includes date, bot ID, totals, per-strategy summary, lineage
  summary, and no invalid numeric values.
- `OrderEvent` includes order ID, status, pair, qty, strategy ID, and trace ID.
- `PortfolioRuleEvent` includes rule name, result, requested vs approved sizing,
  state before/after, and portfolio/risk config versions.
- `PositionSnapshot` includes symbol, direction, quantity, notional, mark price,
  PnL, and lineage without leaking raw account numbers.
- `PortfolioSnapshot` includes exposure by strategy, family, direction, symbol,
  and sector where available.
- `AllocationSnapshot` includes target weights, observed weights, drift,
  `allocation_version`, and source of change.
- `FamilyDailySnapshot` reconciles to the sum of member strategy snapshots.
- `FilterDecisionEvent` computes a correct `margin_pct`.
- `ParameterChangeEvent` includes before/after values and source.
- `DeploymentEvent` includes code/config/deployment identity.
- Sidecar envelope includes `event_id`, `bot_id`, `event_type`, `payload`, and
  `exchange_timestamp`.
- Required monthly lineage fields are present on trade and missed events.
- Portfolio lineage fields are present on portfolio, risk, allocation, order,
  and portfolio-rule events.
- Event ID generation is deterministic.
- Instrumentation exceptions are swallowed and emitted as instrumentation errors.

If importing `trading_assistant` as a dependency is practical, validate against:

- `schemas.events.TradeEvent`;
- `schemas.events.MissedOpportunityEvent`;
- `schemas.events.DailySnapshot`;
- `schemas.enriched_events.FilterDecisionEvent`;
- `schemas.enriched_events.ParameterChangeEvent`;
- `schemas.portfolio_risk.PortfolioRiskCard`;
- `schemas.portfolio_metrics.FamilyDailySnapshot`;
- `schemas.portfolio_metrics.PortfolioRollingMetrics`;
- `schemas.portfolio_metrics.DrawdownCorrelation`;
- `schemas.portfolio_allocation.PortfolioAllocationReport`;
- `schemas.decision_parity.DecisionParityReport`;
- `schemas.replay_parity.ReplayParityReport`.

If not practical, keep local fixture schemas that mirror the contract and run a
cross-repo contract test in CI.

## 17. Definition Of Done

Instrumentation is ready for daily/weekly diagnostics when:

- completed trades, missed opportunities, daily snapshots, errors, heartbeats,
  order events, and filter decisions are emitted;
- family snapshots, portfolio snapshots, allocation snapshots, position
  snapshots, and portfolio-rule/risk-decision events are emitted when the repo
  has portfolio or OMS logic;
- sidecar forwarding is reliable and idempotent;
- process quality and root causes are populated;
- daily snapshots reconcile with local trade files;
- family and portfolio snapshots reconcile with per-strategy trade and position
  files;
- instrumentation failures do not affect trading.

Instrumentation is ready for monthly authoritative validation when:

- `strategy_version`, `config_version`, and `deployment_id` are present on at
  least 95 percent of monthly-critical trade and missed-opportunity events;
- `portfolio_config_version`, `risk_config_version`, `allocation_version`, and
  `strategy_registry_version` are present on portfolio/OMS/risk/allocation
  events when those layers affect behavior;
- `code_sha`, `parameter_set_id`, `bar_id`, `data_source_id`, and timestamps are
  present wherever relevant;
- startup emits deployment and config snapshot events;
- telemetry manifests can classify the strategy as `authoritative`;
- portfolio telemetry can support `PortfolioRiskCard`, `FamilyDailySnapshot`,
  `PortfolioRollingMetrics`, allocation drift, sector exposure, and drawdown
  correlation without guessing;
- data gaps and stale heartbeats are visible;
- decision parity hooks exist for the strategy family.

Instrumentation is ready for structural candidate scoring when:

- live strategy behavior is imported by the replay layer or decision-equivalent
  through an adapter;
- decision parity covers signals, filters, entries, exits, stops, sizing, and
  risk blocks;
- portfolio structural changes can replay allocation, heat-cap, drawdown-tier,
  symbol-collision, sector-cap, correlation-cap, and coordination behavior;
- parity reports are generated for incumbent behavior;
- structural candidates can record live repo patch, backtest adapter patch,
  config/schema patch, tests, rollback plan, and code SHAs.

## 18. Common Failure Modes

Avoid these implementation mistakes:

- generating random event IDs;
- using local timestamps as exchange timestamps;
- omitting deployment ID because "nothing changed";
- hashing only one config file instead of effective runtime config;
- emitting raw secrets in config snapshots;
- logging only completed trades and no blocked signals;
- logging strategy events but omitting the portfolio/risk layer that resized or
  blocked those events;
- emitting only final exposure without requested-vs-approved sizing;
- omitting allocation, portfolio-config, or risk-config versions on portfolio
  events;
- aggregating family/portfolio PnL without reconciling to member strategy files;
- treating missed-opportunity backfills as proof of strategy improvement;
- sending entry-stage trade events as canonical completed trades;
- letting sidecar watermarks advance before successful delivery;
- making sidecar delivery synchronous on the trade hot path;
- changing strategy control flow while adding instrumentation;
- using free-form root causes outside the taxonomy;
- relying on PnL similarity instead of decision-level parity;
- emitting huge indicator snapshots every bar without sampling or limits.

## 19. Suggested Agent Workflow

When a coding agent implements this in a new repo:

1. Create a branch.
2. Read strategy entry points, config loading, order lifecycle, trade state, and
   existing tests.
3. Add the instrumentation skeleton and tests first.
4. Add lineage startup events before trade hooks.
5. Add trade/order hooks with no strategy behavior changes.
6. Add signal/filter/missed-opportunity hooks.
7. Add portfolio/risk/OMS hooks, position snapshots, allocation snapshots, and
   family/portfolio snapshots.
8. Add daily snapshot and heartbeat.
9. Add sidecar integration and compatibility tests.
10. Add decision-parity hooks once basic telemetry is stable.
11. Run the repo's full tests plus instrumentation tests.
12. Produce a short rollout note listing enabled event types, known gaps, and
    whether the repo is diagnostics-only or monthly-authoritative-ready.

The agent should keep edits small and localized. If a hook requires refactoring
strategy logic, first add a thin wrapper or observer. Extract pure strategy core
only when parity work begins or when the repo already has a clean boundary.

## 20. Minimal First-Day Smoke Test

After implementation, run a synthetic or paper-mode session that does the
following:

- starts the bot;
- emits deployment and config snapshot;
- emits allocation and portfolio snapshots;
- emits at least two heartbeats;
- evaluates one signal that passes filters;
- evaluates one signal that is blocked;
- submits one order intent;
- runs one portfolio/risk rule that approves, scales, or blocks the intent;
- simulates an order fill;
- completes one trade;
- builds one daily snapshot;
- runs the sidecar once.

Expected local files:

```text
instrumentation/data/deployments/deployments_YYYY-MM-DD.jsonl
instrumentation/data/config_changes/config_changes_YYYY-MM-DD.jsonl
instrumentation/data/heartbeats/heartbeat_YYYY-MM-DD.jsonl
instrumentation/data/missed/missed_YYYY-MM-DD.jsonl
instrumentation/data/orders/orders_YYYY-MM-DD.jsonl
instrumentation/data/portfolio_rules/portfolio_rules_YYYY-MM-DD.jsonl
instrumentation/data/positions/positions_YYYY-MM-DD.jsonl
instrumentation/data/portfolio/portfolio_snapshots_YYYY-MM-DD.jsonl
instrumentation/data/family/family_snapshots_YYYY-MM-DD.jsonl
instrumentation/data/allocations/allocations_YYYY-MM-DD.jsonl
instrumentation/data/trades/trades_YYYY-MM-DD.jsonl
instrumentation/data/daily/daily_YYYY-MM-DD.json
instrumentation/data/.sidecar_buffer/watermark.json
```

Expected checks:

- no instrumentation exception reaches the trading loop;
- all event IDs are stable across re-read;
- sidecar can resend duplicate events without creating duplicate queue entries;
- monthly lineage fields are present on trade and missed events;
- portfolio lineage fields are present on portfolio/risk/allocation events;
- daily snapshot totals match trade JSONL;
- family and portfolio totals reconcile with strategy snapshots and positions;
- heartbeat includes sidecar diagnostics;
- no secrets appear in any JSON file.

## 21. Final Standard

Optimal instrumentation makes the trading repo legible to the assistant without
making the assistant part of the trading loop.

The final state should answer these questions from structured evidence:

- What strategy made this decision?
- What code and config produced it?
- What deployment was live?
- What data source and bar did it use?
- Why did the signal pass or fail?
- What order did the strategy intend?
- What portfolio, family, allocation, and risk state existed at that moment?
- Did a portfolio rule approve, resize, block, or halt the intent?
- What allocation, heat cap, drawdown tier, sector cap, and coordination config
  was live?
- What did the broker do?
- What was the execution quality?
- What would replay have done with the same inputs?
- Did live and replay agree at the decision level?
- Did live and replay agree on portfolio/OMS decisions, not just strategy
  entry/exit decisions?
- Is the evidence complete enough for monthly authoritative validation?

If the answer to any of those questions is "unknown", emit more structured
instrumentation before asking the monthly loop to trust the strategy.
