# Trading Assistant — Pre-Deploy Bug & Gap Remediation

## Context

A targeted audit of `trading_assistant` looked for bugs, silent-failure paths, and correctness gaps that would degrade or break the system in production. This plan is **revised after verifying every finding against the actual code** — several "critical" items from the initial sweep turned out to be false alarms and have been removed; the remaining items are confirmed against specific line numbers.

This pass covers **deploy blockers + correctness gaps**: HIGH issues that cause silent data loss, wrong output, or operational blind spots, plus MEDIUM correctness gaps that affect what the system tells the user.

### Verified false alarms (no action)

These were flagged in early exploration but verified to be non-issues:

- `orchestrator/db/queue.py:88-101` `claim()` — uses a single `UPDATE … WHERE event_id IN (SELECT …) RETURNING *` statement, atomic at SQLite level. Not a race.
- `skills/regime_parameter_analyzer.py:84-87` PF cap — already returns `min(pf, 99.99)` at L87. Consistent with `engine_decomposer.py:128`.
- `skills/autonomous_pipeline.py` "orphaned analyzers" — `AblationAnalyzer`, `EngineDecomposer`, `ExitTierAnalyzer` are wired into `skills/build_daily_metrics.py:1685-1716`; `RegimeParameterAnalyzer` is wired into `skills/parameter_searcher.py:153`. All four have downstream loaders in `analysis/context_builder.py` (`load_engine_decomposition` L1342, `load_ablation_analysis` L1370, `load_exit_tier_analysis` L1398, `load_regime_parameter_analysis` L1179). Fully integrated.
- `analysis/response_validator.py` "no metrics output" — already emits per-block `logger.info("Blocked … %s", reason)` at L407, L426, L446, L489, and the handler writes a JSONL audit row to `memory/findings/validation_log.jsonl` at `orchestrator/handlers.py:2098-2127`. The only real gap is that this log captures `blocked_suggestions` but not `blocked_proposals` or `blocked_portfolio` — folded into M-new-1 below.
- `orchestrator/handlers.py` "14 bare except blocks" — over-counted. Of ~70 `except Exception` clauses, only 7 are `bare pass`. Most of those are tolerable defaults (e.g., `load_convergence_report` failure → empty dict). Only L3307/L3316 are operationally meaningful (silent JSONL drop) — folded into H-new below.
- `analysis/context_builder.py` "all loaders unbounded" — `_apply_temporal_window()` already exists (lines around 260-330) and is applied by 11 loaders (corrections, failure_log, allocation_history, active_suggestions, recalibrations, outcome_reasonings, discoveries, strategy_ideas, portfolio_outcomes, etc.). Real gap is narrower; see H5 below for the actual unbounded loaders.
- `data/bot_configs/crypto_trader.yaml` missing `timezone` — actually fine. Crypto runs 24/7 and `BotConfig.timezone: str = "UTC"` is the appropriate default. No fix needed.

---

## HIGH severity — fix before deploy

### H1. No `recover_stale()` on startup

`orchestrator/db/queue.py:173` `recover_stale()` is wired only as a periodic scheduled job (`_stale_recovery_job` at `orchestrator/app.py:1521-1522`). It is not invoked once during the lifespan startup at `orchestrator/app.py:1735`. If the process crashed mid-dispatch on a previous run, those events sit in `'processing'` until the next periodic tick — by default the recovery cron may not run for an hour after restart. For high-priority `alert` and `triage` actions that's an unacceptable lag.

The dispatch/ack ordering itself in `orchestrator/worker.py:90-107` is fine: try-except wraps `_dispatch` + `ack`, exception path calls `nack`. The hole is only the crash window (process killed between `_dispatch()` succeeding and `ack()` writing).

**Fix:** Call `await queue.recover_stale(timeout_seconds=300)` once inside the `lifespan` startup block at `orchestrator/app.py:~1735`, before the worker starts polling. Use a tighter timeout than the default 3600s for the startup call only — the periodic job can keep its current cadence.

### H2. Response parser drops items without count log

