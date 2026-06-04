# Meta-Learning Loop Gap Analysis

Date: 2026-05-03

Scope: evaluate whether `trading_assistant` currently behaves like a closed learning system, with particular focus on the parameter optimization loop, the structural proposal loop, and the meta-evaluation loop that should decide what to try next.

Primary references reviewed:

- `docs/2026-04-11-learning-system-state-assessment.md`
- `docs/2026-04-22-hermes-autoagent-learning-loop-leverage-report.md`
- `docs/hermes_port.md`
- `docs/hermes_port_current_state_implementation_audit_2026-04-17.md`
- `_references/hermes-agent/`

## Executive Verdict

The repository has moved materially beyond a reporting system. It now contains many of the right closed-loop primitives: parsed LLM suggestions, parameter search, A/B experiment records, structural experiment records, live outcome measurement, hypothesis tracking, learning cards, a run index, provider scoring, generated playbooks, and a weekly `LearningCycle`.

Second-pass correction: the repository also already contains two important pieces this report must not treat as absent:

- Deployment monitoring exists in `schemas/deployment_monitoring.py`, `skills/deployment_monitor.py`, `orchestrator/app.py`, and `orchestrator/handlers.py`. The gap is not "no deployment tracking"; it is that the existing deployment record is PR/heartbeat/regression oriented and is not yet a full trading-effect manifest tied to every affected trade, experiment, parameter candidate, and diagnostic delta.
- Context budgeting exists inline in `analysis/context_builder.py::base_package()` through workflow priorities, item budgets, token budgets, and `_context_budget_manifest`. The gap is not "no context budget"; it is that the policy is embedded in `ContextBuilder` and does not yet summarize sections, coordinate memory providers, or expose a dedicated budget policy layer.

It is not yet an optimal learning system. The main problem is not the absence of components. The problem is that the components do not yet share a single evidence ledger, a single objective contract, or a causal evaluation contract. As a result, past outputs can influence future prompts, but the system cannot yet reliably answer the most important meta-learning questions:

- Did this proposal actually move live performance toward the target objective?
- Was the backtest or WFO result predictive of live behavior?
- Was the right parameter space searched in the first place?
- Did the LLM generate a structurally meaningful improvement, or a plausible but unvalidated narrative?
- What diagnostics should be added because the previous loop was under-instrumented?
- Which exact experiment should be queued next, and why is it expected to dominate the alternatives?

The current codebase is best described as "learning-capable but evidence-fragmented." The highest-impact work is to connect parameter optimization, structural experiments, WFO, live outcome measurement, and LLM meta-review through a unified proposal/evidence ledger and a shared objective function.

## Current State

### 1. Event Routing and Reliability Loops

The orchestrator has deterministic event routing, which is the right foundation for a learning system because the LLM is not responsible for deciding which loop should run.

Evidence:

- `orchestrator/orchestrator_brain.py::decide()` routes events deterministically by event type and severity.
- `orchestrator/orchestrator_brain.py::_handle_error()` sends CRITICAL errors to immediate alerting, promotes repeated HIGH errors into triage, and suppresses noisy repeats.
- `orchestrator/handlers.py::handle_triage()` builds an error context, runs `skills/run_bug_triage.py::TriageRunner`, invokes an agent, parses repair proposals, and records reliability interventions.
- `skills/reliability_tracker.py` records interventions, recurrences, verification status, and chronic reliability patterns.
- `orchestrator/app.py::_verify_reliability()` periodically verifies interventions and creates chronic reliability hypotheses.

Assessment:

This is a real self-monitoring loop for software reliability. It is stronger than the trading-performance loop because it has explicit recurrence detection and verification. The equivalent trading loop still lacks equally strong causal attribution and experiment lineage.

### 2. Parameter Optimization Loop

The system has a parameter suggestion path, a greedy local search path, a route-to-approval-or-experiment path, and a live outcome calibration path.

Current flow:

1. LLM or deterministic strategy logic proposes a parameter change.
2. `skills/autonomous_pipeline.py::_build_parameter_request()` resolves the suggestion to a registered tunable parameter.
3. `skills/config_registry.py::resolve_suggestion_to_params()` maps the suggestion to a `ParamSpec` using bot/category filters and keyword matching.
4. `skills/config_registry.py::validate_value()` checks bounds and allowed values.
5. `skills/parameter_searcher.py::search()` performs a greedy search around the current/proposed value.
6. `skills/parameter_searcher.py::_evaluate_candidate()` runs a simplified backtest, robustness split, and 1.5x cost sensitivity test.
7. `skills/parameter_searcher.py::_route()` routes the result to approve, experiment, or discard.
8. `skills/autonomous_pipeline.py::_route_to_experiment()` creates an A/B `ExperimentConfig` through `skills/experiment_config_generator.py`.
9. `skills/experiment_manager.py` stores, activates, ingests, analyzes, and concludes experiments.
10. `skills/backtest_calibration_tracker.py` records predicted improvement and later outcome correctness.
11. `skills/auto_outcome_measurer.py::measure()` estimates post-implementation live outcomes and feeds calibration.

Key implementation details:

- `skills/parameter_searcher.py::_build_grid()` builds a small local grid around the current/proposed value. Numeric parameters use an approximate +/-30 percent neighborhood; categorical parameters test allowed values.
- `skills/parameter_searcher.py::_composite_score()` uses ratio-based Calmar, profit factor, drawdown, Sharpe, and trade-count components.
- `schemas/parameter_search.py::ParameterSearchReport` stores only summary fields such as `baseline_composite`, `best_composite`, `candidates_tested`, and `exploration_summary`.
- `data/bot_configs/k_stock_trader.yaml` shows the registered parameter universe: `quality_min_threshold`, `or_range_max`, `rsi_min`, `rsi_max`, `volume_ratio_min`, `atr_filter_mult`, `max_spread_pct`, `max_positions`, `base_risk_pct`, `daily_stop_r`, and `heat_cap_r`.

Assessment:

This is the closest thing to a closed optimization loop in the repository. It is useful, but still too narrow for the mission. It optimizes only parameters that are already in the registry, uses a simplified simulator, stores only summary search evidence, and does not yet meta-evaluate whether the candidate parameter universe itself is right.

### 3. WFO and Autoresearch Loop

The WFO/autoresearch path exists but is not fully connected to the same closed-loop machinery as normal suggestions.

Evidence:

- `skills/run_wfo.py::WFORunner.run()` generates folds, optimizes parameters per fold, creates consensus parameters, aggregates out-of-sample metrics, runs cost sensitivity, audits leakage, sets safety flags, and returns a recommendation.
- `skills/param_optimizer.py::optimize()` performs grid search and chooses the best parameter set by the configured objective metric.
- `skills/param_optimizer.py::_objective_value()` optimizes one metric at a time: Sharpe, Sortino, Calmar, or Profit Factor.
- `orchestrator/handlers.py::handle_wfo()` loads WFO config/trades, runs the WFO runner, writes JSON and Markdown reports, invokes an LLM review, and notifies the user.

Assessment:

WFO is currently a strong analysis/reporting path, not a fully closed learning path. It does not automatically create proposal ledger entries, A/B experiments, `DeploymentRecord` entries, live outcome measurements, or calibration records. In practice, this means WFO can identify candidate parameters, but the system does not consistently learn whether WFO-derived changes outperform other proposal sources.

### 4. Discovery and New Strategy Ideation

The system already has an explicit discovery path for patterns outside the deterministic detector set, including the ability to propose genuinely new strategies.

Evidence:

- `analysis/discovery_prompt_assembler.py::_DISCOVERY_INSTRUCTIONS` tells the discovery agent to search raw trade files for patterns not covered by 25 automated detectors.
- The same prompt schema includes `discoveries`, `strategy_ideas`, and `structural_proposals`.
- `orchestrator/handlers.py::handle_discovery_analysis()` invokes the discovery agent with file access, persists discoveries to `memory/findings/discoveries.jsonl`, adds sufficiently confident discoveries to `HypothesisLibrary`, persists strategy ideas to `memory/findings/strategy_ideas.jsonl`, and records high-confidence strategy ideas as `structural_experiment_tracker` records.
- `analysis/context_builder.py::load_strategy_ideas()` loads active strategy ideas back into later prompt packages.
- `analysis/weekly_prompt_assembler.py` tells the weekly agent to assess active strategy ideas and avoid duplicating them.
- `skills/structural_analyzer.py::compute()` deterministically analyzes strategy lifecycle phase, architecture mismatches, filter ROI, and proposed structural changes.

Assessment:

This is a major existing capability for structural improvement and new-strategy discovery. The remaining gap is that strategy ideas and deterministic structural proposals still join the same weak evaluation path as other structural experiments: they can be recorded with acceptance criteria, but they are not yet linked through a unified proposal ledger, causal live attribution, the existing deployment-monitoring records, or lifecycle-stage-specific diagnostics.

