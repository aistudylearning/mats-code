# MATS Installation — Ubuntu 24.04.4 LTS (Noble Numbat)

> **Target**: Laptop 3 — dedicated Worker node (bare-metal Ubuntu 24.04.4 LTS)

---

## 1. System Packages

```bash
# Update system packages
sudo apt update && sudo apt upgrade -y

# Install Python 3 and core utilities
# Ubuntu 24.04 ships with Python 3.12 — fully compatible
sudo apt install -y python3 python3-pip python3-venv python3-dev \
                    git curl wget rsync sqlite3 jq htop tmux unzip openssh-server

# Ensure SSH is running (needed for L2 → L3 job dispatch)
sudo systemctl enable ssh && sudo systemctl start ssh
```

## 2. User Setup (Optional: `trader` User)

If you prefer a dedicated non-root user per the system design spec:

```bash
sudo useradd -m -s /bin/bash trader
sudo usermod -aG sudo trader
echo 'trader ALL=(ALL) NOPASSWD:ALL' | sudo tee /etc/sudoers.d/trader
su - trader
```

Otherwise, proceed with your existing user.

## 3. Clone & Virtual Environment

```bash
# Clone the repository
mkdir -p ~/projects
cd ~/projects
git clone https://github.com/aistudylearning/mats-code.git mats-code
cd mats-code

# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install all dependencies (including dev tools like pytest)
pip install --upgrade pip
pip install -e ".[dev]"
```

If `pip install -e ".[dev]"` fails (rare on 24.04), use the fallback:
```bash
pip install polars pyarrow duckdb pandas-ta ccxt joblib pytest
```

## 4. Install rclone (Google Drive Data Sync)

The heavy OHLCV data (~4–5 GB) lives on Google Drive and is shared between
Laptop 1 (L1/WSL), Laptop 2 (L2), Laptop 3 (L3), and Google Colab.

```bash
# Install rclone
curl https://rclone.org/install.sh | sudo bash

# Configure Google Drive remote
# This launches an interactive wizard — follow the prompts
rclone config
```

During `rclone config`:
1. Choose **n** (new remote)
2. Name it: `gdrive`
3. Storage type: **Google Drive** (type `drive`)
4. Follow the OAuth browser-based authentication flow
5. Root folder: select `trading/` as your base folder, or leave at root

Verify:
```bash
rclone lsd gdrive:trading/
# Should list: raw/  results/  checkpoints/  reports/
```

## 5. Directory Structure & Data Sync

```bash
cd ~/projects/mats-code

# Create local directory skeleton
mkdir -p data/hot/data
mkdir -p data/staging/results
mkdir -p data/staging/checkpoints

# ═══════════════════════════════════════════════════════════════════
# Pull the shared OHLCV dataset from Google Drive (~4–5 GB)
#
# PREREQUISITE: The data must have been uploaded from L1 first.
# See INSTALLME.26.04LTS.md § 5a for the initial upload procedure.
# ═══════════════════════════════════════════════════════════════════
rclone sync gdrive:trading/raw/ data/hot/data/ \
    --progress \
    --transfers 8 \
    --checkers 4 \
    --log-file /tmp/rclone-pull.log
```

> **Note**: After running backtests, push reports back to Drive:
> ```bash
> rclone copy output/ gdrive:trading/reports/ --progress
> ```

## 6. Verify Installation

```bash
source .venv/bin/activate

# Run the full test suite
pytest tests/ -v

# Quick smoke test — single-asset backtest
python3 main.py backtest --signal 0.1
```

If all tests pass and the backtest runs ✅, your L3 worker is ready.

---

## Quick Reference: rclone Sync Commands

| Direction | Command |
|---|---|
| **⬇ Pull data** (Drive → L3) | `rclone sync gdrive:trading/raw/ data/hot/data/ --progress` |
| **⬆ Upload data** (L3 → Drive, after local fetch) | `rclone sync data/hot/data/ gdrive:trading/raw/ --progress --transfers 8` |
| **Push reports** (L3 → Drive) | `rclone copy output/ gdrive:trading/reports/ --progress` |
| **Push checkpoints** (L3 → Drive) | `rclone copy data/staging/checkpoints/ gdrive:trading/checkpoints/ --progress` |
| **Verify sync** | `rclone check data/hot/data/ gdrive:trading/raw/ --one-way` |
