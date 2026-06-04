# Trading Assistant Workflow And Learning Loop Report

Date: 2026-05-10

> Historical report. Sections that discuss WFO or autonomous parameter search
> describe the pre-cleanup architecture; monthly validation is now the
> authoritative material strategy-learning path.

## 1. Purpose And Scope

This report describes how the trading assistant is intended to operate end to end:

- how remote trading bots send evidence into the local orchestrator;
- what the orchestrator does daily, weekly, and on longer cadences;
- how agent runtimes, deterministic analysis, simulations, proposal tracking, and outcome measurement form a learning loop;
- how the system proposes high-value trading improvements grounded in evidence;
- what the system does not do;
- limitations, pitfalls, and missing requirements that affect whether the loop can reliably improve live trading performance.

The report is based on the current repository implementation, especially:

- `orchestrator/app.py`
- `orchestrator/adapters/vps_receiver.py`
- `orchestrator/db/queue.py`
- `orchestrator/orchestrator_brain.py`
- `orchestrator/worker.py`
- `orchestrator/handlers.py`
- `orchestrator/scheduler.py`
- `orchestrator/catchup.py`
- `analysis/context_builder.py`
- `analysis/strategy_engine.py`
- `analysis/response_parser.py`
- `analysis/response_validator.py`
- `orchestrator/agent_runner.py`
- `skills/build_daily_metrics.py`
- `skills/build_weekly_metrics.py`
- `skills/suggestion_tracker.py`
- `skills/proposal_ledger.py`
- `skills/auto_outcome_measurer.py`
- `skills/suggestion_scorer.py`
- `skills/parameter_searcher.py`
- `skills/run_wfo.py`
- `skills/backtest_simulator.py`
- `skills/learning_cycle.py`

## 2. Executive Summary

The trading assistant is a read-only observability, analysis, and improvement-orchestration layer for trading bots. It ingests structured events from bots, deduplicates and stores them, builds daily and weekly evidence packages, invokes agent runtimes for interpretation, generates deterministic and LLM-assisted improvement proposals, routes eligible proposals through validation, search, approval, PR creation, and later measures whether deployed changes improved live outcomes.

Its strongest design choice is the separation between:

- deterministic event routing;
- deterministic metric construction;
- agent-generated interpretation;
- validation and approval gates;
- measured post-deployment outcomes.

That separation reduces the chance that an LLM can directly mutate trading behavior. The system does not send live trading commands to bots. Trading logic, filters, risk, sizing, portfolio allocation, deployment, and safety-critical changes are gated by approval or double approval.

The system is not yet a fully causal optimizer. It can prioritize plausible improvements, search parameter neighborhoods, run simplified backtests and walk-forward optimization, and measure before/after live results. However, its conclusions depend heavily on data completeness, realistic cost modeling, accurate missed-opportunity backfills, deployment attribution, sufficient sample sizes, and whether simulations faithfully represent the live strategy engine.

The system is best understood as an evidence-ranked proposal engine with a closed feedback loop. It can become a high-value improvement machine if the bot instrumentation contract is complete and if backtests, WFO, and experiments are treated as decision support rather than proof.

## 3. System Boundary

### What It Does

- Polls or receives structured events from remote trading bots.
- Deduplicates events using deterministic event IDs.
- Stores events in SQLite and raw JSONL files.
- Builds curated daily and weekly metrics.
- Runs deterministic strategy detectors.
- Invokes configurable agent runtimes for analysis and report generation.
- Parses and validates structured suggestions from reports.
- Tracks proposals, approvals, deployments, outcomes, forecasts, hypotheses, experiments, and category-level calibration.
- Sends reports and approval requests through communication channels.
- Can create approval-gated PRs or implementation tasks for bot repositories when autonomous repo tooling is enabled and configured.

### What It Does Not Do

- It does not directly place, cancel, or modify live orders.
- It does not directly push trading commands back to bots.
- It does not autonomously change trading logic without the configured approval path.
- It does not guarantee causal attribution from before/after outcomes.
- It does not make event routing decisions through an LLM.
- It does not provide a substitute for realistic strategy backtesting, exchange simulation, independent deployment verification, or exchange-level controls.

## 4. End-To-End Architecture

```text
BOT / VPS SIDE
  Trading bots
    emit trades, missed opportunities, snapshots, errors, health, filters, orders
        |
        v
  Relay VPS or direct /ingest
    stores events until the orchestrator pulls and acknowledges them

LOCAL ORCHESTRATOR INGESTION
  VPSReceiver / ingest API
    normalizes envelope, records latency, enforces basic ingest limits
        |
        v
  SQLite EventQueue
    deduplicates by event_id, retries failures, dead-letters exhausted events
        |
        v
  Worker + deterministic Brain
    routes events without LLM calls
    daily evidence -> data/raw/<date>/<bot>/*.jsonl
    high errors -> triage
    scheduled triggers -> daily, weekly, WFO, notification handlers

EVIDENCE AND ANALYSIS
  Daily metrics builder
    raw events -> curated bot and portfolio metrics
        |
        +--> Daily report
        |      QualityGate -> DailyTriage -> PromptPackage -> AgentRunner
        |
        +--> Weekly report
        |      weekly aggregation -> StrategyEngine -> simulations -> AgentRunner
        |
        +--> WFO
               historical curated trades/missed -> folds -> optimization -> review

PROPOSAL CONTROL
  Parser + ResponseValidator
    extracts structured suggestions, blocks unsafe or weak proposals
        |
        v
  SuggestionTracker + ProposalLedger
    records provenance, status, evaluations, approvals, deployments, outcomes
        |
        v
  Autonomous pipeline, if enabled
    parameter search / backtest / experiment routing -> approval request
        |
        v
  ApprovalHandler
    human approval or double approval -> PR / repo task

OUTSIDE ORCHESTRATOR BOUNDARY
  Bot repository PRs and deployments
    code/config changes are reviewed, merged, and deployed outside the event router
        |
        v
  Future bot events include new outcome evidence and, ideally, deployment lineage

LEARNING FEEDBACK
  Outcome measurement
    compares before/after windows, regimes, volatility, concurrent changes
        |
        v
  Memory and calibration
    scorecards, rejected patterns, hypotheses, forecasts, experiments, lessons
        |
        +--> future daily, weekly, WFO, validation, and proposal scoring
```

## 5. Bot Interaction Workflow

### 5.1 Expected Bot Events

Bots are expected to emit structured event data, usually through a sidecar or relay. The intended event families are:

- trade events;
- missed opportunity events;
- daily snapshots;
- error events;
- health and process-quality events;
- filter decisions;
- order lifecycle events;
- market snapshots;
- indicator snapshots;
- parameter changes;
- stop adjustments;
- execution and slippage context;
- portfolio rule checks.

Useful learning depends on each event carrying consistent metadata:

- `event_id`
- `bot_id`
- `event_type`
- exchange timestamp;
- local timestamp;
- clock skew;
- data source ID;
- bar ID;
- strategy or engine identity where relevant;
- payload with root causes, filters, signal state, trade outcome, costs, and regime context.

### 5.2 Relay Polling

`orchestrator/adapters/vps_receiver.py` implements the relay polling flow:

1. The orchestrator calls the relay endpoint with `GET /events?since=<watermark>&limit=<limit>`.
2. It optionally sends `X-Api-Key` using `RELAY_API_KEY`.
3. Each relay event is normalized into the local queue event shape.
4. The receiver records latency if a latency tracker is attached.
5. Events are inserted into `EventQueue.enqueue_batch`.
6. Accepted events are acknowledged back to the relay with `POST /ack`.
7. The receiver advances the local watermark.
8. Failures return zero events and increment backoff state rather than crashing the orchestrator.

This gives the assistant an idempotent pull-based integration with remote VPSes. The relay can retain events until acknowledgement, and the orchestrator can recover missed events after local downtime.

