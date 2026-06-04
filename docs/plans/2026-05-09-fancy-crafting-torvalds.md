# Plan: Close P0 Wiring Gaps + Add Event Lineage + Establish ProposalLedger Spine

Date: 2026-05-09
Source plan: `docs/plans/2026-05-03-unified-learning-system-improvement-plan.md`

## Context

The unified learning-system plan from 2026-05-03 prescribes a shared evidence
graph so every component reads from and writes to the same learning artifacts.
A direct read of the codebase finds that most P0 wiring fixes are done, but
several small omissions still leak evidence; the entire P0 shared spine
(LearningObjective / LifecycleDiagnosticBundle / ProposalLedger) is unbuilt;
event lineage fields are absent (which blocks any population-filtered causal
evaluation later); and a few feedback links (WFO → calibration tracker,
non-experiment-suggestion outcomes → hypothesis library) are dangling.

This plan implements the **scoped middle tier**: the remaining plumbing fixes,
event/deployment lineage fields, and a ProposalLedger spine that unifies how
suggestions, structural experiments, discovery ideas, and WFO recommendations
are recorded. Larger items — full LifecycleDiagnosticBundle, LearningObjective,
causal evaluator with matched controls, lifecycle simulators, replay infra,
memory manager — are deferred to a separate initiative because each is a
multi-day architectural lift.

The intended outcome: every proposal-producing path writes one record to one
ledger with consistent fields; events and deployments carry lineage IDs so a
later causal evaluator can isolate the affected population; the deterministic
strategy engine sees the simulation outputs it currently misses; and the
instrumentation scorer reports honestly against the curated artifacts that
`build_daily_metrics.py` already produces.

## Audit (verified by direct reads, 2026-05-09)

### P0 wiring — 3 real gaps remain

| Item | Status | Verified |
|------|--------|----------|
| A1 source_suggestion_id | ✅ Done | `app.py:1370-1372` |
| **A2 structural-exp eval is reachable when `experiment_manager is None`** | ❌ Gap | The structural-evaluation block at `app.py:1405+` does run unconditionally **inside** `_check_experiments`, but the **scheduler job registration is gated** at `app.py:1727`: `experiment_check_fn=_experiment_check_job if experiment_manager else None`. When `experiment_manager` is None the entire job never fires — including the structural-experiment evaluation. |
| A3 cap accounting | ✅ Done | `autonomous_pipeline.py:492-500` |
| A4 best_robustness fields | ✅ Done | `parameter_search.py:47-48` |
| A5 approval-summary uses new fields | ✅ Done | `autonomous_pipeline.py:513` |
| A6 bot_id in context loaders | ✅ Done | `context_builder.py:1799,1802` |
| A7 TRAILING_STOP | ✅ Done | `exit_strategy_simulator.py:38-42,116-139` |
| **A8 sims → deterministic strategy evidence** | ❌ Gap | Weekly handler stores sims as `results[f"filter_sensitivity_{bot_id}"]` (handlers.py:3126), `results[f"counterfactual_{bot_id}"]` (3136), `results[f"exit_sweep_{bot_id}"]` (3144). But `engine.build_report(portfolio_summary.bot_summaries, **weekly_evidence)` at line 3578 does not include these in `weekly_evidence`. |
| **A9 instrumentation scorer coverage** | ⚠️ Partial | `_CAPABILITY_FIELDS` (instrumentation_scorer.py:49-83) and `_OPTIONAL_FILES` (91-101) cover most curated artifacts but lack: `order_book_stats.json`, `sizing` (sizing_data field), `portfolio_context.json`, `fill_quality.json`. |

### P0 WFO closure / outcome feedback — partial

- `handle_wfo` at handlers.py:1152-1192 already creates a `SuggestionRecord` for ADOPT/TEST_FURTHER recommendations. **Gap:** does not call `BacktestCalibrationTracker.record_prediction(...)`. The tracker module exists (`skills/backtest_calibration_tracker.py`) and `auto_outcome_measurer.py:188-191` already calls `record_outcome` — so the prediction/outcome loop closes once the WFO side is wired.
- `_check_experiments` (`app.py:1379-1393`) already calls `hypothesis_library.record_outcome(exp.hypothesis_id, positive=True/False)` for **A/B experiments**.
- **Gap:** `auto_outcome_measurer.py` measures non-experiment suggestion outcomes but does **not** feed `HypothesisLibrary`. Suggestions carrying a `hypothesis_id` (already a real field on `SuggestionRecord`, schemas/suggestion_tracking.py) lose their outcome signal.

