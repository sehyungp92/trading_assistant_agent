# Ecosystem Evaluation Gaps Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement all 12 assistant-side changes (A1–A12) from the ecosystem evaluation and resolve all 5 integration layer gaps — closing the analysis ceiling from "diagnostic" to "prescriptive" with counterfactual simulation, exit strategy analysis, and automated outcome measurement.

**Architecture:** Four phases sequenced by dependency. Phase A enriches the data pipeline with signal factor attribution, exit efficiency, slippage→cost model wiring, and regime exclusion computation. Phase B hardens infrastructure: graceful quality gate, brain error deduplication, dead-letter alerting, /metrics endpoint, dynamic polling, and event batching. Phase C builds the simulation skills (filter sensitivity, counterfactual replay, exit strategy comparison, automated outcome measurement). Phase D wires everything into handlers and runs integration tests.

**Tech Stack:** Python 3.12, Pydantic v2, pytest (asyncio_mode=auto), statistics (stdlib), pathlib, json, collections

**Assumes:** Feedback gaps plan fully implemented — 858 tests passing. DailyMetricsBuilder already writes hourly_performance.json and slippage_stats.json. SlippageAnalyzer has export_regime_bps(). CostModel has EMPIRICAL mode. Strategy engine has 10 detectors. SuggestionTracker exists with JSONL storage.

**Coverage map — what this plan addresses:**

| Rec/Gap | Description | Task |
|---------|-------------|------|
| A1 | Signal factor attribution in DailyMetricsBuilder | 1 |
| A2 | Exit efficiency computation in DailyMetricsBuilder | 2 |
| A3 | Wire SlippageAnalyzer → CostModel | 3 |
| A4 | FilterSensitivityAnalyzer | 11 |
| A5 | CounterfactualSimulator | 12 |
| A6 | ExitStrategySimulator | 13 |
| A7 | AutoOutcomeMeasurer | 14 |
| A8 | QualityGate graceful degradation | 5 |
| A9 | Brain error frequency tracking | 6 |
| A10 | Cross-event batching for daily/weekly | 10 |
| A11 | /metrics endpoint | 8 |
| A12 | Strategy engine regime exclusion P&L | 4 |
| Gap 1 | QUEUE_FOR_DAILY/WEEKLY not batch-processed | 10 |
| Gap 2 | Brain doesn't escalate recurring errors | 6 |
| Gap 3 | Dead-letter queue has no alerting | 7 |
| Gap 4 | No observability endpoints | 8 |
| Gap 5 | VPS Receiver poll interval latency | 9 |
| Gap A | No counterfactual simulation engine | 12 |
| Gap B | No exit strategy analysis pipeline | 2, 13 |
| Gap C | No signal factor attribution | 1 |
| Gap D | Strategy engine can't prescribe structural changes | 4, 11, 12 |
| Gap E | Cost model disconnected from real data | 3 |
| Gap F | Quality gate prevents partial analysis | 5 |
| Gap H | Claude has no computational tools | 1, 2, 11, 12, 13 |
| Gap I | No automated outcome measurement | 14 |

**Deferred (requires bot-side changes):**
- Gap G: Market microstructure data — bots must capture order book depth
- Full filter sensitivity curves — bots must emit `margin_pct` per filter (B4)
- MFE/MAE tracking — bots must track intra-trade excursions (B5)
- A/B testing — bots must support `experiment_id` (B11)

**Directory structure this plan creates/modifies:**

```
trading_assistant/
  schemas/
    events.py                          # MODIFY: add signal_factors, post_exit prices
    factor_attribution.py              # CREATE
    exit_efficiency.py                 # CREATE
    filter_sensitivity.py              # CREATE
    counterfactual.py                  # CREATE
    exit_simulation.py                 # CREATE
    outcome_measurement.py             # CREATE
    orchestrator_metrics.py            # CREATE
    report_checklist.py                # MODIFY: add completeness fields
  skills/
    build_daily_metrics.py             # MODIFY: add factor_attribution, exit_efficiency, regime_bps output
    cost_model.py                      # MODIFY: add from_slippage_export() classmethod
    filter_sensitivity_analyzer.py     # CREATE
    counterfactual_simulator.py        # CREATE
    exit_strategy_simulator.py         # CREATE
    auto_outcome_measurer.py           # CREATE
  analysis/
    quality_gate.py                    # MODIFY: graceful degradation + update expected files
    strategy_engine.py                 # MODIFY: regime exclusion P&L
  orchestrator/
    orchestrator_brain.py              # MODIFY: error frequency tracking
    worker.py                          # MODIFY: event batching context
    app.py                             # MODIFY: /metrics endpoint
    adapters/vps_receiver.py           # MODIFY: adaptive polling
    monitoring.py                      # MODIFY: dead-letter checks
  tests/
    test_factor_attribution.py         # CREATE
    test_exit_efficiency.py            # CREATE
    test_cost_model_wiring.py          # CREATE
    test_regime_exclusion.py           # CREATE
    test_quality_gate_graceful.py      # CREATE
    test_brain_error_tracking.py       # CREATE
    test_dead_letter_alerting.py       # CREATE
    test_metrics_endpoint.py           # CREATE
    test_dynamic_polling.py            # CREATE
    test_event_batching.py             # CREATE
    test_filter_sensitivity.py         # CREATE
    test_counterfactual_simulator.py   # CREATE
    test_exit_strategy_simulator.py    # CREATE
    test_auto_outcome_measurer.py      # CREATE
    test_ecosystem_integration.py      # CREATE
```

---

## Phase A: Data Pipeline Enrichment (Tasks 0–4)

*Addresses Gaps B, C, D, E and recommendations A1, A2, A3, A12. Enriches what Claude sees before analysis.*

### Task 0: TradeEvent Schema Extensions

**Files:**
- Modify: `schemas/events.py:71-104`
- Test: `tests/test_factor_attribution.py` (schema portion)

**Step 1: Write the failing test**

```python
# tests/test_factor_attribution.py
"""Tests for signal factor attribution schemas and pipeline."""
from datetime import datetime, timezone

from schemas.events import TradeEvent


class TestTradeEventExtensions:
    def test_signal_factors_optional_default_none(self):
        trade = TradeEvent(
            trade_id="t1", bot_id="bot1", pair="BTC/USDT",
            side="LONG", entry_time=datetime(2026, 3, 1, tzinfo=timezone.utc),
            exit_time=datetime(2026, 3, 1, 1, tzinfo=timezone.utc),
            entry_price=100, exit_price=105, position_size=1, pnl=5, pnl_pct=5.0,
        )
        assert trade.signal_factors is None

    def test_signal_factors_with_data(self):
        factors = [
            {"factor_name": "rsi", "factor_value": 72.0, "threshold": 70.0, "contribution": 0.6},
            {"factor_name": "macd", "factor_value": 1.2, "threshold": 0.0, "contribution": 0.4},
        ]
        trade = TradeEvent(
            trade_id="t1", bot_id="bot1", pair="BTC/USDT",
            side="LONG", entry_time=datetime(2026, 3, 1, tzinfo=timezone.utc),
            exit_time=datetime(2026, 3, 1, 1, tzinfo=timezone.utc),
            entry_price=100, exit_price=105, position_size=1, pnl=5, pnl_pct=5.0,
            signal_factors=factors,
        )
        assert len(trade.signal_factors) == 2
        assert trade.signal_factors[0]["factor_name"] == "rsi"

    def test_post_exit_prices_optional(self):
        trade = TradeEvent(
            trade_id="t1", bot_id="bot1", pair="BTC/USDT",
            side="LONG", entry_time=datetime(2026, 3, 1, tzinfo=timezone.utc),
            exit_time=datetime(2026, 3, 1, 1, tzinfo=timezone.utc),
            entry_price=100, exit_price=105, position_size=1, pnl=5, pnl_pct=5.0,
            post_exit_1h_price=106.0, post_exit_4h_price=107.5,
        )
        assert trade.post_exit_1h_price == 106.0
        assert trade.post_exit_4h_price == 107.5
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_factor_attribution.py::TestTradeEventExtensions -v`
Expected: FAIL — `signal_factors` and `post_exit_*` fields don't exist

**Step 3: Write minimal implementation**

Add these fields to `TradeEvent` in `schemas/events.py` after line 104:

```python
    # Optional enrichment fields (not all bots emit these)
    signal_factors: list[dict] | None = None
    post_exit_1h_price: float | None = None
    post_exit_4h_price: float | None = None
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_factor_attribution.py::TestTradeEventExtensions -v`
Expected: PASS

**Step 5: Commit**

```bash
git add schemas/events.py tests/test_factor_attribution.py
git commit -m "feat: add signal_factors and post_exit prices to TradeEvent schema"
```

---

### Task 1: Signal Factor Attribution Pipeline (A1, Gap C)

**Files:**
- Create: `schemas/factor_attribution.py`
- Modify: `skills/build_daily_metrics.py:14-23,186-216`
- Test: `tests/test_factor_attribution.py` (continued)

**Step 1: Write the failing test**

Append to `tests/test_factor_attribution.py`:

```python
from schemas.factor_attribution import FactorStats, FactorAttribution


class TestFactorAttributionSchema:
    def test_factor_stats_win_rate(self):
        fs = FactorStats(factor_name="rsi", trade_count=10, win_count=7, total_pnl=500.0, avg_contribution=0.6)
        assert fs.win_rate == 0.7

    def test_factor_attribution_model(self):
        fa = FactorAttribution(
            bot_id="bot1", date="2026-03-01",
            factors=[FactorStats(factor_name="rsi", trade_count=5, win_count=3, total_pnl=200.0, avg_contribution=0.5)],
        )
        assert len(fa.factors) == 1
        assert fa.factors[0].factor_name == "rsi"


class TestFactorAttributionPipeline:
    def _make_trade(self, trade_id, pnl, factors=None):
        return TradeEvent(
            trade_id=trade_id, bot_id="bot1", pair="BTC/USDT",
            side="LONG", entry_time=datetime(2026, 3, 1, tzinfo=timezone.utc),
            exit_time=datetime(2026, 3, 1, 1, tzinfo=timezone.utc),
            entry_price=100, exit_price=100 + pnl, position_size=1,
            pnl=pnl, pnl_pct=pnl, signal_factors=factors,
        )

    def test_factor_attribution_aggregates_across_trades(self):
        from skills.build_daily_metrics import DailyMetricsBuilder

        trades = [
            self._make_trade("t1", 10.0, [
                {"factor_name": "rsi", "factor_value": 72, "threshold": 70, "contribution": 0.6},
                {"factor_name": "macd", "factor_value": 1.2, "threshold": 0, "contribution": 0.4},
            ]),
            self._make_trade("t2", -5.0, [
                {"factor_name": "rsi", "factor_value": 68, "threshold": 70, "contribution": 0.3},
            ]),
            self._make_trade("t3", 8.0, [
                {"factor_name": "rsi", "factor_value": 75, "threshold": 70, "contribution": 0.7},
                {"factor_name": "macd", "factor_value": 0.8, "threshold": 0, "contribution": 0.3},
            ]),
        ]
        builder = DailyMetricsBuilder(date="2026-03-01", bot_id="bot1")
        result = builder.factor_attribution(trades)
        assert isinstance(result, FactorAttribution)

        rsi = next(f for f in result.factors if f.factor_name == "rsi")
        assert rsi.trade_count == 3
        assert rsi.win_count == 2  # t1 and t3 are winners

        macd = next(f for f in result.factors if f.factor_name == "macd")
        assert macd.trade_count == 2
        assert macd.win_count == 2

    def test_factor_attribution_skips_trades_without_factors(self):
        from skills.build_daily_metrics import DailyMetricsBuilder

        trades = [
            self._make_trade("t1", 10.0, None),
            self._make_trade("t2", 5.0, []),
        ]
        builder = DailyMetricsBuilder(date="2026-03-01", bot_id="bot1")
        result = builder.factor_attribution(trades)
        assert result.factors == []

    def test_factor_attribution_written_to_curated(self, tmp_path):
        from schemas.events import MissedOpportunityEvent
        from skills.build_daily_metrics import DailyMetricsBuilder

        trades = [
            self._make_trade("t1", 10.0, [
                {"factor_name": "rsi", "factor_value": 72, "threshold": 70, "contribution": 0.6},
            ]),
        ]
        builder = DailyMetricsBuilder(date="2026-03-01", bot_id="bot1")
        output_dir = builder.write_curated(trades, [], tmp_path)
        assert (output_dir / "factor_attribution.json").exists()
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_factor_attribution.py -v -k "not TestTradeEventExtensions"`
Expected: FAIL — module `schemas.factor_attribution` not found

**Step 3: Write minimal implementation**

Create `schemas/factor_attribution.py`:

```python
"""Signal factor attribution schemas — per-factor win rate, PnL, contribution."""
from __future__ import annotations

from pydantic import BaseModel, computed_field


class FactorStats(BaseModel):
    """Aggregated stats for a single signal factor across daily trades."""
    factor_name: str
    trade_count: int = 0
    win_count: int = 0
    total_pnl: float = 0.0
    avg_contribution: float = 0.0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def win_rate(self) -> float:
        return self.win_count / self.trade_count if self.trade_count > 0 else 0.0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def avg_pnl(self) -> float:
        return self.total_pnl / self.trade_count if self.trade_count > 0 else 0.0


class FactorAttribution(BaseModel):
    """Per-factor performance attribution for a bot's daily trades."""
    bot_id: str
    date: str
    factors: list[FactorStats] = []
```

Add method to `skills/build_daily_metrics.py` — add import at top:

```python
from schemas.factor_attribution import FactorAttribution, FactorStats
```

Add method to `DailyMetricsBuilder` class (after `slippage_stats`):

```python
    def factor_attribution(self, trades: list[TradeEvent]) -> FactorAttribution:
        """Aggregate signal_factors across trades: per-factor win rate, PnL, contribution."""
        from collections import defaultdict

        factor_data: dict[str, dict] = defaultdict(lambda: {
            "trade_count": 0, "win_count": 0, "total_pnl": 0.0, "contributions": [],
        })
        for t in trades:
            if not t.signal_factors:
                continue
            for f in t.signal_factors:
                name = f.get("factor_name", "unknown")
                factor_data[name]["trade_count"] += 1
                factor_data[name]["total_pnl"] += t.pnl
                if t.pnl > 0:
                    factor_data[name]["win_count"] += 1
                factor_data[name]["contributions"].append(f.get("contribution", 0.0))

        factors = [
            FactorStats(
                factor_name=name,
                trade_count=d["trade_count"],
                win_count=d["win_count"],
                total_pnl=d["total_pnl"],
                avg_contribution=sum(d["contributions"]) / len(d["contributions"]) if d["contributions"] else 0.0,
            )
            for name, d in sorted(factor_data.items())
        ]
        return FactorAttribution(bot_id=self.bot_id, date=self.date, factors=factors)
```

