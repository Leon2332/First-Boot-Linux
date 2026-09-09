#!/usr/bin/env python3
"""Debian 13 MATE native installer."""

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
from firstboot.osinstall.debian import (  # noqa: E402
    debian_live_relpaths,
    iso_extras,
)
from firstboot.osinstall.debian_13_mate import DRIVER, ID  # noqa: E402

UBUNTU_HASH = (
    "$6$exDY1mhS4KUYCE/2$"
    "zmn9ToZwTKLhCw.b4/b.ZRTIZM30JZ4QrOQ2aOXJ8yk96xpcCof0kxKwuX1kqLG/"
    "ygbJ1f8wxED22bTL4F46P0"
)


def fake_tree(root: str) -> None:
    boot = os.path.join(root, "boot")
    os.makedirs(boot)
    open(os.path.join(boot, "vmlinuz-6.12.0-0.deb13"), "wb").close()
    open(os.path.join(boot, "initrd.img-6.12.0-0.deb13"), "wb").close()
    for rel in (
        "etc",
        "etc/default",
        "etc/systemd/system",
        "etc/lightdm/lightdm.conf.d",
        "etc/apt/sources.list.d",
        "etc/sudoers.d",
        "etc/xdg/autostart",
        "usr/lib/systemd/system",
        "usr/lib/shim",
        "usr/lib/grub/x86_64-efi-signed",
        "usr/share/lightdm/lightdm.conf.d",
        "home",
        "etc/skel",
        "var/lib/dbus",
        "var/lib/dpkg",
    ):
        os.makedirs(os.path.join(root, rel), exist_ok=True)
    with open(os.path.join(root, "etc", "passwd"), "w", encoding="utf-8") as fh:
        fh.write(
            "root:x:0:0:root:/root:/bin/bash\n"
            "user:x:1000:1000:Debian Live user:/home/user:/bin/bash\n"
        )
    with open(os.path.join(root, "etc", "shadow"), "w", encoding="utf-8") as fh:
        fh.write("root:!:0:0:99999:7:::\nuser:*:0:0:99999:7:::\n")
    with open(os.path.join(root, "etc", "group"), "w", encoding="utf-8") as fh:
        fh.write("root:x:0:\nsudo:x:27:\nusers:x:100:\nuser:x:1000:\n")
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
    os.makedirs(os.path.join(root, "home", "user"), exist_ok=True)
    with open(
        os.path.join(root, "etc", "lightdm", "lightdm.conf"),
        "w",
        encoding="utf-8",
    ) as fh:
        fh.write(
            "[Seat:*]\n"
            "autologin-user=user\n"
            "autologin-session=mate\n"
            "user-session=mate\n"
        )
    with open(
        os.path.join(root, "etc", "lightdm", "lightdm.conf.d", "live.conf"),
        "w",
        encoding="utf-8",
    ) as fh:
        fh.write("[Seat:*]\nautologin-user=user\n")
    with open(
        os.path.join(root, "etc", "lightdm", "lightdm.conf.d", "01_debian.conf"),
        "w",
        encoding="utf-8",
    ) as fh:
        fh.write(
            "[Seat:*]\n"
            "autologin-user=user\n"
            "greeter-session=lightdm-gtk-greeter\n"
        )
    with open(
        os.path.join(root, "etc", "xdg", "autostart", "calamares.desktop"),
        "w",
        encoding="utf-8",
    ) as fh:
        fh.write("[Desktop Entry]\nExec=calamares\n")
    with open(os.path.join(root, "etc", "sudoers.d", "live"), "w", encoding="utf-8") as fh:
        fh.write("user ALL=(ALL) NOPASSWD: ALL\n")
    with open(os.path.join(root, "etc", "apt", "sources.list"), "w", encoding="utf-8") as fh:
        fh.write("deb [trusted=yes] file:///run/live/medium trixie main\n")
    with open(
        os.path.join(root, "etc", "apt", "sources.list.d", "live-medium.list"),
        "w",
        encoding="utf-8",
    ) as fh:
        fh.write("deb [trusted=yes] file:///run/live/medium trixie main\n")
    wants = os.path.join(root, "etc", "systemd", "system", "multi-user.target.wants")
    os.makedirs(wants, exist_ok=True)
    os.symlink(
        "/usr/lib/systemd/system/live-config.service",
        os.path.join(wants, "live-config.service"),
    )
    open(os.path.join(root, "usr", "lib", "shim", "shimx64.efi.signed"), "wb").close()
    open(
        os.path.join(root, "usr", "lib", "grub", "x86_64-efi-signed", "grubx64.efi.signed"),
        "wb",
    ).close()
    open(os.path.join(root, "usr", "lib", "shim", "mmx64.efi.signed"), "wb").close()
    with open(os.path.join(root, "var", "lib", "dpkg", "status"), "w", encoding="utf-8") as fh:
        fh.write("Package: live-boot\nStatus: install ok installed\n\n")


