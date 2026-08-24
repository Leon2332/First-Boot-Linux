#!/usr/bin/env python3
"""Ubuntu 26.04 driver only."""

from __future__ import annotations

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
CHOOSER_DIR = os.path.dirname(HERE)
if CHOOSER_DIR not in sys.path:
    sys.path.insert(0, CHOOSER_DIR)

from firstboot.osinstall import OsIdentity, autoinstall_yaml  # noqa: E402
from firstboot.osinstall.ubuntu_2604 import DRIVER, ID, LINUX_EXTRA  # noqa: E402

UBUNTU_HASH = "$6$exDY1mhS4KUYCE/2$Zx9Rit70sU0wKFAKESECRET_k4l5m6n7o8p9q0r1s2t3"


class Ubuntu2604Tests(unittest.TestCase):
    def test_driver_id(self) -> None:
        self.assertEqual(ID, "ubuntu-2604")
        self.assertEqual(DRIVER.id, ID)
        self.assertIn("ubuntu-autoinstall", DRIVER.aliases)

    def test_seed_files(self) -> None:
        ident = OsIdentity("shop-pc", "leon", "Leon", UBUNTU_HASH)
        files = DRIVER.seed_files(ident, "/dev/sda", "")
        self.assertIn("autoinstall.yaml", files)
        self.assertIn("user-data", files)
        self.assertIn("scripts/casper-bottom/29fbl-autoinstall", files)
        self.assertIn("autoinstall", LINUX_EXTRA)

    def test_yaml(self) -> None:
        ident = OsIdentity("shop-pc", "leon", "Leon", UBUNTU_HASH)
        text = autoinstall_yaml(ident, "/dev/sda")
        self.assertIn("autoinstall:", text)
        self.assertIn('hostname: "shop-pc"', text)
        self.assertNotIn("/dev/disk/by-id/", text)
        self.assertIn("/media/filesystem", text)
