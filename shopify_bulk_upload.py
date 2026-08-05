#!/usr/bin/env python3
import argparse
import base64
import html
import http.server
import io
import json
import os
import re
import secrets
import shutil
import sys
import time
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import parse_qs, quote, urlparse

try:
    from dotenv import load_dotenv
    from PIL import Image
    import requests
except ModuleNotFoundError:
    print("Missing dependencies: python-dotenv, Pillow and/or requests")
    print("Use the project virtual environment to run this script.")
    print("macOS/Linux:")
    print("  python3 -m venv .venv")
    print("  ./.venv/bin/python -m pip install -r requirements.txt")
    print("  ./.venv/bin/python shopify_bulk_upload.py --folder \"/path/to/images\"")
    print("Windows:")
    print("  py -m venv .venv")
    print("  .venv\\Scripts\\python -m pip install -r requirements.txt")
    print("  .venv\\Scripts\\python shopify_bulk_upload.py --folder \"C:\\path\\to\\images\"")
    sys.exit(1)

DEFAULT_PRODUCT_TYPE_MAP = {
    "Creator_2.0": "Unisex T-Shirt",
    "Expresser_2.0": "Ladies Fitted T-Shirt",
}

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
MAX_UPLOAD_IMAGE_BYTES = 4_500_000


@dataclass
class ProductTypeConfig:
    label: str
    price: str
    template_suffix: Optional[str]
    product_type: Optional[str]
    description: Optional[str]
    sizes: Optional[List[str]]


@dataclass
class ParsedImage:
    file_path: Path
    artwork_raw: str
    artwork_display: str
    code_ab: str
    code_c: str
    sku: str
    style_code: str
    style_label: str
    style_price: str
    style_template_suffix: Optional[str]
    style_product_type: Optional[str]
    style_description: Optional[str]
    style_sizes: Optional[List[str]]
    color_raw: str
    color_display: str


