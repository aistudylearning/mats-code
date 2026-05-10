"""Tests for RSI indicator computation — Section 4 (Locked)."""
import polars as pl
import pytest

from src.strategy.indicators import compute_rsi, is_oversold, is_overbought


def _make_ohlcv(closes: list[float]) -> pl.DataFrame:
    n = len(closes)
    return pl.DataFrame({
        "timestamp": list(range(n)),
        "open": closes,
        "high": closes,
        "low": closes,
        "close": closes,
        "volume": [1000.0] * n,
    })


def test_rsi_length_produces_nulls_at_start():
    """First 13 rows should be null (warm-up period for length=14)."""
    df = _make_ohlcv([float(i) for i in range(1, 51)])
    result = compute_rsi(df)
    assert "rsi" in result.columns
    nulls = result["rsi"].is_null().sum()
    assert nulls >= 13, f"Expected at least 13 null RSI values, got {nulls}"


def test_rsi_range_0_to_100():
    """All non-null RSI values must be in [0, 100]."""
    closes = [100.0 + (i % 10) * 2.5 for i in range(60)]
    df = _make_ohlcv(closes)
    result = compute_rsi(df)
    non_null = result.filter(pl.col("rsi").is_not_null())["rsi"]
    assert (non_null >= 0).all() and (non_null <= 100).all()


def test_rsi_oversold_threshold():
    assert is_oversold(29.9) is True
    assert is_oversold(30.0) is False
    assert is_oversold(30.1) is False
    assert is_oversold(None) is False


def test_rsi_overbought_threshold():
    assert is_overbought(70.1) is True
    assert is_overbought(70.0) is False
    assert is_overbought(69.9) is False
    assert is_overbought(None) is False


def test_rsi_uptrend_produces_high_rsi():
    """Strongly rising prices should yield RSI > 70."""
    closes = [100.0 + i * 5 for i in range(50)]
    df = _make_ohlcv(closes)
    result = compute_rsi(df)
    last_rsi = result["rsi"][-1]
    assert last_rsi is not None and last_rsi > 70, f"Expected overbought RSI, got {last_rsi}"


def test_rsi_downtrend_produces_low_rsi():
    """Strongly falling prices should yield RSI < 30."""
    closes = [200.0 - i * 5 for i in range(50)]
    df = _make_ohlcv(closes)
    result = compute_rsi(df)
    last_rsi = result["rsi"][-1]
    assert last_rsi is not None and last_rsi < 30, f"Expected oversold RSI, got {last_rsi}"
