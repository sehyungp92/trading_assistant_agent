# Unified Learning System Improvement Plan

Date: 2026-05-03

Purpose: merge the three lens-specific reports into one comprehensive plan for making `trading_assistant` operate as a synergistic learning system. This report describes how the current components should work together, what already exists, what is missing, and how to prioritize implementation so past outputs measurably improve future trading performance.

Source reports merged:

- `docs/2026-05-03-meta-learning-loop-gap-analysis.md`
- `docs/2026-05-03-inner-performance-loop-gap-analysis.md`
- `docs/2026-05-03-hermes-meta-learning-port-plan.md`

## Executive Thesis

`trading_assistant` should not be optimized as a reporting pipeline with some learning features attached. It should be optimized as a closed-loop trading research and execution-learning system.

The optimal design has one shared spine:

```text
Events and diagnostics
  -> LifecycleDiagnosticBundle
  -> ProposalLedger
  -> EvaluationEvidence
  -> ExperimentPlan
  -> DeploymentManifest
  -> LiveOutcomeMeasurement
  -> MetaEvaluation
  -> Replay and memory updates
  -> Next experiment queue
```

Most of the necessary primitives already exist. The repository has rich event schemas, daily metrics, strategy detectors, discovery analysis, LLM proposal parsing, parameter search, WFO, A/B testing, structural experiments, deployment monitoring, outcome measurement, learning cards, run search, provider scoring, generated playbooks, context budgeting, and a weekly learning cycle.

The limiting factor is integration. These components currently form several partial loops, but they do not yet share a canonical evidence object, objective contract, proposal ledger, deployment attribution model, replay harness, or causal evaluation layer. The result is that the system can remember and report, and it can sometimes optimize, but it cannot yet reliably compound knowledge across loops.

The highest-return improvement is to make every component write to and read from the same learning evidence graph.

## What Already Exists

### Event and Diagnostic Foundation

The codebase already captures rich trading lifecycle evidence.

Key files:

- `schemas/events.py::TradeEvent`
- `schemas/events.py::MissedOpportunityEvent`
- `schemas/enriched_events.py::IndicatorSnapshot`
- `schemas/enriched_events.py::OrderBookContext`
- `schemas/enriched_events.py::FilterDecisionEvent`
- `schemas/enriched_events.py::ParameterChangeEvent`
- `skills/build_daily_metrics.py`

Current capability:

- Executed trades include signal, entry, exit, regime, filter, root-cause, process-quality, MFE/MAE, exit-efficiency, fill-quality, latency, sizing, portfolio, market-condition, and parameter-snapshot fields.
- Missed opportunities include signal strength, blocked filter, hypothetical entry, forward outcomes, filter-margin context, signal ID, and backfill confidence.
- Enriched events support indicator snapshots, order-book context, filter decisions, and parameter changes.
- Daily metrics produce many curated artifacts: summaries, filter analysis, root causes, hourly performance, slippage, factor attribution, exit efficiency, excursions, signal health, fill quality, filter decisions, order-book stats, sizing, portfolio context, and parameter correlations.

Main gap:

These diagnostics are not yet normalized into a single lifecycle object used by strategy analysis, LLM reasoning, parameter search, WFO, experiments, deployment monitoring, and live outcome measurement.

### Deterministic Analysis and Structural Discovery

The codebase already contains a substantial deterministic analysis layer plus an LLM discovery layer.

Key files:

- `analysis/strategy_engine.py`
- `skills/filter_sensitivity_analyzer.py`
- `skills/counterfactual_simulator.py`
- `skills/exit_strategy_simulator.py`
- `skills/structural_analyzer.py`
- `analysis/discovery_prompt_assembler.py`
- `orchestrator/handlers.py::handle_discovery_analysis()`
- `analysis/weekly_prompt_assembler.py`

Current capability:

- `StrategyEngine` detects signal decay, component signal decay, factor decay, exit timing issues, filter interactions, regime problems, execution bottlenecks, sizing issues, drawdown concentration, portfolio crowding, and related patterns.
- Weekly simulations run filter sensitivity, counterfactual regime-gate tests, exit sweeps, and filter interaction analysis.
- `StructuralAnalyzer` classifies strategy lifecycle, detects signal/exit architecture mismatches, computes filter ROI, and proposes structural changes.
- Discovery analysis gives an LLM raw-file access to find patterns outside the deterministic detector set and propose new strategies.
- High-confidence strategy ideas are persisted to `memory/findings/strategy_ideas.jsonl` and can become structural experiments.

