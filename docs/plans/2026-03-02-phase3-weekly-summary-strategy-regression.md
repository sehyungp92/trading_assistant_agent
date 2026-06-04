# Phase 3: Weekly Summary + Strategy Refinement + Regression Harness — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build the weekly metrics aggregation pipeline, weekly summary prompt assembler, 4-tier strategy refinement engine, golden-day regression harness, and orchestrator wiring that transform daily reports into weekly insights, testable strategy suggestions, and regression-protected analytics.

**Architecture:** Deterministic Python scripts aggregate 7 days of curated daily metrics into weekly summaries with trend analysis, week-over-week comparisons, and process quality trends. A 4-tier strategy refinement engine analyzes weekly data to produce parameter suggestions, filter adjustments, strategy variants, and new hypotheses — each tier with explicit confidence levels and simulation assumptions. A regression harness maintains frozen "golden day" datasets with known-good classifications and human feedback, and runs automated tests to catch pipeline/prompt drift. The orchestrator triggers weekly analysis via a cron job, reusing the same brain→worker→action pattern as daily analysis.

**Tech Stack:** Python 3.12, Pydantic v2, pytest, pathlib (curated data dirs), statistics (stdlib for metrics)

**Assumes:** Phase 1 and Phase 2 are fully implemented — event queue, task registry, orchestrator brain/worker/scheduler, daily metrics builder, portfolio risk computation, quality gate, prompt assembler, feedback handler, and all schemas exist and pass tests.

**Directory structure this plan creates:**

```
trading_assistant/
  schemas/
    weekly_metrics.py         # WeeklySummary, BotWeeklySummary, WeekOverWeekComparison
    strategy_suggestions.py   # StrategySuggestion, SuggestionTier, RefinementReport
  skills/
    build_weekly_metrics.py   # aggregate 7 daily summaries → weekly metrics
  analysis/
    weekly_prompt_assembler.py  # builds context package for weekly Claude analysis
    strategy_engine.py          # 4-tier strategy refinement (deterministic)
  tests/
    golden_days/
      README.md               # explains golden day structure
    test_weekly_metrics.py
    test_weekly_metrics_pipeline.py
    test_strategy_suggestions.py
    test_strategy_engine.py
    test_weekly_prompt_assembler.py
    test_regression_suite.py
    test_weekly_integration.py
  orchestrator/
    orchestrator_brain.py     # MODIFY: add weekly_summary_trigger handler
    scheduler.py              # MODIFY: add weekly_analysis cron job + config field
    worker.py                 # MODIFY: add on_weekly_analysis handler
```

---

## Task 0: Weekly Metrics Schemas

**Files:**
- Create: `schemas/weekly_metrics.py`
- Test: `tests/test_weekly_metrics.py`

**Step 1: Write the failing test**

```python
# tests/test_weekly_metrics.py
"""Tests for weekly metrics schemas."""
from schemas.weekly_metrics import (
    BotWeeklySummary,
    WeeklySummary,
    WeekOverWeekComparison,
    ProcessQualityTrend,
    RegimePerformanceTrend,
    FilterWeeklySummary,
    CorrelationSummary,
)


class TestBotWeeklySummary:
    def test_creates_from_minimal_data(self):
        summary = BotWeeklySummary(
            week_start="2026-02-23",
            week_end="2026-03-01",
            bot_id="bot1",
            total_trades=50,
            win_count=30,
            loss_count=20,
            gross_pnl=1200.0,
            net_pnl=1100.0,
        )
        assert summary.bot_id == "bot1"
        assert summary.win_rate == 0.6

    def test_win_rate_zero_trades(self):
        summary = BotWeeklySummary(
            week_start="2026-02-23", week_end="2026-03-01", bot_id="bot1"
        )
        assert summary.win_rate == 0.0

    def test_profit_factor_zero_losses(self):
        summary = BotWeeklySummary(
            week_start="2026-02-23",
            week_end="2026-03-01",
            bot_id="bot1",
            total_trades=5,
            win_count=5,
            loss_count=0,
            avg_win=100.0,
            avg_loss=0.0,
        )
        assert summary.profit_factor == float("inf")

    def test_daily_pnl_series(self):
        summary = BotWeeklySummary(
            week_start="2026-02-23",
            week_end="2026-03-01",
            bot_id="bot1",
            daily_pnl={"2026-02-23": 50.0, "2026-02-24": -20.0, "2026-02-25": 80.0},
        )
        assert len(summary.daily_pnl) == 3


class TestWeeklySummary:
    def test_creates_with_bots(self):
        ws = WeeklySummary(
            week_start="2026-02-23",
            week_end="2026-03-01",
            bot_summaries={
                "bot1": BotWeeklySummary(
                    week_start="2026-02-23",
                    week_end="2026-03-01",
                    bot_id="bot1",
                    total_trades=30,
                    net_pnl=500.0,
                ),
            },
            total_net_pnl=500.0,
            total_trades=30,
        )
        assert ws.total_net_pnl == 500.0
        assert "bot1" in ws.bot_summaries


class TestWeekOverWeekComparison:
    def test_creates_comparison(self):
        wow = WeekOverWeekComparison(
            current_week="2026-02-23",
            previous_week="2026-02-16",
            pnl_delta=150.0,
            pnl_delta_pct=12.5,
            win_rate_delta=0.05,
            trade_count_delta=-3,
            avg_process_quality_delta=2.0,
        )
        assert wow.pnl_delta == 150.0
        assert wow.pnl_delta_pct == 12.5

    def test_negative_deltas(self):
        wow = WeekOverWeekComparison(
            current_week="2026-02-23",
            previous_week="2026-02-16",
            pnl_delta=-200.0,
            pnl_delta_pct=-15.0,
            win_rate_delta=-0.1,
        )
        assert wow.pnl_delta < 0


class TestProcessQualityTrend:
    def test_creates_trend(self):
        pqt = ProcessQualityTrend(
            bot_id="bot1",
            weekly_avg_scores=[72.0, 75.0, 78.0, 80.0],
            current_avg=80.0,
            trend_direction="improving",
            most_frequent_root_causes={"regime_mismatch": 12, "normal_loss": 25},
        )
        assert pqt.trend_direction == "improving"
        assert pqt.current_avg == 80.0


class TestRegimePerformanceTrend:
    def test_creates_trend(self):
        rpt = RegimePerformanceTrend(
            bot_id="bot1",
            regime="trending_up",
            weekly_pnl=[200.0, 180.0, 250.0, 300.0],
            weekly_win_rate=[0.7, 0.65, 0.75, 0.8],
            weekly_trade_count=[10, 8, 12, 11],
        )
        assert rpt.regime == "trending_up"
        assert len(rpt.weekly_pnl) == 4


class TestFilterWeeklySummary:
    def test_creates_summary(self):
        fws = FilterWeeklySummary(
            bot_id="bot1",
            filter_name="volatility_filter",
            total_blocks=47,
            blocks_that_would_have_won=31,
            blocks_that_would_have_lost=16,
            net_impact_pnl=-180.0,
            confidence=0.7,
        )
        assert fws.net_impact_pnl == -180.0
        assert fws.total_blocks == 47


class TestCorrelationSummary:
    def test_creates_summary(self):
        cs = CorrelationSummary(
            bot_a="bot1",
            bot_b="bot2",
            rolling_30d_correlation=0.45,
            weekly_pnl_correlation=0.52,
            same_direction_pct=0.6,
        )
        assert cs.rolling_30d_correlation == 0.45
```

**Step 2: Run test to verify it fails**

Run: `venv/Scripts/python -m pytest tests/test_weekly_metrics.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'schemas.weekly_metrics'`

**Step 3: Write minimal implementation**

```python
# schemas/weekly_metrics.py
"""Weekly metrics schemas — Pydantic models for aggregated weekly data.

These define the output format of the weekly aggregation pipeline (skills/build_weekly_metrics.py).
Built from 7 days of daily curated data (schemas/daily_metrics.py).
"""
from __future__ import annotations

from pydantic import BaseModel, computed_field


class BotWeeklySummary(BaseModel):
    """Aggregated weekly stats for a single bot."""

    week_start: str  # YYYY-MM-DD (Monday)
    week_end: str  # YYYY-MM-DD (Sunday)
    bot_id: str
    total_trades: int = 0
    win_count: int = 0
    loss_count: int = 0
    gross_pnl: float = 0.0
    net_pnl: float = 0.0
    max_drawdown_pct: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    avg_process_quality: float = 100.0
    missed_count: int = 0
    missed_would_have_won: int = 0
    error_count: int = 0
    avg_uptime_pct: float = 100.0
    daily_pnl: dict[str, float] = {}  # date → PnL for sparkline

    @computed_field  # type: ignore[prop-decorator]
    @property
    def win_rate(self) -> float:
        if self.total_trades == 0:
            return 0.0
        return self.win_count / self.total_trades

    @computed_field  # type: ignore[prop-decorator]
    @property
    def profit_factor(self) -> float:
        total_wins = self.avg_win * self.win_count
        total_losses = abs(self.avg_loss) * self.loss_count
        if total_losses == 0:
            return float("inf") if total_wins > 0 else 0.0
        return total_wins / total_losses


class WeeklySummary(BaseModel):
    """Portfolio-level weekly summary across all bots."""

    week_start: str
    week_end: str
    bot_summaries: dict[str, BotWeeklySummary] = {}
    total_net_pnl: float = 0.0
    total_gross_pnl: float = 0.0
    total_trades: int = 0
    portfolio_max_drawdown_pct: float = 0.0


class WeekOverWeekComparison(BaseModel):
    """Deltas between current and previous week."""

    current_week: str  # week_start date
    previous_week: str
    pnl_delta: float = 0.0
    pnl_delta_pct: float = 0.0
    win_rate_delta: float = 0.0
    trade_count_delta: int = 0
    avg_process_quality_delta: float = 0.0


class ProcessQualityTrend(BaseModel):
    """Process quality over the last N weeks for one bot."""

    bot_id: str
    weekly_avg_scores: list[float] = []  # last 4 weeks, oldest first
    current_avg: float = 0.0
    trend_direction: str = "stable"  # improving | degrading | stable
    most_frequent_root_causes: dict[str, int] = {}


class RegimePerformanceTrend(BaseModel):
    """Performance trend by regime for one bot over multiple weeks."""

    bot_id: str
    regime: str
    weekly_pnl: list[float] = []
    weekly_win_rate: list[float] = []
    weekly_trade_count: list[int] = []


class FilterWeeklySummary(BaseModel):
    """Aggregated filter impact across the week for one bot."""

    bot_id: str
    filter_name: str
    total_blocks: int = 0
    blocks_that_would_have_won: int = 0
    blocks_that_would_have_lost: int = 0
    net_impact_pnl: float = 0.0  # negative = filter cost more than it saved
    confidence: float = 0.0  # avg confidence of missed opp simulations


class CorrelationSummary(BaseModel):
    """Pairwise bot correlation metrics."""

    bot_a: str
    bot_b: str
    rolling_30d_correlation: float = 0.0
    weekly_pnl_correlation: float = 0.0
    same_direction_pct: float = 0.0  # % of time both bots on same side
```

