# ADR 0003: Root Monorepo Git Ownership

Date: 2026-06-04

Status: Accepted

## Context

The `trading_assistant_agent` workspace is the coordination root for the control,
data, and backtest workspaces, but before this decision it was not itself a Git
repository. The `trading_assistant` and `trading_assistant_data` folders were nested
Git repositories, while `trading_assistant_backtest` was already an ordinary sibling
workspace in this checkout.

The final package-structure plan expects a true monorepo: one parent Git repository
with no accidental nested `.git` directories under the package workspaces.

Update: the package-path migration has completed, and normal development now uses
`packages/trading_assistant`, `packages/trading_assistant_data`, and
`packages/trading_assistant_backtest`.

## Decision

Make `trading_assistant_agent` the owning Git repository. Preserve the existing
committed histories of the nested `trading_assistant` and `trading_assistant_data`
repositories with subtree imports, then capture the current working-tree snapshot in
the parent repository.

Keep the current sibling workspace layout for this Git conversion checkpoint. The
move into `packages/` and the control-plane namespace migration remain separate
planned phases.

Keep local copies of the old nested Git directories under `.monorepo-git-backups/`
for recovery. That backup path is ignored and is not part of the monorepo history.

Use Git LFS for data-like binary formats at the root so future package moves do not
accidentally turn large market-data files into normal Git blobs.

## Consequences

The parent repo can be pushed to GitHub as a true monorepo without submodules. The old
nested repos can still be recovered locally from `.monorepo-git-backups/` if needed,
but normal development should happen from the parent repository after this conversion.

The package-path migration remains reversible and independently testable because it
will start from a parent-repo checkpoint instead of from nested repositories.