`analysis/response_parser.py:23-31` `_safe_parse_list` warns per-item but `parse_response()` (L150-152) never reports the totals. If 50 predictions arrive and 30 parse, no observability surfaces the loss.

**Fix:** In `parse_response()` immediately after each `_safe_parse_list` call, compute and log `parsed/total/dropped` via `logger.warning` when `dropped > 0`. Optionally extend `ParsedAnalysis` (`schemas/agent_response.py:79-88`) with a `dropped_counts: dict[str, int]` field so the handler can surface this in run artifacts.

### H3. Multi-block STRUCTURED_OUTPUT silently truncated

`analysis/response_parser.py:42-54` `_extract_structured_json` calls `pattern.search()` which returns the first match only. If a model emits an initial block then a corrected second block (a known behavior under long contexts), only the stale first one is parsed.

**Fix:** Replace `pattern.search()` with `list(pattern.finditer(response))` and take the **last** valid block per the existing convention that later output supersedes earlier. Apply to both `_BLOCK_PATTERN` and `_JSON_FENCE_PATTERN`.

### H4. Silent drop of trade/missed records during weekly re-load

`orchestrator/handlers.py:3300-3318` reads `trades.jsonl` / `missed.jsonl` line-by-line for the weekly window and silently `pass`es on any malformed record. With multiple bots × 7 days × hundreds of trades, even one bad line triggers a drop with zero visibility. Of the seven `bare pass` clauses in handlers.py, only this pair (L3307, L3316) handles operational data; the others guard tolerable feature-flag fall-backs.

**Fix:** Track `dropped_count` per file and `logger.warning("Dropped %d/%d records from %s", dropped, total, trades_file)` when non-zero. Same shape as the H2 fix in the parser.

### H5. Unbounded JSONL loads in ContextBuilder

`analysis/context_builder.py` exposes ~30 `load_*` JSONL loaders. The `_apply_temporal_window()` helper exists and is applied by 11 of them. The remaining ~13 loaders read entire files and are at risk of unbounded growth in production. The verified offenders are:

- `load_rejected_suggestions` (L154)
- `load_outcome_measurements` (L169)
- `load_correction_patterns` (L562)
- `load_forecast_meta` (L576)
- `load_search_signal_summary` (L688)
- `load_prediction_accuracy` (L725)
- `load_threshold_profile` (L935)
- `load_ground_truth_trend` (L954)
- `load_spurious_outcomes` (L1072)
- `load_search_reports` (L1151)
- `load_backtest_reliability` (L1204)

**Fix:** Audit each of the 13 loaders. For ones that legitimately need a *summary* (e.g., `load_forecast_meta` returns rolling stats, not raw events) — leave them. For ones that return raw lists (`load_outcome_measurements`, `load_rejected_suggestions`, `load_correction_patterns`, `load_spurious_outcomes`, `load_search_reports`), apply `_apply_temporal_window(records, max_age_days=90, max_entries=50)` at the return point. Add a per-instance memoization decorator (`functools.cached_property`-style or plain dict cache keyed on (loader_name, args)) so the same `ContextBuilder` reused across daily and weekly doesn't double-read.

### H6. Composite-score routing inconsistent when baseline ≤ 0

`skills/parameter_searcher.py:380-383` in `_route()`:

```python
if baseline_composite > 0:
    improvement = best.composite_score / baseline_composite     # ratio (≈1.10)
else:
    improvement = best.composite_score if best.composite_score > 0 else 0.0  # raw score (≈0.4)
```

The two branches produce values on different scales but are then compared against the same threshold (`_APPROVE_IMPROVEMENT`, etc.) at L390-401. When baseline composite is non-positive, candidates that should clearly APPROVE end up in DISCARD because their raw composite (≈0.4) is below the ratio threshold (≈1.05).

**Fix:** Define a single rule. Easiest: when `baseline_composite ≤ 0`, treat any positive candidate composite as a default APPROVE (or compute improvement against a small positive floor like `max(baseline_composite, 0.01)` so the ratio remains comparable). Add a unit test in `tests/test_parameter_searcher.py` that exercises the negative-baseline path and asserts a positive candidate is APPROVE.

### H7. Telegram polling failure is silently swallowed

