# Phase 6: Communication + Experience Layer — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a multi-channel notification system (Telegram, Discord, Email) with a pinned Telegram control surface, proactive alerting, and a shared rendering layer — so that daily reports, weekly summaries, alerts, and approval flows are delivered to the right channel at the right time with the right format.

**Architecture:** A shared `MessageRenderer` protocol defines how report data (daily metrics, weekly summaries, alerts, WFO reports, triage results) gets transformed into channel-specific formats. Each channel (Telegram, Discord, Email) has a renderer and a bot/client adapter. A `NotificationDispatcher` routes notifications to the correct channels based on user preferences, priority, and quiet hours. Telegram gets a "pinned control surface" — one message per day with inline keyboard buttons, updated in-place. Proactive notifications integrate with the existing scheduler and monitoring loop. The Worker's existing pluggable callbacks (`on_alert`, `on_daily_analysis`, etc.) wire into the dispatcher.

**Tech Stack:** Python 3.12, Pydantic v2, pytest, python-telegram-bot (async), discord.py (async), aiosmtplib, jinja2 (email templates), FastAPI (existing)

**Assumes:** Phases 1–5 are fully implemented — event queue, task registry, orchestrator brain/worker/scheduler, permission gates, daily/weekly metrics, WFO pipeline, bug triage pipeline, and all schemas exist and pass tests. The Worker already has pluggable callbacks for `on_alert`, `on_daily_analysis`, `on_weekly_analysis`, `on_wfo`. The monitoring loop already produces `Alert` objects. The existing report builders (pr_report_builder, wfo_report_builder) already produce markdown.

**Directory structure this plan creates:**

```
trading_assistant/
  schemas/
    notifications.py           # NotificationChannel, NotificationPriority, NotificationPreferences, ControlPanelState, NotificationPayload
  comms/
    __init__.py
    renderer.py                # MessageRenderer protocol + PlainTextRenderer
    telegram_renderer.py       # TelegramRenderer — MarkdownV2 formatting + inline keyboards
    telegram_bot.py            # TelegramBotAdapter — bot lifecycle, send/edit/pin
    telegram_control_surface.py  # ControlSurface — daily pinned message management
    telegram_handlers.py       # Button callback routing + slash command fallback
    discord_renderer.py        # DiscordRenderer — embed formatting
    discord_bot.py             # DiscordBotAdapter — bot lifecycle, send embed, create thread
    email_renderer.py          # EmailRenderer — HTML templates via Jinja2
    email_adapter.py           # EmailAdapter — async SMTP send
    dispatcher.py              # NotificationDispatcher — routes to channels by preference
  skills/
    proactive_scanner.py       # ProactiveScanner — morning scan, continuous alerts, evening trigger
  orchestrator/
    orchestrator_brain.py      # MODIFY: add SEND_NOTIFICATION action type
    worker.py                  # MODIFY: wire on_alert/on_daily_analysis through dispatcher
    scheduler.py               # MODIFY: add morning_scan_hour, evening_report_hour config
    app.py                     # MODIFY: add /notifications/preferences endpoint
  tests/
    test_notification_schemas.py
    test_renderer.py
    test_telegram_renderer.py
    test_telegram_bot.py
    test_telegram_control_surface.py
    test_telegram_handlers.py
    test_discord_renderer.py
    test_discord_bot.py
    test_email_renderer.py
    test_email_adapter.py
    test_dispatcher.py
    test_proactive_scanner.py
    test_comms_orchestrator_wiring.py
    test_comms_integration.py
```

---

## Task 0: Notification Schemas

**Files:**
- Create: `schemas/notifications.py`
- Test: `tests/test_notification_schemas.py`

**Step 1: Write the failing test**

```python
# tests/test_notification_schemas.py
"""Tests for notification schemas."""
from datetime import datetime, timezone

from schemas.notifications import (
    NotificationChannel,
    NotificationPriority,
    NotificationPreferences,
    ChannelConfig,
    ControlPanelState,
    NotificationPayload,
    BotStatusLine,
)


class TestNotificationChannel:
    def test_all_channels_exist(self):
        assert NotificationChannel.TELEGRAM == "telegram"
        assert NotificationChannel.DISCORD == "discord"
        assert NotificationChannel.EMAIL == "email"


class TestNotificationPriority:
    def test_all_priorities_exist(self):
        assert NotificationPriority.CRITICAL == "critical"
        assert NotificationPriority.HIGH == "high"
        assert NotificationPriority.NORMAL == "normal"
        assert NotificationPriority.LOW == "low"

    def test_ordering(self):
        ordered = sorted(NotificationPriority, key=lambda p: p.rank, reverse=True)
        assert ordered[0] == NotificationPriority.CRITICAL
        assert ordered[-1] == NotificationPriority.LOW

    def test_critical_bypasses_quiet_hours(self):
        assert NotificationPriority.CRITICAL.bypasses_quiet_hours is True
        assert NotificationPriority.HIGH.bypasses_quiet_hours is False
        assert NotificationPriority.NORMAL.bypasses_quiet_hours is False
        assert NotificationPriority.LOW.bypasses_quiet_hours is False


class TestChannelConfig:
    def test_defaults(self):
        cfg = ChannelConfig(channel=NotificationChannel.TELEGRAM)
        assert cfg.enabled is True
        assert cfg.chat_id == ""
        assert cfg.quiet_hours_start is None
        assert cfg.quiet_hours_end is None

    def test_is_quiet_during_quiet_hours(self):
        cfg = ChannelConfig(
            channel=NotificationChannel.TELEGRAM,
            quiet_hours_start=22,
            quiet_hours_end=8,
        )
        # 23:00 UTC → quiet
        assert cfg.is_quiet_at(23) is True
        # 03:00 UTC → quiet
        assert cfg.is_quiet_at(3) is True
        # 12:00 UTC → not quiet
        assert cfg.is_quiet_at(12) is False
        # 8:00 UTC → boundary, not quiet (end is exclusive)
        assert cfg.is_quiet_at(8) is False

    def test_no_quiet_hours(self):
        cfg = ChannelConfig(channel=NotificationChannel.TELEGRAM)
        assert cfg.is_quiet_at(3) is False


class TestNotificationPreferences:
    def test_default_channels(self):
        prefs = NotificationPreferences()
        assert len(prefs.channels) == 0

    def test_add_channel(self):
        prefs = NotificationPreferences(
            channels=[
                ChannelConfig(channel=NotificationChannel.TELEGRAM, chat_id="12345"),
            ]
        )
        assert len(prefs.channels) == 1
        assert prefs.channels[0].chat_id == "12345"

    def test_get_active_channels(self):
        prefs = NotificationPreferences(
            channels=[
                ChannelConfig(channel=NotificationChannel.TELEGRAM, enabled=True),
                ChannelConfig(channel=NotificationChannel.DISCORD, enabled=False),
                ChannelConfig(channel=NotificationChannel.EMAIL, enabled=True),
            ]
        )
        active = prefs.get_active_channels()
        assert len(active) == 2
        assert active[0].channel == NotificationChannel.TELEGRAM
        assert active[1].channel == NotificationChannel.EMAIL

    def test_get_channels_for_priority_respects_quiet_hours(self):
        prefs = NotificationPreferences(
            channels=[
                ChannelConfig(
                    channel=NotificationChannel.TELEGRAM,
                    quiet_hours_start=22,
                    quiet_hours_end=8,
                ),
            ]
        )
        # During quiet hours, NORMAL priority → no channels
        channels = prefs.get_channels_for_priority(NotificationPriority.NORMAL, current_hour_utc=3)
        assert len(channels) == 0

        # During quiet hours, CRITICAL → still gets through
        channels = prefs.get_channels_for_priority(NotificationPriority.CRITICAL, current_hour_utc=3)
        assert len(channels) == 1


class TestBotStatusLine:
    def test_status_emoji(self):
        green = BotStatusLine(bot_id="bot1", status="green", pnl=210.0, wins=4, losses=1, summary="Strong trend")
        assert green.status_emoji == "🟢"

        yellow = BotStatusLine(bot_id="bot2", status="yellow", pnl=82.0, wins=3, losses=2, summary="Normal losses")
        assert yellow.status_emoji == "🟡"

        red = BotStatusLine(bot_id="bot3", status="red", pnl=50.0, wins=2, losses=3, summary="Filter issues")
        assert red.status_emoji == "🔴"


class TestControlPanelState:
    def test_full_panel(self):
        panel = ControlPanelState(
            date="2026-03-01",
            portfolio_pnl=342.0,
            portfolio_pnl_pct=1.2,
            drawdown_pct=-0.3,
            exposure_pct=47.0,
            daily_report_ready=True,
            alert_count=1,
            alert_summary="Bot3 volume filter",
            wfo_status="Bot2 running (est. 45min)",
            pending_pr_count=0,
            risk_status="OK",
            risk_detail="concentration: 35/100",
            bot_statuses=[
                BotStatusLine(bot_id="bot1", status="green", pnl=210.0, wins=4, losses=1, summary="Strong trend"),
            ],
        )
        assert panel.date == "2026-03-01"
        assert panel.portfolio_pnl == 342.0
        assert panel.daily_report_ready is True
        assert panel.alert_count == 1
        assert len(panel.bot_statuses) == 1


class TestNotificationPayload:
    def test_minimal_payload(self):
        payload = NotificationPayload(
            notification_type="daily_report",
            priority=NotificationPriority.NORMAL,
            title="Daily Report — March 1, 2026",
            body="Portfolio: +$342 (+1.2%)",
        )
        assert payload.notification_type == "daily_report"
        assert payload.priority == NotificationPriority.NORMAL
        assert payload.attachments == []

    def test_payload_with_data(self):
        payload = NotificationPayload(
            notification_type="alert",
            priority=NotificationPriority.CRITICAL,
            title="Bot3 crash",
            body="RuntimeError in signal handler",
            data={"bot_id": "bot3", "error_type": "RuntimeError"},
        )
        assert payload.data["bot_id"] == "bot3"
        assert payload.priority == NotificationPriority.CRITICAL

    def test_payload_with_attachments(self):
        payload = NotificationPayload(
            notification_type="weekly_digest",
            priority=NotificationPriority.LOW,
            title="Weekly Digest",
            body="Summary",
            attachments=["reports/weekly_2026-03-01.md", "reports/wfo_bot2.md"],
        )
        assert len(payload.attachments) == 2
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_notification_schemas.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'schemas.notifications'`

**Step 3: Write minimal implementation**

```python
# schemas/notifications.py
"""Notification schemas — channels, preferences, control panel state, payloads.

Used by the communication layer (comms/) to route notifications to the right
channel with the right priority and format.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class NotificationChannel(str, Enum):
    TELEGRAM = "telegram"
    DISCORD = "discord"
    EMAIL = "email"


class NotificationPriority(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"

    @property
    def rank(self) -> int:
        return {"critical": 4, "high": 3, "normal": 2, "low": 1}[self.value]

    @property
    def bypasses_quiet_hours(self) -> bool:
        return self == NotificationPriority.CRITICAL


class ChannelConfig(BaseModel):
    """Per-channel notification configuration."""

    channel: NotificationChannel
    enabled: bool = True
    chat_id: str = ""          # Telegram chat ID, Discord channel ID, or email address
    quiet_hours_start: Optional[int] = None  # UTC hour (0-23), None = no quiet hours
    quiet_hours_end: Optional[int] = None    # UTC hour (0-23)

    def is_quiet_at(self, hour_utc: int) -> bool:
        """Check if the given UTC hour falls within quiet hours."""
        if self.quiet_hours_start is None or self.quiet_hours_end is None:
            return False
        start = self.quiet_hours_start
        end = self.quiet_hours_end
        if start <= end:
            return start <= hour_utc < end
        else:
            # Wraps midnight: e.g. 22-8 means 22,23,0,1,...,7 are quiet
            return hour_utc >= start or hour_utc < end


class NotificationPreferences(BaseModel):
    """User notification preferences across all channels."""

    channels: list[ChannelConfig] = []

    def get_active_channels(self) -> list[ChannelConfig]:
        return [c for c in self.channels if c.enabled]

    def get_channels_for_priority(
        self,
        priority: NotificationPriority,
        current_hour_utc: int,
    ) -> list[ChannelConfig]:
        """Return channels that should receive a notification of this priority right now."""
        result: list[ChannelConfig] = []
        for cfg in self.channels:
            if not cfg.enabled:
                continue
            if cfg.is_quiet_at(current_hour_utc) and not priority.bypasses_quiet_hours:
                continue
            result.append(cfg)
        return result


class BotStatusLine(BaseModel):
    """Single bot status for the control panel."""

    bot_id: str
    status: str  # green | yellow | red
    pnl: float = 0.0
    wins: int = 0
    losses: int = 0
    summary: str = ""

    @property
    def status_emoji(self) -> str:
        return {"green": "🟢", "yellow": "🟡", "red": "🔴"}.get(self.status, "⚪")


class ControlPanelState(BaseModel):
    """State of the daily pinned control surface message."""

    date: str  # YYYY-MM-DD
    portfolio_pnl: float = 0.0
    portfolio_pnl_pct: float = 0.0
    drawdown_pct: float = 0.0
    exposure_pct: float = 0.0
    daily_report_ready: bool = False
    alert_count: int = 0
    alert_summary: str = ""
    wfo_status: str = ""       # e.g. "Bot2 running (est. 45min)" or ""
    pending_pr_count: int = 0
    risk_status: str = "OK"    # OK | WARNING | CRITICAL
    risk_detail: str = ""
    bot_statuses: list[BotStatusLine] = []


class NotificationPayload(BaseModel):
    """Generic notification payload that renderers transform into channel-specific format."""

    notification_type: str     # daily_report | weekly_summary | alert | wfo_report | triage_result | control_panel | bot_status | approval_request
    priority: NotificationPriority = NotificationPriority.NORMAL
    title: str = ""
    body: str = ""
    data: dict = {}            # type-specific structured data (e.g. ControlPanelState.model_dump())
    attachments: list[str] = []  # file paths for email/discord
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_notification_schemas.py -v`
Expected: All 16 tests PASS

**Step 5: Commit**

```bash
git add schemas/notifications.py tests/test_notification_schemas.py
git commit -m "feat(phase6): add notification schemas — channels, preferences, control panel, payloads"
```

---

