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
