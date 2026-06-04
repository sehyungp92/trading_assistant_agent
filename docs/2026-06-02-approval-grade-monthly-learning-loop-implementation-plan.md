# Approval-Grade Monthly Learning Loop Implementation Plan

Date: 2026-06-02

## 1. Purpose

This plan closes the remaining gap between the current repository state and the
target state described in:

- `docs/2026-05-30-trading-assistant-workflow-learning-loop-explainer.html`
- `docs/2026-05-11-workflow-learning-loop-target-state.md`

The current repo has a strong shadow validation spine: authoritative active
portfolio bundles, formal shadow decision parity, replay evidence, data
reproduction, incumbent replay, round reproduction, and historical walk-forward
leakage gates. Historical walk-forward is now a hard approval gate, and current
non-crypto lanes remain blocked until their window/checksum evidence is
regenerated without leakage.

The remaining work is not "make replay exist" or "wire the monthly optimizer
from scratch." Replay, plugin phase specs, repair candidates, confirmatory
variants, purged two-fold scoring, measured repair triggers, and P6/P7 optimizer
audit integration exist. The remaining work is to keep hardening the monthly
analytical loop until every promotion gate is approval-grade:

1. Keep enforcing concrete evaluated parameter patches and patch fingerprints so
   `round_N+1` can only recommend a patch that was actually replayed.
2. Keep scoring candidates on true purged two-fold in-sample windows.
3. Use the latest completed month as selection-OOS after in-sample ranking, not
   as first-pass fold scoring.
4. Trigger repair from measured selection-OOS degradation.
5. Build repair candidates from real accepted-mutation ledgers and replay
   deltas.
6. Compare the phase winner, repair candidates, rollback candidates, and local
   confirmatory variants before choosing the adopted `round_N+1` candidate.
7. Emit one `round_N+1` optimized backtest recommendation, or a deterministic
   no-adoption reason with enough evidence to trust the no-change decision.
8. Promote strategy bridges from `shadow_validated` to `approval_ready` only
   after live/VPS runtime metadata, production fixtures, scheduled shadow
   evidence, and the completed optimizer evidence all pass.

## 2. Current State, Accurately Stated

### 2.1 Complete or Load-Bearing

- The three-workspace boundary is implemented:
  - `trading_assistant` is the control plane.
  - `trading_assistant_data` owns source/data authority and bundle manifests.
  - `trading_assistant_backtest` owns replay, optimizer artifacts, and parity.
- Active data validation lanes pass:
  - `k_stock_olr_kalcb`
  - `trading_stock_family`
  - `trading_momentum_family`
  - `trading_swing_family`
  - `crypto_trader_portfolio`
- The validation harness and five validation-test categories are runnable, but
  per-scope runnability and approval readiness are lane-specific rather than
  implied by artifact shape:
  - Data Reproduction
  - Incumbent Replay
  - Decision Parity
  - Round Reproduction
  - Historical Walk-Forward
- Data reproduction, incumbent replay, decision parity, and round reproduction
  pass for the active lanes. Historical walk-forward is hard-gated by leakage
  checks and currently blocks non-crypto lanes with duplicate bundle checksums or
  non-increasing windows until fresh evidence is generated.
- These validation-matrix results prove the active lanes can reproduce, replay,
  and compare under strict artifact criteria; they do not by themselves prove
  that a strategy bridge is live-deployable or approval-ready.
- Strategy contracts and parity artifacts exist for:
  - crypto trend, momentum, and breakout
  - k_stock OLR/KALCB
  - trading stock
  - trading momentum
  - trading swing
- Replay-backed candidate evaluation exists in the backtest repo.
- Candidate attempts, result rows, workspace manifests, no-adoption rows, and
  optimizer observability artifacts exist.
- `StrategyChangeLedger`, `ProposalLedger`, `SuggestionTracker`, monthly outcome
  schemas, monthly search brief schemas, and outcome prior scaffolds exist in
  the control plane.
- Existing control-plane validators already check much of the runner contract:
  core optimizer artifacts, fold-manifest alignment, search-brief consumption,
  candidate attempts, candidate gates, structural candidate lineage, model
  review plumbing, deployment metadata hashes, and P6/P7 optimizer evidence.
- Approval-grade optimizer evidence now requires an explicit
  `optimizer_run_manifest.json` tied to the promoted scope, run month,
  authoritative data bundle checksum set, full bridge contract hash set, full
  deployment metadata hash set, run manifest hash, and non-smoke approval mode.
  The validation matrix derives that expected context from the promoted
  validation and bridge-readiness reports, indexes explicit approval optimizer
  locations once per run, and ignores generic monthly/smoke artifact roots.
- Portfolio-level optimizer manifests now produce and validate bridge-id keyed
  contract/deployment path and hash maps. For `crypto_trader_portfolio`, the
  manifest must bind all three bridges: `crypto_trend_v1`,
  `crypto_momentum_v1`, and `crypto_breakout_v1`.
- Existing backtest-side approval audit code already has a strict live-emitted
  deployment metadata contract. That strictness is now shared by the
  control-plane structural gates; the remaining gap is installing real live/VPS
  metadata in the bot runtime paths.
