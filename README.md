# Shopify Bulk Product Creator (From Image Filenames)

Cross-platform Python script (macOS + Windows) that:
- Reads image files from a folder
- Parses filename parts into artwork/style/color
- Creates one product per artwork + product type
- Creates color variants within each product
- Uploads images and attaches each image to the matching variant

## Filename Format

Expected filename pattern (without extension):

`Artwork_PBM0_STTU169_C005_StyleCode_Color`

Example:

`Jessie_PBM0_STTU169_C005_Creator_2.0_CottonPink.png`

Rules implemented:
- `Artwork` can include `-` for multi-word names (example: `Jessie-Bear`)
- SKU is generated per image/variant as `PBM0_STTU169_C005-{Artwork}`
- `Creator_2.0` -> `Unisex T-Shirt`
- `Expresser_2.0` -> `Ladies Fitted T-Shirt`
- Product titles are always output in Title Case

Product type translation is editable in `product_type_map.json`.

## What The Script Creates

- One product per artwork + product type
- Variant option:
  - `Color`
- If an artwork has 10 colors and both styles, that becomes 2 products with 10 variants each.

## Setup

1. Install Python 3.9+.
2. In this folder:

```bash
pip install -r requirements.txt
```

3. Copy `.env.example` to `.env` and fill values:

- `SHOPIFY_SHOP_DOMAIN` (example: `my-shop.myshopify.com`)
- `SHOPIFY_API_VERSION` (default `2025-01`)
- OAuth settings:
  - `SHOPIFY_OAUTH_CLIENT_ID`
  - `SHOPIFY_OAUTH_CLIENT_SECRET`
  - `SHOPIFY_OAUTH_REDIRECT_URI` (recommended: `http://127.0.0.1:8787/callback`)
  - `SHOPIFY_OAUTH_SCOPES` (for example `read_products,write_products`)

Optional:
- `SHOPIFY_ACCESS_TOKEN` to skip interactive OAuth after your first successful auth.

4. Ensure your Shopify app has Admin API scopes for products (read/write).

5. Edit `product_type_map.json` whenever you add new product types from Photoshop export naming.

Example:

```json
{
  "Creator_2.0": {
    "label": "Unisex T-Shirt",
    "price": "24.99",
    "template_suffix": "clothing-template",
    "product_type": "T-Shirts",
    "description_file": "descriptors/tshirt_descriptor.html"
  },
  "Expresser_2.0": {
    "label": "Ladies Fitted T-Shirt",
    "price": "24.99",
    "template_suffix": "clothing-template",
    "product_type": "T-Shirts",
    "description": "Ladies fitted t-shirt with a flattering cut and soft cotton feel."
  },
  "Hoodie_3.0": {
    "label": "Unisex Hoodie",
    "price": "39.99",
    "template_suffix": "clothing-template",
    "product_type": "Hoodies",
    "description": "Warm unisex hoodie with a relaxed fit and soft brushed interior."
  },
  "TravelMug_1.0": {
    "label": "Travel Mug",
    "price": "19.99",
    "template_suffix": "drinkware-template",
    "product_type": "Drinkware",
    "description": "Insulated travel mug ideal for hot and cold drinks on the go."
  },
  "Keyring_1.0": {
    "label": "Keyring",
    "price": "9.99",
    "template_suffix": "accessory-template",
    "product_type": "Accessories",
    "description": "Durable keyring accessory featuring your artwork."
  }
}
```

Backward compatibility: a string value is still allowed (`"Creator_2.0": "Unisex T-Shirt"`) and will default price to `0.00`.

## Usage

```bash
python shopify_bulk_upload.py --folder "/path/to/output/images"
```

You can also pass the folder as the first positional argument:

```bash
python shopify_bulk_upload.py "/path/to/output/images"
```

Optional flags:

```bash
python shopify_bulk_upload.py \
  --folder "/path/to/output/images" \
  --description "Optional product description" \
  --product-type-map "./product_type_map.json" \
  --uploaded-dir "uploaded" \
  --vendor "Moonbeam Merch" \
  --dry-run
```

Optional global price override:

```bash
python shopify_bulk_upload.py --folder "/path/to/output/images" --price 24.99
```

