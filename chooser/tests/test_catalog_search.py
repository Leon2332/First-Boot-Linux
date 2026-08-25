#!/usr/bin/env python3
"""Unit tests for firstboot.catalog_search — no GTK."""

from __future__ import annotations

import os
import sys
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
CHOOSER_DIR = os.path.dirname(HERE)
if CHOOSER_DIR not in sys.path:
    sys.path.insert(0, CHOOSER_DIR)

from firstboot.catalog_search import (  # noqa: E402
    DIFFERENT,
    LESS_STRICT,
    MORE_STRICT,
    SAME,
    SearchIndex,
    catalog_index,
    filter_delta,
    fields,
    matches,
    tokens,
)
from firstboot.payload import Distro, Edition  # noqa: E402

ZERO = "0" * 64


def _ed(eid: str = "gnome", name: str = "GNOME", default: bool = True) -> Edition:
    return Edition(
        id=eid,
        name=name,
        default=default,
        claimed_local=False,
        file=None,
        url="https://example.invalid/x.iso",
        sha256=ZERO,
        size_bytes=1,
        available=False,
    )


def _distro(**kwargs: object) -> Distro:
    base: dict = {
        "id": "ubuntu",
        "name": "Ubuntu",
        "version": "26.04 LTS",
        "tagline": "Popular and well-supported",
        "description": "A polished desktop.",
        "family": "ubuntu",
        "install": "ubuntu-2604",
        "editions": (_ed(),),
        "recommended": True,
    }
    base.update(kwargs)
    return Distro(**base)


class TokenTests(unittest.TestCase):
    def test_split_and_casefold(self) -> None:
        self.assertEqual(tokens("  Mint   CIN "), ("mint", "cin"))

    def test_empty(self) -> None:
        self.assertEqual(tokens(""), ())
        self.assertEqual(tokens("   "), ())

    def test_matches_and(self) -> None:
        flds = ("linux mint", "22.3", "cinnamon")
        self.assertTrue(matches(flds, ()))
        self.assertTrue(matches(flds, ("mint",)))
        self.assertTrue(matches(flds, ("mint", "cin")))
        self.assertFalse(matches(flds, ("mint", "plasma")))
        self.assertFalse(matches(flds, ("t 2",)))


class DeltaTests(unittest.TestCase):
    def test_typing_narrows(self) -> None:
        self.assertEqual(filter_delta("", "u"), MORE_STRICT)
        self.assertEqual(filter_delta("u", "ub"), MORE_STRICT)
        self.assertEqual(filter_delta("mint", "mint cin"), MORE_STRICT)

    def test_deleting_widens(self) -> None:
        self.assertEqual(filter_delta("ubu", "ub"), LESS_STRICT)
        self.assertEqual(filter_delta("mint cin", "mint"), LESS_STRICT)
        self.assertEqual(filter_delta("u", ""), LESS_STRICT)

    def test_same_after_spaces(self) -> None:
        self.assertEqual(filter_delta("Mint", "  mint  "), SAME)
        self.assertEqual(filter_delta("a b", "a  b"), SAME)

    def test_rewrite_is_different(self) -> None:
        self.assertEqual(filter_delta("mint", "ubu"), DIFFERENT)


