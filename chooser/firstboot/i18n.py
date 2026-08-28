"""Chooser translations. English (US) is the source; catalogs are GNU gettext .po."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass

DOMAIN = "firstboot"
DEFAULT_LANGUAGE = "en-us"
LANGUAGE_FILE = "language"
HELPER = "/usr/libexec/firstboot/set-language"
ID_RE = re.compile(r"^[a-z]{2,3}(?:-[a-z0-9]+)*$")
LANG_JSON = "languages.json"
ALIASES = {
    "en": "en-us",
    "af-za": "af",
}

_catalog: dict[str, str] = {}
_current = DEFAULT_LANGUAGE


@dataclass(frozen=True)
class Language:
    id: str
    name: str
    en: str

    @property
    def search_text(self) -> str:
        return f"{self.name} {self.en}"


def is_english(lang_id: str) -> bool:
    """True for the English source family (en, en-us, en-gb, …)."""
    return lang_id == "en" or lang_id.startswith("en-")


def _(message: str) -> str:
    if not message:
        return message
    return _catalog.get(message, message)


def format_status(text: str) -> str:
    """Translate a helper STEP/ERROR line. Optional tab + {name}/{size} argument."""
    if not text:
        return text
    msgid, sep, arg = text.partition("\t")
    out = _(msgid)
    if not (sep and arg) or "{" not in out:
        return out
    try:
        return out.format(name=arg, size=arg)
    except (KeyError, ValueError, IndexError):
        return out


def apply_payload_language(root: str | None = None) -> str:
    path = (
        root
        or os.environ.get("FIRSTBOOT_PAYLOAD")
        or os.environ.get("FBL_PAYLOAD")
        or "/run/payload"
    )
    return apply_language(load_language(path))


def current_language() -> str:
    return _current


def normalize_id(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip().casefold().replace("_", "-")
    if not text or not ID_RE.fullmatch(text):
        return None
    if text in ALIASES:
        return ALIASES[text]
    return text


def language_matches(lang: Language, query: str) -> bool:
    tokens = tuple(
        part for part in query.casefold().split() if part
    )
    if not tokens:
        return True
    hay = lang.search_text.casefold()
    return all(tok in hay for tok in tokens)


def locale_dirs() -> list[str]:
    dirs: list[str] = []
    here = os.path.abspath(os.path.dirname(__file__))
    repo = os.path.abspath(os.path.join(here, "..", ".."))
    chooser = os.path.abspath(os.path.join(here, ".."))
    for path in (
        "/usr/share/firstboot/locale",
        os.path.join(chooser, "locale"),
        os.path.join(repo, "po"),
        os.path.join(here, "locale"),
    ):
        if os.path.isdir(path) and path not in dirs:
            dirs.append(path)
    return dirs


def languages_json_paths() -> list[str]:
    here = os.path.abspath(os.path.dirname(__file__))
    repo = os.path.abspath(os.path.join(here, "..", ".."))
    paths = [
        "/usr/share/firstboot/languages.json",
        os.path.join(repo, "po", LANG_JSON),
        os.path.join(here, LANG_JSON),
    ]
    return paths


def load_language_index() -> tuple[Language, ...]:
    for path in languages_json_paths():
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError):
            continue
        rows = data.get("languages") if isinstance(data, dict) else data
        if not isinstance(rows, list):
            continue
        out: list[Language] = []
        seen: set[str] = set()
        for raw in rows:
            if not isinstance(raw, dict):
                continue
            lid = normalize_id(str(raw.get("id") or ""))
            name = str(raw.get("name") or "").strip()
            en = str(raw.get("en") or name).strip()
            if not lid or not name or lid in seen:
                continue
            seen.add(lid)
            out.append(Language(id=lid, name=name, en=en or name))
        if out:
            if not any(is_english(item) for item in seen):
                out.insert(
                    0, Language(DEFAULT_LANGUAGE, "English (US)", "English (US)")
                )
            return tuple(out)
    return (Language(DEFAULT_LANGUAGE, "English (US)", "English (US)"),)


def catalog_path(lang_id: str) -> str | None:
    lid = normalize_id(lang_id)
    if not lid or lid == DEFAULT_LANGUAGE:
        return None
    if lid == "en":
        return None
    for root in locale_dirs():
        candidates = (
            os.path.join(root, lid, "LC_MESSAGES", f"{DOMAIN}.mo"),
            os.path.join(root, lid, "LC_MESSAGES", f"{DOMAIN}.po"),
            os.path.join(root, f"{lid}.po"),
        )
        for path in candidates:
            if os.path.isfile(path):
                return path
    return None


def has_catalog(lang_id: str) -> bool:
    lid = normalize_id(lang_id)
    if not lid:
        return False
    if lid == DEFAULT_LANGUAGE or is_english(lid):
        return True
    return catalog_path(lid) is not None


def supported_languages() -> tuple[Language, ...]:
    """Languages the live chooser may list: shipped index ∩ catalogs we have."""
    out: list[Language] = []
    for lang in load_language_index():
        if has_catalog(lang.id):
            out.append(lang)
    if not any(is_english(lang.id) for lang in out):
        out.insert(0, Language(DEFAULT_LANGUAGE, "English (US)", "English (US)"))
    return tuple(out)


def supported_ids() -> frozenset[str]:
    return frozenset(lang.id for lang in supported_languages())


def resolve_language(lang_id: str | None) -> str:
    lid = normalize_id(lang_id)
    if lid and lid in supported_ids():
        return lid
    return DEFAULT_LANGUAGE


def parse_po(text: str) -> dict[str, str]:
    """Minimal GNU gettext .po reader (msgid / msgstr only)."""
    catalog: dict[str, str] = {}
    msgid: list[str] | None = None
    msgstr: list[str] | None = None
    state: str | None = None

    def flush() -> None:
        nonlocal msgid, msgstr, state
        if msgid is not None and msgstr is not None:
            src = "".join(msgid)
            dst = "".join(msgstr)
            if src and dst:
                catalog[src] = dst
        msgid = None
        msgstr = None
        state = None

    def parse_str(line: str) -> str | None:
        line = line.strip()
        if not line.startswith('"'):
            return None
        try:
            return _unquote_po(line)
        except ValueError:
            return None

    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("msgid "):
            flush()
            msgid = []
            msgstr = None
            state = "msgid"
            chunk = parse_str(line[6:])
            if chunk is not None:
                msgid.append(chunk)
            continue
        if line.startswith("msgstr "):
            msgstr = []
            state = "msgstr"
            chunk = parse_str(line[7:])
            if chunk is not None:
                msgstr.append(chunk)
            continue
        if line.startswith("msgctxt ") or line.startswith("msgid_plural "):
            flush()
            state = None
            continue
        if state in {"msgid", "msgstr"} and line.startswith('"'):
            chunk = parse_str(line)
            if chunk is None:
                continue
            if state == "msgid" and msgid is not None:
                msgid.append(chunk)
            elif state == "msgstr" and msgstr is not None:
                msgstr.append(chunk)
    flush()
    return catalog


def _unquote_po(token: str) -> str:
    token = token.strip()
    if len(token) < 2 or token[0] != '"' or token[-1] != '"':
        raise ValueError("not a po string")
    inner = token[1:-1]
    out: list[str] = []
    i = 0
    while i < len(inner):
        ch = inner[i]
        if ch != "\\":
            out.append(ch)
            i += 1
            continue
        i += 1
        if i >= len(inner):
            break
        esc = inner[i]
        out.append(
            {
                "n": "\n",
                "t": "\t",
                "r": "\r",
                "\\": "\\",
                '"': '"',
            }.get(esc, esc)
        )
        i += 1
    return "".join(out)


def load_catalog(lang_id: str) -> dict[str, str]:
    lid = resolve_language(lang_id)
    if lid == DEFAULT_LANGUAGE or lid == "en":
        return {}
    path = catalog_path(lid)
    if not path:
        return {}
    if path.endswith(".mo"):
        try:
            import gettext

            with open(path, "rb") as fh:
                trans = gettext.GNUTranslations(fh)
            raw = getattr(trans, "_catalog", {})
            return {
                k: v
                for k, v in raw.items()
                if isinstance(k, str) and k and isinstance(v, str) and v
            }
        except (OSError, Exception):
            return {}
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        return {}
    return parse_po(text)


def apply_language(lang_id: str) -> str:
    """Install the catalog for this process. Returns the resolved id."""
    global _catalog, _current
    lid = resolve_language(lang_id)
    _current = lid
    _catalog = load_catalog(lid)
    os.environ["LANGUAGE"] = lid
    return lid


def language_file_path(payload_root: str) -> str:
    return os.path.join(payload_root, LANGUAGE_FILE)


def read_language_file(payload_root: str) -> str | None:
    path = language_file_path(payload_root)
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


def load_language(payload_root: str, retailer_language: str | None = None) -> str:
    for candidate in (read_language_file(payload_root), retailer_language):
        if not candidate:
            continue
        return resolve_language(candidate)
    return DEFAULT_LANGUAGE


def write_language_file(payload_root: str, lang_id: str) -> None:
    lid = resolve_language(lang_id)
    os.makedirs(payload_root, exist_ok=True)
    path = language_file_path(payload_root)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(lid + "\n")
    os.replace(tmp, path)


def persist_language(payload_root: str, lang_id: str) -> bool:
    """Save the live choice on the payload. Best-effort."""
    lid = resolve_language(lang_id)
    helper = HELPER if os.path.isfile(HELPER) else ""
    if helper:
        sudo = shutil.which("sudo")
        if sudo:
            try:
                proc = subprocess.run(
                    [sudo, "-n", helper, payload_root, lid],
                    check=False,
                    capture_output=True,
                    timeout=8,
                )
                if proc.returncode == 0:
                    return True
            except (OSError, subprocess.TimeoutExpired):
                pass
    try:
        write_language_file(payload_root, lid)
        return True
    except OSError:
        return False