Main gap:

The deterministic analysis layer, discovery layer, simulations, and structural analyzer do not yet feed a single lifecycle-ranked experiment planner. Some outputs reach prompts, some reach deterministic suggestions, and some become experiments, but they are not all reconciled through one prioritization and evidence contract.

### Parameter Optimization and WFO

Parameter optimization exists in two forms: local greedy search and WFO.

Key files:

- `skills/config_registry.py`
- `skills/autonomous_pipeline.py`
- `skills/parameter_searcher.py`
- `schemas/parameter_search.py`
- `skills/backtest_simulator.py`
- `skills/suggestion_validator.py`
- `skills/backtest_calibration_tracker.py`
- `skills/run_wfo.py`
- `skills/param_optimizer.py`
- `orchestrator/handlers.py::handle_wfo()`

Current capability:

- `ConfigRegistry` maps suggestions to registered tunable parameters.
- `AutonomousPipeline` converts accepted parameter suggestions into approval requests.
- `ParameterSearcher` explores a local parameter neighborhood, tests robustness and cost sensitivity, and routes suggestions to approve, experiment, or discard.
- `BacktestCalibrationTracker` records whether parameter-search predictions later matched live outcomes.
- `WFORunner` generates folds, optimizes per fold, creates consensus parameters, tests aggregate OOS performance, runs robustness and cost-sensitivity checks, performs leakage audit, and produces a recommendation.

Main gaps:

- WFO remains mostly a reporting/review path. It does not automatically create proposal ledger entries, A/B experiments, deployment records, live outcome measurements, or calibration records.
- Parameter candidate-level evidence is evaluated but not fully persisted.
- `ParameterSearchReport` does not store best-candidate robustness fields, while `AutonomousPipeline` tries to serialize `report.robustness_score`.
- The optimizer cannot yet ask whether the right parameters are searchable in the first place.

### Experiment, Approval, and Deployment Monitoring

The system already has governance and monitoring primitives.

Key files:

- `schemas/experiments.py`
- `skills/experiment_manager.py`
- `skills/experiment_config_generator.py`
- `schemas/structural_experiment.py`
- `skills/structural_experiment_tracker.py`
- `skills/approval_handler.py`
- `schemas/deployment_monitoring.py`
- `skills/deployment_monitor.py`
- `orchestrator/app.py`
- `orchestrator/handlers.py::_check_deployments()`

Current capability:

- A/B `ExperimentConfig` supports variants, success metric, minimum trades, duration, significance threshold, and `source_suggestion_id`.
- `ExperimentManager` stores, activates, ingests, analyzes, and concludes A/B experiments using variant-level trade data.
- Structural experiments can be recorded, activated, resolved, and summarized.
- Approved PRs can create deployment records.
- `DeploymentMonitor` tracks PR merge status, heartbeat-confirmed deployment, pre/post metric snapshots, regression detection, stale deployments, and rollback PRs.

Main gaps:

- A/B experiment auto-accept references `exp.suggestion_id`, but the schema defines `source_suggestion_id`.
- Structural experiment evaluation is coupled to the A/B experiment check job because `_check_experiments()` returns early when `experiment_manager is None`, and the scheduler only registers the job when A/B testing is enabled.
- A/B experiment accounting and structural experiment accounting are split. `AutonomousPipeline` uses `StructuralExperimentTracker` for active-experiment caps while A/B configs live in `ExperimentManager`.
- Deployment monitoring is PR/heartbeat/regression oriented, not yet a full learning attribution manifest tied to affected trades, parameters, diagnostics, and outcomes.

### Outcome Measurement and Learning Cycle

The codebase already measures outcomes and has a weekly meta-learning loop.

Key files:

- `skills/auto_outcome_measurer.py`
- `schemas/outcome_measurement.py`
- `skills/backtest_calibration_tracker.py`
- `skills/learning_cycle.py`
- `skills/learning_ledger.py`
- `skills/retrospective_builder.py`
- `skills/suggestion_scorer.py`
- `skills/hypothesis_library.py`
- `skills/provider_route_scorer.py`
- `skills/benchmark_compiler.py`
- `skills/harness_eval_runner.py`
- `skills/playbook_generator.py`

