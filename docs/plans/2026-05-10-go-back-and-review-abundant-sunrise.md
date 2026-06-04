# Plan — Address valid trading_assistant findings from 2026-05-10 audit

## Context

The 2026-05-10 audit (`docs/2026-05-10-carefully-read-the-following-shiny-moon.md`) raised ~60 findings across the trading monorepo. Almost all live in the trading repo itself (`_references/trading/`). Only three findings are addressable inside `trading_assistant`:

- **TA-1** Bot config IDs drift: `data/bot_configs/swing_trader.yaml` and `momentum_trader.yaml` declare internal `bot_id: swing_trader` / `bot_id: momentum_trader`, while every other surface (`.env.example BOT_IDS`, `data/strategy_profiles.yaml`, the trading runtime emitter, the trading sidecar) uses `swing_multi_01` / `momentum_nq_01`. Events arriving from the bots carry the new IDs, so the trading_assistant has been silently mismatched.
- **TA-2** Stale strategy URDs: `data/strategy_profiles.yaml` URDs drift from live values in `_references/trading/config/strategies.yaml`. The audit cited NQ alone, but verification reveals **6 strategies** drift, 3 severely (6× over).
- **Hardcoded refs uncovered during verification:** `orchestrator/handlers.py:3596-3687` hardcodes `"swing_trader"` for both bot_summaries lookup and curated-data path construction (`_curated_dir / date_str / "swing_trader" / "coordinator_impact.json"`). With real bot data emitted under `swing_multi_01`, these code paths have been silently inert. This was missed by the audit but is the same root cause as TA-1.

`docs/2026-05-10-...md` Phase F (MEMORY refresh) targets the trading repo's MEMORY, not ours — out of scope.

## Verified substrate (reuse, do not rebuild)

- `skills/config_registry.py:43` — loader uses `data.get("bot_id", yaml_file.stem)`. **Internal `bot_id:` field wins over filename.** Filename rename is cosmetic; field change is what actually moves the registry key. (Reuse: change the field; rename file optionally for clarity.)
- `schemas/bot_config.py:7-10` — `BotConfig.bot_id` is `str` with no cross-validation against filename. Safe to update field.
- `orchestrator/strategy_registry_loader.py:14-41` — canonical `yaml.safe_load → StrategyRegistry.model_validate` pattern. Reuse for the drift test.
- `schemas/strategy_profile.py:34` — `StrategyRisk.unit_risk_dollars: float` is the field to update.
- `tests/fixtures.py:64-69` — generic `data_dir` fixture; no BotConfig fixtures exist, so drift test reads files directly.
- `_references/trading/config/strategies.yaml` — confirmed source of truth, top-level `strategies:` key.

## Changes

### 1. TA-1 — Bot config ID alignment

Edit `data/bot_configs/swing_trader.yaml` line 1:
- `bot_id: swing_trader` → `bot_id: swing_multi_01`

Edit `data/bot_configs/momentum_trader.yaml` line 1:
- `bot_id: momentum_trader` → `bot_id: momentum_nq_01`

**Do NOT rename the YAML filenames.** Loader keys off the `bot_id:` field; renaming files adds git noise without behavioral change. The `repo_url` / `repo_dir` fields inside (e.g. `/repos/swing_trader`) remain untouched — those are upstream repo identifiers, not bot IDs.

### 2. Hardcoded references in handlers.py

`orchestrator/handlers.py`:
- Line 3596: `if "swing_trader" in bot_summaries:` → `if "swing_multi_01" in bot_summaries:`
- Line 3600: `bot_id="swing_trader"` → `bot_id="swing_multi_01"`
- Line 3602: `trades_by_bot.get("swing_trader", [])` → `trades_by_bot.get("swing_multi_01", [])`
- Line 3687: `self._curated_dir / date_str / "swing_trader" / "coordinator_impact.json"` → `self._curated_dir / date_str / "swing_multi_01" / "coordinator_impact.json"`
- Line 3676 docstring: `"swing_trader"` → `"swing_multi_01"`

These are the *consumer* side of the same mismatch. With real events under `swing_multi_01`, the current literals never match. Update in lockstep with the YAML field.

### 3. Test data alignment

