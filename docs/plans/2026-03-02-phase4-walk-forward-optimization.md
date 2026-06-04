# Phase 4: Walk-Forward Optimization — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a hardened walk-forward optimization pipeline with leakage prevention, realistic transaction cost modeling, robustness testing, and safety rails — producing actionable parameter recommendations that the orchestrator routes through the existing `requires_approval` permission gate before any changes reach production.

**Architecture:** A deterministic WFO pipeline (`skills/run_wfo.py`) generates temporal folds (anchored or rolling), runs a simplified trade-replay simulator with configurable cost models over each fold's in-sample period, searches the parameter space for optimal settings, validates on out-of-sample data, and applies robustness tests (neighborhood stability, regime stability). A leakage detector audits every feature's data dependency to prove no lookahead occurred. A report builder produces both machine-readable JSON and human-readable markdown. A prompt assembler packages the report for Claude to interpret and recommend ADOPT / TEST_FURTHER / REJECT. The orchestrator triggers WFO via a cron job and routes results through the existing brain→worker→action pipeline.

**Tech Stack:** Python 3.12, Pydantic v2, PyYAML, pytest, pathlib, statistics (stdlib), itertools (stdlib for parameter grid)

**Assumes:** Phases 1–3 are fully implemented — event queue, task registry, orchestrator brain/worker/scheduler, daily/weekly metrics builder, portfolio risk computation, strategy engine, quality gate, prompt assembler, feedback handler, and all schemas exist and pass tests.

**Directory structure this plan creates:**

```
trading_assistant/
  schemas/
    wfo_config.py             # WFOConfig, CostModelConfig, RobustnessConfig, etc.
    wfo_results.py            # FoldDefinition, FoldResult, WFOResult, WFOReport
  skills/
    cost_model.py             # CostModel — transaction cost computation
    fold_generator.py         # FoldGenerator — anchored/rolling temporal splits
    leakage_detector.py       # LeakageDetector — feature timestamp auditing
    backtest_simulator.py     # BacktestSimulator — trade replay with param filtering
    param_optimizer.py        # ParamOptimizer — grid search over parameter space
    robustness_tester.py      # RobustnessTester — neighborhood + regime stability
    run_wfo.py                # WFORunner — main pipeline orchestrating everything
  analysis/
    wfo_report_builder.py     # WFOReportBuilder — JSON + markdown report generation
    wfo_prompt_assembler.py   # WFOPromptAssembler — Claude context package
  orchestrator/
    orchestrator_brain.py     # MODIFY: add SPAWN_WFO action type + wfo_trigger handler
    worker.py                 # MODIFY: add on_wfo pluggable handler
    scheduler.py              # MODIFY: add wfo cron config fields
  tests/
    test_wfo_config.py
    test_wfo_results.py
    test_cost_model.py
    test_fold_generator.py
    test_leakage_detector.py
    test_backtest_simulator.py
    test_param_optimizer.py
    test_robustness_tester.py
    test_wfo_runner.py
    test_wfo_report_builder.py
    test_wfo_prompt_assembler.py
    test_wfo_integration.py
```

---

## Task 0: WFO Configuration Schemas

**Files:**
- Create: `schemas/wfo_config.py`
- Test: `tests/test_wfo_config.py`

**Step 1: Write the failing test**

```python
# tests/test_wfo_config.py
"""Tests for WFO configuration schemas."""
from schemas.wfo_config import (
    WFOMethod,
    OptimizationObjective,
    SlippageModel,
    CostModelConfig,
    LeakagePreventionConfig,
    RobustnessConfig,
    OutputConfig,
    ParameterDef,
    ParameterSpace,
    WFOConfig,
)


class TestWFOMethod:
    def test_all_methods_exist(self):
        assert WFOMethod.ANCHORED == "anchored"
        assert WFOMethod.ROLLING == "rolling"


class TestOptimizationObjective:
    def test_all_objectives_exist(self):
        assert OptimizationObjective.SHARPE == "sharpe"
        assert OptimizationObjective.SORTINO == "sortino"
        assert OptimizationObjective.CALMAR == "calmar"
        assert OptimizationObjective.PROFIT_FACTOR == "profit_factor"


class TestSlippageModel:
    def test_all_models_exist(self):
        assert SlippageModel.FIXED == "fixed"
        assert SlippageModel.SPREAD_PROPORTIONAL == "spread_proportional"
        assert SlippageModel.EMPIRICAL == "empirical"


class TestCostModelConfig:
    def test_creates_with_defaults(self):
        c = CostModelConfig()
        assert c.fees_per_trade_bps == 7.0
        assert c.slippage_model == SlippageModel.FIXED
        assert c.fixed_slippage_bps == 5.0
        assert c.spread_impact is True
        assert c.reject_if_only_profitable_at_zero_cost is True
        assert c.cost_sensitivity_test is True
        assert c.cost_multipliers == [1.0, 1.5, 2.0]

    def test_creates_empirical(self):
        c = CostModelConfig(
            slippage_model=SlippageModel.EMPIRICAL,
            slippage_source="data/curated/slippage_stats.csv",
        )
        assert c.slippage_model == SlippageModel.EMPIRICAL
        assert c.slippage_source == "data/curated/slippage_stats.csv"


class TestLeakagePreventionConfig:
    def test_creates_with_defaults(self):
        lp = LeakagePreventionConfig()
        assert lp.strict_temporal_split is True
        assert lp.no_forward_fill_labels is True
        assert lp.feature_audit is True


class TestRobustnessConfig:
    def test_creates_with_defaults(self):
        r = RobustnessConfig()
        assert r.neighborhood_test is True
        assert r.regime_stability is True
        assert r.min_trades_per_fold == 30
        assert r.neighborhood_pct == 0.1
        assert r.min_profitable_regimes == 3
        assert r.total_regime_types == 4


class TestParameterDef:
    def test_creates_parameter(self):
        p = ParameterDef(
            name="rsi_threshold",
            min_value=20.0,
            max_value=40.0,
            step=5.0,
            current_value=30.0,
        )
        assert p.name == "rsi_threshold"
        assert p.grid_values == [20.0, 25.0, 30.0, 35.0, 40.0]

    def test_grid_values_single_step(self):
        p = ParameterDef(name="stop_atr", min_value=1.0, max_value=1.0, step=0.5, current_value=1.0)
        assert p.grid_values == [1.0]

    def test_grid_values_fractional_step(self):
        p = ParameterDef(name="trail", min_value=1.0, max_value=3.0, step=0.5, current_value=1.5)
        assert p.grid_values == [1.0, 1.5, 2.0, 2.5, 3.0]


class TestParameterSpace:
    def test_creates_space(self):
        ps = ParameterSpace(
            bot_id="bot2",
            parameters=[
                ParameterDef(name="rsi_threshold", min_value=20.0, max_value=40.0, step=5.0, current_value=30.0),
                ParameterDef(name="stop_atr", min_value=1.0, max_value=3.0, step=0.5, current_value=1.5),
            ],
        )
        assert ps.bot_id == "bot2"
        assert len(ps.parameters) == 2
        assert ps.total_combinations == 25  # 5 × 5

    def test_current_params(self):
        ps = ParameterSpace(
            bot_id="bot1",
            parameters=[
                ParameterDef(name="rsi", min_value=20.0, max_value=40.0, step=5.0, current_value=30.0),
            ],
        )
        assert ps.current_params == {"rsi": 30.0}

    def test_empty_space(self):
        ps = ParameterSpace(bot_id="bot1", parameters=[])
        assert ps.total_combinations == 0
        assert ps.current_params == {}


class TestWFOConfig:
    def test_creates_full_config(self):
        cfg = WFOConfig(
            bot_id="bot2",
            method=WFOMethod.ANCHORED,
            in_sample_days=180,
            out_of_sample_days=30,
            step_days=30,
            min_folds=6,
            parameter_space=ParameterSpace(
                bot_id="bot2",
                parameters=[
                    ParameterDef(name="rsi", min_value=20.0, max_value=40.0, step=5.0, current_value=30.0),
                ],
            ),
        )
        assert cfg.bot_id == "bot2"
        assert cfg.method == WFOMethod.ANCHORED
        assert cfg.in_sample_days == 180
        assert cfg.optimization.objective == OptimizationObjective.CALMAR

    def test_defaults(self):
        cfg = WFOConfig(
            bot_id="bot1",
            parameter_space=ParameterSpace(bot_id="bot1", parameters=[]),
        )
        assert cfg.method == WFOMethod.ANCHORED
        assert cfg.in_sample_days == 180
        assert cfg.out_of_sample_days == 30
        assert cfg.step_days == 30
        assert cfg.min_folds == 6
        assert cfg.optimization.objective == OptimizationObjective.CALMAR
        assert cfg.cost_model.fees_per_trade_bps == 7.0
        assert cfg.leakage_prevention.strict_temporal_split is True
        assert cfg.robustness.neighborhood_test is True
        assert cfg.output.param_recommendations is True

    def test_from_yaml_dict(self):
        """Config can be built from a dict (as if loaded from YAML)."""
        raw = {
            "bot_id": "bot3",
            "method": "rolling",
            "in_sample_days": 90,
            "out_of_sample_days": 14,
            "step_days": 14,
            "min_folds": 4,
            "parameter_space": {
                "bot_id": "bot3",
                "parameters": [
                    {"name": "ema_period", "min_value": 10, "max_value": 30, "step": 5, "current_value": 20},
                ],
            },
            "optimization": {"objective": "sharpe", "max_drawdown_constraint": 0.20},
        }
        cfg = WFOConfig(**raw)
        assert cfg.method == WFOMethod.ROLLING
        assert cfg.optimization.objective == OptimizationObjective.SHARPE
        assert cfg.optimization.max_drawdown_constraint == 0.20
```

**Step 2: Run test to verify it fails**

Run: `venv/Scripts/python -m pytest tests/test_wfo_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'schemas.wfo_config'`

**Step 3: Write minimal implementation**

```python
# schemas/wfo_config.py
"""WFO configuration schemas — defines the full parameter space for walk-forward optimization.

Matches the wfo_config.yaml structure from the roadmap (Phase 4.1).
Loaded by skills/run_wfo.py and consumed by the fold generator, optimizer,
cost model, leakage detector, and robustness tester.
"""
from __future__ import annotations

import math
from enum import Enum

from pydantic import BaseModel, computed_field


class WFOMethod(str, Enum):
    ANCHORED = "anchored"
    ROLLING = "rolling"


class OptimizationObjective(str, Enum):
    SHARPE = "sharpe"
    SORTINO = "sortino"
    CALMAR = "calmar"
    PROFIT_FACTOR = "profit_factor"


class SlippageModel(str, Enum):
    FIXED = "fixed"
    SPREAD_PROPORTIONAL = "spread_proportional"
    EMPIRICAL = "empirical"


class OptimizationConfig(BaseModel):
    objective: OptimizationObjective = OptimizationObjective.CALMAR
    secondary: str = "max_drawdown"
    max_drawdown_constraint: float = 0.15


class CostModelConfig(BaseModel):
    fees_per_trade_bps: float = 7.0
    slippage_model: SlippageModel = SlippageModel.FIXED
    fixed_slippage_bps: float = 5.0
    slippage_source: str = ""
    spread_impact: bool = True
    reject_if_only_profitable_at_zero_cost: bool = True
    cost_sensitivity_test: bool = True
    cost_multipliers: list[float] = [1.0, 1.5, 2.0]


class LeakagePreventionConfig(BaseModel):
    strict_temporal_split: bool = True
    no_forward_fill_labels: bool = True
    feature_audit: bool = True


class RobustnessConfig(BaseModel):
    neighborhood_test: bool = True
    regime_stability: bool = True
    min_trades_per_fold: int = 30
    neighborhood_pct: float = 0.1
    min_profitable_regimes: int = 3
    total_regime_types: int = 4


class OutputConfig(BaseModel):
    param_recommendations: bool = True
    robustness_heatmap: bool = True
    equity_curves: bool = True
    regime_breakdown: bool = True
    cost_sensitivity_report: bool = True
    leakage_audit_log: bool = True


class ParameterDef(BaseModel):
    """A single tunable parameter with its search range."""

    name: str
    min_value: float
    max_value: float
    step: float
    current_value: float

    @computed_field  # type: ignore[prop-decorator]
    @property
    def grid_values(self) -> list[float]:
        if self.step <= 0:
            return [self.min_value]
        values: list[float] = []
        v = self.min_value
        while v <= self.max_value + self.step * 1e-9:
            values.append(round(v, 10))
            v += self.step
        return values


class ParameterSpace(BaseModel):
    """The full parameter search space for a bot."""

    bot_id: str
    parameters: list[ParameterDef] = []

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total_combinations(self) -> int:
        if not self.parameters:
            return 0
        return math.prod(len(p.grid_values) for p in self.parameters)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def current_params(self) -> dict[str, float]:
        return {p.name: p.current_value for p in self.parameters}


class WFOConfig(BaseModel):
    """Complete walk-forward optimization configuration — maps to wfo_config.yaml."""

    bot_id: str
    method: WFOMethod = WFOMethod.ANCHORED
    in_sample_days: int = 180
    out_of_sample_days: int = 30
    step_days: int = 30
    min_folds: int = 6
    parameter_space: ParameterSpace
    optimization: OptimizationConfig = OptimizationConfig()
    cost_model: CostModelConfig = CostModelConfig()
    leakage_prevention: LeakagePreventionConfig = LeakagePreventionConfig()
    robustness: RobustnessConfig = RobustnessConfig()
    output: OutputConfig = OutputConfig()
```

**Step 4: Run test to verify it passes**

Run: `venv/Scripts/python -m pytest tests/test_wfo_config.py -v`
Expected: All 17 tests PASS

**Step 5: Commit**

```bash
git add schemas/wfo_config.py tests/test_wfo_config.py
git commit -m "feat: add WFO configuration schemas for walk-forward optimization"
```

---

## Task 1: WFO Result Schemas

**Files:**
- Create: `schemas/wfo_results.py`
- Test: `tests/test_wfo_results.py`

**Step 1: Write the failing test**

