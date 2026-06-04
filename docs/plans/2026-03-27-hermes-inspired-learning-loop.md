# Hermes-Inspired Learning Loop Improvements

**Date:** 2026-03-27
**Status:** Implemented
**Test Results:** 2954 passed, 0 failed

## Context

The trading assistant has a comprehensive learning loop (suggestion lifecycle, outcome measurement, calibration, hypothesis tracking, cross-bot transfer). Comparison with hermes-agent's self-patching procedural memory and evolving user model reveals gaps where the feedback loop is broken or degraded, directly impacting the system's ability to learn from its own suggestions and improve trading returns over time.

The improvements below are ordered by expected trading impact. All close existing feedback loops rather than adding new features.

---

## Priority 1: Progressive Measurement Windows

**Problem:** `AutoOutcomeMeasurer.measure()` (skills/auto_outcome_measurer.py:43-44) defaults to `before_days=7, after_days=7`. The caller in `orchestrator/app.py:956` (`_measure_outcomes`) passes no window args, so it always runs at 7 days. Most strategy changes need 20-30+ days for statistical significance. The quality gate (`compute_measurement_quality` in schemas/outcome_measurement.py:97) returns `INSUFFICIENT` if either trade count < 3 — common in a 7-day window for low-frequency bots. These get filtered out by `ContextBuilder.load_outcome_measurements()` (min_quality="medium"), so they never reach the agent prompt. This starves the entire downstream chain: SuggestionScorer, ThresholdLearner, calibration.

**Evidence:** `PortfolioOutcomeMeasurer` already uses `_MIN_OBSERVATION_DAYS = 30`. The `measure()` method already accepts `before_days`/`after_days` params — they're just never varied.

**Changes:**
- `skills/auto_outcome_measurer.py`: Added `measure_progressive()` that tries windows [7, 14, 30] days, returning the highest-quality result. Only attempts windows where sufficient calendar time has elapsed since `implemented_date`. Existing `measure()` unchanged for backward compat.
- `schemas/outcome_measurement.py`: Added optional `window_days` param to `compute_measurement_quality()` to scale trade count minimums with window size (7d→3, 14d→5, 30d→10). Default preserves current behavior.
- `orchestrator/app.py`: In `_measure_outcomes()`, calls `measure_progressive()` instead of `measure()`.

**Trading impact:** Highest. More suggestions complete the feedback loop → scorer accumulates data faster → confidence multipliers become meaningful → better suggestions reach the user.

---

## Priority 2: Detector Suppression from Category Scorecard

**Problem:** Strategy engine detectors (analysis/strategy_engine.py) keep firing suggestions for categories with poor track records. The `ResponseValidator` (analysis/response_validator.py:94-117) already blocks these downstream via two conditions: hard block at n>=5/win_rate<0.3 and marginal block at n>=3/win_rate<0.5/avg_pnl<0.001. But the detector→record→validate→block cycle still wastes resources:
1. `build_report()` collects all suggestions (lines 980-1061, returns at 1057)
2. `_record_suggestions()` persists them to suggestions.jsonl
3. Agent spends tokens formatting and analyzing them
4. Validator blocks them
5. `validation_log.jsonl` grows

Suppressing at the detector level avoids steps 2-5.

**Changes:**
- `analysis/strategy_engine.py`: Accepts optional `CategoryScorecard` in `__init__()`. Added `_should_suppress(bot_id, category)` → True when `sample_size >= 5 AND win_rate < 0.3 AND avg_pnl_delta < 0`. Filters `all_suggestions` before `return RefinementReport(...)`.
- `orchestrator/handlers.py`: In `handle_weekly_analysis`, computes scorecard before creating `StrategyEngine`, passes it in.

**Trading impact:** Frees agent attention budget for categories that work. Reduces suggestion recording noise. The validator already prevents execution of bad suggestions — this prevents wasted processing.

---

## Priority 3: Transfer Outcome Quality Gates

