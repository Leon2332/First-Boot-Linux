#!/usr/bin/env python3
"""Fedora 44 Plasma driver only."""

from __future__ import annotations

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
CHOOSER_DIR = os.path.dirname(HERE)
if CHOOSER_DIR not in sys.path:
    sys.path.insert(0, CHOOSER_DIR)

from firstboot.osinstall import OsIdentity  # noqa: E402
from firstboot.osinstall.fedora_44_plasma import (  # noqa: E402
    DRIVER,
    ID,
    LIVEINST_WRAPPER,
    SQUASH_LINK,
    fedora_kernel_args,
    fedora_kickstart,
)

UBUNTU_HASH = (
    "$6$exDY1mhS4KUYCE/2$Zx9Rit70sU0wKFAKESECRET_k4l5m6n7o8p9q0r1s2t3"
)


class Fedora44PlasmaTests(unittest.TestCase):
    def test_driver_id(self) -> None:
        self.assertEqual(ID, "fedora-44-plasma")
        self.assertIn("fedora-kickstart", DRIVER.aliases)
        self.assertEqual(DRIVER.default_hostname, "fedora")

    def test_seed_files(self) -> None:
        ident = OsIdentity("shop-pc", "leon", "Leon", UBUNTU_HASH)
        files = DRIVER.seed_files(ident, "/dev/sda", "")
        self.assertIn("ks.cfg", files)
        self.assertIn("fbl-liveinst", files)
        self.assertIn("usr/libexec/fbl-link-squashfs", files)
        self.assertIn("etc/xdg/autostart/fbl-liveinst.desktop", files)

    def test_kickstart_is_liveimg_not_dnf(self) -> None:
        ident = OsIdentity("shop-pc", "leon", "Leon", UBUNTU_HASH)
        text = fedora_kickstart(ident, "/dev/sda")
        self.assertIn(f"liveimg --url=file://{SQUASH_LINK}", text)
        self.assertNotIn("%packages", text)
        self.assertNotIn("boot=casper", text)
        self.assertIn("liveinst.real", LIVEINST_WRAPPER)
        args = fedora_kernel_args(
            "/images/Fedora-KDE-Desktop-Live-44-1.7.x86_64.iso",
            "Fedora-KDE-Live-44",
            toram=True,
        )
        self.assertNotIn("liveinst", args.split())
        self.assertNotIn("inst.ks", args)
