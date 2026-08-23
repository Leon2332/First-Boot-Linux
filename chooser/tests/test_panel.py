#!/usr/bin/env python3
"""Layer-shell panel helpers — no display required."""

from __future__ import annotations

import os
import sys
import unittest
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
CHOOSER_DIR = os.path.dirname(HERE)
REPO = os.path.dirname(CHOOSER_DIR)
if CHOOSER_DIR not in sys.path:
    sys.path.insert(0, CHOOSER_DIR)

from firstboot.panel import (  # noqa: E402
    LAYER_SHELL_SONAMES,
    apply_panel_allocation,
    layer_shell_available,
    preload_layer_shell,
)
from firstboot.shell import TOPBAR_HEIGHT  # noqa: E402


class PanelConstTests(unittest.TestCase):
    def test_topbar_height(self) -> None:
        self.assertEqual(TOPBAR_HEIGHT, 32)

    def test_sonames(self) -> None:
        self.assertIn("libgtk4-layer-shell.so.0", LAYER_SHELL_SONAMES)

    def test_preload_is_bool(self) -> None:
        self.assertIsInstance(preload_layer_shell(), bool)

    def test_available_is_bool(self) -> None:
        self.assertIsInstance(layer_shell_available(), bool)

    def test_apply_panel_allocation_exists(self) -> None:
        self.assertTrue(callable(apply_panel_allocation))


class LabwcConfigTests(unittest.TestCase):
    def test_chooser_always_on_bottom_and_fixed(self) -> None:
        path = os.path.join(
            REPO, "seed", "overlay", "usr", "share", "firstboot", "labwc", "rc.xml"
        )
        tree = ET.parse(path)
        root = tree.getroot()
        chooser = None
        for rule in root.findall(".//windowRule"):
            if rule.get("identifier") == "org.firstboot.Chooser":
                chooser = rule
                break
        self.assertIsNotNone(chooser)
        assert chooser is not None
        self.assertEqual(chooser.get("fixedPosition"), "yes")
        actions = [a.get("name") for a in chooser.findall("action")]
        self.assertIn("Maximize", actions)
        self.assertIn("ToggleAlwaysOnBottom", actions)
        self.assertNotIn("ToggleAlwaysOnTop", actions)

    def test_screen_edge_resistance(self) -> None:
        path = os.path.join(
            REPO, "seed", "overlay", "usr", "share", "firstboot", "labwc", "rc.xml"
        )
        tree = ET.parse(path)
        strength = tree.findtext(".//resistance/screenEdgeStrength")
        self.assertIsNotNone(strength)
        assert strength is not None
        self.assertGreaterEqual(int(strength), 1000)

    def test_keep_list_has_layer_shell(self) -> None:
        path = os.path.join(REPO, "seed", "packages", "keep.list")
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("gir1.2-gtk4layershell-1.0", text)
        self.assertIn("libgtk4-layer-shell0", text)
        self.assertIn("python3-cairo", text)
        self.assertIn("pipewire-pulse", text)
        self.assertIn("wireplumber", text)


if __name__ == "__main__":
    unittest.main()
