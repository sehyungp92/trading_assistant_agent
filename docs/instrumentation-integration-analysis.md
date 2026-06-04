# Instrumentation Integration Analysis

Exhaustive audit of how `_references/stock_trader/` strategy code integrates with the instrumentation system.

---

## 1. Architecture Overview

```
Strategy Engine (ORB/IARIC)
    │
    ├── self._instrumentation  →  InstrumentationKit (facade.py)
    │       ├── kit.log_entry()    → trade_logger.log_entry()
    │       ├── kit.log_exit()     → trade_logger.log_exit()
    │       ├── kit.log_missed()   → missed_logger.log_missed()
    │       ├── kit.log_error()    → error_logger.log_error()
    │       ├── kit.on_indicator_snapshot()
    │       ├── kit.on_orderbook_context()
    │       ├── kit.on_order_event()
    │       └── kit.emit_heartbeat()
    │
    └── self._trade_recorder  →  InstrumentedTradeRecorder (pg_bridge.py)
            ├── record_entry()  →  PG write + kit.log_entry()
            └── record_exit()   →  PG write + kit.log_exit()
```

**Key insight**: Strategy engines do NOT call `kit.log_entry()` or `kit.log_exit()` directly.
They call `self._trade_recorder.record_entry()` / `record_exit()`, and the
`InstrumentedTradeRecorder` (pg_bridge.py) bridges to the kit. The engine calls
`self._instrumentation.log_missed()`, `on_indicator_snapshot()`, `on_orderbook_context()`,
and `on_order_event()` directly.

### Initialization Chain

```
session.py (bootstrap_runtime):
  1. InstrumentationManager(oms, strategy_id, strategy_type)  →  loads YAML config
  2. InstrumentationKit(manager, strategy_type="strategy_orb")
  3. InstrumentedTradeRecorder(pg_trade_recorder, kit, strategy_id, strategy_type)
  4. USORBEngine(..., trade_recorder=instrumented_recorder, instrumentation=kit)
```

File: `strategy_orb/session.py` lines 143-165
File: `strategy_iaric/main.py` (similar pattern)

---

## 2. Every Call Site — Exhaustive Inventory

### 2.1 ORB Engine (`strategy_orb/engine.py`)

#### 2.1.1 Entry Recording (via trade_recorder.record_entry)

**Location**: Lines 1052-1092 (inside fill handler, `role == "ENTRY"`)

```python
ctx.position.trade_id = await self._trade_recorder.record_entry(
    strategy_id=STRATEGY_ID,
    instrument=ctx.symbol,
    direction="LONG",
    quantity=fill_qty,
    entry_price=Decimal(str(fill_price)),
    entry_ts=event.timestamp,
    setup_tag="orb",
    entry_type="stop_limit",
    meta={
        "entry_signal": "us_orb_breakout",
        "entry_signal_id": event.oms_order_id or ctx.symbol,
        "entry_signal_strength": float(ctx.quality_score or ctx.pre_score or 0.0),
        "strategy_params": {
            "pre_score": ctx.pre_score,
            "quality_score": ctx.quality_score,
            "surge": ctx.surge,
            "rvol_1m": ctx.rvol_1m,
            "stop0": ctx.final_stop,
        },
        "signal_factors": self._entry_signal_factors(ctx),
        "filter_decisions": self._entry_filter_decisions(ctx),
        "sizing_inputs": {
            "qty": fill_qty,
            "planned_entry": ctx.planned_entry,
            "planned_limit": ctx.planned_limit,
            "final_stop": ctx.final_stop,
        },
        "portfolio_state": self._portfolio_state_snapshot(),
        "session_type": self._session_type(event.timestamp),
        "exchange_timestamp": event.timestamp,
        "expected_entry_price": (
            entry_order.limit_price
            if entry_order and entry_order.limit_price is not None
            else (ctx.planned_limit or ctx.planned_entry)
        ),
    },
    account_id=self._account_id,
)
```

**Data passed**: signal_factors (5 factors), filter_decisions (3 filters), sizing_inputs,
portfolio_state, session_type, expected_entry_price, strategy_params