## Task 1: Message Renderer Protocol + Plain Text Renderer

**Files:**
- Create: `comms/__init__.py`
- Create: `comms/renderer.py`
- Test: `tests/test_renderer.py`

**Step 1: Write the failing test**

```python
# tests/test_renderer.py
"""Tests for message renderer protocol and plain text renderer."""
from schemas.notifications import (
    ControlPanelState,
    BotStatusLine,
    NotificationPayload,
    NotificationPriority,
)
from comms.renderer import MessageRenderer, PlainTextRenderer


class TestMessageRendererProtocol:
    def test_plain_text_renderer_implements_protocol(self):
        renderer = PlainTextRenderer()
        assert isinstance(renderer, MessageRenderer)


class TestPlainTextRenderControlPanel:
    def test_renders_full_panel(self):
        panel = ControlPanelState(
            date="2026-03-01",
            portfolio_pnl=342.0,
            portfolio_pnl_pct=1.2,
            drawdown_pct=-0.3,
            exposure_pct=47.0,
            daily_report_ready=True,
            alert_count=1,
            alert_summary="Bot3 volume filter",
            wfo_status="Bot2 running (est. 45min)",
            pending_pr_count=0,
            risk_status="OK",
            risk_detail="concentration: 35/100",
            bot_statuses=[
                BotStatusLine(bot_id="Bot1", status="green", pnl=210.0, wins=4, losses=1, summary="Strong trend"),
                BotStatusLine(bot_id="Bot2", status="yellow", pnl=82.0, wins=3, losses=2, summary="Normal losses"),
            ],
        )
        result = PlainTextRenderer().render_control_panel(panel)
        assert "March 1, 2026" in result or "2026-03-01" in result
        assert "+$342" in result or "342" in result
        assert "Bot3 volume filter" in result
        assert "Bot1" in result
        assert "Bot2" in result

    def test_renders_empty_panel(self):
        panel = ControlPanelState(date="2026-03-01")
        result = PlainTextRenderer().render_control_panel(panel)
        assert "2026-03-01" in result


class TestPlainTextRenderAlert:
    def test_renders_critical_alert(self):
        payload = NotificationPayload(
            notification_type="alert",
            priority=NotificationPriority.CRITICAL,
            title="Bot3 crash",
            body="RuntimeError in signal handler",
            data={"bot_id": "bot3"},
        )
        result = PlainTextRenderer().render_alert(payload)
        assert "CRITICAL" in result
        assert "Bot3 crash" in result
        assert "RuntimeError" in result

    def test_renders_medium_alert(self):
        payload = NotificationPayload(
            notification_type="alert",
            priority=NotificationPriority.NORMAL,
            title="Minor issue",
            body="Slow API response",
        )
        result = PlainTextRenderer().render_alert(payload)
        assert "Minor issue" in result


class TestPlainTextRenderDailyReport:
    def test_renders_daily_report_body(self):
        payload = NotificationPayload(
            notification_type="daily_report",
            priority=NotificationPriority.NORMAL,
            title="Daily Report — March 1, 2026",
            body="Portfolio: +$342 (+1.2%) | DD: -0.3%\n\nBot1: +$210 (4W/1L)",
        )
        result = PlainTextRenderer().render_daily_report(payload)
        assert "Daily Report" in result
        assert "+$342" in result or "342" in result
        assert "Bot1" in result

    def test_renders_daily_report_with_data(self):
        payload = NotificationPayload(
            notification_type="daily_report",
            title="Daily Report",
            body="Summary",
            data={"bot_statuses": [{"bot_id": "bot1", "pnl": 100}]},
        )
        result = PlainTextRenderer().render_daily_report(payload)
        assert "Daily Report" in result


class TestPlainTextRenderWeeklySummary:
    def test_renders_weekly_summary(self):
        payload = NotificationPayload(
            notification_type="weekly_summary",
            title="Weekly Summary — Feb 24–Mar 1",
            body="Total PnL: +$1,200\n3 bots active",
        )
        result = PlainTextRenderer().render_weekly_summary(payload)
        assert "Weekly Summary" in result
        assert "$1,200" in result or "1,200" in result


class TestPlainTextRenderGeneric:
    def test_render_dispatches_by_type(self):
        """The generic render() method should dispatch to the right renderer."""
        renderer = PlainTextRenderer()
        payload = NotificationPayload(
            notification_type="alert",
            priority=NotificationPriority.CRITICAL,
            title="Test",
            body="Test body",
        )
        result = renderer.render(payload)
        assert "CRITICAL" in result
        assert "Test" in result

    def test_render_unknown_type_falls_back(self):
        renderer = PlainTextRenderer()
        payload = NotificationPayload(
            notification_type="unknown_type",
            title="Something",
            body="Details here",
        )
        result = renderer.render(payload)
        assert "Something" in result
        assert "Details here" in result
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_renderer.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'comms'`

**Step 3: Write minimal implementation**

```python
# comms/__init__.py
```

```python
# comms/renderer.py
"""Message renderer protocol and plain text implementation.

The MessageRenderer protocol defines how notification payloads get
transformed into channel-specific text. Each channel adapter (Telegram,
Discord, Email) provides its own renderer.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from schemas.notifications import ControlPanelState, NotificationPayload, NotificationPriority


@runtime_checkable
class MessageRenderer(Protocol):
    """Protocol for rendering notifications to a specific channel format."""

    def render(self, payload: NotificationPayload) -> str: ...
    def render_control_panel(self, panel: ControlPanelState) -> str: ...
    def render_alert(self, payload: NotificationPayload) -> str: ...
    def render_daily_report(self, payload: NotificationPayload) -> str: ...
    def render_weekly_summary(self, payload: NotificationPayload) -> str: ...


class PlainTextRenderer:
    """Plain text renderer — used for logging and as a fallback."""

    def render(self, payload: NotificationPayload) -> str:
        dispatch = {
            "alert": self.render_alert,
            "daily_report": self.render_daily_report,
            "weekly_summary": self.render_weekly_summary,
        }
        handler = dispatch.get(payload.notification_type)
        if handler:
            return handler(payload)
        return self._render_generic(payload)

    def render_control_panel(self, panel: ControlPanelState) -> str:
        lines: list[str] = []
        lines.append(f"Control Panel — {panel.date}")
        lines.append("")
        lines.append(
            f"Portfolio: +${panel.portfolio_pnl:.0f} ({panel.portfolio_pnl_pct:+.1f}%) "
            f"| DD: {panel.drawdown_pct:.1f}% | Exposure: {panel.exposure_pct:.0f}%"
        )
        lines.append("")

        if panel.daily_report_ready:
            lines.append("Daily report ready")
        if panel.alert_count > 0:
            lines.append(f"{panel.alert_count} alert(s): {panel.alert_summary}")
        if panel.wfo_status:
            lines.append(f"WFO: {panel.wfo_status}")
        lines.append(f"{panel.pending_pr_count} PRs pending")
        lines.append(f"Risk: {panel.risk_status} ({panel.risk_detail})")
        lines.append("")

        for bot in panel.bot_statuses:
            lines.append(
                f"{bot.status_emoji} {bot.bot_id}: +${bot.pnl:.0f} "
                f"({bot.wins}W/{bot.losses}L) — {bot.summary}"
            )

        return "\n".join(lines)

    def render_alert(self, payload: NotificationPayload) -> str:
        priority_label = payload.priority.value.upper()
        lines: list[str] = []
        lines.append(f"[{priority_label}] {payload.title}")
        lines.append("")
        lines.append(payload.body)
        return "\n".join(lines)

    def render_daily_report(self, payload: NotificationPayload) -> str:
        lines: list[str] = []
        lines.append(payload.title)
        lines.append("")
        lines.append(payload.body)
        return "\n".join(lines)

    def render_weekly_summary(self, payload: NotificationPayload) -> str:
        lines: list[str] = []
        lines.append(payload.title)
        lines.append("")
        lines.append(payload.body)
        return "\n".join(lines)

    def _render_generic(self, payload: NotificationPayload) -> str:
        lines: list[str] = []
        lines.append(payload.title)
        lines.append("")
        lines.append(payload.body)
        return "\n".join(lines)
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_renderer.py -v`
Expected: All 10 tests PASS

**Step 5: Commit**

```bash
git add comms/__init__.py comms/renderer.py tests/test_renderer.py
git commit -m "feat(phase6): add MessageRenderer protocol and PlainTextRenderer"
```

---

## Task 2: Telegram Message Renderer

**Files:**
- Create: `comms/telegram_renderer.py`
- Test: `tests/test_telegram_renderer.py`

**Step 1: Write the failing test**

```python
# tests/test_telegram_renderer.py
"""Tests for Telegram-specific message renderer.

Telegram uses MarkdownV2 formatting and has a 4096 character message limit.
The renderer produces text + optional inline keyboard markup dicts.
"""
from comms.telegram_renderer import TelegramRenderer
from comms.renderer import MessageRenderer
from schemas.notifications import (
    ControlPanelState,
    BotStatusLine,
    NotificationPayload,
    NotificationPriority,
)


class TestTelegramRendererProtocol:
    def test_implements_message_renderer(self):
        renderer = TelegramRenderer()
        assert isinstance(renderer, MessageRenderer)


class TestTelegramControlPanel:
    def _make_panel(self) -> ControlPanelState:
        return ControlPanelState(
            date="2026-03-01",
            portfolio_pnl=342.0,
            portfolio_pnl_pct=1.2,
            drawdown_pct=-0.3,
            exposure_pct=47.0,
            daily_report_ready=True,
            alert_count=1,
            alert_summary="Bot3 volume filter",
            wfo_status="Bot2 running (est. 45min)",
            pending_pr_count=0,
            risk_status="OK",
            risk_detail="concentration: 35/100",
            bot_statuses=[
                BotStatusLine(bot_id="Bot1", status="green", pnl=210.0, wins=4, losses=1, summary="Strong trend, EMA cross"),
                BotStatusLine(bot_id="Bot2", status="yellow", pnl=82.0, wins=3, losses=2, summary="2 normal losses"),
                BotStatusLine(bot_id="Bot3", status="red", pnl=50.0, wins=2, losses=3, summary="Volume filter blocked 3 winners"),
            ],
        )

    def test_renders_header_with_emoji(self):
        panel = self._make_panel()
        text = TelegramRenderer().render_control_panel(panel)
        assert "📊" in text
        assert "2026-03-01" in text or "March 1" in text

    def test_renders_portfolio_line(self):
        panel = self._make_panel()
        text = TelegramRenderer().render_control_panel(panel)
        assert "342" in text
        assert "1.2" in text or "1\\.2" in text

    def test_renders_bot_statuses(self):
        panel = self._make_panel()
        text = TelegramRenderer().render_control_panel(panel)
        assert "🟢" in text
        assert "🟡" in text
        assert "🔴" in text
        assert "Bot1" in text
        assert "Bot3" in text

    def test_renders_status_indicators(self):
        panel = self._make_panel()
        text = TelegramRenderer().render_control_panel(panel)
        assert "✅" in text  # daily report ready
        assert "⚠️" in text  # alert
        assert "🧪" in text  # WFO
        assert "🛡️" in text  # risk

    def test_returns_keyboard_markup(self):
        panel = self._make_panel()
        text, keyboard = TelegramRenderer().render_control_panel_with_keyboard(panel)
        assert keyboard is not None
        # Should have buttons for Daily, Weekly, Bot Status, etc.
        button_labels = [btn["text"] for row in keyboard for btn in row]
        assert "Daily" in button_labels
        assert "Weekly" in button_labels
        assert "Bot Status" in button_labels

    def test_empty_panel(self):
        panel = ControlPanelState(date="2026-03-01")
        text = TelegramRenderer().render_control_panel(panel)
        assert "2026-03-01" in text


class TestTelegramAlert:
    def test_critical_alert_has_siren(self):
        payload = NotificationPayload(
            notification_type="alert",
            priority=NotificationPriority.CRITICAL,
            title="Bot3 crash",
            body="RuntimeError in signal handler",
        )
        text = TelegramRenderer().render_alert(payload)
        assert "🚨" in text
        assert "CRITICAL" in text
        assert "Bot3 crash" in text

    def test_normal_alert(self):
        payload = NotificationPayload(
            notification_type="alert",
            priority=NotificationPriority.NORMAL,
            title="Slow response",
            body="API latency > 2s",
        )
        text = TelegramRenderer().render_alert(payload)
        assert "Slow response" in text


class TestTelegramDailyReport:
    def test_renders_with_header_emoji(self):
        payload = NotificationPayload(
            notification_type="daily_report",
            title="Daily Report — March 1, 2026",
            body="Portfolio: +$342 (+1.2%)\n\nBot1: +$210 (4W/1L)",
        )
        text = TelegramRenderer().render_daily_report(payload)
        assert "📊" in text
        assert "Daily Report" in text

    def test_returns_action_keyboard(self):
        payload = NotificationPayload(
            notification_type="daily_report",
            title="Daily Report",
            body="Summary",
        )
        text, keyboard = TelegramRenderer().render_daily_report_with_keyboard(payload)
        button_labels = [btn["text"] for row in keyboard for btn in row]
        assert "Full Report" in button_labels
        assert "Feedback" in button_labels


class TestTelegramWeeklySummary:
    def test_renders_weekly(self):
        payload = NotificationPayload(
            notification_type="weekly_summary",
            title="Weekly Summary — Feb 24–Mar 1",
            body="Total PnL: +$1,200",
        )
        text = TelegramRenderer().render_weekly_summary(payload)
        assert "Weekly Summary" in text
        assert "$1,200" in text or "1,200" in text


class TestTelegramMessageLimit:
    def test_long_message_is_truncated(self):
        payload = NotificationPayload(
            notification_type="daily_report",
            title="Daily Report",
            body="x" * 5000,
        )
        text = TelegramRenderer().render_daily_report(payload)
        assert len(text) <= 4096

    def test_truncation_adds_continuation_note(self):
        payload = NotificationPayload(
            notification_type="daily_report",
            title="Daily Report",
            body="x" * 5000,
        )
        text = TelegramRenderer().render_daily_report(payload)
        assert "continued" in text.lower() or "truncated" in text.lower()


class TestTelegramEscaping:
    def test_escapes_markdown_v2_special_chars(self):
        """MarkdownV2 requires escaping: _ * [ ] ( ) ~ ` > # + - = | { } . !"""
        payload = NotificationPayload(
            notification_type="alert",
            priority=NotificationPriority.NORMAL,
            title="Bot_1 test-alert",
            body="PnL: +$342.50 (1.2%)",
        )
        text = TelegramRenderer().render_alert(payload)
        # Should not crash and should contain the content
        assert "Bot" in text
        assert "342" in text
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_telegram_renderer.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'comms.telegram_renderer'`

**Step 3: Write minimal implementation**

```python
# comms/telegram_renderer.py
"""Telegram message renderer — MarkdownV2 formatting with inline keyboards.

Telegram has a 4096 character limit per message. The renderer truncates
long messages and adds a "continued..." note.
"""
from __future__ import annotations

