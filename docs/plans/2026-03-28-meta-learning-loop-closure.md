# Meta-Learning Loop Closure: Hermes-Inspired Self-Improvement

## Context

Hermes-agent's core meta-learning insight: **procedural memory that self-patches based on experience**. The trading assistant has extensive learning infrastructure but **four feedback loops were broken or incomplete**, preventing the system from fully learning from its own performance. Data was collected and stored but either never read back, never synthesized into actionable lessons, or missing entirely.

---

## Gap 1 (P0): Recalibrations Written But Never Consumed — BROKEN LOOP

**Problem**: `orchestrator/app.py:1144-1156` writes `recalibrations.jsonl` with `{suggestion_id, revised_confidence, lessons_learned, recorded_at}` from causal outcome reasoning. Neither `ContextBuilder` nor `ResponseValidator` ever reads this file. Zero grep hits for `load_recalibrations` in analysis/.

**Additional finding**: The recalibration records lacked `bot_id` and `category`. The `OutcomeMeasurement` schema also lacks these fields. But the `deployed` suggestion list in `_measure_outcomes()` (line 940) has both via `s.get("bot_id")` and `s.get("category")`. The reasoning loop (line 1113) processes outcomes by `suggestion_id` but had no access to the deployed list context.

### Changes Made

**`orchestrator/app.py`** (~line 1050, before reasoning loop): Built suggestion lookup from `deployed`:
```python
suggestion_lookup = {s.get("suggestion_id", ""): s for s in deployed}
```

At ~line 1149, enriched recalibration writes:
```python
sugg_rec = suggestion_lookup.get(sid, {})
_rf.write(_json.dumps({
    "suggestion_id": sid,
    "bot_id": sugg_rec.get("bot_id", ""),
    "category": sugg_rec.get("category", ""),
    "revised_confidence": revised,
    "lessons_learned": r.get("lessons_learned", []),
    "recorded_at": datetime.now(timezone.utc).isoformat(),
}) + "\n")
```

**`analysis/context_builder.py`**: Added `load_recalibrations()`:
- Reads `memory/findings/recalibrations.jsonl`
- Applies `_apply_temporal_window()` (90d, 30-entry cap)
- Returns `list[dict]`
- Wired into `base_package()` after `outcome_reasonings`
- Added `"recalibrations"` to `_CONTEXT_PRIORITY` after `"outcome_reasonings"`

**`analysis/response_validator.py`**:
- `__init__()`: Accepts `recalibrations: list[dict] | None = None`. Builds index `_recalib_by_key: dict[tuple[str,str], float]` grouping by `(bot_id, category)` → `mean(revised_confidence)`.
- `_apply_calibration()`: Before bucket/heuristic adjustment, checks for recalibration match:
  ```python
  recalib_conf = self._recalib_by_key.get((suggestion.bot_id, suggestion.category))
  if recalib_conf is not None:
      confidence = confidence * 0.6 + recalib_conf * 0.4
  ```

**`orchestrator/handlers.py`** `_validate_and_annotate()`: Loads and passes recalibrations:
```python
recalibrations = ctx.load_recalibrations()
validator = ResponseValidator(
    ...,
    recalibrations=recalibrations,
)
```

### Files
- `orchestrator/app.py` — suggestion_lookup dict + enrich recalibration writes
- `analysis/context_builder.py` — `load_recalibrations()` + `base_package()` wiring
- `analysis/response_validator.py` — `__init__()` + `_apply_calibration()` consumption
- `orchestrator/handlers.py` — `_validate_and_annotate()` wiring

---

## Gap 2 (P1): Directional Bias Detection — MISSING SELF-AWARENESS

**Problem**: `PredictionTracker` has per-prediction `direction` field and `_classify_direction()` with noise thresholds, but never aggregates direction distributions. No detection of systematic optimism/pessimism. Zero grep hits for `directional_bias` in codebase. `ForecastMetaAnalysis` had no bias-related fields.

**Existing infrastructure reused**:
- `PredictionTracker._classify_direction(actual, metric)` — noise thresholds already implemented
- `PredictionTracker.evaluate_predictions(week, curated_dir)` — loads actuals for comparison
- `PredictionRecord.direction` field — stores predicted direction per prediction

### Changes Made

**`skills/prediction_tracker.py`**: Added `compute_directional_bias(curated_dir, lookback_weeks=12)`:
- Loads all predictions, groups by metric
- For each prediction: uses existing `_classify_direction()` to get actual direction
- Counts `predicted_improve` vs `actual_improve` per metric
- Classifies: `gap > 0.15` → `"optimistic"`, `gap < -0.15` → `"pessimistic"`, else `"balanced"`
- Returns `{metric: {predicted_improve_pct, actual_improve_pct, bias, bias_magnitude, sample_size}}`
- Minimum `sample_size >= 5` per metric to report

