# WFO & Backtesting Across Bots: Shared Infrastructure Architecture

> Historical reference only. Legacy WFO scheduling/dispatch is disabled; monthly
> validation owns material strategy evidence and proposal approval. This document
> remains for migration context around old WFO/backtesting assumptions.

How one generic WFO/backtesting pipeline in `trading_assistant` optimises three
fundamentally different trading strategies in three separate repos.

---

## Overview

The three bots run very different strategies:

| Bot | Market | Strategies | Style |
|-----|--------|------------|-------|
| **k_stock_trader** | KRX (Korean stocks) | KMP (momentum breakout), KPR (VWAP pullback), PCIM (event-driven), OLR/KALCB (daily research + breakout surfaces) | Intraday, LONG only, 155–445 symbols |
| **swing_trader** | US futures/ETF | ATRSS (ATR trend-following pullback), AKC-Helix (mean reversion), Breakout V3, S5_PB/S5_DUAL (Keltner) | Multi-day swing, LONG+SHORT, ~6 symbols |
| **momentum_trader** | NQ/MNQ futures | Helix v4.0 (multi-TF momentum), NQDTC (30-min box-breakout), VdubusNQ (VWAP pullback) | Intraday+swing, NQ-focused |

Despite these differences, they all feed into the same WFO pipeline. The
architecture achieves this through three layers of abstraction:

1. **Universal event schemas** — all bots emit identical `TradeEvent` / `MissedOpportunityEvent` structures
2. **Configuration-driven parameter spaces** — bot-specific params defined in YAML, not code
3. **Generic optimisation code** — WFO runner, backtest simulator, and robustness tester are completely bot-agnostic

---

## Layer 1: Universal Event Schemas

All three bots' instrumentation sidecars emit the same Pydantic event types.
Strategy-specific details live in generic fields, not bot-specific schemas.

### TradeEvent (common across all bots)

```
trade_id, event_metadata (event_id, bot_id, timestamps, trace_id)
pair, side, entry_time, exit_time, entry_price, exit_price
position_size, pnl, pnl_pct, fees_paid
entry_signal, entry_signal_id, entry_signal_strength   ← generic string/float
exit_reason                                             ← generic string
market_regime, regime_context                           ← generic string
active_filters[], passed_filters[], blocked_by          ← generic filter tracking
atr_at_entry, spread_at_entry_bps, volume_24h_at_entry
signal_factors[], filter_decisions[]                    ← structured but generic
```

The key insight: `entry_signal` is just a string — it can be `"PULLBACK"`,
`"VALUE_SURGE"`, `"VWAP_RECLAIM"`, or `"MACD_CROSSOVER"` and the WFO pipeline
doesn't care. Similarly, `market_regime` is just `"trending_up"` / `"ranging"` /
`"volatile"` regardless of how the bot classified it.

### MissedOpportunityEvent (common across all bots)

```
signal, signal_id, signal_strength, signal_time
blocked_by, block_reason                                ← which filter blocked
hypothetical_entry, hypothetical_exit, hypothetical_pnl ← backfilled outcomes
```

Each bot's simulation policy defines how to backfill hypothetical outcomes:

| Bot | Strategy | TP | SL | Max Hold | Fees |
|-----|----------|----|----|----------|------|
| k_stock_trader | KMP | 2.0R | 1.2R | 60 bars (~1h) | 20 bps |
| k_stock_trader | KPR | 2.0R | 1.0R | 50 bars (~50m) | 20 bps |
| k_stock_trader | PCIM | 2.5R | 1.5R | 200 bars (~3.3h) | 20 bps |
| k_stock_trader | OLR/KALCB | strategy-owned | strategy-owned | strategy-owned | 20 bps |
| swing_trader | ATRSS | 2.0R | 1.0R | 200 bars | 2 bps |
| swing_trader | AKC-Helix | 2.5R | 1.5R | 150 bars | 2 bps |
| swing_trader | Breakout V3 | 2.0R | 1.0R | 100 bars | 2 bps |
| swing_trader | S5_PB/DUAL | 1.5R | 1.0R | 80 bars | 2 bps |
| momentum_trader | Helix v4.0 | 1.5R | 1.0R | 200 bars | 1 bps |
| momentum_trader | NQDTC | 1.5R | 1.0R | 200 bars | 1 bps |
| momentum_trader | VdubusNQ | 1.5R | 1.0R | 200 bars | 1 bps |

