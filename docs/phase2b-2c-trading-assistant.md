# Phase 2B/2C — Trading Assistant (Orchestrator)

Implementation instructions for the `trading_assistant` repo. This covers the
orchestrator-side ingestion, analysis, and A/B testing lifecycle for the enriched
events emitted by the three bot repos.

---

## Current State

### Event Routing (`orchestrator/orchestrator_brain.py`)
- 19 event types handled in `_handlers` dict
- `parameter_change` already handled — safety-critical params get `ALERT_IMMEDIATE`, others → `QUEUE_FOR_DAILY`
- No handlers for `indicator_snapshot`, `orderbook_context`, or `filter_decision`

### Data Pipeline (`skills/build_daily_metrics.py`)
- `DailyMetricsBuilder` produces 17+ curated files per bot per day
- `write_curated()` already handles `experiment_data.json` via `build_experiment_breakdown()`
- No builder methods for filter decisions, indicator snapshots, or order book data

### Prompt Assembler (`analysis/prompt_assembler.py`)
- `_CURATED_FILES` list has 17 entries
- `_INSTRUCTIONS` string has 26 analysis steps
- No references to enriched event files

### Strategy Engine (`analysis/strategy_engine.py`)
- 12 detectors in `build_report()` covering parameters, filters, regimes, alpha decay, etc.
- No microstructure detector (bid/ask imbalance, spread patterns)

### Telegram Renderer (`comms/telegram_renderer.py`)
- `TelegramRenderer` with `render_alert`, `render_daily_report_with_keyboard`, `render_weekly_summary`, `render_approval_request`
- No experiment proposal or result renderers

### Config (`orchestrator/config.py`)
- `AppConfig` has 3 feature flags: `autonomous_enabled`, `adaptive_thresholds_enabled`, `deployment_monitoring_enabled`
- No `ab_testing_enabled` flag

### Scheduler (`orchestrator/scheduler.py`)
- `SchedulerConfig` with 17 parameters
- `create_scheduler_jobs()` takes 18 optional function callbacks
- No experiment check job

### Deleted Files (recoverable from git HEAD)
- `schemas/enriched_events.py` — IndicatorSnapshot, OrderBookContext, FilterDecisionEvent, ParameterChangeEvent, ChangeSource
- `schemas/experiments.py` — ExperimentConfig, ExperimentResult, VariantMetrics, ExperimentStatus, ExperimentType
- `skills/experiment_manager.py` — Full ExperimentManager with Welch's t-test
- `skills/experiment_config_generator.py` — ExperimentConfigGenerator with YAML + PR generation

---

## Phase 2B — Enriched Event Ingestion

### 2B.1: Restore `schemas/enriched_events.py`

Restore the file from git HEAD. Content is unchanged:

```bash
git show HEAD:schemas/enriched_events.py > schemas/enriched_events.py
```

Verify the file contains these models:
- `IndicatorSnapshot` — bot_id, pair, timestamp, indicators dict, signal_name, signal_strength, decision, context
- `OrderBookContext` — bot_id, pair, timestamp, best_bid/ask, spread_bps, bid/ask_depth_10bps, imbalance_ratio computed_field
- `FilterDecisionEvent` — bot_id, pair, timestamp, filter_name, passed, threshold, actual_value, margin_pct computed_field
- `ChangeSource` enum — PR_MERGE, MANUAL, HOT_RELOAD, EXPERIMENT
- `ParameterChangeEvent` — bot_id, param_name, old/new_value, change_source, timestamp, commit_sha, pr_url

### 2B.2: Add 3 Event Handlers to `orchestrator/orchestrator_brain.py`

Add three new handler methods and register them in `_handlers`:

```python
def _handle_indicator_snapshot(self, event_id: str, bot_id: str, event: dict) -> list[Action]:
    return [Action(type=ActionType.QUEUE_FOR_DAILY, event_id=event_id, bot_id=bot_id)]

def _handle_orderbook_context(self, event_id: str, bot_id: str, event: dict) -> list[Action]:
    return [Action(type=ActionType.QUEUE_FOR_DAILY, event_id=event_id, bot_id=bot_id)]

def _handle_filter_decision(self, event_id: str, bot_id: str, event: dict) -> list[Action]:
    return [Action(type=ActionType.QUEUE_FOR_DAILY, event_id=event_id, bot_id=bot_id)]
```

Add to `_handlers` dict:

```python
_handlers: dict = {
    # ... existing 19 entries ...
    "indicator_snapshot": _handle_indicator_snapshot,
    "orderbook_context": _handle_orderbook_context,
    "filter_decision": _handle_filter_decision,
}
```

### 2B.3: Add 3 Builder Methods to `skills/build_daily_metrics.py`

Add these methods to `DailyMetricsBuilder`:

#### `build_filter_decision_summary()`

```python
def build_filter_decision_summary(self, filter_events: list[dict]) -> dict:
    """Summarize per-filter pass/block decisions from FilterDecisionEvent data.

    Args:
        filter_events: Raw dicts from filter_decision event payloads.

    Returns:
        Dict with per-filter pass/block counts, avg margin_pct, near-miss rates.
    """
    from collections import defaultdict

    per_filter: dict[str, dict] = defaultdict(lambda: {
        "pass_count": 0,
        "block_count": 0,
        "margins": [],
        "near_misses": 0,  # |margin_pct| < 10%
    })

    for evt in filter_events:
        payload = evt.get("payload", evt)
        if isinstance(payload, str):
            import json as _json
            try:
                payload = _json.loads(payload)
            except Exception:
                continue

        name = payload.get("filter_name", "unknown")
        passed = payload.get("passed", True)
        threshold = payload.get("threshold", 0)
        actual = payload.get("actual_value", 0)

        bucket = per_filter[name]
        if passed:
            bucket["pass_count"] += 1
        else:
            bucket["block_count"] += 1

        # Compute margin_pct
        margin_pct = 0.0
        if threshold != 0:
            margin_pct = ((actual - threshold) / abs(threshold)) * 100
        bucket["margins"].append(margin_pct)

        if abs(margin_pct) < 10:
            bucket["near_misses"] += 1

    summary = {}
    for name, data in per_filter.items():
        margins = data["margins"]
        summary[name] = {
            "pass_count": data["pass_count"],
            "block_count": data["block_count"],
            "total": data["pass_count"] + data["block_count"],
            "block_rate": data["block_count"] / (data["pass_count"] + data["block_count"]) if (data["pass_count"] + data["block_count"]) > 0 else 0,
            "avg_margin_pct": sum(margins) / len(margins) if margins else 0,
            "near_miss_count": data["near_misses"],
            "near_miss_rate": data["near_misses"] / len(margins) if margins else 0,
        }

    return {
        "bot_id": self.bot_id,
        "date": self.date,
        "filters": summary,
        "total_evaluations": sum(d["pass_count"] + d["block_count"] for d in per_filter.values()),
    }
```

