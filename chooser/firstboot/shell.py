"""GNOME-like kiosk chrome: top bar, quick settings, network, power.

The three mockup apps (browser, system details, terminal) are listed in
the grid menu and do not launch.
"""

from __future__ import annotations

import datetime as dt
import threading
from collections.abc import Callable
from typing import TYPE_CHECKING

from firstboot.assets import find_app_icon, find_status, symbolic_pixbuf
from firstboot.net import (
    NmError,
    NetSnapshot,
    WifiAP,
    connect_ethernet,
    connect_wifi,
    disconnect_device,
    empty_snapshot,
    ethernet_detail,
    request_scan,
    set_wifi_radio,
    snapshot,
)
from firstboot.volume import VolumeState, get_volume_backend

if TYPE_CHECKING:
    from gi.repository import Gtk

PANEL_FG = "#f6f5f4"
QS_FG = "#f6f5f4"
QS_FG_LIGHT = "#1c1c1c"
QS_FG_ACTIVE = "#ffffff"

APP_ITEMS = (
    ("epiphany.png", "Web browser", "Web browser is not on this image yet."),
    ("cog", "System details", "System details is not on this image yet."),
    ("org.gnome.Terminal.png", "Terminal", "Terminal is not on this image yet."),
)


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


class Shell:
    def __init__(
        self,
        *,
        on_theme: Callable[[bool], None],
        on_toast: Callable[[str], None],
        on_power: Callable[[str], None],
        get_window: Callable,
    ) -> None:
        self.on_theme = on_theme
        self.on_toast = on_toast
        self.on_power = on_power
        self.get_window = get_window
        self.dark = True
        self.volume = get_volume_backend()
        self.net: NetSnapshot = empty_snapshot()
        self.open_menu: str | None = None
        self.allow_scan = True
        self._busy = False
        self._built = False

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
        self.refresh_net()
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
        try:
            self.net = snapshot()
        except Exception:
            self.net = empty_snapshot(available=False)
        self._paint_net()
        return True

    def refresh_volume(self) -> bool:
        try:
            self._paint_volume(self.volume.get())
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
        if name == self.open_menu:
            self.close_menus()
            return
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
            self.refresh_net()
            if self.allow_scan:
                from gi.repository import GLib

                GLib.timeout_add(400, self._scan_async)
        if name == "qs":
            self.refresh_volume()
            self.refresh_net()

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

        self.wifi_host = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        panel.append(self.wifi_host)
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
        panel.set_size_request(240, -1)

        for icon, label, msg in APP_ITEMS:
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
            btn.connect("clicked", lambda *_a, m=msg: self._app_clicked(m))
            panel.append(btn)
        return panel

    def _app_clicked(self, msg: str) -> None:
        self.close_menus()
        self.on_toast(msg)

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

        self._clear(self.wifi_host)
        if not n.wifi.hardware and n.wifi.device is None:
            self.wifi_host.append(self._note("No Wi-Fi adapter"))
        elif not n.wifi.enabled:
            row = self._wifi_off_row()
            self.wifi_host.append(row)
        elif not n.access_points:
            self.wifi_host.append(self._note("No networks found"))
        else:
            for ap in n.access_points[:8]:
                self.wifi_host.append(self._wifi_row(ap))

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

    def _wifi_row(self, ap: WifiAP):
        from gi.repository import Gtk

        btn = Gtk.Button()
        btn.add_css_class("wifi-item")
        if ap.in_use:
            btn.add_css_class("active")
        btn.set_has_frame(False)
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        icon = Gtk.Image()
        set_symbolic(
            icon,
            "network-wireless-signal-excellent-symbolic.svg",
            self._fg(active=ap.in_use),
            16,
        )
        left = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        left.set_hexpand(True)
        left.append(icon)
        left.append(Gtk.Label(label=ap.ssid, xalign=0))
        meta = Gtk.Label(label="Connected" if ap.in_use else "", xalign=1)
        meta.add_css_class("wifi-meta")
        row.append(left)
        row.append(meta)
        btn.set_child(row)
        btn.connect("clicked", lambda *_a, a=ap: self._on_wifi(a))
        return btn

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
        self._paint_net()
        try:
            self._paint_volume(self.volume.get())
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

    def _on_wifi(self, ap: WifiAP) -> None:
        if self._busy:
            return
        if ap.in_use:
            if self.net.wifi.device:
                self._run(
                    lambda: disconnect_device(self.net.wifi.device),
                    f"Disconnected {ap.ssid}",
                )
            return
        if ap.open:
            self._run(lambda: connect_wifi(ap.ssid), f"Connected to {ap.ssid}")
            return
        self._ask_wifi_password(ap)

    def _ask_wifi_password(self, ap: WifiAP) -> None:
        from gi.repository import Adw, GLib, Gtk

        win = self.get_window()
        dialog = Adw.AlertDialog(
            heading=ap.ssid,
            body="Enter the network password.",
        )
        entry = Gtk.PasswordEntry()
        entry.set_show_peek_icon(True)
        entry.set_hexpand(True)
        dialog.set_extra_child(entry)
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("ok", "Connect")
        dialog.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("ok")
        dialog.set_close_response("cancel")

        def done(_d: Adw.AlertDialog, result) -> None:
            try:
                resp = dialog.choose_finish(result)
            except GLib.Error:
                return
            if resp != "ok":
                return
            secret = entry.get_text()
            if not secret:
                self.on_toast("Password required")
                return
            self._run(lambda: connect_wifi(ap.ssid, secret), f"Connected to {ap.ssid}")

        dialog.choose(win, None, done)

    def _scan_async(self) -> bool:
        if self.open_menu != "network":
            return False

        def work() -> None:
            request_scan()
            from gi.repository import GLib

            GLib.idle_add(self.refresh_net)

        threading.Thread(target=work, daemon=True).start()
        return False

    def _run(self, fn: Callable[[], None], ok_msg: str) -> None:
        if self._busy:
            return
        self._busy = True
        self._paint_net()

        def work() -> None:
            from gi.repository import GLib

            err: str | None = None
            try:
                fn()
            except NmError as exc:
                err = str(exc)
            except Exception as exc:
                err = str(exc)
            GLib.idle_add(self._done, ok_msg, err)

        threading.Thread(target=work, daemon=True).start()

    def _done(self, ok_msg: str, err: str | None) -> bool:
        self._busy = False
        self.refresh_net()
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