### 5. Structural Improvement Proposal Loop

The system can parse, validate, store, and later evaluate structural proposals.

Evidence:

- `schemas/agent_response.py::StructuralProposal` captures `hypothesis_id`, linked suggestion, file changes, verification commands, acceptance criteria, confidence, and expected impact.
- `analysis/response_parser.py::parse_response()` extracts `predictions`, `suggestions`, `structural_proposals`, and `portfolio_proposals` from structured JSON or markdown fallback.
- `analysis/response_validator.py::_validate_structural_proposals()` rejects or gates structural proposals using hypothesis track record, category track record, marginal track record, confidence, acceptance-criteria validity, and calibration constraints.
- `orchestrator/handlers.py::_record_structural_experiments()` turns accepted structural proposals with criteria into `schemas/structural_experiment.py::ExperimentRecord`.
- `skills/structural_experiment_tracker.py` records, activates, resolves, and summarizes structural experiments.
- `orchestrator/app.py::_check_experiments()` periodically evaluates structural experiments against `GroundTruthComputer` snapshots.
- `skills/approval_handler.py` activates linked structural experiments when approved suggestions are implemented.

Assessment:

This is a meaningful structural-proposal loop. The most important gap is causal strength. Current structural evaluation compares a bot-level ground-truth snapshot at activation date with a current snapshot. That is useful for broad monitoring, but insufficient to quantitatively validate structural changes that may be confounded by regime changes, concurrent parameter changes, market volatility shifts, or unrelated bug fixes.

There are also wiring risks. `orchestrator/app.py::_check_experiments()` returns immediately when `experiment_manager is None`, and `build_scheduled_job_specs()` only schedules `experiment_check_fn` when `experiment_manager` exists. Since `StructuralExperimentTracker` is created independently of A/B testing, structural experiment evaluation is effectively coupled to the A/B feature flag. Separately, `AutonomousPipeline._route_to_experiment()` uses `_experiment_tracker.get_active_experiments()` for the active-experiment cap, while `orchestrator/app.py` wires `_experiment_tracker` to `StructuralExperimentTracker` and persists A/B configs through `ExperimentManager`. That split means structural and A/B experiment accounting can diverge.

### 6. Outcome Measurement and Calibration

The codebase has an explicit post-implementation measurement layer.

Evidence:

- `skills/auto_outcome_measurer.py::measure()` computes before/after windows, regime-matched comparison, volatility context, concurrent changes, macro stability, measurement quality, significance, and verdict.
- `schemas/outcome_measurement.py::OutcomeMeasurement` stores before/after PnL, win rate, drawdown, trade counts, regime controls, concurrent changes, provider attribution, significance, and quality.
- `schemas/outcome_measurement.py::OutcomeMeasurement.verdict` refuses to classify insufficient samples and only emits positive/negative/neutral when quality is high or medium.
- `skills/backtest_calibration_tracker.py::get_approval_modifier()` can fast-track or require experiments based on historical prediction reliability.

Assessment:

This is a good start. The gap is that the measured outcome is not consistently tied back to the exact proposal, exact candidate set, exact WFO fold evidence, exact deployment manifest, exact live exposure, and exact diagnostic deltas. This weakens the "loop-of-loops" because the weekly `LearningCycle` receives many artifacts, but not a canonical evidence graph.

### 7. Deployment Monitoring

Deployment monitoring exists and should be extended rather than replaced.

Evidence:

- `schemas/deployment_monitoring.py::DeploymentRecord` tracks deployment ID, approval request, suggestion ID, PR URL, bot ID, parameter changes, merge/deploy timestamps, pre/post metrics, regression status, and rollback PR URL.
- `skills/deployment_monitor.py::DeploymentMonitor` creates deployment records, checks PR merge status, records pre/post metrics, confirms deployment from heartbeat, detects regressions, marks stale deployments, and can create rollback PRs.
- `orchestrator/app.py` creates a deployment record after an approval callback when a PR is created.
- `orchestrator/handlers.py::_check_deployments()` moves deployments through pending merge, merged, deployed, regression detected, rollback, and monitoring complete states.
- `schemas/suggestion_tracking.py` and `skills/suggestion_tracker.py` already carry `deployment_id`.

Assessment:

