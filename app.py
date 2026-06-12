"""
CSIR-NPL Caesium Fountain Clock Data Dashboard
Time & Frequency Division — Data Processing Tool
"""

from __future__ import annotations
import streamlit as st
import io
import zipfile
from decimal import Decimal, getcontext
from datetime import date, time as dtime


# ── Precision ──────────────────────────────────────────────────────────────────
getcontext().prec = 20

# ── Constants ──────────────────────────────────────────────────────────────────
FAKE_VALUE   = Decimal("8.015365E+16")
FAKE_THRESH  = Decimal("8.015E+16")          # anything >= this is treated as calibration
SAMPLES_DAY  = Decimal("43200")              # 2-second cadence → 43200 pts/day
DELTA_MJD    = Decimal("2") / Decimal("86400")
IST_OFFSET_S = Decimal("19800")             # IST = UTC + 5:30 = 19800 s


# ══════════════════════════════════════════════════════════════════════════════
#  MJD helpers
# ══════════════════════════════════════════════════════════════════════════════

def date_to_mjd_int(d: date) -> int:
    """Return integer MJD for a calendar date (Gregorian). No internet needed."""
    y, m, day = d.year, d.month, d.day
    # Standard formula (valid for all dates after 1858-11-17)
    a = (14 - m) // 12
    y2 = y + 4800 - a
    m2 = m + 12 * a - 3
    jdn = day + (153 * m2 + 2) // 5 + 365 * y2 + y2 // 4 - y2 // 100 + y2 // 400 - 32045
    mjd = jdn - 2400000 - 1          # MJD = JDN - 2400000.5  →  integer part = JDN - 2400001 + 1 - 1
    # More precisely: MJD = JD - 2400000.5 and JD = JDN - 0.5 at midnight
    # So MJD at midnight = JDN - 2400001
    mjd = jdn - 2400001
    return mjd


def ist_to_fractional_mjd(t: dtime) -> Decimal:
    """Convert an IST time to fractional MJD (UTC-based)."""
    ist_seconds = (Decimal(t.hour) * 3600
                   + Decimal(t.minute) * 60
                   + Decimal(t.second))
    utc_seconds = ist_seconds - IST_OFFSET_S
    return utc_seconds / Decimal("86400")


# ══════════════════════════════════════════════════════════════════════════════
#  LVM Processing
# ══════════════════════════════════════════════════════════════════════════════

def parse_lvm(raw_bytes: bytes, start_date: date, start_time: dtime):
    """
    Parse a .lvm file and return list of (Decimal MJD, Decimal frequency) tuples
    after stripping calibration values.
    """
    text = raw_bytes.decode("utf-8", errors="replace")
    lines = text.splitlines()

    # Find the header sentinel line
    data_start = None
    for i, line in enumerate(lines):
        if line.strip().startswith("X_Value"):
            data_start = i + 1
            break

    if data_start is None:
        raise ValueError("Could not find 'X_Value' header line in LVM file.")

    # Parse frequency values
    raw_freqs: list[Decimal] = []
    for line in lines[data_start:]:
        line = line.strip()
        if not line:
            continue
        # Tab-separated; frequency is the first token
        token = line.split("\t")[0].strip()
        if not token:
            continue
        try:
            raw_freqs.append(Decimal(token))
        except Exception:
            continue   # skip any unparseable lines

    if not raw_freqs:
        raise ValueError("No data points found in LVM file.")

    # Count leading calibration rows FIRST (before MJD assignment)
    n_fake_leading = 0
    for freq in raw_freqs:
        if freq >= FAKE_THRESH:
            n_fake_leading += 1
        else:
            break

    # The user's start time is the time of the very first row (including fake calibration rows).
    # The first REAL data point's MJD is therefore offset by n_fake_leading * 2 seconds.
    base_mjd = Decimal(date_to_mjd_int(start_date))
    frac_mjd = ist_to_fractional_mjd(start_time)
    first_real_mjd = base_mjd + frac_mjd + DELTA_MJD * Decimal(n_fake_leading)

    # Work only with real data points from here
    real_freqs = list(raw_freqs[n_fake_leading:])

    # Drop trailing calibration row if present
    if real_freqs and real_freqs[-1] >= FAKE_THRESH:
        real_freqs = real_freqs[:-1]

    if not real_freqs:
        raise ValueError("No real data points found after stripping calibration rows.")

    # Frequency scaling: divide by 1e20 to get fractional frequency
    FREQ_SCALE = Decimal("1E+20")

    rows: list[tuple[Decimal, Decimal]] = []
    for i, freq in enumerate(real_freqs):
        mjd = first_real_mjd + DELTA_MJD * Decimal(i)
        rows.append((mjd, freq / FREQ_SCALE))
    
    # Remove consecutive duplicate frequency values — any row that is part of a
    # run of 2 or more identical consecutive frequency values is dropped entirely,
    # including the first occurrence (these are invalid repeated readings).
    if rows:
        n = len(rows)
        rows = [
            (mjd, freq)
            for i, (mjd, freq) in enumerate(rows)
            if not (
                (i > 0     and rows[i - 1][1] == freq) or
                (i < n - 1 and rows[i + 1][1] == freq)
            )
        ]

    return rows


