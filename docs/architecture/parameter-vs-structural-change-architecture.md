# Parameter vs. Structural Change Architecture

How the trading assistant ensures parameter-level changes are handled by an autonomous inner loop, while structural changes require genuine LLM analytical reasoning with human-in-the-loop oversight.

---

## Design Principle

The system splits all trading system changes into two categories based on a single criterion: **can the change be bounded and backtested?**

| Property | Parameter Changes | Structural Changes |
|---|---|---|
| **Scope** | Single numeric/categorical value with `valid_range` or `valid_values` | New logic, strategy modifications, filter implementations |
| **Testability** | Backtestable in milliseconds via trade replay | Not backtestable — requires live observation |
| **Bounded?** | Yes: `ConfigRegistry` defines exact bounds per parameter | No: unbounded design space |
| **Decision maker** | Autonomous inner loop (no LLM in the critical path) | LLM as reasoner + human approval |
| **Feedback speed** | Fast (backtest) + slow (live calibration) | Slow only (A/B experiment → weeks of observation) |
| **Examples** | Stop loss ATR multiplier, signal threshold, position sizing % | New filter logic, FSM state changes, new indicator |

This mirrors the autoresearch pattern: bounded modifications with a clear metric run autonomously; unbounded modifications require human judgment.

---

## Part 1: The Autonomous Parameter Inner Loop

### 1.1 How Parameters Enter the System

The LLM (Claude) proposes parameter changes during daily and weekly analysis. Both prompt assemblers (`analysis/prompt_assembler.py`, `analysis/weekly_prompt_assembler.py`) require a `<!-- STRUCTURED_OUTPUT -->` JSON block containing `suggestions` with fields: `suggestion_id`, `bot_id`, `category`, `title`, `confidence`, `proposed_value`, and `target_param`.

The LLM's proposal is informed by rich context injected via `ContextBuilder.base_package()`:

- **`category_scorecard`** — per-(bot, category) historical win rates from outcomes, so the LLM avoids proposing changes in categories that historically fail
- **`search_reports`** — recent parameter search results showing what was explored and what routing decisions were made, preventing the LLM from re-proposing values the system already tested and discarded
- **`backtest_reliability`** — per-category accuracy of backtest predictions vs. live outcomes, so the LLM can calibrate confidence appropriately
- **`active_suggestions`** — what's already in-flight, preventing duplicates
- **`rejected_suggestions`** — what was explicitly rejected, with instructions not to re-propose

### 1.2 Parameter Definition and Bounds

Every tunable parameter is defined in `ConfigRegistry` (`skills/config_registry.py`) via YAML bot config profiles. Each `ParameterDefinition` (`schemas/autonomous_pipeline.py`) specifies:

```
param_name, bot_id, param_type (YAML_FIELD | PYTHON_CONSTANT),
file_path, yaml_key/python_path, current_value,
valid_range: (lo, hi), valid_values: [...],
value_type: int|float|bool|str,
category: signal|exit_timing|filter_threshold|stop_loss|position_sizing|regime_gate,
is_safety_critical: bool
```

This is the "bounded environment" requirement from autoresearch — the system knows exactly what values are legal and where they live in the bot's codebase.

### 1.3 The Search Loop (ParameterSearcher)

Once a suggestion is recorded, `AutonomousPipeline._build_parameter_request()` routes it to `ParameterSearcher.search()` (`skills/parameter_searcher.py`). This is the autoresearch-style inner loop — **no LLM is involved**:

```
For each suggestion:
  1. Compute baseline at current production value
  2. Build candidate grid (up to 11 values, ±30% around proposed, within valid_range)
  3. For each candidate:
     a. BacktestSimulator.simulate() — replay trades with param override
     b. RobustnessTester.evaluate() — neighborhood stability + regime stability
     c. Cost sensitivity — re-simulate at 1.5x fees/slippage
  4. Filter candidates by safety (positive Sharpe, sufficient trades, cost-resilient)
  5. Rank passing candidates by composite score
  6. Route based on best candidate vs thresholds
```

**Grid generation** (`_build_grid`): For continuous parameters, generates a linspace of up to `_MAX_CANDIDATES=11` values between `max(valid_range[0], proposed*0.7)` and `min(valid_range[1], proposed*1.3)`. For categorical parameters, tests all `valid_values`. Always includes both the proposed value and the current production value. Integer parameters are rounded and deduplicated.

**Per-candidate evaluation** (`_evaluate_candidate`):

1. **Backtest** — `BacktestSimulator.simulate()` replays historical trades with the candidate parameter value applied. It filters trades by param-gated thresholds, includes missed opportunities that would have been captured, and applies `CostModel` for realistic fee/slippage modeling. Returns `SimulationMetrics` (Sharpe, win rate, drawdown, profit factor, regime-bucketed PnL).

