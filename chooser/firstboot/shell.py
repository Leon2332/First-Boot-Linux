"""GNOME-like kiosk chrome: top bar, quick settings, network, power.

Web browser, System details, and Terminal open as separate windows.
"""

from __future__ import annotations

import datetime as dt
import threading
from collections.abc import Callable
from typing import TYPE_CHECKING

from firstboot.assets import find_app_icon, find_status, symbolic_pixbuf
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
from firstboot.volume import VolumeState, get_volume_backend

if TYPE_CHECKING:
    from gi.repository import Gtk

PANEL_FG = "#f6f5f4"
QS_FG = "#f6f5f4"
QS_FG_LIGHT = "#1c1c1c"
QS_FG_ACTIVE = "#ffffff"

APP_ITEMS = (
    ("epiphany.png", "Web browser", "browser"),
    ("cog", "System details", "sysinfo"),
    ("org.gnome.Terminal.png", "Terminal", "terminal"),
)

APP_TOASTS: dict[str, str] = {}


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
            self.meta.set_label("Connected")
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
            self.unhide.set_label("Unhide")

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
        entry.set_placeholder_text("Password")
        entry.set_visibility(False)
        entry.set_hexpand(True)
        entry.set_input_purpose(Gtk.InputPurpose.PASSWORD)
        entry.set_input_hints(Gtk.InputHints.PRIVATE)
        entry.connect("activate", lambda *_: self.shell._connect_wifi_row(self))
        unhide = Gtk.Button(label="Unhide")
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
        forget = Gtk.Button(label="Forget")
        forget.add_css_class("btn-pill")
        forget.add_css_class("wifi-forget")
        forget.set_has_frame(False)
        forget.connect("clicked", lambda *_: self.shell._forget_wifi_row(self))
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        connect = Gtk.Button(label="Connect")
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
        self.unhide.set_label("Hide" if self._revealed else "Unhide")

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
            self.connect_btn.set_label("Connecting…" if busy and show_connect else "Connect")
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
    ) -> None:
        self.on_theme = on_theme
        self.on_toast = on_toast
        self.on_power = on_power
        self.get_window = get_window
        self.on_shop_install = on_shop_install
        self.on_terminal = on_terminal
        self.on_sysinfo = on_sysinfo
        self.on_browser = on_browser
        self.show_shop_install = show_shop_install
        self.dark = True
        self.volume = get_volume_backend()
        self.brightness = get_brightness_backend()
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
        self.power_menu = self._build_power()
        self.app_menu = self._build_apps()
        for panel in (self.qs, self.net_panel, self.power_menu, self.app_menu):
            panel.set_visible(False)
        self._built = True
        try:
            self.net = snapshot()
        except Exception:
            self.net = empty_snapshot(available=False)
        self._paint_net()
        self.refresh_volume()
        self.refresh_icons()
        return self.topbar, [
            self.backdrop,
            self.qs,
            self.net_panel,
            self.power_menu,
            self.app_menu,
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
        self.clock.set_label(format_clock(dt.datetime.now()))
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
        try:
            self._paint_volume(self.volume.get())
        except Exception:
            pass
        return True

    def refresh_brightness(self) -> bool:
        try:
            self._paint_brightness(self.brightness.get())
        except Exception:
            pass
        return True

    def handle_key(self, keyval: int) -> bool:
        from gi.repository import Gdk

        if keyval != Gdk.KEY_Escape or self.open_menu is None:
            return False
        if self.open_menu == "network":
            self.show_menu("qs")
        else:
            self.close_menus()
        return True

    def show_menu(self, name: str | None) -> None:
        if self.locked and name is not None:
            return
        if name == self.open_menu:
            self.close_menus()
            return
        if name not in {"network", "qs"}:
            self._set_expanded(None)
        self.open_menu = name
        self.backdrop.set_visible(name is not None)
        self.qs.set_visible(name == "qs")
        self.net_panel.set_visible(name == "network")
        self.power_menu.set_visible(name == "power")
        self.app_menu.set_visible(name == "apps")
        if name == "qs":
            self.sys_btn.add_css_class("open")
        else:
            self.sys_btn.remove_css_class("open")
        if name == "apps":
            self.app_btn.add_css_class("open")
        else:
            self.app_btn.remove_css_class("open")
        if name == "network":
            if self.allow_scan:
                self._request_net(scan=not self._wifi_expanded)
        if name == "qs":
            self.refresh_volume()
            self.refresh_brightness()
            if self.allow_scan:
                self._request_net(scan=False)

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
        bar.set_size_request(-1, 32)
        bar.set_valign(Gtk.Align.FILL)

        self.app_btn = Gtk.Button()
        self.app_btn.add_css_class("panel-btn")
        self.app_btn.set_tooltip_text("Applications")
        self.app_btn.set_has_frame(False)
        self.app_grid_img = Gtk.Image()
        self.app_btn.set_child(self.app_grid_img)
        self.app_btn.connect("clicked", lambda *_: self.show_menu("apps"))
        left = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        left.set_valign(Gtk.Align.CENTER)
        left.append(self.app_btn)
        bar.set_start_widget(left)

        self.clock = Gtk.Label(label="—")
        self.clock.add_css_class("clock")
        bar.set_center_widget(self.clock)

        self.sys_btn = Gtk.Button()
        self.sys_btn.add_css_class("panel-btn")
        self.sys_btn.set_tooltip_text("System menu")
        self.sys_btn.set_has_frame(False)
        icons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        icons.add_css_class("panel-icons")
        self.net_img = Gtk.Image()
        self.vol_img = Gtk.Image()
        self.pwr_img = Gtk.Image()
        for img in (self.net_img, self.vol_img, self.pwr_img):
            img.set_pixel_size(16)
            icons.append(img)
        self.sys_btn.set_child(icons)
        self.sys_btn.connect("clicked", lambda *_: self.show_menu("qs"))
        right = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        right.set_halign(Gtk.Align.END)
        right.set_valign(Gtk.Align.CENTER)
        right.append(self.sys_btn)
        bar.set_end_widget(right)
        return bar

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
        toolbar.set_halign(Gtk.Align.END)
        self.power_btn = Gtk.Button()
        self.power_btn.add_css_class("qs-round")
        self.power_btn.set_has_frame(False)
        self.power_btn.set_size_request(40, 40)
        self.power_btn.set_tooltip_text("Power Off")
        self.power_btn_img = Gtk.Image()
        self.power_btn.set_child(self.power_btn_img)
        self.power_btn.connect("clicked", lambda *_: self.show_menu("power"))
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
        self.qs_net_label.set_label("Network")
        self.net_toggle.connect("clicked", lambda *_: self.show_menu("network"))
        grid.attach(self.net_toggle, 0, 0, 1, 1)

        self.dark_btn, self.dark_img, dark_lab, _, _ = self._qs_tile(toggle=True)
        dark_lab.set_label("Dark Style")
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
        self.bri_btn.set_tooltip_text("Brightness")
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
        back.set_tooltip_text("Back")
        self.net_back_img = Gtk.Image()
        back.set_child(self.net_back_img)
        back.connect("clicked", lambda *_: self.show_menu("qs"))
        title = Gtk.Label(label="Network", xalign=0)
        title.add_css_class("menu-header-title")
        title.set_hexpand(True)
        header.append(back)
        header.append(title)
        panel.append(header)

        eth_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        eth_row.add_css_class("net-row")
        eth_text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        eth_text.set_hexpand(True)
        name = Gtk.Label(label="Ethernet", xalign=0)
        name.add_css_class("net-name")
        self.eth_detail = Gtk.Label(label="Cable unplugged", xalign=0)
        self.eth_detail.add_css_class("net-detail")
        eth_text.append(name)
        eth_text.append(self.eth_detail)
        self.eth_btn = Gtk.Button(label="Connect")
        self.eth_btn.add_css_class("btn-pill")
        self.eth_btn.set_has_frame(False)
        self.eth_btn.connect("clicked", lambda *_: self._on_ethernet())
        eth_row.append(eth_text)
        eth_row.append(self.eth_btn)
        panel.append(eth_row)

        wifi_lab = Gtk.Label(label="WI-FI", xalign=0)
        wifi_lab.add_css_class("net-section")
        panel.append(wifi_lab)

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
        header.append(Gtk.Label(label="Power Off", xalign=0))
        panel.append(header)

        panel.append(self._menu_btn("Restart…", lambda *_: self._power("restart")))
        panel.append(self._menu_btn("Power Off…", lambda *_: self._power("poweroff")))
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

        for icon, label, action in APP_ITEMS:
            btn = Gtk.Button()
            btn.add_css_class("app-menu-item")
            btn.set_has_frame(False)
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
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
            row.append(img)
            row.append(Gtk.Label(label=label, xalign=0))
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
        lab = Gtk.Label(label="Install to this device", xalign=0)
        lab.add_css_class("app-menu-item-label")
        sub = Gtk.Label(label="First Boot Linux", xalign=0)
        sub.add_css_class("app-menu-item-sub")
        text.append(lab)
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
        self.mute_btn.set_tooltip_text("Unmute" if st.output == 0 else "Mute")

    def _paint_brightness(self, st: BrightnessState, *, move_scale: bool = True) -> None:
        if not self._built:
            return
        if move_scale:
            self._bri_lock = True
            self.bri_scale.set_value(st.level)
            self._bri_lock = False
        self.bri_scale.set_sensitive(st.available)
        set_symbolic(self.qs_bri_img, st.icon, self._fg(), 16)

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
        name = Gtk.Label(label="Wi-Fi", xalign=0)
        name.add_css_class("net-name")
        sub = Gtk.Label(label="Off", xalign=0)
        sub.add_css_class("net-detail")
        text.append(name)
        text.append(sub)
        btn = Gtk.Button(label="Turn on")
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
            self.wifi_host.append(self._note("No Wi-Fi adapter"))
            if keep:
                self._set_expanded(None)
            return
        if mode == "off":
            self.wifi_host.append(self._wifi_off_row())
            if keep:
                self._set_expanded(None)
            return
        if mode == "empty":
            self.wifi_host.append(self._note("No networks found"))
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
            self.on_toast("Password required")
            return
        pw = secret or None
        uuid = uuid_for_ssid(self.net.saved_uuids, ap.ssid)
        device = self.net.wifi.device
        sec = ap.security
        self._run(
            lambda: connect_wifi(
                ap.ssid, pw, security=sec, uuid=uuid, device=device
            ),
            f"Connected to {ap.ssid}",
            collapse=ap.ssid,
        )

    def _forget_wifi_row(self, row: _WifiRow) -> None:
        if self._busy:
            return
        ssid = row.ssid
        uuid = uuid_for_ssid(self.net.saved_uuids, ssid)
        self._run(
            lambda: forget_wifi(ssid, uuid),
            f"Forgot {ssid}",
            collapse=ssid,
        )

    def refresh_icons(self) -> None:
        if not self._built:
            return
        fg = self._fg()
        set_symbolic(self.app_grid_img, "view-app-grid-symbolic.svg", PANEL_FG, 16)
        set_symbolic(self.pwr_img, "system-shutdown-symbolic.svg", PANEL_FG, 16)
        set_symbolic(self.power_btn_img, "system-shutdown-symbolic.svg", fg, 18)
        set_symbolic(self.power_hdr_img, "system-shutdown-symbolic.svg", fg, 16)
        set_symbolic(self.dark_img, "dark-mode-symbolic.svg", self._fg(active=self.dark), 16)
        path = find_status("go-next-symbolic.svg")
        if path:
            from gi.repository import Gdk

            pb = symbolic_pixbuf(path, fg, 16)
            if pb is not None:
                self.net_back_img.set_from_paintable(
                    Gdk.Texture.new_for_pixbuf(pb.flip(True))
                )
            else:
                self.net_back_img.set_from_file(path)
            self.net_back_img.set_pixel_size(16)
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
        self._paint_net()
        try:
            self._paint_volume(self.volume.get())
        except Exception:
            pass
        try:
            self._paint_brightness(self.brightness.get())
        except Exception:
            pass

    def _on_ethernet(self) -> None:
        eth = self.net.ethernet
        if not eth.device or self._busy:
            return
        if eth.connected:
            self._run(lambda: disconnect_device(eth.device), "Disconnected Ethernet")
        else:
            self._run(lambda: connect_ethernet(eth.device), "Connected via Ethernet")

    def _wifi_radio(self, enabled: bool) -> None:
        self._run(lambda: set_wifi_radio(enabled), "Wi-Fi on" if enabled else "Wi-Fi off")

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
