from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _workspace(name: str) -> Path:
    final_path = ROOT / "packages" / name
    if final_path.is_dir():
        return final_path
    raise FileNotFoundError(f"missing final package workspace: {final_path}")


def _run(args: Sequence[str], *, cwd: Path, env: dict[str, str] | None = None) -> int:
    print(f"+ ({cwd.relative_to(ROOT).as_posix()}) {' '.join(args)}")
    completed = subprocess.run(args, cwd=cwd, env=env, check=False)
    return completed.returncode


def _run_json_summary(args: Sequence[str], *, cwd: Path, summary) -> int:
    print(f"+ ({cwd.relative_to(ROOT).as_posix()}) {' '.join(args)}")
    completed = subprocess.run(
        args,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.stdout.strip():
        try:
            print(summary(json.loads(completed.stdout)))
        except Exception:
            print(completed.stdout.rstrip())
    if completed.stderr.strip():
        print(completed.stderr.rstrip(), file=sys.stderr)
    return completed.returncode


def _pytest_env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("PYTHONUNBUFFERED", "1")
    return env


def _run_many(commands: Sequence[tuple[Sequence[str], Path, dict[str, str] | None]]) -> int:
    for args, cwd, env in commands:
        code = _run(args, cwd=cwd, env=env)
        if code != 0:
            return code
    return 0


def structure(layout: str) -> int:
    return _run(
        [sys.executable, "tools/check_workspace_structure.py", "--layout", layout],
        cwd=ROOT,
    )


def monthly_focused() -> int:
    return _run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_monthly_optimizer_runner.py",
            "tests/test_monthly_runner_contract_conformance.py",
            "-q",
            "-o",
            "addopts=",
        ],
        cwd=_workspace("trading_assistant"),
        env=_pytest_env(),
    )


def data_contracts() -> int:
    return _run(
        [sys.executable, "-m", "pytest", "tests/test_contracts.py", "-q"],
        cwd=_workspace("trading_assistant_data"),
        env=_pytest_env(),
    )


def backtest_monthly() -> int:
    return _run(
        [sys.executable, "-m", "pytest", "tests/unit/test_monthly_runner.py", "-q"],
        cwd=_workspace("trading_assistant_backtest"),
        env=_pytest_env(),
    )


def backtest_approval() -> int:
    return _run(
        [sys.executable, "-m", "pytest", "tests/unit/test_approval_grade_audit.py", "-q"],
        cwd=_workspace("trading_assistant_backtest"),
        env=_pytest_env(),
    )


def manifest_validate() -> int:
    return _run(
        [
            sys.executable,
            "-m",
            "trading_assistant_backtest.monthly",
            "--manifest",
            "artifacts/validation/monthly_smoke/k_stock_olr_kalcb/run_manifest.json",
            "--validate-only",
        ],
        cwd=_workspace("trading_assistant_backtest"),
    )


def data_reproduction_smoke() -> int:
    with tempfile.TemporaryDirectory(prefix="ta_data_reproduction_") as artifact_root:
        return _run_json_summary(
            [
                sys.executable,
                "-m",
                "trading_assistant_backtest.validation.data_reproduction_run",
                "--agent-root",
                str(ROOT),
                "--artifact-root",
                artifact_root,
                "--scope",
                "crypto_trader_portfolio",
            ],
            cwd=ROOT,
            summary=lambda payload: (
                f"data_reproduction_status={payload.get('status')}; "
                f"report_count={payload.get('report_count')}; "
                "slice_count="
                f"{sum(int(report.get('slice_count') or 0) for report in payload.get('reports', []))}"
            ),
        )


def validation_matrix() -> int:
    with tempfile.TemporaryDirectory(prefix="ta_validation_matrix_") as artifact_root:
        return _run_json_summary(
            [
                sys.executable,
                "-m",
                "trading_assistant_backtest.validation.validation_matrix",
                "--agent-root",
                str(ROOT),
                "--artifact-root",
                artifact_root,
            ],
            cwd=ROOT,
            summary=lambda payload: (
                f"validation_matrix_ok={payload.get('ok')}; "
                "all_validation_tests_runnable_for_all_scopes="
                f"{payload.get('all_validation_tests_runnable_for_all_scopes')}; "
                f"approval_remaining_gaps={len(payload.get('approval_remaining_gaps', []))}"
            ),
        )


def all_tests() -> int:
    env = _pytest_env()
    return _run_many(
        (
            (
                [sys.executable, "-m", "pytest", "-o", "addopts="],
                _workspace("trading_assistant"),
                env,
            ),
            ([sys.executable, "-m", "pytest"], _workspace("trading_assistant_data"), env),
            (
                [sys.executable, "-m", "pytest"],
                _workspace("trading_assistant_backtest"),
                env,
            ),
        )
    )


def cli_smoke() -> int:
    return _run_many(
        (
            (
                [sys.executable, "-m", "trading_assistant_data", "--help"],
                _workspace("trading_assistant_data"),
                None,
            ),
            (
                [sys.executable, "-m", "trading_assistant_backtest.monthly", "--help"],
                _workspace("trading_assistant_backtest"),
                None,
            ),
            (
                [sys.executable, "-m", "backtests.shared.monthly_repair", "--help"],
                _workspace("trading_assistant_backtest"),
                None,
            ),
        )
    )


def imports() -> int:
    commands = (
        [sys.executable, "-c", "import trading_assistant.schemas.monthly_run_manifest"],
        [sys.executable, "-c", "import trading_assistant.orchestrator.config"],
        [
            sys.executable,
            "-c",
            "import trading_assistant.skills.monthly_validation_orchestrator",
        ],
        [sys.executable, "-c", "import trading_assistant_data.cli"],
        [sys.executable, "-c", "import trading_assistant_backtest.monthly"],
    )
    return _run_many(tuple((command, ROOT, None) for command in commands))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run trading-assistant workspace checks.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    structure_parser = subparsers.add_parser("structure")
    structure_parser.add_argument(
        "--layout",
        choices=("current", "final", "either"),
        default="final",
    )
    subparsers.add_parser("monthly-focused")
    subparsers.add_parser("data-contracts")
    subparsers.add_parser("backtest-monthly")
    subparsers.add_parser("backtest-approval")
    subparsers.add_parser("manifest-validate")
    subparsers.add_parser("data-reproduction-smoke")
    subparsers.add_parser("validation-matrix")
    subparsers.add_parser("all-tests")
    subparsers.add_parser("cli-smoke")
    subparsers.add_parser("imports")

    args = parser.parse_args(argv)
    if args.command == "structure":
        return structure(args.layout)
    if args.command == "monthly-focused":
        return monthly_focused()
    if args.command == "data-contracts":
        return data_contracts()
    if args.command == "backtest-monthly":
        return backtest_monthly()
    if args.command == "backtest-approval":
        return backtest_approval()
    if args.command == "manifest-validate":
        return manifest_validate()
    if args.command == "data-reproduction-smoke":
        return data_reproduction_smoke()
    if args.command == "validation-matrix":
        return validation_matrix()
    if args.command == "all-tests":
        return all_tests()
    if args.command == "cli-smoke":
        return cli_smoke()
    if args.command == "imports":
        return imports()
    raise AssertionError(f"unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
