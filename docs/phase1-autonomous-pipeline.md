# Phase 1: Autonomous Pipeline — Implementation Plan

_Minimum end-to-end loop: **Suggestion → Backtest → Human Approval (Telegram) → PR Created**_

## Goal

Close the gap between "suggestion delivered" and "parameter changed on bot" with two human gates:

```
Suggestion Generated → Backtested → Human Approves (Telegram) → PR Created → Human Merges (GitHub)
```

## Architecture

```
StrategyEngine / Claude Analysis
         |
    suggestions recorded (existing)
         |
    AutonomousPipeline.process_new_suggestions()
         |
    ┌────┴────┐
    │ Is it   │ No → skip (hypothesis, strategy_variant,
    │ action- │       low confidence, no matching param)
    │ able?   │
    └────┬────┘
         | Yes
    ConfigRegistry.resolve_suggestion_to_params()
         |
    SuggestionBacktester.backtest_suggestion()
         |
    ┌────┴────┐
    │ Passes  │ No → skip, log reason
    │ safety? │
    └────┬────┘
         | Yes
    ApprovalTracker.create_request()
         |
    TelegramRenderer.render_approval_request()
    + send with inline keyboard [Approve] [Reject] [Details]
         |
    ── Human taps Approve ──
         |
    ApprovalHandler.handle_approve()
         |
    FileChangeGenerator.generate_changes()
         |
    PRBuilder.create_pr()
         |
    ── Human merges PR on GitHub ──
```

## Feature Flag

All new behavior gated behind `AUTONOMOUS_ENABLED=false` (default). System behaves identically to current until explicitly enabled.

---

## Phase 1A: Foundation — Schemas, Config Registry, Backtester

### Task 0: Autonomous Pipeline Schemas (~8 tests)

**File:** `schemas/autonomous_pipeline.py`
**Test:** `tests/test_autonomous_schemas.py`

Models:

- `ParameterType` enum: `YAML_FIELD | PYTHON_CONSTANT | DATACLASS_FIELD`
- `ParameterDefinition`:
  - `param_name: str` — canonical name (e.g. `quality_min_threshold`)
  - `bot_id: str`
  - `strategy_id: str | None`
  - `param_type: ParameterType`
  - `file_path: str` — relative path in bot repo (e.g. `strategy_kmp/config/switches.py`)
  - `yaml_key: str | None` — dotted path for YAML (e.g. `kmp.quality_min_threshold`)
  - `python_path: str | None` — for module constants (e.g. `config.constants.BASE_RISK_PCT`)
  - `current_value: Any`
  - `valid_range: tuple[float, float] | None`
  - `valid_values: list[Any] | None`
  - `value_type: Literal["int", "float", "bool", "str"]`
  - `category: str` — maps to suggestion categories (risk_management, entry_signal, exit_timing, etc.)
  - `is_safety_critical: bool` — extra scrutiny on backtest safety checks
- `BotConfigProfile`:
  - `bot_id: str`
  - `repo_url: str`
  - `repo_dir: str` — local clone path
  - `parameters: list[ParameterDefinition]`
  - `strategies: list[str]`
- `BacktestContext`:
  - `suggestion_id: str`
  - `bot_id: str`
  - `param_name: str`
  - `current_value: Any`
  - `proposed_value: Any`
  - `trade_count: int`
  - `data_days: int`
- `BacktestComparison`:
  - `context: BacktestContext`
  - `baseline: SimulationMetrics` (reuse from `schemas/wfo_results.py`)
  - `proposed: SimulationMetrics`
  - `sharpe_change_pct: float`
  - `max_dd_change_pct: float`
  - `profit_factor_change_pct: float`
  - `win_rate_change_pct: float`
  - `passes_safety: bool`
  - `safety_notes: list[str]`
- `ApprovalStatus` enum: `PENDING | APPROVED | REJECTED | EXPIRED`
- `ApprovalRequest`:
  - `request_id: str`
  - `suggestion_id: str`
  - `bot_id: str`
  - `param_changes: list[dict]` — `[{param_name, current, proposed}]`
  - `backtest_summary: BacktestComparison`
  - `status: ApprovalStatus`
  - `created_at: datetime`
  - `resolved_at: datetime | None`
  - `resolved_by: str | None`
  - `rejection_reason: str | None`
  - `pr_url: str | None`
