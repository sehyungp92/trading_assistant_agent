# Trading Assistant Data Repo Implementation Plan

Date: 2026-05-30

Target repo: `trading_assistant_data`

Purpose: create the canonical, versioned, reproducible market-data repository consumed by
`trading_assistant` and, later, `trading_assistant_backtest`.

## Executive Decision

Build `trading_assistant_data` as the authoritative data product repo, not as a backtest
or strategy repo. It should own raw-source imports, canonical parquet normalization,
coverage manifests, checksums, calendars, fees/slippage model references, adjustment
policies, and monthly bundle manifests.

Do port data ingestion and cleaning code where it is genuinely data-owned. Do not port
strategy engines, optimizers, OMS order code, approval logic, or backtest runners.

The repo must make this contract true:

```text
trading_assistant writes MonthlyRunManifest
  -> manifest points to DataBundleManifest in trading_assistant_data
  -> trading_assistant_backtest reads only the manifest and bundle
  -> backtest artifacts echo the same data bundle checksum
  -> trading_assistant validates before model review or approval routing
```

## Boundaries

`trading_assistant_data` owns:

- Canonical market-data files and derived market-data panels.
- Raw-source import snapshots from IBKR, Hyperliquid, KIS/KRX, LRS SQLite, and macro/regime sources.
- Deterministic normalization from raw inputs to canonical parquet.
- Per-slice `MarketDataManifest` JSON.
- Repo-level `DataBundleManifest` JSON for monthly optimization.
- File checksums and bundle checksums.
- Trading calendars and session definitions.
- Futures roll and adjustment policies.
- Fee, funding, and slippage model reference files.
- Conformance tests proving it can emit manifests compatible with `trading_assistant`.

It must not own:

- Strategy decision logic.
- Backtest execution engines.
- Phased-auto, OOS repair, or confirmatory rerank logic.
- Live order routing, order placement, or OMS state mutation.
- Approval packets, candidate gates, or deployment state.

Cross-repo ownership model:

- `trading_assistant` owns the control plane: schedules, telemetry lineage,
  monthly manifest creation, search brief creation, runner invocation, artifact
  validation, model review, candidate gates, repair requests, approval routing,
  ledgers, operator status, and docs. It should not implement full backtest/search
  logic.
- `trading_assistant_data` owns only canonical market data, checksums, calendars,
  corporate action/adjustment policy, fee/slippage model references, and bundle
  manifests. It must not decide strategy candidates.
- `trading_assistant_backtest` owns reading `run_manifest.json`, loading the data
  bundle and strategy plugin, diagnostics, two-fold phased-auto, OOS repair,
  confirmatory rerank, replay/parity checks, candidate workspaces/attempts, and
  artifact-contract emission. It should not create approvals or mutate live
  deployment state.
- The live trading repo owns production strategy behavior, config schemas, emitted
  telemetry, and deployable strategy/config changes. Structural candidates must
  target this code or a shared strategy package used by this code; backtest-only
  behavior is never approval-ready.
- Key principle: the backtest repo may discover candidates; only
  `trading_assistant` may trust, gate, review, and route them.

## Current Contract Inputs From `trading_assistant`

The data repo must emit JSON compatible with these `trading_assistant` schemas:

- `schemas/market_data_manifest.py`
  - One slice: source, market, symbol, timeframe, start/end, expected bars, actual bars,
    coverage ratio, missing ranges, session calendar, timezone, checksum, source version,
    adjustment policy, fee model version, slippage model version, and authoritative flag.
- `schemas/data_bundle_manifest.py`
  - Monthly/repo bundle: data repo path/SHA, slice manifest list, bundle checksum, calendars,
    fee/slippage versions, adjustment policy, status, diagnostics-only reason.
- `schemas/monthly_run_manifest.py`
  - `data_bundle_manifest_path` and `data_bundle_checksum` must point to the bundle.
- `skills/backtest_runner_client.py` and `skills/monthly_optimizer_runner.py`
  - Optimizer runs fail closed unless bundle status is `authoritative`, checksums match,
    and emitted backtest coverage artifacts echo the same bundle checksum.

## Existing Consumer Constraints To Respect

The current `trading_assistant` code already has most of the contract spine, but it has
two important compatibility constraints that the data repo plan must satisfy.

1. `skills.market_data_sync.FileSystemParquetAdapter` reads monthly parquet from:

```text
<MARKET_DATA_ROOT>/<source>/<market>/<symbol>/<timeframe>/<YYYY-MM>.parquet
```

With the default catalog source, that means:

```text
<MARKET_DATA_ROOT>/filesystem/<market>/<symbol>/<timeframe>/<YYYY-MM>.parquet
```

2. `skills.monthly_validation_orchestrator.MonthlyValidationRequest` currently accepts
   `market_data_manifest_path`, and the default monthly path is:

```text
<MARKET_DATA_ROOT>/manifests/<bot_id>/<strategy_id>/<YYYY-MM>.coverage_manifest.json
```

