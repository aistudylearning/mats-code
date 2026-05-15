"""
Backtesting engine — Signal 0.1 for a single asset.

Spec reference: Sections 1–8.

Flow per 1H bar:
  1. Get active S/R zones (look-ahead-bias-free)
  2. Compute rolling bounds (updated weekly from 1W data)
  3. Gather current RSI values from all timeframes via DuckDB timestamp join
  4. Evaluate Signal 0.1 (entry/exit)
  5. Apply friction, compute PnL
  6. Record trade

Uses DuckDB for cross-timeframe OHLCV+RSI joins by timestamp.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

import duckdb
import polars as pl

from src.backtest.friction import apply_entry_friction, apply_exit_friction, compute_pnl, is_trade_viable
from src.config.settings import (
    DATA_ROOT,
    DEFAULT_INITIAL_CAPITAL,
    TIMEFRAMES,
    SR_WEIGHTS,
)
from src.data.storage import load_ohlcv
from src.strategy.indicators import compute_indicators_all_timeframes
from src.strategy.portfolio import compute_position_size_usd, compute_rolling_bounds
from src.strategy.signals import SignalResult, evaluate_signal
from src.strategy.sr_levels import SRZone, build_sr_zones, get_active_zones
from src.utils.logger import get_logger

log = get_logger(__name__)

_MS_PER_WEEK = 7 * 24 * 3600 * 1000


@dataclass
class Trade:
    """A completed (or open) trade record."""
    symbol: str
    entry_timestamp_ms: int
    entry_price: float            # raw price
    effective_entry_price: float  # after friction
    position_size_usd: float
    exit_timestamp_ms: int | None = None
    exit_price: float | None = None
    effective_exit_price: float | None = None
    pnl: float | None = None
    exit_reason: str = ""         # 'sell_resistance' or 'sell_stoploss'
    entry_zone_weight: int = 0


@dataclass
class BacktestResult:
    """Summary metrics from a completed backtest run."""
    symbol: str
    initial_capital: float
    final_capital: float
    total_return_pct: float
    isolated_return_pct: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate_pct: float
    avg_pnl_per_trade: float
    max_drawdown_pct: float
    trades: list[Trade] = field(default_factory=list)
    sr_zones: list[SRZone] = field(default_factory=list)


def _build_rsi_lookup(
    frames_with_rsi: dict[str, pl.DataFrame],
) -> dict[str, tuple[list[int], list[float | None]]]:
    """
    Pre-compute RSI lookup tables once before the main loop.

    Returns a dict of {timeframe: (sorted_timestamps, rsi_values)} for O(log n)
    binary-search alignment per bar instead of re-filtering DataFrames 17k+ times.
    """
    import bisect
    lookup: dict[str, tuple[list[int], list[float | None]]] = {}
    for tf, df in frames_with_rsi.items():
        if df.is_empty() or "rsi" not in df.columns:
            lookup[tf] = ([], [])
            continue
        ts_list = df["timestamp"].to_list()
        rsi_list = df["rsi"].to_list()
        lookup[tf] = (ts_list, rsi_list)
    return lookup


def _align_rsi_fast(
    rsi_lookup: dict[str, tuple[list[int], list[float | None]]],
    ts_ms: int,
) -> dict[str, float | None]:
    """
    O(log n) RSI alignment using pre-built sorted timestamp arrays.
    Replaces the O(n) per-bar DataFrame filter.
    """
    import bisect
    rsi_by_tf: dict[str, float | None] = {}
    for tf, (ts_list, rsi_list) in rsi_lookup.items():
        if not ts_list:
            rsi_by_tf[tf] = None
            continue
        # Find rightmost timestamp <= ts_ms
        idx = bisect.bisect_right(ts_list, ts_ms) - 1
        if idx < 0:
            rsi_by_tf[tf] = None
        else:
            val = rsi_list[idx]
            rsi_by_tf[tf] = float(val) if val is not None else None
    return rsi_by_tf


def _compute_max_drawdown(equity_curve: list[float]) -> float:
    """Compute maximum drawdown percentage from an equity curve."""
    if not equity_curve:
        return 0.0
    peak = equity_curve[0]
    max_dd = 0.0
    for val in equity_curve:
        if val > peak:
            peak = val
        dd = (peak - val) / peak if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd
    return max_dd * 100.0


def run_backtest(
    symbol: str,
    initial_capital: float = DEFAULT_INITIAL_CAPITAL,
    data_root: str = DATA_ROOT,
    signal_version: str = "0.1",
    proximity_pct: float | None = None,
    execution_tf: str = "1h",
    preloaded_frames: dict[str, pl.DataFrame] | None = None,
    precomputed_zones: list[SRZone] | None = None,
    precomputed_indicators: dict[str, pl.DataFrame] | None = None,
) -> BacktestResult:
    """
    Run a full Signal backtest for a single asset.

    Args:
        symbol:           e.g. 'BTC/USDT'
        initial_capital:  Starting portfolio capital in USD.
        data_root:        Root directory for parquet data.
        preloaded_frames: Optional pre-loaded {tf: DataFrame} dict. When
                          provided, ALL disk reads are skipped entirely.
                          Pass this from the runner when running all TFs
                          for the same symbol to avoid re-reading parquet
                          files on every TF iteration.
        precomputed_zones: Optional pre-computed S/R zones. S/R zones depend
                           only on raw OHLCV frames, NOT on execution_tf.
                           When running multiple TFs for one symbol, compute
                           zones once and pass here to skip the expensive
                           detect_pivots() calls on subsequent TF runs.
        precomputed_indicators: Optional pre-computed {tf: DataFrame_with_RSI}
                                dict. When running multiple TFs for one symbol,
                                RSI only needs computing once per timeframe.

    Returns:
        BacktestResult with all trades and summary metrics.
    """
    log.info(f"=== Starting backtest for {symbol} ===")

    # ------------------------------------------------------------------
    # 1. Load all OHLCV timeframes from parquet (or use preloaded cache)
    # ------------------------------------------------------------------
    if preloaded_frames is not None:
        # Caller loaded data once — skip all disk reads
        frames = preloaded_frames
        for tf, df in frames.items():
            log.info(f"  Loaded {tf}: {len(df)} rows")
    else:
        frames = {}
        for tf in TIMEFRAMES:
            df = load_ohlcv(symbol, tf, root=data_root)
            if not df.is_empty():
                frames[tf] = df
                log.info(f"  Loaded {tf}: {len(df)} rows")
            else:
                log.warning(f"  No data for {tf} — skipping")

    if execution_tf not in frames or frames[execution_tf].is_empty():
        log.error(f"{execution_tf.upper()} data is required for the signal execution timeframe — aborting")
        return BacktestResult(
            symbol=symbol,
            initial_capital=initial_capital,
            final_capital=initial_capital,
            total_return_pct=0.0,
            isolated_return_pct=0.0,
            total_trades=0,
            winning_trades=0,
            losing_trades=0,
            win_rate_pct=0.0,
            avg_pnl_per_trade=0.0,
            max_drawdown_pct=0.0,
            trades=[],
            sr_zones=[],
        )

    # ------------------------------------------------------------------
    # 2. Compute indicators for all timeframes (or use precomputed cache)
    # ------------------------------------------------------------------
    if precomputed_indicators is not None:
        frames_with_indicators = precomputed_indicators
    else:
        frames_with_indicators = compute_indicators_all_timeframes(frames, execution_tf=execution_tf)

    # ------------------------------------------------------------------
    # 3. Build all S/R zones (Algorithm A, all timeframes) — or reuse cache
    # ------------------------------------------------------------------
    if precomputed_zones is not None:
        all_zones = precomputed_zones
    else:
        all_zones = build_sr_zones(frames)
    # Pre-sort zones by bar_active_from once for fast sequential filtering
    all_zones_sorted = sorted(all_zones, key=lambda z: z.bar_active_from)

    # ------------------------------------------------------------------
    # 4. Main backtest loop: iterate over execution_tf bars
    # ------------------------------------------------------------------
    bars_exec = frames_with_indicators[execution_tf]
    weekly_df = frames.get("1w", pl.DataFrame())

    # Pre-compute RSI lookup tables — built once, used 17k+ times
    rsi_lookup = _build_rsi_lookup(frames_with_indicators)

    # Pre-build weekly timestamp/bounds arrays for O(log n) lookups
    if not weekly_df.is_empty():
        weekly_ts = weekly_df["timestamp"].to_list()
        weekly_low = weekly_df["low"].to_list()
        weekly_high = weekly_df["high"].to_list()
    else:
        weekly_ts = weekly_low = weekly_high = []

    capital = initial_capital
    in_position = False
    current_trade: Trade | None = None
    completed_trades: list[Trade] = []
    equity_curve: list[float] = [capital]

    current_week_start_ms: int | None = None
    l_price: float = 0.0
    u_price: float = float("inf")

    # Pointer for zone activation: zones are sorted by bar_active_from
    # We advance this pointer forward as time progresses (O(1) amortized)
    zone_ptr: int = 0
    active_zones_cache: list[SRZone] = []

    import bisect
    ROLLING_WEEKS = 52
    
    # 4. Main backtest loop: iterate over execution_tf bars
    bars_rows = []
    if signal_version == "0.2":
        bars_rows = bars_exec.select(["timestamp", "close", "volume", "volume_sma"]).to_numpy()
    else:
        bars_rows = bars_exec.select(["timestamp", "close"]).to_numpy()

    for row_vals in bars_rows:
        ts_ms: int = int(row_vals[0])
        close: float = float(row_vals[1])
        
        current_volume: float | None = None
        volume_sma: float | None = None
        if signal_version == "0.2":
            current_volume = float(row_vals[2])
            volume_sma = float(row_vals[3]) if not pl.Series([row_vals[3]]).is_null()[0] else None

        # -- Update rolling bounds weekly (O(log n) binary search instead of full DF filter) --
        week_start = (ts_ms // _MS_PER_WEEK) * _MS_PER_WEEK
        if week_start != current_week_start_ms and weekly_ts:
            current_week_start_ms = week_start
            # Find the index of the most recent weekly bar before ts_ms
            idx = bisect.bisect_right(weekly_ts, ts_ms) - 1
            if idx >= ROLLING_WEEKS:
                window_lows = weekly_low[idx - ROLLING_WEEKS: idx]
                window_highs = weekly_high[idx - ROLLING_WEEKS: idx]
                from src.config.settings import LOWER_BOUND_MULTIPLIER, UPPER_BOUND_MULTIPLIER
                l_price = min(window_lows) * LOWER_BOUND_MULTIPLIER
                u_price = max(window_highs) * UPPER_BOUND_MULTIPLIER
            else:
                l_price = 0.0
                u_price = float("inf")

        # -- Advance active zones pointer (amortized O(1) instead of O(n) filter each bar) --
        while zone_ptr < len(all_zones_sorted) and all_zones_sorted[zone_ptr].bar_active_from <= ts_ms:
            active_zones_cache.append(all_zones_sorted[zone_ptr])
            zone_ptr += 1
        active_zones = active_zones_cache

        # -- Gather RSI values: O(log n) binary search lookup --
        rsi_by_tf = _align_rsi_fast(rsi_lookup, ts_ms)

        # -- Evaluate Signal --
        from src.config.settings import SR_PROXIMITY_PCT
        actual_proximity = proximity_pct if proximity_pct is not None else SR_PROXIMITY_PCT
        
        signal: SignalResult = evaluate_signal(
            current_price=close,
            current_timestamp_ms=ts_ms,
            active_zones=active_zones,  # type: ignore[arg-type]
            rsi_by_tf=rsi_by_tf,
            l_price=l_price,
            in_position=in_position,
            proximity_pct=actual_proximity,
            version=signal_version,
            current_volume=current_volume,
            volume_sma=volume_sma,
        )

        # -- Process Buy signal --
        if signal.action == "buy" and signal.zone is not None:
            # Find nearest resistance zone for trade viability check
            resistance_zones = [
                z for z in active_zones
                if z.kind == "resistance" and z.price > close
            ]
            if resistance_zones:
                nearest_resistance = min(resistance_zones, key=lambda z: z.price)
                if not is_trade_viable(close, nearest_resistance.price):
                    log.debug(f"  [{ts_ms}] Trade rejected by spread constraint")
                    equity_curve.append(capital)
                    continue

            pos_size = compute_position_size_usd(symbol, close, capital, l_price, u_price)
            if pos_size <= 0:
                log.debug(f"  [{ts_ms}] Zero position size — skipping entry")
                equity_curve.append(capital)
                continue

            eff_entry = apply_entry_friction(close)
            current_trade = Trade(
                symbol=symbol,
                entry_timestamp_ms=ts_ms,
                entry_price=close,
                effective_entry_price=eff_entry,
                position_size_usd=pos_size,
                entry_zone_weight=signal.zone.combined_weight,
            )
            in_position = True
            dt_str = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime('%Y-%m-%d')
            log.info(f"  [{symbol} {dt_str}] BUY  @ {close:.2f} | pos={pos_size:.2f} USD | {signal.notes}")

        # -- Process Sell signals --
        elif signal.action in ("sell_resistance", "sell_stoploss") and current_trade is not None:
            pnl = compute_pnl(
                entry_price=current_trade.entry_price,
                exit_price=close,
                position_size_usd=current_trade.position_size_usd,
            )
            current_trade.exit_timestamp_ms = ts_ms
            current_trade.exit_price = close
            current_trade.effective_exit_price = apply_exit_friction(close)
            current_trade.pnl = pnl
            current_trade.exit_reason = signal.action
            capital += pnl
            completed_trades.append(current_trade)
            in_position = False
            dt_str = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime('%Y-%m-%d')
            log.info(
                f"  [{symbol} {dt_str}] SELL @ {close:.2f} | reason={signal.action} | "
                f"pnl={pnl:+.2f} USD | capital={capital:.2f}"
            )
            current_trade = None

        equity_curve.append(capital)

    # Close any open position at last bar (mark-to-market, no friction)
    if current_trade is not None:
        last_price = bars_exec["close"][-1]
        pnl = compute_pnl(
            entry_price=current_trade.entry_price,
            exit_price=last_price,
            position_size_usd=current_trade.position_size_usd,
        )
        current_trade.exit_price = last_price
        current_trade.effective_exit_price = last_price
        current_trade.exit_timestamp_ms = bars_exec["timestamp"][-1]
        current_trade.exit_reason = "end_of_data"
        current_trade.pnl = pnl
        capital += pnl
        completed_trades.append(current_trade)
        log.info(f"  End-of-data close @ {last_price:.2f} | pnl={pnl:+.2f}")

    # ------------------------------------------------------------------
    # 5. Compute summary metrics
    # ------------------------------------------------------------------
    total_trades = len(completed_trades)
    winning = [t for t in completed_trades if (t.pnl or 0) > 0]
    losing = [t for t in completed_trades if (t.pnl or 0) <= 0]
    total_return_pct = ((capital - initial_capital) / initial_capital) * 100
    
    # Calculate isolated return (relative only to this asset's allocated slice of the capital)
    from src.config.settings import ASSET_ALLOCATION
    asset_frac = ASSET_ALLOCATION.get(symbol, 1.0)
    allocated_initial_capital = initial_capital * asset_frac
    isolated_return_pct = ((capital - initial_capital) / allocated_initial_capital) * 100.0 if allocated_initial_capital > 0 else 0.0

    win_rate = (len(winning) / total_trades * 100) if total_trades > 0 else 0.0
    avg_pnl = sum(t.pnl or 0 for t in completed_trades) / total_trades if total_trades > 0 else 0.0
    max_dd = _compute_max_drawdown(equity_curve)

    result = BacktestResult(
        symbol=symbol,
        initial_capital=initial_capital,
        final_capital=capital,
        total_return_pct=total_return_pct,
        isolated_return_pct=isolated_return_pct,
        total_trades=total_trades,
        winning_trades=len(winning),
        losing_trades=len(losing),
        win_rate_pct=win_rate,
        avg_pnl_per_trade=avg_pnl,
        max_drawdown_pct=max_dd,
        trades=completed_trades,
        sr_zones=all_zones,
    )

    log.info(
        f"\n=== Backtest Complete: {symbol} ===\n"
        f"  Total Return : {total_return_pct:+.2f}%\n"
        f"  Trades       : {total_trades} (W:{len(winning)} L:{len(losing)})\n"
        f"  Win Rate     : {win_rate:.1f}%\n"
        f"  Avg PnL/trade: {avg_pnl:+.2f} USD\n"
        f"  Max Drawdown : {max_dd:.2f}%\n"
        f"  Final Capital: {capital:.2f} USD"
    )
    return result
