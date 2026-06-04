# Learning System State Assessment

Date: 2026-04-11

## Executive Summary

The current repository is best described as a learning-capable trading research platform with several real closed-loop components, but not yet as a fully integrated system where past outputs are already demonstrably improving future trading performance in one coherent, auditable loop.

Your description is directionally right about the intended destination:

- the repo clearly aims to turn observations into proposals, proposals into experiments or deployments, and outcomes back into future prompts and decisions;
- it already contains both parameter-learning mechanisms and structural-improvement mechanisms;
- it already has more diagnostics and retrospective machinery than a typical "prompt plus report" system.

However, the description is not yet fully accurate for the current state of the repo because:

- parameter optimization is split across two adjacent systems instead of one shared greedy optimization framework;
- structural changes are proposed and tracked, but are not yet validated with the same quantitative rigor as parameter changes;
- diagnostics exist, including a dashboard endpoint, retrospective synthesis, convergence tracking, outcome reasoning, transfer-outcome measurement, and threshold learning, but there is still no single canonical post-cycle review artifact that answers "did this move us toward the goal, why, what should we instrument next, and what should we test next";
- the repo does not contain enough populated findings or baseline-vs-current evidence to claim that measurable improvement is already happening in practice.

The most accurate short description of the current repo is:

> Trading Assistant already contains the primitives for a genuine learning system, but it is still in the "strong components, partial integration" stage rather than the "fully unified autoresearch-style self-improving loop" stage.

## Scope And Evidence

This assessment is based on the code and checked-in artifacts currently in the repo, not on external production data.

Older architecture notes under `docs/` are useful historical context, but some of them are now stale relative to the code. Where those docs and the implementation disagree, the implementation should be treated as the current source of truth.

Key files reviewed included:

- `skills/learning_cycle.py:51`
- `analysis/context_builder.py:150`
- `analysis/context_builder.py:1199`
- `skills/autonomous_pipeline.py:148`
- `skills/autonomous_pipeline.py:424`
- `skills/parameter_searcher.py:48`
- `skills/ground_truth_computer.py:44`
- `skills/param_optimizer.py:75`
- `orchestrator/handlers.py:956`
- `skills/run_wfo.py:44`
- `orchestrator/app.py:935`
- `orchestrator/app.py:1336`
- `skills/structural_experiment_tracker.py:18`
- `skills/experiment_manager.py:91`
- `schemas/structural_experiment.py:24`

Relevant targeted tests were run:

```bash
pytest tests/test_learning_cycle.py tests/test_parameter_search_integration.py tests/test_structural_experiments.py tests/test_outcome_measurement.py tests/test_wfo_integration.py -q
```

Result:

- `128 passed in 37.41s`

Important caveat:

- `memory/findings/` in this checkout is effectively empty (`corrections.jsonl`, `failure_modes.jsonl`, `prompt_patterns.jsonl`, `trade_overrides.jsonl` are all zero bytes), so the repo shows capability and architecture, but not a populated history proving live learning effectiveness yet.

## Second-Pass Corrections To This Assessment

After a deeper code pass, the original version of this report needed three kinds of correction.

### 1. The repo already has more meta-learning machinery than the first pass credited

The first pass under-emphasized several implemented systems that are already in the codebase:

- `/learning/dashboard` exposes ground-truth trend, recent lessons, active hypotheses, active experiments, category scorecard, prediction accuracy, and latest net-improvement state (`orchestrator/app.py:1980`);
- weekly causal outcome reasoning analyzes why measured outcomes happened and records spurious effects, recalibrations, and transferable mechanisms (`orchestrator/app.py:1051`);
- cross-bot transfer outcomes are measured and fed back into transfer scoring (`orchestrator/app.py:1168`, `skills/transfer_proposal_builder.py`);
- adaptive threshold learning is implemented and scheduled (`orchestrator/app.py:1460`, `skills/threshold_learner.py`);
- portfolio-level outcome measurement exists separately from strategy-level measurement (`skills/portfolio_outcome_measurer.py`);
- reliability verification exists and can spawn new hypotheses from chronic bug classes (`orchestrator/app.py:1188`, `skills/reliability_tracker.py`).

