# Instrumentation Gap Remediation

**Date**: 2026-04-13
**Scope**: 13 strategy engines across 3 families (swing, momentum, stock)
**Goal**: Close remaining instrumentation gaps so the Trading Assistant (TA) has full visibility across all strategies.

---

## Summary of Changes

### Phase 1: Entry Field Gaps (4 engines)

| Engine | Change | File |
|--------|--------|------|
| **ALCB** | Wire existing `_portfolio_state_snapshot()` into `kit.log_entry()` (was defined but not passed) | `strategies/stock/alcb/engine.py` ~L1487 |
| **IARIC** | Add `portfolio_state` dict (account_equity, open_positions, pending_entry_risk, base_risk_fraction, regime state, symbols_held) | `strategies/stock/iaric/engine.py` ~L1464 |
| **Downturn** | Add `portfolio_state` dict + wire `filter_decisions=self._entry_gate_decisions()`. Fix `concurrent_positions` from hardcoded 0 to actual value. | `strategies/momentum/downturn/engine.py` ~L1675 |
| **Overlay** | Full enrichment: `signal_factors` (ema_fast/slow/crossover), `sizing_inputs` (equity/deployed/available/allocation), `portfolio_state` (equity/deployed/overlay_positions/bullish_count), `filter_decisions=[]`. Exit enriched with pnl_pct, position_size, expected_exit_price. Added `ema_cache` dict to pass EMA values from signal loop to order loop. | `strategies/swing/overlay/engine.py` ~L366, ~L425 |

### Phase 2: US_ORB Full Trade Logging

| Change | File |
|--------|------|
| Add `log_entry()` after trade_recorder.record_entry with full field set (signal_factors, filter_decisions, sizing_inputs, portfolio_state). Reuses existing `_entry_signal_factors()`, `_entry_filter_decisions()`, `_portfolio_state_snapshot()` methods. | `strategies/stock/us_orb/engine.py` ~L1202 |
| Add `log_exit()` before `ctx.position = None` with mfe/mae R-values, pnl_r, fill_qty, expected_exit_price. Reuses existing MFE/MAE tracking. | `strategies/stock/us_orb/engine.py` ~L1335 |

### Phase 3: Stop Adjustment Logging

#### 3a. New `log_stop_adjustment()` method added to all 3 family facades

| Facade | File | Lines |
|--------|------|-------|
| Swing | `strategies/swing/instrumentation/src/kit.py` | ~L790-836 |
| Momentum | `strategies/momentum/instrumentation/src/facade.py` | ~L490-524 |
| Stock | `strategies/stock/instrumentation/src/facade.py` | ~L512-546 |

**Signature**:
```python
def log_stop_adjustment(
    self, trade_id: str, symbol: str,
    old_stop: float, new_stop: float,
    adjustment_type: str,  # trailing | breakeven | coordination_tighten | partial_trail | time_decay
    trigger: str,          # what caused it: atr_trail, mfe_threshold, coord_rule, etc.
    metadata: dict | None = None,
) -> None:
```

**Output**: Writes to `{data_dir}/stop_adjustments/{date}.jsonl` per strategy.

**Safety**: Fire-and-forget (`try/except Exception: pass`). Early return if `old_stop == new_stop`. Never crashes trading.

#### 3b. Wired into engines at stop modification points

| Engine | Instrumentation Points | Triggers | File |
|--------|:----------------------:|----------|------|
| **Helix** | 3 | helix_trail, coord_rule_1_be, add_on_be | `strategies/swing/akc_helix/engine.py` |
| **ATRSS** | 1 | atr_chandelier | `strategies/swing/atrss/engine.py` |
| **Breakout** | 2 | atr_trail, runner_4h_trail | `strategies/swing/breakout/engine.py` |
| **Keltner** | 2 | atr_mfe_trail (LONG + SHORT) | `strategies/swing/keltner/engine.py` |
| **NQDTC** | 7 callers | ratchet, be, chandelier, news_be | `strategies/momentum/nqdtc/engine.py` |
| **VDub** | 9 callers | overnight_trail, plus1r_be, free_profit_lock, close_mfe_ratchet, intraday_trail, gate_hold, shock_tighten | `strategies/momentum/vdub/engine.py` |
| **ALCB** | 2 | alcb_composite_trail, partial_be | `strategies/stock/alcb/engine.py` |
| **IARIC** | 3 | mfe_stage_trail, v2_partial_profit, overnight_tighten | `strategies/stock/iaric/engine.py` |
| **US_ORB** | 1 | orb_trail | `strategies/stock/us_orb/engine.py` |

**Skipped** (no stop modifications): BRS, Downturn, Helix_v40.

**Centralized pattern** (Helix, NQDTC, VDub): Modified `_update_stop()` to accept `adjustment_type`/`trigger`/`old_stop` params; logging inside the method.

