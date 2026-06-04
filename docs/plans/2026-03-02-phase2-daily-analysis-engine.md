# Phase 2: Daily Analysis Engine — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build the data reduction pipeline, portfolio risk computation, report quality gates, daily analysis agent prompt assembly, and human feedback loop that transform raw trade events into actionable daily reports.

**Architecture:** Deterministic Python scripts reduce raw trade/missed-opportunity events into classified, pre-scored summaries per bot per day. A portfolio risk card computes cross-bot exposure and crowding alerts. A report quality gate validates completeness before the orchestrator assembles a context package and invokes Claude for interpretation. Human corrections flow back via structured JSONL and influence future analysis prompts.

**Tech Stack:** Python 3.12, Pydantic v2, pytest, aiosqlite (read events from queue DB), pathlib (curated data dirs)

**Assumes:** Phase 1 core infrastructure is built — the event queue (`orchestrator/db/queue.py`), task registry (`orchestrator/task_registry.py`), orchestrator brain (`orchestrator/orchestrator_brain.py`), worker (`orchestrator/worker.py`), scheduler (`orchestrator/scheduler.py`), and schemas (`schemas/events.py`) all exist and work.

**Directory structure this plan creates:**

```
trading_assistant/
  schemas/
    daily_metrics.py          # DailySummary, RegimeAnalysis, FilterAnalysis, AnomalyRecord, RootCauseSummary
    portfolio_risk.py         # PortfolioRiskCard, CrowdingAlert
    report_checklist.py       # ReportChecklist, CheckResult
    corrections.py            # HumanCorrection model
  skills/
    __init__.py
    build_daily_metrics.py    # data reduction: events → per-bot curated files
    compute_portfolio_risk.py # cross-bot risk card
  analysis/
    __init__.py
    quality_gate.py           # report Definition of Done checker
    prompt_assembler.py       # builds context package for Claude daily analysis
    feedback_handler.py       # parses human replies → corrections.jsonl
  orchestrator/
    orchestrator_brain.py     # MODIFY: add SPAWN_DAILY_ANALYSIS trigger on schedule
    scheduler.py              # MODIFY: add daily_analysis cron job
    worker.py                 # MODIFY: dispatch SPAWN_DAILY_ANALYSIS to prompt assembler
  tests/
    test_daily_metrics.py
    test_portfolio_risk.py
    test_quality_gate.py
    test_prompt_assembler.py
    test_feedback_handler.py
    test_daily_integration.py
```

---

## Task 0: Daily Metrics Schemas

**Files:**
- Create: `schemas/daily_metrics.py`
- Test: `tests/test_daily_metrics.py`

**Step 1: Write the failing test**

```python
# tests/test_daily_metrics.py
"""Tests for daily metrics schemas."""
from datetime import date

from schemas.daily_metrics import (
    BotDailySummary,
    WinnerLoserRecord,
    ProcessFailureRecord,
    NotableMissedRecord,
    RegimeAnalysis,
    FilterAnalysis,
    AnomalyRecord,
    RootCauseSummary,
)


class TestBotDailySummary:
    def test_creates_from_minimal_data(self):
        summary = BotDailySummary(
            date="2026-03-01",
            bot_id="bot1",
            total_trades=20,
            win_count=12,
            loss_count=8,
            gross_pnl=150.0,
            net_pnl=140.0,
        )
        assert summary.bot_id == "bot1"
        assert summary.win_rate == 0.6

    def test_win_rate_zero_trades(self):
        summary = BotDailySummary(date="2026-03-01", bot_id="bot1")
        assert summary.win_rate == 0.0

    def test_profit_factor_zero_losses(self):
        summary = BotDailySummary(
            date="2026-03-01",
            bot_id="bot1",
            total_trades=5,
            win_count=5,
            loss_count=0,
            avg_win=100.0,
            avg_loss=0.0,
        )
        assert summary.profit_factor == float("inf")


class TestWinnerLoserRecord:
    def test_creates_with_required_fields(self):
        rec = WinnerLoserRecord(
            trade_id="t1",
            bot_id="bot1",
            pair="BTCUSDT",
            side="LONG",
            pnl=250.0,
            pnl_pct=2.5,
            entry_signal="EMA cross",
            exit_reason="TAKE_PROFIT",
            market_regime="trending_up",
            process_quality_score=85,
            root_causes=["normal_win"],
        )
        assert rec.pnl == 250.0
        assert rec.root_causes == ["normal_win"]


class TestProcessFailureRecord:
    def test_creates_with_low_score(self):
        rec = ProcessFailureRecord(
            trade_id="t2",
            bot_id="bot1",
            pair="ETHUSDT",
            process_quality_score=45,
            root_causes=["regime_mismatch", "weak_signal"],
            pnl=-80.0,
        )
        assert rec.process_quality_score < 60


class TestNotableMissedRecord:
    def test_creates_with_outcome(self):
        rec = NotableMissedRecord(
            bot_id="bot1",
            pair="BTCUSDT",
            signal="RSI divergence",
            blocked_by="volatility_filter",
            hypothetical_entry=50000.0,
            outcome_24h=500.0,
            confidence=0.7,
            assumption_tags=["mid_fill", "zero_slippage"],
        )
        assert rec.blocked_by == "volatility_filter"


class TestRegimeAnalysis:
    def test_creates_with_breakdown(self):
        ra = RegimeAnalysis(
            bot_id="bot1",
            date="2026-03-01",
            regime_pnl={"trending_up": 200.0, "ranging": -50.0},
            regime_trade_count={"trending_up": 8, "ranging": 5},
            regime_win_rate={"trending_up": 0.75, "ranging": 0.4},
        )
        assert ra.regime_pnl["trending_up"] == 200.0


class TestFilterAnalysis:
    def test_creates_with_filter_impact(self):
        fa = FilterAnalysis(
            bot_id="bot1",
            date="2026-03-01",
            filter_block_counts={"volatility_filter": 5, "spread_filter": 2},
            filter_saved_pnl={"volatility_filter": 300.0, "spread_filter": 100.0},
            filter_missed_pnl={"volatility_filter": -50.0, "spread_filter": 0.0},
        )
        assert fa.filter_block_counts["volatility_filter"] == 5


class TestAnomalyRecord:
    def test_creates_anomaly(self):
        a = AnomalyRecord(
            bot_id="bot1",
            date="2026-03-01",
            anomaly_type="volume_spike",
            description="Volume 3× above 30-day average on ETHUSDT",
            severity="medium",
            related_trades=["t5", "t6"],
        )
        assert a.anomaly_type == "volume_spike"


class TestRootCauseSummary:
    def test_creates_distribution(self):
        rcs = RootCauseSummary(
            bot_id="bot1",
            date="2026-03-01",
            distribution={"normal_win": 8, "regime_mismatch": 3, "weak_signal": 2},
            total_trades=13,
        )
        assert sum(rcs.distribution.values()) == rcs.total_trades
```

**Step 2: Run test to verify it fails**

Run: `venv/Scripts/python -m pytest tests/test_daily_metrics.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'schemas.daily_metrics'`

**Step 3: Write minimal implementation**

```python
# schemas/daily_metrics.py
"""Daily metrics schemas — Pydantic models for reduced/curated daily data.

These define the output format of the data reduction pipeline (skills/build_daily_metrics.py).
Claude sees these pre-scored, pre-classified structures — not raw trade data.
"""
from __future__ import annotations

from pydantic import BaseModel, computed_field


class BotDailySummary(BaseModel):
    """Aggregated daily stats for a single bot."""

    date: str  # YYYY-MM-DD
    bot_id: str
    total_trades: int = 0
    win_count: int = 0
    loss_count: int = 0
    gross_pnl: float = 0.0
    net_pnl: float = 0.0
    max_drawdown_pct: float = 0.0
    sharpe_rolling_30d: float = 0.0
    sortino_rolling_30d: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    exposure_pct: float = 0.0
    missed_count: int = 0
    missed_would_have_won: int = 0
    error_count: int = 0
    uptime_pct: float = 100.0
    avg_process_quality: float = 100.0

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


class WinnerLoserRecord(BaseModel):
    """A single notable winning or losing trade with full context."""

    trade_id: str
    bot_id: str
    pair: str
    side: str
    pnl: float
    pnl_pct: float = 0.0
    entry_signal: str = ""
    exit_reason: str = ""
    market_regime: str = ""
    process_quality_score: int = 100
    root_causes: list[str] = []
    entry_price: float = 0.0
    exit_price: float = 0.0
    atr_at_entry: float = 0.0


class ProcessFailureRecord(BaseModel):
    """A trade with process_quality_score < 60 — flagged for review."""

    trade_id: str
    bot_id: str
    pair: str
    process_quality_score: int
    root_causes: list[str]
    pnl: float
    entry_signal: str = ""
    market_regime: str = ""


class NotableMissedRecord(BaseModel):
    """A missed opportunity where outcome > 2× avg win."""

    bot_id: str
    pair: str
    signal: str
    blocked_by: str = ""
    hypothetical_entry: float = 0.0
    outcome_24h: float = 0.0
    confidence: float = 0.0
    assumption_tags: list[str] = []


class RegimeAnalysis(BaseModel):
    """PnL breakdown by market regime for one bot on one day."""

    bot_id: str
    date: str
    regime_pnl: dict[str, float] = {}
    regime_trade_count: dict[str, int] = {}
    regime_win_rate: dict[str, float] = {}


class FilterAnalysis(BaseModel):
    """Impact analysis for each filter: how many trades blocked, net PnL effect."""

    bot_id: str
    date: str
    filter_block_counts: dict[str, int] = {}
    filter_saved_pnl: dict[str, float] = {}
    filter_missed_pnl: dict[str, float] = {}


class AnomalyRecord(BaseModel):
    """A statistically unusual event detected in today's data."""

    bot_id: str
    date: str
    anomaly_type: str
    description: str
    severity: str = "medium"  # low | medium | high
    related_trades: list[str] = []


class RootCauseSummary(BaseModel):
    """Distribution of root causes across all trades for one bot on one day."""

    bot_id: str
    date: str
    distribution: dict[str, int] = {}
    total_trades: int = 0
```

**Step 4: Run test to verify it passes**

Run: `venv/Scripts/python -m pytest tests/test_daily_metrics.py -v`
Expected: All 10 tests PASS

**Step 5: Commit**

```bash
git add schemas/daily_metrics.py tests/test_daily_metrics.py
git commit -m "feat: add daily metrics schemas for data reduction pipeline"
```

---

## Task 1: Portfolio Risk Schemas

**Files:**
- Create: `schemas/portfolio_risk.py`
- Test: `tests/test_portfolio_risk.py`