So the repo is not only a parameter-plus-structural loop; it already contains several auxiliary learning loops around calibration, transfer, thresholds, portfolio outcomes, and reliability.

### 2. The A/B experiment story is less integrated than the first pass implied

The first pass correctly said that `ExperimentManager` exists, but it did not go far enough in distinguishing infrastructure from end-to-end integration.

What exists:

- `ExperimentManager` supports `create_experiment()`, `activate_experiment()`, variant data ingestion, statistical analysis, and conclusion (`skills/experiment_manager.py`);
- weekly analysis ingests `experiment_data.json` and can auto-conclude active experiments (`orchestrator/handlers.py:542`);
- `ExperimentConfigGenerator` can build experiment configs and YAML (`skills/experiment_config_generator.py`).

What still appears missing:

- the autonomous parameter-search `EXPERIMENT` route creates an approval request, but I did not find code that automatically persists the generated config through `ExperimentManager.create_experiment()` or materializes it via `generate_experiment_pr()` (`skills/autonomous_pipeline.py:461`);
- the current integration tests for this path only assert request creation, not a full persisted experiment lifecycle (`tests/test_parameter_search_integration.py`).

So the repo has substantial A/B infrastructure, but the autonomous parameter-experiment path is still only partially wired.

### 3. Schema and lifecycle drift is broader than the first pass stated

The original report mentioned the `measurement_date` vs `measured_at` mismatch. The deeper pass shows that this is part of a wider problem:

- several weekly accounting paths still read `timestamp` / `created_at` instead of `proposed_at`;
- several outcome readers still read `measured_at` / `timestamp` instead of `measurement_date`;
- some trend code still treats `implemented` as the live lifecycle state even though the current lifecycle uses `deployed`.

This means some of the repo's learning metrics are more fragile than the first report suggested.

## Claim-By-Claim Evaluation

### 1. "The goal is to be a learning system where past outputs measurably improve future trading performance."

Verdict: **Directionally accurate as a goal, not yet proven as the current state.**

Why this is partly true:

- `SuggestionTracker` records proposal lifecycle from proposed to deployed to measured (`skills/suggestion_tracker.py:22`).
- `AutoOutcomeMeasurer` computes before/after outcome measurements with regime matching, volatility controls, concurrent-change detection, and significance estimates (`skills/auto_outcome_measurer.py`).
- `ContextBuilder.load_outcome_measurements()` feeds reliable measured outcomes back into future prompts (`analysis/context_builder.py:150`).
- `LearningCycle.run()` computes weekly ground truth deltas and records lessons for future cycles (`skills/learning_cycle.py:51`).

Why this is not yet fully true:

- the checked-in repo does not contain populated findings demonstrating a measurable improvement trend over time;
- the system records many learning signals, but they are not yet consolidated into one authoritative "performance improved because of prior outputs" scorecard;
- some outcome-accounting paths still show schema drift and hardening issues (details below), which weakens confidence in the measured loop.

### 2. "Current learning loops are focused on optimizing parameters by leveraging the autoresearch greedy optimization framework."

Verdict: **Partially accurate.**

What exists today:

- `ParameterSearcher.search()` performs a local neighborhood search around a proposed parameter value, evaluates candidate values, runs robustness checks, applies cost sensitivity, and routes to `APPROVE`, `EXPERIMENT`, or `DISCARD` (`skills/parameter_searcher.py:48`).
- `AutonomousPipeline` persists `search_reports.jsonl` and `search_signals.jsonl` so future prompts can see which categories and parameter proposals have recently paid off (`skills/autonomous_pipeline.py:148`, `skills/autonomous_pipeline.py:424`).
- `LearningLedger` functions as a JSONL analogue of an experiment ledger or `results.tsv`-style learning history (`skills/learning_ledger.py:17`).

What is missing relative to an integrated autoresearch-style greedy system:

- scheduled WFO optimization and suggestion-driven neighborhood optimization are still separate systems with separate bookkeeping;
- there is no single frontier manager choosing the next best parameter experiments across both pathways;
- there is no unified proposal ledger showing search space, tested neighborhoods, selected candidate, deployment status, and realized outcome in one place.