**Inline pattern** (ATRSS, Breakout, Keltner, ALCB, IARIC, US_ORB): Logging at each stop modification point, capturing `old_stop` before assignment.

#### 3c. TA Pipeline Integration

These changes are in `_references/trading_assistant/` (the TA orchestrator reference codebase).

| Change | File | Details |
|--------|------|---------|
| **`build_stop_adjustment_analysis()`** method | `skills/build_daily_metrics.py` ~L821-861 | Aggregates stop adjustment events by type and trigger. Computes count, avg_tightening, max_tightening per adjustment_type. Sorts triggers by frequency. |
| **`import statistics`** added | `skills/build_daily_metrics.py` L11 | Required by `statistics.mean()` in the analysis method. |
| **`stop_adjustment_events`** param | `skills/build_daily_metrics.py` L877 | Added to `write_curated()` signature. |
| **Conditional write** | `skills/build_daily_metrics.py` L1020-1024 | Writes `stop_adjustment_analysis.json` if events present. |
| **Curated file registration** | `analysis/prompt_assembler.py` L38 | `"stop_adjustment_analysis.json"` added to `_CURATED_FILES` list. |
| **Handler event loading** | `orchestrator/handlers.py` L3667 | `"stop_adjustment": "stop_adjustment_events"` added to event type dict in `_rebuild_daily_curated_from_raw()`. |
| **Parameter change loading** | `orchestrator/handlers.py` L3666 | `"parameter_change": "parameter_change_events"` also added (was missing from dict). |

**Output schema** (`stop_adjustment_analysis.json`):
```json
{
  "bot_id": "k_momentum",
  "date": "2026-04-13",
  "total_adjustments": 15,
  "avg_tightening_distance": 0.000234,
  "by_adjustment_type": {
    "trailing": {"count": 12, "avg_tightening": 0.000198, "max_tightening": 0.000456},
    "breakeven": {"count": 3, "avg_tightening": 0.000378, "max_tightening": 0.000512}
  },
  "by_trigger": {
    "chandelier": 5,
    "ratchet": 4,
    "be": 3,
    "overnight_trail": 2,
    "news_be": 1
  }
}
```

### Phase 4: Coordinator Portfolio Events

| Coordinator | Change | File |
|-------------|--------|------|
| **Momentum** | Added `_emit_regime_event()` method + call from `apply_regime()`. Emits regime rules snapshot (directional caps, risk mult, max contracts, disabled strategies). | `strategies/momentum/coordinator.py` ~L340-375 |
| **Stock** | Same pattern, includes stock-specific fields (alcb_max_positions, iaric_pb_max_positions). | `strategies/stock/coordinator.py` ~L415-445 |

**Output**: Writes to `{data_dir}/coordination_events/{date}.jsonl` per strategy.

---

## Bugs Found and Fixed During Review

| # | Severity | Description | Files Fixed |
|---|----------|-------------|-------------|
| 1 | **CRITICAL** | Momentum/stock facades used `getattr(self._mgr, "data_dir", None)` but `_mgr` has no `data_dir` attribute. Stop adjustments were never written. Fixed to `self._data_dir`. | `strategies/momentum/instrumentation/src/facade.py`, `strategies/stock/instrumentation/src/facade.py` |
| 2 | **CRITICAL** | Coordinators used `getattr(instr, "data_dir", None)` but facade stores it as `_data_dir` (private). Regime events were never written. Fixed to `getattr(instr, "_data_dir", None)`. | `strategies/momentum/coordinator.py`, `strategies/stock/coordinator.py` |
| 3 | **CRITICAL** | `build_daily_metrics.py` called `statistics.mean()` without importing `statistics`. Would crash at runtime. Added `import statistics`. | `_references/trading_assistant/skills/build_daily_metrics.py` |
| 4 | **MEDIUM** | Handler `_rebuild_daily_curated_from_raw()` never loaded stop_adjustment events from raw JSONL. Added to event type dict. Also added missing `parameter_change` entry. | `_references/trading_assistant/orchestrator/handlers.py` |
| 5 | **LOW** | All 3 facades logged records even when `old_stop == new_stop`, creating zero-distance noise. Added early return guard. | All 3 facade files |

---

## Deferred (Low TA Value)

| Phase | Description | Effort |
|-------|-------------|--------|
| **5. Signal Evolution** | Add `signal_evolution` (ring buffer + builder) to Breakout, Keltner, BRS, ALCB, IARIC | ~4 hrs |
| **6. Exit Consistency** | Normalize `expected_exit_price`, `fill_qty` across 6 engines missing them | ~1 hr |

---

## Data Flow: Stop Adjustments End-to-End