These simulation policies live in each bot's `instrumentation/config/simulation_policies.yaml`
and are used at the bot side for backfilling missed opportunity outcomes. The
trading assistant never needs to know these details — it just reads the final
`hypothetical_pnl` from the events.

### Data Flow

```
Bot VPS                              Trading Assistant
─────────                            ──────────────────
strategy logic                       data/curated/YYYY-MM-DD/{bot_id}/
    ↓                                    trades.jsonl     ← TradeEvent JSONL
InstrumentationKit                       missed.jsonl     ← MissedOpportunityEvent JSONL
    ↓                                    summary.json     ← DailySnapshot
Sidecar → Relay VPS → /events →         ...
    (JSONL batches)       poll ←     build_daily_metrics.py
```

All three bots produce identical file structures per day. The WFO handler loads
trades by scanning `data/curated/YYYY-MM-DD/{bot_id}/trades.jsonl` across the
date range — no bot-specific loading logic.

---

## Layer 2: Configuration-Driven Parameter Spaces

### WFO Config (for grid search)

Each bot has a YAML file in `data/wfo_configs/{bot_id}.yaml` defining its WFO
parameter space using the generic `ParameterDef` schema:

```python
# schemas/wfo_config.py
class ParameterDef(BaseModel):
    name: str           # e.g., "VWAP_DEPTH_MIN", "daily_mult", "CLASS_M_PB_MIN"
    min_value: float    # lower bound of search
    max_value: float    # upper bound of search
    step: float         # grid discretisation
    current_value: float

    @computed_field
    def grid_values(self) -> list[float]:
        # [min, min+step, min+2*step, ..., max]

class ParameterSpace(BaseModel):
    bot_id: str
    parameters: list[ParameterDef]

    @computed_field
    def total_combinations(self) -> int:
        # product of each parameter's grid_values length
```

The structure is identical across bots. The contents differ:

#### k_stock_trader example params

| Parameter | Current | Min | Max | Step | Strategy |
|-----------|---------|-----|-----|------|----------|
| OR_RANGE_MIN | 1.2% | 0.5% | 3.0% | 0.5% | KMP |
| OR_RANGE_MAX | 5.5% | 3.0% | 8.0% | 0.5% | KMP |
| MIN_SURGE_BASE | 3.0 | 2.0 | 5.0 | 0.5 | KMP |
| VWAP_DEPTH_MIN | 2.0% | 1.0% | 3.0% | 0.5% | KPR |
| VWAP_DEPTH_MAX | 5.0% | 4.0% | 7.0% | 0.5% | KPR |
| PARTIAL_R_TARGET | 1.5R | 1.0R | 2.0R | 0.25R | KPR |
| TRAIL_FACTOR | 0.5 | 0.3 | 0.7 | 0.1 | KPR |
| LEADER_TIER_A_PCT | 60% | 50% | 80% | 5% | OLR |
| ENTRY_VOL_DRYUP_PCT | 60% | 30% | 80% | 10% | OLR |

#### swing_trader example params

| Parameter | Current | Min | Max | Step | Strategy |
|-----------|---------|-----|-----|------|----------|
| daily_mult | 2.2 | 1.5 | 2.8 | 0.1 | ATRSS |
| hourly_mult | 3.0 | 2.0 | 3.5 | 0.1 | ATRSS |
| adx_on | 20 | 18 | 24 | 1 | ATRSS |
| adx_off | 18 | 16 | 22 | 1 | ATRSS |
| daily_ema_fast | 20 | 15 | 25 | 1 | ATRSS |
| daily_ema_slow | 55 | 50 | 60 | 1 | ATRSS |
| base_risk_pct | 1.0% | 0.5% | 2.0% | 0.1% | ATRSS |
| TP1_R | 1.0R | 0.8R | 1.2R | 0.1R | ATRSS |
| TP2_R | 2.0R | 1.5R | 2.5R | 0.1R | ATRSS |
| ADDON_A_R | 1.25R | 1.0R | 1.5R | 0.05R | ATRSS |
| chand_mult | 3.0 | 2.0 | 4.0 | 0.2 | ATRSS |

