# Strategy Instrumentation Gaps

**Target repos:** `swing_trader`, `momentum_trader`, `stock_trader` (deployed on VPSes)
**Consuming repo:** `trading_assistant` (this repo)

This document defines the sidecar emission changes needed in each bot repo to
close instrumentation gaps for BRS, Downturn, ALCB, and IARIC. Changes are
ordered by priority — P0 unblocks quality-adjusted learning, P1–P3 enable
progressively deeper analysis.

## Current State

All four strategies emit `TradeEvent` via sidecar with the common fields:

```json
{
  "event_id": "a1b2c3d4e5f6g7h8",
  "bot_id": "swing_multi_01",
  "exchange_timestamp": "2026-04-01T14:30:00Z",
  "entry_price": 445.20,
  "exit_price": 448.50,
  "side": "LONG",
  "exit_reason": "CHANDELIER",
  "mfe_r": 2.1,
  "mae_r": -0.4,
  "regime_at_entry": "BEAR_TREND"
}
```

The following fields are missing or not wired to sidecar emission:

| Field | Description | BRS | Downturn | ALCB | IARIC |
|-------|-------------|-----|----------|------|-------|
| `process_quality_score` | 0–100 execution quality | computed, not emitted | computed, not emitted | emitted | emitted |
| `root_causes` | Controlled taxonomy list | computed, not emitted | computed, not emitted | emitted | emitted |
| `filter_decisions` | Per-filter pass/fail log | not emitted | not emitted | not emitted | not emitted |
| `MissedOpportunityEvent` | Blocked signals with outcomes | not implemented | not implemented | backtest-only | backtest-only |

## P0: Wire Process Quality + Root Causes (BRS, Downturn)

**Effort:** Low — scores already computed internally, need sidecar wiring only.
**Unblocks:** Quality-adjusted outcome measurement in `skills/suggestion_validator.py`.

### 1. `swing_trader` — Wire BRS process quality to sidecar

**Target file:** sidecar event builder (where `TradeEvent` dict is constructed)

Process scoring rules already exist in `instrumentation/config/process_scoring_rules.yaml`
under key `BRS_R9`. The `quality_score` is computed at entry. Add to the sidecar
emission dict:

```python
event["process_quality_score"] = signal.quality_score  # already computed
event["root_causes"] = classify_root_causes(trade)     # use existing taxonomy
```

### 2. `momentum_trader` — Wire Downturn process quality to sidecar

**Target file:** sidecar event builder for Downturn engine

Process scoring rules exist in `instrumentation/config/process_scoring_rules.yaml`
under key `downturn`. Add to the sidecar emission dict:

```python
event["process_quality_score"] = engine.compute_quality(trade)
event["root_causes"] = classify_root_causes(trade)
```

### Expected event after P0

```json
{
  "event_id": "a1b2c3d4e5f6g7h8",
  "bot_id": "swing_multi_01",
  "strategy_id": "BRS_R9",
  "process_quality_score": 72,
  "root_causes": ["regime_aligned", "late_entry"],
  "...": "..."
}
```

### Testing

1. **BRS emits quality** — trigger a BRS trade in backtest mode, verify `process_quality_score` in sidecar JSONL
2. **Downturn emits quality** — same for Downturn engine
3. **Root cause taxonomy** — verify emitted values are in the controlled taxonomy (`schemas/process_quality.py`)
4. **Score range** — verify `process_quality_score` is 0–100

## P1: MissedOpportunityEvent with Filter Decisions (All 4)

**Effort:** Medium — requires shadow tracking infrastructure in live engines.
**Unblocks:** Filter effectiveness analysis in `analysis/strategy_engine.py` detectors,
opportunity cost measurement in weekly prompts.

### 1. `swing_trader` — BRS shadow tracker

**Target file:** BRS signal evaluation loop

When a signal is blocked by a filter, emit a `MissedOpportunityEvent` instead of
silently discarding:

```python
if not filter_result.passed:
    emit_missed_opportunity(
        strategy_id="BRS_R9",
        signal=signal,
        filter_decisions={f.name: f.passed for f in filter_result.filters},
        # backfill hypothetical outcome after bar closes
        hypothetical_outcome_r=None,  # filled by end-of-bar callback
    )
```

### 2. `momentum_trader` — Downturn shadow tracker

Same pattern for Downturn's three engines. Each blocked signal should include
`engine_tag` so the trading assistant can compute per-engine filter blocking rates.

### 3. `stock_trader` — ALCB + IARIC filter decisions

Both strategies have filters in live mode. Emit `filter_decisions` dict on every
`TradeEvent` (not just blocked signals):

