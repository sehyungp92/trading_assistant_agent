# Phase 2: Autonomous System — Revised Plan

## Context

The autonomous pipeline (suggestion → backtest → approve → PR → deploy → monitor) was implemented in a prior session, then evaluated and simplified. The simplification fixed 2 critical bugs (backtester rubber stamp, rollback PR file corruption), removed ~770 lines of dead code (enriched events schemas + A/B testing framework), and deferred premature complexity (threshold learner wiring to strategy engine).

**What works now:**
- Suggestion lifecycle tracking (proposed → accepted → implemented → measured)
- Telegram approval UX with inline keyboards (approve/reject/detail)
- YAML-only PR creation via FileChangeGenerator
- Deployment monitoring with rollback PR capability (basic)
- Data-quality backtesting (validates trade data health, NOT parameter-specific impact)
- Structured output contract (proposed_value/target_param on AgentSuggestion)
- ThresholdLearner exists as standalone module (runs weekly, persists learned values)

**What doesn't work:**
- Parameter-specific backtesting (simulating "what if stop_loss = 0.03 instead of 0.02?")
- Python constant config modification (needed by momentum_trader + k_stock_trader risk params)
- Enriched data extraction from existing TradeEvent fields (filter_decisions, signal_factors, exit_efficiency are emitted but ignored)
- A/B testing (bot-side infrastructure exists but is not activated — no runtime variant routing)
- ThresholdLearner scheduler wiring (exists but learn_thresholds() is never called)
- Detection context capture on suggestions (learner has no data to learn from)
- Deployment metrics collection timing (no pre-deploy baseline captured)

**Design principles:**
1. Prioritize what can work NOW over infrastructure for the future
2. Leverage existing bot infrastructure (BacktestEngine, WFO, experiment analysis) rather than building from scratch
3. For bot-side changes, provide granular details for each bot repo
4. Extract enriched data from existing TradeEvent fields rather than creating new event types
5. Every phase should leave tests green

---

## Phase A: Foundation Fixes

These are wiring gaps and missing pieces that prevent existing code from functioning correctly. No new features — just making existing code actually work.

### A1. Add PYTHON_CONSTANT support to FileChangeGenerator

**Problem:** momentum_trader has ALL 8 parameters as `PYTHON_CONSTANT`. k_stock_trader has 3 risk params (`BASE_RISK_PCT`, `DAILY_STOP_R`, `HEAT_CAP_R`) as `PYTHON_CONSTANT`. Without this, approved suggestions for these params can never generate PRs — the pipeline hits `ValueError("Unsupported param_type: PYTHON_CONSTANT")`.

**Current state:**
- `ParameterType.PYTHON_CONSTANT` exists in the enum (kept during simplification)
- `ParameterDefinition` has `python_path` field with validator
- `FileChangeGenerator.generate_change()` raises ValueError for non-YAML types
- Bot configs in `data/bot_configs/` reference PYTHON_CONSTANT extensively

**Files modified:**
- `skills/file_change_generator.py`

**Implementation details:**

Add `_modify_python_constant()` method to `FileChangeGenerator`:

```python
def _modify_python_constant(self, content: str, python_path: str, new_value: Any) -> str:
    """Replace a module-level constant assignment.

    Matches patterns like:
        BASE_RISK_PCT = 0.02
        MACD_FAST = 12
        TRAIL_ACTIVATION_R = 1.5  # trailing activation

    Uses regex instead of AST rewriting to preserve formatting,
    comments, and whitespace — critical for readable PRs.
    """
    pattern = rf'^({re.escape(python_path)}\s*=\s*)(.+?)(\s*#.*)?$'
    lines = content.split('\n')
    for i, line in enumerate(lines):
        match = re.match(pattern, line)
        if match:
            prefix = match.group(1)
            comment = match.group(3) or ''
            lines[i] = prefix + self._format_python_value(new_value) + comment
            return '\n'.join(lines)
    raise ValueError(f"Constant {python_path} not found in file")
```

Add `_format_python_value()`:

```python
@staticmethod
def _format_python_value(value: Any) -> str:
    """Format value as Python literal (True/False, repr for floats)."""
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, float):
        return repr(value)  # repr preserves precision (0.02 not 0.019999...)
    if isinstance(value, int):
        return str(value)
    return repr(value)
```

Update `generate_change()` dispatch:

```python
if param.param_type == ParameterType.YAML_FIELD:
    modified = self._modify_yaml(original, param.yaml_key, new_value)
elif param.param_type == ParameterType.PYTHON_CONSTANT:
    modified = self._modify_python_constant(original, param.python_path, new_value)
else:
    raise ValueError(f"Unsupported param_type: {param.param_type}")
```

**Test cases** (add to `tests/test_file_change_generator.py`):

| Test | Input | Expected |
|------|-------|----------|
| `test_python_constant_float_change` | `BASE_RISK_PCT = 0.02` → value 0.03 | `BASE_RISK_PCT = 0.03` |
| `test_python_constant_int_change` | `MACD_FAST = 12` → value 15 | `MACD_FAST = 15` |
| `test_python_constant_preserves_comment` | `TRAIL_ACTIVATION_R = 1.5  # activate` → value 2.0 | `TRAIL_ACTIVATION_R = 2.0  # activate` |
| `test_python_constant_preserves_other_lines` | File with multiple constants → change one | Other constants untouched |
| `test_python_constant_not_found_raises` | Constant not in file | `ValueError` |
| `test_python_constant_diff_preview` | Valid change | diff_preview contains old and new values |

**Verification:** After this change, the full autonomous pipeline can generate PRs for momentum_trader and k_stock_trader risk parameters.

---

### A2. Capture detection_context in suggestion recording

**Problem:** ThresholdLearner joins suggestions with outcomes by `suggestion_id` to learn optimal thresholds per detector. But `_record_agent_suggestions()` in `handlers.py` does NOT capture `detection_context` — the detector name, threshold value, and observed value that triggered the suggestion. Without this, the learner's `learn_thresholds()` finds zero joinable records and learns nothing.

**Current state:**
- `DetectionContext` schema exists in `schemas/detection_context.py`
- `StrategyEngine.build_report()` returns `RefinementReport` with suggestions that include detection_context
- `_record_agent_suggestions()` maps `AgentSuggestion` → `SuggestionRecord` but drops detection_context
- `SuggestionRecord` in `schemas/suggestion_tracking.py` has no `detection_context` field

**Files modified:**
- `schemas/suggestion_tracking.py`
- `orchestrator/handlers.py`

**Implementation details:**

1. Add field to `SuggestionRecord`:

```python
class SuggestionRecord(BaseModel):
    # ... existing fields ...
    detection_context: Optional[dict] = None  # {detector_name, threshold_value, observed_value, bot_id}
```

2. In `handlers.py`, pass `refinement_report` (from StrategyEngine) to `_record_agent_suggestions()`:

```python
async def _record_agent_suggestions(
    self,
    validation: ValidationResult,
    run_id: str,
    parsed: ParsedAnalysis | None = None,
    refinement_report: RefinementReport | None = None,  # NEW
) -> dict[str, str]:
```

3. When building each `SuggestionRecord`, match agent suggestion to engine suggestion by `(bot_id, category)` to transfer detection_context:

