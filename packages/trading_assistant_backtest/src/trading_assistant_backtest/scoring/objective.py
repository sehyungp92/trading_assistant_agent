"""Objective component vocabulary."""

from __future__ import annotations

DEFAULT_OBJECTIVE_COMPONENTS = [
    "expected_return",
    "calmar",
    "profit_factor",
    "expectancy",
    "max_drawdown_penalty",
    "trade_frequency_viability",
    "cost_slippage_robustness",
]


def capped_components(cap: int) -> list[str]:
    return DEFAULT_OBJECTIVE_COMPONENTS[: max(1, min(cap, len(DEFAULT_OBJECTIVE_COMPONENTS)))]