#### `build_indicator_snapshot_summary()`

```python
def build_indicator_snapshot_summary(self, indicator_events: list[dict]) -> dict:
    """Summarize indicator values at signal evaluation points.

    Args:
        indicator_events: Raw dicts from indicator_snapshot event payloads.

    Returns:
        Dict with per-indicator min/max/mean/count and per-decision breakdowns.
    """
    from collections import defaultdict

    indicator_values: dict[str, list[float]] = defaultdict(list)
    decision_counts: dict[str, int] = defaultdict(int)
    signal_strengths: list[float] = []

    for evt in indicator_events:
        payload = evt.get("payload", evt)
        if isinstance(payload, str):
            import json as _json
            try:
                payload = _json.loads(payload)
            except Exception:
                continue

        indicators = payload.get("indicators", {})
        for name, value in indicators.items():
            if isinstance(value, (int, float)):
                indicator_values[name].append(value)

        decision = payload.get("decision", "skip")
        decision_counts[decision] += 1

        strength = payload.get("signal_strength", 0)
        if isinstance(strength, (int, float)):
            signal_strengths.append(strength)

    indicator_stats = {}
    for name, values in indicator_values.items():
        sorted_vals = sorted(values)
        n = len(sorted_vals)
        indicator_stats[name] = {
            "count": n,
            "mean": sum(values) / n if n else 0,
            "min": sorted_vals[0] if n else 0,
            "max": sorted_vals[-1] if n else 0,
            "median": sorted_vals[n // 2] if n else 0,
        }

    return {
        "bot_id": self.bot_id,
        "date": self.date,
        "indicator_stats": indicator_stats,
        "decision_counts": dict(decision_counts),
        "total_snapshots": sum(decision_counts.values()),
        "avg_signal_strength": sum(signal_strengths) / len(signal_strengths) if signal_strengths else 0,
    }
```

#### `build_orderbook_summary()`

```python
def build_orderbook_summary(self, orderbook_events: list[dict]) -> dict:
    """Summarize order book state at trading decision points.

    Args:
        orderbook_events: Raw dicts from orderbook_context event payloads.

    Returns:
        Dict with spread stats, depth imbalance distribution, per-context breakdown.
    """
    from collections import defaultdict

    spreads: list[float] = []
    imbalances: list[float] = []
    by_context: dict[str, dict] = defaultdict(lambda: {
        "count": 0, "spreads": [], "imbalances": [],
    })

    for evt in orderbook_events:
        payload = evt.get("payload", evt)
        if isinstance(payload, str):
            import json as _json
            try:
                payload = _json.loads(payload)
            except Exception:
                continue

        spread = payload.get("spread_bps", 0)
        spreads.append(spread)

        bid_depth = payload.get("bid_depth_10bps", 0)
        ask_depth = payload.get("ask_depth_10bps", 0)
        imbalance = bid_depth / ask_depth if ask_depth > 0 else 0
        imbalances.append(imbalance)

        context = payload.get("trade_context", "signal")
        by_context[context]["count"] += 1
        by_context[context]["spreads"].append(spread)
        by_context[context]["imbalances"].append(imbalance)

    def _stats(values: list[float]) -> dict:
        if not values:
            return {"count": 0, "mean": 0, "min": 0, "max": 0, "median": 0}
        s = sorted(values)
        n = len(s)
        return {
            "count": n,
            "mean": sum(s) / n,
            "min": s[0],
            "max": s[-1],
            "median": s[n // 2],
        }

    context_summary = {}
    for ctx, data in by_context.items():
        context_summary[ctx] = {
            "count": data["count"],
            "spread_stats": _stats(data["spreads"]),
            "imbalance_stats": _stats(data["imbalances"]),
        }

    return {
        "bot_id": self.bot_id,
        "date": self.date,
        "spread_stats": _stats(spreads),
        "imbalance_stats": _stats(imbalances),
        "by_context": context_summary,
        "total_snapshots": len(spreads),
    }
```

#### Wire Into `write_curated()`

Add optional parameters to `write_curated()`:

```python
def write_curated(
    self,
    trades: list[TradeEvent],
    missed: list[MissedOpportunityEvent],
    base_dir: Path,
    coordination_events: list[dict] | None = None,
    daily_snapshot: dict | None = None,
    findings_dir: Path | None = None,
    filter_decision_events: list[dict] | None = None,      # NEW
    indicator_snapshot_events: list[dict] | None = None,    # NEW
    orderbook_context_events: list[dict] | None = None,     # NEW
) -> Path:
```

After the existing `fill_quality.json` write block (around line 572), add:

```python
# 2B: Write enriched event summaries if events provided
if filter_decision_events:
    self._write_json(
        output_dir / "filter_decisions.json",
        self.build_filter_decision_summary(filter_decision_events),
    )

if indicator_snapshot_events:
    self._write_json(
        output_dir / "indicator_snapshots.json",
        self.build_indicator_snapshot_summary(indicator_snapshot_events),
    )

if orderbook_context_events:
    self._write_json(
        output_dir / "orderbook_stats.json",
        self.build_orderbook_summary(orderbook_context_events),
    )
```

