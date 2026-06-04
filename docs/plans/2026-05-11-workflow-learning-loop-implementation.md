# Workflow & Learning Loop — Implementation Plan

Date: 2026-05-11
Target artifact (on approval): `docs/plans/2026-05-11-workflow-learning-loop-implementation.md`
Source spec: `docs/2026-05-11-workflow-learning-loop-target-state.md`

## Context

`trading_assistant` is a strong reporting/screening loop. It is not yet an evidence-backed strategy-improvement loop:

- **WFO** (`skills/run_wfo.py`, scheduled Saturday 02:00 by `SchedulerConfig.wfo_day_of_week/hour`) replays curated `TradeEvent`/`MissedOpportunityEvent` records using `skills/backtest_simulator.py` ("simplified trade replay with parameter filtering"). It cannot prove alternate parameters would have produced different signals/entries/exits/fills on the real market. Its optimizer is single-metric (`WFOConfig.optimization.objective`), not the canonical composite.
- **`AutoOutcomeMeasurer`** (`skills/auto_outcome_measurer.py`, scheduled Sunday 10:00 by `SchedulerConfig.outcome_measurement_*`) finalizes the verdict at the first available 7/14/30-day daily-summary window via `measure_progressive`. Any material change can be marked `MEASURED` before stronger evidence exists. `SuggestionTracker.mark_measured(suggestion_id)` takes no source parameter — every outcome source looks the same to downstream consumers.
- **Feedback** (`SuggestionScorer`, `ContextBuilder` with ~40 `load_*` methods, `ResponseValidator`) shapes prompts and confidence. It does not change candidate generation, search allocation, smoke-test focus, acceptance gates, or rollback priority.
- **No strategy-level changelog** joins proposal → approval → PR → commit → deployment → outcome → rollback. `ProposalLedger` (`skills/proposal_ledger.py`, JSONL `proposal_ledger.jsonl`) holds candidate provenance per (source, kind, bot, strategy). `SuggestionTracker` holds suggestion lifecycle. `ApprovalTracker` and `DeploymentMonitor` track approvals and post-merge regression. Nothing joins them into a single per-strategy answer.
- **Canonical market-data sync** and replay-parity audits are not yet prerequisites.

The target replaces the lightweight optimization/outcome path with a **monthly full-fidelity validation-and-repair loop** that (a) uses the existing `objective_weights_v1` composite for selection and measurement, (b) does full replay in a sibling `trading_backtests` repo, and (c) writes to a new strategy-level ledger. Daily/weekly stay as sensors. All trading-behavior changes remain human-approved. This plan reuses existing infrastructure as much as possible and sequences the transition across 13 phases.

## What Already Exists (Reuse, Do Not Rebuild)

Verified in the code:

- **Event lineage**: `TradeEvent` and `MissedOpportunityEvent` (`schemas/events.py` lines 218-226 and 273-281) already carry all 8 lineage fields — `deployment_id`, `experiment_id`, `variant_id`, `parameter_set_id`, `strategy_version`, `config_version`, `signal_generation_version`, `code_sha`. **No schema change is needed on these payloads.**
- **Deployment lineage**: `DeploymentRecord` (`schemas/deployment_monitoring.py`) has `variant_id`, `parameter_set_id`, `strategy_version`, `config_version`, `affected_population` (event_id refs), `pr_url`, `pr_number`, `regression_detected`, `rollback_pr_url`.
- **Objective**: `OBJECTIVE_WEIGHTS_VERSION = "objective_weights_v1"` in `schemas/objective_weights.py` with full + renormalized (no-process) weights and `ratio_to_unit_scale()`. `ParameterSearcher._composite_score` already uses these. `ProposalEvaluation` and `ProposalOutcome` already carry `objective_version: str = OBJECTIVE_WEIGHTS_VERSION`.
- **Proposal/Approval/Deployment infrastructure**:
  - `ProposalLedger` (JSONL) with `ProposalCandidate` (sources include WFO, PARAMETER_SEARCH, STRUCTURAL_EXPERIMENT, PORTFOLIO, INSTRUMENTATION) + `ProposalEvaluation` (already has `evidence_paths` and `objective_version`) + `ProposalOutcome` (already has `objective_delta`, `objective_version`, `verdict`).
  - `SuggestionTracker` with lifecycle `PROPOSED → ACCEPTED → MERGED → DEPLOYED → MEASURED` (+ `REJECTED`).
  - `ApprovalTracker` with `create_request`, `approve`, `reject`, `set_pr_url`, `set_pr_result`. `ApprovalRequest` lives in `schemas/autonomous_pipeline.py`.
  - `DeploymentMonitor` with `create_deployment`, `mark_deployed`, `check_regression`, `record_pre_deploy_metrics`, `record_post_deploy_metrics`.
  - `ApprovalHandler` with `handle_approve`, `handle_reject`, `_resolve_repo_changes`, full PR/branch workflow.
