# Multi-Provider Agent Runtime Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add provider-backed agent runtime switching with persisted global and per-workflow preferences across FastAPI and Telegram.

**Architecture:** Keep `AgentRunner.invoke(...)` as the public entrypoint, but route each invocation through a provider preference resolver plus a CLI backend registry. Persist preferences to `data/agent_preferences.json`, expose them over HTTP, and reuse the Telegram control surface for provider switching.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, Telegram Bot API, Claude Code CLI, Codex CLI

---

### Task 1: Preference Models and Persistence

**Files:**
- Create: `schemas/agent_preferences.py`
- Create: `orchestrator/agent_preferences.py`
- Modify: `orchestrator/config.py`
- Modify: `orchestrator/app.py`
- Test: `tests/test_app_wiring.py`
- Test: `tests/test_agent_preferences_api.py`

**Step 1: Write the failing tests**

Add tests for:
- loading/saving `data/agent_preferences.json`
- seeding defaults from env only when the file is missing
- surfacing the loaded preferences on `app.state`

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_app_wiring.py tests/test_agent_preferences_api.py -q`
Expected: FAIL because agent preference helpers and API endpoints do not exist yet.

**Step 3: Write minimal implementation**

Implement:
- `AgentProvider`, `AgentWorkflow`, `AgentSelection`, `AgentPreferences`, `AgentPreferencesView`
- `AgentPreferencesManager`
- env-backed seeding helpers in `orchestrator/app.py`
- new config keys for runtime commands and provider secrets

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_app_wiring.py tests/test_agent_preferences_api.py -q`
Expected: PASS

**Step 5: Commit**

```bash
git add schemas/agent_preferences.py orchestrator/agent_preferences.py orchestrator/config.py orchestrator/app.py tests/test_app_wiring.py tests/test_agent_preferences_api.py
git commit -m "feat: add persisted agent provider preferences"
```

### Task 2: Multi-Provider Agent Runner

**Files:**
- Modify: `orchestrator/agent_runner.py`
- Modify: `orchestrator/handlers.py`
- Test: `tests/test_agent_runner.py`
- Test: `tests/test_skills_registry_enforcement.py`

**Step 1: Write the failing test**

Add tests covering:
- workflow preference resolution
- Claude and Codex command construction
- Z.AI and OpenRouter env injection
- Codex JSONL parsing
- provider metadata recorded in session history
- unavailable provider rejection

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_agent_runner.py tests/test_skills_registry_enforcement.py -q`
Expected: FAIL because the runner is still Claude-only.

**Step 3: Write minimal implementation**

Implement:
- provider-aware invocation planning
- Claude-backed profiles for `claude_max`, `zai_coding_plan`, `openrouter`
- Codex-backed profile for `codex_pro`
- provider readiness checks and Codex preflight
- generic `agent_invocation` naming where the event was Claude-specific

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_agent_runner.py tests/test_skills_registry_enforcement.py -q`
Expected: PASS

**Step 5: Commit**

```bash
git add orchestrator/agent_runner.py orchestrator/handlers.py tests/test_agent_runner.py tests/test_skills_registry_enforcement.py
git commit -m "feat: add multi-provider agent runner backends"
```

### Task 3: HTTP and Telegram Switching UI

**Files:**
- Modify: `orchestrator/app.py`
- Modify: `comms/telegram_handlers.py`
- Modify: `comms/telegram_bot.py`
- Modify: `comms/telegram_renderer.py`
- Test: `tests/test_telegram_handlers.py`
- Test: `tests/test_telegram_bot.py`
- Test: `tests/test_telegram_renderer.py`

**Step 1: Write the failing test**

Add tests for:
- `/agent/preferences` GET and PUT
- Telegram `/settings`
- provider scope buttons and `Use Global`
- callback responses that edit existing messages

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_agent_preferences_api.py tests/test_telegram_handlers.py tests/test_telegram_bot.py tests/test_telegram_renderer.py -q`
Expected: FAIL because the routes and callback flows do not yet expose provider switching.

**Step 3: Write minimal implementation**

Implement:
- `GET /agent/preferences`
- `PUT /agent/preferences`
- `cmd_settings`
- callback router registration independent of approvals mode
- settings renderer and structured callback responses

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_agent_preferences_api.py tests/test_telegram_handlers.py tests/test_telegram_bot.py tests/test_telegram_renderer.py -q`
Expected: PASS

**Step 5: Commit**

```bash
git add orchestrator/app.py comms/telegram_handlers.py comms/telegram_bot.py comms/telegram_renderer.py tests/test_agent_preferences_api.py tests/test_telegram_handlers.py tests/test_telegram_bot.py tests/test_telegram_renderer.py
git commit -m "feat: add provider switching API and telegram settings"
```

### Task 4: Docs and Regression Coverage

**Files:**
- Modify: `.env.example`
- Modify: `README.md`
- Test: `tests/test_handlers.py`
- Test: `tests/test_comms_integration.py`
- Test: `tests/test_telegram_control_surface.py`

**Step 1: Write the failing test**

Ensure the existing integration tests still pass with the new default provider behavior.

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_handlers.py tests/test_comms_integration.py tests/test_telegram_control_surface.py -q`
Expected: PASS or reveal regressions to fix before documentation is finalized.

**Step 3: Write minimal implementation**

Document:
- provider defaults
- override precedence
- Z.AI Coding Plan constraint
- OpenRouter Claude-compatible behavior
- Codex preflight and Windows caveats

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_handlers.py tests/test_comms_integration.py tests/test_telegram_control_surface.py -q`
Expected: PASS

**Step 5: Commit**

```bash
git add .env.example README.md docs/plans/2026-03-11-multi-provider-agent-runtime.md
git commit -m "docs: describe multi-provider agent switching"
```
