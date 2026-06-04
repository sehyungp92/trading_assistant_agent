"""Hyperliquid parquet store helpers."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from trading_assistant_data.checksums import stable_row_hashes


def candle_open_from_ms(value: int | float) -> pd.Timestamp:
    return pd.to_datetime(int(value), unit="ms", utc=True)


def canonicalize_candles(
    frame: pd.DataFrame,
    *,
    symbol: str,
    interval: str,
    source_file: str = "",
) -> pd.DataFrame:
    required = {"ts", "open", "high", "low", "close", "volume"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"Hyperliquid candle frame missing columns: {missing}")
    source = frame.copy()
    out = pd.DataFrame(
        {
            "timestamp_utc": pd.to_datetime(source["ts"], unit="ms", utc=True),
            "timestamp_exchange": pd.to_datetime(source["ts"], unit="ms", utc=True).astype(str),
            "symbol": symbol.upper(),
            "market": "crypto_perp",
            "source": "hyperliquid",
            "timeframe": interval,
            "kind": "trades",
            "open": source["open"].astype("float64"),
            "high": source["high"].astype("float64"),
            "low": source["low"].astype("float64"),
            "close": source["close"].astype("float64"),
            "volume": source["volume"].astype("float64"),
            "source_file": source_file,
            "source_ts_ms": source["ts"].astype("int64"),
        }
    )
    out["source_row_hash"] = stable_row_hashes(source[sorted(required)])
    return out.sort_values("timestamp_utc").drop_duplicates("timestamp_utc", keep="last")


def canonicalize_funding(
    frame: pd.DataFrame,
    *,
    symbol: str,
    source_file: str = "",
) -> pd.DataFrame:
    required = {"ts", "rate"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"Hyperliquid funding frame missing columns: {missing}")
    source = frame.copy()
    out = pd.DataFrame(
        {
            "timestamp_utc": pd.to_datetime(source["ts"], unit="ms", utc=True),
            "timestamp_exchange": pd.to_datetime(source["ts"], unit="ms", utc=True).astype(str),
            "symbol": symbol.upper(),
            "market": "crypto_perp",
            "source": "hyperliquid",
            "rate": source["rate"].astype("float64"),
            "source_file": source_file,
            "source_ts_ms": source["ts"].astype("int64"),
        }
    )
    out["source_row_hash"] = stable_row_hashes(source[sorted(required)])
    return out.sort_values("timestamp_utc").drop_duplicates("timestamp_utc", keep="last")


def write_monthly_partitions(frame: pd.DataFrame, root: Path, *parts: str) -> list[Path]:
    paths: list[Path] = []
    if frame.empty:
        return paths
    by_month = frame.assign(
        year=frame["timestamp_utc"].dt.year.astype(str),
        month=frame["timestamp_utc"].dt.month.map(lambda value: f"{int(value):02d}"),
    )
    for (year, month), group in by_month.groupby(["year", "month"], sort=True):
        path = Path(root).joinpath(*parts, f"year={year}", f"month={month}", "part.parquet")
        path.parent.mkdir(parents=True, exist_ok=True)
        group.drop(columns=["year", "month"]).to_parquet(path, engine="pyarrow", index=False)
        paths.append(path)
    return paths

