# Final Monorepo Package Structure Implementation Plan

Date: 2026-06-04

## Objective

Migrate the workspace to the final optimal monorepo structure while preserving the
control/data/backtest boundaries that the workflow learning loop depends on.

Target structure:

```text
trading_assistant_agent/
  README.md
  docs/
  artifacts/
  packages/
    trading_assistant/
      pyproject.toml
      src/trading_assistant/
      tests/

    trading_assistant_data/
      pyproject.toml
      src/trading_assistant_data/
      tests/
      data/

    trading_assistant_backtest/
      pyproject.toml
      src/trading_assistant_backtest/
      tests/
      contracts/
      artifacts/
```

The migration is successful only if behavior, package entrypoints, tests, manifest
handoffs, artifact validation, and approval gates continue to work after the move.

## Non-Goals

- Do not merge the three runtime roles into one Python package.
- Do not replace manifest/artifact handoffs with direct in-process imports.
- Do not change strategy logic, data bundle contents, approval policy, or monthly
  optimizer semantics as part of this migration.
- Do not delete historical docs or artifacts unless a later cleanup plan explicitly
  classifies them as generated or obsolete.

## Current State Summary

- The parent `trading_assistant_agent` directory is not currently a git repository.
- `trading_assistant` is a nested git repo and has existing uncommitted changes.
- `trading_assistant_data` is a nested git repo and has many existing data/code changes.
- `trading_assistant_backtest` is a sibling workspace but is not currently a nested git
  repo in this checkout.
- `trading_assistant_data` and `trading_assistant_backtest` already use `src/` layout.
- `trading_assistant` currently exposes root-level packages such as `schemas`,
  `orchestrator`, `skills`, `analysis`, `comms`, and `contracts`.
- A direct move of `trading_assistant` into `src/trading_assistant/` requires a namespace
  migration from `schemas.*` to `trading_assistant.schemas.*`, and similar changes for
  all other root-level modules.
- The root structure guard exists at `tools/check_workspace_structure.py` and now
  supports `--layout current`, `--layout final`, and `--layout either`.
- `trading_assistant_data` currently has two checkout-time import conveniences:
  `trading_assistant_data/__init__.py` for agent-root execution, and
  `trading_assistant_data/trading_assistant_data/` for workspace-root execution.
- `trading_assistant_backtest` currently has two checkout-time import conveniences:
  `trading_assistant_backtest/__init__.py` for agent-root execution, and
  `trading_assistant_backtest/trading_assistant_backtest/` for workspace-root execution.
- `trading_assistant_data/pyproject.toml` uses `setuptools` package discovery from
  `src`, but it does not yet declare an explicit `[build-system]`.
- `trading_assistant_backtest/pyproject.toml` uses `hatchling`, `src/` package layout,
  and currently includes `backtests` in the wheel package list so the compatibility
  runner remains available.
- `trading_assistant/.env.example` still contains old path defaults such as
  `BACKTEST_REPO_PATH=../trading_backtests`; these must be updated during the cutover.
- `trading_assistant_backtest/src/trading_assistant_backtest/validation/validation_matrix.py`
  contains hardcoded sibling paths such as `trading_assistant_data/...` and
  `trading_assistant_backtest/artifacts/...`.
- Several backtest tests compute `AGENT_ROOT = Path(__file__).resolve().parents[3]` and
  then append `"trading_assistant_data"` or `"trading_assistant_backtest"`. Those tests
  need a shared fixture/path helper before or during the move.
- Windows startup scripts and process detection currently refer to module strings such as
  `orchestrator.app:app`; these become `trading_assistant.orchestrator.app:app` after
  the namespace migration.

## Design Principles

1. Preserve the three authority boundaries:
   - `trading_assistant`: control plane, gates, ledgers, approvals.
   - `trading_assistant_data`: canonical data product.
   - `trading_assistant_backtest`: replay and optimizer evidence lab.
2. Keep cross-workspace runtime communication manifest-driven.
3. Make the monorepo layout explicit without introducing hidden import coupling.
4. Make every phase independently testable and reversible through git.
5. Keep generated data and large artifacts out of structural refactors unless their paths
   must change and are covered by tests.
6. Prefer compatibility shims during transition, then remove them only after entrypoints
   and tests prove they are unnecessary.
7. Prefer install-based verification after each package move. Running from the package
   root can hide missing package metadata and package-data omissions.
8. Separate logical policy paths from physical source paths. Permission gates may still
   speak in logical paths like `skills/foo.py` even after the physical file moves to
   `src/trading_assistant/skills/foo.py`.

## Final Package Contract

### Root

The root owns workspace-level documentation, coordination scripts, CI orchestration, and
shared guardrails. It does not own runtime modules.