So the repo does contain a **greedy local search component**, but it does not yet contain **one shared greedy optimization framework spanning all parameter-learning paths**.

### 3. "The system proposes structural improvements by leveraging the reasoning capabilities of LLMs."

Verdict: **Mostly accurate for proposal generation, only partially accurate for validation.**

What exists today:

- prompts already include rich retrospective context, active experiments, convergence state, search reports, track records, and outcomes (`analysis/context_builder.py:1199`, `analysis/prompt_assembler.py`, `analysis/weekly_prompt_assembler.py`);
- structural proposals are tracked through `StructuralExperimentTracker` with explicit acceptance criteria (`skills/structural_experiment_tracker.py:18`, `schemas/structural_experiment.py:24`);
- structural analysis also has deterministic support via `StructuralAnalyzer` for lifecycle, mismatch, and filter ROI analysis (`skills/structural_analyzer.py:48`).

What is weaker than the description implies:

- structural proposals are usually resolved with a whole-bot before/after comparison using ground-truth snapshots (`orchestrator/app.py:1336`);
- that is observational evaluation, not the same thing as a controlled causal test;
- the schema already contains `minimum_trade_count` and `baseline_value` in structural acceptance criteria (`schemas/structural_experiment.py:31-32`), but the current resolver does not actually use them.

So the repo does let LLMs propose structural changes, but it does **not yet validate those structural changes quantitatively with the same rigor as a strong experimental platform should**.

### 4. "These closed learning loops are optimally integrated."

Verdict: **Not accurate yet.**

The repo has strong pieces, but the integration is still incomplete in four important ways:

1. WFO and neighborhood search are not unified into one optimization program.
2. Parameter and structural loops do not share one objective function and one evaluation contract.
3. There is no single generated post-cycle review artifact.
4. Some outcome and ledger paths still contain schema drift and minor defects.

### 5. "After each loop there should be a way to analyze the results with full diagnostics, evaluate whether proposals moved the system closer to the goal, identify missing instrumentation, and choose next experiments."

Verdict: **The ingredients exist, but the single integrated review mechanism does not.**

What exists today:

- `ContextBuilder.base_package()` already assembles a very rich context package including:
  - reliable outcome measurements;
  - experiment track record;
  - active experiments;
  - forecast meta-analysis;
  - category scorecards;
  - prediction accuracy by metric;
  - optimization allocation;
  - search signal summary;
  - search reports;
  - cycle effectiveness trend;
  - suggestion quality trend;
  - convergence report;
  - last-week synthesis.  
  See `analysis/context_builder.py:1199`.
- `LearningCycle.run()` computes ground-truth deltas, retrospective synthesis, category recalibration, experiment selection, and weekly ledger entries (`skills/learning_cycle.py:51`).
- `/learning/dashboard` exposes the current learning state in one API response, including net improvement, recent lessons, ground-truth trend, active hypotheses, active experiments, category scorecard, and prediction accuracy (`orchestrator/app.py:1980`).
- weekly causal outcome reasoning records mechanism-level explanations, spurious outcomes, recalibrations, and transfer proposals (`orchestrator/app.py:1051`).
- `RetrospectiveBuilder.build_synthesis()` persists a structured `retrospective_synthesis.jsonl` artifact (`skills/retrospective_builder.py:145`).

What is still missing:

- there is no one report builder that turns these signals into a canonical "learning review" document after each cycle;
- no single artifact explicitly answers:
  - did we improve the unified objective;
  - which proposals helped;
  - which proposals failed;
  - which diagnostics are still blind spots;
  - which next experiments should be prioritized.

So this statement is accurate about **desired behavior**, but not yet about **current implementation completeness**.

### 6. "There should be a way to critically evaluate whether the right parameters are being proposed for greedy optimization and quantitatively validate structural changes."

Verdict: **Partially accurate for parameter proposals, not yet accurate enough for structural validation.**

Parameter proposal evaluation is already partially supported by:

- neighborhood search reports (`skills/parameter_searcher.py:48`);
- backtest reliability and approval modifiers;
- search signal summaries;
- category scorecards and recalibration;
- weekly retrospective synthesis.

