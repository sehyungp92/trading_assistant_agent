# Ecosystem Deep Evaluation

**Date**: 2026-03-06
**Scope**: trading_assistant + k_stock_trader + momentum_trader + swing_trader
**Tests**: 1,238 passing | **Deterministic skills**: 40+ | **LLM invocations**: 4

---

## 1. Executive Summary & Scorecard

| Dimension | Score | Assessment |
|-----------|-------|------------|
| **LLM Leverage** | 9/10 | Excellent separation — 40+ deterministic pipelines pre-digest data into curated packages before 4 targeted LLM invocations. Claude sees structured, pre-classified data, not raw logs. |
| **Cross-Strategy Optimization** | 7/10 | Strong analysis (synergy, correlation, regime-conditional, proportion optimization) but allocation recommendations are text-only — no execution tracking or enforcement. |
| **Structural Improvement** | 8/10 | 4-tier strategy engine with 10 detectors, structural mismatch detection, pattern library for cross-bot transfer. Missing systematic exit optimization sweep. |
| **Feedback Loop** | 6/10 | Correction collection, suggestion tracking, outcome measurement all present. But no automated pattern extraction from corrections and no contradiction detection. |
| **Data Consumption** | 7/10 | 14 curated files per bot per day. Rich event schemas consumed well. Some fields available in bot data (signal_evolution, order book depth, session transitions) not consumed by the assistant. |
| **Architecture** | 9/10 | Clean event-driven design, deterministic routing, idempotent dedup, permission gates, temporal decay on findings, progress broadcasting. Production-ready foundations. |
| **Overall** | 8/10 | A well-architected system that makes strong use of its data, with clear gaps in allocation execution tracking, coordinator event loading, and some underutilized bot-side fields. |

---

## 2. LLM Leverage Assessment

### 2.1 Deterministic Pipelines (40+ tasks, zero LLM cost)

The system uses a "funnel" architecture: raw data is progressively reduced and classified by deterministic pipelines, so the LLM receives pre-digested context:

| Pipeline | File | What It Does |
|----------|------|-------------|
| **Event Routing** | `orchestrator/orchestrator_brain.py:96-106` | Pattern-matches event type → action type. No LLM. |
| **Error Rate Tracking** | `orchestrator/orchestrator_brain.py` (ErrorRateTracker) | Sliding 3-hour window, storm threshold = 3 errors. Routes HIGH/CRITICAL deterministically. |
| **Daily Metrics Reduction** | `skills/build_daily_metrics.py:28-532` | Raw trades → 14 curated JSON files (summary, winners, losers, process failures, regime analysis, filter analysis, factor attribution, exit efficiency, hourly performance, slippage stats, excursion stats, overlay state, coordinator impact, root cause summary). |
| **Quality Gate** | `analysis/quality_gate.py` | Checks data completeness before LLM invocation. Graceful degradation — missing files logged, not blocking. |
| **Minimum Trade Threshold** | `orchestrator/handlers.py:119-148` | If < 3 trades, skip Claude entirely; send deterministic summary. |
| **Strategy Engine** | `analysis/strategy_engine.py:33-567` | 10 detectors across 4 tiers produce `RefinementReport` with quantified suggestions. |
| **Synergy Analyzer** | `skills/synergy_analyzer.py:28-370` | Pairwise Pearson correlation → redundant/cannibalistic/complementary classification. Marginal Sharpe contribution via leave-one-out. |
| **Portfolio Allocator** | `skills/portfolio_allocator.py` | Cross-bot allocation recommendations based on correlation matrix. |
| **Strategy Proportion Optimizer** | `skills/strategy_proportion_optimizer.py` | Intra-bot strategy weight optimization. |
| **Structural Analyzer** | `skills/structural_analyzer.py:48+` | Lifecycle classification (emerging/mature/decaying), architecture mismatch detection (e.g., mean-reversion + trailing stop), filter ROI. |
| **WFO Pipeline** | `skills/run_wfo.py:44-143` | Fold generation → backtest simulation → parameter grid search → robustness testing → leakage detection → accept/review/reject recommendation. |
| **Triage Classifier** | `skills/run_bug_triage.py` | Pattern-matches error type/stack → severity/complexity/outcome. Routes OBVIOUS_FIX and NEEDS_INVESTIGATION to Claude; NEEDS_HUMAN to human directly. |
| **Filter Sensitivity** | `skills/filter_sensitivity_analyzer.py` | Simulates filter parameter changes on historical trades. |
| **Counterfactual Simulator** | `skills/counterfactual_simulator.py` | "What if" trade simulations using missed opportunity data. |
| **Exit Strategy Simulator** | `skills/exit_strategy_simulator.py` | Backtests alternative exit timing configurations. |
| **Slippage Analyzer** | `skills/slippage_analyzer.py` | Per-symbol/hour/regime slippage distributions. Exports regime→bps for WFO cost model. |
| **Drawdown Analyzer** | `skills/drawdown_analyzer.py` | Equity curve segmentation + root cause attribution per drawdown episode. |
| **Hourly Analyzer** | `skills/hourly_analyzer.py` | Time-of-day performance bucketing. |
| **Retrospective Builder** | `skills/retrospective_builder.py:41-216` | Compares past report predictions to actual outcomes. Accuracy metrics (correct/partial/incorrect/unverifiable). |
| **Pattern Library** | `skills/pattern_library.py:16-75` | Cross-bot innovation tracking with status workflow (PROPOSED → VALIDATED → IMPLEMENTED → TRANSFERRED / REJECTED). |
| **Suggestion Tracker** | `skills/suggestion_tracker.py` | JSONL-backed tracking of suggestion status and outcomes. |
| **Auto Outcome Measurer** | Weekly cron (Sun 10:00 UTC) | Measures implemented suggestions against outcomes, stores to outcomes.jsonl. |
| **Proactive Scanner** | `skills/proactive_scanner.py:31+` | Morning/evening scans: unusual loss (σ-based), repeated errors, heartbeat monitoring. No LLM. |
| **Memory Consolidator** | `orchestrator/memory_consolidator.py` | Weekly JSONL aggregation, rebuilds findings index. |
| **Interaction Analyzer** | `skills/interaction_analyzer.py` | Swing trader coordinator action impact analysis. |