- Replay plugins now provide non-empty phase specs, repair candidates, and
  confirmatory variants through shared plugin semantics.
- The monthly runner now performs purged two-fold in-sample candidate scoring,
  evaluates selection-OOS only after fold ranking, emits measured repair-trigger
  evidence, carries accepted-mutation repair context, evaluates confirmatory
  variants, compares repair follow-up against the original phase winner, and
  emits deterministic `round_N+1` recommendation or no-adoption artifacts.
- Replay evaluators now derive behavior from the candidate's concrete
  `parameter_patch`, preserve evaluated patch fingerprints through fold scoring,
  and require `round_N+1` recommendations to hash-match the patch that was
  actually evaluated.
- Fold-level optimizer evidence now requires each candidate's concrete patch,
  evaluated parameters, parameter patch fingerprint, and evaluated patch
  fingerprint to remain canonical and identical across purged folds.

### 2.2 Still Not Approval-Grade

- All strategy contracts remain `shadow_validated`, not `approval_ready`.
- Deployment metadata is still local/shadow metadata, not emitted by the real
  live bot/VPS runtime. The bot-side instrumentation guides already specify the
  required emitter fields, but the emitters still need to be implemented and
  installed in the actual bot startup/runtime paths.
- The P6/P7 optimizer spine exists, but promotion hardening must keep enforcing
  these invariants in every gate: strict live metadata, true two-fold scoring,
  selection-OOS after fold ranking, concrete evaluated patch fingerprints,
  measured repair triggers, repair/rollback comparison against the original
  phase winner, and non-empty confirmatory variants when a primary candidate
  exists.
- Repair ablation is fed by the accepted-mutation chain, but it still needs
  broader historical fixtures proving every accepted mutation is either ablated
  or receives a deterministic skip reason.
- `round_N+1` emits optimized backtest patch/config recommendation artifacts,
  but live adoption remains intentionally disabled/fail-closed until approval
  routing, live/VPS metadata, and production rollout evidence pass.
- Historical walk-forward leakage checks now gate fresh replay-evidence reports
  and validation-matrix approval readiness, but additional shuffled-window and
  repeated-checksum fixtures should be retained as regression tests.
- The approval audit and validation matrix now treat completed P6/P7 optimizer
  evidence as a promotion requirement. The remaining promotion blockers are
  live/VPS metadata, approval-ready maturity, production fixtures, scheduled
  shadow evidence, and rollout/outcome packaging.
- Approval-grade audit refreshes validation-matrix and bridge-readiness reports
  by default; cached report reuse is diagnostic-only and must not be the normal
  promotion path.

## 3. Non-Negotiable Invariants

- Live bots and VPSes are runtime consumers and telemetry emitters only. They do
  not run optimizer experiments and are not mutated by the backtest repo.
- The live trading repo remains production truth for strategy behavior.
- The data repo owns source refresh, canonicalization, calendars, checksums,
  bundle manifests, fees/slippage/adjustment policies, and slice indexes.
- The backtest repo may discover candidates, but cannot approve or deploy them.
- The control plane owns freeze manifests, gates, approvals, ledgers, outcomes,
  and monthly scheduling.
- Weekly evidence can steer search ordering and candidate priors only. It cannot
  change the monthly sequence, trigger repair, satisfy gates, or create
  approval-ready candidates.
- A structural candidate is never approval-ready unless it has live repo patch
  lineage, backtest adapter parity, rollback plan, tests, decision parity, and
  human approval routing.

## 4. Implementation Workstreams

## 4.1 Workstream A: Runtime Deployment Metadata and Bridge Promotion

### Goal

Replace local clean-checkout shadow evidence with runtime/VPS-emitted deployment
metadata, then promote exactly one bridge to `approval_ready` only after all
approval audit checks pass.

### Target Files

- `trading_assistant/skills/monthly_deployment_metadata.py`
- `trading_assistant_backtest/src/trading_assistant_backtest/validation/deployment_metadata_contract.py`
- `trading_assistant_backtest/src/trading_assistant_backtest/strategies/deployment.py`
- `trading_assistant_backtest/contracts/*/deployment_metadata.json`
- `trading_assistant_backtest/contracts/*/strategy_plugin_contract.json`
- `trading_assistant_backtest/artifacts/validation/approval_grade/`
- reference guides, already updated with the required field contract:
  - `docs/2026-05-31-trading-reference-instrumentation-implementation-guide.md`
  - `docs/2026-05-31-k-stock-trader-instrumentation-implementation-guide.md`
  - `docs/2026-05-31-crypto-trader-instrumentation-implementation-guide.md`
- bot-side instrumentation in:
  - `_references/crypto_trader/`
  - `_references/trading/`
  - `_references/k_stock_trader/`

### Tasks

1. Implement the runtime deployment metadata emitter described in the three
   instrumentation guides in each bot process startup path.
