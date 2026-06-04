# Hermes Port Implementation Audit

Date: 2026-04-17

## Purpose

This is a follow-up implementation audit of `docs/hermes_port_current_state_review_2026-04-16.md`.

The goal here is narrower than the earlier review:

- verify which Hermes-port recommendations are now actually implemented in live code
- check whether those implementations are correct, not just present
- identify report notes that are now inaccurate or unsupported by the repo
- reassess which deferred items still should stay deferred versus which now have clear, material expected value

This audit is based on the current repo state, not on assumptions about live operator behavior.

## Executive Verdict

The repo has made real Hermes-port progress, and several important items from the earlier review are now genuinely implemented:

- prompt delivery is materially better
- `RunIndex` is wired into production
- `metadata.json` is written for runs
- outcome-reasoning writes now use `LearningWriteCoordinator`
- learning-card ingestion is live in production paths
- learning-card retrieval is bot-aware for the workflows where it matters most today

However, the current implementation is still **not yet the optimal integration** of Hermes's best elements for improving trading performance over time.

The biggest reason is not lack of infrastructure. It is that some of the new learning-loop pieces are still semantically miswired:

- validator-block cards are being built from the wrong input shape
- `lessons_learned` is not normalized consistently, so some of the highest-value reflective lessons degrade into noisy prompt text
- run-index metadata is still incomplete for some workflows
- two structured, high-value learning sources were deferred for reasons that are not supported by the codebase

So the repo has moved from "missing primitives" to "integration quality matters." That is progress, but it also means the next gains come from tightening semantics and source coverage rather than adding more generic memory machinery.

## What Is Correctly Implemented

The following points from the earlier review now appear correctly implemented and worth keeping:

### 1. Prompt delivery

`orchestrator/invocation_builder.py:72-125` now merges:

- `task_prompt`
- `instructions`
- summarized `corrections`
- `skill_context`
- `_learning_cards_text`
- a manifest of available JSON data files

This closes the earlier prompt-delivery gap in a meaningful way.

### 2. Run indexing infrastructure

`orchestrator/app.py:320-340` instantiates `RunIndex` and passes it to `AgentRunner`.

`orchestrator/agent_runner.py:281-307` indexes completed runs and now passes:

- provider
- effective model
- `bot_ids`
- `date`
- success
- duration
- cost

`orchestrator/agent_runner.py:573-605` writes `metadata.json`, and `orchestrator/agent_runner.py:527-534` backfills provider/model after invocation.

This is a real infrastructure improvement, not just test-only scaffolding.

### 3. Coordinator adoption for outcome reasoning

`orchestrator/app.py:1166-1189` now groups outcome-reasoning, spurious-outcome, and recalibration writes through `LearningWriteCoordinator`.

That meaningfully improves provenance and reduces the previous multi-file partial-write risk in one of the highest-value reflective flows.

### 4. Production card ingestion hooks

`orchestrator/app.py:1194-1200` and `orchestrator/app.py:1314-1320` call `LearningCardStore.ingest_from_existing()` after outcome reasoning and after memory consolidation.

That means the card layer is no longer purely symbolic. It is live.

### 5. Bot-aware card retrieval for targeted workflows

`analysis/context_builder.py:1593-1599` now retrieves ranked cards with `bot_id=bot_id`.

`analysis/prompt_assembler.py:270-288` passes a single bot for single-bot daily workflows, and `analysis/wfo_prompt_assembler.py:45-52` passes the WFO bot id directly.

This is a good, low-risk first scoping improvement.

## Findings

The findings below are ordered by severity and expected impact on the learning loop.

### Finding 1

**Validator-block card ingestion is wired to the wrong source shape, so real validation-log entries collapse into low-information duplicate cards.**

Evidence:

- `orchestrator/handlers.py:1991-2008` writes `validation_log.jsonl` entries shaped like:
  - `date`
  - `approved_count`
  - `blocked_count`
  - `blocked_details`
  - `timestamp`
- `analysis/context_builder.py:689-745` correctly treats `validation_log.jsonl` as a raw log and aggregates it into `validation_patterns`
- `skills/learning_card_store.py:171-183` explicitly says `card_from_validator_block()` is for a `validation_patterns` entry and expects fields like:
  - `pattern_id`
  - `category`
  - `reason`
  - `block_count`
- `skills/learning_card_store.py:253-261` nevertheless maps raw `validation_log.jsonl` lines directly into `card_from_validator_block()`

Observed effect from a direct code probe on realistic handler-style entries:

