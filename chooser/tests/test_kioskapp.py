#!/usr/bin/env python3
"""Kiosk app launch helpers — no GTK window required."""

from __future__ import annotations

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
CHOOSER_DIR = os.path.dirname(HERE)
if CHOOSER_DIR not in sys.path:
    sys.path.insert(0, CHOOSER_DIR)

from firstboot.kioskapp import (  # noqa: E402
    CONSOLE_BINS,
    SYSINFO_BIN,
    WEB_BINS,
    WEBKIT_CHILD_UNSET,
    child_env,
    resolve_command,
)


class ResolveTests(unittest.TestCase):
    def test_sysinfo_in_tree(self) -> None:
        cmd = resolve_command(SYSINFO_BIN)
        self.assertIsNotNone(cmd)
        assert cmd is not None
        self.assertTrue(os.path.isfile(cmd))
        self.assertEqual(os.path.basename(cmd), SYSINFO_BIN)

    def test_web_names(self) -> None:
        self.assertEqual(WEB_BINS, ("epiphany", "epiphany-browser"))

    def test_console_names(self) -> None:
        self.assertEqual(CONSOLE_BINS, ("kgx",))

    def test_skips_snap(self) -> None:
        cmd = resolve_command("epiphany")
        if cmd is not None:
            self.assertNotIn("/snap/", cmd)


class ChildEnvTests(unittest.TestCase):
    def test_webkit_env_stripped(self) -> None:
        src = {
            "GSK_RENDERER": "ngl",
            "WEBKIT_DISABLE_DMABUF_RENDERER": "1",
            "WEBKIT_DISABLE_COMPOSITING_MODE": "1",
            "PATH": "/bin",
        }
        old = dict(os.environ)
        try:
            os.environ.clear()
            os.environ.update(src)
            env = child_env(unset=WEBKIT_CHILD_UNSET)
            self.assertNotIn("WEBKIT_DISABLE_DMABUF_RENDERER", env)
            self.assertNotIn("WEBKIT_DISABLE_COMPOSITING_MODE", env)
            self.assertNotIn("GSK_RENDERER", env)
            self.assertEqual(env.get("GDK_BACKEND"), "wayland")
            self.assertEqual(env.get("GTK_USE_PORTAL"), "0")
            self.assertEqual(env.get("ADW_DISABLE_PORTAL"), "1")
        finally:
            os.environ.clear()
            os.environ.update(old)

    def test_console_keeps_gsk(self) -> None:
        old = dict(os.environ)
        try:
            os.environ.clear()
            os.environ["GSK_RENDERER"] = "ngl"
            os.environ["PATH"] = "/bin"
            env = child_env()
            self.assertEqual(env.get("GSK_RENDERER"), "ngl")
        finally:
            os.environ.clear()
            os.environ.update(old)

    def test_drops_memory_gsettings(self) -> None:
        old = dict(os.environ)
        try:
            os.environ.clear()
            os.environ["GSETTINGS_BACKEND"] = "memory"
            os.environ["PATH"] = "/bin"
            env = child_env()
            self.assertNotIn("GSETTINGS_BACKEND", env)
            self.assertEqual(env.get("ADW_DISABLE_PORTAL"), "1")
        finally:
            os.environ.clear()
            os.environ.update(old)


if __name__ == "__main__":
    unittest.main()