def fake_esp(path: str) -> None:
    boot = os.path.join(path, "EFI", "BOOT")
    debian = os.path.join(path, "EFI", "debian")
    os.makedirs(boot)
    os.makedirs(debian)
    open(os.path.join(boot, "BOOTX64.EFI"), "wb").close()
    open(os.path.join(debian, "shimx64.efi"), "wb").close()
    open(os.path.join(debian, "grubx64.efi"), "wb").close()


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


class Debian13MateTests(unittest.TestCase):
    def test_driver_contract(self) -> None:
        self.assertEqual(ID, "debian-13-mate")
        self.assertEqual(DRIVER.id, ID)
        self.assertEqual(DRIVER.aliases, ())
        self.assertEqual(DRIVER.unpack_kind, "live-single")
        self.assertEqual(DRIVER.display_manager, "lightdm")
        self.assertEqual(DRIVER.live_usernames, ("user",))
        self.assertEqual(DRIVER.default_hostname, "debian")
        self.assertEqual(DRIVER.bootloader_id, "debian")
        self.assertEqual(DRIVER.nvram_label, "Debian")
        self.assertTrue(is_native_driver(DRIVER))
        self.assertFalse(hasattr(DRIVER, "seed_files") and callable(DRIVER.seed_files))

    def test_live_squashfs_relpaths(self) -> None:
        iso = tempfile.mkdtemp(prefix="fbl-deb13-mate-iso-")
        try:
            live = os.path.join(iso, "live")
            os.makedirs(live)
            open(os.path.join(live, "filesystem.squashfs"), "wb").close()
            self.assertEqual(
                DRIVER.squashfs_relpaths(iso), ["live/filesystem.squashfs"]
            )
            self.assertEqual(debian_live_relpaths(iso), ["live/filesystem.squashfs"])
        finally:
            shutil.rmtree(iso, ignore_errors=True)

    def test_configure_writes_customer_not_live_user(self) -> None:
        root = tempfile.mkdtemp(prefix="fbl-deb13-mate-root-")
        efi = tempfile.mkdtemp(prefix="fbl-deb13-mate-efi-")
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
            self.assertNotIn("user:", passwd)
            self.assertIn(UBUNTU_HASH, shadow)
            lastchg = None
            for line in shadow.splitlines():
                if line.startswith("leon:"):
                    lastchg = int(line.split(":")[2])
                    break
            self.assertIsNotNone(lastchg)
            self.assertGreater(lastchg, 0)
            group = read("etc/group")
            self.assertIn("sudo:x:27:leon", group)
            self.assertEqual(read("etc/hostname").strip(), "shop-pc")
            fstab = read("etc/fstab")
            self.assertIn("ROOT-UUID-2222", fstab)
            self.assertIn("ESP-UUID-1111", fstab)
            grub = read("etc/default/grub")
            self.assertNotIn("fbl.install", grub)
            self.assertNotIn("toram", grub)
            self.assertNotIn("boot=live", grub)
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
            self.assertIn("user-session=mate", lightdm)
            drop = os.path.join(root, "etc", "lightdm", "lightdm.conf.d")
            self.assertFalse(os.path.isfile(os.path.join(drop, "live.conf")))
            debian_drop = read("etc/lightdm/lightdm.conf.d/01_debian.conf")
            self.assertNotIn("autologin-user", debian_drop)
            self.assertIn("greeter-session=lightdm-gtk-greeter", debian_drop)
            self.assertFalse(
                os.path.isfile(
                    os.path.join(root, "etc", "xdg", "autostart", "calamares.desktop")
                )
            )
            wants = os.path.join(
                root, "etc", "systemd", "system", "multi-user.target.wants"
            )
            self.assertFalse(
                os.path.lexists(os.path.join(wants, "live-config.service"))
            )
            self.assertFalse(os.path.isdir(os.path.join(root, "home", "user")))
            self.assertFalse(os.path.isfile(os.path.join(root, "etc", "sudoers.d", "live")))
            sources = read("etc/apt/sources.list")
            self.assertNotIn("/run/live", sources)
            self.assertFalse(
                os.path.isfile(
                    os.path.join(root, "etc", "apt", "sources.list.d", "live-medium.list")
                )
            )
            debian_src = read("etc/apt/sources.list.d/debian.sources")
            self.assertIn("deb.debian.org/debian", debian_src)
            self.assertIn("trixie-security", debian_src)
            fake_esp(efi)
            fails = DRIVER.health_check(root, efi, ident, disk_for(root, efi))
            self.assertEqual(fails, [])
        finally:
            shutil.rmtree(root, ignore_errors=True)
            shutil.rmtree(efi, ignore_errors=True)

    def test_health_check_rejects_missing_lightdm(self) -> None:
        root = tempfile.mkdtemp(prefix="fbl-deb13-mate-dm-")
        efi = tempfile.mkdtemp(prefix="fbl-deb13-mate-dm-efi-")
        try:
            fake_tree(root)
            os.unlink(
                os.path.join(root, "usr", "lib", "systemd", "system", "lightdm.service")
            )
            ident = OsIdentity("shop-pc", "leon", "Leon", UBUNTU_HASH)
            loc = InstallLocale()
            DRIVER.configure(root, ident, loc, disk_for(root, efi))
            fake_esp(efi)
            fails = DRIVER.health_check(root, efi, ident, disk_for(root, efi))
            self.assertTrue(any("lightdm" in f for f in fails), fails)
        finally:
            shutil.rmtree(root, ignore_errors=True)
            shutil.rmtree(efi, ignore_errors=True)

    def test_iso_extras_signed_debs_not_live_grub(self) -> None:
        iso = tempfile.mkdtemp(prefix="fbl-deb13-mate-pool-")
        try:
            pool = os.path.join(
                iso, "pool", "main", "g", "grub-efi-amd64-signed"
            )
            os.makedirs(pool)
            open(
                os.path.join(pool, "grub-efi-amd64-signed_1_amd64.deb"), "wb"
            ).close()
            shim = os.path.join(iso, "pool", "main", "s", "shim-signed")
            os.makedirs(shim)
            open(os.path.join(shim, "shim-signed_1_amd64.deb"), "wb").close()
            open(
                os.path.join(shim, "shim-signed-common_1_all.deb"), "wb"
            ).close()
            efi = os.path.join(iso, "EFI", "boot")
            os.makedirs(efi)
            open(os.path.join(efi, "bootx64.efi"), "wb").close()
            open(os.path.join(efi, "grubx64.efi"), "wb").close()
            extras = DRIVER.iso_extras(iso)
            self.assertIn(
                "pool/main/g/grub-efi-amd64-signed/grub-efi-amd64-signed_1_amd64.deb",
                extras,
            )
            self.assertIn(
                "pool/main/s/shim-signed/shim-signed_1_amd64.deb", extras
            )
            self.assertNotIn(
                "pool/main/s/shim-signed/shim-signed-common_1_all.deb", extras
            )
            self.assertEqual(extras, iso_extras(iso))
        finally:
            shutil.rmtree(iso, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
