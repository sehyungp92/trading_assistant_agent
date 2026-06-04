# Phase 2: Autonomous System Enhancement — Implementation Plan

_From advisory learning to active learning: adaptive thresholds, enriched events, A/B testing, deployment monitoring._

## Context

Phase 1 (complete, 1838 tests) delivers: **Suggestion → Backtest → Human Approval (Telegram) → PR Created**. All components are production-ready and feature-flagged behind `AUTONOMOUS_ENABLED`.

Phase 2 addresses the four remaining gaps from `docs/autonomous-system-assessment.md`:
- **2A:** Strategy engine thresholds are hardcoded — they should auto-tune from outcome data
- **2B:** Missing event types (IndicatorSnapshot, OrderBookContext, FilterDecisionEvent) limit analysis depth
- **2C:** Bot-side A/B infrastructure exists but the orchestrator has no experiment lifecycle management
- **2D:** No post-merge monitoring — PRs are created but deployment success/failure is untracked

## Design Decisions

1. **Percentile-based threshold learning** (2A) — no new dependencies (no scikit-learn), transparent, degrades to defaults with <10 samples. Logistic regression can be swapped in later by replacing `_compute_optimal_threshold`.
2. **Welch's t-test for experiments** (2C) — matches momentum_trader's existing `ExperimentAnalysis`, implemented from `math`/`statistics` (no scipy).
3. **Read-only deployment monitoring** (2D) — orchestrator monitors via `gh pr view` and curated data, never SSH/deploys to bots. Rollback = reverse PR.
4. **Feature-flagged per sub-phase** — `ADAPTIVE_THRESHOLDS_ENABLED`, `AB_TESTING_ENABLED`, `DEPLOYMENT_MONITORING_ENABLED`. Enriched events (2B) are additive, no flag needed.
5. **JSONL storage** for all new state — consistent with SuggestionTracker, ForecastTracker, HypothesisLibrary patterns.

---

## Phase 2A: Adaptive Strategy Engine

**Feature flag:** `ADAPTIVE_THRESHOLDS_ENABLED=false`
**Goal:** Strategy engine thresholds auto-tune from suggestion outcome data.

### Task 0: Detection Context Schema (~6 tests)

**New file:** `schemas/detection_context.py`
**Test:** `tests/test_detection_context.py`

Models:
- `DetectionContext` — `detector_name`, `bot_id`, `threshold_name`, `threshold_value`, `observed_value`, `margin` (computed), `detected_at`
- `ThresholdRecord` — `detector_name`, `bot_id`, `threshold_name`, `default_value`, `learned_value | None`, `sample_count`, `confidence` (0-1), `last_updated`
- `ThresholdProfile` — `bot_id`, `thresholds: dict[str, ThresholdRecord]` (keyed by `{detector}:{threshold}`), `total_outcomes_used`

Tests: margin computation, learned vs default fallback, serialization round-trip, confidence cap, validation

---

### Task 1: Detection Context Recording (~8 tests)

**Modified:** `schemas/strategy_suggestions.py` (add `detection_context: DetectionContext | None = None` to `StrategySuggestion`)
**Modified:** `analysis/strategy_engine.py` (populate `detection_context` on every suggestion from all 12 detectors)
**Test:** `tests/test_detection_context_recording.py`
**Depends on:** Task 0

Detector → context mapping:
| Detector | `detector_name` | `threshold_name` |
|----------|-----------------|-------------------|
| `analyze_parameters` | `tight_stop` | `tight_stop_ratio` |
| `analyze_filters` | `filter_cost` | `filter_cost_threshold` |
| `analyze_regime_fit` | `regime_loss` | `regime_min_weeks` |
| `detect_alpha_decay` | `alpha_decay` | `decay_threshold` |
| `detect_signal_decay` | `signal_decay` | `decay_threshold` |
| `detect_exit_timing_issues` | `exit_timing` | `efficiency_threshold` |
| `detect_correlation_breakdown` | `correlation` | `threshold` |
| `detect_time_of_day_patterns` | `time_of_day` | `loss_threshold` |
| `detect_drawdown_patterns` | `drawdown_concentration` | `concentration_threshold` |
| `detect_position_sizing_issues` | `position_sizing` | `loss_win_ratio_threshold` |
| `detect_component_signal_decay` | `component_signal_decay` | `stability_threshold` |
| `detect_filter_interactions` | `filter_interactions` | `redundancy_threshold` |

