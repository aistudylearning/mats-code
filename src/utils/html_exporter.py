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
        from src.strategy.indicators import compute_rsi
        df = load_ohlcv(symbol, tf, root=data_root)
        if df.is_empty():
            return []
        
        # Calculate RSI before taking tail to ensure no warm-up bias
        df_indicators = compute_rsi(df)
        
        # Take the most recent max_candles
        df_tail = df_indicators.tail(max_candles)
        records = df_tail.select(["timestamp", "open", "high", "low", "close", "rsi"]).to_dicts()
        
        # Lightweight Charts expects time in seconds for Unix timestamps
        formatted = []
        for r in records:
            formatted.append({
                "time": r["timestamp"] / 1000,
                "open": r["open"],
                "high": r["high"],
                "low": r["low"],
                "close": r["close"],
                "rsi": r["rsi"] if r["rsi"] is not None else None
            })
        return formatted
    except Exception as e:
        log.warning(f"Failed to load detailed chart data for {symbol} {tf}: {e}")
        return []


def _build_assets_data(results: dict[str, BacktestResult], data_root: str, tf: str) -> list[dict]:
    """Build the asset data list for a single timeframe.
    Uses ultra-compact array structures to keep the monolithic HTML size well under 20MB,
    enabling direct viewing on mobile and desktop without exceeding Telegram bot upload limits.
    """
    mcap_rank = {sym: idx + 1 for idx, sym in enumerate(MVP_ASSETS)}
    assets_data = []
    for symbol, res in results.items():
        sparkline = generate_sparkline_data(symbol, data_root)
        
        # Format S/R Zones: [price, kind_index (0=support, 1=resistance), weight]
        sr_data = [
            [z.price, 0 if z.kind == "support" else 1, z.combined_weight]
            for z in res.sr_zones
        ]
        
        # Format Trade History: [entry_time, entry_price, exit_time, exit_price, pnl, exit_reason]
        trades_data = []
        for t in res.trades:
            trades_data.append([
                t.entry_timestamp_ms / 1000,
                t.entry_price,
                (t.exit_timestamp_ms / 1000) if t.exit_timestamp_ms else None,
                t.exit_price,
                t.pnl,
                t.exit_reason
            ])

        # Format Chart Data: [time, open, high, low, close, rsi]
        chart_points = []
        for r in load_chart_data(symbol, tf, data_root):
            chart_points.append([
                r["time"],
                r["open"],
                r["high"],
                r["low"],
                r["close"],
                r["rsi"]
            ])

        assets_data.append({
            "sym": symbol,
            "r": mcap_rank.get(symbol, 999),
            "ret": res.total_return_pct,
            "iret": res.isolated_return_pct,
            "wr": res.win_rate_pct,
            "dd": res.max_drawdown_pct,
            "tr": res.total_trades,
            "cap": res.final_capital,
            "spk": sparkline,
            "c": chart_points,
            "s": sr_data,
            "t": trades_data
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
    
    # Send to Telegram (fails gracefully if tokens are not set in environment)
    from src.utils.telegram_bot import send_report_to_telegram
    send_report_to_telegram(out_path)


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

        /* ── Portfolio Summary Cards ── */
        .portfolio-summary {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 20px;
            margin-bottom: 28px;
        }
        .stat-card {
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 20px;
            backdrop-filter: blur(8px);
            box-shadow: 0 4px 20px rgba(0,0,0,0.15);
            display: flex;
            flex-direction: column;
            gap: 6px;
        }
        .stat-label {
            font-size: 0.75rem;
            color: var(--muted);
            text-transform: uppercase;
            letter-spacing: 0.6px;
            font-weight: 600;
        }
        .stat-value {
            font-size: 1.6rem;
            font-weight: 700;
        }

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

    <div class="portfolio-summary" id="portfolioSummary"></div>

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
    
    // Inflate compressed payload to standard objects transparently
    for (const tf in multiTfData) {
        multiTfData[tf] = multiTfData[tf].map(asset => {
            const chartData = asset.c.map(c => ({
                time: c[0],
                open: c[1],
                high: c[2],
                low: c[3],
                close: c[4],
                rsi: c[5]
            }));
            
            const tradesHistory = asset.t.map(t => ({
                entry_time: t[0],
                entry_price: t[1],
                exit_time: t[2],
                exit_price: t[3],
                pnl: t[4],
                exit_reason: t[5]
            }));
            
            const srZones = asset.s.map(s => ({
                price: s[0],
                kind: s[1] === 0 ? 'support' : 'resistance',
                weight: s[2]
            }));

            return {
                symbol: asset.sym,
                mcap_rank: asset.r,
                total_return: asset.ret,
                isolated_return: asset.iret,
                win_rate: asset.wr,
                max_dd: asset.dd,
                trades: asset.tr,
                final_capital: asset.cap,
                sparkline: asset.spk,
                chart_data: chartData,
                trades_history: tradesHistory,
                sr_zones: srZones,
                tradingview_url: `https://www.tradingview.com/chart/?symbol=BINANCE:${asset.sym.replace('/', '')}`
            };
        });
    }

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
            updatePortfolioSummary();
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

    // ── Portfolio Summary Card Logic ──
    function updatePortfolioSummary() {
        const data = multiTfData[activeTf] || [];
        let totalReturn = 0;
        let totalTrades = 0;

        data.forEach(asset => {
            totalReturn += asset.total_return;
            totalTrades += asset.trades;
        });

        const initialCapital = 10000.0;
        const totalPnl = (totalReturn / 100) * initialCapital;
        const finalCapital = initialCapital + totalPnl;

        const summaryEl = document.getElementById('portfolioSummary');
        const retCls = totalReturn >= 0 ? 'pos' : 'neg';
        const sign = totalReturn > 0 ? '+' : '';

        summaryEl.innerHTML = `
            <div class="stat-card">
                <span class="stat-label">Total Portfolio Return</span>
                <span class="stat-value ${retCls}">${sign}${totalReturn.toFixed(2)}%</span>
            </div>
            <div class="stat-card">
                <span class="stat-label">Total Portfolio PnL</span>
                <span class="stat-value ${retCls}">${sign}${totalPnl.toFixed(2)} USD</span>
            </div>
            <div class="stat-card">
                <span class="stat-label">Ending Portfolio Capital</span>
                <span class="stat-value">${finalCapital.toFixed(2)} USD</span>
            </div>
            <div class="stat-card">
                <span class="stat-label">Total Portfolio Trades</span>
                <span class="stat-value">${totalTrades}</span>
            </div>
        `;
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
    updatePortfolioSummary();

    // ── Chart Modals ──────────────────────────────────────────────────────
    let currentChart = null;
    let currentRsiChart = null;
    let currentResizeObserver = null;

    function closeChartModal() {
        document.getElementById('chartModal').classList.remove('active');
        if (currentResizeObserver) {
            currentResizeObserver.disconnect();
            currentResizeObserver = null;
        }
        if (currentChart) {
            currentChart.remove();
            currentChart = null;
        }
        if (currentRsiChart) {
            currentRsiChart.remove();
            currentRsiChart = null;
        }
    }

    function showChartModal(symbol, type) {
        const asset = multiTfData[activeTf].find(a => a.symbol === symbol);
        if (!asset || !asset.chart_data.length) return;

        document.getElementById('modalTitle').textContent = `${symbol} - ${activeTf.toUpperCase()} - ${type === 'price' ? 'Price & S/R Levels' : 'Trade History'}`;
        document.getElementById('chartModal').classList.add('active');

        const container = document.getElementById('chartContainer');
        container.innerHTML = '';
        container.style.display = 'flex';
        container.style.flexDirection = 'column';
        container.style.gap = '8px';

        // Create separate sub-divs for synchronized Price and RSI panes
        const priceDiv = document.createElement('div');
        priceDiv.style.width = '100%';
        priceDiv.style.height = '70%';
        container.appendChild(priceDiv);

        const rsiDiv = document.createElement('div');
        rsiDiv.style.width = '100%';
        rsiDiv.style.height = '30%';
        container.appendChild(rsiDiv);

        // CRITICAL FIX: Defer chart creation until AFTER the browser has painted
        // the modal. Without this, the container has 0x0 dimensions and the chart
        // renders as an invisible black box.
        requestAnimationFrame(() => {
            const w = container.clientWidth || 900;
            const h = container.clientHeight || 560;

            // 1. Create Candlestick Chart (Top Pane)
            currentChart = LightweightCharts.createChart(priceDiv, {
                width: w,
                height: Math.floor(h * 0.70) - 4,
                layout: { background: { color: '#0f111a' }, textColor: '#8892aa' },
                grid: { vertLines: { color: 'rgba(255,255,255,0.05)' }, horzLines: { color: 'rgba(255,255,255,0.05)' } },
                crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
                timeScale: { timeVisible: true, secondsVisible: false }
            });

            const candleSeries = currentChart.addCandlestickSeries({
                upColor: '#10b981', downColor: '#ef4444', borderVisible: false, wickUpColor: '#10b981', wickDownColor: '#ef4444'
            });
            
            candleSeries.setData(asset.chart_data);

            // 2. Create RSI Chart (Bottom Pane)
            currentRsiChart = LightweightCharts.createChart(rsiDiv, {
                width: w,
                height: Math.floor(h * 0.30) - 4,
                layout: { background: { color: '#0f111a' }, textColor: '#8892aa' },
                grid: { vertLines: { color: 'rgba(255,255,255,0.03)' }, horzLines: { color: 'rgba(255,255,255,0.03)' } },
                crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
                timeScale: { timeVisible: true, secondsVisible: false },
                leftPriceScale: { visible: false },
                rightPriceScale: {
                    visible: true,
                    borderVisible: false,
                    scaleMargins: { top: 0.1, bottom: 0.1 }
                }
            });

            const rsiSeries = currentRsiChart.addLineSeries({
                color: '#818cf8',
                lineWidth: 1.5,
                crosshairMarkerVisible: true,
                priceLineVisible: false,
                lastValueVisible: true
            });

            const rsiData = asset.chart_data
                .filter(d => d.rsi !== null && d.rsi !== undefined)
                .map(d => ({ time: d.time, value: d.rsi }));
            rsiSeries.setData(rsiData);

            // Add RSI levels lines (30, 50, 70)
            rsiSeries.createPriceLine({
                price: 70,
                color: 'rgba(239, 68, 68, 0.4)',
                lineWidth: 1,
                lineStyle: LightweightCharts.LineStyle.Dashed,
                axisLabelVisible: true,
                title: '70'
            });

            rsiSeries.createPriceLine({
                price: 50,
                color: 'rgba(255, 255, 255, 0.15)',
                lineWidth: 1,
                lineStyle: LightweightCharts.LineStyle.Dashed,
                axisLabelVisible: true
            });

            rsiSeries.createPriceLine({
                price: 30,
                color: 'rgba(16, 185, 129, 0.4)',
                lineWidth: 1,
                lineStyle: LightweightCharts.LineStyle.Dashed,
                axisLabelVisible: true,
                title: '30'
            });

            // 3. Synchronize Zooming/Scrolling (with re-entrancy guard)
            let syncingRange = false;
            currentChart.timeScale().subscribeVisibleLogicalRangeChange(range => {
                if (syncingRange) return;
                syncingRange = true;
                currentRsiChart.timeScale().setVisibleLogicalRange(range);
                syncingRange = false;
            });
            currentRsiChart.timeScale().subscribeVisibleLogicalRangeChange(range => {
                if (syncingRange) return;
                syncingRange = true;
                currentChart.timeScale().setVisibleLogicalRange(range);
                syncingRange = false;
            });

            // 4. Synchronize Crosshair (with re-entrancy guard)
            // Note: setCrosshairPosition(price, time, series) requires a
            // price value, NOT pixel coords. We look up each series' value
            // for the hovered time to position the crosshair correctly.
            let syncingCrosshair = false;
            currentChart.subscribeCrosshairMove(param => {
                if (syncingCrosshair) return;
                syncingCrosshair = true;
                if (param.time) {
                    const rsiPoint = param.seriesData?.get(candleSeries);
                    const rsiVal = rsiData.find(d => d.time === param.time);
                    if (rsiVal) currentRsiChart.setCrosshairPosition(rsiVal.value, param.time, rsiSeries);
                } else {
                    currentRsiChart.clearCrosshairPosition();
                }
                syncingCrosshair = false;
            });
            currentRsiChart.subscribeCrosshairMove(param => {
                if (syncingCrosshair) return;
                syncingCrosshair = true;
                if (param.time) {
                    const bar = asset.chart_data.find(d => d.time === param.time);
                    if (bar) currentChart.setCrosshairPosition(bar.close, param.time, candleSeries);
                } else {
                    currentChart.clearCrosshairPosition();
                }
                syncingCrosshair = false;
            });

            // 5. Resize both charts when the container changes size
            currentResizeObserver = new ResizeObserver(() => {
                const cw = container.clientWidth;
                const ch = container.clientHeight;
                if (currentChart) currentChart.resize(cw, Math.floor(ch * 0.70) - 4);
                if (currentRsiChart) currentRsiChart.resize(cw, Math.floor(ch * 0.30) - 4);
            });
            currentResizeObserver.observe(container);

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
                        priceDiv.style.position = 'relative';
                        priceDiv.appendChild(msg);
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