```python
event["filter_decisions"] = {
    "gate_1_market_regime": True,
    "gate_2_volume_threshold": True,
    "gate_7_correlation_cap": False,  # blocked here
    "...": "..."
}
```

### Expected MissedOpportunityEvent

```json
{
  "event_type": "MissedOpportunityEvent",
  "bot_id": "swing_multi_01",
  "strategy_id": "BRS_R9",
  "signal_timestamp": "2026-04-01T14:30:00Z",
  "entry_type": "S2_BREAKDOWN",
  "filter_decisions": {
    "regime_filter": false,
    "adx_minimum": true,
    "di_agreement": true
  },
  "hypothetical_entry_price": 445.20,
  "hypothetical_outcome_r": 1.8
}
```

### Testing

1. **Blocked signal emits event** — block a signal via filter, verify `MissedOpportunityEvent` in JSONL
2. **Filter decisions complete** — verify all active filters appear in `filter_decisions` dict
3. **Hypothetical backfill** — verify `hypothetical_outcome_r` is populated after bar close
4. **No emission for passed signals** — signals that pass all filters should NOT emit `MissedOpportunityEvent`

## P2: Per-Component Breakdown (IARIC, ALCB)

**Effort:** Medium — data exists internally, needs structured emission.
**Unblocks:** Factor attribution in weekly analysis, gate-level optimization proposals.

### 1. `stock_trader` — IARIC conviction factor decomposition

**Currently emits:** `conviction_multiplier` (single aggregated float).
**Needed:** Individual factor values for the 6 components.

Add to sidecar emission:

```python
event["conviction_factors"] = {
    "rsi2_depth": 0.85,
    "volume_confirmation": 0.60,
    "sponsorship_score": 0.90,
    "sector_momentum": 0.45,
    "daily_rank_pct": 0.75,
    "flow_pressure": 0.30,
}
```

### 2. `stock_trader` — ALCB per-gate decision log

**Currently emits:** final pass/fail only.
**Needed:** Per-gate pass/fail for the 15-gate funnel.

Add to sidecar emission:

```python
event["gate_decisions"] = {
    "gate_01_market_open": True,
    "gate_02_volume_min": True,
    "gate_03_spread_max": True,
    # ... all 15 gates
    "gate_15_position_limit": True,
}
```

### Testing

1. **IARIC factors sum** — verify individual factors are consistent with aggregated `conviction_multiplier`
2. **ALCB gate count** — verify exactly 15 gates in `gate_decisions`
3. **Gate order preserved** — verify gates are numbered sequentially

## P3: Per-Engine DailySnapshot Tagging (Downturn)

**Effort:** Low — groupby on `engine_tag` in snapshot builder.
**Unblocks:** Engine comparison at aggregate level in `analysis/weekly_prompt_assembler.py`.

### `momentum_trader` — Downturn snapshot builder

**Target file:** daily snapshot aggregation logic

Add per-engine breakdown to `DailySnapshot`:

```python
snapshot["per_engine_stats"] = {
    "REVERSAL": {"trades": 3, "pnl": 450.0, "win_rate": 0.67},
    "BREAKDOWN": {"trades": 2, "pnl": -120.0, "win_rate": 0.00},
    "FADE": {"trades": 1, "pnl": 80.0, "win_rate": 1.00},
}
```

### Testing

1. **Engine stats present** — verify `per_engine_stats` in snapshot when Downturn trades exist
2. **Engine totals match** — verify sum of per-engine trades/pnl equals overall Downturn totals
3. **Empty engines omitted** — engines with zero trades should not appear

## P0-Regime: DailySnapshot Macro Regime Enrichment

**Effort:** Trivial — both values already held in memory, just serialize to snapshot dict.
**Unblocks:** All macro regime analysis in trading assistant (config effectiveness, transition cost, stress entry patterns).

### All three family bots — Attach RegimeContext to DailySnapshot

**Target file:** Daily snapshot emission logic (where `DailySnapshot` dict is constructed)

Both `RegimeContext` (from `RegimeService.get_current()`) and the applied portfolio config
(from `PortfolioRulesConfig`) are already in memory at snapshot time. Add to emission:

```python
snapshot["regime_context"] = {
    "macro_regime": regime_ctx.regime,          # G/R/S/D
    "regime_confidence": regime_ctx.confidence,  # 0-1
    "stress_level": regime_ctx.stress_level,     # 0-1 P(stress)
    "stress_onset": regime_ctx.stress_onset,     # bool
    "shift_velocity": regime_ctx.shift_velocity,
    "suggested_leverage_mult": regime_ctx.suggested_leverage_mult,
    "computed_at": regime_ctx.computed_at.isoformat(),
}
snapshot["applied_regime_config"] = {
    "directional_cap_R": rules.directional_cap_R,
    "regime_unit_risk_mult": rules.regime_unit_risk_mult,
    "disabled_strategies": rules.disabled_strategies,
    # family-specific (momentum only):
    "directional_cap_long_R": getattr(rules, "directional_cap_long_R", None),
    "directional_cap_short_R": getattr(rules, "directional_cap_short_R", None),
    "nqdtc_oppose_size_mult": getattr(rules, "nqdtc_oppose_size_mult", None),
    "max_contracts_scale": getattr(rules, "max_contracts_scale", None),
}
```