### Event + deployment lineage — entirely missing

- `TradeEvent`, `MissedOpportunityEvent` carry no lineage fields. `model_config` does not set `extra="ignore"`, so adding optional defaulted fields is safe in both directions.
- `DeploymentRecord` lacks `affected_population`/`variant_id`/`parameter_set_id`/`strategy_version`/`config_version`.

### Shared spine — entirely missing

- No `schemas/proposal_ledger.py`, no `skills/proposal_ledger.py`. Repo grep for `ProposalLedger`, `ProposalCandidate`, `proposal_ledger`, and `proposal_id` returns **zero matches** — name-clash-safe.

### What already exists (do not re-implement)

| Component | File | Notes |
|-----------|------|-------|
| Atomic JSONL rewrite | `skills/_atomic_write.py:11` — `atomic_rewrite_jsonl(path: Path, records: list) -> None` | Used by SuggestionTracker |
| JSONL store pattern | `skills/suggestion_tracker.py` (lock + `_read_jsonl` + atomic rewrite) | Copy this pattern for ProposalLedger |
| `HypothesisLibrary.record_outcome(hypothesis_id, positive)` | `skills/hypothesis_library.py:300` | Already wired for A/B exp outcomes |
| `BacktestCalibrationTracker.record_prediction` / `.record_outcome` | `skills/backtest_calibration_tracker.py:32,54` | Outcome side already called from auto_outcome_measurer:188-191 |
| `SuggestionRecord.hypothesis_id` | `schemas/suggestion_tracking.py:25-54` | Already optional field; LLM path stamps it via `_record_agent_suggestions` (handlers.py:2782-2937) |
| `SuggestionRecord.detection_context`, `target_param`, `proposed_value`, `expected_impact`, `implementation_context` | same | Sources for ledger candidate fields |
| `_record_*` handler hooks | `handlers.py:1041 (handle_wfo), 1422 (handle_discovery_analysis), 2465 (_record_portfolio_proposals), 2673 (_record_suggestions), 2782 (_record_agent_suggestions), 2939 (_record_structural_experiments)` | Single hook point per source — clean ledger insertion targets |
| `_check_experiments` structural eval | `app.py:1405-1459+` | Already evaluates due structural experiments via `structural_experiment_tracker.get_evaluable_experiments()`; unconditional inside the function |

## Scope (user-confirmed: Plumbing + lineage + ProposalLedger)

**In scope:**
1. A2, A8, A9 wiring fixes; WFO→calibration prediction call; non-A/B outcome→hypothesis feedback
2. Backward-compatible event lineage fields on `TradeEvent` + `MissedOpportunityEvent`
3. Backward-compatible lineage extension on `DeploymentRecord`
4. New `ProposalLedger` schema + skill + handler-side write hooks at every proposal-producing path
5. Single new `ContextBuilder` loader for recent ledger outcomes

**Deferred (out of scope, separate initiative):**
- B1 `LearningObjective`, B2/B4 `LifecycleDiagnosticBundle` + builder
- C1 `wfo_result_integrator.py` (the inline calibration+ledger hooks here cover the high-leverage piece)
- D2 `causal_outcome_evaluator.py`, matched controls, lifecycle-delta reporting
- D3 population-filtered outcome measurement (lineage fields landed here will be the foundation)
- E search-space evaluator
- G1/G3/G4 lifecycle simulators (signal/entry/trade-management)
- H replay infra: `replay_case_builder`, `harness_replay_runner`, `playbook_usage_tracker`, `playbook_curator`
- I `learning_memory_manager` + frozen `learning_memory_snapshot`
- J `lifecycle_experiment_planner`, `diagnostic_request_planner`

## Implementation

### Part 1 — Plumbing fixes

**A2 — Make `experiment_check` job register unconditionally.**
- File: `orchestrator/app.py:1727`
- Change `experiment_check_fn=_experiment_check_job if experiment_manager else None` to `experiment_check_fn=_experiment_check_job`.
- The `_check_experiments` body (`app.py:1349-1459+`) already correctly skips the A/B block when `experiment_manager is None` (line 1351 guard). The structural-evaluation block at line 1405+ runs unconditionally and is the actual purpose of unblocking the schedule.
- **Verify:** with `experiment_manager=None`, `app.state.scheduler.get_jobs()` includes the experiment_check job, and a smoke test asserts `structural_experiment_tracker.resolve(...)` is called for due experiments.

