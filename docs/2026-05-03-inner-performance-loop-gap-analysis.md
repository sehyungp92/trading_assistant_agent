# Inner Performance Loop Gap Analysis

Date: 2026-05-03

Scope: evaluate whether each learning iteration can analyze live and backtest performance across the full trading lifecycle, then convert weaknesses or strengths into testable parameter experiments, structural changes, and live validation plans.

Lifecycle stages reviewed:

- Signal extraction
- Entry mechanism
- Trade management
- Exit mechanism

## Executive Verdict

The repository collects and aggregates far richer trading diagnostics than a normal report generator. `schemas/events.py`, `schemas/enriched_events.py`, and `skills/build_daily_metrics.py` already support signal, filter, execution, exit, sizing, portfolio, order-book, regime, and process-quality diagnostics. `analysis/strategy_engine.py` contains many detectors that convert those diagnostics into structured suggestions.

The inner performance loop is still incomplete because the diagnostics are not yet normalized into a canonical lifecycle diagnostic bundle, and the backtest/simulation layer cannot replay most of the lifecycle decisions the system can diagnose. The result is an asymmetry:

- The system can often describe a weakness.
- It can sometimes propose a parameter change.
- It can rarely simulate the full causal effect of changing signal extraction, entry logic, trade management, or exit behavior.

The highest-impact next step is to create a `LifecycleDiagnosticBundle` that becomes the common input to deterministic strategy analysis, LLM reasoning, parameter search, WFO, structural proposal validation, and live outcome measurement.

## Current Performance Loop

The intended performance loop currently looks like this:

```text
TradeEvent / MissedOpportunityEvent / enriched diagnostics
  -> skills/build_daily_metrics.py
  -> data/curated/<date>/<bot>/*.json
  -> analysis/strategy_engine.py
  -> analysis/weekly_prompt_assembler.py
  -> LLM suggestions and structural proposals
  -> analysis/response_parser.py
  -> analysis/response_validator.py
  -> skills/autonomous_pipeline.py or structural experiment tracker
  -> backtest/search/experiment/live outcome measurement
```

This is a good skeleton. The missing piece is a lifecycle-specific evidence contract that forces every loop to answer:

- What stage of the trade lifecycle is weak or strong?
- Which diagnostic proves that?
- Which candidate change directly targets it?
- How will the change be evaluated offline?
- How will it be validated live?
- What additional instrumentation is needed if the result is ambiguous?

Important second-pass correction: several lifecycle and structural-analysis pieces already exist and should be reused:

- `skills/structural_analyzer.py::compute()` classifies strategy lifecycle phase, detects architecture mismatches, computes filter ROI, and emits proposed structural changes.
- `analysis/discovery_prompt_assembler.py` and `orchestrator/handlers.py::handle_discovery_analysis()` give an LLM raw-file access to discover patterns outside deterministic detector coverage and to propose new strategy ideas.
- `schemas/deployment_monitoring.py` and `skills/deployment_monitor.py` already track PR/merge/deploy/regression lifecycle for approved parameter changes. The gap is per-trade/per-signal attribution and learning-grade deployment metadata, not total absence of deployment monitoring.

## Current State by Lifecycle Stage

### 1. Signal Extraction

The codebase has strong raw signal instrumentation.

Evidence:

- `schemas/events.py::TradeEvent` includes `signal`, `signal_strength`, `confidence`, `regime`, `filters_passed`, `process_quality_score`, `root_causes`, `signal_factors`, `signal_evolution`, `signal_id`, `filter_decisions`, `strategy_params_at_entry`, and post-exit backfill fields.
- `schemas/events.py::MissedOpportunityEvent` includes `signal_strength`, `blocked_by`, hypothetical entry price, 1h/4h/24h outcomes, TP/SL indicators, margin percentage, `signal_id`, and backfill confidence.
- `schemas/enriched_events.py::IndicatorSnapshot` supports indicator values at `enter`, `skip`, and `exit`.
- `schemas/enriched_events.py::FilterDecisionEvent` captures threshold, actual value, pass/fail, margin percentage, and diagnostic context.
- `skills/build_daily_metrics.py::write_all()` writes `signal_health`, `filter_decisions`, `indicator_snapshots`, `factor_attribution`, `root_causes`, `notable_missed`, `filter_analysis`, `regime_analysis`, and `process_failures`.
- `analysis/strategy_engine.py::detect_signal_decay()` detects decay from 30-day versus 90-day signal-outcome correlation.
- `analysis/strategy_engine.py::detect_component_signal_decay()` reads `signal_health` component diagnostics.
- `analysis/strategy_engine.py::detect_filter_interactions()` evaluates interacting filters.
- `skills/signal_health_analyzer.py::compute()` computes signal quality from executed trades with signal evolution.
- `skills/filter_sensitivity_analyzer.py::analyze()` estimates blocked winners, blocked losers, net impact, and threshold relaxation points.
- `skills/counterfactual_simulator.py::simulate_remove_filter()` estimates the impact of removing a filter by adding missed opportunities blocked by that filter.

Assessment:

Signal extraction is the best-instrumented lifecycle stage. The main weakness is that the analyzer still leans heavily on executed trades and selected missed-opportunity backfills. To know whether signal extraction captures maximum available alpha, the system needs a fuller candidate universe: every generated signal, every filter decision, indicator snapshots for accepted and rejected signals, and forward returns for rejected candidates.

Current capability:

- Detect signal decay.
- Detect some component signal weakness.
- Detect filter overblocking or underblocking.
- Estimate some missed opportunity value.

Not yet possible:

- Measure the true alpha ceiling of the signal universe.
- Estimate signal discrimination quality across all accepted and rejected candidates.
- Quantify false accept and false reject rates by regime, hour, liquidity condition, and component.
- Optimize component weights or nonlinear interactions from a full candidate set.

### 2. Entry Mechanism

The repository collects useful entry and execution diagnostics, but the evaluation layer is thinner than the data layer.

Evidence:

- `schemas/events.py::TradeEvent` includes `entry_price`, `qty`, `slippage_bps`, `latency_ms`, `session`, `fill_quality`, `execution_timestamps`, `market_conditions_at_entry`, and `order_book_context`.
- `schemas/enriched_events.py::OrderBookContext` stores bid/ask, spread, depth, imbalance, slippage estimate, and microprice.
- `schemas/enriched_events.py::OrderLifecycleEvent` stores order status transitions, requested quantity, filled quantity, average fill price, rejected reason, and latency.
- `skills/build_daily_metrics.py::write_all()` writes `fill_quality`, `orderbook_stats`, `execution_latency`, and `order_lifecycle` artifacts when data is available.
- `analysis/strategy_engine.py` maps execution and microstructure detectors into suggestion categories such as `execution_latency`, `spread_execution`, `orderbook_imbalance`, and `microstructure_entry`.

Assessment:

The data model can support entry analysis, but the current simulation layer does not evaluate alternative entry mechanisms. There is no clear `entry_mechanism_simulator` that compares market entry, limit entry, delayed entry, spread-aware entry, liquidity-aware entry, or confirmation-based entry against the same signal population.

Current capability:

- Report fill quality, spread, latency, order-book context, and execution problems when events include those fields.
- Generate deterministic suggestions from execution and microstructure diagnostics.

Not yet possible:

- Backtest alternative entry timing or order types using the same signal.
- Separate bad signal quality from bad entry execution.
- Quantify adverse selection immediately after entry.
- Evaluate whether a signal should enter immediately, wait for confirmation, use a limit, or skip under poor liquidity.

### 3. Trade Management

The repository has pieces for trade management analysis but lacks a proper in-trade replay model.

Evidence:

- `schemas/events.py::TradeEvent` includes stop loss, take profit, MFE, MAE, exit efficiency, signal evolution, drawdown at entry, sizing inputs, portfolio state, and post-exit move.
- `skills/build_daily_metrics.py::build_excursion_stats()` aggregates MFE/MAE and exit behavior.
- `skills/build_daily_metrics.py::write_all()` writes `sizing_analysis`, `portfolio_context`, `stop_adjustment_analysis`, and `process_quality`.
- `analysis/strategy_engine.py` includes detectors and categories for drawdown clusters, position sizing, portfolio exposure, correlation crowding, stop logic, and risk controls.
- `schemas/events.py::TradeEvent.root_causes` includes `premature_stop`, `risk_cap_hit`, `correlation_crowding`, `funding_adverse`, and related lifecycle causes.

Assessment:

The system can identify trade-management symptoms, but it cannot yet replay in-trade decisions at a high enough resolution. For example, it can summarize MFE/MAE and process quality, but it cannot consistently test dynamic stop movement, scale-out, break-even rules, time-in-trade rules, pyramiding, exposure throttles, or portfolio-level risk allocation unless those behaviors are represented as simple parameters.

Current capability:

- Aggregate excursion and process-quality diagnostics.
- Detect some sizing, drawdown, and portfolio context issues.
- Propose simple stop or sizing changes.

Not yet possible:

- Replay bar-by-bar in-trade management alternatives.
- Attribute lost expectancy to stop placement versus position sizing versus exposure conflict.
- Validate structural trade-management rules with enough precision before live testing.
- Estimate interaction effects between sizing, stops, and portfolio heat.

### 3b. Structural Lifecycle and New Strategy Discovery

The repository already has a structural layer that sits above individual trade mechanics.

Evidence:

- `skills/structural_analyzer.py::compute()` consumes per-strategy weekly summaries and returns lifecycle statuses, architecture mismatches, filter ROI, growing strategies, decaying strategies, and proposed changes.
- `skills/structural_analyzer.py::_classify_lifecycle()` compares 30d/60d/90d Sharpe windows and estimates edge half-life for decaying strategies.
- `skills/structural_analyzer.py::_detect_mismatches()` uses rule-based signal/exit mismatch detection, such as momentum signals paired with fixed take profit.
- `orchestrator/handlers.py::_run_allocation_analyses()` runs `StructuralAnalyzer` weekly and writes `structural_analysis.json`.
- `analysis/discovery_prompt_assembler.py::_DISCOVERY_INSTRUCTIONS` asks the discovery agent to find patterns outside the 25 automated detectors and to propose genuinely new strategy ideas when the raw evidence supports them.
- `orchestrator/handlers.py::handle_discovery_analysis()` persists strategy ideas and turns high-confidence ideas into structural experiment records.

Assessment:

This partially answers the mission's requirement for meaningful, high-value structural improvements and potentially new strategies. The gap is that this structural layer is not yet normalized into the same lifecycle diagnostic bundle as signal, entry, management, and exit evidence. It also does not yet get a causal validation path stronger than structural-experiment before/after checks.

### 4. Exit Mechanism

Exit analysis is present and better developed than entry simulation, but it still has implementation gaps.

Evidence:

- `schemas/events.py::TradeEvent` includes `exit_price`, `exit_reason`, `holding_minutes`, `mfe_pct`, `mae_pct`, `exit_efficiency`, and `post_exit_move_pct`.
- `skills/build_daily_metrics.py::exit_efficiency()` computes premature exits and post-exit opportunity.
- `skills/build_daily_metrics.py::build_excursion_stats()` aggregates exit and excursion statistics.
- `skills/exit_strategy_simulator.py::default_sweep_configs()` defines fixed stop, trailing stop, ATR stop, and time-based exit candidates.
- `skills/exit_strategy_simulator.py::simulate()` runs candidate exit configs and writes summary metrics.
- `orchestrator/handlers.py::_run_weekly_simulations()` runs default exit sweeps and stores `exit_sweep_<bot_id>`.
- `analysis/strategy_engine.py::detect_exit_timing_issues()` reads exit efficiency and premature exit percentage.

Assessment:

Exit analysis has a useful loop, but the simulator is incomplete. `skills/exit_strategy_simulator.py::default_sweep_configs()` includes `TRAILING_STOP`, but `_simulate_trade()` does not implement trailing-stop behavior. Also, weekly simulations produce exit-sweep outputs, but `_load_weekly_strategy_evidence()` only re-ingests `filter_interactions` from simulation results into deterministic strategy evidence. Exit sweep results are available to the weekly LLM prompt as `simulation_results`, but they do not appear to directly drive deterministic detectors.

Current capability:

- Measure exit efficiency.
- Detect likely premature exits.
- Run simple exit candidate sweeps.
- Provide exit-sweep evidence to LLM weekly analysis.

Not yet possible:

- Fully test trailing stops despite listing them in default configs.
- Feed exit-sweep winners directly into deterministic proposal generation.
- Evaluate exit changes against rich intratrade trajectories.
- Separate exit-rule weakness from entry and signal weakness.

## Critical Gaps Ranked by Impact

### P0: No Canonical Lifecycle Diagnostic Bundle

Evidence:

- Diagnostics are written across many daily metric files in `skills/build_daily_metrics.py::write_all()`.
- `analysis/context_builder.py::base_package()` loads many memory and diagnostic artifacts independently.
- `analysis/strategy_engine.py::build_report()` consumes a wide evidence object, but there is no stable schema that says "this is the lifecycle state of the bot."

Impact:

Each loop can see a different slice of evidence. Parameter search, LLM reasoning, structural validation, WFO, and outcome measurement do not share a single lifecycle diagnosis.

Target:

Add `schemas/lifecycle_diagnostics.py` with:

- `SignalExtractionDiagnostics`
- `EntryMechanismDiagnostics`
- `TradeManagementDiagnostics`
- `ExitMechanismDiagnostics`
- `PortfolioContextDiagnostics`
- `InstrumentationCoverage`
- `LifecycleWeakness`
- `LifecycleStrength`
- `ExperimentOpportunity`

Add `skills/lifecycle_diagnostic_builder.py` to construct this bundle from daily and weekly curated artifacts.

### P0: The Candidate Signal Universe Is Incomplete

Evidence:

- `schemas/events.py::MissedOpportunityEvent` can represent blocked signals, but only when bots emit them.
- `skills/signal_health_analyzer.py::compute()` relies on executed trades with `signal_evolution`.
- `skills/counterfactual_simulator.py::simulate_remove_filter()` only adds missed opportunities already attributed to a filter.

Impact:

The system cannot measure maximum available alpha or true discrimination quality unless every candidate signal and every rejected signal has sufficient forward-return backfill.

Target:

Require bots to emit a `SignalCandidateEvent` or enrich `MissedOpportunityEvent` coverage so every candidate includes:

- `signal_id`
- strategy and component scores
- full filter-decision vector
- indicator snapshot at decision time
- intended entry context
- forward returns at multiple horizons
- whether the candidate was accepted, rejected, delayed, or suppressed

### P0: Backtests Do Not Replay the Lifecycle

Evidence:

- `skills/backtest_simulator.py::_filter_trades()` only handles `signal_strength_min`.
- `skills/suggestion_validator.py::_replay_with_param()` handles a small set of parameter archetypes.
- `skills/exit_strategy_simulator.py::_simulate_trade()` falls back to actual PnL when post-exit data is unavailable and does not implement all configured exit types.

Impact:

The system can gather detailed diagnostics, but optimization often tests shallow parameter filters rather than realistic lifecycle changes.

Target:

Add lifecycle simulators:

- `skills/signal_extraction_replay.py`
- `skills/entry_mechanism_simulator.py`
- `skills/trade_management_simulator.py`
- `skills/exit_mechanism_simulator.py`

All should emit objective score deltas, lifecycle diagnostic deltas, sample sufficiency, and assumptions.

### P1: Instrumentation Scoring Lags the Schema

Evidence:

- `skills/instrumentation_scorer.py::_CAPABILITY_FIELDS` checks a small set of fields such as `signal_strength`, `mfe_pct`, `mae_pct`, and `fill_quality`.
- The optional file map in the same module does not fully cover newer curated outputs such as `fill_quality`, `filter_decisions`, `orderbook_stats`, `execution_latency`, `sizing_analysis`, and `signal_health`.

Impact:

The system may believe a bot is adequately instrumented even when critical lifecycle evidence is absent.

Target:

Update `InstrumentationScorer` around lifecycle capabilities:

- Signal extraction coverage
- Rejected-signal coverage
- Entry microstructure coverage
- In-trade state coverage
- Exit counterfactual coverage
- Sizing and portfolio coverage
- Deployment and experiment assignment coverage

### P1: Weekly Simulations Are Not Fully Integrated Into Deterministic Strategy Proposals

Evidence:

- `orchestrator/handlers.py::_run_weekly_simulations()` writes filter sensitivity, counterfactual, exit sweep, and filter interaction simulations.
- `orchestrator/handlers.py::_load_weekly_strategy_evidence()` re-ingests `filter_interactions` but not exit sweep, filter sensitivity, or counterfactual results into deterministic evidence.

Impact:

The LLM can see simulation results, but the deterministic engine does not consistently convert simulation winners into structured, trackable proposals.

Target:

Expand `_load_weekly_strategy_evidence()` and `analysis/strategy_engine.py` to consume all simulation outputs as first-class evidence.

### P1: Live and Backtest Lineage Are Not Strong Enough

Evidence:

- `schemas/events.py::TradeEvent` includes `strategy_params_at_entry`, but there is no universal deployment manifest linking every trade to code/config/strategy version and experiment assignment.
- `schemas/enriched_events.py::ParameterChangeEvent` exists, but learning loops do not consistently require it.
- `schemas/deployment_monitoring.py::DeploymentRecord` and `skills/deployment_monitor.py::DeploymentMonitor` already track approval request, suggestion ID, PR URL, parameter changes, merge/deploy timestamps, pre/post metrics, regression detection, and rollback PRs.

Impact:

Outcome measurement can mistake regime drift or unrelated config changes for the effect of a proposal. The existing deployment monitor helps catch gross regressions after approved PRs, but it does not yet provide per-event attribution for learning evaluation.

Target:

Extend the existing deployment-monitoring path and require every trade and missed candidate to include:

- `strategy_version`
- `config_version`
- `parameter_set_id`
- `experiment_id`
- `variant_id`
- `deployment_id`
- `signal_generation_version`

### P2: Structural Proposal Acceptance Criteria Need Lifecycle Binding

Evidence:

- `schemas/structural_experiment.py::AcceptanceCriteria` stores metric, direction, minimum change, observation window, minimum trade count, and baseline.
- `schemas/agent_response.py::StructuralProposal` does not require lifecycle stage.

Impact:

A structural proposal can define a metric without clearly identifying whether it targets signal extraction, entry, management, exit, portfolio, execution, or reliability.

Target:

Require `StructuralProposal.lifecycle_stage` and ensure acceptance criteria reference the relevant lifecycle diagnostic.

## Target Inner Loop

The optimal loop should run weekly and after major events:

```text
1. Build LifecycleDiagnosticBundle
2. Rank lifecycle weaknesses and strengths by expected value impact
3. For each ranked item:
   - identify whether this is parameter-sensitive, structural, instrumentation-limited, or regime-specific
   - generate candidate experiments
   - estimate offline validity and required live sample
4. Route:
   - parameter-sensitive -> ParameterSearcher or WFO
   - structural -> LLM design proposal and structural experiment
   - instrumentation-limited -> DiagnosticRequestPlanner
   - regime-specific -> segmented search or transfer proposal
5. Validate offline
6. Deploy as A/B, staged rollout, or observation-only experiment
7. Measure live outcome by lifecycle diagnostic delta and objective delta
8. Feed result to meta-learning loop
```

## Proposed Module Structure

### `schemas/lifecycle_diagnostics.py`

