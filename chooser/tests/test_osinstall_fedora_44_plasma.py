#!/usr/bin/env python3
"""Fedora 44 KDE Plasma native installer."""

from __future__ import annotations

import os
import shutil
import struct
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
CHOOSER_DIR = os.path.dirname(HERE)
if CHOOSER_DIR not in sys.path:
    sys.path.insert(0, CHOOSER_DIR)

from firstboot.installlocale import InstallLocale  # noqa: E402
from firstboot.osinstall.common import (  # noqa: E402
    InstalledDisk,
    OsIdentity,
    is_native_driver,
    write_fstab,
)
from firstboot.osinstall.fedora import (  # noqa: E402
    BTRFS_ROOT_OPTS,
    EROFS_MAGIC,
    FEDORA_BOOT_MIB,
    FEDORA_ESP_MIB,
    copy_fedora_esp_binaries,
    fedora_live_relpaths,
    image_fstype,
    initramfs_contains_live,
    partition_fedora_disk,
    strip_live_dracut_conf,
    write_esp_grub_stub,
)
from firstboot.osinstall.fedora_44_plasma import DRIVER, ID  # noqa: E402

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
        "etc/sddm.conf.d",
        "etc/plasmalogin.conf.d",
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
        os.path.join(root, "usr", "lib", "systemd", "system", "plasmalogin.service"),
        "w",
        encoding="utf-8",
    ) as fh:
        fh.write("[Unit]\n")
    os.makedirs(os.path.join(root, "home", "liveuser"), exist_ok=True)
    with open(os.path.join(root, "etc", "plasmalogin.conf"), "w", encoding="utf-8") as fh:
        fh.write("[Autologin]\nUser=liveuser\nSession=plasma\nRelogin=false\n")
    with open(os.path.join(root, "etc", "plasma-login.conf"), "w", encoding="utf-8") as fh:
        fh.write("[Autologin]\nUser=liveuser\nSession=plasma.desktop\n")
    with open(
        os.path.join(root, "etc", "plasmalogin.conf.d", "livesys.conf"),
        "w",
        encoding="utf-8",
    ) as fh:
        fh.write("[Autologin]\nUser=liveuser\n")
    with open(
        os.path.join(root, "etc", "xdg", "autostart", "liveinst.desktop"),
        "w",
        encoding="utf-8",
    ) as fh:
        fh.write("[Desktop Entry]\nExec=liveinst\n")
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


def fake_iso_efi(iso: str) -> None:
    boot = os.path.join(iso, "EFI", "BOOT")
    fedora = os.path.join(iso, "EFI", "fedora")
    os.makedirs(boot)
    os.makedirs(fedora)
    def put(path: str, data: bytes) -> None:
        with open(path, "wb") as fh:
            fh.write(data)

    put(os.path.join(boot, "BOOTX64.EFI"), b"shim")
    put(os.path.join(boot, "grubx64.efi"), b"live-grub")
    put(os.path.join(boot, "mmx64.efi"), b"mm")
    put(os.path.join(fedora, "shimx64.efi"), b"fedora-shim")
    put(os.path.join(fedora, "grubx64.efi"), b"fedora-grub")
    put(os.path.join(fedora, "gcdx64.efi"), b"gcd")
    put(os.path.join(fedora, "mmx64.efi"), b"fedora-mm")


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