**Step 1: Write the failing test**

```python
# tests/test_portfolio_risk.py
"""Tests for portfolio risk schemas."""
from schemas.portfolio_risk import PortfolioRiskCard, CrowdingAlert


class TestPortfolioRiskCard:
    def test_creates_minimal_card(self):
        card = PortfolioRiskCard(
            date="2026-03-01",
            total_exposure_pct=45.0,
            exposure_by_symbol={"BTC": 30.0, "ETH": 15.0},
            exposure_by_direction={"LONG": 35.0, "SHORT": 10.0},
        )
        assert card.total_exposure_pct == 45.0

    def test_crowding_alerts_empty_by_default(self):
        card = PortfolioRiskCard(date="2026-03-01")
        assert card.crowding_alerts == []

    def test_concentration_score_bounds(self):
        card = PortfolioRiskCard(
            date="2026-03-01",
            concentration_score=85.0,
        )
        assert 0 <= card.concentration_score <= 100

    def test_with_correlation_matrix(self):
        card = PortfolioRiskCard(
            date="2026-03-01",
            correlation_matrix={"bot1_bot2": 0.75, "bot1_bot3": 0.3},
        )
        assert card.correlation_matrix["bot1_bot2"] == 0.75


class TestCrowdingAlert:
    def test_creates_alert(self):
        alert = CrowdingAlert(
            alert_type="high_correlation",
            description="bot1 and bot2 correlation > 0.7",
            severity="high",
            bots_involved=["bot1", "bot2"],
        )
        assert alert.alert_type == "high_correlation"
        assert len(alert.bots_involved) == 2

    def test_single_symbol_concentration(self):
        alert = CrowdingAlert(
            alert_type="single_symbol_concentration",
            description="BTC > 50% of total exposure",
            severity="medium",
            symbol="BTC",
            exposure_pct=65.0,
        )
        assert alert.symbol == "BTC"
```

**Step 2: Run test to verify it fails**

Run: `venv/Scripts/python -m pytest tests/test_portfolio_risk.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'schemas.portfolio_risk'`

**Step 3: Write minimal implementation**

```python
# schemas/portfolio_risk.py
"""Portfolio risk schemas — cross-bot exposure and crowding detection.

Computed daily by skills/compute_portfolio_risk.py. No LLM calls.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class CrowdingAlert(BaseModel):
    """A specific crowding/concentration risk detected."""

    alert_type: str  # high_correlation | same_side | total_exposure | single_symbol_concentration
    description: str
    severity: str = "medium"  # low | medium | high | critical
    bots_involved: list[str] = []
    symbol: Optional[str] = None
    exposure_pct: Optional[float] = None


class PortfolioRiskCard(BaseModel):
    """Daily cross-bot portfolio risk snapshot."""

    date: str  # YYYY-MM-DD
    total_exposure_pct: float = 0.0
    exposure_by_symbol: dict[str, float] = {}
    exposure_by_direction: dict[str, float] = {}
    correlation_matrix: dict[str, float] = {}  # "bot1_bot2" → correlation
    max_simultaneous_leverage: float = 0.0
    concentration_score: float = 0.0  # 0–100, higher = more concentrated
    crowding_alerts: list[CrowdingAlert] = []
```

**Step 4: Run test to verify it passes**

Run: `venv/Scripts/python -m pytest tests/test_portfolio_risk.py -v`
Expected: All 6 tests PASS

**Step 5: Commit**

```bash
git add schemas/portfolio_risk.py tests/test_portfolio_risk.py
git commit -m "feat: add portfolio risk card and crowding alert schemas"
```

---

## Task 2: Report Checklist Schema

**Files:**
- Create: `schemas/report_checklist.py`
- Test: `tests/test_report_checklist.py`

**Step 1: Write the failing test**

```python
# tests/test_report_checklist.py
"""Tests for report checklist schema."""
from schemas.report_checklist import ReportChecklist, CheckResult


class TestCheckResult:
    def test_passing_check(self):
        cr = CheckResult(name="all_bots_reported", passed=True, detail="5/5 bots")
        assert cr.passed is True

    def test_failing_check(self):
        cr = CheckResult(name="open_risks_section", passed=False, detail="CRITICAL error unaddressed")
        assert cr.passed is False


class TestReportChecklist:
    def test_all_pass(self):
        checklist = ReportChecklist(
            report_id="daily-2026-03-01",
            checks=[
                CheckResult(name="all_bots_reported", passed=True, detail="5/5"),
                CheckResult(name="anomaly_detection_ran", passed=True, detail="ok"),
            ],
        )
        assert checklist.overall == "PASS"
        assert checklist.blocking_issues == []

    def test_one_fails(self):
        checklist = ReportChecklist(
            report_id="daily-2026-03-01",
            checks=[
                CheckResult(name="all_bots_reported", passed=True, detail="5/5"),
                CheckResult(name="open_risks_section", passed=False, detail="CRITICAL error"),
            ],
        )
        assert checklist.overall == "FAIL"
        assert len(checklist.blocking_issues) == 1
        assert "open_risks_section" in checklist.blocking_issues[0]

    def test_empty_checks(self):
        checklist = ReportChecklist(report_id="daily-2026-03-01", checks=[])
        assert checklist.overall == "PASS"
```

**Step 2: Run test to verify it fails**

Run: `venv/Scripts/python -m pytest tests/test_report_checklist.py -v`
Expected: FAIL with `ModuleNotFoundError`

**Step 3: Write minimal implementation**

```python
# schemas/report_checklist.py
"""Report quality gate schemas — Definition of Done for daily reports.

Every daily report must pass all checks before being sent.
"""
from __future__ import annotations

from pydantic import BaseModel, computed_field


class CheckResult(BaseModel):
    """One quality gate check."""

    name: str
    passed: bool
    detail: str = ""


class ReportChecklist(BaseModel):
    """Aggregated quality gate for a daily report."""

    report_id: str
    checks: list[CheckResult] = []

    @computed_field  # type: ignore[prop-decorator]
    @property
    def overall(self) -> str:
        if all(c.passed for c in self.checks):
            return "PASS"
        return "FAIL"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def blocking_issues(self) -> list[str]:
        return [f"{c.name}: {c.detail}" for c in self.checks if not c.passed]
```

**Step 4: Run test to verify it passes**

Run: `venv/Scripts/python -m pytest tests/test_report_checklist.py -v`
Expected: All 5 tests PASS

**Step 5: Commit**

```bash
git add schemas/report_checklist.py tests/test_report_checklist.py
git commit -m "feat: add report checklist schema with quality gate"
```

---

## Task 3: Human Correction Schema

**Files:**
- Create: `schemas/corrections.py`
- Test: `tests/test_corrections.py`

**Step 1: Write the failing test**

```python
# tests/test_corrections.py
"""Tests for human correction schema."""
from datetime import datetime, timezone

from schemas.corrections import HumanCorrection, CorrectionType


class TestCorrectionType:
    def test_all_types_exist(self):
        assert CorrectionType.TRADE_RECLASSIFY
        assert CorrectionType.REGIME_OVERRIDE
        assert CorrectionType.POSITIVE_REINFORCEMENT
        assert CorrectionType.FREE_TEXT


class TestHumanCorrection:
    def test_trade_reclassify(self):
        c = HumanCorrection(
            correction_type=CorrectionType.TRADE_RECLASSIFY,
            original_report_id="daily-2026-03-01",
            target_id="trade_xyz",
            raw_text="Trade #xyz wasn't bad — it was a planned hedge against spot",
            structured_correction={"new_root_cause": "normal_win", "reason": "planned hedge"},
        )
        assert c.correction_type == CorrectionType.TRADE_RECLASSIFY
        assert c.target_id == "trade_xyz"

    def test_regime_override(self):
        c = HumanCorrection(
            correction_type=CorrectionType.REGIME_OVERRIDE,
            original_report_id="daily-2026-03-01",
            target_id="bot2",
            raw_text="Bot2's regime classification was wrong today, slow trend not ranging",
            structured_correction={"old_regime": "ranging", "new_regime": "trending_up"},
        )
        assert c.structured_correction["new_regime"] == "trending_up"

    def test_has_timestamp(self):
        c = HumanCorrection(
            correction_type=CorrectionType.FREE_TEXT,
            original_report_id="daily-2026-03-01",
            raw_text="Good catch on the volume filter",
        )
        assert c.timestamp is not None
        assert isinstance(c.timestamp, datetime)

    def test_serializes_to_jsonl_format(self):
        c = HumanCorrection(
            correction_type=CorrectionType.POSITIVE_REINFORCEMENT,
            original_report_id="daily-2026-03-01",
            raw_text="Good catch on the volume filter, that's the third time this week",
        )
        d = c.model_dump(mode="json")
        assert "correction_type" in d
        assert "timestamp" in d
        assert "raw_text" in d
```

**Step 2: Run test to verify it fails**

Run: `venv/Scripts/python -m pytest tests/test_corrections.py -v`
Expected: FAIL with `ModuleNotFoundError`

**Step 3: Write minimal implementation**

```python
# schemas/corrections.py
"""Human correction schemas — structured feedback from Telegram/Discord replies.

Written to memory/findings/corrections.jsonl. Included in future analysis prompts
so Claude learns the human's mental model over time (Ralph Loop V2).
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class CorrectionType(str, Enum):
    TRADE_RECLASSIFY = "trade_reclassify"
    REGIME_OVERRIDE = "regime_override"
    POSITIVE_REINFORCEMENT = "positive_reinforcement"
    FREE_TEXT = "free_text"


class HumanCorrection(BaseModel):
    """A single human correction or feedback item."""

    correction_type: CorrectionType
    original_report_id: str
    target_id: Optional[str] = None  # trade_id or bot_id being corrected
    raw_text: str
    structured_correction: dict = {}
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
```

**Step 4: Run test to verify it passes**

Run: `venv/Scripts/python -m pytest tests/test_corrections.py -v`
Expected: All 5 tests PASS

**Step 5: Commit**

```bash
git add schemas/corrections.py tests/test_corrections.py
git commit -m "feat: add human correction schema for feedback loop"
```

---

## Task 4: Data Reduction Pipeline — `build_daily_metrics.py`

This is the largest task. The pipeline reads trade events and missed opportunities from the event queue DB (acked events for a given date), reduces them into the curated data structures from Task 0, and writes JSON/CSV files to `data/curated/<date>/<bot_id>/`.

**Files:**
- Create: `skills/__init__.py`
- Create: `skills/build_daily_metrics.py`
- Test: `tests/test_daily_metrics_pipeline.py`

**Step 1: Write the failing tests**

