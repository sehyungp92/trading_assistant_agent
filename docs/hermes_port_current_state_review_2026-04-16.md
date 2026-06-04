# Hermes Port Current-State Review

Date: 2026-04-16

## Executive Verdict

The current repo does **not** yet represent the optimal implementation and integration of the best Hermes-inspired elements for improving trading performance over time.

It has made real progress since `docs/hermes_port.md`:

- prompt delivery is now materially stronger
- session-store passthrough is live in the main assembler paths
- a learning-card primitive exists
- a searchable run index exists
- a grouped learning-write coordinator exists
- workflow-aware context prioritization exists

However, the highest-value Hermes import was never "have more learning files." It was "turn learning artifacts into an active memory loop that changes future decisions." On that standard, the current implementation is still incomplete.

The repo now has good **memory infrastructure pieces**, but several of the highest-EV ones are still not fully live:

- learning cards are retrieved, but there is no production card reflector/sync pipeline populating them from the full learning system
- retrieval is still mostly workflow-aware, not genuinely bot/regime/category/query-aware
- run search exists, but the live app does not instantiate `RunIndex`
- write coordination exists, but production learning writes still bypass it
- provider selection still learns from failures and cooldowns, not from downstream trading outcome quality

The result is a system that already has strong domain-specific meta-learning, but still does **not** fully leverage Hermes's strongest idea: memory orchestration that continuously improves what the next run sees.

## Scope and Method

This review compared:

- the implementation status of the recommendations in `docs/hermes_port.md`
- the current `trading_assistant` codebase
- the relevant Hermes reference patterns in `_references/hermes-agent/agent/memory_manager.py`, `_references/hermes-agent/agent/insights.py`, `_references/hermes-agent/agent/smart_model_routing.py`, and `_references/hermes-agent/agent/trajectory.py`

The goal was not to re-evaluate whether Hermes is "good" in the abstract. The goal was to judge whether the repo has ported the **right** Hermes ideas in the **right** way to improve:

- suggestion quality
- calibration
- evidence-grounded recommendations
- adaptation from outcomes/corrections
- expected trading returns over time

## Important Existing Strengths

This review is specifically about the **newer Hermes-style orchestration layer**. It should not be read as saying the repo lacks live reflection or learning today.

Several reflective loops are already active in production code:

- `analysis/context_builder.py` already injects a broad synthesized learning set, including `forecast_meta_analysis`, `category_scorecard`, `regime_stratified_scores`, `prediction_accuracy_by_metric`, `hypothesis_track_record`, `transfer_track_record`, `validation_patterns`, `outcome_reasonings`, `recalibrations`, `self_assessment`, `convergence_report`, `cycle_effectiveness_trend`, `suggestion_quality_trend`, `last_week_synthesis`, `spurious_outcomes`, `search_reports`, `backtest_reliability`, `portfolio_outcomes`, `portfolio_rolling_metrics`, `macro_regime_context`, `regime_config_history`, and `session_history`
- `analysis/response_validator.py` already uses scorecards, forecast calibration, macro regime, and causal recalibrations to adjust confidence and block weak proposals
- `orchestrator/handlers.py` already writes validation feedback to `validation_log.jsonl`, and `ContextBuilder.load_validation_patterns()` turns that back into future prompt context
- `skills/retrospective_builder.py` already persists retrospective synthesis, and the weekly handler already uses it to recalibrate suggestion categories and write learning-ledger lessons
- `orchestrator/app.py` already runs outcome reasoning and persists `outcome_reasonings.jsonl`, `spurious_outcomes.jsonl`, `recalibrations.jsonl`, and transfer proposals

The main gap is therefore **not** "there is no learning loop." The main gap is that the newer Hermes-port pieces do not yet orchestrate these existing signals as effectively as they could.

## What Has Changed Since `hermes_port.md`

Several findings in the earlier report are now outdated.

### 1. Prompt-delivery wiring is no longer the main gap

`orchestrator/invocation_builder.py` now uses `InvocationBuilder.build_full_prompt()` to merge:

- `task_prompt`
- `instructions`
- summarized `corrections`
- `skill_context`
- injected `<learning-memory>` text from `PromptPackage.metadata`
- a manifest of available `package.data` files

`orchestrator/agent_runner.py` also writes:

- `instructions.md`
- `system_prompt.md`
- `corrections.json`
- `skill_context.md`
- all `package.data` JSON files

This is a meaningful fix. The earlier report's biggest prompt-path criticism is no longer accurate.

### 2. Session-store passthrough is now part of the normal assembly path

