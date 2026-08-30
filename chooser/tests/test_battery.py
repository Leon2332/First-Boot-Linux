#!/usr/bin/env python3
"""Battery sysfs probe — no GTK."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
CHOOSER_DIR = os.path.dirname(HERE)
if CHOOSER_DIR not in sys.path:
    sys.path.insert(0, CHOOSER_DIR)

from firstboot.battery import (  # noqa: E402
    COLOR_CRITICAL,
    COLOR_LOW,
    BatteryState,
    battery_svg,
    parse_fake_battery,
    read_battery,
)
from firstboot.i18n import apply_language  # noqa: E402


def _write_supply(root: str, name: str, **fields: str) -> str:
    path = os.path.join(root, name)
    os.makedirs(path)
    for key, value in fields.items():
        with open(os.path.join(path, key), "w", encoding="ascii") as fh:
            fh.write(value)
    return path


class FakeTests(unittest.TestCase):
    def test_none(self) -> None:
        self.assertFalse(parse_fake_battery("none").present)
        self.assertFalse(parse_fake_battery("").present)

    def test_percent(self) -> None:
        st = parse_fake_battery("73")
        self.assertTrue(st.present)
        self.assertEqual(st.percent, 73)
        self.assertFalse(st.charging)
        self.assertEqual(st.label, "73%")

    def test_charging(self) -> None:
        st = parse_fake_battery("40,charging")
        self.assertTrue(st.charging)
        self.assertEqual(st.percent, 40)
        self.assertFalse(st.low)

    def test_full(self) -> None:
        st = parse_fake_battery("100,full")
        self.assertTrue(st.full)
        self.assertTrue(st.charging)


class SysfsTests(unittest.TestCase):
    def test_missing_dir(self) -> None:
        st = read_battery("/no/such/power_supply", env={})
        self.assertFalse(st.present)

    def test_desktop_only_ac(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _write_supply(tmp, "AC", type="Mains", online="1")
            st = read_battery(tmp, env={})
            self.assertFalse(st.present)

    def test_discharging(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _write_supply(
                tmp,
                "BAT0",
                type="Battery",
                present="1",
                status="Discharging",
                capacity="73",
            )
            _write_supply(tmp, "ACAD", type="Mains", online="0")
            st = read_battery(tmp, env={})
            self.assertTrue(st.present)
            self.assertEqual(st.percent, 73)
            self.assertFalse(st.charging)
            self.assertFalse(st.low)

    def test_charging_on_ac(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _write_supply(
                tmp,
                "BAT0",
                type="Battery",
                status="Charging",
                capacity="12",
            )
            _write_supply(tmp, "ADP1", type="Mains", online="1")
            st = read_battery(tmp, env={})
            self.assertTrue(st.charging)
            self.assertFalse(st.low)
            self.assertEqual(st.percent, 12)

    def test_absent_pack(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _write_supply(
                tmp,
                "BAT0",
                type="Battery",
                present="0",
                capacity="50",
            )
            st = read_battery(tmp, env={})
            self.assertFalse(st.present)

    def test_energy_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _write_supply(
                tmp,
                "BAT0",
                type="Battery",
                status="Discharging",
                energy_now="40000000",
                energy_full="80000000",
            )
            st = read_battery(tmp, env={})
            self.assertEqual(st.percent, 50)

    def test_low_and_critical(self) -> None:
        low = BatteryState(True, 18, "discharging", False)
        crit = BatteryState(True, 8, "discharging", False)
        self.assertTrue(low.low)
        self.assertFalse(low.critical)
        self.assertEqual(low.color, COLOR_LOW)
        self.assertTrue(crit.critical)
        self.assertEqual(crit.color, COLOR_CRITICAL)

    def test_fake_env_wins(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _write_supply(tmp, "BAT0", type="Battery", capacity="10")
            st = read_battery(tmp, env={"FIRSTBOOT_FAKE_BATTERY": "none"})
            self.assertFalse(st.present)

    def test_average_two_packs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _write_supply(
                tmp, "BAT0", type="Battery", status="Discharging", capacity="80"
            )
            _write_supply(
                tmp, "BAT1", type="Battery", status="Discharging", capacity="40"
            )
            st = read_battery(tmp, env={})
            self.assertEqual(st.percent, 60)


class SvgTests(unittest.TestCase):
    def test_fill_scales(self) -> None:
        empty = battery_svg(percent=0, charging=False)
        self.assertNotIn("M2.25 6.25", empty)
        half = battery_svg(percent=50, charging=False)
        self.assertIn("M2.25 6.25h4.50", half)
        self.assertNotIn("M9.05 6.15", half)

    def test_charging_bolt(self) -> None:
        svg = battery_svg(percent=40, charging=True)
        self.assertIn("M9.05 6.15", svg)
        self.assertIn('fill-rule="evenodd"', svg)
        self.assertNotIn("M9.05 6.15", battery_svg(percent=40, charging=False))


class TooltipTests(unittest.TestCase):
    def setUp(self) -> None:
        apply_language("en-us")

    def test_copy(self) -> None:
        self.assertEqual(
            BatteryState(True, 73, "discharging").tooltip(),
            "Battery 73%",
        )
        self.assertEqual(
            BatteryState(True, 40, "charging", True).tooltip(),
            "Charging — 40%",
        )
        self.assertEqual(
            BatteryState(True, 100, "full", True).tooltip(),
            "Fully charged",
        )
        self.assertEqual(
            BatteryState(True, 12, "discharging").tooltip(),
            "Battery low — 12%",
        )


if __name__ == "__main__":
    unittest.main()
