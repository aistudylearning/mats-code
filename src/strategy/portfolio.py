"""
Rolling hard bounds and volatility-adjusted position sizing.

Spec reference: Section 7 (Capital Allocation Model — Locked).

Rolling Hard Bounds (CTO Correction v2):
  - LPrice_i = 0.8 × lowest weekly Low in trailing 52 weeks
  - UPrice_i = 1.2 × highest weekly High in trailing 52 weeks
  - Updated at the start of each new week in the backtest

Position Fraction:
  fraction = 1 - (P_current - LPrice) / (UPrice - LPrice)
  Quantized into 10% discrete steps (0.0, 0.1, ..., 1.0)

Per-Asset Capital:
  BTC/USDT = 50%, ETH/USDT = 50% of C_total
"""
from __future__ import annotations

import math

import polars as pl

from src.config.settings import (
    ASSET_ALLOCATION,
    LOWER_BOUND_MULTIPLIER,
    POSITION_STEP,
    ROLLING_WINDOW_WEEKS,
    UPPER_BOUND_MULTIPLIER,
)
from src.utils.logger import get_logger

log = get_logger(__name__)

_MS_PER_WEEK = 7 * 24 * 3600 * 1000


def compute_rolling_bounds(
    weekly_df: pl.DataFrame,
    current_timestamp_ms: int,
    window_weeks: int = ROLLING_WINDOW_WEEKS,
) -> tuple[float, float]:
    """
    Compute rolling LPrice and UPrice from the trailing 52-week (1W) OHLCV data.

    Args:
        weekly_df:           1W OHLCV DataFrame sorted ascending by timestamp.
        current_timestamp_ms: The timestamp of the current bar being evaluated.
        window_weeks:        Look-back window in weeks (default 52).

    Returns:
        (LPrice, UPrice) tuple. Returns (0.0, inf) if insufficient data.
    """
    window_ms = window_weeks * _MS_PER_WEEK
    start_ms = current_timestamp_ms - window_ms

    window_data = weekly_df.filter(
        (pl.col("timestamp") >= start_ms) & (pl.col("timestamp") < current_timestamp_ms)
    )

    if window_data.is_empty():
        log.warning("Insufficient weekly data for rolling bounds — using fallback (0, inf)")
        return (0.0, float("inf"))

    low_52w = window_data["low"].min()
    high_52w = window_data["high"].max()

    l_price = LOWER_BOUND_MULTIPLIER * low_52w
    u_price = UPPER_BOUND_MULTIPLIER * high_52w

    return (l_price, u_price)


def compute_position_fraction(
    current_price: float,
    l_price: float,
    u_price: float,
    step: float = POSITION_STEP,
) -> float:
    """
    Compute the volatility-adjusted position fraction and quantize to discrete steps.

    Formula: fraction = 1 - (P_current - LPrice) / (UPrice - LPrice)
    Clamped to [0.0, 1.0] and quantized to 10% steps.

    Args:
        current_price: Current close price.
        l_price:       Rolling lower bound.
        u_price:       Rolling upper bound.
        step:          Quantization step (default 0.10).

    Returns:
        Position fraction in [0.0, 1.0], rounded to nearest `step`.
    """
    if u_price - l_price < 1e-5:
        log.warning("Compressed bounds (UPrice - LPrice < 1e-5) — returning 0 position fraction")
        return 0.0

    raw = 1.0 - (current_price - l_price) / (u_price - l_price)
    clamped = max(0.0, min(1.0, raw))
    # Quantize to nearest step
    quantized = round(math.floor(clamped / step) * step, 10)
    return quantized


def compute_position_size_usd(
    symbol: str,
    current_price: float,
    total_capital: float,
    l_price: float,
    u_price: float,
) -> float:
    """
    Compute the USD position size for a given asset.

    Steps:
      1. Get per-asset allocation fraction (e.g., 0.50 for BTC).
      2. Compute AC_i = total_capital × asset_allocation_fraction.
      3. Compute position_fraction (volatility-adjusted, quantized).
      4. Return position_size = AC_i × position_fraction.

    Args:
        symbol:         Asset symbol, e.g. 'BTC/USDT'.
        current_price:  Current close price.
        total_capital:  Total portfolio capital in USD.
        l_price:        Rolling lower bound.
        u_price:        Rolling upper bound.

    Returns:
        Position size in USD.
    """
    asset_frac = ASSET_ALLOCATION.get(symbol, 0.0)
    ac_i = total_capital * asset_frac
    pos_frac = compute_position_fraction(current_price, l_price, u_price)
    size_usd = ac_i * pos_frac
    log.debug(
        f"{symbol} | price={current_price:.2f} | bounds=[{l_price:.2f}, {u_price:.2f}] | "
        f"pos_frac={pos_frac:.2f} | size_USD={size_usd:.2f}"
    )
    return size_usd
