#!/usr/bin/env python3
"""Ubuntu 26.04 Budgie native installer."""

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

from firstboot.installlocale import InstallLocale  # noqa: E402
from firstboot.osinstall.common import InstalledDisk, OsIdentity, is_native_driver  # noqa: E402

from firstboot.osinstall.casper import (  # noqa: E402
    casper_leftovers,
    filter_snap_seed,
    install_kernel_from_iso,
    installed_kernel_ok,
    iso_kernel_package,
    kernel_pool_extras,
    parse_install_sources,
    rebuild_initramfs,
    strip_installer_snaps,
)
from firstboot.osinstall.ubuntu_2604_budgie import DRIVER, ID  # noqa: E402

UBUNTU_HASH = (
    "$6$exDY1mhS4KUYCE/2$"
    "zmn9ToZwTKLhCw.b4/b.ZRTIZM30JZ4QrOQ2aOXJ8yk96xpcCof0kxKwuX1kqLG/"
    "ygbJ1f8wxED22bTL4F46P0"
)


def fake_tree(root: str) -> None:
    boot = os.path.join(root, "boot")
    os.makedirs(boot)
    open(os.path.join(boot, "vmlinuz-7.0.0-14-generic"), "wb").close()
    open(os.path.join(boot, "initrd.img-7.0.0-14-generic"), "wb").close()
    for rel in (
        "etc",
        "etc/default",
        "etc/systemd/system",
        "etc/sddm.conf.d",
        "usr/lib/systemd/system",
        "home",
        "etc/skel",
        "var/lib/dbus",
        "var/lib/dpkg",
    ):
        os.makedirs(os.path.join(root, rel), exist_ok=True)
    with open(os.path.join(root, "etc", "passwd"), "w", encoding="utf-8") as fh:
        fh.write(
            "root:x:0:0:root:/root:/bin/bash\n"
            "ubuntu:x:1000:1000:live:/home/ubuntu:/bin/bash\n"
        )
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
        os.path.join(root, "usr", "lib", "systemd", "system", "sddm.service"),
        "w",
        encoding="utf-8",
    ) as fh:
        fh.write("[Unit]\n")
    os.makedirs(os.path.join(root, "home", "ubuntu"), exist_ok=True)
    with open(os.path.join(root, "etc", "sddm.conf"), "w", encoding="utf-8") as fh:
        fh.write("[Autologin]\nUser=ubuntu\nSession=budgie-desktop.desktop\n")
    with open(
        os.path.join(root, "etc", "sddm.conf.d", "live.conf"),
        "w",
        encoding="utf-8",
    ) as fh:
        fh.write("[Autologin]\nUser=ubuntu\nSession=budgie-desktop\n")
    with open(
        os.path.join(root, "etc", "sddm.conf.d", "50-ubuntu-budgie.conf"),
        "w",
        encoding="utf-8",
    ) as fh:
        fh.write(
            "[Theme]\n"
            "Current=ubuntu-budgie-login\n"
            "CursorTheme=Breeze_Light\n"
        )
    seed_dir = os.path.join(root, "var", "lib", "snapd", "seed", "snaps")
    snap_dir = os.path.join(root, "var", "lib", "snapd", "snaps")
    os.makedirs(seed_dir)
    os.makedirs(snap_dir)
    with open(
        os.path.join(root, "var", "lib", "snapd", "seed", "seed.yaml"),
        "w",
        encoding="utf-8",
    ) as fh:
        fh.write(
            "snaps:\n"
            "  -\n"
            "    name: firefox\n"
            "    file: firefox_1.snap\n"
            "  -\n"
            "    name: ubuntu-budgie-welcome\n"
            "    classic: true\n"
            "    file: ubuntu-budgie-welcome_579.snap\n"
            "  -\n"
            "    name: ubuntu-desktop-bootstrap\n"
            "    classic: true\n"
            "    file: ubuntu-desktop-bootstrap_589.snap\n"
        )
    open(os.path.join(snap_dir, "ubuntu-desktop-bootstrap_589.snap"), "wb").close()
    open(os.path.join(seed_dir, "ubuntu-desktop-bootstrap_589.snap"), "wb").close()
    open(os.path.join(seed_dir, "firefox_1.snap"), "wb").close()
    systemd = os.path.join(root, "etc", "systemd", "system")
    unit = "snap-ubuntu\\x2ddesktop\\x2dbootstrap-589.mount"
    with open(os.path.join(systemd, unit), "w", encoding="utf-8") as fh:
        fh.write("[Unit]\nDescription=Mount unit for ubuntu-desktop-bootstrap\n")
    wants = os.path.join(systemd, "multi-user.target.wants")
    os.makedirs(wants, exist_ok=True)
    os.symlink(
        os.path.join("..", unit),
        os.path.join(wants, unit),
    )
    with open(
        os.path.join(systemd, "snap.ubuntu-desktop-bootstrap.subiquity-server.service"),
        "w",
        encoding="utf-8",
    ) as fh:
        fh.write("[Unit]\n")


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