This is an important existing safety loop. It is not yet the same as the deployment manifest needed for learning attribution. The current record is parameter-change and PR lifecycle oriented; it does not include code hash/config hash/strategy registry hash as first-class fields, does not link every affected trade or signal candidate to `deployment_id`, and does not feed a causal outcome evaluator with affected-population diagnostics.

### 8. Learning Cycle and Meta-Evaluation

The repository has an explicit weekly meta-learning cycle.

Evidence:

- `skills/learning_cycle.py::run()` creates ground-truth snapshots, synthesizes retrospectives, updates hypothesis lifecycle, recalibrates suggestion categories, compiles benchmark cases, scores providers, runs harness evaluation, generates playbooks, selects next experiments, and records a ledger entry.
- `skills/learning_cycle.py::_select_next_experiments()` selects experiments from positive-effectiveness active hypotheses while avoiding discarded categories and recent failed combinations.
- `skills/learning_ledger.py::record_week()` stores weekly learning state.
- `skills/learning_ledger.py::compute_cycle_effectiveness()` combines improvement magnitude, conversion rate, outcome quality, and lesson yield.
- `skills/benchmark_compiler.py::compile()` creates benchmark cases from validation blocks, negative outcomes, calibration misses, and transfer failures.
- `skills/harness_eval_runner.py` scores prompt variants over benchmark cases.
- `skills/provider_route_scorer.py::recommend_provider()` can select a provider when sufficient samples and score gap exist.
- `orchestrator/agent_preferences.py::_resolve_learned_selection()` integrates provider route scoring into runtime selection.
- `skills/playbook_generator.py` writes generated playbooks into `memory/playbooks/generated`.
- `analysis/context_builder.py::base_package()` loads learning cards, search reports, backtest reliability, playbooks, prior runs, hypothesis track records, outcomes, validation patterns, and learning-ledger summaries into prompt packages.
- `orchestrator/invocation_builder.py::build_full_prompt()` includes memory blocks and generated playbooks in the actual runtime prompt.
- `orchestrator/run_index.py` indexes past runs in SQLite FTS5.
- `skills/learning_card_store.py` ranks learning cards by recency, impact, confidence, retrieval feedback, and context match.

Assessment:

The meta-learning scaffolding is substantial. The weak point is that several meta-evaluation artifacts are proxies rather than evidence-backed measurements. For example, `skills/harness_eval_runner.py::_score_case()` uses fixed heuristics rather than replaying real prompts through candidate providers or prompt variants. `skills/benchmark_compiler.py` focuses on failures and misses but does not yet include positive exemplars, high-value missed opportunities, or cases where the system correctly rejected a bad idea. `skills/learning_cycle.py::_record_selected_experiments()` records selected experiments without full acceptance criteria, which means a selected next experiment is not necessarily evaluable.

## Critical Gaps Ranked by Impact

### P0: Partial Shared Weights Exist, But There Is No Unified Objective Contract Across Loops

Different subsystems optimize or score different objectives.

Evidence:

- `schemas/objective_weights.py` already centralizes the six ground-truth weights and documents the intentional divergence between GroundTruth, ParameterSearcher, and WFO scoring.
- `schemas/objective_weights.py::ratio_to_unit_scale()` exists for normalizing a parameter-search ratio for display or logging.
- `skills/param_optimizer.py::_objective_value()` optimizes a single configured metric such as Sharpe or Calmar.
- `skills/parameter_searcher.py::_composite_score()` uses a ratio-based composite score.
- `skills/auto_outcome_measurer.py::_estimate_composite_delta()` approximates composite delta and explicitly does not use `GroundTruthComputer`.
- `schemas/objective_weights.py` documents that GroundTruth, ParameterSearcher, and ParamOptimizer scores must not be compared directly.

Impact:

The system has a shared weight source, but not a unified objective contract. It still cannot reliably rank a WFO parameter, a greedy parameter suggestion, a structural proposal, and a live outcome against the same target because each subsystem records a different score scale and evaluation context. This is the central blocker to optimal meta-learning.

Target:

Create `schemas/learning_objective.py` with a versioned `LearningObjective`, `ObjectiveComponent`, and `ObjectiveScore`. All proposal evaluation paths should record the objective version, component scores, uncertainty, and constraints used at evaluation time.

### P0: WFO Results Are Not Closed-Loop Learning Objects

Evidence:

- `orchestrator/handlers.py::handle_wfo()` writes reports and invokes LLM review, but does not route WFO candidates into `SuggestionTracker`, `ExperimentManager`, `BacktestCalibrationTracker`, or `AutoOutcomeMeasurer`.
- `skills/run_wfo.py::write_output()` writes `wfo_report.json` only.

