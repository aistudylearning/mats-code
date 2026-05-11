"""Tests for Signal 0.2 entry/exit logic — Volume Confirmation upgrade."""
import pytest

from src.strategy.signals import evaluate_signal
from src.strategy.sr_levels import SRZone
from src.config.settings import VOLUME_SPIKE_MULTIPLIER


def _make_zone(
    price: float, kind: str, timeframes: list[str],
    combined_weight: int, weight: int,
) -> SRZone:
    return SRZone(
        price=price,
        kind=kind,
        timeframe=timeframes[0],
        weight=weight,
        bar_active_from=0,
        contributing_timeframes=timeframes,
        combined_weight=combined_weight,
    )


HC_SUPPORT = _make_zone(100.0, "support", ["1d", "4h"], combined_weight=5, weight=3)
HC_RESISTANCE = _make_zone(120.0, "resistance", ["1d", "4h"], combined_weight=5, weight=3)


# ── Entry tests (V0.2) ──────────────────────────────────────────────


def test_buy_v02_accepted_with_volume_spike():
    """V0.2 Entry: price near support + oversold RSI + volume > 1.5× SMA → buy."""
    signal = evaluate_signal(
        current_price=101.0,
        current_timestamp_ms=1000,
        active_zones=[HC_SUPPORT],
        rsi_by_tf={"1d": 25.0, "4h": 28.0},
        l_price=50.0,
        in_position=False,
        version="0.2",
        current_volume=2000.0,
        volume_sma=1000.0,  # 2000 > 1.5 × 1000 = 1500 ✓
    )
    assert signal.action == "buy"


def test_buy_v02_rejected_insufficient_volume():
    """V0.2 Entry: Rejected if volume ≤ 1.5× SMA even with perfect price/RSI."""
    signal = evaluate_signal(
        current_price=101.0,
        current_timestamp_ms=1000,
        active_zones=[HC_SUPPORT],
        rsi_by_tf={"1d": 25.0, "4h": 28.0},
        l_price=50.0,
        in_position=False,
        version="0.2",
        current_volume=1200.0,
        volume_sma=1000.0,  # 1200 ≤ 1500 → rejected
    )
    assert signal.action == "hold"


def test_buy_v02_rejected_volume_exactly_at_threshold():
    """V0.2 Entry: Volume exactly at the multiplier threshold should be rejected."""
    sma = 1000.0
    exact_threshold = sma * VOLUME_SPIKE_MULTIPLIER  # 1500.0
    signal = evaluate_signal(
        current_price=101.0,
        current_timestamp_ms=1000,
        active_zones=[HC_SUPPORT],
        rsi_by_tf={"1d": 25.0, "4h": 28.0},
        l_price=50.0,
        in_position=False,
        version="0.2",
        current_volume=exact_threshold,
        volume_sma=sma,
    )
    assert signal.action == "hold"


def test_buy_v02_rejected_missing_volume():
    """V0.2 Entry: Rejected if current_volume is None."""
    signal = evaluate_signal(
        current_price=101.0,
        current_timestamp_ms=1000,
        active_zones=[HC_SUPPORT],
        rsi_by_tf={"1d": 25.0, "4h": 28.0},
        l_price=50.0,
        in_position=False,
        version="0.2",
        current_volume=None,
        volume_sma=1000.0,
    )
    assert signal.action == "hold"


def test_buy_v02_rejected_missing_volume_sma():
    """V0.2 Entry: Rejected if volume_sma is None."""
    signal = evaluate_signal(
        current_price=101.0,
        current_timestamp_ms=1000,
        active_zones=[HC_SUPPORT],
        rsi_by_tf={"1d": 25.0, "4h": 28.0},
        l_price=50.0,
        in_position=False,
        version="0.2",
        current_volume=2000.0,
        volume_sma=None,
    )
    assert signal.action == "hold"


def test_buy_v02_volume_just_above_threshold():
    """V0.2 Entry: Volume barely above threshold should trigger buy."""
    sma = 1000.0
    just_above = sma * VOLUME_SPIKE_MULTIPLIER + 0.01
    signal = evaluate_signal(
        current_price=101.0,
        current_timestamp_ms=1000,
        active_zones=[HC_SUPPORT],
        rsi_by_tf={"1d": 25.0, "4h": 28.0},
        l_price=50.0,
        in_position=False,
        version="0.2",
        current_volume=just_above,
        volume_sma=sma,
    )
    assert signal.action == "buy"


# ── V0.1 backward compatibility ─────────────────────────────────────


def test_buy_v01_ignores_volume():
    """V0.1 Entry: Volume should be completely ignored — buy on RSI+support only."""
    signal = evaluate_signal(
        current_price=101.0,
        current_timestamp_ms=1000,
        active_zones=[HC_SUPPORT],
        rsi_by_tf={"1d": 25.0, "4h": 28.0},
        l_price=50.0,
        in_position=False,
        version="0.1",
        current_volume=None,
        volume_sma=None,
    )
    assert signal.action == "buy"


# ── Exit tests (V0.2 should not gate exits on volume) ───────────────


def test_sell_resistance_v02_fires_regardless_of_volume():
    """V0.2 Exit: Volume confirmation is only for entry, not exit."""
    signal = evaluate_signal(
        current_price=119.0,
        current_timestamp_ms=2000,
        active_zones=[HC_SUPPORT, HC_RESISTANCE],
        rsi_by_tf={"1d": 75.0, "4h": 72.0},
        l_price=50.0,
        in_position=True,
        version="0.2",
        current_volume=500.0,  # Low volume — shouldn't block exit
        volume_sma=1000.0,
    )
    assert signal.action == "sell_resistance"


def test_stoploss_v02_fires_regardless_of_volume():
    """V0.2 Hard stop-loss fires even with zero volume data."""
    signal = evaluate_signal(
        current_price=45.0,
        current_timestamp_ms=3000,
        active_zones=[HC_SUPPORT, HC_RESISTANCE],
        rsi_by_tf={"1d": 15.0, "4h": 12.0},
        l_price=50.0,
        in_position=True,
        version="0.2",
        current_volume=None,
        volume_sma=None,
    )
    assert signal.action == "sell_stoploss"
