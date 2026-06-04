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

The checkout has those workspaces as sibling package directories under `packages/`.

## Decision

Keep `trading_assistant`, `trading_assistant_data`, and `trading_assistant_backtest` as
sibling workspaces. The final target location is:

```text
packages/trading_assistant/
packages/trading_assistant_data/
packages/trading_assistant_backtest/
```

Use `src/` layout inside independently packaged workspaces:

```text
packages/trading_assistant/src/trading_assistant/
packages/trading_assistant_data/src/trading_assistant_data/
packages/trading_assistant_backtest/src/trading_assistant_backtest/
```

The control plane imports through the `trading_assistant.*` namespace; the old
root-level control-plane imports are not supported.

Add lightweight guardrails so the workspaces do not start importing each other's runtime
internals. Cross-workspace handoffs should stay manifest-driven.

## Consequences

The architectural boundary is explicit and stable. All three workspaces are
independently installable and versionable, while cross-workspace behavior remains
manifest-driven instead of import-driven.
