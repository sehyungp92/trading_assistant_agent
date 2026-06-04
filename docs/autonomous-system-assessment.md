# Autonomous System Assessment

_Post-learning-loop-closure assessment of the trading assistant's self-improvement capabilities._

## Section 1: Current System Effectiveness (Post-Fixes)

### What Works End-to-End

After closing 8 integration gaps, the following loops are fully operational:

**Suggestion Lifecycle (closed)**
```
Claude analysis → parse_response() → ResponseValidator → approved suggestions
    → _record_agent_suggestions() → SuggestionTracker (suggestions.jsonl)
    → user "approve #ID" → FeedbackHandler → implement()
    → AutoOutcomeMeasurer (weekly) → outcomes.jsonl
    → SuggestionScorer → category_scorecard → next prompt
    → ResponseValidator blocks poor-track-record categories
```

**Hypothesis Feedback (closed)**
```
Strategy Engine → keyword-match → HypothesisLibrary.get_active() (JSONL-backed)
    → weekly prompt includes effectiveness scores
    → user accepts/rejects → record_acceptance/rejection
    → suggestion measured → hypothesis_library.record_outcome()
    → auto-retire after 3 rejections + non-positive effectiveness
    → retired hypotheses excluded from future prompts
```

**Prediction Calibration (closed)**
```
Claude predictions → parse_response() → PredictionTracker.record_predictions()
    → _measure_outcomes() → evaluate_predictions() against curated data
    → ForecastTracker → rolling accuracy + calibration adjustment
    → ContextBuilder.load_prediction_accuracy(curated_dir) → real per-metric accuracy
    → ResponseValidator caps confidence when rolling accuracy < 50%
```

**Transfer Learning (closed)**
```
PatternLibrary → TransferProposalBuilder(findings_dir=...) → proposals in weekly prompt
    → _measure_transfer_outcomes() → transfer_outcomes.jsonl
    → load_track_record_from_file() (no MagicMock) → score adjustment ±0.1/0.2
    → next proposal cycle uses adjusted scores
```

**Validation Logging (closed)**
```
ResponseValidator → blocked suggestions → validation_log.jsonl
    → now includes blocked_details: [{title, reason, bot_id}]
    → enables post-hoc analysis of what the system is filtering and why
```

### Remaining Advisory-Only Constraints

These mechanisms exist but operate as **soft guidance**, not hard enforcement:

| Mechanism | What It Does | Why It's Advisory |
|-----------|-------------|-------------------|
| Strategy Engine | Flags issues using hardcoded thresholds | Thresholds don't adapt from outcome data |
| ResponseValidator | Blocks rejected/poor-track-record suggestions | Doesn't learn new blocking patterns autonomously |
| Prompt instructions | "Reference active suggestions", "Include hypothesis IDs" | Claude may not comply perfectly every time |
| Confidence calibration | Multiplies by rolling accuracy | Linear adjustment, no Bayesian updating |
| Category scorecard | Per-(bot, category) win rates | Requires 3+ samples to activate |

### Data Flow Diagram (Post-Fixes)

