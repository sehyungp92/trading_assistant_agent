# Trading Reference Instrumentation Implementation Guide

Date: 2026-05-31

Audience: Codex or another coding agent implementing the optimal
instrumentation target in `_references/trading/`.

Primary source guide:
`docs/2026-05-30-optimal-trading-repo-instrumentation-guide.md`

Reference repo audited:
`_references/trading/`

## 1. Purpose

This guide translates the optimal instrumentation target into a concrete
implementation plan for the current `_references/trading/` monorepo.

The current repo is not a blank repo. It already has a substantial
instrumentation foundation:

- per-family instrumentation packages for `swing`, `momentum`, and `stock`;
- structured trade, missed-opportunity, order, filter, indicator, market,
  error, heartbeat, and daily-snapshot events;
- sidecars with watched directories, batching, HMAC support, retry behavior,
  diagnostics, and mutable-file watermarking;
- a unified OMS with risk gateway, portfolio rules, intent denials,
  reconciliation, position persistence, and family-aware risk state;
- config registry and capital allocation helpers;
- live/replay parity infrastructure for strategy, OMS, and family surfaces.

The goal is therefore not to add a parallel logging system. The goal is to
upgrade the existing instrumentation into the optimal evidence contract needed
by `trading_assistant` for:

- daily and weekly diagnostics;
- monthly authoritative strategy validation;
- portfolio-level attribution across allocation, risk, heat, drawdown,
  coordination, sector, and family behavior;
- decision-level live/backtest parity for structural strategy or portfolio
  changes.

The most important finding from the current-state audit is:

Strategy-level telemetry is already in a useful state, but it is not yet
monthly-authoritative because lineage is incomplete. Portfolio-level and OMS
telemetry exists, but it is too lossy for the optimal target because key risk
and allocation decisions are reduced before they reach the assistant.

## 2. Implementation Principle

Use the current repo's existing instrumentation paths. Do not replace them.

The implementation should be surgical:

- preserve the existing `strategies/<family>/instrumentation/src/*` packages;
- add a small shared lineage and contract layer under `libs/`;
- thread that shared context into the existing loggers and sidecars;
- enrich existing payloads without changing trading behavior;
- preserve old field aliases such as `param_set_id`, `signal_id`, and
  Trading Assistant compatibility aliases;
- update tests to require the new contract.

Instrumentation must remain fail-open:

- no trade path should block on instrumentation;
- no OMS approval path should depend on event writes;
- no sidecar delivery should run synchronously in the hot path;
- missing lineage should emit a warning/error event but must not stop trading.

## 3. Current Implementation Map

### 3.1 Strategy Families

The monorepo has three currently instrumented production families declared in
the README and enabled in `config/strategies.yaml`:

| Family | Strategies |
|---|---|
| `swing` | `AKC_HELIX`, `ATRSS`, `TPC` |
| `momentum` | `NQ_REGIME`, `NQDTC_v2.1`, `VdubusNQ_v4`, `DownturnDominator_v1` |
| `stock` | `IARIC_v1`, `ALCB_v1` |

Current registry caveat:

`config/strategies.yaml` also declares disabled research-phase `scalp`
strategies (`SCALP_IVB_AUCTION`, `SCALP_PO3_REVERSAL`). They do not currently
have a live `strategies/scalp/instrumentation` package in this repo and should
not be treated as production-instrumented until the scalp coordinator,
OMS/risk wiring, heartbeat, and instrumentation package exist.

Each family has an instrumentation package:

- `_references/trading/strategies/swing/instrumentation/src/`
- `_references/trading/strategies/momentum/instrumentation/src/`
- `_references/trading/strategies/stock/instrumentation/src/`

These packages are similar enough that shared contract code should live in one
place and be imported by each family instead of copying large changes three
times.

### 3.2 Existing Strategy Event Surface

Representative files in the stock family:

- `trade_logger.py`
- `missed_opportunity.py`
- `order_logger.py`
- `filter_event_logger.py`
- `filter_decision.py`
- `indicator_logger.py`
- `market_snapshot.py`
- `process_scorer.py`
- `error_logger.py`
- `daily_snapshot.py`
- `facade.py`
- `bootstrap.py`
- `sidecar.py`
- `event_metadata.py`
- `config_snapshot.py`
- `config_watcher.py`

Repo-specific naming note:

- stock and momentum use `facade.py`, `filter_event_logger.py`, and
  `filter_decision.py`;
- swing uses `kit.py`, `hooks.py`, `filter_logger.py`,
  and `coordination_logger.py` for equivalent surfaces;
- stock and momentum currently have `config_snapshot.py`; swing should either
  get a thin `config_snapshot.py` wrapper or import the new shared config
  snapshot helpers directly from `libs/instrumentation`.

Useful current behavior:

- `TradeEvent` already captures rich entry/exit context, signal factors,
  conviction factors, sizing inputs, filter decisions, market snapshots, fill
  details, slippage, process quality, root causes, post-exit fields,
  concurrent positions, sector/industry, drawdown state, experiment IDs,
  `strategy_id`, `strategy_type`, and `param_set_id`.
- `MissedOpportunityEvent` already captures signal identity, block reason,
  filter decisions, margin, hypothetical entry, simulation policy, and
  backfilled outcomes.
- `OrderEvent` already captures order identity, status, requested and filled
  quantities, requested and fill prices, slippage, latency, reject reason, and
  event metadata.
- `DailySnapshotBuilder` already reduces local strategy files into bot-level
  daily summaries and can include `per_strategy_summary` and some portfolio
  exposure from heartbeats.
- `InstrumentationKit` is already a useful facade for strategy code, with
  fail-open wrappers around entry, exit, missed, order, heartbeat, indicator,
  filter, and stop-adjustment events.
- Sidecars already know the core event directories and assign priorities.

Current gap:

These event payloads generally do not carry the complete lineage set required
for monthly authoritative validation or portfolio-level attribution.

### 3.3 Existing OMS And Portfolio Surface

Relevant files:

- `_references/trading/libs/oms/risk/portfolio_rules.py`
- `_references/trading/libs/oms/risk/gateway.py`
- `_references/trading/libs/oms/services/factory.py`
- `_references/trading/libs/oms/models/events.py`
- `_references/trading/libs/oms/persistence/postgres.py`
- `_references/trading/config/portfolio.yaml`
- `_references/trading/config/strategies.yaml`
- `_references/trading/config/sector_map.yaml`
- `_references/trading/libs/config/models.py`
- `_references/trading/libs/config/loader.py`
- `_references/trading/libs/config/registry.py`
- `_references/trading/libs/config/capital_allocation.py`

Useful current behavior:

- `PortfolioRuleChecker` has rich rule coverage: regime disable, NQDTC
  direction filter, strategy multipliers, drawdown tiers, dynamic allocation,
  momentum sizing pressure, capacity fit, symbol collision, total active
  positions, strategy positions, portfolio heat, strategy heat, strategy trade
  share, directional cap, family contract cap, symbol heat, and sector heat.
- `PortfolioRulesConfig` contains enough state to explain the rule surface.
- `factory.py` already creates JSONL callbacks for `portfolio_rules` and
  `risk_denials`.
- `capital_allocation.py` resolves strategy allocated NAV from family and
  strategy allocations.
- `registry.py` can emit a stable registry artifact.
- The OMS event model includes `POSITION_UPDATE`, `RISK_HALT`,
  `RISK_DENIAL`, `RECONCILIATION_ALERT`, and `COORDINATION`.