### 5.3 Direct Ingest

`orchestrator/app.py` also exposes direct ingestion. The normalizer requires:

- `event_id`
- `bot_id`
- `event_type`
- `payload`

It rejects unknown bot IDs unless the event is from a configured system source. It enforces a payload size limit of 256 KB. User feedback payloads are sanitized before they can reach an agent prompt. Non-feedback bot payloads are trusted as structured telemetry and are not sanitized in the same way, which is a risk if bot-side payload fields can contain arbitrary text.

### 5.4 Queue Semantics

`orchestrator/db/queue.py` stores events in SQLite:

- `event_id` is the primary key.
- inserts use `INSERT OR IGNORE`, making duplicate ingestion idempotent;
- statuses include `pending`, `processing`, `acked`, `failed`, and `dead_letter`;
- worker claims are atomic;
- failed events are retried until `max_retries`, then moved to dead letter;
- stale `processing` events can be recovered.

This is appropriate for a single-user local orchestrator. It avoids Postgres or Redis but should not be treated as a horizontally scalable queue.

## 6. Deterministic Routing And Persistence

`orchestrator/orchestrator_brain.py` routes events without LLM calls.

High-level behavior:

- trade and missed-opportunity events are queued for daily analysis;
- daily snapshots, health reports, filter decisions, process quality, portfolio checks, market snapshots, and similar telemetry are queued for daily analysis;
- critical errors create alerts and are also included in daily evidence;
- high errors can trigger bug triage unless storm suppression applies;
- low errors are queued for weekly counts only;
- scheduler trigger events spawn daily, weekly, WFO, notification, and other handlers;
- unknown events are logged rather than interpreted by an agent.

`orchestrator/worker.py` persists daily-analysis events into:

```text
data/raw/<bot-local-date>/<bot_id>/<event_type>.jsonl
```

The bot-local date comes from the per-bot timezone mapping. This is important because daily analysis should align with the bot's trading session rather than the orchestrator host timezone.

One limitation: weekly-only events are counted but not necessarily persisted as raw evidence. Low-severity errors routed only to weekly analysis may therefore be underrepresented unless another path writes them to durable weekly evidence.

## 7. Scheduling And Catch-Up

The scheduler is APScheduler-based and supports:

- interval jobs;
- cron jobs;
- stateful catch-up;
- coalesced catch-up;
- scheduled run tracking in SQLite;
- startup recovery of missed scheduled jobs.

Default recurring work includes:

| Cadence | Job | Purpose |
|---|---|---|
| Every 60 seconds | Worker drain | Process pending queue events. |
| Every 5 minutes | Relay poll | Pull new events from the relay VPS. |
| Every 60 minutes | Monitoring | Emit queue, latency, agent, error, and report readiness metrics. |
| Daily | Daily analysis | Build daily curated metrics and report. |
| Daily morning | Morning scan | Check dead letters and previous-day loss conditions. |
| Daily evening | Evening scan | Check whether the day's report and summary are ready. |
| Daily | Reliability verification | Verify recommendation or backtest reliability. |
| Weekly Sunday | Weekly summary | Aggregate available daily summaries across the seven-calendar-day week and run weekly strategy analysis. |
| Weekly Sunday | Outcome measurement | Measure deployed suggestions and portfolio outcomes. |
| Weekly Sunday | Memory consolidation | Consolidate findings and correction patterns. |
| Weekly Sunday | Threshold learning | Learn threshold performance patterns when adaptive thresholds are enabled. |
| Weekly Sunday | Learning cycle | Synthesize outcomes, hypotheses, experiments, and calibration. |
| Weekly Saturday | Discovery | Search for new strategy ideas or patterns. |
| Weekly Saturday by default | WFO | Run walk-forward optimization for configured bots. |
| Daily | Approval expiry | Expire stale approval requests when the approval tracker is enabled. |
| Every 60 minutes | PR review check | Check PR review state when the approval tracker is enabled. |
| Every 6 hours | Experiment check | Evaluate A/B experiments when enabled and mature structural experiments. |
| Every 30 minutes | Deployment check | Check pending deployment statuses when deployment monitoring is enabled. |

When bot-specific market sessions are configured, daily, morning, and evening jobs are grouped by bot trigger time. Trigger times are derived from market close plus configured delay.

Potential issue: grouped trigger times are computed at scheduler startup using the current date. If daylight saving offsets change while the process keeps running, trigger times may be stale until restart unless the implementation refreshes schedules.

## 8. Daily Workflow

```text
daily_analysis_trigger
        |
        v
Resolve run scope
  date, bot list, run_id, scheduled-run identity
        |
        v
Rebuild daily curated data
  data/raw/<date>/<bot>/*.jsonl
      -> data/curated/<date>/<bot>/*
      -> portfolio curated files
        |
        v
QualityGate
  blocking failure -> notify "daily_report_blocked" and stop
  degraded failure -> continue with degraded marker
        |
        v
Minimum trade check
  fewer than required trades -> deterministic light-day summary, no agent
        |
        v
Context and triage
  ContextBuilder loads memory, outcomes, scorecards, active suggestions,
  corrections, reliability, instrumentation readiness, and related context
  DailyTriage selects significant events and focus questions
        |
        v
Prompt assembly and agent run
  DailyPromptAssembler -> PromptPackage
  AgentRunner invokes configured daily_analysis provider
        |
        v
Parse and validate
  ResponseParser extracts structured output
  ResponseValidator blocks or degrades unsafe, weak, or repeated suggestions
        |
        v
Record learning artifacts
  suggestions -> SuggestionTracker + ProposalLedger
  predictions -> PredictionTracker
  learning-card feedback -> findings
  autonomous pipeline may create approval requests if enabled
        |
        v
Write and notify
  runs/<run_id>/daily_report.md
  parsed_analysis.json and validator notes
  Telegram / Discord / email dispatch according to configured channels
```

`orchestrator/handlers.py::handle_daily_analysis` performs the following:

1. Determines the run scope, date, bots, and run ID.
2. Rebuilds curated daily data from raw JSONL files.
3. Uses `DailyMetricsBuilder` and specialized analyzers to produce bot-level and portfolio-level metrics.
4. Runs data quality checks.
5. Skips agent invocation if there are fewer than the minimum required trades for meaningful analysis.
6. Loads memory, active suggestions, correction patterns, scorecards, previous outcomes, and instrumentation readiness through `ContextBuilder`.
7. Runs `DailyTriage` to identify significant events and focus questions.
8. Assembles a `PromptPackage` for the agent.
9. Invokes the configured agent runtime.
10. Parses structured JSON from the agent's report.
11. Validates suggestions with `ResponseValidator`.
12. Records approved or degraded suggestions into trackers and ledgers.
13. Records learning-card feedback and predictions where present.
14. Writes the report and dispatches notifications.

Daily curated outputs can include:

- summary metrics;
- winners and losers;
- process failures;
- missed opportunities;
- root-cause statistics;
- regime performance;
- filter effectiveness;
- factor attribution;
- exit efficiency;
- slippage and excursion metrics;
- hourly performance;
- order lifecycle;
- fill quality;
- indicator snapshots;
- order book context;
- parameter changes;
- process quality;
- execution latency;
- sizing behavior;
- applied regime configuration;
- stop-adjustment behavior;
- portfolio exposure, concentration, and risk-card context.

The daily workflow is primarily observational and diagnostic. It can identify problems and produce proposals, but it is not the main place where robust multi-day evidence is established.

## 9. Weekly Workflow

