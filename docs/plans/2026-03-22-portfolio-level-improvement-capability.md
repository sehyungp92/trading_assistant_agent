# Portfolio-Level Improvement Capability — Assessment & Plan

## Context

The trading_assistant currently proposes improvements at the **individual strategy level** — the strategy engine's 11 detectors fire per-bot, suggestions flow through the lifecycle (PROPOSED → MEASURED), and the LLM reasons about per-bot structural changes. Portfolio-level data is *observed* (risk cards, weekly correlation/synergy, allocation recommendations, drift analysis) but the system never **proposes portfolio-level config changes** with structured lifecycle tracking, outcome measurement, or evidence-grounded guardrails.

The question: can the system propose changes to portfolio-level configs (`portfolio.yaml`: family allocations, heat_cap_R, drawdown tiers, coordination rules) and strategy-family-level configs — and should this live in the inner loop (deterministic/autoresearch-inspired) or outer loop (LLM-reasoned)?

Reference: `docs/portfolio-instrumentation-gaps.md` (7 data gaps to close first).

## Assessment: Yes, With a Hybrid Architecture

### What Already Exists (substantial — don't rebuild)

| Component | File | What It Does |
|-----------|------|-------------|
| Cross-bot allocation (risk-parity + Calmar tilt) | `skills/portfolio_allocator.py` | Produces `PortfolioAllocationReport` with per-bot recommended allocation %, Calmar contribution, rationale |
| Intra-bot proportion optimization | `skills/strategy_proportion_optimizer.py` | Risk-parity + Sharpe tilt for strategies within a bot |
| Synergy analysis (correlation + redundancy) | `skills/synergy_analyzer.py` | `compute_bot_correlation_matrix()` → pairwise Pearson, redundant/complementary classification |
| Allocation drift detection | `skills/drift_analyzer.py` | `compute_drift_trend()` from `AllocationSnapshot` history |
| Allocation tracking | `skills/allocation_tracker.py` | JSONL snapshots + history, `get_latest_actuals()` |
| Portfolio risk card (daily) | `skills/compute_portfolio_risk.py` | Exposure by symbol/direction, concentration_score, crowding_alerts |
| Strategy profiles + coordination rules | `schemas/strategy_profile.py` | `PortfolioConfig` (heat_cap_R, drawdown_tiers, family_allocations), `CoordinationConfig` |
| Weekly ALLOCATION ASSESSMENT prompt | `analysis/weekly_prompt_assembler.py:51` | Asks LLM to validate allocation_analysis, assess signal independence, highlight top 3 changes |
| Allocation analysis injection | `orchestrator/handlers.py:573` | `package.data.update({"allocation_analysis": allocation_results})` into weekly prompt |
| Weekly allocation_analysis.json + allocation_drift.json | `orchestrator/handlers.py:2348-2381` | Written to `curated/weekly/{week_start}/` |
| Ground truth composite (per-bot) | `skills/ground_truth_computer.py` | 0.30*calmar + 0.25*profit_factor + 0.25*inv_drawdown + 0.20*process_quality |
| Suggestion lifecycle | `skills/suggestion_tracker.py` | JSONL-backed PROPOSED → ACCEPTED → MERGED → DEPLOYED → MEASURED |
| Response validator | `analysis/response_validator.py` | Blocks rejected, low-track-record, low-confidence suggestions |
| Coordinator impact (daily) | `analysis/prompt_assembler.py` | `coordinator_impact.json` already in daily curated files (swing family StrategyCoordinator outcomes) |

### Why Hybrid (Not Pure Inner or Pure Outer)