Current gap:

The portfolio rule event callback currently normalizes rich checks into only
`rule_name`, `result`, and a small `details` object. That is too lossy for the
optimal target because the assistant needs requested versus approved sizing,
thresholds, state before and after, config versions, and portfolio/family
identity.

### 3.4 Existing Parity Surface

Relevant files:

- `_references/trading/strategies/core/events.py`
- `_references/trading/backtests/shared/parity/decision_capture.py`
- `_references/trading/tests/integration/parity/live_shadow_contract.py`
- `_references/trading/tests/integration/parity/strict_gate.py`
- `_references/trading/tests/integration/parity/*`
- `_references/trading/tests/unit/test_parity_fixtures.py`
- `_references/trading/tests/unit/test_parity_normalizers.py`
- `_references/trading/tests/unit/test_live_shadow_contract.py`

Useful current behavior:

- `DecisionEvent` exists.
- Live shadow contracts compare live and replay traces for source fingerprint,
  order intents, terminal events, trade ledger, and state snapshot.
- Family-level live/replay tests exist.
- Source fingerprints are deterministic.

Current gap:

`normalize_decision_event()` drops `strategy_id`, `state_ref`, and
`emitted_actions`, and `DecisionEvent` does not yet carry the full lineage and
portfolio context required by the optimal target.

## 4. What Is Already Good Enough

Do not spend time rebuilding these surfaces from scratch:

- the family-level instrumentation package structure;
- JSONL file writing pattern;
- `InstrumentationKit` facade pattern;
- sidecar batching, HMAC, watermarks, and diagnostics;
- trade entry/exit context capture;
- missed-opportunity backfill mechanics;
- process scoring hook location;
- order lifecycle logger;
- filter decision aliases and `margin_pct`;
- `DailySnapshotBuilder` as the bot-level daily summary builder;
- `PortfolioRuleChecker` rule logic;
- capital allocation helper semantics;
- live/replay parity harness.

The optimal implementation should extend these pieces, not replace them.

## 5. What Must Change

The current repo needs these upgrades before it reaches the optimal target.

### 5.1 Required Strategy-Level Upgrades

Add complete lineage to all monthly-critical strategy events:

- `strategy_id`
- `family_id`
- `portfolio_id`
- `account_alias`
- `strategy_version`
- `config_version`
- `portfolio_config_version`
- `risk_config_version`
- `allocation_version`
- `strategy_registry_version`
- `deployment_id`
- `parameter_set_id`
- `code_sha`
- `trace_id`
- `schema_version`

Apply this to:

- `trade`
- `trade_entry`
- `missed_opportunity`
- `order`
- `filter_decision`
- `indicator_snapshot`
- `market_snapshot`
- `stop_adjustment`
- `process_quality`
- `daily_snapshot`
- `heartbeat`
- `error`

`strategy_version`, `config_version`, and `deployment_id` are required for
monthly authoritative validation. The portfolio lineage fields are required
whenever portfolio, OMS, allocation, or risk logic affected sizing, approval,
blocking, or state.

### 5.2 Required Portfolio-Level Upgrades

Add or enrich:

- `portfolio_rule_check`
- `risk_denial`
- `risk_decision`
- `risk_halt`
- `position_snapshot`
- `portfolio_snapshot`
- `allocation_snapshot`
- `coordination_event`
- `reconciliation_alert`

The highest-priority change is to stop reducing portfolio rule checks to a
small `details` payload. The assistant must be able to reconstruct:

- what a strategy requested;
- what the OMS/risk layer approved;
- which rule changed the request;
- which rule blocked the request;
- what threshold was used;
- what portfolio/family state existed before and after the decision;
- which config and allocation versions were active.

### 5.3 Required Sidecar Upgrades

The sidecar envelope currently includes the relay-required fields but does not
duplicate lineage. Add envelope-level lineage extraction from payloads:

- `scope`
- `strategy_id`
- `family_id`
- `portfolio_id`
- `account_alias`
- `strategy_version`
- `config_version`
- `portfolio_config_version`
- `risk_config_version`
- `allocation_version`
- `strategy_registry_version`
- `deployment_id`
- `parameter_set_id`
- `experiment_id`
- `variant_id`
- `code_sha`
- `trace_id`
- `schema_version`

Also add watched directories for the new event streams:

- `positions`
- `portfolio`
- `allocations`
- `deployments`
- `config_snapshots`
- `decisions`
- `regime_transitions`
- `pipeline_funnel`

### 5.4 Required Config And Deployment Upgrades

The current repo has config models, registry loading, and minimal
`config_snapshot.py` helpers in stock/momentum, but it does not compute the
optimal versions.

Add canonical version computation for:

- strategy effective config;
- portfolio config;
- risk config;
- allocation config;
- strategy registry;
- deployment identity;
- code SHA;
- parameter set.

Important repo-specific caution:

`config/portfolio.yaml` is not the only source of portfolio/risk behavior.
Some family-specific portfolio rule config is constructed in coordinators, for
example stock coordination. Those hardcoded or dynamically constructed
`PortfolioRulesConfig` values must be included in `risk_config_version` or
emitted as a family-specific risk-config component. Otherwise the assistant
cannot know which stock sector caps, symbol collision rules, or priority rules
were live.

## 6. Target Event Surface For This Repo

### 6.1 Event Types

The final sidecar should support at least these event types:

| Event type | Scope | Priority | Notes |
|---|---|---:|---|
| `error` | `strategy` or `oms` | 0 | High severity triage |
| `bot_error` | `strategy` | 0 | Existing error alias, if retained |
| `risk_halt` | `oms` or `portfolio` | 0 | Hard halt or breaker |
| `deployment` | `strategy`, `family`, or `portfolio` | 1 | Startup/deploy identity |
| `config_snapshot` | `strategy`, `family`, or `portfolio` | 1 | Effective config and hashes |
| `parameter_change` | `strategy`, `family`, or `portfolio` | 1 | Before/after config |
| `daily_snapshot` | `strategy` | 1 | Bot/strategy daily summary |
| `trade_entry` | `strategy` | 2 | Entry-stage record, not completed trade |
| `trade` | `strategy` | 2 | Completed trade/exit record |
| `missed_opportunity` | `strategy` | 3 | Blocked or not-taken qualified signal |
| `order` | `oms` | 3 | Order lifecycle |
| `filter_decision` | `strategy` | 3 | Individual filter/gate decision |
| `portfolio_rule_check` | `portfolio` or `oms` | 3 | Rule pass/scale/block |
| `risk_denial` | `oms` | 3 | Gateway denial |
| `risk_decision` | `oms` | 3 | Approval, scale, route, or reject |
| `reconciliation_event` | `oms` or `portfolio` | 3 | Drift, inferred fill, freeze/unfreeze, admin correction |
| `coordinator_action` | `family` | 3 | Cross-strategy action |
| `position_snapshot` | `portfolio` or `family` | 4 | Position state |
| `portfolio_snapshot` | `portfolio` | 4 | Exposure/risk state |
| `allocation_snapshot` | `portfolio` | 4 | Target/observed weights |
| `indicator_snapshot` | `strategy` | 4 | Bounded sampled indicators |
| `market_snapshot` | `strategy` | 4 | Market context |
| `decision_event` | `strategy`, `family`, or `oms` | 4 | Live/replay parity |
| `heartbeat` | `strategy`, `family`, or `oms` | 5 | Liveness and diagnostics |