```text
weekly_summary_trigger
        |
        v
Data precheck and aggregation
  verify recent curated days per bot
  WeeklyMetricsBuilder -> data/curated/weekly/<week_start>/weekly_summary.json
        |
        v
Deterministic evidence pass
  load signal health, factor history, strategy evidence, scorecards,
  detector confidence, recent suggestions, and convergence context
        |
        v
StrategyEngine
  run detectors for parameters, filters, regimes, exits, sizing,
  execution, correlation, crypto context, and portfolio coordination
        |
        v
Simulation and portfolio analysis
  filter sensitivity, regime counterfactuals, exit sweep,
  filter interactions, synergy, allocation, proportion, structural analysis
        |
        v
Record deterministic suggestions
  StrategyEngine suggestions -> SuggestionTracker + ProposalLedger
  autonomous pipeline may route actionable items if enabled
        |
        v
Weekly prompt and agent run
  WeeklyTriage -> WeeklyPromptAssembler -> AgentRunner
        |
        v
Parse, validate, and persist
  ResponseParser -> ResponseValidator
  approved suggestions, portfolio proposals, predictions, hypotheses,
  patterns, and transfer candidates are recorded
        |
        v
Write and notify
  runs/<run_id>/weekly_report.md
  parsed_analysis.json, validator notes, and configured channel delivery
```

The weekly workflow is where the system tries to convert accumulated evidence into actionable improvement candidates.

Mechanism: weekly data is first reduced into comparable evidence objects
(`weekly_summary.json`, rolling metrics, scorecards, detector confidence,
recent suggestions, and convergence context). `StrategyEngine` maps that
evidence into concrete `StrategySuggestion` records with bot, category,
confidence, evidence window, impact estimate, target parameter when available,
and detector context. These `StrategySuggestion` objects are deterministic
detector outputs, not LLM outputs; LLM-generated suggestions are parsed
separately as `AgentSuggestion` records. Simulation and portfolio analyzers add what-if evidence;
the report is rebuilt so detector suggestions can reference those results.
Weekly triage then selects anomalies and retrospective questions for the agent.
The weekly prompt packages the refinement report, simulations, allocation
analysis, outcomes, rejected patterns, scorecards, and active hypotheses, and
requires machine-readable suggestions or structural proposals. Parsed output is
validated; approved candidates are recorded in `SuggestionTracker` and
`ProposalLedger`, optionally routed to parameter search, WFO/backtest review,
approval, or experiments, and later measured by the learning loop.

It performs:

- weekly aggregation from available daily summaries in the seven-calendar-day window, usually five populated summaries for weekday-only markets and up to seven for always-on markets;
- deterministic strategy detection;
- event-level simulation and counterfactual analysis where curated trade,
  missed-opportunity, filter, exit, and market-context telemetry exists;
- portfolio-level analysis;
- triage of weekly focus areas;
- LLM-assisted weekly interpretation;
- suggestion parsing and validation;
- proposal tracking;
- autonomous approval routing where enabled;
- experiment and hypothesis lifecycle updates.

`analysis/strategy_engine.py` generates deterministic suggestions from evidence. Detector families include:

- parameter and stop behavior;
- filter cost and filter interaction;
- regime losses and regime gating;
- signal decay;
- factor and component performance;
- exit timing;
- correlation concentration;
- time-of-day performance;
- drawdown concentration;
- position sizing;
- microstructure and execution bottlenecks;
- macro regime configuration;
- portfolio crowding;
- crypto-specific funding, leverage, confluence, session, and liquidation signals;
- family imbalance and portfolio coordination.

The engine applies safeguards:

- minimum evidence thresholds;
- recent suggestion deduplication;
- anti-oscillation logic;
- outcome scorecard adjustment;
- detector confidence adjustment;
- category value map adjustment;
- suppression of categories with poor historical outcomes.

Here, simulation-backed analysis means lightweight event-level replay over curated bot evidence. It does not mean full intraday bar, order-book, or tick replay unless the bots have emitted enough telemetry to reconstruct those states. Weekly simulations load curated trades and missed opportunities, then run filter sensitivity, regime counterfactual, exit-sweep, and filter interaction analyses from those records.

Practical expectation: this is a diagnostic triage layer. It can surface evidence-backed hypotheses about filter opportunity cost, filters that prevented losses, regime or session concentration, redundant filter pairs, and exit alpha visible in post-exit snapshots. It contributes to performance improvement indirectly by strengthening weekly reports, ranking candidate changes, rejecting weak ideas, and routing promising changes into approval, WFO/backtest review, or live experiments. It is not causal proof and must not justify unattended production trading changes.

The weekly report is therefore a combination of deterministic evidence, event-level simulation outputs, and agent synthesis.

## 10. Walk-Forward Optimization Workflow

`orchestrator/handlers.py::handle_wfo` runs WFO per bot.

```text
wfo_trigger for one bot
        |
        v
Load WFO configuration
  data/wfo_configs/<bot>.yaml if present, otherwise default WFOConfig
        |
        v
Load historical curated evidence
  trades and missed opportunities over the required lookback window
        |
        v
Generate temporal folds
  in-sample window -> out-of-sample window, repeated by step size
        |
        v
Optimize and validate
  in-sample grid search per fold
  out-of-sample simulation using each fold's best parameters
        |
        v
Aggregate and stress test
  consensus parameters
  aggregate OOS simulation
  cost sensitivity
  robustness neighborhood and regime stability
  leakage audit
        |
        v
Recommendation
  REJECT, TEST_FURTHER, or ADOPT
        |
        v
Agent review and tracking
  WFO report -> AgentRunner review
  non-reject recommendations -> SuggestionTracker + ProposalLedger
```

`skills/run_wfo.py` performs:

1. fold generation;
2. in-sample parameter optimization;
3. out-of-sample validation;
4. consensus parameter selection;
5. aggregate out-of-sample simulation;
6. cost sensitivity checks;
7. robustness checks;
8. leakage audit;
9. deterministic recommendation.

Current WFO uses temporal splits over curated event-level evidence, not market data. By default, `WFOConfig` is anchored with a 180-day in-sample window, a 30-day out-of-sample window, a 30-day step, and a six-fold minimum. The handler derives the required lookback as:

```text
in_sample_days + out_of_sample_days + step_days * (min_folds - 1)
```

With defaults, that is `180 + 30 + 30 * 5 = 360` calendar days. In anchored mode, the in-sample start stays fixed while the in-sample end grows by `step_days`; the 30-day OOS window immediately follows each in-sample window. In rolling mode, the in-sample window keeps fixed length and slides forward by `step_days`. The scheduled cadence is weekly, Saturday 02:00 UTC per bot by default, but the default OOS window is 30 days, not one week. A custom `data/wfo_configs/<bot>.yaml` can change the method and window lengths.

Without full market data, WFO can only test parameters that the simplified event replay knows how to apply to historical trade and missed-opportunity records. It is useful for screening whether a proposed parameter is robust across time slices of observed events. It cannot prove that the live bot would have generated the same trades under alternate parameters, and it cannot test parameters whose effects require replaying raw bars, order book state, signal generation, or exit mechanics. If no bot-specific parameter space is configured, the default WFO has no meaningful optimization surface and should reject or produce no actionable recommendation.

Recommendations can become suggestions and calibration predictions. They still pass through the normal proposal tracking and approval flow.

WFO is valuable as a discipline because it separates optimization and validation windows. However, the current implementation should be treated as a screening tool, not as final proof. See section 17 for specific concerns.

### 10.1 Recommended Monthly Backtest-Parity Repair Loop

The stronger recommendation is a monthly full-fidelity backtest-parity and mutation-repair workflow, not an extension of the current event-level WFO. The reference code already contains the two useful patterns:

- shared phased auto framework: `backtests/shared/auto`;
- shared latest-period smoke runner:
  `backtests/shared/smoke/latest_oos_smoke.py`, built on
  `backtests/shared/validation/oos_validation.py`;
- strategy repair diagnostics: `backtests/swing/auto/oos_repair_diagnostics.py`,
  `backtests/swing/auto/incumbent_repair.py`, and the moved research runners in
  `backtests/scripts`.

The optimal design is one shared monthly framework with two strategy-level evaluation modes:

- phased-auto mode for mature strategies with strategy plugins, known candidate phases, hard gates, diagnostics, and sequential greedy selection;
- smoke-repair mode for faster OOS failure attribution, one-at-a-time ablation, local perturbation, prior-value rollback, and targeted candidate ranking against a frozen incumbent. The reusable smoke entry point should be `backtests/shared/smoke/latest_oos_smoke.py`; strategy-specific repair runners should extend it or consume its outputs rather than duplicating latest OOS window resolution and coverage checks.

```text
Month-end data sync
  canonical market parquet, bot telemetry, costs, fills, configs, deployments
        |
        v
Coverage and parity audit
  verify data reaches month end; reproduce incumbent IS/backtest metrics
        |
        v
Freeze monthly run
  strategy, production config, accepted mutation sequence, latest live month
        |
        v
Latest-month parity diagnosis
  compare live/OOS month to same-config backtest expectation
  under-trading, outlier losses, cost/fill drift, regime mismatch,
  accepted-mutation regressions, or missing telemetry
        |
        v
Strategy-level candidate suite
  accepted-prefix checks, single-key rollback, cluster rollback,
  numeric perturbation, boolean flips, targeted weakness candidates
        |
        v
Evaluation mode
  phased-auto greedy OR broad smoke-repair ranking
  full calibration, purged validation folds, latest-month selection OOS
        |
        v
Decision path
  keep, revert, adjust, create challenger, route to experiment/approval, reject
```

The shared framework should own cadence, data coverage checks, phase state,
greedy orchestration, smoke-test orchestration, scoring/gate protocol,
diagnostics, retry policy, artifact layout, provenance, and report/approval
routing. Each strategy plugin should own data loading, replay, mutation
semantics, candidate generation, metrics extraction, phase gates, and
strategy-specific diagnostics.

Ablation and perturbation should be strategy-level, not portfolio-global,
because mutation keys, config meanings, engine inputs, trade frequency, and
risk gates differ by strategy. For each strategy, the monthly loop should:

1. Compare actual monthly OOS performance with the relevant backtest expectation.
2. Attribute gaps to under-trading, edge-case losses, cost/fill drift, regime
   mismatch, or accepted low-value mutations.
3. Ablate accepted mutations by dropping or reverting each key to its prior
   value where possible.
4. Perturb active numeric or boolean mutations locally.
5. Add targeted candidates derived from diagnosed OOS weaknesses.
6. Run phased greedy search only after diagnosis, accepting changes that improve
   the canonical objective while fixing under-trading where relevant and
   passing no-regression gates.
7. Run portfolio/synergy checks on shortlisted strategy-level candidates before
   approval or experiment routing.

The objective should use the existing `soul.md` / `objective_weights_v1`
composite rather than inventing a separate monthly objective: net profit or
expected return, Calmar, profit factor, expectancy, max drawdown, and process
quality, with process quality omitted and the remaining weights renormalized
where replay cannot simulate it. Trade frequency should be treated as an
important viability and under-trading gate, not as a standalone target that can
override expectancy or drawdown. Typical acceptance gates should require
latest-month OOS improvement, no material IS deterioration, positive support
across purged validation folds, realistic cost sensitivity, sufficient trade
count, and no large increase in concentrated losses or drawdown.

This should not be implemented as a single-fold anchored WFO. The latest
completed month has two possible roles in the monthly cycle. First, it is used
as validation of the current production configs: did the incumbent strategies
perform like the backtest expectation, and if not, what failed? If repair is
triggered, the same month can then be used as a selection-OOS gate for candidate
mutations. At that point it is no longer a fresh holdout for those mutations.
The next month, a later lockbox, or a controlled live experiment must provide
the next validation layer.

Recommended windowing:

- latest completed month: fixed one-month parity window for incumbent
  validation, then selection-OOS if used to choose candidate mutations;
- trailing 3-6 months: supplementary context when one month has too few trades;
- calibration window: all reliable data before the latest month, anchored and
  growing over time;
- internal validation: purged monthly or quarterly folds inside calibration,
  with an embargo around fold boundaries;
- rolling 12-24 month calibration: secondary sensitivity check when older
  regimes may dominate the anchored history.

In phased-auto mode, candidate mutations should be optimized on the calibration
window and internal purged folds, then retained only if they also perform well
on the latest one-month selection-OOS window. In smoke-repair mode, candidates
are ranked by whether they improve the latest month while also preserving
calibration performance and fold robustness.

The OOS window should not grow indefinitely for candidate selection because it
would dilute recent failure modes. In-sample should not be fixed at 180 days
unless that is all the reliable data available. The primary calibration set
should grow as more historical data becomes available, with rolling-window
sensitivity used to detect stale-regime dependence.

Data requirements are stricter than the current event-level workflow. The live
bots do not need to be the primary monthly market-data downloader. Prefer a
canonical data-sync job owned by `trading_assistant` or a shared backtest host
that writes versioned parquet and coverage manifests. Bots should continue to
emit decision telemetry, fills, costs, config versions, deployment IDs, and
mutation lineage. If a bot has the only reliable source of a traded data feed,
it may upload monthly parquet plus checksums, but that should be a fallback, not
the preferred architecture.

Without canonical market data, a full-fidelity backtest adapter, exact
strategy/config replay, and reliable mutation/deployment provenance, this loop
can produce useful diagnostics but not robust optimization decisions.

## 11. Agent Runtime Workflow

`orchestrator/agent_runner.py` invokes agent providers per task rather than running them as daemons.

Provider support includes:

- Claude CLI;
- Codex CLI;
- Z.AI through a redirected runtime;
- OpenRouter through a redirected runtime.

The runner:

1. receives a `PromptPackage`;
2. writes a task run folder;
3. writes prompt files, data files, metadata, and instructions;
4. builds a provider-specific invocation;
5. applies workflow-specific tuning such as timeout, max turns, and allowed tools;
6. runs the runtime;
7. records cost and run metadata;
8. returns markdown and structured output for parsing.

Agent invocations are stateless. All required memory and data must be assembled into the run folder and prompt package.

## 12. Context And Memory

`analysis/context_builder.py` is the main bridge between raw evidence, accumulated learning, and agent prompts.

It can include:

- policy documents;
- correction patterns;
- failure logs;
- rejected suggestions;
- active suggestions;
- recent outcomes;
- proposal ledger outcomes;
- category scorecards;
- regime-stratified scorecards;
- prediction accuracy;
- forecast calibration;
- hypothesis track records;
- transfer proposal outcomes;
- experiment records;
- validation patterns;
- threshold learning;
- reliability summaries;
- discovery reports;
- retrospective synthesis;
- generated playbooks;
- strategy registry and profiles;
- risk configuration;
- portfolio context;
- macro regime context;
- run history from similar prior runs.

This design makes agent behavior less dependent on hidden conversation memory. It also means context quality, pruning, and priority ordering matter. If critical evidence is excluded by budget pressure or unavailable because data was never generated, the agent can produce plausible but weak proposals.

## 13. Learning Loop

```text
1. Evidence
   bot events -> raw JSONL -> curated daily, weekly, portfolio, and WFO data
        |
        v
2. Candidate generation
   StrategyEngine, agents, WFO/monthly replay repair, portfolio analyzers,
   discovery, transfer proposals, hypotheses, experiments, and human feedback
        |
        v
3. Validation and scoring
   ResponseValidator, category scorecards, calibration, safety rules,
   duplicate/rejection checks, portfolio guardrails, and search evidence
        |
        v
4. Proposal tracking
   SuggestionTracker records lifecycle status
   ProposalLedger records candidate, evaluation, and outcome provenance
        |
        v
5. Decision path
   discard weak ideas
   route uncertain ideas to experiments
   request approval or double approval for trading changes
        |
        v
6. Implementation boundary
   approved repo tasks or PRs are reviewed, merged, and deployed outside
   the deterministic event router
        |
        v
7. Measurement and learning
   outcome measurement, portfolio outcomes, prediction evaluation,
   outcome reasoning, scorecards, hypotheses, recalibration, and lessons
        |
        +--> future context, validation, StrategyEngine scoring, and prompts
```