`MonthlyRunManifest` already supports `data_bundle_manifest_path` and
`data_bundle_checksum`, and the backtest/optimizer validators already prefer the bundle
path when it is present. The gap is the pre-run handoff into monthly validation, not the
runner contract itself.

Therefore, `trading_assistant_data` must treat the filesystem export as transport only.
The authority must come from data-owned manifests and bundle checksums. Before shadow
monthly runs, choose one of these two integration paths:

- Short-term compatibility: the data repo writes an authoritative single-slice
  `MarketDataManifest` at the default `manifests/<bot>/<strategy>/<month>` path when the
  current strategy/run truly has one market-data slice. That file must preserve checksum,
  calendar, fee/slippage, adjustment, and source-version metadata.
- Preferred long-term handoff: add `MonthlyValidationRequest.data_bundle_manifest_path`
  in `trading_assistant` and pass the data repo's `DataBundleManifest` directly, leaving
  `market_data_manifest_path` for incumbent/readiness checks.

Do not represent a multi-slice strategy as one synthetic aggregate
`MarketDataManifest`; the current schema is explicitly slice-level. Any monthly run
needing multiple symbols, markets, timeframes, funding, or derived panels should use the
direct bundle handoff before becoming approval-ready.

Do not rely on `MarketDataSyncJob` as currently written to create authoritative monthly
optimizer input unless it is first updated to preserve source checksums, calendars,
fee/slippage versions, adjustment policy, and source version from the data repo. Its
current generated coverage manifests are useful readiness diagnostics, but they can be
lossy for optimizer authority.

## Reference Repo Audit

### `_references/trading`

What exists:

- Top-level deferred futures research snapshot:
  - `_references/trading/data/raw/ES_1d.parquet`
  - `_references/trading/data/raw/ES_1h.parquet`
  - `_references/trading/data/raw/ES_1m.parquet`
  - `_references/trading/data/raw/ES_1m_bid_ask.parquet`
  - `_references/trading/data/raw/ES_4h.parquet`
  - `_references/trading/data/raw/ES_5m.parquet`
  - `_references/trading/data/raw/ES_daily.parquet`
  - `_references/trading/data/raw/NQ_1d.parquet`
  - `_references/trading/data/raw/NQ_1h.parquet`
  - `_references/trading/data/raw/NQ_1m.parquet`
  - `_references/trading/data/raw/NQ_1m_bid_ask.parquet`
  - `_references/trading/data/raw/NQ_4h.parquet`
  - `_references/trading/data/raw/NQ_5m.parquet`
  - `_references/trading/data/raw/NQ_daily.parquet`
- Futures/IBKR ingestion and quality helpers:
  - `_references/trading/backtests/shared/data/ibkr/bars.py`
  - `_references/trading/backtests/shared/data/ibkr/models.py`
  - `_references/trading/backtests/shared/data/ibkr/store.py`
  - `_references/trading/backtests/shared/data/ibkr/alignment.py`
  - `_references/trading/backtests/shared/data/ibkr/requirements.py`
  - `_references/trading/backtests/shared/data/ibkr/sync.py`
  - `_references/trading/backtests/shared/data/ibkr/ticks.py`
  - `_references/trading/backtests/shared/data/ibkr/pacing.py`
  - `_references/trading/backtests/shared/data/ibkr/stitch.py`
  - `_references/trading/libs/market_data/futures_roll.py`
  - `_references/trading/libs/market_data/panama.py`
- Strategy-family seed datasets:
  - `_references/trading/backtests/momentum/data/raw/`
    - `NQ_5m.parquet`, `ES_1d.parquet`, `NQ_daily_panama.csv`
  - `_references/trading/backtests/swing/data/raw/`
    - `QQQ`, `GLD`, `NQ`, `GC` across `15m`, `1h`, `1d` where present.
  - `_references/trading/backtests/stock/data/raw/`
    - 611 parquet files for US equity daily/5m/30m datasets.
  - `_references/trading/backtests/regime/data/raw/`
    - `macro_df.parquet`, `market_df.parquet`, `strat_ret_df.parquet`,
      `regime_seed_manifest.json`.

Port:

- Shared IBKR read-only historical downloader primitives.
- Futures roll/Panama stitching policy and tests.
- Cross-timeframe alignment checks.
- Store helpers for UTC index normalization, atomic parquet writes, merging,
  gap detection, and resampling.
- Family data requirements, but convert them into declarative YAML/JSON configs.

Do not port:

- Backtest engines under `backtests/*` except data ingestion modules.
- Strategy configs or optimizers as executable data-repo code.
- `data/relay.db`.
- `data/strategy-registry.json` as an authority. Use it only as a migration reference;
  the live trading repo remains the strategy-registry authority.

### `_references/crypto_trader`

What exists:

- Hyperliquid candle parquet:
  - `_references/crypto_trader/data/candles/BTC/{1m,5m,15m,30m,1h,4h,1d}.parquet`
  - `_references/crypto_trader/data/candles/ETH/{1m,5m,15m,30m,1h,4h,1d}.parquet`
  - `_references/crypto_trader/data/candles/SOL/{1m,5m,15m,30m,1h,4h,1d}.parquet`
