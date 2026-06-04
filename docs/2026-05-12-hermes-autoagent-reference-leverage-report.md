# Hermes Agent And AutoAgent Reference Leverage Report

Date: 2026-05-12

Scope: local review of `_references/hermes-agent/`, `_references/autoagent/`, and the current `trading_assistant` learning architecture.

Goal: identify high-value reference mechanisms that can be leveraged or ported into `trading_assistant` to make it a stronger evidence-grounded learning system for proposing meaningful strategy, risk, and execution improvements over time, while preserving human approval gates and maximizing expected risk-adjusted returns.

## Executive Summary

The highest-value path is not to port Hermes Agent or AutoAgent wholesale. `trading_assistant` already has a domain-specific architecture with event ingestion, monthly evidence/replay validation, outcome ledgers, learning cards, generated playbooks, provider routing, and approval gates. The best leverage is to port the reference mechanisms that close gaps in the learning loop:

1. Add an AutoAgent-style executable harness benchmark for the analysis system itself. The current `skills/harness_eval_runner.py` is AutoAgent-inspired but still mostly heuristic. Replacing it with frozen, replayable benchmark cases that actually run prompt assembly, retrieval, validation, and output parsing would let the system keep or discard prompt/context/validator/provider changes based on measured decision quality.

2. Add a Hermes-style asynchronous learning reviewer after complex runs and failed validations. This reviewer should not change trading logic. It should inspect run artifacts and decide whether to create or update learning cards, generated playbooks, benchmark cases, or correction patterns through `skills/learning_write_coordinator.py`.

3. Upgrade recall from "recent summaries plus snippets" to Hermes-style searchable evidence recall. `orchestrator/run_index.py` already provides FTS5 run search, and `analysis/context_builder.py` already retrieves similar runs. The high-value next step is focused summarization of top matching runs/artifacts, with explicit provenance and outcome status.

4. Treat generated playbooks as domain skills and give them Hermes-style lifecycle management. `skills/playbook_generator.py` already creates evidence-backed procedural guidance. It should gain a stronger guard, usage/outcome attribution, a curator that consolidates overlapping playbooks, and recoverable archival for stale or harmful playbooks.

5. Use AutoAgent's `program.md` concept to define a human-owned "analysis harness program" for improving the agent harness, not live trading rules. The loop should be allowed to edit prompts, context retrieval, validators, scoring, and routing only within explicit boundaries. It should never weaken approval gates or directly modify bot trading behavior.

6. Keep the monthly evidence/replay loop as the authority for material trading changes. Hermes improves in-context learning and procedural memory. AutoAgent improves the harness through measured experiments. Neither should replace the existing monthly validation and approval architecture.

The repo already contains partial ports of both ideas: `LearningCardStore`, `RunIndex`, `BenchmarkCompiler`, `HarnessEvalRunner`, `PlaybookGenerator`, `OutcomePriorStore`, `ProviderRouteScorer`, and the monthly validation pipeline. The highest-return work is to harden these into a closed loop where every memory, playbook, prompt change, and provider route can be traced to evidence, evaluated offline, and retired if it stops helping.

## Second-Pass Code Audit Corrections

This report was re-audited against the current code after the first draft. The main corrections are:

- `analysis/monthly_repair_prompt_assembler.py` is referenced by existing planning docs, but it is not present in this checkout. The report should not treat it as an implemented foothold. The implemented monthly model-review pieces are `schemas/monthly_model_review.py`, `analysis/monthly_model_response_parser.py`, `analysis/monthly_model_response_validator.py`, and the optional `model_review.json` validation path in `skills/monthly_candidate_pipeline.py`.

- Learning-card feedback is more advanced than the first draft implied. `Handlers._record_learning_card_feedback_targeted()` already marks retrieved cards helpful or harmful from validation signals, and `tests/test_learning_card_feedback.py` covers category/reason matching, ambiguity suppression, and relevance-score movement. The remaining gap is broader attribution from monthly outcomes, report quality, playbook usage, and long-horizon realized performance.

- Generated playbooks already have a basic safety/usage lifecycle. `PlaybookGenerator._is_safe()` requires provenance and at least three evidence refs, rejects several approval-bypass/live-change phrases, stores `PlaybookTracking`, supports `record_usage()`, `record_outcome()`, and `retire_ineffective()`, and `orchestrator/app.py` calls `retire_ineffective()` during weekly memory consolidation. The remaining gap is that usage/outcome recording does not appear wired into prompt injection or downstream outcome measurement, and there is no Hermes-style consolidation, pinning, archive/restore, or richer safety scanner.

- Provider routing is already partially live, not only advisory. `ProviderRouteScorer.recompute()` writes workflow/provider/model scores, and `AgentPreferencesManager._resolve_learned_selection()` can choose a better provider when the score gap and sample thresholds pass. The remaining gap is stronger evaluation input and workflow coverage: `AgentWorkflow` currently covers `daily_analysis`, `weekly_analysis`, `wfo`, and `triage`, while monthly validation/model review is not a first-class provider preference workflow.

- `MemoryConsolidator` is relevant existing infrastructure. It is scheduled weekly, rebuilds `memory/index.json`, consolidates high-volume findings into `patterns_consolidated.md`, and can create hypothesis candidates from systemic root-cause counts. It is not a Hermes-style post-run LLM reviewer, but it is already a deterministic memory-maintenance path.