**pg_bridge.py then extracts from `meta` and calls**:
```python
kit.log_entry(
    trade_id=trade_id,
    pair=instrument,
    side=direction,
    entry_price=float(entry_price),
    position_size=float(quantity),
    position_size_quote=float(entry_price) * float(quantity),
    entry_signal=context.get("entry_signal"),
    entry_signal_id=context.get("entry_signal_id"),
    entry_signal_strength=float(context.get("entry_signal_strength", 1.0)),
    strategy_params=context.get("strategy_params"),
    signal_factors=context.get("signal_factors"),
    filter_decisions=context.get("filter_decisions"),
    sizing_inputs=context.get("sizing_inputs"),
    portfolio_state=context.get("portfolio_state"),
    session_type=str(context.get("session_type", "")),
    contract_month=str(context.get("contract_month", "")),
    margin_used_pct=context.get("margin_used_pct"),
    concurrent_positions=context.get("concurrent_positions"),
    drawdown_pct=context.get("drawdown_pct"),
    drawdown_tier=str(context.get("drawdown_tier", "")),
    drawdown_size_mult=context.get("drawdown_size_mult"),
    bar_id=context.get("bar_id"),
    exchange_timestamp=context.get("exchange_timestamp"),
    entry_latency_ms=context.get("entry_latency_ms"),
    signal_evolution=context.get("signal_evolution"),
    execution_timestamps=context.get("execution_timestamps"),
)
```

#### 2.1.2 Exit Recording (via trade_recorder.record_exit)

**Location**: Lines 1150-1171

```python
await self._trade_recorder.record_exit(
    trade_id=ctx.position.trade_id,
    exit_price=Decimal(str(fill_price)),
    exit_ts=event.timestamp,
    exit_reason=role or "EXIT",
    realized_r=Decimal(str(round(realized_r, 4))),
    realized_usd=Decimal(str(round(ctx.position.realized_pnl_usd, 2))),
    mfe_r=Decimal(str(round(
        (ctx.position.max_favorable_price - ctx.position.entry_price)
        / max(ctx.position.initial_risk_per_share, 1e-9), 4))),
    mae_r=Decimal(str(round(
        (ctx.position.max_adverse_price - ctx.position.entry_price)
        / max(ctx.position.initial_risk_per_share, 1e-9), 4))),
    max_adverse_price=Decimal(str(ctx.position.max_adverse_price)),
    max_favorable_price=Decimal(str(ctx.position.max_favorable_price)),
    meta={
        "exchange_timestamp": event.timestamp,
        "expected_exit_price": expected_exit_price or fill_price,
    },
)
```

**pg_bridge.py then calls**:
```python
kit.log_exit(
    trade_id=trade_id,
    exit_price=float(exit_price),
    exit_reason=exit_reason,
    fees_paid=context.get("fees_paid", 0.0),
    exchange_timestamp=context.get("exchange_timestamp"),
    expected_exit_price=context.get("expected_exit_price"),
    exit_latency_ms=context.get("exit_latency_ms"),
    mfe_r=float(mfe_r),
    mae_r=float(mae_r),
    mfe_price=float(max_favorable_price),
    mae_price=float(max_adverse_price),
    session_transitions=context.get("session_transitions"),
)
```

#### 2.1.3 Missed Opportunity Logging (direct kit call)

**Location**: `_log_missed()` method, lines 382-420

```python
self._instrumentation.log_missed(
    pair=ctx.symbol,
    side="LONG",
    signal="us_orb_breakout",
    signal_id=f"{ctx.symbol}:{blocked_by}:{int(exchange_timestamp.timestamp())}",
    signal_strength=float(ctx.quality_score or ctx.pre_score or 0.0),
    blocked_by=blocked_by,
    block_reason=block_reason,
    strategy_params={
        "state": ctx.state.value,
        "vdm_state": ctx.vdm.state.value,
        "sector": ctx.sector,
        "planned_entry": ctx.planned_entry,
        "planned_limit": ctx.planned_limit,
        "final_stop": ctx.final_stop,
        "quality_score": ctx.quality_score,
        "pre_score": ctx.pre_score,
        "surge": ctx.surge,
        "rvol_1m": ctx.rvol_1m,
        **(strategy_params or {}),
    },
    filter_decisions=filter_decisions,   # defaults to self._entry_filter_decisions(ctx)
    exchange_timestamp=exchange_timestamp,
    session_type=self._session_type(exchange_timestamp),
)
```

