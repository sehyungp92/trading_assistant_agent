# Monthly Optimizer Workflow

The runner contract is intentionally simple:

1. `trading_assistant` writes `run_manifest.json`.
2. `trading_assistant_backtest` loads the manifest, resolves paths under `artifact_root`,
   and validates any authoritative `DataBundleManifest`.
3. The runner emits incumbent replay diagnostics for every mode.
4. Optimizer modes additionally emit a two-fold purged fold manifest, deterministic
   experiment plan, gate reports, candidate workspace manifest, attempt ledger, runner
   observability, confirmatory rerank, and rounds manifest.
5. Candidate adoption is fail-closed. A strategy plugin must provide replay-backed
   evidence, terminal successful attempts, gate artifacts, and decision parity before
   `selected_candidates.json` may contain an adopted candidate.
6. The control plane re-validates the artifact index, strategy contract maturity,
   deployment metadata evidence, and decision parity before routing model review/approval.

The latest completed month is always treated as selection-OOS evidence. It is not used as
an in-sample fold for phased-auto scoring.

## Strategy Parity Bridge

Structural candidates are trusted only after a plugin proves parity with the production
strategy at the deployed commit/config. The runner supports the bridge in three pieces:

1. Optional `deployment_metadata_path` on the manifest can point at read-only deployment
   facts emitted by a live bot or VPS.
2. `strategies.live_clone.LiveRepoCloneManager` prepares a local clean checkout at that
   pinned commit.
3. `replay.parity.decision_parity_report_from_traces` compares normalized live decision
   events with backtest adapter events across signals, filters, entries, exits, stops,
   sizing, risk caps, and order intent.

If deployment metadata is missing a repo URL, deployed commit, config hash,
strategy version, config version, telemetry schema version, contract artifact path,
or contract artifact hash, the bridge is invalid. If a live checkout is dirty or at
the wrong commit, the bridge is invalid. If any decision dimension is missing or
mismatched, the parity report is not approval-ready.

The first persisted shadow bridge is `contracts/crypto_trend_v1/`. It contains a
`shadow_validated` strategy plugin contract, a deployment metadata snapshot with the
pinned live commit/config hash, and parity fixtures for entries, blocked trades, exits,
stops, sizing/risk caps, and long/short order intent. It is intentionally not
`approval_ready`: the live VPS must publish the same metadata shape from the actual
runtime, fixture coverage must continue to expand from real production cases, and a
replay-backed evaluator must score candidates before structural changes can be trusted.

Run the formal bridge validation with:

```powershell
python -m trading_assistant_backtest.validation.decision_parity_run --artifact-root artifacts\validation\crypto_trend_v1\decision_parity
```

The run emits `decision_parity_report.json` and
`decision_parity_validation_summary.json`, and it must keep the plugin
`shadow_validated` rather than `approval_ready`.

Run the broader live-repo bridge readiness audit with:

```powershell
python -m trading_assistant_backtest.validation.bridge_readiness --artifact-root artifacts\validation\bridge_readiness
```

This audit inventories the formal crypto bridge plus the existing `_references/trading`
and `_references/k_stock_trader` parity surfaces. It is not a promotion step: those
non-crypto surfaces remain diagnostic until this repo has formal strategy plugin
contracts, normalized decision-trace adapters, VPS-emitted deployment metadata, and
durable decision parity reports for them.
