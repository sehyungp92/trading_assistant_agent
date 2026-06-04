# Trading Assistant Changes Required for Schema Alignment

**Date**: 2026-04-18
**Related**: Audit findings #3, #4, #10 from `docs/2026-04-18-live-paper-trading-audit.md`
**Status**: Pending implementation in trading_assistant repo

These changes must be applied to the trading_assistant codebase to complete the
schema alignment. The k_stock_trader side (changes 1-7) has been implemented.

---

## Change 8: `orchestrator/worker.py` — Re-inject `bot_id` into stored payload

### Problem

The brain's `_extract_persistable_payload()` strips envelope keys including
`bot_id`. The worker's `_normalize_payload()` (line 161-177) only re-injects
`event_type` and `exchange_timestamp`. After our emitter changes, `bot_id` is
now inside the payload too — but as a safety net for edge cases (pre-migration
events, transport issues), it should also be injected in `_persist_raw_event`.

### Location

File: `orchestrator/worker.py`, method `_persist_raw_event` (line 117)

### Change

After line 126 (`payload = self._normalize_payload(details)`), add:

```python
        # Ensure bot_id survives envelope stripping
        if isinstance(payload, dict) and "bot_id" not in payload:
            payload["bot_id"] = action.bot_id
```

### Rationale

`action.bot_id` is always set by the brain from the original event envelope
(verified — used at line 128: `bot_dir = ... / action.bot_id`). This ensures
`bot_id` is present in the stored payload even if the emitter-side field was
stripped during transport.

---

## Change 9: `orchestrator/handlers.py` — Merge multiple daily_snapshot records

### Problem

Line 3799-3801 currently takes the last daily_snapshot record:

```python
daily_snapshots = self._load_raw_json_records(bot_raw, "daily_snapshot")
if daily_snapshots:
    kwargs["daily_snapshot"] = daily_snapshots[-1]
```

With the k_stock_trader fix (change #4 — per-strategy `bot_id` via uppercase
`per_strategy_summary` keys), multiple strategies may emit daily snapshots to
the same bot directory. The `[-1]` indexing means whichever strategy snapshot
arrives last overwrites the others.

### Location

File: `orchestrator/handlers.py`, in the daily rebuild method, around line 3799

### Change

Replace the last-one-wins logic with a merge:

```python
daily_snapshots = self._load_raw_json_records(bot_raw, "daily_snapshot")
if daily_snapshots:
    kwargs["daily_snapshot"] = self._merge_daily_snapshots(daily_snapshots)
```

Add a new static method to the handler class:

```python
@staticmethod
def _merge_daily_snapshots(snapshots: list[dict]) -> dict:
    """Merge multiple daily_snapshot records from different strategies.

    Each strategy emits one snapshot with per_strategy_summary containing
    a single key (its own strategy_id). Merge by:
    - Combining per_strategy_summary dicts
    - Summing additive metrics (trades, wins, losses, pnl, missed, errors)
    - Taking the latest value for non-additive fields (account_equity, etc.)
    """
    if len(snapshots) == 1:
        return snapshots[0]

    merged = dict(snapshots[-1])  # start from latest for non-additive fields

    # Merge per_strategy_summary from all snapshots
    combined_pss = {}
    for snap in snapshots:
        pss = snap.get("per_strategy_summary", {})
        combined_pss.update(pss)
    merged["per_strategy_summary"] = combined_pss

    # Sum additive integer/float metrics across all snapshots
    additive_keys = [
        "total_trades", "win_count", "loss_count", "missed_count",
        "missed_would_have_won", "error_count",
    ]
    additive_float_keys = ["gross_pnl", "net_pnl"]

    for key in additive_keys:
        merged[key] = sum(s.get(key, 0) for s in snapshots)
    for key in additive_float_keys:
        merged[key] = sum(s.get(key, 0.0) for s in snapshots)

    # Recompute derived metrics
    total = merged.get("total_trades", 0)
    wins = merged.get("win_count", 0)
    merged["win_rate"] = (wins / total * 100) if total > 0 else 0.0

    return merged
```

### Note on portfolio-level aggregation

There is also a portfolio-level aggregation path (lines 3829-3870) that
`extend()`s daily_snapshots across all bots. That path processes all records
(no `[-1]`) so it doesn't suffer from last-one-wins. After change #7 (uppercase
`per_strategy_summary` keys), the keys from different strategies won't collide
in that path either. No change needed there.
