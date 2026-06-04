# Phase 5: Bug Triage + PR Automation — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a deterministic bug triage pipeline with severity-based routing, a PR review pipeline with trading-specific safety checks, and a Ralph Loop V2 failure log — so that error events from VPS bots are automatically classified, routed to the right handler (alert / auto-fix / investigate / escalate), and any automated PRs go through a multi-stage review gate before reaching a human.

**Architecture:** Error events arrive via the existing relay→queue→brain→worker pipeline. A deterministic severity classifier (no LLM) routes errors into four buckets: CRITICAL (immediate alert), HIGH (spawn triage agent), MEDIUM (queue for daily), LOW (batch for weekly). An error rate tracker detects repeated errors (>3/hour threshold) and auto-promotes severity. For HIGH errors, a bug complexity classifier decides the outcome: KNOWN_FIX (spawn fix agent → draft PR), NEEDS_INVESTIGATION (create GitHub issue), or NEEDS_HUMAN (Telegram alert). A triage context builder assembles stack traces, source files, and recent git log for the triage agent. A PR review pipeline checks every automated PR through permission gates, trading-specific safety assertions, and CI status before notifying the human. A failure log (`.assistant/failure-log.jsonl`) records PR rejections and past triage outcomes, feeding into future triage prompts (Ralph Loop V2).

**Tech Stack:** Python 3.12, Pydantic v2, pytest, aiosqlite (for error rate tracking), pathlib, json, re, datetime (stdlib)

**Assumes:** Phases 1–4 are fully implemented — event queue, task registry, orchestrator brain/worker/scheduler, permission gates, daily/weekly metrics, prompt assembler, feedback handler, monitoring, and all schemas exist and pass tests. The brain already has `SPAWN_TRIAGE` action type and the worker already has an `on_triage` pluggable callback — both need real implementation.

**Directory structure this plan creates:**

```
trading_assistant/
  schemas/
    bug_triage.py             # BugSeverity, BugComplexity, TriageOutcome, ErrorEvent, TriageResult
    pr_review.py              # PRReviewStep, PRReviewResult, TradingSafetyCheck
  skills/
    severity_classifier.py    # SeverityClassifier — deterministic error severity routing
    error_rate_tracker.py     # ErrorRateTracker — sliding window frequency detection
    bug_complexity_classifier.py  # BugComplexityClassifier — auto-fix vs investigate vs human
    failure_log.py            # FailureLog — read/write .assistant/failure-log.jsonl
    triage_context_builder.py # TriageContextBuilder — stack trace + source + git log assembly
    pr_review_checker.py      # PRReviewChecker — trading-specific safety assertions
    run_bug_triage.py         # TriageRunner — main pipeline orchestrating everything
  analysis/
    triage_prompt_assembler.py  # TriagePromptAssembler — packages triage context for Claude
    pr_report_builder.py        # PRReportBuilder — markdown summary of PR review results
  orchestrator/
    orchestrator_brain.py     # MODIFY: enhance _handle_error with severity routing
    worker.py                 # MODIFY: wire up on_triage with real TriageRunner
    scheduler.py              # MODIFY: add stale_error_sweep config
  tests/
    test_bug_triage_schemas.py
    test_pr_review_schemas.py
    test_severity_classifier.py
    test_error_rate_tracker.py
    test_bug_complexity_classifier.py
    test_failure_log.py
    test_triage_context_builder.py
    test_pr_review_checker.py
    test_triage_prompt_assembler.py
    test_pr_report_builder.py
    test_triage_runner.py
    test_bug_triage_integration.py
```

---

## Task 0: Bug Triage Schemas

**Files:**
- Create: `schemas/bug_triage.py`
- Test: `tests/test_bug_triage_schemas.py`

**Step 1: Write the failing test**

```python
# tests/test_bug_triage_schemas.py
"""Tests for bug triage schemas."""
from datetime import datetime, timezone

from schemas.bug_triage import (
    BugSeverity,
    BugComplexity,
    TriageOutcome,
    ErrorEvent,
    TriageResult,
    ErrorCategory,
)


class TestBugSeverity:
    def test_all_levels_exist(self):
        assert BugSeverity.CRITICAL == "critical"
        assert BugSeverity.HIGH == "high"
        assert BugSeverity.MEDIUM == "medium"
        assert BugSeverity.LOW == "low"

    def test_ordering(self):
        """CRITICAL is highest severity."""
        ordered = sorted(BugSeverity, key=lambda s: s.rank, reverse=True)
        assert ordered[0] == BugSeverity.CRITICAL
        assert ordered[-1] == BugSeverity.LOW


class TestBugComplexity:
    def test_all_levels_exist(self):
        assert BugComplexity.OBVIOUS_FIX == "obvious_fix"
        assert BugComplexity.SINGLE_FUNCTION == "single_function"
        assert BugComplexity.MULTI_FILE == "multi_file"
        assert BugComplexity.STATE_DEPENDENT == "state_dependent"
        assert BugComplexity.UNKNOWN == "unknown"


class TestTriageOutcome:
    def test_all_outcomes_exist(self):
        assert TriageOutcome.KNOWN_FIX == "known_fix"
        assert TriageOutcome.NEEDS_INVESTIGATION == "needs_investigation"
        assert TriageOutcome.NEEDS_HUMAN == "needs_human"
        assert TriageOutcome.QUEUED_FOR_DAILY == "queued_for_daily"
        assert TriageOutcome.QUEUED_FOR_WEEKLY == "queued_for_weekly"
        assert TriageOutcome.ALERTED == "alerted"


class TestErrorCategory:
    def test_all_categories_exist(self):
        assert ErrorCategory.CRASH == "crash"
        assert ErrorCategory.STUCK_POSITION == "stuck_position"
        assert ErrorCategory.CONNECTION_LOST == "connection_lost"
        assert ErrorCategory.UNEXPECTED_LOSS == "unexpected_loss"
        assert ErrorCategory.REPEATED_ERROR == "repeated_error"
        assert ErrorCategory.API_ERROR == "api_error"
        assert ErrorCategory.CONFIG_ERROR == "config_error"
        assert ErrorCategory.DEPENDENCY == "dependency"
        assert ErrorCategory.WARNING == "warning"
        assert ErrorCategory.DEPRECATION == "deprecation"
        assert ErrorCategory.UNKNOWN == "unknown"


class TestErrorEvent:
    def test_creates_with_required_fields(self):
        e = ErrorEvent(
            bot_id="bot1",
            error_type="RuntimeError",
            message="division by zero",
            stack_trace="Traceback...\n  File main.py:10\nRuntimeError: division by zero",
        )
        assert e.bot_id == "bot1"
        assert e.error_type == "RuntimeError"
        assert e.message == "division by zero"
        assert e.severity is None  # not yet classified
        assert e.category is None
        assert e.source_file == ""
        assert e.source_line == 0

    def test_creates_with_all_fields(self):
        e = ErrorEvent(
            bot_id="bot2",
            error_type="ConnectionError",
            message="cannot reach exchange",
            stack_trace="...",
            source_file="connectors/binance.py",
            source_line=42,
            severity=BugSeverity.CRITICAL,
            category=ErrorCategory.CONNECTION_LOST,
            context={"exchange": "binance", "retry_count": 3},
        )
        assert e.source_file == "connectors/binance.py"
        assert e.source_line == 42
        assert e.severity == BugSeverity.CRITICAL
        assert e.context["retry_count"] == 3

    def test_timestamp_defaults_to_now(self):
        e = ErrorEvent(bot_id="b", error_type="E", message="m", stack_trace="s")
        assert e.timestamp is not None
        assert e.timestamp.tzinfo is not None


class TestTriageResult:
    def test_creates_minimal(self):
        r = TriageResult(
            error_event=ErrorEvent(
                bot_id="bot1",
                error_type="RuntimeError",
                message="fail",
                stack_trace="...",
            ),
            severity=BugSeverity.HIGH,
            complexity=BugComplexity.OBVIOUS_FIX,
            outcome=TriageOutcome.KNOWN_FIX,
        )
        assert r.severity == BugSeverity.HIGH
        assert r.outcome == TriageOutcome.KNOWN_FIX
        assert r.suggested_fix == ""
        assert r.github_issue_url == ""
        assert r.pr_url == ""
        assert r.past_rejections == []

    def test_creates_with_context(self):
        r = TriageResult(
            error_event=ErrorEvent(
                bot_id="bot1",
                error_type="ImportError",
                message="no module foo",
                stack_trace="...",
            ),
            severity=BugSeverity.HIGH,
            complexity=BugComplexity.OBVIOUS_FIX,
            outcome=TriageOutcome.KNOWN_FIX,
            suggested_fix="Add foo to requirements.txt",
            affected_files=["requirements.txt"],
            past_rejections=["Previously rejected: wrong version pinned"],
        )
        assert r.suggested_fix == "Add foo to requirements.txt"
        assert len(r.affected_files) == 1
        assert len(r.past_rejections) == 1
```

**Step 2: Implement the schemas**

```python
# schemas/bug_triage.py
"""Bug triage schemas — error events, severity, complexity, and triage outcomes.

Used by the deterministic severity classifier and bug complexity classifier
to route errors through the triage pipeline.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class BugSeverity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

    @property
    def rank(self) -> int:
        return {"critical": 4, "high": 3, "medium": 2, "low": 1}[self.value]


class BugComplexity(str, Enum):
    OBVIOUS_FIX = "obvious_fix"       # stack trace → obvious fix, dep bumps, config
    SINGLE_FUNCTION = "single_function"  # single-function logic errors
    MULTI_FILE = "multi_file"         # touches multiple files
    STATE_DEPENDENT = "state_dependent"  # timing, exchange edge cases
    UNKNOWN = "unknown"


class TriageOutcome(str, Enum):
    KNOWN_FIX = "known_fix"                   # auto-fix → draft PR
    NEEDS_INVESTIGATION = "needs_investigation"  # create GitHub issue
    NEEDS_HUMAN = "needs_human"               # Telegram alert with summary
    QUEUED_FOR_DAILY = "queued_for_daily"     # MEDIUM severity
    QUEUED_FOR_WEEKLY = "queued_for_weekly"   # LOW severity
    ALERTED = "alerted"                       # CRITICAL → immediate alert


class ErrorCategory(str, Enum):
    CRASH = "crash"
    STUCK_POSITION = "stuck_position"
    CONNECTION_LOST = "connection_lost"
    UNEXPECTED_LOSS = "unexpected_loss"
    REPEATED_ERROR = "repeated_error"
    API_ERROR = "api_error"
    CONFIG_ERROR = "config_error"
    DEPENDENCY = "dependency"
    WARNING = "warning"
    DEPRECATION = "deprecation"
    UNKNOWN = "unknown"


class ErrorEvent(BaseModel):
    """An error event received from a VPS bot sidecar."""

    bot_id: str
    error_type: str             # e.g. "RuntimeError", "ConnectionError"
    message: str                # error message text
    stack_trace: str            # full traceback
    source_file: str = ""       # file where error originated
    source_line: int = 0        # line number
    severity: Optional[BugSeverity] = None    # set by classifier
    category: Optional[ErrorCategory] = None  # set by classifier
    context: dict = {}          # arbitrary context from the bot
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class TriageResult(BaseModel):
    """The outcome of triaging an error event."""

    error_event: ErrorEvent
    severity: BugSeverity
    complexity: BugComplexity
    outcome: TriageOutcome
    suggested_fix: str = ""
    affected_files: list[str] = []
    github_issue_url: str = ""
    pr_url: str = ""
    past_rejections: list[str] = []
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
```

**Step 3: Run tests**

```bash
pytest tests/test_bug_triage_schemas.py -v
```

Expected: All tests PASS.

**Step 4: Commit**

```bash
git add schemas/bug_triage.py tests/test_bug_triage_schemas.py
git commit -m "feat(phase5): add bug triage schemas — severity, complexity, outcome, error event"
```

---

## Task 1: PR Review Schemas

**Files:**
- Create: `schemas/pr_review.py`
- Test: `tests/test_pr_review_schemas.py`

**Step 1: Write the failing test**

