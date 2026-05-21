"""
Signal 0.1 — Entry and Exit logic.

Spec reference: Section 6 (Signal Logic — Locked).

Entry (Buy) — both must be true on the 1H bar:
  1. Close price is within ±2% of a High-Conviction S/R Support Zone (combined weight ≥ 5)
  2. At least one RSI from the contributing timeframes of that zone is < 30

Exit (Sell) — either triggers on the 1H bar:
  1. Close price within ±2% of a High-Conviction S/R Resistance Zone AND
     at least one RSI from the composing timeframes is > 70
  2. Hard Stop-Loss: price falls below LPrice_i (rolling lower bound)

RSI Timeframe Alignment Rule (CTO Correction v2):
  - RSI check must be on the SAME timeframe(s) that compose the S/R zone
  - Do NOT use 1H RSI when the S/R zone is composed of weekly/monthly levels
"""
from __future__ import annotations

from dataclasses import dataclass

from src.config.settings import (
    HIGH_CONVICTION_THRESHOLD,
    SR_PROXIMITY_PCT,
    VOLUME_SPIKE_MULTIPLIER,
    SR_WEIGHTS,
)
from src.strategy.sr_levels import SRZone
from src.utils.logger import get_logger

log = get_logger(__name__)


@dataclass
class SignalResult:
    """Outcome of evaluating Signal 0.1 at a single 1H bar."""
    action: str           # 'buy', 'sell_resistance', 'sell_stoploss', 'hold'
    price: float          # Current close price at signal bar
    timestamp_ms: int     # Bar timestamp
    zone: SRZone | None = None  # The triggering S/R zone (if any)
    rsi_values: dict[str, float] | None = None  # RSI values used in evaluation
    notes: str = ""


def _price_near_zone(price: float, zone_price: float, proximity_pct: float = SR_PROXIMITY_PCT) -> bool:
    """True if price is within ±proximity_pct of zone_price."""
    if zone_price <= 0:
        return False
    return abs(price - zone_price) / zone_price <= proximity_pct


def _rsi_confirms_entry(zone: SRZone, rsi_by_tf: dict[str, float | None]) -> bool:
    """
    Entry RSI check: check the RSI of the strongest contributing timeframe of the S/R zone.
    """
    if not zone.contributing_timeframes:
        return False
    strongest_tf = max(zone.contributing_timeframes, key=lambda tf: SR_WEIGHTS.get(tf, 0))
    rsi = rsi_by_tf.get(strongest_tf)
    return rsi is not None and rsi < 30


def _rsi_confirms_exit(zone: SRZone, rsi_by_tf: dict[str, float | None]) -> bool:
    """
    Exit RSI check: check the RSI of the strongest contributing timeframe of the S/R zone.
    """
    if not zone.contributing_timeframes:
        return False
    strongest_tf = max(zone.contributing_timeframes, key=lambda tf: SR_WEIGHTS.get(tf, 0))
    rsi = rsi_by_tf.get(strongest_tf)
    return rsi is not None and rsi > 70


def evaluate_signal(
    current_price: float,
    current_timestamp_ms: int,
    active_zones: list[SRZone],
    rsi_by_tf: dict[str, float | None],
    l_price: float,
    in_position: bool,
    proximity_pct: float = SR_PROXIMITY_PCT,
    version: str = "0.1",
    current_volume: float | None = None,
    volume_sma: float | None = None,
) -> SignalResult:
    """
    Evaluate Signal logic at the current 1H bar.

    Args:
        current_price:        Close price of the current 1H bar.
        current_timestamp_ms: Timestamp of the current bar (Unix ms).
        active_zones:         All S/R zones visible at this bar (look-ahead-free).
        rsi_by_tf:            Dict {timeframe: rsi_value} for all timeframes at this bar.
        l_price:              Rolling lower bound (hard stop-loss level).
        in_position:          Whether we currently hold a position.
        proximity_pct:        Percentage proximity threshold to S/R zone.
        version:              Signal version ('0.1' or '0.2').
        current_volume:       Current bar volume (required for V0.2).
        volume_sma:           Volume SMA value (required for V0.2).

    Returns:
        SignalResult with action: 'buy', 'sell_resistance', 'sell_stoploss', or 'hold'.
    """
    # Sort high-conviction zones:
    # 1. Primary key: combined_weight descending (stronger level takes priority)
    # 2. Secondary key: absolute distance from current_price ascending (closer level takes priority)
    high_conviction = sorted(
        [z for z in active_zones if z.combined_weight >= HIGH_CONVICTION_THRESHOLD],
        key=lambda z: (-z.combined_weight, abs(current_price - z.price))
    )

    # --- Hard Stop-Loss (takes priority over all other exit conditions) ---
    if in_position and current_price < l_price:
        return SignalResult(
            action="sell_stoploss",
            price=current_price,
            timestamp_ms=current_timestamp_ms,
            notes=f"Price {current_price:.2f} < LPrice {l_price:.2f}",
        )

    # --- Exit: Resistance zone + overbought RSI ---
    if in_position:
        for zone in high_conviction:
            if zone.kind == "resistance" and _price_near_zone(current_price, zone.price, proximity_pct):
                if _rsi_confirms_exit(zone, rsi_by_tf):
                    return SignalResult(
                        action="sell_resistance",
                        price=current_price,
                        timestamp_ms=current_timestamp_ms,
                        zone=zone,
                        rsi_values=rsi_by_tf,
                        notes=(
                            f"Near resistance {zone.price:.2f} "
                            f"(tfs={zone.contributing_timeframes}, weight={zone.combined_weight})"
                        ),
                    )

    # --- Entry: Support zone + oversold RSI ---
    if not in_position:
        for zone in high_conviction:
            if zone.kind == "support" and _price_near_zone(current_price, zone.price, proximity_pct):
                if _rsi_confirms_entry(zone, rsi_by_tf):
                    
                    # Signal 0.2: Volume Confirmation Check
                    if version == "0.2":
                        if current_volume is None or volume_sma is None:
                            continue
                        if current_volume <= (volume_sma * VOLUME_SPIKE_MULTIPLIER):
                            continue # Volume too low, reject signal
                            
                    return SignalResult(
                        action="buy",
                        price=current_price,
                        timestamp_ms=current_timestamp_ms,
                        zone=zone,
                        rsi_values=rsi_by_tf,
                        notes=(
                            f"Near support {zone.price:.2f} "
                            f"(tfs={zone.contributing_timeframes}, weight={zone.combined_weight})"
                        ),
                    )

    return SignalResult(
        action="hold",
        price=current_price,
        timestamp_ms=current_timestamp_ms,
    )
