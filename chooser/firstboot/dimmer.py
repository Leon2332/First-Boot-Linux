"""Frosted backdrop for the distro popover. GTK CSS has no backdrop-filter."""

from __future__ import annotations

import gi

gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")
gi.require_version("Graphene", "1.0")

from gi.repository import Gdk, Graphene, Gtk


class BlurDimmer(Gtk.Widget):
    __gtype_name__ = "FirstbootBlurDimmer"

    def __init__(self) -> None:
        super().__init__()
        self._source: Gtk.Widget | None = None
        self._wallpaper: Gtk.Widget | None = None
        self._dark = True
        self.set_hexpand(True)
        self.set_vexpand(True)
        self.set_overflow(Gtk.Overflow.HIDDEN)

    def set_source(self, widget: Gtk.Widget) -> None:
        self._source = widget

    def set_wallpaper(self, widget: Gtk.Widget) -> None:
        self._wallpaper = widget

    def set_dark(self, dark: bool) -> None:
        if self._dark == dark:
            return
        self._dark = dark
        self.queue_draw()

    def do_snapshot(self, snapshot: Gtk.Snapshot) -> None:
        width = float(self.get_width())
        height = float(self.get_height())
        if width <= 0 or height <= 0:
            return
        rect = Graphene.Rect()
        rect.init(0, 0, width, height)
        snapshot.push_clip(rect)
        snapshot.push_blur(36.0)
        self._paint_aligned(snapshot, self._wallpaper)
        self._paint_aligned(snapshot, self._source)
        snapshot.pop()
        snapshot.pop()
        tint = Gdk.RGBA()
        if self._dark:
            tint.parse("rgba(14, 16, 20, 0.38)")
        else:
            tint.parse("rgba(240, 242, 245, 0.42)")
        snapshot.append_color(tint, rect)

    def _paint_aligned(self, snapshot: Gtk.Snapshot, widget: Gtk.Widget | None) -> None:
        if widget is None:
            return
        w = float(widget.get_width())
        h = float(widget.get_height())
        if w <= 0 or h <= 0:
            return
        origin = Graphene.Point()
        origin.init(0, 0)
        ok, point = self.compute_point(widget, origin)
        snapshot.save()
        if ok and point is not None:
            offset = Graphene.Point()
            offset.init(-point.x, -point.y)
            snapshot.translate(offset)
        Gtk.WidgetPaintable.new(widget).snapshot(snapshot, w, h)
        snapshot.restore()