The loop has seven stages.

### 13.1 Evidence Creation

Evidence begins as bot events and daily summaries. Curated metrics transform event streams into structured features:

- outcome metrics;
- regime labels;
- root causes;
- filter decisions;
- missed opportunity outcomes;
- execution quality;
- slippage;
- process quality;
- parameter changes;
- portfolio exposure;
- market context.

Evidence quality depends directly on bot instrumentation. Missing costs, missing missed-opportunity outcomes, inconsistent strategy IDs, or absent config versions materially weaken downstream conclusions.

### 13.2 Candidate Generation

Candidates come from multiple sources:

- deterministic `StrategyEngine` detectors;
- daily and weekly agent reports;
- WFO recommendations;
- monthly backtest-parity repair candidates;
- portfolio analyzers;
- hypothesis library updates;
- transfer proposal builder;
- discovery jobs;
- threshold learning;
- experiments;
- human feedback.

This diversity is useful because deterministic detectors can catch known failure modes while agents can synthesize broader patterns.

### 13.3 Validation And Filtering

`analysis/response_validator.py` filters or degrades suggestions using:

- previously rejected similar proposals;
- retired or unknown strategy IDs;
- unsafe crypto leverage or risk proposals;
- weak category track records;
- poor forecast calibration;
- low structural confidence;
- invalid acceptance criteria;
- missing evidence windows;
- excessive portfolio allocation or risk-cap changes;
- permission-sensitive behavior.

Deterministic strategy suggestions also pass through confidence adjustment, anti-oscillation logic, recent duplicate detection, and category outcome scorecards.

Important nuance: some degraded suggestions may still be recorded with review flags rather than being completely dropped. This preserves traceability but can create noise if reviewers treat every recorded suggestion as equally credible.

### 13.4 Proposal Tracking

Two tracking systems are central:

- `SuggestionTracker`: JSONL-backed lifecycle for suggestions and measured outcomes.
- `ProposalLedger`: append-only event ledger for candidate, evaluation, approval, deployment, and outcome events.

The lifecycle is roughly:

```text
proposed -> accepted -> merged -> deployed -> measured
```

Legacy or alternate statuses such as implemented and rejected are also supported.

Concrete routing:

- weekly deterministic `StrategySuggestion` objects are recorded by
  `_record_suggestions()` as proposed `SuggestionRecord` rows and
  `ProposalLedger` candidates;
- approved agent suggestions are recorded by `_record_agent_suggestions()`,
  with lightweight validation evidence when a parameter/value can be replayed;
- immediately after recording, `_run_autonomous_pipeline()` is called, but it
  only acts when the autonomous pipeline is configured;
- WFO does not normally consume weekly `StrategySuggestion` records directly:
  it runs as its own scheduled workflow and records non-reject WFO results as
  separate proposed suggestions;
- outcome measurement only considers suggestions that reached `DEPLOYED`.

The proposal ledger is the better long-term audit source because it records candidate provenance and evaluation events across deterministic, LLM, WFO, structural, and portfolio proposal types.

Recommended optimal tracking model:

- keep `ProposalLedger` as the exhaustive append-only event log for every
  candidate, evaluation, rejection, experiment, approval, deployment, and
  outcome;
- keep `SuggestionTracker` as the lifecycle tracker for actionable suggestions;
- add a strategy-centric `StrategyChangeLedger` as the canonical changelog for
  material strategy changes and monthly no-change reviews.

`StrategyChangeLedger` should not replace the existing ledgers. It should join
them into one auditable record per strategy change or monthly review:

```text
strategy_id / bot_id
record_type: review | proposed_change | deployed_change | rollback
old_config_version -> new_config_version
mutation_diff: added, removed, changed keys
reason: evidence-backed mechanism and decision rationale
source_proposal_ids / suggestion_ids / approval_request_id
backtest, smoke, WFO, experiment, or live evidence paths
approval decision, PR URL, commit SHA, deployment ID
post-deployment outcome and rollback status
```

For monthly replay repair, the broad candidate set should remain in
`ProposalLedger`; only selected candidates, deployed changes, rollbacks, and
explicit "no change because evidence was insufficient" decisions should enter
`StrategyChangeLedger`. This gives a direct answer to what changed, when it
changed, why it changed, and whether it later worked.

### 13.5 Approval And Implementation

`skills/autonomous_pipeline.py` can route eligible suggestions into approval workflows if `AUTONOMOUS_ENABLED` is set. This path is disabled by default.

For parameter and filter proposals:

1. Resolve the suggestion to a known config parameter.
2. Validate parameter type and range.
3. Load recent curated trade data.
4. Run parameter search or the legacy single-value backtest.
5. Route to one of:
   - discard;
   - experiment;
   - approval request.

For structural proposals:

1. Check that file changes or implementation notes exist.
2. Apply repository guardrails.
3. Determine risk tier.
4. Escalate low-reliability or safety-sensitive changes.
5. Create approval requests rather than direct changes.

Approval-request creation can be automatic when `AUTONOMOUS_ENABLED=true`;
approval itself is manual. Telegram callbacks or parsed feedback call
`ApprovalHandler.handle_approve()` or `handle_reject()`. Double-approval
requests remain pending after the first approval. `RepoRiskTier.AUTO` marks a
low-risk repository permission tier, but the current request lifecycle still
passes through the approval handler before PR creation. If a user accepts a
suggestion that has no pending approval request, it is only marked accepted; it
does not mutate bot code.

`skills/approval_handler.py` manages human approval, double approval, PR creation, rejection, and suggestion state updates.

Permission policy is intentionally strict:

- docs, tests, logging, and draft PRs can be auto-tier;
- trading logic, filters, sizing, risk, allocation, and coordination require approval;
- secrets, deployment, exchange settings, kill switches, policies, ground truth, risk caps, and drawdown tiers require double approval.

### 13.6 Outcome Measurement

Current implementation: `skills/auto_outcome_measurer.py` is instantiated in
`orchestrator/app.py` and called by `_measure_outcomes`. That function is
registered with the scheduler as `outcome_measurement`; by default it runs on
Sunday at 10:00 UTC, with one catch-up run allowed and a 48-hour misfire grace
period.

The weekly job scans `SuggestionTracker` for `DEPLOYED` suggestions, skips
already measured suggestions, skips portfolio suggestions, anchors on
`deployed_at`, and calls `measure_progressive()`. `measure_progressive()` tries
7, 14, and 30 calendar-day before/after windows once enough time has elapsed,
then returns the best-quality result, preferring the wider window on equal
quality. The data source is curated daily summaries and daily regime files, not
full-fidelity intraday replay.

In practice this is a one-shot lifecycle measurement: after a result is
persisted, `_measure_outcomes` marks the suggestion `MEASURED`, so a 7-day
measurement can close the record before later 14-day or 30-day evidence is
available. A true progressive outcome design would need explicit per-window
checkpoints.

The measurement itself is deterministic. If unreasoned outcomes exist later in
the same scheduled job, `OutcomeReasoningAssembler` builds an
`outcome_reasoning` prompt and the configured agent runtime is invoked to
explain likely causes and write reasoning records.

It compares before and after performance while considering:

- target metric by suggestion category;
- regime match;
- volatility ratio;
- concurrent changes;
- macro regime stability;
- outcome quality tier;
- significance;
- linked hypothesis and proposal metadata.

Measured outcomes feed:

- `SuggestionTracker`;
- `ProposalLedger`;
- calibration records;
- pattern promotion;
- outcome reasoning;
- transfer proposals;
- spurious-outcome records.

Portfolio proposals are measured through a separate portfolio outcome measurer.

