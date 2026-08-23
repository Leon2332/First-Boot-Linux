#!/usr/bin/env python3
"""Ubuntu autoinstall helper — no root, no GTK."""

from __future__ import annotations

import gzip as gzipmod
import hashlib
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
CHOOSER_DIR = os.path.dirname(HERE)
if CHOOSER_DIR not in sys.path:
    sys.path.insert(0, CHOOSER_DIR)

from firstboot.disk import Disk, Partition, parse_helper_line, part_path  # noqa: E402
from firstboot.osinstall import (  # noqa: E402
    DRIVER_FEDORA,
    DRIVER_MINT,
    DRIVER_UBUNTU,
    FEDORA_LIVEINST_WRAPPER,
    FEDORA_LINUX_FLAG,
    FEDORA_LIVE_LABEL,
    ISO_REL_RE,
    MINT_LINUX_EXTRA,
    OsIdentity,
    autoinstall_yaml,
    fedora_kernel_args,
    fedora_kickstart,
    inject_into_initrd,
    iso_relpath,
    iso_volume_id,
    mint_preseed,
    osinstall_grub,
    plan_os_install,
    sha512_crypt,
    split_initrd,
    suggest_hostname,
    suggest_username,
    validate_identity,
    verify_iso,
    write_cpio,
    _casper_boot_files,
    _fedora_boot_files,
)
from firstboot.payload import Distro, Edition  # noqa: E402

ZERO = "0" * 64
UBUNTU_HASH = (
    "$6$exDY1mhS4KUYCE/2$"
    "zmn9ToZwTKLhCw.b4/b.ZRTIZM30JZ4QrOQ2aOXJ8yk96xpcCof0kxKwuX1kqLG/"
    "ygbJ1f8wxED22bTL4F46P0"
)


def disk(
    path: str,
    size: int,
    *,
    usb: bool = False,
    removable: bool = False,
    parts: list[Partition] | None = None,
) -> Disk:
    return Disk(
        path=path,
        size=size,
        model="",
        removable=removable,
        usb=usb,
        transport="usb" if usb else "",
        parts=tuple(parts or ()),
    )


def fbl_parts(dev: str, *, sys_mp: str = "/cdrom", data_mp: str = "/run/payload") -> list[Partition]:
    return [
        Partition(part_path(dev, 1), 512 * 1024 * 1024, "FBL-ESP", "FBL-ESP", "vfat"),
        Partition(
            part_path(dev, 2),
            2 * 1024 * 1024 * 1024,
            "FBL-SYS",
            "FBL-SYS",
            "ext4",
            (sys_mp,) if sys_mp else (),
        ),
        Partition(
            part_path(dev, 3),
            28 * 1024 * 1024 * 1024,
            "FBL-DATA",
            "FBL-DATA",
            "ext4",
            (data_mp,) if data_mp else (),
        ),
    ]


def ubuntu_distro(root: str, *, present: bool = True) -> Distro:
    iso_rel = "images/ubuntu-26.04-desktop-amd64.iso"
    path = os.path.join(root, iso_rel)
    if present:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(b"iso-bytes")
    sha = hashlib.sha256(b"iso-bytes").hexdigest() if present else ZERO
    ed = Edition(
        id="gnome",
        name="GNOME",
        default=True,
        claimed_local=True,
        file=iso_rel,
        url=None,
        sha256=sha,
        size_bytes=9 if present else 5900000000,
        available=present and os.path.isfile(path),
    )
    return Distro(
        id="ubuntu",
        name="Ubuntu",
        version="26.04 LTS",
        tagline="t",
        description="d",
        family="ubuntu",
        install=DRIVER_UBUNTU,
        editions=(ed,),
        recommended=True,
    )