- `FileChange`:
  - `file_path: str`
  - `original_content: str`
  - `new_content: str`
  - `diff_preview: str`
- `PRRequest`:
  - `approval_request_id: str`
  - `suggestion_id: str`
  - `bot_id: str`
  - `repo_dir: str`
  - `branch_name: str`
  - `title: str`
  - `body: str`
  - `file_changes: list[FileChange]`
- `PRResult`:
  - `success: bool`
  - `pr_url: str | None`
  - `branch_name: str`
  - `error: str | None`

Tests:
- Validation: ParameterDefinition requires yaml_key when param_type is YAML_FIELD
- Validation: ParameterDefinition requires python_path when param_type is PYTHON_CONSTANT
- Validation: valid_range[0] < valid_range[1]
- BacktestComparison auto-computes change percentages
- BacktestComparison passes_safety logic
- ApprovalRequest lifecycle transitions
- Serialization round-trip for all models
- BotConfigProfile parameter lookup

---

### Task 1: Config Registry (~10 tests)

**File:** `skills/config_registry.py`
**Config:** `data/bot_configs/{k_stock_trader,swing_trader,momentum_trader}.yaml`
**Test:** `tests/test_config_registry.py`

```python
class ConfigRegistry:
    def __init__(self, config_dir: Path):
        self._profiles: dict[str, BotConfigProfile] = {}
        self._load_profiles(config_dir)

    def get_profile(self, bot_id: str) -> BotConfigProfile | None
    def get_parameter(self, bot_id: str, param_name: str) -> ParameterDefinition | None
    def find_parameters_by_category(self, bot_id: str, category: str) -> list[ParameterDefinition]
    def resolve_suggestion_to_params(self, suggestion: SuggestionRecord) -> list[ParameterDefinition]
    def validate_value(self, param: ParameterDefinition, value: Any) -> tuple[bool, str | None]
    def list_bot_ids(self) -> list[str]
```

Config YAML structure:
```yaml
bot_id: k_stock_trader
repo_url: git@github.com:user/k_stock_trader.git
repo_dir: /path/to/local/clone
strategies:
  - kmp
parameters:
  - param_name: quality_min_threshold
    strategy_id: kmp
    param_type: YAML_FIELD
    file_path: strategy_kmp/config/switches.yaml
    yaml_key: kmp.quality_min_threshold
    current_value: 0.6
    valid_range: [0.0, 1.0]
    value_type: float
    category: entry_signal
    is_safety_critical: false
  - param_name: base_risk_pct
    strategy_id: null
    param_type: PYTHON_CONSTANT
    file_path: config/risk.py
    python_path: BASE_RISK_PCT
    current_value: 0.02
    valid_range: [0.005, 0.05]
    value_type: float
    category: risk_management
    is_safety_critical: true
```

Initial configs map known tunable params per bot:
- **k_stock_trader:** 8 KMP switches (`quality_min_threshold`, `or_range_max`, `rsi_min`, `rsi_max`, `volume_ratio_min`, `atr_filter_mult`, `max_spread_pct`, `max_positions`) + OMS risk params (`base_risk_pct`, `daily_stop_r`, `heat_cap_r`)
- **swing_trader:** SymbolConfig defaults per strategy (`daily_mult`, `hourly_mult`, `base_risk_pct`, `adx_on`, `adx_threshold`, `atr_period`, `risk_reward_min`)
- **momentum_trader:** Module constants per strategy (`BASE_RISK_PCT`, `MACD_FAST`, `MACD_SLOW`, `MACD_SIGNAL`, `TRAIL_ACTIVATION_R`, `TRAIL_STEP_R`, `RSI_OVERSOLD`, `RSI_OVERBOUGHT`)

Safety-critical flags on: `base_risk_pct`, `daily_stop_r`, `heat_cap_r`, `max_positions`, all position sizing params.

`resolve_suggestion_to_params()` matching logic:
1. Match `suggestion.bot_id` to profile
2. Match `suggestion.category` to parameter categories
3. Keyword match suggestion title/description against param names
4. Return matched params (may be empty — not all suggestions are actionable)

