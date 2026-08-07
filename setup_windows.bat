@echo off
setlocal EnableDelayedExpansion

REM setup_windows.bat
REM Installs Moonbeam Merch Uploader to C:\Program Files\Moonbeam-Uploader
REM and creates a desktop shortcut.

set "INSTALL_DIR=C:\Program Files\Moonbeam-Uploader"
set "SCRIPT_DIR=%~dp0"
set "DESKTOP=%USERPROFILE%\Desktop"
set "SHORTCUT=%DESKTOP%\Moonbeam Merch Uploader.bat"

echo ======================================
echo   Moonbeam Merch Uploader - Windows Setup
echo ======================================
echo.

REM ── Check for admin rights ────────────────────────────────────────────────
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo ERROR: This script must be run as Administrator.
    echo Right-click setup_windows.bat and choose "Run as administrator".
    pause
    exit /b 1
)

REM ── Create install directory ──────────────────────────────────────────────
echo Creating %INSTALL_DIR% ...
if not exist "%INSTALL_DIR%" mkdir "%INSTALL_DIR%"

REM ── Copy required files ───────────────────────────────────────────────────
echo Copying files ...
set FILES=shopify_bulk_upload_graphql.py shopify_bulk_upload.py shopify_uploader_gui.py product_type_map.json color_hex_map.json requirements.txt run_gui_windows.bat

for %%f in (%FILES%) do (
    if exist "%SCRIPT_DIR%%%f" (
        copy /Y "%SCRIPT_DIR%%%f" "%INSTALL_DIR%\%%f" >nul
        echo   Copied %%f
    ) else (
        echo   WARNING: %%f not found - skipping
    )
)

REM ── Copy .env ─────────────────────────────────────────────────────────────
if exist "%SCRIPT_DIR%.env" (
    copy /Y "%SCRIPT_DIR%.env" "%INSTALL_DIR%\.env" >nul
    echo   Copied .env
) else if exist "%SCRIPT_DIR%.env.example" (
    copy /Y "%SCRIPT_DIR%.env.example" "%INSTALL_DIR%\.env" >nul
    echo   Copied .env.example -^> .env  ^(edit this with your Shopify credentials^)
)

REM ── Find Python ───────────────────────────────────────────────────────────
echo.
echo Looking for Python ...
set PYTHON=
for %%p in (py python3 python) do (
    if "!PYTHON!"=="" (
        %%p --version >nul 2>&1 && set "PYTHON=%%p"
    )
)

if "!PYTHON!"=="" (
    echo ERROR: Python 3 not found. Install it from https://python.org
    echo        Make sure to tick "Add Python to PATH" during install.
    pause
    exit /b 1
)

for /f "tokens=*" %%v in ('!PYTHON! --version 2^>^&1') do echo Using: %%v

REM ── Create virtual environment ────────────────────────────────────────────
echo.
echo Setting up virtual environment ...
cd /d "%INSTALL_DIR%"
!PYTHON! -m venv .venv
.venv\Scripts\pip install --quiet --upgrade pip
.venv\Scripts\pip install --quiet -r requirements.txt
echo   Dependencies installed.

REM ── Create desktop shortcut (.bat launcher) ───────────────────────────────
echo.
echo Creating desktop shortcut ...
(
    echo @echo off
    echo cd /d "C:\Program Files\Moonbeam-Uploader"
    echo call run_gui_windows.bat
) > "%SHORTCUT%"
echo   Shortcut created at: %SHORTCUT%

REM ── Also create a .vbs wrapper so it launches without a console window ─────
set "VBS_SHORTCUT=%DESKTOP%\Moonbeam Merch Uploader.vbs"
(
    echo Set WshShell = CreateObject^("WScript.Shell"^)
    echo WshShell.Run """C:\Program Files\Moonbeam-Uploader\run_gui_windows.bat""", 0, False
) > "%VBS_SHORTCUT%"
echo   Silent launcher created at: %VBS_SHORTCUT%

echo.
echo ======================================
echo   Setup complete!
echo   Double-click 'Moonbeam Merch Uploader'
echo   on your Desktop to launch.
echo.
echo   Edit C:\Program Files\Moonbeam-Uploader\.env
echo   with your Shopify credentials if not already set.
echo ======================================
pause