- **WFO building blocks** in `WFORunner`: fold generation (`skills/fold_generator.py`), `_run_cost_sensitivity`, `_cost_safety_flags`, `_run_folds`, robustness testing (`skills/robustness_tester.py`), leakage detection (`skills/leakage_detector.py`), `param_optimizer.py`. These are the right pieces for the monthly loop — they just need a full-fidelity engine behind them.
- **Parameter search**: `ParameterSearcher` already uses `objective_weights_v1` for composite scoring + routes `APPROVE/EXPERIMENT/DISCARD`. Reusable as the inner-loop scoring layer for phased-auto.
- **Learning loop**: `LearningCycle` (weekly) does measure → synthesize → keep/discard → recalibrate → propose next. `LearningLedger` records weekly ground-truth snapshots and composite deltas, has `record_outcome_lessons` and `compute_cycle_effectiveness`. Monthly loop runs *after* the weekly learning cycle; it does not replace it.
- **Context assembly**: `ContextBuilder` already has `load_recent_proposal_outcomes`, `load_outcome_measurements`, `load_active_experiments`, `load_category_scorecard`, `load_hypothesis_track_record`, `load_transfer_track_record`, `load_recalibrations`, `load_outcome_reasonings`, `load_discoveries`, `load_validation_patterns`, `load_consolidated_patterns`, `load_search_reports`, `load_ablation_analysis`, `load_engine_decomposition`, `load_exit_tier_analysis`. New `load_*` methods follow this pattern.
- **Scheduler**: `SchedulerConfig` is a dataclass with cron fields for ~15 jobs (`daily_analysis`, `weekly_analysis`, `wfo`, `outcome_measurement`, `memory_consolidation`, `transfer_outcome`, `approval_expiry`, `pr_review_check`, `deployment_check`, `threshold_learning`, `experiment_check`, `reliability_verification`, `discovery`, `learning_cycle`). `build_scheduled_job_specs()` returns `ScheduledJobSpec` records. New jobs slot in here.
- **Structural proposals**: `StructuralProposal` (`schemas/agent_response.py`) exists with `hypothesis_id`, `linked_suggestion_id`, `bot_id`, `title`, `description`, `reversibility`, `evidence` (string), `estimated_complexity`, `confidence`, `file_changes`, `verification_commands`, `acceptance_criteria`. **Extend, don't replace.** `ResponseValidator` already has `_validate_structural_proposals` + `_calibrate_structural_confidence`.
- **Config registry**: `skills/config_registry.py` (`ConfigRegistry`) loads bot YAML profiles; `BotConfigProfile`/`ParameterDefinition` in `schemas/autonomous_pipeline.py`. No `config_version` field today.
- **Run history & evidence**: `orchestrator/run_index.py`, `orchestrator/scheduled_runs.py`, `runs/<run_id>/` artifact convention.

## Boundary Decisions (Phase 0 ADR)

- **Authoritative loop**: monthly full-fidelity validation. Legacy WFO (`skills/run_wfo.py`) and `AutoOutcomeMeasurer` are **demoted to screening/early-warning** in docstrings, `CLAUDE.md`, and `soul.md`. Not deleted; their building blocks (fold generation, cost sensitivity, robustness, leakage) are reused.
- **Objective**: `objective_weights_v1` for selection and measurement. Use `*_NO_PROCESS` renormalized weights (already in `schemas/objective_weights.py`) when process quality cannot be simulated. Trade frequency is a viability gate only.
- **Backtest engine boundary**: sibling local git repo `trading_backtests`, configured by `BACKTEST_REPO_PATH`. Invoked through a stable CLI with a frozen JSON manifest. Strategy plugins, replay engines, mutation semantics live there. `trading_assistant` stays orchestrator + evidence ledger + approval router.
- **Market data**: shared root `MARKET_DATA_ROOT/<market>/<symbol>/<timeframe>/<source>/yyyy-mm.parquet`. Never committed. Coverage manifest required.
- **Artifacts**: monthly outputs under `BACKTEST_ARTIFACT_ROOT/<bot>/<YYYY-MM>/` containing `coverage_manifest.json`, `run_manifest.json`, `incumbent_validation.json`, `parity_report.json`, `gap_attribution.json`, `candidate_results.jsonl`, `selected_candidates.json`, `rejected_candidates.jsonl`, `monthly_report.md`, `monthly_repair_prompt_input.json` (model input snapshot).
- **Cadence**: daily/weekly stay as sensors and diagnostics. The existing weekly `LearningCycle` continues. Monthly is authoritative for material strategy/config decisions.
- **Storage**: JSONL under `memory/findings/` (consistent with `ProposalLedger`/`SuggestionTracker`); SQLite reserved for queue/run state. `MonthlyVerdict` is appended both to `StrategyChangeLedger` (canonical) and back-linked via `ProposalOutcome` in `ProposalLedger` (existing schema; no schema break).

Concrete ownership:

```text
trading_assistant  -> orchestration, coverage checks, run manifests, ledgers, approval routing, feedback priors
trading_backtests  -> manifest-backed replay, strategy plugins, smoke-repair, phased-auto, artifact generation
trading_data       -> canonical parquet, coverage manifests, telemetry manifests, run artifacts
```

Production market data and run artifacts must stay outside both code repos. Reproducibility comes from data checksums/manifests, config versions, objective version, and code SHAs, not from committing parquet into git.

---

## Phase 0 — ADR & Policy

**Create**:
- `docs/adr/0001-monthly-authoritative-loop.md` — declare monthly loop authoritative; demote WFO + `AutoOutcomeMeasurer`; preserve them as screening/early-warning.
- `docs/adr/0002-backtest-repo-boundary.md` — `BACKTEST_REPO_PATH`, manifest contract, artifact layout, `backtest_repo_commit_sha` pinning per run.
- `docs/adr/0003-objective-canonicalization.md` — confirm `objective_weights_v1`; codify gate checklist from §5.6 of target doc (no in-sample deterioration; OOS improvement; positive purged folds; trade-count, cost realism, drawdown caps; no zero-cost-only improvement; no portfolio/symbol/leverage breach).

The gate checklist must also include data coverage, telemetry lineage, replay parity, no leakage, no dependence on one or two outlier wins, sufficient sample size or explicit sparse classification, and no approval-ready proposal from an unsupported or diagnostics-only strategy.

**Modify**:
- `CLAUDE.md` — new "Monthly Authoritative Loop" section pointing to the ADRs; reclassify WFO and `AutoOutcomeMeasurer`; document new env vars and the cadence reshuffle.
- `memory/policies/v1/soul.md` — append a short paragraph stating the monthly loop is the binding measurement for material strategy/config changes; trade frequency is a viability gate, not an objective. (Existing soul.md already states the 6-component composite — do not duplicate.)
- `skills/run_wfo.py` docstring — mark legacy/screening; cross-reference the monthly loop.
- `skills/auto_outcome_measurer.py` docstring — mark early-warning/context only; explain it does not finalize material changes.

**Acceptance**: docs render; one source of truth per ADR; demotion is visible in `CLAUDE.md` and module docstrings; `soul.md` updated.

---

## Phase 1 — Attribution & Telemetry Contract

`TradeEvent` and `MissedOpportunityEvent` already carry the full 8-field lineage set. The remaining work is enforcement, audit, propagation through the snapshot/aggregate layer, and a gate that blocks monthly verdicts when lineage is incomplete.

