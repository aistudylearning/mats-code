import os
from datetime import datetime, timezone
import json
import polars as pl

from src.backtest.engine import BacktestResult
from src.config.settings import MVP_ASSETS
from src.data.storage import load_ohlcv
from src.utils.logger import get_logger

log = get_logger(__name__)

def generate_sparkline_data(symbol: str, data_root: str, max_points: int = 100) -> list[float]:
    """Load weekly data to generate a small price array for the sparkline."""
    try:
        # Try to load weekly data first to keep it small
        df = load_ohlcv(symbol, "1w", root=data_root)
        if df.is_empty():
            df = load_ohlcv(symbol, "1d", root=data_root)
            
        if df.is_empty():
            return []
            
        prices = df["close"].to_list()
        
        # Downsample if too large
        if len(prices) > max_points:
            step = len(prices) / max_points
            downsampled = [prices[int(i * step)] for i in range(max_points)]
            # Ensure the last price is included
            downsampled[-1] = prices[-1]
            return downsampled
        return prices
    except Exception as e:
        log.warning(f"Failed to generate sparkline for {symbol}: {e}")
        return []

def export_results_to_html(results: dict[str, BacktestResult], data_root: str, out_dir: str = "output") -> None:
    """Generate an interactive HTML report from backtest results."""
    os.makedirs(out_dir, exist_ok=True)
    
    timestamp_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_path = os.path.join(out_dir, f"portfolio_report_{timestamp_str}.html")
    
    # Pre-compute data for HTML
    assets_data = []
    
    # Map index to Market Cap Rank (since MVP_ASSETS is ordered by MCAP)
    mcap_rank = {sym: idx + 1 for idx, sym in enumerate(MVP_ASSETS)}
    
    for symbol, res in results.items():
        sparkline = generate_sparkline_data(symbol, data_root)
        
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
            "tradingview_url": f"https://www.tradingview.com/chart/?symbol=BINANCE:{symbol.replace('/', '')}"
        })

    # Read the template and inject data
    html_content = _get_html_template().replace("{{ASSETS_DATA_JSON}}", json.dumps(assets_data))
    
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html_content)
        
    log.info(f"Exported interactive HTML report to: {out_path}")

