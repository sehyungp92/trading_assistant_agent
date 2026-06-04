# Plan: Close Remaining Learning Loop Gaps

**Date**: 2026-03-28
**Status**: Completed
**Tests**: 29 new tests, 2983 total (all passing)

## Context

The trading assistant has a sophisticated two-loop learning system, but a thorough audit revealed earlier assessments contained errors (ThresholdLearner IS wired, retrospective_synthesis IS persisted, OutcomeReasoningAssembler IS triggered). After correcting these, **6 genuine gaps remained** that prevented the learning loops from being fully closed and optimally integrated.

The system already had: outcome reasoning (LLM-interprets WHY), suggestion validation (backtests parameters), experiment management (A/B with t-tests), threshold learning (adaptive detector thresholds), backtest calibration tracking, discovery agents, self-assessment, and comprehensive context injection. This plan addressed only what was genuinely missing.

---

## Gap 1: Loop Convergence Tracker (NEW MODULE — highest impact)

**Problem**: No signal for whether the learning system as a whole is improving, degrading, or oscillating. LearningLedger tracks per-bot composite scores, ForecastTracker tracks prediction accuracy, but nothing synthesized these into a convergence signal. The LLM and the system operators had no way to know if the optimization process was converging toward better outcomes.

**Files created**:
- `schemas/convergence.py` — Pydantic models (`ConvergenceReport`, `ConvergenceDimension`, `DimensionStatus`)
- `skills/convergence_tracker.py` — deterministic module, no LLM

**Schema** (`schemas/convergence.py`):
```python
class DimensionStatus(str, Enum):
    IMPROVING = "improving"
    STABLE = "stable"
    DEGRADING = "degrading"
    OSCILLATING = "oscillating"
    INSUFFICIENT_DATA = "insufficient_data"

class ConvergenceDimension(BaseModel):
    name: str  # e.g. "composite_scores", "prediction_accuracy", "outcome_ratio"
    status: DimensionStatus
    trend_value: float  # slope or delta
    window_weeks: int
    detail: str  # human-readable explanation

class ConvergenceReport(BaseModel):
    overall_status: DimensionStatus
    dimensions: list[ConvergenceDimension]
    oscillation_detected: bool
    weeks_analyzed: int
    recommendation: str  # e.g. "System converging — maintain current approach"
```

**Implementation** (`skills/convergence_tracker.py`):
```python
class ConvergenceTracker:
    def __init__(self, findings_dir: Path) -> None: ...

    def compute_report(self, weeks: int = 12) -> ConvergenceReport:
        """Compute multi-dimensional convergence report."""
        dims = [
            self._check_composite_scores(weeks),
            self._check_prediction_accuracy(weeks),
            self._check_outcome_ratio(weeks),
            self._check_scorecard_evolution(weeks),
        ]
        overall = self._synthesize_overall(dims)
        oscillation = any(d.status == OSCILLATING for d in dims)
        recommendation = self._generate_recommendation(overall, dims)
        return ConvergenceReport(...)
```

**Dimensions computed**:
1. **Composite scores** — reads `learning_ledger.jsonl`, extracts `composite_delta` per week, fits
   linear trend. If slope > +0.01 → IMPROVING, < -0.01 → DEGRADING, alternating signs 4+ consecutive
   → OSCILLATING
2. **Prediction accuracy** — reads `forecast_history.jsonl`, extracts `accuracy` per week, same trend
   logic
3. **Outcome ratio** — reads `outcomes.jsonl`, groups by week, computes positive/total ratio, trend
4. **Scorecard evolution** — reads `outcomes.jsonl` with timestamps, computes rolling win rates at
   4-week intervals, checks if category win rates are trending up

**Oscillation detection**: Checks sign changes in sequential deltas. If ≥3 sign changes in last 6
values → OSCILLATING. Also checks if standard deviation of deltas > 2× mean absolute delta.

**Wiring**:
- `analysis/context_builder.py`: Added `load_convergence_report()` method, added to `base_package()`
  as `convergence_report`
- Added `convergence_report` to `_CONTEXT_PRIORITY` (high priority, after `self_assessment`)
- `analysis/prompt_assembler.py`: Added CONVERGENCE STATUS section to daily instructions
- `analysis/weekly_prompt_assembler.py`: Added CONVERGENCE STATUS section to weekly instructions with
  guidance: "If OSCILLATING, avoid reversing last week's suggestions. If DEGRADING, question current
  approach fundamentals."