### 2B.4: Add 3 Files + 3 Instruction Steps to `analysis/prompt_assembler.py`

#### Add to `_CURATED_FILES`

```python
_CURATED_FILES = [
    # ... existing 17 entries ...
    "filter_decisions.json",
    "indicator_snapshots.json",
    "orderbook_stats.json",
]
```

#### Add Instruction Steps to `_INSTRUCTIONS`

After step 10 (fill quality), add three new steps (renumber existing 11+ accordingly):

```
11. Filter decisions: when filter_decisions.json is present, review per-filter pass/block
    rates and near-miss percentages. Filters with >30% near-miss rate are borderline —
    consider whether threshold adjustment would improve outcomes. Cross-reference with
    filter_analysis.json to validate that high-block-rate filters are net-positive.
12. Indicator snapshots: when indicator_snapshots.json is present, review indicator value
    distributions at signal evaluation points. Flag indicators with extreme clustering
    (low variance) — they may not be contributing differentiation. Compare decision
    distribution (enter/skip/exit) with win/loss outcomes for signal quality assessment.
13. Order book microstructure: when orderbook_stats.json is present, review spread and
    depth imbalance patterns. Flag entry-context spreads that exceed 2× the median
    (potential adverse selection). Bid/ask imbalance >2.0 or <0.5 at entry suggests
    positioning against order flow — note these for risk assessment.
```

The existing steps 11-26 become steps 14-29. Update the STRUCTURED OUTPUT step number accordingly.

### 2B.5: Add `detect_microstructure_issues()` to `analysis/strategy_engine.py`

Add a new detector method:

```python
def detect_microstructure_issues(
    self,
    bot_id: str,
    orderbook_stats: dict,
    spread_threshold_bps: float = 5.0,
    imbalance_threshold: float = 2.0,
) -> list[StrategySuggestion]:
    """Tier 2: Detect adverse microstructure conditions at entry/exit.

    Args:
        bot_id: Bot identifier.
        orderbook_stats: Output from build_orderbook_summary().
        spread_threshold_bps: Flag if avg entry spread exceeds this.
        imbalance_threshold: Flag if avg entry imbalance exceeds this.
    """
    effective_spread = self._get_threshold(
        "microstructure", "spread_threshold_bps", bot_id, spread_threshold_bps,
    )
    effective_imbalance = self._get_threshold(
        "microstructure", "imbalance_threshold", bot_id, imbalance_threshold,
    )
    suggestions: list[StrategySuggestion] = []

    by_context = orderbook_stats.get("by_context", {})
    entry_data = by_context.get("entry", {})
    if not entry_data:
        return []

    entry_spread = entry_data.get("spread_stats", {}).get("mean", 0)
    entry_imbalance = entry_data.get("imbalance_stats", {}).get("mean", 1.0)
    entry_count = entry_data.get("count", 0)

    if entry_count < 5:
        return []

    if entry_spread > effective_spread:
        suggestions.append(StrategySuggestion(
            tier=SuggestionTier.FILTER,
            bot_id=bot_id,
            title=f"Wide spreads at entry — {bot_id}",
            description=(
                f"Average spread at entry is {entry_spread:.1f} bps "
                f"(threshold: {effective_spread:.1f} bps) across {entry_count} entries. "
                f"Consider adding a spread-width gate or preferring limit orders."
            ),
            evidence_days=7,
            confidence=0.6,
            detection_context=DetectionContext(
                detector_name="microstructure",
                bot_id=bot_id,
                threshold_name="spread_threshold_bps",
                threshold_value=effective_spread,
                observed_value=entry_spread,
            ),
        ))

    if entry_imbalance > effective_imbalance or (entry_imbalance > 0 and entry_imbalance < 1.0 / effective_imbalance):
        suggestions.append(StrategySuggestion(
            tier=SuggestionTier.FILTER,
            bot_id=bot_id,
            title=f"Order book imbalance at entry — {bot_id}",
            description=(
                f"Average bid/ask imbalance at entry is {entry_imbalance:.2f} "
                f"across {entry_count} entries. Values far from 1.0 suggest "
                f"positioning against order flow. Review trade direction vs "
                f"book pressure for adverse selection."
            ),
            evidence_days=7,
            confidence=0.5,
            requires_human_judgment=True,
            detection_context=DetectionContext(
                detector_name="microstructure",
                bot_id=bot_id,
                threshold_name="imbalance_threshold",
                threshold_value=effective_imbalance,
                observed_value=entry_imbalance,
            ),
        ))

    return suggestions
```

Wire into `build_report()` — add `orderbook_stats: dict[str, dict] | None = None` parameter:

```python
def build_report(
    self,
    bot_summaries: dict[str, BotWeeklySummary],
    # ... existing params ...
    filter_interactions: dict[str, list] | None = None,
    orderbook_stats: dict[str, dict] | None = None,  # NEW
) -> RefinementReport:
```

Add at the end of `build_report()` before the return:

```python
if orderbook_stats:
    for bot_id, ob_data in orderbook_stats.items():
        all_suggestions.extend(
            self.detect_microstructure_issues(bot_id, ob_data)
        )
```

---

## Phase 2C — A/B Testing Framework

### 2C.1: Restore Experiment Schemas and Skills

Restore all four files from git HEAD:

```bash
git show HEAD:schemas/experiments.py > schemas/experiments.py
git show HEAD:skills/experiment_manager.py > skills/experiment_manager.py
git show HEAD:skills/experiment_config_generator.py > skills/experiment_config_generator.py
```

Verify contents:

**`schemas/experiments.py`** contains:
- `ExperimentStatus` enum (DRAFT, ACTIVE, CONCLUDED, CANCELLED)
- `ExperimentType` enum (PARAMETER_AB, FILTER_AB, ABLATION)
- `ExperimentVariant` (name, params dict, allocation_pct)
- `ExperimentConfig` with validators (≥2 variants, allocation sums to 100%, significance 0.01-0.10)
- `VariantMetrics` (per-variant accumulated stats)
- `ExperimentResult` (p_value, effect_size, CI, winner, recommendation)

