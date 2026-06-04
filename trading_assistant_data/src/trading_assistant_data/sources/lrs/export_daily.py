"""Data-only LRS SQLite daily export entry points."""

from __future__ import annotations

from pathlib import Path

import pandas as pd


def export_table(sqlite_path: Path, table: str, output_path: Path) -> Path:
    import sqlite3

    with sqlite3.connect(sqlite_path) as connection:
        frame = pd.read_sql_query(f"SELECT * FROM {table}", connection)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(output_path, engine="pyarrow", index=False)
    return output_path