```python
# tests/test_wfo_results.py
"""Tests for WFO result schemas."""
from schemas.wfo_results import (
    FoldDefinition,
    SimulationMetrics,
    FoldResult,
    CostSensitivityResult,
    LeakageAuditEntry,
    RobustnessResult,
    WFORecommendation,
    SafetyFlag,
    WFOReport,
)


class TestFoldDefinition:
    def test_creates_fold(self):
        f = FoldDefinition(
            fold_number=0,
            is_start="2025-07-01",
            is_end="2025-12-28",
            oos_start="2025-12-28",
            oos_end="2026-01-27",
        )
        assert f.fold_number == 0
        assert f.is_start == "2025-07-01"
        assert f.oos_end == "2026-01-27"

    def test_fold_numbering(self):
        f = FoldDefinition(
            fold_number=3,
            is_start="2025-07-01",
            is_end="2026-01-27",
            oos_start="2026-01-27",
            oos_end="2026-02-26",
        )
        assert f.fold_number == 3


class TestSimulationMetrics:
    def test_creates_metrics(self):
        m = SimulationMetrics(
            total_trades=100,
            win_count=60,
            loss_count=40,
            gross_pnl=5000.0,
            net_pnl=4500.0,
            max_drawdown_pct=0.08,
            sharpe_ratio=1.8,
            sortino_ratio=2.5,
            calmar_ratio=3.0,
            profit_factor=1.9,
            total_fees=300.0,
            total_slippage=200.0,
        )
        assert m.win_rate == 0.6
        assert m.net_pnl == 4500.0

    def test_win_rate_zero_trades(self):
        m = SimulationMetrics()
        assert m.win_rate == 0.0

    def test_default_metrics_all_zero(self):
        m = SimulationMetrics()
        assert m.total_trades == 0
        assert m.gross_pnl == 0.0
        assert m.sharpe_ratio == 0.0


class TestFoldResult:
    def test_creates_result(self):
        fold = FoldDefinition(
            fold_number=0,
            is_start="2025-07-01", is_end="2025-12-28",
            oos_start="2025-12-28", oos_end="2026-01-27",
        )
        r = FoldResult(
            fold=fold,
            best_params={"rsi": 35.0, "stop_atr": 2.0},
            is_metrics=SimulationMetrics(total_trades=120, net_pnl=6000.0, sharpe_ratio=2.0),
            oos_metrics=SimulationMetrics(total_trades=25, net_pnl=800.0, sharpe_ratio=1.2),
        )
        assert r.best_params["rsi"] == 35.0
        assert r.is_metrics.net_pnl == 6000.0
        assert r.oos_metrics.net_pnl == 800.0

    def test_oos_degradation(self):
        fold = FoldDefinition(
            fold_number=0,
            is_start="2025-07-01", is_end="2025-12-28",
            oos_start="2025-12-28", oos_end="2026-01-27",
        )
        r = FoldResult(
            fold=fold,
            best_params={"rsi": 30.0},
            is_metrics=SimulationMetrics(sharpe_ratio=2.0),
            oos_metrics=SimulationMetrics(sharpe_ratio=0.5),
        )
        assert r.oos_degradation_pct == 0.75  # (2.0 - 0.5) / 2.0


class TestCostSensitivityResult:
    def test_creates_result(self):
        c = CostSensitivityResult(
            cost_multiplier=1.5,
            metrics=SimulationMetrics(net_pnl=3000.0, sharpe_ratio=1.1),
        )
        assert c.cost_multiplier == 1.5
        assert c.metrics.sharpe_ratio == 1.1


class TestLeakageAuditEntry:
    def test_creates_entry(self):
        e = LeakageAuditEntry(
            feature_name="rsi_14",
            computed_at="2026-01-15T12:00:00",
            latest_data_used="2026-01-15T11:00:00",
            passed=True,
        )
        assert e.passed is True

    def test_failed_entry(self):
        e = LeakageAuditEntry(
            feature_name="regime_label",
            computed_at="2026-01-15T12:00:00",
            latest_data_used="2026-01-16T00:00:00",
            passed=False,
            violation="Used future data: latest_data_used > computed_at",
        )
        assert e.passed is False
        assert "future data" in e.violation


class TestRobustnessResult:
    def test_creates_result(self):
        r = RobustnessResult(
            neighborhood_scores={"rsi=30": 1.5, "rsi=35": 1.8, "rsi=25": 1.4},
            neighborhood_stable=True,
            regime_pnl={"trending_up": 500.0, "trending_down": -50.0, "ranging": 100.0, "volatile": 200.0},
            profitable_regime_count=3,
            regime_stable=True,
            robustness_score=82.0,
        )
        assert r.neighborhood_stable is True
        assert r.regime_stable is True
        assert r.robustness_score == 82.0


class TestWFORecommendation:
    def test_all_recommendations_exist(self):
        assert WFORecommendation.ADOPT == "adopt"
        assert WFORecommendation.TEST_FURTHER == "test_further"
        assert WFORecommendation.REJECT == "reject"


class TestSafetyFlag:
    def test_creates_flag(self):
        f = SafetyFlag(
            flag_type="likely_overfit",
            description="Spiky optimization surface: ±10% params reduce Sharpe by >50%",
            severity="high",
        )
        assert f.flag_type == "likely_overfit"
        assert f.severity == "high"


class TestWFOReport:
    def test_creates_minimal_report(self):
        r = WFOReport(
            bot_id="bot2",
            config_summary={"method": "anchored", "in_sample_days": 180},
            current_params={"rsi": 30.0},
            suggested_params={"rsi": 35.0},
            recommendation=WFORecommendation.ADOPT,
        )
        assert r.bot_id == "bot2"
        assert r.recommendation == WFORecommendation.ADOPT

    def test_full_report(self):
        fold = FoldDefinition(
            fold_number=0,
            is_start="2025-07-01", is_end="2025-12-28",
            oos_start="2025-12-28", oos_end="2026-01-27",
        )
        r = WFOReport(
            bot_id="bot2",
            config_summary={"method": "anchored"},
            current_params={"rsi": 30.0},
            suggested_params={"rsi": 35.0},
            fold_results=[
                FoldResult(
                    fold=fold,
                    best_params={"rsi": 35.0},
                    is_metrics=SimulationMetrics(sharpe_ratio=2.0),
                    oos_metrics=SimulationMetrics(sharpe_ratio=1.5),
                ),
            ],
            aggregate_oos_metrics=SimulationMetrics(sharpe_ratio=1.5),
            cost_sensitivity=[
                CostSensitivityResult(cost_multiplier=1.0, metrics=SimulationMetrics(sharpe_ratio=1.5)),
                CostSensitivityResult(cost_multiplier=1.5, metrics=SimulationMetrics(sharpe_ratio=1.1)),
                CostSensitivityResult(cost_multiplier=2.0, metrics=SimulationMetrics(sharpe_ratio=0.7)),
            ],
            robustness=RobustnessResult(
                robustness_score=75.0,
                neighborhood_stable=True,
                regime_stable=True,
                profitable_regime_count=3,
            ),
            safety_flags=[
                SafetyFlag(flag_type="fragile", description="At 2x costs, Sharpe < 1.0", severity="medium"),
            ],
            recommendation=WFORecommendation.TEST_FURTHER,
            recommendation_reasoning="OOS Sharpe 1.5 is good but fragile at higher costs.",
        )
        assert len(r.fold_results) == 1
        assert len(r.cost_sensitivity) == 3
        assert len(r.safety_flags) == 1
        assert r.recommendation == WFORecommendation.TEST_FURTHER

    def test_rejected_report(self):
        r = WFOReport(
            bot_id="bot1",
            config_summary={"method": "anchored"},
            current_params={"ema": 20.0},
            suggested_params={"ema": 20.0},
            recommendation=WFORecommendation.REJECT,
            recommendation_reasoning="Current params already optimal. No improvement found.",
            safety_flags=[
                SafetyFlag(flag_type="low_conviction", description="Flat optimization surface", severity="high"),
            ],
        )
        assert r.recommendation == WFORecommendation.REJECT
        assert r.suggested_params == r.current_params
```

**Step 2: Run test to verify it fails**

Run: `venv/Scripts/python -m pytest tests/test_wfo_results.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'schemas.wfo_results'`

**Step 3: Write minimal implementation**

```python
# schemas/wfo_results.py
"""WFO result schemas — models for fold definitions, simulation results, and reports.

Produced by the WFO pipeline (skills/run_wfo.py) and consumed by the report builder
(analysis/wfo_report_builder.py) and prompt assembler (analysis/wfo_prompt_assembler.py).
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, computed_field


class FoldDefinition(BaseModel):
    """Temporal boundaries for one WFO fold."""

    fold_number: int
    is_start: str  # YYYY-MM-DD
    is_end: str
    oos_start: str
    oos_end: str


class SimulationMetrics(BaseModel):
    """Performance metrics from a simulation run."""

    total_trades: int = 0
    win_count: int = 0
    loss_count: int = 0
    gross_pnl: float = 0.0
    net_pnl: float = 0.0
    max_drawdown_pct: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    calmar_ratio: float = 0.0
    profit_factor: float = 0.0
    total_fees: float = 0.0
    total_slippage: float = 0.0
    trades_by_regime: dict[str, int] = {}
    pnl_by_regime: dict[str, float] = {}
    daily_pnl: dict[str, float] = {}  # date → PnL for equity curve

    @computed_field  # type: ignore[prop-decorator]
    @property
    def win_rate(self) -> float:
        if self.total_trades == 0:
            return 0.0
        return self.win_count / self.total_trades


class FoldResult(BaseModel):
    """Results for one WFO fold: best params from IS, performance on OOS."""

    fold: FoldDefinition
    best_params: dict[str, float]
    is_metrics: SimulationMetrics = SimulationMetrics()
    oos_metrics: SimulationMetrics = SimulationMetrics()

    @computed_field  # type: ignore[prop-decorator]
    @property
    def oos_degradation_pct(self) -> float:
        """How much the objective metric dropped from IS to OOS. 0.0 = no drop, 1.0 = total loss."""
        is_val = self.is_metrics.sharpe_ratio
        oos_val = self.oos_metrics.sharpe_ratio
        if is_val == 0:
            return 0.0
        return (is_val - oos_val) / is_val


class CostSensitivityResult(BaseModel):
    """Simulation results at a specific cost multiplier."""

    cost_multiplier: float
    metrics: SimulationMetrics = SimulationMetrics()


class LeakageAuditEntry(BaseModel):
    """One entry in the leakage audit log — verifies a feature's temporal correctness."""

    feature_name: str
    computed_at: str  # ISO timestamp
    latest_data_used: str  # ISO timestamp
    passed: bool
    violation: str = ""


class RobustnessResult(BaseModel):
    """Results from neighborhood and regime stability tests."""

    neighborhood_scores: dict[str, float] = {}
    neighborhood_stable: bool = False
    regime_pnl: dict[str, float] = {}
    profitable_regime_count: int = 0
    regime_stable: bool = False
    robustness_score: float = 0.0  # 0–100


class WFORecommendation(str, Enum):
    ADOPT = "adopt"
    TEST_FURTHER = "test_further"
    REJECT = "reject"


class SafetyFlag(BaseModel):
    """A safety warning attached to WFO results."""

    flag_type: str  # low_conviction | likely_overfit | fragile
    description: str
    severity: str = "medium"  # low | medium | high


class WFOReport(BaseModel):
    """Complete WFO output — consumed by report builder and prompt assembler."""

    bot_id: str
    config_summary: dict = {}
    current_params: dict[str, float] = {}
    suggested_params: dict[str, float] = {}
    fold_results: list[FoldResult] = []
    aggregate_oos_metrics: SimulationMetrics = SimulationMetrics()
    cost_sensitivity: list[CostSensitivityResult] = []
    leakage_audit: list[LeakageAuditEntry] = []
    robustness: RobustnessResult = RobustnessResult()
    safety_flags: list[SafetyFlag] = []
    recommendation: WFORecommendation = WFORecommendation.REJECT
    recommendation_reasoning: str = ""
```

**Step 4: Run test to verify it passes**

Run: `venv/Scripts/python -m pytest tests/test_wfo_results.py -v`
Expected: All 15 tests PASS

**Step 5: Commit**

```bash
git add schemas/wfo_results.py tests/test_wfo_results.py
git commit -m "feat: add WFO result schemas for fold definitions, metrics, and reports"
```

---

## Task 2: Cost Model

**Files:**
- Create: `skills/cost_model.py`
- Test: `tests/test_cost_model.py`

**Step 1: Write the failing test**

```python
# tests/test_cost_model.py
"""Tests for transaction cost model."""
import json
from pathlib import Path

from schemas.wfo_config import CostModelConfig, SlippageModel
from skills.cost_model import CostModel, TradeCosts


class TestTradeCosts:
    def test_total_is_sum(self):
        tc = TradeCosts(fees=10.0, slippage=5.0)
        assert tc.total == 15.0

    def test_zero_costs(self):
        tc = TradeCosts()
        assert tc.total == 0.0


class TestCostModelFixed:
    def test_round_trip_fees(self):
        cfg = CostModelConfig(fees_per_trade_bps=7.0, slippage_model=SlippageModel.FIXED, fixed_slippage_bps=0.0)
        model = CostModel(cfg)
        # Entry at $40000, 0.1 BTC → notional = $4000
        # Round-trip fees: 4000 * 7/10000 * 2 = $5.60
        costs = model.compute_costs(entry_price=40000.0, position_size=0.1)
        assert abs(costs.fees - 5.60) < 0.01
        assert costs.slippage == 0.0

    def test_fixed_slippage(self):
        cfg = CostModelConfig(fees_per_trade_bps=0.0, slippage_model=SlippageModel.FIXED, fixed_slippage_bps=5.0)
        model = CostModel(cfg)
        # Notional = $4000, round-trip slippage: 4000 * 5/10000 * 2 = $4.00
        costs = model.compute_costs(entry_price=40000.0, position_size=0.1)
        assert costs.fees == 0.0
        assert abs(costs.slippage - 4.00) < 0.01

    def test_combined_costs(self):
        cfg = CostModelConfig(fees_per_trade_bps=7.0, slippage_model=SlippageModel.FIXED, fixed_slippage_bps=5.0)
        model = CostModel(cfg)
        costs = model.compute_costs(entry_price=40000.0, position_size=0.1)
        assert abs(costs.total - 9.60) < 0.01  # 5.60 + 4.00

    def test_zero_position(self):
        cfg = CostModelConfig()
        model = CostModel(cfg)
        costs = model.compute_costs(entry_price=40000.0, position_size=0.0)
        assert costs.total == 0.0


class TestCostModelSpreadProportional:
    def test_spread_slippage(self):
        cfg = CostModelConfig(
            fees_per_trade_bps=0.0,
            slippage_model=SlippageModel.SPREAD_PROPORTIONAL,
            fixed_slippage_bps=0.0,
        )
        model = CostModel(cfg)
        # Spread = 10 bps on $4000 notional, round trip: 4000 * 10/10000 * 2 = $8.00
        costs = model.compute_costs(entry_price=40000.0, position_size=0.1, spread_bps=10.0)
        assert abs(costs.slippage - 8.00) < 0.01

    def test_zero_spread(self):
        cfg = CostModelConfig(
            fees_per_trade_bps=0.0,
            slippage_model=SlippageModel.SPREAD_PROPORTIONAL,
        )
        model = CostModel(cfg)
        costs = model.compute_costs(entry_price=40000.0, position_size=0.1, spread_bps=0.0)
        assert costs.slippage == 0.0


class TestCostModelEmpirical:
    def test_loads_slippage_stats(self, tmp_path: Path):
        stats = {"default": 6.0, "trending_up": 4.0, "volatile": 12.0}
        stats_path = tmp_path / "slippage_stats.json"
        stats_path.write_text(json.dumps(stats))
        cfg = CostModelConfig(
            fees_per_trade_bps=0.0,
            slippage_model=SlippageModel.EMPIRICAL,
            slippage_source=str(stats_path),
        )
        model = CostModel(cfg)
        # Volatile regime: 4000 * 12/10000 * 2 = $9.60
        costs = model.compute_costs(entry_price=40000.0, position_size=0.1, regime="volatile")
        assert abs(costs.slippage - 9.60) < 0.01

    def test_falls_back_to_default(self, tmp_path: Path):
        stats = {"default": 6.0}
        stats_path = tmp_path / "slippage_stats.json"
        stats_path.write_text(json.dumps(stats))
        cfg = CostModelConfig(
            fees_per_trade_bps=0.0,
            slippage_model=SlippageModel.EMPIRICAL,
            slippage_source=str(stats_path),
        )
        model = CostModel(cfg)
        # Unknown regime → default: 4000 * 6/10000 * 2 = $4.80
        costs = model.compute_costs(entry_price=40000.0, position_size=0.1, regime="unknown_regime")
        assert abs(costs.slippage - 4.80) < 0.01

    def test_missing_stats_uses_fixed_fallback(self):
        cfg = CostModelConfig(
            fees_per_trade_bps=0.0,
            slippage_model=SlippageModel.EMPIRICAL,
            slippage_source="nonexistent_path.json",
            fixed_slippage_bps=5.0,
        )
        model = CostModel(cfg)
        costs = model.compute_costs(entry_price=40000.0, position_size=0.1)
        assert abs(costs.slippage - 4.00) < 0.01  # falls back to fixed


class TestCostModelMultiplier:
    def test_multiplier_scales_costs(self):
        cfg = CostModelConfig(fees_per_trade_bps=7.0, slippage_model=SlippageModel.FIXED, fixed_slippage_bps=5.0)
        model = CostModel(cfg)
        base = model.compute_costs(entry_price=40000.0, position_size=0.1, cost_multiplier=1.0)
        scaled = model.compute_costs(entry_price=40000.0, position_size=0.1, cost_multiplier=2.0)
        assert abs(scaled.total - base.total * 2) < 0.01

    def test_zero_multiplier(self):
        cfg = CostModelConfig(fees_per_trade_bps=7.0, slippage_model=SlippageModel.FIXED, fixed_slippage_bps=5.0)
        model = CostModel(cfg)
        costs = model.compute_costs(entry_price=40000.0, position_size=0.1, cost_multiplier=0.0)
        assert costs.total == 0.0
```

**Step 2: Run test to verify it fails**

Run: `venv/Scripts/python -m pytest tests/test_cost_model.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'skills.cost_model'`

**Step 3: Write minimal implementation**