Expected root files:

```text
README.md
pyproject.toml              # optional but recommended for workspace tooling
docs/
tools/
artifacts/
packages/
```

### `packages/trading_assistant`

The control-plane package owns:

- `src/trading_assistant/orchestrator/`
- `src/trading_assistant/schemas/`
- `src/trading_assistant/skills/`
- `src/trading_assistant/analysis/`
- `src/trading_assistant/comms/`
- `src/trading_assistant/contracts/`
- `data/`, `memory/`, `scripts/`, `docs/`, and `tests/` as package-local resources

Allowed dependencies:

- Standard library and declared third-party dependencies.
- No runtime imports from `trading_assistant_data` or `trading_assistant_backtest`.
- Invokes data/backtest only through subprocess commands, manifests, and artifacts.

### `packages/trading_assistant_data`

The data package owns:

- `src/trading_assistant_data/`
- `data/`
- `docs/`
- `tests/`

Allowed dependencies:

- Standard library and declared third-party dependencies.
- No runtime imports from `trading_assistant` or `trading_assistant_backtest`.
- Publishes data bundle manifests and compatibility exports.

### `packages/trading_assistant_backtest`

The backtest package owns:

- `src/trading_assistant_backtest/`
- `backtests/` compatibility runner while the control plane still needs it.
- `contracts/`
- `artifacts/`
- `tests/`

Allowed dependencies:

- Standard library and declared third-party dependencies.
- No runtime imports from `trading_assistant` or `trading_assistant_data`.
- Reads control-plane manifests and data bundle manifests as files.

## Migration Strategy

Use a staged migration:

1. Establish root monorepo governance.
2. Move data/backtest workspaces under `packages/` with minimal code changes.
3. Move the control-plane workspace under `packages/` without changing its namespace.
4. Migrate the control-plane namespace to `trading_assistant.*`.
5. Remove temporary shims and update docs/CI.
6. Run full validation and freeze the final structure.

The control-plane namespace migration is intentionally isolated because it is the highest
risk part of the change.

## Phase 0: Pre-Migration Safety

Purpose: make the current state recoverable before moving files.

Checklist:

- [ ] 0.1 Record `git status --short --branch` for `trading_assistant`.
- [ ] 0.2 Record `git status --short --branch` for `trading_assistant_data`.
- [ ] 0.3 Record the absence or presence of `.git` under `trading_assistant_backtest`.
- [ ] 0.4 Record whether root `trading_assistant_agent` will become a git repo before
      the move.
- [ ] 0.5 Decide whether root history should be created with `git init`, `git subtree`,
      or historyless file moves.
- [ ] 0.6 If preserving nested repo history, create git bundles or subtree imports for
      `trading_assistant` and `trading_assistant_data`.
- [ ] 0.7 If not preserving nested repo history, explicitly document that decision in a
      new ADR.
- [ ] 0.8 Ensure no untracked generated caches are included in the migration plan:
      `.pytest_cache/`, `.ruff_cache/`, `__pycache__/`.
- [ ] 0.9 Inventory checkout-time import shims:
      `rg -n "checkout shim|Source-tree convenience|sys.path.insert|__path__"`.
- [ ] 0.10 Inventory hardcoded workspace paths:
      `rg -n "trading_assistant_data|trading_assistant_backtest|trading_backtests|BACKTEST_REPO_PATH|MARKET_DATA_ROOT"`.
- [ ] 0.11 Inventory `Path(__file__)` package-root assumptions:
      `rg -n "Path\\(__file__\\)|parents\\[|parent\\.parent"`.
- [ ] 0.12 Save baseline output for:
      `python tools/check_workspace_structure.py --layout current`.
- [ ] 0.13 Save expected failing output for:
      `python tools/check_workspace_structure.py --layout final`.
- [ ] 0.14 Save baseline help output for:
      `python -m trading_assistant_data --help`.
- [ ] 0.15 Save baseline help output for:
      `python -m trading_assistant_backtest.monthly --help`.
- [ ] 0.16 Save baseline help output for:
      `python -m backtests.shared.monthly_repair --help`.
- [ ] 0.17 Run and save baseline focused tests for each workspace.
- [ ] 0.18 Decide whether large data changes in `trading_assistant_data/data/` must be
      committed, stashed, copied, or excluded before the move.
- [ ] 0.19 Create a migration branch or root checkpoint before file moves.

Exit criteria:

- The current state can be restored.
- Baseline commands are recorded.
- Dirty worktree ownership is understood.

## Phase 1: Root Monorepo Foundation

Purpose: make the root the coordination layer before moving packages.

Checklist:

- [ ] 1.1 Create or update root `README.md` to describe the final `packages/` layout.
- [ ] 1.2 Create root `packages/` directory.
- [ ] 1.3 Create or update root `.gitignore` to cover Python caches, local env files,
      generated run artifacts, and workspace-local virtual environments.
- [ ] 1.4 Create root `pyproject.toml` if using shared tooling.
- [ ] 1.5 Add root tooling config only for workspace orchestration, not package runtime
      metadata.
- [ ] 1.6 Keep `tools/check_workspace_structure.py --layout current` passing before any
      package move.
- [ ] 1.7 Keep `tools/check_workspace_structure.py --layout final` failing cleanly with
      actionable missing-path errors before the package move.
- [ ] 1.8 Keep cross-workspace import checks inside the structure guard unless the logic
      becomes large enough to split into `tools/check_no_cross_workspace_imports.py`.
- [ ] 1.9 Add documentation that root scripts must call package commands with explicit
      working directories.
- [ ] 1.10 Add a root command for `python tools/check_workspace_structure.py --layout either`.
- [ ] 1.11 Add a root test command script only after package-local tests still pass.
- [ ] 1.12 Commit or checkpoint the foundation before package moves.

Exit criteria:

- Root has a documented monorepo role.
- Existing package commands still work in the old locations.
- Structure guard can distinguish transitional and final layouts.

## Phase 2: Move `trading_assistant_data`

Purpose: move the lowest-risk `src` package first.

Target:

```text
packages/trading_assistant_data/
  pyproject.toml
  src/trading_assistant_data/
  tests/
  data/
  docs/
```

Checklist:

- [ ] 2.1 Move `trading_assistant_data/` to `packages/trading_assistant_data/`.
- [ ] 2.2 Preserve `src/trading_assistant_data/` exactly.
- [ ] 2.3 Preserve `data/` exactly unless `.gitignore` explicitly classifies generated
      files.
- [ ] 2.4 Preserve `tests/`, `docs/`, `.env.example`, `.gitattributes`, and README.
- [ ] 2.5 Add an explicit `[build-system]` to `packages/trading_assistant_data/pyproject.toml`
      if it is still absent.
- [ ] 2.6 Decide whether package assets under
      `src/trading_assistant_data/requirements/*.yaml` are package data or
      repo-relative resources; encode that decision in packaging metadata or tests.
- [ ] 2.7 Remove or relocate the agent-root checkout shim after root-level command
      compatibility is replaced. The final preferred mechanism is editable install, not
      top-level root shims.
- [ ] 2.8 Update docs that reference `trading_assistant_data/...` to either:
      `packages/trading_assistant_data/...`, or a root variable such as
      `DATA_REPO_PATH=packages/trading_assistant_data`.
- [ ] 2.9 Update tests with hardcoded `agent_root / "trading_assistant_data"`.
- [ ] 2.10 Update default environment examples that point at the data repo.
- [ ] 2.11 Run `python -m pytest` from `packages/trading_assistant_data`.
- [ ] 2.12 Run `python -m trading_assistant_data --help` from
      `packages/trading_assistant_data`.
- [ ] 2.13 Run `python -m pip install -e .` from `packages/trading_assistant_data` in a
      clean environment or throwaway virtual environment.
- [ ] 2.14 Run the data CLI help command from outside the package root after editable
      install, to prove packaging rather than cwd behavior.
- [ ] 2.15 Run the data reproduction tests or smoke commands that do not require live
      credentials.
- [ ] 2.16 Confirm `packages/trading_assistant_data/src/trading_assistant_data/__init__.py`
      exists. Do not require the full final-layout guard to pass yet; the other
      workspaces have not moved.

Exit criteria:

- Data package imports from `src`.
- Data CLI works from its package root.
- No runtime file imports from sibling packages.
- Data path documentation is updated.

## Phase 3: Move `trading_assistant_backtest`

Purpose: move the backtest package and preserve compatibility runner behavior.

Target:

```text
packages/trading_assistant_backtest/
  pyproject.toml
  src/trading_assistant_backtest/
  backtests/
  tests/
  contracts/
  artifacts/
```

Checklist:

- [ ] 3.1 Move `trading_assistant_backtest/` to
      `packages/trading_assistant_backtest/`.
- [ ] 3.2 Preserve `src/trading_assistant_backtest/` exactly.
- [ ] 3.3 Preserve `backtests/` until the control plane no longer invokes
      `python -m backtests.shared.monthly_repair`.
- [ ] 3.4 Preserve `contracts/` and all bridge metadata paths.
- [ ] 3.5 Preserve `artifacts/` unless explicitly classified as generated.
- [ ] 3.6 Update `pyproject.toml` package list to include both
      `src/trading_assistant_backtest` and `backtests`.
