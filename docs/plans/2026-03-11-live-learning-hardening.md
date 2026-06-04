# Live Learning Hardening Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Harden the relay-to-learning loop so live and paper trading decisions are driven by accurate measurements, correct event dating, and implementation states that reflect reality.

**Architecture:** The work stays inside the existing relay, worker, and feedback-loop architecture. We will fix how events are persisted from the relay, how predictions and outcomes are evaluated, and how approval failures roll back so the learning memory only absorbs true implementations and correctly dated evidence.

**Tech Stack:** Python, FastAPI, Pydantic, asyncio, pytest, JSONL, SQLite

---

### Task 1: Fix Prediction Evaluation Baselines

**Files:**
- Modify: `skills/prediction_tracker.py`
- Test: `tests/test_prediction_tracker.py`

**Step 1: Write the failing test**

```python
def test_evaluate_uses_baseline_and_target_dates(tmp_path):
    tracker = PredictionTracker(tmp_path / "findings")
    tracker.record_predictions("2026-03-01", [
        AgentPrediction(bot_id="bot1", metric="pnl", direction="improve", confidence=0.8, timeframe_days=7),
    ])
    # baseline day worse than target day -> should be correct
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_prediction_tracker.py -k baseline -v`
Expected: FAIL because evaluation still searches relative to `datetime.now()`.

**Step 3: Write minimal implementation**

```python
def _load_metric_change(...):
    baseline_date = issued_date
    target_date = issued_date + timedelta(days=timeframe_days)
    return target_value - baseline_value
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_prediction_tracker.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add tests/test_prediction_tracker.py skills/prediction_tracker.py
git commit -m "fix: evaluate predictions against true baseline windows"
```

### Task 2: Prefer Net PnL in Outcome Measurement

**Files:**
- Modify: `skills/auto_outcome_measurer.py`
- Test: `tests/test_auto_outcome_measurer.py`

**Step 1: Write the failing test**

```python
def test_measure_prefers_net_pnl(tmp_path):
    # summary.json contains both gross_pnl and net_pnl
    # outcome measurement should use net_pnl first
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_auto_outcome_measurer.py -k net_pnl -v`
Expected: FAIL because the measurer sums `gross_pnl`.

**Step 3: Write minimal implementation**

```python
before_pnl = sum(self._summary_pnl(s) for s in before_summaries)
after_pnl = sum(self._summary_pnl(s) for s in after_summaries)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_auto_outcome_measurer.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add tests/test_auto_outcome_measurer.py skills/auto_outcome_measurer.py
git commit -m "fix: measure outcomes using net pnl"
```

### Task 3: Preserve Correct Trading Dates for Relay Events

**Files:**
- Modify: `orchestrator/orchestrator_brain.py`
- Modify: `orchestrator/worker.py`
- Modify: `orchestrator/app.py`
- Test: `tests/test_enriched_event_pipeline.py`

**Step 1: Write the failing test**

```python
async def test_worker_persists_events_using_bot_trading_date(...):
    # event timestamp near UTC midnight should persist under the bot's local trading date
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_enriched_event_pipeline.py -k trading_date -v`
Expected: FAIL because worker uses `datetime.now(timezone.utc)`.

**Step 3: Write minimal implementation**

```python
def _raw_event_date(...):
    if payload_date:
        return payload_date
    if exchange_timestamp and bot_config:
        return bot_trading_date(bot_config.timezone, exchange_dt)
    return exchange_dt.strftime("%Y-%m-%d")
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_enriched_event_pipeline.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add tests/test_enriched_event_pipeline.py orchestrator/orchestrator_brain.py orchestrator/worker.py orchestrator/app.py
git commit -m "fix: persist relay events under correct trading dates"
```

### Task 4: Feed Relay Daily Snapshots and Coordinator Events into Curated Data

**Files:**
- Modify: `orchestrator/handlers.py`
- Test: `tests/test_enriched_event_pipeline.py`

**Step 1: Write the failing test**

```python
def test_build_enriched_curated_uses_daily_snapshot_and_coordinator_events(tmp_path):
    # raw relay payloads should produce summary enrichment and coordinator_impact.json
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_enriched_event_pipeline.py -k coordinator -v`
Expected: FAIL because `_build_enriched_curated()` ignores those raw files.

**Step 3: Write minimal implementation**

```python
daily_snapshot = _load_single_jsonl_object(...)
coordination_events = _load_jsonl_records(...)
builder.write_curated(..., daily_snapshot=daily_snapshot, coordination_events=coordination_events)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_enriched_event_pipeline.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add tests/test_enriched_event_pipeline.py orchestrator/handlers.py
git commit -m "feat: use relay snapshot and coordinator data in curated outputs"
```

### Task 5: Roll Back Suggestion State on Approval Failure

**Files:**
- Modify: `skills/approval_handler.py`
- Test: `tests/test_approval_handler.py`

**Step 1: Write the failing test**

```python
async def test_approve_pr_failure_reverts_suggestion_status(components):
    # suggestion should not remain IMPLEMENTED when PR creation fails
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_approval_handler.py -k reverts_suggestion_status -v`
Expected: FAIL because the suggestion is marked implemented before PR success.

**Step 3: Write minimal implementation**

```python
implemented_marked = False
...
if result.failure:
    self._restore_suggestion_status(...)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_approval_handler.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add tests/test_approval_handler.py skills/approval_handler.py
git commit -m "fix: roll back suggestion implementation on approval failure"
```

### Task 6: Write the Review and Improvement Report

**Files:**
- Create: `docs/2026-03-11-live-learning-review.md`

**Step 1: Draft findings and evidence**

```markdown
- Critical bugs with file/line evidence
- Live trading robustness risks
- Learning loop gaps
- High-confidence fixes implemented
- Test-only recommendations for uncertain ideas
```

**Step 2: Verify report references the implemented fixes and remaining risks**

Run: `pytest tests/test_prediction_tracker.py tests/test_auto_outcome_measurer.py tests/test_enriched_event_pipeline.py tests/test_approval_handler.py -q`
Expected: PASS

**Step 3: Commit**

```bash
git add docs/2026-03-11-live-learning-review.md
git commit -m "docs: add live learning review and hardening report"
```