Tests:
- Load profiles from YAML directory
- get_parameter returns correct definition
- find_parameters_by_category filters correctly
- resolve_suggestion_to_params: category + keyword match
- resolve_suggestion_to_params: no match returns empty list
- validate_value: in-range passes
- validate_value: out-of-range fails with message
- validate_value: valid_values enum check
- Safety-critical flag set on risk params
- Unknown bot_id returns None

---

### Task 2: Suggestion Backtester (~12 tests)

**File:** `skills/suggestion_backtester.py`
**Test:** `tests/test_suggestion_backtester.py`
**Depends on:** Task 0, Task 1, existing `BacktestSimulator`/`CostModel`

```python
class SuggestionBacktester:
    def __init__(self, config_registry: ConfigRegistry, data_dir: Path):
        self._registry = config_registry
        self._data_dir = data_dir

    async def backtest_suggestion(
        self,
        suggestion_id: str,
        bot_id: str,
        param_name: str,
        current_value: Any,
        proposed_value: Any,
    ) -> BacktestComparison:
        """Run baseline vs proposed backtest and return comparison."""

    def _load_trades(self, bot_id: str, lookback_days: int = 30) -> list[dict]:
        """Load trades from data/curated/ (same pattern as handle_wfo)."""

    def _check_safety(
        self,
        baseline: SimulationMetrics,
        proposed: SimulationMetrics,
        is_safety_critical: bool,
    ) -> tuple[bool, list[str]]:
        """Apply safety checks to backtest results."""
```

Safety checks:
- Proposed Sharpe ratio >= 0
- Max drawdown not >50% worse than baseline (30% for safety-critical)
- Profit factor >= 1.0
- Trade count >= 10 (minimum statistical relevance)
- Safety-critical params get tighter thresholds on all checks

Tests:
- Baseline vs proposed comparison with improvement
- Baseline vs proposed comparison with regression
- Safety check: Sharpe < 0 fails
- Safety check: DD >50% worse fails
- Safety check: profit factor < 1.0 fails
- Safety check: trade count < 10 fails
- Safety-critical param: tighter DD threshold (30%)
- Load trades from curated directory
- Empty trade data returns comparison with passes_safety=False
- Percentage calculations correct (division by zero handling)
- Integration with real BacktestSimulator (mocked trades)
- Multiple param changes in single backtest

---

### Task 3: Approval Tracker (~10 tests)

**File:** `skills/approval_tracker.py`
**Test:** `tests/test_approval_tracker.py`
**Depends on:** Task 0

```python
class ApprovalTracker:
    """JSONL-backed approval request lifecycle tracker."""

    def __init__(self, storage_path: Path):
        self._path = storage_path  # memory/findings/approvals.jsonl

    def create_request(self, request: ApprovalRequest) -> ApprovalRequest
    def approve(self, request_id: str, resolved_by: str = "telegram") -> ApprovalRequest
    def reject(self, request_id: str, reason: str, resolved_by: str = "telegram") -> ApprovalRequest
    def expire_old(self, max_age_days: int = 7) -> list[str]  # returns expired IDs
    def get_pending(self) -> list[ApprovalRequest]
    def get_by_id(self, request_id: str) -> ApprovalRequest | None
    def set_pr_url(self, request_id: str, pr_url: str) -> None
    def _load_all(self) -> list[ApprovalRequest]
    def _save_all(self, requests: list[ApprovalRequest]) -> None
```

Same JSONL persistence pattern as `SuggestionTracker`:
- Append-on-create, full-rewrite-on-update
- Deduplication by request_id

Tests:
- Create and retrieve request
- Approve transitions status from PENDING to APPROVED
- Reject transitions status from PENDING to REJECTED with reason
- Approve non-PENDING raises ValueError
- Expire old requests (>7 days)
- get_pending returns only PENDING requests
- set_pr_url updates record
- Deduplication by request_id
- JSONL round-trip persistence
- get_by_id returns None for unknown ID

---

## Phase 1B: PR Automation

### Task 4: File Change Generator (~12 tests)

**File:** `skills/file_change_generator.py`
**Test:** `tests/test_file_change_generator.py`
**Depends on:** Task 0, Task 1

