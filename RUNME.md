# MATS — Operational Guide

> What to run, where to run it, and what to expect.

---

## Quick Reference: Task × Environment Matrix

| Task | Command | L1 (WSL) | L3 (Worker) | Colab | Notes |
|---|---|---|---|---|---|
| **Unit tests** | `pytest tests/ -v` | ✅ | ✅ | ✅ | No data needed — uses mock data |
| **Fetch data** | `python3 main.py fetch` | ✅ | ✅ | ✅ ⭐ | Colab writes directly to Drive |
| **Single backtest** | `python3 main.py backtest` | ⚠️ | ✅ | ✅ | L1 needs data synced first |
| **Portfolio backtest** | `python3 main.py portfolio --machine L1` | ⚠️ | ✅ | ✅ | ~50 assets, parallel via joblib. **Always pass `--machine`** |
| **Parameter sweep** | `python3 main.py sweep --machine L1` | ❌ | ✅ | ✅ ⭐ | Colab best for large sweeps. **Always pass `--machine`** |
| **View HTML report** | Open in browser | ✅ | ✅ | 📱 via Drive | Push to `gdrive:trading/reports/` |
| **Code editing** | IDE + git push | ✅ ⭐ | ✅ | ⚠️ | L1 with IDE is the primary dev env |

**Legend**: ✅ works well · ⭐ best environment · ⚠️ works but has caveats · ❌ not recommended

---

## Data Flow

```
         Code: GitHub (source of truth)
         Data: Google Drive (source of truth)

  ┌──────────┐       git push        ┌──────────┐
  │  L1/WSL  │ ───────────────────►  │  GitHub  │
  │  (code)  │                       │          │
  └──────────┘                       └────┬─────┘
                                          │ git pull / clone
                                          ▼
  ┌──────────┐    rclone sync        ┌──────────┐    native mount
  │  L3      │ ◄────────────────►    │  Google  │ ◄──────────────►  Colab
  │  (worker)│                       │  Drive   │
  └──────────┘                       └──────────┘
```

---

## Machine Profiles (`--machine`)

The `portfolio` and `sweep` subcommands require a `--machine` flag to set the optimal number of parallel workers for your hardware. If omitted, it defaults to `L1`.

| Flag | Hardware | Workers | Use when running on |
|---|---|---|---|
| `--machine L1` | 14C/18T | 16 | Laptop 1 (Dev Node, WSL) |
| `--machine L3` | 4C/8T | 6 | Laptop 3 (Always-On Worker) |
| `--machine L2` | 4C/4T | 4 | Laptop 2 (Controller) |
| `--machine Colab` | 2C | 2 | Google Colab |

> **Why this matters**: Without `--machine`, the system defaults to 16 workers (L1). Running 16 workers on a 2-core Colab instance would cause severe thrashing.

## Environment Setup Before Running

### On L1 / L3 (local machines)
```bash
source .venv/bin/activate
# Data must be synced from Drive first:
rclone sync gdrive:trading/raw/ data/hot/data/ --progress
```

### On Colab
```python
# Run the setup cell from INSTALLME.Colab.md § 2
# Data is already on Drive — no sync needed
```

---

## Common Workflows

### 1. Daily Research Cycle
```bash
# On Colab:
!python3 main.py fetch          # Update data (writes to Drive)

# Run portfolio backtest with real-time log saving to Drive
!python3 -u main.py portfolio --signal 0.2 --machine Colab --timeframe 1m 5m 15m 30m 1h 2h 4h 1D 1W 1M --html 2>&1 | tee /content/drive/MyDrive/trading/reports/log_backtest_latest.txt

# → HTML Reports auto-save to Drive now. View on phone via Google Drive app.
```

### 2. Code Development Cycle
```bash
# On L1 (WSL):
# Edit code in IDE
pytest tests/ -v                # Verify changes
git add -A && git commit -m "description" && git push

# On Colab (to test with real data):
!cd /content/mats-code && git pull
!python3 main.py backtest
```

### 3. After Fetching New Data
```bash
# If fetched on Colab: data is already on Drive ✅
# If fetched on L1/L3: push to Drive
rclone sync data/hot/data/ gdrive:trading/raw/ --progress

# Other machines pull:
rclone sync gdrive:trading/raw/ data/hot/data/ --progress
```