```
Strategy Engine (VPS)
  _update_stop() or inline stop modification
    -> facade.log_stop_adjustment()
      -> {data_dir}/stop_adjustments/{YYYY-MM-DD}.jsonl

Sidecar/Relay (VPS -> Orchestrator)
  -> {raw_data_dir}/{date}/{bot_id}/stop_adjustment.jsonl

Handler._rebuild_daily_curated_from_raw()
  -> _load_raw_json_records(bot_raw, "stop_adjustment")
  -> DailyMetricsBuilder.write_curated(stop_adjustment_events=...)
    -> build_stop_adjustment_analysis()
      -> {curated_dir}/{date}/{bot_id}/stop_adjustment_analysis.json

DailyPromptAssembler.assemble()
  -> _load_structured_data() reads stop_adjustment_analysis.json
  -> Claude analyzes stop management patterns
```

**Note**: The relay sidecar must be configured to transfer `stop_adjustments/{date}.jsonl` files from each strategy's data_dir to the orchestrator's raw data directory as `stop_adjustment.jsonl`. This follows the same pattern as existing event types (filter_decisions, indicator_snapshots, etc.).

---

## Instrumentation Variable Names (Reference)

| Engine | Kit Variable | Family |
|--------|-------------|--------|
| ATRSS, Helix, Breakout, Keltner, BRS, Overlay | `self._kit` | swing |
| NQDTC, VDub, Downturn, Helix_v40 | `self._kit` | momentum |
| ALCB | `self._instr_kit` | stock |
| IARIC | `self._kit_cache` (lazy) | stock |
| US_ORB | `self._instrumentation` | stock |

## Modified Files (Complete List)

**Strategy engines** (Phase 1-3b):
- `strategies/stock/alcb/engine.py`
- `strategies/stock/iaric/engine.py`
- `strategies/stock/us_orb/engine.py`
- `strategies/momentum/downturn/engine.py`
- `strategies/momentum/nqdtc/engine.py`
- `strategies/momentum/vdub/engine.py`
- `strategies/swing/overlay/engine.py`
- `strategies/swing/akc_helix/engine.py`
- `strategies/swing/atrss/engine.py`
- `strategies/swing/breakout/engine.py`
- `strategies/swing/keltner/engine.py`

**Instrumentation facades** (Phase 3a):
- `strategies/swing/instrumentation/src/kit.py`
- `strategies/momentum/instrumentation/src/facade.py`
- `strategies/stock/instrumentation/src/facade.py`

**Coordinators** (Phase 4):
- `strategies/momentum/coordinator.py`
- `strategies/stock/coordinator.py`

**TA pipeline** (Phase 3c):
- `_references/trading_assistant/skills/build_daily_metrics.py`
- `_references/trading_assistant/analysis/prompt_assembler.py`
- `_references/trading_assistant/orchestrator/handlers.py`

---

## Trading Assistant Changes (Apply to TA Repo)

The `_references/trading_assistant/` directory is git-ignored in the trading monorepo. All changes below must be applied manually to the actual trading assistant repository. They fall into two categories: **Phase 3c** (stop adjustment pipeline, already documented above) and **Phase 5: Runtime Audit Identity Alignment** (new).

### Phase 5: Runtime Audit — Identity Alignment & Strategy Resolution

These changes fix the assistant's ability to match incoming instrumentation events to the correct strategy profiles and generate per-strategy suggestions.

#### 5a. Strategy Profiles Registry (`data/strategy_profiles.yaml`)

**Problem**: The registry used `DOWNTURN` as the key for the Downturn strategy, but the runtime instrumentation emits `DownturnDominator_v1` as the strategy_id. `strategies_for_bot()` uses exact `==` matching, so DOWNTURN never matched any incoming events.

**Change**: Rename the registry key from `DOWNTURN` to `DownturnDominator_v1`.

```yaml
# BEFORE (line ~252)
  DOWNTURN:
    display_name: "Downturn Multi-Engine Bear"
    bot_id: momentum_nq_01
    ...

# AFTER
  DownturnDominator_v1:
    display_name: "Downturn Multi-Engine Bear"
    bot_id: momentum_nq_01
    ...
```

**Context**: The momentum family's 4 strategies now use these registry keys (matching the runtime's `STRATEGY_ID` constants):
- `AKC_Helix_v40` — bot_id: `momentum_nq_01`
- `NQDTC_v2.1` — bot_id: `momentum_nq_01`
- `VdubusNQ_v4` — bot_id: `momentum_nq_01`
- `DownturnDominator_v1` — bot_id: `momentum_nq_01` (was `DOWNTURN`)

**Also verify**: All `bot_id` values in strategy_profiles.yaml match the `_BOT_ID` constants in each family's instrumentation bootstrap:
- Swing strategies: `bot_id: swing_multi_01` — matches `strategies/swing/instrumentation/src/bootstrap.py` `_BOT_ID`
- Momentum strategies: `bot_id: momentum_nq_01` — matches `strategies/momentum/instrumentation/src/bootstrap.py` `_BOT_ID` (was `momentum_trader`, fixed in runtime audit)
- Stock strategies: `bot_id: stock_trader` — matches `strategies/stock/instrumentation/src/bootstrap.py` `_BOT_ID`

