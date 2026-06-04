# Hermes Meta-Learning Port Plan

Date: 2026-05-03

Scope: identify which meta-learning components and patterns from `_references/hermes-agent/` should be ported into `trading_assistant`, how they should be adapted to trading-specific learning, and which abstractions should be left behind.

## Executive Verdict

`trading_assistant` has already ported several Hermes-like ideas: run indexing, learning cards, prompt memory, provider scoring, generated playbooks, a weekly learning cycle, and partial coordinated writes. The port is real, but incomplete. The current implementation is strongest at collecting learning artifacts and injecting them into future prompts. It is weaker at replaying past decisions, curating procedural knowledge based on measured outcomes, and enforcing a stable memory interface around trading-specific evidence.

Second-pass correction: context budgeting is already implemented inline in `analysis/context_builder.py`, and prompt-injection defense exists for inbound user messages in `orchestrator/input_sanitizer.py`. The right port is not to add those concepts from scratch. It is to extend them to learned memory, extract workflow policy where useful, and add replay/curation layers that Hermes has but `trading_assistant` still lacks.

Hermes' most valuable pattern is not any single tool. It is the combination of:

- bounded memory with clear write rules,
- session/run search,
- trajectory capture,
- replay/evaluation environments,
- procedural skill curation,
- usage telemetry,
- context-budget management,
- and background insight generation.

For `trading_assistant`, these should not be ported as generic assistant memory. They should be adapted as typed trading-learning infrastructure: proposal memory, diagnostic memory, experiment memory, replay cases, outcome-scored playbooks, and learning-operations insights.

## Current Hermes-Like Capabilities in `trading_assistant`

### 1. Run Search and Session Memory

Current state:

- `orchestrator/run_index.py` creates a SQLite FTS5 index over runs, agent type, bot IDs, response text, instructions, validator notes, and structured output.
- `orchestrator/run_index.py::index_run()` indexes `response.md`, `instructions.md`, `validator_notes.md`, and `parsed_analysis.json`.
- `orchestrator/run_index.py::search()` supports FTS search with filters by agent type, bot ID, and minimum date.
- `analysis/context_builder.py::base_package()` retrieves similar past runs and recent runs for prompts.

Hermes reference:

- `_references/hermes-agent/tools/session_search_tool.py` uses SQLite FTS5, resolves parent sessions, excludes current lineage, summarizes top sessions, and instructs the agent to proactively search prior work.

Assessment:

`trading_assistant` has the storage and retrieval foundation. It has not fully ported Hermes' summarized recall pattern, parent/lineage grouping, or replay-oriented use of past sessions.

### 2. Learning Cards and Prompt Memory

Current state:

- `schemas/learning_card.py::LearningCard` stores reusable learning with tags, source type, impact, confidence, half-life, and retrieval feedback.
- `schemas/learning_card.py::LearningCard.relevance_score()` ranks cards by recency, impact, confidence, retrieval feedback, and context match.
- `skills/learning_card_store.py::ranked_for_prompt()` retrieves prompt-relevant cards.
- `skills/learning_card_store.py::ingest_from_existing()` can ingest validations, transfer outcomes, retrospectives, and other existing learning artifacts.
- `analysis/context_builder.py::base_package()` loads learning cards into the prompt package.
- `orchestrator/invocation_builder.py::build_full_prompt()` includes learning memory and playbooks in actual runtime prompts.
- `orchestrator/handlers.py::_record_learning_card_feedback_targeted()` updates helpful/harmful feedback based on overlap between card tags and approved or blocked suggestions.

Hermes reference:

- `_references/hermes-agent/tools/memory_tool.py` implements bounded persistent memory with `MEMORY.md` and `USER.md`, a frozen snapshot for the current turn, injection scanning, deduplication, and controlled add/replace/remove/read actions.
- `_references/hermes-agent/agent/memory_manager.py::build_memory_context_block()` fences recalled memory and marks it as context, not user input.
- `_references/hermes-agent/agent/memory_provider.py::MemoryProvider` defines a lifecycle interface for memory providers: availability, initialize, prefetch, sync turn, tool schemas, session hooks, compression hooks, and shutdown.