```python
detection_ctx = None
if refinement_report:
    for engine_sugg in refinement_report.all_suggestions:
        if (engine_sugg.bot_id == sugg.bot_id
            and engine_sugg.category == sugg.category):
            detection_ctx = engine_sugg.detection_context
            break

record = SuggestionRecord(
    # ... existing fields ...
    detection_context=detection_ctx,
)
```

4. Update callers: the weekly handler has access to the `RefinementReport` — pass it through.

**Test cases** (update `tests/test_handlers.py`):

| Test | Description |
|------|-------------|
| `test_record_suggestions_captures_detection_context` | When refinement_report is provided and matches by (bot_id, category), detection_context is stored on SuggestionRecord |
| `test_record_suggestions_no_refinement_report` | When refinement_report is None, detection_context is None (no crash) |
| `test_record_suggestions_no_match` | When no engine suggestion matches, detection_context is None |

---

### A3. Wire ThresholdLearner scheduler job

**Problem:** ThresholdLearner is initialized in `app.py` and the scheduler slot exists in `scheduler.py`, but the function reference may not be properly passed. The learner's `learn_thresholds()` must be called weekly to build data.

**Current state:**
- `ThresholdLearner` created when `config.adaptive_thresholds_enabled` is True
- `scheduler.py` has a `threshold_learning` job slot (cron: Sun 09:30 UTC)
- `app.py` passes `threshold_learning_fn` to `create_scheduler_jobs()`

**Files modified:**
- `orchestrator/app.py` — verify and fix the wiring

**Verification steps:**
1. Read `app.py` to confirm `threshold_learning_fn=threshold_learner.learn_thresholds` is passed
2. Read `scheduler.py` to confirm the job creation block calls the function
3. If either is broken, fix the wiring
4. Add a test that verifies the scheduler creates the job when the function is provided

**Test case:**
- `test_threshold_learner_scheduler_job_created` — when `threshold_learning_fn` is provided, verify job exists in scheduler

---

### A4. Fix deployment monitoring metrics collection timing

**Problem:** `DeploymentMonitor.record_pre_deploy_metrics()` is never called by the handler. When `check_regression()` runs, it has no baseline to compare against, making regression detection impossible.

**Current state:**
- `DeploymentMonitor` has `record_pre_deploy_metrics()` and `record_post_deploy_metrics()` methods
- `_check_deployments()` in handlers.py checks merge status and regression
- But it never calls `collect_metrics_snapshot()` to capture pre-deploy baseline
- `check_regression()` compares `pre_deploy_metrics` vs `post_deploy_metrics` — both are None

**Files modified:**
- `orchestrator/handlers.py` — `_check_deployments()` method

**Implementation details:**

In `_check_deployments()`, add metrics collection at state transitions:

```python
async def _check_deployments(self) -> None:
    for record in self._deployment_monitor.get_monitoring():
        if record.status == DeploymentStatus.PENDING_MERGE:
            merged = await self._deployment_monitor.check_merge_status(record.deployment_id)
            if merged:
                # Collect pre-deploy baseline NOW (before bot picks up changes)
                snapshot = self._deployment_monitor.collect_metrics_snapshot(record.bot_id)
                if snapshot:
                    self._deployment_monitor.record_pre_deploy_metrics(
                        record.deployment_id, snapshot
                    )

        elif record.status == DeploymentStatus.DEPLOYED:
            # Collect post-deploy metrics for comparison
            snapshot = self._deployment_monitor.collect_metrics_snapshot(record.bot_id)
            if snapshot:
                self._deployment_monitor.record_post_deploy_metrics(
                    record.deployment_id, snapshot
                )

            if self._deployment_monitor.check_regression(record.deployment_id):
                await self._deployment_monitor.create_rollback_pr(record.deployment_id)
                # Notify user
                ...
            elif self._deployment_monitor.check_monitoring_window_expired(record.deployment_id):
                # All clear — monitoring complete
                ...
```

**Test cases** (update `tests/test_deployment_monitor.py`):

| Test | Description |
|------|-------------|
| `test_check_deployments_captures_pre_deploy_metrics` | On PENDING_MERGE → MERGED transition, `record_pre_deploy_metrics()` is called |
| `test_check_deployments_captures_post_deploy_metrics` | On DEPLOYED state, `record_post_deploy_metrics()` is called before regression check |
| `test_regression_check_with_both_metrics` | When both pre and post metrics exist, regression detection works |

---

## Phase B: Real Backtesting via Bot Infrastructure

Replace the data-quality-only backtester with parameter-specific impact simulation using each bot's own BacktestEngine. The key insight: bot repos already have complete backtesting infrastructure with realistic fill simulation — don't rebuild it, invoke it.

### B1. Create BacktestBridge — subprocess interface to bot backtesting

**Problem:** The current `SuggestionBacktester` computes metrics from raw trades but doesn't simulate "what would happen if this parameter were different." The bot repos have `BacktestEngine` with `param_overrides` that can do this, but they have completely different dependency trees (ib_async, numpy, etc.). Importing bot code directly would create dependency conflicts.

**Solution:** Invoke each bot's backtest as a subprocess via a standardized CLI script.

**Files created:**
- `skills/backtest_bridge.py`

**Design:**