**Called from 7 locations** in the ORB engine:
| Line | `blocked_by` | Context |
|------|-------------|---------|
| 672 | `sector_cap` | Sector already has open position |
| 733 | `acceptance_timeout` | Acceptance deadline expired |
| 761 | `quality_or_qty` | Quality score below threshold or qty=0 |
| 772 | `caution_quality` | VDM caution + quality below caution_min |
| 803 | `entry_ttl` | Entry order age expired |
| 1216 | `entry_terminal` | Order cancelled/rejected, no rearms left |
| (additional: `risk_halt`, `max_positions`) | Various risk blocks |

#### 2.1.4 Indicator Snapshot (direct kit call)

**Location**: `_emit_indicator_snapshot()`, lines 308-335

```python
self._instrumentation.on_indicator_snapshot(
    pair=ctx.symbol,
    indicators={
        "spread_pct": float(ctx.spread_pct or 0.0),
        "rvol_1m": float(ctx.rvol_1m or 0.0),
        "relative_strength_5m": float(ctx.relative_strength_5m or 0.0),
        "surge": float(ctx.surge or 0.0),
        "or_pct": float(ctx.or_pct or 0.0),
        "gap_pct": float(ctx.gap_pct or 0.0),
        "imbalance_90s": float(ctx.imbalance_90s or 0.0),
    },
    signal_name="us_orb_breakout",
    signal_strength=float(ctx.quality_score or ctx.pre_score or 0.0),
    decision=ctx.state.value,
    strategy_type="strategy_orb",
    exchange_timestamp=now,
    bar_id=now.isoformat(),
    context={...},  # additional context
)
```

#### 2.1.5 Orderbook Context (direct kit call)

**Location**: `_log_orderbook_context()`, lines 338-375

```python
self._instrumentation.on_orderbook_context(
    pair=ctx.symbol,
    best_bid=best_bid,
    best_ask=best_ask,
    trade_context=trade_context,   # "entry" or "exit"
    related_trade_id=related_trade_id,
    bid_depth_10bps=bid_depth,
    ask_depth_10bps=ask_depth,
    bid_levels=[{"price": best_bid, "size": bid_depth}],
    ask_levels=[{"price": best_ask, "size": ask_depth}],
    exchange_timestamp=exchange_timestamp,
)
```

Called at: entry fill (line 1093), exit fill (line 1172).

#### 2.1.6 Order Event (direct kit call)

**Location**: `_log_order_event()`, lines 425-455

```python
self._instrumentation.on_order_event(
    order_id=order_id,
    pair=symbol,
    side="SELL" if order_type in {"STOP", "MARKET_EXIT"} else "BUY",
    order_type=order_type,
    status=status,
    requested_qty=requested_qty,
    requested_price=requested_price,
    related_trade_id=related_trade_id,
    strategy_type="strategy_orb",
    session=self._session_type(exchange_timestamp or datetime.now(timezone.utc)),
    exchange_timestamp=exchange_timestamp,
)
```

#### 2.1.7 MFE/MAE Tracking (position excursion updates)

**Location**: `_update_position_excursions()`, lines 376-380

```python
def _update_position_excursions(self, ctx: SymbolContext) -> None:
    if ctx.position is None or ctx.last_price is None:
        return
    ctx.position.max_favorable_price = max(ctx.position.max_favorable_price, ctx.last_price)
    ctx.position.max_adverse_price = min(ctx.position.max_adverse_price, ctx.last_price)
```