**Step 4: Run test to verify it passes**

Run: `venv/Scripts/python -m pytest tests/test_weekly_metrics.py -v`
Expected: All 11 tests PASS

**Step 5: Commit**

```bash
git add schemas/weekly_metrics.py tests/test_weekly_metrics.py
git commit -m "feat: add weekly metrics schemas for aggregation pipeline"
```

---

## Task 1: Strategy Suggestion Schemas

**Files:**
- Create: `schemas/strategy_suggestions.py`
- Test: `tests/test_strategy_suggestions.py`

**Step 1: Write the failing test**

```python
# tests/test_strategy_suggestions.py
"""Tests for strategy suggestion schemas."""
from schemas.strategy_suggestions import (
    SuggestionTier,
    StrategySuggestion,
    RefinementReport,
)


class TestSuggestionTier:
    def test_all_tiers_exist(self):
        assert SuggestionTier.PARAMETER == "parameter"
        assert SuggestionTier.FILTER == "filter"
        assert SuggestionTier.STRATEGY_VARIANT == "strategy_variant"
        assert SuggestionTier.HYPOTHESIS == "hypothesis"


class TestStrategySuggestion:
    def test_parameter_suggestion(self):
        s = StrategySuggestion(
            tier=SuggestionTier.PARAMETER,
            bot_id="bot2",
            title="Relax RSI threshold in ranging markets",
            description=(
                "Bot2's RSI threshold of 30 is too aggressive in ranging markets — "
                "entries at RSI 35 had better outcomes over 30 days"
            ),
            current_value="rsi_threshold=30",
            suggested_value="rsi_threshold=35",
            evidence_days=30,
            estimated_impact_pnl=120.0,
            confidence=0.8,
            simulation_assumptions=["mid_fill", "5bps_slippage", "fees_included"],
        )
        assert s.tier == SuggestionTier.PARAMETER
        assert s.confidence == 0.8

    def test_filter_suggestion(self):
        s = StrategySuggestion(
            tier=SuggestionTier.FILTER,
            bot_id="bot3",
            title="Relax volume filter from 2x to 1.5x avg",
            description="Volume filter blocked 47 entries this month. 31 would have been profitable.",
            current_value="volume_filter=2.0x",
            suggested_value="volume_filter=1.5x",
            evidence_days=30,
            estimated_impact_pnl=180.0,
            confidence=0.65,
        )
        assert s.tier == SuggestionTier.FILTER

    def test_strategy_variant(self):
        s = StrategySuggestion(
            tier=SuggestionTier.STRATEGY_VARIANT,
            bot_id="bot1",
            title="Add regime gate: mean-reversion when ADX < 20",
            description="EMA cross strategy loses in ranging. Consider regime gate.",
            requires_human_judgment=True,
        )
        assert s.requires_human_judgment is True

    def test_hypothesis(self):
        s = StrategySuggestion(
            tier=SuggestionTier.HYPOTHESIS,
            bot_id="",
            title="OI increase + negative funding precedes reversals",
            description="Data shows pattern. Needs backtest validation.",
            requires_human_judgment=True,
            confidence=0.3,
        )
        assert s.tier == SuggestionTier.HYPOTHESIS
        assert s.confidence == 0.3


class TestRefinementReport:
    def test_creates_report(self):
        report = RefinementReport(
            week_start="2026-02-23",
            week_end="2026-03-01",
            suggestions=[
                StrategySuggestion(
                    tier=SuggestionTier.PARAMETER,
                    bot_id="bot2",
                    title="Adjust RSI threshold",
                    description="Better outcomes at RSI 35",
                    confidence=0.8,
                ),
                StrategySuggestion(
                    tier=SuggestionTier.FILTER,
                    bot_id="bot3",
                    title="Relax volume filter",
                    description="Filter cost exceeds benefit",
                    confidence=0.65,
                ),
            ],
        )
        assert len(report.suggestions) == 2
        assert report.suggestions_by_tier["parameter"] == 1
        assert report.suggestions_by_tier["filter"] == 1

    def test_empty_report(self):
        report = RefinementReport(
            week_start="2026-02-23", week_end="2026-03-01"
        )
        assert len(report.suggestions) == 0
        assert report.suggestions_by_tier == {}

    def test_high_confidence_only(self):
        report = RefinementReport(
            week_start="2026-02-23",
            week_end="2026-03-01",
            suggestions=[
                StrategySuggestion(
                    tier=SuggestionTier.PARAMETER,
                    bot_id="bot1",
                    title="High conf",
                    description="...",
                    confidence=0.85,
                ),
                StrategySuggestion(
                    tier=SuggestionTier.HYPOTHESIS,
                    bot_id="bot2",
                    title="Low conf",
                    description="...",
                    confidence=0.3,
                ),
            ],
        )
        high_conf = [s for s in report.suggestions if s.confidence >= 0.7]
        assert len(high_conf) == 1
```

**Step 2: Run test to verify it fails**

Run: `venv/Scripts/python -m pytest tests/test_strategy_suggestions.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'schemas.strategy_suggestions'`

**Step 3: Write minimal implementation**

```python
# schemas/strategy_suggestions.py
"""Strategy suggestion schemas — 4-tier refinement output models.

Tier 1: Parameter suggestions (automated, high confidence)
Tier 2: Filter adjustments (automated, medium confidence)
Tier 3: Strategy variants (semi-automated, requires human judgment)
Tier 4: New hypotheses (human-led, Claude-assisted)
"""
from __future__ import annotations

from collections import Counter
from enum import Enum

from pydantic import BaseModel, computed_field


class SuggestionTier(str, Enum):
    PARAMETER = "parameter"
    FILTER = "filter"
    STRATEGY_VARIANT = "strategy_variant"
    HYPOTHESIS = "hypothesis"


class StrategySuggestion(BaseModel):
    """A single strategy refinement suggestion."""

    tier: SuggestionTier
    bot_id: str = ""
    title: str
    description: str
    current_value: str = ""
    suggested_value: str = ""
    evidence_days: int = 0
    estimated_impact_pnl: float = 0.0
    confidence: float = 0.0  # 0–1
    simulation_assumptions: list[str] = []
    requires_human_judgment: bool = False


class RefinementReport(BaseModel):
    """Aggregated strategy refinement output for a week."""

    week_start: str
    week_end: str
    suggestions: list[StrategySuggestion] = []

    @computed_field  # type: ignore[prop-decorator]
    @property
    def suggestions_by_tier(self) -> dict[str, int]:
        counts = Counter(s.tier.value for s in self.suggestions)
        return dict(counts)
```

**Step 4: Run test to verify it passes**

Run: `venv/Scripts/python -m pytest tests/test_strategy_suggestions.py -v`
Expected: All 8 tests PASS

**Step 5: Commit**

```bash
git add schemas/strategy_suggestions.py tests/test_strategy_suggestions.py
git commit -m "feat: add strategy suggestion schemas with 4-tier refinement model"
```

---

## Task 2: Weekly Metrics Pipeline — `build_weekly_metrics.py`

Aggregates 7 days of daily curated data into weekly summaries, week-over-week comparisons, process quality trends, regime performance trends, filter summaries, and correlation summaries.

**Files:**
- Create: `skills/build_weekly_metrics.py`
- Test: `tests/test_weekly_metrics_pipeline.py`

**Step 1: Write the failing tests**