```python
class BacktestBridge:
    """Runs parameter-specific backtests via bot-repo subprocess.

    Each bot repo that supports backtesting provides a standardized script:
        scripts/run_suggestion_backtest.py --param X --value Y --lookback-days 90

    The script runs the bot's own BacktestEngine with param_overrides,
    outputs JSON metrics to stdout.
    """

    def __init__(self, config_registry: ConfigRegistry) -> None:
        self._registry = config_registry

    def supports_backtest(self, bot_id: str) -> bool:
        """Check if bot has a backtest script."""
        profile = self._registry.get_profile(bot_id)
        if not profile:
            return False
        script = Path(profile.repo_dir) / "scripts" / "run_suggestion_backtest.py"
        return script.exists()

    async def run_backtest(
        self,
        bot_id: str,
        param_name: str,
        current_value: Any,
        proposed_value: Any,
        lookback_days: int = 90,
    ) -> BacktestComparison | None:
        """Run baseline (current params) + proposed (new param) backtests.

        Returns BacktestComparison with real simulation metrics,
        or None if bot doesn't support backtesting or subprocess fails.
        """
        profile = self._registry.get_profile(bot_id)
        if not profile:
            return None

        script_path = Path(profile.repo_dir) / "scripts" / "run_suggestion_backtest.py"
        if not script_path.exists():
            return None

        # Run both backtests (could parallelize with asyncio.gather)
        baseline = await self._run_subprocess(
            script_path, profile.repo_dir,
            param_name=param_name, value=current_value,
            lookback_days=lookback_days,
        )
        proposed = await self._run_subprocess(
            script_path, profile.repo_dir,
            param_name=param_name, value=proposed_value,
            lookback_days=lookback_days,
        )

        if baseline is None or proposed is None:
            return None

        return self._build_comparison(
            bot_id, param_name, current_value, proposed_value,
            baseline, proposed,
        )

    async def _run_subprocess(
        self, script_path: Path, repo_dir: str, *,
        param_name: str, value: Any, lookback_days: int,
    ) -> dict | None:
        """Invoke bot backtest script, parse JSON result from stdout."""
        cmd = [
            sys.executable, str(script_path),
            "--param", param_name,
            "--value", str(value),
            "--lookback-days", str(lookback_days),
            "--output", "json",
        ]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd, cwd=repo_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=300  # 5 min max
            )
        except asyncio.TimeoutError:
            logger.warning("Backtest timed out for %s=%s", param_name, value)
            proc.kill()
            return None

        if proc.returncode != 0:
            logger.warning(
                "Backtest failed (rc=%d) for %s=%s: %s",
                proc.returncode, param_name, value, stderr.decode()[:500],
            )
            return None

        try:
            return json.loads(stdout.decode())
        except json.JSONDecodeError:
            logger.warning("Invalid JSON from backtest for %s=%s", param_name, value)
            return None

    def _build_comparison(
        self, bot_id: str, param_name: str,
        current_value: Any, proposed_value: Any,
        baseline_raw: dict, proposed_raw: dict,
    ) -> BacktestComparison:
        """Convert raw JSON results into BacktestComparison."""
        baseline_metrics = SimulationMetrics(
            total_trades=baseline_raw.get("total_trades", 0),
            win_count=baseline_raw.get("win_count", 0),
            loss_count=baseline_raw.get("loss_count", 0),
            win_rate=baseline_raw.get("win_rate", 0.0),
            sharpe_ratio=baseline_raw.get("sharpe_ratio", 0.0),
            max_drawdown_pct=baseline_raw.get("max_drawdown_pct", 0.0),
            profit_factor=baseline_raw.get("profit_factor", 0.0),
        )
        proposed_metrics = SimulationMetrics(
            total_trades=proposed_raw.get("total_trades", 0),
            win_count=proposed_raw.get("win_count", 0),
            loss_count=proposed_raw.get("loss_count", 0),
            win_rate=proposed_raw.get("win_rate", 0.0),
            sharpe_ratio=proposed_raw.get("sharpe_ratio", 0.0),
            max_drawdown_pct=proposed_raw.get("max_drawdown_pct", 0.0),
            profit_factor=proposed_raw.get("profit_factor", 0.0),
        )

        context = BacktestContext(
            suggestion_id="",  # Filled by caller
            bot_id=bot_id,
            param_name=param_name,
            current_value=current_value,
            proposed_value=proposed_value,
            trade_count=proposed_metrics.total_trades,
            data_days=0,  # Not tracked by subprocess
        )

        return BacktestComparison(
            context=context,
            baseline=baseline_metrics,
            proposed=proposed_metrics,
        )
```

**Test cases** (`tests/test_backtest_bridge.py`):

| Test | Description |
|------|-------------|
| `test_supports_backtest_true` | Bot with script → True |
| `test_supports_backtest_false` | Bot without script → False |
| `test_run_backtest_success` | Mock subprocess returns valid JSON → BacktestComparison returned |
| `test_run_backtest_no_script` | Bot without script → None |
| `test_run_backtest_subprocess_failure` | Script exits non-zero → None (not exception) |
| `test_run_backtest_timeout` | Script hangs → None after timeout |
| `test_run_backtest_invalid_json` | Script outputs garbage → None |
| `test_build_comparison_computes_changes` | Raw dicts → correct sharpe_change_pct, etc. |

---

### B2. Integrate BacktestBridge into SuggestionBacktester

**Problem:** The backtester currently only checks data quality. With BacktestBridge, it can run real simulations when available, falling back to data-quality for bots without backtest capability.

**Files modified:**
- `skills/suggestion_backtester.py`
- `orchestrator/app.py` (wiring)

**Implementation details:**

Update `SuggestionBacktester` constructor:

```python
class SuggestionBacktester:
    def __init__(
        self,
        config_registry: ConfigRegistry,
        data_dir: Path,
        backtest_bridge: BacktestBridge | None = None,  # NEW
    ) -> None:
        self._registry = config_registry
        self._data_dir = data_dir
        self._bridge = backtest_bridge
```

Update `backtest_suggestion()` to try real backtest first:

```python
async def backtest_suggestion(self, ...) -> BacktestComparison:
    param_def = self._registry.get_parameter(bot_id, param_name)
    is_safety_critical = param_def.is_safety_critical if param_def else False

    # 1. Try real backtest via bridge (parameter-specific simulation)
    if self._bridge and self._bridge.supports_backtest(bot_id):
        comparison = await self._bridge.run_backtest(
            bot_id, param_name, current_value, proposed_value
        )
        if comparison is not None:
            comparison.context.suggestion_id = suggestion_id
            passes, notes = self._check_safety(comparison.proposed, is_safety_critical)
            comparison.passes_safety = passes
            comparison.safety_notes = notes
            if comparison.proposed.sharpe_ratio < comparison.baseline.sharpe_ratio:
                comparison.safety_notes.append(
                    f"Proposed Sharpe ({comparison.proposed.sharpe_ratio:.2f}) "
                    f"lower than baseline ({comparison.baseline.sharpe_ratio:.2f})"
                )
            return comparison

    # 2. Fall back to data-quality check (existing behavior)
    trades = self._load_trades(bot_id)
    metrics = self._compute_trade_metrics(trades)
    # ... existing data-quality logic unchanged ...
```

Add safety note distinguishing the two modes:

```python
# After real backtest:
notes.append("Backtest: parameter-specific simulation via bot engine")

# After data-quality check:
notes.append("Note: backtester validates current data quality, not parameter-specific impact")
```

Wire in `app.py`:

```python
backtest_bridge = BacktestBridge(config_registry) if config.autonomous_enabled else None
backtester = SuggestionBacktester(config_registry, db_path, backtest_bridge=backtest_bridge)
```

**Test cases** (update `tests/test_suggestion_backtester.py`):

| Test | Description |
|------|-------------|
| `test_backtest_with_bridge_uses_real_results` | Bridge returns comparison → used directly, safety applied |
| `test_backtest_with_bridge_failure_falls_back` | Bridge returns None → data-quality check used |
| `test_backtest_without_bridge_uses_data_quality` | No bridge provided → existing behavior unchanged |
| `test_backtest_bridge_lower_sharpe_noted` | Proposed Sharpe < baseline → safety note added |
| `test_backtest_safety_note_distinguishes_modes` | Real backtest vs data-quality → different safety notes |

---

### B3. Create bot-side backtest scripts

Each bot that supports backtesting needs a standardized CLI entry point. These are simple scripts that wire the bot's own BacktestEngine to a CLI interface.

#### swing_trader: `_references/swing_trader/scripts/run_suggestion_backtest.py`

**Leverages:**
- `backtest.engine.portfolio_engine.run_portfolio()` — existing multi-symbol backtesting
- `backtest.engine.backtest_config.BacktestConfig` — has `param_overrides: dict[str, float]`
- `backtest.engine.portfolio_engine.PortfolioResult` — has all metrics