```python
# skills/cost_model.py
"""Transaction cost model — computes realistic fees and slippage.

Supports three slippage models:
  - fixed: constant bps per trade
  - spread_proportional: slippage = spread in bps
  - empirical: regime-specific bps loaded from historical data

Cost multiplier support for sensitivity testing at 1x, 1.5x, 2x costs.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from schemas.wfo_config import CostModelConfig, SlippageModel

logger = logging.getLogger(__name__)


@dataclass
class TradeCosts:
    """Breakdown of transaction costs for a single trade."""

    fees: float = 0.0
    slippage: float = 0.0

    @property
    def total(self) -> float:
        return self.fees + self.slippage


class CostModel:
    """Computes transaction costs given config and trade details."""

    def __init__(self, config: CostModelConfig) -> None:
        self._config = config
        self._empirical_stats: dict[str, float] | None = None
        if config.slippage_model == SlippageModel.EMPIRICAL and config.slippage_source:
            self._empirical_stats = self._load_stats(config.slippage_source)

    def compute_costs(
        self,
        entry_price: float,
        position_size: float,
        spread_bps: float = 0.0,
        regime: str = "",
        cost_multiplier: float = 1.0,
    ) -> TradeCosts:
        """Compute round-trip transaction costs for a single trade."""
        notional = entry_price * position_size
        if notional == 0 or cost_multiplier == 0:
            return TradeCosts()

        fees = notional * self._config.fees_per_trade_bps / 10_000 * 2
        slippage = self._compute_slippage(notional, spread_bps, regime)

        return TradeCosts(
            fees=fees * cost_multiplier,
            slippage=slippage * cost_multiplier,
        )

    def _compute_slippage(self, notional: float, spread_bps: float, regime: str) -> float:
        if self._config.slippage_model == SlippageModel.FIXED:
            return notional * self._config.fixed_slippage_bps / 10_000 * 2

        if self._config.slippage_model == SlippageModel.SPREAD_PROPORTIONAL:
            return notional * spread_bps / 10_000 * 2

        if self._config.slippage_model == SlippageModel.EMPIRICAL:
            bps = self._get_empirical_bps(regime)
            return notional * bps / 10_000 * 2

        return 0.0

    def _get_empirical_bps(self, regime: str) -> float:
        if self._empirical_stats is None:
            # Fallback to fixed slippage if stats unavailable
            return self._config.fixed_slippage_bps
        return self._empirical_stats.get(regime, self._empirical_stats.get("default", 0.0))

    @staticmethod
    def _load_stats(path_str: str) -> dict[str, float] | None:
        path = Path(path_str)
        if not path.exists():
            logger.warning("Slippage stats file not found: %s — falling back to fixed", path)
            return None
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            logger.warning("Failed to load slippage stats from %s", path)
            return None
```

**Step 4: Run test to verify it passes**

Run: `venv/Scripts/python -m pytest tests/test_cost_model.py -v`
Expected: All 12 tests PASS

**Step 5: Commit**

```bash
git add skills/cost_model.py tests/test_cost_model.py
git commit -m "feat: add transaction cost model with fixed, spread, and empirical slippage"
```

---

## Task 3: Fold Generator

**Files:**
- Create: `skills/fold_generator.py`
- Test: `tests/test_fold_generator.py`

**Step 1: Write the failing test**

```python
# tests/test_fold_generator.py
"""Tests for WFO fold generator."""
from schemas.wfo_config import WFOConfig, WFOMethod, ParameterSpace
from schemas.wfo_results import FoldDefinition
from skills.fold_generator import FoldGenerator


def _make_config(
    method: WFOMethod = WFOMethod.ANCHORED,
    is_days: int = 180,
    oos_days: int = 30,
    step_days: int = 30,
    min_folds: int = 6,
) -> WFOConfig:
    return WFOConfig(
        bot_id="bot1",
        method=method,
        in_sample_days=is_days,
        out_of_sample_days=oos_days,
        step_days=step_days,
        min_folds=min_folds,
        parameter_space=ParameterSpace(bot_id="bot1", parameters=[]),
    )


class TestAnchoredFolds:
    def test_generates_correct_number_of_folds(self):
        cfg = _make_config(is_days=180, oos_days=30, step_days=30, min_folds=1)
        gen = FoldGenerator(cfg)
        # Data: 2025-01-01 to 2026-03-01 = 424 days
        # Fold 0: IS 0-180, OOS 180-210 → need 210 days
        # Fold 1: IS 0-210, OOS 210-240 → need 240 days
        # ...keeps going until IS_end + OOS > data_end
        folds = gen.generate("2025-01-01", "2026-03-01")
        assert len(folds) >= 6

    def test_is_always_starts_at_data_start(self):
        cfg = _make_config()
        gen = FoldGenerator(cfg)
        folds = gen.generate("2025-01-01", "2026-03-01")
        for f in folds:
            assert f.is_start == "2025-01-01"

    def test_is_end_grows_by_step(self):
        cfg = _make_config(is_days=60, oos_days=30, step_days=30, min_folds=1)
        gen = FoldGenerator(cfg)
        folds = gen.generate("2025-01-01", "2025-12-31")
        if len(folds) >= 2:
            from datetime import datetime

            end_0 = datetime.strptime(folds[0].is_end, "%Y-%m-%d")
            end_1 = datetime.strptime(folds[1].is_end, "%Y-%m-%d")
            assert (end_1 - end_0).days == 30

    def test_oos_immediately_follows_is(self):
        cfg = _make_config()
        gen = FoldGenerator(cfg)
        folds = gen.generate("2025-01-01", "2026-03-01")
        for f in folds:
            assert f.oos_start == f.is_end

    def test_no_oos_past_data_end(self):
        cfg = _make_config()
        gen = FoldGenerator(cfg)
        folds = gen.generate("2025-01-01", "2026-03-01")
        for f in folds:
            assert f.oos_end <= "2026-03-01"

    def test_returns_empty_if_insufficient_data(self):
        cfg = _make_config(is_days=180, oos_days=30, min_folds=6)
        gen = FoldGenerator(cfg)
        # Only 100 days of data — not enough for IS=180 + OOS=30
        folds = gen.generate("2025-01-01", "2025-04-11")
        assert len(folds) == 0

    def test_fold_numbering_sequential(self):
        cfg = _make_config(min_folds=1)
        gen = FoldGenerator(cfg)
        folds = gen.generate("2025-01-01", "2026-03-01")
        for i, f in enumerate(folds):
            assert f.fold_number == i


class TestRollingFolds:
    def test_is_start_advances_by_step(self):
        cfg = _make_config(method=WFOMethod.ROLLING, is_days=90, oos_days=30, step_days=30, min_folds=1)
        gen = FoldGenerator(cfg)
        folds = gen.generate("2025-01-01", "2026-01-01")
        if len(folds) >= 2:
            from datetime import datetime

            start_0 = datetime.strptime(folds[0].is_start, "%Y-%m-%d")
            start_1 = datetime.strptime(folds[1].is_start, "%Y-%m-%d")
            assert (start_1 - start_0).days == 30

    def test_is_length_constant(self):
        cfg = _make_config(method=WFOMethod.ROLLING, is_days=90, oos_days=30, step_days=30, min_folds=1)
        gen = FoldGenerator(cfg)
        folds = gen.generate("2025-01-01", "2026-01-01")
        from datetime import datetime

        for f in folds:
            is_start = datetime.strptime(f.is_start, "%Y-%m-%d")
            is_end = datetime.strptime(f.is_end, "%Y-%m-%d")
            assert (is_end - is_start).days == 90

    def test_no_oos_past_data_end(self):
        cfg = _make_config(method=WFOMethod.ROLLING, min_folds=1)
        gen = FoldGenerator(cfg)
        folds = gen.generate("2025-01-01", "2026-03-01")
        for f in folds:
            assert f.oos_end <= "2026-03-01"


class TestMinFoldsEnforcement:
    def test_returns_empty_below_min_folds(self):
        cfg = _make_config(is_days=180, oos_days=30, step_days=30, min_folds=100)
        gen = FoldGenerator(cfg)
        folds = gen.generate("2025-01-01", "2026-03-01")
        assert len(folds) == 0  # can't generate 100 folds from ~1 year of data
```

**Step 2: Run test to verify it fails**

Run: `venv/Scripts/python -m pytest tests/test_fold_generator.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'skills.fold_generator'`

**Step 3: Write minimal implementation**

```python
# skills/fold_generator.py
"""Fold generator — creates anchored or rolling temporal splits for WFO.

Anchored: IS always starts at data_start, IS end grows by step_days each fold.
Rolling: IS window slides forward by step_days, IS length stays constant.
Both: OOS immediately follows IS, OOS length is fixed.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from schemas.wfo_config import WFOConfig, WFOMethod
from schemas.wfo_results import FoldDefinition


class FoldGenerator:
    """Generates walk-forward optimization folds from a WFO config."""

    def __init__(self, config: WFOConfig) -> None:
        self._config = config

    def generate(self, data_start: str, data_end: str) -> list[FoldDefinition]:
        """Generate folds for the given data range. Returns empty list if insufficient data."""
        if self._config.method == WFOMethod.ANCHORED:
            folds = self._generate_anchored(data_start, data_end)
        else:
            folds = self._generate_rolling(data_start, data_end)

        if len(folds) < self._config.min_folds:
            return []
        return folds

    def _generate_anchored(self, data_start: str, data_end: str) -> list[FoldDefinition]:
        start = _parse(data_start)
        end = _parse(data_end)
        is_days = self._config.in_sample_days
        oos_days = self._config.out_of_sample_days
        step = self._config.step_days

        folds: list[FoldDefinition] = []
        is_end = start + timedelta(days=is_days)

        while is_end + timedelta(days=oos_days) <= end:
            oos_end = is_end + timedelta(days=oos_days)
            folds.append(FoldDefinition(
                fold_number=len(folds),
                is_start=_fmt(start),
                is_end=_fmt(is_end),
                oos_start=_fmt(is_end),
                oos_end=_fmt(oos_end),
            ))
            is_end += timedelta(days=step)

        return folds

    def _generate_rolling(self, data_start: str, data_end: str) -> list[FoldDefinition]:
        start = _parse(data_start)
        end = _parse(data_end)
        is_days = self._config.in_sample_days
        oos_days = self._config.out_of_sample_days
        step = self._config.step_days

        folds: list[FoldDefinition] = []
        is_start = start

        while True:
            is_end = is_start + timedelta(days=is_days)
            oos_end = is_end + timedelta(days=oos_days)
            if oos_end > end:
                break
            folds.append(FoldDefinition(
                fold_number=len(folds),
                is_start=_fmt(is_start),
                is_end=_fmt(is_end),
                oos_start=_fmt(is_end),
                oos_end=_fmt(oos_end),
            ))
            is_start += timedelta(days=step)

        return folds


def _parse(date_str: str) -> datetime:
    return datetime.strptime(date_str, "%Y-%m-%d")


def _fmt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")
```

**Step 4: Run test to verify it passes**

Run: `venv/Scripts/python -m pytest tests/test_fold_generator.py -v`
Expected: All 11 tests PASS

**Step 5: Commit**

```bash
git add skills/fold_generator.py tests/test_fold_generator.py
git commit -m "feat: add anchored and rolling fold generator for WFO temporal splits"
```

---

## Task 4: Leakage Detector

**Files:**
- Create: `skills/leakage_detector.py`
- Test: `tests/test_leakage_detector.py`

**Step 1: Write the failing test**

```python
# tests/test_leakage_detector.py
"""Tests for WFO leakage detector."""
from schemas.wfo_results import LeakageAuditEntry
from skills.leakage_detector import LeakageDetector, FeatureRecord, LabelRecord


class TestFeatureRecord:
    def test_creates_record(self):
        r = FeatureRecord(
            feature_name="rsi_14",
            computed_at="2026-01-15T12:00:00",
            latest_data_used="2026-01-15T11:00:00",
        )
        assert r.feature_name == "rsi_14"


class TestLabelRecord:
    def test_creates_record(self):
        r = LabelRecord(
            trade_id="t1",
            entry_time="2026-01-15T12:00:00",
            label_computed_from="2026-01-15T13:00:00",
        )
        assert r.trade_id == "t1"


class TestNoLookaheadInFeatures:
    def test_passes_when_all_features_valid(self):
        detector = LeakageDetector()
        features = [
            FeatureRecord(feature_name="rsi", computed_at="2026-01-15T12:00:00", latest_data_used="2026-01-15T11:00:00"),
            FeatureRecord(feature_name="ema", computed_at="2026-01-15T12:00:00", latest_data_used="2026-01-15T12:00:00"),
        ]
        entries = detector.audit_features(features)
        assert all(e.passed for e in entries)
        assert len(entries) == 2

    def test_fails_when_feature_uses_future_data(self):
        detector = LeakageDetector()
        features = [
            FeatureRecord(feature_name="rsi", computed_at="2026-01-15T12:00:00", latest_data_used="2026-01-15T11:00:00"),
            FeatureRecord(feature_name="regime", computed_at="2026-01-15T12:00:00", latest_data_used="2026-01-16T00:00:00"),
        ]
        entries = detector.audit_features(features)
        assert entries[0].passed is True
        assert entries[1].passed is False
        assert "future data" in entries[1].violation.lower()

    def test_equal_timestamps_is_valid(self):
        detector = LeakageDetector()
        features = [
            FeatureRecord(feature_name="vol", computed_at="2026-01-15T12:00:00", latest_data_used="2026-01-15T12:00:00"),
        ]
        entries = detector.audit_features(features)
        assert entries[0].passed is True


class TestNoForwardFillLabels:
    def test_passes_when_labels_from_after_entry(self):
        detector = LeakageDetector()
        labels = [
            LabelRecord(trade_id="t1", entry_time="2026-01-15T12:00:00", label_computed_from="2026-01-15T13:00:00"),
            LabelRecord(trade_id="t2", entry_time="2026-01-15T14:00:00", label_computed_from="2026-01-15T14:00:00"),
        ]
        entries = detector.audit_labels(labels)
        assert all(e.passed for e in entries)

    def test_fails_when_label_from_before_entry(self):
        detector = LeakageDetector()
        labels = [
            LabelRecord(trade_id="t1", entry_time="2026-01-15T12:00:00", label_computed_from="2026-01-15T11:00:00"),
        ]
        entries = detector.audit_labels(labels)
        assert entries[0].passed is False
        assert "before entry" in entries[0].violation.lower()


class TestFullAudit:
    def test_combined_audit(self):
        detector = LeakageDetector()
        features = [
            FeatureRecord(feature_name="rsi", computed_at="2026-01-15T12:00:00", latest_data_used="2026-01-15T11:00:00"),
        ]
        labels = [
            LabelRecord(trade_id="t1", entry_time="2026-01-15T12:00:00", label_computed_from="2026-01-15T13:00:00"),
        ]
        entries = detector.full_audit(features, labels)
        assert len(entries) == 2
        assert all(e.passed for e in entries)

    def test_empty_inputs(self):
        detector = LeakageDetector()
        entries = detector.full_audit([], [])
        assert len(entries) == 0
```

**Step 2: Run test to verify it fails**

Run: `venv/Scripts/python -m pytest tests/test_leakage_detector.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'skills.leakage_detector'`

**Step 3: Write minimal implementation**

```python
# skills/leakage_detector.py
"""Leakage detector — audits features and labels for temporal correctness.

Two core checks:
1. No lookahead in features: every feature at time t uses only data at or before t.
2. No forward-fill labels: trade outcomes (TP/SL hit) computed from post-entry data only.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from schemas.wfo_results import LeakageAuditEntry


@dataclass
class FeatureRecord:
    """Metadata for a computed feature — tracks its data dependency."""

    feature_name: str
    computed_at: str  # ISO timestamp
    latest_data_used: str  # ISO timestamp


@dataclass
class LabelRecord:
    """Metadata for a trade label — tracks when the label was computed."""

    trade_id: str
    entry_time: str  # ISO timestamp
    label_computed_from: str  # ISO timestamp of earliest data used to compute label


class LeakageDetector:
    """Audits feature and label timestamps for lookahead or forward-fill leakage."""

    def audit_features(self, features: list[FeatureRecord]) -> list[LeakageAuditEntry]:
        """Check that every feature value uses only data at or before its computation time."""
        entries: list[LeakageAuditEntry] = []
        for f in features:
            computed = _parse(f.computed_at)
            latest = _parse(f.latest_data_used)
            if latest > computed:
                entries.append(LeakageAuditEntry(
                    feature_name=f.feature_name,
                    computed_at=f.computed_at,
                    latest_data_used=f.latest_data_used,
                    passed=False,
                    violation=f"Used future data: latest_data_used ({f.latest_data_used}) > computed_at ({f.computed_at})",
                ))
            else:
                entries.append(LeakageAuditEntry(
                    feature_name=f.feature_name,
                    computed_at=f.computed_at,
                    latest_data_used=f.latest_data_used,
                    passed=True,
                ))
        return entries

    def audit_labels(self, labels: list[LabelRecord]) -> list[LeakageAuditEntry]:
        """Check that trade labels are computed from data after entry only."""
        entries: list[LeakageAuditEntry] = []
        for label in labels:
            entry = _parse(label.entry_time)
            computed_from = _parse(label.label_computed_from)
            if computed_from < entry:
                entries.append(LeakageAuditEntry(
                    feature_name=f"label:{label.trade_id}",
                    computed_at=label.entry_time,
                    latest_data_used=label.label_computed_from,
                    passed=False,
                    violation=f"Label computed from before entry: {label.label_computed_from} < {label.entry_time}",
                ))
            else:
                entries.append(LeakageAuditEntry(
                    feature_name=f"label:{label.trade_id}",
                    computed_at=label.entry_time,
                    latest_data_used=label.label_computed_from,
                    passed=True,
                ))
        return entries

    def full_audit(
        self, features: list[FeatureRecord], labels: list[LabelRecord]
    ) -> list[LeakageAuditEntry]:
        """Run all leakage checks, return combined audit log."""
        return self.audit_features(features) + self.audit_labels(labels)


def _parse(iso_str: str) -> datetime:
    return datetime.fromisoformat(iso_str)
```