The main handlers now pass `session_store=self._agent_runner.session_store` into daily, weekly, WFO, discovery, outcome-reasoning, and triage assembly paths.

That means the earlier concern that session history was assembled but not normally used is also outdated.

### 3. The repo now contains Hermes-inspired primitives that did not exist before

Implemented since the earlier report:

- `schemas/learning_card.py`
- `skills/learning_card_store.py`
- `skills/learning_write_coordinator.py`
- `orchestrator/run_index.py`
- learning-card loading in `analysis/context_builder.py`

These are real improvements. The issue is not that nothing was ported. The issue is that some of the most valuable pieces are still only partially integrated into production learning flow.

## Current Assessment by Original Recommendation

## 1. Fix prompt delivery

### Status

Implemented, and implemented well enough to count as a real upgrade.

### Evidence

- `orchestrator/invocation_builder.py`
- `orchestrator/agent_runner.py`

### Assessment

This was the right move, and it appears to have been executed successfully.

Compared with Hermes's `MemoryManager.build_system_prompt()` plus fenced memory injection (`_references/hermes-agent/agent/memory_manager.py`), the current prompt path now has the right shape:

- structured system prompt
- explicit injected learning context
- visible separation between instructions and recalled memory
- file manifest telling the runtime what to read

### Remaining issue

The injected learning-card block is **not part of the main context budget**. `analysis/context_builder.py` budgets `package.data`, but `InvocationBuilder.build_full_prompt()` appends `_learning_cards_text` afterward. That means the highest-priority memory can still grow outside the same budget discipline.

This is not severe enough to reverse the prompt-delivery conclusion, but it is a remaining optimization target.

### Verdict

The earlier deferral logic around prompt delivery should be considered complete. This is no longer the main bottleneck.

## 2. Add a Hermes-style learning memory manager

### Status

Not implemented as a real manager. A partial substitute exists inside `analysis/context_builder.py`.

### Evidence

- `analysis/context_builder.py`
- `skills/learning_card_store.py`
- `_references/hermes-agent/agent/memory_manager.py`

### What exists now

`ContextBuilder.base_package()` already does several good things:

- workflow-aware priority ordering via `_WORKFLOW_PRIORITIES`
- adaptive item-budgeting
- token-aware budgeting support when `context_budget_tokens > 0`
- learning-card retrieval and injection
- broad synthesized learning-context loading across validation, calibration, outcomes, transfer history, convergence, weekly synthesis, portfolio metrics, and macro regime state

This is a meaningful step toward Hermes-style orchestration.

### Why it is still not optimal

The current design is still closer to "rich static context builder plus extra ranked cards" than to a real learning-memory manager.

The main limitations are:

1. Retrieval is not query-aware enough.
   `ContextBuilder.base_package()` currently retrieves cards with:
   `card_store.ranked_for_prompt(limit=10, bot_id="", workflow=agent_type)`.
   That means the live card query is workflow-aware, but not bot-aware, regime-aware, category-aware, or triage-aware.

2. The broader learning context remains mostly global.
   `ContextBuilder` has helper methods like `load_corrections(bot_id)` and `load_pattern_library(bot_id)`, but `base_package()` calls the unscoped versions. For single-bot workflows such as WFO or triage, this leaves value on the table and risks noise.

   This is not equally problematic for every workflow. Global/cross-bot context is often appropriate for weekly, discovery, and portfolio-oriented analysis. The scoping gap is most important for single-bot or tightly targeted workflows.

3. Token-aware budgeting exists, but appears unused in production.
   The live assembler paths call `base_package()` without `context_budget_tokens`. In practice, the repo still runs on the older item-budget default path except in tests.

4. Learning cards are additive rather than orchestrating the whole memory layer.
   Cards are appended as a fenced memory block, but the main learning context is still mostly assembled through many direct JSONL loaders.

### Hermes comparison

Hermes's `MemoryManager` is valuable not because it is generic, but because it makes retrieval a first-class lifecycle step:

- prefetch before turn
- sync after turn
- fenced recalled context
- one integration point for memory behavior

`trading_assistant` has not yet reached that integration level.

### Verdict

The original decision to defer a full `LearningMemoryManager` was understandable at the time, but it is **no longer the optimal decision**.

The right move now is **not** a large generic framework. The right move is a thin, trading-specific manager that:

- constructs workflow queries from bot_ids, categories, regime context, and task type
- ranks cards and selected raw evidence together
- applies one token budget across both card text and raw context
- scopes corrections/patterns/reasonings by workflow and bot where appropriate

This should move from deferred to active implementation.

## 3. Add reflective synthesis into learning cards

