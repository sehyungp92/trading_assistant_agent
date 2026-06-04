# Plan: Close Learning Loop Feedback Quality Gaps

**Date**: 2026-03-28
**Status**: Implemented

## Context

The two learning loops (inner deterministic + outer LLM) were recently improved with 6 gap closures
(temporal decay, directional bias, discovery instructions, suggestion pre-validation, detector confidence,
convergence tracking). These made the inner loop self-calibrating and gave the outer loop empirical
grounding. However, a deeper evaluation reveals the feedback SIGNAL QUALITY itself has fundamental
problems: outcomes don't check whether the targeted metric improved, contradictory suggestions oscillate
unchecked, no one evaluates whether the system is optimizing the right categories, and search signals
are written but never consumed. These 4 gaps degrade every downstream feedback signal.

---

## Gap 1: Per-Metric Targeted Outcome Evaluation (HIGH — fixes all downstream signals)

**Problem**: `AutoOutcomeMeasurer` compares overall PnL/win_rate/drawdown before/after but never checks
whether the SPECIFIC metric a suggestion targeted actually improved. Root cause: `target_param`,
`proposed_value`, and `expected_impact` from `AgentSuggestion` are dropped when mapped to
`SuggestionRecord` in handlers.py. After persistence, the link between suggestion and targeted metric
is lost. This contaminates the scorecard, detector confidence, and every feedback signal.

### Changes

**`schemas/suggestion_tracking.py`** — Added 3 optional fields to `SuggestionRecord`:
```python
target_param: Optional[str] = None
proposed_value: Optional[float] = None
expected_impact: str = ""
```

**`orchestrator/handlers.py`** — Pass through in both recording methods:
- `_record_suggestions()`: Extracts `target_param` from `detection_context.threshold_name`,
  `proposed_value` from `suggestion.suggested_value`, `expected_impact` from description
- `_record_agent_suggestions()`: Passes `suggestion.target_param`, `.proposed_value`,
  `.expected_impact` directly (with safe type checking for mock objects)

**`schemas/outcome_measurement.py`** — Added to `OutcomeMeasurement`:
```python
target_metric: Optional[str] = None          # "pnl" | "win_rate" | "drawdown"
target_metric_improved: Optional[bool] = None
target_metric_delta: float = 0.0
```

**`skills/auto_outcome_measurer.py`** — New logic:
- Added `CATEGORY_TO_TARGET_METRIC` mapping (stop_loss→drawdown, exit_timing→pnl, signal→win_rate,
  filter_threshold→win_rate, position_sizing→pnl, regime_gate→drawdown)
- Added `_load_suggestion_category(suggestion_id)` — reads suggestions.jsonl to find category/target_param
- Added `_evaluate_target_metric(measurement, suggestion_id)` — checks the specific before/after delta for
  the targeted metric. For drawdown: improvement = decrease. For PnL/win_rate: improvement = increase.
- Called after creating measurement object in `measure()`, sets target fields via `model_copy(update=...)`

**`skills/suggestion_scorer.py`** — Weight targeted-metric signal:
- Added `_target_metric_weight(outcome) -> float` returning 1.2 (target improved), 0.8 (target worsened),
  1.0 (no info). Multiplied into age weight in `compute_scorecard()`.

**Tests** (12): target field persistence + backward compat, category mapping, drawdown direction,
pnl direction, win_rate direction, no-info fallback, scorer weighting.

---

## Gap 2: Anti-Oscillation Dampening (HIGH — prevents most wasteful failure mode)

**Problem**: `StrategyEngine` is stateless — constructed fresh each cycle with no memory. Can fire
"stop too tight" one week and "stop too loose" the next. The convergence tracker detects oscillation
in outcome METRICS but not in SUGGESTION DIRECTION. The only anti-oscillation mechanism is a prompt
instruction to the LLM, which the deterministic inner loop ignores entirely.

### Changes

**`skills/suggestion_tracker.py`** — Added query method:
```python
def get_recent_by_bot(self, bot_id: str, weeks: int = 4) -> list[dict]:
    """Return non-rejected suggestions for bot_id within time window."""
```

**`analysis/strategy_engine.py`** — Accepts and uses recent suggestions:
- Constructor: added `recent_suggestions: list[dict] | None = None`,
  `convergence_report: dict | None = None`
- `_infer_direction(suggestion: StrategySuggestion) -> int` — returns +1 (increase), -1 (decrease),
  0 (unknown) by comparing `suggested_value` vs `current_value`, falling back to keyword analysis
  ("tighten"/"reduce"/"lower" → -1, "widen"/"increase"/"raise" → +1)
- `_infer_direction_from_dict(rec: dict) -> int` — same logic for persisted suggestion dicts
- `_contradicts_recent(bot_id, detector_name, direction) -> bool` — checks if a recent suggestion
  from same detector+bot had opposite direction within 4-week window
- In `build_report()`, after detector confidence calibration, before category suppression:
  1. Filters out suggestions that contradict recent ones (same detector, same bot, opposite direction)
  2. If `convergence_report["oscillation_detected"]`, applies 0.7x global confidence dampening