**Step 4: Run test to verify it passes**

Run: `venv/Scripts/python -m pytest tests/test_leakage_detector.py -v`
Expected: All 10 tests PASS

**Step 5: Commit**

```bash
git add skills/leakage_detector.py tests/test_leakage_detector.py
git commit -m "feat: add leakage detector for feature lookahead and label forward-fill auditing"
```

---

## Task 5: Backtest Simulator

**Files:**
- Create: `skills/backtest_simulator.py`
- Test: `tests/test_backtest_simulator.py`

The simulator replays historical trades with parameter variations. Given a parameter set, it determines which trades pass the adjusted thresholds (using `entry_signal_strength` vs parameter thresholds) and which missed opportunities would have been taken. It applies the cost model and computes performance metrics.

**Step 1: Write the failing test**

```python
# tests/test_backtest_simulator.py
"""Tests for the backtest simulator."""
from datetime import datetime

from schemas.events import TradeEvent, MissedOpportunityEvent
from schemas.wfo_config import CostModelConfig, SlippageModel
from schemas.wfo_results import SimulationMetrics
from skills.backtest_simulator import BacktestSimulator
from skills.cost_model import CostModel


def _trade(
    trade_id: str,
    pnl: float,
    entry_price: float = 40000.0,
    position_size: float = 0.1,
    entry_signal_strength: float = 0.8,
    market_regime: str = "trending_up",
    entry_signal: str = "ema_cross",
    **kwargs,
) -> TradeEvent:
    return TradeEvent(
        trade_id=trade_id,
        bot_id="bot1",
        pair="BTCUSDT",
        side="LONG",
        entry_time=datetime(2026, 1, 15, 12, 0),
        exit_time=datetime(2026, 1, 15, 14, 0),
        entry_price=entry_price,
        exit_price=entry_price + pnl / position_size,
        position_size=position_size,
        pnl=pnl,
        pnl_pct=pnl / (entry_price * position_size) * 100,
        entry_signal=entry_signal,
        entry_signal_strength=entry_signal_strength,
        market_regime=market_regime,
        **kwargs,
    )


def _missed(
    bot_id: str = "bot1",
    signal_strength: float = 0.6,
    blocked_by: str = "volume_filter",
    outcome_24h: float = 100.0,
    hypothetical_entry: float = 40000.0,
) -> MissedOpportunityEvent:
    return MissedOpportunityEvent(
        bot_id=bot_id,
        pair="BTCUSDT",
        signal="ema_cross",
        signal_strength=signal_strength,
        blocked_by=blocked_by,
        hypothetical_entry=hypothetical_entry,
        outcome_24h=outcome_24h,
        confidence=0.7,
        assumption_tags=["next_trade_fill", "5bps_slippage"],
    )


def _zero_cost_model() -> CostModel:
    return CostModel(CostModelConfig(fees_per_trade_bps=0.0, fixed_slippage_bps=0.0))


def _real_cost_model() -> CostModel:
    return CostModel(CostModelConfig(fees_per_trade_bps=7.0, fixed_slippage_bps=5.0))


class TestBasicSimulation:
    def test_all_trades_pass_with_no_params(self):
        trades = [_trade("t1", 100.0), _trade("t2", -50.0), _trade("t3", 200.0)]
        sim = BacktestSimulator(_zero_cost_model())
        result = sim.simulate(trades, [], params={})
        assert result.total_trades == 3
        assert result.win_count == 2
        assert result.loss_count == 1
        assert result.gross_pnl == 250.0

    def test_filters_by_signal_strength_threshold(self):
        trades = [
            _trade("t1", 100.0, entry_signal_strength=0.9),
            _trade("t2", -50.0, entry_signal_strength=0.3),
            _trade("t3", 200.0, entry_signal_strength=0.7),
        ]
        sim = BacktestSimulator(_zero_cost_model())
        # Only trades with signal_strength >= 0.5 pass
        result = sim.simulate(trades, [], params={"signal_strength_min": 0.5})
        assert result.total_trades == 2
        assert result.gross_pnl == 300.0

    def test_empty_trades(self):
        sim = BacktestSimulator(_zero_cost_model())
        result = sim.simulate([], [], params={})
        assert result.total_trades == 0
        assert result.gross_pnl == 0.0


class TestCostIntegration:
    def test_costs_reduce_net_pnl(self):
        trades = [_trade("t1", 100.0, entry_price=40000.0, position_size=0.1)]
        sim = BacktestSimulator(_real_cost_model())
        result = sim.simulate(trades, [], params={})
        assert result.gross_pnl == 100.0
        assert result.net_pnl < result.gross_pnl
        assert result.total_fees > 0
        assert result.total_slippage > 0

    def test_cost_multiplier(self):
        trades = [_trade("t1", 100.0, entry_price=40000.0, position_size=0.1)]
        sim = BacktestSimulator(_real_cost_model())
        base = sim.simulate(trades, [], params={}, cost_multiplier=1.0)
        doubled = sim.simulate(trades, [], params={}, cost_multiplier=2.0)
        assert doubled.total_fees > base.total_fees
        assert doubled.net_pnl < base.net_pnl


class TestMissedOpportunityInclusion:
    def test_includes_missed_when_filter_relaxed(self):
        trades = [_trade("t1", 100.0)]
        missed = [_missed(outcome_24h=150.0, blocked_by="volume_filter")]
        sim = BacktestSimulator(_zero_cost_model())
        # include_blocked_by=["volume_filter"] means we now take those missed opps
        result = sim.simulate(trades, missed, params={"include_blocked_by": ["volume_filter"]})
        assert result.total_trades == 2
        assert result.gross_pnl == 250.0  # 100 + 150

    def test_does_not_include_missed_without_param(self):
        trades = [_trade("t1", 100.0)]
        missed = [_missed(outcome_24h=150.0)]
        sim = BacktestSimulator(_zero_cost_model())
        result = sim.simulate(trades, missed, params={})
        assert result.total_trades == 1


class TestMetricsComputation:
    def test_regime_breakdown(self):
        trades = [
            _trade("t1", 100.0, market_regime="trending_up"),
            _trade("t2", -50.0, market_regime="ranging"),
            _trade("t3", 200.0, market_regime="trending_up"),
        ]
        sim = BacktestSimulator(_zero_cost_model())
        result = sim.simulate(trades, [], params={})
        assert result.trades_by_regime["trending_up"] == 2
        assert result.trades_by_regime["ranging"] == 1
        assert result.pnl_by_regime["trending_up"] == 300.0
        assert result.pnl_by_regime["ranging"] == -50.0

    def test_sharpe_ratio_positive(self):
        trades = [
            _trade("t1", 100.0),
            _trade("t2", 80.0),
            _trade("t3", 120.0),
            _trade("t4", 90.0),
        ]
        sim = BacktestSimulator(_zero_cost_model())
        result = sim.simulate(trades, [], params={})
        assert result.sharpe_ratio > 0

    def test_max_drawdown(self):
        trades = [
            _trade("t1", 100.0),
            _trade("t2", -200.0),
            _trade("t3", 50.0),
        ]
        sim = BacktestSimulator(_zero_cost_model())
        result = sim.simulate(trades, [], params={})
        assert result.max_drawdown_pct > 0
```

**Step 2: Run test to verify it fails**

Run: `venv/Scripts/python -m pytest tests/test_backtest_simulator.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'skills.backtest_simulator'`

**Step 3: Write minimal implementation**

```python
# skills/backtest_simulator.py
"""Backtest simulator — simplified trade replay with parameter filtering.

Replays historical trades with parameter adjustments:
- Filters trades by signal_strength_min threshold
- Optionally includes missed opportunities (relaxed filters)
- Applies cost model
- Computes performance metrics (Sharpe, Sortino, Calmar, max DD, profit factor)
"""
from __future__ import annotations

import math
import statistics
from collections import defaultdict

from schemas.events import TradeEvent, MissedOpportunityEvent
from schemas.wfo_results import SimulationMetrics
from skills.cost_model import CostModel


class BacktestSimulator:
    """Replays trades with parameter variations and computes metrics."""

    def __init__(self, cost_model: CostModel) -> None:
        self._cost_model = cost_model

    def simulate(
        self,
        trades: list[TradeEvent],
        missed: list[MissedOpportunityEvent],
        params: dict,
        cost_multiplier: float = 1.0,
    ) -> SimulationMetrics:
        """Simulate a parameter set over historical trades and missed opportunities."""
        # 1. Filter trades by params
        accepted = self._filter_trades(trades, params)

        # 2. Include missed opportunities if filters are relaxed
        synthetic = self._include_missed(missed, params)

        # 3. Build PnL series with costs
        pnl_series: list[float] = []
        total_fees = 0.0
        total_slippage = 0.0
        regime_trades: dict[str, int] = defaultdict(int)
        regime_pnl: dict[str, float] = defaultdict(float)

        for t in accepted:
            costs = self._cost_model.compute_costs(
                entry_price=t.entry_price,
                position_size=t.position_size,
                regime=t.market_regime,
                cost_multiplier=cost_multiplier,
            )
            net = t.pnl - costs.total
            pnl_series.append(net)
            total_fees += costs.fees
            total_slippage += costs.slippage
            regime = t.market_regime or "unknown"
            regime_trades[regime] += 1
            regime_pnl[regime] += net

        for m in synthetic:
            outcome = m.outcome_24h or 0.0
            costs = self._cost_model.compute_costs(
                entry_price=m.hypothetical_entry,
                position_size=0.1,  # default position for missed opps
                cost_multiplier=cost_multiplier,
            )
            net = outcome - costs.total
            pnl_series.append(net)
            total_fees += costs.fees
            total_slippage += costs.slippage

        if not pnl_series:
            return SimulationMetrics()

        # 4. Compute metrics
        wins = [p for p in pnl_series if p > 0]
        losses = [p for p in pnl_series if p <= 0]
        gross_pnl = sum(t.pnl for t in accepted) + sum((m.outcome_24h or 0.0) for m in synthetic)
        net_pnl = sum(pnl_series)
        max_dd = self._max_drawdown(pnl_series)
        sharpe = self._sharpe(pnl_series)
        sortino = self._sortino(pnl_series)
        calmar = abs(net_pnl / max_dd) if max_dd > 0 else (float("inf") if net_pnl > 0 else 0.0)
        total_wins = sum(wins) if wins else 0.0
        total_losses = abs(sum(losses)) if losses else 0.0
        pf = total_wins / total_losses if total_losses > 0 else (float("inf") if total_wins > 0 else 0.0)

        return SimulationMetrics(
            total_trades=len(pnl_series),
            win_count=len(wins),
            loss_count=len(losses),
            gross_pnl=gross_pnl,
            net_pnl=net_pnl,
            max_drawdown_pct=max_dd,
            sharpe_ratio=sharpe,
            sortino_ratio=sortino,
            calmar_ratio=calmar,
            profit_factor=pf,
            total_fees=total_fees,
            total_slippage=total_slippage,
            trades_by_regime=dict(regime_trades),
            pnl_by_regime=dict(regime_pnl),
        )

    def _filter_trades(self, trades: list[TradeEvent], params: dict) -> list[TradeEvent]:
        """Apply parameter-based filters to trades."""
        result = list(trades)
        min_strength = params.get("signal_strength_min")
        if min_strength is not None:
            result = [t for t in result if t.entry_signal_strength >= min_strength]
        return result

    def _include_missed(
        self, missed: list[MissedOpportunityEvent], params: dict
    ) -> list[MissedOpportunityEvent]:
        """Include missed opportunities whose blocking filter is being relaxed."""
        include_filters: list[str] = params.get("include_blocked_by", [])
        if not include_filters:
            return []
        return [m for m in missed if m.blocked_by in include_filters]

    @staticmethod
    def _max_drawdown(pnl_series: list[float]) -> float:
        """Compute max drawdown as a fraction of peak equity."""
        if not pnl_series:
            return 0.0
        equity = 0.0
        peak = 0.0
        max_dd = 0.0
        for pnl in pnl_series:
            equity += pnl
            if equity > peak:
                peak = equity
            dd = (peak - equity) / peak if peak > 0 else 0.0
            if dd > max_dd:
                max_dd = dd
        return max_dd

    @staticmethod
    def _sharpe(pnl_series: list[float]) -> float:
        """Annualized Sharpe ratio (daily PnL, ~252 trading days)."""
        if len(pnl_series) < 2:
            return 0.0
        mean = statistics.mean(pnl_series)
        stdev = statistics.stdev(pnl_series)
        if stdev == 0:
            return 0.0
        return (mean / stdev) * math.sqrt(252)

    @staticmethod
    def _sortino(pnl_series: list[float]) -> float:
        """Annualized Sortino ratio (only downside deviation)."""
        if len(pnl_series) < 2:
            return 0.0
        mean = statistics.mean(pnl_series)
        downside = [p for p in pnl_series if p < 0]
        if not downside:
            return float("inf") if mean > 0 else 0.0
        downside_dev = math.sqrt(statistics.mean([d ** 2 for d in downside]))
        if downside_dev == 0:
            return 0.0
        return (mean / downside_dev) * math.sqrt(252)
```

**Step 4: Run test to verify it passes**

Run: `venv/Scripts/python -m pytest tests/test_backtest_simulator.py -v`
Expected: All 12 tests PASS

**Step 5: Commit**

```bash
git add skills/backtest_simulator.py tests/test_backtest_simulator.py
git commit -m "feat: add backtest simulator with parameter filtering and cost integration"
```

---

## Task 6: Parameter Optimizer

**Files:**
- Create: `skills/param_optimizer.py`
- Test: `tests/test_param_optimizer.py`

**Step 1: Write the failing test**

