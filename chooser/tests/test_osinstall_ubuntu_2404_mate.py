#!/usr/bin/env python3
"""Ubuntu MATE 24.04.4 native installer."""

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
    BOOTLOADER_EXTRACT_PREFIXES,
    casper_leftovers,
    ensure_grub_efi_modules,
    extract_signed_efi_debs,
    install_kernel_from_iso,
    iso_kernel_package,
    kernel_dpkg_debs,
    mate_iso_extras,
    parse_install_sources,
)
from firstboot.osinstall.ubuntu_2404_mate import DRIVER, ID  # noqa: E402

UBUNTU_HASH = (
    "$6$exDY1mhS4KUYCE/2$"
    "zmn9ToZwTKLhCw.b4/b.ZRTIZM30JZ4QrOQ2aOXJ8yk96xpcCof0kxKwuX1kqLG/"
    "ygbJ1f8wxED22bTL4F46P0"
)


def fake_tree(root: str) -> None:
    boot = os.path.join(root, "boot")
    os.makedirs(boot)
    open(os.path.join(boot, "vmlinuz-6.17.0-14-generic"), "wb").close()
    open(os.path.join(boot, "initrd.img-6.17.0-14-generic"), "wb").close()
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
            "autologin-session=mate\n"
            "user-session=mate\n"
        )
    with open(
        os.path.join(root, "etc", "lightdm", "lightdm.conf.d", "90-casper.conf"),
        "w",
        encoding="utf-8",
    ) as fh:
        fh.write("[Seat:*]\nautologin-user=ubuntu\n")
    with open(
        os.path.join(root, "etc", "lightdm", "lightdm.conf.d", "50-ubuntu-mate.conf"),
        "w",
        encoding="utf-8",
    ) as fh:
        fh.write(
            "[Seat:*]\n"
            "autologin-user=ubuntu\n"
            "greeter-session=slick-greeter\n"
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
            "    name: ubuntu-desktop-bootstrap\n"
            "    file: ubuntu-desktop-bootstrap_433.snap\n"
            "  -\n"
            "    name: subiquity\n"
            "    file: subiquity_6871.snap\n"
        )
    open(os.path.join(snap_dir, "ubuntu-desktop-bootstrap_433.snap"), "wb").close()
    open(os.path.join(snap_dir, "subiquity_6871.snap"), "wb").close()


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