import re

from schemas.notifications import (
    ControlPanelState,
    NotificationPayload,
    NotificationPriority,
)

_TELEGRAM_MAX_LENGTH = 4096
_TRUNCATION_NOTE = "\n\n... (truncated, use /full for complete report)"


def _escape_md2(text: str) -> str:
    """Escape Telegram MarkdownV2 special characters."""
    return re.sub(r"([_*\[\]()~`>#+\-=|{}.!])", r"\\\1", text)


def _truncate(text: str, max_length: int = _TELEGRAM_MAX_LENGTH) -> str:
    if len(text) <= max_length:
        return text
    return text[: max_length - len(_TRUNCATION_NOTE)] + _TRUNCATION_NOTE


# Standard keyboard layouts
_CONTROL_PANEL_KEYBOARD = [
    [
        {"text": "Daily", "callback_data": "cmd_daily"},
        {"text": "Weekly", "callback_data": "cmd_weekly"},
        {"text": "Bot Status", "callback_data": "cmd_bot_status"},
    ],
    [
        {"text": "Top Missed", "callback_data": "cmd_top_missed"},
        {"text": "Open PRs", "callback_data": "cmd_open_prs"},
        {"text": "Approve All", "callback_data": "cmd_approve_all"},
    ],
    [
        {"text": "Settings", "callback_data": "cmd_settings"},
    ],
]

_DAILY_REPORT_KEYBOARD = [
    [
        {"text": "Full Report", "callback_data": "cmd_full_report"},
        {"text": "Feedback", "callback_data": "cmd_feedback"},
    ],
    [
        {"text": "Bot Detail", "callback_data": "cmd_bot_detail"},
        {"text": "Approve Change", "callback_data": "cmd_approve_change"},
    ],
]


class TelegramRenderer:
    """Renders notifications for Telegram with MarkdownV2 formatting."""

    def render(self, payload: NotificationPayload) -> str:
        dispatch = {
            "alert": self.render_alert,
            "daily_report": self.render_daily_report,
            "weekly_summary": self.render_weekly_summary,
        }
        handler = dispatch.get(payload.notification_type)
        if handler:
            return handler(payload)
        return self._render_generic(payload)

    def render_control_panel(self, panel: ControlPanelState) -> str:
        text, _ = self.render_control_panel_with_keyboard(panel)
        return text

    def render_control_panel_with_keyboard(
        self, panel: ControlPanelState
    ) -> tuple[str, list[list[dict]]]:
        lines: list[str] = []
        lines.append(f"📊 {panel.date} — Control Panel")
        lines.append("")
        lines.append(
            f"Portfolio: +${panel.portfolio_pnl:.0f} "
            f"({panel.portfolio_pnl_pct:+.1f}%) "
            f"| DD: {panel.drawdown_pct:.1f}% "
            f"| Exposure: {panel.exposure_pct:.0f}%"
        )
        lines.append("")

        if panel.daily_report_ready:
            lines.append("✅ Daily report ready")
        if panel.alert_count > 0:
            lines.append(f"⚠️ {panel.alert_count} alert(s) ({panel.alert_summary})")
        if panel.wfo_status:
            lines.append(f"🧪 WFO: {panel.wfo_status}")
        lines.append(f"🧰 {panel.pending_pr_count} PRs pending")
        lines.append(f"🛡️ Risk: {panel.risk_status} ({panel.risk_detail})")
        lines.append("")

        for bot in panel.bot_statuses:
            lines.append(
                f"{bot.status_emoji} {bot.bot_id}: +${bot.pnl:.0f} "
                f"({bot.wins}W/{bot.losses}L) — {bot.summary}"
            )

        text = "\n".join(lines)
        return text, _CONTROL_PANEL_KEYBOARD

    def render_alert(self, payload: NotificationPayload) -> str:
        priority = payload.priority
        if priority == NotificationPriority.CRITICAL:
            header = f"🚨 CRITICAL — {payload.title}"
        elif priority == NotificationPriority.HIGH:
            header = f"⚠️ HIGH — {payload.title}"
        else:
            header = f"ℹ️ {payload.title}"

        text = f"{header}\n\n{payload.body}"
        return _truncate(text)

    def render_daily_report(self, payload: NotificationPayload) -> str:
        text, _ = self.render_daily_report_with_keyboard(payload)
        return text

    def render_daily_report_with_keyboard(
        self, payload: NotificationPayload
    ) -> tuple[str, list[list[dict]]]:
        lines: list[str] = []
        lines.append(f"📊 {payload.title}")
        lines.append("")
        lines.append(payload.body)
        text = _truncate("\n".join(lines))
        return text, _DAILY_REPORT_KEYBOARD

    def render_weekly_summary(self, payload: NotificationPayload) -> str:
        lines: list[str] = []
        lines.append(f"📈 {payload.title}")
        lines.append("")
        lines.append(payload.body)
        return _truncate("\n".join(lines))

    def _render_generic(self, payload: NotificationPayload) -> str:
        text = f"{payload.title}\n\n{payload.body}"
        return _truncate(text)
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_telegram_renderer.py -v`
Expected: All 16 tests PASS

**Step 5: Commit**

```bash
git add comms/telegram_renderer.py tests/test_telegram_renderer.py
git commit -m "feat(phase6): add TelegramRenderer with MarkdownV2 + inline keyboards"
```

---

## Task 3: Telegram Bot Adapter

**Files:**
- Create: `comms/telegram_bot.py`
- Test: `tests/test_telegram_bot.py`

**Step 1: Write the failing test**

```python
# tests/test_telegram_bot.py
"""Tests for Telegram bot adapter.

Uses a mock transport — no real Telegram API calls.
The adapter wraps python-telegram-bot's Application for send/edit/pin.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from comms.telegram_bot import TelegramBotAdapter, TelegramBotConfig


class TestTelegramBotConfig:
    def test_defaults(self):
        cfg = TelegramBotConfig(token="fake-token", chat_id="12345")
        assert cfg.token == "fake-token"
        assert cfg.chat_id == "12345"
        assert cfg.parse_mode == "MarkdownV2"


class TestTelegramBotAdapter:
    @pytest.fixture
    def mock_bot(self):
        bot = AsyncMock()
        bot.send_message = AsyncMock(return_value=MagicMock(message_id=42))
        bot.edit_message_text = AsyncMock(return_value=MagicMock(message_id=42))
        bot.pin_chat_message = AsyncMock()
        return bot

    @pytest.fixture
    def adapter(self, mock_bot):
        config = TelegramBotConfig(token="fake-token", chat_id="12345")
        a = TelegramBotAdapter(config)
        a._bot = mock_bot
        return a

    @pytest.mark.asyncio
    async def test_send_message(self, adapter, mock_bot):
        msg_id = await adapter.send_message("Hello, world!")
        assert msg_id == 42
        mock_bot.send_message.assert_called_once()
        call_kwargs = mock_bot.send_message.call_args.kwargs
        assert call_kwargs["chat_id"] == "12345"
        assert call_kwargs["text"] == "Hello, world!"

    @pytest.mark.asyncio
    async def test_send_message_with_keyboard(self, adapter, mock_bot):
        keyboard = [[{"text": "Daily", "callback_data": "cmd_daily"}]]
        msg_id = await adapter.send_message("Panel", keyboard=keyboard)
        assert msg_id == 42
        call_kwargs = mock_bot.send_message.call_args.kwargs
        assert "reply_markup" in call_kwargs

    @pytest.mark.asyncio
    async def test_edit_message(self, adapter, mock_bot):
        await adapter.edit_message(42, "Updated text")
        mock_bot.edit_message_text.assert_called_once()
        call_kwargs = mock_bot.edit_message_text.call_args.kwargs
        assert call_kwargs["message_id"] == 42
        assert call_kwargs["text"] == "Updated text"

    @pytest.mark.asyncio
    async def test_edit_message_with_keyboard(self, adapter, mock_bot):
        keyboard = [[{"text": "Weekly", "callback_data": "cmd_weekly"}]]
        await adapter.edit_message(42, "Updated", keyboard=keyboard)
        call_kwargs = mock_bot.edit_message_text.call_args.kwargs
        assert "reply_markup" in call_kwargs

    @pytest.mark.asyncio
    async def test_pin_message(self, adapter, mock_bot):
        await adapter.pin_message(42)
        mock_bot.pin_chat_message.assert_called_once_with(
            chat_id="12345", message_id=42, disable_notification=True
        )

    @pytest.mark.asyncio
    async def test_send_and_pin(self, adapter, mock_bot):
        msg_id = await adapter.send_and_pin("Important message")
        assert msg_id == 42
        mock_bot.send_message.assert_called_once()
        mock_bot.pin_chat_message.assert_called_once()
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_telegram_bot.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'comms.telegram_bot'`

**Step 3: Write minimal implementation**

```python
# comms/telegram_bot.py
"""Telegram bot adapter — wraps send/edit/pin operations.

Encapsulates python-telegram-bot's Bot object. In tests, the _bot
attribute is replaced with a mock.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class TelegramBotConfig:
    token: str
    chat_id: str
    parse_mode: str = "MarkdownV2"


def _build_inline_keyboard(keyboard: list[list[dict]]) -> dict:
    """Convert our keyboard format to Telegram InlineKeyboardMarkup dict."""
    return {
        "inline_keyboard": [
            [{"text": btn["text"], "callback_data": btn["callback_data"]} for btn in row]
            for row in keyboard
        ]
    }


class TelegramBotAdapter:
    """Async adapter for Telegram Bot API operations."""

    def __init__(self, config: TelegramBotConfig) -> None:
        self._config = config
        self._bot: object | None = None  # Set externally or via start()

    async def start(self) -> None:
        """Initialize the bot. Import telegram only when actually starting."""
        from telegram import Bot
        self._bot = Bot(token=self._config.token)

    async def send_message(
        self,
        text: str,
        keyboard: list[list[dict]] | None = None,
    ) -> int:
        """Send a message. Returns the message_id."""
        kwargs: dict = {
            "chat_id": self._config.chat_id,
            "text": text,
        }
        if keyboard:
            kwargs["reply_markup"] = _build_inline_keyboard(keyboard)

        result = await self._bot.send_message(**kwargs)
        return result.message_id

    async def edit_message(
        self,
        message_id: int,
        text: str,
        keyboard: list[list[dict]] | None = None,
    ) -> None:
        """Edit an existing message in-place."""
        kwargs: dict = {
            "chat_id": self._config.chat_id,
            "message_id": message_id,
            "text": text,
        }
        if keyboard:
            kwargs["reply_markup"] = _build_inline_keyboard(keyboard)

        await self._bot.edit_message_text(**kwargs)

    async def pin_message(self, message_id: int) -> None:
        """Pin a message in the chat."""
        await self._bot.pin_chat_message(
            chat_id=self._config.chat_id,
            message_id=message_id,
            disable_notification=True,
        )

    async def send_and_pin(
        self,
        text: str,
        keyboard: list[list[dict]] | None = None,
    ) -> int:
        """Send a message and pin it. Returns the message_id."""
        msg_id = await self.send_message(text, keyboard=keyboard)
        await self.pin_message(msg_id)
        return msg_id
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_telegram_bot.py -v`
Expected: All 8 tests PASS

**Step 5: Commit**

```bash
git add comms/telegram_bot.py tests/test_telegram_bot.py
git commit -m "feat(phase6): add TelegramBotAdapter with send/edit/pin"
```

---

## Task 4: Telegram Control Surface

**Files:**
- Create: `comms/telegram_control_surface.py`
- Test: `tests/test_telegram_control_surface.py`

**Step 1: Write the failing test**

```python
# tests/test_telegram_control_surface.py
"""Tests for the daily pinned control surface.

The control surface maintains one pinned message per day, updated in-place
whenever system state changes (new alerts, report ready, WFO status, etc.).
"""
import pytest
from unittest.mock import AsyncMock

from comms.telegram_control_surface import ControlSurface
from comms.telegram_renderer import TelegramRenderer
from comms.telegram_bot import TelegramBotAdapter, TelegramBotConfig
from schemas.notifications import ControlPanelState, BotStatusLine


@pytest.fixture
def mock_adapter():
    config = TelegramBotConfig(token="fake", chat_id="12345")
    adapter = TelegramBotAdapter(config)
    adapter._bot = AsyncMock()
    adapter._bot.send_message = AsyncMock(return_value=AsyncMock(message_id=100))
    adapter._bot.edit_message_text = AsyncMock()
    adapter._bot.pin_chat_message = AsyncMock()
    return adapter


@pytest.fixture
def surface(mock_adapter):
    return ControlSurface(adapter=mock_adapter, renderer=TelegramRenderer())


class TestControlSurfaceInit:
    def test_no_pinned_message_initially(self, surface):
        assert surface.current_message_id is None
        assert surface.current_date is None


class TestControlSurfacePublish:
    @pytest.mark.asyncio
    async def test_first_publish_creates_and_pins(self, surface, mock_adapter):
        panel = ControlPanelState(date="2026-03-01", portfolio_pnl=100.0)
        await surface.publish(panel)

        assert surface.current_message_id == 100
        assert surface.current_date == "2026-03-01"
        mock_adapter._bot.send_message.assert_called_once()
        mock_adapter._bot.pin_chat_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_second_publish_same_day_edits_in_place(self, surface, mock_adapter):
        panel1 = ControlPanelState(date="2026-03-01", portfolio_pnl=100.0)
        await surface.publish(panel1)

        panel2 = ControlPanelState(date="2026-03-01", portfolio_pnl=200.0, daily_report_ready=True)
        await surface.publish(panel2)

        # Should have sent once, then edited once
        assert mock_adapter._bot.send_message.call_count == 1
        assert mock_adapter._bot.edit_message_text.call_count == 1
        assert surface.current_message_id == 100

    @pytest.mark.asyncio
    async def test_new_day_creates_new_message(self, surface, mock_adapter):
        panel1 = ControlPanelState(date="2026-03-01", portfolio_pnl=100.0)
        await surface.publish(panel1)

        # New day → new pinned message
        mock_adapter._bot.send_message = AsyncMock(return_value=AsyncMock(message_id=200))
        panel2 = ControlPanelState(date="2026-03-02", portfolio_pnl=50.0)
        await surface.publish(panel2)

        assert surface.current_message_id == 200
        assert surface.current_date == "2026-03-02"
        assert mock_adapter._bot.pin_chat_message.call_count == 2


