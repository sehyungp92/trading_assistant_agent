"""Build monthly data bundles and compatibility exports."""

from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yaml

from .io import read_json, write_json
from .manifests import (
    DataBundleManifest,
    DataBundleSlice,
    DataBundleStatus,
    MarketDataManifest,
    load_bundle_manifest,
    load_market_manifest,
    write_model,
)
from .normalization import DEFAULT_FEE_MODEL, DEFAULT_SLIPPAGE_MODEL
from .repo import git_branch, git_commit_exists, is_git_commit_sha


@dataclass(frozen=True)
class BundleBuildResult:
    bundle_path: Path
    slice_index_path: Path
    bundle: DataBundleManifest
    canonical_paths: list[Path]


def build_bundle(
    *,
    repo_root: Path,
    run_month: str,
    bot_id: str,
    strategy_id: str,
    slice_manifest_paths: list[Path] | None = None,
    requirements_path: Path | None = None,
    dry_run: bool = False,
) -> BundleBuildResult:
    if not slice_manifest_paths and requirements_path is None:
        raise ValueError("build-bundle requires --slice-manifest or --requirements-file")
    manifests = _select_slice_manifests(repo_root, run_month, slice_manifest_paths, requirements_path)
    if not manifests:
        raise ValueError(f"no slice manifests found for run month {run_month}")
    data_commit_sha, source_errors = _common_source_version(repo_root, manifests)
    slices = [
        DataBundleSlice(
            manifest_path=_rel(path, repo_root),
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
        for path, manifest in manifests
    ]
    fee_model_version, fee_errors = _single_policy_value(
        [manifest.fee_model_version for _path, manifest in manifests],
        field_name="fee_model_version",
        default=DEFAULT_FEE_MODEL,
    )
    slippage_model_version, slippage_errors = _single_policy_value(
        [manifest.slippage_model_version for _path, manifest in manifests],
        field_name="slippage_model_version",
        default=DEFAULT_SLIPPAGE_MODEL,
    )
    adjustment_policy, adjustment_errors = _single_policy_value(
        [manifest.adjustment_policy for _path, manifest in manifests],
        field_name="adjustment_policy",
        default="mixed_adjustment_policy",
    )
    blocking_reasons = [
        *source_errors,
        *_non_authoritative_slice_reasons(manifests),
        *fee_errors,
        *slippage_errors,
        *adjustment_errors,
    ]
    status = DataBundleStatus.AUTHORITATIVE if not blocking_reasons else DataBundleStatus.DIAGNOSTICS_ONLY
    diagnostics = "; ".join(blocking_reasons)
    bundle = DataBundleManifest(
        data_repo_path=str(Path(repo_root).resolve()),
        data_repo_commit_sha=data_commit_sha,
        data_repo_branch=git_branch(repo_root),
        slice_manifests=slices,
        calendars=sorted({item.calendar for item in slices if item.calendar}),
        fee_model_version=fee_model_version,
        slippage_model_version=slippage_model_version,
        adjustment_policy=adjustment_policy,
        status=status,
        diagnostics_only_reason=diagnostics,
    )
    bundle_root = Path(repo_root) / "data" / "bundles" / "monthly" / run_month / bot_id / strategy_id
    bundle_path = bundle_root / "data_bundle_manifest.json"
    slice_index_path = bundle_root / "slice_index.json"
    canonical_paths = _canonical_paths_for_manifests(repo_root, [manifest.manifest_id for _path, manifest in manifests])
    if not dry_run:
        write_model(bundle_path, bundle)
        write_json(
            slice_index_path,
            {
                "schema_version": "bundle_slice_index_v1",
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "bundle_checksum": bundle.bundle_checksum,
                "slices": [
                    {
                        "manifest_id": manifest.manifest_id,
                        "manifest_path": _rel(path, repo_root),
                        "canonical_paths": [
                            _rel(canonical_path, repo_root)
                            for canonical_path in _canonical_paths_for_manifests(repo_root, [manifest.manifest_id])
                        ],
                    }
                    for path, manifest in manifests
                ],
            },
        )
    return BundleBuildResult(
        bundle_path=bundle_path,
        slice_index_path=slice_index_path,
        bundle=bundle,
        canonical_paths=canonical_paths,
    )


def export_filesystem(
    *,
    repo_root: Path,
    run_month: str,
    bundle_manifest_path: Path | None = None,
    dry_run: bool = False,
) -> dict:
    bundle_path = bundle_manifest_path or _latest_bundle_for_month(repo_root, run_month)
    bundle = load_bundle_manifest(bundle_path)
    exported: list[str] = []
    slice_index = read_json(Path(bundle_path).with_name("slice_index.json"))
    by_id = {item["manifest_id"]: item for item in slice_index.get("slices", [])}
    for item in bundle.slice_manifests:
        if item.timeframe == "funding_8h":
            continue
        index_entry = by_id.get(item.manifest_id, {})
        canonical_paths = [Path(repo_root) / path for path in index_entry.get("canonical_paths", [])]
        if not canonical_paths:
            canonical_paths = _canonical_paths_for_manifests(repo_root, [item.manifest_id])
        frames = [pd.read_parquet(path) for path in canonical_paths if path.exists()]
        if not frames:
            continue
        frame = pd.concat(frames, ignore_index=True).sort_values("timestamp_utc")
        output_path = (
            Path(repo_root)
            / "data"
            / "export"
            / "filesystem"
            / item.market
            / item.symbol
            / item.timeframe
            / f"{run_month}.parquet"
        )
        exported.append(str(output_path))
        if dry_run:
            continue
        output_path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(output_path, engine="pyarrow", index=False)
    return {
        "bundle_manifest_path": str(bundle_path),
        "run_month": run_month,
        "exported": exported,
        "dry_run": dry_run,
    }


def export_single_slice_coverage(
    *,
    repo_root: Path,
    run_month: str,
    bot_id: str,
    strategy_id: str,
    bundle_manifest_path: Path | None = None,
    dry_run: bool = False,
) -> dict:
    bundle_path = bundle_manifest_path or _latest_bundle_for_month(repo_root, run_month)
    bundle = load_bundle_manifest(bundle_path)
    output_path = (
        Path(repo_root)
        / "data"
        / "export"
        / "manifests"
        / bot_id
        / strategy_id
        / f"{run_month}.coverage_manifest.json"
    )
    if len(bundle.slice_manifests) != 1:
        return {
            "status": "skipped",
            "reason": "bundle contains multiple slices; direct DataBundleManifest handoff required",
            "path": str(output_path),
        }
    slice_item = bundle.slice_manifests[0]
    manifest_path = Path(repo_root) / slice_item.manifest_path
    manifest = load_market_manifest(manifest_path)
    if bundle.status != DataBundleStatus.AUTHORITATIVE:
        manifest.usable_for_authoritative_validation = False
        reasons = list(manifest.blocking_reasons)
        reasons.append(f"bundle is {bundle.status.value}: {bundle.diagnostics_only_reason}")
        manifest.blocking_reasons = reasons
    if not dry_run:
        write_model(output_path, manifest)
    return {
        "status": "written" if not dry_run else "planned",
        "path": str(output_path),
        "manifest_id": manifest.manifest_id,
        "bundle_checksum": bundle.bundle_checksum,
        "dry_run": dry_run,
    }


def audit_coverage(repo_root: Path, *, run_month: str) -> dict:
    manifests = _select_slice_manifests(repo_root, run_month, None, None)
    return {
        "run_month": run_month,
        "slice_count": len(manifests),
        "authoritative_count": sum(1 for _path, item in manifests if item.usable_for_authoritative_validation),
        "diagnostics_only": [
            {
                "manifest_path": _rel(path, repo_root),
                "symbol": item.symbol,
                "timeframe": item.timeframe,
                "blocking_reasons": item.blocking_reasons,
            }
            for path, item in manifests
            if not item.usable_for_authoritative_validation
        ],
    }


def _select_slice_manifests(
    repo_root: Path,
    run_month: str,
    slice_manifest_paths: list[Path] | None,
    requirements_path: Path | None,
) -> list[tuple[Path, MarketDataManifest]]:
    if slice_manifest_paths:
        candidates = [Path(path) if Path(path).is_absolute() else Path(repo_root) / path for path in slice_manifest_paths]
    else:
        candidates = sorted((Path(repo_root) / "data" / "manifests" / "slices").rglob("*.market_data_manifest.json"))
    requirements = _load_bundle_requirements(repo_root, requirements_path)
    month_start, month_end = _month_window(run_month)
    selected: list[tuple[Path, MarketDataManifest]] = []
    for path in candidates:
        manifest = load_market_manifest(path)
        if manifest.end_ts < month_start or manifest.start_ts > month_end:
            continue
        if requirements and not _matches_any_requirement(manifest, requirements):
            continue
        selected.append((path, manifest))
    selected.sort(key=lambda item: (item[1].source, item[1].market, item[1].symbol, item[1].timeframe))
    return selected


def _canonical_paths_for_manifests(repo_root: Path, manifest_ids: list[str]) -> list[Path]:
    index_path = Path(repo_root) / "data" / "manifests" / "slices" / "slice_index.json"
    if not index_path.exists():
        return []
    index = read_json(index_path)
    wanted = set(manifest_ids)
    paths: list[Path] = []
    for item in index.get("slices", []):
        if item.get("manifest_id") in wanted:
            paths.extend(Path(repo_root) / path for path in item.get("canonical_paths", []))
    return paths


def _latest_bundle_for_month(repo_root: Path, run_month: str) -> Path:
    candidates = sorted(
        (Path(repo_root) / "data" / "bundles" / "monthly" / run_month).rglob("data_bundle_manifest.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        raise FileNotFoundError(f"no data bundle manifest found for {run_month}")
    return candidates[0]


def _month_window(run_month: str) -> tuple[datetime, datetime]:
    year, month = (int(part) for part in run_month.split("-", 1))
    last_day = monthrange(year, month)[1]
    return (
        datetime(year, month, 1, tzinfo=timezone.utc),
        datetime(year, month, last_day, 23, 59, 59, tzinfo=timezone.utc),
    )


def _single_policy_value(values: list[str], *, field_name: str, default: str) -> tuple[str, list[str]]:
    cleaned = sorted({value for value in values if value})
    if len(cleaned) == 1:
        return cleaned[0], []
    if not cleaned:
        return default, [f"{field_name} missing across bundle"]
    return ",".join(cleaned), [f"{field_name} mismatch across bundle: {','.join(cleaned)}"]


def _common_source_version(
    repo_root: Path,
    manifests: list[tuple[Path, MarketDataManifest]],
) -> tuple[str, list[str]]:
    versions = sorted({manifest.source_version for _path, manifest in manifests if manifest.source_version})
    if len(versions) != 1:
        return "", ["slice source_version missing or mixed across bundle"]
    version = versions[0]
    if not is_git_commit_sha(version):
        return "", [f"slice source_version is not a git commit SHA: {version}"]
    if not git_commit_exists(repo_root, version):
        return version, [f"slice source_version commit is not available in this data repo: {version}"]
    return version, []


def _non_authoritative_slice_reasons(manifests: list[tuple[Path, MarketDataManifest]]) -> list[str]:
    reasons = [
        f"{manifest.symbol}:{manifest.timeframe}:{','.join(manifest.blocking_reasons or ['not authoritative'])}"
        for _path, manifest in manifests
        if not manifest.usable_for_authoritative_validation
    ]
    return [f"non-authoritative slices: {'; '.join(reasons)}"] if reasons else []


def _load_bundle_requirements(repo_root: Path, requirements_path: Path | None) -> list[dict[str, str]]:
    if requirements_path is None:
        return []
    path = Path(requirements_path)
    if not path.is_absolute():
        path = Path(repo_root) / path
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"requirements file must contain an object: {path}")
    raw_requirements = payload.get("requirements") or payload.get("slices") or []
    if not isinstance(raw_requirements, list) or not raw_requirements:
        raise ValueError(f"requirements file has no requirements: {path}")
    requirements: list[dict[str, str]] = []
    for item in raw_requirements:
        if not isinstance(item, dict):
            raise ValueError(f"requirement entry must be an object: {path}")
        requirement = {
            key: str(item.get(key, "")).strip()
            for key in ("source", "market", "symbol", "timeframe")
        }
        missing = [key for key, value in requirement.items() if not value]
        if missing:
            raise ValueError(f"requirement missing fields {missing}: {path}")
        requirement["symbol"] = requirement["symbol"].upper()
        requirements.append(requirement)
    return requirements


def _matches_any_requirement(manifest: MarketDataManifest, requirements: list[dict[str, str]]) -> bool:
    return any(
        manifest.source == requirement["source"]
        and manifest.market == requirement["market"]
        and manifest.symbol.upper() == requirement["symbol"]
        and manifest.timeframe == requirement["timeframe"]
        for requirement in requirements
    )


def _rel(path: Path, root: Path) -> str:
    try:
        return str(Path(path).resolve().relative_to(Path(root).resolve())).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")
