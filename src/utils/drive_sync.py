"""
Post-fetch sync utilities: zip the local data folder and upload to Google Drive.

Called automatically after `main.py fetch` completes on any machine that has
rclone configured (L1, L3). Colab consumes the zip — it never creates it.

Workflow:
  1. Delete stale data.zip from Drive  (so consumers know data changed)
  2. Zip the local data folder         (fast: local I/O, seconds not minutes)
  3. Upload zip to Drive via rclone    (one big file, no API rate limit)
"""

import os
import subprocess
import time

from src.utils.logger import get_logger

log = get_logger(__name__)

# Rclone remote path for the zip on Google Drive
_GDRIVE_ZIP = "gdrive:trading/raw/data.zip"


def _rclone_available() -> bool:
    """Return True if rclone is installed and configured."""
    try:
        result = subprocess.run(
            ["rclone", "version"], capture_output=True, text=True, timeout=10
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _delete_stale_zip() -> None:
    """Delete the existing data.zip from Google Drive (ignore if not present)."""
    log.info(f"🗑️  Deleting stale zip from Drive: {_GDRIVE_ZIP}")
    result = subprocess.run(
        ["rclone", "deletefile", _GDRIVE_ZIP],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        log.info("✅ Stale zip deleted.")
    else:
        # "object not found" is fine — it just didn't exist yet
        if "object not found" in result.stderr.lower() or "not found" in result.stderr.lower():
            log.info("ℹ️  No existing zip on Drive — nothing to delete.")
        else:
            log.warning(f"rclone deletefile warning: {result.stderr.strip()}")


import subprocess

def _create_local_zip(local_data_root: str) -> str:
    """
    Zip the local data folder using the OS zip command.
    Returns path to the created zip file.
    """
    parent = os.path.dirname(local_data_root.rstrip("/"))
    zip_path = os.path.join(parent, "data.zip")

    log.info(f"⏳ Zipping {local_data_root} → {zip_path} ...")
    t0 = time.time()

    # Use OS zip. 'cwd' ensures paths inside the zip are relative to local_data_root,
    # NOT absolute paths like /home/learning/...
    result = subprocess.run(
        ["zip", "-qr", zip_path, "."],
        cwd=local_data_root,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"zip command failed (is 'zip' installed?). Stderr:\n{result.stderr}")

    elapsed = time.time() - t0
    size_mb = os.path.getsize(zip_path) / 1024 / 1024
    log.info(f"✅ Zipped in {elapsed:.1f}s — {size_mb:.0f} MB → {zip_path}")
    return zip_path


def _upload_zip(local_zip_path: str) -> None:
    """Upload the local zip to Google Drive using rclone."""
    log.info(f"⏳ Uploading {local_zip_path} → {_GDRIVE_ZIP} ...")
    t0 = time.time()

    result = subprocess.run(
        ["rclone", "copyto", local_zip_path, _GDRIVE_ZIP, "--progress"],
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError("rclone upload failed.")

    elapsed = time.time() - t0
    log.info(f"✅ Uploaded in {elapsed/60:.1f} min → {_GDRIVE_ZIP}")


def run_post_fetch_sync(local_data_root: str) -> None:
    """
    Full post-fetch pipeline:
      1. Check rclone is available (skip silently on Colab / unconfigured machines)
      2. Delete stale zip from Drive
      3. Zip local data folder
      4. Upload zip to Drive
      5. Clean up local zip

    Args:
        local_data_root: Path to the local data folder (e.g. data/hot/data)
    """
    if not _rclone_available():
        log.info("ℹ️  rclone not configured — skipping Drive zip sync (Colab or unconfigured node).")
        return

    if not os.path.isdir(local_data_root):
        log.warning(f"Data root not found: {local_data_root} — skipping zip sync.")
        return

    log.info("=" * 55)
    log.info("📦 Post-fetch Drive zip sync starting...")
    log.info("=" * 55)

    try:
        _delete_stale_zip()
        local_zip = _create_local_zip(local_data_root)
        _upload_zip(local_zip)
    finally:
        # Always clean up the local zip to save disk space
        local_zip_path = os.path.join(
            os.path.dirname(local_data_root.rstrip("/")), "data.zip"
        )
        if os.path.exists(local_zip_path):
            os.remove(local_zip_path)
            log.info(f"🗑️  Local zip cleaned up: {local_zip_path}")

    log.info("✅ Drive zip sync complete. Consumers (Colab/L3) can now use fast ZIP bootstrap.")