class ShopifyClient:
    def __init__(self, shop_domain: str, access_token: str, api_version: str) -> None:
        self.base_url = f"https://{shop_domain}/admin/api/{api_version}"
        self.session = requests.Session()
        self.session.headers.update(
            {
                "X-Shopify-Access-Token": access_token,
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
        )

    def _request(self, method: str, endpoint: str, json_data: Optional[dict] = None) -> dict:
        url = f"{self.base_url}{endpoint}"

        for attempt in range(6):
            resp = self.session.request(method=method, url=url, json=json_data, timeout=60)

            if resp.status_code == 429:
                wait_seconds = int(resp.headers.get("Retry-After", "2"))
                time.sleep(max(wait_seconds, 1))
                continue

            if resp.status_code >= 400:
                raise RuntimeError(
                    f"Shopify API error {resp.status_code} on {method} {endpoint}: {resp.text}"
                )

            if not resp.text:
                return {}
            return resp.json()

        raise RuntimeError(f"Rate-limit retries exceeded for {method} {endpoint}")

    def create_product(
        self,
        title: str,
        body_html: str,
        vendor: Optional[str],
        tags: str,
        template_suffix: Optional[str],
        product_type: Optional[str],
        variants: List[dict],
        publish_status: Optional[str] = None,
        sizes: Optional[List[str]] = None,
    ) -> dict:
        options = [{"name": "Color"}]
        if sizes:
            options.append({"name": "Size"})
        payload = {
            "product": {
                "title": title,
                "body_html": body_html,
                "options": options,
                "tags": tags,
                "variants": variants,
            }
        }
        if publish_status:
            payload["product"]["status"] = publish_status
        if vendor:
            payload["product"]["vendor"] = vendor
        if template_suffix:
            payload["product"]["template_suffix"] = template_suffix
        if product_type:
            payload["product"]["product_type"] = product_type

        return self._request("POST", "/products.json", json_data=payload)["product"]

    def _upload_product_image_bytes(
        self,
        product_id: int,
        image_bytes: bytes,
        filename: str,
        alt_text: str,
    ) -> dict:
        encoded = base64.b64encode(image_bytes).decode("ascii")
        payload = {
            "image": {
                "attachment": encoded,
                "filename": filename,
                "alt": alt_text,
            }
        }
        return self._request("POST", f"/products/{product_id}/images.json", json_data=payload)["image"]

    def upload_product_image(self, product_id: int, file_path: Path, alt_text: str) -> dict:
        original_bytes = file_path.read_bytes()

        try:
            return self._upload_product_image_bytes(
                product_id=product_id,
                image_bytes=original_bytes,
                filename=file_path.name,
                alt_text=alt_text,
            )
        except RuntimeError as exc:
            # Shopify can reject very large base64 payloads with HTTP 413.
            if " 413 " not in str(exc):
                raise

        optimized_bytes, optimized_filename = optimize_image_for_upload(
            file_path=file_path,
            max_bytes=MAX_UPLOAD_IMAGE_BYTES,
        )
        print(
            "  Image too large for direct upload; retrying optimized version "
            f"for '{file_path.name}' ({len(original_bytes)} -> {len(optimized_bytes)} bytes)"
        )

        return self._upload_product_image_bytes(
            product_id=product_id,
            image_bytes=optimized_bytes,
            filename=optimized_filename,
            alt_text=alt_text,
        )

    def set_variant_image(self, variant_id: int, image_id: int) -> dict:
        payload = {
            "variant": {
                "id": variant_id,
                "image_id": image_id,
            }
        }
        return self._request("PUT", f"/variants/{variant_id}.json", json_data=payload)["variant"]


def build_oauth_authorize_url(
    shop_domain: str,
    client_id: str,
    scopes_csv: str,
    redirect_uri: str,
    state: str,
) -> str:
    scopes_encoded = quote(scopes_csv, safe=",")
    redirect_encoded = quote(redirect_uri, safe=":/")
    return (
        f"https://{shop_domain}/admin/oauth/authorize"
        f"?client_id={quote(client_id)}"
        f"&scope={scopes_encoded}"
        f"&redirect_uri={redirect_encoded}"
        f"&state={quote(state)}"
    )


def extract_code_and_state(code_or_redirect_url: str) -> Tuple[str, Optional[str]]:
    raw = code_or_redirect_url.strip()
    if not raw:
        raise ValueError("No OAuth code input provided")

    # Support either raw code or full redirected URL.
    if raw.startswith("http://") or raw.startswith("https://"):
        parsed = urlparse(raw)
        query = parse_qs(parsed.query)
        code = query.get("code", [""])[0]
        state = query.get("state", [None])[0]
        if not code:
            raise ValueError("Redirect URL does not contain a 'code' query parameter")
        return code, state

    return raw, None


def is_localhost_redirect(redirect_uri: str) -> bool:
    try:
        parsed = urlparse(redirect_uri)
    except Exception:
        return False

    return parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost"}


def wait_for_oauth_callback(redirect_uri: str, timeout_seconds: int = 180) -> Tuple[str, Optional[str]]:
    parsed = urlparse(redirect_uri)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise ValueError("Redirect URI must be http://localhost or http://127.0.0.1 for auto-capture")

    callback_path = parsed.path or "/"
    callback_host = parsed.hostname
    callback_port = parsed.port or 80
    captured: Dict[str, Optional[str]] = {"code": None, "state": None, "error": None}

    class OAuthCallbackHandler(http.server.BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            return

        def do_GET(self) -> None:
            req = urlparse(self.path)
            if req.path != callback_path:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"Not found")
                return

            query = parse_qs(req.query)
            captured["code"] = query.get("code", [None])[0]
            captured["state"] = query.get("state", [None])[0]
            captured["error"] = query.get("error", [None])[0]

            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                b"<html><body><h2>Authorization received.</h2><p>You can close this window.</p></body></html>"
            )

    server = http.server.HTTPServer((callback_host, callback_port), OAuthCallbackHandler)
    server.timeout = 1
    end_time = time.time() + timeout_seconds

    try:
        while time.time() < end_time:
            server.handle_request()
            if captured["error"]:
                raise RuntimeError(f"Shopify OAuth returned error: {captured['error']}")
            if captured["code"]:
                return str(captured["code"]), captured["state"]
    finally:
        server.server_close()

    raise TimeoutError("Timed out waiting for OAuth callback on localhost")