**`skills/experiment_manager.py`** contains:
- `ExperimentManager` class with JSONL storage
- Full lifecycle: create → activate → ingest → analyze → conclude/cancel
- Welch's t-test (no scipy dependency)
- Cohen's d effect size
- Auto-conclusion logic (duration or significance threshold)
- Variant data stored in per-experiment JSONL files

**`skills/experiment_config_generator.py`** contains:
- `ExperimentConfigGenerator` class
- `generate_from_suggestion()` — creates ExperimentConfig from a parameter suggestion
- `generate_bot_yaml()` — produces YAML for bot experiment config
- `generate_experiment_pr()` — creates PRRequest with YAML file change

### 2C.2: Add `ab_testing_enabled` Flag to `orchestrator/config.py`

Add to `AppConfig`:

```python
class AppConfig(BaseModel):
    # ... existing fields ...
    deployment_monitoring_enabled: bool = False
    ab_testing_enabled: bool = False  # NEW
```

Add to `from_env()`:

```python
return cls(
    # ... existing fields ...
    deployment_monitoring_enabled=os.environ.get("DEPLOYMENT_MONITORING_ENABLED", "false").lower() in ("true", "1", "yes"),
    ab_testing_enabled=os.environ.get("AB_TESTING_ENABLED", "false").lower() in ("true", "1", "yes"),
)
```

### 2C.3: Wire ExperimentManager + ExperimentConfigGenerator in `orchestrator/app.py`

Add a feature-flagged block after the deployment monitor section (around line 315):

```python
# Experiment manager (feature-flagged)
experiment_manager = None
experiment_config_gen = None
if config.ab_testing_enabled:
    from skills.experiment_manager import ExperimentManager
    from skills.experiment_config_generator import ExperimentConfigGenerator

    experiment_manager = ExperimentManager(
        findings_dir=db_path / "memory" / "findings",
    )
    _ecg_registry = config_registry if config.autonomous_enabled else None
    experiment_config_gen = ExperimentConfigGenerator(
        config_registry=_ecg_registry,
    )
    logger.info("A/B testing enabled")
```

Pass to Handlers:

```python
handlers = Handlers(
    # ... existing params ...
    threshold_learner=threshold_learner,
    experiment_manager=experiment_manager,          # NEW
    experiment_config_gen=experiment_config_gen,     # NEW
)
```

Expose on app.state:

```python
app.state.experiment_manager = experiment_manager
app.state.experiment_config_gen = experiment_config_gen
```

### 2C.4: Add Experiment Check Scheduler Job

Add to `SchedulerConfig`:

```python
@dataclass
class SchedulerConfig:
    # ... existing fields ...
    threshold_learning_hour: int = 9
    threshold_learning_minute: int = 30
    experiment_check_interval_seconds: int = 21600  # 6 hours
```

Add parameter to `create_scheduler_jobs()`:

```python
def create_scheduler_jobs(
    config: SchedulerConfig,
    # ... existing params ...
    threshold_learning_fn: Callable[[], Awaitable[None]] | None = None,
    experiment_check_fn: Callable[[], Awaitable[None]] | None = None,  # NEW
) -> list[dict]:
```

Add job at the end:

```python
if experiment_check_fn is not None:
    jobs.append({
        "name": "experiment_check",
        "func": experiment_check_fn,
        "trigger": "interval",
        "seconds": config.experiment_check_interval_seconds,
    })
```

In `app.py`, define the experiment check function and wire it:

```python
async def _check_experiments() -> None:
    """Check active experiments for auto-conclusion."""
    if experiment_manager is None:
        return
    try:
        active = experiment_manager.get_active()
        for exp in active:
            if experiment_manager.check_auto_conclusion(exp.experiment_id):
                result = experiment_manager.analyze_experiment(exp.experiment_id)
                experiment_manager.conclude_experiment(exp.experiment_id, result)
                logger.info(
                    "Auto-concluded experiment %s: %s",
                    exp.experiment_id, result.recommendation,
                )
                # Broadcast conclusion
                event_stream.broadcast("experiment_concluded", {
                    "experiment_id": exp.experiment_id,
                    "recommendation": result.recommendation,
                    "winner": result.winner,
                    "p_value": result.p_value,
                })
                # Notify via Telegram
                if telegram_adapter is not None:
                    try:
                        from comms.telegram_renderer import TelegramRenderer
                        renderer = TelegramRenderer()
                        text = renderer.render_experiment_result(exp, result)
                        await telegram_adapter.send_message(text)
                    except Exception:
                        logger.warning("Failed to send experiment result notification")
    except Exception:
        logger.exception("Experiment check failed")
```

Wire into scheduler:

```python
scheduler_jobs = create_scheduler_jobs(
    # ... existing params ...
    threshold_learning_fn=threshold_learner.learn_thresholds if threshold_learner else None,
    experiment_check_fn=_check_experiments if experiment_manager else None,
)
```

### 2C.5: Add Experiment Lifecycle to Weekly Handler

In `orchestrator/handlers.py`, update `Handlers.__init__()`:

```python
def __init__(
    self,
    # ... existing params ...
    threshold_learner: object | None = None,
    experiment_manager: object | None = None,       # NEW
    experiment_config_gen: object | None = None,     # NEW
) -> None:
    # ... existing assignments ...
    self._threshold_learner = threshold_learner
    self._experiment_manager = experiment_manager           # NEW
    self._experiment_config_gen = experiment_config_gen      # NEW
```

In `handle_weekly_analysis()`, after the simulation results block and before prompt assembly, add experiment data ingestion:

```python
# Ingest experiment variant data from curated experiment_data.json files
if self._experiment_manager is not None:
    for bot in self._bots:
        for date_str in dates_in_week:
            exp_path = self._curated_dir / date_str / bot / "experiment_data.json"
            if not exp_path.exists():
                continue
            try:
                exp_data = json.loads(exp_path.read_text())
                for exp_id, variants in exp_data.items():
                    for variant_name, variant_data in variants.items():
                        trades = variant_data.get("trades", [])
                        if trades:
                            self._experiment_manager.ingest_variant_data(
                                exp_id, variant_name, trades,
                            )
            except Exception:
                logger.warning(
                    "Failed to ingest experiment data from %s", exp_path,
                )

    # Check auto-conclusion and analyze
    active_experiments = self._experiment_manager.get_active()
    experiment_results = []
    for exp in active_experiments:
        try:
            if self._experiment_manager.check_auto_conclusion(exp.experiment_id):
                result = self._experiment_manager.analyze_experiment(exp.experiment_id)
                self._experiment_manager.conclude_experiment(exp.experiment_id, result)
                experiment_results.append(result)
                self._event_stream.broadcast("experiment_concluded", {
                    "experiment_id": exp.experiment_id,
                    "recommendation": result.recommendation,
                })
        except Exception:
            logger.warning("Experiment check failed for %s", exp.experiment_id)
```

### 2C.6: Add Telegram Renderers

Add to `comms/telegram_renderer.py`:

```python
def render_experiment_proposal(
    self,
    config,  # ExperimentConfig
) -> tuple[str, list[list[dict]]]:
    """Render an experiment proposal card with start/cancel buttons.

    Args:
        config: ExperimentConfig instance.

    Returns:
        (message_text, inline_keyboard) tuple.
    """
    lines: list[str] = []
    lines.append("\U0001f9ea A/B Experiment Proposal")
    lines.append(f"ID: {_escape_md2(config.experiment_id[:8])}")
    lines.append(f"Bot: {_escape_md2(config.bot_id)}")
    lines.append(f"Type: {config.experiment_type.value}")
    lines.append("")
    lines.append(f"Title: {_escape_md2(config.title)}")
    if config.description:
        lines.append(f"Description: {_escape_md2(config.description)}")
    lines.append("")

    lines.append("Variants:")
    for v in config.variants:
        params_str = ", ".join(f"{k}={v_val}" for k, v_val in v.params.items())
        lines.append(f"  {_escape_md2(v.name)} ({v.allocation_pct:.0f}%): {_escape_md2(params_str)}")
    lines.append("")

    lines.append(f"Metric: {config.success_metric}")
    lines.append(f"Duration: {config.max_duration_days}d")
    lines.append(f"Min trades/variant: {config.min_trades_per_variant}")
    lines.append(f"Significance: {config.significance_level}")

    text = _truncate("\n".join(lines))

    keyboard = [
        [
            {"text": "\u25b6\ufe0f Start", "callback_data": f"start_experiment_{config.experiment_id}"},
            {"text": "\u274c Cancel", "callback_data": f"cancel_experiment_{config.experiment_id}"},
        ],
    ]

    return text, keyboard

def render_experiment_result(
    self,
    config,   # ExperimentConfig
    result,   # ExperimentResult
) -> str:
    """Render experiment conclusion summary.

    Args:
        config: ExperimentConfig of the concluded experiment.
        result: ExperimentResult with statistical analysis.

    Returns:
        Formatted message text.
    """
    lines: list[str] = []

    icon = {
        "adopt_treatment": "\u2705",
        "keep_control": "\U0001f6d1",
        "inconclusive": "\u2753",
        "extend": "\u23f3",
    }.get(result.recommendation, "\u2753")

    lines.append(f"\U0001f9ea Experiment Concluded: {_escape_md2(config.title)}")
    lines.append(f"Bot: {_escape_md2(config.bot_id)}")
    lines.append(f"Result: {icon} {result.recommendation.replace('_', ' ').upper()}")
    lines.append("")

    lines.append("Variant Results:")
    for vm in result.variant_metrics:
        lines.append(
            f"  {_escape_md2(vm.variant_name)}: "
            f"{vm.trade_count} trades, "
            f"PnL ${vm.total_pnl:.0f}, "
            f"WR {vm.win_rate:.0%}, "
            f"Sharpe {vm.sharpe:.2f}"
        )
    lines.append("")

    if result.p_value is not None:
        lines.append(f"p-value: {result.p_value:.4f}")
    if result.effect_size is not None:
        lines.append(f"Effect size (Cohen's d): {result.effect_size:.3f}")
    if result.confidence_interval_95 is not None:
        lo, hi = result.confidence_interval_95
        lines.append(f"95% CI: [{lo:.4f}, {hi:.4f}]")
    if result.winner:
        lines.append(f"Winner: {_escape_md2(result.winner)}")

    return _truncate("\n".join(lines))
```

### 2C.7: Register Telegram Callbacks

In `orchestrator/app.py`, within the `if approval_handler is not None:` block (which already registers `approve_suggestion_`, `reject_suggestion_`, `detail_suggestion_` prefixes), add experiment callbacks:

```python
# Register experiment callbacks (if A/B testing is enabled)
if experiment_manager is not None:
    async def _on_start_experiment(experiment_id: str) -> str:
        try:
            experiment_manager.activate_experiment(experiment_id)
            exp = experiment_manager.get_by_id(experiment_id)
            return f"\u25b6\ufe0f Experiment started: {exp.title if exp else experiment_id}"
        except Exception as e:
            return f"Failed to start experiment: {e}"

    async def _on_cancel_experiment(experiment_id: str) -> str:
        try:
            experiment_manager.cancel_experiment(experiment_id)
            return f"\u274c Experiment cancelled: {experiment_id}"
        except Exception as e:
            return f"Failed to cancel experiment: {e}"

    callback_router.register("start_experiment_", _on_start_experiment)
    callback_router.register("cancel_experiment_", _on_cancel_experiment)
```

If autonomous mode is not enabled but A/B testing is, the callback router setup needs to be extracted into its own block. Add a separate conditional:

```python
# Register experiment Telegram callbacks (independent of autonomous pipeline)
if experiment_manager is not None and telegram_adapter is not None:
    if callback_router is None:
        from comms.telegram_handlers import TelegramCallbackRouter
        callback_router = TelegramCallbackRouter()

    # ... register start_experiment_ and cancel_experiment_ as above ...

    telegram_adapter.set_callback_router(callback_router)
```

---

## Expected Event Payload Formats

### FilterDecisionEvent (from bot)

```json
{
  "event_type": "filter_decision",
  "bot_id": "kmp_v3",
  "event_id": "fd-abc123...",
  "payload": {
    "bot_id": "kmp_v3",
    "pair": "AAPL",
    "timestamp": "2026-03-07T15:30:00Z",
    "filter_name": "volume_filter",
    "passed": false,
    "threshold": 1.5,
    "actual_value": 1.2,
    "signal_name": "breakout",
    "signal_strength": 0.72
  }
}
```

### IndicatorSnapshot (from bot)

```json
{
  "event_type": "indicator_snapshot",
  "bot_id": "swing_atrss",
  "event_id": "is-def456...",
  "payload": {
    "bot_id": "swing_atrss",
    "pair": "MSFT",
    "timestamp": "2026-03-07T14:00:00Z",
    "indicators": {
      "atr_14": 2.85,
      "rsi_14": 62.3,
      "ema_20": 415.50,
      "ema_50": 412.80
    },
    "signal_name": "atr_breakout",
    "signal_strength": 0.68,
    "decision": "enter",
    "context": {
      "strategy_id": "ATRSS",
      "market_regime": "trending",
      "session": "RTH"
    }
  }
}
```

### OrderBookContext (from bot)

```json
{
  "event_type": "orderbook_context",
  "bot_id": "momentum_helix",
  "event_id": "ob-789abc...",
  "payload": {
    "bot_id": "momentum_helix",
    "pair": "NQ",
    "timestamp": "2026-03-07T16:45:00Z",
    "best_bid": 21450.25,
    "best_ask": 21450.50,
    "spread_bps": 1.2,
    "bid_depth_10bps": 125.0,
    "ask_depth_10bps": 98.0,
    "trade_context": "entry",
    "related_trade_id": "trade-xyz"
  }
}
```

### Curated Output: `filter_decisions.json`

```json
{
  "bot_id": "kmp_v3",
  "date": "2026-03-07",
  "filters": {
    "volume_filter": {
      "pass_count": 42,
      "block_count": 15,
      "total": 57,
      "block_rate": 0.263,
      "avg_margin_pct": 12.4,
      "near_miss_count": 8,
      "near_miss_rate": 0.14
    },
    "regime_filter": {
      "pass_count": 50,
      "block_count": 7,
      "total": 57,
      "block_rate": 0.123,
      "avg_margin_pct": 35.2,
      "near_miss_count": 2,
      "near_miss_rate": 0.035
    }
  },
  "total_evaluations": 114
}
```

### Curated Output: `indicator_snapshots.json`

```json
{
  "bot_id": "swing_atrss",
  "date": "2026-03-07",
  "indicator_stats": {
    "atr_14": {"count": 24, "mean": 2.91, "min": 2.10, "max": 3.85, "median": 2.88},
    "rsi_14": {"count": 24, "mean": 55.2, "min": 28.1, "max": 78.4, "median": 54.8},
    "ema_20": {"count": 24, "mean": 415.20, "min": 413.50, "max": 417.10, "median": 415.30}
  },
  "decision_counts": {"enter": 3, "skip": 18, "exit": 3},
  "total_snapshots": 24,
  "avg_signal_strength": 0.58
}
```

### Curated Output: `orderbook_stats.json`

```json
{
  "bot_id": "momentum_helix",
  "date": "2026-03-07",
  "spread_stats": {"count": 30, "mean": 1.8, "min": 0.5, "max": 4.2, "median": 1.5},
  "imbalance_stats": {"count": 30, "mean": 1.15, "min": 0.4, "max": 2.8, "median": 1.05},
  "by_context": {
    "entry": {
      "count": 8,
      "spread_stats": {"count": 8, "mean": 2.1, "min": 1.0, "max": 3.5, "median": 1.9},
      "imbalance_stats": {"count": 8, "mean": 1.25, "min": 0.6, "max": 2.1, "median": 1.15}
    },
    "exit": {
      "count": 6,
      "spread_stats": {"count": 6, "mean": 1.6, "min": 0.8, "max": 2.5, "median": 1.5},
      "imbalance_stats": {"count": 6, "mean": 0.95, "min": 0.5, "max": 1.4, "median": 0.9}
    },
    "signal": {
      "count": 16,
      "spread_stats": {"count": 16, "mean": 1.7, "min": 0.5, "max": 4.2, "median": 1.4},
      "imbalance_stats": {"count": 16, "mean": 1.12, "min": 0.4, "max": 2.8, "median": 1.0}
    }
  },
  "total_snapshots": 30
}
```

---

## Testing

### Brain Tests (`tests/test_orchestrator_brain.py`)

```python
def test_handle_indicator_snapshot():
    brain = OrchestratorBrain()
    actions = brain.decide({
        "event_type": "indicator_snapshot",
        "event_id": "is-001",
        "bot_id": "bot1",
        "payload": "{}",
    })
    assert len(actions) == 1
    assert actions[0].type == ActionType.QUEUE_FOR_DAILY

def test_handle_orderbook_context():
    brain = OrchestratorBrain()
    actions = brain.decide({
        "event_type": "orderbook_context",
        "event_id": "ob-001",
        "bot_id": "bot1",
        "payload": "{}",
    })
    assert len(actions) == 1
    assert actions[0].type == ActionType.QUEUE_FOR_DAILY

def test_handle_filter_decision():
    brain = OrchestratorBrain()
    actions = brain.decide({
        "event_type": "filter_decision",
        "event_id": "fd-001",
        "bot_id": "bot1",
        "payload": "{}",
    })
    assert len(actions) == 1
    assert actions[0].type == ActionType.QUEUE_FOR_DAILY
```