```python
# tests/test_pr_review_schemas.py
"""Tests for PR review schemas."""
from schemas.pr_review import (
    PRReviewStep,
    PRReviewStepResult,
    TradingSafetyCheck,
    TradingSafetyResult,
    PRReviewResult,
    PRReviewStatus,
)


class TestPRReviewStep:
    def test_all_steps_exist(self):
        assert PRReviewStep.CODE_REVIEW == "code_review"
        assert PRReviewStep.CI_CHECK == "ci_check"
        assert PRReviewStep.PERMISSION_GATE == "permission_gate"
        assert PRReviewStep.TRADING_SAFETY == "trading_safety"
        assert PRReviewStep.HUMAN_REVIEW == "human_review"


class TestPRReviewStatus:
    def test_all_statuses_exist(self):
        assert PRReviewStatus.PENDING == "pending"
        assert PRReviewStatus.PASSED == "passed"
        assert PRReviewStatus.FAILED == "failed"
        assert PRReviewStatus.BLOCKED == "blocked"


class TestPRReviewStepResult:
    def test_creates_passed(self):
        r = PRReviewStepResult(
            step=PRReviewStep.CI_CHECK,
            status=PRReviewStatus.PASSED,
            detail="All checks green",
        )
        assert r.step == PRReviewStep.CI_CHECK
        assert r.status == PRReviewStatus.PASSED
        assert r.detail == "All checks green"
        assert r.blocker_reason == ""

    def test_creates_failed_with_blocker(self):
        r = PRReviewStepResult(
            step=PRReviewStep.PERMISSION_GATE,
            status=PRReviewStatus.FAILED,
            detail="File touches risk_limits.py",
            blocker_reason="requires_double_approval for risk_limits.py",
        )
        assert r.blocker_reason != ""


class TestTradingSafetyCheck:
    def test_all_checks_exist(self):
        assert TradingSafetyCheck.POSITION_SIZING_UNCHANGED == "position_sizing_unchanged"
        assert TradingSafetyCheck.RISK_LIMITS_ENFORCED == "risk_limits_enforced"
        assert TradingSafetyCheck.KILL_SWITCH_WORKS == "kill_switch_works"


class TestTradingSafetyResult:
    def test_creates_with_defaults(self):
        r = TradingSafetyResult(
            check=TradingSafetyCheck.POSITION_SIZING_UNCHANGED,
            passed=True,
        )
        assert r.passed is True
        assert r.detail == ""
        assert r.is_intentional_change is False

    def test_intentional_change(self):
        r = TradingSafetyResult(
            check=TradingSafetyCheck.POSITION_SIZING_UNCHANGED,
            passed=False,
            detail="Position size formula changed",
            is_intentional_change=True,
        )
        assert r.is_intentional_change is True


class TestPRReviewResult:
    def test_creates_with_all_steps(self):
        steps = [
            PRReviewStepResult(
                step=PRReviewStep.CODE_REVIEW,
                status=PRReviewStatus.PASSED,
            ),
            PRReviewStepResult(
                step=PRReviewStep.CI_CHECK,
                status=PRReviewStatus.PASSED,
            ),
        ]
        safety = [
            TradingSafetyResult(
                check=TradingSafetyCheck.POSITION_SIZING_UNCHANGED,
                passed=True,
            ),
        ]
        r = PRReviewResult(
            pr_url="https://github.com/user/repo/pull/42",
            steps=steps,
            safety_checks=safety,
        )
        assert r.pr_url.endswith("/42")
        assert len(r.steps) == 2
        assert len(r.safety_checks) == 1

    def test_overall_passed(self):
        r = PRReviewResult(
            pr_url="https://github.com/user/repo/pull/1",
            steps=[
                PRReviewStepResult(step=PRReviewStep.CODE_REVIEW, status=PRReviewStatus.PASSED),
                PRReviewStepResult(step=PRReviewStep.CI_CHECK, status=PRReviewStatus.PASSED),
            ],
            safety_checks=[
                TradingSafetyResult(check=TradingSafetyCheck.KILL_SWITCH_WORKS, passed=True),
            ],
        )
        assert r.overall_passed is True

    def test_overall_failed_when_step_fails(self):
        r = PRReviewResult(
            pr_url="https://github.com/user/repo/pull/2",
            steps=[
                PRReviewStepResult(step=PRReviewStep.CODE_REVIEW, status=PRReviewStatus.PASSED),
                PRReviewStepResult(step=PRReviewStep.CI_CHECK, status=PRReviewStatus.FAILED),
            ],
            safety_checks=[],
        )
        assert r.overall_passed is False

    def test_overall_failed_when_safety_fails_and_not_intentional(self):
        r = PRReviewResult(
            pr_url="https://github.com/user/repo/pull/3",
            steps=[
                PRReviewStepResult(step=PRReviewStep.CODE_REVIEW, status=PRReviewStatus.PASSED),
            ],
            safety_checks=[
                TradingSafetyResult(
                    check=TradingSafetyCheck.RISK_LIMITS_ENFORCED,
                    passed=False,
                    is_intentional_change=False,
                ),
            ],
        )
        assert r.overall_passed is False

    def test_overall_passed_when_safety_fails_but_intentional(self):
        r = PRReviewResult(
            pr_url="https://github.com/user/repo/pull/4",
            steps=[
                PRReviewStepResult(step=PRReviewStep.CODE_REVIEW, status=PRReviewStatus.PASSED),
            ],
            safety_checks=[
                TradingSafetyResult(
                    check=TradingSafetyCheck.POSITION_SIZING_UNCHANGED,
                    passed=False,
                    is_intentional_change=True,
                ),
            ],
        )
        assert r.overall_passed is True
```

**Step 2: Implement the schemas**

```python
# schemas/pr_review.py
"""PR review schemas — multi-stage review pipeline data models.

Every automated PR goes through: code review → CI → permission gate →
trading-specific safety checks → human review. These schemas track each step.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field, computed_field


class PRReviewStep(str, Enum):
    CODE_REVIEW = "code_review"
    CI_CHECK = "ci_check"
    PERMISSION_GATE = "permission_gate"
    TRADING_SAFETY = "trading_safety"
    HUMAN_REVIEW = "human_review"


class PRReviewStatus(str, Enum):
    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"
    BLOCKED = "blocked"


class PRReviewStepResult(BaseModel):
    step: PRReviewStep
    status: PRReviewStatus = PRReviewStatus.PENDING
    detail: str = ""
    blocker_reason: str = ""
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class TradingSafetyCheck(str, Enum):
    POSITION_SIZING_UNCHANGED = "position_sizing_unchanged"
    RISK_LIMITS_ENFORCED = "risk_limits_enforced"
    KILL_SWITCH_WORKS = "kill_switch_works"


class TradingSafetyResult(BaseModel):
    check: TradingSafetyCheck
    passed: bool
    detail: str = ""
    is_intentional_change: bool = False


class PRReviewResult(BaseModel):
    """Aggregated result of a full PR review pipeline run."""

    pr_url: str
    steps: list[PRReviewStepResult] = []
    safety_checks: list[TradingSafetyResult] = []
    rejection_reason: str = ""
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @computed_field  # type: ignore[prop-decorator]
    @property
    def overall_passed(self) -> bool:
        steps_ok = all(s.status == PRReviewStatus.PASSED for s in self.steps)
        safety_ok = all(
            s.passed or s.is_intentional_change for s in self.safety_checks
        )
        return steps_ok and safety_ok
```

**Step 3: Run tests**

```bash
pytest tests/test_pr_review_schemas.py -v
```

Expected: All tests PASS.

**Step 4: Commit**

```bash
git add schemas/pr_review.py tests/test_pr_review_schemas.py
git commit -m "feat(phase5): add PR review schemas — step results, trading safety checks"
```

---

## Task 2: Severity Classifier

**Files:**
- Create: `skills/severity_classifier.py`
- Test: `tests/test_severity_classifier.py`

**Step 1: Write the failing test**

```python
# tests/test_severity_classifier.py
"""Tests for deterministic severity classifier."""
from schemas.bug_triage import BugSeverity, ErrorCategory, ErrorEvent
from skills.severity_classifier import SeverityClassifier


class TestCriticalSeverity:
    def test_crash_is_critical(self):
        e = ErrorEvent(
            bot_id="bot1", error_type="SystemExit", message="process crashed",
            stack_trace="...", context={"crash": True},
        )
        result = SeverityClassifier().classify(e)
        assert result.severity == BugSeverity.CRITICAL
        assert result.category == ErrorCategory.CRASH

    def test_stuck_position_is_critical(self):
        e = ErrorEvent(
            bot_id="bot1", error_type="TimeoutError",
            message="position stuck open for 6 hours",
            stack_trace="...", context={"stuck_position": True},
        )
        result = SeverityClassifier().classify(e)
        assert result.severity == BugSeverity.CRITICAL
        assert result.category == ErrorCategory.STUCK_POSITION

    def test_connection_lost_is_critical(self):
        e = ErrorEvent(
            bot_id="bot1", error_type="ConnectionError",
            message="connection lost to exchange",
            stack_trace="...",
        )
        result = SeverityClassifier().classify(e)
        assert result.severity == BugSeverity.CRITICAL
        assert result.category == ErrorCategory.CONNECTION_LOST


class TestHighSeverity:
    def test_unexpected_loss_is_high(self):
        e = ErrorEvent(
            bot_id="bot1", error_type="TradingError",
            message="unexpected loss exceeding threshold",
            stack_trace="...", context={"unexpected_loss": True},
        )
        result = SeverityClassifier().classify(e)
        assert result.severity == BugSeverity.HIGH
        assert result.category == ErrorCategory.UNEXPECTED_LOSS

    def test_api_error_is_high(self):
        e = ErrorEvent(
            bot_id="bot1", error_type="APIError",
            message="exchange API returned 500",
            stack_trace="...",
        )
        result = SeverityClassifier().classify(e)
        assert result.severity == BugSeverity.HIGH
        assert result.category == ErrorCategory.API_ERROR


class TestMediumSeverity:
    def test_config_error_is_medium(self):
        e = ErrorEvent(
            bot_id="bot1", error_type="ConfigError",
            message="invalid config value for trailing_stop_pct",
            stack_trace="...",
        )
        result = SeverityClassifier().classify(e)
        assert result.severity == BugSeverity.MEDIUM
        assert result.category == ErrorCategory.CONFIG_ERROR

    def test_generic_runtime_error_is_medium(self):
        e = ErrorEvent(
            bot_id="bot1", error_type="RuntimeError",
            message="division by zero",
            stack_trace="Traceback...\n  File calc.py:10\nRuntimeError: division by zero",
        )
        result = SeverityClassifier().classify(e)
        assert result.severity == BugSeverity.MEDIUM


class TestLowSeverity:
    def test_warning_is_low(self):
        e = ErrorEvent(
            bot_id="bot1", error_type="UserWarning",
            message="some deprecation warning",
            stack_trace="...",
        )
        result = SeverityClassifier().classify(e)
        assert result.severity == BugSeverity.LOW
        assert result.category == ErrorCategory.WARNING

    def test_deprecation_is_low(self):
        e = ErrorEvent(
            bot_id="bot1", error_type="DeprecationWarning",
            message="module X is deprecated",
            stack_trace="...",
        )
        result = SeverityClassifier().classify(e)
        assert result.severity == BugSeverity.LOW
        assert result.category == ErrorCategory.DEPRECATION


class TestMutatesEvent:
    def test_classify_sets_severity_and_category_on_event(self):
        e = ErrorEvent(
            bot_id="bot1", error_type="SystemExit",
            message="crash", stack_trace="...", context={"crash": True},
        )
        assert e.severity is None
        result = SeverityClassifier().classify(e)
        # Returns a ClassificationResult, does NOT mutate the event
        assert e.severity is None  # original unchanged
        assert result.severity == BugSeverity.CRITICAL
```

**Step 2: Implement the classifier**

```python
# skills/severity_classifier.py
"""Deterministic severity classifier — no LLM calls.

Routes error events into severity buckets based on error_type, message patterns,
and context flags. This is the first stage of the triage pipeline.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from schemas.bug_triage import BugSeverity, ErrorCategory, ErrorEvent

# Patterns for each category — checked in priority order (most severe first)
_CRITICAL_PATTERNS: list[tuple[re.Pattern, ErrorCategory]] = [
    (re.compile(r"crash|segfault|abort|SystemExit|SIGKILL|SIGSEGV", re.I), ErrorCategory.CRASH),
    (re.compile(r"stuck.*(position|order)|position.*stuck|open.*(?:too|for)\s+\d+\s*h", re.I), ErrorCategory.STUCK_POSITION),
    (re.compile(r"connection.*(lost|refused|reset|timeout)|lost.*connection|cannot.*reach.*exchange", re.I), ErrorCategory.CONNECTION_LOST),
]

_HIGH_PATTERNS: list[tuple[re.Pattern, ErrorCategory]] = [
    (re.compile(r"unexpected.*loss|loss.*exceed|abnormal.*drawdown", re.I), ErrorCategory.UNEXPECTED_LOSS),
    (re.compile(r"API.*(?:error|500|502|503|429)|exchange.*(?:error|reject|refused)", re.I), ErrorCategory.API_ERROR),
]

_MEDIUM_PATTERNS: list[tuple[re.Pattern, ErrorCategory]] = [
    (re.compile(r"config.*(?:error|invalid|missing)|invalid.*config", re.I), ErrorCategory.CONFIG_ERROR),
    (re.compile(r"import.*error|module.*not.*found|dependency", re.I), ErrorCategory.DEPENDENCY),
]

_LOW_PATTERNS: list[tuple[re.Pattern, ErrorCategory]] = [
    (re.compile(r"deprecat", re.I), ErrorCategory.DEPRECATION),
    (re.compile(r"warning|UserWarning|FutureWarning", re.I), ErrorCategory.WARNING),
]


@dataclass
class ClassificationResult:
    severity: BugSeverity
    category: ErrorCategory


class SeverityClassifier:
    """Deterministic error severity classifier."""

    def classify(self, event: ErrorEvent) -> ClassificationResult:
        """Classify an error event's severity and category.

        Checks context flags first (most reliable), then error_type + message patterns.
        Returns a ClassificationResult; does NOT mutate the event.
        """
        # 1. Check explicit context flags (highest priority)
        ctx = event.context
        if ctx.get("crash"):
            return ClassificationResult(BugSeverity.CRITICAL, ErrorCategory.CRASH)
        if ctx.get("stuck_position"):
            return ClassificationResult(BugSeverity.CRITICAL, ErrorCategory.STUCK_POSITION)
        if ctx.get("connection_lost"):
            return ClassificationResult(BugSeverity.CRITICAL, ErrorCategory.CONNECTION_LOST)
        if ctx.get("unexpected_loss"):
            return ClassificationResult(BugSeverity.HIGH, ErrorCategory.UNEXPECTED_LOSS)

        # 2. Pattern match against error_type + message
        text = f"{event.error_type} {event.message}"

        for pattern, category in _CRITICAL_PATTERNS:
            if pattern.search(text):
                return ClassificationResult(BugSeverity.CRITICAL, category)

        for pattern, category in _HIGH_PATTERNS:
            if pattern.search(text):
                return ClassificationResult(BugSeverity.HIGH, category)

        for pattern, category in _MEDIUM_PATTERNS:
            if pattern.search(text):
                return ClassificationResult(BugSeverity.MEDIUM, category)

        for pattern, category in _LOW_PATTERNS:
            if pattern.search(text):
                return ClassificationResult(BugSeverity.LOW, category)

        # 3. Default: MEDIUM with UNKNOWN category
        return ClassificationResult(BugSeverity.MEDIUM, ErrorCategory.UNKNOWN)
```

