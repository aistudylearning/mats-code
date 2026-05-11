"""Tests for locked configuration parameters — Section 1–8 invariants.

These tests act as a safety net: if anyone accidentally modifies a locked
parameter in settings.py, these will immediately flag it.
"""
import pytest

from src.config.settings import (
    # RSI — Section 4
    RSI_LENGTH,
    RSI_OVERSOLD,
    RSI_OVERBOUGHT,
    # S/R — Section 5
    SR_PIVOT_WINDOW,
    SR_MAX_PIVOTS,
    SR_CLUSTER_THRESHOLD,
    SR_PROXIMITY_PCT,
    SR_WEIGHTS,
    HIGH_CONVICTION_THRESHOLD,
    # Capital — Section 7
    ASSET_ALLOCATION,
    ROLLING_WINDOW_WEEKS,
    LOWER_BOUND_MULTIPLIER,
    UPPER_BOUND_MULTIPLIER,
    POSITION_STEP,
    # Friction — Section 8
    TAKER_FEE,
    SLIPPAGE_FLAT,
    TOTAL_FRICTION_PER_EXEC,
    ROUND_TRIP_FRICTION,
    MIN_SPREAD_TO_TRADE,
    # Timeframes
    TIMEFRAMES,
    TF_MAP,
    MVP_ASSETS,
    # Signal 0.2
    VOLUME_SMA_LENGTH,
    VOLUME_SPIKE_MULTIPLIER,
)


# ── RSI invariants (Section 4) ──────────────────────────────────────

def test_rsi_length_locked():
    assert RSI_LENGTH == 14

def test_rsi_oversold_locked():
    assert RSI_OVERSOLD == 30

def test_rsi_overbought_locked():
    assert RSI_OVERBOUGHT == 70


# ── S/R invariants (Section 5) ──────────────────────────────────────

def test_sr_pivot_window_locked():
    assert SR_PIVOT_WINDOW == 5

def test_sr_max_pivots_locked():
    assert SR_MAX_PIVOTS == 50

def test_sr_cluster_threshold_locked():
    assert SR_CLUSTER_THRESHOLD == 0.005

def test_sr_proximity_locked():
    assert SR_PROXIMITY_PCT == 0.02

def test_high_conviction_threshold_locked():
    assert HIGH_CONVICTION_THRESHOLD == 5


# ── Capital allocation (Section 7) ──────────────────────────────────

def test_allocation_sums_to_1():
    """All asset allocation fractions must sum to exactly 1.0."""
    total = sum(ASSET_ALLOCATION.values())
    assert abs(total - 1.0) < 1e-9, f"Allocations sum to {total}, expected 1.0"

def test_allocation_covers_all_mvp_assets():
    """Every MVP asset must have an allocation entry."""
    for asset in MVP_ASSETS:
        assert asset in ASSET_ALLOCATION, f"Missing allocation for {asset}"

def test_rolling_window_52_weeks():
    assert ROLLING_WINDOW_WEEKS == 52

def test_lower_bound_multiplier():
    assert LOWER_BOUND_MULTIPLIER == 0.8

def test_upper_bound_multiplier():
    assert UPPER_BOUND_MULTIPLIER == 1.2

def test_position_step_10pct():
    assert POSITION_STEP == 0.10


# ── Friction invariants (Section 8) ──────────────────────────────────

def test_taker_fee_locked():
    assert abs(TAKER_FEE - 0.0010) < 1e-9

def test_slippage_locked():
    assert abs(SLIPPAGE_FLAT - 0.0005) < 1e-9

def test_total_friction_per_exec():
    assert abs(TOTAL_FRICTION_PER_EXEC - 0.0015) < 1e-9

def test_round_trip_friction():
    assert abs(ROUND_TRIP_FRICTION - 0.003) < 1e-9

def test_min_spread_equals_round_trip():
    assert MIN_SPREAD_TO_TRADE == ROUND_TRIP_FRICTION


# ── Timeframe configuration ─────────────────────────────────────────

def test_ten_timeframes_configured():
    """Must have exactly 10 timeframes per the multi-TF design."""
    assert len(TIMEFRAMES) == 10

def test_tf_map_covers_all_timeframes():
    """Every configured timeframe must have a mapping to a display name."""
    for tf in TIMEFRAMES:
        assert tf in TF_MAP, f"Missing TF_MAP entry for {tf}"

def test_sr_weights_cover_all_timeframes():
    """Every configured timeframe must have an S/R weight."""
    for tf in TIMEFRAMES:
        assert tf in SR_WEIGHTS, f"Missing SR_WEIGHTS entry for {tf}"

def test_sr_weights_monotonic():
    """Higher timeframes should have equal or higher S/R weights."""
    ordered_weights = [SR_WEIGHTS[tf] for tf in TIMEFRAMES]
    for i in range(1, len(ordered_weights)):
        assert ordered_weights[i] >= ordered_weights[i-1], (
            f"S/R weight for {TIMEFRAMES[i]} ({ordered_weights[i]}) "
            f"< {TIMEFRAMES[i-1]} ({ordered_weights[i-1]})"
        )


# ── MVP assets ───────────────────────────────────────────────────────

def test_50_mvp_assets():
    assert len(MVP_ASSETS) == 50

def test_all_assets_are_usdt_pairs():
    """All assets must be X/USDT pairs for Binance compatibility."""
    for asset in MVP_ASSETS:
        assert asset.endswith("/USDT"), f"Asset {asset} is not a USDT pair"

def test_no_duplicate_assets():
    assert len(MVP_ASSETS) == len(set(MVP_ASSETS))


# ── Signal 0.2 parameters ───────────────────────────────────────────

def test_volume_sma_length():
    assert VOLUME_SMA_LENGTH == 20

def test_volume_spike_multiplier():
    assert VOLUME_SPIKE_MULTIPLIER == 1.5