```python
# tests/test_weekly_metrics_pipeline.py
"""Tests for the weekly metrics aggregation pipeline."""
import json
from pathlib import Path

import pytest

from schemas.daily_metrics import BotDailySummary, RegimeAnalysis, FilterAnalysis, RootCauseSummary
from schemas.weekly_metrics import (
    BotWeeklySummary,
    WeeklySummary,
    WeekOverWeekComparison,
    ProcessQualityTrend,
    FilterWeeklySummary,
)
from skills.build_weekly_metrics import WeeklyMetricsBuilder


def _make_daily_summary(
    date: str, bot_id: str, net_pnl: float, total_trades: int = 10, **kwargs
) -> BotDailySummary:
    """Helper to create a BotDailySummary with sensible defaults."""
    wins = total_trades // 2 + (1 if net_pnl > 0 else 0)
    losses = total_trades - wins
    return BotDailySummary(
        date=date,
        bot_id=bot_id,
        total_trades=total_trades,
        win_count=wins,
        loss_count=losses,
        gross_pnl=net_pnl + 10.0,
        net_pnl=net_pnl,
        avg_win=abs(net_pnl) / max(wins, 1),
        avg_loss=-(abs(net_pnl) * 0.5) / max(losses, 1),
        avg_process_quality=kwargs.get("avg_process_quality", 75.0),
        missed_count=kwargs.get("missed_count", 2),
        missed_would_have_won=kwargs.get("missed_would_have_won", 1),
        error_count=kwargs.get("error_count", 0),
        uptime_pct=kwargs.get("uptime_pct", 100.0),
    )


_DATES = [
    "2026-02-23", "2026-02-24", "2026-02-25", "2026-02-26",
    "2026-02-27", "2026-02-28", "2026-03-01",
]


class TestWeeklyMetricsBuilder:
    def test_build_bot_weekly_summary(self):
        dailies = [_make_daily_summary(d, "bot1", 50.0) for d in _DATES]
        builder = WeeklyMetricsBuilder(
            week_start="2026-02-23",
            week_end="2026-03-01",
            bots=["bot1"],
        )
        result = builder.build_bot_summary("bot1", dailies)
        assert result.bot_id == "bot1"
        assert result.total_trades == 70  # 10 * 7
        assert result.net_pnl == 350.0  # 50 * 7
        assert len(result.daily_pnl) == 7

    def test_build_bot_summary_empty(self):
        builder = WeeklyMetricsBuilder(
            week_start="2026-02-23",
            week_end="2026-03-01",
            bots=["bot1"],
        )
        result = builder.build_bot_summary("bot1", [])
        assert result.total_trades == 0
        assert result.net_pnl == 0.0

    def test_build_portfolio_summary(self):
        bot1_dailies = [_make_daily_summary(d, "bot1", 50.0) for d in _DATES]
        bot2_dailies = [_make_daily_summary(d, "bot2", -20.0) for d in _DATES]
        builder = WeeklyMetricsBuilder(
            week_start="2026-02-23",
            week_end="2026-03-01",
            bots=["bot1", "bot2"],
        )
        result = builder.build_portfolio_summary(
            {"bot1": bot1_dailies, "bot2": bot2_dailies}
        )
        assert result.total_net_pnl == 210.0  # 350 - 140
        assert len(result.bot_summaries) == 2

    def test_week_over_week_comparison(self):
        builder = WeeklyMetricsBuilder(
            week_start="2026-02-23",
            week_end="2026-03-01",
            bots=["bot1"],
        )
        current = WeeklySummary(
            week_start="2026-02-23",
            week_end="2026-03-01",
            total_net_pnl=500.0,
            total_trades=60,
        )
        previous = WeeklySummary(
            week_start="2026-02-16",
            week_end="2026-02-22",
            total_net_pnl=400.0,
            total_trades=55,
        )
        wow = builder.compare_weeks(current, previous)
        assert wow.pnl_delta == 100.0
        assert wow.pnl_delta_pct == 25.0
        assert wow.trade_count_delta == 5

    def test_week_over_week_previous_zero_pnl(self):
        builder = WeeklyMetricsBuilder(
            week_start="2026-02-23",
            week_end="2026-03-01",
            bots=["bot1"],
        )
        current = WeeklySummary(
            week_start="2026-02-23", week_end="2026-03-01", total_net_pnl=500.0
        )
        previous = WeeklySummary(
            week_start="2026-02-16", week_end="2026-02-22", total_net_pnl=0.0
        )
        wow = builder.compare_weeks(current, previous)
        assert wow.pnl_delta == 500.0
        assert wow.pnl_delta_pct == 0.0  # cannot compute % from zero

    def test_process_quality_trend(self):
        builder = WeeklyMetricsBuilder(
            week_start="2026-02-23",
            week_end="2026-03-01",
            bots=["bot1"],
        )
        weekly_scores = [68.0, 72.0, 75.0, 80.0]
        root_causes = {"regime_mismatch": 12, "normal_loss": 25, "weak_signal": 5}
        trend = builder.compute_process_quality_trend(
            "bot1", weekly_scores, root_causes
        )
        assert trend.trend_direction == "improving"
        assert trend.current_avg == 80.0

    def test_process_quality_trend_degrading(self):
        builder = WeeklyMetricsBuilder(
            week_start="2026-02-23",
            week_end="2026-03-01",
            bots=["bot1"],
        )
        weekly_scores = [80.0, 75.0, 72.0, 68.0]
        trend = builder.compute_process_quality_trend("bot1", weekly_scores, {})
        assert trend.trend_direction == "degrading"

    def test_process_quality_trend_stable(self):
        builder = WeeklyMetricsBuilder(
            week_start="2026-02-23",
            week_end="2026-03-01",
            bots=["bot1"],
        )
        weekly_scores = [75.0, 76.0, 75.5, 75.0]
        trend = builder.compute_process_quality_trend("bot1", weekly_scores, {})
        assert trend.trend_direction == "stable"

    def test_filter_weekly_summary(self):
        builder = WeeklyMetricsBuilder(
            week_start="2026-02-23",
            week_end="2026-03-01",
            bots=["bot1"],
        )
        daily_filters = [
            FilterAnalysis(
                bot_id="bot1",
                date=d,
                filter_block_counts={"volatility_filter": 3},
                filter_saved_pnl={"volatility_filter": 50.0},
                filter_missed_pnl={"volatility_filter": 80.0},
            )
            for d in _DATES
        ]
        result = builder.build_filter_weekly_summary("bot1", daily_filters)
        vol = next(f for f in result if f.filter_name == "volatility_filter")
        assert vol.total_blocks == 21  # 3 * 7

    def test_write_weekly_curated(self, tmp_path: Path):
        builder = WeeklyMetricsBuilder(
            week_start="2026-02-23",
            week_end="2026-03-01",
            bots=["bot1"],
        )
        bot1_dailies = [_make_daily_summary(d, "bot1", 50.0) for d in _DATES]
        summary = builder.build_portfolio_summary({"bot1": bot1_dailies})
        output_dir = builder.write_weekly_curated(summary, tmp_path)

        assert (output_dir / "weekly_summary.json").exists()
        data = json.loads((output_dir / "weekly_summary.json").read_text())
        assert data["total_net_pnl"] == 350.0
```

**Step 2: Run test to verify it fails**

Run: `venv/Scripts/python -m pytest tests/test_weekly_metrics_pipeline.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'skills.build_weekly_metrics'`

**Step 3: Write minimal implementation**

```python
# skills/build_weekly_metrics.py
"""Weekly metrics aggregation — 7 daily summaries → weekly portfolio metrics.

Deterministic pipeline. No LLM calls. Produces weekly curated data that Claude
interprets for the weekly summary report.

Output directory: data/curated/weekly/<week_start>/
"""
from __future__ import annotations

import json
from pathlib import Path

from schemas.daily_metrics import BotDailySummary, FilterAnalysis
from schemas.weekly_metrics import (
    BotWeeklySummary,
    WeeklySummary,
    WeekOverWeekComparison,
    ProcessQualityTrend,
    FilterWeeklySummary,
)


class WeeklyMetricsBuilder:
    """Aggregates daily curated data into weekly metrics."""

    def __init__(self, week_start: str, week_end: str, bots: list[str]) -> None:
        self.week_start = week_start
        self.week_end = week_end
        self.bots = bots

    def build_bot_summary(
        self, bot_id: str, dailies: list[BotDailySummary]
    ) -> BotWeeklySummary:
        """Aggregate daily summaries into a single weekly summary for one bot."""
        if not dailies:
            return BotWeeklySummary(
                week_start=self.week_start, week_end=self.week_end, bot_id=bot_id
            )

        total_trades = sum(d.total_trades for d in dailies)
        win_count = sum(d.win_count for d in dailies)
        loss_count = sum(d.loss_count for d in dailies)
        gross_pnl = sum(d.gross_pnl for d in dailies)
        net_pnl = sum(d.net_pnl for d in dailies)
        daily_pnl = {d.date: d.net_pnl for d in dailies}

        # Weighted averages
        wins_with_avg = [(d.avg_win, d.win_count) for d in dailies if d.win_count > 0]
        losses_with_avg = [(d.avg_loss, d.loss_count) for d in dailies if d.loss_count > 0]
        total_win_weight = sum(w for _, w in wins_with_avg)
        total_loss_weight = sum(w for _, w in losses_with_avg)
        avg_win = (
            sum(a * w for a, w in wins_with_avg) / total_win_weight
            if total_win_weight > 0
            else 0.0
        )
        avg_loss = (
            sum(a * w for a, w in losses_with_avg) / total_loss_weight
            if total_loss_weight > 0
            else 0.0
        )

        avg_pq = sum(d.avg_process_quality for d in dailies) / len(dailies)
        max_dd = max(d.max_drawdown_pct for d in dailies)
        missed_count = sum(d.missed_count for d in dailies)
        missed_would_have_won = sum(d.missed_would_have_won for d in dailies)
        error_count = sum(d.error_count for d in dailies)
        avg_uptime = sum(d.uptime_pct for d in dailies) / len(dailies)

        return BotWeeklySummary(
            week_start=self.week_start,
            week_end=self.week_end,
            bot_id=bot_id,
            total_trades=total_trades,
            win_count=win_count,
            loss_count=loss_count,
            gross_pnl=gross_pnl,
            net_pnl=net_pnl,
            max_drawdown_pct=max_dd,
            avg_win=avg_win,
            avg_loss=avg_loss,
            avg_process_quality=avg_pq,
            missed_count=missed_count,
            missed_would_have_won=missed_would_have_won,
            error_count=error_count,
            avg_uptime_pct=avg_uptime,
            daily_pnl=daily_pnl,
        )

    def build_portfolio_summary(
        self, dailies_by_bot: dict[str, list[BotDailySummary]]
    ) -> WeeklySummary:
        """Aggregate all bots into a portfolio-level weekly summary."""
        bot_summaries = {}
        for bot_id, dailies in dailies_by_bot.items():
            bot_summaries[bot_id] = self.build_bot_summary(bot_id, dailies)

        total_net = sum(s.net_pnl for s in bot_summaries.values())
        total_gross = sum(s.gross_pnl for s in bot_summaries.values())
        total_trades = sum(s.total_trades for s in bot_summaries.values())

        return WeeklySummary(
            week_start=self.week_start,
            week_end=self.week_end,
            bot_summaries=bot_summaries,
            total_net_pnl=total_net,
            total_gross_pnl=total_gross,
            total_trades=total_trades,
        )

    def compare_weeks(
        self, current: WeeklySummary, previous: WeeklySummary
    ) -> WeekOverWeekComparison:
        """Compute week-over-week deltas."""
        pnl_delta = current.total_net_pnl - previous.total_net_pnl
        if previous.total_net_pnl != 0:
            pnl_delta_pct = (pnl_delta / abs(previous.total_net_pnl)) * 100.0
        else:
            pnl_delta_pct = 0.0

        trade_delta = current.total_trades - previous.total_trades

        return WeekOverWeekComparison(
            current_week=current.week_start,
            previous_week=previous.week_start,
            pnl_delta=pnl_delta,
            pnl_delta_pct=pnl_delta_pct,
            trade_count_delta=trade_delta,
        )

    def compute_process_quality_trend(
        self,
        bot_id: str,
        weekly_avg_scores: list[float],
        root_cause_distribution: dict[str, int],
    ) -> ProcessQualityTrend:
        """Determine if process quality is improving, degrading, or stable."""
        current = weekly_avg_scores[-1] if weekly_avg_scores else 0.0

        if len(weekly_avg_scores) >= 2:
            first_half = weekly_avg_scores[: len(weekly_avg_scores) // 2]
            second_half = weekly_avg_scores[len(weekly_avg_scores) // 2 :]
            first_avg = sum(first_half) / len(first_half)
            second_avg = sum(second_half) / len(second_half)
            delta = second_avg - first_avg
            if delta > 2.0:
                direction = "improving"
            elif delta < -2.0:
                direction = "degrading"
            else:
                direction = "stable"
        else:
            direction = "stable"

        return ProcessQualityTrend(
            bot_id=bot_id,
            weekly_avg_scores=weekly_avg_scores,
            current_avg=current,
            trend_direction=direction,
            most_frequent_root_causes=root_cause_distribution,
        )

    def build_filter_weekly_summary(
        self, bot_id: str, daily_filters: list[FilterAnalysis]
    ) -> list[FilterWeeklySummary]:
        """Aggregate 7 days of filter analysis into weekly filter summaries."""
        all_filters: dict[str, dict] = {}

        for day in daily_filters:
            for filter_name, count in day.filter_block_counts.items():
                if filter_name not in all_filters:
                    all_filters[filter_name] = {
                        "total_blocks": 0,
                        "saved_pnl": 0.0,
                        "missed_pnl": 0.0,
                    }
                all_filters[filter_name]["total_blocks"] += count
                all_filters[filter_name]["saved_pnl"] += day.filter_saved_pnl.get(
                    filter_name, 0.0
                )
                all_filters[filter_name]["missed_pnl"] += day.filter_missed_pnl.get(
                    filter_name, 0.0
                )

        return [
            FilterWeeklySummary(
                bot_id=bot_id,
                filter_name=name,
                total_blocks=data["total_blocks"],
                net_impact_pnl=data["saved_pnl"] - data["missed_pnl"],
            )
            for name, data in all_filters.items()
        ]

    def write_weekly_curated(
        self, summary: WeeklySummary, base_dir: Path
    ) -> Path:
        """Write weekly curated data to base_dir/weekly/<week_start>/."""
        output_dir = base_dir / "weekly" / self.week_start
        output_dir.mkdir(parents=True, exist_ok=True)

        self._write_json(
            output_dir / "weekly_summary.json",
            summary.model_dump(mode="json"),
        )

        return output_dir

    def _write_json(self, path: Path, data: dict | list) -> None:
        path.write_text(json.dumps(data, indent=2, default=str))
```