- [ ] 3.7 Replace hardcoded validation matrix defaults for
      `trading_assistant_data/...` and `trading_assistant_backtest/artifacts/...` with
      helpers that resolve from `--agent-root` and support both current and final
      layouts during transition.
- [ ] 3.8 Replace backtest tests that compute `AGENT_ROOT / "trading_assistant_data"`
      or `AGENT_ROOT / "trading_assistant_backtest"` with a shared test helper.
- [ ] 3.9 Update tests with hardcoded `agent_root / "trading_assistant_backtest"`.
- [ ] 3.10 Update docs that reference `trading_assistant_backtest/...` to
      `packages/trading_assistant_backtest/...`, or a root variable such as
      `BACKTEST_REPO_PATH=packages/trading_assistant_backtest`.
- [ ] 3.11 Update deployment metadata installer docs to use the new contract path.
- [ ] 3.12 Run `python -m trading_assistant_backtest.monthly --help` from the backtest
      package root.
- [ ] 3.13 Run `python -m backtests.shared.monthly_repair --help` from the backtest
      package root.
- [ ] 3.14 Run `python -m pip install -e .` from `packages/trading_assistant_backtest`
      in a clean environment or throwaway virtual environment.
- [ ] 3.15 Run native and compatibility CLI help commands from outside the package root
      after editable install.
- [ ] 3.16 Run backtest unit tests.
- [ ] 3.17 Run approval-grade audit tests.
- [ ] 3.18 Confirm `packages/trading_assistant_backtest/src/trading_assistant_backtest/__init__.py`
      exists and `packages/trading_assistant_backtest/backtests/` still exists if the
      compatibility runner is still supported. Do not require the full final-layout
      guard to pass yet; the control workspace has not completed its namespace migration.

Exit criteria:

- Native backtest CLI works.
- Compatibility runner works.
- Contracts resolve under the new package path.
- Backtest tests pass.

## Phase 4: Move `trading_assistant` Without Namespace Change

Purpose: move the control-plane workspace under `packages/` while keeping existing
imports temporarily stable.

Transitional target:

```text
packages/trading_assistant/
  pyproject.toml
  analysis/
  comms/
  contracts/
  orchestrator/
  schemas/
  skills/
  tests/
  data/
  memory/
  scripts/
```

Checklist:

- [ ] 4.1 Move `trading_assistant/` to `packages/trading_assistant/`.
- [ ] 4.2 Preserve all root-level control-plane packages in their old relative shape.
- [ ] 4.3 Update root docs and scripts to call commands from
      `packages/trading_assistant`.
- [ ] 4.4 Update environment examples:
      old values such as `BACKTEST_REPO_PATH=../trading_backtests` must become paths
      that resolve from `packages/trading_assistant`, most likely
      `../trading_assistant_backtest` if both are siblings under `packages/`.
- [ ] 4.5 Update any absolute docs paths under `/opt/trading_assistant_agent/...`.
- [ ] 4.6 Update `.env.example` values for `BACKTEST_REPO_PATH`,
      `MARKET_DATA_ROOT`, `BACKTEST_ARTIFACT_ROOT`, and any contract paths.
- [ ] 4.7 Update tests with hardcoded `Path(__file__).parents[...]` assumptions only
      when they fail under the moved package.
- [ ] 4.8 Run focused control-plane tests.
- [ ] 4.9 Run the full control-plane test suite if practical.
- [ ] 4.10 Confirm monthly manifest generation still points to the moved data/backtest
      locations.
- [ ] 4.11 Confirm `orchestrator/config.py` still resolves `.env` at the package root.
- [ ] 4.12 Confirm `orchestrator/strategy_registry_loader.py` still resolves
      `data/strategy_profiles.yaml`.
- [ ] 4.13 Confirm startup scripts under `scripts/` still resolve package-local paths.

Exit criteria:

- The control plane works from `packages/trading_assistant`.
- Existing `from schemas...` style imports still work during this phase.
- Data/backtest invocation paths are correct.

## Phase 5: Control-Plane Namespace Migration

Purpose: convert the control plane to standard `src/trading_assistant/` layout.

Target:

```text
packages/trading_assistant/
  pyproject.toml
  src/trading_assistant/
    __init__.py
    analysis/
    comms/
    contracts/
    orchestrator/
    schemas/
    skills/
  tests/
  data/
  memory/
  scripts/
```

Checklist:

- [ ] 5.1 Create `packages/trading_assistant/src/trading_assistant/`.
- [ ] 5.2 Move `analysis/` into `src/trading_assistant/analysis/`.
- [ ] 5.3 Move `comms/` into `src/trading_assistant/comms/`.
- [ ] 5.4 Move `contracts/` into `src/trading_assistant/contracts/`.
- [ ] 5.5 Move `orchestrator/` into `src/trading_assistant/orchestrator/`.
- [ ] 5.6 Move `schemas/` into `src/trading_assistant/schemas/`.
- [ ] 5.7 Move `skills/` into `src/trading_assistant/skills/`.
- [ ] 5.8 Keep `data/`, `memory/`, `scripts/`, `docs/`, and `tests/` at the package root
      unless there is a specific packaging reason to move them.