- `source_id` becomes empty
- `bot_id` becomes empty
- `content` becomes empty
- title collapses to the same `"BLOCKED: unknown - blocked"` shape
- multiple distinct validation-log entries produce the same deterministic `card_id`

That means this path is not just "low quality." It is functionally collapsing real validator memory into a single generic card.

This is important because validator blocks are one of the strongest negative-learning signals in the repo. If they are promoted into cards incorrectly, the Hermes-style memory layer cannot reliably learn from repeated rejected patterns.

The current test coverage missed this mismatch:

- `tests/test_learning_card_ingestion.py:106-114` tests `validation_log.jsonl` ingestion with a synthetic `pattern_id/category/reason` shape that does not match the real writer in `orchestrator/handlers.py`

Recommended fix:

- either ingest `validation_patterns` after aggregation, not raw `validation_log.jsonl`
- or add a `card_from_validation_log()` normalizer that expands `blocked_details` into stable, category-aware cards

### Finding 2

**`lessons_learned` is not normalized consistently, so outcome-reasoning and recalibration lessons can degrade into character-split noise.**

Evidence:

- `analysis/outcome_reasoning_prompt.py:48-58` specifies `"lessons_learned": "..."` as a string in the structured output schema
- `orchestrator/app.py:1157-1163` persists `r.get("lessons_learned", [])` into recalibration records without normalization
- `skills/learning_card_store.py:189-196` and `skills/learning_card_store.py:215` treat `lessons_learned` like a list of strings
- `analysis/context_builder.py:1107-1118` also iterates `lessons_learned` like a list when building self-assessment signals

Observed effect from a direct code probe:

- `"tighten stop"` becomes `t; i; g; h; t; e; n; ...` in both `card_from_outcome_reasoning()` and `card_from_recalibration()`

This matters because these are among the most important Hermes-style reflective artifacts:

- outcome reasoning
- recalibration
- causal lessons

If those lessons are injected as broken character sequences, the memory layer becomes noisier exactly where it should be most useful.

The repo already contains the right normalization pattern:

- `skills/retrospective_builder.py:231-240` handles both string and list forms safely

Recommended fix:

- normalize `lessons_learned` once, at write time or at load/ingestion time
- use the same string-or-list normalization already present in `RetrospectiveBuilder`

### Finding 3

**Run-index metadata is still incomplete for triage and outcome-reasoning workflows, so the implementation does not fully match the report notes.**

The implementation notes in the earlier report claim:

- `docs/hermes_port_current_state_review_2026-04-16.md:837-841`

That claim is not correct in the current code.

Actual state:

- `analysis/triage_prompt_assembler.py:44-48` sets `date` but not `bot_ids`
- `analysis/outcome_reasoning_prompt.py:85-99` sets `date` but not `bot_ids`

This is not a cosmetic gap.

For triage:

- `schemas/bug_triage.py:61-73` defines `ErrorEvent.bot_id`
- `orchestrator/handlers.py:1122-1140` has the triage `bot_id` before prompt assembly

For outcome reasoning:

- the `outcomes` payload already contains bot ids
- the current assembler could derive joined bot ids, or at least pass a single bot id when the batch is single-bot

Impact:

- `RunIndex` filtering remains weaker than it should be for two important workflows
- future replay lookup, route-quality attribution, and bot-scoped diagnostics all lose fidelity

Recommended fix:

- set `pkg.metadata["bot_ids"]` for triage and outcome reasoning
- pass `bot_id` into `base_package()` when those workflows are effectively single-bot

### Finding 4

**Two structured, high-value learning sources remain deferred for reasons that are not supported by the codebase: `transfer_outcomes.jsonl` and `retrospective_synthesis.jsonl`.**

The implementation notes say these were not added because transfer outcomes are not a standalone file and retrospective synthesis is unstructured markdown:

- `docs/hermes_port_current_state_review_2026-04-16.md:801-805`

That rationale is incorrect.

Transfer outcomes are a real standalone JSONL file:

- `skills/transfer_proposal_builder.py:33` defines `_outcomes_path = findings_dir / "transfer_outcomes.jsonl"`
- `skills/transfer_proposal_builder.py:217-229` loads track record directly from `transfer_outcomes.jsonl`
- `skills/convergence_tracker.py:259-269` uses that same file to compute transfer success rate

Retrospective synthesis is also structured JSONL, not unstructured markdown:

- `skills/retrospective_builder.py:150-153` explicitly says it persists to `retrospective_synthesis.jsonl`
- `skills/retrospective_builder.py:252-256` appends `RetrospectiveSynthesis.model_dump_json()`
- `schemas/learning_ledger.py:76-84` defines the structured schema
- `analysis/context_builder.py:870-872` loads it from JSONL today

