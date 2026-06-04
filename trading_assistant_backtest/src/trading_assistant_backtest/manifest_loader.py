"""Manifest loading."""

from __future__ import annotations

import json
from pathlib import Path

from trading_assistant_backtest.contract_models import MonthlyRunManifest


def load_manifest(path: str | Path) -> MonthlyRunManifest:
    manifest_path = Path(path)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    return MonthlyRunManifest.model_validate(payload)