`orchestrator/app.py:1758-1761`:

```python
try:
    await telegram_adapter.start_polling()
except Exception:
    logger.warning("Failed to start Telegram polling")
```

If polling fails to start, the entire suggestion-feedback loop (`approve suggestion #ID` / `reject suggestion #ID`) is silently dead. The system continues believing it can collect human decisions; in reality, no inbound Telegram message will ever reach `FeedbackHandler`.

**Fix:** On polling start failure: (a) `logger.error(..., exc_info=True)` not warning; (b) dispatch a CRITICAL alert through any other healthy channel (Discord, email) via the existing `dispatcher`; (c) set `app.state.telegram_healthy = False` so `/health` reflects degradation.

### H8. `AgentSuggestion.category` not validated against `CATEGORY_TO_TIER`

`schemas/agent_response.py:25-37` declares `category: str = ""` with the comment listing valid values, but no validator enforces it. `CATEGORY_TO_TIER` (L70-82) defines 11 known categories. A suggestion arriving with `category="novel_signal"` passes Pydantic, then `skills/suggestion_scorer.py` looks it up via `_TIER_TO_CATEGORY` (L23-29) — unknown values silently fall through with `setdefault` defaults, producing wrong-bucket scoring.

**Fix:** Add a Pydantic v2 `@field_validator("category")` in `AgentSuggestion` that maps unknown values to `"uncategorized"` and emits a `logger.warning`. Surface unknowns via the existing `validator_notes` so the prompt can be tightened iteratively.

---

## MEDIUM — correctness gaps

### M1. ~13 strategy-engine detectors fire without a min-evidence guard

`analysis/strategy_engine.py` defines 25 `detect_*` methods. Six have explicit `min_trades` parameters (`detect_time_of_day_patterns` L529, `detect_component_signal_decay` L670, `detect_regime_config_effectiveness` L1047, `detect_stress_entry_pattern` L1203, `detect_grade_selectivity` L1796) plus an inline check at L941 (`>= 10 trades`). The others (e.g., `detect_alpha_decay` L359, `detect_signal_decay` L405, `detect_exit_timing_issues` L440, `detect_correlation_breakdown` L489, `detect_drawdown_patterns` L584, `detect_position_sizing_issues` L624, `detect_filter_interactions` L724, `detect_factor_correlation_decay` L790, `detect_microstructure_issues` L963, `detect_funding_impact` L1752, `detect_confluence_quality` L1857, `detect_leverage_utilization` L1905, all six `detect_portfolio_*` methods) lack a guard. With 2-3 trades per regime, statistical noise becomes actionable noise.

**Fix:** Define `_MIN_EVIDENCE_TRADES = 5` at module scope and short-circuit each unguarded detector when the relevant `trade_count` (or `len(trades_in_regime)`) is below it. Pipe the count into the detector's emitted `DetectionContext` so the validator (already gating on `score.sample_size >= 5` in `analysis/response_validator.py:418, 435`) has end-to-end consistency.

### M2. No env-var validation for selected provider

`orchestrator/config.py:161-229` `from_env()` loads every secret as `env.get(KEY, "")` with no validation. Selecting `agent_default_provider="zai_coding_plan"` without `ZAI_API_KEY` succeeds at startup; the failure surfaces at first agent invocation, hours later.

**Fix:** Append to `from_env()` (after `cls(...)` construction) a validation block that checks the providers actually selected (default + per-workflow overrides) and raises a single startup `ValueError` listing all missing keys. Match against the matrix in `CLAUDE.md` ("Multi-LLM Configuration").

### M3. N+1 JSONL scan per weekly handler

`orchestrator/handlers.py:504-508`:

```python
if self._suggestion_tracker:
    for bid in portfolio_summary.bot_summaries:
        _recent_suggestions.extend(
            self._suggestion_tracker.get_recent_by_bot(bid, weeks=4)
        )
```

Each `get_recent_by_bot` re-reads `suggestions.jsonl`. With 10+ bots, the file is scanned 10× per weekly run.