```python
# tests/test_daily_metrics_pipeline.py
"""Tests for the daily metrics data reduction pipeline."""
import json
from pathlib import Path

import pytest

from schemas.events import TradeEvent, MissedOpportunityEvent
from schemas.daily_metrics import (
    BotDailySummary,
    WinnerLoserRecord,
    ProcessFailureRecord,
    NotableMissedRecord,
    RegimeAnalysis,
    FilterAnalysis,
    AnomalyRecord,
    RootCauseSummary,
)
from skills.build_daily_metrics import DailyMetricsBuilder


def _make_trade(trade_id: str, bot_id: str, pnl: float, **kwargs) -> TradeEvent:
    """Helper to create a TradeEvent with sensible defaults."""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    defaults = dict(
        trade_id=trade_id,
        bot_id=bot_id,
        pair="BTCUSDT",
        side="LONG",
        entry_time=now,
        exit_time=now,
        entry_price=50000.0,
        exit_price=50000.0 + pnl,
        position_size=1.0,
        pnl=pnl,
        pnl_pct=pnl / 50000.0 * 100,
        entry_signal="EMA cross",
        exit_reason="TAKE_PROFIT" if pnl > 0 else "STOP_LOSS",
        market_regime="trending_up",
        process_quality_score=85,
        root_causes=["normal_win"] if pnl > 0 else ["normal_loss"],
    )
    defaults.update(kwargs)
    return TradeEvent(**defaults)


def _make_missed(bot_id: str, pair: str, blocked_by: str, outcome_24h: float) -> MissedOpportunityEvent:
    return MissedOpportunityEvent(
        bot_id=bot_id,
        pair=pair,
        signal="RSI divergence",
        blocked_by=blocked_by,
        hypothetical_entry=50000.0,
        outcome_24h=outcome_24h,
        confidence=0.7,
        assumption_tags=["mid_fill"],
    )


class TestDailyMetricsBuilder:
    def test_build_summary_basic(self):
        trades = [
            _make_trade("t1", "bot1", 100.0),
            _make_trade("t2", "bot1", -50.0),
            _make_trade("t3", "bot1", 200.0),
        ]
        builder = DailyMetricsBuilder(date="2026-03-01", bot_id="bot1")
        summary = builder.build_summary(trades)

        assert summary.total_trades == 3
        assert summary.win_count == 2
        assert summary.loss_count == 1
        assert summary.gross_pnl == 250.0

    def test_top_winners(self):
        trades = [_make_trade(f"t{i}", "bot1", (i + 1) * 10.0) for i in range(10)]
        builder = DailyMetricsBuilder(date="2026-03-01", bot_id="bot1")
        winners = builder.top_winners(trades, n=5)

        assert len(winners) == 5
        assert winners[0].pnl >= winners[1].pnl  # sorted descending

    def test_top_losers(self):
        trades = [_make_trade(f"t{i}", "bot1", -(i + 1) * 10.0) for i in range(10)]
        builder = DailyMetricsBuilder(date="2026-03-01", bot_id="bot1")
        losers = builder.top_losers(trades, n=5)

        assert len(losers) == 5
        assert losers[0].pnl <= losers[1].pnl  # sorted ascending (most negative first)

    def test_process_failures(self):
        trades = [
            _make_trade("t1", "bot1", -80.0, process_quality_score=45, root_causes=["regime_mismatch"]),
            _make_trade("t2", "bot1", 100.0, process_quality_score=90),
            _make_trade("t3", "bot1", -20.0, process_quality_score=55, root_causes=["weak_signal"]),
        ]
        builder = DailyMetricsBuilder(date="2026-03-01", bot_id="bot1")
        failures = builder.process_failures(trades, threshold=60)

        assert len(failures) == 2
        assert all(f.process_quality_score < 60 for f in failures)

    def test_notable_missed(self):
        missed = [
            _make_missed("bot1", "BTCUSDT", "vol_filter", 500.0),
            _make_missed("bot1", "ETHUSDT", "spread_filter", 50.0),
            _make_missed("bot1", "SOLUSDT", "vol_filter", 800.0),
        ]
        trades = [_make_trade("t1", "bot1", 100.0)]  # avg_win = 100
        builder = DailyMetricsBuilder(date="2026-03-01", bot_id="bot1")
        notable = builder.notable_missed(missed, trades)

        # Only those with outcome > 2× avg_win (200)
        assert len(notable) == 2
        assert all(n.outcome_24h > 200 for n in notable)

    def test_regime_analysis(self):
        trades = [
            _make_trade("t1", "bot1", 100.0, market_regime="trending_up"),
            _make_trade("t2", "bot1", -50.0, market_regime="ranging"),
            _make_trade("t3", "bot1", 200.0, market_regime="trending_up"),
        ]
        builder = DailyMetricsBuilder(date="2026-03-01", bot_id="bot1")
        ra = builder.regime_analysis(trades)

        assert ra.regime_pnl["trending_up"] == 300.0
        assert ra.regime_pnl["ranging"] == -50.0
        assert ra.regime_trade_count["trending_up"] == 2

    def test_filter_analysis(self):
        missed = [
            _make_missed("bot1", "BTCUSDT", "vol_filter", 500.0),
            _make_missed("bot1", "ETHUSDT", "vol_filter", -100.0),
            _make_missed("bot1", "SOLUSDT", "spread_filter", 200.0),
        ]
        builder = DailyMetricsBuilder(date="2026-03-01", bot_id="bot1")
        fa = builder.filter_analysis(missed)

        assert fa.filter_block_counts["vol_filter"] == 2
        assert fa.filter_block_counts["spread_filter"] == 1

    def test_root_cause_summary(self):
        trades = [
            _make_trade("t1", "bot1", 100.0, root_causes=["normal_win"]),
            _make_trade("t2", "bot1", -50.0, root_causes=["regime_mismatch", "weak_signal"]),
        ]
        builder = DailyMetricsBuilder(date="2026-03-01", bot_id="bot1")
        rcs = builder.root_cause_summary(trades)

        assert rcs.distribution["normal_win"] == 1
        assert rcs.distribution["regime_mismatch"] == 1
        assert rcs.distribution["weak_signal"] == 1

    def test_write_curated_files(self, tmp_path: Path):
        trades = [
            _make_trade("t1", "bot1", 100.0),
            _make_trade("t2", "bot1", -50.0),
        ]
        missed = [_make_missed("bot1", "BTCUSDT", "vol_filter", 500.0)]

        builder = DailyMetricsBuilder(date="2026-03-01", bot_id="bot1")
        output_dir = builder.write_curated(trades, missed, base_dir=tmp_path)

        assert (output_dir / "summary.json").exists()
        assert (output_dir / "winners.json").exists()
        assert (output_dir / "losers.json").exists()
        assert (output_dir / "process_failures.json").exists()
        assert (output_dir / "notable_missed.json").exists()
        assert (output_dir / "regime_analysis.json").exists()
        assert (output_dir / "filter_analysis.json").exists()
        assert (output_dir / "root_cause_summary.json").exists()

        # Verify JSON is valid and round-trips
        summary_data = json.loads((output_dir / "summary.json").read_text())
        assert summary_data["bot_id"] == "bot1"
```

**Step 2: Run test to verify it fails**

Run: `venv/Scripts/python -m pytest tests/test_daily_metrics_pipeline.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'skills'`

**Step 3: Write minimal implementation**

Create `skills/__init__.py` (empty file).