```python
# tests/test_param_optimizer.py
"""Tests for the parameter optimizer."""
from datetime import datetime

from schemas.events import TradeEvent
from schemas.wfo_config import (
    CostModelConfig,
    OptimizationConfig,
    OptimizationObjective,
    ParameterDef,
    ParameterSpace,
    RobustnessConfig,
)
from schemas.wfo_results import SimulationMetrics
from skills.backtest_simulator import BacktestSimulator
from skills.cost_model import CostModel
from skills.param_optimizer import ParamOptimizer


def _trade(trade_id: str, pnl: float, signal_strength: float = 0.8) -> TradeEvent:
    return TradeEvent(
        trade_id=trade_id,
        bot_id="bot1",
        pair="BTCUSDT",
        side="LONG",
        entry_time=datetime(2026, 1, 15, 12, 0),
        exit_time=datetime(2026, 1, 15, 14, 0),
        entry_price=40000.0,
        exit_price=40000.0 + pnl / 0.1,
        position_size=0.1,
        pnl=pnl,
        pnl_pct=pnl / 4000 * 100,
        entry_signal_strength=signal_strength,
    )


def _zero_cost_model() -> CostModel:
    return CostModel(CostModelConfig(fees_per_trade_bps=0.0, fixed_slippage_bps=0.0))


class TestGridGeneration:
    def test_generates_all_combinations(self):
        space = ParameterSpace(
            bot_id="bot1",
            parameters=[
                ParameterDef(name="a", min_value=1.0, max_value=3.0, step=1.0, current_value=2.0),
                ParameterDef(name="b", min_value=10.0, max_value=20.0, step=10.0, current_value=10.0),
            ],
        )
        opt = ParamOptimizer(space, OptimizationConfig())
        grid = opt.generate_grid()
        assert len(grid) == 6  # 3 × 2

    def test_single_param(self):
        space = ParameterSpace(
            bot_id="bot1",
            parameters=[
                ParameterDef(name="a", min_value=1.0, max_value=5.0, step=1.0, current_value=3.0),
            ],
        )
        opt = ParamOptimizer(space, OptimizationConfig())
        grid = opt.generate_grid()
        assert len(grid) == 5

    def test_empty_space(self):
        space = ParameterSpace(bot_id="bot1", parameters=[])
        opt = ParamOptimizer(space, OptimizationConfig())
        grid = opt.generate_grid()
        assert grid == [{}]


class TestOptimization:
    def test_selects_best_by_objective(self):
        space = ParameterSpace(
            bot_id="bot1",
            parameters=[
                ParameterDef(name="signal_strength_min", min_value=0.3, max_value=0.9, step=0.3, current_value=0.6),
            ],
        )
        trades = [
            _trade("t1", 100.0, signal_strength=0.9),
            _trade("t2", -50.0, signal_strength=0.3),
            _trade("t3", 200.0, signal_strength=0.6),
            _trade("t4", 80.0, signal_strength=0.7),
        ]
        sim = BacktestSimulator(_zero_cost_model())
        opt = ParamOptimizer(space, OptimizationConfig(objective=OptimizationObjective.SHARPE))
        best_params, best_metrics, all_results = opt.optimize(trades, [], sim)
        assert isinstance(best_params, dict)
        assert isinstance(best_metrics, SimulationMetrics)
        assert len(all_results) == 3  # signal_strength_min = 0.3, 0.6, 0.9

    def test_respects_max_drawdown_constraint(self):
        space = ParameterSpace(
            bot_id="bot1",
            parameters=[
                ParameterDef(name="signal_strength_min", min_value=0.3, max_value=0.9, step=0.3, current_value=0.6),
            ],
        )
        trades = [
            _trade("t1", 100.0, signal_strength=0.9),
            _trade("t2", -500.0, signal_strength=0.3),
            _trade("t3", 200.0, signal_strength=0.6),
        ]
        sim = BacktestSimulator(_zero_cost_model())
        opt = ParamOptimizer(
            space,
            OptimizationConfig(
                objective=OptimizationObjective.SHARPE,
                max_drawdown_constraint=0.10,
            ),
        )
        best_params, best_metrics, _ = opt.optimize(trades, [], sim)
        # The param set that includes the -500 trade should be filtered out
        assert best_metrics.max_drawdown_pct <= 0.10 or best_params.get("signal_strength_min", 0) > 0.3

    def test_respects_min_trades(self):
        space = ParameterSpace(
            bot_id="bot1",
            parameters=[
                ParameterDef(name="signal_strength_min", min_value=0.3, max_value=0.9, step=0.3, current_value=0.6),
            ],
        )
        trades = [_trade("t1", 100.0, signal_strength=0.9)]
        sim = BacktestSimulator(_zero_cost_model())
        opt = ParamOptimizer(space, OptimizationConfig(), min_trades=5)
        best_params, best_metrics, _ = opt.optimize(trades, [], sim)
        # No param set has >= 5 trades, so best_metrics should be empty
        assert best_metrics.total_trades == 0
```

**Step 2: Run test to verify it fails**

Run: `venv/Scripts/python -m pytest tests/test_param_optimizer.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'skills.param_optimizer'`

**Step 3: Write minimal implementation**

```python
# skills/param_optimizer.py
"""Parameter optimizer — grid search over parameter space with constraint filtering.

Evaluates every combination from the parameter space on in-sample trades,
ranks by the configured objective, and filters by constraints (max drawdown,
min trades per fold).
"""
from __future__ import annotations

import itertools

from schemas.events import TradeEvent, MissedOpportunityEvent
from schemas.wfo_config import OptimizationConfig, OptimizationObjective, ParameterSpace
from schemas.wfo_results import SimulationMetrics
from skills.backtest_simulator import BacktestSimulator


class ParamOptimizer:
    """Grid search optimizer over a parameter space."""

    def __init__(
        self,
        space: ParameterSpace,
        opt_config: OptimizationConfig,
        min_trades: int = 0,
    ) -> None:
        self._space = space
        self._opt = opt_config
        self._min_trades = min_trades

    def generate_grid(self) -> list[dict[str, float]]:
        """Generate all parameter combinations from the space."""
        if not self._space.parameters:
            return [{}]

        names = [p.name for p in self._space.parameters]
        grids = [p.grid_values for p in self._space.parameters]
        combos: list[dict[str, float]] = []
        for values in itertools.product(*grids):
            combos.append(dict(zip(names, values)))
        return combos

    def optimize(
        self,
        trades: list[TradeEvent],
        missed: list[MissedOpportunityEvent],
        simulator: BacktestSimulator,
        cost_multiplier: float = 1.0,
    ) -> tuple[dict[str, float], SimulationMetrics, list[tuple[dict[str, float], SimulationMetrics]]]:
        """Find the best parameter set by grid search.

        Returns: (best_params, best_metrics, all_results)
        """
        grid = self.generate_grid()
        all_results: list[tuple[dict[str, float], SimulationMetrics]] = []

        for params in grid:
            metrics = simulator.simulate(trades, missed, params, cost_multiplier=cost_multiplier)
            all_results.append((params, metrics))

        # Filter by constraints
        valid = [
            (p, m) for p, m in all_results
            if m.total_trades >= self._min_trades
            and m.max_drawdown_pct <= self._opt.max_drawdown_constraint
        ]

        if not valid:
            return {}, SimulationMetrics(), all_results

        # Rank by objective
        best_params, best_metrics = max(valid, key=lambda x: self._objective_value(x[1]))
        return best_params, best_metrics, all_results

    def _objective_value(self, metrics: SimulationMetrics) -> float:
        obj = self._opt.objective
        if obj == OptimizationObjective.SHARPE:
            return metrics.sharpe_ratio
        elif obj == OptimizationObjective.SORTINO:
            return metrics.sortino_ratio
        elif obj == OptimizationObjective.CALMAR:
            return metrics.calmar_ratio
        elif obj == OptimizationObjective.PROFIT_FACTOR:
            return metrics.profit_factor
        return 0.0
```

**Step 4: Run test to verify it passes**

Run: `venv/Scripts/python -m pytest tests/test_param_optimizer.py -v`
Expected: All 6 tests PASS

**Step 5: Commit**

```bash
git add skills/param_optimizer.py tests/test_param_optimizer.py
git commit -m "feat: add parameter optimizer with grid search and constraint filtering"
```

---

## Task 7: Robustness Tester

**Files:**
- Create: `skills/robustness_tester.py`
- Test: `tests/test_robustness_tester.py`

**Step 1: Write the failing test**

```python
# tests/test_robustness_tester.py
"""Tests for the robustness tester."""
from datetime import datetime

from schemas.events import TradeEvent
from schemas.wfo_config import CostModelConfig, RobustnessConfig, ParameterDef, ParameterSpace
from schemas.wfo_results import RobustnessResult, SafetyFlag, SimulationMetrics
from skills.backtest_simulator import BacktestSimulator
from skills.cost_model import CostModel
from skills.robustness_tester import RobustnessTester


def _trade(trade_id: str, pnl: float, regime: str = "trending_up", signal_strength: float = 0.8) -> TradeEvent:
    return TradeEvent(
        trade_id=trade_id,
        bot_id="bot1",
        pair="BTCUSDT",
        side="LONG",
        entry_time=datetime(2026, 1, 15, 12, 0),
        exit_time=datetime(2026, 1, 15, 14, 0),
        entry_price=40000.0,
        exit_price=40000.0 + pnl / 0.1,
        position_size=0.1,
        pnl=pnl,
        pnl_pct=pnl / 4000 * 100,
        market_regime=regime,
        entry_signal_strength=signal_strength,
    )


def _zero_cost_model() -> CostModel:
    return CostModel(CostModelConfig(fees_per_trade_bps=0.0, fixed_slippage_bps=0.0))


class TestNeighborhoodStability:
    def test_stable_neighborhood(self):
        cfg = RobustnessConfig(neighborhood_pct=0.1)
        space = ParameterSpace(
            bot_id="bot1",
            parameters=[
                ParameterDef(name="signal_strength_min", min_value=0.1, max_value=0.9, step=0.1, current_value=0.5),
            ],
        )
        trades = [
            _trade("t1", 100.0, signal_strength=0.9),
            _trade("t2", 80.0, signal_strength=0.8),
            _trade("t3", 60.0, signal_strength=0.7),
            _trade("t4", 40.0, signal_strength=0.6),
            _trade("t5", 20.0, signal_strength=0.5),
        ]
        sim = BacktestSimulator(_zero_cost_model())
        tester = RobustnessTester(cfg, space, sim)
        best_params = {"signal_strength_min": 0.5}
        result = tester.test_neighborhood(trades, [], best_params)
        assert isinstance(result, dict)
        # Neighborhood params should all be tested
        assert len(result) >= 1

    def test_detects_unstable_neighborhood(self):
        cfg = RobustnessConfig(neighborhood_pct=0.5)  # large neighborhood
        space = ParameterSpace(
            bot_id="bot1",
            parameters=[
                ParameterDef(name="signal_strength_min", min_value=0.1, max_value=0.9, step=0.1, current_value=0.5),
            ],
        )
        trades = [
            _trade("t1", 100.0, signal_strength=0.51),  # only passes at exactly 0.5
            _trade("t2", -1000.0, signal_strength=0.2),
        ]
        sim = BacktestSimulator(_zero_cost_model())
        tester = RobustnessTester(cfg, space, sim)
        best_params = {"signal_strength_min": 0.5}
        scores = tester.test_neighborhood(trades, [], best_params)
        # Wide neighborhood should show degradation at 0.25 (includes the -1000 trade)
        assert any(v < 0 for v in scores.values())


class TestRegimeStability:
    def test_stable_across_regimes(self):
        cfg = RobustnessConfig(min_profitable_regimes=3, total_regime_types=4)
        trades = [
            _trade("t1", 100.0, regime="trending_up"),
            _trade("t2", 80.0, regime="trending_down"),
            _trade("t3", 60.0, regime="ranging"),
            _trade("t4", 40.0, regime="volatile"),
        ]
        sim = BacktestSimulator(_zero_cost_model())
        space = ParameterSpace(bot_id="bot1", parameters=[])
        tester = RobustnessTester(cfg, space, sim)
        regime_pnl, count = tester.test_regime_stability(trades, [], {})
        assert count >= 3
        assert all(v > 0 for v in regime_pnl.values())

    def test_unstable_in_some_regimes(self):
        cfg = RobustnessConfig(min_profitable_regimes=3, total_regime_types=4)
        trades = [
            _trade("t1", 100.0, regime="trending_up"),
            _trade("t2", -200.0, regime="ranging"),
            _trade("t3", -150.0, regime="volatile"),
        ]
        sim = BacktestSimulator(_zero_cost_model())
        space = ParameterSpace(bot_id="bot1", parameters=[])
        tester = RobustnessTester(cfg, space, sim)
        regime_pnl, count = tester.test_regime_stability(trades, [], {})
        assert count < 3


class TestFullRobustnessEvaluation:
    def test_produces_result(self):
        cfg = RobustnessConfig()
        space = ParameterSpace(
            bot_id="bot1",
            parameters=[
                ParameterDef(name="signal_strength_min", min_value=0.3, max_value=0.7, step=0.1, current_value=0.5),
            ],
        )
        trades = [
            _trade("t1", 100.0, regime="trending_up", signal_strength=0.9),
            _trade("t2", 80.0, regime="trending_down", signal_strength=0.8),
            _trade("t3", 60.0, regime="ranging", signal_strength=0.7),
            _trade("t4", 40.0, regime="volatile", signal_strength=0.6),
        ]
        sim = BacktestSimulator(_zero_cost_model())
        tester = RobustnessTester(cfg, space, sim)
        result = tester.evaluate(trades, [], {"signal_strength_min": 0.5})
        assert isinstance(result, RobustnessResult)
        assert 0 <= result.robustness_score <= 100


class TestSafetyFlags:
    def test_flat_surface_flag(self):
        cfg = RobustnessConfig()
        space = ParameterSpace(bot_id="bot1", parameters=[])
        sim = BacktestSimulator(_zero_cost_model())
        tester = RobustnessTester(cfg, space, sim)
        # All neighborhood scores identical → flat surface
        scores = {"a=1": 1.0, "a=2": 1.0, "a=3": 1.0}
        flags = tester.detect_safety_flags(scores, regime_stable=True, best_sharpe=1.0)
        flag_types = [f.flag_type for f in flags]
        assert "low_conviction" in flag_types

    def test_spiky_surface_flag(self):
        cfg = RobustnessConfig()
        space = ParameterSpace(bot_id="bot1", parameters=[])
        sim = BacktestSimulator(_zero_cost_model())
        tester = RobustnessTester(cfg, space, sim)
        # Best is 3.0 but neighbors drop by >50%
        scores = {"a=1": 0.5, "a=2": 3.0, "a=3": 0.8}
        flags = tester.detect_safety_flags(scores, regime_stable=True, best_sharpe=3.0)
        flag_types = [f.flag_type for f in flags]
        assert "likely_overfit" in flag_types

    def test_no_flags_for_healthy_surface(self):
        cfg = RobustnessConfig()
        space = ParameterSpace(bot_id="bot1", parameters=[])
        sim = BacktestSimulator(_zero_cost_model())
        tester = RobustnessTester(cfg, space, sim)
        scores = {"a=1": 1.6, "a=2": 2.0, "a=3": 1.8}
        flags = tester.detect_safety_flags(scores, regime_stable=True, best_sharpe=2.0)
        flag_types = [f.flag_type for f in flags]
        assert "likely_overfit" not in flag_types
        assert "low_conviction" not in flag_types
```

**Step 2: Run test to verify it fails**

Run: `venv/Scripts/python -m pytest tests/test_robustness_tester.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'skills.robustness_tester'`

**Step 3: Write minimal implementation**