**Modify**:
- `schemas/events.py::DailySnapshot` — add optional `lineage_summary: dict | None = None` carrying `{strategy_version_counts, config_version_counts, deployment_id_counts, parameter_set_id_counts, experiment_id_counts}`. Computed during curation, not by bots.
- `schemas/bot_config.py::BotConfig` — add `strategy_version: str | None = None`, `config_version: str | None = None`, `code_sha: str | None = None` (optional; populated by deployment ingestion or curation).
- `schemas/deployment_monitoring.py::DeploymentRecord` — add `experiment_id: str | None = None`, `code_sha: str | None = None`.
- `skills/build_daily_metrics.py` — compute `lineage_summary` from trade events when assembling the daily snapshot; emit a `lineage_gap` flag when material gaps exist.

**Create**:
- `orchestrator/lineage_audit.py` — periodic audit (daily 06:30 UTC, after market-data sync); checks required-field coverage per bot/strategy; writes findings to `memory/findings/lineage_gaps.jsonl`; emits a `ProposalCandidate(source=INSTRUMENTATION, kind=INSTRUMENTATION_REQUEST)` when fields are persistently missing.
- `schemas/lineage_audit.py` — `LineageGapReport(bot_id, strategy_id, window_start, window_end, total_events, missing_field_counts, severity, recommended_action)`.

Also create `schemas/telemetry_manifest.py` for monthly `{event_counts_by_type, lineage_coverage_ratio, missing_field_counts, duplicate_count, known_gaps, authoritative_eligibility}` per bot/strategy. Monthly validation consumes this alongside the market-data coverage manifest.

**Modify** event ingestion (`relay/` + `orchestrator/worker.py`):
- Pass lineage fields through verbatim (no stripping). Emit SSE `lineage_missing` event with severity when required fields are absent.

**Tests** (`tests/test_lineage_audit.py`, `tests/test_event_lineage_back_compat.py`):
- Existing event JSONL without lineage fields still parses (back-compat).
- Lineage audit detects missing fields and emits instrumentation request.
- `DailySnapshot.lineage_summary` populated correctly from mixed-lineage trade lists.

**Acceptance**: every trade and missed-opportunity event maps to `(strategy_version, config_version, deployment_id)` when bots emit them; missing attribution is observable, persists to disk, and blocks Phase 9 monthly verdicts (later).

---

## Phase 2 — Canonical Market Data Sync

**Create**:
- `schemas/coverage_manifest.py` — `CoverageManifest(market, symbol, timeframe, source, start_ts, end_ts, bar_count, missing_bar_intervals, timezone, session_metadata, fee_metadata, slippage_metadata, funding_metadata, corporate_actions, checksum, source_version, generated_at, manifest_version)`.
- `skills/market_data_sync.py` — pulls per-(market, symbol, timeframe, source) parquet under `MARKET_DATA_ROOT`. Supports vendor adapters (initial: bot-uploaded fallback path).
- `skills/coverage_manifest_writer.py` — assembles manifest after sync; verifies it reaches latest completed month-end; computes checksum.
- `orchestrator/handlers.py::handle_market_data_sync` — monthly handler invoked before validation.

**Modify**:
- `orchestrator/scheduler.py` `SchedulerConfig` — add `market_data_sync_day_of_month`, `_hour`, `_minute` (default: 1st of month, 01:00 UTC) plus `_enabled`. Register in `build_scheduled_job_specs()` using the existing `_append_cron_specs` helper.
- `orchestrator/config.py` `AppConfig.from_env()` — read `MARKET_DATA_ROOT`, `BACKTEST_REPO_PATH`, `BACKTEST_ARTIFACT_ROOT`. Add fields `market_data_root: str = ""`, `backtest_repo_path: str = ""`, `backtest_artifact_root: str = ""`, `monthly_validation_enabled: bool = False`.
- `.env.example` — document the new env vars.

Add config fields for `monthly_validation_mode: Literal["disabled", "shadow", "approval_gated"] = "disabled"`, `backtest_command_timeout_seconds`, `backtest_max_parallel_strategies`, and `market_data_required_coverage_ratio`.

Add `skills/market_data_catalog.py` as the registry of required symbols/timeframes/data sources per strategy and bot. Initial adapters: `KisMarketDataAdapter` for Korean equities where the configured account and endpoint support historical intraday bars, `BotUploadedParquetAdapter` when the bot is the only reliable source, and `FileSystemParquetAdapter` for vendor/exchange parquet under `MARKET_DATA_ROOT`. For KIS, verify endpoint capability in the real account/environment, archive live WebSocket
tick/order-book data going forward when OHLCV is not enough, and mark the strategy diagnostics-only when required intraday or microstructure data is unavailable.

`CoverageManifest` should include expected bars, actual bars, coverage ratio, missing ranges, checksum, source version, adjustment policy, fee/slippage model versions, `usable_for_authoritative_validation`, and explicit `blocking_reasons`.

**Tests**: fixture parquet, manifest writer, freshness check, latest-month-end gate, checksum stability, fallback-path semantics.

**Acceptance**: monthly orchestrator refuses to proceed without a manifest reaching latest-completed-month-end. Bot-uploaded parquet allowed only when the bot has the only reliable feed.

---

## Phase 3 — StrategyChangeLedger

Mirror the proven `ProposalLedger` pattern.

**Create**:
- `schemas/strategy_change_ledger.py`:
  - `StrategyChangeRecord(record_id, bot_id, strategy_id, record_type, prior_config_version, new_config_version, mutation_diff, source_proposal_ids: list[str], source_suggestion_ids: list[str], approval_request_id: str | None, pr_url: str | None, commit_sha: str | None, deployment_id: str | None, deployed_at: datetime | None, evidence_paths: list[str], decision_reason: str, one_month_verdict: dict | None, follow_up_verdict: dict | None, rollback_status: str, created_at, updated_at)`.
  - `record_type ∈ {monthly_review, proposed_change, deployed_change, rollback, no_change_decision}`.
  - `rollback_status ∈ {none, watching, recommended, executed}`.
- `skills/strategy_change_ledger.py` — JSONL-backed append + in-place update, lock-protected, mirrors `ProposalLedger` shape (single file `memory/findings/strategy_change_ledger.jsonl`, event-stream entries: `{"type": "record"|"update", "payload": ...}`). Methods: `record_monthly_review`, `record_proposed_change`, `record_deployed_change`, `record_one_month_verdict`, `record_follow_up_verdict`, `record_rollback`, `record_no_change_decision`, `get_recent`, `get_for_strategy`, `get_by_id`. Deterministic `record_id` = 16-char SHA256 prefix of `(bot_id, strategy_id, record_type, source_proposal_ids|approval_request_id|deployment_id, created_date)`.