### 6.2 Required Common Fields

Every payload should include this common block, either as top-level fields or
inside `lineage` plus top-level copies. Prefer top-level fields because current
assistant ingestion paths already preserve known top-level fields.

```json
{
  "schema_version": "trade_event_v2",
  "event_type": "trade",
  "scope": "strategy",
  "bot_id": "stock_trader",
  "strategy_id": "IARIC_v1",
  "family_id": "stock",
  "portfolio_id": "paper_default",
  "account_alias": "paper_ibkr_1",
  "strategy_version": "IARIC_v1.0.0",
  "config_version": "cfg_0123456789abcdef",
  "portfolio_config_version": "pcfg_0123456789abcdef",
  "risk_config_version": "risk_0123456789abcdef",
  "allocation_version": "alloc_0123456789abcdef",
  "strategy_registry_version": "registry_0123456789abcdef",
  "deployment_id": "dep_2026_05_31_abcdef12",
  "parameter_set_id": "param_0123456789abcdef",
  "code_sha": "abcdef1234567890",
  "trace_id": "trace_0123456789abcdef"
}
```

Keep compatibility aliases:

- keep `param_set_id` as an alias for `parameter_set_id`;
- keep `signal_id` as an alias for `entry_signal_id` where relevant;
- keep current Trading Assistant aliases such as `market_snapshot`,
  `spread_at_entry`, `volume_24h`, `hypothetical_entry`, and `confidence`.

## 7. Shared Lineage Layer

### 7.1 Add A Shared Package

Add:

```text
_references/trading/libs/instrumentation/
  __init__.py
  lineage.py
  event_contract.py
```

Use this package from all three family instrumentation packages and from OMS
callbacks.

Do not create three independent implementations unless import constraints make
the shared package impossible.

### 7.2 `LineageContext`

Implement `LineageContext` in `libs/instrumentation/lineage.py`.

Required fields:

```python
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class LineageContext:
    bot_id: str
    strategy_id: str = ""
    family_id: str = ""
    portfolio_id: str = "default"
    account_alias: str = ""
    strategy_version: str = ""
    config_version: str = ""
    portfolio_config_version: str = ""
    risk_config_version: str = ""
    allocation_version: str = ""
    strategy_registry_version: str = ""
    deployment_id: str = ""
    parameter_set_id: str = ""
    experiment_id: str = ""
    variant_id: str = ""
    code_sha: str = ""
    proposal_ids: tuple[str, ...] = ()
    suggestion_ids: tuple[str, ...] = ()
    extras: dict[str, Any] = field(default_factory=dict)
```

Required helpers:

- `canonical_json(value) -> str`
- `stable_hash(prefix, value, length=16) -> str`
- `redact_config(value) -> dict`
- `compute_code_sha(repo_root) -> str`
- `compute_strategy_registry_version(registry) -> str`
- `compute_portfolio_config_version(portfolio_config) -> str`
- `compute_allocation_version(portfolio_config, registry) -> str`
- `compute_risk_config_version(portfolio_config, portfolio_rules_config, registry) -> str`
- `compute_strategy_config_version(strategy_manifest, effective_strategy_config, lineage_parts) -> str`
- `resolve_deployment_id(lineage, env) -> str`
- `lineage_from_runtime(...) -> LineageContext`
- `lineage_to_payload(lineage) -> dict`
- `merge_lineage(payload, lineage, scope, schema_version, event_type) -> dict`

Hash rules:

- Use canonical JSON with sorted keys.
- Redact secrets before hashing and before writing snapshots.
- Include defaults and environment overrides, not only source YAML text.
- Include dynamically built `PortfolioRulesConfig` values.
- Prefix versions: `cfg_`, `pcfg_`, `risk_`, `alloc_`, `registry_`,
  `param_`, `dep_`.

### 7.3 Version Source Rules

Compute versions from these sources:

| Version | Source |
|---|---|
| `strategy_registry_version` | `libs.config.registry.build_registry_artifact(load_strategy_registry(config_dir))` |
| `portfolio_config_version` | `load_portfolio_config(config_dir).model_dump()` |
| `allocation_version` | `portfolio.capital`, enabled strategies, family allocations, strategy allocations |
| `risk_config_version` | `portfolio.risk`, drawdown tiers, coordination, `PortfolioRulesConfig`, family-specific hardcoded/dynamic risk config |
| `config_version` | strategy manifest, effective strategy config, env overrides, risk/allocation version references |
| `parameter_set_id` | decision-affecting strategy parameters at decision time |
| `deployment_id` | explicit deployment env value if present, otherwise a generated startup ID that includes timestamp, code SHA, and config version |
| `code_sha` | git commit SHA if available, otherwise env value or `unknown` |

If a value cannot be computed:

- emit the original event anyway;
- set the missing value to `""`;
- include `lineage_gap: true`;
- include `lineage_missing_fields`;
- emit an instrumentation warning event.

## 8. Event Metadata Upgrade

Current family `event_metadata.py` files provide deterministic event IDs,
timestamps, clock skew, data source ID, and optional `bar_id`. Extend them
without breaking existing callers.

Add optional fields:

- `event_type`
- `payload_key`
- `schema_version`
- `strategy_id`
- `family_id`
- `portfolio_id`
- `trace_id`

Keep existing function signatures backward compatible. New parameters should
default to empty strings or `None`.

Target payload:

```json
{
  "event_id": "0123456789abcdef",
  "bot_id": "stock_trader",
  "event_type": "trade",
  "payload_key": "trade_1:exit",
  "exchange_timestamp": "2026-05-31T14:30:00+00:00",
  "local_timestamp": "2026-05-31T14:30:00.015000+00:00",
  "clock_skew_ms": -15,
  "data_source_id": "ibkr_us_equities",
  "bar_id": "AAPL:5m:2026-05-31T14:30:00+00:00",
  "schema_version": "event_metadata_v2",
  "strategy_id": "IARIC_v1",
  "family_id": "stock",
  "portfolio_id": "paper_default",
  "trace_id": "trace_0123456789abcdef"
}
```

Acceptance tests:

- existing event metadata tests still pass;
- event IDs remain deterministic for existing inputs;
- new fields round-trip through `to_dict()`;
- monthly-critical events cannot be constructed in tests without lineage unless
  the test explicitly opts into a missing-lineage case.

## 9. Sidecar Upgrade

### 9.1 Extend Directory Map

Update each family sidecar:

- `strategies/swing/instrumentation/src/sidecar.py`
- `strategies/momentum/instrumentation/src/sidecar.py`
- `strategies/stock/instrumentation/src/sidecar.py`

Add directory mappings:

```python
_DIR_TO_EVENT_TYPE.update({
    "risk_halts": "risk_halt",
    "risk_decisions": "risk_decision",
    "positions": "position_snapshot",
    "portfolio": "portfolio_snapshot",
    "allocations": "allocation_snapshot",
    "deployments": "deployment",
    "config_snapshots": "config_snapshot",
    "decisions": "decision_event",
    "regime_transitions": "regime_transition",
    "pipeline_funnel": "pipeline_funnel",
})
```

Add priorities:

```python
_EVENT_PRIORITY.update({
    "risk_halt": 0,
    "deployment": 1,
    "config_snapshot": 1,
    "risk_decision": 3,
    "position_snapshot": 4,
    "portfolio_snapshot": 4,
    "allocation_snapshot": 4,
    "decision_event": 4,
    "regime_transition": 4,
    "pipeline_funnel": 4,
})
```