```python
class FileChangeGenerator:
    """Generates file modifications for parameter changes across three config formats."""

    def generate_change(
        self,
        param: ParameterDefinition,
        new_value: Any,
        repo_dir: Path,
    ) -> FileChange:
        """Read file, apply change, return FileChange with diff."""

    def _modify_yaml(self, content: str, yaml_key: str, new_value: Any) -> str
    def _modify_python_constant(self, content: str, var_name: str, new_value: Any) -> str
    def _modify_dataclass_field(self, content: str, class_name: str, field_name: str, new_value: Any) -> str
```

Format handlers:
- **YAML fields:** Parse YAML, navigate dotted key path (e.g. `kmp.quality_min_threshold`), replace value, dump back. Use `ruamel.yaml` to preserve comments and formatting.
- **Python constants:** Regex `^(\s*)(VAR_NAME)\s*[:=]\s*.*$` → replace value portion. Handle `float`, `int`, `bool`, `str` formatting.
- **Dataclass fields:** Regex for `(field_name)\s*:\s*\w+\s*=\s*(.*)` within class body, replace default value.

All handlers:
- Preserve comments, blank lines, surrounding code
- Produce `difflib.unified_diff` preview

Tests:
- YAML: simple key change
- YAML: nested dotted path change
- YAML: preserves comments
- Python constant: float value change
- Python constant: int value change
- Python constant: bool value change
- Python constant: type annotation (`: float = 0.02`)
- Dataclass field: replace default value
- File not found raises FileNotFoundError
- Diff preview contains old and new values
- Value formatting: float precision preserved
- Round-trip: original content unchanged when same value applied

---

### Task 5: PR Builder (~10 tests)

**File:** `skills/github_pr.py`
**Test:** `tests/test_github_pr.py`
**Depends on:** Task 0, Task 4

```python
class PRBuilder:
    """Creates PRs against bot repositories using git CLI."""

    def __init__(self, dry_run: bool = False):
        self._dry_run = dry_run

    async def create_pr(self, request: PRRequest) -> PRResult:
        """
        1. Ensure repo up-to-date (git pull)
        2. Create branch ta/suggestion-{id[:8]}-{date} from main
        3. Apply FileChanges to working directory
        4. Commit: "trading-assistant: {title} (#{suggestion_id})"
        5. Push branch
        6. gh pr create with formatted body
        """

    async def _run_git(self, args: list[str], cwd: Path) -> tuple[int, str, str]:
        """Run git command via asyncio.create_subprocess_exec."""

    def _format_pr_body(self, request: PRRequest, comparison: BacktestComparison) -> str:
        """Format PR body with param table, backtest results, rollback instructions."""
```

PR body includes:
- Parameter change table (param: current → proposed)
- Backtest comparison (Sharpe/MaxDD/ProfitFactor/WinRate with % change)
- Safety check results
- Rollback instructions: `git revert <commit-sha>`
- Link to suggestion ID in orchestrator

Rules:
- PR title prefixed with `[trading-assistant]`
- Never force pushes
- Never auto-merges
- Branch naming: `ta/suggestion-{id[:8]}-{YYYY-MM-DD}`
- Single-concern commits (one param change per commit)

Tests:
- Successful PR creation (mocked git/gh commands)
- Branch name format correct
- Commit message format correct
- PR body contains backtest comparison
- PR body contains rollback instructions
- git pull failure → PRResult with error
- gh pr create failure → PRResult with error
- Dry run mode skips git commands, returns preview
- Multiple file changes in single PR
- PR title format with prefix

---

## Phase 1C: Approval UX

### Task 6: Approval Telegram Renderer (~8 tests)

**File:** Extend `comms/telegram_renderer.py`
**Test:** `tests/test_approval_renderer.py`
**Depends on:** Task 0

Add method to existing `TelegramRenderer`:

```python
def render_approval_request(self, request: ApprovalRequest) -> tuple[str, list[list[dict]]]:
    """
    Returns (message_text, inline_keyboard) for Telegram approval card.

    Format:
    🔔 Suggestion Approval Request
    Bot: {bot_id} | Category: {category}
    {title}

    Parameter Changes:
    • param_name: 0.6 → 0.7

    Backtest Results (30d):
    | Metric | Baseline | Proposed | Change |
    | Sharpe | 1.2 | 1.4 | +16.7% |
    | MaxDD | -8.2% | -7.1% | +13.4% |
    ...

    Confidence: 0.72 | Safety: ✅ PASS

    Keyboard:
    [✅ Approve] [❌ Reject]
    [📊 Details]
    """
```

