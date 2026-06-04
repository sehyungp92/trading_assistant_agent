# Trading Assistant Agent

An evidence-ranked improvement engine for algorithmic trading strategies. The system is a read-only local orchestrator: it does not place orders, cancel orders, change live positions, or directly command bots. Material strategy changes are approval-gated and must be supported by full-fidelity replay evidence.

## Why this repo exists

The end goal is a repeatable evidence loop that:

1. Identifies strategy weaknesses from real bot telemetry and market data.
2. Proposes high-value, evidence-grounded changes.
3. Validates them with realistic full-fidelity replay.
4. Routes them through human approval.
5. Measures deployed outcomes against the same objective used for selection.
6. Feeds those outcomes back into future candidate generation, gates, priors,
   and rollback decisions.

Reporting and weekly suggestion lists are not the goal &mdash; durable strategy improvement under explicit gates is.

## What the system does

### Senses bot health and triages errors

- Ingests every trade, missed opportunity, daily snapshot, and error event from each bot in real time via a relay service.
- Classifies error severity deterministically (CRITICAL/HIGH/MEDIUM/LOW) and routes by complexity &mdash; obvious fixes get a model-generated diagnosis and draft PR; complex issues are flagged for human investigation.
- Tracks error rates per bot with sliding-window spike detection (&gt;3/hour auto-promotes severity).
- Monitors bot heartbeats and alerts on gaps (&gt;2h warning, &gt;4h critical).
- Runs morning and evening proactive scans for unusual losses (&gt;2&sigma; from 30-day mean) and repeated error patterns.

### Curates evidence across multiple dimensions

Each day, raw bot events are transformed into a curated analysis package per bot covering:

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

The monthly learning loop is the authoritative path for material strategy/config changes. It assembles a frozen evidence package with:

- Market-data coverage manifests and telemetry lineage.
- Live-vs-backtest decision-level parity checks.
- Objective deltas, counterfactuals, and regime slices.
- Leakage and cost-realism signals from the monthly replay artifacts.
- Structured candidate proposals with calibrated predictions and rollback plans.

Approval-gated monthly candidates produce Telegram approval cards and GitHub PRs through shared approval infrastructure. After merge, deployment monitoring tracks the bot for regressions and can create rollback PRs if performance degrades.

### Proposes structural and portfolio-level improvements

Beyond parameter tuning, the strategy engine runs **19 deterministic detectors** across five categories:

- **Signal quality** (4) &mdash; alpha decay, signal decay, component signal decay, factor correlation decay.
- **Execution quality** (4) &mdash; exit timing, microstructure (fill quality, adverse selection), stress entry patterns, position-sizing mismatches.
- **Regime awareness** (3) &mdash; regime config effectiveness, regime transition cost, time-of-day patterns.
- **Portfolio structure** (5) &mdash; family imbalance, correlation concentration, drawdown-tier miscalibration, coordination gaps, heat-cap utilisation.
- **Pattern detection** (3) &mdash; drawdown patterns, filter interaction effects, correlation breakdown.

Detector findings feed weekly synthesis, which can surface structural ideas (e.g. "add a regime-aware exit rule", "split this strategy into two variants"). Weekly structural suggestions remain report-only until promoted into monthly candidate validation; production adoption requires isolated candidate testing, decision-level parity evidence, and human approval.

Portfolio-level proposals are validated through a what-if analysis that rescales historical family PnL under proposed weights to estimate portfolio Calmar, Sharpe, and max drawdown before any change is recorded. Each strategy carries an archetype profile that sets archetype-specific detection thresholds, so the engine respects each strategy's inherent characteristics rather than applying uniform rules.

## Monorepo layout

The supported checkout shape is a `packages/` monorepo with three workspaces that communicate only through frozen manifests and artifacts &mdash; direct runtime imports across workspaces are not allowed.

