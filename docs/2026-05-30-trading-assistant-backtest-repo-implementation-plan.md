# Trading Assistant Backtest Repo Implementation Plan

Date: 2026-05-30

Target repo: `trading_assistant_backtest`

Purpose: create the local full-fidelity replay, diagnostics, phased-auto, OOS-repair,
confirmatory rerank, and artifact-emission repo consumed by `trading_assistant`.

## Executive Decision

Build `trading_assistant_backtest` as a manifest-driven experiment lab, not as another
control plane and not as the production trading repo. It should read only the frozen
`MonthlyRunManifest` and referenced data/plugin contracts, execute full-fidelity replay
and optimization, and write the artifact contract that `trading_assistant` validates.

Do not copy every historical phased-auto, OOS-repair, and promotion script as separate
frameworks. The optimal shape is:

```text
one monthly runner contract
  -> one shared phased-auto / repair orchestration core
  -> strategy-specific plugins for data loading, replay, candidates, scoring, diagnostics
  -> live-strategy adapters that prove decision parity against the actual trading repo
```

Historical one-off round scripts should become reference material, regression fixtures, or
strategy plugin candidate-family definitions. They should not become first-class entry
points in the new repo.

The repo must make this contract true:

```text
trading_assistant writes run_manifest.json
  -> trading_assistant_backtest validates manifest, data bundle, plugin contract, repo SHAs
  -> runner executes diagnostics, phased-auto, optional OOS repair, confirmatory follow-up
  -> runner writes artifact_index.json plus required artifacts under artifact_root
  -> trading_assistant validates artifacts and routes model review / approval
```

## Boundaries

`trading_assistant_backtest` owns:

- Manifest-backed incumbent replay and diagnostics.
- Full-fidelity strategy backtest adapters.
- Shared phased-auto orchestration, greedy selection, phase state, checkpoints, and gates.
- Conditional OOS repair, ablation, perturbation, rollback, and targeted repair search.
- Repair-centered confirmatory follow-up and round_N+1 optimized backtest recommendation.
- Replay parity, decision parity, and strategy plugin conformance evidence.
- Candidate workspaces, attempts, retry/backoff, stall detection, and runner observability.
- Artifact writing under `MonthlyRunManifest.artifact_root`.
- Compatibility with `contracts.validate_monthly_runner`.

It must not own:

- Canonical market-data storage or data downloads. That belongs in `trading_assistant_data`.
- Scheduling, approval routing, Telegram cards, ledgers, or model-review governance.
- Live order routing, OMS mutation, deployment state, or VPS commands.
- The production source of strategy truth. That belongs in the actual trading repo or a
  shared strategy package imported by the actual trading repo.
- Control-plane objective changes. Objective versions and approval policy are frozen by
  `trading_assistant`.

Cross-repo ownership model:

- `trading_assistant` owns the control plane: schedules, telemetry lineage,
  monthly manifest creation, search brief creation, runner invocation, artifact
  validation, model review, candidate gates, repair requests, approval routing,
  ledgers, operator status, and docs. It should not implement full backtest/search
  logic.
- `trading_assistant_backtest` owns reading `run_manifest.json`, loading the data
  bundle and strategy plugin, diagnostics, two-fold phased-auto, OOS repair,
  confirmatory rerank, replay/parity checks, candidate workspaces/attempts, and
  artifact-contract emission. It should not create approvals or mutate live
  deployment state.
- The live trading repo owns production strategy behavior, config schemas, emitted
  telemetry, and deployable strategy/config changes. Structural candidates must
  target this code or a shared strategy package used by this code; backtest-only
  behavior is never approval-ready.
- `trading_assistant_data` owns canonical market data files, checksums, calendars,
  corporate action/adjustment policy, fee/slippage model references, and bundle
  manifests. It must not decide strategy candidates.
- Key principle: this repo may discover candidates; only `trading_assistant` may
  trust, gate, review, and route them.

## Current Contract Inputs From `trading_assistant`

The backtest repo must treat these as the external contract:

- `schemas/monthly_run_manifest.py`
  - Frozen run id, run month, latest-month OOS window, in-sample window,
    artifact root, data bundle path/checksum, backtest command, repo SHAs,
    strategy plugin contract path, round ids, score component cap, `max_workers`,
    monthly search brief, source weekly signal ids, and runner contract versions.
- `schemas/backtest_artifacts.py`
  - `artifact_index.json` container plus required artifacts:
    `coverage_manifest.json`, `incumbent_validation.json`, `gap_attribution.json`,
    `mode_decision.json`, `replay_parity_report.json`, `objective_breakdown.json`,
    `candidate_results.jsonl`, `selected_candidates.json`, `rejected_candidates.jsonl`,
    `monthly_report.md`, `stdout.log`, `stderr.log`, and `exit_status.json`.
  - Optimizer extension artifacts:
    `leakage_report.json`, `cost_sensitivity.json`, `fold_validation.json`,
    `outlier_sensitivity.json`, `portfolio_synergy.json`, `fold_manifest.json`,
    `rounds_manifest.json`, `end_of_round_diagnostics.json`,
    `llm_experiment_plan.json`, `candidate_workspace_manifest.json`,
    `candidate_attempts.jsonl`, `runner_observability.json`, and
    `confirmatory_rerank.json`.
  - OOS-repair artifact:
    `repair_ablation_matrix.jsonl`.
  - Structural candidate artifacts:
    `structural_candidate_plan.json`, `live_repo_patch.diff`,
    `backtest_adapter_patch.diff`, `config_patch.diff`, and
    `decision_parity_report.json`.
- `schemas/data_bundle_manifest.py`
  - Optimizer runs require an authoritative `DataBundleManifest` and matching bundle checksum.
- `schemas/strategy_plugin_contract.py`
  - Plugin id, live repo path/SHA, backtest adapter path/SHA, config schema version,
    decision API version, required telemetry schemas, supported symbols/timeframes,
    parity fixture set, and maturity.
- `schemas/decision_parity.py`
  - Structural candidates must pass decision parity for signals, filters, entries,
    exits, stops, sizing, risk caps, and order intent.
- `schemas/monthly_optimizer.py`
  - Two-fold purged fold manifest, optimizer experiment plan, candidate workspace
    manifest, candidate attempt ledger, confirmatory rerank, and rounds manifest.