Tests: each detector populates context, backward compat, parametrized coverage for all 12

---

### Task 2: Threshold Learner (~14 tests)

**New file:** `skills/threshold_learner.py`
**Test:** `tests/test_threshold_learner.py`
**Depends on:** Task 0, Task 1

```python
class ThresholdLearner:
    def __init__(self, findings_dir: Path, min_samples: int = 10): ...
    def learn_thresholds(self) -> ThresholdProfile: ...
    def get_threshold(self, detector_name, threshold_name, bot_id, default) -> float: ...
    def _load_detection_outcomes(self) -> list[tuple[DetectionContext, bool]]: ...
    def _compute_optimal_threshold(self, observations, default) -> tuple[float, float]: ...
```

Algorithm:
1. Join `suggestions.jsonl` (with `detection_context`) to `outcomes.jsonl` (positive/negative)
2. Group by `(detector_name, bot_id, threshold_name)`
3. For groups with >= `min_samples`: try each observed_value as candidate threshold, select max F1
4. Confidence = `min(1.0, sample_count / 30)`
5. Persist to `learned_thresholds.jsonl`

Tests: empty data → defaults, below min_samples → defaults, simple separation case, per-bot specialization, JSONL round-trip, F1 ties → conservative

---

### Task 3: Adaptive Strategy Engine Integration (~10 tests)

**Modified:** `analysis/strategy_engine.py`
**Test:** `tests/test_adaptive_strategy_engine.py`
**Depends on:** Task 2

Add `threshold_learner: ThresholdLearner | None = None` to `StrategyEngine.__init__`. Add `_get_threshold(detector_name, threshold_name, bot_id, default)` that delegates to learner or returns default.

Each detector calls `self._get_threshold(...)` instead of using the hardcoded constructor value directly.

Tests: without learner → defaults (backward compat), with learner → uses learned values, mixed (some detectors learned, some default), parametrized over all 12 detectors

---

### Task 4: Threshold Learning Wiring (~8 tests)

**Modified:** `orchestrator/config.py`, `orchestrator/app.py`, `orchestrator/scheduler.py`, `analysis/context_builder.py`, `orchestrator/handlers.py`
**Test:** `tests/test_adaptive_threshold_wiring.py`
**Depends on:** Tasks 0-3

- `config.py`: add `adaptive_thresholds_enabled: bool = False`
- `app.py`: create `ThresholdLearner` when enabled, pass to weekly handler's `StrategyEngine`
- `scheduler.py`: schedule learning job Sunday 09:30 UTC (after memory consolidation, before outcome measurement)
- `context_builder.py`: add `load_threshold_profile()`, include in `base_package()` data
- `handlers.py`: weekly handler passes `threshold_learner` to `StrategyEngine`

Tests: flag off → no learner, flag on → wired, scheduler job registered, context_builder loads profile, runs without error on empty data

---

### Task 5: Phase 2A Integration Test (~6 tests)

**New file:** `tests/test_adaptive_integration.py`
**Depends on:** Tasks 0-4

Scenarios: full loop (suggestion → outcome → learned threshold → next engine run uses it), insufficient data → defaults, per-bot specialization, backward compat with flag off, old suggestions without detection_context skipped gracefully, threshold drift notification

---

## Phase 2B: Bot-Side Instrumentation Enrichment

**No feature flag needed** — new event types are additive and backward compatible.

### Task 6: Enriched Event Schemas (~10 tests)

**New file:** `schemas/enriched_events.py`
**Test:** `tests/test_enriched_event_schemas.py`