#### momentum_trader example params

| Parameter | Current | Min | Max | Step | Strategy |
|-----------|---------|-----|-----|------|----------|
| CLASS_M_PB_MIN | 0.2 ATR | 0.1 | 0.4 | 0.05 | Helix |
| CLASS_M_PB_MAX | 1.6 ATR | 1.2 | 2.0 | 0.1 | Helix |
| TRAIL_MULT_MAX | 3.0 | 2.5 | 3.5 | 0.1 | Helix |
| MFE_RATCHET_FLOOR_PCT | 0.65 | 0.50 | 0.80 | 0.05 | Helix |
| PARTIAL1_R | 1.0R | 0.75R | 1.5R | 0.25R | Helix |
| PARTIAL2_R | 1.5R | 1.25R | 2.0R | 0.25R | Helix |
| BASE_RISK_PCT | 1.25% | 1.0% | 1.5% | 0.05% | Helix |
| q_disp | 0.70 | 0.55 | 0.85 | 0.05 | NQDTC |
| k_slope | 0.10 | 0.05 | 0.20 | 0.01 | NQDTC |
| adx_trending | 25 | 20 | 30 | 1 | NQDTC |
| base_risk_pct | 0.30% | 0.20% | 0.50% | 0.05% | NQDTC |

### Bot Config Profile (for autonomous approval pipeline)

A separate schema supports the approval pipeline's need to know where each
parameter lives in the bot's source code:

```python
# schemas/autonomous_pipeline.py
class ParameterDefinition(BaseModel):
    param_name: str                              # "VWAP_DEPTH_MIN"
    bot_id: str                                  # "k_stock_trader"
    strategy_id: Optional[str]                   # "kpr"
    param_type: ParameterType                    # YAML_FIELD or PYTHON_CONSTANT
    file_path: str                               # "strategy_kpr/config/constants.py"
    yaml_key: Optional[str]                      # "kpr.vwap_depth_min" (if YAML)
    python_path: Optional[str]                   # module path (if Python constant)
    current_value: Any
    valid_range: Optional[tuple[float, float]]   # (0.01, 0.10)
    valid_values: Optional[list[Any]]            # for discrete params
    value_type: Literal["int", "float", "bool", "str"]
    category: str                                # "entry_signal", "risk", "exit"
    is_safety_critical: bool                     # stricter validation if True

class BotConfigProfile(BaseModel):
    bot_id: str
    repo_url: str          # GitHub repo URL
    repo_dir: str          # local clone path
    parameters: list[ParameterDefinition]
    strategies: list[str]  # e.g. ["kalcb", "olr"]

    def get_parameter(self, name: str) -> Optional[ParameterDefinition]: ...
    def get_parameters_by_category(self, category: str) -> list[ParameterDefinition]: ...
```

These profiles are loaded from `data/bot_configs/{bot_id}.yaml` by the
`ConfigRegistry`. This tells the approval pipeline exactly which file and field
to modify when generating a PR — different per bot, but the same API.

---

## Layer 3: Generic Optimisation Code

All code in `skills/` and `orchestrator/` is completely bot-agnostic.

### Backtest Simulator (`skills/backtest_simulator.py`)

The simulator filters trades using the parameter dict's keys, not strategy-specific logic:

```python
def _filter_trades(self, trades: list[TradeEvent], params: dict) -> list[TradeEvent]:
    result = list(trades)
    min_strength = params.get("signal_strength_min")
    if min_strength is not None:
        result = [t for t in result if t.entry_signal_strength >= min_strength]
    return result

def _include_missed(self, missed: list[MissedOpportunityEvent], params: dict) -> list[MissedOpportunityEvent]:
    include_filters: list[str] = params.get("include_blocked_by", [])
    if not include_filters:
        return []
    return [m for m in missed if m.blocked_by in include_filters]
```

The simulator then computes purely P&L-derived metrics:
- Sharpe ratio (annualised: mean/stdev × √252)
- Sortino ratio (downside deviation only)
- Calmar ratio (net PnL / max drawdown)
- Profit factor (total wins / abs total losses)
- Max drawdown, win rate, per-regime PnL breakdown

