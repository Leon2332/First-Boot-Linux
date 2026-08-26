#!/usr/bin/env python3
"""Asset paths and SVG recolor — no GTK."""

from __future__ import annotations

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
CHOOSER_DIR = os.path.dirname(HERE)
if CHOOSER_DIR not in sys.path:
    sys.path.insert(0, CHOOSER_DIR)

from firstboot.assets import (  # noqa: E402
    find_app_icon,
    find_brand_logo,
    find_brand_wordmark,
    find_logo,
    find_status,
    recolor_svg,
)
from firstboot.shell import format_clock  # noqa: E402

import datetime as dt


class AssetTests(unittest.TestCase):
    def test_repo_logos_and_status(self) -> None:
        self.assertTrue(find_logo("ubuntu"))
        self.assertTrue(find_logo("linux-mint"))
        self.assertTrue(find_status("network-wired-symbolic.svg"))
        self.assertTrue(find_status("view-app-grid-symbolic.svg"))
        self.assertTrue(find_app_icon("epiphany.png"))
        self.assertTrue(find_app_icon("org.gnome.Epiphany.svg"))
        self.assertTrue(find_app_icon("other-option-dark.png"))
        self.assertTrue(find_app_icon("other-option-light.png"))
        self.assertTrue(find_status("folder-download-symbolic.svg"))
        self.assertTrue(find_status("display-brightness-symbolic.svg"))
        self.assertTrue(find_brand_logo())
        self.assertTrue(find_brand_wordmark(True))
        self.assertTrue(find_brand_wordmark(False))
        self.assertNotEqual(find_brand_wordmark(True), find_brand_wordmark(False))

    def test_recolor_replaces_fill(self) -> None:
        src = '<svg><g fill="#808080"><circle /></g></svg>'
        out = recolor_svg(src, "#f6f5f4")
        self.assertIn('fill="#f6f5f4"', out)
        self.assertNotIn("#808080", out)

    def test_clock_format(self) -> None:
        now = dt.datetime(2026, 8, 13, 0, 42)
        self.assertEqual(format_clock(now), "13 Aug 00:42")
        utc = dt.datetime(2026, 8, 13, 0, 42, tzinfo=dt.timezone.utc)
        from firstboot.timezone import clock_in_offset

        self.assertEqual(format_clock(clock_in_offset(330, utc)), "13 Aug 06:12")


if __name__ == "__main__":
    unittest.main()
