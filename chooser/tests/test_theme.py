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
    CURSOR_SIZE,
    CURSOR_THEME,
    EPIPHANY_DESKTOP,
    EPIPHANY_SCHEMA,
    apply_session_theme,
    config_home,
    ensure_default_browser,
)
from firstboot.browser import (  # noqa: E402
    DEFAULT_SEARCH_ENGINE,
    START_PAGE_URI,
    search_engine_providers_variant,
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
            self.assertIn(f"gtk-cursor-theme-name={CURSOR_THEME}", gtk)
            self.assertIn(f"gtk-cursor-theme-size={CURSOR_SIZE}", gtk)
            apply_session_theme(False, env)
            gtk = Path(tmp, "gtk-4.0", "settings.ini").read_text(encoding="utf-8")
            self.assertIn("gtk-application-prefer-dark-theme=false", gtk)
            self.assertIn("gtk-interface-color-scheme=light", gtk)
            self.assertIn(f"gtk-cursor-theme-name={CURSOR_THEME}", gtk)
            gtk3 = Path(tmp, "gtk-3.0", "settings.ini").read_text(encoding="utf-8")
            self.assertIn("gtk-application-prefer-dark-theme=false", gtk3)
            self.assertIn("gtk-interface-color-scheme=light", gtk3)
            self.assertIn(f"gtk-cursor-theme-name={CURSOR_THEME}", gtk3)
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
        text = labwc.read_text(encoding="utf-8")
        self.assertIn("ADW_DISABLE_PORTAL=1", text)
        self.assertIn("XCURSOR_THEME=First Boot Cursor", text)
        self.assertIn("XCURSOR_SIZE=24", text)
        self.assertIn("XCURSOR_THEME=", session)
        self.assertIn("First Boot Cursor", session)


class EpiphanyDefaultTests(unittest.TestCase):
    def test_override_homepage_and_search(self) -> None:
        path = Path(
            CHOOSER_DIR,
            "..",
            "seed",
            "overlay",
            "usr",
            "share",
            "glib-2.0",
            "schemas",
            "20-firstboot-epiphany.gschema.override",
        ).resolve()
        self.assertTrue(path.is_file(), path)
        text = path.read_text(encoding="utf-8")
        self.assertIn("[org.gnome.Epiphany]", text)
        self.assertIn("ask-for-default=false", text)
        self.assertIn(f"homepage-url='{START_PAGE_URI}'", text)
        self.assertIn(f"default-search-engine='{DEFAULT_SEARCH_ENGINE}'", text)
        self.assertIn(f"incognito-search-engine='{DEFAULT_SEARCH_ENGINE}'", text)
        self.assertIn("restore-session-policy='crashed'", text)
        self.assertIn(
            f"search-engine-providers={search_engine_providers_variant()}", text
        )
        self.assertNotIn("Bing", text)
        self.assertNotIn("Ecosia", text)
        self.assertNotIn("Baidu", text)

    def test_chooser_sets_epiphany_search(self) -> None:
        app = Path(CHOOSER_DIR, "firstboot", "app.py").read_text(encoding="utf-8")
        theme = Path(CHOOSER_DIR, "firstboot", "theme.py").read_text(encoding="utf-8")
        self.assertIn("ensure_default_browser", app)
        self.assertIn(EPIPHANY_SCHEMA, theme)
        self.assertIn('"homepage-url"', theme)
        self.assertIn('"default-search-engine"', theme)
        self.assertIn('"search-engine-providers"', theme)
        kiosk = Path(CHOOSER_DIR, "firstboot", "kioskapp.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("START_PAGE_URI", kiosk)
        seed = Path(
            CHOOSER_DIR, "..", "seed", "build-seed.sh"
        ).resolve().read_text(encoding="utf-8")
        self.assertIn("write_start_page", seed)


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


class CursorThemeTests(unittest.TestCase):
    def test_overlay_default_index(self) -> None:
        path = Path(
            CHOOSER_DIR,
            "..",
            "seed",
            "overlay",
            "usr",
            "share",
            "icons",
            "default",
            "index.theme",
        ).resolve()
        self.assertTrue(path.is_file(), path)
        text = path.read_text(encoding="utf-8")
        self.assertIn("Inherits=First Boot Cursor", text)

    def test_interface_gschema_override(self) -> None:
        path = Path(
            CHOOSER_DIR,
            "..",
            "seed",
            "overlay",
            "usr",
            "share",
            "glib-2.0",
            "schemas",
            "20-firstboot-interface.gschema.override",
        ).resolve()
        self.assertTrue(path.is_file(), path)
        text = path.read_text(encoding="utf-8")
        self.assertIn("[org.gnome.desktop.interface]", text)
        self.assertIn("cursor-theme='First Boot Cursor'", text)
        self.assertIn("cursor-size=24", text)

    def test_svg_sources(self) -> None:
        svg = Path(
            CHOOSER_DIR, "..", "seed", "cursors", "src", "svg", "left_ptr.svg"
        ).resolve()
        self.assertTrue(svg.is_file(), svg)
        builder = Path(
            CHOOSER_DIR, "..", "seed", "cursors", "build_theme.py"
        ).resolve()
        self.assertTrue(builder.is_file(), builder)
        toml = Path(
            CHOOSER_DIR, "..", "seed", "cursors", "configs", "x.build.toml"
        ).resolve()
        self.assertTrue(toml.is_file(), toml)


if __name__ == "__main__":
    unittest.main()
