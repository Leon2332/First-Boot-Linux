#!/usr/bin/env python3
"""Session theme + default browser helpers — no GTK window required."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
CHOOSER_DIR = os.path.dirname(HERE)
if CHOOSER_DIR not in sys.path:
    sys.path.insert(0, CHOOSER_DIR)

from firstboot.theme import (  # noqa: E402
    EPIPHANY_DESKTOP,
    apply_session_theme,
    config_home,
    ensure_default_browser,
)


class ConfigHomeTests(unittest.TestCase):
    def test_xdg_config_home(self) -> None:
        self.assertEqual(
            config_home({"XDG_CONFIG_HOME": "/tmp/cfg", "HOME": "/home/x"}),
            "/tmp/cfg",
        )

    def test_falls_back_to_home(self) -> None:
        self.assertEqual(config_home({"HOME": "/home/x"}), "/home/x/.config")


class WriteTests(unittest.TestCase):
    def test_gtk_settings_and_mimeapps(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = {"XDG_CONFIG_HOME": tmp, "HOME": tmp}
            apply_session_theme(True, env)
            ensure_default_browser(env)
            gtk = Path(tmp, "gtk-4.0", "settings.ini").read_text(encoding="utf-8")
            self.assertIn("gtk-application-prefer-dark-theme=true", gtk)
            apply_session_theme(False, env)
            gtk = Path(tmp, "gtk-4.0", "settings.ini").read_text(encoding="utf-8")
            self.assertIn("gtk-application-prefer-dark-theme=false", gtk)
            mime = Path(tmp, "mimeapps.list").read_text(encoding="utf-8")
            self.assertIn("[Default Applications]", mime)
            self.assertIn(f"x-scheme-handler/https={EPIPHANY_DESKTOP}", mime)
            self.assertIn(f"text/html={EPIPHANY_DESKTOP}", mime)


if __name__ == "__main__":
    unittest.main()
