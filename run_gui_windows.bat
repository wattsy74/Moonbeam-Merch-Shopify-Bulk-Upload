@echo off
setlocal

cd /d "%~dp0"

echo Moonbeam Merch Uploader - Starting...
echo.

REM Find Python 3 (try py launcher first, then python/python3 directly)
set PYTHON=
where py >nul 2>&1 && set PYTHON=py
if "%PYTHON%"=="" where python >nul 2>&1 && set PYTHON=python
if "%PYTHON%"=="" where python3 >nul 2>&1 && set PYTHON=python3

if "%PYTHON%"=="" (
  echo ERROR: Python 3 not found.
  echo Please install Python 3.11 or later from https://python.org/downloads/
  echo Make sure to check "Add Python to PATH" during installation.
  echo.
  pause
  exit /b 1
)

REM Verify Python version is 3.x
%PYTHON% -c "import sys; assert sys.version_info >= (3,10), 'Python 3.10+ required'" 2>nul
if errorlevel 1 (
  echo ERROR: Python 3.10 or later is required.
  echo Please install a newer version from https://python.org/downloads/
  echo.
  pause
  exit /b 1
)

REM Create virtual environment if missing
if not exist ".venv\Scripts\python.exe" (
  echo Setting up virtual environment...
  %PYTHON% -m venv .venv
  if errorlevel 1 (
    echo ERROR: Failed to create virtual environment.
    pause
    exit /b 1
  )
)

REM Install/update dependencies
echo Checking dependencies...
.venv\Scripts\python -m pip install --quiet --upgrade pip
.venv\Scripts\python -m pip install --quiet -r requirements.txt
if errorlevel 1 (
  echo ERROR: Failed to install dependencies.
  echo Check your internet connection and try again.
  pause
  exit /b 1
)

echo Starting Moonbeam Merch Uploader...
echo.

REM Launch GUI (use start to detach so this window can close)
start "" .venv\Scripts\pythonw.exe shopify_uploader_gui.py %*