---

## Gap 2: Temporal Decay on CategoryScorecard (BUG FIX)

**Problem**: `suggestion_scorer.py` computed win rates from ALL outcomes ever. A 6-month-old negative
outcome penalized a category equally to a failure last week. This was inconsistent with
learning_ledger's 5%/week decay and made it impossible for categories to "recover" from early failures.

**File modified**: `skills/suggestion_scorer.py`

**Changes**:
- Added `_compute_age_weight()` static method: exponential decay at 5%/week (same rate as
  learning_ledger). Unknown timestamps get 0.5 weight.
- `compute_scorecard()` now uses weighted sums instead of raw counts for:
  - Win rate calculation: weighted positive / weighted total
  - Average PnL delta: weighted average
  - Bayesian posterior: uses effective_n (sum of weights) instead of raw count

```python
_DECAY_RATE = 0.95  # 5%/week, consistent with learning_ledger

@staticmethod
def _compute_age_weight(outcome: dict) -> float:
    ts = outcome.get("measured_at") or outcome.get("timestamp", "")
    if not ts:
        return 0.5  # unknown age → half weight
    try:
        measured = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        weeks_ago = (datetime.now(timezone.utc) - measured).days / 7
        return _DECAY_RATE ** max(0, weeks_ago)
    except (ValueError, TypeError):
        return 0.5
```

**Test updates**: 1 existing test (`test_insufficient_sample_no_penalty`) updated to reflect new
weighted posterior calculation (0.667 → 0.8 due to half-weight on missing timestamps).

---

## Gap 3: Wire directional_bias into ResponseValidator

**Problem**: `PredictionTracker.compute_directional_bias()` detects systematic optimism/pessimism per
metric. This was already computed and injected into `ForecastMetaAnalysis.directional_bias` via
context_builder. But `ResponseValidator._adjust_prediction_confidence()` never checked it.

**File modified**: `analysis/response_validator.py`

**Change in `_adjust_prediction_confidence()`**:
```python
# Apply directional bias correction from prediction track record
directional_bias = self._forecast_meta.get("directional_bias", {})
if directional_bias:
    metric_bias = directional_bias.get(prediction.metric, {})
    bias_direction = metric_bias.get("bias", "balanced")
    gap_pct = metric_bias.get("gap_pct", 0)

    # Systematically optimistic about "improve" → reduce confidence
    if bias_direction == "optimistic" and prediction.direction == "improve":
        penalty = min(0.2, gap_pct / 100)  # cap at 20% reduction
        confidence *= (1.0 - penalty)
    # Systematically pessimistic about "decline" → reduce confidence
    elif bias_direction == "pessimistic" and prediction.direction == "decline":
        penalty = min(0.2, gap_pct / 100)
        confidence *= (1.0 - penalty)
```

---

## Gap 4: Discovery Context in Prompt Instructions

**Problem**: `base_package()` loads `discoveries` from `discoveries.jsonl` (via context_builder), but
neither `prompt_assembler.py` nor `weekly_prompt_assembler.py` told the LLM how to use them. The data
was present in `pkg.data` but invisible to the LLM's instruction set.

**Files modified**:
- `analysis/prompt_assembler.py` — added DISCOVERIES section to `_FOCUSED_INSTRUCTIONS`
- `analysis/weekly_prompt_assembler.py` — added DISCOVERIES AND STRATEGY IDEAS section to
  `_FOCUSED_WEEKLY_INSTRUCTIONS`

**Daily instruction addition**:
```
## DISCOVERIES (from automated pattern discovery)
If `discoveries` is present in your data, these are patterns found by a separate
discovery agent scanning raw JSONL data. Reference relevant discoveries when they
corroborate or contradict your analysis. Flag if a discovery seems invalidated by
recent data.
```

**Weekly instruction addition** (more detailed):
```
## DISCOVERIES AND STRATEGY IDEAS
If `discoveries` and `strategy_ideas` are present:
- Reference discoveries that corroborate or contradict detector findings
- For strategy_ideas with status "under_review": assess edge strength and recommend
  either backtest validation or retirement
- Do not propose structural changes that overlap with active strategy ideas
- If a discovery has been corroborated by 2+ weeks of data, escalate to structural proposal
```

---

## Gap 5: Strategy Engine Suggestion Pre-Validation

