"""Kiosk topbar as a layer-shell surface above other windows."""

from __future__ import annotations

import sys
from ctypes import CDLL
from typing import Any, Callable

from firstboot.shell import TOPBAR_HEIGHT

LAYER_SHELL_SONAMES = (
    "libgtk4-layer-shell.so.0",
    "libgtk4-layer-shell.so",
)


def preload_layer_shell() -> bool:
    for name in LAYER_SHELL_SONAMES:
        try:
            CDLL(name)
            return True
        except OSError:
            continue
    return False


def layer_shell_available() -> bool:
    try:
        import gi

        gi.require_version("Gtk4LayerShell", "1.0")
        from gi.repository import Gtk4LayerShell as LayerShell
    except (ValueError, ImportError):
        return False
    try:
        return bool(LayerShell.is_supported())
    except Exception:
        return False


def output_size(window) -> tuple[int, int]:
    display = None
    try:
        display = window.get_display()
    except Exception:
        display = None
    if display is None:
        from gi.repository import Gdk

        display = Gdk.Display.get_default()
    width, height = 1280, 800
    if display is not None:
        monitors = display.get_monitors()
        if monitors.get_n_items() > 0:
            geo = monitors.get_item(0).get_geometry()
            width = max(1, geo.width)
            height = max(TOPBAR_HEIGHT, geo.height)
    return width, height


def apply_panel_allocation(window, fill=None) -> tuple[int, int]:
    width, _ = output_size(window)
    window.set_default_size(width, TOPBAR_HEIGHT)
    if fill is not None:
        fill.set_size_request(width, TOPBAR_HEIGHT)
    return width, TOPBAR_HEIGHT


def attach_shell_panel(
    application,
    topbar,
    menus: list,
    *,
    on_key: Callable,
    dark: bool,
) -> Any | None:
    del menus
    if not layer_shell_available():
        return None

    import gi
    from gi.repository import Gtk

    gi.require_version("Gtk4LayerShell", "1.0")
    from gi.repository import Gtk4LayerShell as LayerShell

    win = Gtk.Window(application=application, title="First Boot Linux")
    win.set_decorated(False)
    win.add_css_class("firstboot")
    win.add_css_class("firstboot-panel")
    if not dark:
        win.add_css_class("light")
    try:
        LayerShell.init_for_window(win)
        LayerShell.set_namespace(win, "firstboot-panel")
        LayerShell.set_layer(win, LayerShell.Layer.TOP)
        LayerShell.set_anchor(win, LayerShell.Edge.TOP, True)
        LayerShell.set_anchor(win, LayerShell.Edge.LEFT, True)
        LayerShell.set_anchor(win, LayerShell.Edge.RIGHT, True)
        LayerShell.set_anchor(win, LayerShell.Edge.BOTTOM, False)
        LayerShell.set_exclusive_zone(win, TOPBAR_HEIGHT)
        LayerShell.set_keyboard_mode(win, LayerShell.KeyboardMode.ON_DEMAND)
    except Exception:
        return None

    topbar.set_hexpand(True)
    topbar.set_halign(Gtk.Align.FILL)
    topbar.set_valign(Gtk.Align.FILL)
    topbar.set_size_request(-1, TOPBAR_HEIGHT)
    win.set_child(topbar)
    apply_panel_allocation(win)
    application.shell.enable_panel_popovers()

    mapped = False

    def on_map(*_a: object) -> None:
        nonlocal mapped
        width, height = apply_panel_allocation(win)
        if not mapped:
            mapped = True
            print(
                f"firstboot-chooser: panel {width}x{height}",
                file=sys.stderr,
                flush=True,
            )

    win.connect("realize", lambda *_: apply_panel_allocation(win))
    win.connect("map", on_map)

    key = Gtk.EventControllerKey()
    key.connect("key-pressed", on_key)
    win.add_controller(key)
    return win