```
trading_assistant_agent/
  docs/                          # ADRs, plans, audits, target-state docs
  artifacts/                     # Run outputs, reports, ledger snapshots
  tools/                         # Repo-wide tooling
  _references/                   # Read-only reference code (e.g. trading repo patterns)
  trading-assistant-workflow-explainer.html
  packages/
    trading_assistant/           # Control plane: orchestrator, ledgers, approval routing
    trading_assistant_data/      # Canonical data product: market data, bundles, manifests
    trading_assistant_backtest/  # Replay & optimizer lab: diagnostics, phased-auto, OOS repair
```

| Package | Role | Owns |
|---|---|---|
| `trading_assistant` | Control plane | Run manifests, freeze windows, objective version, `round_N` configs, ledgers, approval state |
| `trading_assistant_data` | Data product | Canonical market data, calendars, checksums, bundle manifests, coverage reports |
| `trading_assistant_backtest` | Experiment lab | Diagnostics, phased-auto search, OOS repair, scoring, replay adapters, artifact emission |

The actual trading repo (separate) remains production truth for strategy
behavior. Structural candidates must prove decision-level parity against it
before they can be scored or approved.

## Event-flow architecture

```
VPS Bots → Sidecar → Relay VPS → POST /events → EventQueue (SQLite)
                                                       ↓
                                              OrchestratorBrain
                                            (classify → create task)
                                                       ↓
                                                    Worker
                                              (pick task → run agent)
                                                       ↓
                                                  AgentRunner
                                          (assemble context → provider profile → CLI runtime)
                                                       ↓
                                                runs/<id>/outputs/
                                                       ↓
                                          Telegram / Discord / Email
```

Inside the `trading_assistant` control-plane package:

```
orchestrator/   FastAPI app, brain, worker, scheduler, event queue, handlers
analysis/       prompt assemblers, strategy engine, context builders, response validation
skills/         data pipelines, metrics builders, simulation runners, trackers
comms/          Telegram, Discord, Email adapters + dispatcher + renderers
schemas/        Pydantic v2 models for all data contracts
memory/         policies/ (human-edited) + findings/ (system-written)
tests/          pytest, asyncio_mode=auto
```

`trading_assistant_data` and `trading_assistant_backtest` are reached only through frozen manifests, CLI/API contracts, and emitted artifacts.

## Cadence

| Cadence | Role | Authority |
|---|---|---|
| Daily | Sensor / diagnostic: anomalies, process failures, telemetry gaps, drawdown alerts | None over strategy changes |
| Weekly | Synthesis: scorecards, hypotheses, rotation across active strategy / portfolio scopes, build `monthly_search_brief.json` | Bounded search priors only &mdash; cannot trigger OOS repair, satisfy gates, or approve candidates |
| Monthly | Authoritative full-fidelity validation, optimization, and outcome measurement | Sole authority for material strategy/config changes (still human-approved) |

Weekly scope rotates across `k_stock_trader` + trading stock, trading momentum,
trading swing, and `crypto_trader`, then repeats.

### Scheduled tasks

| Task | Schedule | What it does |
|---|---|---|
| Daily Analysis | 06:00 UTC (configurable per bot timezone) | Per-bot daily report with quality gate |
| Weekly Summary | Sunday | Cross-bot review, suggestions, structural proposals, search-brief assembly |
| Monthly Validation | Monthly | Authoritative `round_N` diagnostics, phased-auto, OOS repair, approval-gated proposals |
| Proactive Scanner | Morning + evening | Anomaly detection, heartbeat monitoring |
| Learning Cycle | Weekly | Ground-truth snapshots, suggestion routing, ledger deltas |
| Outcome Measurement | Sunday 10:00 UTC | Early-warning 7/14/30-day pre/post against deployed suggestions (non-authoritative) |
| Memory Consolidation | Sunday 09:00 UTC | Aggregates findings, generates hypothesis candidates |
| Transfer Outcome Tracking | Sunday 10:30 UTC | Measures cross-bot pattern transfer results |
| Threshold Learning | Periodic | Adapts detector firing thresholds from outcome history |
| Experiment Check | Periodic | Auto-concludes experiments that reach statistical significance |
| Discovery Analysis | Periodic | Raw JSONL pattern discovery outside detector coverage |
| Reliability Verification | Periodic | Verifies system health and data pipeline integrity |