Assessment:

`trading_assistant` has richer typed memory than Hermes' free-form memory, which is appropriate for the domain. What it lacks is a clear memory-provider boundary and a stricter write/read contract. Learning cards, playbooks, run search, outcome measurements, and ledgers are currently loaded directly by `ContextBuilder` rather than coordinated through a unified learning-memory manager.

### 3. Weekly Learning Cycle and Meta-Evaluation

Current state:

- `skills/learning_cycle.py::run()` creates ground truth snapshots, retrospectives, hypothesis lifecycle updates, suggestion category recalibration, benchmark cases, provider route scores, harness evaluation, playbooks, selected next experiments, and ledger entries.
- `skills/learning_ledger.py::compute_cycle_effectiveness()` estimates weekly cycle effectiveness from improvement, conversion, outcome quality, and lesson yield.
- `skills/benchmark_compiler.py::compile()` creates benchmark cases from validation blocks, negative outcomes, calibration misses, and transfer failures.
- `skills/harness_eval_runner.py` evaluates prompt variants over benchmark cases.
- `skills/provider_route_scorer.py::recommend_provider()` feeds learned provider selection.

Hermes reference:

- `_references/hermes-agent/environments/hermes_base_env.py` defines an evaluation environment abstraction with datasets, tools, max turns, scoring, and managed state.
- `_references/hermes-agent/environments/hermes_swe_env/hermes_swe_env.py::compute_reward()` runs tests in a sandbox and returns scored rewards.
- `_references/hermes-agent/environments/agent_loop.py::HermesAgentLoop.run()` captures full messages, tool calls, reasoning summaries, tool errors, turn counts, and termination state.

Assessment:

`trading_assistant` has the weekly evaluation scaffold but not the replay environment. `skills/harness_eval_runner.py::_score_case()` currently uses fixed heuristics, not actual provider or prompt replay. This is the largest missing Hermes-style capability.

### 4. Procedural Playbooks

Current state:

- `skills/playbook_generator.py` creates generated playbooks from benchmark cases and retrospectives.
- `analysis/context_builder.py::base_package()` loads generated playbooks into prompt context.

Hermes reference:

- `_references/hermes-agent/tools/skill_manager_tool.py` lets the agent create, edit, and patch procedural skills after successful complex tasks or when existing skills are outdated.
- `_references/hermes-agent/tools/skill_usage.py` tracks skill views, uses, patches, state, pins, archival status, and agent-created reports.
- `_references/hermes-agent/agent/curator.py` runs background skill maintenance, marks skills stale or archived, reviews agent-created skills, consolidates overlapping skills, and writes run reports.

Assessment:

`trading_assistant` has generated playbooks but not playbook lifecycle management. It should port Hermes' usage and curator patterns, but adapt them to trading outcomes: a playbook should be retained because it improves proposal quality or live outcome decisions, not because it is frequently viewed.

### 5. Coordinated Learning Writes

Current state:

- `skills/learning_write_coordinator.py` groups related writes under a shared `write_group_id`, records provenance, deduplicates writes, and logs success/failure.
- `orchestrator/app.py` uses it in the outcome-reasoning path.

Hermes reference:

- Hermes memory tools use locks, frozen snapshots, injection scanning, and bounded writes.
- The memory manager provides a central routing layer for memory providers.

Assessment:

The coordinator is a strong starting point, but it is only partially wired. Suggestion writes, parameter search reports, experiment records, calibration predictions, structural experiments, learning cards, and ledger writes should all use it for atomic provenance.

### 6. Context Budgeting

Current state:

- `analysis/context_builder.py::_CONTEXT_PRIORITY` defines a default priority order for prompt data.
- `analysis/context_builder.py::_WORKFLOW_PRIORITIES` defines workflow-specific priority lists for weekly analysis, WFO, discovery analysis, outcome reasoning, and triage.
- `analysis/context_builder.py::base_package()` supports both item-count budgeting and token-aware budgeting through `context_budget_items` and `context_budget_tokens`.
- The same method records `_context_budget_manifest` with included keys, omitted keys, budget mode, workflow, total available items, and token estimates.
- `tests/test_hermes_port.py` covers workflow-aware filtering and token-aware context budget behavior.