class TestControlSurfaceUpdate:
    @pytest.mark.asyncio
    async def test_update_alert_count(self, surface, mock_adapter):
        panel = ControlPanelState(date="2026-03-01")
        await surface.publish(panel)

        await surface.update_field(alert_count=2, alert_summary="Bot1 crash, Bot3 timeout")
        assert mock_adapter._bot.edit_message_text.call_count == 1

    @pytest.mark.asyncio
    async def test_update_daily_report_ready(self, surface, mock_adapter):
        panel = ControlPanelState(date="2026-03-01")
        await surface.publish(panel)

        await surface.update_field(daily_report_ready=True)
        assert mock_adapter._bot.edit_message_text.call_count == 1

    @pytest.mark.asyncio
    async def test_update_without_publish_is_noop(self, surface, mock_adapter):
        """If no panel has been published yet, update_field does nothing."""
        await surface.update_field(alert_count=5)
        mock_adapter._bot.edit_message_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_wfo_status(self, surface, mock_adapter):
        panel = ControlPanelState(date="2026-03-01")
        await surface.publish(panel)

        await surface.update_field(wfo_status="Bot2 complete — ADOPT")
        assert mock_adapter._bot.edit_message_text.call_count == 1
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_telegram_control_surface.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'comms.telegram_control_surface'`

**Step 3: Write minimal implementation**

```python
# comms/telegram_control_surface.py
"""Telegram control surface — one pinned message per day, updated in-place.

Manages the daily dashboard message: creates it on first call each day,
edits it in-place for subsequent updates, and pins it.
"""
from __future__ import annotations

from comms.telegram_bot import TelegramBotAdapter
from comms.telegram_renderer import TelegramRenderer
from schemas.notifications import ControlPanelState


class ControlSurface:
    """Manages the daily pinned control panel message."""

    def __init__(
        self,
        adapter: TelegramBotAdapter,
        renderer: TelegramRenderer,
    ) -> None:
        self._adapter = adapter
        self._renderer = renderer
        self._current_message_id: int | None = None
        self._current_date: str | None = None
        self._current_panel: ControlPanelState | None = None

    @property
    def current_message_id(self) -> int | None:
        return self._current_message_id

    @property
    def current_date(self) -> str | None:
        return self._current_date

    async def publish(self, panel: ControlPanelState) -> None:
        """Publish or update the control panel for the given date."""
        text, keyboard = self._renderer.render_control_panel_with_keyboard(panel)
        self._current_panel = panel

        if self._current_date == panel.date and self._current_message_id is not None:
            # Same day → edit in place
            await self._adapter.edit_message(self._current_message_id, text, keyboard=keyboard)
        else:
            # New day (or first publish) → send + pin
            msg_id = await self._adapter.send_and_pin(text, keyboard=keyboard)
            self._current_message_id = msg_id
            self._current_date = panel.date

    async def update_field(self, **kwargs) -> None:
        """Update one or more fields on the current panel and re-publish.

        Accepts any field name from ControlPanelState (e.g. alert_count=2).
        No-op if no panel has been published yet.
        """
        if self._current_panel is None:
            return

        updated = self._current_panel.model_copy(update=kwargs)
        self._current_panel = updated

        text, keyboard = self._renderer.render_control_panel_with_keyboard(updated)
        await self._adapter.edit_message(self._current_message_id, text, keyboard=keyboard)
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_telegram_control_surface.py -v`
Expected: All 8 tests PASS

**Step 5: Commit**

```bash
git add comms/telegram_control_surface.py tests/test_telegram_control_surface.py
git commit -m "feat(phase6): add Telegram ControlSurface — daily pinned message"
```

---

## Task 5: Telegram Callback Handlers

**Files:**
- Create: `comms/telegram_handlers.py`
- Test: `tests/test_telegram_handlers.py`

**Step 1: Write the failing test**

```python
# tests/test_telegram_handlers.py
"""Tests for Telegram callback query + slash command handlers.

Button presses on inline keyboards trigger callback queries. Each callback_data
string (e.g. "cmd_daily") maps to a handler that fetches data and responds.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from comms.telegram_handlers import TelegramCallbackRouter


class TestCallbackRouter:
    @pytest.fixture
    def router(self):
        return TelegramCallbackRouter()

    def test_register_handler(self, router):
        handler = AsyncMock()
        router.register("cmd_daily", handler)
        assert "cmd_daily" in router.handlers

    def test_register_multiple(self, router):
        router.register("cmd_daily", AsyncMock())
        router.register("cmd_weekly", AsyncMock())
        assert len(router.handlers) == 2


class TestCallbackDispatch:
    @pytest.fixture
    def router(self):
        r = TelegramCallbackRouter()
        r.register("cmd_daily", AsyncMock(return_value="Daily report content"))
        r.register("cmd_weekly", AsyncMock(return_value="Weekly report content"))
        r.register("cmd_bot_status", AsyncMock(return_value="All bots OK"))
        return r

    @pytest.mark.asyncio
    async def test_dispatch_known_command(self, router):
        result = await router.dispatch("cmd_daily")
        assert result == "Daily report content"
        router.handlers["cmd_daily"].assert_called_once()

    @pytest.mark.asyncio
    async def test_dispatch_unknown_command(self, router):
        result = await router.dispatch("cmd_nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_dispatch_passes_context(self, router):
        ctx = {"user_id": "123", "chat_id": "456"}
        await router.dispatch("cmd_daily", context=ctx)
        router.handlers["cmd_daily"].assert_called_once_with(context=ctx)


class TestSlashCommandFallback:
    @pytest.fixture
    def router(self):
        r = TelegramCallbackRouter()
        r.register("cmd_daily", AsyncMock(return_value="Daily"))
        r.register("cmd_weekly", AsyncMock(return_value="Weekly"))
        return r

    @pytest.mark.asyncio
    async def test_slash_command_maps_to_callback(self, router):
        result = await router.dispatch_slash("/daily")
        assert result == "Daily"

    @pytest.mark.asyncio
    async def test_slash_command_unknown(self, router):
        result = await router.dispatch_slash("/unknown")
        assert result is None

    @pytest.mark.asyncio
    async def test_slash_help_returns_command_list(self, router):
        result = await router.dispatch_slash("/help")
        assert "/daily" in result
        assert "/weekly" in result


class TestApprovalFlow:
    @pytest.fixture
    def router(self):
        r = TelegramCallbackRouter()
        approval_handler = AsyncMock(return_value="Approved 2 items")
        r.register("cmd_approve_all", approval_handler)
        return r

    @pytest.mark.asyncio
    async def test_approve_all_dispatches(self, router):
        result = await router.dispatch("cmd_approve_all")
        assert result == "Approved 2 items"

    @pytest.mark.asyncio
    async def test_approve_with_confirmation_context(self, router):
        ctx = {"confirmed": True}
        await router.dispatch("cmd_approve_all", context=ctx)
        router.handlers["cmd_approve_all"].assert_called_once_with(context=ctx)
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_telegram_handlers.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'comms.telegram_handlers'`

**Step 3: Write minimal implementation**

```python
# comms/telegram_handlers.py
"""Telegram callback query router and slash command fallback.

Maps inline keyboard callback_data strings to async handler functions.
Slash commands (/daily, /weekly, etc.) are translated to the same callbacks.
"""
from __future__ import annotations

from typing import Callable, Awaitable, Optional


# Slash command → callback_data mapping
_SLASH_MAP: dict[str, str] = {
    "/daily": "cmd_daily",
    "/weekly": "cmd_weekly",
    "/botstatus": "cmd_bot_status",
    "/bot_status": "cmd_bot_status",
    "/topmissed": "cmd_top_missed",
    "/top_missed": "cmd_top_missed",
    "/openprs": "cmd_open_prs",
    "/open_prs": "cmd_open_prs",
    "/approve": "cmd_approve_all",
    "/settings": "cmd_settings",
}


class TelegramCallbackRouter:
    """Routes callback queries and slash commands to handler functions."""

    def __init__(self) -> None:
        self._handlers: dict[str, Callable[..., Awaitable[str | None]]] = {}

    @property
    def handlers(self) -> dict[str, Callable[..., Awaitable[str | None]]]:
        return self._handlers

    def register(self, callback_data: str, handler: Callable[..., Awaitable[str | None]]) -> None:
        """Register a handler for a callback_data string."""
        self._handlers[callback_data] = handler

    async def dispatch(
        self,
        callback_data: str,
        context: dict | None = None,
    ) -> str | None:
        """Dispatch a callback query to the registered handler."""
        handler = self._handlers.get(callback_data)
        if handler is None:
            return None
        if context is not None:
            return await handler(context=context)
        return await handler()

    async def dispatch_slash(
        self,
        command: str,
        context: dict | None = None,
    ) -> str | None:
        """Dispatch a slash command by mapping it to a callback_data string."""
        if command == "/help":
            return self._build_help_text()

        callback_data = _SLASH_MAP.get(command)
        if callback_data is None:
            return None
        return await self.dispatch(callback_data, context=context)

    def _build_help_text(self) -> str:
        """Build a help message listing all available slash commands."""
        lines = ["Available commands:"]
        for slash, cb in sorted(_SLASH_MAP.items()):
            if cb in self._handlers:
                lines.append(f"  {slash}")
        return "\n".join(lines)
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_telegram_handlers.py -v`
Expected: All 9 tests PASS

**Step 5: Commit**

```bash
git add comms/telegram_handlers.py tests/test_telegram_handlers.py
git commit -m "feat(phase6): add TelegramCallbackRouter for buttons + slash commands"
```

---

## Task 6: Discord Message Renderer

**Files:**
- Create: `comms/discord_renderer.py`
- Test: `tests/test_discord_renderer.py`

**Step 1: Write the failing test**

```python
# tests/test_discord_renderer.py
"""Tests for Discord embed renderer.

Discord supports rich embeds with fields, colors, thumbnails, and footers.
The renderer produces embed dicts compatible with discord.py's Embed.from_dict().
"""
from comms.discord_renderer import DiscordRenderer
from comms.renderer import MessageRenderer
from schemas.notifications import (
    ControlPanelState,
    BotStatusLine,
    NotificationPayload,
    NotificationPriority,
)


class TestDiscordRendererProtocol:
    def test_implements_message_renderer(self):
        renderer = DiscordRenderer()
        assert isinstance(renderer, MessageRenderer)


class TestDiscordRenderAlert:
    def test_critical_alert_embed(self):
        payload = NotificationPayload(
            notification_type="alert",
            priority=NotificationPriority.CRITICAL,
            title="Bot3 crash",
            body="RuntimeError in signal handler",
        )
        embed = DiscordRenderer().render_alert_embed(payload)
        assert embed["title"] == "🚨 CRITICAL — Bot3 crash"
        assert embed["color"] == 0xFF0000  # red
        assert "RuntimeError" in embed["description"]

    def test_normal_alert_embed(self):
        payload = NotificationPayload(
            notification_type="alert",
            priority=NotificationPriority.NORMAL,
            title="Slow response",
            body="API latency > 2s",
        )
        embed = DiscordRenderer().render_alert_embed(payload)
        assert embed["color"] == 0x3498DB  # blue

    def test_render_alert_returns_string(self):
        """The render_alert method returns a plain string for protocol compliance."""
        payload = NotificationPayload(
            notification_type="alert",
            priority=NotificationPriority.CRITICAL,
            title="Test",
            body="Body",
        )
        text = DiscordRenderer().render_alert(payload)
        assert isinstance(text, str)
        assert "Test" in text


class TestDiscordRenderDailyReport:
    def test_daily_report_embed_has_fields(self):
        payload = NotificationPayload(
            notification_type="daily_report",
            title="Daily Report — March 1, 2026",
            body="Portfolio: +$342 (+1.2%)",
            data={
                "bot_statuses": [
                    {"bot_id": "Bot1", "status": "green", "pnl": 210.0, "wins": 4, "losses": 1, "summary": "Strong"},
                    {"bot_id": "Bot2", "status": "red", "pnl": -50.0, "wins": 1, "losses": 3, "summary": "Filter"},
                ],
            },
        )
        embed = DiscordRenderer().render_daily_report_embed(payload)
        assert embed["title"] == "📊 Daily Report — March 1, 2026"
        # Should have fields for each bot
        field_names = [f["name"] for f in embed.get("fields", [])]
        assert any("Bot1" in n for n in field_names)
        assert any("Bot2" in n for n in field_names)

    def test_daily_report_without_bot_data(self):
        payload = NotificationPayload(
            notification_type="daily_report",
            title="Daily Report",
            body="Summary here",
        )
        embed = DiscordRenderer().render_daily_report_embed(payload)
        assert embed["title"] == "📊 Daily Report"
        assert embed["description"] == "Summary here"


class TestDiscordRenderWeeklySummary:
    def test_weekly_embed(self):
        payload = NotificationPayload(
            notification_type="weekly_summary",
            title="Weekly Summary — Feb 24–Mar 1",
            body="Total PnL: +$1,200\n3 bots active",
        )
        embed = DiscordRenderer().render_weekly_summary_embed(payload)
        assert embed["title"] == "📈 Weekly Summary — Feb 24–Mar 1"
        assert "1,200" in embed["description"]

    def test_weekly_embed_color(self):
        payload = NotificationPayload(
            notification_type="weekly_summary",
            title="Weekly",
            body="Good week",
        )
        embed = DiscordRenderer().render_weekly_summary_embed(payload)
        assert embed["color"] == 0x2ECC71  # green


class TestDiscordRenderControlPanel:
    def test_control_panel_text(self):
        panel = ControlPanelState(
            date="2026-03-01",
            portfolio_pnl=342.0,
            portfolio_pnl_pct=1.2,
            bot_statuses=[
                BotStatusLine(bot_id="Bot1", status="green", pnl=210.0, wins=4, losses=1, summary="Good"),
            ],
        )
        text = DiscordRenderer().render_control_panel(panel)
        assert "Bot1" in text
        assert "342" in text
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_discord_renderer.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'comms.discord_renderer'`

**Step 3: Write minimal implementation**

```python
# comms/discord_renderer.py
"""Discord embed renderer — rich formatting for Discord messages.