**Cross-reference with runtime**: The stock bootstrap's `_STRATEGY_ID_MAP` now passes through original IDs unchanged (`IARIC_v1` → `IARIC_v1`, `US_ORB_v1` → `US_ORB_v1`, `ALCB_v1` → `ALCB_v1`). Previously it remapped to lowercase (`iaric`, `us_orb`, `alcb`), which broke registry matching.

#### 5b. Strategy Engine — `strategy_id` Parameter (`analysis/strategy_engine.py`)

**Problem**: `_resolve_strategy_id(bot_id)` at line 163-168 returns the strategy_id only when exactly 1 strategy exists for a bot_id. Since ALL current bot_ids have multiple strategies (swing=6, momentum=4, stock=3), this function returns `""` for every bot_id. Any `StrategySuggestion` generated by analyzer methods had an empty `strategy_id`, breaking per-strategy suggestion tracking and outcome measurement.

**Change**: Added `strategy_id: str = ""` parameter to 5 detector methods so callers can pass the strategy_id explicitly (bypassing `_resolve_strategy_id` for multi-strategy bots):

```python
# All 5 methods now accept an explicit strategy_id override:

def detect_regime_config_effectiveness(
    self, bot_id: str, macro_regime: str, ...,
    strategy_id: str = "",          # NEW
) -> list[StrategySuggestion]:
    strategy_id = strategy_id or self._resolve_strategy_id(bot_id)
    ...

def detect_stress_entry_pattern(
    self, bot_id: str, trades_by_stress: dict, ...,
    strategy_id: str = "",          # NEW
) -> list[StrategySuggestion]:
    strategy_id = strategy_id or self._resolve_strategy_id(bot_id)
    ...

def detect_alpha_decay(
    self, bot_id: str, ...,
    strategy_id: str = "",          # ALREADY HAD IT
) -> list[StrategySuggestion]:
    sid = strategy_id or self._resolve_strategy_id(bot_id)
    ...

def detect_exit_timing_issues(
    self, bot_id: str, ...,
    strategy_id: str = "",          # ALREADY HAD IT
) -> list[StrategySuggestion]:
    sid = strategy_id or self._resolve_strategy_id(bot_id)
    ...

def detect_time_of_day_patterns(
    self, bot_id: str, ...,
    strategy_id: str = "",          # ALREADY HAD IT
) -> list[StrategySuggestion]:
    sid = strategy_id or self._resolve_strategy_id(bot_id)
    ...
```

**Callers must be updated**: All call sites for `detect_regime_config_effectiveness` and `detect_stress_entry_pattern` in the daily analysis skill and weekly summary skill should pass `strategy_id=<current_strategy_id>` when iterating per-strategy data.

**Known limitation**: `_resolve_strategy_id()` itself is NOT fixed — it still returns `""` for multi-strategy bots. This is acceptable because (a) the explicit `strategy_id` parameter bypasses it, and (b) fixing the resolver to handle multi-strategy bots would require changing the return type and all callers. The parameter approach is safer and backward-compatible.

#### 5c. Evidence Pipeline Prerequisites

These changes were made in the **trading monorepo** (not the TA repo) but directly affect what data the assistant receives:

| Runtime Change | Effect on Assistant |
|---------------|-------------------|
| Momentum `_BOT_ID` changed from `"momentum_trader"` to `"momentum_nq_01"` | Events now match `strategy_profiles.yaml` bot_id → `strategies_for_bot("momentum_nq_01")` returns 4 strategies instead of 0 |
| Stock `_STRATEGY_ID_MAP` now passes through original IDs | `strategy_id` in events matches registry keys (`IARIC_v1` not `iaric`) → archetype lookups and suggestion tracking work |
| All 3 sidecars now forward `coordination_events/` directory | Regime→rules events reach the assistant for daily analysis context |
| Relay URL and port fixed across all configs | Sidecar→relay connection actually works → events arrive at the orchestrator |
| Bootstrap config paths are `__file__`-relative | YAML configs are loaded correctly in Docker → correct `bot_id`, `data_dir`, `relay_url` values |

#### 5d. Coordination Events — New Event Type for TA Pipeline

The momentum and stock coordinators now emit `regime_rules_change` events to `{data_dir}/coordination_events/{date}.jsonl` when `apply_regime()` runs. All 3 sidecars now include `"coordination_events": "coordinator_action"` in their `_DIR_TO_EVENT_TYPE` mapping, so these events are forwarded to the relay.