**Step 3: Run tests**

```bash
pytest tests/test_severity_classifier.py -v
```

Expected: All tests PASS.

**Step 4: Commit**

```bash
git add skills/severity_classifier.py tests/test_severity_classifier.py
git commit -m "feat(phase5): add deterministic severity classifier with pattern matching"
```

---

## Task 3: Error Rate Tracker

**Files:**
- Create: `skills/error_rate_tracker.py`
- Test: `tests/test_error_rate_tracker.py`

**Step 1: Write the failing test**

```python
# tests/test_error_rate_tracker.py
"""Tests for error rate tracker — sliding window frequency detection."""
from datetime import datetime, timezone, timedelta

from schemas.bug_triage import ErrorEvent
from skills.error_rate_tracker import ErrorRateTracker


class TestErrorRateTracker:
    def test_single_error_below_threshold(self):
        tracker = ErrorRateTracker(window_seconds=3600, threshold=3)
        e = ErrorEvent(bot_id="bot1", error_type="E", message="m", stack_trace="s")
        tracker.record(e)
        assert tracker.is_repeated("bot1") is False

    def test_three_errors_hits_threshold(self):
        tracker = ErrorRateTracker(window_seconds=3600, threshold=3)
        for _ in range(3):
            e = ErrorEvent(bot_id="bot1", error_type="E", message="m", stack_trace="s")
            tracker.record(e)
        assert tracker.is_repeated("bot1") is True

    def test_errors_from_different_bots_tracked_separately(self):
        tracker = ErrorRateTracker(window_seconds=3600, threshold=3)
        for _ in range(3):
            tracker.record(ErrorEvent(bot_id="bot1", error_type="E", message="m", stack_trace="s"))
        tracker.record(ErrorEvent(bot_id="bot2", error_type="E", message="m", stack_trace="s"))
        assert tracker.is_repeated("bot1") is True
        assert tracker.is_repeated("bot2") is False

    def test_old_errors_expire(self):
        tracker = ErrorRateTracker(window_seconds=3600, threshold=3)
        old_time = datetime.now(timezone.utc) - timedelta(hours=2)
        for _ in range(3):
            e = ErrorEvent(
                bot_id="bot1", error_type="E", message="m", stack_trace="s",
                timestamp=old_time,
            )
            tracker.record(e)
        assert tracker.is_repeated("bot1") is False

    def test_get_rate_returns_count(self):
        tracker = ErrorRateTracker(window_seconds=3600, threshold=3)
        for _ in range(5):
            tracker.record(ErrorEvent(bot_id="bot1", error_type="E", message="m", stack_trace="s"))
        assert tracker.get_rate("bot1") == 5

    def test_get_rate_unknown_bot_returns_zero(self):
        tracker = ErrorRateTracker(window_seconds=3600, threshold=3)
        assert tracker.get_rate("unknown") == 0

    def test_clear_bot(self):
        tracker = ErrorRateTracker(window_seconds=3600, threshold=3)
        for _ in range(5):
            tracker.record(ErrorEvent(bot_id="bot1", error_type="E", message="m", stack_trace="s"))
        tracker.clear("bot1")
        assert tracker.get_rate("bot1") == 0
        assert tracker.is_repeated("bot1") is False
```

**Step 2: Implement the tracker**

```python
# skills/error_rate_tracker.py
"""Error rate tracker — sliding window frequency detection.

Tracks error counts per bot within a configurable time window.
When errors exceed the threshold (default: 3/hour), the bot is flagged
as having "repeated errors", which promotes severity to HIGH.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone, timedelta

from schemas.bug_triage import ErrorEvent


class ErrorRateTracker:
    """In-memory sliding window error rate tracker."""

    def __init__(self, window_seconds: int = 3600, threshold: int = 3) -> None:
        self._window = timedelta(seconds=window_seconds)
        self._threshold = threshold
        self._timestamps: dict[str, list[datetime]] = defaultdict(list)

    def record(self, event: ErrorEvent) -> None:
        """Record an error event's timestamp for the given bot."""
        self._timestamps[event.bot_id].append(event.timestamp)

    def is_repeated(self, bot_id: str) -> bool:
        """Check if a bot has exceeded the error threshold within the window."""
        return self.get_rate(bot_id) >= self._threshold

    def get_rate(self, bot_id: str) -> int:
        """Get the count of errors within the current window for a bot."""
        self._prune(bot_id)
        return len(self._timestamps.get(bot_id, []))

    def clear(self, bot_id: str) -> None:
        """Clear all tracked errors for a bot."""
        self._timestamps.pop(bot_id, None)

    def _prune(self, bot_id: str) -> None:
        """Remove timestamps outside the sliding window."""
        if bot_id not in self._timestamps:
            return
        cutoff = datetime.now(timezone.utc) - self._window
        self._timestamps[bot_id] = [
            ts for ts in self._timestamps[bot_id] if ts > cutoff
        ]
```

**Step 3: Run tests**

```bash
pytest tests/test_error_rate_tracker.py -v
```

Expected: All tests PASS.

**Step 4: Commit**

```bash
git add skills/error_rate_tracker.py tests/test_error_rate_tracker.py
git commit -m "feat(phase5): add error rate tracker with sliding window detection"
```

---

## Task 4: Bug Complexity Classifier

**Files:**
- Create: `skills/bug_complexity_classifier.py`
- Test: `tests/test_bug_complexity_classifier.py`

**Step 1: Write the failing test**

```python
# tests/test_bug_complexity_classifier.py
"""Tests for bug complexity classifier."""
from schemas.bug_triage import (
    BugComplexity,
    BugSeverity,
    ErrorCategory,
    ErrorEvent,
    TriageOutcome,
)
from skills.bug_complexity_classifier import BugComplexityClassifier


class TestObviousFix:
    def test_import_error_is_obvious_fix(self):
        e = ErrorEvent(
            bot_id="bot1", error_type="ImportError",
            message="No module named 'requests'",
            stack_trace="...",
            source_file="requirements.txt",
        )
        result = BugComplexityClassifier().classify(e, BugSeverity.MEDIUM, ErrorCategory.DEPENDENCY)
        assert result.complexity == BugComplexity.OBVIOUS_FIX
        assert result.outcome == TriageOutcome.KNOWN_FIX

    def test_config_error_is_obvious_fix(self):
        e = ErrorEvent(
            bot_id="bot1", error_type="ConfigError",
            message="missing key 'api_key' in config.yaml",
            stack_trace="...",
        )
        result = BugComplexityClassifier().classify(e, BugSeverity.MEDIUM, ErrorCategory.CONFIG_ERROR)
        assert result.complexity == BugComplexity.OBVIOUS_FIX
        assert result.outcome == TriageOutcome.KNOWN_FIX

    def test_deprecation_warning_is_obvious_fix(self):
        e = ErrorEvent(
            bot_id="bot1", error_type="DeprecationWarning",
            message="use new_func instead of old_func",
            stack_trace="...",
        )
        result = BugComplexityClassifier().classify(e, BugSeverity.LOW, ErrorCategory.DEPRECATION)
        assert result.complexity == BugComplexity.OBVIOUS_FIX
        assert result.outcome == TriageOutcome.QUEUED_FOR_WEEKLY


class TestSingleFunction:
    def test_runtime_error_single_file(self):
        e = ErrorEvent(
            bot_id="bot1", error_type="RuntimeError",
            message="division by zero",
            stack_trace="Traceback:\n  File \"calc.py\", line 10\n    return x / y\nRuntimeError: division by zero",
            source_file="calc.py",
            source_line=10,
        )
        result = BugComplexityClassifier().classify(e, BugSeverity.MEDIUM, ErrorCategory.UNKNOWN)
        assert result.complexity == BugComplexity.SINGLE_FUNCTION
        assert result.outcome == TriageOutcome.NEEDS_INVESTIGATION

    def test_api_error_single_endpoint(self):
        e = ErrorEvent(
            bot_id="bot1", error_type="APIError",
            message="exchange returned 429",
            stack_trace="Traceback:\n  File \"connector.py\", line 55\nAPIError: 429",
            source_file="connector.py",
            source_line=55,
        )
        result = BugComplexityClassifier().classify(e, BugSeverity.HIGH, ErrorCategory.API_ERROR)
        assert result.complexity == BugComplexity.SINGLE_FUNCTION
        assert result.outcome == TriageOutcome.NEEDS_INVESTIGATION


class TestStateDependentOrMultiFile:
    def test_stuck_position_is_state_dependent(self):
        e = ErrorEvent(
            bot_id="bot1", error_type="TimeoutError",
            message="position stuck",
            stack_trace="...",
        )
        result = BugComplexityClassifier().classify(e, BugSeverity.CRITICAL, ErrorCategory.STUCK_POSITION)
        assert result.complexity == BugComplexity.STATE_DEPENDENT
        assert result.outcome == TriageOutcome.NEEDS_HUMAN

    def test_connection_lost_is_needs_human(self):
        e = ErrorEvent(
            bot_id="bot1", error_type="ConnectionError",
            message="connection lost",
            stack_trace="...",
        )
        result = BugComplexityClassifier().classify(e, BugSeverity.CRITICAL, ErrorCategory.CONNECTION_LOST)
        assert result.complexity == BugComplexity.STATE_DEPENDENT
        assert result.outcome == TriageOutcome.NEEDS_HUMAN


class TestSeverityBasedRouting:
    def test_critical_always_alerted(self):
        """CRITICAL errors → ALERTED regardless of complexity."""
        e = ErrorEvent(
            bot_id="bot1", error_type="SystemExit",
            message="crash", stack_trace="...",
        )
        result = BugComplexityClassifier().classify(e, BugSeverity.CRITICAL, ErrorCategory.CRASH)
        assert result.outcome == TriageOutcome.ALERTED

    def test_low_queued_for_weekly(self):
        """LOW errors → QUEUED_FOR_WEEKLY."""
        e = ErrorEvent(
            bot_id="bot1", error_type="UserWarning",
            message="some warning", stack_trace="...",
        )
        result = BugComplexityClassifier().classify(e, BugSeverity.LOW, ErrorCategory.WARNING)
        assert result.outcome == TriageOutcome.QUEUED_FOR_WEEKLY

    def test_medium_queued_for_daily(self):
        """MEDIUM obvious_fix → QUEUED_FOR_DAILY (not auto-fix, just queue)."""
        e = ErrorEvent(
            bot_id="bot1", error_type="RuntimeError",
            message="some error", stack_trace="...",
        )
        result = BugComplexityClassifier().classify(e, BugSeverity.MEDIUM, ErrorCategory.UNKNOWN)
        assert result.outcome == TriageOutcome.QUEUED_FOR_DAILY


class TestComplexityResult:
    def test_result_has_complexity_and_outcome(self):
        e = ErrorEvent(
            bot_id="bot1", error_type="ImportError",
            message="no module foo", stack_trace="...",
        )
        result = BugComplexityClassifier().classify(e, BugSeverity.HIGH, ErrorCategory.DEPENDENCY)
        assert hasattr(result, "complexity")
        assert hasattr(result, "outcome")
        assert hasattr(result, "rationale")
```

**Step 2: Implement the classifier**