Core models:

- `LifecycleStage`: signal_extraction, entry, trade_management, exit, portfolio, execution, data_quality.
- `MetricObservation`: value, baseline, change, sample size, confidence, regime slices, source file.
- `LifecycleWeakness`: stage, diagnosis, impact estimate, evidence refs, confidence, missing diagnostics.
- `LifecycleStrength`: stage, diagnosis, impact estimate, evidence refs, confidence.
- `ExperimentOpportunity`: stage, mechanism, parameter candidates, structural candidates, instrumentation needs, offline evaluator, live acceptance criteria.
- `LifecycleDiagnosticBundle`: bot, strategy, window, regime mix, objective score, stage diagnostics, ranked weaknesses, ranked strengths.

### `skills/lifecycle_diagnostic_builder.py`

Responsibilities:

- Read curated daily/weekly artifacts from `data/curated/`.
- Normalize diagnostics into lifecycle stages.
- Attach source-file refs and sample counts.
- Compute instrumentation coverage by stage.
- Emit ranked weaknesses and strengths.

### `skills/lifecycle_experiment_planner.py`

Responsibilities:

- Convert `LifecycleWeakness` objects into experiment candidates.
- Decide whether each candidate is parameter, structural, or instrumentation-first.
- Attach evaluation method: greedy search, WFO, counterfactual replay, entry simulator, exit simulator, or live-only.
- Create `ProposalCandidate` records.

### `skills/alpha_capture_analyzer.py`

Responsibilities:

- Compute accepted versus rejected signal expectancy.
- Estimate alpha ceiling by signal component and regime.
- Compute false accept and false reject rates.
- Identify where filters saved bad trades versus blocked good trades.

### `skills/entry_mechanism_simulator.py`

Responsibilities:

- Compare immediate market entry, delayed entry, limit entry, spread-aware entry, liquidity-aware entry, and confirmation entry.
- Use order-book, fill, spread, latency, and adverse-excursion diagnostics.
- Emit entry-specific objective deltas.

### `skills/trade_management_simulator.py`

Responsibilities:

- Replay stop movement, scale-out, break-even, time-in-trade, portfolio heat, and exposure throttles.
- Use MFE/MAE paths when available.
- Mark results as low-confidence when only summary MFE/MAE exists.

### `skills/exit_mechanism_simulator.py`

Responsibilities:

- Replace or extend `skills/exit_strategy_simulator.py`.
- Implement fixed stop, ATR stop, trailing stop, time stop, signal-decay exit, and partial exits.
- Emit stage-specific deltas: MFE capture, giveback, premature exit rate, tail loss reduction.

## Required Instrumentation Additions

### Signal Extraction

- Emit every candidate signal, not only executed trades and selected missed opportunities.
- Include component scores, raw indicator values, filter vector, regime, liquidity context, and forward returns.
- Link accepted and rejected candidates with `signal_id`.
- Add signal calibration bins: predicted confidence versus realized expectancy.

### Entry

- Record intended order type, intended entry price, actual order type, actual fill, queue/limit behavior, spread, depth, imbalance, latency, and immediate adverse/favorable excursion.
- Record whether the entry was delayed, skipped, repriced, partially filled, or rejected.

### Trade Management

- Record per-bar or checkpointed in-trade state: unrealized PnL, MFE, MAE, stop, target, trailing stop, size, portfolio heat, correlation exposure, signal evolution.
- Record every stop/target adjustment and reason.
- Record scale-in/scale-out decisions.

### Exit

- Record exit trigger state: target, stop, time, signal decay, manual, risk cap, portfolio, exchange failure.
- Record post-exit path at multiple horizons.
- Record alternative exit triggers if known.
- Record trailing-stop path if trailing stops are evaluated.

### Experiment and Deployment

- Add `deployment_id`, `experiment_id`, `variant_id`, `parameter_set_id`, `config_version`, and `strategy_version` to every trade, missed opportunity, and signal candidate.
- Extend `schemas/deployment_monitoring.py::DeploymentRecord` or add a linked manifest file at activation and rollback, rather than creating an unrelated deployment system.