class Ubuntu2404MateTests(unittest.TestCase):
    def test_driver_contract(self) -> None:
        self.assertEqual(ID, "ubuntu-2404-mate")
        self.assertEqual(DRIVER.id, ID)
        self.assertEqual(DRIVER.aliases, ())
        self.assertEqual(DRIVER.unpack_kind, "casper-layered")
        self.assertEqual(DRIVER.display_manager, "lightdm")
        self.assertEqual(DRIVER.live_usernames, ("ubuntu",))
        self.assertEqual(DRIVER.default_hostname, "ubuntu")
        self.assertEqual(DRIVER.bootloader_id, "ubuntu")
        self.assertEqual(DRIVER.nvram_label, "Ubuntu")
        self.assertIn("grub2-common_", BOOTLOADER_EXTRACT_PREFIXES)
        self.assertIn("grub-efi-amd64-signed_", BOOTLOADER_EXTRACT_PREFIXES)
        self.assertTrue(is_native_driver(DRIVER))
        self.assertFalse(hasattr(DRIVER, "seed_files") and callable(DRIVER.seed_files))

    def test_layered_relpaths_skip_live(self) -> None:
        iso = tempfile.mkdtemp(prefix="fbl-mate-iso-")
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
        iso = tempfile.mkdtemp(prefix="fbl-mate-src-")
        try:
            casper_dir = os.path.join(iso, "casper")
            os.makedirs(casper_dir)
            with open(
                os.path.join(casper_dir, "install-sources.yaml"),
                "w",
                encoding="utf-8",
            ) as fh:
                fh.write(
                    "- default: false\n"
                    "  id: ubuntu-mate-desktop-minimal\n"
                    "  path: minimal.squashfs\n"
                    "  type: fsimage-layered\n"
                    "- default: true\n"
                    "  id: ubuntu-mate-desktop\n"
                    "  path: minimal.standard.squashfs\n"
                    "  type: fsimage-layered\n"
                )
            parsed = parse_install_sources(iso)
            # 24.04 yaml has no top-level sources:/kernel: keys.
            self.assertEqual(parsed["kernel"], "")
            self.assertNotIn("live", parsed.get("path", ""))
        finally:
            shutil.rmtree(iso, ignore_errors=True)

    def test_iso_kernel_package_falls_back_to_pool_hwe_24(self) -> None:
        iso = tempfile.mkdtemp(prefix="fbl-mate-pool-")
        try:
            casper_dir = os.path.join(iso, "casper")
            os.makedirs(casper_dir)
            deb_dir = os.path.join(iso, "pool", "main", "l", "linux-meta-hwe-6.17")
            os.makedirs(deb_dir)
            open(
                os.path.join(
                    deb_dir, "linux-generic-hwe-24.04_6.17.0-14.14~24.04.1_amd64.deb"
                ),
                "wb",
            ).close()
            self.assertEqual(iso_kernel_package(iso), "linux-generic-hwe-24.04")
        finally:
            shutil.rmtree(iso, ignore_errors=True)

    def test_iso_extras_kernel_firmware_and_signed_grub(self) -> None:
        iso = tempfile.mkdtemp(prefix="fbl-mate-extra-")
        try:
            dists = os.path.join(iso, "dists", "noble", "main", "binary-amd64")
            os.makedirs(dists)
            open(os.path.join(dists, "Packages"), "wb").close()
            meta = os.path.join(iso, "pool", "main", "l", "linux-meta-hwe-6.17")
            fw = os.path.join(iso, "pool", "main", "l", "linux-firmware")
            grub = os.path.join(iso, "pool", "main", "g", "grub2-signed")
            os.makedirs(meta)
            os.makedirs(fw)
            os.makedirs(grub)
            open(
                os.path.join(meta, "linux-image-generic-hwe-24.04_1_amd64.deb"),
                "wb",
            ).close()
            open(os.path.join(fw, "linux-firmware_1_all.deb"), "wb").close()
            open(
                os.path.join(grub, "grub-efi-amd64-signed_1.202.5+2.12_amd64.deb"),
                "wb",
            ).close()
            extras = DRIVER.iso_extras(iso)
            self.assertEqual(extras, mate_iso_extras(iso))
            self.assertIn("dists", extras)
            self.assertTrue(
                any("linux-image-generic-hwe-24.04" in rel for rel in extras),
                extras,
            )
            self.assertTrue(any("linux-firmware" in rel for rel in extras), extras)
            self.assertTrue(
                any("grub-efi-amd64-signed" in rel for rel in extras), extras
            )
        finally:
            shutil.rmtree(iso, ignore_errors=True)

    def test_kernel_dpkg_debs_order_skips_headers(self) -> None:
        iso = tempfile.mkdtemp(prefix="fbl-mate-kdebs-")
        try:
            pool = os.path.join(iso, "pool", "main", "l")
            for sub, name in (
                ("linux-firmware", "linux-firmware_1_all.deb"),
                ("intel-microcode", "intel-microcode_1_amd64.deb"),
                (
                    "linux-hwe-6.17",
                    "linux-modules-6.17.0-14-generic_1_amd64.deb",
                ),
                (
                    "linux-hwe-6.17",
                    "linux-modules-extra-6.17.0-14-generic_1_amd64.deb",
                ),
                (
                    "linux-signed-hwe-6.17",
                    "linux-image-6.17.0-14-generic_1_amd64.deb",
                ),
                (
                    "linux-meta-hwe-6.17",
                    "linux-image-generic-hwe-24.04_1_amd64.deb",
                ),
                (
                    "linux-meta-hwe-6.17",
                    "linux-generic-hwe-24.04_1_amd64.deb",
                ),
                (
                    "linux-hwe-6.17",
                    "linux-headers-6.17.0-14-generic_1_amd64.deb",
                ),
            ):
                folder = os.path.join(pool, sub)
                os.makedirs(folder, exist_ok=True)
                open(os.path.join(folder, name), "wb").close()
            names = [os.path.basename(p) for p in kernel_dpkg_debs(iso)]
            self.assertEqual(names[0], "linux-firmware_1_all.deb")
            self.assertIn("linux-modules-6.17.0-14-generic_1_amd64.deb", names)
            self.assertLess(
                names.index("linux-modules-6.17.0-14-generic_1_amd64.deb"),
                names.index("linux-modules-extra-6.17.0-14-generic_1_amd64.deb"),
            )
            self.assertIn("linux-image-6.17.0-14-generic_1_amd64.deb", names)
            self.assertIn("linux-image-generic-hwe-24.04_1_amd64.deb", names)
            self.assertFalse(any("linux-generic-hwe-24.04_" in n for n in names))
            self.assertFalse(any("linux-headers-" in n for n in names))
        finally:
            shutil.rmtree(iso, ignore_errors=True)

    def test_install_kernel_from_iso_uses_dpkg_not_apt(self) -> None:
        iso = tempfile.mkdtemp(prefix="fbl-mate-dpkg-")
        root = tempfile.mkdtemp(prefix="fbl-mate-dpkg-root-")
        try:
            deb_dir = os.path.join(iso, "pool", "main", "l", "linux-signed-hwe")
            os.makedirs(deb_dir)
            open(
                os.path.join(deb_dir, "linux-image-6.17.0-14-generic_1_amd64.deb"),
                "wb",
            ).close()
            os.makedirs(os.path.join(root, "boot"))
            seen: list[list[str]] = []

            def fake_chroot(_root: str, argv: list[str], **_kwargs: object) -> tuple[int, str]:
                seen.append(argv)
                if argv[:4] == ["env", "DEBIAN_FRONTEND=noninteractive", "dpkg", "-i"]:
                    open(
                        os.path.join(root, "boot", "vmlinuz-6.17.0-14-generic"),
                        "wb",
                    ).close()
                    open(
                        os.path.join(root, "boot", "initrd.img-6.17.0-14-generic"),
                        "wb",
                    ).close()
                return 0, ""

            with mock.patch(
                "firstboot.osinstall.casper.chroot_run", side_effect=fake_chroot
            ), mock.patch("firstboot.osinstall.casper.run_checked"), mock.patch(
                "firstboot.osinstall.casper.umount_path"
            ):
                install_kernel_from_iso(root, iso)
            dpkg_calls = [a for a in seen if "dpkg" in a]
            self.assertTrue(dpkg_calls, seen)
            argv = dpkg_calls[0]
            self.assertIn("-i", argv)
            self.assertTrue(any("linux-image-6.17.0-14-generic" in x for x in argv))
            self.assertFalse(any("apt-get" in a for a in seen))
            self.assertFalse(any("grub-efi-amd64-signed" in x for a in seen for x in a))
        finally:
            shutil.rmtree(iso, ignore_errors=True)
            shutil.rmtree(root, ignore_errors=True)

    def test_extract_signed_efi_includes_grub2_common_not_grub_efi_amd64(self) -> None:
        iso = tempfile.mkdtemp(prefix="fbl-mate-xdeb-")
        root = tempfile.mkdtemp(prefix="fbl-mate-xroot-")
        try:
            signed = os.path.join(iso, "pool", "main", "g", "grub2-signed")
            common = os.path.join(iso, "pool", "main", "g", "grub2")
            efi = os.path.join(iso, "pool", "main", "g", "grub2-unsigned")
            os.makedirs(signed)
            os.makedirs(common)
            os.makedirs(efi)
            open(os.path.join(signed, "grub-efi-amd64-signed_1_amd64.deb"), "wb").close()
            open(os.path.join(common, "grub2-common_1_amd64.deb"), "wb").close()
            open(os.path.join(efi, "grub-efi-amd64_1_amd64.deb"), "wb").close()
            open(os.path.join(efi, "grub-efi-amd64-bin_1_amd64.deb"), "wb").close()
            extracted: list[str] = []

            def fake_run(argv: list[str], **_kwargs: object) -> object:
                if argv[:2] == ["dpkg-deb", "-x"]:
                    extracted.append(os.path.basename(argv[2]))
                    os.makedirs(
                        os.path.join(
                            root, "usr", "lib", "grub", "x86_64-efi-signed"
                        ),
                        exist_ok=True,
                    )
                    open(
                        os.path.join(
                            root,
                            "usr",
                            "lib",
                            "grub",
                            "x86_64-efi-signed",
                            "grubx64.efi.signed",
                        ),
                        "wb",
                    ).close()
                    return mock.Mock(returncode=0, stdout="", stderr="")
                return mock.Mock(returncode=1, stdout="", stderr="")

            with mock.patch("firstboot.osinstall.casper.subprocess.run", side_effect=fake_run):
                extract_signed_efi_debs(iso, root)
            self.assertIn("grub-efi-amd64-signed_1_amd64.deb", extracted)
            self.assertIn("grub2-common_1_amd64.deb", extracted)
            self.assertIn("grub-efi-amd64-bin_1_amd64.deb", extracted)
            self.assertNotIn("grub-efi-amd64_1_amd64.deb", extracted)
        finally:
            shutil.rmtree(iso, ignore_errors=True)
            shutil.rmtree(root, ignore_errors=True)

    def test_ensure_grub_efi_modules_prefers_iso_over_host(self) -> None:
        root = tempfile.mkdtemp(prefix="fbl-mate-grubmod-")
        iso = tempfile.mkdtemp(prefix="fbl-mate-grubiso-")
        try:
            iso_mods = os.path.join(iso, "boot", "grub", "x86_64-efi")
            os.makedirs(iso_mods)
            with open(os.path.join(iso_mods, "modinfo.sh"), "w", encoding="utf-8") as fh:
                fh.write("ISO-24.04\n")
            ensure_grub_efi_modules(root, iso_mnt=iso)
            dest = os.path.join(root, "usr", "lib", "grub", "x86_64-efi", "modinfo.sh")
            with open(dest, encoding="utf-8") as fh:
                self.assertEqual(fh.read(), "ISO-24.04\n")
        finally:
            shutil.rmtree(root, ignore_errors=True)
            shutil.rmtree(iso, ignore_errors=True)

    def test_configure_writes_customer_not_live_user(self) -> None:
        root = tempfile.mkdtemp(prefix="fbl-mate-root-")
        efi = tempfile.mkdtemp(prefix="fbl-mate-efi-")
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
            self.assertIn("user-session=mate", lightdm)
            drop = os.path.join(root, "etc", "lightdm", "lightdm.conf.d")
            self.assertFalse(os.path.isfile(os.path.join(drop, "90-casper.conf")))
            mate_drop = read("etc/lightdm/lightdm.conf.d/50-ubuntu-mate.conf")
            self.assertNotIn("autologin-user", mate_drop)
            self.assertIn("greeter-session=slick-greeter", mate_drop)
            self.assertFalse(os.path.isdir(os.path.join(root, "home", "ubuntu")))
            seed = read("var/lib/snapd/seed/seed.yaml")
            self.assertNotIn("ubuntu-desktop-bootstrap", seed)
            self.assertNotIn("subiquity", seed)
            leftovers = casper_leftovers(root)
            self.assertNotIn("Live installer snap is still present.", leftovers)
            fake_esp(efi)
            fails = DRIVER.health_check(root, efi, ident, disk_for(root, efi))
            self.assertEqual(fails, [])
        finally:
            shutil.rmtree(root, ignore_errors=True)
            shutil.rmtree(efi, ignore_errors=True)

    def test_health_check_rejects_missing_lightdm(self) -> None:
        root = tempfile.mkdtemp(prefix="fbl-mate-dm-")
        efi = tempfile.mkdtemp(prefix="fbl-mate-dm-efi-")
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