**Step 4: Run test to verify it passes**

Run: `venv/Scripts/python -m pytest tests/test_weekly_metrics_pipeline.py -v`
Expected: All 11 tests PASS

**Step 5: Commit**

```bash
git add skills/build_weekly_metrics.py tests/test_weekly_metrics_pipeline.py
git commit -m "feat: add weekly metrics aggregation pipeline"
```

---

## Task 3: Strategy Refinement Engine

The engine analyzes weekly data and produces 4-tier strategy suggestions deterministically. Claude later interprets these for the weekly report, but the scoring and classification are rules-based.

**Files:**
- Create: `analysis/strategy_engine.py`
- Test: `tests/test_strategy_engine.py`

**Step 1: Write the failing tests**

```python
# tests/test_strategy_engine.py
"""Tests for the 4-tier strategy refinement engine."""
from schemas.strategy_suggestions import SuggestionTier, StrategySuggestion, RefinementReport
from schemas.weekly_metrics import (
    BotWeeklySummary,
    FilterWeeklySummary,
    ProcessQualityTrend,
    RegimePerformanceTrend,
)
from analysis.strategy_engine import StrategyEngine


class TestParameterSuggestions:
    def test_detects_tight_stop_loss(self):
        """If a bot's avg_loss is small relative to avg_win (< 0.3 ratio),
        stops may be too tight, cutting winners short."""
        engine = StrategyEngine(week_start="2026-02-23", week_end="2026-03-01")
        summary = BotWeeklySummary(
            week_start="2026-02-23",
            week_end="2026-03-01",
            bot_id="bot1",
            total_trades=50,
            win_count=20,
            loss_count=30,
            net_pnl=-100.0,
            avg_win=200.0,
            avg_loss=-30.0,  # losses are tiny → stops too tight
        )
        suggestions = engine.analyze_parameters(summary)
        assert any(
            s.tier == SuggestionTier.PARAMETER and "stop" in s.title.lower()
            for s in suggestions
        )

    def test_no_suggestion_when_balanced(self):
        engine = StrategyEngine(week_start="2026-02-23", week_end="2026-03-01")
        summary = BotWeeklySummary(
            week_start="2026-02-23",
            week_end="2026-03-01",
            bot_id="bot1",
            total_trades=50,
            win_count=28,
            loss_count=22,
            net_pnl=300.0,
            avg_win=80.0,
            avg_loss=-50.0,
        )
        suggestions = engine.analyze_parameters(summary)
        stop_suggestions = [s for s in suggestions if "stop" in s.title.lower()]
        assert len(stop_suggestions) == 0


class TestFilterSuggestions:
    def test_detects_costly_filter(self):
        """If a filter's net impact is negative (cost > saved), suggest relaxing."""
        engine = StrategyEngine(week_start="2026-02-23", week_end="2026-03-01")
        filter_summary = FilterWeeklySummary(
            bot_id="bot3",
            filter_name="volume_filter",
            total_blocks=47,
            blocks_that_would_have_won=31,
            blocks_that_would_have_lost=16,
            net_impact_pnl=-180.0,
        )
        suggestions = engine.analyze_filters("bot3", [filter_summary])
        assert len(suggestions) == 1
        assert suggestions[0].tier == SuggestionTier.FILTER
        assert "volume_filter" in suggestions[0].title

    def test_no_suggestion_for_beneficial_filter(self):
        engine = StrategyEngine(week_start="2026-02-23", week_end="2026-03-01")
        filter_summary = FilterWeeklySummary(
            bot_id="bot1",
            filter_name="spread_filter",
            total_blocks=10,
            net_impact_pnl=200.0,  # filter saves more than it costs
        )
        suggestions = engine.analyze_filters("bot1", [filter_summary])
        assert len(suggestions) == 0


class TestStrategyVariantSuggestions:
    def test_detects_regime_mismatch(self):
        """If a bot loses consistently in one regime, suggest a regime gate."""
        engine = StrategyEngine(week_start="2026-02-23", week_end="2026-03-01")
        trend = RegimePerformanceTrend(
            bot_id="bot1",
            regime="ranging",
            weekly_pnl=[-50.0, -80.0, -40.0, -60.0],  # consistent losses
            weekly_win_rate=[0.3, 0.25, 0.35, 0.28],
            weekly_trade_count=[10, 12, 8, 11],
        )
        suggestions = engine.analyze_regime_fit("bot1", [trend])
        assert len(suggestions) >= 1
        assert suggestions[0].tier == SuggestionTier.STRATEGY_VARIANT
        assert suggestions[0].requires_human_judgment is True

    def test_no_suggestion_for_profitable_regime(self):
        engine = StrategyEngine(week_start="2026-02-23", week_end="2026-03-01")
        trend = RegimePerformanceTrend(
            bot_id="bot1",
            regime="trending_up",
            weekly_pnl=[100.0, 120.0, 80.0, 150.0],
            weekly_win_rate=[0.7, 0.75, 0.65, 0.8],
            weekly_trade_count=[10, 12, 8, 11],
        )
        suggestions = engine.analyze_regime_fit("bot1", [trend])
        assert len(suggestions) == 0


class TestRefinementReport:
    def test_builds_full_report(self):
        engine = StrategyEngine(week_start="2026-02-23", week_end="2026-03-01")
        summary = BotWeeklySummary(
            week_start="2026-02-23",
            week_end="2026-03-01",
            bot_id="bot1",
            total_trades=50,
            win_count=20,
            loss_count=30,
            net_pnl=-100.0,
            avg_win=200.0,
            avg_loss=-30.0,
        )
        filter_summaries = [
            FilterWeeklySummary(
                bot_id="bot1",
                filter_name="volume_filter",
                total_blocks=20,
                net_impact_pnl=-100.0,
            )
        ]
        regime_trends = [
            RegimePerformanceTrend(
                bot_id="bot1",
                regime="ranging",
                weekly_pnl=[-50.0, -80.0, -40.0, -60.0],
                weekly_win_rate=[0.3, 0.25, 0.35, 0.28],
                weekly_trade_count=[10, 12, 8, 11],
            )
        ]
        report = engine.build_report(
            bot_summaries={"bot1": summary},
            filter_summaries={"bot1": filter_summaries},
            regime_trends={"bot1": regime_trends},
        )
        assert isinstance(report, RefinementReport)
        assert len(report.suggestions) > 0
```

**Step 2: Run test to verify it fails**

Run: `venv/Scripts/python -m pytest tests/test_strategy_engine.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'analysis.strategy_engine'`

**Step 3: Write minimal implementation**

```python
# analysis/strategy_engine.py
"""Strategy refinement engine — deterministic 4-tier suggestion generator.

Analyzes weekly metrics and produces strategy suggestions. All rules-based,
no LLM calls. Claude interprets these in the weekly report prompt.

Tier 1 (Parameter): e.g. stop-loss too tight, threshold misaligned
Tier 2 (Filter): filter cost exceeds benefit over the week
Tier 3 (Strategy Variant): regime mismatch → suggest regime gate
Tier 4 (Hypothesis): reserved for Claude to synthesize in the weekly report
"""
from __future__ import annotations

from schemas.strategy_suggestions import (
    SuggestionTier,
    StrategySuggestion,
    RefinementReport,
)
from schemas.weekly_metrics import (
    BotWeeklySummary,
    FilterWeeklySummary,
    RegimePerformanceTrend,
)


class StrategyEngine:
    """Deterministic strategy suggestion generator."""

    def __init__(
        self,
        week_start: str,
        week_end: str,
        tight_stop_ratio: float = 0.3,
        filter_cost_threshold: float = 0.0,
        regime_loss_threshold: float = 0.0,
        regime_min_weeks: int = 3,
    ) -> None:
        self.week_start = week_start
        self.week_end = week_end
        self.tight_stop_ratio = tight_stop_ratio
        self.filter_cost_threshold = filter_cost_threshold
        self.regime_loss_threshold = regime_loss_threshold
        self.regime_min_weeks = regime_min_weeks

    def analyze_parameters(
        self, summary: BotWeeklySummary
    ) -> list[StrategySuggestion]:
        """Tier 1: Detect parameter misalignment from weekly stats."""
        suggestions: list[StrategySuggestion] = []

        # Tight stop detection: avg_loss is small relative to avg_win
        if summary.avg_win > 0 and summary.avg_loss != 0:
            loss_win_ratio = abs(summary.avg_loss) / summary.avg_win
            if loss_win_ratio < self.tight_stop_ratio:
                suggestions.append(
                    StrategySuggestion(
                        tier=SuggestionTier.PARAMETER,
                        bot_id=summary.bot_id,
                        title=f"Stop loss may be too tight on {summary.bot_id}",
                        description=(
                            f"Avg loss (${abs(summary.avg_loss):.0f}) is only "
                            f"{loss_win_ratio:.0%} of avg win (${summary.avg_win:.0f}). "
                            f"Stops may be clipping winners too early. "
                            f"Consider widening stop by 0.5× ATR."
                        ),
                        current_value=f"loss/win_ratio={loss_win_ratio:.2f}",
                        suggested_value="loss/win_ratio>=0.3",
                        evidence_days=7,
                        confidence=0.7,
                    )
                )

        return suggestions

    def analyze_filters(
        self, bot_id: str, filter_summaries: list[FilterWeeklySummary]
    ) -> list[StrategySuggestion]:
        """Tier 2: Detect filters that cost more than they save."""
        suggestions: list[StrategySuggestion] = []

        for f in filter_summaries:
            if f.net_impact_pnl < self.filter_cost_threshold:
                suggestions.append(
                    StrategySuggestion(
                        tier=SuggestionTier.FILTER,
                        bot_id=bot_id,
                        title=f"Relax {f.filter_name} on {bot_id}",
                        description=(
                            f"{f.filter_name} blocked {f.total_blocks} entries this week. "
                            f"Net impact: ${f.net_impact_pnl:.0f} (cost exceeds benefit). "
                            f"Consider relaxing the threshold."
                        ),
                        evidence_days=7,
                        estimated_impact_pnl=abs(f.net_impact_pnl),
                        confidence=max(0.0, min(1.0, f.confidence)),
                    )
                )

        return suggestions

    def analyze_regime_fit(
        self, bot_id: str, regime_trends: list[RegimePerformanceTrend]
    ) -> list[StrategySuggestion]:
        """Tier 3: Detect consistent losses in a specific regime."""
        suggestions: list[StrategySuggestion] = []

        for trend in regime_trends:
            if len(trend.weekly_pnl) < self.regime_min_weeks:
                continue

            # All weeks negative in this regime
            losing_weeks = sum(1 for pnl in trend.weekly_pnl if pnl < self.regime_loss_threshold)
            if losing_weeks >= self.regime_min_weeks:
                total_loss = sum(pnl for pnl in trend.weekly_pnl if pnl < 0)
                suggestions.append(
                    StrategySuggestion(
                        tier=SuggestionTier.STRATEGY_VARIANT,
                        bot_id=bot_id,
                        title=f"Add regime gate for {trend.regime} on {bot_id}",
                        description=(
                            f"{bot_id} lost in {trend.regime} regime for "
                            f"{losing_weeks}/{len(trend.weekly_pnl)} weeks "
                            f"(total: ${total_loss:.0f}). "
                            f"Consider adding a regime gate to disable trading "
                            f"in {trend.regime} conditions."
                        ),
                        requires_human_judgment=True,
                        evidence_days=len(trend.weekly_pnl) * 7,
                        confidence=0.5,
                    )
                )

        return suggestions

    def build_report(
        self,
        bot_summaries: dict[str, BotWeeklySummary],
        filter_summaries: dict[str, list[FilterWeeklySummary]] | None = None,
        regime_trends: dict[str, list[RegimePerformanceTrend]] | None = None,
    ) -> RefinementReport:
        """Build the complete refinement report across all bots."""
        all_suggestions: list[StrategySuggestion] = []

        for bot_id, summary in bot_summaries.items():
            all_suggestions.extend(self.analyze_parameters(summary))

            if filter_summaries and bot_id in filter_summaries:
                all_suggestions.extend(
                    self.analyze_filters(bot_id, filter_summaries[bot_id])
                )

            if regime_trends and bot_id in regime_trends:
                all_suggestions.extend(
                    self.analyze_regime_fit(bot_id, regime_trends[bot_id])
                )

        return RefinementReport(
            week_start=self.week_start,
            week_end=self.week_end,
            suggestions=all_suggestions,
        )
```