# ══════════════════════════════════════════════════════════════════════════════
#  Combine + sort
# ══════════════════════════════════════════════════════════════════════════════

def combine_and_sort(all_rows: list[tuple[Decimal, Decimal]]) -> list[tuple[Decimal, Decimal]]:
    return sorted(all_rows, key=lambda r: r[0])


# ══════════════════════════════════════════════════════════════════════════════
#  Day splitting
# ══════════════════════════════════════════════════════════════════════════════

def split_by_day(combined: list[tuple[Decimal, Decimal]]) -> dict[int, list]:
    """
    Returns a dict  {mjd_int: [(mjd, freq), ...]}
    Each key N covers MJD range [N-0.5, N+0.5).
    Only days that actually contain at least one data point are included.
    """
    if not combined:
        return {}

    half = Decimal("0.5")
    days: dict[int, list] = {}

    for mjd, freq in combined:
        # Day N covers [N-0.5, N+0.5): use floor(mjd + 0.5)
        # int() on a positive Decimal truncates = floor
        n = int(mjd + half)
        if n not in days:
            days[n] = []
        days[n].append((mjd, freq))

    return days


# ══════════════════════════════════════════════════════════════════════════════
#  Statistics
# ══════════════════════════════════════════════════════════════════════════════

def compute_statistics(days: dict[int, list], combined: list) -> str:
    lines = []
    lines.append("CSIR-NPL Caesium Fountain Clock — Run Statistics")
    lines.append("=" * 56)
    lines.append("")
    lines.append("Per-Day Statistics:")
    lines.append("-" * 56)
    lines.append(f"{'Day (MJD)':<12} {'Data Points':>12} {'Uptime %':>12} {'Deadtime %':>12}")
    lines.append("-" * 56)

    total_points = 0
    num_days = len(days)

    for day_n in sorted(days.keys()):
        pts = len(days[day_n])
        total_points += pts
        uptime   = (Decimal(pts) / SAMPLES_DAY * 100).quantize(Decimal("0.0001"))
        deadtime = (100 - uptime).quantize(Decimal("0.0001"))
        lines.append(f"{day_n:<12} {pts:>12} {float(uptime):>11.4f}% {float(deadtime):>11.4f}%")

    lines.append("-" * 56)
    lines.append("")
    lines.append("Overall (Combined File) Statistics:")
    lines.append("-" * 56)

    max_possible  = SAMPLES_DAY * num_days
    total_d       = Decimal(total_points)
    overall_up    = (total_d / max_possible * 100).quantize(Decimal("0.0001"))
    overall_dead  = (100 - overall_up).quantize(Decimal("0.0001"))

    lines.append(f"  Total days spanned  : {num_days}")
    lines.append(f"  Max possible points : {int(max_possible)}")
    lines.append(f"  Actual data points  : {total_points}")
    lines.append(f"  Overall uptime      : {float(overall_up):.4f}%")
    lines.append(f"  Overall deadtime    : {float(overall_dead):.4f}%")
    lines.append("")

    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
#  Serialise rows → bytes
# ══════════════════════════════════════════════════════════════════════════════

