# Portfolio-Level Instrumentation Gaps — TA Pipeline Report

> **Date:** 2026-03-21
> **Scope:** Changes needed in the Trading Assistant (TA) pipeline to consume portfolio-level data from live trading instrumentation and produce actionable portfolio optimization insights.

---

## 1. Current State

The TA already has significant portfolio-level infrastructure:

### Curated Data (22 files loaded by prompt assembler)
- Per-bot daily summaries (`BotDailySummary`) with net PnL, fees, drawdown, exposure, trade count
- `portfolio_risk_card.json` — daily cross-bot snapshot with exposure by symbol/direction, concentration score, crowding alerts
- `coordinator_impact.json` — strategy coordinator rule enforcement outcomes
- `parameter_changes.json` — parameter modifications with before/after values
- Per-bot signal health, filter effectiveness, and process quality scores

### Weekly Analysis
- `_build_bot_correlation_summaries()` in `handlers.py` computes pairwise bot correlation via `synergy.compute_bot_correlation_matrix()`
- `allocator.compute()` produces risk-parity allocation recommendations using Calmar ratio tilt
- Pattern library tracks `correlation_crowding` as a `COORDINATION` pattern category

### Risk Infrastructure
- `PortfolioRiskComputer` (in `skills/compute_portfolio_risk.py`) computes daily risk cards
- `PortfolioRiskCard` schema has fields: `total_exposure_pct`, `exposure_by_symbol`, `exposure_by_direction`, `correlation_matrix`, `concentration_score`, `crowding_alerts`
- `PortfolioRuleChecker` (in `libs/oms/risk/portfolio_rules.py`) enforces cross-strategy rules for momentum and stock families
- Crowding alert thresholds: HHI > 0.4 or correlation > 0.7

---

## 2. Gap Analysis

### Gap 1: Portfolio Rules Summary

**What's missing:** The `PortfolioRuleChecker` emits `portfolio_rule_check` events to the OMS event bus when rules trigger (directional cap reached, symbol collision detected, max positions hit). These events are written to JSONL but the TA pipeline never reads them.

**Why it matters:** The TA can't see how often portfolio rules are constraining strategies. A strategy that's frequently capped by the 8R directional limit may need its allocation reduced, but the TA has no visibility into this.

**JSON schema for curated output:**
```json
// curated/{date}/portfolio_rules_summary.json
{
  "date": "2026-03-21",
  "total_checks": 142,
  "total_blocks": 7,
  "blocks_by_rule": {
    "directional_exposure_cap": 3,
    "symbol_collision": 2,
    "max_positions": 1,
    "max_positions_per_sector": 1
  },
  "blocks_by_strategy": {
    "IARIC_v1": 3,
    "ALCB_v1": 2,
    "AKC_Helix_v40": 2
  },
  "blocked_symbols": ["AAPL", "NVDA", "NQ"],
  "directional_exposure_at_block": {
    "LONG": 6.8,
    "SHORT": 2.1
  }
}
```

**Files to modify:**
- `handlers.py` → `_rebuild_daily_curated_from_raw()`: Add a pass to scan `portfolio_rule_check` events from the raw JSONL directory, aggregate by rule type and strategy
- `prompt_assembler.py`: Add `portfolio_rules_summary.json` to curated file list

---

### Gap 2: Family-Level Daily Snapshots

**What's missing:** `BotDailySummary` is per-bot. There's no aggregation to the family level (swing/momentum/stock). The TA sees 11 individual bots but can't easily compare family-level performance.

**Why it matters:** Portfolio allocation decisions happen at the family level. The weekly analysis computes bot correlation but lacks family-level metrics like "swing family Sharpe this week" or "momentum family is in drawdown while stock family is at equity highs."

