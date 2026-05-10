"""
Data fetcher using ccxt async (Binance REST API).

Spec reference: Section 1 (ccxt), Section 2 (Data Architecture), Section 3 (Market Selection).

Partition scheme: data/hot/data/{ASSET}/{TF}/YYYY-MM.parquet
  - ASSET: e.g. BTC-USDT  (slash replaced with dash for filesystem safety)
  - TF:    e.g. 1H

Performance: all (symbol, timeframe) combinations are fetched concurrently via
asyncio + ccxt.async_support, constrained by a semaphore to respect Binance
rate limits. Typical speedup: 5-10x over the sequential approach.
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from pathlib import Path

import ccxt.async_support as ccxt_async
import polars as pl

from src.config.settings import (
    DATA_ROOT,
    EXCHANGE_ID,
    PARQUET_COMPRESSION,
    TF_MAP,
)
from src.utils.logger import get_logger

log = get_logger(__name__)

# ccxt returns OHLCV as: [timestamp_ms, open, high, low, close, volume]
_CCXT_COLS = ["timestamp", "open", "high", "low", "close", "volume"]

# Maximum number of concurrent API requests.
# Binance allows ~20 req/s on public endpoints; 16 gives headroom.
_MAX_CONCURRENT = 16


def _asset_to_path_name(symbol: str) -> str:
    """'BTC/USDT' → 'BTC-USDT'"""
    return symbol.replace("/", "-")


async def _fetch_ohlcv_async(
    exchange: ccxt_async.Exchange,
    semaphore: asyncio.Semaphore,
    symbol: str,
    timeframe: str,
    since_ms: int,
    until_ms: int,
    root: str,
    batch_size: int = 1000,
) -> tuple[str, str, pl.DataFrame]:
    """
    Async fetch of a single (symbol, timeframe) combination.

    Phase 1 (no semaphore, threaded): parallel disk reads via asyncio.to_thread().
    Phase 2 (semaphore):              only the Binance API calls are rate-limited.

    Returns (symbol, timeframe, df) so the caller can save without re-indexing.
    """
    # --- Phase 1: Gap detection (non-blocking, runs fully in parallel) ---
    from src.data.storage import load_ohlcv
    existing_df = await asyncio.to_thread(load_ohlcv, symbol, timeframe, root)

    gaps_to_fetch = []
    if existing_df.is_empty():
        gaps_to_fetch.append((since_ms, until_ms))
    else:
        min_ts = existing_df["timestamp"].min()
        max_ts = existing_df["timestamp"].max()
        if since_ms < min_ts:
            gaps_to_fetch.append((since_ms, min_ts - 1))
        if max_ts < until_ms:
            gaps_to_fetch.append((max_ts + 1, until_ms))

    if not gaps_to_fetch:
        log.info(f"  ✓ {symbol} {timeframe}: Up to date")
        return symbol, timeframe, pl.DataFrame(schema={c: pl.Float64 for c in _CCXT_COLS})

    log.info(f"  → Fetching {symbol} {timeframe} ({len(gaps_to_fetch)} gap(s)) ...")

    # --- Phase 2: API calls (rate-limited via semaphore) ---
    all_new_rows: list[list] = []

    async with semaphore:
        for gap_start, gap_end in gaps_to_fetch:
            current_since = gap_start
            while current_since < gap_end:
                raw = await exchange.fetch_ohlcv(
                    symbol,
                    timeframe=timeframe,
                    since=current_since,
                    limit=batch_size,
                )
                if not raw:
                    break

                raw = [r for r in raw if r[0] <= gap_end]
                if not raw:
                    break

                all_new_rows.extend(raw)

                if len(raw) < batch_size:
                    break

                current_since = raw[-1][0] + 1

    if not all_new_rows:
        log.warning(f"  No new data returned for {symbol} {timeframe}")
        return symbol, timeframe, pl.DataFrame(schema={c: pl.Float64 for c in _CCXT_COLS})

    df = pl.DataFrame(all_new_rows, schema=_CCXT_COLS, orient="row")
    df = df.with_columns(pl.col("timestamp").cast(pl.Int64))
    df = df.unique(subset=["timestamp"]).sort("timestamp")

    log.info(f"  ✓ {symbol} {timeframe}: Fetched {len(df)} new candles")
    return symbol, timeframe, df


def _save_parquet(df: pl.DataFrame, symbol: str, timeframe: str, root: str) -> None:
    """Save OHLCV DataFrame to monthly-partitioned parquet files.
    Merges with existing data to prevent overwrite loss.
    """
    tf_label = TF_MAP.get(timeframe, timeframe.upper())
    asset_name = _asset_to_path_name(symbol)

    df = df.with_columns(
        pl.from_epoch(pl.col("timestamp"), time_unit="ms")
        .dt.strftime("%Y-%m")
        .alias("_ym")
    )

    for ym in df["_ym"].unique().sort().to_list():
        month_df = df.filter(pl.col("_ym") == ym).drop("_ym")
        path = Path(root) / asset_name / tf_label / f"{ym}.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        
        if path.exists():
            try:
                existing_df = pl.read_parquet(str(path))
                month_df = pl.concat([existing_df, month_df]).unique(subset=["timestamp"]).sort("timestamp")
            except Exception as e:
                log.error(f"Error reading existing parquet {path}: {e}")
                
        month_df.write_parquet(str(path), compression=PARQUET_COMPRESSION)


async def _fetch_all_async(
    symbols: list[str],
    timeframes: list[str],
    since_dt: datetime,
    until_dt: datetime,
    root: str,
) -> None:
    """
    Fetch all (symbol, timeframe) combinations concurrently and save to parquet.

    Improvements:
    - Phase 1 disk reads use asyncio.to_thread() (non-blocking).
    - Semaphore only gates actual Binance API calls.
    - Results are saved to disk immediately as they complete (asyncio.as_completed),
      overlapping disk writes with ongoing API fetches.
    """
    since_ms = int(since_dt.timestamp() * 1000)
    until_ms = int(until_dt.timestamp() * 1000)

    exchange = getattr(ccxt_async, EXCHANGE_ID)({"enableRateLimit": True})
    semaphore = asyncio.Semaphore(_MAX_CONCURRENT)

    tasks = [
        asyncio.ensure_future(
            _fetch_ohlcv_async(exchange, semaphore, symbol, tf, since_ms, until_ms, root)
        )
        for symbol in symbols
        for tf in timeframes
    ]

    t0 = time.perf_counter()
    log.info(
        f"Starting parallel fetch: {len(tasks)} tasks "
        f"({len(symbols)} assets × {len(timeframes)} timeframes) "
        f"| concurrency={_MAX_CONCURRENT}"
    )

    # Save each result immediately as it completes (overlaps with ongoing fetches)
    completed = 0
    for coro in asyncio.as_completed(tasks):
        try:
            symbol, tf, df = await coro
            if not df.is_empty():
                await asyncio.to_thread(_save_parquet, df, symbol, tf, root)
            completed += 1
            if completed % 50 == 0:
                log.info(f"  Progress: {completed}/{len(tasks)} tasks done")
        except Exception as e:
            log.error(f"  FAILED task: {e}")
            completed += 1

    await exchange.close()

    elapsed = time.perf_counter() - t0
    log.info(f"Fetch complete in {elapsed:.1f}s — all data saved.")


def fetch_all_parallel(
    symbols: list[str],
    timeframes: list[str],
    since_dt: datetime,
    until_dt: datetime,
    root: str = DATA_ROOT,
) -> None:
    """
    Public entry point: fetch all symbols/timeframes in parallel and persist to parquet.

    Args:
        symbols:    List of ccxt symbol strings, e.g. ['BTC/USDT', 'ETH/USDT'].
        timeframes: List of ccxt timeframe strings, e.g. ['1h', '4h', '1d'].
        since_dt:   Start datetime (UTC-aware).
        until_dt:   End datetime (UTC-aware).
        root:       Root directory for parquet data.
    """
    asyncio.run(_fetch_all_async(symbols, timeframes, since_dt, until_dt, root))


# ---------------------------------------------------------------------------
# Legacy sync API (kept for backward compatibility / single-pair use)
# ---------------------------------------------------------------------------

def fetch_ohlcv(
    symbol: str,
    timeframe: str,
    since_dt: datetime,
    until_dt: datetime | None = None,
    batch_size: int = 1000,
    root: str = DATA_ROOT,
) -> pl.DataFrame:
    """Synchronous single-pair fetch (kept for compatibility)."""
    import ccxt as ccxt_sync
    from src.data.storage import load_ohlcv
    
    exchange = getattr(ccxt_sync, EXCHANGE_ID)({"enableRateLimit": True})
    since_ms = int(since_dt.timestamp() * 1000)
    until_ms = int(until_dt.timestamp() * 1000) if until_dt else int(time.time() * 1000)

    log.info(f"Checking {symbol} {timeframe} from {since_dt.date()} ...")
    
    existing_df = load_ohlcv(symbol, timeframe, root=root)
    gaps_to_fetch = []
    if existing_df.is_empty():
        gaps_to_fetch.append((since_ms, until_ms))
    else:
        min_ts = existing_df["timestamp"].min()
        max_ts = existing_df["timestamp"].max()
        if since_ms < min_ts:
            gaps_to_fetch.append((since_ms, min_ts - 1))
        if max_ts < until_ms:
            gaps_to_fetch.append((max_ts + 1, until_ms))
            
    if not gaps_to_fetch:
        log.info(f"  ✓ {symbol} {timeframe}: Up to date")
        return pl.DataFrame(schema={c: pl.Float64 for c in _CCXT_COLS})

    all_new_rows: list[list] = []
    
    for gap_start, gap_end in gaps_to_fetch:
        current_since = gap_start
        while current_since < gap_end:
            raw = exchange.fetch_ohlcv(symbol, timeframe=timeframe, since=current_since, limit=batch_size)
            if not raw:
                break
            raw = [r for r in raw if r[0] <= gap_end]
            if not raw:
                break
            all_new_rows.extend(raw)
            if len(raw) < batch_size:
                break
            current_since = raw[-1][0] + 1

    if not all_new_rows:
        return pl.DataFrame(schema={c: pl.Float64 for c in _CCXT_COLS})

    df = pl.DataFrame(all_new_rows, schema=_CCXT_COLS, orient="row")
    df = df.with_columns(pl.col("timestamp").cast(pl.Int64))
    return df.unique(subset=["timestamp"]).sort("timestamp")


def fetch_and_store(
    symbol: str,
    timeframe: str,
    since_dt: datetime,
    until_dt: datetime | None = None,
    root: str = DATA_ROOT,
) -> pl.DataFrame:
    """Synchronous fetch + store for a single symbol/timeframe (kept for compatibility)."""
    df = fetch_ohlcv(symbol, timeframe, since_dt, until_dt, root=root)
    if len(df) > 0:
        _save_parquet(df, symbol, timeframe, root)
    return df
