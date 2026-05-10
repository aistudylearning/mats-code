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

  # Step 5: Regenerate HTML report from the latest cached backtest results
  python3 main.py report
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
    """Run the full portfolio backtest across all MVP assets, optionally across multiple timeframes."""
    _VALID_TFS = ["15m", "30m", "1h", "2h", "4h"]
    timeframes = args.timeframe if isinstance(args.timeframe, list) else [args.timeframe]
    invalid = [tf for tf in timeframes if tf not in _VALID_TFS]
    if invalid:
        print(f"Error: invalid timeframe(s): {invalid}. Choose from {_VALID_TFS}")
        return

    # Run one full portfolio backtest per requested timeframe
    all_tf_results: dict[str, dict] = {}
    for tf in timeframes:
        log.info(f"Running portfolio backtest for timeframe: {tf}")
        results = run_portfolio_backtest(
            total_capital=DEFAULT_INITIAL_CAPITAL,
            symbols=MVP_ASSETS,
            data_root=DATA_ROOT,
            signal_version=args.signal,
            export_csv=args.csv,
            export_html=False,   # handled below for multi-tf
            execution_tf=tf,
        )
        all_tf_results[tf] = results
        for symbol, r in results.items():
            print(f"  [{tf}] {symbol}: {r.total_return_pct:+.2f}% return | {r.total_trades} trades")

    # Cache the results for fast report generation later
    import joblib
    import os
    os.makedirs("output", exist_ok=True)
    cache_path = os.path.join("output", "latest_results.pkl")
    joblib.dump(all_tf_results, cache_path)
    log.info(f"Saved backtest results cache to: {cache_path}")

    if args.html:
        from src.utils.html_exporter import export_multi_tf_html
        export_multi_tf_html(all_tf_results, data_root=DATA_ROOT)


def cmd_report(args: argparse.Namespace) -> None:
    """Generate an HTML report directly from the most recently cached backtest results."""
    import joblib
    import os
    cache_path = os.path.join("output", "latest_results.pkl")
    
    if not os.path.exists(cache_path):
        log.error(f"Cache file not found at {cache_path}. Please run 'python3 main.py portfolio' first.")
        return
        
    log.info(f"Loading cached backtest results from {cache_path}...")
    try:
        all_tf_results = joblib.load(cache_path)
        from src.utils.html_exporter import export_multi_tf_html
        export_multi_tf_html(all_tf_results, data_root=DATA_ROOT)
    except Exception as e:
        log.error(f"Failed to load cache: {e}")


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
    parser_pf.add_argument(
        "--timeframe", "--tf",
        type=str,
        nargs="+",
        default=["1h"],
        metavar="TF",
        help="One or more signal execution timeframes (e.g. --timeframe 15m 1h 4h). Choices: 15m 30m 1h 2h 4h",
    )

    # sweep command
    parser_sw = subparsers.add_parser("sweep", help="Sweep S/R proximity parameters")
    parser_sw.add_argument("--signal", choices=["0.1", "0.2"], default="0.1", help="Signal version")

    # report command
    parser_rp = subparsers.add_parser("report", help="Regenerate HTML report from cached backtest results")

    args = parser.parse_args()

    commands = {
        "fetch": cmd_fetch,
        "backtest": cmd_backtest,
        "portfolio": cmd_portfolio,
        "sweep": cmd_sweep,
        "report": cmd_report,
    }

    commands[args.command](args)


if __name__ == "__main__":
    main()
