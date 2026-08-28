#!/usr/bin/env python3
"""Shop keyboard layouts — no GTK."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
CHOOSER_DIR = os.path.dirname(HERE)
if CHOOSER_DIR not in sys.path:
    sys.path.insert(0, CHOOSER_DIR)

from firstboot.keyboard import (  # noqa: E402
    DEFAULT_KEYBOARD,
    KEYBOARD_FILE,
    load_keyboard,
    load_keyboard_index,
    normalize_id,
    resolve_keyboard,
    write_keyboard_file,
)


class KeyboardTests(unittest.TestCase):
    def test_normalize(self) -> None:
        self.assertEqual(normalize_id("US"), "us")
        self.assertEqual(normalize_id("gb"), "gb")
        self.assertEqual(normalize_id("latam"), "latam")
        self.assertIsNone(normalize_id("English"))
        self.assertIsNone(normalize_id("../us"))

    def test_index_has_us_and_gb(self) -> None:
        ids = {kb.id for kb in load_keyboard_index()}
        self.assertIn("us", ids)
        self.assertIn("gb", ids)
        self.assertIn("za", ids)
        self.assertIn("de", ids)

    def test_resolve_unknown_is_us(self) -> None:
        self.assertEqual(resolve_keyboard(None), DEFAULT_KEYBOARD)
        self.assertEqual(resolve_keyboard("nope"), "us")
        self.assertEqual(resolve_keyboard("GB"), "gb")

    def test_file_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory(prefix="fbl-kbd-") as tmp:
            self.assertEqual(load_keyboard(tmp), "us")
            write_keyboard_file(tmp, "gb")
            path = os.path.join(tmp, KEYBOARD_FILE)
            with open(path, encoding="utf-8") as fh:
                self.assertEqual(fh.read().strip(), "gb")
            self.assertEqual(load_keyboard(tmp), "gb")
            self.assertEqual(load_keyboard(tmp, "us"), "gb")
            os.remove(path)
            self.assertEqual(load_keyboard(tmp, "za"), "za")


if __name__ == "__main__":
    unittest.main()