**Problem:** `TransferProposalBuilder.measure_transfer_outcomes()` (skills/transfer_proposal_builder.py:109-114) uses naive binary verdict: `pnl_delta > 0 AND wr_delta >= 0 → "positive"`. No regime matching, no trade count minimum, no volatility control. Meanwhile `AutoOutcomeMeasurer.measure()` does extensive quality checking.

The `compute_transfer_track_record()` feeds these verdicts into `build_proposals()` scoring: `+0.1` for positive track record, `-0.2` for negative. False positives directly inflate compatibility scores.

**Changes:**
- `skills/transfer_proposal_builder.py`:
  - Extended `_load_bot_metrics()` to also return `trade_count` and `dominant_regime`.
  - In `measure_transfer_outcomes()`: requires `before_trades >= 5 AND after_trades >= 5` (skips otherwise), loads regimes for before/after windows, classifies as `"inconclusive"` when regimes don't match.
  - In `compute_transfer_track_record()`: excludes `"inconclusive"` verdicts from success rate.
  - In `load_track_record_from_file()`: same inconclusive exclusion applied.
- `schemas/transfer_proposals.py`: Added to `TransferOutcome`: `regime_matched: bool = True`, `measurement_quality: str = "medium"`, `before_trade_count: int = 0`, `after_trade_count: int = 0`. Updated `verdict` Literal to include `"inconclusive"`.

**Trading impact:** Prevents bad patterns from propagating across bots via inflated compatibility scores.

---

## Priority 4: Magnitude-Aware Prediction Evaluation

**Problem:** `PredictionTracker.evaluate_predictions()` (skills/prediction_tracker.py:91-98) uses binary direction matching — any `actual > 0` counts as "improve". A $1 PnL rise and a $10,000 PnL rise are equally "correct". This makes per-metric accuracy noisy, which degrades the calibration data in `ForecastTracker`.

**Existing scaffolding:** `PredictionRecord` schema already has `predicted_magnitude: Optional[float]` and `actual_magnitude: Optional[float]` fields — currently unused.

**Changes:**
- `skills/prediction_tracker.py`:
  - Added `_classify_direction(actual, metric)` with per-metric noise thresholds: pnl→$50, win_rate→0.03, drawdown→0.005, sharpe→0.1. Changes below threshold classify as "stable" instead of "improve"/"decline".
  - Added `_compute_magnitude_score(predicted_direction, actual, metric)` → float 0-1 measuring alignment strength.
  - Uses noise-aware direction in verdict computation.
- `schemas/prediction_tracking.py`: Added `magnitude_score: float = 0.0` to `PredictionVerdict`. Added `magnitude_weighted_accuracy: float = 0.0` to `PredictionEvaluation`.

**Trading impact:** More reliable calibration → better confidence adjustment on suggestions.

---

## Priority 5: Context Budget Transparency

**Problem:** `ContextBuilder.base_package()` (analysis/context_builder.py) has a `_CONTEXT_PRIORITY` list of 23 items but a default budget of 15. When all sources have data, 8 items are silently dropped. A `logger.warning` fires but the agent prompt has NO indication that context was truncated.

**Changes:**
- `analysis/context_builder.py`: After budget trimming, adds `_context_budget_manifest` to `package.metadata`: `{"included": [...], "omitted": [...], "total_available": N}`.
- Budget is adaptive: default budget of 15 auto-expands up to `min(items_with_data, 20)` — only trims when there's genuine pressure. Explicitly set budgets are respected as-is.

**Trading impact:** Prevents analysis blind spots. Agent can caveat suggestions when relevant context is missing.

---

## Priority 6: Bayesian SuggestionScorer

**Problem:** `SuggestionScorer.compute_scorecard()` (skills/suggestion_scorer.py:89-92) uses a hard `n >= 5` threshold for `confidence_multiplier` penalization. Below n=5, multiplier is always 1.0.

**Changes:**
- `skills/suggestion_scorer.py`: Replaced hard threshold with Bayesian posterior mean: `posterior = (wins + 1) / (total + 2)` (Beta(1,1) prior). `multiplier = max(0.3, min(1.0, posterior * 2.0))`. This gives: n=0→1.0, n=2 (0 wins)→0.5, n=3 (1 win)→0.8, n=5 (1 win)→0.57.
- No changes needed to `ResponseValidator` blocking logic — existing n>=3 marginal check remains as-is.

