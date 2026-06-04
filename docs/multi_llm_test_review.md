# Multi-LLM Test Suite Review

Date: 2026-03-14

## Summary

10 test files reviewed, 175 total tests across the multi-LLM configuration subsystem.

---

## File-by-File Analysis

### 1. `tests/test_agent_preferences_manager.py` — 26 tests

**Classes:** TestResolveSelection (9), TestBuildView (5), TestUnavailableReasons (5), TestGetSetPreferences (4), TestModelNormalization (3)

**Key scenarios covered:**
- Default provider resolution with/without workflow
- Override provider for specific workflow
- Model override precedence (explicit > selection > default)
- Build view with effective selections per workflow
- Provider status resolver wiring
- Deep-copy isolation on get/set
- Blank/None/whitespace model normalization

**Missing scenarios:**
- No test for concurrent set/get (thread safety)
- No test for invalid provider enum values
- No test for `resolve_selection` with all 4 providers — only CLAUDE_MAX and CODEX_PRO exercised
- No test for preferences with ALL workflows overridden simultaneously
- `unavailable_reasons()` not tested with mixed available/unavailable across multiple overrides
- No test for `resolve_tuning()` (covered in test_workflow_tuning instead — OK)

**Fragility:** Low. Tests use the manager's public API cleanly.

**Assertions:** Appropriate granularity; check both positive and negative cases.

---

### 2. `tests/test_provider_health.py` — 18 tests

**Classes:** TestClaudeMaxAuth (8), TestCodexAuth (6), TestProviderStatusCaching (2), TestZaiOpenRouterKeyChecks (2)

**Key scenarios covered:**
- Claude Max: valid subscription, not logged in, wrong auth method, pro subscription, command not found, timeout, invalid JSON, nonzero exit
- Codex: valid ChatGPT auth, missing auth file, wrong auth mode, OpenAI API key present, no tokens, malformed JSON
- Status caching: cached within TTL, expires after TTL
- Z.ai/OpenRouter: key-based readiness (no subprocess needed)

**KNOWN BUG:** `test_available_with_valid_max_subscription` FAILS with `AttributeError: module 'orchestrator.agent_runner' has no attribute 'subprocess'`. The patch target is `orchestrator.agent_runner.subprocess.run` but `subprocess` was moved to `orchestrator.provider_auth`. The test patches the wrong module path. This likely affects ALL 8 TestClaudeMaxAuth tests and possibly the caching tests.

**Missing scenarios:**
- No test for `invalidate_provider_status_cache()` with a specific provider (only TTL expiry tested)
- No test for Codex runtime diagnostics content (log file parsing)
- No test for Codex `_find_latest_codex_log()` or `_read_text_tail()`
- No test for Claude auth with partial/missing JSON fields (e.g., `loggedIn` present but `subscriptionType` missing)
- No test for Z.ai with empty string API key vs None
- No test for OpenRouter with empty string API key vs None
- No test for concurrent provider status checks

**Fragility:** HIGH — patch targets reference `orchestrator.agent_runner.subprocess` which is WRONG. These tests are broken and would fail if actually run. This is the most critical issue found.

---

### 3. `tests/test_invocation_building.py` — 16 tests

**Classes:** TestClaudeCLIArgs (6), TestCodexCLIArgs (3), TestEnvIsolation (5), TestResolveClaudeModel (2)

**Key scenarios covered:**
- Claude CLI: correct command + args, model flag, --print-output, instructions flag, launcher args, system prompt via --instructions
- Codex CLI: correct command + args, model forwarded, system prompt handling
- Env isolation: Anthropic keys cleared for Claude, OpenAI keys cleared for Codex, overrides applied after clear, existing env preserved
- Model resolution: Claude Max passes model directly, default model when None

**Missing scenarios:**
- No test for `--instructions` flag when system_prompt is empty or whitespace-only
- No test for max_turns argument forwarding to Claude CLI
- No test for allowed_tools argument forwarding
- No test for Codex sandbox mode (`_CODEX_SANDBOX`) in args
- No test for very long system prompts (could hit OS arg limits)
- No test for special characters in system_prompt (quotes, newlines)
- No test for `_merge_codex_prompt()` output format
- No test that verifies the run_dir is passed correctly to CLI