**TA handler requirement**: The handler's `_rebuild_daily_curated_from_raw()` event type dict should include:
```python
"coordinator_action": "coordinator_action_events"
```
This enables `build_daily_metrics.py` to load and analyze regime change events. The prompt assembler already loads `coordinator_impact.json` from curated files.

**Event schema** (`coordination_events/{date}.jsonl`):
```json
{
  "timestamp": "2026-04-13T14:30:00+00:00",
  "event_type": "regime_rules_change",
  "family": "momentum",
  "regime": "Defensive",
  "prev_regime": "Recovery",
  "rules_applied": {
    "directional_cap_R": 8.0,
    "regime_unit_risk_mult": 0.5,
    "max_contracts_per_strategy": 1,
    "nqdtc_oppose_size_mult": 0.5,
    "disabled_strategies": ["AKC_Helix_v40"]
  }
}
```

Stock variant includes `alcb_max_positions` and `iaric_pb_max_positions` in `rules_applied`.

---

### Phase 6: Pipeline Integrity Audit — Brain Event Routing & Sidecar Forwarding

**Date**: 2026-04-14
**Context**: End-to-end audit of the instrumentation pipeline from engine → sidecar → relay → brain → worker → handlers → daily metrics → prompt assembler. Found multiple independent breaks where events were forwarded by sidecars but silently dropped by the brain or worker.

#### 6a. Sidecar `_DIR_TO_EVENT_TYPE` — Add `stop_adjustments` Directory Scanning

**Problem**: Phase 3 added `log_stop_adjustment()` to all engines, writing to `stop_adjustments/*.jsonl`. But no sidecar scanned that directory — events accumulated on disk and were never forwarded to the relay.

**Files changed** (3 sidecars):

| Sidecar | File | Dict Addition | Priority Addition |
|---------|------|---------------|-------------------|
| Swing | `strategies/swing/instrumentation/src/sidecar.py` | `"stop_adjustments": "stop_adjustment"` in `_DIR_TO_EVENT_TYPE` | `"stop_adjustment": 3` in `_PRIORITY_MAP` |
| Momentum | `strategies/momentum/instrumentation/src/sidecar.py` | Same in `_DIR_TO_EVENT_TYPE` | `"stop_adjustment": 3` in `_EVENT_PRIORITY` |
| Stock | `strategies/stock/instrumentation/src/sidecar.py` | Same in `_DIR_TO_EVENT_TYPE` | `"stop_adjustment": 3` in `_EVENT_PRIORITY` |

**Why priority 3**: Same as `trade`, `order`, `portfolio_rule_check`, `parameter_change` — data-bearing events that feed daily analysis but aren't urgent enough for priority 1-2 (errors, exit trades).

#### 6b. Brain `_handlers` — Add Missing Event Type Handlers

**Problem**: Several event types forwarded by sidecars had no matching handler in `OrchestratorBrain._handlers`. Events fell through to `_handle_unknown` → `ActionType.LOG_UNKNOWN` → silently discarded.

**File**: `_references/trading_assistant/orchestrator/orchestrator_brain.py`

**New handlers added**:

```python
def _handle_stop_adjustment(self, event_id: str, bot_id: str, event: dict) -> list[Action]:
    return self._queue_for_daily_event(event_id, bot_id, event, "stop_adjustment")

def _handle_trade_entry(self, event_id: str, bot_id: str, event: dict) -> list[Action]:
    return self._queue_for_daily_event(event_id, bot_id, event, "trade_entry")
```

**`_handlers` dict additions**:
```python
"stop_adjustment": _handle_stop_adjustment,
"trade_entry": _handle_trade_entry,
```

**Context**: `trade_entry` events are produced by all 3 sidecars' `_forward_event_type()` method, which renames non-exit trade events from `"trade"` to `"trade_entry"`. Entry-specific fields (`entry_fill_details`, `spread_at_entry`, entry signal metadata) are only in these events. Exit events contain most entry data, so this is lower severity but still a data gap.

#### 6c. Brain — Fix `portfolio_rule_check` Triple Naming Mismatch

**Problem**: Three independent breaks in the `portfolio_rule_check` data path:

1. **Sidecar → Brain mismatch**: Sidecars send `event_type: "portfolio_rule_check"` but the brain `_handlers` dict had key `"portfolio_rule"` → handler never matched → `_handle_unknown` → `LOG_UNKNOWN`.

2. **Bare handler**: Even if the key matched, `_handle_portfolio_rule` returned a bare `Action(type=QUEUE_FOR_DAILY, event_id=..., bot_id=...)` without `details` → worker's `_persist_raw_event` checks `details.get("event_type", "")` → gets `""` → `return` (silently skips).

3. **handlers.py loading mismatch**: `handlers.py` loaded `_load_raw_json_records(bot_raw, "portfolio_rule")` but the brain (if it had worked) would persist as `portfolio_rule_check.jsonl` → filename mismatch → no data loaded → `rule_blocks_summary.json` always empty.