### 9.2 Extend Envelope

Modify `_wrap_event()` so it extracts lineage from the payload and includes it
beside the relay-required fields.

The envelope should still contain:

- `event_id`
- `bot_id`
- `event_type`
- `priority`
- `payload`
- `exchange_timestamp`

Add best-effort top-level copies:

- `scope`
- `strategy_id`
- `family_id`
- `portfolio_id`
- `account_alias`
- `strategy_version`
- `config_version`
- `portfolio_config_version`
- `risk_config_version`
- `allocation_version`
- `strategy_registry_version`
- `deployment_id`
- `parameter_set_id`
- `experiment_id`
- `variant_id`
- `code_sha`
- `trace_id`
- `schema_version`

When a field is present inside `event_metadata`, extract it. When it is present
top-level, prefer the top-level value. Never parse arbitrary nested user text.

### 9.3 Trade Stage Behavior

Keep the current behavior where entry-stage trade records forward as
`trade_entry` and exit-stage/completed records forward as `trade`. That is
compatible with the target guide.

Do not treat `trade_entry` as the canonical completed trade.

### 9.4 Sidecar Tests

Extend or add sidecar tests to require:

- new directories are watched;
- lineage fields are copied into the envelope;
- payload stays a canonical JSON string on the wire;
- missing lineage does not crash wrapping;
- mutable JSONL resend behavior still works;
- daily JSON hash watermark behavior still works;
- high-priority events keep exact-ack safety.

## 10. Strategy Logger Upgrades

Apply these changes in all three families. Start with `stock` as the reference
implementation, then port to `momentum` and `swing`.

### 10.1 `TradeEvent`

Files:

- `strategies/stock/instrumentation/src/trade_logger.py`
- `strategies/momentum/instrumentation/src/trade_logger.py`
- `strategies/swing/instrumentation/src/trade_logger.py`

Add fields:

- `schema_version = "trade_event_v2"`
- `scope = "strategy"`
- `family_id`
- `portfolio_id`
- `account_alias`
- `strategy_version`
- `config_version`
- `portfolio_config_version`
- `risk_config_version`
- `allocation_version`
- `strategy_registry_version`
- `deployment_id`
- `parameter_set_id`
- `code_sha`
- `trace_id`
- `lineage_gap`
- `lineage_missing_fields`
- `proposal_ids`
- `suggestion_ids`

Keep:

- `param_set_id`
- `strategy_id`
- `strategy_type`
- `experiment_id`
- `experiment_variant`

In `to_dict()`:

- if `parameter_set_id` is empty and `param_set_id` is populated, set
  `parameter_set_id = param_set_id`;
- keep `param_set_id` for backward compatibility;
- include all lineage fields top-level;
- keep the existing `signal_id` alias;
- keep the existing Trading Assistant aliases.

In `TradeLogger.__init__()`:

- accept `lineage_context`;
- store it as `self.lineage`;
- keep existing config behavior if lineage is missing.

In `log_entry()` and `log_exit()`:

- merge lineage into the event before writing;
- compute `parameter_set_id` with the shared helper;
- assign one `trace_id` that can connect signal, filters, risk checks, order,
  fill, entry, and exit when the caller provides it;
- include `portfolio_state_at_entry` using a stable shape, not arbitrary
  strategy-specific dictionaries only;
- include `risk_decision_ref` and `portfolio_rule_trace_id` when available.

For completed `trade` events, include the join keys needed to reconstruct the
full lifecycle from runtime decision to executed exposure:

- `decision_ref`;
- `action_ref`;
- `portfolio_decision_ref`;
- `intent_id`;
- OMS/client/broker order IDs;
- fill IDs;
- strategy artifact hash;
- config version;
- resource-plan hash when the portfolio/runtime has one.

Stable `portfolio_state_at_entry` shape:

```json
{
  "portfolio_id": "paper_default",
  "family_id": "stock",
  "allocated_nav": 16666.67,
  "equity": 100000.0,
  "gross_exposure": 12500.0,
  "net_exposure": 12500.0,
  "open_position_count": 2,
  "family_open_position_count": 1,
  "portfolio_heat_R": 0.9,
  "portfolio_heat_cap_R": 2.5,
  "directional_risk_R": 0.4,
  "drawdown_pct": 0.02,
  "drawdown_tier": "normal",
  "allocation_version": "alloc_0123456789abcdef",
  "risk_config_version": "risk_0123456789abcdef"
}
```

### 10.2 `MissedOpportunityEvent`

Files:

- `strategies/stock/instrumentation/src/missed_opportunity.py`
- `strategies/momentum/instrumentation/src/missed_opportunity.py`
- `strategies/swing/instrumentation/src/missed_opportunity.py`

Add the same lineage fields as `TradeEvent`.

Also add:

- `trace_id`
- `bar_id`
- `blocked_stage`
- `candidate_intent`
- `risk_decision_ref`
- `portfolio_rule_trace_id`
- `simulation_policy_version`
- `outcome_backfill_status`

Event ID should remain deterministic. Prefer payload key:

```text
{signal_id}:{bar_id}:{blocked_by}
```

If `bar_id` is unavailable, use the current signal timestamp and symbol, but
record `lineage_gap` or `metadata_gap` for missing `bar_id`.

### 10.3 `OrderEvent`

Files:

- `strategies/stock/instrumentation/src/order_logger.py`
- `strategies/momentum/instrumentation/src/order_logger.py`
- `strategies/swing/instrumentation/src/order_logger.py`

Add:

- `scope = "oms"`
- common lineage;
- `strategy_id`;
- `family_id`;
- `portfolio_id`;
- `trace_id`;
- `intent_id`;
- `oms_order_id`;
- `broker_order_id`;
- `risk_decision_id`;
- `portfolio_rule_trace_id`;
- `requested_qty`;
- `approved_qty`;
- `requested_risk_R`;
- `approved_risk_R`;
- `requested_risk_dollars`;
- `approved_risk_dollars`;
- `order_source`: `strategy`, `oms`, `coordinator`, `reconcile`, or `manual`;
- `account_alias`.

Do not remove current order fields. Existing tests expect basic order aliases.

### 10.4 Filter, Indicator, Stop, And Market Events

Add common lineage and `trace_id` to the equivalent files:

- stock/momentum `filter_event_logger.py`
- stock/momentum `filter_decision.py`
- swing `filter_logger.py`
- `indicator_logger.py`
- `market_snapshot.py`
- stop-adjustment logging in stock/momentum `facade.py` and swing `kit.py` or
  `hooks.py`

Filter events should include:

- `signal_id`
- `bar_id`
- `filter_name`
- `filter_kind`
- `passed`
- `threshold`
- `actual_value`
- `margin_pct`
- `blocked_stage`
- `sequence`
- `trace_id`

The assistant must be able to reconstruct the ordered funnel for a qualified
signal without reading strategy source code.

### 10.5 Heartbeat

Update `InstrumentationKit.emit_heartbeat()` or the swing kit equivalent to
include:

- common lineage;
- `lineage_gap`;
- `lineage_missing_fields`;
- `sidecar_diagnostics`;
- `active_positions`;
- `open_orders`;
- `portfolio_exposure`;
- `allocation_version`;
- `risk_config_version`;
- `config_version`;
- `deployment_id`;
- heartbeat interval and gap threshold.

Heartbeats are the right place to report missing lineage without affecting
trading.

## 11. OMS And Portfolio Rule Upgrades

### 11.1 Add A Full Portfolio Rule Event

