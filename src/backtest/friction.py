"""
Fee and slippage model + trade rejection constraint.

Spec reference: Section 8 (Fee & Slippage Structure — Locked).

Base friction model:
  - Exchange fee (taker): 0.10% per execution
  - Slippage (flat MVP):  0.05% per execution
  - Total per execution:  0.15%
  - Total round trip:     0.30%

Trade Rejection Constraint:
  If spread between entry (support) and exit (resistance) <= 0.30%, reject the trade.
  No trade is taken that cannot mathematically profit after friction.
"""
from __future__ import annotations

from src.config.settings import (
    MIN_SPREAD_TO_TRADE,
    ROUND_TRIP_FRICTION,
    SLIPPAGE_FLAT,
    TAKER_FEE,
    TOTAL_FRICTION_PER_EXEC,
)
from src.utils.logger import get_logger

log = get_logger(__name__)


def apply_entry_friction(price: float) -> float:
    """
    Return the effective entry price after fee + slippage (buyer pays more).

    Effective entry = price × (1 + total_friction_per_exec)
    """
    return price * (1.0 + TOTAL_FRICTION_PER_EXEC)


def apply_exit_friction(price: float) -> float:
    """
    Return the effective exit price after fee + slippage (seller receives less).

    Effective exit = price × (1 - total_friction_per_exec)
    """
    return price * (1.0 - TOTAL_FRICTION_PER_EXEC)


def is_trade_viable(entry_price: float, target_exit_price: float) -> bool:
    """
    Check the Trade Rejection Constraint.

    A trade is viable only if the spread between the support zone (entry) and
    resistance zone (target exit) exceeds the round-trip friction (0.30%).

    Args:
        entry_price:       Identified support zone price (potential entry).
        target_exit_price: Identified resistance zone price (potential exit).

    Returns:
        True if the trade is mathematically profitable after friction.
    """
    if entry_price <= 0:
        return False
    spread = (target_exit_price - entry_price) / entry_price
    viable = spread > MIN_SPREAD_TO_TRADE
    if not viable:
        log.debug(
            f"Trade rejected: spread={spread:.4%} <= min_required={MIN_SPREAD_TO_TRADE:.4%} "
            f"(entry={entry_price:.2f}, target={target_exit_price:.2f})"
        )
    return viable


def compute_pnl(
    entry_price: float,
    exit_price: float,
    position_size_usd: float,
) -> float:
    """
    Compute net PnL for a completed trade after applying friction on both legs.

    Args:
        entry_price:       Raw entry price (pre-friction).
        exit_price:        Raw exit price (pre-friction).
        position_size_usd: USD value of the position at entry.

    Returns:
        Net PnL in USD (positive = profit, negative = loss).
    """
    effective_entry = apply_entry_friction(entry_price)
    effective_exit = apply_exit_friction(exit_price)
    qty = position_size_usd / effective_entry
    gross_proceeds = qty * effective_exit
    pnl = gross_proceeds - position_size_usd
    return pnl