Impact:

The highest-quality parameter optimization engine can produce recommendations that remain outside the normal evidence, experiment, and outcome loop.

Target:

Add `skills/wfo_result_integrator.py` to convert WFO results into proposal ledger entries, A/B experiments, deployment candidates, and calibration predictions.

### P0: Structural Evaluation Is Too Weak for High-Value Code or Strategy Changes

Evidence:

- `orchestrator/app.py::_check_experiments()` evaluates structural experiments by comparing bot-level `GroundTruthComputer` snapshots at activation and current dates.
- `skills/auto_outcome_measurer.py::_find_concurrent_changes()` detects concurrent changes, but structural experiment resolution does not yet use the same level of causal controls.
- `orchestrator/app.py` only schedules the experiment check job when `experiment_manager` exists, so structural evaluation is coupled to A/B testing even though `StructuralExperimentTracker` is independent.

Impact:

A structural change can appear good or bad because of market regime, volatility, concurrent parameter changes, data quality, or unrelated bug fixes. This can teach the LLM the wrong lesson.

Target:

Create `skills/causal_outcome_evaluator.py` for structural changes. It should extend the existing deployment-monitoring path by requiring a learning-grade deployment manifest: affected strategies, eligible trade population, code/config/strategy versions, counterfactual baseline, live exposure, concurrent-change controls, and per-lifecycle diagnostic deltas.

### P0: Candidate-Level Evidence Is Discarded

Evidence:

- `skills/parameter_searcher.py::search()` evaluates all candidates.
- `schemas/parameter_search.py::ParameterSearchReport` persists only summary-level fields.
- `analysis/context_builder.py::load_search_reports()` loads search summaries, not the full candidate grid, robustness profiles, or diagnostics.

Impact:

The next loop cannot learn why losing candidates failed, where the optimum appears to sit, whether the proposed value was near the edge of the search space, or whether the parameter itself is weakly connected to the objective.

Target:

Add `ParameterCandidateResult` and persist all candidate metrics, robustness splits, cost sensitivity, sample counts, and diagnostic deltas. Store them in `data/parameter_searches/*.jsonl` and feed condensed summaries into the prompt.

### P1: The System Does Not Meta-Evaluate the Parameter Search Space

Evidence:

- `skills/config_registry.py::resolve_suggestion_to_params()` relies on hand-authored parameter specs and keyword matching.
- `data/bot_configs/k_stock_trader.yaml` defines the searchable parameter universe manually.
- `skills/learning_cycle.py::_select_next_experiments()` selects from hypotheses but does not evaluate whether new parameters should be added, removed, widened, narrowed, or transformed.

Impact:

The greedy optimizer can only optimize parameters that humans or prior code made visible. The system cannot yet ask whether the most important missing control variable is absent from the optimizer.

Target:

Add `skills/search_space_evaluator.py` to review parameter search reports, WFO fold sensitivity, diagnostic bottlenecks, and structural proposals. It should emit `SearchSpaceChangeProposal` objects: add parameter, retire parameter, widen range, narrow range, change transform, split by regime, or add interaction term.

### P1: The Offline Harness Is a Heuristic Proxy

Evidence:

- `skills/harness_eval_runner.py::_score_case()` assigns scores from tags and source type rather than replaying prompts through providers or prompt variants.
- `skills/benchmark_compiler.py::compile()` creates cases, but the harness does not evaluate real LLM outputs against expected actions.

Impact:

Provider and prompt routing can be influenced by a proxy score that may not reflect actual reasoning quality.

Target:

Replace or supplement it with `skills/harness_replay_runner.py` that replays frozen benchmark cases through selected providers or prompt variants, parses outputs with `analysis/response_parser.py`, validates them with `analysis/response_validator.py`, and scores against expected decisions.

### P1: A/B Experiment Auto-Accept Has a Field Mismatch

Evidence:

- `schemas/experiments.py::ExperimentConfig` defines `source_suggestion_id`.
- `orchestrator/app.py::_check_experiments()` references `exp.suggestion_id` when trying to auto-accept an adopted treatment.
- `AutonomousPipeline._route_to_experiment()` also checks active experiment count through `_experiment_tracker`, but app wiring sets that tracker to `StructuralExperimentTracker` while A/B configs live in `ExperimentManager`.

Impact:

Parameter A/B experiments can conclude, but the associated suggestion may not be marked accepted/implemented through the intended automated path. The split between structural and A/B trackers can also make experiment caps and experiment lifecycle accounting inaccurate.

