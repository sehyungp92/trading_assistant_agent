# Workflow Learning Loop Gap Implementation Plan

Date: 2026-05-29
Status: Implemented through the bounded local contracts; production runner depth remains ongoing

## Purpose

This plan converts the valid remaining gaps from
`docs/2026-05-29-trading-assistant-workflow-learning-loop-explainer.html` into
a concrete implementation sequence.

It is intentionally narrower than the older target-state plans. It does not
rebuild features that have already landed. It focuses on the highest-value work
still required to make the monthly trading loop and the harness meta-learning
loop measurable, auditable, and operationally useful.

Primary references:

- `docs/2026-05-29-trading-assistant-workflow-learning-loop-explainer.html`
- `docs/2026-05-12-hermes-autoagent-reference-leverage-report.md`
- `docs/2026-05-11-workflow-learning-loop-target-state.md`
- `docs/adr/0001-monthly-evidence-replay-foundation.md`
- `memory/policies/v1/harness_program.md`

## Current-State Corrections

The implementation plan below is based on the codebase state observed on
2026-05-29. The following items should not be treated as open gaps:

Implementation update, later 2026-05-29:

- Harness replay is now variant-aware and executable in CI-safe deterministic
  mode. `HarnessExecutionRunner` applies prompt patches, retrieval profile
  overrides, validator profiles, route metadata, parser/validator execution,
  artifact containment checks, and governance hard-fails; `HarnessEvalRunner`
  can execute enabled variants and deterministic fallback scoring cannot
  promote a variant.
- Evidence references used by harness materialization, harness execution,
  harness evaluation, and focused recall now share root-contained path
  validation. Existing absolute paths outside the workspace no longer count as
  valid provenance.
- `LearningReviewOrchestrator` now includes bounded deterministic run-artifact
  review over recent run folders, parser outputs, validator notes, and report
  checklists. `llm_review` falls back to this safe path until strict
  structured-output LLM review is configured.
- Monthly optimizer attempt tracking now allocates attempt numbers across all
  prior attempt states, rejects active duplicate claims, and validates adopted
  candidates against terminal attempt ledger records.
- Monthly search briefs now emit rollback candidates, bounded optimizer
  guidance, and manifest-carried guidance; optimizer validation requires
  non-empty search guidance to be cited/consumed by experiment plans.
- Focused recall only attaches outcome/change status when a card matches a
  concrete run/proposal/suggestion/change/deployment identity, avoiding
  unrelated "latest outcome" attribution.
- Generated playbook curation now patches keeper playbooks during duplicate
  consolidation by merging evidence refs and supersession provenance.
- Shared contracts now prefer domain projections over raw JSONL reads:
  strategy-change consumers use `StrategyChangeLedger` projections, scheduled
  monthly validation writes a run-folder artifact index for learning review, and
  monthly model-review provider attribution is persisted for provider scoring.

- Monthly validation and monthly model review are already first-class
  `AgentWorkflow` values in `schemas/agent_preferences.py` and are included in
  `orchestrator/agent_preferences.py` workflow order and default tuning.
- `memory/policies/v1/harness_program.md` already exists and is referenced by
  harness evaluation results.
- `skills/monthly_model_review_runner.py` is wired into
  `skills/monthly_validation_orchestrator.py`; the remaining gap is production
  readiness and incomplete-artifact repair, not absence of model review.
- Generated playbook usage is recorded at prompt-injection time in
  `analysis/context_builder.py`; curation now covers guard quarantine,
  duplicate consolidation, patching, pinning, and archive/restore. The remaining
  gap is richer downstream outcome attribution.
- Legacy WFO runtime routing is removed from active codepaths. Stale
  documentation/index references may remain, but `handle_wfo`, WFO scheduler
  jobs, and WFO worker dispatch should not be reintroduced.
- `skills/learning_review_orchestrator.py` exists and is invoked by
  `skills/learning_cycle.py`; it now performs bounded deterministic artifact
  review. The remaining gap is optional structured-output LLM review, not
  artifact awareness.
- `skills/harness_eval_runner.py` is no longer only a tag/name heuristic. It
  performs parser, validator, artifact, governance, executable variant replay,
  and keep/discard checks. The remaining gap is provider-sandbox coverage depth,
  not CI-safe executable replay.
- `orchestrator/app.py` already creates shared approval plumbing for
  `approval_gated` monthly validation even when `AUTONOMOUS_ENABLED=false`.
  The monthly plan should reuse this infrastructure, not recreate approval
  ownership.
- `schemas/backtest_artifacts.py` already defines the required backtest
  artifact contract and `BacktestRunnerClient` already validates
  `artifact_index.json`, required artifact presence, malformed JSON/JSONL,
  path containment, and stale artifacts. OOS-repair/phased-auto work should
  extend this contract, not replace it.
- OOS-repair/phased-auto are partially wired as monthly candidate sources; the
  existing OOS-repair surfaces are still named `SMOKE_REPAIR` in code:
  `MonthlyRunMode.SMOKE_REPAIR`, `MonthlyRunMode.PHASED_AUTO`,
  `MonthlyCandidateSource.SMOKE_REPAIR`, `MonthlyCandidateSource.PHASED_AUTO`,
  `ProposalSource.MONTHLY_SMOKE_REPAIR`, `ProposalSource.MONTHLY_PHASED_AUTO`,
  source-runner contract gates, purged-fold support gates, proposal recording,
  and approval-packet ingestion already exist. The remaining gap is the
  production-grade external runner implementation, not candidate ingestion.
- `OutcomePriorStore`, `SearchAllocationPolicy`, `MonthlyCandidatePipeline`,
  and `ResponseValidator` already feed monthly outcome priors into candidate
  ordering and stronger-evidence gates. The remaining feedback gap is depth and
  evidence quality, not first wiring.
- `LearningReviewOrchestrator` writes `focused_recall_cards.jsonl`, and
  `ContextBuilder` consumes focused recall as a first-class surface before raw
  RunIndex snippets.
- Weekly learning already records advisory memory, hypotheses, structural
  experiments, and outcome/recalibration context. A bounded weekly-to-monthly
  search-prior contract now exists and is carried in the monthly manifest; it
  should steer the LLM experiment plan, phased-auto ordering, seed neighborhoods,
  negative priors, rollback inspection, and conditional OOS-repair ablation
  priority without changing the fixed monthly sequence, triggering repair, or
  creating approval-ready monthly candidates.

## Target Outcome

After this plan is complete:

1. Harness changes are evaluated by replaying frozen benchmark cases through
   real prompt assembly, retrieval, parser, validator, and optional model
   invocation boundaries.
2. Run recall produces focused, provenance-rich evidence summaries rather than
   short lexical snippets.
3. Post-run learning review inspects concrete artifacts and writes only
   idempotent advisory learning through bounded write paths.
4. At least one replay-ready strategy runs monthly validation in shadow mode on
   a predictable cadence, with a documented path to `approval_gated`.
5. Weekly evidence feeds monthly through a non-authoritative
   `monthly_search_brief.json` that contains evidence-linked search priors,
   phased-auto ordering hints, seed candidates, conditional OOS-repair ablation
   priorities, negative priors, and attribution.