Add:

```text
_references/trading/libs/oms/instrumentation/portfolio_rule_event.py
```

The event builder should accept:

- rule name;
- result: `pass`, `scale`, `block`, `halt`, or `warn`;
- strategy intent context;
- requested sizing;
- approved sizing;
- thresholds;
- state before;
- state after;
- rule sequence;
- lineage context;
- timestamps;
- trace IDs.

Target payload:

```json
{
  "schema_version": "portfolio_rule_check_v2",
  "event_type": "portfolio_rule_check",
  "scope": "portfolio",
  "result": "scale",
  "rule_name": "symbol_collision",
  "action": "half_size",
  "reason": "sibling strategy holds AAPL",
  "trace_id": "trace_0123456789abcdef",
  "rule_trace_id": "rule_trace_0123456789abcdef",
  "check_sequence": 5,
  "strategy_id": "ALCB_v1",
  "family_id": "stock",
  "portfolio_id": "paper_default",
  "account_alias": "paper_ibkr_1",
  "symbol": "AAPL",
  "direction": "LONG",
  "requested_qty": 100,
  "approved_qty": 50,
  "requested_risk_R": 1.0,
  "approved_risk_R": 0.5,
  "requested_risk_dollars": 100.0,
  "approved_risk_dollars": 50.0,
  "size_multiplier_before": 1.0,
  "size_multiplier_after": 0.5,
  "threshold": {
    "symbol_collision_action": "half_size"
  },
  "state_before": {
    "sibling_positions": [
      {
        "strategy_id": "IARIC_v1",
        "symbol": "AAPL",
        "direction": "LONG",
        "qty": 25
      }
    ]
  },
  "state_after": {
    "approved": true
  },
  "portfolio_config_version": "pcfg_0123456789abcdef",
  "risk_config_version": "risk_0123456789abcdef",
  "allocation_version": "alloc_0123456789abcdef",
  "strategy_registry_version": "registry_0123456789abcdef",
  "deployment_id": "dep_2026_05_31_abcdef12",
  "code_sha": "abcdef1234567890"
}
```

### 11.2 Preserve Raw Rule Details

In `libs/oms/risk/portfolio_rules.py`, update `_emit()` so it does not collapse
events into a tiny details payload.

Current behavior:

- keeps `rule_name`;
- keeps `result`;
- keeps a small subset of details.

Target behavior:

- preserve original event fields;
- add standard names required by the assistant;
- add lineage;
- add `schema_version`;
- add `scope`;
- add deterministic event ID or payload key;
- keep backward-compatible aliases:
  - `rule_name`
  - `result`
  - `details.reason`
  - `details.blocked_symbol`

Do not remove existing `details`; enrich it.

### 11.3 Add Context To `check_entry()`

Extend `PortfolioRuleChecker.check_entry()` with optional keyword-only context:

```python
async def check_entry(
    self,
    strategy_id: str,
    direction: str,
    new_risk_R: float = 1.0,
    symbol: str | None = None,
    new_qty: int = 0,
    new_risk_dollars: float = 0.0,
    *,
    trace_id: str = "",
    signal_id: str = "",
    bar_id: str = "",
    exchange_timestamp: datetime | None = None,
    lineage_context: LineageContext | None = None,
) -> PortfolioRuleResult:
    ...
```

Keep all new parameters optional to avoid breaking existing call sites.

### 11.4 Enrich `PortfolioRuleResult`

Add optional fields to `PortfolioRuleResult`:

- `requested_qty`
- `approved_qty`
- `requested_risk_R`
- `approved_risk_R`
- `requested_risk_dollars`
- `approved_risk_dollars`
- `rule_trace_id`
- `applied_rules`
- `lineage_gap`

Do not remove or rename:

- `approved`
- `denial_reason`
- `size_multiplier`

### 11.5 Enrich Factory Loggers

In `libs/oms/services/factory.py`:

- update `_make_portfolio_rule_logger()` to write full payloads;
- add `family_id` and lineage if the event did not already include them;
- avoid mutating shared event objects in surprising ways;
- write to `portfolio_rules/rules_YYYY-MM-DD.jsonl`;
- preserve fail-open behavior.

Update `_make_intent_denial_logger()` similarly:

- add `schema_version = "risk_denial_v2"`;
- add `scope = "oms"`;
- add common lineage;
- add `trace_id`, `intent_id`, `strategy_id`, `family_id`, `portfolio_id`;
- include requested order details and denial reason.

### 11.6 OMS Event Loop Coverage

In each family `bootstrap.py`, the instrumentation event loop should handle or
forward:

- `RISK_DENIAL`
- `RISK_HALT`
- order lifecycle events
- `FILL`
- `POSITION_UPDATE`
- `COORDINATION`
- `RECONCILIATION_ALERT`

Existing behavior already handles key order/risk-denial paths. Extend it to
emit snapshots or structured events for the remaining OMS event types.

### 11.7 Risk Gateway Decision Events

File:

- `libs/oms/risk/gateway.py`

Add `risk_decision` events for every gateway decision that approves, scales,
denies, halts, or routes an intent.

Required fields:

- common lineage;
- `schema_version = "risk_decision_v1"`;
- `event_type = "risk_decision"`;
- `scope = "oms"`;
- `trace_id`;
- `intent_id`;
- `strategy_id`;
- `family_id`;
- `portfolio_id`;
- `symbol`;
- `side`;
- `role`;
- `decision`: `approve`, `scale`, `deny`, `halt`, or `route`;
- `reason`;
- requested quantity and risk;
- approved quantity and risk;
- daily and weekly stop usage;
- strategy heat and cap;
- portfolio heat and cap;
- account gate result;
- session gate result;
- references to any `portfolio_rule_check` events used in the decision.

This event should complement, not replace, `risk_denial`. A denial is one
terminal case; `risk_decision` is the full approval and transformation ledger.

## 12. Snapshot Implementation

For the approval-ready path, snapshots should cover lifecycle state needed for
replay, fills, reconciliation, and closeout. Do not make monitoring-only
analytics part of the approval gate.

### 12.1 Add Shared Snapshot Builders

Prefer shared builders under:

```text
_references/trading/libs/oms/instrumentation/
  position_snapshot.py
  portfolio_snapshot.py
  allocation_snapshot.py
```

Each family `InstrumentationManager` can call these builders and write the
result into its own `data_dir`.

### 12.2 Position Snapshot

Write to:

```text
strategies/<family>/instrumentation/data/positions/positions_YYYY-MM-DD.jsonl
```

Emit:

- at startup after OMS hydration;
- after fills;
- after broker reconciliation;
- near daily close.

Required fields:

- common lineage;
- `position_id`;
- `portfolio_id`;
- `account_alias`;
- `family_id`;
- `strategy_id`;
- `symbol`;
- `asset_class`;
- `sector`;
- `industry`;
- `direction`;
- `qty`;
- `avg_price`;
- `mark_price`;
- `notional`;
- `unrealized_pnl`;
- `realized_pnl`;
- `open_risk_R`;
- `open_risk_dollars`;
- `stop_price`;
- `target_price`;
- `entry_time`;
- `last_update_time`;
- `source`: `oms_db`, `broker`, `strategy_memory`, or `reconcile`;
- `source_snapshot_id`.

### 12.3 Portfolio Snapshot

Write to:

```text
strategies/<family>/instrumentation/data/portfolio/portfolio_snapshots_YYYY-MM-DD.jsonl
```