```python
#!/usr/bin/env python3
"""Run a single-parameter backtest for trading assistant suggestion validation.

Usage:
    python scripts/run_suggestion_backtest.py \\
        --param daily_mult --value 1.2 --lookback-days 90 --output json

Output (JSON to stdout):
    {"total_trades": 142, "win_count": 85, "loss_count": 57,
     "win_rate": 0.5986, "sharpe_ratio": 1.24, "max_drawdown_pct": 0.087,
     "profit_factor": 1.52, "avg_pnl": 23.45, "total_pnl": 3329.90}
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from backtest.engine.backtest_config import BacktestConfig
from backtest.engine.portfolio_engine import run_portfolio
from backtest.data.data_loader import load_portfolio_data  # adapt to actual module name


def _parse_value(raw: str) -> int | float:
    """Parse string to int or float."""
    try:
        return int(raw)
    except ValueError:
        return float(raw)


def _get_active_symbols() -> list[str]:
    """Read active symbols from config."""
    # Import from strategy config — adapt to actual module
    from strategy.config import SYMBOL_CONFIGS
    return list(SYMBOL_CONFIGS.keys())


def main() -> None:
    parser = argparse.ArgumentParser(description="Run suggestion backtest")
    parser.add_argument("--param", required=True, help="Parameter name to override")
    parser.add_argument("--value", required=True, help="Value to set")
    parser.add_argument("--lookback-days", type=int, default=90)
    parser.add_argument("--output", default="json", choices=["json"])
    args = parser.parse_args()

    value = _parse_value(args.value)
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=args.lookback_days)

    config = BacktestConfig(
        symbols=_get_active_symbols(),
        start_date=start_date,
        end_date=end_date,
        param_overrides={args.param: value},
    )

    data = load_portfolio_data(config)
    result = run_portfolio(data, config)

    metrics = {
        "total_trades": result.total_trades,
        "win_count": result.win_count,
        "loss_count": result.loss_count,
        "win_rate": result.win_rate,
        "sharpe_ratio": result.sharpe_ratio,
        "max_drawdown_pct": result.max_drawdown_pct,
        "profit_factor": result.profit_factor,
        "avg_pnl": result.avg_pnl if hasattr(result, "avg_pnl") else 0.0,
        "total_pnl": result.total_pnl if hasattr(result, "total_pnl") else 0.0,
    }
    json.dump(metrics, sys.stdout)


if __name__ == "__main__":
    main()
```

#### momentum_trader: `_references/momentum_trader/scripts/run_suggestion_backtest.py`

Same structure, different imports:

```python
#!/usr/bin/env python3
"""Run a single-parameter backtest for trading assistant suggestion validation.

Uses momentum_trader's own BacktestEngine with param_overrides.
Momentum trader uses PYTHON_CONSTANT params — the script maps param_name
to the correct override key.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from backtest.engine.backtest_config import BacktestConfig
from backtest.engine.portfolio_engine import run_portfolio
from backtest.data.data_loader import load_portfolio_data


def _parse_value(raw: str) -> int | float:
    try:
        return int(raw)
    except ValueError:
        return float(raw)


def _get_active_symbols() -> list[str]:
    # Adapt to momentum_trader's symbol config
    from config.symbols import ACTIVE_SYMBOLS
    return ACTIVE_SYMBOLS


def main() -> None:
    parser = argparse.ArgumentParser(description="Run suggestion backtest")
    parser.add_argument("--param", required=True)
    parser.add_argument("--value", required=True)
    parser.add_argument("--lookback-days", type=int, default=90)
    parser.add_argument("--output", default="json", choices=["json"])
    args = parser.parse_args()

    value = _parse_value(args.value)
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=args.lookback_days)

    config = BacktestConfig(
        symbols=_get_active_symbols(),
        start_date=start_date,
        end_date=end_date,
        param_overrides={args.param: value},
    )

    data = load_portfolio_data(config)
    result = run_portfolio(data, config)

    metrics = {
        "total_trades": result.total_trades,
        "win_count": result.win_count,
        "loss_count": result.loss_count,
        "win_rate": result.win_rate,
        "sharpe_ratio": result.sharpe_ratio,
        "max_drawdown_pct": result.max_drawdown_pct,
        "profit_factor": result.profit_factor,
        "avg_pnl": getattr(result, "avg_pnl", 0.0),
        "total_pnl": getattr(result, "total_pnl", 0.0),
    }
    json.dump(metrics, sys.stdout)


if __name__ == "__main__":
    main()
```

#### k_stock_trader: No backtest script

k_stock_trader is a Korean stock market bot with a different architecture — it does NOT have a `BacktestEngine` or `PortfolioEngine`. For k_stock_trader, the system continues to use data-quality backtesting only. `BacktestBridge.supports_backtest("k_stock_trader")` returns False.

**Bot-side smoke tests:**

Each bot should have a minimal test:
```python
# _references/swing_trader/tests/test_suggestion_backtest_script.py
def test_script_runs_with_mock_data(tmp_path):
    """Verify script starts, parses args, and produces valid JSON."""
    # Create minimal test data
    # Run script with subprocess
    # Assert JSON output has required keys
```

---

## Phase C: Enriched Data Extraction from Existing TradeEvent Fields

Bots already emit rich structured data inside `TradeEvent` fields. The previous implementation created new event types (IndicatorSnapshot, OrderBookContext, FilterDecisionEvent) — wrong approach, since bots don't emit these as separate events. Instead, extract the data from existing TradeEvent fields during daily metrics building.

### C1. Extract filter decision data from TradeEvent.filter_decisions

**What bots emit (momentum_trader, embedded in every TradeEvent):**
```json
"filter_decisions": [
    {"filter_name": "adx_filter", "threshold": 25, "actual_value": 22.3, "passed": false, "margin_pct": -10.8},
    {"filter_name": "volume_filter", "threshold": 1.5, "actual_value": 2.1, "passed": true, "margin_pct": 28.6}
]
```

**What k_stock_trader emits (different format):**
```json
"would_block_count": 3,
"would_block_log": ["spread_filter: 0.15 > 0.1", "volume_filter: 0.8 < 1.5"]
```

**Files modified:**
- `skills/build_daily_metrics.py` — add `build_filter_decision_summary()` method

**Implementation:**

```python
def build_filter_decision_summary(self, trades: list[dict]) -> dict:
    """Extract filter decision stats from TradeEvent.filter_decisions field.

    Handles two formats:
    1. momentum/swing: structured filter_decisions list
    2. k_stock: would_block_count + would_block_log strings
    """
    filter_stats: dict[str, dict] = {}

    for trade in trades:
        # Format 1: Structured filter_decisions
        decisions = trade.get("filter_decisions", [])
        for fd in decisions:
            name = fd.get("filter_name", "unknown")
            self._update_filter_stats(filter_stats, name, fd)

        # Format 2: k_stock would_block_log
        block_log = trade.get("would_block_log", [])
        for entry in block_log:
            # Parse "filter_name: actual > threshold" or "filter_name: actual < threshold"
            parts = entry.split(":", 1)
            if len(parts) == 2:
                name = parts[0].strip()
                if name not in filter_stats:
                    filter_stats[name] = self._empty_filter_stats(name)
                filter_stats[name]["blocks"] += 1
                filter_stats[name]["total_evaluations"] += 1

    # Compute derived metrics
    for stats in filter_stats.values():
        margins = stats.pop("_margins", [])
        stats["avg_margin_pct"] = sum(margins) / len(margins) if margins else 0.0
        stats["block_rate"] = stats["blocks"] / max(stats["total_evaluations"], 1)

    return {"filters": list(filter_stats.values())}

def _update_filter_stats(self, stats_map, name, fd):
    if name not in stats_map:
        stats_map[name] = self._empty_filter_stats(name, fd.get("threshold"))
    s = stats_map[name]
    s["total_evaluations"] += 1
    if fd.get("passed"):
        s["passes"] += 1
    else:
        s["blocks"] += 1
    margin = fd.get("margin_pct")
    if margin is not None:
        s["_margins"].append(margin)

def _empty_filter_stats(self, name, threshold=None):
    return {
        "filter_name": name,
        "total_evaluations": 0,
        "blocks": 0,
        "passes": 0,
        "threshold": threshold,
        "_margins": [],
    }
```