2. Emit one metadata artifact per portfolio/strategy bridge with:
   - `bot_id`
   - `portfolio_id`
   - `strategy_id`
   - `repo_url`
   - `source_control_origin`
   - `source_control_commit_sha`
   - `source_control_worktree_clean`
   - `deployed_commit_sha`
   - `config_hash`
   - `strategy_version`
   - `config_version`
   - `telemetry_schema_version`
   - `strategy_plugin_contract_path`
   - `strategy_plugin_contract_hash`
   - optional aliases only if needed for import compatibility:
     `contract_artifact_path`, `contract_hash`
   - `runtime_entrypoint`
   - `runtime_instance_id`
   - `runtime_host_fingerprint`
   - `live_runtime_started_at_utc`
   - `emitted_at_utc`
   - `emission_environment`
   - `metadata_source`
3. Ensure `metadata_source` is one of:
   - `live_bot_runtime_deployment_metadata_v1`
   - `vps_live_bot_runtime_deployment_metadata_v1`
4. Ensure `emission_environment` is one of:
   - `live_bot`
   - `paper_vps`
   - `production_vps`
   - `vps`
5. Harden the existing control-plane import/validation so it reuses or mirrors
   the strict backtest live-emission contract and rejects:
   - `local://` repo URLs
   - local/shadow/snapshot metadata source tokens
   - dirty worktrees
   - missing runtime identity fields
   - config hash mismatches
   - contract hash mismatches
   - telemetry schema mismatches
6. Add a contract promotion command or script that changes maturity only after:
   - live metadata passes
   - decision parity passes
   - replay evidence passes
   - scheduled shadow evidence passes
   - P6/P7 optimizer evidence passes for that bridge
7. Extend the backtest approval audit and validation matrix so P6/P7 optimizer
   evidence is checked explicitly, not inferred from the five validation-test
   pass/fail flags.

### Acceptance Criteria

- Approval-grade audit reports at least one approved scope.
- `approval_ready_bridges` is non-empty.
- No bridge can become `approval_ready` with local/shadow metadata.
- Metadata hash checks fail closed if the contract artifact changes without a
  matching emitted hash.

## 4.2 Workstream B: Strategy Plugin Candidate Semantics

### Goal

Harden the existing strategy-specific monthly optimization plugins. They now
generate candidate families, repair candidates, confirmatory variants, and
`round_N+1` artifacts; the approval-grade gap is keeping those artifacts tied to
the exact concrete parameter patch that replay evaluated.

### Target Files

- `trading_assistant_backtest/src/trading_assistant_backtest/auto/plugin.py`
- `trading_assistant_backtest/src/trading_assistant_backtest/auto/types.py`
- `trading_assistant_backtest/src/trading_assistant_backtest/strategies/crypto/replay_evaluator.py`
- `trading_assistant_backtest/src/trading_assistant_backtest/strategies/trading/momentum_replay_evaluator.py`
- `trading_assistant_backtest/src/trading_assistant_backtest/strategies/trading/equity_replay_evaluator.py`
- `trading_assistant_backtest/src/trading_assistant_backtest/strategies/krx/replay_evaluator.py`
- `trading_assistant_backtest/src/trading_assistant_backtest/strategies/bar_replay.py`

### Tasks

1. Standardize `Candidate` payload requirements:
   - candidate family
   - mutation type
   - target strategy/config scope
   - parameter patch or structural patch reference
   - expected mechanism
   - source evidence paths
   - weekly signal attribution, if any
   - rollback plan reference
2. Add a narrow fold/replay-evaluation payload schema, or extend
   `CandidateEvaluation` only if that stays small. The control plane already has
   the richer `MonthlyImprovementCandidate` schema, so avoid duplicating that
   whole model inside the backtest plugin protocol. The emitted candidate result
   rows must include:
   - fold-level metrics
   - selection-OOS metrics
   - objective component scores
   - no-regression gate statuses
   - replay hashes
   - fold support booleans consumed by the existing `purged_fold_support` gate
   - decision parity status
   - cost/drawdown/outlier/synergy checks
3. Maintain and extend `build_phase_specs()` coverage per active scope:
   - crypto trend/momentum/breakout
   - trading momentum: NQDTC, NQ_REGIME, Vdubus, Downturn
   - trading swing: ATRSS, AKC Helix, TPC
   - trading stock: IARIC, ALCB
   - k_stock: OLR, KALCB
4. Keep the monthly runner consuming plugin phase specs after diagnostics and
   experiment-plan validation. The deterministic fallback plan may remain as a
   fail-closed fallback, but approval-grade runs should use plugin-owned phase
   definitions and candidate semantics.
5. Continue expanding strategy-specific candidate families:
   - signal threshold repair
   - filter loosen/tighten
   - entry quality gates
   - exit/stop/take-profit changes
   - sizing/risk-cap changes
   - session/time-of-day gating
   - regime filters
   - portfolio cap/collision handling
   - structural candidates where parity contracts allow it
6. Harden `build_repair_candidates()` from failure analysis and round chain.
7. Harden `build_confirmatory_variants()` around the selected primary candidate.
8. Keep `write_round_n_plus_1()` fail-closed so it only emits a recommendation
   for a candidate with evaluated patch fingerprints, and so it emits:
   - hash-matched config patch
   - strategy patch, if structural
   - adapter patch, if structural
   - next config hash
   - rollback plan
   - candidate manifest
9. Keep `adoption_enabled=False` until the relevant bridge passes the approval
   audit. Promotion should be per bridge, not global. When it is enabled, derive
   it from the manifest/contract approval-readiness evidence for that bridge
   rather than flipping a broad module-level constant.