Current capability:

- `AutoOutcomeMeasurer` compares before/after windows, detects concurrent changes, considers volatility and macro regime stability, estimates measurement quality, and feeds calibration.
- `OutcomeMeasurement` stores before/after PnL, win rate, drawdown, trade counts, regimes, concurrent changes, provider attribution, significance, and verdict.
- `LearningCycle` computes ground-truth snapshots, builds retrospective synthesis, updates hypotheses, recalibrates categories, compiles benchmark cases, scores providers, runs harness evaluation, generates playbooks, selects next experiments, and records a ledger entry.

Main gaps:

- The measured outcome is not consistently tied to exact proposal, candidate set, WFO fold evidence, deployment record, live exposure, and lifecycle diagnostic delta.
- Structural outcomes are still mainly whole-bot before/after checks.
- The harness runner is heuristic rather than replaying real prompt packages through candidate providers or prompt variants.
- The weekly selected experiments can be recorded without acceptance criteria, so they are not always evaluable.

### Learning Memory and Hermes-Inspired Infrastructure

Several Hermes-like components already exist.

Key files:

- `orchestrator/run_index.py`
- `skills/learning_card_store.py`
- `schemas/learning_card.py`
- `skills/learning_write_coordinator.py`
- `analysis/context_builder.py`
- `orchestrator/invocation_builder.py`
- `orchestrator/input_sanitizer.py`
- `schemas/generated_playbook.py`
- `skills/playbook_generator.py`

Current capability:

- `RunIndex` indexes runs in SQLite FTS5.
- Learning cards rank prior lessons by recency, impact, confidence, retrieval feedback, and context match.
- Generated playbooks are loaded into future prompts.
- `LearningWriteCoordinator` can group related writes with provenance.
- `ContextBuilder` has workflow-aware priority lists, item budgets, token budgets, and `_context_budget_manifest`.
- `InvocationBuilder` fences learning cards and generated playbooks as contextual memory, not fresh user instructions.
- `InputSanitizer` blocks common inbound prompt-injection patterns.

Main gaps:

- There is no unified learning memory manager that coordinates providers, scope, sanitization, prefetch, write sync, and snapshotting.
- Learned memory and playbooks do not yet have a full Hermes-style frozen snapshot and curation lifecycle.
- Past run recall is searchable but not yet summarized into replay-ready cases.
- Playbooks are generated but not outcome-scored through usage tracking and curation.

## Target System: One Evidence Graph

The optimal architecture has one evidence graph that every subsystem uses.

```text
Raw bot events
  -> Curated diagnostics
  -> LifecycleDiagnosticBundle
  -> ProposalCandidate
  -> EvaluationEvidence
  -> ExperimentPlan
  -> DeploymentManifest
  -> LiveOutcomeMeasurement
  -> MetaEvaluation
  -> ReplayCase and LearningMemory updates
  -> NextExperimentQueue
```

This graph should be append-only, source-attributed, bot/strategy scoped, and objective-versioned. Every parameter change, structural proposal, WFO recommendation, strategy idea, portfolio change, and instrumentation request should become a `ProposalCandidate` with evidence links.

## The Optimal Synergy Model

### 1. Diagnostics Feed the Same Lifecycle Bundle

Current diagnostics should converge into `LifecycleDiagnosticBundle`.

Proposed files:

- `schemas/lifecycle_diagnostics.py`
- `skills/lifecycle_diagnostic_builder.py`

The bundle should include:

- Signal extraction diagnostics
- Entry mechanism diagnostics
- Trade management diagnostics
- Exit mechanism diagnostics
- Portfolio/execution diagnostics
- Instrumentation coverage
- Ranked weaknesses
- Ranked strengths
- Experiment opportunities
- Source file references
- Missing diagnostic requests

How existing components use it:

- `analysis/strategy_engine.py` consumes it for deterministic suggestions.
- `analysis/weekly_prompt_assembler.py` exposes it to LLM reasoning.
- `skills/parameter_searcher.py` links candidate searches to lifecycle weaknesses.
- `skills/run_wfo.py` records which lifecycle issue each WFO run addresses.
- `skills/structural_analyzer.py` and discovery outputs map proposals to lifecycle stages.
- `skills/auto_outcome_measurer.py` measures diagnostic deltas after deployment.
- `skills/learning_cycle.py` learns which lifecycle interventions work.