- [ ] 5.9 Update `pyproject.toml` package discovery to `where = ["src"]`.
- [ ] 5.10 Update console scripts, if any, to use `trading_assistant...` module paths.
- [ ] 5.11 Rewrite module-string entrypoints:
      `orchestrator.app:app` -> `trading_assistant.orchestrator.app:app`.
- [ ] 5.12 Rewrite startup process detection patterns that look for
      `orchestrator.app:app`.
- [ ] 5.13 Rewrite subprocess or scheduler command strings that invoke root-level
      control-plane modules.
- [ ] 5.14 Rewrite absolute imports:
      `from schemas.x` -> `from trading_assistant.schemas.x`.
- [ ] 5.15 Rewrite absolute imports:
      `import schemas.x` -> `import trading_assistant.schemas.x`.
- [ ] 5.16 Rewrite absolute imports:
      `from orchestrator.x` -> `from trading_assistant.orchestrator.x`.
- [ ] 5.17 Rewrite absolute imports:
      `from skills.x` -> `from trading_assistant.skills.x`.
- [ ] 5.18 Rewrite absolute imports:
      `from analysis.x` -> `from trading_assistant.analysis.x`.
- [ ] 5.19 Rewrite absolute imports:
      `from comms.x` -> `from trading_assistant.comms.x`.
- [ ] 5.20 Rewrite absolute imports:
      `from contracts.x` -> `from trading_assistant.contracts.x`.
- [ ] 5.21 Update test imports the same way.
- [ ] 5.22 Add temporary import compatibility shims only if needed to keep external
      callers working during one release window.
- [ ] 5.23 Update `Path(__file__).resolve().parent.parent` assumptions inside moved
      modules.
- [ ] 5.24 Introduce a central `trading_assistant.paths` helper for package root, repo
      root, data root, memory root, and docs root.
- [ ] 5.25 Replace repeated package-root calculations with the new path helper where
      they break under `src/`.
- [ ] 5.26 Update permission gate path patterns if they currently expect
      `skills/*` or `orchestrator/*`.
- [ ] 5.27 Decide whether permission gates should use logical paths
      `skills/foo.py` or physical paths `src/trading_assistant/skills/foo.py`.
- [ ] 5.28 Update `orchestrator/skills_registry.py`, `skills/repo_change_guard.py`,
      `orchestrator/permission_gates.py`, and their tests together so approval behavior
      is unchanged.
- [ ] 5.29 Update skills registry forbidden path tests accordingly.
- [ ] 5.30 Update docs references from `schemas/...` to
      `src/trading_assistant/schemas/...` only where they are physical file paths.
- [ ] 5.31 Keep user-facing logical references as `schemas/...` if they describe
      control-plane concepts rather than physical paths.
- [ ] 5.32 Run `rg "^(from|import) (schemas|orchestrator|skills|analysis|comms|contracts)(\\.| import|$)" src tests`.
      This must return no runtime imports after the namespace migration.
- [ ] 5.33 Run import smoke tests:
      `python -c "import trading_assistant.schemas.monthly_run_manifest"`.
- [ ] 5.34 Run import smoke tests:
      `python -c "import trading_assistant.orchestrator.config"`.
- [ ] 5.35 Run import smoke tests:
      `python -c "import trading_assistant.skills.monthly_validation_orchestrator"`.
- [ ] 5.36 Run all focused monthly tests.
- [ ] 5.37 Run all startup/config tests.
- [ ] 5.38 Run all permission gate and skills registry tests.
- [ ] 5.39 Run the full control-plane test suite.

Exit criteria:

- No runtime module imports the old root-level control-plane packages.
- `trading_assistant.*` imports work from an editable install.
- Tests pass without adding the package root itself to `PYTHONPATH`.

## Phase 6: Entrypoint and Invocation Cutover

Purpose: make all commands use the final paths.

Checklist:

- [ ] 6.1 Update root docs to install packages from:
      `packages/trading_assistant`,
      `packages/trading_assistant_data`,
      `packages/trading_assistant_backtest`.
- [ ] 6.2 Update `.env.example` files with final relative paths.
- [ ] 6.3 Update `BACKTEST_REPO_PATH` defaults or examples.
- [ ] 6.4 Update `MARKET_DATA_ROOT` examples if they point to the old data path.
- [ ] 6.5 Update `BACKTEST_ARTIFACT_ROOT` examples if they point to the old backtest
      path.
