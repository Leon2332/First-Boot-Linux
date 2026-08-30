"""GNOME-like kiosk chrome: top bar, quick settings, network, power.

Web browser, System details, and Terminal open as separate windows.
"""

from __future__ import annotations

import datetime as dt
import sys
import threading
import time
from collections.abc import Callable
from typing import TYPE_CHECKING

from firstboot.assets import (
    find_app_icon,
    find_status,
    symbolic_pixbuf,
    symbolic_pixbuf_from_svg,
)
from firstboot.battery import BatteryState, battery_svg, read_battery
from firstboot.net import (
    WIFI_LIST_LIMIT,
    NmError,
    NetSnapshot,
    WifiAP,
    connect_ethernet,
    connect_wifi,
    disconnect_device,
    empty_snapshot,
    ethernet_detail,
    forget_wifi,
    request_scan,
    set_wifi_radio,
    snapshot,
    uuid_for_ssid,
    wifi_row_actions,
)
from firstboot.brightness import BrightnessState, get_brightness_backend
from firstboot.timezone import (
    TZ_MINUTES_MAX,
    TZ_MINUTES_MIN,
    TZ_MINUTES_STEP,
    apply_tz_minutes,
    clock_in_offset,
    current_tz_minutes,
    format_tz_offset,
    load_timezone_minutes,
    persist_timezone,
    snap_tz_minutes,
)
from firstboot.volume import MemoryVolume, Volume, VolumeState, get_volume_backend
from firstboot.i18n import (
    DEFAULT_LANGUAGE,
    _,
    language_matches,
    persist_language,
    supported_languages,
)

if TYPE_CHECKING:
    from gi.repository import Gtk

PANEL_FG = "#f6f5f4"
QS_FG = "#f6f5f4"
QS_FG_LIGHT = "#1c1c1c"
QS_FG_ACTIVE = "#ffffff"
TOPBAR_HEIGHT = 32

APP_ITEMS = (
    ("epiphany.png", "Web browser", "browser"),
    ("cog", "System details", "sysinfo"),
    ("org.gnome.Terminal.png", "Terminal", "terminal"),
)


def app_items() -> tuple[tuple[str, str, str], ...]:
    return tuple((icon, _(label), action) for icon, label, action in APP_ITEMS)


APP_TOASTS: dict[str, str] = {}
QS_MENUS = frozenset({"qs", "network", "power", "language"})


def format_clock(now: dt.datetime) -> str:
    return now.strftime("%-d %b %H:%M")


def _texture(path: str, color: str, size: int):
    from gi.repository import Gdk

    pb = symbolic_pixbuf(path, color, size)
    if pb is None:
        return None
    return Gdk.Texture.new_for_pixbuf(pb)


def set_symbolic(image: Gtk.Image, name: str, color: str, size: int = 16) -> None:
    path = find_status(name)
    if not path:
        return
    tex = _texture(path, color, size)
    if tex is not None:
        image.set_from_paintable(tex)
    else:
        image.set_from_file(path)
    image.set_pixel_size(size)


def set_symbolic_svg(image: Gtk.Image, svg: str, color: str, size: int = 16) -> None:
    from gi.repository import Gdk

    pb = symbolic_pixbuf_from_svg(svg, color, size)
    if pb is None:
        return
    image.set_from_paintable(Gdk.Texture.new_for_pixbuf(pb))
    image.set_pixel_size(size)


class _WifiRow:
    def __init__(self, shell: Shell, ap: WifiAP, saved: bool) -> None:
        from gi.repository import Gtk, Pango

        self.shell = shell
        self.ssid = ap.ssid
        self.ap = ap
        self.saved = saved
        self.expanded = False
        self._revealed = False
        self._icon_color: str | None = None
        self.entry = None
        self.unhide = None
        self.forget_btn = None
        self.connect_btn = None
        self.expand = None
        self.password_wrap = None
        self.actions = None

        self.root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.root.add_css_class("wifi-row")

        self.header = Gtk.Button()
        self.header.add_css_class("wifi-item")
        self.header.set_has_frame(False)
        self.header.set_hexpand(True)
        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.icon = Gtk.Image()
        self.icon.set_pixel_size(16)
        left = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        left.set_hexpand(True)
        left.append(self.icon)
        self.ssid_lab = Gtk.Label(label=ap.ssid, xalign=0)
        self.ssid_lab.add_css_class("wifi-ssid")
        self.ssid_lab.set_ellipsize(Pango.EllipsizeMode.END)
        self.ssid_lab.set_hexpand(True)
        left.append(self.ssid_lab)
        self.meta = Gtk.Label(label="", xalign=1)
        self.meta.add_css_class("wifi-meta")
        head.append(left)
        head.append(self.meta)
        self.header.set_child(head)
        self.header.connect("clicked", lambda *_: self.shell._toggle_wifi(self.ssid))
        self.root.append(self.header)
        self.update(ap, saved, shell._busy)

    def update(self, ap: WifiAP, saved: bool, busy: bool) -> None:
        self.ap = ap
        self.saved = saved
        if ap.in_use:
            self.root.add_css_class("active")
            self.header.add_css_class("active")
            self.meta.set_label(_("Connected"))
        else:
            self.root.remove_css_class("active")
            self.header.remove_css_class("active")
            self.meta.set_label("")
        color = self.shell._fg(active=ap.in_use)
        if color != self._icon_color:
            set_symbolic(
                self.icon,
                "network-wireless-signal-excellent-symbolic.svg",
                color,
                16,
            )
            self._icon_color = color
        self.header.set_sensitive(not busy)
        self._sync_expand(busy)

    def password(self) -> str:
        if self.entry is None:
            return ""
        return self.entry.get_text()

    def set_expanded(self, expanded: bool) -> None:
        if expanded == self.expanded:
            if expanded and self.entry is not None:
                self.entry.grab_focus()
            return
        self.expanded = expanded
        if expanded:
            self.root.add_css_class("expanded")
            self._ensure_expand()
            if self.expand is not None:
                self.expand.set_visible(True)
            self._sync_expand(self.shell._busy)
            if self.entry is not None:
                self.entry.grab_focus()
        else:
            self.hide_password()
            self.root.remove_css_class("expanded")
            if self.expand is not None:
                self.expand.set_visible(False)

    def hide_password(self) -> None:
        self._revealed = False
        if self.entry is not None:
            self.entry.set_visibility(False)
        if self.unhide is not None:
            self.unhide.set_label(_("Unhide"))

    def _ensure_expand(self) -> None:
        from gi.repository import Gtk

        if self.expand is not None:
            return
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.add_css_class("wifi-expand")

        wrap = Gtk.Overlay()
        wrap.add_css_class("wifi-password-field")
        entry = Gtk.Entry()
        entry.add_css_class("wifi-password")
        entry.set_placeholder_text(_("Password"))
        entry.set_visibility(False)
        entry.set_hexpand(True)
        entry.set_input_purpose(Gtk.InputPurpose.PASSWORD)
        entry.set_input_hints(Gtk.InputHints.PRIVATE)
        entry.connect("activate", lambda *_: self.shell._connect_wifi_row(self))
        unhide = Gtk.Button(label=_("Unhide"))
        unhide.add_css_class("wifi-unhide")
        unhide.set_has_frame(False)
        unhide.set_focus_on_click(False)
        unhide.set_halign(Gtk.Align.END)
        unhide.set_valign(Gtk.Align.CENTER)
        unhide.set_margin_end(4)
        unhide.connect("clicked", lambda *_: self._toggle_reveal())
        wrap.set_child(entry)
        wrap.add_overlay(unhide)
        box.append(wrap)

        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        actions.add_css_class("wifi-expand-actions")
        forget = Gtk.Button(label=_("Forget"))
        forget.add_css_class("btn-pill")
        forget.add_css_class("wifi-forget")
        forget.set_has_frame(False)
        forget.connect("clicked", lambda *_: self.shell._forget_wifi_row(self))
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        connect = Gtk.Button(label=_("Connect"))
        connect.add_css_class("btn-pill")
        connect.add_css_class("wifi-connect")
        connect.set_has_frame(False)
        connect.connect("clicked", lambda *_: self.shell._connect_wifi_row(self))
        actions.append(forget)
        actions.append(spacer)
        actions.append(connect)
        box.append(actions)

        self.entry = entry
        self.unhide = unhide
        self.forget_btn = forget
        self.connect_btn = connect
        self.password_wrap = wrap
        self.actions = actions
        self.expand = box
        self.root.append(box)

    def _toggle_reveal(self) -> None:
        if self.entry is None or self.unhide is None:
            return
        self._revealed = not self._revealed
        self.entry.set_visibility(self._revealed)
        self.unhide.set_label(_("Hide") if self._revealed else _("Unhide"))

    def _sync_expand(self, busy: bool) -> None:
        if self.expand is None:
            return
        show_password, show_connect, show_forget = wifi_row_actions(
            secure=not self.ap.open,
            in_use=self.ap.in_use,
            saved=self.saved,
        )
        if self.password_wrap is not None:
            self.password_wrap.set_visible(show_password)
        if self.forget_btn is not None:
            self.forget_btn.set_visible(show_forget)
            self.forget_btn.set_sensitive(not busy)
        if self.connect_btn is not None:
            self.connect_btn.set_visible(show_connect)
            self.connect_btn.set_sensitive(not busy)
            self.connect_btn.set_label(
                _("Connecting…") if busy and show_connect else _("Connect")
            )
        if self.unhide is not None:
            self.unhide.set_sensitive(not busy)
        if self.entry is not None:
            self.entry.set_sensitive(not busy)
        self.expand.set_visible(self.expanded)