**Fragility:** Medium — tests import private constants (`_ANTHROPIC_ENV_KEYS_TO_CLEAR`, `_CODEX_RUNTIME`, etc.). Renaming these constants would break tests without breaking functionality.

**Implementation detail testing:** `test_anthropic_keys_cleared_for_claude` checks specific env var names — this tests the implementation list rather than the behavior of "no stale auth leaks."

---

### 4. `tests/test_agent_invocation.py` — 9 tests

**Classes:** TestInvokeWithSelection (9)

**Key scenarios covered:**
- `invoke()` resolves workflow to selection
- Unknown agent type uses default selection
- Unavailable provider returns failure result
- Unavailable provider broadcasts failure event
- Successful Claude invocation end-to-end
- Run directory creation and file writing
- Model override flows through to subprocess
- Started event includes provider details

**Missing scenarios:**
- No test for Codex invocation path (only Claude tested)
- No test for `invoke_with_selection()` with ZAI or OpenRouter providers
- No test for subprocess failure (nonzero exit, crash, timeout)
- No test for large prompt packages
- No test for empty data in PromptPackage
- No test for run_id collision (same run_id used twice)
- No test for cancellation during invocation
- No test that the result.response content is correct (only checks success=True)
- No test for cost_usd extraction from successful run

**Fragility:** Medium — tests directly set `runner._provider_status_cache` (private attribute). If the caching mechanism changes, all tests break.

---

### 5. `tests/test_stream_parsing.py` — 18 tests

**Classes:** TestClaudeStreamParsing (9), TestOutputParsing (6), TestCodexStreamParsing (3)

**Key scenarios covered:**
- Claude streaming: result event capture, session/thread ID, cost extraction, usage block cost, tool use counting, text content accumulation, invalid JSON handling, non-dict JSON ignored
- Codex streaming: message item text, tool item counting
- Output parsing: JSON output extraction, fallback on invalid JSON, JSONL message extraction, JSONL thread ID, routing to JSON vs JSONL format, JSONL tool call counting

**Missing scenarios:**
- No test for Claude stream with interleaved result + text events
- No test for very large stream output (memory pressure)
- No test for malformed/truncated stream lines (partial JSON)
- No test for empty stream output
- No test for Codex stream with usage/cost block
- No test for stream with multiple result blocks (which one wins?)
- No test for Unicode/binary content in stream
- No test for `_record_assistant_text()` deduplication or ordering
- Codex stream parsing has only 3 tests vs Claude's 9 — significantly underrepresented

**Fragility:** Low-Medium — tests use `_parse_claude_stream_line` and `_ClaudeStreamState` (private), but these are stable internal APIs.

**Imbalance:** Codex stream parsing is undertested (3 tests) compared to Claude (9 tests). Given that Codex is a distinct runtime with different output formats, this is a coverage gap.

---

### 6. `tests/test_workflow_tuning.py` — 18 tests

**Classes:** TestWorkflowTuningSchema (4), TestDefaultTuning (7), TestResolveTuning (4), TestInvokeWithTuning (3)

**Key scenarios covered:**
- Schema: all fields optional, fields set, preferences with tuning, serialization round-trip
- Defaults: daily, weekly, WFO, triage, heartbeat, notification, alert defaults
- Resolve: per-workflow override, partial override merges with defaults, global override
- Invoke integration: tuned timeout passed to invocation, caller max_turns overrides tuning, timeout applied during invocation

**Missing scenarios:**
- No test for `allowed_tools` being forwarded to the invocation
- No test for zero/negative timeout_seconds
- No test for zero/negative max_turns
- No test for empty allowed_tools list vs None
- No test for unknown workflow falling back to a sensible default
- No test for tuning serialization with all AgentWorkflow keys populated

**Fragility:** Low. Tests use public API and schema validation.

**Assertions:** Good — checks both override and fallback-to-default behavior.

---

### 7. `tests/test_cost_tracking.py` — 16 tests

**Classes:** TestCostRecordSchema (3), TestCostSummarySchema (2), TestCostTracker (6), TestAgentRunnerIntegration (3), TestCostTrackerOptional (2)