```python
# skills/build_daily_metrics.py
"""Data reduction pipeline — events → per-bot curated daily files.

Claude sees reduced, classified, pre-scored data. This deterministic pipeline
does the heavy lifting of classification. Claude does interpretation and synthesis.

Output directory: data/curated/<date>/<bot_id>/
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from schemas.events import TradeEvent, MissedOpportunityEvent
from schemas.daily_metrics import (
    BotDailySummary,
    WinnerLoserRecord,
    ProcessFailureRecord,
    NotableMissedRecord,
    RegimeAnalysis,
    FilterAnalysis,
    RootCauseSummary,
)


class DailyMetricsBuilder:
    """Builds curated daily metrics for a single bot on a single day."""

    def __init__(self, date: str, bot_id: str) -> None:
        self.date = date
        self.bot_id = bot_id

    def build_summary(self, trades: list[TradeEvent]) -> BotDailySummary:
        """Aggregate trade list into daily summary stats."""
        if not trades:
            return BotDailySummary(date=self.date, bot_id=self.bot_id)

        wins = [t for t in trades if t.pnl > 0]
        losses = [t for t in trades if t.pnl <= 0]
        gross_pnl = sum(t.pnl for t in trades)
        avg_win = sum(t.pnl for t in wins) / len(wins) if wins else 0.0
        avg_loss = sum(t.pnl for t in losses) / len(losses) if losses else 0.0
        avg_pq = sum(t.process_quality_score for t in trades) / len(trades)

        return BotDailySummary(
            date=self.date,
            bot_id=self.bot_id,
            total_trades=len(trades),
            win_count=len(wins),
            loss_count=len(losses),
            gross_pnl=gross_pnl,
            net_pnl=gross_pnl,  # fees not separately tracked yet
            avg_win=avg_win,
            avg_loss=avg_loss,
            avg_process_quality=avg_pq,
        )

    def top_winners(self, trades: list[TradeEvent], n: int = 5) -> list[WinnerLoserRecord]:
        """Top N winning trades by PnL, descending."""
        wins = sorted([t for t in trades if t.pnl > 0], key=lambda t: t.pnl, reverse=True)
        return [self._to_winner_loser(t) for t in wins[:n]]

    def top_losers(self, trades: list[TradeEvent], n: int = 5) -> list[WinnerLoserRecord]:
        """Top N losing trades by PnL, ascending (most negative first)."""
        losses = sorted([t for t in trades if t.pnl <= 0], key=lambda t: t.pnl)
        return [self._to_winner_loser(t) for t in losses[:n]]

    def process_failures(
        self, trades: list[TradeEvent], threshold: int = 60
    ) -> list[ProcessFailureRecord]:
        """Trades with process_quality_score below threshold."""
        return [
            ProcessFailureRecord(
                trade_id=t.trade_id,
                bot_id=t.bot_id,
                pair=t.pair,
                process_quality_score=t.process_quality_score,
                root_causes=t.root_causes,
                pnl=t.pnl,
                entry_signal=t.entry_signal,
                market_regime=t.market_regime,
            )
            for t in trades
            if t.process_quality_score < threshold
        ]

    def notable_missed(
        self,
        missed: list[MissedOpportunityEvent],
        trades: list[TradeEvent],
    ) -> list[NotableMissedRecord]:
        """Missed opportunities where outcome > 2× average win."""
        wins = [t for t in trades if t.pnl > 0]
        avg_win = sum(t.pnl for t in wins) / len(wins) if wins else 0.0
        threshold = 2.0 * avg_win if avg_win > 0 else float("inf")

        return [
            NotableMissedRecord(
                bot_id=m.bot_id,
                pair=m.pair,
                signal=m.signal,
                blocked_by=m.blocked_by,
                hypothetical_entry=m.hypothetical_entry,
                outcome_24h=m.outcome_24h or 0.0,
                confidence=m.confidence,
                assumption_tags=m.assumption_tags,
            )
            for m in missed
            if (m.outcome_24h or 0.0) > threshold
        ]

    def regime_analysis(self, trades: list[TradeEvent]) -> RegimeAnalysis:
        """PnL breakdown by market regime."""
        regime_pnl: dict[str, float] = defaultdict(float)
        regime_count: dict[str, int] = defaultdict(int)
        regime_wins: dict[str, int] = defaultdict(int)

        for t in trades:
            regime = t.market_regime or "unknown"
            regime_pnl[regime] += t.pnl
            regime_count[regime] += 1
            if t.pnl > 0:
                regime_wins[regime] += 1

        regime_win_rate = {
            r: regime_wins.get(r, 0) / c for r, c in regime_count.items()
        }

        return RegimeAnalysis(
            bot_id=self.bot_id,
            date=self.date,
            regime_pnl=dict(regime_pnl),
            regime_trade_count=dict(regime_count),
            regime_win_rate=regime_win_rate,
        )

    def filter_analysis(self, missed: list[MissedOpportunityEvent]) -> FilterAnalysis:
        """Impact analysis for each filter."""
        block_counts: dict[str, int] = defaultdict(int)
        saved_pnl: dict[str, float] = defaultdict(float)
        missed_pnl: dict[str, float] = defaultdict(float)

        for m in missed:
            filt = m.blocked_by or "unknown"
            block_counts[filt] += 1
            outcome = m.outcome_24h or 0.0
            if outcome <= 0:
                saved_pnl[filt] += abs(outcome)
            else:
                missed_pnl[filt] += outcome

        return FilterAnalysis(
            bot_id=self.bot_id,
            date=self.date,
            filter_block_counts=dict(block_counts),
            filter_saved_pnl=dict(saved_pnl),
            filter_missed_pnl=dict(missed_pnl),
        )

    def root_cause_summary(self, trades: list[TradeEvent]) -> RootCauseSummary:
        """Distribution of root causes across all trades."""
        dist: dict[str, int] = defaultdict(int)
        for t in trades:
            for cause in t.root_causes:
                dist[cause] += 1

        return RootCauseSummary(
            bot_id=self.bot_id,
            date=self.date,
            distribution=dict(dist),
            total_trades=len(trades),
        )

    def write_curated(
        self,
        trades: list[TradeEvent],
        missed: list[MissedOpportunityEvent],
        base_dir: Path,
    ) -> Path:
        """Write all curated files to base_dir/<date>/<bot_id>/. Returns output dir."""
        output_dir = base_dir / self.date / self.bot_id
        output_dir.mkdir(parents=True, exist_ok=True)

        summary = self.build_summary(trades)
        winners = self.top_winners(trades)
        losers = self.top_losers(trades)
        failures = self.process_failures(trades)
        notable = self.notable_missed(missed, trades)
        regime = self.regime_analysis(trades)
        filters = self.filter_analysis(missed)
        root_causes = self.root_cause_summary(trades)

        self._write_json(output_dir / "summary.json", summary.model_dump(mode="json"))
        self._write_json(output_dir / "winners.json", [w.model_dump(mode="json") for w in winners])
        self._write_json(output_dir / "losers.json", [l.model_dump(mode="json") for l in losers])
        self._write_json(output_dir / "process_failures.json", [f.model_dump(mode="json") for f in failures])
        self._write_json(output_dir / "notable_missed.json", [n.model_dump(mode="json") for n in notable])
        self._write_json(output_dir / "regime_analysis.json", regime.model_dump(mode="json"))
        self._write_json(output_dir / "filter_analysis.json", filters.model_dump(mode="json"))
        self._write_json(output_dir / "root_cause_summary.json", root_causes.model_dump(mode="json"))

        return output_dir

    def _write_json(self, path: Path, data: dict | list) -> None:
        path.write_text(json.dumps(data, indent=2, default=str))

    def _to_winner_loser(self, t: TradeEvent) -> WinnerLoserRecord:
        return WinnerLoserRecord(
            trade_id=t.trade_id,
            bot_id=t.bot_id,
            pair=t.pair,
            side=t.side,
            pnl=t.pnl,
            pnl_pct=t.pnl_pct,
            entry_signal=t.entry_signal,
            exit_reason=t.exit_reason,
            market_regime=t.market_regime,
            process_quality_score=t.process_quality_score,
            root_causes=t.root_causes,
            entry_price=t.entry_price,
            exit_price=t.exit_price,
            atr_at_entry=t.atr_at_entry,
        )
```

**Step 4: Run test to verify it passes**

Run: `venv/Scripts/python -m pytest tests/test_daily_metrics_pipeline.py -v`
Expected: All 10 tests PASS

**Step 5: Commit**

```bash
git add skills/__init__.py skills/build_daily_metrics.py tests/test_daily_metrics_pipeline.py
git commit -m "feat: implement data reduction pipeline for daily metrics"
```

---

## Task 5: Portfolio Risk Computation — `compute_portfolio_risk.py`

**Files:**
- Create: `skills/compute_portfolio_risk.py`
- Test: `tests/test_portfolio_risk_computation.py`

**Step 1: Write the failing tests**

```python
# tests/test_portfolio_risk_computation.py
"""Tests for cross-bot portfolio risk computation."""
from schemas.daily_metrics import BotDailySummary
from schemas.portfolio_risk import PortfolioRiskCard, CrowdingAlert
from skills.compute_portfolio_risk import PortfolioRiskComputer


def _make_summary(bot_id: str, exposure_pct: float = 20.0, **kwargs) -> BotDailySummary:
    defaults = dict(
        date="2026-03-01",
        bot_id=bot_id,
        total_trades=10,
        win_count=6,
        loss_count=4,
        gross_pnl=100.0,
        exposure_pct=exposure_pct,
    )
    defaults.update(kwargs)
    return BotDailySummary(**defaults)


class TestPortfolioRiskComputer:
    def test_total_exposure(self):
        summaries = [
            _make_summary("bot1", exposure_pct=30.0),
            _make_summary("bot2", exposure_pct=25.0),
        ]
        computer = PortfolioRiskComputer(
            date="2026-03-01",
            bot_summaries=summaries,
            position_details={
                "bot1": [{"symbol": "BTC", "direction": "LONG", "exposure_pct": 30.0}],
                "bot2": [{"symbol": "ETH", "direction": "LONG", "exposure_pct": 25.0}],
            },
        )
        card = computer.compute()
        assert card.total_exposure_pct == 55.0

    def test_exposure_by_symbol(self):
        computer = PortfolioRiskComputer(
            date="2026-03-01",
            bot_summaries=[_make_summary("bot1"), _make_summary("bot2")],
            position_details={
                "bot1": [{"symbol": "BTC", "direction": "LONG", "exposure_pct": 30.0}],
                "bot2": [{"symbol": "BTC", "direction": "LONG", "exposure_pct": 25.0}],
            },
        )
        card = computer.compute()
        assert card.exposure_by_symbol["BTC"] == 55.0

    def test_exposure_by_direction(self):
        computer = PortfolioRiskComputer(
            date="2026-03-01",
            bot_summaries=[_make_summary("bot1"), _make_summary("bot2")],
            position_details={
                "bot1": [{"symbol": "BTC", "direction": "LONG", "exposure_pct": 30.0}],
                "bot2": [{"symbol": "BTC", "direction": "SHORT", "exposure_pct": 10.0}],
            },
        )
        card = computer.compute()
        assert card.exposure_by_direction["LONG"] == 30.0
        assert card.exposure_by_direction["SHORT"] == 10.0

    def test_single_symbol_concentration_alert(self):
        computer = PortfolioRiskComputer(
            date="2026-03-01",
            bot_summaries=[_make_summary("bot1"), _make_summary("bot2")],
            position_details={
                "bot1": [{"symbol": "BTC", "direction": "LONG", "exposure_pct": 40.0}],
                "bot2": [{"symbol": "BTC", "direction": "LONG", "exposure_pct": 20.0}],
            },
            max_single_symbol_pct=50.0,
        )
        card = computer.compute()
        btc_alerts = [a for a in card.crowding_alerts if a.symbol == "BTC"]
        assert len(btc_alerts) == 1
        assert btc_alerts[0].alert_type == "single_symbol_concentration"

    def test_same_side_alert(self):
        computer = PortfolioRiskComputer(
            date="2026-03-01",
            bot_summaries=[_make_summary("b1"), _make_summary("b2"), _make_summary("b3")],
            position_details={
                "b1": [{"symbol": "BTC", "direction": "LONG", "exposure_pct": 10.0}],
                "b2": [{"symbol": "BTC", "direction": "LONG", "exposure_pct": 10.0}],
                "b3": [{"symbol": "BTC", "direction": "LONG", "exposure_pct": 10.0}],
            },
        )
        card = computer.compute()
        same_side = [a for a in card.crowding_alerts if a.alert_type == "same_side"]
        assert len(same_side) == 1

    def test_total_exposure_alert(self):
        computer = PortfolioRiskComputer(
            date="2026-03-01",
            bot_summaries=[_make_summary("bot1"), _make_summary("bot2")],
            position_details={
                "bot1": [{"symbol": "BTC", "direction": "LONG", "exposure_pct": 50.0}],
                "bot2": [{"symbol": "ETH", "direction": "LONG", "exposure_pct": 60.0}],
            },
            max_total_exposure_pct=80.0,
        )
        card = computer.compute()
        total_alerts = [a for a in card.crowding_alerts if a.alert_type == "total_exposure"]
        assert len(total_alerts) == 1

    def test_concentration_score(self):
        # All in one symbol = high concentration
        computer = PortfolioRiskComputer(
            date="2026-03-01",
            bot_summaries=[_make_summary("bot1")],
            position_details={
                "bot1": [{"symbol": "BTC", "direction": "LONG", "exposure_pct": 100.0}],
            },
        )
        card = computer.compute()
        assert card.concentration_score > 80  # single symbol = highly concentrated

    def test_no_alerts_when_diversified(self):
        computer = PortfolioRiskComputer(
            date="2026-03-01",
            bot_summaries=[_make_summary("bot1"), _make_summary("bot2")],
            position_details={
                "bot1": [{"symbol": "BTC", "direction": "LONG", "exposure_pct": 10.0}],
                "bot2": [{"symbol": "ETH", "direction": "SHORT", "exposure_pct": 10.0}],
            },
        )
        card = computer.compute()
        assert card.crowding_alerts == []
```