Meanwhile, `skills/learning_card_store.py:253-261` still does not ingest either source.

These are not fringe artifacts:

- `transfer_outcomes.jsonl` captures whether cross-bot transfer ideas actually worked
- `retrospective_synthesis.jsonl` captures the repo's strongest keep/discard learning summary

Those are exactly the kinds of reflective signals that should graduate into durable ranked memory.

Recommended fix:

- add card factories for transfer outcomes and retrospective synthesis
- prioritize these ahead of lower-EV coordinator expansion work

### Finding 5

**The coordinator-adoption notes in the earlier report overstate what is actually coordinated.**

The implementation notes say weekly synthesis has its own coordination and discovery persistence is handled by the agent output:

- `docs/hermes_port_current_state_review_2026-04-16.md:858-861`

Current code does not support those claims.

Weekly retrospective synthesis still writes directly:

- `skills/retrospective_builder.py:253-256`

Discovery persistence also still writes directly in the handler:

- `orchestrator/handlers.py:1368-1377`

And app-level coordinator usage still appears limited to outcome reasoning:

- `orchestrator/app.py:1167-1185`

This is not the highest-EV bug in the repo, but it does mean the "correctly deferred" rationale should be corrected. Discovery and retrospective persistence are still fragmented write paths.

Recommendation:

- keep this below the semantic fixes above
- but do not describe weekly/discovery coordination as already solved

### Finding 6

**The repo still has not reached the capability level described by a thin Hermes-style learning orchestrator, even though deferring a separate `LearningMemoryManager` class may still be fine.**

This is an important distinction.

It is probably still fine to defer a new manager class.

It is **not** accurate to say the capability gap is closed.

Evidence:

- `analysis/context_builder.py:121-126` supports bot-scoped corrections
- `analysis/context_builder.py:1346-1560` assembles most context globally and still loads many sources unscoped
- `analysis/context_builder.py:1606-1610` still returns `corrections=self.load_corrections()` without bot scoping
- `analysis/context_builder.py:1537-1557` supports token-aware budgeting, but there are no production callers passing `context_budget_tokens`
- `orchestrator/invocation_builder.py:104-113` appends `_learning_cards_text` after the main `base_package()` budgeting step, so the recalled card block is still outside one unified budget
- `schemas/learning_card.py:232-241` exposes `record_feedback()`, but there is no production caller
- no production caller was found for `RunIndex.search()` or `RunIndex.get_recent_runs()`

So the repo has improved plumbing, but not yet the full Hermes-style loop of:

- targeted query construction
- unified ranking across memory and raw evidence
- unified budget
- retrieval feedback
- replay-assisted reuse

Recommended conclusion:

- keep the class deferred if desired
- stop treating the capability gap as closed

## Reassessment of Deferred Decisions

### Still correct to defer

#### 1. Full RL / Tinker-Atropos style training

Still correctly deferred.

Reasons:

- delayed and confounded rewards
- closed external runtimes
- replay and attribution are still immature
- current issues are much more basic and higher EV

#### 2. External or cloud memory backends

Still correctly deferred.

Reasons:

- the bottleneck is memory quality, not storage backend sophistication
- local JSONL plus SQLite is enough for the next stage

#### 3. Full Hermes context-compressor port

Still correctly deferred.

Reasons:

- retrieval semantics are not yet good enough to justify compressor-first work
- better source normalization and ranking will return more value first

#### 4. Token-aware budget activation

Still reasonable to defer for now.

But the reason is not simply "current item budgets work."

The better reason is:

- fix card/source semantics first
- widen source coverage second
- only then make memory and raw evidence compete under one explicit token budget

#### 5. Retrieval-feedback wiring

Still reasonable to defer for now.

But only after the card layer is made trustworthy.

There is limited value in learning helpful/harmful retrieval feedback from cards whose source normalization is still wrong.

### No longer right to defer

#### 1. Validation-log normalization for cards

This should not remain deferred. It is a correctness issue in the live learning-card path.

#### 2. `lessons_learned` normalization

This should not remain deferred. It directly affects the quality of causal learning artifacts.

#### 3. Card ingestion for transfer outcomes

This should not remain deferred. The source exists, is structured, and captures a high-value performance signal.

#### 4. Card ingestion for retrospective synthesis

This should not remain deferred. The source exists, is structured, and encodes the repo's strongest keep/discard summary.

#### 5. `bot_ids` metadata for triage and outcome reasoning

This should not remain deferred. The data is already available and improves the usefulness of the new run-index layer.

### Needs a different rationale

#### ProviderPerformanceTracker