**Step 4: Run test to verify it passes**

Run: `venv/Scripts/python -m pytest tests/test_strategy_engine.py -v`
Expected: All 7 tests PASS

**Step 5: Commit**

```bash
git add analysis/strategy_engine.py tests/test_strategy_engine.py
git commit -m "feat: add 4-tier strategy refinement engine"
```

---

## Task 4: Weekly Prompt Assembler

Builds the context package for the weekly analysis Claude invocation, similar to the daily prompt assembler (`analysis/prompt_assembler.py`) but with weekly-specific data and instructions.

**Files:**
- Create: `analysis/weekly_prompt_assembler.py`
- Test: `tests/test_weekly_prompt_assembler.py`

**Step 1: Write the failing tests**

```python
# tests/test_weekly_prompt_assembler.py
"""Tests for the weekly prompt assembler."""
import json
from pathlib import Path

import pytest

from analysis.weekly_prompt_assembler import WeeklyPromptAssembler


@pytest.fixture
def setup_dirs(tmp_path: Path):
    """Create directory structure with weekly curated data and daily reports."""
    curated = tmp_path / "curated"
    memory = tmp_path / "memory"
    runs = tmp_path / "runs"

    # Weekly curated data
    weekly_dir = curated / "weekly" / "2026-02-23"
    weekly_dir.mkdir(parents=True)
    (weekly_dir / "weekly_summary.json").write_text(
        json.dumps({"week_start": "2026-02-23", "total_net_pnl": 500.0})
    )
    (weekly_dir / "refinement_report.json").write_text(
        json.dumps({"suggestions": [{"title": "Adjust RSI"}]})
    )
    (weekly_dir / "week_over_week.json").write_text(
        json.dumps({"pnl_delta": 100.0})
    )

    # 7 daily reports (just create stubs)
    for i in range(23, 30):
        date = f"2026-02-{i:02d}"
        run_dir = runs / date / "daily-report"
        run_dir.mkdir(parents=True)
        (run_dir / "daily_report.md").write_text(f"# Daily Report {date}\nAll good.")

    # Portfolio risk cards (7 days)
    for i in range(23, 30):
        date = f"2026-02-{i:02d}"
        date_dir = curated / date
        date_dir.mkdir(parents=True)
        (date_dir / "portfolio_risk_card.json").write_text(
            json.dumps({"date": date, "concentration_score": 30.0})
        )

    # Memory policies
    policy_dir = memory / "policies" / "v1"
    policy_dir.mkdir(parents=True)
    (policy_dir / "agents.md").write_text("You are the trading assistant.")
    (policy_dir / "trading_rules.md").write_text("Max drawdown 15%.")
    (policy_dir / "soul.md").write_text("Conservative approach.")

    # Corrections
    findings_dir = memory / "findings"
    findings_dir.mkdir(parents=True)
    (findings_dir / "corrections.jsonl").write_text(
        json.dumps({"correction_type": "positive_reinforcement", "raw_text": "good catch"})
        + "\n"
    )

    return curated, memory, runs


class TestWeeklyPromptAssembler:
    def test_assembles_complete_package(self, setup_dirs):
        curated, memory, runs = setup_dirs
        assembler = WeeklyPromptAssembler(
            week_start="2026-02-23",
            week_end="2026-03-01",
            bots=["bot1", "bot2"],
            curated_dir=curated,
            memory_dir=memory,
            runs_dir=runs,
        )
        package = assembler.assemble()

        assert "system_prompt" in package
        assert "task_prompt" in package
        assert "data" in package
        assert "instructions" in package
        assert "corrections" in package
        assert "context_files" in package

    def test_system_prompt_includes_policies(self, setup_dirs):
        curated, memory, runs = setup_dirs
        assembler = WeeklyPromptAssembler(
            week_start="2026-02-23",
            week_end="2026-03-01",
            bots=["bot1"],
            curated_dir=curated,
            memory_dir=memory,
            runs_dir=runs,
        )
        package = assembler.assemble()
        assert "trading assistant" in package["system_prompt"]
        assert "Max drawdown" in package["system_prompt"]

    def test_data_includes_weekly_summary(self, setup_dirs):
        curated, memory, runs = setup_dirs
        assembler = WeeklyPromptAssembler(
            week_start="2026-02-23",
            week_end="2026-03-01",
            bots=["bot1"],
            curated_dir=curated,
            memory_dir=memory,
            runs_dir=runs,
        )
        package = assembler.assemble()
        assert "weekly_summary" in package["data"]
        assert package["data"]["weekly_summary"]["total_net_pnl"] == 500.0

    def test_data_includes_daily_reports(self, setup_dirs):
        curated, memory, runs = setup_dirs
        assembler = WeeklyPromptAssembler(
            week_start="2026-02-23",
            week_end="2026-03-01",
            bots=["bot1"],
            curated_dir=curated,
            memory_dir=memory,
            runs_dir=runs,
        )
        package = assembler.assemble()
        assert "daily_reports" in package["data"]
        assert len(package["data"]["daily_reports"]) == 7

    def test_data_includes_risk_cards(self, setup_dirs):
        curated, memory, runs = setup_dirs
        assembler = WeeklyPromptAssembler(
            week_start="2026-02-23",
            week_end="2026-03-01",
            bots=["bot1"],
            curated_dir=curated,
            memory_dir=memory,
            runs_dir=runs,
        )
        package = assembler.assemble()
        assert "portfolio_risk_cards" in package["data"]
        assert len(package["data"]["portfolio_risk_cards"]) == 7

    def test_task_prompt_mentions_weekly(self, setup_dirs):
        curated, memory, runs = setup_dirs
        assembler = WeeklyPromptAssembler(
            week_start="2026-02-23",
            week_end="2026-03-01",
            bots=["bot1"],
            curated_dir=curated,
            memory_dir=memory,
            runs_dir=runs,
        )
        package = assembler.assemble()
        assert "weekly" in package["task_prompt"].lower()

    def test_corrections_loaded(self, setup_dirs):
        curated, memory, runs = setup_dirs
        assembler = WeeklyPromptAssembler(
            week_start="2026-02-23",
            week_end="2026-03-01",
            bots=["bot1"],
            curated_dir=curated,
            memory_dir=memory,
            runs_dir=runs,
        )
        package = assembler.assemble()
        assert len(package["corrections"]) == 1
```

**Step 2: Run test to verify it fails**

Run: `venv/Scripts/python -m pytest tests/test_weekly_prompt_assembler.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'analysis.weekly_prompt_assembler'`

**Step 3: Write minimal implementation**

