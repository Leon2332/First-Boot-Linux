#!/usr/bin/env python3
"""Brightness helpers — no GTK."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
CHOOSER_DIR = os.path.dirname(HERE)
if CHOOSER_DIR not in sys.path:
    sys.path.insert(0, CHOOSER_DIR)

from firstboot.brightness import (  # noqa: E402
    MemoryBrightness,
    SysfsBrightness,
    level_to_raw,
    pick_backlight,
    raw_to_level,
)


class ConvertTests(unittest.TestCase):
    def test_round_trip(self) -> None:
        self.assertEqual(raw_to_level(1023, 1023), 100)
        self.assertEqual(raw_to_level(0, 1023), 0)
        self.assertEqual(level_to_raw(100, 1023), 1023)
        self.assertEqual(level_to_raw(0, 1023), 0)

    def test_mid(self) -> None:
        self.assertEqual(raw_to_level(512, 1023), 50)
        self.assertEqual(level_to_raw(50, 1023), 512)


class MemoryTests(unittest.TestCase):
    def test_set_level(self) -> None:
        b = MemoryBrightness(80)
        self.assertEqual(b.get().level, 80)
        self.assertFalse(b.get().available)
        st = b.set_level(40)
        self.assertEqual(st.level, 40)


class SysfsTests(unittest.TestCase):
    def test_pick_prefers_intel(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            acpi = os.path.join(tmp, "acpi_video0")
            intel = os.path.join(tmp, "intel_backlight")
            os.makedirs(acpi)
            os.makedirs(intel)
            for root, mx in ((acpi, "15"), (intel, "1023")):
                with open(os.path.join(root, "max_brightness"), "w") as fh:
                    fh.write(mx)
                with open(os.path.join(root, "actual_brightness"), "w") as fh:
                    fh.write(mx)
                with open(os.path.join(root, "brightness"), "w") as fh:
                    fh.write(mx)
            self.assertEqual(pick_backlight(tmp), intel)

    def test_sysfs_set(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "max_brightness"), "w") as fh:
                fh.write("1023")
            with open(os.path.join(tmp, "actual_brightness"), "w") as fh:
                fh.write("1023")
            path = os.path.join(tmp, "brightness")
            with open(path, "w") as fh:
                fh.write("1023")
            b = SysfsBrightness(tmp)
            st = b.set_level(50)
            self.assertEqual(st.level, 50)
            with open(path) as fh:
                self.assertEqual(int(fh.read().strip()), 512)


if __name__ == "__main__":
    unittest.main()