But the repo still lacks:

- a cross-cycle analysis of whether the search space itself is correct;
- an explicit ranking of "important but currently unoptimized parameters";
- a mechanism that distinguishes "proposal quality is poor" from "parameter is unimportant" from "data is insufficient".

Structural validation is materially weaker:

- parameter A/B infrastructure exists in `ExperimentManager` with Welch's t-test (`skills/experiment_manager.py:91`);
- structural experiments, however, are resolved primarily via before/after ground-truth deltas instead of control/treatment evidence (`orchestrator/app.py:1336`).

## What The Repo Already Does Well

This repo is meaningfully ahead of a lot of systems that call themselves "learning loops." It already has the following real strengths.

### 1. It separates proposal, approval, deployment, and measurement

That separation is visible across:

- `SuggestionTracker`
- `AutonomousPipeline`
- approval request generation
- `AutoOutcomeMeasurer`
- `LearningCycle`

This is the right architecture for preventing "ideas" from being confused with "validated improvements."

### 2. It already has a serious retrospective context layer

`ContextBuilder.base_package()` is unusually rich. It does not just feed the model raw reports; it feeds it:

- measured outcomes;
- quality-filtered outcomes vs spurious outcomes;
- calibration meta-analysis;
- experiment history;
- active experiments;
- convergence state;
- search reports;
- optimization allocation;
- retrospective synthesis.

That is exactly the kind of context a learning system needs.

### 3. It already distinguishes parameter changes from structural changes

This is important. Parameter tuning and structural redesign should not be treated as the same kind of evidence problem, and the repo already has separate machinery for each.

### 4. It already includes measurement-quality thinking

`AutoOutcomeMeasurer` does not just compare PnL before and after. It also looks at:

- regime matching;
- volatility shifts;
- concurrent changes;
- macro regime stability;
- significance score;
- targeted metric alignment.

That is a strong base for real-world learning.

### 5. It already tracks weekly learning at the system level

`LearningCycle.run()` and `LearningLedger` show the repo is not only learning at the suggestion level, but also attempting to learn about the quality of its own loop.

### 6. It already has multiple meta-learning side loops

Beyond the core parameter and structural paths, the repo already includes:

- convergence tracking (`skills/convergence_tracker.py`);
- causal outcome reasoning (`orchestrator/app.py:1051`);
- transfer learning with measured transfer outcomes (`skills/transfer_proposal_builder.py`);
- adaptive threshold learning (`skills/threshold_learner.py`);
- portfolio outcome measurement (`skills/portfolio_outcome_measurer.py`);
- reliability verification and chronic-bug hypothesis creation (`skills/reliability_tracker.py`).

These are real assets that the first pass understated.

## Critical Gaps

The following are the most important gaps between the current repo and the system you described.

### Gap 1. There is no single shared optimization objective across all learning loops

This is the largest architecture gap.

Current state:

- `GroundTruthComputer` uses a 6-component composite score with expected return, Calmar, profit factor, expectancy, inverse drawdown, and process quality (`skills/ground_truth_computer.py:44`).
- `ParameterSearcher._composite_score()` uses a different, simplified score that excludes process quality and uses ratio-style comparisons (`skills/parameter_searcher.py:259`).
- `ParamOptimizer._objective_value()` optimizes the configured WFO objective, usually one metric such as Sharpe, Sortino, Calmar, or profit factor (`skills/param_optimizer.py:75`).

Why this matters:

- different loops can recommend different actions because they are optimizing different things;
- a weekly "improvement" can disagree with the optimization logic that created the proposal;
- structural and parameter loops cannot be compared on one scale.

What should happen instead:

- one canonical objective function should exist and be reused by:
  - WFO ranking;
  - neighborhood search;
  - experiment evaluation;
  - weekly learning ledger;
  - proposal prioritization.

### Gap 2. The parameter loop is split into two systems instead of one integrated loop

Current state:

- the suggestion-driven path uses `ParameterSearcher` and writes `search_reports.jsonl`;
- the scheduled WFO path runs independently through `handle_wfo()` and `WFORunner.run()` (`orchestrator/handlers.py:956`, `skills/run_wfo.py:44`);
- there is also an A/B experiment subsystem, but the autonomous `EXPERIMENT` route currently appears to stop at an approval request instead of automatically persisting a concrete `ExperimentManager` config (`skills/autonomous_pipeline.py:461`);
- the WFO path produces reports and notifications, but it does not flow naturally into:
  - `SuggestionTracker`;
  - `search_reports.jsonl`;
  - `LearningLedger`;
  - `BacktestCalibrationTracker`;
  - `AutoOutcomeMeasurer`.

Why this matters:

- you do not yet have one end-to-end parameter-learning narrative from proposal to evaluation;
- WFO can discover parameter ideas that the learning ledger does not fully own;
- the system cannot easily answer "which parameter discovery source is producing the highest realized value?"

### Gap 3. Structural experiments are tracked, but not yet evaluated causally

Current state:

- structural experiments can be proposed, activated, and resolved;
- resolution currently compares ground-truth snapshots from activation date to current date for the whole bot (`orchestrator/app.py:1336`);
- `ExperimentManager` already has stronger controlled-experiment statistics, but structural experiments do not appear to use that path (`skills/experiment_manager.py:91`).

Why this matters:

- whole-bot before/after deltas are vulnerable to confounding from market regime shifts, concurrent changes, and unrelated parameter updates;
- a structural improvement can look good because the market changed, not because the structure improved;
- a good structural change can also be unfairly rejected because other concurrent changes hurt performance.

### Gap 4. There is no single post-cycle "learning review" artifact

Current state:

- the raw ingredients are present in JSONL files, prompt context, ledger entries, `retrospective_synthesis.jsonl`, and `/learning/dashboard`;
- there is no generated review document after each weekly cycle that synthesizes them.

Why this matters:

- operator trust depends on being able to inspect one coherent review, not multiple logs;
- missing instrumentation and next experiments are not surfaced in one canonical place;
- the loop is harder to audit and harder to improve.

### Gap 5. The repo has capability, but not checked-in evidence of realized learning

Current state:

- the system can record outcomes and learn from them;
- the checked-in `memory/findings/` directory contains almost no accumulated evidence.

Why this matters:

- you can accurately say the repo is designed to learn;
- you cannot yet accurately say the repo proves that past outputs are already improving future trading performance.

### Gap 6. Upstream instrumentation is still a bottleneck

The repo already expects richer event data than many upstream bot stacks typically emit. This is reflected in:

- the event schemas under `schemas/events.py` and `schemas/enriched_events.py`;
- the instrumentation requirements documented in `docs/strategy_instrumentation_spec.md`.

Why this matters:

- if process quality, root causes, filter decisions, slippage, execution quality, and missed opportunities are incomplete upstream, then downstream learning will be noisier and less reliable;
- structural and parameter analysis are only as good as the event stream they receive.

## Concrete Hardening Issues Found During Review

These are implementation-level problems that weaken the loop even if the overall architecture is good.

### 1. Undefined variable in outcome promotion path

In `orchestrator/app.py:986`, `_measure_outcomes()` checks `if outcome.net_positive_7d:` even though the variable in scope is `result`.

Likely consequence:

- the enhanced outcome measurement may already be written and the suggestion may already be marked measured;
- then the code throws a `NameError`;
- the broad `try/except` logs the failure and skips linked pattern promotion;
- this makes the loop appear partially successful while silently breaking one feedback path.

### 2. Schema and lifecycle drift across weekly accounting

The `measurement_date` mismatch called out in the first pass is real, but it is only part of a broader drift problem.

Examples:

- `LearningLedger._compute_week_outcome_quality()` reads `measured_at` or `timestamp`, not `measurement_date` (`skills/learning_ledger.py:306`);
- `RetrospectiveBuilder._load_week_outcomes()` does the same (`skills/retrospective_builder.py:262`);
- `ConvergenceTracker` groups outcomes by `measured_at` or `timestamp`, not `measurement_date` (`skills/convergence_tracker.py:366`, `skills/convergence_tracker.py:390`);
- `SuggestionScorer._compute_suggestion_quality_trend()` groups suggestions by `timestamp` or `created_at` and counts statuses `implemented` / `measured`, not `proposed_at` / `deployed` (`skills/suggestion_scorer.py`);
- `LearningCycle._count_suggestions()` and `_classify_loop_sources()` also use legacy timestamp fields and legacy implementation statuses (`skills/learning_cycle.py:262`, `skills/learning_cycle.py:313`);
- `LearningCycle._count_experiments()` looks for `concluded_at`, but the structural experiment tracker stores `resolved_at` (`skills/learning_cycle.py:326`, `schemas/structural_experiment.py`).
- `ThresholdLearner._load_detection_outcomes()` still derives positivity from legacy `pnl_delta_7d` fields rather than the richer enhanced outcome verdicts and quality flags (`skills/threshold_learner.py`).

Likely consequence:

- weekly cycle effectiveness can undercount or miss newer outcome records;
- retrospective synthesis and convergence tracking can miss newer measurements;
- proposal counts, loop-source attribution, and "implemented" counts can be understated or skewed;
- suggestion quality trend can undercount the current `deployed` lifecycle.

This also suggests that `outcomes.jsonl` is currently serving mixed schemas:

- legacy `SuggestionOutcome`;
- newer `OutcomeMeasurement`.

Some readers handle that gracefully, but not all of them do so consistently.

### 3. Autonomous parameter experiments are not fully wired end to end

`AutonomousPipeline._route_to_experiment()` builds an approval request using `ExperimentConfigGenerator.generate_from_suggestion()`, but I did not find code that then:

- persists that config with `ExperimentManager.create_experiment()`;
- activates it through the same route;
- or materializes it via `generate_experiment_pr()`.

The current tests for this path only check that a structural-style approval request is created (`tests/test_parameter_search_integration.py`).

Likely consequence:

- the system can identify "experiment-worthy" parameter changes without consistently turning them into managed A/B experiments;
- `ExperimentManager` exists, but the autonomous parameter loop does not appear to fully use it yet.

### 4. Experiment recommendation propagation is mismatched

`ExperimentManager.analyze_experiment()` returns recommendations such as:

- `adopt_treatment`
- `keep_control`
- `inconclusive`
- `extend`

But the auto-conclusion code in `orchestrator/app.py` checks for `"adopt"` and `"discard"` when deciding whether to accept suggestions or update hypotheses.

Likely consequence:

- experiments can be concluded statistically while downstream suggestion and hypothesis propagation does not behave as intended.

### 5. Strategy-idea experiment creation path calls a missing method

In `orchestrator/handlers.py:1388`, high-confidence strategy ideas call `self._experiment_manager.propose(...)`, but `ExperimentManager` does not define `propose()`.

Likely consequence:

- the code falls into the `except` block and logs a warning instead of creating the intended experiment records;
- this is another example of experiment infrastructure existing in pieces without fully consistent wiring.

### 6. Structural acceptance criteria are richer than the resolver actually uses

The structural experiment schema contains:

- `minimum_trade_count`
- `baseline_value`
- `observation_window_days`

But the current resolver in `orchestrator/app.py:1336` appears to evaluate only metric deltas and direction thresholds.

Likely consequence:

- experiments can pass or fail without enforcing the full acceptance contract;
- structurally weak evidence can masquerade as a resolved experiment.

### 7. Test coverage is strong on components, but weaker on cross-schema and lifecycle integration

The targeted test suite passed, which is good. But the tests also suggest an integration gap:

- `tests/test_learning_cycle.py` still writes legacy `measured_at` outcome records;
- `tests/test_outcome_measurement.py` exercises the newer `measurement_date` path.
- the experiment-route integration tests only assert approval-request creation, not persisted experiment creation (`tests/test_parameter_search_integration.py`).

This means the component tests are healthy, while the migration boundary between old and new outcome formats is under-tested.

## Additional Diagnostics And Instrumentation Needed

If the goal is to know whether the system is proposing the right parameters and the right structural changes, the following additions would provide the most leverage.

### 1. Unified proposal-to-outcome ledger

Add one canonical record per learning action with fields like:

- proposal_id
- source (`strategy_engine`, `llm_weekly`, `wfo`, `retrospective`, `human`)
- proposal_type (`parameter`, `structural`, `portfolio`, `instrumentation`)
- target bot / strategy / parameter
- optimization objective value before proposal
- evaluation method (`search`, `backtest`, `ab_test`, `before_after`)
- deployment status
- measured outcome
- confidence / reliability adjustment

This should replace the need to mentally join multiple JSONL files.

### 2. Objective decomposition telemetry

Every evaluated proposal should log not just the composite score, but the contribution deltas of:

- expected return
- drawdown
- Calmar
- expectancy
- process quality
- trade count / sample sufficiency

That makes it possible to answer "why did this score improve?" instead of just "what was the score?"

### 3. Search-space quality diagnostics

The system currently evaluates proposed values, but it does not yet rigorously evaluate whether it is even searching the right parameters.

Add diagnostics for:

- parameter proposal frequency vs realized value;
- category proposal frequency vs realized value;
- parameters never proposed but highly associated with outcome variance;
- proposal rejection reasons by category;
- "important but underexplored" parameter ranking.

### 4. Structural experiment design metadata

Structural experiments should carry:

- explicit control definition;
- treatment definition;
- eligibility rules;
- minimum sample size;
- blocked concurrent changes;
- primary metric;
- guardrail metrics;
- analysis method.

Without that, structural validation remains weaker than it should be.

### 5. Deployment and causal-change manifest

Whenever something is deployed, write a manifest that says exactly what changed:

- parameter file and value diffs;
- strategy or structural diffs;
- deployment time;
- affected bot(s);
- experiment or suggestion linkage.

That makes before/after measurement far easier to trust.

### 6. Upstream execution-quality instrumentation

The most valuable additional upstream signals would be:

- filter decision outcomes by filter and regime;
- process-quality score on every trade and daily summary;
- explicit parameter-change events;
- execution-quality fields such as slippage bucket, latency bucket, order-book context;
- counterfactual missed-opportunity outcomes.

These are especially important if the system is going to diagnose whether a failed proposal was conceptually wrong or simply deployed into noisy conditions.

## Recommended Target Architecture

The optimal next state is not "add more heuristics." It is to make every learning loop conform to one shared contract.

### Closed-Loop Contract

Every proposal, regardless of source, should pass through the same stages:

1. **Propose**  
   Source can be strategy engine, WFO, weekly LLM reasoning, retrospective analysis, or human.

2. **Score ex ante**  
   Score against one canonical objective plus uncertainty and guardrails.

3. **Choose action**  
   Approve, experiment, discard, or request instrumentation first.

4. **Deploy with manifest**  
   Every live or experimental change gets a precise change manifest.

5. **Measure ex post**  
   Measure outcome using the best valid method for that proposal type.

6. **Review cycle outcome**  
   Generate a single review artifact summarizing whether the system moved toward the goal.

7. **Select next experiments**  
   Prioritize the next batch from the same unified ledger and objective.

Right now, the repo has good implementations of several of these stages, but they are not yet governed by one shared contract.

## Recommended Remediation Plan

### Phase 1. Unify the objective function

Priority: **highest**

Goal:

- ensure WFO, neighborhood search, experiments, and weekly review are all optimizing and judging the same thing.

Recommended changes:

- extract a shared scoring module, for example `schemas/learning_objective.py` or `skills/learning_objective.py`;
- make `GroundTruthComputer`, `ParameterSearcher`, `ParamOptimizer`, and experiment evaluation all call the same scorer;
- include process quality explicitly everywhere, not only in weekly ground truth;
- record both total score and component contributions.

Files most likely involved:

- `skills/ground_truth_computer.py`
- `skills/parameter_searcher.py`
- `skills/param_optimizer.py`
- `skills/auto_outcome_measurer.py`
- `skills/experiment_manager.py`

### Phase 2. Merge WFO and search into one parameter-learning program

Priority: **highest**

Goal:

- make WFO and suggestion-driven optimization two proposal sources feeding one common evaluation and measurement pipeline.

Recommended changes:

- treat WFO recommendations as first-class proposals in the same unified ledger;
- feed WFO results into the same approval / experiment / deployment / measurement path used by the autonomous pipeline;
- store WFO-origin proposals alongside `search_reports` rather than outside them;
- add a source field so the system can compare realized value by source.

Files most likely involved:

- `orchestrator/handlers.py`
- `skills/run_wfo.py`
- `skills/suggestion_tracker.py`
- `skills/learning_ledger.py`
- a new unified proposal ledger module

### Phase 3. Upgrade structural changes from observational tracking to experiment-grade validation

Priority: **high**

Goal:

- validate structural changes with a stronger causal standard.

Recommended changes:

- extend `ExperimentRecord` with explicit control/treatment metadata and primary metric;
- route structural changes into `ExperimentManager` when feasible;
- use before/after resolution only as a fallback when controlled evaluation is impossible;
- enforce `minimum_trade_count`, `baseline_value`, and guardrail metrics during resolution.

Files most likely involved:

- `schemas/structural_experiment.py`
- `skills/structural_experiment_tracker.py`
- `skills/experiment_manager.py`
- `orchestrator/app.py`

### Phase 4. Generate a post-cycle learning review artifact

Priority: **high**

Goal:

- after each weekly cycle, produce one authoritative review.

Recommended changes:

- create a builder such as `skills/learning_review_builder.py`;
- invoke it at the end of `LearningCycle.run()`;
- write `runs/learning-review-<week_start>-<week_end>.md`;
- include:
  - objective movement;
  - parameter proposals tested and realized;
  - structural proposals tested and realized;
  - which diagnostics were decisive;
  - where evidence was weak or confounded;
  - instrumentation gaps;
  - prioritized next experiments.

Files most likely involved:

- `skills/learning_cycle.py`
- `skills/learning_ledger.py`
- `analysis/context_builder.py`
- new report builder module

### Phase 5. Harden the bookkeeping and schema boundaries

Priority: **high**

Goal:

- ensure the system is not silently dropping or miscounting learning signals.

Recommended changes:

- fix the undefined variable in `_measure_outcomes()`;
- normalize outcome schemas so every downstream consumer can read them consistently;
- update weekly outcome-quality logic to understand `measurement_date`;
- add end-to-end tests that exercise the exact current data path from proposal to weekly review.

Files most likely involved:

- `orchestrator/app.py`
- `skills/learning_ledger.py`
- `schemas/outcome_measurement.py`
- `schemas/suggestion_tracking.py`
- `tests/test_learning_cycle.py`
- `tests/test_outcome_measurement.py`

### Phase 6. Add instrumentation-first recommendations

Priority: **medium**

Goal:

- let the system explicitly say "do not optimize yet; measure this first."

Recommended changes:

- add an explicit proposal action type for instrumentation requests;
- let the weekly review surface missing evidence before recommending a change;
- track whether instrumentation additions later improved proposal quality.

This is important because an intelligent learning system should sometimes conclude that the next best experiment is "collect better evidence."

## What "Accurate Current-State Language" Would Look Like

If you want a description that fits the repo as it exists today, this would be accurate:

> Trading Assistant already contains substantial learning-loop infrastructure: it can generate parameter and structural proposals, run local parameter neighborhood searches and WFO analyses, measure deployed outcomes, track experiments, assemble retrospective context, and feed those learnings back into future prompts.  
>  
> The main remaining gaps are that the parameter-learning pathways are not yet unified under one canonical objective and one proposal ledger, structural changes are not yet validated with experiment-grade rigor, and the system does not yet generate a single post-cycle review artifact proving whether it moved trading performance closer to the target objective.

## Bottom Line

The current repo is not missing the idea of a learning system. It already has most of the primitives required for one.

The real issue is integration quality:

- the system already learns locally in several places;
- it does not yet judge all of those learnings through one objective, one ledger, one measurement contract, and one cycle review.

That is the critical gap to address next.

If you close only three things, they should be:

1. unify the objective function;
2. unify WFO and autonomous parameter search into one proposal-to-outcome pipeline;
3. generate one post-cycle learning review artifact that explicitly selects the next experiments and instrumentation work.

Those three changes would move the repo from "promising learning architecture" to "coherent self-improving research system."