Models:
- `IndicatorSnapshot` — `event_metadata`, `bot_id`, `pair`, `timestamp`, `indicators: dict[str, float]`, `signal_name`, `signal_strength`, `decision` (enter/skip/exit)
- `OrderBookContext` — `event_metadata`, `bot_id`, `pair`, `best_bid/ask`, `spread_bps`, `bid/ask_depth_10bps`, `imbalance_ratio`, `trade_context`, `related_trade_id`
- `FilterDecisionEvent` — `event_metadata`, `bot_id`, `pair`, `filter_name`, `passed`, `threshold`, `actual_value`, `margin_pct` (computed)
- `ParameterChangeEvent` — `event_metadata`, `bot_id`, `param_name`, `old/new_value`, `change_source` (pr_merge/manual/hot_reload/experiment), `commit_sha`, `pr_url`

Tests: serialization for each type, computed fields, validation, backward compat

---

### Task 7: Enriched Event Ingestion (~10 tests)

**Modified:** `orchestrator/orchestrator_brain.py`, `skills/build_daily_metrics.py`
**Test:** `tests/test_enriched_event_ingestion.py`
**Depends on:** Task 6

Brain routing:
- `indicator_snapshot` → `QUEUE_FOR_DAILY`
- `orderbook_context` → `QUEUE_FOR_DAILY`
- `filter_decision` → `QUEUE_FOR_DAILY`
- `parameter_change` → `ALERT_IMMEDIATE` if safety-critical, else `QUEUE_FOR_DAILY`

Daily metrics builder additions:
- `build_filter_decision_summary()` → writes `filter_decisions.json`
- `build_indicator_snapshot_summary()` → writes `indicator_snapshots.json`
- `build_orderbook_summary()` → writes `orderbook_stats.json`
- `build_parameter_changes()` → writes `parameter_changes.json`

Tests: brain routing for each type, builder functions, empty data handling, backward compat when new event types absent

---

### Task 8: Enriched Data in Analysis Pipeline (~8 tests)

**Modified:** `analysis/prompt_assembler.py` (daily), `analysis/strategy_engine.py`
**Test:** `tests/test_enriched_data_analysis.py`
**Depends on:** Task 7

- Daily prompt assembler: add `filter_decisions.json`, `indicator_snapshots.json`, `orderbook_stats.json` to `_CURATED_FILES`
- Strategy engine: `detect_filter_interactions` uses filter margin data when available; new `detect_microstructure_issues` detector for high spread/adverse imbalance patterns

Tests: assembler includes new files, handles missing files gracefully, new detector produces suggestions, no suggestion with normal spread, backward compat

---

## Phase 2C: A/B Testing Framework

**Feature flag:** `AB_TESTING_ENABLED=false`

### Task 9: Experiment Schemas (~8 tests)

**New file:** `schemas/experiments.py`
**Test:** `tests/test_experiment_schemas.py`

