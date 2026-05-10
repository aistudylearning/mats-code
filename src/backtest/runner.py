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
    data_root: str = DATA_ROOT,
    signal_version: str = "0.1",
    proximity_pct: float | None = None,
    n_jobs: int = -1,
    export_csv: bool = False,
    export_html: bool = False,
    execution_tf: str = "1h",
) -> dict[str, BacktestResult]:
    """
    Run backtests for all specified assets in parallel and aggregate results.

    Each asset receives its own capital slice (AC_i) from total_capital.
    Cross-asset capital borrowing is not modelled in Signal 0.1.

    Args:
        symbols:       List of symbols to backtest (defaults to all MVP assets).
        total_capital: Total portfolio capital in USD.
        data_root:     Root directory for parquet data.
        n_jobs:        Number of parallel jobs (-1 = all CPU cores).

    Returns:
        Dict mapping symbol → BacktestResult.
    """
    if symbols is None:
        symbols = list(ASSET_ALLOCATION.keys())

    log.info(f"Starting portfolio backtest | capital={total_capital:.2f} | assets={symbols}")

    results_list: list[BacktestResult] = Parallel(n_jobs=n_jobs)(
        delayed(run_backtest)(symbol, total_capital, data_root, signal_version, proximity_pct, execution_tf=execution_tf)
        for symbol in symbols
    )

    results: dict[str, BacktestResult] = {r.symbol: r for r in results_list}

    # Portfolio-level summary
    total_pnl = sum(r.final_capital - r.initial_capital for r in results.values())
    total_return_pct = (total_pnl / total_capital) * 100 if total_capital > 0 else 0.0
    total_trades = sum(r.total_trades for r in results.values())

    log.info(
        f"\n{'='*50}\n"
        f"PORTFOLIO SUMMARY\n"
        f"{'='*50}\n"
        f"  Assets       : {', '.join(symbols)}\n"
        f"  Total Capital: {total_capital:.2f} USD\n"
        f"  Total PnL    : {total_pnl:+.2f} USD\n"
        f"  Total Return : {total_return_pct:+.2f}%\n"
        f"  Total Trades : {total_trades}\n"
        f"{'='*50}"
    )

    if export_csv:
        from src.utils.exporter import export_trades_to_csv
        export_trades_to_csv(results)

    if export_html:
        from src.utils.html_exporter import export_results_to_html
        export_results_to_html(results, data_root=data_root)

    return results