2. **Robustness** — `RobustnessTester.evaluate()` runs two tests, each worth 50 points: neighborhood stability (does Sharpe hold at nearby values?) and regime stability (is the strategy profitable across market regimes?). Returns `RobustnessResult` with `neighborhood_stable`, `regime_stable`, and a 0–100 `robustness_score`.

3. **Cost sensitivity** — Re-runs the simulation at 1.5x cost multiplier. If Sharpe goes negative under stressed costs, the candidate fails safety.

**Composite scoring** (internal ranking, aligned with ground truth excl. process_quality, renormalized to 90%):
```
0.333 * expected_r_ratio + 0.222 * calmar_ratio + 0.167 * profit_factor_ratio
+ 0.167 * expectancy_ratio - 0.111 * max(0, drawdown_increase)
```
Where ratios are relative to the baseline at the current production value.

**Safety gates** — A candidate is rejected if: negative Sharpe, fewer than 5 trades, or negative Sharpe at 1.5x costs.

### 1.4 Three-Way Routing

The best passing candidate is routed based on module-level thresholds:

| Route | Condition | What happens |
|---|---|---|
| **APPROVE** | `improvement >= 1.05` AND `robustness >= 70` | Creates `ApprovalRequest` with `best_value`, sent to Telegram for human approval |
| **EXPERIMENT** | `improvement >= 0.95` AND `robustness >= 50` | Routes to A/B experiment via `ExperimentConfigGenerator` |
| **DISCARD** | Below thresholds or no candidates pass safety | Suggestion killed; negative signal recorded for weekly synthesis |

Safety-critical parameters (e.g., risk limits) use a higher APPROVE threshold of 1.10 (10% improvement required).

**Key insight**: The `best_value` may differ from the LLM's originally proposed value. The system found a better value through neighborhood search. This is the core value of the inner loop — the LLM identifies *what* to change, the system finds *the optimal value*.

### 1.5 Calibration Override

Before finalizing APPROVE routing, `BacktestCalibrationTracker.get_approval_modifier()` checks the historical reliability of backtests for this `(bot_id, param_category)` pair:

- `reliability >= 0.70` with `n >= 5` → **fast_track** (backtest is trustworthy)
- `reliability < 0.50` with `n >= 5` → **require_experiment** (override APPROVE → EXPERIMENT)
- Otherwise → **normal** (proceed as routed)

This means the system automatically downgrades APPROVE to EXPERIMENT for parameter categories where backtest predictions have been historically inaccurate. The system learns which categories it can trust.

### 1.6 The Meta-Learning Loop (Calibration)

```
ParameterSearcher routes APPROVE
  → BacktestCalibrationTracker.record_prediction(predicted_improvement, predicted_routing)
  → Human approves via Telegram → change deployed
  → AutoOutcomeMeasurer.measure() (weekly, 7 days after deployment)
    → Compares before/after performance with regime matching and concurrent change detection
    → BacktestCalibrationTracker.record_outcome(actual_composite_delta)
    → prediction_correct = (predicted_improvement > 1.0) == (actual_delta > 0)
  → Next time ParameterSearcher processes a suggestion in this category:
    → get_approval_modifier() uses updated reliability
    → System self-corrects routing decisions
```

The calibration tracker accumulates silently for the first 5 predictions (`_MIN_SAMPLES`), then begins influencing routing. This prevents premature penalization.

### 1.7 The Immutable Ground Truth

`GroundTruthComputer` (`skills/ground_truth_computer.py`) computes a single composite score from six z-score-normalized metrics with fixed weights, aligned with `soul.md` priorities:

```
composite = 0.30 * expected_r_z + 0.20 * calmar_z + 0.15 * profit_factor_z
          + 0.15 * expectancy_z + 0.10 * inv_drawdown_z + 0.10 * process_quality_z
```

- **Expected total return (30%)**: annualized net PnL — primary optimization target
- **Calmar ratio (20%)**: soul.md's preferred risk-adjusted metric; captures return/drawdown tradeoff
- **Profit factor (15%)**: gross_wins / gross_losses quality ratio
- **Expectancy (15%)**: win_rate × (avg_win / avg_loss) — the expectancy equation
- **Inverse drawdown (10%)**: hard constraint emphasis
- **Process quality (10%)**: process over outcomes; anti-gaming safeguard

This is the trading equivalent of autoresearch's `evaluate_bpb()` — the ground truth metric that the agent cannot game. The file is protected by double-approval in `permission_gates.md`. The composite score is used by `LearningCycle` for weekly ground truth snapshots. The inner loop's `_composite_score` mirrors these priorities (excl. process_quality, renormalized to 90%) using ratio-based comparison.

