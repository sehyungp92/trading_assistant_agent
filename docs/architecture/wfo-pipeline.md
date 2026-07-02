# Walk-Forward Optimisation Pipeline

> Historical reference only. Legacy WFO runtime wiring is disabled; monthly
> validation is now the authoritative path for material strategy learning and
> approval-gated proposals. Do not use this document as an operator runbook.

End-to-end documentation of how the trading assistant optimises bot parameters
through walk-forward optimisation, autonomous approval, and deployment monitoring.

---

## 1. WFO Configuration

**`schemas/wfo_config.py`** defines the entire search space:

- **WFOMethod**: `ANCHORED` (expanding IS window) or `ROLLING` (fixed-size sliding window)
- **ParameterSpace**: list of `ParameterDef` with min/max/step/current_value — grid values computed automatically
- **CostModelConfig**: fees (default 7 bps round-trip), slippage model (FIXED, SPREAD_PROPORTIONAL, or EMPIRICAL with regime-specific bps), and `cost_multipliers` for sensitivity testing (1.0x, 1.5x, 2.0x)
- **RobustnessConfig**: neighborhood perturbation (±10%), regime stability (≥3 of 4 regimes profitable), min 30 trades per fold
- **OptimizationObjective**: SHARPE, SORTINO, CALMAR, or PROFIT_FACTOR

---

## 2. The WFO Runner Pipeline

**`skills/run_wfo.py`** orchestrates the full pipeline in `run()`:

### Step 1 — Fold Generation (`skills/fold_generator.py`)

Two temporal splitting strategies:

**Anchored method:**
```
Fold 0: IS [data_start ... data_start+180d], OOS [... +210d]
Fold 1: IS [data_start ... data_start+210d], OOS [... +240d]
Fold 2: IS [data_start ... data_start+240d], OOS [... +270d]
... (IS window grows by step_days each fold, start stays fixed)
```
More stable parameters due to longer history. Requires sufficient total data.

**Rolling method:**
```
Fold 0: IS [start ... start+180d], OOS [... +210d]
Fold 1: IS [start+30d ... start+210d], OOS [... +240d]
Fold 2: IS [start+60d ... start+240d], OOS [... +270d]
... (window slides, IS length constant)
```
More responsive to regime changes. All folds have uniform trade count.

Must produce ≥ `min_folds` (default 6) or the pipeline returns REJECT immediately.

### Step 2 — Per-Fold Optimisation

For each fold:

1. Filter trades to the IS (in-sample) period
2. **ParamOptimizer** (`skills/param_optimizer.py`) runs exhaustive grid search via `itertools.product` over the full parameter space
3. Each combination is simulated through **BacktestSimulator** (`skills/backtest_simulator.py`):
   - Filters trades by parameter thresholds (e.g. `signal_strength_min`)
   - Includes missed opportunities if filters are relaxed (`include_blocked_by`)
   - Applies costs via **CostModel** (`skills/cost_model.py`)
   - Computes: Sharpe, Sortino, Calmar, profit factor, max drawdown, win rate, per-regime PnL
4. Combinations filtered by constraints:
   - `total_trades >= min_trades_per_fold`
   - `max_drawdown_pct <= max_drawdown_constraint`
5. Ranked by the chosen objective (SHARPE, SORTINO, CALMAR, or PROFIT_FACTOR)
6. Best IS parameters are then simulated on OOS data
7. `oos_degradation_pct` measures how much the objective drops from IS to OOS

### Step 3 — Consensus Parameter Selection

Uses `Counter.most_common()` per parameter across all folds — the most frequently
selected value wins. Deterministic (no randomness).

### Step 4 — Cost Sensitivity Testing

Simulates consensus params at each cost multiplier (default: 1.0x, 1.5x, 2.0x).
If only profitable at zero cost, a safety flag is raised and
`reject_if_only_profitable_at_zero_cost` triggers REJECT.

### Step 5 — Robustness Testing (`skills/robustness_tester.py`)

**Neighborhood stability (50 points):**
- Perturbs each parameter ±10% from the consensus value
- Simulates all neighbors
- If any neighbor drops >50% from best Sharpe → `likely_overfit` flag
- If all neighbors within 5% of each other → `low_conviction` flag (flat surface)

**Regime stability (50 points):**
- Simulates consensus params, extracts `pnl_by_regime`
- Must be profitable in ≥ `min_profitable_regimes` (default 3 of 4 regime types)
- Fewer than threshold → `regime_unstable` flag

Combined robustness score: 0–100.

### Step 6 — Leakage Audit (`skills/leakage_detector.py`)