None of these metrics require knowledge of entry/exit logic. They work on any
`TradeEvent` regardless of whether it came from a KPR VWAP pullback, an ATRSS
trend-following entry, or a NQDTC box breakout.

### Parameter Optimizer (`skills/param_optimizer.py`)

Pure combinatorial grid search using `itertools.product`:

```python
def generate_grid(self) -> list[dict[str, float]]:
    names = [p.name for p in self._space.parameters]
    grids = [p.grid_values for p in self._space.parameters]
    return [dict(zip(names, values)) for values in itertools.product(*grids)]
```

For each combo: simulate → filter by constraints (min trades, max drawdown) →
rank by objective. Completely strategy-agnostic.

### Cost Model (`skills/cost_model.py`)

Three slippage models, all generic:
- **FIXED**: constant bps per trade
- **SPREAD_PROPORTIONAL**: bid-ask spread based
- **EMPIRICAL**: regime-specific bps from historical data

The cost config comes from the WFO YAML, which specifies the appropriate model
per bot (e.g., KRX's 20 bps round-trip vs NQ's ~1 bps).

### Fold Generator (`skills/fold_generator.py`)

Purely temporal — splits date ranges into IS/OOS windows. No strategy knowledge.
Works identically for Korean stock intraday data and US futures multi-day swing data.

### Robustness Tester (`skills/robustness_tester.py`)

- **Neighborhood test**: perturbs each param ±10%, simulates all neighbours
- **Regime stability**: checks profitable in ≥3 of 4 regime types

Both are metric-based, operating on the generic `SimulationMetrics` output.
The regime types come from the `market_regime` field of `TradeEvent` — each bot
classifies regimes differently, but they all produce the same string field.

### Leakage Detector (`skills/leakage_detector.py`)

Audits temporal correctness of features and labels. Pure timestamp comparison,
no strategy-specific logic.

---

## How It All Connects: End-to-End Flow

### 1. WFO Trigger

The scheduler or brain dispatches a `SPAWN_WFO` action for a specific `bot_id`:

```python
# orchestrator/handlers.py
async def handle_wfo(self, action: Action):
    bot_id = action.details.bot_id  # e.g., "k_stock_trader"
```

### 2. Load Bot-Specific Config

```python
    config_path = data_dir / "wfo_configs" / f"{bot_id}.yaml"
    config = WFOConfig(**yaml.safe_load(config_path.read_text()))
    # Contains: WFOMethod, ParameterSpace, CostModelConfig, RobustnessConfig
```

This is the only bot-specific input. Different bots have different YAML files
with different parameter spaces and cost assumptions.

### 3. Load Trade Data

```python
    def _load_trades_for_wfo(self, bot_id, date_start, date_end):
        for date_dir in sorted(curated_dir.iterdir()):
            bot_dir = date_dir / bot_id
            trades_file = bot_dir / "trades.jsonl"   # Same structure, any bot
            missed_file = bot_dir / "missed.jsonl"   # Same structure, any bot
```

Scans `data/curated/YYYY-MM-DD/{bot_id}/` — the directory name is the only
bot-specific part. File format and schema are identical.

### 4. Run Generic Pipeline

```python
    runner = WFORunner(config)
    report = runner.run(trades, missed, data_start, data_end)
    # Folds → Grid Search → Consensus → Cost Sensitivity → Robustness → Recommendation
```

Same code path regardless of bot. The `config` object carries all bot-specific
settings (parameter space, cost model, robustness thresholds).

### 5. Recommendation → Autonomous Pipeline

If strategy engine produces a suggestion to change a parameter:

```
StrategySuggestion(bot_id="swing_trader", category="exit", title="Increase TP1_R to 1.2")
    ↓
ConfigRegistry.resolve_suggestion_to_params()
    → finds ParameterDefinition(param_name="TP1_R", file_path="strategy/config.py",
                                 python_path="TP1_R", valid_range=(0.8, 1.5))
    ↓
SuggestionBacktester validates data quality (generic: loads last 30 days of trades)
    ↓
ApprovalRequest → Telegram card with approve/reject buttons
    ↓
User approves → ApprovalHandler
    → FileChangeGenerator reads strategy/config.py, updates TP1_R = 1.2
    → PRBuilder creates branch ta/suggestion-{id}, pushes, opens PR
    ↓
DeploymentMonitor tracks post-merge for 24h
    → Collects metrics snapshots every 30 min
    → If PnL drops >50% or win rate drops >15pp → auto-creates rollback PR
```