6. The monthly optimizer runner sequence uses all pre-latest-month data as
   in-sample, the latest completed month as selection-OOS, diagnostics-driven
   LLM experiment planning, two-fold phased-auto, OOS repair when needed,
   repair-centered confirmatory follow-up, and `round_N+1` backtest-config
   adoption.
7. Generated playbooks have curator lifecycle controls: consolidate, pin,
   archive/restore, patch/quarantine, and outcome attribution.
8. Incomplete monthly artifacts route to structured repair requests instead of
   silently blocking or letting the model infer through missing evidence.

## Guiding Constraints

- Monthly full-fidelity validation remains the sole authority for material
  strategy/config changes.
- Harness meta-learning may change prompts, retrieval, validators, parsers,
  benchmark scoring, generated memory, and provider routing only inside the
  boundaries in `memory/policies/v1/harness_program.md`.
- Generated learning is advisory context, never hidden policy.
- Every new memory or playbook write must cite concrete artifacts and be
  idempotent.
- All trading behavior changes remain human-approved.
- Weekly analysis may prioritize monthly search only. It may not approve,
  reject, or bypass gates for any monthly candidate.
- New executable evaluation must support a no-provider offline mode so CI can
  run without live LLM calls.
- Harness evaluation must run against isolated or read-only memory/run
  surfaces. It must not increment production learning-card retrieval counters,
  generated-playbook usage counters, cost logs, run indexes, approval trackers,
  or provider-routing evidence unless explicitly running in an approved
  experiment mode.

## Workstream Overview

| Priority | Workstream | Primary Value | Depends On |
|---|---|---|---|
| P0 | Source-of-truth cleanup | Prevents stale backlog churn | None |
| P1 | Executable harness benchmark | Makes harness changes measurable | Existing benchmark compiler and harness ledger |
| P1 | Focused recall + artifact-aware reviewer | Reduces repeated mistakes and bad memory | RunIndex, existing focused recall cards, ContextBuilder, LearningWriteCoordinator |
| P1 | Monthly shadow pilot | Turns monthly path from code-ready to operational | Replay-ready strategy and market-data manifests |
| P1 | Weekly-to-monthly search brief | Lets weekly evidence guide search without adding decision noise | Weekly evidence + monthly run manifest |
| P1 | Monthly optimizer runner sequence | Core trading-performance candidate generation | Monthly validation artifact contract + replay-ready strategy |
| P2 | Playbook curator | Prevents stale procedural memory bias | Playbook usage tracking |
| P2 | Monthly repair path | Handles incomplete evidence safely | Monthly model-review runner |
| P3 | Provider-routing hardening | Uses better evidence once P1/P2 land | Executable benchmark + monthly outcomes |

## Phase 0 - Source Of Truth And Baseline

Goal: update planning surfaces so implementation does not chase already-landed
or stale gaps.

Actions:

- Update the HTML explainer or add an errata note near sections 8-10:
  - mark monthly validation/model review workflows as live;
  - mark `harness_program.md` as live;
  - change harness evaluator status to variant-aware executable replay with
    deterministic fallback unable to promote variants;
  - change playbook status to show injection-time usage tracking and lifecycle
    curation are live;
  - change monthly model review from "not first-class" to "first-class runner
    exists; repair path/invoker rollout still open".
- Remove or update stale `memory/skills/skills_index.md` WFO references.
- Record a baseline test set for this plan:
  - `pytest tests/test_harness_eval_runner.py -q`
  - `pytest tests/test_learning_review_orchestrator.py -q`
  - `pytest tests/test_monthly_candidate_generation.py -q`
  - `pytest tests/test_monthly_learning_loop_phase3.py -q`
  - `pytest tests/test_provider_route_scorer.py -q`
- Capture current reference maps with `rg` for:
  - `harness_program`
  - `monthly_model_review`
  - `focused_recall`
  - `generated_playbook`
  - `wfo_pipeline`
  - `REQUIRED_BACKTEST_ARTIFACTS`

Deliverables:

- Corrected explainer or companion errata.
- Removed stale WFO skill index entry, or explicit historical label.
- Baseline test results in the implementation PR summary.

Acceptance criteria:

- No roadmap/backlog item claims monthly model review or monthly workflows are
  absent.
- The remaining gaps list matches this document.
- Targeted baseline tests pass before feature work starts.

Rollback:

- Documentation-only changes can be reverted independently.

## Phase 1 - Executable Harness Benchmark

Status: implemented for the local deterministic/sandboxable contract.

Goal: keep `HarnessEvalRunner` as an executable benchmark that can compare
baseline and candidate harness variants against frozen cases. Remaining work is
coverage depth and opt-in provider-sandbox replay, not the local execution
boundary.

### Design

Add an execution layer around existing `BenchmarkCase` records.

Recommended new or extended components:

- `schemas/harness_learning.py`
  - `HarnessExecutionMode`: `deterministic_only`, `recorded_agent`,
    `provider_sandbox`.
  - `HarnessExecutionInput`: frozen workflow, bot, strategy, run metadata,
    prompt inputs, retrieval profile, allowed artifacts, expected behavior, and
    forbidden behavior.
  - `HarnessExecutionOutput`: prompt package hash, retrieved card/playbook ids,
    raw response path or fixture id, parse result, validation result, evidence
    refs used, cost/latency, and governance flags.
- `skills/harness_case_materializer.py`
  - converts current `BenchmarkCase` rows into executable case folders;
  - freezes prompt input snapshots and artifact refs;
  - refuses materialization when provenance is missing.
- `skills/harness_execution_runner.py`
  - runs prompt assembly and context retrieval for each variant;
  - supports recorded agent outputs for deterministic CI;
  - optionally invokes a provider only when explicitly configured;
  - always runs parser and validator on the produced response;
  - executes against a sandboxed memory/runs root, or uses an explicit
    read-only context-building mode that suppresses retrieval and playbook usage
    counters.
- `skills/harness_eval_runner.py`
  - consumes execution outputs as primary scoring evidence;
  - keeps current deterministic scoring as fallback only when execution inputs
    are incomplete;
  - records fallback use as a warning in the ledger.

### Execution Modes

`deterministic_only`:

- CI-safe default.
- Rebuilds context, parser, validator, artifact checks, and governance checks.
- Uses stored raw response or structured output from the benchmark case.
- Uses isolated memory state and does not write run-index, card-retrieval,
  playbook-usage, cost, approval, or provider score records.

`recorded_agent`:

- Uses frozen prompt packages and recorded agent outputs.
- Validates prompt/retrieval changes without live provider cost.

`provider_sandbox`:

- Optional local/dev mode.
- Invokes `AgentRunner` through a sandbox provider selection.
- Never writes approvals, deploys changes, or mutates policy memory.
- Writes run artifacts only under an experiment-specific harness run root.

### Scoring

Primary metrics:

- parser/schema success;
- validator pass/block accuracy;
- evidence citation completeness;
- repeated-negative avoidance;
- monthly authority compliance;
- deterministic gate fidelity;
- hallucinated artifact/path rate;
- confidence calibration against known outcomes;
- governance hard-fail absence.

Secondary metrics:

- cost;
- latency;
- prompt size;
- complexity score.

