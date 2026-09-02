#!/usr/bin/env python3
"""Ubuntu 26.04 GNOME native installer."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
CHOOSER_DIR = os.path.dirname(HERE)
if CHOOSER_DIR not in sys.path:
    sys.path.insert(0, CHOOSER_DIR)

from firstboot.installlocale import InstallLocale  # noqa: E402
from firstboot.osinstall.casper import (  # noqa: E402
    casper_squashfs_relpaths,
    write_esp_grub_stub,
)
from firstboot.osinstall.common import InstalledDisk, OsIdentity, is_native_driver  # noqa: E402
from firstboot.osinstall.ubuntu_2604_gnome import DRIVER, ID  # noqa: E402

UBUNTU_HASH = (
    "$6$exDY1mhS4KUYCE/2$"
    "zmn9ToZwTKLhCw.b4/b.ZRTIZM30JZ4QrOQ2aOXJ8yk96xpcCof0kxKwuX1kqLG/"
    "ygbJ1f8wxED22bTL4F46P0"
)


def fake_tree(root: str) -> None:
    boot = os.path.join(root, "boot")
    os.makedirs(boot)
    open(os.path.join(boot, "vmlinuz-6.17.0"), "wb").close()
    open(os.path.join(boot, "initrd.img-6.17.0"), "wb").close()
    for rel in (
        "etc",
        "etc/default",
        "etc/systemd/system",
        "usr/lib/systemd/system",
        "home",
        "etc/skel",
        "var/lib/dbus",
        "var/lib/dpkg",
    ):
        os.makedirs(os.path.join(root, rel), exist_ok=True)
    with open(os.path.join(root, "etc", "passwd"), "w", encoding="utf-8") as fh:
        fh.write("root:x:0:0:root:/root:/bin/bash\nubuntu:x:1000:1000:live:/home/ubuntu:/bin/bash\n")
    with open(os.path.join(root, "etc", "shadow"), "w", encoding="utf-8") as fh:
        fh.write("root:!:0:0:99999:7:::\nubuntu:*:0:0:99999:7:::\n")
    with open(os.path.join(root, "etc", "group"), "w", encoding="utf-8") as fh:
        fh.write("root:x:0:\nsudo:x:27:\nusers:x:100:\nubuntu:x:1000:\n")
    with open(
        os.path.join(root, "usr", "lib", "systemd", "system", "graphical.target"),
        "w",
        encoding="utf-8",
    ) as fh:
        fh.write("[Unit]\n")
    with open(
        os.path.join(root, "usr", "lib", "systemd", "system", "gdm.service"),
        "w",
        encoding="utf-8",
    ) as fh:
        fh.write("[Unit]\n")
    os.makedirs(os.path.join(root, "home", "ubuntu"), exist_ok=True)


def fake_esp(path: str) -> None:
    boot = os.path.join(path, "EFI", "BOOT")
    ubuntu = os.path.join(path, "EFI", "ubuntu")
    os.makedirs(boot)
    os.makedirs(ubuntu)
    open(os.path.join(boot, "BOOTX64.EFI"), "wb").close()
    open(os.path.join(ubuntu, "grubx64.efi"), "wb").close()


def disk_for(root: str, efi: str) -> InstalledDisk:
    return InstalledDisk(
        disk="/dev/vda",
        esp_dev="/dev/vda1",
        root_dev="/dev/vda2",
        esp_uuid="ESP-UUID-1111",
        root_uuid="ROOT-UUID-2222",
        esp_mp=efi,
        root_mp=root,
    )


class Ubuntu2604GnomeTests(unittest.TestCase):
    def test_driver_contract(self) -> None:
        self.assertEqual(ID, "ubuntu-2604-gnome")
        self.assertEqual(DRIVER.id, ID)
        self.assertEqual(DRIVER.aliases, ())
        self.assertEqual(DRIVER.unpack_kind, "casper-layered")
        self.assertEqual(DRIVER.display_manager, "gdm")
        self.assertEqual(DRIVER.live_usernames, ("ubuntu",))
        self.assertEqual(DRIVER.default_hostname, "ubuntu")
        self.assertTrue(is_native_driver(DRIVER))
        self.assertFalse(hasattr(DRIVER, "seed_files") and callable(DRIVER.seed_files))

    def test_layered_relpaths_skip_live(self) -> None:
        iso = tempfile.mkdtemp(prefix="fbl-iso-")
        try:
            casper = os.path.join(iso, "casper")
            os.makedirs(casper)
            for name in (
                "minimal.squashfs",
                "minimal.en.squashfs",
                "minimal.standard.squashfs",
                "minimal.standard.en.squashfs",
                "minimal.standard.live.squashfs",
                "minimal.enhanced-secureboot.squashfs",
                "minimal.standard.enhanced-secureboot.squashfs",
            ):
                open(os.path.join(casper, name), "wb").close()
            rels = DRIVER.squashfs_relpaths(iso)
            self.assertEqual(
                rels,
                [
                    "casper/minimal.squashfs",
                    "casper/minimal.en.squashfs",
                    "casper/minimal.standard.squashfs",
                    "casper/minimal.standard.en.squashfs",
                ],
            )
            self.assertFalse(any("live" in r for r in rels))
            self.assertFalse(any("enhanced-secureboot" in r for r in rels))
        finally:
            shutil.rmtree(iso, ignore_errors=True)

    def test_esp_grub_stub_points_at_root_uuid(self) -> None:
        efi = tempfile.mkdtemp(prefix="fbl-esp-stub-")
        try:
            write_esp_grub_stub(efi, "ubuntu", "ROOT-UUID-2222")
            path = os.path.join(efi, "EFI", "ubuntu", "grub.cfg")
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            self.assertIn("search.fs_uuid ROOT-UUID-2222 root", text)
            self.assertIn("set prefix=($root)'/boot/grub'", text)
            self.assertIn("configfile $prefix/grub.cfg", text)
            self.assertTrue(os.path.isfile(os.path.join(efi, "EFI", "BOOT", "grub.cfg")))
        finally:
            shutil.rmtree(efi, ignore_errors=True)

    def test_single_filesystem_squashfs_still_wins(self) -> None:
        iso = tempfile.mkdtemp(prefix="fbl-iso-")
        try:
            casper = os.path.join(iso, "casper")
            os.makedirs(casper)
            open(os.path.join(casper, "filesystem.squashfs"), "wb").close()
            open(os.path.join(casper, "minimal.squashfs"), "wb").close()
            self.assertEqual(
                casper_squashfs_relpaths(iso), ["casper/filesystem.squashfs"]
            )
        finally:
            shutil.rmtree(iso, ignore_errors=True)

    def test_configure_writes_customer_not_live_user(self) -> None:
        root = tempfile.mkdtemp(prefix="fbl-gnome-root-")
        efi = tempfile.mkdtemp(prefix="fbl-gnome-efi-")
        try:
            fake_tree(root)
            ident = OsIdentity("shop-pc", "leon", "Leon", UBUNTU_HASH)
            loc = InstallLocale()
            DRIVER.configure(root, ident, loc, disk_for(root, efi))
            def read(rel: str) -> str:
                with open(os.path.join(root, rel), encoding="utf-8") as fh:
                    return fh.read()

            passwd = read("etc/passwd")
            shadow = read("etc/shadow")
            self.assertIn("leon:", passwd)
            self.assertNotIn("ubuntu:", passwd)
            self.assertIn(UBUNTU_HASH, shadow)
            self.assertNotIn("\nubuntu:", shadow)
            lastchg = None
            for line in shadow.splitlines():
                if line.startswith("leon:"):
                    lastchg = int(line.split(":")[2])
                    break
            self.assertIsNotNone(lastchg)
            self.assertGreater(lastchg, 0)
            self.assertEqual(read("etc/hostname").strip(), "shop-pc")
            fstab = read("etc/fstab")
            self.assertIn("ROOT-UUID-2222", fstab)
            self.assertIn("ESP-UUID-1111", fstab)
            grub = read("etc/default/grub")
            self.assertNotIn("fbl.install", grub)
            self.assertNotIn("toram", grub)
            self.assertIn("quiet splash", grub)
            default = os.readlink(os.path.join(root, "etc", "systemd", "system", "default.target"))
            self.assertEqual(os.path.basename(default), "graphical.target")
        finally:
            shutil.rmtree(root, ignore_errors=True)
            shutil.rmtree(efi, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