def optimize_image_for_upload(file_path: Path, max_bytes: int) -> Tuple[bytes, str]:
    with Image.open(file_path) as src:
        image = src.copy()

    # Limit dimensions for high-resolution Photoshop exports.
    max_dimension = 2400
    if max(image.size) > max_dimension:
        image.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)

    output = io.BytesIO()

    # Preserve transparency when present, otherwise prefer compressed JPEG.
    has_alpha = image.mode in ("RGBA", "LA") or (
        image.mode == "P" and "transparency" in image.info
    )

    if has_alpha:
        image.save(output, format="PNG", optimize=True)
        png_bytes = output.getvalue()
        if len(png_bytes) <= max_bytes:
            return png_bytes, f"{file_path.stem}.png"
        # If still too large, flatten onto white and continue with JPEG fallback.
        background = Image.new("RGB", image.size, (255, 255, 255))
        background.paste(image, mask=image.split()[-1])
        image = background
    elif image.mode != "RGB":
        image = image.convert("RGB")

    for quality in (88, 82, 76, 70, 64, 58, 52):
        output = io.BytesIO()
        image.save(output, format="JPEG", quality=quality, optimize=True)
        jpg_bytes = output.getvalue()
        if len(jpg_bytes) <= max_bytes:
            return jpg_bytes, f"{file_path.stem}.jpg"

    # Return best-effort smallest JPEG if strict size target is not achieved.
    return jpg_bytes, f"{file_path.stem}.jpg"


def format_color_label(color_raw: str) -> str:
    base = color_raw.replace("-", " ").replace("_", " ").strip()
    parts = base.split()
    spaced_parts = [re.sub(r"(?<!^)(?=[A-Z])", " ", part) for part in parts]
    return " ".join(" ".join(spaced_parts).split())


def to_title_case(text: str) -> str:
    return text.title()


def exchange_oauth_code_for_token(
    shop_domain: str,
    client_id: str,
    client_secret: str,
    code: str,
) -> str:
    endpoint = f"https://{shop_domain}/admin/oauth/access_token"
    payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
    }
    resp = requests.post(endpoint, json=payload, timeout=60)
    if resp.status_code >= 400:
        body = resp.text
        hint = ""
        if "Missing or invalid client secret" in body:
            hint = (
                "\nHint: SHOPIFY_OAUTH_CLIENT_SECRET is invalid for this app, "
                "or does not match the app tied to SHOPIFY_OAUTH_CLIENT_ID."
            )
        raise RuntimeError(
            f"OAuth token exchange failed ({resp.status_code}): {body}{hint}"
        )

    data = resp.json()
    token = data.get("access_token", "")
    if not token:
        raise RuntimeError("OAuth response did not include access_token")
    return token


def get_access_token(shop_domain: str) -> str:
    existing = os.getenv("SHOPIFY_ACCESS_TOKEN", "").strip()
    if existing:
        return existing

    client_id = os.getenv("SHOPIFY_OAUTH_CLIENT_ID", "").strip()
    client_secret = os.getenv("SHOPIFY_OAUTH_CLIENT_SECRET", "").strip()
    scopes = os.getenv("SHOPIFY_OAUTH_SCOPES", "read_products,write_products").strip()
    redirect_uri = os.getenv("SHOPIFY_OAUTH_REDIRECT_URI", "").strip()

    if not client_id or not client_secret or not redirect_uri:
        raise ValueError(
            "Missing Shopify auth config. Set SHOPIFY_ACCESS_TOKEN or OAuth variables: "
            "SHOPIFY_OAUTH_CLIENT_ID, SHOPIFY_OAUTH_CLIENT_SECRET, SHOPIFY_OAUTH_REDIRECT_URI"
        )

    if client_id == client_secret:
        raise ValueError(
            "SHOPIFY_OAUTH_CLIENT_ID and SHOPIFY_OAUTH_CLIENT_SECRET are identical. "
            "This is usually a misconfiguration. Copy the real API key and API secret key "
            "from the same Shopify app into .env."
        )

    state = secrets.token_urlsafe(16)
    auth_url = build_oauth_authorize_url(
        shop_domain=shop_domain,
        client_id=client_id,
        scopes_csv=scopes,
        redirect_uri=redirect_uri,
        state=state,
    )

    print("\nNo SHOPIFY_ACCESS_TOKEN found.")
    print("Complete OAuth once, then this run will continue automatically.")
    print("OAuth URL:")
    print(auth_url)

    code: str
    returned_state: Optional[str]
    if is_localhost_redirect(redirect_uri):
        print("\nStarting local callback listener for OAuth...")
        print(f"Listening on: {redirect_uri}")
        print("Opening browser for authorization...")
        opened = webbrowser.open(auth_url)
        if not opened:
            print("Could not auto-open browser. Please open the OAuth URL manually.")

        try:
            code, returned_state = wait_for_oauth_callback(redirect_uri)
            print("OAuth callback received automatically.")
        except Exception as exc:
            print(f"Automatic OAuth capture failed: {exc}")
            print("Falling back to manual paste mode.")
            print("Paste the full redirected URL (or just the code) below.")
            user_input = input("OAuth redirect URL or code: ").strip()
            code, returned_state = extract_code_and_state(user_input)
    else:
        print("\nRedirect URI is not localhost; using manual paste mode.")
        print("1) Open this URL in your browser and approve the app:")
        print(auth_url)
        print("2) Paste the full redirected URL (or just the code) below.")
        user_input = input("OAuth redirect URL or code: ").strip()
        code, returned_state = extract_code_and_state(user_input)

    if returned_state is not None and returned_state != state:
        raise RuntimeError("OAuth state mismatch. Please retry authorization.")

    token = exchange_oauth_code_for_token(
        shop_domain=shop_domain,
        client_id=client_id,
        client_secret=client_secret,
        code=code,
    )

    print("\nOAuth token retrieved successfully.")
    print("Add this to your .env for future runs:")
    print(f"SHOPIFY_ACCESS_TOKEN={token}")
    return token


