# Architecture Evaluation: MATS Backtest Performance Analysis & Fixes

This document provides a comprehensive technical diagnosis of the performance issues (negative total returns) identified in the MATS backtest run `log_portfolio_20260515_1835.txt`. It outlines the core logical flaws, evaluates the mathematical validity of the Support/Resistance (S/R) and RSI strategy, and details sequential fixes with concrete code modifications. 

Use this document to prompt other LLMs for architectural review, validation, or further optimization.

---

## 1. Executive Summary
The backtest results for several assets returned negative performance despite the theoretical soundness of the underlying S/R and RSI strategy. The primary causes of failure are not the strategic indicators themselves, but rather **implementation-level architectural flaws**:
1. **Global Look-Ahead Bias** introduced by pre-clustering pivot zones across the entire historical timeline.
2. **Low-Timeframe Indicator Pollution** where ultra-short-term noise (1m/5m RSI) contaminated high-timeframe (Weekly/Daily) structural support levels.
3. **Friction Bleeding (Whipsawing)** resulting in high-frequency trading loops at a single price zone, where commissions and slippage slowly eroded the capital.

---

## 2. Detailed Technical Diagnosis

### A. The S/R Clustering Look-Ahead Bug
* **The Flaw:** In `sr_levels.py:L195-227`, the function `build_sr_zones` runs a global pivot-clustering algorithm (`cluster_zones`) across the *entire* historical dataset before the backtest loop begins. 
* **The Mechanism:** When a weekly support level from `2020` is close in price to a 5-minute pivot from `2026`, they are merged into a single `SRZone`. The zone's `bar_active_from` is set to the minimum timestamp (`active_from = min(prev.bar_active_from, zone.bar_active_from)`).
* **The Impact:** The merged zone's **price** (averaged with a future pivot) and **`contributing_timeframes`** list (containing future low-TF entries) are contaminated by data that does not exist yet at `bar_active_from`. Note: the activation timestamp itself is conservatively set to the *earliest* constituent — so the zone appears at the correct time, but with **wrong properties** (price, weight, timeframe list). This violates the strict "look-ahead-bias-free" rule required for quantitative modeling.

### B. Timeframe RSI Contamination
* **The Flaw:** When zones are merged, their `contributing_timeframes` are concatenated. For example, a weekly zone merged with a 5-minute pivot contains `['1w', '5m']`.
* **The Mechanism:** The entry logic (`signals.py:L50-59`) checks if *at least one* contributing timeframe's RSI is oversold ($< 30$):
  ```python
  for tf in zone.contributing_timeframes:
      rsi = rsi_by_tf.get(tf)
      if rsi is not None and rsi < 30:
          return True
  ```
* **The Impact:** Because 5-minute RSI constantly dips below 30 due to normal market noise, it constantly triggers a "BUY" confirmation at the Weekly support price, even when the weekly trend is in a strong downtrend and weekly momentum is not oversold. 

### C. HFT Whipsawing and Friction Bleeding
* **The Flaw:** When support and resistance levels overlap due to clustering, a price level (e.g., DOGE at `$0.11`) can act as support and resistance simultaneously.
* **The Mechanism:** 
  1. Bar 1: Price is near `$0.11` (Support Zone) and 5m RSI dips below 30 $\rightarrow$ **BUY**.
  2. Bar 2: Price is still near `$0.11` (Resistance Zone) and 5m RSI spikes above 70 $\rightarrow$ **SELL**.
  3. Bar 3: Price remains near `$0.11`, 5m RSI dips below 30 $\rightarrow$ **BUY**.
* **The Impact:** The system gets caught in a loop of rapid execution at the same price zone. Every round-trip trade incurs a **0.30% fee/slippage cost (friction)** (`settings.py:L115`). Over dozens of trades, the capital is slowly bled to zero by execution friction despite no significant price movement.

---

## 3. Evaluation of the S/R + RSI Strategy Validity

### Is the core strategy still relevant?
**Yes.** Quantitative finance literature (e.g., Kaufman, Murphy, Chan) validates the combination of S/R and RSI under strict constraints:
* **Structural vs. Momentum Alignment:** S/R zones provide structural context (where the trade should happen), and RSI provides momentum confirmation (when the trend is exhausted).
* **Timeframe Parity:** High-timeframe structural zones (Weekly/Daily) must be paired with high-timeframe momentum indicators. Pair weekly support with weekly RSI, and 1H support with 1H RSI. Pairs must never cross-contaminate.