In `write_curated()`, write `filter_decisions.json`:
```python
fd_summary = self.build_filter_decision_summary(trades)
(curated_dir / "filter_decisions.json").write_text(json.dumps(fd_summary, indent=2))
```

Add `"filter_decisions.json"` to `DailyPromptAssembler._CURATED_FILES`.

**Test cases:**

| Test | Description |
|------|-------------|
| `test_filter_decision_summary_structured` | Trades with momentum-style filter_decisions → correct stats |
| `test_filter_decision_summary_kstock_format` | Trades with would_block_log → parsed correctly |
| `test_filter_decision_summary_mixed` | Some trades have filter_decisions, some don't → graceful |
| `test_filter_decision_summary_empty` | No filter data on any trade → `{"filters": []}` |
| `test_filter_decisions_written_to_curated` | After write_curated(), file exists with correct content |

---

### C2. Extract signal factor data from TradeEvent.signal_factors

**What bots emit (momentum_trader):**
```json
"signal_factors": [
    {"factor_name": "displacement", "factor_value": 0.72, "threshold": 0.55, "contribution": 0.35},
    {"factor_name": "regime_slope", "factor_value": 0.12, "threshold": 0.05, "contribution": 0.25}
]
```

**Files modified:**
- `skills/build_daily_metrics.py` — add `build_signal_factor_summary()` method

**Implementation:**

```python
def build_signal_factor_summary(self, trades: list[dict]) -> dict:
    """Extract signal factor stats from TradeEvent.signal_factors field.

    Groups by factor_name, computes avg value/contribution,
    splits by winner/loser for signal quality analysis.
    """
    factor_stats: dict[str, dict] = {}

    for trade in trades:
        factors = trade.get("signal_factors", [])
        is_winner = (trade.get("pnl", 0) > 0)

        for sf in factors:
            name = sf.get("factor_name", "unknown")
            if name not in factor_stats:
                factor_stats[name] = {
                    "factor_name": name,
                    "count": 0,
                    "threshold": sf.get("threshold"),
                    "_values": [],
                    "_contributions": [],
                    "_win_values": [],
                    "_loss_values": [],
                }
            s = factor_stats[name]
            s["count"] += 1
            val = sf.get("factor_value", 0)
            s["_values"].append(val)
            s["_contributions"].append(sf.get("contribution", 0))
            if is_winner:
                s["_win_values"].append(val)
            else:
                s["_loss_values"].append(val)

    for s in factor_stats.values():
        vals = s.pop("_values")
        contribs = s.pop("_contributions")
        win_v = s.pop("_win_values")
        loss_v = s.pop("_loss_values")
        s["avg_value"] = sum(vals) / len(vals) if vals else 0.0
        s["avg_contribution"] = sum(contribs) / len(contribs) if contribs else 0.0
        s["avg_value_winners"] = sum(win_v) / len(win_v) if win_v else None
        s["avg_value_losers"] = sum(loss_v) / len(loss_v) if loss_v else None

    return {"factors": list(factor_stats.values())}
```

Write `signal_factors.json` in `write_curated()`. Add to `_CURATED_FILES`.

**Test cases:** Mirror C1 pattern.

---

### C3. Extract exit efficiency and MFE/MAE data

**What bots emit (momentum_trader, swing_trader):**
```json
"exit_efficiency": 0.73,
"mfe_r": 2.1,
"mae_r": -0.8
```

**Files modified:**
- `skills/build_daily_metrics.py` — add `build_exit_quality_summary()` method

**Implementation:**

```python
def build_exit_quality_summary(self, trades: list[dict]) -> dict:
    """Extract MFE/MAE and exit efficiency stats from trades."""
    efficiencies = []
    mfe_values = []
    mae_values = []
    captures = []  # exit_efficiency for winners only

    for trade in trades:
        eff = trade.get("exit_efficiency")
        if eff is not None:
            efficiencies.append(eff)
            if trade.get("pnl", 0) > 0:
                captures.append(eff)
        mfe = trade.get("mfe_r")
        if mfe is not None:
            mfe_values.append(mfe)
        mae = trade.get("mae_r")
        if mae is not None:
            mae_values.append(mae)

    def _avg(lst):
        return sum(lst) / len(lst) if lst else None

    def _median(lst):
        if not lst:
            return None
        s = sorted(lst)
        return s[len(s) // 2]

    return {
        "exit_efficiency_avg": _avg(efficiencies),
        "exit_efficiency_median": _median(efficiencies),
        "exit_efficiency_winners_avg": _avg(captures),
        "mfe_avg_r": _avg(mfe_values),
        "mae_avg_r": _avg(mae_values),
        "mfe_median_r": _median(mfe_values),
        "mae_median_r": _median(mae_values),
        "trades_with_data": len(efficiencies),
        "total_trades": len(trades),
    }
```

Write `exit_quality.json` in `write_curated()`. Add to `_CURATED_FILES`.

**Test cases:** Mirror C1 pattern.

---

## Phase D: A/B Testing Activation

This requires coordinated bot-side and orchestrator-side changes. The bot repos already have the infrastructure — this phase activates it.

### D1. Bot-side: Create experiment config files and wire variant routing

Each bot needs:
1. An experiment YAML config file (initially empty, populated by orchestrator when experiments are created)
2. Code to read the config at startup and route symbols to variants

#### k_stock_trader

**Infrastructure that exists:**
- `KMPSwitches.update_from_yaml()` for runtime parameter reload
- `experiment_id` and `experiment_variant` fields in YAML config sections
- Per-switch `would_block_count`/`would_block_log` for comparison

**Files to create/modify:**
- `_references/k_stock_trader/config/experiments.yaml` (NEW)
- `_references/k_stock_trader/strategy_kmp/switches.py` (MODIFY)
- `_references/k_stock_trader/instrumentation/src/trade_logger.py` (MODIFY)

**`config/experiments.yaml` template:**
```yaml
# Active experiments for k_stock_trader.
# Managed by trading assistant — do not edit manually.
# Format:
#   experiments:
#     - experiment_id: "exp_001"
#       hypothesis: "..."
#       strategy_type: "kmp"
#       variants:
#         - name: "control"
#           params: {}                  # empty = use current defaults
#         - name: "treatment"
#           params: {quality_min_threshold: 0.5}
#       allocation_pct: 50              # % of symbols assigned to treatment
#       start_date: "2026-04-01"
#       end_date: null                  # null = manual conclusion
#       min_trades_per_variant: 30
#       primary_metric: "sharpe"
experiments: []
```