**Pure inner loop won't work** for most portfolio parameters because:
- Portfolio-level backtesting requires multi-strategy replay with coordination rules (doesn't exist, very complex)
- Parameters like heat_cap_R and drawdown tiers are safety-critical (emergency braking)
- Allocation decisions require qualitative judgment about strategy maturity, regime outlook, diversification

**Pure outer loop is insufficient** because:
- Some portfolio metrics have clear numeric signals (heat cap utilization at 95% = too tight, correlation > 0.7 with 40%+ weight = crowded)
- The LLM needs deterministic detectors to surface issues — it can't efficiently scan raw correlation matrices
- Inner loop handles bounded exploration, freeing the LLM for causal reasoning

### Parameter Classification

| Parameter | Loop | Why |
|-----------|------|-----|
| Family allocation weights | **Outer** | Safety-critical, requires regime context, monthly cadence |
| Intra-bot strategy proportions | **Inner** (already works via `StrategyProportionOptimizer`) | Numeric, bounded |
| heat_cap_R | **Outer** | Safety-critical, quarterly |
| daily/weekly stop levels | **Outer** | Safety-critical, `requires_double_approval`, quarterly |
| Drawdown tier multipliers | **Outer** | Emergency braking — tiers can only narrow, never loosen/remove |
| New coordination signal | **Outer** | Structural, requires causal reasoning |
| Cooldown pair duration | **Hybrid** | Existence = outer; duration = inner (if enough co-occurrence data) |
| Direction filter multipliers | **Inner** (candidate) | Numeric with backtestable impact |
| Symbol collision action | **Outer** | Discrete structural choice |

---

## Phase 0: Data Foundation (Close 7 Instrumentation Gaps)

Without portfolio-level data, any suggestion system is guessing. These are strict prerequisites.

**Important distinction**: `coordinator_impact.json` (already in daily curated) tracks the **swing family's StrategyCoordinator** (in-process). Gap 1 below tracks **momentum/stock PortfolioRuleChecker** events (OMS event bus) — different system, different data.

### 0A. Populate `correlation_matrix` on PortfolioRiskCard (Gap 4, P0)
- **File**: `skills/compute_portfolio_risk.py` → new `_compute_correlation_matrix()` method
- **Reuse**: `synergy_analyzer.compute_bot_correlation_matrix()` logic (pairwise Pearson from daily PnL series)
- Populate existing `PortfolioRiskCard.correlation_matrix: dict[str, float]` field (currently always `{}`)
- Add `high_correlation` type to `CrowdingAlert` when any pair > `self.correlation_threshold` (0.7)
- Need: load 20 days of `BotDailySummary` from curated dir

### 0B. Portfolio rules summary (Gap 1, P0)
- **File**: `skills/build_daily_metrics.py` → new standalone function `build_portfolio_rules_summary()`
- Scan `portfolio_rule_check` events from raw JSONL (momentum/stock PortfolioRuleChecker)
- Output: `curated/{date}/portfolio/rule_blocks_summary.json`
- Schema: inline dict (matches spec in `docs/portfolio-instrumentation-gaps.md`)
- **File**: `analysis/prompt_assembler.py` → add `portfolio/rule_blocks_summary.json` to `_CURATED_FILES`

### 0C. Family-level daily snapshots (Gap 2, P1)
- **File**: `skills/build_daily_metrics.py` → new function `build_family_snapshots()`
- Aggregate `BotDailySummary` by family (using `strategy_registry.strategies_in_family()`)
- Output: `curated/{date}/portfolio/family_snapshots.json`
- **New schema**: `FamilyDailySnapshot` in `schemas/portfolio_metrics.py` — fields: family, strategy_ids, total_net_pnl, total_fees, trade_count, win_count, loss_count, max_drawdown_pct, avg_exposure_pct, active_strategies
- **File**: `analysis/prompt_assembler.py` → add to `_CURATED_FILES`

### 0D. Consume `correlated_pairs_detail` (Gap 5, P1)
- **File**: `skills/build_daily_metrics.py` → extract from trade event payloads
- Output: `curated/{date}/portfolio/concurrent_position_analysis.json`
- **File**: `analysis/prompt_assembler.py` → add to `_CURATED_FILES`

### 0E. Sector exposure aggregation (Gap 7, P1)
- **File**: `skills/compute_portfolio_risk.py` → new `_compute_sector_exposure()` method
- Consume stock sector metadata, aggregate exposure by sector
- Add sector concentration alerts to `PortfolioRiskCard.crowding_alerts`
- Output: `curated/{date}/portfolio/sector_exposure.json`
- **File**: `analysis/prompt_assembler.py` → add to `_CURATED_FILES`

### 0F. Portfolio-level rolling metrics (Gap 3, P2)
- **New file**: `skills/portfolio_metrics_tracker.py`
- Compute rolling 7d/30d/90d Sharpe, Sortino, Calmar from family snapshots (requires 0C)
- Output: `curated/{date}/portfolio/portfolio_rolling_metrics.json`
- **New schema**: `PortfolioRollingMetrics` in `schemas/portfolio_metrics.py`

### 0G. Drawdown correlation analysis (Gap 6, P2)
- **File**: `skills/compute_portfolio_risk.py` → new `compute_drawdown_correlation()` method
- Load per-family equity curves, compute overlap days, correlation coefficients
- Output: `curated/weekly/{week_start}/drawdown_correlation.json`
- **New schema**: `DrawdownCorrelation` in `schemas/portfolio_metrics.py`

---

## Phase 1: Portfolio Suggestion Taxonomy

### Key Implementation Detail: Two Suggestion Types

The codebase has **two separate suggestion flows**:
1. **`StrategySuggestion`** (`schemas/strategy_suggestions.py`) — produced by the deterministic strategy engine, has `SuggestionTier` enum (PARAMETER/FILTER/STRATEGY_VARIANT/HYPOTHESIS), carries `bot_id`, `strategy_id`, `archetype_note`
2. **`AgentSuggestion`** (`schemas/agent_response.py`) — parsed from LLM structured output, has `category: str` (exit_timing, filter_threshold, etc.), `proposed_value`, `target_param`

Both eventually flow into **`SuggestionRecord`** (`schemas/suggestion_tracking.py`) via `_record_agent_suggestions()` in handlers.py.

Portfolio suggestions need to work through **both flows**:
- Inner loop portfolio detectors → `StrategySuggestion` (with new tier or existing HYPOTHESIS tier)
- Outer loop LLM proposals → `AgentSuggestion` (with new portfolio category strings)

### 1A. Extend `SuggestionTier` enum
- **File**: `schemas/strategy_suggestions.py`
- Add: `PORTFOLIO = "portfolio"` to `SuggestionTier` enum
- This is used by inner loop portfolio detectors (Phase 2)

### 1B. Add portfolio categories to prompt instructions
- **Note**: `AgentSuggestion.category` is a plain `str` field, not an enum — valid values are documented in prompt instructions only
- **File**: `analysis/weekly_prompt_assembler.py` → add to structured output spec: `portfolio_allocation`, `portfolio_risk_cap`, `portfolio_coordination`, `portfolio_drawdown_tier`
- **File**: `schemas/agent_response.py` → add `CATEGORY_TO_TIER` mapping for new categories → `"portfolio"` tier

### 1C. PortfolioProposal schema
- **New file**: `schemas/portfolio_proposal.py`
- `PortfolioProposalType` enum: `allocation_rebalance | risk_cap_change | coordination_change | drawdown_tier_change`
- `PortfolioProposal(BaseModel)`: `proposal_type`, `current_config: dict`, `proposed_config: dict`, `evidence_summary: str`, `expected_portfolio_calmar_delta: float`, `confidence: float`, `observation_window_days: int`, `acceptance_criteria: list[dict]`
- This is used for LLM-generated proposals (richer than `AgentSuggestion`)

### 1D. Lifecycle extension for portfolio suggestions
- **File**: `skills/suggestion_tracker.py`
- `bot_id = "PORTFOLIO"` as sentinel — works without changes to basic record/get_rejected logic
- Add: concurrent deployment check — `get_deployed(bot_id="PORTFOLIO")` returns count, block if > 0 (max 1 DEPLOYED portfolio change at a time for attribution)
- Add: dedup by `proposal_type + config_hash` for portfolio suggestions (not just suggestion_id)

### 1E. Portfolio suggestion scoring
- **File**: `skills/suggestion_scorer.py`
- Add: portfolio-level category tracking with `bot_id="PORTFOLIO"` key
- Use portfolio-level ground truth delta for outcome measurement (Phase 5)

---

## Phase 2: Portfolio-Level Detectors (Inner Loop)

Five new standalone methods in `analysis/strategy_engine.py`. These follow the same pattern as existing `detect_*()` methods — each returns `list[StrategySuggestion]` and gets called from the weekly handler, not from a `build_report()` method (which doesn't exist).

### 2A. `detect_family_imbalance()`
```python
def detect_family_imbalance(
    self, family_summaries: dict[str, FamilyDailySnapshot],
    family_allocations: dict[str, float],
    min_days: int = 30,
) -> list[StrategySuggestion]:
```
- Detects: family consistently underperforming its allocation weight
- Output: `StrategySuggestion(tier=SuggestionTier.PORTFOLIO, bot_id="PORTFOLIO", ...)`
- Guardrail: minimum 30 days data, max 15% single rebalance

### 2B. `detect_correlation_concentration()`
```python
def detect_correlation_concentration(
    self, correlation_matrix: dict[str, float],
    current_allocations: dict[str, float],
    threshold: float = 0.7,
    weight_threshold: float = 0.4,
) -> list[StrategySuggestion]:
```
- Detects: pairs with correlation > 0.7 holding > 40% combined portfolio weight
- Output: Tier PORTFOLIO suggestion to reduce combined allocation

### 2C. `detect_drawdown_tier_miscalibration()`
```python
def detect_drawdown_tier_miscalibration(
    self, historical_drawdowns: list[float],
    current_tiers: list[list[float]],
    min_days: int = 90,
) -> list[StrategySuggestion]:
```
- Detects: tiers that never trigger (too loose) or trigger too often (too tight)
- Safety: only suggests narrowing, never removing or loosening

### 2D. `detect_coordination_gaps()`
```python
def detect_coordination_gaps(
    self, concurrent_positions: dict,  # from 0D output
    existing_coordination: CoordinationConfig,
    min_co_occurrences: int = 50,
) -> list[StrategySuggestion]:
```
- Detects: strategies that frequently collide without coordination rules
- Output: suggests adding cooldown or direction filter

### 2E. `detect_heat_cap_utilization()`
```python
def detect_heat_cap_utilization(
    self, daily_heat_series: list[float],
    heat_cap_R: float,
    min_days: int = 30,
) -> list[StrategySuggestion]:
```
- Detects: consistently >90% (opportunity cost) or <30% (overly conservative)
- Guardrail: max +/-10% adjustment, never below sum of per-bot daily_stop_R

### 2F. Handler integration
- **File**: `orchestrator/handlers.py` → in `handle_weekly_analysis()`, after existing strategy engine calls
- Call each portfolio detector with appropriate data from Phase 0 outputs
- Append returned `StrategySuggestion` objects to the existing `RefinementReport.suggestions` list
- These flow naturally into `refinement_report.json` → weekly prompt → LLM sees them as portfolio findings

---

## Phase 3: Outer Loop Integration (LLM-Reasoned)

### 3A. Extend weekly prompt — augment ALLOCATION ASSESSMENT
- **File**: `analysis/weekly_prompt_assembler.py`
- **Don't create a new section** — extend the existing `## ALLOCATION ASSESSMENT` (line 51) to become `## PORTFOLIO IMPROVEMENT ASSESSMENT`
- Add subsections:
  - Family performance trajectory (from 0C family snapshots)
  - Portfolio rolling metrics trend (from 0F)
  - Drawdown correlation risk (from 0G)
  - Portfolio rule block frequency (from 0B)
  - Portfolio detector findings (from Phase 2, already in refinement_report.json)
- Add instructions:
  - "Propose at most 2 portfolio-level changes per report"
  - "All proposals must cite specific family/bot data and projected portfolio Calmar impact"
  - "portfolio_allocation proposals require 60+ days of evidence"
  - "portfolio_risk_cap and portfolio_drawdown_tier require 90+ days of evidence"

### 3B. Structured output extension
- **File**: `analysis/weekly_prompt_assembler.py` → extend STRUCTURED_OUTPUT JSON spec
- Add `portfolio_proposals` array:
```json
"portfolio_proposals": [
  {
    "proposal_type": "allocation_rebalance|risk_cap_change|coordination_change|drawdown_tier_change",
    "current_config": {"swing": 0.3334, "stock": 0.3333, "momentum": 0.3333},
    "proposed_config": {"swing": 0.40, "stock": 0.30, "momentum": 0.30},
    "evidence_summary": "Swing family Calmar 2.1 vs portfolio 1.4...",
    "expected_portfolio_calmar_delta": 0.15,
    "confidence": 0.6,
    "observation_window_days": 30
  }
]
```

### 3C. Response parser extension
- **File**: `analysis/response_parser.py`
- Parse `portfolio_proposals` from structured output into `PortfolioProposal` objects (from 1C schema)
- Add `portfolio_proposals: list[PortfolioProposal]` field to `ParsedAnalysis`

### 3D. Response validator — portfolio guardrails
- **File**: `analysis/response_validator.py`
- New method `_validate_portfolio_proposals()`:
  - Block allocation changes > 15% per family
  - Block allocation below 5% floor per family
  - Block risk cap increases > 20% of current value
  - Block drawdown tier removals entirely
  - Block stop level loosening (can only tighten)
  - Block proposals with < 60 days evidence (90 for risk/drawdown)
  - Block all portfolio proposals if overall prediction accuracy < 40%
  - Block proposals with confidence < 30% (minimum confidence floor)
  - Block unknown proposal types by default
  - Apply portfolio category scorecard for confidence adjustment
- Add `approved_portfolio_proposals` and `blocked_portfolio_proposals` to `ValidationResult`

### 3E. Handler wiring
- **File**: `orchestrator/handlers.py` → in `handle_weekly_analysis()`, after response parsing
- Extract `parsed.portfolio_proposals` (approved ones from validator)
- Record each as `SuggestionRecord(bot_id="PORTFOLIO", category=proposal_type, tier="portfolio", ...)`
- Check concurrent deployment limit (max 1 DEPLOYED portfolio change)
- Broadcast `portfolio_proposal_recorded` lifecycle events
- Fallback path (validator returns None) preserves portfolio_proposals alongside suggestions

### 3F. Monthly cadence gate
- **No new scheduler job** — the weekly handler already runs
- Add a time-based gate in the handler: only generate portfolio proposals if:
  - Last portfolio proposal was > 30 days ago (allocation) or > 90 days (risk/drawdown)
  - OR there's an emergency signal (portfolio ground truth drop > 10%)
- The portfolio data and detector findings always run (for awareness), but the LLM instruction to propose changes is gated by cadence

### 3G. Permission gates
- **File**: `memory/policies/v1/permission_gates.md`
- `portfolio_allocation` → `requires_approval`
- `portfolio_risk_cap`, `portfolio_drawdown_tier` → `requires_double_approval`
- `portfolio_coordination` → `requires_approval`

---

## Phase 4: Simplified Portfolio Backtesting

### 4A. Portfolio what-if analysis
- **New file**: `skills/portfolio_what_if.py`
- Input: historical daily family PnL series + proposed allocation weights
- Method: linear rescaling — multiply each family's daily PnL by (new_weight / old_weight)
- Output: portfolio Calmar, Sharpe, max drawdown under new allocation
- Limitation: ignores interaction effects from coordination rules, capacity constraints
- **Good enough for**: allocation weight changes (80% of proposals)
- **Not sufficient for**: coordination rule changes, drawdown tier changes (these rely on LLM reasoning + post-deployment measurement)

### 4B. Integration with proposal lifecycle
- Run `portfolio_what_if` before recording portfolio allocation proposals
- Annotate proposals with backtested projected impact
- If backtested Calmar delta is negative, block the proposal automatically
- Store what-if results in `proposal.detection_context` for LLM to reference
- Handler loads family PnL from curated snapshots via `_load_family_pnl_for_what_if()`

### 4C. Full portfolio replay (DEFERRED)
- Only build if simplified what-if proves insufficient after 3+ months of operation
- Would require: multi-strategy trade replay with coordination rules, cooldowns, position limits

---

## Phase 5: Outcome Measurement (Ships With Phase 3)

### 5A. Portfolio ground truth snapshots
- **File**: `skills/ground_truth_computer.py` → new `compute_portfolio_snapshot()` method
- Allocation-weighted composite across all bots: `sum(bot_composite * bot_allocation_pct)`
- Store in `data/findings/portfolio_ground_truth.jsonl`

### 5B. Portfolio outcome measurer
- **New file**: `skills/portfolio_outcome_measurer.py`
- For DEPLOYED portfolio suggestions: measure portfolio composite before vs. after
- Observation window: 30 days minimum (vs. 7 for strategy-level)
- Regime-conditional analysis: if market regime changed significantly during window → INCONCLUSIVE
- Verdict: POSITIVE / NEGATIVE / INCONCLUSIVE
- Store in `data/findings/portfolio_outcomes.jsonl`
- Schedule: check weekly alongside existing `AutoOutcomeMeasurer`

### 5C. Emergency reversal
- If portfolio composite drops > 10% within 14 days of deployment:
  - CRITICAL notification
  - Auto-proposal to revert to previous config (stored in `SuggestionRecord.detection_context`)
  - Reversion gets `auto` permission (no approval needed for reverting to known-good state)

### 5D. Context injection
- **File**: `analysis/context_builder.py`
- New: `load_portfolio_outcomes()` → portfolio suggestion outcome history
- New: `load_portfolio_metrics()` → latest portfolio rolling metrics
- Both injected into `base_package().data` so every prompt sees portfolio track record

---

## Risk Guardrails (Hard Constraints — Code-Enforced)

| Guardrail | Rule | Enforcement Point |
|-----------|------|-------------------|
| Max allocation change per cycle | 15% per family | `response_validator.py` |
| Minimum allocation floor | No family below 5% | `response_validator.py` |
| heat_cap_R change limit | +/-10% per quarterly review | `response_validator.py` |
| Stop level reduction | **Never** loosened | `response_validator.py` |
| Drawdown tier removal | **Blocked** entirely | `response_validator.py` |
| Evidence minimum | 60d allocation, 90d risk/drawdown | `response_validator.py` |
| Prediction accuracy gate | Block all portfolio proposals if < 40% | `response_validator.py` |
| Confidence floor | Block proposals with confidence < 30% | `response_validator.py` |
| Unknown type safety | Block unrecognized proposal types | `response_validator.py` |
| Concurrent change limit | Max 1 DEPLOYED portfolio change | `suggestion_tracker.py` |
| Cadence gate | 30d allocation, 90d risk/drawdown since last proposal | `handlers.py` |

---

## Post-Implementation Review Fixes (2026-03-22)

After comprehensive code review, the following issues were found and fixed:

### Critical Runtime Bugs Fixed
1. **Missing detector invocations** — `detect_drawdown_tier_miscalibration` and `detect_coordination_gaps` were defined but never called from `_run_portfolio_detectors` in handlers.py. Added both with data loading.
2. **PortfolioWhatIf constructor mismatch** — Handler called `PortfolioWhatIf(curated_dir=...)` but actual signature requires `family_daily_pnl` + `current_weights`. Added `_load_family_pnl_for_what_if()` helper.
3. **Fallback drops portfolio proposals** — When validator returned None, fallback `ValidationResult` only preserved suggestions and predictions, silently discarding portfolio proposals.

### Guardrail Gaps Fixed
4. **Unknown proposal types auto-approved** — `_check_portfolio_guardrails` returned None for unrecognized types. Added catch-all block.
5. **No confidence floor** — Added `_MIN_PORTFOLIO_CONFIDENCE = 0.3` check.
6. **Coordination gaps always blocked** — Detector set `evidence_days=0` but validator requires >=60 days. Fixed to derive from observation metadata.

### Code Quality Fixes
7. `SuggestionRecord.confidence` — Added `Field(ge=0.0, le=1.0)` bounds.
8. Dead code removal — Redundant `max_dd > 0` ternaries in `_calmar()` methods.
9. Empty collection guard — `_build_portfolio_series` crash on empty family PnL.
10. Redundant division check — Duplicate `total_pnl != 0` in `detect_family_imbalance`.

---

## Files Summary

### New files (5)
| File | Purpose |
|------|---------|
| `schemas/portfolio_proposal.py` | PortfolioProposal, PortfolioProposalType |
| `schemas/portfolio_metrics.py` | FamilyDailySnapshot, PortfolioRollingMetrics, DrawdownCorrelation |
| `skills/portfolio_metrics_tracker.py` | Rolling portfolio Sharpe/Sortino/Calmar |
| `skills/portfolio_what_if.py` | Simplified what-if analysis |
| `skills/portfolio_outcome_measurer.py` | Portfolio suggestion outcome measurement |

### Modified files (16)
| File | Change |
|------|--------|
| `skills/compute_portfolio_risk.py` | `_compute_correlation_matrix()`, `_compute_sector_exposure()`, `compute_drawdown_correlation()` |
| `skills/build_daily_metrics.py` | `build_portfolio_rules_summary()`, `build_family_snapshots()`, consume `correlated_pairs_detail` |
| `analysis/strategy_engine.py` | 5 new `detect_*()` portfolio methods returning `list[StrategySuggestion]` |
| `analysis/weekly_prompt_assembler.py` | Extend ALLOCATION ASSESSMENT → PORTFOLIO IMPROVEMENT, add `portfolio_proposals` to structured output |
| `analysis/prompt_assembler.py` | Add 4 new portfolio files to `_CURATED_FILES` |
| `analysis/response_parser.py` | Parse `portfolio_proposals` → `PortfolioProposal` objects, add field to `ParsedAnalysis` |
| `analysis/response_validator.py` | `_validate_portfolio_proposals()` with all hard guardrails + confidence floor + unknown type block |
| `analysis/context_builder.py` | `load_portfolio_outcomes()`, `load_portfolio_metrics()` |
| `schemas/agent_response.py` | Add `portfolio_proposals` field to `ParsedAnalysis`, extend `CATEGORY_TO_TIER` |
| `schemas/strategy_suggestions.py` | Add `PORTFOLIO` to `SuggestionTier` enum |
| `schemas/suggestion_tracking.py` | Add confidence bounds `Field(ge=0.0, le=1.0)` to `SuggestionRecord` |
| `skills/suggestion_tracker.py` | Concurrent deployment check for `bot_id="PORTFOLIO"`, `proposed_at` in date lookup |
| `skills/suggestion_scorer.py` | Portfolio-level category scoring |
| `skills/ground_truth_computer.py` | `compute_portfolio_snapshot()` |
| `orchestrator/handlers.py` | Call all 5 portfolio detectors, record proposals, cadence gate, what-if helper, fallback fix |
| `memory/policies/v1/permission_gates.md` | Portfolio-specific permission rules |
| `memory/policies/v1/trading_rules.md` | Portfolio change constraints |

---

## Verification

1. **Unit tests**: Each phase ships with tests for new schemas, detectors, lifecycle methods
2. **Integration test**: Family snapshot → portfolio detector → weekly prompt → structured output parsing → suggestion recording → outcome measurement
3. **Regression**: All 2900 tests pass (no per-bot behavior changes)
4. **Guardrail tests**: Verify every hard constraint — allocation cap (15%), tier removal block, evidence minimum (60d/90d), concurrent deployment limit (1), cadence gate, confidence floor (30%), unknown type block
5. **Manual validation**: Run weekly analysis with sample data, verify PORTFOLIO IMPROVEMENT ASSESSMENT section appears with grounded proposals referencing specific family metrics and correlation data