- The report's core recommendation remains unchanged: the biggest missing piece is still an executable harness benchmark and keep/discard loop. `BenchmarkCompiler` creates useful cases, but `HarnessEvalRunner` still scores variants synthetically instead of executing the analysis harness against frozen cases.

## Code Audit Evidence Map

The following files were checked directly during the second pass:

- `skills/harness_eval_runner.py`: confirms benchmark variants are scored by rule-based heuristics (`baseline` starts at 0.45, candidates at 0.5, then receive tag/profile bonuses). It does not execute prompt assembly, agent output, response parsing, or validators.

- `skills/benchmark_compiler.py`: confirms benchmark cases are genuinely compiled from validation blocks, negative outcomes, calibration misses, and transfer failures, with artifact refs and snapshots. This is a good corpus builder; the evaluator is the weak link.

- `skills/learning_cycle.py`: confirms the weekly learning loop already orchestrates ground truth, retrospective synthesis, hypothesis updates, category recalibration, benchmark compilation, provider scoring, harness eval, playbook generation, experiment selection, and ledger recording.

- `skills/learning_card_store.py` and `schemas/learning_card.py`: confirm learning cards already support retrieval counts, helpful/harmful feedback, supersession, activity filtering, relevance scoring, and ingestion from many existing JSONL sources.

- `orchestrator/handlers.py`: confirms daily/weekly validation can mark injected learning cards helpful or harmful through `_record_learning_card_feedback_targeted()`.

- `skills/playbook_generator.py` and `schemas/generated_playbook.py`: confirm basic generated-playbook safety, tracking, outcome counters, quarantine, and retirement exist. They do not yet provide Hermes-style consolidation, pinning, recoverable archive/restore, or prompt-injection-time usage attribution.

- `orchestrator/memory_consolidator.py`: confirms a scheduled deterministic consolidation/index path exists, including root-cause counting and hypothesis candidate creation. This is not the same as Hermes' LLM background reviewer.

- `orchestrator/run_index.py`, `orchestrator/session_store.py`, and `analysis/context_builder.py`: confirm run-level FTS exists and is injected as compact similar-run snippets. Full trajectory/session search with summarization does not exist.

- `skills/provider_route_scorer.py` and `orchestrator/agent_preferences.py`: confirm learned provider recommendations are already used when sample and score-gap thresholds pass. Monthly validation/model review is not currently a first-class `AgentWorkflow`.

- `skills/monthly_validation_orchestrator.py`, `skills/monthly_candidate_pipeline.py`, `analysis/monthly_model_response_parser.py`, `analysis/monthly_model_response_validator.py`, and `schemas/monthly_model_review.py`: confirm monthly model-review parsing/validation exists for a pre-existing `model_review.json`, but no in-repo monthly review agent invocation or repair prompt assembler exists.

## Reference Architecture Readout

### Hermes Agent: What Matters

Hermes Agent is primarily a mechanism for in-context learning and durable procedural memory. Its most relevant design ideas are:

- Bounded memory surfaces. `tools/memory_tool.py` manages `MEMORY.md` and `USER.md` as compact, file-backed memories. These are intentionally tiny and stable. General facts go into memory; procedures go into skills; raw history remains searchable elsewhere.

- Autonomous skill creation. `run_agent.py` counts turns and tool-call iterations. After enough activity, it spawns a background reviewer that can create or update skills using `tools/skill_manager_tool.py`. The main task is not blocked.

- Skill safety scanning. `tools/skills_guard.py` scans agent-created skills for exfiltration, prompt injection, persistence, destructive commands, hardcoded secrets, path traversal, binaries, symlinks, and structural risk.

- Skill lifecycle management. `agent/curator.py` periodically reviews agent-created skills, consolidates one-off micro-skills into broader class-level skills, archives stale skills recoverably, and skips pinned or human-owned skills.

- Searchable raw history. `hermes_state.py` stores sessions and messages in SQLite with FTS5 and trigram search. `tools/session_search_tool.py` retrieves and summarizes prior sessions when they are likely relevant.

- Prompt-cache-aware memory discipline. Hermes avoids mutating the active prompt mid-session. Memory writes affect future sessions, reducing prompt instability.

- Tool and plugin hooks. Hermes uses a registry and hooks around tool calls and model calls. This is less directly important than the memory/skill loop, but it is a useful pattern for instrumentation and background learning.

The Hermes lesson for this repo: learning should be extracted from actual work, saved into the correct memory layer, guarded, retrieved on demand, and curated over time.

### AutoAgent: What Matters

AutoAgent is not a memory mechanism. It is a harness-improvement loop. Its core design is:

- A human-owned `program.md` defines what the agent harness is supposed to become.

- A meta-agent edits the harness, prompt, tools, runtime configuration, or orchestration.

- A benchmark suite evaluates the modified harness against a baseline.

- A results ledger records each experiment.

- A keep/discard rule retains only improvements. If scores tie, simpler wins. Discarded experiments remain useful learning signal.

- The loop uses a fixed adapter boundary, so the harness can improve without changing the evaluator contract.

- The anti-overfitting test is: if this exact task disappeared, would the change still be worthwhile?

The AutoAgent lesson for this repo: improvements to the analysis harness should be treated as experiments, evaluated against benchmark cases derived from real failures and outcomes, and accepted only when they improve measured decision quality.

## Current Trading Assistant Baseline