**A8 — Pipe weekly simulation outputs into `StrategyEngine.build_report`.**
- File: `analysis/strategy_engine.py::build_report` — add three optional kwargs at the end of the existing parameter list (the function already has 23 optional params; adding three more is consistent):
  ```python
  exit_sweep: dict[str, dict] | None = None,
  filter_sensitivity: dict[str, dict] | None = None,
  counterfactual: dict[str, dict] | None = None,
  ```
- Add three new detector branches (or three new `detect_*` methods) that emit `StrategySuggestion` objects only when the sim output exceeds plan-defined thresholds. Concretely:
  - `detect_better_exit_strategies(exit_sweep)` — emits suggestion if any sweep variant beats the live exit by >X% net PnL
  - `detect_filter_sensitivity_findings(filter_sensitivity)` — emits suggestion if a filter has marginal value (low ROI / high false-block rate)
  - `detect_counterfactual_gaps(counterfactual)` — emits suggestion if a counterfactual gate would have improved expectancy meaningfully
- File: `orchestrator/handlers.py` — at the weekly handler's `build_report` site (around line 3578), build a per-bot dict from the `results[...]` keys created at lines 3126/3136/3144, and pass it as new kwargs:
  ```python
  exit_sweep_per_bot = {bid: results[f"exit_sweep_{bid}"] for bid in bot_ids if f"exit_sweep_{bid}" in results}
  filter_sensitivity_per_bot = {bid: results[f"filter_sensitivity_{bid}"] for bid in bot_ids if f"filter_sensitivity_{bid}" in results}
  counterfactual_per_bot = {bid: results[f"counterfactual_{bid}"] for bid in bot_ids if f"counterfactual_{bid}" in results}
  refinement_report = engine.build_report(
      portfolio_summary.bot_summaries,
      **weekly_evidence,
      exit_sweep=exit_sweep_per_bot,
      filter_sensitivity=filter_sensitivity_per_bot,
      counterfactual=counterfactual_per_bot,
  )
  ```
- **Verify:** extend `tests/test_strategy_engine.py` — fabricate each sim output, assert matching suggestion category appears in `RefinementReport.suggestions`. Existing detector test patterns (~20 detectors already tested) make this a small additive change.

**A9 — Extend `instrumentation_scorer.py`.**
- File: `skills/instrumentation_scorer.py`
- Add to `_CAPABILITY_FIELDS`:
  ```python
  "order_book_analysis": ["order_book", "orderbook", "order_book_stats"],
  "sizing_analysis": ["position_size", "sizing_data"],
  "portfolio_context": ["portfolio_context", "portfolio_correlation"],
  "fill_quality": ["fill_quality", "execution_quality"],
  ```
- Add to `_OPTIONAL_FILES`:
  ```python
  "order_book_stats.json",
  "sizing_data.json",
  "portfolio_context.json",
  "fill_quality.json",
  ```
- (Confirm exact filenames against `skills/build_daily_metrics.py` writers before final code lands — they may be hyphenated or differently named.)
- **Verify:** new `tests/test_instrumentation_scorer.py` (file does not yet exist) — fixture with all four files; expect coverage score increase relative to a fixture without them.

**WFO → calibration tracker prediction call.**
- File: `orchestrator/handlers.py::handle_wfo`, after the `SuggestionRecord` is constructed (around line 1180-1190):
  ```python
  if self._calibration_tracker is not None:
      self._calibration_tracker.record_prediction(
          suggestion_id=suggestion_id,
          bot_id=bot_id,
          param_category="wfo_optimization",
          predicted_improvement=float(robustness_score or 0.0),
          predicted_routing="adopt" if recommendation == WFORecommendation.ADOPT else "experiment",
      )
  ```
- `BacktestCalibrationTracker` is already wired into `auto_outcome_measurer.py` for the outcome side, so this call alone closes the prediction→outcome loop for WFO recommendations.
- **Verify:** new test in `tests/test_handlers.py` — invoke `handle_wfo` with a fake report → expect entries in `data/calibration/backtest_calibration.jsonl`.

