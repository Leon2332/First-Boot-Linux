#!/usr/bin/env python3
"""Ubuntu autoinstall helper — no root, no GTK."""

from __future__ import annotations

import gzip as gzipmod
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
CHOOSER_DIR = os.path.dirname(HERE)
if CHOOSER_DIR not in sys.path:
    sys.path.insert(0, CHOOSER_DIR)

from firstboot.disk import Disk, Partition, parse_helper_line, part_path  # noqa: E402
from firstboot.osinstall import (  # noqa: E402
    DRIVER_MINT_CINNAMON,
    DRIVER_MINT_MATE,
    DRIVER_MINT_XFCE,
    DRIVER_UBUNTU_GNOME,
    canonical_driver_id,
    get_driver,
    is_native_driver,
    ISO_REL_RE,
    inject_into_initrd,
    iso_relpath,
    iso_volume_id,
    osinstall_grub,
    live_os_plan,
    plan_os_install,
    sha512_crypt,
    split_initrd,
    suggest_hostname,
    suggest_username,
    validate_identity,
    verify_iso,
    write_cpio,
    _casper_boot_files,
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
        install=DRIVER_UBUNTU_GNOME,
        editions=(ed,),
        recommended=True,
    )


class RegistryTests(unittest.TestCase):
    def test_catalog_ids_and_old_aliases(self) -> None:
        self.assertEqual(DRIVER_UBUNTU_GNOME, "ubuntu-2604-gnome")
        self.assertEqual(get_driver("ubuntu-2604-gnome").default_hostname, "ubuntu")
        self.assertTrue(is_native_driver(get_driver("ubuntu-2604-gnome")))
        self.assertEqual(DRIVER_MINT_CINNAMON, "mint-223-cinnamon")
        self.assertEqual(get_driver("mint-223-cinnamon").default_hostname, "mint")
        self.assertTrue(is_native_driver(get_driver("mint-223-cinnamon")))
        self.assertEqual(get_driver("mint-223-cinnamon").display_manager, "lightdm")
        self.assertEqual(DRIVER_MINT_MATE, "mint-223-mate")
        self.assertTrue(is_native_driver(get_driver("mint-223-mate")))
        self.assertEqual(get_driver("mint-223-mate").display_manager, "lightdm")
        self.assertEqual(DRIVER_MINT_XFCE, "mint-223-xfce")
        self.assertTrue(is_native_driver(get_driver("mint-223-xfce")))
        self.assertEqual(get_driver("mint-223-xfce").display_manager, "lightdm")
        self.assertIsNone(get_driver("ubuntu-2604"))
        self.assertIsNone(get_driver("ubuntu-autoinstall"))
        self.assertIsNone(get_driver("ubuntu-calamares-2604"))
        self.assertIsNone(get_driver("mint-223"))
        self.assertIsNone(get_driver("mint"))
        self.assertIsNone(get_driver("fedora-44-plasma"))
        self.assertIsNone(get_driver("fedora-kickstart"))
        self.assertEqual(canonical_driver_id("ubuntu-autoinstall"), "ubuntu-autoinstall")
        self.assertIsNone(get_driver("deepin-25"))

    def test_custom_pack_driver(self) -> None:
        root = tempfile.mkdtemp(prefix="fbl-pack-")
        try:
            drv = os.path.join(root, "custom", "pop-os", "driver.py")
            os.makedirs(os.path.dirname(drv), exist_ok=True)
            with open(drv, "w", encoding="utf-8") as fh:
                fh.write(
                    "from firstboot.osinstall.common import OsInstallError\n"
                    "ID = 'pop-os'\n"
                    "class P:\n"
                    "    id = ID\n"
                    "    aliases = ()\n"
                    "    default_hostname = 'pop-os'\n"
                    "    def boot_files(self, iso_mnt):\n"
                    "        return 'v', 'i'\n"
                    "    def kernel_args(self, iso_rel, *, toram, iso_path=''):\n"
                    "        return 'boot=casper'\n"
                    "    def seed_files(self, identity, target_path, serial, locale=None):\n"
                    "        return {}\n"
                    "DRIVER = P()\n"
                )
            loaded = get_driver("pop-os", root)
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.id, "pop-os")
            self.assertEqual(loaded.boot_files("/iso"), ("v", "i"))
            self.assertIs(get_driver("pop-os", root), loaded)
            self.assertIsNone(get_driver("no-such-pack", root))
        finally:
            shutil.rmtree(root, ignore_errors=True)


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
    def test_grub_one_shot(self) -> None:
        cfg = osinstall_grub(
            "abc-uuid",
            "/images/ubuntu-26.04-desktop-amd64.iso",
            "Ubuntu (GNOME)",
            toram=True,
        )
        self.assertIn("set default=0", cfg)
        self.assertIn("iso-scan/filename=/images/ubuntu-26.04-desktop-amd64.iso", cfg)
        self.assertIn("toram", cfg)
        self.assertNotIn("autoinstall", cfg)
        self.assertNotIn("subiquity", cfg)
        self.assertIn("/boot/osinstall/vmlinuz", cfg)
        self.assertIn("initrd /boot/osinstall/initrd", cfg)
        self.assertNotIn("seed.cpio", cfg)
        self.assertIn("First Boot Linux", cfg)
        cfg2 = osinstall_grub("abc-uuid", "/images/ubuntu-26.04-desktop-amd64.iso", "Ubuntu", toram=False)
        self.assertNotIn("toram", cfg2)

    def test_grub_passes_extra(self) -> None:
        cfg = osinstall_grub(
            "abc-uuid",
            "/images/shop-os.iso",
            "Shop OS",
            toram=True,
            extra="custom-flag",
        )
        self.assertIn("toram custom-flag", cfg)
        self.assertIn("iso-scan/filename=/images/shop-os.iso", cfg)

    def test_iso_rel(self) -> None:
        self.assertEqual(iso_relpath("images/ubuntu-26.04-desktop-amd64.iso"), "/images/ubuntu-26.04-desktop-amd64.iso")
        self.assertTrue(ISO_REL_RE.fullmatch("/images/ubuntu-26.04-desktop-amd64.iso"))
        self.assertTrue(ISO_REL_RE.fullmatch("/images/linuxmint-22.3-cinnamon-64bit.iso"))
        self.assertTrue(ISO_REL_RE.fullmatch("/images/linuxmint-22.3-mate-64bit.iso"))
        self.assertTrue(ISO_REL_RE.fullmatch("/images/linuxmint-22.3-xfce-64bit.iso"))
        self.assertTrue(ISO_REL_RE.fullmatch("/images/Fedora-KDE-Desktop-Live-44-1.7.x86_64.iso"))
        self.assertTrue(ISO_REL_RE.fullmatch("/images/pop-os_22.04_amd64_intel.iso"))
        self.assertTrue(ISO_REL_RE.fullmatch("/images/shop-os.img"))
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
            self.assertEqual(plan.driver, DRIVER_UBUNTU_GNOME)

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

    def test_live_os_plan_remounts_missing_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            distro = ubuntu_distro(tmp)
            sda = disk("/dev/sda", 512 * 1024**3, parts=fbl_parts("/dev/sda"))
            with mock.patch("firstboot.osinstall.live_lsblk", return_value=[sda]), mock.patch(
                "firstboot.osinstall.live_mounts",
                side_effect=[{}, {"/run/payload": "/dev/sda3"}],
            ), mock.patch("firstboot.osinstall._remount_payload") as remount, mock.patch(
                "os.path.isfile",
                side_effect=lambda p: p.endswith(".iso") and os.path.exists(p),
            ):
                # first isfile for the iso is False until remount copies... the iso
                # already exists under tmp. Force a miss then a hit via exists.
                iso = os.path.join(tmp, distro.default_edition.file)
                calls = {"n": 0}

                def isfile(path: str) -> bool:
                    if path == iso:
                        calls["n"] += 1
                        return calls["n"] > 1
                    return os.path.isfile(path)

                with mock.patch("os.path.isfile", side_effect=isfile):
                    plan = live_os_plan(tmp, distro, distro.default_edition)
            remount.assert_called_once()
            self.assertTrue(plan.available, plan.reason)

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

    def test_edition_install_overrides_distro(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            distro = ubuntu_distro(tmp)
            ed = distro.editions[0]
            ed = Edition(
                id=ed.id,
                name=ed.name,
                default=ed.default,
                claimed_local=ed.claimed_local,
                file=ed.file,
                url=ed.url,
                sha256=ed.sha256,
                size_bytes=ed.size_bytes,
                available=ed.available,
                install=DRIVER_UBUNTU_GNOME,
            )
            distro = Distro(
                id=distro.id,
                name=distro.name,
                version=distro.version,
                tagline=distro.tagline,
                description=distro.description,
                family=distro.family,
                install="ubuntu-2604",
                editions=(ed,),
                recommended=True,
            )
            self.assertEqual(distro.install_for(ed), DRIVER_UBUNTU_GNOME)
            sda = disk("/dev/sda", 512 * 1024**3, parts=fbl_parts("/dev/sda"))
            mounts = {"/cdrom": "/dev/sda2", "/run/payload": "/dev/sda3"}
            plan = plan_os_install([sda], mounts, tmp, distro, ed)
            self.assertTrue(plan.available, plan.reason)
            self.assertEqual(plan.driver, DRIVER_UBUNTU_GNOME)

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
                    "ks.cfg": "cmdline\n",
                    "usr/libexec/fbl-link-squashfs": "#!/bin/bash\nexit 0\n",
                    "usr/libexec/fbl-anaconda": "#!/bin/bash\nexit 0\n",
                    "etc/systemd/system/getty@tty1.service": "[Unit]\n",
                    "etc/systemd/system-generators/fbl-anaconda-gen": "#!/bin/sh\nexit 0\n",
                    "var/lib/dracut/hooks/pre-pivot/90-fbl-ks.sh": "#!/bin/sh\n",
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
            link = os.path.join(unpacked, "usr/libexec/fbl-link-squashfs")
            self.assertTrue(os.path.isfile(link))
            self.assertTrue(os.access(link, os.X_OK))
            ana = os.path.join(unpacked, "usr/libexec/fbl-anaconda")
            self.assertTrue(os.path.isfile(ana))
            self.assertTrue(os.access(ana, os.X_OK))
            unit = os.path.join(
                unpacked, "etc/systemd/system/getty@tty1.service"
            )
            self.assertTrue(os.path.isfile(unit))
            self.assertEqual(os.stat(unit).st_mode & 0o111, 0)
            gen = os.path.join(
                unpacked, "etc/systemd/system-generators/fbl-anaconda-gen"
            )
            self.assertTrue(os.path.isfile(gen))
            self.assertTrue(os.access(gen, os.X_OK))


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

    def test_tick_lines(self) -> None:
        ticks = parse_helper_line("TICKS Checking the image|Preparing the disk|Restarting")
        self.assertIsNotNone(ticks)
        self.assertEqual(ticks.kind, "ticks")
        self.assertEqual(
            ticks.ticks, ("Checking the image", "Preparing the disk", "Restarting")
        )
        current = parse_helper_line("TICK 4 current")
        self.assertEqual(current.kind, "tick")
        self.assertEqual(current.tick, 4)
        self.assertEqual(current.tick_status, "current")
        done = parse_helper_line("TICK 2 skip")
        self.assertEqual(done.tick_status, "skip")


if __name__ == "__main__":
    unittest.main()