```python
# skills/bug_complexity_classifier.py
"""Bug complexity classifier — determines fix approach based on error characteristics.

Decision matrix:
  CRITICAL → always ALERTED (immediate telegram)
  HIGH + OBVIOUS_FIX → KNOWN_FIX (spawn fix agent)
  HIGH + SINGLE_FUNCTION → NEEDS_INVESTIGATION (create GitHub issue)
  HIGH + STATE_DEPENDENT/MULTI_FILE → NEEDS_HUMAN (Telegram alert)
  MEDIUM → QUEUED_FOR_DAILY
  LOW → QUEUED_FOR_WEEKLY
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from schemas.bug_triage import (
    BugComplexity,
    BugSeverity,
    ErrorCategory,
    ErrorEvent,
    TriageOutcome,
)

_OBVIOUS_FIX_CATEGORIES = {
    ErrorCategory.DEPENDENCY,
    ErrorCategory.CONFIG_ERROR,
    ErrorCategory.DEPRECATION,
}

_STATE_DEPENDENT_CATEGORIES = {
    ErrorCategory.STUCK_POSITION,
    ErrorCategory.CONNECTION_LOST,
}

_MULTI_FILE_PATTERNS = re.compile(
    r"multi.*service|cross.*module|distributed|race.*condition|deadlock",
    re.I,
)


@dataclass
class ComplexityResult:
    complexity: BugComplexity
    outcome: TriageOutcome
    rationale: str


class BugComplexityClassifier:
    """Classifies bug complexity and determines triage outcome."""

    def classify(
        self,
        event: ErrorEvent,
        severity: BugSeverity,
        category: ErrorCategory,
    ) -> ComplexityResult:
        """Classify complexity and determine outcome.

        Args:
            event: The error event to classify.
            severity: Already-classified severity from SeverityClassifier.
            category: Already-classified category from SeverityClassifier.
        """
        complexity = self._assess_complexity(event, category)
        outcome = self._determine_outcome(severity, complexity)
        rationale = self._build_rationale(severity, complexity, category)
        return ComplexityResult(
            complexity=complexity, outcome=outcome, rationale=rationale,
        )

    def _assess_complexity(
        self, event: ErrorEvent, category: ErrorCategory,
    ) -> BugComplexity:
        """Assess how complex the bug is to fix."""
        if category in _OBVIOUS_FIX_CATEGORIES:
            return BugComplexity.OBVIOUS_FIX

        if category in _STATE_DEPENDENT_CATEGORIES:
            return BugComplexity.STATE_DEPENDENT

        text = f"{event.error_type} {event.message}"
        if _MULTI_FILE_PATTERNS.search(text):
            return BugComplexity.MULTI_FILE

        # If we have a single source file, it's likely a single-function issue
        if event.source_file and event.source_line > 0:
            return BugComplexity.SINGLE_FUNCTION

        # Count unique files in stack trace as a heuristic
        file_refs = re.findall(r'File "([^"]+)"', event.stack_trace)
        unique_files = {f for f in file_refs if not f.startswith("<")}
        if len(unique_files) > 3:
            return BugComplexity.MULTI_FILE
        if len(unique_files) == 1:
            return BugComplexity.SINGLE_FUNCTION

        return BugComplexity.UNKNOWN

    def _determine_outcome(
        self, severity: BugSeverity, complexity: BugComplexity,
    ) -> TriageOutcome:
        """Map (severity, complexity) to a triage outcome."""
        if severity == BugSeverity.CRITICAL:
            return TriageOutcome.ALERTED

        if severity == BugSeverity.LOW:
            return TriageOutcome.QUEUED_FOR_WEEKLY

        if severity == BugSeverity.MEDIUM:
            return TriageOutcome.QUEUED_FOR_DAILY

        # HIGH severity — outcome depends on complexity
        if complexity == BugComplexity.OBVIOUS_FIX:
            return TriageOutcome.KNOWN_FIX
        if complexity == BugComplexity.SINGLE_FUNCTION:
            return TriageOutcome.NEEDS_INVESTIGATION
        if complexity in (BugComplexity.MULTI_FILE, BugComplexity.STATE_DEPENDENT):
            return TriageOutcome.NEEDS_HUMAN

        return TriageOutcome.NEEDS_INVESTIGATION  # UNKNOWN complexity

    def _build_rationale(
        self,
        severity: BugSeverity,
        complexity: BugComplexity,
        category: ErrorCategory,
    ) -> str:
        return (
            f"Severity={severity.value}, complexity={complexity.value}, "
            f"category={category.value} → outcome determined by decision matrix"
        )
```

**Step 3: Run tests**

```bash
pytest tests/test_bug_complexity_classifier.py -v
```

Expected: All tests PASS.

**Step 4: Commit**

```bash
git add skills/bug_complexity_classifier.py tests/test_bug_complexity_classifier.py
git commit -m "feat(phase5): add bug complexity classifier with severity-based routing"
```

---

## Task 5: Failure Log (Ralph Loop V2)

**Files:**
- Create: `skills/failure_log.py`
- Test: `tests/test_failure_log.py`

**Step 1: Write the failing test**

```python
# tests/test_failure_log.py
"""Tests for failure log — .assistant/failure-log.jsonl persistence."""
import json
from pathlib import Path

from schemas.bug_triage import BugSeverity, BugComplexity, TriageOutcome, ErrorEvent, TriageResult
from skills.failure_log import FailureLog, FailureEntry


class TestFailureEntry:
    def test_creates_from_triage_result(self):
        tr = TriageResult(
            error_event=ErrorEvent(
                bot_id="bot1", error_type="E", message="m", stack_trace="s",
            ),
            severity=BugSeverity.HIGH,
            complexity=BugComplexity.OBVIOUS_FIX,
            outcome=TriageOutcome.KNOWN_FIX,
            suggested_fix="fix X",
        )
        entry = FailureEntry.from_triage_result(tr, rejection_reason="wrong fix")
        assert entry.bot_id == "bot1"
        assert entry.error_type == "E"
        assert entry.outcome == TriageOutcome.KNOWN_FIX
        assert entry.rejection_reason == "wrong fix"


class TestFailureLogWrite:
    def test_append_creates_file(self, tmp_path: Path):
        log_path = tmp_path / ".assistant" / "failure-log.jsonl"
        log = FailureLog(log_path)
        tr = TriageResult(
            error_event=ErrorEvent(
                bot_id="bot1", error_type="E", message="m", stack_trace="s",
            ),
            severity=BugSeverity.HIGH,
            complexity=BugComplexity.OBVIOUS_FIX,
            outcome=TriageOutcome.KNOWN_FIX,
        )
        log.record_triage(tr)
        assert log_path.exists()
        lines = log_path.read_text().strip().splitlines()
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["bot_id"] == "bot1"

    def test_append_multiple(self, tmp_path: Path):
        log_path = tmp_path / "failure-log.jsonl"
        log = FailureLog(log_path)
        for i in range(3):
            tr = TriageResult(
                error_event=ErrorEvent(
                    bot_id=f"bot{i}", error_type="E", message="m", stack_trace="s",
                ),
                severity=BugSeverity.HIGH,
                complexity=BugComplexity.OBVIOUS_FIX,
                outcome=TriageOutcome.KNOWN_FIX,
            )
            log.record_triage(tr)
        lines = log_path.read_text().strip().splitlines()
        assert len(lines) == 3

    def test_record_rejection(self, tmp_path: Path):
        log_path = tmp_path / "failure-log.jsonl"
        log = FailureLog(log_path)
        tr = TriageResult(
            error_event=ErrorEvent(
                bot_id="bot1", error_type="ImportError", message="no foo", stack_trace="s",
            ),
            severity=BugSeverity.HIGH,
            complexity=BugComplexity.OBVIOUS_FIX,
            outcome=TriageOutcome.KNOWN_FIX,
            pr_url="https://github.com/user/repo/pull/42",
        )
        log.record_rejection(tr, reason="wrong version pinned")
        lines = log_path.read_text().strip().splitlines()
        data = json.loads(lines[0])
        assert data["rejection_reason"] == "wrong version pinned"
        assert data["pr_url"] == "https://github.com/user/repo/pull/42"


class TestFailureLogRead:
    def test_get_past_rejections(self, tmp_path: Path):
        log_path = tmp_path / "failure-log.jsonl"
        log = FailureLog(log_path)

        for i in range(3):
            tr = TriageResult(
                error_event=ErrorEvent(
                    bot_id="bot1", error_type="ImportError", message="no foo", stack_trace="s",
                ),
                severity=BugSeverity.HIGH,
                complexity=BugComplexity.OBVIOUS_FIX,
                outcome=TriageOutcome.KNOWN_FIX,
            )
            log.record_rejection(tr, reason=f"rejection {i}")

        rejections = log.get_past_rejections(error_type="ImportError", limit=10)
        assert len(rejections) == 3
        assert all(r.rejection_reason.startswith("rejection") for r in rejections)

    def test_get_past_rejections_filters_by_error_type(self, tmp_path: Path):
        log_path = tmp_path / "failure-log.jsonl"
        log = FailureLog(log_path)

        for etype in ["ImportError", "RuntimeError", "ImportError"]:
            tr = TriageResult(
                error_event=ErrorEvent(
                    bot_id="bot1", error_type=etype, message="m", stack_trace="s",
                ),
                severity=BugSeverity.HIGH,
                complexity=BugComplexity.OBVIOUS_FIX,
                outcome=TriageOutcome.KNOWN_FIX,
            )
            log.record_rejection(tr, reason=f"rej-{etype}")

        import_rejections = log.get_past_rejections(error_type="ImportError")
        assert len(import_rejections) == 2

    def test_get_past_rejections_empty_file(self, tmp_path: Path):
        log_path = tmp_path / "failure-log.jsonl"
        log = FailureLog(log_path)
        assert log.get_past_rejections(error_type="E") == []

    def test_get_past_rejections_respects_limit(self, tmp_path: Path):
        log_path = tmp_path / "failure-log.jsonl"
        log = FailureLog(log_path)

        for i in range(10):
            tr = TriageResult(
                error_event=ErrorEvent(
                    bot_id="bot1", error_type="E", message="m", stack_trace="s",
                ),
                severity=BugSeverity.HIGH,
                complexity=BugComplexity.OBVIOUS_FIX,
                outcome=TriageOutcome.KNOWN_FIX,
            )
            log.record_rejection(tr, reason=f"rej-{i}")

        rejections = log.get_past_rejections(error_type="E", limit=5)
        assert len(rejections) == 5
```

**Step 2: Implement the failure log**

```python
# skills/failure_log.py
"""Failure log — persists triage outcomes and PR rejections for Ralph Loop V2.

Written to `.assistant/failure-log.jsonl`. Future triage prompts include
past rejections for the same error type, so the system learns from mistakes.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from schemas.bug_triage import TriageOutcome, TriageResult


@dataclass
class FailureEntry:
    bot_id: str
    error_type: str
    message: str
    outcome: TriageOutcome
    rejection_reason: str = ""
    pr_url: str = ""
    suggested_fix: str = ""
    timestamp: str = ""

    @classmethod
    def from_triage_result(
        cls,
        result: TriageResult,
        rejection_reason: str = "",
    ) -> FailureEntry:
        return cls(
            bot_id=result.error_event.bot_id,
            error_type=result.error_event.error_type,
            message=result.error_event.message,
            outcome=result.outcome,
            rejection_reason=rejection_reason,
            pr_url=result.pr_url,
            suggested_fix=result.suggested_fix,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    def to_dict(self) -> dict:
        return {
            "bot_id": self.bot_id,
            "error_type": self.error_type,
            "message": self.message,
            "outcome": self.outcome.value,
            "rejection_reason": self.rejection_reason,
            "pr_url": self.pr_url,
            "suggested_fix": self.suggested_fix,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, d: dict) -> FailureEntry:
        return cls(
            bot_id=d["bot_id"],
            error_type=d["error_type"],
            message=d["message"],
            outcome=TriageOutcome(d["outcome"]),
            rejection_reason=d.get("rejection_reason", ""),
            pr_url=d.get("pr_url", ""),
            suggested_fix=d.get("suggested_fix", ""),
            timestamp=d.get("timestamp", ""),
        )


class FailureLog:
    """Append-only JSONL log of triage outcomes and PR rejections."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def record_triage(self, result: TriageResult) -> None:
        """Record a triage outcome."""
        entry = FailureEntry.from_triage_result(result)
        self._append(entry)

    def record_rejection(self, result: TriageResult, reason: str) -> None:
        """Record a PR rejection with the reason."""
        entry = FailureEntry.from_triage_result(result, rejection_reason=reason)
        self._append(entry)

    def get_past_rejections(
        self,
        error_type: str,
        limit: int = 10,
    ) -> list[FailureEntry]:
        """Load past rejections filtered by error_type."""
        if not self._path.exists():
            return []

        entries: list[FailureEntry] = []
        for line in self._path.read_text(encoding="utf-8").strip().splitlines():
            if not line.strip():
                continue
            data = json.loads(line)
            if data.get("error_type") == error_type and data.get("rejection_reason"):
                entries.append(FailureEntry.from_dict(data))

        return entries[-limit:]

    def _append(self, entry: FailureEntry) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry.to_dict()) + "\n")
```

**Step 3: Run tests**

```bash
pytest tests/test_failure_log.py -v
```

Expected: All tests PASS.

**Step 4: Commit**

```bash
git add skills/failure_log.py tests/test_failure_log.py
git commit -m "feat(phase5): add failure log for Ralph Loop V2 feedback"
```

---

## Task 6: Triage Context Builder

**Files:**
- Create: `skills/triage_context_builder.py`
- Test: `tests/test_triage_context_builder.py`

**Step 1: Write the failing test**