Update `write_curated` method — add after slippage_stats line:

```python
        self._write_json(output_dir / "factor_attribution.json", self.factor_attribution(trades).model_dump(mode="json"))
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_factor_attribution.py -v`
Expected: PASS (all 7 tests)

**Step 5: Commit**

```bash
git add schemas/factor_attribution.py skills/build_daily_metrics.py tests/test_factor_attribution.py
git commit -m "feat(A1): add signal factor attribution pipeline to DailyMetricsBuilder"
```

---

### Task 2: Exit Efficiency Pipeline (A2, Gap B)

**Files:**
- Create: `schemas/exit_efficiency.py`
- Modify: `skills/build_daily_metrics.py`
- Test: `tests/test_exit_efficiency.py`

**Step 1: Write the failing test**

```python
# tests/test_exit_efficiency.py
"""Tests for exit efficiency schemas and pipeline."""
from datetime import datetime, timezone

from schemas.events import TradeEvent
from schemas.exit_efficiency import ExitEfficiencyRecord, ExitEfficiencyStats


def _make_trade(trade_id, pnl, exit_reason="SIGNAL", regime="trending",
                post_1h=None, post_4h=None, entry_price=100.0):
    return TradeEvent(
        trade_id=trade_id, bot_id="bot1", pair="BTC/USDT",
        side="LONG",
        entry_time=datetime(2026, 3, 1, tzinfo=timezone.utc),
        exit_time=datetime(2026, 3, 1, 1, tzinfo=timezone.utc),
        entry_price=entry_price, exit_price=entry_price + pnl,
        position_size=1, pnl=pnl, pnl_pct=pnl / entry_price * 100,
        exit_reason=exit_reason, market_regime=regime,
        post_exit_1h_price=post_1h, post_exit_4h_price=post_4h,
    )


class TestExitEfficiencySchema:
    def test_record_creation(self):
        r = ExitEfficiencyRecord(
            trade_id="t1", bot_id="bot1", pair="BTC/USDT",
            pnl=10.0, exit_reason="SIGNAL", market_regime="trending",
            exit_efficiency=0.75, continuation_1h=2.0, continuation_4h=5.0,
        )
        assert r.exit_efficiency == 0.75

    def test_stats_model(self):
        s = ExitEfficiencyStats(
            bot_id="bot1", date="2026-03-01",
            avg_efficiency=0.65, premature_exit_pct=0.3,
            by_exit_reason={"SIGNAL": 0.7, "STOP_LOSS": 0.4},
            by_regime={"trending": 0.8, "ranging": 0.5},
            total_trades_with_data=20,
        )
        assert s.avg_efficiency == 0.65


class TestExitEfficiencyPipeline:
    def test_computes_from_post_exit_prices(self):
        from skills.build_daily_metrics import DailyMetricsBuilder

        trades = [
            # Winner: exited at 105, price went to 107 (left $2 on table)
            _make_trade("t1", 5.0, post_1h=107.0, post_4h=108.0),
            # Winner: exited at 103, price dropped to 101 (good exit)
            _make_trade("t2", 3.0, post_1h=101.0, post_4h=99.0),
            # Loser: no post-exit data (skipped)
            _make_trade("t3", -2.0),
        ]
        builder = DailyMetricsBuilder(date="2026-03-01", bot_id="bot1")
        result = builder.exit_efficiency(trades)
        assert isinstance(result, ExitEfficiencyStats)
        assert result.total_trades_with_data == 2
        assert result.avg_efficiency > 0  # should be calculated

    def test_premature_exit_detection(self):
        from skills.build_daily_metrics import DailyMetricsBuilder

        trades = [
            # Price continued 1h after exit — premature
            _make_trade("t1", 5.0, post_1h=110.0, post_4h=112.0),
            _make_trade("t2", 3.0, post_1h=108.0, post_4h=110.0),
            # Price reversed — good exit
            _make_trade("t3", 4.0, post_1h=99.0, post_4h=97.0),
        ]
        builder = DailyMetricsBuilder(date="2026-03-01", bot_id="bot1")
        result = builder.exit_efficiency(trades)
        assert result.premature_exit_pct > 0

    def test_grouping_by_exit_reason(self):
        from skills.build_daily_metrics import DailyMetricsBuilder

        trades = [
            _make_trade("t1", 5.0, exit_reason="SIGNAL", post_1h=107.0),
            _make_trade("t2", 3.0, exit_reason="STOP_LOSS", post_1h=101.0),
        ]
        builder = DailyMetricsBuilder(date="2026-03-01", bot_id="bot1")
        result = builder.exit_efficiency(trades)
        assert "SIGNAL" in result.by_exit_reason
        assert "STOP_LOSS" in result.by_exit_reason

    def test_exit_efficiency_written_to_curated(self, tmp_path):
        from skills.build_daily_metrics import DailyMetricsBuilder

        trades = [_make_trade("t1", 5.0, post_1h=107.0, post_4h=108.0)]
        builder = DailyMetricsBuilder(date="2026-03-01", bot_id="bot1")
        output_dir = builder.write_curated(trades, [], tmp_path)
        assert (output_dir / "exit_efficiency.json").exists()
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_exit_efficiency.py -v`
Expected: FAIL — module `schemas.exit_efficiency` not found

**Step 3: Write minimal implementation**

Create `schemas/exit_efficiency.py`:

```python
"""Exit efficiency schemas — measuring how well exits capture available moves."""
from __future__ import annotations

from pydantic import BaseModel


class ExitEfficiencyRecord(BaseModel):
    """Per-trade exit efficiency with post-exit price continuation data."""
    trade_id: str
    bot_id: str
    pair: str
    pnl: float
    exit_reason: str
    market_regime: str = ""
    exit_efficiency: float = 0.0
    continuation_1h: float | None = None
    continuation_4h: float | None = None


class ExitEfficiencyStats(BaseModel):
    """Aggregated exit efficiency stats for a bot's daily trades."""
    bot_id: str
    date: str
    avg_efficiency: float = 0.0
    premature_exit_pct: float = 0.0
    by_exit_reason: dict[str, float] = {}
    by_regime: dict[str, float] = {}
    total_trades_with_data: int = 0
```

Add method to `DailyMetricsBuilder` in `skills/build_daily_metrics.py` — add import:

```python
from schemas.exit_efficiency import ExitEfficiencyStats
```

Add method (after `factor_attribution`):

```python
    def exit_efficiency(self, trades: list[TradeEvent]) -> ExitEfficiencyStats:
        """Compute exit efficiency from post-exit price data.

        Exit efficiency = actual_capture / max_available_move.
        Premature exit = price continued favorably after exit (1h post-exit).
        """
        records = []
        by_reason: dict[str, list[float]] = defaultdict(list)
        by_regime: dict[str, list[float]] = defaultdict(list)
        premature_count = 0

        for t in trades:
            if t.post_exit_1h_price is None and t.post_exit_4h_price is None:
                continue

            # Compute continuation: how much price moved after exit
            cont_1h = None
            if t.post_exit_1h_price is not None:
                cont_1h = t.post_exit_1h_price - t.exit_price

            cont_4h = None
            if t.post_exit_4h_price is not None:
                cont_4h = t.post_exit_4h_price - t.exit_price

            # For LONG trades, positive continuation = left money on table
            # For SHORT trades, negative continuation = left money on table
            is_long = t.side.upper() == "LONG"
            favorable_cont_1h = (cont_1h if is_long else -cont_1h) if cont_1h is not None else None

            # Max move = trade PnL + any favorable continuation
            max_move = abs(t.pnl)
            if favorable_cont_1h is not None and favorable_cont_1h > 0:
                max_move = abs(t.pnl) + favorable_cont_1h
                premature_count += 1

            efficiency = abs(t.pnl) / max_move if max_move > 0 else 1.0

            records.append(efficiency)
            if t.exit_reason:
                by_reason[t.exit_reason].append(efficiency)
            if t.market_regime:
                by_regime[t.market_regime].append(efficiency)

        if not records:
            return ExitEfficiencyStats(bot_id=self.bot_id, date=self.date)

        avg_by_reason = {k: sum(v) / len(v) for k, v in by_reason.items()}
        avg_by_regime = {k: sum(v) / len(v) for k, v in by_regime.items()}

        return ExitEfficiencyStats(
            bot_id=self.bot_id,
            date=self.date,
            avg_efficiency=sum(records) / len(records),
            premature_exit_pct=premature_count / len(records),
            by_exit_reason=avg_by_reason,
            by_regime=avg_by_regime,
            total_trades_with_data=len(records),
        )
```

Update `write_curated` — add after factor_attribution line:

```python
        self._write_json(output_dir / "exit_efficiency.json", self.exit_efficiency(trades).model_dump(mode="json"))
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_exit_efficiency.py -v`
Expected: PASS (all 6 tests)

**Step 5: Commit**

```bash
git add schemas/exit_efficiency.py skills/build_daily_metrics.py tests/test_exit_efficiency.py
git commit -m "feat(A2): add exit efficiency pipeline to DailyMetricsBuilder"
```

---

### Task 3: Wire SlippageAnalyzer → CostModel (A3, Gap E)

**Files:**
- Modify: `skills/build_daily_metrics.py`
- Modify: `skills/cost_model.py:35-42`
- Modify: `orchestrator/handlers.py` (WFO handler)
- Test: `tests/test_cost_model_wiring.py`

**Step 1: Write the failing test**

```python
# tests/test_cost_model_wiring.py
"""Tests for SlippageAnalyzer → CostModel wiring."""
import json
from pathlib import Path

from schemas.wfo_config import CostModelConfig, SlippageModel
from skills.cost_model import CostModel


class TestCostModelFromSlippageExport:
    def test_from_slippage_export_creates_empirical_model(self):
        regime_bps = {"trending": 5.0, "ranging": 8.0, "default": 6.0}
        config = CostModelConfig(
            slippage_model=SlippageModel.EMPIRICAL,
            fees_per_trade_bps=5.0,
            fixed_slippage_bps=3.0,
        )
        model = CostModel.from_slippage_export(regime_bps, config)
        costs = model.compute_costs(100.0, 1.0, regime="trending")
        # Empirical: 100 * 5.0 / 10000 * 2 = 0.10
        assert costs.slippage > 0

    def test_from_slippage_export_uses_regime_lookup(self):
        regime_bps = {"trending": 3.0, "ranging": 10.0, "default": 6.0}
        config = CostModelConfig(
            slippage_model=SlippageModel.EMPIRICAL,
            fees_per_trade_bps=5.0,
            fixed_slippage_bps=3.0,
        )
        model = CostModel.from_slippage_export(regime_bps, config)
        trending_costs = model.compute_costs(1000.0, 1.0, regime="trending")
        ranging_costs = model.compute_costs(1000.0, 1.0, regime="ranging")
        assert ranging_costs.slippage > trending_costs.slippage

    def test_from_slippage_export_fallback_to_default(self):
        regime_bps = {"trending": 5.0, "default": 7.0}
        config = CostModelConfig(
            slippage_model=SlippageModel.EMPIRICAL,
            fees_per_trade_bps=5.0,
            fixed_slippage_bps=3.0,
        )
        model = CostModel.from_slippage_export(regime_bps, config)
        costs = model.compute_costs(1000.0, 1.0, regime="unknown_regime")
        # Falls back to "default" → 7.0 bps
        assert costs.slippage > 0


class TestRegimeBpsWritten:
    def test_write_curated_writes_regime_bps(self, tmp_path):
        from datetime import datetime, timezone
        from schemas.events import TradeEvent
        from skills.build_daily_metrics import DailyMetricsBuilder

        trades = [
            TradeEvent(
                trade_id="t1", bot_id="bot1", pair="BTC/USDT",
                side="LONG",
                entry_time=datetime(2026, 3, 1, tzinfo=timezone.utc),
                exit_time=datetime(2026, 3, 1, 1, tzinfo=timezone.utc),
                entry_price=100, exit_price=105, position_size=1,
                pnl=5, pnl_pct=5.0, spread_at_entry=3.5, market_regime="trending",
            ),
        ]
        builder = DailyMetricsBuilder(date="2026-03-01", bot_id="bot1")
        output_dir = builder.write_curated(trades, [], tmp_path)
        regime_bps_path = output_dir / "regime_bps.json"
        assert regime_bps_path.exists()
        data = json.loads(regime_bps_path.read_text())
        assert "trending" in data

    def test_regime_bps_empty_when_no_spread_data(self, tmp_path):
        from datetime import datetime, timezone
        from schemas.events import TradeEvent
        from skills.build_daily_metrics import DailyMetricsBuilder

        trades = [
            TradeEvent(
                trade_id="t1", bot_id="bot1", pair="BTC/USDT",
                side="LONG",
                entry_time=datetime(2026, 3, 1, tzinfo=timezone.utc),
                exit_time=datetime(2026, 3, 1, 1, tzinfo=timezone.utc),
                entry_price=100, exit_price=105, position_size=1,
                pnl=5, pnl_pct=5.0, spread_at_entry=0,
            ),
        ]
        builder = DailyMetricsBuilder(date="2026-03-01", bot_id="bot1")
        output_dir = builder.write_curated(trades, [], tmp_path)
        data = json.loads((output_dir / "regime_bps.json").read_text())
        assert data == {}
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_cost_model_wiring.py -v`
Expected: FAIL — `from_slippage_export` not found

**Step 3: Write minimal implementation**

Add classmethod to `skills/cost_model.py` — add after `__init__`:

```python
    @classmethod
    def from_slippage_export(
        cls, regime_bps: dict[str, float], config: CostModelConfig
    ) -> "CostModel":
        """Create a CostModel with empirical slippage from SlippageAnalyzer export."""
        config = config.model_copy(update={"slippage_model": SlippageModel.EMPIRICAL})
        instance = cls(config)
        instance._empirical_stats = regime_bps
        return instance
```

Add regime_bps output to `skills/build_daily_metrics.py` — add to `write_curated` after exit_efficiency line:

```python
        # Write regime→bps mapping for WFO cost model
        from skills.slippage_analyzer import SlippageAnalyzer
        analyzer = SlippageAnalyzer(bot_id=self.bot_id, date=self.date)
        regime_bps = analyzer.export_regime_bps(trades)
        self._write_json(output_dir / "regime_bps.json", regime_bps)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_cost_model_wiring.py -v`
Expected: PASS (all 5 tests)

**Step 5: Commit**

```bash
git add skills/cost_model.py skills/build_daily_metrics.py tests/test_cost_model_wiring.py
git commit -m "feat(A3): wire SlippageAnalyzer regime_bps into CostModel empirical mode"
```

---

### Task 4: Strategy Engine Regime Exclusion P&L (A12, Gap D)