### 2.2 Claude LLM Invocations (4 entry points)

All invocations go through `AgentRunner.invoke()` (`orchestrator/agent_runner.py:66-179`), which creates a run directory, writes data files, and calls `claude -p` CLI:

| # | Agent Type | Trigger | Handler Location | What Claude Does |
|---|-----------|---------|-----------------|-----------------|
| 1 | **daily_analysis** | Cron 22:30 UTC | `handlers.py:67-233` | Interprets 14 curated JSON files. Produces daily_report.md + report_checklist.json. 11-step analysis guide. |
| 2 | **weekly_analysis** | Cron Sun 23:00 UTC | `handlers.py:235-404` | Synthesizes weekly metrics + strategy engine suggestions + synergy report + simulations + retrospective. Produces weekly_report.md. |
| 3 | **wfo** | Cron weekly/monthly | `handlers.py:406-511` | Reviews deterministic WFO results (parameter optimization, robustness, safety flags). Approves/rejects param changes. CRITICAL if REJECT. |
| 4 | **triage** | HIGH error event | `handlers.py:513-612` | Diagnoses errors using stack trace + source snippets + failure history. Suggests fix or escalates. Can propose draft PR. |

### 2.3 Assessment

**Excellent.** The funnel architecture means Claude never sees raw JSONL — it receives pre-classified, quantified, structured data. The 10:1 ratio of deterministic-to-LLM work is strong. Each LLM invocation has a clear purpose that requires synthesis beyond what rules can provide.

### 2.4 Gaps: Where LLM Could Add More Value

| Gap | Impact | Detail |
|-----|--------|--------|
| **No LLM-assisted pattern extraction** | Medium | Corrections accumulate in corrections.jsonl but are never analyzed for recurring themes. Claude could extract meta-patterns from 30+ corrections. |
| **No contradiction detection** | Medium | When a new daily report contradicts a previous weekly conclusion, there's no flagging. Claude could cross-reference recent reports. |
| **Strategy refinement is prompt-only** | Low | The strategy_refinement agent type is defined in skills_index.md but has no dedicated handler — it runs through weekly analysis. A separate, deeper invocation could be triggered when alpha decay is detected. |

---

## 3. Data Flow & Consumption Analysis

### 3.1 Complete Data Flow

```
VPS Bots (emit JSONL via sidecar)
    ↓ HMAC-SHA256 signed, gzip compressed
Relay VPS → POST /events
    ↓ Dedup by event_id (SHA-256 of bot_id|timestamp|type|key, truncated 16 chars)
EventQueue (SQLite)
    ↓ OrchestratorBrain.decide() — deterministic routing
Worker → Handler Pipeline
    ↓
┌──────────────────────────────────────────────────────┐
│  DailyMetricsBuilder.write_curated()                 │
│  → 14 JSON files in data/curated/<date>/<bot_id>/    │
│                                                      │
│  ContextBuilder.base_package()                       │
│  → System prompt + corrections + failure log         │
│    + pattern library + session history               │
│                                                      │
│  PromptAssembler.assemble()                          │
│  → PromptPackage (system + task + data + instructions)│
│                                                      │
│  AgentRunner.invoke()                                │
│  → claude -p → runs/<run_id>/outputs/                │
│                                                      │
│  NotificationDispatcher                              │
│  → Telegram / Discord / Email                        │
└──────────────────────────────────────────────────────┘
    ↓
memory/findings/
  corrections.jsonl    (human feedback, 90-day window, 50-entry cap)
  failure-log.jsonl    (past failures)
  suggestions.jsonl    (tracked with status)
  outcomes.jsonl       (implemented suggestion results)
  allocation_history.jsonl
  pattern_library.jsonl
  patterns_consolidated.md
```

