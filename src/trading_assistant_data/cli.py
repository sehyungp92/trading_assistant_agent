"""Command-line interface for trading_assistant_data."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .authority import finalize_slice_manifests
from .bundle_builder import (
    audit_coverage,
    build_bundle,
    export_filesystem,
    export_single_slice_coverage,
)
from .importer import import_reference_snapshot
from .io import write_json
from .manifests import load_market_manifest
from .normalization import normalize_all, normalize_crypto, normalize_krx_intraday, normalize_reference_trading_bars
from .repo import resolve_repo_root
from .validation import report_path, validate_bundle, validate_market_manifest


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 0
    try:
        payload = args.func(args)
        _emit(args, payload)
        return 0
    except Exception as exc:
        payload = {"ok": False, "error": str(exc)}
        _emit(args, payload, stderr=True)
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="trading_assistant_data")
    parser.add_argument("--repo-root", type=Path, default=None)
    sub = parser.add_subparsers(dest="command")

    import_ref = sub.add_parser("import-reference", help="Copy raw reference snapshots into data/imported")
    _common(import_ref)
    import_ref.add_argument("--snapshot", required=True)
    import_ref.add_argument("--references-root", type=Path, required=True)
    import_ref.set_defaults(func=_cmd_import_reference)

    normalize = sub.add_parser("normalize", help="Normalize imported snapshots into canonical parquet")
    _common(normalize)
    normalize.add_argument("--snapshot", default="2026-05-30")
    normalize.add_argument("--all", action="store_true")
    normalize.add_argument("--crypto", action="store_true")
    normalize.add_argument("--ibkr", action="store_true")
    normalize.add_argument("--krx-intraday", action="store_true")
    normalize.set_defaults(func=_cmd_normalize)

    sync = sub.add_parser("sync", help="Source-specific live sync entry points")
    sync_sub = sync.add_subparsers(dest="source", required=True)
    for name in ("ibkr", "hyperliquid", "kis"):
        child = sync_sub.add_parser(name)
        _common(child)
        child.add_argument("--families", default="")
        child.add_argument("--symbols", default="")
        child.add_argument("--symbols-file", type=Path, default=None)
        child.add_argument("--intervals", default="")
        child.add_argument("--years", type=int, default=0)
        child.add_argument("--latest", action="store_true")
        child.add_argument("--funding", action="store_true")
        child.add_argument("--daily", action="store_true")
        child.add_argument("--intraday", action="store_true")
        child.set_defaults(func=_cmd_sync)

    validate_slice = sub.add_parser("validate-slice", help="Validate one MarketDataManifest")
    _common(validate_slice)
    validate_slice.add_argument("--manifest", type=Path, required=True)
    validate_slice.set_defaults(func=_cmd_validate_slice)

    finalize = sub.add_parser("finalize-slices", help="Finalize slice manifests against a committed data snapshot")
    _common(finalize)
    finalize.add_argument("--run-month", required=True)
    finalize.add_argument("--slice-manifest", action="append", type=Path, default=[])
    finalize.add_argument("--requirements-file", type=Path, default=None)
    finalize.add_argument("--data-commit-sha", default="")
    finalize.set_defaults(func=_cmd_finalize_slices)

    build = sub.add_parser("build-bundle", help="Build a monthly DataBundleManifest")
    _common(build)
    build.add_argument("--run-month", required=True)
    build.add_argument("--bot-id", required=True)
    build.add_argument("--strategy-id", required=True)
    build.add_argument("--slice-manifest", action="append", type=Path, default=[])
    build.add_argument("--requirements-file", type=Path, default=None)
    build.set_defaults(func=_cmd_build_bundle)

    export = sub.add_parser("export-filesystem", help="Write FileSystemParquetAdapter exports")
    _common(export)
    export.add_argument("--run-month", required=True)
    export.add_argument("--bundle-manifest", type=Path, default=None)
    export.set_defaults(func=_cmd_export_filesystem)

    export_cov = sub.add_parser("export-single-slice-coverage", help="Write default monthly coverage manifest")
    _common(export_cov)
    export_cov.add_argument("--run-month", required=True)
    export_cov.add_argument("--bot-id", required=True)
    export_cov.add_argument("--strategy-id", required=True)
    export_cov.add_argument("--bundle-manifest", type=Path, default=None)
    export_cov.set_defaults(func=_cmd_export_single_slice)

    audit = sub.add_parser("audit-coverage", help="Summarize monthly slice authority")
    _common(audit)
    audit.add_argument("--run-month", required=True)
    audit.set_defaults(func=_cmd_audit_coverage)
    return parser


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true", dest="json_output")


def _repo(args: argparse.Namespace) -> Path:
    return resolve_repo_root(args.repo_root)


def _cmd_import_reference(args: argparse.Namespace) -> dict[str, Any]:
    repo_root = _repo(args)
    payload = import_reference_snapshot(
        repo_root=repo_root,
        snapshot=args.snapshot,
        references_root=args.references_root,
        dry_run=args.dry_run,
    )
    _write_report(repo_root, "import-reference", payload)
    return payload


def _cmd_normalize(args: argparse.Namespace) -> dict[str, Any]:
    repo_root = _repo(args)
    selected = args.all or not (args.crypto or args.ibkr or args.krx_intraday)
    if selected:
        payload = normalize_all(repo_root, snapshot=args.snapshot, dry_run=args.dry_run)
    else:
        reports = []
        if args.crypto:
            reports.append(normalize_crypto(repo_root, snapshot=args.snapshot, dry_run=args.dry_run))
        if args.ibkr:
            reports.append(normalize_reference_trading_bars(repo_root, snapshot=args.snapshot, dry_run=args.dry_run))
        if args.krx_intraday:
            reports.append(normalize_krx_intraday(repo_root, snapshot=args.snapshot, dry_run=args.dry_run))
        payload = {"snapshot": args.snapshot, "dry_run": args.dry_run, "reports": reports}
    _write_report(repo_root, "normalize", payload)
    _raise_on_report_errors(payload)
    return payload


def _cmd_sync(args: argparse.Namespace) -> dict[str, Any]:
    repo_root = _repo(args)
    payload = {
        "source": args.source,
        "dry_run": args.dry_run,
        "status": "planned" if args.dry_run else "blocked",
        "reason": "live sync adapters are scaffolded; credentials/network refresh is intentionally not run by default",
        "options": {
            "families": args.families,
            "symbols": args.symbols,
            "symbols_file": str(args.symbols_file) if args.symbols_file else "",
            "intervals": args.intervals,
            "years": args.years,
            "latest": args.latest,
            "funding": args.funding,
            "daily": args.daily,
            "intraday": args.intraday,
        },
    }
    _write_report(repo_root, f"sync-{args.source}", payload)
    if not args.dry_run:
        raise RuntimeError(payload["reason"])
    return payload


def _cmd_validate_slice(args: argparse.Namespace) -> dict[str, Any]:
    repo_root = _repo(args)
    manifest = load_market_manifest(args.manifest)
    report = validate_market_manifest(manifest).to_dict()
    payload = {"manifest": str(args.manifest), **report}
    _write_report(repo_root, "validate-slice", payload)
    if not report["valid"]:
        raise RuntimeError("; ".join(report["errors"]))
    return payload


def _cmd_finalize_slices(args: argparse.Namespace) -> dict[str, Any]:
    repo_root = _repo(args)
    result = finalize_slice_manifests(
        repo_root=repo_root,
        run_month=args.run_month,
        slice_manifest_paths=args.slice_manifest or None,
        requirements_path=args.requirements_file,
        data_commit_sha=args.data_commit_sha or None,
        dry_run=args.dry_run,
    )
    payload = result.to_dict()
    _write_report(repo_root, "finalize-slices", payload)
    if payload["skipped_count"]:
        raise RuntimeError("; ".join(item["reason"] for item in payload["skipped"][:10]))
    return payload


def _cmd_build_bundle(args: argparse.Namespace) -> dict[str, Any]:
    repo_root = _repo(args)
    result = build_bundle(
        repo_root=repo_root,
        run_month=args.run_month,
        bot_id=args.bot_id,
        strategy_id=args.strategy_id,
        slice_manifest_paths=args.slice_manifest or None,
        requirements_path=args.requirements_file,
        dry_run=args.dry_run,
    )
    report = validate_bundle(result.bundle).to_dict()
    payload = {
        "bundle_path": str(result.bundle_path),
        "slice_index_path": str(result.slice_index_path),
        "bundle_checksum": result.bundle.bundle_checksum,
        "status": result.bundle.status.value,
        "dry_run": args.dry_run,
        "validation": report,
    }
    _write_report(repo_root, "build-bundle", payload)
    if not report["valid"]:
        raise RuntimeError(result.bundle.diagnostics_only_reason or "; ".join(report["errors"]))
    return payload


def _cmd_export_filesystem(args: argparse.Namespace) -> dict[str, Any]:
    repo_root = _repo(args)
    payload = export_filesystem(
        repo_root=repo_root,
        run_month=args.run_month,
        bundle_manifest_path=args.bundle_manifest,
        dry_run=args.dry_run,
    )
    _write_report(repo_root, "export-filesystem", payload)
    return payload


def _cmd_export_single_slice(args: argparse.Namespace) -> dict[str, Any]:
    repo_root = _repo(args)
    payload = export_single_slice_coverage(
        repo_root=repo_root,
        run_month=args.run_month,
        bot_id=args.bot_id,
        strategy_id=args.strategy_id,
        bundle_manifest_path=args.bundle_manifest,
        dry_run=args.dry_run,
    )
    _write_report(repo_root, "export-single-slice-coverage", payload)
    return payload


def _cmd_audit_coverage(args: argparse.Namespace) -> dict[str, Any]:
    repo_root = _repo(args)
    payload = audit_coverage(repo_root, run_month=args.run_month)
    _write_report(repo_root, "audit-coverage", payload)
    return payload


def _write_report(repo_root: Path, command: str, payload: Any) -> None:
    write_json(report_path(repo_root, command), payload)


def _raise_on_report_errors(payload: dict[str, Any]) -> None:
    errors: list[str] = []
    for report in payload.get("reports", []):
        errors.extend(str(error) for error in report.get("errors", []))
    if errors:
        preview = "; ".join(errors[:10])
        suffix = f"; ... ({len(errors)} total errors)" if len(errors) > 10 else ""
        raise RuntimeError(preview + suffix)


def _emit(args: argparse.Namespace, payload: Any, *, stderr: bool = False) -> None:
    stream = sys.stderr if stderr else sys.stdout
    if getattr(args, "json_output", False):
        print(json.dumps(payload, indent=2, sort_keys=True, default=str), file=stream)
    else:
        if isinstance(payload, dict):
            ok = payload.get("ok", True)
            status = payload.get("status") or payload.get("name") or args.command
            print(f"{'OK' if ok is not False else 'ERROR'} {status}", file=stream)
            if payload.get("error"):
                print(payload["error"], file=stream)
            elif payload.get("bundle_path"):
                print(payload["bundle_path"], file=stream)
            elif payload.get("manifest_paths"):
                print(f"slice manifests: {len(payload['manifest_paths'])}", file=stream)
        else:
            print(payload, file=stream)