**JSON schema for curated output:**
```json
// curated/{date}/family_daily_summary.json
{
  "date": "2026-03-21",
  "families": {
    "swing": {
      "strategy_ids": ["ATRSS", "AKC_HELIX", "SWING_BREAKOUT_V3", "S5_PB", "S5_DUAL"],
      "total_net_pnl": 342.50,
      "total_fees": 12.80,
      "trade_count": 8,
      "win_count": 5,
      "loss_count": 3,
      "max_drawdown_pct": 1.2,
      "avg_exposure_pct": 45.0,
      "active_strategies": 4
    },
    "momentum": {
      "strategy_ids": ["AKC_Helix_v40", "NQDTC_v2.1", "VdubusNQ_v4"],
      "total_net_pnl": -125.00,
      "total_fees": 8.40,
      "trade_count": 12,
      "win_count": 4,
      "loss_count": 8,
      "max_drawdown_pct": 3.5,
      "avg_exposure_pct": 60.0,
      "active_strategies": 3
    },
    "stock": {
      "strategy_ids": ["IARIC_v1", "US_ORB_v1", "ALCB_v1"],
      "total_net_pnl": 89.20,
      "total_fees": 4.10,
      "trade_count": 5,
      "win_count": 3,
      "loss_count": 2,
      "max_drawdown_pct": 0.8,
      "avg_exposure_pct": 30.0,
      "active_strategies": 2
    }
  },
  "portfolio_total_pnl": 306.70,
  "portfolio_total_fees": 25.30
}
```

**Files to modify:**
- `handlers.py` → `_rebuild_daily_curated_from_raw()`: After per-bot loop, group `BotDailySummary` by family (using strategy → family mapping from `config/strategies.yaml`), aggregate PnL/fees/trade counts
- `schemas/daily_metrics.py`: Add `FamilyDailySummary` Pydantic model
- `prompt_assembler.py`: Add `family_daily_summary.json` to curated file list

---

### Gap 3: Portfolio-Level Sharpe/Sortino/Calmar

**What's missing:** Per-bot rolling Sharpe exists but there's no portfolio-level risk-adjusted return metric. The weekly allocator uses Calmar ratio for tilt, but this is computed ad-hoc during weekly analysis — not persisted or tracked over time.

**Why it matters:** Portfolio-level Sharpe/Sortino/Calmar trending down is an early warning that diversification is failing. The TA needs this to make allocation suggestions with conviction.

**JSON schema for curated output:**
```json
// curated/weekly/{week_start}/portfolio_risk_metrics.json
{
  "week_start": "2026-03-17",
  "portfolio": {
    "rolling_sharpe_20d": 1.45,
    "rolling_sortino_20d": 2.10,
    "rolling_calmar_90d": 3.20,
    "max_drawdown_pct_20d": 2.8,
    "daily_vol_annualized": 12.5
  },
  "by_family": {
    "swing": {"rolling_sharpe_20d": 1.8, "rolling_sortino_20d": 2.5, "rolling_calmar_90d": 4.1},
    "momentum": {"rolling_sharpe_20d": 0.9, "rolling_sortino_20d": 1.2, "rolling_calmar_90d": 1.8},
    "stock": {"rolling_sharpe_20d": 1.6, "rolling_sortino_20d": 2.0, "rolling_calmar_90d": 3.5}
  },
  "trend": {
    "sharpe_5w_ago": 1.65,
    "sharpe_direction": "declining"
  }
}
```

**Files to modify:**
- `skills/compute_portfolio_risk.py` → `PortfolioRiskComputer`: Add `compute_risk_adjusted_metrics()` method that loads 20 trading days of `BotDailySummary` from curated dir and computes portfolio-level Sharpe, Sortino, and Calmar
- `handlers.py` → `handle_weekly_analysis()`: Call the new method and persist to `weekly/{week_start}/portfolio_risk_metrics.json`
- `schemas/portfolio_risk.py`: Add `PortfolioRiskMetrics` Pydantic model

---

### Gap 4: Populate `correlation_matrix` on PortfolioRiskCard

**What's missing:** The `PortfolioRiskCard` schema has `correlation_matrix: dict[str, float] = {}` but `PortfolioRiskComputer.compute()` never populates it. The field is always empty `{}`.

**Why it matters:** Daily pairwise bot correlation is the foundation for crowding detection. Without it, the `high_correlation` crowding alert type can never fire — the TA only sees correlation at the weekly level via `synergy.compute_bot_correlation_matrix()`.

**JSON schema (already defined, just needs populating):**
```json
{
  "correlation_matrix": {
    "ATRSS_AKC_HELIX": 0.72,
    "ATRSS_SWING_BREAKOUT_V3": 0.31,
    "AKC_Helix_v40_NQDTC_v2.1": 0.85,
    "IARIC_v1_US_ORB_v1": 0.45
  }
}
```

