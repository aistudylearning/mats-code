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
    ├── reports/          ← HTML backtest reports (auto-saved here)
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

## 2. Running a Colab Session

### Option A: Ready-to-Run Notebook (Recommended)

Open [`notebooks/colab_backtest.ipynb`](https://github.com/aistudylearning/mats-code/blob/main/notebooks/colab_backtest.ipynb)
in Colab, hit **`Ctrl+F9`** (Run All), and walk away. It handles setup + backtest + report saving automatically.

> 📓 **Tip**: Upload the notebook to `My Drive → trading → notebooks` so you always have it handy.

### Option B: Copy-Paste into a Blank Notebook

If you prefer a blank notebook, paste the block below into the **first cell**:

```python
# ╔══════════════════════════════════════════════════════════════════╗
# ║         MATS Colab Master Setup — run once per session          ║
# ╚══════════════════════════════════════════════════════════════════╝

# ── Step 1: Install dependencies ────────────────────────────────────
# Note: pandas-ta manages its own pandas version. Do NOT pin pandas.
!pip install -q polars pyarrow duckdb pandas-ta ccxt joblib

# ── Step 2: Mount Google Drive ──────────────────────────────────────
from google.colab import drive
drive.mount('/content/drive')

# ── Step 3: Clone or update the repo ────────────────────────────────
import os, shutil, time
if not os.path.exists('/content/mats-code'):
    !git clone https://github.com/aistudylearning/mats-code.git /content/mats-code
else:
    !cd /content/mats-code && git pull

# ── Step 4: Copy data from Drive → local SSD (~5 min, ~2× speedup) ─
# Drive I/O: ~50 MB/s   |   Colab local SSD: ~1 GB/s
DRIVE_DATA = "/content/drive/MyDrive/trading/raw/data/hot/data"
LOCAL_DATA  = "/content/data"

if not os.path.exists(LOCAL_DATA):
    print("⏳ Copying data to local SSD (one-time, ~5 min)...")
    t0 = time.time()
    shutil.copytree(DRIVE_DATA, LOCAL_DATA)
    print(f"✅ Data copied in {(time.time()-t0)/60:.1f} min")
else:
    print("✅ Local data already present — skipping copy")

# ── Step 5: Configure environment ───────────────────────────────────
os.environ["MATS_DATA_ROOT"] = LOCAL_DATA
%cd /content/mats-code

# ── Step 6: Verify ──────────────────────────────────────────────────
print("\n✅ MATS ready.")
print("   DATA_ROOT :", os.environ["MATS_DATA_ROOT"])
print("   First assets:", os.listdir(LOCAL_DATA)[:5])
```

> **Drive path note:** If your data.zip was zipped from the `mats-code/` root, the
> actual parquet files are at `trading/raw/data/hot/data/`. If zipped from inside
> `data/hot/data/`, they are at `trading/raw/`. Check with:
> `!ls /content/drive/MyDrive/trading/raw` and adjust `DRIVE_DATA` if needed.

---

## 3. Running Tasks on Colab

After the setup cell, use subsequent cells for your work:

```python
# Fetch latest data (writes directly to Drive — no rclone needed)
!python3 main.py fetch

# Run single-asset backtest
!python3 main.py backtest

# Run portfolio backtest (all 50 assets, 10 timeframes)
!python3 main.py portfolio --signal 0.2 --timeframe 1m 5m 15m 30m 1h 2h 4h 1D 1W 1M --html

# Run unit tests
!pytest tests/ -v
```

### HTML Reports → Drive (Automatic)

Reports are **automatically copied to Drive** when the backtest finishes:
```
My Drive → trading → reports → portfolio_report_YYYYMMDD_HHMMSS.html
```
No manual step needed. If for any reason the auto-copy failed, run:
```python
import shutil, glob, os
for f in glob.glob('/content/mats-code/output/*.html'):
    dest = f"/content/drive/MyDrive/trading/reports/{os.path.basename(f)}"
    shutil.copy2(f, dest)
    print("✅ Saved:", dest)
```

---

## 4. Anti-Idle (Prevent Session Timeout)

Colab disconnects after ~30 min of inactivity. Paste this in your browser's
DevTools console (F12 → Console --> Please type ‘allow pasting’ below and press Enter to allow pasting) to keep the session alive.

> **First time only:** Chrome may block pasting. Type `allow pasting` in the
> console and press Enter before pasting the snippet below.

```javascript
function keepAlive() {
    document.querySelector("colab-connect-button").click();
    console.log("🔄 Keep-alive ping at", new Date().toLocaleTimeString());
}
setInterval(keepAlive, 60000);
```

> **Note**: Sessions still have a hard limit of ~12 hours. Plan accordingly.

---

## 5. Performance Reference

| Setup | Estimated runtime (50 assets, 10 TF) |
|---|---|
| Drive mount only (no local copy) | ~4–5 hours |
| **Local SSD copy (standard above)** | **~1.5–2.5 hours** ✅ |
| Colab Pro (paid, ~$10/month) | ~1–1.5 hours |

---

## 6. Colab vs Local: Key Differences

| Aspect | Colab | Local (L1/L3) |
|---|---|---|
| Data access | Local SSD after copy (~1 GB/s) | Local disk (fastest) |
| Persistence | ❌ Everything lost on disconnect | ✅ Persistent filesystem |
| Startup time | ~6 min (pip + mount + clone + copy) | 0s (already set up) |
| Git workflow | `!git pull` only; commits are clunky | Full IDE + git integration |
| Max runtime | ~12 hours (hard limit) | Unlimited |
| Cost | Free (with limits) | Your electricity |

---

## 7. Lessons Learned & Notes

> _This section is a living journal. Add your observations as you use Colab._

### 2026-05-12 — Initial Setup & Lessons
- ✅ **Do NOT pin `pandas==2.2.2`** — causes a hard conflict with `pandas-ta`.
  The original "ERROR" about pandas was a warning only; MATS uses Polars so it is harmless.
- ⚠️ **ZIP path gotcha**: When zipping from the project root (`mats-code/`), the zip preserves
  the full `data/hot/data/` subfolder path. After extracting to `trading/raw/`, the actual
  parquet files end up at `trading/raw/data/hot/data/{ASSET}/`. Set `DRIVE_DATA` accordingly.
- 💡 To avoid this in future: zip from inside `data/hot/data/` so the asset folders are at the
  zip root, and extraction to `trading/raw/` gives the clean `trading/raw/{ASSET}/` structure.
- 🚀 **Copy to local SSD first** — cuts runtime from ~5h to ~2h for the 50-asset 10-TF backtest.
- 📊 **Reports auto-save to Drive** — `html_exporter.py` detects Drive mount and copies automatically.
- 🖥️ **Chrome DevTools paste block** — type `allow pasting` in the console before pasting the
  anti-idle snippet. Chrome blocks paste by default on first use.

<!--
Template for adding lessons:

### YYYY-MM-DD — Topic
- Observation or issue encountered
- Solution or workaround applied
- Pro/con discovered
-->
