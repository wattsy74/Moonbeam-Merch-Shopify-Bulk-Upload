@echo off
setlocal

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  py -m venv .venv
)

.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python shopify_bulk_upload.py %*