Called on every bar while in position (State.IN_POSITION handler, line ~816).
Values flow to instrumentation via `record_exit()` → `mfe_r`, `mae_r`, `mfe_price`, `mae_price`.

---

### 2.2 IARIC Engine (`strategy_iaric/engine.py`)

#### 2.2.1 Entry Recording (via trade_recorder.record_entry)

**Location**: Lines 1085-1124

```python
position.trade_id = await self._trade_recorder.record_entry(
    strategy_id=STRATEGY_ID,
    instrument=symbol,
    direction="LONG",
    quantity=fill_qty,
    entry_price=Decimal(str(fill_price)),
    entry_ts=event.timestamp,
    setup_tag=position.setup_tag,
    entry_type="marketable_limit",
    meta={
        "entry_signal": state.setup_type or position.setup_tag,
        "entry_signal_id": event.oms_order_id or symbol,
        "entry_signal_strength": self._confidence_score(state.confidence),
        "strategy_params": {
            "setup_type": state.setup_type,
            "location_grade": state.location_grade,
            "sponsorship_signal": state.sponsorship_signal,
            "micropressure_signal": state.micropressure_signal,
            "flowproxy_signal": state.flowproxy_signal,
            "stop0": state.stop_level,
        },
        "signal_factors": self._entry_signal_factors(state),
        "filter_decisions": self._entry_filter_decisions(
            state=state, market=market, timing_ok=True,
        ),
        "sizing_inputs": {
            "entry_price": fill_price,
            "stop_level": state.stop_level,
            "qty": fill_qty,
        },
        "portfolio_state": self._portfolio_state_snapshot(),
        "session_type": self._current_session_type(event.timestamp),
        "exchange_timestamp": event.timestamp,
        "expected_entry_price": entry_order.limit_price if entry_order else fill_price,
    },
    account_id=self._account_id,
)
```

#### 2.2.2 Exit Recording (via trade_recorder.record_exit)

**Location**: Lines 1163-1189

```python
await self._trade_recorder.record_exit(
    trade_id=position.trade_id,
    exit_price=Decimal(str(fill_price)),
    exit_ts=event.timestamp,
    exit_reason=role or "EXIT",
    realized_r=Decimal(str(round(realized_r, 4))),
    realized_usd=Decimal(str(round(position.realized_pnl_usd, 2))),
    mfe_r=Decimal(str(round(
        (position.max_favorable_price - position.entry_price)
        / max(position.initial_risk_per_share, 1e-9), 4))),
    mae_r=Decimal(str(round(
        (position.max_adverse_price - position.entry_price)
        / max(position.initial_risk_per_share, 1e-9), 4))),
    max_adverse_price=Decimal(str(position.max_adverse_price)),
    max_favorable_price=Decimal(str(position.max_favorable_price)),
    meta={
        "exchange_timestamp": event.timestamp,
        "expected_exit_price": (
            exit_order.limit_price if exit_order and exit_order.limit_price is not None
            else fill_price
        ),
        "session_transitions": [state.last_transition_reason]
            if state.last_transition_reason else [],
    },
)
```

**Note**: IARIC passes `session_transitions` in meta (unlike ORB which does not).

#### 2.2.3 Missed Opportunity Logging (direct kit call)

**Location**: `_log_missed()`, lines 496-535

```python
self._instrumentation.log_missed(
    pair=symbol,
    side="LONG",
    signal=signal,
    signal_id=f"{symbol}:{blocked_by}:{int(ts.timestamp())}",
    signal_strength=signal_strength or self._confidence_score(state.confidence),
    blocked_by=blocked_by,
    block_reason=block_reason,
    strategy_params={
        "setup_type": state.setup_type,
        "fsm_state": state.fsm_state,
        "confidence": state.confidence,
        "location_grade": state.location_grade,
        "stop_level": state.stop_level,
        **(strategy_params or {}),
    },
    filter_decisions=filter_decisions or self._entry_filter_decisions(
        state=state, market=self._markets[symbol], timing_ok=True,
    ),
    exchange_timestamp=exchange_timestamp,
    session_type=self._current_session_type(exchange_timestamp or datetime.now(timezone.utc)),
)
```