**`orchestrator/handlers.py`** — Wires data:
- Before StrategyEngine construction: loads recent suggestions per bot via `suggestion_tracker`
- Loads convergence report from context_builder
- Passes both to StrategyEngine constructor

**Tests** (10): contradiction suppression, same-direction pass-through, different-detector pass,
different-bot pass, oscillation dampening, direction inference from keywords, unknown direction,
get_recent_by_bot filtering, rejected exclusion.

---

## Gap 3: Optimization Allocation Diagnostic (HIGH — adds strategic direction)

**Problem**: The system greedily optimizes whatever detectors fire. Nothing evaluates whether the
optimization DIRECTION is correct. Key questions go unasked: "Are we spending too many suggestions
on stop_loss when the real alpha is in signal quality?" The data exists in outcomes.jsonl and
suggestions.jsonl but nobody computes value-per-suggestion by category.

### Changes

**`skills/suggestion_scorer.py`** — Added `compute_category_value_map()`:
```python
def compute_category_value_map(self) -> dict:
    """Per-(bot_id, category): avg_composite_delta, suggestion_count, value_per_suggestion."""
```
Groups outcomes by (bot_id, category), counts total suggestions per category (including unmeasured),
computes avg_composite_delta and value_per_suggestion. Generates recommendations: "shift effort from
{low_value} to {high_value}", "deprioritize {category} with 0 positive outcomes in N attempts".

**`analysis/context_builder.py`** — Added `load_optimization_allocation()`:
Instantiates SuggestionScorer, calls `compute_category_value_map()`. Added to `base_package()` as
`optimization_allocation`. Added to `_CONTEXT_PRIORITY`.

**`analysis/weekly_prompt_assembler.py`** — Added instruction section:
```
## OPTIMIZATION ALLOCATION
If optimization_allocation is present, reference when proposing suggestions:
- Prefer categories with high value_per_suggestion
- Categories with negative value require exceptional evidence
- Follow recommendations for shifting effort between categories
```

**`analysis/strategy_engine.py`** — Bounded confidence adjustment:
Accepts `category_value_map: dict | None = None`. In `build_report()`, after anti-oscillation and
before category suppression, applies +-10% confidence adjustment based on value_per_suggestion.

**`orchestrator/handlers.py`** — Computes and passes category_value_map to StrategyEngine.

**Tests** (8): basic ranking, empty outcomes, recommendations, zero-positive warning, confidence
boost, confidence reduction, base_package injection, instruction presence.

---

## Gap 4: Consume Search Signals (MEDIUM — completes search feedback loop)

**Problem**: `search_signals.jsonl` written by `autonomous_pipeline.py` with `{bot_id, category,
positive, timestamp}` records, but NO downstream system reads it. This per-category APPROVE/DISCARD
ratio stream goes nowhere.

### Changes

**`analysis/context_builder.py`** — Added `load_search_signal_summary()`:
Reads `search_signals.jsonl`, aggregates by (bot_id, category), computes approve_count, discard_count,
approve_rate. Added to `base_package()` as `search_signal_summary`. Added to `_CONTEXT_PRIORITY`.

**`analysis/weekly_prompt_assembler.py`** — Added instruction:
```
## SEARCH SIGNAL QUALITY
If search_signal_summary is present:
- approve_rate < 0.3: detector firing on noise -- investigate threshold
- approve_rate > 0.7: search productive -- more suggestions in this category worthwhile
```

**Tests** (5): aggregation, approve_rate, empty file, missing file, base_package injection.

---

## Implementation Order

```
Gap 1 (targeted outcome) ─────> Gap 2 (anti-oscillation) ─────> Gap 3 (optimization allocation)
       │                              uses target_param                    │
       └──────────────────────────────────────────────────── Gap 4 (search signals, independent)
```

Gap 1 was first: `target_param`/`proposed_value` on SuggestionRecord are used by Gap 2's direction
inference. Gaps 2+3 are independent of each other. Gap 4 is fully independent.

## Files Changed Summary

| File | Gaps | Change |
|------|------|--------|
| `schemas/suggestion_tracking.py` | 1 | 3 new optional fields |
| `schemas/outcome_measurement.py` | 1 | 3 new optional fields |
| `skills/auto_outcome_measurer.py` | 1 | 2 new methods + measure() enhancement |
| `skills/suggestion_scorer.py` | 1, 3 | 2 new methods + weight adjustment |
| `skills/suggestion_tracker.py` | 2 | 1 new method |
| `analysis/strategy_engine.py` | 2, 3 | 3 new params + direction inference + build_report() |
| `analysis/context_builder.py` | 3, 4 | 2 new loaders + base_package() |
| `analysis/weekly_prompt_assembler.py` | 3, 4 | 2 new instruction sections |
| `orchestrator/handlers.py` | 1, 2, 3 | Target passthrough + StrategyEngine wiring |
| `tests/test_loop_feedback_quality.py` | all | 37 new tests |

## Verification

- **3020 tests pass** (37 new + 2983 existing, zero regressions)
- All new fields have defaults — backward compatible with existing JSONL data
- Integration verified: `base_package()` includes new keys with correct priority