```python
# tests/test_triage_context_builder.py
"""Tests for triage context builder — assembles stack trace + source + git log."""
import json
from pathlib import Path

from schemas.bug_triage import ErrorEvent, BugSeverity, ErrorCategory
from skills.failure_log import FailureEntry, FailureLog
from skills.triage_context_builder import TriageContextBuilder, TriageContext


class TestTriageContext:
    def test_has_required_fields(self):
        ctx = TriageContext(
            error_event_summary="RuntimeError: division by zero in calc.py:10",
            stack_trace="Traceback...",
            source_snippet="",
            recent_git_log="",
            past_rejections=[],
        )
        assert ctx.error_event_summary != ""
        assert ctx.stack_trace != ""


class TestTriageContextBuilder:
    def test_builds_context_with_source_file(self, tmp_path: Path):
        # Create a fake source file
        src = tmp_path / "calc.py"
        src.write_text("def divide(x, y):\n    return x / y\n")

        e = ErrorEvent(
            bot_id="bot1", error_type="RuntimeError",
            message="division by zero",
            stack_trace='Traceback:\n  File "calc.py", line 2\n    return x / y\nRuntimeError: division by zero',
            source_file="calc.py",
            source_line=2,
        )

        builder = TriageContextBuilder(source_root=tmp_path)
        ctx = builder.build(e, BugSeverity.HIGH, ErrorCategory.UNKNOWN, [])

        assert "RuntimeError" in ctx.error_event_summary
        assert "division by zero" in ctx.error_event_summary
        assert "return x / y" in ctx.source_snippet

    def test_builds_context_without_source_file(self, tmp_path: Path):
        e = ErrorEvent(
            bot_id="bot1", error_type="ConnectionError",
            message="connection lost",
            stack_trace="...",
        )

        builder = TriageContextBuilder(source_root=tmp_path)
        ctx = builder.build(e, BugSeverity.CRITICAL, ErrorCategory.CONNECTION_LOST, [])

        assert ctx.source_snippet == ""
        assert "ConnectionError" in ctx.error_event_summary

    def test_includes_past_rejections(self, tmp_path: Path):
        e = ErrorEvent(
            bot_id="bot1", error_type="ImportError",
            message="no module foo",
            stack_trace="...",
        )

        past = [
            FailureEntry(
                bot_id="bot1", error_type="ImportError", message="no module foo",
                outcome="known_fix", rejection_reason="wrong version",
            ),
        ]

        builder = TriageContextBuilder(source_root=tmp_path)
        ctx = builder.build(e, BugSeverity.HIGH, ErrorCategory.DEPENDENCY, past)

        assert len(ctx.past_rejections) == 1
        assert "wrong version" in ctx.past_rejections[0]

    def test_source_snippet_includes_surrounding_lines(self, tmp_path: Path):
        src = tmp_path / "module.py"
        lines = [f"line {i}\n" for i in range(1, 21)]
        src.write_text("".join(lines))

        e = ErrorEvent(
            bot_id="bot1", error_type="E", message="m",
            stack_trace="...", source_file="module.py", source_line=10,
        )

        builder = TriageContextBuilder(source_root=tmp_path, context_lines=3)
        ctx = builder.build(e, BugSeverity.HIGH, ErrorCategory.UNKNOWN, [])

        # Should include lines 7-13 (3 before, target, 3 after)
        assert "line 7" in ctx.source_snippet
        assert "line 10" in ctx.source_snippet
        assert "line 13" in ctx.source_snippet
```

**Step 2: Implement the context builder**

```python
# skills/triage_context_builder.py
"""Triage context builder — assembles context for the bug triage agent.

Collects: error summary, stack trace, source code snippet around the error line,
recent git log, and past rejection reasons for similar errors.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from schemas.bug_triage import BugSeverity, ErrorCategory, ErrorEvent
from skills.failure_log import FailureEntry


@dataclass
class TriageContext:
    """Context package for the triage agent."""

    error_event_summary: str
    stack_trace: str
    source_snippet: str
    recent_git_log: str
    past_rejections: list[str] = field(default_factory=list)


class TriageContextBuilder:
    """Builds context for the bug triage agent."""

    def __init__(
        self,
        source_root: Path,
        context_lines: int = 10,
    ) -> None:
        self._source_root = source_root
        self._context_lines = context_lines

    def build(
        self,
        event: ErrorEvent,
        severity: BugSeverity,
        category: ErrorCategory,
        past_rejections: list[FailureEntry],
    ) -> TriageContext:
        summary = (
            f"[{severity.value.upper()}] {event.error_type}: {event.message} "
            f"(bot={event.bot_id}, category={category.value})"
        )

        source_snippet = self._extract_source(event.source_file, event.source_line)
        rejection_texts = [
            f"Past rejection: {r.rejection_reason}" for r in past_rejections if r.rejection_reason
        ]

        return TriageContext(
            error_event_summary=summary,
            stack_trace=event.stack_trace,
            source_snippet=source_snippet,
            recent_git_log="",  # populated by caller if git is available
            past_rejections=rejection_texts,
        )

    def _extract_source(self, source_file: str, source_line: int) -> str:
        """Extract source code around the error line."""
        if not source_file or source_line <= 0:
            return ""

        path = self._source_root / source_file
        if not path.exists():
            return ""

        try:
            all_lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            return ""

        start = max(0, source_line - 1 - self._context_lines)
        end = min(len(all_lines), source_line + self._context_lines)

        snippet_lines: list[str] = []
        for i in range(start, end):
            line_num = i + 1
            marker = " >>> " if line_num == source_line else "     "
            snippet_lines.append(f"{line_num:4d}{marker}{all_lines[i]}")

        return "\n".join(snippet_lines)
```

**Step 3: Run tests**

```bash
pytest tests/test_triage_context_builder.py -v
```

Expected: All tests PASS.

**Step 4: Commit**

```bash
git add skills/triage_context_builder.py tests/test_triage_context_builder.py
git commit -m "feat(phase5): add triage context builder with source snippet extraction"
```

---

## Task 7: PR Review Checker

**Files:**
- Create: `skills/pr_review_checker.py`
- Test: `tests/test_pr_review_checker.py`

**Step 1: Write the failing test**

```python
# tests/test_pr_review_checker.py
"""Tests for PR review checker — trading-specific safety assertions."""
from schemas.pr_review import (
    PRReviewStep,
    PRReviewStepResult,
    PRReviewStatus,
    TradingSafetyCheck,
    TradingSafetyResult,
    PRReviewResult,
)
from schemas.permissions import PermissionTier
from skills.pr_review_checker import PRReviewChecker


class TestPermissionGateCheck:
    def test_auto_tier_passes(self):
        checker = PRReviewChecker(permission_config={
            "permission_tiers": {
                "auto": {"file_paths": ["tests/*", "*.md"]},
                "requires_approval": {"file_paths": ["skills/*"]},
                "requires_double_approval": {"file_paths": ["orchestrator/orchestrator_brain.py"]},
            }
        })
        result = checker.check_permission_gate(["tests/test_foo.py", "README.md"])
        assert result.status == PRReviewStatus.PASSED

    def test_requires_approval_blocks(self):
        checker = PRReviewChecker(permission_config={
            "permission_tiers": {
                "auto": {"file_paths": ["tests/*"]},
                "requires_approval": {"file_paths": ["skills/*"]},
                "requires_double_approval": {},
            }
        })
        result = checker.check_permission_gate(["skills/severity_classifier.py"])
        assert result.status == PRReviewStatus.BLOCKED
        assert "requires_approval" in result.blocker_reason.lower()

    def test_double_approval_blocks(self):
        checker = PRReviewChecker(permission_config={
            "permission_tiers": {
                "auto": {},
                "requires_approval": {},
                "requires_double_approval": {"file_paths": ["orchestrator/*"]},
            }
        })
        result = checker.check_permission_gate(["orchestrator/brain.py"])
        assert result.status == PRReviewStatus.BLOCKED
        assert "double" in result.blocker_reason.lower()


class TestTradingSafetyChecks:
    def test_position_sizing_unchanged_passes(self):
        checker = PRReviewChecker(permission_config=_MINIMAL_CONFIG)
        result = checker.check_trading_safety(
            changed_files=["skills/severity_classifier.py"],
            diff_content="+ def classify(self):\n+     return BugSeverity.HIGH",
        )
        pos_check = _find_safety(result, TradingSafetyCheck.POSITION_SIZING_UNCHANGED)
        assert pos_check.passed is True

    def test_position_sizing_flags_when_touched(self):
        checker = PRReviewChecker(permission_config=_MINIMAL_CONFIG)
        result = checker.check_trading_safety(
            changed_files=["skills/position_sizer.py"],
            diff_content="- position_size = balance * 0.01\n+ position_size = balance * 0.02",
        )
        pos_check = _find_safety(result, TradingSafetyCheck.POSITION_SIZING_UNCHANGED)
        assert pos_check.passed is False

    def test_risk_limits_unchanged_passes(self):
        checker = PRReviewChecker(permission_config=_MINIMAL_CONFIG)
        result = checker.check_trading_safety(
            changed_files=["tests/test_foo.py"],
            diff_content="+ assert result == True",
        )
        risk_check = _find_safety(result, TradingSafetyCheck.RISK_LIMITS_ENFORCED)
        assert risk_check.passed is True

    def test_risk_limits_flags_when_touched(self):
        checker = PRReviewChecker(permission_config=_MINIMAL_CONFIG)
        result = checker.check_trading_safety(
            changed_files=["config/risk_limits.yaml"],
            diff_content="- max_drawdown: 0.05\n+ max_drawdown: 0.10",
        )
        risk_check = _find_safety(result, TradingSafetyCheck.RISK_LIMITS_ENFORCED)
        assert risk_check.passed is False

    def test_kill_switch_unchanged_passes(self):
        checker = PRReviewChecker(permission_config=_MINIMAL_CONFIG)
        result = checker.check_trading_safety(
            changed_files=["tests/test_foo.py"],
            diff_content="+ pass",
        )
        ks_check = _find_safety(result, TradingSafetyCheck.KILL_SWITCH_WORKS)
        assert ks_check.passed is True

    def test_kill_switch_flags_when_touched(self):
        checker = PRReviewChecker(permission_config=_MINIMAL_CONFIG)
        result = checker.check_trading_safety(
            changed_files=["orchestrator/kill_switch.py"],
            diff_content="- if should_kill:\n-     kill()\n+ pass",
        )
        ks_check = _find_safety(result, TradingSafetyCheck.KILL_SWITCH_WORKS)
        assert ks_check.passed is False


class TestRunFullReview:
    def test_full_review_all_pass(self):
        checker = PRReviewChecker(permission_config={
            "permission_tiers": {
                "auto": {"file_paths": ["tests/*"]},
                "requires_approval": {},
                "requires_double_approval": {},
            }
        })
        result = checker.run_review(
            pr_url="https://github.com/user/repo/pull/1",
            changed_files=["tests/test_foo.py"],
            diff_content="+ assert True",
            ci_passed=True,
        )
        assert isinstance(result, PRReviewResult)
        assert result.overall_passed is True

    def test_full_review_ci_fails(self):
        checker = PRReviewChecker(permission_config={
            "permission_tiers": {
                "auto": {"file_paths": ["tests/*"]},
                "requires_approval": {},
                "requires_double_approval": {},
            }
        })
        result = checker.run_review(
            pr_url="https://github.com/user/repo/pull/2",
            changed_files=["tests/test_foo.py"],
            diff_content="+ assert True",
            ci_passed=False,
        )
        assert result.overall_passed is False


# --- Helpers ---

_MINIMAL_CONFIG = {
    "permission_tiers": {
        "auto": {"file_paths": ["tests/*", "*.md"]},
        "requires_approval": {},
        "requires_double_approval": {},
    }
}


def _find_safety(
    results: list[TradingSafetyResult], check: TradingSafetyCheck,
) -> TradingSafetyResult:
    for r in results:
        if r.check == check:
            return r
    raise ValueError(f"Safety check {check} not found in results")
```

**Step 2: Implement the checker**