**Fixes applied**:

**File 1**: `orchestrator/orchestrator_brain.py`
```python
# _handlers dict key: changed "portfolio_rule" → "portfolio_rule_check"
"portfolio_rule_check": _handle_portfolio_rule,

# Handler body: changed from bare Action to _queue_for_daily_event
def _handle_portfolio_rule(self, event_id: str, bot_id: str, event: dict) -> list[Action]:
    return self._queue_for_daily_event(event_id, bot_id, event, "portfolio_rule_check")
```

**File 2**: `orchestrator/handlers.py` (line 3843)
```python
# BEFORE
all_rule_events.extend(self._load_raw_json_records(bot_raw, "portfolio_rule"))

# AFTER
all_rule_events.extend(self._load_raw_json_records(bot_raw, "portfolio_rule_check"))
```

**Downstream verification**: `build_portfolio_rules_summary()` in `build_daily_metrics.py` already filters by `e.get("event_type") == "portfolio_rule_check"` — no change needed there.

#### 6d. Brain — Fix Bare `QUEUE_FOR_DAILY` Handlers (Silent Data Loss)

**Problem**: Four handlers returned bare `Action(type=QUEUE_FOR_DAILY)` without a `details` dict. The worker's `_persist_raw_event()` pattern:
```python
def _persist_raw_event(self, action: Action) -> None:
    details = action.details or {}
    event_type = details.get("event_type", "")
    if not event_type:
        return  # <-- silently drops the event
```

All four events were silently lost.

**File**: `orchestrator/orchestrator_brain.py`

**Handlers fixed** (all changed from bare Action to `_queue_for_daily_event`):

```python
# BEFORE (all four were identical bare Actions)
def _handle_post_exit(self, event_id, bot_id, event):
    return [Action(type=ActionType.QUEUE_FOR_DAILY, event_id=event_id, bot_id=bot_id)]

# AFTER (all four now use the helper that populates details)
def _handle_post_exit(self, event_id: str, bot_id: str, event: dict) -> list[Action]:
    return self._queue_for_daily_event(event_id, bot_id, event, "post_exit")

def _handle_market_snapshot(self, event_id: str, bot_id: str, event: dict) -> list[Action]:
    return self._queue_for_daily_event(event_id, bot_id, event, "market_snapshot")

def _handle_exit_movement(self, event_id: str, bot_id: str, event: dict) -> list[Action]:
    return self._queue_for_daily_event(event_id, bot_id, event, "exit_movement")

def _handle_stop_adjustment(self, event_id: str, bot_id: str, event: dict) -> list[Action]:
    return self._queue_for_daily_event(event_id, bot_id, event, "stop_adjustment")
```

**Impact of each**:
| Handler | Feeds | Prompt Assembler File |
|---------|-------|----------------------|
| `post_exit` | `exit_efficiency.json` — post-exit price movement analysis | `prompt_assembler.py` line 25 |
| `market_snapshot` | `market_conditions.json` — daily market context | `prompt_assembler.py` line 32 |
| `exit_movement` | Raw data preserved for future analysis | Not yet in curated files |
| `stop_adjustment` | `stop_adjustment_analysis.json` — stop management patterns | `prompt_assembler.py` line 40 |

#### 6e. Brain — Fix `_handle_error` Bare Actions (Same Pattern)

**Problem**: Discovered during review that `_handle_error` had 3 bare Action branches — the exact same silent-drop pattern fixed in 6d. Suppressed HIGH errors, MEDIUM errors, and LOW errors all vanished in `_persist_raw_event`.

**File**: `orchestrator/orchestrator_brain.py`

**Fixes**:

```python
# BEFORE: suppressed HIGH errors (line 162)
if suppressed:
    return [Action(type=ActionType.QUEUE_FOR_DAILY, event_id=event_id, bot_id=bot_id)]

# AFTER:
if suppressed:
    return self._queue_for_daily_event(event_id, bot_id, event, "error")


# BEFORE: LOW severity errors (line 173)
elif severity == "LOW":
    return [Action(type=ActionType.QUEUE_FOR_WEEKLY, event_id=event_id, bot_id=bot_id)]

# AFTER: (QUEUE_FOR_WEEKLY has no _queue_for_weekly_event helper, so inline details)
elif severity == "LOW":
    return [Action(
        type=ActionType.QUEUE_FOR_WEEKLY,
        event_id=event_id,
        bot_id=bot_id,
        details={
            "event_type": "error",
            "payload": self._extract_persistable_payload(event),
            "exchange_timestamp": event.get("exchange_timestamp"),
        },
    )]


# BEFORE: MEDIUM/unrecognized severity (line 175)
else:  # MEDIUM or unrecognized
    return [Action(type=ActionType.QUEUE_FOR_DAILY, event_id=event_id, bot_id=bot_id)]

# AFTER:
else:  # MEDIUM or unrecognized
    return self._queue_for_daily_event(event_id, bot_id, event, "error")
```

