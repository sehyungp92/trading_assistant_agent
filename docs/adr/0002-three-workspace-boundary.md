# ADR 0002: Three Workspace Boundary

## Status

Accepted.

## Context

The trading assistant system is a control/data/backtest architecture. The control plane
freezes manifests and gates approval; the data product produces authoritative market-data
bundles; the backtest lab produces replay, parity, and optimizer evidence. The target
state described by the workflow and learning-loop docs depends on those roles staying
separate.

Flattening the system into one root `src/` tree would make imports convenient, but it
would also make the package boundary look weaker than the runtime boundary. The system's
most important contract is not a Python import contract; it is the manifest and artifact
handoff between separately runnable workspaces.

The current checkout has those workspaces as root-level sibling directories. The final
monorepo target moves them under `packages/` while preserving the same sibling
relationship inside that directory.

## Decision

Keep `trading_assistant`, `trading_assistant_data`, and `trading_assistant_backtest` as
sibling workspaces. The final target location is:

```text
packages/trading_assistant/
packages/trading_assistant_data/
packages/trading_assistant_backtest/
```

Use `src/` layout inside independently packaged workspaces where it is already safe:

```text
trading_assistant_data/src/trading_assistant_data/
trading_assistant_backtest/src/trading_assistant_backtest/
```

Preserve the control plane's existing root-level import packages until a dedicated
namespace migration rewrites imports and path-resolution assumptions together.

Add lightweight guardrails so the workspaces do not start importing each other's runtime
internals. Cross-workspace handoffs should stay manifest-driven.

## Consequences

During the transition, the layout remains slightly mixed internally, but the
architectural boundary is explicit and stable. The data and backtest workspaces can
remain independently installable and versionable. The control-plane namespace can be
migrated later without coupling that risk to the initial boundary cleanup.
