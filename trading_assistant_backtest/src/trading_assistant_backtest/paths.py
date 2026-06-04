"""Path containment helpers."""

from __future__ import annotations

from pathlib import Path


def resolve_under(root: Path, path: str | Path, *, label: str = "path") -> Path:
    """Resolve `path` and require it to remain under `root`."""
    root = Path(root).resolve()
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"{label} escapes artifact root: {resolved}") from exc
    return resolved


def ensure_directory(path: str | Path) -> Path:
    resolved = Path(path).resolve()
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved
