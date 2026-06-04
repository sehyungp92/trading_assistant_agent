# Plan: Optimally connect trading_assistant with crypto_trader

## Context

The user wants `trading_assistant` to deliver meaningful, evidence-grounded improvements to the **crypto_trader** bot — at parity with momentum_nq_01, swing_multi_01, and stock_trader. The existing crypto integration covers ~85% of the surface (config file present, 4 detectors, validator gates, prompt supplement, `_CURATED_FILES` already lists funding/grade/confluence/leverage analysis, 18 crypto detector tests, archetype enum populated). However, a deep audit against the latest reference at `_references/crypto_trader/` reveals four hard gaps that prevent the assistant from acting on crypto data:

1. **Config drift (silent blocker).** `data/bot_configs/crypto_trader.yaml` declares all 40+ parameters as `TOML_FIELD` with `file_path: config/momentum_pullback.toml` etc. The actual bot stores its strategy params in **JSON** at `config/strategies/{momentum,trend,breakout}.json`, with a different nested key shape: `strategy.indicators.ema_fast` (not `entry.ema_fast`), `strategy.filters.funding_extreme_threshold` (not `filters.funding_extreme`), `strategy.exits.tp1_r`, `strategy.risk.risk_pct_a`, etc. Result: `ConfigRegistry._validate_parameter_definition` (skills/config_registry.py:111-122) rejects every crypto param at load time because `repo_dir / file_path` doesn't exist; `FileChangeGenerator.generate_change` (skills/file_change_generator.py:23-61) has no JSON branch even if it did. So no crypto parameter suggestion can ever reach a PR.

2. **Two untapped event streams.** The bot's sidecar emits `PipelineFunnelSnapshot` (signals→entries→exits funnel, written to `pipeline_funnels.jsonl`) and `HealthReportSnapshot` (`health_reports.jsonl`). Verified at `_references/crypto_trader/src/crypto_trader/instrumentation/types.py` and `sinks.py`. Neither has a Pydantic schema in `schemas/events.py`, neither is routed by `OrchestratorBrain._handlers` (orchestrator/orchestrator_brain.py:327-338), and neither has a curated builder in `skills/build_daily_metrics.py`.

3. **Five missing crypto detectors.** `analysis/strategy_engine.py` has `detect_funding_impact`/`detect_grade_selectivity`/`detect_confluence_quality`/`detect_leverage_utilization` but lacks: multi-timeframe alignment drift, liquidation proximity, BTC/ETH/SOL symbol concentration, 24/7 session patterns (Asia 00–04 / EU 07–11 / US 13–17 UTC, matching the windows already named in `_CRYPTO_DAILY_SUPPLEMENT`), per-symbol funding trend over weeks.

4. **Empty regime sensitivity, no policy, no crypto outcome categories.** `data/strategy_profiles.yaml` lines 358/396/434: `macro_regime_sensitivity: {}` for all 3 crypto strategies. `memory/policies/v1/trading_rules.md`: zero references to crypto/perpetual/funding/leverage. `skills/auto_outcome_measurer.py:31-39`: `CATEGORY_TO_TARGET_METRIC` only covers stop_loss/exit_timing/signal/filter_threshold/position_sizing/regime_gate/structural — so crypto-specific suggestions (`funding_threshold`, `leverage_cap`, `confluence_count`, `setup_grade_filter`) skip target-metric evaluation entirely. `.env.example` `BOT_TIMEZONES` line 9 doesn't list crypto_trader.

Outcome of this plan: parity with the other bots. Strategy optimizer can patch crypto JSON configs. Funnel + health data flow into prompts. Five new detectors fire on weekly analysis. Crypto-specific policy + regime sensitivity + outcome categories let suggestions be validated and learned from over time.

---

## Phase 1 — Fix config drift (highest leverage; blocker for all optimization output)

### 1.1 Add `JSON_FIELD` parameter type
`schemas/autonomous_pipeline.py`:
- `ParameterType` (line 13–18): add `JSON_FIELD = "JSON_FIELD"`.
- `FileChangeMode` (line 34–39): add `JSON_FIELD = "json_field"`.
- `ParameterDefinition._check_type_fields` (line 59–72): add a clause requiring `python_path` (used as JSON dotted path) when `param_type == JSON_FIELD`. Mirrors the existing TOML_FIELD clause.

`skills/file_change_generator.py`:
- Add `_modify_json_field(content, json_path, new_value)` mirroring `_modify_toml_field` (line 409–436): parse with `json.loads`, walk dotted path, replace leaf, re-emit with `json.dumps(doc, indent=2)` followed by a trailing newline. Preserve type via the existing `value_type` (int vs float vs bool).
- Add a new branch to `generate_change` (line 36–53): `elif param.param_type == ParameterType.JSON_FIELD: ... change_mode = FileChangeMode.JSON_FIELD; metadata = {"json_path": param.python_path or ""}`.
- Optional: pretty-print formatting that matches the reference momentum.json (2-space indent, no trailing newline diff churn — verify against `_references/crypto_trader/config/strategies/momentum.json`).

`skills/config_registry.py`: no change needed — `_validate_parameter_definition` (line 92–123) already round-trips through `generate_change` so JSON paths get validated via the new writer.

### 1.2 Rewrite `data/bot_configs/crypto_trader.yaml`
Apply per-parameter:
- `param_type: TOML_FIELD` → `param_type: JSON_FIELD`
- `file_path`:
  - momentum_pullback.toml → `config/strategies/momentum.json`
  - institutional_anchor.toml → `config/strategies/trend.json`
  - volume_profile_breakout.toml → `config/strategies/breakout.json`
- `python_path` rewrites (verified against the actual JSON):
  - `entry.ema_fast`/`ema_mid`/`ema_slow` → `strategy.indicators.ema_fast` etc.
  - `entry.adx_period` → `strategy.indicators.adx_period`
  - `entry.min_confluences_a/b` → `strategy.setup.min_confluences_a/b`
  - `entry.min_room_a/b` → `strategy.setup.min_room_a/b`
  - `entry.entry_on_close` → `strategy.entry.entry_on_close`
  - `entry.require_volume` → `strategy.confirmation.require_volume_confirm` (verify exact key in trend.json)
  - `entry.h1_adx_threshold` → `strategy.bias.h1_adx_threshold`
  - `entry.min_4h_conditions` → `strategy.bias.min_4h_conditions`
  - `risk.risk_pct_a/b` → `strategy.risk.risk_pct_a/b` (verify presence — may live in portfolio_config.json instead; if so, file_path changes accordingly)
  - `risk.max_leverage_major/alt` → `strategy.risk.max_leverage_major/alt` (same caveat)
  - `risk.max_concurrent` → `strategy.risk.max_concurrent` (or portfolio_config.json)
  - `exit.tp1_r`/`tp2_r` → `strategy.exits.tp1_r`/`tp2_r`
  - `exit.soft_time_stop`/`hard_time_stop` → `strategy.exits.soft_time_stop`/`hard_time_stop` (verify; may be `time_stops`)
  - `filters.funding_extreme` → `strategy.filters.funding_extreme_threshold` (note name change — verified)
  - `filters.atr_expansion_mult` → `strategy.filters.atr_expansion_mult` (verify; may be elsewhere)
  - VolumeProfileBreakout: `entry.volume_bins`, `entry.lookback_bars`, etc. → `strategy.{indicators|setup|entry}.<key>` per breakout.json
- `current_value` re-pegged to live defaults (e.g., momentum tp1_r = 1.2 not 1.0; tp1_frac = 0.16 may need to be added if mutable).
- `allowed_edit_paths`: include `config/strategies/*` and `src/crypto_trader/strategy/**`.
- `structural_context_paths`: same plus `src/crypto_trader/portfolio/*`.
- `verification_commands`: read from `_references/crypto_trader/pyproject.toml`; use the exact pytest invocation the bot uses.

**Implementation note**: before writing, do a quick scripted diff between every declared `python_path` and the actual JSON keys in `_references/crypto_trader/config/strategies/*.json`. Any path that doesn't resolve must be either remapped or dropped. A few params (esp. risk and leverage caps) likely live in `portfolio_config.json` rather than the per-strategy JSON — those entries get a different `file_path`.

