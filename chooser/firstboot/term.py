"""In-kiosk VTE terminal. Support tool, not a desktop."""

from __future__ import annotations

import getpass
import os
import socket
from collections.abc import Callable
from typing import Any

VTE_API = "3.91"
TERM_WIDTH = 720
TERM_HEIGHT = 420
TERM_TOP = 40
FG = "#e8e6e3"
BG = "#1e1e1e"
CURSOR = "#3584e4"


def vte_available() -> bool:
    try:
        import gi

        gi.require_version("Vte", VTE_API)
        from gi.repository import Vte  # noqa: F401
    except (ImportError, ValueError):
        return False
    return True


def spawn_argv() -> list[str]:
    shell = os.environ.get("SHELL") or "/bin/bash"
    if not os.path.isfile(shell):
        shell = "/bin/bash"
    return [shell, "-l"]


def spawn_cwd() -> str:
    home = os.environ.get("HOME")
    if home and os.path.isdir(home):
        return home
    return "/"


def default_title() -> str:
    user = getpass.getuser() or "firstboot"
    host = socket.gethostname() or "firstboot"
    return f"{user}@{host}: ~"


class TermWindow:
    def __init__(
        self,
        *,
        get_window: Callable,
        on_toast: Callable[[str], None],
    ) -> None:
        self.get_window = get_window
        self.on_toast = on_toast
        self.frame = None
        self.vte = None
        self.title_lab = None
        self._close_img = None
        self._maxed = False
        self._alive = False
        self._placed = False
        self._x = 0
        self._y = TERM_TOP
        self._drag_orig: tuple[int, int] | None = None

    @property
    def visible(self) -> bool:
        return bool(self.frame is not None and self.frame.get_visible())

    def build(self):
        from gi.repository import Gdk, Gtk, Pango

        from firstboot.assets import find_app_icon, find_status, symbolic_pixbuf

        self.frame = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.frame.add_css_class("term-window")
        self.frame.set_halign(Gtk.Align.START)
        self.frame.set_valign(Gtk.Align.START)
        self.frame.set_size_request(TERM_WIDTH, TERM_HEIGHT)
        self.frame.set_visible(False)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        header.add_css_class("term-headerbar")
        header.set_hexpand(True)

        title_wrap = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        title_wrap.add_css_class("term-title-wrap")
        title_wrap.set_hexpand(True)
        icon = Gtk.Image()
        icon.set_pixel_size(18)
        path = find_app_icon("org.gnome.Terminal.png")
        if path:
            icon.set_from_file(path)
        title_wrap.append(icon)
        self.title_lab = Gtk.Label(label=default_title(), xalign=0)
        self.title_lab.add_css_class("term-title")
        self.title_lab.set_ellipsize(Pango.EllipsizeMode.END)
        self.title_lab.set_hexpand(True)
        title_wrap.append(self.title_lab)
        header.append(title_wrap)

        controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        controls.add_css_class("term-window-controls")
        max_btn = Gtk.Button()
        max_btn.add_css_class("term-wc")
        max_btn.add_css_class("term-max")
        max_btn.set_has_frame(False)
        max_btn.set_tooltip_text("Maximize")
        max_mark = Gtk.Box()
        max_mark.add_css_class("term-max-mark")
        max_mark.set_halign(Gtk.Align.CENTER)
        max_mark.set_valign(Gtk.Align.CENTER)
        max_btn.set_child(max_mark)
        max_btn.connect("clicked", lambda *_: self.toggle_max())
        close_btn = Gtk.Button()
        close_btn.add_css_class("term-wc")
        close_btn.add_css_class("term-close")
        close_btn.set_has_frame(False)
        close_btn.set_tooltip_text("Close")
        self._close_img = Gtk.Image()
        self._close_img.set_pixel_size(14)
        close_path = find_status("window-close-symbolic.svg")
        if close_path:
            pb = symbolic_pixbuf(close_path, "#f6f5f4", 14)
            if pb is not None:
                self._close_img.set_from_paintable(Gdk.Texture.new_for_pixbuf(pb))
            else:
                self._close_img.set_from_file(close_path)
        close_btn.set_child(self._close_img)
        close_btn.connect("clicked", lambda *_: self.close())
        controls.append(max_btn)
        controls.append(close_btn)
        header.append(controls)
        self.frame.append(header)

        drag = Gtk.GestureDrag()
        drag.connect("drag-begin", self._on_drag_begin)
        drag.connect("drag-update", self._on_drag_update)
        drag.connect("drag-end", lambda *_: setattr(self, "_drag_orig", None))
        header.add_controller(drag)
        dbl = Gtk.GestureClick()
        dbl.connect("pressed", self._on_header_press)
        header.add_controller(dbl)

        if vte_available():
            import gi

            gi.require_version("Vte", VTE_API)
            from gi.repository import Vte

            self.vte = Vte.Terminal()
            self.vte.add_css_class("term-body")
            self.vte.set_hexpand(True)
            self.vte.set_vexpand(True)
            self.vte.set_scrollback_lines(10000)
            self.vte.set_audible_bell(False)
            self.vte.set_mouse_autohide(True)
            self.vte.set_font(Pango.FontDescription.from_string("DejaVu Sans Mono 11"))
            fg, bg, cur = Gdk.RGBA(), Gdk.RGBA(), Gdk.RGBA()
            fg.parse(FG)
            bg.parse(BG)
            cur.parse(CURSOR)
            self.vte.set_color_foreground(fg)
            self.vte.set_color_background(bg)
            self.vte.set_color_cursor(cur)
            self.vte.connect("window-title-changed", self._on_title)
            self.vte.connect("child-exited", self._on_child_exited)
            self.frame.append(self.vte)
        else:
            miss = Gtk.Label(label="Terminal is not on this image yet.")
            miss.add_css_class("term-missing")
            miss.set_hexpand(True)
            miss.set_vexpand(True)
            miss.set_valign(Gtk.Align.CENTER)
            self.frame.append(miss)
        return self.frame

    def open(self) -> None:
        if self.frame is None:
            return
        if not self._placed:
            self._place_default()
            self._placed = True
        self.frame.set_visible(True)
        if self.vte is not None and not self._alive:
            self._spawn()
        self._focus()

    def close(self) -> None:
        if self.frame is None:
            return
        self.frame.set_visible(False)

    def toggle_max(self) -> None:
        from gi.repository import Gtk

        if self.frame is None:
            return
        self._maxed = not self._maxed
        if self._maxed:
            self.frame.add_css_class("maximized")
            self.frame.set_halign(Gtk.Align.FILL)
            self.frame.set_valign(Gtk.Align.FILL)
            self.frame.set_hexpand(True)
            self.frame.set_vexpand(True)
            self.frame.set_size_request(-1, -1)
            self.frame.set_margin_start(0)
            self.frame.set_margin_end(0)
            self.frame.set_margin_top(0)
            self.frame.set_margin_bottom(0)
        else:
            self.frame.remove_css_class("maximized")
            self.frame.set_halign(Gtk.Align.START)
            self.frame.set_valign(Gtk.Align.START)
            self.frame.set_hexpand(False)
            self.frame.set_vexpand(False)
            self.frame.set_size_request(TERM_WIDTH, TERM_HEIGHT)
            self.frame.set_margin_start(self._x)
            self.frame.set_margin_top(self._y)
        self._focus()

    def apply_theme(self, dark: bool) -> None:
        from gi.repository import Gdk

        from firstboot.assets import find_status, symbolic_pixbuf

        if self._close_img is None:
            return
        path = find_status("window-close-symbolic.svg")
        if not path:
            return
        color = "#f6f5f4" if dark else "#1c1c1c"
        pb = symbolic_pixbuf(path, color, 14)
        if pb is not None:
            self._close_img.set_from_paintable(Gdk.Texture.new_for_pixbuf(pb))

    def _place_default(self) -> None:
        parent = self.frame.get_parent() if self.frame is not None else None
        pw = parent.get_width() if parent is not None else 0
        if pw <= 0:
            win = self.get_window()
            pw = win.get_width() if win is not None else 0
        if pw <= 0:
            pw = 1280
        self._x = max(24, (pw - TERM_WIDTH) // 2)
        self._y = TERM_TOP
        self.frame.set_margin_start(self._x)
        self.frame.set_margin_top(self._y)

    def _focus(self) -> None:
        if self.vte is not None:
            self.vte.grab_focus()

    def _spawn(self) -> None:
        from gi.repository import GLib, Vte

        if self.vte is None:
            return

        def done(
            _term: Any,
            _pid: int,
            error: GLib.Error | None,
            *_rest: Any,
        ) -> None:
            if error is not None:
                self._alive = False
                self.on_toast(error.message)
                return
            self._alive = True

        self.vte.spawn_async(
            Vte.PtyFlags.DEFAULT,
            spawn_cwd(),
            spawn_argv(),
            None,
            GLib.SpawnFlags.DEFAULT,
            None,
            None,
            -1,
            None,
            done,
        )

    def _on_title(self, term) -> None:
        if self.title_lab is None:
            return
        title = term.get_window_title() or default_title()
        self.title_lab.set_label(title)

    def _on_child_exited(self, *_args: object) -> None:
        self._alive = False
        self.close()

    def _on_header_press(self, _g, n_press: int, *_xy) -> None:
        if n_press == 2:
            self.toggle_max()

    def _on_drag_begin(self, *_args: object) -> None:
        if self._maxed or self.frame is None:
            self._drag_orig = None
            return
        self._drag_orig = (self.frame.get_margin_start(), self.frame.get_margin_top())

    def _on_drag_update(self, _g, dx: float, dy: float) -> None:
        if self._maxed or self._drag_orig is None or self.frame is None:
            return
        parent = self.frame.get_parent()
        pw = parent.get_width() if parent is not None else 1280
        ph = parent.get_height() if parent is not None else 800
        w = self.frame.get_width() or TERM_WIDTH
        ox, oy = self._drag_orig
        nx = max(-w + 80, min(pw - 80, ox + int(dx)))
        ny = max(0, min(ph - 40, oy + int(dy)))
        self._x, self._y = nx, ny
        self.frame.set_margin_start(nx)
        self.frame.set_margin_top(ny)