- [ ] 6.6 Update `MONTHLY_STRATEGY_PLUGIN_CONTRACT_PATH` examples if they point to old
      `trading_assistant_backtest/contracts/...` paths.
- [ ] 6.7 Update service files or deployment docs that reference the old workspace path.
- [ ] 6.8 Update compatibility commands in docs:
      `python -m backtests.shared.monthly_repair`.
- [ ] 6.9 Decide whether the compatibility runner remains supported after migration.
- [ ] 6.10 If it remains supported, keep packaging and tests for `backtests`.
- [ ] 6.11 If it is retired, update control-plane default command to
      `python -m trading_assistant_backtest.monthly`.
- [ ] 6.12 Run native monthly runner help command.
- [ ] 6.13 Run compatibility monthly runner help command if still supported.
- [ ] 6.14 Run data CLI help command.
- [ ] 6.15 Run one validate-only monthly manifest fixture.
- [ ] 6.16 Run one data bundle reproduction fixture.

Exit criteria:

- Every documented command works from the final layout.
- No default configuration points at removed top-level workspace paths.

## Phase 7: Remove Transitional Shims

Purpose: remove temporary compatibility surfaces once final imports and entrypoints pass.

Checklist:

- [ ] 7.1 Remove top-level package shims that only existed for the old sibling layout.
- [ ] 7.2 Remove `sys.path` mutations added solely for checkout-time compatibility.
- [ ] 7.3 Remove old root-level control-plane import aliases if they were added in
      Phase 5.
- [ ] 7.4 Remove or demote current-layout support in `tools/check_workspace_structure.py`
      after the final layout is fully adopted.
- [ ] 7.5 Update docs to say the final layout is the only supported checkout shape.
- [ ] 7.6 Run import-boundary guard.
- [ ] 7.7 Run full package test suites.

Exit criteria:

- The final layout works without compatibility shims.
- Structure guard fails if old sibling workspaces are recreated.

## Phase 8: CI and Developer Workflow

Purpose: make the final layout easy to maintain.

Checklist:

- [ ] 8.1 Add root command for structure guard.
- [ ] 8.2 Add root command for all package tests.
- [ ] 8.3 Add root command for focused monthly validation tests.
- [ ] 8.4 Add root command for data contract tests.
- [ ] 8.5 Add root command for backtest approval-grade audit tests.
- [ ] 8.6 Add CI job for `packages/trading_assistant`.
- [ ] 8.7 Add CI job for `packages/trading_assistant_data`.
- [ ] 8.8 Add CI job for `packages/trading_assistant_backtest`.
- [ ] 8.9 Add CI job for cross-workspace import boundary checks.
- [ ] 8.10 Add CI job for CLI entrypoint smoke tests.
- [ ] 8.11 Document local setup from a fresh checkout.
- [ ] 8.12 Document which generated paths are expected to be ignored.

Exit criteria:

- A fresh clone can install and test all three packages from `packages/`.
- CI enforces structure and entrypoints.

## Phase 9: Full Validation and Freeze

Purpose: prove the final structure preserves the system's capabilities.

Checklist:

- [ ] 9.1 Run `python tools/check_workspace_structure.py --layout final`.
- [ ] 9.2 Run all control-plane tests.
- [ ] 9.3 Run all data package tests.
- [ ] 9.4 Run all backtest package tests.
- [ ] 9.5 Run data CLI help.
- [ ] 9.6 Run backtest native CLI help.
- [ ] 9.7 Run backtest compatibility CLI help if still supported.
- [ ] 9.8 Run control-plane import smoke tests.
- [ ] 9.9 Run data import smoke tests.
- [ ] 9.10 Run backtest import smoke tests.
- [ ] 9.11 Run monthly runner contract conformance tests.
- [ ] 9.12 Run approval-grade audit tests.
- [ ] 9.13 Run data bundle reproduction tests or smoke fixture.
- [ ] 9.14 Run a manifest validate-only backtest fixture.
- [ ] 9.15 Confirm docs no longer instruct users to use removed top-level workspace
      paths.
- [ ] 9.16 Confirm root `README.md` and implementation docs agree on final paths.
- [ ] 9.17 Confirm no nested `.git` directories remain under `packages/` unless the
      repo intentionally uses submodules.
- [ ] 9.18 Mark this plan complete with the final command outputs.

Exit criteria:

- All acceptance matrix rows are green.
- The final layout is the only documented supported structure.

## Acceptance Matrix

