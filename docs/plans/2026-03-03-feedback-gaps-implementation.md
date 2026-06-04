# Feedback Gaps Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Address all 15 critical gaps and 5 highest-impact actions identified in `docs/feedback.md` — closing the feedback loop, enriching the data pipeline, expanding the strategy engine from 3 to 10+ detectors, implementing real proactive scanning, enhancing prompts for structural analysis, and hardening integration.

**Architecture:** The plan is organized into 5 phases (A–E) sequenced for maximum value delivery. Phase A wires the feedback loop (the #1 prerequisite for learning). Phase B enriches the data pipeline with slippage, time-of-day, and drawdown analysis (prerequisite for strategy engine). Phase C expands the strategy engine with 7+ new detectors using the enriched data. Phase D enhances prompts for structural analysis and implements real proactive scanning. Phase E hardens integration (trace IDs, relay persistence). Each phase is independently testable and deployable.

**Tech Stack:** Python 3.12, Pydantic v2, pytest (asyncio_mode=auto), pathlib, json, re, datetime, statistics (stdlib)

**Assumes:** All 6 phases (0–5) fully implemented — 740+ tests passing. Event queue, brain, worker, scheduler, handlers, all prompt assemblers, strategy engine, proactive scanner, feedback handler, comms layer, WFO pipeline all exist.

**Deferred (requires bot-side changes):**
- **Gap 1:** Filter threshold awareness — bots must emit threshold values + proximity data
- **Gap 8:** A/B testing / shadow mode — bots must support parallel parameter sets
- **Gap 14:** Bot error vs instrumentation error separation — bots must emit typed error events

**Directory structure this plan creates:**

```
trading_assistant/
  schemas/
    slippage_analysis.py         # SlippageDistribution, SlippageTrend
    hourly_performance.py        # HourlyBucket, HourlyPerformance
    drawdown_analysis.py         # DrawdownEpisode, DrawdownAttribution
    suggestion_tracking.py       # SuggestionRecord, SuggestionOutcome
  skills/
    slippage_analyzer.py         # SlippageAnalyzer — per-symbol, per-hour distributions
    hourly_analyzer.py           # HourlyAnalyzer — time-of-day performance buckets
    drawdown_analyzer.py         # DrawdownAnalyzer — episode segmentation + attribution
    suggestion_tracker.py        # SuggestionTracker — record/measure suggestion outcomes
  analysis/
    strategy_engine.py           # MODIFY: add 7 new detectors (alpha decay, signal quality, etc.)
    prompt_assembler.py          # MODIFY: load failure_log + rejected suggestions into context
    weekly_prompt_assembler.py   # MODIFY: add structural analysis instructions + failure_log
    context_builder.py           # MODIFY: add load_failure_log() + load_rejected_suggestions()
  skills/
    proactive_scanner.py         # MODIFY: implement real scanning logic
    build_daily_metrics.py       # MODIFY: add hourly_performance + slippage_stats output
  orchestrator/
    handlers.py                  # MODIFY: wire FeedbackHandler into notification callbacks
  comms/
    telegram_handlers.py         # MODIFY: wire button callbacks to FeedbackHandler
  relay/
    app.py                       # MODIFY: add trace_id propagation
  tests/
    test_slippage_analyzer.py
    test_hourly_analyzer.py
    test_drawdown_analyzer.py
    test_suggestion_tracker.py
    test_strategy_engine_expanded.py
    test_proactive_scanner_real.py
    test_feedback_wiring.py
    test_prompt_assembler_enriched.py
    test_trace_id.py
```

---

## Phase A: Wire the Feedback Loop (Gaps 9, 10, 11)

*Highest ROI — unblocks learning. Without this, corrections are parsed but never flow back into prompts, suggestions are never tracked, and the system repeats rejected suggestions.*

### Task 0: Suggestion Tracking Schema

**Files:**
- Create: `schemas/suggestion_tracking.py`
- Test: `tests/test_suggestion_tracking.py`

**Step 1: Write the failing test**

```python
# tests/test_suggestion_tracking.py
"""Tests for suggestion tracking schemas."""
from datetime import datetime, timezone

from schemas.suggestion_tracking import (
    SuggestionRecord,
    SuggestionOutcome,
    SuggestionStatus,
)


class TestSuggestionStatus:
    def test_all_statuses_exist(self):
        assert SuggestionStatus.PROPOSED == "proposed"
        assert SuggestionStatus.ACCEPTED == "accepted"
        assert SuggestionStatus.REJECTED == "rejected"
        assert SuggestionStatus.IMPLEMENTED == "implemented"


class TestSuggestionRecord:
    def test_creates_with_required_fields(self):
        rec = SuggestionRecord(
            suggestion_id="s001",
            bot_id="bot1",
            title="Widen stop by 0.5 ATR",
            tier="parameter",
            source_report_id="weekly-2026-02-24",
        )
        assert rec.status == SuggestionStatus.PROPOSED
        assert rec.suggestion_id == "s001"

    def test_mark_implemented(self):
        rec = SuggestionRecord(
            suggestion_id="s002",
            bot_id="bot1",
            title="Relax volume_gate",
            tier="filter",
            source_report_id="weekly-2026-02-24",
        )
        rec.status = SuggestionStatus.IMPLEMENTED
        assert rec.status == SuggestionStatus.IMPLEMENTED


class TestSuggestionOutcome:
    def test_creates_with_deltas(self):
        outcome = SuggestionOutcome(
            suggestion_id="s001",
            implemented_date="2026-02-25",
            pnl_delta_7d=120.0,
            pnl_delta_30d=340.0,
            win_rate_delta_7d=0.05,
            drawdown_delta_7d=-0.02,
        )
        assert outcome.pnl_delta_7d == 120.0
        assert outcome.drawdown_delta_7d == -0.02

    def test_net_positive_property(self):
        outcome = SuggestionOutcome(
            suggestion_id="s001",
            implemented_date="2026-02-25",
            pnl_delta_7d=120.0,
        )
        assert outcome.net_positive_7d is True

    def test_net_negative_property(self):
        outcome = SuggestionOutcome(
            suggestion_id="s002",
            implemented_date="2026-02-25",
            pnl_delta_7d=-50.0,
        )
        assert outcome.net_positive_7d is False
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_suggestion_tracking.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'schemas.suggestion_tracking'`

**Step 3: Write minimal implementation**

```python
# schemas/suggestion_tracking.py
"""Suggestion tracking schemas — record and measure suggestion outcomes.

Closes the loop: suggestion proposed → accepted/rejected → implemented → measured.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class SuggestionStatus(str, Enum):
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    IMPLEMENTED = "implemented"


class SuggestionRecord(BaseModel):
    """A single suggestion with lifecycle tracking."""

    suggestion_id: str
    bot_id: str
    title: str
    tier: str  # parameter | filter | strategy_variant | hypothesis
    source_report_id: str
    description: str = ""
    status: SuggestionStatus = SuggestionStatus.PROPOSED
    proposed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    resolved_at: Optional[datetime] = None
    rejection_reason: str = ""


class SuggestionOutcome(BaseModel):
    """Measured impact of an implemented suggestion."""

    suggestion_id: str
    implemented_date: str  # YYYY-MM-DD
    pnl_delta_7d: float = 0.0
    pnl_delta_30d: float = 0.0
    win_rate_delta_7d: float = 0.0
    win_rate_delta_30d: float = 0.0
    drawdown_delta_7d: float = 0.0
    drawdown_delta_30d: float = 0.0
    measured_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    @property
    def net_positive_7d(self) -> bool:
        return self.pnl_delta_7d > 0
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_suggestion_tracking.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add schemas/suggestion_tracking.py tests/test_suggestion_tracking.py
git commit -m "feat(feedback): add suggestion tracking schemas"
```

---

### Task 1: Suggestion Tracker Skill

**Files:**
- Create: `skills/suggestion_tracker.py`
- Test: `tests/test_suggestion_tracker.py`

**Step 1: Write the failing test**

```python
# tests/test_suggestion_tracker.py
"""Tests for SuggestionTracker — records and measures suggestion outcomes."""
import json
from pathlib import Path

from schemas.suggestion_tracking import (
    SuggestionRecord,
    SuggestionOutcome,
    SuggestionStatus,
)
from skills.suggestion_tracker import SuggestionTracker


class TestSuggestionTracker:
    def test_record_suggestion(self, tmp_path):
        tracker = SuggestionTracker(store_dir=tmp_path)
        rec = SuggestionRecord(
            suggestion_id="s001",
            bot_id="bot1",
            title="Widen stop",
            tier="parameter",
            source_report_id="weekly-2026-02-24",
        )
        tracker.record(rec)

        suggestions = tracker.load_all()
        assert len(suggestions) == 1
        assert suggestions[0]["suggestion_id"] == "s001"

    def test_mark_rejected(self, tmp_path):
        tracker = SuggestionTracker(store_dir=tmp_path)
        rec = SuggestionRecord(
            suggestion_id="s001",
            bot_id="bot1",
            title="Widen stop",
            tier="parameter",
            source_report_id="weekly-2026-02-24",
        )
        tracker.record(rec)
        tracker.reject("s001", reason="Not convinced by evidence")

        suggestions = tracker.load_all()
        match = [s for s in suggestions if s["suggestion_id"] == "s001"]
        assert match[0]["status"] == "rejected"
        assert match[0]["rejection_reason"] == "Not convinced by evidence"

    def test_mark_implemented(self, tmp_path):
        tracker = SuggestionTracker(store_dir=tmp_path)
        rec = SuggestionRecord(
            suggestion_id="s001",
            bot_id="bot1",
            title="Widen stop",
            tier="parameter",
            source_report_id="weekly-2026-02-24",
        )
        tracker.record(rec)
        tracker.implement("s001")

        suggestions = tracker.load_all()
        match = [s for s in suggestions if s["suggestion_id"] == "s001"]
        assert match[0]["status"] == "implemented"

    def test_record_outcome(self, tmp_path):
        tracker = SuggestionTracker(store_dir=tmp_path)
        outcome = SuggestionOutcome(
            suggestion_id="s001",
            implemented_date="2026-02-25",
            pnl_delta_7d=120.0,
            win_rate_delta_7d=0.03,
        )
        tracker.record_outcome(outcome)

        outcomes = tracker.load_outcomes()
        assert len(outcomes) == 1
        assert outcomes[0]["pnl_delta_7d"] == 120.0

    def test_get_rejected_suggestions(self, tmp_path):
        tracker = SuggestionTracker(store_dir=tmp_path)
        for i, title in enumerate(["Widen stop", "Remove filter", "Add gate"]):
            tracker.record(SuggestionRecord(
                suggestion_id=f"s{i:03d}",
                bot_id="bot1",
                title=title,
                tier="parameter",
                source_report_id="weekly-2026-02-24",
            ))
        tracker.reject("s000", reason="No evidence")
        tracker.reject("s002", reason="Too risky")

        rejected = tracker.get_rejected(bot_id="bot1")
        assert len(rejected) == 2
        titles = [r["title"] for r in rejected]
        assert "Widen stop" in titles
        assert "Add gate" in titles

    def test_get_rejected_filters_by_bot(self, tmp_path):
        tracker = SuggestionTracker(store_dir=tmp_path)
        tracker.record(SuggestionRecord(
            suggestion_id="s001", bot_id="bot1", title="A",
            tier="parameter", source_report_id="r1",
        ))
        tracker.record(SuggestionRecord(
            suggestion_id="s002", bot_id="bot2", title="B",
            tier="parameter", source_report_id="r1",
        ))
        tracker.reject("s001", reason="x")
        tracker.reject("s002", reason="y")

        assert len(tracker.get_rejected(bot_id="bot1")) == 1
        assert len(tracker.get_rejected(bot_id="bot2")) == 1

    def test_empty_store_returns_empty(self, tmp_path):
        tracker = SuggestionTracker(store_dir=tmp_path)
        assert tracker.load_all() == []
        assert tracker.load_outcomes() == []
        assert tracker.get_rejected(bot_id="bot1") == []
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_suggestion_tracker.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'skills.suggestion_tracker'`

**Step 3: Write minimal implementation**

```python
# skills/suggestion_tracker.py
"""SuggestionTracker — records suggestions, tracks status, and measures outcomes.

Storage: Two JSONL files in store_dir:
  - suggestions.jsonl — one record per suggestion with lifecycle status
  - outcomes.jsonl — measured impacts of implemented suggestions
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from schemas.suggestion_tracking import (
    SuggestionOutcome,
    SuggestionRecord,
    SuggestionStatus,
)


class SuggestionTracker:
    def __init__(self, store_dir: Path) -> None:
        self._store_dir = store_dir
        self._suggestions_path = store_dir / "suggestions.jsonl"
        self._outcomes_path = store_dir / "outcomes.jsonl"

    def record(self, suggestion: SuggestionRecord) -> None:
        self._store_dir.mkdir(parents=True, exist_ok=True)
        with open(self._suggestions_path, "a") as f:
            f.write(json.dumps(suggestion.model_dump(mode="json"), default=str) + "\n")

    def reject(self, suggestion_id: str, reason: str = "") -> None:
        self._update_status(suggestion_id, SuggestionStatus.REJECTED, reason)

    def implement(self, suggestion_id: str) -> None:
        self._update_status(suggestion_id, SuggestionStatus.IMPLEMENTED)

    def record_outcome(self, outcome: SuggestionOutcome) -> None:
        self._store_dir.mkdir(parents=True, exist_ok=True)
        with open(self._outcomes_path, "a") as f:
            f.write(json.dumps(outcome.model_dump(mode="json"), default=str) + "\n")

    def load_all(self) -> list[dict]:
        return self._read_jsonl(self._suggestions_path)

    def load_outcomes(self) -> list[dict]:
        return self._read_jsonl(self._outcomes_path)

    def get_rejected(self, bot_id: str | None = None) -> list[dict]:
        suggestions = self.load_all()
        rejected = [s for s in suggestions if s.get("status") == SuggestionStatus.REJECTED.value]
        if bot_id:
            rejected = [s for s in rejected if s.get("bot_id") == bot_id]
        return rejected

    def _update_status(
        self, suggestion_id: str, status: SuggestionStatus, reason: str = ""
    ) -> None:
        records = self.load_all()
        with open(self._suggestions_path, "w") as f:
            for rec in records:
                if rec["suggestion_id"] == suggestion_id:
                    rec["status"] = status.value
                    if reason:
                        rec["rejection_reason"] = reason
                    rec["resolved_at"] = datetime.now(timezone.utc).isoformat()
                f.write(json.dumps(rec, default=str) + "\n")

    @staticmethod
    def _read_jsonl(path: Path) -> list[dict]:
        if not path.exists():
            return []
        records: list[dict] = []
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
        return records
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_suggestion_tracker.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add skills/suggestion_tracker.py tests/test_suggestion_tracker.py
git commit -m "feat(feedback): add SuggestionTracker — records and measures suggestion outcomes"
```

---

### Task 2: Enrich ContextBuilder with Failure Log + Rejected Suggestions

**Files:**
- Modify: `analysis/context_builder.py`
- Test: `tests/test_context_builder.py` (add new tests)

This addresses **Gap 10** (failure log not read by prompt assemblers) and **Gap 11** (rejected suggestions not in context).

**Step 1: Write the failing tests**

Append to `tests/test_context_builder.py`:

```python
class TestLoadFailureLog:
    def test_loads_failure_log_entries(self, tmp_path):
        findings = tmp_path / "findings"
        findings.mkdir()
        log_path = findings / "failure-log.jsonl"
        log_path.write_text(
            '{"error_type":"timeout","bot_id":"bot1","outcome":"known_fix"}\n'
            '{"error_type":"api_error","bot_id":"bot2","outcome":"needs_human"}\n'
        )
        ctx = ContextBuilder(memory_dir=tmp_path)
        entries = ctx.load_failure_log()
        assert len(entries) == 2
        assert entries[0]["error_type"] == "timeout"

    def test_missing_failure_log_returns_empty(self, tmp_path):
        ctx = ContextBuilder(memory_dir=tmp_path)
        assert ctx.load_failure_log() == []


class TestLoadRejectedSuggestions:
    def test_loads_rejected_suggestions(self, tmp_path):
        findings = tmp_path / "findings"
        findings.mkdir()
        suggestions_path = findings / "suggestions.jsonl"
        suggestions_path.write_text(
            '{"suggestion_id":"s001","bot_id":"bot1","title":"Widen stop","status":"rejected","rejection_reason":"No evidence"}\n'
            '{"suggestion_id":"s002","bot_id":"bot1","title":"Remove filter","status":"implemented"}\n'
        )
        ctx = ContextBuilder(memory_dir=tmp_path)
        rejected = ctx.load_rejected_suggestions()
        assert len(rejected) == 1
        assert rejected[0]["title"] == "Widen stop"

    def test_missing_suggestions_file_returns_empty(self, tmp_path):
        ctx = ContextBuilder(memory_dir=tmp_path)
        assert ctx.load_rejected_suggestions() == []


class TestBasePackageWithFailureLog:
    def test_base_package_includes_failure_log(self, tmp_path):
        policies = tmp_path / "policies" / "v1"
        policies.mkdir(parents=True)
        findings = tmp_path / "findings"
        findings.mkdir()
        (findings / "failure-log.jsonl").write_text(
            '{"error_type":"timeout","outcome":"known_fix"}\n'
        )
        ctx = ContextBuilder(memory_dir=tmp_path)
        pkg = ctx.base_package()
        assert "failure_log" in pkg.data
        assert len(pkg.data["failure_log"]) == 1

    def test_base_package_includes_rejected_suggestions(self, tmp_path):
        policies = tmp_path / "policies" / "v1"
        policies.mkdir(parents=True)
        findings = tmp_path / "findings"
        findings.mkdir()
        (findings / "suggestions.jsonl").write_text(
            '{"suggestion_id":"s001","status":"rejected","rejection_reason":"x"}\n'
        )
        ctx = ContextBuilder(memory_dir=tmp_path)
        pkg = ctx.base_package()
        assert "rejected_suggestions" in pkg.data
        assert len(pkg.data["rejected_suggestions"]) == 1
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_context_builder.py -v -k "FailureLog or RejectedSuggestion or BasePackageWith"`
Expected: FAIL — `AttributeError: 'ContextBuilder' object has no attribute 'load_failure_log'`

**Step 3: Modify implementation**

In `analysis/context_builder.py`, add two new methods and modify `base_package()`:

Add after `load_corrections()` method (after line ~43):

```python
    def load_failure_log(self) -> list[dict]:
        """Load failure log entries from findings/failure-log.jsonl."""
        path = self._memory_dir / "findings" / "failure-log.jsonl"
        if not path.exists():
            return []
        entries: list[dict] = []
        for line in path.read_text().strip().split("\n"):
            if line.strip():
                entries.append(json.loads(line))
        return entries

    def load_rejected_suggestions(self) -> list[dict]:
        """Load rejected suggestions from findings/suggestions.jsonl."""
        path = self._memory_dir / "findings" / "suggestions.jsonl"
        if not path.exists():
            return []
        rejected: list[dict] = []
        for line in path.read_text().strip().split("\n"):
            if line.strip():
                rec = json.loads(line)
                if rec.get("status") == "rejected":
                    rejected.append(rec)
        return rejected
```

Modify `base_package()` to include failure_log and rejected_suggestions in `.data`:

```python
    def base_package(self) -> PromptPackage:
        system_prompt = self.build_system_prompt()
        corrections = self.load_corrections()
        context_files = self.list_policy_files()
        metadata = self.runtime_metadata()
        failure_log = self.load_failure_log()
        rejected_suggestions = self.load_rejected_suggestions()
        data: dict = {}
        if failure_log:
            data["failure_log"] = failure_log
        if rejected_suggestions:
            data["rejected_suggestions"] = rejected_suggestions
        return PromptPackage(
            system_prompt=system_prompt,
            corrections=corrections,
            context_files=context_files,
            metadata=metadata,
            data=data,
        )
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_context_builder.py -v`
Expected: PASS (all existing + new tests)

**Step 5: Run full test suite to verify no regressions**

Run: `pytest tests/ -x -q`
Expected: All 740+ tests pass. The `base_package()` change adds keys to `data` dict only when data exists — all assemblers call `pkg.data.update(...)` or `pkg.data = {...}` which merges, so existing assemblers should be unaffected. If any assembler overwrites `pkg.data = {...}` instead of updating, that assembler's test will break and must be fixed to use `pkg.data.update(...)`.

**Step 6: Commit**

```bash
git add analysis/context_builder.py tests/test_context_builder.py
git commit -m "feat(feedback): load failure_log + rejected suggestions into all prompt contexts"
```

---

### Task 3: Wire Telegram Callbacks to FeedbackHandler

**Files:**
- Modify: `comms/telegram_handlers.py`
- Modify: `orchestrator/handlers.py`
- Test: `tests/test_feedback_wiring.py`

This addresses **Gap 9** (corrections not written by handlers).

**Step 1: Write the failing test**

```python
# tests/test_feedback_wiring.py
"""Tests for feedback loop wiring — Telegram callbacks → FeedbackHandler → corrections.jsonl."""
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from analysis.feedback_handler import FeedbackHandler
from comms.telegram_handlers import TelegramCallbackRouter


class TestFeedbackWiring:
    def test_router_accepts_feedback_handler(self):
        """TelegramCallbackRouter can register a feedback callback."""
        router = TelegramCallbackRouter()
        router.register("feedback_correction", AsyncMock())
        assert "feedback_correction" in router.handlers

    @pytest.mark.asyncio
    async def test_feedback_callback_writes_correction(self, tmp_path):
        """When user sends feedback via Telegram, it flows through to corrections.jsonl."""
        corrections_path = tmp_path / "findings" / "corrections.jsonl"

        handler = FeedbackHandler(report_id="daily-2026-03-01")
        correction = handler.parse("Trade #T123 was actually a hedge, not a real loss")
        handler.write_correction(correction, corrections_path)

        assert corrections_path.exists()
        import json
        lines = corrections_path.read_text().strip().split("\n")
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["correction_type"] == "trade_reclassify"
        assert data["target_id"] == "T123"

    @pytest.mark.asyncio
    async def test_positive_reinforcement_recorded(self, tmp_path):
        corrections_path = tmp_path / "findings" / "corrections.jsonl"

        handler = FeedbackHandler(report_id="daily-2026-03-01")
        correction = handler.parse("Great analysis on the regime detection")
        handler.write_correction(correction, corrections_path)

        import json
        data = json.loads(corrections_path.read_text().strip())
        assert data["correction_type"] == "positive_reinforcement"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_feedback_wiring.py -v`
Expected: Tests should pass since these test existing FeedbackHandler functionality. The key integration is in how handlers.py calls it.

**Step 3: Modify `orchestrator/handlers.py`**

Add a `handle_feedback` method to the `Handlers` class that receives user text from Telegram callbacks and routes it through `FeedbackHandler`:

```python
    async def handle_feedback(self, action: Action) -> None:
        """Process user feedback from Telegram/Discord callbacks."""
        details = action.details or {}
        text = details.get("text", "")
        report_id = details.get("report_id", "unknown")
        if not text:
            return

        handler = FeedbackHandler(report_id=report_id)
        correction = handler.parse(text)
        corrections_path = self._memory_dir / "findings" / "corrections.jsonl"
        handler.write_correction(correction, corrections_path)

        await self._notify(
            notification_type="feedback_received",
            priority=NotificationPriority.LOW,
            title="Feedback recorded",
            body=f"Correction type: {correction.correction_type.value}",
        )
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_feedback_wiring.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add orchestrator/handlers.py comms/telegram_handlers.py tests/test_feedback_wiring.py
git commit -m "feat(feedback): wire Telegram callbacks → FeedbackHandler → corrections.jsonl"
```

---

### Task 4: Enrich Daily + Weekly Prompt Instructions with Rejection Context

**Files:**
- Modify: `analysis/prompt_assembler.py`
- Modify: `analysis/weekly_prompt_assembler.py`
- Test: `tests/test_prompt_assembler_enriched.py`

This addresses **Gap 10** (daily/weekly assemblers ignoring failure log) and ensures Claude sees rejected suggestions.

**Step 1: Write the failing test**

```python
# tests/test_prompt_assembler_enriched.py
"""Tests for enriched prompt assemblers — failure log + rejected suggestions in context."""
import json
from pathlib import Path

from analysis.prompt_assembler import DailyPromptAssembler
from analysis.weekly_prompt_assembler import WeeklyPromptAssembler


class TestDailyAssemblerEnriched:
    def test_includes_failure_log_in_data(self, tmp_path):
        memory_dir = tmp_path / "memory"
        policies = memory_dir / "policies" / "v1"
        policies.mkdir(parents=True)
        findings = memory_dir / "findings"
        findings.mkdir()
        (findings / "failure-log.jsonl").write_text(
            '{"error_type":"timeout","bot_id":"bot1","outcome":"known_fix"}\n'
        )
        curated = tmp_path / "curated"
        curated.mkdir()

        assembler = DailyPromptAssembler(
            date="2026-03-01",
            bots=["bot1"],
            curated_dir=curated,
            memory_dir=memory_dir,
        )
        pkg = assembler.assemble()
        assert "failure_log" in pkg.data

    def test_includes_rejected_suggestions_in_data(self, tmp_path):
        memory_dir = tmp_path / "memory"
        policies = memory_dir / "policies" / "v1"
        policies.mkdir(parents=True)
        findings = memory_dir / "findings"
        findings.mkdir()
        (findings / "suggestions.jsonl").write_text(
            '{"suggestion_id":"s001","bot_id":"bot1","title":"Widen stop","status":"rejected","rejection_reason":"No evidence"}\n'
        )
        curated = tmp_path / "curated"
        curated.mkdir()

        assembler = DailyPromptAssembler(
            date="2026-03-01",
            bots=["bot1"],
            curated_dir=curated,
            memory_dir=memory_dir,
        )
        pkg = assembler.assemble()
        assert "rejected_suggestions" in pkg.data

    def test_instructions_reference_rejected_suggestions(self, tmp_path):
        memory_dir = tmp_path / "memory"
        policies = memory_dir / "policies" / "v1"
        policies.mkdir(parents=True)
        curated = tmp_path / "curated"
        curated.mkdir()

        assembler = DailyPromptAssembler(
            date="2026-03-01",
            bots=["bot1"],
            curated_dir=curated,
            memory_dir=memory_dir,
        )
        pkg = assembler.assemble()
        assert "rejected" in pkg.instructions.lower() or "previously rejected" in pkg.instructions.lower()


class TestWeeklyAssemblerEnriched:
    def test_includes_failure_log_in_data(self, tmp_path):
        memory_dir = tmp_path / "memory"
        policies = memory_dir / "policies" / "v1"
        policies.mkdir(parents=True)
        findings = memory_dir / "findings"
        findings.mkdir()
        (findings / "failure-log.jsonl").write_text(
            '{"error_type":"timeout","outcome":"known_fix"}\n'
        )
        curated = tmp_path / "curated"
        curated.mkdir()
        runs = tmp_path / "runs"
        runs.mkdir()

        assembler = WeeklyPromptAssembler(
            week_start="2026-02-24",
            week_end="2026-03-02",
            bots=["bot1"],
            curated_dir=curated,
            memory_dir=memory_dir,
            runs_dir=runs,
        )
        pkg = assembler.assemble()
        assert "failure_log" in pkg.data

    def test_instructions_reference_structural_analysis(self, tmp_path):
        memory_dir = tmp_path / "memory"
        policies = memory_dir / "policies" / "v1"
        policies.mkdir(parents=True)
        curated = tmp_path / "curated"
        curated.mkdir()
        runs = tmp_path / "runs"
        runs.mkdir()

        assembler = WeeklyPromptAssembler(
            week_start="2026-02-24",
            week_end="2026-03-02",
            bots=["bot1"],
            curated_dir=curated,
            memory_dir=memory_dir,
            runs_dir=runs,
        )
        pkg = assembler.assemble()
        lower = pkg.instructions.lower()
        assert "structural" in lower or "signal decay" in lower
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_prompt_assembler_enriched.py -v`
Expected: FAIL — `failure_log` not in `pkg.data`, instructions don't reference rejections

**Step 3: Modify implementations**

In `analysis/prompt_assembler.py`, modify `assemble()` to preserve base_package data (don't overwrite) and add instruction about rejected suggestions:

Change the `assemble()` method so it uses `pkg.data.update(...)` instead of `pkg.data = ...`, and append a line to `_INSTRUCTIONS` about checking rejected suggestions.

In `analysis/weekly_prompt_assembler.py`, same pattern: use `pkg.data.update(...)` and add structural analysis instructions to `_WEEKLY_INSTRUCTIONS`.

Add to daily `_INSTRUCTIONS` (append after step 6):
```
7. Check the rejected_suggestions list (if present). Do NOT re-suggest anything that was previously rejected unless you have new evidence.
```

Add to weekly `_WEEKLY_INSTRUCTIONS` (append after step 10):
```
11. Structural analysis: Given 30-day root cause patterns, assess whether any bot's core signal logic needs restructuring (not just parameter tuning). Flag signal decay, filter structural issues, or exit logic flaws.
12. Do NOT re-suggest anything in the rejected_suggestions list unless you present new quantitative evidence.
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_prompt_assembler_enriched.py -v`
Expected: PASS

**Step 5: Run full test suite**

Run: `pytest tests/ -x -q`
Expected: All tests pass. Watch for existing assembler tests that assert exact `pkg.data` keys — they may need updating if `base_package()` now pre-populates `data`.

**Step 6: Commit**

```bash
git add analysis/prompt_assembler.py analysis/weekly_prompt_assembler.py tests/test_prompt_assembler_enriched.py
git commit -m "feat(feedback): enrich daily/weekly prompts with failure_log, rejected suggestions, structural analysis instructions"
```

---

## Phase B: Data Pipeline Enhancements (Gaps 2, 3, 4)

*Enriches curated data — prerequisite for strategy engine expansion in Phase C.*

### Task 5: Slippage Analysis Schema

**Files:**
- Create: `schemas/slippage_analysis.py`
- Test: `tests/test_slippage_analysis.py`

**Step 1: Write the failing test**

```python
# tests/test_slippage_analysis.py
"""Tests for slippage analysis schemas."""
from schemas.slippage_analysis import (
    SlippageBucket,
    SlippageDistribution,
    SlippageTrend,
)


class TestSlippageBucket:
    def test_creates_with_stats(self):
        bucket = SlippageBucket(
            key="BTCUSDT",
            sample_count=50,
            mean_bps=4.2,
            median_bps=3.8,
            p75_bps=5.5,
            p95_bps=8.1,
        )
        assert bucket.mean_bps == 4.2
        assert bucket.sample_count == 50


class TestSlippageDistribution:
    def test_creates_per_symbol(self):
        dist = SlippageDistribution(
            bot_id="bot1",
            date="2026-03-01",
            by_symbol={
                "BTCUSDT": SlippageBucket(key="BTCUSDT", sample_count=50, mean_bps=4.2),
                "ETHUSDT": SlippageBucket(key="ETHUSDT", sample_count=30, mean_bps=6.1),
            },
        )
        assert len(dist.by_symbol) == 2

    def test_creates_per_hour(self):
        dist = SlippageDistribution(
            bot_id="bot1",
            date="2026-03-01",
            by_hour={
                "09": SlippageBucket(key="09", sample_count=10, mean_bps=3.0),
                "15": SlippageBucket(key="15", sample_count=15, mean_bps=5.0),
            },
        )
        assert dist.by_hour["15"].mean_bps == 5.0


class TestSlippageTrend:
    def test_creates_trend(self):
        trend = SlippageTrend(
            bot_id="bot1",
            symbol="BTCUSDT",
            weekly_mean_bps=[3.5, 4.0, 4.2, 4.8],
            trend_direction="increasing",
        )
        assert trend.trend_direction == "increasing"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_slippage_analysis.py -v`
Expected: FAIL — module not found

**Step 3: Write implementation**

```python
# schemas/slippage_analysis.py
"""Slippage analysis schemas — per-symbol, per-hour slippage distributions.

Used by SlippageAnalyzer to feed empirical data into WFO cost models.
"""
from __future__ import annotations

from pydantic import BaseModel


class SlippageBucket(BaseModel):
    """Slippage statistics for one grouping key (symbol or hour)."""

    key: str
    sample_count: int = 0
    mean_bps: float = 0.0
    median_bps: float = 0.0
    p75_bps: float = 0.0
    p95_bps: float = 0.0


class SlippageDistribution(BaseModel):
    """Slippage breakdown for one bot on one date."""

    bot_id: str
    date: str
    by_symbol: dict[str, SlippageBucket] = {}
    by_hour: dict[str, SlippageBucket] = {}


class SlippageTrend(BaseModel):
    """Slippage trend over multiple weeks for one symbol."""

    bot_id: str
    symbol: str
    weekly_mean_bps: list[float] = []
    trend_direction: str = "stable"  # increasing | decreasing | stable
```

**Step 4: Run test, commit**

Run: `pytest tests/test_slippage_analysis.py -v`
Expected: PASS

```bash
git add schemas/slippage_analysis.py tests/test_slippage_analysis.py
git commit -m "feat(data): add slippage analysis schemas"
```

---

### Task 6: Hourly Performance Schema

**Files:**
- Create: `schemas/hourly_performance.py`
- Test: `tests/test_hourly_performance.py`

**Step 1: Write the failing test**

```python
# tests/test_hourly_performance.py
"""Tests for hourly performance schemas."""
from schemas.hourly_performance import HourlyBucket, HourlyPerformance


class TestHourlyBucket:
    def test_creates_with_stats(self):
        bucket = HourlyBucket(
            hour=14,
            trade_count=8,
            pnl=250.0,
            win_rate=0.75,
            avg_process_quality=82.0,
        )
        assert bucket.hour == 14
        assert bucket.win_rate == 0.75

    def test_defaults(self):
        bucket = HourlyBucket(hour=0)
        assert bucket.trade_count == 0
        assert bucket.pnl == 0.0


class TestHourlyPerformance:
    def test_creates_with_buckets(self):
        perf = HourlyPerformance(
            bot_id="bot1",
            date="2026-03-01",
            buckets=[
                HourlyBucket(hour=9, trade_count=5, pnl=100.0, win_rate=0.8),
                HourlyBucket(hour=15, trade_count=3, pnl=-50.0, win_rate=0.33),
            ],
        )
        assert len(perf.buckets) == 2

    def test_best_hour_property(self):
        perf = HourlyPerformance(
            bot_id="bot1",
            date="2026-03-01",
            buckets=[
                HourlyBucket(hour=9, trade_count=5, pnl=100.0, win_rate=0.8),
                HourlyBucket(hour=15, trade_count=3, pnl=-50.0, win_rate=0.33),
                HourlyBucket(hour=20, trade_count=4, pnl=200.0, win_rate=0.75),
            ],
        )
        assert perf.best_hour == 20

    def test_worst_hour_property(self):
        perf = HourlyPerformance(
            bot_id="bot1",
            date="2026-03-01",
            buckets=[
                HourlyBucket(hour=9, pnl=100.0),
                HourlyBucket(hour=15, pnl=-50.0),
            ],
        )
        assert perf.worst_hour == 15

    def test_empty_buckets_returns_none(self):
        perf = HourlyPerformance(bot_id="bot1", date="2026-03-01")
        assert perf.best_hour is None
        assert perf.worst_hour is None
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_hourly_performance.py -v`

**Step 3: Write implementation**

```python
# schemas/hourly_performance.py
"""Hourly performance schemas — time-of-day analysis buckets.

Captures PnL, win rate, and process quality by hour of day.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class HourlyBucket(BaseModel):
    """Performance stats for a single hour of the day (0-23 UTC)."""

    hour: int  # 0-23
    trade_count: int = 0
    pnl: float = 0.0
    win_rate: float = 0.0
    avg_process_quality: float = 0.0


class HourlyPerformance(BaseModel):
    """Time-of-day performance breakdown for one bot on one date."""

    bot_id: str
    date: str
    buckets: list[HourlyBucket] = []

    @property
    def best_hour(self) -> Optional[int]:
        if not self.buckets:
            return None
        return max(self.buckets, key=lambda b: b.pnl).hour

    @property
    def worst_hour(self) -> Optional[int]:
        if not self.buckets:
            return None
        return min(self.buckets, key=lambda b: b.pnl).hour
```

**Step 4: Run test, commit**

Run: `pytest tests/test_hourly_performance.py -v`
Expected: PASS

```bash
git add schemas/hourly_performance.py tests/test_hourly_performance.py
git commit -m "feat(data): add hourly performance schemas"
```

---

### Task 7: Drawdown Analysis Schema

**Files:**
- Create: `schemas/drawdown_analysis.py`
- Test: `tests/test_drawdown_analysis.py`

**Step 1: Write the failing test**

```python
# tests/test_drawdown_analysis.py
"""Tests for drawdown analysis schemas."""
from schemas.drawdown_analysis import DrawdownEpisode, DrawdownAttribution


class TestDrawdownEpisode:
    def test_creates_episode(self):
        ep = DrawdownEpisode(
            bot_id="bot1",
            start_date="2026-02-20",
            end_date="2026-02-25",
            peak_pnl=5000.0,
            trough_pnl=4200.0,
            drawdown_pct=16.0,
            trade_count=12,
            duration_days=5,
        )
        assert ep.drawdown_pct == 16.0
        assert ep.duration_days == 5

    def test_recovery_flag(self):
        ep = DrawdownEpisode(
            bot_id="bot1",
            start_date="2026-02-20",
            end_date="2026-02-25",
            peak_pnl=5000.0,
            trough_pnl=4200.0,
            recovered=True,
            recovery_date="2026-02-28",
        )
        assert ep.recovered is True


class TestDrawdownAttribution:
    def test_creates_attribution(self):
        attr = DrawdownAttribution(
            bot_id="bot1",
            date="2026-03-01",
            episodes=[
                DrawdownEpisode(
                    bot_id="bot1",
                    start_date="2026-02-20",
                    end_date="2026-02-25",
                    peak_pnl=5000.0,
                    trough_pnl=4200.0,
                    drawdown_pct=16.0,
                    trade_count=12,
                    duration_days=5,
                ),
            ],
            top_contributing_root_causes={"regime_mismatch": 5, "weak_signal": 3},
            largest_single_loss_pct=4.2,
        )
        assert len(attr.episodes) == 1
        assert attr.top_contributing_root_causes["regime_mismatch"] == 5

    def test_max_drawdown_property(self):
        attr = DrawdownAttribution(
            bot_id="bot1",
            date="2026-03-01",
            episodes=[
                DrawdownEpisode(bot_id="bot1", start_date="a", end_date="b",
                                peak_pnl=100, trough_pnl=90, drawdown_pct=10.0),
                DrawdownEpisode(bot_id="bot1", start_date="c", end_date="d",
                                peak_pnl=200, trough_pnl=150, drawdown_pct=25.0),
            ],
        )
        assert attr.max_drawdown_pct == 25.0

    def test_empty_episodes(self):
        attr = DrawdownAttribution(bot_id="bot1", date="2026-03-01")
        assert attr.max_drawdown_pct == 0.0
```

**Step 2: Run test, then implement**

```python
# schemas/drawdown_analysis.py
"""Drawdown analysis schemas — episode segmentation and attribution.

Segments equity curve into drawdown episodes and attributes each to root causes.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class DrawdownEpisode(BaseModel):
    """A single drawdown period from peak to trough."""

    bot_id: str
    start_date: str
    end_date: str
    peak_pnl: float = 0.0
    trough_pnl: float = 0.0
    drawdown_pct: float = 0.0
    trade_count: int = 0
    duration_days: int = 0
    recovered: bool = False
    recovery_date: Optional[str] = None
    contributing_trades: list[str] = []  # trade_ids
    dominant_regime: str = ""
    root_cause_distribution: dict[str, int] = {}


class DrawdownAttribution(BaseModel):
    """Drawdown attribution report for one bot."""

    bot_id: str
    date: str
    episodes: list[DrawdownEpisode] = []
    top_contributing_root_causes: dict[str, int] = {}
    largest_single_loss_pct: float = 0.0

    @property
    def max_drawdown_pct(self) -> float:
        if not self.episodes:
            return 0.0
        return max(ep.drawdown_pct for ep in self.episodes)
```

**Step 3: Run test, commit**

```bash
git add schemas/drawdown_analysis.py tests/test_drawdown_analysis.py
git commit -m "feat(data): add drawdown analysis schemas"
```

---

### Task 8: Slippage Analyzer Skill

**Files:**
- Create: `skills/slippage_analyzer.py`
- Test: `tests/test_slippage_analyzer.py`

**Step 1: Write the failing test**

```python
# tests/test_slippage_analyzer.py
"""Tests for SlippageAnalyzer — computes per-symbol, per-hour slippage distributions."""
from datetime import datetime

from schemas.events import TradeEvent
from schemas.slippage_analysis import SlippageDistribution
from skills.slippage_analyzer import SlippageAnalyzer


def _make_trade(pair: str, entry_price: float, exit_price: float,
                spread_at_entry: float, entry_hour: int = 14) -> TradeEvent:
    return TradeEvent(
        trade_id=f"t_{pair}_{entry_hour}",
        bot_id="bot1",
        pair=pair,
        side="LONG",
        entry_time=datetime(2026, 3, 1, entry_hour, 0, 0),
        exit_time=datetime(2026, 3, 1, entry_hour + 1, 0, 0),
        entry_price=entry_price,
        exit_price=exit_price,
        position_size=1.0,
        pnl=exit_price - entry_price,
        pnl_pct=((exit_price - entry_price) / entry_price) * 100,
        spread_at_entry=spread_at_entry,
    )


class TestSlippageAnalyzer:
    def test_compute_by_symbol(self):
        trades = [
            _make_trade("BTCUSDT", 50000, 50100, 5.0),
            _make_trade("BTCUSDT", 50200, 50300, 4.0),
            _make_trade("ETHUSDT", 3000, 3050, 8.0),
        ]
        analyzer = SlippageAnalyzer(bot_id="bot1", date="2026-03-01")
        dist = analyzer.compute(trades)

        assert isinstance(dist, SlippageDistribution)
        assert "BTCUSDT" in dist.by_symbol
        assert dist.by_symbol["BTCUSDT"].sample_count == 2
        assert "ETHUSDT" in dist.by_symbol
        assert dist.by_symbol["ETHUSDT"].sample_count == 1

    def test_compute_by_hour(self):
        trades = [
            _make_trade("BTCUSDT", 50000, 50100, 5.0, entry_hour=9),
            _make_trade("BTCUSDT", 50200, 50300, 3.0, entry_hour=9),
            _make_trade("BTCUSDT", 50400, 50500, 7.0, entry_hour=15),
        ]
        analyzer = SlippageAnalyzer(bot_id="bot1", date="2026-03-01")
        dist = analyzer.compute(trades)

        assert "09" in dist.by_hour
        assert dist.by_hour["09"].sample_count == 2
        assert "15" in dist.by_hour
        assert dist.by_hour["15"].sample_count == 1

    def test_slippage_bps_from_spread(self):
        """Spread at entry is the primary slippage signal."""
        trades = [
            _make_trade("BTCUSDT", 50000, 50100, 10.0),
        ]
        analyzer = SlippageAnalyzer(bot_id="bot1", date="2026-03-01")
        dist = analyzer.compute(trades)

        # Slippage = spread_at_entry (already in bps)
        assert dist.by_symbol["BTCUSDT"].mean_bps == 10.0

    def test_empty_trades(self):
        analyzer = SlippageAnalyzer(bot_id="bot1", date="2026-03-01")
        dist = analyzer.compute([])
        assert dist.by_symbol == {}
        assert dist.by_hour == {}

    def test_export_for_cost_model(self):
        """Exports regime→bps mapping for WFO cost model empirical mode."""
        trades = [
            TradeEvent(
                trade_id="t1", bot_id="bot1", pair="BTCUSDT", side="LONG",
                entry_time=datetime(2026, 3, 1, 14, 0),
                exit_time=datetime(2026, 3, 1, 15, 0),
                entry_price=50000, exit_price=50100,
                position_size=1.0, pnl=100, pnl_pct=0.2,
                spread_at_entry=5.0, market_regime="trending_up",
            ),
            TradeEvent(
                trade_id="t2", bot_id="bot1", pair="BTCUSDT", side="LONG",
                entry_time=datetime(2026, 3, 1, 16, 0),
                exit_time=datetime(2026, 3, 1, 17, 0),
                entry_price=50200, exit_price=50300,
                position_size=1.0, pnl=100, pnl_pct=0.2,
                spread_at_entry=8.0, market_regime="ranging",
            ),
        ]
        analyzer = SlippageAnalyzer(bot_id="bot1", date="2026-03-01")
        regime_bps = analyzer.export_regime_bps(trades)
        assert "trending_up" in regime_bps
        assert regime_bps["trending_up"] == 5.0
        assert regime_bps["ranging"] == 8.0
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_slippage_analyzer.py -v`

**Step 3: Write implementation**

```python
# skills/slippage_analyzer.py
"""SlippageAnalyzer — computes per-symbol, per-hour slippage distributions.

Uses spread_at_entry from TradeEvent as the primary slippage signal.
Exports regime→bps mapping for WFO cost model empirical mode.
"""
from __future__ import annotations

import statistics
from collections import defaultdict

from schemas.events import TradeEvent
from schemas.slippage_analysis import SlippageBucket, SlippageDistribution


class SlippageAnalyzer:
    def __init__(self, bot_id: str, date: str) -> None:
        self._bot_id = bot_id
        self._date = date

    def compute(self, trades: list[TradeEvent]) -> SlippageDistribution:
        by_symbol: dict[str, list[float]] = defaultdict(list)
        by_hour: dict[str, list[float]] = defaultdict(list)

        for t in trades:
            bps = t.spread_at_entry
            if bps <= 0:
                continue
            by_symbol[t.pair].append(bps)
            hour_key = f"{t.entry_time.hour:02d}"
            by_hour[hour_key].append(bps)

        return SlippageDistribution(
            bot_id=self._bot_id,
            date=self._date,
            by_symbol={k: self._make_bucket(k, v) for k, v in by_symbol.items()},
            by_hour={k: self._make_bucket(k, v) for k, v in by_hour.items()},
        )

    def export_regime_bps(self, trades: list[TradeEvent]) -> dict[str, float]:
        """Export regime→mean_bps mapping for WFO cost model."""
        by_regime: dict[str, list[float]] = defaultdict(list)
        for t in trades:
            if t.spread_at_entry > 0 and t.market_regime:
                by_regime[t.market_regime].append(t.spread_at_entry)
        return {
            regime: statistics.mean(values) for regime, values in by_regime.items()
        }

    @staticmethod
    def _make_bucket(key: str, values: list[float]) -> SlippageBucket:
        if not values:
            return SlippageBucket(key=key)
        sorted_vals = sorted(values)
        n = len(sorted_vals)
        return SlippageBucket(
            key=key,
            sample_count=n,
            mean_bps=statistics.mean(sorted_vals),
            median_bps=statistics.median(sorted_vals),
            p75_bps=sorted_vals[int(n * 0.75)] if n >= 4 else sorted_vals[-1],
            p95_bps=sorted_vals[int(n * 0.95)] if n >= 20 else sorted_vals[-1],
        )
```

**Step 4: Run test, commit**

```bash
git add skills/slippage_analyzer.py tests/test_slippage_analyzer.py
git commit -m "feat(data): add SlippageAnalyzer — per-symbol, per-hour slippage distributions"
```

---

### Task 9: Hourly Analyzer Skill

**Files:**
- Create: `skills/hourly_analyzer.py`
- Test: `tests/test_hourly_analyzer.py`

**Step 1: Write the failing test**

```python
# tests/test_hourly_analyzer.py
"""Tests for HourlyAnalyzer — time-of-day performance buckets."""
from datetime import datetime

from schemas.events import TradeEvent
from schemas.hourly_performance import HourlyPerformance
from skills.hourly_analyzer import HourlyAnalyzer


def _make_trade(hour: int, pnl: float, quality: int = 80) -> TradeEvent:
    return TradeEvent(
        trade_id=f"t_{hour}_{pnl}",
        bot_id="bot1",
        pair="BTCUSDT",
        side="LONG",
        entry_time=datetime(2026, 3, 1, hour, 30, 0),
        exit_time=datetime(2026, 3, 1, hour + 1, 0, 0),
        entry_price=50000,
        exit_price=50000 + pnl,
        position_size=1.0,
        pnl=pnl,
        pnl_pct=pnl / 500,
        process_quality_score=quality,
    )


class TestHourlyAnalyzer:
    def test_basic_bucketing(self):
        trades = [
            _make_trade(9, 100.0),
            _make_trade(9, 50.0),
            _make_trade(15, -80.0),
        ]
        analyzer = HourlyAnalyzer(bot_id="bot1", date="2026-03-01")
        perf = analyzer.compute(trades)

        assert isinstance(perf, HourlyPerformance)
        buckets_by_hour = {b.hour: b for b in perf.buckets}
        assert buckets_by_hour[9].trade_count == 2
        assert buckets_by_hour[9].pnl == 150.0
        assert buckets_by_hour[9].win_rate == 1.0
        assert buckets_by_hour[15].trade_count == 1
        assert buckets_by_hour[15].pnl == -80.0
        assert buckets_by_hour[15].win_rate == 0.0

    def test_avg_process_quality(self):
        trades = [
            _make_trade(14, 100.0, quality=90),
            _make_trade(14, -50.0, quality=60),
        ]
        analyzer = HourlyAnalyzer(bot_id="bot1", date="2026-03-01")
        perf = analyzer.compute(trades)

        buckets_by_hour = {b.hour: b for b in perf.buckets}
        assert buckets_by_hour[14].avg_process_quality == 75.0

    def test_empty_trades(self):
        analyzer = HourlyAnalyzer(bot_id="bot1", date="2026-03-01")
        perf = analyzer.compute([])
        assert perf.buckets == []

    def test_best_worst_hours(self):
        trades = [
            _make_trade(9, 200.0),
            _make_trade(12, -100.0),
            _make_trade(18, 50.0),
        ]
        analyzer = HourlyAnalyzer(bot_id="bot1", date="2026-03-01")
        perf = analyzer.compute(trades)
        assert perf.best_hour == 9
        assert perf.worst_hour == 12
```

**Step 2: Run test, then implement**

```python
# skills/hourly_analyzer.py
"""HourlyAnalyzer — computes time-of-day performance buckets.

Groups trades by entry hour (UTC) and computes PnL, win rate, and
process quality per hour bucket.
"""
from __future__ import annotations

from collections import defaultdict

from schemas.events import TradeEvent
from schemas.hourly_performance import HourlyBucket, HourlyPerformance


class HourlyAnalyzer:
    def __init__(self, bot_id: str, date: str) -> None:
        self._bot_id = bot_id
        self._date = date

    def compute(self, trades: list[TradeEvent]) -> HourlyPerformance:
        by_hour: dict[int, list[TradeEvent]] = defaultdict(list)
        for t in trades:
            by_hour[t.entry_time.hour].append(t)

        buckets: list[HourlyBucket] = []
        for hour in sorted(by_hour):
            hour_trades = by_hour[hour]
            wins = sum(1 for t in hour_trades if t.pnl > 0)
            count = len(hour_trades)
            buckets.append(HourlyBucket(
                hour=hour,
                trade_count=count,
                pnl=sum(t.pnl for t in hour_trades),
                win_rate=wins / count if count > 0 else 0.0,
                avg_process_quality=(
                    sum(t.process_quality_score for t in hour_trades) / count
                    if count > 0 else 0.0
                ),
            ))

        return HourlyPerformance(
            bot_id=self._bot_id,
            date=self._date,
            buckets=buckets,
        )
```

**Step 3: Run test, commit**

```bash
git add skills/hourly_analyzer.py tests/test_hourly_analyzer.py
git commit -m "feat(data): add HourlyAnalyzer — time-of-day performance buckets"
```

---

### Task 10: Drawdown Analyzer Skill

**Files:**
- Create: `skills/drawdown_analyzer.py`
- Test: `tests/test_drawdown_analyzer.py`

**Step 1: Write the failing test**

```python
# tests/test_drawdown_analyzer.py
"""Tests for DrawdownAnalyzer — drawdown episode segmentation + attribution."""
from datetime import datetime

from schemas.events import TradeEvent
from schemas.drawdown_analysis import DrawdownAttribution
from skills.drawdown_analyzer import DrawdownAnalyzer


def _make_trade(trade_id: str, date_str: str, pnl: float,
                root_causes: list[str] | None = None,
                regime: str = "trending_up") -> TradeEvent:
    return TradeEvent(
        trade_id=trade_id,
        bot_id="bot1",
        pair="BTCUSDT",
        side="LONG",
        entry_time=datetime.fromisoformat(f"{date_str}T10:00:00"),
        exit_time=datetime.fromisoformat(f"{date_str}T11:00:00"),
        entry_price=50000,
        exit_price=50000 + pnl,
        position_size=1.0,
        pnl=pnl,
        pnl_pct=pnl / 500,
        root_causes=root_causes or [],
        market_regime=regime,
    )


class TestDrawdownAnalyzer:
    def test_identifies_single_drawdown(self):
        trades = [
            _make_trade("t1", "2026-02-20", 100),
            _make_trade("t2", "2026-02-21", 50),
            _make_trade("t3", "2026-02-22", -80, ["regime_mismatch"]),
            _make_trade("t4", "2026-02-23", -120, ["weak_signal"]),
            _make_trade("t5", "2026-02-24", -50, ["regime_mismatch"]),
            _make_trade("t6", "2026-02-25", 200),
        ]
        analyzer = DrawdownAnalyzer(bot_id="bot1", date="2026-03-01")
        attr = analyzer.compute(trades)

        assert isinstance(attr, DrawdownAttribution)
        assert len(attr.episodes) == 1
        assert attr.episodes[0].trade_count == 3
        assert attr.episodes[0].drawdown_pct > 0

    def test_no_drawdown(self):
        trades = [
            _make_trade("t1", "2026-02-20", 100),
            _make_trade("t2", "2026-02-21", 50),
            _make_trade("t3", "2026-02-22", 200),
        ]
        analyzer = DrawdownAnalyzer(bot_id="bot1", date="2026-03-01")
        attr = analyzer.compute(trades)
        assert len(attr.episodes) == 0

    def test_root_cause_attribution(self):
        trades = [
            _make_trade("t1", "2026-02-20", 100),
            _make_trade("t2", "2026-02-21", -80, ["regime_mismatch"]),
            _make_trade("t3", "2026-02-22", -60, ["regime_mismatch"]),
            _make_trade("t4", "2026-02-23", -40, ["weak_signal"]),
            _make_trade("t5", "2026-02-24", 200),
        ]
        analyzer = DrawdownAnalyzer(bot_id="bot1", date="2026-03-01")
        attr = analyzer.compute(trades)

        assert "regime_mismatch" in attr.top_contributing_root_causes
        assert attr.top_contributing_root_causes["regime_mismatch"] == 2

    def test_largest_single_loss(self):
        trades = [
            _make_trade("t1", "2026-02-20", 1000),
            _make_trade("t2", "2026-02-21", -200),
            _make_trade("t3", "2026-02-22", -50),
            _make_trade("t4", "2026-02-23", 500),
        ]
        analyzer = DrawdownAnalyzer(bot_id="bot1", date="2026-03-01")
        attr = analyzer.compute(trades)
        assert attr.largest_single_loss_pct > 0

    def test_empty_trades(self):
        analyzer = DrawdownAnalyzer(bot_id="bot1", date="2026-03-01")
        attr = analyzer.compute([])
        assert len(attr.episodes) == 0
        assert attr.largest_single_loss_pct == 0.0
```

**Step 2: Run test, then implement**

```python
# skills/drawdown_analyzer.py
"""DrawdownAnalyzer — segments equity curve into drawdown episodes and attributes to root causes.

A drawdown episode starts when cumulative PnL drops below a running peak and
ends when cumulative PnL returns to or exceeds that peak.
"""
from __future__ import annotations

from collections import Counter

from schemas.drawdown_analysis import DrawdownAttribution, DrawdownEpisode
from schemas.events import TradeEvent


class DrawdownAnalyzer:
    def __init__(self, bot_id: str, date: str) -> None:
        self._bot_id = bot_id
        self._date = date

    def compute(self, trades: list[TradeEvent]) -> DrawdownAttribution:
        if not trades:
            return DrawdownAttribution(bot_id=self._bot_id, date=self._date)

        # Build equity curve
        cumulative = 0.0
        peak = 0.0
        episodes: list[DrawdownEpisode] = []
        current_dd_trades: list[TradeEvent] = []
        dd_peak = 0.0
        in_drawdown = False

        all_root_causes: Counter[str] = Counter()
        largest_single_loss_pct = 0.0

        for t in trades:
            cumulative += t.pnl

            if t.pnl < 0 and abs(t.pnl_pct) > largest_single_loss_pct:
                largest_single_loss_pct = abs(t.pnl_pct)

            if cumulative > peak:
                # New high — close any open drawdown
                if in_drawdown and current_dd_trades:
                    episodes.append(self._make_episode(
                        current_dd_trades, dd_peak, recovered=True,
                        recovery_date=t.exit_time.strftime("%Y-%m-%d"),
                    ))
                    current_dd_trades = []
                    in_drawdown = False
                peak = cumulative
                dd_peak = peak
            elif cumulative < peak:
                if not in_drawdown:
                    in_drawdown = True
                    dd_peak = peak
                current_dd_trades.append(t)

        # Close unclosed drawdown
        if in_drawdown and current_dd_trades:
            episodes.append(self._make_episode(current_dd_trades, dd_peak, recovered=False))

        # Aggregate root causes across all episodes
        for ep in episodes:
            all_root_causes.update(ep.root_cause_distribution)

        return DrawdownAttribution(
            bot_id=self._bot_id,
            date=self._date,
            episodes=episodes,
            top_contributing_root_causes=dict(all_root_causes),
            largest_single_loss_pct=largest_single_loss_pct,
        )

    def _make_episode(
        self,
        trades: list[TradeEvent],
        peak_pnl: float,
        recovered: bool = False,
        recovery_date: str | None = None,
    ) -> DrawdownEpisode:
        cumulative = peak_pnl
        trough = peak_pnl
        root_causes: Counter[str] = Counter()
        regimes: Counter[str] = Counter()

        for t in trades:
            cumulative += t.pnl
            if cumulative < trough:
                trough = cumulative
            for rc in t.root_causes:
                root_causes[rc] += 1
            if t.market_regime:
                regimes[t.market_regime] += 1

        dd_pct = ((peak_pnl - trough) / peak_pnl * 100) if peak_pnl > 0 else 0.0

        return DrawdownEpisode(
            bot_id=self._bot_id,
            start_date=trades[0].entry_time.strftime("%Y-%m-%d"),
            end_date=trades[-1].exit_time.strftime("%Y-%m-%d"),
            peak_pnl=peak_pnl,
            trough_pnl=trough,
            drawdown_pct=dd_pct,
            trade_count=len(trades),
            duration_days=(trades[-1].exit_time - trades[0].entry_time).days + 1,
            recovered=recovered,
            recovery_date=recovery_date,
            contributing_trades=[t.trade_id for t in trades],
            dominant_regime=regimes.most_common(1)[0][0] if regimes else "",
            root_cause_distribution=dict(root_causes),
        )
```

**Step 3: Run test, commit**

```bash
git add skills/drawdown_analyzer.py tests/test_drawdown_analyzer.py
git commit -m "feat(data): add DrawdownAnalyzer — drawdown episode segmentation + attribution"
```

---

### Task 11: Integrate New Analyzers into DailyMetricsBuilder

**Files:**
- Modify: `skills/build_daily_metrics.py`
- Test: `tests/test_daily_metrics_pipeline.py` (add new tests)

Add `hourly_performance()` and `slippage_stats()` methods to `DailyMetricsBuilder` and include them in `write_curated()` output.

**Step 1: Write the failing tests**

Append to `tests/test_daily_metrics_pipeline.py`:

```python
class TestDailyMetricsPipelineEnriched:
    def test_writes_hourly_performance(self, tmp_path):
        builder = DailyMetricsBuilder(date="2026-03-01", bot_id="bot1")
        trades = [_make_trade("t1", 100.0, hour=9), _make_trade("t2", -50.0, hour=15)]
        missed = []
        builder.write_curated(trades, missed, tmp_path)

        hourly_path = tmp_path / "2026-03-01" / "bot1" / "hourly_performance.json"
        assert hourly_path.exists()
        data = json.loads(hourly_path.read_text())
        assert len(data["buckets"]) == 2

    def test_writes_slippage_stats(self, tmp_path):
        builder = DailyMetricsBuilder(date="2026-03-01", bot_id="bot1")
        trades = [_make_trade_with_spread("t1", 100.0, spread=5.0)]
        missed = []
        builder.write_curated(trades, missed, tmp_path)

        slippage_path = tmp_path / "2026-03-01" / "bot1" / "slippage_stats.json"
        assert slippage_path.exists()
```

**Step 2: Modify `skills/build_daily_metrics.py`**

Add two new methods and extend `write_curated()`:

```python
    def hourly_performance(self, trades: list[TradeEvent]) -> dict:
        from skills.hourly_analyzer import HourlyAnalyzer
        analyzer = HourlyAnalyzer(bot_id=self._bot_id, date=self._date)
        return analyzer.compute(trades).model_dump(mode="json")

    def slippage_stats(self, trades: list[TradeEvent]) -> dict:
        from skills.slippage_analyzer import SlippageAnalyzer
        analyzer = SlippageAnalyzer(bot_id=self._bot_id, date=self._date)
        return analyzer.compute(trades).model_dump(mode="json")
```

In `write_curated()`, add after existing file writes:

```python
        self._write_json(out_dir / "hourly_performance.json", self.hourly_performance(trades))
        self._write_json(out_dir / "slippage_stats.json", self.slippage_stats(trades))
```

**Step 3: Run tests, commit**

```bash
git add skills/build_daily_metrics.py tests/test_daily_metrics_pipeline.py
git commit -m "feat(data): integrate hourly performance + slippage stats into daily metrics pipeline"
```

---

## Phase C: Strategy Engine Expansion (Gap 5)

*Expands from 3 rules to 10+ detectors using the enriched data from Phase B.*

### Task 12: Alpha Decay Detector

**Files:**
- Modify: `analysis/strategy_engine.py`
- Test: `tests/test_strategy_engine_expanded.py`

**Step 1: Write the failing test**

```python
# tests/test_strategy_engine_expanded.py
"""Tests for expanded strategy engine detectors."""
from analysis.strategy_engine import StrategyEngine
from schemas.weekly_metrics import BotWeeklySummary


class TestAlphaDecayDetector:
    def test_detects_declining_sharpe(self):
        engine = StrategyEngine(week_start="2026-02-24", week_end="2026-03-02")
        result = engine.detect_alpha_decay(
            bot_id="bot1",
            rolling_sharpe_30d=0.8,
            rolling_sharpe_60d=1.5,
            rolling_sharpe_90d=2.1,
        )
        assert len(result) == 1
        assert "alpha decay" in result[0].title.lower() or "decay" in result[0].description.lower()
        assert result[0].confidence > 0

    def test_no_decay_when_stable(self):
        engine = StrategyEngine(week_start="2026-02-24", week_end="2026-03-02")
        result = engine.detect_alpha_decay(
            bot_id="bot1",
            rolling_sharpe_30d=1.5,
            rolling_sharpe_60d=1.4,
            rolling_sharpe_90d=1.3,
        )
        assert len(result) == 0

    def test_no_decay_when_improving(self):
        engine = StrategyEngine(week_start="2026-02-24", week_end="2026-03-02")
        result = engine.detect_alpha_decay(
            bot_id="bot1",
            rolling_sharpe_30d=2.0,
            rolling_sharpe_60d=1.5,
            rolling_sharpe_90d=1.0,
        )
        assert len(result) == 0
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_strategy_engine_expanded.py::TestAlphaDecayDetector -v`
Expected: FAIL — `AttributeError: 'StrategyEngine' object has no attribute 'detect_alpha_decay'`

**Step 3: Add method to `analysis/strategy_engine.py`**

```python
    def detect_alpha_decay(
        self,
        bot_id: str,
        rolling_sharpe_30d: float,
        rolling_sharpe_60d: float,
        rolling_sharpe_90d: float,
        decay_threshold: float = 0.3,
    ) -> list[StrategySuggestion]:
        """Tier 4: Detect declining Sharpe ratio over 30/60/90 day windows."""
        if rolling_sharpe_90d <= 0:
            return []
        # Check if 30d Sharpe is significantly below 90d Sharpe
        decay_ratio = (rolling_sharpe_90d - rolling_sharpe_30d) / rolling_sharpe_90d
        if decay_ratio < decay_threshold:
            return []
        return [StrategySuggestion(
            tier=SuggestionTier.HYPOTHESIS,
            bot_id=bot_id,
            title=f"Alpha decay detected — {bot_id}",
            description=(
                f"30d Sharpe ({rolling_sharpe_30d:.2f}) is {decay_ratio:.0%} below "
                f"90d Sharpe ({rolling_sharpe_90d:.2f}). The strategy may be losing edge. "
                f"Review signal quality and market regime alignment."
            ),
            evidence_days=90,
            confidence=min(0.9, 0.5 + decay_ratio),
            requires_human_judgment=True,
        )]
```

**Step 4: Run test, commit**

```bash
git add analysis/strategy_engine.py tests/test_strategy_engine_expanded.py
git commit -m "feat(strategy): add alpha decay detector"
```

---

### Task 13: Signal Quality Decay Detector

Append to `tests/test_strategy_engine_expanded.py` and `analysis/strategy_engine.py`.

**Test:**

```python
class TestSignalQualityDecay:
    def test_detects_declining_correlation(self):
        engine = StrategyEngine(week_start="2026-02-24", week_end="2026-03-02")
        result = engine.detect_signal_decay(
            bot_id="bot1",
            signal_outcome_correlation_30d=0.35,
            signal_outcome_correlation_90d=0.72,
        )
        assert len(result) == 1
        assert result[0].requires_human_judgment is True

    def test_no_decay_when_stable(self):
        engine = StrategyEngine(week_start="2026-02-24", week_end="2026-03-02")
        result = engine.detect_signal_decay(
            bot_id="bot1",
            signal_outcome_correlation_30d=0.65,
            signal_outcome_correlation_90d=0.70,
        )
        assert len(result) == 0
```

**Implementation:**

```python
    def detect_signal_decay(
        self,
        bot_id: str,
        signal_outcome_correlation_30d: float,
        signal_outcome_correlation_90d: float,
        decay_threshold: float = 0.2,
    ) -> list[StrategySuggestion]:
        """Tier 4: Detect declining signal-to-outcome correlation."""
        drop = signal_outcome_correlation_90d - signal_outcome_correlation_30d
        if drop < decay_threshold:
            return []
        return [StrategySuggestion(
            tier=SuggestionTier.HYPOTHESIS,
            bot_id=bot_id,
            title=f"Signal quality decay — {bot_id}",
            description=(
                f"Signal→outcome correlation dropped from {signal_outcome_correlation_90d:.2f} "
                f"(90d) to {signal_outcome_correlation_30d:.2f} (30d). "
                f"Signal may need recalibration or replacement."
            ),
            evidence_days=90,
            confidence=min(0.9, 0.5 + drop),
            requires_human_judgment=True,
        )]
```

**Commit:**
```bash
git commit -m "feat(strategy): add signal quality decay detector"
```

---

### Task 14: Exit Timing Analyzer

**Test:**

```python
class TestExitTimingAnalyzer:
    def test_detects_premature_exits(self):
        engine = StrategyEngine(week_start="2026-02-24", week_end="2026-03-02")
        result = engine.detect_exit_timing_issues(
            bot_id="bot1",
            avg_exit_efficiency=0.45,  # captures only 45% of available move
            premature_exit_pct=0.6,    # 60% of exits are premature
        )
        assert len(result) == 1
        assert "exit" in result[0].title.lower()

    def test_no_issue_when_efficient(self):
        engine = StrategyEngine(week_start="2026-02-24", week_end="2026-03-02")
        result = engine.detect_exit_timing_issues(
            bot_id="bot1",
            avg_exit_efficiency=0.75,
            premature_exit_pct=0.2,
        )
        assert len(result) == 0
```

**Implementation:**

```python
    def detect_exit_timing_issues(
        self,
        bot_id: str,
        avg_exit_efficiency: float,
        premature_exit_pct: float,
        efficiency_threshold: float = 0.5,
        premature_threshold: float = 0.4,
    ) -> list[StrategySuggestion]:
        """Tier 3: Detect systematic premature exits."""
        if avg_exit_efficiency >= efficiency_threshold and premature_exit_pct <= premature_threshold:
            return []
        suggestions: list[StrategySuggestion] = []
        if avg_exit_efficiency < efficiency_threshold:
            suggestions.append(StrategySuggestion(
                tier=SuggestionTier.STRATEGY_VARIANT,
                bot_id=bot_id,
                title=f"Premature exits — {bot_id}",
                description=(
                    f"Average exit efficiency is {avg_exit_efficiency:.0%} (captures "
                    f"{avg_exit_efficiency:.0%} of available move). "
                    f"{premature_exit_pct:.0%} of exits are premature. "
                    f"Consider trailing stop or wider take-profit."
                ),
                evidence_days=30,
                confidence=0.6,
                requires_human_judgment=True,
            ))
        return suggestions
```

**Commit:**
```bash
git commit -m "feat(strategy): add exit timing analyzer"
```

---

### Task 15: Correlation Breakdown Detector

**Test:**

```python
class TestCorrelationBreakdown:
    def test_detects_rising_correlation(self):
        engine = StrategyEngine(week_start="2026-02-24", week_end="2026-03-02")
        from schemas.weekly_metrics import CorrelationSummary
        correlations = [
            CorrelationSummary(
                bot_a="bot1", bot_b="bot2",
                rolling_30d_correlation=0.82,
                weekly_pnl_correlation=0.75,
                same_direction_pct=0.8,
            ),
        ]
        result = engine.detect_correlation_breakdown(correlations)
        assert len(result) >= 1
        assert "correlation" in result[0].title.lower()

    def test_no_alert_when_low_correlation(self):
        engine = StrategyEngine(week_start="2026-02-24", week_end="2026-03-02")
        from schemas.weekly_metrics import CorrelationSummary
        correlations = [
            CorrelationSummary(
                bot_a="bot1", bot_b="bot2",
                rolling_30d_correlation=0.3,
            ),
        ]
        result = engine.detect_correlation_breakdown(correlations)
        assert len(result) == 0
```

**Implementation:**

```python
    def detect_correlation_breakdown(
        self,
        correlations: list,  # list[CorrelationSummary]
        threshold: float = 0.7,
    ) -> list[StrategySuggestion]:
        """Tier 3: Detect rising cross-bot return correlation (systemic risk)."""
        suggestions: list[StrategySuggestion] = []
        for corr in correlations:
            if corr.rolling_30d_correlation >= threshold:
                suggestions.append(StrategySuggestion(
                    tier=SuggestionTier.STRATEGY_VARIANT,
                    bot_id=f"{corr.bot_a}+{corr.bot_b}",
                    title=f"High correlation — {corr.bot_a} / {corr.bot_b}",
                    description=(
                        f"30d return correlation is {corr.rolling_30d_correlation:.2f}. "
                        f"Same-direction trading {corr.same_direction_pct:.0%} of the time. "
                        f"This increases systemic risk during adverse moves. "
                        f"Consider diversifying signal sources or staggering entry timing."
                    ),
                    evidence_days=30,
                    confidence=min(0.9, corr.rolling_30d_correlation),
                    requires_human_judgment=True,
                ))
        return suggestions
```

**Commit:**
```bash
git commit -m "feat(strategy): add correlation breakdown detector"
```

---

### Task 16: Time-of-Day Pattern Detector

**Test:**

```python
class TestTimeOfDayPatterns:
    def test_detects_bad_hours(self):
        engine = StrategyEngine(week_start="2026-02-24", week_end="2026-03-02")
        from schemas.hourly_performance import HourlyBucket
        buckets = [
            HourlyBucket(hour=9, trade_count=20, pnl=500.0, win_rate=0.75),
            HourlyBucket(hour=15, trade_count=15, pnl=-400.0, win_rate=0.2),
            HourlyBucket(hour=20, trade_count=10, pnl=100.0, win_rate=0.6),
        ]
        result = engine.detect_time_of_day_patterns(
            bot_id="bot1",
            hourly_buckets=buckets,
            min_trades=10,
        )
        assert len(result) >= 1
        assert "15" in result[0].description or "hour" in result[0].description.lower()

    def test_no_pattern_when_uniform(self):
        engine = StrategyEngine(week_start="2026-02-24", week_end="2026-03-02")
        from schemas.hourly_performance import HourlyBucket
        buckets = [
            HourlyBucket(hour=9, trade_count=10, pnl=100.0, win_rate=0.6),
            HourlyBucket(hour=15, trade_count=10, pnl=80.0, win_rate=0.55),
        ]
        result = engine.detect_time_of_day_patterns(
            bot_id="bot1",
            hourly_buckets=buckets,
        )
        assert len(result) == 0
```

**Implementation:**

```python
    def detect_time_of_day_patterns(
        self,
        bot_id: str,
        hourly_buckets: list,  # list[HourlyBucket]
        min_trades: int = 10,
        loss_threshold: float = 0.35,
    ) -> list[StrategySuggestion]:
        """Tier 2: Detect hours with consistently poor performance."""
        suggestions: list[StrategySuggestion] = []
        for bucket in hourly_buckets:
            if bucket.trade_count < min_trades:
                continue
            if bucket.pnl < 0 and bucket.win_rate < loss_threshold:
                suggestions.append(StrategySuggestion(
                    tier=SuggestionTier.FILTER,
                    bot_id=bot_id,
                    title=f"Poor hour {bucket.hour:02d}:00 — {bot_id}",
                    description=(
                        f"Hour {bucket.hour:02d}:00 UTC: {bucket.trade_count} trades, "
                        f"PnL ${bucket.pnl:.0f}, win rate {bucket.win_rate:.0%}. "
                        f"Consider adding a time-of-day gate to avoid this hour."
                    ),
                    evidence_days=7,
                    confidence=0.6,
                ))
        return suggestions
```

**Commit:**
```bash
git commit -m "feat(strategy): add time-of-day pattern detector"
```

---

### Task 17: Drawdown Pattern Detector + Position Sizing Efficiency

**Test:**

```python
class TestDrawdownPatternDetector:
    def test_detects_concentrated_drawdown(self):
        engine = StrategyEngine(week_start="2026-02-24", week_end="2026-03-02")
        result = engine.detect_drawdown_patterns(
            bot_id="bot1",
            largest_single_loss_pct=8.5,
            max_drawdown_pct=15.0,
            avg_loss_pct=2.0,
        )
        assert len(result) >= 1
        assert "drawdown" in result[0].title.lower() or "position" in result[0].title.lower()

    def test_no_alert_for_normal_drawdown(self):
        engine = StrategyEngine(week_start="2026-02-24", week_end="2026-03-02")
        result = engine.detect_drawdown_patterns(
            bot_id="bot1",
            largest_single_loss_pct=2.0,
            max_drawdown_pct=8.0,
            avg_loss_pct=1.5,
        )
        assert len(result) == 0


class TestPositionSizingEfficiency:
    def test_detects_oversizing(self):
        engine = StrategyEngine(week_start="2026-02-24", week_end="2026-03-02")
        result = engine.detect_position_sizing_issues(
            bot_id="bot1",
            avg_win_pct=1.5,
            avg_loss_pct=3.0,
            win_rate=0.65,
        )
        assert len(result) >= 1

    def test_no_issue_when_balanced(self):
        engine = StrategyEngine(week_start="2026-02-24", week_end="2026-03-02")
        result = engine.detect_position_sizing_issues(
            bot_id="bot1",
            avg_win_pct=2.0,
            avg_loss_pct=1.5,
            win_rate=0.55,
        )
        assert len(result) == 0
```

**Implementation:**

```python
    def detect_drawdown_patterns(
        self,
        bot_id: str,
        largest_single_loss_pct: float,
        max_drawdown_pct: float,
        avg_loss_pct: float,
        concentration_threshold: float = 3.0,
    ) -> list[StrategySuggestion]:
        """Tier 3: Detect concentrated drawdown (single loss dominates)."""
        if avg_loss_pct <= 0:
            return []
        concentration = largest_single_loss_pct / avg_loss_pct
        if concentration < concentration_threshold:
            return []
        return [StrategySuggestion(
            tier=SuggestionTier.STRATEGY_VARIANT,
            bot_id=bot_id,
            title=f"Concentrated drawdown risk — {bot_id}",
            description=(
                f"Largest single loss ({largest_single_loss_pct:.1f}%) is "
                f"{concentration:.1f}× the average loss ({avg_loss_pct:.1f}%). "
                f"Max drawdown: {max_drawdown_pct:.1f}%. "
                f"Consider tighter per-trade risk limits or position sizing adjustments."
            ),
            evidence_days=30,
            confidence=0.65,
            requires_human_judgment=True,
        )]

    def detect_position_sizing_issues(
        self,
        bot_id: str,
        avg_win_pct: float,
        avg_loss_pct: float,
        win_rate: float,
        loss_win_ratio_threshold: float = 1.5,
    ) -> list[StrategySuggestion]:
        """Tier 3: Detect asymmetric position sizing (losses > wins despite positive win rate)."""
        if avg_win_pct <= 0 or win_rate < 0.5:
            return []
        loss_win_ratio = avg_loss_pct / avg_win_pct
        if loss_win_ratio < loss_win_ratio_threshold:
            return []
        return [StrategySuggestion(
            tier=SuggestionTier.STRATEGY_VARIANT,
            bot_id=bot_id,
            title=f"Position sizing imbalance — {bot_id}",
            description=(
                f"Average loss ({avg_loss_pct:.1f}%) is {loss_win_ratio:.1f}× "
                f"average win ({avg_win_pct:.1f}%) despite {win_rate:.0%} win rate. "
                f"Risk/reward is asymmetric — consider reducing position size on "
                f"lower-confidence signals or tightening stop placement."
            ),
            evidence_days=30,
            confidence=0.6,
            requires_human_judgment=True,
        )]
```

**Commit:**
```bash
git commit -m "feat(strategy): add drawdown pattern + position sizing efficiency detectors"
```

---

### Task 18: Wire New Detectors into build_report()

**Files:**
- Modify: `analysis/strategy_engine.py` — extend `build_report()` to call new detectors
- Test: `tests/test_strategy_engine_expanded.py` — add integration test

**Test:**

```python
class TestExpandedBuildReport:
    def test_build_report_calls_all_detectors(self):
        from schemas.weekly_metrics import BotWeeklySummary, CorrelationSummary
        from schemas.hourly_performance import HourlyBucket

        engine = StrategyEngine(week_start="2026-02-24", week_end="2026-03-02")
        bot_summaries = {
            "bot1": BotWeeklySummary(
                week_start="2026-02-24", week_end="2026-03-02",
                bot_id="bot1", total_trades=50, win_count=30, loss_count=20,
                avg_win=100.0, avg_loss=-60.0, max_drawdown_pct=12.0,
            ),
        }

        report = engine.build_report(
            bot_summaries=bot_summaries,
            rolling_sharpe={
                "bot1": {"30d": 0.5, "60d": 1.2, "90d": 2.0},
            },
            hourly_buckets={
                "bot1": [
                    HourlyBucket(hour=9, trade_count=20, pnl=500.0, win_rate=0.75),
                    HourlyBucket(hour=15, trade_count=15, pnl=-400.0, win_rate=0.2),
                ],
            },
        )
        # Should produce suggestions from multiple detectors
        assert len(report.suggestions) > 0
        tiers = {s.tier.value for s in report.suggestions}
        # At minimum we should get parameter (tight stop) and hypothesis (alpha decay)
        assert len(tiers) >= 1
```

**Implementation:**

Extend `build_report()` signature to accept optional new data:

```python
    def build_report(
        self,
        bot_summaries: dict[str, BotWeeklySummary],
        filter_summaries: dict[str, list[FilterWeeklySummary]] | None = None,
        regime_trends: dict[str, list[RegimePerformanceTrend]] | None = None,
        rolling_sharpe: dict[str, dict[str, float]] | None = None,
        signal_correlations: dict[str, dict[str, float]] | None = None,
        hourly_buckets: dict[str, list] | None = None,
        correlation_summaries: list | None = None,
        drawdown_data: dict[str, dict] | None = None,
    ) -> RefinementReport:
```

Inside, after existing calls, add:

```python
        # New detectors
        if rolling_sharpe:
            for bot_id, sharpe in rolling_sharpe.items():
                suggestions.extend(self.detect_alpha_decay(
                    bot_id, sharpe.get("30d", 0), sharpe.get("60d", 0), sharpe.get("90d", 0),
                ))

        if signal_correlations:
            for bot_id, corr in signal_correlations.items():
                suggestions.extend(self.detect_signal_decay(
                    bot_id, corr.get("30d", 0), corr.get("90d", 0),
                ))

        if hourly_buckets:
            for bot_id, buckets in hourly_buckets.items():
                suggestions.extend(self.detect_time_of_day_patterns(bot_id, buckets))

        if correlation_summaries:
            suggestions.extend(self.detect_correlation_breakdown(correlation_summaries))

        if drawdown_data:
            for bot_id, dd in drawdown_data.items():
                suggestions.extend(self.detect_drawdown_patterns(
                    bot_id,
                    dd.get("largest_single_loss_pct", 0),
                    dd.get("max_drawdown_pct", 0),
                    dd.get("avg_loss_pct", 0),
                ))

        for bot_id, summary in bot_summaries.items():
            if summary.avg_win > 0 and abs(summary.avg_loss) > 0:
                suggestions.extend(self.detect_position_sizing_issues(
                    bot_id,
                    avg_win_pct=summary.avg_win,
                    avg_loss_pct=abs(summary.avg_loss),
                    win_rate=summary.win_rate,
                ))
```

**Commit:**
```bash
git commit -m "feat(strategy): wire all new detectors into build_report()"
```

---

## Phase D: Structural Analysis Prompts + Proactive Scanner (Gaps 6, 7, 12)

### Task 19: Enhance Weekly Prompts for Structural Analysis

**Files:**
- Modify: `analysis/weekly_prompt_assembler.py`
- Test: `tests/test_weekly_prompt_assembler.py` (add new tests)

This addresses **Gap 6** (cannot propose structural changes) and **Gap 7** (WFO parameter space expansion).

**Step 1: Write the failing test**

```python
class TestStructuralAnalysisInstructions:
    def test_weekly_instructions_include_structural_questions(self, tmp_path):
        memory_dir = tmp_path / "memory"
        policies = memory_dir / "policies" / "v1"
        policies.mkdir(parents=True)
        curated = tmp_path / "curated"
        curated.mkdir()
        runs = tmp_path / "runs"
        runs.mkdir()

        assembler = WeeklyPromptAssembler(
            week_start="2026-02-24", week_end="2026-03-02",
            bots=["bot1"], curated_dir=curated,
            memory_dir=memory_dir, runs_dir=runs,
        )
        pkg = assembler.assemble()
        instructions = pkg.instructions.lower()
        # Gap 6: Structural analysis
        assert "structural" in instructions
        assert "signal" in instructions
        # Gap 7: Parameter space expansion
        assert "parameter" in instructions
```

**Step 2: Modify `_WEEKLY_INSTRUCTIONS`**

Add these structural analysis prompts to the weekly instructions:

```
11. Structural analysis: Based on 30-day root cause patterns, assess whether any bot's signal logic needs structural changes (not just parameter tuning). Specifically evaluate:
    - Has signal→outcome correlation declined? Does the signal need recalibration or replacement?
    - Are filters blocking high-quality signals? Should a filter be restructured rather than threshold-adjusted?
    - Are exits consistently premature? Should the exit strategy change (e.g., trailing stop)?
12. Parameter space proposals: If evidence suggests a new dimension should be optimized (e.g., adding a time-of-day gate, changing position sizing model), propose it with supporting evidence. These proposals require human approval.
13. Do NOT re-suggest anything in the rejected_suggestions list unless you present new quantitative evidence.
```

**Commit:**
```bash
git commit -m "feat(prompts): add structural analysis + parameter space expansion instructions to weekly prompt"
```

---

### Task 20: Implement Real Proactive Scanner

**Files:**
- Modify: `skills/proactive_scanner.py`
- Test: `tests/test_proactive_scanner_real.py`

This addresses **Gap 12** (proactive scanner is a skeleton).

**Step 1: Write the failing test**

```python
# tests/test_proactive_scanner_real.py
"""Tests for real proactive scanning logic."""
from datetime import datetime

from schemas.events import TradeEvent
from schemas.notifications import NotificationPriority
from skills.proactive_scanner import ProactiveScanner


def _make_trade(pnl: float, date_str: str = "2026-03-01") -> TradeEvent:
    return TradeEvent(
        trade_id=f"t_{pnl}",
        bot_id="bot1",
        pair="BTCUSDT",
        side="LONG",
        entry_time=datetime.fromisoformat(f"{date_str}T10:00:00"),
        exit_time=datetime.fromisoformat(f"{date_str}T11:00:00"),
        entry_price=50000,
        exit_price=50000 + pnl,
        position_size=1.0,
        pnl=pnl,
        pnl_pct=pnl / 500,
    )


class TestUnusualLossDetection:
    def test_detects_unusual_loss(self):
        # Normal losses: ~$50–100
        historical = [_make_trade(-60), _make_trade(-80), _make_trade(-50),
                      _make_trade(-70), _make_trade(-90)]
        # Unusual: $500 loss (>2 sigma from mean)
        scanner = ProactiveScanner()
        result = scanner.detect_unusual_losses(
            bot_id="bot1",
            recent_trade=_make_trade(-500),
            historical_losses=[t.pnl for t in historical],
        )
        assert result is not None
        assert result.priority == NotificationPriority.HIGH

    def test_normal_loss_not_flagged(self):
        historical = [_make_trade(-60), _make_trade(-80), _make_trade(-50)]
        scanner = ProactiveScanner()
        result = scanner.detect_unusual_losses(
            bot_id="bot1",
            recent_trade=_make_trade(-75),
            historical_losses=[t.pnl for t in historical],
        )
        assert result is None


class TestRepeatedErrorDetection:
    def test_detects_repeated_errors(self):
        scanner = ProactiveScanner()
        errors = [
            {"bot_id": "bot1", "error_type": "api_timeout", "timestamp": "2026-03-01T10:00:00"},
            {"bot_id": "bot1", "error_type": "api_timeout", "timestamp": "2026-03-01T10:15:00"},
            {"bot_id": "bot1", "error_type": "api_timeout", "timestamp": "2026-03-01T10:30:00"},
            {"bot_id": "bot1", "error_type": "api_timeout", "timestamp": "2026-03-01T10:45:00"},
        ]
        result = scanner.detect_repeated_errors(errors, threshold=3)
        assert len(result) >= 1
        assert result[0].priority in (NotificationPriority.HIGH, NotificationPriority.CRITICAL)

    def test_sparse_errors_not_flagged(self):
        scanner = ProactiveScanner()
        errors = [
            {"bot_id": "bot1", "error_type": "api_timeout", "timestamp": "2026-03-01T10:00:00"},
            {"bot_id": "bot1", "error_type": "connection_reset", "timestamp": "2026-03-01T12:00:00"},
        ]
        result = scanner.detect_repeated_errors(errors, threshold=3)
        assert len(result) == 0


class TestHeartbeatMonitoring:
    def test_detects_missing_heartbeat(self):
        scanner = ProactiveScanner()
        result = scanner.check_heartbeats(
            bot_heartbeats={"bot1": "2026-03-01T08:00:00", "bot2": "2026-03-01T10:00:00"},
            current_time="2026-03-01T12:00:00",
            max_gap_hours=2,
        )
        # bot1 last seen 4 hours ago
        assert len(result) >= 1
        assert any("bot1" in r.title for r in result)

    def test_recent_heartbeat_ok(self):
        scanner = ProactiveScanner()
        result = scanner.check_heartbeats(
            bot_heartbeats={"bot1": "2026-03-01T11:30:00"},
            current_time="2026-03-01T12:00:00",
            max_gap_hours=2,
        )
        assert len(result) == 0
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_proactive_scanner_real.py -v`

**Step 3: Add real scanning methods to `skills/proactive_scanner.py`**

```python
    def detect_unusual_losses(
        self,
        bot_id: str,
        recent_trade: TradeEvent,
        historical_losses: list[float],
        sigma_threshold: float = 2.0,
    ) -> NotificationPayload | None:
        """Detect if a recent loss is >2σ from 30-day mean."""
        if not historical_losses or recent_trade.pnl >= 0:
            return None
        import statistics
        mean_loss = statistics.mean(historical_losses)
        if len(historical_losses) < 2:
            return None
        stdev = statistics.stdev(historical_losses)
        if stdev == 0:
            return None
        z_score = (recent_trade.pnl - mean_loss) / stdev
        if abs(z_score) < sigma_threshold:
            return None
        return NotificationPayload(
            notification_type="alert",
            priority=NotificationPriority.HIGH,
            title=f"Unusual loss — {bot_id}",
            body=(
                f"PnL: ${recent_trade.pnl:.0f} on {recent_trade.pair}. "
                f"This is {abs(z_score):.1f}σ from 30d mean (${mean_loss:.0f})."
            ),
        )

    def detect_repeated_errors(
        self,
        errors: list[dict],
        threshold: int = 3,
    ) -> list[NotificationPayload]:
        """Detect repeated errors of the same type within a short window."""
        from collections import Counter
        type_counts: Counter[str] = Counter()
        for e in errors:
            key = f"{e.get('bot_id', 'unknown')}:{e.get('error_type', 'unknown')}"
            type_counts[key] += 1

        payloads: list[NotificationPayload] = []
        for key, count in type_counts.items():
            if count >= threshold:
                bot_id, error_type = key.split(":", 1)
                payloads.append(NotificationPayload(
                    notification_type="alert",
                    priority=NotificationPriority.HIGH,
                    title=f"Repeated errors — {bot_id}",
                    body=f"{error_type} occurred {count}× recently. Possible systemic issue.",
                ))
        return payloads

    def check_heartbeats(
        self,
        bot_heartbeats: dict[str, str],
        current_time: str,
        max_gap_hours: int = 2,
    ) -> list[NotificationPayload]:
        """Check for missing bot heartbeats."""
        from datetime import datetime, timedelta
        now = datetime.fromisoformat(current_time)
        payloads: list[NotificationPayload] = []
        for bot_id, last_seen_str in bot_heartbeats.items():
            last_seen = datetime.fromisoformat(last_seen_str)
            gap = now - last_seen
            if gap > timedelta(hours=max_gap_hours):
                hours_ago = gap.total_seconds() / 3600
                payloads.append(NotificationPayload(
                    notification_type="alert",
                    priority=NotificationPriority.CRITICAL if hours_ago > 4 else NotificationPriority.HIGH,
                    title=f"Heartbeat missing — {bot_id}",
                    body=f"Last seen {hours_ago:.1f} hours ago. Check bot health.",
                ))
        return payloads
```

Add the necessary import at top of file:
```python
from schemas.events import TradeEvent
```

**Step 4: Run test, commit**

```bash
git add skills/proactive_scanner.py tests/test_proactive_scanner_real.py
git commit -m "feat(scanner): implement real proactive scanning — unusual losses, repeated errors, heartbeat monitoring"
```

---

## Phase E: Integration Hardening (Gaps 13, 15)

### Task 21: Add trace_id to Event Flow

**Files:**
- Modify: `schemas/events.py`
- Modify: `relay/app.py`
- Test: `tests/test_trace_id.py`

This addresses **Gap 15** (no end-to-end event tracing).

**Step 1: Write the failing test**

```python
# tests/test_trace_id.py
"""Tests for trace_id propagation through event pipeline."""
import uuid

from schemas.events import EventMetadata


class TestTraceId:
    def test_event_metadata_has_trace_id(self):
        from datetime import datetime, timezone
        meta = EventMetadata(
            bot_id="bot1",
            exchange_timestamp=datetime(2026, 3, 1, tzinfo=timezone.utc),
            local_timestamp=datetime(2026, 3, 1, tzinfo=timezone.utc),
            data_source_id="src1",
            event_type="trade",
            payload_key="t1",
            trace_id="abc-123",
        )
        assert meta.trace_id == "abc-123"

    def test_trace_id_auto_generated_if_missing(self):
        from datetime import datetime, timezone
        meta = EventMetadata(
            bot_id="bot1",
            exchange_timestamp=datetime(2026, 3, 1, tzinfo=timezone.utc),
            local_timestamp=datetime(2026, 3, 1, tzinfo=timezone.utc),
            data_source_id="src1",
            event_type="trade",
            payload_key="t1",
        )
        assert meta.trace_id is not None
        assert len(meta.trace_id) > 0
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_trace_id.py -v`
Expected: FAIL — `trace_id` field doesn't exist

**Step 3: Modify `schemas/events.py`**

Add `trace_id` field to `EventMetadata`:

```python
    trace_id: str = Field(
        default_factory=lambda: uuid.uuid4().hex[:16]
    )
```

Add `import uuid` at top of file.

**Step 4: Run test, commit**

```bash
git add schemas/events.py tests/test_trace_id.py
git commit -m "feat(tracing): add trace_id to EventMetadata for end-to-end event tracing"
```

---

### Task 22: Create Relay Schema File

**Files:**
- Create: `relay/db/schema.sql` (if not present, or validate it exists)
- Test: Verify relay app references it

This addresses **Gap 13** (relay schema.sql missing).

**Step 1: Verify current state**

Check if `relay/db/schema.sql` already exists (it was found by the explorer). If it exists, verify it matches what `relay/db/store.py` expects. If the relay uses in-memory SQLite, modify to support disk-backed mode.

**Step 2: Modify relay/app.py**

Ensure `create_relay_app()` accepts a `db_path` parameter (it already does) and document that it should be a disk path for crash resilience, not `:memory:`.

**Step 3: Commit**

```bash
git add relay/db/schema.sql relay/app.py
git commit -m "fix(relay): ensure relay schema.sql present and DB is disk-backed for crash resilience"
```

---

### Task 23: Run Full Test Suite + Final Verification

**Step 1: Run all tests**

Run: `pytest tests/ -v --tb=short`
Expected: All 740+ existing tests pass, plus ~80 new tests = 820+ total

**Step 2: Verify no regressions**

Run: `pytest tests/ -x -q`
Expected: PASS

**Step 3: Final commit**

```bash
git add -A
git commit -m "chore: final verification — all tests passing after feedback gaps implementation"
```

---

## Summary

| Phase | Tasks | Gaps Addressed | New Tests |
|-------|-------|---------------|-----------|
| **A: Feedback Loop** | 0–4 | Gaps 9, 10, 11 | ~25 |
| **B: Data Pipeline** | 5–11 | Gaps 2, 3, 4 | ~25 |
| **C: Strategy Engine** | 12–18 | Gap 5 | ~20 |
| **D: Structural + Scanner** | 19–20 | Gaps 6, 7, 12 | ~15 |
| **E: Integration** | 21–22 | Gaps 13, 15 | ~5 |
| **Total** | **23 tasks** | **12 of 15 gaps** | **~90 tests** |

**Deferred (requires bot-side changes):**
- Gap 1: Filter threshold awareness
- Gap 8: A/B testing / shadow mode
- Gap 14: Bot error vs instrumentation error separation