```python
# analysis/weekly_prompt_assembler.py
"""Weekly prompt assembler — builds context package for weekly analysis Claude invocation.

Similar to the daily prompt assembler (analysis/prompt_assembler.py) but with
weekly-specific data: 7 daily reports, weekly summary, week-over-week comparisons,
strategy refinement report, portfolio risk card series, and corrections.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

_WEEKLY_INSTRUCTIONS = """\
1. Trend analysis: Is performance improving or degrading? By bot? By regime?
2. Pattern recognition: Which signal+regime combos are consistently profitable?
3. Filter tuning signals: Across the week, which filters cost more than they saved?
4. Correlation analysis: How correlated are your bots? Is diversification working?
5. Process quality trends: Is average process quality improving? Which root causes most frequent?
6. Drawdown context: Was it a single event or systemic?
7. Week-over-week comparison: This week vs. last 4 weeks
8. Strategy refinement: Review the refinement report and highlight top suggestions
9. Actionable items: Max 5 specific, testable suggestions ranked by confidence
10. Output: weekly_report.md"""


class WeeklyPromptAssembler:
    """Assembles the full context package for a weekly analysis agent invocation."""

    def __init__(
        self,
        week_start: str,
        week_end: str,
        bots: list[str],
        curated_dir: Path,
        memory_dir: Path,
        runs_dir: Path,
    ) -> None:
        self.week_start = week_start
        self.week_end = week_end
        self.bots = bots
        self.curated_dir = curated_dir
        self.memory_dir = memory_dir
        self.runs_dir = runs_dir

    def assemble(self) -> dict:
        """Build the complete weekly prompt package."""
        return {
            "system_prompt": self._build_system_prompt(),
            "task_prompt": self._build_task_prompt(),
            "data": self._load_data(),
            "instructions": _WEEKLY_INSTRUCTIONS,
            "corrections": self._load_corrections(),
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
        bot_list = ", ".join(self.bots)
        return (
            f"Produce the weekly summary for {self.week_start} to {self.week_end} "
            f"covering all bots: {bot_list}.\n"
            f"Use the weekly summary data, 7 daily reports, portfolio risk cards, "
            f"and strategy refinement report provided. Follow the instructions exactly."
        )

    def _load_data(self) -> dict:
        data: dict = {}

        # Weekly summary
        weekly_dir = self.curated_dir / "weekly" / self.week_start
        summary_path = weekly_dir / "weekly_summary.json"
        if summary_path.exists():
            data["weekly_summary"] = json.loads(summary_path.read_text())

        # Refinement report
        refinement_path = weekly_dir / "refinement_report.json"
        if refinement_path.exists():
            data["refinement_report"] = json.loads(refinement_path.read_text())

        # Week-over-week
        wow_path = weekly_dir / "week_over_week.json"
        if wow_path.exists():
            data["week_over_week"] = json.loads(wow_path.read_text())

        # 7 daily reports
        data["daily_reports"] = self._load_daily_reports()

        # 7 portfolio risk cards
        data["portfolio_risk_cards"] = self._load_risk_cards()

        return data

    def _load_daily_reports(self) -> list[dict]:
        reports: list[dict] = []
        for date_str in self._week_dates():
            run_dir = self.runs_dir / date_str / "daily-report"
            report_path = run_dir / "daily_report.md"
            if report_path.exists():
                reports.append({
                    "date": date_str,
                    "content": report_path.read_text(),
                })
        return reports

    def _load_risk_cards(self) -> list[dict]:
        cards: list[dict] = []
        for date_str in self._week_dates():
            card_path = self.curated_dir / date_str / "portfolio_risk_card.json"
            if card_path.exists():
                cards.append(json.loads(card_path.read_text()))
        return cards

    def _load_corrections(self) -> list[dict]:
        corrections_path = self.memory_dir / "findings" / "corrections.jsonl"
        if not corrections_path.exists():
            return []
        corrections: list[dict] = []
        for line in corrections_path.read_text().strip().splitlines():
            if line.strip():
                corrections.append(json.loads(line))
        return corrections

    def _list_context_files(self) -> list[str]:
        files: list[str] = []
        weekly_dir = self.curated_dir / "weekly" / self.week_start
        for name in ["weekly_summary.json", "refinement_report.json", "week_over_week.json"]:
            path = weekly_dir / name
            if path.exists():
                files.append(str(path))

        policy_dir = self.memory_dir / "policies" / "v1"
        for name in ["agents.md", "trading_rules.md", "soul.md"]:
            path = policy_dir / name
            if path.exists():
                files.append(str(path))

        return files

    def _week_dates(self) -> list[str]:
        """Generate the 7 date strings for this week."""
        start = datetime.strptime(self.week_start, "%Y-%m-%d")
        return [(start + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)]
```

**Step 4: Run test to verify it passes**

Run: `venv/Scripts/python -m pytest tests/test_weekly_prompt_assembler.py -v`
Expected: All 7 tests PASS

**Step 5: Commit**

```bash
git add analysis/weekly_prompt_assembler.py tests/test_weekly_prompt_assembler.py
git commit -m "feat: add weekly prompt assembler for Claude analysis context"
```

---

## Task 5: Golden Days Test Fixture Structure

Create the golden days directory structure and a README explaining how to add golden days. Also create a fixture loader that reads golden day data for use in regression tests.

**Files:**
- Create: `tests/golden_days/README.md`
- Create: `tests/golden_days/__init__.py`
- Create: `tests/golden_days/loader.py`
- Test: `tests/test_regression_suite.py` (partial — loader tests only)

**Step 1: Write the failing test**

```python
# tests/test_regression_suite.py
"""Tests for the regression suite — golden day loader + regression checks."""
import json
from pathlib import Path

import pytest

from tests.golden_days.loader import GoldenDay, load_golden_days


@pytest.fixture
def golden_day_dir(tmp_path: Path) -> Path:
    """Create a single golden day with known data."""
    day_dir = tmp_path / "2026-02-15"
    day_dir.mkdir()

    # Raw events
    raw_dir = day_dir / "raw_events"
    raw_dir.mkdir()
    (raw_dir / "trades.json").write_text(json.dumps([
        {
            "trade_id": "t1", "bot_id": "bot1", "pair": "BTCUSDT",
            "side": "LONG", "pnl": 200.0, "pnl_pct": 2.0,
            "entry_price": 50000.0, "exit_price": 51000.0,
            "position_size": 0.1, "entry_time": "2026-02-15T10:00:00Z",
            "exit_time": "2026-02-15T14:00:00Z",
            "entry_signal": "EMA cross", "exit_reason": "TAKE_PROFIT",
            "market_regime": "trending_up",
            "process_quality_score": 90, "root_causes": ["normal_win"],
        },
        {
            "trade_id": "t2", "bot_id": "bot1", "pair": "ETHUSDT",
            "side": "SHORT", "pnl": -80.0, "pnl_pct": -1.5,
            "entry_price": 3000.0, "exit_price": 3045.0,
            "position_size": 0.5, "entry_time": "2026-02-15T11:00:00Z",
            "exit_time": "2026-02-15T13:00:00Z",
            "entry_signal": "RSI divergence", "exit_reason": "STOP_LOSS",
            "market_regime": "ranging",
            "process_quality_score": 45, "root_causes": ["regime_mismatch"],
        },
    ]))
    (raw_dir / "missed.json").write_text(json.dumps([
        {
            "bot_id": "bot1", "pair": "BTCUSDT", "signal": "Volume breakout",
            "blocked_by": "volatility_filter", "hypothetical_entry": 50500.0,
            "outcome_24h": 400.0, "confidence": 0.7,
            "assumption_tags": ["mid_fill", "5bps_slippage"],
        },
    ]))

    # Expected classifications
    (day_dir / "expected_classifications.json").write_text(json.dumps({
        "t1": {"root_causes": ["normal_win"], "process_quality_score": 90},
        "t2": {"root_causes": ["regime_mismatch"], "process_quality_score": 45},
    }))

    # Expected curated metrics
    expected_dir = day_dir / "expected_curated"
    expected_dir.mkdir()
    (expected_dir / "summary.json").write_text(json.dumps({
        "bot_id": "bot1", "total_trades": 2, "win_count": 1,
        "loss_count": 1, "net_pnl": 120.0,
    }))

    # Human feedback
    (day_dir / "human_feedback.json").write_text(json.dumps([
        {"correction_type": "positive_reinforcement", "raw_text": "Good analysis"},
    ]))

    # Reference report
    (day_dir / "reference_report.md").write_text(
        "# Daily Report 2026-02-15\nBot1 had a good day. Process failure on t2."
    )

    # Metadata
    (day_dir / "metadata.json").write_text(json.dumps({
        "date": "2026-02-15",
        "bots": ["bot1"],
        "top_anomaly": "volume_spike",
        "biggest_loss_driver": "regime_mismatch",
        "crowding_alerts": [],
    }))

    return tmp_path


class TestGoldenDayLoader:
    def test_loads_golden_day(self, golden_day_dir: Path):
        days = load_golden_days(golden_day_dir)
        assert len(days) == 1

    def test_golden_day_has_trades(self, golden_day_dir: Path):
        days = load_golden_days(golden_day_dir)
        day = days[0]
        assert len(day.trades) == 2
        assert day.trades[0]["trade_id"] == "t1"

    def test_golden_day_has_missed(self, golden_day_dir: Path):
        days = load_golden_days(golden_day_dir)
        day = days[0]
        assert len(day.missed) == 1

    def test_golden_day_has_expected_classifications(self, golden_day_dir: Path):
        days = load_golden_days(golden_day_dir)
        day = days[0]
        assert "t1" in day.expected_classifications
        assert day.expected_classifications["t2"]["root_causes"] == ["regime_mismatch"]

    def test_golden_day_has_metadata(self, golden_day_dir: Path):
        days = load_golden_days(golden_day_dir)
        day = days[0]
        assert day.date == "2026-02-15"
        assert day.top_anomaly == "volume_spike"
        assert day.biggest_loss_driver == "regime_mismatch"

    def test_golden_day_has_reference_report(self, golden_day_dir: Path):
        days = load_golden_days(golden_day_dir)
        day = days[0]
        assert "Process failure on t2" in day.reference_report
```

**Step 2: Run test to verify it fails**

Run: `venv/Scripts/python -m pytest tests/test_regression_suite.py::TestGoldenDayLoader -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tests.golden_days'`

**Step 3: Write the golden day loader**

```python
# tests/golden_days/__init__.py
```

```python
# tests/golden_days/loader.py
"""Golden day loader — reads frozen test datasets for regression testing.

Each golden day directory has a fixed structure:
  <date>/
    raw_events/
      trades.json              # list of trade event dicts
      missed.json              # list of missed opportunity dicts
    expected_classifications.json  # trade_id → {root_causes, process_quality_score}
    expected_curated/
      summary.json             # what the pipeline should produce
    human_feedback.json        # corrections from that day
    reference_report.md        # the report rated "good"
    metadata.json              # date, bots, top_anomaly, biggest_loss_driver, crowding_alerts
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class GoldenDay:
    """A frozen test dataset with known-good outcomes."""

    date: str
    bots: list[str]
    trades: list[dict]
    missed: list[dict]
    expected_classifications: dict[str, dict]
    expected_curated: dict[str, dict]  # filename → content
    human_feedback: list[dict]
    reference_report: str
    top_anomaly: str = ""
    biggest_loss_driver: str = ""
    crowding_alerts: list[str] = field(default_factory=list)


def load_golden_days(base_dir: Path) -> list[GoldenDay]:
    """Load all golden days from the base directory."""
    days: list[GoldenDay] = []

    for day_dir in sorted(base_dir.iterdir()):
        if not day_dir.is_dir():
            continue

        metadata_path = day_dir / "metadata.json"
        if not metadata_path.exists():
            continue

        metadata = json.loads(metadata_path.read_text())

        # Raw events
        raw_dir = day_dir / "raw_events"
        trades = json.loads((raw_dir / "trades.json").read_text()) if (raw_dir / "trades.json").exists() else []
        missed = json.loads((raw_dir / "missed.json").read_text()) if (raw_dir / "missed.json").exists() else []

        # Expected classifications
        class_path = day_dir / "expected_classifications.json"
        expected_classifications = json.loads(class_path.read_text()) if class_path.exists() else {}

        # Expected curated
        expected_curated: dict[str, dict] = {}
        curated_dir = day_dir / "expected_curated"
        if curated_dir.is_dir():
            for f in curated_dir.iterdir():
                if f.suffix == ".json":
                    expected_curated[f.name] = json.loads(f.read_text())

        # Human feedback
        feedback_path = day_dir / "human_feedback.json"
        human_feedback = json.loads(feedback_path.read_text()) if feedback_path.exists() else []

        # Reference report
        report_path = day_dir / "reference_report.md"
        reference_report = report_path.read_text() if report_path.exists() else ""

        days.append(GoldenDay(
            date=metadata["date"],
            bots=metadata.get("bots", []),
            trades=trades,
            missed=missed,
            expected_classifications=expected_classifications,
            expected_curated=expected_curated,
            human_feedback=human_feedback,
            reference_report=reference_report,
            top_anomaly=metadata.get("top_anomaly", ""),
            biggest_loss_driver=metadata.get("biggest_loss_driver", ""),
            crowding_alerts=metadata.get("crowding_alerts", []),
        ))

    return days
```