Hermes reference:

- `_references/hermes-agent/agent/context_engine.py::ContextEngine`
- `_references/hermes-agent/agent/context_compressor.py::ContextCompressor`

Assessment:

`trading_assistant` already has the most important first-order budgeting behavior. The remaining Hermes-style gap is structured summarization and memory-provider coordination. Large low-priority sections are dropped, but not summarized into compact lessons; the policy is embedded in `ContextBuilder`; and there is no dedicated memory manager that can prefetch, rank, summarize, and sync providers.

## High-Value Hermes Patterns to Port

### Pattern 1: Memory Provider Boundary

Hermes source:

- `_references/hermes-agent/agent/memory_provider.py::MemoryProvider`
- `_references/hermes-agent/agent/memory_manager.py::MemoryManager`
- `_references/hermes-agent/agent/memory_manager.py::build_memory_context_block()`

What to port:

- A lifecycle-managed memory interface.
- Explicit prefetch/sync hooks.
- Fenced memory blocks.
- Nonfatal memory-provider failures.
- A single orchestration layer for memory injection.

How to adapt:

Add `skills/learning_memory_manager.py`:

- `collect_context(workflow, bot_id, strategy_id, regime, category, token_budget) -> LearningMemoryBundle`
- `record_event(event: LearningEvent) -> WriteResult`
- `prefetch(workflow, scope) -> PrefetchHandle`
- `sync_after_run(run_id, parsed_output, validation_result, outcome_refs)`

Providers should be typed:

- `LearningCardProvider`
- `RunRecallProvider`
- `OutcomeProvider`
- `ProposalLedgerProvider`
- `ExperimentProvider`
- `PlaybookProvider`
- `ReliabilityProvider`

Do not port Hermes' generic user-memory model directly. Trading memory should remain structured and source-attributed.

### Pattern 2: Frozen Memory Snapshot and Write Safety

Hermes source:

- `_references/hermes-agent/tools/memory_tool.py::MemoryStore`
- `_references/hermes-agent/tools/memory_tool.py::add()`
- `_references/hermes-agent/tools/memory_tool.py` injection scanner

What to port:

- Snapshot memory at invocation start.
- Allow writes during a run, but do not let those writes silently alter the same run's system prompt.
- Scan learned text for prompt-injection patterns before future prompt inclusion.
- Enforce size limits, deduplication, and provenance.

How to adapt:

Update `orchestrator/agent_runner.py::_write_run_files()` and `orchestrator/invocation_builder.py::build_full_prompt()`:

- Build a frozen `learning_memory_snapshot.json`.
- Include only sanitized, scoped memory in `<learning-memory>` blocks.
- Store live writes separately and expose them only to future runs after validation.

Extend `orchestrator/input_sanitizer.py` or add a dedicated `skills/learning_memory_sanitizer.py`:

- Strip tool-use instructions, identity override patterns, hidden Unicode control characters, and prompt-injection markers.
- Preserve quantitative trading evidence.

### Pattern 3: Session Search With Summarized Recall

Hermes source:

- `_references/hermes-agent/tools/session_search_tool.py::session_search()`
- `_references/hermes-agent/tools/session_search_tool.py::_summarize_session()`

What to port:

- Summarize relevant prior runs, not just retrieve raw snippets.
- Exclude current lineage.
- Group related runs.
- Prefer high-signal summaries over long raw recall.

How to adapt:

Extend `orchestrator/run_index.py`:

- Add `run_parent_id`, `root_run_id`, `workflow`, `proposal_ids`, `experiment_ids`, and `outcome_ids`.
- Add `search_summaries(query, filters, max_tokens)`.
- Cache summaries in `data/run_summaries/*.jsonl`.

Update `analysis/context_builder.py::base_package()`:

- Replace raw similar-run blocks with summarized prior-run lessons.
- Scope by bot, strategy, lifecycle stage, provider, and proposal category.

### Pattern 4: Replayable Trajectories

