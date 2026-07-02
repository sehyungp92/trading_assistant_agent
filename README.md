# Trading Assistant Agent

A learning system for improving the trading performance of the external trading repos over time. It turns live bot outcomes into durable evidence, uses that evidence to propose and test better strategy behavior, and feeds measured results back into future search, gates, priors, and rollback decisions.

The system is a read-only local orchestrator: it does not place orders, cancel orders, change live positions, or directly command bots. Material strategy changes are approval-gated and must be supported by full-fidelity replay evidence.

## Why this repo exists

The end goal is not "generate reports" or "make suggestions"; it is to make the trading repos better through a repeatable evidence loop:

1. Identifies strategy weaknesses from real bot telemetry and market data.
2. Proposes high-value, evidence-grounded changes.
3. Validates them with realistic full-fidelity replay.
4. Routes them through human approval.
5. Measures deployed outcomes against the same governed scoring profile used for selection.
6. Feeds those outcomes back into future candidate generation, gates, priors,
   and rollback decisions.

Every useful subsystem serves that loop: preserve what happened, explain why it happened, test what should change, approve only evidence-backed changes, and use the next live outcomes to make the next cycle smarter.

## What the system does

### Senses bot health and triages errors

The first job is to make sure the learning loop is fed by trustworthy live signals. The orchestrator ingests trades, missed opportunities, snapshots, heartbeats, and errors from the bots, then separates "the strategy is weak" from "the bot or data path is broken." That protects future optimization from being trained on corrupted or incomplete outcomes.

It classifies error severity deterministically, tracks error spikes, monitors heartbeat gaps, and runs proactive loss/error scans. Obvious operational fixes can become draft PRs; ambiguous failures stay flagged for human investigation.

### Curates evidence across multiple dimensions

Raw bot events are too noisy to improve strategies directly. Each day, the repo turns them into comparable evidence about where performance is coming from, why it is deteriorating, and which failure modes deserve monthly replay attention:

- **Trade quality** &mdash; winners, losers, process failures (quality score &lt; 60), and notable missed opportunities.
- **Regime analysis** &mdash; PnL, win rate, and trade count broken down by market regime.
- **Filter effectiveness** &mdash; per-filter block count, saved PnL, and missed PnL.
- **Time-of-day patterns** &mdash; hourly PnL and win rate distributions.
- **Slippage** &mdash; per-symbol and per-hour spread distributions (mean, median, p75, p95).
- **Exit efficiency** &mdash; premature exit rates by exit reason and regime.
- **Signal attribution** &mdash; per-signal-factor win rate, PnL contribution, and trend.
- **Drawdown episodes** &mdash; equity-curve segmentation with duration, root-cause attribution, and recovery tracking.
- **Root cause distribution** &mdash; across a 21-type controlled taxonomy.

### Runs monthly full-fidelity validation

Monthly validation is where learning becomes an adoption candidate. Weekly and daily evidence can shape hypotheses, but material strategy/config changes must survive a frozen, replay-backed monthly loop that tests whether the change should improve future trading rather than merely explain the past. It assembles:

- Market-data coverage manifests and telemetry lineage.
- Live-vs-backtest decision-level parity checks.
- Score deltas, counterfactuals, and regime slices.
- Leakage and cost-realism signals from the monthly replay artifacts.
- Structured candidate proposals with calibrated predictions and rollback plans.

Approval-gated monthly candidates produce Telegram approval cards and GitHub PRs through shared approval infrastructure. After merge, deployment monitoring tracks whether the live outcome matches the predicted improvement; regressions can create rollback PRs and become negative evidence for future cycles.

### Proposes structural and portfolio-level improvements

The repo is meant to improve strategy behavior, not just tune knobs. Beyond parameter search, the strategy engine uses **19 deterministic detectors** to turn recurring outcome patterns into hypotheses about signal quality, execution, regime fit, portfolio structure, and failure patterns:

- **Signal quality** (4) &mdash; alpha decay, signal decay, component signal decay, factor correlation decay.
- **Execution quality** (4) &mdash; exit timing, microstructure (fill quality, adverse selection), stress entry patterns, position-sizing mismatches.
- **Regime awareness** (3) &mdash; regime config effectiveness, regime transition cost, time-of-day patterns.
- **Portfolio structure** (5) &mdash; family imbalance, correlation concentration, drawdown-tier miscalibration, coordination gaps, heat-cap utilisation.
- **Pattern detection** (3) &mdash; drawdown patterns, filter interaction effects, correlation breakdown.

