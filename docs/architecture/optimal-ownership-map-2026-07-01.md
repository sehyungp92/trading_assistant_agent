# Optimal Ownership Map

This map records the post-refactor owner modules for the architecture review
closed by `docs/plans/optimal-architecture-implementation-plan-2026-06-30.md`.

It is a module-architecture map, not a production-readiness certificate. The
deep modules below are the intended owners for ongoing work, but approval-gated
monthly adoption still requires live runtime/VPS deployment metadata, scheduled
shadow evidence, and at least one strategy bridge promoted from
`shadow_validated` to `approval_ready`.

| Capability | Owner Module | Notes |
|---|---|---|
| Control-plane runtime assembly | `packages/trading_assistant/src/trading_assistant/orchestrator/runtime.py` | `app.py` binds FastAPI routes and lifespan behavior to the built runtime. |
| Scheduler callbacks and side jobs | `orchestrator/runtime_scheduled_callbacks.py`, `runtime_side_jobs.py`, `runtime_dispatch.py` | `architecture-health` keeps broad runtime code from moving back into `app.py`. |
| Loop handlers | `orchestrator/loops/` and `orchestrator/action_handlers/` | `handlers.py` and `_handler_implementation.py` are delegating compatibility surfaces only. |
| Prompt evidence | `analysis/context_sources/` and `analysis/evidence_memory.py` | `ContextBuilder` keeps `PromptPackage` assembly and inherits loader compatibility from source-owned mixins. |
| Detector behavior and metadata | `analysis/detectors/` | `StrategyEngine` keeps public delegating detector methods while callers migrate. |
| Monthly artifact contract | `skills/monthly_artifact_contract.py` | Approval-facing artifact views and verifier inputs are built through the contract. |
| Approval authority vocabulary | `schemas/artifact_authority.py`, `skills/artifact_authority_registry.py` | Loop authority uses the shared artifact authority values. |
| Slice product | `trading_assistant_data/slices/` | Writer owns manifest paths/index updates; authority owns manifest authority views; validation/calendars remain the source of coverage truth. |
| Source refresh | `trading_assistant_data/source_refresh.py` | Request coverage preparation remains here; existing-manifest authoritativeness uses `slices.is_authoritative_slice_manifest`. |
| Monthly backtest execution | `trading_assistant_backtest/monthly_execution/` | `monthly.py` is only the CLI/command adapter. |
| Architecture enforcement | `tools/check_workspace_structure.py`, `tools/run_workspace_checks.py architecture-health` | The guard checks import direction, AST parsing, UTF-8 BOM absence, and watched module sizes. |

## Deletion-Test Summary

- `ContextBuilder` has no local `load_*` method bodies; source-owned mixins provide compatibility methods for direct callers.
- `monthly.py` no longer exposes `_run_manifest_impl` or dynamic `__getattr__` compatibility exports.
- `normalization.py` no longer owns slice manifest path or slice index helpers.
- Detector families for signal, execution, regime, portfolio, and crypto live under `analysis/detectors/`; `StrategyEngine` methods delegate for API stability.
- Backtest monthly structural registry constants remain single-sourced in `monthly_execution/structural_registry.py`.

## Readiness Axis

| Axis | Current State | Not Yet Implied |
|---|---|---|
| Module architecture | Runtime, loop, prompt-evidence, detector, monthly-artifact, data-slice, and backtest monthly owners exist and are guarded by focused checks. | Production adoption authority. |
| Operational readiness | Shadow-ready validation spine can produce and verify monthly artifacts, approval packets, and backtest evidence. | Live metadata from bots/VPS, scheduled shadow history, and an `approval_ready` bridge. |
| Approval authority | Artifact authority and monthly verifier checks fail closed around advisory, diagnostics-only, generated, and human-owned artifacts. | Permission to deploy or auto-adopt a strategy change without human approval. |

## Open Polish Tracks

- Detector modules still keep `StrategyEngine` compatibility wrappers while
  callers migrate; this is acceptable for API stability but should not become
  the long-term detector interface.
- `trading_assistant_data/normalization.py` remains a large command surface even
  though slice path/index and authority ownership moved under
  `trading_assistant_data/slices/`; future data work should keep moving rules
  toward the slice product without changing manifest schemas.
