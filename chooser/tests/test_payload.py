#!/usr/bin/env python3
"""Unit tests for firstboot.payload — no GTK."""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
CHOOSER_DIR = os.path.dirname(HERE)
if CHOOSER_DIR not in sys.path:
    sys.path.insert(0, CHOOSER_DIR)

from firstboot.payload import (  # noqa: E402
    load_payload,
    parse_retailer_conf,
    PayloadError,
    edition_is_present,
    other_options,
    recommended_offerings,
)

ZERO = "0" * 64

RETAILER = """\
schema_version = 1
name = Example Computers
support = support@example.com  /  012 345 6789
wallpaper_dark = wallpapers/dark.jpg
wallpaper_light = wallpapers/light.jpg
"""

UBUNTU = {
    "id": "ubuntu",
    "name": "Ubuntu",
    "version": "26.04 LTS",
    "tagline": "Popular and well-supported",
    "description": "A polished desktop.",
    "family": "ubuntu",
    "install": "ubuntu-autoinstall",
    "editions": [
        {
            "id": "gnome",
            "name": "GNOME",
            "default": True,
            "local": True,
            "file": "images/ubuntu-26.04-desktop-amd64.iso",
            "sha256": ZERO,
            "size_bytes": 5900000000,
        }
    ],
}

MINT = {
    "id": "linux-mint",
    "name": "Linux Mint",
    "version": "22.3",
    "tagline": "Familiar and easy",
    "description": "A stable desktop.",
    "family": "mint",
    "install": "mint",
    "editions": [
        {
            "id": "cinnamon",
            "name": "Cinnamon",
            "default": True,
            "local": True,
            "file": "images/linuxmint-22.3-cinnamon-64bit.iso",
            "sha256": ZERO,
            "size_bytes": 2800000000,
        },
        {
            "id": "mate",
            "name": "MATE",
            "default": False,
            "local": False,
            "url": "https://mirrors.kernel.org/linuxmint/stable/22.3/linuxmint-22.3-mate-64bit.iso",
            "sha256": ZERO,
            "size_bytes": 2600000000,
        },
    ],
}


def _write(root: str, rel: str, body: str | bytes) -> str:
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    mode = "wb" if isinstance(body, bytes) else "w"
    with open(path, mode, encoding=None if isinstance(body, bytes) else "utf-8") as fh:
        fh.write(body)
    return path


class ParseRetailerTests(unittest.TestCase):
    def test_comments_and_spaces(self) -> None:
        data = parse_retailer_conf(
            "# hi\n\nname = Example Computers\nschema_version = 1\n"
        )
        self.assertEqual(data["name"], "Example Computers")
        self.assertEqual(data["schema_version"], "1")

    def test_bad_line(self) -> None:
        with self.assertRaises(PayloadError):
            parse_retailer_conf("not-a-pair\n")


class LoadPayloadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="fbl-payload-")
        _write(self.tmp, "retailer.conf", RETAILER)
        _write(self.tmp, "wallpapers/dark.jpg", b"dark")
        _write(self.tmp, "wallpapers/light.jpg", b"light")
        _write(
            self.tmp,
            "catalog.json",
            json.dumps(
                {"schema_version": 1, "recommended": [UBUNTU, MINT], "catalog": []}
            ),
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp)

    def test_missing_directory(self) -> None:
        p = load_payload(os.path.join(self.tmp, "nope"))
        self.assertIsNone(p.retailer)
        self.assertTrue(any("missing" in e for e in p.errors))

    def test_retailer_and_wallpapers(self) -> None:
        p = load_payload(self.tmp)
        self.assertIsNotNone(p.retailer)
        assert p.retailer is not None
        self.assertEqual(p.retailer.name, "Example Computers")
        self.assertEqual(p.retailer.language, "en-us")
        self.assertEqual(p.retailer.keyboard, "us")
        self.assertIsNone(p.retailer.timezone)
        self.assertTrue(p.wallpaper_dark and p.wallpaper_dark.endswith("dark.jpg"))
        self.assertTrue(p.wallpaper_light and p.wallpaper_light.endswith("light.jpg"))

    def test_retailer_language_optional(self) -> None:
        _write(
            self.tmp,
            "retailer.conf",
            RETAILER + "language = af\n",
        )
        p = load_payload(self.tmp)
        assert p.retailer is not None
        self.assertEqual(p.retailer.language, "af")

    def test_retailer_en_alias_is_en_us(self) -> None:
        _write(
            self.tmp,
            "retailer.conf",
            RETAILER + "language = en\n",
        )
        p = load_payload(self.tmp)
        assert p.retailer is not None
        self.assertEqual(p.retailer.language, "en-us")

    def test_retailer_keyboard_optional(self) -> None:
        _write(
            self.tmp,
            "retailer.conf",
            RETAILER + "keyboard = gb\n",
        )
        p = load_payload(self.tmp)
        assert p.retailer is not None
        self.assertEqual(p.retailer.keyboard, "gb")
        self.assertEqual(p.retailer.language, "en-us")

    def test_retailer_timezone_optional(self) -> None:
        _write(
            self.tmp,
            "retailer.conf",
            RETAILER + "timezone = UTC+0200\n",
        )
        p = load_payload(self.tmp)
        assert p.retailer is not None
        self.assertEqual(p.retailer.timezone, "UTC+0200")

    def test_retailer_unknown_keys_do_not_drop_wallpapers(self) -> None:
        _write(
            self.tmp,
            "retailer.conf",
            RETAILER + "future_flag = yes\n",
        )
        p = load_payload(self.tmp)
        assert p.retailer is not None
        self.assertEqual(p.retailer.name, "Example Computers")
        self.assertTrue(p.wallpaper_dark and p.wallpaper_dark.endswith("dark.jpg"))
        self.assertFalse(any("unknown keys" in e for e in p.errors))

    def test_local_is_file_present_not_json_flag(self) -> None:
        p = load_payload(self.tmp)
        ubuntu = next(d for d in p.recommended if d.id == "ubuntu")
        self.assertTrue(ubuntu.default_edition.claimed_local)
        self.assertFalse(ubuntu.default_edition.available)
        self.assertEqual(ubuntu.default_edition.action, "download")

        _write(self.tmp, "images/ubuntu-26.04-desktop-amd64.iso", b"iso")
        p = load_payload(self.tmp)
        ubuntu = next(d for d in p.recommended if d.id == "ubuntu")
        self.assertTrue(ubuntu.default_edition.available)
        self.assertEqual(ubuntu.default_edition.action, "install")

        mint = next(d for d in p.recommended if d.id == "linux-mint")
        mate = next(e for e in mint.editions if e.id == "mate")
        self.assertFalse(mate.claimed_local)
        self.assertFalse(mate.available)

    def test_others_is_recommended_then_catalog_sorted(self) -> None:
        extra = {
            "id": "debian",
            "name": "Debian",
            "version": "13",
            "tagline": "Rock-solid base",
            "description": "Stable.",
            "family": "debian",
            "install": "debian-preseed",
            "editions": [
                {
                    "id": "gnome",
                    "name": "GNOME",
                    "default": True,
                    "local": False,
                    "url": "https://example.invalid/debian.iso",
                    "sha256": ZERO,
                    "size_bytes": 3500000000,
                }
            ],
        }
        _write(
            self.tmp,
            "catalog.json",
            json.dumps(
                {"schema_version": 1, "recommended": [UBUNTU, MINT], "catalog": [extra]}
            ),
        )
        p = load_payload(self.tmp)
        self.assertEqual([d.id for d in p.recommended], ["ubuntu", "linux-mint"])
        self.assertEqual([d.id for d in p.catalog], ["debian"])
        self.assertEqual([d.id for d in p.others], ["debian", "linux-mint", "ubuntu"])

    def test_duplicate_id_rejected(self) -> None:
        _write(
            self.tmp,
            "catalog.json",
            json.dumps(
                {"schema_version": 1, "recommended": [UBUNTU], "catalog": [UBUNTU]}
            ),
        )
        p = load_payload(self.tmp)
        self.assertTrue(any("duplicate id" in e for e in p.errors))
        self.assertEqual(p.recommended, [])

    def test_path_traversal_wallpaper_rejected(self) -> None:
        _write(
            self.tmp,
            "retailer.conf",
            RETAILER.replace("wallpapers/dark.jpg", "../etc/passwd"),
        )
        p = load_payload(self.tmp)
        self.assertIsNone(p.retailer)
        self.assertTrue(any("safe relative path" in e for e in p.errors))

    def test_bad_schema_version(self) -> None:
        _write(
            self.tmp,
            "catalog.json",
            json.dumps({"schema_version": 2, "recommended": [], "catalog": []}),
        )
        p = load_payload(self.tmp)
        self.assertTrue(any("schema_version" in e for e in p.errors))

    def test_empty_catalog_is_ok(self) -> None:
        _write(
            self.tmp,
            "catalog.json",
            json.dumps({"schema_version": 1, "recommended": [], "catalog": []}),
        )
        p = load_payload(self.tmp)
        self.assertEqual(p.recommended, [])
        self.assertEqual(p.others, [])
        self.assertFalse(any(e.startswith("catalog.json:") for e in p.errors))

    def test_repo_example_catalog(self) -> None:
        repo = os.path.abspath(os.path.join(CHOOSER_DIR, ".."))
        example = os.path.join(repo, "schemas", "examples")
        p = load_payload(example)
        self.assertIsNotNone(p.retailer)
        self.assertEqual([d.id for d in p.recommended], ["ubuntu"])
        self.assertEqual(p.catalog, [])
        self.assertTrue(all(not d.default_edition.available for d in p.recommended))

    def test_dummy_payload_catalog(self) -> None:
        repo = os.path.abspath(os.path.join(CHOOSER_DIR, ".."))
        dummy = os.path.join(repo, "image", "dummy-payload")
        p = load_payload(dummy)
        self.assertIsNotNone(p.retailer)
        self.assertEqual([d.id for d in p.recommended], ["ubuntu"])
        self.assertEqual(p.catalog, [])
        ubuntu = p.recommended[0]
        self.assertEqual(ubuntu.install, "ubuntu-2604-gnome")
        self.assertEqual([e.id for e in ubuntu.editions], ["gnome"])

    def test_recommended_download_only_is_ok(self) -> None:
        windows = {
            "id": "ms-windows",
            "name": "MS Windows",
            "version": "11",
            "tagline": "Familiar and widely used",
            "description": "Download only.",
            "family": "windows",
            "install": "windows",
            "editions": [
                {
                    "id": "windows-11",
                    "name": "Windows 11",
                    "default": True,
                    "local": False,
                    "url": "https://example.invalid/windows.iso",
                    "sha256": ZERO,
                    "size_bytes": 6500000000,
                }
            ],
        }
        _write(
            self.tmp,
            "catalog.json",
            json.dumps(
                {
                    "schema_version": 1,
                    "recommended": [UBUNTU, windows],
                    "catalog": [],
                }
            ),
        )
        p = load_payload(self.tmp)
        self.assertEqual([d.id for d in p.recommended], ["ubuntu", "ms-windows"])
        win = next(d for d in p.recommended if d.id == "ms-windows")
        self.assertEqual(win.install, "windows")
        self.assertEqual(win.family, "windows")
        self.assertEqual(win.name, "MS Windows")
        self.assertEqual(win.catalog_name, "Microsoft Windows")
        ubuntu = next(d for d in p.recommended if d.id == "ubuntu")
        self.assertEqual(ubuntu.catalog_name, "Ubuntu")
        self.assertFalse(win.default_edition.claimed_local)
        self.assertFalse(win.default_edition.available)
        self.assertEqual(win.default_edition.action, "download")

    def test_recommended_offerings_are_local_desktops(self) -> None:
        mint = {
            "id": "linux-mint",
            "name": "Linux Mint",
            "version": "22.3",
            "tagline": "Familiar and easy",
            "description": "A stable desktop.",
            "family": "mint",
            "install": "mint-223",
            "editions": [
                {
                    "id": "cinnamon",
                    "name": "Cinnamon",
                    "default": False,
                    "local": False,
                    "url": "https://example.invalid/cinnamon.iso",
                    "sha256": ZERO,
                    "size_bytes": 2800000000,
                },
                {
                    "id": "mate",
                    "name": "MATE",
                    "default": True,
                    "local": True,
                    "file": "images/linuxmint-22.3-mate-64bit.iso",
                    "sha256": ZERO,
                    "size_bytes": 2600000000,
                },
                {
                    "id": "xfce",
                    "name": "Xfce",
                    "default": False,
                    "local": True,
                    "file": "images/linuxmint-22.3-xfce-64bit.iso",
                    "sha256": ZERO,
                    "size_bytes": 2500000000,
                },
            ],
        }
        fedora = {
            "id": "fedora",
            "name": "Fedora",
            "version": "44",
            "tagline": "Modern Plasma desktop",
            "description": "Plasma.",
            "family": "fedora",
            "install": "fedora-44-plasma",
            "editions": [
                {
                    "id": "plasma",
                    "name": "KDE Plasma",
                    "default": True,
                    "local": True,
                    "file": "images/Fedora-KDE-Desktop-Live-44-1.7.x86_64.iso",
                    "sha256": ZERO,
                    "size_bytes": 2800000000,
                }
            ],
        }
        _write(
            self.tmp,
            "catalog.json",
            json.dumps(
                {
                    "schema_version": 1,
                    "recommended": [mint, fedora],
                    "catalog": [UBUNTU],
                }
            ),
        )
        p = load_payload(self.tmp)
        cards = recommended_offerings(p.recommended)
        self.assertEqual(
            [(d.id, e.id) for d, e in cards],
            [("linux-mint", "mate"), ("linux-mint", "xfce"), ("fedora", "plasma")],
        )
        mint_d = next(d for d in p.others if d.id == "linux-mint")
        by_id = {e.id: e for e in mint_d.editions}
        self.assertFalse(by_id["cinnamon"].claimed_local)
        self.assertTrue(by_id["mate"].claimed_local)
        self.assertTrue(by_id["xfce"].claimed_local)
        self.assertEqual(by_id["cinnamon"].action, "download")
        _write(self.tmp, "images/linuxmint-22.3-mate-64bit.iso", b"iso")
        _write(self.tmp, "images/linuxmint-22.3-xfce-64bit.iso", b"iso")
        p = load_payload(self.tmp)
        by_id = {e.id: e for e in p.recommended[0].editions}
        self.assertEqual(by_id["cinnamon"].action, "download")
        self.assertEqual(by_id["mate"].action, "install")
        self.assertEqual(by_id["xfce"].action, "install")

    def test_edition_is_present_rejects_unsafe(self) -> None:
        self.assertFalse(edition_is_present(self.tmp, "../catalog.json"))
        self.assertFalse(edition_is_present(self.tmp, "/etc/passwd"))
        self.assertFalse(edition_is_present(self.tmp, None))

    def test_custom_install_needs_pack(self) -> None:
        pop = {
            "id": "pop-os",
            "name": "Pop!_OS",
            "version": "22.04",
            "tagline": "t",
            "description": "d",
            "family": "other",
            "install": "pop-os",
            "editions": [
                {
                    "id": "gnome",
                    "name": "GNOME",
                    "default": True,
                    "local": True,
                    "file": "images/pop-os_22.04_amd64_intel.iso",
                    "sha256": ZERO,
                    "size_bytes": 1,
                }
            ],
        }
        _write(
            self.tmp,
            "catalog.json",
            json.dumps({"schema_version": 1, "recommended": [pop], "catalog": []}),
        )
        p = load_payload(self.tmp)
        self.assertTrue(any("unknown install driver" in e for e in p.errors))
        _write(self.tmp, "custom/pop-os/driver.py", "DRIVER = object()\n")
        p = load_payload(self.tmp)
        self.assertFalse(any("unknown install driver" in e for e in p.errors))
        self.assertEqual(p.recommended[0].id, "pop-os")
        self.assertEqual(p.recommended[0].install, "pop-os")
        self.assertTrue(p.recommended[0].secure_boot)

    def test_secure_boot_field(self) -> None:
        pop = {
            "id": "pop-os",
            "name": "Pop!_OS",
            "version": "24.04 LTS",
            "tagline": "t",
            "description": "d",
            "family": "other",
            "install": "pop-os",
            "secure_boot": False,
            "editions": [
                {
                    "id": "cosmic",
                    "name": "COSMIC",
                    "default": True,
                    "local": True,
                    "file": "images/pop-os_24.04_amd64_generic_27.iso",
                    "sha256": ZERO,
                    "size_bytes": 1,
                }
            ],
        }
        _write(self.tmp, "custom/pop-os/driver.py", "DRIVER = object()\n")
        _write(
            self.tmp,
            "catalog.json",
            json.dumps(
                {"schema_version": 1, "recommended": [pop], "catalog": [UBUNTU]}
            ),
        )
        p = load_payload(self.tmp)
        self.assertFalse(p.recommended[0].secure_boot)
        self.assertTrue(p.catalog[0].secure_boot)
        hidden = other_options(p.recommended, p.catalog, secure_boot_on=True)
        self.assertEqual([d.id for d in hidden], ["pop-os", "ubuntu"])
        catalog_only = other_options([], p.catalog, secure_boot_on=True)
        self.assertEqual([d.id for d in catalog_only], ["ubuntu"])
        unsigned_catalog = other_options([], p.recommended, secure_boot_on=True)
        self.assertEqual(unsigned_catalog, [])
        kept = other_options(p.recommended, [], secure_boot_on=True)
        self.assertEqual([d.id for d in kept], ["pop-os"])
        shown = other_options(p.recommended, p.catalog, secure_boot_on=False)
        self.assertEqual({d.id for d in shown}, {"pop-os", "ubuntu"})


if __name__ == "__main__":
    unittest.main()
