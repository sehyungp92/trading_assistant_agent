# Audit Remediation Plan — 4 Reports (2026-05-09 / 2026-05-10)

## Context

Four audit reports were produced 2026-05-09 → 2026-05-10 covering live/paper-trading readiness across the unified monorepo. Together they raise ~60 findings, with significant overlap (e.g. swing equity, reconnect callbacks, account_id propagation, research coordinator status, init-db.sh, RiskContext serialization, duplicate fills, offline executions). Each claim was verified against HEAD by reading the cited files directly. This plan classifies each claim (VALID / PARTIAL / INVALID), captures **what already exists in the codebase that we should reuse** (so we don't duplicate work), and lays out remediation grouped by tier and dependency.

The reports:
1. `docs/repo-audit-2026-05-09.md`
2. `docs/live-paper-trading-critical-audit-2026-05-09.md`
3. `docs/live-paper-trading-strategy-oms-audit-2026-05-09.md`
4. `docs/live-paper-trading-audit-2026-05-10.md`

User-confirmed scope:
- Full P0 + P1 set.
- TPC + NQ_REGIME — keep `enabled: true`, **build live coordinator-driven wiring** (substantial new code; see Phase D below).
- Deferred futures research family — keep out of production wiring.

---

## Findings classification

Legend: ✅ VALID (verified at file:line); ⚠️ PARTIAL (claim true but framing/severity overstated); ❌ INVALID (refuted at code); ✓ ALREADY-EXISTS (substrate the fix should reuse, not rebuild).

### P0 — Trade-blocking / state-corrupting

| ID | Claim | Verdict | Verification + reusable substrate |
|----|-------|---------|-----------------------------------|
| **OMS-1** | `RiskContext.unit_risk_dollars` dynamically attached, persisted via `__dict__`, fails `RiskContext(**rc_data)` on reload | ✅ VALID | `libs/oms/models/order.py:75-83` — RiskContext lacks the field; `libs/oms/risk/gateway.py:295` attaches dynamically; `libs/oms/persistence/repository.py:125` persists `__dict__`; `:454-455` reconstructs and would fail. ✓ Note: `OMSOrder.retry_count` (line 142-143) is already declared with comment "H5: persisted instead of transient dynamic attr" — same H5 pattern was applied to retry_count but `unit_risk_dollars` was missed. |
| **OMS-2** | `FillProcessor.process_fill()` returns None; factory callbacks unconditionally update risk/equity/positions even on duplicates | ✅ VALID | `libs/oms/engine/fill_processor.py:33` returns `None`; line 56-58 silently early-exits on `fill_exists()`; line 100-112 throws away the `inserted: bool` from `save_order_fill_and_event`. Factory callbacks at `libs/oms/services/factory.py:1193` (single OMS) and `:1533` (multi OMS) both call `process_fill` and proceed unconditionally. ✓ **Reusable substrate**: `repository.save_fill` (line 158-184) already returns `bool`; `save_order_fill_and_event` (line 196-209) already returns `bool` keyed off the duplicate insert. We just need to surface those existing return values up through `process_fill` and gate the callbacks. |
| **OMS-3** | `cache.rebuild_from_broker(...)` marks every fetched broker execution `seen` without importing as fills; later `execDetailsEvent` is dropped | ✅ VALID | `libs/broker_ibkr/state/cache.py:84-86` calls `mark_fill_seen(exec_id)` unconditionally for each fetched execution. `libs/broker_ibkr/adapters/execution_adapter.py:291-295` returns early when `is_fill_seen()` is true. `libs/oms/reconciliation/orchestrator.py:64-72` also fetches `request_executions()` but only logs the count; never imports. ✓ **Reusable substrate**: `repository.fill_exists(broker_fill_id)` (line 211-216) already exists; `FillProcessor.process_fill` is idempotent through `save_order_fill_and_event` (which returns False on duplicate). Fix is to (a) call `fill_exists` first in `rebuild_from_broker`, (b) if missing, route through `FillProcessor` to import it, (c) only call `mark_fill_seen` after success. |
| **SWING-1** | Swing live equity is hardcoded to `$100_000.0` | ✅ VALID | `strategies/swing/coordinator.py:189` literal `100_000.0` — no NetLiquidation read in the live branch. ✓ **Reusable substrate**: momentum (`strategies/momentum/coordinator.py:114-125`) and stock both already have a NetLiquidation lookup pattern (broken in different ways — see EQUITY-1). Plan extracts a single helper used by all three. |
| **SWING-2** | Swing soft-degrades on `IBKRConfig` load failure | ✅ VALID | `strategies/swing/coordinator.py:151-175` catches and sets `adapter=None`; `:417-418` proceeds. Compare momentum at `strategies/momentum/coordinator.py:89-94` which raises `RuntimeError` immediately. The swing path is the only family that soft-degrades. |

### P1 — Silent drift / reliability

| ID | Claim | Verdict | Verification + reusable substrate |
|----|-------|---------|-----------------------------------|
| **OMS-4** | Account-level risk gate is not atomic with order reservation across multiple OMS instances | ✅ VALID — but **scope-heavy** | `libs/risk/account_risk_gate.py` reads under `pg_advisory_xact_lock` but releases before persistence. With 7 OMS instances on one account this is a real race. The audit's recommended fix (account_risk_reservations table + same-txn reservation) is a substantial schema + transaction-flow change. **Recommendation: stage as a discrete PR after Phase A** — too risky to bundle with OMS state-machine fixes. Phase A's other OMS fixes do not require this. |
| **OMS-5** | `open_positions` runtime cache not hydrated from DB on restart | ⚠️ PARTIAL severity, ✅ valid concern | `libs/oms/services/factory.py:269` (single) and `:652` (multi) initialize empty dicts. `_sync_strategy_risk_from_repo` hydrates the strategy-risk dataclass (lines 271, 656) but does NOT seed `open_positions`. The exit-fill code paths (single: `:1274-1334`; multi: `:1616-1668`) do `pos = open_positions.get(pos_key)` and silently skip the entire P&L/risk-release/equity-update block when `pos` is None. After restart, an exit fill will save a flat-zero position with no realized P&L. Real concern. |
| **OMS-6** | Order upsert ON CONFLICT omits `retry_count` and `reject_reason`; `_row_to_order()` doesn't read them | ✅ VALID for repository, ⚠️ already-declared for the model | `OMSOrder.retry_count` IS declared (`libs/oms/models/order.py:142-143`) with the H5 comment; `reject_reason` IS declared (line 121). But `repository.save_order` ON CONFLICT update (line 98-101) does not refresh either field, and `_row_to_order()` (line 472-500) does not read either. Pacing-retry budget resets after restart. |
| **OMS-7** | `OMSOrder.account_id` is blank for swing/momentum (default `""`); only stock sets it | ✅ VALID | `OMSOrder.account_id` defaults to `""` (`libs/oms/models/order.py:94`). `strategies/stock/iaric/execution.py:32-37` sets `account_id` explicitly. Swing/momentum execution code does not — the agent verified this for ATRSS at `strategies/swing/atrss/engine.py:1278-1290`. Real attribution gap in DB. |
| **OMS-8** | Fill-arrives-before-status race leaves order in `ROUTED` with `filled_qty>0` (P2 in 2026-05-10 audit) | ✅ VALID — P2, but cheap to fix | `libs/oms/engine/state_machine.py:18` forbids `ROUTED→FILLED`; `libs/oms/engine/fill_processor.py:91-97` rejects the transition with a warning then **still saves the fill** (line 100-110). `_apply_status_update` already handles the status-first walk in factory.py at the level the 2026-04-24 fix added, but the fill-first direction was not mirrored. Fix: walk `ROUTED→ACKED` before transitioning to `FILLED` inside `fill_processor.py`. |
| **CONN-1** | `set_reconnect_callback` is a single-value setter; later coordinator clobbers earlier; net effect is no OMS reconciliation after IB reconnect | ✅ VALID | `libs/broker_ibkr/connection.py:27` declares single value; `:73-75` setter overwrites; `:128-135` reconnect loop invokes only the single stored callback. Swing registers OMS reconciler at `strategies/swing/coordinator.py:300-302`; stock registers engine-only reconcile at `:360-361` (clobbers swing); momentum registers nothing. |
| **EQUITY-1** | Live equity in momentum/stock silently falls back to `$100_000.0` if `NetLiquidation` lookup fails or arrives late | ✅ VALID | `strategies/momentum/coordinator.py:114-125`, `strategies/stock/coordinator.py:120-131` both warn and continue with $100k. `accountValues()` populates asynchronously after IB connect; race vs. coordinator startup is plausible. |
| **CFG-1** | `portfolio.yaml.risk.heat_cap_R / portfolio_daily_stop_R / portfolio_weekly_stop_R` are dead config; three competing sources | ✅ VALID | Defined at `config/portfolio.yaml:1-5` and `libs/config/models.py:138-142`; zero consumers. `apps/runtime/runtime.py:459-465` constructs the gate without piping the YAML through; `AccountRiskGate` falls through to dataclass defaults (2.5R/3.0R). Swing has its own competing constants (5.5R/3.75R/9.0R) at `strategies/swing/coordinator.py:59-61`. |
| **RUNTIME-1** | Coordinator-create / coordinator-start failures swallowed — runtime continues partial-family unless ALL fail | ✅ VALID | `apps/runtime/runtime.py:546-572` catches per-family; `:632` `if not coordinators` shutdown gate only triggers if every family fails. |
| **STRAT-1** | TPC enabled but inert in production — engine inherits `ETFCoreLiveEngine` whose `start()` only marks running; plugin callbacks empty | ✅ VALID — substantial scope to fix | `strategies/swing/_shared/etf_live_engine.py:58-60` start() only marks running; `process_bar_input` (line 89-99) is a sync method that returns actions/events without any dispatcher. TPC's `process_bar_input` (`strategies/swing/tpc/engine.py:50-107`) overrides for instrumentation but inherits the rest. **No bar scheduler, no OMS event loop, no action dispatcher** exists. Comparison: ATRSS has `_hourly_scheduler` (line 348), `_hourly_cycle` (line 387), `_fetch_hourly_bars` (line 2273) and an event_task (line 280). Wiring TPC to live = building a new subclass scheduler + dispatcher + event loop, ~150-300 LoC. |
| **STRAT-2** | NQ_REGIME enabled but inert — engine `start()` only marks running, no scheduler | ✅ VALID — substantial scope | `strategies/momentum/nq_regime/engine.py:104-108` start spawns event_task but no bar scheduler. NQDTC has `start()` at line 329 doing `_restore_state()` + event_task + `_fetch_bars(startup)` + `_5m_scheduler` task. Same scope as TPC. |
| **STRAT-3** | Deferred futures research coordinator unreachable; user-flagged as research-phase | ✅ VALID, **remove from production surface per user direction** | Historical research coordinator was not registered in `_FAMILY_COORDINATORS` (`apps/runtime/runtime.py:32-36`); entries were disabled. |
| **STRAT-4** | Strategy state hydration inconsistent — Vdub, NQ_REGIME, IARIC, ALCB, ATRSS, AKC_HELIX, TPC have hydrate methods but coordinators don't call them; only NQDTC + Downturn restore | ✅ VALID — staged | NQRegimeEngine has `hydrate()` (line 120-126) and `snapshot_state()` (line 128). NQDTC's `_restore_state()` is engine-internal, not coordinator-driven. ETFCoreLiveEngine has `hydrate()` and `snapshot_state()` (line 83-87). The coordinators construct engines and call `engine.start()` without first calling `hydrate(snapshot)`. **Phase D (TPC/NQ_REGIME wiring) naturally introduces engine.hydrate(snapshot) into the new scheduler-driven start path; for ATRSS/Helix/IARIC/ALCB the same pattern can be added with minimal risk.** |
| **RELAY-1** | Relay's `purge_stale_unacked(days=3)` permanently deletes evidence if assistant orchestrator is offline >3 days | ✅ VALID | `apps/relay/db/store.py:232-249`; called at `apps/relay/app.py:109` (startup) and `:122` (every 24h). |
| **RELAY-2** | Relay auth defaults insecure; missing API key / shared secrets only warns, doesn't fail | ✅ VALID — P1 | `apps/relay/app.py:85-101` warns. `.env.example` defaults `RELAY_API_KEY=` and `RELAY_SHARED_SECRETS={}`. |
| **RELAY-3** | Sidecar assigns priority but `GET /events` ignores it (`ORDER BY id ASC LIMIT ?`) | ✅ VALID — P1 | `apps/relay/db/store.py` (per audit). |
| **RELAY-4** | Swing/momentum sidecars only forward daily JSON when watermark==0 (vs stock's mtime/hash model) | ✅ VALID — P1 | per audit, fix is to port stock's mtime/hash watermark to swing+momentum. |
| **TA-1** | Trading-assistant bot config IDs drift from runtime emitter IDs | ✅ VALID | `_references/trading_assistant/data/bot_configs/swing_trader.yaml:1` has `bot_id: swing_trader`; runtime uses `swing_multi_01`. Same for `momentum_trader.yaml` → runtime `momentum_nq_01`. |
| **TA-2** | TA strategy_profiles.yaml stale (NQ URD 300 vs live 50) | ✅ VALID | per audit. |
| **INFRA-1** | `infra/init-db.sh` heredoc unquoted; bash interpolates `${READER_PW}/${WRITER_PW}` into SQL with no escaping; passwords containing `'` break role creation | ✅ VALID — P1 (downgrading from F-I4 P0) | Confirmed: `infra/init-db.sh:16` uses `<<EOSQL` (unquoted). The "P0 injection" framing in the repo audit overstates it (init runs once, no untrusted input), but the cold-start fragility is real if any password contains `'`, `\`, backtick, or `$VAR`. |
| **SWING-3** | Swing coordinator action logger may be wired against `ctx.instrumentation = None` | ✅ VALID | `strategies/swing/coordinator.py:287-293` reads `instrumentation_ctx = getattr(ctx, "instrumentation", None)` and wires `_coordinator.set_action_logger(...)` only if non-None. The runtime constructs RuntimeContext with `instrumentation=None`; the swing coordinator's local `_bootstrap_instrumentation_kits()` (later in start()) creates `self._instrumentation_ctx` but the wiring above already happened against the empty `ctx.instrumentation`. Result: swing coordinator action evidence is dropped. The directory mapping issue (P1-11b) is also real — swing sidecar maps `coordination_events/` not `coordination/`. |

### P2 — Quality / observability

| ID | Claim | Verdict |
|----|-------|---------|
| **CFG-2** | Risk parameters duplicated YAML ↔ coordinator; reference URD constants conflict with YAML URDs | ✅ VALID | swing 34-56 vs YAML 26-82; momentum reference URD `250.0` vs YAML 50/200; stock reference URD `162.0` vs YAML 100. |
| **CFG-3** | Swing per-strategy `max_heat_R` sums to 8.25R but family `_HEAT_CAP_R = 5.5R` (50% over) | ✅ VALID — likely intentional. |
| **CFG-4** | `account_urd` env-only with no validation | ✅ VALID. |
| **CFG-5** | `NQDTC_STATE_DIR/DOWNTURN_STATE_DIR` env wins over `manifest.engine_config.state_dir` from YAML | ✅ VALID at `strategies/momentum/coordinator.py:624, 668`. |
| **CFG-6** | No `TRADING_MODE` ↔ port assertion (live with port 4002 silently lands on paper gateway) | ✅ VALID. |
| **HB-1** | Heartbeat loops only catch `CancelledError`; exceptions outside `asyncio.sleep` kill the loop | ✅ VALID. |
| **DB-1** | Migrations 004 + 005 both define `v_portfolio_daily_summary` | ✅ VALID. |
| **DB-2** | `DB_POOL_MAX=10` likely too small | ✅ VALID. |
| **DB-3** | `paper_equity` schema uses `DOUBLE PRECISION` instead of `NUMERIC` | ✅ VALID. |
| **DB-4** | Some views use `CURRENT_DATE` (mitigated by tz pinning at init) | ✅ VALID. |
| **NET-1** | `network_mode: host` defeats `depends_on` healthchecks; runtime preflight mitigates | ✅ VALID, mitigated. |
| **NET-2** | IB Gateway healthcheck is TCP-only; doesn't verify TWS login | ✅ VALID. |

### P3 — Polish

| ID | Claim | Verdict |
|----|-------|---------|
| **DOC-1** | Stale swing coordinator docstring | ✅ VALID at `strategies/swing/coordinator.py:1-12`. |
| **DIR-1** | Heartbeat dir naming mismatch: swing `heartbeat/`, mom/stock `heartbeats/` | ✅ VALID, cosmetic. |
| **HB-2** | Heartbeat strategy-level exceptions logged at DEBUG | ✅ VALID. |
| **DB-5** | Migration 006 backfills `family_id='unknown'` | ✅ VALID, ops-only. |

### Reclassified / refuted

| ID | Claim | Verdict | Reason |
|----|-------|---------|--------|
| **REFUTED-1** | Repo-audit F-I4 P0 framing of init-db.sh as "shell-injection-style" | ⚠️ severity overstated, fix still warranted | True bug (passwords with `'` break role creation), but "injection" framing implies untrusted input. Reclassified as P1 cold-start fragility (INFRA-1). |
| **REFUTED-2** | "open_positions not hydrated" framed as full P0 corruption | ⚠️ P1 not P0 | DB-backed risk state IS hydrated; in-memory map is a runtime cache that does affect exit-fill correctness (real bug), but symptomatic only when an exit arrives without a prior entry event in the same process lifetime. Real concern, not catastrophic. Reclassified as P1 (OMS-5). |
| **REFUTED-3** | "retry_count is not declared on OMSOrder" implication | ⚠️ partial | `retry_count` and `reject_reason` ARE declared on OMSOrder (line 142, 121). The actual gap is in `repository.save_order` ON CONFLICT and `_row_to_order` only. Smaller fix than the audit suggested. |
| **REFUTED-4** | MEMORY claims about strategy roster + per-strategy client_ids | ✅ MEMORY IS STALE | Verified: single `client_id=7`; swing = ATRSS+AKC_HELIX+TPC+Overlay; momentum = NQDTC+NQ_REGIME+VdubusNQ+DownturnDominator; stock = IARIC+ALCB. |

---

## Implementation plan

### Phase A — P0 OMS persistence + restart safety (independent fixes, can be parallelised)

1. **OMS-1: `RiskContext.unit_risk_dollars` persistence**
   - `libs/oms/models/order.py:75-83` — add `unit_risk_dollars: float = 0.0` field. Mirror the H5 comment style used for `OMSOrder.retry_count` (line 142): `# H7: persisted instead of transient dynamic attr`.
   - `libs/oms/persistence/repository.py:443-456` — `_row_to_order` already calls `RiskContext(**rc_data)` which will now succeed. **Belt-and-braces:** add a tolerant decoder (`{k: v for k, v in rc_data.items() if k in {f.name for f in fields(RiskContext)}}`) to insulate against future similar drift. Same protective filter for `EntryPolicy` at line 449.
   - `libs/oms/risk/gateway.py:295` — keep the dynamic assign (it already works); the field is now declared so persistence is safe.
   - **Test**: `tests/integration/test_riskcontext_roundtrip.py` — persist a real `OMSOrder` via Postgres, reload via `_row_to_order`, assert `unit_risk_dollars` survives. (Existing `test_entry_serialization.py` uses MagicMock and missed this — replace or augment.)

2. **OMS-2: Gate fill side effects on dedupe result**
   - `libs/oms/engine/fill_processor.py:25-43` — change return to `bool` (or a small `FillProcessResult` dataclass). Return `False` on the `fill_exists` early-out (line 56-58) and on the `save_order_fill_and_event` returning False (line 111-112). `inserted = True` on the success path.
   - `libs/oms/services/factory.py:1193, 1533` — capture the bool. Wrap all post-`process_fill` side-effect blocks in `if inserted:`. The wrap covers the strategy fill emit (line 1196-1209), risk update (1211-1231), open_positions update (1232-1248), entry-side coordinator notification (multi-OMS), paper/live equity (1249+), exit branch (1274-1334), and final `save_position` (1361). Same pattern in multi at 1535+.
   - ✓ **Reuse**: existing `repo.save_fill` and `save_order_fill_and_event` already return bool — we are surfacing values that exist, not changing DB semantics.
   - **Test**: `tests/integration/test_duplicate_fill_callback.py` — drive same `broker_fill_id` twice; assert exactly one risk/equity update.

3. **OMS-3: Import missing executions before mark-seen**
   - `libs/broker_ibkr/state/cache.py:54-99` — change `rebuild_from_broker` signature to accept an optional `fill_importer: Callable[[ExecReport], Awaitable[bool]]` and a `fill_exists_check: Callable[[str], Awaitable[bool]]`. Inside the per-execution loop (lines 84-91): (a) call `fill_exists_check(exec_report.exec_id)`; (b) if False AND we have an importer, call it; (c) only call `mark_fill_seen()` when the fill is confirmed in OMS DB.
   - `libs/oms/reconciliation/orchestrator.py:55-72` — wire the importer. The importer wraps `FillProcessor.process_fill(...)` so it goes through the same idempotent path as live execDetails. Resolve OMS order ID via `repo.get_order_id_by_broker_order_id(broker_id)` (already exists at repository line 241-251).
   - ✓ **Reuse**: `repo.fill_exists` (already exists, line 211-216). `FillProcessor` already idempotent. No new import path needed; reuse.
   - **Test**: `tests/integration/test_offline_execution_import.py`.

4. **OMS-5: Hydrate `open_positions` from DB on startup (P1, but architecturally part of Phase A)**
   - `libs/oms/services/factory.py` — after `open_positions = {}` at line 269 (single) and 652 (multi), call a new `_hydrate_open_positions_from_repo(open_positions, repo, strategy_ids, …)` BEFORE `OMSService.start()` is awaited. Read non-zero positions via `repo.get_positions_for_strategies(...)` (line 388-399, already exists) and seed dict entries with `entry_price`, `risk_per_contract_R`, `point_value`, `side`, `open_qty`, plus `risk_per_contract_portfolio_R` for multi.
   - ⚠ **Schema gap**: the current `positions` table stores `open_risk_R` and `open_risk_dollars` per position but does NOT store `risk_per_contract_R`, `point_value`, `side`, or `entry_price` separately enough to fully reconstruct the dict. Plan: derive `risk_per_contract_R = open_risk_R / |net_qty|`; `side` from sign of `net_qty`; `entry_price` from `avg_price`; `point_value` from the `Instrument` registry (line 460 lookup). This avoids a migration.
   - **Halt-on-mismatch**: if an exit fill arrives for an unknown position in paper/live, halt rather than silently writing zero-row.
   - **Test**: `tests/integration/test_restart_exit_fill.py`.

### Phase B — P0 swing coordinator + shared NetLiquidation helper

5. **EQUITY shared helper** (extract first, reuse in 3 places)
   - New file `libs/services/equity.py` exposing `async def resolve_live_nlv(session, *, account_id: str | None = None, timeout_s: float = 10.0) -> float`. Wait-loop on `session.ib.accountValues()`, match `tag == "NetLiquidation"`, `currency == "USD"`, account match (configured `IB_ACCOUNT_ID` if provided, else `managedAccounts()[0]`). Raises `RuntimeError` if timeout or zero/negative.

6. **SWING-1: Swing live equity from `NetLiquidation`**
   - `strategies/swing/coordinator.py:184-195` — in the live branch, replace `equity = 100_000.0` with `equity = await resolve_live_nlv(session, account_id=ibkr_config.profile.account_id if ibkr_config else None)`.

7. **EQUITY-1: Replace momentum + stock fallbacks**
   - `strategies/momentum/coordinator.py:114-125` — replace the warn-and-default block with the helper call.
   - `strategies/stock/coordinator.py:120-131` — same.

8. **SWING-2: Hard-fail on `IBKRConfig` load**
   - `strategies/swing/coordinator.py:151-159` — replace the soft-degrade except branch with `raise RuntimeError(...) from exc`. Keep the `session is None` (shadow/test) path soft.

### Phase C — P1 reliability cluster

9. **CONN-1: Reconnect callbacks as a list**
   - `libs/broker_ibkr/connection.py:27` — change to `_on_reconnect_callbacks: list[Callable] = []` in `__init__` (line 19-27).
   - `libs/broker_ibkr/connection.py:73-75` — keep `set_reconnect_callback` as a deprecated alias that **appends** (don't break existing calls). Add new `add_reconnect_callback(cb)`.
   - `libs/broker_ibkr/connection.py:128-135` — iterate the list; per-callback try/except so one failure doesn't stop the others.
   - `libs/broker_ibkr/session.py:456-467` — wrapper update.
   - `strategies/swing/coordinator.py:300-302` — switch to `add_reconnect_callback`.
   - `strategies/stock/coordinator.py:360-361` — switch to `add_reconnect_callback`.
   - `strategies/momentum/coordinator.py` — **add** a reconnect callback that iterates `self._oms_services` and calls `oms._reconciler.on_reconnect_reconciliation()` on each (momentum has 4 OMS instances).
   - **Test**: register two callbacks, simulate reconnect via `ib.disconnectedEvent`, assert both fire.

10. **CFG-1: Wire `portfolio.yaml` into AccountRiskGate; surface effective caps**
    - `apps/runtime/runtime.py:459-465` — pass `self.portfolio.risk.heat_cap_R` and `self.portfolio.risk.portfolio_daily_stop_R` to `AccountRiskGate(...)`. Keep `account_urd` env path but log effective dollar caps at startup (`heat=2.5R=$500, daily_stop=3.0R=$600, urd=$200`).
    - In paper/live, **raise** on `AccountRiskGate` init failure rather than warning-only.
    - **Layering decision**: `portfolio.yaml.risk.*` are account-level (cross-family); swing's `_HEAT_CAP_R=5.5` etc. at `strategies/swing/coordinator.py:59-61` are intra-family. Rename swing module-level constants to `_SWING_FAMILY_HEAT_CAP_R` / `_SWING_FAMILY_DAILY_STOP_R` / `_SWING_FAMILY_WEEKLY_STOP_R` and add a one-line comment explaining the two-tier model. Document in `config/portfolio.yaml`.
    - Add `account_urd_dollars` to `PortfolioRiskConfig` so it isn't env-only (CFG-4).

11. **RUNTIME-1: Hard-fail partial-family startup in paper/live**
    - `apps/runtime/runtime.py:546-572` — in the per-coordinator try/except, if `get_environment() in ("paper", "live")` and `not allow_partial_families` (new CLI flag), re-raise. Default = strict.
    - `apps/runtime/cli.py` — add `--allow-partial-families` flag.

12. **OMS-6: Persist + hydrate `retry_count` and `reject_reason`**
    - `libs/oms/persistence/repository.py:98-101` — extend ON CONFLICT update SET clause to include `retry_count=$28, reject_reason=$29` (with new params at end of insert tuple).
    - `:472-500` — hydrate both fields in `_row_to_order`.
    - **Test**: round-trip a retryable + terminal reject.

13. **OMS-7: Inject `account_id` into swing/momentum order builders**
    - Pattern: each coordinator already has `ibkr_config.profile.account_id` in scope (swing line 171, momentum line 172). Pass it to engines as `account_id` constructor kwarg or attach at the OMS-bridge layer.
    - Easiest path: a thin wrapper at the OMS intent layer — `IntentHandler.create_intent` (or equivalent) injects `account_id = self._account_id` if the order's `account_id == ""`. The OMS service factory already has `account_id` available.
    - Add validation: in paper/live, `IntentHandler` rejects orders with empty `account_id`.
    - **Test**: assert all enabled strategies' OMSOrders carry non-empty `account_id`.

14. **OMS-8: Mirror status-first walk in fill-first race**
    - `libs/oms/engine/fill_processor.py:91-97` — before transitioning to `FILLED`/`PARTIALLY_FILLED`, walk `ROUTED → ACKED` if needed. Reuse the helper from `factory.py:_apply_status_update` (extract to `engine/transitions.py` if needed).

15. **SWING-3: Wire swing coordinator action logger AFTER bootstrap**
    - `strategies/swing/coordinator.py` — move the `set_action_logger` block from line 287-293 to AFTER `_bootstrap_instrumentation_kits()` runs (which creates `self._instrumentation_ctx`). Use `self._instrumentation_ctx` not `ctx.instrumentation`.
    - Either (a) add `coordination` directory mapping to swing sidecar (`strategies/swing/instrumentation/src/sidecar.py`), or (b) make `CoordinationLogger` write to `coordination_events/` (which is already mapped). Recommendation: (b) — minimal sidecar changes, aligns with regime/crisis emitters already writing to `coordination_events/`.

16. **STRAT-4: Coordinator-driven engine state hydration**
    - For each enabled strategy, in the family coordinator's `start()` BEFORE `engine.start()`, load any persisted snapshot and call `engine.hydrate(snapshot)` (where the engine declares it). NQDTC's existing `_restore_state` becomes redundant but harmless during transition. Plan: introduce `libs/persistence/engine_state.py` with `load_snapshot(strategy_id)` / `save_snapshot(strategy_id, snapshot)` — file-based JSON keyed by strategy_id, mirroring NQDTC's pattern.
    - Snapshot writers: schedule periodic `engine.snapshot_state()` writes in each engine (e.g. inside the bar scheduler tail). NQDTC already does this; ATRSS/Helix/Vdub/IARIC/ALCB will need the same hook.
    - For TPC and NQ_REGIME, this is folded into Phase D's wiring naturally.

17. **RELAY-1: Stale-purge window**
    - `apps/relay/db/store.py:232` — change default `days=3` → 14 (override via env `RELAY_PURGE_DAYS`).
    - `apps/relay/app.py:122` — same.
    - Add `oldest_pending_age_seconds` metric exposed via `GET /metrics`.

18. **RELAY-2: Auth mandatory in paper/live**
    - `apps/relay/app.py:85-101` — in `paper`/`live` mode, raise on missing `RELAY_API_KEY` or empty `RELAY_SHARED_SECRETS` unless `ALLOW_UNAUTHENTICATED_RELAY_DEV=1`.

19. **RELAY-3: Priority-aware `GET /events`**
    - `apps/relay/db/store.py:get_events` — `ORDER BY priority DESC, id ASC LIMIT ?`. Preserve ack semantics by acking strict-monotonic `id`. Document that low-priority backlog can build behind higher-priority events.

20. **RELAY-4: Port stock sidecar mutable-file watermarks to swing+momentum**
    - Stock sidecar's mtime/hash watermark logic at `strategies/stock/instrumentation/src/sidecar.py` — extract to a shared base or copy the pattern verbatim into `strategies/swing/instrumentation/src/sidecar.py` and `strategies/momentum/instrumentation/src/sidecar.py`.

21. **TA-1: Bot config IDs**
    - Rename `_references/trading_assistant/data/bot_configs/swing_trader.yaml` → `swing_multi_01.yaml` (and inside, `bot_id: swing_multi_01`).
    - Rename `momentum_trader.yaml` → `momentum_nq_01.yaml` (and inside, `bot_id: momentum_nq_01`).
    - Verify `ConfigRegistry` doesn't hard-code the old filenames; if it does, update.

22. **TA-2: TA strategy_profiles refresh + drift test**
    - Update `_references/trading_assistant/data/strategy_profiles.yaml` to match `config/strategies.yaml` URDs (NQDTC=50, NQ_REGIME=50, Vdubus=200, Downturn=50, IARIC=100, ALCB=100, swing-family per current YAML).
    - Add a drift test that compares YAML, coordinator reference URDs, and TA profiles.

23. **INFRA-1: Quote heredoc + psql variables**
    - `infra/init-db.sh:16` — change `<<EOSQL` to `<<'EOSQL'`. Pass passwords via `-v reader_pw="$READER_PW" -v writer_pw="$WRITER_PW"` and reference as `:'reader_pw'` / `:'writer_pw'` in SQL (psql escapes them as proper SQL literals).
    - **Test**: smoke with a password containing `'`.

### Phase D — TPC + NQ_REGIME live wiring (substantial new code; user requested)

This is the largest piece of work in the plan. Building production execution shells for both strategies — bar scheduler, action dispatcher, OMS event loop, state hydration — is ~150-300 LoC per strategy. The patterns to mirror exist:

- **NQDTC** (`strategies/momentum/nqdtc/engine.py:329-430`): 5m boundary scheduler, `_fetch_bars(request_kind=…)`, `_on_5m_close`, OMS event_task, action dispatch via `await self._dispatch_action(action)`, state via `_restore_state`/`_persist_state`.
- **ATRSS** (`strategies/swing/atrss/engine.py:273-465`): hourly scheduler, `_fetch_hourly_bars`, `_hourly_cycle` building bar input, action dispatch.

24. **NQ_REGIME live wiring**
    - In `strategies/momentum/nq_regime/engine.py`, override the existing `start()` (line 104-108) to:
      1. Call `await self.hydrate(load_snapshot(STRATEGY_ID))` (per STRAT-4).
      2. Spawn an OMS event_task (already exists at line 108).
      3. Spawn a `_5m_scheduler` task that wakes on 5m boundaries (mirror NQDTC's pattern at line 410-430), fetches NQ continuous-future bars via `self._ib.req_historical_data` (or the shared `historical_requester`), constructs a `BarData`, calls `await self.on_bar(bar_data, daily_context=…, live_context=…)`.
      4. The split between `analysis_symbol="NQ"` and `trade_symbol="MNQ"` — bars are fetched on NQ, but the `on_bar` action dispatch must construct OMS orders on MNQ. The engine's `_dispatch_action` (need to add — copy NQDTC's pattern at the level that converts `SubmitEntry`/`SubmitProtectiveStop`/etc. into `OMSOrder` objects with `instrument = self._instruments[trade_symbol]`).
      5. Snapshot state periodically (end of each cycle) via `save_snapshot(STRATEGY_ID, self.snapshot_state())`.
    - Daily-context fetch: `KeyLevels` are computed from a daily NQ bar fetch — call once at startup and once per ET trading day boundary inside the scheduler.

25. **TPC live wiring**
    - In `strategies/swing/tpc/engine.py`, override `start()` to spawn:
      1. Hydration: `await load_snapshot(STRATEGY_ID)` then `await self.hydrate(snapshot)`.
      2. OMS event_task that consumes `oms.stream_events(STRATEGY_ID)` and routes fills/order-updates into `self.process_fill(...)` / `self.process_order_update(...)` (TPC has these at lines 109+ and 146+).
      3. A bar scheduler. TPC consumes `ETFBarInput` which carries `bar_15m`. Use a 15m boundary scheduler. Per-symbol fetch loop using `session.req_historical_data` for each TPC symbol from `_config`.
      4. An action dispatcher that converts swing actions (`SubmitEntry`, `SubmitProtectiveStop`, `ReplaceProtectiveStop`, `SubmitProfitTarget`, `CancelAction`, `FlattenPosition`) into `OMSOrder` + intents on the shared swing OMS. ATRSS's pattern at `strategies/swing/atrss/engine.py:_hourly_cycle` and surrounding `_dispatch_action` is the template.
      5. Snapshot state periodically.
    - Coordinator wiring: the swing coordinator already constructs TPCEngine at line 373 and calls `engine.start()` at 416 — no coordinator changes required if the override is on TPCEngine itself.

26. **Liveness metrics for STRAT-1/STRAT-2**
    - Heartbeat payload should include `bars_processed` per strategy (already exists for NQDTC, exists in ETFCoreLiveEngine.health_status at line 73, exists for NQ_REGIME at line 169). Surface in `emit_family_heartbeats`.
    - Watchdog rule: alert if a started strategy's `bars_processed` is zero past the expected first-bar time for its market hours.

### Phase E — Research-family cleanup (user requested)

27. **STRAT-3 — Remove deferred research family from production surface**
    - Keep the research package outside the live repo and runtime registry until it has a rebuilt coordinator mirroring the momentum pattern: per-strategy OMS service construction, account gate, portfolio rules, instrumentation manager, and heartbeat task.
    - `config/strategies.yaml` — keep only active production families in the registry.
    - All four audit reports — append a one-line callout to each research-family finding:
      `> [Note 2026-05-10]: the deferred futures research family is intentionally outside the current remediation cycle.`
    - **Files**:
      - `docs/repo-audit-2026-05-09.md` (F-S2)
      - `docs/live-paper-trading-critical-audit-2026-05-09.md` (add a footnote)
      - `docs/live-paper-trading-strategy-oms-audit-2026-05-09.md` (P2 research-family finding)
      - `docs/live-paper-trading-audit-2026-05-10.md` (P1-5)

### Phase F — MEMORY.md refresh

28. **Refresh MEMORY.md** to reflect verified ground truth:
    - Strategy roster: swing = ATRSS + AKC_HELIX + TPC + Overlay; momentum = NQDTC_v2.1 + NQ_REGIME + VdubusNQ_v4 + DownturnDominator_v1; stock = IARIC_v1 + ALCB_v1.
    - Connection topology: single `client_id=7` for all strategies — delete the stale "swing=7, momentum=11/12/13/14, stock=31/32/34" claim.
    - Family membership corrections: DownturnDominator_v1 = momentum (not stock); AKC_HELIX = swing (not momentum); US_ORB removed from stock.

---

## Critical files to modify

- `libs/oms/models/order.py` — `RiskContext.unit_risk_dollars` field add
- `libs/oms/persistence/repository.py` — tolerant decoder, ON CONFLICT update extension, `_row_to_order` field reads
- `libs/oms/engine/fill_processor.py` — return value, ROUTED→ACKED→FILLED walk
- `libs/oms/services/factory.py` — gate side effects on `inserted` (single + multi callbacks), hydrate `open_positions`
- `libs/oms/reconciliation/orchestrator.py` — execution import before mark-seen
- `libs/broker_ibkr/state/cache.py` — accept fill_importer, mark-seen-only-after-import
- `libs/broker_ibkr/connection.py`, `libs/broker_ibkr/session.py` — list-of-callbacks pattern
- `libs/risk/account_risk_gate.py` — (no signature change, already accepts kwargs)
- `apps/runtime/runtime.py` — wire `portfolio.risk.*`, hard-fail partial families, log effective caps
- `apps/runtime/cli.py` — `--allow-partial-families` flag
- `strategies/swing/coordinator.py` — live equity, IBKRConfig hard-fail, action-logger ordering, _SWING_FAMILY_* renames, set_reconnect_callback → add_reconnect_callback
- `strategies/momentum/coordinator.py` — live equity helper, add reconnect callback (new), STATE_DIR YAML-aware (CFG-5)
- `strategies/stock/coordinator.py` — live equity helper, add_reconnect_callback
- `strategies/momentum/nq_regime/engine.py` — live wiring (Phase D)
- `strategies/swing/tpc/engine.py` — live wiring (Phase D)
- `config/strategies.yaml` — production roster cleanup
- `apps/relay/db/store.py`, `apps/relay/app.py` — purge window, priority order, auth mandatory, metrics
- `apps/relay/auth.py` — fail-fast in paper/live
- `strategies/swing/instrumentation/src/sidecar.py` — mutable-file watermarks, `coordination` dir mapping (or move emitter to `coordination_events`)
- `strategies/momentum/instrumentation/src/sidecar.py` — mutable-file watermarks
- `infra/init-db.sh` — quoted heredoc + psql variables
- `_references/trading_assistant/data/bot_configs/{swing,momentum}_*.yaml` — bot_id rename
- `_references/trading_assistant/data/strategy_profiles.yaml` — URD refresh
- `libs/services/equity.py` — NEW shared NLV helper
- `libs/persistence/engine_state.py` — NEW snapshot store
- `docs/{four audit files}` — research-family callouts
- `MEMORY.md` — strategy roster + topology refresh

## Reusable substrate (already exists — do not duplicate)

- `repository.save_fill` returns bool (line 158-184) — surface, don't replace
- `repository.save_order_fill_and_event` returns bool (line 196-209) — surface
- `repository.fill_exists(broker_fill_id)` (line 211-216) — call from cache rebuild
- `repository.get_order_id_by_broker_order_id(...)` (line 241-251) — order resolution for execution import
- `repository.get_positions_for_strategies(...)` (line 388-399) — for open_positions hydration
- `FillProcessor` is already idempotent — reuse for execution import path
- `_apply_status_update` in factory.py — extract / reuse for fill-first race walk
- `OMSOrder.retry_count` and `reject_reason` already declared (model-level) — only the persistence layer needs the fix
- `AccountRiskGate(__init__)` already accepts `heat_cap_R` / `daily_stop_R` kwargs — only the runtime call site needs to pass them
- NQDTC (`_5m_scheduler`, `_fetch_bars`, `_on_5m_close`, `_dispatch_action`) — full template for NQ_REGIME wiring
- ATRSS (`_hourly_scheduler`, `_hourly_cycle`, `_fetch_hourly_bars`) — template for TPC wiring
- Stock sidecar mutable-file watermarks — copy pattern to swing/momentum sidecars

## Verification — end-to-end smoke

After all fixes:
1. Wipe Postgres volume; recreate with `POSTGRES_READER_PASSWORD="abc'def$x"` (INFRA-1 test).
2. Start runtime in paper mode against a paper IBKR account.
3. Verify all four families start (RUNTIME-1 hard-fail satisfied).
4. Verify startup log: `AccountRiskGate active: heat=2.5R=$500, daily_stop=3.0R=$600, urd=$200` (CFG-1).
5. Verify swing live equity in live mode = real NLV (SWING-1, EQUITY-1).
6. Force IB Gateway restart mid-session; verify all four families' OMS reconcilers fire (CONN-1).
7. Place a synthetic entry; restart runtime mid-flight; place exit; verify state machine + risk + equity all consistent (OMS-1, OMS-2, OMS-5).
8. Verify a synthetic broker execution arriving while runtime down gets imported on restart and side effects fire exactly once (OMS-3).
9. Drive a duplicate `execDetailsEvent` at the OMS callback level; assert no double-counting (OMS-2).
10. Verify NQ_REGIME `bars_processed > 0` within 6 minutes of session start; verify TPC `bars_processed > 0` within 16 minutes (STRAT-1, STRAT-2).
11. Verify TA bot configs map runtime emitter IDs (TA-1).