| ID | Area | Acceptance Criterion | Verification | Required Result |
| --- | --- | --- | --- | --- |
| A1 | Root layout | Root contains `packages/`, `docs/`, `artifacts/`, and `README.md`. | `Get-ChildItem -Force` from root | Required directories exist. |
| A2 | Package layout | Data package lives at `packages/trading_assistant_data/src/trading_assistant_data`. | Structure guard | Pass. |
| A3 | Package layout | Backtest package lives at `packages/trading_assistant_backtest/src/trading_assistant_backtest`. | Structure guard | Pass. |
| A4 | Package layout | Control package lives at `packages/trading_assistant/src/trading_assistant`. | Structure guard | Pass. |
| A5 | Git hygiene | No accidental nested `.git` dirs remain under `packages/` unless explicitly submodules. | `Get-ChildItem -Force -Recurse -Directory -Filter .git packages` | Empty or documented submodules only. |
| A6 | Import boundary | Control plane does not import `trading_assistant_data` or `trading_assistant_backtest` at runtime. | Import-boundary guard | Pass. |
| A7 | Import boundary | Data package does not import `trading_assistant` or `trading_assistant_backtest`. | Import-boundary guard | Pass. |
| A8 | Import boundary | Backtest package does not import `trading_assistant` or `trading_assistant_data`. | Import-boundary guard | Pass. |
| A9 | Control imports | `trading_assistant.schemas.monthly_run_manifest` imports from editable install. | `python -c "import trading_assistant.schemas.monthly_run_manifest"` | Exit code 0. |
| A10 | Control imports | `trading_assistant.orchestrator.config` imports from editable install. | `python -c "import trading_assistant.orchestrator.config"` | Exit code 0. |
| A11 | Control imports | `trading_assistant.skills.monthly_validation_orchestrator` imports from editable install. | `python -c "import trading_assistant.skills.monthly_validation_orchestrator"` | Exit code 0. |
| A12 | Data imports | `trading_assistant_data.cli` imports from editable install. | `python -c "import trading_assistant_data.cli"` | Exit code 0. |
| A13 | Backtest imports | `trading_assistant_backtest.monthly` imports from editable install. | `python -c "import trading_assistant_backtest.monthly"` | Exit code 0. |
| A14 | Data CLI | Data CLI help works from package root. | `python -m trading_assistant_data --help` | Exit code 0. |
| A15 | Backtest CLI | Native backtest CLI help works from package root. | `python -m trading_assistant_backtest.monthly --help` | Exit code 0. |
| A16 | Compatibility CLI | Compatibility monthly runner help works if still supported. | `python -m backtests.shared.monthly_repair --help` | Exit code 0 or documented retired. |
| A17 | Control tests | Focused monthly optimizer tests pass. | `python -m pytest tests/test_monthly_optimizer_runner.py tests/test_monthly_runner_contract_conformance.py -q` | Pass. |
| A18 | Data tests | Data contract tests pass. | `python -m pytest tests/test_contracts.py -q` | Pass. |
| A19 | Backtest tests | Monthly runner CLI tests pass. | `python -m pytest tests/unit/test_monthly_runner.py -q` | Pass. |
| A20 | Backtest tests | Approval-grade audit tests pass. | `python -m pytest tests/unit/test_approval_grade_audit.py -q` | Pass. |
| A21 | Manifests | Monthly manifest paths resolve to final data/backtest locations. | Monthly manifest fixture or unit test | Paths exist and validate. |
| A22 | Data bundles | Data bundle reproduction works from final package path. | Data reproduction fixture | Pass. |
| A23 | Backtest artifacts | Backtest artifact index validation still passes. | Monthly runner contract tests | Pass. |
| A24 | Deployment metadata | Deployment metadata validation uses manifest/artifact files, not backtest imports from control. | Import-boundary guard plus monthly tests | Pass. |
| A25 | Config | `.env.example` path examples match final layout. | Manual doc/config review | No old top-level workspace paths. |
| A26 | Docs | Root README documents final `packages/` layout. | Manual doc review | Accurate. |
| A27 | Docs | Implementation docs no longer contradict final layout. | `rg "trading_assistant_data|trading_assistant_backtest|trading_assistant/" docs README.md` | Only intentional references remain. |
| A28 | Packaging | Each package builds or imports from declared package discovery. | `python -m pip install -e .` per package | Exit code 0. |
| A29 | CI | CI or local root command runs structure guard and package tests. | CI config or root script | Present and documented. |
| A30 | Cleanup | Temporary shims are removed or explicitly documented as supported compatibility. | Structure guard plus docs | Pass. |
| A31 | Guardrails | Current layout guard passes before migration and final guard fails cleanly before migration. | `python tools/check_workspace_structure.py --layout current`; `python tools/check_workspace_structure.py --layout final` | Current passes; final emits actionable missing-path errors. |
| A32 | Guardrails | Final layout guard passes after migration. | `python tools/check_workspace_structure.py --layout final` | Pass. |
| A33 | Namespace | No old root-level control-plane imports remain after Phase 5. | `rg "^(from|import) (schemas|orchestrator|skills|analysis|comms|contracts)(\\.| import|$)" packages/trading_assistant/src packages/trading_assistant/tests` | No matches except documented compatibility shims. |
| A34 | Entrypoints | Uvicorn/module strings use `trading_assistant.orchestrator.app:app` after namespace migration. | `rg "orchestrator\\.app:app|trading_assistant\\.orchestrator\\.app:app" packages/trading_assistant` | Only final names remain. |
| A35 | Path resolution | Backtest validation matrix resolves data/backtest paths in final layout. | Validation matrix unit tests and `--agent-root` smoke run | Pass. |
| A36 | Package data | Data package resource files are either packaged or explicitly loaded as repo resources. | Editable-install smoke plus package-data/resource test | Pass. |
| A37 | Policy paths | Permission gates preserve behavior after physical files move under `src/`. | Permission gate, PR review, repo change guard, and skills registry tests | Pass. |
| A38 | Environment | `.env.example` no longer contains obsolete `../trading_backtests` defaults, and any data/backtest paths resolve from the final package root. | `rg "trading_backtests|BACKTEST_REPO_PATH|MARKET_DATA_ROOT|BACKTEST_ARTIFACT_ROOT" packages/trading_assistant/.env.example` | No `trading_backtests`; remaining paths are final-layout paths. |

