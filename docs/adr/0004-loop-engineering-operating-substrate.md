# ADR-0004: Loop Engineering Operating Substrate

Date: 2026-06-21

Status: accepted

## Decision

Port only the loop-engineering pieces that strengthen the existing trading
evidence loop:

- Checked loop contracts under `packages/trading_assistant/memory/loops/`.
- Loop-run projection and generated work log.
- Artifact authority registry.
- Independent monthly evidence verifier.
- Workspace checks and smoke commands.

This port does not add top-level `signals/`, generic `domains/`, autonomous PR
shipping, live bot mutation authority, or autonomous writes to `memory/policies`.

## Source Of Truth

| Surface | Authority |
|---|---|
| Loop contracts | `packages/trading_assistant/memory/loops/*.md` plus `LoopContractStore` |
| Scheduler truth | `SchedulerConfig` and `build_scheduled_job_specs` |
| Run lifecycle | `ScheduledRunStore` |
| Agent tasks | `TaskRegistry` |
| Recent activity digest | generated from `memory/findings/loop_run_ledger.jsonl` |
| Artifact authority | `ArtifactAuthorityRegistry`, seeded from existing backtest artifact constants |
| Monthly approval evidence | deterministic gates plus `MonthlyEvidenceVerifier` |
| Material strategy outcomes | monthly and follow-up replay-backed outcomes |

## Initial Loop Contract Set

`daily_analysis`, `weekly_summary`, `monthly_validation`, `market_data_sync`,
`learning_cycle`, `outcome_measurement`, `bug_triage`, plus every current
stateful or coalesced scheduler job.

## Implementation Evidence

| AM row | Evidence |
|---|---|
| AM-01, AM-02 | `python tools/run_workspace_checks.py loop-contracts`; `tests/test_loop_contracts.py` includes scheduler matching and stale daily schedule fixture. |
| AM-03, AM-04 | `python tools/run_workspace_checks.py loop-ledger`; runtime projection tests prove finalized `ScheduledRunStore` records write `loop_run_ledger.jsonl` and regenerate `memory/work_log.md` without mutating lifecycle state. `tests/test_scheduled_runs.py::test_monthly_handler_projects_runtime_artifacts_after_scheduled_completion` proves single-result scheduled monthly handler output enriches the same projection with monthly artifacts, blockers, task ID, provider/model, `cost_usd`, duration, run folder, approval packets, and proposal IDs. `tests/test_scheduled_runs.py::test_monthly_handler_projects_multi_strategy_metadata_and_artifacts` proves multi-strategy scheduled monthly output preserves provider/model/cost metadata and scoped output-artifact links. Delivered integration evidence is recorded in `packages/trading_assistant/memory/findings/loop_run_ledger.jsonl`, `packages/trading_assistant/memory/work_log.md`, and non-placeholder artifacts under `packages/trading_assistant/memory/findings/loop_projection_acceptance/`. |
| AM-05 | `ContextBuilder` injects bounded `loop_contract` and `recent_work_log`; covered by `test_context_builder_injects_loop_contract_and_bounded_work_log`. |
| AM-06, AM-07 | `tests/test_artifact_authority_registry.py`; monthly search brief cannot satisfy approval gates or actionable model-review evidence, while hypothesis-only search-brief context does not suppress an unrelated clean actionable packet. |
| AM-08, AM-09 | `python tools/run_workspace_checks.py monthly-verifier`; verifier fixtures cover nonexistent actionable evidence, actionable advisory-evidence misuse, actionable diagnostics-only misuse such as `runner_observability.json`, mixed hypothesis-only/advisory context, deployment-metadata blocker overclaims, deployment path false positives, mismatched IDs, no selected candidates, `needs_human_review`, clean pass, and lightweight outcome misuse. Candidate-pipeline tests prove persisted gate/packet artifacts are verified before routing, verifier suppression prevents approval-ready packets and proposal-ledger `approve` decisions, and proposal IDs propagate into runtime projections. |
| AM-10 | `tools/run_workspace_checks.py` commands: `loop-contracts`, `loop-ledger`, `monthly-verifier`, `monthly-shadow-smoke`, `approval-packet-smoke`; `loop-contracts` passing output lists every checked AM row, including AM-08. |
| AM-11 | Verifier runs deterministically in shadowable artifact mode and suppresses approval on fail without changing live deployment behavior. |
| AM-12 | Lightweight outcome misuse fixture fails verification. |
| AM-13 | This ADR records scope, non-goals, source-of-truth surfaces, rollout state, and command evidence. |

## Current Commands

```text
python tools/run_workspace_checks.py loop-contracts
python tools/run_workspace_checks.py loop-ledger
python tools/run_workspace_checks.py monthly-verifier
python tools/run_workspace_checks.py monthly-shadow-smoke
python tools/run_workspace_checks.py approval-packet-smoke
python tools/run_workspace_checks.py monthly-focused
python tools/run_workspace_checks.py backtest-monthly
python tools/run_workspace_checks.py backtest-approval
python tools/check_loop_contracts.py --warning-mode
```

## Rollout State

The substrate is additive. Loop-contract checks and verifier fixtures run without
secrets or live market data. Verifier failure suppresses approval routing; it
does not deploy, mutate live bot state, or alter monthly scoring semantics.

## Checklist Closure

All applicable finite-checklist items are implemented by the files and commands
above. The data-heavy skip item is superseded because the new checks are
fixture-only and require no canonical local market data. Production CI-gating
and post-gated-run refresh items are superseded until a repository CI policy or
first production gated monthly run exists. The explicit non-goals remain: no
generic `domains/`, no top-level `signals/`, and no autonomous PR shipping for
material trading behavior.
