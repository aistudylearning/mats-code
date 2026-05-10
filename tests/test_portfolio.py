"""Tests for rolling bounds and position sizing — Section 7 (Locked)."""
import polars as pl
import pytest

from src.strategy.portfolio import (
    compute_position_fraction,
    compute_position_size_usd,
    compute_rolling_bounds,
)

_MS_PER_WEEK = 7 * 24 * 3600 * 1000


def _make_weekly_df(lows: list[float], highs: list[float], start_ts: int = 0) -> pl.DataFrame:
    n = len(lows)
    return pl.DataFrame({
        "timestamp": [start_ts + i * _MS_PER_WEEK for i in range(n)],
        "open": highs,
        "high": highs,
        "low": lows,
        "close": highs,
        "volume": [1e9] * n,
    })


def test_rolling_bounds_formula():
    """LPrice = 0.8 × 52w_low, UPrice = 1.2 × 52w_high."""
    # 52 weekly bars, lows = 15500, highs = 48000 (spec example)
    lows = [15500.0] * 52
    highs = [48000.0] * 52
    df = _make_weekly_df(lows, highs, start_ts=0)
    current_ts = 52 * _MS_PER_WEEK  # one week after last bar
    l_price, u_price = compute_rolling_bounds(df, current_ts, window_weeks=52)
    assert abs(l_price - 0.8 * 15500) < 1.0, f"LPrice={l_price}"
    assert abs(u_price - 1.2 * 48000) < 1.0, f"UPrice={u_price}"


def test_rolling_bounds_only_uses_trailing_window():
    """Bounds should only reflect data within trailing 52 weeks."""
    # Older period: very low/high
    old_lows = [1000.0] * 60
    old_highs = [200000.0] * 60
    # Recent period (last 52 weeks): normal range
    recent_lows = [15500.0] * 52
    recent_highs = [48000.0] * 52
    all_lows = old_lows + recent_lows
    all_highs = old_highs + recent_highs
    df = _make_weekly_df(all_lows, all_highs, start_ts=0)
    # current_ts: one step after the last bar
    current_ts = (60 + 52) * _MS_PER_WEEK
    l_price, u_price = compute_rolling_bounds(df, current_ts, window_weeks=52)
    # Should reflect recent range, NOT old range
    assert l_price > 0.8 * 1000
    assert u_price < 1.2 * 200000


def test_position_fraction_near_lbound():
    """When price ≈ LPrice, fraction should be close to 1.0."""
    frac = compute_position_fraction(current_price=12500.0, l_price=12400.0, u_price=57600.0)
    assert frac >= 0.9, f"Expected fraction ≈ 1.0, got {frac}"


def test_position_fraction_near_ubound():
    """When price ≈ UPrice, fraction should be close to 0.0."""
    frac = compute_position_fraction(current_price=57500.0, l_price=12400.0, u_price=57600.0)
    assert frac <= 0.1, f"Expected fraction ≈ 0.0, got {frac}"


def test_position_fraction_quantized_to_10pct_steps():
    """Position fraction must be one of [0.0, 0.1, 0.2, ..., 1.0]."""
    l_price, u_price = 10000.0, 60000.0
    for price in [10000, 20000, 30000, 40000, 50000, 60000]:
        frac = compute_position_fraction(float(price), l_price, u_price)
        rounded = round(frac * 10) / 10
        assert abs(frac - rounded) < 1e-9, f"Fraction {frac} is not quantized"


def test_position_fraction_clamped_0_to_1():
    """Fraction must never exceed 1.0 or go below 0.0."""
    # Below LPrice
    frac_low = compute_position_fraction(5000.0, l_price=10000.0, u_price=60000.0)
    assert frac_low == 1.0

    # Above UPrice
    frac_high = compute_position_fraction(70000.0, l_price=10000.0, u_price=60000.0)
    assert frac_high == 0.0


def test_position_size_usd_btc():
    """BTC gets 50% of capital. Size = AC_i × position_fraction."""
    total_capital = 10000.0
    # Near LPrice → fraction should be close to 1.0 → size ≈ 5000
    size = compute_position_size_usd(
        symbol="BTC/USDT",
        current_price=12500.0,
        total_capital=total_capital,
        l_price=12400.0,
        u_price=57600.0,
    )
    assert size >= 4000.0, f"Expected near-full BTC allocation, got {size}"
    assert size <= 5000.0