**Called from 5 locations**:
| Line | `blocked_by` | Context |
|------|-------------|---------|
| 722 | `entry_gate` | Confidence RED or timing gate failed |
| 740 | `spread_guard` | Live spread too wide |
| 771 | `portfolio_constraints` | Position limits / risk constraints |
| 816 | `oms_submit` | OMS returned no order ID |
| 1222 | `entry_terminal` | Order terminal event |

#### 2.2.4 Indicator Snapshot (direct kit call)

**Location**: `_emit_indicator_snapshot()`, lines 422-453

```python
self._instrumentation.on_indicator_snapshot(
    pair=symbol,
    indicators={
        "spread_pct": float(market.spread_pct or 0.0),
        "atr_5m_pct": float(self._atr_5m_pct(symbol)),
        "session_vwap_live": float(market.avwap_live or 0.0),
        "average_30m_volume": float(state.average_30m_volume or 0.0),
        "expected_volume_pct": float(state.expected_volume_pct or 0.0),
    },
    signal_name=state.setup_type or "iaric_signal",
    signal_strength=self._confidence_score(state.confidence),
    decision=state.fsm_state,
    strategy_type="strategy_iaric",
    exchange_timestamp=bar.end_time,
    bar_id=bar.end_time.isoformat(),
    context={
        "location_grade": state.location_grade,
        "micropressure_signal": state.micropressure_signal,
        "flowproxy_signal": state.flowproxy_signal,
        "sponsorship_signal": state.sponsorship_signal,
    },
)
```

#### 2.2.5 Orderbook Context (direct kit call)

**Location**: Lines 454-494, same pattern as ORB.

#### 2.2.6 Order Event (direct kit call)

**Location**: Lines 538-569, same pattern as ORB.

---

### 2.3 main.py (both strategies)

#### 2.3.1 `log_error()` — Runtime Errors

**Location**: `strategy_orb/main.py` lines 59-69

```python
services.instrumentation_kit.log_error(
    error_type=error_type,          # e.g. "scanner_loop_error"
    message=str(exc),
    severity=severity,              # "medium" or "high"
    category="dependency",
    context={"component": "strategy_orb.main"},
    exc=exc,
)
```

Called from: scanner_loop errors (line 82), market_data errors (line 89), heartbeat errors (line 151).

#### 2.3.2 `emit_heartbeat()` — Periodic Health

**Location**: `strategy_orb/main.py` lines 92-152

The heartbeat loop (every 30s) calls `emit_heartbeat()` which writes to the PG store
(not via the kit). The kit's own `emit_heartbeat()` method is NOT directly called by
the ORB main.py — the heartbeat goes through a separate DB path.

---

## 3. How Key Data Is Computed / Obtained

### 3.1 signal_factors

**ORB** (`_entry_signal_factors`, engine.py):
```python
[
    {"factor_name": "pre_score",             "factor_value": ctx.pre_score,             "threshold": 70.0},
    {"factor_name": "quality_score",         "factor_value": ctx.quality_score,         "threshold": settings.minimum_quality_score},
    {"factor_name": "surge",                 "factor_value": ctx.surge,                 "threshold": 2.0},
    {"factor_name": "rvol_1m",              "factor_value": ctx.rvol_1m,              "threshold": 1.5},
    {"factor_name": "relative_strength_5m",  "factor_value": ctx.relative_strength_5m,  "threshold": 0.0},
]
```

**IARIC** (`_entry_signal_factors`, engine.py):
```python
[
    {"factor_name": "location_grade",        "factor_value": grade_scores.get(state.location_grade, 0)},
    {"factor_name": "sponsorship_signal",    "factor_value": label_scores.get(state.sponsorship_signal, 0)},
    {"factor_name": "micropressure_signal",  "factor_value": label_scores.get(state.micropressure_signal, 0)},
    {"factor_name": "flowproxy_signal",      "factor_value": label_scores.get(state.flowproxy_signal, 0)},
    {"factor_name": "confidence",            "factor_value": self._confidence_score(state.confidence)},
]
```