- `contracts/monthly_runner_contract.py`
  - The reusable validator. The backtest repo should run this validator before claiming
    conformance, and `trading_assistant` will run the same checks after subprocess exit.

Current validation already exists in `trading_assistant`:

- `skills/backtest_runner_client.py` writes captured stdout/stderr/exit status after
  subprocess completion, requires `artifact_index.json`, validates path containment,
  stale artifacts, JSON/JSONL parsing, manifest id, and data bundle checksum.
- `skills/monthly_optimizer_runner.py` validates the Phase 4 optimizer sequence:
  core artifacts, two-fold/window alignment, search-brief consumption, candidate
  attempts, confirmatory rerank, rounds manifest, selected candidate lineage,
  runner contract version, structural parity, and strategy plugin maturity.
- `contracts.validate_monthly_runner` and
  `tests/contract_fixtures/monthly_runner_contract/runner.py` are the upstream
  conformance harness. The backtest repo should reuse these checks instead of
  reimplementing control-plane validation as business logic.

Current invocation detail:

- `orchestrator/backtest_invocation.py` defaults to:

```bash
python -m backtests.shared.monthly_repair --manifest <run_manifest.json>
```

The new repo should implement this compatibility module and also expose a clearer native
entry point:

```bash
python -m trading_assistant_backtest.monthly --manifest <run_manifest.json>
```

`MonthlyRunManifest.backtest_command` can override either path, but the compatibility
module avoids needless control-plane changes.

Contract sync rule:

- During local development, import the installed `trading_assistant` contract package or
  add the sibling repo to the test environment so the same Pydantic models validate both
  sides.
- If the backtest repo later vendors schemas, vendor generated JSON schemas and pin the
  schema versions. Do not hand-maintain divergent copies of these contracts.
- CI should run the `trading_assistant` conformance fixture against the real runner command
  before any runner is considered compatible.

## Reference Repo Audit

### `_references/trading`

High-value reusable parts:

- Shared phased-auto framework:
  - `_references/trading/backtests/shared/auto/plugin.py`
  - `_references/trading/backtests/shared/auto/types.py`
  - `_references/trading/backtests/shared/auto/greedy_optimizer.py`
  - `_references/trading/backtests/shared/auto/phase_runner.py`
  - `_references/trading/backtests/shared/auto/phase_state.py`
  - `_references/trading/backtests/shared/auto/phase_gates.py`
  - `_references/trading/backtests/shared/auto/phase_analyzer.py`
  - `_references/trading/backtests/shared/auto/phase_logging.py`
  - `_references/trading/backtests/shared/auto/round_manager.py`
  - `_references/trading/backtests/shared/auto/provenance.py`
  - `_references/trading/backtests/shared/auto/cache_keys.py`
  - `_references/trading/backtests/shared/auto/replay_bundle.py`
- Shared smoke/OOS pattern:
  - `_references/trading/backtests/shared/smoke/latest_oos_smoke.py`
  - `_references/trading/backtests/swing/auto/incumbent_repair.py`
  - `_references/trading/backtests/swing/auto/oos_repair_diagnostics.py`
- Parity and replay primitives:
  - `_references/trading/backtests/shared/parity/decision_capture.py`
  - `_references/trading/backtests/shared/parity/replay_driver.py`
  - `_references/trading/backtests/shared/parity/execution_adapters.py`
  - `_references/trading/backtests/shared/parity/trade_outcomes.py`
  - `_references/trading/backtests/shared/parity/calibration_report.py`
- Strategy plugin examples:
  - momentum: `nqdtc`, `vdubus`, `downturn`, `nq_regime`, `portfolio_synergy`
  - swing: `atrss`, `helix`, `tpc`, `portfolio_synergy`
  - stock: `alcb`, `iaric`, `portfolio_synergy`
  - deferred futures research family: `ivb_auction`, `po3_reversal`
  - regime: `crisis`
- Diagnostics examples:
  - `_references/trading/backtests/swing/analysis/*`
  - `_references/trading/backtests/stock/analysis/*`
  - `_references/trading/backtests/regime/analysis/*`

Port:

- The shared auto framework concepts, with contract adaptations for
  `MonthlyRunManifest`, `DataBundleManifest`, artifact containment, candidate attempts,
  and score component cap.
- Provenance and round manager ideas, especially selection vs diagnostics fingerprints.
- Latest-OOS smoke window resolution and repair candidate stages, but rewritten against
  manifest windows rather than auto-detected repo-local data.
- Decision stream normalization and replay-driver ideas for parity.
- Strategy-specific phase/candidate definitions only for strategies that are actually
  wired to a live strategy plugin contract.

Do not port as first-class entry points:

- One-off `run_round*.py`, `promote_round*.py`, `*_deep_dive.py`, and exploratory
  scripts. Convert useful candidate families or diagnostics into plugins.
- Backtest-owned raw data folders. Data should come from `trading_assistant_data`.
- Any promotion/deployment script that mutates live config or deployment state.

### `_references/crypto_trader`

High-value reusable parts:

- Full-fidelity backtest runner and split handling:
  - `_references/crypto_trader/src/crypto_trader/backtest/runner.py`
  - `_references/crypto_trader/src/crypto_trader/backtest/metrics.py`
  - `_references/crypto_trader/src/crypto_trader/backtest/diagnostics.py`
  - `_references/crypto_trader/src/crypto_trader/backtest/profiles.py`
- Strategy runtime parity:
  - `_references/crypto_trader/src/crypto_trader/core/strategy_runtime.py`
  - `_references/crypto_trader/src/crypto_trader/parity/report.py`
  - `_references/crypto_trader/src/crypto_trader/parity/shadow.py`
  - `_references/crypto_trader/tests/parity/*`
- Optimizer contracts and preflight:
  - `_references/crypto_trader/src/crypto_trader/optimize/contracts.py`
  - `_references/crypto_trader/src/crypto_trader/optimize/phase_runner.py`
  - `_references/crypto_trader/src/crypto_trader/optimize/phase_state.py`
  - `_references/crypto_trader/src/crypto_trader/optimize/greedy_optimizer.py`
  - `_references/crypto_trader/src/crypto_trader/optimize/phase_gates.py`
  - `_references/crypto_trader/src/crypto_trader/optimize/phase_analyzer.py`