```python
# skills/pr_review_checker.py
"""PR review checker — multi-stage review pipeline with trading safety assertions.

Every automated PR goes through:
1. CI check (lint, types, unit tests, integration tests)
2. Permission gate check — file paths verified against tiers
3. Trading-specific safety checks:
   - Position sizing unchanged
   - Risk limits still enforced
   - Kill switch still works
"""
from __future__ import annotations

import re

from orchestrator.permission_gates import PermissionGateChecker
from schemas.permissions import PermissionTier
from schemas.pr_review import (
    PRReviewResult,
    PRReviewStatus,
    PRReviewStep,
    PRReviewStepResult,
    TradingSafetyCheck,
    TradingSafetyResult,
)

# Patterns that indicate trading-critical changes
_POSITION_SIZING_PATTERNS = re.compile(
    r"position.?siz|lot.?size|order.?size|leverage|margin",
    re.I,
)
_RISK_LIMIT_PATTERNS = re.compile(
    r"risk.?limit|max.?drawdown|max.?loss|stop.?loss.?pct|risk.?per.?trade|max.?position",
    re.I,
)
_KILL_SWITCH_PATTERNS = re.compile(
    r"kill.?switch|emergency.?stop|halt.?trading|shutdown|circuit.?breaker",
    re.I,
)


class PRReviewChecker:
    """Runs the multi-stage PR review pipeline."""

    def __init__(self, permission_config: dict) -> None:
        self._gate = PermissionGateChecker(permission_config)

    def run_review(
        self,
        pr_url: str,
        changed_files: list[str],
        diff_content: str,
        ci_passed: bool,
    ) -> PRReviewResult:
        """Run the full review pipeline and return aggregated results."""
        steps: list[PRReviewStepResult] = []

        # Step 1: CI check
        steps.append(PRReviewStepResult(
            step=PRReviewStep.CI_CHECK,
            status=PRReviewStatus.PASSED if ci_passed else PRReviewStatus.FAILED,
            detail="All CI checks passed" if ci_passed else "CI checks failed",
        ))

        # Step 2: Permission gate
        steps.append(self.check_permission_gate(changed_files))

        # Step 3: Trading safety
        safety_checks = self.check_trading_safety(changed_files, diff_content)

        return PRReviewResult(
            pr_url=pr_url,
            steps=steps,
            safety_checks=safety_checks,
        )

    def check_permission_gate(self, changed_files: list[str]) -> PRReviewStepResult:
        """Check file paths against permission tiers."""
        result = self._gate.check_file_paths(changed_files)

        if result.tier == PermissionTier.AUTO:
            return PRReviewStepResult(
                step=PRReviewStep.PERMISSION_GATE,
                status=PRReviewStatus.PASSED,
                detail="All files in AUTO tier",
            )

        tier_name = result.tier.name.lower()
        flagged = ", ".join(result.flagged_files) if result.flagged_files else "unknown"
        return PRReviewStepResult(
            step=PRReviewStep.PERMISSION_GATE,
            status=PRReviewStatus.BLOCKED,
            detail=f"Files require {tier_name}: {flagged}",
            blocker_reason=f"{tier_name} for: {flagged}",
        )

    def check_trading_safety(
        self,
        changed_files: list[str],
        diff_content: str,
    ) -> list[TradingSafetyResult]:
        """Run all trading-specific safety checks."""
        combined = " ".join(changed_files) + " " + diff_content

        return [
            self._check_pattern(
                TradingSafetyCheck.POSITION_SIZING_UNCHANGED,
                _POSITION_SIZING_PATTERNS,
                combined,
            ),
            self._check_pattern(
                TradingSafetyCheck.RISK_LIMITS_ENFORCED,
                _RISK_LIMIT_PATTERNS,
                combined,
            ),
            self._check_pattern(
                TradingSafetyCheck.KILL_SWITCH_WORKS,
                _KILL_SWITCH_PATTERNS,
                combined,
            ),
        ]

    def _check_pattern(
        self,
        check: TradingSafetyCheck,
        pattern: re.Pattern,
        text: str,
    ) -> TradingSafetyResult:
        match = pattern.search(text)
        if match:
            return TradingSafetyResult(
                check=check,
                passed=False,
                detail=f"Pattern matched: '{match.group()}' — verify this is intentional",
            )
        return TradingSafetyResult(check=check, passed=True)
```

**Step 3: Run tests**

```bash
pytest tests/test_pr_review_checker.py -v
```

Expected: All tests PASS.

**Step 4: Commit**

```bash
git add skills/pr_review_checker.py tests/test_pr_review_checker.py
git commit -m "feat(phase5): add PR review checker with trading safety assertions"
```

---

## Task 8: Triage Prompt Assembler

**Files:**
- Create: `analysis/triage_prompt_assembler.py`
- Test: `tests/test_triage_prompt_assembler.py`

**Step 1: Write the failing test**

```python
# tests/test_triage_prompt_assembler.py
"""Tests for triage prompt assembler — packages context for Claude."""
from pathlib import Path

from schemas.bug_triage import BugSeverity, BugComplexity, ErrorCategory, ErrorEvent, TriageOutcome
from skills.triage_context_builder import TriageContext
from analysis.triage_prompt_assembler import TriagePromptAssembler


class TestTriagePromptAssembler:
    def test_assemble_returns_required_keys(self, tmp_path: Path):
        ctx = TriageContext(
            error_event_summary="[HIGH] RuntimeError: division by zero (bot=bot1)",
            stack_trace="Traceback...",
            source_snippet="10 >>> return x / y",
            recent_git_log="abc123 fix: previous fix",
            past_rejections=[],
        )
        asm = TriagePromptAssembler(memory_dir=tmp_path)
        result = asm.assemble(ctx, BugSeverity.HIGH, BugComplexity.OBVIOUS_FIX)

        assert "system_prompt" in result
        assert "task_prompt" in result
        assert "context" in result

    def test_task_prompt_includes_severity_and_complexity(self, tmp_path: Path):
        ctx = TriageContext(
            error_event_summary="[HIGH] ImportError: no module foo",
            stack_trace="...",
            source_snippet="",
            recent_git_log="",
            past_rejections=[],
        )
        asm = TriagePromptAssembler(memory_dir=tmp_path)
        result = asm.assemble(ctx, BugSeverity.HIGH, BugComplexity.OBVIOUS_FIX)

        assert "HIGH" in result["task_prompt"]
        assert "obvious_fix" in result["task_prompt"]

    def test_includes_past_rejections_in_context(self, tmp_path: Path):
        ctx = TriageContext(
            error_event_summary="[HIGH] ImportError: no module foo",
            stack_trace="...",
            source_snippet="",
            recent_git_log="",
            past_rejections=["Past rejection: wrong version pinned"],
        )
        asm = TriagePromptAssembler(memory_dir=tmp_path)
        result = asm.assemble(ctx, BugSeverity.HIGH, BugComplexity.OBVIOUS_FIX)

        assert "wrong version pinned" in result["context"]

    def test_includes_stack_trace_in_context(self, tmp_path: Path):
        ctx = TriageContext(
            error_event_summary="[HIGH] RuntimeError: x",
            stack_trace="Traceback (most recent call last):\n  File foo.py:10\nRuntimeError: x",
            source_snippet="",
            recent_git_log="",
            past_rejections=[],
        )
        asm = TriagePromptAssembler(memory_dir=tmp_path)
        result = asm.assemble(ctx, BugSeverity.HIGH, BugComplexity.SINGLE_FUNCTION)

        assert "Traceback" in result["context"]

    def test_includes_source_snippet_in_context(self, tmp_path: Path):
        ctx = TriageContext(
            error_event_summary="[HIGH] E: m",
            stack_trace="...",
            source_snippet="  10 >>> return x / y",
            recent_git_log="",
            past_rejections=[],
        )
        asm = TriagePromptAssembler(memory_dir=tmp_path)
        result = asm.assemble(ctx, BugSeverity.HIGH, BugComplexity.SINGLE_FUNCTION)

        assert "return x / y" in result["context"]

    def test_loads_policies_for_system_prompt(self, tmp_path: Path):
        policy_dir = tmp_path / "policies" / "v1"
        policy_dir.mkdir(parents=True)
        (policy_dir / "agents.md").write_text("Be helpful.")

        asm = TriagePromptAssembler(memory_dir=tmp_path)
        ctx = TriageContext(
            error_event_summary="e", stack_trace="s",
            source_snippet="", recent_git_log="", past_rejections=[],
        )
        result = asm.assemble(ctx, BugSeverity.HIGH, BugComplexity.OBVIOUS_FIX)

        assert "Be helpful" in result["system_prompt"]
```

**Step 2: Implement the assembler**

```python
# analysis/triage_prompt_assembler.py
"""Triage prompt assembler — builds context package for the Claude triage agent.

Follows the same pattern as DailyPromptAssembler:
  SYSTEM PROMPT: policies
  TASK PROMPT: triage instructions with severity/complexity
  CONTEXT: stack trace + source + git log + past rejections
"""
from __future__ import annotations

from pathlib import Path

from schemas.bug_triage import BugComplexity, BugSeverity
from skills.triage_context_builder import TriageContext

_TRIAGE_INSTRUCTIONS = """\
1. Analyze the error event summary and severity classification
2. Read the stack trace to identify the root cause
3. If source code is provided, review the code around the error
4. Check past rejections — do NOT repeat previously rejected fixes
5. Based on the complexity assessment:
   - OBVIOUS_FIX: Propose a specific fix with exact file paths and code changes
   - SINGLE_FUNCTION: Identify the root cause, suggest investigation steps
   - MULTI_FILE / STATE_DEPENDENT: Summarize findings, recommend human intervention
6. Output: triage_result.json with outcome, affected_files, and suggested_fix"""


class TriagePromptAssembler:
    """Assembles the full context package for a bug triage agent invocation."""

    def __init__(self, memory_dir: Path) -> None:
        self._memory_dir = memory_dir

    def assemble(
        self,
        context: TriageContext,
        severity: BugSeverity,
        complexity: BugComplexity,
    ) -> dict:
        """Build the complete prompt package."""
        system_prompt = self._build_system_prompt()
        task_prompt = self._build_task_prompt(severity, complexity)
        context_text = self._build_context(context)

        return {
            "system_prompt": system_prompt,
            "task_prompt": task_prompt,
            "context": context_text,
            "instructions": _TRIAGE_INSTRUCTIONS,
        }

    def _build_system_prompt(self) -> str:
        parts: list[str] = []
        policy_dir = self._memory_dir / "policies" / "v1"

        for name in ["agents.md", "trading_rules.md", "soul.md"]:
            path = policy_dir / name
            if path.exists():
                parts.append(f"--- {name} ---\n{path.read_text()}")

        return "\n\n".join(parts)

    def _build_task_prompt(
        self, severity: BugSeverity, complexity: BugComplexity,
    ) -> str:
        return (
            f"Triage this error event.\n"
            f"Severity: {severity.value.upper()}\n"
            f"Complexity: {complexity.value}\n"
            f"Follow the instructions to produce a triage result."
        )

    def _build_context(self, context: TriageContext) -> str:
        sections: list[str] = []

        sections.append(f"## Error Summary\n{context.error_event_summary}")
        sections.append(f"## Stack Trace\n```\n{context.stack_trace}\n```")

        if context.source_snippet:
            sections.append(f"## Source Code\n```python\n{context.source_snippet}\n```")

        if context.recent_git_log:
            sections.append(f"## Recent Git Log\n```\n{context.recent_git_log}\n```")

        if context.past_rejections:
            rejections = "\n".join(f"- {r}" for r in context.past_rejections)
            sections.append(f"## Past Rejections\n{rejections}")

        return "\n\n".join(sections)
```

**Step 3: Run tests**

```bash
pytest tests/test_triage_prompt_assembler.py -v
```

Expected: All tests PASS.

**Step 4: Commit**

```bash
git add analysis/triage_prompt_assembler.py tests/test_triage_prompt_assembler.py
git commit -m "feat(phase5): add triage prompt assembler for Claude context packaging"
```

---

## Task 9: PR Report Builder

**Files:**
- Create: `analysis/pr_report_builder.py`
- Test: `tests/test_pr_report_builder.py`

**Step 1: Write the failing test**

```python
# tests/test_pr_report_builder.py
"""Tests for PR report builder — markdown summary of PR review results."""
from schemas.pr_review import (
    PRReviewResult,
    PRReviewStep,
    PRReviewStepResult,
    PRReviewStatus,
    TradingSafetyCheck,
    TradingSafetyResult,
)
from analysis.pr_report_builder import PRReportBuilder


class TestPRReportBuilder:
    def test_builds_markdown_for_passed_review(self):
        result = PRReviewResult(
            pr_url="https://github.com/user/repo/pull/42",
            steps=[
                PRReviewStepResult(step=PRReviewStep.CI_CHECK, status=PRReviewStatus.PASSED),
                PRReviewStepResult(step=PRReviewStep.PERMISSION_GATE, status=PRReviewStatus.PASSED),
            ],
            safety_checks=[
                TradingSafetyResult(check=TradingSafetyCheck.KILL_SWITCH_WORKS, passed=True),
            ],
        )
        md = PRReportBuilder.build_markdown(result)

        assert "PR Review" in md
        assert "PASSED" in md.upper() or "passed" in md.lower()
        assert "pull/42" in md

    def test_builds_markdown_for_failed_review(self):
        result = PRReviewResult(
            pr_url="https://github.com/user/repo/pull/99",
            steps=[
                PRReviewStepResult(step=PRReviewStep.CI_CHECK, status=PRReviewStatus.FAILED, detail="lint errors"),
            ],
            safety_checks=[],
        )
        md = PRReportBuilder.build_markdown(result)

        assert "FAILED" in md.upper() or "failed" in md.lower()
        assert "lint errors" in md

    def test_builds_markdown_for_safety_failures(self):
        result = PRReviewResult(
            pr_url="https://github.com/user/repo/pull/7",
            steps=[
                PRReviewStepResult(step=PRReviewStep.CI_CHECK, status=PRReviewStatus.PASSED),
            ],
            safety_checks=[
                TradingSafetyResult(
                    check=TradingSafetyCheck.POSITION_SIZING_UNCHANGED,
                    passed=False,
                    detail="Position size formula changed",
                ),
            ],
        )
        md = PRReportBuilder.build_markdown(result)

        assert "position_sizing" in md.lower() or "Position" in md
        assert "changed" in md.lower()

    def test_builds_markdown_for_blocked_permission(self):
        result = PRReviewResult(
            pr_url="https://github.com/user/repo/pull/5",
            steps=[
                PRReviewStepResult(
                    step=PRReviewStep.PERMISSION_GATE,
                    status=PRReviewStatus.BLOCKED,
                    blocker_reason="requires_approval for skills/foo.py",
                ),
            ],
            safety_checks=[],
        )
        md = PRReportBuilder.build_markdown(result)

        assert "blocked" in md.lower() or "BLOCKED" in md
        assert "requires_approval" in md
```