Produces embed dicts compatible with discord.py's Embed.from_dict().
"""
from __future__ import annotations

from schemas.notifications import (
    ControlPanelState,
    NotificationPayload,
    NotificationPriority,
)

# Discord embed color palette
_COLORS = {
    NotificationPriority.CRITICAL: 0xFF0000,  # red
    NotificationPriority.HIGH: 0xE67E22,      # orange
    NotificationPriority.NORMAL: 0x3498DB,     # blue
    NotificationPriority.LOW: 0x95A5A6,        # gray
}


class DiscordRenderer:
    """Renders notifications as Discord embeds."""

    def render(self, payload: NotificationPayload) -> str:
        dispatch = {
            "alert": self.render_alert,
            "daily_report": self.render_daily_report,
            "weekly_summary": self.render_weekly_summary,
        }
        handler = dispatch.get(payload.notification_type)
        if handler:
            return handler(payload)
        return f"{payload.title}\n\n{payload.body}"

    def render_control_panel(self, panel: ControlPanelState) -> str:
        lines: list[str] = []
        lines.append(f"📊 {panel.date} — Control Panel")
        lines.append(
            f"Portfolio: +${panel.portfolio_pnl:.0f} ({panel.portfolio_pnl_pct:+.1f}%) "
            f"| DD: {panel.drawdown_pct:.1f}% | Exposure: {panel.exposure_pct:.0f}%"
        )
        for bot in panel.bot_statuses:
            lines.append(f"{bot.status_emoji} {bot.bot_id}: +${bot.pnl:.0f} ({bot.wins}W/{bot.losses}L) — {bot.summary}")
        return "\n".join(lines)

    def render_alert(self, payload: NotificationPayload) -> str:
        embed = self.render_alert_embed(payload)
        return f"{embed['title']}\n\n{embed['description']}"

    def render_alert_embed(self, payload: NotificationPayload) -> dict:
        priority = payload.priority
        if priority == NotificationPriority.CRITICAL:
            title = f"🚨 CRITICAL — {payload.title}"
        elif priority == NotificationPriority.HIGH:
            title = f"⚠️ HIGH — {payload.title}"
        else:
            title = f"ℹ️ {payload.title}"

        return {
            "title": title,
            "description": payload.body,
            "color": _COLORS.get(priority, 0x3498DB),
        }

    def render_daily_report(self, payload: NotificationPayload) -> str:
        embed = self.render_daily_report_embed(payload)
        return f"{embed['title']}\n\n{embed['description']}"

    def render_daily_report_embed(self, payload: NotificationPayload) -> dict:
        embed: dict = {
            "title": f"📊 {payload.title}",
            "description": payload.body,
            "color": 0x3498DB,
            "fields": [],
        }

        bot_statuses = payload.data.get("bot_statuses", [])
        for bot in bot_statuses:
            bot_id = bot.get("bot_id", "?")
            status = bot.get("status", "")
            emoji = {"green": "🟢", "yellow": "🟡", "red": "🔴"}.get(status, "⚪")
            pnl = bot.get("pnl", 0)
            wins = bot.get("wins", 0)
            losses = bot.get("losses", 0)
            summary = bot.get("summary", "")
            embed["fields"].append({
                "name": f"{emoji} {bot_id}",
                "value": f"+${pnl:.0f} ({wins}W/{losses}L) — {summary}",
                "inline": True,
            })

        return embed

    def render_weekly_summary(self, payload: NotificationPayload) -> str:
        embed = self.render_weekly_summary_embed(payload)
        return f"{embed['title']}\n\n{embed['description']}"

    def render_weekly_summary_embed(self, payload: NotificationPayload) -> dict:
        return {
            "title": f"📈 {payload.title}",
            "description": payload.body,
            "color": 0x2ECC71,
        }
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_discord_renderer.py -v`
Expected: All 10 tests PASS

**Step 5: Commit**

```bash
git add comms/discord_renderer.py tests/test_discord_renderer.py
git commit -m "feat(phase6): add DiscordRenderer with rich embeds"
```

---

## Task 7: Discord Bot Adapter

**Files:**
- Create: `comms/discord_bot.py`
- Test: `tests/test_discord_bot.py`

**Step 1: Write the failing test**

```python
# tests/test_discord_bot.py
"""Tests for Discord bot adapter.

Uses mock client — no real Discord API calls.
The adapter wraps discord.py for send embed, create thread, pin message.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from comms.discord_bot import DiscordBotAdapter, DiscordBotConfig


class TestDiscordBotConfig:
    def test_defaults(self):
        cfg = DiscordBotConfig(token="fake-token", channel_id=123456)
        assert cfg.token == "fake-token"
        assert cfg.channel_id == 123456


class TestDiscordBotAdapter:
    @pytest.fixture
    def mock_channel(self):
        ch = AsyncMock()
        msg = MagicMock(id=42)
        ch.send = AsyncMock(return_value=msg)
        ch.fetch_message = AsyncMock(return_value=msg)
        msg.pin = AsyncMock()
        msg.create_thread = AsyncMock(return_value=MagicMock(id=99))
        return ch

    @pytest.fixture
    def adapter(self, mock_channel):
        config = DiscordBotConfig(token="fake-token", channel_id=123456)
        a = DiscordBotAdapter(config)
        a._channel = mock_channel
        return a

    @pytest.mark.asyncio
    async def test_send_message(self, adapter, mock_channel):
        msg_id = await adapter.send_message("Hello")
        assert msg_id == 42
        mock_channel.send.assert_called_once_with(content="Hello")

    @pytest.mark.asyncio
    async def test_send_embed(self, adapter, mock_channel):
        embed_dict = {"title": "Test", "description": "Body", "color": 0xFF0000}
        msg_id = await adapter.send_embed(embed_dict)
        assert msg_id == 42
        mock_channel.send.assert_called_once()
        call_kwargs = mock_channel.send.call_args.kwargs
        assert "embed" in call_kwargs

    @pytest.mark.asyncio
    async def test_pin_message(self, adapter, mock_channel):
        msg = await mock_channel.fetch_message(42)
        await adapter.pin_message(42)
        mock_channel.fetch_message.assert_called_with(42)

    @pytest.mark.asyncio
    async def test_create_thread(self, adapter, mock_channel):
        thread_id = await adapter.create_thread(42, "Bot1 Discussion")
        assert thread_id == 99

    @pytest.mark.asyncio
    async def test_send_to_thread(self, adapter, mock_channel):
        thread = MagicMock()
        thread.send = AsyncMock(return_value=MagicMock(id=55))
        mock_channel.fetch_message = AsyncMock(return_value=MagicMock(id=42))
        adapter._threads = {99: thread}
        msg_id = await adapter.send_to_thread(99, "Thread message")
        assert msg_id == 55
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_discord_bot.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'comms.discord_bot'`

**Step 3: Write minimal implementation**

```python
# comms/discord_bot.py
"""Discord bot adapter — wraps send/pin/thread operations.

Encapsulates discord.py client operations. In tests, _channel is replaced
with a mock.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class DiscordBotConfig:
    token: str
    channel_id: int


class DiscordBotAdapter:
    """Async adapter for Discord bot operations."""

    def __init__(self, config: DiscordBotConfig) -> None:
        self._config = config
        self._channel: object | None = None  # Set externally or via start()
        self._threads: dict[int, object] = {}

    async def start(self) -> None:
        """Initialize the Discord client. Import discord only when starting."""
        import discord
        client = discord.Client(intents=discord.Intents.default())
        # In production, would await client.start() and fetch channel
        # For now, _channel must be set externally

    async def send_message(self, content: str) -> int:
        """Send a plain text message. Returns message ID."""
        msg = await self._channel.send(content=content)
        return msg.id

    async def send_embed(self, embed_dict: dict) -> int:
        """Send an embed message from a dict. Returns message ID."""
        # Import only when needed (tests mock this away)
        try:
            import discord
            embed = discord.Embed.from_dict(embed_dict)
        except ImportError:
            # In test environment without discord.py installed
            embed = embed_dict
        msg = await self._channel.send(embed=embed)
        return msg.id

    async def pin_message(self, message_id: int) -> None:
        """Pin a message in the channel."""
        msg = await self._channel.fetch_message(message_id)
        await msg.pin()

    async def create_thread(self, message_id: int, name: str) -> int:
        """Create a thread on a message. Returns thread ID."""
        msg = await self._channel.fetch_message(message_id)
        thread = await msg.create_thread(name=name)
        self._threads[thread.id] = thread
        return thread.id

    async def send_to_thread(self, thread_id: int, content: str) -> int:
        """Send a message to an existing thread. Returns message ID."""
        thread = self._threads.get(thread_id)
        if thread is None:
            raise ValueError(f"Thread {thread_id} not found. Call create_thread first.")
        msg = await thread.send(content=content)
        return msg.id
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_discord_bot.py -v`
Expected: All 6 tests PASS

**Step 5: Commit**

```bash
git add comms/discord_bot.py tests/test_discord_bot.py
git commit -m "feat(phase6): add DiscordBotAdapter with embed/thread/pin support"
```

---

## Task 8: Email Renderer

**Files:**
- Create: `comms/email_renderer.py`
- Test: `tests/test_email_renderer.py`

**Step 1: Write the failing test**

```python
# tests/test_email_renderer.py
"""Tests for email HTML renderer.

Renders weekly digests and WFO reports as HTML email bodies.
Uses Jinja2 templates for structure, with inline CSS for email client compat.
"""
from comms.email_renderer import EmailRenderer
from comms.renderer import MessageRenderer
from schemas.notifications import (
    ControlPanelState,
    NotificationPayload,
    NotificationPriority,
)


class TestEmailRendererProtocol:
    def test_implements_message_renderer(self):
        renderer = EmailRenderer()
        assert isinstance(renderer, MessageRenderer)


class TestEmailRenderWeeklyDigest:
    def test_renders_html_structure(self):
        payload = NotificationPayload(
            notification_type="weekly_summary",
            title="Weekly Summary — Feb 24–Mar 1",
            body="Total PnL: +$1,200\n3 bots active\n\nBot1: +$800\nBot2: +$400",
        )
        html = EmailRenderer().render_weekly_html(payload)
        assert "<html" in html
        assert "Weekly Summary" in html
        assert "$1,200" in html or "1,200" in html

    def test_renders_with_inline_styles(self):
        payload = NotificationPayload(
            notification_type="weekly_summary",
            title="Weekly",
            body="Content",
        )
        html = EmailRenderer().render_weekly_html(payload)
        assert "style=" in html

    def test_newlines_become_paragraphs(self):
        payload = NotificationPayload(
            notification_type="weekly_summary",
            title="Weekly",
            body="Line 1\n\nLine 2",
        )
        html = EmailRenderer().render_weekly_html(payload)
        assert "<p>" in html or "<br" in html


class TestEmailRenderAlert:
    def test_critical_alert_html(self):
        payload = NotificationPayload(
            notification_type="alert",
            priority=NotificationPriority.CRITICAL,
            title="Bot crash",
            body="RuntimeError",
        )
        text = EmailRenderer().render_alert(payload)
        assert "CRITICAL" in text
        assert "Bot crash" in text

    def test_render_protocol_method(self):
        payload = NotificationPayload(
            notification_type="weekly_summary",
            title="Weekly",
            body="Content",
        )
        text = EmailRenderer().render_weekly_summary(payload)
        assert "Weekly" in text


class TestEmailRenderDailyReport:
    def test_daily_report_html(self):
        payload = NotificationPayload(
            notification_type="daily_report",
            title="Daily Report",
            body="Portfolio: +$342",
        )
        text = EmailRenderer().render_daily_report(payload)
        assert "Daily Report" in text


class TestEmailSubjectLine:
    def test_subject_from_payload(self):
        payload = NotificationPayload(
            notification_type="weekly_summary",
            title="Weekly Summary — Feb 24–Mar 1",
            body="Content",
        )
        subject = EmailRenderer().build_subject(payload)
        assert "Weekly Summary" in subject

    def test_critical_alert_subject(self):
        payload = NotificationPayload(
            notification_type="alert",
            priority=NotificationPriority.CRITICAL,
            title="Bot crash",
            body="Details",
        )
        subject = EmailRenderer().build_subject(payload)
        assert "CRITICAL" in subject or "🚨" in subject
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_email_renderer.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'comms.email_renderer'`

**Step 3: Write minimal implementation**

```python
# comms/email_renderer.py
"""Email HTML renderer — produces HTML email bodies with inline CSS.