**Modify**:
- `analysis/context_builder.py` — add `load_strategy_change_ledger(bot_id="", days=180)` injected into `base_package()` data alongside the existing `load_recent_proposal_outcomes`.
- `analysis/daily_prompt_assembler.py`, `weekly_prompt_assembler.py`, `wfo_prompt_assembler.py`, `discovery_prompt_assembler.py` — include recent strategy-level changes in their context section.
- `orchestrator/memory_consolidator.py` — add `consolidate_strategy_changes()` step; surface in weekly consolidation.

**Tests**: deterministic ID, dedup, append + in-place update, lineage links to existing `ProposalLedger` proposal_ids, `SuggestionTracker` suggestion_ids, `ApprovalTracker` request_ids, `DeploymentMonitor` deployment_ids.

**Acceptance**: a reviewer can answer "what changed on bot X strategy Y this month, why, did it work?" from `strategy_change_ledger.jsonl` alone; broad candidate noise remains in `ProposalLedger`.

---

## Phase 4 — Replay Adapter & Parity Audit

The existing `BacktestSimulator` is simplified trade replay with parameter filtering — not full-fidelity. The work is to define the boundary to the sibling repo and the parity contract.

**Create (this repo)**:
- `schemas/run_manifest.py` — `RunManifest(manifest_id, strategy_id, bot_id, production_config_path, production_config_version, parquet_coverage_manifest_paths: list[str], objective_version, accepted_mutation_ledger_path, run_window_start, run_window_end, artifact_root, backtest_repo_commit_sha, manifest_version, generated_at)`.
- `schemas/parity_report.py` — `ParityReport(strategy_id, bot_id, window, trade_count_live, trade_count_replay, entry_match_rate, exit_match_rate, pnl_delta_pct, cost_delta_bps, drawdown_delta_pct, missing_explanations: list[str], status ∈ {pass, warn, fail}, evidence_paths)`.
- `analysis/replay_adapter.py` — subprocess invoker: runs `python -m backtests.shared.monthly_repair --manifest <path>` inside `BACKTEST_REPO_PATH`; captures artifacts; surfaces failures as `replay_failed` events. Long-running → spawned via `SubagentManager` (already in `orchestrator/subagent.py`).
- `skills/parity_runner.py` — orchestrates incumbent parity replays for the strategies that have a replay plugin; writes `ParityReport` JSON under the run's artifact folder.

`RunManifest` should also carry `mode`, `created_at`, `latest_month_start/end`, `calibration_start/end`, `selection_oos_start/end`, `telemetry_manifest_path`, `backtest_command`, `approval_mode`, and `expected_outputs`. The replay adapter must validate the returned artifact index, capture `stdout.log`/`stderr.log`/`exit_status.json`, and reject authoritative verdicts when required artifacts are missing, stale, malformed, or not linked to the manifest.

**Out of scope (sibling `trading_backtests` repo, documented but not built here)**:
- Strategy plugin protocol per references (`_references/trading/backtests/shared/auto/plugin.py`).
- CLI: `python -m backtests.shared.monthly_repair --manifest <path>`.
- Standard artifact set under `artifact_root`, including artifact index,   incumbent validation, parity report, gap attribution, mode decision, objective breakdown, candidate results, selected/rejected candidates, logs, and a concise monthly report.

**Tests**: manifest schema, replay adapter timeout/error handling, parity report status thresholds, subagent integration smoke test against a stub backtest CLI.

**Acceptance**: monthly orchestrator blocks unless parity is `pass`/`warn` for the strategy; strategies without a passing replay adapter remain reporting-only.

---

## Phase 5 — Monthly Validation Orchestrator

**Create**:
- `orchestrator/monthly_runner.py`:
  1. Verify `CoverageManifest` reaches latest completed month.
  2. Freeze run metadata: month, data versions, strategy/config versions, deployment IDs, `OBJECTIVE_WEIGHTS_VERSION`, `backtest_repo_commit_sha`.
  3. Build a `RunManifest` per strategy/bot.
  4. Invoke incumbent replay via `replay_adapter`.
  5. Run parity audit (`parity_runner`).
  6. Run gap attribution.
  7. Write `StrategyChangeRecord(record_type=monthly_review)` with status `keep|watch|repair|rollback|insufficient_data`.
  8. Emit candidates for Phase 6/7 if repair is needed.

Monthly strategy status set:
`keep|watch|repair|rollback|quarantine|experiment|insufficient_data|insufficient_lineage|unsupported_no_replay_plugin|no_change`.

Gap attribution should explicitly distinguish under-trading, outlier loss, broad degradation, execution drift, slippage/cost drift, data gap, regime mismatch, harmful accepted mutation, filter overreach, entry signal decay, exit mismatch, portfolio/correlation crowding, and opportunity scarcity.
- `skills/gap_attribution.py` — deterministic classifier emitting `GapAttribution(strategy_id, bot_id, window, primary_mode ∈ {under_trading, outlier_losses, execution_drift, regime_mismatch, data_gap, mutation_harm, filter_overreach, other}, secondary_modes, evidence_paths)`. Reuses `skills/drawdown_analyzer.py`, `skills/slippage_analyzer.py`, `skills/hourly_analyzer.py`, `skills/exit_tier_analyzer.py`, `skills/regime_parameter_analyzer.py`, `skills/engine_decomposer.py` for the underlying analyses.
- `schemas/gap_attribution.py`.
- `analysis/monthly_prompt_assembler.py` — minimal assembler for any synthesis the monthly run needs before Phase 8.
- `orchestrator/handlers.py::handle_monthly_validation` — long-running; spawn via `SubagentManager`; broadcast `monthly_validation_progress` events through `EventStream`.

**Modify**:
- `orchestrator/scheduler.py` `SchedulerConfig` — add `monthly_validation_day_of_month`, `_hour`, `_minute` (default: 2nd of month, 03:00 UTC; after market-data sync). Register via `_append_cron_specs`.
- `orchestrator/app.py` — wire handler slot; pass `strategy_change_ledger`, `replay_adapter`, `parity_runner`, `coverage_manifest_reader` references.