Models:
- `ExperimentStatus` enum: `DRAFT | ACTIVE | CONCLUDED | CANCELLED`
- `ExperimentType` enum: `PARAMETER_AB | FILTER_AB | ABLATION`
- `ExperimentVariant` — `name`, `params: dict[str, Any]`, `allocation_pct`
- `ExperimentConfig` — `experiment_id`, `bot_id`, `strategy_id`, `experiment_type`, `title`, `description`, `variants` (≥2), `success_metric` (pnl/sharpe/win_rate/profit_factor), `min_trades_per_variant=30`, `max_duration_days=30`, `significance_level=0.05`, `status`, timestamps, `source_suggestion_id`
- `VariantMetrics` — `variant_name`, `trade_count`, `total_pnl`, `avg_pnl`, `win_rate`, `sharpe`, `profit_factor`, `max_drawdown_pct`
- `ExperimentResult` — `experiment_id`, `variant_metrics`, `p_value`, `effect_size` (Cohen's d), `confidence_interval_95`, `winner`, `recommendation` (adopt_treatment/keep_control/inconclusive/extend)

Validations: ≥2 variants, allocation sums to 100, significance_level 0.01-0.10

---

### Task 10: Experiment Manager (~14 tests)

**New file:** `skills/experiment_manager.py`
**Test:** `tests/test_experiment_manager.py`
**Depends on:** Task 9

```python
class ExperimentManager:
    def __init__(self, findings_dir: Path, min_trades: int = 30): ...
    def create_experiment(self, config) -> ExperimentConfig: ...
    def activate_experiment(self, experiment_id) -> None: ...
    def ingest_variant_data(self, experiment_id, variant_name, trades) -> None: ...
    def analyze_experiment(self, experiment_id) -> ExperimentResult: ...
    def check_auto_conclusion(self, experiment_id) -> bool: ...
    def conclude_experiment(self, experiment_id, result) -> None: ...
    def cancel_experiment(self, experiment_id) -> None: ...
    def get_active(self) -> list[ExperimentConfig]: ...
    def _welch_t_test(self, group_a, group_b) -> tuple[float, float, tuple[float, float]]: ...
    def _cohens_d(self, group_a, group_b) -> float: ...
```

Auto-conclusion triggers:
- `p_value < significance_level` and `min_trades_per_variant` reached → conclude with winner
- Duration exceeded → conclude as inconclusive
- Treatment significantly worse → conclude, recommend keep_control

JSONL storage: `experiments.jsonl`, `experiment_results.jsonl`

Tests: lifecycle (create/activate/conclude/cancel), Welch's t-test with known data, Cohen's d, auto-conclusion logic, insufficient data → extend, persistence

---

### Task 11: Experiment Config Generator (~8 tests)

**New file:** `skills/experiment_config_generator.py`
**Test:** `tests/test_experiment_config_generator.py`
**Depends on:** Task 9, Task 10, existing `ConfigRegistry`

```python
class ExperimentConfigGenerator:
    def __init__(self, config_registry: ConfigRegistry): ...
    def generate_from_suggestion(self, suggestion, param_name, current_value, proposed_value, duration_days=14) -> ExperimentConfig: ...
    def generate_bot_yaml(self, config) -> str: ...
    def generate_experiment_pr(self, config, repo_dir) -> PRRequest: ...
```

Creates control (current_value) + treatment (proposed_value) variants with 50/50 allocation. Generates YAML matching each bot's experiment config format. Links to source suggestion via `source_suggestion_id`.

Tests: generate from suggestion, control/treatment values correct, allocation sums, YAML format per bot, deterministic experiment_id, PR request targets correct repo

---

### Task 12: Experiment Data Ingestion (~10 tests)

**Modified:** `skills/build_daily_metrics.py`, `orchestrator/handlers.py`
**Test:** `tests/test_experiment_data_ingestion.py`
**Depends on:** Task 10, Task 7 (for `experiment_breakdown` in `DailySnapshot`)

- `build_daily_metrics.py`: add `build_experiment_breakdown()` — reads `experiment_breakdown` from `DailySnapshot`, writes `experiment_data.json`
- `handlers.py` (weekly): check active experiments → ingest variant data → check auto-conclusion → conclude if ready → broadcast event → generate adoption/rollback PR suggestion

Tests: builder extracts experiment_breakdown, handler ingests data, auto-conclusion flow, treatment wins → adoption suggestion, no active experiments → skip, missing data → skip

---

### Task 13: Experiment Approval UX (~6 tests)

**Modified:** `comms/telegram_renderer.py`, `comms/telegram_handlers.py`
**Test:** `tests/test_experiment_approval_ux.py`
**Depends on:** Task 9, Task 10

Add to `TelegramRenderer`:
- `render_experiment_proposal(config)` → message + `[Start Experiment] [Cancel]` keyboard
- `render_experiment_result(result)` → variant metrics table + recommendation

Callback data: `start_experiment_{id}`, `cancel_experiment_{id}`, `adopt_experiment_{id}`

Tests: proposal rendering, result rendering, callback data format, truncation, missing fields handled

---

### Task 14: A/B Testing Wiring + Integration Test (~10 tests)

**Modified:** `orchestrator/config.py`, `orchestrator/app.py`, `orchestrator/scheduler.py`
**New file:** `tests/test_experiment_integration.py`
**Depends on:** Tasks 9-13

- `config.py`: add `ab_testing_enabled: bool = False`
- `app.py`: create `ExperimentManager` + `ExperimentConfigGenerator` when enabled
- `scheduler.py`: schedule experiment check job (interval, every 6h)
- Integration scenarios: full lifecycle, inconclusive result, treatment worse → rollback, manual cancellation, flag off → no infrastructure, concurrent experiments

---

## Phase 2D: Autonomous Deployment Monitoring

**Feature flag:** `DEPLOYMENT_MONITORING_ENABLED=false`

### Task 15: Deployment Monitor Schema (~6 tests)

**New file:** `schemas/deployment_monitoring.py`
**Test:** `tests/test_deployment_monitoring_schemas.py`

Models:
- `DeploymentStatus` enum: `PENDING_MERGE | MERGED | DEPLOYING | DEPLOYED | REGRESSION_DETECTED | ROLLED_BACK`
- `DeploymentRecord` — `deployment_id`, `approval_request_id`, `pr_url`, `pr_number`, `bot_id`, `param_changes`, `status`, `merge_time`, `deploy_detected_time`, `monitoring_window_hours=24`, `pre/post_deploy_metrics`, `regression_detected`, `regression_details`, `rollback_pr_url`, `created_at`
- `DeploymentMetricsSnapshot` — `bot_id`, `timestamp`, `total_trades`, `win_rate`, `avg_pnl`, `sharpe_rolling_7d`, `max_drawdown_pct`

Tests: status transitions, serialization, defaults, regression fields

---

### Task 16: Deployment Monitor (~14 tests)

**New file:** `skills/deployment_monitor.py`
**Test:** `tests/test_deployment_monitor.py`
**Depends on:** Task 15, existing `PRBuilder`, `ConfigRegistry`

```python
class DeploymentMonitor:
    def __init__(self, findings_dir, curated_dir, pr_builder, config_registry, event_stream=None): ...
    def create_deployment(self, approval_request) -> DeploymentRecord: ...
    async def check_merge_status(self, deployment_id) -> bool: ...
    def record_pre_deploy_metrics(self, deployment_id, snapshot) -> None: ...
    def record_post_deploy_metrics(self, deployment_id, snapshot) -> None: ...
    def check_regression(self, deployment_id) -> bool: ...
    async def create_rollback_pr(self, deployment_id) -> PRResult: ...
    def get_monitoring(self) -> list[DeploymentRecord]: ...
    def collect_metrics_snapshot(self, bot_id) -> DeploymentMetricsSnapshot: ...
```

Regression detection:
- 7 days pre-deploy daily PnL → mean + std
- Post-deploy cumulative PnL > 2σ below mean → regression
- Additional: win_rate decline >15pp, max_drawdown >50% worse

Rollback PR: uses `FileChangeGenerator` for reverse change, title `[trading-assistant] ROLLBACK: revert {param_name} on {bot_id}`

Tests: create deployment, check merge (mocked gh), record metrics, regression detection (>2σ), no regression (normal range), rollback PR creation, monitoring window expiry → success, JSONL persistence, concurrent deployments, event broadcasts

---

### Task 17: Deployment Monitor Wiring (~8 tests)

**Modified:** `orchestrator/config.py`, `orchestrator/app.py`, `orchestrator/scheduler.py`, `orchestrator/handlers.py`
**Test:** `tests/test_deployment_monitor_wiring.py`
**Depends on:** Task 16

- `config.py`: add `deployment_monitoring_enabled: bool = False`
- `app.py`: create `DeploymentMonitor` when enabled, hook into approval handler (auto-create `DeploymentRecord` after PR created)
- `scheduler.py`: schedule deployment check every 30 min
- `handlers.py`: deployment check function processes all states (PENDING_MERGE → check merge, MERGED → check heartbeat, DEPLOYED → check regression)

Tests: flag off → no monitor, flag on → wired, scheduler job registered, PR creation triggers deployment record, regression triggers rollback PR + Telegram notification, no error when no active deployments

---

### Task 18: Phase 2D Integration Test (~6 tests)

**New file:** `tests/test_deployment_monitoring_integration.py`
**Depends on:** Tasks 15-17

Scenarios: happy path (PR → merge → deploy → 24h pass → success), regression detected → rollback PR, PR not merged → expires, heartbeat missing → alert, flag off → unchanged, selective rollback with multiple deployments

---

## Summary

| Sub-Phase | New Source Files | Modified Files | Est. Tests |
|-----------|-----------------|----------------|------------|
| **2A: Adaptive Thresholds** | `schemas/detection_context.py`, `skills/threshold_learner.py` | `schemas/strategy_suggestions.py`, `analysis/strategy_engine.py`, `orchestrator/config.py`, `orchestrator/app.py`, `orchestrator/scheduler.py`, `analysis/context_builder.py`, `orchestrator/handlers.py` | ~52 |
| **2B: Enriched Events** | `schemas/enriched_events.py` | `orchestrator/orchestrator_brain.py`, `skills/build_daily_metrics.py`, `analysis/prompt_assembler.py`, `analysis/strategy_engine.py` | ~28 |
| **2C: A/B Testing** | `schemas/experiments.py`, `skills/experiment_manager.py`, `skills/experiment_config_generator.py` | `skills/build_daily_metrics.py`, `orchestrator/handlers.py`, `comms/telegram_renderer.py`, `comms/telegram_handlers.py`, `orchestrator/config.py`, `orchestrator/app.py`, `orchestrator/scheduler.py` | ~56 |
| **2D: Deployment Monitoring** | `schemas/deployment_monitoring.py`, `skills/deployment_monitor.py` | `orchestrator/config.py`, `orchestrator/app.py`, `orchestrator/scheduler.py`, `orchestrator/handlers.py` | ~34 |
| **Total** | **7 new source files** | **12 modified files** | **~170** |

## Dependency Graph

```
Phase 2A (Adaptive Thresholds) ──────── no external dependencies
  Task 0 (Schema) → Task 1 (Recording) → Task 2 (Learner) → Task 3 (Engine) → Task 4 (Wiring) → Task 5 (Integration)

Phase 2B (Enriched Events) ──────────── no external dependencies, parallelizable with 2A
  Task 6 (Schema) → Task 7 (Ingestion) → Task 8 (Analysis)

Phase 2C (A/B Testing) ─────────────── depends on 2B.Task 7 for experiment_breakdown ingestion
  Task 9 (Schema) → Task 10 (Manager) → Task 11 (Config Gen) ─┐
                                       → Task 12 (Ingestion) ──┤→ Task 14 (Integration)
                                       → Task 13 (UX) ─────────┘

Phase 2D (Deployment Monitoring) ────── depends on Phase 1 PRBuilder + ApprovalTracker
  Task 15 (Schema) → Task 16 (Monitor) → Task 17 (Wiring) → Task 18 (Integration)
```

**Recommended implementation order:**
1. **2A + 2B in parallel** (no cross-dependencies)
2. **2D** (builds on existing Phase 1 PR infrastructure)
3. **2C** (depends on 2B for experiment data ingestion, most cross-cutting)

## Critical Files

| File | Role |
|------|------|
| `analysis/strategy_engine.py` | All 12 detectors need detection_context (Task 1) + adaptive threshold lookup (Task 3) |
| `schemas/strategy_suggestions.py` | Add `detection_context` field — anchors entire 2A |
| `skills/suggestion_tracker.py` | JSONL pattern to follow for ThresholdLearner, ExperimentManager, DeploymentMonitor |
| `orchestrator/app.py` | Central wiring for all four sub-phases |
| `orchestrator/config.py` | Three new feature flags |
| `skills/build_daily_metrics.py` | Extended for enriched events (2B) and experiment data (2C) |
| `orchestrator/handlers.py` | Weekly handler extended for experiment lifecycle (2C) and deployment tracking (2D) |

## Verification

1. `pytest tests/` — all 1838 existing + ~170 new tests pass
2. All feature flags off → behavior identical to Phase 1
3. `ADAPTIVE_THRESHOLDS_ENABLED=true` → learner runs on empty data, returns defaults
4. Enriched event schemas validate independently, builder handles missing events
5. `AB_TESTING_ENABLED=true` → experiment manager creates/concludes with mocked data
6. `DEPLOYMENT_MONITORING_ENABLED=true` → monitor tracks mock PR lifecycle
7. All 12 strategy engine detectors produce detection_context on suggestions