### 1.3 Tests
- `tests/test_file_change_generator.py`: add JSON_FIELD round-trip tests for int/float/bool/str leaves; nested dotted path; missing path raises.
- `tests/test_config_registry.py`: add a fixture bot config that uses JSON_FIELD; assert it loads cleanly when the JSON file exists.
- `tests/test_crypto_integration.py`: assert every parameter in `data/bot_configs/crypto_trader.yaml` resolves cleanly against the reference JSON files (use `_references/crypto_trader/` as the temp repo dir).

---

## Phase 2 — Ingest PipelineFunnelSnapshot + HealthReportSnapshot

### 2.1 Schemas
`schemas/events.py`: add Pydantic v2 models mirroring the reference dataclasses (`_references/crypto_trader/src/crypto_trader/instrumentation/types.py`):
- **`PipelineFunnelSnapshot`** — `event_metadata`, `bot_id`, `strategy_id`, `date`, `signals_generated`, `setups_qualified`, `confirmations_passed`, `entries_taken`, `wins`, `losses`, `per_strategy_breakdown: dict`, `per_symbol_breakdown: dict`, `assessment: str = ""`. Use `model_config = {"extra": "ignore"}` like existing events.
- **`HealthReportSnapshot`** — `event_metadata`, `bot_id`, `uptime_pct`, `last_event_age_sec`, `queue_depth`, `funding_drift_per_symbol: dict`, `websocket_disconnects_24h`, `error_count_24h`, `severity: str`, `notes: str = ""`.

### 2.2 Ingestion route (NB: assistant uses `/ingest`, not `/events`)
- `orchestrator/app.py` `/ingest` endpoint: union the new event types into the inbound dispatcher. Verify in implementation what shape `/ingest` accepts — if it accepts a generic `dict` keyed by `event_type`, only the brain routing change is needed.
- `orchestrator/orchestrator_brain.py` `_handlers` dict (line 327–338): add `pipeline_funnel` and `health_report` keys mapped to a new lightweight handler `handle_telemetry_event` that persists to disk without spawning a subagent.
- `orchestrator/handlers.py`: add `handle_telemetry_event(event)` that appends to `data/curated/<date>/<bot>/funnel_snapshots.jsonl` or `health_snapshots.jsonl` based on event_type. Use the same date-resolution helpers other handlers already use (UTC for crypto_trader since its market_close_local is 00:00).
- `orchestrator/db/queue.py`: no change — already keys on `event_id`.

### 2.3 Curated builders + prompt context
`skills/build_daily_metrics.py`: add `_build_funnel_analysis(funnel_snapshots)` → writes `funnel_analysis.json` with top drop-off stages (signals→qualified, qualified→confirmed, confirmed→entries) and per-strategy/per-symbol conversion rates. Add `_build_health_summary(health_snapshots)` → writes `health_summary.json` with 24h disconnects, max funding drift, last_event_age. Wire both into the existing crypto block alongside funding/grade/confluence/leverage builders (around line 1793–1807).

`analysis/prompt_assembler.py` `_CURATED_FILES` (lines 18–56): append `funnel_analysis.json` and `health_summary.json`.

`_CRYPTO_DAILY_SUPPLEMENT` (lines 270–293): append two short paragraphs:
- Funnel triage: identify top drop-off stage; cross-reference with detector findings (e.g., if "qualified→confirmed" leaks AND `detect_confluence_quality` flags low B-grade conversion, propose confirmation gate tightening).
- Health alerts: any HIGH severity in health_summary is a process-quality concern; do not propose strategy changes during periods with >5 disconnects/24h.

`analysis/weekly_prompt_assembler.py`: include funnel WoW conversion change in the weekly context.

`_FOCUSED_INSTRUCTIONS` STRUCTURED_OUTPUT block (lines 256–268): extend the `category` enum string from `exit_timing|filter_threshold|stop_loss|signal|structural|position_sizing|regime_gate` to `... |funding_threshold|leverage_cap|confluence_count|setup_grade_filter`. NB: `analysis/response_validator.py` does **not** maintain an allowlist of categories (verified — it filters via `_rejected` and track record), so no validator-side change is required for new categories to be accepted.

---

## Phase 3 — Five new crypto detectors

In `analysis/strategy_engine.py`, add to the existing crypto detector cluster (after `detect_leverage_utilization` ~line 2190). Each follows the existing detector signature and uses the archetype-default mechanism:

1. **`detect_mtf_alignment_drift`** — for trades whose `bias_direction` and `side` disagree, compute expectancy delta vs aligned trades. Flag if mismatched n≥10 AND win-rate gap ≥15pp.
2. **`detect_liquidation_proximity`** — compute `mae_r * leverage` (leverage from `sizing_inputs["leverage"]`). Flag any trade with value >0.7; if ≥3 such over 30 days, raise as systemic.
3. **`detect_symbol_concentration`** — group by `pair`; flag if one of {BTC,ETH,SOL} carries ≥70% of net negative pnl across ≥10 trades.
4. **`detect_session_patterns_24_7`** — bucket trade timestamps into Asia (00–04 UTC), EU (07–11), US (13–17) per the existing crypto supplement convention. Flag if one session is materially negative with ≥10 trades.
5. **`detect_funding_trend`** — funding cost as % of gross pnl per ISO week. Flag if rising ≥3 consecutive weeks AND last week >15% (10% for `volume_profile_breakout` per existing thresholds).

All five wired into `build_report()` via the existing optional-params pattern. Archetype-conditional thresholds in `_ARCHETYPE_DEFAULTS`. Add tests to `tests/test_crypto_detectors.py` (currently 18 tests) — at least empty-data, threshold-edge, and one positive case per detector.

---

## Phase 4 — Regime sensitivity, policy, outcome categories, timezone