Detector findings feed weekly synthesis, which can surface structural ideas (for example, "add a regime-aware exit rule" or "split this strategy into two variants"). Weekly structural suggestions remain report-only until promoted into monthly candidate validation; production adoption requires isolated candidate testing, decision-level parity evidence, measured score improvement, and human approval.

Portfolio-level proposals are treated as performance hypotheses too: the system asks whether different family weights, risk caps, or coordination rules would have improved the portfolio without hiding drawdown or regime fragility. Each strategy carries an archetype profile so the learning system compares it against the right kind of behavior instead of applying one generic threshold set to every bot.

## Monorepo layout

The package split exists to keep the learning loop honest. The control plane decides what evidence is needed, the data package proves the inputs, and the backtest package proves candidate behavior under replay. They communicate through frozen manifests and artifacts so a candidate cannot quietly change the data, scorer, replay assumptions, or live strategy boundary it is being judged against.

```
trading_assistant_agent/
  docs/                          # ADRs, target-state docs
  artifacts/                     # Run outputs, reports, ledger snapshots
  tools/                         # Repo-wide tooling
  packages/
    trading_assistant/           # Control plane: orchestrator, ledgers, approval routing
    trading_assistant_data/      # Canonical data product: market data, bundles, manifests
    trading_assistant_backtest/  # Replay & optimizer lab: diagnostics, phased-auto, OOS repair
```

| Package | Role | Owns |
|---|---|---|
| `trading_assistant` | Control plane | Run manifests, freeze windows, score-profile version, `round_N` configs, ledgers, approval state |
| `trading_assistant_data` | Data product | Canonical market data, calendars, checksums, bundle manifests, coverage reports |
| `trading_assistant_backtest` | Experiment lab | Diagnostics, phased-auto search, OOS repair, scoring, replay adapters, artifact emission |

### Architecture Ownership Map

| Interface | Owner | Compatibility Surface |
|---|---|---|
| Runtime assembly | `trading_assistant.orchestrator.runtime` | `orchestrator.app` binds HTTP routes and lifespan hooks |
| Loop orchestration | `trading_assistant.orchestrator.loops` and `orchestrator.action_handlers` | `orchestrator.handlers` delegates legacy entry points |
| Prompt evidence | `trading_assistant.analysis.context_sources` via `EvidenceMemory` | `ContextBuilder` assembles `PromptPackage` and inherits source-owned loader methods |
| Strategy detectors | `trading_assistant.analysis.detectors` | `StrategyEngine` keeps public detector methods as delegating adapters |
| Monthly artifacts and gates | `trading_assistant.skills.monthly_artifact_contract` plus `artifact_authority_registry` | Candidate/model-review runners consume contract-built views |
| Slice data product | `trading_assistant_data.slices` | `normalization.py` remains the CLI/source normalization command owner |
| Monthly replay execution | `trading_assistant_backtest.monthly_execution` | `monthly.py` is the command adapter |
| Architecture enforcement | `tools/check_workspace_structure.py` and `tools/run_workspace_checks.py architecture-health` | Deployment gate runs the same guard |

The external live-bot repos remain production truth for strategy behavior: `_references/trading`, `_references/k_stock_trader`, and `_references/crypto_trader`. Structural candidates must prove decision-level parity against the relevant pinned live repo and bridge contract before they can be scored for adoption or approved.

## Event-flow architecture

The event path turns live trading outcomes into durable learning material. It is one-way by design: bots emit facts, the assistant stores and analyzes them, and approved changes flow back only through human-reviewed PRs.

```
VPS bots
  -> sidecar
  -> relay VPS
  -> POST /events
  -> EventQueue (SQLite)
  -> OrchestratorBrain (classify, create task)
  -> Worker (pick task, run agent)
  -> AgentRunner (assemble context, provider profile, CLI runtime)
  -> runs/<id>/outputs/
  -> Telegram / Discord / Email
```

Inside the `trading_assistant` control-plane package, each component supports that evidence-to-learning path:

```
orchestrator/   receive facts, classify work, schedule learning cycles
analysis/       convert evidence into hypotheses, prompts, and validated outputs
skills/         build metrics, ledgers, search briefs, simulations, and trackers
comms/          surface approvals, alerts, and evidence summaries to humans
schemas/        make every event, candidate, and approval packet auditable
memory/         keep human policy separate from system-written findings
tests/          preserve the contracts that make the loop trustworthy
```

`trading_assistant_data` and `trading_assistant_backtest` are reached only through frozen manifests, CLI/API contracts, and emitted artifacts.

## Cadence

The cadence is a learning hierarchy. Daily work protects data quality and finds fresh symptoms; weekly work turns symptoms into bounded hypotheses; monthly work is the only path that can convert a hypothesis into an approval candidate.

| Cadence | Role | Authority |
|---|---|---|
| Daily | Sensor / diagnostic: anomalies, process failures, telemetry gaps, drawdown alerts | None over strategy changes |
| Weekly | Synthesis: scorecards, hypotheses, rotation across active strategy / portfolio scopes, build `monthly_search_brief.json` | Bounded search priors only &mdash; cannot trigger OOS repair, satisfy gates, or approve candidates |
| Monthly | Authoritative full-fidelity validation, optimization, and outcome measurement | Sole authority for material strategy/config changes (still human-approved) |

Weekly scope rotates across `k_stock_trader` + trading stock, trading momentum, trading swing, and `crypto_trader`, then repeats.

### Scheduled tasks

These jobs are not independent automations; they keep the improvement loop fed, measured, and honest between monthly validation runs.

| Task | Schedule | Learning contribution |
|---|---|---|
| Daily Analysis | 06:00 UTC | Finds fresh performance symptoms and data-quality issues before they distort learning |
| Weekly Summary | Sunday | Turns recent evidence into bounded hypotheses and monthly search-brief priors |
| Monthly Validation | Monthly | Converts hypotheses into replay-tested, approval-gated candidates |
| Proactive Scanner | Morning + evening | Catches unusual losses, repeated errors, and heartbeat gaps early |
| Learning Cycle | Weekly | Updates helper outcome snapshots, ledgers, and pending-item routing |
| Outcome Measurement | Sunday 10:00 UTC | Provides early-warning 7/14/30-day context after deployment |
| Memory Consolidation | Sunday 09:00 UTC | Distills repeated findings into reusable learning material |
| Transfer Outcome Tracking | Sunday 10:30 UTC | Tests whether patterns learned on one bot actually transfer |
| Threshold Learning | Periodic | Tunes detector sensitivity from measured outcomes |
| Experiment Check | Periodic | Closes statistically resolved experiments and records hypothesis outcomes |
| Discovery Analysis | Periodic | Looks for raw JSONL patterns outside the detector catalogue |
| Reliability Verification | Periodic | Keeps the evidence pipeline fit for decision-making |

Bug triage runs on demand when HIGH+ severity errors arrive. The configured agent runtime is invoked per task (not always-running), keeping subscription-backed profiles at zero extra cost while idle.

## The monthly authoritative loop

The monthly loop is where the repo asks the hard question: "Given what we have learned from live outcomes so far, what change is most likely to improve future trading after costs, drawdown, data quality, and out-of-sample pressure?" Each month, after data sync and freeze (in-sample = all reliable data before the latest completed month; selection-OOS = the latest completed month):

1. **`round_N` diagnostics** &mdash; full end-of-round diagnostics on the current optimized strategy and portfolio configs.
2. **Search brief** &mdash; consume the weekly `monthly_search_brief.json` as advisory priors only.
3. **LLM experiment plan** &mdash; diagnostics &rarr; structured phased-auto plan (signals, discrimination, entries, mechanisms, exits, structural candidates, overfit risks).
4. **Two-fold phased-auto on in-sample** &mdash; purged folds with embargo; `max_workers=2`; config-only and structural candidates compete under the resolved `immutable_score_profiles_v1` profile with at most seven active components.
5. **Conditional OOS repair** &mdash; triggered only when selection-OOS materially trails in-sample/fold expectation. Ablates all cumulative accepted mutations, perturbs locally, considers rollback and targeted additions.
6. **Repair-centered confirmatory follow-up** &mdash; the OOS-repair recommendation competes against incumbent, phased-auto winner, rollback candidates, and targeted additions under the same resolved immutable score profile.
7. **Adopt `round_N+1`** &mdash; update the rounds manifest, save end-of-round diagnostics, verify live/backtest parity, then route to model review and human approval once the relevant bridge is eligible for adoption.

