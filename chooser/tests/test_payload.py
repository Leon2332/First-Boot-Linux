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
        self.assertTrue(p.wallpaper_dark and p.wallpaper_dark.endswith("dark.jpg"))
        self.assertTrue(p.wallpaper_light and p.wallpaper_light.endswith("light.jpg"))

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
        self.assertEqual([d.id for d in p.recommended], ["ubuntu", "linux-mint"])
        self.assertTrue(all(not d.default_edition.available for d in p.recommended))

    def test_dummy_payload_catalog(self) -> None:
        repo = os.path.abspath(os.path.join(CHOOSER_DIR, ".."))
        dummy = os.path.join(repo, "image", "dummy-payload")
        p = load_payload(dummy)
        self.assertIsNotNone(p.retailer)
        self.assertEqual([d.id for d in p.recommended], ["ubuntu", "linux-mint"])
        mint = next(d for d in p.recommended if d.id == "linux-mint")
        self.assertEqual([e.id for e in mint.editions], ["cinnamon", "mate", "xfce"])
        self.assertTrue(all(not e.available for e in mint.editions))
        self.assertEqual(mint.editions[0].action, "download")
        self.assertEqual(mint.editions[1].action, "download")

    def test_edition_is_present_rejects_unsafe(self) -> None:
        self.assertFalse(edition_is_present(self.tmp, "../catalog.json"))
        self.assertFalse(edition_is_present(self.tmp, "/etc/passwd"))
        self.assertFalse(edition_is_present(self.tmp, None))


if __name__ == "__main__":
    unittest.main()