Emit:

- at startup;
- after fills;
- after risk halt;
- after allocation/config changes;
- near daily close.

Required fields:

- common portfolio lineage;
- `equity`;
- `cash`;
- `buying_power`;
- `margin_used`;
- `currency`;
- `gross_exposure`;
- `net_exposure`;
- exposure by strategy;
- exposure by family;
- exposure by symbol;
- exposure by sector;
- exposure by direction;
- `portfolio_heat_R`;
- `portfolio_heat_cap_R`;
- `daily_realized_R`;
- `weekly_realized_R`;
- `daily_stop_R`;
- `weekly_stop_R`;
- `drawdown_pct`;
- `drawdown_tier`;
- `drawdown_size_multiplier`;
- open position counts;
- max position caps;
- stale data flags;
- reconciliation status.

### 12.4 Allocation Snapshot

Write to:

```text
strategies/<family>/instrumentation/data/allocations/allocations_YYYY-MM-DD.jsonl
```

Emit:

- at startup;
- when `config/portfolio.yaml` or strategy registry changes;
- after broker/equity reconciliation;
- after assistant-approved allocation changes;
- after rollback.

Required fields:

- `portfolio_id`;
- `allocation_version`;
- `portfolio_config_version`;
- `risk_config_version`;
- `strategy_registry_version`;
- family target weights;
- strategy target weights;
- observed family weights;
- observed strategy weights;
- drift by family;
- drift by strategy;
- raw NAV;
- allocated NAV;
- source of change: `startup`, `manual`, `assistant_proposal`,
  `hot_reload`, `rollback`, or `broker_reconcile`;
- proposal IDs, suggestion IDs, approval IDs, PR or commit references when
  applicable.

### 12.5 Reconciliation And Drift Events

Emit first-class `reconciliation_event` rows whenever OMS, broker, or portfolio
truth changes because reconciliation found drift or an operator resolved it.

Required fields:

- common lineage;
- `portfolio_id`;
- `account_alias`;
- `family_id` and `strategy_id` when attributable;
- `symbol`;
- `event_reason`: `drift_detected`, `inferred_fill`, `freeze`, `unfreeze`,
  `admin_correction`, `drift_assigned`, or `eod_cleanup`;
- previous and current broker position state;
- previous and current OMS position state;
- previous and current virtual allocation state;
- `_UNKNOWN_` allocation delta when attribution is unknown;
- decision, action, intent, order, and fill refs when available;
- operator/admin reference when manually corrected.

### 12.6 Approval-Ready Snapshot Scope

For the `approval_ready` path, keep snapshots tied to lifecycle facts that are
needed for replay and risk attribution:

- startup portfolio/allocation/position state;
- fill-triggered position, allocation, and portfolio state;
- risk-control and reconciliation state changes;
- end-of-day closeout state.

Do not make monitoring-only analytics part of the approval gate. If
portfolio-rule events include sector exposure at decision time, that is enough
for the approval-ready lane.

## 13. Config Snapshot And Deployment Events

### 13.1 Upgrade Or Add `config_snapshot.py`

The current stock and momentum `config_snapshot.py` helpers capture uppercase
constants from Python modules. Keep that helper, add a swing equivalent or a
shared import path, and add repo-wide effective config snapshots.

Implement:

- `build_effective_strategy_config(strategy_id, config_dir, env)`;
- `build_effective_portfolio_config(config_dir, family_id, env)`;
- `build_effective_risk_config(family_id, portfolio_rules_config, env)`;
- `build_lineage_context(...)`;
- `write_config_snapshot(data_dir, lineage, effective_config)`;
- `write_deployment_event(data_dir, lineage, status)`.

Write files:

```text
instrumentation/data/config_snapshots/config_snapshots_YYYY-MM-DD.jsonl
instrumentation/data/deployments/deployments_YYYY-MM-DD.jsonl
```

### 13.2 Startup Events

In each family `InstrumentationManager.start()`:

1. compute lineage;
2. write `deployment` event with `status = "startup"`;
3. write `config_snapshot`;
4. write `allocation_snapshot`;
5. write initial `portfolio_snapshot`;
6. write initial `position_snapshot` records for hydrated open positions;
7. write approval-grade `deployment_metadata.json`;
8. start sidecar.

If lineage computation fails, write an instrumentation error and continue.

### 13.3 Approval-Grade Deployment Metadata Emitter

The `deployment` event is useful telemetry, but `approval_ready` also requires
a dedicated runtime-emitted metadata artifact that can be imported into
`trading_assistant_backtest/contracts/<bridge_id>/deployment_metadata.json`.
Generate it from the running bot or VPS process, not from a local assistant
checkout.

Write one metadata artifact per bridge:

- `trading_stock_family`;
- `trading_momentum_family`;
- `trading_swing_family`.

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
  "bot_id": "trading",
  "portfolio_id": "stock|momentum|swing",
  "strategy_id": "<bridge id>",
  "config_hash": "<effective config hash>",
  "strategy_version": "<deployed strategy/package version>",
  "config_version": "<effective config version>",
  "deployment_id": "<stable deployment id>",
  "telemetry_schema_version": "trading_live_shadow_contract_v1",
  "strategy_plugin_contract_path": "trading_assistant_backtest/contracts/<bridge_id>/strategy_plugin_contract.json",
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
`production_vps` when the artifact is emitted on a VPS. `repo_url` and
`source_control_origin` must be the same real Git remote, never `local://`.
`source_control_worktree_clean` must be `true`. `source_control_commit_sha`
must match `deployed_commit_sha`.

Promotion rule:

Do not set the corresponding strategy plugin contract to
`maturity = "approval_ready"` until this metadata artifact exists, its contract
hash matches the final contract file, the deployed SHA matches
`live_repo_commit_sha`, and the five validation tests still pass.

### 13.4 Config Watcher

Update `config_watcher.py` so `parameter_change` events include:

- common lineage;
- `config_version_before`;
- `config_version_after`;
- `portfolio_config_version_before`;
- `portfolio_config_version_after`;
- `risk_config_version_before`;
- `risk_config_version_after`;
- `allocation_version_before`;
- `allocation_version_after`;
- `change_source`;
- `is_safety_critical`;
- `approval_id`;
- `proposal_ids`;
- `suggestion_ids`;
- `rollback_of`, when applicable.

Do not rely only on uppercase module constants. Also watch YAML/config inputs
that influence portfolio and risk behavior.

## 14. Decision Parity Upgrade

### 14.1 Extend `DecisionEvent`

File:

- `strategies/core/events.py`

Add optional fields:

- `schema_version = "decision_event_v1"`
- `event_type = "decision_event"`
- `bot_id`
- `family_id`
- `portfolio_id`
- `strategy_version`
- `config_version`
- `portfolio_config_version`
- `risk_config_version`
- `allocation_version`
- `strategy_registry_version`
- `deployment_id`
- `parameter_set_id`
- `code_sha`
- `trace_id`
- `bar_id`
- `decision_kind`
- `sequence`

Keep:

- `code`
- `ts`
- `symbol`
- `timeframe`
- `details`
- `strategy_id`
- `state_ref`
- `emitted_actions`

### 14.2 Fix Decision Normalization

File:

- `backtests/shared/parity/decision_capture.py`

Update `normalize_decision_event()` to include:

- `schema_version`;
- `event_type`;
- `strategy_id`;
- `family_id`;
- `portfolio_id`;
- lineage versions;
- `state_ref`;
- `emitted_actions`;
- `trace_id`;
- `bar_id`;
- `decision_kind`;
- normalized sorted `details`.