The earlier implementation notes say this was "correctly deferred" partly because one provider is primarily in active use:

- `docs/hermes_port_current_state_review_2026-04-16.md:875-884`

That may or may not be operationally true, but it is not something this repo audit can verify from code alone.

From a code-grounded perspective, the better conclusion is:

- still keep this below the current memory-loop fixes
- do not treat it as the next highest-EV item
- revisit once route attribution, run-index consumption, and multi-provider history are stronger

So the deferral may still be reasonable, but the stated rationale in the report is too assumption-heavy.

## Highest-EV Next Steps

Ordered by expected practical value:

1. Fix validation-log card ingestion so real validator memory becomes usable.
2. Normalize `lessons_learned` across outcome reasoning, recalibration, card creation, and self-assessment.
3. Add `bot_ids` metadata for triage and outcome reasoning, and pass bot scoping into targeted workflows where possible.
4. Add learning-card factories and ingestion for `transfer_outcomes.jsonl` and `retrospective_synthesis.jsonl`.
5. After those are stable, decide whether discovery and retrospective writes should move into `LearningWriteCoordinator`.
6. After the memory layer is semantically reliable, revisit retrieval feedback, unified budgeting, and shadow provider scorecards.

## Bottom Line

The current repo is materially better than the state described in the original Hermes-port review, and several previously missing pieces are now real.

But the current state is still **not yet optimal**, because some of the new Hermes-inspired learning infrastructure is still wired in ways that reduce the value of the strongest reflective signals.

The most important corrections to the current implementation and the current report are:

- the card layer is live, but one of its new sources is miswired
- the reflective lesson format is not normalized consistently
- some run-index metadata is still incomplete
- two structured high-value learning sources were deferred on incorrect premises

The practical implication is straightforward:

- keep deferring RL, cloud memory, and compressor-heavy work
- stop deferring the small, evidence-backed fixes that make the new learning loop actually trustworthy

## Verification Notes

Targeted tests for the newly added Hermes-port wiring passed during this audit:

- `pytest tests/test_learning_card_ingestion.py tests/test_run_index_wiring.py tests/test_write_coordinator_wiring.py -q`

However, the audit also found that one of those tests encodes the wrong assumption:

- `tests/test_learning_card_ingestion.py:106-114` uses a synthetic `validation_log.jsonl` shape that does not match the real writer in `orchestrator/handlers.py`

So the current passing tests are useful, but they do not yet fully protect the highest-risk integration point found here.

---

## Remediation Log (2026-04-18)

All four high-priority findings (1–4) have been fixed. Findings 5–6 remain deferred as planned. An additional review pass caught three supplementary issues that were also resolved.

### Finding 1 — Fixed

**Validator-block card ingestion shape mismatch.**

Changes:
- Added `card_from_validation_log(entry) -> list[LearningCard]` static method to `LearningCardStore`. This expands `blocked_details` from the real `validation_log.jsonl` shape (as written by `handlers.py`) into one card per blocked detail, with:
  - `source_id=f"vlog:{date}:{sha256(title)[:8]}"` for deterministic dedup
  - `bot_id` from each blocked detail
  - `title=f"BLOCKED: {detail_title}"`
  - `content=detail_reason`
- `ingest_from_existing()` updated: validation_log is now handled in a separate multi-card expansion block instead of the single-card factory loop.
- `card_from_validator_block()` preserved unchanged — it correctly handles the aggregated `validation_patterns` shape and may be used elsewhere.
- Tests updated: `test_ingests_validation_log` now uses the real handler shape; added `test_validation_log_empty_blocked_details`, `test_validation_log_multiple_blocks`, and a dedicated `TestValidationLogCards` class with 3 unit tests for the factory method.

### Finding 2 — Fixed

**`lessons_learned` not normalized consistently (string vs list iteration).**

Changes:
- Added `_normalize_lessons(raw) -> list[str]` module-level helper in `learning_card_store.py`. Handles: string → single-element list (unless whitespace-only), list → filtered to non-empty strings, None/falsy → empty list.
- Applied in `card_from_outcome_reasoning()`, `card_from_recalibration()`, and `card_from_retrospective()`.
- `context_builder.py` `_build_self_assessment_signals()`: inline normalization tightened to match the same behavior — filters whitespace-only strings and non-string list items.
- `orchestrator/app.py`: fixed root cause at the write site — `r.get("lessons_learned", [])` changed to `r.get("lessons_learned", "")` to match the schema's `str` type, preventing type inconsistency in persisted JSONL.
- Added `TestLessonsLearnedNormalization` class with 4 tests: string lessons, empty string, whitespace-only string, for both outcome_reasoning and recalibration card factories.

