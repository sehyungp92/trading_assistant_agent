"""Agent-root checkout shim for the data product package.

This lets ``python -m trading_assistant_data`` work from the enclosing
``trading_assistant_agent`` directory. Editable installs and commands run from the data
workspace itself use ``src/trading_assistant_data`` directly.
"""

from __future__ import annotations

from pathlib import Path

_src_package = Path(__file__).resolve().parent / "src" / "trading_assistant_data"
if _src_package.exists():
    __path__ = [str(_src_package)]

