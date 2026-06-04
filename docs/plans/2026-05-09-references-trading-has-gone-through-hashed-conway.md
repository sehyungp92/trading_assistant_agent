# Sync trading_assistant to the reshuffled `_references/trading/`

## Context

`_references/trading/` is the swing+momentum+stock monorepo. The latest commit `c412a8d Strategy optimisation` deleted three live swing strategies and one momentum strategy outright (their `strategies/<family>/<name>/` dirs are now empty), and an earlier commit `00d3936 Third commit` added a new momentum strategy plus a deferred futures research family. `trading_assistant`'s job is to consume bot events and produce *evidence-grounded structural improvement proposals* — that requires the registry, attribution path, and prompt context to match what's actually deployed.

**Note on scope: each bot has its OWN reference repo.** Other bots (`_references/k_stock_trader/`, `_references/crypto_trader/`, `_references/momentum_trader/`, `_references/stock_trader/`, `_references/swing_trader/`) live under `_references/` and are out of scope here — the user's stated change is to `_references/trading/` only. The plan does NOT touch YAML entries for `k_stock_trader` or `crypto_trader` based on absence from `_references/trading/`.

### Verified ground truth (`_references/trading/strategies/`, HEAD = `c412a8d`)

| Family | Dir | Status | YAML mapping (current) |
|---|---|---|---|
| swing | `akc_helix/` | **alive** (added `circuit.py` in c412a8d) | "AKC Helix Divergence Swing" — keep |
| swing | `atrss/` | **alive** | "ATR Swing Strategy" — keep |
| swing | `breakout/` | **dead** (only empty `tests/` dir remains) | "Swing Breakout v3" — REMOVE |
| swing | `brs/` | **dead** (empty dir) | "Bear Regime Swing R9" (BRS = Bear Regime Swing) — REMOVE |
| swing | `keltner/` | **dead** (empty dir) | (no current YAML entry) |
| swing | `overlay/` | **alive** (4 files: `__init__.py`, `config.py`, `engine.py`, `shared.py`) | likely the home of "S5 Pullback" / "S5 Dual Pullback" — VERIFY by reading `overlay/config.py` |
| swing | `tpc/` | **alive — NEW** (full implementation, added in c412a8d — the only genuinely new swing) | ADD |
| momentum | `helix_v40/` | **dead** (empty dir, deleted in c412a8d) | "AKC Helix Multi-TF Momentum v40" — REMOVE |
| momentum | `nqdtc/` | **alive** | "NQ Day Trade Channel v2.1" — keep |
| momentum | `vdub/` | **alive** | "Vdubus NQ VWAP Pullback v4" — keep |
| momentum | `downturn/` | **alive** | "Downturn Multi-Engine Bear" — keep |
| momentum | `nq_regime/` | **alive — NEW** (added in `00d3936 Third commit`) | ADD |
| stock | `iaric/`, `alcb/` | both alive | keep both |
| stock | `us_orb/` | **dead** (empty dir) | "US Opening Range Breakout v1" — REMOVE |
| deferred futures research family | `ivb_auction/`, `po3_reversal/` | outside production repo | **deferred per user** |

S5 Pullback / S5 Dual Pullback need explicit verification: if they map to `overlay/` (likely) they survive; if they mapped to `breakout/` (dead) they need removal. Read `overlay/config.py` + `overlay/engine.py` during implementation to decide.

### Code-side gaps (verified by reading actual code)

1. **`StrategySuggestion` already carries `strategy_id` + `strategy_archetype`** (`schemas/strategy_suggestions.py:33-34`), but `_record_suggestions` (`orchestrator/handlers.py:2886+`) maps it to `SuggestionRecord` (`schemas/suggestion_tracking.py:25-55`), which has **no `strategy_id` field**. The strategy attribution is silently dropped.

2. **`AgentSuggestion`** (`schemas/agent_response.py:54-67`) has `engine`, `regime_condition`, `ablation_flag` — but **no `strategy_id`**. So Claude-emitted suggestions can't be attributed to a strategy at all.

3. **`AgentPrediction`, `PredictionRecord`, `CategoryScore`, `TransferProposal`/`TransferOutcome`, `ForecastMetaAnalysis`** are bot-keyed only.

4. **`SuggestionScorer.compute_scorecard()`** (`skills/suggestion_scorer.py:76`) groups by `(bot_id, category)`. It already supports stratification (`compute_regime_stratified_scores` at line 165, macro-regime confidence adjustment at line 212, detector confidence at line 330) — the same pattern can layer in strategy stratification.