Bug triage runs on demand when HIGH+ severity errors arrive. The configured agent runtime is invoked per task (not always-running), keeping subscription-backed profiles at zero extra cost while idle.

## The monthly authoritative loop

Each month, after data sync and freeze (in-sample = all reliable data before
the latest completed month; selection-OOS = the latest completed month):

1. **`round_N` diagnostics** &mdash; full end-of-round diagnostics on the current optimized strategy and portfolio configs.
2. **Search brief** &mdash; consume the weekly `monthly_search_brief.json` as advisory priors only.
3. **LLM experiment plan** &mdash; diagnostics &rarr; structured phased-auto plan (signals, discrimination, entries, mechanisms, exits, structural candidates, overfit risks).
4. **Two-fold phased-auto on in-sample** &mdash; purged folds with embargo; `max_workers=2`; immutable score &le; 7 components; config-only and structural candidates compete under one objective.
5. **Conditional OOS repair** &mdash; triggered only when selection-OOS materially trails in-sample/fold expectation. Ablates all cumulative accepted mutations, perturbs locally, considers rollback and targeted additions.
6. **Repair-centered confirmatory follow-up** &mdash; the OOS-repair recommendation competes against incumbent, phased-auto winner, rollback candidates, and targeted additions under the same immutable objective.
7. **Adopt `round_N+1`** &mdash; update the rounds manifest, save end-of-round diagnostics, verify live/backtest parity, then route to model review and human approval.

Deployed verdicts come from the **next** completed monthly full-fidelity validation (the selection-OOS month is no longer clean once it influenced selection). Persistence is confirmed by a three-month or minimum-trade-count follow-up.

## Canonical objective

Selection and measurement both use `objective_weights_v1` (canonical policy in `memory/policies/v1/soul.md`, code-level source in `schemas/objective_weights.py`):

- 30% &mdash; expected return / net profit
- 20% &mdash; Calmar
- 15% &mdash; profit factor
- 15% &mdash; expectancy
- 10% &mdash; inverse max drawdown
- 10% &mdash; process quality (renormalized away when replay cannot simulate it)

Hard gates: no material in-sample deterioration, latest-month OOS improvement, positive support across purged folds, sufficient trade count, realistic costs, no large drawdown increase, no dependence on one or two outlier wins, no constraint breakage. Trade frequency is an under-trading gate, not a target.

## Safety boundary

- The assistant never places, cancels, or modifies live orders or positions.
- Models synthesize evidence and propose structural changes &mdash; they cannot route events, bypass gates, edit policy memory, or approve trading changes.
- Every material change requires human approval with replay evidence, objective deltas, failure attribution, and a rollback plan attached.
- `AutoOutcomeMeasurer` (7/14/30-day daily-summary windows) is retained for operational alerts and prompt context only &mdash; it is no longer authoritative for deployed outcomes.

## Human-in-the-loop

The system is read-only with respect to bots &mdash; it never sends commands to them. All changes flow through GitHub PRs that require human action to merge:

- **Parameter changes** &mdash; validated by monthly phased-auto and replay parity; require explicit Telegram approval before a PR is created.
- **Structural candidates** &mdash; may be implemented and scored inside the monthly phased-auto/backtest lane, but production PRs require decision-level parity, evidence gates, and human approval. Weekly structural suggestions remain report-only until promoted.
- **Bug fix PRs** &mdash; generated for obvious fixes; always require human review.
- **Rollback PRs** &mdash; created automatically on regression detection; still require human merge.
- **Portfolio allocation** &mdash; recommendations only; reallocating capital is a manual action.

Three-tier permission gates (`auto` / `requires_approval` / `requires_double_approval`, defined in `memory/policies/v1/permission_gates.md`) enforce this at the file-path level during PR review. Trading-logic and policy-document changes always require approval; the canonical objective and ground-truth function sit behind double approval so neither the system nor a single human action can change how performance is measured.