### Expected DailySnapshot after P0-Regime

```json
{
  "date": "2026-04-06",
  "bot_id": "momentum_nq_01",
  "total_trades": 8,
  "regime_context": {
    "macro_regime": "S",
    "regime_confidence": 0.82,
    "stress_level": 0.65,
    "stress_onset": false,
    "shift_velocity": 0.12,
    "suggested_leverage_mult": 0.7,
    "computed_at": "2026-04-04T21:00:00Z"
  },
  "applied_regime_config": {
    "directional_cap_R": 4.0,
    "regime_unit_risk_mult": 0.7,
    "disabled_strategies": ["DOWNTURN"],
    "directional_cap_long_R": 3.0,
    "directional_cap_short_R": 5.0,
    "nqdtc_oppose_size_mult": 0.3,
    "max_contracts_scale": 0.8
  },
  "...": "..."
}
```

### Testing

1. **RegimeContext present** — trigger DailySnapshot, verify `regime_context` dict in JSONL
2. **Applied config present** — verify `applied_regime_config` has correct active values
3. **Staleness detection** — verify `computed_at` is recent (within 7 days of snapshot date)
4. **Missing regime graceful** — if regime module unavailable, both fields should be `null`

## P1-Regime: TradeEvent Macro Regime Context

**Effort:** Trivial — cached values from weekly RegimeContext, no computation at trade time.
**Unblocks:** Per-trade macro regime correlation (stress entry patterns, regime-stratified outcomes).

### All three family bots — Add macro fields to TradeEvent

**Target file:** Sidecar event builder (where `TradeEvent` dict is constructed)

```python
event["macro_regime"] = regime_service.current_regime  # G/R/S/D, cached
event["stress_level_at_entry"] = regime_service.current_stress  # 0-1, cached
```

### Expected TradeEvent after P1-Regime

```json
{
  "trade_id": "t_abc123",
  "bot_id": "stock_trader",
  "macro_regime": "S",
  "stress_level_at_entry": 0.65,
  "market_regime": "trending_down",
  "...": "..."
}
```

### Testing

1. **Macro regime populated** — verify non-empty `macro_regime` on trades when regime module active
2. **Stress level range** — verify `stress_level_at_entry` is 0.0–1.0
3. **Distinct from micro regime** — verify `macro_regime` (G/R/S/D) differs from `market_regime` (trending_up, etc.)

## P2-Regime: Regime Transition Event

**Status:** Implemented in `regime/live/service.py` via `_emit_transition()`.
**Effort:** Low — emit when macro regime changes (~every 2.3 years on average).
**Unblocks:** Transition cost measurement, allocation shift auditing.

### Centralized in RegimeService

`RegimeService._compute_signal()` captures `_prev_ctx` before updating, detects
regime change after persist, and writes to `data/regime/transitions.jsonl`:

```python
# regime/live/service.py
if _prev_ctx is not None and _prev_ctx.regime != self._context.regime:
    self._emit_transition(_prev_ctx, self._context)
```

### Expected RegimeTransitionEvent

```json
{
  "event_type": "regime_transition",
  "from_regime": "G",
  "to_regime": "S",
  "regime_confidence": 0.78,
  "stress_level": 0.72,
  "stress_onset": false,
  "shift_velocity": 0.12,
  "timestamp": "2026-04-06T21:00:00Z"
}
```

### Fields NOT included (by design)

- **`shift_predicted`** / **`shift_lead_weeks`**: The HMM is a concurrent
  classifier, not a predictor. Eight optimization rounds confirmed the model cannot
  produce forward-looking signals (historical alignment 0.228, COVID latency 110.9
  weeks). These fields would always be empty.
- **`regime_allocations`** (SPY/EFA/TLT/GLD/IBIT/CASH weights): Model-internal
  theoretical portfolio weights. They validate regime quality during optimization
  (wide allocation spreads prove regimes are distinct) but are not consumed by any
  coordinator or strategy. The actual downstream effect is captured by
  `applied_regime_config` (directional caps, risk mults, disabled strategies).

See `regime-optimization-cross-round-assessment.md` for full evidence.

### Testing

