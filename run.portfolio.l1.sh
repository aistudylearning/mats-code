#!/bin/bash
# ---------------------------------------------------------
# MATS Local Portfolio Runner
# ---------------------------------------------------------

cd ~/projects/mats-code

# 1. Export your Telegram credentials securely into the environment
export MATS_TELEGRAM_BOT_TOKEN="8604062820:AAHvBxNVETmXQl3pr7PHcRFJf6atzpJ3vi8"
export MATS_TELEGRAM_CHAT_ID="1408951620"

# 2. Run the full portfolio backtest across all timeframes and generate the HTML report!
python3 main.py portfolio \
    --signal 0.2 \
    --timeframe 1m 5m 15m 30m 1h 2h 4h 1d 1w 1M \
    --html \
    --machine L1 \
    2>&1 | tee output/log_portfolio_$(date +%Y%m%d_%H%M).txt