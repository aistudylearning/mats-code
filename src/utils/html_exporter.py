import os
import shutil
from datetime import datetime, timezone
import json
import polars as pl

from src.backtest.engine import BacktestResult
from src.config.settings import MVP_ASSETS
from src.data.storage import load_ohlcv
from src.utils.logger import get_logger

log = get_logger(__name__)

# Google Drive reports folder — used automatically when running on Colab.
_DRIVE_REPORTS_DIR = "/content/drive/MyDrive/trading/reports"


def _copy_to_drive(local_path: str) -> None:
    """If running on Colab with Drive mounted, copy the report there automatically."""
    if not os.path.isdir(_DRIVE_REPORTS_DIR):
        return  # Not on Colab or Drive not mounted — silently skip.
    try:
        dest = os.path.join(_DRIVE_REPORTS_DIR, os.path.basename(local_path))
        shutil.copy2(local_path, dest)
        log.info(f"📊 Report also saved to Drive: {dest}")
    except Exception as e:
        log.warning(f"Could not copy report to Drive: {e}")


def generate_sparkline_data(symbol: str, data_root: str, max_points: int = 100) -> list[float]:
    """Load weekly data to generate a small price array for the sparkline."""
    try:
        df = load_ohlcv(symbol, "1w", root=data_root)
        if df.is_empty():
            df = load_ohlcv(symbol, "1d", root=data_root)
        if df.is_empty():
            return []
        prices = df["close"].to_list()
        if len(prices) > max_points:
            step = len(prices) / max_points
            downsampled = [prices[int(i * step)] for i in range(max_points)]
            downsampled[-1] = prices[-1]
            return downsampled
        return prices
    except Exception as e:
        log.warning(f"Failed to generate sparkline for {symbol}: {e}")
        return []


def load_chart_data(symbol: str, tf: str, data_root: str, max_candles: int = 1000) -> list[dict]:
    """Load detailed candlestick data for the detailed charting modal."""
    try:
        df = load_ohlcv(symbol, tf, root=data_root)
        if df.is_empty():
            return []
        
        # Take the most recent max_candles
        df_tail = df.tail(max_candles)
        records = df_tail.select(["timestamp", "open", "high", "low", "close"]).to_dicts()
        
        # Lightweight Charts expects time in seconds for Unix timestamps
        formatted = []
        for r in records:
            formatted.append({
                "time": r["timestamp"] / 1000,
                "open": r["open"],
                "high": r["high"],
                "low": r["low"],
                "close": r["close"]
            })
        return formatted
    except Exception as e:
        log.warning(f"Failed to load detailed chart data for {symbol} {tf}: {e}")
        return []


def _build_assets_data(results: dict[str, BacktestResult], data_root: str, tf: str) -> list[dict]:
    """Build the asset data list for a single timeframe."""
    mcap_rank = {sym: idx + 1 for idx, sym in enumerate(MVP_ASSETS)}
    assets_data = []
    for symbol, res in results.items():
        sparkline = generate_sparkline_data(symbol, data_root)
        
        # Format S/R Zones
        sr_data = [
            {"price": z.price, "kind": z.kind, "weight": z.combined_weight} 
            for z in res.sr_zones
        ]
        
        # Format Trade History
        trades_data = []
        for t in res.trades:
            trades_data.append({
                "entry_time": t.entry_timestamp_ms / 1000,
                "entry_price": t.entry_price,
                "exit_time": (t.exit_timestamp_ms / 1000) if t.exit_timestamp_ms else None,
                "exit_price": t.exit_price,
                "pnl": t.pnl,
                "exit_reason": t.exit_reason
            })

        assets_data.append({
            "symbol": symbol,
            "mcap_rank": mcap_rank.get(symbol, 999),
            "total_return": res.total_return_pct,
            "isolated_return": res.isolated_return_pct,
            "win_rate": res.win_rate_pct,
            "max_dd": res.max_drawdown_pct,
            "trades": res.total_trades,
            "final_capital": res.final_capital,
            "sparkline": sparkline,
            "chart_data": load_chart_data(symbol, tf, data_root),
            "sr_zones": sr_data,
            "trades_history": trades_data,
            "tradingview_url": f"https://www.tradingview.com/chart/?symbol=BINANCE:{symbol.replace('/', '')}"
        })
    return assets_data