### Acceptance Criteria

- Every active plugin returns at least one phase spec for its normal monthly
  run when data and maturity gates are satisfied.
- Monthly approval-grade runs consume plugin-owned phase specs rather than only
  `_phase_specs_from_plan()` deterministic fallback output.
- Every active plugin can produce repair candidates from a synthetic failure
  analysis fixture.
- Every active plugin can produce confirmatory variants for a selected candidate.
- Candidate payloads are stable enough to reproduce exact candidate IDs across
  reruns.
- A `round_N+1` recommendation cannot name a config patch whose stable hash does
  not match the selected candidate's evaluated patch evidence.

## 4.3 Workstream C: True Two-Fold Phased-Auto In-Sample Scoring

### Goal

Maintain and harden Phase 6 from the target-state doc: run diagnostics first,
build a bounded experiment plan, score candidates on two purged in-sample folds,
and shortlist only candidates that improve the canonical objective without
regression.

### Target Files

- `trading_assistant_backtest/src/trading_assistant_backtest/monthly.py`
- `trading_assistant_backtest/src/trading_assistant_backtest/replay/windows.py`
- `trading_assistant_backtest/src/trading_assistant_backtest/auto/phase_runner.py`
- `trading_assistant_backtest/src/trading_assistant_backtest/auto/greedy_optimizer.py`
- `trading_assistant_backtest/src/trading_assistant_backtest/auto/phase_gates.py`
- `trading_assistant_backtest/src/trading_assistant_backtest/scoring/gates.py`
- `trading_assistant_backtest/src/trading_assistant_backtest/auto/fold_scoring.py`

### Tasks

1. Keep first-pass candidate evaluation on the two in-sample folds from
   `fold_manifest.json`; selection-OOS must remain excluded until after fold
   ranking.
2. Cache incumbent replay once per fold, then evaluate each candidate against
   the cached fold incumbent:
   - fold 1 incumbent replay
   - fold 2 incumbent replay
   - fold 1 candidate replay
   - fold 2 candidate replay
3. Aggregate:
   - objective score
   - objective delta
   - fold variance
   - net return delta
   - Calmar delta
   - profit factor delta
   - expectancy delta
   - max drawdown delta
   - process-quality proxy, where available
4. Keep the pass-gate payloads tied to real candidate checks for shortlisted
   candidates:
   - both folds must have sufficient rows and trades
   - both folds must avoid material drawdown degradation
   - cost sensitivity must not erase the edge
   - outlier removal must not destroy the candidate
   - selection must not depend on one isolated trade
   - strategy/portfolio synergy checks must pass
5. Make weekly search brief influence:
   - phase ordering
   - candidate ordering
   - seed neighborhoods
   - negative priors
   - repair-ablation ordering after repair trigger
6. Make weekly search brief unable to influence:
   - monthly sequence
   - OOS repair trigger
   - score weights
   - approval status
   - maturity gates
7. Emit:
   - `fold_candidate_results.jsonl`
   - `fold_score_matrix.json`
   - `candidate_attempts.jsonl`
   - `candidate_results.jsonl`
   - `selected_candidates.json`
   - `rejected_candidates.jsonl`
   - `runner_observability.json`
8. Ensure `selected_candidates.json` remains empty if no candidate passes both
   folds.

### Acceptance Criteria

- A fixture candidate that improves only one fold is rejected.
- A fixture candidate that improves both folds and passes no-regression gates is
  shortlisted.
- Selection-OOS data is not read during first-pass in-sample fold scoring.
- Rerunning the same manifest produces identical candidate IDs, score rows, and
  adoption/no-adoption decision.

## 4.4 Workstream D: Selection-OOS Repair Trigger and Failure Attribution

### Goal

Complete the conditional OOS repair trigger. Latest-month selection-OOS should
be used after in-sample ranking to test whether the candidate or incumbent
materially trails the in-sample/fold expectation.

### Target Files

- `trading_assistant_backtest/src/trading_assistant_backtest/monthly.py`
- `trading_assistant_backtest/src/trading_assistant_backtest/repair/failure_analysis.py`
- `trading_assistant_backtest/src/trading_assistant_backtest/repair/ablation.py`
- `trading_assistant_backtest/src/trading_assistant_backtest/repair/targeted.py`
- `trading_assistant_backtest/src/trading_assistant_backtest/repair/perturbation.py`
- `trading_assistant_backtest/src/trading_assistant_backtest/repair/rollback.py`
- `trading_assistant_backtest/src/trading_assistant_backtest/repair/trigger.py`
- `trading_assistant_backtest/src/trading_assistant_backtest/replay/windows.py`

### Tasks

1. Extend the existing OOS repair trigger module beyond the simple
   `material_underperformance()` threshold and emit `selection_oos_evaluation.json`:
   - incumbent score on selection-OOS
   - phased-auto winner score on selection-OOS
   - expected IS/fold score band
   - measured degradation
   - sample-size caveat
   - trigger status
2. Define degradation thresholds:
   - objective drop threshold
   - drawdown increase threshold
   - trade-count collapse threshold
   - cost sensitivity threshold
   - strategy-specific under-trading threshold