**Outcome → HypothesisLibrary feedback (non-A/B path).**
- File: `skills/auto_outcome_measurer.py`
- Constructor: accept `hypothesis_library: HypothesisLibrary | None = None` and `suggestion_tracker: SuggestionTracker | None = None`.
- After persisting `OutcomeMeasurement` (currently at lines 188-191 where calibration tracker is called), add:
  ```python
  if self._hypothesis_library is not None and self._suggestion_tracker is not None:
      sugg = next((s for s in self._suggestion_tracker.load_all()
                   if s.get("suggestion_id") == suggestion_id), None)
      if sugg and sugg.get("hypothesis_id"):
          positive = (delta or 0) > 0
          self._hypothesis_library.record_outcome(sugg["hypothesis_id"], positive=positive)
  ```
- File: `orchestrator/app.py` — pass `hypothesis_library=hypothesis_library` and `suggestion_tracker=suggestion_tracker` into `AutoOutcomeMeasurer` construction.
- **Verify:** extend `tests/test_auto_outcome_measurer.py` — record a SuggestionRecord with `hypothesis_id="h_alpha_decay"`, run measurement, assert `HypothesisLibrary.get_track_record()["h_alpha_decay"]["outcomes_positive"]` (or `outcomes_negative`) incremented.

### Part 2 — Event + Deployment lineage (additive, defaults None)

**File `schemas/events.py`** — add to both `TradeEvent` and `MissedOpportunityEvent`:
```python
deployment_id: str | None = None
experiment_id: str | None = None
variant_id: str | None = None
parameter_set_id: str | None = None
strategy_version: str | None = None
config_version: str | None = None
signal_generation_version: str | None = None
code_sha: str | None = None
```

Also set `model_config = ConfigDict(extra="ignore")` on both models so an older relay/bot sending unknown fields parses cleanly. This is an extra robustness improvement; today the default Pydantic v2 behavior would reject a relay producing unrecognized fields during a migration window.

**File `schemas/deployment_monitoring.py::DeploymentRecord`** — add:
```python
affected_population: list[str] = Field(default_factory=list)  # event_id refs
variant_id: str | None = None
parameter_set_id: str | None = None
strategy_version: str | None = None
config_version: str | None = None
```

`affected_population` deliberately stays empty until the future causal evaluator
populates it; the field is added now so the slot exists without further
schema migrations.

**Verify:**
- New `tests/test_event_schemas.py` (does not yet exist) — round-trip a JSONL line *without* the new fields; round-trip with them populated; both stable.
- New `tests/test_deployment_monitoring.py` (does not yet exist) — same shape for `DeploymentRecord`.

### Part 3 — ProposalLedger spine

**New schema: `schemas/proposal_ledger.py`**

```python
from __future__ import annotations
from datetime import datetime, timezone
from enum import Enum
from pydantic import BaseModel, Field

class ProposalSource(str, Enum):
    LLM_DAILY = "llm_daily"
    LLM_WEEKLY = "llm_weekly"
    DETERMINISTIC = "deterministic"
    DISCOVERY = "discovery"
    WFO = "wfo"
    PARAMETER_SEARCH = "parameter_search"
    STRUCTURAL_EXPERIMENT = "structural"
    PORTFOLIO = "portfolio"
    TRANSFER = "transfer"
    INSTRUMENTATION = "instrumentation"

class ProposalKind(str, Enum):
    PARAMETER_CHANGE = "parameter_change"
    STRUCTURAL_CHANGE = "structural_change"
    NEW_STRATEGY = "new_strategy"
    PORTFOLIO_CHANGE = "portfolio_change"
    SEARCH_SPACE_CHANGE = "search_space_change"
    INSTRUMENTATION_REQUEST = "instrumentation_request"
    BUG_FIX = "bug_fix"

class ProposalCandidate(BaseModel):
    proposal_id: str                          # deterministic 16-char sha256 prefix
    source: ProposalSource
    kind: ProposalKind
    bot_id: str
    strategy_id: str = ""
    lifecycle_stage: str = ""                 # signal/entry/management/exit/portfolio
    hypothesis_id: str = ""                   # links to HypothesisLibrary if known
    title: str
    description: str = ""
    expected_mechanism: str = ""
    affected_parameters: list[str] = Field(default_factory=list)
    affected_files: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    evaluation_method: str = ""               # parameter_search/wfo/experiment/replay/approval
    linked_diagnostics: list[str] = Field(default_factory=list)
    linked_run_id: str = ""                   # source agent run
    suggestion_id: str = ""                   # cross-link to SuggestionTracker
    experiment_id: str = ""                   # cross-link to A/B or structural exp
    deployment_id: str = ""                   # cross-link to DeploymentRecord
    proposed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class ProposalEvaluation(BaseModel):
    proposal_id: str
    method: str                               # parameter_search/wfo/experiment/...
    summary: str = ""
    objective_score: float = 0.0
    confidence: float = 0.0
    decision: str                             # approve/reject/experiment/defer/instrument
    decision_reason: str = ""
    evidence_paths: list[str] = Field(default_factory=list)
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class ProposalOutcome(BaseModel):
    proposal_id: str
    deployment_id: str = ""
    objective_delta: float = 0.0
    verdict: str                              # improved/regressed/inconclusive/insufficient_data
    measurement_path: str = ""                # link to OutcomeMeasurement record
    measured_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class ProposalRecord(BaseModel):
    candidate: ProposalCandidate
    evaluations: list[ProposalEvaluation] = Field(default_factory=list)
    outcomes: list[ProposalOutcome] = Field(default_factory=list)
```