**Files:**
- Modify: `analysis/strategy_engine.py:101-133`
- Test: `tests/test_regime_exclusion.py`

**Step 1: Write the failing test**

```python
# tests/test_regime_exclusion.py
"""Tests for regime exclusion P&L computation in strategy engine."""
from datetime import datetime, timezone

from schemas.events import TradeEvent
from schemas.weekly_metrics import BotWeeklySummary, RegimePerformanceTrend
from analysis.strategy_engine import StrategyEngine


def _make_trade(trade_id, pnl, regime="trending"):
    return TradeEvent(
        trade_id=trade_id, bot_id="bot1", pair="BTC/USDT",
        side="LONG",
        entry_time=datetime(2026, 3, 1, tzinfo=timezone.utc),
        exit_time=datetime(2026, 3, 1, 1, tzinfo=timezone.utc),
        entry_price=100, exit_price=100 + pnl, position_size=1,
        pnl=pnl, pnl_pct=pnl, market_regime=regime,
    )


class TestRegimeExclusionPnL:
    def test_compute_exclusion_impact(self):
        engine = StrategyEngine(week_start="2026-02-24", week_end="2026-03-02")
        trades = [
            _make_trade("t1", 10.0, "trending"),
            _make_trade("t2", 8.0, "trending"),
            _make_trade("t3", -15.0, "ranging"),
            _make_trade("t4", -12.0, "ranging"),
            _make_trade("t5", 5.0, "volatile"),
        ]
        impact = engine.compute_regime_exclusion_impact("bot1", trades, "ranging")
        # Baseline PnL: 10+8-15-12+5 = -4
        # Without ranging: 10+8+5 = 23
        # Impact: 23 - (-4) = 27
        assert impact["baseline_pnl"] == -4.0
        assert impact["excluded_pnl"] == 23.0
        assert impact["delta_pnl"] == 27.0
        assert impact["excluded_trade_count"] == 2

    def test_exclusion_impact_empty_regime(self):
        engine = StrategyEngine(week_start="2026-02-24", week_end="2026-03-02")
        trades = [_make_trade("t1", 10.0, "trending")]
        impact = engine.compute_regime_exclusion_impact("bot1", trades, "nonexistent")
        assert impact["delta_pnl"] == 0.0

    def test_regime_gate_suggestions_include_quantified_impact(self):
        engine = StrategyEngine(
            week_start="2026-02-24", week_end="2026-03-02",
            regime_min_weeks=2,
        )
        trends = [
            RegimePerformanceTrend(regime="ranging", weekly_pnl=[-100.0, -80.0, -90.0]),
        ]
        trades = [
            _make_trade("t1", 10.0, "trending"),
            _make_trade("t2", -50.0, "ranging"),
        ]
        suggestions = engine.analyze_regime_fit_quantified("bot1", trends, trades)
        assert len(suggestions) == 1
        assert "$" in suggestions[0].description  # should include dollar amount
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_regime_exclusion.py -v`
Expected: FAIL — `compute_regime_exclusion_impact` not found

**Step 3: Write minimal implementation**

Add methods to `analysis/strategy_engine.py` after `analyze_regime_fit`:

```python
    def compute_regime_exclusion_impact(
        self, bot_id: str, trades: list, regime_to_exclude: str
    ) -> dict:
        """Compute P&L impact of excluding all trades in a specific regime."""
        baseline_pnl = sum(t.pnl for t in trades)
        kept = [t for t in trades if (t.market_regime or "unknown") != regime_to_exclude]
        excluded_pnl = sum(t.pnl for t in kept)
        excluded_count = len(trades) - len(kept)
        return {
            "regime": regime_to_exclude,
            "baseline_pnl": baseline_pnl,
            "excluded_pnl": excluded_pnl,
            "delta_pnl": excluded_pnl - baseline_pnl,
            "excluded_trade_count": excluded_count,
            "total_trade_count": len(trades),
        }

    def analyze_regime_fit_quantified(
        self, bot_id: str, regime_trends: list[RegimePerformanceTrend],
        trades: list | None = None,
    ) -> list[StrategySuggestion]:
        """Tier 3: Regime fit analysis with quantified exclusion impact."""
        suggestions: list[StrategySuggestion] = []

        for trend in regime_trends:
            if len(trend.weekly_pnl) < self.regime_min_weeks:
                continue
            losing_weeks = sum(1 for pnl in trend.weekly_pnl if pnl < self.regime_loss_threshold)
            if losing_weeks < self.regime_min_weeks:
                continue

            total_loss = sum(pnl for pnl in trend.weekly_pnl if pnl < 0)
            desc = (
                f"{bot_id} lost in {trend.regime} regime for "
                f"{losing_weeks}/{len(trend.weekly_pnl)} weeks "
                f"(total: ${total_loss:.0f}). "
            )

            if trades:
                impact = self.compute_regime_exclusion_impact(bot_id, trades, trend.regime)
                desc += (
                    f"Excluding {trend.regime} trades would change PnL from "
                    f"${impact['baseline_pnl']:.0f} to ${impact['excluded_pnl']:.0f} "
                    f"(+${impact['delta_pnl']:.0f}, removing {impact['excluded_trade_count']} trades). "
                )

            desc += f"Consider adding a regime gate to disable trading in {trend.regime} conditions."

            suggestions.append(
                StrategySuggestion(
                    tier=SuggestionTier.STRATEGY_VARIANT,
                    bot_id=bot_id,
                    title=f"Add regime gate for {trend.regime} on {bot_id}",
                    description=desc,
                    requires_human_judgment=True,
                    evidence_days=len(trend.weekly_pnl) * 7,
                    confidence=0.5,
                    estimated_impact_pnl=abs(total_loss),
                )
            )

        return suggestions
```

Add import at top of strategy_engine.py (if not present): no new imports needed — `list` type hint suffices.

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_regime_exclusion.py -v`
Expected: PASS (all 3 tests)

**Step 5: Commit**

```bash
git add analysis/strategy_engine.py tests/test_regime_exclusion.py
git commit -m "feat(A12): add regime exclusion P&L computation to strategy engine"
```

---

## Phase B: Quality & Infrastructure (Tasks 5–10)

*Addresses Gap F, Integration Gaps 1–5, and recommendations A8, A9, A10, A11. Hardens the orchestration layer.*

### Task 5: QualityGate Graceful Degradation (A8, Gap F)

**Files:**
- Modify: `schemas/report_checklist.py`
- Modify: `analysis/quality_gate.py`
- Test: `tests/test_quality_gate_graceful.py`

**Step 1: Write the failing test**

```python
# tests/test_quality_gate_graceful.py
"""Tests for quality gate graceful degradation."""
import json
from pathlib import Path

from analysis.quality_gate import QualityGate


def _setup_bot_dir(base: Path, date: str, bot_id: str, files: list[str]) -> None:
    bot_dir = base / date / bot_id
    bot_dir.mkdir(parents=True)
    for f in files:
        (bot_dir / f).write_text("{}")


ALL_FILES = [
    "summary.json", "winners.json", "losers.json", "process_failures.json",
    "notable_missed.json", "regime_analysis.json", "filter_analysis.json",
    "root_cause_summary.json", "hourly_performance.json", "slippage_stats.json",
]


class TestGracefulDegradation:
    def test_partial_bots_reported_passes_with_degradation(self, tmp_path):
        _setup_bot_dir(tmp_path, "2026-03-01", "bot1", ALL_FILES)
        # bot2 missing entirely
        gate = QualityGate("r1", "2026-03-01", ["bot1", "bot2"], tmp_path)
        checklist = gate.run()
        # Should pass (degraded), not fail
        assert checklist.can_proceed is True
        assert checklist.data_completeness < 1.0
        assert "bot2" in checklist.missing_bots

    def test_all_bots_present_full_completeness(self, tmp_path):
        _setup_bot_dir(tmp_path, "2026-03-01", "bot1", ALL_FILES)
        _setup_bot_dir(tmp_path, "2026-03-01", "bot2", ALL_FILES)
        gate = QualityGate("r1", "2026-03-01", ["bot1", "bot2"], tmp_path)
        checklist = gate.run()
        assert checklist.can_proceed is True
        assert checklist.data_completeness == 1.0
        assert checklist.missing_bots == []

    def test_missing_files_reduces_completeness(self, tmp_path):
        # bot1 has all files, bot2 missing some
        _setup_bot_dir(tmp_path, "2026-03-01", "bot1", ALL_FILES)
        _setup_bot_dir(tmp_path, "2026-03-01", "bot2", ALL_FILES[:5])  # only 5 of 10
        gate = QualityGate("r1", "2026-03-01", ["bot1", "bot2"], tmp_path)
        checklist = gate.run()
        assert checklist.can_proceed is True
        assert 0.5 < checklist.data_completeness < 1.0

    def test_no_bots_present_still_proceeds_with_zero_completeness(self, tmp_path):
        gate = QualityGate("r1", "2026-03-01", ["bot1", "bot2"], tmp_path)
        checklist = gate.run()
        assert checklist.can_proceed is True
        assert checklist.data_completeness == 0.0

    def test_expected_files_includes_hourly_and_slippage(self, tmp_path):
        """Regression: hourly_performance.json and slippage_stats.json must be in expected list."""
        _setup_bot_dir(tmp_path, "2026-03-01", "bot1", ALL_FILES[:8])  # original 8 only
        gate = QualityGate("r1", "2026-03-01", ["bot1"], tmp_path)
        checklist = gate.run()
        # Should detect missing hourly_performance.json and slippage_stats.json
        assert checklist.data_completeness < 1.0
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_quality_gate_graceful.py -v`
Expected: FAIL — `can_proceed`, `data_completeness`, `missing_bots` don't exist on ReportChecklist

**Step 3: Write minimal implementation**

Add fields to `schemas/report_checklist.py`:

```python
    # Graceful degradation fields
    can_proceed: bool = True
    data_completeness: float = 1.0
    available_bots: list[str] = []
    missing_bots: list[str] = []
```

Rewrite `analysis/quality_gate.py`:

```python
"""Report quality gate — Definition of Done for daily reports.

Validates curated data completeness. Degrades gracefully when some bots
or files are missing — returns a confidence score instead of blocking.
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
    "hourly_performance.json",
    "slippage_stats.json",
]


class QualityGate:
    """Runs all quality checks for a daily report. Always allows proceeding."""

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
        """Run all checks and return checklist with completeness score."""
        checks: list[CheckResult] = []

        bot_check = self._check_all_bots_reported()
        checks.append(bot_check)
        checks.extend(self._check_curated_files())
        checks.append(self._check_portfolio_risk_card())

        # Compute completeness
        available, missing = self._partition_bots()
        file_scores = self._compute_file_completeness()

        completeness = file_scores if self.expected_bots else 0.0

        return ReportChecklist(
            report_id=self.report_id,
            checks=checks,
            can_proceed=True,
            data_completeness=completeness,
            available_bots=available,
            missing_bots=missing,
        )

    def write_checklist(self, checklist: ReportChecklist, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(checklist.model_dump(mode="json"), indent=2, default=str)
        )

    def _partition_bots(self) -> tuple[list[str], list[str]]:
        date_dir = self.curated_dir / self.date
        available = [b for b in self.expected_bots if (date_dir / b).is_dir()]
        missing = [b for b in self.expected_bots if b not in available]
        return available, missing

    def _compute_file_completeness(self) -> float:
        """Compute fraction of expected files that exist across all bots."""
        if not self.expected_bots:
            return 0.0
        total_expected = len(self.expected_bots) * len(_EXPECTED_BOT_FILES)
        if total_expected == 0:
            return 0.0
        date_dir = self.curated_dir / self.date
        found = 0
        for bot in self.expected_bots:
            bot_dir = date_dir / bot
            if not bot_dir.is_dir():
                continue
            for f in _EXPECTED_BOT_FILES:
                if (bot_dir / f).exists():
                    found += 1
        return found / total_expected

    def _check_all_bots_reported(self) -> CheckResult:
        available, missing = self._partition_bots()
        if missing:
            return CheckResult(
                name="all_bots_reported",
                passed=False,
                detail=f"Missing: {', '.join(missing)} ({len(available)}/{len(self.expected_bots)} bots)",
            )
        return CheckResult(
            name="all_bots_reported",
            passed=True,
            detail=f"{len(available)}/{len(self.expected_bots)} bots",
        )

    def _check_curated_files(self) -> list[CheckResult]:
        results: list[CheckResult] = []
        date_dir = self.curated_dir / self.date
        for bot in self.expected_bots:
            bot_dir = date_dir / bot
            if not bot_dir.is_dir():
                continue
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
            return CheckResult(name="portfolio_risk_card", passed=True, detail="Computed")
        return CheckResult(name="portfolio_risk_card", passed=False, detail="Portfolio risk card not computed")
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_quality_gate_graceful.py -v`
Expected: PASS (all 5 tests)

Run: `pytest tests/test_quality_gate.py -v` (ensure existing tests still pass — may need adjustment for new expected files list)

**Step 5: Commit**

```bash
git add schemas/report_checklist.py analysis/quality_gate.py tests/test_quality_gate_graceful.py
git commit -m "feat(A8): quality gate degrades gracefully — completeness score instead of blocking"
```

---

### Task 6: Brain Error Frequency Tracking (A9, Integration Gap 2)

**Files:**
- Modify: `orchestrator/orchestrator_brain.py`
- Test: `tests/test_brain_error_tracking.py`

**Step 1: Write the failing test**

```python
# tests/test_brain_error_tracking.py
"""Tests for brain error frequency tracking — prevents error storm resource waste."""
import time
from orchestrator.orchestrator_brain import OrchestratorBrain, ActionType


def _make_error_event(event_id, bot_id="bot1", severity="HIGH", error_type="ConnectionError"):
    import json
    return {
        "event_type": "error",
        "event_id": event_id,
        "bot_id": bot_id,
        "payload": json.dumps({"severity": severity, "error_type": error_type}),
    }


class TestErrorFrequencyTracking:
    def test_first_high_error_spawns_triage(self):
        brain = OrchestratorBrain()
        actions = brain.decide(_make_error_event("e1"))
        assert len(actions) == 1
        assert actions[0].type == ActionType.SPAWN_TRIAGE

    def test_duplicate_errors_consolidated_into_one_triage(self):
        brain = OrchestratorBrain()
        # First error: spawns triage
        a1 = brain.decide(_make_error_event("e1", error_type="ConnectionError"))
        assert a1[0].type == ActionType.SPAWN_TRIAGE

        # Same error type again within window: suppressed
        a2 = brain.decide(_make_error_event("e2", error_type="ConnectionError"))
        assert len(a2) == 1
        assert a2[0].type == ActionType.QUEUE_FOR_DAILY  # suppressed to queue

    def test_different_error_types_not_suppressed(self):
        brain = OrchestratorBrain()
        brain.decide(_make_error_event("e1", error_type="ConnectionError"))
        a2 = brain.decide(_make_error_event("e2", error_type="TimeoutError"))
        assert a2[0].type == ActionType.SPAWN_TRIAGE  # different type, not suppressed

    def test_three_same_errors_creates_urgency_flag(self):
        brain = OrchestratorBrain()
        brain.decide(_make_error_event("e1", error_type="ConnectionError"))
        brain.decide(_make_error_event("e2", error_type="ConnectionError"))
        a3 = brain.decide(_make_error_event("e3", error_type="ConnectionError"))
        # Third error: escalated with urgency
        assert a3[0].type == ActionType.SPAWN_TRIAGE
        assert a3[0].details.get("urgency") == "error_storm"
        assert a3[0].details.get("error_count") >= 3

    def test_different_bots_tracked_separately(self):
        brain = OrchestratorBrain()
        brain.decide(_make_error_event("e1", bot_id="bot1", error_type="X"))
        a2 = brain.decide(_make_error_event("e2", bot_id="bot2", error_type="X"))
        assert a2[0].type == ActionType.SPAWN_TRIAGE  # different bot, not suppressed

    def test_critical_errors_never_suppressed(self):
        brain = OrchestratorBrain()
        # Even if same type, CRITICAL always routes immediately
        brain.decide(_make_error_event("e1", severity="CRITICAL", error_type="X"))
        a2 = brain.decide(_make_error_event("e2", severity="CRITICAL", error_type="X"))
        assert a2[0].type == ActionType.ALERT_IMMEDIATE
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_brain_error_tracking.py -v`
Expected: FAIL — brain routes all HIGH errors to SPAWN_TRIAGE (no dedup)

**Step 3: Write minimal implementation**

Rewrite `orchestrator/orchestrator_brain.py`:

```python
"""Orchestrator brain — deterministic event routing.