Now create the README:

```markdown
# Golden Days — Regression Test Data

## What is a golden day?

A frozen dataset from a specific trading day with known-good outcomes and human feedback.
Used to regression-test the data pipeline, classification engine, and report quality.

## Directory structure

```
tests/golden_days/
  2026-02-15/
    raw_events/
      trades.json              # list of trade event dicts (as emitted by bots)
      missed.json              # list of missed opportunity dicts
    expected_classifications.json  # trade_id → {root_causes, process_quality_score}
    expected_curated/
      summary.json             # what the pipeline should produce
    human_feedback.json        # your actual corrections from that day
    reference_report.md        # the report you rated "good"
    metadata.json              # date, bots, top_anomaly, biggest_loss_driver, crowding_alerts
```

## How to add a new golden day

1. Pick a day with interesting data (mix of wins, losses, process failures, missed opps)
2. Export the raw events from the event queue for that date
3. Run the pipeline and verify the curated output matches your expectations
4. Save your human feedback/corrections for that day
5. Rate the daily report — if it was "good", save it as reference_report.md
6. Fill in metadata.json with the top anomaly, biggest loss driver, and any crowding alerts
7. Commit the directory under tests/golden_days/

## How regression tests use this

- `test_classification_accuracy`: Run pipeline on raw_events, compare root causes to expected_classifications
- `test_metric_stability`: Compare pipeline output metrics to expected_curated (within 5% tolerance)
- `test_report_quality_heuristics`: Generate report, verify it mentions top anomaly, biggest loss driver, and all crowding alerts
```

**Step 4: Run test to verify it passes**

Run: `venv/Scripts/python -m pytest tests/test_regression_suite.py::TestGoldenDayLoader -v`
Expected: All 6 tests PASS

**Step 5: Commit**

```bash
git add tests/golden_days/__init__.py tests/golden_days/loader.py tests/golden_days/README.md tests/test_regression_suite.py
git commit -m "feat: add golden day loader and regression test fixture structure"
```

---

## Task 6: Regression Suite — Classification and Metric Tests

Add the actual regression tests that run the data pipeline on golden days and verify classification accuracy and metric stability. These tests use the golden day loader from Task 5 and the `DailyMetricsBuilder` from Phase 2.

**Files:**
- Modify: `tests/test_regression_suite.py` (add regression test classes)

**Step 1: Add regression tests to the existing file**

Append these classes to `tests/test_regression_suite.py`:

```python
# --- Append to tests/test_regression_suite.py ---

from datetime import datetime, timezone

from schemas.events import TradeEvent, MissedOpportunityEvent
from skills.build_daily_metrics import DailyMetricsBuilder


def _dict_to_trade_event(d: dict) -> TradeEvent:
    """Convert a golden day trade dict to a TradeEvent."""
    return TradeEvent(
        trade_id=d["trade_id"],
        bot_id=d["bot_id"],
        pair=d["pair"],
        side=d["side"],
        pnl=d["pnl"],
        pnl_pct=d.get("pnl_pct", 0.0),
        entry_price=d.get("entry_price", 0.0),
        exit_price=d.get("exit_price", 0.0),
        position_size=d.get("position_size", 0.0),
        entry_time=datetime.fromisoformat(d["entry_time"]),
        exit_time=datetime.fromisoformat(d["exit_time"]),
        entry_signal=d.get("entry_signal", ""),
        exit_reason=d.get("exit_reason", ""),
        market_regime=d.get("market_regime", ""),
        process_quality_score=d.get("process_quality_score", 100),
        root_causes=d.get("root_causes", []),
    )


def _dict_to_missed_event(d: dict) -> MissedOpportunityEvent:
    """Convert a golden day missed dict to a MissedOpportunityEvent."""
    return MissedOpportunityEvent(
        bot_id=d["bot_id"],
        pair=d["pair"],
        signal=d["signal"],
        blocked_by=d.get("blocked_by", ""),
        hypothetical_entry=d.get("hypothetical_entry", 0.0),
        outcome_24h=d.get("outcome_24h"),
        confidence=d.get("confidence", 0.0),
        assumption_tags=d.get("assumption_tags", []),
    )


class TestClassificationAccuracy:
    """Run pipeline on golden days, compare root causes to human labels."""

    def test_root_causes_match_expected(self, golden_day_dir: Path):
        days = load_golden_days(golden_day_dir)
        for day in days:
            trades = [_dict_to_trade_event(t) for t in day.trades]
            for trade in trades:
                expected = day.expected_classifications.get(trade.trade_id, {})
                if "root_causes" in expected:
                    assert trade.root_causes == expected["root_causes"], (
                        f"Trade {trade.trade_id}: expected root causes "
                        f"{expected['root_causes']}, got {trade.root_causes}"
                    )

    def test_process_quality_scores_match(self, golden_day_dir: Path):
        days = load_golden_days(golden_day_dir)
        for day in days:
            trades = [_dict_to_trade_event(t) for t in day.trades]
            for trade in trades:
                expected = day.expected_classifications.get(trade.trade_id, {})
                if "process_quality_score" in expected:
                    assert trade.process_quality_score == expected["process_quality_score"], (
                        f"Trade {trade.trade_id}: expected PQ score "
                        f"{expected['process_quality_score']}, got {trade.process_quality_score}"
                    )


class TestMetricStability:
    """Key metrics should not change more than 5% between pipeline versions."""

    def test_summary_metrics_within_tolerance(self, golden_day_dir: Path):
        days = load_golden_days(golden_day_dir)
        for day in days:
            if "summary.json" not in day.expected_curated:
                continue

            trades = [_dict_to_trade_event(t) for t in day.trades]
            missed = [_dict_to_missed_event(m) for m in day.missed]

            for bot_id in day.bots:
                bot_trades = [t for t in trades if t.bot_id == bot_id]
                builder = DailyMetricsBuilder(date=day.date, bot_id=bot_id)
                actual = builder.build_summary(bot_trades)

                expected = day.expected_curated["summary.json"]
                # Check key integer metrics exactly
                assert actual.total_trades == expected["total_trades"], (
                    f"total_trades: expected {expected['total_trades']}, got {actual.total_trades}"
                )
                assert actual.win_count == expected["win_count"], (
                    f"win_count: expected {expected['win_count']}, got {actual.win_count}"
                )

                # Check float metrics within 5% tolerance
                expected_pnl = expected["net_pnl"]
                if expected_pnl != 0:
                    delta = abs(actual.net_pnl - expected_pnl) / abs(expected_pnl)
                    assert delta < 0.05, (
                        f"net_pnl drifted by {delta:.1%}: "
                        f"expected {expected_pnl}, got {actual.net_pnl}"
                    )
```

**Step 2: Run test to verify all pass**

Run: `venv/Scripts/python -m pytest tests/test_regression_suite.py -v`
Expected: All 8 tests PASS (6 loader + 2 regression)

**Step 3: Commit**

```bash
git add tests/test_regression_suite.py
git commit -m "feat: add classification accuracy and metric stability regression tests"
```

---

## Task 7: Orchestrator Wiring — Weekly Schedule Trigger

Wire the weekly analysis into the existing orchestrator: add a `weekly_summary_trigger` event type to the brain, a `on_weekly_analysis` handler to the worker, and a weekly cron job to the scheduler.

**Files:**
- Modify: `orchestrator/orchestrator_brain.py`
- Modify: `orchestrator/worker.py`
- Modify: `orchestrator/scheduler.py`
- Test: `tests/test_weekly_integration.py`

**Step 1: Write the failing integration test**

```python
# tests/test_weekly_integration.py
"""Integration test: weekly analysis trigger flows through brain → worker → handler."""
import pytest

from orchestrator.orchestrator_brain import OrchestratorBrain, ActionType


class TestWeeklyBrainRouting:
    def test_weekly_trigger_routes_to_spawn_weekly(self):
        brain = OrchestratorBrain()
        event = {
            "event_type": "weekly_summary_trigger",
            "event_id": "weekly-2026-03-01",
            "bot_id": "",
        }
        actions = brain.decide(event)
        assert len(actions) == 1
        assert actions[0].type == ActionType.SPAWN_WEEKLY_SUMMARY


class TestWeeklyWorkerDispatch:
    @pytest.mark.asyncio
    async def test_weekly_handler_called(self, tmp_path):
        from orchestrator.db.queue import EventQueue
        from orchestrator.db.connection import create_connection
        from orchestrator.task_registry import TaskRegistry
        from orchestrator.worker import Worker

        db_path = str(tmp_path / "test.db")
        queue = EventQueue(db_path)
        await queue.initialize()
        registry = TaskRegistry(db_path)
        await registry.initialize()
        brain = OrchestratorBrain()

        worker = Worker(queue=queue, registry=registry, brain=brain)

        called = {"value": False}

        async def mock_weekly_handler(action):
            called["value"] = True

        worker.on_weekly_analysis = mock_weekly_handler

        # Enqueue a weekly trigger event
        await queue.enqueue({
            "event_id": "weekly-2026-03-01",
            "event_type": "weekly_summary_trigger",
            "bot_id": "",
            "payload": "{}",
        })

        processed = await worker.process_batch(limit=1)
        assert processed == 1
        assert called["value"] is True

        await queue.close()
        await registry.close()


class TestWeeklySchedulerConfig:
    def test_weekly_analysis_job_created(self):
        from orchestrator.scheduler import SchedulerConfig, create_scheduler_jobs

        async def noop():
            pass

        config = SchedulerConfig(
            weekly_analysis_day_of_week="sun",
            weekly_analysis_hour=8,
            weekly_analysis_minute=0,
        )
        jobs = create_scheduler_jobs(
            config=config,
            worker_fn=noop,
            monitoring_fn=noop,
            relay_fn=noop,
            weekly_analysis_fn=noop,
        )
        weekly_jobs = [j for j in jobs if j["name"] == "weekly_analysis"]
        assert len(weekly_jobs) == 1
        assert weekly_jobs[0]["trigger"] == "cron"
        assert weekly_jobs[0]["day_of_week"] == "sun"
        assert weekly_jobs[0]["hour"] == 8
```

