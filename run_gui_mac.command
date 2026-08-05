#!/bin/zsh
set -e

cd "$(dirname "$0")"

find_python() {
  for py in /opt/homebrew/bin/python3 /usr/local/bin/python3 python3.12 python3.11 python3.10 python3; do
    if [[ -n "$py" ]] && command -v "$py" >/dev/null 2>&1; then
      echo "$py"
      return 0
    fi
  done
  return 1
}

PY_BIN="$(find_python)"
if [[ -z "$PY_BIN" ]]; then
  echo "Unable to find a Python interpreter." >&2
  exit 1
fi

export TK_SILENCE_DEPRECATION=1

if [[ -x /opt/homebrew/bin/brew ]]; then
  export PATH="/opt/homebrew/bin:$PATH"
fi

"$PY_BIN" -m pip install --user --break-system-packages -r requirements.txt

if [[ -n "$(command -v brew 2>/dev/null)" ]]; then
  brew list pyside >/dev/null 2>&1 || brew install pyside
fi

export QT_QPA_PLATFORM=cocoa
export QT_PLUGIN_PATH="/opt/homebrew/lib/qt/plugins:${QT_PLUGIN_PATH:-}"
export QT_QPA_PLATFORM_PLUGIN_PATH="/opt/homebrew/lib/qt/plugins/platforms:${QT_QPA_PLATFORM_PLUGIN_PATH:-}"
export DYLD_FALLBACK_LIBRARY_PATH="/opt/homebrew/lib/qt/lib:${DYLD_FALLBACK_LIBRARY_PATH:-}"
export DYLD_FRAMEWORK_PATH="/opt/homebrew/lib/qt/lib:${DYLD_FRAMEWORK_PATH:-}"

if [[ "$PY_BIN" == /opt/homebrew/bin/python3* ]] || [[ "$PY_BIN" == /usr/local/bin/python3* ]] || [[ "$PY_BIN" == python3* ]]; then
  PY_SITE_PACKAGES="$($PY_BIN - <<'PY'
import site, sys
print(site.getusersitepackages())
PY
)"
else
  PY_SITE_PACKAGES=""
fi

if [[ -n "$PY_SITE_PACKAGES" && -d "$PY_SITE_PACKAGES/PySide6/Qt/plugins/platforms" ]]; then
  export QT_QPA_PLATFORM_PLUGIN_PATH="$PY_SITE_PACKAGES/PySide6/Qt/plugins/platforms:${QT_QPA_PLATFORM_PLUGIN_PATH:-}"
fi

echo "Launching GUI with: $($PY_BIN -V)"
echo "Launcher path: $PWD/run_gui_mac.command"
echo "GUI script: $PWD/shopify_uploader_gui.py"

echo "Qt plugin path: $QT_QPA_PLATFORM_PLUGIN_PATH"

"$PY_BIN" shopify_uploader_gui.py "$@"