## Ledgers

| Ledger | Scope |
|---|---|
| `ProposalLedger` | Append-only provenance for every candidate, evaluation, rejection, experiment, approval, deployment, and outcome |
| `SuggestionTracker` | Actionable suggestion lifecycle and approval-facing status |
| `StrategyChangeLedger` | Canonical strategy-level changelog: what changed, why, when, on which strategy under which config, and whether it worked (one-month + multi-month verdicts) |

Broad candidate noise stays in `ProposalLedger`. Only selected changes, deployed changes, rollbacks, and explicit no-change decisions enter `StrategyChangeLedger`.

## Memory layers

The system maintains a five-layer memory model so harness improvements never become trading authority:

1. **Policy memory** &mdash; human-edited rules, objectives, gates, governance.
2. **Evidence memory** &mdash; monthly artifacts, ledgers, outcomes, priors, replay reports, rejected candidates.
3. **Advisory memory** &mdash; learning cards and generated playbooks with provenance, usage attribution, supersession, quarantine.
4. **Raw recall** &mdash; indexed run artifacts, session summaries, validator notes, model-review traces.
5. **Evaluation corpus** &mdash; executable harness benchmarks derived from failures, blocked proposals, calibration misses, and high-value successes.

Harness changes (prompts, retrieval, validators, parsers, generated playbooks, provider routing) must pass executable benchmarks before they are kept. Hard failures &mdash; approval bypass, direct live commands, hallucinated evidence, autonomous policy edits &mdash; override any score gains.

## Learning loop

Every suggestion is tracked from generation to deployed outcome and back into the next prompt:

```
                       Strategy engine (19 detectors)
                                  ↓
                  suggestion with ID → SuggestionTracker
                       ↓                          ↓
                config candidate            structural proposal
                       ↓                          ↓
              monthly validation             validation gates
              (phased-auto, OOS              (track record, category
               repair, replay parity)         win rate, calibration)
                       ↓                          ↓
              ProposalLedger &              report for human review
              StrategyChangeLedger
                       ↓
              Telegram approval card → GitHub PR
                       ↓
            Approve / reject via Telegram → lifecycle update
                       ↓
  ┌──── Learning cycle (weekly, advisory only) ──────────────────┐
  │ ground-truth snapshot → ledger delta → route pending items   │
  │ config candidates → monthly val.   structural → tracker      │
  │ weekly evidence → monthly_search_brief.json (advisory)       │
  └──────────────────────────────────────────────────────────────┘
                       ↓
       AutoOutcomeMeasurer (7/14/30-day pre/post, early warning only)
                       ↓
       Next monthly full-fidelity validation = primary deployed verdict
                       ↓
       3-month or min-trade follow-up = persistence verdict
                       ↓
  ┌──── Fed back into every subsequent prompt ───────────────────┐
  │ ground-truth trends · monthly outcomes · category scorecards │
  │ prediction accuracy · convergence · loop health · bias data  │
  └──────────────────────────────────────────────────────────────┘
```

The system will not re-suggest rejected ideas. Categories with low success rates have their suggestions stripped before delivery. Confidence is capped based on historical prediction accuracy. Hypotheses that accumulate rejections and negative outcomes are auto-retired. Measured outcomes and persistent correction patterns are synthesised into learning ledger entries without manual curation.

The loop is self-correcting &mdash; the harness monitors whether its own optimisation process is working and adapts without touching trading authority:

- **Convergence tracking** synthesises composite score trends, prediction accuracy, outcome ratios, and scorecard evolution into an overall signal (improving / degrading / oscillating / stable). When oscillation is detected, the LLM is instructed to hold steady rather than reversing last week's suggestions.
- **Loop health metrics** quantify proposal-to-measurement latency, oscillation severity, transfer success rate, recalibration effectiveness, suggestions per cycle, and measurement coverage. These are injected into every prompt so the agent can see where the learning pipeline itself is underperforming.
- **Temporal decay** applies a 5%/week exponential decay to scorecard outcome weights, matching the learning ledger's decay rate. Categories recover from early failures as old negatives fade.
- **Directional bias correction** detects systematic optimism or pessimism per metric in the LLM's prediction track record and reduces confidence on predictions matching the bias (capped at 20%).
- **Per-detector confidence calibration** gives each of the 19 detectors an empirical confidence multiplier derived from its outcome history &mdash; distinct from threshold learning, which adapts *when* a detector fires.
- **Structural proposal validation** runs six parity gates before any structural suggestion reaches a report: hypothesis track record, category track record, simplicity, acceptance-criteria presence, low-confidence block, and empirical calibration adjustment.
- **Instrumentation readiness scoring** evaluates each bot across eight capability categories and injects per-bot readiness reports into prompts, preventing confident conclusions from incomplete instrumentation.
- **Experiment auto-conclusion** tracks parameter experiments to statistical resolution, then escalates through the full chain: conclude experiment &rarr; accept/reject linked suggestion &rarr; record hypothesis outcome.

## Design philosophy

The system combines four reference architectures to serve a single goal: continuously improve trading bot performance while keeping a human in control of what matters. The four patterns share one objective function, one suggestion lifecycle, and the same approval gates &mdash; they are integrated, not stacked.

### From OpenClaw &mdash; disposable agents, permanent knowledge

The agent is disposable; the knowledge is permanent. The CLI runtime is a stateless executor that reads context, runs a skill, writes results, and exits. Everything that compounds value over time &mdash; outcome measurements, suggestion histories, calibration, correction logs, prompt patterns &mdash; lives in local files and SQLite: owned, queryable, backed up, inspectable.

This buys three concrete properties:

- **The brain is swappable.** When a better model arrives, swap the executor and everything continues. Four runtime providers (Claude Max, Codex Pro, Z.AI Coding Plan, OpenRouter) are already supported, with automatic fallback chains.
- **Every interaction is auditable.** The agent reads explicit context (memory files, skill prompts, event payloads) and writes explicit outputs (run-folder artifacts, JSONL records, parsed analyses), so any recommendation can be traced back to exactly what the agent saw.
- **Proactive intelligence without infrastructure.** APScheduler fires cron jobs for daily analysis, weekly synthesis, monthly validation, heartbeat monitoring, and proactive scanning &mdash; just scheduled subprocesses on the local machine.

Disposability depends on clear, enforceable boundaries: three-tier permission gates classify every action the system can take (auto, requires approval, requires double approval) and enforce them at the file-path level during PR review; separated memory tiers keep `memory/policies/` (versioned, human-edited only) distinct from `memory/findings/` (additive, time-stamped, system-written); deterministic routing keeps the orchestrator brain LLM-free for event classification and task creation.

### From Hermes &mdash; advisory memory and harness meta-learning

Hermes adds the advisory memory and harness layer that decides what the next agent run should see, and whether prompt, retrieval, validator, parser, playbook, or provider changes actually improve decision quality.

- **Prompt delivery closes the last-mile gap.** `InvocationBuilder.build_full_prompt()` merges instructions, corrections, skill methodology, ranked learning cards, and focused recall into the prompt itself, so upstream learning influences analysis instead of sitting in sidecar files the runtime may never read.
- **Learning cards turn past lessons into ranked retrieval.** Corrections, measured outcomes, discoveries, causal reasonings, recalibrations, spurious-outcome flags, hypothesis results, validator blocks, transfer outcomes, retrospectives, and validation logs are ingested as `LearningCard` objects scored by recency, impact, confidence, and context match, then injected most-relevant-first.
- **Session history and run recall flow through assemblers.** The session store passes through assembler paths into `base_package()`; `RunIndex` and focused recall can surface relevant prior artifacts, so the agent builds on prior reasoning rather than starting from a blank slate.
- **Bounded search briefs are the bridge into monthly optimization.** Weekly synthesis, learning cards, hypotheses, and prior outcomes are summarized into `monthly_search_brief.json` for planner and runner ordering only &mdash; the brief cannot choose the monthly sequence, trigger OOS repair, satisfy gates, approve changes, weaken policy memory, or command bots.
- **Generated memory remains advisory.** Policy memory and monthly evidence outrank learning cards, generated playbooks, raw recall, and harness benchmark results. Advisory artifacts require provenance, outcome attribution, supersession, quarantine, and keep/discard evidence before they re-enter prompts.