**Note**: CRITICAL and HIGH (non-suppressed) branches were already correct — they use `ALERT_IMMEDIATE`/`SPAWN_TRIAGE` with populated `details`.

#### 6f. Swing Coordinator — Add `_emit_regime_event()`

**Problem**: Swing (6 strategies, largest family) never emitted regime change events to `coordination_events/`. Momentum coordinator and stock coordinator both already had `_emit_regime_event()`. Swing's `apply_regime()` applied regime changes to portfolio rules and overlay weights but never wrote an event.

**Important design difference**: Swing uses a SHARED `InstrumentationContext` with ONE `data_dir` (stored at `self._instrumentation_ctx.data_dir`, type=`str`). Momentum/stock iterate over per-strategy `InstrumentationManager` instances accessing `_config["data_dir"]`. The swing implementation must use the single shared data_dir.

**File**: `strategies/swing/coordinator.py`

**Method added** (after `apply_regime`, ~line 611):
```python
def _emit_regime_event(self, payload: dict) -> None:
    """Write a regime->rules event to the shared data_dir for TA pipeline."""
    ctx = getattr(self, "_instrumentation_ctx", None)
    if ctx is None:
        return
    data_dir = getattr(ctx, "data_dir", None)
    if not data_dir:
        return
    now = datetime.now(timezone.utc)
    record = {"timestamp": now.isoformat(), "event_type": "regime_rules_change", **payload}
    try:
        out_dir = Path(data_dir) / "coordination_events"
        out_dir.mkdir(parents=True, exist_ok=True)
        date_str = now.strftime("%Y-%m-%d")
        with open(out_dir / f"{date_str}.jsonl", "a") as f:
            f.write(json.dumps(record, default=str) + "\n")
    except Exception:
        logger.debug("Failed to emit regime event", exc_info=True)
```

**Call site** (end of `apply_regime()`):
```python
self._emit_regime_event({
    "family": "swing",
    "regime": str(ctx.regime),
    "prev_regime": str(prev_regime) if prev_regime else None,
    "rules_applied": {
        "directional_cap_R": self._portfolio_checker._cfg.directional_cap_R if self._portfolio_checker else None,
        "regime_unit_risk_mult": self._portfolio_checker._cfg.regime_unit_risk_mult if self._portfolio_checker else None,
        "overlay_weights": dict(OVERLAY_WEIGHTS[regime]),
    },
})
```

**Event schema** (`coordination_events/{date}.jsonl`):
```json
{
  "timestamp": "2026-04-14T14:30:00+00:00",
  "event_type": "regime_rules_change",
  "family": "swing",
  "regime": "Trending",
  "prev_regime": "Range",
  "rules_applied": {
    "directional_cap_R": 8.0,
    "regime_unit_risk_mult": 1.0,
    "overlay_weights": {"QQQ": 0.6, "GLD": 0.4}
  }
}
```

---

## Bugs Found and Fixed During Phase 6 Review

| # | Severity | Description | Fix |
|---|----------|-------------|-----|
| 6 | **CRITICAL** | `_handle_error` had 3 bare Action branches (suppressed HIGH, LOW, MEDIUM). Error events silently dropped by `_persist_raw_event`. Not in original audit plan. | Populated `details` with `event_type: "error"` on all 3 branches |
| 7 | **CRITICAL** | `portfolio_rule_check` triple mismatch: sidecar sends `portfolio_rule_check`, brain key was `portfolio_rule`, handlers.py loaded `portfolio_rule`. 3 independent breaks. | Fixed brain key, handler body, and handlers.py load call |
| 8 | **HIGH** | `_handle_post_exit`, `_handle_market_snapshot`, `_handle_exit_movement` returned bare Actions. Events silently dropped. | Changed to `_queue_for_daily_event` |
| 9 | **HIGH** | No `stop_adjustment` or `trade_entry` handler in brain. Events fell to `_handle_unknown` → discarded. | Added handlers + `_handlers` dict entries |
| 10 | **HIGH** | No sidecar scanned `stop_adjustments/` directory despite 15 engine call sites writing to it. | Added to `_DIR_TO_EVENT_TYPE` in all 3 sidecars |
| 11 | **MEDIUM** | Swing coordinator never emitted regime events (momentum/stock did). | Added `_emit_regime_event()` using shared `_instrumentation_ctx.data_dir` |
| 12 | **LOW** | Swing `_emit_regime_event` silently swallowed exceptions with bare `pass`. | Changed to `logger.debug(...)` for observability |

---

## Data Flow: Full Pipeline After Phase 6

