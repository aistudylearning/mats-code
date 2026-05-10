"""
MATS Strategy A — Signal 0.1 & 0.2
MVP entry point.

Usage:
  # Step 1: Fetch data for all 50 assets
  python3 main.py fetch

  # Step 2: Run Signal 0.1 backtest on BTC/USDT and save to CSV
  python3 main.py backtest --signal 0.1 --csv

  # Step 3: Run full Signal 0.2 portfolio backtest
  python3 main.py portfolio --signal 0.2 --csv

  # Step 4: Run parameter sweep to test different S/R proximity values
  python3 main.py sweep --signal 0.2
"""
from __future__ import annotations

import argparse
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


def cmd_fetch(args: argparse.Namespace) -> None:
    """Fetch and store OHLCV data for all timeframes and symbols in parallel."""
    log.info(f"Fetching data for {len(MVP_ASSETS)} assets | {_SINCE.date()} → {_UNTIL.date()}")
    fetch_all_parallel(
        symbols=MVP_ASSETS,
        timeframes=TIMEFRAMES,
        since_dt=_SINCE,
        until_dt=_UNTIL,
        root=DATA_ROOT,
    )


def cmd_backtest(args: argparse.Namespace) -> None:
    """Run a single-asset backtest."""
    symbol = "BTC/USDT"
    result = run_backtest(
        symbol=symbol,
        initial_capital=DEFAULT_INITIAL_CAPITAL,
        data_root=DATA_ROOT,
        signal_version=args.signal,
        execution_tf=args.timeframe,
    )
    print(f"\nFinal Capital : {result.final_capital:.2f} USD")
    print(f"Total Return  : {result.total_return_pct:+.2f}% (Contribution to Portfolio)")
    print(f"Asset Return  : {result.isolated_return_pct:+.2f}% (On its allocated capital)")
    print(f"Trades        : {result.total_trades}")
    print(f"Win Rate      : {result.win_rate_pct:.1f}%")
    print(f"Max Drawdown  : {result.max_drawdown_pct:.2f}%")

    if args.csv:
        from src.utils.exporter import export_trades_to_csv
        export_trades_to_csv(result)


def cmd_portfolio(args: argparse.Namespace) -> None:
    """Run the full portfolio backtest across all MVP assets in parallel."""
    results = run_portfolio_backtest(
        total_capital=DEFAULT_INITIAL_CAPITAL,
        symbols=MVP_ASSETS,
        data_root=DATA_ROOT,
        signal_version=args.signal,
        export_csv=args.csv,
        export_html=args.html,
        execution_tf=args.timeframe,
    )
    for symbol, r in results.items():
        print(f"\n{symbol}:")
        print(f"  Return (Port): {r.total_return_pct:+.2f}%")
        print(f"  Return (Iso) : {r.isolated_return_pct:+.2f}%")
        print(f"  Trades       : {r.total_trades}")
        print(f"  Win Rate     : {r.win_rate_pct:.1f}%")
        print(f"  Max DD   : {r.max_drawdown_pct:.2f}%")


def cmd_sweep(args: argparse.Namespace) -> None:
    """Sweep S/R proximity values and print comparison."""
    proximities = [0.01, 0.02, 0.03, 0.04, 0.05]
    log.info(f"Starting parameter sweep for proximity values: {proximities}")
    
    best_return = -float('inf')
    best_pct = 0.0
    
    results_summary = []
    
    for pct in proximities:
        log.info(f"\n{'='*40}\nTesting Proximity: {pct*100:.1f}%\n{'='*40}")
        res = run_portfolio_backtest(
            total_capital=DEFAULT_INITIAL_CAPITAL,
            data_root=DATA_ROOT,
            signal_version=args.signal,
            proximity_pct=pct,
            export_csv=False,
        )
        
        total_pnl = sum(r.final_capital - r.initial_capital for r in res.values())
        total_ret = (total_pnl / DEFAULT_INITIAL_CAPITAL) * 100
        total_trades = sum(r.total_trades for r in res.values())
        
        results_summary.append((pct, total_ret, total_trades))
        
        if total_ret > best_return:
            best_return = total_ret
            best_pct = pct

    print("\n\n=== SWEEP RESULTS ===")
    print(f"{'Proximity':<12} | {'Total Return':<15} | {'Total Trades'}")
    print("-" * 45)
    for pct, ret, trades in results_summary:
        print(f"{pct*100:>8.1f}%   | {ret:>14.2f}% | {trades:>12}")
        
    print(f"\nBest Proximity: {best_pct*100:.1f}% (+{best_return:.2f}%)")


def main() -> None:
    parser = argparse.ArgumentParser(description="MATS Strategy A Backtester")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # fetch command
    subparsers.add_parser("fetch", help="Fetch OHLCV data")

    # backtest command
    parser_bt = subparsers.add_parser("backtest", help="Run backtest on BTC/USDT")
    parser_bt.add_argument("--signal", choices=["0.1", "0.2"], default="0.1", help="Signal version")
    parser_bt.add_argument("--csv", action="store_true", help="Export trade log to CSV")
    parser_bt.add_argument("--timeframe", "--tf", type=str, default="1h", choices=["15m", "30m", "1h", "2h", "4h"], help="Signal execution timeframe (default: 1h)")

    # portfolio command
    parser_pf = subparsers.add_parser("portfolio", help="Run portfolio backtest")
    parser_pf.add_argument("--signal", choices=["0.1", "0.2"], default="0.1", help="Signal version")
    parser_pf.add_argument("--csv", action="store_true", help="Export trades to CSV")
    parser_pf.add_argument("--html", action="store_true", help="Export interactive HTML report")
    parser_pf.add_argument("--timeframe", "--tf", type=str, default="1h", choices=["15m", "30m", "1h", "2h", "4h"], help="Signal execution timeframe (default: 1h)")

    # sweep command
    parser_sw = subparsers.add_parser("sweep", help="Sweep S/R proximity parameters")
    parser_sw.add_argument("--signal", choices=["0.1", "0.2"], default="0.1", help="Signal version")

    args = parser.parse_args()

    commands = {
        "fetch": cmd_fetch,
        "backtest": cmd_backtest,
        "portfolio": cmd_portfolio,
        "sweep": cmd_sweep,
    }

    commands[args.command](args)


if __name__ == "__main__":
    main()
