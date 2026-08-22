#!/usr/bin/env python3
"""System details probe — no GTK required."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
CHOOSER_DIR = os.path.dirname(HERE)
if CHOOSER_DIR not in sys.path:
    sys.path.insert(0, CHOOSER_DIR)

from firstboot.disk import Disk, Partition  # noqa: E402
from firstboot.sysinfo import (  # noqa: E402
    Display,
    Field,
    SysInfo,
    apply_monitor_refresh,
    collect,
    disk_fields,
    format_gib,
    format_kernel,
    gpu_label,
    parse_hex,
    parse_mode,
    parse_os_release,
    parse_pci_ids,
    paths_from_root,
    primary_part,
    read_cpu,
    read_displays,
    read_graphics,
    read_memory,
    read_model,
    read_os_name,
    tidy_cpu,
    windowing_system,
)

PCI_IDS = """\
# pci.ids fixture
1002  Advanced Micro Devices, Inc. [AMD/ATI]
	1638  Cezanne [Radeon Vega Series / Radeon Vega Mobile Series]
	747e  Navi 32 [Radeon RX 7700 XT / 7800 XT]
8086  Intel Corporation
	5917  UHD Graphics 620
1af4  Red Hat, Inc.
	1050  Virtio GPU
"""


def write(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def disk(
    path: str,
    size: int,
    *,
    tran: str = "",
    parts: list[Partition] | None = None,
) -> Disk:
    return Disk(
        path=path,
        size=size,
        transport=tran,
        parts=tuple(parts or ()),
    )


class FormatTests(unittest.TestCase):
    def test_gib(self) -> None:
        self.assertEqual(format_gib(16 * 1024**3), "16.0 GiB")
        self.assertEqual(format_gib(500107862016), "465.8 GiB")

    def test_kernel(self) -> None:
        self.assertEqual(format_kernel("6.17.0-generic"), "Linux 6.17.0-generic")
        self.assertEqual(format_kernel("Linux 6.8"), "Linux 6.8")
        self.assertIsNone(format_kernel(None))

    def test_tidy_cpu(self) -> None:
        self.assertEqual(
            tidy_cpu("Intel(R) Core(TM) i5-8250U CPU @ 1.60GHz"),
            "Intel Core i5-8250U",
        )
        self.assertEqual(
            tidy_cpu("AMD Ryzen 7 5700G with Radeon Graphics"),
            "AMD Ryzen 7 5700G with Radeon Graphics",
        )

    def test_windowing(self) -> None:
        self.assertEqual(windowing_system({"WAYLAND_DISPLAY": "wayland-0"}), "Wayland")
        self.assertEqual(windowing_system({"DISPLAY": ":0"}), "X11")
        self.assertEqual(
            windowing_system({"DISPLAY": ":0", "WAYLAND_DISPLAY": "wayland-0"}),
            "Wayland",
        )
        self.assertEqual(windowing_system({}), "Wayland")

    def test_parse_hex(self) -> None:
        self.assertEqual(parse_hex("0x1002"), 0x1002)
        self.assertEqual(parse_hex("747e"), 0x747E)
        self.assertIsNone(parse_hex("nope"))

    def test_parse_mode(self) -> None:
        self.assertEqual(parse_mode("1920x1080"), (1920, 1080))
        self.assertEqual(parse_mode("1366x768i"), (1366, 768))
        self.assertIsNone(parse_mode(""))


class OsReleaseTests(unittest.TestCase):
    def test_pretty(self) -> None:
        text = 'PRETTY_NAME="First Boot Linux 0.6.18"\nNAME="First Boot Linux"\n'
        self.assertEqual(parse_os_release(text)["PRETTY_NAME"], "First Boot Linux 0.6.18")
        self.assertEqual(read_os_name(text), "First Boot Linux 0.6.18")

    def test_fallback(self) -> None:
        self.assertEqual(read_os_name('NAME="Foo"\nVERSION_ID="1"\n'), "Foo 1")


class MemoryCpuTests(unittest.TestCase):
    def test_memtotal(self) -> None:
        self.assertEqual(read_memory("MemTotal:       11438020 kB\n"), "10.9 GiB")
        self.assertIsNone(read_memory(""))

    def test_cpu_model(self) -> None:
        text = "processor\t: 0\nmodel name\t: Intel(R) Core(TM) i5-8250U CPU @ 1.60GHz\n"
        self.assertEqual(read_cpu(text), "Intel Core i5-8250U")

    def test_cpu_skips_processor_index(self) -> None:
        self.assertIsNone(read_cpu("processor\t: 0\n"))


class ModelTests(unittest.TestCase):
    def test_msi_board(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            write(os.path.join(tmp, "sys_vendor"), "Micro-Star International Co., Ltd.\n")
            write(os.path.join(tmp, "product_name"), "MS-7D14\n")
            write(os.path.join(tmp, "product_version"), "1.0\n")
            write(os.path.join(tmp, "product_family"), "To be filled by O.E.M.\n")
            self.assertEqual(
                read_model(tmp),
                "Micro-Star International Co., Ltd. MS-7D14",
            )

    def test_lenovo_marketing_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            write(os.path.join(tmp, "sys_vendor"), "LENOVO\n")
            write(os.path.join(tmp, "product_name"), "81HM\n")
            write(os.path.join(tmp, "product_version"), "Lenovo V130-15IKB\n")
            self.assertEqual(read_model(tmp), "Lenovo V130-15IKB")

    def test_qemu(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            write(os.path.join(tmp, "sys_vendor"), "QEMU\n")
            write(os.path.join(tmp, "product_name"), "Standard PC (Q35 + ICH9, 2009)\n")
            write(os.path.join(tmp, "product_version"), "pc-q35-8.2\n")
            self.assertEqual(read_model(tmp), "QEMU Standard PC (Q35 + ICH9, 2009)")


class PciGpuTests(unittest.TestCase):
    def test_bracket_marketing_name(self) -> None:
        db = parse_pci_ids(PCI_IDS)
        self.assertEqual(
            gpu_label(0x1002, 0x747E, db),
            "AMD Radeon RX 7700 XT / 7800 XT",
        )
        self.assertEqual(gpu_label(0x8086, 0x5917, db), "Intel UHD Graphics 620")
        self.assertEqual(gpu_label(0x1AF4, 0x1050, db), "Virtio GPU")

    def test_missing_ids(self) -> None:
        self.assertEqual(gpu_label(0x1002, 0x1111, None), "AMD Device 1111")
        self.assertEqual(gpu_label(0xABCD, 0x1, None), "PCI abcd:0001")

    def test_graphics_from_drm(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            write(os.path.join(tmp, "pci.ids"), PCI_IDS)
            card0 = os.path.join(tmp, "card0", "device")
            card1 = os.path.join(tmp, "card1", "device")
            os.makedirs(os.path.join(tmp, "card0-eDP-1"))
            write(os.path.join(card0, "vendor"), "0x8086\n")
            write(os.path.join(card0, "device"), "0x5917\n")
            write(os.path.join(card1, "vendor"), "0x8086\n")
            write(os.path.join(card1, "device"), "0x5917\n")
            db = parse_pci_ids(PCI_IDS)
            names = read_graphics(tmp, db)
            self.assertEqual(names, ("Intel UHD Graphics 620",))


class DisplayTests(unittest.TestCase):
    def test_connected_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            edp = os.path.join(tmp, "card0-eDP-1")
            hdmi = os.path.join(tmp, "card0-HDMI-A-1")
            wb = os.path.join(tmp, "card0-Writeback-1")
            os.makedirs(os.path.join(tmp, "card0"))
            write(os.path.join(edp, "status"), "connected\n")
            write(os.path.join(edp, "modes"), "1366x768\n1024x768\n")
            write(os.path.join(hdmi, "status"), "disconnected\n")
            write(os.path.join(hdmi, "modes"), "1920x1080\n")
            write(os.path.join(wb, "status"), "unknown\n")
            write(os.path.join(wb, "modes"), "1920x1080\n")
            got = read_displays(tmp)
            self.assertEqual(got, (Display(1366, 768),))

    def test_format_and_refresh(self) -> None:
        self.assertEqual(Display(1920, 1080).format(), "1920\u00d71080")
        self.assertEqual(Display(1920, 1080, 60).format(), "1920\u00d71080 @ 60 Hz")
        info = SysInfo(displays=(Display(1920, 1080),))
        out = apply_monitor_refresh(info, [(1920, 1080, 100)])
        self.assertEqual(out.displays[0].refresh_hz, 100)


class DiskFieldTests(unittest.TestCase):
    def test_root_and_unmounted(self) -> None:
        root = disk(
            "/dev/nvme0n1",
            500107862016,
            tran="nvme",
            parts=[
                Partition("/dev/nvme0n1p1", 512 * 1024 * 1024, fstype="vfat"),
                Partition(
                    "/dev/nvme0n1p2",
                    400 * 1024**3,
                    fstype="ext4",
                    mountpoints=("/",),
                ),
            ],
        )
        extra = disk("/dev/sda", 1000204886016, tran="sata")
        extra2 = disk("/dev/sdb", 1000204886016, tran="sata")
        rows = disk_fields([root, extra, extra2])
        self.assertEqual(rows[0], Field("Disk (/)", "NVMe - 465.8 GiB (ext4)"))
        self.assertEqual(rows[1].label, "Disk")
        self.assertEqual(rows[1].value, "SATA - 931.5 GiB")
        self.assertEqual(rows[2].label, "Disk (sdb)")

    def test_payload_mount(self) -> None:
        d = disk(
            "/dev/sda",
            929 * 1024**3,
            tran="sata",
            parts=[
                Partition(
                    "/dev/sda3",
                    900 * 1024**3,
                    label="FBL-DATA",
                    fstype="ext4",
                    mountpoints=("/run/payload",),
                )
            ],
        )
        self.assertEqual(primary_part(d).label, "FBL-DATA")
        rows = disk_fields([d])
        self.assertEqual(rows[0].label, "Disk (/run/payload)")
        self.assertIn("(ext4)", rows[0].value)


class CollectTests(unittest.TestCase):
    def test_fixture_tree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            write(os.path.join(tmp, "sys/class/dmi/id/sys_vendor"), "LENOVO\n")
            write(os.path.join(tmp, "sys/class/dmi/id/product_name"), "81HM\n")
            write(
                os.path.join(tmp, "sys/class/dmi/id/product_version"),
                "Lenovo V130-15IKB\n",
            )
            write(os.path.join(tmp, "sys/class/dmi/id/bios_version"), "1.0\n")
            write(os.path.join(tmp, "proc/meminfo"), "MemTotal:       11438020 kB\n")
            write(
                os.path.join(tmp, "proc/cpuinfo"),
                "model name\t: Intel(R) Core(TM) i5-8250U CPU @ 1.60GHz\n",
            )
            write(
                os.path.join(tmp, "etc/os-release"),
                'PRETTY_NAME="First Boot Linux 0.6.18"\n',
            )
            write(os.path.join(tmp, "pci.ids"), PCI_IDS)
            card = os.path.join(tmp, "sys/class/drm/card0/device")
            write(os.path.join(card, "vendor"), "0x8086\n")
            write(os.path.join(card, "device"), "0x5917\n")
            conn = os.path.join(tmp, "sys/class/drm/card0-eDP-1")
            write(os.path.join(conn, "status"), "connected\n")
            write(os.path.join(conn, "modes"), "1366x768\n")
            disks = [
                disk(
                    "/dev/sda",
                    1024**4,
                    tran="sata",
                    parts=[
                        Partition(
                            "/dev/sda2",
                            900 * 1024**3,
                            fstype="ext4",
                            mountpoints=("/",),
                        )
                    ],
                )
            ]
            info = collect(
                paths=paths_from_root(tmp),
                disks=disks,
                machine="x86_64",
                kernel="6.17.0-generic",
                env={"WAYLAND_DISPLAY": "wayland-1"},
            )
            self.assertEqual(info.model, "Lenovo V130-15IKB")
            self.assertEqual(info.processor, "Intel Core i5-8250U")
            self.assertEqual(info.graphics, ("Intel UHD Graphics 620",))
            self.assertEqual(info.displays, (Display(1366, 768),))
            self.assertEqual(info.os, "First Boot Linux 0.6.18")
            self.assertEqual(info.os_type, "x86_64")
            self.assertEqual(info.windowing, "Wayland")
            self.assertEqual(info.kernel, "Linux 6.17.0-generic")
            self.assertEqual(info.firmware, "1.0")
            hw = {f.label: f.value for f in info.hardware_fields()}
            sw = {f.label: f.value for f in info.software_fields()}
            self.assertEqual(hw["Graphics"], "Intel UHD Graphics 620")
            self.assertEqual(hw["Display"], "1366\u00d7768")
            self.assertEqual(hw["Disk (/)"].startswith("SATA"), True)
            self.assertEqual(sw["Operating System"], "First Boot Linux 0.6.18")
            self.assertNotIn("Graphics 1", hw)

    def test_collect_live_does_not_raise(self) -> None:
        info = collect()
        self.assertIsInstance(info, SysInfo)
        self.assertTrue(info.software_fields())


if __name__ == "__main__":
    unittest.main()