Hard-fail metrics:

- approval bypass;
- policy edit attempt;
- direct live trading command;
- unsupported material strategy change;
- hallucinated evidence used as authority;
- weakened deterministic gates;
- cost-only provider promotion.

### Keep/Discard

- Keep a variant when primary score improves by the configured threshold and no
  hard-fail regresses.
- Keep a tie only when complexity, cost, or latency improves without quality
  loss.
- Discard otherwise.
- Always write a ledger entry, including discarded experiments and future
  warning tags.

### Tests

Add or extend:

- `tests/test_harness_case_materializer.py`
- `tests/test_harness_execution_runner.py`
- `tests/test_harness_eval_runner.py`
- fixtures under `tests/fixtures/harness_cases/`

Required cases:

- validation block that a permissive variant tries to approve;
- negative monthly prior that requires stronger evidence;
- hallucinated artifact path;
- repeated rejected idea;
- model response with partial JSON parse;
- monthly candidate gate failure;
- tie where lower complexity wins;
- provider sandbox disabled in CI;
- context-building harness run does not mutate production learning-card
  retrieval counts or generated-playbook usage counts.

Acceptance criteria:

- A benchmark run can compare baseline vs candidate using real prompt assembly,
  retrieval, parser, and validator outputs.
- CI can run the benchmark without network or live LLM calls.
- A variant cannot be kept if it weakens approval gates or monthly authority.
- `harness_experiment_ledger.jsonl` explains why each variant was kept or
  discarded.
- Fallback heuristic scoring is visibly marked and cannot promote a variant by
  itself.

Rollback:

- Keep existing `HarnessEvalRunner` deterministic path as fallback until the
  executable runner passes fixtures and at least one weekly learning cycle.

## Phase 2 - Focused Recall And Artifact-Aware Learning Review

Goal: replace snippet-only similar-run context with focused evidence summaries,
then let post-run review create durable advisory learning from concrete
artifacts.

### 2A - Focused Run Recall

Add `skills/run_recall_summarizer.py` or an equivalent focused-recall service
that normalizes both `RunIndex` search results and existing
`focused_recall_cards.jsonl` records.

Inputs:

- current workflow, bot, strategy, category, regime, and validation tags;
- `RunIndex.search()` results;
- existing `memory/findings/focused_recall_cards.jsonl` records written by
  `LearningReviewOrchestrator`;
- run folders and artifacts;
- proposal/suggestion/strategy-change ledgers;
- monthly outcomes and outcome priors;
- validation blocks and approval status.

Outputs:

- compact recall cards:
  - `run_id`;
  - date;
  - workflow;
  - reason for retrieval;
  - proposal or finding summary;
  - validator/gate status;
  - approval/deployment/outcome status;
  - concrete evidence paths;
  - supersession or contradiction notes;
  - "how this matters now".

Integration:

- Add `ContextBuilder.load_focused_recall(...)`.
- Budget focused recall separately from learning cards and generated playbooks.
- Inject recall as evidence context, not instructions.
- Prefer focused recall over raw `similar_past_runs` when provenance and outcome
  status are available.
- Keep existing `similar_runs` snippets as fallback during rollout.

Tests:

- search returns top runs but summarizer suppresses stale contradicted recall;
- existing `focused_recall_cards.jsonl` rows can be loaded, validated, and
  budgeted;
- recall includes approval/outcome status when ledger entries exist;
- recall refuses entries without artifact provenance;
- context budget can drop recall without dropping higher-priority policy or
  monthly evidence.

Acceptance criteria:

- Focused recall entries include artifact paths and dates.
- They distinguish proposed, blocked, approved, deployed, measured, and rolled
  back states.
- Newer monthly outcomes can supersede older recall.
- Similar-run snippets remain available as fallback only.

### 2B - Artifact-Aware Post-Run Reviewer

Upgrade `skills/learning_review_orchestrator.py` from deterministic
harness/provider review into a bounded post-run reviewer.

Trigger conditions:

- report validation failed;
- response parser partially failed;
- monthly candidate was blocked;
- model review failed validation;
- suggestion outcome contradicted prior expectation;
- retrieval included cards/playbooks later judged harmful;
- a run produced a material proposal;
- N runs occurred for the same workflow/bot/category since last review.

Inputs:

- run folder metadata and response;
- prompt package metadata;
- retrieved learning-card and playbook ids;
- parsed output and validator result;
- report checklist;
- monthly validation artifacts;
- approval packet and gate reports;
- current outcome priors;
- focused recall cards.

Allowed actions:

- create or update learning cards;
- record retrieval as helpful/harmful when evidence supports it;
- create benchmark cases;
- propose playbook update or quarantine;
- create focused recall cards;
- record provider/harness warning tags.

Forbidden actions:

- edit `memory/policies`;
- approve, deploy, or change trading logic;
- weaken approval gates;
- write outside learning/artifact directories;
- create learning without artifact evidence.

Implementation notes:

- Current reviewer writes learning cards through `LearningCardStore` directly.
  Migrate reviewer-created learning-card, focused-recall, benchmark-case, and
  playbook-curation writes through `LearningWriteCoordinator`, or extend the
  coordinator with typed helper methods for those artifacts.
- Add a target allowlist and path normalization to reviewer writes. The current
  coordinator provides provenance and per-process deduplication; it should not
  be treated as a complete safety scanner by itself.
- Use idempotency keys based on run id, action type, and evidence refs.
- Add `review_mode`: `disabled`, `deterministic`, `llm_review`.
- Keep `deterministic` as default until fixture tests and one shadow cycle pass.
- For `llm_review`, use structured output with a strict validator before any
  write action is applied.

Tests:

- no write occurs without evidence paths;
- duplicate review does not duplicate cards/cases;
- harmful playbook recommendation quarantines only generated playbooks;
- reviewer cannot write policy files;
- reviewer cannot use path traversal or arbitrary `LearningWriteCoordinator`
  targets;
- malformed LLM review output is rejected fail-closed;
- deterministic mode preserves current behavior.

Acceptance criteria:

- Reviewer outputs are idempotent and evidence-bounded.
- Every write has a provenance path.
- Reviewer can be disabled per workflow.
- Reviewer-created artifacts appear in the write log with a shared
  `write_group_id`.
- Generated learning remains advisory and visible in ledgers.

Rollback:

- Keep `review_mode=deterministic` as the default until LLM review proves stable.

## Phase 3 - Monthly Shadow Pilot

Goal: move monthly validation from code-ready to operational for one
replay-ready strategy without approval routing at first.

Prerequisites:

- valid `BACKTEST_REPO_PATH`;
- one strategy with a passing external replay adapter;
- market-data manifest reaches the latest completed month;
- telemetry lineage ratio meets threshold;
- replay parity report is produced and machine-readable;
- monthly model-review invoker can be disabled or run in controlled mode;
- approval-gated dry-run uses the existing shared `ApprovalTracker` /
  `ApprovalHandler` plumbing from `orchestrator/app.py`, not a new approval
  subsystem.

Actions:

- Select one pilot strategy and document:
  - bot id;
  - strategy id;
  - data source;
  - replay adapter path;
  - expected monthly artifact root;
  - owner and rollback contact.