---

## 4. Concrete Implementation Fixes

### Fix 1: Sequential, Look-Ahead-Free S/R Clustering
Instead of pre-clustering globally, feed raw (unclustered) pivots into the backtest loop sorted by `bar_active_from`, and cluster **incrementally** as new pivots activate.

> **⚠️ Performance Warning:** Do NOT call `cluster_zones()` on the full `active_zones_cache` on every bar — that creates an O(n²) hotpath across ~17k iterations and will destroy performance. Instead, use an **incremental merge**: when a new pivot activates, attempt to merge it into the existing clustered set (O(k) where k = current active zones), which is amortized O(1) per bar.

```diff
# src/strategy/sr_levels.py — NEW FUNCTION
+def merge_zone_into_clustered(
+    clustered: list[SRZone],
+    new_zone: SRZone,
+    threshold: float = SR_CLUSTER_THRESHOLD,
+) -> list[SRZone]:
+    """
+    Incrementally merge a single new zone into an already-clustered list.
+    Only merges with same-kind zones within threshold. O(k) per call.
+    """
+    for i, existing in enumerate(clustered):
+        if existing.kind != new_zone.kind:
+            continue
+        distance = abs(existing.price - new_zone.price) / existing.price
+        if distance <= threshold:
+            avg_price = (existing.price + new_zone.price) / 2
+            combined_tfs = list(set(existing.contributing_timeframes + new_zone.contributing_timeframes))
+            combined_weight = existing.combined_weight + new_zone.weight
+            active_from = min(existing.bar_active_from, new_zone.bar_active_from)
+            clustered[i] = SRZone(
+                price=avg_price,
+                kind=existing.kind,
+                timeframe=existing.timeframe,
+                weight=existing.weight,
+                bar_active_from=active_from,
+                contributing_timeframes=combined_tfs,
+                combined_weight=combined_weight,
+            )
+            return clustered
+    clustered.append(new_zone)
+    return clustered
```

```diff
# src/backtest/engine.py (Lines 297-300)
-        # -- Advance active zones pointer (amortized O(1) instead of O(n) filter each bar) --
-        while zone_ptr < len(all_zones_sorted) and all_zones_sorted[zone_ptr].bar_active_from <= ts_ms:
-            active_zones_cache.append(all_zones_sorted[zone_ptr])
-            zone_ptr += 1
-        active_zones = active_zones_cache

+        # -- Advance raw pivots and merge incrementally (Look-Ahead-Bias-Free) --
+        from src.strategy.sr_levels import merge_zone_into_clustered
+        while zone_ptr < len(all_zones_sorted) and all_zones_sorted[zone_ptr].bar_active_from <= ts_ms:
+            merge_zone_into_clustered(active_zones_cache, all_zones_sorted[zone_ptr])
+            zone_ptr += 1
+        active_zones = active_zones_cache
```

Also change `build_sr_zones` to return **unclustered** pivots when called from the engine, so the engine receives raw pivots for incremental merging:

```diff
# src/backtest/engine.py (Line 224)
-        all_zones = build_sr_zones(frames)
+        all_zones = build_sr_zones(frames, cluster=False)  # raw pivots; engine clusters incrementally
```

### Fix 2: Remove Low-Timeframe Noise
For a 1-hour execution timeframe strategy, sub-1H timeframes (`1m`, `5m`, `15m`, `30m`) should not be computed.

```diff
# src/config/settings.py (Lines 27-28)
- TIMEFRAMES = ["1m", "5m", "15m", "30m", "1h", "2h", "4h", "1d", "1w", "1M"]
+ TIMEFRAMES = ["1h", "2h", "4h", "1d", "1w", "1M"]
```

### Fix 3: Strict Timeframe-to-RSI Alignment
Modify signal validation to strictly check the RSI of the *strongest* (highest) contributing timeframe of the S/R zone.

