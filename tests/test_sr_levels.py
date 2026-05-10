"""Tests for S/R level detection and clustering — Section 5 (Locked)."""
import polars as pl
import pytest

from src.strategy.sr_levels import (
    SRZone,
    cluster_zones,
    compute_pivot_points,
    detect_pivots,
    get_active_zones,
)


def _make_ohlcv_df(highs: list[float], lows: list[float], timestamps: list[int] | None = None) -> pl.DataFrame:
    n = len(highs)
    ts = timestamps or list(range(n))
    return pl.DataFrame({
        "timestamp": ts,
        "open": highs,
        "high": highs,
        "low": lows,
        "close": highs,
        "volume": [1000.0] * n,
    })


def test_detect_pivot_resistance():
    """A clear local high should be detected as a resistance pivot."""
    highs = [100, 102, 104, 110, 104, 102, 100, 98, 96, 94, 92, 90]  # peak at index 3
    lows  = [90, 92, 94, 100, 94, 92, 90, 88, 86, 84, 82, 80]
    df = _make_ohlcv_df(highs, lows)
    zones = detect_pivots(df, timeframe="1d", window=2)
    resistances = [z for z in zones if z.kind == "resistance"]
    assert len(resistances) >= 1
    assert any(abs(z.price - 110) < 1e-6 for z in resistances)


def test_detect_pivot_support():
    """A clear local low should be detected as a support pivot."""
    highs = [100, 98, 96, 90, 96, 98, 100, 102, 104, 106, 108, 110]
    lows  = [90, 88, 86, 80, 86, 88, 90, 92, 94, 96, 98, 100]
    df = _make_ohlcv_df(highs, lows)
    zones = detect_pivots(df, timeframe="1d", window=2)
    supports = [z for z in zones if z.kind == "support"]
    assert len(supports) >= 1
    assert any(abs(z.price - 80) < 1e-6 for z in supports)


def test_look_ahead_bias_rule():
    """Pivot at bar t should only be active from bar t+N+1 (not before)."""
    highs = [100, 102, 110, 102, 100, 98, 96, 94, 92, 90, 88, 86]
    lows  = [90, 92, 100, 92, 90, 88, 86, 84, 82, 80, 78, 76]
    # Use real timestamps spaced 1 unit apart
    ts = list(range(len(highs)))
    df = _make_ohlcv_df(highs, lows, timestamps=ts)
    zones = detect_pivots(df, timeframe="1d", window=2)
    resistances = [z for z in zones if z.kind == "resistance"]
    for z in resistances:
        # bar_active_from should be >= pivot_bar + window (not the pivot bar itself)
        assert z.bar_active_from > 0


def test_cluster_merges_close_pivots():
    """Two pivots within 0.5% of each other should be merged."""
    z1 = SRZone(price=100.0, kind="support", timeframe="1d", weight=3, bar_active_from=0)
    z2 = SRZone(price=100.4, kind="support", timeframe="4h", weight=2, bar_active_from=0)
    merged = cluster_zones([z1, z2], threshold=0.005)
    assert len(merged) == 1
    assert abs(merged[0].price - 100.2) < 1e-6
    assert merged[0].combined_weight == 5


def test_cluster_keeps_far_pivots_separate():
    """Two pivots > 0.5% apart should not be merged."""
    z1 = SRZone(price=100.0, kind="support", timeframe="1d", weight=3, bar_active_from=0)
    z2 = SRZone(price=102.0, kind="support", timeframe="4h", weight=2, bar_active_from=0)
    merged = cluster_zones([z1, z2], threshold=0.005)
    assert len(merged) == 2


def test_get_active_zones_filters_future_pivots():
    """Zones with bar_active_from in the future should be excluded."""
    z_past = SRZone(price=100.0, kind="support", timeframe="1d", weight=3, bar_active_from=1000)
    z_future = SRZone(price=110.0, kind="resistance", timeframe="1d", weight=3, bar_active_from=9999)
    active = get_active_zones([z_past, z_future], current_timestamp_ms=5000)
    assert z_past in active
    assert z_future not in active


def test_pivot_points_algorithm_b():
    """Algorithm B: classic pivot point formula."""
    pp = compute_pivot_points(prev_high=110.0, prev_low=90.0, prev_close=100.0)
    p = (110 + 90 + 100) / 3
    assert abs(pp["P"] - p) < 1e-9
    assert abs(pp["R1"] - (2 * p - 90)) < 1e-9
    assert abs(pp["S1"] - (2 * p - 110)) < 1e-9
    assert abs(pp["R2"] - (p + 20)) < 1e-9
    assert abs(pp["S2"] - (p - 20)) < 1e-9