In the recommended monthly backtest-parity repair loop, the primary
post-deployment performance verdict for strategy/config changes should be
mostly covered by the next clean one-month validation window. After deployment,
the latest completed month should validate the live strategy config against the
expected backtest and selection-OOS profile, then attribute any gap to
under-trading, outlier losses, execution drift, regime mismatch, or harmful
accepted mutations. That monthly validation is the more useful trading
performance measurement because it uses the same full-fidelity replay and
coverage discipline as candidate selection.

Recommended replacement: for material strategy, filter, sizing, and config
changes, `AutoOutcomeMeasurer` should be superseded as the authoritative
outcome mechanism by the monthly full-fidelity validation and repair loop. It
should not mark strategy changes finally `MEASURED` from 7/14/30-day daily
summary comparisons. At most, it should remain as a provisional early-warning
monitor for obvious regressions, operational changes, prompt context, and
outcome-reasoning inputs.

The optimal outcome architecture is:

- record every deployed strategy/config change in `StrategyChangeLedger`;
- use the next completed one-month validation window as the primary verdict;
- replay the deployed config against expected backtest and selection-OOS
  behavior;
- attribute gaps to under-trading, outlier losses, execution drift, regime
  mismatch, harmful accepted mutations, or overfit prior changes;
- run ablation, perturbation, rollback, and targeted repair tests where the
  validation window exposes weakness;
- write the verdict, attribution, replay evidence, and keep/rollback/repair
  decision to `StrategyChangeLedger`, `ProposalLedger`, and `SuggestionTracker`;
- run a later three-month or minimum-trade-count confirmation to confirm,
  downgrade, or overturn the one-month verdict.

The current code does not provide this full-fidelity one-month plus multi-month
strategy-level outcome system; the existing progressive measurer stops at 30
days and uses daily summaries.

### 13.7 Feedback Into Future Decisions

`skills/suggestion_scorer.py`, `skills/forecast_tracker.py`, `skills/prediction_tracker.py`, and `skills/learning_cycle.py` turn measured results into future prompt context and deterministic scoring.

The system updates:

- category success rates;
- bot-specific and strategy-specific category scores;
- detector confidence;
- regime-stratified performance;
- forecast calibration;
- directional bias;
- hypothesis lifecycle;
- transfer proposal quality;
- experiment outcomes;
- suggestion quality trends;
- generated playbooks;
- cycle effectiveness.

These artifacts are then included in future daily and weekly prompts through `ContextBuilder`, and also used directly by deterministic engines to suppress weak categories or emphasize stronger ones.

Current effect: feedback mostly improves future prompt context and confidence
scoring. `ContextBuilder` injects outcome measurements, proposal outcomes,
category scorecards, regime-stratified scores, recalibrations, outcome
reasoning, and suggestion-quality trends into later weekly, WFO, discovery, and
outcome-reasoning prompts. `SuggestionScorer`, `RetrospectiveBuilder`, and
`LearningCycle` convert outcomes into category win rates, value-per-suggestion
rankings, discard/recalibration records, benchmark cases, playbooks, provider
route scores, and learning-ledger entries. `StrategyEngine` and
`ResponseValidator` can then suppress or downweight categories with poor
measured history. This is useful, but it is mostly contextual for the current
WFO unless the WFO runner directly consumes those signals in its candidate
builder, objective, and acceptance gates.

Optimal effect: monthly validation outcomes should directly shape future
optimization and proposal generation. Positive deployed mutations should become
preferred candidate families; failed or overfit mutations should become
negative priors; repeated weak categories should be excluded or require stronger
evidence; and validation failures should choose the next repair path. In
phased-auto mode, this means allocating phases and search effort toward
historically productive mutation families and tightening gates for weak ones.
In smoke-repair mode, this means focusing ablation, perturbation, rollback, and
targeted tests on the specific failure mode found in the latest month:
under-trading, outlier losses, execution drift, regime mismatch, harmful
accepted mutations, or filter overreach. For structural proposals, this means
models should propose changes from replay-attributed failure modes and prior
mutation outcomes, not from narrative intuition alone.

The recommended monthly backtest-parity repair loop would strengthen this
learning cycle by adding a full-fidelity replay validation layer between
proposal generation and approval. Its role is to test whether the current
configs behaved as expected in the latest month, attribute any gap to
under-trading, outlier losses, execution drift, regime mismatch, or harmful
accepted mutations, then evaluate ablation, perturbation, rollback, and targeted
repair candidates against calibration data, purged folds, and the latest
selection-OOS month. Only evidence-ranked candidates should become
`SuggestionTracker` records; the broader tested candidate set should live in
`ProposalLedger` with windows, metrics, gates, rejection reasons, and replay
provenance. This makes future suggestions more grounded because the system
learns not only which deployed changes worked, but also which candidate classes
failed robust replay before approval.

## 14. Exact Mechanism For Proposing High-Value Improvements

The intended high-value proposal mechanism is:

1. Build a reliable evidence base from bot telemetry.
2. Convert raw telemetry into curated daily metrics.
3. Aggregate daily metrics into weekly and longer-window views.
4. Detect statistically or operationally meaningful weak points using deterministic detectors.
5. Ask an agent to synthesize the curated evidence, active memory, rejected patterns, and scorecards.
6. Parse proposed changes into structured suggestions.
7. Validate suggestions against safety rules, evidence requirements, track records, calibration, and known bad patterns.
8. For tunable parameters, search nearby parameter values against recent evidence.
9. For larger or mutation-linked changes, run full-fidelity monthly replay repair or WFO where sufficient historical data exists.
10. For uncertain changes, route to experiments rather than immediate adoption.
11. Require approval for trading behavior changes.
12. Measure deployed changes after sufficient live time.
13. Feed measured outcomes into scorecards, calibration, hypotheses, and future prompts.

This is a good architecture for compounding learning because proposals are not supposed to stand alone. A proposal becomes more credible when it has:

- a clear category;
- a specific bot and strategy scope;
- enough examples;
- quantified baseline underperformance;
- a plausible mechanism;
- acceptance criteria;
- simulation or search support;
- no recent contradictory outcomes;
- a category with positive historical value;
- a safe approval tier;
- post-deployment measurement.

Weak proposals should be discarded, degraded, or routed to experiments.

Implementation note: the optimal candidate-generation design is hybrid, even if
model cost is irrelevant. Deterministic detectors should remain the first-pass
evidence gate and audit spine for known measurable failure modes. They should
emit exact fields: detector name, source metric, threshold, observed value,
sample size, bot, strategy, category, proposed action, confidence, and
contradictory evidence if available. The model should then review the highest
value detector candidates and the strongest unexplained anomalies, not replace
the detector pass.

The model review should be constrained to:

- agree, disagree, or defer on each detector candidate;
- identify confounders such as regime shift, low sample size, concurrent
  changes, missing costs, or missing backfilled outcomes;
- rank candidates by expected value and reversibility;
- request missing evidence or instrumentation;
- propose experiment or WFO/search routing;
- generate structural hypotheses only when deterministic detectors cannot
  express the pattern.

The parsed model output should preserve provenance by linking each reviewed
candidate to the source detector suggestion or anomaly. Unsupported model-only
suggestions should be allowed only as hypotheses or instrumentation requests
unless they cite explicit evidence. Outcome measurement should score both the
detector and the model review separately so future weekly runs can learn which
detectors fire on noise and which model review patterns improve or degrade
proposal quality.

## 15. Evidence Requirements For Meaningful Improvements

To do what it intends, the assistant needs more than trade PnL. It needs a complete, consistent evidence contract from bots.

Required data:

