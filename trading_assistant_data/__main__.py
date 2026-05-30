from __future__ import annotations

import sys
from pathlib import Path

src = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(src))

from trading_assistant_data.cli import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())

