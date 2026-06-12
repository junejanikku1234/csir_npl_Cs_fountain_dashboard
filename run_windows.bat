@echo off
setlocal EnableDelayedExpansion
REM CSIR-NPL Cesium Fountain Clock Dashboard — Windows launcher

echo ==============================================
echo  CSIR-NPL Cesium Fountain Clock Dashboard
echo  Time ^& Frequency Division, CSIR-NPL
echo ==============================================
echo.

REM ── 1. Check Python ──────────────────────────────────────────────────────────
python --version >NUL 2>&1
if errorlevel 1 (
    python3 --version >NUL 2>&1
    if errorlevel 1 (
        echo ERROR: Python is not installed or not on PATH.
        echo.
        echo Please install Anaconda ^(recommended^):
        echo   https://www.anaconda.com/download
        echo Or plain Python: https://www.python.org/downloads/
        echo ^(tick "Add Python to PATH" during installation^)
        pause
        exit /b 1
    )
    set PYTHON=python3
) else (
    set PYTHON=python
)

for /f "tokens=*" %%v in ('!PYTHON! --version 2^>^&1') do set PY_VER=%%v
echo [OK] !PY_VER! found

REM ── Check Python version is 3.8+ ─────────────────────────────────────────────
!PYTHON! -c "import sys; exit(0 if sys.version_info >= (3,8) else 1)" >NUL 2>&1
if errorlevel 1 (
    echo ERROR: Your Python version is too old. Python 3.8 or newer is required.
    echo.
    echo Please update Python via Anaconda or from https://www.python.org/downloads/
    pause
    exit /b 1
)

REM ── 2. Check pip ─────────────────────────────────────────────────────────────
!PYTHON! -m pip --version >NUL 2>&1
if errorlevel 1 (
    echo ERROR: pip is not available.
    echo Try: python -m ensurepip --upgrade
    pause
    exit /b 1
)
echo [OK] pip found
REM ── SSL Certificate fix (needed on machines with PostgreSQL installed) ────────
REM PostgreSQL incorrectly sets SSL_CERT_FILE system-wide which breaks pip.
REM We override it with Python's own certificate bundle.
for /f "tokens=*" %%c in ('!PYTHON! -c "import certifi; print(certifi.where())"  2^>NUL') do set CERT_PATH=%%c
if not "!CERT_PATH!"=="" (
    set SSL_CERT_FILE=!CERT_PATH!
    set REQUESTS_CA_BUNDLE=!CERT_PATH!
)

echo Checking dependencies...
echo.

REM ── 3. Check Streamlit version ────────────────────────────────────────────────
set NEEDS_INSTALL=0

!PYTHON! -c "import streamlit" >NUL 2>&1
if errorlevel 1 (
    echo [..] Streamlit not found. Installing...
    set NEEDS_INSTALL=1
) else (
    REM Check version >= 1.35.0
    !PYTHON! -c "from packaging.version import Version; import streamlit; exit(0 if Version(streamlit.__version__) >= Version('1.35.0') else 1)" >NUL 2>&1
    if errorlevel 1 (
        for /f %%v in ('!PYTHON! -c "import streamlit; print(streamlit.__version__)"') do set ST_OLD=%%v
        echo [!!] Streamlit !ST_OLD! is too old ^(need 1.35.0+^).
        echo      This causes the "altair.vegalite.v4" import error.
        echo      Upgrading now...
        set NEEDS_INSTALL=1
    ) else (
        for /f %%v in ('!PYTHON! -c "import streamlit; print(streamlit.__version__)"') do set ST_VER=%%v
        echo [OK] Streamlit !ST_VER!
    )
)

if !NEEDS_INSTALL!==1 (
    REM First ensure certifi is available so SSL works correctly
    !PYTHON! -m pip install --upgrade certifi -q --trusted-host pypi.org --trusted-host files.pythonhosted.org
    for /f "tokens=*" %%c in ('!PYTHON! -c "import certifi; print(certifi.where())" 2^>NUL') do set SSL_CERT_FILE=%%c
    for /f "tokens=*" %%c in ('!PYTHON! -c "import certifi; print(certifi.where())" 2^>NUL') do set REQUESTS_CA_BUNDLE=%%c
    !PYTHON! -m pip install --upgrade "streamlit>=1.35.0" -q
    if errorlevel 1 (
        echo ERROR: Could not install/upgrade Streamlit.
        echo Try manually: pip install --upgrade streamlit
        pause
        exit /b 1
    )
    for /f %%v in ('!PYTHON! -c "import streamlit; print(streamlit.__version__)"') do set ST_VER=%%v
    echo [OK] Streamlit !ST_VER! installed/upgraded
)

REM ── 4. Verify Streamlit actually loads without errors ─────────────────────────
!PYTHON! -c "import streamlit; from streamlit.web import cli; from streamlit.runtime import Runtime" >NUL 2>&1
if errorlevel 1 (
    echo [!!] Streamlit has a compatibility issue. Attempting automatic fix...
    !PYTHON! -m pip install --upgrade "streamlit>=1.35.0" altair protobuf -q --trusted-host pypi.org --trusted-host files.pythonhosted.org
    if errorlevel 1 (
        echo ERROR: Auto-fix failed. Please send this error to whoever gave you this app.
        pause
        exit /b 1
    )
    REM Re-check
    !PYTHON! -c "import streamlit; from streamlit.web import cli; from streamlit.runtime import Runtime" >NUL 2>&1
    if errorlevel 1 (
        echo ERROR: Could not resolve automatically.
        echo Please send this error to whoever gave you this app.
        pause
        exit /b 1
    )
    echo [OK] Conflict resolved
) else (
    for /f %%v in ('!PYTHON! -c "import altair; print(altair.__version__)" 2^>NUL') do set ALT_VER=%%v
    echo [OK] Altair !ALT_VER! ^(compatible^)
    echo [OK] All dependencies OK
)

REM ── 5. Launch ─────────────────────────────────────────────────────────────────
echo.
echo Launching dashboard...
echo -^> Opening in your browser at http://localhost:8501
echo -^> Close this window to stop the server.
echo.

cd /d "%~dp0"
!PYTHON! -m streamlit run app.py --browser.gatherUsageStats false --theme.base dark
pause