```
┌─────────────────────────────────────────────────────────────────────┐
│                        ANALYSIS PIPELINE                            │
│                                                                     │
│  PromptAssembler ──→ Claude CLI ──→ parse_response()                │
│       ↑                                    ↓                        │
│       │                           ResponseValidator                 │
│       │                          ╱              ╲                   │
│       │                   approved          blocked                 │
│       │                      ↓                 ↓                    │
│       │           SuggestionTracker    validation_log.jsonl         │
│       │              (with hypothesis_id)  (with blocked_details)   │
│       │                      ↓                                      │
│       │              PredictionTracker                              │
│       │                      ↓                                      │
│       │         ┌────────────────────────┐                          │
│       │         │  WEEKLY OUTCOME CYCLE  │                          │
│       │         │  AutoOutcomeMeasurer   │                          │
│       │         │  → outcomes.jsonl      │                          │
│       │         │  → hypothesis outcome  │                          │
│       │         │  → prediction eval     │                          │
│       │         └────────────────────────┘                          │
│       │                      ↓                                      │
│       │            ContextBuilder.base_package()                    │
│       │           ╱     ╱      ╱       ╲       ╲                    │
│       └── scorecard  forecast  outcomes  hypotheses  predictions    │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Section 2: Current Limitations

### 2.1 Strategy Engine Uses Hardcoded Thresholds

The 4-tier strategy engine (`analysis/strategy_engine.py`) detects issues using fixed thresholds:
- Alpha decay: `win_correlation < 0.1 for 30+ days`
- Filter over-blocking: `blocking > 30%`
- Exit timing: `exit_efficiency < 50%`

These thresholds were set manually and never update from outcome data. A suggestion flagged at 29% filter blocking is invisible; one at 31% triggers. The system cannot learn that for a specific bot, the optimal threshold might be 25%.

### 2.2 Validator Enforces But Doesn't Learn

`ResponseValidator` blocks suggestions matching rejected ones (Jaccard > 0.6) or poor-track-record categories (win_rate < 0.3, n >= 3). However:
- It cannot discover new blocking patterns from outcomes
- The similarity threshold (0.6) is fixed
- It has no concept of "similar but different enough to try"

### 2.3 Backtesting Not Wired to Suggestion Validation

The orchestrator has a complete backtesting stack — `BacktestSimulator.simulate()` returns `SimulationMetrics` (Sharpe, max DD, profit factor), and the full WFO pipeline (`skills/run_wfo.py`) produces ADOPT/TEST_FURTHER/REJECT recommendations using `fold_generator.py`, `param_optimizer.py`, and `robustness_tester.py`.

Additionally, both swing_trader and momentum_trader have their own WFO infrastructure:
- `backtest/optimization/walk_forward.py` — `WalkForwardValidator` with `RobustnessThresholds`
- `backtest/optimization/runner.py` — Two-stage optimization (LHS coarse + Optuna TPE refinement)
- `backtest/optimization/param_space.py` — Parameterized grid definitions

**Actual gap:** These run as standalone WFO tasks. They are **not wired to validate individual suggestions** before delivery. Suggestions still go from Claude → validator → user without quantitative pre-validation. The `expected_impact` field on `AgentSuggestion` is Claude's estimate, not a computed value from backtesting.

### 2.4 No PR Automation for Bot Parameter Changes

When a suggestion is approved and implemented, the actual parameter change on the bot is manual:
1. User reads the suggestion
2. User manually edits bot config on VPS
3. User marks as "implemented" via text command

There's no `git` integration to create PRs against bot repositories, no deployment pipeline to push changes to VPSes.

**Note:** `skills/github_pr.py` does not exist despite being listed in CLAUDE.md's skills directory. `pr_report_builder.py` exists for formatting PR markdown output. The `SkillsRegistry` has a `PR_REVIEW` agent type with `create_draft_pr` capability but forbids `merge_pr` for all agents.

### 2.5 A/B Testing Infrastructure Exists But Is Not Activated

All three bot repos have A/B experiment infrastructure:
- **k_stock_trader:** `experiment_id` and `experiment_variant` fields in TradeEvent schema, config YAML experiment sections per strategy
- **momentum_trader:** Full framework — `ExperimentRegistry` + `ExperimentMetadata` (YAML-driven, strategy-scoped, date-bounded) + `ExperimentAnalysis` with Welch's t-test, per-variant stats (win_rate, avg_pnl, Sharpe, total_pnl), and statistical significance testing (p-value)
- **swing_trader:** `experiment_id`/`experiment_variant` on `SymbolConfig` + `AblationFlags` framework with 16+ toggleable filters for offline contribution analysis

**Actual gap:** None of this is activated for live trading. The experiment YAML configs are empty templates. There's no runtime variant routing — all trades use the same parameters. The analysis code exists but has no data to consume yet. The orchestrator has no mechanism to create experiment configs, monitor experiment groups, or trigger auto-conclusion.

### 2.6 Human Approval via Text Commands Only

Approval workflows use unstructured text commands ("approve suggestion #abc123"). There's no:
- Telegram inline keyboard for approve/reject with context preview
- Diff view showing current vs proposed parameters
- Confidence/risk assessment attached to the approval prompt

### 2.7 Limited Direct Bot Parameter Modification

The system is read-only with respect to bots (by design). Even approved changes require manual intervention. This is a safety feature but limits autonomy.

**Bot-side update mechanisms differ:**
- **k_stock_trader:** `KMPSwitches` has `update_from_yaml()` for runtime parameter reload without restart — YAML-only changes can be hot-loaded
- **swing_trader & momentum_trader:** Use frozen dataclasses and module-level constants — changes require code edit + Docker rebuild

### 2.8 Passive Pattern Library and Transfer Proposals

`PatternLibrary` and `TransferProposalBuilder` operate on manually entered patterns. The system:
- Cannot automatically extract patterns from successful bot configurations
- Cannot detect when a pattern emerges from trade data
- Requires human curation of the pattern catalog

### 2.9 Event Richness Richer Than Originally Assessed

Bots emit more structured data than the core event types suggest:
- All three bots include `experiment_id`/`experiment_variant` on TradeEvent (ready for A/B testing)
- **k_stock_trader:** tracks `would_block_count`/`would_block_log` per switch for permissive vs strict comparison
- **momentum_trader:** has `process_scoring_rules.yaml` for quality scoring and `simulation_policies.yaml` for backtest configs

**Remaining gap:** The system still cannot request richer instrumentation on-demand (e.g., real-time indicator values, order book snapshots, or pre-trade signal confidence distributions). These would require bot-side code changes.

---

## Section 3: Medium-Term Roadmap for Autonomous Improvement

### A. Adaptive Strategy Engine

**Goal:** Strategy engine thresholds auto-tune from outcome data.

**Steps:**
1. Record threshold-at-detection alongside each suggestion (e.g., "filter_blocking_pct: 0.32")
2. After outcome measurement, correlate threshold values with positive/negative outcomes
3. Compute per-bot, per-detector optimal thresholds using logistic regression on outcome data
4. Replace hardcoded thresholds with learned thresholds (min 10 outcomes per detector)
5. Add a "threshold confidence" metric — low-sample detectors keep conservative defaults

**Key files:** `analysis/strategy_engine.py`, `schemas/suggestion_tracking.py` (add `detection_context`), `skills/suggestion_scorer.py`

### B. Backtested Suggestions

**Goal:** Every parameter/filter suggestion includes a quantitative impact estimate from historical replay.

**Steps:**
1. For parameter suggestions: extract current and proposed values, run WFO `backtest_simulator` on recent 30d data
2. For filter suggestions: replay missed_opportunities with modified threshold
3. Attach `BacktestResult` to `AgentSuggestion` before validation
4. ResponseValidator can then block suggestions with negative backtest results
5. User sees "Backtest: +2.3% PnL over 30d (47 simulated trades)" alongside each suggestion

**Key files:** `skills/run_backtest.py`, `analysis/response_validator.py`, `schemas/agent_response.py` (add `backtest_result`)

**Status:** Backtesting infrastructure already exists (`BacktestSimulator`, `CostModel`, WFO pipeline). Bot repos also have their own WFO runners. Gap is wiring these to validate individual suggestions before delivery.

### C. PR Automation Pipeline

**Goal:** Approved suggestions automatically generate PRs against bot repositories.

**Steps:**
1. Map suggestion types to config file paths in bot repos (e.g., "stop_loss" → `config/strategy.yaml:stop_loss_pct`)
2. Clone/checkout bot repo on approval event
3. Apply parameter change as a code modification
4. Run bot's unit tests
5. Create PR with: change description, backtest results, suggestion history, rollback instructions
6. Await merge via existing permission_gates system

**Key files:** `skills/github_pr.py` (exists but needs extension), new `skills/bot_config_modifier.py`

### D. Human-in-the-Loop Approval UX

**Goal:** Rich Telegram/Discord approval flow with context and one-tap actions.

**Steps:**
1. Extend `TelegramRenderer` with inline keyboard buttons: [Approve] [Reject] [Details] [Backtest]
2. On [Details]: show current value, proposed value, backtest results, category scorecard
3. On [Approve]: trigger SuggestionTracker.implement() + optionally kick off PR pipeline
4. On [Reject]: prompt for reason (free text or preset: "too risky", "not now", "wrong direction")
5. Thread-based conversations in Discord for complex discussions about suggestions

**Key files:** `comms/telegram_handlers.py`, `comms/telegram_renderer.py`, `orchestrator/handlers.py` (feedback routing)

### E. Bot-Side Instrumentation Enrichment

**Goal:** Richer event data from bots for better analysis.

**Steps:**
1. Add `IndicatorSnapshot` event type: signal values at decision time
2. Add `OrderBookContext` event type: spread, depth, imbalance at entry/exit
3. Add `ParameterChangeEvent`: automatic emission when bot config changes
4. Add `FilterDecisionEvent`: per-filter pass/block with threshold and actual value
5. Extend relay schema to handle new event types
6. Update `build_daily_metrics.py` to ingest enriched data

**Key files:** Bot sidecar code (external repos), `schemas/events.py`, `skills/build_daily_metrics.py`

**Status:** Partially complete. All three bots already emit `experiment_id`/`experiment_variant` on TradeEvent. k_stock_trader tracks per-switch `would_block_count`/`would_block_log`. momentum_trader has `process_scoring_rules.yaml` and `simulation_policies.yaml`. Remaining work is adding new event types (IndicatorSnapshot, OrderBookContext, FilterDecisionEvent).

### F. A/B Testing Framework

**Goal:** Controlled experiments with statistical rigor and automatic rollback.

**Steps:**
1. Define `Experiment` schema: control params, treatment params, allocation %, duration, success metric
2. Bot-side: experiment-aware parameter selection (hash trade_id to assign group)
3. Orchestrator: track per-group metrics via enriched events
4. Statistical test module: compute p-value, confidence interval, effect size
5. Auto-conclude: stop experiment when significance threshold reached or duration expires
6. Auto-rollback: revert to control if treatment is significantly worse

**Key files:** New `schemas/experiments.py`, new `skills/experiment_manager.py`, bot config extension

**Status:** Bot-side infrastructure largely exists. momentum_trader has full `ExperimentRegistry` + `ExperimentAnalysis` with statistical testing. swing_trader has `AblationFlags` with 16+ toggleable filters. All bots have experiment fields on TradeEvent. Gap is activation: creating experiment configs, runtime variant routing, and orchestrator-side experiment management.

### G. Autonomous Deployment

**Goal:** From approved PR to running on VPS without manual SSH.

**Steps:**
1. Bot repos include CI/CD that deploys on merge to main
2. Orchestrator monitors PR merge status via GitHub API
3. On merge: verify deployment via bot heartbeat
4. Monitor post-deployment metrics for 24h regression window
5. Auto-create rollback PR if regression detected (>2σ PnL decline)
6. Notify user of deployment status and post-deployment metrics

**Key files:** New `skills/deployment_monitor.py`, `orchestrator/handlers.py` (deployment events), GitHub Actions in bot repos

---

## Dependency Graph

```
A (Adaptive Thresholds) ── no dependencies, start immediately
B (Backtested Suggestions) ── depends on WFO pipeline (exists ✓)
C (PR Automation) ── depends on B for backtest attachment
D (Approval UX) ── depends on C for approve→PR flow
E (Bot Instrumentation) ── PARTIALLY COMPLETE (experiment fields exist, per-switch tracking exists)
    └── remaining: new event types (IndicatorSnapshot, OrderBookContext, FilterDecisionEvent)
F (A/B Testing) ── depends on activating existing bot-side frameworks (not on adding instrumentation fields)
    └── bot-side infrastructure exists: ExperimentRegistry, AblationFlags, experiment fields
    └── gap: runtime variant routing, experiment lifecycle management, orchestrator integration
G (Autonomous Deployment) ── depends on C + F
```

**Recommended order:** A and E-remaining in parallel → B → C + D in parallel → F (activate existing) → G

---

## Summary

The 8 gap closures transform the system from a **reporting tool** into a **learning system** where past outputs measurably improve future outputs. The key change: Claude's suggestions are now tracked, measured, and fed back into every subsequent analysis via scorecard, hypothesis effectiveness, and prediction accuracy.

The medium-term roadmap moves from **advisory learning** (soft prompt guidance) to **active learning** (backtest validation, PR automation, A/B testing) — progressively reducing the human effort required per improvement cycle while maintaining safety through permission gates and rollback mechanisms.