class Fedora44PlasmaTests(unittest.TestCase):
    def test_driver_contract(self) -> None:
        self.assertEqual(ID, "fedora-44-plasma")
        self.assertEqual(DRIVER.id, ID)
        self.assertEqual(DRIVER.aliases, ())
        self.assertEqual(DRIVER.unpack_kind, "fedora-erofs")
        self.assertEqual(DRIVER.display_manager, "plasmalogin")
        self.assertEqual(DRIVER.live_usernames, ("liveuser",))
        self.assertEqual(DRIVER.default_hostname, "fedora")
        self.assertEqual(DRIVER.bootloader_id, "fedora")
        self.assertEqual(DRIVER.nvram_label, "Fedora")
        self.assertTrue(is_native_driver(DRIVER))
        self.assertFalse(hasattr(DRIVER, "seed_files") and callable(DRIVER.seed_files))

    def test_liveos_squashfs_relpaths(self) -> None:
        iso = tempfile.mkdtemp(prefix="fbl-f44-iso-")
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

    def test_erofs_magic(self) -> None:
        path = tempfile.NamedTemporaryFile(prefix="fbl-erofs-", delete=False)
        try:
            blob = bytearray(2048)
            struct.pack_into("<I", blob, 1024, EROFS_MAGIC)
            path.write(blob)
            path.close()
            self.assertEqual(image_fstype(path.name), "erofs")
            with open(path.name, "wb") as fh:
                fh.write(b"hsqs" + b"\x00" * 16)
            self.assertEqual(image_fstype(path.name), "squashfs")
        finally:
            os.unlink(path.name)

    def test_esp_uses_fedora_shim_not_gcdx64(self) -> None:
        iso = tempfile.mkdtemp(prefix="fbl-f44-efi-iso-")
        efi = tempfile.mkdtemp(prefix="fbl-f44-esp-")
        try:
            fake_iso_efi(iso)
            copy_fedora_esp_binaries(efi, iso, "fedora")
            write_esp_grub_stub(efi, "fedora", "ROOT-UUID-2222")
            boot = os.path.join(efi, "EFI", "BOOT")
            fedora_dir = os.path.join(efi, "EFI", "fedora")
            self.assertTrue(os.path.isfile(os.path.join(boot, "BOOTX64.EFI")))
            with open(os.path.join(boot, "BOOTX64.EFI"), "rb") as fh:
                self.assertEqual(fh.read(), b"fedora-shim")
            self.assertFalse(os.path.isfile(os.path.join(boot, "grubx64.efi")))
            self.assertFalse(os.path.isfile(os.path.join(boot, "mmx64.efi")))
            with open(os.path.join(fedora_dir, "grubx64.efi"), "rb") as fh:
                grub = fh.read()
            self.assertEqual(grub, b"fedora-grub")
            self.assertNotEqual(grub, b"gcd")
            with open(os.path.join(fedora_dir, "grub.cfg"), encoding="utf-8") as fh:
                stub = fh.read()
            self.assertIn("search.fs_uuid ROOT-UUID-2222 root", stub)
            self.assertIn("set prefix=($root)'/boot/grub2'", stub)
        finally:
            shutil.rmtree(iso, ignore_errors=True)
            shutil.rmtree(efi, ignore_errors=True)

    def test_configure_writes_customer_not_liveuser(self) -> None:
        root = tempfile.mkdtemp(prefix="fbl-f44-root-")
        efi = tempfile.mkdtemp(prefix="fbl-f44-efi-")
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
            self.assertEqual(os.path.basename(dm), "plasmalogin.service")
            plm = read("etc/plasmalogin.conf")
            self.assertNotIn("User=liveuser", plm)
            plasma_login = read("etc/plasma-login.conf")
            self.assertNotIn("User=liveuser", plasma_login)
            self.assertFalse(
                os.path.isfile(
                    os.path.join(root, "etc", "plasmalogin.conf.d", "livesys.conf")
                )
            )
            self.assertFalse(
                os.path.isfile(
                    os.path.join(root, "etc", "xdg", "autostart", "liveinst.desktop")
                )
            )
            wants = os.path.join(
                root, "etc", "systemd", "system", "multi-user.target.wants"
            )
            self.assertFalse(os.path.lexists(os.path.join(wants, "livesys.service")))
            self.assertFalse(os.path.isdir(os.path.join(root, "home", "liveuser")))
            self.assertTrue(os.path.isfile(os.path.join(root, ".autorelabel")))
            with open(os.path.join(root, ".autorelabel"), encoding="ascii") as fh:
                self.assertIn("-F", fh.read())
            bls_dir = os.path.join(root, "boot", "loader", "entries")
            names = [n for n in os.listdir(bls_dir) if n.endswith(".conf")]
            self.assertEqual(len(names), 1)
            bls = read(os.path.join("boot", "loader", "entries", names[0]))
            self.assertIn("root=UUID=ROOT-UUID-2222", bls)
            self.assertIn("linux /vmlinuz-", bls)
            self.assertIn("enforcing=0", bls)
            self.assertNotIn("rd.live.", bls)
            self.assertNotIn("fbl.install", bls)
            grub2 = read("boot/grub2/grub.cfg")
            self.assertIn("menuentry", grub2)
            self.assertIn("linux /vmlinuz-", grub2)
            self.assertNotIn("blscfg", grub2)
            self.assertNotIn("fbl.install", grub2)
            self.assertTrue(
                os.path.isfile(
                    os.path.join(
                        root,
                        "etc",
                        "systemd",
                        "system",
                        "clear-selinux-relabel-kargs.service",
                    )
                )
            )
            locale = read("etc/locale.conf")
            self.assertIn("LANG=en_US.UTF-8", locale)
            fake_esp(efi)
            fails = DRIVER.health_check(root, efi, ident, disk_for(root, efi))
            self.assertEqual(fails, [])
        finally:
            shutil.rmtree(root, ignore_errors=True)
            shutil.rmtree(efi, ignore_errors=True)

    def test_strip_live_dracut_conf(self) -> None:
        root = tempfile.mkdtemp(prefix="fbl-f44-dracut-")
        try:
            live = os.path.join(root, "etc", "dracut.conf.d")
            os.makedirs(live)
            os.makedirs(os.path.join(root, "usr", "lib", "dracut", "modules.d", "90dmsquash-live"))
            with open(os.path.join(live, "90-live.conf"), "w", encoding="utf-8") as fh:
                fh.write('add_dracutmodules+=" dmsquash-live "\n')
            with open(os.path.join(live, "00-generic.conf"), "w", encoding="utf-8") as fh:
                fh.write("compress=zstd\n")
            strip_live_dracut_conf(root)
            self.assertFalse(os.path.isfile(os.path.join(live, "90-live.conf")))
            self.assertTrue(os.path.isfile(os.path.join(live, "00-generic.conf")))
            self.assertTrue(
                os.path.isdir(
                    os.path.join(root, "usr", "lib", "dracut", "modules.d", "90dmsquash-live")
                )
            )
            fbl = os.path.join(live, "99-fbl.conf")
            with open(fbl, encoding="utf-8") as fh:
                text = fh.read()
            self.assertIn("omit_dracutmodules", text)
            self.assertIn("dmsquash-live", text)
            self.assertIn('hostonly="no"', text)
            self.assertNotIn("add_dracutmodules", text)
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_initramfs_contains_live(self) -> None:
        root = tempfile.mkdtemp(prefix="fbl-f44-initrd-")
        try:
            boot = os.path.join(root, "boot")
            os.makedirs(boot)
            open(os.path.join(boot, "vmlinuz-6.19.10-300.fc44.x86_64"), "wb").close()
            mods = os.path.join(root, "usr", "lib", "modules", "6.19.10-300.fc44.x86_64")
            os.makedirs(mods)
            live = os.path.join(boot, "initramfs-6.19.10-300.fc44.x86_64.img")
            with open(live, "wb") as fh:
                fh.write(b"header " + b"dmsquash-live" + b" tail" + b"\x00" * 80)
            self.assertTrue(initramfs_contains_live(root))
            with open(live, "wb") as fh:
                fh.write(b"just a host initramfs" + b"\x00" * 80)
            self.assertFalse(initramfs_contains_live(root))
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_health_check_rejects_sddm_only(self) -> None:
        root = tempfile.mkdtemp(prefix="fbl-f44-sddm-")
        efi = tempfile.mkdtemp(prefix="fbl-f44-sddm-efi-")
        try:
            fake_tree(root)
            os.unlink(
                os.path.join(root, "usr", "lib", "systemd", "system", "plasmalogin.service")
            )
            with open(
                os.path.join(root, "usr", "lib", "systemd", "system", "sddm.service"),
                "w",
                encoding="utf-8",
            ) as fh:
                fh.write("[Unit]\n")
            ident = OsIdentity("shop-pc", "leon", "Leon", UBUNTU_HASH)
            loc = InstallLocale()
            DRIVER.configure(root, ident, loc, disk_for(root, efi))
            fake_esp(efi)
            fails = DRIVER.health_check(root, efi, ident, disk_for(root, efi))
            self.assertTrue(any("plasmalogin" in f for f in fails), fails)
        finally:
            shutil.rmtree(root, ignore_errors=True)
            shutil.rmtree(efi, ignore_errors=True)

    def test_esp_stub_uses_boot_uuid_when_separate_boot(self) -> None:
        efi = tempfile.mkdtemp(prefix="fbl-f44-boot-esp-")
        try:
            write_esp_grub_stub(efi, "fedora", "ROOT-UUID-2222", boot_uuid="BOOT-UUID-3333")
            with open(
                os.path.join(efi, "EFI", "fedora", "grub.cfg"), encoding="utf-8"
            ) as fh:
                stub = fh.read()
            self.assertIn("search.fs_uuid BOOT-UUID-3333 root", stub)
            self.assertIn("set prefix=($root)/grub2", stub)
            self.assertNotIn("/boot/grub2", stub)
        finally:
            shutil.rmtree(efi, ignore_errors=True)

    def test_fstab_fedora_layout(self) -> None:
        root = tempfile.mkdtemp(prefix="fbl-f44-fstab-")
        try:
            os.makedirs(os.path.join(root, "etc"))
            disk = InstalledDisk(
                disk="/dev/sda",
                esp_dev="/dev/sda1",
                root_dev="/dev/sda3",
                esp_uuid="ESP-UUID-1111",
                root_uuid="ROOT-UUID-2222",
                esp_mp="/mnt/esp",
                root_mp=root,
                boot_dev="/dev/sda2",
                boot_uuid="BOOT-UUID-3333",
                boot_mp="/mnt/boot",
                root_fstype="btrfs",
                root_fsopts=BTRFS_ROOT_OPTS,
            )
            write_fstab(root, disk)
            with open(os.path.join(root, "etc", "fstab"), encoding="utf-8") as fh:
                text = fh.read()
            self.assertIn("UUID=ROOT-UUID-2222 / btrfs subvol=root,compress=zstd:1", text)
            self.assertIn("UUID=BOOT-UUID-3333 /boot ext4", text)
            self.assertIn("UUID=ESP-UUID-1111 /boot/efi vfat", text)
            self.assertIn("UUID=ROOT-UUID-2222 /home btrfs subvol=home,compress=zstd:1", text)
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_partition_fedora_disk_layout(self) -> None:
        runs: list[list[str]] = []

        def fake_checked(argv, **_kwargs):
            runs.append(list(argv))

        uuids = iter(["esp-uuid", "boot-uuid", "root-uuid"])
        with mock.patch(
            "firstboot.osinstall.fedora.casper_loops_on_disk", return_value=[]
        ), mock.patch(
            "firstboot.osinstall.fedora.run_checked", side_effect=fake_checked
        ), mock.patch("subprocess.run"), mock.patch(
            "firstboot.osinstall.fedora.wait_dev"
        ), mock.patch(
            "firstboot.osinstall.fedora.blkid_uuid", side_effect=lambda *_a, **_k: next(uuids)
        ), mock.patch(
            "firstboot.osinstall.fedora.detach_loops_on_disk"
        ), mock.patch(
            "firstboot.osinstall.fedora.umount_path"
        ), mock.patch("os.makedirs"):
            disk = partition_fedora_disk("/dev/sda", "/tmp/work")
        sgdisk = [
            a
            for a in runs
            if a and a[0] == "sgdisk" and any(str(x).startswith("--new=") for x in a)
        ]
        self.assertTrue(sgdisk)
        argv = sgdisk[0]
        self.assertIn(f"--new=1:1M:+{FEDORA_ESP_MIB}M", argv)
        self.assertIn(f"--new=2:0:+{FEDORA_BOOT_MIB}M", argv)
        self.assertIn("--new=3:0:0", argv)
        self.assertEqual(disk.esp_dev, "/dev/sda1")
        self.assertEqual(disk.boot_dev, "/dev/sda2")
        self.assertEqual(disk.root_dev, "/dev/sda3")
        self.assertEqual(disk.root_fstype, "btrfs")
        self.assertEqual(disk.root_fsopts, BTRFS_ROOT_OPTS)
        self.assertTrue(any(a and a[0] == "mkfs.btrfs" for a in runs))
        self.assertTrue(
            any(a and a[0] == "mkfs.ext4" and "boot" in a for a in runs)
        )


if __name__ == "__main__":
    unittest.main()