- Hyperliquid funding parquet:
  - `_references/crypto_trader/data/funding/BTC.parquet`
  - `_references/crypto_trader/data/funding/ETH.parquet`
  - `_references/crypto_trader/data/funding/SOL.parquet`
- Timestamp/live parity helpers:
  - `_references/crypto_trader/src/crypto_trader/core/market_time.py`
  - `_references/crypto_trader/src/crypto_trader/live/feed.py`
  - `_references/crypto_trader/tests/parity/test_market_event_timestamps.py`
- Incremental refresh script:
  - `_references/crypto_trader/scripts/refresh_data.py`

Important caveat:

`refresh_data.py` imports `crypto_trader.data.downloader` and `crypto_trader.data.store`,
but those modules are not present in the inspected reference tree. Do not port the script
blindly. Recreate the missing downloader/store as first-class data repo code, then use the
script's behavior as a spec: coins `BTC`, `ETH`, `SOL`; intervals `1m`, `5m`, `15m`, `30m`,
`1h`, `4h`, `1d`; funding; incremental resume from last stored timestamp; gap detection.

Port:

- Timestamp policy and completed-candle semantics.
- Hyperliquid interval set and funding concept.
- Historical feed ordering assumptions as tests, not as strategy code.

Do not port:

- Strategy, optimizer, portfolio, relay, or live trading modules.

### `_references/k_stock_trader`

What exists:

- KRX daily/LRS parquet mirror:
  - `_references/k_stock_trader/data/krx_daily_parquet/manifest.json`
  - 103-symbol grouped daily OHLCV.
  - 103-symbol grouped daily flow.
  - 103-symbol daily foreign flow.
  - 103-symbol daily institutional flow.
  - 2 index OHLCV groups.
  - 7 table-level parquet files.
  - Manifest range: `2024-02-19` to `2026-05-12`.
- KIS intraday parquet:
  - `_references/k_stock_trader/data/kis_intraday_parquet/`
  - 685 parquet files.
  - 124 symbol directories.
  - Five timeframes: `1m`, `5m`, `15m`, `30m`, `1h`.
  - Some symbol/timeframe pairs have duplicate date-range files and must be merged/deduped.
- Daily export tooling:
  - `_references/k_stock_trader/scripts/export_lrs_to_parquet.py`
  - `_references/k_stock_trader/strategy_common/daily_lrs_parquet.py`
- Market-derived panels:
  - `_references/k_stock_trader/strategy_common/sector_daily.py`
  - `_references/k_stock_trader/strategy_common/sector_intraday.py`
  - `_references/k_stock_trader/strategy_common/sector_map.py`
- KIS read-only data methods live inside a broader client:
  - `_references/k_stock_trader/kis_core/kis_client.py`
  - Relevant methods include daily chart, minute chart, daily bars, minute bars,
    index daily, current price, orderbook, rankings, and condition search.
  - The same file also contains order methods and must not be ported wholesale.
- Calendar:
  - `_references/k_stock_trader/kis_core/trading_calendar.py`
  - It expects `kis_core/data/krx_holidays.yaml`, but that file is absent in the reference tree.

Port:

- LRS SQLite-to-parquet export, with tests.
- KRX daily and flow schema.
- Sector map normalization and sector daily/intraday panel builders as deterministic
  derived market-data transforms.
- Read-only KIS REST quotation/history methods only, extracted into a data-only client.
- Rate limiting and response parsing if needed for read-only KIS endpoints.

Do not port:

- OMS.
- Order placement/cancel/revise methods.
- Deployment runtime.
- Strategy artifact promotion scripts.
- Strategy engines.

## Initial Data Migration Plan

Create two layers: `imported/` for untouched reference snapshots, and `canonical/`
for normalized authoritative candidates.

### Repository Layout

```text
trading_assistant_data/
  README.md
  pyproject.toml
  .env.example
  .gitattributes
  src/trading_assistant_data/
    __init__.py
    cli.py
    checksums.py
    manifests.py
    validation.py
    bundle_builder.py
    calendars/
      __init__.py
      cme.py
      crypto.py
      krx.py
      us_equities.py
    sources/
      ibkr/
        bars.py
        contracts.py
        pacing.py
        store.py
        sync.py
        ticks.py
      hyperliquid/
        downloader.py
        store.py
        sync.py
      kis/
        auth.py
        read_only_client.py
        sync_daily.py
        sync_intraday.py
      lrs/
        export_daily.py
    transforms/
      futures_roll.py
      panama.py
      resample.py
      alignment.py
      krx_daily_lrs.py
      sector_daily.py
      sector_intraday.py
    requirements/
      cme_futures.yaml
      us_equities.yaml
      crypto_hyperliquid.yaml
      krx_equities.yaml
      macro_regime.yaml
  data/
    imported/
    canonical/
    manifests/
    bundles/
    calendars/
    cost_models/
    adjustments/
    validation_reports/
  tests/
```

