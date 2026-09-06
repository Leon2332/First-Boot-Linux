#!/usr/bin/env python3
"""Fedora 44 Workstation (GNOME) native installer."""

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
from firstboot.osinstall.common import (  # noqa: E402
    InstalledDisk,
    OsIdentity,
    is_native_driver,
)
from firstboot.osinstall.fedora import fedora_live_relpaths  # noqa: E402
from firstboot.osinstall.fedora_44_gnome import DRIVER, ID  # noqa: E402

UBUNTU_HASH = (
    "$6$exDY1mhS4KUYCE/2$"
    "zmn9ToZwTKLhCw.b4/b.ZRTIZM30JZ4QrOQ2aOXJ8yk96xpcCof0kxKwuX1kqLG/"
    "ygbJ1f8wxED22bTL4F46P0"
)


def fake_tree(root: str) -> None:
    boot = os.path.join(root, "boot")
    os.makedirs(boot)
    open(os.path.join(boot, "vmlinuz-6.17.0-0.fc44.x86_64"), "wb").close()
    open(os.path.join(boot, "initramfs-6.17.0-0.fc44.x86_64.img"), "wb").close()
    for rel in (
        "etc",
        "etc/default",
        "etc/systemd/system",
        "etc/gdm",
        "etc/gdm/custom.conf.d",
        "etc/kernel",
        "etc/sysconfig",
        "etc/xdg/autostart",
        "usr/lib/systemd/system",
        "usr/lib/modules/6.17.0-0.fc44.x86_64",
        "home",
        "etc/skel",
        "var/lib/dbus",
    ):
        os.makedirs(os.path.join(root, rel), exist_ok=True)
    with open(os.path.join(root, "etc", "passwd"), "w", encoding="utf-8") as fh:
        fh.write(
            "root:x:0:0:root:/root:/bin/bash\n"
            "liveuser:x:1000:1000:Live:/home/liveuser:/bin/bash\n"
        )
    with open(os.path.join(root, "etc", "shadow"), "w", encoding="utf-8") as fh:
        fh.write("root:!:0:0:99999:7:::\nliveuser:*:0:0:99999:7:::\n")
    with open(os.path.join(root, "etc", "group"), "w", encoding="utf-8") as fh:
        fh.write("root:x:0:\nwheel:x:10:\nusers:x:100:\nliveuser:x:1000:\n")
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
    os.makedirs(os.path.join(root, "home", "liveuser"), exist_ok=True)
    with open(os.path.join(root, "etc", "gdm", "custom.conf"), "w", encoding="utf-8") as fh:
        fh.write(
            "[daemon]\n"
            "AutomaticLoginEnable=True\n"
            "AutomaticLogin=liveuser\n"
            "WaylandEnable=true\n"
        )
    with open(
        os.path.join(root, "etc", "gdm", "custom.conf.d", "livesys.conf"),
        "w",
        encoding="utf-8",
    ) as fh:
        fh.write("[daemon]\nAutomaticLoginEnable=True\nAutomaticLogin=liveuser\n")
    with open(
        os.path.join(root, "etc", "xdg", "autostart", "liveinst.desktop"),
        "w",
        encoding="utf-8",
    ) as fh:
        fh.write("[Desktop Entry]\nExec=liveinst\n")
    with open(
        os.path.join(
            root, "etc", "xdg", "autostart", "gnome-initial-setup-first-login.desktop"
        ),
        "w",
        encoding="utf-8",
    ) as fh:
        fh.write("[Desktop Entry]\nExec=gnome-initial-setup\n")
    wants = os.path.join(root, "etc", "systemd", "system", "multi-user.target.wants")
    os.makedirs(wants, exist_ok=True)
    os.symlink("/usr/lib/systemd/system/livesys.service", os.path.join(wants, "livesys.service"))


def fake_esp(path: str) -> None:
    boot = os.path.join(path, "EFI", "BOOT")
    fedora = os.path.join(path, "EFI", "fedora")
    os.makedirs(boot)
    os.makedirs(fedora)
    open(os.path.join(boot, "BOOTX64.EFI"), "wb").close()
    open(os.path.join(fedora, "shimx64.efi"), "wb").close()
    open(os.path.join(fedora, "grubx64.efi"), "wb").close()


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