3. Trigger repair only if thresholds hold. Do not use `manifest.mode` as the
   primary repair trigger for normal monthly runs.
4. Build failure attribution from replay diagnostics:
   - signal extraction
   - discrimination
   - entry quality
   - exit quality
   - stop behavior
   - sizing/risk caps
   - portfolio collisions
   - execution/cost sensitivity
   - regime/session behavior
   - data/sample caveats
5. Emit `selection_oos_repair_trigger.json`.
6. Emit `repair_failure_attribution.json`.
7. Preserve selection-OOS as selection evidence, not the clean deployed verdict.

### Acceptance Criteria

- Repair is not triggered by weekly evidence alone.
- Repair is not triggered when selection-OOS is sparse but within declared
  tolerance.
- Repair is triggered when selection-OOS materially trails the IS/fold profile.
- Trigger output includes deterministic reasons and thresholds.

## 4.5 Workstream E: Cumulative OOS Repair and Accepted-Mutation Ablation

### Goal

Make repair operate on actual accepted mutations from all prior rounds, not on
empty lists or generic candidates.

### Target Files

- `trading_assistant/skills/strategy_change_ledger.py`
- `trading_assistant/schemas/strategy_change_ledger.py`
- `trading_assistant_backtest/src/trading_assistant_backtest/repair/ablation.py`
- `trading_assistant_backtest/src/trading_assistant_backtest/repair/rollback.py`
- `trading_assistant_backtest/src/trading_assistant_backtest/repair/perturbation.py`
- `trading_assistant_backtest/src/trading_assistant_backtest/repair/targeted.py`
- `trading_assistant_backtest/src/trading_assistant_backtest/monthly.py`

### Tasks

1. Add a round-chain loader that reads accepted mutations from existing control
   and backtest provenance:
   - `StrategyChangeLedger`
   - `rounds_manifest.json`
   - accepted config patches
   - deployment records
2. Normalize each accepted mutation:
   - mutation ID
   - first accepted round
   - strategy/config scope
   - patch path
   - parameter diff
   - structural diff, if any
   - original evidence paths
   - outcome status
3. Generate ablation candidates:
   - one-at-a-time mutation removal
   - small-combination rollback
   - targeted rollback ordered by failure attribution
   - skip reasons for non-ablatable structural changes
4. Generate perturbation candidates:
   - numeric parameter local changes
   - boolean toggle variants
   - threshold loosen/tighten neighborhoods
5. Generate targeted candidates from diagnosed weakness:
   - missed alpha
   - filter overreach
   - under-trading
   - outlier loss
   - session/regime mismatch
   - sizing/risk-cap suppression
6. Emit:
   - `accepted_mutation_chain.json`
   - `repair_ablation_matrix.jsonl`
   - `repair_candidate_results.jsonl`
   - `repair_checkpoint.json`
7. Replace the current `build_ablation_matrix(..., [])` call in the monthly
   runner with the loaded accepted-mutation chain.

### Acceptance Criteria

- Every accepted mutation is ablated or has a deterministic skip reason.
- A known harmful prior mutation fixture is identified and rollback-ranked.
- Repair candidates cannot materially degrade in-sample/fold quality to fit the
  latest month.
- Long repair runs can resume from checkpoints without changing candidate IDs.

## 4.6 Workstream F: Confirmatory Rerank and Round_N+1 Recommendation

### Goal

Make confirmatory follow-up load-bearing. Every monthly run should end with one
optimized backtest recommendation or a deterministic no-adoption reason.

### Target Files

- `trading_assistant_backtest/src/trading_assistant_backtest/monthly.py`
- `trading_assistant_backtest/src/trading_assistant_backtest/repair/confirmatory.py`
- `trading_assistant_backtest/src/trading_assistant_backtest/contract_models.py`
- strategy replay plugins under `trading_assistant_backtest/src/trading_assistant_backtest/strategies/`

### Tasks

1. If repair triggered, center confirmatory follow-up on the best repair
   candidate while keeping the original phased-auto winner in the final
   comparison set.
2. If repair did not trigger, center confirmatory follow-up on the phased-auto
   winner.
3. Generate confirmatory variants:
   - local parameter perturbations
   - small add/remove mutation toggles
   - focused rollback variants
   - targeted additions tied to diagnosed weakness
4. Evaluate each variant on:
   - fold 1
   - fold 2
   - selection-OOS
   - cost sensitivity
   - outlier sensitivity
   - portfolio/synergy gates
5. Rerank against:
   - incumbent
   - phased-auto winner
   - repair winner, if any
   - rollback candidates
   - targeted additions
6. Emit a non-empty `confirmatory_rerank.json` whenever a primary candidate
   exists.
7. Emit `round_N+1` artifacts:
   - `rounds_manifest.json`
   - candidate patch/config patch
   - next config hash
   - rollback plan
   - approval packet payload
   - decision parity artifact paths
8. Keep live deployment status as `optimized_backtest_recommendation` until
   human approval and deployment happen.

### Acceptance Criteria

- Confirmatory rerank cannot adopt a candidate absent from compared candidates.
- Empty variants are allowed only when there is no primary candidate and a
  deterministic no-adoption reason is present.