### Status

Only partially implemented.

### Evidence

- `schemas/learning_card.py`
- `skills/learning_card_store.py`
- `analysis/context_builder.py`
- `orchestrator/app.py`

### What exists now

The repo has a solid primitive:

- `LearningCard`
- `LearningCardIndex`
- `LearningCardStore`
- factory methods for several source artifact types
- retrieval-count persistence

This is a good abstraction.

### Why it is still not optimal

The card layer is still not acting like a production reflection loop.

Observed gaps:

1. No live card-specific reflector/sync pipeline.
   Search of the production code paths found no live use of:
   - `LearningCardStore.ingest_from_existing()`
   - `LearningCardStore.add_card()`

   The only production use found for `LearningCardStore` is prompt-time retrieval
   from `ContextBuilder.base_package()`.

2. The repo snapshot has no active card corpus.
   As of this review:
   - `memory/findings/learning_cards.jsonl` does not exist

3. Ingestion coverage is too narrow.
   `ingest_from_existing()` only scans:
   - `corrections.jsonl`
   - `outcomes.jsonl`
   - `discoveries.jsonl`

   It does not synthesize cards from high-value artifacts the repo already generates, including:

   - `outcome_reasonings.jsonl`
   - `recalibrations.jsonl`
   - `spurious_outcomes.jsonl`
   - `transfer_outcomes.jsonl`
   - hypothesis lifecycle state
   - validator blocks/patterns
   - retrospective synthesis
   - run-level replay evidence

   There is also a nuance here: helper factories such as `card_from_hypothesis()` and `card_from_validator_block()` already exist, but the default ingestion path does not use them.

4. Card scoring is still too naive for the intended role.
   `LearningCard.relevance_score()` is a clean baseline, but it does not yet incorporate several trading-specific trust signals the repo already has:
   - measurement quality
   - significance score
   - concurrent change contamination
   - regime match
   - transfer validation history
   - validator recurrence

5. Retrieval feedback is one-sided.
   `record_retrieval()` is called.
   `record_feedback()` does not appear wired into live flows.
   So the helpful/harmful component of ranking never matures in production.

### Hermes comparison

Hermes's memory value comes partly from prefetch and sync, but also from the fact that memory is continuously refreshed after the model acts. The current card layer is still mostly a storage abstraction waiting for a real reflector.

### Verdict

The original decision to defer a `LearningReflector` is **no longer optimal**.

This is now one of the highest-value missing pieces, because the current repo already generates high-quality reflective artifacts through:

- outcome reasoning
- recalibration
- spurious-outcome detection
- cross-bot transfer measurement
- weekly synthesis
- validator blocks

Without a live reflector, the system is producing many lessons but not converting them into a stable ranked memory layer.

## 4. Add searchable session and trajectory storage

### Status

Partially implemented, but still far from optimal.

### Evidence

- `orchestrator/session_store.py`
- `orchestrator/run_index.py`
- `orchestrator/agent_runner.py`
- `orchestrator/app.py`
- `_references/hermes-agent/agent/trajectory.py`
- `_references/hermes-agent/agent/insights.py`

### What exists now

The repo already has:

- live `SessionStore` persistence per invocation
- run folders with prompts/data/response artifacts
- a `RunIndex` implementation backed by SQLite FTS5
- `TaskRegistry` persistence of `context_files`, `run_folder`, status, and summaries
- `StreamParser` capture of session ids, cost, first-output timing, tool-call counts, and streaming progress previews

This is a good foundation.

### Why it is still not optimal

1. `RunIndex` is not wired into the live app.
   `AgentRunner` supports a `run_index` dependency, but `create_app()` does not instantiate or pass one.

2. There is no live run index database in the repo snapshot.
   As of this review:
   - `data/run_index.db` does not exist

3. Even if enabled, current indexing would still be underpowered.
   `AgentRunner._index_run()` currently passes:
   - provider
   - model
   - success
   - duration_ms
   - cost_usd

   But it does **not** pass:
   - bot_ids
   - date
   - richer metadata

   `RunIndex` supports those fields, but the live integration does not populate them.

4. Reindex assumptions do not match live run output.
   `RunIndex.reindex_from_directory()` looks for `metadata.json`, but `AgentRunner._write_run_files()` does not write that file.

5. `SessionStore` is still summary-only.
   It stores:
   - prompt hash
   - response summary
   - token usage
   - duration
   - provider/runtime/model metadata

   It does not store:
   - searchable full prompt bodies
   - searchable reasoning traces
   - trajectory-style conversation structure

