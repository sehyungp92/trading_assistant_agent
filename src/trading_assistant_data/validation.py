"""Manifest validation and coverage helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

import pandas as pd

from .calendars import CalendarDefinition, expected_bars
from .calendars.core import TIMEFRAME_MINUTES
from .manifests import DataBundleManifest, DataBundleStatus, MarketDataManifest, MissingRange
from .repo import is_git_commit_sha


REQUIRED_MARKET_FIELDS = (
    "checksum",
    "session_calendar",
    "source_version",
    "adjustment_policy",
    "fee_model_version",
    "slippage_model_version",
)


@dataclass(frozen=True)
class ValidationReport:
    valid: bool
    status: str
    errors: list[str]
    warnings: list[str]

    def to_dict(self) -> dict:
        return {
            "valid": self.valid,
            "status": self.status,
            "errors": self.errors,
            "warnings": self.warnings,
        }


def market_manifest_errors(
    manifest: MarketDataManifest,
    *,
    min_coverage_ratio: float = 0.95,
) -> list[str]:
    errors = [
        f"{field} missing"
        for field in REQUIRED_MARKET_FIELDS
        if not str(getattr(manifest, field, "") or "").strip()
    ]
    if manifest.expected_bars <= 0:
        errors.append("expected_bars missing")
    if manifest.actual_bars <= 0:
        errors.append("actual_bars missing")
    if manifest.coverage_ratio < min_coverage_ratio:
        errors.append("coverage_ratio below threshold")
    if manifest.missing_ranges:
        errors.append("missing_ranges present")
    if manifest.source_version and not is_git_commit_sha(manifest.source_version):
        errors.append("source_version is not a git commit SHA")
    errors.extend(manifest.blocking_reasons)
    return errors


def validate_market_manifest(
    manifest: MarketDataManifest,
    *,
    min_coverage_ratio: float = 0.95,
) -> ValidationReport:
    errors = market_manifest_errors(manifest, min_coverage_ratio=min_coverage_ratio)
    if manifest.usable_for_authoritative_validation and errors:
        errors.append("manifest marked authoritative despite contract errors")
    return ValidationReport(
        valid=not errors,
        status=manifest.usability.value,
        errors=errors,
        warnings=[],
    )


def bundle_errors(bundle: DataBundleManifest) -> list[str]:
    errors = list(bundle.authoritative_contract_errors())
    if bundle.status == DataBundleStatus.AUTHORITATIVE and errors:
        errors.append("bundle marked authoritative despite contract errors")
    if bundle.status != DataBundleStatus.AUTHORITATIVE and not bundle.diagnostics_only_reason:
        errors.append("diagnostics_only_reason missing")
    return errors


def validate_bundle(bundle: DataBundleManifest) -> ValidationReport:
    errors = bundle_errors(bundle)
    return ValidationReport(
        valid=not errors,
        status=bundle.status.value,
        errors=errors,
        warnings=[],
    )


def detect_missing_ranges(
    timestamps: Iterable[datetime | pd.Timestamp],
    timeframe: str,
    *,
    tolerance: int = 1,
) -> list[MissingRange]:
    ts = pd.DatetimeIndex(pd.to_datetime(list(timestamps), utc=True)).sort_values().unique()
    if len(ts) < 2:
        return []
    minutes = TIMEFRAME_MINUTES[timeframe.lower()]
    expected_delta = pd.Timedelta(minutes=minutes * tolerance)
    diffs = ts.to_series().diff().dropna()
    missing: list[MissingRange] = []
    for current, delta in diffs[diffs > expected_delta].items():
        previous = ts[ts.get_loc(current) - 1]
        missing.append(
            MissingRange(
                start_ts=(previous + pd.Timedelta(minutes=minutes)).to_pydatetime(),
                end_ts=(current - pd.Timedelta(minutes=minutes)).to_pydatetime(),
                reason=f"gap>{minutes}min",
            )
        )
    return missing


def coverage_counts(
    timestamps: Iterable[datetime | pd.Timestamp],
    timeframe: str,
    calendar: CalendarDefinition,
) -> tuple[int, int, list[MissingRange]]:
    idx = pd.DatetimeIndex(pd.to_datetime(list(timestamps), utc=True)).sort_values().unique()
    if idx.empty:
        return 0, 0, []
    actual = len(idx)
    expected = expected_bars(calendar, timeframe, idx[0].to_pydatetime(), idx[-1].to_pydatetime())
    missing = detect_missing_ranges(idx, timeframe)
    return expected, actual, missing


def report_path(repo_root: Path, command_name: str) -> Path:
    return Path(repo_root) / "data" / "validation_reports" / f"{command_name}.json"