**Changes to `switches.py`:**

Add `_load_experiments()` method to read config and assign symbols:

```python
def _load_experiments(self) -> dict[str, dict]:
    """Load active experiments, assign symbols to variants.

    Returns: {symbol: {"experiment_id": ..., "experiment_variant": ...}}
    """
    config_path = self._config_dir / "experiments.yaml"
    if not config_path.exists():
        return {}

    with open(config_path) as f:
        data = yaml.safe_load(f)

    assignments = {}
    for exp in data.get("experiments", []):
        exp_id = exp["experiment_id"]
        variants = exp["variants"]
        allocation = exp.get("allocation_pct", 50)
        strategy = exp.get("strategy_type", "")

        # Deterministic hash-based assignment
        for symbol in self._symbols:
            h = hashlib.md5(f"{exp_id}:{symbol}".encode()).hexdigest()
            pct = int(h[:8], 16) / 0xFFFFFFFF * 100
            variant = variants[0]["name"] if pct >= allocation else variants[1]["name"]
            assignments[symbol] = {
                "experiment_id": exp_id,
                "experiment_variant": variant,
                "param_overrides": next(
                    v["params"] for v in variants if v["name"] == variant
                ),
            }

    return assignments
```

**Changes to `trade_logger.py`:**

When logging a trade, set `experiment_id` and `experiment_variant` from the switch state for that symbol.

#### swing_trader

**Infrastructure that exists:**
- `SymbolConfig.experiment_id` and `experiment_variant` fields (frozen dataclass)
- `AblationFlags` with 16+ toggleable filters for offline analysis
- `BacktestConfig.param_overrides` for parameter injection

**Files to create/modify:**
- `_references/swing_trader/config/experiments.yaml` (NEW) — same schema as k_stock_trader
- `_references/swing_trader/strategy/config.py` (MODIFY)

**Changes to `strategy/config.py`:**

Add `load_experiments()` function:

```python
def load_experiments(symbol_configs: dict[str, SymbolConfig]) -> dict[str, SymbolConfig]:
    """Apply active experiment assignments to symbol configs.

    Reads config/experiments.yaml, assigns symbols to variants,
    returns modified configs with experiment_id/variant set and
    param_overrides applied.
    """
    config_path = Path(__file__).parent.parent / "config" / "experiments.yaml"
    if not config_path.exists():
        return symbol_configs

    with open(config_path) as f:
        data = yaml.safe_load(f)

    modified = dict(symbol_configs)
    for exp in data.get("experiments", []):
        exp_id = exp["experiment_id"]
        variants = exp["variants"]
        allocation = exp.get("allocation_pct", 50)

        for symbol in modified:
            h = hashlib.md5(f"{exp_id}:{symbol}".encode()).hexdigest()
            pct = int(h[:8], 16) / 0xFFFFFFFF * 100
            variant_name = variants[0]["name"] if pct >= allocation else variants[1]["name"]
            variant_params = next(v["params"] for v in variants if v["name"] == variant_name)

            # Create new SymbolConfig with experiment fields + overrides
            current = modified[symbol]
            overrides = {"experiment_id": exp_id, "experiment_variant": variant_name}
            overrides.update(variant_params)
            modified[symbol] = dataclasses.replace(current, **overrides)

    return modified
```

Call at module load: `SYMBOL_CONFIGS = load_experiments(SYMBOL_CONFIGS)`

#### momentum_trader

**Infrastructure that exists:**
- `ExperimentRegistry` + `ExperimentMetadata` (YAML-driven)
- `ExperimentAnalysis` with Welch's t-test, per-variant stats, p-value
- `experiment_id`/`experiment_variant` on TradeEvent

**Files to create/modify:**
- `_references/momentum_trader/config/experiments.yaml` (NEW) — same schema
- `_references/momentum_trader/strategy/config.py` (MODIFY)

momentum_trader's `ExperimentRegistry` already reads from YAML. The gap is:
1. Creating the YAML file (empty template)
2. Wiring `ExperimentRegistry.active_experiments()` into strategy config loading
3. Applying variant-specific param overrides at runtime

**Changes to `strategy/config.py`:**

```python
from instrumentation.src.experiment import ExperimentRegistry

def _apply_experiments():
    """Load active experiments and apply variant routing."""
    registry = ExperimentRegistry(Path("config/experiments.yaml"))
    active = registry.active_experiments()
    if not active:
        return

    for exp in active:
        # Assign symbols to variants using same hash-based method
        ...
```

---

### D2. Orchestrator: Lightweight experiment lifecycle manager

**Problem:** The orchestrator needs to create experiment configs, push them to bot repos, monitor trade counts per variant, and conclude experiments when statistical significance is reached.

**Design decision:** Keep it lightweight (~150 lines). No hand-rolled statistics — use bot-side analysis (momentum_trader's `ExperimentAnalysis` has Welch's t-test). For bots without their own analysis, use a simple trade count + metric comparison.

**Files created:**
- `schemas/experiment_tracking.py` — experiment record schema
- `skills/experiment_manager.py` — lightweight lifecycle manager

**`schemas/experiment_tracking.py`:**

```python
class ExperimentStatus(str, Enum):
    CREATED = "CREATED"
    DEPLOYED = "DEPLOYED"        # Config pushed to bot repo
    MONITORING = "MONITORING"    # Collecting trade data
    CONCLUDED = "CONCLUDED"      # Winner determined
    CANCELLED = "CANCELLED"

class ExperimentRecord(BaseModel):
    experiment_id: str
    bot_id: str
    param_name: str
    hypothesis: str
    control_value: Any
    treatment_value: Any
    status: ExperimentStatus = ExperimentStatus.CREATED
    min_trades_per_variant: int = 30
    primary_metric: str = "sharpe"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    concluded_at: Optional[datetime] = None
    winner: Optional[str] = None              # "control" or "treatment"
    control_trades: int = 0
    treatment_trades: int = 0
    p_value: Optional[float] = None
    conclusion_reason: Optional[str] = None   # "significant", "manual", "timeout"
```

**`skills/experiment_manager.py`:**