### 3.2 Per-Bot Data Richness

#### Event Types Emitted

| Event Type | k_stock_trader | momentum_trader | swing_trader |
|------------|---------------|-----------------|--------------|
| TradeEvent | Yes | Yes | Yes |
| MissedOpportunityEvent | Yes | Yes | Yes |
| DailySnapshot | Yes | Yes | Yes |
| ErrorEvent | Yes | Yes | Yes |
| HeartbeatEvent | Yes | Yes | Yes |
| CoordinatorEvent | No | No | **Yes** |

#### TradeEvent Field Comparison

| Field Category | k_stock_trader | momentum_trader | swing_trader |
|---------------|---------------|-----------------|--------------|
| **Core** (trade_id, pair, side, prices, pnl) | Full | Full | Full |
| **Signal** (signal, strength, factors, regime) | Full | Full | Full |
| **Filter Decisions** (per-filter threshold/actual/margin) | Full | Full | Full |
| **Sizing Context** (target_risk, volatility_basis, multipliers) | Full | Full | Full |
| **Portfolio State at Entry** | Full | Full | Full |
| **Execution Quality** (slippage_bps, latency_ms) | Full | Full | Full |
| **Execution Timeline** (signal→fill cascade) | Full | Full | Full |
| **MFE/MAE** | pct + price | **R-multiples** + price | pct + price + R |
| **Post-Exit Prices** (1h, 4h) | prices | prices + pct | **pct only** |
| **Exit Efficiency** | Yes | Yes | Yes |
| **Drawdown Context** (tier, multiplier) | Full | Full | Full |
| **Experiment Tracking** (id, variant, param_set_id) | Full | Full | Full |
| **Signal Evolution** (last N bars) | No | **Yes** | No |
| **Order Fill Details** (partial fills, spreads) | No | **Yes** | No |
| **Order Book Depth** | No | **Yes** | No |
| **Session Transitions** (ETH↔RTH) | No | **Yes** | No |
| **Overlay State** (macro EMA regime) | No | No | **Yes** |
| **Strategy ID** (multi-strategy) | No | Yes (strategy_type) | **Yes** (strategy_id) |
| **Overnight Gap** | No | No | **Yes** |
| **Coordination Context** | No | **Yes** (missed opps) | **Yes** (full) |

#### DailySnapshot Extras

| Field | k_stock_trader | momentum_trader | swing_trader |
|-------|---------------|-----------------|--------------|
| per_strategy_summary | Yes (mono) | Yes (multi) | Yes (multi) |
| overlay_state_summary | No | No | **Yes** |
| experiment_breakdown | No | No | **Yes** |
| session_breakdown | No | No | **Yes** |
| avg_signal_to_fill_ms | No | No | **Yes** |

### 3.3 What the Assistant Consumes

The `DailyPromptAssembler._CURATED_FILES` list (`analysis/prompt_assembler.py:17-32`) defines what gets loaded into the LLM context:

```
summary.json              ← DailySnapshot aggregate
winners.json              ← Top 5 by PnL
losers.json               ← Bottom 5 by PnL
process_failures.json     ← Trades with process_quality_score < 60
notable_missed.json       ← Missed opps where outcome > 2× avg win
regime_analysis.json      ← PnL by market regime
filter_analysis.json      ← Per-filter block count + impact
root_cause_summary.json   ← Controlled taxonomy distribution
factor_attribution.json   ← Per-signal-factor performance
exit_efficiency.json      ← Exit timing quality + MFE/MAE
hourly_performance.json   ← Time-of-day buckets
slippage_stats.json       ← Per-symbol/hour/regime slippage
excursion_stats.json      ← MFE/MAE distributions
overlay_state_summary.json ← Swing trader EMA state (if present)
```

Plus enrichment from `ContextBuilder.base_package()` (`analysis/context_builder.py:250-286`):
- `failure_log` — past failures (90-day window)
- `rejected_suggestions` — items Claude should not re-propose
- `outcome_measurements` — what implemented suggestions achieved
- `allocation_history` — position sizing changes
- `consolidated_patterns` — weekly pattern consolidation
- `pattern_library` — cross-bot innovation candidates
- `session_history` — recent agent invocation summaries

### 3.4 Gap Analysis: Available But Not Consumed

