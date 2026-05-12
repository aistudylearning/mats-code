# MATS Installation — Google Colab

> **Target**: Ephemeral compute environment for backtesting, data fetching, and parameter sweeps.
> Data lives natively on Google Drive — zero sync friction.

---

## 1. One-Time Google Drive Setup

Before your first Colab session, ensure the shared data folder exists on Drive.
If you've already uploaded from L1 (see `INSTALLME.26.04LTS.md` § 5a), skip this.

```
My Drive/
└── trading/
    ├── raw/              ← OHLCV parquet data (~4–5 GB)
    ├── reports/          ← HTML backtest reports
    ├── checkpoints/      ← Job checkpoints
    └── notebooks/        ← (optional) saved Colab notebooks
```

If the `trading/` folder doesn't exist yet, create it manually in Google Drive
or from any machine with rclone:
```bash
rclone mkdir gdrive:trading/raw
rclone mkdir gdrive:trading/reports
rclone mkdir gdrive:trading/checkpoints
```

---

## 2. Colab Session Setup (Run Every Session)

Copy-paste this into the **first cell** of any new Colab notebook:

```python
# ═══════════════════════════════════════════════════════════════════
# MATS Colab Setup — Run this cell first, every session
# ═══════════════════════════════════════════════════════════════════

# Step 1: Install dependencies (~30 seconds)
!pip install -q polars pyarrow duckdb pandas-ta ccxt joblib "pandas==2.2.2"

# Step 2: Mount Google Drive
from google.colab import drive
drive.mount('/content/drive')

# Step 3: Clone the repo (or pull latest if already cloned)
import os
if not os.path.exists('/content/mats-code'):
    !git clone https://github.com/aistudylearning/mats-code.git /content/mats-code
else:
    !cd /content/mats-code && git pull

# Step 4: Set data root to Google Drive
# NOTE: The path depends on how data.zip was created:
#   • If zipped from mats-code/ root → path includes data/hot/data
#   • If zipped from data/hot/data/ directly → path is just trading/raw
# Check with: !ls /content/drive/MyDrive/trading/raw
os.environ["MATS_DATA_ROOT"] = "/content/drive/MyDrive/trading/raw/data/hot/data"

# Step 5: Change to project directory
%cd /content/mats-code

print("✅ MATS ready. Data root:", os.environ["MATS_DATA_ROOT"])
!ls $MATS_DATA_ROOT | head -5  # Should list asset folders like BTC-USDT, ETH-USDT
```

Alternatively, use the pre-made notebook at:
📓 `notebooks/colab_setup.ipynb` (in the repo)

---

## 3. Running Tasks on Colab

After the setup cell, use subsequent cells for your work:

```python
# Fetch latest data (writes directly to Drive — no sync needed!)
!python3 main.py fetch

# Run single-asset backtest
!python3 main.py backtest

# Run portfolio backtest (all 50 assets)
!python3 main.py portfolio

# Run unit tests
!pytest tests/ -v
```

### Saving HTML Reports to Drive

Backtest reports are generated in the `output/` folder. Copy them to Drive:

```python
!cp -r output/*.html "/content/drive/MyDrive/trading/reports/"
print("📊 Reports saved to Drive — viewable from phone/browser")
```

---

## 4. Anti-Idle (Prevent Session Timeout)

Colab disconnects after ~30 min of inactivity. Paste this in your browser's
DevTools console (F12 → Console) to keep the session alive:

```javascript
function keepAlive() {
    document.querySelector("colab-connect-button").click();
    console.log("🔄 Keep-alive ping at", new Date().toLocaleTimeString());
}
setInterval(keepAlive, 60000);
```

> **Note**: Sessions still have a hard limit of ~12 hours. Plan accordingly.

---

## 5. Colab vs Local: Key Differences

| Aspect | Colab | Local (L1/L3) |
|---|---|---|
| Data access | Native Drive mount (fast) | Local disk (fastest) or rclone |
| Persistence | ❌ Everything lost on disconnect | ✅ Persistent filesystem |
| Startup time | ~60s (pip + mount + clone) | 0s (already set up) |
| Git workflow | `!git pull` only; commits are clunky | Full IDE + git integration |
| Max runtime | ~12 hours (hard limit) | Unlimited |
| Cost | Free (with limits) | Your electricity |

---

## 6. Lessons Learned & Notes

> _This section is a living journal. Add your observations as you use Colab._

### 2026-05-12 — Initial Setup & Lessons
- ✅ `pandas==2.2.2` must be pinned to avoid conflicts with Colab-native tools (gradio, bqplot)
- ✅ These are **warnings only** — MATS uses Polars, not pandas, so the conflicts are harmless
- ⚠️ **ZIP path gotcha**: When zipping from the project root (`mats-code/`), the zip preserves
  the full `data/hot/data/` subfolder path. After extracting to `trading/raw/`, the actual
  parquet files end up at `trading/raw/data/hot/data/{ASSET}/`. Set `MATS_DATA_ROOT` accordingly.
- 💡 To avoid this in future: zip from inside `data/hot/data/` so the asset folders are at the
  zip root, and extraction to `trading/raw/` gives the clean `trading/raw/{ASSET}/` structure.

<!--
Template for adding lessons:

### YYYY-MM-DD — Topic
- Observation or issue encountered
- Solution or workaround applied
- Pro/con discovered
-->

