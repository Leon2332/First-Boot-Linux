#!/usr/bin/env python3
"""Ubuntu 26.04 Cinnamon native installer."""

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
    disable_overlayroot,
    ensure_user_icon,
    filter_snap_seed,
    install_kernel_from_iso,
    installed_kernel_ok,
    iso_kernel_package,
    kernel_pool_extras,
    parse_install_sources,
    rebuild_initramfs,
    strip_casper_initramfs,
)
from firstboot.osinstall.ubuntu_2604_cinnamon import DRIVER, ID  # noqa: E402

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
        os.path.join(root, "usr", "lib", "systemd", "system", "lightdm.service"),
        "w",
        encoding="utf-8",
    ) as fh:
        fh.write("[Unit]\n")
    os.makedirs(os.path.join(root, "home", "ubuntu"), exist_ok=True)
    with open(
        os.path.join(root, "etc", "lightdm", "lightdm.conf"),
        "w",
        encoding="utf-8",
    ) as fh:
        fh.write(
            "[Seat:*]\n"
            "autologin-user=ubuntu\n"
            "autologin-session=cinnamon\n"
            "user-session=cinnamon\n"
        )
    with open(
        os.path.join(root, "etc", "lightdm", "lightdm.conf.d", "90-casper.conf"),
        "w",
        encoding="utf-8",
    ) as fh:
        fh.write("[Seat:*]\nautologin-user=ubuntu\n")
    with open(
        os.path.join(root, "etc", "lightdm", "lightdm.conf.d", "50-slick.conf"),
        "w",
        encoding="utf-8",
    ) as fh:
        fh.write(
            "[Seat:*]\n"
            "autologin-user=ubuntu\n"
            "greeter-session=slick-greeter\n"
        )
    acc_users = os.path.join(root, "var", "lib", "AccountsService", "users")
    acc_icons = os.path.join(root, "var", "lib", "AccountsService", "icons")
    os.makedirs(acc_users)
    os.makedirs(acc_icons)
    with open(os.path.join(acc_users, "ubuntu"), "w", encoding="utf-8") as fh:
        fh.write("[User]\nSystemAccount=false\n")
    with open(os.path.join(acc_icons, "ubuntu"), "wb") as fh:
        fh.write(b"old-face")
    faces = os.path.join(root, "usr", "share", "cinnamon", "faces")
    os.makedirs(faces)
    with open(os.path.join(faces, "user-generic.png"), "wb") as fh:
        fh.write(b"cinnamon-face")
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
            "    name: ubuntu-desktop-bootstrap\n"
            "    classic: true\n"
            "    file: ubuntu-desktop-bootstrap_589.snap\n"
        )
    open(os.path.join(snap_dir, "ubuntu-desktop-bootstrap_589.snap"), "wb").close()
    open(os.path.join(seed_dir, "ubuntu-desktop-bootstrap_589.snap"), "wb").close()
    open(os.path.join(seed_dir, "firefox_1.snap"), "wb").close()


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