Callback data format:
- `approve_suggestion_{request_id}`
- `reject_suggestion_{request_id}`
- `detail_suggestion_{request_id}`

Respects 4096 char Telegram limit — auto-truncates backtest details if needed.

Tests:
- Renders approval card with all sections
- Inline keyboard has correct callback data
- Backtest table formatted correctly
- Safety pass/fail indicators
- Truncation at 4096 chars
- Handles missing optional fields gracefully
- Callback data format matches handler expectations
- MarkdownV2 escaping applied

---

### Task 7: Approval Callback Handlers (~12 tests)

**File:** `skills/approval_handler.py`
**Extend:** `comms/telegram_handlers.py` (callback routes)
**Test:** `tests/test_approval_handler.py`
**Depends on:** Task 3, Task 4, Task 5, Task 6

```python
class ApprovalHandler:
    def __init__(
        self,
        approval_tracker: ApprovalTracker,
        suggestion_tracker: SuggestionTracker,
        file_change_generator: FileChangeGenerator,
        pr_builder: PRBuilder,
        config_registry: ConfigRegistry,
        event_stream: EventStream | None = None,
    ): ...

    async def handle_approve(self, request_id: str) -> str:
        """
        1. Validate request is PENDING
        2. Mark APPROVED in ApprovalTracker
        3. Mark linked suggestion as IMPLEMENTED in SuggestionTracker
        4. Generate FileChanges via FileChangeGenerator
        5. Build PRRequest, create PR via PRBuilder
        6. Record PR URL on approval
        7. Broadcast suggestion_pr_created event
        8. Return confirmation: "PR created: {url}"

        If PR creation fails, revert approval to PENDING (rollback).
        """

    async def handle_reject(self, request_id: str, reason: str = "") -> str:
        """Mark REJECTED, update SuggestionTracker, return confirmation."""

    async def handle_detail(self, request_id: str) -> str:
        """Return extended backtest details for the request."""
```

Telegram callback integration:
- Register callbacks for `approve_suggestion_*`, `reject_suggestion_*`, `detail_suggestion_*`
- On reject without reason: prompt for reason (or use "rejected via Telegram")

Tests:
- Approve: PENDING → APPROVED → PR created
- Approve: PR failure → rollback to PENDING
- Approve: non-PENDING request → error message
- Reject: PENDING → REJECTED with reason
- Reject: marks suggestion as rejected in SuggestionTracker
- Detail: returns backtest comparison text
- Detail: unknown request_id → error message
- Event broadcast on PR creation
- Telegram callback routing for approve
- Telegram callback routing for reject
- Telegram callback routing for detail
- SuggestionTracker updated on approve

---

## Phase 1D: Integration

### Task 8: Pipeline Orchestrator (~14 tests)

**File:** `skills/autonomous_pipeline.py`
**Test:** `tests/test_autonomous_pipeline.py`
**Depends on:** Task 1, Task 2, Task 3, Task 6

```python
class AutonomousPipeline:
    def __init__(
        self,
        config_registry: ConfigRegistry,
        backtester: SuggestionBacktester,
        approval_tracker: ApprovalTracker,
        suggestion_tracker: SuggestionTracker,
        telegram_bot: TelegramBotAdapter | None = None,
        telegram_renderer: TelegramRenderer | None = None,
        event_stream: EventStream | None = None,
    ): ...

    async def process_new_suggestions(
        self,
        suggestion_ids: list[str],
        run_id: str | None = None,
    ) -> list[ApprovalRequest]:
        """
        For each suggestion:
        1. Load SuggestionRecord from tracker
        2. Filter: only tier == parameter|filter, confidence >= 0.5,
           not already in approval queue
        3. Resolve to ParameterDefinitions via ConfigRegistry
        4. Extract proposed value from suggestion text
        5. Run backtest via SuggestionBacktester
        6. Skip if backtest fails safety
        7. Create ApprovalRequest with backtest results
        8. Send Telegram notification with approval buttons
        """

    def _extract_proposed_value(
        self,
        suggestion: SuggestionRecord,
        param: ParameterDefinition,
    ) -> Any | None:
        """
        Extract proposed value from suggestion text.
        Regex patterns:
        - "increase X to Y" / "decrease X to Y"
        - "set X to Y"
        - "change X from A to B"
        Fallback: valid_range midpoint
        """

    def _is_actionable(self, suggestion: SuggestionRecord) -> bool:
        """Check tier, confidence, and not-already-queued."""
```