- Strategy implementations and plugin examples:
  - `strategy/trend`, `strategy/breakout`, `strategy/momentum`
  - `portfolio/backtest_runner.py`, `portfolio/sweep.py`
  - `optimize/trend_round*_plugin.py`, `optimize/*_phased.py`,
    `optimize/portfolio_round2_phased.py`

Port:

- Contract hashing and profile preflight ideas: economic profile, code identity,
  data fingerprint, plugin code hash, phase contract summary, and score-spec hash.
- Strategy runtime and parity report ideas for a unified decision trace.
- Crypto runner adapters as early replay targets once the data repo publishes
  authoritative Hyperliquid bundles.
- Portfolio-level backtest runner patterns for cross-strategy synergy checks.

Do not port:

- `scripts/promote_*.py`, `scripts/run_*round*.py`, output folders, or historical
  round artifacts as executable workflow.
- Live exchange clients, OMS stores, or mutable runtime state except parity fixtures.

### `_references/k_stock_trader`

High-value reusable parts:

- Newer shared auto fork with official metric contract and artifact hygiene:
  - `_references/k_stock_trader/backtests/auto/shared/plugin.py`
  - `_references/k_stock_trader/backtests/auto/shared/phase_runner.py`
  - `_references/k_stock_trader/backtests/auto/shared/greedy_optimizer.py`
  - `_references/k_stock_trader/backtests/auto/shared/round_manager.py`
  - `_references/k_stock_trader/backtests/analysis/artifact_hygiene.py`
- OOS ablation and repair:
  - `_references/k_stock_trader/backtests/auto/oos_ablation.py`
- Replay and completed-bar policy:
  - `_references/k_stock_trader/backtests/core/replay_bundle.py`
  - `_references/k_stock_trader/backtests/core/replay_events.py`
  - `_references/k_stock_trader/backtests/core/completed_bar_policy.py`
  - `_references/k_stock_trader/backtests/engine/replay.py`
  - `_references/k_stock_trader/backtests/engine/sim_broker.py`
- Strategy plugin and runner examples:
  - `_references/k_stock_trader/backtests/strategies/common/plugin_base.py`
  - `_references/k_stock_trader/backtests/strategies/registry.py`
  - `_references/k_stock_trader/backtests/strategies/kalcb/*`
  - `_references/k_stock_trader/backtests/strategies/olr/*`
  - `_references/k_stock_trader/backtests/strategies/portfolio_synergy/*`
- Live/backtest parity fixtures:
  - `_references/k_stock_trader/tests/fixtures/live_replay_parity/*`
  - `_references/k_stock_trader/tests/backtests/strategies/test_olr_kalcb_live_replay_artifact_parity.py`
- Strategy core production-style packages:
  - `_references/k_stock_trader/strategy_kalcb/core/*`
  - `_references/k_stock_trader/strategy_olr/core/*`

Port:

- The newer artifact hygiene and official metric contract checks.
- Completed-bar and no-lookahead policy as replay invariants.
- `oos_ablation.py` ideas for loading full round chains and evaluating cumulative
  accepted mutations across all previous rounds.
- OLR/KALCB plugin concepts after the data repo has authoritative KRX bundles.

Do not port:

- KIS live account/order methods, deployment service code, cron scripts, or runtime
  OMS mutation.
- Research-only scripts under `scripts/` as first-class runner paths. Convert durable
  logic into plugins, tests, or repair candidate builders.

## Framework Consolidation Decision

Use a single shared backtest framework in `trading_assistant_backtest`, assembled from
the best reference parts:

- Base phase runner: start from the newer `_references/k_stock_trader/backtests/auto/shared`
  shape because it already includes official metric basis, artifact hygiene, and source
  fingerprint awareness.
- Provenance: port the richer `_references/trading/backtests/shared/auto/provenance.py`
  selection/diagnostics fingerprint model.
- Optimizer preflight: port the useful parts of
  `_references/crypto_trader/src/crypto_trader/optimize/contracts.py`, especially code
  identity, data fingerprint, profile hash, and phase contract hashing.
- OOS repair: implement one generic repair engine inspired by
  `latest_oos_smoke.py`, `incumbent_repair.py`, and `oos_ablation.py`.
- Parity: implement one normalized decision trace and map reference-specific events into
  it through adapters.

The resulting framework should have one plugin protocol:

```python
class MonthlyStrategyPlugin(Protocol):
    plugin_id: str
    strategy_id: str
    family: str
    supported_symbols: list[str]
    supported_timeframes: list[str]

    def load_baseline(self, manifest, data_bundle) -> BaselineState: ...
    def run_incumbent(self, window: WindowSpec, baseline: BaselineState) -> ReplayResult: ...
    def run_diagnostics(self, replay: ReplayResult) -> DiagnosticsBundle: ...
    def build_phase_specs(self, diagnostics, experiment_plan, search_brief) -> list[PhaseSpec]: ...
    def evaluate_candidate(self, candidate, window: WindowSpec) -> CandidateEvaluation: ...
    def build_repair_candidates(self, failure_analysis, round_chain) -> list[RepairCandidate]: ...
    def build_confirmatory_variants(self, primary, context) -> list[Candidate]: ...
    def write_round_n_plus_1(self, candidate, output_dir) -> RoundAdoptionArtifacts: ...
    def run_decision_parity(self, candidate, fixtures) -> DecisionParityReport: ...
```

Reference strategy code can keep native internal types, but the monthly runner should only
see normalized `ReplayResult`, `CandidateEvaluation`, diagnostics, candidates, and parity
reports.

## Repository Layout

