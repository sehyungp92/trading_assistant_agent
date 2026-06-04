# Trading Assistant Agent Workspace

This checkout is a monorepo for the trading-assistant system. The important invariant
is three strict runtime boundaries:

```text
trading_assistant_agent/
  README.md
  docs/
  tools/
  artifacts/
  packages/
    trading_assistant/           # control-plane workspace
    trading_assistant_data/      # data-product workspace
    trading_assistant_backtest/  # replay-lab workspace
  _references/                   # local external strategy references, ignored
```

The package workspaces live under `packages/` and communicate through frozen JSON
manifests, contracts, and artifact directories, not by importing each other in-process:

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

See `docs/2026-06-04-final-monorepo-package-structure-implementation-plan.md` for the
staged migration plan.

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

## Package Layout

All runtime packages use standard package-local metadata. The control plane is the
application coordinator; data and backtest remain separate installable packages:

```text
packages/trading_assistant/src/trading_assistant/
packages/trading_assistant_data/src/trading_assistant_data/
packages/trading_assistant_backtest/src/trading_assistant_backtest/
```

The root owns documentation, coordination scripts, and guardrails. Root scripts should
call package commands with explicit working directories; they should not rely on the
process current directory accidentally making a package importable.

## Fresh Checkout Setup

From the repository root, create one virtual environment and install all three
packages from `packages/`:

```bash
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ./packages/trading_assistant_data
python -m pip install -e ./packages/trading_assistant_backtest
python -m pip install -e "./packages/trading_assistant[dev,notifications]"
```

Local external strategy checkouts belong under `_references/`. Runtime outputs are
package-local: `packages/trading_assistant/runs/`, `packages/trading_assistant/logs/`,
`packages/trading_assistant/memory/findings/`,
`packages/trading_assistant_data/data/validation_reports/`, and
`packages/trading_assistant_backtest/artifacts/`. These paths are either ignored or
treated as generated evidence, not as additional package roots.

## Useful Checks

Run the structure guard from this directory:

```bash
python tools/check_workspace_structure.py --layout final
python tools/run_workspace_checks.py structure --layout final
```

Run each workspace's own tests from its workspace root:

```bash
cd packages/trading_assistant && python -m pytest
cd ../trading_assistant_data && python -m pytest
cd ../trading_assistant_backtest && python -m pytest
```

Root-level orchestration commands are available for the acceptance suites:

```bash
python tools/run_workspace_checks.py monthly-focused
python tools/run_workspace_checks.py data-contracts
python tools/run_workspace_checks.py backtest-monthly
python tools/run_workspace_checks.py backtest-approval
python tools/run_workspace_checks.py cli-smoke
python tools/run_workspace_checks.py imports
python tools/run_workspace_checks.py all-tests
```