- A fixture where the local confirmatory variant beats the repair winner adopts
  the variant, not the original repair candidate.
- A fixture where the original phase winner beats repair follow-up after a
  repair trigger adopts the phase winner with `adopted_source=phased_auto`.
- `rounds_manifest.json` records exactly one adopted candidate or exactly one
  no-adoption reason.

## 4.7 Workstream G: Approval Gate Integration

### Goal

Make the control plane reject structural approval unless data, parity, replay,
optimizer, metadata, and maturity all pass.

### Target Files

- `trading_assistant/skills/monthly_candidate_pipeline.py`
- `trading_assistant/skills/monthly_optimizer_runner.py`
- `trading_assistant/skills/monthly_validation_orchestrator.py`
- `trading_assistant/contracts/monthly_runner_contract.py`
- `trading_assistant/contracts/validate_monthly_runner.py`
- `trading_assistant/schemas/monthly_validation.py`
- `trading_assistant/schemas/monthly_candidates.py`
- `trading_assistant/schemas/monthly_optimizer.py`
- `trading_assistant/schemas/monthly_run_manifest.py`
- `trading_assistant_backtest/src/trading_assistant_backtest/contract_models.py`
- `trading_assistant_backtest/src/trading_assistant_backtest/monthly.py`
- `trading_assistant_backtest/src/trading_assistant_backtest/validation/approval_grade_audit.py`
- `trading_assistant_backtest/src/trading_assistant_backtest/validation/optimizer_evidence.py`
- `trading_assistant_backtest/src/trading_assistant_backtest/validation/validation_matrix.py`

### Tasks

1. Add an explicit `optimizer_approval_readiness` block to monthly artifacts or
   the approval audit output. This should extend the existing gate/reporting
   surfaces, not create a parallel approval system.
2. Require approval-grade P6/P7 evidence to be selected only from an explicit
   non-smoke `optimizer_run_manifest.json` that hash-ties the run to the
   promoted scope, run month, data bundle checksum set, bridge contract hash
   set, deployment metadata hash set, and frozen run manifest.
3. Refresh validation-matrix and bridge-readiness reports by default in the
   approval-grade audit; allow cached report reuse only for explicit diagnostic
   runs.
4. Emit and validate bridge-id keyed path/hash maps from the monthly producer
   for every multi-bridge optimizer scope, especially all three crypto bridge
   contracts and deployment metadata artifacts.
5. Require:
    - data reproduction pass
    - incumbent replay pass
    - decision parity pass
    - round reproduction pass
    - historical walk-forward pass
    - plugin maturity `approval_ready`
    - runtime deployment metadata pass
    - P6 true fold scoring pass
    - P7 repair/confirmatory/round_N+1 pass
6. Preserve the existing lifecycle concepts (`MonthlyValidationStatus`,
   `OptimizerSequenceStatus`, approval-ready candidate counts, approval
   packets, deployment/outcome records), but make the distinction explicit in
   the emitted reports:
   - validation tests passed
   - optimizer P6/P7 complete
   - bridge approval-ready
   - approval requested
   - approved
   - deployed
   - measured
5. Ensure validation-test pass cannot imply `approval_ready=true`.
6. Ensure approval packet creation is impossible without `approval_ready=true`.
7. Keep the existing structural-candidate gates and extend them to block
   structural candidates without:
   - live repo patch
   - backtest adapter patch
   - decision parity fixture expansion
   - rollback plan
   - human approval route

### Acceptance Criteria

- Current shadow bridges remain blocked from approval.
- A fixture bridge with complete metadata but incomplete P6/P7 evidence remains
  blocked.
- A fixture bridge with complete P6/P7 evidence but local metadata remains
  blocked.
- A fixture with the current five validation tests passing but empty
  confirmatory variants remains blocked from approval-ready promotion.
- A fully passing fixture can route an approval packet but still cannot deploy
  without human approval.

## 4.8 Workstream H: Historical Walk-Forward Hardening

### Goal

Make historical walk-forward evidence prove value across ordered, non-identical
monthly windows, not just pass basic replay availability.

### Target Files

- `trading_assistant_backtest/src/trading_assistant_backtest/validation/replay_evidence_run.py`
- `trading_assistant_backtest/artifacts/validation/replay_evidence/*/historical_walk_forward_report.json`

### Tasks

1. Require strictly increasing window order.
2. Require unique bundle checksums for approval-grade walk-forward unless a
   declared same-bundle diagnostic mode is explicitly requested and excluded
   from approval promotion.
3. Simulate monthly sequence:
   - use data available up to month M
   - run diagnostics
   - run phased-auto
   - run selection-OOS repair if triggered
   - run confirmatory rerank
   - select candidate/no-adoption
   - evaluate selected outcome on later unseen month M+1
4. Track whether the selected candidate improves unseen performance versus the
   incumbent.
5. Record candidate persistence over 3 months or minimum trade count where data
   allows.
6. Fail the walk-forward test if leakage checks fail.
7. Update the validation matrix so these leakage checks affect approval-grade
   readiness, not just report decoration.

### Acceptance Criteria