- Set configuration for pilot environment:
  - `MONTHLY_VALIDATION_MODE=shadow`;
  - `MONTHLY_VALIDATION_ENABLED=true`;
  - market-data sync schedule on day 1;
  - monthly validation schedule on day 2.
- Run one manual shadow cycle before relying on cron.
- Record artifact completeness:
  - telemetry manifest;
  - market-data manifest;
  - run manifest;
  - artifact index;
  - replay parity report;
  - gap attribution;
  - candidate summary and gate report;
  - model review request/prompt or skipped reason;
  - strategy-change monthly-review record.
- Add a `docs/migration/` or `docs/plans/` pilot runbook with command examples
  and expected files.

Exit criteria for staying in shadow:

- missing or malformed market-data manifest;
- lineage below threshold;
- replay parity not eligible;
- candidate artifacts missing;
- model review blocks all approval-ready candidates due to missing evidence;
- monthly report omits any required provenance.

Exit criteria for `approval_gated` promotion:

- two consecutive shadow runs complete with no artifact contract failures;
- incumbent replay parity is acceptable and stable;
- candidate gate report is generated and understandable;
- approval packet can be generated in dry-run form;
- rollback thresholds are documented;
- manual operator confirms evidence package is sufficient.

Tests:

- targeted monthly evidence tests;
- one pilot dry run with local fixture data;
- scheduler test confirming monthly jobs only run when enabled;
- approval-gated dry-run test with no real deployment;
- regression check that `approval_gated` monthly mode has approval plumbing even
  when `AUTONOMOUS_ENABLED=false`.

Acceptance criteria:

- At least one strategy has a repeatable monthly shadow run.
- Shadow run writes all expected artifacts and ledgers.
- Failures block authoritative verdicts rather than creating false confidence.
- Promotion to `approval_gated` is a deliberate config change, not automatic.

Rollback:

- Set `MONTHLY_VALIDATION_MODE=disabled`.
- Preserve all shadow artifacts for diagnosis.

## Phase 3B - Weekly-To-Monthly Search Brief

Goal: let weekly evidence guide the fixed monthly optimization sequence without
turning weekly analysis into trading authority.

Add a structured, non-authoritative `monthly_search_brief.json` artifact. It
should be generated from weekly outputs and stored with the next monthly run
inputs, then passed to the LLM experiment planner and external runner as search
priors only. It may shape what gets tested first, but it must not change the
monthly sequence: diagnostics, LLM phased-auto plan, two-fold in-sample
phased-auto, conditional OOS repair, repair-centered confirmatory follow-up,
and `round_N+1` adoption.

Inputs:

- latest weekly synthesis and deterministic detector findings;
- active hypotheses and structural experiment records;
- recent accepted/rejected suggestions and monthly outcomes;
- outcome priors and category recalibrations;
- explicit evidence paths for every included signal.

Suggested schema fields:

- `brief_id`;
- `generated_at`;
- `run_month`;
- `bot_id`;
- `strategy_id`;
- `experiment_focus_hints`;
- `phased_auto_priority_families`;
- `seed_parameter_neighborhoods`;
- `oos_repair_ablation_priorities`;
- `prioritized_mutation_families`;
- `seed_candidates`;
- `rollback_candidates`;
- `negative_priors`;
- `confidence_cap`;
- `evidence_paths`;
- `source_weekly_signal_ids`.

Rules:

- Weekly hints are search priors, not mode selectors.
- The brief cannot decide whether phased-auto runs; phased-auto remains the
  standard monthly optimization pass when maturity/data gates pass.
- The brief cannot trigger OOS repair; OOS repair only runs after phased-auto if
  latest-month selection-OOS materially trails the in-sample/fold profile.
- Weekly seed candidates can change LLM-plan emphasis, phase order, or
  candidate-neighborhood order, not candidate status.
- Every signal must cite evidence paths and carry recency/sample-size metadata.
- One-week signals should be confidence-capped unless supported by monthly
  outcomes or repeated weekly evidence.
- The monthly runner must preserve attribution from search-brief signal to
  candidate and outcome so weekly guidance can be scored later.

Implementation notes:

- Add `schemas/monthly_search_brief.py`.
- Add `skills/monthly_search_brief_builder.py`.
- Include `monthly_search_brief_path` in the monthly run manifest or adjacent
  monthly validation evidence bundle.
- Teach the LLM experiment planner and external runner contract to accept the
  brief as optional input and emit which brief signals influenced plan sections,
  phase order, candidate neighborhoods, repair ablations, or candidates.
- Feed downstream outcome attribution back into `LearningCycle` and
  `SearchAllocationPolicy`.

Tests:

- one-week noisy signal is capped and cannot create an approval-ready candidate;
- repeated evidence raises search allocation but still requires replay gates;
- brief cannot change the monthly sequence or trigger OOS repair;
- phased-auto experiment-plan fixture consumes brief priorities without treating
  them as evidence gates;
- rollback hint prioritizes OOS-repair ablation candidates if the phased-auto
  shortlist later fails selection-OOS;
- negative prior forces stronger validation or suppresses the family;
- candidate output preserves `source_weekly_signal_ids`.

Acceptance criteria:

- A monthly run can include a search brief without changing any approval gates.
- The LLM experiment planner, phased-auto fixture runner, and OOS-repair fixture
  runner can consume the brief to change plan emphasis, phase ordering, seed
  neighborhoods, and conditional ablation order.
- Monthly candidate and outcome records retain attribution back to weekly
  signals.

## Phase 4 - Monthly Optimizer Runner Sequence

Goal: make the monthly candidate-generation sequence production-grade enough to
turn diagnostics into a `round_N+1` optimized backtest config while keeping live
deployment approval-gated.

Criticality: this is the trading-performance engine of the learning loop. The
model-review layer can interpret, challenge, and package evidence, but it should
not invent high-value candidates or compensate for shallow optimization. If
phased-auto and OOS repair remain thin, the system becomes better at explaining
performance than improving it.

### 4A - Runner Contract

Formalize the external backtest runner contract around the existing
`BacktestRunnerClient`, `BacktestArtifactIndex`, and
`REQUIRED_BACKTEST_ARTIFACTS` surfaces:

- input manifest path;
- monthly optimizer workflow contract path/version;
- optional monthly search brief path;
- command template;
- strategy plugin id;
- `round_N` strategy config path/version;
- `round_N` portfolio config path/version;
- `trading_assistant` run/control-plane code SHA;
- `trading_assistant_backtest` path and commit SHA;
- actual trading repo path, branch, and commit SHA;
- data manifest path/checksum;
- repo-level data bundle manifest path/checksum
  (`schemas/data_bundle_manifest.py`), with data repo commit, slice manifests,
  calendars, fee/slippage versions, adjustment policy, and
  authoritative/diagnostics-only status;
- strategy plugin contract path/version
  (`schemas/strategy_plugin_contract.py`), binding live strategy code,
  backtest adapter code, config schema version, decision API version,
  required telemetry schemas, supported symbols/timeframes, parity fixtures,
  and maturity;
