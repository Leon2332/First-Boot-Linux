#!/usr/bin/env python3
"""Volume backend — no Pulse required."""

from __future__ import annotations

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
CHOOSER_DIR = os.path.dirname(HERE)
if CHOOSER_DIR not in sys.path:
    sys.path.insert(0, CHOOSER_DIR)

from firstboot.volume import (  # noqa: E402
    MemoryVolume,
    clamp_level,
    parse_pactl_mute,
    parse_pactl_volume,
)


class ParseTests(unittest.TestCase):
    def test_volume_line(self) -> None:
        text = (
            "Volume: front-left: 45875 /  70% / -9.11 dB,   "
            "front-right: 45875 /  70% / -9.11 dB"
        )
        self.assertEqual(parse_pactl_volume(text), 70)

    def test_mute(self) -> None:
        self.assertTrue(parse_pactl_mute("Mute: yes"))
        self.assertFalse(parse_pactl_mute("Mute: no"))

    def test_clamp(self) -> None:
        self.assertEqual(clamp_level(-4), 0)
        self.assertEqual(clamp_level(140), 100)


class MemoryTests(unittest.TestCase):
    def test_slider_to_zero_mutes(self) -> None:
        v = MemoryVolume(70)
        st = v.set_level(0)
        self.assertEqual(st.output, 0)
        self.assertEqual(st.icon, "audio-volume-muted-symbolic.svg")

    def test_toggle_mute_restores(self) -> None:
        v = MemoryVolume(55)
        v.toggle_mute()
        self.assertEqual(v.get().output, 0)
        st = v.toggle_mute()
        self.assertEqual(st.level, 55)
        self.assertEqual(st.output, 55)
        self.assertEqual(st.icon, "audio-volume-medium-symbolic.svg")

    def test_unmute_from_zero_goes_to_default(self) -> None:
        v = MemoryVolume(0, muted=True)
        st = v.toggle_mute()
        self.assertEqual(st.level, 70)
        self.assertFalse(st.muted)


if __name__ == "__main__":
    unittest.main()