```python
# skills/robustness_tester.py
"""Robustness tester — neighborhood stability, regime stability, and safety flags.

From roadmap §4.4:
- Neighborhood test: test params ±10%, ensure performance doesn't collapse
- Regime stability: profitable in at least 3 of 4 regime types
- Safety flags: flat surface → low conviction, spiky → likely overfit, fragile at higher costs
"""
from __future__ import annotations

import statistics
from collections import defaultdict

from schemas.events import TradeEvent, MissedOpportunityEvent
from schemas.wfo_config import RobustnessConfig, ParameterSpace
from schemas.wfo_results import RobustnessResult, SafetyFlag
from skills.backtest_simulator import BacktestSimulator


class RobustnessTester:
    """Tests parameter robustness via neighborhood and regime analysis."""

    def __init__(
        self,
        config: RobustnessConfig,
        space: ParameterSpace,
        simulator: BacktestSimulator,
    ) -> None:
        self._config = config
        self._space = space
        self._sim = simulator

    def test_neighborhood(
        self,
        trades: list[TradeEvent],
        missed: list[MissedOpportunityEvent],
        best_params: dict[str, float],
    ) -> dict[str, float]:
        """Test Sharpe at ±neighborhood_pct around best params. Returns label→Sharpe map."""
        scores: dict[str, float] = {}
        pct = self._config.neighborhood_pct

        for pdef in self._space.parameters:
            name = pdef.name
            best_val = best_params.get(name, pdef.current_value)
            for direction in [-1, 0, 1]:
                adjusted = best_val * (1 + direction * pct)
                adjusted = max(pdef.min_value, min(pdef.max_value, adjusted))
                neighbor = dict(best_params)
                neighbor[name] = adjusted
                label = f"{name}={adjusted:.4g}"
                result = self._sim.simulate(trades, missed, neighbor)
                scores[label] = result.sharpe_ratio

        return scores

    def test_regime_stability(
        self,
        trades: list[TradeEvent],
        missed: list[MissedOpportunityEvent],
        params: dict[str, float],
    ) -> tuple[dict[str, float], int]:
        """Test PnL by regime. Returns (regime_pnl, profitable_regime_count)."""
        result = self._sim.simulate(trades, missed, params)
        regime_pnl = result.pnl_by_regime
        profitable = sum(1 for v in regime_pnl.values() if v > 0)
        return regime_pnl, profitable

    def evaluate(
        self,
        trades: list[TradeEvent],
        missed: list[MissedOpportunityEvent],
        best_params: dict[str, float],
    ) -> RobustnessResult:
        """Full robustness evaluation: neighborhood + regime + score."""
        neighborhood = self.test_neighborhood(trades, missed, best_params)
        regime_pnl, profitable_count = self.test_regime_stability(trades, missed, best_params)

        best_sharpe_result = self._sim.simulate(trades, missed, best_params)
        best_sharpe = best_sharpe_result.sharpe_ratio

        neighborhood_stable = self._is_neighborhood_stable(neighborhood, best_sharpe)
        regime_stable = profitable_count >= self._config.min_profitable_regimes

        # Score: 50 points for neighborhood stability, 50 for regime stability
        score = 0.0
        if neighborhood_stable:
            score += 50.0
        elif neighborhood:
            avg_neighbor = statistics.mean(neighborhood.values()) if neighborhood else 0
            score += max(0, 50 * (avg_neighbor / best_sharpe)) if best_sharpe > 0 else 0

        regime_ratio = profitable_count / self._config.total_regime_types if self._config.total_regime_types > 0 else 0
        score += 50 * regime_ratio

        flags = self.detect_safety_flags(neighborhood, regime_stable, best_sharpe)

        return RobustnessResult(
            neighborhood_scores=neighborhood,
            neighborhood_stable=neighborhood_stable,
            regime_pnl=regime_pnl,
            profitable_regime_count=profitable_count,
            regime_stable=regime_stable,
            robustness_score=min(100, max(0, score)),
        )

    def _is_neighborhood_stable(self, scores: dict[str, float], best_sharpe: float) -> bool:
        """Neighborhood is stable if no neighbor drops by more than 50% from best."""
        if not scores or best_sharpe <= 0:
            return False
        return all(v >= best_sharpe * 0.5 for v in scores.values())

    def detect_safety_flags(
        self,
        neighborhood_scores: dict[str, float],
        regime_stable: bool,
        best_sharpe: float,
    ) -> list[SafetyFlag]:
        """Detect safety flags from robustness test results."""
        flags: list[SafetyFlag] = []
        if not neighborhood_scores:
            return flags

        values = list(neighborhood_scores.values())

        # Flat surface: all scores within 5% of each other → low conviction
        if len(values) >= 2:
            spread = max(values) - min(values)
            mean_val = statistics.mean(values)
            if mean_val > 0 and spread / mean_val < 0.05:
                flags.append(SafetyFlag(
                    flag_type="low_conviction",
                    description="Flat optimization surface: all neighbors within 5% — parameter choice has little impact",
                    severity="high",
                ))

        # Spiky surface: any neighbor drops >50% from best → likely overfit
        if best_sharpe > 0:
            worst_neighbor = min(values)
            if worst_neighbor < best_sharpe * 0.5:
                flags.append(SafetyFlag(
                    flag_type="likely_overfit",
                    description=f"Spiky optimization surface: ±{self._config.neighborhood_pct:.0%} params reduce Sharpe by >{50}%",
                    severity="high",
                ))

        if not regime_stable:
            flags.append(SafetyFlag(
                flag_type="regime_unstable",
                description=f"Not profitable in {self._config.min_profitable_regimes}/{self._config.total_regime_types} regimes",
                severity="medium",
            ))

        return flags
```

**Step 4: Run test to verify it passes**

Run: `venv/Scripts/python -m pytest tests/test_robustness_tester.py -v`
Expected: All 10 tests PASS

**Step 5: Commit**

```bash
git add skills/robustness_tester.py tests/test_robustness_tester.py
git commit -m "feat: add robustness tester with neighborhood stability, regime checks, and safety flags"
```

---

## Task 8: WFO Runner (Main Pipeline)

**Files:**
- Create: `skills/run_wfo.py`
- Test: `tests/test_wfo_runner.py`

This is the orchestrating skill that ties fold generation, optimization, backtest, robustness, leakage, and cost sensitivity together into one pipeline.

**Step 1: Write the failing test**

```python
# tests/test_wfo_runner.py
"""Tests for the main WFO runner pipeline."""
import json
from datetime import datetime
from pathlib import Path

from schemas.events import TradeEvent, MissedOpportunityEvent
from schemas.wfo_config import (
    WFOConfig,
    WFOMethod,
    ParameterDef,
    ParameterSpace,
    CostModelConfig,
    OptimizationConfig,
    OptimizationObjective,
    RobustnessConfig,
)
from schemas.wfo_results import WFOReport, WFORecommendation
from skills.run_wfo import WFORunner


def _trade(
    trade_id: str,
    pnl: float,
    date: str = "2025-08-15",
    signal_strength: float = 0.8,
    regime: str = "trending_up",
) -> TradeEvent:
    dt = datetime.strptime(date, "%Y-%m-%d")
    return TradeEvent(
        trade_id=trade_id,
        bot_id="bot1",
        pair="BTCUSDT",
        side="LONG",
        entry_time=dt,
        exit_time=dt,
        entry_price=40000.0,
        exit_price=40000.0 + pnl / 0.1,
        position_size=0.1,
        pnl=pnl,
        pnl_pct=pnl / 4000 * 100,
        entry_signal_strength=signal_strength,
        market_regime=regime,
    )


def _make_config(min_folds: int = 1, is_days: int = 60, oos_days: int = 30) -> WFOConfig:
    return WFOConfig(
        bot_id="bot1",
        method=WFOMethod.ANCHORED,
        in_sample_days=is_days,
        out_of_sample_days=oos_days,
        step_days=30,
        min_folds=min_folds,
        parameter_space=ParameterSpace(
            bot_id="bot1",
            parameters=[
                ParameterDef(name="signal_strength_min", min_value=0.3, max_value=0.9, step=0.3, current_value=0.6),
            ],
        ),
        optimization=OptimizationConfig(
            objective=OptimizationObjective.SHARPE,
            max_drawdown_constraint=0.50,
        ),
        cost_model=CostModelConfig(fees_per_trade_bps=0.0, fixed_slippage_bps=0.0),
        robustness=RobustnessConfig(
            min_trades_per_fold=1,
            min_profitable_regimes=1,
            total_regime_types=4,
        ),
    )


def _generate_trades(count: int = 50) -> list[TradeEvent]:
    """Generate trades spread across 365 days with varied regimes."""
    import random

    random.seed(42)
    regimes = ["trending_up", "trending_down", "ranging", "volatile"]
    trades = []
    for i in range(count):
        day_offset = int(i * 365 / count)
        dt = datetime(2025, 1, 1) + __import__("datetime").timedelta(days=day_offset)
        pnl = random.uniform(-100, 200)
        trades.append(TradeEvent(
            trade_id=f"t{i}",
            bot_id="bot1",
            pair="BTCUSDT",
            side="LONG",
            entry_time=dt,
            exit_time=dt,
            entry_price=40000.0,
            exit_price=40000.0 + pnl / 0.1,
            position_size=0.1,
            pnl=pnl,
            pnl_pct=pnl / 4000 * 100,
            entry_signal_strength=random.uniform(0.2, 1.0),
            market_regime=regimes[i % len(regimes)],
        ))
    return trades


class TestWFORunnerExecutes:
    def test_produces_report(self):
        cfg = _make_config(min_folds=1, is_days=60, oos_days=30)
        trades = _generate_trades(50)
        runner = WFORunner(cfg)
        report = runner.run(
            trades=trades,
            missed=[],
            data_start="2025-01-01",
            data_end="2026-01-01",
        )
        assert isinstance(report, WFOReport)
        assert report.bot_id == "bot1"
        assert len(report.fold_results) >= 1
        assert report.recommendation in [
            WFORecommendation.ADOPT,
            WFORecommendation.TEST_FURTHER,
            WFORecommendation.REJECT,
        ]

    def test_includes_cost_sensitivity(self):
        cfg = _make_config(min_folds=1)
        cfg.cost_model = CostModelConfig(
            fees_per_trade_bps=7.0,
            fixed_slippage_bps=5.0,
            cost_multipliers=[1.0, 1.5, 2.0],
        )
        trades = _generate_trades(50)
        runner = WFORunner(cfg)
        report = runner.run(trades=trades, missed=[], data_start="2025-01-01", data_end="2026-01-01")
        assert len(report.cost_sensitivity) == 3

    def test_includes_robustness(self):
        cfg = _make_config(min_folds=1)
        trades = _generate_trades(50)
        runner = WFORunner(cfg)
        report = runner.run(trades=trades, missed=[], data_start="2025-01-01", data_end="2026-01-01")
        assert 0 <= report.robustness.robustness_score <= 100

    def test_returns_reject_on_insufficient_data(self):
        cfg = _make_config(min_folds=100)  # impossible to achieve
        trades = _generate_trades(10)
        runner = WFORunner(cfg)
        report = runner.run(trades=trades, missed=[], data_start="2025-01-01", data_end="2025-06-01")
        assert report.recommendation == WFORecommendation.REJECT
        assert "insufficient" in report.recommendation_reasoning.lower()


class TestWFORunnerOutputs:
    def test_writes_report_json(self, tmp_path: Path):
        cfg = _make_config(min_folds=1)
        trades = _generate_trades(50)
        runner = WFORunner(cfg)
        report = runner.run(trades=trades, missed=[], data_start="2025-01-01", data_end="2026-01-01")
        runner.write_output(report, tmp_path)
        assert (tmp_path / "wfo_report.json").exists()
        data = json.loads((tmp_path / "wfo_report.json").read_text())
        assert data["bot_id"] == "bot1"
        assert "recommendation" in data

    def test_cost_sensitivity_flag(self):
        cfg = _make_config(min_folds=1)
        cfg.cost_model = CostModelConfig(
            fees_per_trade_bps=100.0,  # absurdly high fees
            fixed_slippage_bps=100.0,
            cost_multipliers=[1.0, 1.5, 2.0],
            reject_if_only_profitable_at_zero_cost=True,
        )
        trades = _generate_trades(50)
        runner = WFORunner(cfg)
        report = runner.run(trades=trades, missed=[], data_start="2025-01-01", data_end="2026-01-01")
        flag_types = [f.flag_type for f in report.safety_flags]
        # With absurd costs, should flag as fragile or reject
        assert "fragile" in flag_types or report.recommendation == WFORecommendation.REJECT
```

**Step 2: Run test to verify it fails**

Run: `venv/Scripts/python -m pytest tests/test_wfo_runner.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'skills.run_wfo'`

**Step 3: Write minimal implementation**

```python
# skills/run_wfo.py
"""WFO runner — main walk-forward optimization pipeline.

Orchestrates: fold generation → per-fold optimization + OOS validation →
aggregate metrics → robustness testing → cost sensitivity → leakage audit →
recommendation + safety flags → JSON output.

Usage: WFORunner(config).run(trades, missed, data_start, data_end)
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from schemas.events import TradeEvent, MissedOpportunityEvent
from schemas.wfo_config import WFOConfig
from schemas.wfo_results import (
    CostSensitivityResult,
    FoldResult,
    RobustnessResult,
    SafetyFlag,
    SimulationMetrics,
    WFORecommendation,
    WFOReport,
)
from skills.backtest_simulator import BacktestSimulator
from skills.cost_model import CostModel
from skills.fold_generator import FoldGenerator
from skills.param_optimizer import ParamOptimizer
from skills.robustness_tester import RobustnessTester

logger = logging.getLogger(__name__)


class WFORunner:
    """Runs the full walk-forward optimization pipeline."""

    def __init__(self, config: WFOConfig) -> None:
        self._config = config

    def run(
        self,
        trades: list[TradeEvent],
        missed: list[MissedOpportunityEvent],
        data_start: str,
        data_end: str,
    ) -> WFOReport:
        """Execute the WFO pipeline and return a complete report."""
        # 1. Generate folds
        fold_gen = FoldGenerator(self._config)
        folds = fold_gen.generate(data_start, data_end)

        if not folds:
            return WFOReport(
                bot_id=self._config.bot_id,
                config_summary=self._config_summary(),
                current_params=self._config.parameter_space.current_params,
                suggested_params=self._config.parameter_space.current_params,
                recommendation=WFORecommendation.REJECT,
                recommendation_reasoning="Insufficient data to generate required number of folds.",
            )

        # 2. Run per-fold optimization
        cost_model = CostModel(self._config.cost_model)
        simulator = BacktestSimulator(cost_model)
        fold_results = self._run_folds(folds, trades, missed, simulator)

        # 3. Determine best params from consensus across folds
        suggested_params = self._consensus_params(fold_results)

        # 4. Aggregate OOS metrics
        all_oos_trades = self._filter_trades_in_oos(trades, folds)
        aggregate_oos = simulator.simulate(all_oos_trades, missed, suggested_params)

        # 5. Cost sensitivity
        cost_sensitivity = self._run_cost_sensitivity(trades, missed, suggested_params)

        # 6. Robustness testing
        robustness_tester = RobustnessTester(
            self._config.robustness, self._config.parameter_space, simulator
        )
        robustness = robustness_tester.evaluate(trades, missed, suggested_params)

        # 7. Safety flags
        safety_flags = list(robustness_tester.detect_safety_flags(
            robustness.neighborhood_scores,
            robustness.regime_stable,
            aggregate_oos.sharpe_ratio,
        ))
        safety_flags.extend(self._cost_safety_flags(cost_sensitivity))

        # 8. Recommendation
        recommendation, reasoning = self._determine_recommendation(
            aggregate_oos, robustness, safety_flags, fold_results
        )

        return WFOReport(
            bot_id=self._config.bot_id,
            config_summary=self._config_summary(),
            current_params=self._config.parameter_space.current_params,
            suggested_params=suggested_params,
            fold_results=fold_results,
            aggregate_oos_metrics=aggregate_oos,
            cost_sensitivity=cost_sensitivity,
            robustness=robustness,
            safety_flags=safety_flags,
            recommendation=recommendation,
            recommendation_reasoning=reasoning,
        )

    def write_output(self, report: WFOReport, output_dir: Path) -> None:
        """Write the WFO report JSON to output_dir."""
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / "wfo_report.json"
        path.write_text(json.dumps(report.model_dump(mode="json"), indent=2, default=str))

    def _run_folds(
        self, folds, trades, missed, simulator
    ) -> list[FoldResult]:
        results: list[FoldResult] = []
        for fold in folds:
            is_trades = self._filter_by_period(trades, fold.is_start, fold.is_end)
            is_missed = self._filter_missed_by_period(missed, fold.is_start, fold.is_end)
            oos_trades = self._filter_by_period(trades, fold.oos_start, fold.oos_end)
            oos_missed = self._filter_missed_by_period(missed, fold.oos_start, fold.oos_end)

            optimizer = ParamOptimizer(
                self._config.parameter_space,
                self._config.optimization,
                min_trades=self._config.robustness.min_trades_per_fold,
            )
            best_params, is_metrics, _ = optimizer.optimize(is_trades, is_missed, simulator)

            if not best_params:
                continue

            oos_metrics = simulator.simulate(oos_trades, oos_missed, best_params)
            results.append(FoldResult(
                fold=fold,
                best_params=best_params,
                is_metrics=is_metrics,
                oos_metrics=oos_metrics,
            ))

        return results

    def _consensus_params(self, fold_results: list[FoldResult]) -> dict[str, float]:
        """Take the most common best param values across folds (mode for each param)."""
        if not fold_results:
            return self._config.parameter_space.current_params

        from collections import Counter

        param_votes: dict[str, list[float]] = {}
        for fr in fold_results:
            for name, val in fr.best_params.items():
                param_votes.setdefault(name, []).append(val)

        consensus: dict[str, float] = {}
        for name, vals in param_votes.items():
            counter = Counter(vals)
            consensus[name] = counter.most_common(1)[0][0]
        return consensus

    def _run_cost_sensitivity(
        self,
        trades: list[TradeEvent],
        missed: list[MissedOpportunityEvent],
        params: dict[str, float],
    ) -> list[CostSensitivityResult]:
        if not self._config.cost_model.cost_sensitivity_test:
            return []

        results: list[CostSensitivityResult] = []
        cost_model = CostModel(self._config.cost_model)
        simulator = BacktestSimulator(cost_model)

        for mult in self._config.cost_model.cost_multipliers:
            metrics = simulator.simulate(trades, missed, params, cost_multiplier=mult)
            results.append(CostSensitivityResult(cost_multiplier=mult, metrics=metrics))

        return results

    def _cost_safety_flags(self, sensitivity: list[CostSensitivityResult]) -> list[SafetyFlag]:
        flags: list[SafetyFlag] = []
        if not sensitivity:
            return flags

        base = next((s for s in sensitivity if s.cost_multiplier == 1.0), None)
        elevated = [s for s in sensitivity if s.cost_multiplier > 1.0]

        if base and base.metrics.net_pnl <= 0 and self._config.cost_model.reject_if_only_profitable_at_zero_cost:
            flags.append(SafetyFlag(
                flag_type="fragile",
                description="Not profitable at base cost assumptions",
                severity="high",
            ))

        for s in elevated:
            if base and base.metrics.sharpe_ratio > 0 and s.metrics.sharpe_ratio < 1.0:
                flags.append(SafetyFlag(
                    flag_type="fragile",
                    description=f"At {s.cost_multiplier}x costs, Sharpe drops to {s.metrics.sharpe_ratio:.2f}",
                    severity="medium",
                ))
                break  # one flag is enough

        return flags

    def _determine_recommendation(
        self,
        oos_metrics: SimulationMetrics,
        robustness: RobustnessResult,
        safety_flags: list[SafetyFlag],
        fold_results: list[FoldResult],
    ) -> tuple[WFORecommendation, str]:
        high_severity_flags = [f for f in safety_flags if f.severity == "high"]

        if not fold_results:
            return WFORecommendation.REJECT, "No valid fold results produced."

        if high_severity_flags:
            reasons = "; ".join(f.description for f in high_severity_flags)
            return WFORecommendation.REJECT, f"High-severity safety flags: {reasons}"

        if oos_metrics.sharpe_ratio <= 0:
            return WFORecommendation.REJECT, f"OOS Sharpe ratio is {oos_metrics.sharpe_ratio:.2f} (not profitable)."

        if robustness.robustness_score >= 70 and oos_metrics.sharpe_ratio >= 1.0:
            return (
                WFORecommendation.ADOPT,
                f"OOS Sharpe {oos_metrics.sharpe_ratio:.2f}, robustness {robustness.robustness_score:.0f}/100.",
            )

        return (
            WFORecommendation.TEST_FURTHER,
            f"OOS Sharpe {oos_metrics.sharpe_ratio:.2f}, robustness {robustness.robustness_score:.0f}/100. Needs more validation.",
        )

    def _filter_by_period(self, trades: list[TradeEvent], start: str, end: str) -> list[TradeEvent]:
        s = datetime.strptime(start, "%Y-%m-%d")
        e = datetime.strptime(end, "%Y-%m-%d")
        return [t for t in trades if s <= t.entry_time < e]

    def _filter_missed_by_period(
        self, missed: list[MissedOpportunityEvent], start: str, end: str
    ) -> list[MissedOpportunityEvent]:
        # MissedOpportunityEvent doesn't have a direct timestamp — filter by metadata if available
        return missed  # Include all missed for now; per-fold filtering is optional

    def _filter_trades_in_oos(self, trades, folds) -> list[TradeEvent]:
        """Collect trades that fall in any OOS period."""
        result: list[TradeEvent] = []
        for fold in folds:
            result.extend(self._filter_by_period(trades, fold.oos_start, fold.oos_end))
        return result

    def _config_summary(self) -> dict:
        return {
            "method": self._config.method.value,
            "in_sample_days": self._config.in_sample_days,
            "out_of_sample_days": self._config.out_of_sample_days,
            "step_days": self._config.step_days,
            "objective": self._config.optimization.objective.value,
            "total_parameter_combinations": self._config.parameter_space.total_combinations,
        }
```

