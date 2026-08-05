#!/bin/zsh
set -e

cd "$(dirname "$0")"

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi

if [[ $# -eq 0 ]]; then
  echo "No folder supplied; launching GUI instead..."
  exec ./run_gui_mac.command
fi

./.venv/bin/python -m pip install -r requirements.txt
./.venv/bin/python shopify_bulk_upload.py "$@"