Hermes source:

- `_references/hermes-agent/agent/trajectory.py::save_trajectory()`
- `_references/hermes-agent/environments/agent_loop.py::AgentResult`
- `_references/hermes-agent/environments/agent_loop.py::HermesAgentLoop.run()`

What to port:

- Full decision trajectories.
- Prompt package, model/provider, parsed output, validation result, user approval, implementation state, live outcome, and retrospective label.
- Replay cases derived from real successes and failures.

How to adapt:

Add `schemas/replay_case.py`:

- `ReplayCase`: source run, workflow, bot, strategy, prompt package hash, input artifacts, expected decision, forbidden decision, validator reason, measured outcome, scoring rubric.
- `ReplayResult`: provider, prompt variant, parsed suggestions, validation result, score, failure modes, latency, cost.

Add `skills/replay_case_builder.py`:

- Build cases from negative outcomes, calibration misses, validation blocks, false rejections, successful high-impact proposals, and missed high-value opportunities.

Add `skills/harness_replay_runner.py`:

- Reinvoke candidate providers or prompt variants on frozen cases.
- Parse with `analysis/response_parser.py`.
- Validate with `analysis/response_validator.py`.
- Score actual decisions against expected outcomes.

### Pattern 5: Procedural Skill Usage and Curator

Hermes source:

- `_references/hermes-agent/tools/skill_manager_tool.py`
- `_references/hermes-agent/tools/skill_usage.py`
- `_references/hermes-agent/agent/curator.py`

What to port:

- Usage tracking for procedural knowledge.
- Stale/active/archived lifecycle.
- Background curation.
- Consolidation of overlapping guidance.
- Patching guidance when outcomes show it is incomplete or harmful.

How to adapt:

Do not allow unconstrained agent-created trading rules. Instead, use outcome-scored playbooks.

Add `schemas/playbook_usage.py`:

- `PlaybookUsageRecord`: playbook id, workflow, run id, retrieval reason, used sections, resulting suggestions, validation status, outcome ids.
- `PlaybookLifecycleState`: active, stale, archived, pinned, needs_review.

Add `skills/playbook_usage_tracker.py`:

- Record retrievals, uses, outcome attributions, and negative feedback.

Add `skills/playbook_curator.py`:

- Review generated playbooks after each learning cycle.
- Archive playbooks associated with bad outcomes or repeated validation failures.
- Promote playbooks associated with high-quality decisions.
- Patch playbooks when a new outcome reveals a missing condition.

Update `skills/playbook_generator.py`:

- Generate versioned playbooks with source cases, applicability constraints, contraindications, and expected evidence.

### Pattern 6: Context Budget Management

Hermes source:

- `_references/hermes-agent/agent/context_engine.py::ContextEngine`
- `_references/hermes-agent/agent/context_compressor.py::ContextCompressor`

What to port:

- Structured context summarization and provider-aware budgeting on top of the existing workflow-aware budget.
- Structured summaries of older, lower-priority context.
- Anti-thrashing rules around compression.
- Explicit preservation of the current task and high-priority evidence.

How to adapt:

Extract or extend the existing `analysis/context_builder.py` budget logic into `analysis/context_budget.py` only if it reduces complexity:

- `ContextBudgetPolicy` by workflow: daily, weekly, WFO, triage, structural review, outcome measurement.
- Priority tiers: current data, objective, lifecycle diagnostics, active experiments, relevant outcomes, learning cards, run recall, generated playbooks.
- Token estimates and summarization rules.

Update `analysis/context_builder.py`:

- Return prioritized context sections, not just data dictionaries.
- Summarize or drop low-priority sections when the prompt budget is exceeded.
- Preserve the current `_context_budget_manifest` and extend it with summary counts, provider names, and reason codes for omitted memory.

### Pattern 7: Learning Operations Insights

Hermes source:

- `_references/hermes-agent/agent/insights.py::InsightsEngine`

What to port:

- Periodic insight reports about the learning system itself.
- Tool/provider/workflow usage.
- Success rate by workflow.
- Top productive runs.
- Failure modes and stale memory.