For email client compatibility, all styles are inline.
No external template files — templates are embedded as strings.
"""
from __future__ import annotations

from schemas.notifications import (
    ControlPanelState,
    NotificationPayload,
    NotificationPriority,
)

_BASE_STYLE = (
    "font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; "
    "font-size: 14px; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;"
)
_HEADER_STYLE = "font-size: 20px; font-weight: bold; color: #1a1a1a; margin-bottom: 16px;"
_CRITICAL_STYLE = "background-color: #fee; border-left: 4px solid #f44; padding: 12px;"


def _body_to_html(body: str) -> str:
    """Convert newline-separated text into HTML paragraphs."""
    paragraphs = body.split("\n\n")
    parts: list[str] = []
    for p in paragraphs:
        lines = p.strip().replace("\n", "<br>")
        if lines:
            parts.append(f"<p>{lines}</p>")
    return "\n".join(parts)


def _wrap_html(title: str, body_html: str) -> str:
    return (
        f'<html><head><meta charset="utf-8"></head>'
        f'<body style="{_BASE_STYLE}">'
        f'<h1 style="{_HEADER_STYLE}">{title}</h1>'
        f'{body_html}'
        f'</body></html>'
    )


class EmailRenderer:
    """Renders notifications as HTML email bodies."""

    def render(self, payload: NotificationPayload) -> str:
        dispatch = {
            "alert": self.render_alert,
            "daily_report": self.render_daily_report,
            "weekly_summary": self.render_weekly_summary,
        }
        handler = dispatch.get(payload.notification_type)
        if handler:
            return handler(payload)
        return f"{payload.title}\n\n{payload.body}"

    def render_control_panel(self, panel: ControlPanelState) -> str:
        lines: list[str] = [f"Control Panel — {panel.date}"]
        for bot in panel.bot_statuses:
            lines.append(f"{bot.status_emoji} {bot.bot_id}: +${bot.pnl:.0f}")
        return "\n".join(lines)

    def render_alert(self, payload: NotificationPayload) -> str:
        priority = payload.priority.value.upper()
        body_html = f'<div style="{_CRITICAL_STYLE}">{_body_to_html(payload.body)}</div>'
        return _wrap_html(f"[{priority}] {payload.title}", body_html)

    def render_daily_report(self, payload: NotificationPayload) -> str:
        body_html = _body_to_html(payload.body)
        return _wrap_html(f"📊 {payload.title}", body_html)

    def render_weekly_summary(self, payload: NotificationPayload) -> str:
        return self.render_weekly_html(payload)

    def render_weekly_html(self, payload: NotificationPayload) -> str:
        body_html = _body_to_html(payload.body)
        return _wrap_html(f"📈 {payload.title}", body_html)

    def build_subject(self, payload: NotificationPayload) -> str:
        """Build an email subject line from the payload."""
        if payload.priority == NotificationPriority.CRITICAL:
            return f"🚨 CRITICAL: {payload.title}"
        return payload.title
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_email_renderer.py -v`
Expected: All 9 tests PASS

**Step 5: Commit**

```bash
git add comms/email_renderer.py tests/test_email_renderer.py
git commit -m "feat(phase6): add EmailRenderer with inline-CSS HTML templates"
```

---

## Task 9: Email Adapter

**Files:**
- Create: `comms/email_adapter.py`
- Test: `tests/test_email_adapter.py`

**Step 1: Write the failing test**

```python
# tests/test_email_adapter.py
"""Tests for async email adapter.

Uses mock SMTP — no real email sending.
"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from comms.email_adapter import EmailAdapter, EmailConfig


class TestEmailConfig:
    def test_defaults(self):
        cfg = EmailConfig(
            smtp_host="smtp.gmail.com",
            smtp_port=587,
            username="test@example.com",
            password="secret",
            from_address="bot@example.com",
        )
        assert cfg.smtp_host == "smtp.gmail.com"
        assert cfg.use_tls is True

    def test_custom_config(self):
        cfg = EmailConfig(
            smtp_host="localhost",
            smtp_port=25,
            username="",
            password="",
            from_address="bot@local",
            use_tls=False,
        )
        assert cfg.use_tls is False


class TestEmailAdapter:
    @pytest.fixture
    def mock_smtp(self):
        smtp = AsyncMock()
        smtp.connect = AsyncMock()
        smtp.starttls = AsyncMock()
        smtp.login = AsyncMock()
        smtp.send_message = AsyncMock()
        smtp.quit = AsyncMock()
        return smtp

    @pytest.fixture
    def adapter(self):
        config = EmailConfig(
            smtp_host="smtp.gmail.com",
            smtp_port=587,
            username="test@example.com",
            password="secret",
            from_address="bot@example.com",
        )
        return EmailAdapter(config)

    @pytest.mark.asyncio
    async def test_send_email(self, adapter, mock_smtp):
        adapter._create_smtp = lambda: mock_smtp
        await adapter.send(
            to="user@example.com",
            subject="Test Subject",
            html_body="<html><body>Hello</body></html>",
        )
        mock_smtp.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_email_with_attachments(self, adapter, mock_smtp):
        adapter._create_smtp = lambda: mock_smtp
        await adapter.send(
            to="user@example.com",
            subject="Weekly Digest",
            html_body="<html><body>Report</body></html>",
            attachment_paths=[],
        )
        mock_smtp.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_calls_connect_and_quit(self, adapter, mock_smtp):
        adapter._create_smtp = lambda: mock_smtp
        await adapter.send(
            to="user@example.com",
            subject="Test",
            html_body="<html><body>Hi</body></html>",
        )
        mock_smtp.connect.assert_called_once()
        mock_smtp.quit.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_with_tls(self, adapter, mock_smtp):
        adapter._create_smtp = lambda: mock_smtp
        await adapter.send(
            to="user@example.com",
            subject="Test",
            html_body="<html><body>Hi</body></html>",
        )
        mock_smtp.starttls.assert_called_once()
        mock_smtp.login.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_without_tls(self, mock_smtp):
        config = EmailConfig(
            smtp_host="localhost",
            smtp_port=25,
            username="",
            password="",
            from_address="bot@local",
            use_tls=False,
        )
        adapter = EmailAdapter(config)
        adapter._create_smtp = lambda: mock_smtp
        await adapter.send(to="user@local", subject="Test", html_body="<html>Hi</html>")
        mock_smtp.starttls.assert_not_called()
        mock_smtp.login.assert_not_called()
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_email_adapter.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'comms.email_adapter'`

**Step 3: Write minimal implementation**

```python
# comms/email_adapter.py
"""Async email adapter — sends HTML emails via SMTP.

Uses aiosmtplib for async SMTP. In tests, _create_smtp is overridden
to return a mock.
"""
from __future__ import annotations

from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path


@dataclass
class EmailConfig:
    smtp_host: str
    smtp_port: int
    username: str
    password: str
    from_address: str
    use_tls: bool = True


class EmailAdapter:
    """Async email sender."""

    def __init__(self, config: EmailConfig) -> None:
        self._config = config

    def _create_smtp(self):
        """Create an aiosmtplib.SMTP instance. Overridden in tests."""
        import aiosmtplib
        return aiosmtplib.SMTP(
            hostname=self._config.smtp_host,
            port=self._config.smtp_port,
        )

    async def send(
        self,
        to: str,
        subject: str,
        html_body: str,
        attachment_paths: list[str] | None = None,
    ) -> None:
        """Send an HTML email, optionally with file attachments."""
        msg = EmailMessage()
        msg["From"] = self._config.from_address
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(html_body, subtype="html")

        if attachment_paths:
            for path_str in attachment_paths:
                path = Path(path_str)
                if path.exists():
                    data = path.read_bytes()
                    msg.add_attachment(
                        data,
                        maintype="application",
                        subtype="octet-stream",
                        filename=path.name,
                    )

        smtp = self._create_smtp()
        await smtp.connect()

        if self._config.use_tls:
            await smtp.starttls()
            await smtp.login(self._config.username, self._config.password)

        await smtp.send_message(msg)
        await smtp.quit()
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_email_adapter.py -v`
Expected: All 6 tests PASS

**Step 5: Commit**

```bash
git add comms/email_adapter.py tests/test_email_adapter.py
git commit -m "feat(phase6): add async EmailAdapter with TLS + attachment support"
```

---

## Task 10: Notification Dispatcher

**Files:**
- Create: `comms/dispatcher.py`
- Test: `tests/test_dispatcher.py`

**Step 1: Write the failing test**

```python
# tests/test_dispatcher.py
"""Tests for the central notification dispatcher.

Routes NotificationPayloads to channel adapters based on user preferences,
priority, and quiet hours.
"""
import pytest
from unittest.mock import AsyncMock

from comms.dispatcher import NotificationDispatcher, ChannelAdapter
from schemas.notifications import (
    NotificationChannel,
    NotificationPriority,
    NotificationPreferences,
    ChannelConfig,
    NotificationPayload,
)


class TestDispatcherInit:
    def test_register_adapter(self):
        dispatcher = NotificationDispatcher()
        adapter = AsyncMock(spec=ChannelAdapter)
        dispatcher.register_adapter(NotificationChannel.TELEGRAM, adapter)
        assert NotificationChannel.TELEGRAM in dispatcher.adapters


class TestDispatchRouting:
    @pytest.fixture
    def telegram_adapter(self):
        a = AsyncMock(spec=ChannelAdapter)
        a.send = AsyncMock()
        return a

    @pytest.fixture
    def discord_adapter(self):
        a = AsyncMock(spec=ChannelAdapter)
        a.send = AsyncMock()
        return a

    @pytest.fixture
    def prefs(self):
        return NotificationPreferences(
            channels=[
                ChannelConfig(channel=NotificationChannel.TELEGRAM, enabled=True, chat_id="12345"),
                ChannelConfig(channel=NotificationChannel.DISCORD, enabled=True, chat_id="67890"),
            ]
        )

    @pytest.fixture
    def dispatcher(self, telegram_adapter, discord_adapter):
        d = NotificationDispatcher()
        d.register_adapter(NotificationChannel.TELEGRAM, telegram_adapter)
        d.register_adapter(NotificationChannel.DISCORD, discord_adapter)
        return d

    @pytest.mark.asyncio
    async def test_dispatches_to_all_active_channels(self, dispatcher, prefs, telegram_adapter, discord_adapter):
        payload = NotificationPayload(
            notification_type="daily_report",
            priority=NotificationPriority.NORMAL,
            title="Daily Report",
            body="Content",
        )
        await dispatcher.dispatch(payload, prefs, current_hour_utc=12)
        telegram_adapter.send.assert_called_once()
        discord_adapter.send.assert_called_once()

    @pytest.mark.asyncio
    async def test_skips_disabled_channel(self, dispatcher, prefs, telegram_adapter, discord_adapter):
        prefs.channels[1].enabled = False  # Disable Discord
        payload = NotificationPayload(
            notification_type="alert",
            priority=NotificationPriority.NORMAL,
            title="Test",
            body="Body",
        )
        await dispatcher.dispatch(payload, prefs, current_hour_utc=12)
        telegram_adapter.send.assert_called_once()
        discord_adapter.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_respects_quiet_hours(self, dispatcher, telegram_adapter, discord_adapter):
        prefs = NotificationPreferences(
            channels=[
                ChannelConfig(
                    channel=NotificationChannel.TELEGRAM,
                    quiet_hours_start=22,
                    quiet_hours_end=8,
                ),
                ChannelConfig(channel=NotificationChannel.DISCORD, enabled=True),
            ]
        )
        payload = NotificationPayload(
            notification_type="daily_report",
            priority=NotificationPriority.NORMAL,
            title="Report",
            body="Content",
        )
        await dispatcher.dispatch(payload, prefs, current_hour_utc=3)
        # Telegram should be skipped (quiet hours), Discord should receive
        telegram_adapter.send.assert_not_called()
        discord_adapter.send.assert_called_once()

    @pytest.mark.asyncio
    async def test_critical_bypasses_quiet_hours(self, dispatcher, telegram_adapter, discord_adapter):
        prefs = NotificationPreferences(
            channels=[
                ChannelConfig(
                    channel=NotificationChannel.TELEGRAM,
                    quiet_hours_start=22,
                    quiet_hours_end=8,
                ),
            ]
        )
        payload = NotificationPayload(
            notification_type="alert",
            priority=NotificationPriority.CRITICAL,
            title="CRASH",
            body="Bot3 down",
        )
        await dispatcher.dispatch(payload, prefs, current_hour_utc=3)
        telegram_adapter.send.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_adapters_registered(self):
        dispatcher = NotificationDispatcher()
        prefs = NotificationPreferences(
            channels=[ChannelConfig(channel=NotificationChannel.TELEGRAM)]
        )
        payload = NotificationPayload(
            notification_type="alert",
            title="Test",
            body="Body",
        )
        # Should not raise — just logs warning
        await dispatcher.dispatch(payload, prefs, current_hour_utc=12)

    @pytest.mark.asyncio
    async def test_dispatch_returns_delivery_results(self, dispatcher, prefs, telegram_adapter, discord_adapter):
        payload = NotificationPayload(
            notification_type="daily_report",
            title="Report",
            body="Content",
        )
        results = await dispatcher.dispatch(payload, prefs, current_hour_utc=12)
        assert len(results) == 2
        assert all(r.success for r in results)

    @pytest.mark.asyncio
    async def test_adapter_failure_doesnt_block_others(self, dispatcher, prefs, telegram_adapter, discord_adapter):
        telegram_adapter.send.side_effect = Exception("Network error")
        payload = NotificationPayload(
            notification_type="alert",
            title="Test",
            body="Body",
        )
        results = await dispatcher.dispatch(payload, prefs, current_hour_utc=12)
        # Telegram failed, Discord succeeded
        assert results[0].success is False
        assert results[1].success is True
        discord_adapter.send.assert_called_once()
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_dispatcher.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'comms.dispatcher'`

**Step 3: Write minimal implementation**

```python
# comms/dispatcher.py
"""Notification dispatcher — routes payloads to channel adapters.

Respects user preferences, quiet hours, and priority-based bypass rules.
Each adapter failure is isolated — one channel failing doesn't block others.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from schemas.notifications import (
    NotificationChannel,
    NotificationPayload,
    NotificationPreferences,
    ChannelConfig,
)

logger = logging.getLogger(__name__)


@runtime_checkable
class ChannelAdapter(Protocol):
    """Protocol for channel adapters that can send notifications."""

    async def send(self, payload: NotificationPayload, channel_config: ChannelConfig) -> None: ...


@dataclass
class DeliveryResult:
    channel: NotificationChannel
    success: bool
    error: str = ""


class NotificationDispatcher:
    """Routes notifications to channel adapters based on user preferences."""

    def __init__(self) -> None:
        self._adapters: dict[NotificationChannel, ChannelAdapter] = {}

    @property
    def adapters(self) -> dict[NotificationChannel, ChannelAdapter]:
        return self._adapters

    def register_adapter(self, channel: NotificationChannel, adapter: ChannelAdapter) -> None:
        self._adapters[channel] = adapter

    async def dispatch(
        self,
        payload: NotificationPayload,
        prefs: NotificationPreferences,
        current_hour_utc: int,
    ) -> list[DeliveryResult]:
        """Send a notification to all eligible channels. Returns delivery results."""
        eligible = prefs.get_channels_for_priority(payload.priority, current_hour_utc)
        results: list[DeliveryResult] = []

        for cfg in eligible:
            adapter = self._adapters.get(cfg.channel)
            if adapter is None:
                logger.warning("No adapter registered for %s", cfg.channel.value)
                results.append(DeliveryResult(
                    channel=cfg.channel, success=False, error="No adapter registered"
                ))
                continue

            try:
                await adapter.send(payload, cfg)
                results.append(DeliveryResult(channel=cfg.channel, success=True))
            except Exception as e:
                logger.exception("Failed to send via %s", cfg.channel.value)
                results.append(DeliveryResult(
                    channel=cfg.channel, success=False, error=str(e)
                ))

        return results
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_dispatcher.py -v`
Expected: All 8 tests PASS

**Step 5: Commit**

```bash
git add comms/dispatcher.py tests/test_dispatcher.py
git commit -m "feat(phase6): add NotificationDispatcher with preference-aware routing"
```

---

## Task 11: Proactive Notification Scanner

**Files:**
- Create: `skills/proactive_scanner.py`
- Test: `tests/test_proactive_scanner.py`

**Step 1: Write the failing test**

```python
# tests/test_proactive_scanner.py
"""Tests for the proactive notification scanner.