```
Strategy Engine (VPS)
  stop modification / entry / exit / regime change / portfolio rule check
    -> facade.log_*() or coordinator._emit_regime_event()
      -> {data_dir}/{event_dir}/{YYYY-MM-DD}.jsonl

Sidecar (VPS, background thread)
  _DIR_TO_EVENT_TYPE maps directory names to canonical event types:
    stop_adjustments/ -> "stop_adjustment"
    trades/           -> "trade" (or "trade_entry" via _forward_event_type)
    portfolio_rules/  -> "portfolio_rule_check"
    post_exit/        -> "post_exit"
    snapshots/        -> "market_snapshot"
    coordination_events/ -> "coordinator_action"
  -> HMAC-signed HTTP POST to relay /events endpoint

Relay (VPS, SQLite buffer)
  -> EventStore.insert() with priority indexing
  -> GET /events?bot_id=... (polled by worker)

Brain (OrchestratorBrain.decide())
  _handlers dict routes event_type to handler method:
    "stop_adjustment"      -> _handle_stop_adjustment    -> QUEUE_FOR_DAILY
    "trade_entry"          -> _handle_trade_entry         -> QUEUE_FOR_DAILY
    "portfolio_rule_check" -> _handle_portfolio_rule      -> QUEUE_FOR_DAILY
    "post_exit"            -> _handle_post_exit           -> QUEUE_FOR_DAILY
    "market_snapshot"      -> _handle_market_snapshot     -> QUEUE_FOR_DAILY
    "exit_movement"        -> _handle_exit_movement       -> QUEUE_FOR_DAILY
    "error" (suppressed)   -> _handle_error               -> QUEUE_FOR_DAILY
    "error" (LOW)          -> _handle_error               -> QUEUE_FOR_WEEKLY
  All return Action with populated details.event_type

Worker (_persist_raw_event)
  details.get("event_type") -> filename
  -> {raw_data_dir}/{date}/{bot_id}/{event_type}.jsonl

Handler (_rebuild_daily_curated_from_raw)
  _load_raw_json_records(bot_raw, "stop_adjustment")     -> stop_adjustment_events
  _load_raw_json_records(bot_raw, "portfolio_rule_check") -> all_rule_events
  _load_raw_json_records(bot_raw, "post_exit")            -> post_exit_events
  -> DailyMetricsBuilder.write_curated(**kwargs)

DailyMetricsBuilder
  build_stop_adjustment_analysis()  -> stop_adjustment_analysis.json
  build_portfolio_rules_summary()   -> rule_blocks_summary.json
  post_exit merge into trades       -> exit_efficiency.json

DailyPromptAssembler.assemble()
  _CURATED_FILES includes all output JSONs
  -> Claude analyzes full instrumentation data
```

---

## Complete TA Repo Change List

All files in the trading assistant repository that need changes:

| File | Changes | Source Phase |
|------|---------|-------------|
| `data/strategy_profiles.yaml` | Rename `DOWNTURN` → `DownturnDominator_v1` | Phase 5a |
| `analysis/strategy_engine.py` | Add `strategy_id=""` param to `detect_regime_config_effectiveness` and `detect_stress_entry_pattern` | Phase 5b |
| `skills/build_daily_metrics.py` | Add `build_stop_adjustment_analysis()`, `import statistics`, wire into `write_curated()` | Phase 3c |
| `analysis/prompt_assembler.py` | Add `"stop_adjustment_analysis.json"` to `_CURATED_FILES` | Phase 3c |
| `orchestrator/handlers.py` | Add `"stop_adjustment": "stop_adjustment_events"` and `"parameter_change": "parameter_change_events"` to event type dict in `_rebuild_daily_curated_from_raw()` | Phase 3c |
| `orchestrator/handlers.py` | Add `"coordinator_action": "coordinator_action_events"` to event type dict (enables regime event loading) | Phase 5d |
| `orchestrator/handlers.py` | Change `_load_raw_json_records(bot_raw, "portfolio_rule")` → `"portfolio_rule_check"` | Phase 6c |
| `orchestrator/orchestrator_brain.py` | Add `_handle_stop_adjustment` and `_handle_trade_entry` handlers + `_handlers` dict entries | Phase 6b |
| `orchestrator/orchestrator_brain.py` | Fix `_handlers` key `"portfolio_rule"` → `"portfolio_rule_check"` | Phase 6c |
| `orchestrator/orchestrator_brain.py` | Fix `_handle_portfolio_rule`, `_handle_post_exit`, `_handle_market_snapshot`, `_handle_exit_movement` from bare Actions to `_queue_for_daily_event()` | Phase 6c, 6d |
| `orchestrator/orchestrator_brain.py` | Fix `_handle_error` bare Actions for suppressed HIGH, MEDIUM, LOW severity | Phase 6e |
