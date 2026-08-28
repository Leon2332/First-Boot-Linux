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
from firstboot.osinstall.fedora_44_plasma import fedora_kickstart  # noqa: E402
from firstboot.osinstall.mint_223 import mint_preseed  # noqa: E402
from firstboot.osinstall.ubuntu_2604 import autoinstall_yaml  # noqa: E402
from firstboot.osinstall.common import OsIdentity  # noqa: E402

HASH = (
    "$6$exDY1mhS4KUYCE/2$"
    "zmn9ToZwTKLhCw.b4/b.ZRTIZM30JZ4QrOQ2aOXJ8yk96xpcCof0kxKwuX1kqLG/"
    "ygbJ1f8wxED22bTL4F46P0"
)
IDENT = OsIdentity("shop-pc", "leon", "Leon", HASH)


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
        text = autoinstall_yaml(IDENT, "/dev/sda", locale=loc)
        self.assertIn("locale: en_GB.UTF-8", text)
        self.assertIn("layout: us", text)
        self.assertNotIn("language-pack-af", text)

    def test_ubuntu_south_african_english(self) -> None:
        loc = resolve_install_locale("en-za", "za")
        text = autoinstall_yaml(IDENT, "/dev/sda", locale=loc)
        self.assertIn("locale: en_ZA.UTF-8", text)
        self.assertIn("layout: za", text)
        self.assertNotIn("language-pack-af", text)

    def test_ubuntu_afrikaans_language_pack(self) -> None:
        loc = resolve_install_locale("af", "gb")
        text = autoinstall_yaml(IDENT, "/dev/sda", locale=loc)
        self.assertIn("locale: af_ZA.UTF-8", text)
        self.assertIn("layout: gb", text)
        self.assertIn("language-pack-af", text)
        self.assertIn("language-pack-gnome-af", text)

    def test_mint_uk(self) -> None:
        loc = resolve_install_locale("en-gb", "gb")
        text = mint_preseed(IDENT, "/dev/sda", locale=loc)
        self.assertIn("debian-installer/locale string en_GB.UTF-8", text)
        self.assertIn("countrychooser/shortlist select GB", text)
        self.assertIn("keyboard-configuration/layoutcode string gb", text)
        self.assertIn("pkgsel/install-language-support boolean true", text)

    def test_fedora_afrikaans_us_keyboard(self) -> None:
        loc = resolve_install_locale("af", "us")
        text = fedora_kickstart(IDENT, "/dev/sda", locale=loc)
        self.assertIn("lang af_ZA.UTF-8", text)
        self.assertIn("keyboard --vckeymap=us --xlayouts='us'", text)
        self.assertNotIn("%packages", text)


if __name__ == "__main__":
    unittest.main()
