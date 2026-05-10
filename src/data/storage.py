"""
Parquet storage read/write helpers.

Spec reference: Section 2 (Data Architecture).
Partition scheme: {root}/{ASSET}/{TF}/YYYY-MM.parquet
"""
from __future__ import annotations

from pathlib import Path

import polars as pl

from src.config.settings import DATA_ROOT, PARQUET_COMPRESSION, TF_MAP
from src.utils.logger import get_logger

log = get_logger(__name__)


def _asset_to_path_name(symbol: str) -> str:
    """'BTC/USDT' → 'BTC-USDT'"""
    return symbol.replace("/", "-")


def load_ohlcv(
    symbol: str,
    timeframe: str,
    root: str = DATA_ROOT,
) -> pl.DataFrame:
    """
    Load all available parquet files for a symbol+timeframe, sorted by timestamp.

    Args:
        symbol:    e.g. 'BTC/USDT'
        timeframe: ccxt string, e.g. '1h'
        root:      Base data directory.

    Returns:
        Sorted Polars DataFrame. Empty DataFrame if no data found.
    """
    tf_label = TF_MAP.get(timeframe, timeframe.upper())
    asset_name = _asset_to_path_name(symbol)
    base_path = Path(root) / asset_name / tf_label

    if not base_path.exists():
        log.warning(f"No data directory found: {base_path}")
        return pl.DataFrame()

    files = sorted(base_path.glob("*.parquet"))
    if not files:
        log.warning(f"No parquet files in {base_path}")
        return pl.DataFrame()

    frames = [pl.read_parquet(str(f)) for f in files]
    df = pl.concat(frames).unique(subset=["timestamp"]).sort("timestamp")
    log.info(f"Loaded {len(df)} rows for {symbol} {tf_label} from {len(files)} files")
    return df


def save_ohlcv(
    df: pl.DataFrame,
    symbol: str,
    timeframe: str,
    root: str = DATA_ROOT,
) -> None:
    """
    Write a DataFrame to monthly-partitioned parquet files.
    Overwrites any existing file for the same month.

    Args:
        df:        DataFrame with a 'timestamp' column (Unix ms, Int64).
        symbol:    e.g. 'BTC/USDT'
        timeframe: ccxt string, e.g. '1h'
        root:      Base data directory.
    """
    tf_label = TF_MAP.get(timeframe, timeframe.upper())
    asset_name = _asset_to_path_name(symbol)

    df = df.with_columns(
        pl.from_epoch(pl.col("timestamp"), time_unit="ms")
        .dt.strftime("%Y-%m")
        .alias("_ym")
    )

    for ym in df["_ym"].unique().sort().to_list():
        month_df = df.filter(pl.col("_ym") == ym).drop("_ym")
        path = Path(root) / asset_name / tf_label / f"{ym}.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        month_df.write_parquet(str(path), compression=PARQUET_COMPRESSION)
        log.debug(f"Saved {path} ({len(month_df)} rows)")


def list_available(root: str = DATA_ROOT) -> dict[str, list[str]]:
    """
    List available (symbol, timeframe) pairs in the data store.

    Returns:
        Dict mapping asset folder names to list of timeframe folder names.
    """
    base = Path(root)
    result: dict[str, list[str]] = {}
    if not base.exists():
        return result
    for asset_dir in sorted(base.iterdir()):
        if asset_dir.is_dir():
            tfs = [tf.name for tf in sorted(asset_dir.iterdir()) if tf.is_dir()]
            result[asset_dir.name] = tfs
    return result