6. The search layer is not yet used by production features.
   Search of the live app/orchestrator code found no production caller of:
   - `RunIndex.search()`
   - `RunIndex.get_recent_runs()`

### Hermes comparison

Hermes persists trajectories and uses session analytics to learn from how the agent worked, not just what the final answer was. `trading_assistant` is not there yet.

### Verdict

The earlier choice to defer a full replay harness still looks right.

But the current level of deferral around searchable replay infrastructure is **too conservative**.

The right split is:

- keep full replay/eval harness deferred
- stop deferring the prerequisite data plane

That means:

- wire `RunIndex` into `create_app()`
- populate bot/date metadata at index time
- write a small `metadata.json` alongside run artifacts
- backfill existing runs

This is a clear, practical bridge from "we have run folders" to "we can actually learn from them."

## 5. Add learned provider/model routing

### Status

Still deferred in practice.

### Evidence

- `orchestrator/agent_preferences.py`
- `orchestrator/agent_runner.py`
- `orchestrator/cost_tracker.py`
- `_references/hermes-agent/agent/smart_model_routing.py`
- `_references/hermes-agent/agent/insights.py`

### What exists now

The current provider layer is good operationally:

- default provider selection
- per-workflow overrides
- fallback chains
- provider availability checks
- cooldowns after failure
- cost logging

This is good runtime hygiene.

### Why it is still not optimal

The current selection logic still does **not** learn from downstream outcome quality.

There is no live component that scores provider/model routes by:

- validator pass rate
- parsing reliability
- latency
- cost per successful run
- downstream measured outcome quality
- forecast calibration quality

So the system can fall back away from failure, but it cannot learn which route actually produces better trading decisions.

### Is the original deferral still right?

Partially.

It is still correct to defer:

- aggressive online bandits
- high-variance route changes with low sample sizes
- any routing policy that optimizes only cost or speed

It is **not** optimal to keep deferring a basic provider-performance tracker altogether.

The repo already captures enough telemetry to start in shadow mode:

- run success/failure
- duration
- cost
- provider/model metadata
- downstream validated suggestions
- later measured outcomes

The right next step is a conservative offline scorecard, not a live bandit.

### Verdict

`ProviderPerformanceTracker` should move from fully deferred to **shadow-mode implementation**.

It should begin as reporting only, then graduate to low-risk ranking inputs once sample-size gates are met.

## 6. Unify learning writes through a memory bus / coordinator

### Status

Infrastructure implemented, production integration missing.

### Evidence

- `skills/learning_write_coordinator.py`
- `orchestrator/app.py`
- `orchestrator/handlers.py`

### What exists now

`LearningWriteCoordinator` is a good design:

- grouped writes
- provenance via `write_group_id`
- per-op success/failure tracking
- idempotency hooks
- event broadcast on completion

This is exactly the kind of infrastructure Hermes-style memory sync benefits from.

### Why it is still not optimal

Production learning writes still happen through scattered direct file appends and callback sequences.

Those writes are not useless or disconnected. They already power live downstream features such as:

- `validation_patterns`
- recalibration-aware confidence adjustment
- transfer track records
- retrospective synthesis
- convergence metrics

The issue is coordination and unified provenance, not the absence of writeback.

The clearest example is the outcome-reasoning flow in `orchestrator/app.py`, which writes:

- `outcome_reasonings.jsonl`
- `spurious_outcomes.jsonl`
- `recalibrations.jsonl`
- transfer proposals through a separate builder

These are high-value reflective writes, but they are not routed through the coordinator.

The repo snapshot also has no sign that this path is active in practice:

- `memory/findings/write_log.jsonl` does not exist

### Verdict

The original decision to defer a full event bus is still reasonable.

But the current production non-use of `LearningWriteCoordinator` is **not** optimal.

The right near-term step is not a 13-event generic bus. It is to route the highest-value write clusters through the coordinator now:

- outcome reasoning
- weekly synthesis/recalibration
- discovery persistence
- validator-block persistence
- card refresh triggers

## What Already Exists and Should Be Preserved

One of the most important conclusions of this review is that `trading_assistant` already has a stronger domain-specific learning substrate than Hermes in several areas.

Do **not** replace these with generic Hermes abstractions:

- `analysis/outcome_reasoning_prompt.py`
- `analysis/response_validator.py`
- `skills/prediction_tracker.py`
- `skills/suggestion_scorer.py`
- `skills/convergence_tracker.py`
- `skills/learning_ledger.py`
- `skills/hypothesis_library.py`
- `skills/transfer_proposal_builder.py`
- the broad synthesis already performed in `analysis/context_builder.py`

The correct integration strategy remains:

- preserve the current trading-specific learning logic
- improve the orchestration, retrieval, and writeback around it

In other words: Hermes should upgrade the memory plumbing, not replace the trading brain.

## Deferred-Item Review

## Still correct to defer

### 1. Full RL / Tinker-Atropos training

This still looks like the right defer decision.

Reasons:

- the system uses external closed runtimes
- reward is delayed and confounded
- current replay infrastructure is immature
- direct RL before strong replay/eval would optimize noise

The prerequisite remains the same: build better replay data and route-quality evaluation first.

### 2. External/cloud memory providers

Still right to defer.

Reasons:

- the current bottleneck is not storage backend sophistication
- local JSONL/SQLite is sufficient for the next stage
- external memory adds failure modes without solving retrieval quality

### 3. Full context-compressor port

Still mostly right to defer.

Reasons:

- the architecture is stateless, per-task CLI invocation
- the main missing value is better retrieval, not yet aggressive compression
- run-summary compaction may help later, but full Hermes compressor is not the next best use of effort

## No longer optimal to defer

### 1. LearningMemoryManager

Deferring a full generic manager was reasonable.
Deferring a thin trading-specific manager is now holding back value.

### 2. LearningReflector

This should no longer be deferred.
Without it, the card layer stays sparse and mostly symbolic.

### 3. Workflow query construction

This should no longer be deferred.
Current global/workflow-only retrieval is too blunt for the repo's actual learning objectives.

### 4. ProviderPerformanceTracker

Do not jump to online routing.
But do start a shadow tracker now.

### 5. LearningWriteCoordinator adoption

The full learning-event bus can remain deferred.
Using the coordinator in the highest-value flows should not remain deferred.

## Highest-EV Implementation Order

The next steps below are ordered by expected contribution to future trading-decision quality, not by architectural neatness.

## Priority 1: Make the learning-card layer real

Implement a `LearningReflector` or equivalent sync path that creates/updates cards from:

- outcome reasonings
- recalibrations
- spurious outcomes
- transfer outcomes
- validator patterns/blocks
- weekly retrospective synthesis
- selected hypothesis outcomes
- discoveries

Why this is first:

- the card abstraction already exists
- the repo already generates strong reflective evidence
- this is the shortest path from "lessons exist" to "lessons are retrieved next time"

## Priority 2: Replace flat card retrieval with query-aware retrieval

Introduce a thin query object or manager that uses:

- workflow
- bot_ids
- triage categories
- current regime / macro context
- time horizon
- artifact type budgets

Also scope raw learning loaders the same way where possible.

Why this is second:

- once cards exist, retrieval quality becomes the next bottleneck
- improving relevance directly improves prompt quality and suggestion quality

## Priority 3: Wire `RunIndex` into production and enrich metadata

Do all of the following together:

- instantiate `RunIndex` in `create_app()`
- pass it into `AgentRunner`
- write `metadata.json` for each run
- populate bot_ids/date/metadata at index time
- backfill historical run folders

Why this matters:

- it unlocks searchable replay and reflection
- it supports future reflector logic
- it supports future provider scorecards

## Priority 4: Route the major reflective write clusters through `LearningWriteCoordinator`

Start with:

- outcome reasoning outputs
- recalibration outputs
- spurious outcome logs
- transfer proposal generation
- weekly synthesis-derived recalibration

Why this matters:

- provenance becomes coherent
- future reflection/card-refresh hooks have one stable integration point
- partial-write inconsistency risk drops

## Priority 5: Implement shadow-mode provider performance tracking

Start with reporting only. Score routes on:

- invocation success rate
- parse success rate
- validator block rate
- latency
- cost
- measured positive-outcome rate for implemented suggestions originating from that route

Do not automatically reroute until sample-size thresholds are met.

Why this matters:

- there is now enough telemetry to begin learning
- aggressive route changes are risky, but not measuring route quality is wasted information

## Priority 6: Add retrieval feedback to cards

Use `_learning_card_ids` plus downstream signals to update helpful/harmful counts.

Candidate signals:

- validator blocked repeated bad pattern after card retrieval -> harmful
- validated recommendation aligned with retrieved card and later positive measured outcome -> helpful
- repeated contradiction between retrieved card and measured outcome -> harmful or supersede

Why this matters:

- this is what turns ranking from static heuristics into a true adaptive memory layer

## Priority 7: Activate token-aware budget policy in production

Once retrieval is query-aware, make `context_budget_tokens` part of live workflows so memory and raw evidence compete under one explicit budget.

This is less urgent than the steps above, but it becomes more important once the memory layer grows.