| Bot Field | Available In | Consumed? | Impact |
|-----------|-------------|-----------|--------|
| `signal_evolution` (last N bars of signal components) | momentum_trader TradeEvent | **No** | HIGH — would enable signal quality decay detection at component level, not just aggregate |
| `order_book_depth_at_entry` | momentum_trader TradeEvent | **No** | MEDIUM — could detect liquidity-driven adverse selection |
| `entry_fill_details` / `exit_fill_details` (partial fills) | momentum_trader TradeEvent | **No** | MEDIUM — could identify systematic fill quality issues |
| `session_transitions` (ETH↔RTH with unrealized PnL) | momentum_trader TradeEvent | **No** | LOW — relevant for session-boundary risk but niche |
| `experiment_breakdown` (per experiment_id:variant stats) | swing_trader DailySnapshot | **No** | HIGH — A/B testing infrastructure exists in bots but is invisible to the assistant |
| `session_breakdown` (PRE/RTH/ETH stats) | swing_trader DailySnapshot | **No** | MEDIUM — `hourly_performance.json` captures time-of-day but not session-typed |
| `overnight_gap_pct` / `prev_close_price` | swing_trader TradeEvent | **No** | LOW — gap-fade analysis would be useful for swing strategies |
| `contract_month` / `margin_used_pct` | momentum_trader TradeEvent | **No** | LOW — roll risk and margin utilization monitoring |
| `coordination_context` (in MissedOpportunityEvent) | momentum_trader | **No** | MEDIUM — cross-strategy blocking reasons for missed opportunities |

---

## 4. Cross-Strategy Optimization & Allocation

### 4.1 Existing Capabilities

The weekly analysis handler (`handlers.py:840-929`) runs 6 allocation analyses in sequence:

| # | Analysis | Tool | Location | Output |
|---|----------|------|----------|--------|
| 1 | **Cross-bot synergy** | `SynergyAnalyzer.compute()` | `skills/synergy_analyzer.py:43-97` | Pairwise correlation, redundant/cannibalistic/complementary classification |
| 2 | **Intra-bot synergy** | `SynergyAnalyzer.compute_intra_bot()` | `skills/synergy_analyzer.py:99-150` | Per-bot redundancy detection |
| 3 | **Portfolio allocation** | `PortfolioAllocator.compute()` | `skills/portfolio_allocator.py` | Cross-bot weight recommendations using correlation matrix |
| 4 | **Proportion optimization** | `StrategyProportionOptimizer.compute()` | `skills/strategy_proportion_optimizer.py` | Intra-bot strategy weight optimization |
| 5 | **Structural analysis** | `StructuralAnalyzer.compute()` | `skills/structural_analyzer.py:65+` | Lifecycle classification, architecture mismatches, filter ROI |
| 6 | **Regime-conditional metrics** | `StrategyEngine.compute_regime_conditional_metrics()` | `analysis/strategy_engine.py:374-495` | Per-regime-per-strategy performance with inverse-volatility allocation suggestions |