def export_results_to_html(results: dict[str, BacktestResult], data_root: str, out_dir: str = "output") -> None:
    """Generate an interactive HTML report from backtest results (single timeframe)."""
    export_multi_tf_html({"1h": results}, data_root=data_root, out_dir=out_dir)


def export_multi_tf_html(
    all_tf_results: dict[str, dict[str, BacktestResult]],
    data_root: str,
    out_dir: str = "output",
) -> None:
    """Generate a multi-timeframe tabbed HTML report."""
    os.makedirs(out_dir, exist_ok=True)
    timestamp_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_path = os.path.join(out_dir, f"portfolio_report_{timestamp_str}.html")

    # Build data payload: { "1h": [...], "4h": [...], ... }
    payload: dict[str, list] = {}
    for tf, results in all_tf_results.items():
        payload[tf] = _build_assets_data(results, data_root, tf)

    # json.dumps() does not escape U+2028 (LINE SEPARATOR) or U+2029 (PARAGRAPH SEPARATOR).
    # These are valid in JSON strings but act as JavaScript line terminators inside <script> blocks,
    # causing "Unexpected token" SyntaxErrors that silently kill the entire script.
    # We also escape </script> to prevent premature script-tag termination.
    json_payload = (
        json.dumps(payload)
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
        .replace("</script>", "<\\/script>")
    )
    html_content = _get_html_template().replace("{{MULTI_TF_DATA_JSON}}", json_payload)

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    log.info(f"Exported multi-timeframe HTML report to: {out_path}")
    _copy_to_drive(out_path)


