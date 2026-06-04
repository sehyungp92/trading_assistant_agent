# Hermes/AutoAgent Leverage Report — Evaluation & Implementation Plan

## Context

The report at `docs/2026-04-22-hermes-autoagent-learning-loop-leverage-report.md` evaluates how ideas from `_references/hermes-agent/` and `_references/autoagent/` can improve the trading assistant's learning feedback loop. After thorough codebase validation (reading 20+ source files, tracing full data flows), the report's analysis is largely accurate but overstates some gaps and understates existing infrastructure in specific areas. This plan implements the valid high-value improvements and explains why others are deferred.

---

## Recommendation Evaluation

### Rec 1: Failure-to-Benchmark Compiler — VALID, IMPLEMENT

The report correctly identifies that no **harness-level** benchmark suite exists. The codebase has strong **trade-level** evaluators (`GroundTruthComputer`, `BacktestSimulator`, `ParameterSearcher`) but nothing that evaluates whether the analysis harness itself (prompts, retrieval, validators, routing) is improving over time. Learning artifacts are rich (outcomes.jsonl, validation_log.jsonl, recalibrations.jsonl, transfer_outcomes.jsonl) but stay attached to their local workflows — they never become a unified regression corpus.

### Rec 2: AutoAgent Harness Improvement Loop — VALID, DEFER

Correct concept but premature. Requires accumulated benchmark data from Rec 1. Cannot A/B test harness variants without a benchmark corpus. **Prerequisite: Rec 1 operational for several weeks.**

### Rec 3: Query-Aware Decision-Memory Router — PARTIALLY VALID

Two concrete gaps confirmed:

**Gap A — Retrieval feedback is inoperative**: `LearningCard` has `helpful_count`/`harmful_count` fields (schema line 76-77) and `LearningCardIndex.record_feedback()` exists (line 232-241), both used in `relevance_score()` at 15% weight (line 155). But `record_feedback()` is **never called in production**. The `record_retrieval()` call in `context_builder.py:1604` increments `retrieval_count`, but the feedback factor always returns 0.5 neutral because `helpful_count + harmful_count` is always 0. **IMPLEMENT.**

**Gap B — RunIndex not integrated with prompts**: `RunIndex` (run_index.py) has full FTS5 over runs with `search()` and `get_recent_runs()` methods, and already stores provider/model/bot_ids. But `ContextBuilder.__init__` (context_builder.py:103) only accepts `memory_dir` and `curated_dir` — no `run_index`. None of the 6 assemblers or the handler-level ContextBuilder instances pass RunIndex. **IMPLEMENT (merged with Rec 6).**

However, the "full decision-memory router" framing is over-engineered. `base_package()` already has workflow-specific priorities (`_WORKFLOW_PRIORITIES`, 5 workflow-specific orderings at lines 1244-1349), adaptive token budgeting (lines 1542-1555), and 5-factor learning card ranking via `relevance_score()`. The concrete fixes (operationalize feedback, wire RunIndex) are sufficient without a new abstraction.

### Rec 4: Outcome-Conditioned Provider Routing — VALID, MINIMAL IMPL

Provider selection is confirmed 100% static config (`AgentPreferencesManager`). `AgentResult` captures provider/runtime/model but downstream artifacts don't record which provider produced them: validation_log.jsonl entries (handlers.py:2003-2008), `detection_context` in suggestion records (handlers.py:2618), and `OutcomeMeasurement` schema all lack provider fields.

**IMPLEMENT minimal**: Add provider attribution to validation log entries and suggestion detection_context so future analysis is possible. Skip the routing engine — likely single provider in use.

### Rec 5: Controlled Playbook Generation — LOW VALUE, SKIP