**Fix:** Add `SuggestionTracker.get_recent_grouped(bot_ids: list[str], weeks: int) -> dict[str, list[SuggestionRecord]]` that scans once and groups in memory. Update the call site.

### M4. Startup catch-up has no per-occurrence timeout

`orchestrator/app.py:1791-1809` iterates `catchup.build_plan(...)` and awaits `scheduled_job_runner.run(...)` per occurrence. There's a per-occurrence `try/except` for failures, but no timeout. A hung missed-job (e.g., a daily analysis blocked on Claude CLI) blocks every later occurrence; the worker never starts.

**Fix:** Wrap each `scheduled_job_runner.run(...)` in `asyncio.wait_for(..., timeout=600)`. On `TimeoutError` log + continue. Catch-up is best-effort; the next periodic tick re-runs.

### M5. New analyzers covered by unit tests only — no end-to-end integration

`tests/test_ablation_analyzer.py`, `tests/test_engine_decomposer.py`, `tests/test_exit_tier_analyzer.py`, `tests/test_regime_parameter_analyzer.py` all use synthesized `TradeEvent` objects and `MagicMock` for the strategy registry. The production path is `build_daily_metrics → analyzer → curated JSON → ContextBuilder.load_*  → DailyPromptAssembler` — none of which is exercised by the existing tests. A schema rename or path mismatch between writer and reader would only surface in production.

**Fix:** Add four integration cases to the existing `tests/test_strategy_aware_integration.py` — one per analyzer. Each: (a) construct realistic `TradeEvent` fixtures, (b) run the relevant `BuildDailyMetrics` step end-to-end on a temp dir, (c) instantiate `ContextBuilder` against that dir, (d) assert `load_engine_decomposition / load_ablation_analysis / load_exit_tier_analysis / load_regime_parameter_analysis` returns non-empty, well-typed data. No mocks for the file I/O path.

### M6. Concurrent re-runs of `build_daily_metrics` for the same bot/date silently overwrite

`skills/build_daily_metrics.py:1916-1924` `_write_jsonl` uses `path.write_text(...)` which truncates. The output dir scoping (`<curated>/<date>/<bot>/`) makes cross-bot collisions impossible, but a manual re-run of `build_daily_metrics` for the same bot/date while a prior run is still mid-flight will silently wipe the in-flight output (or vice versa). Same applies if catch-up triggers a build for a date whose previous run is still pending.

**Fix:** Add a `filelock`-based guard keyed on `<date>/<bot>/.write.lock` covering the entire `write_curated()` block. Within the run, use `path.with_suffix(".tmp")` + `os.replace()` for each file write so a crash mid-write doesn't leave a half-written JSONL. The same pattern applies to `_write_json` (L1914) — atomic temp+rename instead of direct `write_text`.

### M-new-1. Validation log only captures blocked suggestions

`orchestrator/handlers.py:2103-2125` writes `blocked_details` to `memory/findings/validation_log.jsonl` from `validation.blocked_suggestions` only. The `validation` result also exposes `blocked_proposals` and `blocked_portfolio` (verified in `analysis/response_validator.py`), but neither is captured. Operators tracking gate effectiveness see only one of three streams.

**Fix:** Extend the JSONL row schema with `blocked_proposal_count`, `blocked_portfolio_count`, and parallel `details` arrays. Keep the existing `blocked_details` shape for backward compatibility — add new fields rather than restructure.

---

## Out-of-scope (deferred)

LOW-severity items not addressed here: per-agent decay tuning, scheduler degradation alerts, regex consolidation, the five truly tolerable `bare pass` blocks in handlers.py (L514, L522, L1537, L1984, L2932 — feature-flag fallbacks). Track as a separate hygiene pass.

---

## Critical files to modify

- `orchestrator/app.py` — H1, H7, M4
- `orchestrator/worker.py` — (already correct; touched only if H1 startup hook is best placed there)
- `orchestrator/handlers.py` — H4, M3, M-new-1
- `orchestrator/config.py` — M2
- `analysis/response_parser.py` — H2, H3
- `analysis/context_builder.py` — H5 (apply existing `_apply_temporal_window`)
- `analysis/strategy_engine.py` — M1
- `schemas/agent_response.py` — H8 (field validator)
- `skills/parameter_searcher.py` — H6
- `skills/build_daily_metrics.py` — M6 (filelock + atomic temp+rename)
- `skills/suggestion_tracker.py` — M3 (add `get_recent_grouped`)
- New tests in `tests/test_strategy_aware_integration.py` — M5
- New negative-baseline test in `tests/test_parameter_searcher.py` — H6

