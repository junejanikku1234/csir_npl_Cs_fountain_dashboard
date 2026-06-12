#!/bin/bash
# CSIR-NPL Cesium Fountain Clock Dashboard — macOS/Linux launcher

echo "=============================================="
echo " CSIR-NPL Cesium Fountain Clock Dashboard"
echo " Time & Frequency Division, CSIR-NPL"
echo "=============================================="
echo ""

# ── 1. Check Python ────────────────────────────────────────────────────────────
if ! command -v python3 &> /dev/null; then
    echo "ERROR: Python 3 is not installed."
    echo ""
    echo "Please install Anaconda (recommended):"
    echo "  https://www.anaconda.com/download"
    echo "Or plain Python: https://www.python.org/downloads/"
    echo ""
    read -p "Press Enter to exit..."
    exit 1
fi

PYTHON_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PYTHON_OK=$(python3 -c "import sys; print('yes' if sys.version_info >= (3, 8) else 'no')")

if [ "$PYTHON_OK" != "yes" ]; then
    echo "ERROR: Python $PYTHON_VERSION is too old. Python 3.8 or newer is required."
    echo ""
    echo "Please update Python via Anaconda or from https://www.python.org/downloads/"
    read -p "Press Enter to exit..."
    exit 1
fi

echo "✓ Python $PYTHON_VERSION found"

# ── 2. Check pip ───────────────────────────────────────────────────────────────
if ! python3 -m pip --version &> /dev/null; then
    echo "ERROR: pip is not available."
    echo "Try: python3 -m ensurepip --upgrade"
    read -p "Press Enter to exit..."
    exit 1
fi
echo "✓ pip found"
echo ""
echo "Checking dependencies..."
echo ""

# ── 3. Check Streamlit is installed and version is >= 1.35 ────────────────────
NEEDS_INSTALL=false

if ! python3 -c "import streamlit" &> /dev/null; then
    echo "  Streamlit not found. Installing..."
    NEEDS_INSTALL=true
else
    ST_VERSION=$(python3 -c "import streamlit; print(streamlit.__version__)")
    # Check version >= 1.35.0
    IS_OLD=$(python3 -c "
from packaging.version import Version
import streamlit
print('yes' if Version(streamlit.__version__) < Version('1.35.0') else 'no')
" 2>/dev/null)

    if [ "$IS_OLD" = "yes" ]; then
        echo "⚠ Streamlit $ST_VERSION is too old (need 1.35.0+)."
        echo "  This causes the 'altair.vegalite.v4' import error."
        echo "  Upgrading now..."
        NEEDS_INSTALL=true
    else
        echo "✓ Streamlit $ST_VERSION"
    fi
fi

if [ "$NEEDS_INSTALL" = true ]; then
    python3 -m pip install --upgrade "streamlit>=1.35.0" -q
    if [ $? -ne 0 ]; then
        echo "ERROR: Could not install/upgrade Streamlit."
        echo "Try manually: pip install --upgrade streamlit"
        read -p "Press Enter to exit..."
        exit 1
    fi
    ST_VERSION=$(python3 -c "import streamlit; print(streamlit.__version__)" 2>/dev/null)
    echo "✓ Streamlit $ST_VERSION installed/upgraded"
fi

# ── 4. Verify Streamlit actually loads without errors ─────────────────────────
# (catches altair/protobuf/any other internal conflict)
IMPORT_ERR=$(python3 -c "
import streamlit
from streamlit.web import cli
from streamlit.runtime import Runtime
" 2>&1)

if [ -n "$IMPORT_ERR" ]; then
    # Something is broken — try upgrading altair and protobuf together
    echo "⚠ Streamlit has a compatibility issue:"
    echo "  $IMPORT_ERR"
    echo "  Attempting automatic fix..."
    python3 -m pip install --upgrade "streamlit>=1.35.0" altair protobuf -q
    if [ $? -ne 0 ]; then
        echo "ERROR: Auto-fix failed. Please send the error above to whoever gave you this app."
        read -p "Press Enter to exit..."
        exit 1
    fi

    # Re-check
    IMPORT_ERR2=$(python3 -c "
import streamlit
from streamlit.web import cli
from streamlit.runtime import Runtime
" 2>&1)
    if [ -n "$IMPORT_ERR2" ]; then
        echo "ERROR: Could not resolve automatically:"
        echo "  $IMPORT_ERR2"
        echo "Please send this error to whoever gave you this app."
        read -p "Press Enter to exit..."
        exit 1
    fi
    echo "✓ Conflict resolved"
else
    ALTAIR_VERSION=$(python3 -c "import altair; print(altair.__version__)" 2>/dev/null || echo "n/a")
    echo "✓ Altair $ALTAIR_VERSION (compatible)"
    echo "✓ All dependencies OK"
fi

# ── 5. Launch ──────────────────────────────────────────────────────────────────
echo ""
echo "Launching dashboard..."
echo "→ Opening in your browser at http://localhost:8501"
echo "→ Close this terminal window to stop the server."
echo ""

cd "$(dirname "$0")"

python3 -m streamlit run app.py \
    --browser.gatherUsageStats false \
    --theme.base dark