Target:

Change the auto-accept path to use `exp.source_suggestion_id`, add a regression test, and ensure the conclusion writes to the proposal ledger. Use `ExperimentManager` for A/B active counts or create a unified experiment registry that counts both structural and A/B experiments explicitly.

### P1: Parameter Search Reporting Has a Robustness Field Mismatch

Evidence:

- `schemas/parameter_search.py::CandidateResult` stores `robustness_score`, `neighborhood_stable`, safety notes, metrics, and cost sensitivity.
- `schemas/parameter_search.py::ParameterSearchReport` does not store the best candidate's `robustness_score` or the candidate list.
- `skills/autonomous_pipeline.py::_build_parameter_request()` serializes `getattr(report, "robustness_score", 0.0)` into approval notes, but `ParameterSearchReport` has no `robustness_score` field.

Impact:

The approval payload can show a zero robustness score even when the chosen candidate had nonzero robustness. More broadly, the learning loop loses the best candidate's diagnostics.

Target:

Add `best_robustness_score`, `best_cost_sensitivity_sharpe`, and optional `candidate_results` to `ParameterSearchReport`, then update approval summaries and prompt loaders.

### P1: Backtest Simulation Does Not Match the Available Diagnostics

Evidence:

- `skills/backtest_simulator.py::_filter_trades()` only handles `signal_strength_min`.
- `skills/backtest_simulator.py::_include_missed()` can include missed opportunities by `blocked_by`, but does not replay entry mechanics, trade management, or exit alternatives.
- `skills/suggestion_validator.py::_replay_with_param()` handles a small set of archetypes: threshold/signal, stop, sizing, and filter.

Impact:

The codebase collects rich event data, but the optimizer and validator cannot use most of it. This creates a mismatch between diagnosis and evaluation.

Target:

Split simulation into lifecycle modules: `signal_filter_replay`, `entry_replay`, `trade_management_replay`, and `exit_replay`. Each should emit diagnostic deltas and objective deltas.

### P1: Learning Writes Are Not Yet Coordinated Across the Whole Loop

Evidence:

- `skills/learning_write_coordinator.py` provides grouped, provenance-tracked writes.
- `orchestrator/app.py` uses it for one outcome-reasoning write path, but suggestion writes, search reports, experiments, calibration predictions, and structural records are mostly written independently.

Impact:

The learning trail can become inconsistent when a multi-artifact operation partially succeeds.

Target:

Use `LearningWriteCoordinator` as the default write path for proposal, search, experiment, outcome, hypothesis, card, and ledger writes.

### P2: Prompt Context Is Broad but Not Always Scoped Enough

Evidence:

- `analysis/context_builder.py::base_package(bot_id=...)` supports bot-scoped retrieval for learning cards and similar runs.
- The same method loads `search_reports` and `backtest_reliability` without passing `bot_id`.

Impact:

Bot-specific prompts can receive global or cross-bot evidence without clear relevance ranking.

Target:

Make every learning-memory loader accept `bot_id`, `strategy_id`, `regime`, `category`, and `lookback_days` where applicable. Require explicit `scope` metadata on all learning artifacts.

## Target Architecture

The target system should be organized around a single evidence graph:

```text
Raw events and diagnostics
  -> LifecycleDiagnosticBundle
  -> ProposalCandidate
  -> EvaluationEvidence
  -> ExperimentPlan
  -> DeploymentManifest
  -> LiveOutcomeMeasurement
  -> MetaEvaluation
  -> NextExperimentQueue
```

### Proposed Core Schemas

Add `schemas/learning_objective.py`:

- `LearningObjective`: version, target horizon, primary metric, secondary metrics, hard constraints, weights, risk limits.
- `ObjectiveScore`: objective version, component scores, composite score, confidence interval, sample size, regime coverage, data quality.

Add `schemas/proposal_ledger.py`:

- `ProposalCandidate`: source, bot, strategy, category, lifecycle stage, hypothesis, expected mechanism, affected parameters/files, acceptance criteria.
- `EvaluationEvidence`: backtest evidence, WFO evidence, structural verification, diagnostics used, missing diagnostics, objective score.
- `ExperimentPlan`: experiment type, assignment method, baseline, treatment, minimum sample, stop rules, adoption rules.
- `DeploymentManifest`: extend or wrap the existing `DeploymentRecord` with code version, config version, parameter snapshot, strategy registry version, activation timestamp, affected population, rollback marker, and event-linkage keys.
- `LearningDecision`: approve, reject, experiment, defer, request instrumentation, with reason and confidence.