The report's claim "no playbook generation" is inaccurate. The system already has:
- `memory/skills/` with 6 markdown instruction files per agent type (daily_analysis.md, weekly_summary.md, strategy_refinement.md, wfo_pipeline.md, bug_triage.md, skills_index.md)
- `FileChangeGenerator` + `ExperimentConfigGenerator` for automated change proposals
- `LearningCardStore` with 10 card type factories (`card_from_correction`, `card_from_outcome`, `card_from_validator_block`, `card_from_retrospective`, etc.) that convert learning artifacts into retrievable lessons
- `HypothesisLibrary` with JSONL-backed lifecycle tracking and auto-retirement
- `PatternLibrary` for cross-bot pattern storage and retrieval

Generated playbooks would add complexity and maintenance burden for marginal benefit. The learning card system already captures reusable patterns with provenance tracking.

### Rec 6: Trajectory Search and Replay — VALID, MERGED WITH REC 3

`RunIndex` has FTS5 search, stores provider/model/bot_ids/response_preview, and supports filtered queries. But it's not used during prompt assembly. **Merged into Item 3 below.**

### Rec 7: Bounded Hot Memory — LOW PRIORITY, SKIP

The report itself ranks this medium-low. Existing learning cards, session history, and findings serve similar needs.

---

## Implementation Plan

### Item 1: Operationalize Learning Card Retrieval Feedback

**Problem**: `record_feedback(card_id, helpful)` on `LearningCardIndex` (learning_card.py:232-241) exists and `relevance_score()` uses the feedback factor at 15% weight (line 120-127), but no production code calls `record_feedback()`. Cards always score 0.5 neutral on the feedback factor, defeating adaptive ranking.

**Approach**: After `_validate_and_annotate()` runs in the handler, use the validation pass rate (approved vs blocked suggestions) as a proxy signal. The `_learning_card_ids` are already stored in `package.metadata` by `base_package()` (context_builder.py:1607).

**Files to modify**:

**`orchestrator/handlers.py`** — Add new private method + 2 call sites:

```python
def _record_learning_card_feedback(
    self, validation_result, prompt_package,
) -> None:
```

Logic:
- Extract `_learning_card_ids` from `prompt_package.metadata` — this is a `list[str]` of card IDs set by `base_package()` at context_builder.py:1607
- If no card_ids or validation_result is None: return (no-op)
- Count `len(validation_result.approved_suggestions)` and `len(validation_result.blocked_suggestions)` — these are `list[AgentSuggestion]` and `list[BlockedSuggestion]` respectively (response_validator.py:38-39)
- If total (approved + blocked) == 0: return
- approval_rate = approved / total
- If approval_rate >= 0.5: helpful=True for all cards
- If approval_rate <= 0.25 (75%+ blocked): helpful=False for all cards
- Otherwise: no feedback (preserve neutral)
- Instantiate `LearningCardStore(self._memory_dir / "findings")`, call `.load()` to get `LearningCardIndex`, call `index.record_feedback(card_id, helpful)` for each card_id, then `store.save(index)`. This follows the existing pattern at context_builder.py:1604-1605.

Call sites — both `package` and `validation` are in scope:
1. **`handle_daily_analysis`** after line 311 (`_record_agent_suggestions`): `self._record_learning_card_feedback(validation, package)` — `package` defined at line 256, `validation` at line 299
2. **`handle_weekly_analysis`** after line 925 (`_record_agent_suggestions`): `self._record_learning_card_feedback(validation, package)` — `package` defined at line 646, `validation` at line 912

**Tests**: `tests/test_learning_card_feedback.py` (~8 tests)
- helpful when majority approved (3 approved / 1 blocked → helpful)
- harmful when majority blocked (1 approved / 4 blocked → harmful)
- no feedback when mixed (2/2 → neutral, counts unchanged)
- no-op when no card_ids in metadata
- no-op when validation_result is None
- no-op when zero total suggestions
- feedback persists through save/load cycle
- `relevance_score()` changes with accumulated feedback (card with helpful_count=5, retrieval_count=6 scores higher than default)

---

### Item 2: Provider Attribution in Validation Logs & Suggestion Records

