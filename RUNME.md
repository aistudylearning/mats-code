# MATS — Operational Guide

> What to run, where to run it, and what to expect.

---

## Quick Reference: Task × Environment Matrix

| Task | Command | L1 (WSL) | L3 (Worker) | Colab | Notes |
|---|---|---|---|---|---|
| **Unit tests** | `pytest tests/ -v` | ✅ | ✅ | ✅ | No data needed — uses mock data |
| **Fetch data** | `python3 main.py fetch` | ✅ | ✅ | ✅ ⭐ | Colab writes directly to Drive |
| **Single backtest** | `python3 main.py backtest` | ⚠️ | ✅ | ✅ | L1 needs data synced first |
| **Portfolio backtest** | `python3 main.py portfolio` | ⚠️ | ✅ | ✅ | ~50 assets, parallel via joblib |
| **Parameter sweep** | `python3 main.py sweep` | ❌ | ✅ | ✅ ⭐ | Colab best for large sweeps |
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
!python3 main.py portfolio      # Run portfolio backtest
!cp output/*.html "/content/drive/MyDrive/trading/reports/"
# → View reports on phone via Google Drive app
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
