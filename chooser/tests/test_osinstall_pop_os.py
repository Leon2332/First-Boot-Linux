#!/usr/bin/env python3
"""Pop!_OS shop-pack driver."""

from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
CHOOSER_DIR = os.path.dirname(HERE)
ROOT = os.path.dirname(CHOOSER_DIR)
if CHOOSER_DIR not in sys.path:
    sys.path.insert(0, CHOOSER_DIR)

from firstboot.disk import Disk, Partition  # noqa: E402
from firstboot.osinstall.common import (  # noqa: E402
    OsInstallError,
    OsInstallPlan,
    find_iso_efi,
    install_vendor_shim,
    secure_boot_enabled,
)

POP_DRIVER = os.path.join(
    ROOT, "examples", "retailer-distros", "pop-os", "driver.py"
)


def load_pop():
    spec = importlib.util.spec_from_file_location("pop_os_pack", POP_DRIVER)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def fake_iso(root: str, *, nvidia: bool = False) -> str:
    name = (
        "casper_pop-os_24.04_amd64_nvidia_debug_654"
        if nvidia
        else "casper_pop-os_24.04_amd64_generic_debug_654"
    )
    casper = os.path.join(root, name)
    os.makedirs(casper)
    open(os.path.join(casper, "vmlinuz.efi"), "wb").close()
    open(os.path.join(casper, "initrd.gz"), "wb").close()
    os.symlink(name, os.path.join(root, "casper"))
    efi = os.path.join(root, "efi", "boot")
    os.makedirs(efi)
    with open(os.path.join(efi, "bootx64.efi"), "wb") as fh:
        fh.write(b"shim")
    with open(os.path.join(efi, "grubx64.efi"), "wb") as fh:
        fh.write(b"grub")
    return casper


class SecureBootTests(unittest.TestCase):
    def test_env_override(self) -> None:
        with mock.patch.dict(os.environ, {"FIRSTBOOT_SECURE_BOOT": "1"}):
            self.assertIs(secure_boot_enabled(), True)
        with mock.patch.dict(os.environ, {"FIRSTBOOT_SECURE_BOOT": "0"}):
            self.assertIs(secure_boot_enabled(), False)


class PopDriverTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mod = load_pop()
        self.drv = self.mod.PopOS()

    def test_casper_star_not_casper_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            casper = fake_iso(tmp)
            with mock.patch.dict(os.environ, {"FIRSTBOOT_SECURE_BOOT": "0"}):
                vmlinuz, initrd = self.drv.boot_files(tmp)
            self.assertEqual(vmlinuz, os.path.join(casper, "vmlinuz.efi"))
            self.assertEqual(initrd, os.path.join(casper, "initrd.gz"))
            self.assertEqual(
                self.drv._casper_name, "casper_pop-os_24.04_amd64_generic_debug_654"
            )
            args = self.drv.kernel_args(
                "/images/pop-os_24.04_amd64_generic_27.iso", toram=True
            )
            self.assertIn(
                "live-media-path=/casper_pop-os_24.04_amd64_generic_debug_654",
                args,
            )
            self.assertIn("toram", args)
            self.assertIn("hostname=pop-os", args)
            self.assertNotIn("modules_load=nvidia", args)

    def test_nvidia_kernel_args(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fake_iso(tmp, nvidia=True)
            with mock.patch.dict(os.environ, {"FIRSTBOOT_SECURE_BOOT": "0"}):
                self.drv.boot_files(tmp)
            args = self.drv.kernel_args(
                "/images/pop-os_24.04_amd64_nvidia_27.iso",
                toram=False,
                iso_path="/tmp/pop-os_24.04_amd64_nvidia_27.iso",
            )
            self.assertIn(
                "live-media-path=/casper_pop-os_24.04_amd64_nvidia_debug_654",
                args,
            )
            self.assertIn("modules_load=nvidia", args)
            self.assertIn("nvidia-drm.modeset=1", args)
            self.assertNotIn("toram", args)

    def test_secure_boot_refuses_before_grub(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fake_iso(tmp)
            with mock.patch.dict(os.environ, {"FIRSTBOOT_SECURE_BOOT": "1"}):
                with self.assertRaises(OsInstallError) as ctx:
                    self.drv.boot_files(tmp)
            self.assertIn("Secure Boot", str(ctx.exception))
            self.assertIn("not signed", str(ctx.exception).lower())


class VendorShimTests(unittest.TestCase):
    def test_finds_lowercase_efi_boot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fake_iso(tmp)
            shim, grub, mm = find_iso_efi(tmp)
            self.assertTrue(shim.endswith("bootx64.efi"))
            self.assertTrue(grub.endswith("grubx64.efi"))
            self.assertEqual(mm, "")

    def test_copies_shim_to_esp(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            iso = os.path.join(tmp, "iso")
            esp = os.path.join(tmp, "esp")
            os.makedirs(iso)
            fake_iso(iso)
            os.makedirs(esp)
            live = Disk(
                path="/dev/sda",
                size=1,
                parts=(
                    Partition(
                        path="/dev/sda1",
                        size=1,
                        label="FBL-ESP",
                        mountpoints=(esp,),
                    ),
                ),
            )
            plan = OsInstallPlan(available=True, live=live, target=live)
            with mock.patch(
                "firstboot.osinstall.common.shutil.which", return_value=None
            ):
                ok = install_vendor_shim(
                    iso,
                    plan,
                    "sys-uuid",
                    "Pop!_OS",
                    "boot=casper",
                    bootnext_label="Install Pop!_OS",
                )
            self.assertTrue(ok)
            dest = os.path.join(esp, "EFI", "osinstall")
            with open(os.path.join(dest, "shimx64.efi"), "rb") as fh:
                self.assertEqual(fh.read(), b"shim")
            with open(os.path.join(dest, "grubx64.efi"), "rb") as fh:
                self.assertEqual(fh.read(), b"grub")
            with open(os.path.join(dest, "grub.cfg"), encoding="utf-8") as fh:
                cfg = fh.read()
            self.assertIn("linux /boot/osinstall/vmlinuz boot=casper", cfg)
            self.assertIn("search --no-floppy --set=root --fs-uuid sys-uuid", cfg)


if __name__ == "__main__":
    unittest.main()