`tests/test_allocation_integration.py`:
- Line 24: `_BOTS = ["k_stock_trader", "momentum_trader", "swing_trader"]` → `["k_stock_trader", "momentum_nq_01", "swing_multi_01"]`
- Lines 75, 93: `_make_daily_with_strategies(date, "momentum_trader", …)` / `"swing_trader"` → updated bot_ids
- Lines 64-65, 76, 94: dict key `dailies["momentum_trader"]` / `dailies["swing_trader"]` → updated
- Line 161-165: `"momentum_trader" in p.strategy_a` substring check → `"momentum_nq_01"`
- Line 185-186: `r.bot_id == "momentum_trader"` → `r.bot_id == "momentum_nq_01"` (and the assertion message stays semantic — NQ concentration is still about momentum bot)

### 4. TA-2 — Strategy URD refresh

Update `data/strategy_profiles.yaml` `unit_risk_dollars` for 6 strategies to match `_references/trading/config/strategies.yaml`:

| Strategy | Profile (current) | Trading (live) | New |
|----------|-------------------|----------------|-----|
| NQDTC_v2.1 | 300.0 | 50.0 | **50.0** |
| NQ_REGIME | 300.0 | 50.0 | **50.0** |
| DownturnDominator_v1 | 300.0 | 50.0 | **50.0** |
| VdubusNQ_v4 | 300.0 | 200.0 | **200.0** |
| IARIC_v1 | 150.0 | 100.0 | **100.0** |
| ALCB_v1 | 150.0 | 100.0 | **100.0** |
| ATRSS / AKC_HELIX / TPC | 200.0 | 200.0 | (no change) |

`AKC_Helix_v40` is retired upstream — leave its profile entry as-is (separate cleanup, not in scope).

### 5. New drift test

Create `tests/test_strategy_profile_drift.py` (~80 LoC):

- Load `data/strategy_profiles.yaml` via `orchestrator.strategy_registry_loader.load_strategy_registry()` (reuse, don't open-code).
- Load `_references/trading/config/strategies.yaml` via `yaml.safe_load`.
- Build `{strategy_id: unit_risk_dollars}` map from each.
- For every strategy that exists in **both** files, assert URDs match. Skip strategies present in only one (assistant-only retired entries, trading-only new entries) with an explicit `pytest.skip` so misses are visible.
- Also assert each profile's `bot_id` value is one of the canonical four: `{k_stock_trader, stock_trader, swing_multi_01, momentum_nq_01}` (crypto excluded, separate pool).

This catches both URD drift and any future bot_id drift. Reuses `load_strategy_registry()` and `yaml.safe_load` patterns already in the codebase.

## Critical files to modify

- `data/bot_configs/swing_trader.yaml` (line 1)
- `data/bot_configs/momentum_trader.yaml` (line 1)
- `orchestrator/handlers.py` (lines 3596, 3600, 3602, 3676, 3687)
- `tests/test_allocation_integration.py` (lines 24, 64-65, 75-76, 93-94, 161-165, 185-186)
- `data/strategy_profiles.yaml` (URD updates for 6 strategies)
- `tests/test_strategy_profile_drift.py` (NEW)

## Out of scope

- Phase F MEMORY.md refresh: targets the trading repo, not us.
- All P0/P1 OMS, SWING, CONN, RELAY, INFRA, STRAT findings: live in `_references/trading/`, not in trading_assistant.
- YAML filename rename: cosmetic only; loader uses `bot_id:` field.
- AKC_Helix_v40 retirement cleanup: separate task.

## Verification

1. `pytest tests/test_allocation_integration.py -v` — confirm renamed bot_ids still pass (test logic unchanged, only string literals).
2. `pytest tests/test_strategy_profile_drift.py -v` — new test passes after URD updates.
3. `pytest tests/ -k "config_registry or bot_config"` — confirm bot_config loading still works after field changes.
4. `pytest tests/` — full suite still green (~3154 tests).
5. Manual smoke: launch `python -c "from skills.config_registry import ConfigRegistry; r = ConfigRegistry('data/bot_configs'); print(r.list_bot_ids())"` — should print `['crypto_trader', 'k_stock_trader', 'momentum_nq_01', 'stock_trader', 'swing_multi_01']`.
6. Manual: grep `git grep -n 'swing_trader\b\|momentum_trader\b' -- orchestrator/ tests/ skills/ analysis/ schemas/` — every remaining hit should be either a comment, a `repo_dir` (upstream repo path), or in a docstring example. No live code path should reference the old IDs.
