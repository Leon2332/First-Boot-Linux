#!/usr/bin/env python3
"""Linux Mint 22.3 Cinnamon native installer."""

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
from firstboot.osinstall.casper import casper_squashfs_relpaths  # noqa: E402
from firstboot.osinstall.common import InstalledDisk, OsIdentity, is_native_driver  # noqa: E402
from firstboot.osinstall.mint_223_cinnamon import DRIVER, ID  # noqa: E402

UBUNTU_HASH = (
    "$6$exDY1mhS4KUYCE/2$"
    "zmn9ToZwTKLhCw.b4/b.ZRTIZM30JZ4QrOQ2aOXJ8yk96xpcCof0kxKwuX1kqLG/"
    "ygbJ1f8wxED22bTL4F46P0"
)


def fake_tree(root: str) -> None:
    boot = os.path.join(root, "boot")
    os.makedirs(boot)
    open(os.path.join(boot, "vmlinuz-6.8.0"), "wb").close()
    open(os.path.join(boot, "initrd.img-6.8.0"), "wb").close()
    for rel in (
        "etc",
        "etc/default",
        "etc/systemd/system",
        "etc/lightdm/lightdm.conf.d",
        "usr/lib/systemd/system",
        "usr/share/lightdm/lightdm.conf.d",
        "home",
        "etc/skel",
        "var/lib/dbus",
        "var/lib/dpkg",
    ):
        os.makedirs(os.path.join(root, rel), exist_ok=True)
    with open(os.path.join(root, "etc", "passwd"), "w", encoding="utf-8") as fh:
        fh.write("root:x:0:0:root:/root:/bin/bash\nmint:x:1000:1000:live:/home/mint:/bin/bash\n")
    with open(os.path.join(root, "etc", "shadow"), "w", encoding="utf-8") as fh:
        fh.write("root:!:0:0:99999:7:::\nmint:*:0:0:99999:7:::\n")
    with open(os.path.join(root, "etc", "group"), "w", encoding="utf-8") as fh:
        fh.write("root:x:0:\nsudo:x:27:\nusers:x:100:\nmint:x:1000:\n")
    with open(
        os.path.join(root, "usr", "lib", "systemd", "system", "graphical.target"),
        "w",
        encoding="utf-8",
    ) as fh:
        fh.write("[Unit]\n")
    with open(
        os.path.join(root, "usr", "lib", "systemd", "system", "lightdm.service"),
        "w",
        encoding="utf-8",
    ) as fh:
        fh.write("[Unit]\n")
    os.makedirs(os.path.join(root, "home", "mint"), exist_ok=True)
    with open(
        os.path.join(root, "etc", "lightdm", "lightdm.conf"),
        "w",
        encoding="utf-8",
    ) as fh:
        fh.write(
            "[Seat:*]\n"
            "autologin-user=mint\n"
            "autologin-session=cinnamon\n"
            "user-session=cinnamon\n"
        )
    with open(
        os.path.join(root, "etc", "lightdm", "lightdm.conf.d", "90-linuxmint.conf"),
        "w",
        encoding="utf-8",
    ) as fh:
        fh.write("[Seat:*]\nautologin-user=mint\ngreeter-session=slick-greeter\n")
    with open(
        os.path.join(root, "etc", "lightdm", "lightdm.conf.d", "90-casper.conf"),
        "w",
        encoding="utf-8",
    ) as fh:
        fh.write("[Seat:*]\nautologin-user=mint\n")


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


class Mint223CinnamonTests(unittest.TestCase):
    def test_driver_contract(self) -> None:
        self.assertEqual(ID, "mint-223-cinnamon")
        self.assertEqual(DRIVER.id, ID)
        self.assertEqual(DRIVER.aliases, ())
        self.assertEqual(DRIVER.unpack_kind, "casper-single")
        self.assertEqual(DRIVER.display_manager, "lightdm")
        self.assertEqual(DRIVER.live_usernames, ("mint",))
        self.assertEqual(DRIVER.default_hostname, "mint")
        self.assertEqual(DRIVER.bootloader_id, "ubuntu")
        self.assertEqual(DRIVER.nvram_label, "Linux Mint")
        self.assertTrue(is_native_driver(DRIVER))
        self.assertFalse(hasattr(DRIVER, "seed_files") and callable(DRIVER.seed_files))

    def test_single_filesystem_squashfs(self) -> None:
        iso = tempfile.mkdtemp(prefix="fbl-mint-iso-")
        try:
            casper = os.path.join(iso, "casper")
            os.makedirs(casper)
            open(os.path.join(casper, "filesystem.squashfs"), "wb").close()
            self.assertEqual(
                DRIVER.squashfs_relpaths(iso), ["casper/filesystem.squashfs"]
            )
            self.assertEqual(
                casper_squashfs_relpaths(iso), ["casper/filesystem.squashfs"]
            )
        finally:
            shutil.rmtree(iso, ignore_errors=True)

    def test_configure_writes_customer_not_live_user(self) -> None:
        root = tempfile.mkdtemp(prefix="fbl-mint-root-")
        efi = tempfile.mkdtemp(prefix="fbl-mint-efi-")
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
            self.assertNotIn("mint:", passwd)
            self.assertIn(UBUNTU_HASH, shadow)
            self.assertNotIn("\nmint:", shadow)
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
            default = os.readlink(
                os.path.join(root, "etc", "systemd", "system", "default.target")
            )
            self.assertEqual(os.path.basename(default), "graphical.target")
            dm = os.readlink(
                os.path.join(root, "etc", "systemd", "system", "display-manager.service")
            )
            self.assertEqual(os.path.basename(dm), "lightdm.service")
            lightdm = read("etc/lightdm/lightdm.conf")
            self.assertNotIn("autologin-user", lightdm)
            self.assertNotIn("autologin-session", lightdm)
            self.assertIn("user-session=cinnamon", lightdm)
            drop = os.path.join(root, "etc", "lightdm", "lightdm.conf.d")
            self.assertFalse(os.path.isfile(os.path.join(drop, "90-casper.conf")))
            mint_drop = read("etc/lightdm/lightdm.conf.d/90-linuxmint.conf")
            self.assertNotIn("autologin-user", mint_drop)
            self.assertIn("greeter-session=slick-greeter", mint_drop)
            self.assertFalse(os.path.isdir(os.path.join(root, "home", "mint")))
        finally:
            shutil.rmtree(root, ignore_errors=True)
            shutil.rmtree(efi, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