**Files to modify:**
- `skills/compute_portfolio_risk.py` → `PortfolioRiskComputer.compute()`: After computing exposure, load last 20 days of per-bot daily PnL from curated dir, compute pairwise Pearson correlation, populate `correlation_matrix` field. Add `high_correlation` crowding alert when any pair exceeds threshold (0.7).
- No schema changes needed — field already exists on `PortfolioRiskCard`.

---

### Gap 5: Consume `correlated_pairs_detail` from Live-Side

**What's missing:** Live trade loggers now populate `correlated_pairs_detail` (implemented in this PR). But the TA pipeline doesn't read or aggregate this field. Trade events with `correlated_pairs_detail` are ingested but the data is dropped during `_rebuild_daily_curated_from_raw()`.

**Why it matters:** This field records exactly which sibling strategies held positions at the moment of a new entry. Aggregating this data reveals structural overlap patterns: "Every time ATRSS enters QQQ LONG, AKC_HELIX already holds QQQ LONG" — a crowding pattern the TA should flag.

**JSON schema for curated output:**
```json
// curated/{date}/concurrent_position_analysis.json
{
  "date": "2026-03-21",
  "total_entries_with_siblings": 6,
  "same_symbol_entries": 2,
  "overlap_pairs": [
    {
      "entering_strategy": "AKC_HELIX",
      "entering_symbol": "QQQ",
      "entering_direction": "LONG",
      "siblings_at_entry": [
        {"strategy_id": "ATRSS", "symbol": "QQQ", "direction": "LONG", "same_symbol": true}
      ]
    }
  ],
  "same_symbol_frequency": {
    "QQQ": {"count": 2, "strategies": ["ATRSS", "AKC_HELIX", "S5_PB"]},
    "NQ": {"count": 1, "strategies": ["AKC_Helix_v40", "NQDTC_v2.1"]}
  }
}
```

**Files to modify:**
- `handlers.py` → `_rebuild_daily_curated_from_raw()`: During trade event ingestion, extract `correlated_pairs_detail` fields, aggregate into overlap frequency tables, write `concurrent_position_analysis.json`
- `prompt_assembler.py`: Add `concurrent_position_analysis.json` to curated file list

---

### Gap 6: Drawdown Correlation Analysis

**What's missing:** Each bot has its own drawdown tracker, but there's no analysis of whether drawdowns are correlated across bots/families. Multiple bots drawing down simultaneously is a systemic risk event.

**Why it matters:** If swing and momentum families both draw down at the same time, the portfolio is experiencing a correlated shock. The TA should flag this for emergency allocation review.

**JSON schema for curated output:**
```json
// curated/weekly/{week_start}/drawdown_correlation.json
{
  "week_start": "2026-03-17",
  "simultaneous_drawdown_days": 2,
  "worst_portfolio_drawdown_pct": 4.2,
  "systemic_risk_score": 65,
  "family_drawdown_overlap": {
    "swing_momentum": {"overlap_days": 2, "correlation": 0.78},
    "swing_stock": {"overlap_days": 0, "correlation": -0.12},
    "momentum_stock": {"overlap_days": 1, "correlation": 0.35}
  },
  "recovery_divergence": {
    "fastest_family": "stock",
    "slowest_family": "momentum",
    "divergence_days": 3
  }
}
```

**Files to modify:**
- `skills/compute_portfolio_risk.py`: Add `compute_drawdown_correlation()` method that loads daily drawdown series per family from curated BotDailySummary data, computes rolling overlap and correlation
- `handlers.py` → `handle_weekly_analysis()`: Call `compute_drawdown_correlation()`, persist result
- `schemas/portfolio_risk.py`: Add `DrawdownCorrelation` Pydantic model

---

### Gap 7: Sector Exposure Aggregation

**What's missing:** Stock family trades now include `sector` and `industry` metadata (implemented in this PR via `config/sector_map.yaml`). But the TA pipeline doesn't aggregate this into a sector exposure view.

**Why it matters:** Three stock strategies independently trading AAPL, NVDA, and AMD creates 3x Technology sector exposure. The TA needs sector-level aggregation to detect concentration risk that's invisible at the symbol level.