def mint_distro(root: str, *, present: bool = True) -> Distro:
    iso_rel = "images/linuxmint-22.3-cinnamon-64bit.iso"
    path = os.path.join(root, iso_rel)
    if present:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(b"iso-bytes")
    sha = hashlib.sha256(b"iso-bytes").hexdigest() if present else ZERO
    ed = Edition(
        id="cinnamon",
        name="Cinnamon",
        default=True,
        claimed_local=True,
        file=iso_rel,
        url=None,
        sha256=sha,
        size_bytes=9 if present else 2800000000,
        available=present and os.path.isfile(path),
    )
    return Distro(
        id="linux-mint",
        name="Linux Mint",
        version="22.3",
        tagline="t",
        description="d",
        family="mint",
        install=DRIVER_MINT,
        editions=(ed,),
        recommended=True,
    )


def fedora_distro(root: str, *, present: bool = True) -> Distro:
    iso_rel = "images/Fedora-KDE-Desktop-Live-44-1.7.x86_64.iso"
    path = os.path.join(root, iso_rel)
    if present:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(b"iso-bytes")
    sha = hashlib.sha256(b"iso-bytes").hexdigest() if present else ZERO
    ed = Edition(
        id="plasma",
        name="KDE Plasma",
        default=True,
        claimed_local=True,
        file=iso_rel,
        url=None,
        sha256=sha,
        size_bytes=9 if present else 3368683520,
        available=present and os.path.isfile(path),
    )
    return Distro(
        id="fedora",
        name="Fedora",
        version="44",
        tagline="t",
        description="d",
        family="fedora",
        install=DRIVER_FEDORA,
        editions=(ed,),
        recommended=True,
    )


class HashTests(unittest.TestCase):
    def test_known_vector(self) -> None:
        got = sha512_crypt("ubuntu", "exDY1mhS4KUYCE/2")
        self.assertEqual(got, UBUNTU_HASH)

    def test_random_salt_roundtrip_prefix(self) -> None:
        hashed = sha512_crypt("secret-password")
        self.assertTrue(hashed.startswith("$6$"))
        self.assertGreater(len(hashed), 80)


class IdentityTests(unittest.TestCase):
    def test_suggest_username(self) -> None:
        self.assertEqual(suggest_username("Leon de Klerk"), "leon-de-klerk")
        self.assertEqual(suggest_username("123"), "user123")
        self.assertTrue(suggest_username("").startswith("user"))

    def test_suggest_hostname(self) -> None:
        self.assertEqual(suggest_hostname("leon"), "leon")
        self.assertEqual(suggest_hostname(""), "ubuntu")

    def test_validate(self) -> None:
        self.assertIsNone(validate_identity("pc", "leon", "Leon", "secret1"))
        self.assertIsNotNone(validate_identity("pc", "Leon", "Leon", "secret1"))
        self.assertIsNotNone(validate_identity("pc", "leon", "Leon", "ab"))
        self.assertIsNotNone(validate_identity("-bad", "leon", "Leon", "secret1"))