**Step 4: Run test to verify it passes**

Run: `venv/Scripts/python -m pytest tests/test_wfo_runner.py -v`
Expected: All 6 tests PASS

**Step 5: Commit**

```bash
git add skills/run_wfo.py tests/test_wfo_runner.py
git commit -m "feat: add WFO runner pipeline orchestrating folds, optimization, robustness, and cost sensitivity"
```

---

## Task 9: WFO Report Builder + Prompt Assembler

**Files:**
- Create: `analysis/wfo_report_builder.py`
- Create: `analysis/wfo_prompt_assembler.py`
- Test: `tests/test_wfo_report_builder.py`
- Test: `tests/test_wfo_prompt_assembler.py`

**Step 1: Write the failing tests**

```python
# tests/test_wfo_report_builder.py
"""Tests for the WFO report builder — markdown generation."""
from schemas.wfo_results import (
    FoldDefinition,
    FoldResult,
    SimulationMetrics,
    CostSensitivityResult,
    RobustnessResult,
    SafetyFlag,
    WFORecommendation,
    WFOReport,
)
from analysis.wfo_report_builder import WFOReportBuilder


def _sample_report() -> WFOReport:
    fold = FoldDefinition(
        fold_number=0,
        is_start="2025-07-01", is_end="2025-12-28",
        oos_start="2025-12-28", oos_end="2026-01-27",
    )
    return WFOReport(
        bot_id="bot2",
        config_summary={"method": "anchored", "in_sample_days": 180},
        current_params={"rsi": 30.0, "stop_atr": 1.5},
        suggested_params={"rsi": 35.0, "stop_atr": 2.0},
        fold_results=[
            FoldResult(
                fold=fold,
                best_params={"rsi": 35.0, "stop_atr": 2.0},
                is_metrics=SimulationMetrics(sharpe_ratio=2.0, net_pnl=5000.0, total_trades=100),
                oos_metrics=SimulationMetrics(sharpe_ratio=1.5, net_pnl=800.0, total_trades=25),
            ),
        ],
        aggregate_oos_metrics=SimulationMetrics(sharpe_ratio=1.5, net_pnl=800.0, max_drawdown_pct=0.08),
        cost_sensitivity=[
            CostSensitivityResult(cost_multiplier=1.0, metrics=SimulationMetrics(sharpe_ratio=1.5)),
            CostSensitivityResult(cost_multiplier=1.5, metrics=SimulationMetrics(sharpe_ratio=1.1)),
            CostSensitivityResult(cost_multiplier=2.0, metrics=SimulationMetrics(sharpe_ratio=0.7)),
        ],
        robustness=RobustnessResult(
            robustness_score=82.0,
            neighborhood_stable=True,
            regime_stable=True,
            profitable_regime_count=3,
        ),
        safety_flags=[
            SafetyFlag(flag_type="fragile", description="At 2x costs, Sharpe drops to 0.70", severity="medium"),
        ],
        recommendation=WFORecommendation.ADOPT,
        recommendation_reasoning="OOS Sharpe 1.5, robustness 82/100.",
    )


class TestReportBuilder:
    def test_generates_markdown(self):
        report = _sample_report()
        builder = WFOReportBuilder()
        md = builder.build_markdown(report)
        assert isinstance(md, str)
        assert "bot2" in md
        assert "ADOPT" in md.upper()

    def test_contains_param_comparison(self):
        report = _sample_report()
        builder = WFOReportBuilder()
        md = builder.build_markdown(report)
        assert "rsi" in md
        assert "30" in md  # current
        assert "35" in md  # suggested

    def test_contains_cost_sensitivity(self):
        report = _sample_report()
        builder = WFOReportBuilder()
        md = builder.build_markdown(report)
        assert "1.5x" in md or "1.5×" in md
        assert "2.0x" in md or "2.0×" in md

    def test_contains_safety_flags(self):
        report = _sample_report()
        builder = WFOReportBuilder()
        md = builder.build_markdown(report)
        assert "fragile" in md.lower()

    def test_contains_what_could_go_wrong(self):
        report = _sample_report()
        builder = WFOReportBuilder()
        md = builder.build_markdown(report)
        assert "could go wrong" in md.lower() or "risk" in md.lower()

    def test_empty_report(self):
        report = WFOReport(
            bot_id="bot1",
            config_summary={},
            recommendation=WFORecommendation.REJECT,
            recommendation_reasoning="No data.",
        )
        builder = WFOReportBuilder()
        md = builder.build_markdown(report)
        assert "REJECT" in md.upper()
```

```python
# tests/test_wfo_prompt_assembler.py
"""Tests for the WFO prompt assembler."""
import json
from pathlib import Path

from analysis.wfo_prompt_assembler import WFOPromptAssembler


class TestWFOPromptAssembler:
    def test_assembles_package(self, tmp_path: Path):
        # Set up memory dir
        policy_dir = tmp_path / "memory" / "policies" / "v1"
        policy_dir.mkdir(parents=True)
        (policy_dir / "agents.md").write_text("You are the WFO analyst.")
        (policy_dir / "trading_rules.md").write_text("Max 15% drawdown.")
        (policy_dir / "soul.md").write_text("Conservative risk tolerance.")

        # Set up WFO report
        wfo_dir = tmp_path / "runs" / "wfo" / "bot2"
        wfo_dir.mkdir(parents=True)
        report = {"bot_id": "bot2", "recommendation": "adopt", "suggested_params": {"rsi": 35}}
        (wfo_dir / "wfo_report.json").write_text(json.dumps(report))

        assembler = WFOPromptAssembler(
            bot_id="bot2",
            memory_dir=tmp_path / "memory",
            wfo_output_dir=wfo_dir,
        )
        package = assembler.assemble()
        assert "system_prompt" in package
        assert "task_prompt" in package
        assert "data" in package
        assert "instructions" in package
        assert package["data"]["wfo_report"]["bot_id"] == "bot2"

    def test_handles_missing_files_gracefully(self, tmp_path: Path):
        assembler = WFOPromptAssembler(
            bot_id="bot1",
            memory_dir=tmp_path / "memory",
            wfo_output_dir=tmp_path / "nonexistent",
        )
        package = assembler.assemble()
        assert "system_prompt" in package
        assert package["data"] == {}

    def test_includes_wfo_skill_context(self, tmp_path: Path):
        skill_dir = tmp_path / "memory" / "skills"
        skill_dir.mkdir(parents=True)
        (skill_dir / "wfo_pipeline.md").write_text("WFO pipeline instructions here.")

        assembler = WFOPromptAssembler(
            bot_id="bot1",
            memory_dir=tmp_path / "memory",
            wfo_output_dir=tmp_path / "runs",
        )
        package = assembler.assemble()
        assert "wfo_pipeline" in package.get("skill_context", "")
```

**Step 2: Run tests to verify they fail**

Run: `venv/Scripts/python -m pytest tests/test_wfo_report_builder.py tests/test_wfo_prompt_assembler.py -v`
Expected: FAIL with `ModuleNotFoundError`

**Step 3: Write minimal implementations**

```python
# analysis/wfo_report_builder.py
"""WFO report builder — generates human-readable markdown from WFO results.

Produces a structured report with:
- Parameter comparison (current vs suggested)
- Fold-by-fold OOS performance
- Cost sensitivity table
- Robustness score and regime breakdown
- Safety flags and "what could go wrong"
- Final recommendation (ADOPT / TEST_FURTHER / REJECT)
"""
from __future__ import annotations

from schemas.wfo_results import WFOReport, SafetyFlag


class WFOReportBuilder:
    """Generates markdown reports from WFOReport data."""

    def build_markdown(self, report: WFOReport) -> str:
        """Build a complete markdown report."""
        sections: list[str] = []
        sections.append(self._header(report))
        sections.append(self._param_comparison(report))
        sections.append(self._fold_summary(report))
        sections.append(self._cost_sensitivity(report))
        sections.append(self._robustness(report))
        sections.append(self._safety_flags(report))
        sections.append(self._what_could_go_wrong(report))
        sections.append(self._recommendation(report))
        return "\n\n".join(s for s in sections if s)

    def _header(self, r: WFOReport) -> str:
        method = r.config_summary.get("method", "unknown")
        return (
            f"# WFO Report — {r.bot_id}\n\n"
            f"**Method:** {method}  \n"
            f"**Config:** {r.config_summary}"
        )

    def _param_comparison(self, r: WFOReport) -> str:
        if not r.current_params and not r.suggested_params:
            return ""
        lines = ["## Parameter Comparison\n", "| Parameter | Current | Suggested |", "|---|---|---|"]
        all_keys = set(r.current_params.keys()) | set(r.suggested_params.keys())
        for key in sorted(all_keys):
            cur = r.current_params.get(key, "—")
            sug = r.suggested_params.get(key, "—")
            lines.append(f"| {key} | {cur} | {sug} |")
        return "\n".join(lines)

    def _fold_summary(self, r: WFOReport) -> str:
        if not r.fold_results:
            return "## Fold Results\n\nNo folds completed."
        lines = [
            "## Fold Results\n",
            "| Fold | IS Sharpe | OOS Sharpe | OOS PnL | OOS Trades | Degradation |",
            "|---|---|---|---|---|---|",
        ]
        for fr in r.fold_results:
            deg = f"{fr.oos_degradation_pct:.0%}"
            lines.append(
                f"| {fr.fold.fold_number} | {fr.is_metrics.sharpe_ratio:.2f} | "
                f"{fr.oos_metrics.sharpe_ratio:.2f} | ${fr.oos_metrics.net_pnl:.0f} | "
                f"{fr.oos_metrics.total_trades} | {deg} |"
            )
        return "\n".join(lines)

    def _cost_sensitivity(self, r: WFOReport) -> str:
        if not r.cost_sensitivity:
            return ""
        lines = [
            "## Cost Sensitivity\n",
            "| Cost Multiplier | Sharpe | Net PnL |",
            "|---|---|---|",
        ]
        for cs in r.cost_sensitivity:
            mult = f"{cs.cost_multiplier}x"
            lines.append(f"| {mult} | {cs.metrics.sharpe_ratio:.2f} | ${cs.metrics.net_pnl:.0f} |")
        return "\n".join(lines)

    def _robustness(self, r: WFOReport) -> str:
        rob = r.robustness
        return (
            f"## Robustness\n\n"
            f"**Score:** {rob.robustness_score:.0f}/100  \n"
            f"**Neighborhood stable:** {rob.neighborhood_stable}  \n"
            f"**Regime stable:** {rob.regime_stable} "
            f"({rob.profitable_regime_count} profitable regimes)"
        )

    def _safety_flags(self, r: WFOReport) -> str:
        if not r.safety_flags:
            return "## Safety Flags\n\nNone."
        lines = ["## Safety Flags\n"]
        for f in r.safety_flags:
            icon = "🔴" if f.severity == "high" else "🟡" if f.severity == "medium" else "🟢"
            lines.append(f"- {icon} **{f.flag_type}** ({f.severity}): {f.description}")
        return "\n".join(lines)

    def _what_could_go_wrong(self, r: WFOReport) -> str:
        risks: list[str] = []
        if r.safety_flags:
            for f in r.safety_flags:
                risks.append(f"- {f.description}")
        if any(fr.oos_degradation_pct > 0.3 for fr in r.fold_results):
            risks.append("- Significant IS→OOS degradation in some folds (>30%)")
        if r.robustness.robustness_score < 60:
            risks.append("- Low robustness score — results may not generalize")
        if not risks:
            risks.append("- No major risks identified")
        return "## What Could Go Wrong\n\n" + "\n".join(risks)

    def _recommendation(self, r: WFOReport) -> str:
        return (
            f"## Recommendation: **{r.recommendation.value.upper()}**\n\n"
            f"{r.recommendation_reasoning}"
        )
```

```python
# analysis/wfo_prompt_assembler.py
"""WFO prompt assembler — builds context package for Claude WFO analysis.

Similar pattern to DailyPromptAssembler and WeeklyPromptAssembler but
tailored for WFO result interpretation and recommendation.
"""
from __future__ import annotations

import json
from pathlib import Path

_WFO_INSTRUCTIONS = """\
1. Review the WFO report for bot {bot_id}
2. Verify the parameter changes make strategic sense (not just statistical)
3. Check cost sensitivity: are results fragile at higher costs?
4. Check robustness: stable across regimes and neighboring params?
5. Review safety flags and assess overall risk
6. Provide your recommendation: ADOPT / TEST_FURTHER / REJECT with reasoning
7. If ADOPT: summarize the param changes for a draft PR description
8. If TEST_FURTHER: specify what additional validation is needed
9. If REJECT: explain why and suggest alternative approaches
10. Output: wfo_analysis.md"""


class WFOPromptAssembler:
    """Assembles the full context package for a WFO analysis agent invocation."""

    def __init__(
        self,
        bot_id: str,
        memory_dir: Path,
        wfo_output_dir: Path,
    ) -> None:
        self.bot_id = bot_id
        self.memory_dir = memory_dir
        self.wfo_output_dir = wfo_output_dir

    def assemble(self) -> dict:
        """Build the complete WFO prompt package."""
        return {
            "system_prompt": self._build_system_prompt(),
            "task_prompt": self._build_task_prompt(),
            "data": self._load_data(),
            "instructions": _WFO_INSTRUCTIONS.format(bot_id=self.bot_id),
            "skill_context": self._load_skill_context(),
            "context_files": self._list_context_files(),
        }

    def _build_system_prompt(self) -> str:
        parts: list[str] = []
        policy_dir = self.memory_dir / "policies" / "v1"
        for name in ["agents.md", "trading_rules.md", "soul.md"]:
            path = policy_dir / name
            if path.exists():
                parts.append(f"--- {name} ---\n{path.read_text()}")
        return "\n\n".join(parts)

    def _build_task_prompt(self) -> str:
        return (
            f"Review the walk-forward optimization results for {self.bot_id}. "
            f"The WFO pipeline has run and produced a report with parameter recommendations, "
            f"cost sensitivity analysis, robustness scores, and safety flags. "
            f"Provide your assessment and recommendation."
        )

    def _load_data(self) -> dict:
        data: dict = {}
        report_path = self.wfo_output_dir / "wfo_report.json"
        if report_path.exists():
            try:
                data["wfo_report"] = json.loads(report_path.read_text())
            except (json.JSONDecodeError, OSError):
                pass
        return data

    def _load_skill_context(self) -> str:
        skill_path = self.memory_dir / "skills" / "wfo_pipeline.md"
        if skill_path.exists():
            return skill_path.read_text()
        return ""

    def _list_context_files(self) -> list[str]:
        files: list[str] = []
        report_path = self.wfo_output_dir / "wfo_report.json"
        if report_path.exists():
            files.append(str(report_path))
        policy_dir = self.memory_dir / "policies" / "v1"
        for name in ["agents.md", "trading_rules.md", "soul.md"]:
            path = policy_dir / name
            if path.exists():
                files.append(str(path))
        return files
```