### Builder Tests (`tests/test_build_daily_metrics.py`)

```python
def test_build_filter_decision_summary():
    builder = DailyMetricsBuilder(date="2026-03-07", bot_id="bot1")
    events = [
        {"payload": {"filter_name": "vol", "passed": True, "threshold": 1.5, "actual_value": 2.0}},
        {"payload": {"filter_name": "vol", "passed": False, "threshold": 1.5, "actual_value": 1.2}},
        {"payload": {"filter_name": "regime", "passed": True, "threshold": 0.5, "actual_value": 0.8}},
    ]
    result = builder.build_filter_decision_summary(events)
    assert result["total_evaluations"] == 3
    assert result["filters"]["vol"]["pass_count"] == 1
    assert result["filters"]["vol"]["block_count"] == 1
    assert result["filters"]["regime"]["pass_count"] == 1

def test_build_filter_decision_summary_near_miss():
    builder = DailyMetricsBuilder(date="2026-03-07", bot_id="bot1")
    events = [
        {"payload": {"filter_name": "vol", "passed": True, "threshold": 1.5, "actual_value": 1.55}},
    ]
    result = builder.build_filter_decision_summary(events)
    assert result["filters"]["vol"]["near_miss_count"] == 1

def test_build_indicator_snapshot_summary():
    builder = DailyMetricsBuilder(date="2026-03-07", bot_id="bot1")
    events = [
        {"payload": {"indicators": {"rsi": 45.0, "atr": 2.5}, "decision": "skip", "signal_strength": 0.3}},
        {"payload": {"indicators": {"rsi": 65.0, "atr": 3.0}, "decision": "enter", "signal_strength": 0.8}},
    ]
    result = builder.build_indicator_snapshot_summary(events)
    assert result["total_snapshots"] == 2
    assert result["decision_counts"]["skip"] == 1
    assert result["decision_counts"]["enter"] == 1
    assert result["indicator_stats"]["rsi"]["mean"] == 55.0
    assert result["avg_signal_strength"] == 0.55

def test_build_orderbook_summary():
    builder = DailyMetricsBuilder(date="2026-03-07", bot_id="bot1")
    events = [
        {"payload": {"spread_bps": 2.0, "bid_depth_10bps": 100, "ask_depth_10bps": 80, "trade_context": "entry"}},
        {"payload": {"spread_bps": 1.5, "bid_depth_10bps": 90, "ask_depth_10bps": 110, "trade_context": "exit"}},
    ]
    result = builder.build_orderbook_summary(events)
    assert result["total_snapshots"] == 2
    assert result["by_context"]["entry"]["count"] == 1
    assert result["by_context"]["exit"]["count"] == 1

def test_build_orderbook_summary_empty():
    builder = DailyMetricsBuilder(date="2026-03-07", bot_id="bot1")
    result = builder.build_orderbook_summary([])
    assert result["total_snapshots"] == 0
```

### Prompt Assembler Tests (`tests/test_prompt_assembler.py`)

```python
def test_curated_files_includes_enriched():
    from analysis.prompt_assembler import _CURATED_FILES
    assert "filter_decisions.json" in _CURATED_FILES
    assert "indicator_snapshots.json" in _CURATED_FILES
    assert "orderbook_stats.json" in _CURATED_FILES
```

### Strategy Engine Tests (`tests/test_strategy_engine.py`)

```python
def test_detect_microstructure_wide_spread():
    engine = StrategyEngine(week_start="2026-03-01", week_end="2026-03-07")
    stats = {
        "by_context": {
            "entry": {
                "count": 10,
                "spread_stats": {"mean": 8.0},
                "imbalance_stats": {"mean": 1.0},
            }
        }
    }
    suggestions = engine.detect_microstructure_issues("bot1", stats, spread_threshold_bps=5.0)
    assert len(suggestions) == 1
    assert "Wide spreads" in suggestions[0].title

def test_detect_microstructure_imbalance():
    engine = StrategyEngine(week_start="2026-03-01", week_end="2026-03-07")
    stats = {
        "by_context": {
            "entry": {
                "count": 10,
                "spread_stats": {"mean": 1.0},
                "imbalance_stats": {"mean": 3.0},
            }
        }
    }
    suggestions = engine.detect_microstructure_issues("bot1", stats, imbalance_threshold=2.0)
    assert len(suggestions) == 1
    assert "imbalance" in suggestions[0].title

def test_detect_microstructure_insufficient_data():
    engine = StrategyEngine(week_start="2026-03-01", week_end="2026-03-07")
    stats = {
        "by_context": {
            "entry": {
                "count": 2,
                "spread_stats": {"mean": 20.0},
                "imbalance_stats": {"mean": 5.0},
            }
        }
    }
    suggestions = engine.detect_microstructure_issues("bot1", stats)
    assert len(suggestions) == 0  # count < 5

def test_detect_microstructure_no_entry_context():
    engine = StrategyEngine(week_start="2026-03-01", week_end="2026-03-07")
    stats = {"by_context": {}}
    suggestions = engine.detect_microstructure_issues("bot1", stats)
    assert len(suggestions) == 0
```

### Experiment Manager Tests (`tests/test_experiment_manager.py`)