**Step 2: Run test to verify it fails**

Run: `venv/Scripts/python -m pytest tests/test_portfolio_risk_computation.py -v`
Expected: FAIL with `ModuleNotFoundError`

**Step 3: Write minimal implementation**

```python
# skills/compute_portfolio_risk.py
"""Cross-bot portfolio risk computation — daily, no LLM calls.

Computes exposure, concentration, and crowding alerts.
If crowding alerts trigger, the daily report leads with them.
"""
from __future__ import annotations

from collections import defaultdict

from schemas.daily_metrics import BotDailySummary
from schemas.portfolio_risk import PortfolioRiskCard, CrowdingAlert


class PortfolioRiskComputer:
    """Computes a PortfolioRiskCard from bot summaries and position details."""

    def __init__(
        self,
        date: str,
        bot_summaries: list[BotDailySummary],
        position_details: dict[str, list[dict]],
        max_single_symbol_pct: float = 50.0,
        max_total_exposure_pct: float = 80.0,
        correlation_threshold: float = 0.7,
    ) -> None:
        self.date = date
        self.bot_summaries = bot_summaries
        self.position_details = position_details  # bot_id → [{symbol, direction, exposure_pct}]
        self.max_single_symbol_pct = max_single_symbol_pct
        self.max_total_exposure_pct = max_total_exposure_pct
        self.correlation_threshold = correlation_threshold

    def compute(self) -> PortfolioRiskCard:
        """Build the full risk card."""
        exposure_by_symbol = self._compute_exposure_by_symbol()
        exposure_by_direction = self._compute_exposure_by_direction()
        total_exposure = sum(exposure_by_symbol.values())
        concentration_score = self._compute_concentration_score(exposure_by_symbol, total_exposure)
        alerts = self._detect_alerts(exposure_by_symbol, exposure_by_direction, total_exposure)

        return PortfolioRiskCard(
            date=self.date,
            total_exposure_pct=total_exposure,
            exposure_by_symbol=exposure_by_symbol,
            exposure_by_direction=exposure_by_direction,
            concentration_score=concentration_score,
            crowding_alerts=alerts,
        )

    def _compute_exposure_by_symbol(self) -> dict[str, float]:
        by_symbol: dict[str, float] = defaultdict(float)
        for positions in self.position_details.values():
            for pos in positions:
                by_symbol[pos["symbol"]] += pos["exposure_pct"]
        return dict(by_symbol)

    def _compute_exposure_by_direction(self) -> dict[str, float]:
        by_dir: dict[str, float] = defaultdict(float)
        for positions in self.position_details.values():
            for pos in positions:
                by_dir[pos["direction"]] += pos["exposure_pct"]
        return dict(by_dir)

    def _compute_concentration_score(
        self, exposure_by_symbol: dict[str, float], total_exposure: float
    ) -> float:
        """Herfindahl-Hirschman Index normalized to 0–100. Higher = more concentrated."""
        if total_exposure == 0:
            return 0.0
        shares = [exp / total_exposure for exp in exposure_by_symbol.values()]
        hhi = sum(s * s for s in shares)
        # HHI ranges from 1/N (perfectly diversified) to 1.0 (single symbol)
        # Normalize: 0 = perfectly diversified, 100 = single symbol
        n = len(shares)
        if n <= 1:
            return 100.0
        min_hhi = 1.0 / n
        return ((hhi - min_hhi) / (1.0 - min_hhi)) * 100.0

    def _detect_alerts(
        self,
        exposure_by_symbol: dict[str, float],
        exposure_by_direction: dict[str, float],
        total_exposure: float,
    ) -> list[CrowdingAlert]:
        alerts: list[CrowdingAlert] = []

        # Single symbol concentration
        for symbol, exp in exposure_by_symbol.items():
            pct_of_total = (exp / total_exposure * 100) if total_exposure > 0 else 0
            if exp > self.max_single_symbol_pct:
                alerts.append(CrowdingAlert(
                    alert_type="single_symbol_concentration",
                    description=f"{symbol} > {self.max_single_symbol_pct}% of total exposure ({exp:.1f}%)",
                    severity="medium",
                    symbol=symbol,
                    exposure_pct=exp,
                ))

        # Total exposure too high
        if total_exposure > self.max_total_exposure_pct:
            alerts.append(CrowdingAlert(
                alert_type="total_exposure",
                description=f"Total exposure {total_exposure:.1f}% exceeds {self.max_total_exposure_pct}%",
                severity="high",
            ))

        # All bots on same side of same symbol
        symbol_direction_bots: dict[tuple[str, str], list[str]] = defaultdict(list)
        for bot_id, positions in self.position_details.items():
            for pos in positions:
                key = (pos["symbol"], pos["direction"])
                symbol_direction_bots[key].append(bot_id)

        for (symbol, direction), bots in symbol_direction_bots.items():
            if len(bots) >= 3:  # 3+ bots on same side of same asset
                alerts.append(CrowdingAlert(
                    alert_type="same_side",
                    description=f"{len(bots)} bots all {direction} on {symbol}",
                    severity="high",
                    bots_involved=bots,
                    symbol=symbol,
                ))

        return alerts
```

**Step 4: Run test to verify it passes**

Run: `venv/Scripts/python -m pytest tests/test_portfolio_risk_computation.py -v`
Expected: All 8 tests PASS

**Step 5: Commit**

```bash
git add skills/compute_portfolio_risk.py tests/test_portfolio_risk_computation.py
git commit -m "feat: implement cross-bot portfolio risk computation"
```

---

## Task 6: Report Quality Gate

**Files:**
- Create: `analysis/__init__.py`
- Create: `analysis/quality_gate.py`
- Test: `tests/test_quality_gate.py`

**Step 1: Write the failing tests**

```python
# tests/test_quality_gate.py
"""Tests for the report quality gate."""
import json
from pathlib import Path

import pytest

from schemas.report_checklist import ReportChecklist
from analysis.quality_gate import QualityGate


class TestQualityGate:
    def test_all_pass_with_complete_data(self, tmp_path: Path):
        """Full bot data present → all checks pass."""
        bot_dir = tmp_path / "2026-03-01" / "bot1"
        bot_dir.mkdir(parents=True)

        # Write all expected files
        (bot_dir / "summary.json").write_text(json.dumps({
            "bot_id": "bot1", "date": "2026-03-01", "total_trades": 10,
            "error_count": 0, "avg_process_quality": 85,
        }))
        (bot_dir / "winners.json").write_text("[]")
        (bot_dir / "losers.json").write_text("[]")
        (bot_dir / "process_failures.json").write_text("[]")
        (bot_dir / "notable_missed.json").write_text("[]")
        (bot_dir / "regime_analysis.json").write_text("{}")
        (bot_dir / "filter_analysis.json").write_text("{}")
        (bot_dir / "root_cause_summary.json").write_text(json.dumps({
            "distribution": {"normal_win": 6, "normal_loss": 4}, "total_trades": 10,
        }))

        # Portfolio risk card at date level
        risk_dir = tmp_path / "2026-03-01"
        (risk_dir / "portfolio_risk_card.json").write_text(json.dumps({
            "date": "2026-03-01", "total_exposure_pct": 30.0, "crowding_alerts": [],
        }))

        gate = QualityGate(
            report_id="daily-2026-03-01",
            date="2026-03-01",
            expected_bots=["bot1"],
            curated_dir=tmp_path,
        )
        checklist = gate.run()

        assert checklist.overall == "PASS"

    def test_fails_when_bot_missing(self, tmp_path: Path):
        gate = QualityGate(
            report_id="daily-2026-03-01",
            date="2026-03-01",
            expected_bots=["bot1", "bot2"],
            curated_dir=tmp_path,
        )
        checklist = gate.run()
        assert checklist.overall == "FAIL"
        assert any("all_bots_reported" in issue for issue in checklist.blocking_issues)

    def test_fails_when_risk_card_missing(self, tmp_path: Path):
        bot_dir = tmp_path / "2026-03-01" / "bot1"
        bot_dir.mkdir(parents=True)
        for f in ["summary.json", "winners.json", "losers.json", "process_failures.json",
                   "notable_missed.json", "regime_analysis.json", "filter_analysis.json",
                   "root_cause_summary.json"]:
            (bot_dir / f).write_text("{}" if not f.endswith("s.json") else "[]")

        gate = QualityGate(
            report_id="daily-2026-03-01",
            date="2026-03-01",
            expected_bots=["bot1"],
            curated_dir=tmp_path,
        )
        checklist = gate.run()
        assert checklist.overall == "FAIL"
        assert any("portfolio_risk_card" in issue for issue in checklist.blocking_issues)

    def test_fails_when_curated_file_missing(self, tmp_path: Path):
        bot_dir = tmp_path / "2026-03-01" / "bot1"
        bot_dir.mkdir(parents=True)
        # Only write some files, skip root_cause_summary
        for f in ["summary.json", "winners.json", "losers.json", "process_failures.json",
                   "notable_missed.json", "regime_analysis.json", "filter_analysis.json"]:
            (bot_dir / f).write_text("{}" if not f.endswith("s.json") else "[]")

        (tmp_path / "2026-03-01" / "portfolio_risk_card.json").write_text("{}")

        gate = QualityGate(
            report_id="daily-2026-03-01",
            date="2026-03-01",
            expected_bots=["bot1"],
            curated_dir=tmp_path,
        )
        checklist = gate.run()
        assert checklist.overall == "FAIL"

    def test_writes_checklist_json(self, tmp_path: Path):
        gate = QualityGate(
            report_id="daily-2026-03-01",
            date="2026-03-01",
            expected_bots=["bot1"],
            curated_dir=tmp_path,
        )
        checklist = gate.run()
        output_path = tmp_path / "2026-03-01" / "report_checklist.json"
        gate.write_checklist(checklist, output_path)

        assert output_path.exists()
        data = json.loads(output_path.read_text())
        assert data["report_id"] == "daily-2026-03-01"
```

**Step 2: Run test to verify it fails**

Run: `venv/Scripts/python -m pytest tests/test_quality_gate.py -v`
Expected: FAIL with `ModuleNotFoundError`

**Step 3: Write minimal implementation**

Create `analysis/__init__.py` (empty file).