### From Autoresearch &mdash; an immutable objective and a separable evidence loop

A self-improving system needs an evaluation function it cannot modify and an optimization loop whose scoring, gates, repair triggers, and adoption decisions do not depend on model persuasion. The LLM can design experiments and review candidates after evidence is assembled; deterministic replay, objective scoring, parity gates, and approval policy remain decisive.

- **The ground-truth computer** (`skills/ground_truth_computer.py`) computes a single composite score from z-score-normalized metrics with fixed weights centralized in `schemas/objective_weights.py`. When replay cannot simulate process quality, the remaining weights renormalize. The objective lives behind the double-approval permission gate, so neither the system nor a single human action can change how performance is measured.
- **The monthly evidence loop** is the material strategy-learning path that replaces legacy WFO. The control plane owns frozen manifests, telemetry and market-data coverage checks, replay-parity evidence, monthly search-brief attachment, model review, candidate gates, approval packets, ledgers, and outcome measurement; full-fidelity replay is delegated to `trading_assistant_backtest`.
- **The weekly learning cycle** remains a sensor, early-warning, and context provider. Its influence on monthly optimization is intentionally bounded to `monthly_search_brief.json` &mdash; it may steer planner emphasis, phase order, seed neighborhoods, negative priors, and conditional repair-ablation priority, but it cannot create approval-ready candidates, change the monthly sequence, trigger OOS repair, or satisfy adoption gates.

### From Symphony &mdash; isolated candidate orchestration

Symphony contributes the runner boundary for expensive monthly optimisation work, not the trading brain. The Symphony-style layer owns deterministic per-candidate workspaces, path containment with enforced subprocess `cwd`, repo-owned optimizer workflow contracts, candidate-attempt state, retry/backoff, stall detection, drift reconciliation, and structured attempt logs.

It explicitly does not own strategy logic, replay scoring, live/backtest parity gates, approval or deployment decisions, ticket workflow, or live trading commands. `trading_assistant` remains the control plane and ledger; `trading_assistant_backtest` is the experiment lab; the actual trading repo remains production source of truth.

### How they integrate

- **Shared objective function.** Daily ground truth, monthly replay evidence, and approval-gated candidate scoring draw from the same vocabulary in `schemas/objective_weights.py`. Replay layers renormalize only when process quality is unavailable; trade frequency stays a viability gate. When the weights are updated behind double approval, evaluation, candidate scoring, and outcome measurement move together.
- **Unified suggestion lifecycle.** Suggestions and monthly candidates flow with deterministic IDs through `SuggestionTracker`, `ProposalLedger`, and `StrategyChangeLedger`, then through approval, implementation, deployment monitoring, rollback/watch decisions, and outcome measurement. The next completed one-month full-fidelity validation is the primary deployed verdict; early-warning windows are prompt context only.
- **Experiment-to-hypothesis traceability.** On statistical resolution, the auto-conclusion chain updates the linked suggestion (accept / reject) and records the outcome against the hypothesis that motivated it (positive / negative). The next analysis prompt reflects not just "this change was tested" but "the hypothesis behind it was strengthened or weakened."
- **Bidirectional context flow.** Weekly results flow back through context assembly, monthly outcome priors, learning cards, focused recall, and `monthly_search_brief.json`. The LLM sees what was tried, what worked, which candidate families have poor track records, whether the system is converging or oscillating, where its directional biases lie, which bots have sufficient instrumentation, and which weak weekly signals should stay low-confidence.
- **Governance prevents gaming.** Because `soul.md` and the ground-truth formula sit behind human-only policy controls, the system cannot shift to something easier to optimize. Structural and config candidates must pass data coverage, replay parity, objective, no-regression, model-review, approval-payload, and human approval gates before adoption. The system learns from its own history through an evaluation function it cannot change.