def parse_filename(file_path: Path, product_type_map: Dict[str, ProductTypeConfig]) -> ParsedImage:
    stem = file_path.stem
    parts = stem.split("_")
    if len(parts) < 6:
        raise ValueError(
            f"Filename '{file_path.name}' does not match expected format: "
            "Artwork_PBM0_STTU169_C005_StyleCode_Color"
        )

    artwork_raw = parts[0]
    code_a, code_b, code_c = parts[1], parts[2], parts[3]
    remaining = parts[4:]

    style_code = None
    color_raw = ""
    for candidate in sorted(product_type_map.keys(), key=lambda s: len(s.split("_")), reverse=True):
        candidate_tokens = candidate.split("_")
        if remaining[: len(candidate_tokens)] == candidate_tokens:
            style_code = candidate
            color_raw = "_".join(remaining[len(candidate_tokens) :])
            break

    if not style_code:
        raise ValueError(
            f"Unknown style code in '{file_path.name}'. "
            f"Supported: {', '.join(product_type_map.keys())}"
        )

    if not color_raw:
        raise ValueError(f"Missing color segment in '{file_path.name}'")

    style_config = product_type_map[style_code]
    style_label = to_title_case(style_config.label)
    style_price = style_config.price
    style_template_suffix = style_config.template_suffix
    style_product_type = style_config.product_type
    style_description = style_config.description
    style_sizes = style_config.sizes

    sku = f"{code_a}_{code_b}_{code_c}-{artwork_raw}"
    artwork_display = to_title_case(artwork_raw.replace("-", " ").strip())
    code_ab = f"{code_a}_{code_b}"
    color_display = format_color_label(color_raw)

    return ParsedImage(
        file_path=file_path,
        artwork_raw=artwork_raw,
        artwork_display=artwork_display,
        code_ab=code_ab,
        code_c=code_c,
        sku=sku,
        style_code=style_code,
        style_label=style_label,
        style_price=style_price,
        style_template_suffix=style_template_suffix,
        style_product_type=style_product_type,
        style_description=style_description,
        style_sizes=style_sizes,
        color_raw=color_raw,
        color_display=color_display,
    )


def collect_images(folder: Path, product_type_map: Dict[str, ProductTypeConfig]) -> List[ParsedImage]:
    if not folder.exists() or not folder.is_dir():
        raise ValueError(f"Folder does not exist or is not a directory: {folder}")

    parsed: List[ParsedImage] = []
    for item in sorted(folder.iterdir()):
        if not item.is_file():
            continue
        if item.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        parsed.append(parse_filename(item, product_type_map))

    if not parsed:
        raise ValueError(f"No supported images found in folder: {folder}")

    return parsed


def build_groups(parsed_images: List[ParsedImage]) -> Dict[Tuple[str, str], List[ParsedImage]]:
    groups: Dict[Tuple[str, str], List[ParsedImage]] = {}
    for image in parsed_images:
        key = (image.artwork_raw, image.style_label)
        groups.setdefault(key, []).append(image)

    # Prevent duplicate colors inside the same artwork + product type group.
    for group_key, images in groups.items():
        seen: set[str] = set()
        seen_skus: set[str] = set()
        for img in images:
            color_key = img.color_display
            if color_key in seen:
                raise ValueError(
                    "Duplicate color variant found for group "
                    f"'{group_key[0]} / {group_key[1]}': color='{img.color_display}'"
                )
            seen.add(color_key)

            if img.sku in seen_skus:
                raise ValueError(
                    "Duplicate SKU found inside group "
                    f"'{group_key[0]} / {group_key[1]}': sku='{img.sku}'"
                )
            seen_skus.add(img.sku)

    return groups


