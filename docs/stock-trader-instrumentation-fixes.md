# Stock Bot Instrumentation: Live VPS Change Notes

Precise file-targeted changes for the deployed stock_trader bot on VPS.
These changes are required to connect stock bot instrumentation to the TA pipeline.

Items marked **[DONE]** are already implemented in the reference code
(`_references/trading/strategies/stock/instrumentation/`). Verify the deployed
VPS code matches — if it does, no action needed for those items.

---

## B1. Relay Connectivity (1 change + 2 verify-only)

### 1. Verify relay URL in instrumentation config — **[DONE]**

**File:** `instrumentation/config/instrumentation_config.yaml`

Reference code already uses localhost (line 23):
```yaml
relay_url: "http://127.0.0.1:8001/events"
```

The sidecar also supports env var override (`sidecar.py` line 77):
```python
raw_url = os.environ.get("INSTRUMENTATION_RELAY_URL") or sidecar_config.get("relay_url", "")
```

**Action:** Verify deployed VPS code matches. If it still has the old
`host.docker.internal` URL, update to `127.0.0.1`. Set `INSTRUMENTATION_RELAY_URL`
env var if the relay runs on a different host.

### 2. Register stock_trader HMAC secret on relay VPS

**File:** `/opt/trading-relay/secrets.json` (relay VPS)

Add entry:
```json
{
  "stock_trader": "<HMAC_HEX_SECRET>"
}
```

Generate with: `python -c "import secrets; print(secrets.token_hex(32))"`

Set the same hex value as `INSTRUMENTATION_HMAC_SECRET` env var on the stock bot VPS.
The sidecar reads this via `hmac_secret_env` config key (`sidecar.py` line 87).
Without it, events are sent **unsigned** and the relay will reject them (401).

### 3. Verify bot_id unification in bootstrap — **[DONE]**

**File:** `instrumentation/src/bootstrap.py`

Reference code already has `_BOT_ID = "stock_trader"` (line 48) and
`config["bot_id"] = _BOT_ID` (line 84). Strategy-level differentiation
uses `strategy_id` field (iaric, us_orb, alcb), not `bot_id`.

**Action:** Verify deployed VPS code matches the reference. No code change
needed if it does.

---

## B2. Config & Portfolio Instrumentation (2 changes + 1 verify-only)

### 4. Add ALCB entry to simulation_policies.yaml

**File:** `instrumentation/config/simulation_policies.yaml`

`iaric` and `us_orb` entries already exist. Only `alcb` is missing (falls back
to `default` which has wrong fee/slippage values). Add using the same field
schema as existing entries:

```yaml
alcb:
  entry_fill_model: "mid"
  slippage_model: "fixed_bps"
  slippage_bps: 3.0
  fees_included: false
  fee_bps: 1.0
  tp_sl_logic: "atr_multiple"
  tp_value: 2.5        # trailing ATR — wider than IARIC's 2.0×
  sl_value: 1.0
  max_hold_bars: 156    # 2 trading days
```

Adjust `tp_value` and `sl_value` to match ALCB's actual trailing ATR parameters.

### 5. Add ALCB entry to process_scoring_rules.yaml

**File:** `instrumentation/config/process_scoring_rules.yaml`