```python
class ExperimentManager:
    """Manages experiment lifecycle: create → deploy → monitor → conclude.

    Keeps it simple — delegates statistical analysis to bot-side tools
    (momentum_trader's ExperimentAnalysis) or uses basic metric comparison.
    """

    def __init__(self, config_registry: ConfigRegistry, findings_dir: Path) -> None:
        self._registry = config_registry
        self._findings_dir = findings_dir
        self._storage = findings_dir / "experiments.jsonl"

    def create_experiment(
        self,
        bot_id: str,
        param_name: str,
        control_value: Any,
        treatment_value: Any,
        hypothesis: str,
        min_trades: int = 30,
    ) -> ExperimentRecord:
        """Create experiment record."""
        record = ExperimentRecord(
            experiment_id=f"exp_{hashlib.sha256(f'{bot_id}:{param_name}:{datetime.now().isoformat()}'.encode()).hexdigest()[:8]}",
            bot_id=bot_id,
            param_name=param_name,
            hypothesis=hypothesis,
            control_value=control_value,
            treatment_value=treatment_value,
            min_trades_per_variant=min_trades,
        )
        self._save(record)
        return record

    def generate_bot_experiment_yaml(self, experiment_id: str) -> str:
        """Generate YAML config block for the bot's experiments.yaml file."""
        record = self.get_by_id(experiment_id)
        if not record:
            raise ValueError(f"Experiment {experiment_id} not found")

        return yaml.dump({
            "experiments": [{
                "experiment_id": record.experiment_id,
                "hypothesis": record.hypothesis,
                "variants": [
                    {"name": "control", "params": {record.param_name: record.control_value}},
                    {"name": "treatment", "params": {record.param_name: record.treatment_value}},
                ],
                "allocation_pct": 50,
                "start_date": record.created_at.strftime("%Y-%m-%d"),
                "min_trades_per_variant": record.min_trades_per_variant,
                "primary_metric": record.primary_metric,
            }]
        })

    def check_status(self, experiment_id: str, curated_dir: Path) -> ExperimentRecord:
        """Check trade counts per variant from curated data.

        Reads trades.jsonl files and counts by experiment_variant field.
        """
        record = self.get_by_id(experiment_id)
        if not record:
            raise ValueError(f"Experiment {experiment_id} not found")

        control_count = 0
        treatment_count = 0

        # Scan curated trade data for experiment_id matches
        for day_dir in sorted(curated_dir.glob("*")):
            bot_dir = day_dir / record.bot_id
            trades_file = bot_dir / "trades.jsonl"
            if not trades_file.exists():
                continue
            for line in trades_file.read_text().splitlines():
                trade = json.loads(line)
                if trade.get("experiment_id") != record.experiment_id:
                    continue
                variant = trade.get("experiment_variant", "")
                if variant == "control":
                    control_count += 1
                elif variant == "treatment":
                    treatment_count += 1

        record.control_trades = control_count
        record.treatment_trades = treatment_count
        self._save(record)
        return record

    def conclude(
        self, experiment_id: str, winner: str, reason: str = "manual"
    ) -> ExperimentRecord:
        """Conclude experiment with winner determination."""
        record = self.get_by_id(experiment_id)
        if not record:
            raise ValueError(f"Experiment {experiment_id} not found")
        record.status = ExperimentStatus.CONCLUDED
        record.winner = winner
        record.concluded_at = datetime.now(timezone.utc)
        record.conclusion_reason = reason
        self._save(record)
        return record
```

**Test cases:**

| Test | Description |
|------|-------------|
| `test_create_experiment` | Creates record with deterministic ID |
| `test_generate_bot_yaml` | Generates valid YAML with correct structure |
| `test_check_status_counts_trades` | Reads curated data, counts by variant |
| `test_conclude_sets_winner` | Status → CONCLUDED, winner recorded |
| `test_conclude_records_timestamp` | concluded_at set |

---

### D3. Wire experiment management into approval flow

**Problem:** When a suggestion is approved, the user should have the option to A/B test it instead of immediately deploying.

**Files modified:**
- `skills/approval_handler.py` — add `handle_experiment()` method
- `orchestrator/app.py` — register `experiment_suggestion_*` callback
- `skills/autonomous_pipeline.py` — add `[A/B Test]` button to Telegram notification

**Implementation:**

Add third button to Telegram approval card:
```python
# In autonomous_pipeline.py, _send_telegram_notification():
buttons = [
    {"text": "✅ Approve", "callback_data": f"approve_suggestion_{request.request_id}"},
    {"text": "🔬 A/B Test", "callback_data": f"experiment_suggestion_{request.request_id}"},
    {"text": "❌ Reject", "callback_data": f"reject_suggestion_{request.request_id}"},
]
```

Add handler:
```python
# In approval_handler.py:
async def handle_experiment(self, request_id: str) -> str:
    """Create A/B experiment instead of immediate deployment."""
    request = self._approval_tracker.get_by_id(request_id)
    if not request or not self._experiment_manager:
        return "Experiment creation not available"

    # Extract param details from request
    change = request.param_changes[0]
    record = self._experiment_manager.create_experiment(
        bot_id=request.bot_id,
        param_name=change["param_name"],
        control_value=change.get("current_value"),
        treatment_value=change.get("proposed"),
        hypothesis=request.param_changes[0].get("title", ""),
    )

    # Generate YAML and create PR to add experiment config to bot repo
    yaml_content = self._experiment_manager.generate_bot_experiment_yaml(record.experiment_id)
    # ... create PR with experiment config file change ...

    return f"Experiment {record.experiment_id} created. PR with experiment config will be generated."
```

---

## Phase E: Re-wire Threshold Learner into Strategy Engine

This is the last phase because it benefits from accumulated data from Phases A-D.

### E1. Re-wire ThresholdLearner into StrategyEngine

**Why:** Phase A3 wires the scheduler job so the learner runs weekly. Phase A2 ensures detection_context is captured on suggestions. After enough data accumulates (the learner itself requires `min_samples=10` per detector per bot), the learned thresholds should feed back into the strategy engine's detectors.

**Files modified:**
- `analysis/strategy_engine.py`
- `orchestrator/handlers.py` — pass threshold_learner to StrategyEngine
- `orchestrator/app.py` — pass threshold_learner to Handlers

**Implementation:**

Re-add `threshold_learner` parameter to `StrategyEngine.__init__()`:

```python
class StrategyEngine:
    # Adaptive thresholds: ThresholdLearner feeds learned values into
    # detector thresholds when sufficient outcome data is available
    # (min_samples=10 per detector per bot).
    def __init__(
        self, week_start: str, week_end: str,
        tight_stop_ratio: float = 0.3,
        filter_cost_threshold: float = 0.0,
        regime_loss_threshold: float = 0.0,
        regime_min_weeks: int = 3,
        threshold_learner: ThresholdLearner | None = None,  # RE-ADDED
    ) -> None:
        # ... existing init ...
        self._threshold_learner = threshold_learner
```

Re-add `_get_threshold()` method:

```python
def _get_threshold(
    self, detector: str, name: str, bot_id: str, default: float
) -> float:
    """Return learned threshold if available, else default.

    Safe to call even with no learner or insufficient data — always
    returns a valid threshold value.
    """
    if self._threshold_learner is None:
        return default
    return self._threshold_learner.get_threshold(detector, name, bot_id, default)
```

Replace the 18 hardcoded defaults with `self._get_threshold(...)` calls. The exact replacements are the reverse of the simplification that was done — each detector's threshold constant becomes a `_get_threshold()` call with the same default value.

**Guard:** The learner's `get_threshold()` method returns the default when:
- No learned values exist for this (detector, bot_id, threshold_name) triple
- Sample count is below `min_samples=10`
- Confidence is too low

This means wiring is safe immediately — it's a no-op until data accumulates.

**Test cases** (update `tests/test_adaptive_strategy_engine.py`):

| Test | Description |
|------|-------------|
| `test_engine_uses_learned_threshold` | Mock learner returns learned value → engine uses it |
| `test_engine_uses_default_no_data` | Mock learner returns default (no data) → same as no learner |
| `test_engine_works_without_learner` | `threshold_learner=None` → uses hardcoded defaults |
| `test_engine_detector_outputs_unchanged` | With learner returning defaults → output identical to no-learner |

---

## Dependency Graph

