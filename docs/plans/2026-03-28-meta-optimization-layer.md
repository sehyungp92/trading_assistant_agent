# Plan: Meta-Optimization Layer — Close Genuine Learning Loop Gaps

## Status: COMPLETED (2026-03-28)

## Context

The assessment in `docs/2026-03-28-learning-loop-integration-assessment.md` contained **major errors** about "missing" features that actually exist:

| Claimed Missing | Actually Exists |
|----------------|-----------------|
| Post-cycle diagnostic synthesis | `RetrospectiveBuilder.build_synthesis()` in `skills/retrospective_builder.py` |
| Experiment design mechanism | `LearningCycle._select_next_experiments()` in `skills/learning_cycle.py` |
| Inner/outer loop indistinguishable | Distinguishable via `detection_context.detector_name` (inner) vs `implementation_context` (outer) |
| Experiment evaluation not wired | `_check_experiments()` in `app.py:1278` — auto-concludes, feeds hypothesis library |

After correcting these errors, **5 genuine gaps remained** that prevent the learning loops from functioning as a coherent greedy optimization:

1. **Cycle effectiveness score** — no single metric to compare cycle N vs N-1
2. **Exploration-exploitation balance** — categories with 0 suggestions are invisible
3. **Loop source attribution** — nobody aggregates inner vs outer counts/outcomes
4. **Experiment failure blacklist** — `_select_next_experiments()` doesn't skip failed hypothesis+bot combos
5. **Suggestion quality trend** — no tracking of whether suggestion generation is improving

---

## Task 0: Correct Assessment Document

**File**: `docs/2026-03-28-learning-loop-integration-assessment.md`

Updated sections 3.1-3.4 to acknowledge what exists and reframe the genuine gaps accurately. Removed false claims, added corrected findings.

---

## Task 1: Cycle Effectiveness Score (HIGH)

**Problem**: `LearningLedgerEntry` has `net_improvement` (bool) and `composite_delta` (dict), but no normalized metric to compare cycle quality over time.

**Files modified**:
- `schemas/learning_ledger.py` — added `cycle_effectiveness: float = 0.0` to `LearningLedgerEntry`
- `skills/learning_ledger.py` — added `compute_cycle_effectiveness()` method + `_compute_week_outcome_quality()` helper; updated `record_week()` to accept and store the field
- `skills/learning_cycle.py` — calls `compute_cycle_effectiveness()` before `ledger.record_week()`, passes result
- `analysis/context_builder.py` — added `load_cycle_effectiveness()` loader reading last 8 ledger entries, injected into `base_package()` after convergence_report; added to `_CONTEXT_PRIORITY`
- `analysis/weekly_prompt_assembler.py` — added `## CYCLE EFFECTIVENESS TREND` instruction section

**Formula** (4 equal-weight components, 0.0-1.0):
- `improvement_magnitude`: sigmoid(mean(composite_delta values) × 10) → maps any range to [0,1]
- `conversion_rate`: implemented / max(proposed, 1)
- `outcome_quality`: positive_outcomes / max(total_outcomes, 1) for that week (from outcomes.jsonl)
- `lesson_yield`: min(1.0, len(lessons) / 5)

---

## Task 2: Exploration-Exploitation Balance (HIGH)

**Problem**: `compute_category_value_map()` silently ignores categories with 0 suggestions. System gets stuck optimizing known-good categories.

**Files modified**:
- `skills/suggestion_scorer.py` — defined `_NON_PORTFOLIO_CATEGORIES` frozenset from `CATEGORY_TO_TIER` keys (excluding portfolio_* categories); modified `compute_category_value_map()` to add `unexplored=True` entries for bot:category combos with no data; added recommendation for unexplored categories
- `analysis/strategy_engine.py` — in `build_report()` value-per-suggestion adjustment loop, skip (neutral treatment) entries with `unexplored=True` instead of penalizing

**Known categories** (from `schemas/agent_response.py:59-71`): exit_timing, filter_threshold, stop_loss, signal, structural, position_sizing, regime_gate (7 non-portfolio)

---

## Task 3: Loop Source Attribution (MEDIUM)

**Problem**: Nobody aggregates how many suggestions/outcomes came from each loop. Can't tell which loop is contributing more.

**Files modified**:
- `schemas/learning_ledger.py` — added 6 fields to `LearningLedgerEntry`: `inner_suggestions_proposed`, `outer_suggestions_proposed`, `inner_positive_outcomes`, `outer_positive_outcomes`, `inner_total_outcomes`, `outer_total_outcomes` (all `int = 0`)
- `skills/learning_ledger.py` — updated `record_week()` to accept 6 new params
- `skills/learning_cycle.py` — added `classify_suggestion_source()` static method (checks `detection_context.detector_name` → "inner", else → "outer"); added `_classify_loop_sources()` method; passes counts to `ledger.record_week()`
- `skills/convergence_tracker.py` — added `_check_loop_balance()` as 5th dimension in `compute_report()`; reads ledger entries, computes combined positive outcome rate per week, runs `_classify_trend()`