Three scan modes:
  - morning_scan: overnight events, errors, unusual losses
  - continuous_scan: heartbeat staleness, CRITICAL escalation, crowding
  - evening_scan: daily report ready trigger
"""
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock

from skills.proactive_scanner import ProactiveScanner, ScanResult
from schemas.notifications import NotificationPayload, NotificationPriority


class TestMorningScan:
    @pytest.fixture
    def scanner(self):
        return ProactiveScanner()

    def test_no_events_returns_empty(self, scanner):
        result = scanner.morning_scan(events=[], errors=[], unusual_losses=[])
        assert result.has_notifications is False
        assert len(result.payloads) == 0

    def test_errors_produce_alert_payload(self, scanner):
        errors = [
            {"bot_id": "bot1", "error_type": "ConnectionError", "message": "Exchange API timeout", "severity": "HIGH"},
        ]
        result = scanner.morning_scan(events=[], errors=errors, unusual_losses=[])
        assert result.has_notifications is True
        assert len(result.payloads) == 1
        assert result.payloads[0].priority == NotificationPriority.HIGH

    def test_unusual_losses_produce_summary(self, scanner):
        losses = [
            {"bot_id": "bot2", "pnl": -500.0, "reason": "3 consecutive losses in trending market"},
        ]
        result = scanner.morning_scan(events=[], errors=[], unusual_losses=losses)
        assert result.has_notifications is True
        assert "bot2" in result.payloads[0].body.lower() or "bot2" in result.payloads[0].data.get("bot_id", "")

    def test_multiple_items_consolidated(self, scanner):
        errors = [
            {"bot_id": "bot1", "error_type": "ConnectionError", "message": "Timeout", "severity": "HIGH"},
            {"bot_id": "bot3", "error_type": "RuntimeError", "message": "Signal crash", "severity": "CRITICAL"},
        ]
        losses = [
            {"bot_id": "bot2", "pnl": -500.0, "reason": "Unusual drawdown"},
        ]
        result = scanner.morning_scan(events=[], errors=errors, unusual_losses=losses)
        assert result.has_notifications is True
        # Should produce a consolidated morning summary + escalated CRITICAL
        assert any(p.priority == NotificationPriority.CRITICAL for p in result.payloads)


class TestContinuousScan:
    @pytest.fixture
    def scanner(self):
        return ProactiveScanner()

    def test_no_alerts_returns_empty(self, scanner):
        result = scanner.continuous_scan(alerts=[])
        assert result.has_notifications is False

    def test_critical_alert_produces_immediate_payload(self, scanner):
        from orchestrator.monitoring import Alert, AlertSeverity
        alerts = [
            Alert(severity=AlertSeverity.CRITICAL, source="heartbeat", message="Bot3 heartbeat stale for 4h"),
        ]
        result = scanner.continuous_scan(alerts=alerts)
        assert result.has_notifications is True
        assert result.payloads[0].priority == NotificationPriority.CRITICAL

    def test_high_alert_produces_payload(self, scanner):
        from orchestrator.monitoring import Alert, AlertSeverity
        alerts = [
            Alert(severity=AlertSeverity.HIGH, source="stale_task", message="Daily analysis stuck"),
        ]
        result = scanner.continuous_scan(alerts=alerts)
        assert result.has_notifications is True
        assert result.payloads[0].priority == NotificationPriority.HIGH

    def test_low_alerts_batched(self, scanner):
        from orchestrator.monitoring import Alert, AlertSeverity
        alerts = [
            Alert(severity=AlertSeverity.LOW, source="run_output", message="Missing file A"),
            Alert(severity=AlertSeverity.LOW, source="run_output", message="Missing file B"),
        ]
        result = scanner.continuous_scan(alerts=alerts)
        # Low alerts should be batched into a single NORMAL-priority payload
        assert len(result.payloads) <= 1


class TestEveningScan:
    @pytest.fixture
    def scanner(self):
        return ProactiveScanner()

    def test_evening_scan_produces_report_trigger(self, scanner):
        result = scanner.evening_scan(date="2026-03-01", daily_report_ready=True)
        assert result.has_notifications is True
        assert result.payloads[0].notification_type == "daily_report"

    def test_evening_scan_not_ready(self, scanner):
        result = scanner.evening_scan(date="2026-03-01", daily_report_ready=False)
        assert result.has_notifications is True
        # Should send a "report pending" notification
        assert "pending" in result.payloads[0].body.lower() or "not ready" in result.payloads[0].body.lower()
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_proactive_scanner.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'skills.proactive_scanner'`

**Step 3: Write minimal implementation**

```python
# skills/proactive_scanner.py
"""Proactive notification scanner — morning, continuous, and evening scans.

No LLM calls. Deterministic event processing to produce notification payloads.
Integrates with the monitoring loop's Alert objects and the scheduler.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from schemas.notifications import NotificationPayload, NotificationPriority


@dataclass
class ScanResult:
    """Outcome of a proactive scan — zero or more notification payloads."""

    payloads: list[NotificationPayload] = field(default_factory=list)

    @property
    def has_notifications(self) -> bool:
        return len(self.payloads) > 0


_SEVERITY_TO_PRIORITY = {
    "CRITICAL": NotificationPriority.CRITICAL,
    "HIGH": NotificationPriority.HIGH,
    "MEDIUM": NotificationPriority.NORMAL,
    "LOW": NotificationPriority.LOW,
}


class ProactiveScanner:
    """Produces notification payloads from system state checks."""

    def morning_scan(
        self,
        events: list[dict],
        errors: list[dict],
        unusual_losses: list[dict],
    ) -> ScanResult:
        """Scan overnight events and produce a morning summary."""
        payloads: list[NotificationPayload] = []

        # Escalate CRITICAL errors immediately
        for error in errors:
            severity = error.get("severity", "MEDIUM").upper()
            priority = _SEVERITY_TO_PRIORITY.get(severity, NotificationPriority.NORMAL)
            payloads.append(NotificationPayload(
                notification_type="alert",
                priority=priority,
                title=f"{error.get('bot_id', '?')} — {error.get('error_type', 'Error')}",
                body=error.get("message", ""),
                data=error,
            ))

        # Unusual losses summary
        for loss in unusual_losses:
            payloads.append(NotificationPayload(
                notification_type="alert",
                priority=NotificationPriority.HIGH,
                title=f"Unusual loss — {loss.get('bot_id', '?')}",
                body=f"PnL: ${loss.get('pnl', 0):.0f} — {loss.get('reason', '')}",
                data=loss,
            ))

        return ScanResult(payloads=payloads)

    def continuous_scan(self, alerts: list) -> ScanResult:
        """Convert monitoring alerts into notification payloads.

        Args:
            alerts: list of orchestrator.monitoring.Alert objects.
        """
        payloads: list[NotificationPayload] = []
        low_alerts: list[str] = []

        for alert in alerts:
            severity_str = alert.severity.value.upper()
            priority = _SEVERITY_TO_PRIORITY.get(severity_str, NotificationPriority.NORMAL)

            if priority in (NotificationPriority.LOW,):
                low_alerts.append(alert.message)
                continue

            payloads.append(NotificationPayload(
                notification_type="alert",
                priority=priority,
                title=f"{alert.source} alert",
                body=alert.message,
            ))

        # Batch low alerts into a single payload
        if low_alerts:
            payloads.append(NotificationPayload(
                notification_type="alert",
                priority=NotificationPriority.LOW,
                title=f"{len(low_alerts)} low-priority alert(s)",
                body="\n".join(f"- {m}" for m in low_alerts),
            ))

        return ScanResult(payloads=payloads)

    def evening_scan(self, date: str, daily_report_ready: bool) -> ScanResult:
        """Trigger the evening daily report notification."""
        if daily_report_ready:
            return ScanResult(payloads=[
                NotificationPayload(
                    notification_type="daily_report",
                    priority=NotificationPriority.NORMAL,
                    title=f"Daily Report — {date}",
                    body=f"Your daily trading report for {date} is ready.",
                    data={"date": date},
                )
            ])
        else:
            return ScanResult(payloads=[
                NotificationPayload(
                    notification_type="alert",
                    priority=NotificationPriority.LOW,
                    title=f"Daily report pending — {date}",
                    body=f"Daily report for {date} is not ready yet. Analysis may still be running.",
                    data={"date": date},
                )
            ])
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_proactive_scanner.py -v`
Expected: All 10 tests PASS

**Step 5: Commit**

```bash
git add skills/proactive_scanner.py tests/test_proactive_scanner.py
git commit -m "feat(phase6): add ProactiveScanner — morning/continuous/evening scans"
```

---

## Task 12: Orchestrator Wiring — Brain + Worker + Scheduler

**Files:**
- Modify: `orchestrator/orchestrator_brain.py` — add `SEND_NOTIFICATION` action type
- Modify: `orchestrator/worker.py` — add `on_notification` callback, wire dispatcher
- Modify: `orchestrator/scheduler.py` — add morning/evening scan config
- Test: `tests/test_comms_orchestrator_wiring.py`

**Step 1: Write the failing test**

```python
# tests/test_comms_orchestrator_wiring.py
"""Tests for Phase 6 orchestrator wiring.

Verifies that:
  1. Brain routes notification_trigger events to SEND_NOTIFICATION action
  2. Worker dispatches SEND_NOTIFICATION to on_notification callback
  3. Scheduler has morning_scan and evening_report cron jobs
"""
import pytest
from unittest.mock import AsyncMock

from orchestrator.orchestrator_brain import OrchestratorBrain, ActionType
from orchestrator.worker import Worker
from orchestrator.scheduler import SchedulerConfig, create_scheduler_jobs


class TestBrainNotificationRouting:
    def test_notification_trigger_event(self):
        brain = OrchestratorBrain()
        event = {
            "event_type": "notification_trigger",
            "event_id": "notif-001",
            "bot_id": "system",
            "payload": '{"type": "daily_report"}',
        }
        actions = brain.decide(event)
        assert len(actions) == 1
        assert actions[0].type == ActionType.SEND_NOTIFICATION

    def test_send_notification_action_type_exists(self):
        assert hasattr(ActionType, "SEND_NOTIFICATION")
        assert ActionType.SEND_NOTIFICATION == "send_notification"


class TestWorkerNotificationDispatch:
    @pytest.fixture
    def mock_queue(self):
        q = AsyncMock()
        q.peek = AsyncMock(return_value=[])
        q.ack = AsyncMock()
        return q

    @pytest.fixture
    def mock_registry(self):
        return AsyncMock()

    @pytest.fixture
    def worker(self, mock_queue, mock_registry):
        brain = OrchestratorBrain()
        return Worker(queue=mock_queue, registry=mock_registry, brain=brain)

    def test_on_notification_callback_exists(self, worker):
        assert hasattr(worker, "on_notification")

    @pytest.mark.asyncio
    async def test_notification_action_calls_on_notification(self, worker, mock_queue):
        handler = AsyncMock()
        worker.on_notification = handler

        mock_queue.peek = AsyncMock(return_value=[{
            "event_type": "notification_trigger",
            "event_id": "notif-001",
            "bot_id": "system",
            "payload": '{"type": "daily_report"}',
        }])

        await worker.process_batch(limit=1)
        handler.assert_called_once()

    @pytest.mark.asyncio
    async def test_notification_without_handler_logs(self, worker, mock_queue):
        """Should not raise even without handler — just log."""
        mock_queue.peek = AsyncMock(return_value=[{
            "event_type": "notification_trigger",
            "event_id": "notif-001",
            "bot_id": "system",
            "payload": '{"type": "daily_report"}',
        }])
        # No handler set
        processed = await worker.process_batch(limit=1)
        assert processed == 1


class TestSchedulerNotificationJobs:
    def test_morning_scan_config(self):
        config = SchedulerConfig()
        assert hasattr(config, "morning_scan_hour")
        assert hasattr(config, "morning_scan_minute")

    def test_evening_report_config(self):
        config = SchedulerConfig()
        assert hasattr(config, "evening_report_hour")
        assert hasattr(config, "evening_report_minute")

    def test_morning_scan_job_created(self):
        config = SchedulerConfig()
        morning_fn = AsyncMock()
        jobs = create_scheduler_jobs(
            config,
            worker_fn=AsyncMock(),
            monitoring_fn=AsyncMock(),
            relay_fn=AsyncMock(),
            morning_scan_fn=morning_fn,
        )
        job_names = [j["name"] for j in jobs]
        assert "morning_scan" in job_names

    def test_evening_report_job_created(self):
        config = SchedulerConfig()
        evening_fn = AsyncMock()
        jobs = create_scheduler_jobs(
            config,
            worker_fn=AsyncMock(),
            monitoring_fn=AsyncMock(),
            relay_fn=AsyncMock(),
            evening_report_fn=evening_fn,
        )
        job_names = [j["name"] for j in jobs]
        assert "evening_report" in job_names

    def test_default_morning_scan_hour(self):
        config = SchedulerConfig()
        assert config.morning_scan_hour == 7  # 7 UTC

    def test_default_evening_report_hour(self):
        config = SchedulerConfig()
        assert config.evening_report_hour == 22  # 22 UTC
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_comms_orchestrator_wiring.py -v`
Expected: FAIL — `AttributeError: 'ActionType' has no attribute 'SEND_NOTIFICATION'`

**Step 3: Write minimal implementation**

Modify `orchestrator/orchestrator_brain.py` — add to `ActionType` enum and add handler:

```python
# In ActionType enum, add:
    SEND_NOTIFICATION = "send_notification"

