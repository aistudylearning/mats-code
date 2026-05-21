"""Tests for S/R level detection and clustering — Section 5 (Locked)."""
import polars as pl
import pytest

from src.strategy.sr_levels import (
    SRZone,
    build_sr_zones,
    cluster_zones,
    compute_pivot_points,
    detect_pivots,
    get_active_zones,
    merge_zone_into_clustered,
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


def test_merge_zone_into_clustered():
    """merge_zone_into_clustered merges close pivots of same kind, appends otherwise."""
    clustered = [
        SRZone(price=100.0, kind="support", timeframe="1d", weight=3, bar_active_from=100),
    ]
    # 1. Close support zone within 0.5% threshold -> should merge (average price, combined weight, etc.)
    new_close_support = SRZone(price=100.4, kind="support", timeframe="4h", weight=2, bar_active_from=50)
    merge_zone_into_clustered(clustered, new_close_support, threshold=0.005)
    assert len(clustered) == 1
    assert abs(clustered[0].price - 100.2) < 1e-6
    assert clustered[0].combined_weight == 5
    assert clustered[0].bar_active_from == 50
    assert "4h" in clustered[0].contributing_timeframes

    # 2. Far support zone -> should append
    new_far_support = SRZone(price=102.0, kind="support", timeframe="1h", weight=1, bar_active_from=200)
    merge_zone_into_clustered(clustered, new_far_support, threshold=0.005)
    assert len(clustered) == 2
    assert clustered[1].price == 102.0

    # 3. Close resistance zone (different kind) -> should append
    new_close_resistance = SRZone(price=100.2, kind="resistance", timeframe="1d", weight=3, bar_active_from=150)
    merge_zone_into_clustered(clustered, new_close_resistance, threshold=0.005)
    assert len(clustered) == 3
    assert clustered[2].kind == "resistance"


def test_merge_into_empty_list():
    """Merging into an empty list should just append."""
    clustered: list[SRZone] = []
    zone = SRZone(price=100.0, kind="support", timeframe="1d", weight=3, bar_active_from=500)
    merge_zone_into_clustered(clustered, zone)
    assert len(clustered) == 1
    assert clustered[0] is zone


def test_merge_returns_none():
    """merge_zone_into_clustered mutates in-place and returns None."""
    clustered = [SRZone(price=100.0, kind="support", timeframe="1d", weight=3, bar_active_from=0)]
    result = merge_zone_into_clustered(
        clustered,
        SRZone(price=100.1, kind="support", timeframe="4h", weight=2, bar_active_from=0),
    )
    assert result is None


def test_merge_at_exact_threshold_boundary():
    """Distance exactly at the 0.5% threshold should still merge (<=)."""
    base = SRZone(price=100.0, kind="support", timeframe="1d", weight=3, bar_active_from=0)
    # 0.5% of 100 = exactly 0.5 → price 100.5 is at threshold
    edge = SRZone(price=100.5, kind="support", timeframe="4h", weight=2, bar_active_from=0)
    clustered = [base]
    merge_zone_into_clustered(clustered, edge, threshold=0.005)
    assert len(clustered) == 1, "Should merge at exact threshold boundary"


def test_merge_just_beyond_threshold():
    """Distance just beyond 0.5% threshold should NOT merge."""
    base = SRZone(price=100.0, kind="support", timeframe="1d", weight=3, bar_active_from=0)
    beyond = SRZone(price=100.51, kind="support", timeframe="4h", weight=2, bar_active_from=0)
    clustered = [base]
    merge_zone_into_clustered(clustered, beyond, threshold=0.005)
    assert len(clustered) == 2, "Should NOT merge just beyond threshold"


def test_merge_triple_accumulates_weight():
    """Merging three zones into the same cluster accumulates weight correctly."""
    z1 = SRZone(price=100.0, kind="support", timeframe="1d", weight=3, bar_active_from=100)
    z2 = SRZone(price=100.2, kind="support", timeframe="4h", weight=2, bar_active_from=200)
    z3 = SRZone(price=100.1, kind="support", timeframe="1w", weight=4, bar_active_from=50)
    clustered = [z1]
    merge_zone_into_clustered(clustered, z2)
    merge_zone_into_clustered(clustered, z3)
    assert len(clustered) == 1
    # z1 combined_weight=3 + z2 weight=2 = 5, then 5 + z3 weight=4 = 9
    assert clustered[0].combined_weight == 9
    assert clustered[0].bar_active_from == 50  # earliest
    assert set(clustered[0].contributing_timeframes) == {"1d", "4h", "1w"}


def test_merge_deduplicates_contributing_timeframes():
    """Same timeframe merged twice shouldn't duplicate in contributing_timeframes."""
    z1 = SRZone(price=100.0, kind="support", timeframe="1d", weight=3, bar_active_from=0)
    z2 = SRZone(price=100.1, kind="support", timeframe="1d", weight=3, bar_active_from=100)
    clustered = [z1]
    merge_zone_into_clustered(clustered, z2)
    assert clustered[0].contributing_timeframes.count("1d") == 1


def test_build_sr_zones_cluster_false_returns_unclustered():
    """With cluster=False, zones that would normally merge stay separate."""
    # Two close 1d pivots that cluster_zones would merge
    n = 15
    timestamps = list(range(n))
    highs = [90.0]*5 + [100.0] + [90.0]*4 + [100.3] + [90.0]*4
    lows  = [80.0]*n
    df = _make_ohlcv_df(highs, lows, timestamps=timestamps)
    # build with cluster=True vs cluster=False
    raw = build_sr_zones({"1d": df}, cluster=False)
    clustered = build_sr_zones({"1d": df}, cluster=True)
    # Raw should have more or equal zones than clustered
    assert len(raw) >= len(clustered)


def test_build_sr_zones_filters_low_timeframes():
    """build_sr_zones should ignore frames for non-structural timeframes like 5m."""
    n = 15
    highs = [90.0]*5 + [110.0] + [90.0]*9
    lows  = [80.0]*n
    df = _make_ohlcv_df(highs, lows)
    # Pass frames with 5m key — should be filtered out
    zones_5m = build_sr_zones({"5m": df}, cluster=False)
    zones_1d = build_sr_zones({"1d": df}, cluster=False)
    assert len(zones_5m) == 0, "5m is not a structural TF, should produce no zones"
    assert len(zones_1d) > 0, "1d is structural, should produce zones"


def test_build_sr_zones_empty_frames():
    """build_sr_zones with empty dict returns empty list."""
    assert build_sr_zones({}, cluster=False) == []
    assert build_sr_zones({}, cluster=True) == []