- in-sample window: all reliable data before the latest completed month;
- selection-OOS window: the latest completed month;
- fold manifest path for the two purged in-sample folds;
- rounds manifest path, prior round id, and next round id;
- full end-of-round diagnostics path;
- structural candidate patch paths when applicable:
  - live trading repo patch;
  - backtest adapter patch;
  - config/schema patch;
- candidate workspace root, sanitized workspace key, and workspace manifest path;
- attempt id, attempt number, attempt status, retry reason, and stall timeout;
- output artifact names;
- exit codes;
- required JSON schemas;
- backtest repo commit SHA;
- max workers, defaulting to `2` for monthly phased-auto;
- checkpoint/cache paths for long-running optimization and repair;
- source runner contract versions:
  - `smoke_repair_runner_contract_v1`;
  - `phased_auto_runner_contract_v1`.
- emitted attribution from candidate to any consumed
  `source_weekly_signal_ids`.

Existing required artifacts are defined in `schemas/backtest_artifacts.py`:

- `coverage_manifest.json`;
- `incumbent_validation.json`;
- `gap_attribution.json`;
- `mode_decision.json`;
- `replay_parity_report.json`;
- `objective_breakdown.json`;
- `candidate_results.jsonl`;
- `selected_candidates.json`;
- `rejected_candidates.jsonl`;
- `monthly_report.md`;
- `stdout.log`;
- `stderr.log`;
- `exit_status.json`.

`artifact_index.json` is the index file read by `BacktestRunnerClient`; it is
not listed inside `REQUIRED_BACKTEST_ARTIFACTS` because it is the contract
container. Phase 4 should add optional or required extension artifacts only when
the candidate gates actually consume them, for example:

- `leakage_report.json`;
- `cost_sensitivity.json`;
- `fold_validation.json`;
- `outlier_sensitivity.json`;
- `portfolio_synergy.json`;
- `fold_manifest.json`;
- `rounds_manifest.json`;
- `end_of_round_diagnostics.json`;
- `llm_experiment_plan.json`;
- `structural_candidate_plan.json`;
- `live_repo_patch.diff`;
- `backtest_adapter_patch.diff`;
- `decision_parity_report.json`;
- `candidate_workspace_manifest.json`;
- `candidate_attempts.jsonl`;
- `runner_observability.json`;
- `repair_ablation_matrix.jsonl`;
- `confirmatory_rerank.json`.

The contract must preserve source attribution all the way into
`MonthlyCandidatePipeline`: OOS-repair candidates need
`runner_contract_version=smoke_repair_runner_contract_v1`, phased-auto
candidates need `runner_contract_version=phased_auto_runner_contract_v1`, and
unknown/model-only candidates must remain unable to create approval-ready
trading changes. Weekly search-brief inputs may reorder search or seed
candidate neighborhoods, but they must not satisfy improvement, calibration,
drawdown, cost, outlier, model-review, or approval-payload gates by themselves.
For optimizer runs, `artifact_index.json` must include the run `manifest_id`;
`coverage_manifest.json` must echo the data bundle checksum; selected
candidates must carry run id, manifest id, round ids, repo SHAs, succeeded
attempt linkage, and the expected runner contract version. Structural
candidates additionally require live repo and backtest adapter patches plus a
schema-valid `DecisionParityReport` covering signals, filters, entries, exits,
stops, sizing, risk caps, and order intent.
The latest completed month may be used as selection-OOS during this sequence,
but once used for selection or repair it is no longer a clean deployed verdict;
the next completed month after approval/deployment is the first clean verdict.

Repository boundary:

- `trading_assistant` is the control plane: scheduling, manifests, evidence
  contracts, ledgers, approval routing, and artifact ingestion.
- `trading_assistant_backtest` is the experiment lab: diagnostics, phased-auto,
  OOS repair, replay, scoring, and artifact emission behind the runner contract.
- The actual trading repo is production truth for strategy behavior. Structural
  candidates must be implemented against production-style strategy code first,
  or against a shared package imported by production, then exposed to backtest
  through an adapter.
- Backtest-only approximations are not approval-ready. A structural candidate is
  eligible for scoring only after unit tests and decision-level live/backtest
  parity pass for signals, filters, entries, exits, stops, sizing, and risk
  blocks.
- The shared executable contract lives in `contracts.validate_monthly_runner`.
  Future `trading_assistant_backtest` runners should use
  `python -m contracts.validate_monthly_runner --manifest run_manifest.json`
  against their emitted artifacts before claiming conformance.

Symphony-style orchestration patterns to port:

- Use deterministic per-candidate workspaces for structural phased-auto and
  long-running repair attempts. Workspace keys must be sanitized, resolved paths
  must stay under the configured workspace root, and all agent/subprocess work
  must run with `cwd` equal to the candidate workspace.
- Add a repo-owned monthly optimizer workflow contract, for example
  `MONTHLY_OPTIMIZER_WORKFLOW.md` or `PHASED_AUTO_WORKFLOW.md` in
  `trading_assistant_backtest`, for runner command, hooks, timeouts,
  `max_workers`, score-component cap, parity requirements, artifact names, and
  prompt template. Freeze the parsed contract version into each run manifest.
- Track candidate attempts through explicit states: unclaimed, claimed, running,
  retry queued, released, succeeded, failed, timed out, stalled, and canceled by
  reconciliation.
- Add bounded retry/backoff, stall detection, and reconciliation. Cancel or
  release attempts if the run manifest changes, repo SHAs drift, data manifests
  become stale, approval state changes, or a candidate is no longer eligible.
- Emit structured observability for run id, candidate id, workspace, attempt
  state, subprocess pid, phase, token usage when agent-driven, timeout/stall
  status, retry state, artifact paths, and parity status.
- Do not port Symphony's issue-tracker daemon, Linear business logic,
  high-trust auto-approval posture, or "no durable state required" assumption.
  Monthly optimizer attempts should be durable and approval-gated.

### 4B - Full Diagnostics And LLM Experiment Plan

Before optimizing, run full end-of-round diagnostics on the latest optimized
strategy and portfolio configs over the in-sample window, with the latest-month
selection-OOS comparison kept separate. The LLM then reads those diagnostics and
writes a structured phased-auto experiment plan; it does not approve changes.

The plan should explicitly evaluate:

- whether signal extraction is capturing available alpha or leaving alpha on
  the table;
- whether signals and filters discriminate strongly enough against negative or
  low-quality trades;
- entry timing, entry triggers, and candidate additional entry mechanisms;
- trade management, sizing, stop, take-profit, and partial-exit behavior;
- exit mechanism quality, including early-exit and late-exit failure modes;
- structural candidates as well as incremental parameter mutations;
- whether each structural candidate requires live strategy code, backtest
  adapter code, schema/config changes, or all three;
- implementation risk, required tests, rollback plan, and parity assertions for
  every structural candidate;
- experiment order, dependencies, and stopping rules;
- immutable objective version with no more than seven score components, score
  scaling, drawdown/trade-frequency balance, and cost assumptions;
- overfit risks from small samples, outliers, sparse regimes, and correlated
  candidates.

Acceptance criteria:

- Diagnostics are generated before candidate search and are stored with stable
  evidence paths.
- The LLM output is machine-readable and rejected if it lacks evidence links,
  candidate families, gate expectations, or overfit-risk notes.