`trading_assistant` already has many of the ingredients that Hermes and AutoAgent would otherwise add from scratch.

### Existing Strengths

- The repo has a strong domain objective: ingest structured bot events, analyze evidence, propose improvements, and deliver reports/actions while preserving approval gates.

- `docs/adr/0001-monthly-evidence-replay-foundation.md` makes monthly evidence/replay validation authoritative for material strategy/config decisions. This is the correct anchor. Daily, weekly, WFO-like, and early measurements should be sensors, not authority.

- `skills/monthly_validation_orchestrator.py` builds the monthly artifact flow: telemetry manifest, market-data manifest, run manifest, external replay, parity report, gap attribution, candidate pipeline, and outcome prior snapshots.

- `skills/monthly_candidate_pipeline.py` already applies deterministic candidate gates for evidence paths, market coverage, telemetry lineage, replay parity, leakage, improvement, calibration, trade count, costs, drawdown, risk, phase support, and outcome priors.

- `skills/monthly_outcome_measurer.py`, `skills/outcome_prior_store.py`, and `skills/strategy_change_ledger.py` form a credible evidence-to-priors loop.

- `skills/learning_card_store.py` is a domain-specific memory primitive. It supports typed learning cards, relevance ranking, retrieval counts, helpful/harmful feedback fields, supersession, confidence, and context matching.

- `Handlers._record_learning_card_feedback_targeted()` already closes part of the retrieval feedback loop by marking retrieved cards helpful or harmful based on approved/blocked validation tags.

- `orchestrator/run_index.py` is already Hermes-like in one important way: it uses SQLite FTS5 to index run artifacts.

- `analysis/context_builder.py` already injects workflow-aware learning context, ranked learning cards, similar past runs, generated playbooks, outcome priors, category scorecards, forecast meta-analysis, hypothesis records, transfer records, and validation patterns.

- `skills/benchmark_compiler.py`, `schemas/benchmark_case.py`, `skills/harness_eval_runner.py`, and `schemas/harness_learning.py` are already AutoAgent-inspired.

- `skills/learning_cycle.py` already runs a weekly learning sequence that computes ground-truth deltas, builds retrospective synthesis, updates hypothesis lifecycle, compiles benchmark cases, recomputes provider scores, runs harness eval, generates playbooks, selects experiments, and records the learning ledger.

- `skills/playbook_generator.py` and `schemas/generated_playbook.py` already implement a "generated procedural memory" concept similar to Hermes skills, with evidence references, trigger conditions, required evidence, steps, failure modes, basic safety checks, usage/outcome tracking fields, and quarantine support.

- `orchestrator/memory_consolidator.py` provides a scheduled deterministic consolidation/indexing path and can generate hypothesis candidates from recurring root-cause counts.

- `skills/provider_route_scorer.py` is already connected to learned provider selection through `AgentPreferencesManager`, subject to sample and score-gap thresholds.

- Monthly model-review parsing and validation already exist through `analysis/monthly_model_response_parser.py`, `analysis/monthly_model_response_validator.py`, and `schemas/monthly_model_review.py`. The monthly candidate pipeline validates an existing `model_review.json` if the backtest artifact directory supplies one.

- `orchestrator/invocation_builder.py` correctly frames learning cards and generated playbooks as advisory evidence, not overriding instructions. This matters because agent-generated memory must not become a hidden policy channel.

### Current Gaps

- The harness evaluation path is not yet a true AutoAgent loop. `HarnessEvalRunner` currently assigns mostly synthetic scores by variant name and tags. It does not actually rerun the analysis harness against frozen cases and judge behavior.

- There is no Hermes-style post-run LLM reviewer that systematically extracts durable learning after a complex run, failed validation, or materially wrong recommendation. The existing `MemoryConsolidator` is useful, but it is deterministic aggregation, not artifact-aware review of a completed run.

- `SessionStore` records compact JSONL summaries, but it does not preserve rich message/tool trajectories like Hermes. `RunIndex` is stronger, but it still returns snippets rather than focused summaries of the most relevant evidence.

- Generated playbooks already have basic safety checks, tracking schema, quarantine, and weekly retirement. They do not yet have a Hermes-like curator that consolidates redundant playbooks, pins human-approved playbooks, archives/restores playbooks recoverably, patches incorrect playbooks, or wires usage/outcome attribution into prompt injection and downstream measurement.

- Learning-card retrieval already increments retrieval count in `ContextBuilder`, and daily/weekly validation already supplies targeted helpful/harmful feedback through handlers. The system still needs broader attribution tied to monthly outcomes, report quality, recall usefulness, playbook use, and long-horizon realized performance.

- The monthly candidate pipeline validates `model_review.json` if present, but the monthly orchestrator does not appear to invoke a model-review agent or repair prompt path as a first-class step. Also, `analysis/monthly_repair_prompt_assembler.py` is not present in this checkout despite being mentioned in planning docs.

- Learned provider routing exists for configured `AgentWorkflow` values, but monthly validation/model review is not represented in `AgentWorkflow`, so high-consequence monthly work cannot yet benefit from separate learned routing and tuning.

- Existing cleanup planning notes that legacy WFO/autonomous/search paths still need to be demoted or retired so the monthly evidence loop remains the single authority for material changes.

## High-Value Leverage Opportunities

### 1. Replace Heuristic Harness Eval With Executable AutoAgent-Style Benchmarking

Priority: highest.