Two audit types:

1. **Feature audit**: verifies features computed at time t use only data ≤ t
   - `latest_data_used > computed_at` → FAIL (lookahead violation)
2. **Label audit**: verifies trade outcomes are computed from post-entry data only
   - `label_computed_from < entry_time` → FAIL (forward-fill violation)

Any failure → `data_leakage` safety flag (severity: high).

### Step 7 — Safety Flag Collection

Flag types and their severities:

| Flag | Severity | Trigger |
|------|----------|---------|
| `data_leakage` | high | Leakage audit failure |
| `likely_overfit` | high | Neighbor drops >50% from best |
| `fragile` | medium | Cost sensitivity failure |
| `regime_unstable` | medium | < 3 profitable regimes |
| `low_conviction` | low | Flat optimisation surface |

### Step 8 — Recommendation

Deterministic logic:

- **REJECT**: any high-severity safety flag, OR OOS Sharpe ≤ 0, OR no valid fold results
- **ADOPT**: OOS Sharpe ≥ 1.0 AND robustness score ≥ 70
- **TEST_FURTHER**: everything else

Output: `WFOReport` (`schemas/wfo_results.py`) containing all folds, metrics,
cost sensitivity results, robustness results, safety flags, and recommendation reasoning.

---

## 3. Cost Model

**`skills/cost_model.py`**

Computes `TradeCosts` (fees + slippage) per trade:

- **Fees**: `notional × fees_per_trade_bps / 10,000 × 2` (round-trip)
- **Slippage** depends on model:
  - **FIXED**: constant bps per trade (`notional × fixed_slippage_bps / 10,000 × 2`)
  - **SPREAD_PROPORTIONAL**: slippage = bid-ask spread (`notional × spread_bps / 10,000 × 2`)
  - **EMPIRICAL**: regime-specific bps from a JSON file (e.g. `{"uptrend": 2.5, "downtrend": 3.0}`), fallback to fixed if regime not found

Cost multiplier support: both fees and slippage are scaled by the multiplier for
sensitivity testing.

---

## 4. Backtest Simulator

**`skills/backtest_simulator.py`**

`simulate(trades, missed, params, cost_multiplier=1.0) → SimulationMetrics`

1. Filter trades by parameter thresholds (e.g. `signal_strength_min`)
2. Include missed opportunities if filter thresholds are relaxed
3. Apply costs per trade via CostModel
4. Compute metrics:
   - Win/loss counts, win rate
   - Gross and net PnL
   - Max drawdown (peak-to-trough / notional)
   - **Sharpe ratio**: `(mean / stdev) × √252` (annualised)
   - **Sortino ratio**: downside deviation only
   - **Calmar ratio**: `net_pnl / max_drawdown`
   - **Profit factor**: `total_wins / abs(total_losses)`
   - Per-regime breakdown: `trades_by_regime`, `pnl_by_regime`

---

## 5. Report Builder & Claude Review

### Markdown Report (`analysis/wfo_report_builder.py`)

Generates a human-readable report with sections:

1. **Header**: bot_id, method (anchored/rolling), config summary
2. **Parameter Comparison**: current vs suggested values in table
3. **Fold Results**: per-fold IS Sharpe, OOS Sharpe, PnL, degradation %
4. **Cost Sensitivity**: metrics at 1.0x, 1.5x, 2.0x cost multipliers
5. **Robustness**: score/100, neighborhood stable? regime stable?
6. **Safety Flags**: list with severity icons
7. **What Could Go Wrong**: risk summary
8. **Recommendation**: ADOPT/TEST_FURTHER/REJECT + reasoning

### Handler Orchestration (`orchestrator/handlers.py` → `handle_wfo()`)

1. Loads WFO config YAML for the bot from `wfo_configs/{bot_id}.yaml`
2. Loads trades from `data/curated/{date}/{bot_id}/trades.jsonl` and `missed.jsonl`
3. Runs the WFO pipeline
4. Writes WFO report (JSON + markdown) to `runs/wfo-{bot_id}-{date}/`
5. **WFOPromptAssembler** assembles context for Claude CLI invocation
6. Claude's role is **confirmatory** — validates WFO output, checks strategic sense,
   reviews flags, provides independent recommendation
7. Notification sent (CRITICAL priority if REJECT)

---

## 6. Autonomous Pipeline: Suggestion → Backtest → Approval

**`skills/autonomous_pipeline.py`** processes actionable suggestions from the
strategy engine:

1. **Filter**: only parameter/filter suggestions with confidence ≥ 0.5
2. **Resolve**: `ConfigRegistry` maps suggestion to specific bot parameter file and YAML field
3. **Extract**: proposed value parsed from structured fields or regex from title/description
4. **Validate**: value checked against `valid_range` from parameter definition
5. **Backtest**: `SuggestionBacktester` (`skills/suggestion_backtester.py`) validates data quality:
   - Loads last 30 days of trades
   - Requires ≥ 10 trades (≥ 30 for safety-critical params)
   - Requires Sharpe ≥ 0 and profit_factor ≥ 1.0
6. **Approval request**: creates `ApprovalRequest`, sends Telegram message with inline
   approve/reject/detail buttons
7. **Tracking**: added to `ApprovalTracker` (JSONL-backed, 7-day expiry)

### Approval Schemas (`schemas/autonomous_pipeline.py`)

- **ApprovalRequest**: suggestion_id, bot_id, param_changes, backtest_summary, status
- **ApprovalStatus**: PENDING → APPROVED / REJECTED / EXPIRED
- **ParamChange**: param_name, current_value, proposed_value, file_path

---

## 7. Telegram Approval → GitHub PR

When the user clicks **Approve** in Telegram:

**`skills/approval_handler.py` → `handle_approve()`**:

1. Transitions request to APPROVED
2. Marks suggestion as IMPLEMENTED in SuggestionTracker
3. Loads bot config profile from ConfigRegistry
4. For each param_change:
   - Fetches ParameterDefinition
   - **FileChangeGenerator** reads the bot's param YAML file
   - Performs the value update
   - Generates a diff preview
5. Builds PR request:
   - Branch: `ta/suggestion-{id[:8]}-{date}`
   - Title: `Update {param_names}`
   - Body: backtest comparison (Sharpe, MaxDD, PF, WR changes)