- The plan can steer phased-auto ordering but cannot satisfy replay,
  improvement, or approval gates.

### 4C - Two-Fold Phased-Auto On In-Sample Data

Implement or adapt phased-auto as the first monthly optimization pass for mature
strategies:

- use the latest optimized configs as the starting baseline;
- treat all data before the latest completed month as in-sample;
- build two purged in-sample folds with embargo; the fold boundaries shift each
  month as the data history grows;
- keep the latest completed month fully outside phased-auto scoring;
- consume optional `monthly_search_brief.json` as search-prior guidance for LLM
  plan emphasis, phase order, and seed neighborhoods only;
- follow the LLM experiment plan when choosing phase specs, candidate families,
  and experiment order;
- include candidate families for signal extraction, signal quality filters,
  entries, added mechanisms, trade management, exits, sizing, and portfolio
  interactions;
- treat structural changes as first-class phased-auto candidates, not a separate
  workflow: new signals/features, entry/exit mechanisms, trade-management logic,
  and portfolio interaction logic can compete with config-only candidates;
- for structural candidates, create isolated worktrees/branches for the actual
  trading repo and `trading_assistant_backtest`, implement the smallest viable
  code/config change, and record patch paths and SHAs before scoring;
- update or add the backtest adapter so it imports the live strategy logic or
  proves decision-level equivalence against the live repo implementation;
- run unit tests, strategy decision tests, and live/backtest parity checks before
  the structural candidate enters phased-auto scoring;
- tune parameter/config neighborhoods around passing structural candidates using
  the latest optimized configs as the baseline;
- use a fixed objective that leans aggressive but controlled: maximize expected
  return and trading frequency while minimizing max drawdown and cost leakage;
- keep the immutable score to no more than seven components;
- run with `max_workers=2` unless the run manifest explicitly lowers it;
- apply sample-size, trade-count, fold-consistency, drawdown, cost sensitivity,
  outlier-exclusion, and portfolio/synergy gates;
- retain every rejected candidate and rejection reason;
- emit `runner_contract_version=phased_auto_runner_contract_v1` in candidate
  gate inputs.

Acceptance criteria:

- Phased-auto only runs when data, plugin maturity, replay parity, and sample
  size are sufficient.
- Selected candidates improve the canonical objective and pass hard gates on
  both in-sample folds.
- Structural candidates carry live repo patch, backtest adapter patch,
  config/schema patch when applicable, code SHAs, rollback plan, and
  decision-level parity report before they can be shortlisted.
- Config-only and structural+config candidates compete under the same objective,
  but structural candidates require stronger tests and lineage.
- Rejected candidates, search order, objective breakdown, and fold-local scores
  are retained.
- If no strategy is mature enough for phased-auto, fixture runners still prove
  phase specs, greedy selection, rejection retention, and gate behavior end to
  end.

### 4D - Selection-OOS Repair

After phased-auto, compare the shortlisted candidate against in-sample/fold
expectations and latest-month selection-OOS. If selection-OOS materially trails
the in-sample or fold profile, run OOS repair behind the existing monthly
adapter:

- diagnose whether underperformance is driven by edge cases, regime drift,
  low-value accepted mutations, overfit interactions, execution cost, or sparse
  latest-month sampling;
- use weekly rollback/weakness hints only to order the ablation queue after the
  selection-OOS repair trigger has fired;
- ablate all cumulative accepted mutations from all previous rounds, not only
  the most recent round;
- prefer granular one-at-a-time and small-combination ablations before broad
  cluster rollback;
- run local numeric/boolean perturbations around accepted mutations;
- add targeted mutations from the latest-month OOS weakness analysis when they
  can raise both in-sample and OOS performance, or materially raise OOS without
  materially hurting in-sample/fold performance;
- use long timeouts, checkpointing, and cached replay reuse because exhaustive
  ablation/perturbation can be slow;
- confirm candidate repairs through purged in-sample folds, cost checks,
  outlier checks, and selection-OOS comparison;
- emit `runner_contract_version=smoke_repair_runner_contract_v1` in candidate
  gate inputs.

Acceptance criteria:

- OOS repair can explain whether accepted mutations, edge cases, or overfit
  interactions likely caused degradation.
- All cumulative accepted mutations are represented in the ablation matrix or
  have a deterministic skip reason.
- Each candidate has keep/reject/repair/experiment status and evidence.
- Repair candidates cannot trade away material in-sample/fold quality just to
  fit the latest month.
- At least one replay-ready strategy can run OOS repair in shadow mode or
  produce a deterministic insufficient-data/insufficient-parity reason.

### 4E - OOS-Repair-Centered Confirmatory Follow-Up And Adoption

Add a final confirmatory pass before recording the optimized round:

- when OOS repair runs, treat the OOS-repair recommended candidate as the
  primary candidate to challenge and refine, not merely one item in a flat
  leaderboard;
- run targeted follow-up rounds around that repair candidate: local parameter
  perturbations, small add/remove mutation toggles, focused rollback variants,
  and narrow structural additions tied to the diagnosed OOS weakness;
- compare those follow-up variants against the original repair recommendation,
  phased-auto winner, incumbent, rollback candidates, and targeted additions
  under the same immutable objective;
- prefer variants that raise both in-sample and selection-OOS performance, or
  materially raise selection-OOS without material in-sample/fold deterioration;
- let the model review whether the repair recommendation is genuinely best or
  whether a bounded targeted follow-up round is still justified by the evidence;
- require deterministic replay to score every follow-up variant;
- if OOS repair was not triggered, use the same confirmatory logic around the
  phased-auto winner instead;
- adopt the best backtest candidate as `round_N+1` optimized configs;
- update `rounds_manifest.json` and link prior/current/next round ids;
- run and save full end-of-round diagnostics for `round_N+1`;
- verify live/backtest parity alignment before approval routing;
- record that `round_N+1` is an optimized backtest recommendation, not a live
  deployment.

Acceptance criteria:

- The monthly run ends with exactly one adopted backtest candidate or a clear
  deterministic no-adoption reason.
- When OOS repair runs, the confirmatory artifact shows the repair candidate,
  its local follow-up variants, and why the adopted candidate beat or failed to
  beat the original repair recommendation.
- `rounds_manifest.json` links `round_N`, candidate lineage, `round_N+1`,
  objective version, fold manifest, diagnostics, and approval state.
- Full diagnostics for the adopted candidate are saved before model review or
  approval packets claim readiness.
- Live deployment remains manual approval gated, and the next completed month is
  used as the first clean deployed verdict.

Tests:

- fixture runner that emits a known harmful mutation;
- fixture runner where phased-auto improves in-sample folds but fails
  selection-OOS repair gates;
- structural phased-auto fixture that emits live repo and backtest adapter
  patches, then passes/fails decision-level parity before scoring;
- candidate workspace safety tests for sanitized keys, path containment, cwd
  enforcement, retry/backoff, stall timeout, and reconciliation cancellation;
- fixture runner where granular ablation beats broad cluster rollback;
- fixture runner where a targeted addition improves selection-OOS without
  material in-sample deterioration;
