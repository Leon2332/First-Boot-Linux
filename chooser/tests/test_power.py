#!/usr/bin/env python3
"""Power Off / Restart countdown copy."""

from __future__ import annotations

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
CHOOSER_DIR = os.path.dirname(HERE)
if CHOOSER_DIR not in sys.path:
    sys.path.insert(0, CHOOSER_DIR)

from firstboot.i18n import apply_language  # noqa: E402
from firstboot.power import POWER_DELAY_SECONDS, countdown_body  # noqa: E402


class CountdownTests(unittest.TestCase):
    def test_delay_is_thirty(self) -> None:
        self.assertEqual(POWER_DELAY_SECONDS, 30)

    def test_restart_plural_and_one(self) -> None:
        self.assertEqual(
            countdown_body("restart", 30),
            "The computer will restart automatically in 30 seconds.",
        )
        self.assertEqual(
            countdown_body("restart", 1),
            "The computer will restart automatically in 1 second.",
        )

    def test_poweroff_plural_and_one(self) -> None:
        self.assertEqual(
            countdown_body("poweroff", 30),
            "The computer will shut down automatically in 30 seconds.",
        )
        self.assertEqual(
            countdown_body("poweroff", 1),
            "The computer will shut down automatically in 1 second.",
        )

    def test_afrikaans(self) -> None:
        apply_language("af")
        try:
            self.assertIn("30", countdown_body("restart", 30))
            self.assertNotIn("seconds", countdown_body("restart", 30))
            self.assertIn("1", countdown_body("poweroff", 1))
        finally:
            apply_language("en-us")


if __name__ == "__main__":
    unittest.main()