### 2. All Proposals Enter the Same Ledger

The system needs a single `ProposalLedger` rather than separate partial trails.

Proposed files:

- `schemas/proposal_ledger.py`
- `skills/proposal_ledger.py`

It should store:

- Parameter suggestions from LLM and deterministic detectors
- WFO candidate parameter sets
- Structural proposals
- Strategy ideas
- Portfolio proposals
- Transfer proposals
- Bug/reliability fixes
- Instrumentation requests
- Search-space change proposals

Every record should include:

- source run or detector
- bot and strategy scope
- lifecycle stage
- hypothesis ID
- linked diagnostics
- expected mechanism
- affected parameters/files/strategies
- acceptance criteria
- evaluation method
- deployment links
- outcome links
- final decision correctness

How this improves synergy:

- LLM proposals, WFO recommendations, deterministic detectors, and discovery ideas become comparable learning objects.
- The weekly `LearningCycle` can evaluate decision quality, not just outcome counts.
- Replay cases can be built automatically from false accepts, false rejects, successful proposals, and missed opportunities.
- Search-space meta-learning can see which categories and parameters repeatedly matter.

### 3. One Objective Contract Anchors Every Evaluation

`schemas/objective_weights.py` already centralizes weights, but the system needs a versioned objective contract.

Proposed file:

- `schemas/learning_objective.py`

Core models:

- `LearningObjective`
- `ObjectiveComponent`
- `ObjectiveScore`
- `ObjectiveConstraint`

Every evaluation should record:

- objective version
- component scores
- composite score
- hard constraint results
- sample size
- regime coverage
- confidence interval or quality score
- data assumptions

How existing components change:

- `skills/ground_truth_computer.py` records objective version.
- `skills/parameter_searcher.py` records relative objective score plus normalized display score.
- `skills/param_optimizer.py` records the WFO objective and also computes the shared objective score for comparability.
- `skills/auto_outcome_measurer.py` records objective deltas with quality controls.
- `skills/provider_route_scorer.py` can score providers by objective-linked decision quality.

### 4. Evaluation Engines Are Chosen by Proposal Type

The system should route each proposal to the strongest available evaluator.

```text
Parameter-sensitive weakness
  -> ParameterSearcher for local search
  -> WFO for multi-parameter/regime robustness

Lifecycle mechanism change
  -> signal/entry/management/exit simulator
  -> structural experiment if simulator confidence is low

New strategy idea
  -> discovery evidence review
  -> replay/backtest harness if data supports it
  -> structural experiment with staged live validation

Unclear outcome
  -> diagnostic request planner
  -> instrumentation task

Prompt/provider/playbook question
  -> replay harness
  -> provider and playbook curation
```

Proposed files:

- `skills/lifecycle_experiment_planner.py`
- `skills/search_space_evaluator.py`
- `skills/wfo_result_integrator.py`
- `skills/diagnostic_request_planner.py`
- `skills/signal_extraction_replay.py`
- `skills/entry_mechanism_simulator.py`
- `skills/trade_management_simulator.py`
- `skills/exit_mechanism_simulator.py`

### 5. Experiments, Deployment, and Outcome Measurement Become One Path

The existing approval, experiment, and deployment pieces should be wired into a single learning path.

Target flow:

```text
ProposalCandidate
  -> EvaluationEvidence
  -> LearningDecision
  -> ApprovalRequest or ExperimentConfig or StructuralExperiment
  -> DeploymentRecord plus DeploymentManifest
  -> affected trade/signal population
  -> CausalOutcomeEvaluation
  -> ProposalLedger outcome update
  -> LearningCycle
```

Proposed files:

- `schemas/deployment_manifest.py` or extension fields on `schemas/deployment_monitoring.py::DeploymentRecord`
- `skills/causal_outcome_evaluator.py`
- `skills/experiment_registry.py` if a shared registry is cleaner than joining `ExperimentManager` and `StructuralExperimentTracker`

Required fixes:

- Use `ExperimentConfig.source_suggestion_id` in `orchestrator/app.py::_check_experiments()`.
- Schedule structural experiment evaluation independently of the A/B feature flag.
- Use A/B experiment data, not structural experiment data, for A/B active-experiment caps.
- Extend deployment records with code/config/strategy versions and affected population.
- Add `deployment_id`, `experiment_id`, `variant_id`, `parameter_set_id`, `config_version`, and `strategy_version` to trade, missed-opportunity, and signal-candidate events.

### 6. Meta-Learning Uses Replay, Not Only Memory

Hermes' best lesson is that memory becomes powerful when paired with replayable trajectories and curation.

Proposed files:

- `schemas/replay_case.py`
- `skills/replay_case_builder.py`
- `skills/harness_replay_runner.py`
- `skills/learning_memory_manager.py`
- `skills/playbook_usage_tracker.py`
- `skills/playbook_curator.py`
- `skills/learning_insights.py`

How current components evolve:

- `orchestrator/run_index.py` remains the searchable run store, but adds lineage/proposal/experiment/outcome metadata and summarized recall.
- `skills/benchmark_compiler.py` continues producing cases, but adds positive exemplars, false rejections, correct rejections, and missed high-value opportunities.
- `skills/harness_eval_runner.py` becomes a cheap proxy or is replaced by `HarnessReplayRunner`, which replays frozen prompt packages through providers/prompt variants.
- `skills/playbook_generator.py` produces versioned playbooks with applicability constraints and contraindications.
- `skills/playbook_usage_tracker.py` records whether a retrieved playbook improved validation and outcomes.
- `skills/playbook_curator.py` promotes, patches, archives, or pins playbooks based on measured outcomes.

## Ranked Implementation Priorities

### P0. Fix Evidence Integrity and Wiring

These are small changes with high leverage.

1. Fix A/B experiment auto-accept to use `exp.source_suggestion_id`.
2. Decouple structural experiment evaluation from `experiment_manager`.
3. Correct A/B active-experiment cap accounting.
4. Add `best_robustness_score`, `best_cost_sensitivity_sharpe`, and optional candidate list to `ParameterSearchReport`.
5. Update `AutonomousPipeline` approval summaries to use the new robustness fields.
6. Pass `bot_id` into `ContextBuilder.load_search_reports()` and `load_backtest_reliability()` from `base_package()`.
7. Implement or remove `TRAILING_STOP` from `skills/exit_strategy_simulator.py` default sweeps.
8. Feed `exit_sweep`, `filter_sensitivity`, and `counterfactual` simulation results into deterministic weekly strategy evidence, not only prompt data.
9. Update `skills/instrumentation_scorer.py` to score current enriched files and lifecycle capabilities.

### P0. Create the Shared Evidence Spine

1. Add `schemas/learning_objective.py`.
2. Add `schemas/lifecycle_diagnostics.py`.
3. Add `schemas/proposal_ledger.py`.
4. Add `skills/lifecycle_diagnostic_builder.py`.
5. Add `skills/proposal_ledger.py`.
6. Require all proposal-producing paths to write ledger records:
   - `orchestrator/handlers.py::_record_suggestions()`
   - `orchestrator/handlers.py::_record_agent_suggestions()`
   - `orchestrator/handlers.py::_record_structural_experiments()`
   - `orchestrator/handlers.py::handle_discovery_analysis()`
   - `orchestrator/handlers.py::handle_wfo()`
   - portfolio and transfer proposal paths

### P0. Close WFO Into the Learning Loop

1. Add `skills/wfo_result_integrator.py`.
2. Convert WFO ADOPT or TEST_FURTHER recommendations into `ProposalCandidate` records.
3. Store WFO fold-level evidence, aggregate OOS metrics, robustness, cost sensitivity, and leakage results.
4. Generate A/B experiment candidates when WFO confidence is high enough.
5. Record WFO predictions in `BacktestCalibrationTracker`.
6. Measure WFO-derived deployments with the same live outcome path as greedy parameter suggestions.

### P0. Add Causal Outcome Evaluation

1. Extend `DeploymentRecord` or create linked `DeploymentManifest`.
2. Add `skills/causal_outcome_evaluator.py`.
3. Evaluate by affected trade/signal population, not only calendar before/after.
4. Use matched controls where possible: unchanged strategy, unchanged bot, unchanged regime, or synthetic baseline.
5. Report both objective delta and lifecycle diagnostic delta.
6. Feed outcomes to `SuggestionTracker`, `HypothesisLibrary`, `LearningCardStore`, `ProviderRouteScorer`, and `LearningCycle`.

