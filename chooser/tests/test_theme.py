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
    CONSOLE_SCHEMA,
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
            self.assertIn("gtk-interface-color-scheme=dark", gtk)
            apply_session_theme(False, env)
            gtk = Path(tmp, "gtk-4.0", "settings.ini").read_text(encoding="utf-8")
            self.assertIn("gtk-application-prefer-dark-theme=false", gtk)
            self.assertIn("gtk-interface-color-scheme=light", gtk)
            gtk3 = Path(tmp, "gtk-3.0", "settings.ini").read_text(encoding="utf-8")
            self.assertIn("gtk-application-prefer-dark-theme=false", gtk3)
            self.assertIn("gtk-interface-color-scheme=light", gtk3)
            mime = Path(tmp, "mimeapps.list").read_text(encoding="utf-8")
            self.assertIn("[Default Applications]", mime)
            self.assertIn(f"x-scheme-handler/https={EPIPHANY_DESKTOP}", mime)
            self.assertIn(f"text/html={EPIPHANY_DESKTOP}", mime)


class ChooserEnvTests(unittest.TestCase):
    def test_chooser_does_not_force_memory_gsettings(self) -> None:
        path = Path(CHOOSER_DIR, "firstboot-chooser")
        text = path.read_text(encoding="utf-8")
        self.assertNotIn('setdefault("GSETTINGS_BACKEND", "memory")', text)
        self.assertIn('pop("GSETTINGS_BACKEND", None)', text)
        self.assertIn('ADW_DISABLE_PORTAL', text)

    def test_session_and_labwc_disable_adw_portal(self) -> None:
        session = Path(CHOOSER_DIR, "firstboot-session").read_text(encoding="utf-8")
        self.assertIn("ADW_DISABLE_PORTAL=1", session)
        sysinfo = Path(CHOOSER_DIR, "firstboot-sysinfo").read_text(encoding="utf-8")
        self.assertIn('ADW_DISABLE_PORTAL', sysinfo)
        labwc = Path(
            CHOOSER_DIR,
            "..",
            "seed",
            "overlay",
            "usr",
            "share",
            "firstboot",
            "labwc",
            "environment",
        ).resolve()
        self.assertTrue(labwc.is_file(), labwc)
        self.assertIn("ADW_DISABLE_PORTAL=1", labwc.read_text(encoding="utf-8"))


class ConsoleDefaultTests(unittest.TestCase):
    def test_override_follows_system(self) -> None:
        path = Path(
            CHOOSER_DIR,
            "..",
            "seed",
            "overlay",
            "usr",
            "share",
            "glib-2.0",
            "schemas",
            "20-firstboot-console.gschema.override",
        ).resolve()
        self.assertTrue(path.is_file(), path)
        text = path.read_text(encoding="utf-8")
        self.assertIn("[org.gnome.Console]", text)
        self.assertIn("theme='auto'", text)

    def test_chooser_sets_console_theme(self) -> None:
        app = Path(CHOOSER_DIR, "firstboot", "app.py").read_text(encoding="utf-8")
        theme = Path(CHOOSER_DIR, "firstboot", "theme.py").read_text(encoding="utf-8")
        self.assertIn("ensure_console_follows_system", app)
        self.assertIn(CONSOLE_SCHEMA, theme)
        self.assertIn('"theme", "auto"', theme)


if __name__ == "__main__":
    unittest.main()
