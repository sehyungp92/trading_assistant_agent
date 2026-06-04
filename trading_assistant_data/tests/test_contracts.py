from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from trading_assistant_data.bundle_builder import (
    build_bundle,
    export_filesystem,
    export_single_slice_coverage,
)
from trading_assistant_data.calendars.core import CalendarDefinition, expected_bars
from trading_assistant_data.checksums import parquet_content_checksum
from trading_assistant_data.io import write_json
from trading_assistant_data.manifests import (
    DataBundleManifest,
    DataBundleSlice,
    DataBundleStatus,
    MarketDataManifest,
    write_model,
)
from trading_assistant_data.normalization import normalize_krx_intraday_frames
from trading_assistant_data.sources.hyperliquid.store import candle_open_from_ms
from trading_assistant_data.sources.kis.read_only_client import KisReadOnlyClient
from trading_assistant_data.transforms.alignment import compare_derived_frame_alignment
from trading_assistant_data.validation import detect_missing_ranges, validate_market_manifest

FIXTURE_DATA_SHA = "a" * 40


def test_market_data_manifest_authoritative_happy_path() -> None:
    manifest = _manifest()

    report = validate_market_manifest(manifest)

    assert report.valid is True
    assert manifest.usable_for_authoritative_validation is True

    from schemas.market_data_manifest import MarketDataManifest as ConsumerManifest

    assert ConsumerManifest.model_validate(manifest.model_dump()).manifest_id == manifest.manifest_id


def test_market_data_manifest_blocks_missing_checksum() -> None:
    manifest = _manifest(checksum="", authoritative=False)

    report = validate_market_manifest(manifest)

    assert report.valid is False
    assert "checksum missing" in report.errors


def test_market_data_manifest_blocks_missing_calendar() -> None:
    manifest = _manifest(session_calendar="", authoritative=False)

    report = validate_market_manifest(manifest)

    assert report.valid is False
    assert "session_calendar missing" in report.errors


def test_data_bundle_manifest_authoritative_happy_path() -> None:
    bundle = _bundle(_manifest())

    assert bundle.status == DataBundleStatus.AUTHORITATIVE
    assert bundle.usable_for_authoritative_validation is True

    from schemas.data_bundle_manifest import DataBundleManifest as ConsumerBundle

    assert ConsumerBundle.model_validate(bundle.model_dump()).bundle_checksum == bundle.bundle_checksum


def test_data_bundle_manifest_diagnostics_only_when_any_slice_is_not_authoritative() -> None:
    manifest = _manifest(authoritative=False, blocking_reasons=["gap"])
    bundle = _bundle(manifest, status=DataBundleStatus.DIAGNOSTICS_ONLY)

    assert bundle.usable_for_authoritative_validation is False
    assert bundle.diagnostics_only_reason


def test_bundle_checksum_changes_when_any_slice_checksum_changes() -> None:
    first = _bundle(_manifest(checksum="sha-a"))
    second = _bundle(_manifest(checksum="sha-b"))

    assert first.bundle_checksum != second.bundle_checksum