**Step 4: Run tests to verify they pass**

Run: `venv/Scripts/python -m pytest tests/test_wfo_report_builder.py tests/test_wfo_prompt_assembler.py -v`
Expected: All 9 tests PASS

**Step 5: Commit**

```bash
git add analysis/wfo_report_builder.py analysis/wfo_prompt_assembler.py tests/test_wfo_report_builder.py tests/test_wfo_prompt_assembler.py
git commit -m "feat: add WFO report builder (markdown) and prompt assembler (Claude context)"
```

---

## Task 10: Orchestrator Wiring

**Files:**
- Modify: `orchestrator/orchestrator_brain.py`
- Modify: `orchestrator/worker.py`
- Modify: `orchestrator/scheduler.py`
- Test: `tests/test_wfo_orchestrator_wiring.py`

**Step 1: Write the failing test**

```python
# tests/test_wfo_orchestrator_wiring.py
"""Tests for WFO orchestrator wiring — brain, worker, scheduler."""
import asyncio

from orchestrator.orchestrator_brain import OrchestratorBrain, ActionType
from orchestrator.worker import Worker
from orchestrator.scheduler import SchedulerConfig, create_scheduler_jobs


class TestBrainWFORouting:
    def test_wfo_trigger_spawns_wfo(self):
        brain = OrchestratorBrain()
        event = {
            "event_id": "wfo-bot2-2026-03-01",
            "event_type": "wfo_trigger",
            "bot_id": "bot2",
            "payload": "{}",
        }
        actions = brain.decide(event)
        assert len(actions) == 1
        assert actions[0].type == ActionType.SPAWN_WFO
        assert actions[0].bot_id == "bot2"


class TestWorkerWFODispatch:
    def test_dispatches_to_wfo_handler(self):
        from unittest.mock import AsyncMock

        from orchestrator.db.queue import EventQueue
        from orchestrator.task_registry import TaskRegistry

        queue = AsyncMock(spec=EventQueue)
        queue.peek.return_value = [
            {
                "event_id": "wfo-bot2-2026-03-01",
                "event_type": "wfo_trigger",
                "bot_id": "bot2",
                "payload": "{}",
            },
        ]

        registry = TaskRegistry()
        brain = OrchestratorBrain()
        worker = Worker(queue, registry, brain)
        handler = AsyncMock()
        worker.on_wfo = handler

        asyncio.get_event_loop().run_until_complete(worker.process_batch(limit=1))
        handler.assert_called_once()
        action = handler.call_args[0][0]
        assert action.type == ActionType.SPAWN_WFO


class TestSchedulerWFOConfig:
    def test_scheduler_config_has_wfo_fields(self):
        cfg = SchedulerConfig()
        assert hasattr(cfg, "wfo_day_of_week")
        assert hasattr(cfg, "wfo_hour")

    def test_scheduler_creates_wfo_job(self):
        async def noop():
            pass

        cfg = SchedulerConfig()
        jobs = create_scheduler_jobs(
            cfg,
            worker_fn=noop,
            monitoring_fn=noop,
            relay_fn=noop,
            wfo_fn=noop,
        )
        wfo_jobs = [j for j in jobs if j["name"] == "wfo"]
        assert len(wfo_jobs) == 1
        assert wfo_jobs[0]["trigger"] == "cron"

    def test_scheduler_omits_wfo_without_fn(self):
        async def noop():
            pass

        cfg = SchedulerConfig()
        jobs = create_scheduler_jobs(
            cfg,
            worker_fn=noop,
            monitoring_fn=noop,
            relay_fn=noop,
        )
        wfo_jobs = [j for j in jobs if j["name"] == "wfo"]
        assert len(wfo_jobs) == 0
```

**Step 2: Run test to verify it fails**

Run: `venv/Scripts/python -m pytest tests/test_wfo_orchestrator_wiring.py -v`
Expected: FAIL with `AttributeError: type object 'ActionType' has no member 'SPAWN_WFO'`

**Step 3: Modify existing files**

**orchestrator/orchestrator_brain.py** — add `SPAWN_WFO` and `wfo_trigger` handler:

Add to the `ActionType` enum:
```
    SPAWN_WFO = "spawn_wfo"
```

Add handler method to `OrchestratorBrain`:
```python
    def _handle_wfo_trigger(self, event_id: str, bot_id: str, event: dict) -> list[Action]:
        return [Action(type=ActionType.SPAWN_WFO, event_id=event_id, bot_id=bot_id)]
```

Add to the `_handlers` dict:
```
        "wfo_trigger": _handle_wfo_trigger,
```

**orchestrator/worker.py** — add `on_wfo` handler:

Add to `__init__`:
```python
        self.on_wfo: Callable[[Action], Awaitable[None]] | None = None
```

Add dispatch case in `_dispatch`:
```python
        elif action.type == ActionType.SPAWN_WFO:
            if self.on_wfo:
                await self.on_wfo(action)
            else:
                logger.info("WFO triggered but no handler set: %s", action.event_id)
```

**orchestrator/scheduler.py** — add WFO cron fields:

Add to `SchedulerConfig`:
```python
    wfo_day_of_week: str = "sat"  # run WFO on Saturday
    wfo_hour: int = 2
    wfo_minute: int = 0
```

Add `wfo_fn` parameter and job to `create_scheduler_jobs`:
```python
def create_scheduler_jobs(
    config: SchedulerConfig,
    worker_fn: ...,
    monitoring_fn: ...,
    relay_fn: ...,
    daily_analysis_fn: ... = None,
    weekly_analysis_fn: ... = None,
    wfo_fn: Callable[[], Awaitable[None]] | None = None,
) -> list[dict]:
    # ... existing jobs ...

    if wfo_fn is not None:
        jobs.append({
            "name": "wfo",
            "func": wfo_fn,
            "trigger": "cron",
            "day_of_week": config.wfo_day_of_week,
            "hour": config.wfo_hour,
            "minute": config.wfo_minute,
        })

    return jobs
```

**Step 4: Run test to verify it passes**

Run: `venv/Scripts/python -m pytest tests/test_wfo_orchestrator_wiring.py -v`
Expected: All 5 tests PASS

Also verify existing orchestrator tests still pass:

Run: `venv/Scripts/python -m pytest tests/test_orchestrator_brain.py tests/test_worker.py tests/test_scheduler.py -v`
Expected: All existing tests PASS

**Step 5: Commit**

```bash
git add orchestrator/orchestrator_brain.py orchestrator/worker.py orchestrator/scheduler.py tests/test_wfo_orchestrator_wiring.py
git commit -m "feat: wire WFO into orchestrator brain, worker, and scheduler"
```

---

## Task 11: Integration Test

**Files:**
- Create: `tests/test_wfo_integration.py`

**Step 1: Write the integration test**

```python
# tests/test_wfo_integration.py
"""Integration test — full WFO pipeline from config to report to prompt package."""
import json
import random
from datetime import datetime, timedelta
from pathlib import Path

from schemas.events import TradeEvent
from schemas.wfo_config import (
    WFOConfig,
    WFOMethod,
    ParameterDef,
    ParameterSpace,
    CostModelConfig,
    OptimizationConfig,
    OptimizationObjective,
    RobustnessConfig,
)
from schemas.wfo_results import WFORecommendation, WFOReport
from skills.run_wfo import WFORunner
from analysis.wfo_report_builder import WFOReportBuilder
from analysis.wfo_prompt_assembler import WFOPromptAssembler


def _generate_realistic_trades(seed: int = 42) -> list[TradeEvent]:
    """Generate 200 trades spread over 400 days with regime variation."""
    random.seed(seed)
    regimes = ["trending_up", "trending_down", "ranging", "volatile"]
    trades: list[TradeEvent] = []
    base_date = datetime(2025, 1, 1)

    for i in range(200):
        offset = int(i * 400 / 200)
        dt = base_date + timedelta(days=offset)
        regime = regimes[i % len(regimes)]

        # Trending regimes are more profitable, ranging less so
        if regime in ("trending_up", "trending_down"):
            pnl = random.gauss(50, 80)
        elif regime == "ranging":
            pnl = random.gauss(-10, 60)
        else:
            pnl = random.gauss(20, 120)

        signal_strength = random.uniform(0.2, 1.0)

        trades.append(TradeEvent(
            trade_id=f"int-t{i}",
            bot_id="bot2",
            pair="BTCUSDT",
            side="LONG",
            entry_time=dt,
            exit_time=dt + timedelta(hours=2),
            entry_price=40000.0,
            exit_price=40000.0 + pnl / 0.1,
            position_size=0.1,
            pnl=pnl,
            pnl_pct=pnl / 4000 * 100,
            entry_signal_strength=signal_strength,
            market_regime=regime,
            entry_signal="ema_cross",
        ))
    return trades


class TestFullWFOPipeline:
    def test_end_to_end(self, tmp_path: Path):
        """Config → WFO run → report builder → prompt assembler → all outputs valid."""
        # 1. Build config
        config = WFOConfig(
            bot_id="bot2",
            method=WFOMethod.ANCHORED,
            in_sample_days=120,
            out_of_sample_days=30,
            step_days=30,
            min_folds=2,
            parameter_space=ParameterSpace(
                bot_id="bot2",
                parameters=[
                    ParameterDef(
                        name="signal_strength_min",
                        min_value=0.3,
                        max_value=0.9,
                        step=0.3,
                        current_value=0.6,
                    ),
                ],
            ),
            optimization=OptimizationConfig(
                objective=OptimizationObjective.SHARPE,
                max_drawdown_constraint=0.50,
            ),
            cost_model=CostModelConfig(
                fees_per_trade_bps=7.0,
                fixed_slippage_bps=5.0,
                cost_multipliers=[1.0, 1.5, 2.0],
            ),
            robustness=RobustnessConfig(
                min_trades_per_fold=5,
                min_profitable_regimes=2,
                total_regime_types=4,
            ),
        )

        # 2. Generate trades
        trades = _generate_realistic_trades()

        # 3. Run WFO
        runner = WFORunner(config)
        report = runner.run(
            trades=trades,
            missed=[],
            data_start="2025-01-01",
            data_end="2026-03-01",
        )

        # 4. Validate report structure
        assert isinstance(report, WFOReport)
        assert report.bot_id == "bot2"
        assert len(report.fold_results) >= 2
        assert len(report.cost_sensitivity) == 3
        assert report.robustness.robustness_score >= 0
        assert report.recommendation in list(WFORecommendation)

        # 5. Write output
        output_dir = tmp_path / "runs" / "wfo" / "bot2"
        runner.write_output(report, output_dir)
        assert (output_dir / "wfo_report.json").exists()
        loaded = json.loads((output_dir / "wfo_report.json").read_text())
        assert loaded["bot_id"] == "bot2"

        # 6. Build markdown report
        builder = WFOReportBuilder()
        md = builder.build_markdown(report)
        assert len(md) > 100  # non-trivial report
        assert "bot2" in md
        assert "Parameter Comparison" in md

        # 7. Assemble prompt package
        memory_dir = tmp_path / "memory"
        policy_dir = memory_dir / "policies" / "v1"
        policy_dir.mkdir(parents=True)
        (policy_dir / "agents.md").write_text("You analyze WFO results.")
        (policy_dir / "trading_rules.md").write_text("Max 15% drawdown.")
        (policy_dir / "soul.md").write_text("Conservative risk tolerance.")

        assembler = WFOPromptAssembler(
            bot_id="bot2",
            memory_dir=memory_dir,
            wfo_output_dir=output_dir,
        )
        package = assembler.assemble()
        assert "system_prompt" in package
        assert "task_prompt" in package
        assert package["data"]["wfo_report"]["bot_id"] == "bot2"

    def test_yaml_config_loading(self, tmp_path: Path):
        """Config can be loaded from YAML dict (simulating wfo_config.yaml)."""
        import yaml

        yaml_content = {
            "bot_id": "bot3",
            "method": "rolling",
            "in_sample_days": 90,
            "out_of_sample_days": 14,
            "step_days": 14,
            "min_folds": 2,
            "parameter_space": {
                "bot_id": "bot3",
                "parameters": [
                    {"name": "signal_strength_min", "min_value": 0.2, "max_value": 0.8, "step": 0.2, "current_value": 0.5},
                ],
            },
            "optimization": {"objective": "calmar", "max_drawdown_constraint": 0.20},
            "cost_model": {"fees_per_trade_bps": 7, "fixed_slippage_bps": 5},
            "robustness": {"min_trades_per_fold": 3, "min_profitable_regimes": 2, "total_regime_types": 4},
        }

        yaml_path = tmp_path / "wfo_config.yaml"
        yaml_path.write_text(yaml.dump(yaml_content))

        loaded = yaml.safe_load(yaml_path.read_text())
        config = WFOConfig(**loaded)
        assert config.bot_id == "bot3"
        assert config.method.value == "rolling"

        # Run pipeline with loaded config
        trades = _generate_realistic_trades(seed=99)
        runner = WFORunner(config)
        report = runner.run(trades=trades, missed=[], data_start="2025-01-01", data_end="2026-03-01")
        assert isinstance(report, WFOReport)

    def test_insufficient_data_produces_reject(self):
        config = WFOConfig(
            bot_id="bot1",
            in_sample_days=180,
            out_of_sample_days=30,
            min_folds=10,
            parameter_space=ParameterSpace(bot_id="bot1", parameters=[]),
        )
        runner = WFORunner(config)
        report = runner.run(
            trades=[],
            missed=[],
            data_start="2025-01-01",
            data_end="2025-06-01",
        )
        assert report.recommendation == WFORecommendation.REJECT
```

**Step 2: Run test to verify it passes**

Run: `venv/Scripts/python -m pytest tests/test_wfo_integration.py -v`
Expected: All 3 tests PASS

**Step 3: Run the full test suite to verify no regressions**

Run: `venv/Scripts/python -m pytest tests/ -v --tb=short`
Expected: All tests PASS (existing Phase 1–3 tests + all new WFO tests)

**Step 4: Commit**

```bash
git add tests/test_wfo_integration.py
git commit -m "feat: add WFO integration test — full pipeline from config to prompt package"
```

---

## Summary

| Task | Component | Tests | New Files |
|------|-----------|-------|-----------|
| 0 | WFO Configuration Schemas | ~17 | `schemas/wfo_config.py` |
| 1 | WFO Result Schemas | ~15 | `schemas/wfo_results.py` |
| 2 | Cost Model | ~12 | `skills/cost_model.py` |
| 3 | Fold Generator | ~11 | `skills/fold_generator.py` |
| 4 | Leakage Detector | ~10 | `skills/leakage_detector.py` |
| 5 | Backtest Simulator | ~12 | `skills/backtest_simulator.py` |
| 6 | Parameter Optimizer | ~6 | `skills/param_optimizer.py` |
| 7 | Robustness Tester | ~10 | `skills/robustness_tester.py` |
| 8 | WFO Runner | ~6 | `skills/run_wfo.py` |
| 9 | Report Builder + Prompt Assembler | ~9 | `analysis/wfo_report_builder.py`, `analysis/wfo_prompt_assembler.py` |
| 10 | Orchestrator Wiring | ~5 | Modifies 3 existing files |
| 11 | Integration Test | ~3 | `tests/test_wfo_integration.py` |
| **Total** | | **~116** | **10 new + 3 modified** |