**Step 2: Implement the report builder**

```python
# analysis/pr_report_builder.py
"""PR report builder — generates markdown summary of PR review results.

Produces a human-readable summary suitable for Telegram notifications.
"""
from __future__ import annotations

from schemas.pr_review import PRReviewResult, PRReviewStatus


class PRReportBuilder:
    """Builds markdown reports from PR review results."""

    @staticmethod
    def build_markdown(result: PRReviewResult) -> str:
        lines: list[str] = []

        overall = "PASSED" if result.overall_passed else "FAILED"
        lines.append(f"# PR Review — {overall}")
        lines.append(f"**PR:** {result.pr_url}")
        lines.append("")

        # Step results
        lines.append("## Review Steps")
        for step in result.steps:
            icon = _status_icon(step.status)
            line = f"- {icon} **{step.step.value}**: {step.status.value}"
            if step.detail:
                line += f" — {step.detail}"
            if step.blocker_reason:
                line += f"\n  - Blocker: {step.blocker_reason}"
            lines.append(line)
        lines.append("")

        # Safety checks
        if result.safety_checks:
            lines.append("## Trading Safety Checks")
            for check in result.safety_checks:
                icon = "pass" if check.passed else "FAIL"
                line = f"- [{icon}] **{check.check.value}**"
                if check.detail:
                    line += f": {check.detail}"
                if check.is_intentional_change:
                    line += " (intentional)"
                lines.append(line)
            lines.append("")

        return "\n".join(lines)


def _status_icon(status: PRReviewStatus) -> str:
    return {
        PRReviewStatus.PASSED: "ok",
        PRReviewStatus.FAILED: "FAIL",
        PRReviewStatus.BLOCKED: "BLOCKED",
        PRReviewStatus.PENDING: "...",
    }.get(status, "?")
```

**Step 3: Run tests**

```bash
pytest tests/test_pr_report_builder.py -v
```

Expected: All tests PASS.

**Step 4: Commit**

```bash
git add analysis/pr_report_builder.py tests/test_pr_report_builder.py
git commit -m "feat(phase5): add PR report builder with markdown summary generation"
```

---

## Task 10: Triage Runner (Main Pipeline)

**Files:**
- Create: `skills/run_bug_triage.py`
- Test: `tests/test_triage_runner.py`

**Step 1: Write the failing test**

```python
# tests/test_triage_runner.py
"""Tests for triage runner — main pipeline orchestrating severity → complexity → route."""
from pathlib import Path

from schemas.bug_triage import (
    BugSeverity,
    BugComplexity,
    ErrorCategory,
    ErrorEvent,
    TriageOutcome,
    TriageResult,
)
from skills.run_bug_triage import TriageRunner


class TestTriageRunnerCritical:
    def test_critical_crash_returns_alerted(self, tmp_path: Path):
        runner = TriageRunner(
            source_root=tmp_path,
            failure_log_path=tmp_path / "failure-log.jsonl",
        )
        event = ErrorEvent(
            bot_id="bot1", error_type="SystemExit",
            message="process crashed", stack_trace="...",
            context={"crash": True},
        )
        result = runner.triage(event)
        assert result.severity == BugSeverity.CRITICAL
        assert result.outcome == TriageOutcome.ALERTED

    def test_critical_connection_lost_returns_alerted(self, tmp_path: Path):
        runner = TriageRunner(
            source_root=tmp_path,
            failure_log_path=tmp_path / "failure-log.jsonl",
        )
        event = ErrorEvent(
            bot_id="bot1", error_type="ConnectionError",
            message="connection lost to exchange",
            stack_trace="...",
        )
        result = runner.triage(event)
        assert result.severity == BugSeverity.CRITICAL
        assert result.outcome == TriageOutcome.ALERTED


class TestTriageRunnerHigh:
    def test_high_obvious_fix_returns_known_fix(self, tmp_path: Path):
        runner = TriageRunner(
            source_root=tmp_path,
            failure_log_path=tmp_path / "failure-log.jsonl",
        )
        event = ErrorEvent(
            bot_id="bot1", error_type="ImportError",
            message="No module named requests",
            stack_trace="...",
        )
        # Manually push severity to HIGH (e.g., via repeated errors)
        result = runner.triage(event, severity_override=BugSeverity.HIGH)
        assert result.severity == BugSeverity.HIGH
        assert result.outcome == TriageOutcome.KNOWN_FIX

    def test_high_single_function_returns_needs_investigation(self, tmp_path: Path):
        runner = TriageRunner(
            source_root=tmp_path,
            failure_log_path=tmp_path / "failure-log.jsonl",
        )
        event = ErrorEvent(
            bot_id="bot1", error_type="APIError",
            message="exchange returned 500",
            stack_trace='Traceback:\n  File "connector.py", line 55\nAPIError: 500',
            source_file="connector.py",
            source_line=55,
        )
        result = runner.triage(event)
        assert result.severity == BugSeverity.HIGH
        assert result.outcome == TriageOutcome.NEEDS_INVESTIGATION


class TestTriageRunnerMediumLow:
    def test_medium_queued_for_daily(self, tmp_path: Path):
        runner = TriageRunner(
            source_root=tmp_path,
            failure_log_path=tmp_path / "failure-log.jsonl",
        )
        event = ErrorEvent(
            bot_id="bot1", error_type="RuntimeError",
            message="division by zero",
            stack_trace="Traceback:\n  File calc.py:10\nRuntimeError: division by zero",
        )
        result = runner.triage(event)
        assert result.severity == BugSeverity.MEDIUM
        assert result.outcome == TriageOutcome.QUEUED_FOR_DAILY

    def test_low_queued_for_weekly(self, tmp_path: Path):
        runner = TriageRunner(
            source_root=tmp_path,
            failure_log_path=tmp_path / "failure-log.jsonl",
        )
        event = ErrorEvent(
            bot_id="bot1", error_type="DeprecationWarning",
            message="module X is deprecated",
            stack_trace="...",
        )
        result = runner.triage(event)
        assert result.severity == BugSeverity.LOW
        assert result.outcome == TriageOutcome.QUEUED_FOR_WEEKLY


class TestTriageRunnerWithRepeatedErrors:
    def test_repeated_errors_promote_to_high(self, tmp_path: Path):
        runner = TriageRunner(
            source_root=tmp_path,
            failure_log_path=tmp_path / "failure-log.jsonl",
            repeated_error_threshold=3,
        )
        event = ErrorEvent(
            bot_id="bot1", error_type="RuntimeError",
            message="some recurring error",
            stack_trace="...",
        )
        # Record multiple errors to trigger promotion
        for _ in range(3):
            runner.record_error(event)

        result = runner.triage(event)
        assert result.severity == BugSeverity.HIGH


class TestTriageRunnerRecordsToFailureLog:
    def test_triage_records_to_log(self, tmp_path: Path):
        log_path = tmp_path / "failure-log.jsonl"
        runner = TriageRunner(
            source_root=tmp_path,
            failure_log_path=log_path,
        )
        event = ErrorEvent(
            bot_id="bot1", error_type="RuntimeError",
            message="fail", stack_trace="...",
        )
        runner.triage(event)
        assert log_path.exists()
        lines = log_path.read_text().strip().splitlines()
        assert len(lines) == 1


class TestTriageRunnerPastRejections:
    def test_includes_past_rejections_in_result(self, tmp_path: Path):
        log_path = tmp_path / "failure-log.jsonl"
        runner = TriageRunner(
            source_root=tmp_path,
            failure_log_path=log_path,
        )
        # Seed a past rejection
        from skills.failure_log import FailureLog
        fl = FailureLog(log_path)
        fl.record_rejection(
            TriageResult(
                error_event=ErrorEvent(
                    bot_id="bot1", error_type="ImportError",
                    message="no foo", stack_trace="s",
                ),
                severity=BugSeverity.HIGH,
                complexity=BugComplexity.OBVIOUS_FIX,
                outcome=TriageOutcome.KNOWN_FIX,
            ),
            reason="wrong version",
        )

        event = ErrorEvent(
            bot_id="bot1", error_type="ImportError",
            message="no foo", stack_trace="s",
        )
        result = runner.triage(event, severity_override=BugSeverity.HIGH)
        assert len(result.past_rejections) >= 1
        assert any("wrong version" in r for r in result.past_rejections)
```

**Step 2: Implement the triage runner**

```python
# skills/run_bug_triage.py
"""Triage runner — main bug triage pipeline.

Orchestrates: severity classification → error rate check → complexity classification →
outcome routing → failure log recording → context building.

This is the skill the orchestrator worker calls when it receives a SPAWN_TRIAGE action.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from schemas.bug_triage import (
    BugSeverity,
    ErrorEvent,
    TriageOutcome,
    TriageResult,
)
from skills.bug_complexity_classifier import BugComplexityClassifier
from skills.error_rate_tracker import ErrorRateTracker
from skills.failure_log import FailureLog
from skills.severity_classifier import SeverityClassifier
from skills.triage_context_builder import TriageContextBuilder


class TriageRunner:
    """Main triage pipeline — the entry point for bug triage."""

    def __init__(
        self,
        source_root: Path,
        failure_log_path: Path,
        repeated_error_threshold: int = 3,
        error_rate_window_seconds: int = 3600,
    ) -> None:
        self._severity_classifier = SeverityClassifier()
        self._complexity_classifier = BugComplexityClassifier()
        self._error_rate_tracker = ErrorRateTracker(
            window_seconds=error_rate_window_seconds,
            threshold=repeated_error_threshold,
        )
        self._failure_log = FailureLog(failure_log_path)
        self._context_builder = TriageContextBuilder(source_root=source_root)

    def record_error(self, event: ErrorEvent) -> None:
        """Record an error for rate tracking (called by worker on every error event)."""
        self._error_rate_tracker.record(event)

    def triage(
        self,
        event: ErrorEvent,
        severity_override: Optional[BugSeverity] = None,
    ) -> TriageResult:
        """Run the full triage pipeline for an error event.

        Args:
            event: The error event to triage.
            severity_override: If set, skip severity classification and use this value.
        """
        # Step 1: Classify severity
        if severity_override is not None:
            severity = severity_override
            classification = self._severity_classifier.classify(event)
            category = classification.category
        else:
            classification = self._severity_classifier.classify(event)
            severity = classification.severity
            category = classification.category

            # Step 2: Check error rate — promote to HIGH if repeated
            if severity.rank < BugSeverity.HIGH.rank and self._error_rate_tracker.is_repeated(event.bot_id):
                severity = BugSeverity.HIGH

        # Step 3: Load past rejections
        past_rejections = self._failure_log.get_past_rejections(
            error_type=event.error_type, limit=5,
        )
        rejection_texts = [r.rejection_reason for r in past_rejections if r.rejection_reason]

        # Step 4: Classify complexity and determine outcome
        complexity_result = self._complexity_classifier.classify(event, severity, category)

        # Step 5: Build triage result
        result = TriageResult(
            error_event=event,
            severity=severity,
            complexity=complexity_result.complexity,
            outcome=complexity_result.outcome,
            past_rejections=rejection_texts,
        )

        # Step 6: Record to failure log
        self._failure_log.record_triage(result)

        return result
```

**Step 3: Run tests**

```bash
pytest tests/test_triage_runner.py -v
```

Expected: All tests PASS.

**Step 4: Commit**

```bash
git add skills/run_bug_triage.py tests/test_triage_runner.py
git commit -m "feat(phase5): add triage runner — main bug triage pipeline"
```

---

## Task 11: Orchestrator Wiring

**Files:**
- Modify: `orchestrator/orchestrator_brain.py`
- Modify: `orchestrator/worker.py`
- Modify: `orchestrator/scheduler.py`
- Test: `tests/test_bug_triage_orchestrator_wiring.py`

**Step 1: Write the failing test**