Do not drop fields that a replay comparison needs.

### 14.3 Emit Decision Events

Add a bounded decision writer:

```text
strategies/<family>/instrumentation/data/decisions/decisions_YYYY-MM-DD.jsonl
```

Emit or export decision events for:

- signal generated;
- filter passed;
- filter failed;
- entry intent created;
- entry intent suppressed;
- risk approved;
- risk scaled;
- risk denied;
- order submitted;
- order rejected;
- fill observed;
- stop adjusted;
- exit decision;
- flatten/halt decision.

The live/replay parity harness can still compare in-memory traces, but the
sidecar event stream must preserve decision evidence for the assistant.

## 15. Granular Implementation Sequence

### Phase 0: Baseline

Run from `_references/trading`:

```powershell
pytest tests/unit/test_ta_schema_compatibility.py
pytest strategies/stock/instrumentation/tests
pytest tests/unit/test_sidecar_watermarks.py
pytest tests/unit/test_capital_allocation.py
pytest tests/unit/test_stock_portfolio_rules.py
```

Record current failures if any. Do not start edits by changing strategy logic.

### Phase 1: Shared Lineage

Files to add:

- `libs/instrumentation/__init__.py`
- `libs/instrumentation/lineage.py`
- `libs/instrumentation/event_contract.py`
- `tests/unit/test_lineage_contract.py`

Acceptance:

- hashes are deterministic;
- secret redaction works;
- versions change when relevant config changes;
- versions do not change when key order changes;
- `LineageContext` can be built from `config/portfolio.yaml`,
  `config/strategies.yaml`, env, and family risk config;
- missing git SHA is handled fail-open.

### Phase 2: Thread Lineage Into Instrumentation Managers

Files to update:

- `strategies/stock/instrumentation/src/bootstrap.py`
- `strategies/momentum/instrumentation/src/bootstrap.py`
- `strategies/swing/instrumentation/src/bootstrap.py`
- stock/momentum `facade.py`
- swing `kit.py` and `hooks.py`

Changes:

- compute one `LineageContext` at manager startup;
- pass it into `TradeLogger`, `MissedOpportunityLogger`, `OrderLogger`,
  `DailySnapshotBuilder`, and facade/kit helpers;
- add helper `manager.lineage_payload(scope, event_type, schema_version)`;
- emit lineage warnings in heartbeat if required fields are missing.

Acceptance:

- existing strategy hooks still work without passing lineage explicitly;
- tests can construct loggers with no lineage for backward compatibility;
- manager startup writes deployment/config events in dev temp dirs.

### Phase 3: Event Metadata And Strategy Payloads

Files to update:

- each family `event_metadata.py`;
- each family `trade_logger.py`;
- each family `missed_opportunity.py`;
- each family `order_logger.py`;
- stock/momentum `filter_event_logger.py` and `filter_decision.py`;
- swing `filter_logger.py`;
- each family `indicator_logger.py`;
- each family `market_snapshot.py`;
- each family `daily_snapshot.py`.

Acceptance:

- trade exit payload contains the full common lineage set;
- missed opportunity payload contains the full common lineage set;
- order payload contains OMS lineage and trace IDs;
- current Trading Assistant alias tests still pass;
- event IDs remain stable for existing payload keys.

### Phase 4: Sidecar Contract

Files to update:

- each family `sidecar.py`;
- `tests/unit/test_sidecar_watermarks.py` or new sidecar contract tests.

Acceptance:

- new event directories are forwarded;
- sidecar envelopes include lineage;
- payload lineage remains inside the JSON payload;
- priority values match the target table;
- mutable-file watermark tests still pass.

### Phase 5: Portfolio Rule Event Enrichment

Files to update or add:

- `libs/oms/instrumentation/portfolio_rule_event.py`
- `libs/oms/risk/portfolio_rules.py`
- `libs/oms/services/factory.py`
- `tests/unit/test_stock_portfolio_rules.py`
- new `tests/unit/test_portfolio_rule_event_contract.py`

Acceptance:

- every rule pass/scale/block event preserves requested and approved sizing;
- rule events carry portfolio/risk/allocation/registry versions;
- old `rule_name`, `result`, and `details.reason` fields still exist;
- risk-denial JSONL events carry lineage and intent context;
- no portfolio rule behavior changes.

### Phase 6: Position, Portfolio, Allocation, And Family Snapshots

Files to add:

- `libs/oms/instrumentation/position_snapshot.py`
- `libs/oms/instrumentation/portfolio_snapshot.py`
- `libs/oms/instrumentation/allocation_snapshot.py`
- `libs/oms/instrumentation/family_snapshot.py`
- `libs/oms/instrumentation/exposure_snapshot.py`
- `tests/unit/test_snapshot_contracts.py`

Files to update:

- each family `bootstrap.py`;
- each family `daily_snapshot.py`;
- `libs/config/capital_allocation.py`, only if a helper is needed to emit
  serializable allocation records.

Acceptance:

- startup emits allocation and portfolio snapshots;
- fills trigger position, allocation, and portfolio snapshots;
- final family/portfolio daily reconciliation ties strategy daily files, trade
  files, OMS positions, allocation state, risk tables, and portfolio PnL;
- snapshots redact raw account IDs;
- sidecar forwards snapshots.

### Phase 7: Config Snapshot And Deployment Events

Files to update:

- stock/momentum `config_snapshot.py`;
- add swing `config_snapshot.py` or wire swing to the shared helper directly;
- each family `config_watcher.py`;
- each family `bootstrap.py`;
- `libs/instrumentation/lineage.py`.

Acceptance:

- startup emits `deployment` and `config_snapshot`;
- `parameter_change` includes before/after versions;
- hardcoded/dynamic family `PortfolioRulesConfig` values are included in
  `risk_config_version`;
- missing version fields are visible but do not stop trading.

### Phase 8: Decision Parity Contract

Files to update:

- `strategies/core/events.py`;
- `backtests/shared/parity/decision_capture.py`;
- live/replay parity normalizers as needed;
- `tests/unit/test_parity_normalizers.py`;
- `tests/unit/test_live_shadow_contract.py`;
- relevant integration parity fixtures.

Acceptance:

- normalized decision events retain strategy ID and lineage;
- emitted actions and state refs survive normalization;
- parity tests still compare deterministic payloads;
- portfolio rule and allocation gate decisions can be represented.

### Phase 9: End-To-End Synthetic Day

Add or extend a test that creates one synthetic day with:

- one accepted entry;
- one completed exit;
- one missed opportunity;
- one filter block;
- one portfolio rule scale;
- one risk denial;
- one order fill;
- one position snapshot;
- one portfolio snapshot;
- one allocation snapshot;
- one config snapshot;
- one deployment event;
- one approval-grade deployment metadata artifact;
- one heartbeat;
- one error event.

Acceptance:

- sidecar wraps every event;
- relay-required fields exist;
- lineage exists at payload and envelope levels;
- JSON payloads parse;
- no raw secrets or raw broker account numbers appear.

## 16. Tests To Add Or Strengthen

### 16.1 Existing Tests To Extend

Extend:

- `tests/unit/test_ta_schema_compatibility.py`
- `strategies/stock/instrumentation/tests/test_trading_assistant_contracts.py`
- `strategies/stock/instrumentation/tests/test_event_metadata.py`
- `tests/unit/test_sidecar_watermarks.py`
- `tests/unit/test_stock_portfolio_rules.py`
- `tests/unit/test_capital_allocation.py`
- `tests/unit/test_parity_normalizers.py`
- `tests/unit/test_live_shadow_contract.py`