What to port: AutoAgent's benchmark-driven keep/discard loop.

Why it matters: The system's trading impact depends less on having more analysis and more on making better decisions: avoiding false-positive strategy changes, catching bad proposals, improving calibration, citing the right evidence, and escalating only when monthly validation is strong. A true harness benchmark would let the repo improve prompt assemblers, retrieval, validators, and provider routing with measured evidence instead of intuition.

Existing foothold:

- `skills/benchmark_compiler.py`
- `schemas/benchmark_case.py`
- `skills/harness_eval_runner.py`
- `schemas/harness_learning.py`
- `skills/learning_cycle.py`
- `skills/provider_route_scorer.py`

Problem: the current runner is not yet measuring real harness performance. It uses rule-based score adjustments rather than running the actual analysis package through the candidate prompt/context/validator stack.

Recommended design:

1. Define an executable `AnalysisHarnessBenchmarkCase` view over existing `BenchmarkCase` records.

2. Freeze enough inputs to rerun a decision:
   - workflow type
   - bot id and strategy id
   - selected learning cards/playbooks
   - prompt package inputs
   - relevant artifacts and ledgers
   - expected behavior
   - forbidden behavior
   - scoring rubric

3. Run candidate harness variants against the case. A variant can change:
   - context retrieval ranking
   - learning-card selection
   - generated-playbook injection rules
   - prompt assembler templates
   - validator thresholds
   - provider/model route selection
   - response parser strictness

4. Score observable outputs:
   - structured output parse success
   - validator pass/block accuracy
   - evidence citation completeness
   - whether the model repeats a previously rejected or negative-outcome proposal
   - whether the model escalates material changes only through monthly approval
   - confidence calibration against known outcomes
   - candidate gate consistency
   - hallucinated artifact/path rate
   - cost/latency as secondary metrics

5. Apply AutoAgent keep/discard:
   - keep when primary score improves without governance regression
   - keep when score ties and complexity/cost decreases
   - discard otherwise
   - always log the experiment and diagnosis

6. Enforce the anti-overfitting question:
   - "If this exact bot/date/case disappeared, would this harness change still be worthwhile?"

Acceptance criteria:

- A benchmark run can compare baseline vs candidate using real prompt assembly and validation.
- A candidate cannot be accepted if it weakens approval gates, increases forbidden suggestions, or lowers monthly candidate gate fidelity.
- Results are stored as a durable experiment ledger with enough detail to explain why a change was kept or discarded.
- Discarded experiments produce learning records, not silent loss.

Suggested files:

- Extend `skills/harness_eval_runner.py`
- Extend `schemas/harness_learning.py`
- Add `docs/agent_harness_program.md` or `memory/policies/v1/harness_program.md`
- Add tests around real scoring cases in `tests/test_harness_eval_runner.py`

### 2. Add A Hermes-Style Post-Run Learning Reviewer

Priority: very high.

What to port: Hermes background memory/skill review, adapted to trading artifacts.

Why it matters: Many valuable learning signals appear during actual report generation: repeated validation blocks, ambiguous evidence, bad prior assumptions, prompt failures, stale playbooks, repeated root causes, and missed opportunities. Today, some signals enter ledgers through specific workflows, but there is no general reviewer whose job is to extract durable learning from a completed run.

Existing foothold:

- `skills/learning_write_coordinator.py`
- `skills/learning_card_store.py`
- `skills/playbook_generator.py`
- `orchestrator/run_index.py`
- `analysis/context_builder.py`
- `orchestrator/agent_runner.py`
- `orchestrator/memory_consolidator.py`
- `Handlers._record_learning_card_feedback_targeted()`

Recommended design:

Add `LearningReviewOrchestrator` that runs after selected agent invocations. It should be asynchronous or post-response, so it never delays operational delivery.

Trigger conditions:

- run produced a strategy suggestion
- report validation failed
- response parser produced partial/invalid structured output
- monthly candidate was blocked
- suggestion/outcome measurement contradicted prior expectation
- agent runtime took unusually many iterations or had repeated repair attempts
- N runs occurred since last review for the same workflow/bot/category

Reviewer inputs:

- run folder files
- `metadata.json`
- `response.md`
- `instructions.md`
- parsed structured output
- report checklist
- validation notes
- learning-card ids injected into the prompt
- generated-playbook ids injected into the prompt
- relevant outcome priors
- recent benchmark cases and validation blocks

Allowed write actions:

- create or update a learning card when existing ingestion/feedback does not already capture the lesson
- record learning-card retrieval as helpful/harmful when evidence supports it
- create a benchmark case from a failure or blocked proposal
- propose a generated playbook update
- quarantine a generated playbook if it appears harmful or stale
- add a correction pattern

Forbidden write actions:

- edit `memory/policies`
- change live trading rules
- approve or deploy strategy changes
- weaken approval gates
- write arbitrary files outside learning/artifact directories

Acceptance criteria:

- The reviewer produces no output unless it can cite concrete artifacts.
- Every write goes through `LearningWriteCoordinator`.
- The reviewer can be disabled per workflow.
- Reviewer writes are idempotent by dedup key.
- Generated learning is advisory until validated by downstream outcomes.

This is the closest direct Hermes port and likely one of the highest compounding improvements.

### 3. Upgrade Run Recall To Focused Evidence Summarization

Priority: high.

What to port: Hermes session search with FTS5 retrieval and summarization.