## Reusable existing infrastructure (don't reinvent)

- `analysis/context_builder._apply_temporal_window()` — already used by 11 loaders; reuse for H5
- `memory/findings/validation_log.jsonl` writer pattern at `orchestrator/handlers.py:2098-2127` — extend in place for M-new-1
- `orchestrator/db/queue.py:recover_stale()` — already implemented; H1 just adds a startup call
- Existing `min_trades` parameter pattern at `analysis/strategy_engine.py:529, 670, 1047, 1796` — replicate for M1
- `_TIER_TO_CATEGORY` reverse mapping at `skills/suggestion_scorer.py:23-29` — H8 validator can use this list as the canonical set
- `dispatcher` and existing channel adapters (Discord/email) for the H7 fall-back alert — don't add a new notification path

---

## Verification

End-to-end after fixes:

1. **Run full suite:** `pytest tests/ -q` — must stay green; four new integration tests (M5) and one negative-baseline test (H6) added.
2. **H1 — recover_stale on startup:** Manually mark an event as `'processing'` in SQLite, restart the orchestrator, confirm log line `recovered N stale events` and the event is back to `'pending'`.
3. **H2 / H4 — drop counts:** Submit a STRUCTURED_OUTPUT with 5 valid + 5 invalid predictions and a trades.jsonl with 5 valid + 2 corrupt lines; confirm `parsed=5 total=10 dropped=5` and `Dropped 2/7 records from trades.jsonl` in logs.
4. **H3 — multi-block:** Synth a response with two `STRUCTURED_OUTPUT` blocks; confirm the **second** is parsed.
5. **H5 — bounded loaders:** Generate a 100MB synthetic `outcomes.jsonl`; assert `base_package().data["outcome_measurements"]` has ≤ 50 entries and `base_package()` runtime < 2s.
6. **H6 — negative baseline routing:** Unit test asserts that with `baseline_composite = -0.2` and `best.composite_score = 0.6`, routing is APPROVE, not DISCARD.
7. **H7 — telegram fail:** Start with an invalid `TELEGRAM_BOT_TOKEN`; confirm Discord/email receive a CRITICAL alert and `/health` shows `telegram_healthy=False`.
8. **H8 — unknown category:** Feed a parsed suggestion with `category="novel_signal"`; confirm `validator_notes` references "uncategorized" and a warning is logged.
9. **M1 — min-evidence:** Run `strategy_engine.build_report` against a 2-trade fixture; confirm zero suggestions; with 6+ trades, confirm suggestions emitted.
10. **M2 — fast fail:** Start with `AGENT_PROVIDER=zai_coding_plan` and no `ZAI_API_KEY`; confirm immediate startup `ValueError` (not late failure).
11. **M3 — single scan:** Add a counter to `SuggestionTracker._read_jsonl` and assert it increments once per weekly run, regardless of bot count.
12. **M4 — catch-up timeout:** Inject a sleep into a job; confirm the runner moves on after 600s.
13. **M5 — analyzer integration:** Each new test must FAIL if any of the four analyzer outputs aren't successfully read back by `ContextBuilder`.
14. **M6 — concurrent build:** Launch two `build_daily_metrics` for the same bot/date concurrently; confirm one acquires the filelock and the other waits, no JSONL truncation.
15. **M-new-1 — full validation log:** Trigger a run that blocks a suggestion, a structural proposal, and a portfolio proposal; confirm all three counts and details land in `validation_log.jsonl`.
16. **Smoke:** `uvicorn orchestrator.app:app --reload` — `/health` green, `/metrics` populated, send a test event end-to-end (queue → worker → handler → comms), confirm the expected curated + parsed_analysis files are produced and `validation_log.jsonl` gains a row.
