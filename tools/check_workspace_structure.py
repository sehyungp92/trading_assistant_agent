from __future__ import annotations

import argparse
import ast
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

LAYOUTS = {
    "current": {
        "trading_assistant": ROOT / "trading_assistant",
        "trading_assistant_data": ROOT / "trading_assistant_data",
        "trading_assistant_backtest": ROOT / "trading_assistant_backtest",
    },
    "final": {
        "trading_assistant": ROOT / "packages" / "trading_assistant",
        "trading_assistant_data": ROOT / "packages" / "trading_assistant_data",
        "trading_assistant_backtest": ROOT / "packages" / "trading_assistant_backtest",
    },
}

RUNTIME_DIRS = {
    "current": {
        "trading_assistant": [
            "analysis",
            "comms",
            "contracts",
            "orchestrator",
            "schemas",
            "skills",
        ],
        "trading_assistant_data": ["src/trading_assistant_data"],
        "trading_assistant_backtest": ["src/trading_assistant_backtest", "backtests"],
    },
    "final": {
        "trading_assistant": ["src/trading_assistant"],
        "trading_assistant_data": ["src/trading_assistant_data"],
        "trading_assistant_backtest": ["src/trading_assistant_backtest", "backtests"],
    },
}

FORBIDDEN_IMPORTS = {
    "current": {
        "trading_assistant": {"trading_assistant_data", "trading_assistant_backtest"},
        "trading_assistant_data": {"trading_assistant", "trading_assistant_backtest"},
        "trading_assistant_backtest": {"trading_assistant", "trading_assistant_data"},
    },
    "final": {
        "trading_assistant": {
            "analysis",
            "comms",
            "contracts",
            "orchestrator",
            "schemas",
            "skills",
            "trading_assistant_data",
            "trading_assistant_backtest",
        },
        "trading_assistant_data": {"trading_assistant", "trading_assistant_backtest"},
        "trading_assistant_backtest": {"trading_assistant", "trading_assistant_data"},
    },
}


def _rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _load_toml(path: Path) -> dict:
    with path.open("rb") as handle:
        return tomllib.load(handle)


def _check_exists(workspaces: dict[str, Path], errors: list[str]) -> None:
    for name, path in workspaces.items():
        if not path.is_dir():
            errors.append(f"missing workspace directory: {name}")
        if not (path / "pyproject.toml").is_file():
            errors.append(f"missing pyproject.toml: {name}")

    data_src = workspaces["trading_assistant_data"] / "src" / "trading_assistant_data"
    backtest_src = (
        workspaces["trading_assistant_backtest"] / "src" / "trading_assistant_backtest"
    )
    if not (data_src / "__init__.py").is_file():
        errors.append("missing data src package")
    if not (backtest_src / "__init__.py").is_file():
        errors.append("missing backtest src package")


def _check_packaging(layout: str, workspaces: dict[str, Path], errors: list[str]) -> None:
    if layout == "final":
        control_pyproject = workspaces["trading_assistant"] / "pyproject.toml"
        if not control_pyproject.is_file():
            return
        control = _load_toml(workspaces["trading_assistant"] / "pyproject.toml")
        control_where = (
            control.get("tool", {})
            .get("setuptools", {})
            .get("packages", {})
            .get("find", {})
            .get("where")
        )
        if control_where != ["src"]:
            errors.append("trading_assistant should discover packages from src in final layout")

        control_src = workspaces["trading_assistant"] / "src" / "trading_assistant"
        if not (control_src / "__init__.py").is_file():
            errors.append("missing control-plane src package")

    data_pyproject = workspaces["trading_assistant_data"] / "pyproject.toml"
    backtest_pyproject = workspaces["trading_assistant_backtest"] / "pyproject.toml"
    if not data_pyproject.is_file() or not backtest_pyproject.is_file():
        return

    data = _load_toml(workspaces["trading_assistant_data"] / "pyproject.toml")
    data_where = (
        data.get("tool", {})
        .get("setuptools", {})
        .get("packages", {})
        .get("find", {})
        .get("where")
    )
    if data_where != ["src"]:
        errors.append("trading_assistant_data should discover packages from src")

    backtest = _load_toml(workspaces["trading_assistant_backtest"] / "pyproject.toml")
    wheel_packages = (
        backtest.get("tool", {})
        .get("hatch", {})
        .get("build", {})
        .get("targets", {})
        .get("wheel", {})
        .get("packages", [])
    )
    required = {"src/trading_assistant_backtest", "backtests"}
    missing = sorted(required - set(wheel_packages))
    if missing:
        errors.append(
            "trading_assistant_backtest wheel package list is missing: "
            + ", ".join(missing)
        )


def _iter_python_files(
    workspace: str,
    *,
    workspaces: dict[str, Path],
    runtime_dirs: dict[str, list[str]],
) -> list[Path]:
    root = workspaces[workspace]
    files: list[Path] = []
    for relative in runtime_dirs[workspace]:
        directory = root / relative
        if directory.is_dir():
            files.extend(
                path
                for path in directory.rglob("*.py")
                if "__pycache__" not in path.parts
            )
    return sorted(files)


def _import_roots(tree: ast.AST) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.partition(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.partition(".")[0])
    return roots


def _check_import_boundaries(
    *,
    workspaces: dict[str, Path],
    runtime_dirs: dict[str, list[str]],
    forbidden_imports: dict[str, set[str]],
    errors: list[str],
) -> None:
    for workspace, forbidden in forbidden_imports.items():
        for path in _iter_python_files(
            workspace,
            workspaces=workspaces,
            runtime_dirs=runtime_dirs,
        ):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            except SyntaxError as exc:
                errors.append(f"could not parse {_rel(path)}: {exc}")
                continue

            illegal = sorted(_import_roots(tree) & forbidden)
            if illegal:
                errors.append(
                    f"{_rel(path)} imports forbidden workspace package(s): "
                    + ", ".join(illegal)
                )


def _check_layout(layout: str) -> list[str]:
    errors: list[str] = []
    workspaces = LAYOUTS[layout]
    _check_exists(workspaces, errors)
    _check_packaging(layout, workspaces, errors)
    _check_import_boundaries(
        workspaces=workspaces,
        runtime_dirs=RUNTIME_DIRS[layout],
        forbidden_imports=FORBIDDEN_IMPORTS[layout],
        errors=errors,
    )
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate trading assistant workspace layout.")
    parser.add_argument(
        "--layout",
        choices=("current", "final", "either"),
        default="current",
        help="Workspace layout to validate. Use 'final' after the packages/ migration.",
    )
    args = parser.parse_args(argv)

    if args.layout == "either":
        current_errors = _check_layout("current")
        if not current_errors:
            print("workspace structure OK (current layout)")
            return 0
        final_errors = _check_layout("final")
        if not final_errors:
            print("workspace structure OK (final layout)")
            return 0
        for error in current_errors:
            print(f"CURRENT ERROR: {error}")
        for error in final_errors:
            print(f"FINAL ERROR: {error}")
        return 1

    errors = _check_layout(args.layout)

    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1

    print(f"workspace structure OK ({args.layout} layout)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