class Fedora44GnomeTests(unittest.TestCase):
    def test_driver_contract(self) -> None:
        self.assertEqual(ID, "fedora-44-gnome")
        self.assertEqual(DRIVER.id, ID)
        self.assertEqual(DRIVER.aliases, ())
        self.assertEqual(DRIVER.unpack_kind, "fedora-erofs")
        self.assertEqual(DRIVER.display_manager, "gdm")
        self.assertEqual(DRIVER.live_usernames, ("liveuser",))
        self.assertEqual(DRIVER.default_hostname, "fedora")
        self.assertEqual(DRIVER.bootloader_id, "fedora")
        self.assertEqual(DRIVER.nvram_label, "Fedora")
        self.assertTrue(is_native_driver(DRIVER))
        self.assertFalse(hasattr(DRIVER, "seed_files") and callable(DRIVER.seed_files))

    def test_liveos_squashfs_relpaths(self) -> None:
        iso = tempfile.mkdtemp(prefix="fbl-f44-gnome-iso-")
        try:
            live = os.path.join(iso, "LiveOS")
            os.makedirs(live)
            open(os.path.join(live, "squashfs.img"), "wb").close()
            self.assertEqual(
                DRIVER.squashfs_relpaths(iso), ["LiveOS/squashfs.img"]
            )
            self.assertEqual(fedora_live_relpaths(iso), ["LiveOS/squashfs.img"])
        finally:
            shutil.rmtree(iso, ignore_errors=True)

    def test_configure_writes_customer_not_liveuser(self) -> None:
        root = tempfile.mkdtemp(prefix="fbl-f44-gnome-root-")
        efi = tempfile.mkdtemp(prefix="fbl-f44-gnome-efi-")
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
            self.assertNotIn("liveuser:", passwd)
            self.assertIn(UBUNTU_HASH, shadow)
            lastchg = None
            for line in shadow.splitlines():
                if line.startswith("leon:"):
                    lastchg = int(line.split(":")[2])
                    break
            self.assertIsNotNone(lastchg)
            self.assertGreater(lastchg, 0)
            group = read("etc/group")
            self.assertIn("wheel:x:10:leon", group)
            self.assertEqual(read("etc/hostname").strip(), "shop-pc")
            fstab = read("etc/fstab")
            self.assertIn("ROOT-UUID-2222", fstab)
            self.assertIn("ESP-UUID-1111", fstab)
            grub = read("etc/default/grub")
            self.assertNotIn("fbl.install", grub)
            self.assertNotIn("toram", grub)
            self.assertNotIn("rd.live.", grub)
            self.assertIn("rhgb quiet", grub)
            cmdline = read("etc/kernel/cmdline")
            self.assertIn("root=UUID=ROOT-UUID-2222", cmdline)
            self.assertIn("enforcing=0", cmdline)
            self.assertNotIn("fbl.install", cmdline)
            self.assertNotIn("systemd.unit=", cmdline)
            default = os.readlink(
                os.path.join(root, "etc", "systemd", "system", "default.target")
            )
            self.assertEqual(os.path.basename(default), "graphical.target")
            dm = os.readlink(
                os.path.join(root, "etc", "systemd", "system", "display-manager.service")
            )
            self.assertEqual(os.path.basename(dm), "gdm.service")
            gdm = read("etc/gdm/custom.conf")
            self.assertNotIn("AutomaticLoginEnable", gdm)
            self.assertNotIn("AutomaticLogin=liveuser", gdm)
            self.assertIn("WaylandEnable=true", gdm)
            self.assertFalse(
                os.path.isfile(
                    os.path.join(root, "etc", "gdm", "custom.conf.d", "livesys.conf")
                )
            )
            self.assertFalse(
                os.path.isfile(
                    os.path.join(root, "etc", "xdg", "autostart", "liveinst.desktop")
                )
            )
            self.assertFalse(
                os.path.isfile(
                    os.path.join(
                        root,
                        "etc",
                        "xdg",
                        "autostart",
                        "gnome-initial-setup-first-login.desktop",
                    )
                )
            )
            gis = os.path.join(
                root, "home", "leon", ".config", "gnome-initial-setup-done"
            )
            self.assertTrue(os.path.isfile(gis))
            with open(gis, encoding="ascii") as fh:
                self.assertIn("yes", fh.read())
            wants = os.path.join(
                root, "etc", "systemd", "system", "multi-user.target.wants"
            )
            self.assertFalse(os.path.lexists(os.path.join(wants, "livesys.service")))
            self.assertFalse(os.path.isdir(os.path.join(root, "home", "liveuser")))
            self.assertTrue(os.path.isfile(os.path.join(root, ".autorelabel")))
            with open(os.path.join(root, ".autorelabel"), encoding="ascii") as fh:
                self.assertIn("-F", fh.read())
            fake_esp(efi)
            fails = DRIVER.health_check(root, efi, ident, disk_for(root, efi))
            self.assertEqual(fails, [])
        finally:
            shutil.rmtree(root, ignore_errors=True)
            shutil.rmtree(efi, ignore_errors=True)

    def test_health_check_rejects_plasmalogin_only(self) -> None:
        root = tempfile.mkdtemp(prefix="fbl-f44-gnome-plm-")
        efi = tempfile.mkdtemp(prefix="fbl-f44-gnome-plm-efi-")
        try:
            fake_tree(root)
            os.unlink(os.path.join(root, "usr", "lib", "systemd", "system", "gdm.service"))
            with open(
                os.path.join(root, "usr", "lib", "systemd", "system", "plasmalogin.service"),
                "w",
                encoding="utf-8",
            ) as fh:
                fh.write("[Unit]\n")
            ident = OsIdentity("shop-pc", "leon", "Leon", UBUNTU_HASH)
            loc = InstallLocale()
            DRIVER.configure(root, ident, loc, disk_for(root, efi))
            fake_esp(efi)
            fails = DRIVER.health_check(root, efi, ident, disk_for(root, efi))
            self.assertTrue(any("gdm" in f for f in fails), fails)
        finally:
            shutil.rmtree(root, ignore_errors=True)
            shutil.rmtree(efi, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