**Step 2: Run test to verify it fails**

Run: `venv/Scripts/python -m pytest tests/test_weekly_integration.py -v`
Expected: FAIL — `weekly_summary_trigger` not in brain handlers, `on_weekly_analysis` not on worker, scheduler config missing fields

**Step 3: Modify orchestrator_brain.py**

Add a handler for the `weekly_summary_trigger` event type. Append to the `_handlers` dict:

In `orchestrator/orchestrator_brain.py`, add:

```python
    def _handle_weekly_summary_trigger(self, event_id: str, bot_id: str, event: dict) -> list[Action]:
        return [Action(type=ActionType.SPAWN_WEEKLY_SUMMARY, event_id=event_id, bot_id=bot_id)]
```

And add to `_handlers`:

```python
    _handlers: dict = {
        "trade": _handle_trade,
        "missed_opportunity": _handle_missed_opportunity,
        "error": _handle_error,
        "heartbeat": _handle_heartbeat,
        "daily_analysis_trigger": _handle_daily_analysis_trigger,
        "weekly_summary_trigger": _handle_weekly_summary_trigger,
    }
```

**Step 4: Modify worker.py**

Add `on_weekly_analysis` handler and dispatch case. In `orchestrator/worker.py`:

Add to `__init__`:

```python
        self.on_weekly_analysis: Callable[[Action], Awaitable[None]] | None = None
```

Add to `_dispatch`:

```python
        elif action.type == ActionType.SPAWN_WEEKLY_SUMMARY:
            if self.on_weekly_analysis:
                await self.on_weekly_analysis(action)
            else:
                logger.info("Weekly analysis triggered but no handler set: %s", action.event_id)
```

**Step 5: Modify scheduler.py**

Add weekly analysis fields to `SchedulerConfig` and `create_scheduler_jobs`. In `orchestrator/scheduler.py`:

Add to `SchedulerConfig`:

```python
    weekly_analysis_day_of_week: str = "sun"  # day of week for weekly analysis
    weekly_analysis_hour: int = 8
    weekly_analysis_minute: int = 0
```

Add `weekly_analysis_fn` parameter to `create_scheduler_jobs` and append the job:

```python
def create_scheduler_jobs(
    config: SchedulerConfig,
    worker_fn: Callable[[], Awaitable[None]],
    monitoring_fn: Callable[[], Awaitable[None]],
    relay_fn: Callable[[], Awaitable[None]],
    daily_analysis_fn: Callable[[], Awaitable[None]] | None = None,
    weekly_analysis_fn: Callable[[], Awaitable[None]] | None = None,
) -> list[dict]:
    # ... existing jobs ...

    if weekly_analysis_fn is not None:
        jobs.append({
            "name": "weekly_analysis",
            "func": weekly_analysis_fn,
            "trigger": "cron",
            "day_of_week": config.weekly_analysis_day_of_week,
            "hour": config.weekly_analysis_hour,
            "minute": config.weekly_analysis_minute,
        })

    return jobs
```

**Step 6: Run test to verify all pass**

Run: `venv/Scripts/python -m pytest tests/test_weekly_integration.py -v`
Expected: All 3 tests PASS

**Step 7: Run full test suite to verify no regressions**

Run: `venv/Scripts/python -m pytest tests/ -v`
Expected: All existing tests PASS + 3 new tests PASS

**Step 8: Commit**

```bash
git add orchestrator/orchestrator_brain.py orchestrator/worker.py orchestrator/scheduler.py tests/test_weekly_integration.py
git commit -m "feat: wire weekly analysis trigger into orchestrator brain, worker, scheduler"
```

---

## Task 8: Full Weekly Pipeline Integration Test

End-to-end test: daily curated data exists → weekly metrics builder runs → strategy engine runs → weekly prompt assembler produces a complete context package.

**Files:**
- Create: `tests/test_weekly_pipeline_integration.py`

**Step 1: Write the integration test**

```python
# tests/test_weekly_pipeline_integration.py
"""End-to-end integration test for the weekly analysis pipeline.

Flow: daily curated data → weekly metrics builder → strategy engine →
      weekly prompt assembler → complete context package.
"""
import json
from pathlib import Path

import pytest

from schemas.daily_metrics import (
    BotDailySummary,
    FilterAnalysis,
)
from schemas.weekly_metrics import FilterWeeklySummary, RegimePerformanceTrend
from skills.build_weekly_metrics import WeeklyMetricsBuilder
from analysis.strategy_engine import StrategyEngine
from analysis.weekly_prompt_assembler import WeeklyPromptAssembler


_DATES = [
    "2026-02-23", "2026-02-24", "2026-02-25", "2026-02-26",
    "2026-02-27", "2026-02-28", "2026-03-01",
]


def _setup_daily_data(base_dir: Path, bots: list[str]) -> None:
    """Create 7 days of daily curated data for each bot."""
    for date in _DATES:
        for bot_id in bots:
            bot_dir = base_dir / date / bot_id
            bot_dir.mkdir(parents=True)
            summary = BotDailySummary(
                date=date,
                bot_id=bot_id,
                total_trades=10,
                win_count=6,
                loss_count=4,
                gross_pnl=80.0,
                net_pnl=70.0,
                avg_win=30.0,
                avg_loss=-15.0,
                avg_process_quality=75.0,
                missed_count=3,
                missed_would_have_won=1,
            )
            (bot_dir / "summary.json").write_text(
                json.dumps(summary.model_dump(mode="json"), indent=2)
            )
            # Minimal files for completeness
            for fname in [
                "winners.json", "losers.json", "process_failures.json",
                "notable_missed.json", "regime_analysis.json",
                "filter_analysis.json", "root_cause_summary.json",
            ]:
                (bot_dir / fname).write_text("[]")

        # Portfolio risk card per day
        (base_dir / date / "portfolio_risk_card.json").write_text(
            json.dumps({"date": date, "concentration_score": 30.0})
        )


def _setup_memory(memory_dir: Path) -> None:
    """Create memory policies and corrections."""
    policy_dir = memory_dir / "policies" / "v1"
    policy_dir.mkdir(parents=True)
    (policy_dir / "agents.md").write_text("You are the trading assistant.")
    (policy_dir / "trading_rules.md").write_text("Max drawdown 15%.")
    (policy_dir / "soul.md").write_text("Conservative.")
    findings_dir = memory_dir / "findings"
    findings_dir.mkdir(parents=True)
    (findings_dir / "corrections.jsonl").write_text("")


def _setup_runs(runs_dir: Path) -> None:
    """Create 7 days of daily report stubs."""
    for date in _DATES:
        run_dir = runs_dir / date / "daily-report"
        run_dir.mkdir(parents=True)
        (run_dir / "daily_report.md").write_text(f"# Daily Report {date}\nAll good.")


class TestWeeklyPipelineIntegration:
    def test_full_weekly_pipeline(self, tmp_path: Path):
        """End-to-end: daily data → weekly summary → strategy suggestions → prompt package."""
        curated_dir = tmp_path / "curated"
        memory_dir = tmp_path / "memory"
        runs_dir = tmp_path / "runs"
        bots = ["bot1", "bot2"]

        _setup_daily_data(curated_dir, bots)
        _setup_memory(memory_dir)
        _setup_runs(runs_dir)

        # Step 1: Build weekly metrics
        builder = WeeklyMetricsBuilder(
            week_start="2026-02-23", week_end="2026-03-01", bots=bots
        )

        dailies_by_bot = {}
        for bot_id in bots:
            dailies = []
            for date in _DATES:
                summary_path = curated_dir / date / bot_id / "summary.json"
                data = json.loads(summary_path.read_text())
                dailies.append(BotDailySummary.model_validate(data))
            dailies_by_bot[bot_id] = dailies

        portfolio_summary = builder.build_portfolio_summary(dailies_by_bot)
        assert portfolio_summary.total_trades == 140  # 10 * 7 * 2 bots
        assert portfolio_summary.total_net_pnl == 980.0  # 70 * 7 * 2

        # Write weekly curated data
        weekly_dir = builder.write_weekly_curated(portfolio_summary, curated_dir)
        assert (weekly_dir / "weekly_summary.json").exists()

        # Step 2: Run strategy engine
        engine = StrategyEngine(week_start="2026-02-23", week_end="2026-03-01")
        report = engine.build_report(bot_summaries=portfolio_summary.bot_summaries)
        # Write refinement report
        (weekly_dir / "refinement_report.json").write_text(
            json.dumps(report.model_dump(mode="json"), indent=2, default=str)
        )

        # Step 3: Assemble weekly prompt
        assembler = WeeklyPromptAssembler(
            week_start="2026-02-23",
            week_end="2026-03-01",
            bots=bots,
            curated_dir=curated_dir,
            memory_dir=memory_dir,
            runs_dir=runs_dir,
        )
        package = assembler.assemble()

        # Verify complete package
        assert "system_prompt" in package
        assert "task_prompt" in package
        assert "data" in package
        assert "weekly_summary" in package["data"]
        assert "refinement_report" in package["data"]
        assert "daily_reports" in package["data"]
        assert len(package["data"]["daily_reports"]) == 7
        assert "portfolio_risk_cards" in package["data"]
        assert len(package["data"]["portfolio_risk_cards"]) == 7
        assert "instructions" in package
        assert "weekly" in package["task_prompt"].lower()
```

**Step 2: Run test to verify it passes**

Run: `venv/Scripts/python -m pytest tests/test_weekly_pipeline_integration.py -v`
Expected: 1 test PASS

**Step 3: Run full test suite**

Run: `venv/Scripts/python -m pytest tests/ -v`
Expected: All tests PASS (existing + all new Phase 3 tests)

**Step 4: Commit**

```bash
git add tests/test_weekly_pipeline_integration.py
git commit -m "feat: add end-to-end weekly pipeline integration test"
```

---

## Summary

| Task | Component | Tests | New Files |
|------|-----------|-------|-----------|
| 0 | Weekly metrics schemas | 11 | `schemas/weekly_metrics.py` |
| 1 | Strategy suggestion schemas | 8 | `schemas/strategy_suggestions.py` |
| 2 | Weekly metrics pipeline | 11 | `skills/build_weekly_metrics.py` |
| 3 | Strategy refinement engine | 7 | `analysis/strategy_engine.py` |
| 4 | Weekly prompt assembler | 7 | `analysis/weekly_prompt_assembler.py` |
| 5 | Golden day loader + fixtures | 6 | `tests/golden_days/loader.py`, `README.md` |
| 6 | Regression tests | 2 | (appended to `test_regression_suite.py`) |
| 7 | Orchestrator wiring | 3 | (modified brain, worker, scheduler) |
| 8 | Integration test | 1 | `tests/test_weekly_pipeline_integration.py` |
| **Total** | | **~56** | **7 new + 3 modified** |