class Ubuntu2604CinnamonTests(unittest.TestCase):
    def test_driver_contract(self) -> None:
        self.assertEqual(ID, "ubuntu-2604-cinnamon")
        self.assertEqual(DRIVER.id, ID)
        self.assertEqual(DRIVER.aliases, ())
        self.assertEqual(DRIVER.unpack_kind, "casper-layered")
        self.assertEqual(DRIVER.display_manager, "lightdm")
        self.assertEqual(DRIVER.live_usernames, ("ubuntu",))
        self.assertEqual(DRIVER.default_hostname, "ubuntu")
        self.assertEqual(DRIVER.bootloader_id, "ubuntu")
        self.assertEqual(DRIVER.nvram_label, "Ubuntu")
        self.assertTrue(is_native_driver(DRIVER))
        self.assertFalse(hasattr(DRIVER, "seed_files") and callable(DRIVER.seed_files))

    def test_layered_relpaths_skip_live(self) -> None:
        iso = tempfile.mkdtemp(prefix="fbl-cinnamon-iso-")
        try:
            casper_dir = os.path.join(iso, "casper")
            os.makedirs(casper_dir)
            for name in (
                "minimal.squashfs",
                "minimal.standard.squashfs",
                "minimal.standard.live.squashfs",
            ):
                open(os.path.join(casper_dir, name), "wb").close()
            self.assertEqual(
                DRIVER.squashfs_relpaths(iso),
                [
                    "casper/minimal.squashfs",
                    "casper/minimal.standard.squashfs",
                ],
            )
            extras = DRIVER.iso_extras(iso)
            self.assertNotIn("casper/minimal.standard.live.squashfs", extras)
        finally:
            shutil.rmtree(iso, ignore_errors=True)

    def test_parse_install_sources_default_is_standard_not_live(self) -> None:
        iso = tempfile.mkdtemp(prefix="fbl-cinnamon-src-")
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
                    "  default: linux-generic\n"
                    "sources:\n"
                    "- default: false\n"
                    "  path: minimal.squashfs\n"
                    "  type: fsimage-layered\n"
                    "- default: true\n"
                    "  path: minimal.standard.squashfs\n"
                    "  type: fsimage-layered\n"
                    "version: 2\n"
                )
            parsed = parse_install_sources(iso)
            self.assertEqual(parsed["kernel"], "linux-generic")
            self.assertEqual(parsed["path"], "minimal.standard.squashfs")
            self.assertNotIn("live", parsed["path"])
        finally:
            shutil.rmtree(iso, ignore_errors=True)

    def test_iso_kernel_package_falls_back_to_pool_hwe(self) -> None:
        iso = tempfile.mkdtemp(prefix="fbl-cinnamon-pool-")
        try:
            casper_dir = os.path.join(iso, "casper")
            os.makedirs(casper_dir)
            with open(
                os.path.join(casper_dir, "install-sources.yaml"),
                "w",
                encoding="utf-8",
            ) as fh:
                fh.write("kernel:\n  default: linux-generic\n")
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

    def test_kernel_pool_extras_copies_dists_skips_firmware(self) -> None:
        iso = tempfile.mkdtemp(prefix="fbl-cinnamon-extra-")
        try:
            dists = os.path.join(
                iso, "dists", "resolute", "main", "binary-amd64"
            )
            os.makedirs(dists)
            open(os.path.join(dists, "Packages"), "wb").close()
            meta = os.path.join(iso, "pool", "main", "l", "linux-meta")
            fw = os.path.join(iso, "pool", "main", "l", "linux-firmware")
            os.makedirs(meta)
            os.makedirs(fw)
            open(
                os.path.join(meta, "linux-image-generic-hwe-26.04_1_amd64.deb"),
                "wb",
            ).close()
            open(os.path.join(fw, "linux-firmware_1_all.deb"), "wb").close()
            extras = DRIVER.iso_extras(iso)
            self.assertIn("dists", extras)
            self.assertTrue(
                any("linux-image-generic-hwe-26.04" in rel for rel in extras),
                extras,
            )
            self.assertFalse(any("linux-firmware" in rel for rel in extras), extras)
        finally:
            shutil.rmtree(iso, ignore_errors=True)

    def test_install_kernel_from_iso_skips_when_present(self) -> None:
        root = tempfile.mkdtemp(prefix="fbl-cinnamon-kskip-")
        try:
            boot = os.path.join(root, "boot")
            os.makedirs(boot)
            open(os.path.join(boot, "vmlinuz-7.0.0-14-generic"), "wb").close()
            open(os.path.join(boot, "initrd.img-7.0.0-14-generic"), "wb").close()
            install_kernel_from_iso(root, "")
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_install_kernel_skips_apt_when_vmlinuz_without_initrd(self) -> None:
        """Cinnamon squashfs has the kernel; initrd is built with dracut."""
        root = tempfile.mkdtemp(prefix="fbl-cinnamon-kimg-")
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
        root = tempfile.mkdtemp(prefix="fbl-cinnamon-dracut-")
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
        root = tempfile.mkdtemp(prefix="fbl-cinnamon-casperize-hc-")
        efi = tempfile.mkdtemp(prefix="fbl-cinnamon-casperize-hc-efi-")
        try:
            fake_tree(root)
            conf = os.path.join(root, "etc", "initramfs-tools", "conf.d")
            os.makedirs(conf)
            with open(os.path.join(conf, "casperize.conf"), "w") as fh:
                fh.write("CASPER=1\n")
            ident = OsIdentity("shop-pc", "leon", "Leon", UBUNTU_HASH)
            fake_esp(efi)
            fails = DRIVER.health_check(root, efi, ident, disk_for(root, efi))
            self.assertTrue(
                any("casper" in f.lower() for f in fails), fails
            )
            leftovers = casper_leftovers(root)
            self.assertIn("Live casper initramfs config is still present.", leftovers)
        finally:
            shutil.rmtree(root, ignore_errors=True)
            shutil.rmtree(efi, ignore_errors=True)

    def test_disable_overlayroot(self) -> None:
        root = tempfile.mkdtemp(prefix="fbl-cinnamon-ovl-")
        try:
            os.makedirs(os.path.join(root, "etc"))
            path = os.path.join(root, "etc", "overlayroot.local.conf")
            with open(path, "w") as fh:
                fh.write("overlayroot=tmpfs\n")
            disable_overlayroot(root)
            self.assertFalse(os.path.isfile(path))
            self.assertTrue(os.path.isfile(path + ".old"))
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_health_check_rejects_dangling_initrd(self) -> None:
        root = tempfile.mkdtemp(prefix="fbl-cinnamon-initrd-")
        efi = tempfile.mkdtemp(prefix="fbl-cinnamon-initrd-efi-")
        try:
            fake_tree(root)
            ident = OsIdentity("shop-pc", "leon", "Leon", UBUNTU_HASH)
            loc = InstallLocale()
            DRIVER.configure(root, ident, loc, disk_for(root, efi))
            boot = os.path.join(root, "boot")
            os.unlink(os.path.join(boot, "initrd.img-6.17.0"))
            os.symlink("initrd.img-6.17.0", os.path.join(boot, "initrd.img"))
            self.assertFalse(installed_kernel_ok(root))
            fake_esp(efi)
            fails = DRIVER.health_check(root, efi, ident, disk_for(root, efi))
            self.assertTrue(any("initrd" in f.lower() or "kernel" in f.lower() for f in fails), fails)
        finally:
            shutil.rmtree(root, ignore_errors=True)
            shutil.rmtree(efi, ignore_errors=True)

    def test_installed_kernel_ok_needs_versioned_pair(self) -> None:
        root = tempfile.mkdtemp(prefix="fbl-cinnamon-boot-")
        try:
            boot = os.path.join(root, "boot")
            os.makedirs(boot)
            open(os.path.join(boot, "vmlinuz"), "wb").close()
            open(os.path.join(boot, "initrd.img"), "wb").close()
            self.assertFalse(installed_kernel_ok(root))
            open(os.path.join(boot, "vmlinuz-7.0.0-14-generic"), "wb").close()
            os.unlink(os.path.join(boot, "initrd.img"))
            os.symlink(
                "initrd.img-7.0.0-14-generic", os.path.join(boot, "initrd.img")
            )
            self.assertFalse(installed_kernel_ok(root))
            open(os.path.join(boot, "initrd.img-7.0.0-14-generic"), "wb").close()
            self.assertTrue(installed_kernel_ok(root))
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_strip_casper_initramfs_drops_live_hooks(self) -> None:
        root = tempfile.mkdtemp(prefix="fbl-cinnamon-casperize-")
        try:
            conf = os.path.join(root, "etc", "initramfs-tools", "conf.d")
            scripts = os.path.join(
                root, "usr", "share", "initramfs-tools", "scripts"
            )
            os.makedirs(conf)
            os.makedirs(os.path.join(scripts, "casper-bottom"))
            with open(os.path.join(conf, "casperize.conf"), "w") as fh:
                fh.write("CASPER=1\n")
            with open(os.path.join(conf, "default-layer.conf"), "w") as fh:
                fh.write("LAYER=live\n")
            with open(os.path.join(conf, "resume"), "w") as fh:
                fh.write("RESUME=none\n")
            open(os.path.join(scripts, "casper"), "wb").close()
            strip_casper_initramfs(root)
            self.assertFalse(os.path.exists(os.path.join(conf, "casperize.conf")))
            self.assertFalse(
                os.path.exists(os.path.join(conf, "default-layer.conf"))
            )
            self.assertTrue(os.path.isfile(os.path.join(conf, "resume")))
            self.assertFalse(os.path.exists(os.path.join(scripts, "casper")))
            self.assertFalse(
                os.path.isdir(os.path.join(scripts, "casper-bottom"))
            )
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_filter_snap_seed_drops_bootstrap(self) -> None:
        text = (
            "snaps:\n"
            "  -\n"
            "    name: core24\n"
            "    file: core24_1.snap\n"
            "  -\n"
            "    name: ubuntu-desktop-bootstrap\n"
            "    classic: true\n"
            "    file: ubuntu-desktop-bootstrap_589.snap\n"
            "  -\n"
            "    name: subiquity\n"
            "    file: subiquity_1.snap\n"
        )
        new = filter_snap_seed(text, {"ubuntu-desktop-bootstrap", "subiquity"})
        self.assertIn("core24", new)
        self.assertNotIn("ubuntu-desktop-bootstrap", new)
        self.assertNotIn("subiquity", new)

    def test_ensure_user_icon_skips_debian_logo(self) -> None:
        root = tempfile.mkdtemp(prefix="fbl-cinnamon-face-")
        try:
            os.makedirs(os.path.join(root, "home", "leon"))
            os.makedirs(os.path.join(root, "usr", "share", "pixmaps"))
            with open(
                os.path.join(root, "usr", "share", "pixmaps", "debian-logo.png"),
                "wb",
            ) as fh:
                fh.write(b"debian")
            faces = os.path.join(root, "usr", "share", "cinnamon", "faces")
            os.makedirs(faces)
            with open(os.path.join(faces, "user-generic.png"), "wb") as fh:
                fh.write(b"cinnamon-face")
            ensure_user_icon(root, "leon")
            with open(os.path.join(root, "home", "leon", ".face"), "rb") as fh:
                self.assertEqual(fh.read(), b"cinnamon-face")
            acc = os.path.join(
                root, "var", "lib", "AccountsService", "users", "leon"
            )
            with open(acc, encoding="utf-8") as fh:
                text = fh.read()
            self.assertIn("Icon=/usr/share/cinnamon/faces/user-generic.png", text)
            self.assertNotIn("debian-logo", text)
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_configure_writes_customer_not_live_user(self) -> None:
        root = tempfile.mkdtemp(prefix="fbl-cinnamon-root-")
        efi = tempfile.mkdtemp(prefix="fbl-cinnamon-efi-")
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
            self.assertEqual(os.path.basename(dm), "lightdm.service")
            lightdm = read("etc/lightdm/lightdm.conf")
            self.assertNotIn("autologin-user", lightdm)
            self.assertNotIn("autologin-session", lightdm)
            self.assertIn("user-session=cinnamon", lightdm)
            drop = os.path.join(root, "etc", "lightdm", "lightdm.conf.d")
            self.assertFalse(os.path.isfile(os.path.join(drop, "90-casper.conf")))
            slick = read("etc/lightdm/lightdm.conf.d/50-slick.conf")
            self.assertNotIn("autologin-user", slick)
            self.assertIn("greeter-session=slick-greeter", slick)
            self.assertFalse(os.path.isdir(os.path.join(root, "home", "ubuntu")))
            self.assertFalse(
                os.path.isfile(
                    os.path.join(root, "var", "lib", "AccountsService", "users", "ubuntu")
                )
            )
            self.assertTrue(
                os.path.isfile(os.path.join(root, "home", "leon", ".face"))
            )
            acc = read("var/lib/AccountsService/users/leon")
            self.assertIn("Icon=/usr/share/cinnamon/faces/user-generic.png", acc)
            seed = read("var/lib/snapd/seed/seed.yaml")
            self.assertNotIn("ubuntu-desktop-bootstrap", seed)
            self.assertIn("firefox", seed)
            self.assertFalse(
                os.path.isfile(
                    os.path.join(
                        root, "var", "lib", "snapd", "snaps", "ubuntu-desktop-bootstrap_589.snap"
                    )
                )
            )
            fake_esp(efi)
            fails = DRIVER.health_check(root, efi, ident, disk_for(root, efi))
            self.assertEqual(fails, [])
        finally:
            shutil.rmtree(root, ignore_errors=True)
            shutil.rmtree(efi, ignore_errors=True)

    def test_health_check_rejects_missing_lightdm(self) -> None:
        root = tempfile.mkdtemp(prefix="fbl-cinnamon-dm-")
        efi = tempfile.mkdtemp(prefix="fbl-cinnamon-dm-efi-")
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


if __name__ == "__main__":
    unittest.main()