**Trading impact:** Smoother confidence adjustment for approved suggestions from categories with small sample sizes.

---

## Priority 7: Evolving Analysis Notes (Hermes-Inspired)

**Problem:** The trading assistant's `LearningLedger` records `what_worked`, `what_failed`, `lessons_for_next_week` per week, and `ContextBuilder.load_ground_truth_trend()` injects the last 4 weeks of lessons into prompts. But:
1. Lessons expire after 4 weeks regardless of relevance
2. Lessons are raw text with no deduplication or synthesis
3. Insights from outcomes and predictions don't feed into lessons
4. No relevance-based retention

**Changes:**
- `skills/learning_ledger.py`: Added `get_curated_notes(max_notes=30)` that:
  - Loads all lessons from 52 weeks lookback
  - Deduplicates by Jaccard similarity on word tokens (threshold 0.6)
  - Applies 5%/week relevance decay but boosts lessons corroborated by outcome measurements
  - Returns curated, ranked notes capped at `max_notes`
  - Added `_load_outcome_keywords()` helper for outcome boosting
- `analysis/context_builder.py`: In `load_ground_truth_trend()`, includes `curated_analysis_notes` from the extended ledger alongside existing `recent_lessons`.
- `orchestrator/handlers.py`: At end of weekly handler, after outcome measurement and prediction evaluation, appends outcome-derived insights to the ledger's `lessons_for_next_week`.

**Trading impact:** Accumulates operational wisdom beyond the 4-week window. Insights like "filter loosening for bot X consistently fails" persist and strengthen over time instead of expiring.

---

## Implementation Sequence

```
Batch 1 (independent, parallel): P1 + P5 + P6
Batch 2 (benefits from P1):      P2 + P3
Batch 3 (benefits from all):     P4 + P7
```

## Key Files Modified

| File | Changes |
|------|---------|
| `skills/auto_outcome_measurer.py` | P1: Added `measure_progressive()` |
| `schemas/outcome_measurement.py` | P1: Optional `window_days` in quality computation |
| `orchestrator/app.py` | P1: `_measure_outcomes()` calls `measure_progressive()` |
| `analysis/strategy_engine.py` | P2: Accepts `CategoryScorecard`, filters in `build_report()` |
| `orchestrator/handlers.py` | P2: Passes scorecard to engine. P7: Appends outcome-derived lessons |
| `skills/transfer_proposal_builder.py` | P3: Regime matching, trade count minimums, quality gates |
| `schemas/transfer_proposals.py` | P3: New fields on `TransferOutcome` |
| `skills/prediction_tracker.py` | P4: Noise thresholds, magnitude scoring |
| `schemas/prediction_tracking.py` | P4: `magnitude_score`, `magnitude_weighted_accuracy` |
| `analysis/context_builder.py` | P5: Budget manifest in metadata. P7: Curated notes loader |
| `skills/suggestion_scorer.py` | P6: Bayesian multiplier |
| `skills/learning_ledger.py` | P7: `get_curated_notes()` with decay + dedup + boosting |
| `tests/test_response_validator.py` | P6: Updated assertion for Bayesian multiplier |

## Deferred

- **Calibration baseline** (forecast_tracker.py:93 `calibration = avg_accuracy - 0.5`): Naive 0.5 baseline doesn't account for per-metric base rates. P4 (magnitude-aware eval) partially mitigates this by reducing false "correct" predictions. Full fix would require tracking base rates per metric per market condition — deferred as low ROI relative to complexity.
- **Hypothesis keyword matching** (hypothesis_library.py:166-199): `get_relevant()` uses brittle keyword map. Semantic matching would help but requires an embedding model — out of scope.
- **MemoryConsolidator scope** (memory_consolidator.py): Only consolidates `corrections.jsonl`. Other JSONL files grow unbounded. Worth extending but orthogonal to learning loop quality.