# Add handler method:
    def _handle_notification_trigger(self, event_id: str, bot_id: str, event: dict) -> list[Action]:
        return [Action(type=ActionType.SEND_NOTIFICATION, event_id=event_id, bot_id=bot_id)]

# In _handlers dict, add:
        "notification_trigger": _handle_notification_trigger,
```

Modify `orchestrator/worker.py` — add `on_notification` callback and dispatch:

```python
# In __init__, add:
        self.on_notification: Callable[[Action], Awaitable[None]] | None = None

# In _dispatch(), add before the QUEUE_FOR_DAILY elif:
        elif action.type == ActionType.SEND_NOTIFICATION:
            if self.on_notification:
                await self.on_notification(action)
            else:
                logger.info("Notification triggered but no handler set: %s", action.event_id)
```

Modify `orchestrator/scheduler.py` — add morning/evening config and jobs:

```python
# In SchedulerConfig, add:
    morning_scan_hour: int = 7
    morning_scan_minute: int = 0
    evening_report_hour: int = 22
    evening_report_minute: int = 0

# In create_scheduler_jobs(), add parameters:
    morning_scan_fn: Callable[[], Awaitable[None]] | None = None,
    evening_report_fn: Callable[[], Awaitable[None]] | None = None,

# In create_scheduler_jobs(), add jobs:
    if morning_scan_fn is not None:
        jobs.append({
            "name": "morning_scan",
            "func": morning_scan_fn,
            "trigger": "cron",
            "hour": config.morning_scan_hour,
            "minute": config.morning_scan_minute,
        })

    if evening_report_fn is not None:
        jobs.append({
            "name": "evening_report",
            "func": evening_report_fn,
            "trigger": "cron",
            "hour": config.evening_report_hour,
            "minute": config.evening_report_minute,
        })
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_comms_orchestrator_wiring.py -v`
Expected: All 9 tests PASS

**Step 5: Verify existing tests still pass**

Run: `python -m pytest tests/test_orchestrator_brain.py tests/test_worker.py tests/test_scheduler.py -v`
Expected: All existing tests PASS (no regressions)

**Step 6: Commit**

```bash
git add orchestrator/orchestrator_brain.py orchestrator/worker.py orchestrator/scheduler.py tests/test_comms_orchestrator_wiring.py
git commit -m "feat(phase6): wire notification dispatch into brain/worker/scheduler"
```

---

## Task 13: Integration Test

**Files:**
- Test: `tests/test_comms_integration.py`

**Step 1: Write the integration test**

```python
# tests/test_comms_integration.py
"""Integration test for the full Phase 6 communication pipeline.

Tests the flow: event → brain → worker → proactive scanner → dispatcher → channel adapters.
All external services (Telegram, Discord, SMTP) are mocked.
"""
import pytest
from unittest.mock import AsyncMock

from orchestrator.orchestrator_brain import OrchestratorBrain, ActionType
from orchestrator.worker import Worker
from orchestrator.db.queue import EventQueue
from orchestrator.task_registry import TaskRegistry
from orchestrator.monitoring import MonitoringLoop, MonitoringCheck, Alert, AlertSeverity
from skills.proactive_scanner import ProactiveScanner
from comms.dispatcher import NotificationDispatcher, ChannelAdapter
from comms.renderer import PlainTextRenderer
from comms.telegram_renderer import TelegramRenderer
from comms.telegram_control_surface import ControlSurface
from comms.telegram_bot import TelegramBotAdapter, TelegramBotConfig
from schemas.notifications import (
    NotificationChannel,
    NotificationPriority,
    NotificationPreferences,
    ChannelConfig,
    NotificationPayload,
    ControlPanelState,
    BotStatusLine,
)


class TestFullNotificationPipeline:
    """End-to-end: event arrives → brain decides → worker dispatches → notification sent."""

    @pytest.fixture
    def mock_telegram_adapter(self):
        adapter = AsyncMock(spec=ChannelAdapter)
        adapter.send = AsyncMock()
        return adapter

    @pytest.fixture
    def mock_discord_adapter(self):
        adapter = AsyncMock(spec=ChannelAdapter)
        adapter.send = AsyncMock()
        return adapter

    @pytest.fixture
    def prefs(self):
        return NotificationPreferences(
            channels=[
                ChannelConfig(channel=NotificationChannel.TELEGRAM, enabled=True, chat_id="12345"),
                ChannelConfig(channel=NotificationChannel.DISCORD, enabled=True, chat_id="67890"),
            ]
        )

    @pytest.fixture
    def dispatcher(self, mock_telegram_adapter, mock_discord_adapter):
        d = NotificationDispatcher()
        d.register_adapter(NotificationChannel.TELEGRAM, mock_telegram_adapter)
        d.register_adapter(NotificationChannel.DISCORD, mock_discord_adapter)
        return d

    @pytest.mark.asyncio
    async def test_critical_error_dispatches_to_all_channels(self, dispatcher, prefs, mock_telegram_adapter, mock_discord_adapter):
        """CRITICAL error should reach all active channels, even during quiet hours."""
        prefs.channels[0].quiet_hours_start = 22
        prefs.channels[0].quiet_hours_end = 8

        payload = NotificationPayload(
            notification_type="alert",
            priority=NotificationPriority.CRITICAL,
            title="Bot3 crash",
            body="RuntimeError in signal handler",
        )

        results = await dispatcher.dispatch(payload, prefs, current_hour_utc=3)
        assert all(r.success for r in results)
        mock_telegram_adapter.send.assert_called_once()
        mock_discord_adapter.send.assert_called_once()


class TestProactiveScannerToDispatcher:
    """Morning scan → payloads → dispatcher → channels."""

    @pytest.mark.asyncio
    async def test_morning_errors_dispatched(self):
        scanner = ProactiveScanner()
        errors = [
            {"bot_id": "bot1", "error_type": "ConnectionError", "message": "Timeout", "severity": "HIGH"},
        ]
        result = scanner.morning_scan(events=[], errors=errors, unusual_losses=[])

        mock_adapter = AsyncMock(spec=ChannelAdapter)
        mock_adapter.send = AsyncMock()
        dispatcher = NotificationDispatcher()
        dispatcher.register_adapter(NotificationChannel.TELEGRAM, mock_adapter)

        prefs = NotificationPreferences(
            channels=[ChannelConfig(channel=NotificationChannel.TELEGRAM)]
        )

        for payload in result.payloads:
            await dispatcher.dispatch(payload, prefs, current_hour_utc=7)

        assert mock_adapter.send.call_count == 1


class TestControlSurfaceIntegration:
    """Control surface updates are rendered and sent."""

    @pytest.mark.asyncio
    async def test_publish_and_update_panel(self):
        config = TelegramBotConfig(token="fake", chat_id="12345")
        adapter = TelegramBotAdapter(config)
        adapter._bot = AsyncMock()
        adapter._bot.send_message = AsyncMock(return_value=AsyncMock(message_id=100))
        adapter._bot.edit_message_text = AsyncMock()
        adapter._bot.pin_chat_message = AsyncMock()

        surface = ControlSurface(adapter=adapter, renderer=TelegramRenderer())

        panel = ControlPanelState(
            date="2026-03-01",
            portfolio_pnl=342.0,
            portfolio_pnl_pct=1.2,
            drawdown_pct=-0.3,
            exposure_pct=47.0,
            bot_statuses=[
                BotStatusLine(bot_id="Bot1", status="green", pnl=210.0, wins=4, losses=1, summary="Strong"),
            ],
        )

        await surface.publish(panel)
        assert surface.current_message_id == 100

        # Update with new alert
        await surface.update_field(alert_count=1, alert_summary="Bot3 volume filter")
        adapter._bot.edit_message_text.assert_called_once()


class TestRenderersProduceValidOutput:
    """Smoke test: all renderers produce non-empty strings."""

    def test_plain_text_daily(self):
        payload = NotificationPayload(
            notification_type="daily_report",
            title="Daily Report",
            body="Portfolio: +$342",
        )
        text = PlainTextRenderer().render(payload)
        assert len(text) > 0

    def test_telegram_daily(self):
        payload = NotificationPayload(
            notification_type="daily_report",
            title="Daily Report",
            body="Portfolio: +$342",
        )
        text = TelegramRenderer().render(payload)
        assert len(text) > 0

    def test_plain_text_alert(self):
        payload = NotificationPayload(
            notification_type="alert",
            priority=NotificationPriority.CRITICAL,
            title="Crash",
            body="Details",
        )
        text = PlainTextRenderer().render(payload)
        assert "CRITICAL" in text

    def test_telegram_alert(self):
        payload = NotificationPayload(
            notification_type="alert",
            priority=NotificationPriority.CRITICAL,
            title="Crash",
            body="Details",
        )
        text = TelegramRenderer().render(payload)
        assert "🚨" in text


class TestBrainToWorkerNotificationFlow:
    """Brain routes notification_trigger → Worker dispatches to handler."""

    @pytest.mark.asyncio
    async def test_notification_event_flow(self):
        brain = OrchestratorBrain()
        event = {
            "event_type": "notification_trigger",
            "event_id": "notif-001",
            "bot_id": "system",
            "payload": '{"type": "daily_report"}',
        }

        actions = brain.decide(event)
        assert len(actions) == 1
        assert actions[0].type == ActionType.SEND_NOTIFICATION

        # Verify worker can dispatch this
        mock_queue = AsyncMock()
        mock_queue.peek = AsyncMock(return_value=[event])
        mock_queue.ack = AsyncMock()
        mock_registry = AsyncMock()

        worker = Worker(queue=mock_queue, registry=mock_registry, brain=brain)
        handler = AsyncMock()
        worker.on_notification = handler

        await worker.process_batch(limit=1)
        handler.assert_called_once()
```

**Step 2: Run to verify it fails initially (before Task 12 implementation)**

Run: `python -m pytest tests/test_comms_integration.py -v`
Expected: PASS (if Tasks 0–12 are all implemented)

**Step 3: Commit**

```bash
git add tests/test_comms_integration.py
git commit -m "test(phase6): add integration test for full notification pipeline"
```

---

## Task 14: FastAPI Notification Endpoints

**Files:**
- Modify: `orchestrator/app.py` — add `/notifications/preferences` endpoints
- Test: (covered by integration test above + existing test_integration.py patterns)

**Step 1: Write the failing test**

```python
# Add to tests/test_comms_integration.py (or create a separate test file)

class TestNotificationEndpoints:
    """FastAPI endpoints for notification preferences."""

    @pytest.fixture
    def app(self, tmp_path):
        from orchestrator.app import create_app
        return create_app(db_dir=str(tmp_path))

    @pytest.mark.asyncio
    async def test_get_preferences_returns_defaults(self, app):
        from httpx import AsyncClient, ASGITransport
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            await app.state.queue.initialize()
            await app.state.registry.initialize()
            resp = await client.get("/notifications/preferences")
            assert resp.status_code == 200
            data = resp.json()
            assert "channels" in data

    @pytest.mark.asyncio
    async def test_update_preferences(self, app):
        from httpx import AsyncClient, ASGITransport
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            await app.state.queue.initialize()
            await app.state.registry.initialize()
            resp = await client.put("/notifications/preferences", json={
                "channels": [
                    {"channel": "telegram", "enabled": True, "chat_id": "12345"},
                ]
            })
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["channels"]) == 1
            assert data["channels"][0]["chat_id"] == "12345"
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_comms_integration.py::TestNotificationEndpoints -v`
Expected: FAIL — 404 on `/notifications/preferences`

**Step 3: Modify `orchestrator/app.py`**

Add the following endpoints inside `create_app()`, after the existing routes:

```python
    # In-memory preferences (persisted via settings file in production)
    from schemas.notifications import NotificationPreferences
    app.state.notification_preferences = NotificationPreferences()

    @app.get("/notifications/preferences")
    async def get_notification_preferences():
        return app.state.notification_preferences.model_dump()

    @app.put("/notifications/preferences")
    async def update_notification_preferences(prefs: NotificationPreferences):
        app.state.notification_preferences = prefs
        return prefs.model_dump()
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_comms_integration.py -v`
Expected: All tests PASS

**Step 5: Verify no regressions**

Run: `python -m pytest tests/ -v`
Expected: All tests PASS

**Step 6: Commit**

```bash
git add orchestrator/app.py tests/test_comms_integration.py
git commit -m "feat(phase6): add notification preferences API endpoints"
```

---

## Summary

| Task | Component | Tests | New Files | Modified Files |
|------|-----------|-------|-----------|----------------|
| 0 | Notification Schemas | ~16 | `schemas/notifications.py` | — |
| 1 | Renderer Protocol + Plain Text | ~10 | `comms/__init__.py`, `comms/renderer.py` | — |
| 2 | Telegram Renderer | ~16 | `comms/telegram_renderer.py` | — |
| 3 | Telegram Bot Adapter | ~8 | `comms/telegram_bot.py` | — |
| 4 | Control Surface | ~8 | `comms/telegram_control_surface.py` | — |
| 5 | Callback Handlers | ~9 | `comms/telegram_handlers.py` | — |
| 6 | Discord Renderer | ~10 | `comms/discord_renderer.py` | — |
| 7 | Discord Bot Adapter | ~6 | `comms/discord_bot.py` | — |
| 8 | Email Renderer | ~9 | `comms/email_renderer.py` | — |
| 9 | Email Adapter | ~6 | `comms/email_adapter.py` | — |
| 10 | Notification Dispatcher | ~8 | `comms/dispatcher.py` | — |
| 11 | Proactive Scanner | ~10 | `skills/proactive_scanner.py` | — |
| 12 | Orchestrator Wiring | ~9 | — | `orchestrator_brain.py`, `worker.py`, `scheduler.py` |
| 13 | Integration Test | ~10 | — | — |
| 14 | FastAPI Endpoints | ~2 | — | `orchestrator/app.py` |
| **Total** | | **~137** | **13 new** | **4 modified** |

**Dependencies:** Tasks 0–1 must go first (schemas + renderer protocol). Tasks 2–9 can be parallelized in pairs. Task 10 depends on all adapters. Task 11 is independent. Tasks 12–14 depend on everything else.