## Suggested Success Criteria

The following metrics would show whether the Hermes-inspired integration is actually improving trading_assistant's end goal:

- higher positive-outcome rate for implemented suggestions
- lower repeat rate of previously blocked or disproven suggestion categories
- improved forecast calibration and lower directional bias
- higher transfer success rate for cross-bot pattern proposals
- lower validator block rate for agent-generated suggestions
- lower cost per validated suggestion
- lower cost per positive measured outcome
- higher retrieval helpful-rate for learning cards
- improved replay search usefulness for weekly/reflection workflows

## Bottom Line

The current repo has gone beyond the state described in `docs/hermes_port.md`, and that progress is real.

But it is still **not** the optimal integration of Hermes's best elements.

The repo has already fixed the prompt path and added strong memory primitives. The remaining gap is that those primitives are not yet fully connected into a production learning loop.

The most important conclusion from this review is:

- keep deferring full RL
- keep deferring external memory backends
- stop deferring the pieces that turn existing reflective artifacts into active future guidance

Concretely, the next high-value work is:

1. productionize reflective card creation
2. make retrieval genuinely query-aware
3. activate searchable run replay
4. unify reflective writes
5. start shadow provider-performance learning

That path is the most evidence-grounded way to improve trading performance over time using the strongest transferable ideas from Hermes.

---

## Implementation Notes (2026-04-17)

The four highest-value priorities from this review were addressed. A post-implementation review identified and fixed three additional robustness issues. Total: 3373 tests passing (33 new).

### What Was Implemented

#### Priority 1: Learning-card layer activated (Phase A)

The learning-card pipeline is now live. `LearningCardStore.ingest_from_existing()` was expanded from 3 JSONL sources to 8:

| Source File | Card Type | Factory Method |
|---|---|---|
| `corrections.jsonl` | CORRECTION | `card_from_correction()` (existing) |
| `outcomes.jsonl` | OUTCOME | `card_from_outcome()` (existing) |
| `discoveries.jsonl` | DISCOVERY | `card_from_discovery()` (existing) |
| `outcome_reasonings.jsonl` | SYNTHESIS | `card_from_outcome_reasoning()` (new) |
| `recalibrations.jsonl` | RECALIBRATION | `card_from_recalibration()` (new) |
| `spurious_outcomes.jsonl` | OUTCOME | `card_from_spurious_outcome()` (new) |
| `hypotheses.jsonl` | HYPOTHESIS | `card_from_hypothesis()` (existing, newly wired) |
| `validation_log.jsonl` | VALIDATOR_BLOCK | `card_from_validator_block()` (existing, newly wired) |

Card ID collision between `outcomes.jsonl` and `spurious_outcomes.jsonl` (both `CardType.OUTCOME`) is handled by prefixing spurious source_ids with `spurious:`.

Ingestion is scheduled at two points in `orchestrator/app.py`:
- End of `_measure_outcomes()` (after outcome reasoning writes complete)
- End of `_consolidate_memory()` (after weekly consolidation)

Both are best-effort with independent try/except blocks.

Note: The review recommended `transfer_outcomes.jsonl`, `retrospective synthesis`, and `run-level replay evidence` as additional ingestion sources. These were not added because:
- `transfer_outcomes.jsonl` is not a standalone file; transfer outcomes are measured inline by `TransferProposalBuilder` and stored within its own JSONL
- Retrospective synthesis is unstructured markdown, not JSONL; card creation from it would require parsing heuristics that risk low-quality cards
- Run-level replay evidence requires the RunIndex search infrastructure to be mature first

The review also noted card scoring does not yet incorporate measurement quality, significance score, concurrent change contamination, regime match, transfer validation history, or validator recurrence. This was not addressed because it requires a larger redesign of `LearningCard.relevance_score()` with access to runtime context that the static scoring method does not currently have. It remains a valid future improvement.

#### Priority 2: Bot-aware card retrieval (Phase B)

`ContextBuilder.base_package()` now accepts a `bot_id: str = ""` parameter, passed through to `LearningCardStore.ranked_for_prompt()`. This is backward-compatible — all existing callers that omit it get the same empty-string default.

Two assemblers now pass bot_id:
- `DailyPromptAssembler`: passes `self.bots[0]` when exactly one bot, else `""`
- `WFOPromptAssembler`: passes `self.bot_id`

Four assemblers correctly remain `bot_id=""`:
- **Weekly**: cross-bot workflow by design
- **Discovery**: cross-bot pattern detection
- **Outcome Reasoning**: cross-bot causal analysis
- **Triage**: bot-neutral bug fixing (no bot_id concept in its constructor)