- all entries and exits, with timestamps, prices, size, fees, slippage, and realized PnL;
- all blocked signals with simulated or backfilled outcome labels;
- exact signal strength and component values at decision time;
- all filters and reasons for pass/block;
- regime labels and source features;
- current parameter values and config version at trade time;
- deployment version and commit/PR ID where possible;
- market session and timezone;
- order lifecycle and rejects;
- latency and clock skew;
- stop movements and exit-tier decisions;
- portfolio exposure and coordination state;
- macro and market context used by the bot;
- experiment variant assignment;
- exchange/funding/borrow/financing costs where relevant;
- post-exit movement for missed exit or early exit analysis.

Without these, the system can still produce reports, but improvement suggestions may be correlational, incomplete, or misattributed.

## 16. Strengths

### 16.1 Strong Safety Boundary

The orchestrator is read-only with respect to bots and uses approval gates for trading changes. This is the correct default for a trading assistant that uses LLMs.

### 16.2 Deterministic Routing

Event routing is deterministic. This prevents prompt injection or LLM hallucination from changing routing behavior.

### 16.3 Rich Evidence Model

The daily metrics builder covers execution, filters, root causes, regimes, portfolio exposure, process quality, missed opportunities, and strategy-specific crypto context. This is much stronger than analyzing only closed-trade PnL.

### 16.4 Closed Feedback Loop

The system does not merely generate suggestions. It tracks whether accepted and deployed suggestions worked, then uses outcomes to recalibrate future recommendations.

### 16.5 Anti-Repetition And Calibration

The system tracks rejected suggestions, poor categories, category success rates, forecast calibration, and detector confidence. This helps prevent the assistant from repeating attractive but historically unhelpful advice.

### 16.6 Human-In-The-Loop Permissions

Risky changes require approval or double approval. This is essential because backtests and LLM analysis can both be wrong in ways that are expensive.

## 17. Limitations And Pitfalls

### 17.1 Backtesting Fidelity

`skills/backtest_simulator.py` is a simplified replay engine. It can support directional evidence, but it is not equivalent to the full live strategy engine unless it models:

- exact signal generation;
- exact filter ordering;
- order book and liquidity constraints;
- partial fills;
- slippage;
- fees and funding;
- latency;
- position sizing;
- portfolio constraints;
- stop and exit mechanics;
- exchange-specific behavior;
- rejected orders;
- concurrent positions.

If the simulator does not match live behavior, optimization can select parameters that only work inside the simplified replay.

### 17.2 Walk-Forward Optimization Weaknesses

WFO is conceptually appropriate, but several implementation details reduce reliability:

- current WFO is event-level replay, not full strategy replay over market data;
- it cannot evaluate parameters unless the simulator implements their behavioral effect;
- an empty or incomplete `data/wfo_configs/<bot>.yaml` leaves no meaningful parameter surface;
- missed-opportunity filtering appears to return all missed events for every fold, which can leak future information across folds;
- consensus by per-parameter mode can break interacting parameter combinations;
- cost sensitivity and robustness checks may evaluate broader data than strictly out-of-sample data;
- leakage audit uses available trade timestamps rather than complete feature provenance, so it cannot detect many real upstream leaks;
- the optimizer is grid-based and depends on the chosen parameter grid;
- fold-level trade counts may be too small for stable conclusions;
- folds may not cover enough regimes;
- OOS validation is still historical and not a replacement for live experiment measurement.

WFO should therefore be used as a ranking and rejection tool. It can say "this candidate is worth testing" more reliably than "this candidate will improve live trading."

### 17.3 Greedy Parameter Search

`skills/parameter_searcher.py` searches local neighborhoods around proposed values. This is useful for low-cost sanity checking but has structural limits:

- single-parameter or narrow local search can miss interacting parameters;
- local optima may be unstable;
- the latest 30 curated directories used by the search path can overfit to current regime and may need stricter date filtering;
- candidate values are only as good as the parameter metadata and ranges;
- the same simplified simulator limitations apply;
- robustness of +/-10% around one parameter does not prove production safety.

The search is effective as a triage step. It should route candidates to discard, experiment, or approval, not replace WFO or controlled live experiments.

### 17.4 Causal Attribution

Outcome measurement compares before and after windows and accounts for regime, volatility, macro stability, and concurrent changes. That is helpful, but it is not full causal inference.

Potential confounders:

- market regime changed;
- multiple suggestions deployed near each other;
- bot code changed outside the assistant;
- execution venue conditions changed;
- sample size is small;
- PnL distribution is heavy-tailed;
- a few exceptional wins or losses dominate the window.

The system should label uncertain outcomes as low quality rather than treating them as calibration truth.

### 17.5 Data Sufficiency

Many detectors and validators require minimum sample sizes. In sparse strategies, daily and weekly windows may not contain enough trades. Without enough trades, the assistant can still produce narrative analysis, but high-confidence improvement proposals should be rare.

### 17.6 Prompt Injection Surface

User feedback is sanitized. Bot payloads are treated as telemetry. If any bot payload contains untrusted natural language, stack traces, external messages, or exchange annotations that reach prompts, prompt-injection patterns could still enter the agent context.

Mitigation: sanitize or quote untrusted text fields before prompt assembly, especially error messages, stack traces, external alert text, and free-form notes.

### 17.7 Weekly-Only Event Persistence

Some low-severity errors are routed to weekly counts rather than daily raw persistence. This can weaken later root-cause analysis if the weekly report needs exact payloads.

### 17.8 Scheduler Timezone Drift

Bot-specific schedule groups are computed at app startup. If DST changes while the orchestrator is running, trigger times may need refresh logic.

### 17.9 JSONL And SQLite Scope

SQLite is fine for a single-user local orchestrator. JSONL trackers are simple and auditable, and `orchestrator/app.py` takes a process lock to prevent a second orchestrator from writing the same stores. Remaining risk is mostly from external tools or ad hoc scripts writing the same JSONL files outside that lock.

### 17.10 Agent Output Quality

Parsing and validation reduce risk, but agent suggestions can still be:

- plausible but unsupported;
- overly broad;
- duplicated in new wording;
- based on missing context;
- biased by recent exceptional trades;
- too confident about simulation results.

The validator and scorer help, but human review remains necessary for trading changes.

## 18. Missing Or Underdeveloped Requirements

The system appears architecturally complete enough to run the intended loop, but its ability to improve trading performance depends on closing several practical gaps.

### 18.1 Strong Bot Data Contract

`schemas/events.py` already defines rich Pydantic event models, including deployment and experiment lineage fields. The remaining requirement is an enforced, versioned bot telemetry contract: required fields per event type, valid enums, timestamp semantics, config version fields, experiment assignment, cost fields, and compatibility tests proving each bot emits the contract.

### 18.2 Deployment Attribution

The code already has partial attribution fields: `SuggestionRecord` includes `approval_request_id`, `deployment_id`, and `pr_url`; trade and missed-opportunity events include optional `deployment_id`, `experiment_id`, `variant_id`, `parameter_set_id`, `strategy_version`, `config_version`, and `code_sha`; and `DeploymentMonitor` can track PR merge, heartbeat-confirmed deployment, and regression windows when enabled. The gap is reliable population and enforcement of those links.

Outcome measurement needs reliable mapping from suggestion ID to:

- PR ID;
- commit hash;
- deployed bot;
- deployment time;
- config version;
- rollback time if any.

Without this, before/after measurement can misattribute unrelated code changes.

The missing operational artifact is a `StrategyChangeLedger`: a materialized,
strategy-centric changelog built from proposal, suggestion, approval,
deployment, and outcome records. It should be the place a reviewer can inspect
the complete lineage of a strategy version: previous config, new config,
mutation diff, reason for change, supporting evidence, approval, PR, deployment,
live outcome, and rollback status.

### 18.3 Full-Fidelity Backtest Adapter

The current simulator is useful, but high-confidence optimization requires an adapter that can replay through the actual strategy logic or a verified equivalent. This is especially important for multi-filter interactions and exit logic.