**Problem**: `_record_suggestions()` in handlers.py recorded `StrategySuggestion` objects from the
strategy engine directly to SuggestionTracker. While `build_report()` already suppresses suggestions
where scorecard shows `win_rate < 0.3` (at the detector level), the recording path had no validation.
This meant if `category_scorecard` was `None` during `build_report()`, suggestions in failed
categories could slip through.

**File modified**: `orchestrator/handlers.py`

**Changes**:
- `_record_suggestions()` now accepts optional `category_scorecard` parameter
- Before recording each suggestion, checks if its category has poor track record
  (win_rate < 0.3, sample_size >= 5) and skips it with a log message
- Weekly handler passes `_scorecard` to `_record_suggestions()`

```python
def _record_suggestions(self, suggestions, run_id, category_scorecard=None):
    # ...
    for idx, suggestion in enumerate(suggestions):
        # Pre-validation: skip suggestions in categories with poor track record
        if category_scorecard is not None:
            # ... check scorecard scores against suggestion tier ...
            if _skip:
                continue
        # ... proceed with recording ...
```

---

## Gap 6: Per-Detector Confidence Calibration

**Problem**: All detector confidence values in strategy_engine.py were hardcoded (0.5, 0.6, 0.65).
ThresholdLearner handled adaptive *thresholds* (WHEN to fire), but not adaptive *confidence* (HOW
much to trust the detection). When a detector fired but its suggestions consistently got negative
outcomes, the confidence should decrease; when consistently positive, increase.

**Files modified**:
- `skills/suggestion_scorer.py` — added `compute_detector_confidence()` method
- `analysis/strategy_engine.py` — accepts `detector_confidence: dict[str, float] | None`, applies
  multipliers in `build_report()` after collecting all suggestions
- `orchestrator/handlers.py` — computes detector confidence alongside scorecard (reuses same
  `SuggestionScorer` instance), passes to `StrategyEngine`

**SuggestionScorer.compute_detector_confidence()**:
```python
def compute_detector_confidence(self) -> dict[str, float]:
    """Compute per-detector confidence multipliers from outcome data.

    Groups outcomes by detector_name (from detection_context in suggestions.jsonl),
    applies temporal decay, returns {detector_name: confidence_multiplier}.
    """
    # Map suggestion_id → detector_name from suggestions.jsonl
    # Group outcomes by detector, deduplicate by suggestion_id
    # Apply same Bayesian + temporal decay formula as scorecard
    # Return {detector_name: multiplier}
```

**StrategyEngine integration**:
```python
# In build_report(), after collecting all suggestions:
if self._detector_confidence:
    for s in all_suggestions:
        det_name = s.detection_context.detector_name if s.detection_context else ""
        multiplier = self._detector_confidence.get(det_name, 1.0)
        if multiplier != 1.0:
            s = s.model_copy(update={"confidence": s.confidence * multiplier})
```

---

## Implementation Order (as executed)

1. **Gap 2** (temporal decay) — smallest scope, fixes data quality for all downstream consumers
2. **Gap 3** (directional bias) — small wiring fix, immediate value
3. **Gap 4** (discovery instructions) — prompt-only change, no logic
4. **Gap 5** (strategy suggestion validation) — small guard, prevents category leakage
5. **Gap 6** (per-detector confidence) — extends existing scorer, moderate scope
6. **Gap 1** (convergence tracker) — new module, depends on correct data from gaps 2-6

## Files Changed

| File | Change Type |
|------|-------------|
| `schemas/convergence.py` | **Created** — new schema |
| `skills/convergence_tracker.py` | **Created** — new module |
| `skills/suggestion_scorer.py` | Modified — temporal decay + detector confidence |
| `analysis/response_validator.py` | Modified — directional bias wiring |
| `analysis/context_builder.py` | Modified — convergence loader + priority |
| `analysis/prompt_assembler.py` | Modified — discovery + convergence instructions |
| `analysis/weekly_prompt_assembler.py` | Modified — discovery + convergence instructions |
| `analysis/strategy_engine.py` | Modified — detector confidence parameter |
| `orchestrator/handlers.py` | Modified — pre-validation + detector confidence wiring |
| `tests/test_learning_loop_gaps.py` | **Created** — 29 new tests |
| `tests/test_response_validator.py` | Modified — updated 1 expected value for decay |

## Verification

- Full test suite: **2983 passed, 0 failures**
- New tests: 29 covering all 6 gaps
- No regressions in existing tests (1 expected-value update in test_response_validator.py)
