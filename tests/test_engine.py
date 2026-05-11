"""Tests for backtesting engine — end-to-end verification and edge cases."""
import polars as pl
import pytest

from src.backtest.engine import (
    BacktestResult,
    Trade,
    _build_rsi_lookup,
    _align_rsi_fast,
    _compute_max_drawdown,
    run_backtest,
)
from src.data.storage import save_ohlcv


# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def temp_engine_data(tmp_path):
    """Temporary directory populated with minimal but valid backtest data."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    num_rows = 50
    timestamps = [1704067200000 + i * 3600000 for i in range(num_rows)]
    df_1h = pl.DataFrame({
        "timestamp": timestamps,
        "open":   [100.0] * num_rows,
        "high":   [110.0] * num_rows,
        "low":    [90.0] * num_rows,
        "close":  [105.0] * num_rows,
        "volume": [1000.0] * num_rows,
    })

    df_1w = pl.DataFrame({
        "timestamp": [1704067200000],
        "open":  [100.0],
        "high":  [120.0],
        "low":   [80.0],
        "close": [105.0],
        "volume": [10000.0],
    })

    save_ohlcv(df_1h, "BTC/USDT", "1h", root=str(data_dir))
    save_ohlcv(df_1h, "BTC/USDT", "1d", root=str(data_dir))
    save_ohlcv(df_1w, "BTC/USDT", "1w", root=str(data_dir))

    yield str(data_dir)


# ── Max Drawdown unit tests ─────────────────────────────────────────


def test_max_drawdown_monotonic_up():
    """An equity curve that only goes up has 0% drawdown."""
    curve = [100.0, 110.0, 120.0, 130.0, 140.0]
    assert _compute_max_drawdown(curve) == 0.0


def test_max_drawdown_single_drop():
    """100 → 120 → 90 = 25% drop from the 120 peak."""
    curve = [100.0, 120.0, 90.0]
    dd = _compute_max_drawdown(curve)
    assert abs(dd - 25.0) < 0.01


def test_max_drawdown_recovery():
    """Drawdown tracks the worst peak-to-trough, even if recovery follows."""
    curve = [100.0, 120.0, 60.0, 150.0]
    dd = _compute_max_drawdown(curve)
    # Worst trough: 120 → 60 = 50% drawdown
    assert abs(dd - 50.0) < 0.01


def test_max_drawdown_empty_curve():
    assert _compute_max_drawdown([]) == 0.0


def test_max_drawdown_flat_curve():
    curve = [100.0, 100.0, 100.0]
    assert _compute_max_drawdown(curve) == 0.0


# ── RSI Lookup unit tests ───────────────────────────────────────────


def test_build_rsi_lookup_basic():
    """Should build sorted timestamp/rsi arrays from a DataFrame."""
    df = pl.DataFrame({
        "timestamp": [100, 200, 300],
        "close": [50.0, 55.0, 53.0],
        "rsi": [30.0, 45.0, 60.0],
    })
    lookup = _build_rsi_lookup({"1h": df})
    assert "1h" in lookup
    ts_list, rsi_list = lookup["1h"]
    assert ts_list == [100, 200, 300]
    assert rsi_list == [30.0, 45.0, 60.0]


def test_build_rsi_lookup_empty_df():
    """Empty DataFrame should produce empty lists."""
    df = pl.DataFrame()
    lookup = _build_rsi_lookup({"1h": df})
    assert lookup["1h"] == ([], [])


def test_align_rsi_fast_exact_match():
    """When timestamp matches exactly, return that RSI."""
    lookup = {"1h": ([100, 200, 300], [30.0, 45.0, 60.0])}
    rsi = _align_rsi_fast(lookup, 200)
    assert rsi["1h"] == 45.0


def test_align_rsi_fast_between_bars():
    """When timestamp is between bars, return the most recent bar's RSI."""
    lookup = {"1h": ([100, 200, 300], [30.0, 45.0, 60.0])}
    rsi = _align_rsi_fast(lookup, 250)
    assert rsi["1h"] == 45.0  # bisect_right(250) - 1 = index 1