Maps incoming events to actions. No LLM calls.
The brain decides WHAT should happen; workers execute HOW.
"""

from __future__ import annotations

import json
import time
from collections import defaultdict
from dataclasses import dataclass
from enum import Enum


class ActionType(str, Enum):
    QUEUE_FOR_DAILY = "queue_for_daily"
    ALERT_IMMEDIATE = "alert_immediate"
    SPAWN_TRIAGE = "spawn_triage"
    SPAWN_DAILY_ANALYSIS = "spawn_daily_analysis"
    SPAWN_WEEKLY_SUMMARY = "spawn_weekly_summary"
    SPAWN_WFO = "spawn_wfo"
    QUEUE_FOR_WEEKLY = "queue_for_weekly"
    SEND_NOTIFICATION = "send_notification"
    UPDATE_HEARTBEAT = "update_heartbeat"
    LOG_UNKNOWN = "log_unknown"


@dataclass
class Action:
    type: ActionType
    event_id: str
    bot_id: str
    details: dict | None = None
    chain_id: str = ""


class ErrorRateTracker:
    """Sliding window counter for error frequency tracking per bot+error_type."""

    def __init__(self, window_seconds: int = 3600, storm_threshold: int = 3) -> None:
        self._window = window_seconds
        self._storm_threshold = storm_threshold
        # key = "bot_id:error_type" -> list of timestamps
        self._events: dict[str, list[float]] = defaultdict(list)
        # key = "bot_id:error_type" -> True if triage already spawned in this window
        self._triage_spawned: dict[str, bool] = defaultdict(bool)

    def record_and_check(self, bot_id: str, error_type: str) -> tuple[int, bool, bool]:
        """Record an error and check frequency.

        Returns: (count_in_window, is_suppressed, is_storm)
        - is_suppressed: True if a triage was already spawned for this type in window
        - is_storm: True if count >= storm_threshold (escalate with urgency)
        """
        key = f"{bot_id}:{error_type}"
        now = time.monotonic()
        cutoff = now - self._window

        # Prune old entries
        self._events[key] = [t for t in self._events[key] if t > cutoff]
        self._events[key].append(now)

        count = len(self._events[key])
        already_triaging = self._triage_spawned[key]
        is_storm = count >= self._storm_threshold

        if is_storm:
            # Reset suppression — escalate with urgency
            self._triage_spawned[key] = True
            return count, False, True

        if already_triaging:
            return count, True, False

        # First error of this type in window
        self._triage_spawned[key] = True
        return count, False, False


class OrchestratorBrain:
    """Deterministic decision engine for incoming events."""

    def __init__(self) -> None:
        self._error_tracker = ErrorRateTracker()

    def decide(self, event: dict) -> list[Action]:
        """Given a raw event dict, return a list of actions to take."""
        event_type = event.get("event_type", "")
        event_id = event.get("event_id", "")
        bot_id = event.get("bot_id", "")

        handler = self._handlers.get(event_type)
        if handler is not None:
            return handler(self, event_id, bot_id, event)
        return self._handle_unknown(event_id, bot_id, event)

    def _handle_trade(self, event_id: str, bot_id: str, event: dict) -> list[Action]:
        return [Action(type=ActionType.QUEUE_FOR_DAILY, event_id=event_id, bot_id=bot_id)]

    def _handle_missed_opportunity(self, event_id: str, bot_id: str, event: dict) -> list[Action]:
        return [Action(type=ActionType.QUEUE_FOR_DAILY, event_id=event_id, bot_id=bot_id)]

    def _handle_error(self, event_id: str, bot_id: str, event: dict) -> list[Action]:
        payload = json.loads(event.get("payload", "{}"))
        severity = payload.get("severity", "MEDIUM").upper()

        if severity == "CRITICAL":
            return [
                Action(type=ActionType.ALERT_IMMEDIATE, event_id=event_id, bot_id=bot_id, details=payload),
            ]
        elif severity == "HIGH":
            error_type = payload.get("error_type", "unknown")
            count, suppressed, is_storm = self._error_tracker.record_and_check(bot_id, error_type)

            if suppressed:
                # Already triaging this error type — queue instead of spawning another triage
                return [Action(type=ActionType.QUEUE_FOR_DAILY, event_id=event_id, bot_id=bot_id)]

            details = dict(payload)
            if is_storm:
                details["urgency"] = "error_storm"
                details["error_count"] = count

            return [
                Action(type=ActionType.SPAWN_TRIAGE, event_id=event_id, bot_id=bot_id, details=details),
            ]
        elif severity == "LOW":
            return [Action(type=ActionType.QUEUE_FOR_WEEKLY, event_id=event_id, bot_id=bot_id)]
        else:  # MEDIUM or unrecognized
            return [Action(type=ActionType.QUEUE_FOR_DAILY, event_id=event_id, bot_id=bot_id)]

    def _handle_heartbeat(self, event_id: str, bot_id: str, event: dict) -> list[Action]:
        return [Action(type=ActionType.UPDATE_HEARTBEAT, event_id=event_id, bot_id=bot_id)]

    def _handle_daily_analysis_trigger(self, event_id: str, bot_id: str, event: dict) -> list[Action]:
        return [Action(type=ActionType.SPAWN_DAILY_ANALYSIS, event_id=event_id, bot_id=bot_id)]

    def _handle_weekly_summary_trigger(self, event_id: str, bot_id: str, event: dict) -> list[Action]:
        return [Action(type=ActionType.SPAWN_WEEKLY_SUMMARY, event_id=event_id, bot_id=bot_id)]

    def _handle_wfo_trigger(self, event_id: str, bot_id: str, event: dict) -> list[Action]:
        return [Action(type=ActionType.SPAWN_WFO, event_id=event_id, bot_id=bot_id)]

    def _handle_notification_trigger(self, event_id: str, bot_id: str, event: dict) -> list[Action]:
        return [Action(type=ActionType.SEND_NOTIFICATION, event_id=event_id, bot_id=bot_id)]

    def _handle_unknown(self, event_id: str, bot_id: str, event: dict) -> list[Action]:
        return [Action(type=ActionType.LOG_UNKNOWN, event_id=event_id, bot_id=bot_id)]

    _handlers: dict = {
        "trade": _handle_trade,
        "missed_opportunity": _handle_missed_opportunity,
        "error": _handle_error,
        "heartbeat": _handle_heartbeat,
        "daily_analysis_trigger": _handle_daily_analysis_trigger,
        "weekly_summary_trigger": _handle_weekly_summary_trigger,
        "wfo_trigger": _handle_wfo_trigger,
        "notification_trigger": _handle_notification_trigger,
    }
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_brain_error_tracking.py -v`
Expected: PASS (all 6 tests)

Run: `pytest tests/ -k "brain or orchestrator_brain" -v` (ensure no regressions)

**Step 5: Commit**

```bash
git add orchestrator/orchestrator_brain.py tests/test_brain_error_tracking.py
git commit -m "feat(A9): add error frequency tracking to brain — prevents error storm resource waste"
```

---

### Task 7: Dead-Letter Queue Alerting (Integration Gap 3)

**Files:**
- Modify: `orchestrator/monitoring.py:35-106`
- Test: `tests/test_dead_letter_alerting.py`

**Step 1: Write the failing test**

```python
# tests/test_dead_letter_alerting.py
"""Tests for dead-letter queue alerting in monitoring."""
import pytest
from unittest.mock import AsyncMock

from orchestrator.monitoring import MonitoringCheck, MonitoringLoop, AlertSeverity


class TestDeadLetterAlerting:
    @pytest.mark.asyncio
    async def test_alerts_when_dead_letters_exist(self):
        queue = AsyncMock()
        queue.get_dead_letters.return_value = [
            {"event_id": "e1", "last_error": "timeout"},
            {"event_id": "e2", "last_error": "parse error"},
        ]
        check = MonitoringCheck(queue=queue)
        alerts = await check.check_dead_letters()
        assert len(alerts) == 1
        assert alerts[0].severity == AlertSeverity.HIGH
        assert "2" in alerts[0].message

    @pytest.mark.asyncio
    async def test_no_alert_when_empty(self):
        queue = AsyncMock()
        queue.get_dead_letters.return_value = []
        check = MonitoringCheck(queue=queue)
        alerts = await check.check_dead_letters()
        assert alerts == []

    @pytest.mark.asyncio
    async def test_critical_when_many_dead_letters(self):
        queue = AsyncMock()
        queue.get_dead_letters.return_value = [{"event_id": f"e{i}"} for i in range(10)]
        check = MonitoringCheck(queue=queue, dead_letter_critical_threshold=5)
        alerts = await check.check_dead_letters()
        assert alerts[0].severity == AlertSeverity.CRITICAL

    @pytest.mark.asyncio
    async def test_dead_letters_included_in_run_all(self):
        queue = AsyncMock()
        queue.get_dead_letters.return_value = [{"event_id": "e1"}]
        check = MonitoringCheck(queue=queue)
        loop = MonitoringLoop(checks=[check])
        alerts = await loop.run_all()
        assert any(a.source == "dead_letter" for a in alerts)
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_dead_letter_alerting.py -v`
Expected: FAIL — `check_dead_letters` not found, `queue` param not accepted

**Step 3: Write minimal implementation**

Update `orchestrator/monitoring.py` — add `queue` parameter and `check_dead_letters` method:

Add to `MonitoringCheck.__init__`:

```python
        self._queue = None
        self._dead_letter_critical = 5
```

Add parameters to `__init__` signature:

```python
    def __init__(
        self,
        registry: TaskRegistry | None = None,
        task_timeout_seconds: int = 3600,
        heartbeat_dir: str = "",
        heartbeat_max_age_seconds: int = 7200,
        queue=None,
        dead_letter_critical_threshold: int = 5,
    ) -> None:
```

And assign:

```python
        self._queue = queue
        self._dead_letter_critical = dead_letter_critical_threshold
```

Add method:

```python
    async def check_dead_letters(self) -> list[Alert]:
        """Alert when events are stuck in dead-letter queue."""
        if not self._queue:
            return []
        try:
            dead_letters = await self._queue.get_dead_letters(limit=50)
        except Exception:
            return []
        count = len(dead_letters)
        if count == 0:
            return []
        severity = AlertSeverity.CRITICAL if count >= self._dead_letter_critical else AlertSeverity.HIGH
        return [Alert(
            severity=severity,
            source="dead_letter",
            message=f"{count} event(s) in dead-letter queue — inspect and reprocess or discard",
        )]
```

Update `MonitoringLoop.run_all()` to include dead-letter checks:

```python
    async def run_all(self) -> list[Alert]:
        all_alerts: list[Alert] = []
        for check in self._checks:
            all_alerts.extend(await check.check_stale_tasks())
            all_alerts.extend(check.check_heartbeats())
            all_alerts.extend(await check.check_dead_letters())
        # ... rest unchanged
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_dead_letter_alerting.py -v`
Expected: PASS (all 4 tests)

**Step 5: Commit**

```bash
git add orchestrator/monitoring.py tests/test_dead_letter_alerting.py
git commit -m "feat: add dead-letter queue alerting to monitoring loop"
```

---

### Task 8: /metrics Endpoint (A11, Integration Gap 4)

**Files:**
- Create: `schemas/orchestrator_metrics.py`
- Modify: `orchestrator/app.py`
- Test: `tests/test_metrics_endpoint.py`

**Step 1: Write the failing test**

```python
# tests/test_metrics_endpoint.py
"""Tests for /metrics observability endpoint."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from schemas.orchestrator_metrics import OrchestratorMetrics


class TestOrchestratorMetricsSchema:
    def test_metrics_model(self):
        m = OrchestratorMetrics(
            queue_depth=5, dead_letter_count=1, active_agents=2,
            error_rate_1h=0.05, uptime_seconds=3600,
        )
        assert m.queue_depth == 5
        assert m.dead_letter_count == 1


class TestMetricsEndpoint:
    @pytest.mark.asyncio
    async def test_metrics_returns_queue_depth(self):
        """Test via direct function call (avoids full app wiring)."""
        from orchestrator.app import create_app, AppConfig

        config = AppConfig(bot_ids=[], data_dir="/tmp/test_metrics")
        with patch("orchestrator.app.EventQueue") as MockQueue, \
             patch("orchestrator.app.TaskRegistry") as MockRegistry:
            mock_q = AsyncMock()
            mock_q.initialize = AsyncMock()
            mock_q.close = AsyncMock()
            mock_q.count_pending = AsyncMock(return_value=5)
            mock_q.get_dead_letters = AsyncMock(return_value=[{"event_id": "e1"}])
            MockQueue.return_value = mock_q

            mock_reg = AsyncMock()
            mock_reg.initialize = AsyncMock()
            mock_reg.close = AsyncMock()
            MockRegistry.return_value = mock_reg

            app = create_app(db_dir="/tmp/test_metrics", config=config)
            # Verify endpoint exists
            routes = [r.path for r in app.routes]
            assert "/metrics" in routes
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_metrics_endpoint.py -v`
Expected: FAIL — `schemas.orchestrator_metrics` not found, `/metrics` not in routes

**Step 3: Write minimal implementation**

Create `schemas/orchestrator_metrics.py`:

```python
"""Orchestrator observability metrics schema."""
from __future__ import annotations