How to adapt:

Add `skills/learning_insights.py`:

- Proposal conversion rate by source.
- Validation pass rate by provider/model/category.
- Backtest-to-live reliability by bot/strategy/regime.
- Structural proposal outcome quality.
- Learning-card helpfulness.
- Playbook usage and outcome association.
- Experiment throughput and age.
- Instrumentation blockers.

Write reports to `docs/learning_ops/` or `data/learning_insights/` and feed summaries into the weekly `LearningCycle`.

## Integration Map

| Hermes component | Port target in `trading_assistant` | Adaptation |
| --- | --- | --- |
| `agent/memory_provider.py` | `skills/learning_memory_manager.py` and provider classes | Typed trading evidence providers instead of generic memory providers |
| `agent/memory_manager.py` | `analysis/context_builder.py` and `orchestrator/invocation_builder.py` | Centralize memory collection, scoping, fencing, and sync hooks |
| `tools/memory_tool.py` | `skills/learning_memory_sanitizer.py` and `skills/learning_write_coordinator.py` | Frozen snapshots, injection scanning, bounded writes, provenance |
| `tools/session_search_tool.py` | `orchestrator/run_index.py` | Summarized run recall, lineage grouping, proposal/experiment filters |
| `agent/trajectory.py` | `schemas/replay_case.py` and run artifacts | Preserve prompt/output/validation/outcome trajectory |
| `environments/agent_loop.py` | `skills/harness_replay_runner.py` | Replay frozen trading cases through providers/prompt variants |
| `environments/hermes_base_env.py` | `skills/trading_eval_environment.py` | Offline environment for scored proposal decisions |
| `tools/skill_manager_tool.py` | `skills/playbook_curator.py` | Outcome-scored playbooks, not free-form trading-rule skills |
| `tools/skill_usage.py` | `skills/playbook_usage_tracker.py` | Track use, validation, and outcome impact |
| `agent/curator.py` | `skills/playbook_curator.py` | Archive, patch, consolidate, and promote generated playbooks |
| `agent/context_compressor.py` | Existing `analysis/context_builder.py` budget logic, optionally extracted to `analysis/context_budget.py` | Preserve current workflow/token budget; add summarization and provider-aware compression |
| `agent/insights.py` | `skills/learning_insights.py` | Learning-operations reports and metrics |

## What to Leave Behind

Do not port these Hermes abstractions directly:

- Generic user preference memory. Trading memory must be evidence-backed and scoped.
- Generic external memory providers unless there is a concrete storage need.
- Agent-managed arbitrary skill creation for trading rules. Use governed playbooks and approval-gated structural proposals instead.
- Full RL/Atropos training loops as an initial dependency. Start with deterministic replay evaluation; consider reinforcement-style training only after replay cases and rewards are trustworthy.
- Generic conversational session summaries that are not tied to proposal, experiment, diagnostic, or outcome IDs.
- Any memory write path that allows untrusted bot output to become prompt instructions.

## Concrete Port Plan

### Phase 0: Harden Existing Memory Injection

1. Extend `orchestrator/input_sanitizer.py` for learned-memory/playbook text or add `skills/learning_memory_sanitizer.py` if separation is cleaner.
2. Add frozen `learning_memory_snapshot.json` to every run folder in `orchestrator/agent_runner.py::_write_run_files()`.
3. Add explicit scope metadata to learning cards, search reports, playbooks, run summaries, and outcome snippets.
4. Update `orchestrator/invocation_builder.py::build_full_prompt()` to fence learning memory as context, not instructions.
5. Fix bot-scoping gaps in `analysis/context_builder.py::base_package()`, especially search reports and backtest reliability.

### Phase 1: Add a Learning Memory Manager

1. Add `skills/learning_memory_manager.py`.
2. Move memory-loading orchestration out of `ContextBuilder` into provider classes.
3. Keep `ContextBuilder` responsible for assembling the prompt package, but have it request scoped memory bundles from the manager.
4. Route memory writes through `LearningWriteCoordinator`.
5. Add tests for memory scoping, sanitization, and provider failure tolerance.