@pytest.fixture
def bundle_git_sha(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setattr(
        "trading_assistant_data.bundle_builder.git_commit_exists",
        lambda _repo_root, commit_sha: commit_sha == FIXTURE_DATA_SHA,
    )
    return FIXTURE_DATA_SHA


def test_compatibility_export_matches_filesystem_adapter_layout(tmp_path: Path, bundle_git_sha: str) -> None:
    manifest_path = _write_sample_slice(tmp_path, symbol="BTC", timeframe="1m")
    result = build_bundle(
        repo_root=tmp_path,
        run_month="2026-05",
        bot_id="crypto_portfolio",
        strategy_id="portfolio",
        slice_manifest_paths=[manifest_path],
    )

    export = export_filesystem(
        repo_root=tmp_path,
        run_month="2026-05",
        bundle_manifest_path=result.bundle_path,
    )

    expected = tmp_path / "data/export/filesystem/crypto_perp/BTC/1m/2026-05.parquet"
    assert str(expected) in export["exported"]
    assert expected.exists()


def test_single_slice_coverage_manifest_matches_monthly_default_path(tmp_path: Path, bundle_git_sha: str) -> None:
    manifest_path = _write_sample_slice(tmp_path, symbol="BTC", timeframe="1m")
    result = build_bundle(
        repo_root=tmp_path,
        run_month="2026-05",
        bot_id="crypto_portfolio",
        strategy_id="portfolio",
        slice_manifest_paths=[manifest_path],
    )

    export = export_single_slice_coverage(
        repo_root=tmp_path,
        run_month="2026-05",
        bot_id="crypto_portfolio",
        strategy_id="portfolio",
        bundle_manifest_path=result.bundle_path,
    )

    expected = tmp_path / "data/export/manifests/crypto_portfolio/portfolio/2026-05.coverage_manifest.json"
    assert export["path"] == str(expected)
    assert expected.exists()


def test_single_slice_coverage_manifest_preserves_authority_metadata(tmp_path: Path, bundle_git_sha: str) -> None:
    manifest_path = _write_sample_slice(tmp_path, symbol="ETH", timeframe="5m")
    result = build_bundle(
        repo_root=tmp_path,
        run_month="2026-05",
        bot_id="crypto_portfolio",
        strategy_id="eth_5m",
        slice_manifest_paths=[manifest_path],
    )

    export_single_slice_coverage(
        repo_root=tmp_path,
        run_month="2026-05",
        bot_id="crypto_portfolio",
        strategy_id="eth_5m",
        bundle_manifest_path=result.bundle_path,
    )
    payload = json.loads(
        (tmp_path / "data/export/manifests/crypto_portfolio/eth_5m/2026-05.coverage_manifest.json").read_text()
    )

    assert payload["checksum"]
    assert payload["source_version"] == bundle_git_sha
    assert payload["fee_model_version"] == "fees_v1"
    assert payload["slippage_model_version"] == "slippage_v1"
    assert payload["adjustment_policy"] == "crypto_raw_perp_policy_v1"
    assert payload["usable_for_authoritative_validation"] is True


def test_multi_slice_bundle_does_not_emit_aggregate_market_data_manifest(tmp_path: Path, bundle_git_sha: str) -> None:
    first = _write_sample_slice(tmp_path, symbol="BTC", timeframe="1m")
    second = _write_sample_slice(tmp_path, symbol="ETH", timeframe="1m")
    result = build_bundle(
        repo_root=tmp_path,
        run_month="2026-05",
        bot_id="crypto_portfolio",
        strategy_id="portfolio",
        slice_manifest_paths=[first, second],
    )

    export = export_single_slice_coverage(
        repo_root=tmp_path,
        run_month="2026-05",
        bot_id="crypto_portfolio",
        strategy_id="portfolio",
        bundle_manifest_path=result.bundle_path,
    )

    assert export["status"] == "skipped"
    assert not (tmp_path / "data/export/manifests/crypto_portfolio/portfolio/2026-05.coverage_manifest.json").exists()


def test_build_bundle_diagnostics_only_without_git_commit(tmp_path: Path) -> None:
    manifest_path = _write_sample_slice(tmp_path, symbol="BTC", timeframe="1m")

    result = build_bundle(
        repo_root=tmp_path,
        run_month="2026-05",
        bot_id="crypto_portfolio",
        strategy_id="portfolio",
        slice_manifest_paths=[manifest_path],
    )

    assert result.bundle.status == DataBundleStatus.DIAGNOSTICS_ONLY
    assert result.bundle.data_repo_commit_sha == FIXTURE_DATA_SHA
    assert "commit is not available" in result.bundle.diagnostics_only_reason


def test_build_bundle_requires_explicit_slices_or_requirements(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="requires --slice-manifest or --requirements-file"):
        build_bundle(
            repo_root=tmp_path,
            run_month="2026-05",
            bot_id="crypto_portfolio",
            strategy_id="portfolio",
        )


def test_build_bundle_uses_strategy_requirements_file(tmp_path: Path, bundle_git_sha: str) -> None:
    _write_sample_slice(tmp_path, symbol="BTC", timeframe="1m")
    _write_sample_slice(tmp_path, symbol="ETH", timeframe="1m")
    requirements_path = tmp_path / "requirements.json"
    write_json(
        requirements_path,
        {
            "schema_version": "strategy_data_requirements_v1",
            "requirements": [
                {
                    "source": "hyperliquid",
                    "market": "crypto_perp",
                    "symbol": "BTC",
                    "timeframe": "1m",
                }
            ],
        },
    )

    result = build_bundle(
        repo_root=tmp_path,
        run_month="2026-05",
        bot_id="crypto_portfolio",
        strategy_id="btc_1m",
        requirements_path=requirements_path,
    )

    assert result.bundle.status == DataBundleStatus.AUTHORITATIVE
    assert [item.symbol for item in result.bundle.slice_manifests] == ["BTC"]
    assert result.bundle.data_repo_commit_sha == bundle_git_sha


def test_build_bundle_diagnostics_only_when_policy_versions_mixed(
    tmp_path: Path,
    bundle_git_sha: str,
) -> None:
    first = _write_sample_slice(tmp_path, symbol="BTC", timeframe="1m")
    second = _write_sample_slice(
        tmp_path,
        symbol="ETH",
        timeframe="1m",
        adjustment_policy="crypto_raw_perp_policy_v2",
    )

    result = build_bundle(
        repo_root=tmp_path,
        run_month="2026-05",
        bot_id="crypto_portfolio",
        strategy_id="portfolio",
        slice_manifest_paths=[first, second],
    )

    assert result.bundle.status == DataBundleStatus.DIAGNOSTICS_ONLY
    assert "adjustment_policy mismatch" in result.bundle.diagnostics_only_reason


def test_data_bundle_manifest_can_be_passed_directly_to_monthly_run_manifest(tmp_path: Path) -> None:
    bundle_path = tmp_path / "data_bundle_manifest.json"
    bundle = _bundle(_manifest())
    write_model(bundle_path, bundle)

    from schemas.monthly_run_manifest import MonthlyRunManifest

    run = MonthlyRunManifest(
        run_id="monthly-crypto-portfolio-2026-05",
        run_month="2026-05",
        bot_id="crypto",
        strategy_id="portfolio",
        latest_month_start=date(2026, 5, 1),
        latest_month_end=date(2026, 5, 31),
        market_data_manifest_path=str(bundle_path),
        data_bundle_manifest_path=str(bundle_path),
        data_bundle_checksum=bundle.bundle_checksum,
        telemetry_manifest_path=str(tmp_path / "telemetry.json"),
        artifact_root=str(tmp_path / "artifacts"),
    )

    assert run.data_bundle_manifest_path == str(bundle_path)
    assert run.data_bundle_checksum == bundle.bundle_checksum


def test_crypto_ts_ms_converts_to_utc_open_time() -> None:
    ts = candle_open_from_ms(1776206400000)

    assert ts.tzinfo is not None
    assert ts == pd.Timestamp("2026-04-14T22:40:00Z")


def test_krx_timestamp_policy_requires_exchange_timezone() -> None:
    frame = pd.DataFrame(
        {
            "timestamp": [pd.Timestamp("2026-05-12 09:00:00")],
            "open": [1],
            "high": [1],
            "low": [1],
            "close": [1],
            "volume": [1],
        }
    )

    with pytest.raises(ValueError, match="Asia/Seoul timezone"):
        normalize_krx_intraday_frames([frame], symbol="000100", timeframe="1m")


def test_kis_client_contains_no_order_methods() -> None:
    forbidden = {"buy", "sell", "cancel", "revise", "place_order", "submit_order"}
    method_names = {
        name
        for name in dir(KisReadOnlyClient)
        if callable(getattr(KisReadOnlyClient, name)) and not name.startswith("_")
    }

    assert method_names.isdisjoint(forbidden)


def test_ibkr_alignment_detects_derived_timeframe_mismatch() -> None:
    index = pd.date_range("2026-05-01T00:00:00Z", periods=1, freq="5min")
    derived = pd.DataFrame({"open": [1.0], "high": [2.0], "low": [1.0], "close": [2.0], "volume": [10]}, index=index)
    target = pd.DataFrame({"open": [1.0], "high": [2.0], "low": [1.0], "close": [3.0], "volume": [10]}, index=index)

    result = compare_derived_frame_alignment(
        symbol="NQ",
        derived=derived,
        target=target,
        base_timeframe="1m",
        target_timeframe="5m",
    )

    assert result.status == "MISMATCH"
    assert result.mismatched_rows == 1


def test_duplicate_krx_intraday_files_are_merged_and_deduped() -> None:
    ts = pd.Timestamp("2026-05-12 09:00:00", tz="Asia/Seoul")
    first = pd.DataFrame({"timestamp": [ts], "open": [1], "high": [1], "low": [1], "close": [1], "volume": [1]})
    second = pd.DataFrame({"timestamp": [ts], "open": [2], "high": [2], "low": [2], "close": [2], "volume": [2]})

    out = normalize_krx_intraday_frames([first, second], symbol="000100", timeframe="1m")

    assert len(out) == 1
    assert float(out.iloc[0]["close"]) == 2.0
    assert out.iloc[0]["timestamp_exchange"].endswith("+09:00")


def test_missing_ranges_are_reported() -> None:
    timestamps = [
        datetime(2026, 5, 1, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 5, 1, 0, 1, tzinfo=timezone.utc),
        datetime(2026, 5, 1, 0, 4, tzinfo=timezone.utc),
    ]

    missing = detect_missing_ranges(timestamps, "1m")

    assert len(missing) == 1
    assert missing[0].start_ts.minute == 2
    assert missing[0].end_ts.minute == 3


def test_expected_bars_respect_calendar_holidays() -> None:
    calendar = CalendarDefinition(
        calendar_id="fixture",
        timezone="UTC",
        session_open="09:00",
        session_close="09:02",
        weekdays=(0, 1, 2, 3, 4),
        holidays=frozenset({date(2026, 1, 1)}),
        version="v1",
    )

    count = expected_bars(
        calendar,
        "1m",
        datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 1, 2, 23, 59, tzinfo=timezone.utc),
    )

    assert count == 2


