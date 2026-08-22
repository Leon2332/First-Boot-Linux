"""Chooser asset lookup. Logos and status icons live next to the live tree
or, when running from a checkout, under docs/."""

from __future__ import annotations

import os
import re

SHARE_LIVE = "/usr/share/firstboot"


def chooser_dir() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def repo_root() -> str:
    return os.path.abspath(os.path.join(chooser_dir(), ".."))


def asset_search_roots() -> list[str]:
    roots: list[str] = []
    if os.path.isdir(SHARE_LIVE):
        roots.append(SHARE_LIVE)
    docs = os.path.join(repo_root(), "docs")
    if os.path.isdir(docs):
        roots.append(docs)
        roots.append(os.path.join(docs, "assets"))
    return roots


def find_asset(*relatives: str) -> str | None:
    for root in asset_search_roots():
        for rel in relatives:
            path = os.path.join(root, rel)
            if os.path.isfile(path):
                return path
    return None


def find_logo(distro_id: str) -> str | None:
    return find_asset(
        os.path.join("distros", f"{distro_id}.png"),
        os.path.join("assets", "distros", f"{distro_id}.png"),
    )


def find_status(name: str) -> str | None:
    return find_asset(
        os.path.join("status", name),
        os.path.join("assets", "status", name),
    )


def find_app_icon(name: str) -> str | None:
    return find_asset(
        os.path.join("apps", name),
        os.path.join("assets", "apps", name),
    )


def find_brand_logo() -> str | None:
    return find_asset(
        "logo.png",
        os.path.join("Logo", "First Boot Linux.png"),
    )


def find_brand_wordmark(dark: bool) -> str | None:
    if dark:
        return find_asset(
            "logo-wordmark-dark.png",
            os.path.join("Logo", "First Boot Linux - dark mode.png"),
        )
    return find_asset(
        "logo-wordmark-light.png",
        os.path.join("Logo", "First Boot Linux- light mode.png"),
    )


def recolor_svg(text: str, color: str) -> str:
    """Force a symbolic SVG onto one fill color (panel / QS icons)."""
    text = re.sub(r'fill="(?!none)[^"]*"', f'fill="{color}"', text)
    text = re.sub(r"fill='(?!none)[^']*'", f"fill='{color}'", text)
    text = re.sub(r"fill:(?!none)[^;\"']+", f"fill:{color}", text)
    if re.search(r"<svg\b", text, re.I) and "fill=" not in text.lower():
        text = re.sub(r"<svg\b", f'<svg fill="{color}"', text, count=1, flags=re.I)
    return text


def symbolic_pixbuf(path: str, color: str, size: int):
    """Load an SVG as a GdkPixbuf tinted to *color*. Returns None on failure."""
    try:
        import gi

        gi.require_version("GdkPixbuf", "2.0")
        from gi.repository import GdkPixbuf
    except (ImportError, ValueError):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            raw = fh.read()
    except OSError:
        return None
    data = recolor_svg(raw, color).encode("utf-8")
    try:
        loader = GdkPixbuf.PixbufLoader.new_with_type("svg")
        loader.set_size(size, size)
        loader.write(data)
        loader.close()
        return loader.get_pixbuf()
    except Exception:
        return None


def brand_logo_pixbuf(path: str, dark: bool, size: int):
    """White boot-print on black → transparent; invert for the light style."""
    try:
        import gi

        gi.require_version("GdkPixbuf", "2.0")
        from gi.repository import GdkPixbuf
    except (ImportError, ValueError):
        return None
    try:
        src = GdkPixbuf.Pixbuf.new_from_file_at_size(path, size, size)
    except Exception:
        return None
    if src is None:
        return None
    if src.get_n_channels() < 4:
        src = src.add_alpha(True, 0, 0, 0)
    else:
        src = src.copy()
    w, h = src.get_width(), src.get_height()
    n = src.get_n_channels()
    stride = src.get_rowstride()
    src_px = src.get_pixels()
    dest_stride = w * 4
    dest_px = bytearray(dest_stride * h)
    for y in range(h):
        row = y * stride
        for x in range(w):
            i = row + x * n
            r, g, b = src_px[i], src_px[i + 1], src_px[i + 2]
            a = src_px[i + 3] if n >= 4 else 255
            dest = y * dest_stride + x * 4
            if r < 24 and g < 24 and b < 24:
                dest_px[dest : dest + 4] = b"\x00\x00\x00\x00"
                continue
            if not dark:
                r, g, b = 255 - r, 255 - g, 255 - b
            dest_px[dest] = r
            dest_px[dest + 1] = g
            dest_px[dest + 2] = b
            dest_px[dest + 3] = a
    try:
        from gi.repository import GLib
    except ImportError:
        return src
    return GdkPixbuf.Pixbuf.new_from_bytes(
        GLib.Bytes.new(bytes(dest_px)),
        GdkPixbuf.Colorspace.RGB,
        True,
        8,
        w,
        h,
        dest_stride,
    )


def wordmark_pixbuf(path: str, dark: bool, width: int):
    """White-on-black wordmark → transparent; invert for the light style."""
    try:
        import gi

        gi.require_version("GdkPixbuf", "2.0")
        from gi.repository import GdkPixbuf, GLib
    except (ImportError, ValueError):
        return None
    try:
        src = GdkPixbuf.Pixbuf.new_from_file(path)
    except Exception:
        return None
    if src is None or src.get_width() <= 0:
        return None
    height = max(1, round(src.get_height() * width / src.get_width()))
    src = src.scale_simple(width, height, GdkPixbuf.InterpType.BILINEAR)
    if src is None:
        return None
    if src.get_n_channels() < 4:
        src = src.add_alpha(True, 0, 0, 0)
    else:
        src = src.copy()
    w, h = src.get_width(), src.get_height()
    n = src.get_n_channels()
    stride = src.get_rowstride()
    src_px = src.get_pixels()
    dest_stride = w * 4
    dest_px = bytearray(dest_stride * h)
    min_x, min_y, max_x, max_y = w, h, -1, -1
    for y in range(h):
        row = y * stride
        for x in range(w):
            i = row + x * n
            r, g, b = src_px[i], src_px[i + 1], src_px[i + 2]
            a = src_px[i + 3] if n >= 4 else 255
            dest = y * dest_stride + x * 4
            if r < 24 and g < 24 and b < 24:
                dest_px[dest : dest + 4] = b"\x00\x00\x00\x00"
                continue
            if not dark:
                r, g, b = 255 - r, 255 - g, 255 - b
            dest_px[dest] = r
            dest_px[dest + 1] = g
            dest_px[dest + 2] = b
            dest_px[dest + 3] = a
            if x < min_x:
                min_x = x
            if y < min_y:
                min_y = y
            if x > max_x:
                max_x = x
            if y > max_y:
                max_y = y
    full = GdkPixbuf.Pixbuf.new_from_bytes(
        GLib.Bytes.new(bytes(dest_px)),
        GdkPixbuf.Colorspace.RGB,
        True,
        8,
        w,
        h,
        dest_stride,
    )
    if max_x < min_x:
        return full
    pad = 2
    x0 = max(0, min_x - pad)
    y0 = max(0, min_y - pad)
    cw = min(w - x0, max_x - min_x + 1 + pad * 2)
    ch = min(h - y0, max_y - min_y + 1 + pad * 2)
    cropped = full.new_subpixbuf(x0, y0, cw, ch)
    return cropped.copy() if cropped is not None else full