Deployed verdicts come from the **next** completed monthly full-fidelity validation (the selection-OOS month is no longer clean once it influenced selection). Persistence is confirmed by a three-month or minimum-trade-count follow-up.

## Canonical scoring

The scoring contract exists to keep the improvement loop honest: a candidate only matters if it improves the strategy under replay evidence, survives out-of-sample pressure, and does not buy performance by taking unacceptable risk. Monthly and phased-auto ranking therefore uses the governed `immutable_score_profiles_v1` profiles, with profiles scaled to the relevant strategy, family, or portfolio instead of forcing every bot through one static formula.

`immutable_score_profiles_v1` combines risk-adjusted return, drawdown control, trade support, cost realism, out-of-sample persistence, and family-specific behavior checks, then applies hard rejects before ranking candidates. That aligns scoring with the app's goal: improve future live trading performance through durable, replay-backed edge rather than short-term backtest gains or riskier parameter fits.

## Safety boundary

The safety boundary is part of the performance system. A learning loop that can command bots, weaken policy, or approve its own changes can overfit to its own incentives. This repo keeps evidence generation, candidate scoring, approval, and live trading authority separated.

- The assistant never places, cancels, or modifies live orders or positions.
- Models synthesize evidence and propose structural changes &mdash; they cannot route events, bypass gates, edit policy memory, or approve trading changes.
- Every material change requires human approval with replay evidence, score deltas, failure attribution, and a rollback plan attached.
- `AutoOutcomeMeasurer` (7/14/30-day daily-summary windows) is retained for operational alerts and prompt context only &mdash; it is no longer authoritative for deployed outcomes.

## Human-in-the-loop

Human approval is not just a safety valve; it is the point where evidence, business judgment, and deployment risk meet. The system is read-only with respect to bots, and all changes flow through GitHub PRs that require human action to merge:

- **Parameter changes** &mdash; validated by monthly phased-auto and replay parity; require explicit Telegram approval before a PR is created.
- **Structural candidates** &mdash; may be implemented and scored inside the monthly phased-auto/backtest lane, but production PRs require decision-level parity, evidence gates, and human approval. Weekly structural suggestions remain report-only until promoted.
- **Bug fix PRs** &mdash; generated for obvious fixes; always require human review.
- **Rollback PRs** &mdash; can be created when deployment monitoring detects regression; still require human merge.
- **Portfolio allocation** &mdash; recommendations only; reallocating capital is a manual action.

Three-tier permission gates (`auto` / `requires_approval` / `requires_double_approval`, defined in `memory/policies/v1/permission_gates.md`) enforce this at the file-path level during PR review. Trading-logic, policy-document, immutable score-profile, helper objective, and ground-truth-function changes are human-owned governance changes; the system cannot change how performance is measured through an ordinary agent run.

## Ledgers

The ledgers are how the repo avoids repeating itself. They preserve which ideas were proposed, why they were accepted or rejected, what changed in production, and whether the change actually improved trading later.

| Ledger | Scope |
|---|---|
| `ProposalLedger` | Append-only provenance for every candidate, evaluation, rejection, experiment, approval, deployment, and outcome |
| `SuggestionTracker` | Actionable suggestion lifecycle and approval-facing status |
| `StrategyChangeLedger` | Canonical strategy-level changelog: what changed, why, when, on which strategy under which config, and whether it worked (one-month + multi-month verdicts) |

Broad candidate noise stays in `ProposalLedger`. Only selected changes, deployed changes, rollbacks, and explicit no-change decisions enter `StrategyChangeLedger`, so future planning can distinguish "explored and weak" from "approved and performance-relevant."

## Memory layers

Memory exists to make the next cycle better than the last one without letting generated advice become trading authority. The layers separate durable human policy, replay evidence, advisory lessons, recall, and harness evaluation:

1. **Policy memory** &mdash; human-edited rules, objectives, gates, governance.
2. **Evidence memory** &mdash; monthly artifacts, ledgers, outcomes, priors, replay reports, rejected candidates.
3. **Advisory memory** &mdash; learning cards and generated playbooks with provenance, usage attribution, supersession, quarantine.
4. **Raw recall** &mdash; indexed run artifacts, session summaries, validator notes, model-review traces.
5. **Evaluation corpus** &mdash; executable harness benchmarks derived from failures, blocked proposals, calibration misses, and high-value successes.

Harness changes (prompts, retrieval, validators, parsers, generated playbooks, provider routing) must pass executable benchmarks before they are kept. Hard failures &mdash; approval bypass, direct live commands, hallucinated evidence, autonomous policy edits &mdash; override any score gains because they would make future trading decisions less trustworthy.

## Learning loop

Past outcomes improve future trading only when they are linked back to the ideas that caused them. Every suggestion is tracked from generation to deployed outcome and then back into the next prompt, search brief, detector calibration, and approval context:

```
Strategy engine (19 detectors)
  -> suggestion ID in SuggestionTracker
  -> config candidate -> monthly validation
       (phased-auto, OOS repair, replay parity)
  -> structural proposal -> validation gates
       (hypothesis track record, category win rate, calibration)
  -> ProposalLedger and StrategyChangeLedger
  -> Telegram approval card / GitHub PR, only after approval gates
  -> approve or reject via Telegram
  -> lifecycle update

Weekly learning cycle (advisory only)
  -> helper ground-truth snapshot, ledger delta, pending-item routing
  -> weekly evidence and monthly_search_brief.json
  -> AutoOutcomeMeasurer early-warning context
  -> next monthly full-fidelity validation as primary deployed verdict
  -> 3-month or min-trade follow-up as persistence verdict
  -> feedback into prompts, priors, category scorecards, confidence, and loop health
```

The system should get harder to fool over time. It will not re-suggest rejected ideas, categories with low success rates are stripped before delivery, confidence is capped by historical prediction accuracy, and hypotheses that accumulate rejections or negative outcomes are retired. Positive and negative outcomes both become learning material for the next cycle.

The harness also monitors whether its own improvement process is working, without touching trading authority:

- **Convergence tracking** asks whether recent changes are actually improving future results, degrading them, or causing oscillation. When oscillation is detected, the LLM is instructed to hold steady rather than reverse last week's suggestions.
- **Loop health metrics** expose whether the learning system itself is slow, noisy, poorly measured, or overproducing suggestions.
- **Temporal decay** applies a 5%/week exponential decay to scorecard outcome weights, matching the learning ledger's decay rate. Categories recover from early failures as old negatives fade.
- **Directional bias correction** detects systematic optimism or pessimism per metric in the LLM's prediction track record and reduces confidence on predictions matching the bias (capped at 20%).
- **Per-detector confidence calibration** gives each of the 19 detectors an empirical confidence multiplier derived from its outcome history &mdash; distinct from threshold learning, which adapts *when* a detector fires.
- **Structural proposal validation** runs six parity gates before any structural suggestion reaches a report: hypothesis track record, category track record, simplicity, acceptance-criteria presence, low-confidence block, and empirical calibration adjustment.
- **Instrumentation readiness scoring** evaluates each bot across eight capability categories and injects per-bot readiness reports into prompts, preventing confident conclusions from incomplete instrumentation.
- **Experiment auto-conclusion** tracks parameter experiments to statistical resolution, then escalates through the full chain: conclude experiment &rarr; accept/reject linked suggestion &rarr; record hypothesis outcome.

## Design philosophy

The system borrows four architectural patterns only where they help the core goal: use accumulated evidence to improve future trading performance while keeping a human in control of live risk. They share governed scoring vocabulary, one suggestion lifecycle, and the same approval gates &mdash; they are integrated, not stacked.

### From OpenClaw &mdash; disposable agents, permanent knowledge

The agent is disposable; the learning history is permanent. Models, providers, and CLI runtimes can change, but outcome measurements, suggestion histories, calibration, correction logs, and prompt patterns stay local, queryable, and auditable.

That matters for trading improvement because:

- **The brain is swappable.** Better models can be adopted without losing the trading history the system has learned from.
- **Every recommendation is auditable.** A change can be traced back to the evidence, memories, prompts, and artifacts the agent saw.
- **Proactive learning stays local.** Scheduled daily, weekly, and monthly jobs can keep the evidence loop moving without giving the agent live trading authority.