- Reports cannot have status `pass` when leakage checks are false.
- A synthetic shuffled-window fixture fails.
- A repeated-checksum fixture fails unless explicitly marked diagnostic.
- The report distinguishes candidate-selection OOS from clean deployed-verdict
  OOS.

## 4.9 Workstream I: Model Review and Structural Proposal Layer

### Goal

Use model reasoning after deterministic evidence assembly, not as a substitute
for evidence.

### Target Files

- `trading_assistant/skills/monthly_model_review_runner.py`
- `trading_assistant/analysis/monthly_model_response_parser.py`
- `trading_assistant/analysis/monthly_model_response_validator.py`
- `trading_assistant/schemas/monthly_model_review.py`
- `trading_assistant/schemas/proposal_ledger.py`

### Tasks

1. Extend the existing monthly model review packages to include:
   - diagnostics
   - gap attribution
   - fold score matrix
   - OOS trigger report
   - repair ablation results
   - confirmatory rerank
   - rejected candidates
   - prior outcomes
   - risk flags
   - data/parity status
2. Require model outputs to include:
   - affected strategy/config scope
   - evidence paths
   - hypothesized mechanism
   - acceptance criteria
   - rollback plan
   - risk classification
   - whether it is config-only or structural
3. Parse and validate model output.
4. Route accepted model-reviewed candidates to ProposalLedger and approval
   handling.
5. Ensure model review cannot change deterministic gates or maturity.

### Acceptance Criteria

- Model output without evidence paths is rejected.
- Model output that proposes a material change without rollback criteria is
  rejected.
- Model output can explain no-adoption without generating an approval request.

## 4.10 Workstream J: Monthly Outcome Verdict and Priors

### Goal

Replace lightweight before/after outcome authority for material changes with
next-month full-fidelity verdicts and follow-up persistence checks.

### Target Files

- `trading_assistant/skills/monthly_outcome_measurer.py`
- `trading_assistant/skills/monthly_outcome_scorer.py`
- `trading_assistant/skills/outcome_prior_store.py`
- `trading_assistant/skills/monthly_search_brief_builder.py`
- `trading_assistant/analysis/context_builder.py`
- `trading_assistant/schemas/monthly_outcome.py`
- `trading_assistant/schemas/outcome_priors.py`
- `trading_assistant/schemas/monthly_search_brief.py`

### Tasks

1. When a candidate is approved and deployed, use the existing monthly outcome
   and ledger scaffolds to record deployment ID, commit SHA,
   config hash, contract hash, proposal ID, and candidate ID.
2. Use the next completed month after deployment as the primary clean deployed
   verdict.
3. Compare deployed `round_N+1` against the prior incumbent using the same
   replay/objective framework.
4. Write:
   - `monthly_outcomes.jsonl`
   - `monthly_outcome_followups.jsonl`
   - `outcome_priors.jsonl`
   - `StrategyChangeLedger` outcome record
   - `ProposalLedger` outcome record
5. Add persistence checks:
   - 3-month follow-up
   - minimum trade-count follow-up
6. Feed outcomes into:
   - candidate-family priors
   - phase ordering
   - seed neighborhoods
   - negative priors
   - repair-ablation ordering
   - rollback priority
7. Keep `AutoOutcomeMeasurer` as early warning only for material strategy
   changes.

### Acceptance Criteria

- A deployed material change cannot be marked final by 7-day lightweight
  daily-summary evidence.
- A negative monthly verdict creates a negative prior or rollback/watch action.
- A positive one-month verdict is marked promising, not fully proven, until the
  follow-up threshold is met.

## 4.11 Workstream K: Data Authority Maintenance

### Goal

Keep data validation green without confusing current source authority with
historical archived reproduction.

### Target Files

- `trading_assistant_data/`
- `trading_assistant_backtest/artifacts/validation/data_reproduction/`
- data bundle requirement files in the data/backtest workspaces

### Tasks

1. Keep active full-family bundles current before each monthly cycle.
2. Keep slice indexes authoritative for bundle selection.
3. Keep source refresh reports current:
   - Hyperliquid for crypto
   - IBKR for trading momentum/swing/stock
   - KIS for k_stock intraday
   - LRS as local KRX research input only
4. Preserve the distinction between:
   - legacy archived parity
   - live production-source refresh evidence
   - approval-scope bundle evidence
5. For trading stock, keep the live approval lane scoped to the 98-symbol
   intraday universe plus declared daily/reference context.
6. For k_stock, keep the OLR/KALCB lane scoped to the declared 103-symbol
   universe and exact daily/intraday roots.
7. For crypto phased optimizer, validate required optimizer timeframes:
   - trend: 15m, 1h, 1d
   - breakout: 30m, 4h
   - momentum: 15m, 1h, 4h
   - funding where required
8. Do not block phased optimizer on long 1m/5m Hyperliquid history, because live
   API retention is limited and those intervals are not required optimizer
   inputs.

### Acceptance Criteria

- Bundle builds fail if an unindexed slice can influence selection.
- Each required slice has checksum, lineage, session policy, adjustment policy,
  fee/slippage policy, and usable authority flag.
- Source refresh/reproduction reports are regenerated before scheduled monthly
  cycles.