1. **Transition emitted** — simulate regime change, verify event in JSONL
2. **No duplicate** — same regime → same regime should NOT emit

## Compatibility

All changes are additive — existing event fields are unchanged. The trading
assistant already handles missing fields gracefully:

- `process_quality_score`: `TradeEvent` schema defaults to `None`
- `filter_decisions`: curated data pipeline skips if absent
- `MissedOpportunityEvent`: `build_daily_metrics.py` loads `missed.jsonl` only if present
- New nested fields (`conviction_factors`, `gate_decisions`, `per_engine_stats`):
  flow through as opaque dicts in `TradeEvent.metadata` — no schema changes needed
  in trading_assistant until P2/P3 are implemented
- `regime_context` / `applied_regime_config`: `DailySnapshot` schema defaults to `None`;
  `build_macro_regime_analysis()` returns empty dict when absent; context builder and
  prompt assemblers skip regime sections when no data present
- `macro_regime` / `stress_level_at_entry` on `TradeEvent`: default to `""` / `0.0`;
  strategy engine stress detectors require minimum trade counts before firing
- `RegimeTransitionEvent`: consumed only when present; transition cost detector
  returns empty list if no events provided

## Regime Field Reliability Guide

The regime HMM is a **concurrent classifier, not a predictor**. Instrumentation fields are categorized by signal reliability to guide downstream consumers.

### HIGH confidence — use for config mutations and analysis

| Field | Where | Reliability | Notes |
|-------|-------|-------------|-------|
| `regime` / `macro_regime` | TradeEvent, DailySnapshot, TransitionEvent | Strong | Core classification (G/R/S/D). Near-binary posteriors (0.993-1.000). ~122-week regime spells. Maps to Tier 1/Tier 2 config mutations. |
| `regime_confidence` | DailySnapshot, TransitionEvent | Strong | Near-binary with R8/R9. Useful for conviction gating. |
| `applied_regime_config` | DailySnapshot | Strong | Records what the regime system actually DID (directional caps, disabled strategies, risk mult, DD tiers). Essential for auditing config effectiveness. |

### OBSERVATIONAL — record for diagnostics, do not use for active decisions

| Field | Where | Reliability | Notes |
|-------|-------|-------------|-------|
| `stress_level` / `stress_level_at_entry` | TradeEvent, DailySnapshot, TransitionEvent | Low (41% FPR) | P(stress) from stress HMM. Cannot discriminate stress from normal volatility. Record for post-hoc analysis only. |
| `stress_onset` | DailySnapshot, TransitionEvent | Low | Fires during bull markets. Not reliable as defensive trigger. |
| `shift_velocity` | DailySnapshot, TransitionEvent | Low | Derivative of noisy stress_level. Transition momentum had wrong sign during 3 of 4 crises. |
| `suggested_leverage_mult` | DailySnapshot | Negligible | Only 5% max impact on sizing. Dominated by Tier 1 config mutations. |

### NOT instrumented (by design)

| Field | Why excluded |
|-------|-------------|
| `shift_predicted` | Model cannot predict shifts. HMM computes P(state\|observations_up_to_now), not P(future_state). Confirmed across 8 rounds, 3 architectures. |
| `shift_lead_weeks` | No forward-looking signal exists. COVID detection latency: 110.9 weeks. 2022 inflation: 90.9 weeks. |
| `regime_allocations` | Model-internal theoretical portfolio weights (SPY/EFA/TLT/GLD/IBIT/CASH). Validate regime quality during optimization but not consumed downstream. Actual downstream effect captured by `applied_regime_config`. |
| Per-bar regime signals | Weekly signal barely changes day-to-day with near-binary posteriors. Daily refresh adds no value. |

### Implementation Status

| Tier | Items | Status |
|------|-------|--------|
| P0: process_quality_score + root_causes | BRS, Downturn, ALCB, IARIC | All 4 implemented |
| P1: MissedOpportunityEvent | All 4 strategies | All 4 implemented |
| P1: filter_decisions | BRS (4 gates), ALCB (23 gates), momentum, stock | All implemented |
| P2: IARIC conviction_factors | IARIC | Implemented |
| P2: ALCB per-gate decision log | ALCB (23 gates + gate_decisions summary) | Implemented |
| P3: Downturn per_engine_stats | Downturn | Implemented |
| P0-Regime: DailySnapshot enrichment | All 3 families | Implemented via `RegimeContext.to_snapshot_dict()` |
| P1-Regime: TradeEvent macro fields | All 3 families | Implemented (`macro_regime`, `stress_level_at_entry`) |
| P2-Regime: RegimeTransitionEvent | Centralized in RegimeService | Implemented with allocations, without prediction fields |