```
Phase A (Foundation) ── no dependencies, start first
  A1: Python constant support         ── standalone
  A2: Detection context capture        ── standalone
  A3: ThresholdLearner scheduler       ── standalone
  A4: Deployment metrics timing        ── standalone

Phase B (Real Backtesting) ── depends on A1 (Python constant PRs need to work)
  B1: BacktestBridge                   ── standalone
  B2: Integrate into SuggestionBacktester ── depends on B1
  B3: Bot-side backtest scripts        ── depends on B1 (output contract)

Phase C (Enriched Data) ── no dependencies, can run parallel with B
  C1: Filter decision extraction       ── standalone
  C2: Signal factor extraction         ── standalone
  C3: Exit quality extraction          ── standalone

Phase D (A/B Testing) ── depends on A2 (detection context for experiment outcomes)
  D1: Bot-side experiment configs      ── standalone
  D2: Orchestrator experiment manager  ── depends on D1
  D3: Wire into approval flow          ── depends on D2

Phase E (Adaptive Thresholds) ── depends on A2 + A3 (data accumulation)
  E1: Re-wire ThresholdLearner         ── depends on A2, A3
```

**Recommended execution order:** A (all 4 in parallel) → B + C in parallel → D → E

---

## Bot-Side Changes Summary

### k_stock_trader (`_references/k_stock_trader/`)

| Change | Phase | Files | Description |
|--------|-------|-------|-------------|
| Experiment config | D1 | `config/experiments.yaml` (new) | Empty experiments YAML template |
| Experiment loading | D1 | `strategy_kmp/switches.py` (modify) | `_load_experiments()` → hash-based symbol→variant assignment |
| Experiment tagging | D1 | `instrumentation/src/trade_logger.py` (modify) | Set `experiment_id`/`experiment_variant` from switch state |
| **No backtest script** | — | — | k_stock_trader lacks BacktestEngine; uses data-quality check only |

### swing_trader (`_references/swing_trader/`)

| Change | Phase | Files | Description |
|--------|-------|-------|-------------|
| Backtest script | B3 | `scripts/run_suggestion_backtest.py` (new) | CLI: `--param X --value Y` → JSON metrics via `run_portfolio()` |
| Backtest test | B3 | `tests/test_suggestion_backtest_script.py` (new) | Smoke test for script |
| Experiment config | D1 | `config/experiments.yaml` (new) | Empty experiments YAML template |
| Experiment loading | D1 | `strategy/config.py` (modify) | `load_experiments()` → modify `SYMBOL_CONFIGS` with variant assignments |

### momentum_trader (`_references/momentum_trader/`)

| Change | Phase | Files | Description |
|--------|-------|-------|-------------|
| Backtest script | B3 | `scripts/run_suggestion_backtest.py` (new) | CLI: uses existing `BacktestConfig` + `param_overrides` |
| Backtest test | B3 | `tests/test_suggestion_backtest_script.py` (new) | Smoke test for script |
| Experiment config | D1 | `config/experiments.yaml` (new) | Empty experiments YAML template |
| Experiment activation | D1 | `strategy/config.py` (modify) | Wire `ExperimentRegistry.active_experiments()` → variant routing |

---

## Trading Assistant Files Summary

### New Files

| File | Phase | Lines (est) | Purpose |
|------|-------|-------------|---------|
| `skills/backtest_bridge.py` | B1 | ~150 | Subprocess interface to bot BacktestEngines |
| `schemas/experiment_tracking.py` | D2 | ~50 | ExperimentRecord, ExperimentStatus |
| `skills/experiment_manager.py` | D2 | ~150 | Lightweight experiment lifecycle |
| `tests/test_backtest_bridge.py` | B1 | ~100 | BacktestBridge tests |
| `tests/test_experiment_manager.py` | D2 | ~80 | ExperimentManager tests |

### Modified Files

| File | Phase | Changes |
|------|-------|---------|
| `skills/file_change_generator.py` | A1 | Add `_modify_python_constant()`, `_format_python_value()` |
| `tests/test_file_change_generator.py` | A1 | Add Python constant test cases |
| `schemas/suggestion_tracking.py` | A2 | Add `detection_context` field |
| `orchestrator/handlers.py` | A2, A4 | Pass detection_context, fix metrics timing |
| `orchestrator/app.py` | A3, B2, D3 | Wire threshold_learner, backtest_bridge, experiment callbacks |
| `skills/suggestion_backtester.py` | B2 | Accept BacktestBridge, try real backtest first |
| `skills/build_daily_metrics.py` | C1-C3 | Add 3 enriched data extraction methods |
| `analysis/prompt_assembler.py` | C1-C3 | Add new curated files to `_CURATED_FILES` |
| `analysis/strategy_engine.py` | E1 | Re-add threshold_learner param + `_get_threshold()` |
| `skills/approval_handler.py` | D3 | Add `handle_experiment()` method |
| `skills/autonomous_pipeline.py` | D3 | Add A/B Test button to Telegram card |

---

## Verification Plan

### After Phase A (Foundation)
```bash
pytest tests/ -v  # All 1927+ tests pass
```
- Verify `FileChangeGenerator` handles `PYTHON_CONSTANT` by running `test_file_change_generator.py`
- Verify detection_context appears in SuggestionRecord when refinement_report is provided
- Verify ThresholdLearner scheduler job is created in app startup
- Verify deployment handler collects pre-deploy metrics on merge transition

### After Phase B (Backtesting)
```bash
pytest tests/test_backtest_bridge.py tests/test_suggestion_backtester.py -v
```
- Mock subprocess to verify BacktestBridge returns real comparison
- Verify SuggestionBacktester tries bridge first, falls back to data-quality
- Verify safety notes distinguish "parameter-specific simulation" from "data quality"

### After Phase C (Enriched Data)
```bash
pytest tests/test_build_daily_metrics.py -v
```
- Build curated data from sample trades with filter_decisions/signal_factors
- Verify `filter_decisions.json`, `signal_factors.json`, `exit_quality.json` written
- Verify new files in `_CURATED_FILES` → included in daily prompt

### After Phase D (A/B Testing)
```bash
pytest tests/test_experiment_manager.py -v
```
- Create experiment → generate YAML → verify valid config
- Check status with mock curated data → correct trade counts
- Conclude experiment → verify winner recorded
- Verify Telegram shows A/B Test button

### After Phase E (Thresholds)
```bash
pytest tests/test_adaptive_strategy_engine.py -v
```
- Verify engine uses learned threshold when learner has data
- Verify engine returns same results with learner returning defaults
- Verify engine works with `threshold_learner=None`

### Full Suite
```bash
pytest tests/ -v  # All tests pass, including new ones
```

---

## Estimated Scope

| Phase | New/Modified Files | New Test Cases | Lines (est) |
|-------|-------------------|----------------|-------------|
| A (Foundation) | 5 modified | ~10 | ~120 |
| B (Backtesting) | 2 new + 2 modified + 2 bot scripts | ~12 | ~400 |
| C (Enriched Data) | 2 modified | ~12 | ~180 |
| D (A/B Testing) | 2 new + 3 modified + 3 bot configs + 3 bot mods | ~10 | ~350 |
| E (Thresholds) | 3 modified | ~6 | ~80 |
| **Total** | ~22 files | ~50 tests | ~1,130 lines |