### Storage Policy

Use Git LFS or DVC for parquet/csv/db artifacts. Do not commit large parquet files
through normal git blobs.

Authoritative monthly bundles must be reproducible by checking out the data repo commit
recorded in `DataBundleManifest.data_repo_commit_sha`. Do not mutate canonical files
referenced by an authoritative bundle after the bundle is written. If a source correction is
needed, write a new canonical partition, new slice manifest, and new bundle manifest. Mutable
`latest` exports are allowed only as generated compatibility outputs, never as authority.

Minimum `.gitattributes`:

```gitattributes
*.parquet filter=lfs diff=lfs merge=lfs -text
*.csv filter=lfs diff=lfs merge=lfs -text
*.db filter=lfs diff=lfs merge=lfs -text
data/imported/** filter=lfs diff=lfs merge=lfs -text
data/canonical/** filter=lfs diff=lfs merge=lfs -text
```

Keep JSON manifests, calendars, source requirements, tests, and docs in normal git.

## Exact Seed Copy Instructions

Copy reference files into `data/imported/reference_snapshot_2026-05-30/` first.
Only canonicalize after validation.

### US futures and US equities from `_references/trading`

Copy:

```text
_references/trading/data/raw/*.parquet
  -> data/imported/reference_snapshot_2026-05-30/trading/data/raw/

_references/trading/backtests/momentum/data/raw/*
  -> data/imported/reference_snapshot_2026-05-30/trading/backtests/momentum/data/raw/

_references/trading/backtests/swing/data/raw/*
  -> data/imported/reference_snapshot_2026-05-30/trading/backtests/swing/data/raw/

_references/trading/backtests/stock/data/raw/*.parquet
  -> data/imported/reference_snapshot_2026-05-30/trading/backtests/stock/data/raw/

_references/trading/backtests/regime/data/raw/*
  -> data/imported/reference_snapshot_2026-05-30/trading/backtests/regime/data/raw/
```

Do not copy:

```text
_references/trading/data/relay.db
```

Treat `data/strategy-registry.json` as a migration reference only:

```text
_references/trading/data/strategy-registry.json
  -> docs/reference_inputs/trading_strategy_registry_2026-05-30.json
```

### Crypto from `_references/crypto_trader`

Copy:

```text
_references/crypto_trader/data/candles/BTC/*.parquet
  -> data/imported/reference_snapshot_2026-05-30/crypto_trader/data/candles/BTC/

_references/crypto_trader/data/candles/ETH/*.parquet
  -> data/imported/reference_snapshot_2026-05-30/crypto_trader/data/candles/ETH/

_references/crypto_trader/data/candles/SOL/*.parquet
  -> data/imported/reference_snapshot_2026-05-30/crypto_trader/data/candles/SOL/

_references/crypto_trader/data/funding/*.parquet
  -> data/imported/reference_snapshot_2026-05-30/crypto_trader/data/funding/
```

Do not copy:

```text
_references/crypto_trader/output/
```

The `output/` tree contains optimizer/backtest outputs, not source market data.

### KRX/KIS from `_references/k_stock_trader`

Copy:

```text
_references/k_stock_trader/data/krx_daily_parquet/**
  -> data/imported/reference_snapshot_2026-05-30/k_stock_trader/data/krx_daily_parquet/

_references/k_stock_trader/data/kis_intraday_parquet/**
  -> data/imported/reference_snapshot_2026-05-30/k_stock_trader/data/kis_intraday_parquet/

_references/k_stock_trader/config/olr_kalcb/olr_deployment_universe_103.yaml
  -> docs/reference_inputs/olr_deployment_universe_103.yaml

_references/k_stock_trader/config/universe_103.yaml
  -> docs/reference_inputs/k_stock_universe_103.yaml
```

Do not copy:

```text
_references/k_stock_trader/data/live_readiness/
_references/k_stock_trader/data/strategy/
_references/k_stock_trader/data/paper_sessions/
```

Those are runtime/strategy artifacts, not canonical market data.

## Canonical Data Layout

Normalize imported files into this shape:

```text
data/canonical/
  bars/
    market=cme_futures/source=ibkr/kind=trades/symbol=NQ/timeframe=1m/year=2026/month=05/part.parquet
    market=cme_futures/source=ibkr/kind=bid_ask/symbol=NQ/timeframe=1m/year=2026/month=05/part.parquet
    market=us_equity/source=ibkr/kind=trades/symbol=QQQ/timeframe=15m/year=2026/month=05/part.parquet
    market=krx_equity/source=kis/kind=trades/symbol=000100/timeframe=1m/year=2026/month=05/part.parquet
    market=crypto_perp/source=hyperliquid/kind=trades/symbol=BTC/timeframe=1m/year=2026/month=05/part.parquet
  funding/
    market=crypto_perp/source=hyperliquid/symbol=BTC/year=2026/month=05/part.parquet
  daily_flow/
    market=krx_equity/source=lrs/symbol=000100/year=2026/part.parquet
  sector/
    market=krx_equity/source=lrs/model=sector_daily_v2/year=2026/part.parquet
    market=krx_equity/source=kis/model=sector_intraday_v2/year=2026/month=05/part.parquet
  regime/
    market=global_macro/source=seed/model=regime_seed_v1/part.parquet
```