## Evaluation Metrics by Lifecycle Stage

### Signal Extraction

- Accepted signal expectancy
- Rejected signal expectancy
- False accept rate
- False reject rate
- Signal AUC or rank correlation
- Confidence calibration error
- Alpha capture ratio: accepted alpha divided by available candidate alpha
- Filter saved-bad versus blocked-good value
- Component stability by regime

### Entry

- Entry slippage in bps
- Fill quality
- Immediate adverse excursion
- Spread paid versus expected spread
- Latency impact
- Missed fill opportunity cost
- Entry timing contribution to R

### Trade Management

- MFE capture before exit
- MAE containment
- Stop efficiency
- Giveback after peak
- Heat-adjusted return
- Size efficiency
- Correlation-adjusted drawdown contribution
- Process-quality contribution

### Exit

- Exit efficiency
- Premature exit rate
- Tail-loss avoidance
- Post-exit opportunity cost
- Average giveback
- Exit-rule stability by regime
- Exit candidate objective delta

## Concrete Next Steps

### Phase 0: Fix Known Evaluation Holes

1. Implement `TRAILING_STOP` in `skills/exit_strategy_simulator.py::_simulate_trade()`.
2. Feed `exit_sweep`, `filter_sensitivity`, and `counterfactual` simulation results into `orchestrator/handlers.py::_load_weekly_strategy_evidence()`.
3. Update `skills/instrumentation_scorer.py` to score all current lifecycle diagnostic files and fields.
4. Add tests that weekly simulations appear in deterministic `StrategyEngine` evidence, not only LLM prompt data.

### Phase 1: Create the Lifecycle Diagnostic Bundle

1. Add `schemas/lifecycle_diagnostics.py`.
2. Add `skills/lifecycle_diagnostic_builder.py`.
3. Add bundle generation after `skills/build_daily_metrics.py::write_all()`.
4. Update `analysis/strategy_engine.py` to consume the bundle.
5. Update `analysis/weekly_prompt_assembler.py` to make lifecycle weaknesses and strengths first-class prompt sections.

### Phase 2: Expand the Candidate Universe

1. Add or enforce full candidate signal events.
2. Require indicator snapshots for accepted and rejected signals.
3. Require filter decisions for all filters on all candidate signals.
4. Add forward-return backfills for rejected candidates.
5. Add alpha-capture and discrimination metrics to daily metrics.

### Phase 3: Build Lifecycle Simulators

1. Split current backtest functionality into lifecycle-specific replay modules.
2. Start with signal/filter replay and exit replay because the repository already has the most data there.
3. Add entry replay when order-book/fill coverage is sufficient.
4. Add trade-management replay when in-trade state data is available.
5. Require every simulator result to include assumptions and confidence.

### Phase 4: Tie Lifecycle Evaluation to Experiments

1. Require every `AgentSuggestion` and `StructuralProposal` to declare lifecycle stage.
2. Attach lifecycle diagnostic refs to every parameter search and structural experiment.
3. Make live outcome measurement report both objective delta and lifecycle diagnostic delta.
4. Feed lifecycle deltas into `LearningCycle` and `HypothesisLibrary`.

## Definition of Done

The inner performance loop is complete when a weekly cycle can produce:

- A ranked lifecycle diagnosis for each bot and strategy.
- Quantified signal extraction, entry, trade-management, and exit weaknesses.
- Quantified strengths that should be preserved or amplified.
- A set of parameter experiments, structural proposals, and instrumentation tasks tied to those lifecycle diagnoses.
- Offline evaluation results using the best available lifecycle replay.
- Live validation criteria tied to objective score and lifecycle diagnostic deltas.
- A post-live outcome review that says whether the loop learned, what evidence was decisive, and what should be tried next.

At that point, the system will no longer merely report performance. It will diagnose where expectancy is created or lost, test targeted interventions, and compound knowledge about which interventions actually improve trading results.