- fixture runner where phased-auto candidate fails cost sensitivity;
- confirmatory follow-up fixture where a local variant around the OOS-repair
  recommendation beats the original repair candidate;
- confirmatory safety fixture where the incumbent beats the optimized candidate;
- artifact-index missing-key tests;
- candidate pipeline tests for each optimizer stage and rejection reason.

Rollback:

- Keep monthly validation incumbent-only until runner contract tests pass.

## Phase 5 - Generated Playbook Curator

Goal: prevent generated procedural memory from becoming stale, redundant, or
quietly harmful.

Actions:

- Extract or extend the existing `PlaybookGenerator._is_safe()` checks into
  `skills/generated_playbook_guard.py`:
  - validates evidence refs exist;
  - rejects vague or unbounded procedures;
  - rejects authority inflation, approval bypass, live-command wording, and
    unsupported "always do X" instructions;
  - enforces max size and max active count;
  - requires trigger, required evidence, steps, outputs, failure modes, and
    provenance.
- Add `skills/generated_playbook_curator.py`:
  - consolidates overlapping playbooks;
  - pins human-approved playbooks;
  - archives stale playbooks recoverably;
  - restores archived playbooks when a matching pattern recurs;
  - patches incorrect playbooks with provenance;
  - quarantines playbooks tied to harmful outcomes;
  - logs all curator actions.
- Extend `schemas/generated_playbook.py`:
  - `pinned_by`;
  - `archived_at`;
  - `archive_reason`;
  - `supersedes`;
  - `superseded_by`;
  - `curator_action_ids`;
  - `last_outcome_at`.
- Wire outcome attribution:
  - retrieved playbook ids already appear in prompt metadata;
  - generated playbook usage is already recorded during prompt injection;
  - validator/report/monthly outcomes should record whether retrieved playbooks
    were helpful, neutral, or harmful;
  - negative downstream outcomes should not automatically blame playbooks, but
    should create review candidates.

Tests:

- unsafe generated playbook is rejected;
- duplicate playbooks consolidate with evidence refs preserved;
- pinned playbook cannot be autonomously deleted;
- archived playbook can be restored;
- harmful playbook is quarantined and no longer injected;
- curator actions are reversible and logged.

Acceptance criteria:

- Every active generated playbook is traceable to evidence and usage.
- Prompt injection excludes quarantined/archived playbooks.
- Human-pinned playbooks are protected.
- Curator actions are recoverable.

Rollback:

- Curator can run in `report_only` mode before mutating manifests.

## Phase 6 - Monthly Repair Path For Incomplete Artifacts

Goal: handle incomplete monthly evidence explicitly instead of letting model
review infer through missing data or blocking without actionable repair.

Actions:

- Extend the existing failure surfaces first:
  - `BacktestRunnerResult.error`;
  - `BacktestArtifactIndex.validation_errors(...)`;
  - `MonthlyModelReviewRunResult.error`;
  - `model_review_error.json`;
  - `MonthlyValidationResult.blocking_reasons`.
- Add `schemas/monthly_repair_request.py`:
  - run id;
  - bot/strategy/month;
  - missing artifact keys;
  - malformed artifacts;
  - blocking gates;
  - owner component;
  - repair command hints;
  - retry eligibility;
  - evidence paths.
- Add `skills/monthly_repair_planner.py`:
  - classifies missing data, telemetry, replay, parity, candidate, and model
    review failures;
  - writes `monthly_repair_request.json`;
  - decides whether retry is safe;
  - creates a human-readable repair section for the monthly report.
- Integrate with `MonthlyValidationOrchestrator`:
  - produce repair requests for incomplete artifacts before model review;
  - also produce repair requests when the backtest command fails before an
    `artifact_index.json` can be trusted;
  - if selected candidates exist but model review is missing, distinguish
    "invoker unavailable" from "model review failed";
  - do not generate approval packets from incomplete evidence;
  - include repair request path in result evidence.
- Optional LLM repair prompt:
  - only after deterministic repair request is built;
  - may explain missing artifacts or suggest operator actions;
  - may not propose strategy changes.

Tests:

- missing market data manifest produces data repair request;
- missing or malformed `artifact_index.json` produces artifact-contract repair
  request;
- reusable conformance fixture runner covers valid incumbent artifacts,
  missing index, path containment, stale artifacts, malformed JSON/JSONL,
  optimizer core artifacts, and structural-candidate lineage failures;
- malformed replay parity produces replay repair request;
- missing selected candidates produces candidate-generation repair request;
- invoker timeout writes error and blocks approval;
- repair prompt cannot produce actionable trading change.

Acceptance criteria:

- Every blocked monthly run has a specific repair classification.
- Existing blocking reasons are preserved and linked to the repair request.
- Monthly report explains the next operational action.
- Approval packets are impossible when repair-required artifacts are missing.
- Repair output is evidence-bound and non-authoritative.

Rollback:

- Repair planner can initially run in report-only mode.

## Phase 7 - Provider Routing Evidence Hardening

Goal: improve provider routing inputs after executable benchmarks and monthly
outcomes are available.

This is not a first-class workflow coverage gap anymore. It is an evidence
quality gap.

Actions:

- Preserve the existing `ProviderRouteScorer` inputs:
  `validation_log.jsonl`, `outcomes.jsonl`, `recalibrations.jsonl`,
  `provider_benchmark_results.jsonl`, and `harness_eval_results.jsonl`;
  add `monthly_outcomes.jsonl` as direct monthly-validation evidence.
- Feed executable benchmark results into `ProviderRouteScorer` with explicit
  workflow/provider/model fields. Current harness eval records only become
  provider evidence when those fields are present.
- Include monthly model-review validation failures as provider quality signals:
  - parse failures;
  - invalid evidence paths;
  - unsupported actionable recommendations;
  - hallucinated artifacts;
  - calibration misses.
- Keep cost and latency as secondary tie-breakers only.
- Add route-change ledger entries:
  - previous provider;
  - new recommended provider;
  - score gap;
  - sample count;
  - benchmark quality;
  - rollback condition.
- Require higher sample thresholds for monthly workflows than daily/weekly.
- Add an offline provider benchmark mode that can compare providers before
  production routing changes.
- Do not change `AgentWorkflow` coverage as part of this phase unless a new
  workflow is genuinely introduced; monthly validation and monthly model review
  are already covered.

Tests:

- provider with lower cost but worse governance score is not promoted;
- provider with model-review parse failures is demoted;
- monthly workflow requires higher sample count;
- learned selection still respects explicit user override and cooldown.

Acceptance criteria:

- Provider promotion is never cost-only.
- Monthly validation/model review routing can learn from benchmark and real
  monthly outcomes.
- Route changes are explainable and reversible.

Rollback:

- Disable learned routing by clearing findings scores or setting explicit
  workflow overrides.

## Cross-Cutting Data Contracts

The following identifiers should be present in every relevant artifact:

- `run_id`;
- `bot_id`;
- `strategy_id`;
- `strategy_version`;
- `config_version`;
- `round_id`;
- `prior_round_id` when applicable;
- `next_round_id` when applicable;
- `deployment_id`;
- `parameter_set_id`;
- `code_sha`;
- `backtest_repo_commit_sha`;
- `live_trading_repo_commit_sha` when applicable;
- `control_plane_commit_sha` when applicable;
- `structural_candidate_id` when applicable;
- `candidate_workspace_key` when applicable;
- `candidate_workspace_path` when applicable;
- `candidate_attempt_id` when applicable;
- `candidate_attempt_status` when applicable;
- `retry_attempt` when applicable;
- `retry_reason` when applicable;
- `stall_timeout_seconds` when applicable;
- `workflow_contract_path` when applicable;
- `workflow_contract_version` when applicable;
- `live_repo_patch_path` when applicable;
- `backtest_adapter_patch_path` when applicable;
- `config_patch_path` when applicable;
- `decision_parity_report_path` when applicable;
- `objective_version`;
- `score_component_count`;
- `max_workers`;
- `is_window`;
- `selection_oos_window`;
- `fold_manifest_path` when applicable;
- `rounds_manifest_path` when applicable;
- `end_of_round_diagnostics_path` when applicable;
- `optimizer_stage` when applicable;
- `candidate_source` when applicable;
- `checkpoint_path` when applicable;
- `evidence_paths`;
- `monthly_search_brief_id` when applicable;
- `monthly_search_brief_path` when applicable;
- `source_weekly_signal_ids` when applicable;
- `approval_request_id` when applicable;
- `strategy_change_record_id` when applicable.

All new JSONL writes should be append-only or atomic rewrites through existing
store helpers. Every generated record needs a stable idempotency key.

## Suggested Implementation Order

1. Phase 0 source-of-truth cleanup.
2. Phase 1 executable harness benchmark materializer and CI-safe execution.
3. Phase 2A focused recall summarizer.
4. Phase 2B artifact-aware reviewer in deterministic mode, then optional LLM
   mode.
5. Phase 3 monthly shadow pilot.
6. Phase 3B weekly-to-monthly search brief: report-only baseline, then
   manifest attachment and optimizer-plan guidance validation.
7. Phase 4 monthly optimizer runner sequence, starting with the runner contract,
   Symphony-style candidate workspace/attempt orchestration, full diagnostics,
   fixture runners, and two-fold phased-auto immediately after the monthly
   shadow path is proven.
8. Phase 6 monthly repair planner, in parallel where practical, because the
   pilot and runner work will expose artifact gaps.
9. Phase 5 playbook curator in report-only mode, then guarded mutating mode.
10. Phase 7 provider-routing hardening after benchmark/monthly evidence exists.

## Verification Matrix

| Area | Minimum tests before merge |
|---|---|
| Harness benchmark | `tests/test_harness_case_materializer.py`, `tests/test_harness_execution_runner.py`, `tests/test_harness_eval_runner.py` |
| Focused recall | `tests/test_run_recall_summarizer.py`, `tests/test_context_builder.py` targeted recall cases |
| Learning review | `tests/test_learning_review_orchestrator.py` with deterministic, LLM-validation, write-coordinator, and target-allowlist fixtures |
| Monthly shadow | `tests/test_monthly_evidence_foundation.py`, `tests/test_monthly_candidate_generation.py`, pilot dry run |
| Weekly search brief | `tests/test_monthly_search_brief_builder.py`, fixture runner attribution tests |
| Monthly optimizer runner | fixture-runner tests for diagnostics, two-fold phased-auto, OOS repair, repair-centered confirmatory follow-up, Symphony-style candidate workspaces/attempts, and candidate pipeline gates |
| Playbook curator | `tests/test_generated_playbook_guard.py`, `tests/test_generated_playbook_curator.py` |
| Repair path | `tests/test_monthly_repair_planner.py`, blocked monthly run fixtures |
| Provider routing | `tests/test_provider_route_scorer.py`, `tests/test_agent_preferences.py` |

Before promoting monthly validation to `approval_gated`, run:

```bash
pytest tests/test_monthly_evidence_foundation.py tests/test_monthly_candidate_generation.py tests/test_monthly_learning_loop_phase3.py -q
pytest tests/test_harness_eval_runner.py tests/test_learning_review_orchestrator.py tests/test_provider_route_scorer.py -q
```

Before merging broad changes, run:

```bash
pytest tests/ -q
```

## Operational Rollout

Stage 1: report-only baseline (complete).

- Focused recall, monthly search briefs, playbook curator recommendations, and
  repair requests were first emitted without changing runtime context or
  manifests.
- Report-only artifacts remain useful for dry-run fixtures and operator audits,
  but they no longer describe the current integrated behavior.

Stage 2: bounded shadow injection (current integrated state).

- Focused recall is injected into `ContextBuilder` with a small context budget
  and provenance checks.
- Artifact-aware reviewer writes bounded advisory learning cards from harness,
  run-folder, monthly candidate, model-review, approval, retrieval-context, and
  deployment artifacts.
- When `MONTHLY_VALIDATION_MODE=shadow` is enabled for a pilot bot, scheduled
  monthly validation carries optimizer-sequence defaults, backtest command, and
  workflow-contract metadata into the monthly request.
- Monthly search briefs are attached to monthly manifests and optimizer plans
  must cite the brief, consume its source weekly signal IDs, and reflect required
  candidate, rollback, and negative-prior families in phase/search guidance.
- Playbook curator can mutate generated playbook manifests in guarded mode,
  including archive, restore, quarantine, supersede, patch, and duplicate
  consolidation actions with logged evidence.

Stage 3: broader guarded mutation.

- Expand curator mutation from fixture/shadow coverage to scheduled runs after
  operator review of curator action logs.
- Harness variants may be kept when executable benchmark thresholds pass.
- Provider routing may use learned recommendations with workflow thresholds.

Stage 4: approval-gated monthly.

- Pilot strategy moves from `shadow` to `approval_gated`.
- Approval packets require complete monthly evidence, model-review validation,
  and rollback plans.

## Final Definition Of Done

This plan is complete when:

- The explainer/backlog no longer contains stale implementation-status claims.
- Executable harness evaluation can reject a bad harness change through a real
  prompt/parser/validator path.
- Focused recall entries with provenance are available to `ContextBuilder`.
- Artifact-aware review can write idempotent advisory learning through bounded
  write paths.
- One strategy completes monthly validation in shadow mode end to end.
- Weekly evidence can produce a bounded `monthly_search_brief.json` that changes
  monthly planner emphasis, phase order, seed neighborhoods, and conditional
  repair-ablation order in fixtures without changing sequence, triggers, or
  approval gates.
- Missing monthly artifacts produce repair requests with clear operator action.
- The monthly optimizer runner can produce or reject evidence-backed candidates
  through the external runner contract in fixtures, including diagnostics-driven
  two-fold phased-auto, selection-OOS repair, repair-centered confirmatory
  follow-up, Symphony-style candidate workspace/attempt tracking, `round_N+1`
  manifest adoption, saved end-of-round diagnostics, and live/backtest parity
  alignment; at least one replay-ready strategy exercises the sequence in shadow
  mode or records a clear deterministic blocker.
- Generated playbooks can be consolidated, pinned, archived/restored, and
  quarantined with logged curator actions.
- Provider routing uses benchmark/monthly evidence and remains reversible.
- All targeted tests and the full suite pass.
