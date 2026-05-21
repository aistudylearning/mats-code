"""Unit tests verifying all mathematical and system edge cases in the MATS backtest engine."""
import pytest

from src.strategy.signals import evaluate_signal, _price_near_zone
from src.strategy.sr_levels import SRZone
from src.strategy.portfolio import compute_position_fraction, compute_position_size_usd
from src.backtest.engine import _align_rsi_fast
from src.backtest.friction import is_trade_viable


# ── 1. High-Conviction S/R Zone Collision & Tie-Breaking ─────────────────────

def test_signal_collision_prioritizes_stronger_weight():
    """
    If multiple active support zones are in proximity, verify which zone is selected.
    We assert that the stronger zone (higher combined weight) is chosen as the trigger zone,
    and if weights are equal, the closer zone takes priority.
    """
    zone_weak = SRZone(
        price=100.0,
        kind="support",
        timeframe="1d",
        weight=3,
        bar_active_from=0,
        contributing_timeframes=["1d", "4h"],
        combined_weight=5
    )
    
    zone_strong = SRZone(
        price=101.0,
        kind="support",
        timeframe="1d",
        weight=6,
        bar_active_from=0,
        contributing_timeframes=["1d", "4h", "1h"],
        combined_weight=9
    )

    # Both zones are within 2% proximity of 100.5:
    # Weak: abs(100.5 - 100.0) / 100.0 = 0.5% (proximity <= 2%)
    # Strong: abs(100.5 - 101.0) / 101.0 = 0.495% (proximity <= 2%)
    signal = evaluate_signal(
        current_price=100.5,
        current_timestamp_ms=1000,
        active_zones=[zone_weak, zone_strong],  # zone_weak is first in the list
        rsi_by_tf={"1d": 25.0, "4h": 25.0, "1h": 25.0},
        l_price=50.0,
        in_position=False,
    )
    
    # Assert tie-breaking selects the high-weight level (101.0)
    assert signal.action == "buy"
    assert signal.zone is not None
    assert signal.zone.price == 101.0
    assert signal.zone.combined_weight == 9


def test_signal_collision_prioritizes_closer_proximity_if_weights_equal():
    """
    If multiple active support zones have identical combined weights,
    tie-breaking should prioritize the zone closest to the current price.
    """
    zone_far = SRZone(
        price=98.1,
        kind="support",
        timeframe="1d",
        weight=3,
        bar_active_from=0,
        contributing_timeframes=["1d", "4h"],
        combined_weight=5
    )
    
    zone_near = SRZone(
        price=99.9,
        kind="support",
        timeframe="1d",
        weight=3,
        bar_active_from=0,
        contributing_timeframes=["1d", "4h"],
        combined_weight=5
    )

    # Price at 100.0:
    # Far: abs(100 - 98.1) / 98.1 = 1.93% (<= 2%)
    # Near: abs(100 - 99.9) / 99.9 = 0.10% (<= 2%)
    signal = evaluate_signal(
        current_price=100.0,
        current_timestamp_ms=1000,
        active_zones=[zone_far, zone_near],  # zone_far is first in list
        rsi_by_tf={"1d": 25.0, "4h": 25.0},
        l_price=50.0,
        in_position=False,
    )
    
    assert signal.action == "buy"
    assert signal.zone is not None
    assert signal.zone.price == 99.9  # Closest zone chosen


# ── 2. Division-by-Zero Safeguard for S/R Zone Price = 0.0 ───────────────────

def test_price_near_zone_zero_division_safeguard():
    """Verify that a zone price of 0.0 or negative does not raise a ZeroDivisionError."""
    # Should safely return False rather than throwing ZeroDivisionError
    try:
        is_near = _price_near_zone(price=0.01, zone_price=0.0)
        assert is_near is False
    except ZeroDivisionError:
        pytest.fail("ZeroDivisionError raised for zone_price = 0.0")

    # Negative price guard check
    is_near_neg = _price_near_zone(price=0.01, zone_price=-10.0)
    assert is_near_neg is False


# ── 3. Position Fraction Bounds Compression (UPrice ≈ LPrice) ─────────────────

def test_position_fraction_highly_compressed_bounds():
    """Verify position sizing under extreme volatility compression behaves stably."""
    fraction = compute_position_fraction(
        current_price=1.005,
        l_price=1.00000000,
        u_price=1.00000001,
    )
    # Price is way above compressed upper bound, fraction must clamp to 0.0 cleanly
    assert fraction == 0.0

    # Test equal bounds
    fraction_equal = compute_position_fraction(
        current_price=1.0,
        l_price=1.0,
        u_price=1.0,
    )
    assert fraction_equal == 0.0


# ── 4. Timeframe Alignment Out-of-Bounds (Early Execution Timestamp) ──────────

def test_align_rsi_fast_out_of_bounds_underflow():
    """
    Verify that querying a timestamp before any structural data exists
    returns None instead of wrapping to the last element (look-ahead bias safeguard).
    """
    rsi_lookup = {
        "1w": ([1000, 2000, 3000], [45.0, 50.0, 55.0])
    }
    
    # 500 is before the first timestamp of 1000
    aligned = _align_rsi_fast(rsi_lookup, ts_ms=500)
    assert aligned["1w"] is None  # Must not wrap to 55.0 (index -1 in Python lists)


# ── 5. Negative Spread Rejection (Inverted S/R Levels) ─────────────────────────

def test_is_trade_viable_negative_spread():
    """Verify that an inverted or negative spread is immediately rejected."""
    # Resistance price (95) is below support price (100)
    viable = is_trade_viable(entry_price=100.0, target_exit_price=95.0)
    assert viable is False


# ── 6. Capital Allocation Inconsistencies for Undefined Symbols ───────────────

def test_capital_allocation_undefined_symbol_behavior():
    """Verify that undefined symbols are sized consistently across modules."""
    from src.config.settings import ASSET_ALLOCATION

    symbol = "RANDOMCOIN/USDT"
    # Ensure it's not configured
    if symbol in ASSET_ALLOCATION:
        del ASSET_ALLOCATION[symbol]

    # Sizing should return 0.0 because allocation fraction defaults to 0.0
    size = compute_position_size_usd(
        symbol=symbol,
        current_price=100.0,
        total_capital=10000.0,
        l_price=50.0,
        u_price=150.0
    )
    assert size == 0.0
