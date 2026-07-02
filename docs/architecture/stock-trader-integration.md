# stock_trader Integration with trading_assistant

**Target repo:** `stock_trader` (deployed on VPS)
**Target files:** `instrumentation/config/simulation_policies.yaml`, `instrumentation/src/bootstrap.py`
**Relay:** `swing_trader` VPS — `/opt/trading-relay/secrets.json`

This document describes the changes needed in the stock_trader and relay repos
to complete integration with the trading_assistant orchestrator.

## Architecture

The stock_trader repo contains two US equity strategies (IARIC, US_ORB) that
share a single `bot_id: stock_trader`. Individual events carry a `strategy_id`
field to distinguish which strategy generated them. This matches k_stock_trader's
pattern (4 strategies under one bot_id across 2 VPSes).

All events flow: VPS sidecar → relay (`/opt/trading-relay/`) → orchestrator poll.

## Current State

The stock_trader instrumentation suite is fully compatible with the
trading_assistant event schema:
- Same root cause taxonomy (21 values)
- Same EventMetadata structure (event_id, bot_id, exchange_timestamp, etc.)
- Same event types (trade, missed_opportunity, daily_snapshot, error, heartbeat, etc.)
- Already emits both field naming conventions (e.g., `spread_at_entry_bps` + `spread_at_entry`)

What remains: bot_id unification, sidecar config, simulation policies, and relay auth.

## Required Changes

### 1. Relay `shared_secrets` — Register stock_trader

**Target repo:** `swing_trader`
**Target file:** `/opt/trading-relay/secrets.json` (on the relay VPS)

The relay loads all bot HMAC secrets from a single JSON file via
`run_relay.py` (`RELAY_SECRETS_FILE` env var, defaults to
`/opt/trading-relay/secrets.json`). It does NOT use per-bot env vars.

Generate a secret and add one entry for stock_trader:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Add to `secrets.json`:

```json
{
    "k_stock_trader": "<existing>",
    "swing_trader": "<existing>",
    "momentum_trader": "<existing>",
    "stock_trader": "<generated-hex-secret>"
}
```

The relay's `HMACAuth` matches `bot_id` from the event payload against the
keys in this file.

### 2. Unify bot_id — Change bootstrap.py

**Target repo:** `stock_trader`
**Target file:** `instrumentation/src/bootstrap.py`

Currently, `_BOT_HMAC_ENV_MAP` (line 44) overrides `bot_id` per-strategy to
`IARIC_v1` / `US_ORB_v1`. Change to use a single `bot_id: stock_trader` and
populate `strategy_id` on each event instead.

Replace:
```python
_BOT_HMAC_ENV_MAP = {
    "IARIC_v1": "INSTRUMENTATION_HMAC_SECRET_IARIC",
    "US_ORB_v1": "INSTRUMENTATION_HMAC_SECRET_US_ORB",
}
```

With:
```python
# Single bot_id for all strategies; strategy_id distinguishes them in events
_BOT_ID = "stock_trader"
_HMAC_SECRET_ENV = "INSTRUMENTATION_HMAC_SECRET"
```

Ensure each event includes `strategy_id: "iaric"` or `strategy_id: "us_orb"`
in its payload. The trading_assistant schema accepts `strategy_id: str = ""`
on TradeEvent and MissedOpportunityEvent.

### 3. Sidecar Configuration — Relay URL and HMAC secret

**Target repo:** `stock_trader`
**Target file:** VPS environment (no `.env.example` exists in the repo — set in host env or Docker Compose)

Verify the relay URL in `instrumentation/config/instrumentation_config.yaml`
(`sidecar.relay_url`). On Linux VPS, change `host.docker.internal` to
`localhost` or the host's LAN IP.

Set one shared HMAC secret (replaces the old per-strategy secrets):