class Ubuntu2604BudgieTests(unittest.TestCase):
    def test_driver_contract(self) -> None:
        self.assertEqual(ID, "ubuntu-2604-budgie")
        self.assertEqual(DRIVER.id, ID)
        self.assertEqual(DRIVER.aliases, ())
        self.assertEqual(DRIVER.unpack_kind, "casper-layered")
        self.assertEqual(DRIVER.display_manager, "sddm")
        self.assertEqual(DRIVER.live_usernames, ("ubuntu",))
        self.assertEqual(DRIVER.default_hostname, "ubuntu")
        self.assertEqual(DRIVER.bootloader_id, "ubuntu")
        self.assertEqual(DRIVER.nvram_label, "Ubuntu")
        self.assertTrue(is_native_driver(DRIVER))
        self.assertFalse(hasattr(DRIVER, "seed_files") and callable(DRIVER.seed_files))

    def test_layered_relpaths_skip_live(self) -> None:
        iso = tempfile.mkdtemp(prefix="fbl-budgie-iso-")
        try:
            casper_dir = os.path.join(iso, "casper")
            os.makedirs(casper_dir)
            for name in (
                "minimal.squashfs",
                "minimal.en.squashfs",
                "minimal.standard.squashfs",
                "minimal.standard.en.squashfs",
                "minimal.standard.live.squashfs",
                "minimal.standard.no-languages.squashfs",
            ):
                open(os.path.join(casper_dir, name), "wb").close()
            self.assertEqual(
                DRIVER.squashfs_relpaths(iso),
                [
                    "casper/minimal.squashfs",
                    "casper/minimal.en.squashfs",
                    "casper/minimal.standard.squashfs",
                    "casper/minimal.standard.en.squashfs",
                ],
            )
            extras = DRIVER.iso_extras(iso)
            self.assertNotIn("casper/minimal.standard.live.squashfs", extras)
        finally:
            shutil.rmtree(iso, ignore_errors=True)

    def test_parse_install_sources_default_is_standard_not_live(self) -> None:
        iso = tempfile.mkdtemp(prefix="fbl-budgie-src-")
        try:
            casper_dir = os.path.join(iso, "casper")
            os.makedirs(casper_dir)
            with open(
                os.path.join(casper_dir, "install-sources.yaml"),
                "w",
                encoding="utf-8",
            ) as fh:
                fh.write(
                    "kernel:\n"
                    "  default: linux-generic-hwe-24.04\n"
                    "sources:\n"
                    "- default: false\n"
                    "  id: ubuntu-budgie-desktop-minimal\n"
                    "  path: minimal.squashfs\n"
                    "  type: fsimage-layered\n"
                    "- default: true\n"
                    "  id: ubuntu-budgie-desktop\n"
                    "  path: minimal.standard.squashfs\n"
                    "  type: fsimage-layered\n"
                    "version: 2\n"
                )
            parsed = parse_install_sources(iso)
            self.assertEqual(parsed["kernel"], "linux-generic-hwe-24.04")
            self.assertEqual(parsed["path"], "minimal.standard.squashfs")
            self.assertNotIn("live", parsed["path"])
        finally:
            shutil.rmtree(iso, ignore_errors=True)

    def test_iso_kernel_package_falls_back_to_pool_hwe(self) -> None:
        iso = tempfile.mkdtemp(prefix="fbl-budgie-pool-")
        try:
            casper_dir = os.path.join(iso, "casper")
            os.makedirs(casper_dir)
            with open(
                os.path.join(casper_dir, "install-sources.yaml"),
                "w",
                encoding="utf-8",
            ) as fh:
                fh.write("kernel:\n  default: linux-generic-hwe-24.04\n")
            deb_dir = os.path.join(iso, "pool", "main", "l", "linux-meta")
            os.makedirs(deb_dir)
            open(
                os.path.join(
                    deb_dir, "linux-generic-hwe-26.04_7.0.0-14.14_amd64.deb"
                ),
                "wb",
            ).close()
            open(
                os.path.join(
                    deb_dir, "linux-image-generic-hwe-26.04_7.0.0-14.14_amd64.deb"
                ),
                "wb",
            ).close()
            self.assertEqual(iso_kernel_package(iso), "linux-generic-hwe-26.04")
            extras = kernel_pool_extras(iso)
            self.assertTrue(
                any("linux-generic-hwe-26.04" in rel for rel in extras), extras
            )
            self.assertFalse(any("linux-firmware" in rel for rel in extras), extras)
        finally:
            shutil.rmtree(iso, ignore_errors=True)

    def test_install_kernel_skips_apt_when_vmlinuz_without_initrd(self) -> None:
        """Budgie squashfs has the kernel; initrd is built with dracut."""
        root = tempfile.mkdtemp(prefix="fbl-budgie-kimg-")
        try:
            boot = os.path.join(root, "boot")
            os.makedirs(boot)
            open(os.path.join(boot, "vmlinuz-7.0.0-14-generic"), "wb").close()
            self.assertFalse(installed_kernel_ok(root))
            install_kernel_from_iso(root, "")
            self.assertFalse(installed_kernel_ok(root))
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_rebuild_initramfs_uses_dracut(self) -> None:
        root = tempfile.mkdtemp(prefix="fbl-budgie-dracut-")
        try:
            boot = os.path.join(root, "boot")
            os.makedirs(boot)
            open(os.path.join(boot, "vmlinuz-7.0.0-14-generic"), "wb").close()
            os.makedirs(os.path.join(root, "usr", "bin"))
            open(os.path.join(root, "usr", "bin", "dracut"), "wb").close()

            def fake_chroot(_root: str, argv: list[str], **_kwargs: object) -> tuple[int, str]:
                self.assertEqual(argv[0], "/usr/bin/dracut")
                self.assertIn("--no-hostonly", argv)
                open(
                    os.path.join(root, "boot", "initrd.img-7.0.0-14-generic"),
                    "wb",
                ).close()
                return 0, ""

            with mock.patch(
                "firstboot.osinstall.casper.chroot_run", side_effect=fake_chroot
            ):
                rebuild_initramfs(root)
            self.assertTrue(installed_kernel_ok(root))
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_health_check_rejects_casperize_conf(self) -> None:
        root = tempfile.mkdtemp(prefix="fbl-budgie-casperize-hc-")
        efi = tempfile.mkdtemp(prefix="fbl-budgie-casperize-hc-efi-")
        try:
            fake_tree(root)
            conf = os.path.join(root, "etc", "initramfs-tools", "conf.d")
            os.makedirs(conf)
            with open(os.path.join(conf, "casperize.conf"), "w") as fh:
                fh.write("CASPER=1\n")
            ident = OsIdentity("shop-pc", "leon", "Leon", UBUNTU_HASH)
            fake_esp(efi)
            fails = DRIVER.health_check(root, efi, ident, disk_for(root, efi))
            self.assertTrue(any("casper" in f.lower() for f in fails), fails)
            leftovers = casper_leftovers(root)
            self.assertIn("Live casper initramfs config is still present.", leftovers)
        finally:
            shutil.rmtree(root, ignore_errors=True)
            shutil.rmtree(efi, ignore_errors=True)

    def test_health_check_rejects_bootstrap_snap(self) -> None:
        root = tempfile.mkdtemp(prefix="fbl-budgie-snap-hc-")
        efi = tempfile.mkdtemp(prefix="fbl-budgie-snap-hc-efi-")
        try:
            fake_tree(root)
            ident = OsIdentity("shop-pc", "leon", "Leon", UBUNTU_HASH)
            fake_esp(efi)
            leftovers = casper_leftovers(root)
            self.assertIn("Live installer snap is still present.", leftovers)
            self.assertIn("Live installer snap mount is still present.", leftovers)
            fails = DRIVER.health_check(root, efi, ident, disk_for(root, efi))
            self.assertTrue(any("installer snap" in f.lower() for f in fails), fails)
        finally:
            shutil.rmtree(root, ignore_errors=True)
            shutil.rmtree(efi, ignore_errors=True)

    def test_strip_installer_snaps_drops_mount_units(self) -> None:
        root = tempfile.mkdtemp(prefix="fbl-budgie-strip-")
        try:
            fake_tree(root)
            strip_installer_snaps(root)
            leftovers = casper_leftovers(root)
            self.assertNotIn("Live installer snap is still present.", leftovers)
            self.assertNotIn("Live installer snap mount is still present.", leftovers)
            systemd = os.path.join(root, "etc", "systemd", "system")
            unit = "snap-ubuntu\\x2ddesktop\\x2dbootstrap-589.mount"
            self.assertFalse(os.path.lexists(os.path.join(systemd, unit)))
            self.assertFalse(
                os.path.lexists(
                    os.path.join(systemd, "multi-user.target.wants", unit)
                )
            )
            self.assertFalse(
                os.path.isfile(
                    os.path.join(
                        systemd,
                        "snap.ubuntu-desktop-bootstrap.subiquity-server.service",
                    )
                )
            )
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_filter_snap_seed_drops_bootstrap(self) -> None:
        text = (
            "snaps:\n"
            "  -\n"
            "    name: ubuntu-budgie-welcome\n"
            "    file: ubuntu-budgie-welcome_579.snap\n"
            "  -\n"
            "    name: ubuntu-desktop-bootstrap\n"
            "    classic: true\n"
            "    file: ubuntu-desktop-bootstrap_589.snap\n"
        )
        new = filter_snap_seed(text, {"ubuntu-desktop-bootstrap", "subiquity"})
        self.assertIn("ubuntu-budgie-welcome", new)
        self.assertNotIn("ubuntu-desktop-bootstrap", new)

    def test_configure_writes_customer_not_live_user(self) -> None:
        root = tempfile.mkdtemp(prefix="fbl-budgie-root-")
        efi = tempfile.mkdtemp(prefix="fbl-budgie-efi-")
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
            default = os.readlink(
                os.path.join(root, "etc", "systemd", "system", "default.target")
            )
            self.assertEqual(os.path.basename(default), "graphical.target")
            dm = os.readlink(
                os.path.join(root, "etc", "systemd", "system", "display-manager.service")
            )
            self.assertEqual(os.path.basename(dm), "sddm.service")
            sddm = read("etc/sddm.conf")
            self.assertNotIn("User=", sddm)
            self.assertNotIn("Session=", sddm)
            self.assertFalse(
                os.path.isfile(os.path.join(root, "etc", "sddm.conf.d", "live.conf"))
            )
            theme = read("etc/sddm.conf.d/50-ubuntu-budgie.conf")
            self.assertIn("Current=ubuntu-budgie-login", theme)
            self.assertFalse(os.path.isdir(os.path.join(root, "home", "ubuntu")))
            seed = read("var/lib/snapd/seed/seed.yaml")
            self.assertNotIn("ubuntu-desktop-bootstrap", seed)
            self.assertIn("firefox", seed)
            self.assertIn("ubuntu-budgie-welcome", seed)
            self.assertFalse(
                os.path.isfile(
                    os.path.join(
                        root,
                        "var",
                        "lib",
                        "snapd",
                        "snaps",
                        "ubuntu-desktop-bootstrap_589.snap",
                    )
                )
            )
            leftovers = casper_leftovers(root)
            self.assertEqual(leftovers, [])
            fake_esp(efi)
            fails = DRIVER.health_check(root, efi, ident, disk_for(root, efi))
            self.assertEqual(fails, [])
        finally:
            shutil.rmtree(root, ignore_errors=True)
            shutil.rmtree(efi, ignore_errors=True)

    def test_health_check_rejects_missing_sddm(self) -> None:
        root = tempfile.mkdtemp(prefix="fbl-budgie-dm-")
        efi = tempfile.mkdtemp(prefix="fbl-budgie-dm-efi-")
        try:
            fake_tree(root)
            os.unlink(
                os.path.join(root, "usr", "lib", "systemd", "system", "sddm.service")
            )
            ident = OsIdentity("shop-pc", "leon", "Leon", UBUNTU_HASH)
            loc = InstallLocale()
            DRIVER.configure(root, ident, loc, disk_for(root, efi))
            fake_esp(efi)
            fails = DRIVER.health_check(root, efi, ident, disk_for(root, efi))
            self.assertTrue(any("sddm" in f for f in fails), fails)
        finally:
            shutil.rmtree(root, ignore_errors=True)
            shutil.rmtree(efi, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
