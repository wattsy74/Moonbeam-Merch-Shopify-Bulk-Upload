# Moonbeam Merch Shopify Bulk Uploader — Setup Guide

## Required Files

Copy all of the following files to the same folder on the new machine:

### Core Application
| File | Purpose |
|------|---------|
| `shopify_bulk_upload_graphql.py` | Main upload engine |
| `shopify_bulk_upload.py` | Image parsing and grouping helpers |
| `shopify_uploader_gui.py` | GUI application |
| `product_type_map.json` | Maps image filenames to product types, prices, sizes, templates |
| `color_hex_map.json` | Maps colour names to hex values for swatch creation || `descriptors/` | HTML product description templates per shirt model |
| `icons/` | App icons || `.env` | Shopify API credentials (**do not share or commit this file**) |
| `requirements.txt` | Python package dependencies |

### Launchers
| File | Purpose |
|------|---------|
| `run_gui_mac.command` | Launch the GUI on macOS |
| `run_gui_windows.bat` | Launch the GUI on Windows |

---

## Setup Steps

### macOS

1. Install Python 3.11+ from [python.org](https://www.python.org) or via Homebrew:
   ```
   brew install python
   ```
2. Open Terminal, navigate to the folder:
   ```
   cd /path/to/folder
   ```
3. Create a virtual environment and install dependencies:
   ```
   python3 -m venv .venv
   .venv/bin/pip install -r requirements.txt
   ```
4. Make the launcher executable (first time only):
   ```
   chmod +x run_gui_mac.command
   ```
5. Double-click `run_gui_mac.command` to launch.

### Windows

1. Install Python 3.11+ from [python.org](https://www.python.org) — tick **"Add Python to PATH"** during install.
2. Open Command Prompt, navigate to the folder:
   ```
   cd C:\path\to\folder
   ```
3. Create a virtual environment and install dependencies:
   ```
   python -m venv .venv
   .venv\Scripts\pip install -r requirements.txt
   ```
4. Double-click `run_gui_windows.bat` to launch.

---

## Configuration

### `.env` file
Copy `.env.example` to `.env` and fill in your Shopify credentials:

```
SHOPIFY_SHOP_DOMAIN=yourstore.myshopify.com
SHOPIFY_API_VERSION=2026-07
SHOPIFY_ACCESS_TOKEN=your_admin_api_token
```

### `product_type_map.json`
Defines how image filenames are matched to product types, prices, sizes and Shopify templates. Edit this to add new product types.

### `color_hex_map.json`
Maps colour names (as they appear in filenames) to hex colour codes. Used when creating colour swatch metaobjects in Shopify for the first time. Edit this to fix or add colours. Existing Shopify metaobjects are **not** updated automatically — edit those directly in Shopify Admin → Settings → Custom data → Metaobjects.

---

## Theme Files (Shopify — not copied to machine)

These files live in your Shopify theme and must be updated there via **Online Store → Themes → Edit code**:

| Theme File | What was changed |
|------------|-----------------|
| `snippets/product-variant-options.liquid` | Added custom metaobject swatch colour lookup |
| `snippets/swatch-input.liquid` | Passes `custom_swatch_color` through to swatch renderer |
| `snippets/swatch.liquid` | Falls back to `custom_swatch_color` when no built-in swatch exists |

Reference copies of the modified theme files are in the repo as `*-IMPROVED.liquid` files.