### Phase 2: Build Replay Cases and Real Harness Evaluation

1. Add `schemas/replay_case.py`.
2. Add `skills/replay_case_builder.py`.
3. Convert `skills/benchmark_compiler.py` cases into replay-ready cases with expected decisions and scoring rubrics.
4. Add positive cases, false rejection cases, and missed high-value opportunity cases.
5. Add `skills/harness_replay_runner.py`.
6. Replace `skills/harness_eval_runner.py::_score_case()` or mark it as a cheap prefilter only.
7. Feed replay results into `skills/provider_route_scorer.py`, `skills/playbook_generator.py`, and `skills/learning_cycle.py`.

### Phase 3: Add Procedural Playbook Lifecycle

1. Add `schemas/playbook_usage.py`.
2. Add `skills/playbook_usage_tracker.py`.
3. Add `skills/playbook_curator.py`.
4. Update `skills/playbook_generator.py` to emit applicability constraints, contraindications, source cases, and version IDs.
5. Record playbook retrieval and use during each agent invocation.
6. Promote, patch, archive, or pin playbooks based on validation and measured outcome.

### Phase 4: Extract and Strengthen Context Budgeting

1. Preserve the existing workflow-aware and token-aware budget behavior in `analysis/context_builder.py`.
2. Extract `analysis/context_budget.py` only if needed to make policies testable and reusable.
3. Add summarized run recall and summarized outcome memory instead of only dropping large sections.
4. Make `analysis/context_builder.py::base_package()` return prioritized sections with reason codes.
5. Add tests that high-priority current data and active experiments cannot be displaced by low-priority generated playbooks, and tests that large useful context is summarized when it cannot fit.

### Phase 5: Add Learning Operations Insights

1. Add `skills/learning_insights.py`.
2. Generate weekly learning-ops reports after `skills/learning_cycle.py::run()`.
3. Track proposal conversion, validation pass rate, provider performance, experiment throughput, stale playbooks, memory helpfulness, and instrumentation blockers.
4. Feed insights into `LearningCycle` and human-facing weekly reports.

## Required Data Flow After Port

```text
Agent run starts
  -> LearningMemoryManager collects scoped, sanitized, frozen memory
  -> ContextBuilder assembles prioritized prompt package
  -> AgentRunner writes run files and invocation metadata
  -> LLM output is parsed and validated
  -> ProposalLedger records decisions and evidence
  -> LearningWriteCoordinator writes related artifacts atomically
  -> Outcome measurement later links live results
  -> ReplayCaseBuilder creates scored cases from successes/failures
  -> HarnessReplayRunner evaluates providers and prompt variants
  -> PlaybookCurator updates procedural memory
  -> LearningInsights reports system-level learning quality
  -> Next run receives better scoped memory
```

## Evaluation Criteria for the Port

The Hermes port should be considered successful when these metrics improve:

- Replay accuracy: prompt/provider variants choose the known-good action on frozen cases.
- Decision precision: accepted suggestions have higher measured positive-outcome rates.
- Decision recall: the system misses fewer high-value proposals.
- Calibration: predicted impact aligns better with live measured impact.
- Context usefulness: retrieved cards and playbooks receive positive outcome-linked feedback.
- Provider routing: learned provider choices beat the default provider on replay and live validation.
- Playbook health: stale/harmful playbooks are archived, and high-performing playbooks are reused.
- Experiment throughput: fewer proposals remain unmeasured or stuck without acceptance criteria.
- Instrumentation closure: inconclusive outcomes increasingly create concrete diagnostic tasks.

## Final Recommendation

The highest-value Hermes capabilities to port next are replayable trajectories and procedural-memory curation. `trading_assistant` already has enough artifacts to remember prior lessons. It now needs to test whether those lessons make future decisions better.

The recommended order is:

1. Harden and scope learning memory.
2. Build replay cases from real proposal outcomes.
3. Replace heuristic harness evaluation with replay.
4. Add playbook usage tracking and curation.
5. Add learning-operations insights.

This keeps the port focused on the mission: improving trading decisions and expected returns over time, not building a generic assistant memory system.