### P1. Meta-Learn the Search Space

1. Add `schemas/search_space_evaluation.py`.
2. Add `skills/search_space_evaluator.py`.
3. Detect edge optima, flat response curves, unstable parameters, and missing interaction terms.
4. Propose adding, retiring, widening, narrowing, transforming, or regime-splitting parameters.
5. Route search-space changes through approval because they affect what the optimizer can learn.

### P1. Build Lifecycle Simulators

Priority order:

1. `skills/signal_extraction_replay.py`
2. `skills/exit_mechanism_simulator.py`
3. `skills/entry_mechanism_simulator.py`
4. `skills/trade_management_simulator.py`

Reasoning:

- Signal/filter and exit already have the most data.
- Entry needs stronger order-book/fill coverage.
- Trade management needs in-trade state checkpoints before high-confidence replay is possible.

### P1. Replace Heuristic Harness Evaluation With Replay

1. Add `schemas/replay_case.py`.
2. Add `skills/replay_case_builder.py`.
3. Add `skills/harness_replay_runner.py`.
4. Use frozen prompt packages, parsed outputs, validator results, approval decisions, and measured outcomes.
5. Score provider/prompt variants by expected decision, calibration, evidence use, safety, and outcome alignment.
6. Feed results into `ProviderRouteScorer`, `PlaybookGenerator`, `LearningCycle`, and agent preferences.

### P1. Add Learning Memory Management and Playbook Curation

1. Add `skills/learning_memory_manager.py` to coordinate learning cards, run recall, outcomes, proposal ledger, experiments, playbooks, and reliability memory.
2. Extend `InputSanitizer` or add `skills/learning_memory_sanitizer.py` for learned-memory/playbook text.
3. Add frozen `learning_memory_snapshot.json` to run folders.
4. Add `schemas/playbook_usage.py`.
5. Add `skills/playbook_usage_tracker.py`.
6. Add `skills/playbook_curator.py`.
7. Extend `analysis/context_builder.py` budget metadata with provider/source and summarization details.

## Optimal Component Responsibilities

### Event Layer

Responsible files:

- `schemas/events.py`
- `schemas/enriched_events.py`
- `orchestrator/db/*`
- `orchestrator/handlers.py`

Target responsibility:

- Preserve raw factual evidence.
- Never decide strategy changes.
- Emit enough lineage to connect decisions to outcomes.

Required additions:

- `SignalCandidateEvent` or stricter full coverage of `MissedOpportunityEvent`.
- Event-level `deployment_id`, `experiment_id`, `variant_id`, `strategy_version`, `config_version`, and `parameter_set_id`.

### Diagnostic Layer

Responsible files:

- `skills/build_daily_metrics.py`
- `skills/lifecycle_diagnostic_builder.py`
- `skills/instrumentation_scorer.py`

Target responsibility:

- Convert raw events into lifecycle-stage diagnostics.
- Identify weaknesses, strengths, and missing instrumentation.
- Produce stable objects that all learning loops consume.

### Deterministic Planning Layer

Responsible files:

- `analysis/strategy_engine.py`
- `skills/structural_analyzer.py`
- `skills/lifecycle_experiment_planner.py`
- `skills/search_space_evaluator.py`

Target responsibility:

- Convert diagnostics into specific experiment opportunities.
- Decide which opportunities are parameter-sensitive, structural, instrumentation-limited, or regime-specific.
- Provide deterministic guardrails for LLM reasoning.

### LLM Reasoning Layer

Responsible files:

- `analysis/weekly_prompt_assembler.py`
- `analysis/discovery_prompt_assembler.py`
- `analysis/wfo_prompt_assembler.py`
- `analysis/response_parser.py`
- `analysis/response_validator.py`
- `orchestrator/agent_runner.py`

Target responsibility:

- Generate structural hypotheses, new strategy ideas, explanations, and high-level designs.
- Use deterministic diagnostics and prior memory as evidence, not as instructions.
- Emit structured outputs that enter the proposal ledger.

### Evaluation Layer

Responsible files:

- `skills/parameter_searcher.py`
- `skills/run_wfo.py`
- `skills/backtest_simulator.py`
- lifecycle simulators
- `skills/suggestion_validator.py`

Target responsibility:

- Quantitatively test proposals before live exposure.
- Record assumptions and confidence.
- Decide whether to approve, reject, experiment, or request instrumentation.

### Governance and Deployment Layer

Responsible files:

- `skills/approval_handler.py`
- `skills/experiment_manager.py`
- `skills/structural_experiment_tracker.py`
- `skills/deployment_monitor.py`
- `schemas/deployment_monitoring.py`

Target responsibility:

- Enforce human-in-the-loop permission gates.
- Run A/B and structural experiments.
- Track deployment state and rollback safety.
- Produce deployment manifests for learning attribution.

### Outcome and Meta-Learning Layer

Responsible files:

- `skills/auto_outcome_measurer.py`
- `skills/causal_outcome_evaluator.py`
- `skills/learning_cycle.py`
- `skills/learning_ledger.py`
- `skills/hypothesis_library.py`
- `skills/suggestion_scorer.py`
- `skills/backtest_calibration_tracker.py`

Target responsibility:

- Decide whether proposals worked.
- Learn whether prior decisions were correct.
- Recalibrate categories, hypotheses, providers, prompts, search spaces, and playbooks.
- Queue the next best experiments.

### Memory and Replay Layer

Responsible files:

- `orchestrator/run_index.py`
- `skills/learning_card_store.py`
- `skills/learning_write_coordinator.py`
- `skills/replay_case_builder.py`
- `skills/harness_replay_runner.py`
- `skills/playbook_curator.py`
- `analysis/context_builder.py`

Target responsibility:

- Retrieve the right lessons for the next task.
- Prevent stale or harmful lessons from dominating.
- Replay past cases to test whether prompt/provider/memory changes improve decisions.
- Keep learning writes scoped, sanitized, and provenance-tracked.

## Unified Data Flow

### Weekly Cycle

```text
Daily curated files
  -> LifecycleDiagnosticBuilder
  -> StrategyEngine + StructuralAnalyzer
  -> WeeklyPromptAssembler
  -> LLM structural proposals and parameter suggestions
  -> ResponseParser + ResponseValidator
  -> ProposalLedger
  -> ParameterSearcher / WFO / lifecycle simulator / structural experiment
  -> Approval or Experiment
  -> DeploymentMonitor and DeploymentManifest
  -> CausalOutcomeEvaluator
  -> LearningCycle
  -> ReplayCaseBuilder + LearningCardStore + PlaybookCurator
```

### WFO Cycle

```text
WFO trigger
  -> WFORunner
  -> WFOReport
  -> WFOResultIntegrator
  -> ProposalLedger
  -> A/B ExperimentPlan or approval request
  -> DeploymentRecord + manifest
  -> Live outcome and calibration
  -> Search-space and objective updates
```

### Discovery and New Strategy Cycle

```text
Discovery trigger
  -> raw file exploration by LLM
  -> discoveries + strategy_ideas + structural_proposals
  -> ProposalLedger
  -> StructuralExperimentTracker
  -> staged implementation/deployment
  -> causal outcome evaluation
  -> hypothesis library and replay cases
```

### Prompt/Provider Learning Cycle

```text
Agent run
  -> parsed output and validation result
  -> eventual outcome
  -> ReplayCaseBuilder
  -> HarnessReplayRunner
  -> ProviderRouteScorer
  -> PlaybookCurator and LearningCardStore
  -> future ContextBuilder retrieval
```

## Instrumentation Requirements

### Signal Extraction

- Every candidate signal, not only executed trades.
- Component scores, raw indicators, filter vector, regime, liquidity context.
- Accepted/rejected/delayed/suppressed decision.
- Forward returns at multiple horizons.
- Signal calibration bins and false accept/reject rates.

### Entry

- Intended order type and price.
- Actual order type and fill.
- Spread, depth, imbalance, latency, partial fill, rejection reason.
- Immediate adverse and favorable excursion.

### Trade Management

- In-trade state checkpoints: unrealized PnL, MFE, MAE, stop, target, position size, heat, correlation exposure, signal evolution.
- Stop/target adjustments with reason.
- Scale-in/scale-out decisions.

### Exit

