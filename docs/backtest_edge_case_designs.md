# MATS Backtest Engine — Edge Case Implementation & Test Spec

This document details critical quantitative and system edge cases in the MATS backtest engine. It provides the exact context, potential risks, mathematical designs, **implementation blueprints (source code diffs)**, and **pytest skeleton implementations** for each scenario.

---

## 1. High-Conviction S/R Zone Collision & Tie-Breaking

### Description & Context
At any given timestamp, the close price can fall within the $\pm 2\%$ proximity of multiple active high-conviction S/R zones simultaneously (e.g., two support zones at $100.0$ and $101.5$ with a close price at $101.0$). 

### Current System Risk
In `src/strategy/signals.py`, the engine loops over `high_conviction` zones sequentially:
```python
for zone in high_conviction:
    if zone.kind == "support" and _price_near_zone(current_price, zone.price, proximity_pct):
        # ... triggers entry on the FIRST match in the iteration
```
This introduces non-determinism or suboptimal entries because the engine ignores zone weights or relative proximity, matching whichever zone happens to appear first in the active cache.

### 🛠️ Implementation Blueprint
Sort the high-conviction zones by `combined_weight` descending and then by relative proximity ascending before evaluating, ensuring the strongest and closest structural level is chosen as the trigger zone.

```python
# In src/strategy/signals.py inside evaluate_signal:
# Sort high_conviction zones:
# 1. Primary key: combined_weight descending
# 2. Secondary key: absolute distance from current_price ascending
high_conviction_sorted = sorted(
    [z for z in active_zones if z.combined_weight >= HIGH_CONVICTION_THRESHOLD],
    key=lambda z: (-z.combined_weight, abs(current_price - z.price))
)
```

### 🧪 Test Design & Pytest Skeleton
* **Input State**:
  * Price: $100.5$
  * Zone A (Support): Price = $100.0$, Combined Weight = $5$ (Minimum HC threshold)
  * Zone B (Support): Price = $101.0$, Combined Weight = $9$ (Stronger HC level)
  * RSI values are oversold for both.
* **Expected Output**: The engine should deterministically select **Zone B** (the stronger structural level) or evaluate both.

```python
def test_signal_collision_prioritizes_stronger_weight():
    """
    If multiple active support zones are in proximity, verify which zone is selected.
    We assert that the stronger zone (higher combined weight) is chosen as the trigger zone.
    """
    from src.strategy.signals import evaluate_signal
    from src.strategy.sr_levels import SRZone

    zone_weak = SRZone(price=100.0, kind="support", timeframe="1d", weight=3, bar_active_from=0, contributing_timeframes=["1d", "4h"], combined_weight=5)
    zone_strong = SRZone(price=101.0, kind="support", timeframe="1d", weight=6, bar_active_from=0, contributing_timeframes=["1d", "4h", "1h"], combined_weight=9)

    # Both zones are within 2% proximity of 100.5
    signal = evaluate_signal(
        current_price=100.5,
        current_timestamp_ms=1000,
        active_zones=[zone_weak, zone_strong],  # zone_weak is first in list
        rsi_by_tf={"1d": 25.0, "4h": 25.0, "1h": 25.0},
        l_price=50.0,
        in_position=False,
    )
    
    # Assert tie-breaking selects the high-weight level
    assert signal.action == "buy"
    assert signal.zone.price == 101.0
    assert signal.zone.combined_weight == 9
```

---

## 2. Division-by-Zero Safeguard for S/R Zone Price = 0.0

### Description & Context
If an asset crashes dramatically (e.g., distressed tokens like LUNA or FTT) or if historical data contains anomalies, a support level at price $0.0$ could be recorded.

### Current System Risk
In `src/strategy/signals.py`, `_price_near_zone` calculates:
```python
return abs(price - zone_price) / zone_price <= proximity_pct
```
If `zone_price == 0.0`, this raises a `ZeroDivisionError`, crashing the entire parallel portfolio runner.

### 🛠️ Implementation Blueprint
Add a safety guard inside `_price_near_zone` to check if `zone_price <= 0` and safely return `False`.

