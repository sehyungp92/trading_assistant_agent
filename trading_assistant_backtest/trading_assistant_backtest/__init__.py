"""Checkout-time import shim for the src-layout package.

Editable installs use `src/trading_assistant_backtest` directly. This shim exists only so
`python -m trading_assistant_backtest.monthly` works from a fresh checkout too.
"""

from __future__ import annotations

from pathlib import Path

_src_package = Path(__file__).resolve().parents[1] / "src" / "trading_assistant_backtest"
if _src_package.exists():
    __path__.append(str(_src_package))

__version__ = "0.1.0"
