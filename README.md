# MATS Strategy A — Signal 0.1

**Inventory-Based | Crypto-First | All Decisions Locked**

Backtesting engine for MATS Strategy A, Signal 0.1.  
Specification: `MATS-Design-3.3.1-StrategyA-Crypto-Signal0.1-Opus4.6Thinking.md`

---

## Quick Start

> **Setting up a new environment?** Pick the guide for your platform:  
> - [Ubuntu 24.04.4 LTS — Laptop 3 (bare-metal worker)](INSTALLME.24.04.4LTS.md)  
> - [Ubuntu 26.04 LTS — WSL on Windows (development)](INSTALLME.26.04LTS.md)  
> - [Google Colab (ephemeral compute)](INSTALLME.Colab.md)  
>  
> **Already set up?** See the [Operational Guide (RUNME.md)](RUNME.md) for  
> which tasks to run on which environment.

### 1. Install dependencies (Python 3.11+)

```bash
pip install -e ".[dev]"
```

Or directly:

```bash
pip install polars pyarrow duckdb pandas-ta ccxt joblib pytest
```

### 2. Fetch OHLCV data (Binance, 2023–2025)

```bash
python3 main.py fetch
```

Downloads BTC/USDT and ETH/USDT for all 5 timeframes (1H, 4H, 1D, 1W, 1M).  
Data is stored in `data/hot/data/{ASSET}/{TF}/YYYY-MM.parquet`.

### 3. Run backtest (BTC/USDT only)

```bash
python3 main.py backtest
```

### 4. Run portfolio backtest (BTC + ETH, parallel)

```bash
python3 main.py portfolio
```

### 5. Run tests

```bash
pytest tests/ -v
```

---

## Project Structure

```
mats-code/
├── main.py                    # CLI entry point (fetch | backtest | portfolio)
├── requirements.txt
├── pyproject.toml
├── data/
│   └── hot/data/              # Parquet store: {ASSET}/{TF}/YYYY-MM.parquet
├── docs/
│   └── architecture.md
├── src/
│   ├── config/
│   │   └── settings.py        # All locked parameters from the spec
│   ├── data/
│   │   ├── fetcher.py         # ccxt Binance REST fetcher
│   │   └── storage.py         # Parquet read/write helpers
│   ├── strategy/
│   │   ├── indicators.py      # RSI (pandas-ta, Wilder RMA, length=14)
│   │   ├── sr_levels.py       # Algorithm A: local extrema + clustering
│   │   ├── signals.py         # Signal 0.1 entry/exit logic
│   │   └── portfolio.py       # Rolling bounds + position sizing
│   ├── backtest/
│   │   ├── engine.py          # Single-asset backtest engine
│   │   ├── friction.py        # Fee/slippage + trade rejection
│   │   └── runner.py          # joblib parallel multi-asset runner
│   └── utils/
│       └── logger.py
└── tests/
    ├── test_indicators.py
    ├── test_sr_levels.py
    ├── test_signals.py
    ├── test_portfolio.py
    ├── test_friction.py
    └── test_engine.py
```

---

## Locked Parameters (Signal 0.1)

| Parameter | Value |
|---|---|
| Assets | BTC/USDT, ETH/USDT (Binance) |
| Execution TF | 1H |
| RSI length | 14 (Wilder RMA) |
| RSI oversold | < 30 |
| RSI overbought | > 70 |
| S/R window (N) | 5 candles |
| S/R max pivots (M) | 50 per timeframe |
| Cluster threshold | 0.5% |
| Proximity zone | ±2% |
| High-Conviction threshold | combined weight ≥ 5 |
| Rolling bounds window | 52 weeks |
| LPrice multiplier | 0.8× 52w low |
| UPrice multiplier | 1.2× 52w high |
| Taker fee | 0.10% |
| Slippage (flat) | 0.05% |
| Round-trip friction | 0.30% |
| Min trade spread | > 0.30% |
