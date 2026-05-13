# MATS Installation — Ubuntu 26.04 LTS (WSL)

> **Target**: Laptop 1 (L1) — development/research node running Ubuntu 26.04 LTS inside WSL2

---

## 1. WSL Environment Setup

If WSL is already installed with Ubuntu 26.04, skip this step.

```powershell
# (From PowerShell as Admin on Windows)
wsl --install -d Ubuntu
# After reboot, open the Ubuntu terminal and continue below
```

## 2. System Packages

```bash
# Update system packages
sudo apt update && sudo apt upgrade -y

# Install Python 3 and core utilities
# Ubuntu 26.04 ships with Python 3.13+ — fully compatible
sudo apt install -y python3 python3-pip python3-venv python3-dev \
                    git curl wget rsync sqlite3 jq htop tmux unzip zip

# SSH server is typically not needed in WSL (use Windows networking)
# but install if you plan to accept connections from L2/L3:
# sudo apt install -y openssh-server
```

## 3. Clone & Virtual Environment

```bash
# Create project directory
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

If `pip install -e ".[dev]"` fails, use the fallback:
```bash
pip install polars pyarrow duckdb pandas-ta ccxt joblib pytest
```

## 4. Install rclone (Google Drive Data Sync)

The heavy OHLCV data (~4–5 GB) lives on Google Drive and is shared between
Laptop 1 (L1/WSL), Laptop 2 (L2), Laptop 3 (L3), and Google Colab.

```bash
# Install rclone inside WSL
curl https://rclone.org/install.sh | sudo bash

# Configure Google Drive remote
rclone config
```

During `rclone config`:
1. Choose **n** (new remote)
2. Name it: `gdrive`
3. Storage type: **Google Drive** (type `drive`)
4. Follow the OAuth authentication flow
   - **WSL tip**: If the browser doesn't open automatically, copy the URL
     printed in the terminal and paste it into your Windows browser
5. Root folder: select `trading/` as your base folder, or leave at root

Verify:
```bash
rclone lsd gdrive:trading/
# Should list: raw/  results/  checkpoints/  reports/
```

## 5. Directory Structure & Data Upload

```bash
cd ~/projects/mats-code

# Create local directory skeleton
mkdir -p data/hot/data
mkdir -p data/staging/results
mkdir -p data/staging/checkpoints
```

### 5a. First-Time Upload (push data TO Google Drive)

If this is the machine where you originally ran `python3 main.py fetch`, your
data already lives at `data/hot/data/`. You need to upload it once so that
Laptop 3, Laptop 2, and Colab can all pull from it.

```bash
# ═══════════════════════════════════════════════════════════════════
# ONE-TIME UPLOAD: Push your local ~4–5 GB OHLCV data to Google Drive
# Creates the gdrive:trading/raw/ folder structure automatically
# ═══════════════════════════════════════════════════════════════════

# Step 1: Create the remote folder structure
rclone mkdir gdrive:trading/raw
rclone mkdir gdrive:trading/reports
rclone mkdir gdrive:trading/checkpoints

# Step 2: Upload the entire data folder (~4–5 GB, takes 10–30 min)
rclone sync data/hot/data/ gdrive:trading/raw/ \
    --progress \
    --transfers 8 \
    --checkers 4 \
    --log-file /tmp/rclone-upload.log

# Step 3: Verify upload completed correctly
rclone check data/hot/data/ gdrive:trading/raw/ --one-way
# Should print: 0 differences found
```

> **What does `rclone sync` do here?**  
> It mirrors your local `data/hot/data/` folder into `gdrive:trading/raw/`.  
> The folder structure `{ASSET}/{TF}/YYYY-MM.parquet` is preserved exactly.

### 5b. Pull Data (when re-cloning or refreshing)

If you've already uploaded, or another machine uploaded the data, pull it down:

```bash
rclone sync gdrive:trading/raw/ data/hot/data/ \
    --progress \
    --transfers 8 \
    --checkers 4 \
    --log-file /tmp/rclone-pull.log
```

### Pushing results back to Drive

After running backtests, push the HTML reports to Drive so you can view them
on your phone or other laptops:

```bash
rclone copy output/ gdrive:trading/reports/ --progress
```

## 6. WSL-Specific Notes

### Accessing data from Windows

The WSL filesystem is accessible from Windows at:
```
\\wsl.localhost\Ubuntu\home\<user>\learning\projects\mats-code
```

### Google Drive Desktop already mounted?

If you have Google Drive for Desktop installed on Windows (e.g., `G:\My Drive`),
you can access it from WSL at `/mnt/g/My Drive/`. However, **rclone is still
recommended** for the MATS data sync because:
- Drive Desktop's virtual filesystem has high I/O latency for parquet workloads
- rclone creates real local copies, giving you native disk speed

### Performance tip

To get maximum backtest speed on WSL, ensure your data is stored on the
**Linux filesystem** (e.g., `~/projects/`) — NOT on `/mnt/c/` which
passes through the Windows filesystem layer and is 3–5× slower.

## 7. Verify Installation

```bash
source .venv/bin/activate

# Run the full test suite
pytest tests/ -v

# Quick smoke test — single-asset backtest
python3 main.py backtest --signal 0.1
```

If all tests pass and the backtest runs ✅, your L1 development node is ready.

---

## Quick Reference: rclone Sync Commands

| Direction | Command |
|---|---|
| **⬆ Upload data** (L1 → Drive, first time) | `rclone sync data/hot/data/ gdrive:trading/raw/ --progress --transfers 8` |
| **⬇ Pull data** (Drive → L1) | `rclone sync gdrive:trading/raw/ data/hot/data/ --progress` |
| **Push reports** (L1 → Drive) | `rclone copy output/ gdrive:trading/reports/ --progress` |
| **Push checkpoints** (L1 → Drive) | `rclone copy data/staging/checkpoints/ gdrive:trading/checkpoints/ --progress` |
| **Verify sync** | `rclone check data/hot/data/ gdrive:trading/raw/ --one-way` |

