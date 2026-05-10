"""
MATS Strategy A — Signal 0.1
MVP entry point.

Usage:
  # Step 1: Fetch data for BTC/USDT (all required timeframes, 2 years)
  python main.py fetch

  # Step 2: Run backtest on BTC/USDT only
  python main.py backtest

  # Step 3: Run full portfolio backtest (BTC + ETH) in parallel
  python main.py portfolio
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone

from src.backtest.engine import run_backtest
from src.backtest.runner import run_portfolio_backtest
from src.config.settings import DATA_ROOT, DEFAULT_INITIAL_CAPITAL, MVP_ASSETS, TIMEFRAMES
from src.data.fetcher import fetch_all_parallel
from src.utils.logger import get_logger

log = get_logger("mats.main")

# Default fetch window: 2018 to 2026
_SINCE = datetime(2018, 1, 1, tzinfo=timezone.utc)
_UNTIL = datetime(2026, 1, 1, tzinfo=timezone.utc)


def cmd_fetch(symbols: list[str] | None = None) -> None:
    """Fetch and store OHLCV data for all timeframes and symbols in parallel."""
    targets = symbols or MVP_ASSETS
    log.info(f"Fetching data for {targets} | {_SINCE.date()} → {_UNTIL.date()}")
    fetch_all_parallel(
        symbols=targets,
        timeframes=TIMEFRAMES,
        since_dt=_SINCE,
        until_dt=_UNTIL,
        root=DATA_ROOT,
    )


def cmd_backtest(symbol: str = "BTC/USDT") -> None:
    """Run a single-asset backtest."""
    result = run_backtest(symbol=symbol, initial_capital=DEFAULT_INITIAL_CAPITAL, data_root=DATA_ROOT)
    print(f"\nFinal Capital : {result.final_capital:.2f} USD")
    print(f"Total Return  : {result.total_return_pct:+.2f}%")
    print(f"Trades        : {result.total_trades}")
    print(f"Win Rate      : {result.win_rate_pct:.1f}%")
    print(f"Max Drawdown  : {result.max_drawdown_pct:.2f}%")


def cmd_portfolio() -> None:
    """Run the full portfolio backtest across all MVP assets in parallel."""
    results = run_portfolio_backtest(total_capital=DEFAULT_INITIAL_CAPITAL, data_root=DATA_ROOT)
    for symbol, r in results.items():
        print(f"\n{symbol}:")
        print(f"  Return   : {r.total_return_pct:+.2f}%")
        print(f"  Trades   : {r.total_trades}")
        print(f"  Win Rate : {r.win_rate_pct:.1f}%")
        print(f"  Max DD   : {r.max_drawdown_pct:.2f}%")


def main() -> None:
    commands = {
        "fetch":     cmd_fetch,
        "backtest":  cmd_backtest,
        "portfolio": cmd_portfolio,
    }

    if len(sys.argv) < 2 or sys.argv[1] not in commands:
        print("Usage: python3 main.py [fetch|backtest|portfolio]")
        sys.exit(1)

    cmd = sys.argv[1]
    commands[cmd]()


if __name__ == "__main__":
    main()