6. **PRBuilder** (`skills/github_pr.py`):
   - Pre-flight checks (git clean, branch doesn't exist, file paths valid)
   - Creates branch, applies file changes, commits, pushes
   - Creates PR on GitHub
   - Dedup: checks for existing PR covering the same suggestion
7. Stores PR URL in ApprovalTracker
8. Edits the Telegram approval card to show "APPROVED" with PR link
9. Broadcasts `suggestion_pr_created` event

If PR creation fails, status reverts from APPROVED back to PENDING.

---

## 8. Deployment Monitoring & Auto-Rollback

**`skills/deployment_monitor.py`** tracks each deployment through a lifecycle:

```
PENDING_MERGE → MERGED → DEPLOYED → MONITORING_COMPLETE
                                   ↘ REGRESSION_DETECTED → ROLLED_BACK
```

Checked every 10 minutes by the scheduler (`orchestrator/handlers.py` → `_check_deployments`).

### Lifecycle Stages

**PENDING_MERGE** (PR created):
- Polls `gh pr view` for merge status
- Timeout after 7 days → STALE

**MERGED** (user merged PR):
- Snapshots pre-deploy metrics from last 7 days of curated data:
  avg PnL, win_rate, max_drawdown
- Waits for bot heartbeat confirming new config loaded
- Heartbeat arrives after merge_time → transitions to DEPLOYED
- No heartbeat for 6 hours → STALE

**DEPLOYED** (heartbeat confirmed, monitoring active):
- Collects metric snapshots every 30 minutes
- Stores up to 48 snapshots (24-hour window)
- At 24 hours: compares pre-deploy vs worst post-deploy snapshot

**Regression detection** criteria:
- PnL decline > 50%
- Win rate drop > 15 percentage points
- Max drawdown > 50% worse

### Rollback

If regression detected:
- Auto-creates a **rollback PR**:
  - Branch: `ta/rollback-{deployment_id[:8]}`
  - Title: `[trading-assistant] ROLLBACK: revert changes on {bot_id}`
  - Body: regression details + reverted parameter values
  - File changes: original parameter values via FileChangeGenerator
- Transitions to ROLLED_BACK
- Sends CRITICAL priority notification

If clean after 24 hours → MONITORING_COMPLETE.

### Deployment Schemas (`schemas/deployment_monitoring.py`)

8-state lifecycle: PENDING_MERGE, MERGED, DEPLOYED, MONITORING, MONITORING_COMPLETE,
REGRESSION_DETECTED, ROLLED_BACK, STALE.

DeploymentRecord includes: deployment_id, bot_id, suggestion_id, pr_url,
pre_deploy_metrics, post_deploy_snapshots, regression_details.

---

## 9. App Wiring

**`orchestrator/app.py`** connects everything:

**Feature flags:**
- `config.autonomous_enabled` — enables suggestion backtesting, approval pipeline, PR creation
- `config.deployment_monitoring_enabled` — enables post-merge regression detection

**Handler registration:**
```python
worker.on_wfo = lambda action: subagent_mgr.spawn(
    "wfo", lambda a=action: handlers.handle_wfo(a))
```

**Telegram callbacks:**
```python
callback_router.register("approve_suggestion_", _on_approve_callback)
callback_router.register("reject_suggestion_", _on_reject_callback)
callback_router.register("detail_suggestion_", _on_detail_callback)
```

**Auto-deployment tracking:**
```python
async def _on_approve_callback(request_id):
    response = await approval_handler.handle_approve(request_id)
    if deployment_monitor and "PR created:" in response:
        deployment_monitor.create_deployment(...)
    return response
```

**Scheduler jobs:**

| Job | Schedule | Purpose |
|-----|----------|---------|
| `_check_pr_reviews` | every 30 min | Monitor PR merge status |
| `_check_deployments` | every 10 min | Deployment lifecycle monitoring |
| `_expire_approvals` | hourly | Expire 7-day-old approval requests |

---

## 10. Key Files

### Core WFO
| File | Purpose |
|------|---------|
| `schemas/wfo_config.py` | WFO configuration (method, params, costs, robustness) |
| `schemas/wfo_results.py` | Results (folds, metrics, flags, recommendation) |
| `skills/run_wfo.py` | Main WFO pipeline runner |
| `skills/fold_generator.py` | Anchored/rolling temporal fold generation |
| `skills/backtest_simulator.py` | Trade replay with cost application |
| `skills/param_optimizer.py` | Exhaustive grid search |
| `skills/cost_model.py` | Fee + slippage computation |
| `skills/robustness_tester.py` | Neighborhood + regime stability |
| `skills/leakage_detector.py` | Feature/label temporal audit |
| `analysis/wfo_report_builder.py` | Markdown report generation |
| `analysis/wfo_prompt_assembler.py` | Claude context assembly |

### Autonomous Pipeline
| File | Purpose |
|------|---------|
| `skills/autonomous_pipeline.py` | Suggestion → backtest → approval request |
| `schemas/autonomous_pipeline.py` | ApprovalRequest, ParamChange schemas |
| `skills/suggestion_backtester.py` | Data quality validation |
| `skills/approval_handler.py` | Approve/reject/detail handling |
| `skills/approval_tracker.py` | JSONL-backed request lifecycle |
| `skills/github_pr.py` | PRBuilder: branch, commit, push, create PR |

### Deployment Monitoring
| File | Purpose |
|------|---------|
| `skills/deployment_monitor.py` | Post-merge lifecycle tracking |
| `schemas/deployment_monitoring.py` | 8-state deployment lifecycle schemas |

### Orchestration
| File | Purpose |
|------|---------|
| `orchestrator/handlers.py` | `handle_wfo()`, `_check_deployments()` |
| `orchestrator/app.py` | Feature flags, callback wiring, scheduler jobs |
| `memory/skills/wfo_pipeline.md` | Agent instructions for WFO review |

### Data
| Path | Content |
|------|---------|
| `wfo_configs/{bot_id}.yaml` | Per-bot WFO parameter space config |
| `data/curated/{date}/{bot_id}/trades.jsonl` | Trade events |
| `data/curated/{date}/{bot_id}/missed.jsonl` | Missed opportunity events |
| `runs/wfo-{bot_id}-{date}/wfo_report.json` | Full WFO results |
| `runs/wfo-{bot_id}-{date}/wfo_report.md` | Human-readable report |
| `memory/findings/approvals.jsonl` | Approval request lifecycle |
| `memory/findings/deployments.jsonl` | Deployment monitoring records |

---

## 11. Safety Properties

1. **Never auto-deploys** — human must click Approve in Telegram AND merge the PR
2. **Out-of-sample only** — never recommends params validated only in-sample
3. **Deterministic** — grid search is exhaustive, fold generation fixed, consensus via mode, recommendation via thresholds
4. **Multi-layered validation** — leakage audit, cost sensitivity, neighborhood stability, regime stability, safety flags
5. **High-severity flags auto-REJECT** — overfit, fragile, or leakage findings block adoption
6. **Minimum statistical significance** — 30+ trades per fold required
7. **Post-deploy monitoring** — 24-hour regression watch with automatic rollback PR
8. **Idempotent** — dedup on approval request IDs, deployment IDs, and PR branches
9. **Read-only with respect to bots** — never sends commands to trading bots
