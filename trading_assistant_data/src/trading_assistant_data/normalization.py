"""Reference snapshot to canonical parquet normalization."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from .calendars import CalendarDefinition
from .calendars.crypto import calendar_definition as crypto_calendar
from .calendars.krx import calendar_definition as krx_calendar
from .checksums import parquet_content_checksum, stable_row_hashes
from .io import read_json, write_json
from .manifests import MarketDataManifest, write_model
from .repo import git_commit_sha, is_git_commit_sha
from .sources.hyperliquid.store import canonicalize_candles, canonicalize_funding
from .validation import coverage_counts


DEFAULT_FEE_MODEL = "fees_v1"
DEFAULT_SLIPPAGE_MODEL = "slippage_v1"
CRYPTO_ADJUSTMENT_POLICY = "crypto_raw_perp_policy_v1"
CME_ADJUSTMENT_POLICY = "cme_futures_panama_v1"
KRX_ADJUSTMENT_POLICY = "krx_split_adjusted_policy_v1"


@dataclass(frozen=True)
class SliceWrite:
    manifest_path: Path
    canonical_paths: list[Path]
    manifest: MarketDataManifest


def normalize_all(repo_root: Path, *, snapshot: str = "2026-05-30", dry_run: bool = False) -> dict:
    reports = []
    reports.append(normalize_crypto(repo_root, snapshot=snapshot, dry_run=dry_run))
    reports.append(normalize_reference_trading_bars(repo_root, snapshot=snapshot, dry_run=dry_run))
    reports.append(normalize_krx_intraday(repo_root, snapshot=snapshot, dry_run=dry_run))
    return {
        "snapshot": snapshot,
        "dry_run": dry_run,
        "reports": reports,
        "slice_manifest_count": sum(report.get("slice_manifest_count", 0) for report in reports),
    }


def normalize_crypto(repo_root: Path, *, snapshot: str, dry_run: bool = False) -> dict:
    imported = Path(repo_root) / "data" / "imported" / f"reference_snapshot_{snapshot}" / "crypto_trader"
    candles_root = imported / "data" / "candles"
    funding_root = imported / "data" / "funding"
    writes: list[SliceWrite] = []
    errors: list[str] = []
    calendar = crypto_calendar()
    source_version = git_commit_sha(repo_root) or f"reference_snapshot_{snapshot}"

    for source_path in sorted(candles_root.glob("*/*.parquet")):
        symbol = source_path.parent.name.upper()
        interval = source_path.stem
        try:
            source = pd.read_parquet(source_path)
            canonical = canonicalize_candles(
                source,
                symbol=symbol,
                interval=interval,
                source_file=_rel(source_path, repo_root),
            )
            writes.extend(
                _write_bar_partitions_and_manifests(
                    repo_root=repo_root,
                    canonical=canonical,
                    market="crypto_perp",
                    source="hyperliquid",
                    symbol=symbol,
                    timeframe=interval,
                    kind="trades",
                    calendar=calendar,
                    adjustment_policy=CRYPTO_ADJUSTMENT_POLICY,
                    authoritative_allowed=True,
                    source_version=source_version,
                    dry_run=dry_run,
                )
            )
        except Exception as exc:
            errors.append(f"{source_path}: {exc}")

    for source_path in sorted(funding_root.glob("*.parquet")):
        symbol = source_path.stem.upper()
        try:
            source = pd.read_parquet(source_path)
            canonical = canonicalize_funding(
                source,
                symbol=symbol,
                source_file=_rel(source_path, repo_root),
            )
            writes.extend(
                _write_funding_partitions_and_manifests(
                    repo_root=repo_root,
                    canonical=canonical,
                    symbol=symbol,
                    calendar=calendar,
                    source_version=source_version,
                    dry_run=dry_run,
                )
            )
        except Exception as exc:
            errors.append(f"{source_path}: {exc}")

    if not dry_run:
        _update_slice_index(repo_root, writes)
    return {
        "name": "crypto_hyperliquid",
        "dry_run": dry_run,
        "slice_manifest_count": len(writes),
        "errors": errors,
        "manifest_paths": [str(item.manifest_path) for item in writes],
    }


def normalize_reference_trading_bars(repo_root: Path, *, snapshot: str, dry_run: bool = False) -> dict:
    raw_root = Path(repo_root) / "data" / "imported" / f"reference_snapshot_{snapshot}" / "trading" / "data" / "raw"
    writes: list[SliceWrite] = []
    errors: list[str] = []
    skipped: list[str] = []
    source_version = git_commit_sha(repo_root) or f"reference_snapshot_{snapshot}"
    source_paths = sorted(raw_root.glob("*.parquet"))
    available_stems = {path.stem for path in source_paths}
    for source_path in source_paths:
        if _is_duplicate_daily_alias(source_path, available_stems):
            skipped.append(f"{source_path}: duplicate daily alias; using matching 1d file")
            continue
        try:
            symbol, timeframe, kind = _parse_trading_raw_name(source_path.stem)
            source = pd.read_parquet(source_path)
            canonical = canonicalize_ohlcv_frame(
                source,
                symbol=symbol,
                market="cme_futures",
                source="ibkr",
                timeframe=timeframe,
                kind=kind,
                source_file=_rel(source_path, repo_root),
            )
            writes.extend(
                _write_bar_partitions_and_manifests(
                    repo_root=repo_root,
                    canonical=canonical,
                    market="cme_futures",
                    source="ibkr",
                    symbol=symbol,
                    timeframe=timeframe,
                    kind=kind,
                    calendar=None,
                    adjustment_policy=CME_ADJUSTMENT_POLICY,
                    authoritative_allowed=False,
                    source_version=source_version,
                    dry_run=dry_run,
                    extra_blocking_reasons=["CME session/roll authority requires final exchange calendar and roll checksum"],
                )
            )
        except Exception as exc:
            errors.append(f"{source_path}: {exc}")
    if not dry_run:
        _update_slice_index(repo_root, writes)
    return {
        "name": "trading_ibkr_raw",
        "dry_run": dry_run,
        "slice_manifest_count": len(writes),
        "errors": errors,
        "skipped": skipped,
        "manifest_paths": [str(item.manifest_path) for item in writes],
    }


def normalize_krx_intraday(repo_root: Path, *, snapshot: str, dry_run: bool = False) -> dict:
    source_root = (
        Path(repo_root)
        / "data"
        / "imported"
        / f"reference_snapshot_{snapshot}"
        / "k_stock_trader"
        / "data"
        / "kis_intraday_parquet"
    )
    writes: list[SliceWrite] = []
    errors: list[str] = []
    source_version = git_commit_sha(repo_root) or f"reference_snapshot_{snapshot}"
    grouped: dict[tuple[str, str], list[Path]] = {}
    for path in sorted(source_root.rglob("*.parquet")):
        parts = path.stem.split("_")
        if len(parts) < 2:
            continue
        grouped.setdefault((parts[0], parts[1]), []).append(path)

    holiday_path = Path(repo_root) / "data" / "calendars" / "krx_holidays.yaml"
    calendar = krx_calendar(holiday_path if holiday_path.exists() else None)
    for (symbol, timeframe), paths in grouped.items():
        try:
            frames = [pd.read_parquet(path) for path in paths]
            canonical = normalize_krx_intraday_frames(
                frames,
                symbol=symbol,
                timeframe=timeframe,
                source_files=[_rel(path, repo_root) for path in paths],
            )
            writes.extend(
                _write_bar_partitions_and_manifests(
                    repo_root=repo_root,
                    canonical=canonical,
                    market="krx_equity",
                    source="kis",
                    symbol=symbol,
                    timeframe=timeframe,
                    kind="trades",
                    calendar=calendar,
                    adjustment_policy=KRX_ADJUSTMENT_POLICY,
                    authoritative_allowed=False,
                    source_version=source_version,
                    dry_run=dry_run,
                    extra_blocking_reasons=["KRX intraday timestamp/session audit required before authority"],
                )
            )
        except Exception as exc:
            errors.append(f"{symbol} {timeframe}: {exc}")
    if not dry_run:
        _update_slice_index(repo_root, writes)
    return {
        "name": "krx_kis_intraday",
        "dry_run": dry_run,
        "slice_manifest_count": len(writes),
        "errors": errors,
        "manifest_paths": [str(item.manifest_path) for item in writes],
    }


def canonicalize_ohlcv_frame(
    frame: pd.DataFrame,
    *,
    symbol: str,
    market: str,
    source: str,
    timeframe: str,
    kind: str,
    source_file: str,
) -> pd.DataFrame:
    source_frame = frame.copy()
    if "timestamp_utc" in source_frame.columns:
        timestamp = pd.to_datetime(source_frame["timestamp_utc"], utc=True)
    elif "timestamp" in source_frame.columns:
        timestamp = pd.to_datetime(source_frame["timestamp"], utc=True)
    elif "time" in source_frame.columns:
        timestamp = pd.to_datetime(source_frame["time"], utc=True)
    else:
        timestamp = pd.to_datetime(source_frame.index, utc=True)
    out = pd.DataFrame(
        {
            "timestamp_utc": timestamp,
            "timestamp_exchange": timestamp.astype(str),
            "symbol": symbol.upper(),
            "market": market,
            "source": source,
            "timeframe": timeframe,
            "kind": kind,
            "open": source_frame["open"].astype("float64"),
            "high": source_frame["high"].astype("float64"),
            "low": source_frame["low"].astype("float64"),
            "close": source_frame["close"].astype("float64"),
            "volume": source_frame["volume"].astype("float64"),
            "source_file": source_file,
        }
    )
    for optional in ("bar_count", "wap", "is_RTH", "is_rth"):
        if optional in source_frame.columns:
            target = "is_rth" if optional == "is_RTH" else optional
            out[target] = source_frame[optional]
    out["source_row_hash"] = stable_row_hashes(source_frame.reset_index(drop=False))
    return out.sort_values("timestamp_utc").drop_duplicates("timestamp_utc", keep="last")


def normalize_krx_intraday_frames(
    frames: list[pd.DataFrame],
    *,
    symbol: str,
    timeframe: str,
    source_files: list[str] | None = None,
) -> pd.DataFrame:
    if not frames:
        return pd.DataFrame()
    source_files = source_files or [""] * len(frames)
    canonical_frames: list[pd.DataFrame] = []
    tz = ZoneInfo("Asia/Seoul")
    for frame, source_file in zip(frames, source_files):
        if "timestamp" not in frame.columns:
            raise ValueError("KRX intraday frame requires timestamp column")
        timestamp = pd.to_datetime(frame["timestamp"])
        if timestamp.dt.tz is None:
            raise ValueError("KRX intraday timestamp must include Asia/Seoul timezone")
        exchange = timestamp.dt.tz_convert(tz)
        utc = exchange.dt.tz_convert("UTC")
        out = pd.DataFrame(
            {
                "timestamp_utc": utc,
                "timestamp_exchange": exchange.astype(str),
                "symbol": symbol.zfill(6),
                "market": "krx_equity",
                "source": "kis",
                "timeframe": timeframe,
                "kind": "trades",
                "open": frame["open"].astype("float64"),
                "high": frame["high"].astype("float64"),
                "low": frame["low"].astype("float64"),
                "close": frame["close"].astype("float64"),
                "volume": frame["volume"].astype("float64"),
                "source_file": source_file,
            }
        )
        out["source_row_hash"] = stable_row_hashes(frame.reset_index(drop=False))
        canonical_frames.append(out)
    merged = pd.concat(canonical_frames, ignore_index=True)
    return merged.sort_values("timestamp_utc").drop_duplicates("timestamp_utc", keep="last")


def _write_bar_partitions_and_manifests(
    *,
    repo_root: Path,
    canonical: pd.DataFrame,
    market: str,
    source: str,
    symbol: str,
    timeframe: str,
    kind: str,
    calendar: CalendarDefinition | None,
    adjustment_policy: str,
    authoritative_allowed: bool,
    source_version: str,
    dry_run: bool,
    extra_blocking_reasons: list[str] | None = None,
) -> list[SliceWrite]:
    if canonical.empty:
        return []
    paths: list[Path] = []
    frame = canonical.assign(
        year=canonical["timestamp_utc"].dt.year.astype(str),
        month=canonical["timestamp_utc"].dt.month.map(lambda value: f"{int(value):02d}"),
    )
    writes: list[SliceWrite] = []
    for (year, month), group in frame.groupby(["year", "month"], sort=True):
        path = (
            Path(repo_root)
            / "data"
            / "canonical"
            / "bars"
            / f"market={market}"
            / f"source={source}"
            / f"kind={kind}"
            / f"symbol={symbol.upper()}"
            / f"timeframe={timeframe}"
            / f"year={year}"
            / f"month={month}"
            / "part.parquet"
        )
        paths = [path]
        output = group.drop(columns=["year", "month"])
        if not dry_run:
            path.parent.mkdir(parents=True, exist_ok=True)
            output.to_parquet(path, engine="pyarrow", index=False)
        writes.append(
            _manifest_for_partition(
                repo_root=repo_root,
                canonical_paths=paths,
                frame=output,
                source=source,
                market=market,
                symbol=symbol.upper(),
                timeframe=timeframe,
                calendar=calendar,
                adjustment_policy=adjustment_policy,
                authoritative_allowed=authoritative_allowed,
                source_version=source_version,
                dry_run=dry_run,
                extra_blocking_reasons=extra_blocking_reasons,
            )
        )
    return writes


def _write_funding_partitions_and_manifests(
    *,
    repo_root: Path,
    canonical: pd.DataFrame,
    symbol: str,
    calendar: CalendarDefinition,
    source_version: str,
    dry_run: bool,
) -> list[SliceWrite]:
    if canonical.empty:
        return []
    writes: list[SliceWrite] = []
    frame = canonical.assign(
        year=canonical["timestamp_utc"].dt.year.astype(str),
        month=canonical["timestamp_utc"].dt.month.map(lambda value: f"{int(value):02d}"),
    )
    for (year, month), group in frame.groupby(["year", "month"], sort=True):
        path = (
            Path(repo_root)
            / "data"
            / "canonical"
            / "funding"
            / "market=crypto_perp"
            / "source=hyperliquid"
            / f"symbol={symbol.upper()}"
            / f"year={year}"
            / f"month={month}"
            / "part.parquet"
        )
        output = group.drop(columns=["year", "month"])
        if not dry_run:
            path.parent.mkdir(parents=True, exist_ok=True)
            output.to_parquet(path, engine="pyarrow", index=False)
        writes.append(
            _manifest_for_partition(
                repo_root=repo_root,
                canonical_paths=[path],
                frame=output,
                source="hyperliquid",
                market="crypto_perp",
                symbol=symbol.upper(),
                timeframe="funding_8h",
                calendar=calendar,
                adjustment_policy=CRYPTO_ADJUSTMENT_POLICY,
                authoritative_allowed=True,
                source_version=source_version,
                dry_run=dry_run,
            )
        )
    return writes


def _manifest_for_partition(
    *,
    repo_root: Path,
    canonical_paths: list[Path],
    frame: pd.DataFrame,
    source: str,
    market: str,
    symbol: str,
    timeframe: str,
    calendar: CalendarDefinition | None,
    adjustment_policy: str,
    authoritative_allowed: bool,
    source_version: str,
    dry_run: bool,
    extra_blocking_reasons: list[str] | None = None,
) -> SliceWrite:
    start = pd.Timestamp(frame["timestamp_utc"].min()).to_pydatetime()
    end = pd.Timestamp(frame["timestamp_utc"].max()).to_pydatetime()
    if calendar is None:
        expected = len(frame)
        actual = len(frame)
        missing = []
        session_calendar = ""
        timezone_name = "UTC"
    else:
        expected, actual, missing = coverage_counts(frame["timestamp_utc"], timeframe, calendar)
        session_calendar = calendar.calendar_id
        timezone_name = calendar.timezone
    blocking_reasons = list(extra_blocking_reasons or [])
    if calendar is None:
        blocking_reasons.append("session calendar missing")
    if missing:
        blocking_reasons.append("missing ranges present")
    if not is_git_commit_sha(source_version):
        blocking_reasons.append("source_version is not a data repo commit SHA")
    checksum = "" if dry_run else parquet_content_checksum(canonical_paths[0])
    if not checksum:
        blocking_reasons.append("checksum missing")
    authoritative = (
        authoritative_allowed
        and not blocking_reasons
        and expected > 0
        and actual > 0
        and (actual / expected if expected else 0.0) >= 0.95
    )
    manifest = MarketDataManifest(
        source=source,
        market=market,
        symbol=symbol,
        timeframe=timeframe,
        start_ts=start,
        end_ts=end,
        expected_bars=expected,
        actual_bars=actual,
        coverage_ratio=(actual / expected if expected else 0.0),
        missing_ranges=missing,
        session_calendar=session_calendar,
        timezone=timezone_name,
        checksum=checksum,
        source_version=source_version,
        adjustment_policy=adjustment_policy,
        fee_model_version=DEFAULT_FEE_MODEL,
        slippage_model_version=DEFAULT_SLIPPAGE_MODEL,
        usable_for_authoritative_validation=authoritative,
        blocking_reasons=blocking_reasons,
    )
    manifest_path = _slice_manifest_path(repo_root, manifest)
    if not dry_run:
        write_model(manifest_path, manifest)
    return SliceWrite(manifest_path=manifest_path, canonical_paths=canonical_paths, manifest=manifest)


def _slice_manifest_path(repo_root: Path, manifest: MarketDataManifest) -> Path:
    start = manifest.start_ts.strftime("%Y%m%dT%H%M%SZ")
    end = manifest.end_ts.strftime("%Y%m%dT%H%M%SZ")
    return (
        Path(repo_root)
        / "data"
        / "manifests"
        / "slices"
        / manifest.source
        / manifest.market
        / manifest.symbol
        / manifest.timeframe
        / f"{start}_{end}.market_data_manifest.json"
    )


def _update_slice_index(
    repo_root: Path,
    writes: list[SliceWrite],
) -> None:
    if not writes:
        return
    index_path = Path(repo_root) / "data" / "manifests" / "slices" / "slice_index.json"
    if index_path.exists():
        try:
            payload = read_json(index_path)
        except ValueError:
            payload = {"schema_version": "slice_index_v1", "slices": []}
    else:
        payload = {"schema_version": "slice_index_v1", "slices": []}
    entries_by_id = {}
    for write in writes:
        manifest = write.manifest
        entries_by_id[manifest.manifest_id] = {
            "manifest_id": manifest.manifest_id,
            "manifest_path": _rel(write.manifest_path, repo_root),
            "source": manifest.source,
            "market": manifest.market,
            "symbol": manifest.symbol,
            "timeframe": manifest.timeframe,
            "checksum": manifest.checksum,
            "canonical_paths": [_rel(path, repo_root) for path in write.canonical_paths],
        }
    entries = list(entries_by_id.values())
    manifest_ids = {entry["manifest_id"] for entry in entries}
    manifest_paths = {entry["manifest_path"] for entry in entries}
    payload["slices"] = [
        item
        for item in payload.get("slices", [])
        if item.get("manifest_id") not in manifest_ids
        and item.get("manifest_path") not in manifest_paths
    ]
    payload["slices"].extend(entries)
    by_manifest_path = {}
    for item in payload["slices"]:
        by_manifest_path[item["manifest_path"]] = item
    payload["slices"] = list(by_manifest_path.values())
    payload["slices"].sort(key=lambda item: (item["source"], item["market"], item["symbol"], item["timeframe"], item["manifest_path"]))
    write_json(index_path, payload)


def _parse_trading_raw_name(stem: str) -> tuple[str, str, str]:
    parts = stem.split("_")
    symbol = parts[0].upper()
    if parts[-2:] == ["bid", "ask"]:
        timeframe = f"{parts[1]}_bid_ask"
        kind = "bid_ask"
    else:
        timeframe = parts[1] if len(parts) > 1 else "1d"
        if timeframe == "daily":
            timeframe = "1d"
        kind = "trades"
    return symbol, timeframe, kind


def _is_duplicate_daily_alias(path: Path, available_stems: set[str]) -> bool:
    parts = path.stem.split("_")
    return len(parts) == 2 and parts[1] == "daily" and f"{parts[0]}_1d" in available_stems


def _rel(path: Path, root: Path) -> str:
    try:
        return str(Path(path).resolve().relative_to(Path(root).resolve())).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")