class YamlTests(unittest.TestCase):
    def test_autoinstall_pins_target_and_identity(self) -> None:
        ident = OsIdentity("shop-pc", "leon", "Leon", UBUNTU_HASH)
        text = autoinstall_yaml(ident, "/dev/sda")
        self.assertIn("autoinstall:", text)
        self.assertIn('hostname: "shop-pc"', text)
        self.assertIn('username: "leon"', text)
        self.assertIn("name: direct", text)
        self.assertRegex(text, r'path: "/dev/sda"')
        self.assertNotIn("/dev/disk/by-id/", text)
        self.assertNotIn("updates:", text)
        self.assertIn("offline-install", text)
        self.assertIn("shutdown: reboot", text)
        self.assertIn("/isodevice", text)
        self.assertIn("losetup", text)
        self.assertIn("/media/filesystem", text)
        self.assertIn("/run/fbl-casper", text)
        self.assertNotIn("FBL-SYS", text)
        self.assertIn("early-commands:", text)
        self.assertIn("late-commands:", text)
        self.assertIn("First Boot Linux", text)
        self.assertIn("efibootmgr", text)
        self.assertIn(UBUNTU_HASH, text)

    def test_mint_preseed_is_not_autoinstall(self) -> None:
        ident = OsIdentity("shop-pc", "leon", "Leon", UBUNTU_HASH)
        text = mint_preseed(ident, "/dev/sda")
        self.assertNotIn("autoinstall:", text)
        self.assertNotIn("subiquity", text)
        self.assertIn("d-i passwd/username string leon", text)
        self.assertIn("d-i passwd/user-fullname string Leon", text)
        self.assertIn("d-i netcfg/get_hostname string shop-pc", text)
        self.assertIn(UBUNTU_HASH, text)
        self.assertIn("d-i partman-auto/disk string /dev/sda", text)
        self.assertIn("d-i partman-auto/method string regular", text)
        self.assertIn("d-i partman-auto/choose_recipe select atomic", text)
        self.assertIn("ubiquity ubiquity/reboot boolean true", text)
        self.assertIn("ubiquity ubiquity/download_updates boolean false", text)
        self.assertIn("ubiquity ubiquity/reboot_on_failure boolean false", text)
        self.assertIn("localechooser/languagelist string en", text)
        self.assertIn("partman-auto/init_automatically_partition select regular", text)
        self.assertIn("/usr/lib/firstboot-efi-cleanup", text)
        self.assertNotIn("grub-installer/bootdev", text)
        self.assertIn("username=mint", MINT_LINUX_EXTRA)
        self.assertIn("hostname=mint", MINT_LINUX_EXTRA)
        self.assertIn("automatic-ubiquity", MINT_LINUX_EXTRA)
        self.assertNotIn("only-ubiquity", MINT_LINUX_EXTRA)
        self.assertNotIn("/dev/disk/by-id/", text)

    def test_fedora_kickstart_is_not_casper(self) -> None:
        ident = OsIdentity("shop-pc", "leon", "Leon", UBUNTU_HASH)
        text = fedora_kickstart(ident, "/dev/sda")
        self.assertNotIn("autoinstall:", text)
        self.assertNotIn("subiquity", text)
        self.assertNotIn("d-i ", text)
        self.assertNotIn("boot=casper", text)
        self.assertIn("graphical\n", text)
        self.assertNotIn("cmdline\n", text)
        self.assertIn("ignoredisk --only-use=sda", text)
        self.assertIn("clearpart --all --initlabel --disklabel=gpt --drives=sda", text)
        self.assertIn("autopart --type=btrfs", text)
        self.assertIn('user --name=leon --gecos="Leon"', text)
        self.assertIn(UBUNTU_HASH, text)
        self.assertIn("network --hostname=shop-pc", text)
        self.assertIn("rootpw --lock", text)
        self.assertIn('--kickstart=/ks.cfg --graphical', FEDORA_LIVEINST_WRAPPER)
        self.assertIn("--liveinst", FEDORA_LIVEINST_WRAPPER)
        self.assertIn("%pre", text)
        self.assertIn("%post", text)
        self.assertIn("First Boot Linux", text)
        self.assertIn("Install Fedora", text)
        self.assertIn("plasma-setup", text)
        self.assertNotIn("inst.ks", text)
        args = fedora_kernel_args(
            "/images/Fedora-KDE-Desktop-Live-44-1.7.x86_64.iso",
            FEDORA_LIVE_LABEL,
            toram=True,
        )
        self.assertIn("root=live:CDLABEL=Fedora-KDE-Live-44", args)
        self.assertIn("rd.live.image", args)
        self.assertIn("rd.live.ram=1", args)
        self.assertIn("iso-scan/filename=/images/Fedora-KDE-Desktop-Live-44-1.7.x86_64.iso", args)
        self.assertIn(FEDORA_LINUX_FLAG, args)
        self.assertIn("liveinst", args.split())
        self.assertNotIn("systemd.unit=multi-user.target", args)
        self.assertNotIn("boot=casper", args)
        self.assertNotIn("inst.ks", args)
        self.assertNotIn("autoinstall", args)

    def test_autoinstall_prefers_serial_match(self) -> None:
        ident = OsIdentity("shop-pc", "leon", "Leon", UBUNTU_HASH)
        text = autoinstall_yaml(
            ident, "/dev/sda", serial="ST1000LM035-1RK172_Z123"
        )
        self.assertIn('serial: "ST1000LM035-1RK172_Z123"', text)
        self.assertIn('path: "/dev/sda"', text)
        self.assertIn("- serial:", text)

    def test_grub_one_shot(self) -> None:
        cfg = osinstall_grub(
            "abc-uuid",
            "/images/ubuntu-26.04-desktop-amd64.iso",
            "Ubuntu (GNOME)",
            toram=True,
        )
        self.assertIn("set default=0", cfg)
        self.assertIn("iso-scan/filename=/images/ubuntu-26.04-desktop-amd64.iso", cfg)
        self.assertIn("toram autoinstall", cfg)
        self.assertIn("subiquity.autoinstallpath=/autoinstall.yaml", cfg)
        self.assertIn("/boot/osinstall/vmlinuz", cfg)
        self.assertIn("initrd /boot/osinstall/initrd", cfg)
        self.assertNotIn("seed.cpio", cfg)
        self.assertIn("First Boot Linux", cfg)
        cfg2 = osinstall_grub("abc-uuid", "/images/ubuntu-26.04-desktop-amd64.iso", "Ubuntu", toram=False)
        self.assertNotIn("toram", cfg2)
        self.assertIn("autoinstall", cfg2)

    def test_mint_grub_uses_ubiquity_not_subiquity(self) -> None:
        cfg = osinstall_grub(
            "abc-uuid",
            "/images/linuxmint-22.3-cinnamon-64bit.iso",
            "Linux Mint (Cinnamon)",
            toram=True,
            extra=MINT_LINUX_EXTRA,
        )
        self.assertIn("set default=0", cfg)
        self.assertIn("iso-scan/filename=/images/linuxmint-22.3-cinnamon-64bit.iso", cfg)
        self.assertIn("toram username=mint hostname=mint automatic-ubiquity", cfg)
        self.assertNotIn("only-ubiquity", cfg)
        self.assertNotIn("autoinstall", cfg)
        self.assertNotIn("subiquity", cfg)
        self.assertIn("/boot/osinstall/vmlinuz", cfg)
        self.assertIn("initrd /boot/osinstall/initrd", cfg)
        self.assertIn("First Boot Linux", cfg)

    def test_fedora_grub_is_dracut_not_casper(self) -> None:
        iso = "/images/Fedora-KDE-Desktop-Live-44-1.7.x86_64.iso"
        args = fedora_kernel_args(iso, FEDORA_LIVE_LABEL, toram=True)
        cfg = osinstall_grub(
            "abc-uuid",
            iso,
            "Fedora (KDE Plasma)",
            toram=True,
            linux_args=args,
        )
        self.assertIn("set default=0", cfg)
        self.assertIn("iso-scan/filename=/images/Fedora-KDE-Desktop-Live-44-1.7.x86_64.iso", cfg)
        self.assertIn("rd.live.image", cfg)
        self.assertIn("rd.live.ram=1", cfg)
        self.assertIn("root=live:CDLABEL=Fedora-KDE-Live-44", cfg)
        self.assertIn(FEDORA_LINUX_FLAG, cfg)
        install_line = [
            line
            for line in cfg.splitlines()
            if "linux /boot/osinstall/vmlinuz" in line
        ][0]
        self.assertNotIn("boot=casper", install_line)
        self.assertNotIn("live-media-path=casper", install_line)
        self.assertNotIn("autoinstall", install_line)
        self.assertNotIn("subiquity", install_line)
        self.assertNotIn("inst.ks", install_line)
        self.assertIn("liveinst", install_line.split())
        self.assertNotIn("systemd.unit=multi-user.target", install_line)
        self.assertIn("/boot/osinstall/vmlinuz", cfg)
        self.assertIn("initrd /boot/osinstall/initrd", cfg)
        self.assertIn("First Boot Linux", cfg)
        cfg2 = osinstall_grub(
            "abc-uuid", iso, "Fedora", toram=False, linux_args=fedora_kernel_args(iso, FEDORA_LIVE_LABEL, toram=False)
        )
        self.assertNotIn("rd.live.ram", cfg2)

    def test_iso_rel(self) -> None:
        self.assertEqual(iso_relpath("images/ubuntu-26.04-desktop-amd64.iso"), "/images/ubuntu-26.04-desktop-amd64.iso")
        self.assertTrue(ISO_REL_RE.fullmatch("/images/ubuntu-26.04-desktop-amd64.iso"))
        self.assertTrue(ISO_REL_RE.fullmatch("/images/linuxmint-22.3-cinnamon-64bit.iso"))
        self.assertTrue(ISO_REL_RE.fullmatch("/images/Fedora-KDE-Desktop-Live-44-1.7.x86_64.iso"))
        self.assertFalse(ISO_REL_RE.fullmatch("/etc/passwd"))
        self.assertFalse(ISO_REL_RE.fullmatch("/images/../ubuntu.iso"))


