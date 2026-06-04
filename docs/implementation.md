# Deployment & Implementation Guide

Step-by-step guide to deploying the three-package trading-assistant monorepo:
the relay on a VPS, bot sidecars, the local orchestrator (`trading_assistant`),
the market-data authority (`trading_assistant_data`), and the replay lab
(`trading_assistant_backtest`). Legacy single-repo notes live in
`docs/implementation_old.md`; this guide supersedes it and adds the data /
backtest wiring required for the monthly evidence loop.

---

## Architecture

```text
Bot VPSes   -> Sidecars            -> Relay VPS         -> Local Orchestrator
              (HMAC-signed JSONL)     (FastAPI :8001       (FastAPI :8000
                                       SQLite buffer)        VPSReceiver -> Brain
                                                              -> Worker -> Handlers
                                                              -> AgentRunner)

trading_assistant_data       -> ../trading_data/market           (MARKET_DATA_ROOT)
trading_assistant_backtest   -> ../trading_data/runs/monthly_*   (BACKTEST_ARTIFACT_ROOT)
                                ../trading_backtests             (BACKTEST_REPO_PATH)
```

Data flow (live path): bot writes JSONL -> sidecar HMAC-signs + POSTs to
relay -> orchestrator polls relay -> local queue dedups by `event_id` ->
deterministic brain routes -> handler resolves provider profile -> CLI runtime
executes -> Telegram / Discord / email.

Data flow (monthly path): `trading_assistant_data` rebuilds the frozen market
bundle and writes coverage manifests; `trading_assistant_backtest` runs replay
parity, phased-auto, and OOS repair against those bundles; `trading_assistant`
owns the StrategyChangeLedger, approval cards, deployment monitoring, and
outcome measurement.

---

## Prerequisites

- Python 3.12+ on every machine.
- SSH access to each bot VPS and one VPS to run the relay.
- Claude CLI (for `claude_max`, `zai_coding_plan`, `openrouter`) and/or Codex
  CLI (for `codex_pro`) installed locally and authenticated.
- Telegram bot token (recommended first channel).
- Working git remote for `BACKTEST_REPO_PATH` if you intend to run the monthly
  loop in non-shadow mode.

### Generate shared secrets

