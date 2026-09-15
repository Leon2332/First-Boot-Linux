#!/usr/bin/env python3
"""Ubuntu 26.04 Plasma native installer (Kubuntu ISO as an Ubuntu edition)."""

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
    KUBUNTU_EXTRA_LIVE_PACKAGES,
    LIVE_PACKAGES,
    casper_leftovers,
    casper_squashfs_relpaths,
    packages_to_purge,
)
from firstboot.osinstall.common import (  # noqa: E402
    InstalledDisk,
    OsIdentity,
    add_user,
    is_native_driver,
)
from firstboot.osinstall.ubuntu_2604_plasma import DRIVER, ID  # noqa: E402

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
            "kubuntu:x:1000:1000:live:/home/kubuntu:/bin/bash\n"
        )
    with open(os.path.join(root, "etc", "shadow"), "w", encoding="utf-8") as fh:
        fh.write("root:!:0:0:99999:7:::\nkubuntu:*:0:0:99999:7:::\n")
    with open(os.path.join(root, "etc", "group"), "w", encoding="utf-8") as fh:
        fh.write("root:x:0:\nsudo:x:27:\nusers:x:100:\nkubuntu:x:1000:\n")
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
    os.makedirs(os.path.join(root, "home", "kubuntu"), exist_ok=True)
    # Casper 15autologin on the live ISO writes this, not the squashfs.
    with open(os.path.join(root, "etc", "sddm.conf"), "w", encoding="utf-8") as fh:
        fh.write(
            "[Autologin]\nUser=kubuntu\nSession=kubuntu-live-environment.desktop\n"
        )
    with open(
        os.path.join(root, "etc", "sddm.conf.d", "live.conf"),
        "w",
        encoding="utf-8",
    ) as fh:
        fh.write("[Autologin]\nUser=kubuntu\nSession=kubuntu-live-environment\n")
    with open(
        os.path.join(root, "etc", "sddm.conf.d", "20-kubuntu.conf"),
        "w",
        encoding="utf-8",
    ) as fh:
        fh.write(
            "[Autologin]\nRelogin=false\nSession=plasma\nUser=\n\n"
            "[Theme]\nCurrent=kubuntu\n"
        )
    with open(
        os.path.join(root, "etc", "sddm.conf.d", "kde_settings.conf"),
        "w",
        encoding="utf-8",
    ) as fh:
        fh.write("[Theme]\nCurrent=breeze\n")
    wayland = os.path.join(root, "usr", "share", "wayland-sessions")
    os.makedirs(wayland, exist_ok=True)
    with open(
        os.path.join(wayland, "kubuntu-live-environment.desktop"),
        "w",
        encoding="utf-8",
    ) as fh:
        fh.write("[Desktop Entry]\nExec=/usr/libexec/start-kubuntu-live-env\n")
    with open(
        os.path.join(wayland, "plasma.desktop"), "w", encoding="utf-8"
    ) as fh:
        fh.write("[Desktop Entry]\nExec=startplasma-wayland\n")
    for rel, body in (
        ("usr/bin/kubuntu-installer-prompt", "#!/bin/sh\n"),
        ("usr/libexec/start-kubuntu-live-env", "#!/bin/sh\n"),
        ("usr/bin/calamares", "#!/bin/sh\n"),
    ):
        path = os.path.join(root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(body)
        os.chmod(path, 0o755)
    os.makedirs(os.path.join(root, "etc", "calamares"), exist_ok=True)
    with open(
        os.path.join(root, "etc", "calamares", "settings.conf"),
        "w",
        encoding="utf-8",
    ) as fh:
        fh.write("branding: kubuntu\n")
    wants = os.path.join(
        root, "etc", "systemd", "system", "final.target.wants"
    )
    os.makedirs(wants, exist_ok=True)
    os.symlink(
        "/usr/lib/systemd/system/casper.service",
        os.path.join(wants, "casper.service"),
    )
    with open(
        os.path.join(root, "var", "lib", "dpkg", "status"),
        "w",
        encoding="utf-8",
    ) as fh:
        fh.write(
            "Package: kubuntu-installer-prompt\n"
            "Status: install ok installed\n"
            "\n"
            "Package: calamares-settings-kubuntu\n"
            "Status: install ok installed\n"
            "\n"
            "Package: calamares\n"
            "Status: install ok installed\n"
            "\n"
            "Package: casper\n"
            "Status: install ok installed\n"
            "\n"
            "Package: cifs-utils\n"
            "Status: install ok installed\n"
        )


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


class Ubuntu2604PlasmaTests(unittest.TestCase):
    def test_driver_contract(self) -> None:
        self.assertEqual(ID, "ubuntu-2604-plasma")
        self.assertEqual(DRIVER.id, ID)
        self.assertEqual(DRIVER.aliases, ())
        self.assertEqual(DRIVER.unpack_kind, "casper-single")
        self.assertEqual(DRIVER.display_manager, "sddm")
        self.assertEqual(DRIVER.live_usernames, ("kubuntu",))
        self.assertEqual(DRIVER.default_hostname, "ubuntu")
        self.assertEqual(DRIVER.bootloader_id, "ubuntu")
        self.assertEqual(DRIVER.nvram_label, "Ubuntu")
        self.assertEqual(DRIVER.extra_live_packages, KUBUNTU_EXTRA_LIVE_PACKAGES)
        self.assertEqual(DRIVER.sddm_session, "plasma")
        self.assertIn("kubuntu-installer-prompt", LIVE_PACKAGES)
        self.assertIn("calamares-settings-kubuntu", LIVE_PACKAGES)
        self.assertIn("cifs-utils", KUBUNTU_EXTRA_LIVE_PACKAGES)
        self.assertTrue(is_native_driver(DRIVER))
        self.assertFalse(hasattr(DRIVER, "seed_files") and callable(DRIVER.seed_files))

    def test_single_filesystem_squashfs(self) -> None:
        iso = tempfile.mkdtemp(prefix="fbl-plasma-iso-")
        try:
            casper_dir = os.path.join(iso, "casper")
            os.makedirs(casper_dir)
            open(os.path.join(casper_dir, "filesystem.squashfs"), "wb").close()
            self.assertEqual(
                DRIVER.squashfs_relpaths(iso), ["casper/filesystem.squashfs"]
            )
            self.assertEqual(
                casper_squashfs_relpaths(iso), ["casper/filesystem.squashfs"]
            )
        finally:
            shutil.rmtree(iso, ignore_errors=True)

    def test_configure_writes_customer_not_live_user(self) -> None:
        root = tempfile.mkdtemp(prefix="fbl-plasma-root-")
        efi = tempfile.mkdtemp(prefix="fbl-plasma-efi-")
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
            self.assertNotIn("kubuntu:", passwd)
            self.assertIn(UBUNTU_HASH, shadow)
            self.assertNotIn("\nkubuntu:", shadow)
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
                os.path.join(
                    root, "etc", "systemd", "system", "display-manager.service"
                )
            )
            self.assertEqual(os.path.basename(dm), "sddm.service")
            sddm = read("etc/sddm.conf")
            self.assertNotIn("User=", sddm)
            self.assertNotIn("kubuntu-live-environment", sddm)
            self.assertIn("Session=plasma", sddm)
            self.assertFalse(
                os.path.isfile(os.path.join(root, "etc", "sddm.conf.d", "live.conf"))
            )
            kubuntu = read("etc/sddm.conf.d/20-kubuntu.conf")
            self.assertIn("Session=plasma", kubuntu)
            self.assertNotIn("User=", kubuntu)
            self.assertIn("Current=kubuntu", kubuntu)
            theme = read("etc/sddm.conf.d/kde_settings.conf")
            self.assertIn("Current=breeze", theme)
            self.assertFalse(os.path.isdir(os.path.join(root, "home", "kubuntu")))
            self.assertFalse(
                os.path.isfile(
                    os.path.join(root, "usr", "bin", "kubuntu-installer-prompt")
                )
            )
            self.assertFalse(
                os.path.isfile(
                    os.path.join(
                        root,
                        "usr",
                        "share",
                        "wayland-sessions",
                        "kubuntu-live-environment.desktop",
                    )
                )
            )
            self.assertTrue(
                os.path.isfile(
                    os.path.join(
                        root, "usr", "share", "wayland-sessions", "plasma.desktop"
                    )
                )
            )
            self.assertFalse(
                os.path.isfile(os.path.join(root, "usr", "bin", "calamares"))
            )
            self.assertFalse(os.path.isdir(os.path.join(root, "etc", "calamares")))
            self.assertFalse(
                os.path.lexists(
                    os.path.join(
                        root,
                        "etc",
                        "systemd",
                        "system",
                        "final.target.wants",
                        "casper.service",
                    )
                )
            )
            fake_esp(efi)
            fails = DRIVER.health_check(root, efi, ident, disk_for(root, efi))
            self.assertEqual(fails, [])
        finally:
            shutil.rmtree(root, ignore_errors=True)
            shutil.rmtree(efi, ignore_errors=True)

    def test_add_user_copies_skel_desktop_symlinks(self) -> None:
        """Kubuntu skel Desktop links are absolute; do not follow on FBL."""
        root = tempfile.mkdtemp(prefix="fbl-plasma-skel-")
        try:
            fake_tree(root)
            skel_desk = os.path.join(root, "etc", "skel", "Desktop")
            os.makedirs(skel_desk)
            for name in (
                "org.kubuntu.web.home.desktop",
                "org.kfocus.web.howtos.desktop",
            ):
                os.symlink(
                    f"/usr/share/applications/{name}",
                    os.path.join(skel_desk, name),
                )
            ident = OsIdentity("shop-pc", "test", "Test", UBUNTU_HASH)
            add_user(root, ident)
            home_desk = os.path.join(root, "home", "test", "Desktop")
            for name in (
                "org.kubuntu.web.home.desktop",
                "org.kfocus.web.howtos.desktop",
            ):
                path = os.path.join(home_desk, name)
                self.assertTrue(os.path.islink(path), path)
                self.assertEqual(
                    os.readlink(path), f"/usr/share/applications/{name}"
                )
            with open(
                os.path.join(root, "etc", "passwd"), encoding="utf-8"
            ) as fh:
                self.assertIn("test:", fh.read())
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_packages_to_purge_includes_installer_prompt_and_cifs(self) -> None:
        root = tempfile.mkdtemp(prefix="fbl-plasma-purge-")
        try:
            fake_tree(root)
            pkgs = packages_to_purge(root, extra=KUBUNTU_EXTRA_LIVE_PACKAGES)
            self.assertIn("kubuntu-installer-prompt", pkgs)
            self.assertIn("calamares-settings-kubuntu", pkgs)
            self.assertIn("calamares", pkgs)
            self.assertIn("casper", pkgs)
            self.assertIn("cifs-utils", pkgs)
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_health_check_rejects_installer_prompt(self) -> None:
        root = tempfile.mkdtemp(prefix="fbl-plasma-prompt-")
        efi = tempfile.mkdtemp(prefix="fbl-plasma-prompt-efi-")
        try:
            fake_tree(root)
            ident = OsIdentity("shop-pc", "leon", "Leon", UBUNTU_HASH)
            loc = InstallLocale()
            DRIVER.configure(root, ident, loc, disk_for(root, efi))
            prompt = os.path.join(root, "usr", "bin", "kubuntu-installer-prompt")
            os.makedirs(os.path.dirname(prompt), exist_ok=True)
            with open(prompt, "w", encoding="utf-8") as fh:
                fh.write("#!/bin/sh\n")
            fake_esp(efi)
            fails = DRIVER.health_check(root, efi, ident, disk_for(root, efi))
            leftovers = casper_leftovers(root)
            self.assertTrue(
                any("installer" in f.lower() for f in fails), fails
            )
            self.assertIn("Live installer is still present.", leftovers)
        finally:
            shutil.rmtree(root, ignore_errors=True)
            shutil.rmtree(efi, ignore_errors=True)

    def test_health_check_rejects_live_session(self) -> None:
        root = tempfile.mkdtemp(prefix="fbl-plasma-live-sess-")
        efi = tempfile.mkdtemp(prefix="fbl-plasma-live-sess-efi-")
        try:
            fake_tree(root)
            ident = OsIdentity("shop-pc", "leon", "Leon", UBUNTU_HASH)
            loc = InstallLocale()
            DRIVER.configure(root, ident, loc, disk_for(root, efi))
            wayland = os.path.join(root, "usr", "share", "wayland-sessions")
            os.makedirs(wayland, exist_ok=True)
            with open(
                os.path.join(wayland, "kubuntu-live-environment.desktop"),
                "w",
                encoding="utf-8",
            ) as fh:
                fh.write("[Desktop Entry]\n")
            fake_esp(efi)
            fails = DRIVER.health_check(root, efi, ident, disk_for(root, efi))
            self.assertTrue(any("session" in f.lower() for f in fails), fails)
        finally:
            shutil.rmtree(root, ignore_errors=True)
            shutil.rmtree(efi, ignore_errors=True)

    def test_health_check_rejects_missing_sddm(self) -> None:
        root = tempfile.mkdtemp(prefix="fbl-plasma-dm-")
        efi = tempfile.mkdtemp(prefix="fbl-plasma-dm-efi-")
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