def test_authoritative_bundle_requires_fee_slippage_and_adjustment_versions() -> None:
    with pytest.raises(ValueError, match="authoritative data bundle missing required fields"):
        DataBundleManifest(
            data_repo_path="/tmp/data",
            data_repo_commit_sha="sha",
            slice_manifests=[
                DataBundleSlice(
                    manifest_path="slice.json",
                    manifest_id="slice-1",
                    source="fixture",
                    market="crypto_perp",
                    symbol="BTC",
                    timeframe="1m",
                    checksum="sha",
                    calendar="crypto_utc_24_7_v1",
                    authoritative=True,
                )
            ],
            calendars=["crypto_utc_24_7_v1"],
            status=DataBundleStatus.AUTHORITATIVE,
        )


def _manifest(
    *,
    checksum: str = "slice-sha",
    session_calendar: str = "crypto_utc_24_7_v1",
    symbol: str = "BTC",
    timeframe: str = "1m",
    source_version: str = FIXTURE_DATA_SHA,
    adjustment_policy: str = "crypto_raw_perp_policy_v1",
    fee_model_version: str = "fees_v1",
    slippage_model_version: str = "slippage_v1",
    authoritative: bool = True,
    blocking_reasons: list[str] | None = None,
) -> MarketDataManifest:
    return MarketDataManifest(
        source="hyperliquid",
        market="crypto_perp",
        symbol=symbol,
        timeframe=timeframe,
        start_ts=datetime(2026, 5, 1, 0, 0, tzinfo=timezone.utc),
        end_ts=datetime(2026, 5, 1, 0, 1, tzinfo=timezone.utc),
        expected_bars=2,
        actual_bars=2,
        coverage_ratio=1.0,
        session_calendar=session_calendar,
        timezone="UTC",
        checksum=checksum,
        source_version=source_version,
        adjustment_policy=adjustment_policy,
        fee_model_version=fee_model_version,
        slippage_model_version=slippage_model_version,
        usable_for_authoritative_validation=authoritative,
        blocking_reasons=blocking_reasons or [],
    )