def make_body_html(description: Optional[str]) -> str:
    if not description:
        return ""
    cleaned = description.strip()
    # If user provides HTML, pass it through unchanged so Shopify renders it.
    if "<" in cleaned and ">" in cleaned:
        return cleaned

    escaped = html.escape(cleaned).replace("\n", "<br>")
    return f"<p>{escaped}</p>"


def choose_title(images: List[ParsedImage]) -> str:
    artwork = images[0].artwork_display
    style = images[0].style_label
    return to_title_case(f"{artwork} {style}")


def load_product_type_map(path: Path) -> Dict[str, ProductTypeConfig]:
    if not path.exists() or not path.is_file():
        raise ValueError(f"Product type map file does not exist: {path}")

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in product type map '{path}': {exc}") from exc

    if not isinstance(data, dict) or not data:
        raise ValueError("Product type map must be a non-empty JSON object")

    parsed: Dict[str, ProductTypeConfig] = {}
    for key, value in data.items():
        if not isinstance(key, str) or not key.strip():
            raise ValueError("Each product type map key must be a non-empty string")

        style_code = key.strip()
        if isinstance(value, str):
            label = value.strip()
            if not label:
                raise ValueError(
                    f"Product type label for '{key}' must be a non-empty string"
                )
            parsed[style_code] = ProductTypeConfig(
                label=label,
                price="0.00",
                template_suffix=None,
                product_type=None,
                description=None,
                sizes=None,
            )
            continue

        if not isinstance(value, dict):
            raise ValueError(
                f"Value for '{key}' must be a string or object with 'label' and optional metadata"
            )

        label_raw = value.get("label", "")
        price_raw = value.get("price", "0.00")
        template_suffix_raw = value.get("template_suffix", None)
        product_type_raw = value.get("product_type", None)
        description_raw = value.get("description", None)
        description_file_raw = value.get("description_file", None)
        sizes_raw = value.get("sizes", None)
        if not isinstance(label_raw, str) or not label_raw.strip():
            raise ValueError(f"Product type label for '{key}' must be a non-empty string")
        if not isinstance(price_raw, str) or not price_raw.strip():
            raise ValueError(f"Product type price for '{key}' must be a non-empty string")
        if template_suffix_raw is not None and (
            not isinstance(template_suffix_raw, str) or not template_suffix_raw.strip()
        ):
            raise ValueError(
                f"Product type template_suffix for '{key}' must be a non-empty string when provided"
            )
        if product_type_raw is not None and (
            not isinstance(product_type_raw, str) or not product_type_raw.strip()
        ):
            raise ValueError(
                f"Product type product_type for '{key}' must be a non-empty string when provided"
            )
        if description_raw is not None and (
            not isinstance(description_raw, str) or not description_raw.strip()
        ):
            raise ValueError(
                f"Product type description for '{key}' must be a non-empty string when provided"
            )
        if description_file_raw is not None and (
            not isinstance(description_file_raw, str) or not description_file_raw.strip()
        ):
            raise ValueError(
                f"Product type description_file for '{key}' must be a non-empty string when provided"
            )
        if description_raw is not None and description_file_raw is not None:
            raise ValueError(
                f"Product type '{key}' cannot define both description and description_file"
            )

        resolved_description: Optional[str] = None
        if isinstance(description_raw, str):
            resolved_description = description_raw.strip()
        elif isinstance(description_file_raw, str):
            description_file_path = Path(description_file_raw.strip())
            if not description_file_path.is_absolute():
                description_file_path = path.parent / description_file_path
            if not description_file_path.exists() or not description_file_path.is_file():
                raise ValueError(
                    f"Description file for '{key}' does not exist: {description_file_path}"
                )
            resolved_description = description_file_path.read_text(encoding="utf-8").strip()

        parsed[style_code] = ProductTypeConfig(
            label=label_raw.strip(),
            price=price_raw.strip(),
            template_suffix=(template_suffix_raw.strip() if isinstance(template_suffix_raw, str) else None),
            product_type=(product_type_raw.strip() if isinstance(product_type_raw, str) else None),
            description=resolved_description,
            sizes=([s.strip() for s in sizes_raw.split(",") if s.strip()] if isinstance(sizes_raw, str) else None),
        )

    return parsed