Why it matters: Trading analysis has many repeated motifs: the same strategy family failing in a regime, the same risk cap blocking otherwise good trades, the same slippage pattern, the same calibration mistake, or the same proposal being rejected twice. Better recall reduces repeated mistakes and improves proposal specificity.

Existing foothold:

- `orchestrator/run_index.py` already provides SQLite FTS5 search.
- `analysis/context_builder.py` already builds a retrieval profile and injects `similar_past_runs`.
- `orchestrator/session_store.py` records run summaries.

Gap: similar-run retrieval currently returns compact snippets. It does not summarize full relevant artifacts into a high-signal, provenance-rich memory package.

Recommended design:

Add a `RunRecallSummarizer` that:

1. Searches `RunIndex` with the current workflow, bot, regime, category, and validation patterns.

2. Loads the top run folders and relevant artifacts.

3. Summarizes only the decision-relevant evidence:
   - what was proposed
   - what evidence supported it
   - what validators said
   - whether it was approved, rejected, blocked, implemented, measured, or rolled back
   - what the eventual outcome was
   - what should be remembered for the current run

4. Emits compact recall cards with artifact paths and outcome status.

5. Injects recall as evidence context, not instructions.

Acceptance criteria:

- Recall entries include provenance paths and dates.
- Entries clearly distinguish proposal, validation status, and eventual outcome.
- The context builder can budget recall separately from learning cards.
- The system can suppress stale or contradicted recall when a newer outcome supersedes it.

This is a safer and more domain-relevant version of Hermes session search. It should emphasize outcomes and validation status, not just lexical similarity.

### 4. Give Generated Playbooks A Hermes-Style Guard And Curator

Priority: high.

What to port: Hermes skill safety scanning and curator, extending the basic playbook lifecycle that already exists.

Why it matters: Generated playbooks are powerful because they can capture procedural knowledge. They are risky because stale procedural memory can quietly bias every future run. The more the system learns, the more important memory hygiene becomes.

Existing foothold:

- `skills/playbook_generator.py`
- `schemas/generated_playbook.py`
- `analysis/context_builder.py`
- `orchestrator/app.py` weekly `retire_ineffective()` call

Already implemented:

- Playbooks require repeated evidence (`min_evidence=3` by default).
- `_is_safe()` rejects missing provenance and several approval-bypass/live-change phrases.
- `PlaybookTracking` tracks usage and positive/negative outcomes.
- `retire_ineffective()` quarantines sufficiently used low-effectiveness playbooks and removes their markdown files.

Remaining gap: the lifecycle is present but shallow. Usage is not recorded when `ContextBuilder` injects playbooks, outcome attribution is not wired to monthly/report outcomes, the safety scanner is simple phrase matching, and there is no consolidation, pinning, archive/restore, or patch flow.

Recommended design:

Extend the current safety check into `GeneratedPlaybookGuard`:

- Require sufficient evidence references.
- Require trigger conditions, required evidence, investigation steps, expected outputs, and failure modes.
- Reject playbooks that imply direct deployment, approval bypass, live bot commands, disabled gates, or unsupported authority.
- Reject playbooks with unbounded scope, vague "always do X" instructions, or missing provenance.
- Validate referenced artifact paths.
- Enforce maximum size and maximum number of active generated playbooks per workflow/category.

Add `GeneratedPlaybookCurator`:

- Runs weekly or after a threshold number of playbook retrievals.
- Consolidates overlapping one-off playbooks into broader playbooks.
- Archives stale playbooks recoverably rather than deleting them.
- Pins human-approved playbooks.
- Quarantines playbooks associated with harmful downstream outcomes.
- Updates playbook metadata with usage and outcome attribution.

Acceptance criteria:

- A playbook can be traced to evidence refs and downstream usage.
- Repeatedly unhelpful playbooks stop being injected.
- Human-pinned playbooks are protected from autonomous deletion.
- Curator actions are logged and reversible.
- Playbook ids injected into a prompt are recorded as used, just as learning-card ids already record retrieval.

This is a strong Hermes port because playbooks are the trading-specific equivalent of skills.

### 5. Create A Human-Owned Analysis Harness Program

Priority: high.

What to port: AutoAgent's `program.md` as the objective contract.

Why it matters: A harness-improvement loop needs a written target. Without a target, it may optimize superficial metrics like parse success or report verbosity instead of better trading decisions.

Recommended location:

- `docs/agent_harness_program.md` for a design-facing version; or
- `memory/policies/v1/harness_program.md` if it should become part of the policy set.

Recommended contents:

- Mission: improve evidence-grounded analysis and proposal quality to maximize expected risk-adjusted returns over time.
- Scope: analysis harness, prompt assembly, retrieval, validators, response parsing, benchmark scoring, provider routing, and generated memory.
- Out of scope: live trading execution, direct bot commands, policy edits, approval-gate weakening, objective-function changes without human approval.
- Primary metrics:
  - fewer false-positive strategy changes
  - more high-value validated proposals
  - better confidence calibration
  - better use of authoritative monthly outcomes
  - fewer repeated rejected ideas
  - lower hallucinated evidence rate
- Secondary metrics:
  - cost
  - latency
  - report compactness
  - provider availability
- Keep/discard rules.
- Overfitting rule.
- Governance invariants.

Acceptance criteria:

- Harness experiments reference the program explicitly.
- The evaluator can reject a change that improves a narrow score but violates the program.
- The program is human-owned and versioned.