### 4.1 Populate `data/strategy_profiles.yaml`
For MomentumPullback_M15 (line 358), InstitutionalAnchor_H1 (line 396), VolumeProfileBreakout_M30 (line 434), replace `macro_regime_sensitivity: {}` with archetype-appropriate G/R/S/D multipliers. Mirror the schema used by stock/momentum entries (numeric per-regime multipliers; "disabled" for regimes where the strategy shouldn't trade). Suggested defaults:
- MomentumPullback_M15 (trend-pullback): G:1.0, R:1.0, S:0.5, D:0.7
- InstitutionalAnchor_H1 (long-cycle trend): G:1.1, R:1.0, S:0.4, D:0.8
- VolumeProfileBreakout_M30 (range-break): G:0.8, R:0.9, S:1.1, D:0.6

### 4.2 Add crypto policy to `memory/policies/v1/trading_rules.md`
New H2 section "Crypto Perpetuals Discipline" covering:
- Hard leverage caps (5.0 major, 4.0 alt) — never lift without 60d evidence at confidence ≥0.9.
- Funding cost as a first-class P&L item — any hold-time-extending change must reason about funding.
- 24/7 cadence — daily windows are midnight UTC; no market-close concept; session windows are Asia/EU/US per supplement.
- Liquidation proximity (`mae_r * leverage > 0.7`) — process-quality failure, not a tunable.
- Symbol risk parity — no single symbol >70% of exposure without explicit opt-in.

### 4.3 Outcome measurer categories
`skills/auto_outcome_measurer.py` `CATEGORY_TO_TARGET_METRIC` (line 31–39): add
```
"funding_threshold": "pnl",
"leverage_cap": "drawdown",
"confluence_count": "win_rate",
"setup_grade_filter": "win_rate",
```
Plus tests in `tests/test_auto_outcome_measurer.py`.

### 4.4 BOT_TIMEZONES default
`.env.example` line 9: append `,crypto_trader:UTC:00:00` to the existing string. (Verified the format is the three-field `bot_id:tz:HH:MM` already supported by `orchestrator/config._parse_bot_timezones`.)

---

## Phase 5 — End-to-end validation

- Run the full test suite (currently ~3154+ tests). Target ≥30 new tests across phases 1–4. All existing tests must still pass.
- Manual smoke test: stage 5 synthetic InstrumentedTradeEvents + 1 PipelineFunnelSnapshot + 1 HealthReportSnapshot via the relay polling path; run `python -m orchestrator.scheduler --run-now daily_report` for `crypto_trader`; confirm the output `daily_report.md` references at least one funnel drop-off and one new detector finding.
- Sanity check: load `data/bot_configs/crypto_trader.yaml` via `ConfigRegistry` against `_references/crypto_trader` as the repo dir — assert `load_errors` is empty.

---

## Open implementation-time verification points (do these *while* writing, not before)

1. **`strategy_id` shape from the bot.** `EventMetadata.strategy_id` (reference types.py:113) is a free string set by `Collector(strategy_id=...)` at construction. Verify the bot constructs collectors with `MomentumPullback_M15`/`InstitutionalAnchor_H1`/`VolumeProfileBreakout_M30` (matching `data/strategy_profiles.yaml` ids), not internal short keys `momentum`/`trend`/`breakout`. If the bot uses short keys, surface as a bot-side recommendation (see below) and add a temporary mapping in `orchestrator/orchestrator_brain.py` until the bot ships the fix.
2. **`risk.risk_pct_a` JSON location.** May live in `config/strategies/momentum.json` under `strategy.risk` OR in `config/portfolio_config.json` under a per-strategy block. Confirm before finalising the YAML rewrite — wrong file_path is the same kind of silent failure we're fixing.
3. **`/ingest` endpoint shape.** Confirm whether it accepts a generic dict or a typed Pydantic union; this determines whether new event types need to be added to a union or just routed by string.

---

## Bot-side recommendations (out of scope for this plan, but file as issues afterward)

- **Strategy ID alignment** — if the bot emits short keys (`momentum`/`trend`/`breakout`), align the emitter to the long IDs the assistant uses.
- **HealthReportSnapshot cadence** — recommend ≥5-min cadence so silent failures surface within a daily window.
- **PipelineFunnelSnapshot cadence** — recommend daily aggregation (not per-bar) to keep JSONL size sane.
- **Sidecar watermark file location** — ensure `.sidecar_watermarks.json` lives on a persistent volume.

---

## Critical files modified

- `schemas/autonomous_pipeline.py` — +JSON_FIELD enum members + validator clause
- `schemas/events.py` — +PipelineFunnelSnapshot + HealthReportSnapshot
- `skills/file_change_generator.py` — +_modify_json_field + dispatch branch
- `skills/build_daily_metrics.py` — +_build_funnel_analysis + _build_health_summary
- `skills/auto_outcome_measurer.py` — +4 crypto categories
- `analysis/strategy_engine.py` — +5 crypto detectors
- `analysis/prompt_assembler.py` — +2 curated files, +supplement paragraphs, +structured-output category list
- `analysis/weekly_prompt_assembler.py` — +funnel WoW context
- `data/bot_configs/crypto_trader.yaml` — full param-path rewrite (TOML→JSON)
- `data/strategy_profiles.yaml` — populate macro_regime_sensitivity for 3 crypto strategies
- `memory/policies/v1/trading_rules.md` — +Crypto Perpetuals Discipline section
- `orchestrator/orchestrator_brain.py` — +pipeline_funnel/health_report routes
- `orchestrator/handlers.py` — +handle_telemetry_event
- `orchestrator/app.py` — `/ingest` accepts new event types (only if it currently uses a closed union)
- `.env.example` — append crypto_trader to BOT_TIMEZONES
- `tests/test_file_change_generator.py`, `tests/test_config_registry.py`, `tests/test_crypto_detectors.py`, `tests/test_crypto_integration.py`, `tests/test_auto_outcome_measurer.py` — coverage for all new code

## Reused functions / utilities (no reinvention)

- `FileChangeGenerator._modify_toml_field` (skills/file_change_generator.py:409) — mirror pattern for JSON
- `ConfigRegistry._validate_parameter_definition` (skills/config_registry.py:92) — already round-trips via `generate_change`, no changes needed once JSON_FIELD is supported
- `OrchestratorBrain._handlers` dispatch (orchestrator/orchestrator_brain.py:327) — add string keys, no architectural change
- `DailyPromptAssembler._CURATED_FILES` (analysis/prompt_assembler.py:18) — append, don't refactor
- `_CRYPTO_DAILY_SUPPLEMENT` (analysis/prompt_assembler.py:270) — append paragraphs to existing block
- `_has_crypto_strategies()` gate (analysis/prompt_assembler.py:392) — no change; supplement injection already conditional on archetype
- `StrategyEngine` `_ARCHETYPE_DEFAULTS` (analysis/strategy_engine.py:60–82) — extend, don't restructure
- `AutoOutcomeMeasurer.CATEGORY_TO_TARGET_METRIC` (skills/auto_outcome_measurer.py:31) — add keys
- Existing 18 crypto-detector tests (tests/test_crypto_detectors.py) — established fixtures and patterns to copy