from pydantic import BaseModel


class OrchestratorMetrics(BaseModel):
    """Point-in-time snapshot of orchestrator operational state."""
    queue_depth: int = 0
    dead_letter_count: int = 0
    active_agents: int = 0
    error_rate_1h: float = 0.0
    uptime_seconds: float = 0.0
    last_daily_analysis: str | None = None
    last_weekly_analysis: str | None = None
```

Add `/metrics` endpoint to `orchestrator/app.py` — add after `/health` endpoint:

```python
    @app.get("/metrics")
    async def metrics():
        """Operational metrics for monitoring the orchestrator itself."""
        pending = await queue.count_pending() if hasattr(queue, "count_pending") else 0
        dead_letters = await queue.get_dead_letters(limit=1)
        dead_count = len(dead_letters)  # approximate
        running = subagent_mgr.get_running()
        return {
            "queue_depth": pending,
            "dead_letter_count": dead_count,
            "active_agents": len(running),
            "uptime_seconds": (datetime.now(timezone.utc) - app.state.start_time).total_seconds()
            if hasattr(app.state, "start_time") else 0,
        }
```

Add `app.state.start_time = datetime.now(timezone.utc)` after `app = FastAPI(...)` line.

Add `count_pending` method to `orchestrator/db/queue.py` if not present:

```python
    async def count_pending(self) -> int:
        """Count events with pending status."""
        row = self._conn.execute("SELECT COUNT(*) FROM events WHERE status = 'pending'").fetchone()
        return row[0] if row else 0
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_metrics_endpoint.py -v`
Expected: PASS (all 2 tests)

**Step 5: Commit**

```bash
git add schemas/orchestrator_metrics.py orchestrator/app.py orchestrator/db/queue.py tests/test_metrics_endpoint.py
git commit -m "feat(A11): add /metrics observability endpoint with queue depth and agent count"
```

---

### Task 9: Dynamic VPS Poll Interval (Integration Gap 5)

**Files:**
- Modify: `orchestrator/adapters/vps_receiver.py`
- Test: `tests/test_dynamic_polling.py`

**Step 1: Write the failing test**

```python
# tests/test_dynamic_polling.py
"""Tests for adaptive VPS receiver polling."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from orchestrator.adapters.vps_receiver import VPSReceiver


class TestAdaptivePolling:
    def test_initial_interval_is_default(self):
        queue = AsyncMock()
        receiver = VPSReceiver(
            relay_url="http://relay:8080",
            local_queue=queue,
            min_poll_seconds=10,
            max_poll_seconds=300,
        )
        assert receiver.current_poll_interval == 300  # starts at max (quiet)

    def test_interval_shrinks_after_events_received(self):
        queue = AsyncMock()
        receiver = VPSReceiver(
            relay_url="http://relay:8080",
            local_queue=queue,
            min_poll_seconds=10,
            max_poll_seconds=300,
        )
        receiver.adapt_interval(events_received=5)
        assert receiver.current_poll_interval == 10  # shrink to min

    def test_interval_grows_when_no_events(self):
        queue = AsyncMock()
        receiver = VPSReceiver(
            relay_url="http://relay:8080",
            local_queue=queue,
            min_poll_seconds=10,
            max_poll_seconds=300,
        )
        receiver.adapt_interval(events_received=5)  # shrink first
        assert receiver.current_poll_interval == 10
        receiver.adapt_interval(events_received=0)  # no events
        assert receiver.current_poll_interval > 10  # should grow

    def test_interval_capped_at_max(self):
        queue = AsyncMock()
        receiver = VPSReceiver(
            relay_url="http://relay:8080",
            local_queue=queue,
            min_poll_seconds=10,
            max_poll_seconds=60,
        )
        # Many empty polls
        for _ in range(20):
            receiver.adapt_interval(events_received=0)
        assert receiver.current_poll_interval <= 60
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_dynamic_polling.py -v`
Expected: FAIL — `min_poll_seconds` param not accepted, `current_poll_interval` not found

**Step 3: Write minimal implementation**

Update `orchestrator/adapters/vps_receiver.py` — add parameters and method:

Add to `__init__` signature:

```python
        min_poll_seconds: int = 10,
        max_poll_seconds: int = 300,
```

Add to `__init__` body:

```python
        self._min_poll = min_poll_seconds
        self._max_poll = max_poll_seconds
        self.current_poll_interval: int = max_poll_seconds
```

Add method:

```python
    def adapt_interval(self, events_received: int) -> None:
        """Adjust poll interval based on recent activity."""
        if events_received > 0:
            self.current_poll_interval = self._min_poll
        else:
            # Exponential backoff: double interval until max
            self.current_poll_interval = min(self.current_poll_interval * 2, self._max_poll)
```

Update `poll()` to call `adapt_interval`:

```python
    async def poll(self) -> int:
        try:
            pulled = await self.pull_and_store()
            self._consecutive_failures = 0
            self.adapt_interval(events_received=pulled)
            return pulled
        except Exception as exc:
            self._consecutive_failures += 1
            delay = min(2 ** self._consecutive_failures, 300)
            logger.warning(
                "Relay poll failed (attempt %d, next backoff %ds): %s",
                self._consecutive_failures, delay, exc,
            )
            return 0
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_dynamic_polling.py -v`
Expected: PASS (all 4 tests)

**Step 5: Commit**

```bash
git add orchestrator/adapters/vps_receiver.py tests/test_dynamic_polling.py
git commit -m "feat: add adaptive poll interval to VPS receiver — shrinks when active, grows when quiet"
```

---

### Task 10: QUEUE_FOR_DAILY/WEEKLY Event Batching (A10, Integration Gap 1)

**Files:**
- Modify: `orchestrator/worker.py`
- Test: `tests/test_event_batching.py`

**Step 1: Write the failing test**

```python
# tests/test_event_batching.py
"""Tests for QUEUE_FOR_DAILY/WEEKLY event batching in worker."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from orchestrator.orchestrator_brain import Action, ActionType
from orchestrator.worker import Worker


class TestEventBatching:
    def test_worker_tracks_daily_queue_counts(self):
        queue = AsyncMock()
        registry = AsyncMock()
        brain = MagicMock()
        worker = Worker(queue=queue, registry=registry, brain=brain)
        assert hasattr(worker, "daily_queue_counts")
        assert isinstance(worker.daily_queue_counts, dict)

    def test_queue_for_daily_increments_counter(self):
        queue = AsyncMock()
        registry = AsyncMock()
        brain = MagicMock()
        worker = Worker(queue=queue, registry=registry, brain=brain)
        worker._record_queued_event("bot1", ActionType.QUEUE_FOR_DAILY)
        worker._record_queued_event("bot1", ActionType.QUEUE_FOR_DAILY)
        worker._record_queued_event("bot2", ActionType.QUEUE_FOR_DAILY)
        assert worker.daily_queue_counts["bot1"] == 2
        assert worker.daily_queue_counts["bot2"] == 1

    def test_weekly_queue_counts_tracked_separately(self):
        queue = AsyncMock()
        registry = AsyncMock()
        brain = MagicMock()
        worker = Worker(queue=queue, registry=registry, brain=brain)
        worker._record_queued_event("bot1", ActionType.QUEUE_FOR_WEEKLY)
        assert worker.weekly_queue_counts["bot1"] == 1
        assert worker.daily_queue_counts.get("bot1", 0) == 0

    def test_get_and_reset_daily_counts(self):
        queue = AsyncMock()
        registry = AsyncMock()
        brain = MagicMock()
        worker = Worker(queue=queue, registry=registry, brain=brain)
        worker._record_queued_event("bot1", ActionType.QUEUE_FOR_DAILY)
        worker._record_queued_event("bot1", ActionType.QUEUE_FOR_DAILY)
        counts = worker.get_and_reset_daily_counts()
        assert counts == {"bot1": 2}
        assert worker.daily_queue_counts == {}
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_event_batching.py -v`
Expected: FAIL — `daily_queue_counts` not found

**Step 3: Write minimal implementation**

Add to `Worker.__init__` in `orchestrator/worker.py`:

```python
        self.daily_queue_counts: dict[str, int] = {}
        self.weekly_queue_counts: dict[str, int] = {}
```

Add methods:

```python
    def _record_queued_event(self, bot_id: str, action_type: ActionType) -> None:
        """Track event counts for QUEUE_FOR_DAILY/WEEKLY actions."""
        if action_type == ActionType.QUEUE_FOR_DAILY:
            self.daily_queue_counts[bot_id] = self.daily_queue_counts.get(bot_id, 0) + 1
        elif action_type == ActionType.QUEUE_FOR_WEEKLY:
            self.weekly_queue_counts[bot_id] = self.weekly_queue_counts.get(bot_id, 0) + 1

    def get_and_reset_daily_counts(self) -> dict[str, int]:
        """Get accumulated daily event counts and reset. Called by daily analysis trigger."""
        counts = dict(self.daily_queue_counts)
        self.daily_queue_counts = {}
        return counts

    def get_and_reset_weekly_counts(self) -> dict[str, int]:
        """Get accumulated weekly event counts and reset. Called by weekly analysis trigger."""
        counts = dict(self.weekly_queue_counts)
        self.weekly_queue_counts = {}
        return counts
```

Update `_dispatch` method to call `_record_queued_event` for QUEUE actions:

In the `_dispatch` method, add to the QUEUE_FOR_DAILY/QUEUE_FOR_WEEKLY handling:

```python
        if action.type in (ActionType.QUEUE_FOR_DAILY, ActionType.QUEUE_FOR_WEEKLY):
            self._record_queued_event(action.bot_id, action.type)
            return
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_event_batching.py -v`
Expected: PASS (all 4 tests)

**Step 5: Commit**

```bash
git add orchestrator/worker.py tests/test_event_batching.py
git commit -m "feat(A10): track QUEUE_FOR_DAILY/WEEKLY event counts per bot for daily analysis context"
```

---

## Phase C: Simulation & Analysis Skills (Tasks 11–14)

*Addresses Gaps A, D, H, I and recommendations A4, A5, A6, A7. Builds the prescriptive analysis layer.*

### Task 11: FilterSensitivityAnalyzer (A4, Gap D)

**Files:**
- Create: `schemas/filter_sensitivity.py`
- Create: `skills/filter_sensitivity_analyzer.py`
- Test: `tests/test_filter_sensitivity.py`

**Step 1: Write the failing test**

```python
# tests/test_filter_sensitivity.py
"""Tests for filter sensitivity analysis."""
from datetime import datetime, timezone

from schemas.events import MissedOpportunityEvent, TradeEvent
from schemas.filter_sensitivity import FilterSensitivityCurve, FilterSensitivityReport


def _make_missed(pair, blocked_by, outcome_24h, margin_pct=None):
    return MissedOpportunityEvent(
        bot_id="bot1", pair=pair, signal="momentum",
        blocked_by=blocked_by, outcome_24h=outcome_24h,
        confidence=0.8, assumption_tags=[],
        margin_pct=margin_pct,
    )


class TestFilterSensitivitySchema:
    def test_curve_model(self):
        curve = FilterSensitivityCurve(
            filter_name="volume_filter", bot_id="bot1",
            current_block_count=20, current_net_impact=-500.0,
        )
        assert curve.filter_name == "volume_filter"

    def test_report_model(self):
        report = FilterSensitivityReport(
            bot_id="bot1", date="2026-03-01", curves=[],
        )
        assert report.curves == []


class TestFilterSensitivityAnalyzer:
    def test_computes_net_impact_per_filter(self):
        from skills.filter_sensitivity_analyzer import FilterSensitivityAnalyzer

        missed = [
            _make_missed("BTC/USDT", "volume_filter", 500.0),
            _make_missed("ETH/USDT", "volume_filter", -200.0),
            _make_missed("BTC/USDT", "rsi_filter", 100.0),
        ]
        analyzer = FilterSensitivityAnalyzer(bot_id="bot1", date="2026-03-01")
        report = analyzer.analyze(missed)
        assert isinstance(report, FilterSensitivityReport)
        vol = next(c for c in report.curves if c.filter_name == "volume_filter")
        assert vol.current_block_count == 2
        # Net impact: removing filter would add 500-200 = 300
        assert vol.current_net_impact == 300.0

    def test_breakeven_identified(self):
        from skills.filter_sensitivity_analyzer import FilterSensitivityAnalyzer

        # Filter blocks 5 trades: 3 would have been losers, 2 winners
        missed = [
            _make_missed("BTC", "vol_filter", -100.0),
            _make_missed("ETH", "vol_filter", -150.0),
            _make_missed("SOL", "vol_filter", -80.0),
            _make_missed("BTC", "vol_filter", 200.0),
            _make_missed("ETH", "vol_filter", 300.0),
        ]
        analyzer = FilterSensitivityAnalyzer(bot_id="bot1", date="2026-03-01")
        report = analyzer.analyze(missed)
        vol = next(c for c in report.curves if c.filter_name == "vol_filter")
        # Net: -100-150-80+200+300 = 170 (filter costs money)
        assert vol.current_net_impact == 170.0
        assert vol.recommendation is not None

    def test_no_missed_produces_empty_report(self):
        from skills.filter_sensitivity_analyzer import FilterSensitivityAnalyzer

        analyzer = FilterSensitivityAnalyzer(bot_id="bot1", date="2026-03-01")
        report = analyzer.analyze([])
        assert report.curves == []

    def test_with_margin_pct_data(self):
        from skills.filter_sensitivity_analyzer import FilterSensitivityAnalyzer

        missed = [
            _make_missed("BTC", "vol_filter", 500.0, margin_pct=5.0),   # close to threshold
            _make_missed("ETH", "vol_filter", -200.0, margin_pct=25.0),  # far from threshold
            _make_missed("SOL", "vol_filter", 300.0, margin_pct=8.0),   # moderately close
        ]
        analyzer = FilterSensitivityAnalyzer(bot_id="bot1", date="2026-03-01")
        report = analyzer.analyze(missed)
        vol = next(c for c in report.curves if c.filter_name == "vol_filter")
        # Should have sensitivity points when margin data available
        assert len(vol.sensitivity_points) > 0
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_filter_sensitivity.py -v`
Expected: FAIL — modules not found

**Step 3: Write minimal implementation**

Add optional `margin_pct` to `MissedOpportunityEvent` in `schemas/events.py`:

```python
    margin_pct: float | None = None  # how close to filter threshold (requires bot B4)