### 3.2 filter_decisions

**ORB** (`_entry_filter_decisions`, engine.py):
```python
[
    {"filter_name": "quality_score_gate",   "threshold": settings.minimum_quality_score, "passed": ...},
    {"filter_name": "spread_gate",          "threshold": settings.spread_limit_pct,      "passed": ...},
    {"filter_name": "caution_quality_gate", "threshold": settings.caution_quality_min,   "passed": ...},
]
```

**IARIC** (`_entry_filter_decisions`, engine.py):
```python
[
    {"filter_name": "confidence_gate", "threshold": 0.5,                          "passed": confidence != "RED"},
    {"filter_name": "timing_gate",     "threshold": 1.0,                          "passed": timing_ok},
    {"filter_name": "spread_gate",     "threshold": settings.max_median_spread_pct * 2, "passed": ...},
]
```

### 3.3 market_regime

- Obtained inside `InstrumentationKit.log_entry()` (facade.py line ~132):
  `regime = self._mgr.regime_classifier.current_regime(pair)`
- The engine does NOT pass market_regime — the kit fetches it autonomously.
- Similarly for `log_missed()`: kit calls `regime_classifier.current_regime(pair)`.

### 3.4 process_quality_score

- Starts at 100 on `log_entry()` (trade_logger.py line 271).
- Recomputed on `log_exit()` via `ProcessScorer.score_trade()` (trade_logger.py lines 415-425).
- ProcessScorer is a deterministic rules engine loaded from `process_scoring_rules.yaml`.
- Deductions for: regime_mismatch, weak_signal, slippage_spike, late_entry, early_exit, etc.
- Root causes assigned based on score + PnL: normal_win, normal_loss, exceptional_win, etc.

### 3.5 post_exit prices (1h/4h)

- Queued during `log_exit()` into `_pending_exit_backfills` (trade_logger.py line 405).
- Backfilled by `run_post_exit_backfill(data_provider)` (trade_logger.py line 500).
- Must be called periodically with a data provider that supports `get_ohlcv()`.
- Computes `post_exit_1h_price`, `post_exit_4h_price`, `post_exit_1h_move_pct`, `post_exit_4h_move_pct`.

### 3.6 MFE/MAE

- **Tracked per-bar**: `_update_position_excursions()` updates `max_favorable_price` / `max_adverse_price` on every bar tick while in position.
- **Passed on exit**: `record_exit()` computes `mfe_r` and `mae_r` as R-multiples.
- **trade_logger computes**: `mfe_pct`, `mae_pct` (percentage), `exit_efficiency` (actual_R / mfe_R).

### 3.7 sizing_inputs

**ORB**: `{qty, planned_entry, planned_limit, final_stop}`
**IARIC**: `{entry_price, stop_level, qty}`

### 3.8 portfolio_state

**ORB** (`_portfolio_state_snapshot()`):
```python
{
    "open_positions": self._portfolio.open_positions,
    "halt_new_entries": self._portfolio.halt_new_entries,
    "flatten_all": self._portfolio.flatten_all,
    "total_pnl_pct": self._portfolio.total_pnl_pct,
    "sectors_in_use": sorted(self._portfolio.sectors_in_use),
    "regime_ok": self._regime.regime_ok,
    "risk_off": self._regime.risk_off,
}
```

---

## 4. Gaps — Data Available But NOT Being Logged

### 4.1 CRITICAL Gaps

| Gap | Available In | Not Passed To | Impact |
|-----|-------------|--------------|--------|
| **entry_latency_ms** | OMS events have timestamps; delta computable | `record_entry()` meta — missing `entry_latency_ms` key | Slippage analysis cannot correlate latency. Trade_logger field exists but is never populated. |
| **exit_latency_ms** | Same as above | `record_exit()` meta — missing `exit_latency_ms` key | Exit slippage analysis incomplete. |
| **fees_paid** | Available from broker fill events | `record_exit()` meta — missing `fees_paid` key; defaults to 0.0 | PnL computations ignore commission costs. |
| **execution_timestamps** | OMS timestamps (signal_detected_at, order_submitted_at, fill_received_at) are available in the OMS event flow | `record_entry()` meta — missing `execution_timestamps` key | Cannot audit execution cascade latency. |
| **session_transitions (ORB)** | ORB engine tracks session transitions via position state | ORB `record_exit()` meta does NOT pass `session_transitions` (IARIC does) | ORB trades that span sessions lose transition context. |
| **concurrent_positions** | `self._portfolio.open_positions` count available | ORB `record_entry()` meta — missing `concurrent_positions` key | pg_bridge looks for this but gets None. |
| **drawdown_pct / drawdown_tier / drawdown_size_mult** | ORB tracks `total_pnl_pct` in portfolio; could derive drawdown | Not passed in meta dict | Drawdown-aware sizing analysis blind. |
| **margin_used_pct** | Available from broker account state | Not in meta dict | Margin utilization not tracked. |
| **contract_month** | Not applicable for US equities, but field exists | Always "" | N/A for stocks, relevant if futures added. |

### 4.2 MODERATE Gaps

| Gap | Available In | Not Passed To | Impact |
|-----|-------------|--------------|--------|
| **bar_id** | ORB has `now.isoformat()` in indicator snapshots | `record_entry()` meta — missing `bar_id` key | Cannot cross-reference entry to specific bar. |
| **signal_evolution** | IARIC tracks signal state transitions | Not passed in `record_entry()` meta for either engine | Cannot replay signal decision path. |
| **ORB: vwap, imbalance_90s, last5m_value, gap_pct** | Available on `ctx` | Not in `signal_factors` | Only 5 factors logged; rich context lost. |
| **ORB: or_high, or_low, or_mid, or_pct, value15** | Available on `ctx` | Not in strategy_params or signal_factors | Opening range context not captured for analysis. |
| **IARIC: average_30m_volume, expected_volume_pct** | Available on `state` | Not in signal_factors or strategy_params at entry | Volume context lost. |
| **ORB: size_penalty** | `ctx.size_penalty` affects qty computation | Not in sizing_inputs | Position sizing audit incomplete. |
| **ORB: rearms_used** | Available on `ctx` | Not in strategy_params for missed logs | Cannot distinguish first attempt from re-entry. |

### 4.3 MINOR Gaps

| Gap | Details |
|-----|---------|
| **ORB emit_heartbeat via kit** | Heartbeat goes through PG store, not through kit.emit_heartbeat(). Kit heartbeat capability is unused by ORB. |
| **ORB: no log_error in engine.py** | Engine never calls `kit.log_error()` — only main.py does. Strategy-level errors (e.g., order planning failures) are not recorded as structured error events. |
| **IARIC: flow_reversal_flag** | Available per-symbol but not in entry meta. |
| **Both: order fill_details** | TradeEvent has `entry_fill_details` / `exit_fill_details` fields but neither engine populates them via meta. |
| **Both: order_book_depth_at_entry** | TradeEvent field exists; orderbook context is logged separately via `on_orderbook_context()` but NOT linked into the TradeEvent record itself. |
| **Both: market_conditions_at_entry** | TradeEvent field exists but never populated. |

---

## 5. Summary of the Data Flow