### Finding 3 — Fixed

**`bot_ids` missing from metadata in triage and outcome reasoning assemblers.**

Changes:
- `triage_prompt_assembler.py`: added `bot_id: str = ""` parameter to `assemble()`, passed through to `base_package()` for bot-scoped card retrieval, and set in `pkg.metadata["bot_ids"]` when non-empty.
- `handlers.py`: triage handler call site now passes `bot_id=bot_id` to the assembler.
- `outcome_reasoning_prompt.py`: `assemble()` now derives `bot_ids` from the outcomes list (`sorted({o.get("bot_id", "") for o in outcomes} - {""})`) and sets in metadata.
- Added 2 tests in `test_triage_prompt_assembler.py` (`test_bot_id_passed_to_metadata`, `test_empty_bot_id_omits_bot_ids_metadata`) and 2 tests in `test_outcome_reasoning.py` (`test_metadata_includes_bot_ids_from_outcomes`, `test_metadata_omits_bot_ids_when_none_present`).

### Finding 4 — Fixed

**Missing card factories for `transfer_outcomes.jsonl` and `retrospective_synthesis.jsonl`.**

Changes:
- Added `card_from_transfer_outcome(entry) -> LearningCard`:
  - `card_type=CardType.TRANSFER_RESULT` (enum value already existed)
  - `source_id=f"transfer:{pattern_id}:{target_bot}"`, `bot_id=target_bot`
  - Impact scoring: +0.4 positive, -0.3 negative, 0.0 neutral
  - Confidence: 0.7 if regime matched, 0.4 otherwise
  - Content: structured summary of source_bot, pnl_delta_7d, win_rate_delta_7d, regime_matched
- Added `card_from_retrospective(entry) -> LearningCard`:
  - `card_type=CardType.SYNTHESIS`, `source_id=f"retro:{week_start}"`, `bot_id=""`
  - Content: compact summary from what_worked titles, what_failed titles, discard reasons, lessons_learned (via `_normalize_lessons`)
  - Tags: `["retrospective"]`
- Both added to `ingest_from_existing()` sources list.
- Added `TestCardFromTransferOutcome` (3 tests: positive/negative/neutral verdicts), `TestCardFromRetrospective` (2 tests: full entry, string lessons normalization), and 2 ingestion tests in `TestExpandedIngestion`.

### Finding 5 — Not addressed (correctly deferred)

**Coordinator adoption for discovery and retrospective writes.**

Rationale for deferral:
- Both `retrospective_builder.py` and the discovery handler write to single JSONL files via simple `file.open("a")` appends. The partial-write risk for single-line JSONL appends is negligible — an interrupted append produces at worst a truncated final line, which all readers already skip via `try/except json.JSONDecodeError`.
- The outcome reasoning flow (Finding 3 in the original review) had genuine multi-file atomicity concerns (reasoning + spurious + recalibration in one logical operation), which is why coordinator adoption there was high-value. Discovery and retrospective don't share that characteristic.
- The coordinator adds provenance metadata (`_write_group_id`, `_source_workflow`), which is useful but not urgent for these two write paths. Their provenance is already implicitly clear from the file they land in.
- Addressing this would add complexity to `retrospective_builder.py` and the discovery handler for marginal reliability gain, when the priority should be on making the card and memory layer semantically correct first (Findings 1–4).

### Finding 6 — Not addressed (correctly deferred)

**Full Hermes-style learning orchestrator capabilities (unified budget, retrieval feedback, RunIndex.search consumers, bot-scoped corrections).**

Rationale for deferral:
- The audit document itself explicitly recommends this ordering: fix card/source semantics first (Findings 1–4), widen source coverage second, then revisit unified budgeting and retrieval feedback.
- Findings 1–4 were prerequisite: there is limited value in learning retrieval feedback from cards whose source normalization was still wrong, or in building unified budgets over sources that weren't yet ingested.
- Now that Findings 1–4 are resolved, these capabilities become the natural next tier. But they represent new feature work (adding callers for `RunIndex.search()`, implementing `record_feedback()` consumers, adding `context_budget_tokens` to production call sites), not bug fixes.
- The practical next step is to let the corrected card layer run in production, observe whether the ranked cards are actually useful in prompts, and then decide which of these capabilities has the highest marginal value.

### Test verification

- 79 targeted tests pass (all files touched by the fixes)
- 3379 full suite tests pass (3 pre-existing flaky async tests in `test_handler_progress.py` excluded — race condition in progress stage assertions, unrelated to these changes)