```text
trading_assistant_backtest/
  README.md
  pyproject.toml
  .env.example
  MONTHLY_OPTIMIZER_WORKFLOW.md
  src/trading_assistant_backtest/
    __init__.py
    monthly.py
    contract_models.py
    contract_loader.py
    artifact_writer.py
    artifact_index.py
    manifest_loader.py
    observability.py
    paths.py
    scoring/
      objective.py
      gates.py
      cost_sensitivity.py
      outlier_sensitivity.py
      leakage.py
      portfolio_synergy.py
    data/
      bundle_loader.py
      slice_index.py
      replay_frames.py
    replay/
      types.py
      windows.py
      split_runner.py
      parity.py
      decision_trace.py
      completed_bar_policy.py
    auto/
      plugin.py
      types.py
      phase_runner.py
      phase_state.py
      greedy_optimizer.py
      phase_gates.py
      phase_analyzer.py
      phase_logging.py
      round_manager.py
      provenance.py
      cache_keys.py
      candidate_workspace.py
      candidate_attempts.py
    repair/
      trigger.py
      failure_analysis.py
      ablation.py
      perturbation.py
      rollback.py
      targeted.py
      confirmatory.py
    planner/
      prompt_builder.py
      model_invoker.py
      plan_validator.py
      deterministic_fallback.py
    structural/
      workspace.py
      patching.py
      test_runner.py
      parity_harness.py
    strategies/
      registry.py
      common/
        plugin_base.py
        metrics.py
        diagnostics.py
      crypto/
        trend.py
        breakout.py
        momentum.py
        portfolio.py
      krx/
        kalcb.py
        olr.py
        portfolio_synergy.py
      trading/
        momentum.py
        swing.py
        stock.py
        regime.py
  backtests/
    shared/
      monthly_repair.py
  tests/
    contract/
    fixtures/
    unit/
    integration/
```

`backtests/shared/monthly_repair.py` is a compatibility wrapper that imports and calls
`trading_assistant_backtest.monthly`.

## Runner CLI Contract

Primary command:

```bash
python -m trading_assistant_backtest.monthly --manifest path/to/run_manifest.json
```

Compatibility command:

```bash
python -m backtests.shared.monthly_repair --manifest path/to/run_manifest.json
```

Required behavior:

- Load `MonthlyRunManifest`.
- Resolve all manifest paths to absolute paths without rewriting the manifest.
- Validate `artifact_root` exists or can be created.
- Validate `artifact_root` path containment for every emitted artifact.
- Validate `DataBundleManifest` status/checksum.
- Validate the strategy plugin contract and enforce maturity gates: diagnostic plugins
  may produce diagnostics/research only, `shadow_validated` plugins may run optimizer
  shadow flows, and `approval_ready` is required before structural candidates can be
  approval-ready.
- Validate backtest repo SHA and live repo SHA, when provided.
- Write or mirror `stdout.log`, `stderr.log`, and `exit_status.json` for standalone
  runs and controlled failures. When invoked by `trading_assistant`, the subprocess
  client also writes these captured files after process completion, so the runner
  must at minimum avoid conflicting paths and include the keys in `artifact_index.json`.
- Write `artifact_index.json` last.
- Never write outside `artifact_root` except candidate workspaces under the configured
  candidate workspace root.
- Exit non-zero only when the runner cannot produce a contract-complete artifact set.
  For deterministic no-adoption, exit zero and emit a no-adoption `confirmatory_rerank.json`.

Every run should support:

- `--dry-run`
- `--validate-only`
- `--json`
- `--stage diagnostics|phased_auto|oos_repair|confirmatory|all`
- `--max-workers`, defaulting to `manifest.max_workers` and never exceeding it
- `--stall-timeout-seconds`, defaulting to `manifest.stall_timeout_seconds`

## Monthly Sequence

The monthly runner should execute this sequence for `MonthlyRunMode.PHASED_AUTO`.

1. Preflight
   - Validate run manifest, data bundle, strategy plugin contract, workflow contract,
     repo SHAs, artifact root, candidate workspace root, and score component cap.
   - Write initial `runner_observability.json`.
   - Write `coverage_manifest.json` echoing the data bundle checksum.
2. Incumbent validation
   - Load `round_N` strategy and portfolio configs from the manifest/plugin contract.
   - Run full replay diagnostics over the in-sample window.
   - Run latest-month selection-OOS replay separately.
   - Write `incumbent_validation.json`, `objective_breakdown.json`, `gap_attribution.json`,
     `replay_parity_report.json`, and initial `monthly_report.md`.
3. LLM experiment plan
   - Build a prompt from diagnostics, objective breakdown, monthly search brief, prior
     round manifest, plugin capabilities, and overfit constraints.
   - The model may design experiment families, structural candidates, score scaling, and
     phase order.
   - Validate the output as `llm_experiment_plan.json`.
   - Reject or fall back if evidence paths, candidate families, gate expectations, or
     overfit risks are missing.
4. Two-fold phased-auto on in-sample data
   - Build exactly two purged folds using `manifest.in_sample_start/end` and
     `manifest.selection_oos_start/end`.
   - Keep the latest completed month outside phased-auto scoring.
   - Run shared phase/greedy optimizer using the latest optimized configs as baseline.
   - Use `max_workers=2` unless the manifest lowers it.
   - Apply at most seven objective components.
   - Write `fold_manifest.json`, `fold_validation.json`, `leakage_report.json`,
     `cost_sensitivity.json`, `outlier_sensitivity.json`, `portfolio_synergy.json`,
     `candidate_results.jsonl`, and `rejected_candidates.jsonl`.
5. OOS repair trigger
   - Compare phased-auto winner against fold/in-sample expectations and latest-month
     selection-OOS.
   - Trigger repair only when selection-OOS materially underperforms according to a
     deterministic threshold in `repair/trigger.py`.
   - Weekly/monthly search brief hints may order repair work only after this trigger fires.
6. OOS repair, if triggered
   - Evaluate all cumulative accepted mutations from all prior rounds, not only the latest
     round.
   - Run granular ablation, local perturbation, rollback, and targeted additions.
   - Use long timeout, checkpointing, cached replay, and resumable candidate attempts.
   - Write `repair_ablation_matrix.jsonl`.
7. Confirmatory follow-up
   - If OOS repair ran, center follow-up on the repair-recommended candidate.
   - Test targeted local variants around the repair candidate: numeric perturbations,
     add/remove toggles, focused rollback variants, and narrow structural additions.
   - Compare repair variants against incumbent, phased-auto winner, rollback candidates,
     and targeted additions under the same objective.
   - If OOS repair did not run, run the same confirmatory logic around the phased-auto winner.
   - Write `confirmatory_rerank.json`.