---

## Part 2: LLM-Reasoned Structural Changes

### 2.1 What Qualifies as Structural

Structural changes are unbounded modifications that cannot be backtested: new strategy logic, FSM state changes, new filter implementations, architecture changes, new indicators. These are recorded as suggestions with `tier="hypothesis"` and route to a fundamentally different pipeline.

### 2.2 How the LLM Proposes Structural Changes

Three prompt assemblers ask Claude for structural proposals:

**Daily analysis** (`analysis/prompt_assembler.py`): Asks Claude to emit `structural_proposals` in the structured output block. Each must include a `hypothesis_id` (from the injected `structural_hypotheses` context), `reversibility`, `estimated_complexity`, and a list of `acceptance_criteria` (metric, direction, minimum_change, observation_window_days, minimum_trade_count). This forces the LLM to think in terms of falsifiable, measurable hypotheses.

**Weekly analysis** (`analysis/weekly_prompt_assembler.py`): Adds a `STRATEGY PROPOSALS` section requiring Calmar ratio impact quantification, statistical evidence, falsifiable acceptance criteria, and reference to existing hypothesis IDs. Maximum 5 suggestions ranked by confidence.

**Discovery agent** (`analysis/discovery_prompt_assembler.py`): Has raw JSONL access to find patterns outside automated detector coverage. Must explain methodology and provide structural proposals in the same schema.

### 2.3 What the LLM Sees (Context for Reasoning)

The LLM receives a rich context package via `ContextBuilder.base_package()` specifically designed to support genuine analytical reasoning:

| Context Item | Purpose | Source |
|---|---|---|
| `ground_truth_trend` | 12-week composite score trajectory per bot | `LearningLedger` |
| `last_week_synthesis` | What worked, what failed, lessons learned | `RetrospectiveBuilder` |
| `active_experiments` | Currently running A/B tests (don't re-propose) | `StructuralExperimentTracker` |
| `experiment_track_record` | Historical pass/fail rates for structural experiments | `StructuralExperimentTracker` |
| `hypothesis_track_record` | Per-hypothesis effectiveness scores | `HypothesisLibrary` |
| `category_scorecard` | Per-category win rates from measured outcomes | `SuggestionScorer` |
| `prediction_accuracy_by_metric` | How accurate past predictions were | `PredictionTracker` |
| `outcome_reasonings` | Causal analysis of WHY past changes worked/failed | `OutcomeReasoningPrompt` |
| `discoveries` | Patterns found by the discovery agent | Discovery pipeline |
| `search_reports` | What the parameter inner loop tested and found | `ParameterSearcher` |
| `backtest_reliability` | Which categories have reliable backtests | `BacktestCalibrationTracker` |

This context enables the LLM to reason about:
- **What has been tried** (active experiments, search reports, active suggestions)
- **What has worked** (hypothesis track record, category scorecard, outcome reasonings)
- **What the system's blind spots are** (backtest reliability, prediction accuracy)
- **What direction things are heading** (ground truth trend, weekly synthesis)

### 2.4 Response Validation (Guard Rails)

Before structural proposals reach the pipeline, `ResponseValidator` (`analysis/response_validator.py`) applies three filters:

1. **Rejection fuzzy match** — Jaccard similarity against `rejected_suggestions` prevents re-proposing rejected ideas in different words
2. **Category track record** — Blocks suggestions in categories with `win_rate < 30%` and `n >= 5` measured outcomes
3. **Confidence capping** — Adjusts confidence based on `ForecastMetaAnalysis` calibration data

A `Validator Notes` section is appended to the report, and all blocks are logged to `validation_log.jsonl`.

### 2.5 The Structural Pipeline

Validated structural suggestions with `tier="hypothesis"` route to `_build_structural_request()` in `AutonomousPipeline`:

1. Reads `implementation_context` (file changes, planned files, notes, verification commands)
2. **Permission gating** — `RepoChangeGuard` checks every planned file against the bot's `allowed_edit_paths` allowlist (fnmatch). Then maps paths to three permission tiers:
   - `auto` — docs, tests, scripts (no human review)
   - `requires_approval` — strategies, signals, filters, execution, config (one human approval)
   - `requires_double_approval` — kill switches, deploy scripts, secrets (two human approvals)
3. Builds an `ApprovalRequest` with `change_kind=STRUCTURAL_CHANGE` and the determined `risk_tier`
4. Sends to Telegram with approve/reject inline keyboard

### 2.6 A/B Experiments for Structural Changes

When a structural change is approved, `ExperimentConfigGenerator` (`skills/experiment_config_generator.py`) creates an experiment config with `control` (current value, 50% allocation) and `treatment` (proposed, 50% allocation) variants using hash-based trade allocation. This produces a `PRRequest` with the experiment YAML as a `FileChange`.

`StructuralExperimentTracker` (`skills/structural_experiment_tracker.py`) manages the lifecycle:

```
PROPOSED → activate() → ACTIVE → resolve(criteria_met, actual_values) → PASSED / FAILED
                                                                      → abandon() → ABANDONED
```

An experiment is `is_evaluable` when `now >= activated_at + max(observation_window_days)`. Each experiment carries `acceptance_criteria` with `metric`, `direction`, `minimum_change`, and `minimum_trade_count` — the same criteria the LLM was required to specify upfront.

### 2.7 Hypothesis Lifecycle

`HypothesisLibrary` (`skills/hypothesis_library.py`) tracks the full lifecycle of structural ideas:

- `record_proposal(id)` — increments `times_proposed`
- `record_acceptance(id)` — increments `times_accepted`
- `record_rejection(id)` — increments `times_rejected`; **auto-retires** if `times_rejected >= 3` AND `effectiveness <= 0`
- `record_outcome(id, positive)` — increments `outcomes_positive/negative`
- `effectiveness` property: `(positive - negative) / max(1, positive + negative)` — ranges from -1.0 to +1.0
- Auto-retirement kills ideas that keep failing
- `get_track_record()` feeds back into the LLM's context for the next analysis cycle

---

## Part 3: How the Two Paths Interact

### 3.1 The LLM Informs, the System Decides (Parameters)

For parameters, the LLM's role is **identification**: it spots that a signal threshold seems suboptimal based on pattern analysis. The system's role is **optimization**: the inner loop tests 11 neighborhood values, evaluates robustness, stress-tests costs, and picks the best. The LLM never sees backtests or routing decisions — it just gets informed of outcomes via `search_reports` in the next analysis cycle.

### 3.2 The LLM Reasons, Humans Approve (Structural)

For structural changes, the LLM's role is **genuine analytical reasoning**: it synthesizes ground truth trends, outcome causality, hypothesis track records, and pattern discoveries to propose falsifiable hypotheses with measurable acceptance criteria. Humans approve or reject via Telegram. The system then manages the A/B experiment lifecycle autonomously.

### 3.3 Cross-Path Feedback

The two paths share a common feedback infrastructure:

```
Parameter inner loop results (search_reports, backtest_reliability)
  → Injected into LLM context
  → LLM adjusts structural proposals based on what the inner loop found
  → e.g., "Parameter tuning for exit_timing has 0.3 reliability —
           consider structural changes to the exit logic instead"

Structural experiment outcomes (experiment_track_record, hypothesis_track_record)
  → Feed into HypothesisLibrary effectiveness
  → Influence LearningCycle experiment selection
  → LLM sees what structural changes worked/failed
```

### 3.4 Weekly Learning Cycle Integration

`LearningCycle.run()` (`skills/learning_cycle.py`) ties both paths together weekly:

1. **Ground truth snapshots** — Computes composite score delta per bot (immutable metric)
2. **Retrospective synthesis** — Determines what worked/failed across both parameter and structural changes
3. **Hypothesis lifecycle updates** — Updates effectiveness from verdicts
4. **Category recalibration** — Adjusts category confidence multipliers based on measured outcomes
5. **Calibration logging** — Writes per-(bot, category) backtest reliability summaries
6. **Experiment selection** — Picks next structural experiments from hypotheses with positive effectiveness
7. **Ledger record** — Persists all metrics for the next cycle's context

---

## Summary: Division of Labor

```
                    PARAMETER CHANGES                    STRUCTURAL CHANGES
                    ─────────────────                    ──────────────────

LLM's role:         Identify what to change              Reason about why and how
                    ("signal threshold seems high")      ("exit logic has a structural flaw
                                                          because regime transitions cause
                                                          premature stops — hypothesis H7")

System's role:      Find optimal value autonomously      Manage experiment lifecycle
                    (grid search → backtest →            (A/B split → observe → evaluate
                     robustness → cost sensitivity)       acceptance criteria)

Human's role:       Approve final value via Telegram     Approve hypothesis via Telegram
                    (single approval)                    (single or double approval based
                                                          on file path risk tier)

Feedback loop:      Fast: backtest (ms) + calibration    Slow: observation window (weeks)
                    (weekly outcome measurement)          → pass/fail → effectiveness score

Anti-gaming:        Composite score (internal ranking)    Acceptance criteria (defined upfront
                    is NOT the ground truth metric.       by the LLM, evaluated by the system)
                    GroundTruthComputer's formula is      Humans can reject proposals.
                    double-approval protected.            Auto-retirement after 3 rejections.
```