A pre-existing bug was also fixed: `context_builder.py` line 1594 used `self._findings_dir` which does not exist as an attribute (the class uses `self._memory_dir / "findings"` everywhere else). The `try/except Exception` silently swallowed the `AttributeError`, making the entire learning card retrieval permanently dormant. Fixed by changing to `self._memory_dir / "findings"`.

The review recommended a broader query-aware retrieval system incorporating regime context, triage categories, time horizon, and artifact type budgets. This was not implemented because it requires architectural changes beyond parameter passthrough — specifically, a query object that carries runtime regime state and category context into the card ranking function. The current bot_id fix delivers the highest-value scoping improvement (single-bot workflows get bot-relevant cards) with minimal risk.

#### Priority 3: RunIndex wired into production (Phase C)

`RunIndex` is now instantiated in `create_app()` and passed to `AgentRunner`. Changes:

- `RunIndex(db_path / "data" / "run_index.db")` created alongside other components
- Passed as `run_index=run_index` to `AgentRunner` constructor
- `run_index.close()` added to lifespan shutdown
- `_index_run()` now accepts `prompt_package` parameter, extracts `bot_ids` and `date` from `prompt_package.metadata`
- `_write_run_files()` now writes `metadata.json` with `agent_type`, `bot_ids`, `date`, `provider`, `effective_model`, `created_at` — compatible with `reindex_from_directory()`
- Post-invocation backfill updates `metadata.json` with actual `provider` and `effective_model` values (initially written empty because `_write_run_files` runs before invocation)

All 6 assemblers now populate `pkg.metadata["bot_ids"]` and `pkg.metadata["date"]` so this data flows through to the run index.

The review recommended backfilling historical run folders. This was not implemented because existing run folders lack `metadata.json` files and their directory names don't reliably encode bot_ids or dates. A backfill script would need heuristic extraction from prompt content, which is fragile. Going forward, all new runs will be indexed correctly.

The review also noted that `RunIndex.search()` and `RunIndex.get_recent_runs()` have no production callers. This remains true — the index is now populated but not yet consumed. Consumption requires a feature that queries past runs (e.g., a reflector that checks "did we already investigate this pattern?"). This is a valid next step once the index has accumulated data.

#### Priority 4: Outcome reasoning writes through coordinator (Phase D)

The scattered `open()` calls in `_measure_outcomes()` for outcome reasoning, spurious outcomes, and recalibrations were replaced with a collect-then-batch pattern using `LearningWriteCoordinator`:

1. Reasoning records enriched with `reasoned_at` timestamp
2. For-loop collects spurious and recalibration records into lists
3. Transfer proposal logic remains in the for-loop (self-contained via `_tpb.create_from_reasoning`)
4. Single `write_coordinator.begin()` / `add_jsonl_append()` / `execute()` batch writes all records with shared `group_id` and provenance

This gives outcome reasoning writes:
- Shared `_write_group_id` for cross-reference
- Provenance logged to `write_log.jsonl`
- Per-operation success/failure tracking
- Event broadcast on completion

The review recommended also routing weekly synthesis/recalibration, discovery persistence, and validator-block persistence through the coordinator. These were not addressed because:
- Weekly synthesis writes happen in `handlers.py` through `RetroBuilder`, which has its own write coordination
- Discovery persistence is handled by the discovery agent's file output, not by the orchestrator
- Validator-block writes happen in `response_validator.py` through the handler pipeline and are single-file appends where grouped provenance adds little value

### Post-Implementation Review Fixes (2026-04-17)

Three additional issues were found and fixed during code review:

1. **`metadata.json` provider/effective_model backfill** (`agent_runner.py`): `_write_run_files` runs before invocation, so `provider` and `effective_model` were always `""`. Added a post-invocation backfill in `_invoke_with_selection_inner` that reads and updates metadata.json with actual values. This ensures `reindex_from_directory()` recovery produces correct provider/model data.

2. **Spurious record missing `bot_id`** (`app.py`): The spurious outcome record dict omitted `bot_id`, while the adjacent recalibration record correctly included it from `suggestion_lookup`. Added `"bot_id": suggestion_lookup.get(sid, {}).get("bot_id", "")` to match. Without this fix, cards ingested from `spurious_outcomes.jsonl` would always have empty `bot_id`, losing bot association for the bot-aware retrieval implemented in Phase B.

3. **Type annotation cleanup** (`learning_card_store.py`): Dropped the unconventional `type(self.card_from_correction)` annotation from the `sources` list (evaluates to `<class 'function'>` at runtime — technically valid but confusing).