The same approval pipeline handles all three bots. The `ParameterDefinition`
tells it whether to edit a YAML file (`param_type=YAML_FIELD`) or a Python
constant file (`param_type=PYTHON_CONSTANT`), and which path/key to modify.

---

## Bot-Specific Strategy Details

### k_stock_trader (4 strategies, KRX)

**KMP (momentum breakout)**: Scans 155 blue-chip stocks at 09:15 for volume
surges + opening range breakouts. Time-decaying surge thresholds, relative
volume gating, breadth regime check. Hard stop at 1.2×ATR, risk 0.5% NAV.

WFO-optimisable parameters:
- `OR_RANGE_MIN/MAX` (opening range bounds)
- `MIN_SURGE_BASE/SLOPE` (time-decaying surge threshold)
- `RVOL_MIN` (minimum relative volume)
- `STALL_MIN_MINUTES` (hold time before stall exit)
- `QUALITY_THRESHOLD_*` (quality score tiers)

**KPR (VWAP pullback)**: Detects price pullback to VWAP band (2–5% below) via
panic flush (3%+ drop in 15 min) or drift (2%+ drop after 60 min). Requires 2
consecutive closes above reclaim level. Micro-pressure signals from tick-level
uptick/downtick ratios. Partial at 1.5R, trailing at 50% of gain.

WFO-optimisable parameters:
- `VWAP_DEPTH_MIN/MAX` (pullback acceptance band)
- `PANIC_DROP_PCT`, `DRIFT_DROP_PCT` (setup triggers)
- `BASE_ACCEPT_CLOSES` (confirmation bars)
- `PARTIAL_R_TARGET`, `FULL_R_TARGET_*` (exit R-multiples)
- `TRAIL_FACTOR` (trailing stop offset)
- `TIME_STOP_MINUTES` (hold timeout)

**OLR/KALCB (daily research + breakout surfaces)**: Current k_stock_trader
surfaces use OLR daily research artifacts and KALCB breakout execution logic.
LRS remains relevant here as the local KRX daily/research artifact store, not
as a live refresh adapter owned by the data repo.

WFO-optimisable parameters:
- Regime scoring weights and tier thresholds
- `LEADER_TIER_A/B_PCT` (leader filter cutoff)
- `ENTRY_DIP_SMA_PERIOD`, `ENTRY_VOL_DRYUP_PCT`
- `AVWAP_BREAKDOWN_PCT`, `BREAKDOWN_VOL_MULT`
- `SIZE_TOP_20_MULT`, `SIZE_20_50_MULT`, `SIZE_50_80_MULT`

**PCIM (event-driven)**: Gemini AI analysis of social sentiment. Wider targets
(2.5×ATR TP, 1.5×ATR SL) and extended holds (~3.3h). Fewer tuneable parameters.

### swing_trader (5 strategies, US futures/ETF)

**ATRSS (primary)**: Multi-timeframe trend-follower. Daily ADX/EMA structure
for regime (RANGE/TREND/STRONG_TREND with hysteresis). Hourly pullback entries
to EMA with quality score gating (0–7, gate ≥ 4). Three entry types: Pullback-
to-Value (A), Breakout arm+pullback (B), Stop-and-Reverse (C). ATR-based stops
with break-even at 1.25R, chandelier trailing, profit floor enforcement. Uniform
partial exits at TP1 (1.0R, 33%), TP2 (2.0R, 33%), runner on trail.

Per-symbol `SymbolConfig` with individually tuneable:
- `daily_ema_fast/slow` (15–25, 50–60)
- `adx_on/off` (hysteresis thresholds: 16–24)
- `daily_mult/hourly_mult` (stop multipliers: 1.5–3.5)
- `chand_mult` (chandelier: 2.0–4.0)
- `base_risk_pct` (0.5–2.0%)