**`SuggestionRecord` and `OutcomeMeasurement` additions (linkage only):**
- `schemas/suggestion_tracking.py::SuggestionRecord` — add `proposal_id: str | None = None` (additive, optional).
- `schemas/outcome_measurement.py::OutcomeMeasurement` — add `hypothesis_id: str | None = None` and `proposal_id: str | None = None`.

**New skill: `skills/proposal_ledger.py`**

Modeled on `SuggestionTracker` (atomic JSONL with `threading.Lock`):
- Storage: `memory/findings/proposal_ledger.jsonl` (matches existing `memory/findings/` convention used by SuggestionTracker, HypothesisLibrary).
- Internal helpers reuse `skills/_atomic_write.py::atomic_rewrite_jsonl(path, records)` and a `_read_jsonl` parse loop identical to SuggestionTracker's.
- Public API:
  ```python
  class ProposalLedger:
      def __init__(self, store_dir: Path) -> None: ...
      def record_candidate(self, candidate: ProposalCandidate) -> bool: ...   # dedup by proposal_id
      def record_evaluation(self, proposal_id: str, evaluation: ProposalEvaluation) -> bool: ...
      def record_outcome(self, proposal_id: str, outcome: ProposalOutcome) -> bool: ...
      def get_by_id(self, proposal_id: str) -> ProposalRecord | None: ...
      def list_by_bot(self, bot_id: str, lifecycle_stage: str | None = None,
                      kind: ProposalKind | None = None) -> list[ProposalRecord]: ...
      def list_recent(self, days: int = 30) -> list[ProposalRecord]: ...
      def list_open(self) -> list[ProposalRecord]: ...   # candidates with no terminal outcome
  ```
- Storage shape: each line is one event (`{"type": "candidate"|"evaluation"|"outcome", ...payload}`). Reading scans the file once and groups by `proposal_id` into `ProposalRecord` objects. Writing always appends; status updates that change a record (e.g. cumulative metadata) use `atomic_rewrite_jsonl` with the same lock pattern as SuggestionTracker.
- Deterministic `proposal_id`: `sha256(f"{source.value}|{bot_id}|{kind.value}|{title.strip().lower()}|{proposed_at.date().isoformat()}").hexdigest()[:16]`.

**Handler integration (`orchestrator/handlers.py`):**

The ledger is wired in **alongside**, not replacing, existing trackers. Each
proposal-producing call site adds one ledger write. `Handlers.__init__` gains a
`proposal_ledger: ProposalLedger | None = None` parameter (parallel to
`suggestion_tracker`); every write is guarded by `if self._proposal_ledger:`.