Each canonical bar parquet must use these columns:

```text
timestamp_utc: datetime64[ns, UTC]
timestamp_exchange: string
symbol: string
market: string
source: string
timeframe: string
kind: string
open: float64
high: float64
low: float64
close: float64
volume: float64
bar_count: float64 optional
wap: float64 optional
is_rth: bool optional
source_file: string
source_row_hash: string
```

Crypto source files use integer millisecond `ts`; canonicalization must convert with
`unit="ms"` and treat it as UTC candle open time.

KRX intraday files need an explicit timestamp policy audit before they become
authoritative. The reference files have `timestamp` columns with KRX session times.
Canonicalization must preserve both:

```text
timestamp_exchange = Asia/Seoul local session timestamp
timestamp_utc = timestamp_exchange converted to UTC
```

Do not mark KRX intraday authoritative until this conversion is proven against at
least one known trading day and session close.

## Compatibility Export For `trading_assistant`

`trading_assistant.skills.market_data_sync.FileSystemParquetAdapter` currently expects:

```text
<MARKET_DATA_ROOT>/<source>/<market>/<symbol>/<timeframe>/<YYYY-MM>.parquet
```

So the data repo should also write a compatibility export:

```text
data/export/
  filesystem/cme_futures/NQ/1m/2026-05.parquet
  filesystem/cme_futures/NQ/5m/2026-05.parquet
  filesystem/us_equity/QQQ/15m/2026-05.parquet
  filesystem/crypto_perp/BTC/1m/2026-05.parquet
  filesystem/krx_equity/000100/1m/2026-05.parquet
  manifests/<bot_id>/<strategy_id>/2026-05.coverage_manifest.json
```

Set `MARKET_DATA_ROOT` in `trading_assistant` to:

```text
../trading_assistant_data/data/export
```

This compatibility export should be generated from canonical parquet, never edited
directly.

The `filesystem/...` parquet files satisfy the existing `FileSystemParquetAdapter`.
The `manifests/...coverage_manifest.json` file satisfies the current
`MonthlyValidationOrchestrator` pre-run gate for a single-slice run. For multi-slice
monthly optimization, use the preferred direct `DataBundleManifest` handoff instead of
collapsing multiple slices into one synthetic coverage manifest. Any compatibility
manifest should be generated from the same authoritative slice manifest that feeds the
bundle; it should not be the lossy composite currently produced by `MarketDataSyncJob`
unless that job is first updated to preserve all data authority metadata.

## Manifest Rules

For every canonical slice, write:

```text
data/manifests/slices/<source>/<market>/<symbol>/<timeframe>/<start>_<end>.market_data_manifest.json
```

Do not make consumer correctness depend on ad hoc extra fields inside
`MarketDataManifest`; the current schema does not define a `data_path` field. If the data
repo needs path lookup, emit a data-repo-local `slice_index.json` next to the bundle and
keep `MarketDataManifest` focused on coverage, checksum, provenance, and authority.

For monthly optimization, write:

```text
data/bundles/monthly/<YYYY-MM>/<bot_id>/<strategy_id>/data_bundle_manifest.json
data/bundles/monthly/<YYYY-MM>/<bot_id>/<strategy_id>/slice_index.json
```

Authoritative `MarketDataManifest` requirements:

- `checksum` is sha256 over canonical parquet content plus schema metadata.
- `session_calendar` is non-empty.
- `source_version` is the data repo commit SHA.
- `adjustment_policy` is non-empty.
- `fee_model_version` is non-empty.
- `slippage_model_version` is non-empty.
- `expected_bars` is computed from the declared calendar/session.
- `actual_bars / expected_bars >= required coverage threshold`.
- `missing_ranges` are explicit.
- `usable_for_authoritative_validation = true` only when all required fields pass.

Authoritative `DataBundleManifest` requirements:

- `data_repo_commit_sha` is populated.
- `bundle_checksum` is deterministic.
- Every slice manifest is authoritative.
- Calendars cover every included market.
- Fee/slippage/adjustment policy versions match the intended monthly runner.
- Status is `authoritative`.

If any condition fails, emit `diagnostics_only` or `blocked`, with a precise reason.

Single-slice compatibility `MarketDataManifest` requirements:

- It is written to `data/export/manifests/<bot_id>/<strategy_id>/<YYYY-MM>.coverage_manifest.json`
  for the current `trading_assistant` default path.
- It represents exactly one slice used by the monthly bundle.
- It carries a deterministic checksum and non-empty source version, session calendar,
  fee/slippage versions, and adjustment policy.
