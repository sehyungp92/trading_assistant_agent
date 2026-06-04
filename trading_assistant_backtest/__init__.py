"""Agent-root checkout shim for the backtest repo package.

This lets `python -m trading_assistant_backtest.monthly` work from the enclosing
`trading_assistant_agent` directory as well as from `trading_assistant_backtest` itself.
"""

from __future__ import annotations

from pathlib import Path

_src_package = Path(__file__).resolve().parent / "src" / "trading_assistant_backtest"
if _src_package.exists():
    __path__ = [str(_src_package)]

__version__ = "0.1.0"