**Problem**: `AgentResult` (agent_runner.py:40-55) has `provider`, `effective_model`, `runtime`, `auth_mode` fields. But the validation log entry dict (handlers.py:2003-2008) and suggestion `detection_context` dict (handlers.py:2618) don't include which provider produced the analysis.

**Files to modify**:

**`orchestrator/handlers.py`**:

1. **`_validate_and_annotate` (line 1950)**: Add `provider: str = ""`, `model: str = ""` params. Include in log entry dict at line 2003:
   ```python
   entry = {
       "date": date_or_week,
       "approved_count": len(validation.approved_suggestions),
       "blocked_count": len(validation.blocked_suggestions),
       "blocked_details": blocked_details,
       "provider": provider,
       "model": model,
       "timestamp": datetime.now(timezone.utc).isoformat(),
   }
   ```

2. **`_record_agent_suggestions` (line 2522)**: Add `provider: str = ""`, `model: str = ""` params. Add to `detection_ctx` dict at line 2618:
   ```python
   detection_ctx = {}
   if provider:
       detection_ctx["source_provider"] = provider
   if model:
       detection_ctx["source_model"] = model
   if validation_evidence:
       detection_ctx["validation_evidence"] = validation_evidence
   ```

3. **Call sites** — `result` (AgentResult) is in scope at both:
   - `handle_daily_analysis` line 299: `self._validate_and_annotate(parsed, date, provider=result.provider, model=result.effective_model)`
   - `handle_daily_analysis` line 311: `self._record_agent_suggestions(validation, run_id, parsed, provider=result.provider, model=result.effective_model)`
   - `handle_weekly_analysis` line 912: same pattern
   - `handle_weekly_analysis` line 925: same pattern

**`schemas/outcome_measurement.py`** — Add two optional fields to `OutcomeMeasurement` (after line 67):
```python
source_provider: str = ""
source_model: str = ""
```
Backward compatible — existing JSONL entries will deserialize with empty defaults.

**Tests**: `tests/test_provider_attribution.py` (~6 tests)
- validation_log entry includes provider/model when passed
- validation_log entry has empty strings when not passed (backward compat)
- detection_context includes source_provider/source_model
- OutcomeMeasurement accepts and serializes provider fields
- round-trip: model_dump_json → model_validate_json preserves fields

---

### Item 3: RunIndex Integration in Context Building

**Problem**: `RunIndex` (run_index.py) has FTS5 search over responses, instructions, validator notes, and structured output. It already stores provider/model/bot_ids per run. But `ContextBuilder.__init__` (context_builder.py:103) doesn't accept `run_index`, and none of the 12+ `ContextBuilder()` instantiation sites pass it. Claude cannot learn from how similar situations were handled in past analyses.

**ContextBuilder instantiation sites** (all must remain working — `run_index` defaults to `None`):
- `analysis/prompt_assembler.py:259` (DailyPromptAssembler)
- `analysis/weekly_prompt_assembler.py:290` (WeeklyPromptAssembler)
- `analysis/discovery_prompt_assembler.py:158`
- `analysis/outcome_reasoning_prompt.py:76`
- `analysis/triage_prompt_assembler.py:34`
- `analysis/wfo_prompt_assembler.py:41`
- `orchestrator/handlers.py:211, 618, 775, 1960` (handler-level loads)
- `orchestrator/app.py:2103`
- Tests (many)

**Approach**: Add `run_index` as optional param to `ContextBuilder.__init__`. Add `load_similar_runs()` method. Wire through only the daily + weekly assemblers initially (highest impact). Handler-level ContextBuilder instances (used for loading validation data, not prompt assembly) don't need it.

**Files to modify**:

1. **`analysis/context_builder.py`**:
   - `__init__` (line 103): Add `run_index: object | None = None` param, store as `self._run_index`
   - Add new method:
     ```python
     def load_similar_runs(
         self, agent_type: str = "", bot_id: str = "",
         limit: int = 5, days: int = 60,
     ) -> list[dict]:
     ```
     - If `self._run_index is None`: return `[]`
     - Call `self._run_index.get_recent_runs(agent_type=agent_type, limit=limit, days=days)`
     - Return compact dicts: `{run_id, date, agent_type, provider, snippet[:200]}`
     - Wrap in try/except returning `[]` on failure
   - In `base_package()` after session_history loading (after line 1505): if `self._run_index` is set, call `load_similar_runs(agent_type=agent_type, bot_id=bot_id)` and inject into `data["similar_past_runs"]`

2. **`analysis/prompt_assembler.py`** (DailyPromptAssembler):
   - `__init__`: Add `run_index: object | None = None` param
   - Pass to `ContextBuilder(memory_dir, curated_dir=curated_dir, run_index=run_index)`

3. **`analysis/weekly_prompt_assembler.py`** (WeeklyPromptAssembler):
   - Same pattern as daily assembler

4. **`orchestrator/handlers.py`**:
   - `__init__` (line 41): Add `run_index: object | None = None` param, store as `self._run_index`
   - When creating `DailyPromptAssembler` (line 248): pass `run_index=self._run_index`
   - When creating `WeeklyPromptAssembler` (line ~640): pass `run_index=self._run_index`

5. **`orchestrator/app.py`**:
   - `Handlers()` call (line 578): Add `run_index=run_index` — the `run_index` variable already exists at line 321

**Tests**: `tests/test_run_index_context.py` (~7 tests)
- `load_similar_runs` returns results from indexed runs
- `load_similar_runs` filters by agent_type
- `run_index=None` returns empty list (graceful degradation)
- `similar_past_runs` key appears in base_package data when run_index is set
- snippets truncated to 200 chars (no large payloads)
- exception in RunIndex doesn't crash base_package (returns partial data)
- backward compat: all existing ContextBuilder instantiations still work

---

### Item 4: Benchmark Case Schema + Minimal Compiler

**Problem**: No infrastructure to compile the system's learning signals into a regression test corpus for the analysis harness. Negative outcomes, repeated blocks, and calibration misses are recorded but never unified into reusable evaluation cases.

**JSONL sources verified** (actual field names from schemas):
- **`outcomes.jsonl`**: `OutcomeMeasurement.model_dump_json()` — fields: `suggestion_id`, `implemented_date`, `measurement_date`, `pnl_delta` (computed), `verdict` (computed: positive/negative/neutral/inconclusive/insufficient_data), `measurement_quality` (high/medium/low/insufficient) — written in app.py:974-977
- **`validation_log.jsonl`**: raw dicts — fields: `date`, `approved_count`, `blocked_count`, `blocked_details` (list of {title, reason, bot_id}), `timestamp` — written in handlers.py:2003-2011
- **`recalibrations.jsonl`**: written via LearningWriteCoordinator — fields include `suggestion_id`, `revised_confidence`, `original_confidence`, `lessons_learned`
- **`transfer_outcomes.jsonl`**: written by TransferProposalBuilder — fields: `pattern_id`, `target_bot`, `source_bot`, `verdict`, `pnl_delta_7d`, `win_rate_delta_7d`, `regime_matched`

**Note on predictions.jsonl**: Contains raw `PredictionRecord` entries (bot_id, metric, direction, confidence, week) but NOT evaluation verdicts. `PredictionTracker.evaluate_predictions()` produces `PredictionEvaluation` objects transiently (logged at app.py:1056 but not persisted to JSONL). Therefore `_compile_prediction_misses` cannot read evaluated verdicts from disk. **Use `forecast_history.jsonl` for weekly-level accuracy misses instead**, or skip this source initially.

**Files to create**:

1. **`schemas/benchmark_case.py`** (~65 lines):
   - `BenchmarkSource` enum: `VALIDATION_BLOCK`, `NEGATIVE_OUTCOME`, `CALIBRATION_MISS`, `TRANSFER_FAILURE`
   - `BenchmarkSeverity` enum: `CRITICAL`, `HIGH`, `MEDIUM`, `LOW`
   - `BenchmarkCase(BaseModel)`: `case_id` (deterministic SHA256 from `f"{source.value}:{source_id}"`, truncated to 16 chars), `source`, `source_id`, `severity`, `bot_id`, `agent_type`, `date`, `title`, `description`, `expected_behavior`, `actual_behavior`, `provider`, `model`, `created_at`, `input_snapshot: dict`, `output_snapshot: dict`
   - `BenchmarkSuite(BaseModel)`: `cases: list[BenchmarkCase]`, `compiled_at`, `source_summary: dict`

2. **`skills/benchmark_compiler.py`** (~180 lines):
   - `BenchmarkCompiler(findings_dir: Path)`
   - `compile(lookback_days=90) -> BenchmarkSuite` — runs all sub-compilers, deduplicates by case_id
   - `compile_and_save(lookback_days=90) -> int` — appends new cases to `benchmark_cases.jsonl`, skips existing IDs (idempotent)
   - `_compile_validation_blocks(cutoff)` — reads `validation_log.jsonl`, filters entries with `blocked_count / (approved_count + blocked_count) >= 0.75` AND total >= 4. Severity: HIGH
   - `_compile_negative_outcomes(cutoff)` — reads `outcomes.jsonl`, filters entries where `verdict == "negative"` AND `measurement_quality in ("high", "medium")`. Severity: CRITICAL
   - `_compile_calibration_misses(cutoff)` — reads `recalibrations.jsonl`, filters entries where `abs(revised_confidence - original_confidence) >= 0.3`. Severity: MEDIUM. (Uses field names from actual recalibrations schema)
   - `_compile_transfer_failures(cutoff)` — reads `transfer_outcomes.jsonl`, filters entries where `verdict == "negative"`. Severity: HIGH
   - Helpers: `_load_jsonl(filename) -> list[dict]`, `_load_existing_ids(path) -> set[str]`, `_parse_ts(entry) -> datetime | None` (tries "timestamp", "created_at", "recorded_at", "measurement_date")
   - Prediction misses deferred — `predictions.jsonl` lacks persisted verdicts

**Tests**: `tests/test_benchmark_compiler.py` (~12 tests)
- Empty findings → empty suite
- compile_validation_blocks: high block rate → case created
- compile_validation_blocks: low total (2 suggestions) → skipped
- compile_negative_outcomes: NEGATIVE verdict → CRITICAL case
- compile_negative_outcomes: LOW quality measurement → skipped
- compile_calibration_misses: large delta → case created
- compile_calibration_misses: small delta (0.1) → skipped
- compile_transfer_failures: negative transfer → case created
- Dedup by case_id (same source data → no duplicates)
- compile_and_save incremental (existing cases not re-written)
- Deterministic case_id (same inputs → same hash)
- Lookback days filter (old entries excluded)

---

## Implementation Order

1. **Item 2** (Provider Attribution) — smallest scope, pure additions (new params + dict keys), fully backward compatible. Sets up data for Items 3 and 4.
2. **Item 1** (Retrieval Feedback) — self-contained, reuses existing `LearningCardStore`/`LearningCardIndex` APIs, no schema changes.
3. **Item 4** (Benchmark Compiler) — all new files, zero modifications to existing code. Clean TDD.
4. **Item 3** (RunIndex Context) — most wiring touchpoints (context_builder, 2 assemblers, handlers, app.py). Done last because it touches the most files.

## Verification

1. Run full test suite: `pytest tests/` — all 3154 existing tests must pass
2. Run each new test file: `pytest tests/test_provider_attribution.py tests/test_learning_card_feedback.py tests/test_benchmark_compiler.py tests/test_run_index_context.py -v`
3. Verify backward compatibility: import handlers, context_builder, and assemblers with existing signatures — no TypeError
4. Verify schema compat: `OutcomeMeasurement(suggestion_id="x", implemented_date="2026-01-01", measurement_date="2026-01-08")` still works without provider fields
