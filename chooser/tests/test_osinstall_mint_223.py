#!/usr/bin/env python3
"""Linux Mint 22.3 driver only."""

from __future__ import annotations

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
CHOOSER_DIR = os.path.dirname(HERE)
if CHOOSER_DIR not in sys.path:
    sys.path.insert(0, CHOOSER_DIR)

from firstboot.osinstall import OsIdentity  # noqa: E402
from firstboot.osinstall.mint_223 import DRIVER, ID, LINUX_EXTRA, mint_preseed  # noqa: E402

UBUNTU_HASH = (
    "$6$exDY1mhS4KUYCE/2$Zx9Rit70sU0wKFAKESECRET_k4l5m6n7o8p9q0r1s2t3"
)


class Mint223Tests(unittest.TestCase):
    def test_driver_id(self) -> None:
        self.assertEqual(ID, "mint-223")
        self.assertIn("mint", DRIVER.aliases)
        self.assertEqual(DRIVER.default_hostname, "mint")

    def test_shared_by_all_mint_catalog_rows(self) -> None:
        from firstboot.osinstall import get_driver

        self.assertIs(get_driver("mint-223"), DRIVER)
        self.assertIs(get_driver("mint"), DRIVER)

    def test_seed_files(self) -> None:
        ident = OsIdentity("shop-pc", "leon", "Leon", UBUNTU_HASH)
        files = DRIVER.seed_files(ident, "/dev/sda", "")
        self.assertIn("preseed.cfg", files)
        self.assertIn("usr/lib/firstboot-efi-cleanup", files)
        self.assertIn("scripts/casper-bottom/29fbl-mint", files)
        self.assertIn("automatic-ubiquity", LINUX_EXTRA)
        self.assertNotIn("only-ubiquity", LINUX_EXTRA)

    def test_preseed(self) -> None:
        ident = OsIdentity("shop-pc", "leon", "Leon", UBUNTU_HASH)
        text = mint_preseed(ident, "/dev/sda")
        self.assertNotIn("autoinstall:", text)
        self.assertIn("d-i passwd/username string leon", text)
        self.assertIn("ubiquity ubiquity/reboot_on_failure boolean false", text)