**Tests**: golden monthly run on fixture; insufficient-data path; harmful-mutation path; replay-parity-blocking path; coverage-manifest-stale path.

**Acceptance**: every strategy receives `keep|watch|repair|rollback|insufficient_data`; insufficient data is not treated as success or failure; latest completed month is clearly marked incumbent-validation before reuse as selection-OOS for any repair candidates.

Unsupported, insufficient-lineage, quarantined, and diagnostics-only strategies must be reported explicitly rather than folded into `insufficient_data`.

---

## Phase 6 — Smoke-Repair Mode

**Create**:
- `skills/smoke_repair.py` — wraps the sibling repo's smoke runner via `replay_adapter`. Generates:
  - Accepted-prefix checks (validate the prefix of the accepted-mutation ledger).
  - One-at-a-time rollback candidates over recently accepted mutations.
  - Cluster rollback candidates.
  - Local numeric/boolean perturbations targeting the diagnosed failure mode.
  - Targeted candidates derived from `GapAttribution.primary_mode`.
  - Ranks candidates against frozen incumbent using calibration window + purged folds + latest-month selection-OOS using `objective_weights_v1` (`ParameterSearcher._composite_score` is the reference scorer).
- `schemas/smoke_repair_result.py` — `SmokeRepairResult(strategy_id, bot_id, candidates: list[SmokeCandidate], rollback_recommendations, decision ∈ {keep, repair, rollback, escalate_to_phased_auto}, evidence_paths)`.

**Modify**:
- `orchestrator/monthly_runner.py` — when `GapAttribution.primary_mode` ∈ {`mutation_harm`, `under_trading`, `outlier_losses`, `execution_drift`, `filter_overreach`}, smoke-repair runs first.

**Tests**: fixture with a known-harmful accepted mutation → expects rollback selection; fixture with a perturbation winner → expects keep+repair; escalation path to phased-auto.

**Acceptance**: smoke-repair explains whether recent mutations caused degradation; each candidate has a keep/reject/repair/experiment decision with evidence paths.

---

## Phase 7 — Phased-Auto Mode

**Create**:
- `skills/phased_auto.py` — wraps the sibling repo's shared phased-auto runner. Defines phase specs, candidate families, greedy selection per phase. Adds fold-local purged validation with embargo, cost sensitivity, outlier-exclusion, portfolio/synergy checks. Reuses:
  - `skills/fold_generator.py` for purged/embargo folds (extend existing helper).
  - `WFORunner._run_cost_sensitivity` + `_cost_safety_flags` — extract these to `skills/cost_sensitivity.py` for shared use; preserve `WFORunner` calls.
  - `skills/robustness_tester.py`, `skills/leakage_detector.py`.
  - `skills/portfolio_outcome_measurer.py`, `skills/synergy_analyzer.py` for portfolio/synergy checks.
- `schemas/phased_auto_result.py` — full ranked-candidate set + rejected candidates with rejection reasons + per-phase summaries.

**Modify**:
- `orchestrator/monthly_runner.py` — phased-auto runs when (a) the strategy plugin reports maturity, (b) data sufficiency passes, (c) smoke-repair did not produce a stable winner alone.

**Tests**: fixture with a known winner; fixture where data is insufficient → expects no-go; gate-failure path (no in-sample deterioration, OOS improvement required, trade-count gate).

**Acceptance**: phased-auto runs only when plugin maturity + data + sample size are sufficient; selected candidates pass all gates; rejected candidates persist with reasons.

---

## Phase 8 — Model Review & Structural Proposal Layer

`StructuralProposal` exists in `schemas/agent_response.py`. Extend rather than replace.

**Modify** `schemas/agent_response.py::StructuralProposal`:
- Add: `failure_mode: str = ""`, `mechanism: str = ""`, `affected_strategy_versions: list[str] = []`, `affected_config_versions: list[str] = []`, `expected_objective_impact: dict[str, float] = {}` (e.g. `{"net_profit": +0.05, "calmar": +0.10, "max_drawdown": -0.02}`), `risk_classification: Literal["low", "medium", "high"] = "medium"`, `replay_or_experiment_plan: str = ""`, `rollback_plan: str = ""`, `routing: Literal["smoke_repair", "phased_auto", "experiment", "manual_design_review"] = "manual_design_review"`, `evidence_paths: list[str] = []`, `rejected_alternatives: list[dict] = []`.
- Keep existing `evidence: str` for back-compat; new path requires non-empty `evidence_paths`.

**Modify** `analysis/response_validator.py::_validate_structural_proposals`:
- Block proposals where `routing` requires deterministic backing but `evidence_paths` is empty.
- Tighten confidence caps when `risk_classification == "high"` and category scorecard shows repeated negative monthly outcomes.

**Create**:
- `analysis/monthly_repair_prompt_assembler.py` — inputs: `incumbent_validation.json`, `parity_report.json`, `gap_attribution.json`, `smoke_repair_result.json`, `phased_auto_result.json`, `rejected_candidates.jsonl`, `objective_deltas`, recent `StrategyChangeRecord`s, category scorecard, hypothesis track record, outcome priors. Returns `PromptPackage` per the existing pattern.
- `orchestrator/handlers.py::handle_monthly_model_review` — invoked at the end of monthly orchestration; records parsed proposals into `ProposalLedger` (`ProposalSource.STRUCTURAL_EXPERIMENT`) + `SuggestionTracker`; when selected, writes `StrategyChangeRecord(record_type=proposed_change)`.