def build_product_tags(images: List[ParsedImage]) -> str:
    tags: set[str] = set()
    tags.add(images[0].artwork_display)
    tags.add(images[0].code_ab)
    tags.add(images[0].style_label)

    for img in images:
        tags.add(img.code_c)
        tags.add(img.color_display)

    return ", ".join(sorted(tags, key=lambda t: t.lower()))


def move_uploaded_file(file_path: Path, uploaded_dir: Path) -> Path:
    uploaded_dir.mkdir(parents=True, exist_ok=True)
    target = uploaded_dir / file_path.name

    if not target.exists():
        shutil.move(str(file_path), str(target))
        return target

    stem = file_path.stem
    suffix = file_path.suffix
    counter = 1
    while True:
        candidate = uploaded_dir / f"{stem}_{counter}{suffix}"
        if not candidate.exists():
            shutil.move(str(file_path), str(candidate))
            return candidate
        counter += 1


def create_products(
    client: ShopifyClient,
    groups: Dict[Tuple[str, str], List[ParsedImage]],
    description: Optional[str],
    price_override: Optional[str],
    vendor: Optional[str],
    uploaded_dir: Path,
    dry_run: bool,
    publish_status: str,
    sizes: Optional[List[str]] = None,
) -> None:
    total_products = len(groups)
    created = 0

    for (artwork, style_label), images in sorted(groups.items(), key=lambda i: (i[0][0], i[0][1])):
        title = choose_title(images)
        tags = build_product_tags(images)
        template_suffix = images[0].style_template_suffix
        product_type = images[0].style_product_type
        effective_description = description if description else images[0].style_description
        body_html = make_body_html(effective_description)
        # sizes arg overrides map; fall back to map's sizes
        effective_sizes = sizes if sizes is not None else images[0].style_sizes

        variants_payload = []
        for img in sorted(images, key=lambda i: i.color_display):
            variant_price = price_override if price_override else img.style_price
            if effective_sizes:
                for size in effective_sizes:
                    variants_payload.append(
                        {
                            "option1": img.color_display,
                            "option2": size,
                            "sku": f"{img.sku}-{size.replace(' ', '-')}",
                            "price": variant_price,
                        }
                    )
            else:
                variants_payload.append(
                    {
                        "option1": img.color_display,
                        "sku": img.sku,
                        "price": variant_price,
                    }
                )

        print(f"\nArtwork: {artwork}")
        print(f"  Product type: {style_label}")
        print(f"  Product title: {title}")
        if template_suffix:
            print(f"  Template suffix: {template_suffix}")
        if product_type:
            print(f"  Shopify product_type: {product_type}")
        if effective_description:
            preview = body_html[:120].replace("\n", " ")
            print(f"  Description: {preview}{'...' if len(body_html) > 120 else ''}")
        print(f"  Tags: {tags}")
        sku_preview = sorted({img.sku for img in images})
        print(f"  SKU range: {sku_preview[0]} ... {sku_preview[-1]}")
        print(f"  Variants: {len(variants_payload)}")

        if dry_run:
            if effective_sizes:
                print(f"  Sizes: {', '.join(effective_sizes)} (from {'--sizes override' if sizes else 'map'})")
            for v in variants_payload:
                size_part = f" / Size={v['option2']}" if 'option2' in v else ""
                print(f"    - {v['option1']}{size_part} / SKU={v['sku']} / Price={v['price']}")
            continue

        product = client.create_product(
            title=title,
            body_html=body_html,
            vendor=vendor,
            tags=tags,
            template_suffix=template_suffix,
            product_type=product_type,
            variants=variants_payload,
            publish_status=publish_status,
            sizes=effective_sizes,
        )

        product_id = product["id"]
        variant_lookup: Dict[str, int] = {}
        for variant in product.get("variants", []):
            # Key by color alone (no sizes) or color+size tuple
            if effective_sizes:
                key = (variant.get("option1", ""), variant.get("option2", ""))
            else:
                key = variant.get("option1", "")
            variant_lookup[key] = variant["id"]

        print(f"  Created Shopify product ID: {product_id}")

        for img in images:
            uploaded = client.upload_product_image(
                product_id=product_id,
                file_path=img.file_path,
                alt_text=f"{img.artwork_display} - {img.style_label} - {img.color_display}",
            )
            image_id = uploaded["id"]
            # With sizes, link to the first size variant for each color
            if effective_sizes:
                variant_key = (img.color_display, effective_sizes[0])
            else:
                variant_key = img.color_display
            variant_id = variant_lookup.get(variant_key)

            if variant_id:
                client.set_variant_image(variant_id=variant_id, image_id=image_id)
                print(
                    "  Uploaded and linked image "
                    f"'{img.file_path.name}' -> variant {variant_id}"
                )
            else:
                print(
                    "  Uploaded image but no matching variant found for "
                    f"'{img.file_path.name}'"
                )

            moved_to = move_uploaded_file(img.file_path, uploaded_dir)
            print(f"  Moved uploaded file -> '{moved_to}'")

        created += 1

    print("\nDone")
    if dry_run:
        print(f"Dry-run complete. Products previewed: {total_products}")
    else:
        print(f"Products created: {created}/{total_products}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create Shopify products + variants from image filenames."
    )
    parser.add_argument(
        "folder_positional",
        nargs="?",
        help="Folder containing generated images (positional fallback)",
    )
    parser.add_argument(
        "--folder",
        default=None,
        help="Folder containing generated images",
    )
    parser.add_argument(
        "--description",
        default=None,
        help="Optional description text added to all created products",
    )
    parser.add_argument(
        "--price",
        default=None,
        help="Optional override price for all variants (otherwise uses mapping table price)",
    )
    parser.add_argument(
        "--vendor",
        default=None,
        help="Optional Shopify product vendor",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview parsing/grouping without creating products in Shopify",
    )
    parser.add_argument(
        "--product-type-map",
        default="product_type_map.json",
        help="Path to JSON lookup for filename style code -> Shopify product type label",
    )
    parser.add_argument(
        "--uploaded-dir",
        default="uploaded",
        help="Folder to move uploaded images into (relative paths are resolved inside --folder)",
    )
    parser.add_argument(
        "--publish-status",
        default="draft",
        choices=["draft", "active"],
        help="Set Shopify products to draft (default) or active",
    )
    parser.add_argument(
        "--sizes",
        default=None,
        help="Comma-separated sizes to create as variants, e.g. 'S,M,L,XL' or 'Age 3-4,Age 5-6'",
    )
    return parser.parse_args()


