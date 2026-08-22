"""Fullscreen GTK4 chooser. Reads /run/payload. Shop USB→disk. Ubuntu autoinstall."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import threading

from firstboot.assets import (
    brand_logo_pixbuf,
    find_app_icon,
    find_brand_logo,
    find_logo,
)
from firstboot.disk import HelperEvent, live_plan
from firstboot.install import InstallError, run_apply
from firstboot.osinstall import (
    DRIVER_UBUNTU,
    OsIdentity,
    OsInstallError,
    live_os_plan,
    run_os_install,
    sha512_crypt,
    suggest_hostname,
    suggest_username,
    validate_identity,
)
from firstboot.payload import Distro, Edition, Payload, load_payload
from firstboot.shell import Shell
from firstboot.floatlayer import FloatLayer
from firstboot.browser import BrowserWindow
from firstboot.kioskapp import launch_console, launch_sysinfo, launch_web
from firstboot.theme import apply_session_theme, ensure_default_browser
from firstboot.style import CSS
from firstboot.sysinfo import SysinfoWindow
from firstboot.term import TermWindow

PAYLOAD_DEFAULT = "/run/payload"


def dump_payload(payload: Payload) -> None:
    print(f"payload: {payload.root}")
    if payload.retailer:
        print(f"retailer: {payload.retailer.name}")
        print(f"support: {payload.retailer.support}")
    else:
        print("retailer: (missing)")
    print(f"wallpaper_dark: {payload.wallpaper_dark or '-'}")
    print(f"wallpaper_light: {payload.wallpaper_light or '-'}")
    print(f"recommended: {len(payload.recommended)}")
    for distro in payload.recommended:
        ed = distro.default_edition
        print(f"  {distro.id}  default={ed.id}  {ed.action}  {ed.file or ed.url}")
    print(f"others: {len(payload.others)}")
    for distro in payload.others:
        print(f"  {distro.id}")
    for err in payload.errors:
        print(f"error: {err}", file=sys.stderr)


def run_window(
    payload_root: str,
    screenshot: str | None = None,
    open_id: str | None = None,
    open_as_catalog: bool = False,
    open_catalog_list: bool = False,
    open_menu: str | None = None,
    light: bool = False,
    shop: str | None = None,
    osinstall: str | None = None,
) -> int:
    print("firstboot-chooser: run", file=sys.stderr, flush=True)
    import gi

    gi.require_version("Gdk", "4.0")
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")

    from gi.repository import Adw, Gdk, Gio, GLib, Gtk
    print("firstboot-chooser: gtk ready", file=sys.stderr, flush=True)

    class Chooser(Adw.Application):
        def __init__(
            self,
            root: str,
            screenshot: str | None = None,
            open_id: str | None = None,
            open_as_catalog: bool = False,
            open_catalog_list: bool = False,
            open_menu: str | None = None,
            light: bool = False,
            shop: str | None = None,
            osinstall: str | None = None,
        ) -> None:
            super().__init__(
                application_id="org.firstboot.Chooser",
                flags=Gio.ApplicationFlags.NON_UNIQUE,
            )
            self.payload_root = root
            self.payload = load_payload(root)
            self.dark = not light
            self.screenshot = screenshot
            self.open_id = open_id
            self.open_as_catalog = open_as_catalog
            self.open_catalog_list = open_catalog_list
            self.open_menu = open_menu
            self.shop = shop
            self.osinstall = osinstall
            self._app_procs: list = []
            self.shop_plan = live_plan(root)
            self.detail_distro: Distro | None = None
            self.detail_from_catalog = False
            self.overlay_mode: str | None = None
            self.other_logo = None
            self._installing = False
            self._os_logo = False
            self.connect("activate", self.on_activate)

        def on_activate(self, _app: Adw.Application) -> None:
            print("firstboot-chooser: activate", file=sys.stderr, flush=True)
            Adw.StyleManager.get_default().set_color_scheme(
                Adw.ColorScheme.FORCE_LIGHT if not self.dark else Adw.ColorScheme.FORCE_DARK
            )

            provider = Gtk.CssProvider()
            provider.load_from_data(CSS)
            display = Gdk.Display.get_default()
            if display is not None:
                Gtk.StyleContext.add_provider_for_display(
                    display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
                )

            self.win = Gtk.ApplicationWindow(application=self, title="First Boot Linux")
            self.win.add_css_class("firstboot")
            kiosk = (
                os.environ.get("FIRSTBOOT_KIOSK") == "1"
                or os.environ.get("XDG_CURRENT_DESKTOP") == "FirstBoot"
            )
            self.kiosk = kiosk
            if kiosk:
                self.win.set_decorated(False)
            else:
                width, height = 1280, 800
                if display is not None:
                    monitors = display.get_monitors()
                    if monitors.get_n_items() > 0:
                        geo = monitors.get_item(0).get_geometry()
                        width = min(1280, max(800, geo.width - 80))
                        height = min(800, max(600, geo.height - 80))
                self.win.set_default_size(width, height)

            self.toasts = Adw.ToastOverlay()
            self.overlay = Gtk.Overlay()
            self.toasts.set_child(self.overlay)
            self.win.set_child(self.toasts)

            self.wallpaper = Gtk.Picture()
            self.wallpaper.set_content_fit(Gtk.ContentFit.COVER)
            self.wallpaper.set_can_shrink(True)
            self.wallpaper.set_hexpand(True)
            self.wallpaper.set_vexpand(True)
            self.wallpaper.add_css_class("wallpaper")
            self.overlay.set_child(self.wallpaper)

            column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            column.set_hexpand(True)
            column.set_vexpand(True)
            column.set_halign(Gtk.Align.FILL)
            column.set_valign(Gtk.Align.FILL)
            self.overlay.add_overlay(column)

            show_shop = (
                self.shop_plan.available
                or bool(self.shop)
                or os.environ.get("FIRSTBOOT_SHOP_INSTALL") == "1"
                or (bool(self.screenshot) and self.open_menu == "apps")
            )
            self.float_layer = FloatLayer()
            self.term = None
            self.sysinfo = None
            self.browser = None
            if kiosk:
                on_terminal = self._open_console
                on_sysinfo = self._open_sysinfo
                on_browser = self._open_web
            else:
                self.term = TermWindow(
                    get_window=lambda: self.win,
                    on_toast=self._toast,
                    layer=self.float_layer,
                )
                self.sysinfo = SysinfoWindow(
                    get_window=lambda: self.win,
                    retailer=self.payload.retailer,
                    layer=self.float_layer,
                )
                self.browser = BrowserWindow(
                    get_window=lambda: self.win,
                    on_toast=self._toast,
                    layer=self.float_layer,
                )
                on_terminal = self.term.open
                on_sysinfo = self.sysinfo.open
                on_browser = self.browser.open
            self.shell = Shell(
                on_theme=self._set_dark,
                on_toast=self._toast,
                on_power=self._confirm_power,
                get_window=lambda: self.win,
                on_shop_install=self._confirm_shop_install,
                on_terminal=on_terminal,
                on_sysinfo=on_sysinfo,
                on_browser=on_browser,
                show_shop_install=show_shop,
            )
            self.shell.allow_scan = not bool(self.screenshot)
            topbar, menus = self.shell.build()
            column.append(topbar)

            stage = Gtk.Overlay()
            stage.set_hexpand(True)
            stage.set_vexpand(True)
            column.append(stage)

            scroll = Gtk.ScrolledWindow()
            scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            scroll.set_vexpand(True)
            scroll.set_hexpand(True)
            outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            outer.set_halign(Gtk.Align.CENTER)
            outer.set_valign(Gtk.Align.CENTER)
            outer.set_hexpand(True)
            outer.set_vexpand(True)
            self.main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            self.main_box.add_css_class("content")
            self.main_box.set_halign(Gtk.Align.CENTER)
            outer.append(self.main_box)
            scroll.set_child(outer)
            stage.set_child(scroll)

            from firstboot.dimmer import BlurDimmer

            self.dimmer = BlurDimmer()
            self.dimmer.add_css_class("dimmer")
            self.dimmer.set_source(scroll)
            self.dimmer.set_wallpaper(self.wallpaper)
            self.dimmer.set_visible(False)
            click = Gtk.GestureClick()
            click.connect("pressed", lambda *_: self._overlay_back())
            self.dimmer.add_controller(click)

            self.footer = self._build_footer()
            stage.add_overlay(self.footer)
            stage.add_overlay(self.dimmer)

            self.detail_host = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            self.detail_host.set_halign(Gtk.Align.CENTER)
            self.detail_host.set_valign(Gtk.Align.START)
            self.detail_host.set_margin_top(40)
            self.detail_host.set_visible(False)
            self.overlay_stack = Gtk.Stack()
            self.overlay_stack.set_halign(Gtk.Align.CENTER)
            self.overlay_stack.set_hhomogeneous(True)
            self.overlay_stack.set_vhomogeneous(False)
            self.overlay_stack.set_interpolate_size(True)
            self.overlay_stack.set_transition_duration(320)
            self.catalog_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            self.catalog_page.set_halign(Gtk.Align.CENTER)
            self.detail_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            self.detail_page.set_halign(Gtk.Align.CENTER)
            self.overlay_stack.add_named(self.catalog_page, "catalog")
            self.overlay_stack.add_named(self.detail_page, "detail")
            self.detail_host.append(self.overlay_stack)
            stage.add_overlay(self.detail_host)

            self.install_host = self._build_install_overlay()
            self.done_host = self._build_done_overlay()
            stage.add_overlay(self.install_host)
            stage.add_overlay(self.done_host)
            if self.term is not None:
                self.term.build()
            if self.sysinfo is not None:
                self.sysinfo.build()
            if self.browser is not None:
                self.browser.build()
            stage.add_overlay(self.float_layer)

            for widget in menus:
                self.overlay.add_overlay(widget)

            key = Gtk.EventControllerKey()
            key.connect("key-pressed", self._on_key)
            self.win.add_controller(key)

            self._apply_theme()
            apply_session_theme(self.dark)
            ensure_default_browser()
            self._render_main()
            if self.open_catalog_list and not self.open_id:
                self.open_catalog()
            if self.open_id:
                for distro in [*self.payload.recommended, *self.payload.catalog]:
                    if distro.id == self.open_id:
                        self.open_detail(
                            distro,
                            from_catalog=self.open_as_catalog
                            or self.open_catalog_list,
                        )
                        break
            self.shell.tick_clock()
            GLib.timeout_add_seconds(15, self.shell.tick_clock)
            GLib.timeout_add_seconds(5, self.shell.refresh_net)
            self.win.present()
            self._announce_ready()
            if self.open_menu == "terminal":
                GLib.idle_add(lambda: self._open_terminal_menu() or False)
            elif self.open_menu == "sysinfo":
                GLib.idle_add(lambda: self._open_sysinfo_menu() or False)
            elif self.open_menu == "browser":
                GLib.idle_add(lambda: self._open_browser_menu() or False)
            elif self.open_menu:
                GLib.idle_add(lambda: self.shell.show_menu(self.open_menu) or False)
            if self.shop == "confirm":
                GLib.timeout_add(250, self._confirm_shop_install)
            elif self.shop == "progress":
                GLib.idle_add(self._preview_shop_progress)
            elif self.shop == "done":
                GLib.idle_add(self._show_shop_done)
            if self.osinstall == "confirm":
                GLib.timeout_add(250, self._preview_os_confirm)
            elif self.osinstall == "progress":
                GLib.idle_add(self._preview_os_progress)
            elif self.osinstall == "done":
                GLib.idle_add(self._preview_os_done)
            if self.screenshot:
                delay = (
                    1800
                    if self.shop == "confirm"
                    or self.osinstall == "confirm"
                    or self.open_menu == "terminal"
                    or self.open_menu == "sysinfo"
                    or self.open_menu == "browser"
                    else 1200
                )
                GLib.timeout_add(delay, self._write_screenshot)

        def _open_terminal_menu(self) -> None:
            if self.term is not None:
                self.term.open()
                return
            self._open_console()

        def _open_sysinfo_menu(self) -> None:
            if self.sysinfo is not None:
                self.sysinfo.open()
                return
            self._open_sysinfo()

        def _open_browser_menu(self) -> None:
            if self.browser is not None:
                self.browser.open()
                return
            self._open_web()

        def _open_web(self) -> None:
            self._spawn_app("browser", launch_web)

        def _open_console(self) -> None:
            self._spawn_app("terminal", launch_console)

        def _open_sysinfo(self) -> None:
            self._spawn_app(
                "sysinfo", lambda: launch_sysinfo(dark=self.dark)
            )

        def _spawn_app(self, kind: str, launcher) -> None:
            from gi.repository import GLib

            err, proc = launcher()
            if err:
                self._toast(err)
                return
            if proc is None:
                return
            self._app_procs.append(proc)
            GLib.child_watch_add(
                proc.pid, lambda pid, status: self._on_app_exit(kind, pid, status)
            )

        def _on_app_exit(self, kind: str, pid: int, status: int) -> None:
            try:
                rc = os.waitstatus_to_exitcode(status)
            except ValueError:
                rc = status
            print(
                f"firstboot-chooser: {kind} pid={pid} status={status} rc={rc}",
                file=sys.stderr,
                flush=True,
            )
            labels = {
                "browser": "Web browser",
                "terminal": "Terminal",
                "sysinfo": "System details",
            }
            name = labels.get(kind, kind)
            if rc < 0:
                self._toast(f"{name} stopped unexpectedly.")
            elif rc != 0:
                self._toast(f"{name} failed to start.")

        def _announce_ready(self) -> None:
            print("firstboot-chooser: window presented", file=sys.stderr, flush=True)
            try:
                subprocess.run(
                    ["logger", "-t", "firstboot-chooser", "window presented"],
                    check=False,
                )
            except OSError:
                pass

        def _on_key(self, _c: Gtk.EventControllerKey, keyval: int, *_rest: object) -> bool:
            if self._installing:
                return True
            if self.shell.handle_key(keyval):
                return True
            if keyval == Gdk.KEY_Escape and self.detail_host.get_visible():
                self._overlay_back()
                return True
            return False

        def _set_dark(self, dark: bool) -> None:
            self.dark = dark
            apply_session_theme(dark)
            self._apply_theme()
            self.shell.apply_theme(dark)

        def _apply_theme(self) -> None:
            mgr = Adw.StyleManager.get_default()
            if self.dark:
                mgr.set_color_scheme(Adw.ColorScheme.FORCE_DARK)
                self.win.remove_css_class("light")
            else:
                mgr.set_color_scheme(Adw.ColorScheme.FORCE_LIGHT)
                self.win.add_css_class("light")
            path = (
                self.payload.wallpaper_dark if self.dark else self.payload.wallpaper_light
            )
            if path and os.path.isfile(path):
                self.wallpaper.set_filename(path)
            else:
                self.wallpaper.set_filename(None)
            self.dimmer.set_dark(self.dark)
            if getattr(self, "term", None) is not None:
                self.term.apply_theme(self.dark)
            if getattr(self, "sysinfo", None) is not None:
                self.sysinfo.apply_theme(self.dark)
            if getattr(self, "browser", None) is not None:
                self.browser.apply_theme(self.dark)
            if hasattr(self, "install_logo"):
                self._paint_brand_logo()
            self._paint_other_logo()

        def _clear(self, box: Gtk.Box) -> None:
            child = box.get_first_child()
            while child is not None:
                nxt = child.get_next_sibling()
                box.remove(child)
                child = nxt

        def _build_footer(self) -> Gtk.Widget:
            lab = Gtk.Label(xalign=1)
            lab.add_css_class("brand-footer")
            lab.set_halign(Gtk.Align.END)
            lab.set_valign(Gtk.Align.END)
            lab.set_margin_end(16)
            lab.set_margin_bottom(12)
            retailer = self.payload.retailer
            if retailer is None:
                lab.set_visible(False)
                return lab
            text = f"Configured by {retailer.name}"
            if retailer.support:
                text += f"\nSupport: {retailer.support}"
            lab.set_label(text)
            return lab

        def _render_main(self) -> None:
            self._clear(self.main_box)
            self.other_logo = None
            p = self.payload

            if p.errors and p.retailer is None and not p.recommended and not p.catalog:
                note = Gtk.Label(
                    label="This image has no usable payload.\n"
                    + "\n".join(p.errors[:6])
                )
                note.set_justify(Gtk.Justification.CENTER)
                note.add_css_class("error-note")
                self.main_box.append(note)
                return

            cards: list[Gtk.Widget] = [self._card(d) for d in p.recommended]
            if p.others:
                cards.append(self._other_card())
            if cards:
                self.main_box.append(self._card_rows(cards))
            else:
                empty = Gtk.Label(
                    label="No recommended distributions are listed on this image.",
                    xalign=0,
                )
                empty.add_css_class("empty-note")
                self.main_box.append(empty)

            if p.errors:
                err = Gtk.Label(label="\n".join(p.errors), xalign=0)
                err.add_css_class("error-note")
                self.main_box.append(err)

        def _logo_image(self, distro_id: str, pixel: int) -> Gtk.Widget:
            path = find_logo(distro_id)
            if path:
                img = Gtk.Image.new_from_file(path)
                img.set_pixel_size(pixel)
                img.set_halign(Gtk.Align.CENTER)
                img.set_valign(Gtk.Align.CENTER)
                img.set_size_request(pixel, pixel)
                return img
            fallback = Gtk.Label(label=distro_id[:1].upper())
            fallback.set_size_request(pixel, pixel)
            return fallback

        def _card_rows(self, cards: list[Gtk.Widget]) -> Gtk.Widget:
            col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
            col.set_halign(Gtk.Align.CENTER)
            col.set_valign(Gtk.Align.CENTER)
            for i in range(0, len(cards), 6):
                row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
                row.set_halign(Gtk.Align.CENTER)
                for card in cards[i : i + 6]:
                    row.append(card)
                col.append(row)
            return col

        def _card(self, distro: Distro) -> Gtk.Widget:
            btn = Gtk.Button()
            btn.add_css_class("distro-card")
            btn.set_has_frame(False)
            btn.set_valign(Gtk.Align.START)
            btn.set_size_request(176, 198)
            inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            inner.set_halign(Gtk.Align.CENTER)
            logo = self._logo_image(distro.id, 64)
            logo.set_halign(Gtk.Align.CENTER)
            inner.append(logo)
            name = Gtk.Label(label=distro.name)
            name.add_css_class("card-name")
            desk = Gtk.Label(label=distro.default_desktop)
            desk.add_css_class("card-desktop")
            ver = Gtk.Label(label=distro.version)
            ver.add_css_class("card-version")
            inner.append(name)
            inner.append(desk)
            inner.append(ver)
            btn.set_child(inner)
            btn.connect("clicked", lambda *_: self.open_detail(distro, from_catalog=False))
            return btn

        def _other_card(self) -> Gtk.Widget:
            btn = Gtk.Button()
            btn.add_css_class("distro-card")
            btn.add_css_class("other-option-card")
            btn.set_has_frame(False)
            btn.set_valign(Gtk.Align.START)
            btn.set_size_request(176, 198)
            inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            inner.set_halign(Gtk.Align.CENTER)
            logo = Gtk.Image()
            logo.set_pixel_size(64)
            logo.set_halign(Gtk.Align.CENTER)
            logo.set_valign(Gtk.Align.CENTER)
            logo.set_size_request(64, 64)
            self.other_logo = logo
            self._paint_other_logo()
            inner.append(logo)
            name = Gtk.Label(label="Other options")
            name.add_css_class("card-name")
            desk = Gtk.Label(label="...")
            desk.add_css_class("card-desktop")
            ver = Gtk.Label(label="\u00a0")
            ver.add_css_class("card-version")
            inner.append(name)
            inner.append(desk)
            inner.append(ver)
            btn.set_child(inner)
            btn.connect("clicked", lambda *_: self.open_catalog())
            return btn

        def _paint_other_logo(self) -> None:
            img = self.other_logo
            if img is None:
                return
            name = "other-option-dark.png" if self.dark else "other-option-light.png"
            path = find_app_icon(name)
            if path:
                img.set_from_file(path)

        def _row(self, distro: Distro) -> Gtk.Widget:
            btn = Gtk.Button()
            btn.add_css_class("catalog-row")
            btn.set_has_frame(False)
            btn.set_hexpand(True)
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
            row.append(self._logo_image(distro.id, 40))
            name = Gtk.Label(label=distro.catalog_name, xalign=0)
            name.add_css_class("row-name")
            name.set_hexpand(True)
            row.append(name)
            meta = Gtk.Label(label=distro.version)
            meta.add_css_class("row-meta")
            row.append(meta)
            btn.set_child(row)
            btn.connect("clicked", lambda *_: self.open_detail(distro, from_catalog=True))
            return btn

        def _back_button(self, on_click) -> Gtk.Button:
            back = Gtk.Button(label="←  Back")
            back.add_css_class("back-link")
            back.set_has_frame(False)
            back.set_halign(Gtk.Align.START)
            back.connect("clicked", lambda *_: on_click())
            return back

        def _overlay_wrap(self, on_back, child: Gtk.Widget) -> Gtk.Widget:
            wrap = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            wrap.set_margin_start(16)
            wrap.set_margin_end(16)
            wrap.append(self._back_button(on_back))
            wrap.append(child)
            return wrap

        def _set_dimmed(self, on: bool) -> None:
            self.dimmer.set_visible(on)
            if on:
                self.dimmer.queue_draw()
            self.footer.set_visible(bool(self.payload.retailer) and not on)

        def _show_overlay(self, page: str, *, slide: bool) -> None:
            if slide:
                trans = (
                    Gtk.StackTransitionType.SLIDE_LEFT
                    if page == "detail"
                    else Gtk.StackTransitionType.SLIDE_RIGHT
                )
            else:
                trans = Gtk.StackTransitionType.NONE
            self.overlay_stack.set_transition_type(trans)
            self.overlay_stack.set_visible_child_name(page)
            self.overlay_mode = page
            self._set_dimmed(True)
            self.detail_host.set_visible(True)

        def _hide_overlay(self) -> None:
            self.overlay_mode = None
            self.detail_distro = None
            self.detail_from_catalog = False
            self._set_dimmed(False)
            self.detail_host.set_visible(False)

        def _overlay_back(self) -> None:
            if self.overlay_mode == "detail" and self.detail_from_catalog:
                self._show_overlay("catalog", slide=True)
                return
            self._hide_overlay()

        def open_catalog(self) -> None:
            self.shell.close_menus()
            self.detail_distro = None
            self.detail_from_catalog = False
            self._fill_catalog()
            self._show_overlay("catalog", slide=False)

        def _fill_catalog(self) -> None:
            self._clear(self.catalog_page)
            card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            card.add_css_class("detail-card")
            card.add_css_class("catalog-card")
            card.set_size_request(480, -1)
            title = Gtk.Label(label="Other options", xalign=0)
            title.add_css_class("catalog-title")
            card.append(title)
            listing = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            distros = sorted(
                self.payload.others,
                key=lambda d: (d.catalog_name.casefold(), d.id),
            )
            for distro in distros:
                listing.append(self._row(distro))
            scroll = Gtk.ScrolledWindow()
            scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            scroll.set_max_content_height(480)
            scroll.set_propagate_natural_height(True)
            scroll.set_hexpand(True)
            scroll.set_has_frame(False)
            scroll.set_child(listing)
            card.append(scroll)
            self.catalog_page.append(self._overlay_wrap(self._hide_overlay, card))

        def open_detail(self, distro: Distro, *, from_catalog: bool) -> None:
            self.shell.close_menus()
            self.detail_distro = distro
            self.detail_from_catalog = from_catalog
            if from_catalog and self.catalog_page.get_first_child() is None:
                self._fill_catalog()
            self._fill_detail(distro, from_catalog=from_catalog)
            slide = (
                from_catalog
                and self.overlay_mode == "catalog"
                and self.detail_host.get_visible()
            )
            self._show_overlay("detail", slide=slide)

        def _fill_detail(self, distro: Distro, *, from_catalog: bool) -> None:
            self._clear(self.detail_page)
            card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            card.add_css_class("detail-card")
            card.set_size_request(480, -1)

            hero = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
            hero.append(self._logo_image(distro.id, 80))
            titles = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            t = Gtk.Label(label=distro.name, xalign=0)
            t.add_css_class("detail-title")
            titles.append(t)
            if not from_catalog:
                dsk = Gtk.Label(label=distro.default_desktop, xalign=0)
                dsk.add_css_class("detail-desktop")
                titles.append(dsk)
            ver = Gtk.Label(label=distro.version, xalign=0)
            ver.add_css_class("detail-version")
            tag = Gtk.Label(label=distro.tagline, xalign=0)
            tag.add_css_class("detail-tagline")
            titles.append(ver)
            titles.append(tag)
            hero.append(titles)
            card.append(hero)

            desc = Gtk.Label(label=distro.description, xalign=0)
            desc.set_wrap(True)
            desc.set_max_width_chars(48)
            desc.add_css_class("detail-desc")
            card.append(desc)

            if from_catalog and len(distro.editions) >= 1:
                lab = Gtk.Label(label="Desktop environment", xalign=0)
                lab.add_css_class("de-label")
                card.append(lab)
                for ed in distro.editions:
                    card.append(self._edition_row(distro, ed))
            else:
                actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
                actions.set_halign(Gtk.Align.END)
                actions.set_margin_top(12)
                ed = distro.default_edition
                btn = Gtk.Button(label="Install" if ed.on_disk else "Download")
                btn.add_css_class("btn-primary")
                btn.connect("clicked", lambda *_: self._act(distro, ed))
                actions.append(btn)
                card.append(actions)

            self.detail_page.append(self._overlay_wrap(self._overlay_back, card))

        def _edition_row(self, distro: Distro, ed: Edition) -> Gtk.Widget:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            row.add_css_class("de-row")
            meta = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
            meta.set_hexpand(True)
            name = Gtk.Label(label=ed.name, xalign=0)
            bits = [ed.size_label()]
            if ed.on_disk:
                bits.append("On disk")
            size = Gtk.Label(label=" · ".join(bits), xalign=0)
            size.add_css_class("row-meta")
            meta.append(name)
            meta.append(size)
            row.append(meta)
            btn = Gtk.Button(label="Install" if ed.on_disk else "Download")
            btn.add_css_class("btn-primary")
            btn.connect("clicked", lambda *_: self._act(distro, ed))
            row.append(btn)
            return row

        def close_detail(self) -> None:
            self._hide_overlay()

        def _act(self, distro: Distro, ed: Edition) -> None:
            if not ed.on_disk:
                self._toast(
                    f"Download is not available yet ({distro.name} {ed.name})."
                )
                return
            if distro.install != DRIVER_UBUNTU:
                self._toast(
                    f"{distro.name} install is not available yet."
                )
                return
            self._confirm_os_install(distro, ed)

        def _toast(self, text: str) -> None:
            self.toasts.add_toast(Adw.Toast.new(text))

        def _build_install_overlay(self) -> Gtk.Widget:
            host = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            host.set_halign(Gtk.Align.CENTER)
            host.set_valign(Gtk.Align.CENTER)
            host.set_visible(False)

            panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
            panel.add_css_class("install-panel")
            panel.set_halign(Gtk.Align.CENTER)

            self.install_logo = Gtk.Image()
            self.install_logo.set_pixel_size(80)
            self.install_logo.set_halign(Gtk.Align.CENTER)
            self._paint_brand_logo()
            panel.append(self.install_logo)

            self.install_title = Gtk.Label(label="Installing First Boot Linux")
            self.install_title.add_css_class("install-title")
            panel.append(self.install_title)

            self.install_sub = Gtk.Label(label="")
            self.install_sub.add_css_class("install-sub")
            panel.append(self.install_sub)

            self.install_bar = Gtk.ProgressBar()
            self.install_bar.add_css_class("shop-progress")
            self.install_bar.set_fraction(0)
            self.install_bar.set_margin_top(10)
            panel.append(self.install_bar)

            meta = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
            meta.add_css_class("progress-meta")
            self.install_pct = Gtk.Label(label="0%", xalign=0)
            self.install_pct.set_hexpand(True)
            self.install_step = Gtk.Label(label="", xalign=1)
            meta.append(self.install_pct)
            meta.append(self.install_step)
            panel.append(meta)

            host.append(panel)
            return host

        def _build_done_overlay(self) -> Gtk.Widget:
            host = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            host.set_halign(Gtk.Align.CENTER)
            host.set_valign(Gtk.Align.CENTER)
            host.set_visible(False)

            panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
            panel.add_css_class("done-panel")
            panel.set_halign(Gtk.Align.CENTER)

            check = Gtk.Label(label="✓")
            check.add_css_class("done-check")
            check.set_halign(Gtk.Align.CENTER)
            panel.append(check)

            title = Gtk.Label(label="You're all set")
            title.add_css_class("done-title")
            panel.append(title)

            self.done_msg = Gtk.Label(
                label="First Boot Linux is on this computer. Remove the USB stick and restart."
            )
            self.done_msg.add_css_class("done-msg")
            self.done_msg.set_wrap(True)
            self.done_msg.set_justify(Gtk.Justification.CENTER)
            self.done_msg.set_max_width_chars(36)
            panel.append(self.done_msg)

            reboot = Gtk.Button(label="Restart now")
            reboot.add_css_class("btn-primary")
            reboot.set_halign(Gtk.Align.CENTER)
            reboot.set_margin_top(8)
            reboot.connect("clicked", lambda *_: _power("reboot"))
            panel.append(reboot)

            host.append(panel)
            return host

        def _paint_brand_logo(self) -> None:
            if self._os_logo:
                return
            path = find_brand_logo()
            if not path:
                return
            try:
                pb = brand_logo_pixbuf(path, self.dark, 80)
            except Exception:
                pb = None
            if pb is not None:
                from gi.repository import Gdk

                self.install_logo.set_from_paintable(Gdk.Texture.new_for_pixbuf(pb))
            else:
                self.install_logo.set_from_file(path)

        def _set_shop_progress(self, pct: int, step: str | None = None) -> None:
            pct = max(0, min(100, pct))
            self.install_bar.set_fraction(pct / 100.0)
            self.install_pct.set_label(f"{pct}%")
            if step is not None:
                self.install_sub.set_label(step)
                self.install_step.set_label(step)

        def _show_install_overlay(self) -> None:
            self.close_detail()
            self.shell.close_menus()
            if self.term is not None:
                self.term.close()
            if self.sysinfo is not None:
                self.sysinfo.close()
            self.shell.locked = True
            self._installing = True
            self._set_dimmed(True)
            self.done_host.set_visible(False)
            self.install_host.set_visible(True)
            self._set_shop_progress(0, "")

        def _set_os_brand(self, distro: Distro, ed: Edition | None = None) -> None:
            self._os_logo = True
            de = f" ({ed.name})" if ed and ed.name else ""
            self.install_title.set_label(f"Installing {distro.name}{de}")
            path = find_logo(distro.id)
            if path:
                self.install_logo.set_from_file(path)
            else:
                self._os_logo = False
                self._paint_brand_logo()

        def _hide_shop_overlays(self) -> None:
            self._installing = False
            self._os_logo = False
            self.shell.locked = False
            self.install_host.set_visible(False)
            self.done_host.set_visible(False)
            self._set_dimmed(False)
            self._paint_brand_logo()
            self.install_title.set_label("Installing First Boot Linux")
            self.done_msg.set_label(
                "First Boot Linux is on this computer. Remove the USB stick and restart."
            )

        def _confirm_shop_install(self) -> bool:
            self.shell.close_menus()
            dialog = Adw.AlertDialog(
                heading="Install to this device?",
                body="This will erase the internal disk and copy First Boot Linux onto it.",
            )
            dialog.add_response("cancel", "Cancel")
            dialog.add_response("ok", "Install")
            dialog.set_response_appearance("ok", Adw.ResponseAppearance.DESTRUCTIVE)
            dialog.set_default_response("cancel")
            dialog.set_close_response("cancel")

            def done(_d: Adw.AlertDialog, result: Gio.AsyncResult) -> None:
                try:
                    resp = dialog.choose_finish(result)
                except GLib.Error:
                    return
                if resp == "ok":
                    self._start_shop_install()

            dialog.choose(self.win, None, done)
            return False

        def _start_shop_install(self) -> None:
            self._show_install_overlay()
            if self.shop or self.screenshot:
                self._preview_shop_progress()
                return
            plan = live_plan(self.payload_root)
            if not plan.available or plan.target is None:
                self._hide_shop_overlays()
                self._toast(plan.reason or "No internal disk to install to.")
                return

            def work() -> None:
                err: str | None = None
                try:
                    run_apply(plan.target.path, on_event=self._shop_event)
                except InstallError as exc:
                    err = str(exc)
                except Exception as exc:
                    err = str(exc)
                GLib.idle_add(self._shop_finished, err)

            threading.Thread(target=work, daemon=True).start()

        def _shop_event(self, event: HelperEvent) -> None:
            def paint() -> bool:
                if event.kind == "step":
                    if event.progress is not None:
                        self._set_shop_progress(event.progress, event.text)
                    else:
                        self.install_sub.set_label(event.text)
                        self.install_step.set_label(event.text)
                elif event.kind == "progress" and event.progress is not None:
                    self._set_shop_progress(event.progress)
                return False

            from gi.repository import GLib

            GLib.idle_add(paint)

        def _shop_finished(self, err: str | None) -> bool:
            if err:
                self._hide_shop_overlays()
                self._toast(err)
                return False
            self._show_shop_done()
            return False

        def _preview_shop_progress(self) -> bool:
            self._show_install_overlay()
            steps = (
                (12, "Preparing the disk…"),
                (34, "Copying boot files…"),
                (58, "Copying First Boot…"),
                (82, "Copying recommended systems…"),
                (100, "Complete"),
            )
            state = {"i": 0}

            def tick() -> bool:
                if state["i"] >= len(steps):
                    GLib.timeout_add(350, self._show_shop_done)
                    return False
                pct, label = steps[state["i"]]
                self._set_shop_progress(pct, label)
                state["i"] += 1
                return True

            tick()
            if self.screenshot and self.shop == "progress":
                self._set_shop_progress(58, "Copying First Boot…")
                return False
            GLib.timeout_add(500, tick)
            return False

        def _show_shop_done(self) -> bool:
            self.shell.close_menus()
            self.shell.locked = True
            self._installing = False
            self.install_host.set_visible(False)
            self._set_dimmed(True)
            self.done_host.set_visible(True)
            return False

        def _preview_os_distro(self) -> Distro | None:
            for distro in self.payload.recommended:
                if distro.install == DRIVER_UBUNTU:
                    return distro
            return None

        def _preview_os_confirm(self) -> bool:
            distro = self._preview_os_distro()
            if distro is None:
                return False
            self._confirm_os_install(distro, distro.default_edition)
            return False

        def _preview_os_progress(self) -> bool:
            distro = self._preview_os_distro()
            self._show_install_overlay()
            if distro is not None:
                self._set_os_brand(distro, distro.default_edition)
            self._set_shop_progress(58, "Checking the image…")
            return False

        def _preview_os_done(self) -> bool:
            distro = self._preview_os_distro()
            name = distro.name if distro else "Ubuntu"
            de = ""
            if distro is not None:
                de = f" ({distro.default_edition.name})"
            self.done_msg.set_label(
                f"{name}{de} will install after restart. This computer will be erased."
            )
            self._show_shop_done()
            return False

        def _confirm_os_install(self, distro: Distro, ed: Edition) -> None:
            self.shell.close_menus()
            de = f" ({ed.name})" if ed.name else ""
            dialog = Adw.AlertDialog(
                heading=f"Install {distro.name}{de}?",
                body="This will erase this computer and install Ubuntu. Create the account you will use after restart.",
            )
            dialog.add_response("cancel", "Cancel")
            dialog.add_response("ok", "Install")
            dialog.set_response_appearance("ok", Adw.ResponseAppearance.DESTRUCTIVE)
            dialog.set_default_response("cancel")
            dialog.set_close_response("cancel")

            grid = Gtk.Grid(row_spacing=8, column_spacing=10)
            grid.set_margin_top(8)

            def labeled(row: int, title: str, widget: Gtk.Widget) -> None:
                lab = Gtk.Label(label=title, xalign=0)
                lab.add_css_class("row-meta")
                grid.attach(lab, 0, row, 1, 1)
                widget.set_hexpand(True)
                grid.attach(widget, 1, row, 1, 1)

            name_e = Gtk.Entry()
            name_e.set_placeholder_text("Your name")
            user_e = Gtk.Entry()
            user_e.set_placeholder_text("username")
            host_e = Gtk.Entry()
            host_e.set_text("ubuntu")
            pw_e = Gtk.Entry()
            pw_e.set_visibility(False)
            pw_e.set_input_purpose(Gtk.InputPurpose.PASSWORD)
            pw2_e = Gtk.Entry()
            pw2_e.set_visibility(False)
            pw2_e.set_input_purpose(Gtk.InputPurpose.PASSWORD)
            labeled(0, "Name", name_e)
            labeled(1, "Username", user_e)
            labeled(2, "Computer", host_e)
            labeled(3, "Password", pw_e)
            labeled(4, "Confirm", pw2_e)
            dialog.set_extra_child(grid)
            dialog.set_response_enabled("ok", False)

            def on_name(*_a: object) -> None:
                user_e.set_text(suggest_username(name_e.get_text()))
                suggested = suggest_hostname(user_e.get_text())
                if host_e.get_text() in ("", "ubuntu") and suggested:
                    host_e.set_text(suggested)

            def refresh(*_a: object) -> None:
                password = pw_e.get_text()
                match = password == pw2_e.get_text()
                err = validate_identity(
                    host_e.get_text().strip().lower(),
                    user_e.get_text().strip(),
                    name_e.get_text(),
                    password,
                )
                dialog.set_response_enabled("ok", err is None and match)

            name_e.connect("changed", on_name)
            for w in (name_e, user_e, host_e, pw_e, pw2_e):
                w.connect("changed", refresh)

            def done(_d: Adw.AlertDialog, result: Gio.AsyncResult) -> None:
                try:
                    resp = dialog.choose_finish(result)
                except GLib.Error:
                    return
                if resp != "ok":
                    return
                realname = name_e.get_text()
                username = user_e.get_text().strip()
                hostname = host_e.get_text().strip().lower()
                password = pw_e.get_text()
                if password != pw2_e.get_text():
                    self._toast("Passwords do not match.")
                    return
                err = validate_identity(hostname, username, realname, password)
                if err:
                    self._toast(err)
                    return
                ident = OsIdentity(
                    hostname=hostname,
                    username=username,
                    realname=realname.strip(),
                    password_hash=sha512_crypt(password),
                )
                self._start_os_install(distro, ed, ident)

            dialog.choose(self.win, None, done)

        def _start_os_install(self, distro: Distro, ed: Edition, ident: OsIdentity) -> None:
            self._show_install_overlay()
            self._set_os_brand(distro, ed)
            if self.osinstall or self.screenshot:
                self._preview_os_progress()
                return
            plan = live_os_plan(self.payload_root, distro, ed)
            if not plan.available:
                self._hide_shop_overlays()
                self._toast(plan.reason or "Cannot install.")
                return

            def work() -> None:
                err: str | None = None
                reboot = False
                try:
                    def on_event(event: HelperEvent) -> None:
                        nonlocal reboot
                        if event.kind == "reboot":
                            reboot = True
                        self._shop_event(event)

                    run_os_install(plan, ident, on_event=on_event)
                except (OsInstallError, InstallError) as exc:
                    err = str(exc)
                except Exception as exc:
                    err = str(exc)
                GLib.idle_add(self._os_finished, err, reboot, distro, ed)

            threading.Thread(target=work, daemon=True).start()

        def _os_finished(
            self, err: str | None, reboot: bool, distro: Distro, ed: Edition
        ) -> bool:
            if err:
                self._hide_shop_overlays()
                self._toast(err)
                return False
            de = f" ({ed.name})" if ed.name else ""
            self.done_msg.set_label(
                f"{distro.name}{de} will install after restart. This computer will be erased."
            )
            if reboot and not self.screenshot:
                self._set_shop_progress(100, "Restarting to install Ubuntu…")
                GLib.timeout_add(1200, self._reboot_now)
                return False
            self._show_shop_done()
            return False

        def _reboot_now(self) -> bool:
            _power("reboot")
            return False

        def _confirm_power(self, action: str) -> None:
            title = "Restart?" if action == "restart" else "Power Off?"
            body = (
                "The computer will restart."
                if action == "restart"
                else "The computer will shut down."
            )
            confirm = "Restart" if action == "restart" else "Power Off"
            dialog = Adw.AlertDialog(heading=title, body=body)
            dialog.add_response("cancel", "Cancel")
            dialog.add_response("ok", confirm)
            dialog.set_response_appearance("ok", Adw.ResponseAppearance.DESTRUCTIVE)
            dialog.set_default_response("cancel")
            dialog.set_close_response("cancel")

            def done(_d: Adw.AlertDialog, result: Gio.AsyncResult) -> None:
                try:
                    resp = dialog.choose_finish(result)
                except GLib.Error:
                    return
                if resp == "ok":
                    _power(action)

            dialog.choose(self.win, None, done)

        def _write_screenshot(self) -> bool:
            path = self.screenshot
            if not path:
                self.quit()
                return False
            try:
                from gi.repository import Graphene

                native = self.win.get_native()
                renderer = native.get_renderer() if native is not None else None
                w, h = self.win.get_width(), self.win.get_height()
                if renderer is None or w <= 0 or h <= 0:
                    print("screenshot: window not ready", file=sys.stderr)
                    self.quit()
                    return False
                snapshot = Gtk.Snapshot()
                paintable = Gtk.WidgetPaintable.new(self.win)
                paintable.snapshot(snapshot, float(w), float(h))
                node = snapshot.to_node()
                if node is None:
                    snapshot = Gtk.Snapshot()
                    Gtk.WidgetPaintable.new(self.overlay).snapshot(
                        snapshot, float(w), float(h)
                    )
                    node = snapshot.to_node()
                if node is None:
                    print(
                        f"screenshot: empty snapshot ({w}x{h} menu={self.open_menu})",
                        file=sys.stderr,
                    )
                    self.quit()
                    return False
                rect = Graphene.Rect()
                rect.init(0, 0, float(w), float(h))
                texture = renderer.render_texture(node, rect)
                texture.save_to_png(path)
                print(f"screenshot: {path}")
            except Exception as exc:
                print(f"screenshot: {exc}", file=sys.stderr)
            self.quit()
            return False

    print("firstboot-chooser: creating application", file=sys.stderr, flush=True)
    return int(
        Chooser(
            payload_root,
            screenshot,
            open_id,
            open_as_catalog,
            open_catalog_list,
            open_menu,
            light,
            shop,
            osinstall,
        ).run(None)
    )


def _power(action: str) -> None:
    verb = {"restart": "reboot", "poweroff": "poweroff", "reboot": "reboot"}.get(
        action, action
    )
    cmd = ["systemctl", verb]
    if shutil.which("systemctl"):
        try:
            subprocess.run(cmd, check=False)
            return
        except OSError:
            pass
    if shutil.which("sudo"):
        subprocess.run(["sudo", "-n", *cmd], check=False)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(description="First Boot Linux chooser")
    parser.add_argument(
        "--payload",
        default=os.environ.get("FBL_PAYLOAD", PAYLOAD_DEFAULT),
        help="payload directory (default: /run/payload)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="load the payload and print a summary; do not open a window",
    )
    parser.add_argument(
        "--dump",
        action="store_true",
        help="same as --check",
    )
    parser.add_argument(
        "--screenshot",
        metavar="FILE",
        help="write a PNG of the window and exit (host/CI)",
    )
    parser.add_argument("--open", metavar="ID", help="open this distro's detail view")
    parser.add_argument(
        "--catalog",
        action="store_true",
        help="open the Other options popover (host/CI screenshots)",
    )
    parser.add_argument(
        "--catalog-detail",
        action="store_true",
        help="open --open as an Other options detail (DE rows)",
    )
    parser.add_argument(
        "--menu",
        choices=("qs", "network", "apps", "power", "terminal", "sysinfo", "browser"),
        help="open a shell menu or an in-kiosk window (host/CI screenshots)",
    )
    parser.add_argument(
        "--light",
        action="store_true",
        help="start in the light style",
    )
    parser.add_argument(
        "--shop",
        choices=("confirm", "progress", "done"),
        help="open the shop-install UI (host/CI screenshots)",
    )
    parser.add_argument(
        "--osinstall",
        choices=("confirm", "progress", "done"),
        help="open the Ubuntu install UI (host/CI screenshots)",
    )
    print("firstboot-chooser: main", file=sys.stderr, flush=True)
    args = parser.parse_args(argv)
    print(f"firstboot-chooser: loading payload {args.payload!r}", file=sys.stderr, flush=True)
    payload = load_payload(args.payload)
    print("firstboot-chooser: payload loaded", file=sys.stderr, flush=True)
    if args.check or args.dump:
        dump_payload(payload)
        return 1 if payload.retailer is None else 0
    return run_window(
        args.payload,
        screenshot=args.screenshot,
        open_id=args.open,
        open_as_catalog=args.catalog_detail,
        open_catalog_list=args.catalog,
        open_menu=args.menu,
        light=args.light,
        shop=args.shop,
        osinstall=args.osinstall,
    )


if __name__ == "__main__":
    raise SystemExit(main())
