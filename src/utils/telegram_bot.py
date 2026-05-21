import os
import requests
import zipfile
from src.utils.logger import get_logger

log = get_logger(__name__)

def send_report_to_telegram(file_path: str) -> None:
    """
    Sends the generated HTML report to Telegram.
    If the report exceeds 40MB, automatically compresses it to .zip format
    to stay well within Telegram's 50MB upload limits.
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

    file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
    actual_send_path = file_path
    temp_zip_created = False
    zip_path = file_path + ".zip"

    if file_size_mb > 40:
        log.info(f"📦 Report is large ({file_size_mb:.1f} MB). Compressing to .zip for Telegram upload...")
        try:
            with zipfile.ZipFile(zip_path, 'w', compression=zipfile.ZIP_DEFLATED) as zipf:
                zipf.write(file_path, arcname=os.path.basename(file_path))
            actual_send_path = zip_path
            temp_zip_created = True
            log.info(f"⚡ Compressed successfully. Zip file size: {os.path.getsize(zip_path) / (1024 * 1024):.2f} MB")
        except Exception as e:
            log.warning(f"⚠️ Failed to compress report: {e}. Attempting raw upload...")

    log.info(f"⏳ Sending {os.path.basename(actual_send_path)} to Telegram...")
    url = f"https://api.telegram.org/bot{bot_token}/sendDocument"

    try:
        with open(actual_send_path, 'rb') as doc:
            res = requests.post(url, data={'chat_id': chat_id}, files={'document': doc}, timeout=60)
        
        if res.status_code == 200:
            log.info("✅ Report successfully delivered to Telegram!")
        else:
            log.warning(f"❌ Failed to send to Telegram: HTTP {res.status_code} - {res.text}")
            
    except requests.exceptions.RequestException as e:
        log.error(f"❌ Network error sending to Telegram: {e}")
    finally:
        if temp_zip_created and os.path.exists(zip_path):
            try:
                os.remove(zip_path)
            except Exception as e:
                log.warning(f"Failed to delete temporary zip file: {e}")