Global constants also tuneable:
- `RECOVERY_TOLERANCE_ATR` (pullback recovery zone)
- `TP1_R/TP2_R` (partial exit levels)
- `ADDON_A_R/ADDON_B_R` (pyramiding thresholds)
- `STALL_MFE_THRESHOLD` (stall exit sensitivity)

Portfolio-level: 6% heat cap, 18h order expiry, drawdown throttle (5%→75%,
8%→50%, 11%→halt). Cooldown per regime (RANGE 4h, TREND 2h, STRONG 1h).

### momentum_trader (3 strategies, NQ/MNQ)

**Helix v4.0 (primary)**: Multi-TF momentum with three setup classes:
- **Class M** (1H pullback): Higher-low pivot pattern → pullback depth 0.2–1.6
  ATR → MACD reclaim → entry at breakout pivot. Alignment score (0–2) from
  daily+4H EMA structure. Size: 0.65x base.
- **Class F** (fast re-entry): Within 8 bars of trailing stop exit. Tighter stop
  (0.40 ATR), half-size (0.50x).
- **Class T** (4H trend continuation): 9-point gate (daily+4H+1H alignment,
  MACD expansion, trend strength >0.60, compression gate). Half-size.

Position management: catastrophic floor (-1.5R), early adverse kill (-0.80R at
bar 4), momentum stall check (bar 8), trail activation (+0.55R), uniform
partials (P1 at 1.0R 30%, P2 at 1.5R 30%, runner 40%), MFE ratchet floor (65%
of peak after +1.5R), time-decay BE force (bar 12), stale exits (16–20 bars).

Risk engine: 1.25% base risk × vol_factor × setup_mult × session_mult ×
hour_mult × dow_mult × drawdown_throttle.

Session blocks: ETH_EUROPE (0.50x, longs only), RTH_PRIME (1.00x),
RTH_DEAD (0.70x), ETH_OVERNIGHT (0.50x). Monday/Wednesday blocked, Thursday 0.50x.

**NQDTC v2.1** (~30 WFO parameters): displacement quantile, regime slope,
ADX thresholds, evidence scorecard, squeeze quantiles, entry offsets, risk/position management.

**VdubusNQ v4.2** (~25 WFO parameters): VWAP touch lookback, extension skip,
momentum slope, stop points, partial percentages, trail parameters, weekend
hold/lock thresholds.

---

## How Each Bot's Parameters Map to the Generic Simulator

The key abstraction is that the backtest simulator only filters on
`signal_strength_min` and `include_blocked_by` from the params dict. The actual
parameter values (like `VWAP_DEPTH_MIN` or `daily_mult`) don't filter trades
in the simulator — they were already baked into the trade at execution time.

This means WFO is operating on a **counterfactual basis**: "given the trades
that already happened, which parameter settings would have produced the best
risk-adjusted returns?" It's replay-based optimisation, not strategy simulation.

The grid search answer tells the system: "if `signal_strength_min` were set to
0.7 instead of 0.5, these trades would have been filtered out, and the resulting
portfolio would have Sharpe X." For parameters that don't map to trade filtering
(like stop multipliers or EMA periods), the WFO recommendation is supplemented
by Claude's confirmatory review, which assesses whether the parameter change
makes strategic sense given the bot's logic.

---

## Summary: Adding a New Bot

To bring a new bot into the WFO pipeline:

1. **Bot side**: Instrument with `InstrumentationKit` emitting `TradeEvent`,
   `MissedOpportunityEvent`, `DailySnapshot`, `ErrorEvent` via sidecar to relay
2. **Trading assistant**: Create `data/wfo_configs/{bot_id}.yaml` with parameter
   space definition (names, ranges, steps, current values)
3. **Trading assistant**: Create `data/bot_configs/{bot_id}.yaml` with parameter
   definitions (file paths, YAML keys, valid ranges, categories, safety flags)
4. **Done**: The entire pipeline — WFO runner, backtest simulator, grid search,
   robustness testing, leakage auditing, autonomous approval, PR creation,
   deployment monitoring, and rollback — works automatically

No code changes required. The bot's strategy can be arbitrarily complex — the
trading assistant only sees standardised events and configuration.