class Shell:
    def __init__(
        self,
        *,
        on_theme: Callable[[bool], None],
        on_toast: Callable[[str], None],
        on_power: Callable[[str], None],
        get_window: Callable,
        on_shop_install: Callable[[], None] | None = None,
        on_terminal: Callable[[], None] | None = None,
        on_sysinfo: Callable[[], None] | None = None,
        on_browser: Callable[[], None] | None = None,
        show_shop_install: bool = False,
        language: str = DEFAULT_LANGUAGE,
        payload_root: str | None = None,
        on_language: Callable[[str], None] | None = None,
        retailer_timezone: str | None = None,
    ) -> None:
        self.on_theme = on_theme
        self.on_toast = on_toast
        self.on_power = on_power
        self.get_window = get_window
        self.on_shop_install = on_shop_install
        self.on_terminal = on_terminal
        self.on_sysinfo = on_sysinfo
        self.on_browser = on_browser
        self.on_language = on_language
        self.on_menu_changed: Callable[[str | None], None] | None = None
        self.show_shop_install = show_shop_install
        self.language = language
        self.payload_root = payload_root
        self._lang_query = ""
        self._lang_rows: list = []
        self._app_labels: dict[str, object] = {}
        self.dark = True
        self.volume: Volume = MemoryVolume()
        self._vol_gen = 0
        self.brightness = get_brightness_backend()
        self.battery = BatteryState()
        self.net: NetSnapshot = empty_snapshot()
        self.open_menu: str | None = None
        self.allow_scan = True
        self.locked = False
        self._busy = False
        self._built = False
        self._app_download = None
        self._wifi_rows: dict[str, _WifiRow] = {}
        self._wifi_mode: str | None = None
        self._wifi_expanded: str | None = None
        self._net_inflight = False
        self._net_again = False
        self._net_again_scan = False
        self._net_gen = 0
        self.qs_popover = None
        self.app_popover = None
        self.clock_popover = None
        self.qs_stack = None
        loaded_tz = load_timezone_minutes(payload_root or "", retailer_timezone)
        if loaded_tz is not None:
            self.tz_minutes = loaded_tz
            apply_tz_minutes(loaded_tz)
        else:
            self.tz_minutes = current_tz_minutes()
        self._tz_apply_id = 0
        self._ignore_popover_closed = False
        self._popover_closed_at = 0.0
        self._popover_closed_which: str | None = None
        self._app_running_dots: dict[str, object] = {}
        self._app_running: dict[str, bool] = {}

    def build(self) -> tuple[Gtk.Widget, list[Gtk.Widget]]:
        from gi.repository import Gtk

        self.topbar = self._build_topbar()
        self.backdrop = Gtk.Box()
        self.backdrop.set_hexpand(True)
        self.backdrop.set_vexpand(True)
        self.backdrop.set_halign(Gtk.Align.FILL)
        self.backdrop.set_valign(Gtk.Align.FILL)
        self.backdrop.set_visible(False)
        click = Gtk.GestureClick()
        click.connect("pressed", lambda *_: self.close_menus())
        self.backdrop.add_controller(click)

        self.qs = self._build_qs()
        self.net_panel = self._build_network()
        self.lang_panel = self._build_language()
        self.power_menu = self._build_power()
        self.app_menu = self._build_apps()
        self.clock_panel = self._build_clock()
        for panel in (
            self.qs,
            self.net_panel,
            self.lang_panel,
            self.power_menu,
            self.app_menu,
            self.clock_panel,
        ):
            panel.set_visible(False)
        self._built = True
        try:
            self.net = snapshot()
        except Exception:
            self.net = empty_snapshot(available=False)
        self._paint_net()
        self.refresh_volume()
        self.refresh_battery()
        self.refresh_icons()
        return self.topbar, [
            self.backdrop,
            self.qs,
            self.net_panel,
            self.lang_panel,
            self.power_menu,
            self.app_menu,
            self.clock_panel,
        ]

    def apply_theme(self, dark: bool) -> None:
        self.dark = dark
        if self.dark_btn.get_active() != dark:
            self.dark_btn.handler_block_by_func(self._on_dark)
            self.dark_btn.set_active(dark)
            self.dark_btn.handler_unblock_by_func(self._on_dark)
        if dark:
            self.dark_btn.add_css_class("active")
        else:
            self.dark_btn.remove_css_class("active")
        self.refresh_icons()

    def tick_clock(self) -> bool:
        self.clock.set_label(format_clock(clock_in_offset(self.tz_minutes)))
        self.refresh_battery()
        return True

    def refresh_net(self) -> bool:
        self._request_net(scan=False)
        return True

    def _request_net(self, *, scan: bool = False) -> None:
        if self._wifi_expanded:
            scan = False
        if self._net_inflight:
            self._net_again = True
            self._net_again_scan = self._net_again_scan or scan
            return
        self._net_inflight = True
        self._net_gen += 1
        gen = self._net_gen
        do_scan = scan

        def work() -> None:
            from gi.repository import GLib

            try:
                if do_scan:
                    request_scan()
                snap = snapshot()
            except Exception:
                snap = empty_snapshot(available=False)
            GLib.idle_add(self._apply_net, gen, snap)

        threading.Thread(target=work, daemon=True).start()

    def _apply_net(self, gen: int, snap: NetSnapshot) -> bool:
        if gen != self._net_gen:
            return False
        self._net_inflight = False
        self.net = snap
        self._paint_net()
        if self._net_again:
            again_scan = self._net_again_scan
            self._net_again = False
            self._net_again_scan = False
            self._request_net(scan=again_scan)
        return False

    def refresh_volume(self) -> bool:
        self._vol_gen += 1
        gen = self._vol_gen

        def work() -> None:
            from gi.repository import GLib

            backend = self.volume
            if isinstance(backend, MemoryVolume):
                backend = get_volume_backend()
            try:
                st = backend.get()
            except Exception:
                return
            GLib.idle_add(self._apply_volume, gen, backend, st)

        threading.Thread(target=work, daemon=True).start()
        return True

    def _apply_volume(self, gen: int, backend: Volume, st: VolumeState) -> bool:
        if gen != self._vol_gen:
            return False
        self.volume = backend
        self._paint_volume(st)
        return False

    def set_app_running(self, action: str, running: bool) -> None:
        self._app_running[action] = running
        dot = self._app_running_dots.get(action)
        if dot is not None:
            dot.set_opacity(1.0 if running else 0.0)

    def refresh_brightness(self) -> bool:
        try:
            self._paint_brightness(self.brightness.get())
        except Exception:
            pass
        return True

    def refresh_battery(self) -> bool:
        try:
            self.battery = read_battery()
        except Exception:
            self.battery = BatteryState()
        self._paint_battery()
        return True

    def handle_key(self, keyval: int) -> bool:
        from gi.repository import Gdk

        if keyval != Gdk.KEY_Escape or self.open_menu is None:
            return False
        if self.open_menu in {"network", "language", "power"}:
            self.show_menu("qs")
        else:
            self.close_menus()
        return True

    def show_menu(self, name: str | None) -> None:
        if self.locked and name is not None:
            return
        if name is not None and self.app_popover is not None:
            if name == "apps":
                which = "apps"
            elif name == "clock":
                which = "clock"
            elif name in QS_MENUS:
                which = "qs"
            else:
                which = None
            if (
                which is not None
                and which == self._popover_closed_which
                and (time.monotonic() - self._popover_closed_at) < 0.25
            ):
                self._popover_closed_which = None
                return
        if name == self.open_menu:
            self.close_menus()
            return
        if name not in {"network", "qs", "language"}:
            self._set_expanded(None)
        self.open_menu = name
        if self.app_popover is not None:
            self._sync_panel_popovers(name)
        else:
            self.backdrop.set_visible(name is not None)
            self.qs.set_visible(name == "qs")
            self.net_panel.set_visible(name == "network")
            self.lang_panel.set_visible(name == "language")
            self.power_menu.set_visible(name == "power")
            self.app_menu.set_visible(name == "apps")
            self.clock_panel.set_visible(name == "clock")
        if name == "qs":
            self.sys_btn.add_css_class("open")
        else:
            self.sys_btn.remove_css_class("open")
        if name == "apps":
            self.app_btn.add_css_class("open")
        else:
            self.app_btn.remove_css_class("open")
        if name == "clock":
            self.clock_btn.add_css_class("open")
            self._paint_tz()
            self.clock_panel.grab_focus()
        else:
            self.clock_btn.remove_css_class("open")
        if name == "network":
            if self.allow_scan:
                self._request_net(scan=not self._wifi_expanded)
        if name == "language":
            self._reset_language_search()
            self._render_languages()
            if getattr(self, "lang_search", None) is not None:
                self.lang_search.grab_focus()
        if name == "qs":
            self.refresh_volume()
            self.refresh_brightness()
            self.refresh_battery()
            if self.allow_scan:
                self._request_net(scan=False)
        if name is not None:
            print(f"firstboot-chooser: menu {name}", file=sys.stderr, flush=True)
        if self.on_menu_changed is not None:
            self.on_menu_changed(self.open_menu)

    def enable_panel_popovers(self) -> None:
        from gi.repository import Gtk

        if self.app_popover is not None:
            return
        for panel in (
            self.qs,
            self.net_panel,
            self.lang_panel,
            self.power_menu,
            self.app_menu,
            self.clock_panel,
        ):
            panel.set_visible(True)
            panel.set_margin_top(0)
            panel.set_margin_end(0)
            panel.set_margin_start(0)
            panel.set_halign(Gtk.Align.FILL)
            panel.set_valign(Gtk.Align.FILL)

        self.qs_stack = Gtk.Stack()
        self.qs_stack.set_interpolate_size(True)
        self.qs_stack.set_vhomogeneous(False)
        self.qs_stack.add_named(self.qs, "qs")
        self.qs_stack.add_named(self.net_panel, "network")
        self.qs_stack.add_named(self.lang_panel, "language")
        self.qs_stack.add_named(self.power_menu, "power")

        self.qs_popover = self._make_popover(self.qs_stack, self.sys_btn)
        self.app_popover = self._make_popover(self.app_menu, self.app_btn)
        self.clock_popover = self._make_popover(self.clock_panel, self.clock_btn)
        self.qs_popover.connect("closed", self._on_popover_closed)
        self.app_popover.connect("closed", self._on_popover_closed)
        self.clock_popover.connect("closed", self._on_popover_closed)

    def _make_popover(self, child, parent):
        from gi.repository import Gtk

        pop = Gtk.Popover()
        pop.add_css_class("shell-popover")
        pop.set_autohide(True)
        pop.set_has_arrow(False)
        pop.set_position(Gtk.PositionType.BOTTOM)
        pop.set_offset(0, 8)
        pop.set_child(child)
        pop.set_parent(parent)
        return pop

    def _sync_panel_popovers(self, name: str | None) -> None:
        self._ignore_popover_closed = True
        try:
            if name == "apps":
                self.qs_popover.popdown()
                self.clock_popover.popdown()
                self.app_popover.popup()
            elif name == "clock":
                self.qs_popover.popdown()
                self.app_popover.popdown()
                self.clock_popover.popup()
            elif name in QS_MENUS:
                self.app_popover.popdown()
                self.clock_popover.popdown()
                self.qs_stack.set_visible_child_name(name)
                self.qs_popover.popup()
            else:
                self.app_popover.popdown()
                self.qs_popover.popdown()
                self.clock_popover.popdown()
        finally:
            self._ignore_popover_closed = False

    def _on_popover_closed(self, pop) -> None:
        if self._ignore_popover_closed:
            return
        if pop is self.app_popover:
            which = "apps"
        elif pop is self.clock_popover:
            which = "clock"
        else:
            which = "qs"
        self._popover_closed_at = time.monotonic()
        self._popover_closed_which = which
        if which == "apps" and self.open_menu == "apps":
            self.open_menu = None
            self.app_btn.remove_css_class("open")
        elif which == "clock" and self.open_menu == "clock":
            self.open_menu = None
            self.clock_btn.remove_css_class("open")
        elif which == "qs" and self.open_menu in QS_MENUS:
            self.open_menu = None
            self.sys_btn.remove_css_class("open")

    def close_menus(self) -> None:
        if self.open_menu is None:
            return
        self.show_menu(None)

    def _fg(self, *, active: bool = False) -> str:
        if active:
            return QS_FG_ACTIVE
        return QS_FG if self.dark else QS_FG_LIGHT

    def _build_topbar(self) -> Gtk.Widget:
        from gi.repository import Gtk

        bar = Gtk.CenterBox()
        bar.add_css_class("top-bar")
        bar.set_hexpand(True)
        bar.set_size_request(-1, TOPBAR_HEIGHT)
        bar.set_valign(Gtk.Align.FILL)

        self.app_btn = Gtk.Button()
        self.app_btn.add_css_class("panel-btn")
        self.app_btn.set_tooltip_text(_("Applications"))
        self.app_btn.set_has_frame(False)
        self.app_grid_img = Gtk.Image()
        self.app_btn.set_child(self.app_grid_img)
        self.app_btn.connect("clicked", lambda *_: self.show_menu("apps"))
        left = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        left.set_valign(Gtk.Align.CENTER)
        left.append(self.app_btn)
        bar.set_start_widget(left)

        self.clock_btn = Gtk.Button()
        self.clock_btn.add_css_class("panel-btn")
        self.clock_btn.set_tooltip_text(_("Date and time"))
        self.clock_btn.set_has_frame(False)
        self.clock = Gtk.Label(label="—")
        self.clock.add_css_class("clock")
        self.clock_btn.set_child(self.clock)
        self.clock_btn.connect("clicked", lambda *_: self.show_menu("clock"))
        bar.set_center_widget(self.clock_btn)

        self.sys_btn = Gtk.Button()
        self.sys_btn.add_css_class("panel-btn")
        self.sys_btn.set_tooltip_text(_("System menu"))
        self.sys_btn.set_has_frame(False)
        icons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        icons.add_css_class("panel-icons")
        self.net_img = Gtk.Image()
        self.vol_img = Gtk.Image()
        self.pwr_img = Gtk.Image()
        self.bat_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self.bat_box.add_css_class("panel-bat")
        self.bat_img = Gtk.Image()
        self.bat_img.set_pixel_size(16)
        self.bat_pct = Gtk.Label(label="")
        self.bat_pct.add_css_class("panel-bat-pct")
        self.bat_box.append(self.bat_img)
        self.bat_box.append(self.bat_pct)
        self.bat_box.set_visible(False)
        for img in (self.net_img, self.vol_img):
            img.set_pixel_size(16)
            icons.append(img)
        icons.append(self.bat_box)
        self.pwr_img.set_pixel_size(16)
        icons.append(self.pwr_img)
        self.sys_btn.set_child(icons)
        self.sys_btn.connect("clicked", lambda *_: self.show_menu("qs"))
        right = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        right.set_halign(Gtk.Align.END)
        right.set_valign(Gtk.Align.CENTER)
        right.append(self.sys_btn)
        bar.set_end_widget(right)
        return bar

    def _build_clock(self) -> Gtk.Widget:
        from gi.repository import Gdk, Gtk

        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        panel.add_css_class("shell-panel")
        panel.add_css_class("clock-menu")
        panel.set_halign(Gtk.Align.CENTER)
        panel.set_valign(Gtk.Align.START)
        panel.set_margin_top(40)
        panel.set_focusable(True)
        steal = Gtk.GestureClick()
        steal.connect("pressed", lambda *a: True)
        panel.add_controller(steal)

        spin = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        spin.add_css_class("tz-spin")
        self.tz_value = Gtk.Label(label=format_tz_offset(self.tz_minutes))
        self.tz_value.add_css_class("tz-spin-value")
        self.tz_value.set_hexpand(True)
        self.tz_value.set_xalign(0.5)
        btns = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        btns.add_css_class("tz-spin-btns")
        self.tz_up = Gtk.Button()
        self.tz_down = Gtk.Button()
        self.tz_up_img = Gtk.Image()
        self.tz_down_img = Gtk.Image()
        self.tz_up.set_child(self.tz_up_img)
        self.tz_down.set_child(self.tz_down_img)
        self.tz_up.add_css_class("tz-spin-btn")
        self.tz_down.add_css_class("tz-spin-btn")
        self.tz_up.set_has_frame(False)
        self.tz_down.set_has_frame(False)
        self.tz_up.set_tooltip_text(_("Later time zone"))
        self.tz_down.set_tooltip_text(_("Earlier time zone"))
        self.tz_up.connect("clicked", lambda *_: self._nudge_tz(TZ_MINUTES_STEP))
        self.tz_down.connect("clicked", lambda *_: self._nudge_tz(-TZ_MINUTES_STEP))
        btns.append(self.tz_up)
        btns.append(self.tz_down)
        spin.append(self.tz_value)
        spin.append(btns)
        panel.append(spin)

        key = Gtk.EventControllerKey()

        def on_key(_c, keyval: int, *_a: object) -> bool:
            if keyval in (Gdk.KEY_Up, Gdk.KEY_Page_Up):
                self._nudge_tz(TZ_MINUTES_STEP)
                return True
            if keyval in (Gdk.KEY_Down, Gdk.KEY_Page_Down):
                self._nudge_tz(-TZ_MINUTES_STEP)
                return True
            return False

        key.connect("key-pressed", on_key)
        panel.add_controller(key)
        self._paint_tz()
        return panel

    def _nudge_tz(self, delta: int) -> None:
        self._set_tz_minutes(self.tz_minutes + delta)

    def _set_tz_minutes(self, minutes: int) -> None:
        minutes = snap_tz_minutes(minutes)
        if minutes == self.tz_minutes:
            self._paint_tz()
            return
        self.tz_minutes = minutes
        self._paint_tz()
        self.tick_clock()
        if self.payload_root:
            persist_timezone(self.payload_root, minutes)
        self._schedule_apply_tz()

    def _paint_tz(self) -> None:
        if not getattr(self, "tz_value", None):
            return
        self.tz_value.set_label(format_tz_offset(self.tz_minutes))
        self.tz_up.set_sensitive(self.tz_minutes < TZ_MINUTES_MAX)
        self.tz_down.set_sensitive(self.tz_minutes > TZ_MINUTES_MIN)
        self._paint_tz_carets()

    def _paint_tz_carets(self) -> None:
        if not getattr(self, "tz_up_img", None):
            return
        path = find_status("go-next-symbolic.svg")
        if not path:
            return
        from gi.repository import Gdk, GdkPixbuf

        pb = symbolic_pixbuf(path, self._fg(), 12)
        if pb is None:
            self.tz_up_img.set_from_file(path)
            self.tz_down_img.set_from_file(path)
            return
        up = pb.rotate_simple(GdkPixbuf.PixbufRotation.COUNTERCLOCKWISE)
        down = pb.rotate_simple(GdkPixbuf.PixbufRotation.CLOCKWISE)
        if up is not None:
            self.tz_up_img.set_from_paintable(Gdk.Texture.new_for_pixbuf(up))
        if down is not None:
            self.tz_down_img.set_from_paintable(Gdk.Texture.new_for_pixbuf(down))
        self.tz_up_img.set_pixel_size(12)
        self.tz_down_img.set_pixel_size(12)

    def _schedule_apply_tz(self) -> None:
        from gi.repository import GLib

        self._tz_apply_id += 1
        token = self._tz_apply_id

        def run() -> bool:
            if token != self._tz_apply_id:
                return False
            apply_tz_minutes(self.tz_minutes)
            return False

        GLib.timeout_add(250, run)

    def _build_qs(self) -> Gtk.Widget:
        from gi.repository import Gtk

        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        panel.add_css_class("shell-panel")
        panel.set_halign(Gtk.Align.END)
        panel.set_valign(Gtk.Align.START)
        panel.set_margin_top(40)
        panel.set_margin_end(10)
        panel.set_size_request(380, -1)
        steal = Gtk.GestureClick()
        steal.connect("pressed", lambda *a: True)
        panel.add_controller(steal)

        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        toolbar.add_css_class("qs-toolbar")
        toolbar.set_hexpand(True)
        self.lang_btn = Gtk.Button()
        self.lang_btn.add_css_class("qs-round")
        self.lang_btn.set_has_frame(False)
        self.lang_btn.set_size_request(40, 40)
        self.lang_btn.set_tooltip_text(_("Language"))
        self.lang_btn_img = Gtk.Image()
        self.lang_btn.set_child(self.lang_btn_img)
        self.lang_btn.connect("clicked", lambda *_: self.show_menu("language"))
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        self.power_btn = Gtk.Button()
        self.power_btn.add_css_class("qs-round")
        self.power_btn.set_has_frame(False)
        self.power_btn.set_size_request(40, 40)
        self.power_btn.set_tooltip_text(_("Power Off"))
        self.power_btn_img = Gtk.Image()
        self.power_btn.set_child(self.power_btn_img)
        self.power_btn.connect("clicked", lambda *_: self.show_menu("power"))
        toolbar.append(self.lang_btn)
        toolbar.append(spacer)
        toolbar.append(self.power_btn)
        panel.append(toolbar)

        grid = Gtk.Grid()
        grid.set_column_homogeneous(True)
        grid.set_column_spacing(10)
        grid.set_hexpand(True)

        (
            self.net_toggle,
            self.qs_net_img,
            self.qs_net_label,
            self.qs_net_sub,
            self.qs_net_chev,
        ) = self._qs_tile(sub="Not connected", chevron=True)
        self.qs_net_label.set_label(_("Network"))
        self.net_toggle.connect("clicked", lambda *_: self.show_menu("network"))
        grid.attach(self.net_toggle, 0, 0, 1, 1)

        self.dark_btn, self.dark_img, self.dark_lab, _sub, _chev = self._qs_tile(
            toggle=True
        )
        self.dark_lab.set_label(_("Dark Style"))
        self.dark_btn.add_css_class("active")
        self.dark_btn.set_active(True)
        self.dark_btn.connect("toggled", self._on_dark)
        grid.attach(self.dark_btn, 1, 0, 1, 1)
        panel.append(grid)

        slider_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.mute_btn = Gtk.Button()
        self.mute_btn.add_css_class("qs-slider-icon")
        self.mute_btn.set_has_frame(False)
        self.qs_vol_img = Gtk.Image()
        self.mute_btn.set_child(self.qs_vol_img)
        self.mute_btn.connect("clicked", lambda *_: self._toggle_mute())
        self.vol_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        self.vol_scale.add_css_class("qs-slider")
        self.vol_scale.set_draw_value(False)
        self.vol_scale.set_hexpand(True)
        self.vol_scale.set_value(70)
        self.vol_scale.connect("value-changed", self._on_volume)
        slider_row.append(self.mute_btn)
        slider_row.append(self.vol_scale)
        panel.append(slider_row)

        bri_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.bri_btn = Gtk.Button()
        self.bri_btn.add_css_class("qs-slider-icon")
        self.bri_btn.set_has_frame(False)
        self.bri_btn.set_tooltip_text(_("Brightness"))
        self.qs_bri_img = Gtk.Image()
        self.bri_btn.set_child(self.qs_bri_img)
        self.bri_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        self.bri_scale.add_css_class("qs-slider")
        self.bri_scale.set_draw_value(False)
        self.bri_scale.set_hexpand(True)
        self.bri_scale.set_value(100)
        self.bri_scale.connect("value-changed", self._on_brightness)
        bri_row.append(self.bri_btn)
        bri_row.append(self.bri_scale)
        panel.append(bri_row)
        return panel

    def _build_language(self) -> Gtk.Widget:
        from gi.repository import Gtk

        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        panel.add_css_class("shell-panel")
        panel.add_css_class("qs-language")
        panel.set_halign(Gtk.Align.END)
        panel.set_valign(Gtk.Align.START)
        panel.set_margin_top(40)
        panel.set_margin_end(10)
        panel.set_size_request(380, -1)
        steal = Gtk.GestureClick()
        steal.connect("pressed", lambda *a: True)
        panel.add_controller(steal)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        header.add_css_class("menu-header")
        back = Gtk.Button()
        back.add_css_class("menu-back")
        back.set_has_frame(False)
        back.set_tooltip_text(_("Back"))
        self.lang_back_img = Gtk.Image()
        back.set_child(self.lang_back_img)
        back.connect("clicked", lambda *_: self.show_menu("qs"))
        self.lang_title = Gtk.Label(label=_("Language"), xalign=0)
        self.lang_title.add_css_class("menu-header-title")
        self.lang_title.set_hexpand(True)
        header.append(back)
        header.append(self.lang_title)
        panel.append(header)

        search = Gtk.SearchEntry()
        search.add_css_class("lang-search")
        search.set_placeholder_text(_("Search"))
        search.set_hexpand(True)
        if hasattr(search, "set_search_delay"):
            search.set_search_delay(0)
        search.connect("search-changed", self._on_language_search)
        self.lang_search = search
        panel.append(search)

        self.lang_empty = Gtk.Label(label=_("No matching languages"), xalign=0.5)
        self.lang_empty.add_css_class("lang-empty")
        self.lang_empty.set_visible(False)
        panel.append(self.lang_empty)

        scroll = Gtk.ScrolledWindow()
        scroll.add_css_class("lang-scroll")
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_max_content_height(280)
        scroll.set_propagate_natural_height(True)
        scroll.set_hexpand(True)
        scroll.set_has_frame(False)
        scroll.set_overlay_scrolling(True)
        self.lang_host = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        scroll.set_child(self.lang_host)
        panel.append(scroll)
        self._render_languages()
        return panel

    def _on_language_search(self, entry) -> None:
        self._lang_query = entry.get_text() or ""
        self._render_languages()

    def _reset_language_search(self) -> None:
        self._lang_query = ""
        if getattr(self, "lang_search", None) is not None:
            self.lang_search.set_text("")

    def _render_languages(self) -> None:
        from gi.repository import Gtk

        if not getattr(self, "lang_host", None):
            return
        self._clear(self.lang_host)
        self._lang_rows = []
        langs = [
            lang
            for lang in supported_languages()
            if language_matches(lang, self._lang_query)
        ]
        langs.sort(key=lambda lang: (lang.name.casefold(), lang.id))
        if self.lang_empty is not None:
            self.lang_empty.set_visible(len(langs) == 0)
        for lang in langs:
            btn = Gtk.Button()
            btn.add_css_class("lang-item")
            btn.set_has_frame(False)
            btn.set_hexpand(True)
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            name = Gtk.Label(label=lang.name, xalign=0)
            name.add_css_class("lang-name")
            name.set_hexpand(True)
            check = Gtk.Image()
            check.add_css_class("lang-check")
            check.set_pixel_size(16)
            path = find_status("object-select-symbolic.svg")
            if path:
                tex = _texture(path, self._fg(), 16)
                if tex is not None:
                    check.set_from_paintable(tex)
                else:
                    check.set_from_file(path)
            selected = lang.id == self.language
            check.set_opacity(1.0 if selected else 0.0)
            if selected:
                btn.add_css_class("selected")
            row.append(name)
            row.append(check)
            btn.set_child(row)
            btn.connect("clicked", lambda _b, lid=lang.id: self._pick_language(lid))
            self.lang_host.append(btn)
            self._lang_rows.append(btn)

    def _pick_language(self, lang_id: str) -> None:
        if lang_id == self.language:
            self._render_languages()
            return
        from firstboot.i18n import apply_language

        self.language = apply_language(lang_id, payload_root=self.payload_root)
        if self.payload_root:
            persist_language(self.payload_root, self.language)
        self.retranslate()
        if self.on_language is not None:
            self.on_language(self.language)
        self._render_languages()

    def retranslate(self) -> None:
        if not self._built:
            return
        self.app_btn.set_tooltip_text(_("Applications"))
        self.clock_btn.set_tooltip_text(_("Date and time"))
        self.lang_btn.set_tooltip_text(_("Language"))
        self.power_btn.set_tooltip_text(_("Power Off"))
        self.tz_up.set_tooltip_text(_("Later time zone"))
        self.tz_down.set_tooltip_text(_("Earlier time zone"))
        self.dark_lab.set_label(_("Dark Style"))
        self.bri_btn.set_tooltip_text(_("Brightness"))
        self.net_title.set_label(_("Network"))
        self.eth_name.set_label(_("Ethernet"))
        self.wifi_lab.set_label(_("WI-FI"))
        self.power_title.set_label(_("Power Off"))
        self.restart_btn.get_child().set_label(_("Restart…"))
        self.poweroff_btn.get_child().set_label(_("Power Off…"))
        self.lang_title.set_label(_("Language"))
        self.lang_search.set_placeholder_text(_("Search"))
        self.lang_empty.set_label(_("No matching languages"))
        for _icon, label, action in app_items():
            lab = self._app_labels.get(action)
            if lab is not None:
                lab.set_label(label)
        if getattr(self, "shop_install_lab", None) is not None:
            self.shop_install_lab.set_label(_("Install to this device"))
        self._paint_net()
        self.refresh_volume()
        self.refresh_icons()

    def _qs_tile(
        self,
        *,
        sub: str | None = None,
        chevron: bool = False,
        toggle: bool = False,
    ):
        from gi.repository import Gtk, Pango

        btn = Gtk.ToggleButton() if toggle else Gtk.Button()
        btn.add_css_class("qs-toggle")
        btn.set_has_frame(False)
        btn.set_hexpand(True)
        btn.set_size_request(160, 52)

        grid = Gtk.Grid()
        grid.set_column_spacing(8)
        grid.set_row_spacing(0)
        grid.set_valign(Gtk.Align.CENTER)
        grid.set_hexpand(True)

        img = Gtk.Image()
        img.set_pixel_size(16)
        img.set_halign(Gtk.Align.CENTER)
        img.set_valign(Gtk.Align.CENTER)
        grid.attach(img, 0, 0, 1, 2 if sub is not None else 1)

        label = Gtk.Label(xalign=0)
        label.add_css_class("qs-toggle-label")
        label.set_ellipsize(Pango.EllipsizeMode.END)
        label.set_wrap(False)
        label.set_hexpand(True)
        label.set_halign(Gtk.Align.START)
        grid.attach(label, 1, 0, 1, 1)

        sub_lab = None
        if sub is not None:
            sub_lab = Gtk.Label(label=sub, xalign=0)
            sub_lab.add_css_class("qs-toggle-sub")
            sub_lab.set_ellipsize(Pango.EllipsizeMode.END)
            sub_lab.set_wrap(False)
            sub_lab.set_hexpand(True)
            sub_lab.set_halign(Gtk.Align.START)
            grid.attach(sub_lab, 1, 1, 1, 1)

        chev = None
        if chevron:
            chev = Gtk.Image()
            chev.set_pixel_size(12)
            chev.set_valign(Gtk.Align.CENTER)
            grid.attach(chev, 2, 0, 1, 2 if sub is not None else 1)

        btn.set_child(grid)
        return btn, img, label, sub_lab, chev

    def _build_network(self) -> Gtk.Widget:
        from gi.repository import Gtk

        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        panel.add_css_class("shell-panel")
        panel.set_halign(Gtk.Align.END)
        panel.set_valign(Gtk.Align.START)
        panel.set_margin_top(40)
        panel.set_margin_end(10)
        panel.set_size_request(340, -1)
        steal = Gtk.GestureClick()
        steal.connect("pressed", lambda *a: True)
        panel.add_controller(steal)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        header.add_css_class("menu-header")
        back = Gtk.Button()
        back.add_css_class("menu-back")
        back.set_has_frame(False)
        back.set_tooltip_text(_("Back"))
        self.net_back_img = Gtk.Image()
        back.set_child(self.net_back_img)
        back.connect("clicked", lambda *_: self.show_menu("qs"))
        self.net_title = Gtk.Label(label=_("Network"), xalign=0)
        self.net_title.add_css_class("menu-header-title")
        self.net_title.set_hexpand(True)
        header.append(back)
        header.append(self.net_title)
        panel.append(header)

        eth_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        eth_row.add_css_class("net-row")
        eth_text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        eth_text.set_hexpand(True)
        self.eth_name = Gtk.Label(label=_("Ethernet"), xalign=0)
        self.eth_name.add_css_class("net-name")
        self.eth_detail = Gtk.Label(label=_("Cable unplugged"), xalign=0)
        self.eth_detail.add_css_class("net-detail")
        eth_text.append(self.eth_name)
        eth_text.append(self.eth_detail)
        self.eth_btn = Gtk.Button(label=_("Connect"))
        self.eth_btn.add_css_class("btn-pill")
        self.eth_btn.set_has_frame(False)
        self.eth_btn.connect("clicked", lambda *_: self._on_ethernet())
        eth_row.append(eth_text)
        eth_row.append(self.eth_btn)
        panel.append(eth_row)

        self.wifi_lab = Gtk.Label(label=_("WI-FI"), xalign=0)
        self.wifi_lab.add_css_class("net-section")
        panel.append(self.wifi_lab)

        scroll = Gtk.ScrolledWindow()
        scroll.add_css_class("wifi-scroll")
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_max_content_height(320)
        scroll.set_propagate_natural_height(True)
        scroll.set_hexpand(True)
        self.wifi_host = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        scroll.set_child(self.wifi_host)
        panel.append(scroll)
        return panel

    def _build_power(self) -> Gtk.Widget:
        from gi.repository import Gtk

        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        panel.add_css_class("shell-panel")
        panel.add_css_class("power-menu")
        panel.set_halign(Gtk.Align.END)
        panel.set_valign(Gtk.Align.START)
        panel.set_margin_top(40)
        panel.set_margin_end(10)
        panel.set_size_request(220, -1)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        header.add_css_class("power-menu-header")
        self.power_hdr_img = Gtk.Image()
        header.append(self.power_hdr_img)
        self.power_title = Gtk.Label(label=_("Power Off"), xalign=0)
        header.append(self.power_title)
        panel.append(header)

        self.restart_btn = self._menu_btn(_("Restart…"), lambda *_: self._power("restart"))
        self.poweroff_btn = self._menu_btn(_("Power Off…"), lambda *_: self._power("poweroff"))
        panel.append(self.restart_btn)
        panel.append(self.poweroff_btn)
        return panel

    def _menu_btn(self, label: str, handler) -> Gtk.Widget:
        from gi.repository import Gtk

        btn = Gtk.Button()
        btn.add_css_class("power-menu-item")
        btn.set_has_frame(False)
        btn.set_halign(Gtk.Align.FILL)
        lab = Gtk.Label(label=label, xalign=0)
        lab.set_hexpand(True)
        btn.set_child(lab)
        btn.connect("clicked", handler)
        return btn

    def _build_apps(self) -> Gtk.Widget:
        from gi.repository import Gtk

        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        panel.add_css_class("shell-panel")
        panel.add_css_class("app-menu")
        panel.set_halign(Gtk.Align.START)
        panel.set_valign(Gtk.Align.START)
        panel.set_margin_top(40)
        panel.set_margin_start(10)
        panel.set_size_request(260, -1)

        if self.show_shop_install:
            panel.append(self._shop_install_row())
            sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
            sep.add_css_class("app-menu-sep")
            panel.append(sep)

        for icon, label, action in app_items():
            btn = Gtk.Button()
            btn.add_css_class("app-menu-item")
            btn.set_has_frame(False)
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            dot = Gtk.Box()
            dot.add_css_class("app-running-dot")
            dot.set_valign(Gtk.Align.CENTER)
            dot.set_halign(Gtk.Align.CENTER)
            dot.set_opacity(1.0 if self._app_running.get(action) else 0.0)
            self._app_running_dots[action] = dot
            img = Gtk.Image()
            img.set_pixel_size(24)
            if icon == "cog":
                path = find_status("cog-wheel-symbolic.svg")
                if path:
                    tex = _texture(path, self._fg(), 24)
                    if tex is not None:
                        img.set_from_paintable(tex)
                    else:
                        img.set_from_file(path)
                self._app_cog = img
            else:
                path = find_app_icon(icon)
                if path:
                    img.set_from_file(path)
            row.append(dot)
            row.append(img)
            lab = Gtk.Label(label=label, xalign=0)
            self._app_labels[action] = lab
            row.append(lab)
            btn.set_child(row)
            btn.connect("clicked", lambda *_a, a=action: self._app_clicked(a))
            panel.append(btn)
        return panel

    def _shop_install_row(self) -> Gtk.Widget:
        from gi.repository import Gtk

        btn = Gtk.Button()
        btn.add_css_class("app-menu-item")
        btn.set_has_frame(False)
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        img = Gtk.Image()
        img.set_pixel_size(24)
        img.set_valign(Gtk.Align.CENTER)
        path = find_status("folder-download-symbolic.svg")
        if path:
            tex = _texture(path, self._fg(), 24)
            if tex is not None:
                img.set_from_paintable(tex)
            else:
                img.set_from_file(path)
        self._app_download = img
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        text.set_valign(Gtk.Align.CENTER)
        self.shop_install_lab = Gtk.Label(label=_("Install to this device"), xalign=0)
        self.shop_install_lab.add_css_class("app-menu-item-label")
        sub = Gtk.Label(label="First Boot Linux", xalign=0)
        sub.add_css_class("app-menu-item-sub")
        text.append(self.shop_install_lab)
        text.append(sub)
        row.append(img)
        row.append(text)
        btn.set_child(row)
        btn.connect("clicked", lambda *_: self._shop_clicked())
        return btn

    def _shop_clicked(self) -> None:
        self.close_menus()
        if self.on_shop_install is not None:
            self.on_shop_install()

    def _app_clicked(self, action: str) -> None:
        self.close_menus()
        if action == "terminal":
            if self.on_terminal is not None:
                self.on_terminal()
            else:
                self.on_toast("Terminal is not on this image yet.")
            return
        if action == "sysinfo":
            if self.on_sysinfo is not None:
                self.on_sysinfo()
            else:
                self.on_toast("System details is not on this image yet.")
            return
        if action == "browser":
            if self.on_browser is not None:
                self.on_browser()
            else:
                self.on_toast("Web browser is not on this image yet.")
            return
        self.on_toast(APP_TOASTS.get(action, f"{action} is not on this image yet."))

    def _power(self, action: str) -> None:
        self.close_menus()
        self.on_power(action)

    def _on_dark(self, btn) -> None:
        self.on_theme(btn.get_active())

    def _on_volume(self, scale) -> None:
        if getattr(self, "_vol_lock", False):
            return
        try:
            st = self.volume.set_level(int(scale.get_value()))
        except Exception:
            return
        self._paint_volume(st, move_scale=False)

    def _toggle_mute(self) -> None:
        try:
            st = self.volume.toggle_mute()
        except Exception:
            return
        self._paint_volume(st)

    def _on_brightness(self, scale) -> None:
        if getattr(self, "_bri_lock", False):
            return
        try:
            st = self.brightness.set_level(int(scale.get_value()))
        except Exception:
            return
        self._paint_brightness(st, move_scale=False)

    def _paint_volume(self, st: VolumeState, *, move_scale: bool = True) -> None:
        if not self._built:
            return
        if move_scale:
            self._vol_lock = True
            self.vol_scale.set_value(st.output)
            self._vol_lock = False
        color = self._fg()
        set_symbolic(self.vol_img, st.icon, PANEL_FG, 16)
        set_symbolic(self.qs_vol_img, st.icon, color, 16)
        self.mute_btn.set_tooltip_text(_("Unmute") if st.output == 0 else _("Mute"))

    def _paint_brightness(self, st: BrightnessState, *, move_scale: bool = True) -> None:
        if not self._built:
            return
        if move_scale:
            self._bri_lock = True
            self.bri_scale.set_value(st.level)
            self._bri_lock = False
        self.bri_scale.set_sensitive(st.available)
        set_symbolic(self.qs_bri_img, st.icon, self._fg(), 16)

    def _paint_battery(self) -> None:
        if not self._built:
            return
        st = self.battery
        self.bat_box.set_visible(st.present)
        if not st.present:
            self.bat_box.set_tooltip_text("")
            self.bat_pct.remove_css_class("low")
            self.bat_pct.remove_css_class("critical")
            return
        color = st.color or PANEL_FG
        set_symbolic_svg(
            self.bat_img,
            battery_svg(percent=st.percent, charging=st.charging),
            color,
            16,
        )
        self.bat_pct.set_label(st.label)
        self.bat_pct.remove_css_class("low")
        self.bat_pct.remove_css_class("critical")
        if st.critical:
            self.bat_pct.add_css_class("critical")
        elif st.low:
            self.bat_pct.add_css_class("low")
        tip = st.tooltip()
        self.bat_box.set_tooltip_text(tip)
        self.bat_img.set_tooltip_text(tip)

    def _paint_net(self) -> None:
        if not self._built:
            return
        n = self.net
        set_symbolic(self.net_img, n.icon, PANEL_FG, 16)
        self.net_img.set_tooltip_text(n.tooltip)
        self.sys_btn.set_tooltip_text(n.tooltip)
        active = n.connected
        if active:
            self.net_toggle.add_css_class("active")
        else:
            self.net_toggle.remove_css_class("active")
        set_symbolic(self.qs_net_img, n.icon, self._fg(active=active), 16)
        set_symbolic(self.qs_net_chev, "go-next-symbolic.svg", self._fg(active=active), 12)
        self.qs_net_label.set_label(n.label)
        self.qs_net_sub.set_label(n.sub)

        detail, action = ethernet_detail(n.ethernet)
        self.eth_detail.set_label(detail)
        if action:
            self.eth_btn.set_label(action)
            self.eth_btn.set_visible(True)
            self.eth_btn.set_sensitive(not self._busy)
        else:
            self.eth_btn.set_visible(False)

        self._sync_wifi_list()

    def _note(self, text: str):
        from gi.repository import Gtk

        lab = Gtk.Label(label=text, xalign=0)
        lab.add_css_class("net-empty")
        return lab

    def _wifi_off_row(self):
        from gi.repository import Gtk

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        row.add_css_class("net-row")
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        text.set_hexpand(True)
        name = Gtk.Label(label=_("Wi-Fi"), xalign=0)
        name.add_css_class("net-name")
        sub = Gtk.Label(label=_("Off"), xalign=0)
        sub.add_css_class("net-detail")
        text.append(name)
        text.append(sub)
        btn = Gtk.Button(label=_("Turn on"))
        btn.add_css_class("btn-pill")
        btn.set_has_frame(False)
        btn.set_sensitive(not self._busy)
        btn.connect("clicked", lambda *_: self._wifi_radio(True))
        row.append(text)
        row.append(btn)
        return row

    def _sync_wifi_list(self) -> None:
        n = self.net
        if not n.wifi.hardware and n.wifi.device is None:
            mode, aps = "no-hw", ()
        elif not n.wifi.enabled:
            mode, aps = "off", ()
        elif not n.access_points:
            mode, aps = "empty", ()
        else:
            mode, aps = "aps", n.access_points[:WIFI_LIST_LIMIT]

        ids = tuple(ap.ssid for ap in aps)
        if self._wifi_expanded and ids and self._wifi_expanded not in ids:
            self._set_expanded(None)

        if self._wifi_expanded and self._wifi_mode == "aps" and self._wifi_rows:
            by_ssid = {ap.ssid: ap for ap in n.access_points}
            for ssid, row in self._wifi_rows.items():
                ap = by_ssid.get(ssid)
                if ap is not None:
                    row.update(ap, ssid in n.saved_ssids, self._busy)
            return

        if mode == "aps" and self._wifi_mode == "aps" and ids == tuple(self._wifi_rows):
            by_ssid = {ap.ssid: ap for ap in aps}
            for ssid, row in self._wifi_rows.items():
                ap = by_ssid.get(ssid)
                if ap is not None:
                    row.update(ap, ssid in n.saved_ssids, self._busy)
            return

        self._rebuild_wifi_list(mode, aps)

    def _rebuild_wifi_list(self, mode: str, aps: tuple[WifiAP, ...]) -> None:
        keep = self._wifi_expanded
        keep_row = self._wifi_rows.get(keep) if keep else None
        self._clear(self.wifi_host)
        self._wifi_rows = {}
        self._wifi_mode = mode
        if mode == "no-hw":
            self.wifi_host.append(self._note(_("No Wi-Fi adapter")))
            if keep:
                self._set_expanded(None)
            return
        if mode == "off":
            self.wifi_host.append(self._wifi_off_row())
            if keep:
                self._set_expanded(None)
            return
        if mode == "empty":
            self.wifi_host.append(self._note(_("No networks found")))
            if keep:
                self._set_expanded(None)
            return
        saved = self.net.saved_ssids
        for ap in aps:
            if keep_row is not None and keep_row.ssid == ap.ssid:
                row = keep_row
                row.update(ap, ap.ssid in saved, self._busy)
            else:
                row = _WifiRow(self, ap, ap.ssid in saved)
            self._wifi_rows[ap.ssid] = row
            self.wifi_host.append(row.root)
        if keep and keep not in self._wifi_rows:
            self._wifi_expanded = None
        elif keep_row is not None and keep == keep_row.ssid:
            keep_row.set_expanded(True)

    def _toggle_wifi(self, ssid: str) -> None:
        if self._busy:
            return
        self._set_expanded(None if self._wifi_expanded == ssid else ssid)

    def _set_expanded(self, ssid: str | None) -> None:
        prev = self._wifi_expanded
        if prev == ssid:
            return
        if prev and prev in self._wifi_rows:
            self._wifi_rows[prev].set_expanded(False)
        self._wifi_expanded = ssid
        if ssid and ssid in self._wifi_rows:
            self._wifi_rows[ssid].set_expanded(True)

    def _connect_wifi_row(self, row: _WifiRow) -> None:
        if self._busy:
            return
        ap = row.ap
        if ap.in_use:
            return
        secret = row.password().strip()
        saved = ap.ssid in self.net.saved_ssids
        if not ap.open and not saved and not secret:
            self.on_toast(_("Password required"))
            return
        pw = secret or None
        uuid = uuid_for_ssid(self.net.saved_uuids, ap.ssid)
        device = self.net.wifi.device
        sec = ap.security
        self._run(
            lambda: connect_wifi(
                ap.ssid, pw, security=sec, uuid=uuid, device=device
            ),
            _("Connected to {ssid}").format(ssid=ap.ssid),
            collapse=ap.ssid,
        )

    def _forget_wifi_row(self, row: _WifiRow) -> None:
        if self._busy:
            return
        ssid = row.ssid
        uuid = uuid_for_ssid(self.net.saved_uuids, ssid)
        self._run(
            lambda: forget_wifi(ssid, uuid),
            _("Forgot {ssid}").format(ssid=ssid),
            collapse=ssid,
        )

    def refresh_icons(self) -> None:
        if not self._built:
            return
        fg = self._fg()
        set_symbolic(self.app_grid_img, "view-app-grid-symbolic.svg", PANEL_FG, 16)
        set_symbolic(self.pwr_img, "system-shutdown-symbolic.svg", PANEL_FG, 16)
        set_symbolic(self.lang_btn_img, "languages-symbolic.svg", fg, 18)
        set_symbolic(self.power_btn_img, "system-shutdown-symbolic.svg", fg, 18)
        set_symbolic(self.power_hdr_img, "system-shutdown-symbolic.svg", fg, 16)
        set_symbolic(self.dark_img, "dark-mode-symbolic.svg", self._fg(active=self.dark), 16)
        path = find_status("go-next-symbolic.svg")
        if path:
            from gi.repository import Gdk

            pb = symbolic_pixbuf(path, fg, 16)
            for img in (self.net_back_img, getattr(self, "lang_back_img", None)):
                if img is None:
                    continue
                if pb is not None:
                    img.set_from_paintable(
                        Gdk.Texture.new_for_pixbuf(pb.flip(True))
                    )
                else:
                    img.set_from_file(path)
                img.set_pixel_size(16)
        if hasattr(self, "_app_cog") and self._app_cog is not None:
            path = find_status("cog-wheel-symbolic.svg")
            if path:
                tex = _texture(path, fg, 24)
                if tex is not None:
                    self._app_cog.set_from_paintable(tex)
        if self._app_download is not None:
            path = find_status("folder-download-symbolic.svg")
            if path:
                tex = _texture(path, fg, 24)
                if tex is not None:
                    self._app_download.set_from_paintable(tex)
        self._paint_tz_carets()
        self._paint_net()
        self.refresh_volume()
        self._paint_battery()
        try:
            self._paint_brightness(self.brightness.get())
        except Exception:
            pass

    def _on_ethernet(self) -> None:
        eth = self.net.ethernet
        if not eth.device or self._busy:
            return
        if eth.connected:
            self._run(lambda: disconnect_device(eth.device), _("Disconnected Ethernet"))
        else:
            self._run(lambda: connect_ethernet(eth.device), _("Connected via Ethernet"))

    def _wifi_radio(self, enabled: bool) -> None:
        self._run(
            lambda: set_wifi_radio(enabled),
            _("Wi-Fi on") if enabled else _("Wi-Fi off"),
        )

    def _set_busy_widgets(self, busy: bool) -> None:
        self.eth_btn.set_sensitive(not busy)
        for row in self._wifi_rows.values():
            row.update(row.ap, row.saved, busy)

    def _run(
        self,
        fn: Callable[[], None],
        ok_msg: str,
        *,
        collapse: str | None = None,
    ) -> None:
        if self._busy:
            return
        self._busy = True
        self._set_busy_widgets(True)

        def work() -> None:
            from gi.repository import GLib

            err: str | None = None
            try:
                fn()
            except NmError as exc:
                err = str(exc)
            except Exception as exc:
                err = str(exc)
            GLib.idle_add(self._done, ok_msg, err, collapse)

        threading.Thread(target=work, daemon=True).start()

    def _done(self, ok_msg: str, err: str | None, collapse: str | None = None) -> bool:
        self._busy = False
        if collapse and not err:
            self._set_expanded(None)
        self._set_busy_widgets(False)
        self._request_net(scan=False)
        if err:
            self.on_toast(err)
        else:
            self.on_toast(ok_msg)
        return False

    def _clear(self, box) -> None:
        child = box.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            box.remove(child)
            child = nxt