```python
# analysis/quality_gate.py
"""Report quality gate — Definition of Done for daily reports.

Validates that all expected curated data exists and is complete before
the orchestrator assembles a context package for Claude.
"""
from __future__ import annotations

import json
from pathlib import Path

from schemas.report_checklist import ReportChecklist, CheckResult

_EXPECTED_BOT_FILES = [
    "summary.json",
    "winners.json",
    "losers.json",
    "process_failures.json",
    "notable_missed.json",
    "regime_analysis.json",
    "filter_analysis.json",
    "root_cause_summary.json",
]


class QualityGate:
    """Runs all quality checks for a daily report."""

    def __init__(
        self,
        report_id: str,
        date: str,
        expected_bots: list[str],
        curated_dir: Path,
    ) -> None:
        self.report_id = report_id
        self.date = date
        self.expected_bots = expected_bots
        self.curated_dir = curated_dir

    def run(self) -> ReportChecklist:
        """Run all checks and return the checklist."""
        checks: list[CheckResult] = []

        checks.append(self._check_all_bots_reported())
        checks.extend(self._check_curated_files())
        checks.append(self._check_portfolio_risk_card())

        return ReportChecklist(report_id=self.report_id, checks=checks)

    def write_checklist(self, checklist: ReportChecklist, output_path: Path) -> None:
        """Write the checklist to a JSON file."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(checklist.model_dump(mode="json"), indent=2, default=str)
        )

    def _check_all_bots_reported(self) -> CheckResult:
        date_dir = self.curated_dir / self.date
        found = []
        missing = []
        for bot in self.expected_bots:
            if (date_dir / bot).is_dir():
                found.append(bot)
            else:
                missing.append(bot)

        if missing:
            return CheckResult(
                name="all_bots_reported",
                passed=False,
                detail=f"Missing: {', '.join(missing)} ({len(found)}/{len(self.expected_bots)} bots)",
            )
        return CheckResult(
            name="all_bots_reported",
            passed=True,
            detail=f"{len(found)}/{len(self.expected_bots)} bots",
        )

    def _check_curated_files(self) -> list[CheckResult]:
        results: list[CheckResult] = []
        date_dir = self.curated_dir / self.date

        for bot in self.expected_bots:
            bot_dir = date_dir / bot
            if not bot_dir.is_dir():
                continue  # already caught by all_bots_reported

            missing = [f for f in _EXPECTED_BOT_FILES if not (bot_dir / f).exists()]
            if missing:
                results.append(CheckResult(
                    name=f"curated_files_{bot}",
                    passed=False,
                    detail=f"Missing: {', '.join(missing)}",
                ))
            else:
                results.append(CheckResult(
                    name=f"curated_files_{bot}",
                    passed=True,
                    detail="All files present",
                ))

        return results

    def _check_portfolio_risk_card(self) -> CheckResult:
        risk_path = self.curated_dir / self.date / "portfolio_risk_card.json"
        if risk_path.exists():
            return CheckResult(
                name="portfolio_risk_card",
                passed=True,
                detail="Computed",
            )
        return CheckResult(
            name="portfolio_risk_card",
            passed=False,
            detail="Portfolio risk card not computed",
        )
```

**Step 4: Run test to verify it passes**

Run: `venv/Scripts/python -m pytest tests/test_quality_gate.py -v`
Expected: All 5 tests PASS

**Step 5: Commit**

```bash
git add analysis/__init__.py analysis/quality_gate.py tests/test_quality_gate.py
git commit -m "feat: implement report quality gate with Definition of Done checks"
```

---

## Task 7: Prompt Assembler

Builds the context package for the daily analysis Claude invocation as described in roadmap section 2.4.

**Files:**
- Create: `analysis/prompt_assembler.py`
- Test: `tests/test_prompt_assembler.py`

**Step 1: Write the failing tests**

```python
# tests/test_prompt_assembler.py
"""Tests for the daily analysis prompt assembler."""
import json
from pathlib import Path

import pytest

from analysis.prompt_assembler import DailyPromptAssembler


@pytest.fixture
def curated_dir(tmp_path: Path) -> Path:
    """Set up a minimal curated data directory."""
    date_dir = tmp_path / "data" / "curated" / "2026-03-01"

    # Bot1 data
    bot_dir = date_dir / "bot1"
    bot_dir.mkdir(parents=True)
    (bot_dir / "summary.json").write_text(json.dumps({
        "bot_id": "bot1", "date": "2026-03-01", "total_trades": 10,
        "win_count": 6, "loss_count": 4, "net_pnl": 150.0,
    }))
    (bot_dir / "winners.json").write_text(json.dumps([
        {"trade_id": "t1", "pnl": 200.0, "pair": "BTCUSDT"},
    ]))
    (bot_dir / "losers.json").write_text(json.dumps([
        {"trade_id": "t2", "pnl": -50.0, "pair": "ETHUSDT"},
    ]))
    (bot_dir / "process_failures.json").write_text("[]")
    (bot_dir / "notable_missed.json").write_text("[]")
    (bot_dir / "regime_analysis.json").write_text(json.dumps({"regime_pnl": {"trending_up": 150.0}}))
    (bot_dir / "filter_analysis.json").write_text(json.dumps({"filter_block_counts": {}}))
    (bot_dir / "root_cause_summary.json").write_text(json.dumps({"distribution": {"normal_win": 6}}))

    # Portfolio risk card
    (date_dir / "portfolio_risk_card.json").write_text(json.dumps({
        "date": "2026-03-01", "total_exposure_pct": 30.0, "crowding_alerts": [],
    }))

    return tmp_path / "data" / "curated"


@pytest.fixture
def memory_dir(tmp_path: Path) -> Path:
    """Set up a minimal memory directory."""
    mem = tmp_path / "memory"
    policies = mem / "policies" / "v1"
    policies.mkdir(parents=True)
    (policies / "agents.md").write_text("You are a trading analyst.")
    (policies / "trading_rules.md").write_text("Max 3 suggestions.")
    (policies / "soul.md").write_text("Be helpful.")

    findings = mem / "findings"
    findings.mkdir(parents=True)
    (findings / "corrections.jsonl").write_text("")
    (findings / "prompt_patterns.jsonl").write_text("")

    return mem


class TestDailyPromptAssembler:
    def test_assembles_system_prompt(self, curated_dir: Path, memory_dir: Path):
        assembler = DailyPromptAssembler(
            date="2026-03-01",
            bots=["bot1"],
            curated_dir=curated_dir,
            memory_dir=memory_dir,
        )
        prompt = assembler.assemble()

        assert "system_prompt" in prompt
        assert "You are a trading analyst" in prompt["system_prompt"]
        assert "Max 3 suggestions" in prompt["system_prompt"]

    def test_assembles_task_prompt(self, curated_dir: Path, memory_dir: Path):
        assembler = DailyPromptAssembler(
            date="2026-03-01",
            bots=["bot1"],
            curated_dir=curated_dir,
            memory_dir=memory_dir,
        )
        prompt = assembler.assemble()

        assert "task_prompt" in prompt
        assert "bot1" in prompt["task_prompt"]
        assert "2026-03-01" in prompt["task_prompt"]

    def test_includes_structured_data(self, curated_dir: Path, memory_dir: Path):
        assembler = DailyPromptAssembler(
            date="2026-03-01",
            bots=["bot1"],
            curated_dir=curated_dir,
            memory_dir=memory_dir,
        )
        prompt = assembler.assemble()

        assert "data" in prompt
        assert "bot1" in prompt["data"]
        assert "summary" in prompt["data"]["bot1"]

    def test_includes_portfolio_risk_card(self, curated_dir: Path, memory_dir: Path):
        assembler = DailyPromptAssembler(
            date="2026-03-01",
            bots=["bot1"],
            curated_dir=curated_dir,
            memory_dir=memory_dir,
        )
        prompt = assembler.assemble()

        assert "portfolio_risk_card" in prompt["data"]

    def test_includes_instructions(self, curated_dir: Path, memory_dir: Path):
        assembler = DailyPromptAssembler(
            date="2026-03-01",
            bots=["bot1"],
            curated_dir=curated_dir,
            memory_dir=memory_dir,
        )
        prompt = assembler.assemble()

        assert "instructions" in prompt
        assert "portfolio-level picture" in prompt["instructions"]
        assert "actionable" in prompt["instructions"].lower()

    def test_includes_corrections_context(self, curated_dir: Path, memory_dir: Path):
        # Write a correction
        corrections_path = memory_dir / "findings" / "corrections.jsonl"
        corrections_path.write_text(json.dumps({
            "correction_type": "trade_reclassify",
            "original_report_id": "daily-2026-02-28",
            "raw_text": "That was a hedge",
            "timestamp": "2026-02-28T12:00:00Z",
        }) + "\n")

        assembler = DailyPromptAssembler(
            date="2026-03-01",
            bots=["bot1"],
            curated_dir=curated_dir,
            memory_dir=memory_dir,
            corrections_lookback_days=30,
        )
        prompt = assembler.assemble()
        assert "corrections" in prompt
        assert len(prompt["corrections"]) == 1

    def test_context_file_list(self, curated_dir: Path, memory_dir: Path):
        assembler = DailyPromptAssembler(
            date="2026-03-01",
            bots=["bot1"],
            curated_dir=curated_dir,
            memory_dir=memory_dir,
        )
        prompt = assembler.assemble()

        assert "context_files" in prompt
        assert len(prompt["context_files"]) > 0
```

**Step 2: Run test to verify it fails**

Run: `venv/Scripts/python -m pytest tests/test_prompt_assembler.py -v`
Expected: FAIL with `ModuleNotFoundError`

**Step 3: Write minimal implementation**