### 6. Make Provider Routing Outcome-Aware And Benchmark-Aware

Priority: medium-high.

What to port: AutoAgent's measured comparison discipline, applied to provider routing.

Existing foothold:

- `skills/provider_route_scorer.py`
- `orchestrator/agent_preferences.py`
- `orchestrator/provider_cooldown.py`
- `orchestrator/cost_tracker.py`

Already implemented:

- Provider scores combine validation pass rate, measured outcomes, and calibration.
- `recommend_provider()` uses minimum samples and score-gap thresholds.
- `AgentPreferencesManager._resolve_learned_selection()` can use the recommendation automatically.
- Fallback chains and provider cooldown already exist.

Remaining gap: the scoring inputs are only as good as current validation/outcome attribution, and monthly validation/model review is not represented in `AgentWorkflow`.

Recommended design:

- Score provider/workflow routes using executable benchmark results plus real downstream outcomes.
- Keep minimum sample sizes and score-gap requirements.
- Treat monthly validation and strategy refinement as high-consequence workflows where quality dominates cost.
- Allow cost/latency to break ties only after quality and governance metrics pass.
- Log route changes with reasons and rollback conditions.
- Add first-class workflow preferences for monthly validation/model review if model-reviewed monthly analysis becomes active.

Acceptance criteria:

- A provider is not promoted on cost alone.
- A provider can be demoted for parse failures, hallucinated evidence, validator misses, or poor calibration.
- Provider changes can be evaluated offline before production use.

### 7. Wire Monthly Model Review And Repair Into The Monthly Loop

Priority: medium-high.

What to leverage: existing monthly repair/model-review components, strengthened by AutoAgent eval.

Existing foothold:

- `skills/monthly_validation_orchestrator.py`
- `skills/monthly_candidate_pipeline.py`
- `analysis/monthly_model_response_parser.py`
- `analysis/monthly_model_response_validator.py`
- `schemas/monthly_model_review.py`
- `orchestrator/backtest_invocation.py`
- `docs/2026-05-12-monthly-learning-loop-cleanup-plan.md`

Observed gap: the monthly candidate pipeline validates `model_review.json` if present, but monthly orchestration does not appear to invoke model review as a first-class step. The report's first draft also repeated a stale planning-doc assumption: `analysis/monthly_repair_prompt_assembler.py` is not present in this checkout.

Recommended design:

- Create or restore a monthly model-review/repair prompt assembler if this is still the desired architecture.
- After deterministic monthly artifacts are assembled, invoke a monthly model-review agent only when the artifact readiness gates pass.
- Require the model review to output structured findings, candidate interpretation, uncertainty, and repair requests.
- If artifacts are incomplete, invoke the repair prompt path rather than letting the model infer through missing data.
- Use the executable harness benchmark to test changes to monthly review prompts.

Acceptance criteria:

- No monthly approval packet depends on a missing model review when model review is required.
- Repair requests are structured and tied to artifact paths.
- Monthly validation remains deterministic-first, model-second.

### 8. Close The Learning-Card Feedback Loop

Priority: medium-high.

What to port: Hermes discipline around compact memory and maintenance, adapted to existing learning cards.

Existing foothold:

- `skills/learning_card_store.py`
- `schemas/learning_card.py`
- `analysis/context_builder.py`
- `Handlers._record_learning_card_feedback_targeted()`
- `tests/test_learning_card_feedback.py`

Recommended design:

- Continue recording retrieval when cards are injected.
- Broaden explicit post-run attribution beyond the current validation-tag feedback:
  - helpful when the card was cited and contributed to a correct validator block, better calibration, correct evidence recall, or a monthly-valid decision
  - harmful when the card contributed to a stale idea, unsupported proposal, validator failure, or later negative monthly outcome
  - neutral/unknown by default
- Supersede older cards when monthly outcomes contradict them.
- Create high-impact cards from monthly outcomes and rollbacks automatically.
- Penalize cards whose confidence is high but subsequent outcomes contradict them.

Acceptance criteria:

- Repeatedly harmful cards fall out of retrieval.
- Superseded cards stay auditable but are not injected.
- Top retrieved cards have clear provenance and recent outcome support.

### 9. Record Discarded Experiments As First-Class Learning

Priority: medium.

What to port: AutoAgent's idea that discarded runs still teach the system.

Why it matters: In trading research, knowing what failed is often as valuable as knowing what worked. Without a durable record, the system can repeatedly rediscover the same weak edge, overfit the same artifact, or re-propose the same brittle threshold change.

Recommended design:

- Add a `discarded_harness_experiments.jsonl` or integrate into the harness learning ledger.
- Add structured fields:
  - experiment id
  - hypothesis
  - changed component
  - benchmark score delta
  - governance regressions
  - discard reason
  - anti-overfitting assessment
  - future warning tags
- Convert recurring discard themes into learning cards or playbooks only when supported by multiple cases.

Acceptance criteria:

- Future benchmark compilation can sample discarded experiments as negative examples.
- Context retrieval can warn the model away from repeated failed ideas without overloading normal prompts.

### 10. Finish Legacy Authority Cleanup Before Increasing Autonomy

Priority: prerequisite.

What to do: execute the cleanup direction already documented in `docs/2026-05-12-monthly-learning-loop-cleanup-plan.md`.