Disposability depends on clear, enforceable boundaries: three-tier permission gates classify every action the system can take (auto, requires approval, requires double approval) and enforce them at the file-path level during PR review; separated memory tiers keep `memory/policies/` (versioned, human-edited only) distinct from `memory/findings/` (additive, time-stamped, system-written); deterministic routing keeps the orchestrator brain LLM-free for event classification and task creation.

### From Hermes &mdash; advisory memory and harness meta-learning

Hermes-style memory decides what past outcomes the next agent run should see and whether changes to prompts, retrieval, validators, parsers, playbooks, or providers improve decision quality.

- **Prompt delivery closes the last-mile gap.** `InvocationBuilder.build_full_prompt()` merges instructions, corrections, skill methodology, ranked learning cards, and focused recall into the prompt itself, so upstream learning influences analysis instead of sitting in sidecar files the runtime may never read.
- **Learning cards turn past lessons into ranked retrieval.** Corrections, measured outcomes, discoveries, causal reasonings, recalibrations, spurious-outcome flags, hypothesis results, validator blocks, transfer outcomes, retrospectives, and validation logs are ingested as `LearningCard` objects scored by recency, impact, confidence, and context match, then injected most-relevant-first.
- **Session history and run recall flow through assemblers.** The session store passes through assembler paths into `base_package()`; `RunIndex` and focused recall can surface relevant prior artifacts, so the agent builds on prior reasoning rather than starting from a blank slate.
- **Bounded search briefs are the bridge into monthly optimization.** Weekly synthesis, learning cards, hypotheses, and prior outcomes are summarized into `monthly_search_brief.json` for planner and runner ordering only &mdash; the brief cannot choose the monthly sequence, trigger OOS repair, satisfy gates, approve changes, weaken policy memory, or command bots.
- **Generated memory remains advisory.** Policy memory and monthly evidence outrank learning cards, generated playbooks, raw recall, and harness benchmark results. Advisory artifacts require provenance, outcome attribution, supersession, quarantine, and keep/discard evidence before they re-enter prompts.

### From Autoresearch &mdash; immutable scoring and a separable evidence loop

A self-improving trading system needs governed evaluation rules it cannot modify. The LLM can design experiments and review candidates after evidence is assembled; deterministic replay, immutable scoring, parity gates, and approval policy remain decisive.

- **Immutable monthly scoring** lives in `trading_assistant_backtest.scoring.immutable`. Monthly/phased-auto candidate ranking resolves a profile for the strategy, family, or portfolio, applies hard rejects first, then persists the exact profile metadata and compact score payload with each replay artifact. `skills/ground_truth_computer.py` and `schemas/objective_weights.py` remain stable helper composites for daily/weekly learning snapshots and local triage, not the binding monthly scorer.
- **The monthly evidence loop** is the material strategy-learning path that replaces legacy WFO. The control plane owns frozen manifests, telemetry and market-data coverage checks, replay-parity evidence, monthly search-brief attachment, model review, candidate gates, approval packets, ledgers, and outcome measurement; full-fidelity replay is delegated to `trading_assistant_backtest`.
- **The weekly learning cycle** remains a sensor, early-warning, and context provider. Its influence on monthly optimization is intentionally bounded to `monthly_search_brief.json` &mdash; it may steer planner emphasis, phase order, seed neighborhoods, negative priors, and conditional repair-ablation priority, but it cannot create approval-ready candidates, change the monthly sequence, trigger OOS repair, or satisfy adoption gates.

### From Symphony &mdash; isolated candidate orchestration

Symphony-style orchestration keeps expensive candidate testing isolated from both the control plane and the live trading repos. That lets the system explore possible improvements aggressively while preserving deterministic workspaces, path containment, retry/backoff, stall detection, drift reconciliation, and structured attempt logs.

It explicitly does not own strategy logic, replay scoring, live/backtest parity gates, approval or deployment decisions, ticket workflow, or live trading commands. `trading_assistant` remains the control plane and ledger; `trading_assistant_backtest` is the experiment lab; the external live-bot repos remain production source of truth.

### How they integrate