- It is marked authoritative only when the underlying bundle is authoritative.
- If multiple slices, markets, calendars, funding series, or derived panels are required,
  skip this shim and pass `DataBundleManifest` directly.

## Calendars

Create versioned calendar definitions:

```text
data/calendars/crypto_utc_24_7_v1.json
data/calendars/cme_equity_index_futures_v1.json
data/calendars/us_equities_xnys_xnas_v1.json
data/calendars/krx_equities_v1.json
```

Calendar definitions must include:

- Timezone.
- Session open/close.
- Breaks, if any.
- Weekday rules.
- Holiday source and generated-at timestamp.
- Version.
- Expected bar-count function tests.

KRX is the highest risk because the reference calendar silently falls back to
weekday-only when `krx_holidays.yaml` is missing. Add a real KRX holiday file
before marking KRX bundles authoritative.

## Cost, Funding, And Adjustment Policies

Create:

```text
data/cost_models/fees/fees_v1.json
data/cost_models/slippage/slippage_v1.json
data/cost_models/funding/hyperliquid_funding_v1.json
data/adjustments/cme_futures_panama_v1.json
data/adjustments/us_equity_split_adjusted_policy_v1.json
data/adjustments/krx_split_adjusted_policy_v1.json
data/adjustments/crypto_raw_perp_policy_v1.json
```

Minimum policy content:

- Source.
- Markets covered.
- Instruments covered.
- Version.
- Formula or external source.
- Effective date.
- Known limitations.

For CME futures, port the roll policy from:

```text
_references/trading/libs/market_data/futures_roll.py
_references/trading/libs/market_data/panama.py
```

Use it to describe and reproduce continuous contracts. Do not let a continuous
futures file become authoritative unless the roll schedule and Panama adjustment
checksum are part of the slice manifest.

## Ingestion And Cleaning Code To Port

### Port as data-owned modules

From `_references/trading`:

- `backtests/shared/data/ibkr/bars.py`
- `backtests/shared/data/ibkr/models.py`
- `backtests/shared/data/ibkr/store.py`
- `backtests/shared/data/ibkr/alignment.py`
- `backtests/shared/data/ibkr/pacing.py`
- `backtests/shared/data/ibkr/ticks.py`
- `backtests/shared/data/ibkr/stitch.py`
- `libs/market_data/futures_roll.py`
- `libs/market_data/panama.py`

Adaptation:

- Rename imports under `trading_assistant_data.sources.ibkr`.
- Remove backtest-family runtime dependencies.
- Convert output paths to canonical partitioned layout.
- Add manifest emission after every successful write.

From `_references/k_stock_trader`:

- `strategy_common/daily_lrs_parquet.py`
- `strategy_common/sector_map.py`
- `strategy_common/sector_daily.py`
- `strategy_common/sector_intraday.py`
- `kis_core/trading_calendar.py`
- Read-only portions of `kis_core/kis_client.py`.
- `kis_core/rate_budget.py` and `kis_core/kis_responses.py` if needed by read-only KIS sync.

Adaptation:

- Split read-only KIS endpoints from order endpoints.
- Add explicit no-order tests.
- Create `krx_holidays.yaml` from an authoritative source.
- Make intraday timestamp conversion explicit and tested.

From `_references/crypto_trader`:

- `src/crypto_trader/core/market_time.py`
- The behavior in `scripts/refresh_data.py`.

Adaptation:

- Rebuild missing `HyperliquidDownloader` and `ParquetStore`.
- Store candle timestamps as `timestamp_utc`.
- Preserve source integer `ts` as `source_ts_ms`.
- Emit funding manifests separately from candle manifests.

### Do not port as executable code

- `_references/crypto_trader/output/**`
- `_references/*/strategy*/**` except pure market-data transforms listed above.
- `_references/*/backtests/**/runner.py`
- `_references/*/optimize/**`
- `_references/k_stock_trader/oms/**`
- `_references/k_stock_trader/deployment/**`
- Any order placement, cancel, revise, or account mutation method.

## CLI Surface

Implement these commands:

```bash
python -m trading_assistant_data import-reference --snapshot 2026-05-30 --references-root ../trading_assistant/_references
python -m trading_assistant_data normalize --all
python -m trading_assistant_data sync ibkr --families momentum,swing,stock --years 2 --latest
python -m trading_assistant_data sync hyperliquid --symbols BTC,ETH,SOL --intervals 1m,5m,15m,30m,1h,4h,1d --funding
python -m trading_assistant_data sync kis --symbols-file data/requirements/krx_equities.yaml --daily --intraday
python -m trading_assistant_data validate-slice --manifest data/manifests/slices/...
python -m trading_assistant_data build-bundle --run-month 2026-05 --bot-id crypto_portfolio --strategy-id portfolio
python -m trading_assistant_data export-filesystem --run-month 2026-05
python -m trading_assistant_data export-single-slice-coverage --run-month 2026-05 --bot-id crypto_portfolio --strategy-id portfolio
python -m trading_assistant_data audit-coverage --run-month 2026-05
```

