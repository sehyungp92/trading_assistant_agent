## #9: Momentum identity model alignment

**Problem**: Momentum bootstrap set `bot_id = strategy_id`, meaning each strategy appeared as a separate "bot" to the assistant. Stock uses a shared family `bot_id` ("stock_trader") with per-strategy `strategy_id`. Additionally, the assistant's regime analysis grouped by `entry_signal` instead of `strategy_id`.

**Fix**:
1. Added `_BOT_ID = "momentum_trader"` constant in bootstrap.
2. Set `config["bot_id"] = _BOT_ID` and `config["strategy_id"] = strategy_id`.
3. Added `strategy_id: str = ""` field to momentum `TradeEvent` dataclass.
4. Wired `strategy_id=self.strategy_id` in `TradeLogger.log_entry()`.

**Files**:
- `strategies/momentum/instrumentation/src/bootstrap.py` -- `_BOT_ID` constant, config identity fix, stale docstring fix
- `strategies/momentum/instrumentation/src/trade_logger.py` -- `strategy_id` field on `TradeEvent`, wired in `log_entry`

### Changes to `trading_assistant`

These files are in the trading assistant codebase (separate repo, vendored at `trading_assistant`). They must be ported to the assistant repo independently.

**`trading_assistant/analysis/strategy_engine.py`** (line 839):
- Changed `strat = getattr(t, "entry_signal", "") or "default"` to `strat = getattr(t, "strategy_id", "") or "default"`
- The docstring on line 831 already documented intent as "Group trades by (bot_id, strategy_id, regime)" -- only the implementation was wrong.
- This aligns grouping with the `strategy_id` field that all three families now populate in their TradeEvent.

**`trading_assistant/tests/test_regime_conditional.py`**:
- Added `strategy_id: str = ""` parameter to `_make_trade` helper and passed it through to `make_trade` factory.
- `test_allocation_per_regime`: Changed `entry_signal="s1"/"s2"` to `strategy_id="s1"/"s2"` to match the engine fix.
- `test_multiple_bots`: Changed `entry_signal="helix"` to `strategy_id="helix"`.