| Existing call site | Action |
|--------------------|--------|
| `_record_suggestions` (handlers.py:2673) | For each `StrategySuggestion`: derive `kind` from `tier`, build `ProposalCandidate(source=DETERMINISTIC, ...)`, stamp `candidate.suggestion_id`, write back the `proposal_id` onto the `SuggestionRecord` before saving so they cross-link. |
| `_record_agent_suggestions` (handlers.py:2782) | Same, with `source=LLM_WEEKLY` (or `LLM_DAILY` based on the calling handler — pass a `source` argument from the caller). The existing `hypothesis_id` extraction (line 2915) carries through to `ProposalCandidate.hypothesis_id`. |
| `_record_structural_experiments` (handlers.py:2939) | `source=STRUCTURAL_EXPERIMENT`, `kind=STRUCTURAL_CHANGE`. Cross-link via `candidate.experiment_id`. |
| `handle_discovery_analysis` (handlers.py:1422) | Iterate `discoveries` / `strategy_ideas` / `structural_proposals`. One ledger candidate per item, `source=DISCOVERY`. Use `proposal.lifecycle_stage` if the discovery output carries it; otherwise leave blank. |
| `handle_wfo` (handlers.py:1041, near line 1180) | `source=WFO`, `kind=PARAMETER_CHANGE`. Immediately append a `ProposalEvaluation(method="wfo", objective_score=robustness_score, decision="approve" if ADOPT else "experiment")`. |
| `_record_portfolio_proposals` (handlers.py:2465) | `source=PORTFOLIO`, `kind=PORTFOLIO_CHANGE`. |
| Transfer proposal builder writers | `source=TRANSFER`. Confirm exact write site in `skills/transfer_proposal_builder.py`. |

Reject decisions: where the existing path emits a deferred / rejected suggestion,
also write a `ProposalEvaluation(decision="reject", decision_reason=...)`. The
unified "decision quality" metric depends on seeing rejects, not just accepts.

**App wiring (`orchestrator/app.py`):**
- Construct `proposal_ledger = ProposalLedger(store_dir=Path("memory/findings"))` once during runtime build.
- Pass into `Handlers(...)` as `proposal_ledger=proposal_ledger`.
- Pass into `AutoOutcomeMeasurer(...)` as `proposal_ledger=proposal_ledger` so the measurer also writes a `ProposalOutcome` when a measured suggestion has a `proposal_id`.

**Outcome integration (`skills/auto_outcome_measurer.py`):**
- After persisting `OutcomeMeasurement` and the `BacktestCalibrationTracker.record_outcome` call (currently lines 188-191), add:
  ```python
  if self._proposal_ledger is not None and sugg and sugg.get("proposal_id"):
      self._proposal_ledger.record_outcome(
          sugg["proposal_id"],
          ProposalOutcome(
              proposal_id=sugg["proposal_id"],
              objective_delta=float(delta or 0.0),
              verdict=measurement.verdict.value if hasattr(measurement.verdict, "value") else str(measurement.verdict),
              measurement_path=str(self._outcomes_path),
          ),
      )
  ```

### Part 4 — ContextBuilder enrichment (small, additive)

`analysis/context_builder.py::base_package` — add one new loader and inject:
- `load_recent_proposal_outcomes(bot_id: str, days: int = 30) -> list[dict]` — reads ledger via `proposal_ledger.list_by_bot(bot_id)` filtered to records where the most recent `ProposalOutcome.measured_at` is within `days`. Returns lightweight dicts (id, kind, source, verdict, objective_delta).
- Inject result into `data["recent_proposal_outcomes"]`.
- Update the daily/weekly prompt instruction templates to reference this new field so the LLM consumes "what proposals have been tried recently and what came of them" without joining three trackers.

## Critical files modified

| File | Change |
|------|--------|
| `orchestrator/app.py` | Unconditional `experiment_check` registration (A2); construct `ProposalLedger`; inject into `Handlers` and `AutoOutcomeMeasurer`; inject `HypothesisLibrary` + `SuggestionTracker` into `AutoOutcomeMeasurer` |
| `orchestrator/handlers.py` | A8 sim→build_report wiring; WFO calibration prediction call; ledger writes at all 7 proposal sites; `Handlers.__init__` accepts `proposal_ledger` |
| `analysis/strategy_engine.py::build_report` | 3 new optional kwargs; 3 new detector branches |
| `analysis/context_builder.py` | New `load_recent_proposal_outcomes`; injected into `base_package` |
| `skills/instrumentation_scorer.py` | 4 new entries each in `_CAPABILITY_FIELDS` and `_OPTIONAL_FILES` |
| `skills/auto_outcome_measurer.py` | Accept `hypothesis_library`, `suggestion_tracker`, `proposal_ledger`; on outcome, call `HypothesisLibrary.record_outcome` (when suggestion has `hypothesis_id`) and `ProposalLedger.record_outcome` (when suggestion has `proposal_id`) |
| `skills/proposal_ledger.py` | **NEW** (~180 lines, modeled on SuggestionTracker) |
| `schemas/proposal_ledger.py` | **NEW** (~80 lines, see Part 3) |
| `schemas/events.py` | 8 lineage fields on `TradeEvent` + `MissedOpportunityEvent`; `extra="ignore"` on both |
| `schemas/deployment_monitoring.py` | 5 lineage fields on `DeploymentRecord` |
| `schemas/suggestion_tracking.py` | Optional `proposal_id` on `SuggestionRecord` |
| `schemas/outcome_measurement.py` | Optional `proposal_id` and `hypothesis_id` on `OutcomeMeasurement` |