The adapter should expose a shared phased-auto interface: the shared runner owns
state, phases, greedy orchestration, smoke-repair orchestration, gates,
diagnostics, artifacts, and provenance, while each strategy plugin owns data
loading, replay, candidate generation, mutation semantics, and
strategy-specific scoring.

The smoke path should reuse `backtests/shared/smoke/latest_oos_smoke.py` for
latest-period window resolution, data-end policy, strategy probe coverage, and
aggregate latest-OOS reporting. Strategy-specific repair modules should add
candidate generation and replay evaluation on top of that shared smoke result.

It also needs a canonical market-data sync process that writes versioned parquet
and coverage manifests before each monthly run. Bot event telemetry is not
enough for ablation, perturbation, or targeted re-optimization because alternate
parameters can change which signals, entries, exits, and fills would have
existed.

### 18.4 WFO Leakage Fixes

WFO should ensure all trades, missed opportunities, features, labels, and costs are strictly fold-local. The leakage audit should receive real feature timestamps and label timestamps, not just trade entry and exit timestamps.

### 18.5 Experiment Design

Experiment infrastructure already exists: A/B experiment schemas and manager, structural experiment tracking, acceptance criteria, active-experiment checks, and experiment outcome measurement. The remaining requirement is stricter governance:

- mutually exclusive active experiments where interactions are likely;
- pre-registered acceptance criteria;
- minimum sample and duration;
- regime coverage requirements;
- stop-loss criteria for experiments;
- clear bot-side variant assignment and logging.

### 18.6 Portfolio-Level Ground Truth

Portfolio coordination proposals need portfolio-level ground truth:

- concurrent exposure;
- correlation clusters;
- family-level drawdowns;
- capital allocation by strategy;
- avoided trades due to portfolio rules;
- opportunity cost of blocked trades.

Without this, portfolio suggestions can optimize local bot performance while harming total portfolio performance.

### 18.7 Operational Monitoring

The system reports queue and run metrics, exposes dead-letter reprocessing, has approval expiry, and can run deployment monitoring when enabled. Improvement safety still needs stronger coverage:

- alerting when bots stop emitting required telemetry;
- alerting when config version fields disappear;
- report quality regression alerts;
- stalled approval/deployment alerts;
- stale scheduler or DST mismatch checks;
- outcome measurement coverage metrics.

## 19. Does It Have What It Needs?

### For Daily Diagnosis

Mostly yes, if bots emit the intended structured events. Daily reports can identify anomalies, losses, process failures, execution issues, and likely root causes.

Main risk: sparse trading days and incomplete instrumentation.

### For Weekly Improvement Suggestions

Partially yes. The deterministic engine, weekly metrics, simulations, scorecards, and validation pipeline are a strong foundation.

Main risk: weekly windows may be too small, and some evidence may be correlational or missing exact decision-time context.

### For Backtest-Grounded Parameter Changes

Partially. The parameter search and simulator can reject weak candidates and prioritize experiments.

Main risk: simplified simulation fidelity. Backtest evidence should not be treated as sufficient for direct high-confidence adoption unless the simulator is validated against live strategy behavior.

### For Walk-Forward Optimization

Conceptually yes, implementation needs tightening. WFO can be effective if fold-local data, realistic replay, sufficient history, and robust cost modeling are guaranteed.

Current WFO is useful for screening. It is not yet enough to justify unsupervised production parameter adoption.

### For Closed-Loop Learning

Yes in architecture. The system has trackers, outcomes, scorecards, forecasts, hypotheses, experiments, and prompt feedback.

Main risk: the loop learns from noisy labels if outcome attribution is weak. A closed loop compounds both truth and error. Measurement quality controls are therefore critical.

## 20. Recommended Priority Improvements

The priority is to replace lightweight validation with a monthly
full-fidelity evidence loop, while preserving deterministic guardrails and using
models where they add reasoning value.

### 20.1 Main Improvements

1. Adopt the hybrid proposal design: deterministic detectors, scoring,
   evidence checks, and safety gates first; model synthesis for structural
   reasoning, hypothesis generation, candidate review, and explanation.
2. Replace the current event-level WFO with a monthly full-fidelity validation
   and repair workflow. The latest completed month should first validate the
   incumbent production configs, then, if repair is needed, act as the
   selection-OOS gate for candidate mutations.
3. Implement a shared phased-auto plus smoke-repair framework. Phased-auto
   should handle mature strategy optimization with strategy plugins, phases,
   greedy selection, and hard gates; smoke-repair should handle targeted OOS
   failure diagnosis, ablation, perturbation, rollback, and quick repair.
4. Add a canonical market-data sync. `trading_assistant` or a shared backtest
   host should write versioned parquet and coverage manifests; live bots should
   continue emitting decision telemetry, fills, costs, config versions, and
   deployment IDs, but should not be the only market-data source.
5. Add `StrategyChangeLedger` as the strategy-level changelog for proposal,
   approval, PR/commit, deployment, config diff, reason, evidence, outcome,
   follow-up verdict, and rollback status.
6. Supersede `AutoOutcomeMeasurer` as the authoritative strategy outcome
   mechanism. Monthly one-month validation should provide the primary verdict;
   a later three-month or minimum-trade-count follow-up should confirm,
   downgrade, or overturn it. The current weekly measurer can remain only as
   early warning and prompt context.
7. Make feedback operational. Outcomes should directly influence candidate
   generation, search allocation, smoke-test focus, acceptance gates, negative
   priors, rollback priority, and structural proposal prompts.

### 20.2 Requirements To Make Explicit

1. Enforce deployment and config attribution. Trades, missed opportunities,
   validation runs, proposals, approvals, PRs, deployments, and outcomes need
   reliable `strategy_version`, `config_version`, `deployment_id`,
   `commit_sha`, proposal IDs, and change IDs.
2. Use the existing objective consistently. The canonical objective already
   exists in `soul.md` and `schemas/objective_weights.py`
   (`objective_weights_v1`): net profit or expected return, Calmar, profit
   factor, expectancy, max drawdown, and process quality. The new monthly
   framework should use that composite for selection and measurement, with
   hard gates for drawdown, trade count, costs, OOS degradation, and data
   sufficiency.
3. Add data-quality and coverage gates. No monthly verdict or optimization
   should run without coverage manifests, missing-bar checks, calendar/session
   alignment, fee/slippage sanity, feature parity checks, and replay/live
   behavior parity checks.
4. Keep model outputs strictly structured. Structural proposals need
   machine-readable schemas, evidence references, risk classification,
   acceptance criteria, rollback plans, and manual approval for any trading
   behavior change.
5. Define persistence and rollback policy. Positive one-month results should
   not become strong priors until confirmed by a three-month or
   minimum-trade-count follow-up; negative results should route to rollback,
   quarantine, or targeted repair according to pre-defined thresholds.
6. Preserve operational safety. Continue prompt-injection sanitization,
   report/data coverage metrics, stale telemetry alerts, approval expiry,
   deployment monitoring, and experiment interaction controls.

## 21. Final Assessment

The trading assistant is well-designed as a local, safety-conscious learning orchestrator. Its workflow is coherent: bots emit structured evidence; the orchestrator curates and analyzes it; deterministic and LLM systems propose improvements; validators and approval gates reduce risk; deployed suggestions are measured; measured outcomes recalibrate the next round of suggestions.

The most important caveat is that trading improvement is only as reliable as the evidence and replay model. The assistant can discover meaningful high-value changes if bots provide complete decision-time telemetry, if deployment attribution is exact, and if backtests and WFO are used conservatively. Without those conditions, the same loop can amplify noise, overfit recent regimes, or reward suggestions that looked good only inside incomplete data.

In its current shape, the system should be trusted as an evidence-ranked analyst and proposal engine, not as an autonomous trading optimizer. With stronger telemetry contracts, fold-local WFO, validated replay fidelity, and disciplined experiment design, it has the right architecture to improve trading performance over time while keeping humans in control of material trading changes.