Why it matters: Hermes and AutoAgent both increase the system's ability to learn and modify itself. That only helps if the authority structure is clean. If legacy WFO/autonomous/search pathways still appear authoritative, generated learning may reinforce the wrong decision pathway.

Acceptance criteria:

- Monthly validation is the single authority for material strategy/config changes.
- Legacy WFO outputs are historical/contextual unless explicitly retained as sensors.
- Approval infrastructure is not gated by obsolete autonomous flags.
- ContextBuilder no longer gives deprecated paths undue priority.

## Proposed Target Learning Architecture

The target architecture should separate five memory and learning layers:

1. Policy memory: human-edited, versioned, stable. Examples: permission gates, trading rules, agent behavior constraints. Agents may read but not autonomously edit.

2. Evidence memory: structured outcomes, ledgers, priors, validation logs, monthly artifacts, replay results, approval decisions. This is the source of truth for learning.

3. Advisory memory: learning cards and generated playbooks. These are generated from evidence, retrieved into prompts, and demoted or superseded when outcomes contradict them.

4. Raw recall: run folders, indexed artifacts, session summaries, response traces, validator notes, and searchable FTS. This allows the system to recover details without permanently injecting everything.

5. Evaluation corpus: benchmark cases derived from failures, blocked proposals, negative outcomes, calibration misses, transfer failures, parser failures, and high-value successes. This is what makes harness improvement measurable.

Flow:

```text
Bot events and artifacts
  -> daily/weekly/monthly prompt packages
  -> agent runtime
  -> parsed proposals, predictions, reports
  -> validators and approval gates
  -> outcomes, ledgers, priors, run index
  -> learning reviewer
  -> learning cards, playbooks, benchmark cases
  -> context retrieval and harness benchmark
  -> improved prompts, retrieval, validators, provider routing
  -> next run
```

This architecture uses Hermes for memory extraction and retrieval, AutoAgent for measured harness improvement, and the existing monthly evidence loop for trading authority.

## Concrete Harness Benchmark Metrics

The benchmark should not optimize for general report quality alone. It should optimize for decision quality.

Primary metrics:

- Bad-proposal block accuracy: did the harness block suggestions that should be blocked?
- Good-candidate preservation: did the harness avoid blocking candidates that met evidence and risk gates?
- Repeat-negative avoidance: did it avoid proposing ideas already rejected or shown harmful?
- Evidence citation completeness: did it cite the right artifacts, ledgers, and outcomes?
- Monthly-authority compliance: did it route material changes through monthly validation and approval?
- Parse and schema success: did structured outputs validate without manual repair?
- Calibration: did confidence match historical hit rates and outcome priors?
- Risk realism: did the proposal account for drawdown, cost, slippage, outlier concentration, and trade count?
- Contradiction handling: did it notice when learning cards/playbooks were superseded by newer evidence?

Secondary metrics:

- Token use.
- Runtime latency.
- Provider cost.
- Report compactness.
- Number of repair attempts.

Hard-fail metrics:

- Approval bypass.
- Direct live trading command.
- Material strategy change without required evidence.
- Hallucinated artifact path used as evidence.
- Policy memory edit by autonomous reviewer.
- Any candidate accepted despite deterministic gate failure.

## Implementation Roadmap

### Phase 0: Authority And Inventory Cleanup

Objective: make sure the learning system has one source of authority before adding more autonomy.

Tasks:

- Complete the monthly-loop cleanup already planned in docs.
- Mark legacy WFO/search/autonomous paths as historical or sensor-only unless intentionally retained.
- Inventory current generated playbooks, learning cards, benchmark cases, and outcome priors.
- Add missing provenance fields where necessary.

Exit criteria:

- Monthly validation remains authoritative.
- Context injection does not prioritize deprecated pathways.
- Existing memory artifacts can be audited by source and date.

### Phase 1: Executable Harness Benchmark

Objective: make AutoAgent-style harness improvement measurable.

Tasks:

- Extend `BenchmarkCase` into executable cases.
- Implement baseline vs candidate runs through prompt assembly, retrieval, parsing, and validators.
- Add a results ledger with keep/discard decisions.
- Add a small initial benchmark corpus from known validation blocks and negative outcomes.

Exit criteria:

- At least one harness variant can be evaluated against baseline.
- The runner can reject a variant that improves a minor metric but violates governance.
- Test coverage proves the scorer catches repeated bad suggestions and approval bypass.

### Phase 2: Post-Run Learning Reviewer

Objective: extract durable learning from actual runs.

Tasks:

- Add `LearningReviewOrchestrator`.
- Add trigger logic after selected agent runs.
- Use `LearningWriteCoordinator` for writes.
- Allow writes only to learning cards, generated playbooks, benchmark cases, correction patterns, and quarantine metadata.

Exit criteria:

- Reviewer creates no learning without artifact evidence.
- Idempotent review of the same run does not duplicate records.
- Reviewer cannot edit policy files or trading logic.

### Phase 3: Focused Evidence Recall

Objective: improve context quality through better historical recall.

Tasks:

- Add run recall summarization over `RunIndex` matches.
- Include outcome and approval status in recall cards.
- Budget recall separately from learning cards and generated playbooks.
- Add suppression for stale or superseded recall.

Exit criteria:

- Similar past runs injected into prompts are more informative than snippets.
- Recall entries include artifact paths and outcome status.
- Retrieval has tests for workflow, bot, regime, and category filters.

