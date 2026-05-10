"""
Export utilities for saving backtest results to disk.
"""
from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path

from src.backtest.engine import BacktestResult, Trade
from src.utils.logger import get_logger

log = get_logger(__name__)


def _format_timestamp(ts_ms: int | None) -> str:
    if not ts_ms:
        return ""
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S')


def export_trades_to_csv(
    results: BacktestResult | dict[str, BacktestResult],
    output_dir: str = "data/results",
    filename: str | None = None,
) -> str:
    """
    Export all trades from a BacktestResult or a portfolio of results to a CSV file.
    
    Args:
        results:    Single BacktestResult or dict of multiple results.
        output_dir: Directory to save the CSV.
        filename:   Optional override for filename. Defaults to trades_YYYYMMDD_HHMMSS.csv.
        
    Returns:
        The absolute path to the saved CSV file.
    """
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    
    if filename is None:
        ts_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"trades_{ts_str}.csv"
        
    filepath = Path(output_dir) / filename
    
    # Flatten all trades
    all_trades: list[Trade] = []
    if isinstance(results, BacktestResult):
        all_trades = results.trades
    else:
        for r in results.values():
            all_trades.extend(r.trades)
            
    # Sort by entry timestamp
    all_trades.sort(key=lambda t: t.entry_timestamp_ms)
    
    headers = [
        "symbol", "entry_time_utc", "entry_price", "effective_entry_price",
        "position_size_usd", "zone_weight", "exit_time_utc", "exit_price",
        "effective_exit_price", "pnl_usd", "exit_reason"
    ]
    
    with open(filepath, mode="w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        
        for t in all_trades:
            writer.writerow([
                t.symbol,
                _format_timestamp(t.entry_timestamp_ms),
                f"{t.entry_price:.6f}",
                f"{t.effective_entry_price:.6f}",
                f"{t.position_size_usd:.2f}",
                t.entry_zone_weight,
                _format_timestamp(t.exit_timestamp_ms),
                f"{t.exit_price:.6f}" if t.exit_price else "",
                f"{t.effective_exit_price:.6f}" if t.effective_exit_price else "",
                f"{t.pnl:.2f}" if t.pnl else "",
                t.exit_reason,
            ])
            
    log.info(f"Exported {len(all_trades)} trades to {filepath.absolute()}")
    return str(filepath.absolute())