def _bundle(
    manifest: MarketDataManifest,
    *,
    status: DataBundleStatus = DataBundleStatus.AUTHORITATIVE,
) -> DataBundleManifest:
    return DataBundleManifest(
        data_repo_path="/tmp/trading_assistant_data",
        data_repo_commit_sha=FIXTURE_DATA_SHA,
        slice_manifests=[
            DataBundleSlice(
                manifest_path="slice.json",
                manifest_id=manifest.manifest_id,
                source=manifest.source,
                market=manifest.market,
                symbol=manifest.symbol,
                timeframe=manifest.timeframe,
                start_ts=manifest.start_ts,
                end_ts=manifest.end_ts,
                checksum=manifest.checksum,
                calendar=manifest.session_calendar,
                authoritative=manifest.usable_for_authoritative_validation,
            )
        ],
        calendars=[manifest.session_calendar] if manifest.session_calendar else [],
        fee_model_version=manifest.fee_model_version,
        slippage_model_version=manifest.slippage_model_version,
        adjustment_policy=manifest.adjustment_policy,
        status=status,
        diagnostics_only_reason="" if status == DataBundleStatus.AUTHORITATIVE else "not all slices authoritative",
    )


def _write_sample_slice(
    tmp_path: Path,
    *,
    symbol: str,
    timeframe: str,
    adjustment_policy: str = "crypto_raw_perp_policy_v1",
) -> Path:
    frame = pd.DataFrame(
        {
            "timestamp_utc": pd.to_datetime(["2026-05-01T00:00:00Z", "2026-05-01T00:01:00Z"]),
            "timestamp_exchange": ["2026-05-01 00:00:00+00:00", "2026-05-01 00:01:00+00:00"],
            "symbol": [symbol, symbol],
            "market": ["crypto_perp", "crypto_perp"],
            "source": ["hyperliquid", "hyperliquid"],
            "timeframe": [timeframe, timeframe],
            "kind": ["trades", "trades"],
            "open": [1.0, 2.0],
            "high": [1.0, 2.0],
            "low": [1.0, 2.0],
            "close": [1.0, 2.0],
            "volume": [10.0, 20.0],
            "source_file": ["fixture", "fixture"],
            "source_row_hash": ["a", "b"],
        }
    )
    canonical_path = (
        tmp_path
        / "data/canonical/bars/market=crypto_perp/source=hyperliquid/kind=trades"
        / f"symbol={symbol}/timeframe={timeframe}/year=2026/month=05/part.parquet"
    )
    canonical_path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(canonical_path, engine="pyarrow", index=False)
    manifest = _manifest(
        checksum=parquet_content_checksum(canonical_path),
        symbol=symbol,
        timeframe=timeframe,
        adjustment_policy=adjustment_policy,
    )
    manifest_path = (
        tmp_path
        / "data/manifests/slices/hyperliquid/crypto_perp"
        / symbol
        / timeframe
        / "20260501T000000Z_20260501T000100Z.market_data_manifest.json"
    )
    write_model(manifest_path, manifest)
    index_path = tmp_path / "data/manifests/slices/slice_index.json"
    payload = json.loads(index_path.read_text()) if index_path.exists() else {"schema_version": "slice_index_v1", "slices": []}
    entry = {
        "manifest_id": manifest.manifest_id,
        "manifest_path": str(manifest_path.relative_to(tmp_path)).replace("\\", "/"),
        "source": manifest.source,
        "market": manifest.market,
        "symbol": manifest.symbol,
        "timeframe": manifest.timeframe,
        "checksum": manifest.checksum,
        "canonical_paths": [str(canonical_path.relative_to(tmp_path)).replace("\\", "/")],
    }
    payload["slices"] = [item for item in payload["slices"] if item["manifest_id"] != manifest.manifest_id]
    payload["slices"].append(entry)
    write_json(index_path, payload)
    return manifest_path