def main() -> int:
    load_dotenv()
    args = parse_args()

    folder_arg = args.folder or args.folder_positional
    if not folder_arg:
        print("Missing folder. Use --folder PATH or provide PATH as first argument.")
        return 1

    folder = Path(folder_arg)
    product_type_map_path = Path(args.product_type_map)
    uploaded_dir_arg = Path(args.uploaded_dir)
    uploaded_dir = uploaded_dir_arg if uploaded_dir_arg.is_absolute() else folder / uploaded_dir_arg

    try:
        product_type_map = load_product_type_map(product_type_map_path)
        parsed_images = collect_images(folder, product_type_map)
        groups = build_groups(parsed_images)
    except Exception as exc:
        print(f"Error while parsing folder: {exc}")
        return 1

    print(f"Found {len(parsed_images)} image files")
    print(f"Grouped into {len(groups)} artwork/product-type products")

    if args.dry_run:
        client = None
    else:
        shop_domain = os.getenv("SHOPIFY_SHOP_DOMAIN", "").strip()
        api_version = os.getenv("SHOPIFY_API_VERSION", "2025-01").strip()

        if not shop_domain:
            print("Missing SHOPIFY_SHOP_DOMAIN in environment/.env")
            return 1

        try:
            access_token = get_access_token(shop_domain)
        except Exception as exc:
            print(f"Authentication error: {exc}")
            return 1

        client = ShopifyClient(
            shop_domain=shop_domain,
            access_token=access_token,
            api_version=api_version,
        )

    sizes = [s.strip() for s in args.sizes.split(",") if s.strip()] if args.sizes else None

    try:
        create_products(
            client=client,  # type: ignore[arg-type]
            groups=groups,
            description=args.description,
            price_override=args.price,
            vendor=args.vendor,
            uploaded_dir=uploaded_dir,
            dry_run=args.dry_run,
            publish_status=args.publish_status,
            sizes=sizes,
        )
    except Exception as exc:
        print(f"Error during Shopify upload: {exc}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