def rows_to_bytes(rows: list[tuple[Decimal, Decimal]]) -> bytes:
    buf = io.StringIO()
    for mjd, freq in rows:
        buf.write(f"{mjd}\t{freq}\n")
    return buf.getvalue().encode("utf-8")


# ══════════════════════════════════════════════════════════════════════════════
#  Streamlit UI
# ══════════════════════════════════════════════════════════════════════════════

def main():
    st.set_page_config(
        page_title="NPL Caesium Fountain Clock Dashboard",
        page_icon="⚛️",
        layout="wide",
    )

    # ── Custom CSS ────────────────────────────────────────────────────────────
    st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Share+Tech+Mono&family=Exo+2:wght@300;400;600;700&display=swap');

    html, body, [class*="css"] {
        font-family: 'Exo 2', sans-serif;
    }

    /* dark scientific theme */
    .stApp {
        background: #0a0e1a;
        color: #c8d8e8;
    }

    .block-container {
        padding-top: 2rem;
        max-width: 1100px;
    }

    h1, h2, h3 {
        font-family: 'Share Tech Mono', monospace !important;
        color: #4fc3f7 !important;
        letter-spacing: 0.04em;
    }

    /* cards */
    .file-card {
        background: linear-gradient(135deg, #0d1b2a 60%, #112240);
        border: 1px solid #1e3a5f;
        border-radius: 10px;
        padding: 1.2rem 1.4rem;
        margin-bottom: 1.2rem;
        box-shadow: 0 0 18px rgba(79,195,247,0.07);
    }

    .file-card:hover {
        border-color: #4fc3f7;
        box-shadow: 0 0 24px rgba(79,195,247,0.18);
        transition: all 0.2s ease;
    }

    .file-label {
        font-family: 'Share Tech Mono', monospace;
        font-size: 0.82rem;
        color: #4fc3f7;
        letter-spacing: 0.06em;
        margin-bottom: 0.3rem;
    }

    /* status pills */
    .pill-ok  { display:inline-block; background:#0d3b2e; color:#4caf50;
                border:1px solid #4caf50; border-radius:20px;
                padding:2px 10px; font-size:0.75rem; margin-left:6px; }
    .pill-err { display:inline-block; background:#3b0d0d; color:#ef5350;
                border:1px solid #ef5350; border-radius:20px;
                padding:2px 10px; font-size:0.75rem; margin-left:6px; }

    /* metric boxes */
    .metric-box {
        background: #0d1b2a;
        border: 1px solid #1e3a5f;
        border-radius: 8px;
        padding: 1rem;
        text-align: center;
    }
    .metric-val {
        font-family: 'Share Tech Mono', monospace;
        font-size: 1.6rem;
        color: #4fc3f7;
    }
    .metric-lbl {
        font-size: 0.78rem;
        color: #7a9bbf;
        letter-spacing: 0.05em;
    }

    /* section divider */
    .section-divider {
        border: none;
        border-top: 1px solid #1e3a5f;
        margin: 2rem 0;
    }

    /* download area */
    .download-section {
        background: linear-gradient(135deg, #0d1b2a, #0a1628);
        border: 1px solid #1e4a6f;
        border-radius: 12px;
        padding: 1.5rem 2rem;
    }

    /* override streamlit button */
    .stDownloadButton > button {
        background: #0d2a40 !important;
        color: #4fc3f7 !important;
        border: 1px solid #4fc3f7 !important;
        border-radius: 6px !important;
        font-family: 'Share Tech Mono', monospace !important;
        font-size: 0.82rem !important;
        letter-spacing: 0.04em;
        transition: all 0.15s ease;
    }
    .stDownloadButton > button:hover {
        background: #4fc3f7 !important;
        color: #0a0e1a !important;
    }

    .stButton > button {
        background: linear-gradient(135deg, #0d3b5e, #1565c0) !important;
        color: #e3f2fd !important;
        border: none !important;
        border-radius: 6px !important;
        font-family: 'Exo 2', sans-serif !important;
        font-weight: 600 !important;
        padding: 0.5rem 2rem !important;
        letter-spacing: 0.04em;
    }
    .stButton > button:hover {
        background: linear-gradient(135deg, #1565c0, #0d3b5e) !important;
        box-shadow: 0 0 14px rgba(79,195,247,0.3) !important;
    }

    /* file uploader */
    [data-testid="stFileUploader"] {
        background: #0d1b2a;
        border: 1px dashed #1e3a5f;
        border-radius: 10px;
        padding: 0.5rem;
    }

    /* date/time inputs */
    [data-testid="stDateInput"] input,
    [data-testid="stTimeInput"] input {
        background: #0d1b2a !important;
        color: #c8d8e8 !important;
        border: 1px solid #1e3a5f !important;
        border-radius: 6px !important;
        font-family: 'Share Tech Mono', monospace !important;
    }

    /* expander */
    .streamlit-expanderHeader {
        background: #0d1b2a !important;
        color: #4fc3f7 !important;
        font-family: 'Share Tech Mono', monospace !important;
        border: 1px solid #1e3a5f !important;
        border-radius: 8px !important;
    }

    /* info/warning/success boxes */
    .stAlert {
        border-radius: 8px !important;
    }

    /* hide streamlit branding */
    #MainMenu, footer, header { visibility: hidden; }
    </style>
    """, unsafe_allow_html=True)

    # ── Header ────────────────────────────────────────────────────────────────
    st.markdown("""
    <div style='text-align:center; padding: 1rem 0 0.5rem 0;'>
        <div style='font-family:"Share Tech Mono",monospace; font-size:0.8rem;
                    color:#4fc3f7; letter-spacing:0.2em; margin-bottom:0.3rem;'>
            CSIR — NATIONAL PHYSICAL LABORATORY
        </div>
        <h1 style='font-size:2rem; margin:0; padding:0;'>
            ⚛️ &nbsp; Caesium Fountain Clock Dashboard
        </h1>
        <div style='font-family:"Exo 2",sans-serif; font-size:0.9rem;
                    color:#7a9bbf; margin-top:0.4rem; letter-spacing:0.05em;'>
            Time &amp; Frequency Division &nbsp;·&nbsp; LVM Data Processing Tool
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("<hr class='section-divider'>", unsafe_allow_html=True)

    # ── Step 1: Upload ─────────────────────────────────────────────────────────
    st.markdown("### 📂 &nbsp; Step 1 — Upload LVM Files")
    st.markdown(
        "<div style='font-size:0.85rem; color:#7a9bbf; margin-bottom:1rem;'>"
        "Select one or more <code>.lvm</code> files from your computer. "
        "You will then assign a start date &amp; IST time to each file."
        "</div>",
        unsafe_allow_html=True,
    )

    uploaded_files = st.file_uploader(
        "Browse or drag-and-drop your .lvm files here",
        type=["lvm"],
        accept_multiple_files=True,
        help="Select all .lvm files you want to process in this session.",
        label_visibility="collapsed",
    )

    if not uploaded_files:
        st.info("⬆️  Upload at least one .lvm file to begin.")
        st.stop()

    st.success(f"✅  {len(uploaded_files)} file(s) uploaded.")

    st.markdown("<hr class='section-divider'>", unsafe_allow_html=True)

    # ── Step 2: Date/Time per file ─────────────────────────────────────────────
    st.markdown("### 🗓️ &nbsp; Step 2 — Assign Start Date &amp; IST Time")
    st.markdown(
        "<div style='font-size:0.85rem; color:#7a9bbf; margin-bottom:1rem;'>"
        "For each uploaded file, select the date and start time (IST, 24-hour) "
        "corresponding to the <b>first data point</b> in that file."
        "</div>",
        unsafe_allow_html=True,
    )

    file_configs: list[dict] = []

    for i, uf in enumerate(uploaded_files):
        st.markdown(f"<div class='file-label'>FILE {i+1:02d}</div>", unsafe_allow_html=True)
        with st.container():
            col_name, col_date, col_hh, col_mm, col_ss = st.columns([3, 2, 1, 1, 1])
            with col_name:
                st.markdown(
                    f"<div style='font-family:\"Share Tech Mono\",monospace; "
                    f"font-size:0.9rem; color:#e3f2fd; padding-top:1.9rem;'>"
                    f"📄 {uf.name}</div>",
                    unsafe_allow_html=True,
                )
            with col_date:
                chosen_date = st.date_input(
                    "Start Date",
                    value=date.today(),
                    key=f"date_{i}",
                    help="Calendar date for the first reading in this file.",
                )
            with col_hh:
                chosen_hh = st.number_input(
                    "HH (IST)",
                    min_value=0, max_value=23, value=0,
                    key=f"hh_{i}",
                    help="Hour (0-23) in Indian Standard Time.",
                )
            with col_mm:
                chosen_mm = st.number_input(
                    "MM",
                    min_value=0, max_value=59, value=0,
                    key=f"mm_{i}",
                    help="Minute (0-59).",
                )
            with col_ss:
                chosen_ss = st.number_input(
                    "SS",
                    min_value=0, max_value=59, value=0,
                    key=f"ss_{i}",
                    help="Second (0-59).",
                )

            chosen_time = dtime(int(chosen_hh), int(chosen_mm), int(chosen_ss))

            file_configs.append({
                "file": uf,
                "date": chosen_date,
                "time": chosen_time,
            })


        st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)

    st.markdown("<hr class='section-divider'>", unsafe_allow_html=True)

    # ── Step 3: Process ────────────────────────────────────────────────────────
    st.markdown("### ⚙️ &nbsp; Step 3 — Process &amp; Generate Output Files")

    if st.button("🚀  Run Processing", use_container_width=False):

        progress = st.progress(0, text="Initialising…")
        status   = st.empty()
        all_rows: list[tuple[Decimal, Decimal]] = []
        errors: list[str] = []

        n = len(file_configs)
        for idx, cfg in enumerate(file_configs):
            fname = cfg["file"].name
            status.markdown(
                f"<div style='font-family:\"Share Tech Mono\",monospace; "
                f"font-size:0.82rem; color:#4fc3f7;'>Processing: {fname}</div>",
                unsafe_allow_html=True,
            )
            try:
                raw = cfg["file"].read()
                rows = parse_lvm(raw, cfg["date"], cfg["time"])
                all_rows.extend(rows)
                st.markdown(
                    f"<div class='file-card'>"
                    f"<span style='font-family:\"Share Tech Mono\",monospace;"
                    f"font-size:0.85rem; color:#c8d8e8;'>📄 {fname}</span>"
                    f"<span class='pill-ok'>✓ {len(rows)} points</span>"
                    f"</div>",
                    unsafe_allow_html=True,
                )
            except Exception as e:
                errors.append(f"{fname}: {e}")
                st.markdown(
                    f"<div class='file-card'>"
                    f"<span style='font-family:\"Share Tech Mono\",monospace;"
                    f"font-size:0.85rem; color:#c8d8e8;'>📄 {fname}</span>"
                    f"<span class='pill-err'>✗ {e}</span>"
                    f"</div>",
                    unsafe_allow_html=True,
                )
            progress.progress((idx + 1) / n, text=f"Processed {idx+1}/{n} files…")

        status.empty()
        progress.empty()

        if not all_rows:
            st.error("No valid data points were extracted. Please check your files and timestamps.")
            st.stop()

        # Combine + sort
        combined = combine_and_sort(all_rows)
        days     = split_by_day(combined)
        stats    = compute_statistics(days, combined)

        # Summary metrics
        st.markdown("<hr class='section-divider'>", unsafe_allow_html=True)
        st.markdown("### 📊 &nbsp; Summary")

        mc = st.columns(4)
        total_pts = len(combined)
        n_days    = len(days)
        first_mjd = combined[0][0]
        last_mjd  = combined[-1][0]
        overall_up = float((Decimal(total_pts) / (SAMPLES_DAY * n_days) * 100).quantize(Decimal("0.01")))

        with mc[0]:
            st.markdown(
                f"<div class='metric-box'><div class='metric-val'>{total_pts:,}</div>"
                f"<div class='metric-lbl'>TOTAL DATA POINTS</div></div>",
                unsafe_allow_html=True,
            )
        with mc[1]:
            st.markdown(
                f"<div class='metric-box'><div class='metric-val'>{n_days}</div>"
                f"<div class='metric-lbl'>DAYS SPANNED</div></div>",
                unsafe_allow_html=True,
            )
        with mc[2]:
            st.markdown(
                f"<div class='metric-box'><div class='metric-val'>{overall_up:.2f}%</div>"
                f"<div class='metric-lbl'>OVERALL UPTIME</div></div>",
                unsafe_allow_html=True,
            )
        with mc[3]:
            st.markdown(
                f"<div class='metric-box'><div class='metric-val'>"
                f"{float(first_mjd):.4f}→{float(last_mjd):.4f}</div>"
                f"<div class='metric-lbl'>MJD RANGE</div></div>",
                unsafe_allow_html=True,
            )

        st.markdown("<hr class='section-divider'>", unsafe_allow_html=True)

        # ── Downloads ──────────────────────────────────────────────────────────
        st.markdown("### 💾 &nbsp; Step 4 — Download Output Files")

        # Build ZIP with everything
        zip_buf = io.BytesIO()
        with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
            # combined.txt
            combined_bytes = rows_to_bytes(combined)
            zf.writestr("combined.txt", combined_bytes)

            # per-day files
            for day_n in sorted(days.keys()):
                day_bytes = rows_to_bytes(days[day_n])
                zf.writestr(f"{day_n}.txt", day_bytes)

            # stats
            zf.writestr("clock_run_statistics.txt", stats.encode("utf-8"))

        zip_buf.seek(0)

        st.markdown("<div class='download-section'>", unsafe_allow_html=True)

        dl_col1, dl_col2, dl_col3 = st.columns(3)

        with dl_col1:
            st.markdown("**📦 All Files (ZIP)**")
            st.download_button(
                label="⬇  Download all_outputs.zip",
                data=zip_buf.getvalue(),
                file_name="all_outputs.zip",
                mime="application/zip",
                use_container_width=True,
            )

        with dl_col2:
            st.markdown("**📄 Combined Dataset**")
            st.download_button(
                label="⬇  Download combined.txt",
                data=rows_to_bytes(combined),
                file_name="combined.txt",
                mime="text/plain",
                use_container_width=True,
            )

        with dl_col3:
            st.markdown("**📈 Run Statistics**")
            st.download_button(
                label="⬇  Download clock_run_statistics.txt",
                data=stats.encode("utf-8"),
                file_name="clock_run_statistics.txt",
                mime="text/plain",
                use_container_width=True,
            )

        st.markdown("<br>**📅 Individual Day Files**", unsafe_allow_html=True)
        day_cols = st.columns(min(len(days), 6))
        for ci, day_n in enumerate(sorted(days.keys())):
            with day_cols[ci % len(day_cols)]:
                st.download_button(
                    label=f"⬇  {day_n}.txt  ({len(days[day_n])} pts)",
                    data=rows_to_bytes(days[day_n]),
                    file_name=f"{day_n}.txt",
                    mime="text/plain",
                    use_container_width=True,
                    key=f"dl_day_{day_n}",
                )

        st.markdown("</div>", unsafe_allow_html=True)

        # Statistics preview
        st.markdown("<hr class='section-divider'>", unsafe_allow_html=True)
        with st.expander("🔬 View Clock Run Statistics", expanded=False):
            st.code(stats, language=None)
 
        if errors:
            st.markdown("<hr class='section-divider'>", unsafe_allow_html=True)
            st.warning(f"⚠️  {len(errors)} file(s) had errors and were skipped:")
            for e in errors:
                st.markdown(f"- `{e}`")

    # ── Footer ─────────────────────────────────────────────────────────────────
    st.markdown("<hr class='section-divider'>", unsafe_allow_html=True)
    st.markdown(
        "<div style='text-align:center; font-size:0.75rem; color:#3a5a7a; "
        "font-family:\"Share Tech Mono\",monospace; letter-spacing:0.08em;'>"
        "CSIR-NPL &nbsp;·&nbsp; Time &amp; Frequency Division &nbsp;·&nbsp; "
        "Caesium Fountain Clock Analysis Suite &nbsp;·&nbsp; v1.0"
        "</div>",
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()