#!/usr/bin/env python3
"""CachyOS desktop 260809 KDE Plasma native installer."""

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
from firstboot.osinstall.cachyos import (  # noqa: E402
    BTRFS_ROOT_OPTS,
    CACHYOS_ESP_MIB,
    NVIDIA_LIVE_PACKAGES,
    cachyos_live_relpaths,
    find_systemd_boot_efi,
    install_staged_packages,
    iso_extras,
    locale_gen_enabled,
    pci_has_nvidia,
    remove_live_nvidia_packages,
    staged_package_files,
    write_cachyos_fstab,
    write_loader_entries,
    write_mkinitcpio_conf,
)
from firstboot.osinstall.cachyos_260809_plasma import DRIVER, ID  # noqa: E402
from firstboot.osinstall.common import (  # noqa: E402
    InstalledDisk,
    OsIdentity,
    OsInstallError,
    is_native_driver,
)

UBUNTU_HASH = (
    "$6$exDY1mhS4KUYCE/2$"
    "zmn9ToZwTKLhCw.b4/b.ZRTIZM30JZ4QrOQ2aOXJ8yk96xpcCof0kxKwuX1kqLG/"
    "ygbJ1f8wxED22bTL4F46P0"
)


def fake_tree(root: str) -> None:
    boot = os.path.join(root, "boot")
    os.makedirs(boot)
    open(os.path.join(boot, "vmlinuz-linux-cachyos"), "wb").close()
    open(os.path.join(boot, "initramfs-linux-cachyos.img"), "wb").close()
    for rel in (
        "etc",
        "etc/default",
        "etc/systemd/system",
        "etc/sddm.conf.d",
        "etc/plasmalogin.conf.d",
        "etc/sudoers.d",
        "etc/polkit-1/rules.d",
        "etc/xdg/autostart",
        "etc/mkinitcpio.conf.d",
        "usr/lib/systemd/system",
        "usr/lib/systemd/boot/efi",
        "usr/share/applications",
        "etc/mkinitcpio.d",
        "home",
        "etc/skel",
        "etc/skel/.config/autostart",
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
        fh.write(
            "root:x:0:\n"
            "sys:x:3:liveuser\n"
            "network:x:90:liveuser\n"
            "power:x:98:liveuser\n"
            "wheel:x:998:liveuser\n"
            "rfkill:x:983:liveuser\n"
            "video:x:986:liveuser\n"
            "storage:x:988:liveuser\n"
            "lp:x:991:liveuser\n"
            "audio:x:995:liveuser\n"
            "users:x:985:liveuser\n"
            "liveuser:x:1000:\n"
        )
    with open(
        os.path.join(root, "usr", "lib", "systemd", "system", "graphical.target"),
        "w",
        encoding="utf-8",
    ) as fh:
        fh.write("[Unit]\n")
    with open(
        os.path.join(root, "usr", "lib", "systemd", "system", "plasmalogin.service"),
        "w",
        encoding="utf-8",
    ) as fh:
        fh.write("[Unit]\n")
    with open(
        os.path.join(root, "usr", "lib", "systemd", "system", "NetworkManager.service"),
        "w",
        encoding="utf-8",
    ) as fh:
        fh.write("[Unit]\n")
    os.makedirs(os.path.join(root, "home", "liveuser"), exist_ok=True)
    with open(os.path.join(root, "etc", "plasmalogin.conf"), "w", encoding="utf-8") as fh:
        fh.write("[Autologin]\nUser=liveuser\nSession=plasma\nRelogin=false\n")
    with open(
        os.path.join(root, "etc", "plasmalogin.conf.d", "live.conf"),
        "w",
        encoding="utf-8",
    ) as fh:
        fh.write("[Autologin]\nUser=liveuser\n")
    with open(
        os.path.join(root, "etc", "xdg", "autostart", "calamares.desktop"),
        "w",
        encoding="utf-8",
    ) as fh:
        fh.write("[Desktop Entry]\nExec=calamares\n")
    with open(
        os.path.join(root, "etc", "sudoers.d", "live"), "w", encoding="utf-8"
    ) as fh:
        fh.write("liveuser ALL=(ALL) NOPASSWD: ALL\n")
    with open(
        os.path.join(root, "etc", "sudoers.d", "g_wheel"), "w", encoding="utf-8"
    ) as fh:
        fh.write("%wheel ALL=(ALL) NOPASSWD: ALL\n")
    with open(
        os.path.join(root, "etc", "polkit-1", "rules.d", "49-nopasswd_global.rules"),
        "w",
        encoding="utf-8",
    ) as fh:
        fh.write("polkit.addRule(function(action, subject) { return polkit.Result.YES; });\n")
    with open(
        os.path.join(root, "etc", "systemd", "system", "etc-pacman.d-gnupg.mount"),
        "w",
        encoding="utf-8",
    ) as fh:
        fh.write("[Unit]\n")
    with open(os.path.join(root, "etc", "locale.gen"), "w", encoding="utf-8") as fh:
        fh.write("#en_US.UTF-8 UTF-8\n#af_ZA.UTF-8 UTF-8\n")
    with open(
        os.path.join(root, "etc", "skel", ".config", "autostart", "cachyos-hello.desktop"),
        "w",
        encoding="utf-8",
    ) as fh:
        fh.write("[Desktop Entry]\nExec=/usr/bin/cachyos-hello\n")
    with open(os.path.join(root, "etc", "mkinitcpio.conf"), "w", encoding="utf-8") as fh:
        fh.write("HOOKS=(base udev archiso archiso_loop_mnt filesystems)\n")
    with open(
        os.path.join(root, "etc", "mkinitcpio.conf.d", "archiso.conf"),
        "w",
        encoding="utf-8",
    ) as fh:
        fh.write("HOOKS+=(archiso)\n")
    with open(
        os.path.join(root, "etc", "mkinitcpio.d", "linux.preset"),
        "w",
        encoding="utf-8",
    ) as fh:
        fh.write(
            "PRESETS=('archiso')\n"
            "archiso_config='/etc/mkinitcpio.conf.d/archiso.conf'\n"
        )
    with open(
        os.path.join(root, "etc", "mkinitcpio.d", "linux-cachyos.preset"),
        "w",
        encoding="utf-8",
    ) as fh:
        fh.write('ALL_kver="/boot/vmlinuz-linux-cachyos"\nPRESETS=(\'default\')\n')
    with open(
        os.path.join(root, "usr", "lib", "systemd", "boot", "efi", "systemd-bootx64.efi"),
        "wb",
    ) as fh:
        fh.write(b"sdboot")
    wants = os.path.join(root, "etc", "systemd", "system", "multi-user.target.wants")
    os.makedirs(wants, exist_ok=True)
    os.symlink(
        "/usr/lib/systemd/system/pacman-init.service",
        os.path.join(wants, "pacman-init.service"),
    )


def fake_esp(path: str) -> None:
    boot = os.path.join(path, "EFI", "BOOT")
    vendor = os.path.join(path, "EFI", "cachyos")
    systemd = os.path.join(path, "EFI", "systemd")
    os.makedirs(boot)
    os.makedirs(vendor)
    os.makedirs(systemd)
    open(os.path.join(boot, "BOOTX64.EFI"), "wb").close()
    open(os.path.join(vendor, "systemd-bootx64.efi"), "wb").close()
    open(os.path.join(systemd, "systemd-bootx64.efi"), "wb").close()
    os.makedirs(os.path.join(path, "loader", "entries"))
    with open(
        os.path.join(path, "loader", "entries", "cachyos.conf"), "w", encoding="utf-8"
    ) as fh:
        fh.write("title CachyOS\nlinux /vmlinuz-linux-cachyos\n")


def fake_extras() -> str:
    pkgs = tempfile.mkdtemp(prefix="fbl-cachyos-extras-")
    open(os.path.join(pkgs, "shelly-3.1.3-1-x86_64.pkg.tar.zst"), "wb").close()
    return pkgs


def disk_for(root: str, efi: str) -> InstalledDisk:
    return InstalledDisk(
        disk="/dev/vda",
        esp_dev="/dev/vda1",
        root_dev="/dev/vda2",
        esp_uuid="ESP-UUID-1111",
        root_uuid="ROOT-UUID-2222",
        esp_mp=efi,
        root_mp=root,
        boot_mp=efi,
        root_fstype="btrfs",
        root_fsopts=BTRFS_ROOT_OPTS,
    )


class CachyOS260809PlasmaTests(unittest.TestCase):
    def test_driver_contract(self) -> None:
        self.assertEqual(ID, "cachyos-260809-plasma")
        self.assertEqual(DRIVER.id, ID)
        self.assertEqual(DRIVER.aliases, ())
        self.assertEqual(DRIVER.unpack_kind, "archiso-airootfs")
        self.assertEqual(DRIVER.display_manager, "plasmalogin")
        self.assertEqual(DRIVER.live_usernames, ("liveuser", "cachyos"))
        self.assertEqual(DRIVER.default_hostname, "cachyos")
        self.assertEqual(DRIVER.bootloader_id, "cachyos")
        self.assertEqual(DRIVER.nvram_label, "CachyOS")
        self.assertEqual(CACHYOS_ESP_MIB, 4096)
        self.assertTrue(is_native_driver(DRIVER))
        self.assertFalse(hasattr(DRIVER, "seed_files") and callable(DRIVER.seed_files))

    def test_airootfs_relpaths(self) -> None:
        iso = tempfile.mkdtemp(prefix="fbl-cachyos-iso-")
        try:
            arch = os.path.join(iso, "arch", "x86_64")
            os.makedirs(arch)
            open(os.path.join(arch, "airootfs.sfs"), "wb").close()
            boot = os.path.join(iso, "arch", "boot", "x86_64")
            os.makedirs(boot)
            open(os.path.join(boot, "vmlinuz-linux-cachyos"), "wb").close()
            open(os.path.join(iso, "arch", "boot", "intel-ucode.img"), "wb").close()
            self.assertEqual(
                DRIVER.squashfs_relpaths(iso), ["arch/x86_64/airootfs.sfs"]
            )
            self.assertEqual(
                cachyos_live_relpaths(iso), ["arch/x86_64/airootfs.sfs"]
            )
            extras = iso_extras(iso)
            self.assertIn("arch/boot/x86_64/vmlinuz-linux-cachyos", extras)
            self.assertIn("arch/boot/intel-ucode.img", extras)
        finally:
            shutil.rmtree(iso, ignore_errors=True)

    def test_configure_writes_customer_not_liveuser(self) -> None:
        root = tempfile.mkdtemp(prefix="fbl-cachyos-root-")
        efi = tempfile.mkdtemp(prefix="fbl-cachyos-esp-")
        pkgs = fake_extras()
        try:
            fake_tree(root)
            fake_esp(efi)
            ident = OsIdentity("shop-pc", "leon", "Leon", UBUNTU_HASH)
            locale = InstallLocale(glibc="en_US.UTF-8", keyboard="us")
            DRIVER.configure(
                root, ident, locale, disk_for(root, efi), extras_dir=pkgs
            )
            passwd = open(os.path.join(root, "etc", "passwd"), encoding="utf-8").read()
            self.assertIn("leon:", passwd)
            self.assertNotIn("liveuser:", passwd)
            self.assertFalse(os.path.isdir(os.path.join(root, "home", "liveuser")))
            fstab = open(os.path.join(root, "etc", "fstab"), encoding="utf-8").read()
            self.assertIn("subvol=/@", fstab)
            self.assertIn("subvol=/@home", fstab)
            self.assertIn("/boot vfat", fstab)
            self.assertNotIn("/boot/efi", fstab)
            mk = open(os.path.join(root, "etc", "mkinitcpio.conf"), encoding="utf-8").read()
            self.assertNotIn("archiso", mk)
            self.assertIn("systemd", mk)
            self.assertFalse(
                os.path.isfile(os.path.join(root, "etc", "mkinitcpio.conf.d", "archiso.conf"))
            )
            self.assertFalse(
                os.path.isfile(os.path.join(root, "etc", "mkinitcpio.d", "linux.preset"))
            )
            self.assertTrue(
                os.path.isfile(os.path.join(root, "etc", "mkinitcpio.d", "linux-cachyos.preset"))
            )
            self.assertFalse(
                os.path.isfile(os.path.join(root, "etc", "xdg", "autostart", "calamares.desktop"))
            )
            self.assertFalse(os.path.isfile(os.path.join(root, "etc", "sudoers.d", "live")))
            self.assertFalse(os.path.isfile(os.path.join(root, "etc", "sudoers.d", "g_wheel")))
            sudoers = os.path.join(root, "etc", "sudoers.d", "10-installer")
            self.assertTrue(os.path.isfile(sudoers))
            self.assertEqual(
                open(sudoers, encoding="utf-8").read(), "%wheel ALL=(ALL) ALL\n"
            )
            self.assertEqual(os.stat(sudoers).st_mode & 0o777, 0o440)
            self.assertFalse(
                os.path.isfile(
                    os.path.join(
                        root, "etc", "polkit-1", "rules.d", "49-nopasswd_global.rules"
                    )
                )
            )
            self.assertFalse(
                os.path.isfile(
                    os.path.join(root, "etc", "systemd", "system", "etc-pacman.d-gnupg.mount")
                )
            )
            group = open(os.path.join(root, "etc", "group"), encoding="utf-8").read()
            self.assertIn("wheel:x:998:leon", group)
            self.assertIn("network:x:90:leon", group)
            self.assertIn("storage:x:988:leon", group)
            self.assertNotIn("liveuser", group)
            pl = open(os.path.join(root, "etc", "plasmalogin.conf"), encoding="utf-8").read()
            self.assertNotIn("liveuser", pl)
            default = os.readlink(
                os.path.join(root, "etc", "systemd", "system", "default.target")
            )
            self.assertTrue(default.endswith("graphical.target"))
            dm = os.readlink(
                os.path.join(root, "etc", "systemd", "system", "display-manager.service")
            )
            self.assertEqual(os.path.basename(dm), "plasmalogin.service")
            locale_conf = open(
                os.path.join(root, "etc", "locale.conf"), encoding="utf-8"
            ).read()
            self.assertIn("en_US.UTF-8", locale_conf)
            self.assertTrue(locale_gen_enabled(root, "en_US.UTF-8"))
            gen = open(os.path.join(root, "etc", "locale.gen"), encoding="utf-8").read()
            self.assertIn("en_US.UTF-8 UTF-8", gen)
            self.assertNotIn("#en_US.UTF-8", gen)
            self.assertTrue(
                os.path.isfile(
                    os.path.join(
                        root, "etc", "skel", ".config", "autostart", "cachyos-hello.desktop"
                    )
                )
            )
            self.assertTrue(
                os.path.isfile(
                    os.path.join(
                        root,
                        "home",
                        "leon",
                        ".config",
                        "autostart",
                        "cachyos-hello.desktop",
                    )
                )
            )
        finally:
            shutil.rmtree(root, ignore_errors=True)
            shutil.rmtree(efi, ignore_errors=True)
            shutil.rmtree(pkgs, ignore_errors=True)

    def test_bootloader_copies_systemd_boot_not_live_grub(self) -> None:
        root = tempfile.mkdtemp(prefix="fbl-cachyos-tree-")
        efi = tempfile.mkdtemp(prefix="fbl-cachyos-esp-")
        iso = tempfile.mkdtemp(prefix="fbl-cachyos-iso-")
        try:
            fake_tree(root)
            os.makedirs(os.path.join(iso, "EFI", "BOOT"))
            with open(os.path.join(iso, "EFI", "BOOT", "BOOTX64.EFI"), "wb") as fh:
                fh.write(b"live-grub")
            DRIVER.bootloader(root, efi, disk_for(root, efi), iso)
            bootx = os.path.join(efi, "EFI", "BOOT", "BOOTX64.EFI")
            vendor = os.path.join(efi, "EFI", "cachyos", "systemd-bootx64.efi")
            self.assertTrue(os.path.isfile(bootx))
            self.assertTrue(os.path.isfile(vendor))
            with open(bootx, "rb") as fh:
                self.assertEqual(fh.read(), b"sdboot")
            conf = open(
                os.path.join(efi, "loader", "entries", "cachyos.conf"), encoding="utf-8"
            ).read()
            self.assertIn("vmlinuz-linux-cachyos", conf)
            self.assertIn("subvol=/@", conf)
            self.assertNotIn("archisobasedir", conf)
            self.assertTrue(find_systemd_boot_efi(root).endswith("systemd-bootx64.efi"))
        finally:
            shutil.rmtree(root, ignore_errors=True)
            shutil.rmtree(efi, ignore_errors=True)
            shutil.rmtree(iso, ignore_errors=True)

    def test_health_check_pass_and_archiso_fail(self) -> None:
        root = tempfile.mkdtemp(prefix="fbl-cachyos-hc-")
        efi = tempfile.mkdtemp(prefix="fbl-cachyos-esp-")
        pkgs = fake_extras()
        try:
            fake_tree(root)
            fake_esp(efi)
            ident = OsIdentity("shop-pc", "leon", "Leon", UBUNTU_HASH)
            locale = InstallLocale(glibc="en_US.UTF-8", keyboard="us")
            disk = disk_for(root, efi)
            DRIVER.configure(root, ident, locale, disk, extras_dir=pkgs)
            DRIVER.bootloader(root, efi, disk, iso_mnt=efi)
            fails = DRIVER.health_check(root, efi, ident, disk)
            self.assertEqual(fails, [])
            os.unlink(os.path.join(root, "etc", "sudoers.d", "10-installer"))
            fails_sudo = DRIVER.health_check(root, efi, ident, disk)
            self.assertTrue(any("sudoers" in item for item in fails_sudo))
            with open(
                os.path.join(root, "etc", "sudoers.d", "10-installer"),
                "w",
                encoding="utf-8",
            ) as fh:
                fh.write("%wheel ALL=(ALL) ALL\n")
            with open(os.path.join(root, "etc", "mkinitcpio.conf"), "w", encoding="utf-8") as fh:
                fh.write("HOOKS=(base udev archiso filesystems)\n")
            fails_live = DRIVER.health_check(root, efi, ident, disk)
            self.assertTrue(any("archiso" in item for item in fails_live))
        finally:
            shutil.rmtree(root, ignore_errors=True)
            shutil.rmtree(efi, ignore_errors=True)
            shutil.rmtree(pkgs, ignore_errors=True)

    def test_fstab_and_loader_helpers(self) -> None:
        root = tempfile.mkdtemp(prefix="fbl-cachyos-fstab-")
        efi = tempfile.mkdtemp(prefix="fbl-cachyos-esp-")
        try:
            os.makedirs(os.path.join(root, "etc"))
            os.makedirs(os.path.join(root, "boot"))
            open(os.path.join(root, "boot", "vmlinuz-linux-cachyos"), "wb").close()
            open(os.path.join(root, "boot", "initramfs-linux-cachyos.img"), "wb").close()
            open(os.path.join(root, "boot", "intel-ucode.img"), "wb").close()
            disk = disk_for(root, efi)
            write_cachyos_fstab(root, disk)
            text = open(os.path.join(root, "etc", "fstab"), encoding="utf-8").read()
            self.assertIn("UUID=ROOT-UUID-2222 / btrfs", text)
            self.assertIn("subvol=/@log", text)
            self.assertIn("UUID=ESP-UUID-1111 /boot vfat", text)
            write_loader_entries(os.path.join(root, "boot"), disk)
            conf = open(
                os.path.join(root, "boot", "loader", "entries", "cachyos.conf"),
                encoding="utf-8",
            ).read()
            self.assertIn("intel-ucode.img", conf)
            self.assertIn("initramfs-linux-cachyos.img", conf)
            os.makedirs(os.path.join(root, "etc", "mkinitcpio.d"), exist_ok=True)
            with open(os.path.join(root, "etc", "mkinitcpio.conf"), "w", encoding="utf-8") as fh:
                fh.write("HOOKS=(base udev archiso)\n")
            with open(
                os.path.join(root, "etc", "mkinitcpio.d", "linux.preset"),
                "w",
                encoding="utf-8",
            ) as fh:
                fh.write("PRESETS=('archiso')\n")
            write_mkinitcpio_conf(root)
            mk = open(os.path.join(root, "etc", "mkinitcpio.conf"), encoding="utf-8").read()
            self.assertNotIn("archiso", mk)
            self.assertFalse(
                os.path.isfile(os.path.join(root, "etc", "mkinitcpio.d", "linux.preset"))
            )
        finally:
            shutil.rmtree(root, ignore_errors=True)
            shutil.rmtree(efi, ignore_errors=True)

    def test_staged_packages_order_and_skip_without_root(self) -> None:
        pkgs = tempfile.mkdtemp(prefix="fbl-cachyos-pkgs-")
        root = tempfile.mkdtemp(prefix="fbl-cachyos-pkgroot-")
        try:
            open(os.path.join(pkgs, "readme.txt"), "w", encoding="utf-8").close()
            for name in (
                "shelly-3.1.3-1-x86_64.pkg.tar.zst",
                "gtk4-1:4.22.5-1-x86_64.pkg.tar.zst",
            ):
                open(os.path.join(pkgs, name), "wb").close()
            files = staged_package_files(pkgs)
            names = [os.path.basename(p) for p in files]
            self.assertEqual(
                names,
                [
                    "gtk4-1:4.22.5-1-x86_64.pkg.tar.zst",
                    "shelly-3.1.3-1-x86_64.pkg.tar.zst",
                ],
            )
            os.makedirs(os.path.join(root, "usr", "bin"))
            open(os.path.join(root, "usr", "bin", "pacman"), "wb").close()
            install_staged_packages(root, pkgs)
            self.assertFalse(
                os.path.ismount(os.path.join(root, "var", "cache", "fbl-pkgs"))
            )
            self.assertEqual(staged_package_files(""), [])
            self.assertEqual(staged_package_files("/no/such/dir"), [])
            with self.assertRaises(OsInstallError):
                install_staged_packages(root, "")
        finally:
            shutil.rmtree(pkgs, ignore_errors=True)
            shutil.rmtree(root, ignore_errors=True)

    def test_pci_has_nvidia_and_skip_remove_without_root(self) -> None:
        sysfs = tempfile.mkdtemp(prefix="fbl-cachyos-sysfs-")
        root = tempfile.mkdtemp(prefix="fbl-cachyos-nv-")
        try:
            intel = os.path.join(sysfs, "bus", "pci", "devices", "0000:00:02.0")
            nvidia = os.path.join(sysfs, "bus", "pci", "devices", "0000:01:00.0")
            os.makedirs(intel)
            with open(os.path.join(intel, "vendor"), "w", encoding="ascii") as fh:
                fh.write("0x8086\n")
            self.assertFalse(pci_has_nvidia(sysfs))
            os.makedirs(nvidia)
            with open(os.path.join(nvidia, "vendor"), "w", encoding="ascii") as fh:
                fh.write("0x10de\n")
            self.assertTrue(pci_has_nvidia(sysfs))
            self.assertIn("linux-cachyos-nvidia-open", NVIDIA_LIVE_PACKAGES)
            self.assertIn("linux-cachyos-lts-nvidia-open", NVIDIA_LIVE_PACKAGES)
            self.assertIn("nvidia-utils", NVIDIA_LIVE_PACKAGES)
            os.makedirs(os.path.join(root, "usr", "bin"))
            open(os.path.join(root, "usr", "bin", "pacman"), "wb").close()
            remove_live_nvidia_packages(root, sysfs=os.path.join(sysfs, "missing"))
        finally:
            shutil.rmtree(sysfs, ignore_errors=True)
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
