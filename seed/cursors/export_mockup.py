#!/usr/bin/env python3
"""Write 24px mockup PNGs + hotspot CSS from the First Boot Cursor SVGs."""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from build_theme import (  # noqa: E402
    BIBATA_TOML,
    parse_bibata_config,
    render_svg,
    resolve_anim_frames,
    resolve_static_svg,
    scale_hotspot,
)

REPO = HERE.parent.parent
OUT = REPO / "docs" / "assets" / "cursors"
SIZE = 24

# CSS cursor name → Bibata config key
MOCKUP = (
    ("default", "left_ptr"),
    ("pointer", "hand2"),
    ("text", "xterm"),
    ("wait", "wait"),
    ("progress", "left_ptr_watch"),
    ("move", "move"),
    ("grab", "hand1"),
    ("grabbing", "grabbing"),
    ("ns-resize", "sb_v_double_arrow"),
    ("ew-resize", "sb_h_double_arrow"),
    ("nwse-resize", "bd_double_arrow"),
    ("nesw-resize", "fd_double_arrow"),
    ("n-resize", "top_side"),
    ("s-resize", "bottom_side"),
    ("e-resize", "right_side"),
    ("w-resize", "left_side"),
    ("col-resize", "sb_h_double_arrow"),
    ("row-resize", "sb_v_double_arrow"),
    ("not-allowed", "crossed_circle"),
    ("help", "question_arrow"),
    ("crosshair", "crosshair"),
    ("copy", "copy"),
    ("alias", "dnd-link"),
    ("context-menu", "context-menu"),
    ("zoom-in", "zoom_in"),
    ("zoom-out", "zoom_out"),
    ("no-drop", "dnd_no_drop"),
)


def _svg_for(key: str, meta: dict) -> Path:
    if meta.get("animated"):
        frames = resolve_anim_frames(key)
        if not frames:
            raise SystemExit(f"no animation frames for {key}")
        return frames[0]
    svg = resolve_static_svg(key, meta["png"])
    if svg is None:
        raise SystemExit(f"no svg for {key}")
    return svg


def main() -> None:
    cfg = parse_bibata_config(BIBATA_TOML)
    OUT.mkdir(parents=True, exist_ok=True)
    lines = [":root {"]
    for css_name, key in MOCKUP:
        meta = cfg["cursors"].get(key)
        if meta is None:
            raise SystemExit(f"missing cursor in config: {key}")
        svg = _svg_for(key, meta)
        im = render_svg(svg, SIZE)
        hx, hy = scale_hotspot(meta["x_hotspot"], meta["y_hotspot"], SIZE)
        png = OUT / f"{css_name}.png"
        im.save(png)
        lines.append(
            f'  --cursor-{css_name}: url("assets/cursors/{css_name}.png")'
            f" {hx} {hy}, {css_name};"
        )
        print(f"  {png.name}  hotspot=({hx},{hy})  ← {svg.name}")
    lines.append("}")
    css = "\n".join(lines) + "\n"
    (OUT / "hotspots.css").write_text(css, encoding="utf-8")
    styles = REPO / "docs" / "styles.css"
    text = styles.read_text(encoding="utf-8")
    start = text.find("  --cursor-default:")
    end = text.find("}", start)
    if start < 0 or end < 0:
        raise SystemExit(f"could not find cursor vars in {styles}")
    inner = "\n".join(lines[1:-1])
    styles.write_text(text[:start] + inner + "\n" + text[end:], encoding="utf-8")
    print(f"wrote {OUT / 'hotspots.css'} and updated {styles}")


if __name__ == "__main__":
    main()
