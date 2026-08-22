"""Click-through Fixed layer for in-kiosk windows.

Position children with Fixed.move, not overlay margins (GSK cairo leaves a
ghost of the old allocation). Empty space must not steal clicks. Header drag
maps the pointer's surface position into this layer — GestureDrag offsets are
widget-local and collapse after the first move.
"""

from __future__ import annotations

from typing import Protocol

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Graphene", "1.0")

from gi.repository import Graphene, Gtk


class DragHost(Protocol):
    layer: Gtk.Widget | None
    frame: Gtk.Widget | None
    _maxed: bool
    _x: int
    _y: int

    def _move(self, x: int, y: int) -> None: ...


def clamp_pos(
    x: float,
    y: float,
    win_w: int,
    layer_w: int,
    layer_h: int,
) -> tuple[int, int]:
    nx = max(-win_w + 80, min(layer_w - 80, int(x)))
    ny = max(0, min(layer_h - 40, int(y)))
    return nx, ny


def pointer_from_surface(
    target: Gtk.Widget,
    surface_x: float,
    surface_y: float,
) -> tuple[float, float] | None:
    """Surface coordinates mapped into an unmoving widget."""
    native = target.get_native()
    if native is None:
        return None
    tx, ty = native.get_surface_transform()
    point = Graphene.Point()
    point.init(surface_x - tx, surface_y - ty)
    ok, out = native.compute_point(target, point)
    if not ok or out is None:
        return None
    return (out.x, out.y)


def pointer_from_gesture(target, gesture) -> tuple[float, float] | None:
    """Current pointer in target coordinates.

    Uses the event's surface position so the result does not move when the
    gesture widget is Fixed.move'd. Do not use GestureDrag dx/dy for that.
    """
    if target is None:
        return None
    event = gesture.get_current_event()
    if event is not None:
        ok, x, y = event.get_position()
        if ok:
            mapped = pointer_from_surface(target, x, y)
            if mapped is not None:
                return mapped
    native = target.get_native()
    if native is None:
        return None
    surface = native.get_surface()
    display = target.get_display()
    if surface is None or display is None:
        return None
    seat = display.get_default_seat()
    if seat is None:
        return None
    device = seat.get_pointer()
    if device is None:
        return None
    ok, x, y, _mask = surface.get_device_position(device)
    if not ok:
        return None
    return pointer_from_surface(target, x, y)


class HeaderDrag:
    """Drag an in-kiosk window by its header across a FloatLayer."""

    def __init__(self, host: DragHost) -> None:
        self.host = host
        self._orig: tuple[int, int] | None = None
        self._ptr: tuple[float, float] | None = None

    def attach(self, header: Gtk.Widget) -> None:
        drag = Gtk.GestureDrag()
        drag.set_button(1)
        drag.connect("drag-begin", self._begin)
        drag.connect("drag-update", self._update)
        drag.connect("drag-end", self._end)
        header.add_controller(drag)

    def _target(self):
        host = self.host
        if host.layer is not None:
            return host.layer
        if host.frame is not None:
            return host.frame.get_parent()
        return None

    def _begin(self, gesture, x: float, y: float) -> None:
        host = self.host
        widget = gesture.get_widget()
        if widget is not None:
            picked = widget.pick(x, y, Gtk.PickFlags.DEFAULT)
            cur = picked
            while cur is not None and cur is not widget:
                if cur.has_css_class("term-wc"):
                    gesture.set_state(Gtk.EventSequenceState.DENIED)
                    self._orig = None
                    self._ptr = None
                    return
                cur = cur.get_parent()
        if host._maxed or host.frame is None:
            self._orig = None
            self._ptr = None
            return
        self._orig = (host._x, host._y)
        self._ptr = pointer_from_gesture(self._target(), gesture)
        if self._ptr is None:
            self._ptr = self._local_point(gesture, x, y)

    def _local_point(self, gesture, x: float, y: float):
        """Widget-local point mapped into the layer. Valid only before the child moves."""
        target = self._target()
        widget = gesture.get_widget()
        if target is None or widget is None:
            return None
        point = Graphene.Point()
        point.init(x, y)
        ok, out = widget.compute_point(target, point)
        if not ok or out is None:
            return None
        return (out.x, out.y)

    def _update(self, gesture, _dx: float, _dy: float) -> None:
        host = self.host
        if host._maxed or self._orig is None or self._ptr is None or host.frame is None:
            return
        cur = pointer_from_gesture(self._target(), gesture)
        if cur is None:
            return
        parent = host.frame.get_parent()
        pw = parent.get_width() if parent is not None else 1280
        ph = parent.get_height() if parent is not None else 800
        w = host.frame.get_width() or 1
        ox, oy = self._orig
        nx, ny = clamp_pos(
            ox + (cur[0] - self._ptr[0]),
            oy + (cur[1] - self._ptr[1]),
            w,
            pw,
            ph,
        )
        host._x, host._y = nx, ny
        host._move(nx, ny)

    def _end(self, *_args: object) -> None:
        self._orig = None
        self._ptr = None


class FloatLayer(Gtk.Fixed):
    __gtype_name__ = "FirstbootFloatLayer"

    def __init__(self) -> None:
        super().__init__()
        self.set_hexpand(True)
        self.set_vexpand(True)
        self.set_halign(Gtk.Align.FILL)
        self.set_valign(Gtk.Align.FILL)
        press = Gtk.GestureClick()
        press.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        press.set_button(1)
        press.connect("pressed", self._on_press)
        self.add_controller(press)

    def place(self, widget: Gtk.Widget, x: int, y: int) -> None:
        if widget.get_parent() is self:
            self.move(widget, x, y)
        else:
            self.put(widget, x, y)

    def raise_child(self, widget: Gtk.Widget) -> None:
        """Last sibling is painted on top."""
        if widget.get_parent() is not self:
            return
        if widget.get_next_sibling() is None:
            return
        widget.insert_before(self, None)

    def _on_press(self, _g, _n: int, x: float, y: float) -> None:
        child = self._child_at(x, y)
        if child is not None:
            self.raise_child(child)

    def do_contains(self, x: float, y: float) -> bool:
        return self._child_at(x, y) is not None

    def do_pick(self, x: float, y: float, flags: Gtk.PickFlags):
        for child in self._top_first():
            if child.get_visible() and child.get_can_target():
                local = self._to_child(child, x, y)
                if local is not None:
                    picked = child.pick(local[0], local[1], flags)
                    if picked is not None:
                        return picked
        return None

    def _child_at(self, x: float, y: float):
        for child in self._top_first():
            if child.get_visible():
                local = self._to_child(child, x, y)
                if local is not None and child.contains(local[0], local[1]):
                    return child
        return None

    def _top_first(self):
        child = self.get_last_child()
        while child is not None:
            yield child
            child = child.get_prev_sibling()

    def _to_child(self, child: Gtk.Widget, x: float, y: float):
        origin = Graphene.Point()
        origin.init(0.0, 0.0)
        ok, point = child.compute_point(self, origin)
        if not ok or point is None:
            return None
        return (x - point.x, y - point.y)
