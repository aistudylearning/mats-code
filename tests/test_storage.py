"""Tests for data storage — parquet I/O, partitioning, deduplication, edge cases."""
import polars as pl
import pytest
from pathlib import Path

from src.data.storage import load_ohlcv, save_ohlcv, list_available, _asset_to_path_name


@pytest.fixture
def temp_data_root(tmp_path):
    """Provide a temporary directory for data storage testing."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    yield str(data_dir)


def _make_ohlcv(start_ts_ms: int, num_rows: int, close: float = 105.0) -> pl.DataFrame:
    """Create a dummy OHLCV DataFrame."""
    timestamps = [start_ts_ms + i * 3600000 for i in range(num_rows)]
    return pl.DataFrame({
        "timestamp": timestamps,
        "open":   [100.0] * num_rows,
        "high":   [110.0] * num_rows,
        "low":    [90.0] * num_rows,
        "close":  [close] * num_rows,
        "volume": [1000.0] * num_rows,
    })


# ── Path conversion ─────────────────────────────────────────────────


def test_asset_to_path_name():
    """Symbol slash is replaced with hyphen for filesystem safety."""
    assert _asset_to_path_name("BTC/USDT") == "BTC-USDT"
    assert _asset_to_path_name("ETH/USDT") == "ETH-USDT"
    assert _asset_to_path_name("SHIB/USDT") == "SHIB-USDT"


# ── Round-trip persistence ───────────────────────────────────────────


def test_save_and_load_round_trip(temp_data_root):
    """Data saved then loaded should produce identical rows."""
    df = _make_ohlcv(1704067200000, 24)  # 2024-01-01 00:00 UTC
    save_ohlcv(df, "BTC/USDT", "1h", root=temp_data_root)
    loaded = load_ohlcv("BTC/USDT", "1h", root=temp_data_root)

    assert not loaded.is_empty()
    assert len(loaded) == 24
    assert loaded["timestamp"].to_list() == df["timestamp"].to_list()
    assert loaded["close"].to_list() == df["close"].to_list()


def test_save_preserves_all_columns(temp_data_root):
    """All 6 OHLCV columns must survive the save/load cycle."""
    df = _make_ohlcv(1704067200000, 5)
    save_ohlcv(df, "BTC/USDT", "1h", root=temp_data_root)
    loaded = load_ohlcv("BTC/USDT", "1h", root=temp_data_root)

    expected_cols = {"timestamp", "open", "high", "low", "close", "volume"}
    assert set(loaded.columns) == expected_cols


# ── Monthly partitioning ─────────────────────────────────────────────


def test_partitioning_across_month_boundary(temp_data_root):
    """Data spanning Jan/Feb 2024 should produce two parquet files."""
    # 2024-01-31 23:00:00 UTC → 3 rows crossing into Feb 1
    df = _make_ohlcv(1706742000000, 3)
    save_ohlcv(df, "BTC/USDT", "1h", root=temp_data_root)

    target_dir = Path(temp_data_root) / "BTC-USDT" / "1H"
    files = sorted(f.name for f in target_dir.glob("*.parquet"))
    assert files == ["2024-01.parquet", "2024-02.parquet"]


def test_partitioning_single_month(temp_data_root):
    """Data within one month should produce exactly one file."""
    df = _make_ohlcv(1704067200000, 24)  # 24 hours, all in Jan 2024
    save_ohlcv(df, "BTC/USDT", "4h", root=temp_data_root)

    target_dir = Path(temp_data_root) / "BTC-USDT" / "4H"
    files = list(target_dir.glob("*.parquet"))
    assert len(files) == 1
    assert files[0].name == "2024-01.parquet"


# ── Deduplication ────────────────────────────────────────────────────


def test_load_deduplicates_timestamps(temp_data_root):
    """Writing overlapping data then loading should produce unique timestamps."""
    df1 = _make_ohlcv(1704067200000, 10)
    df2 = _make_ohlcv(1704067200000 + 5 * 3600000, 10)  # 5 rows overlap

    save_ohlcv(df1, "BTC/USDT", "1h", root=temp_data_root)
    save_ohlcv(df2, "BTC/USDT", "1h", root=temp_data_root)

    loaded = load_ohlcv("BTC/USDT", "1h", root=temp_data_root)
    timestamps = loaded["timestamp"].to_list()
    assert len(timestamps) == len(set(timestamps)), "Duplicate timestamps found"


def test_load_sorts_ascending(temp_data_root):
    """Loaded data must be sorted ascending by timestamp regardless of write order."""
    df = _make_ohlcv(1704067200000, 20)
    save_ohlcv(df, "BTC/USDT", "1h", root=temp_data_root)
    loaded = load_ohlcv("BTC/USDT", "1h", root=temp_data_root)
    timestamps = loaded["timestamp"].to_list()
    assert timestamps == sorted(timestamps)


# ── Missing data handling ────────────────────────────────────────────


def test_load_returns_empty_for_unknown_symbol(temp_data_root):
    """Missing asset directory → empty DataFrame, no crash."""
    df = load_ohlcv("FAKETOKEN/USDT", "1h", root=temp_data_root)
    assert df.is_empty()


def test_load_returns_empty_for_unknown_timeframe(temp_data_root):
    """Asset exists but requested timeframe doesn't → empty DataFrame."""
    save_ohlcv(_make_ohlcv(1704067200000, 1), "BTC/USDT", "1h", root=temp_data_root)
    df = load_ohlcv("BTC/USDT", "15m", root=temp_data_root)
    assert df.is_empty()


def test_load_returns_empty_for_nonexistent_root():
    """Non-existent data root → empty DataFrame."""
    df = load_ohlcv("BTC/USDT", "1h", root="/tmp/does_not_exist_xyz_123")
    assert df.is_empty()


# ── list_available ───────────────────────────────────────────────────


def test_list_available_multiple_assets(temp_data_root):
    """Correctly discovers assets and timeframes."""
    df = _make_ohlcv(1704067200000, 1)
    save_ohlcv(df, "BTC/USDT", "1h", root=temp_data_root)
    save_ohlcv(df, "BTC/USDT", "4h", root=temp_data_root)
    save_ohlcv(df, "ETH/USDT", "1d", root=temp_data_root)

    available = list_available(root=temp_data_root)
    assert "BTC-USDT" in available
    assert "ETH-USDT" in available
    assert sorted(available["BTC-USDT"]) == ["1H", "4H"]
    assert available["ETH-USDT"] == ["1D"]


def test_list_available_empty_root(temp_data_root):
    """Empty data root → empty dict."""
    assert list_available(root=temp_data_root) == {}


def test_list_available_nonexistent_root():
    """Non-existent root → empty dict."""
    assert list_available(root="/tmp/does_not_exist_xyz_123") == {}


# ── TF_MAP coverage ─────────────────────────────────────────────────


def test_all_timeframes_map_to_valid_paths(temp_data_root):
    """Every configured timeframe in settings.TIMEFRAMES should round-trip through storage."""
    from src.config.settings import TIMEFRAMES
    df = _make_ohlcv(1704067200000, 1)
    for tf in TIMEFRAMES:
        save_ohlcv(df, "TEST/USDT", tf, root=temp_data_root)
        loaded = load_ohlcv("TEST/USDT", tf, root=temp_data_root)
        assert not loaded.is_empty(), f"Failed round-trip for timeframe: {tf}"
