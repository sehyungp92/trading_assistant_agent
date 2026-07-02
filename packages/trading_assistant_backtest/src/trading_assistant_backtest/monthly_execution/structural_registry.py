"""Shared structural plugin registry for monthly execution."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from trading_assistant_backtest.strategies.crypto.breakout import (
    DECISION_API_VERSION as CRYPTO_BREAKOUT_DECISION_API_VERSION,
)
from trading_assistant_backtest.strategies.crypto.breakout import (
    PLUGIN_ID as CRYPTO_BREAKOUT_PLUGIN_ID,
)
from trading_assistant_backtest.strategies.crypto.breakout import (
    build_crypto_breakout_decision_parity_report,
)
from trading_assistant_backtest.strategies.crypto.momentum import (
    DECISION_API_VERSION as CRYPTO_MOMENTUM_DECISION_API_VERSION,
)
from trading_assistant_backtest.strategies.crypto.momentum import (
    PLUGIN_ID as CRYPTO_MOMENTUM_PLUGIN_ID,
)
from trading_assistant_backtest.strategies.crypto.momentum import (
    build_crypto_momentum_decision_parity_report,
)
from trading_assistant_backtest.strategies.crypto.trend import (
    DECISION_API_VERSION as CRYPTO_TREND_DECISION_API_VERSION,
)
from trading_assistant_backtest.strategies.crypto.trend import (
    PLUGIN_ID as CRYPTO_TREND_PLUGIN_ID,
)
from trading_assistant_backtest.strategies.crypto.trend import (
    build_crypto_trend_decision_parity_report,
)
from trading_assistant_backtest.strategies.krx.olr_kalcb import (
    DECISION_API_VERSION as K_STOCK_DECISION_API_VERSION,
)
from trading_assistant_backtest.strategies.krx.olr_kalcb import (
    PLUGIN_ID as K_STOCK_PLUGIN_ID,
)
from trading_assistant_backtest.strategies.krx.olr_kalcb import (
    build_k_stock_olr_kalcb_decision_parity_report,
)
from trading_assistant_backtest.strategies.trading.momentum import (
    DECISION_API_VERSION as TRADING_MOMENTUM_DECISION_API_VERSION,
)
from trading_assistant_backtest.strategies.trading.momentum import (
    PLUGIN_ID as TRADING_MOMENTUM_PLUGIN_ID,
)
from trading_assistant_backtest.strategies.trading.momentum import (
    build_trading_momentum_decision_parity_report,
)
from trading_assistant_backtest.strategies.trading.stock import (
    DECISION_API_VERSION as TRADING_STOCK_DECISION_API_VERSION,
)
from trading_assistant_backtest.strategies.trading.stock import (
    PLUGIN_ID as TRADING_STOCK_PLUGIN_ID,
)
from trading_assistant_backtest.strategies.trading.stock import (
    build_trading_stock_decision_parity_report,
)
from trading_assistant_backtest.strategies.trading.swing import (
    DECISION_API_VERSION as TRADING_SWING_DECISION_API_VERSION,
)
from trading_assistant_backtest.strategies.trading.swing import (
    PLUGIN_ID as TRADING_SWING_PLUGIN_ID,
)
from trading_assistant_backtest.strategies.trading.swing import (
    build_trading_swing_decision_parity_report,
)

StructuralParityBuilder = Callable[..., Any]

STRUCTURAL_PARITY_BUILDERS: dict[str, tuple[str, StructuralParityBuilder]] = {
    CRYPTO_TREND_PLUGIN_ID: (
        CRYPTO_TREND_DECISION_API_VERSION,
        build_crypto_trend_decision_parity_report,
    ),
    CRYPTO_MOMENTUM_PLUGIN_ID: (
        CRYPTO_MOMENTUM_DECISION_API_VERSION,
        build_crypto_momentum_decision_parity_report,
    ),
    CRYPTO_BREAKOUT_PLUGIN_ID: (
        CRYPTO_BREAKOUT_DECISION_API_VERSION,
        build_crypto_breakout_decision_parity_report,
    ),
    K_STOCK_PLUGIN_ID: (
        K_STOCK_DECISION_API_VERSION,
        build_k_stock_olr_kalcb_decision_parity_report,
    ),
    TRADING_STOCK_PLUGIN_ID: (
        TRADING_STOCK_DECISION_API_VERSION,
        build_trading_stock_decision_parity_report,
    ),
    TRADING_MOMENTUM_PLUGIN_ID: (
        TRADING_MOMENTUM_DECISION_API_VERSION,
        build_trading_momentum_decision_parity_report,
    ),
    TRADING_SWING_PLUGIN_ID: (
        TRADING_SWING_DECISION_API_VERSION,
        build_trading_swing_decision_parity_report,
    ),
}

CRYPTO_PLUGIN_IDS = frozenset(
    {
        CRYPTO_TREND_PLUGIN_ID,
        CRYPTO_MOMENTUM_PLUGIN_ID,
        CRYPTO_BREAKOUT_PLUGIN_ID,
    }
)

BRIDGE_IDS_BY_SCOPE = {
    "crypto_trader_portfolio": (
        "crypto_trend_v1",
        "crypto_momentum_v1",
        "crypto_breakout_v1",
    ),
    "k_stock_olr_kalcb": ("k_stock_olr_kalcb",),
    "trading_stock_family": ("trading_stock_family",),
    "trading_momentum_family": ("trading_momentum_family",),
    "trading_swing_family": ("trading_swing_family",),
}

BRIDGE_ID_BY_PLUGIN_ID = {
    CRYPTO_TREND_PLUGIN_ID: "crypto_trend_v1",
    CRYPTO_MOMENTUM_PLUGIN_ID: "crypto_momentum_v1",
    CRYPTO_BREAKOUT_PLUGIN_ID: "crypto_breakout_v1",
    K_STOCK_PLUGIN_ID: "k_stock_olr_kalcb",
    TRADING_STOCK_PLUGIN_ID: "trading_stock_family",
    TRADING_MOMENTUM_PLUGIN_ID: "trading_momentum_family",
    TRADING_SWING_PLUGIN_ID: "trading_swing_family",
}


def bridge_ids_for_scope(scope_id: str) -> tuple[str, ...]:
    return BRIDGE_IDS_BY_SCOPE.get(scope_id, ())


def bridge_id_for_plugin(plugin_id: str, fallback: str) -> str:
    return BRIDGE_ID_BY_PLUGIN_ID.get(plugin_id, fallback)


def scope_id_for_plugin(plugin_id: str, fallback: str) -> str:
    if plugin_id in CRYPTO_PLUGIN_IDS:
        return "crypto_trader_portfolio"
    return BRIDGE_ID_BY_PLUGIN_ID.get(plugin_id, fallback)