Additionally:
- **Interaction analysis** for swing_trader (`skills/interaction_analyzer.py`) — analyzes coordinator action impact on trades (but see Bug #1 below)
- **Bot correlation matrix** (`SynergyAnalyzer.compute_bot_correlation_matrix()`) — bot-level correlation for crowding detection

### 4.2 The Allocation Execution Gap

**Problem**: All allocation recommendations are text in reports — there is no tracking of whether recommendations were implemented, no measurement of actual vs. recommended allocations, and no enforcement mechanism.

The flow is:
```
PortfolioAllocator → "Recommend 40% k_stock, 35% momentum, 25% swing"
                          ↓
                   weekly_report.md (text)
                          ↓
                   Human reads on Telegram
                          ↓
                   ... (no tracking) ...
```

`AllocationTracker` (`skills/allocation_tracker.py:13+`) exists and records `AllocationRecord` entries to `allocation_history.jsonl`, but there is no mechanism to:
1. Compare recommended allocations to actual allocations
2. Track whether the human implemented the recommendation
3. Measure the impact of allocation changes over time
4. Alert when actual allocation drifts significantly from recommended

### 4.3 WFO Single-Strategy Limitation

The WFO pipeline (`skills/run_wfo.py`) optimizes parameters for **one strategy at a time**. There is no multi-strategy portfolio-level WFO that jointly optimizes:
- Cross-strategy parameter interactions
- Combined portfolio Sharpe (not per-strategy Sharpe)
- Correlation-aware parameter selection (avoid parameter sets that increase cross-strategy correlation)

### 4.4 Missing Multi-Strategy Portfolio Optimization

While `SynergyAnalyzer` detects redundancy and `PortfolioAllocator` suggests weights, there is no integrated optimization that:
- Jointly optimizes strategy weights + parameters
- Considers regime-switching costs (the system detects regime performance but doesn't model transition costs)
- Models the impact of removing a strategy vs. re-weighting

---

## 5. Structural Improvement Capabilities

### 5.1 Four-Tier Strategy Engine

`StrategyEngine` (`analysis/strategy_engine.py:33-567`) produces a `RefinementReport` with suggestions across 4 tiers:

**Tier 1 — PARAMETER** (direct, low-risk):
- `analyze_parameters()` (line 52): Detects tight stops (avg_loss/avg_win ratio < 0.3)

**Tier 2 — FILTER** (moderate, testable):
- `analyze_filters()` (line 82): Detects filters costing more than they save (net_impact_pnl < 0)
- `detect_time_of_day_patterns()` (line 289): Poor-performing hours (win_rate < 0.35 with 10+ trades)

**Tier 3 — STRATEGY_VARIANT** (significant, requires judgment):
- `analyze_regime_fit_quantified()` (line 135): Regime-specific underperformance with PnL quantification
- `detect_exit_timing_issues()` (line 235): Premature exits (exit_efficiency < 0.5, premature_exit_pct > 0.4)
- `detect_correlation_breakdown()` (line 264): Cross-bot correlation risk (rolling 30d > 0.7)
- `detect_drawdown_patterns()` (line 316): Concentrated drawdowns (largest loss > 3× avg)
- `detect_position_sizing_issues()` (line 345): Asymmetric wins/losses despite good win rate

**Tier 4 — HYPOTHESIS** (synthesis, Claude's domain):
- `detect_alpha_decay()` (line 181): Declining Sharpe (30d vs 90d, threshold > 30% drop)
- `detect_signal_decay()` (line 210): Declining signal-to-outcome correlation (threshold > 0.2 drop)

### 5.2 Structural Analyzer

`StructuralAnalyzer` (`skills/structural_analyzer.py:48+`) performs:

- **Strategy lifecycle classification**: Emerging (Sharpe improving), mature (stable), decaying (Sharpe declining) — using configurable thresholds (decay_sharpe_threshold=0.3, growth_sharpe_threshold=0.2)
- **Architecture mismatch detection**: Rules-based matching of signal_type + exit_type combinations:
  - Mean reversion + trailing stop → mismatch (recommend fixed TP or time-based)
  - Breakout + time-based exit → mismatch (recommend trailing stop)
  - Momentum + fixed TP → mismatch (recommend trailing stop)
- **Filter ROI analysis**: Per-filter cost/benefit calculation

### 5.3 Pattern Library

`PatternLibrary` (`skills/pattern_library.py:16-75`) tracks cross-bot innovations:

- **Status workflow**: PROPOSED → VALIDATED → IMPLEMENTED → TRANSFERRED (or REJECTED)
- **Categories**: FILTER, EXIT_RULE, ENTRY_SIGNAL, POSITION_SIZING, REGIME_GATE, RISK_MANAGEMENT, COORDINATION
- **Integration**: `ContextBuilder.load_pattern_library()` feeds active patterns into weekly prompts so Claude can propose cross-bot transfers
- **Example**: A regime gate that works well for k_stock_trader could be proposed for momentum_trader

### 5.4 Simulation Pipeline

Three simulation skills run during weekly analysis (`handlers.py:776-829`):

| Simulator | What It Tests | Trigger |
|-----------|--------------|---------|
| `FilterSensitivityAnalyzer` | Impact of relaxing/tightening filter thresholds | Strategy engine finds costly filter |
| `CounterfactualSimulator` | "What if we took the trade" using missed opportunity outcomes | Strategy engine finds filter issues |
| `ExitStrategySimulator` | Alternative exit configurations (trailing, ATR, time-based, fixed) | Strategy engine finds exit timing issues |

### 5.5 Gaps

| Gap | Impact | Detail |
|-----|--------|--------|
| **No systematic exit optimization sweep** | HIGH | The exit strategy simulator is invoked with a hardcoded single config (`ExitStrategyType.TRAILING_STOP`, `trail_pct: 2.0` at `handlers.py:819-822`). It should sweep multiple configurations (trailing 1-3%, ATR 1-3×, time-based 1h/4h/1d) and compare. |
| **No signal health monitoring** | MEDIUM | `detect_signal_decay()` checks aggregate signal-to-outcome correlation but doesn't monitor individual signal components. momentum_trader's `signal_evolution` field (per-bar signal component values) would enable component-level health checks. |
| **No multi-filter interaction analysis** | MEDIUM | Filters are analyzed independently. No detection of filter combinations that are jointly harmful (filter A blocks good trades that filter B would have saved). |

---

## 6. Feedback Loop & Learning

### 6.1 What Exists

| Component | Location | Function |
|-----------|----------|----------|
| **Correction Collection** | `analysis/feedback_handler.py:17-86` | Parses human feedback from Telegram/Discord into typed `HumanCorrection` entries (TRADE_RECLASSIFY, REGIME_OVERRIDE, ALLOCATION_CHANGE, POSITIVE_REINFORCEMENT, FREE_TEXT) |
| **Correction Storage** | `memory/findings/corrections.jsonl` | JSONL with temporal decay (90 days, 50-entry cap) |
| **Suggestion Tracking** | `skills/suggestion_tracker.py` | Tracks suggestion status: proposed → accepted / rejected / implemented |
| **Outcome Measurement** | Auto-measurer (weekly cron) | Compares implemented suggestions to actual outcomes, stores in outcomes.jsonl |
| **Retrospective Builder** | `skills/retrospective_builder.py:41-216` | Compares past predictions to outcomes. Accuracy metrics: correct, partially_correct, incorrect, unverifiable |
| **Rejected Suggestion Guard** | `analysis/prompt_assembler.py` instructions | Explicitly tells Claude to check rejected_suggestions and not re-propose |
| **Failure Log** | `memory/findings/failure-log.jsonl` | Records what failed and why (Ralph Loop V2) |
| **Pattern Library** | `skills/pattern_library.py` | Cross-bot innovation transfer with status tracking |
| **Context Enrichment** | `analysis/context_builder.py:250-286` | Loads all of the above into every LLM invocation's base context |

### 6.2 Underutilization

| Gap | Impact | Detail |
|-----|--------|--------|
| **No pattern extraction from corrections** | HIGH | 30+ corrections accumulate over 90 days but are only loaded as raw text. No system extracts "you keep misreading regime X as Y" or "stop suggesting filter changes for bot Z" meta-patterns. |
| **No contradiction detection** | HIGH | If Monday's daily report says "momentum is strong" and Thursday's says "momentum is weak" with no regime change, there's no flagging. Reports are independent — no cross-reference. |
| **Retrospective accuracy is mostly "unverifiable"** | MEDIUM | `RetrospectiveBuilder._assess_accuracy()` (`retrospective_builder.py:193-198`) returns "unverifiable" by default. Claude does the actual assessment, but the deterministic pipeline could do more matching (e.g., if suggestion was "widen stops" and avg_mae improved, that's signal). |
| **No correction feedback to strategy engine** | MEDIUM | When a human corrects a REGIME_OVERRIDE, the strategy engine doesn't learn from it. Corrections only flow to Claude prompts, not to deterministic detectors. |

---

## 7. Bugs & Code Issues Found

### Bug #1: `_load_coordinator_events` Returns Empty List

**Location**: `orchestrator/handlers.py:975-995`

```python
def _load_coordinator_events(self, week_start: str, week_end: str) -> list:
    events: list[CoordinatorAction] = []
    start = datetime.strptime(week_start, "%Y-%m-%d")
    end = datetime.strptime(week_end, "%Y-%m-%d")

    current = start
    while current <= end:
        date_str = current.strftime("%Y-%m-%d")
        coord_file = self._curated_dir / date_str / "swing_trader" / "coordinator_impact.json"
        if not coord_file.exists():
            current += timedelta(days=1)
            continue
        current += timedelta(days=1)
        # BUG: File found but never read. No json.load(), no events.append().

    return events  # ALWAYS EMPTY
```

**Impact**: The interaction analysis for swing_trader (`handlers.py:920-928`) calls `InteractionAnalyzer.compute(coord_events, swing_trades)` with an empty `coord_events` list. The coordinator impact report is meaningless — it analyzes zero events every week.

**Fix**: Add file reading and parsing inside the loop when `coord_file.exists()`.

### Bug #2: Exit Strategy Simulation Hardcoded to Single Config

**Location**: `orchestrator/handlers.py:819-822`

```python
config = ExitStrategyConfig(
    strategy_type=ExitStrategyType.TRAILING_STOP,
    params={"trail_pct": 2.0},
)
sim_result = exit_sim.simulate(trades, config)
```

**Impact**: Only tests one exit configuration (trailing stop 2.0%) regardless of the current strategy's actual exit mechanism. The `ExitStrategyType` enum defines 4 types (FIXED_STOP, TRAILING_STOP, ATR_STOP, TIME_BASED) at `schemas/exit_simulation.py:9-13`, but only one is ever used. A strategy using ATR-based stops will only be tested against trailing 2.0%.

**Fix**: Sweep multiple configurations and compare against baseline. At minimum, test the 4 exit types with 2-3 parameter values each.

---

## 8. Priority Improvements Ranked by ROI

### Tier 1 — High Impact, Achievable Now

| # | Improvement | Effort | Impact | Detail |
|---|------------|--------|--------|--------|
| 1.1 | **Fix `_load_coordinator_events` bug** | ~15 min | HIGH | Add `json.loads(coord_file.read_text())` and parse into `CoordinatorAction` list. Immediately unlocks swing_trader interaction analysis. |
| 1.2 | **Exit optimization sweep** | ~2 hours | HIGH | Replace hardcoded single config with sweep across 4 exit types × 3 param values. Compare all against baseline. Pick best per strategy. |
| 1.3 | **Allocation execution tracking** | ~4 hours | HIGH | After `PortfolioAllocator` produces recommendations, store in allocation_history.jsonl with `recommended` and `actual` fields. Weekly analysis compares drift. |
| 1.4 | **Consume experiment_breakdown** | ~2 hours | HIGH | swing_trader's DailySnapshot already has per-experiment stats. Add to `_CURATED_FILES`, write in `DailyMetricsBuilder`, include in prompts. Enables A/B analysis. |
| 1.5 | **Consume signal_evolution** | ~3 hours | HIGH | momentum_trader provides per-bar signal component values. Write `signal_health.json` in DailyMetricsBuilder. Feed to strategy engine for component-level decay detection. |

### Tier 2 — Medium Impact, Moderate Effort

| # | Improvement | Effort | Impact | Detail |
|---|------------|--------|--------|--------|
| 2.1 | **Contradiction detection** | ~4 hours | MEDIUM | Before daily analysis, load last 3 daily reports. Flag if key conclusions (regime, direction, risk level) contradict without regime change. |
| 2.2 | **Signal health monitoring** | ~4 hours | MEDIUM | Per-signal-factor correlation tracking over rolling 30d window. Alert when specific factor's correlation to outcome drops below threshold. |
| 2.3 | **Multi-filter interaction analysis** | ~3 hours | MEDIUM | Analyze filter combinations, not just individual filters. Detect pairs of filters that jointly block good trades. |
| 2.4 | **Pattern extraction from corrections** | ~3 hours | MEDIUM | Weekly batch: cluster corrections by target (bot/trade type/regime). Extract "you keep getting X wrong" patterns as meta-corrections. |
| 2.5 | **Retrospective accuracy improvement** | ~2 hours | MEDIUM | Deterministic matching: if suggestion was "widen stops" and avg_mae improved next week, mark as "partially_correct" automatically. |
| 2.6 | **Consume order fill details** | ~2 hours | MEDIUM | momentum_trader's `entry_fill_details`/`exit_fill_details` → write `fill_quality.json`. Detect systematic adverse selection. |

### Tier 3 — High Impact, Significant Effort (Future)

| # | Improvement | Effort | Impact | Detail |
|---|------------|--------|--------|--------|
| 3.1 | **Multi-strategy WFO** | ~2 weeks | HIGH | Joint parameter optimization across strategies, maximizing portfolio Sharpe not individual Sharpe. Requires correlation-aware objective function. |
| 3.2 | **Regime prediction integration** | ~1 week | MEDIUM | Currently regime is classified post-hoc. A forward-looking regime model could pre-gate strategies before the market shifts. |
| 3.3 | **Forward testing sandbox** | ~1 week | MEDIUM | Paper-trade proposed parameter changes for 1 week before committing. Requires simulation engine extension. |
| 3.4 | **Correction-aware strategy engine** | ~3 days | MEDIUM | Feed REGIME_OVERRIDE corrections back into `detect_alpha_decay()` and `analyze_regime_fit_quantified()` as ground-truth regime labels. |

---

## 9. Bot-Side Observations

### 9.1 Experiment Tracking — High-Value, Apparently Unused

All three bots emit `experiment_id` and `experiment_variant` fields in TradeEvent and MissedOpportunityEvent:
- **k_stock_trader**: `trade_logger.py` — experiment_id, experiment_variant, param_set_id
- **momentum_trader**: `trade_logger.py` — experiment_id, experiment_variant
- **swing_trader**: `trade_logger.py` — experiment_id, experiment_variant; `daily_snapshot.py` — experiment_breakdown dict

**Status**: The fields exist and are emitted, but the trading_assistant never groups, compares, or reports on experiments. swing_trader even aggregates per-experiment stats in DailySnapshot.experiment_breakdown, which is never consumed.

**Value**: This is the infrastructure for A/B testing strategy variants. Consuming it would let the assistant compare variant performance with statistical rigor.

### 9.2 Order-Level Events

- **momentum_trader** has `entry_fill_details`, `exit_fill_details`, and `order_book_depth_at_entry` — the most granular execution data of any bot.
- **k_stock_trader** and **swing_trader** have `execution_timeline` (signal→fill cascade timestamps) but no per-order detail.
- **No bot** emits standalone order-level events (order submitted, partial fill, reject). Execution quality is embedded in TradeEvent, making it impossible to analyze rejected or partially filled orders that never became trades.

### 9.3 Instrumentation Quality Assessment

**Overall: Excellent.** All three bots have comprehensive instrumentation that goes well beyond what most trading systems provide:

| Aspect | Rating | Notes |
|--------|--------|-------|
| **Core trade data** | 10/10 | Complete: prices, PnL, sizing, timing, fees |
| **Signal context** | 9/10 | Signal strength, factors, regime, filters. momentum_trader adds signal_evolution (excellent). |
| **Execution quality** | 8/10 | Slippage, latency, execution timeline. momentum_trader has order-level detail. |
| **Post-exit tracking** | 9/10 | 1h/4h post-exit prices for exit efficiency measurement. Backfilled asynchronously. |
| **MFE/MAE** | 9/10 | All bots track intra-trade excursion. momentum_trader uses R-multiples (better for cross-strategy comparison). |
| **Process quality** | 9/10 | 0-100 score + controlled root cause taxonomy. Enables systematic quality analysis. |
| **Missed opportunities** | 8/10 | Hypothetical outcomes with simulation policy transparency. momentum_trader adds coordination_context. |
| **Coordinator tracking** | N/A for 2 bots | swing_trader has full coordinator event logging with action/trigger/target/rule/outcome. |
| **A/B infrastructure** | 7/10 | Fields present everywhere, but only swing_trader aggregates in daily snapshot. |

### 9.4 Key Bot-Side Gaps — RESOLVED

All three gaps have been addressed in bot code (see `_references/` for implementations):

| Gap | Status | Implementation |
|-----|--------|----------------|
| **Order events** | Resolved | All 3 bots: `OrderLogger` with sidecar routing. swing_trader adds coordinator integration. |
| **Position snapshots** | Resolved | All 3 bots: enriched heartbeat with `positions`/`portfolio_exposure` fields. |
| **Experiment fields** | Resolved | All 3 bots: `experiment_breakdown` in DailySnapshot. swing_trader/momentum_trader add `active_experiments`. |

Additionally, 8 event types previously routed to `LOG_UNKNOWN` (`daily_snapshot`, `order`, `process_quality`, `bot_error`, `post_exit`, `portfolio_rule`, `market_snapshot`, `exit_movement`) are now handled by dedicated brain handlers and routed to appropriate actions (primarily `QUEUE_FOR_DAILY`; `bot_error` delegates to severity-based error routing).

---

## Appendix: File Reference Index

| File | Key Classes/Functions | Lines |
|------|----------------------|-------|
| `orchestrator/orchestrator_brain.py` | `OrchestratorBrain.decide()`, `ErrorRateTracker` | 192 |
| `orchestrator/worker.py` | `Worker.process_batch()`, `_dispatch()` | 173 |
| `orchestrator/agent_runner.py` | `AgentRunner.invoke()`, `_build_command()` | 250 |
| `orchestrator/handlers.py` | 8 handler methods, `_run_allocation_analyses()`, `_load_coordinator_events()` | 1,078 |
| `analysis/strategy_engine.py` | `StrategyEngine.build_report()`, 10 detect/analyze methods | 567 |
| `analysis/prompt_assembler.py` | `DailyPromptAssembler.assemble()`, `_CURATED_FILES` | 138 |
| `analysis/context_builder.py` | `ContextBuilder.base_package()`, 8 load methods | 287 |
| `analysis/feedback_handler.py` | `FeedbackHandler.parse()`, `write_correction()` | 86 |
| `skills/build_daily_metrics.py` | `DailyMetricsBuilder.write_curated()`, 14 analysis methods | 532 |
| `skills/synergy_analyzer.py` | `SynergyAnalyzer.compute()`, `_classify()`, `_compute_marginal_contributions()` | 370 |
| `skills/structural_analyzer.py` | `StructuralAnalyzer.compute()` — lifecycle, mismatches, filter ROI | ~200 |
| `skills/pattern_library.py` | `PatternLibrary` — add, load_active, load_for_bot, update_status | 75 |
| `skills/retrospective_builder.py` | `RetrospectiveBuilder.build()` — prediction accuracy tracking | 216 |
| `skills/run_wfo.py` | `WFORunner.run()` — fold gen → optimize → robustness → recommend | 143 |
| `skills/proactive_scanner.py` | `ProactiveScanner.morning_scan()`, `evening_report()` | ~100 |
| `skills/portfolio_allocator.py` | `PortfolioAllocator.compute()` | — |
| `skills/strategy_proportion_optimizer.py` | `StrategyProportionOptimizer.compute()` | — |
| `skills/interaction_analyzer.py` | `InteractionAnalyzer.compute()` | — |
| `skills/allocation_tracker.py` | `AllocationTracker` — allocation history JSONL | — |
| `schemas/events.py` | `TradeEvent`, `MissedOpportunityEvent`, `DailySnapshot`, `EventMetadata` | 163 |
| `schemas/pattern_library.py` | `PatternEntry` — 7 categories, 5 statuses | 44 |
| `schemas/corrections.py` | `HumanCorrection`, `CorrectionType` enum | 33 |
| `schemas/exit_simulation.py` | `ExitStrategyConfig`, `ExitStrategyType` enum (4 types) | — |