def _get_html_template() -> str:
    return """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>MATS Strategy — Portfolio Report</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <script src="https://unpkg.com/lightweight-charts@4.2.0/dist/lightweight-charts.standalone.production.js"></script>
    <style>
        :root {
            --bg: #0f111a;
            --surface: rgba(25, 28, 41, 0.85);
            --border: rgba(255,255,255,0.07);
            --text: #f1f3f9;
            --muted: #8892aa;
            --accent: #6366f1;
            --accent-glow: rgba(99,102,241,0.35);
            --positive: #10b981;
            --negative: #ef4444;
            --tab-active-bg: rgba(99,102,241,0.18);
        }
        * { box-sizing: border-box; margin: 0; padding: 0; }

        body {
            font-family: 'Inter', sans-serif;
            background: var(--bg);
            color: var(--text);
            min-height: 100vh;
            padding: 36px 20px 60px;
            background-image:
                radial-gradient(circle at 10% 40%, rgba(99,102,241,0.07), transparent 30%),
                radial-gradient(circle at 90% 20%, rgba(16,185,129,0.04), transparent 30%);
            background-attachment: fixed;
        }

        .container { max-width: 1440px; margin: 0 auto; }

        header {
            display: flex;
            justify-content: space-between;
            align-items: flex-end;
            margin-bottom: 32px;
            padding-bottom: 20px;
            border-bottom: 1px solid var(--border);
        }
        h1 {
            font-size: 2rem;
            font-weight: 700;
            background: linear-gradient(135deg, #fff 30%, #8892aa);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        .subtitle {
            font-size: 0.85rem;
            color: var(--muted);
            margin-top: 4px;
        }

        /* ── Timeframe Tabs ── */
        .tf-tabs {
            display: flex;
            gap: 8px;
            margin-bottom: 24px;
            flex-wrap: wrap;
        }
        .tf-tab {
            padding: 8px 20px;
            border-radius: 8px;
            border: 1px solid var(--border);
            background: var(--surface);
            color: var(--muted);
            font-family: 'Inter', sans-serif;
            font-size: 0.9rem;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s ease;
            backdrop-filter: blur(8px);
            letter-spacing: 0.5px;
        }
        .tf-tab:hover {
            border-color: var(--accent);
            color: var(--text);
        }
        .tf-tab.active {
            background: var(--tab-active-bg);
            border-color: var(--accent);
            color: var(--text);
            box-shadow: 0 0 12px var(--accent-glow);
        }

        /* ── Table ── */
        .table-wrap {
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 16px;
            overflow-x: auto;
            box-shadow: 0 8px 32px rgba(0,0,0,0.25);
            backdrop-filter: blur(12px);
        }
        table { width: 100%; border-collapse: collapse; white-space: nowrap; }

        th, td { padding: 14px 22px; text-align: right; border-bottom: 1px solid var(--border); }
        th:nth-child(1), td:nth-child(1),
        th:nth-child(2), td:nth-child(2) { text-align: left; }
        tr:last-child td { border-bottom: none; }
        tr:hover td { background: rgba(255,255,255,0.02); }

        th {
            color: var(--muted);
            font-size: 0.78rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.6px;
            cursor: pointer;
            user-select: none;
            transition: color 0.2s;
        }
        th:hover { color: var(--text); }

        .sort-icon {
            display: inline-block;
            width: 0; height: 0;
            border-left: 4px solid transparent;
            border-right: 4px solid transparent;
            margin-left: 5px;
            vertical-align: middle;
            opacity: 0.25;
        }
        th.sort-asc .sort-icon  { border-bottom: 4px solid var(--text); opacity: 1; }
        th.sort-desc .sort-icon { border-top:    4px solid var(--text); opacity: 1; }

        .asset-link {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            font-weight: 600;
            font-size: 1rem;
            text-decoration: none;
            color: var(--text);
            transition: color 0.2s;
        }
        .asset-link:hover { color: var(--accent); }
        .tv-badge {
            font-size: 0.72rem;
            font-weight: 700;
            padding: 2px 6px;
            border-radius: 4px;
            background: rgba(41,98,255,0.12);
            color: #4d85ff;
            transition: background 0.2s, color 0.2s;
        }
        .asset-link:hover .tv-badge { background: #2962ff; color: #fff; }

        .val { font-size: 0.95rem; font-weight: 500; }
        .pos { color: var(--positive); }
        .neg { color: var(--negative); }

        .spark-cell { width: 180px; padding: 6px 22px !important; vertical-align: middle; }
        .spark-wrap { height: 38px; width: 140px; }
        .spark { width: 100%; height: 100%; overflow: visible; }
        .spark-path { fill: none; stroke-width: 1.5; stroke-linecap: round; stroke-linejoin: round; }
        .spark-fill  { stroke: none; }

        .rank-num { color: var(--muted); font-size: 0.9rem; }

        /* ── Modal ── */
        .modal { display: none; position: fixed; inset: 0; z-index: 1000; background: rgba(0,0,0,0.8); backdrop-filter: blur(4px); align-items: center; justify-content: center; }
        .modal.active { display: flex; }
        .modal-content { background: var(--bg); border: 1px solid var(--border); border-radius: 16px; width: 90vw; max-width: 1200px; padding: 24px; display: flex; flex-direction: column; gap: 16px; box-shadow: 0 16px 48px rgba(0,0,0,0.5); }
        .modal-header { display: flex; justify-content: space-between; align-items: center; }
        .modal-title { font-size: 1.2rem; font-weight: 600; }
        .modal-close { background: none; border: none; color: var(--muted); font-size: 2rem; line-height: 1; cursor: pointer; }
        .modal-close:hover { color: var(--text); }
        #chartContainer { width: 100%; height: 600px; }
        .clickable-cell { cursor: pointer; transition: opacity 0.2s; }
        .clickable-cell:hover { opacity: 0.8; }
    </style>
</head>
<body>
<div class="container">
    <header>
        <div>
            <h1>Portfolio Backtest Results</h1>
            <p class="subtitle">MATS Strategy A · Signal Analysis · Multi-Timeframe</p>
        </div>
    </header>

    <div class="tf-tabs" id="tfTabs"></div>

    <div class="table-wrap">
        <table>
            <thead>
                <tr>
                    <th data-sort="mcap_rank" class="sort-asc"># <span class="sort-icon"></span></th>
                    <th data-sort="symbol">Asset <span class="sort-icon"></span></th>
                    <th data-sort="total_return">Total Return <span class="sort-icon"></span></th>
                    <th data-sort="isolated_return">Isolated Return <span class="sort-icon"></span></th>
                    <th data-sort="win_rate">Win Rate <span class="sort-icon"></span></th>
                    <th data-sort="max_dd">Max Drawdown <span class="sort-icon"></span></th>
                    <th data-sort="trades">Trades <span class="sort-icon"></span></th>
                    <th>Price History</th>
                    <th>Trade History</th>
                </tr>
            </thead>
            <tbody id="tableBody"></tbody>
        </table>
    </div>
</div>

<div class="modal" id="chartModal">
    <div class="modal-content">
        <div class="modal-header">
            <div class="modal-title" id="modalTitle">Chart</div>
            <button class="modal-close" onclick="closeChartModal()">&times;</button>
        </div>
        <div id="chartContainer"></div>
    </div>
</div>

<script>
    const multiTfData = {{MULTI_TF_DATA_JSON}};
    const timeframes = Object.keys(multiTfData);

    let activeTf = timeframes[0];
    let currentSort = { column: 'mcap_rank', asc: true };

    // ── Tabs ──────────────────────────────────────────────────────────────
    const tfTabsEl = document.getElementById('tfTabs');
    timeframes.forEach(tf => {
        const btn = document.createElement('button');
        btn.className = 'tf-tab' + (tf === activeTf ? ' active' : '');
        btn.textContent = tf.toUpperCase();
        btn.dataset.tf = tf;
        btn.addEventListener('click', () => {
            activeTf = tf;
            document.querySelectorAll('.tf-tab').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            renderTable();
        });
        tfTabsEl.appendChild(btn);
    });

    // ── Sorting ───────────────────────────────────────────────────────────
    const headers = document.querySelectorAll('th[data-sort]');
    const tbody = document.getElementById('tableBody');

    headers.forEach(th => {
        th.addEventListener('click', () => {
            const col = th.dataset.sort;
            if (currentSort.column === col) {
                currentSort.asc = !currentSort.asc;
            } else {
                currentSort.column = col;
                currentSort.asc = true;
            }
            headers.forEach(h => h.classList.remove('sort-asc', 'sort-desc'));
            th.classList.add(currentSort.asc ? 'sort-asc' : 'sort-desc');
            renderTable();
        });
    });

    // ── Sparkline ─────────────────────────────────────────────────────────
    function createSparkline(data, positive) {
        if (!data || data.length < 2) return '';
        const min = Math.min(...data), max = Math.max(...data);
        const range = max - min || 1;
        const W = 140, H = 38;
        const pts = data.map((v, i) => {
            const x = (i / (data.length - 1)) * W;
            const y = H - ((v - min) / range) * H;
            return `${x},${y}`;
        }).join(' ');
        const color = positive ? '#10b981' : '#ef4444';
        const gid = 'g' + Math.random().toString(36).slice(2, 9);
        return `<svg class="spark" viewBox="0 -4 140 46" preserveAspectRatio="none">
            <defs>
                <linearGradient id="${gid}" x1="0" x2="0" y1="0" y2="1">
                    <stop offset="0%" stop-color="${color}" stop-opacity="0.2"/>
                    <stop offset="100%" stop-color="${color}" stop-opacity="0"/>
                </linearGradient>
            </defs>
            <polygon class="spark-fill" points="0,${H} ${pts} ${W},${H}" fill="url(#${gid})"/>
            <polyline class="spark-path" points="${pts}" stroke="${color}"/>
        </svg>`;
    }

    function fmtPct(v) {
        const cls = v >= 0 ? 'pos' : 'neg';
        const sign = v > 0 ? '+' : '';
        return `<span class="val ${cls}">${sign}${v.toFixed(2)}%</span>`;
    }

    // ── Render ────────────────────────────────────────────────────────────
    function renderTable() {
        const data = [...(multiTfData[activeTf] || [])];
        const col = currentSort.column;
        data.sort((a, b) => {
            let va = a[col], vb = b[col];
            if (typeof va === 'string') { va = va.toLowerCase(); vb = vb.toLowerCase(); }
            if (va < vb) return currentSort.asc ? -1 : 1;
            if (va > vb) return currentSort.asc ?  1 : -1;
            return 0;
        });

        tbody.innerHTML = data.map(asset => `
            <tr>
                <td class="rank-num">${asset.mcap_rank}</td>
                <td>
                    <a href="${asset.tradingview_url}" target="_blank" class="asset-link">
                        ${asset.symbol.split('/')[0]}
                        <span class="tv-badge">TV</span>
                    </a>
                </td>
                <td>${fmtPct(asset.total_return)}</td>
                <td>${fmtPct(asset.isolated_return)}</td>
                <td class="val">${asset.win_rate.toFixed(1)}%</td>
                <td class="val">${asset.max_dd.toFixed(2)}%</td>
                <td class="val">${asset.trades}</td>
                <td class="spark-cell clickable-cell" onclick="showChartModal('${asset.symbol}', 'price')">
                    <div class="spark-wrap" title="Click to view Price History & S/R Levels">
                        ${createSparkline(asset.sparkline, asset.total_return >= 0)}
                    </div>
                </td>
                <td class="spark-cell clickable-cell" onclick="showChartModal('${asset.symbol}', 'trades')">
                    <div class="spark-wrap" style="display:flex;align-items:center;justify-content:flex-end;" title="Click to view Trade History & Signals">
                        <span style="padding: 4px 12px; background: rgba(99,102,241,0.1); border: 1px solid var(--accent); border-radius: 4px; font-size: 0.8rem; color: var(--accent);">View Trades</span>
                    </div>
                </td>
            </tr>
        `).join('');
    }

    // Initial render
    renderTable();

    // ── Chart Modals ──────────────────────────────────────────────────────
    let currentChart = null;

    function closeChartModal() {
        document.getElementById('chartModal').classList.remove('active');
        if (currentChart) {
            currentChart.remove();
            currentChart = null;
        }
    }

    function showChartModal(symbol, type) {
        const asset = multiTfData[activeTf].find(a => a.symbol === symbol);
        if (!asset || !asset.chart_data.length) return;

        document.getElementById('modalTitle').textContent = `${symbol} - ${activeTf.toUpperCase()} - ${type === 'price' ? 'Price & S/R Levels' : 'Trade History'}`;
        document.getElementById('chartModal').classList.add('active');

        const container = document.getElementById('chartContainer');
        container.innerHTML = '';

        // CRITICAL FIX: Defer chart creation until AFTER the browser has painted
        // the modal. Without this, the container has 0x0 dimensions and the chart
        // renders as an invisible black box.
        requestAnimationFrame(() => {
            const w = container.clientWidth || 900;
            const h = container.clientHeight || 560;

            currentChart = LightweightCharts.createChart(container, {
                width: w,
                height: h,
                layout: { background: { color: '#0f111a' }, textColor: '#8892aa' },
                grid: { vertLines: { color: 'rgba(255,255,255,0.05)' }, horzLines: { color: 'rgba(255,255,255,0.05)' } },
                crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
                timeScale: { timeVisible: true, secondsVisible: false }
            });

            const candleSeries = currentChart.addCandlestickSeries({
                upColor: '#10b981', downColor: '#ef4444', borderVisible: false, wickUpColor: '#10b981', wickDownColor: '#ef4444'
            });
            
            candleSeries.setData(asset.chart_data);

            if (type === 'price') {
                asset.sr_zones.forEach(zone => {
                    candleSeries.createPriceLine({
                        price: zone.price,
                        color: zone.kind === 'support' ? 'rgba(16, 185, 129, 0.7)' : 'rgba(239, 68, 68, 0.7)',
                        lineWidth: zone.weight >= 5 ? 2 : 1,
                        lineStyle: zone.weight >= 5 ? LightweightCharts.LineStyle.Solid : LightweightCharts.LineStyle.Dashed,
                        axisLabelVisible: true,
                        title: `${zone.kind.toUpperCase()} (W:${zone.weight})`
                    });
                });
            } else if (type === 'trades') {
                try {
                    const markers = [];
                    const chartStart = asset.chart_data[0].time;
                    const chartEnd   = asset.chart_data[asset.chart_data.length - 1].time;

                    // Build a sorted array of exact chart timestamps for binary-search snapping.
                    const chartTimes = asset.chart_data.map(d => d.time); // already sorted

                    // Snap t to the nearest available chart timestamp.
                    // Returns null if t is outside the chart range by more than one bar interval.
                    const snap = (t) => {
                        if (t < chartStart || t > chartEnd) return null;
                        let lo = 0, hi = chartTimes.length - 1;
                        while (lo < hi) {
                            const mid = Math.floor((lo + hi) / 2);
                            if (chartTimes[mid] < t) lo = mid + 1; else hi = mid;
                        }
                        // Pick the closer of lo-1 or lo
                        if (lo > 0 && Math.abs(chartTimes[lo-1] - t) < Math.abs(chartTimes[lo] - t)) lo--;
                        return chartTimes[lo];
                    };

                    asset.trades_history.forEach(trade => {
                        const exitTime  = trade.exit_time  || chartEnd;
                        const exitPrice = trade.exit_price || asset.chart_data[asset.chart_data.length - 1].close;

                        // Skip trades that are entirely outside the visible chart window
                        if (exitTime < chartStart) return;
                        if (trade.entry_time > chartEnd) return;

                        const sEntry = snap(trade.entry_time);
                        const sExit  = snap(exitTime);

                        // Entry marker — only if entry falls inside the chart window
                        if (sEntry !== null) {
                            markers.push({
                                time: sEntry,
                                position: 'belowBar',
                                color: '#10b981',
                                shape: 'arrowUp',
                                text: `Buy @ ${trade.entry_price ? trade.entry_price.toFixed(2) : '?'}`
                            });
                        }

                        // Exit marker — snap to first bar if trade started before chart
                        const exitSnapped = sExit !== null ? sExit : chartStart;
                        markers.push({
                            time: exitSnapped,
                            position: 'aboveBar',
                            color: '#ef4444',
                            shape: 'arrowDown',
                            text: `Sell @ ${exitPrice.toFixed(2)} (${trade.pnl >= 0 ? '+' : ''}${trade.pnl ? trade.pnl.toFixed(2) : '?'}%)`
                        });

                        // PnL connecting dashed line — only when there are two distinct snapped times
                        const lineStart = sEntry !== null ? sEntry : chartStart;
                        if (lineStart < exitSnapped) {
                            try {
                                const tradeSeries = currentChart.addLineSeries({
                                    color: trade.pnl > 0 ? 'rgba(16,185,129,0.4)' : 'rgba(239,68,68,0.4)',
                                    lineStyle: LightweightCharts.LineStyle.Dashed,
                                    lineWidth: 1,
                                    crosshairMarkerVisible: false,
                                    lastValueVisible: false,
                                    priceLineVisible: false,
                                });
                                tradeSeries.setData([
                                    { time: lineStart,    value: trade.entry_price || exitPrice },
                                    { time: exitSnapped,  value: exitPrice }
                                ]);
                            } catch (e) {
                                console.warn("Could not draw connecting line:", e.message);
                            }
                        }
                    });

                    if (markers.length > 0) {
                        markers.sort((a, b) => a.time - b.time);

                        // Deduplicate: merge label text for markers that land on the same bar
                        const uniqueMarkers = [];
                        for (const m of markers) {
                            const last = uniqueMarkers[uniqueMarkers.length - 1];
                            if (last && last.time === m.time) {
                                last.text += ' | ' + m.text;
                            } else {
                                uniqueMarkers.push(Object.assign({}, m));
                            }
                        }

                        candleSeries.setMarkers(uniqueMarkers);
                    } else {
                        // Show a friendly message overlay when no trades fall in the chart window
                        const msg = document.createElement('div');
                        msg.style.cssText = 'position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);color:#8892aa;font-size:1rem;pointer-events:none;text-align:center;';
                        msg.innerHTML = 'No trades in the visible chart window.<br><small>Trades for this asset occurred outside the last 1,000 candles.</small>';
                        container.style.position = 'relative';
                        container.appendChild(msg);
                    }
                } catch (err) {
                    console.error("Trade History rendering error:", err);
                }
            }
            
            currentChart.timeScale().fitContent();
        }); // end requestAnimationFrame
    }
</script>
</body>
</html>"""
