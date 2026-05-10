"""
MATS Strategy A — Signal 0.1
All parameters in this file are LOCKED per the specification.
Do not change without a versioned spec update.
"""

# ---------------------------------------------------------------------------
# MVP Assets & Exchange
# ---------------------------------------------------------------------------
MVP_ASSETS = [
    "BTC/USDT", "ETH/USDT", "XRP/USDT", "BNB/USDT", "SOL/USDT",
    "TRX/USDT", "DOGE/USDT", "ADA/USDT", "ZEC/USDT", "BCH/USDT",
    "LINK/USDT", "XMR/USDT", "TON/USDT", "XLM/USDT", "SUI/USDT",
    "LTC/USDT", "AVAX/USDT", "HBAR/USDT", "SHIB/USDT", "FTM/USDT",
    "TAO/USDT", "UNI/USDT", "DOT/USDT", "NEAR/USDT", "ONDO/USDT",
    "ICP/USDT", "PEPE/USDT", "ETC/USDT", "AAVE/USDT", "ENA/USDT",
    "ALGO/USDT", "POL/USDT", "QNT/USDT", "RENDER/USDT", "ATOM/USDT",
    "FIL/USDT", "WLD/USDT", "APT/USDT", "ARB/USDT", "JUP/USDT",
    "SAND/USDT", "VET/USDT", "BONK/USDT", "DASH/USDT", "STX/USDT",
    "CHZ/USDT", "SEI/USDT", "XTZ/USDT", "CFX/USDT", "INJ/USDT",
]
EXCHANGE_ID = "binance"

# ---------------------------------------------------------------------------
# Timeframes (ordered weakest → strongest for S/R weighting)
# ---------------------------------------------------------------------------
TIMEFRAMES = ["1h", "4h", "1d", "1w", "1M"]

# Map ccxt timeframe strings to display names used in parquet paths
TF_MAP = {
    "1h": "1H",
    "4h": "4H",
    "1d": "1D",
    "1w": "1W",
    "1M": "1M",
}

# S/R weight per timeframe (higher TF = stronger level)
SR_WEIGHTS = {
    "1h": 1,
    "4h": 2,
    "1d": 3,
    "1w": 4,
    "1M": 5,
}

# Minimum combined S/R weight to be considered a High-Conviction Zone
HIGH_CONVICTION_THRESHOLD = 5

# ---------------------------------------------------------------------------
# Data Storage
# ---------------------------------------------------------------------------
# Partition scheme: data/hot/data/{ASSET}/{TF}/YYYY-MM.parquet
DATA_ROOT = "data/hot/data"
PARQUET_COMPRESSION = "snappy"

REQUIRED_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]

# ---------------------------------------------------------------------------
# RSI — Section 4 (Locked)
# ---------------------------------------------------------------------------
RSI_LENGTH = 14
RSI_OVERSOLD = 30    # Buy signal threshold
RSI_OVERBOUGHT = 70  # Sell signal threshold

# ---------------------------------------------------------------------------
# S/R Algorithm A — Section 5 (Locked)
# ---------------------------------------------------------------------------
SR_PIVOT_WINDOW = 5        # N: look-back and look-forward candles for local extrema
SR_MAX_PIVOTS = 50         # M: max recent pivots kept per timeframe per asset
SR_CLUSTER_THRESHOLD = 0.005  # 0.5% — merge two pivots if within this distance

# S/R proximity zone for signal trigger (Section 6 CTO correction v2)
SR_PROXIMITY_PCT = 0.02    # ±2%

# ---------------------------------------------------------------------------
# Capital Allocation — Section 7 (Locked)
# ---------------------------------------------------------------------------
# Allocate equally across all MVP assets (e.g. 2% for 50 assets)
ASSET_ALLOCATION = {symbol: 1.0 / len(MVP_ASSETS) for symbol in MVP_ASSETS}

# Rolling hard bounds: trailing 52-week window updated weekly
ROLLING_WINDOW_WEEKS = 52
LOWER_BOUND_MULTIPLIER = 0.8   # LPrice = 0.8 × 52w_low
UPPER_BOUND_MULTIPLIER = 1.2   # UPrice = 1.2 × 52w_high

# Position fraction quantization step
POSITION_STEP = 0.10  # Discrete 10% steps

# ---------------------------------------------------------------------------
# Fee & Slippage — Section 8 (Locked)
# ---------------------------------------------------------------------------
TAKER_FEE = 0.0010       # 0.10% per execution
SLIPPAGE_FLAT = 0.0005   # 0.05% flat slippage per execution
TOTAL_FRICTION_PER_EXEC = TAKER_FEE + SLIPPAGE_FLAT   # 0.15%
ROUND_TRIP_FRICTION = TOTAL_FRICTION_PER_EXEC * 2     # 0.30%

# Minimum spread required to take a trade (must exceed round-trip cost)
MIN_SPREAD_TO_TRADE = ROUND_TRIP_FRICTION  # 0.30%

# ---------------------------------------------------------------------------
# Backtest defaults
# ---------------------------------------------------------------------------
DEFAULT_INITIAL_CAPITAL = 10_000.0   # USD
DEFAULT_BACKTEST_ASSET = "BTC/USDT"

# ---------------------------------------------------------------------------
# Signal 0.2 Upgrades
# ---------------------------------------------------------------------------
VOLUME_SMA_LENGTH = 20
VOLUME_SPIKE_MULTIPLIER = 1.5