### Phase 4: Playbook Guard And Curator

Objective: make generated procedural memory safe and useful over time.

Tasks:

- Expand the existing playbook safety check into `GeneratedPlaybookGuard`.
- Wire `record_usage()` when playbooks are injected into prompts.
- Wire `record_outcome()` from downstream validation/monthly outcomes where attribution is defensible.
- Add weekly or threshold-based curator for consolidation, pinning, patching, and recoverable archive.
- Preserve the existing quarantine/retirement behavior for ineffective playbooks.

Exit criteria:

- Redundant playbooks are consolidated.
- Harmful or stale playbooks stop being injected.
- Human-pinned playbooks are protected.

### Phase 5: Monthly Model Review And Repair

Objective: strengthen the most important decision workflow.

Tasks:

- Wire model-review invocation into monthly validation after deterministic readiness gates.
- Invoke repair prompt when artifacts are incomplete.
- Validate model-review output before approval packet generation.
- Add monthly review cases to the harness benchmark.

Exit criteria:

- Approval packets cite deterministic artifacts and model-review interpretation.
- Missing artifacts route to repair, not speculation.
- Prompt changes to monthly review are benchmarked before adoption.

## Governance And Safety Constraints

These constraints should be non-negotiable:

- Generated learning cannot modify `memory/policies`.
- Generated learning is advisory context, never hidden policy.
- The monthly validation loop remains authoritative for material strategy/config changes.
- Direct bot commands remain out of scope.
- Approval and double-approval gates cannot be weakened by harness experiments.
- Benchmark scoring functions and objective weights are human-owned.
- A harness variant cannot be kept if it improves score by overfitting one case while worsening general decision quality.
- Generated playbooks and learning cards need provenance, dates, and supersession.
- Background reviewers must be idempotent and auditable.
- Cost and latency are secondary to expected return, risk control, and governance correctness.

## Low-Value Or Risky Ports

Do not port these wholesale:

- Hermes' general user-persona memory beyond lightweight operator preferences. The trading system needs evidence memory more than broad personal memory.

- Hermes' full communication/gateway stack. `trading_assistant` already has Telegram, Discord, email, and orchestrator components.

- Hermes' unrestricted general skill creation. Trading playbooks should be narrower, evidence-backed, guarded, and tied to outcomes.

- AutoAgent's single-file generic harness pattern. This repo already has a modular domain architecture; collapsing it would lose useful structure.

- An infinite self-improvement loop against live trading logic. Harness experiments should run offline and should not directly alter trading strategies.

- Score-only optimization without governance hard fails. A benchmark score that allows approval bypass or hallucinated evidence would be worse than no benchmark.

## Suggested Near-Term PR Sequence

1. PR: executable harness benchmark skeleton.
   - Replace synthetic variant scoring in `HarnessEvalRunner` with a first real baseline-vs-candidate evaluator.
   - Add 5 to 10 benchmark cases from validation blocks and negative outcomes.

2. PR: harness program and experiment ledger.
   - Add a human-owned harness objective document.
   - Add keep/discard logging and anti-overfitting fields.

3. PR: post-run learning reviewer.
   - Add an asynchronous reviewer with strict write boundaries.
   - Create/update learning cards and benchmark cases from run artifacts.

4. PR: focused run recall.
   - Add summarized recall cards over `RunIndex` matches.
   - Inject with provenance and outcome status.

5. PR: generated playbook guard and curator.
   - Harden the existing safety checks, wire usage/outcome attribution, and add archive/consolidation/pinning.

6. PR: monthly model-review wiring.
   - Create or restore the monthly review/repair prompt assembler, then invoke monthly model review and repair as first-class monthly steps.
   - Add benchmark cases for monthly approval packet quality.

## Expected Impact On Trading Performance

The expected return benefit is indirect but material. These changes do not make a specific trading strategy better by themselves. They improve the system that proposes, filters, validates, and learns from strategy changes.

Likely benefits:

- Fewer repeated bad suggestions because negative outcomes and rejected ideas become benchmark cases and retrieval warnings.
- Better proposal quality because the harness learns which evidence, regimes, and priors matter for each workflow.
- Better calibration because forecasts, confidence, and category hit rates are fed back into prompts and evaluation.
- Better use of monthly validation because material changes stay tied to replay, parity, coverage, and approval packets.
- Faster learning from failures because background review turns failed validations into durable benchmark cases and memory updates.
- Lower context bloat because generated memory is ranked, curated, superseded, and archived.
- More reliable provider routing because model/provider choices are judged by decision quality, not just availability or cost.

The most important caveat: self-improvement only helps if the evaluation signal is strong. The AutoAgent loop should not be activated aggressively until executable benchmarks and governance hard-fails are in place.

## Bottom Line

Hermes Agent should influence `trading_assistant`'s memory extraction, procedural playbooks, recall, safety scanning, and curation. AutoAgent should influence its harness experimentation, benchmark scoring, keep/discard discipline, and human-owned improvement objective.

The best architecture is a hybrid:

- Hermes-style learning reviewer and guarded procedural memory.
- AutoAgent-style measured harness evolution.
- Existing monthly evidence/replay validation as the trading authority.

That combination directly serves the repo's goal: a local trading analysis orchestrator that becomes more evidence-aware over time, proposes fewer weak ideas, identifies more meaningful high-value improvements, and routes material decisions through the strongest available validation before risking capital.
