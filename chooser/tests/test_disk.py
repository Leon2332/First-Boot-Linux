#!/usr/bin/env python3
"""Shop-install plan and helper protocol — no root, no GTK."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
CHOOSER_DIR = os.path.dirname(HERE)
if CHOOSER_DIR not in sys.path:
    sys.path.insert(0, CHOOSER_DIR)

from firstboot.disk import (  # noqa: E402
    Disk,
    Partition,
    bytes_to_mib,
    disk_for_device,
    find_source_disk,
    format_size,
    live_media_from_cmdline,
    map_range,
    parent_disk_name,
    parse_helper_line,
    parse_lsblk,
    parse_mountinfo,
    part_path,
    payload_fstab_spec,
    plan_install,
    rsync_percent,
    skip_name,
)
from unittest import mock  # noqa: E402

from firstboot.install import (  # noqa: E402
    ESP_GRUB,
    SYS_GRUB,
    InstallError,
    copy_tree,
    efi_ids_for_label,
    efi_ids_for_unshimmed_loaders,
    rewrite_grub,
    unmount_error,
)


def disk(
    path: str,
    size: int,
    *,
    usb: bool = False,
    removable: bool = False,
    model: str = "",
    parts: list[Partition] | None = None,
    tran: str = "",
) -> Disk:
    return Disk(
        path=path,
        size=size,
        model=model,
        removable=removable,
        usb=usb,
        transport=tran or ("usb" if usb else ""),
        parts=tuple(parts or ()),
    )


def fbl_parts(dev: str, *, sys_mp: str = "/cdrom", data_mp: str = "/run/payload") -> list[Partition]:
    p = "" if os.path.basename(dev)[-1].isdigit() is False else "p"
    # part_path already handles this; build names from part_path
    return [
        Partition(part_path(dev, 1), 512 * 1024 * 1024, "FBL-ESP", "FBL-ESP", "vfat"),
        Partition(part_path(dev, 2), 2 * 1024 * 1024 * 1024, "FBL-SYS", "FBL-SYS", "ext4", (sys_mp,)),
        Partition(part_path(dev, 3), 28 * 1024 * 1024 * 1024, "FBL-DATA", "FBL-DATA", "ext4", (data_mp,)),
    ]


class NameTests(unittest.TestCase):
    def test_parent_nvme(self) -> None:
        self.assertEqual(parent_disk_name("/dev/nvme0n1p2"), "nvme0n1")

    def test_parent_sda(self) -> None:
        self.assertEqual(parent_disk_name("/dev/sda2"), "sda")

    def test_parent_mmc(self) -> None:
        self.assertEqual(parent_disk_name("/dev/mmcblk0p1"), "mmcblk0")

    def test_parent_vda(self) -> None:
        self.assertEqual(parent_disk_name("/dev/vda3"), "vda")

    def test_part_path(self) -> None:
        self.assertEqual(part_path("/dev/sda", 2), "/dev/sda2")
        self.assertEqual(part_path("/dev/nvme0n1", 3), "/dev/nvme0n1p3")
        self.assertEqual(part_path("/dev/mmcblk0", 1), "/dev/mmcblk0p1")

    def test_skip_virtual(self) -> None:
        self.assertTrue(skip_name("loop0"))
        self.assertTrue(skip_name("zram0"))
        self.assertTrue(skip_name("sr0"))
        self.assertFalse(skip_name("sda"))
        self.assertFalse(skip_name("nvme0n1"))


class ParseTests(unittest.TestCase):
    def test_mountinfo(self) -> None:
        text = (
            "36 24 8:18 / /cdrom rw - ext4 /dev/sdb2 rw\n"
            "40 24 8:19 / /run/payload rw - ext4 /dev/sdb3 rw\n"
        )
        mounts = parse_mountinfo(text)
        self.assertEqual(mounts["/cdrom"], "/dev/sdb2")
        self.assertEqual(mounts["/run/payload"], "/dev/sdb3")

    def test_lsblk_skips_loop_and_marks_usb(self) -> None:
        data = {
            "blockdevices": [
                {
                    "name": "/dev/loop0",
                    "type": "disk",
                    "size": "4096",
                },
                {
                    "name": "/dev/sdb",
                    "type": "disk",
                    "size": "32000000000",
                    "rm": True,
                    "tran": "usb",
                    "model": "SanDisk",
                    "children": [
                        {
                            "name": "/dev/sdb2",
                            "type": "part",
                            "size": "2147483648",
                            "label": "FBL-SYS",
                            "partlabel": "FBL-SYS",
                            "fstype": "ext4",
                            "mountpoints": ["/cdrom"],
                        }
                    ],
                },
                {
                    "name": "/dev/nvme0n1",
                    "type": "disk",
                    "size": "512110190592",
                    "rm": False,
                    "tran": "nvme",
                    "model": "Samsung SSD",
                },
            ]
        }
        disks = parse_lsblk(data)
        names = [d.name for d in disks]
        self.assertEqual(names, ["sdb", "nvme0n1"])
        usb = disks[0]
        self.assertTrue(usb.usb)
        self.assertTrue(usb.removable)
        self.assertEqual(usb.parts[0].label, "FBL-SYS")
        self.assertIn("/cdrom", usb.parts[0].mountpoints)


class PlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = os.environ.pop("FIRSTBOOT_SHOP_INSTALL", None)

    def tearDown(self) -> None:
        if self.env is None:
            os.environ.pop("FIRSTBOOT_SHOP_INSTALL", None)
        else:
            os.environ["FIRSTBOOT_SHOP_INSTALL"] = self.env

    def test_usb_plus_nvme(self) -> None:
        usb = disk("/dev/sdb", 32 * 1024**3, usb=True, removable=True, parts=fbl_parts("/dev/sdb"))
        nvme = disk("/dev/nvme0n1", 512 * 1024**3, model="Samsung")
        mounts = {"/cdrom": "/dev/sdb2", "/run/payload": "/dev/sdb3"}
        plan = plan_install([usb, nvme], mounts, payload_used=8 * 1024**3)
        self.assertTrue(plan.available, plan.reason)
        self.assertEqual(plan.source.path, "/dev/sdb")
        self.assertEqual(plan.target.path, "/dev/nvme0n1")
        self.assertGreater(plan.need_bytes, 8 * 1024**3)

    def test_usb_preferred_when_cdrom_is_internal(self) -> None:
        usb = disk(
            "/dev/sdb",
            32 * 1024**3,
            usb=True,
            removable=True,
            parts=fbl_parts("/dev/sdb", sys_mp="", data_mp=""),
        )
        sda = disk(
            "/dev/sda",
            512 * 1024**3,
            parts=fbl_parts("/dev/sda"),
        )
        mounts = {"/cdrom": "/dev/sda2", "/run/payload": "/dev/sda3"}
        plan = plan_install([sda, usb], mounts, payload_used=8 * 1024**3)
        self.assertTrue(plan.available, plan.reason)
        self.assertEqual(plan.source.path, "/dev/sdb")
        self.assertEqual(plan.target.path, "/dev/sda")

    def test_hidden_when_booted_from_internal(self) -> None:
        nvme = disk(
            "/dev/nvme0n1",
            512 * 1024**3,
            parts=fbl_parts("/dev/nvme0n1"),
        )
        usb = disk("/dev/sdb", 32 * 1024**3, usb=True, removable=True)
        mounts = {"/cdrom": "/dev/nvme0n1p2", "/run/payload": "/dev/nvme0n1p3"}
        plan = plan_install([nvme, usb], mounts, payload_used=8 * 1024**3)
        self.assertFalse(plan.available)
        self.assertIn("USB", plan.reason)

    def test_hidden_when_only_one_disk(self) -> None:
        usb = disk("/dev/sdb", 32 * 1024**3, usb=True, removable=True, parts=fbl_parts("/dev/sdb"))
        mounts = {"/cdrom": "/dev/sdb2"}
        plan = plan_install([usb], mounts, payload_used=1024)
        self.assertFalse(plan.available)
        self.assertIn("No internal disk", plan.reason)

    def test_too_small(self) -> None:
        usb = disk("/dev/sdb", 32 * 1024**3, usb=True, removable=True, parts=fbl_parts("/dev/sdb"))
        tiny = disk("/dev/sda", 4 * 1024**3)
        mounts = {"/cdrom": "/dev/sdb2", "/run/payload": "/dev/sdb3"}
        plan = plan_install([usb, tiny], mounts, payload_used=8 * 1024**3)
        self.assertFalse(plan.available)
        self.assertIn("too small", plan.reason)

    def test_host_session_has_no_live_mounts(self) -> None:
        nvme = disk("/dev/nvme0n1", 512 * 1024**3)
        plan = plan_install([nvme], {})
        self.assertFalse(plan.available)
        self.assertIn("USB", plan.reason)

    def test_qemu_override(self) -> None:
        src = disk("/dev/vda", 4 * 1024**3, parts=fbl_parts("/dev/vda"))
        dst = disk("/dev/vdb", 16 * 1024**3)
        mounts = {"/cdrom": "/dev/vda2", "/run/payload": "/dev/vda3"}
        os.environ["FIRSTBOOT_SHOP_INSTALL"] = "1"
        plan = plan_install([src, dst], mounts, payload_used=10 * 1024**2)
        self.assertTrue(plan.available, plan.reason)
        self.assertEqual(plan.target.path, "/dev/vdb")

    def test_picks_largest_internal(self) -> None:
        usb = disk("/dev/sdb", 32 * 1024**3, usb=True, removable=True, parts=fbl_parts("/dev/sdb"))
        small = disk("/dev/sda", 128 * 1024**3)
        big = disk("/dev/nvme0n1", 1024 * 1024**3)
        mounts = {"/cdrom": "/dev/sdb2", "/run/payload": "/dev/sdb3"}
        plan = plan_install([usb, small, big], mounts, payload_used=1024)
        self.assertTrue(plan.available)
        self.assertEqual(plan.target.path, "/dev/nvme0n1")

    def test_source_from_payload_mount(self) -> None:
        usb = disk("/dev/sdb", 32 * 1024**3, usb=True, parts=fbl_parts("/dev/sdb"))
        nvme = disk("/dev/nvme0n1", 256 * 1024**3)
        mounts = {"/run/payload": "/dev/sdb3"}
        self.assertEqual(find_source_disk([usb, nvme], mounts).path, "/dev/sdb")

    def test_reinstall_when_payload_is_on_internal(self) -> None:
        usb = disk(
            "/dev/sdb",
            32 * 1024**3,
            usb=True,
            removable=True,
            parts=fbl_parts("/dev/sdb", data_mp=""),
        )
        sda = disk(
            "/dev/sda",
            512 * 1024**3,
            parts=fbl_parts("/dev/sda", sys_mp="", data_mp="/run/payload"),
        )
        mounts = {"/cdrom": "/dev/sdb2", "/run/payload": "/dev/sda3"}
        plan = plan_install([usb, sda], mounts, payload_used=8 * 1024**3)
        self.assertTrue(plan.available, plan.reason)
        self.assertEqual(plan.source.path, "/dev/sdb")
        self.assertEqual(plan.target.path, "/dev/sda")
        self.assertIsNone(unmount_error("/run/payload", plan.target.path))
        self.assertIsNotNone(unmount_error("/cdrom", plan.target.path))
        self.assertIsNotNone(unmount_error("/", plan.target.path))

    def test_disk_for_device(self) -> None:
        nvme = disk("/dev/nvme0n1", 100)
        self.assertIs(disk_for_device([nvme], "/dev/nvme0n1p3"), nvme)

    def test_payload_fstab_prefers_same_disk_uuid(self) -> None:
        spec = payload_fstab_spec(
            "/dev/sdb2",
            [("/dev/sda3", "old-uuid"), ("/dev/sdb3", "usb-uuid")],
        )
        self.assertEqual(spec, "UUID=usb-uuid")

    def test_payload_fstab_falls_back_to_label(self) -> None:
        self.assertEqual(payload_fstab_spec(None, [("/dev/sda3", "x")]), "LABEL=FBL-DATA")
        self.assertEqual(payload_fstab_spec("/dev/sdb2", []), "LABEL=FBL-DATA")

    def test_live_media_from_cmdline(self) -> None:
        cmd = (
            "BOOT_IMAGE=/casper/vmlinuz boot=casper "
            "live-media=/dev/disk/by-uuid/c4b0c66c-a7e7-4917-9c4b-e96aa866ce2f "
            "nopersistent"
        )
        self.assertEqual(
            live_media_from_cmdline(cmd),
            "/dev/disk/by-uuid/c4b0c66c-a7e7-4917-9c4b-e96aa866ce2f",
        )


class UnmountPolicyTests(unittest.TestCase):
    def test_payload_on_target_is_cleared(self) -> None:
        self.assertIsNone(unmount_error("/run/payload", "/dev/sda"))

    def test_live_medium_stays(self) -> None:
        self.assertIn("refusing", unmount_error("/cdrom", "/dev/sda") or "")
        self.assertIn("refusing", unmount_error("/", "/dev/sda") or "")
        self.assertIn("refusing", unmount_error("/run/live/medium", "/dev/sdb") or "")


class EfiNvramTests(unittest.TestCase):
    SAMPLE = """\