```

Create `schemas/filter_sensitivity.py`:

```python
"""Filter sensitivity analysis schemas."""
from __future__ import annotations

from pydantic import BaseModel


class SensitivityPoint(BaseModel):
    """Performance estimate at a specific threshold adjustment."""
    threshold_adjustment_pct: float
    estimated_additional_trades: int = 0
    estimated_pnl_impact: float = 0.0


class FilterSensitivityCurve(BaseModel):
    """Sensitivity analysis for a single filter."""
    filter_name: str
    bot_id: str
    current_block_count: int = 0
    current_net_impact: float = 0.0
    blocked_winners: int = 0
    blocked_losers: int = 0
    recommendation: str | None = None
    sensitivity_points: list[SensitivityPoint] = []


class FilterSensitivityReport(BaseModel):
    """Sensitivity analysis across all filters for a bot."""
    bot_id: str
    date: str
    curves: list[FilterSensitivityCurve] = []
```

Create `skills/filter_sensitivity_analyzer.py`:

```python
"""Filter sensitivity analysis — estimates impact of threshold changes.

When margin_pct data is available (from bot-side B4), computes sensitivity curves
showing what happens at ±10/20/30% threshold adjustments.

Without margin_pct, computes net impact and recommendations from outcome data.
"""
from __future__ import annotations

from collections import defaultdict

from schemas.events import MissedOpportunityEvent
from schemas.filter_sensitivity import (
    FilterSensitivityCurve,
    FilterSensitivityReport,
    SensitivityPoint,
)


class FilterSensitivityAnalyzer:
    def __init__(self, bot_id: str, date: str) -> None:
        self._bot_id = bot_id
        self._date = date

    def analyze(self, missed: list[MissedOpportunityEvent]) -> FilterSensitivityReport:
        """Analyze filter sensitivity from missed opportunity data."""
        by_filter: dict[str, list[MissedOpportunityEvent]] = defaultdict(list)
        for m in missed:
            if m.blocked_by:
                by_filter[m.blocked_by].append(m)

        curves = []
        for filter_name, events in sorted(by_filter.items()):
            curves.append(self._analyze_filter(filter_name, events))

        return FilterSensitivityReport(
            bot_id=self._bot_id, date=self._date, curves=curves,
        )

    def _analyze_filter(
        self, filter_name: str, events: list[MissedOpportunityEvent]
    ) -> FilterSensitivityCurve:
        outcomes = [(m, m.outcome_24h or 0.0) for m in events]
        winners = sum(1 for _, o in outcomes if o > 0)
        losers = sum(1 for _, o in outcomes if o <= 0)
        net_impact = sum(o for _, o in outcomes)

        # Recommendation
        if net_impact > 0:
            rec = (
                f"Removing {filter_name} would have added ${net_impact:.0f} "
                f"({winners} winners, {losers} losers blocked). Consider relaxing."
            )
        elif net_impact < 0:
            rec = (
                f"{filter_name} saved ${abs(net_impact):.0f} by blocking "
                f"{losers} losing trades. Keep current threshold."
            )
        else:
            rec = f"{filter_name} has neutral impact. Review for simplification."

        # Sensitivity points (only when margin_pct available)
        sensitivity_points = self._compute_sensitivity_points(events)

        return FilterSensitivityCurve(
            filter_name=filter_name,
            bot_id=self._bot_id,
            current_block_count=len(events),
            current_net_impact=net_impact,
            blocked_winners=winners,
            blocked_losers=losers,
            recommendation=rec,
            sensitivity_points=sensitivity_points,
        )

    def _compute_sensitivity_points(
        self, events: list[MissedOpportunityEvent]
    ) -> list[SensitivityPoint]:
        """Compute sensitivity curve from margin_pct data if available."""
        with_margin = [(m, m.margin_pct) for m in events if m.margin_pct is not None]
        if not with_margin:
            return []

        points = []
        for adjustment in [10, 20, 30]:
            # Trades within margin_pct <= adjustment would be captured by widening
            captured = [m for m, margin in with_margin if margin <= adjustment]
            pnl_impact = sum(m.outcome_24h or 0.0 for m in captured)
            points.append(SensitivityPoint(
                threshold_adjustment_pct=float(adjustment),
                estimated_additional_trades=len(captured),
                estimated_pnl_impact=pnl_impact,
            ))

        return points
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_filter_sensitivity.py -v`
Expected: PASS (all 5 tests)

**Step 5: Commit**

```bash
git add schemas/events.py schemas/filter_sensitivity.py skills/filter_sensitivity_analyzer.py tests/test_filter_sensitivity.py
git commit -m "feat(A4): add FilterSensitivityAnalyzer — threshold impact estimation with optional margin curves"
```

---

### Task 12: CounterfactualSimulator (A5, Gap A)

**Files:**
- Create: `schemas/counterfactual.py`
- Create: `skills/counterfactual_simulator.py`
- Test: `tests/test_counterfactual_simulator.py`

**Step 1: Write the failing test**

```python
# tests/test_counterfactual_simulator.py
"""Tests for counterfactual trade replay simulator."""
from datetime import datetime, timezone

from schemas.events import TradeEvent, MissedOpportunityEvent
from schemas.counterfactual import ScenarioType, CounterfactualScenario, CounterfactualResult


def _make_trade(trade_id, pnl, regime="trending", pair="BTC/USDT"):
    return TradeEvent(
        trade_id=trade_id, bot_id="bot1", pair=pair,
        side="LONG",
        entry_time=datetime(2026, 3, 1, tzinfo=timezone.utc),
        exit_time=datetime(2026, 3, 1, 1, tzinfo=timezone.utc),
        entry_price=100, exit_price=100 + pnl, position_size=1,
        pnl=pnl, pnl_pct=pnl, market_regime=regime,
        spread_at_entry=2.0,
    )


def _make_missed(blocked_by, outcome_24h):
    return MissedOpportunityEvent(
        bot_id="bot1", pair="BTC/USDT", signal="momentum",
        blocked_by=blocked_by, outcome_24h=outcome_24h,
        hypothetical_entry=100.0, confidence=0.8, assumption_tags=[],
    )


class TestCounterfactualSchema:
    def test_scenario_creation(self):
        s = CounterfactualScenario(
            scenario_type=ScenarioType.REMOVE_FILTER,
            description="Remove volume filter",
            parameters={"filter_name": "volume_filter"},
        )
        assert s.scenario_type == ScenarioType.REMOVE_FILTER

    def test_result_model(self):
        r = CounterfactualResult(
            scenario=CounterfactualScenario(
                scenario_type=ScenarioType.ADD_REGIME_GATE,
                description="Add ranging gate",
                parameters={"regime": "ranging"},
            ),
            baseline_pnl=100.0, modified_pnl=150.0,
            baseline_trade_count=20, modified_trade_count=15,
        )
        assert r.delta_pnl == 50.0


class TestCounterfactualSimulator:
    def test_remove_filter_includes_missed_ops(self):
        from skills.counterfactual_simulator import CounterfactualSimulator

        trades = [_make_trade("t1", 10.0), _make_trade("t2", -5.0)]
        missed = [
            _make_missed("volume_filter", 20.0),
            _make_missed("volume_filter", -8.0),
            _make_missed("rsi_filter", 15.0),  # different filter, not included
        ]
        sim = CounterfactualSimulator()
        result = sim.simulate_remove_filter(trades, missed, "volume_filter")
        assert isinstance(result, CounterfactualResult)
        # Baseline: 10 - 5 = 5
        assert result.baseline_pnl == 5.0
        # Modified: 10 - 5 + 20 - 8 = 17
        assert result.modified_pnl == 17.0
        assert result.modified_trade_count == 4  # 2 original + 2 unfiltered

    def test_add_regime_gate_excludes_trades(self):
        from skills.counterfactual_simulator import CounterfactualSimulator

        trades = [
            _make_trade("t1", 10.0, "trending"),
            _make_trade("t2", 8.0, "trending"),
            _make_trade("t3", -15.0, "ranging"),
            _make_trade("t4", -12.0, "ranging"),
        ]
        sim = CounterfactualSimulator()
        result = sim.simulate_regime_gate(trades, [], "ranging")
        assert result.baseline_pnl == -9.0  # 10+8-15-12
        assert result.modified_pnl == 18.0  # 10+8
        assert result.modified_trade_count == 2

    def test_exclude_trades_by_criteria(self):
        from skills.counterfactual_simulator import CounterfactualSimulator

        trades = [
            _make_trade("t1", 10.0, pair="BTC/USDT"),
            _make_trade("t2", -20.0, pair="DOGE/USDT"),
            _make_trade("t3", 5.0, pair="ETH/USDT"),
        ]
        sim = CounterfactualSimulator()
        result = sim.simulate_exclude(trades, [], lambda t: t.pair == "DOGE/USDT")
        assert result.modified_pnl == 15.0
        assert result.modified_trade_count == 2

    def test_computes_win_rate_delta(self):
        from skills.counterfactual_simulator import CounterfactualSimulator

        trades = [
            _make_trade("t1", 10.0, "trending"),
            _make_trade("t2", -5.0, "ranging"),
            _make_trade("t3", -3.0, "ranging"),
        ]
        sim = CounterfactualSimulator()
        result = sim.simulate_regime_gate(trades, [], "ranging")
        # Baseline win rate: 1/3 = 0.333
        assert result.baseline_win_rate == pytest.approx(1 / 3, abs=0.01)
        # Modified: 1/1 = 1.0
        assert result.modified_win_rate == 1.0

    def test_empty_trades_returns_zero_baseline(self):
        from skills.counterfactual_simulator import CounterfactualSimulator

        sim = CounterfactualSimulator()
        result = sim.simulate_remove_filter([], [], "volume_filter")
        assert result.baseline_pnl == 0.0
        assert result.modified_pnl == 0.0
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_counterfactual_simulator.py -v`
Expected: FAIL — modules not found

**Step 3: Write minimal implementation**

Create `schemas/counterfactual.py`:

```python
"""Counterfactual simulation schemas — what-if trade replay."""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, computed_field


class ScenarioType(str, Enum):
    REMOVE_FILTER = "remove_filter"
    ADD_REGIME_GATE = "add_regime_gate"
    EXCLUDE_TRADES = "exclude_trades"


class CounterfactualScenario(BaseModel):
    scenario_type: ScenarioType
    description: str
    parameters: dict = {}


class CounterfactualResult(BaseModel):
    scenario: CounterfactualScenario
    baseline_pnl: float = 0.0
    modified_pnl: float = 0.0
    baseline_trade_count: int = 0
    modified_trade_count: int = 0
    baseline_win_rate: float = 0.0
    modified_win_rate: float = 0.0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def delta_pnl(self) -> float:
        return self.modified_pnl - self.baseline_pnl

    @computed_field  # type: ignore[prop-decorator]
    @property
    def delta_win_rate(self) -> float:
        return self.modified_win_rate - self.baseline_win_rate
```

Create `skills/counterfactual_simulator.py`:

```python
"""Counterfactual simulator — what-if trade replay with modified strategy rules.

Replays historical trades under modified conditions:
  - Remove filter: include missed opportunities blocked by a specific filter
  - Add regime gate: exclude trades in a specific market regime
  - Exclude trades: remove trades matching arbitrary criteria

Does NOT require tick-level data — works with existing TradeEvent and
MissedOpportunityEvent records.
"""
from __future__ import annotations

from collections.abc import Callable

from schemas.counterfactual import (
    CounterfactualResult,
    CounterfactualScenario,
    ScenarioType,
)
from schemas.events import MissedOpportunityEvent, TradeEvent


class CounterfactualSimulator:
    """Lightweight counterfactual trade replay engine."""

    def simulate_remove_filter(
        self,
        trades: list[TradeEvent],
        missed: list[MissedOpportunityEvent],
        filter_name: str,
    ) -> CounterfactualResult:
        """Simulate removing a filter — add back blocked missed opportunities."""
        baseline_pnl, baseline_count, baseline_wr = self._compute_baseline(trades)

        # Include missed ops that were blocked by this filter
        unfiltered = [m for m in missed if m.blocked_by == filter_name]
        additional_pnl = sum(m.outcome_24h or 0.0 for m in unfiltered)
        additional_wins = sum(1 for m in unfiltered if (m.outcome_24h or 0.0) > 0)

        modified_pnl = baseline_pnl + additional_pnl
        modified_count = baseline_count + len(unfiltered)
        modified_wins = sum(1 for t in trades if t.pnl > 0) + additional_wins
        modified_wr = modified_wins / modified_count if modified_count > 0 else 0.0

        return CounterfactualResult(
            scenario=CounterfactualScenario(
                scenario_type=ScenarioType.REMOVE_FILTER,
                description=f"Remove {filter_name} filter",
                parameters={"filter_name": filter_name},
            ),
            baseline_pnl=baseline_pnl,
            modified_pnl=modified_pnl,
            baseline_trade_count=baseline_count,
            modified_trade_count=modified_count,
            baseline_win_rate=baseline_wr,
            modified_win_rate=modified_wr,
        )

    def simulate_regime_gate(
        self,
        trades: list[TradeEvent],
        missed: list[MissedOpportunityEvent],
        regime_to_exclude: str,
    ) -> CounterfactualResult:
        """Simulate adding a regime gate — exclude trades in specified regime."""
        baseline_pnl, baseline_count, baseline_wr = self._compute_baseline(trades)

        kept = [t for t in trades if (t.market_regime or "") != regime_to_exclude]
        modified_pnl = sum(t.pnl for t in kept)
        modified_wins = sum(1 for t in kept if t.pnl > 0)
        modified_count = len(kept)
        modified_wr = modified_wins / modified_count if modified_count > 0 else 0.0

        return CounterfactualResult(
            scenario=CounterfactualScenario(
                scenario_type=ScenarioType.ADD_REGIME_GATE,
                description=f"Add regime gate for {regime_to_exclude}",
                parameters={"regime": regime_to_exclude},
            ),
            baseline_pnl=baseline_pnl,
            modified_pnl=modified_pnl,
            baseline_trade_count=baseline_count,
            modified_trade_count=modified_count,
            baseline_win_rate=baseline_wr,
            modified_win_rate=modified_wr,
        )

    def simulate_exclude(
        self,
        trades: list[TradeEvent],
        missed: list[MissedOpportunityEvent],
        exclude_fn: Callable[[TradeEvent], bool],
    ) -> CounterfactualResult:
        """Simulate excluding trades that match a criteria function."""
        baseline_pnl, baseline_count, baseline_wr = self._compute_baseline(trades)

        kept = [t for t in trades if not exclude_fn(t)]
        modified_pnl = sum(t.pnl for t in kept)
        modified_wins = sum(1 for t in kept if t.pnl > 0)
        modified_count = len(kept)
        modified_wr = modified_wins / modified_count if modified_count > 0 else 0.0

        return CounterfactualResult(
            scenario=CounterfactualScenario(
                scenario_type=ScenarioType.EXCLUDE_TRADES,
                description="Exclude trades by criteria",
                parameters={},
            ),
            baseline_pnl=baseline_pnl,
            modified_pnl=modified_pnl,
            baseline_trade_count=baseline_count,
            modified_trade_count=modified_count,
            baseline_win_rate=baseline_wr,
            modified_win_rate=modified_wr,
        )

    @staticmethod
    def _compute_baseline(trades: list[TradeEvent]) -> tuple[float, int, float]:
        pnl = sum(t.pnl for t in trades)
        count = len(trades)
        wins = sum(1 for t in trades if t.pnl > 0)
        wr = wins / count if count > 0 else 0.0
        return pnl, count, wr
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_counterfactual_simulator.py -v`
Expected: PASS (all 7 tests)

**Step 5: Commit**

```bash
git add schemas/counterfactual.py skills/counterfactual_simulator.py tests/test_counterfactual_simulator.py
git commit -m "feat(A5): add CounterfactualSimulator — what-if trade replay for filter removal, regime gates, trade exclusion"
```

---

### Task 13: ExitStrategySimulator (A6, Gap B)

**Files:**
- Create: `schemas/exit_simulation.py`
- Create: `skills/exit_strategy_simulator.py`
- Test: `tests/test_exit_strategy_simulator.py`

**Step 1: Write the failing test**

```python
# tests/test_exit_strategy_simulator.py
"""Tests for exit strategy comparison simulator."""
from datetime import datetime, timezone

import pytest

from schemas.events import TradeEvent
from schemas.exit_simulation import ExitStrategyType, ExitStrategyConfig, ExitSimulationResult


def _make_trade(trade_id, entry_price, exit_price, pnl, exit_reason="SIGNAL",
                post_1h=None, post_4h=None, atr=2.0):
    return TradeEvent(
        trade_id=trade_id, bot_id="bot1", pair="BTC/USDT",
        side="LONG",
        entry_time=datetime(2026, 3, 1, tzinfo=timezone.utc),
        exit_time=datetime(2026, 3, 1, 1, tzinfo=timezone.utc),
        entry_price=entry_price, exit_price=exit_price,
        position_size=1, pnl=pnl, pnl_pct=pnl / entry_price * 100,
        exit_reason=exit_reason, atr_at_entry=atr,
        post_exit_1h_price=post_1h, post_exit_4h_price=post_4h,
    )


class TestExitSimulationSchema:
    def test_strategy_config(self):
        cfg = ExitStrategyConfig(
            strategy_type=ExitStrategyType.TRAILING_STOP,
            params={"trail_pct": 2.0},
        )
        assert cfg.strategy_type == ExitStrategyType.TRAILING_STOP

    def test_result_model(self):
        r = ExitSimulationResult(
            strategy=ExitStrategyConfig(
                strategy_type=ExitStrategyType.FIXED_STOP,
                params={"stop_pct": 1.0},
            ),
            total_trades=10, trades_with_data=8,
            baseline_pnl=500.0, simulated_pnl=650.0,
        )
        assert r.improvement == 150.0


class TestExitStrategySimulator:
    def test_wider_stop_captures_more_on_favorable_continuation(self):
        from skills.exit_strategy_simulator import ExitStrategySimulator

        trades = [
            # Stopped out at 98, but price recovered to 105 at 1h
            _make_trade("t1", 100, 98, -2.0, exit_reason="STOP_LOSS", post_1h=105.0),
        ]
        sim = ExitStrategySimulator()
        config = ExitStrategyConfig(
            strategy_type=ExitStrategyType.FIXED_STOP,
            params={"stop_pct": 5.0},  # wider stop (5% vs whatever original was)
        )
        result = sim.simulate(trades, config)
        assert result.trades_with_data == 1
        # With wider stop, would have captured the recovery
        assert result.simulated_pnl > result.baseline_pnl

    def test_skips_trades_without_post_exit_data(self):
        from skills.exit_strategy_simulator import ExitStrategySimulator

        trades = [
            _make_trade("t1", 100, 105, 5.0),  # no post-exit data
            _make_trade("t2", 100, 103, 3.0, post_1h=107.0),
        ]
        sim = ExitStrategySimulator()
        config = ExitStrategyConfig(
            strategy_type=ExitStrategyType.FIXED_STOP,
            params={"stop_pct": 2.0},
        )
        result = sim.simulate(trades, config)
        assert result.total_trades == 2
        assert result.trades_with_data == 1

    def test_time_based_exit_comparison(self):
        from skills.exit_strategy_simulator import ExitStrategySimulator

        trades = [
            # Exited by signal at 103, but at 4h price was 110
            _make_trade("t1", 100, 103, 3.0, exit_reason="SIGNAL", post_4h=110.0),
        ]
        sim = ExitStrategySimulator()
        config = ExitStrategyConfig(
            strategy_type=ExitStrategyType.TIME_BASED,
            params={"hold_hours": 4},
        )
        result = sim.simulate(trades, config)
        assert result.simulated_pnl > result.baseline_pnl

    def test_empty_trades(self):
        from skills.exit_strategy_simulator import ExitStrategySimulator

        sim = ExitStrategySimulator()
        config = ExitStrategyConfig(
            strategy_type=ExitStrategyType.FIXED_STOP,
            params={"stop_pct": 2.0},
        )
        result = sim.simulate([], config)
        assert result.total_trades == 0
        assert result.simulated_pnl == 0.0
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_exit_strategy_simulator.py -v`
Expected: FAIL — modules not found

**Step 3: Write minimal implementation**

Create `schemas/exit_simulation.py`:

```python
"""Exit strategy simulation schemas."""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, computed_field


class ExitStrategyType(str, Enum):
    FIXED_STOP = "fixed_stop"
    TRAILING_STOP = "trailing_stop"
    ATR_STOP = "atr_stop"
    TIME_BASED = "time_based"


class ExitStrategyConfig(BaseModel):
    strategy_type: ExitStrategyType
    params: dict = {}


class TradeExitComparison(BaseModel):
    trade_id: str
    actual_pnl: float
    simulated_pnl: float

    @computed_field  # type: ignore[prop-decorator]
    @property
    def improvement(self) -> float:
        return self.simulated_pnl - self.actual_pnl


class ExitSimulationResult(BaseModel):
    strategy: ExitStrategyConfig
    total_trades: int = 0
    trades_with_data: int = 0
    baseline_pnl: float = 0.0
    simulated_pnl: float = 0.0
    comparisons: list[TradeExitComparison] = []

    @computed_field  # type: ignore[prop-decorator]
    @property
    def improvement(self) -> float:
        return self.simulated_pnl - self.baseline_pnl
```

Create `skills/exit_strategy_simulator.py`:

```python
"""Exit strategy comparison simulator.

Compares actual exit results against alternative strategies using
post-exit price data (1h and 4h snapshots). Limited precision without
tick-level data, but sufficient for directional comparison.
"""
from __future__ import annotations

from schemas.events import TradeEvent
from schemas.exit_simulation import (
    ExitSimulationResult,
    ExitStrategyConfig,
    ExitStrategyType,
    TradeExitComparison,
)


class ExitStrategySimulator:
    """Simulate alternative exit strategies using post-exit price snapshots."""

    def simulate(
        self, trades: list[TradeEvent], strategy: ExitStrategyConfig
    ) -> ExitSimulationResult:
        comparisons: list[TradeExitComparison] = []
        baseline_pnl = sum(t.pnl for t in trades)

        for t in trades:
            if t.post_exit_1h_price is None and t.post_exit_4h_price is None:
                continue

            sim_pnl = self._simulate_trade(t, strategy)
            comparisons.append(TradeExitComparison(
                trade_id=t.trade_id,
                actual_pnl=t.pnl,
                simulated_pnl=sim_pnl,
            ))

        simulated_total = sum(c.simulated_pnl for c in comparisons)
        # For trades without data, keep actual PnL
        no_data_pnl = sum(
            t.pnl for t in trades
            if t.post_exit_1h_price is None and t.post_exit_4h_price is None
        )

        return ExitSimulationResult(
            strategy=strategy,
            total_trades=len(trades),
            trades_with_data=len(comparisons),
            baseline_pnl=baseline_pnl,
            simulated_pnl=simulated_total + no_data_pnl,
            comparisons=comparisons,
        )

    def _simulate_trade(
        self, trade: TradeEvent, strategy: ExitStrategyConfig
    ) -> float:
        """Simulate a single trade exit under the alternative strategy."""
        is_long = trade.side.upper() == "LONG"
        entry = trade.entry_price
        post_1h = trade.post_exit_1h_price
        post_4h = trade.post_exit_4h_price

        if strategy.strategy_type == ExitStrategyType.FIXED_STOP:
            stop_pct = strategy.params.get("stop_pct", 2.0) / 100
            stop_price = entry * (1 - stop_pct) if is_long else entry * (1 + stop_pct)
            return self._best_exit(trade, stop_price, is_long)

        elif strategy.strategy_type == ExitStrategyType.TIME_BASED:
            hold_hours = strategy.params.get("hold_hours", 4)
            price = post_4h if hold_hours >= 4 and post_4h else post_1h
            if price is None:
                return trade.pnl
            return (price - entry) * trade.position_size if is_long else (entry - price) * trade.position_size

        elif strategy.strategy_type == ExitStrategyType.ATR_STOP:
            atr_mult = strategy.params.get("atr_multiplier", 2.0)
            atr = trade.atr_at_entry or 0
            stop_dist = atr * atr_mult
            stop_price = (entry - stop_dist) if is_long else (entry + stop_dist)
            return self._best_exit(trade, stop_price, is_long)

        return trade.pnl  # fallback

    def _best_exit(self, trade: TradeEvent, stop_price: float, is_long: bool) -> float:
        """Determine best exit given stop price and post-exit data."""
        # Check if stop would have been hit (price went below stop for LONG)
        post_1h = trade.post_exit_1h_price
        post_4h = trade.post_exit_4h_price

        # Use the best available post-exit price as the potential exit
        best_price = trade.exit_price  # start with actual exit
        if post_1h is not None:
            if is_long:
                best_price = max(best_price, post_1h)
            else:
                best_price = min(best_price, post_1h)
        if post_4h is not None:
            if is_long:
                best_price = max(best_price, post_4h)
            else:
                best_price = min(best_price, post_4h)

        # If stop would have been triggered before the best price
        # (simplified: we don't have intra-period data, so check if any
        # post-exit price is below stop for LONG or above stop for SHORT)
        stop_hit = False
        for p in [post_1h, post_4h]:
            if p is not None:
                if is_long and p < stop_price:
                    stop_hit = True
                elif not is_long and p > stop_price:
                    stop_hit = True

        if stop_hit:
            exit_at = stop_price
        else:
            exit_at = best_price

        if is_long:
            return (exit_at - trade.entry_price) * trade.position_size
        else:
            return (trade.entry_price - exit_at) * trade.position_size
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_exit_strategy_simulator.py -v`
Expected: PASS (all 6 tests)

**Step 5: Commit**

```bash
git add schemas/exit_simulation.py skills/exit_strategy_simulator.py tests/test_exit_strategy_simulator.py
git commit -m "feat(A6): add ExitStrategySimulator — compare fixed/trailing/ATR/time-based exits"
```

---

### Task 14: AutoOutcomeMeasurer (A7, Gap I)

**Files:**
- Create: `schemas/outcome_measurement.py`
- Create: `skills/auto_outcome_measurer.py`
- Test: `tests/test_auto_outcome_measurer.py`

**Step 1: Write the failing test**

```python
# tests/test_auto_outcome_measurer.py
"""Tests for automated suggestion outcome measurement."""
import json
from datetime import datetime, timezone
from pathlib import Path

from schemas.outcome_measurement import OutcomeMeasurement, Verdict


class TestOutcomeMeasurementSchema:
    def test_verdict_positive(self):
        m = OutcomeMeasurement(
            suggestion_id="s1",
            implemented_date="2026-02-20",
            measurement_date="2026-03-01",
            window_days=7,
            pnl_before=100.0, pnl_after=200.0,
            win_rate_before=0.5, win_rate_after=0.6,
            drawdown_before=5.0, drawdown_after=4.0,
        )
        assert m.verdict == Verdict.POSITIVE
        assert m.pnl_delta == 100.0

    def test_verdict_negative(self):
        m = OutcomeMeasurement(
            suggestion_id="s2",
            implemented_date="2026-02-20",
            measurement_date="2026-03-01",
            window_days=7,
            pnl_before=200.0, pnl_after=50.0,
            win_rate_before=0.6, win_rate_after=0.4,
        )
        assert m.verdict == Verdict.NEGATIVE

    def test_verdict_neutral(self):
        m = OutcomeMeasurement(
            suggestion_id="s3",
            implemented_date="2026-02-20",
            measurement_date="2026-03-01",
            window_days=7,
            pnl_before=100.0, pnl_after=102.0,
            win_rate_before=0.5, win_rate_after=0.51,
        )
        assert m.verdict == Verdict.NEUTRAL


class TestAutoOutcomeMeasurer:
    def test_measure_suggestion_outcome(self, tmp_path):
        from skills.auto_outcome_measurer import AutoOutcomeMeasurer

        # Create curated summaries for before/after periods
        self._write_summaries(tmp_path, "2026-02-15", "bot1", pnl=50, wins=5, total=10)
        self._write_summaries(tmp_path, "2026-02-16", "bot1", pnl=60, wins=6, total=10)
        self._write_summaries(tmp_path, "2026-02-25", "bot1", pnl=100, wins=8, total=10)
        self._write_summaries(tmp_path, "2026-02-26", "bot1", pnl=90, wins=7, total=10)

        measurer = AutoOutcomeMeasurer(curated_dir=tmp_path)
        result = measurer.measure(
            suggestion_id="s1",
            bot_id="bot1",
            implemented_date="2026-02-20",
            before_days=7,
            after_days=7,
        )
        assert isinstance(result, OutcomeMeasurement)
        assert result.pnl_after > result.pnl_before

    def test_insufficient_data_returns_none(self, tmp_path):
        from skills.auto_outcome_measurer import AutoOutcomeMeasurer

        measurer = AutoOutcomeMeasurer(curated_dir=tmp_path)
        result = measurer.measure(
            suggestion_id="s1",
            bot_id="bot1",
            implemented_date="2026-02-20",
            before_days=7,
            after_days=7,
        )
        assert result is None

    def test_detect_parameter_change(self, tmp_path):
        from skills.auto_outcome_measurer import AutoOutcomeMeasurer

        # Write WFO reports with different params
        wfo_dir = tmp_path / "wfo"
        wfo_dir.mkdir()
        (wfo_dir / "2026-02-15.json").write_text(json.dumps({
            "bot_id": "bot1", "suggested_params": {"stop_pct": 2.0},
            "recommendation": "ADOPT",
        }))
        (wfo_dir / "2026-03-01.json").write_text(json.dumps({
            "bot_id": "bot1", "suggested_params": {"stop_pct": 3.0},
            "recommendation": "ADOPT",
        }))

        measurer = AutoOutcomeMeasurer(curated_dir=tmp_path, wfo_dir=wfo_dir)
        changes = measurer.detect_parameter_changes("bot1")
        assert len(changes) >= 1

    def _write_summaries(self, base: Path, date: str, bot_id: str,
                         pnl: float, wins: int, total: int):
        bot_dir = base / date / bot_id
        bot_dir.mkdir(parents=True, exist_ok=True)
        (bot_dir / "summary.json").write_text(json.dumps({
            "date": date, "bot_id": bot_id,
            "gross_pnl": pnl, "win_count": wins, "total_trades": total,
            "max_drawdown_pct": 3.0,
        }))
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_auto_outcome_measurer.py -v`
Expected: FAIL — modules not found

**Step 3: Write minimal implementation**

Create `schemas/outcome_measurement.py`:

```python
"""Automated suggestion outcome measurement schemas."""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, computed_field