```diff
# src/strategy/signals.py (Lines 50-70)
def _rsi_confirms_entry(zone: SRZone, rsi_by_tf: dict[str, float | None]) -> bool:
-    for tf in zone.contributing_timeframes:
-        rsi = rsi_by_tf.get(tf)
-        if rsi is not None and rsi < 30:
-            return True
-    return False

+    # Sort timeframes by strength and only check the strongest one
+    from src.config.settings import SR_WEIGHTS
+    strongest_tf = max(zone.contributing_timeframes, key=lambda tf: SR_WEIGHTS.get(tf, 0))
+    rsi = rsi_by_tf.get(strongest_tf)
+    return rsi is not None and rsi < 30
```

> **Alternative (stricter):** Require RSI confirmation from **all** contributing timeframes (conjunction), not just the strongest. This eliminates the "weakest link" problem entirely but may reduce trade frequency:
>
> ```python
> def _rsi_confirms_entry(zone, rsi_by_tf):
>     return all(
>         (rsi := rsi_by_tf.get(tf)) is not None and rsi < 30
>         for tf in zone.contributing_timeframes
>     )
> ```

### Fix 4: Implement a Per-Zone Trade Cooldown
To prevent HFT fee-bleeding loops during ranging consolidation, implement a minimum trade cooldown **per S/R zone** (e.g., 24 hours). A global cooldown is too blunt — it would suppress legitimate entries at *different* price levels after a stop-loss at an unrelated zone.

```diff
# src/backtest/engine.py (Before the main loop)
+        # Track per-zone cooldowns: {zone_price_bucket: last_exit_timestamp_ms}
+        zone_cooldowns: dict[int, int] = {}
+        COOLDOWN_MS = 24 * 3600 * 1000  # 24 hours
```

```diff
# src/backtest/engine.py (Inside loop, before buying — after signal evaluation)
+        # -- Prevent overtrading: per-zone 24-hour cooldown --
+        if signal.action == "buy" and signal.zone is not None:
+            zone_bucket = round(signal.zone.price, 2)  # bucket by price
+            last_exit = zone_cooldowns.get(zone_bucket, 0)
+            if ts_ms - last_exit < COOLDOWN_MS:
+                equity_curve.append(capital)
+                continue
```

```diff
# src/backtest/engine.py (After completing a sell)
+            # Record cooldown for the zone that triggered the original entry
+            if current_trade.entry_price:
+                zone_cooldowns[round(current_trade.entry_price, 2)] = ts_ms
```

### Fix 5 (New): Skip `cluster_zones()` in `build_sr_zones()` for Engine Use
The `build_sr_zones()` function currently always clusters. Add a `cluster=True` flag so the engine can request raw pivots for incremental merging, while other callers (analysis, visualization) still get the pre-clustered output.

```diff
# src/strategy/sr_levels.py (Line 195-227)
 def build_sr_zones(
     frames: dict[str, pl.DataFrame],
     window: int = SR_PIVOT_WINDOW,
     max_pivots: int = SR_MAX_PIVOTS,
     cluster_threshold: float = SR_CLUSTER_THRESHOLD,
+    cluster: bool = True,
 ) -> list[SRZone]:
     ...
-    clustered = cluster_zones(all_zones, threshold=cluster_threshold)
+    if cluster:
+        clustered = cluster_zones(all_zones, threshold=cluster_threshold)
+    else:
+        clustered = all_zones
```

---

## 5. Instructions for Evaluator LLMs

*Copy and paste this section along with this document into another LLM to request an evaluation.*

```markdown
Hello! Please evaluate the technical diagnosis, strategic validity, and code diffs presented in the document above. 

Specifically, address the following:
1. **Critical Review:** Do you agree that the global S/R clustering logic introduces look-ahead bias and that timeframe concatenation pollutes the RSI validation rules?
2. **Feasibility of Fixes:** Are the proposed code changes (on-the-fly clustering, timeframe limitation, strongest-timeframe RSI validation, and trade cooldown) effective, robust, and free of side effects?
3. **Alternative Solutions:** Can you suggest alternative or more elegant ways to handle point-in-time S/R zone clustering or timeframe-aligned momentum indicators without increasing processing latency?
4. **Execution Mode Advice:** Would utilizing limit orders (Maker model) instead of market orders (Taker model) materially improve the transaction cost analysis for this specific strategy?
```