If `--price` is omitted, each product type uses its `price` from `product_type_map.json`.

If `--description` is omitted, each product type uses its `description` from `product_type_map.json`.
If `--description` is provided, that value overrides mapped descriptions for all created products.
Descriptions support plain text or raw HTML.
You can also use `description_file` in the mapping to load HTML from a separate file.

After each successful image upload, the image file is moved to `uploaded` (inside the source folder) by default.
Use `--uploaded-dir` to change this destination. Absolute paths are supported.

- `--dry-run` previews parsing and grouping without creating anything in Shopify.

## OAuth Flow (When No Token Is Set)

If `SHOPIFY_ACCESS_TOKEN` is empty, the script will:
1. Print a Shopify OAuth authorization URL.
2. If redirect URI is localhost, open your browser and auto-capture the callback.
3. If auto-capture fails, ask you to paste the redirected URL (or just the `code`).
4. Exchange the code for an access token.
5. Continue the upload in the same run.

For auto-capture to work:
1. Add exactly the same callback URL in your Shopify app's Allowed redirection URL(s).
2. Set that exact value in `.env` as `SHOPIFY_OAUTH_REDIRECT_URI`.
3. Recommended value is `http://127.0.0.1:8787/callback`.

After success, the script prints a `SHOPIFY_ACCESS_TOKEN=...` line you can copy to `.env` so future runs are non-interactive.

## Simple Launchers

macOS:

```bash
./run_mac.command --folder "/path/to/output/images" --dry-run
```

Windows:

```bat
run_windows.bat --folder "C:\path\to\output\images" --dry-run
```

These launchers create `.venv` automatically (if missing), install dependencies, then run the uploader.

## Desktop Applet (No Command Line)

A cross-platform GUI app is included so you can run uploads without terminal commands.

macOS:

```bash
./run_gui_mac.command
```

Windows:

```bat
run_gui_windows.bat
```

The applet lets you:
1. Pick the folder to read.
2. Set dry-run, vendor, price override, description override, and uploaded folder.
3. Open a map editor to add/update/remove style mappings (`label`, `price`, `template_suffix`, `product_type`, `description` or `description_file`).
4. Run upload and watch live output in the app window.

Optional prefill flags:

```bash
./run_gui_mac.command --folder "/path/to/output/images" --product-type-map "./product_type_map.json"
```

```bat
run_gui_windows.bat --folder "C:\path\to\output\images" --product-type-map ".\product_type_map.json"
```

## Photoshop Post-Export Hook

If you want Photoshop exports to launch the uploader automatically, use [photoshop_post_export_hook.jsx](photoshop_post_export_hook.jsx).

In your export `.jsx` script:

```jsx
#include "photoshop_post_export_hook.jsx"

// ... your export logic ...
maybeLaunchShopifyUploaderGUI(true);
```

Notes:
1. Edit the repository path near the top of [photoshop_post_export_hook.jsx](photoshop_post_export_hook.jsx) if your folder lives elsewhere.
2. The hook launches [run_gui_mac.command](run_gui_mac.command) on macOS and [run_gui_windows.bat](run_gui_windows.bat) on Windows.
3. Set `maybeLaunchShopifyUploaderGUI(false)` to disable launching without removing the hook call.

## Notes

- Product title behavior: `{artwork} {product type}`
- Variant SKU is unique per color variant, using each filename's own `C###` segment.
- Product tags are auto-generated from filename parts + mapping label:
  - Artwork (Title Case)
  - `PBM0_STTU169` part
  - each `C###` code in the product group
  - each color label
  - mapped product type label
- Theme template can be assigned per product type with `template_suffix` (for example `clothing-template`).
- Product description can be assigned per product type with `description`.
- Shopify's native Product Type field can be assigned per product type with `product_type` (for example `T-Shirts`).

## Shopify API Limits

The script retries automatically on `429` rate-limit responses.

If Shopify returns `413 Payload Too Large` for an image upload, the script now automatically:
1. Resizes oversized images to a max dimension of 2400px.
2. Attempts optimized PNG when transparency exists.
3. Falls back to compressed JPEG and retries upload.