class PlanTests(unittest.TestCase):
    def test_same_disk_when_already_on_internal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            distro = ubuntu_distro(tmp)
            sda = disk("/dev/sda", 512 * 1024**3, parts=fbl_parts("/dev/sda"))
            mounts = {"/cdrom": "/dev/sda2", "/run/payload": "/dev/sda3"}
            plan = plan_os_install([sda], mounts, tmp, distro, distro.default_edition)
            self.assertTrue(plan.available, plan.reason)
            self.assertTrue(plan.same_disk)
            self.assertEqual(plan.target.path, "/dev/sda")
            self.assertEqual(plan.driver, DRIVER_UBUNTU)

    def test_internal_boot_ignores_plugged_usb(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            distro = ubuntu_distro(tmp)
            usb = disk(
                "/dev/sdb",
                32 * 1024**3,
                usb=True,
                removable=True,
                parts=fbl_parts("/dev/sdb", sys_mp="", data_mp=""),
            )
            sda = disk("/dev/sda", 512 * 1024**3, parts=fbl_parts("/dev/sda"))
            mounts = {"/cdrom": "/dev/sda2", "/run/payload": "/dev/sda3"}
            plan = plan_os_install([usb, sda], mounts, tmp, distro, distro.default_edition)
            self.assertTrue(plan.available, plan.reason)
            self.assertTrue(plan.same_disk)
            self.assertEqual(plan.live.path, "/dev/sda")
            self.assertEqual(plan.target.path, "/dev/sda")

    def test_usb_boot_installs_to_internal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            distro = ubuntu_distro(tmp)
            usb = disk(
                "/dev/sdb",
                32 * 1024**3,
                usb=True,
                removable=True,
                parts=fbl_parts("/dev/sdb"),
            )
            sda = disk("/dev/sda", 512 * 1024**3, parts=fbl_parts("/dev/sda", sys_mp="", data_mp=""))
            mounts = {"/cdrom": "/dev/sdb2", "/run/payload": "/dev/sdb3"}
            plan = plan_os_install([usb, sda], mounts, tmp, distro, distro.default_edition)
            self.assertTrue(plan.available, plan.reason)
            self.assertFalse(plan.same_disk)
            self.assertEqual(plan.live.path, "/dev/sdb")
            self.assertEqual(plan.target.path, "/dev/sda")

    def test_mint_same_disk_is_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            distro = mint_distro(tmp)
            sda = disk("/dev/sda", 512 * 1024**3, parts=fbl_parts("/dev/sda"))
            mounts = {"/cdrom": "/dev/sda2", "/run/payload": "/dev/sda3"}
            plan = plan_os_install([sda], mounts, tmp, distro, distro.default_edition)
            self.assertTrue(plan.available, plan.reason)
            self.assertTrue(plan.same_disk)
            self.assertEqual(plan.driver, DRIVER_MINT)
            self.assertEqual(plan.iso_rel, "/images/linuxmint-22.3-cinnamon-64bit.iso")

    def test_fedora_same_disk_is_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            distro = fedora_distro(tmp)
            sda = disk("/dev/sda", 512 * 1024**3, parts=fbl_parts("/dev/sda"))
            mounts = {"/cdrom": "/dev/sda2", "/run/payload": "/dev/sda3"}
            plan = plan_os_install([sda], mounts, tmp, distro, distro.default_edition)
            self.assertTrue(plan.available, plan.reason)
            self.assertTrue(plan.same_disk)
            self.assertEqual(plan.driver, DRIVER_FEDORA)
            self.assertEqual(
                plan.iso_rel, "/images/Fedora-KDE-Desktop-Live-44-1.7.x86_64.iso"
            )

    def test_unknown_driver_is_not_ready(self) -> None:
        sda = disk("/dev/sda", 512 * 1024**3, parts=fbl_parts("/dev/sda"))
        ed = Edition(
            id="gnome",
            name="GNOME",
            default=True,
            claimed_local=True,
            file="images/debian-13.0.0-amd64-DVD-1.iso",
            url=None,
            sha256=ZERO,
            size_bytes=3800000000,
            available=True,
        )
        distro = Distro(
            id="debian",
            name="Debian",
            version="13",
            tagline="t",
            description="d",
            family="debian",
            install="debian-preseed",
            editions=(ed,),
            recommended=True,
        )
        plan = plan_os_install(
            [sda],
            {"/cdrom": "/dev/sda2"},
            "/run/payload",
            distro,
            distro.default_edition,
        )
        self.assertFalse(plan.available)
        self.assertIn("not available", plan.reason)

    def test_missing_iso(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            distro = ubuntu_distro(tmp, present=False)
            sda = disk("/dev/sda", 512 * 1024**3, parts=fbl_parts("/dev/sda"))
            plan = plan_os_install(
                [sda],
                {"/cdrom": "/dev/sda2", "/run/payload": "/dev/sda3"},
                tmp,
                distro,
                distro.default_edition,
            )
            self.assertFalse(plan.available)


class VerifyTests(unittest.TestCase):
    def test_verify_ok_and_progress(self) -> None:
        with tempfile.NamedTemporaryFile(delete=False) as fh:
            fh.write(b"hello-iso")
            path = fh.name
        try:
            digest = hashlib.sha256(b"hello-iso").hexdigest()
            seen: list[int] = []
            verify_iso(path, digest, size_bytes=9, on_progress=seen.append)
            self.assertTrue(seen)
            self.assertEqual(seen[-1], 100)
        finally:
            os.unlink(path)

    def test_verify_rejects_bad_hash(self) -> None:
        with tempfile.NamedTemporaryFile(delete=False) as fh:
            fh.write(b"hello-iso")
            path = fh.name
        try:
            with self.assertRaises(Exception):
                verify_iso(path, ZERO)
        finally:
            os.unlink(path)


class CpioTests(unittest.TestCase):
    def test_write_cpio(self) -> None:
        with tempfile.NamedTemporaryFile(delete=False) as fh:
            path = fh.name
        try:
            write_cpio(
                path,
                {
                    "autoinstall.yaml": "autoinstall:\n  version: 1\n",
                    "scripts/casper-bottom/29fbl-autoinstall": "#!/bin/sh\n",
                },
            )
            with open(path, "rb") as fh:
                data = fh.read()
            self.assertIn(b"autoinstall.yaml", data)
            self.assertIn(b"version: 1", data)
            self.assertIn(b"29fbl-autoinstall", data)
            self.assertNotIn(b"initrd-head", data)
        finally:
            os.unlink(path)

    def test_inject_into_gzip_main_archive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            early = os.path.join(tmp, "early")
            main = os.path.join(tmp, "main")
            initrd = os.path.join(tmp, "initrd")
            write_cpio(early, {"kernel/x86/microcode/fake": b"ucode"})
            write_cpio(
                main,
                {
                    "scripts/casper-bottom/01hostname": "#!/bin/sh\n",
                    "scripts/casper-bottom/ORDER": "/scripts/casper-bottom/01hostname\n",
                },
            )
            with open(early, "rb") as fh:
                early_b = fh.read()
            with open(main, "rb") as fh:
                main_b = gzipmod.compress(fh.read())
            with open(initrd, "wb") as fh:
                fh.write(early_b + main_b)
            inject_into_initrd(
                initrd,
                {
                    "autoinstall.yaml": "autoinstall:\n  version: 1\n",
                    "scripts/casper-bottom/29fbl-autoinstall": "#!/bin/sh\nexit 0\n",
                },
            )
            with open(initrd, "rb") as fh:
                parts = split_initrd(fh.read())
            self.assertEqual(len(parts), 2)
            self.assertTrue(parts[1].startswith(b"\x1f\x8b"))
            unpacked = os.path.join(tmp, "out")
            os.mkdir(unpacked)
            subprocess.run(
                ["cpio", "-id", "--no-absolute-filenames"],
                cwd=unpacked,
                input=gzipmod.decompress(parts[1]),
                check=True,
                capture_output=True,
            )
            self.assertTrue(os.path.isfile(os.path.join(unpacked, "autoinstall.yaml")))
            self.assertTrue(
                os.path.isfile(
                    os.path.join(unpacked, "scripts/casper-bottom/29fbl-autoinstall")
                )
            )
            with open(
                os.path.join(unpacked, "scripts/casper-bottom/ORDER"), encoding="ascii"
            ) as fh:
                order = fh.read()
            self.assertIn("29fbl-autoinstall", order)
            self.assertNotIn("29fbl-mint", order)

    def test_inject_mint_preseed_into_zstd_archive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            early = os.path.join(tmp, "early")
            main = os.path.join(tmp, "main")
            initrd = os.path.join(tmp, "initrd")
            write_cpio(early, {"kernel/x86/microcode/fake": b"ucode"})
            write_cpio(
                main,
                {
                    "scripts/casper-bottom/24preseed": "#!/bin/sh\n",
                    "scripts/casper-bottom/ORDER": "/scripts/casper-bottom/24preseed\n",
                },
            )
            with open(early, "rb") as fh:
                early_b = fh.read()
            with open(main, "rb") as fh:
                main_b = fh.read()
            packed = subprocess.run(
                ["zstd", "-1", "-c"],
                input=main_b,
                check=True,
                capture_output=True,
            )
            with open(initrd, "wb") as fh:
                fh.write(early_b + packed.stdout)
            inject_into_initrd(
                initrd,
                {
                    "preseed.cfg": "d-i debian-installer/locale string en_US.UTF-8\n",
                    "scripts/casper-bottom/29fbl-mint": "#!/bin/sh\nexit 0\n",
                },
            )
            with open(initrd, "rb") as fh:
                parts = split_initrd(fh.read())
            self.assertEqual(len(parts), 2)
            self.assertTrue(parts[1].startswith(b"\x28\xb5\x2f\xfd"))
            unpacked = os.path.join(tmp, "out")
            os.mkdir(unpacked)
            raw = subprocess.run(
                ["zstd", "-d", "-c"],
                input=parts[1],
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["cpio", "-id", "--no-absolute-filenames"],
                cwd=unpacked,
                input=raw.stdout,
                check=True,
                capture_output=True,
            )
            self.assertTrue(os.path.isfile(os.path.join(unpacked, "preseed.cfg")))
            self.assertTrue(
                os.path.isfile(
                    os.path.join(unpacked, "scripts/casper-bottom/29fbl-mint")
                )
            )
            with open(
                os.path.join(unpacked, "scripts/casper-bottom/ORDER"), encoding="ascii"
            ) as fh:
                order = fh.read()
            self.assertIn("29fbl-mint", order)
            self.assertIn("24preseed", order)
            self.assertNotIn("autoinstall.yaml", order)

    def test_inject_fedora_kickstart_into_gzip_archive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            early = os.path.join(tmp, "early")
            main = os.path.join(tmp, "main")
            initrd = os.path.join(tmp, "initrd")
            write_cpio(early, {"kernel/x86/microcode/fake": b"ucode"})
            write_cpio(main, {"init": "#!/bin/sh\n"})
            with open(early, "rb") as fh:
                early_b = fh.read()
            with open(main, "rb") as fh:
                main_b = gzipmod.compress(fh.read())
            with open(initrd, "wb") as fh:
                fh.write(early_b + main_b)
            inject_into_initrd(
                initrd,
                {
                    "ks.cfg": "graphical\n",
                    "fbl-liveinst": "#!/bin/bash\nexit 0\n",
                    "var/lib/dracut/hooks/pre-pivot/90-fbl-ks.sh": "#!/bin/sh\nexit 0\n",
                },
            )
            with open(initrd, "rb") as fh:
                parts = split_initrd(fh.read())
            self.assertEqual(len(parts), 2)
            unpacked = os.path.join(tmp, "out")
            os.mkdir(unpacked)
            subprocess.run(
                ["cpio", "-id", "--no-absolute-filenames"],
                cwd=unpacked,
                input=gzipmod.decompress(parts[1]),
                check=True,
                capture_output=True,
            )
            self.assertTrue(os.path.isfile(os.path.join(unpacked, "ks.cfg")))
            hook = os.path.join(
                unpacked, "var/lib/dracut/hooks/pre-pivot/90-fbl-ks.sh"
            )
            self.assertTrue(os.path.isfile(hook))
            self.assertTrue(os.access(hook, os.X_OK))
            wrapper = os.path.join(unpacked, "fbl-liveinst")
            self.assertTrue(os.path.isfile(wrapper))
            self.assertTrue(os.access(wrapper, os.X_OK))


class CasperBootTests(unittest.TestCase):
    def test_prefers_initrd_then_lz(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            casper = os.path.join(tmp, "casper")
            os.makedirs(casper)
            open(os.path.join(casper, "vmlinuz"), "wb").close()
            lz = os.path.join(casper, "initrd.lz")
            open(lz, "wb").close()
            vmlinuz, initrd = _casper_boot_files(tmp)
            self.assertEqual(initrd, lz)
            plain = os.path.join(casper, "initrd")
            open(plain, "wb").close()
            vmlinuz, initrd = _casper_boot_files(tmp)
            self.assertEqual(initrd, plain)
            self.assertTrue(vmlinuz.endswith("vmlinuz"))

    def test_fedora_f44_loader_preferred(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            loader = os.path.join(tmp, "boot", "x86_64", "loader")
            pxe = os.path.join(tmp, "images", "pxeboot")
            os.makedirs(loader)
            os.makedirs(pxe)
            linux = os.path.join(loader, "linux")
            initrd = os.path.join(loader, "initrd")
            open(linux, "wb").close()
            open(initrd, "wb").close()
            open(os.path.join(pxe, "vmlinuz"), "wb").close()
            open(os.path.join(pxe, "initrd.img"), "wb").close()
            got_v, got_i = _fedora_boot_files(tmp)
            self.assertEqual(got_v, linux)
            self.assertEqual(got_i, initrd)

    def test_fedora_pxeboot_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pxe = os.path.join(tmp, "images", "pxeboot")
            os.makedirs(pxe)
            vmlinuz = os.path.join(pxe, "vmlinuz")
            initrd = os.path.join(pxe, "initrd.img")
            open(vmlinuz, "wb").close()
            open(initrd, "wb").close()
            got_v, got_i = _fedora_boot_files(tmp)
            self.assertEqual(got_v, vmlinuz)
            self.assertEqual(got_i, initrd)

    def test_iso_volume_id(self) -> None:
        with tempfile.NamedTemporaryFile(delete=False) as fh:
            fh.write(b"\x00" * 32768)
            pvd = bytearray(2048)
            pvd[0] = 1
            pvd[1:6] = b"CD001"
            pvd[40:72] = b"Fedora-KDE-Live-44              "
            fh.write(pvd)
            path = fh.name
        try:
            self.assertEqual(iso_volume_id(path), "Fedora-KDE-Live-44")
        finally:
            os.unlink(path)


class ProtocolTests(unittest.TestCase):
    def test_reboot_line(self) -> None:
        ev = parse_helper_line("REBOOT")
        self.assertIsNotNone(ev)
        self.assertEqual(ev.kind, "reboot")
        self.assertEqual(ev.progress, 100)


if __name__ == "__main__":
    unittest.main()