Add `schemas/search_space_evaluation.py`:

- `SearchSpaceChangeProposal`: add/remove/modify parameter, range, transform, regime split, interaction, diagnostic reason, expected benefit, validation plan.

### Proposed Core Services

Add `skills/proposal_ledger.py`:

- Own the lifecycle of every parameter, WFO, structural, bug-fix, transfer, and portfolio proposal.
- Provide query APIs for `LearningCycle`, prompts, outcome measurement, and reports.

Add `skills/wfo_result_integrator.py`:

- Convert `WFOReport` into `ProposalCandidate` and `ExperimentPlan` objects.
- Record fold-level evidence and consensus-parameter evidence.
- Send eligible candidates to `ExperimentManager`.

Add `skills/meta_evaluator.py`:

- Join proposal, search, experiment, deployment, outcome, and diagnostics.
- Decide whether each loop produced reliable evidence.
- Emit next-loop actions: adopt, revert, extend experiment, add diagnostics, expand search, retire parameter, ask LLM for structural design.

Add `skills/search_space_evaluator.py`:

- Review candidate-level parameter search results.
- Detect edge optima, flat response curves, unstable parameters, regime-specific effects, and missing interaction terms.
- Generate search-space change proposals for approval.

Add `skills/diagnostic_request_planner.py`:

- Convert inconclusive outcomes into instrumentation tasks.
- Example outputs: collect `filter_decisions` for every rejected signal, add per-bar MFE/MAE trajectory, add entry intent/fill snapshots, add signal component values for skipped signals.

Add `skills/causal_outcome_evaluator.py`:

- Evaluate structural proposals with deployment manifests built from `DeploymentRecord`, affected populations, matched controls, regime controls, concurrent-change controls, and lifecycle diagnostic deltas.

Add `skills/harness_replay_runner.py`:

- Replace heuristic prompt-variant scoring with real replay against frozen benchmark cases.

## How the Three Loops Should Interconnect

### Parameter Optimization Loop

```text
Lifecycle diagnostics identify a parameter-sensitive weakness
  -> SearchSpaceEvaluator checks whether the relevant parameter exists
  -> ParameterSearcher or WFORunner evaluates candidates
  -> ProposalLedger stores candidate-level evidence
  -> ExperimentManager runs A/B or staged live rollout
  -> AutoOutcomeMeasurer measures live outcome
  -> BacktestCalibrationTracker updates predictive reliability
  -> MetaEvaluator decides adopt/revert/expand/narrow/search-next
```

Required additions:

- Persist full candidate grids.
- Link each candidate to diagnostics and objective components.
- Treat WFO output as first-class proposal evidence.
- Require live deployment manifests for implemented parameters.

### Structural Proposal Loop

```text
LLM proposes structural change with mechanism and criteria
  -> ResponseValidator checks calibration, track record, criteria, and safety
  -> ProposalLedger stores the proposal and missing diagnostics
  -> StructuralExperimentTracker records criteria and activation
  -> Implementation or PR path creates DeploymentManifest
  -> CausalOutcomeEvaluator measures affected population
  -> HypothesisLibrary records outcome
  -> MetaEvaluator updates structural category reliability
```

Required additions:

- Require every structural proposal to declare affected lifecycle stage.
- Require quantitative acceptance criteria tied to `LearningObjective`.
- Evaluate against matched controls where possible.
- Feed rejected and successful structural proposals into replay benchmarks.

### Meta-Evaluation Loop

```text
Weekly LearningCycle
  -> reads ProposalLedger, ObjectiveScore history, outcomes, diagnostics, cards, runs
  -> measures loop quality, not just trading quality
  -> asks: did our evaluation process make good decisions?
  -> queues next parameter searches, structural experiments, and instrumentation tasks
  -> updates playbooks, provider routing, prompt variants, and search-space definitions
```

Required additions:

- Include positive exemplars and missed high-value opportunities in `BenchmarkCompiler`.
- Replace heuristic harness scoring with replay.
- Record "decision correctness" for approve/reject/defer/request-instrumentation.
- Add card/playbook feedback from measured outcomes, not only suggestion overlap.

## Instrumentation Needed for Meta-Learning

The system needs instrumentation that explains not just trades, but learning decisions:

- Proposal lineage: source, prompt run, provider, model, strategy engine detector, hypothesis, linked diagnostics.
- Evaluation lineage: simulator version, objective version, WFO config version, folds, costs, data window, diagnostics used, diagnostics missing.
- Candidate lineage: every parameter candidate, score components, robustness, regime slices, cost sensitivity, failure reason.
- Deployment lineage: code hash, config hash, parameter snapshot, strategy registry version, activation time, rollback marker.
- Live exposure: number of eligible signals/trades affected by each change, not just calendar time.
- Decision correctness: did approve/reject/experiment/defer turn out to be right?
- Search-space quality: parameter sensitivity, stability, edge-hit rate, flatness, regime interaction, repeated irrelevance.

## Prioritized Implementation Plan

### Phase 0: Repair Evidence Integrity

1. Fix `orchestrator/app.py::_check_experiments()` to use `ExperimentConfig.source_suggestion_id`.
2. Decouple structural experiment evaluation from `experiment_manager` so structural experiments are checked even when A/B testing is disabled.
3. Use `ExperimentManager` or a unified experiment registry for A/B active counts instead of counting structural experiments.
4. Add candidate-level persistence to `skills/parameter_searcher.py` and `schemas/parameter_search.py`.
5. Add `best_robustness_score` to `ParameterSearchReport` and fix the approval summary field.
6. Add `LearningObjective` and migrate ParameterSearcher, WFO, outcome measurement, and ground truth reports to record objective version and component scores.
7. Make `analysis/context_builder.py` pass `bot_id` into `load_search_reports()` and `load_backtest_reliability()`.
8. Route all multi-artifact writes through `skills/learning_write_coordinator.py`.

### Phase 1: Close WFO Into the Learning Loop

1. Add `skills/wfo_result_integrator.py`.
2. Convert WFO consensus parameters into proposal ledger entries.
3. Create experiment plans automatically for safe WFO candidates.
4. Record WFO fold-level predictions in `BacktestCalibrationTracker`.
5. Add WFO outcome cards after live measurement.

### Phase 2: Build the Proposal Evidence Ledger

1. Add `schemas/proposal_ledger.py` and `skills/proposal_ledger.py`.
2. Migrate suggestion, structural experiment, WFO, transfer, and portfolio proposal records into the ledger.
3. Add query APIs for prompts, reports, outcome measurement, and the weekly `LearningCycle`.
4. Add tests that every accepted/implemented proposal has evidence, deployment, and outcome links or an explicit "not yet measurable" reason.

### Phase 3: Strengthen Structural Causality

1. Extend `schemas/deployment_monitoring.py::DeploymentRecord` or add a linked `DeploymentManifest` wrapper for implemented structural and parameter changes.
2. Add `skills/causal_outcome_evaluator.py`.
3. Evaluate structural outcomes by affected trade population and matched control, not just whole-bot before/after.
4. Require structural proposals to specify lifecycle stage: signal, entry, trade management, exit, portfolio, execution, data, reliability.

### Phase 4: Meta-Learn the Search Space

1. Add `skills/search_space_evaluator.py`.
2. Detect missing parameters from diagnostics and repeated structural proposals.
3. Detect poor parameters from flat/unstable candidate response curves.
4. Generate `SearchSpaceChangeProposal` objects and route them through approval.
5. Feed accepted search-space changes into `ConfigRegistry`.

### Phase 5: Replace Proxy Harness Evaluation

1. Add replay cases with prompt package, expected decision, validation reason, and outcome result.
2. Run real provider/prompt variants through parser and validator.
3. Score outputs on expected action, calibration, evidence use, safety, and measurable outcome.
4. Feed results into `ProviderRouteScorer` and prompt/playbook generation.

## Definition of Done

The meta-learning loop should be considered closed when the system can produce, for each weekly cycle:

- A ranked list of parameter, structural, and instrumentation experiments queued next.
- A quantitative explanation of why each experiment was selected.
- A measurement of prior proposal decision correctness.
- A measurement of backtest/WFO predictive reliability by bot, strategy, regime, and category.
- A search-space quality report: added, removed, widened, narrowed, split, or retired parameters.
- A structural proposal outcome report with causal controls and affected-population metrics.
- A prompt/provider/playbook update report tied to replay results or measured live outcomes.
- A unified objective history showing whether the system is moving toward expected return, risk-adjusted return, drawdown control, and live robustness.

Until those artifacts exist, the repository should be treated as a sophisticated reporting and learning-assist system rather than a fully closed trading meta-learning system.