---

## Task 4: Experiment Failure Blacklist (HIGH — small scope)

**Problem**: `_select_next_experiments()` skips discarded categories but doesn't skip hypothesis+bot combos that already failed an experiment. Can re-test failed hypotheses.

**Files modified**:
- `skills/structural_experiment_tracker.py` — added `get_failed_experiments()` method returning FAILED/ABANDONED records
- `skills/learning_cycle.py` — in `_select_next_experiments()`, loads failed experiments, builds `failed_combos: set[tuple[str, str]]` of (hypothesis_id, bot_id), skips those in the inner loop

---

## Task 5: Suggestion Quality Trend (MEDIUM)

**Problem**: No tracking of whether suggestion generation quality is improving over time.

**Files modified**:
- `skills/suggestion_scorer.py` — added `compute_suggestion_quality_trend(weeks=8)` method computing per-week: hit_rate (positive/implemented), high_value_ratio (top-3 categories/total); returns weekly metrics + 4-week rolling avg + trend
- `analysis/context_builder.py` — added `load_suggestion_quality_trend()` loader, injected into `base_package()`, added to `_CONTEXT_PRIORITY`
- `analysis/weekly_prompt_assembler.py` — added `## SUGGESTION QUALITY TREND` instruction section

---

## Implementation Order (as executed)

```
Task 0 (assessment correction)
  ↓
Task 1 (cycle effectiveness) + Task 4 (experiment blacklist)  ← parallel
  ↓
Task 2 (exploration-exploitation)
  ↓
Task 3 (loop source attribution) + Task 5 (suggestion quality trend)  ← parallel
```

## Post-Implementation Review Fixes

During code review, the following issues were found and fixed:

1. **Bug: Dead code** in `learning_cycle.py:134-135` — variables initialized then immediately overwritten. Removed the dead initializations.

2. **Bug: Import style** in `learning_ledger.py:12` — `import math` separated from stdlib group by blank line. Moved into proper position.

3. **Bug: Inconsistent positive detection** in `_compute_week_outcome_quality()` — only checked `verdict == "positive"`, while `_is_positive()` everywhere else also handles legacy `pnl_delta` fallback. Added `_is_positive()` static method to `LearningLedger` consistent with other scorers.

4. **Bug: Redundant computation** in `compute_suggestion_quality_trend()` — called `self.compute_category_value_map()` internally, re-loading all data that was already loaded. Added `value_map` parameter to accept pre-computed map; `ContextBuilder.load_suggestion_quality_trend()` passes `optimization_allocation` through.

5. **Bug (pre-existing): composite_delta type mismatch** in `ConvergenceTracker._check_composite_scores()` — treated `composite_delta` as scalar float, but schema defines it as `dict[str, float]` (bot_id → delta). In production JSONL, this would crash `_classify_trend()`. Fixed to handle both dict (aggregate to mean) and scalar (legacy) formats. Updated test to use dict form matching production shape.

## Tests

Added to existing test files:
- `tests/test_learning_loop_gaps.py`: 11 tests (convergence loop_balance dimension, cycle effectiveness, loop source classification, experiment blacklist)
- `tests/test_loop_feedback_quality.py`: 9 tests (exploration-exploitation balance, suggestion quality trend, weekly instruction sections)

Total: 20 new tests across 2 existing test files. **91 tests in these files, 3045 total — all passing.**

## Files Changed Summary

| File | Change Type |
|------|-------------|
| `schemas/learning_ledger.py` | 7 new fields on `LearningLedgerEntry` |
| `skills/learning_ledger.py` | `compute_cycle_effectiveness()`, `_compute_week_outcome_quality()`, `_is_positive()`, extended `record_week()` |
| `skills/learning_cycle.py` | `classify_suggestion_source()`, `_classify_loop_sources()`, experiment blacklist in `_select_next_experiments()`, steps 7-8 in `run()` |
| `skills/suggestion_scorer.py` | `_NON_PORTFOLIO_CATEGORIES`, unexplored entries in `compute_category_value_map()`, `compute_suggestion_quality_trend()` |
| `skills/convergence_tracker.py` | `_check_loop_balance()` 5th dimension, fixed `_check_composite_scores()` dict handling |
| `skills/structural_experiment_tracker.py` | `get_failed_experiments()` |
| `analysis/context_builder.py` | `load_cycle_effectiveness()`, `load_suggestion_quality_trend()`, both in `base_package()` and `_CONTEXT_PRIORITY` |
| `analysis/strategy_engine.py` | Neutral treatment for `unexplored` categories in optimization allocation |
| `analysis/weekly_prompt_assembler.py` | `CYCLE EFFECTIVENESS TREND` + `SUGGESTION QUALITY TREND` instruction sections |
| `docs/2026-03-28-learning-loop-integration-assessment.md` | Corrected false claims, reframed genuine gaps |
| `tests/test_learning_loop_gaps.py` | 11 new tests |
| `tests/test_loop_feedback_quality.py` | 9 new tests |