def _get_html_template() -> str:
    return """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>MATS Strategy - Portfolio Report</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-color: #0f111a;
            --surface-color: rgba(25, 28, 41, 0.7);
            --border-color: rgba(255, 255, 255, 0.08);
            --text-primary: #f8f9fa;
            --text-secondary: #a0aabf;
            --accent-primary: #6366f1;
            --accent-glow: rgba(99, 102, 241, 0.4);
            --positive: #10b981;
            --negative: #ef4444;
            --positive-bg: rgba(16, 185, 129, 0.1);
            --negative-bg: rgba(239, 68, 68, 0.1);
        }

        body {
            font-family: 'Inter', sans-serif;
            background-color: var(--bg-color);
            color: var(--text-primary);
            margin: 0;
            padding: 40px 20px;
            background-image: 
                radial-gradient(circle at 15% 50%, rgba(99, 102, 241, 0.08), transparent 25%),
                radial-gradient(circle at 85% 30%, rgba(16, 185, 129, 0.05), transparent 25%);
            background-attachment: fixed;
        }

        .container {
            max-width: 1400px;
            margin: 0 auto;
        }

        header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 40px;
            padding-bottom: 20px;
            border-bottom: 1px solid var(--border-color);
        }

        h1 {
            font-size: 2.2rem;
            font-weight: 600;
            margin: 0;
            background: linear-gradient(135deg, #fff, #a0aabf);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }

        .table-container {
            background: var(--surface-color);
            border: 1px solid var(--border-color);
            border-radius: 16px;
            backdrop-filter: blur(12px);
            overflow-x: auto;
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.2);
        }

        table {
            width: 100%;
            border-collapse: collapse;
            white-space: nowrap;
        }

        th, td {
            padding: 16px 24px;
            text-align: right;
            border-bottom: 1px solid var(--border-color);
        }

        th:nth-child(1), td:nth-child(1),
        th:nth-child(2), td:nth-child(2) {
            text-align: left;
        }

        th {
            color: var(--text-secondary);
            font-weight: 500;
            font-size: 0.85rem;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            cursor: pointer;
            user-select: none;
            transition: color 0.2s, background 0.2s;
        }

        th:hover {
            color: var(--text-primary);
            background: rgba(255, 255, 255, 0.03);
        }

        tr:last-child td {
            border-bottom: none;
        }

        tr:hover td {
            background: rgba(255, 255, 255, 0.02);
        }

        .symbol {
            font-size: 1.1rem;
            font-weight: 600;
            text-decoration: none;
            color: var(--text-primary);
            transition: color 0.2s;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        
        .symbol:hover {
            color: var(--accent-primary);
        }

        .tv-icon {
            font-size: 0.8rem;
            background: rgba(41, 98, 255, 0.1);
            color: #2962ff;
            padding: 2px 6px;
            border-radius: 4px;
            font-weight: 600;
        }

        .symbol:hover .tv-icon {
            background: #2962ff;
            color: white;
        }

        .value {
            font-size: 1rem;
            font-weight: 500;
        }

        .positive { color: var(--positive); }
        .negative { color: var(--negative); }

        .sparkline-cell {
            width: 200px;
            padding: 8px 24px !important;
            vertical-align: middle;
        }

        .sparkline-container {
            height: 40px;
            width: 150px;
            position: relative;
        }

        .sparkline {
            width: 100%;
            height: 100%;
            overflow: visible;
        }
        
        .sparkline-path {
            fill: none;
            stroke-width: 1.5;
            stroke-linecap: round;
            stroke-linejoin: round;
        }
        
        .sparkline-fill {
            stroke: none;
        }

        .sort-icon {
            display: inline-block;
            width: 0;
            height: 0;
            border-left: 4px solid transparent;
            border-right: 4px solid transparent;
            margin-left: 6px;
            vertical-align: middle;
            opacity: 0.3;
        }

        th.sort-asc .sort-icon {
            border-bottom: 4px solid var(--text-primary);
            opacity: 1;
        }

        th.sort-desc .sort-icon {
            border-top: 4px solid var(--text-primary);
            opacity: 1;
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>Portfolio Backtest Results</h1>
        </header>

        <div class="table-container">
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
                        <th>Price History (Fetched)</th>
                    </tr>
                </thead>
                <tbody id="tableBody"></tbody>
            </table>
        </div>
    </div>

    <script>
        const assetsData = {{ASSETS_DATA_JSON}};
        let currentSort = { column: 'mcap_rank', asc: true };

        const tbody = document.getElementById('tableBody');
        const headers = document.querySelectorAll('th[data-sort]');

        function formatPct(val) {
            const prefix = val > 0 ? '+' : '';
            return `<span class="value ${val >= 0 ? 'positive' : 'negative'}">${prefix}${val.toFixed(2)}%</span>`;
        }

        function createSparkline(data, isPositive) {
            if (!data || data.length < 2) return '';
            
            const min = Math.min(...data);
            const max = Math.max(...data);
            const range = max - min || 1;
            
            const width = 150;
            const height = 40;
            
            const points = data.map((val, i) => {
                const x = (i / (data.length - 1)) * width;
                const y = height - ((val - min) / range) * height;
                return `${x},${y}`;
            }).join(' ');

            const color = isPositive ? '#10b981' : '#ef4444';
            const gradientId = `grad-${Math.random().toString(36).substr(2, 9)}`;

            return `
                <svg class="sparkline" viewBox="0 -5 150 50" preserveAspectRatio="none">
                    <defs>
                        <linearGradient id="${gradientId}" x1="0" x2="0" y1="0" y2="1">
                            <stop offset="0%" stop-color="${color}" stop-opacity="0.2"/>
                            <stop offset="100%" stop-color="${color}" stop-opacity="0"/>
                        </linearGradient>
                    </defs>
                    <polygon class="sparkline-fill" points="0,40 ${points} 150,40" fill="url(#${gradientId})"/>
                    <polyline class="sparkline-path" points="${points}" stroke="${color}"/>
                </svg>
            `;
        }

        function renderTable(data) {
            tbody.innerHTML = data.map(asset => `
                <tr>
                    <td class="value">${asset.mcap_rank}</td>
                    <td>
                        <a href="${asset.tradingview_url}" target="_blank" class="symbol">
                            ${asset.symbol.split('/')[0]}
                            <span class="tv-icon">TV</span>
                        </a>
                    </td>
                    <td>${formatPct(asset.total_return)}</td>
                    <td>${formatPct(asset.isolated_return)}</td>
                    <td class="value">${asset.win_rate.toFixed(1)}%</td>
                    <td class="value">${asset.max_dd.toFixed(2)}%</td>
                    <td class="value">${asset.trades}</td>
                    <td class="sparkline-cell">
                        <div class="sparkline-container">
                            ${createSparkline(asset.sparkline, asset.total_return >= 0)}
                        </div>
                    </td>
                </tr>
            `).join('');
        }

        function sortData(column) {
            if (currentSort.column === column) {
                currentSort.asc = !currentSort.asc;
            } else {
                currentSort.column = column;
                currentSort.asc = true;
            }

            headers.forEach(th => th.classList.remove('sort-asc', 'sort-desc'));
            const activeHeader = document.querySelector(`th[data-sort="${column}"]`);
            activeHeader.classList.add(currentSort.asc ? 'sort-asc' : 'sort-desc');

            assetsData.sort((a, b) => {
                let valA = a[column];
                let valB = b[column];
                
                if (typeof valA === 'string') {
                    valA = valA.toLowerCase();
                    valB = valB.toLowerCase();
                }

                if (valA < valB) return currentSort.asc ? -1 : 1;
                if (valA > valB) return currentSort.asc ? 1 : -1;
                return 0;
            });

            renderTable(assetsData);
        }

        headers.forEach(th => {
            th.addEventListener('click', () => sortData(th.dataset.sort));
        });

        // Initial render
        sortData('mcap_rank');
    </script>
</body>
</html>"""