```python
def test_create_and_get_experiment(tmp_path):
    mgr = ExperimentManager(findings_dir=tmp_path)
    config = ExperimentConfig(
        experiment_id="exp-001",
        bot_id="bot1",
        title="Test experiment",
        variants=[
            ExperimentVariant(name="control", params={"stop_pct": 2.0}, allocation_pct=50),
            ExperimentVariant(name="treatment", params={"stop_pct": 3.0}, allocation_pct=50),
        ],
    )
    created = mgr.create_experiment(config)
    assert created.experiment_id == "exp-001"
    retrieved = mgr.get_by_id("exp-001")
    assert retrieved is not None
    assert retrieved.status == ExperimentStatus.DRAFT

def test_activate_and_get_active(tmp_path):
    mgr = ExperimentManager(findings_dir=tmp_path)
    # ... create experiment ...
    mgr.activate_experiment("exp-001")
    active = mgr.get_active()
    assert len(active) == 1
    assert active[0].status == ExperimentStatus.ACTIVE

def test_welch_t_test_significant(tmp_path):
    mgr = ExperimentManager(findings_dir=tmp_path, min_trades=5)
    # ... create and activate experiment, ingest divergent variant data ...
    result = mgr.analyze_experiment("exp-001")
    # With sufficiently different distributions, p_value should be low
    assert result.p_value is not None

def test_experiment_deduplication(tmp_path):
    mgr = ExperimentManager(findings_dir=tmp_path)
    config = ExperimentConfig(...)
    mgr.create_experiment(config)
    mgr.create_experiment(config)  # same ID
    assert len(mgr._load_all()) == 1
```

### Config Generator Tests (`tests/test_experiment_config_generator.py`)

```python
def test_generate_from_suggestion():
    gen = ExperimentConfigGenerator()
    config = gen.generate_from_suggestion(
        suggestion_id="sug-001",
        bot_id="bot1",
        param_name="stop_pct",
        current_value=2.0,
        proposed_value=3.0,
    )
    assert len(config.variants) == 2
    assert config.variants[0].name == "control"
    assert config.variants[1].name == "treatment"
    assert config.variants[0].params["stop_pct"] == 2.0
    assert config.variants[1].params["stop_pct"] == 3.0

def test_generate_bot_yaml():
    gen = ExperimentConfigGenerator()
    config = gen.generate_from_suggestion(...)
    yaml_str = gen.generate_bot_yaml(config)
    assert "experiments:" in yaml_str
    assert "allocation_method: hash" in yaml_str

def test_generate_experiment_pr():
    gen = ExperimentConfigGenerator()
    config = gen.generate_from_suggestion(...)
    pr = gen.generate_experiment_pr(config, repo_dir="/tmp/repo")
    assert pr.bot_id == "bot1"
    assert len(pr.file_changes) == 1
    assert "experiments/" in pr.file_changes[0].file_path
```

### Telegram Renderer Tests (`tests/test_telegram_renderer.py`)

```python
def test_render_experiment_proposal():
    renderer = TelegramRenderer()
    config = ExperimentConfig(
        experiment_id="exp-001",
        bot_id="bot1",
        title="Test AB",
        variants=[
            ExperimentVariant(name="control", params={"x": 1}, allocation_pct=50),
            ExperimentVariant(name="treatment", params={"x": 2}, allocation_pct=50),
        ],
    )
    text, keyboard = renderer.render_experiment_proposal(config)
    assert "A/B Experiment" in text
    assert "bot1" in text
    assert len(keyboard) == 1
    assert "start_experiment_" in keyboard[0][0]["callback_data"]

def test_render_experiment_result():
    renderer = TelegramRenderer()
    # ... create config + result with known values ...
    text = renderer.render_experiment_result(config, result)
    assert "Concluded" in text
    assert "ADOPT TREATMENT" in text or "KEEP CONTROL" in text or "INCONCLUSIVE" in text
```

---

## Compatibility

### Backward Compatibility Guarantees

1. **All changes are additive** — existing event types and curated files are unchanged
2. **New curated files are optional** — `_load_structured_data()` skips missing files (`if path.exists()`)
3. **Builder params are optional** — `filter_decision_events=None` etc. means `write_curated()` simply skips those outputs
4. **Feature flag off** — `ab_testing_enabled=False` means no ExperimentManager instantiation, no scheduler job, no callbacks
5. **Old bots without new events** — orchestrator handles gracefully; brain routes unknown types to `LOG_UNKNOWN`, missing curated files are silently skipped in prompt assembly
6. **Existing `parameter_change` handler unchanged** — safety-critical detection continues to work identically
7. **No schema changes to existing models** — `schemas/enriched_events.py` and `schemas/experiments.py` are standalone files with no modifications to existing schemas

### Migration Path

1. Deploy orchestrator changes first (all backward-compatible)
2. Deploy bot changes incrementally (each bot can be updated independently)
3. Enable `AB_TESTING_ENABLED=true` only after all bots support experiment variant assignment
4. First experiment should be a low-risk parameter on a single bot to validate the pipeline end-to-end

### Data Flow After Implementation

```
Bot (new events) → Sidecar JSONL → Relay → POST /events → EventQueue
                                                              ↓
                                              OrchestratorBrain.decide()
                                    indicator_snapshot → QUEUE_FOR_DAILY
                                    orderbook_context  → QUEUE_FOR_DAILY
                                    filter_decision    → QUEUE_FOR_DAILY
                                                              ↓
                                          DailyMetricsBuilder.write_curated()
                                    filter_decisions.json ← build_filter_decision_summary()
                                    indicator_snapshots.json ← build_indicator_snapshot_summary()
                                    orderbook_stats.json ← build_orderbook_summary()
                                                              ↓
                                          DailyPromptAssembler.assemble()
                                    _CURATED_FILES includes all 3 new files
                                    _INSTRUCTIONS includes 3 new analysis steps
                                                              ↓
                                          StrategyEngine.build_report()
                                    detect_microstructure_issues() from orderbook_stats
                                                              ↓
                                          Claude analysis includes enriched insights
```

```
ExperimentConfigGenerator.generate_from_suggestion()
    → ExperimentConfig + bot YAML + PRRequest
    → Bot merges PR, loads experiments.yaml
    → Bot assigns variants to trades via ExperimentRegistry
    → DailySnapshot.experiment_breakdown includes per-variant metrics
    → Sidecar forwards experiment_data → orchestrator curated
    → ExperimentManager.ingest_variant_data()
    → ExperimentManager.analyze_experiment() (Welch's t-test)
    → ExperimentManager.conclude_experiment()
    → Telegram notification with result
```
