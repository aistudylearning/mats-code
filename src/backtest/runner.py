"""
Parallel backtest runner.

Spec reference: Section 1 (joblib), Section 7 (Shared Capital Pool Rule).

Uses joblib to run backtests across assets in parallel (not across time).
Each asset runs its own independent backtest using its own AC_i capital slice.
Portfolio P&L = sum of all asset P&Ls.
"""
from __future__ import annotations

from joblib import Parallel, delayed

from src.backtest.engine import BacktestResult, run_backtest
from src.config.settings import (
    ASSET_ALLOCATION,
    DEFAULT_INITIAL_CAPITAL,
    DATA_ROOT,
    MVP_ASSETS,
)
from src.utils.logger import get_logger

log = get_logger(__name__)


def run_portfolio_backtest(
    total_capital: float = DEFAULT_INITIAL_CAPITAL,
    symbols: list[str] = MVP_ASSETS,
    execution_tfs: list[str] | None = None,
    data_root: str = DATA_ROOT,
    signal_version: str = "0.1",
    proximity_pct: float | None = None,
    n_jobs: int = -1,
    export_csv: bool = False,
    export_html: bool = False,
) -> dict[str, dict[str, BacktestResult]]:
    """
    Run backtests for all specified assets and timeframes in a single parallel pool.

    Each asset receives its own capital slice (AC_i) from total_capital.
    Cross-asset capital borrowing is not modelled in Signal 0.1.

    Args:
        symbols:       List of symbols to backtest (defaults to all MVP assets).
        total_capital: Total portfolio capital in USD.
        data_root:     Root directory for parquet data.
        n_jobs:        Number of parallel jobs (-1 = all CPU cores).

    Returns:
        Dict mapping timeframe → symbol → BacktestResult.
    """
    if execution_tfs is None:
        execution_tfs = ["1h"]
    if symbols is None:
        symbols = list(ASSET_ALLOCATION.keys())

    # Create a flat list of tasks to ensure perfect load balancing
    tasks = [(sym, tf) for tf in execution_tfs for sym in symbols]

    log.info(f"Starting portfolio backtest | capital={total_capital:.2f} | tasks={len(tasks)} (assets={len(symbols)}, timeframes={len(execution_tfs)})")

    results_list: list[BacktestResult] = Parallel(n_jobs=n_jobs)(
        delayed(run_backtest)(sym, total_capital, data_root, signal_version, proximity_pct, execution_tf=tf)
        for sym, tf in tasks
    )

    # Group results by timeframe: {tf: {symbol: result}}
    grouped_results: dict[str, dict[str, BacktestResult]] = {tf: {} for tf in execution_tfs}
    for r, (sym, tf) in zip(results_list, tasks):
        grouped_results[tf][sym] = r

    # Print summary per timeframe
    for tf in execution_tfs:
        tf_results = grouped_results[tf]
        total_pnl = sum(r.final_capital - r.initial_capital for r in tf_results.values())
        total_return_pct = (total_pnl / total_capital) * 100 if total_capital > 0 else 0.0
        total_trades = sum(r.total_trades for r in tf_results.values())

        log.info(
            f"\n{'='*50}\n"
            f"SUMMARY [{tf}]\n"
            f"{'='*50}\n"
            f"  Assets       : {len(symbols)}\n"
            f"  Total Capital: {total_capital:.2f} USD\n"
            f"  Total PnL    : {total_pnl:+.2f} USD\n"
            f"  Total Return : {total_return_pct:+.2f}%\n"
            f"  Total Trades : {total_trades}\n"
            f"{'='*50}"
        )
        for sym, r in tf_results.items():
            print(f"  [{tf}] {sym}: {r.total_return_pct:+.2f}% return | {r.total_trades} trades")

    if export_csv:
        from src.utils.exporter import export_trades_to_csv
        # Flatten all timeframe results for CSV export
        flat_results = {}
        for tf, r_dict in grouped_results.items():
            for sym, r in r_dict.items():
                flat_results[f"{tf}_{sym}"] = r
        export_trades_to_csv(flat_results)

    if export_html:
        from src.utils.html_exporter import export_multi_tf_html
        export_multi_tf_html(grouped_results, data_root=data_root)

    return grouped_results