def test_align_rsi_fast_before_all_data():
    """When timestamp is before all data, return None."""
    lookup = {"1h": ([100, 200, 300], [30.0, 45.0, 60.0])}
    rsi = _align_rsi_fast(lookup, 50)
    assert rsi["1h"] is None


def test_align_rsi_fast_multiple_timeframes():
    """Alignment should work independently per timeframe."""
    lookup = {
        "1h": ([100, 200], [30.0, 45.0]),
        "4h": ([100, 400], [55.0, 70.0]),
    }
    rsi = _align_rsi_fast(lookup, 250)
    assert rsi["1h"] == 45.0
    assert rsi["4h"] == 55.0  # 250 > 100 but < 400 → index 0


# ── End-to-end engine tests ─────────────────────────────────────────


def test_run_backtest_returns_valid_result(temp_engine_data):
    """Engine executes without crashing and returns a well-formed BacktestResult."""
    result = run_backtest(
        symbol="BTC/USDT",
        initial_capital=10000.0,
        data_root=temp_engine_data,
        signal_version="0.1",
        execution_tf="1h",
    )

    assert result.symbol == "BTC/USDT"
    assert result.initial_capital == 10000.0
    assert isinstance(result.final_capital, float)
    assert isinstance(result.total_return_pct, float)
    assert isinstance(result.trades, list)
    assert result.total_trades >= 0


def test_run_backtest_missing_execution_tf(temp_engine_data):
    """Engine gracefully returns empty result when execution TF data is missing."""
    result = run_backtest(
        symbol="BTC/USDT",
        initial_capital=10000.0,
        data_root=temp_engine_data,
        signal_version="0.1",
        execution_tf="5m",
    )

    assert result.total_trades == 0
    assert result.final_capital == 10000.0
    assert result.total_return_pct == 0.0


def test_run_backtest_missing_asset(temp_engine_data):
    """Engine handles a completely missing asset without crashing."""
    result = run_backtest(
        symbol="FAKETOKEN/USDT",
        initial_capital=10000.0,
        data_root=temp_engine_data,
        signal_version="0.1",
        execution_tf="1h",
    )

    assert result.total_trades == 0
    assert result.final_capital == 10000.0


def test_run_backtest_preserves_capital_no_trades(temp_engine_data):
    """If no signals fire (flat data), capital must remain exactly unchanged."""
    result = run_backtest(
        symbol="BTC/USDT",
        initial_capital=10000.0,
        data_root=temp_engine_data,
        signal_version="0.1",
        execution_tf="1h",
    )

    # With perfectly flat data (all closes = 105), no S/R zones should form,
    # so no entries should be triggered. Capital should be preserved.
    if result.total_trades == 0:
        assert result.final_capital == 10000.0


# ── Trade dataclass tests ────────────────────────────────────────────


def test_trade_dataclass_defaults():
    """Trade defaults should be sensible for an open position."""
    t = Trade(
        symbol="BTC/USDT",
        entry_timestamp_ms=1000,
        entry_price=50000.0,
        effective_entry_price=50075.0,
        position_size_usd=5000.0,
    )
    assert t.exit_timestamp_ms is None
    assert t.exit_price is None
    assert t.pnl is None
    assert t.exit_reason == ""


def test_backtest_result_dataclass():
    """BacktestResult should compute correct win rate from provided values."""
    r = BacktestResult(
        symbol="BTC/USDT",
        initial_capital=10000.0,
        final_capital=11000.0,
        total_return_pct=10.0,
        isolated_return_pct=20.0,
        total_trades=4,
        winning_trades=3,
        losing_trades=1,
        win_rate_pct=75.0,
        avg_pnl_per_trade=250.0,
        max_drawdown_pct=5.0,
    )
    assert r.win_rate_pct == 75.0
    assert r.trades == []
    assert r.sr_zones == []
