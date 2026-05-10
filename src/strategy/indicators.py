"""
RSI indicator calculation.

Spec reference: Section 4 (RSI Specification — Locked).

Rules:
- Library: pandas-ta
- Function: pandas_ta.rsi(close, length=14)
- Smoothing: Wilder's Moving Average (RMA) — TradingView-compatible default
- RSI calculated independently per timeframe on that timeframe's close series
- Thresholds: oversold < 30, overbought > 70
"""
from __future__ import annotations

import pandas as pd
import pandas_ta as ta
import polars as pl

from src.config.settings import (
    RSI_LENGTH, RSI_OVERSOLD, RSI_OVERBOUGHT,
    VOLUME_SMA_LENGTH,
)
from src.utils.logger import get_logger

log = get_logger(__name__)


def compute_rsi(df: pl.DataFrame, length: int = RSI_LENGTH) -> pl.DataFrame:
    """
    Compute RSI on the 'close' column of a Polars OHLCV DataFrame.

    Args:
        df:     Polars DataFrame with at least ['timestamp', 'close'].
        length: RSI period (default 14, locked per spec).

    Returns:
        Input DataFrame with an additional 'rsi' column (Float64).
        First `length` rows will be null (warm-up period).
    """
    close_pd = df["close"].to_pandas()
    rsi_series = ta.rsi(close_pd, length=length)

    if rsi_series is None:
        rsi_pl = pl.Series("rsi", [None] * len(df), dtype=pl.Float64)
    else:
        rsi_pl = pl.Series("rsi", rsi_series.values, dtype=pl.Float64)
        
    return df.with_columns(rsi_pl)


def compute_volume_sma(df: pl.DataFrame, length: int = VOLUME_SMA_LENGTH) -> pl.DataFrame:
    """
    Compute Simple Moving Average (SMA) of volume for Signal 0.2.
    """
    vol_pd = df["volume"].to_pandas()
    sma_series = ta.sma(vol_pd, length=length)

    if sma_series is None:
        sma_pl = pl.Series("volume_sma", [None] * len(df), dtype=pl.Float64)
    else:
        sma_pl = pl.Series("volume_sma", sma_series.values, dtype=pl.Float64)
        
    return df.with_columns(sma_pl)


def is_oversold(rsi_value: float | None) -> bool:
    """Return True if RSI is below the oversold threshold (< 30)."""
    return rsi_value is not None and rsi_value < RSI_OVERSOLD


def is_overbought(rsi_value: float | None) -> bool:
    """Return True if RSI is above the overbought threshold (> 70)."""
    return rsi_value is not None and rsi_value > RSI_OVERBOUGHT


def compute_indicators_all_timeframes(
    frames: dict[str, pl.DataFrame],
) -> dict[str, pl.DataFrame]:
    """
    Compute RSI for each timeframe DataFrame.
    Also computes volume_sma for 1h timeframe (needed for Signal 0.2).

    Args:
        frames: Dict mapping ccxt timeframe string → OHLCV DataFrame.

    Returns:
        Same dict with 'rsi' (and optionally 'volume_sma') column added.
    """
    result: dict[str, pl.DataFrame] = {}
    for tf, df in frames.items():
        if df.is_empty():
            result[tf] = df
            continue
        
        df_indicators = compute_rsi(df)
        if tf == "1h":
            df_indicators = compute_volume_sma(df_indicators)
            
        result[tf] = df_indicators
        log.debug(f"Indicators computed for timeframe {tf} ({len(df)} rows)")
    return result