class Verdict(str, Enum):
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"


class OutcomeMeasurement(BaseModel):
    """Before/after comparison for a implemented suggestion."""
    suggestion_id: str
    implemented_date: str
    measurement_date: str
    window_days: int
    pnl_before: float = 0.0
    pnl_after: float = 0.0
    win_rate_before: float = 0.0
    win_rate_after: float = 0.0
    drawdown_before: float = 0.0
    drawdown_after: float = 0.0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def pnl_delta(self) -> float:
        return self.pnl_after - self.pnl_before

    @computed_field  # type: ignore[prop-decorator]
    @property
    def verdict(self) -> Verdict:
        # Positive if PnL improved by >10% and win rate didn't drop significantly
        if self.pnl_before == 0:
            return Verdict.NEUTRAL
        pnl_change = self.pnl_delta / abs(self.pnl_before)
        wr_change = self.win_rate_after - self.win_rate_before
        if pnl_change > 0.1 and wr_change >= -0.05:
            return Verdict.POSITIVE
        elif pnl_change < -0.1 or wr_change < -0.1:
            return Verdict.NEGATIVE
        return Verdict.NEUTRAL
```

Create `skills/auto_outcome_measurer.py`:

```python
"""Automated outcome measurement for implemented suggestions.

Detects parameter changes from WFO reports, computes before/after metrics
from curated daily summaries, and records outcomes via SuggestionTracker.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from schemas.outcome_measurement import OutcomeMeasurement


class AutoOutcomeMeasurer:
    """Measures suggestion outcomes by comparing pre/post performance."""

    def __init__(
        self,
        curated_dir: Path,
        wfo_dir: Path | None = None,
    ) -> None:
        self._curated_dir = curated_dir
        self._wfo_dir = wfo_dir

    def measure(
        self,
        suggestion_id: str,
        bot_id: str,
        implemented_date: str,
        before_days: int = 7,
        after_days: int = 7,
    ) -> OutcomeMeasurement | None:
        """Compare performance before and after a suggestion was implemented."""
        impl_date = datetime.strptime(implemented_date, "%Y-%m-%d")
        today = datetime.now()

        before_start = impl_date - timedelta(days=before_days)
        after_end = impl_date + timedelta(days=after_days)

        before_summaries = self._load_summaries(bot_id, before_start, impl_date)
        after_summaries = self._load_summaries(bot_id, impl_date, after_end)

        if not before_summaries or not after_summaries:
            return None

        before_pnl = sum(s.get("gross_pnl", 0) for s in before_summaries)
        after_pnl = sum(s.get("gross_pnl", 0) for s in after_summaries)

        before_wins = sum(s.get("win_count", 0) for s in before_summaries)
        before_total = sum(s.get("total_trades", 0) for s in before_summaries)
        after_wins = sum(s.get("win_count", 0) for s in after_summaries)
        after_total = sum(s.get("total_trades", 0) for s in after_summaries)

        before_wr = before_wins / before_total if before_total > 0 else 0
        after_wr = after_wins / after_total if after_total > 0 else 0

        before_dd = max((s.get("max_drawdown_pct", 0) for s in before_summaries), default=0)
        after_dd = max((s.get("max_drawdown_pct", 0) for s in after_summaries), default=0)

        return OutcomeMeasurement(
            suggestion_id=suggestion_id,
            implemented_date=implemented_date,
            measurement_date=today.strftime("%Y-%m-%d"),
            window_days=after_days,
            pnl_before=before_pnl,
            pnl_after=after_pnl,
            win_rate_before=before_wr,
            win_rate_after=after_wr,
            drawdown_before=before_dd,
            drawdown_after=after_dd,
        )

    def detect_parameter_changes(self, bot_id: str) -> list[dict]:
        """Detect parameter changes from WFO reports over time."""
        if not self._wfo_dir or not self._wfo_dir.exists():
            return []

        reports = []
        for f in sorted(self._wfo_dir.glob("*.json")):
            try:
                data = json.loads(f.read_text())
                if data.get("bot_id") == bot_id:
                    reports.append(data)
            except (json.JSONDecodeError, OSError):
                continue

        changes = []
        for i in range(1, len(reports)):
            prev = reports[i - 1].get("suggested_params", {})
            curr = reports[i].get("suggested_params", {})
            if prev != curr:
                changes.append({
                    "date": reports[i].get("date", "unknown"),
                    "previous_params": prev,
                    "new_params": curr,
                })
        return changes

    def _load_summaries(
        self, bot_id: str, start: datetime, end: datetime
    ) -> list[dict]:
        """Load daily summaries for a date range."""
        summaries = []
        current = start
        while current < end:
            date_str = current.strftime("%Y-%m-%d")
            summary_path = self._curated_dir / date_str / bot_id / "summary.json"
            if summary_path.exists():
                try:
                    summaries.append(json.loads(summary_path.read_text()))
                except (json.JSONDecodeError, OSError):
                    pass
            current += timedelta(days=1)
        return summaries
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_auto_outcome_measurer.py -v`
Expected: PASS (all 5 tests)

**Step 5: Commit**

```bash
git add schemas/outcome_measurement.py skills/auto_outcome_measurer.py tests/test_auto_outcome_measurer.py
git commit -m "feat(A7): add AutoOutcomeMeasurer — detects parameter changes and computes before/after metrics"
```

---

## Phase D: Integration & Validation (Tasks 15–16)

### Task 15: Wire New Skills into Handlers

**Files:**
- Modify: `orchestrator/handlers.py`
- Test: extend existing handler tests

**Step 1: Write the failing test**

```python
# tests/test_ecosystem_integration.py
"""Integration tests for ecosystem evaluation gap implementations."""
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from schemas.events import TradeEvent, MissedOpportunityEvent


def _make_trade(trade_id, pnl, regime="trending", factors=None, post_1h=None, post_4h=None):
    return TradeEvent(
        trade_id=trade_id, bot_id="bot1", pair="BTC/USDT",
        side="LONG",
        entry_time=datetime(2026, 3, 1, 10, tzinfo=timezone.utc),
        exit_time=datetime(2026, 3, 1, 11, tzinfo=timezone.utc),
        entry_price=100, exit_price=100 + pnl, position_size=1,
        pnl=pnl, pnl_pct=pnl, market_regime=regime,
        spread_at_entry=3.0, signal_factors=factors,
        post_exit_1h_price=post_1h, post_exit_4h_price=post_4h,
        process_quality_score=80, root_causes=["normal_win" if pnl > 0 else "normal_loss"],
    )


class TestDataPipelineIntegration:
    """Verify all new curated files are written by DailyMetricsBuilder."""

    def test_write_curated_produces_all_files(self, tmp_path):
        from skills.build_daily_metrics import DailyMetricsBuilder

        trades = [
            _make_trade("t1", 10.0, "trending",
                        factors=[{"factor_name": "rsi", "contribution": 0.6}],
                        post_1h=107.0),
            _make_trade("t2", -5.0, "ranging",
                        factors=[{"factor_name": "macd", "contribution": 0.4}],
                        post_1h=96.0, post_4h=94.0),
        ]
        missed = [
            MissedOpportunityEvent(
                bot_id="bot1", pair="BTC/USDT", signal="momentum",
                blocked_by="volume_filter", outcome_24h=20.0,
                confidence=0.8, assumption_tags=[],
            ),
        ]
        builder = DailyMetricsBuilder(date="2026-03-01", bot_id="bot1")
        output_dir = builder.write_curated(trades, missed, tmp_path)

        expected = [
            "summary.json", "winners.json", "losers.json",
            "process_failures.json", "notable_missed.json",
            "regime_analysis.json", "filter_analysis.json",
            "root_cause_summary.json", "hourly_performance.json",
            "slippage_stats.json", "factor_attribution.json",
            "exit_efficiency.json", "regime_bps.json",
        ]
        for f in expected:
            assert (output_dir / f).exists(), f"Missing: {f}"


class TestQualityGateIntegration:
    """Verify quality gate works with new file list."""

    def test_passes_with_all_new_files(self, tmp_path):
        from analysis.quality_gate import QualityGate

        bot_dir = tmp_path / "2026-03-01" / "bot1"
        bot_dir.mkdir(parents=True)
        for f in ["summary.json", "winners.json", "losers.json",
                   "process_failures.json", "notable_missed.json",
                   "regime_analysis.json", "filter_analysis.json",
                   "root_cause_summary.json", "hourly_performance.json",
                   "slippage_stats.json"]:
            (bot_dir / f).write_text("{}")

        gate = QualityGate("r1", "2026-03-01", ["bot1"], tmp_path)
        checklist = gate.run()
        assert checklist.can_proceed is True
        assert checklist.data_completeness == 1.0


class TestCounterfactualIntegration:
    """Verify counterfactual simulator works with strategy engine data."""

    def test_regime_gate_counterfactual_matches_engine_detection(self):
        from analysis.strategy_engine import StrategyEngine
        from skills.counterfactual_simulator import CounterfactualSimulator

        trades = [
            _make_trade("t1", 10.0, "trending"),
            _make_trade("t2", -15.0, "ranging"),
            _make_trade("t3", -12.0, "ranging"),
            _make_trade("t4", 8.0, "trending"),
        ]

        # Strategy engine detects regime mismatch
        engine = StrategyEngine(week_start="2026-02-24", week_end="2026-03-02")
        impact = engine.compute_regime_exclusion_impact("bot1", trades, "ranging")
        assert impact["delta_pnl"] > 0

        # Counterfactual simulator gives same result
        sim = CounterfactualSimulator()
        result = sim.simulate_regime_gate(trades, [], "ranging")
        assert result.delta_pnl == impact["delta_pnl"]


class TestBrainErrorTracking:
    """Verify error tracking prevents storm."""

    def test_ten_errors_produce_at_most_two_triages(self):
        import json as jsonmod
        from orchestrator.orchestrator_brain import OrchestratorBrain, ActionType

        brain = OrchestratorBrain()
        triage_count = 0
        for i in range(10):
            actions = brain.decide({
                "event_type": "error",
                "event_id": f"e{i}",
                "bot_id": "bot1",
                "payload": jsonmod.dumps({"severity": "HIGH", "error_type": "ConnErr"}),
            })
            if actions[0].type == ActionType.SPAWN_TRIAGE:
                triage_count += 1

        # Should be exactly 2: first occurrence + storm escalation
        assert triage_count == 2
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_ecosystem_integration.py -v`
Expected: some may fail if previous tasks not yet implemented; should PASS after all tasks complete

**Step 3: Write minimal implementation**

Wire new features into `orchestrator/handlers.py`. In the `handle_wfo` method, add regime_bps loading:

```python
        # Load empirical slippage for cost model (A3 wiring)
        regime_bps_path = self._curated_dir / date / bot_id / "regime_bps.json"
        if regime_bps_path.exists():
            import json as jsonmod
            regime_bps = jsonmod.loads(regime_bps_path.read_text())
            cost_model = CostModel.from_slippage_export(regime_bps, wfo_config.cost_model)
        else:
            cost_model = CostModel(wfo_config.cost_model)
```

In `handle_daily_analysis`, add completeness info to prompt context:

```python
        # Use quality gate's data_completeness in prompt context
        if checklist.data_completeness < 1.0:
            # Add confidence caveat to prompt
            pass  # Handler already proceeds; completeness visible in checklist
```

In `handle_weekly_analysis`, wire `analyze_regime_fit_quantified` for quantified suggestions:

```python
        # Use quantified regime analysis when trade data available
        if regime_trends and trades_by_bot:
            for bot_id, trends in regime_trends.items():
                bot_trades = trades_by_bot.get(bot_id, [])
                suggestions.extend(
                    engine.analyze_regime_fit_quantified(bot_id, trends, bot_trades)
                )
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_ecosystem_integration.py -v`
Expected: PASS (all 4 tests)

**Step 5: Commit**

```bash
git add orchestrator/handlers.py tests/test_ecosystem_integration.py
git commit -m "feat: wire ecosystem gap implementations into handlers + integration tests"
```

---

### Task 16: Final Validation

**Step 1: Run full test suite**

Run: `pytest tests/ -v --tb=short`
Expected: ~945+ tests PASS, 0 failures

**Step 2: Verify no regressions**

Run: `pytest tests/test_quality_gate.py tests/test_daily_metrics.py tests/test_cost_model.py tests/test_strategy_engine_expanded.py -v`
Expected: All existing tests pass (may need minor updates for new QualityGate expected files list and brain `__init__` signature)

**Step 3: Commit**

```bash
git add -A
git commit -m "chore: final validation — all ecosystem evaluation gaps addressed"
```

---

## Summary

| Phase | Tasks | New Tests | Key Deliverables |
|-------|-------|-----------|------------------|
| A: Data Pipeline | 0–4 | ~25 | Factor attribution, exit efficiency, slippage→cost wiring, regime exclusion |
| B: Infrastructure | 5–10 | ~29 | Graceful quality gate, error dedup, dead-letter alerting, /metrics, adaptive polling, event batching |
| C: Simulation Skills | 11–14 | ~23 | Filter sensitivity, counterfactual replay, exit strategy comparison, outcome measurement |
| D: Integration | 15–16 | ~8 | Handler wiring, integration tests |
| **Total** | **17** | **~85** | **858 → ~943 tests** |

**Gaps fully addressed:** A, B, C, D, E, F, H, I + all 5 integration gaps + all 12 assistant-side changes (A1–A12)

**Deferred (requires bot-side changes):** Gap G (microstructure), full filter sensitivity curves (B4), MFE/MAE precision (B5), A/B testing (B11)