Tests:
- Process actionable suggestion end-to-end
- Skip non-actionable suggestion (wrong tier)
- Skip low-confidence suggestion (< 0.5)
- Skip suggestion already in approval queue
- Skip suggestion with no matching parameters
- Extract value: "increase X to 0.7"
- Extract value: "set X to 0.7"
- Extract value: "change X from 0.5 to 0.7"
- Extract value: fallback to range midpoint
- Backtest failure → no approval request created
- Multiple suggestions processed (some pass, some fail)
- Telegram notification sent on approval request creation
- Event broadcast on pipeline completion
- Pipeline errors logged, not raised (doesn't break analysis)

---

### Task 9: Handler + App Wiring (~10 tests)

**Files modified:**
- `orchestrator/handlers.py`
- `orchestrator/app.py`
- `orchestrator/config.py`
**Test:** `tests/test_autonomous_wiring.py`
**Depends on:** Tasks 0–8

#### Config changes (`orchestrator/config.py`):

Add fields to `AppConfig`:
```python
bot_repo_dir: Path = Path(".")        # parent dir containing bot repo clones
bot_config_dir: Path = Path("data/bot_configs")  # config registry YAMLs
autonomous_enabled: bool = False      # feature flag
```

Read from env: `BOT_REPO_DIR`, `BOT_CONFIG_DIR`, `AUTONOMOUS_ENABLED`

#### Handler changes (`orchestrator/handlers.py`):

After `_record_suggestions()` and `_record_agent_suggestions()`:
```python
if self._autonomous_pipeline:
    try:
        await self._autonomous_pipeline.process_new_suggestions(
            suggestion_ids=[s.suggestion_id for s in recorded],
            run_id=run_id,
        )
    except Exception:
        logger.exception("Autonomous pipeline failed — analysis unaffected")
```

Add `autonomous_pipeline: AutonomousPipeline | None = None` constructor param.

#### App wiring (`orchestrator/app.py`):

When `config.autonomous_enabled`:
1. Create `ConfigRegistry(config.bot_config_dir)`
2. Create `SuggestionBacktester(config_registry, config.data_dir)`
3. Create `ApprovalTracker(findings_dir / "approvals.jsonl")`
4. Create `FileChangeGenerator()`
5. Create `PRBuilder(dry_run=not config.autonomous_enabled)`
6. Create `ApprovalHandler(approval_tracker, suggestion_tracker, file_change_generator, pr_builder, config_registry)`
7. Create `AutonomousPipeline(config_registry, backtester, approval_tracker, suggestion_tracker, telegram_bot, telegram_renderer)`
8. Pass `autonomous_pipeline` to Handlers
9. Register Telegram approval callbacks

Register `/pending` Telegram command → returns `approval_tracker.get_pending()` summary.

Tests:
- Feature flag off: no autonomous components created
- Feature flag on: all components wired
- Handler calls pipeline after recording suggestions
- Pipeline failure doesn't break analysis handler
- Pipeline failure logged
- Telegram callbacks registered when autonomous enabled
- /pending command returns pending approvals
- Config reads from env vars
- App wiring with missing Telegram (pipeline still works minus notifications)
- Handlers constructor accepts optional autonomous_pipeline

---

### Task 10: Scheduler Integration (~4 tests)

**File modified:** `orchestrator/scheduler.py`
**Test:** `tests/test_autonomous_scheduler.py`
**Depends on:** Task 3

Add to scheduler when `autonomous_enabled`:
```python
# Daily at midnight UTC: expire old approval requests
scheduler.add_job(
    approval_tracker.expire_old,
    CronTrigger(hour=0, minute=0),
    kwargs={"max_age_days": 7},
    id="approval_expiry",
)
```

Tests:
- Expiry job registered when autonomous enabled
- Expiry job not registered when autonomous disabled
- Expired requests transition to EXPIRED status
- Expiry runs without error on empty tracker

---

### Task 11: Integration Test (~8 tests)

**File:** `tests/test_autonomous_integration.py`
**Depends on:** All Tasks 0–10

End-to-end test scenarios (git/gh commands mocked):

1. **Happy path:** StrategyEngine generates parameter suggestion → SuggestionTracker records → AutonomousPipeline backtests (passes) → ApprovalRequest created → Approve via handler → PR created → confirmation returned
2. **Backtest failure:** Suggestion backtests poorly → no ApprovalRequest created → no Telegram notification
3. **Non-actionable suggestion:** Hypothesis suggestion → skipped by pipeline → no processing
4. **Safety-critical param:** risk_management suggestion → tighter backtest thresholds applied
5. **Rejection flow:** ApprovalRequest created → User rejects → SuggestionTracker updated → no PR
6. **Expiry flow:** ApprovalRequest created → 7 days pass → expire_old() → status EXPIRED
7. **Telegram notification:** Verify rendered message contains backtest table and inline keyboard
8. **Pipeline isolation:** Pipeline throws exception → daily analysis handler completes normally

---

## Summary

| | Files | Tests |
|---|---|---|
| **New source files** | `schemas/autonomous_pipeline.py`, `skills/config_registry.py`, `skills/suggestion_backtester.py`, `skills/approval_tracker.py`, `skills/file_change_generator.py`, `skills/github_pr.py`, `skills/autonomous_pipeline.py`, `skills/approval_handler.py` | |
| **New test files** | `tests/test_autonomous_schemas.py`, `tests/test_config_registry.py`, `tests/test_suggestion_backtester.py`, `tests/test_approval_tracker.py`, `tests/test_file_change_generator.py`, `tests/test_github_pr.py`, `tests/test_autonomous_pipeline.py`, `tests/test_approval_renderer.py`, `tests/test_approval_handler.py`, `tests/test_autonomous_wiring.py`, `tests/test_autonomous_scheduler.py`, `tests/test_autonomous_integration.py` | |
| **New config files** | `data/bot_configs/k_stock_trader.yaml`, `data/bot_configs/swing_trader.yaml`, `data/bot_configs/momentum_trader.yaml` | |
| **Modified files** | `orchestrator/handlers.py`, `orchestrator/app.py`, `orchestrator/config.py`, `comms/telegram_renderer.py`, `comms/telegram_handlers.py`, `orchestrator/scheduler.py` | |
| **Total estimated tests** | | **~118** |

## Dependency Graph

```
Task 0 (Schemas) ──────────────────────────────────────
    ├── Task 1 (Config Registry)
    │       ├── Task 2 (Suggestion Backtester)
    │       └── Task 4 (File Change Generator)
    │               └── Task 5 (PR Builder)
    ├── Task 3 (Approval Tracker)  ─── Task 10 (Scheduler)
    └── Task 6 (Approval Renderer)

Tasks 3+4+5+6 ──→ Task 7 (Approval Handlers)
Tasks 1+2+3+6 ──→ Task 8 (Pipeline Orchestrator)
Tasks 0-8     ──→ Task 9 (Handler Wiring)
All           ──→ Task 11 (Integration Test)
```

## Key Design Decisions

1. **Feature-flagged** (`AUTONOMOUS_ENABLED=false` by default) — system behaves identically to current until explicitly enabled
2. **Two human gates** — Telegram approval + GitHub PR merge. Never auto-merges.
3. **Only parameter/filter suggestions are actionable** — hypothesis and strategy_variant require human design work
4. **Conservative backtesting safety** — Sharpe >= 0, DD not >50% worse, profit factor >= 1.0
5. **Config Registry is YAML-driven** — adding a new bot or parameter is a YAML-only change
6. **Git CLI for PRs** — `gh pr create` rather than GitHub API, uses existing git auth
7. **Rollback-first** — every PR body includes rollback instructions, single-concern commits
8. **Pipeline isolation** — autonomous pipeline failures never break the analysis pipeline (try/except with logging)

## Verification

1. `pytest tests/` — all 1576 existing + ~118 new tests pass
2. Manual: `AUTONOMOUS_ENABLED=false` → daily/weekly handler behavior unchanged
3. Manual: `AUTONOMOUS_ENABLED=true` with mock bot repos → full pipeline produces PR
4. Telegram rendering: approval card with backtest table and buttons renders correctly
5. Safety: safety-critical param changes flagged, backtest failures block approval creation
