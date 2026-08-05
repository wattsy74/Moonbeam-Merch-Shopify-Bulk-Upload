#!/bin/zsh
# build_mac_app.sh
# Creates "Moonbeam Merch Uploader.app" in the project folder.
# Drag the resulting .app to your Dock or /Applications.

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_NAME="Moonbeam Merch Uploader"
APP_BUNDLE="$SCRIPT_DIR/$APP_NAME.app"
EXECUTABLE="$APP_BUNDLE/Contents/MacOS/MoonbeamMerchUploader"
RESOURCES="$APP_BUNDLE/Contents/Resources"

find_python() {
  for py in /opt/homebrew/bin/python3 /usr/local/bin/python3 python3.12 python3.11 python3.10 python3; do
    if command -v "$py" >/dev/null 2>&1; then
      echo "$py"; return 0
    fi
  done
  echo "python3"
}

PY_BIN="$(find_python)"

echo "Building $APP_NAME.app ..."

# ── Directory structure ─────────────────────────────────────────────────────
mkdir -p "$APP_BUNDLE/Contents/MacOS"
mkdir -p "$RESOURCES"

# ── Info.plist ───────────────────────────────────────────────────────────────
cat > "$APP_BUNDLE/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key>
  <string>Moonbeam Merch Uploader</string>
  <key>CFBundleDisplayName</key>
  <string>Moonbeam Merch Uploader</string>
  <key>CFBundleIdentifier</key>
  <string>com.moonbeam.merch.uploader</string>
  <key>CFBundleVersion</key>
  <string>1.0</string>
  <key>CFBundleShortVersionString</key>
  <string>1.0</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>CFBundleExecutable</key>
  <string>MoonbeamMerchUploader</string>
  <key>CFBundleIconFile</key>
  <string>AppIcon</string>
  <key>NSHighResolutionCapable</key>
  <true/>
  <key>NSRequiresAquaSystemAppearance</key>
  <false/>
</dict>
</plist>
PLIST

# ── Launcher executable ──────────────────────────────────────────────────────
cat > "$EXECUTABLE" <<LAUNCHER
#!/bin/zsh
# Resolve project directory from the .app bundle location
PROJ="\$(cd "\$(dirname "\$0")/../../../" && pwd)"
cd "\$PROJ"

find_python() {
  for py in /opt/homebrew/bin/python3 /usr/local/bin/python3 python3.12 python3.11 python3.10 python3; do
    command -v "\$py" >/dev/null 2>&1 && echo "\$py" && return 0
  done
  echo python3
}
PY_BIN="\$(find_python)"

export QT_QPA_PLATFORM=cocoa
export PATH="/opt/homebrew/bin:\$PATH"

if [[ -x /opt/homebrew/bin/brew ]]; then
  PY_SITE="\$("\$PY_BIN" -c 'import site; print(site.getusersitepackages())' 2>/dev/null)"
  if [[ -n "\$PY_SITE" && -d "\$PY_SITE/PySide6/Qt/plugins/platforms" ]]; then
    export QT_QPA_PLATFORM_PLUGIN_PATH="\$PY_SITE/PySide6/Qt/plugins/platforms:\${QT_QPA_PLATFORM_PLUGIN_PATH:-}"
  fi
fi

exec "\$PY_BIN" "\$PROJ/shopify_uploader_gui.py"
LAUNCHER

chmod +x "$EXECUTABLE"

# ── Icon ─────────────────────────────────────────────────────────────────────
echo "Generating icon ..."
"$PY_BIN" "$SCRIPT_DIR/create_icon.py" "$RESOURCES" && \
  echo "  Icon placed in $RESOURCES" || \
  echo "  (icon generation skipped — run: pip install Pillow, then re-run this script)"

# ── Done ─────────────────────────────────────────────────────────────────────
echo ""
echo "✓ Created: $APP_BUNDLE"
echo ""
echo "Next steps:"
echo "  • Drag '$APP_NAME.app' to your Dock"
echo "  • Or copy to /Applications for system-wide access"
echo "  • Or just double-click it from this folder"