8. Adoption artifact
   - Adopt exactly one optimized backtest candidate as `round_N+1`, or emit a deterministic
     no-adoption reason.
   - Write `selected_candidates.json`, `rounds_manifest.json`,
     `end_of_round_diagnostics.json`, and final `monthly_report.md`.
   - Record `round_N+1` as `optimized_backtest_recommendation`, not a live deployment.
9. Final validation
   - Run local equivalent of `contracts.validate_monthly_runner`.
   - Write `artifact_index.json` last.

For `MonthlyRunMode.INCUMBENT_VALIDATION`, run only preflight, incumbent validation,
parity, diagnostics, report, and artifact index. The required artifact contract still
requires `candidate_results.jsonl`, `selected_candidates.json`, and
`rejected_candidates.jsonl`; emit them as empty/diagnostic files rather than omitting
them. Do not emit non-empty selected candidates or optimizer extension artifacts unless
the mode is optimizer/repair/structural and the contract supports them.

For direct `MonthlyRunMode.SMOKE_REPAIR`, skip new phased-auto search and start from the
manifest-provided incumbent/round state plus latest-month underperformance evidence. It
must still emit the optimizer core artifacts required by the contract, including a fold
manifest, confirmatory rerank, rounds manifest, candidate attempts, observability, and
repair ablation matrix. Its `confirmatory_rerank.json` should set
`repair_triggered=true` and `primary_source=smoke_repair`; `mode_decision.json` should
make clear that phased-auto was intentionally bypassed by mode rather than skipped by
model choice.

## LLM Planning And Structural Reasoning

The model is useful for diagnostics synthesis and structural experiment design, but it
must not become the gate.

The planner prompt should ask for:

- signal extraction weaknesses and hidden alpha left on the table;
- signal discrimination failures, especially false positives and low-quality accepted
  trades;
- entry timing and additional entry mechanisms;
- trade management, sizing, stops, partial exits, and exits;
- candidate structural code changes and required live/backtest adapter changes;
- experiment order and dependencies;
- score scaling and no more than seven objective components;
- overfit risks from small samples, sparse regimes, outliers, and correlated candidates;
- candidate families that can target real alpha rather than fit the latest month.

The planner output cannot:

- change the monthly sequence;
- trigger OOS repair;
- weaken parity, data, sample-size, cost, drawdown, or approval gates;
- approve a candidate;
- modify policy memory or objective weights.

The backtest repo should support three planner modes:

- `model`: invoke a configured model/runtime using `MONTHLY_OPTIMIZER_WORKFLOW.md`.
- `manual`: consume a supplied `llm_experiment_plan.json` and validate it.
- `fixture`: generate a deterministic plan for conformance tests.

## Structural Candidate Lane

Structural candidates are first-class phased-auto candidates, not a separate workflow.
They include new signals/features, filter redesign, entry/exit mechanisms, trade
management rules, risk logic, and portfolio coordination changes.

Required process:

1. Create isolated candidate workspaces for the live trading repo and backtest repo.
2. Apply the smallest viable live repo patch first, or patch a shared strategy package
   imported by the live repo.
3. Add or update the backtest adapter.
4. Add or update config/schema patches when needed.
5. Run live repo unit/decision tests.
6. Run backtest adapter tests.
7. Run decision parity fixtures across signals, filters, entries, exits, stops, sizing,
   risk caps, and order intent.
8. Only then allow fold scoring.
9. Copy patch files and parity evidence under `artifact_root`.

Required structural artifact fields:

- `structural_candidate_plan.json`
- `live_repo_patch.diff`
- `backtest_adapter_patch.diff`
- `config_patch.diff` when applicable; it is optional for code-only structural changes,
  but if a selected candidate references `config_patch_path`, the path must exist under
  `artifact_root`.
- `decision_parity_report.json`
- selected candidate fields:
  `live_repo_patch_path`, `backtest_adapter_patch_path`,
  optional `config_patch_path`, `decision_parity_report_path`, repo SHAs, run id,
  manifest id, round ids,
  candidate attempt id, rollback plan, and evidence paths.

Backtest-only approximations are never approval-ready. A candidate can be useful as
diagnostics if it improves replay metrics, but it cannot be selected unless the strategy
plugin contract is mature and decision parity passes.

## Live/Backtest Parity Design

Parity should be decision-level, not PnL-only.

Define a normalized `DecisionTrace` with dimensions:

- signals
- filters
- entries
- exits
- stops
- sizing
- risk_caps
- order_intent

Each strategy plugin must provide:

- fixture input events or bars;
- live strategy outputs from the actual trading repo or shared production package;
- backtest adapter outputs from the candidate adapter;
- normalizers for harmless representation differences;
- a `DecisionParityReport` with zero mismatches for approval-ready structural candidates.

Parity tiers:

- `diagnostic`: adapter can replay enough to produce research diagnostics, but cannot
  emit approval-ready structural candidates.
- `shadow_validated`: adapter has decision parity fixtures and can run monthly phased-auto
  in shadow/experiment mode.
- `approval_ready`: adapter imports production strategy behavior or proves decision-level
  equivalence, has stable fixture set, and can support approval packets.

The next implementation step after this plan should wire `StrategyPluginContract` against
the actual trading repo. Until that is done, mature strategy plugins should remain
`diagnostic` or `shadow_validated`, not `approval_ready`.

## Data Consumption

The backtest repo consumes `trading_assistant_data`; it does not download or canonicalize
data.

Required behavior:

- Read `manifest.data_bundle_manifest_path`, falling back to
  `manifest.market_data_manifest_path` only for transitional manifests where that path is
  already a repo-level `DataBundleManifest`.
- Validate `DataBundleManifest.status == authoritative`.
- Validate `bundle_checksum == manifest.data_bundle_checksum`.
- Load slice manifests and `slice_index.json` if present.
- Map canonical data slices into strategy plugin replay frames.
- Preserve data repo path/SHA, bundle checksum, calendar ids, fee/slippage versions, and
  adjustment policy in every coverage and replay artifact.
- Fail closed when any required data slice, checksum, calendar, or cost policy is missing.

Do not copy parquet files from reference repos into `trading_assistant_backtest`.

## Candidate Orchestration

Use Symphony-style discipline for expensive or structural attempts.

Candidate workspace rules:

- Workspace root defaults to `<artifact_root>/workspaces` unless the manifest provides
  `candidate_workspace_root`.