## Tests

Existing test files to extend:
- `tests/test_handlers.py` — assert ledger writes at each of the 7 proposal sites; assert WFO calibration prediction call
- `tests/test_strategy_engine.py` — three new detectors fed by sim outputs
- `tests/test_auto_outcome_measurer.py` — outcome → HypothesisLibrary link; outcome → ProposalLedger link
- `tests/test_app_wiring.py` — `experiment_check` job present even when `experiment_manager is None`; ProposalLedger constructed and injected

New test files to create:
- `tests/test_proposal_ledger.py` — record/load/dedup; evaluation+outcome chain; `list_by_bot` / `list_recent` / `list_open` filters
- `tests/test_instrumentation_scorer.py` — fixture with the 4 added artifact files vs without
- `tests/test_event_schemas.py` — backward-compat round-trip with and without lineage fields
- `tests/test_deployment_monitoring.py` — DeploymentRecord lineage round-trip

## Verification end-to-end

1. **Backward compat first.** Run existing `pytest` before code changes are merged; the schema work is additive, so the suite stays green.
2. **Integration smoke test.** Add `tests/test_proposal_ledger_e2e.py`:
   - Spawn the weekly handler with a fixture event set
   - Assert `memory/findings/proposal_ledger.jsonl` has at least one record per non-portfolio source: `LLM_WEEKLY`, `DETERMINISTIC`, `WFO` (if WFO ran), `STRUCTURAL_EXPERIMENT`
   - Assert the matching `SuggestionRecord` carries the same `proposal_id`
   - Run a synthetic `auto_outcome_measurer.measure(...)` for a suggestion and assert both `HypothesisLibrary.outcomes_positive` and `ProposalLedger.outcomes` updated
3. **Manual run.** Run `python -m orchestrator.scheduler --run-now weekly_summary` against a stubbed bot dataset; inspect `memory/findings/proposal_ledger.jsonl` and the agent run folder for `recent_proposal_outcomes` injected by ContextBuilder.
4. **Regression sweep.** This repo's xdist sometimes hangs — run the directly-affected files serially:
   ```
   pytest -o "addopts=" tests/test_handlers.py tests/test_strategy_engine.py \
     tests/test_proposal_ledger.py tests/test_app_wiring.py \
     tests/test_event_schemas.py tests/test_deployment_monitoring.py \
     tests/test_instrumentation_scorer.py tests/test_auto_outcome_measurer.py
   ```
5. **Full suite.** `pytest` (with default `-n auto --dist loadfile`). Expect zero new failures: schema additions are optional, ledger writes are guarded, `build_report` extensions default to `None`, and `experiment_check` previously gated by `experiment_manager` continues to no-op the A/B block when that manager is absent.

## Definition of done

- All 7 proposal-producing call sites write a `ProposalCandidate` with consistent fields
- `tests/test_proposal_ledger_e2e.py` passes — one weekly cycle produces a unified ledger record set linked to suggestion records
- `auto_outcome_measurer` writes both `SuggestionOutcome` and `ProposalOutcome` for every measured suggestion, and updates `HypothesisLibrary.effectiveness` for any linked hypothesis
- `TradeEvent` / `MissedOpportunityEvent` / `DeploymentRecord` round-trip cleanly with and without the new lineage fields; old JSONL files parse unchanged
- `instrumentation_scorer` reports `order_book_stats`, `sizing`, `portfolio_context`, `fill_quality` coverage
- `StrategyEngine.build_report` consumes `exit_sweep` / `filter_sensitivity` / `counterfactual` and emits at least one new deterministic suggestion when any of them flag an issue
- `app.py` schedules the `experiment_check` job regardless of `experiment_manager` initialization, and structural-experiment evaluation runs on schedule even when A/B testing is disabled
- WFO handler records calibration **predictions**; outcome measurer feeds **HypothesisLibrary** for non-A/B suggestion outcomes
- Full `pytest` run is green