```python
# In src/strategy/signals.py:
def _price_near_zone(price: float, zone_price: float, proximity_pct: float = SR_PROXIMITY_PCT) -> bool:
    """True if price is within ±proximity_pct of zone_price."""
    if zone_price <= 0:
        return False
    return abs(price - zone_price) / zone_price <= proximity_pct
```

### 🧪 Test Design & Pytest Skeleton
* **Input State**: Price: $0.01$, Zone Price: $0.0$
* **Expected Output**: The function should return `False` safely without raising any exception.

```python
def test_price_near_zone_zero_division_safeguard():
    """Verify that a zone price of 0.0 does not raise a ZeroDivisionError."""
    from src.strategy.signals import _price_near_zone

    # Should safely return False rather than throwing ZeroDivisionError
    try:
        is_near = _price_near_zone(price=0.01, zone_price=0.0)
        assert is_near is False
    except ZeroDivisionError:
        pytest.fail("ZeroDivisionError raised for zone_price = 0.0")
```

---

## 3. Position Fraction Bounds Compression ($UPrice \approx LPrice$)

### Description & Context
In periods of extremely low volatility (e.g., highly peg-stable stablecoins or flat historical data gaps), the weekly high and weekly low in the trailing 52 weeks might be extremely close (or identical).

### Current System Risk
In `src/strategy/portfolio.py`:
```python
raw = 1.0 - (current_price - l_price) / (u_price - l_price)
```
If $UPrice - LPrice$ is exceptionally small (e.g. $0.00000001$), any tiny price variance creates massive, erratic swings in the unclamped position fraction. If $UPrice = LPrice$, it returns $0.0$, but near-equality is not guarded.

### 🛠️ Implementation Blueprint
Guard against division-by-zero or extremely narrow bounds (e.g., less than $1\text{e-5}$) to prevent floating-point anomalies.

```python
# In src/strategy/portfolio.py inside compute_position_fraction:
if u_price - l_price < 1e-5:
    log.warning("Compressed bounds (UPrice - LPrice < 1e-5) — returning 0 position fraction")
    return 0.0
```

### 🧪 Test Design & Pytest Skeleton
* **Input State**:
  * $LPrice = 1.00000000$ (weekly low multiplier adjusted)
  * $UPrice = 1.00000001$ (weekly high multiplier adjusted)
  * Current Price: $1.00500000$
* **Expected Output**: Ensure the fraction is clamped beautifully to $0.0$ and does not crash or raise numerical precision errors.

```python
def test_position_fraction_highly_compressed_bounds():
    """Verify position sizing under extreme volatility compression behaves stably."""
    from src.strategy.portfolio import compute_position_fraction

    fraction = compute_position_fraction(
        current_price=1.005,
        l_price=1.00000000,
        u_price=1.00000001,
    )
    # Price is way above compressed upper bound, fraction must clamp to 0.0 cleanly
    assert fraction == 0.0
```

---

## 4. Timeframe Alignment Out-of-Bounds (Early Execution Timestamp)

### Description & Context
During backtests, the active execution timeframe starts immediately, but structural data (e.g., weekly or monthly bars) might not have formed yet, meaning the execution bar's timestamp precedes the first available structural timestamp.

### Current System Risk
If an execution timestamp `ts_ms` is smaller than the first element in `ts_list`, binary search via `bisect.bisect_right(ts_list, ts_ms) - 1` returns index `-1`.
In Python, index `-1` retrieves the *last* element in the array (the future), creating a silent, severe **look-ahead bias**.

### 🛠️ Implementation Blueprint
Explicitly guard `idx < 0` inside `_align_rsi_fast` to return `None` (no RSI available) instead of fetching a wrapped last element (`rsi_list[-1]`).

```python
# In src/backtest/engine.py inside _align_rsi_fast:
idx = bisect.bisect_right(ts_list, ts_ms) - 1
if idx < 0:
    rsi_by_tf[tf] = None  # Correct safeguard against index -1 wrapping
else:
    val = rsi_list[idx]
    rsi_by_tf[tf] = float(val) if val is not None else None
```

### 🧪 Test Design & Pytest Skeleton
* **Input State**:
  * Sorted weekly timestamps: `[1000, 2000, 3000]`
  * Weekly RSI values: `[45.0, 50.0, 55.0]`
  * Query execution timestamp: `500` (preceding all structural data)