## Risk Register

| Risk | Impact | Mitigation | Acceptance Link |
| --- | --- | --- | --- |
| Dirty nested repos are moved without preserving user work. | Data loss or confusing diffs. | Phase 0 status capture, bundle/subtree decision, checkpoint before moves. | A5 |
| Control namespace rewrite misses imports. | Runtime import failures. | Mechanical rewrite plus import smoke tests and full tests. | A9-A11, A17 |
| `Path(__file__)` assumptions break under `src/`. | Config/data/memory paths resolve incorrectly. | Add path helper and targeted config/startup tests. | A21, A25 |
| Permission gate path patterns become stale. | Approval policy weakens or blocks too much. | Decide logical vs physical paths and update tests. | A17, A24 |
| Backtest compatibility runner is dropped too early. | Monthly invocation breaks. | Keep `backtests` package until control default command is changed and tested. | A16 |
| Docs and deployment examples point to old paths. | Operator follows stale instructions. | Docs grep and implementation doc review. | A25-A27 |
| Cross-workspace direct imports creep back in. | Boundary weakens. | Structure/import guard in CI. | A6-A8, A29 |
| Data artifacts are accidentally changed by the move. | Data authority checks fail. | Preserve data files and run reproduction tests. | A18, A22 |
| Package-root execution hides missing install metadata. | Editable install fails after apparent local success. | Run help/import tests from outside package roots after `pip install -e .`. | A12-A16, A28 |
| Validation matrix keeps old sibling path constants. | Approval/readiness reports look in removed paths. | Refactor defaults through layout-aware path helpers and test them. | A21, A35 |
| Module-string entrypoints keep old package names. | Startup scripts and process detection fail after namespace migration. | Rewrite and test `orchestrator.app:app` command strings. | A34 |
| Package-data assets are omitted from wheels. | Installed CLI cannot find YAML requirements or resources. | Add package-data/resource tests or keep assets explicitly repo-relative. | A36 |

## Recommended Implementation Order

Do not start with the control-plane namespace migration. The safest order is:

1. Phase 0: snapshot and baseline.
2. Phase 1: root foundation.
3. Phase 2: move data.
4. Phase 3: move backtest.
5. Phase 4: move control plane without namespace change.
6. Phase 5: migrate control namespace.
7. Phase 6: cut over entrypoints and docs.
8. Phase 7: remove shims.
9. Phase 8: CI and developer workflow.
10. Phase 9: full validation and freeze.

## Final Completion Definition

This migration is complete when all of the following are true:

- [ ] The final `packages/` layout exists.
- [ ] All three packages install in editable mode.
- [ ] All package-local tests pass.
- [ ] Structure and import-boundary guards pass.
- [ ] Monthly manifest validation still works.
- [ ] Data bundle reproduction still works.
- [ ] Backtest artifact validation still works.
- [ ] Approval-grade audit tests still pass.
- [ ] Docs and `.env.example` files reference final paths.
- [ ] Temporary shims are removed or explicitly documented as supported compatibility.
- [ ] No old top-level workspace paths are required for normal operation.
- [ ] `python tools/check_workspace_structure.py --layout final` passes.
- [ ] Old root-level control-plane imports are absent except for explicitly documented
      compatibility shims.