**Key scenarios covered:**
- Schema: defaults, full record, serialization round-trip, summary defaults, populated summary
- Tracker: record creates file, record and load, empty summary, aggregation (multiple records), days filter, by_provider grouping
- Integration: cost recorded after invocation, no crash without tracker, failure cost captured
- Optional: by_workflow grouping, malformed line skipped

**Missing scenarios:**
- No test for `by_workflow()` with multiple workflows
- No test for concurrent writes to cost_log.jsonl (file locking)
- No test for very large JSONL files (performance)
- No test for cost_usd = 0.0 (free invocations)
- No test for negative cost values
- No test for timezone edge cases in days filter
- No test for JSONL file corruption recovery (partial writes)
- No test for disk-full scenarios

**Fragility:** Low. Clean use of tmp_path fixtures and public API.

**Assertions:** `test_summary_aggregation` uses `pytest.approx` for float comparison — good practice.

---

### 8. `tests/test_hardening.py` — 8 tests

**Classes:** TestCodexInstructionsFlag (3), TestDefaultProviderModels (3), TestCostTrackerOptional (2)

**Key scenarios covered:**
- Codex: system_prompt passed via --instructions flag, no flag when empty, no flag when whitespace
- Provider models: invocation_builder imports canonical DEFAULT_PROVIDER_MODELS, Z.ai default model matches, OpenRouter default model matches
- Cost tracker: optional wiring (no crash without), by_workflow test

**Missing scenarios:**
- No test for Codex --instructions with special characters (newlines, quotes, backticks)
- No test that DEFAULT_PROVIDER_MODELS covers all AgentProvider enum values
- No test for provider model changes at runtime
- Only 8 tests for a "hardening" file — seems thin. Many hardening concerns (retry logic, graceful degradation, error recovery) are not tested here

**Fragility:** Low. Tests verify integration contracts rather than implementation details.

**Overlap:** `TestCostTrackerOptional` appears in both `test_cost_tracking.py` and `test_hardening.py` — redundant tests.

---

### 9. `tests/test_fallback_chains.py` — 19 tests

**Classes:** TestFallbackEntrySchema (2), TestResolveWithFallbacks (6), TestAgentRunnerFallbackIntegration (7 async + 4 sync)

**Key scenarios covered:**
- Schema: preferences with fallback chain, serialization
- Resolve: primary returned when available, skips cooled-down providers, deduplicates primary in chain, fills default model for entries, all unavailable returns empty, model override applies to primary only
- Integration: primary success (no fallback triggered), fallback on primary failure, all fallbacks exhausted, cooldown recorded on failure, fallback event broadcast, no fallback chain uses simple path, fallback run_id suffixed

**Missing scenarios:**
- No test for fallback chain with 3+ entries (only 1-2 tested)
- No test for fallback from Claude to Codex (cross-runtime fallback)
- No test for fallback with cooldown expiry during chain execution
- No test for fallback when primary succeeds but returns poor quality result
- No test for concurrent fallback chains (two workflows failing simultaneously)
- No test for fallback chain modification during execution
- No test for ProviderCooldownTracker in isolation (no dedicated test file)
- No test for cooldown TTL customization
- No test for `clear_cooldown()` if it exists

**Fragility:** Medium — tests inject into `_provider_status_cache` directly and mock `_invoke_with_selection_inner`.

**Good practice:** Tests verify both the resolution logic AND the integration with AgentRunner — two-layer testing.

---

### 10. `tests/test_agent_runner.py` — 25 tests (multi-LLM relevant)

**Key scenarios covered:**
- Model resolution: default provider model, workflow override before global default
- CLI building: correct Claude command, launcher args, system prompt handling
- Env isolation: Anthropic key clearing, Z.ai env overrides, OpenRouter env overrides
- Auth: Claude Max auth succeeds/requires max, Z.ai/OpenRouter readiness without max auth, Codex auth modes (ChatGPT, OpenAI API key rejection, token check, diagnostics)
- Streaming: Full Claude streaming run (artifacts + events), Claude fallback without result block, full Codex streaming run
- Error handling: unavailable provider returns failed result, buffered timeout kills process, cache TTL refresh

**Missing scenarios:**
- No test for streaming with network interruption/partial output
- No test for process that hangs indefinitely (beyond timeout)
- No test for stderr output handling during streaming
- No test for mixed success/failure events in a single stream
- No test for very large response handling (memory)
- No test for Codex streaming timeout