5. **`HypothesisRecord`** (`schemas/hypothesis.py`) is intentionally cross-strategy (keyed by `category`). Do **not** add `strategy_id` here.

6. **No `is_active(strategy_id)` helper** on `StrategyRegistry`. **No filtering** in `analysis/context_builder.py` loaders. Records pinned to retired strategies linger in prompt context forever.

7. **Regime taxonomy actually used**: `trending_up`, `trending_down`, `ranging`, `volatile`, `compression` (NOT `bull`/`bear`/`chop`/`trend`/`range` — Agent #1 was wrong) plus macro `G`/`R`/`S`/`D`. Reflected correctly in `data/strategy_profiles.yaml` and `analysis/strategy_engine.py`.

User decisions: manual YAML refresh + drift checker; *optimal* learning re-keying; aggressive retirement; **defer futures research family**.

---

## Phase 1 — Refresh `data/strategy_profiles.yaml` against `_references/trading/`

### 1a. Scope of edits

**Remove (deleted from `_references/trading/`):**
- `swing_multi_01` → "Swing Breakout v3" (`breakout/` empty)
- `swing_multi_01` → "Bear Regime Swing R9" (`brs/` empty)
- `momentum_nq_01` → "AKC Helix Multi-TF Momentum v40" (`helix_v40/` empty)
- `stock_trader` → "US Opening Range Breakout v1" (`us_orb/` empty)

**Conditionally remove (verify first):**
- `swing_multi_01` → "S5 Pullback" / "S5 Dual Pullback" — read `_references/trading/strategies/swing/overlay/config.py` and `overlay/engine.py`. If overlay implements them, **rename** the YAML entries to point at overlay (single entry, one or two depending on what overlay actually does). If they were tied to the now-dead `breakout/`, **remove**.

**Add (currently in `_references/trading/`, not in YAML):**
- `swing_multi_01` → new entry for `tpc/`. Source metadata from `_references/trading/strategies/swing/tpc/config.py` and `tpc/__init__.py`: display_name, asset class (mixed, given _shared/etf_*), preferred/adverse regimes, holding_period, archetype, key_metadata_fields, exit_profile.
- `momentum_nq_01` → new entry for `nq_regime/`. Source metadata from `_references/trading/strategies/momentum/nq_regime/config.py` and the four module files (`liquidity_reversion.py`, `second_wind.py`, `structural_expansion.py`, `base.py`) — the `modules/` shape suggests this is a multi-engine strategy, so the YAML's `sub_engines: list[str]` field (already present on `StrategyProfile`) is where they go.

**Re-validate (still alive but the optimization commit may have shifted them):**
- `swing_multi_01` → "ATR Swing Strategy" (`atrss/`), "AKC Helix Divergence Swing" (`akc_helix/` — `circuit.py` was added)
- `momentum_nq_01` → "NQ Day Trade Channel v2.1" (`nqdtc/`), "Vdubus NQ VWAP Pullback v4" (`vdub/`), "Downturn Multi-Engine Bear" (`downturn/`)
- `stock_trader` → both surviving (`iaric/`, `alcb/`)

For each surviving entry, re-derive `preferred_regimes`, `adverse_regimes`, `archetype`, `exit_profile` from the strategy's current `config.py` rather than trusting the YAML's pre-optimization values.

**Out of scope:**
- `swing_multi_01` → "S5 Pullback" / "S5 Dual Pullback" if overlay is unrelated (decide during implementation).
- Deferred futures research family — entirely outside this production pass per user.
- `k_stock_trader`, `crypto_trader` entries — separate reference repos, not in `_references/trading/`. Mention as a follow-up but do not touch in this plan.

### 1b. `StrategyArchetype` enum

`schemas/strategy_profile.py:9-25` currently has 16 values. Verify whether `tpc/` and `nq_regime/` need a new archetype value; if so, add it AND add a matching block to the YAML's `archetype_expectations` section (lines ~552-628). Otherwise reuse an existing archetype.

### 1c. Drift checker — `skills/strategy_registry_drift.py` (new)

- Scan `_references/trading/strategies/{momentum,stock,swing}/` (skip deferred research packages per user, skip `_shared`, `instrumentation`, `coordinator.py`, `__init__.py`, `*.py` infra in `core/`).
- A directory counts as a *live strategy* only if it contains at least one of `engine.py`, `plugin.py`, or `__init__.py` with non-empty content (the `breakout/`/`brs/`/`keltner/` empty-dir case must be classified as **dead**, not as a registered strategy).
- Diff against `StrategyRegistry.strategies` keys; emit a structured `RegistryDrift` finding (added/removed/empty-shell lists).
- Wire into the daily handler's pre-analysis stage so the diff lands in the daily report's "Validator Notes" section. Do not block the run on drift — surface only.
- Future-proofing for k_stock/crypto: take an optional `reference_roots: list[Path]` parameter so the same checker can later be pointed at `_references/k_stock_trader/` and `_references/crypto_trader/`.

**Files modified:** `data/strategy_profiles.yaml` (targeted edits per the table above), `schemas/strategy_profile.py` (enum extension if needed), `skills/strategy_registry_drift.py` (new), `orchestrator/handlers.py` (call drift checker in daily pipeline).

`orchestrator/strategy_registry_loader.py` already loads YAML and gracefully returns an empty registry on parse failure — no loader changes.

`.env.example` is **not** changed: no new bots are introduced (`tpc`/`nq_regime` slot into existing `swing_multi_01` / `momentum_nq_01`).

---

## Phase 2 — Stop dropping `strategy_id`; key the learning loop on it

The optimal split: add `strategy_id` to every per-trade-evidence record (the bot already attributes trades to strategies, and `StrategySuggestion` already has the field), and let aggregate scorecards / forecast meta-analyses *also* emit strategy-stratified rows alongside the existing bot-stratified rows. No JSONL migration needed — `Optional[str] = None` is forward-compatible.

### 2a. Add `strategy_id: Optional[str] = None` to per-trade-evidence schemas

- `schemas/agent_response.py:54` — `AgentSuggestion.strategy_id`
- `schemas/agent_response.py:43` — `AgentPrediction.strategy_id`
- `schemas/suggestion_tracking.py:25` — `SuggestionRecord.strategy_id`
- `schemas/prediction_tracking.py:11` — `PredictionRecord.strategy_id`
- `schemas/transfer_proposals.py:11,23` — `TransferProposal.source_strategy_id`, `target_strategy_id`; mirror on `TransferOutcome`
- `schemas/suggestion_scoring.py:8` — `CategoryScore.strategy_id` (Optional; `None` = bot-wide aggregate row)
- `schemas/forecast_tracking.py` — extend `ForecastMetaAnalysis` with `accuracy_by_strategy: dict[str, float]` (alongside existing `accuracy_by_metric`)

`HypothesisRecord` is intentionally not changed.

### 2b. Stop throwing the strategy_id away in handlers

- **`orchestrator/handlers.py:2886+`** (`_record_suggestions`) — `StrategySuggestion` already carries `strategy_id` + `strategy_archetype`. Pass them into the new `SuggestionRecord.strategy_id` instead of dropping them. This is the single highest-leverage code change in the plan: the strategy engine already knows; the persistence layer already runs; only the field on `SuggestionRecord` is missing.
- **`orchestrator/handlers.py:3015+`** (`_record_agent_suggestions`) — read `strategy_id` from `AgentSuggestion` (now that it's a field) and pass into `SuggestionRecord`.
- **`skills/prediction_tracker.py`** — same: read off `AgentPrediction`, persist on `PredictionRecord`.

### 2c. Teach Claude to attribute suggestions/predictions per-strategy

- `analysis/daily_prompt_assembler.py`, `analysis/weekly_prompt_assembler.py` — extend the structured-output instruction so every suggestion and prediction MUST include `strategy_id` (drawn from the `StrategyRegistry` rendered into the prompt). Existing fields (`engine`, `regime_condition`, `ablation_flag`) coexist alongside `strategy_id`.

### 2d. Stratify scorecards/forecasts by strategy

- `skills/suggestion_scorer.py` — extend `compute_scorecard()` to emit BOTH `(bot_id, None, category)` rows (existing aggregate, preserves all callers) AND `(bot_id, strategy_id, category)` rows wherever `suggestions.jsonl` records carry a non-null `strategy_id`. Reuses temporal decay (`_compute_age_weight`), Bayesian posterior, target-metric weighting, and category-overrides — only the grouping axis is widened. Mirrors the existing `compute_regime_stratified_scores` pattern.
- `schemas/suggestion_scoring.py` — `CategoryScorecard.get_score()` accepts optional `strategy_id` arg; falls back to bot-wide row when no per-strategy row exists.
- `skills/forecast_tracker.py` — analogous extension: per-strategy accuracy alongside per-metric accuracy.

### 2e. Inject per-strategy scorecards into prompts

`analysis/context_builder.py` — `base_package().data` already loads `category_scorecard`. Extend rendering so per-strategy rows are surfaced under each bot's section: "for `iaric_pullback`, your `regime_gate` suggestions succeed 7/10 in `volatile` regimes; for `us_orb_v1`, 1/8." This is the single most impactful prompt change for the user's stated goal — it tells Claude *which strategy* its evidence applies to so structural proposals can be specific instead of bot-wide averages.

**Files modified:** `schemas/agent_response.py`, `schemas/suggestion_tracking.py`, `schemas/prediction_tracking.py`, `schemas/suggestion_scoring.py`, `schemas/transfer_proposals.py`, `schemas/forecast_tracking.py`, `analysis/context_builder.py`, `analysis/daily_prompt_assembler.py`, `analysis/weekly_prompt_assembler.py`, `orchestrator/handlers.py` (`_record_suggestions` line 2886, `_record_agent_suggestions` line 3015), `skills/suggestion_scorer.py`, `skills/forecast_tracker.py`, `skills/prediction_tracker.py`.

**No migration:** all field additions are `Optional` with `None` default. Legacy JSONL records load fine; per-strategy rows simply don't appear until new records arrive.

---

## Phase 3 — Retire records for dead strategies

### 3a. `is_active(strategy_id)` on `StrategyRegistry`

`schemas/strategy_profile.py:132` — add a one-line helper:
```python
def is_active(self, strategy_id: str) -> bool:
    return strategy_id in self.strategies
```

### 3b. Filter at context-assembly time

`analysis/context_builder.py` — every loader returning suggestion/outcome/finding records (`load_active_suggestions`, `load_outcome_measurements`, `load_failure_log`, `load_rejected_suggestions`, `load_discoveries`, `load_outcome_reasonings`) gets a filter:
```python
records = [r for r in records if not r.get("strategy_id") or self._registry.is_active(r["strategy_id"])]
```
Records with no `strategy_id` (legacy or genuinely bot-wide) pass through. Records pinned to a retired strategy are silently dropped from prompts.

### 3c. Weekly archive sweep — `skills/archive_retired_strategies.py` (new)

Scheduled weekly (same window as `MemoryConsolidator` / `AutoOutcomeMeasurer`):
- For each JSONL under `memory/findings/`, partition records into the active file (rewrite in place) vs. `archive/<YYYY-MM-DD>.jsonl` (append-only).
- Records with no `strategy_id` always stay active.
- Pure move; never delete. Forensic history preserved.

### 3d. Validator block for inactive strategies

`analysis/response_validator.py` — when validating an `AgentSuggestion` whose `strategy_id` is set but not in the active registry, strip it with a "Validator Notes" entry: `"Suggestion targets retired strategy '<id>' — ignored."` Same plumbing as the existing rejected-suggestion block.

**Files modified:** `schemas/strategy_profile.py`, `analysis/context_builder.py`, `analysis/response_validator.py`, `skills/archive_retired_strategies.py` (new), `orchestrator/app.py` (schedule the archive job).

---

## Critical files (modify, don't recreate)

- `data/strategy_profiles.yaml` — targeted edits per Phase 1a table (3 confirmed removals, 2 confirmed adds, conditional S5 reconciliation, re-validate 7 surviving entries)
- `schemas/strategy_profile.py` — enum extension if needed + `is_active()`
- `schemas/agent_response.py`, `schemas/suggestion_tracking.py`, `schemas/prediction_tracking.py`, `schemas/suggestion_scoring.py`, `schemas/transfer_proposals.py`, `schemas/forecast_tracking.py` — add `strategy_id` (Optional)
- `analysis/context_builder.py` — strategy-aware filtering + per-strategy scorecard rendering
- `analysis/response_validator.py` — block suggestions for inactive strategies
- `analysis/daily_prompt_assembler.py`, `analysis/weekly_prompt_assembler.py` — instruct Claude to emit `strategy_id`
- `orchestrator/handlers.py` — `_record_suggestions` (line 2886) preserves `strategy_id` from `StrategySuggestion`; `_record_agent_suggestions` (line 3015) reads `strategy_id` off `AgentSuggestion`; daily handler calls drift checker
- `skills/suggestion_scorer.py` — emit per-strategy stratified rows alongside existing aggregates
- `skills/forecast_tracker.py`, `skills/prediction_tracker.py` — propagate `strategy_id` and add per-strategy accuracy

## New files

- `skills/strategy_registry_drift.py` (drift checker, daily)
- `skills/archive_retired_strategies.py` (weekly archive sweep)

## Verification

1. **`pytest tests/`** — all 3154 tests must still pass. Expect to update fixtures that build `SuggestionRecord` / `PredictionRecord` (passing `strategy_id=None` keeps them green). Add tests under `tests/test_strategy_aware_integration.py` for: per-strategy scorecard emission, validator block on retired strategy, drift checker against synthetic empty-dir case (must classify `breakout/`-style empty dirs as **dead**, not registered), archive sweep partitioning.
2. **YAML reload** — after editing `data/strategy_profiles.yaml`, `python -c "from orchestrator.strategy_registry_loader import load_strategy_registry; r = load_strategy_registry(); print(sorted(r.strategies))"`. Confirm the active set matches the live `_references/trading/strategies/` directory listing.
3. **Drift checker E2E** — temporarily make `_references/trading/strategies/swing/atrss/` empty; run the drift checker. Confirm it reports `atrss` as a removed strategy. Restore.
4. **Per-strategy scorecard E2E** — write a synthetic `outcomes.jsonl` with two strategies (one positive, one negative) under `swing_multi_01`. Run `SuggestionScorer.compute_scorecard()`. Confirm two strategy-stratified rows in addition to the bot-aggregate row.
5. **End-to-end prompt** — `python -m orchestrator.scheduler --run-now daily_report` against curated data; confirm `parsed_analysis.json` includes `strategy_id` on every suggestion/prediction and that "Validator Notes" cites strategy-specific track records.
6. **Archive sweep E2E** — drop a record with `strategy_id="breakout_v3"` (now-retired) into `memory/findings/suggestions.jsonl`, run the sweep, confirm it lands in `memory/findings/archive/<date>.jsonl` and is no longer surfaced by `ContextBuilder.load_active_suggestions()`.

## Out of scope (intentional)

- **Deferred futures research family** — deferred per user direction.
- **`k_stock_trader` / `crypto_trader` YAML entries** — these bots have their own reference repos (`_references/k_stock_trader/`, `_references/crypto_trader/`). Drift against those is a separate effort; the plan does NOT delete or modify them based on absence from `_references/trading/`. Drift checker is built to accept additional reference roots later.
- **No automatic strategy discovery from `_references/` at runtime** — explicit user choice.
- **No re-keying of `HypothesisRecord`** — hypotheses are intentionally cross-strategy.
- **No backfill of `strategy_id` on legacy JSONL records** — `Optional[str] = None` makes this unnecessary.
- **No bot-side instrumentation changes** — those belong in the bot repos.

## Major corrections from earlier drafts (acknowledging error)

The first two drafts of this plan contained several factual errors. Corrected here:

- **WRONG**: claimed `brs`, `keltner`, `overlay`, `tpc` were all newly-added swing strategies. **CORRECT**: `brs`, `keltner`, and `breakout` are *deleted* (empty dirs); `overlay` was already there; `tpc` is the only genuinely new swing strategy.
- **WRONG**: claimed `helix_v40` momentum strategy was alive. **CORRECT**: `helix_v40/` is now an empty dir — deleted in `c412a8d`. The "AKC Helix Multi-TF Momentum v40" YAML entry must be removed.
- **WRONG**: claimed `crypto_trader` entries should be retired based on absence from `_references/trading/`. **CORRECT**: `_references/crypto_trader/` is a separate repo; absence from the trading monorepo says nothing about crypto bot status.
- **WRONG**: claimed `HypothesisRecord` has a `proposed_for_strategies` field. **CORRECT**: it doesn't; hypotheses are category-keyed by design.
- **WRONG**: claimed regime taxonomy is `bull`/`bear`/`chop`. **CORRECT**: it's `trending_up`/`trending_down`/`ranging`/`volatile`/`compression` plus macro `G`/`R`/`S`/`D`.
- **MISSED**: that `StrategySuggestion` (`schemas/strategy_suggestions.py:33-34`) already carries `strategy_id` + `strategy_archetype`, and the bug is purely that `_record_suggestions` (`orchestrator/handlers.py:2886+`) drops them on the floor when writing `SuggestionRecord`. This is the single highest-leverage fix in Phase 2.
