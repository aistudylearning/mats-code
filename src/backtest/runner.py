"""
Parallel backtest runner.

Spec reference: Section 1 (joblib), Section 7 (Shared Capital Pool Rule).

Uses joblib to run backtests across assets in parallel (not across time).
Each asset runs its own independent backtest using its own AC_i capital slice.
Portfolio P&L = sum of all asset P&Ls.

Parallelism strategy:
    - Outer pool: one job per symbol (up to n_jobs workers), parallelized via joblib.
    - Inner loop: all execution timeframes run SEQUENTIALLY within each worker.
    - Rationale: the backtest engine loads ALL timeframe data per symbol for S/R
      computation. With a flat (sym, tf) pool, each task re-reads the same files
      from disk: 500 tasks × 10 files = 5000 disk reads. By grouping all TFs under
      one worker per symbol, each symbol's data is loaded exactly once → 500 reads.
      This shifts the bottleneck from 100% disk back to CPU, where it belongs.
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


def _run_all_tfs_for_symbol(
    sym: str,
    total_capital: float,
    data_root: str,
    signal_version: str,
    proximity_pct: float | None,
    execution_tfs: list[str],
) -> list[tuple[str, str, BacktestResult]]:
    """
    Worker function: load all timeframes for one symbol ONCE, compute S/R
    zones ONCE, then run all execution TF backtests sharing both caches.

    Optimizations vs naive approach (one run_backtest per task):
      - Data loading:  10 TF files read once     (not 10× per TF run)
      - S/R zones:     detect_pivots() runs once  (not 10× per TF run)
      - For BTC 1m (4.5M bars), this saves ~100-200 sec of Python-loop pivots

    Memory management:
      - Frames dict and zones are explicitly deleted after use
      - gc.collect() is called to release memory before this worker
        picks up the next symbol from the joblib pool

    Returns:
        List of (symbol, timeframe, BacktestResult) tuples.
    """
    import gc
    from src.data.storage import load_ohlcv
    from src.config.settings import TIMEFRAMES
    from src.strategy.sr_levels import build_sr_zones
    from src.strategy.indicators import compute_rsi, compute_volume_sma

    # Load all TF data ONCE into RAM
    frames: dict[str, "pl.DataFrame"] = {}
    for tf in TIMEFRAMES:
        df = load_ohlcv(sym, tf, root=data_root)
        if not df.is_empty():
            frames[tf] = df

    # Compute S/R zones ONCE — they depend only on raw OHLCV, not on execution_tf
    zones = build_sr_zones(frames)

    # Compute RSI ONCE per timeframe — RSI on 4.58M 1m rows takes ~2 sec;
    # doing it 10× (once per execution TF) was pure waste.
    # RSI depends ONLY on the close series, not on which TF is being executed.
    base_indicators: dict[str, "pl.DataFrame"] = {}
    for tf, df in frames.items():
        if df.is_empty():
            base_indicators[tf] = df
        else:
            base_indicators[tf] = compute_rsi(df)

    # For each execution TF, create indicator set with volume_sma added
    # only to that TF's DataFrame (needed for Signal 0.2).
    # This is cheap — volume_sma is only computed on the execution TF frame.
    all_indicators: dict[str, dict[str, "pl.DataFrame"]] = {}
    for etf in execution_tfs:
        indicators_for_etf = dict(base_indicators)  # shallow copy — shares DataFrames
        if etf in indicators_for_etf and not indicators_for_etf[etf].is_empty():
            indicators_for_etf[etf] = compute_volume_sma(indicators_for_etf[etf])
        all_indicators[etf] = indicators_for_etf

    # Run all execution TFs using all three caches
    results = []
    for tf in execution_tfs:
        r = run_backtest(
            sym, total_capital, data_root, signal_version, proximity_pct,
            execution_tf=tf,
            preloaded_frames=frames,
            precomputed_zones=zones,
            precomputed_indicators=all_indicators[tf],
        )
        results.append((sym, tf, r))

    # Release memory — critical with 50 symbols and multi-GB 1m data per symbol
    del frames, zones, all_indicators, base_indicators
    gc.collect()

    return results



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
    Run backtests for all specified assets and timeframes in a parallel pool.

    Each asset receives its own capital slice (AC_i) from total_capital.
    Cross-asset capital borrowing is not modelled in Signal 0.1.

    Parallelism: n_jobs workers, each handling one symbol across all TFs.
    This minimizes disk I/O by loading each symbol's data once per worker.

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

    log.info(
        f"Starting portfolio backtest | capital={total_capital:.2f} | "
        f"assets={len(symbols)}, timeframes={len(execution_tfs)} | "
        f"strategy=symbol-parallel (1 disk load per symbol)"
    )

    # One job per symbol — each worker runs all TFs sequentially, loading data once
    all_results: list[list[tuple[str, str, BacktestResult]]] = Parallel(n_jobs=n_jobs)(
        delayed(_run_all_tfs_for_symbol)(
            sym, total_capital, data_root, signal_version, proximity_pct, execution_tfs
        )
        for sym in symbols
    )

    # Flatten and regroup into {tf: {sym: result}}
    grouped_results: dict[str, dict[str, BacktestResult]] = {tf: {} for tf in execution_tfs}
    for sym_results in all_results:
        for sym, tf, r in sym_results:
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
        flat_results = {}
        for tf, r_dict in grouped_results.items():
            for sym, r in r_dict.items():
                flat_results[f"{tf}_{sym}"] = r
        export_trades_to_csv(flat_results)

    if export_html:
        from src.utils.html_exporter import export_multi_tf_html
        export_multi_tf_html(grouped_results, data_root=data_root)

    return grouped_results
