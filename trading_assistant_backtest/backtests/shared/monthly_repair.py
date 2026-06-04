"""Compatibility module for `python -m backtests.shared.monthly_repair`."""

from __future__ import annotations

import sys
from pathlib import Path


def _ensure_src_on_path() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    src = repo_root / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))


def main(argv: list[str] | None = None) -> int:
    _ensure_src_on_path()
    from trading_assistant_backtest.monthly import main as monthly_main

    return monthly_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
