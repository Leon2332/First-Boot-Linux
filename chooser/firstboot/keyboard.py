"""Shop keyboard layout. Independent of language. xkb layout ids only."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass

DEFAULT_KEYBOARD = "us"
KEYBOARD_FILE = "keyboard"
KB_JSON = "keyboards.json"
ID_RE = re.compile(r"^[a-z]{2,5}$")


@dataclass(frozen=True)
class Keyboard:
    id: str
    name: str


def normalize_id(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip().casefold().replace("_", "-")
    if not text or not ID_RE.fullmatch(text):
        return None
    return text


def keyboard_json_paths() -> list[str]:
    here = os.path.abspath(os.path.dirname(__file__))
    repo = os.path.abspath(os.path.join(here, "..", ".."))
    return [
        "/usr/share/firstboot/keyboards.json",
        os.path.join(repo, "po", KB_JSON),
        os.path.join(here, KB_JSON),
    ]


def load_keyboard_index() -> tuple[Keyboard, ...]:
    for path in keyboard_json_paths():
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError):
            continue
        rows = data.get("keyboards") if isinstance(data, dict) else data
        if not isinstance(rows, list):
            continue
        out: list[Keyboard] = []
        seen: set[str] = set()
        for raw in rows:
            if not isinstance(raw, dict):
                continue
            kid = normalize_id(str(raw.get("id") or ""))
            name = str(raw.get("name") or "").strip()
            if not kid or not name or kid in seen:
                continue
            seen.add(kid)
            out.append(Keyboard(id=kid, name=name))
        if out:
            if DEFAULT_KEYBOARD not in seen:
                out.insert(0, Keyboard(DEFAULT_KEYBOARD, "English (US)"))
            return tuple(out)
    return (Keyboard(DEFAULT_KEYBOARD, "English (US)"),)


def supported_ids() -> frozenset[str]:
    return frozenset(kb.id for kb in load_keyboard_index())


def resolve_keyboard(kbd_id: str | None) -> str:
    kid = normalize_id(kbd_id)
    if kid and kid in supported_ids():
        return kid
    return DEFAULT_KEYBOARD


def keyboard_file_path(payload_root: str) -> str:
    return os.path.join(payload_root, KEYBOARD_FILE)


def read_keyboard_file(payload_root: str) -> str | None:
    path = keyboard_file_path(payload_root)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            for raw in fh:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                return normalize_id(line)
    except OSError:
        return None
    return None


def load_keyboard(payload_root: str, retailer_keyboard: str | None = None) -> str:
    for candidate in (read_keyboard_file(payload_root), retailer_keyboard):
        if not candidate:
            continue
        return resolve_keyboard(candidate)
    return DEFAULT_KEYBOARD


def write_keyboard_file(payload_root: str, kbd_id: str) -> None:
    kid = resolve_keyboard(kbd_id)
    os.makedirs(payload_root, exist_ok=True)
    path = keyboard_file_path(payload_root)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(kid + "\n")
    os.replace(tmp, path)


def emit_session_env() -> None:
    """Print XKB_DEFAULT_LAYOUT for firstboot-session. Ids are a tight whitelist."""
    root = (
        os.environ.get("FIRSTBOOT_PAYLOAD")
        or os.environ.get("FBL_PAYLOAD")
        or "/run/payload"
    )
    kid = load_keyboard(root)
    print(f"export XKB_DEFAULT_LAYOUT={kid}")