* **Expected Output**: The aligned RSI must return `None` rather than `55.0` (which is index `-1`).

```python
def test_align_rsi_fast_out_of_bounds_underflow():
    """
    Verify that querying a timestamp before any structural data exists
    returns None instead of wrapping to the last element (look-ahead bias safeguard).
    """
    from src.backtest.engine import _align_rsi_fast

    rsi_lookup = {
        "1w": ([1000, 2000, 3000], [45.0, 50.0, 55.0])
    }
    
    # 500 is before 1000
    aligned = _align_rsi_fast(rsi_lookup, ts_ms=500)
    assert aligned["1w"] is None  # Should not wrap to 55.0 (index -1)
```

---

## 5. Negative Spread Rejection (Inverted S/R Levels)

### Description & Context
Under rare clustering anomalies or temporary market inversions, a target resistance zone could mathematically exist *below* the close entry price.

### Current System Risk
If the target exit price is lower than the entry price, the spread is negative. In `is_trade_viable`:
```python
spread = (target_exit_price - entry_price) / entry_price
```
If target resistance is $95.0$ and support is $100.0$, the spread is $-5\%$. This is mathematically $\le 0.30\%$, so it correctly evaluates to `False`. However, we must explicitly verify this behavior to guarantee no trade is taken.

### 🛠️ Implementation Blueprint
The current math works correctly because a negative spread is less than `MIN_SPREAD_TO_TRADE` ($0.003$). However, we can add a descriptive log warning and explicitly ensure this edge case is tested.

```python
# In src/backtest/friction.py inside is_trade_viable:
spread = (target_exit_price - entry_price) / entry_price
if spread <= 0:
    log.warning(f"Inverted levels detected (support={entry_price}, resistance={target_exit_price})")
    return False
```

### 🧪 Test Design & Pytest Skeleton
* **Input State**: Entry price = $100.0$, Target exit price = $95.0$
* **Expected Output**: `is_trade_viable` must return `False` immediately.

```python
def test_is_trade_viable_negative_spread():
    """Verify that an inverted or negative spread is immediately rejected."""
    from src.backtest.friction import is_trade_viable

    # Resistance is below support
    viable = is_trade_viable(entry_price=100.0, target_exit_price=95.0)
    assert viable is False
```

---

## 6. Capital Allocation Inconsistencies for Undefined Symbols

### Description & Context
If a token is added to the backtest runner but is omitted from the static `ASSET_ALLOCATION` configuration in `src/config/settings.py`.

### Current System Risk
* `compute_position_size_usd()` defaults the asset's allocation fraction to `0.0`.
* `run_backtest()`'s isolated return calculation defaults the fraction to `1.0`.
This mismatch allows the backtest to run, but size all trades to exactly $0 USD$, while calculating isolated returns against the full $100\%$ portfolio capital, returning a flat $0\%$ return that dilutes actual performance.

### 🛠️ Implementation Blueprint
Align both fallbacks to use a safe default of `0.0` or explicitly raise a `ValueError` for undefined symbols so that the user is immediately warned of missing configurations.

```python
# In src/backtest/engine.py inside run_backtest:
asset_frac = ASSET_ALLOCATION.get(symbol, 0.0)  # Corrected from 1.0 to 0.0 to match sizing consistency
if asset_frac <= 0:
    log.warning(f"Symbol {symbol} has 0.0 or undefined asset allocation fraction — isolated return set to 0.0")
```

### 🧪 Test Design & Pytest Skeleton
* **Input State**: Symbol `"UNKNOWN/USDT"` (not defined in allocation dictionary).
* **Expected Output**: The sizing function and isolated return calculation should handle missing config consistently.

```python
def test_capital_allocation_undefined_symbol_behavior():
    """Verify that undefined symbols are sized consistently across modules."""
    from src.strategy.portfolio import compute_position_size_usd
    from src.config.settings import ASSET_ALLOCATION

    symbol = "RANDOMCOIN/USDT"
    assert symbol not in ASSET_ALLOCATION

    # Sizing should return 0.0 because allocation is 0
    size = compute_position_size_usd(
        symbol=symbol,
        current_price=100.0,
        total_capital=10000.0,
        l_price=50.0,
        u_price=150.0
    )
    assert size == 0.0
```