```python
# tests/test_bug_triage_orchestrator_wiring.py
"""Tests for Phase 5 orchestrator wiring — brain + worker + scheduler."""
import json
import pytest

from orchestrator.orchestrator_brain import OrchestratorBrain, ActionType
from orchestrator.scheduler import SchedulerConfig, create_scheduler_jobs


class TestBrainErrorRouting:
    """The brain already handles error events, but now we test the full severity spectrum."""

    def test_critical_error_produces_alert(self):
        brain = OrchestratorBrain()
        event = {
            "event_id": "e1",
            "bot_id": "bot1",
            "event_type": "error",
            "payload": json.dumps({
                "severity": "CRITICAL",
                "error_type": "SystemExit",
                "message": "crash",
            }),
        }
        actions = brain.decide(event)
        assert len(actions) == 1
        assert actions[0].type == ActionType.ALERT_IMMEDIATE

    def test_high_error_spawns_triage(self):
        brain = OrchestratorBrain()
        event = {
            "event_id": "e2",
            "bot_id": "bot1",
            "event_type": "error",
            "payload": json.dumps({"severity": "HIGH"}),
        }
        actions = brain.decide(event)
        assert len(actions) == 1
        assert actions[0].type == ActionType.SPAWN_TRIAGE

    def test_medium_error_queues_for_daily(self):
        brain = OrchestratorBrain()
        event = {
            "event_id": "e3",
            "bot_id": "bot1",
            "event_type": "error",
            "payload": json.dumps({"severity": "MEDIUM"}),
        }
        actions = brain.decide(event)
        assert len(actions) == 1
        assert actions[0].type == ActionType.QUEUE_FOR_DAILY

    def test_low_error_queues_for_weekly(self):
        brain = OrchestratorBrain()
        event = {
            "event_id": "e4",
            "bot_id": "bot1",
            "event_type": "error",
            "payload": json.dumps({"severity": "LOW"}),
        }
        actions = brain.decide(event)
        assert len(actions) == 1
        assert actions[0].type == ActionType.QUEUE_FOR_WEEKLY


class TestSchedulerStaleErrorSweep:
    def test_config_has_stale_error_sweep_fields(self):
        config = SchedulerConfig()
        assert hasattr(config, "stale_error_sweep_interval_seconds")
        assert config.stale_error_sweep_interval_seconds == 600  # 10 min default

    def test_stale_error_sweep_job_created(self):
        config = SchedulerConfig()

        async def noop():
            pass

        jobs = create_scheduler_jobs(
            config,
            worker_fn=noop,
            monitoring_fn=noop,
            relay_fn=noop,
            stale_error_sweep_fn=noop,
        )
        job_names = [j["name"] for j in jobs]
        assert "stale_error_sweep" in job_names

    def test_stale_error_sweep_not_created_without_fn(self):
        config = SchedulerConfig()

        async def noop():
            pass

        jobs = create_scheduler_jobs(
            config,
            worker_fn=noop,
            monitoring_fn=noop,
            relay_fn=noop,
        )
        job_names = [j["name"] for j in jobs]
        assert "stale_error_sweep" not in job_names
```

**Step 2: Apply modifications**

**Modify `orchestrator/orchestrator_brain.py`:** Add `QUEUE_FOR_WEEKLY` action type and enhance error routing.

Add to `ActionType` enum:
```python
QUEUE_FOR_WEEKLY = "queue_for_weekly"
```

Replace `_handle_error` method:
```python
def _handle_error(self, event_id: str, bot_id: str, event: dict) -> list[Action]:
    payload = json.loads(event.get("payload", "{}"))
    severity = payload.get("severity", "MEDIUM").upper()

    if severity == "CRITICAL":
        return [
            Action(type=ActionType.ALERT_IMMEDIATE, event_id=event_id, bot_id=bot_id, details=payload),
        ]
    elif severity == "HIGH":
        return [
            Action(type=ActionType.SPAWN_TRIAGE, event_id=event_id, bot_id=bot_id, details=payload),
        ]
    elif severity == "LOW":
        return [Action(type=ActionType.QUEUE_FOR_WEEKLY, event_id=event_id, bot_id=bot_id)]
    else:  # MEDIUM or unrecognized
        return [Action(type=ActionType.QUEUE_FOR_DAILY, event_id=event_id, bot_id=bot_id)]
```

**Modify `orchestrator/worker.py`:** Add `QUEUE_FOR_WEEKLY` dispatch.

Add to `_dispatch`:
```python
elif action.type == ActionType.QUEUE_FOR_WEEKLY:
    logger.debug("Queued for weekly: %s", action.event_id)
```

**Modify `orchestrator/scheduler.py`:** Add stale error sweep config and job.

Add field to `SchedulerConfig`:
```python
stale_error_sweep_interval_seconds: int = 600
```

Add parameter and job to `create_scheduler_jobs`:
```python
stale_error_sweep_fn: Callable[[], Awaitable[None]] | None = None,
```

```python
if stale_error_sweep_fn is not None:
    jobs.append({
        "name": "stale_error_sweep",
        "func": stale_error_sweep_fn,
        "trigger": "interval",
        "seconds": config.stale_error_sweep_interval_seconds,
    })
```

**Step 3: Run tests**

```bash
pytest tests/test_bug_triage_orchestrator_wiring.py -v
```

Expected: All tests PASS.

**Step 4: Run full test suite to ensure no regressions**

```bash
pytest --tb=short -q
```

Expected: All existing tests still PASS.

**Step 5: Commit**

```bash
git add orchestrator/orchestrator_brain.py orchestrator/worker.py orchestrator/scheduler.py tests/test_bug_triage_orchestrator_wiring.py
git commit -m "feat(phase5): wire up orchestrator — enhanced error routing + weekly queue + stale sweep"
```

---

## Task 12: Integration Test

**Files:**
- Create: `tests/test_bug_triage_integration.py`

**Step 1: Write the integration test**

```python
# tests/test_bug_triage_integration.py
"""Integration test — full bug triage pipeline end-to-end."""
import json
from pathlib import Path

from schemas.bug_triage import (
    BugSeverity,
    BugComplexity,
    ErrorEvent,
    TriageOutcome,
    TriageResult,
)
from schemas.pr_review import PRReviewStatus, TradingSafetyCheck
from skills.run_bug_triage import TriageRunner
from skills.failure_log import FailureLog
from skills.pr_review_checker import PRReviewChecker
from analysis.triage_prompt_assembler import TriagePromptAssembler
from analysis.pr_report_builder import PRReportBuilder


class TestFullTriagePipeline:
    """End-to-end: error event → triage → context → prompt → result."""

    def test_critical_crash_flow(self, tmp_path: Path):
        """CRITICAL crash → ALERTED, no auto-fix attempted."""
        runner = TriageRunner(
            source_root=tmp_path,
            failure_log_path=tmp_path / "failure-log.jsonl",
        )
        event = ErrorEvent(
            bot_id="bot1", error_type="SystemExit",
            message="SIGSEGV in trade loop",
            stack_trace="Traceback:\n  File trade_loop.py:42\nSystemExit: SIGSEGV",
            context={"crash": True},
        )
        result = runner.triage(event)

        assert result.severity == BugSeverity.CRITICAL
        assert result.outcome == TriageOutcome.ALERTED
        # Verify it was logged
        log_lines = (tmp_path / "failure-log.jsonl").read_text().strip().splitlines()
        assert len(log_lines) == 1
        logged = json.loads(log_lines[0])
        assert logged["outcome"] == "alerted"

    def test_high_obvious_fix_flow(self, tmp_path: Path):
        """HIGH + OBVIOUS_FIX → KNOWN_FIX, context built for auto-fix agent."""
        runner = TriageRunner(
            source_root=tmp_path,
            failure_log_path=tmp_path / "failure-log.jsonl",
        )
        event = ErrorEvent(
            bot_id="bot2", error_type="ImportError",
            message="No module named 'ccxt'",
            stack_trace="Traceback:\n  File connector.py:1\nImportError: No module named 'ccxt'",
        )
        result = runner.triage(event, severity_override=BugSeverity.HIGH)

        assert result.severity == BugSeverity.HIGH
        assert result.outcome == TriageOutcome.KNOWN_FIX
        assert result.complexity == BugComplexity.OBVIOUS_FIX

        # Build triage context for the fix agent
        asm = TriagePromptAssembler(memory_dir=tmp_path)
        from skills.triage_context_builder import TriageContextBuilder
        ctx_builder = TriageContextBuilder(source_root=tmp_path)
        ctx = ctx_builder.build(
            event, result.severity,
            result.error_event.category or "unknown",
            [],
        )
        prompt_pkg = asm.assemble(ctx, result.severity, result.complexity)
        assert "HIGH" in prompt_pkg["task_prompt"]
        assert "obvious_fix" in prompt_pkg["task_prompt"]

    def test_repeated_errors_promote_severity(self, tmp_path: Path):
        """MEDIUM errors repeated >3/hour → promoted to HIGH → NEEDS_INVESTIGATION."""
        runner = TriageRunner(
            source_root=tmp_path,
            failure_log_path=tmp_path / "failure-log.jsonl",
            repeated_error_threshold=3,
        )
        event = ErrorEvent(
            bot_id="bot3", error_type="RuntimeError",
            message="index out of range",
            stack_trace='Traceback:\n  File "algo.py", line 20\nRuntimeError: index out of range',
            source_file="algo.py",
            source_line=20,
        )

        # First triage: MEDIUM
        first = runner.triage(event)
        assert first.severity == BugSeverity.MEDIUM

        # Record 3 errors to trigger promotion
        for _ in range(3):
            runner.record_error(event)

        # Second triage: promoted to HIGH
        second = runner.triage(event)
        assert second.severity == BugSeverity.HIGH

    def test_ralph_loop_rejection_feedback(self, tmp_path: Path):
        """PR rejection → failure log → next triage includes past rejection."""
        log_path = tmp_path / "failure-log.jsonl"
        runner = TriageRunner(
            source_root=tmp_path,
            failure_log_path=log_path,
        )

        # First triage produces a KNOWN_FIX
        event = ErrorEvent(
            bot_id="bot1", error_type="ImportError",
            message="no module pandas",
            stack_trace="...",
        )
        first = runner.triage(event, severity_override=BugSeverity.HIGH)
        assert first.outcome == TriageOutcome.KNOWN_FIX

        # Human rejects the PR
        failure_log = FailureLog(log_path)
        failure_log.record_rejection(first, reason="should use polars, not pandas")

        # Next triage for same error type includes the rejection
        second = runner.triage(event, severity_override=BugSeverity.HIGH)
        assert any("polars" in r for r in second.past_rejections)


class TestPRReviewPipeline:
    """End-to-end: PR → review checker → report builder."""

    def test_safe_pr_passes_review(self):
        checker = PRReviewChecker(permission_config={
            "permission_tiers": {
                "auto": {"file_paths": ["tests/*", "*.md"]},
                "requires_approval": {"file_paths": ["skills/*"]},
                "requires_double_approval": {"file_paths": ["orchestrator/*"]},
            }
        })
        result = checker.run_review(
            pr_url="https://github.com/user/repo/pull/42",
            changed_files=["tests/test_foo.py"],
            diff_content="+ def test_new(): assert True",
            ci_passed=True,
        )
        assert result.overall_passed is True

        # Build human-readable report
        md = PRReportBuilder.build_markdown(result)
        assert "PASSED" in md
        assert "pull/42" in md

    def test_dangerous_pr_fails_review(self):
        checker = PRReviewChecker(permission_config={
            "permission_tiers": {
                "auto": {"file_paths": ["tests/*"]},
                "requires_approval": {},
                "requires_double_approval": {"file_paths": ["orchestrator/*"]},
            }
        })
        result = checker.run_review(
            pr_url="https://github.com/user/repo/pull/99",
            changed_files=["orchestrator/kill_switch.py"],
            diff_content="- kill_switch_enabled = True\n+ kill_switch_enabled = False",
            ci_passed=True,
        )
        assert result.overall_passed is False

        md = PRReportBuilder.build_markdown(result)
        assert "FAIL" in md or "BLOCKED" in md


class TestFullPipelineCount:
    """Verify the full pipeline produces the expected number of components."""

    def test_all_components_importable(self):
        """Smoke test: all Phase 5 modules can be imported."""
        from schemas import bug_triage  # noqa: F401
        from schemas import pr_review  # noqa: F401
        from skills import severity_classifier  # noqa: F401
        from skills import error_rate_tracker  # noqa: F401
        from skills import bug_complexity_classifier  # noqa: F401
        from skills import failure_log  # noqa: F401
        from skills import triage_context_builder  # noqa: F401
        from skills import pr_review_checker  # noqa: F401
        from skills import run_bug_triage  # noqa: F401
        from analysis import triage_prompt_assembler  # noqa: F401
        from analysis import pr_report_builder  # noqa: F401
```

**Step 2: Run the integration test**

```bash
pytest tests/test_bug_triage_integration.py -v
```

Expected: All tests PASS.

**Step 3: Run the full test suite**

```bash
pytest --tb=short -q
```

Expected: ALL tests across all phases PASS (no regressions).

**Step 4: Commit**

```bash
git add tests/test_bug_triage_integration.py
git commit -m "feat(phase5): add integration tests — full triage pipeline + PR review end-to-end"
```

---

## Summary

| Task | Component | Files Created | Tests |
|------|-----------|---------------|-------|
| 0 | Bug Triage Schemas | `schemas/bug_triage.py` | ~12 |
| 1 | PR Review Schemas | `schemas/pr_review.py` | ~10 |
| 2 | Severity Classifier | `skills/severity_classifier.py` | ~10 |
| 3 | Error Rate Tracker | `skills/error_rate_tracker.py` | ~7 |
| 4 | Bug Complexity Classifier | `skills/bug_complexity_classifier.py` | ~9 |
| 5 | Failure Log | `skills/failure_log.py` | ~8 |
| 6 | Triage Context Builder | `skills/triage_context_builder.py` | ~5 |
| 7 | PR Review Checker | `skills/pr_review_checker.py` | ~10 |
| 8 | Triage Prompt Assembler | `analysis/triage_prompt_assembler.py` | ~7 |
| 9 | PR Report Builder | `analysis/pr_report_builder.py` | ~4 |
| 10 | Triage Runner | `skills/run_bug_triage.py` | ~8 |
| 11 | Orchestrator Wiring | (modify 3 files) | ~5 |
| 12 | Integration Test | `tests/test_bug_triage_integration.py` | ~7 |
| **Total** | **13 tasks** | **11 new + 3 modified** | **~102** |