### What Was Not Addressed and Why

#### Priority 5: Shadow-mode provider performance tracking

**Status**: Correctly deferred.

The review recommends a `ProviderPerformanceTracker` that scores routes by validator pass rate, parsing reliability, latency, cost per successful run, and downstream outcome quality. This was not implemented because:

- The system currently has primarily one provider in active use (Claude Max). Shadow tracking produces unused reports until multi-provider usage is common.
- The existing `ProviderCooldownTracker` already handles the most critical operational need (avoiding recently-failed providers).
- Meaningful outcome-quality scoring requires accumulating enough runs across multiple providers to reach statistical significance, which hasn't happened yet.
- The cost/benefit ratio improves significantly once RunIndex is populated and multiple providers are regularly used.

#### Priority 6: Retrieval feedback wiring

**Status**: Correctly deferred.

`record_feedback()` exists on `LearningCardIndex` but is not wired into live flows. This was not implemented because:

- It requires a card corpus to exist first. Phase A creates that corpus; feedback wiring becomes meaningful afterward.
- The feedback signals (validator blocked after card retrieval, positive outcome aligned with retrieved card) require correlation between `_learning_card_ids` in run metadata and downstream outcomes — a pipeline that doesn't exist yet.
- The card ranking already incorporates retrieval count as a decay signal. Adding feedback is an optimization on top of a functional baseline.

#### Priority 7: Token-aware budget activation

**Status**: Correctly deferred.

All assemblers call `base_package()` without `context_budget_tokens`. This was not implemented because:

- The current item-budget approach works well given the current memory layer size.
- Token-aware budgeting becomes valuable when the memory layer grows large enough that items compete for prompt space. With the card pipeline just activated, the corpus is still small.
- Activating token budgets prematurely would add complexity (token estimation heuristics, budget tuning per workflow) without measurable improvement.

#### Review recommendation 2: Full LearningMemoryManager class

**Status**: Intentionally not implemented.

The review recommended a "thin, trading-specific manager" that constructs workflow queries, ranks cards and raw evidence together, applies one token budget, and scopes loaders by workflow and bot. This was not implemented as a separate class because:

- `ContextBuilder.base_package()` already performs the core orchestration: workflow-aware priority ordering, adaptive item-budgeting, token-aware budgeting support, and broad learning-context loading.
- Adding a separate manager class would duplicate what `base_package()` does and create two competing integration points for the same data.
- The specific sub-recommendations (bot-aware queries, scoped loaders) were addressed directly: bot_id passthrough (Phase B) and the existing `_WORKFLOW_PRIORITIES` dict already handles workflow scoping.
- If a dedicated manager becomes necessary in the future, it should replace `base_package()`, not wrap it.

### Files Modified

| File | Changes |
|---|---|
| `skills/learning_card_store.py` | 3 new factory methods, expanded `ingest_from_existing()` to 8 sources, type annotation cleanup |
| `analysis/context_builder.py` | Added `bot_id` param to `base_package()`, fixed `_findings_dir` bug |
| `analysis/prompt_assembler.py` | Pass `bot_id` to `base_package()`, set `metadata["bot_ids"]`/`metadata["date"]` |
| `analysis/wfo_prompt_assembler.py` | Pass `bot_id` to `base_package()`, set metadata |
| `analysis/weekly_prompt_assembler.py` | Set `metadata["bot_ids"]`/`metadata["date"]` |
| `analysis/triage_prompt_assembler.py` | Set `metadata["date"]` |
| `analysis/discovery_prompt_assembler.py` | Set `metadata["bot_ids"]`/`metadata["date"]` |
| `analysis/outcome_reasoning_prompt.py` | Set `metadata["date"]` |
| `orchestrator/app.py` | Instantiate RunIndex + WriteCoordinator, pass RunIndex to AgentRunner, add `run_index.close()`, add card ingestion calls, refactor outcome reasoning writes, add `bot_id` to spurious records |
| `orchestrator/agent_runner.py` | Add `prompt_package` to `_index_run()`, write `metadata.json`, add post-invocation backfill |

### New Test Files

| File | Tests |
|---|---|
| `tests/test_learning_card_ingestion.py` | 12 tests for expanded ingestion + new factory methods |
| `tests/test_run_index_wiring.py` | 10 tests for RunIndex wiring, metadata.json, backfill, assembler metadata |
| `tests/test_write_coordinator_wiring.py` | 8 tests for coordinator adoption, provenance, spurious bot_id |
| `tests/test_context_builder.py` (appended) | 4 tests for bot-aware card retrieval |