```
Strategy Engine
  ├─ on_fill(ENTRY) ──────────► trade_recorder.record_entry(meta={...})
  │                                 └──► InstrumentedTradeRecorder
  │                                       ├──► PG: trades table
  │                                       └──► kit.log_entry()
  │                                             └──► trade_logger.log_entry()
  │                                                   ├──► regime_classifier.current_regime()
  │                                                   ├──► snapshot_service.capture_now()
  │                                                   ├──► TradeEvent(process_quality_score=100)
  │                                                   └──► write JSONL + sidecar relay
  │
  ├─ on_fill(EXIT) ───────────► trade_recorder.record_exit(mfe_r, mae_r, meta={...})
  │                                 └──► InstrumentedTradeRecorder
  │                                       ├──► PG: trades + trade_marks tables
  │                                       └──► kit.log_exit()
  │                                             └──► trade_logger.log_exit()
  │                                                   ├──► compute PnL, slippage, MFE/MAE pct
  │                                                   ├──► compute exit_efficiency
  │                                                   ├──► process_scorer.score_trade() → quality + root_causes
  │                                                   ├──► queue post_exit backfill
  │                                                   └──► write JSONL + sidecar relay
  │
  ├─ on_bar/on_quote ─────────► _update_position_excursions()  (MFE/MAE tracking)
  │                             _emit_indicator_snapshot()      (if enabled)
  │
  ├─ entry blocked ───────────► _log_missed()
  │                                 └──► kit.log_missed()
  │                                       └──► missed_logger.log_missed()
  │                                             ├──► regime_classifier.current_regime()
  │                                             └──► write JSONL + sidecar relay
  │
  ├─ order lifecycle ─────────► _log_order_event()
  │                                 └──► kit.on_order_event()
  │                                       └──► order_logger.log_order()
  │
  └─ entry/exit fills ────────► _log_orderbook_context()
                                    └──► kit.on_orderbook_context()
                                          └──► orderbook_logger.log_orderbook()

main.py
  ├─ runtime errors ──────────► kit.log_error()
  │                                 └──► error_logger.log_error()
  │
  └─ heartbeat (30s) ─────────► PG emit_heartbeat() (separate path, NOT via kit)
```

---

## 6. InstrumentationKit Configuration

**File**: `instrumentation/src/bootstrap.py`

```python
class InstrumentationManager:
    def __init__(self, oms, strategy_id, strategy_type):
        self._config = _load_config(strategy_id, strategy_type)
        self.bot_id = self._config["bot_id"]

        self.error_logger = ErrorLogger(self._config)
        self.snapshot_service = MarketSnapshotService(self._config, None)
        self.process_scorer = ProcessScorer()         # from process_scoring_rules.yaml
        self.trade_logger = TradeLogger(
            self._config, self.snapshot_service,
            process_scorer=self.process_scorer,
            strategy_type=self._strategy_type,
            error_logger=self.error_logger,
        )
        self.missed_logger = MissedOpportunityLogger(self._config, self.snapshot_service, ...)
        self.order_logger = OrderLogger(self._config, strategy_type=...)
        self.experiment_registry = ExperimentRegistry()
        self.daily_builder = DailySnapshotBuilder(self._config, ...)
        self.regime_classifier = RegimeClassifier(data_provider=None)
        self.sidecar = Sidecar(self._config)
```

Config loaded from `instrumentation/config/instrumentation_config.yaml`:
- `data_dir`: where JSONL files are written
- `sidecar`: relay URL, HMAC secret, flush interval
- `market_snapshots`: symbols for snapshot service (default: SPY, QQQ, IWM)
- `bot_id`, `bot_name`, `strategy_type`, `data_source_id`

---

## 7. Recommendations for Closing Gaps

**High priority** (data exists, just not wired):
1. Add `concurrent_positions`, `drawdown_pct`, `drawdown_tier` to ORB `record_entry()` meta
2. Add `fees_paid` to both engines' `record_exit()` meta (from broker fill event)
3. Add `entry_latency_ms` / `exit_latency_ms` by computing deltas from OMS event timestamps
4. Add `session_transitions` to ORB `record_exit()` meta (IARIC already does this)

**Medium priority** (enriches analysis):
5. Add `bar_id` and `signal_evolution` to entry meta
6. Expand ORB `signal_factors` to include vwap, imbalance_90s, gap_pct, or_pct
7. Add `size_penalty` and `rearms_used` to ORB strategy_params
8. Call `kit.log_error()` from engine.py for strategy-level errors

**Low priority** (structural improvements):
9. Populate `entry_fill_details` / `exit_fill_details` from OMS fill events
10. Link orderbook context into TradeEvent records (currently logged separately)
11. Route heartbeat through kit.emit_heartbeat() for unified event pipeline