### Matching the change type to the right tool

- **Parameter changes** &mdash; adjusting a stop-loss percentage, a signal threshold, a filter sensitivity. Numerical optimization problems with a clear objective function, owned by the monthly evidence and replay validation loop. Phased-auto compares config candidates against frozen artifacts, replay parity, objective thresholds, OOS degradation checks, and rollback requirements before approval.
- **Structural changes** &mdash; adding a regime-aware exit rule, splitting a strategy into variants, redesigning a filter interaction. First-class phased-auto candidates inside the monthly loop, not a separate advisory-only lane. The LLM designs candidate patches; the runner applies them in isolated workspaces across the live strategy repo and backtest adapter; unit, decision, and decision-level parity tests run before fold scoring; config neighborhoods are tuned around passing structural candidates.
- **Portfolio-level changes** &mdash; rebalancing family allocation weights, adjusting risk caps, modifying coordination rules, changing drawdown-tier multipliers. Validated through a what-if analysis (`skills/portfolio_what_if.py`) that rescales historical family PnL under the proposed weights to estimate portfolio Calmar, Sharpe, and max drawdown. Where per-family trade-level data exists, the what-if uses individual trades for intra-day max drawdown, Sortino, profit factor, and regime breakdowns that daily aggregation would mask. Outcomes are measured over a 30-day observation window (vs 7 days for strategy-level); regime shifts during the window yield INCONCLUSIVE verdicts rather than false signals.

## Running the system

Operational setup, env vars, CLI commands, and the secure-binding rules for the control-plane FastAPI app live in [`packages/trading_assistant/README.md`](packages/trading_assistant/README.md). Canonical data-sync jobs are documented in [`packages/trading_assistant_data/README.md`](packages/trading_assistant_data/README.md); the monthly optimizer runner contract lives in [`packages/trading_assistant_backtest/MONTHLY_OPTIMIZER_WORKFLOW.md`](packages/trading_assistant_backtest/MONTHLY_OPTIMIZER_WORKFLOW.md).

The agent runtime is swappable per workflow between Claude Max (default), Codex Pro, Z.AI Coding Plan, and OpenRouter-backed Claude-compatible models &mdash; selection is persisted in `data/agent_preferences.json` and surfaced via `GET/PUT /agent/preferences` and the Telegram `/settings` panel. Daily and weekly Claude workflows use read-only tool allowlists (`Read`, `Grep`, `Glob`); monthly model review runs without tools; triage keeps `Bash` enabled alongside the read-only tools. The runner clears Anthropic/OpenAI API/base-url env vars before subscription-backed launches so Max/Pro runs cannot silently fall back to API billing.

## Where to look next

| File | Purpose |
|---|---|
| [`trading-assistant-workflow-explainer.html`](trading-assistant-workflow-explainer.html) | Narrated system map, cadence timeline, gap and roadmap status |
| [`docs/workflow-learning-loop-target-state.md`](docs/workflow-learning-loop-target-state.md) | Authoritative target-state spec and 12-phase implementation plan |
| [`docs/2026-06-04-final-monorepo-package-structure-implementation-plan.md`](docs/2026-06-04-final-monorepo-package-structure-implementation-plan.md) | Final monorepo structure plan |
| [`docs/2026-06-02-approval-grade-monthly-learning-loop-implementation-plan.md`](docs/2026-06-02-approval-grade-monthly-learning-loop-implementation-plan.md) | Approval-grade monthly loop implementation plan |
| `packages/trading_assistant/README.md` | Control-plane package details |
| `packages/trading_assistant_data/README.md` | Canonical data-product package details |
| `packages/trading_assistant_backtest/README.md` | Replay & optimizer package details |
| `packages/trading_assistant_backtest/MONTHLY_OPTIMIZER_WORKFLOW.md` | Repo-owned workflow contract for monthly optimizer runs |