**Fragility:** Medium-High — Uses `_StreamingProcess` helper class to mock asyncio subprocess, and directly accesses `_provider_status_cache`, `_auth_checker`, and other private attributes.

---

## Cross-Cutting Findings

### 1. Test Coverage Gaps (Critical)

| Gap | Severity | Affected Files |
|-----|----------|---------------|
| **Broken patch targets** in test_provider_health.py | CRITICAL | Patches `orchestrator.agent_runner.subprocess` but subprocess is in `provider_auth` |
| **No ProviderCooldownTracker unit tests** | HIGH | No dedicated test file; only tested indirectly via fallback chains |
| **Codex stream parsing undertested** | HIGH | 3 tests vs 9 for Claude in test_stream_parsing.py |
| **No cross-runtime fallback test** | MEDIUM | No test for Claude -> Codex fallback path |
| **No concurrent/thread-safety tests** | MEDIUM | Multiple files |
| **No error recovery tests** | MEDIUM | What happens when JSONL is corrupted mid-write? |

### 2. Fragile Tests

| Pattern | Risk | Files |
|---------|------|-------|
| Direct `_provider_status_cache` injection | Breaks if caching redesigned | test_agent_invocation, test_agent_runner, test_fallback_chains |
| Patching private methods (`_invoke_with_selection_inner`) | Breaks on rename | test_fallback_chains |
| Importing private constants (`_ANTHROPIC_ENV_KEYS_TO_CLEAR`) | Breaks on rename | test_invocation_building |
| Wrong patch target (`orchestrator.agent_runner.subprocess`) | Already broken | test_provider_health |

### 3. Implementation Detail Testing

- `test_invocation_building.py`: Tests check specific env var names in the clear-list rather than verifying no stale credentials leak
- `test_stream_parsing.py`: Tests internal `_ClaudeStreamState` dataclass fields
- `test_agent_runner.py`: Tests check `_codex_auth_status()` and `_claude_max_auth_status()` which are private methods
- `test_fallback_chains.py`: Mocks `_invoke_with_selection_inner` — tightly coupled to internal dispatch

### 4. Missing Edge Case Tests

- **Empty/None values:** System prompt = None, empty data dict, blank model strings (partially covered)
- **Boundary values:** timeout_seconds = 0, max_turns = 0, negative values
- **Concurrent operations:** Parallel invocations, simultaneous preference updates
- **File system edge cases:** Disk full, permission denied, path too long
- **Network edge cases:** DNS failure, connection reset, partial response
- **Large inputs:** Very large PromptPackage, many data files, huge stream output

### 5. Fixture Realism

**Adequate:**
- `PromptPackage` fixtures contain realistic task/system prompts
- `ProviderReadiness` helpers correctly map provider to runtime
- `tmp_path` usage for file system isolation is correct
- `_StreamingProcess` helper in test_agent_runner.py realistically simulates async subprocess

**Inadequate:**
- `sample_package` fixtures contain minimal data (`{"trades": [{"id": 1}]}`) — real packages have 10+ data keys
- No fixtures with metadata populated (metadata field always empty)
- No fixtures with realistic curated data file paths
- `_mock_subprocess("")` returns empty stdout — real processes return JSON/JSONL
- No fixture that simulates a realistic multi-file run directory

---

## Recommendations (Priority Order)

1. **FIX test_provider_health.py patch targets** — All 18 tests are likely broken. Change `orchestrator.agent_runner.subprocess` to `orchestrator.provider_auth.subprocess`.

2. **Add ProviderCooldownTracker unit tests** — `record_failure()`, `is_cooled_down()`, TTL expiry, custom cooldown_seconds, `clear()` if available.

3. **Expand Codex stream parsing tests** — Match Claude's coverage level (at minimum: cost extraction, session ID, error handling, tool counting).

4. **Add cross-runtime fallback test** — Claude -> Codex fallback to verify runtime switching works.

5. **Replace private attribute injection** — Use public APIs or factory methods instead of `runner._provider_status_cache[...] = ...`.

6. **Remove duplicate TestCostTrackerOptional** — Present in both test_cost_tracking.py and test_hardening.py.

7. **Add boundary/edge case tests** for timeout=0, max_turns=0, empty fallback chains, and corrupt JSONL files.
