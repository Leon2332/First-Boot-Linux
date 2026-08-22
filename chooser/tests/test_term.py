#!/usr/bin/env python3
"""Terminal helpers — no GTK required."""

from __future__ import annotations

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
CHOOSER_DIR = os.path.dirname(HERE)
if CHOOSER_DIR not in sys.path:
    sys.path.insert(0, CHOOSER_DIR)

from firstboot.shell import APP_ITEMS, APP_TOASTS  # noqa: E402
from firstboot.term import (  # noqa: E402
    VTE_API,
    default_title,
    spawn_argv,
    spawn_cwd,
    vte_available,
)


class TermHelperTests(unittest.TestCase):
    def test_vte_api(self) -> None:
        self.assertEqual(VTE_API, "3.91")

    def test_spawn_argv_login_shell(self) -> None:
        argv = spawn_argv()
        self.assertEqual(len(argv), 2)
        self.assertTrue(os.path.isfile(argv[0]))
        self.assertEqual(argv[1], "-l")

    def test_spawn_cwd_home(self) -> None:
        home = os.path.expanduser("~")
        cwd = spawn_cwd()
        if os.path.isdir(home):
            self.assertEqual(cwd, home)
        else:
            self.assertEqual(cwd, "/")

    def test_default_title_shape(self) -> None:
        title = default_title()
        self.assertIn("@", title)
        self.assertTrue(title.endswith(": ~"))

    def test_vte_available_is_bool(self) -> None:
        self.assertIsInstance(vte_available(), bool)


class AppGridTests(unittest.TestCase):
    def test_app_grid_actions(self) -> None:
        actions = [item[2] for item in APP_ITEMS]
        self.assertEqual(actions, ["browser", "sysinfo", "terminal"])
        self.assertNotIn("terminal", APP_TOASTS)
        self.assertNotIn("sysinfo", APP_TOASTS)
        self.assertNotIn("browser", APP_TOASTS)


if __name__ == "__main__":
    unittest.main()