**`schemas/forecast_tracking.py`**: Added to `ForecastMetaAnalysis`:
```python
directional_bias: dict[str, dict] = {}
```

**`skills/forecast_tracker.py`**: `compute_meta_analysis()` accepts and passes through `directional_bias` parameter.

**`analysis/context_builder.py`**: `load_forecast_meta()` computes directional bias via PredictionTracker when curated_dir is available. Flows automatically through the existing ForecastMetaAnalysis dict.

**`analysis/prompt_assembler.py`** + **`analysis/weekly_prompt_assembler.py`**: Added after "YOUR PREDICTION TRACK RECORD" section:
```
## DIRECTIONAL BIAS AWARENESS
If forecast_meta_analysis contains directional_bias data:
- "optimistic" bias: you predict improvement more than reality — reduce improve predictions
- "pessimistic" bias: you predict decline more than reality — consider improve scenarios
- Acknowledge your bias before making predictions in affected metrics
```

### Files
- `skills/prediction_tracker.py` — `compute_directional_bias()` method
- `schemas/forecast_tracking.py` — `directional_bias` field
- `skills/forecast_tracker.py` — wire into `compute_meta_analysis()`
- `analysis/prompt_assembler.py` — instruction text
- `analysis/weekly_prompt_assembler.py` — instruction text

---

## Gap 3 (P2): Correction Pattern → Lesson Synthesis — MISSING LESSON EXTRACTION

**Problem**: `CorrectionPatternExtractor` is already called in `handlers.py:716-732`. It extracts patterns from corrections.jsonl and persists them to `correction_patterns.jsonl`. These patterns are loaded into prompts via `ContextBuilder.load_correction_patterns()`. **But**: patterns were never synthesized into learning ledger lessons, so they didn't benefit from the ledger's temporal decay, outcome boosting, and curated notes pipeline. Recurring corrections stayed as raw pattern data — they didn't evolve into persistent wisdom.

### Changes Made

**`orchestrator/handlers.py`**: After the existing correction pattern extraction block (line 732), added lesson synthesis:
```python
# Synthesize persistent correction patterns into learning ledger lessons
try:
    from skills.learning_ledger import LearningLedger as _LL
    correction_lessons = []
    for p in pattern_report.patterns[:5]:
        if p.count >= 3:  # Only persistent patterns
            correction_lessons.append(
                f"[correction] {p.description}. "
                f"Adjust analysis approach for {target}."
            )
    if correction_lessons:
        _corr_ledger = _LL(self._memory_dir / "findings")
        _corr_ledger.record_outcome_lessons(week_start, correction_lessons)
except Exception:
    logger.debug("Correction lesson synthesis failed")
```

Uses existing `LearningLedger.record_outcome_lessons()` with `[correction]` prefix. The ledger's Jaccard dedup (0.6 threshold) prevents duplicates across weeks. The curated notes pipeline's 5%/week decay naturally fades stale corrections.

### Files
- `orchestrator/handlers.py` — ~10 lines after line 732

---

## Gap 4 (P3): Synthesized Self-Assessment — MISSING SELF-KNOWLEDGE

**Problem**: The agent sees 12+ separate data sources about its past performance (accuracy, scorecard, corrections, outcomes, etc.) but no synthesized summary. Each invocation, the agent must independently re-derive "I'm optimistic about PnL, weak at exit_timing for bot_X, and keep getting regime wrong" from scattered raw data. No grep hits for `self_assessment` anywhere.

**Depends on**: Gap 1 (recalibrations) and Gap 2 (directional bias) for complete data.

### Changes Made

**`analysis/context_builder.py`**: Added `build_self_assessment()` → `str`:
1. **Directional biases** from `load_forecast_meta()` → `directional_bias`
2. **Calibration state** from `load_forecast_meta()` → ECE, overconfident/underconfident
3. **Category strengths/weaknesses** from `load_category_scorecard()` → win_rate >= 0.6 (strong), < 0.4 (weak), with sample_size >= 3
4. **Recurring corrections** from `load_correction_patterns()` → top 3 patterns by count
5. **Causal lessons** from `load_recalibrations()` → deduplicated lessons_learned

Returns plain-text narrative. Empty string if insufficient data (< 2 signals available).

In `base_package()`: added `data["self_assessment"]`. Added `"self_assessment"` to `_CONTEXT_PRIORITY` at position 4 (high priority — after ground_truth_trend, portfolio data).

