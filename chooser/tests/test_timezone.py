#!/usr/bin/env python3
"""UTC-offset timezone helpers — no GTK."""

from __future__ import annotations

import datetime as dt
import os
import sys
import tempfile
import unittest
from zoneinfo import ZoneInfo, reset_tzpath

HERE = os.path.dirname(os.path.abspath(__file__))
CHOOSER_DIR = os.path.dirname(HERE)
if CHOOSER_DIR not in sys.path:
    sys.path.insert(0, CHOOSER_DIR)

from firstboot.timezone import (  # noqa: E402
    TZ_MINUTES_MAX,
    TZ_MINUTES_MIN,
    TZ_MINUTES_STEP,
    clock_in_offset,
    format_tz_offset,
    iana_zone,
    load_timezone_minutes,
    parse_tz_offset,
    persist_timezone,
    posix_tz,
    snap_tz_minutes,
    tzif_bytes,
)


class SnapTests(unittest.TestCase):
    def test_half_hours(self) -> None:
        self.assertEqual(snap_tz_minutes(0), 0)
        self.assertEqual(snap_tz_minutes(29), 30)
        self.assertEqual(snap_tz_minutes(44), 30)
        self.assertEqual(snap_tz_minutes(45), 60)
        self.assertEqual(snap_tz_minutes(-20), -30)
        self.assertEqual(snap_tz_minutes(TZ_MINUTES_MIN - 90), TZ_MINUTES_MIN)
        self.assertEqual(snap_tz_minutes(TZ_MINUTES_MAX + 90), TZ_MINUTES_MAX)
        self.assertEqual(TZ_MINUTES_STEP, 30)


class FormatTests(unittest.TestCase):
    def test_labels(self) -> None:
        self.assertEqual(format_tz_offset(0), "UTC+0000")
        self.assertEqual(format_tz_offset(30), "UTC+0030")
        self.assertEqual(format_tz_offset(60), "UTC+0100")
        self.assertEqual(format_tz_offset(330), "UTC+0530")
        self.assertEqual(format_tz_offset(-300), "UTC-0500")
        self.assertEqual(format_tz_offset(-210), "UTC-0330")
        self.assertEqual(format_tz_offset(840), "UTC+1400")
        self.assertEqual(format_tz_offset(-720), "UTC-1200")

    def test_parse(self) -> None:
        self.assertEqual(parse_tz_offset("UTC+0000"), 0)
        self.assertEqual(parse_tz_offset("utc+0530"), 330)
        self.assertEqual(parse_tz_offset("+5:30"), 330)
        self.assertEqual(parse_tz_offset("UTC-0330"), -210)
        self.assertEqual(parse_tz_offset("UTC+14"), 840)
        self.assertIsNone(parse_tz_offset("UTC+0545"))
        self.assertIsNone(parse_tz_offset("Europe/Paris"))


class PosixTests(unittest.TestCase):
    def test_posix(self) -> None:
        self.assertEqual(posix_tz(0), "UTC0")
        self.assertEqual(posix_tz(60), "<+0100>-1")
        self.assertEqual(posix_tz(330), "<+0530>-5:30")
        self.assertEqual(posix_tz(-300), "<-0500>+5")
        self.assertEqual(posix_tz(-210), "<-0330>+3:30")

    def test_iana_whole_hours(self) -> None:
        self.assertEqual(iana_zone(0), "UTC")
        self.assertEqual(iana_zone(60), "Etc/GMT-1")
        self.assertEqual(iana_zone(-300), "Etc/GMT+5")
        self.assertEqual(iana_zone(840), "Etc/GMT-14")
        self.assertIsNone(iana_zone(330))


class PersistTests(unittest.TestCase):
    def test_file_and_retailer(self) -> None:
        with tempfile.TemporaryDirectory(prefix="fbl-tz-") as tmp:
            self.assertIsNone(load_timezone_minutes(tmp))
            self.assertEqual(load_timezone_minutes(tmp, "UTC+0200"), 120)
            self.assertTrue(persist_timezone(tmp, 330))
            self.assertEqual(load_timezone_minutes(tmp, "UTC+0000"), 330)
            with open(os.path.join(tmp, "timezone"), encoding="utf-8") as fh:
                self.assertEqual(fh.read().strip(), "UTC+0530")


class ClockTests(unittest.TestCase):
    def test_offset_shifts_wall_clock(self) -> None:
        now = dt.datetime(2026, 8, 13, 0, 42, tzinfo=dt.timezone.utc)
        shifted = clock_in_offset(60, now)
        self.assertEqual(shifted.hour, 1)
        self.assertEqual(shifted.minute, 42)
        kolkata = clock_in_offset(330, now)
        self.assertEqual(kolkata.hour, 6)
        self.assertEqual(kolkata.minute, 12)


class TzifTests(unittest.TestCase):
    def test_zoneinfo_reads_generated_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest_dir = os.path.join(tmp, "FirstBoot")
            os.makedirs(dest_dir)
            path = os.path.join(dest_dir, "Offset")
            with open(path, "wb") as fh:
                fh.write(tzif_bytes(330))
            reset_tzpath((tmp,))
            try:
                zone = ZoneInfo("FirstBoot/Offset")
            finally:
                reset_tzpath()
            now = dt.datetime(2026, 1, 1, 12, 0, tzinfo=dt.timezone.utc)
            local = now.astimezone(zone)
            self.assertEqual(local.utcoffset(), dt.timedelta(hours=5, minutes=30))
            self.assertTrue(pathlib_magic(path))


class HelperTests(unittest.TestCase):
    def test_rejects_bad_args(self) -> None:
        path = os.path.join(CHOOSER_DIR, "firstboot-set-timezone")
        ns: dict = {"__name__": "fbl_set_timezone", "__file__": path}
        with open(path, encoding="utf-8") as fh:
            exec(compile(fh.read(), path, "exec"), ns)
        self.assertEqual(ns["main"]([]), 2)
        self.assertEqual(ns["main"](["nope"]), 2)
        self.assertEqual(ns["main"](["15"]), 2)
        if os.geteuid() != 0:
            self.assertEqual(ns["main"](["0"]), 1)


def pathlib_magic(path: str) -> bool:
    with open(path, "rb") as fh:
        return fh.read(5) == b"TZif2"


if __name__ == "__main__":
    unittest.main()