## 4.12 Workstream L: Strategy Rollout Order

### Goal

Promote one bridge at a time. Do not batch-promote all contracts together.

### Recommended Order

1. Crypto portfolio or narrow `crypto_trend_v1`
   - Closest to approval because Hyperliquid/data/replay is simplest.
   - Needs runtime metadata, production fixtures, scheduled shadow cycles, and
     completed P6/P7 candidate semantics.
2. Trading momentum family
   - Smallest non-crypto source set.
   - Proves IBKR plus CME authority and futures roll policy.
3. Trading swing family
   - Small QQQ/GLD data scope.
   - Needs richer swing-specific candidate semantics.
4. Trading stock family
   - Broader live 98-symbol approval lane plus declared references.
   - Needs IARIC/ALCB-specific phase and repair builders.
5. k_stock OLR/KALCB
   - Broad 103-symbol universe.
   - Needs KRX/KIS/KALCB/OLR-specific failure attribution and repair semantics.

### Weekly Search-Brief Rotation

- Week 1: `k_stock_trader` plus trading stock
- Week 2: trading momentum
- Week 3: trading swing
- Week 4: `crypto_trader`
- Week 5: repeat from week 1

The rotation changes search-prior emphasis only. Monthly validation remains the
only authority for material strategy changes.

## 5. Test Plan

### 5.1 Backtest Repo Tests

Add or extend tests for:

- two-fold split and embargo correctness
- selection-OOS exclusion from first-pass fold scoring
- fold aggregation and no-regression gates
- candidate ID determinism
- strategy plugin phase spec generation
- repair trigger true/false threshold behavior
- accepted-mutation chain loading
- one-at-a-time ablation and skip reasons
- perturbation candidate generation
- targeted repair candidate generation
- confirmatory rerank with non-empty variants
- `rounds_manifest.json` exactly-one adoption/no-adoption invariant
- historical walk-forward leakage checks
- approval blocked when maturity or metadata is missing

Suggested command:

```powershell
pytest trading_assistant_backtest/tests
```

### 5.2 Control Plane Tests

Add or extend tests for:

- runtime deployment metadata validation
- approval audit blocking local/shadow metadata
- monthly optimizer runner requiring P6/P7 artifacts
- model review package evidence requirements
- approval packet routing only after all gates pass
- monthly outcome verdict writing
- outcome prior feedback into monthly search brief
- weekly search brief unable to trigger repair or approval

Suggested command:

```powershell
pytest trading_assistant/tests
```

### 5.3 End-to-End Shadow Tests

Run one full shadow monthly cycle for the first bridge:

1. Refresh data.
2. Rebuild bundle.
3. Re-run data reproduction.
4. Re-run decision parity.
5. Run two-fold phased-auto.
6. Run selection-OOS trigger check.
7. Run repair if triggered.
8. Run confirmatory rerank.
9. Emit `round_N+1` or no-adoption.
10. Validate approval audit remains blocked if metadata/maturity is missing.
11. Install live-emitted metadata.
12. Promote bridge to `approval_ready`.
13. Re-run audit and route approval packet in shadow.

## 6. Definition of Done

The repo reaches the optimal target state when all of the following are true for
at least one bridge, then eventually for every active bridge:

- Source data refresh and data reproduction pass.
- Decision parity passes against live runtime metadata and production-derived
  fixtures.
- Incumbent replay passes against latest accepted config and frozen diagnostics.
- True two-fold in-sample phased-auto runs and records fold score matrices.
- Selection-OOS is evaluated after in-sample ranking.
- OOS repair triggers only from measured degradation.
- Repair uses cumulative accepted mutations and replay deltas.
- Confirmatory rerank evaluates real variants.
- `round_N+1` emits a patch/config recommendation or deterministic no-adoption.
- Model review receives deterministic evidence and cannot bypass gates.
- Approval packet can be routed only when data, parity, replay, P6/P7,
  metadata, and maturity gates pass.
- Human approval remains required for trading behavior changes.
- Deployment records write back commit SHA, deployment ID, config hash, and
  contract hash.
- Next completed month produces the primary clean deployed verdict.
- Outcome priors alter future search behavior, not just prompt text.

## 7. Immediate Next Slice

The highest-value next implementation slice is:

1. Pick the first promotion lane, preferably narrow crypto trend or the crypto
   portfolio if all three crypto strategies must be promoted together.
2. Implement runtime deployment metadata emission for that lane.
3. Install production-derived parity fixtures and scheduled shadow evidence for
   that lane.
4. Run the implemented two-fold, selection-OOS, repair, confirmatory, and
   `round_N+1` optimizer sequence against that lane's authoritative bundles.
5. Add or refresh fixtures that prove repair-triggered rerank compares the phase
   winner, repair/rollback candidates, and confirmatory variants.
6. Re-run the five validation tests, validation matrix, and approval-grade audit;
   expect historical walk-forward to remain blocked until fresh non-leaking
   evidence is generated for each lane.
7. Promote the contract to `approval_ready` only after the audit passes and the
   completed P6/P7 evidence is present.

After that first bridge is approval-ready, repeat the same pattern in rollout
order: trading momentum, trading swing, trading stock, then k_stock OLR/KALCB.
