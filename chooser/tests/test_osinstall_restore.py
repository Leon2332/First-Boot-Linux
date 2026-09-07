#!/usr/bin/env python3
"""Restore First Boot after a failed customer install."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
CHOOSER_DIR = os.path.dirname(HERE)
if CHOOSER_DIR not in sys.path:
    sys.path.insert(0, CHOOSER_DIR)

from firstboot.disk import parse_helper_line  # noqa: E402
from firstboot.osinstall.restore import (  # noqa: E402
    PAYLOAD_SKIP,
    find_casper_kernel,
    find_live_squashfs,
    rescue_ready,
    snapshot_rescue,
    write_fbl_data,
    write_fbl_esp,
    write_fbl_sys,
)


class RestoreSnapshotTests(unittest.TestCase):
    def test_snapshot_keeps_shop_files_drops_isos(self) -> None:
        work = tempfile.mkdtemp(prefix="fbl-rescue-")
        live = tempfile.mkdtemp(prefix="fbl-live-")
        payload = tempfile.mkdtemp(prefix="fbl-payload-")
        try:
            casper = os.path.join(live, "casper")
            os.makedirs(casper)
            with open(os.path.join(casper, "vmlinuz"), "wb") as fh:
                fh.write(b"k")
            with open(os.path.join(casper, "initrd"), "wb") as fh:
                fh.write(b"i")
            os.makedirs(os.path.join(payload, "images"))
            os.makedirs(os.path.join(payload, "wallpapers"))
            with open(os.path.join(payload, "retailer.conf"), "w", encoding="utf-8") as fh:
                fh.write("name=Shop\n")
            with open(os.path.join(payload, "catalog.json"), "w", encoding="utf-8") as fh:
                fh.write("{}\n")
            with open(os.path.join(payload, "wallpapers", "dark.jpg"), "wb") as fh:
                fh.write(b"jpg")
            with open(os.path.join(payload, "images", "huge.iso"), "wb") as fh:
                fh.write(b"iso")
            hash_dir = os.path.join(live, "firstboot")
            os.makedirs(hash_dir)
            with open(os.path.join(hash_dir, "live-user.hash"), "w", encoding="utf-8") as fh:
                fh.write("$6$x\n")
            with mock.patch("firstboot.osinstall.restore.LIVE_MOUNTS", (live,)), mock.patch(
                "firstboot.osinstall.restore.RESCUE_DIR", work
            ), mock.patch(
                "firstboot.osinstall.restore.PAYLOAD_MOUNT", payload
            ):
                snapshot_rescue(payload)
                self.assertTrue(os.path.isfile(os.path.join(work, "casper", "vmlinuz")))
                self.assertTrue(os.path.isfile(os.path.join(work, "casper", "initrd")))
                self.assertTrue(os.path.isfile(os.path.join(work, "live-user.hash")))
                dest = os.path.join(work, "payload")
                self.assertTrue(os.path.isfile(os.path.join(dest, "retailer.conf")))
                self.assertTrue(os.path.isfile(os.path.join(dest, "catalog.json")))
                self.assertTrue(os.path.isfile(os.path.join(dest, "wallpapers", "dark.jpg")))
                self.assertFalse(os.path.isdir(os.path.join(dest, "images")))
                self.assertIn("images", PAYLOAD_SKIP)
        finally:
            shutil.rmtree(work, ignore_errors=True)
            shutil.rmtree(live, ignore_errors=True)
            shutil.rmtree(payload, ignore_errors=True)

    def test_rescue_ready_needs_squash_and_kernel(self) -> None:
        work = tempfile.mkdtemp(prefix="fbl-ready-")
        try:
            squash = os.path.join(work, "live.squashfs")
            with open(squash, "wb") as fh:
                fh.write(b"sq")
            os.makedirs(os.path.join(work, "rescue", "casper"))
            with open(os.path.join(work, "rescue", "casper", "vmlinuz"), "wb") as fh:
                fh.write(b"k")
            with open(os.path.join(work, "rescue", "casper", "initrd"), "wb") as fh:
                fh.write(b"i")
            with mock.patch("firstboot.osinstall.restore.RAM_DIR", work), mock.patch(
                "firstboot.osinstall.restore.RESCUE_DIR", os.path.join(work, "rescue")
            ), mock.patch(
                "firstboot.osinstall.restore.RESCUE_SQUASH", squash
            ), mock.patch(
                "firstboot.osinstall.restore.LIVE_MOUNTS", ()
            ):
                self.assertTrue(rescue_ready())
                self.assertTrue(find_live_squashfs().endswith("live.squashfs"))
                vmlinuz, initrd = find_casper_kernel()
                self.assertTrue(vmlinuz.endswith("vmlinuz"))
                self.assertTrue(initrd.endswith("initrd"))
        finally:
            shutil.rmtree(work, ignore_errors=True)


class RestoreWriteTests(unittest.TestCase):
    def test_write_sys_and_data_and_esp(self) -> None:
        work = tempfile.mkdtemp(prefix="fbl-write-")
        try:
            squash = os.path.join(work, "live.squashfs")
            with open(squash, "wb") as fh:
                fh.write(b"squash")
            casper = os.path.join(work, "rescue", "casper")
            os.makedirs(casper)
            with open(os.path.join(casper, "vmlinuz"), "wb") as fh:
                fh.write(b"kernel")
            with open(os.path.join(casper, "initrd"), "wb") as fh:
                fh.write(b"init")
            payload = os.path.join(work, "rescue", "payload")
            os.makedirs(os.path.join(payload, "wallpapers"))
            with open(os.path.join(payload, "retailer.conf"), "w", encoding="utf-8") as fh:
                fh.write("name=Shop\n")
            efi_src = os.path.join(work, "efi")
            os.makedirs(efi_src)
            with open(os.path.join(efi_src, "shimx64.efi"), "wb") as fh:
                fh.write(b"shim")
            with open(os.path.join(efi_src, "grubx64.efi"), "wb") as fh:
                fh.write(b"grub")
            gcd = os.path.join(work, "gcdx64.efi.signed")
            with open(gcd, "wb") as fh:
                fh.write(b"gcd")
            sys_mnt = os.path.join(work, "sys")
            data_mnt = os.path.join(work, "data")
            esp_mnt = os.path.join(work, "esp")
            os.makedirs(sys_mnt)
            os.makedirs(data_mnt)
            os.makedirs(esp_mnt)
            with mock.patch("firstboot.osinstall.restore.RAM_DIR", work), mock.patch(
                "firstboot.osinstall.restore.RESCUE_DIR", os.path.join(work, "rescue")
            ), mock.patch(
                "firstboot.osinstall.restore.RESCUE_SQUASH", squash
            ), mock.patch(
                "firstboot.osinstall.restore.LIVE_MOUNTS", ()
            ), mock.patch(
                "firstboot.osinstall.restore.SIGNED_EFI_DIR", efi_src
            ), mock.patch(
                "firstboot.osinstall.restore.GCDX64", gcd
            ), mock.patch(
                "firstboot.osinstall.restore._seed_version", return_value="0.7.2.1"
            ):
                write_fbl_sys(sys_mnt, "SYS-UUID-1")
                write_fbl_data(data_mnt)
                write_fbl_esp(esp_mnt)
            self.assertTrue(os.path.isfile(os.path.join(sys_mnt, "casper", "vmlinuz")))
            self.assertTrue(
                os.path.isfile(os.path.join(sys_mnt, "casper", "filesystem.squashfs"))
            )
            with open(os.path.join(sys_mnt, ".disk", "info"), encoding="utf-8") as fh:
                self.assertIn("0.7.2.1", fh.read())
            with open(
                os.path.join(sys_mnt, "boot", "grub", "grub.cfg"), encoding="utf-8"
            ) as fh:
                grub = fh.read()
            self.assertIn("live-media=/dev/disk/by-uuid/SYS-UUID-1", grub)
            self.assertIn("/casper/vmlinuz", grub)
            self.assertTrue(os.path.isfile(os.path.join(data_mnt, "retailer.conf")))
            self.assertTrue(os.path.isdir(os.path.join(data_mnt, "images")))
            boot = os.path.join(esp_mnt, "EFI", "BOOT")
            vendor = os.path.join(esp_mnt, "EFI", "firstboot")
            with open(os.path.join(boot, "BOOTX64.EFI"), "rb") as fh:
                self.assertEqual(fh.read(), b"shim")
            with open(os.path.join(boot, "grubx64.efi"), "rb") as fh:
                self.assertEqual(fh.read(), b"gcd")
            with open(os.path.join(vendor, "grubx64.efi"), "rb") as fh:
                self.assertEqual(fh.read(), b"gcd")
        finally:
            shutil.rmtree(work, ignore_errors=True)


class RestoreProtocolTests(unittest.TestCase):
    def test_wiped_line(self) -> None:
        ev = parse_helper_line("WIPED /dev/sda")
        self.assertEqual(ev.kind, "wiped")
        self.assertEqual(ev.text, "/dev/sda")


if __name__ == "__main__":
    unittest.main()
