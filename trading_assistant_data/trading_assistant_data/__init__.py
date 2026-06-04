"""Source-tree convenience wrapper.

The installable package lives under ``src/``. This wrapper lets
``python -m trading_assistant_data`` work directly from a fresh checkout.
"""

from __future__ import annotations

from pathlib import Path

_src_pkg = Path(__file__).resolve().parents[1] / "src" / "trading_assistant_data"
if _src_pkg.exists():
    __path__.append(str(_src_pkg))
