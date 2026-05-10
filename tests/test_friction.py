"""Tests for fee/slippage model and trade rejection — Section 8 (Locked)."""
import pytest

from src.backtest.friction import (
    apply_entry_friction,
    apply_exit_friction,
    compute_pnl,
    is_trade_viable,
)
from src.config.settings import TOTAL_FRICTION_PER_EXEC, ROUND_TRIP_FRICTION


def test_entry_friction_adds_cost():
    """Effective entry price must be higher than raw price."""
    raw = 50000.0
    effective = apply_entry_friction(raw)
    assert effective > raw
    assert abs(effective - raw * (1 + TOTAL_FRICTION_PER_EXEC)) < 1e-6


def test_exit_friction_reduces_proceeds():
    """Effective exit price must be lower than raw price."""
    raw = 60000.0
    effective = apply_exit_friction(raw)
    assert effective < raw
    assert abs(effective - raw * (1 - TOTAL_FRICTION_PER_EXEC)) < 1e-6


def test_total_friction_is_015_pct():
    """Total friction per execution = taker fee (0.10%) + slippage (0.05%) = 0.15%."""
    assert abs(TOTAL_FRICTION_PER_EXEC - 0.0015) < 1e-9


def test_round_trip_friction_is_030_pct():
    """Round-trip friction = 2 × 0.15% = 0.30%."""
    assert abs(ROUND_TRIP_FRICTION - 0.003) < 1e-9


def test_trade_viable_when_spread_exceeds_threshold():
    """Trade is viable if spread > 0.30%."""
    # Spread: (50150 - 50000) / 50000 = 0.30% — right at the boundary, should reject
    assert is_trade_viable(50000.0, 50150.0) is False  # exactly at threshold
    # Just above: spread ≈ 0.31%
    assert is_trade_viable(50000.0, 50155.0) is True


def test_trade_rejected_when_spread_at_or_below_threshold():
    """Trade must be rejected at exactly the round-trip friction threshold."""
    entry = 100.0
    exit_at_threshold = entry * (1 + ROUND_TRIP_FRICTION)
    assert is_trade_viable(entry, exit_at_threshold) is False


def test_compute_pnl_profitable_trade():
    """A clean profitable trade should return positive PnL."""
    pnl = compute_pnl(
        entry_price=50000.0,
        exit_price=55000.0,
        position_size_usd=5000.0,
    )
    assert pnl > 0, f"Expected profit, got {pnl}"


def test_compute_pnl_losing_trade():
    """A stop-loss exit at lower price should return negative PnL."""
    pnl = compute_pnl(
        entry_price=50000.0,
        exit_price=40000.0,
        position_size_usd=5000.0,
    )
    assert pnl < 0, f"Expected loss, got {pnl}"


def test_compute_pnl_friction_reduces_profit():
    """PnL after friction should be less than naive gross profit."""
    entry = 50000.0
    exit_ = 55000.0
    pos = 5000.0
    naive_return = (exit_ - entry) / entry
    pnl = compute_pnl(entry, exit_, pos)
    naive_pnl = pos * naive_return
    assert pnl < naive_pnl, "Friction must reduce the profitable PnL"