### 16.2 New Tests

Add:

- `tests/unit/test_lineage_contract.py`
- `tests/unit/test_sidecar_envelope_lineage.py`
- `tests/unit/test_portfolio_rule_event_contract.py`
- `tests/unit/test_snapshot_contracts.py`
- `tests/unit/test_config_snapshot_contract.py`
- `tests/unit/test_decision_event_contract.py`
- `tests/integration/test_instrumentation_synthetic_day.py`

### 16.3 Required Assertions

Test these explicitly:

- trade and missed events include `strategy_version`, `config_version`, and
  `deployment_id`;
- portfolio/risk/allocation events include `portfolio_config_version`,
  `risk_config_version`, `allocation_version`, and
  `strategy_registry_version`;
- `parameter_set_id` exists while `param_set_id` remains available;
- sidecar envelope duplicates lineage;
- sidecar payload still contains lineage;
- portfolio rule event preserves requested versus approved sizing;
- portfolio rule event includes thresholds and state before/after;
- startup emits deployment, config, allocation, portfolio, and position
  snapshots;
- config watcher emits before/after versions;
- normalized decision events preserve strategy ID, state ref, emitted actions,
  and lineage;
- no event contains keys matching secret patterns;
- raw account IDs are replaced by `account_alias`;
- instrumentation errors are swallowed and logged.

## 17. Rollout Plan

Use a feature flag:

```text
INSTRUMENTATION_CONTRACT_VERSION=v2
```

Rollout order:

1. Add shared lineage code and tests.
2. Enable lineage on stock instrumentation in a temp/test data dir.
3. Enable sidecar envelope lineage for stock.
4. Port identical logger changes to momentum and swing.
5. Enrich portfolio rule events and risk denials.
6. Add snapshots.
7. Add config/deployment startup events.
8. Add decision parity event normalization.
9. Run synthetic-day test.
10. Run family-specific unit and parity tests.
11. Deploy to paper mode first.
12. Verify assistant ingestion before live mode.

Do not deploy portfolio rule event enrichment and strategy logger lineage as one
large untested change. The portfolio rule upgrade touches OMS/risk code and
should be verified independently from pure payload lineage.

## 18. Commands For Verification

From `_references/trading`:

```powershell
pytest tests/unit/test_lineage_contract.py
pytest tests/unit/test_ta_schema_compatibility.py
pytest strategies/stock/instrumentation/tests
pytest tests/unit/test_sidecar_watermarks.py
pytest tests/unit/test_sidecar_envelope_lineage.py
pytest tests/unit/test_portfolio_rule_event_contract.py
pytest tests/unit/test_snapshot_contracts.py
pytest tests/unit/test_config_snapshot_contract.py
pytest tests/unit/test_decision_event_contract.py
pytest tests/unit/test_capital_allocation.py
pytest tests/unit/test_stock_portfolio_rules.py
pytest tests/unit/test_parity_normalizers.py
pytest tests/unit/test_live_shadow_contract.py
pytest tests/integration/test_instrumentation_synthetic_day.py
```

Then run targeted family and parity suites:

```powershell
pytest tests/unit/test_momentum_portfolio_synergy_live_parity.py
pytest tests/unit/test_swing_portfolio_synergy_live_parity.py
pytest tests/integration/parity/test_live_shadow_families.py
pytest tests/integration/parity/test_parity_acceptance_gate.py
```

Run `parity_nightly` only after the strict gate is expected to pass in the
current branch:

```powershell
pytest tests/integration/parity -m parity_nightly
```

## 19. Definition Of Done For `_references/trading`

The repo is ready for daily/weekly diagnostics when:

- existing trade, missed, order, filter, indicator, market, error, heartbeat,
  and daily events still emit;
- sidecar forwarding remains idempotent and non-fatal;
- portfolio rule and risk-denial events carry enough context for diagnosis;
- bot daily snapshots still reconcile to local JSONL files;
- no instrumentation failure affects trading.

The repo is ready for monthly authoritative strategy validation when:

- at least 95 percent of monthly-critical `trade` and `missed_opportunity`
  events include `strategy_version`, `config_version`, and `deployment_id`;
- those events also include `code_sha`, `parameter_set_id`, `bar_id` where
  available, and `data_source_id`;
- startup emits `deployment` and `config_snapshot`;
- startup emits approval-grade `deployment_metadata.json` with live/VPS
  source-control and contract-hash evidence;
- lineage gaps are visible in heartbeats or errors;
- decision parity hooks can export normalized decision events.

The repo is ready for optimal portfolio-level validation when:

- portfolio rule events preserve requested versus approved sizing;
- portfolio/risk/allocation events include `portfolio_config_version`,
  `risk_config_version`, `allocation_version`, and
  `strategy_registry_version`;
- `position_snapshot`, `portfolio_snapshot`, `allocation_snapshot`, and
  closeout events are emitted for startup, fills, risk-control changes,
  reconciliation, and end-of-day closeout;
- portfolio snapshots reconcile with strategy-level files and OMS positions;
- portfolio structural changes can be replayed with allocation, heat-cap,
  drawdown-tier, symbol-collision, sector-cap, and coordination behavior using
  portfolio-rule and risk-decision events.

## 20. Non-Goals

Do not implement these as part of this instrumentation pass unless explicitly
requested:

- new trading rules;
- changed portfolio caps;
- changed allocation weights;
- automated assistant deployment or approval actions;
- curation inside the trading repo.
- monitoring-only analytics outside the lifecycle evidence listed above.

The README mentions a `DailyMetricsBuilder` and curated files, but this audit
did not find a trading-side implementation of that builder. The trading repo
should emit authoritative raw events and snapshots. The assistant can continue
owning curated daily artifacts unless architecture is intentionally changed.

## 21. High-Risk Mistakes To Avoid

- Do not change entry/exit/risk decisions while adding payload fields.
- Do not make OMS approval depend on JSONL writes.
- Do not replace existing sidecar behavior with a new relay client.
- Do not remove old aliases that assistant compatibility tests already expect.
- Do not hash only `portfolio.yaml` and call it the full risk config.
- Do not omit hardcoded or dynamically constructed `PortfolioRulesConfig`
  values from `risk_config_version`.
- Do not rely on envelope-only lineage; put lineage in payloads too.
- Do not log raw broker account IDs when `account_alias` is enough.
- Do not emit huge every-bar snapshots; bound sampling and payload size.
- Do not normalize portfolio rule events down to text reasons only.
- Do not drop `strategy_id`, `state_ref`, or `emitted_actions` from decision
  parity normalization.

## 22. Short Answer For Future Agents

If time is limited, implement in this order:

1. Shared `LineageContext` and config/version hashes.
2. Payload and sidecar lineage for existing trade, missed, order, heartbeat,
   daily, and error events.
3. Full `portfolio_rule_check` and `risk_denial` payloads.
4. Position, portfolio, and allocation snapshots tied to startup, fills,
   reconciliation, risk-control changes, and closeout.
5. Startup deployment/config snapshot events plus approval-grade
   `deployment_metadata.json`.
6. Decision parity event normalization.
7. Contract tests and synthetic-day test.

That order upgrades the current good strategy telemetry into monthly-useful
evidence first, then fixes the largest portfolio-level blind spot.