```python
# analysis/prompt_assembler.py
"""Prompt assembler — builds the context package for the daily analysis Claude invocation.

Follows the prompt structure from roadmap section 2.4:
  SYSTEM PROMPT: policies + corrections + patterns
  TASK PROMPT: "Analyze today's trading performance for all bots."
  DATA: curated summaries + risk card
  INSTRUCTIONS: structured analysis steps
"""
from __future__ import annotations

import json
from pathlib import Path

_CURATED_FILES = [
    "summary.json",
    "winners.json",
    "losers.json",
    "process_failures.json",
    "notable_missed.json",
    "regime_analysis.json",
    "filter_analysis.json",
    "root_cause_summary.json",
]

_INSTRUCTIONS = """\
1. Start with portfolio-level picture (total PnL, drawdown, exposure, crowding alerts)
2. For each bot:
   a. What worked: winning pattern (regime + signal combo + process quality)
   b. What failed: distinguish PROCESS errors from NORMAL LOSSES using root cause tags
   c. Missed opportunities: quantify filter impact, note simulation assumptions
   d. Anomalies: anything statistically unusual
3. Cross-bot patterns: correlation, regime alignment, crowding risk
4. Actionable items: max 3 specific, testable suggestions
5. Open risks: any CRITICAL/HIGH events that need human attention
6. Output: daily_report.md + report_checklist.json"""


class DailyPromptAssembler:
    """Assembles the full context package for a daily analysis agent invocation."""

    def __init__(
        self,
        date: str,
        bots: list[str],
        curated_dir: Path,
        memory_dir: Path,
        corrections_lookback_days: int = 30,
    ) -> None:
        self.date = date
        self.bots = bots
        self.curated_dir = curated_dir
        self.memory_dir = memory_dir
        self.corrections_lookback_days = corrections_lookback_days

    def assemble(self) -> dict:
        """Build the complete prompt package."""
        system_prompt = self._build_system_prompt()
        task_prompt = self._build_task_prompt()
        data = self._load_structured_data()
        corrections = self._load_corrections()
        context_files = self._list_context_files()

        return {
            "system_prompt": system_prompt,
            "task_prompt": task_prompt,
            "data": data,
            "instructions": _INSTRUCTIONS,
            "corrections": corrections,
            "context_files": context_files,
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
            f"Analyze today's ({self.date}) trading performance for all bots: {bot_list}.\n"
            f"Use the structured data provided. Follow the instructions exactly."
        )

    def _load_structured_data(self) -> dict:
        data: dict = {}
        date_dir = self.curated_dir / self.date

        for bot in self.bots:
            bot_dir = date_dir / bot
            bot_data: dict = {}
            for filename in _CURATED_FILES:
                path = bot_dir / filename
                if path.exists():
                    key = filename.replace(".json", "")
                    bot_data[key] = json.loads(path.read_text())
            data[bot] = bot_data

        risk_path = date_dir / "portfolio_risk_card.json"
        if risk_path.exists():
            data["portfolio_risk_card"] = json.loads(risk_path.read_text())

        return data

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
        date_dir = self.curated_dir / self.date

        for bot in self.bots:
            bot_dir = date_dir / bot
            for filename in _CURATED_FILES:
                path = bot_dir / filename
                if path.exists():
                    files.append(str(path))

        risk_path = date_dir / "portfolio_risk_card.json"
        if risk_path.exists():
            files.append(str(risk_path))

        policy_dir = self.memory_dir / "policies" / "v1"
        for name in ["agents.md", "trading_rules.md", "soul.md"]:
            path = policy_dir / name
            if path.exists():
                files.append(str(path))

        return files
```

**Step 4: Run test to verify it passes**

Run: `venv/Scripts/python -m pytest tests/test_prompt_assembler.py -v`
Expected: All 7 tests PASS

**Step 5: Commit**

```bash
git add analysis/prompt_assembler.py tests/test_prompt_assembler.py
git commit -m "feat: implement daily analysis prompt assembler"
```

---

## Task 8: Feedback Handler

Parses human reply text, classifies correction type, and writes structured corrections to `memory/findings/corrections.jsonl`.

**Files:**
- Create: `analysis/feedback_handler.py`
- Test: `tests/test_feedback_handler.py`

**Step 1: Write the failing tests**

```python
# tests/test_feedback_handler.py
"""Tests for the human feedback handler."""
import json
from pathlib import Path

import pytest

from schemas.corrections import HumanCorrection, CorrectionType
from analysis.feedback_handler import FeedbackHandler


class TestFeedbackHandler:
    def test_parse_trade_reclassify(self):
        handler = FeedbackHandler(report_id="daily-2026-03-01")
        correction = handler.parse(
            "Trade #xyz wasn't bad — it was a planned hedge against spot"
        )
        assert correction.correction_type == CorrectionType.TRADE_RECLASSIFY
        assert correction.target_id == "xyz"
        assert correction.raw_text == "Trade #xyz wasn't bad — it was a planned hedge against spot"

    def test_parse_regime_override(self):
        handler = FeedbackHandler(report_id="daily-2026-03-01")
        correction = handler.parse(
            "Bot2's regime classification was wrong today, it was a slow trend not ranging"
        )
        assert correction.correction_type == CorrectionType.REGIME_OVERRIDE
        assert "bot2" in correction.target_id.lower()

    def test_parse_positive_reinforcement(self):
        handler = FeedbackHandler(report_id="daily-2026-03-01")
        correction = handler.parse(
            "Good catch on the volume filter, that's the third time this week"
        )
        assert correction.correction_type == CorrectionType.POSITIVE_REINFORCEMENT

    def test_parse_free_text(self):
        handler = FeedbackHandler(report_id="daily-2026-03-01")
        correction = handler.parse("Interesting day overall, keep monitoring ETH")
        assert correction.correction_type == CorrectionType.FREE_TEXT

    def test_write_to_jsonl(self, tmp_path: Path):
        corrections_path = tmp_path / "corrections.jsonl"
        handler = FeedbackHandler(report_id="daily-2026-03-01")

        correction = handler.parse("Trade #abc was actually fine")
        handler.write_correction(correction, corrections_path)

        lines = corrections_path.read_text().strip().splitlines()
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["correction_type"] == "trade_reclassify"

    def test_appends_to_existing_file(self, tmp_path: Path):
        corrections_path = tmp_path / "corrections.jsonl"
        corrections_path.write_text('{"existing": true}\n')

        handler = FeedbackHandler(report_id="daily-2026-03-01")
        correction = handler.parse("Good catch on volume filter")
        handler.write_correction(correction, corrections_path)

        lines = corrections_path.read_text().strip().splitlines()
        assert len(lines) == 2
```

**Step 2: Run test to verify it fails**

Run: `venv/Scripts/python -m pytest tests/test_feedback_handler.py -v`
Expected: FAIL with `ModuleNotFoundError`

**Step 3: Write minimal implementation**

```python
# analysis/feedback_handler.py
"""Feedback handler — parses human reply text into structured corrections.

Human replies on Telegram/Discord are parsed into HumanCorrection objects and
appended to memory/findings/corrections.jsonl. Future analysis prompts include
recent corrections as context (Ralph Loop V2).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from schemas.corrections import HumanCorrection, CorrectionType


class FeedbackHandler:
    """Parses human feedback text and writes structured corrections."""

    def __init__(self, report_id: str) -> None:
        self.report_id = report_id

    def parse(self, text: str) -> HumanCorrection:
        """Classify and parse a human feedback message."""
        # Pattern: Trade #<id> ...
        trade_match = re.search(r"[Tt]rade\s*#(\w+)", text)
        if trade_match:
            return HumanCorrection(
                correction_type=CorrectionType.TRADE_RECLASSIFY,
                original_report_id=self.report_id,
                target_id=trade_match.group(1),
                raw_text=text,
            )

        # Pattern: Bot<N>'s regime ... wrong
        regime_match = re.search(r"(bot\w+).*regime.*wrong", text, re.IGNORECASE)
        if regime_match:
            return HumanCorrection(
                correction_type=CorrectionType.REGIME_OVERRIDE,
                original_report_id=self.report_id,
                target_id=regime_match.group(1),
                raw_text=text,
            )

        # Pattern: Good catch, nice, well done, etc.
        positive_patterns = [
            r"good\s+catch",
            r"nice\s+catch",
            r"well\s+done",
            r"great\s+(analysis|catch|job)",
            r"spot\s+on",
        ]
        for pattern in positive_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                return HumanCorrection(
                    correction_type=CorrectionType.POSITIVE_REINFORCEMENT,
                    original_report_id=self.report_id,
                    raw_text=text,
                )

        # Default: free text
        return HumanCorrection(
            correction_type=CorrectionType.FREE_TEXT,
            original_report_id=self.report_id,
            raw_text=text,
        )

    def write_correction(self, correction: HumanCorrection, path: Path) -> None:
        """Append a correction to the JSONL file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(correction.model_dump(mode="json"), default=str) + "\n")
```

**Step 4: Run test to verify it passes**

Run: `venv/Scripts/python -m pytest tests/test_feedback_handler.py -v`
Expected: All 6 tests PASS

**Step 5: Commit**

```bash
git add analysis/feedback_handler.py tests/test_feedback_handler.py
git commit -m "feat: implement human feedback handler with pattern-based classification"
```

---

## Task 9: Wire Orchestrator Brain — Daily Analysis Trigger

Modify the orchestrator brain and scheduler to trigger daily analysis at a configured time. Add a new `SPAWN_DAILY_ANALYSIS` action that the worker dispatches by running the data reduction pipeline, quality gate, and prompt assembler.

**Files:**
- Modify: `orchestrator/orchestrator_brain.py`
- Modify: `orchestrator/scheduler.py`
- Modify: `orchestrator/worker.py`
- Test: `tests/test_daily_analysis_wiring.py`

**Step 1: Write the failing tests**

```python
# tests/test_daily_analysis_wiring.py
"""Tests for daily analysis wiring — brain trigger, scheduler cron, worker dispatch."""
import pytest

from orchestrator.orchestrator_brain import OrchestratorBrain, ActionType
from orchestrator.scheduler import SchedulerConfig, create_scheduler_jobs


class TestBrainDailyTrigger:
    def test_daily_analysis_trigger_event(self):
        brain = OrchestratorBrain()
        event = {
            "event_type": "daily_analysis_trigger",
            "event_id": "cron-daily-2026-03-01",
            "bot_id": "_system",
            "payload": '{"date": "2026-03-01"}',
        }
        actions = brain.decide(event)
        assert len(actions) == 1
        assert actions[0].type == ActionType.SPAWN_DAILY_ANALYSIS


class TestSchedulerDailyCron:
    def test_scheduler_includes_daily_analysis_job(self):
        config = SchedulerConfig()

        async def noop():
            pass

        jobs = create_scheduler_jobs(
            config=config,
            worker_fn=noop,
            monitoring_fn=noop,
            relay_fn=noop,
            daily_analysis_fn=noop,
        )
        job_names = [j["name"] for j in jobs]
        assert "daily_analysis" in job_names

    def test_daily_analysis_default_cron(self):
        config = SchedulerConfig()

        async def noop():
            pass

        jobs = create_scheduler_jobs(
            config=config,
            worker_fn=noop,
            monitoring_fn=noop,
            relay_fn=noop,
            daily_analysis_fn=noop,
        )
        daily_job = next(j for j in jobs if j["name"] == "daily_analysis")
        assert daily_job["trigger"] == "cron"
        assert daily_job["hour"] == config.daily_analysis_hour
```

**Step 2: Run test to verify it fails**

Run: `venv/Scripts/python -m pytest tests/test_daily_analysis_wiring.py -v`
Expected: FAIL — `daily_analysis_trigger` not in brain handlers

**Step 3: Implement changes**