`iaric` and `us_orb` entries already exist. Only `alcb` is missing. Add using
the same field schema (includes fields the global defaults don't cover):

```yaml
alcb:
  preferred_regimes: ["trending_up", "mean_reverting"]
  adverse_regimes: ["choppy", "breakdown"]
  max_hold_bars: 156
  expected_slippage_bps: 3
  min_signal_strength: 0.40
  strong_signal_threshold: 0.60
```

### 6. Portfolio rule event emission — **[DONE]**

**File:** `libs/oms/services/factory.py` (shared OMS library)

`_make_portfolio_rule_logger()` (line 131) creates a JSONL-writing callback to
`instrumentation/data/portfolio_rules/rules_{date}.jsonl`. It's wired via
`on_rule_event` in both OMS factory paths (`build_oms_service` line 449,
`build_multi_oms_service` line 781). The `PortfolioRuleChecker` calls this
callback when rules (directional cap, symbol collision, priority headroom)
trigger.

The sidecar maps `portfolio_rules/` → `portfolio_rule` event type (line 28)
and forwards them to the relay.

**Action:** Verify deployed OMS library matches reference. No code change needed.

---

## B3. Strategy Data Gaps (2 changes + 4 verify-only)

### 7. Entry metadata fields — **[DONE]**

**File:** `instrumentation/src/trade_logger.py`

Reference code already has `concurrent_positions`, `drawdown_pct`, and `bar_id`
as parameters in `log_entry()` (lines 247-256) and `TradeEvent` dataclass fields.

**Action:** Verify deployed VPS code matches. Verify the calling engine code
actually passes these values (not just that the logger accepts them).

### 8. `fees_paid` in exit recording — **[DONE]**

**File:** `instrumentation/src/trade_logger.py`

Reference code already has `fees_paid` as a parameter in `log_exit()` (line 387)
with default `0.0`.

**Action:** Verify deployed code matches and the engine passes the actual
broker fill commission + fee values.

### 9. Entry/exit latency — **[DONE]**

**File:** `instrumentation/src/trade_logger.py`

Reference code has `entry_latency_ms` and `exit_latency_ms` as `TradeEvent`
dataclass fields (lines 169-170) and parameters in `log_entry()`/`log_exit()`.

**Action:** Verify deployed code matches and the engine computes latency from
`(fill.timestamp - signal.timestamp).total_seconds() * 1000`.

### 10. Session transitions in ORB exit — **[DONE]**

**File:** `instrumentation/src/trade_logger.py`

Reference code has `session_transitions` as a `TradeEvent` field (line 182) and
`log_exit()` parameter (line 395).

**Action:** Verify deployed code matches and the ORB engine passes this
(IARIC already does).

### 11. Add signal factors to ORB `_entry_signal_factors()`

**File:** `us_orb/engine.py` — `_entry_signal_factors()` method (lines 274-306)

Currently returns only 5 factors: `pre_score`, `quality_score`, `surge`,
`rvol_1m`, `relative_strength_5m`. The values below exist in `SymbolContext`
but are **not forwarded** to the signal factor output. All 4 need adding:

```python
# Add to _entry_signal_factors() return list:
{
    "factor_name": "vwap_distance",
    "factor_value": (ctx.last_price - ctx.vwap) / ctx.vwap if ctx.vwap else 0.0,
    "threshold": 0.0,
    "contribution": 0.0,
},
{
    "factor_name": "imbalance_90s",
    "factor_value": float(ctx.imbalance_90s or 0.0),
    "threshold": 0.0,
    "contribution": float(ctx.imbalance_90s or 0.0),
},
{
    "factor_name": "gap_pct",
    "factor_value": float(ctx.gap_pct or 0.0),
    "threshold": 0.0,
    "contribution": float(ctx.gap_pct or 0.0),
},
{
    "factor_name": "or_pct",
    "factor_value": float(ctx.or_pct or 0.0),
    "threshold": 0.0,
    "contribution": float(ctx.or_pct or 0.0),
},
```

Note: `imbalance_90s` IS already in the indicator snapshot (`_emit_indicator_snapshot`)
but that's a separate instrumentation channel — signal factors need it too for
TA's factor attribution analysis.

### 12. Add fields to ORB `_log_missed()` strategy_params

**File:** `us_orb/engine.py` — all `_log_missed()` call sites

The `_log_missed()` method accepts `strategy_params` (line 382) but most call
sites pass minimal or no strategy_params. Both values exist in `SymbolContext`
(`models.py` lines 194, 208) but are never forwarded. Add to relevant call sites:

```python
strategy_params={
    "rearms_used": ctx.rearms_used,
    "size_penalty": ctx.size_penalty,
    # include existing params if present at that call site
},
```

---

## Action Summary

| Item | Status | Action Required |
|------|--------|-----------------|
| 1. Relay URL | DONE | Verify deployed matches reference |
| 2. HMAC secret | TODO | Register on relay VPS + set env var |
| 3. bot_id | DONE | Verify only |
| 4. simulation_policies | TODO | Add ALCB entry (iaric/us_orb exist) |
| 5. scoring_rules | TODO | Add ALCB entry (iaric/us_orb exist) |
| 6. Portfolio rule events | DONE | Verify OMS library matches |
| 7. Entry meta fields | DONE | Verify engine passes values |
| 8. fees_paid | DONE | Verify engine passes values |
| 9. Latency fields | DONE | Verify engine passes values |
| 10. session_transitions | DONE | Verify ORB engine passes values |
| 11. ORB signal factors | TODO | Add all 4 to `_entry_signal_factors()` |
| 12. ORB missed params | TODO | Add 2 fields to `_log_missed()` call sites |

## Verification After Deployment

1. Check relay logs for incoming events: `journalctl -u trading-relay -f`
2. Verify HMAC auth succeeds (no 403 errors)
3. Confirm events appear in TA raw dir: `ls data/raw/$(date +%Y-%m-%d)/stock_trader/`
4. Run TA daily rebuild and verify portfolio files generated
5. Check `fees_paid`, `entry_latency_ms` fields appear in new trade events
6. Verify `concurrent_positions`, `drawdown_pct` are non-null in entry events
7. Verify `portfolio_rule` events appear in raw dir after coordinator caps trigger