class HaystackTests(unittest.TestCase):
    def test_windows_catalog_name(self) -> None:
        win = _distro(
            id="ms-windows",
            name="MS Windows",
            version="11",
            tagline="Familiar and widely used",
            family="windows",
            install="windows",
            editions=(_ed("windows-11", "Windows 11"),),
            recommended=True,
        )
        flds = fields(win)
        self.assertIn("microsoft windows", flds)
        self.assertIn("ms windows", flds)
        self.assertNotIn("ms-windows", flds)
        self.assertNotIn("windows 11", flds)
        self.assertFalse(any("familiar" in f for f in flds))

    def test_name_only_not_version_or_edition(self) -> None:
        mint = _distro(
            id="linux-mint",
            name="Linux Mint",
            version="22.3",
            family="mint",
            install="mint-223",
            editions=(
                _ed("cinnamon", "Cinnamon", True),
                _ed("mate", "MATE", False),
            ),
            recommended=True,
        )
        flds = fields(mint)
        self.assertEqual(flds, ("linux mint",))
        self.assertNotIn("cinnamon", flds)
        self.assertNotIn("mate", flds)
        self.assertNotIn("22.3", flds)
        self.assertNotIn("linux-mint", flds)

    def test_tagline_is_not_searched(self) -> None:
        lubuntu = _distro(
            id="lubuntu",
            name="Lubuntu",
            version="26.04 LTS",
            tagline="Very lightweight",
            family="ubuntu",
            install="ubuntu-2604",
            editions=(_ed("lxqt", "LXQt"),),
        )
        idx = catalog_index([lubuntu])
        self.assertEqual(idx.search("v"), [])
        self.assertEqual(idx.search("very"), [])
        self.assertEqual(idx.search("light"), [])
        self.assertEqual(idx.search("lxqt"), [])
        self.assertEqual(idx.search("26.04"), [])
        self.assertEqual([d.id for d in idx.search("lubu")], ["lubuntu"])


class IndexTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ubuntu = _distro()
        self.mint = _distro(
            id="linux-mint",
            name="Linux Mint",
            version="22.3",
            tagline="Familiar and easy",
            family="mint",
            install="mint-223",
            editions=(_ed("cinnamon", "Cinnamon"),),
        )
        self.fedora = _distro(
            id="fedora",
            name="Fedora",
            version="44",
            tagline="Modern Plasma desktop",
            family="fedora",
            install="fedora-44-plasma",
            editions=(_ed("plasma", "KDE Plasma"),),
        )
        self.index = catalog_index([self.ubuntu, self.mint, self.fedora])

    def test_empty_query_is_sorted_by_catalog_name(self) -> None:
        hits = self.index.search("")
        self.assertEqual([d.id for d in hits], ["fedora", "linux-mint", "ubuntu"])

    def test_case_insensitive_name(self) -> None:
        hits = self.index.search("MiNt")
        self.assertEqual([d.id for d in hits], ["linux-mint"])

    def test_version_and_edition_tokens_are_ignored(self) -> None:
        self.assertEqual(self.index.search("44 plasma"), [])
        self.assertEqual(self.index.search("plasma"), [])
        self.assertEqual(self.index.search("22.3"), [])
        self.assertEqual(self.index.search("cinnamon"), [])
        self.assertEqual([d.id for d in self.index.search("fedora")], ["fedora"])

    def test_no_match(self) -> None:
        self.assertEqual(self.index.search("windows"), [])

    def test_incremental_narrowing(self) -> None:
        first = self.index.search("u")
        self.assertIn(self.ubuntu, first)
        self.assertEqual([d.id for d in self.index.search("ubuntu")], ["ubuntu"])
        widened = self.index.search("u")
        self.assertEqual(
            [d.id for d in widened],
            ["linux-mint", "ubuntu"],
        )


class ScaleTests(unittest.TestCase):
    def test_five_thousand_is_fast(self) -> None:
        items = [
            (f"distro-{i:04d}", (f"distro {i:04d}", "linux", "gnome"))
            for i in range(5000)
        ]
        index = SearchIndex(items)
        expected = [
            f"distro-{i:04d}"
            for i in range(5000)
            if "042" in f"distro {i:04d}"
        ]
        t0 = time.perf_counter()
        hits = index.search("distro 042")
        elapsed = time.perf_counter() - t0
        self.assertLess(elapsed, 0.05)
        self.assertEqual(hits, expected)
        t1 = time.perf_counter()
        narrow = index.search("distro 0421")
        self.assertLess(time.perf_counter() - t1, 0.01)
        self.assertEqual(narrow, ["distro-0421"])


if __name__ == "__main__":
    unittest.main()