**JSON schema for curated output:**
```json
// curated/{date}/sector_exposure.json
{
  "date": "2026-03-21",
  "sector_exposure": {
    "Technology": {
      "total_exposure_pct": 45.0,
      "position_count": 4,
      "symbols": ["AAPL", "NVDA", "AMD", "MSFT"],
      "strategies": ["IARIC_v1", "US_ORB_v1", "ALCB_v1"],
      "net_direction": "LONG",
      "long_pct": 40.0,
      "short_pct": 5.0
    },
    "Financial Services": {
      "total_exposure_pct": 15.0,
      "position_count": 1,
      "symbols": ["JPM"],
      "strategies": ["IARIC_v1"],
      "net_direction": "LONG",
      "long_pct": 15.0,
      "short_pct": 0.0
    }
  },
  "concentration_alerts": [
    {
      "sector": "Technology",
      "exposure_pct": 45.0,
      "threshold_pct": 40.0,
      "severity": "high"
    }
  ],
  "hhi_by_sector": 0.38
}
```

**Files to modify:**
- `handlers.py` → `_rebuild_daily_curated_from_raw()`: During stock trade event ingestion, extract `sector`/`industry` fields, aggregate exposure by sector. Build sector concentration alerts (threshold: any single sector > 40% of stock family exposure).
- `skills/compute_portfolio_risk.py` → `PortfolioRiskComputer`: Accept optional sector exposure data, add sector-level crowding alerts to `PortfolioRiskCard.crowding_alerts`
- `schemas/portfolio_risk.py`: Add `SectorExposure` Pydantic model
- `prompt_assembler.py`: Add `sector_exposure.json` to curated file list

---

## 3. Architecture Notes

### OMS Topology (affects data collection)
| Family | OMS Model | Position Source | PortfolioRuleChecker |
|--------|-----------|-----------------|---------------------|
| Swing | Shared (client_id=7) | StrategyCoordinator in-process | No (uses StrategyCoordinator directly) |
| Momentum | Separate per-strategy (11/12/13) | `positions` table via pg_store | Yes (8R directional cap) |
| Stock | Separate per-strategy (31/32/34) | `positions` table via pg_store | Yes (8R directional cap + symbol collision) |

### Portfolio Rule Event Format
Rules emit events on the OMS event bus:
```python
{
    "event_type": "portfolio_rule_check",
    "strategy_id": "IARIC_v1",
    "rule_name": "directional_exposure_cap",
    "action": "block",  # or "allow" or "half_size"
    "symbol": "AAPL",
    "direction": "LONG",
    "current_exposure_r": 7.2,
    "cap_r": 8.0,
    "timestamp": "2026-03-21T14:30:00Z"
}
```

### Data Flow
```
Live Trading → JSONL (raw) → _rebuild_daily_curated_from_raw() → curated/{date}/ → prompt_assembler → TA prompt
                                    ↓
                            PortfolioRiskComputer → portfolio_risk_card.json
                                    ↓
                            Weekly: synergy + allocator → allocation recommendations
```

### Strategy IDs by Family
- **Swing (5):** ATRSS, AKC_HELIX, SWING_BREAKOUT_V3, S5_PB, S5_DUAL
- **Momentum (3):** AKC_Helix_v40, NQDTC_v2.1, VdubusNQ_v4
- **Stock (3):** IARIC_v1, US_ORB_v1, ALCB_v1

---

## 4. Implementation Priority

| # | Gap | Effort | Impact | Priority |
|---|-----|--------|--------|----------|
| 4 | Populate `correlation_matrix` on PortfolioRiskCard | Low | High | P0 — field exists, just needs computation |
| 1 | Portfolio rules summary | Low | High | P0 — data already in JSONL |
| 5 | Consume `correlated_pairs_detail` | Medium | High | P1 — live-side now emitting |
| 7 | Sector exposure aggregation | Medium | High | P1 — live-side now emitting |
| 2 | Family-level daily snapshots | Low | Medium | P1 — pure aggregation |
| 3 | Portfolio-level Sharpe/Sortino/Calmar | Medium | Medium | P2 — requires historical load |
| 6 | Drawdown correlation analysis | Medium | Medium | P2 — requires multi-day window |