**`analysis/prompt_assembler.py`** + **`analysis/weekly_prompt_assembler.py`**: Added instruction:
```
## SELF-ASSESSMENT
If self_assessment data is present, READ IT CAREFULLY. This summarizes your known
biases, weak categories, and recurring mistakes. You MUST:
- Acknowledge biases before making predictions in affected metrics
- Avoid or explicitly justify suggestions in weak categories
- Not repeat patterns listed in recurring corrections
```

### Files
- `analysis/context_builder.py` — `build_self_assessment()` + `base_package()` wiring
- `analysis/prompt_assembler.py` — instruction text
- `analysis/weekly_prompt_assembler.py` — instruction text

---

## ~~Gap 4 (original): Validation Pattern Persistence~~

**REMOVED** — already implemented. Validation patterns flow: `_validate_and_annotate()` → `validation_log.jsonl` → `ContextBuilder.load_validation_patterns()` → `base_package()` → prompt. Confirmed at handlers.py:1863-1885 and context_builder.py:579-637.

---

## Implementation Sequence

```
Batch 1 (independent):     Gap 1 (recalibrations) + Gap 3 (correction lessons)
Batch 2 (independent):     Gap 2 (directional bias)
Batch 3 (needs 1+2):       Gap 4 (self-assessment)
```

## Key Files Modified

| File | Changes |
|------|---------|
| `orchestrator/app.py` | Gap 1: suggestion_lookup + enrich recalibration writes |
| `analysis/context_builder.py` | Gap 1: load_recalibrations(). Gap 2: directional bias in load_forecast_meta(). Gap 4: build_self_assessment(). All in base_package() |
| `analysis/response_validator.py` | Gap 1: Accept + consume recalibrations in _apply_calibration() |
| `orchestrator/handlers.py` | Gap 1: Pass recalibrations to validator. Gap 3: Correction lesson synthesis |
| `skills/prediction_tracker.py` | Gap 2: compute_directional_bias() |
| `schemas/forecast_tracking.py` | Gap 2: directional_bias field |
| `skills/forecast_tracker.py` | Gap 2: Wire into compute_meta_analysis() |
| `analysis/prompt_assembler.py` | Gap 2+4: Bias awareness + self-assessment instructions |
| `analysis/weekly_prompt_assembler.py` | Gap 2+4: Same prompt additions |

## Existing Code Reused

- `LearningLedger.record_outcome_lessons()` — Gap 3 lesson persistence
- `ContextBuilder._apply_temporal_window()` — Gap 1 recalibration loading
- `ContextBuilder.load_correction_patterns()` — Gap 4 self-assessment input
- `ContextBuilder.load_category_scorecard()` — Gap 4 self-assessment input
- `PredictionTracker._classify_direction()` — Gap 2 noise thresholds
- `CorrectionPatternExtractor.extract()` — Gap 3 already called in handlers
- `ResponseValidator._bucket_adjust_confidence()` — Gap 1 integration pattern

## Verification

- All 2954 existing tests pass after implementation
- Gap 1: Recalibration writes now include `bot_id`/`category`; `ResponseValidator` blends recalibrated confidence at 60/40 ratio
- Gap 2: `compute_directional_bias()` returns optimistic/pessimistic/balanced per metric with 0.15 threshold
- Gap 3: Correction patterns with count >= 3 are synthesized into `[correction]`-prefixed learning ledger lessons
- Gap 4: `build_self_assessment()` produces narrative from 5 signal sources, requires >= 2 signals
- End-to-end: `grep -r "recalibrations" .` shows BOTH write (app.py) AND read (context_builder.py, response_validator.py)

## Post-Implementation Review Fixes

Three issues found during review, all corrected:

1. **`_parse_timestamp()` missing `recorded_at` key** — recalibrations use `recorded_at` but temporal window only checked `timestamp`, `created_at`, `date`. Added `recorded_at` to the key list so recalibrations benefit from age filtering and decay sorting.

2. **Correction lesson entry_id collision** — `record_outcome_lessons()` used `outcomes:{week_start}` as entry_id prefix for both outcome-derived and correction-derived lessons. Added `source` parameter (default `"outcomes"`, correction site passes `"corrections"`) so both can coexist for the same week.

3. **`build_self_assessment()` duplicated 4 expensive loads** — `load_forecast_meta()`, `load_category_scorecard()`, `load_correction_patterns()`, `load_recalibrations()` were called in both `build_self_assessment()` and `base_package()`. Refactored to accept optional pre-loaded data; `base_package()` passes its already-loaded values.
