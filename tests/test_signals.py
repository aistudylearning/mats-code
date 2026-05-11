"""Tests for Signal 0.1 entry/exit logic — Section 6 (Locked)."""
import pytest

from src.strategy.signals import evaluate_signal
from src.strategy.sr_levels import SRZone



def _make_zone(price: float, kind: str, timeframes: list[str], combined_weight: int, weight: int) -> SRZone:
    z = SRZone(
        price=price,
        kind=kind,
        timeframe=timeframes[0],
        weight=weight,
        bar_active_from=0,
        contributing_timeframes=timeframes,
        combined_weight=combined_weight,
    )
    return z


HC_SUPPORT = _make_zone(100.0, "support", ["1d", "4h"], combined_weight=5, weight=3)
HC_RESISTANCE = _make_zone(120.0, "resistance", ["1d", "4h"], combined_weight=5, weight=3)


def test_buy_signal_fires_at_oversold_support():
    """Entry: price near support + oversold RSI on contributing timeframe."""
    signal = evaluate_signal(
        current_price=101.0,        # within ±2% of 100
        current_timestamp_ms=1000,
        active_zones=[HC_SUPPORT, HC_RESISTANCE],
        rsi_by_tf={"1d": 25.0, "4h": 28.0},  # both oversold
        l_price=50.0,
        in_position=False,
    )
    assert signal.action == "buy"


def test_no_buy_if_rsi_not_oversold():
    """No entry if RSI is above 30 for all contributing timeframes."""
    signal = evaluate_signal(
        current_price=101.0,
        current_timestamp_ms=1000,
        active_zones=[HC_SUPPORT, HC_RESISTANCE],
        rsi_by_tf={"1d": 50.0, "4h": 55.0},  # not oversold
        l_price=50.0,
        in_position=False,
    )
    assert signal.action == "hold"


def test_no_buy_if_price_far_from_support():
    """No entry if price is > ±2% away from support zone."""
    signal = evaluate_signal(
        current_price=85.0,         # ~15% below support at 100
        current_timestamp_ms=1000,
        active_zones=[HC_SUPPORT, HC_RESISTANCE],
        rsi_by_tf={"1d": 20.0, "4h": 18.0},
        l_price=50.0,
        in_position=False,
    )
    assert signal.action == "hold"


def test_sell_at_resistance_overbought():
    """Exit: price near resistance + overbought RSI on contributing timeframe."""
    signal = evaluate_signal(
        current_price=119.0,        # within ±2% of 120
        current_timestamp_ms=2000,
        active_zones=[HC_SUPPORT, HC_RESISTANCE],
        rsi_by_tf={"1d": 75.0, "4h": 72.0},
        l_price=50.0,
        in_position=True,
    )
    assert signal.action == "sell_resistance"


def test_no_sell_if_rsi_not_overbought():
    """No exit at resistance if RSI is below 70 for all contributing timeframes."""
    signal = evaluate_signal(
        current_price=119.0,
        current_timestamp_ms=2000,
        active_zones=[HC_SUPPORT, HC_RESISTANCE],
        rsi_by_tf={"1d": 60.0, "4h": 55.0},
        l_price=50.0,
        in_position=True,
    )
    assert signal.action == "hold"


def test_hard_stoploss_triggers_below_lprice():
    """Hard stop-loss: exit immediately if price < LPrice, regardless of zones."""
    signal = evaluate_signal(
        current_price=45.0,    # below l_price=50
        current_timestamp_ms=3000,
        active_zones=[HC_SUPPORT, HC_RESISTANCE],
        rsi_by_tf={"1d": 15.0, "4h": 12.0},
        l_price=50.0,
        in_position=True,
    )
    assert signal.action == "sell_stoploss"


def test_stoploss_takes_priority_over_resistance():
    """If price is simultaneously below LPrice and near resistance, stoploss wins."""
    signal = evaluate_signal(
        current_price=49.0,    # below l_price=50
        current_timestamp_ms=3000,
        active_zones=[HC_RESISTANCE],
        rsi_by_tf={"1d": 80.0, "4h": 85.0},
        l_price=50.0,
        in_position=True,
    )
    assert signal.action == "sell_stoploss"


def test_rsi_wrong_timeframe_does_not_trigger_entry():
    """
    RSI alignment: if zone is composed of [1d, 4h], 1H RSI alone must NOT trigger.
    """
    signal = evaluate_signal(
        current_price=101.0,
        current_timestamp_ms=1000,
        active_zones=[HC_SUPPORT],
        rsi_by_tf={"1h": 20.0, "1d": 55.0, "4h": 60.0},  # only 1h oversold, not zone TFs
        l_price=50.0,
        in_position=False,
    )
    assert signal.action == "hold"