- Workspace key must pass the same sanitized-key rules as `schemas.monthly_optimizer`.
- Resolved workspace path must stay under workspace root.
- Subprocess `cwd` must equal the candidate workspace.
- Patch artifacts copied into `artifact_root` are the approval evidence; workspace files are
  not enough.

Attempt states:

- `unclaimed`
- `claimed`
- `running`
- `retry_queued`
- `released`
- `succeeded`
- `failed`
- `timed_out`
- `stalled`
- `canceled_by_reconciliation`

Attempt logic:

- Append every transition to `candidate_attempts.jsonl`.
- Retry transient model/subprocess failures with bounded backoff.
- Mark stalled attempts when no progress heartbeat is observed within timeout.
- Reconcile attempts when manifest id, data bundle checksum, backtest repo SHA, live repo SHA,
  plugin contract, or candidate eligibility changes.
- Emit every attempt in `runner_observability.json`.
- No adopted candidate may reference a non-terminal or non-succeeded attempt.

## Artifact Contract Details

`artifact_index.json`:

- `run_id` must match `MonthlyRunManifest.run_id`.
- `manifest_id` is required for phased-auto, smoke-repair, and structural review modes.
- `artifact_root` must match the manifest.
- Every path must resolve under `artifact_root`.
- Required artifacts must exist and be fresh relative to `run_manifest.json`.
- JSON/JSONL artifacts must parse.

`coverage_manifest.json`:

- Must echo `data_bundle_checksum`.
- Must cite `DataBundleManifest.bundle_id` when available.
- Must include data repo SHA, calendars, fee/slippage versions, adjustment policy, and
  slice manifest ids.

`llm_experiment_plan.json`:

- Must include evidence paths.
- Must include candidate families.
- Must include gate expectations.
- Must include overfit risks.
- Must cite `monthly_search_brief_path` when the manifest guidance has content.
- Must preserve `source_weekly_signal_ids` that influenced ordering.
- Must use no more than seven score components.

`selected_candidates.json`:

- For adoption, exactly one candidate.
- For no-adoption, an empty list; the no-adoption reason belongs in
  `confirmatory_rerank.json` and `rounds_manifest.json`.
- Candidate id must match `confirmatory_rerank.adopted_candidate_id`.
- Source must match `confirmatory_rerank.primary_source`.
- Must include run id, manifest id, round id, prior round id, next round id, repo SHAs,
  succeeded attempt id, runner contract version, objective deltas, evidence paths,
  rollback plan, and deterministic gate inputs.

`confirmatory_rerank.json`:

- Must either adopt one candidate or provide a no-adoption reason.
- If repair triggered, `primary_source` must be `smoke_repair`.
- If repair not triggered, `primary_source` must be `phased_auto`.
- Adopted candidate must appear in compared candidates.

`rounds_manifest.json`:

- Must link current round, next round, adopted candidate or no-adoption reason.
- Must not claim live deployment.
- Must cite fold manifest, diagnostics, confirmatory rerank, and decision parity path when
  applicable.

`repair_ablation_matrix.jsonl`:

- Required only when repair is triggered.
- Must include all cumulative accepted mutations from prior rounds, or skip reasons.
- Must identify stage: ablation, perturbation, rollback, targeted, or confirmatory.
- Must include in-sample and selection-OOS deltas.

## Scoring And Gates

Use the control-plane objective vocabulary. The backtest repo may compute replay-native
metrics, but selected candidates must map them into the objective components expected by
`trading_assistant`.

Hard constraints:

- No more than seven score components.
- Latest completed month is selection-OOS, not part of phased-auto fold scoring.
- Trade frequency is a viability gate and an objective-supporting metric, not a license to
  accept negative expectancy.
- Max drawdown and cost realism must be hard gates for aggressive candidates.
- Candidate must pass cost sensitivity, outlier sensitivity, leakage checks, minimum trade
  count, fold support, and portfolio/synergy checks before adoption.
- Structural candidates must pass decision parity before scoring.

Recommended default objective components:

- expected return or net return
- Calmar or drawdown-adjusted return
- profit factor
- expectancy or average R
- max drawdown penalty
- trade frequency viability
- cost/slippage robustness

If process-quality telemetry is not replayable, renormalize replay score without changing
the control-plane objective version, and record the missing component in
`objective_breakdown.json`.

## Implementation Phases

### Phase 0 - Repo Bootstrap

Deliverables:

- Create sibling repo `trading_assistant_backtest`.
- Add Python package, CI, pytest, lint/type checks.
- Add `MONTHLY_OPTIMIZER_WORKFLOW.md`.
- Add native and compatibility CLI modules.
- Add README boundary statement.
- Add dependency groups:
  - core: `pydantic`, `pandas`, `pyarrow`, `numpy`, `pyyaml`
  - optional model: provider/runtime dependencies
  - optional strategy extras: crypto, KRX, futures/IBKR only where needed

Acceptance:

- `python -m trading_assistant_backtest.monthly --help` works.
- `python -m backtests.shared.monthly_repair --help` works.
- No command can place live orders.

### Phase 1 - Contract Models And Validators

Deliverables:

- Vendor or import compatible Pydantic models for the current `trading_assistant` contracts.
- Implement manifest loader, path resolver, artifact writer, and local contract validator.
- Add fixture `MonthlyRunManifest` generators.
- Reuse the existing upstream conformance suite in `trading_assistant`
  (`contracts.validate_monthly_runner` plus the monthly runner fixture) against the
  real backtest command. Add local mirror tests only for runner-owned behavior that the
  control-plane validator cannot see directly, such as CLI flags and planner modes.

Acceptance:

- Fixture incumbent run emits all required artifacts.
- Missing artifact index fails.
- Path outside artifact root fails.
- Stale artifact fails.
- Malformed JSON/JSONL fails.
- Optimizer artifact omissions fail.

### Phase 2 - Data Bundle Reader

Deliverables:

- Implement `DataBundleManifest` reader.
- Implement slice manifest and optional `slice_index.json` loader.
- Implement canonical replay frame adapters.
- Implement coverage artifact writer that echoes bundle checksum.

Acceptance:

- Authoritative bundle is required for optimizer modes.
- Bundle checksum mismatch fails.
- Missing slice manifest fails.
- Fee/slippage/adjustment versions propagate to artifacts.

### Phase 3 - Replay And Parity Kernel

Deliverables:

- Implement normalized replay result types.
- Implement window resolver for in-sample, fold, and latest-month selection-OOS.
- Port completed-bar/no-lookahead policy from KRX and crypto references where relevant.
- Implement decision trace normalizers.
- Implement `DecisionParityReport` writer.
- Implement incumbent `ReplayParityReport` writer.

Acceptance:

- Replay windows match manifest dates.
- No-lookahead tests fail on higher-timeframe premature visibility.
- Decision parity report covers all required dimensions.
- PnL-only parity cannot satisfy structural gates.

### Phase 4 - Shared Auto Core

Deliverables:

- Implement unified plugin protocol.
- Port/adapt phase state, phase runner, greedy optimizer, gates, analyzer, logging, cache keys,
  provenance, and round manager.
- Add official metric/hygiene contract from K stock reference.
- Add crypto-style optimizer preflight hash.
- Add candidate workspace and attempt ledger.

Acceptance:

- Fixture plugin can run two phases with checkpoint resume.
- Score component cap is enforced.
- Rejected candidates and reasons are retained.
- Attempt ledger records terminal states.
- Workspace containment tests pass.

### Phase 5 - Incumbent Diagnostics

Deliverables:

- Implement diagnostics bundle schema.
- Implement full round_N diagnostics before search.
- Implement gap attribution focused on signal extraction, discrimination, entries,
  trade management, exits, sizing, costs, drawdown, and portfolio interactions.
- Write `incumbent_validation.json`, `gap_attribution.json`,
  `objective_breakdown.json`, `end_of_round_diagnostics.json`, and `monthly_report.md`.

Acceptance:

- Diagnostics run before planner/optimization.
- Evidence paths are stable and cited by the experiment plan.
- Latest-month selection-OOS comparison is separated from in-sample diagnostics.

### Phase 6 - LLM Experiment Plan

Deliverables:

- Implement planner prompt builder.
- Implement model/manual/fixture planner modes.
- Validate `OptimizerExperimentPlan`.
- Consume `monthly_search_brief.json` only as advisory ordering and seed guidance.
- Preserve `source_weekly_signal_ids`.

Acceptance:

- Plan missing evidence paths fails.
- Plan missing candidate families fails.
- Plan missing overfit risks fails.
- Weekly hints can reorder candidate families but cannot trigger repair or satisfy gates.

### Phase 7 - Strategy Plugin Contracts

Deliverables:

- Implement strategy registry.
- Implement `StrategyPluginContract` checker.
- Add plugin maturity states: diagnostic, shadow_validated, approval_ready.
- Add parity fixture set loader.
- Implement first real plugin against the actual trading repo selected for production.

Acceptance:

- Plugin contract missing live/backtest SHAs cannot be approval-ready.
- Unsupported symbol/timeframe blocks optimizer run.
- Strategy plugin can emit replay result, diagnostics, candidate families, and parity report.

Recommended first target order:

1. Actual trading repo production strategy that will be deployed first. This is the most
   important target because plugin/parity must be wired against production truth.
2. Crypto trend/breakout/momentum once `trading_assistant_data` has authoritative
   Hyperliquid bundles. These references have clean data and strong parity/runtime tests.
3. KRX KALCB/OLR once KRX calendars and intraday bundle authority are complete. These
   references have the newest shared optimization and artifact hygiene concepts.
4. US futures/swing/stock strategies from `_references/trading`, prioritized by live use
   and strategy plugin maturity.

### Phase 8 - Two-Fold Phased-Auto

Deliverables:

- Build two purged fold manifest.
- Run phase specs from plugin and validated LLM plan.
- Support config-only and structural candidates.
- Enforce `max_workers`.
- Emit fold validation, leakage, cost, outlier, portfolio/synergy, candidate results,
  and rejected candidates.

Acceptance:

- Candidate improves both fold support and canonical objective.
- Latest month is excluded from fold scoring.
- Structural candidates pass tests and decision parity before scoring.
- Phased-auto candidates use `phased_auto_runner_contract_v1`.

### Phase 9 - OOS Repair

Deliverables:

- Implement deterministic OOS underperformance trigger.
- Implement failure analysis.
- Implement cumulative accepted-mutation ablation across all prior rounds.
- Implement local perturbation, rollback, and targeted addition search.
- Implement checkpointed long-running repair attempts.
- Emit `repair_ablation_matrix.jsonl`.

Acceptance:

- All prior accepted mutations are represented or skipped with reason.
- Repair cannot materially degrade in-sample/fold quality.
- Repair candidates use `smoke_repair_runner_contract_v1`.
- Repair is never triggered by weekly hints alone.

### Phase 10 - Confirmatory Follow-Up And Round Adoption

Deliverables:

- Implement confirmatory variant builder.
- If repair ran, center variants around repair-recommended candidate.
- If repair did not run, center variants around phased-auto winner.
- Compare incumbent, phased-auto winner, repair candidate, rollback variants, and local
  follow-up variants.
- Write `confirmatory_rerank.json`.
- Write `rounds_manifest.json`.
- Write `selected_candidates.json` with exactly one adopted candidate, or `[]` with the
  no-adoption reason recorded in `confirmatory_rerank.json` and `rounds_manifest.json`.

Acceptance:

- Monthly run ends with exactly one adopted backtest candidate or no-adoption reason.
- Adopted candidate matches confirmatory rerank and rounds manifest.
- Adopted candidate has succeeded attempt record.
- Round_N+1 is not marked live deployed.

### Phase 11 - Structural Candidate Implementation

Deliverables:

- Implement structural workspace manager.
- Implement live repo patch generation.
- Implement backtest adapter patch generation.
- Implement config/schema patch generation.
- Implement test runner for live repo and backtest repo.
- Implement decision parity harness.

Acceptance:

- Structural candidate without live patch fails.
- Structural candidate without backtest adapter patch fails.
- Structural candidate without passing decision parity fails.
- Patch paths and parity evidence are under artifact root.

### Phase 12 - Shadow Monthly Runs

Deliverables:

- Run one incumbent-only shadow.
- Run one phased-auto shadow with fixture plugin.
- Run one phased-auto shadow with real plugin in diagnostic mode.
- Run one OOS-repair shadow where latest-month degradation is forced by fixture.
- Run one structural candidate shadow that fails parity and is blocked.

Acceptance:

- `trading_assistant` can invoke the repo via `BACKTEST_REPO_PATH`.
- All emitted artifacts pass `contracts.validate_monthly_runner`.
- Candidate pipeline creates no approval packet for diagnostic-only plugins.
- Operator-facing artifacts clearly explain no-adoption and blocked reasons.

## Conformance Tests

The upstream `trading_assistant` suite already covers the shared contract validator and
fixture runner. The backtest repo should run that suite against its real command, then
add repo-local tests for replay/plugin behavior that is invisible to the control plane.

Core tests:

- `test_cli_accepts_monthly_run_manifest`
- `test_compatibility_monthly_repair_entrypoint`
- `test_required_artifacts_emitted_for_incumbent`
- `test_artifact_index_paths_stay_under_artifact_root`
- `test_artifacts_are_newer_than_manifest`
- `test_malformed_jsonl_fails_contract`
- `test_coverage_manifest_echoes_data_bundle_checksum`
- `test_optimizer_requires_manifest_id`
- `test_two_fold_manifest_matches_run_manifest_windows`
- `test_llm_plan_consumes_monthly_search_brief_ids`
- `test_score_component_cap_blocks_plan_with_eight_components`
- `test_rejected_candidates_are_retained`
- `test_runner_observability_covers_all_attempt_ids`

Data/replay tests:

- `test_data_bundle_status_must_be_authoritative_for_optimizer`
- `test_bundle_checksum_mismatch_fails`
- `test_no_lookahead_higher_timeframe_bar_visibility`
- `test_latest_month_excluded_from_phased_auto_folds`
- `test_selection_oos_is_not_clean_deployed_verdict`

OOS-repair tests:

- `test_oos_repair_trigger_requires_material_underperformance`
- `test_weekly_hints_do_not_trigger_repair`
- `test_all_prior_mutations_in_ablation_matrix`
- `test_granular_ablation_can_beat_cluster_rollback`
- `test_repair_candidate_rejected_when_is_degrades_materially`
- `test_confirmatory_centers_repair_candidate_when_repair_triggered`

Structural/parity tests:

- `test_structural_candidate_requires_live_patch`
- `test_structural_candidate_requires_backtest_adapter_patch`
- `test_structural_candidate_requires_decision_parity_report`
- `test_decision_parity_must_cover_all_dimensions`
- `test_decision_parity_evidence_paths_exist_under_artifact_root`
- `test_backtest_only_structural_candidate_is_diagnostics_only`

Strategy plugin tests:

- `test_plugin_contract_maturity_requires_live_repo_sha`
- `test_plugin_contract_blocks_unsupported_symbol`
- `test_plugin_contract_blocks_unsupported_timeframe`
- `test_strategy_plugin_fixture_replay_is_deterministic`
- `test_strategy_plugin_parity_fixture_passes_before_approval_ready`

## Porting Rules

Port as executable shared code:

- Shared phase/greedy/core orchestration.
- Provenance, cache keys, phase logging, round manager, artifact hygiene.
- OOS ablation/repair mechanics generalized behind plugin adapters.
- Replay/parity kernels and completed-bar/no-lookahead policies.

Port as strategy plugin code only when the live strategy contract exists:

- Strategy-specific candidate builders.
- Strategy-specific replay adapters.
- Strategy-specific diagnostics.
- Strategy-specific phase specs and scoring transforms.

Keep as tests or docs:

- Historical round scripts.
- Promotion scripts.
- Ad hoc analysis scripts.
- Old output artifacts.

Never port:

- Order placement/cancel/revise code.
- Live OMS mutation.
- VPS deployment scripts.
- Data download/canonicalization code.
- Control-plane approval or Telegram routing.

## Key Risks And Controls

| Risk | Control |
|---|---|
| Three divergent auto frameworks become permanent | One shared auto core; strategy-specific behavior only in plugins |
| Backtest-only logic diverges from live trading | StrategyPluginContract plus DecisionParityReport before structural scoring |
| Historical round scripts encode stale assumptions | Convert durable ideas into plugins/tests; do not preserve scripts as entry points |
| Latest month is overfit during repair | Label it selection-OOS; next deployed month remains clean verdict |
| Data is silently stale or partial | Authoritative DataBundleManifest and checksum echo in coverage artifact |
| Structural candidate patches escape artifact root | Copy patches/evidence under artifact_root and validate containment |
| Long repair runs become opaque | Candidate attempts, checkpoints, runner_observability, timeout/stall states |
| Weekly hints become hidden authority | Search brief only affects ordering/seeds; deterministic gates decide |
| Portfolio improvements ignore interaction risk | Portfolio/synergy artifact required for adoption |
| Model produces persuasive but unsupported plan | Plan schema requires evidence paths, gates, and overfit risks; deterministic validation blocks |

## Definition Of Done For The Backtest Repo

The repo is ready for monthly shadow use when:

- It exposes native and compatibility manifest runner CLIs.
- It passes `contracts.validate_monthly_runner` against fixture incumbent and phased-auto runs.
- It validates authoritative `DataBundleManifest` input and echoes bundle checksum.
- It emits all required artifact contract files under `artifact_root`.
- It has one shared phased-auto core and does not depend on historical one-off round scripts.
- It has OOS repair with cumulative mutation ablation, perturbation, rollback, targeted repair,
  and repair-centered confirmatory follow-up.
- It has candidate workspace and attempt tracking with path containment.
- It has at least one real strategy plugin wired to the actual trading repo or explicitly
  marked diagnostic/shadow-only.
- It can generate `DecisionParityReport` for structural candidates.
- It records no live deployment and creates no approval artifacts itself.

The repo is ready for approval-gated monthly candidates only when:

- The data repo emits authoritative monthly bundles for the target strategy.
- The actual trading repo is wired through `StrategyPluginContract`.
- The target strategy plugin is `approval_ready`.
- Structural candidates pass decision-level parity.
- A full monthly shadow run emits contract-valid artifacts and `trading_assistant` candidate
  gates pass without repair requests.