BootCurrent: 0001
Timeout: 1 seconds
BootOrder: 0001,0002,0003,0006,0007
Boot0001* First Boot Linux\tHD(1,GPT,aaa,0x800,0x100000)/File(\\EFI\\BOOT\\BOOTX64.EFI)
Boot0002* First Boot Linux\tHD(1,GPT,bbb,0x800,0x100000)/File(\\EFI\\BOOT\\BOOTX64.EFI)
Boot0003* First Boot Linux
Boot0005* Fedora\tHD(1,GPT,ccc,0x800,0x100000)/File(\\EFI\\fedora\\shimx64.efi)
Boot0006* Ubuntu\tHD(1,GPT,ddd,0x800,0x100000)/File(\\EFI\\ubuntu\\shimx64.efi)
Boot0007* Windows Boot Manager\tHD(1,GPT,eee,0x800,0x100000)/File(\\EFI\\Microsoft\\Boot\\bootmgfw.efi)
"""

    def test_collects_duplicate_firstboot(self) -> None:
        ids = efi_ids_for_label(self.SAMPLE, "First Boot Linux")
        self.assertEqual(ids, ["0001", "0002", "0003"])

    def test_other_labels(self) -> None:
        self.assertEqual(efi_ids_for_label(self.SAMPLE, "Ubuntu"), ["0006"])
        self.assertEqual(efi_ids_for_label(self.SAMPLE, "Fedora"), ["0005"])
        self.assertEqual(efi_ids_for_label(self.SAMPLE, "Windows Boot Manager"), ["0007"])
        self.assertEqual(efi_ids_for_label(self.SAMPLE, "missing"), [])

    def test_unshimmed_loaders_not_shim(self) -> None:
        text = (
            "Boot0000* Linux Mint\tHD(1,GPT,aaa,0x800,0x100000)/"
            "File(\\EFI\\ubuntu\\shimx64.efi)\n"
            "Boot0003* ubuntu\tHD(1,GPT,aaa,0x800,0x100000)/"
            "File(\\EFI\\ubuntu\\grubx64.efi)RC\n"
            "Boot0004* ubuntu\tHD(1,GPT,aaa,0x800,0x100000)/"
            "File(\\EFI\\ubuntu\\mmx64.efi)RC\n"
            "Boot0014* NVMe:\tVenMsg(bc7838d2-0f82-4d60-8316-c068ee79d25b,001c)\n"
        )
        self.assertEqual(efi_ids_for_unshimmed_loaders(text), ["0003", "0004"])
        self.assertEqual(efi_ids_for_unshimmed_loaders(self.SAMPLE), [])


class ProtocolTests(unittest.TestCase):
    def test_helper_lines(self) -> None:
        self.assertEqual(parse_helper_line("STEP Copying boot files…").kind, "step")
        self.assertEqual(parse_helper_line("STEP Copying boot files…").text, "Copying boot files…")
        self.assertEqual(parse_helper_line("PROGRESS 34").progress, 34)
        self.assertEqual(parse_helper_line("DONE").kind, "done")
        self.assertEqual(parse_helper_line("ERROR disk too small").kind, "error")
        self.assertEqual(parse_helper_line("ERROR disk too small").text, "disk too small")
        self.assertIsNone(parse_helper_line(""))

    def test_rsync_percent(self) -> None:
        line = "  1,234,567  45%  12.34MB/s    0:00:01"
        self.assertEqual(rsync_percent(line), 45)
        self.assertIsNone(rsync_percent("sending incremental file list"))

    def test_copy_tree_xattr_code_23_is_ok(self) -> None:
        proc = mock.Mock()
        proc.stderr = iter(
            [
                "rsync: rsync_xal_set: lsetxattr(\"/dst/usr/bin/plasmalogin\",\"security.selinux\") failed: Operation not supported (95)\n",
                "rsync error: some files/attr were not transferred (see previous errors) (code 23) at main.c(1356) [sender=3.4.1]\n",
            ]
        )
        proc.wait.return_value = 23
        with mock.patch("firstboot.install.subprocess.Popen", return_value=proc):
            copy_tree("/src", "/dst", xattrs=True)
        proc.wait.return_value = 12
        with mock.patch("firstboot.install.subprocess.Popen", return_value=proc):
            with self.assertRaises(InstallError):
                copy_tree("/src", "/dst", xattrs=True)

    def test_map_range(self) -> None:
        self.assertEqual(map_range(0, 59, 96), 59)
        self.assertEqual(map_range(100, 59, 96), 96)
        self.assertEqual(map_range(50, 0, 100), 50)

    def test_format_and_mib(self) -> None:
        self.assertEqual(bytes_to_mib(512 * 1024 * 1024), 512)
        self.assertIn("GB", format_size(512 * 1024**3))


class GrubRewriteTests(unittest.TestCase):
    def test_writes_uuid_stubs(self) -> None:
        uuid = "11111111-2222-3333-4444-555555555555"
        with tempfile.TemporaryDirectory() as tmp:
            esp = os.path.join(tmp, "esp")
            sys = os.path.join(tmp, "sys")
            rewrite_grub(esp, sys, uuid)
            def _read(rel: str) -> str:
                with open(rel, encoding="utf-8") as fh:
                    return fh.read()

            boot = _read(os.path.join(esp, "EFI/BOOT/grub.cfg"))
            first = _read(os.path.join(esp, "EFI/firstboot/grub.cfg"))
            ubuntu = _read(os.path.join(esp, "EFI/ubuntu/grub.cfg"))
            live = _read(os.path.join(sys, "boot/grub/grub.cfg"))
            self.assertEqual(boot, ESP_GRUB.format(uuid=uuid))
            self.assertEqual(first, boot)
            self.assertEqual(ubuntu, boot)
            self.assertEqual(live, SYS_GRUB.format(uuid=uuid))
            self.assertIn(f"--fs-uuid {uuid}", boot)
            self.assertIn("--label FBL-SYS", boot)
            self.assertIn(f"live-media=/dev/disk/by-uuid/{uuid}", live)
            self.assertIn("--label FBL-SYS", live)


if __name__ == "__main__":
    unittest.main()
