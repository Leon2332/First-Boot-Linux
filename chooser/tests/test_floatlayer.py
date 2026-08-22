#!/usr/bin/env python3
"""Float layer drag mapping — clamp is pure; surface map needs a display."""

from __future__ import annotations

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
CHOOSER_DIR = os.path.dirname(HERE)
if CHOOSER_DIR not in sys.path:
    sys.path.insert(0, CHOOSER_DIR)


class ClampTests(unittest.TestCase):
    def test_inside(self) -> None:
        from firstboot.floatlayer import clamp_pos

        self.assertEqual(clamp_pos(100, 40, 720, 1280, 800), (100, 40))

    def test_edges(self) -> None:
        from firstboot.floatlayer import clamp_pos

        self.assertEqual(clamp_pos(-1000, -20, 720, 1280, 800), (-640, 0))
        self.assertEqual(clamp_pos(4000, 4000, 720, 1280, 800), (1200, 760))


class PointerTests(unittest.TestCase):
    def test_none_target(self) -> None:
        from firstboot.floatlayer import pointer_from_gesture

        self.assertIsNone(pointer_from_gesture(None, object()))


@unittest.skipUnless(
    os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"),
    "no display",
)
class StackTests(unittest.TestCase):
    def test_raise_child_becomes_last_sibling(self) -> None:
        import gi

        gi.require_version("Gtk", "4.0")
        from gi.repository import Gtk

        from firstboot.floatlayer import FloatLayer

        layer = FloatLayer()
        first = Gtk.Label(label="first")
        second = Gtk.Label(label="second")
        layer.put(first, 0, 0)
        layer.put(second, 10, 10)
        self.assertIs(layer.get_last_child(), second)
        layer.raise_child(first)
        self.assertIs(layer.get_last_child(), first)
        self.assertIs(first.get_next_sibling(), None)
        self.assertIs(second.get_next_sibling(), first)
        layer.raise_child(first)
        self.assertIs(layer.get_last_child(), first)


@unittest.skipUnless(
    os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"),
    "no display",
)
class SurfaceMapTests(unittest.TestCase):
    def test_child_move_does_not_shift_surface_map(self) -> None:
        import gi

        gi.require_version("Gtk", "4.0")
        from gi.repository import GLib, Gtk

        from firstboot.floatlayer import pointer_from_surface

        result: dict[str, object] = {}

        def activate(app: Gtk.Application) -> None:
            win = Gtk.ApplicationWindow(application=app)
            win.set_default_size(400, 300)
            fixed = Gtk.Fixed()
            win.set_child(fixed)
            child = Gtk.Box()
            child.set_size_request(200, 80)
            fixed.put(child, 100, 40)
            win.present()

            def tick() -> bool:
                native = fixed.get_native()
                if native is None or child.get_width() <= 0:
                    return True
                tx, ty = native.get_surface_transform()
                sx, sy = 160.0 + tx, 90.0 + ty
                before = pointer_from_surface(fixed, sx, sy)
                fixed.move(child, 250, 90)
                after = pointer_from_surface(fixed, sx, sy)
                result["before"] = before
                result["after"] = after
                app.quit()
                return False

            GLib.timeout_add(50, tick)
            GLib.timeout_add(2000, lambda: (app.quit(), False)[1])

        app = Gtk.Application(application_id="org.firstboot.testfloatlayer")
        app.connect("activate", activate)
        app.run([])
        self.assertIsNotNone(result.get("before"))
        self.assertEqual(result.get("before"), result.get("after"))


if __name__ == "__main__":
    unittest.main()