Every command must support:

- `--dry-run`
- `--json`
- non-zero exit on validation failure
- structured output written under `data/validation_reports/`

## Conformance Tests

Add tests that install or import the `trading_assistant` schemas and validate emitted JSON
against the current contracts.

Minimum tests:

- `test_market_data_manifest_authoritative_happy_path`
- `test_market_data_manifest_blocks_missing_checksum`
- `test_market_data_manifest_blocks_missing_calendar`
- `test_data_bundle_manifest_authoritative_happy_path`
- `test_data_bundle_manifest_diagnostics_only_when_any_slice_is_not_authoritative`
- `test_bundle_checksum_changes_when_any_slice_checksum_changes`
- `test_compatibility_export_matches_filesystem_adapter_layout`
- `test_single_slice_coverage_manifest_matches_monthly_default_path`
- `test_single_slice_coverage_manifest_preserves_authority_metadata`
- `test_multi_slice_bundle_does_not_emit_aggregate_market_data_manifest`
- `test_data_bundle_manifest_can_be_passed_directly_to_monthly_run_manifest`
- `test_crypto_ts_ms_converts_to_utc_open_time`
- `test_krx_timestamp_policy_requires_exchange_timezone`
- `test_kis_client_contains_no_order_methods`
- `test_ibkr_alignment_detects_derived_timeframe_mismatch`
- `test_duplicate_krx_intraday_files_are_merged_and_deduped`
- `test_missing_ranges_are_reported`
- `test_expected_bars_respect_calendar_holidays`
- `test_authoritative_bundle_requires_fee_slippage_and_adjustment_versions`

## Phase Plan

### Phase 0 - Repo Bootstrap

Deliverables:

- Create `trading_assistant_data` repo.
- Add Python package skeleton.
- Add Git LFS/DVC storage policy.
- Add README with boundary statement.
- Add dependency set: `pandas`, `pyarrow`, `pydantic`, `typer` or `argparse`, `pyyaml`,
  `requests`, `ib_async` optional extra, `hyperliquid-python-sdk` optional extra.
- Add CI for lint and tests.

Acceptance:

- `python -m trading_assistant_data --help` works.
- Tests run without data downloads.
- Repo README clearly says it is data-only and cannot place orders.

### Phase 1 - Contract Models And Validators

Deliverables:

- Implement local models or JSON-schema validators compatible with:
  - `MarketDataManifest`
  - `DataBundleManifest`
- Add checksum utilities.
- Add calendar expected-bar utilities.
- Add slice and bundle validators.

Acceptance:

- The data repo can emit a valid sample `MarketDataManifest`.
- The data repo can emit a valid sample `DataBundleManifest`.
- `trading_assistant` can load both without schema errors.

### Phase 2 - Import Reference Snapshots

Deliverables:

- Add `import-reference` command.
- Copy exact seed folders listed above into `data/imported/reference_snapshot_2026-05-30/`.
- Write import manifest with source repo path, source repo commit if available, file count,
  bytes, and sha256 per file.

Acceptance:

- Import is deterministic.
- Re-running import does not corrupt or duplicate outputs.
- Imported files remain raw and unmodified.

### Phase 3 - Canonical Normalization

Deliverables:

- Normalize US futures/IBKR bars.
- Normalize US equity bars.
- Normalize crypto candles and funding.
- Normalize KRX daily/flow/index data.
- Normalize KIS intraday bars.
- Emit canonical partitioned parquet.
- Emit per-slice manifests.

Acceptance:

- All canonical bar files have `timestamp_utc`, `symbol`, `market`, `source`,
  `timeframe`, `kind`, OHLCV, and provenance columns.
- Crypto timestamps are correctly parsed from source millisecond `ts`.
- KRX intraday timestamps include both exchange and UTC representations.
- Duplicate KRX intraday symbol/timeframe ranges are merged and deduped.

### Phase 4 - Calendar And Coverage Authority

Deliverables:

- Implement calendar files and expected bar-count logic.
- Create a real KRX holiday file.
- Add missing-range detection.
- Add coverage reports.

Acceptance:

- Authoritative status is impossible without a calendar.
- KRX cannot be authoritative while using weekday-only fallback.
- Coverage reports identify missing months/days/time ranges.

### Phase 5 - Bundle Builder

Deliverables:

- Implement `build-bundle`.
- Inputs:
  - run month
  - bot id
  - strategy id
  - symbol/timeframe requirements
  - in-sample start/end
  - OOS start/end
- Output:
  - `data_bundle_manifest.json`
  - `slice_index.json`
  - bundle coverage report
  - compatibility export for `trading_assistant`
  - single-slice compatibility `MarketDataManifest` for the current monthly default path,
    only when the bundle contains exactly one slice

Acceptance:

- Bundle status is `authoritative` only when every required slice is authoritative.
- Bundle checksum changes if any slice checksum changes.
- `trading_assistant.skills.monthly_validation_orchestrator` can consume either the
  generated single-slice manifest or, after the preferred integration change, the bundle
  path directly without downgrading it to diagnostics-only.
