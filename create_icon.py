#!/usr/bin/env python3
"""
Generates AppIcon.icns (macOS) and AppIcon.ico (Windows) for the
Moonbeam Merch Uploader app bundle.

Usage:
    python create_icon.py [output_dir]

Requires Pillow:  pip install Pillow
"""

import math
import struct
import sys
import zlib
from io import BytesIO
from pathlib import Path


# ---------------------------------------------------------------------------
# Minimal PNG writer (no Pillow required for the fallback case)
# ---------------------------------------------------------------------------

def _pack_png(width: int, height: int, pixels_rgba: bytes) -> bytes:
    """Pack raw RGBA pixels into a valid PNG file without Pillow."""
    def chunk(name: bytes, data: bytes) -> bytes:
        c = name + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)  # RGB, no alpha for simplicity
    # Rebuild as RGBA (colour type 6)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)

    raw_rows = b""
    stride = width * 4
    for y in range(height):
        raw_rows += b"\x00" + pixels_rgba[y * stride:(y + 1) * stride]

    compressed = zlib.compress(raw_rows, 9)

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", ihdr)
    png += chunk(b"IDAT", compressed)
    png += chunk(b"IEND", b"")
    return png


def _render_icon_rgba(size: int) -> bytes:
    """Draw a simple gradient icon and return raw RGBA bytes."""
    pixels = bytearray(size * size * 4)
    cx = cy = size / 2
    r_outer = size / 2

    # Colours: deep indigo background → bright teal accent
    bg_r, bg_g, bg_b = 30, 20, 60        # deep indigo
    acc_r, acc_g, acc_b = 80, 220, 200   # teal

    for y in range(size):
        for x in range(size):
            dx = x - cx
            dy = y - cy
            dist = math.sqrt(dx * dx + dy * dy)

            # Circular mask with anti-alias
            alpha = max(0, min(255, int((r_outer - dist) * 3)))

            # Radial gradient blend
            t = min(1.0, dist / r_outer)
            r = int(bg_r + (acc_r - bg_r) * t)
            g = int(bg_g + (acc_g - bg_g) * t)
            b = int(bg_b + (acc_b - bg_b) * t)

            idx = (y * size + x) * 4
            pixels[idx]     = r
            pixels[idx + 1] = g
            pixels[idx + 2] = b
            pixels[idx + 3] = alpha

    # Draw a simple "M" glyph in the centre (3×5 cell scaled to icon size)
    glyph_scale = max(1, size // 16)
    glyph_x = int(cx - 3 * glyph_scale)
    glyph_y = int(cy - 4 * glyph_scale)
    M = [
        (0, 0), (0, 1), (0, 2), (0, 3), (0, 4),
        (1, 1),
        (2, 2),
        (3, 1),
        (4, 0), (4, 1), (4, 2), (4, 3), (4, 4),
    ]
    for px, py in M:
        for dy in range(glyph_scale):
            for dx in range(glyph_scale):
                xi = glyph_x + px * glyph_scale + dx
                yi = glyph_y + py * glyph_scale + dy
                if 0 <= xi < size and 0 <= yi < size:
                    idx = (yi * size + xi) * 4
                    pixels[idx]     = 255
                    pixels[idx + 1] = 255
                    pixels[idx + 2] = 255
                    pixels[idx + 3] = 255

    return bytes(pixels)


# ---------------------------------------------------------------------------
# .icns builder  (macOS)
# ---------------------------------------------------------------------------

_ICNS_TYPES = {
    16:   b"icp4",
    32:   b"icp5",
    64:   b"icp6",
    128:  b"ic07",
    256:  b"ic08",
    512:  b"ic09",
    1024: b"ic10",
}


def _build_icns(png_by_size: dict[int, bytes]) -> bytes:
    body = b""
    for size, png_data in sorted(png_by_size.items()):
        tag = _ICNS_TYPES.get(size)
        if tag is None:
            continue
        entry = tag + struct.pack(">I", len(png_data) + 8) + png_data
        body += entry
    header = b"icns" + struct.pack(">I", len(body) + 8)
    return header + body


# ---------------------------------------------------------------------------
# .ico builder  (Windows)
# ---------------------------------------------------------------------------

def _build_ico(png_by_size: dict[int, bytes]) -> bytes:
    sizes = sorted(png_by_size.keys())
    n = len(sizes)
    header = struct.pack("<HHH", 0, 1, n)   # reserved, type=1 (ICO), count
    dir_entries = b""
    image_data = b""
    offset = 6 + 16 * n                     # header + directory
    for size in sizes:
        data = png_by_size[size]
        w = h = size if size < 256 else 0   # 256 encoded as 0
        dir_entries += struct.pack("<BBBBHHII", w, h, 0, 0, 1, 32, len(data), offset)
        image_data += data
        offset += len(data)
    return header + dir_entries + image_data


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def generate(output_dir: Path):
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        from PIL import Image, ImageDraw, ImageFont
        use_pillow = True
        print("Pillow found — using high-quality rendering.")
    except ImportError:
        use_pillow = False
        print("Pillow not found — using built-in renderer (install Pillow for better quality).")

    sizes = [16, 32, 64, 128, 256, 512, 1024]
    png_by_size: dict[int, bytes] = {}

    for size in sizes:
        if use_pillow:
            from PIL import Image, ImageDraw, ImageFont
            img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)
            # Background circle
            draw.ellipse([0, 0, size - 1, size - 1], fill=(30, 20, 60, 255))
            # "M" text
            font_size = max(8, int(size * 0.55))
            try:
                font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", font_size)
            except Exception:
                try:
                    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size)
                except Exception:
                    font = ImageFont.load_default()
            bbox = draw.textbbox((0, 0), "M", font=font)
            tw = bbox[2] - bbox[0]
            th = bbox[3] - bbox[1]
            draw.text(((size - tw) / 2 - bbox[0], (size - th) / 2 - bbox[1]), "M", font=font, fill=(80, 220, 200, 255))
            buf = BytesIO()
            img.save(buf, "PNG")
            png_by_size[size] = buf.getvalue()
        else:
            rgba = _render_icon_rgba(size)
            png_by_size[size] = _pack_png(size, size, rgba)

    # Write individual PNGs for icns iconset
    icns_dir = output_dir / "AppIcon.iconset"
    icns_dir.mkdir(exist_ok=True)
    for size in sizes:
        (icns_dir / f"icon_{size}x{size}.png").write_bytes(png_by_size[size])
        if size <= 512:
            (icns_dir / f"icon_{size}x{size}@2x.png").write_bytes(png_by_size[min(size * 2, 1024)])

    # Try macOS iconutil
    import subprocess
    icns_path = output_dir / "AppIcon.icns"
    try:
        subprocess.run(
            ["iconutil", "-c", "icns", str(icns_dir), "-o", str(icns_path)],
            check=True, capture_output=True,
        )
        print(f"  Created {icns_path} via iconutil")
    except Exception:
        icns_path.write_bytes(_build_icns({s: png_by_size[s] for s in sizes if s <= 1024}))
        print(f"  Created {icns_path} (built-in)")

    # Write .ico for Windows (use sizes ≤ 256)
    ico_sizes = [s for s in sizes if s <= 256]
    ico_path = output_dir / "AppIcon.ico"
    ico_path.write_bytes(_build_ico({s: png_by_size[s] for s in ico_sizes}))
    print(f"  Created {ico_path}")

    # Write a 256×256 PNG fallback
    png_path = output_dir / "AppIcon.png"
    png_path.write_bytes(png_by_size[256])
    print(f"  Created {png_path}")

    print("Done.")
    return icns_path, ico_path


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "icons"
    generate(out)
