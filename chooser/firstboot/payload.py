"""Load /run/payload retailer.conf + catalog.json.

The chooser does not read official-catalog.json. Local vs download is
whether the edition file exists on the payload, not the JSON `local` flag.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field

SCHEMA_VERSION = 1
DEFAULT_PAYLOAD = "/run/payload"
FAMILIES = frozenset(
    {"ubuntu", "mint", "fedora", "debian", "suse", "windows", "bsd", "other"}
)
INSTALL_DRIVERS = frozenset(
    {
        "ubuntu-2604",
        "ubuntu-autoinstall",
        "mint-223",
        "mint",
        "fedora-44-plasma",
        "fedora-kickstart",
        "debian-preseed",
        "windows",
        "freebsd",
    }
)
ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
FILE_RE = re.compile(r"^images/[^/\\]+\.(iso|img)$")


class PayloadError(Exception):
    """A single recoverable load problem."""


@dataclass(frozen=True)
class Retailer:
    name: str
    support: str
    wallpaper_dark: str
    wallpaper_light: str


@dataclass(frozen=True)
class Edition:
    id: str
    name: str
    default: bool
    claimed_local: bool
    file: str | None
    url: str | None
    sha256: str
    size_bytes: int
    available: bool

    @property
    def on_disk(self) -> bool:
        return self.available

    @property
    def action(self) -> str:
        return "install" if self.available else "download"

    def size_label(self) -> str:
        gb = self.size_bytes / 1_000_000_000
        if gb >= 10:
            return f"~{gb:.0f} GB"
        return f"~{gb:.1f} GB"


@dataclass(frozen=True)
class Distro:
    id: str
    name: str
    version: str
    tagline: str
    description: str
    family: str
    install: str
    editions: tuple[Edition, ...]
    recommended: bool

    @property
    def default_edition(self) -> Edition:
        for ed in self.editions:
            if ed.default:
                return ed
        return self.editions[0]

    @property
    def default_desktop(self) -> str:
        return self.default_edition.name

    @property
    def catalog_name(self) -> str:
        if self.id == "ms-windows":
            return "Microsoft Windows"
        return self.name


@dataclass
class Payload:
    root: str
    retailer: Retailer | None = None
    recommended: list[Distro] = field(default_factory=list)
    catalog: list[Distro] = field(default_factory=list)
    others: list[Distro] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    wallpaper_dark: str | None = None
    wallpaper_light: str | None = None

    @property
    def ok(self) -> bool:
        return self.retailer is not None and not any(
            e.startswith("catalog.json:") for e in self.errors
        )


def load_payload(root: str = DEFAULT_PAYLOAD) -> Payload:
    payload = Payload(root=os.path.abspath(root))
    if not os.path.isdir(payload.root):
        payload.errors.append(f"payload directory missing: {payload.root}")
        return payload

    try:
        payload.retailer = _load_retailer(payload.root)
    except PayloadError as exc:
        payload.errors.append(str(exc))

    if payload.retailer is not None:
        payload.wallpaper_dark = _resolve_wallpaper(
            payload.root, payload.retailer.wallpaper_dark, "wallpaper_dark"
        )
        payload.wallpaper_light = _resolve_wallpaper(
            payload.root, payload.retailer.wallpaper_light, "wallpaper_light"
        )
        if payload.wallpaper_dark is None:
            payload.errors.append(
                f"retailer.conf: wallpaper_dark not found ({payload.retailer.wallpaper_dark})"
            )
        if payload.wallpaper_light is None:
            payload.errors.append(
                f"retailer.conf: wallpaper_light not found ({payload.retailer.wallpaper_light})"
            )

    try:
        recommended, catalog = _load_catalog(payload.root)
        payload.recommended = recommended
        payload.catalog = catalog
        payload.others = _merge_others(recommended, catalog)
    except PayloadError as exc:
        payload.errors.append(str(exc))

    return payload


def parse_retailer_conf(text: str) -> dict[str, str]:
    data: dict[str, str] = {}
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise PayloadError(f"retailer.conf:{lineno}: expected key = value")
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            raise PayloadError(f"retailer.conf:{lineno}: empty key")
        data[key] = value
    return data


def format_size(size_bytes: int) -> str:
    return Edition(
        id="x",
        name="x",
        default=True,
        claimed_local=False,
        file=None,
        url=None,
        sha256="0" * 64,
        size_bytes=size_bytes,
        available=False,
    ).size_label()


def edition_is_present(root: str, file_rel: str | None) -> bool:
    if not file_rel:
        return False
    if _unsafe_relpath(file_rel):
        return False
    return os.path.isfile(os.path.join(root, file_rel))


def _load_retailer(root: str) -> Retailer:
    path = os.path.join(root, "retailer.conf")
    if not os.path.isfile(path):
        raise PayloadError("retailer.conf missing")
    try:
        text = _read_text(path)
    except OSError as exc:
        raise PayloadError(f"retailer.conf: {exc}") from exc
    raw = parse_retailer_conf(text)
    if raw.get("schema_version") != "1":
        raise PayloadError("retailer.conf: schema_version must be 1")
    required = ("name", "support", "wallpaper_dark", "wallpaper_light")
    missing = [k for k in required if not raw.get(k)]
    if missing:
        raise PayloadError("retailer.conf: missing " + ", ".join(missing))
    for key in ("wallpaper_dark", "wallpaper_light"):
        if _unsafe_relpath(raw[key]):
            raise PayloadError(f"retailer.conf: {key} is not a safe relative path")
        if not raw[key].startswith("wallpapers/"):
            raise PayloadError(f"retailer.conf: {key} must be under wallpapers/")
    extra = set(raw) - {"schema_version", *required}
    if extra:
        raise PayloadError("retailer.conf: unknown keys: " + ", ".join(sorted(extra)))
    return Retailer(
        name=raw["name"],
        support=raw["support"],
        wallpaper_dark=raw["wallpaper_dark"],
        wallpaper_light=raw["wallpaper_light"],
    )


def _load_catalog(root: str) -> tuple[list[Distro], list[Distro]]:
    path = os.path.join(root, "catalog.json")
    if not os.path.isfile(path):
        raise PayloadError("catalog.json missing")
    try:
        text = _read_text(path)
        data = json.loads(text)
    except OSError as exc:
        raise PayloadError(f"catalog.json: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise PayloadError(f"catalog.json: invalid JSON ({exc.msg})") from exc
    if not isinstance(data, dict):
        raise PayloadError("catalog.json: root must be an object")
    extra = set(data) - {"schema_version", "recommended", "catalog"}
    if extra:
        raise PayloadError("catalog.json: unknown keys: " + ", ".join(sorted(extra)))
    if data.get("schema_version") != SCHEMA_VERSION:
        raise PayloadError("catalog.json: schema_version must be 1")
    if not isinstance(data.get("recommended"), list) or not isinstance(
        data.get("catalog"), list
    ):
        raise PayloadError("catalog.json: recommended and catalog must be arrays")

    seen: set[str] = set()
    recommended: list[Distro] = []
    for i, raw in enumerate(data["recommended"]):
        distro = _parse_distro(root, raw, recommended=True, index=i, seen=seen)
        recommended.append(distro)
    catalog: list[Distro] = []
    for i, raw in enumerate(data["catalog"]):
        distro = _parse_distro(root, raw, recommended=False, index=i, seen=seen)
        catalog.append(distro)
    return recommended, catalog


def _parse_distro(
    root: str, raw: object, *, recommended: bool, index: int, seen: set[str]
) -> Distro:
    where = f"{'recommended' if recommended else 'catalog'}[{index}]"
    if not isinstance(raw, dict):
        raise PayloadError(f"catalog.json: {where} must be an object")
    extra = set(raw) - {
        "id",
        "name",
        "version",
        "tagline",
        "description",
        "family",
        "install",
        "editions",
    }
    if extra:
        raise PayloadError(f"catalog.json: {where} unknown keys: {', '.join(sorted(extra))}")
    for key in (
        "id",
        "name",
        "version",
        "tagline",
        "description",
        "family",
        "install",
        "editions",
    ):
        if key not in raw:
            raise PayloadError(f"catalog.json: {where} missing {key}")
    did = raw["id"]
    if not isinstance(did, str) or not ID_RE.fullmatch(did):
        raise PayloadError(f"catalog.json: {where} invalid id")
    if did in seen:
        raise PayloadError(f"catalog.json: duplicate id {did}")
    seen.add(did)
    if raw["family"] not in FAMILIES:
        raise PayloadError(f"catalog.json: {where} unknown family")
    if raw["install"] not in INSTALL_DRIVERS:
        raise PayloadError(f"catalog.json: {where} unknown install driver")
    if not isinstance(raw["editions"], list) or not raw["editions"]:
        raise PayloadError(f"catalog.json: {where} editions must be a non-empty array")

    editions: list[Edition] = []
    defaults = 0
    edition_ids: set[str] = set()
    for j, eraw in enumerate(raw["editions"]):
        ed = _parse_edition(root, eraw, f"{where}.editions[{j}]")
        if ed.id in edition_ids:
            raise PayloadError(f"catalog.json: {where} duplicate edition id {ed.id}")
        edition_ids.add(ed.id)
        if ed.default:
            defaults += 1
        editions.append(ed)
    if defaults != 1:
        raise PayloadError(f"catalog.json: {where} needs exactly one default edition")

    for key in ("name", "version", "tagline", "description"):
        if not isinstance(raw[key], str) or not raw[key].strip():
            raise PayloadError(f"catalog.json: {where} {key} must be a non-empty string")

    return Distro(
        id=did,
        name=raw["name"].strip(),
        version=raw["version"].strip(),
        tagline=raw["tagline"].strip(),
        description=raw["description"].strip(),
        family=raw["family"],
        install=raw["install"],
        editions=tuple(editions),
        recommended=recommended,
    )


def _parse_edition(root: str, raw: object, where: str) -> Edition:
    if not isinstance(raw, dict):
        raise PayloadError(f"catalog.json: {where} must be an object")
    extra = set(raw) - {
        "id",
        "name",
        "default",
        "local",
        "file",
        "url",
        "sha256",
        "size_bytes",
    }
    if extra:
        raise PayloadError(f"catalog.json: {where} unknown keys: {', '.join(sorted(extra))}")
    for key in ("id", "name", "default", "local", "sha256", "size_bytes"):
        if key not in raw:
            raise PayloadError(f"catalog.json: {where} missing {key}")
    eid = raw["id"]
    if not isinstance(eid, str) or not ID_RE.fullmatch(eid):
        raise PayloadError(f"catalog.json: {where} invalid id")
    if not isinstance(raw["name"], str) or not raw["name"].strip():
        raise PayloadError(f"catalog.json: {where} name must be a non-empty string")
    if not isinstance(raw["default"], bool) or not isinstance(raw["local"], bool):
        raise PayloadError(f"catalog.json: {where} default/local must be booleans")
    if not isinstance(raw["sha256"], str) or not SHA256_RE.fullmatch(raw["sha256"]):
        raise PayloadError(f"catalog.json: {where} sha256 must be 64 lowercase hex")
    if not isinstance(raw["size_bytes"], int) or isinstance(raw["size_bytes"], bool):
        raise PayloadError(f"catalog.json: {where} size_bytes must be an integer")
    if raw["size_bytes"] < 1:
        raise PayloadError(f"catalog.json: {where} size_bytes must be >= 1")

    file_rel = raw.get("file")
    url = raw.get("url")
    if raw["local"]:
        if not isinstance(file_rel, str) or not FILE_RE.fullmatch(file_rel):
            raise PayloadError(f"catalog.json: {where} local edition needs file under images/")
    else:
        if not isinstance(url, str) or not url.startswith(("http://", "https://")):
            raise PayloadError(f"catalog.json: {where} download edition needs a url")
        if file_rel is not None and (
            not isinstance(file_rel, str) or not FILE_RE.fullmatch(file_rel)
        ):
            raise PayloadError(f"catalog.json: {where} file must look like images/name.iso")

    available = edition_is_present(root, file_rel if isinstance(file_rel, str) else None)
    return Edition(
        id=eid,
        name=raw["name"].strip(),
        default=raw["default"],
        claimed_local=raw["local"],
        file=file_rel if isinstance(file_rel, str) else None,
        url=url if isinstance(url, str) else None,
        sha256=raw["sha256"],
        size_bytes=raw["size_bytes"],
        available=available,
    )


def _merge_others(recommended: list[Distro], catalog: list[Distro]) -> list[Distro]:
    return sorted(
        [*recommended, *catalog],
        key=lambda d: (d.name.casefold(), d.id),
    )


def _resolve_wallpaper(root: str, rel: str, _key: str) -> str | None:
    if _unsafe_relpath(rel):
        return None
    path = os.path.join(root, rel)
    if os.path.isfile(path):
        return os.path.abspath(path)
    return None


def _unsafe_relpath(rel: str) -> bool:
    if not rel or rel.startswith("/") or rel.startswith("\\"):
        return True
    parts = rel.replace("\\", "/").split("/")
    return any(p in ("", ".", "..") for p in parts)


def _read_text(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()