**Modify `orchestrator/orchestrator_brain.py`** — add `daily_analysis_trigger` handler:

Add after `_handle_heartbeat`:

```python
    def _handle_daily_analysis_trigger(self, event_id: str, bot_id: str, event: dict) -> list[Action]:
        return [Action(type=ActionType.SPAWN_DAILY_ANALYSIS, event_id=event_id, bot_id=bot_id)]
```

Add to `_handlers` dict:

```python
        "daily_analysis_trigger": _handle_daily_analysis_trigger,
```

**Modify `orchestrator/scheduler.py`** — add `daily_analysis_hour` config and cron job:

Replace `SchedulerConfig`:

```python
@dataclass
class SchedulerConfig:
    monitoring_interval_minutes: int = 10
    worker_interval_seconds: int = 60
    relay_poll_interval_seconds: int = 300
    daily_analysis_hour: int = 6  # UTC hour to run daily analysis
    daily_analysis_minute: int = 0
```

Replace `create_scheduler_jobs` signature and body:

```python
def create_scheduler_jobs(
    config: SchedulerConfig,
    worker_fn: Callable[[], Awaitable[None]],
    monitoring_fn: Callable[[], Awaitable[None]],
    relay_fn: Callable[[], Awaitable[None]],
    daily_analysis_fn: Callable[[], Awaitable[None]] | None = None,
) -> list[dict]:
    """Build job definitions for APScheduler."""
    jobs = [
        {
            "name": "worker",
            "func": worker_fn,
            "trigger": "interval",
            "seconds": config.worker_interval_seconds,
        },
        {
            "name": "monitoring",
            "func": monitoring_fn,
            "trigger": "interval",
            "seconds": config.monitoring_interval_minutes * 60,
        },
        {
            "name": "relay_poll",
            "func": relay_fn,
            "trigger": "interval",
            "seconds": config.relay_poll_interval_seconds,
        },
    ]

    if daily_analysis_fn is not None:
        jobs.append({
            "name": "daily_analysis",
            "func": daily_analysis_fn,
            "trigger": "cron",
            "hour": config.daily_analysis_hour,
            "minute": config.daily_analysis_minute,
        })

    return jobs
```

**Modify `orchestrator/worker.py`** — add `SPAWN_DAILY_ANALYSIS` dispatch:

Add to `__init__` after existing handlers:

```python
        self.on_daily_analysis: Callable[[Action], Awaitable[None]] | None = None
```

Add to `_dispatch` method before the `LOG_UNKNOWN` elif:

```python
        elif action.type == ActionType.SPAWN_DAILY_ANALYSIS:
            if self.on_daily_analysis:
                await self.on_daily_analysis(action)
            else:
                logger.info("Daily analysis triggered but no handler set: %s", action.event_id)
```

**Step 4: Run test to verify it passes**

Run: `venv/Scripts/python -m pytest tests/test_daily_analysis_wiring.py -v`
Expected: All 3 tests PASS

**Step 5: Run full test suite**

Run: `venv/Scripts/python -m pytest tests/ -v`
Expected: All existing tests still pass + new tests pass

**Step 6: Commit**

```bash
git add orchestrator/orchestrator_brain.py orchestrator/scheduler.py orchestrator/worker.py tests/test_daily_analysis_wiring.py
git commit -m "feat: wire daily analysis trigger into brain, scheduler, and worker"
```

---

## Task 10: Integration Test — Full Daily Pipeline

End-to-end test: create trade events → run data reduction → compute risk → quality gate → prompt assembly.

**Files:**
- Create: `tests/test_daily_integration.py`

**Step 1: Write the integration test**

```python
# tests/test_daily_integration.py
"""Integration test — full daily analysis pipeline end-to-end."""
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from schemas.events import TradeEvent, MissedOpportunityEvent
from skills.build_daily_metrics import DailyMetricsBuilder
from skills.compute_portfolio_risk import PortfolioRiskComputer
from analysis.quality_gate import QualityGate
from analysis.prompt_assembler import DailyPromptAssembler


def _make_trades(bot_id: str, n: int = 10) -> list[TradeEvent]:
    now = datetime.now(timezone.utc)
    trades = []
    for i in range(n):
        pnl = 100.0 if i % 3 != 0 else -50.0
        trades.append(TradeEvent(
            trade_id=f"{bot_id}_t{i}",
            bot_id=bot_id,
            pair="BTCUSDT",
            side="LONG",
            entry_time=now,
            exit_time=now,
            entry_price=50000.0,
            exit_price=50000.0 + pnl,
            position_size=1.0,
            pnl=pnl,
            pnl_pct=pnl / 500.0,
            entry_signal="EMA cross",
            exit_reason="TAKE_PROFIT" if pnl > 0 else "STOP_LOSS",
            market_regime="trending_up",
            process_quality_score=85 if pnl > 0 else 55,
            root_causes=["normal_win"] if pnl > 0 else ["regime_mismatch"],
        ))
    return trades


def _make_missed(bot_id: str) -> list[MissedOpportunityEvent]:
    return [
        MissedOpportunityEvent(
            bot_id=bot_id,
            pair="ETHUSDT",
            signal="RSI divergence",
            blocked_by="volatility_filter",
            hypothetical_entry=3000.0,
            outcome_24h=500.0,
            confidence=0.7,
            assumption_tags=["mid_fill"],
        ),
    ]


class TestDailyPipelineIntegration:
    def test_full_pipeline(self, tmp_path: Path):
        date = "2026-03-01"
        bots = ["bot1", "bot2"]
        curated_dir = tmp_path / "curated"
        memory_dir = tmp_path / "memory"

        # --- Step 1: Data reduction ---
        for bot_id in bots:
            trades = _make_trades(bot_id)
            missed = _make_missed(bot_id)
            builder = DailyMetricsBuilder(date=date, bot_id=bot_id)
            builder.write_curated(trades, missed, base_dir=curated_dir)

        # Verify curated files exist
        for bot_id in bots:
            bot_dir = curated_dir / date / bot_id
            assert (bot_dir / "summary.json").exists()
            assert (bot_dir / "winners.json").exists()

        # --- Step 2: Portfolio risk ---
        summaries = []
        for bot_id in bots:
            summary_data = json.loads((curated_dir / date / bot_id / "summary.json").read_text())
            from schemas.daily_metrics import BotDailySummary
            summaries.append(BotDailySummary(**summary_data))

        computer = PortfolioRiskComputer(
            date=date,
            bot_summaries=summaries,
            position_details={
                "bot1": [{"symbol": "BTC", "direction": "LONG", "exposure_pct": 20.0}],
                "bot2": [{"symbol": "ETH", "direction": "LONG", "exposure_pct": 15.0}],
            },
        )
        risk_card = computer.compute()
        risk_path = curated_dir / date / "portfolio_risk_card.json"
        risk_path.write_text(json.dumps(risk_card.model_dump(mode="json"), indent=2))

        # --- Step 3: Quality gate ---
        gate = QualityGate(
            report_id=f"daily-{date}",
            date=date,
            expected_bots=bots,
            curated_dir=curated_dir,
        )
        checklist = gate.run()
        assert checklist.overall == "PASS", f"Quality gate failed: {checklist.blocking_issues}"

        # --- Step 4: Prompt assembly ---
        # Set up memory dir
        policies_dir = memory_dir / "policies" / "v1"
        policies_dir.mkdir(parents=True)
        (policies_dir / "agents.md").write_text("You are a trading analyst.")
        (policies_dir / "trading_rules.md").write_text("Max 3 suggestions.")
        (policies_dir / "soul.md").write_text("Be helpful.")
        findings_dir = memory_dir / "findings"
        findings_dir.mkdir(parents=True)
        (findings_dir / "corrections.jsonl").write_text("")
        (findings_dir / "prompt_patterns.jsonl").write_text("")

        assembler = DailyPromptAssembler(
            date=date,
            bots=bots,
            curated_dir=curated_dir,
            memory_dir=memory_dir,
        )
        prompt = assembler.assemble()

        assert "system_prompt" in prompt
        assert "task_prompt" in prompt
        assert "data" in prompt
        assert "bot1" in prompt["data"]
        assert "bot2" in prompt["data"]
        assert "portfolio_risk_card" in prompt["data"]
        assert "instructions" in prompt
        assert len(prompt["context_files"]) > 0
```

**Step 2: Run integration test**

Run: `venv/Scripts/python -m pytest tests/test_daily_integration.py -v`
Expected: PASS

**Step 3: Run full test suite**

Run: `venv/Scripts/python -m pytest tests/ -v`
Expected: All tests PASS

**Step 4: Commit**

```bash
git add tests/test_daily_integration.py
git commit -m "test: add end-to-end integration test for daily analysis pipeline"
```

---

## Task 11: Update `pyproject.toml` and `setuptools` Package Discovery

The new `skills/` and `analysis/` packages need to be included in setuptools discovery.

**Files:**
- Modify: `pyproject.toml`

**Step 1: Update `pyproject.toml`**

Change the `[tool.setuptools.packages.find]` section:

```toml
[tool.setuptools.packages.find]
include = ["orchestrator*", "relay*", "schemas*", "skills*", "analysis*"]
```

**Step 2: Verify tests still pass**

Run: `venv/Scripts/python -m pytest tests/ -v`
Expected: All tests PASS

**Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "chore: add skills and analysis packages to setuptools discovery"
```

---

## Summary

| Task | Component | Tests | Files Created | Files Modified |
|------|-----------|-------|---------------|----------------|
| 0 | Daily Metrics Schemas | 10 | `schemas/daily_metrics.py` | — |
| 1 | Portfolio Risk Schemas | 6 | `schemas/portfolio_risk.py` | — |
| 2 | Report Checklist Schema | 5 | `schemas/report_checklist.py` | — |
| 3 | Human Correction Schema | 5 | `schemas/corrections.py` | — |
| 4 | Data Reduction Pipeline | 10 | `skills/build_daily_metrics.py` | — |
| 5 | Portfolio Risk Computation | 8 | `skills/compute_portfolio_risk.py` | — |
| 6 | Report Quality Gate | 5 | `analysis/quality_gate.py` | — |
| 7 | Prompt Assembler | 7 | `analysis/prompt_assembler.py` | — |
| 8 | Feedback Handler | 6 | `analysis/feedback_handler.py` | — |
| 9 | Orchestrator Wiring | 3 | `tests/test_daily_analysis_wiring.py` | `orchestrator_brain.py`, `scheduler.py`, `worker.py` |
| 10 | Integration Test | 1 | `tests/test_daily_integration.py` | — |
| 11 | Package Config | 0 | — | `pyproject.toml` |
| **Total** | | **~66** | **10 new** | **4 modified** |