- **Governed scoring vocabulary.** Monthly replay evidence and approval-gated candidate scoring use `immutable_score_profiles_v1`, including profile metadata, capped components, and hard rejects. Daily/weekly ground-truth snapshots and local helper composites draw from `objective_weights_v1` for continuity, but they cannot override monthly ranking. Score-profile and helper-weight changes are human-owned governance changes.
- **Unified suggestion lifecycle.** Suggestions and monthly candidates flow with deterministic IDs through `SuggestionTracker`, `ProposalLedger`, and `StrategyChangeLedger`, then through approval, implementation, deployment monitoring, rollback/watch decisions, and outcome measurement. The next completed one-month full-fidelity validation is the primary deployed verdict; early-warning windows are prompt context only.
- **Experiment-to-hypothesis traceability.** On statistical resolution, the auto-conclusion chain updates the linked suggestion (accept / reject) and records the outcome against the hypothesis that motivated it (positive / negative). The next analysis prompt reflects not just "this change was tested" but "the hypothesis behind it was strengthened or weakened."
- **Bidirectional context flow.** Weekly results flow back through context assembly, monthly outcome priors, learning cards, focused recall, and `monthly_search_brief.json`. The LLM sees what was tried, what worked, which candidate families have poor track records, whether the system is converging or oscillating, where its directional biases lie, which bots have sufficient instrumentation, and which weak weekly signals should stay low-confidence.
- **Governance prevents gaming.** Because policy memory, immutable score profiles, helper weights, and ground-truth functions sit behind human-owned controls, the system cannot shift to something easier to optimize. Structural and config candidates must pass data coverage, replay parity, immutable scoring, no-regression, model-review, approval-payload, and human approval gates before adoption. The system learns from its own history through governed scoring rules it cannot change.

### Matching the change type to the right tool

- **Parameter changes** &mdash; adjusting a stop-loss percentage, a signal threshold, a filter sensitivity. Numerical optimization problems with a resolved immutable score profile, owned by the monthly evidence and replay validation loop. Phased-auto compares config candidates against frozen artifacts, replay parity, profile thresholds, OOS degradation checks, and rollback requirements before approval.
- **Structural changes** &mdash; adding a regime-aware exit rule, splitting a strategy into variants, redesigning a filter interaction. First-class phased-auto candidates inside the monthly loop, not a separate advisory-only lane. The LLM designs candidate patches; the runner applies them in isolated workspaces across the relevant live-bot repo and backtest adapter; unit, decision, and decision-level parity tests run before fold scoring; config neighborhoods are tuned around passing structural candidates.
- **Portfolio-level changes** &mdash; rebalancing family allocation weights, adjusting risk caps, modifying coordination rules, changing drawdown-tier multipliers. Validated through a what-if analysis (`skills/portfolio_what_if.py`) that rescales historical family PnL under the proposed weights to estimate portfolio Calmar, Sharpe, and max drawdown. Where per-family trade-level data exists, the what-if uses individual trades for intra-day max drawdown, Sortino, profit factor, and regime breakdowns that daily aggregation would mask. Outcomes are measured over a 30-day observation window (vs 7 days for strategy-level); regime shifts during the window yield INCONCLUSIVE verdicts rather than false signals.

## Running the system

This top-level README explains why the learning loop exists and how the pieces fit together. Operational setup lives closer to the packages that own each part of the loop: control-plane runtime and secure binding in [`packages/trading_assistant/README.md`](packages/trading_assistant/README.md), canonical data-sync jobs in [`packages/trading_assistant_data/README.md`](packages/trading_assistant_data/README.md), and the monthly optimizer runner contract in [`packages/trading_assistant_backtest/MONTHLY_OPTIMIZER_WORKFLOW.md`](packages/trading_assistant_backtest/MONTHLY_OPTIMIZER_WORKFLOW.md).

The agent runtime is swappable per workflow between Claude Max, Codex Pro, Z.AI Coding Plan, and OpenRouter-backed Claude-compatible models. Selection is persisted in `data/agent_preferences.json`, can be seeded from provider env vars when no preferences file exists, and is surfaced via `GET/PUT /agent/preferences` plus the Telegram `/settings` panel. Daily and weekly Claude-compatible workflows use read-only tool allowlists (`Read`, `Grep`, `Glob`); monthly model review runs without tools; triage keeps `Bash` enabled alongside the read-only tools. The runner clears Anthropic/OpenAI API/base-url env vars before subscription-backed launches so subscription-backed runs cannot silently fall back to API billing.