- Multi-slice bundles require the direct bundle handoff before they can be approval-ready.

### Phase 6 - Live Refresh

Deliverables:

- Implement source-specific sync:
  - IBKR for CME futures and US equities.
  - Hyperliquid for crypto candles and funding.
  - KIS for KRX intraday.
  - KRX daily refresh from the production-approved upstream pull path, with LRS kept as a local SQLite/parquet research-data input rather than a live refresh adapter.
- Add append mode with overlap repair.
- Add stale-data reports.

Acceptance:

- Refresh is idempotent.
- Append mode handles gaps and overlaps.
- A failed source does not mark stale data authoritative.

### Phase 7 - Integration With `trading_assistant`

Deliverables:

- Set `MARKET_DATA_ROOT=../trading_assistant_data/data/export`.
- Generate one shadow monthly bundle for a low-risk strategy.
- Short-term: for single-slice runs, confirm the data repo writes the default coverage
  manifest at `data/export/manifests/<bot_id>/<strategy_id>/<YYYY-MM>.coverage_manifest.json`.
- Preferred: add `MonthlyValidationRequest.data_bundle_manifest_path` in
  `trading_assistant` so monthly validation can pass the data repo bundle directly into
  `MonthlyRunManifest`.
- If continuing to use `MarketDataSyncJob`, update it to preserve data repo checksum,
  source version, calendar, fee/slippage, and adjustment metadata instead of generating a
  diagnostics-only composite.
- Confirm `trading_assistant` records the bundle checksum in `MonthlyRunManifest`.
- Confirm backtest artifacts must echo the checksum before gates pass.

Acceptance:

- Monthly validation can run in `shadow` without data-contract repair requests.
- `MonthlyRunManifest.data_bundle_manifest_path` points to a data repo-owned bundle, or
  to a bundle built from authoritative data repo metadata rather than a lossy sync output.
- If a data file is modified, checksum mismatch causes fail-closed validation.

## First Authoritative Targets

Do not try to make everything authoritative at once.

Recommended order:

1. Crypto Hyperliquid BTC/ETH/SOL candles and funding.
   - Data source is cleanest.
   - 24/7 calendar is simplest.
   - Existing parquet is compact and recent.
2. CME futures NQ/ES momentum bars.
   - Critical for US futures strategies.
   - Requires futures roll and alignment discipline.
3. KRX daily LRS parquet.
   - Existing manifest is already strong.
   - Needs KRX holiday source before authoritative use.
4. KIS intraday parquet.
   - High value, but timestamp/session semantics and duplicate range merging need care.
5. US equity stock universe.
   - Large file count and broader symbol coverage; useful after the core loop is proven.
6. Macro/regime seed data.
   - Useful for context and regime features, but not the first monthly optimizer blocker.

## Key Risks And Controls

| Risk | Control |
|---|---|
| Backtest looks good on stale or partial data | Authoritative bundles require source repo SHA, checksums, calendars, coverage ratios, and missing ranges |
| Data repo accidentally becomes strategy/backtest repo | Boundary tests and README forbid strategy decisions, optimizer logic, and order APIs |
| KRX holiday/session gaps create false signals | Real holiday calendar required before authoritative status |
| KIS client ports order methods | Static test fails if read-only client exposes buy/sell/order/cancel/revise methods |
| Crypto script is ported while imports are missing | Rebuild downloader/store first; use `refresh_data.py` as behavior spec only |
| Futures continuous series hides bad roll seams | Panama roll policy manifest plus gap/roll quality checks |
| Multiple data layouts confuse consumers | Canonical partitioned layout plus generated compatibility export |
| Current `trading_assistant` sync output drops authority metadata | Data repo writes authoritative single-slice manifests directly, or `trading_assistant` accepts `data_bundle_manifest_path` before shadow |
| Multi-slice bundle is collapsed into one aggregate slice manifest | Conformance test blocks synthetic aggregate `MarketDataManifest`; direct bundle handoff is required |

## Definition Of Done For The Data Repo

The repo is ready for `trading_assistant_backtest` creation when:

- It can build at least one authoritative monthly `DataBundleManifest`.
- It can export filesystem-compatible monthly parquet shards for `trading_assistant`.
- It can populate the current default monthly coverage-manifest path for single-slice
  runs, or `trading_assistant` has been updated to accept a direct
  `data_bundle_manifest_path` handoff for multi-slice bundles.
- It has conformance tests against `trading_assistant` schemas.
- It has source-specific ingestion tests for IBKR, Hyperliquid, KIS, and the local LRS KRX daily export path.
- It has coverage reports with explicit missing ranges.
- It has versioned calendars and cost/adjustment policies.
- It has no strategy execution, optimizer, approval, or order-routing code.

At that point, create `trading_assistant_backtest` and make the backtest runner consume
only `MonthlyRunManifest` plus `DataBundleManifest`.