- Exit trigger state.
- Alternative exit trigger candidates.
- Post-exit path at multiple horizons.
- Trailing-stop path when evaluating trailing stops.

### Experiment and Deployment

- `deployment_id`
- `experiment_id`
- `variant_id`
- `parameter_set_id`
- `strategy_version`
- `config_version`
- `signal_generation_version`
- code hash or commit SHA
- activation and rollback timestamps

## Evaluation Criteria

The unified system should evaluate improvements at three levels.

### Trading Performance

- Expected total R
- Net PnL
- Calmar
- Profit factor
- Expectancy
- Drawdown
- Process quality
- Live robustness by regime

### Learning Quality

- Proposal acceptance precision
- Proposal rejection correctness
- Backtest-to-live reliability
- WFO-to-live reliability
- Structural proposal pass rate
- Search-space change success rate
- Decision calibration
- Experiment throughput
- Inconclusive outcome rate

### Memory and Reasoning Quality

- Replay-case score by provider and prompt variant
- Learning-card helpfulness
- Playbook usage and outcome association
- Provider routing improvement
- Prompt-context relevance
- Stale or harmful memory rate

## Phased Roadmap

### Phase 0: Wiring and Integrity Fixes

Goal: stop losing evidence and fix known broken links.

Deliverables:

- Fix `source_suggestion_id` auto-accept.
- Decouple structural experiment checks from A/B flag.
- Fix experiment cap accounting.
- Add best robustness fields to parameter search reports.
- Pass bot scope into search reports and backtest reliability context loading.
- Integrate all weekly simulation outputs into deterministic strategy evidence.
- Update instrumentation scorer.

### Phase 1: Shared Spine

Goal: give all components common objects.

Deliverables:

- `LearningObjective`
- `LifecycleDiagnosticBundle`
- `ProposalLedger`
- lifecycle diagnostic builder
- proposal ledger writer integrations
- objective version recorded in ground truth, parameter search, WFO, and outcomes

### Phase 2: Close Parameter and WFO Loops

Goal: make parameter optimization a measured learning loop.

Deliverables:

- full candidate persistence
- WFO result integrator
- WFO-to-experiment routing
- WFO calibration records
- parameter search-space evaluator
- parameter search-space change proposals

### Phase 3: Causal Structural Learning

Goal: make structural proposals quantitatively meaningful.

Deliverables:

- deployment manifest extension
- causal outcome evaluator
- lifecycle-stage binding on structural proposals
- affected-population measurement
- matched-control or regime-controlled outcome reporting

### Phase 4: Lifecycle Simulators

Goal: make backtests match the diagnostics the system collects.

Deliverables:

- signal/filter replay
- exit simulator replacement or extension
- entry simulator
- trade-management simulator
- simulator confidence and assumption reporting

### Phase 5: Replay-Backed Meta-Learning

Goal: make LLM/provider/prompt/memory learning measurable.

Deliverables:

- replay case schema
- replay case builder
- harness replay runner
- provider/prompt variant scoring from real outputs
- playbook usage tracking
- playbook curator
- learning insights reports

## Definition of Done

The app should be considered a synergistic learning system when each weekly cycle can answer:

- What lifecycle stage created or destroyed the most expectancy?
- Which parameter or structural proposals directly addressed that lifecycle evidence?
- What offline evidence supported each proposal?
- Which proposals were approved, rejected, experimented, deployed, or deferred, and why?
- What live exposure did each deployed change receive?
- Did the live result improve the shared objective?
- Did the targeted lifecycle diagnostic improve?
- Was the prior backtest/WFO/LLM prediction calibrated?
- Which parameters should be added, removed, widened, narrowed, or split by regime?
- Which structural hypotheses are gaining or losing credibility?
- Which diagnostics are missing and should be instrumented next?
- Which provider, prompt variant, learning card, or playbook improved decision quality?
- Which exact experiments should be queued next?

The strategic aim is compounding learning. Every report, suggestion, experiment, deployment, bug fix, and correction should either improve trading performance directly or improve the system's ability to choose future improvements.

Until that evidence graph is in place, `trading_assistant` is best understood as a strong learning-assist and reporting system. With the shared spine above, it becomes a true loop-of-loops: a system that learns not only from trades, but from its own research decisions, proposal quality, experiment design, deployment outcomes, and reasoning history.
