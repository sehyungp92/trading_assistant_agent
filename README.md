# Trading Assistant Agent Workspace

This checkout is a multi-workspace trading-assistant system. The important invariant is
three strict runtime boundaries:

```text
trading_assistant_agent/
  trading_assistant/           # current control-plane workspace
  trading_assistant_data/      # current data-product workspace
  trading_assistant_backtest/  # current replay-lab workspace
  docs/
  artifacts/
  _references/
```

The current root-level sibling shape is transitional. The final monorepo target moves
those three workspaces under `packages/` while preserving the same boundaries:

```text
trading_assistant_agent/
  packages/
    trading_assistant/
      src/trading_assistant/
    trading_assistant_data/
      src/trading_assistant_data/
    trading_assistant_backtest/
      src/trading_assistant_backtest/
```

See
`docs/2026-06-04-final-monorepo-package-structure-implementation-plan.md`
for the staged migration plan. The packages should communicate through frozen JSON
manifests, contracts, and artifact directories, not by importing each other in-process.

## Workspace Roles

`trading_assistant` owns the control plane. It schedules daily, weekly, and monthly
workflows; builds frozen manifests; validates artifacts; maintains memory/ledgers; and
routes human approvals. It may invoke the data and backtest workspaces as tools, but it
should not depend on their Python internals.

`trading_assistant_data` owns canonical market data. It builds checksum-stamped bundles,
calendars, source imports, slice manifests, and data-reproduction reports. It does not
own strategy decisions, replay logic, approvals, or deployment state.

`trading_assistant_backtest` owns replay and optimizer evidence. It consumes frozen
manifests and data bundles, emits retained artifacts and parity evidence, and remains
fail-closed until contract maturity and approval gates hold. It does not approve, deploy,
or place orders.

## Current Packaging Shape

The data and backtest workspaces use standard `src/` layout:

```text
trading_assistant_data/src/trading_assistant_data/
trading_assistant_backtest/src/trading_assistant_backtest/
```

The control-plane workspace currently keeps its established root-level import packages
such as `orchestrator`, `schemas`, `skills`, `analysis`, `comms`, and `contracts`.
Changing that to `src/trading_assistant/...` would require a coordinated namespace and
path-resolution migration. The final plan schedules that as a separate phase after the
lower-risk data and backtest moves.

## Useful Checks

Run the structure guard from this directory:

```bash
python tools/check_workspace_structure.py --layout current
```

Run each workspace's own tests from its workspace root:

```bash
cd trading_assistant && python -m pytest
cd ../trading_assistant_data && python -m pytest
cd ../trading_assistant_backtest && python -m pytest
```