```bash
# Must match secrets.json["stock_trader"] on the relay VPS
INSTRUMENTATION_HMAC_SECRET=<same-value-as-secrets.json["stock_trader"]>
```

Verify the sidecar starts and forwards events:
```bash
docker compose -f infra/docker-compose.yml logs -f strategy_iaric 2>&1 | grep sidecar
# Should see: "Forwarded N events to relay"
```

### 4. Simulation Policies — Add per-strategy entries

**Target repo:** `stock_trader`
**Target file:** `instrumentation/config/simulation_policies.yaml`

The current file has policies for NQ futures strategies (`helix`, `nqdtc`,
`vdubus`) which don't apply to US equities. Without matching policies, the
`MissedOpportunityLogger` falls back to `default` — which uses generic
slippage/fee assumptions that may not reflect IBKR US equity execution.

Add two new policy entries keyed by strategy_id:

```yaml
iaric:
  entry_fill_model: mid          # IBKR smart routing typically fills near mid
  slippage_model: fixed_bps
  slippage_bps: 3.0              # US large-cap equities: ~3 bps typical
  fees_included: true
  fee_bps: 1.0                   # IBKR tiered: ~$0.005/share ≈ 1 bps on $50 stock
  tp_sl_logic: atr_based
  tp_value: 2.0                  # 2× ATR take profit
  sl_value: 1.0                  # 1× ATR stop loss
  max_hold_bars: 78              # Intraday: 6.5h × 12 bars/h (5-min bars)

us_orb:
  entry_fill_model: mid
  slippage_model: fixed_bps
  slippage_bps: 5.0              # ORB entries in first 15 min: wider spreads
  fees_included: true
  fee_bps: 1.0
  tp_sl_logic: atr_based
  tp_value: 1.5                  # ORB: tighter targets
  sl_value: 1.0
  max_hold_bars: 78              # Intraday
```

**Note:** These values are starting estimates. After collecting real trade data,
refine slippage_bps from actual `entry_slippage_bps` / `exit_slippage_bps`
measurements in the curated data.

### 5. Daily Snapshot Emission — Verify Market Close Timing

**Target repo:** `stock_trader`
**Target file:** `instrumentation/src/bootstrap.py`

The `DailySnapshotBuilder` builds snapshots via periodic checkpoints
(`_maybe_checkpoint_daily_snapshot()` every 300s by default) and emits a
`snapshot_kind: "final"` snapshot at end-of-day.

Verify that the strategy's main loop or shutdown sequence calls the final
snapshot at or after NYSE close (16:00 ET). If using Docker, the container
should remain running past 16:00 ET so the final snapshot is emitted.

Check the daily snapshot appears in the sidecar output:
```bash
ls instrumentation/data/daily/
# Should contain: daily_YYYY-MM-DD.json with snapshot_kind: "final"
```

The trading_assistant scheduler will trigger daily analysis at 17:00 ET
(market_close 16:00 + 60 min delay), so the final snapshot must be emitted
before then.

## Verification Checklist

After all changes:

1. **Relay accepts events** — Check relay logs for successful auth from `stock_trader`
2. **Sidecar forwards** — `docker compose logs` shows "Forwarded N events"
3. **Events carry strategy_id** — trade events have `strategy_id: "iaric"` or `"us_orb"`
4. **Orchestrator receives** — trading_assistant logs show stock_trader events in queue
5. **Daily snapshot present** — `data/curated/YYYY-MM-DD/stock_trader/summary.json` exists after analysis
6. **Simulation policies used** — missed opportunity events show correct slippage_bps per strategy
7. **Telegram report arrives** — daily analysis for stock_trader triggers report at ~17:00 ET

## Compatibility

All changes are additive:
- Relay: new secret doesn't affect existing bots
- Sidecar: single HMAC secret simplifies config
- Simulation policies: new entries don't change existing `default` policy
- Daily snapshot: checkpoint logic is already built in
- Schema: `strategy_id` field is optional with empty string default