You need two relay-side secrets — HMAC (bot -> relay) and API key
(orchestrator -> relay), plus an `ORCHESTRATOR_API_KEY` for the local control
plane:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"   # run three times
```

---

## Step 1: Deploy the Relay (VPS)

The relay code still lives under `_references/trading/apps/relay/`. It is
unchanged from the legacy guide.

### 1.1 Copy and install

```bash
scp -r _references/trading/apps user@relay-vps:/opt/trading/
ssh user@relay-vps
cd /opt/trading && python3 -m venv venv && source venv/bin/activate
pip install fastapi uvicorn pydantic
```

### 1.2 Configure `/opt/trading/.env`

```bash
RELAY_SHARED_SECRETS='{"swing_multi_01":"HMAC1","momentum_nq_01":"HMAC2","stock_trader":"HMAC3","k_stock_trader":"HMAC4"}'
RELAY_API_KEY=YOUR_API_KEY
RELAY_DB_PATH=/opt/trading/data/relay.db
```

### 1.3 Run via systemd

`/etc/systemd/system/trading-relay.service`:

```ini
[Unit]
Description=Trading Relay
After=network.target
[Service]
Type=simple
User=trading
WorkingDirectory=/opt/trading
EnvironmentFile=/opt/trading/.env
ExecStart=/opt/trading/venv/bin/uvicorn apps.relay.app:app --host 127.0.0.1 --port 8001
Restart=always
RestartSec=5
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=/opt/trading/data
[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload
systemctl enable --now trading-relay
curl http://127.0.0.1:8001/health
```

Open port `8001/tcp` to the bot VPSes and to your home IP (firewall scoped,
not internet-wide). For TLS, terminate with Nginx (Appendix A).

---

## Step 2: Bot Sidecars

Each bot needs a sidecar thread that tails event JSONL and forwards batches to
the relay. Sources live in:

- US monorepo: `_references/trading/strategies/{swing,momentum,stock}/instrumentation/src/sidecar.py`
- K-Stock: `_references/k_stock_trader/instrumentation/src/sidecar.py`

### 2.1 Configure per bot

`instrumentation/config/instrumentation_config.yaml`:

```yaml
bot_id: "swing_multi_01"
data_dir: "instrumentation/data"
sidecar:
  relay_url: "http://RELAY_VPS_IP:8001"   # auto-normalized to /events
  hmac_secret_env: "INSTRUMENTATION_HMAC_SECRET"
  batch_size: 50
  retry_max: 5
  retry_backoff_base_seconds: 10
  poll_interval_seconds: 60
  buffer_dir: "instrumentation/data/.sidecar_buffer"
```

### 2.2 Wire into the bot

```bash
export INSTRUMENTATION_HMAC_SECRET=YOUR_HMAC_SECRET   # must match relay map
```

```python
import yaml
from instrumentation.src.sidecar import Sidecar
config = yaml.safe_load(open("instrumentation/config/instrumentation_config.yaml"))
sidecar = Sidecar(config); sidecar.start()
# ... bot runs ...
sidecar.stop()
```

Verify: `tail -f instrumentation/data/instrumentation.log` and check
`.sidecar_buffer/watermark.json`. Repeat for all four bots.

---

## Step 3: Install the Local Stack (workstation)

The repo is a monorepo of three editable installs. Install them in this
order so the orchestrator picks up the data + backtest packages it imports
through their public APIs:

```bash
git clone <repo-url> trading_assistant_agent
cd trading_assistant_agent

# Create one venv for the whole stack
python -m venv .venv
.venv\Scripts\Activate.ps1                       # Windows
# source .venv/bin/activate                      # macOS/Linux

# Editable installs
pip install -e ./trading_assistant_data
pip install -e ./trading_assistant_backtest
pip install -e "./trading_assistant[dev,notifications]"
```

`notifications` adds Telegram, Discord, and email adapters. Drop it if you
will route everything through Telegram only.
The command examples below use the console scripts installed by these editable
installs. If a shell cannot find a script, run the equivalent module form, for
example `python -m trading_assistant_backtest.validation.approval_grade_audit`.

### 3.1 Smoke-test each package

```bash
pytest trading_assistant_data/tests -q
pytest trading_assistant_backtest/tests -q
pytest trading_assistant/tests -q     # ~3370 tests, all should pass
```

---

## Step 4: Configure the Orchestrator (`trading_assistant`)

Copy `trading_assistant/.env.example` to `trading_assistant/.env`. Minimum
non-shadow configuration:

```bash
# --- Bots ---
BOT_IDS=k_stock_trader,stock_trader,swing_multi_01,momentum_nq_01
BOT_TIMEZONES=k_stock_trader:Asia/Seoul,stock_trader:US/Eastern,swing_multi_01:US/Eastern,momentum_nq_01:US/Eastern

# --- Agent runtimes ---
CLAUDE_COMMAND=claude
CODEX_COMMAND=codex
AGENT_PROVIDER=claude_max     # seeds data/agent_preferences.json on first boot only

# --- Relay link ---
RELAY_URL=https://relay.yourdomain.com
RELAY_API_KEY=YOUR_API_KEY

# --- Local control plane ---
BIND_HOST=127.0.0.1
ORCHESTRATOR_API_KEY=YOUR_ORCH_KEY       # required unless ALLOW_UNAUTHENTICATED_LOCAL=true on loopback
ALLOW_UNAUTHENTICATED_LOCAL=false

# --- Notifications ---
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...

# --- Monthly evidence loop (shadow first, see Step 6) ---
MONTHLY_VALIDATION_ENABLED=true
MONTHLY_VALIDATION_MODE=shadow
MARKET_DATA_ROOT=../trading_data/market
BACKTEST_REPO_PATH=../trading_backtests
BACKTEST_ARTIFACT_ROOT=../trading_data/runs/monthly_validation
```

### 4.1 Startup invariants

The lifespan in `orchestrator/config.py` refuses to boot when:

- `BIND_HOST` is non-loopback and `ORCHESTRATOR_API_KEY` is empty.
- `AGENT_PROVIDER` (or any per-workflow override) is set to `zai_coding_plan`
  / `openrouter` without the corresponding API key.
- `MONTHLY_VALIDATION_ENABLED=true` and `MONTHLY_VALIDATION_MODE` is anything
  other than `disabled`, `shadow`, or `approval_gated`.

### 4.2 Create the data tree

`DATA_DIR` defaults to `data` inside `trading_assistant/`. Resolved paths are
logged at startup as `Resolved data dirs: ...`.

```bash
cd trading_assistant
mkdir data\raw data\curated data\benchmarks runs memory\findings logs .assistant
```

`memory/policies/v1/` is version-controlled — never recreate or overwrite it.

### 4.3 Bring it up

```bash
uvicorn orchestrator.app:app --host 127.0.0.1 --port 8000
```

```bash
curl http://127.0.0.1:8000/health
curl -H "X-Api-Key: %ORCHESTRATOR_API_KEY%" http://127.0.0.1:8000/metrics
curl -H "X-Api-Key: %ORCHESTRATOR_API_KEY%" http://127.0.0.1:8000/events/pending
curl -H "X-Api-Key: %ORCHESTRATOR_API_KEY%" http://127.0.0.1:8000/agent/preferences
```

`X-Api-Key` is mandatory on every non-`/health` endpoint once
`ORCHESTRATOR_API_KEY` is set.

---

## Step 5: Stand Up `trading_assistant_data`

The data package owns source requests, read-only refreshes, canonical slice
manifests, bundle manifests, legacy-source comparisons, and data reproduction
reports. The current approval path is source-request driven; there is no
generic `refresh --bot` command.

### 5.1 Configure source credentials and write gates

```bash
TA_SOURCE_REFRESH_ALLOW_NETWORK=true
TA_SOURCE_REFRESH_ALLOW_WRITE=true

# IBKR uses a running TWS/Gateway session, not API keys.
IBKR_HOST=127.0.0.1
IBKR_PORT=4002
IBKR_CLIENT_ID=107
IBKR_READ_ONLY_ACK=true

# KIS/KRX market-data refresh.
KIS_BASE_URL=https://openapi.koreainvestment.com:9443
KIS_ACCOUNT_MODE=paper
KIS_APP_KEY=...
KIS_APP_SECRET=...
KIS_READ_ONLY_ACK=true
```

Hyperliquid candles/funding are public and do not require wallet credentials.
For k_stock intraday, live KIS is an incremental append/repair lane. Seed the
archived 103-symbol KIS parquet coverage first, or intentionally set
`KIS_ALLOW_FULL_HISTORY_REFRESH=true` for a full-history rebuild.

### 5.2 Declare source requests

Rebuild the source-request manifest whenever imported legacy files or strategy
requirements change:

```bash
trading-assistant-data --repo-root trading_assistant_data \
  declare-source-requests --snapshot 2026-05-30 --json
```

The source-request manifest maps each old parquet to an exact source request:
IBKR futures/equity bars, KIS/KRX intraday bars, Hyperliquid candles/funding,
or LRS local research imports. It is also the filter used by live syncs.

### 5.3 Refresh source-owned slices

```bash
# Crypto phased optimizer data: BTC/ETH/SOL candles and funding.
trading-assistant-data --repo-root trading_assistant_data \
  sync hyperliquid --symbols BTC,ETH,SOL --intervals 15m,30m,1h,4h,1d \
  --latest --funding --json

# Momentum: retention-covered live TWS lane for resolvable CME contracts.
trading-assistant-data --repo-root trading_assistant_data \
  sync ibkr --families trading_momentum \
  --ibkr-coverage-mode retention-covered --json

# Swing and stock: IBKR read-only historical equity/ETF bars.
trading-assistant-data --repo-root trading_assistant_data \
  sync ibkr --families trading_swing,trading_stock --json

# k_stock: KIS read-only intraday incremental append/repair.
trading-assistant-data --repo-root trading_assistant_data \
  sync kis --families k_stock_kis_intraday --intraday --json
```

Full legacy CME reproduction still requires archived raw IBKR payloads and
contract metadata for pre-retention contracts. Do not treat live TWS retention
coverage as proof that old unavailable contracts can be recreated from TWS.

### 5.4 Build, reproduce, and compare bundles

Build only from indexed, authoritative slice manifests. The command fails if
any required slice is stale, unindexed, non-authoritative, checksum-mismatched,
or has unexplained missing ranges.

```bash
trading-assistant-data --repo-root trading_assistant_data build-bundle \
  --run-month 2026-05 --bot-id crypto_portfolio --strategy-id phased_optimizer \
  --requirements-file data/requirements/strategies/crypto_portfolio/phased_optimizer.json --json

trading-assistant-data --repo-root trading_assistant_data build-bundle \
  --run-month 2026-05 --bot-id trading_momentum_family --strategy-id portfolio \
  --requirements-file data/requirements/strategies/trading_momentum/portfolio.json --json

trading-assistant-data --repo-root trading_assistant_data build-bundle \
  --run-month 2026-05 --bot-id trading_swing_family --strategy-id portfolio \
  --requirements-file data/requirements/strategies/trading_swing/portfolio.json --json

trading-assistant-data --repo-root trading_assistant_data build-bundle \
  --run-month 2026-05 --bot-id trading_stock_family --strategy-id portfolio \
  --requirements-file data/requirements/strategies/trading_stock/portfolio.json --json

trading-assistant-data --repo-root trading_assistant_data build-bundle \
  --run-month 2026-05 --bot-id k_stock_olr_kalcb --strategy-id portfolio \
  --requirements-file data/requirements/strategies/k_stock/portfolio.json --json
```

Then emit durable reproduction and legacy-source reports:

```bash
trading-assistant-data --repo-root trading_assistant_data audit-coverage \
  --run-month 2026-05 --json

trading-assistant-data --repo-root trading_assistant_data reproduce-bundle \
  --bundle-manifest data/bundles/monthly/2026-05/crypto_portfolio/phased_optimizer/data_bundle_manifest.json --json

trading-assistant-data --repo-root trading_assistant_data compare-legacy-source \
  --families trading_momentum,trading_swing,trading_stock,k_stock_kis_intraday,crypto_portfolio \
  --latest-only --json
```

Acceptance for deployment: every active monthly bundle is
`status=authoritative`, every slice is in `slice_index.json`, every required
checksum matches, and any non-exact legacy comparison has a deterministic
reason such as resampling, sparse IBKR ETH trade bars, roll/Panama construction,
or retained-live-source coverage.

---

## Step 6: Stand Up `trading_assistant_backtest`

The backtest package owns replay, scoring, repair, validation reports,
decision-parity evidence, runtime deployment metadata installation, and the
seven active strategy bridge contracts (see
`validation/approval_grade_audit.py`).

### 6.1 Workspace layout

```bash
mkdir ..\trading_backtests
mkdir ..\trading_data\runs\monthly_validation
```

- `BACKTEST_REPO_PATH=../trading_backtests` is the per-candidate isolated
  workspaces Symphony-style runner creates (`auto/`, `repair/`).
- `BACKTEST_ARTIFACT_ROOT=../trading_data/runs/monthly_validation` is for frozen
  replay outputs, parity reports, and the artifact index.

### 6.2 Register strategy contracts

Each active bridge has a `strategy_plugin_contract.json` under
`trading_assistant_backtest/contracts/`: crypto trend/momentum/breakout,
k_stock OLR/KALCB, trading stock, trading momentum, and trading swing. They
are currently `shadow_validated` until live metadata, scheduled shadow
evidence, fixture breadth, and the approval audit justify manual promotion.
Verify bridge inventory and the five-test matrix with the actual entrypoints:

```bash
trading-assistant-backtest-bridge-readiness --agent-root .
trading-assistant-backtest-validation-matrix --agent-root .
```

### 6.3 Runtime deployment metadata

The current remaining deployment blocker is live/VPS metadata. The backtest
package now includes an emitter and a fail-closed installer. Run the emitter
from the live bot checkout at startup or deploy time:

```bash
trading-assistant-backtest-emit-deployment-metadata \
  --repo-path /opt/crypto_trader \
  --contract /opt/trading_assistant_agent/trading_assistant_backtest/contracts/crypto_trend_v1/strategy_plugin_contract.json \
  --config /opt/crypto_trader/config/live_config.json \
  --output /opt/crypto_trader/runtime/deployment_metadata.crypto_trend_v1.json \
  --bot-id crypto_portfolio \
  --strategy-id trend \
  --strategy-version crypto_trend_v1 \
  --config-version live_config_v1 \
  --telemetry-schema-version trade_event_v1 \
  --runtime-entrypoint "crypto-trader live" \
  --runtime-instance-id "crypto-vps-1" \
  --deployment-id "crypto-vps-1-2026-06" \
  --emission-environment production_vps
```

Repeat for the bridge being promoted. The emitted JSON must have a non-local
repo URL, deployed SHA equal to the contract's `live_repo_commit_sha`, clean
worktree proof, config hash, telemetry schema listed by the contract, runtime
identity, contract path/hash, and `dry_run=false`.

Import the emitted file on the workstation:

```bash
trading-assistant-backtest-install-deployment-metadata \
  --agent-root . \
  --bridge-id crypto_trend_v1 \
  --metadata /path/to/deployment_metadata.crypto_trend_v1.json \
  --install
```

The installer must report `ok=true` and `installed=true`. It rejects local,
shadow, dry-run, dirty-checkout, SHA-mismatched, contract-hash-mismatched, and
telemetry-schema-mismatched metadata.

### 6.4 Run validation and optimizer evidence

Run the existing evidence jobs before any bridge promotion:

```bash
trading-assistant-backtest-data-reproduction --agent-root . --scope all
trading-assistant-backtest-replay-evidence --agent-root . --scope all
trading-assistant-backtest-validation-matrix --agent-root .
trading-assistant-backtest-approval-grade-audit --agent-root .
```

The approval audit must stay fail-closed until the selected bridge is manually
promoted from `shadow_validated` to `approval_ready` and all runtime metadata,
parity, replay, walk-forward, P6 fold scoring, and P7 repair/confirmatory
checks pass. For a manifest-level monthly runner smoke, use:

```bash
trading-assistant-backtest-monthly --manifest path/to/run_manifest.json
trading-assistant-backtest-monthly --manifest path/to/run_manifest.json --validate-only
```

---

## Step 7: Relay <-> Orchestrator Sync

`VPSReceiver` polls on a fixed cadence (`RELAY_POLL_INTERVAL_SECONDS=300`):

1. Startup drain on boot.
2. `GET /events?since=<watermark>&limit=100` every 300s.
3. Local insert + dedup by `event_id`.
4. `POST /ack` advances the relay watermark.
5. Watermark persisted to local SQLite for restart resume.

Auth: bot -> relay uses `X-Signature = HMAC-SHA256(canonical_json, HMAC_SECRET)`;
orchestrator -> relay uses `X-Api-Key = RELAY_API_KEY`. A 401 means either the
bot's HMAC or the orchestrator's API key is wrong.

---

## Step 8: Notifications

### 8.1 Telegram (required for approvals)

Create the bot through `@BotFather`, then:

```bash
TELEGRAM_BOT_TOKEN=123:ABC...
TELEGRAM_CHAT_ID=-1001234567890
```

`/settings` exposes provider switching. Approval / experiment buttons appear
only when `AUTONOMOUS_ENABLED=true` or when `MONTHLY_VALIDATION_MODE=approval_gated`.

### 8.2 Discord / Email (optional)

```bash
DISCORD_BOT_TOKEN=
DISCORD_CHANNEL_ID=
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=
SMTP_PASS=
EMAIL_FROM=
EMAIL_TO=
```

Email needs the `notifications` extra. On a fresh install, channels are
auto-seeded into `data/notification_prefs.json` from whichever adapters are
configured.

---

## Step 9: End-to-End Verification

```bash
# Liveness
curl http://RELAY_VPS_IP:8001/health
curl http://127.0.0.1:8000/health

# Pipeline
curl -H "X-Api-Key: %ORCHESTRATOR_API_KEY%" http://127.0.0.1:8000/events/pending
curl -H "X-Api-Key: %ORCHESTRATOR_API_KEY%" -X POST http://127.0.0.1:8000/process
curl -H "X-Api-Key: %ORCHESTRATOR_API_KEY%" http://127.0.0.1:8000/metrics

# Direct ingest (bypasses relay; for smoke testing)
curl -H "X-Api-Key: %ORCHESTRATOR_API_KEY%" -X POST http://127.0.0.1:8000/ingest \
  -H "Content-Type: application/json" \
  -d "{\"event_id\":\"manual-001\",\"bot_id\":\"stock_trader\",\"event_type\":\"trade\",\"payload\":{\"trade_id\":\"demo\"},\"exchange_timestamp\":\"2026-05-10T12:00:00+00:00\"}"

# Monthly shadow run from inside the orchestrator
python -m orchestrator.scheduler --run-now monthly_validation
```

### Control-plane endpoints

| Endpoint | Purpose |
|----------|---------|
| `GET /health` | Liveness (no auth) |
| `GET /metrics` | Operational metrics |
| `POST /ingest` | Direct event injection |
| `GET /events/pending` | Peek local queue |
| `GET /events/dead-letter` / `POST /events/dead-letter/{id}/reprocess` | DLQ inspect + requeue |
| `GET/PUT /agent/preferences` | Provider defaults + per-workflow overrides |
| `GET/PUT /notifications/preferences` | Channel preferences |

All non-`/health` endpoints require `X-Api-Key` when `ORCHESTRATOR_API_KEY`
is set.

---

## Step 10: Run as a Service

### 10.1 Windows auto-start (recommended for the local workstation)

```powershell
powershell -ExecutionPolicy Bypass -File trading_assistant\scripts\install-startup.ps1
```

Behaviour: interpreter resolution (`.venv` -> `venv` -> `PATH`), single-instance
ownership, log rotation under `logs\orchestrator.log` /
`logs\orchestrator.err.log`, hidden `pythonw` child, health-checked restart
with capped backoff. Startup catch-up replays missed cron jobs via
`scheduled_runs.db` and APScheduler `misfire_grace_time`.

Remove: `Unregister-ScheduledTask -TaskName "TradingAssistantAutoStart"`.

### 10.2 Linux systemd (if running on a server)

```ini
[Unit]
Description=Trading Assistant Orchestrator
After=network.target
[Service]
Type=simple
User=your_user
WorkingDirectory=/path/to/trading_assistant_agent/trading_assistant
EnvironmentFile=/path/to/trading_assistant_agent/trading_assistant/.env
ExecStart=/path/to/trading_assistant_agent/.venv/bin/uvicorn orchestrator.app:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=10
[Install]
WantedBy=multi-user.target
```

Logs: `journalctl -u trading-orchestrator -f`,
`trading_assistant/logs/events-YYYY-MM-DD.jsonl`,
`trading_assistant/memory/heartbeat.md`, and per-bot
`instrumentation/data/instrumentation.log`.

---

## Step 11: Promote Monthly Loop from Shadow to Approval-Gated

Only flip `MONTHLY_VALIDATION_MODE=approval_gated` after at least one full
shadow-mode month has produced deployment evidence for the specific bridge or
portfolio being promoted:

1. Runtime-emitted deployment metadata has been installed with
   `trading-assistant-backtest-install-deployment-metadata --install`.
2. The installed metadata is live/VPS sourced, not local/shadow/dry-run, and
   its repo URL, deployed SHA, clean worktree flag, config hash, telemetry
   schema, runtime identity, and contract hash all pass the installer checks.
3. `trading-assistant-backtest-validation-matrix --agent-root .` reports the
   five validation tests passing for the promoted scope.
4. `trading-assistant-backtest-approval-grade-audit --agent-root . --scope <scope>`
   is blocked only by intentional `shadow_validated` maturity before promotion.
5. The operator updates the selected bridge contract from `shadow_validated`
   to `approval_ready`, reruns bridge readiness and approval audit, and the
   audit reports `approval_grade=true` for that scope.
6. A Telegram approval card is delivered against a known-safe candidate, with
   ledger entry written under `data/strategy_change_ledger.jsonl`.

Then promote:

```bash
# In trading_assistant/.env
MONTHLY_VALIDATION_MODE=approval_gated
DEPLOYMENT_MONITORING_ENABLED=true
```

Restart the orchestrator. Deployment monitoring will start tracking the next
merged candidate for regressions and can open an auto-rollback PR.

---

## Scheduled Jobs

Configured in `orchestrator/scheduler.py`. Defaults:

| Job | Schedule | Grace |
|-----|----------|-------|
| `worker.process_batch` | every 60s | - |
| `monitoring_loop.run_all` | every 60 min | - |
| `vps_receiver.poll` | every 300s | - |
| `stale_event_recovery` | every 900s | - |
| `daily_analysis_*` | per-timezone group | 12h |
| `morning_scan_*` / `evening_report_*` | per-timezone group | 4h |
| `weekly_summary_trigger` | Sun 08:00 UTC | 48h |
| `memory_consolidation` | Sun 09:00 UTC | 48h |
| `threshold_learning` | Sun 09:30 UTC | 48h |
| `outcome_measurement` | Sun 10:00 UTC | 48h |
| `transfer_outcome_measurement` | Sun 10:30 UTC | 48h |
| `learning_cycle` | Sun 11:00 UTC | 48h |
| `market_data_sync` | 1st of month 01:00 local | 12h |
| `monthly_validation` | 2nd of month 03:00 local | 48h |
| `discovery_analysis` | Sat 03:00 UTC | 48h |
| `approval_expiry` | daily 00:00 UTC | 4h |
| `reliability_verification` | daily 06:30 UTC | 12h |
| `pr_review_check` | every 1h | - |
| `deployment_check` | every 30 min | - |
| `experiment_check` | every 6h | - |

---

## Feature Flags

| Env Var | Default | Enables |
|---------|---------|---------|
| `MONTHLY_VALIDATION_ENABLED` | `false` | Monthly evidence loop scheduler hook |
| `MONTHLY_VALIDATION_MODE` | `disabled` | `shadow` (artifact-producing dry runs) or `approval_gated` (approval cards + ledger writes after audits pass) |
| `MONTHLY_OPTIMIZER_SEQUENCE_ENABLED` | `true` | Planner emits the full phased-auto + repair sequence |
| `AUTONOMOUS_ENABLED` | `false` | Legacy suggestion processor; shared approval surface |
| `DEPLOYMENT_MONITORING_ENABLED` | `false` | Post-merge regression detection + auto-rollback PR |
| `ADAPTIVE_THRESHOLDS_ENABLED` | `false` | `threshold_learning` job tunes detector thresholds |
| `AB_TESTING_ENABLED` | `false` | A/B experiment management |
| `LEARNING_REVIEW_MODE` | `deterministic` | Set to `llm_review` to enable LLM-backed prompt-pattern review |

---

## Troubleshooting

| Symptom | Check |
|---------|-------|
| Bot events not reaching relay | `instrumentation.log`, `$INSTRUMENTATION_HMAC_SECRET`, `.sidecar_buffer/watermark.json` |
| Orchestrator not pulling | `$RELAY_URL`, `curl -H "X-Api-Key:..." $RELAY/events`, `journalctl ... grep relay` |
| Orchestrator 401 locally | Add `-H "X-Api-Key: $ORCHESTRATOR_API_KEY"` to every non-`/health` request |
| Orchestrator refuses to start | `BIND_HOST` non-loopback without `ORCHESTRATOR_API_KEY`; provider missing required secret; `MONTHLY_VALIDATION_MODE` invalid |
| Monthly bundle build fails | Run `trading-assistant-data audit-coverage --run-month <YYYY-MM> --json`; inspect stale, unindexed, non-authoritative, checksum, and missing-range errors |
| Deployment metadata install fails | Inspect `deployment_metadata_install_report.json`; common blockers are local/shadow source, dirty live checkout, SHA mismatch, contract-hash mismatch, missing config hash, or telemetry schema mismatch |
| Approval card never arrives in `approval_gated` mode | Run `trading-assistant-backtest-approval-grade-audit --agent-root . --scope <scope>`; bridge maturity, live metadata, parity, replay, or optimizer evidence is still blocking |
| Relay DB growing | `curl -X POST "$RELAY/admin/purge?days=3" -H "X-Api-Key:..."` |
| High event latency | Sidecar `poll_interval_seconds`, `RELAY_POLL_INTERVAL_SECONDS=300`, network |

---

## Appendix A: Nginx HTTPS for the Relay

```nginx
server {
    listen 443 ssl;
    server_name relay.yourdomain.com;
    ssl_certificate /etc/letsencrypt/live/relay.yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/relay.yourdomain.com/privkey.pem;
    location / {
        proxy_pass http://127.0.0.1:8001;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        client_max_body_size 10m;
    }
}
```

Then update sidecar `relay_url` and orchestrator `RELAY_URL` to the HTTPS
URL. Multi-relay setups are not supported by the orchestrator (single
`RELAY_URL`).

---

## Appendix B: Quick Reference

### Secrets

| Machine | Variable | Value |
|---------|----------|-------|
| Bot VPS | `INSTRUMENTATION_HMAC_SECRET` | HMAC secret for that bot |
| Relay VPS | `RELAY_SHARED_SECRETS` | `{"bot_id":"hmac",...}` JSON |
| Relay VPS | `RELAY_API_KEY` | Relay read API key |
| Workstation | `RELAY_API_KEY` | Same value as relay |
| Workstation | `ORCHESTRATOR_API_KEY` | Control-plane API key |
| Workstation | `IBKR_*` / `KIS_*` / `TA_SOURCE_REFRESH_*` | Read-only production source refresh gates |
| Workstation | Hyperliquid | Public candles/funding; no wallet credentials required |
| Workstation | `ZAI_API_KEY` / `OPENROUTER_API_KEY` | Optional alternate providers |

### Paths

| Variable | Default | Owner |
|----------|---------|-------|
| `DATA_DIR` | `data` | `trading_assistant` runtime data |
| `MARKET_DATA_ROOT` | `../trading_data/market` | `trading_assistant_data` bundles |
| `BACKTEST_REPO_PATH` | `../trading_backtests` | per-candidate workspaces |
| `BACKTEST_ARTIFACT_ROOT` | `../trading_data/runs/monthly_validation` | frozen replay outputs |

### Ports

- Relay: `8001`
- Orchestrator: `8000`

Both configurable via `uvicorn --port`.

---

## Promotion Checklist

Use this list when moving from a fresh clone to a production-ready local
deployment:

- [ ] Relay deployed, `/health` reachable from workstation and all bot VPSes.
- [ ] All four bot sidecars running with their `INSTRUMENTATION_HMAC_SECRET`
      values matching the relay's `RELAY_SHARED_SECRETS` map.
- [ ] `pytest` green for `trading_assistant_data`, `trading_assistant_backtest`,
      and `trading_assistant`.
- [ ] `data/agent_preferences.json` seeded with the desired default provider.
- [ ] Source requests are declared, non-dry-run source refreshes complete for
      the promoted scope, and bundle builds are authoritative with indexed
      slices and clean reproduction reports.
- [ ] Live bot calls `trading-assistant-backtest-emit-deployment-metadata`;
      workstation import with `trading-assistant-backtest-install-deployment-metadata --install`
      reports `ok=true` and `installed=true`.
- [ ] Shadow-mode `monthly_validation` plus backtest validation matrix and
      approval-grade audit pass for the promoted scope, except for the
      intentional pre-promotion `shadow_validated` maturity block.
- [ ] Telegram bot delivers a daily report end-to-end.
- [ ] Windows auto-start (or systemd) configured; reboot smoke-tested.
- [ ] Selected bridge contract is manually promoted to `approval_ready`; the
      approval-grade audit is rerun and reports `approval_grade=true`.
- [ ] `MONTHLY_VALIDATION_MODE` promoted to `approval_gated`,
      `DEPLOYMENT_MONITORING_ENABLED=true`.
- [ ] At least one approval card flow completed end-to-end against a
      known-safe candidate.
