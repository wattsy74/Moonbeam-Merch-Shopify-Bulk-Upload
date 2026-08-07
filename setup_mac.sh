#!/bin/zsh
# setup_mac.sh
# Installs Moonbeam Merch Uploader to /Applications/Moonbeam-Uploader
# and creates a desktop shortcut.

set -e

INSTALL_DIR="/Applications/Moonbeam-Uploader"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DESKTOP="$HOME/Desktop"
SHORTCUT="$DESKTOP/Moonbeam Merch Uploader.command"

REQUIRED_FILES=(
    "shopify_bulk_upload_graphql.py"
    "shopify_bulk_upload.py"
    "shopify_uploader_gui.py"
    "product_type_map.json"
    "color_hex_map.json"
    "requirements.txt"
    "run_gui_mac.command"
)

REQUIRED_DIRS=(
    "descriptors"
)

REQUIRED_DIRS=(
    "descriptors"
    "icons"
)

echo "======================================"
echo "  Moonbeam Merch Uploader — Mac Setup"
echo "======================================"
echo ""

# ── Create install directory ──────────────────────────────────────────────────
echo "Creating $INSTALL_DIR ..."
mkdir -p "$INSTALL_DIR"

# ── Copy required files ───────────────────────────────────────────────────────
echo "Copying files ..."
for f in "${REQUIRED_FILES[@]}"; do
    if [[ -f "$SCRIPT_DIR/$f" ]]; then
        cp "$SCRIPT_DIR/$f" "$INSTALL_DIR/$f"
        echo "  Copied $f"
    else
        echo "  WARNING: $f not found in $SCRIPT_DIR — skipping"
    fi
done

for d in "${REQUIRED_DIRS[@]}"; do
    if [[ -d "$SCRIPT_DIR/$d" ]]; then
        cp -R "$SCRIPT_DIR/$d" "$INSTALL_DIR/$d"
        echo "  Copied $d/"
    else
        echo "  WARNING: $d/ not found in $SCRIPT_DIR — skipping"
    fi
done

for d in "${REQUIRED_DIRS[@]}"; do
    if [[ -d "$SCRIPT_DIR/$d" ]]; then
        cp -R "$SCRIPT_DIR/$d" "$INSTALL_DIR/$d"
        echo "  Copied $d/"
    else
        echo "  WARNING: $d/ not found in $SCRIPT_DIR — skipping"
    fi
done

# ── Copy .env if present, otherwise copy .env.example ─────────────────────────
if [[ -f "$SCRIPT_DIR/.env" ]]; then
    cp "$SCRIPT_DIR/.env" "$INSTALL_DIR/.env"
    echo "  Copied .env"
elif [[ -f "$SCRIPT_DIR/.env.example" ]]; then
    cp "$SCRIPT_DIR/.env.example" "$INSTALL_DIR/.env"
    echo "  Copied .env.example -> .env  (edit this with your Shopify credentials)"
fi

# ── Find Python ───────────────────────────────────────────────────────────────
find_python() {
    for py in /opt/homebrew/opt/python@3.14/bin/python3.14 \
              /opt/homebrew/bin/python3 \
              /usr/local/bin/python3 \
              python3.14 python3.13 python3.12 python3.11 python3.10 python3; do
        if command -v "$py" >/dev/null 2>&1; then
            echo "$py"; return 0
        fi
    done
    echo ""
}

PY_BIN="$(find_python)"
if [[ -z "$PY_BIN" ]]; then
    echo ""
    echo "ERROR: Python 3 not found. Install it from https://python.org and re-run this script."
    exit 1
fi
echo ""
echo "Using Python: $PY_BIN ($($PY_BIN --version))"

# ── Create virtual environment ────────────────────────────────────────────────
echo ""
echo "Setting up virtual environment ..."
cd "$INSTALL_DIR"
"$PY_BIN" -m venv .venv
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet -r requirements.txt
echo "  Dependencies installed."

# ── Make launcher executable ──────────────────────────────────────────────────
chmod +x "$INSTALL_DIR/run_gui_mac.command"

# ── Create desktop shortcut ───────────────────────────────────────────────────
echo ""
echo "Creating desktop shortcut ..."
cat > "$SHORTCUT" <<'EOF'
#!/bin/zsh
cd /Applications/Moonbeam-Uploader
exec ./run_gui_mac.command
EOF
chmod +x "$SHORTCUT"
echo "  Shortcut created at: $SHORTCUT"

echo ""
echo "======================================"
echo "  Setup complete!"
echo "  Double-click 'Moonbeam Merch Uploader'"
echo "  on your Desktop to launch."
echo ""
echo "  Edit /Applications/Moonbeam-Uploader/.env"
echo "  with your Shopify credentials if not already set."
echo "======================================"
