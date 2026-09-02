#!/usr/bin/env python3
"""Install locale mapping — language and keyboard stay independent."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
CHOOSER_DIR = os.path.dirname(HERE)
if CHOOSER_DIR not in sys.path:
    sys.path.insert(0, CHOOSER_DIR)

from firstboot.installlocale import (  # noqa: E402
    payload_install_locale,
    resolve_install_locale,
)
from firstboot.osinstall.casper import write_locale  # noqa: E402


class ResolveTests(unittest.TestCase):
    def test_defaults(self) -> None:
        loc = resolve_install_locale()
        self.assertEqual(loc.language, "en-us")
        self.assertEqual(loc.glibc, "en_US.UTF-8")
        self.assertEqual(loc.keyboard, "us")
        self.assertEqual(loc.langpack, "en")

    def test_uk_english_keeps_separate_keyboard(self) -> None:
        loc = resolve_install_locale("en-gb", "us")
        self.assertEqual(loc.language, "en-gb")
        self.assertEqual(loc.glibc, "en_GB.UTF-8")
        self.assertEqual(loc.keyboard, "us")
        self.assertEqual(loc.langpack, "en")

    def test_south_african_english_locale(self) -> None:
        loc = resolve_install_locale("en-za", "us")
        self.assertEqual(loc.language, "en-za")
        self.assertEqual(loc.glibc, "en_ZA.UTF-8")
        self.assertEqual(loc.di_country, "ZA")
        self.assertEqual(loc.keyboard, "us")
        self.assertEqual(loc.langpack, "en")

    def test_afrikaans_does_not_force_za_keyboard(self) -> None:
        loc = resolve_install_locale("af", "us")
        self.assertEqual(loc.glibc, "af_ZA.UTF-8")
        self.assertEqual(loc.keyboard, "us")
        self.assertEqual(loc.langpack, "af")
        self.assertEqual(loc.di_country, "ZA")

    def test_payload_prefers_files(self) -> None:
        with tempfile.TemporaryDirectory(prefix="fbl-iloc-") as tmp:
            with open(os.path.join(tmp, "language"), "w", encoding="utf-8") as fh:
                fh.write("en-gb\n")
            with open(os.path.join(tmp, "keyboard"), "w", encoding="utf-8") as fh:
                fh.write("de\n")
            loc = payload_install_locale(tmp)
            self.assertEqual(loc.language, "en-gb")
            self.assertEqual(loc.keyboard, "de")


class SeedTests(unittest.TestCase):
    def test_ubuntu_uk_locale_us_keyboard(self) -> None:
        loc = resolve_install_locale("en-gb", "us")
        with tempfile.TemporaryDirectory() as tmp:
            write_locale(tmp, loc)
            with open(os.path.join(tmp, "etc", "default", "locale"), encoding="utf-8") as fh:
                self.assertIn("LANG=en_GB.UTF-8", fh.read())
            with open(os.path.join(tmp, "etc", "default", "keyboard"), encoding="utf-8") as fh:
                self.assertIn('XKBLAYOUT="us"', fh.read())
            with open(os.path.join(tmp, "etc", "locale.gen"), encoding="utf-8") as fh:
                self.assertIn("en_GB.UTF-8 UTF-8", fh.read())

    def test_ubuntu_south_african_english(self) -> None:
        loc = resolve_install_locale("en-za", "za")
        with tempfile.TemporaryDirectory() as tmp:
            write_locale(tmp, loc)
            with open(os.path.join(tmp, "etc", "default", "locale"), encoding="utf-8") as fh:
                self.assertIn("LANG=en_ZA.UTF-8", fh.read())
            with open(os.path.join(tmp, "etc", "default", "keyboard"), encoding="utf-8") as fh:
                self.assertIn('XKBLAYOUT="za"', fh.read())

    def test_ubuntu_afrikaans_language_pack(self) -> None:
        loc = resolve_install_locale("af", "gb")
        self.assertEqual(loc.glibc, "af_ZA.UTF-8")
        self.assertEqual(loc.keyboard, "gb")
        self.assertEqual(loc.langpack, "af")
        with tempfile.TemporaryDirectory() as tmp:
            write_locale(tmp, loc)
            with open(os.path.join(tmp, "etc", "default", "locale"), encoding="utf-8") as fh:
                self.assertIn("LANG=af_ZA.UTF-8", fh.read())
            with open(os.path.join(tmp, "etc", "default", "keyboard"), encoding="utf-8") as fh:
                self.assertIn('XKBLAYOUT="gb"', fh.read())


if __name__ == "__main__":
    unittest.main()