**Tests**: validator rejects structural proposals without evidence paths; parser handles both `<!-- STRUCTURED_OUTPUT -->` and ` ```json ` fences (existing `response_parser.py` behavior); high-risk classification triggers stricter caps.

**Acceptance**: no actionable trading change without `evidence_paths`; model output remains machine-readable; structural proposals are grounded in replay-attributed failure modes.

---

## Phase 9 — Outcome Measurement Replacement

**Create**:
- `schemas/monthly_verdict.py` — `MonthlyVerdict(strategy_change_id, window, replay_objective, live_objective, delta_vs_expected, attribution: GapAttribution, decision ∈ {keep, watch, rollback, quarantine, repair}, evidence_paths, outcome_source ∈ {monthly, follow_up}, measured_at)`.
- `skills/monthly_outcome_measurer.py` — for each `StrategyChangeRecord(record_type=deployed_change)`, compute the one-month verdict at the next monthly validation; schedule three-month / minimum-trade follow-up via APScheduler `date` triggers; persist verdicts to `StrategyChangeLedger`, write a back-link `ProposalOutcome` into `ProposalLedger`, and call `SuggestionTracker.mark_measured(..., source="monthly")`.

**Modify**:
- `skills/suggestion_tracker.py::mark_measured` — change signature to `mark_measured(self, suggestion_id: str, source: Literal["early_warning", "monthly", "follow_up"] = "early_warning") -> None`. Persist `outcome_source` on the suggestion record. All call sites: `AutoOutcomeMeasurer` keeps default `"early_warning"`; the new monthly path passes `"monthly"`/`"follow_up"`.
- `schemas/suggestion_tracking.py::SuggestionRecord` — add optional `outcome_source: str | None = None` plus `outcome_source_history: list[dict] = []` (timestamped transitions).
- `skills/auto_outcome_measurer.py::measure_progressive` — accept an optional `suggestion_record: SuggestionRecord` parameter (or a `risk_tier`/`change_kind` lookup). When the suggestion is tied to a deployed change with `risk_tier ≥ medium` (looked up via `SuggestionTracker.get_by_id`), still write the `OutcomeMeasurement` to `outcomes.jsonl` but tag it `outcome_source = "early_warning"` and **do not call `mark_measured`** — leave that to monthly. For low-risk suggestions the existing behavior is preserved.
- `analysis/context_builder.py` — `load_monthly_verdicts()`, `load_follow_up_verdicts()` injected into `base_package()`. Update `load_outcome_measurements` to expose `outcome_source` in its returned dicts.
- `skills/forecast_tracker.py`, `skills/prediction_tracker.py`, `skills/suggestion_scorer.py` — when computing accuracy/win-rate aggregates, weight `monthly`/`follow_up` outcomes more heavily than `early_warning` (or filter to monthly+follow_up only for material decisions).

**Tests**:
- Medium+ risk suggestion is not finalized by weekly measurer (no `MEASURED` status transition).
- One-month verdict written by the monthly measurer transitions the suggestion to `MEASURED` with `outcome_source="monthly"`.
- Three-month follow-up can overturn the primary verdict (write a new `MonthlyVerdict` with `outcome_source="follow_up"` and update `StrategyChangeRecord.follow_up_verdict`).
- Back-compat: existing `outcomes.jsonl` entries with no `outcome_source` are read as `"early_warning"`.

**Acceptance**: material strategy/config changes are not finalized by 7/14/30-day daily-summary checks; the monthly verdict is the primary verdict; multi-month follow-up confirms or overturns; downstream consumers can distinguish source.

---

## Phase 10 — Operational Feedback Controls

**Create**:
- `schemas/outcome_priors.py` — `OutcomePriors(strategy_id, regime, mutation_family, n_positive, n_negative, n_inconclusive, prior_score: float, source_breakdown: dict, last_updated)`.
- `skills/outcome_prior_layer.py` — aggregates `MonthlyVerdict`s by `(mutation_family, strategy_id, regime)`; computes `prior_score ∈ [-1, +1]`; exports priors consumed by smoke-repair (rollback ordering), phased-auto (phase ordering, perturbation neighborhoods), monthly model-review prompts. Storage: `memory/findings/outcome_priors.jsonl`.

**Modify**:
- `skills/suggestion_scorer.py` — distinguish `outcome_source` when computing per-`(bot_id, category)` win rates; expose `monthly_only_scorecard` and `combined_scorecard`.
- `analysis/response_validator.py` — tighten confidence caps for categories with repeated negative monthly outcomes (use `monthly_only_scorecard`).
- `analysis/context_builder.py` — `load_outcome_priors()` injected into daily/weekly/monthly/discovery prompts.
- `skills/phased_auto.py` + `skills/smoke_repair.py` — read priors to order candidate evaluation and rollback evaluation.
- `skills/parameter_searcher.py` — accept optional `priors: OutcomePriors` to seed search neighborhoods toward historically productive perturbations.

**Tests**: priors persist across runs; failing mutation family is deprioritized in next phased-auto run; successful family receives bounded preference; validator caps confidence when priors are negative.

Rules:
- positive priors strengthen only after a monthly positive plus persistence confirmation, or high-confidence minimum-trade evidence;
- positive priors increase allocation toward the specific mutation family and strategy context, but never loosen hard safety gates;
- negative priors apply immediately when one-month attribution is strong;
- repeated negative categories require stricter evidence, higher confidence thresholds, and earlier rollback/quarantine consideration.

**Acceptance**: outcomes change the **next run's candidate space**, not only prompt text.

---

## Phase 11 — Approval, Deployment, Rollback Integration

**Modify**:
- `schemas/autonomous_pipeline.py::ApprovalRequest` — add `evidence_paths: list[str] = []`, `objective_deltas: dict[str, float] = {}`, `attribution_summary: str = ""`, `rollback_plan: str = ""`, `linked_strategy_change_id: str | None = None`. Existing fields (`request_id`, `suggestion_id`, `risk_tier`, `change_kind`, `pr_url`, `status`, `approval_count`) preserved.
- `skills/approval_tracker.py::create_request` — when `risk_tier ∈ {medium, high}`, require non-empty `evidence_paths`, `objective_deltas`, `rollback_plan`; reject creation otherwise with a clear error.
- `orchestrator/handlers.py` approval flow + `comms/renderers/*` — include replay evidence + objective deltas + linked `StrategyChangeRecord` in approval messages.
- `skills/deployment_monitor.py::mark_deployed` and `record_post_deploy_metrics` — write back `commit_sha`, `deployment_id`, `config_version`, `strategy_version` into the matching `StrategyChangeRecord` (`record_deployed_change`).
- `skills/approval_handler.py::handle_approve` — on approval, create the `StrategyChangeRecord(record_type=proposed_change)`. On PR merge (signaled via `DeploymentMonitor`), transition to `deployed_change`.

**Create**:
- `schemas/rollback_thresholds.py` — `RollbackThresholds(drawdown_breach_pct, monthly_verdict_decision, early_warning_anomaly_z, ...)` versioned and stored at `memory/policies/v1/rollback_thresholds.yaml`.
- `skills/rollback_advisor.py` — pre-defined risk thresholds (drawdown breach, monthly verdict `rollback`/`quarantine`, early-warning anomaly z-score). Emits emergency rollback recommendations; appends `StrategyChangeRecord(record_type=rollback, rollback_status=recommended)`; still human-approved through `ApprovalTracker.create_request` with `change_kind="rollback"`.

**Tests**: missing evidence paths block approval creation for medium+ risk; deployment writeback updates `StrategyChangeRecord`; rollback advisor fires on threshold breach and creates approval request; approval-handler creates linked `StrategyChangeRecord`.

**Acceptance**: no material deployment without lineage fields; rollback advice is auditable; human approval required for all trading behavior changes (including rollbacks).

---

## Phase 12 — Tests, Dry Runs, Migration

**Tests** (added on top of the existing 3154):
- Unit: new schemas (`coverage_manifest`, `run_manifest`, `parity_report`, `strategy_change_ledger`, `monthly_verdict`, `outcome_priors`, `lineage_audit`, `gap_attribution`, `rollback_thresholds`) and `StructuralProposal` extension.
- Replay parity per strategy plugin under `tests/fixtures/replay_parity/<strategy>/`.
- Golden monthly validation: fixture month → expected `StrategyChangeRecord(monthly_review)` + `GapAttribution`.
- Smoke-repair: known-harmful mutation → rollback selection.
- Phased-auto: known winner → passes gates.
- Integration: proposal → approval → deployment → monthly verdict → priors update → next-run candidate ordering shifts.
- Back-compat: existing JSONL files (`suggestions.jsonl`, `outcomes.jsonl`, `proposal_ledger.jsonl`) without new fields still parse.

**Dry runs**:
- `--shadow` flag on `monthly_runner` and `handle_monthly_validation`: writes all artifacts but does **not** enqueue approvals or update production-facing context (the new `load_*` methods read shadow-tagged ledger entries only when the env flag is set).
- Run at least one full monthly cycle in shadow on a single strategy/bot before enabling approval routing.

**Migration**:
- `docs/migration/wfo-to-monthly.md` — how legacy WFO outputs map to monthly artifacts; deprecation timeline; what parts of `WFORunner` are reused as shared utilities (`fold_generator`, `cost_sensitivity`, `robustness_tester`, `leakage_detector`).
- `docs/migration/outcome-measurer-to-monthly.md` — cutover; existing `outcomes.jsonl` entries are reclassified to `outcome_source="early_warning"` on read; new entries carry the field.
- `docs/migration/structural-proposal-extension.md` — required new fields, validator behavior, model prompt updates.
- Per-bot rollout checklist: replay adapter live → parity passes → shadow month → approval-gated month → multi-month follow-up.

**Acceptance**: at least one full monthly cycle runs in shadow end-to-end; every artifact has provenance + objective version; failures block authoritative verdicts.

---

## Strategy Rollout Gate

Start with one strategy family that has reliable market data, clean production config lineage, a full-fidelity replay engine, sufficient trade count, and a passing parity audit. A strategy becomes approval-gated only after it completes at least one shadow monthly cycle with valid artifacts and a defensible no-change/watch/repair decision.

Strategies remain diagnostics-only when market data is unavailable, the replay plugin is missing, replay parity fails, lineage is insufficient, or the latest month is too sparse for a verdict. Diagnostics-only still supports daily/weekly anomaly detection, telemetry gap detection, process-quality monitoring, under-trading hypotheses, data-collection recommendations, and non-actionable model-reviewed structural hypotheses.

---

## Critical File Map

**New (this repo)**:
- `docs/adr/0001-monthly-authoritative-loop.md`, `docs/adr/0002-backtest-repo-boundary.md`, `docs/adr/0003-objective-canonicalization.md`
- `docs/migration/{wfo-to-monthly,outcome-measurer-to-monthly,structural-proposal-extension}.md`
- `schemas/{coverage_manifest, telemetry_manifest, run_manifest, parity_report, strategy_change_ledger, monthly_verdict, outcome_priors, lineage_audit, gap_attribution, rollback_thresholds, smoke_repair_result, phased_auto_result}.py`
- `skills/{market_data_sync, market_data_catalog, coverage_manifest_writer, strategy_change_ledger, parity_runner, smoke_repair, phased_auto, monthly_outcome_measurer, outcome_prior_layer, rollback_advisor, gap_attribution, cost_sensitivity (extracted from WFORunner)}.py`
- `analysis/{replay_adapter, monthly_prompt_assembler, monthly_repair_prompt_assembler}.py`
- `orchestrator/{monthly_runner, lineage_audit}.py`
- `memory/policies/v1/rollback_thresholds.yaml`

**Modify (with rough line/area refs)**:
- `schemas/events.py` — add `lineage_summary` to `DailySnapshot`. **Do not add** lineage to `TradeEvent`/`MissedOpportunityEvent` (already present at lines 218-226, 273-281).
- `schemas/bot_config.py::BotConfig` — add `strategy_version`, `config_version`, `code_sha`.
- `schemas/deployment_monitoring.py::DeploymentRecord` — add `experiment_id`, `code_sha`.
- `schemas/agent_response.py::StructuralProposal` — extend with monthly-loop fields (Phase 8).
- `schemas/suggestion_tracking.py::SuggestionRecord` — add `outcome_source`, `outcome_source_history`.
- `schemas/autonomous_pipeline.py::ApprovalRequest` — add `evidence_paths`, `objective_deltas`, `attribution_summary`, `rollback_plan`, `linked_strategy_change_id`.
- `skills/run_wfo.py` — legacy docstring; extract cost-sensitivity helpers into `skills/cost_sensitivity.py`.
- `skills/auto_outcome_measurer.py::measure_progressive` — gate by risk tier; tag `outcome_source="early_warning"`; do not finalize medium+ risk.
- `skills/suggestion_tracker.py::mark_measured` — add `source` parameter.
- `skills/suggestion_scorer.py` — monthly-vs-early-warning weighting.
- `skills/forecast_tracker.py`, `skills/prediction_tracker.py` — same.
- `skills/deployment_monitor.py::mark_deployed`, `record_post_deploy_metrics` — write back to `StrategyChangeLedger`.
- `skills/approval_handler.py::handle_approve` — create `StrategyChangeRecord(proposed_change)`.
- `skills/approval_tracker.py::create_request` — require evidence for medium+ risk.
- `skills/parameter_searcher.py::search` — accept optional priors.
- `analysis/context_builder.py` — add `load_strategy_change_ledger`, `load_monthly_verdicts`, `load_follow_up_verdicts`, `load_outcome_priors`; surface `outcome_source` in `load_outcome_measurements`.
- `analysis/response_validator.py::_validate_structural_proposals` — require `evidence_paths` for structural proposals routed to deterministic systems.
- `analysis/{daily_prompt_assembler, weekly_prompt_assembler, wfo_prompt_assembler, discovery_prompt_assembler}.py` — surface strategy-change ledger + outcome priors.
- `orchestrator/scheduler.py::SchedulerConfig` + `build_scheduled_job_specs` — add `market_data_sync_*`, `monthly_validation_*`, `monthly_follow_up_*` fields and jobs via `_append_cron_specs`.
- `orchestrator/handlers.py` — `handle_market_data_sync`, `handle_monthly_validation`, `handle_monthly_model_review`; enrich approval flow.
- `orchestrator/app.py` — wire new handler slots; pass new dependencies; long-running monthly run via existing `SubagentManager`.
- `orchestrator/config.py::AppConfig` — `market_data_root`, `backtest_repo_path`, `backtest_artifact_root`, `monthly_validation_enabled`; read in `from_env`.
- `orchestrator/memory_consolidator.py` — `consolidate_strategy_changes()`.
- `orchestrator/config.py::AppConfig` ??also include `monthly_validation_mode`, `backtest_command_timeout_seconds`, `backtest_max_parallel_strategies`, and `market_data_required_coverage_ratio`.
- `orchestrator/lineage_audit.py` (new) wired into the scheduler.
- `comms/renderers/*` — approval messages include evidence paths and objective deltas.
- `skills/build_daily_metrics.py` — populate `DailySnapshot.lineage_summary`.
- `.env.example`, `CLAUDE.md`, `memory/policies/v1/soul.md`.

## Reused Existing Utilities

- `ProposalLedger` (`skills/proposal_ledger.py`) — pattern template for `StrategyChangeLedger`. Continues to hold all candidate provenance including rejected. Monthly verdicts also write a back-link `ProposalOutcome` here.
- `SuggestionTracker` (`skills/suggestion_tracker.py`) — lifecycle preserved; `mark_measured` gains a `source` parameter; record gains `outcome_source`.
- `ApprovalTracker` + `ApprovalHandler` — payload enriched, no schema break; existing PR/branch workflow reused.
- `DeploymentMonitor` (`skills/deployment_monitor.py`) — `create_deployment`, `mark_deployed`, `check_regression` keep working; ledger-writeback added.
- `HypothesisLibrary` (`skills/hypothesis_library.py`) — monthly verdicts feed `record_outcome`.
- `ForecastTracker`, `PredictionTracker` — continue receiving structured outputs; weight monthly verdicts heavier.
- `LearningCycle` + `LearningLedger` — weekly cadence preserved; monthly is downstream.
- `ContextBuilder.base_package()` — extension via new `load_*` methods.
- `ResponseParser` + `ResponseValidator` — `StructuralProposal` extension only; existing parsing unchanged.
- `MemoryConsolidator` — gains `consolidate_strategy_changes()`.
- `SubagentManager` (`orchestrator/subagent.py`) — invokes replay adapter as a long-running subagent.
- `EventStream` (`orchestrator/event_stream.py`) — emit `market_data_sync_done`, `monthly_validation_progress`, `parity_audit_result`, `rollback_recommendation`.
- `RunIndex`/`scheduled_runs` — captures monthly run lifecycle.
- `WFORunner` building blocks (`_run_cost_sensitivity`, `_cost_safety_flags`, `_run_folds`, robustness, leakage detection) — extracted to shared utilities where useful, original WFO path preserved as legacy/screening.
- `ParameterSearcher._composite_score` — reference composite-score implementation for phased-auto and smoke-repair candidate ranking.
- `BacktestSimulator` — kept for current screening uses; replaced by full-fidelity engine in `trading_backtests` for monthly verdicts.

## Suggested Build Order

P0 → P1 (can parallel with P3) → P2 → P3 → P4 (parity for first strategy family only) → P5 (shadow mode) → P6 → P7 → P8 → P9 → P10 → P11 → P12. Roll out strategy by strategy.

## Verification — End-to-End

1. `pytest tests/` — current 3154 plus new tests pass.
2. Trigger a shadow monthly run on one bot:
   `python -m orchestrator.scheduler --run-now monthly_validation --bot k_stock_trader --shadow`
3. Inspect `BACKTEST_ARTIFACT_ROOT/k_stock_trader/<YYYY-MM>/`: coverage manifest, run manifest, incumbent validation, parity report present; candidates produced only if repair needed.
4. Confirm `memory/findings/strategy_change_ledger.jsonl` has a `monthly_review` record with linked `proposal_id`s and `suggestion_id`s.
5. Verify the next daily/weekly run's `ContextBuilder.base_package()` includes `strategy_change_history` and `outcome_priors`.
6. Run a harmful-mutation fixture; confirm smoke-repair selects rollback; confirm an approval request is generated with non-empty `evidence_paths` and `objective_deltas`; confirm a `StrategyChangeRecord(proposed_change)` exists with `record_type` linked to the approval.
7. After the following month, confirm a `MonthlyVerdict` is written and linked back to the `StrategyChangeRecord`; confirm `outcome_source="monthly"`; confirm `outcome_prior_layer` updates the next run's candidate ordering.
8. Confirm `AutoOutcomeMeasurer` runs still write to `outcomes.jsonl` but tagged `outcome_source="early_warning"` and do not call `mark_measured` for medium+ risk suggestions.
9. Confirm `ApprovalTracker.create_request` rejects a medium-risk request that lacks evidence paths.
10. Confirm `DeploymentMonitor.mark_deployed` writes `commit_sha`/`deployment_id`/`config_version`/`strategy_version` back into the `StrategyChangeRecord`.
