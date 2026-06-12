# CSIR-NPL Cesium Fountain Clock Dashboard

**Time & Frequency Division — LVM Data Processing Tool**

---

## Overview

A Streamlit-based interactive dashboard for processing raw Cesium Fountain Clock
data files (`.lvm`) recorded by LabVIEW. It automates MJD timestamp assignment,
data cleaning, day-wise splitting, and run statistics — tasks previously done manually.

Fully offline. No internet connection required after initial setup.

---

## Files

| File | Description |
|---|---|
| `app.py` | The Streamlit dashboard (main application) |
| `run_mac.sh` | One-click launcher for macOS / Linux |
| `run_windows.bat` | One-click launcher for Windows |
| `requirements.txt` | Python dependencies |

---

## Running the App

### macOS / Linux

```bash
# First time only — make the script executable
chmod +x run_mac.sh

# Launch
./run_mac.sh
```

### Windows

Double-click `run_windows.bat`.

Both scripts will automatically check your Python version, install Streamlit if
missing, detect and fix common version conflicts, then open the dashboard in your
browser at `http://localhost:8501`.

---

## Requirements

- Python **3.8 or newer** (check with `python --version`)
- Streamlit 1.35.0 or newer (installed automatically by the launcher scripts)
- Internet access required only for the first-time Streamlit installation

If you do not have Python, install **Anaconda** (recommended for scientific use):
https://www.anaconda.com/download

---

## Usage

**Step 1 — Upload**
Click the file browser and select one or more `.lvm` files. Multiple files can be
selected at once.

**Step 2 — Assign timestamps**
For each uploaded file, set the recording start date and IST time (HH / MM / SS)
using the pickers. This is the time corresponding to the very first row in that
file, including any leading calibration rows.

**Step 3 — Process**
Click "Run Processing". The app processes all files and shows a per-file status
and a summary of total data points, days spanned, MJD range, and overall uptime.

**Step 4 — Download**
Download any combination of:
- `combined.txt` — all data merged and sorted by MJD
- `NNNNN.txt` per day — one file per MJD day
- `clock_run_statistics.txt` — uptime/deadtime report
- `all_outputs.zip` — everything bundled together

---

## Output File Format

All output `.txt` files are tab-separated with no column headers:

```
<MJD>    <fractional frequency>
60831.498391203703703703704    -5.30304424505E-14
60831.498414351851851851852    -6.25284329522E-14
...
```

---

## Processing Pipeline

### Per `.lvm` file

1. **Header stripping** — everything up to and including the `X_Value Untitled Comment` line is removed
2. **Calibration row handling** — leading rows with value `≥ 8.015×10¹⁶` are counted; the trailing row is also dropped if it matches; MJD timestamps are offset accordingly so the first real data point gets the correct timestamp
3. **MJD assignment** — computed locally using the standard Gregorian → Julian Day Number formula; IST start time is converted to UTC by subtracting 19800 seconds (5h 30m); each subsequent row is incremented by 2/86400 MJD (one 2-second step)
4. **Frequency scaling** — raw LabVIEW frequency values are divided by 1×10²⁰ to produce dimensionless fractional frequency
5. **Consecutive duplicate removal** — any row whose frequency value is identical to an immediately adjacent row is dropped entirely (both/all occurrences); these represent invalid repeated readings from the instrument

### Combining

All processed files are concatenated and sorted by MJD ascending.

### Day-wise splitting

The combined data is split into per-day files using `floor(MJD + 0.5)` as the day
index. Day file `NNNNN.txt` contains all rows where MJD falls in `[N−0.5, N+0.5)`.
Only days that contain at least one data point produce a file.

### Clock run statistics

Each day file is expected to have at most 43200 data points (one every 2 seconds).
Uptime % = `(actual points / 43200) × 100`. The combined file's overall uptime
is calculated against `43200 × number of days spanned`.

---

## Technical Notes

- Arithmetic uses Python's `decimal` module at **20-digit precision** — no floating-point drift on large MJD values
- Mixed frequency notation handled natively (`-1068524.609071` and `2.823672E+7` both parse correctly via `Decimal(token)`)
- MJD formula verified against the 1858-11-17 epoch anchor (MJD = 0) and the J2000 anchor
- All output is tab-separated with full decimal precision and no column headers

---

## Common Issues

**"altair.vegalite.v4" import error**
Your Streamlit installation is too old. The launcher scripts detect and fix this
automatically by upgrading Streamlit to 1.35.0+.

**"Could not find a suitable TLS CA certificate bundle" (Windows)**
Caused by PostgreSQL overriding the system SSL certificate path. The Windows
launcher script detects and works around this automatically.

**Browser doesn't open**
Navigate manually to `http://localhost:8501` after running the script.

**Port 8501 already in use**
Stop any other running Streamlit apps, or run directly with a different port:
```bash
streamlit run app.py --server.port 8502
```
