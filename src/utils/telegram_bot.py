import os
import requests
from src.utils.logger import get_logger

log = get_logger(__name__)

def send_report_to_telegram(file_path: str) -> None:
    """
    Sends the generated HTML report to Telegram.
    Fails silently (with a log warning) if credentials are not configured.
    """
    bot_token = os.environ.get("MATS_TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("MATS_TELEGRAM_CHAT_ID")

    if not bot_token or not chat_id:
        log.info("ℹ️  Telegram credentials not found. Skipping Telegram notification.")
        log.info("   (Set MATS_TELEGRAM_BOT_TOKEN and MATS_TELEGRAM_CHAT_ID to enable)")
        return

    if not os.path.exists(file_path):
        log.error(f"❌ Telegram: File not found to send: {file_path}")
        return

    log.info(f"⏳ Sending {os.path.basename(file_path)} to Telegram...")
    url = f"https://api.telegram.org/bot{bot_token}/sendDocument"

    try:
        with open(file_path, 'rb') as doc:
            res = requests.post(url, data={'chat_id': chat_id}, files={'document': doc}, timeout=30)
        
        if res.status_code == 200:
            log.info("✅ Report successfully delivered to Telegram!")
        else:
            log.warning(f"❌ Failed to send to Telegram: HTTP {res.status_code} - {res.text}")
            
    except requests.exceptions.RequestException as e:
        log.error(f"❌ Network error sending to Telegram: {e}")
