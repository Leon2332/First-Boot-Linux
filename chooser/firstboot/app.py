"""Fullscreen GTK4 chooser. Reads /run/payload. Does not install."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys

from firstboot.assets import find_logo
from firstboot.payload import Distro, Edition, Payload, load_payload
from firstboot.shell import Shell
from firstboot.style import CSS

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
    open_catalog: bool = False,
    open_menu: str | None = None,
    light: bool = False,
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
            open_catalog: bool = False,
            open_menu: str | None = None,
            light: bool = False,
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
            self.open_catalog = open_catalog
            self.open_menu = open_menu
            self.detail_distro: Distro | None = None
            self.detail_from_catalog = False
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

            self.shell = Shell(
                on_theme=self._set_dark,
                on_toast=self._toast,
                on_power=self._confirm_power,
                get_window=lambda: self.win,
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
            self.main_box.set_size_request(980, -1)
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
            click.connect("pressed", lambda *_: self.close_detail())
            self.dimmer.add_controller(click)
            stage.add_overlay(self.dimmer)

            self.detail_host = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            self.detail_host.set_halign(Gtk.Align.CENTER)
            self.detail_host.set_valign(Gtk.Align.START)
            self.detail_host.set_margin_top(40)
            self.detail_host.set_visible(False)
            stage.add_overlay(self.detail_host)

            for widget in menus:
                self.overlay.add_overlay(widget)

            key = Gtk.EventControllerKey()
            key.connect("key-pressed", self._on_key)
            self.win.add_controller(key)

            self._apply_theme()
            self._render_main()
            if self.open_id:
                for distro in [*self.payload.recommended, *self.payload.catalog]:
                    if distro.id == self.open_id:
                        self.open_detail(distro, from_catalog=self.open_catalog)
                        break
            self.shell.tick_clock()
            GLib.timeout_add_seconds(15, self.shell.tick_clock)
            GLib.timeout_add_seconds(5, self.shell.refresh_net)
            self.win.present()
            self._announce_ready()
            if self.open_menu:
                GLib.idle_add(lambda: self.shell.show_menu(self.open_menu) or False)
            if self.screenshot:
                GLib.timeout_add(1200, self._write_screenshot)

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
            if self.shell.handle_key(keyval):
                return True
            if keyval == Gdk.KEY_Escape and self.detail_host.get_visible():
                self.close_detail()
                return True
            return False

        def _set_dark(self, dark: bool) -> None:
            self.dark = dark
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

        def _clear(self, box: Gtk.Box) -> None:
            child = box.get_first_child()
            while child is not None:
                nxt = child.get_next_sibling()
                box.remove(child)
                child = nxt

        def _heading(self, title: str, sub: str | None = None) -> Gtk.Widget:
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            box.add_css_class("chooser-heading")
            t = Gtk.Label(label=title, xalign=0)
            t.add_css_class("heading-title")
            box.append(t)
            if sub:
                s = Gtk.Label(label=sub, xalign=0)
                s.add_css_class("heading-sub")
                box.append(s)
            return box

        def _render_main(self) -> None:
            self._clear(self.main_box)
            p = self.payload
            shop = p.retailer.name if p.retailer else "this device"
            support = p.retailer.support if p.retailer else None

            if p.errors and p.retailer is None and not p.recommended and not p.catalog:
                note = Gtk.Label(
                    label="This image has no usable payload.\n"
                    + "\n".join(p.errors[:6])
                )
                note.set_justify(Gtk.Justification.CENTER)
                note.add_css_class("error-note")
                self.main_box.append(note)
                return

            self.main_box.append(
                self._heading(
                    f"Recommended by {shop}",
                    f"Install support: {support}" if support else None,
                )
            )

            if p.recommended:
                self.main_box.append(self._card_rows(p.recommended))
            else:
                empty = Gtk.Label(
                    label="No recommended distributions are listed on this image.",
                    xalign=0,
                )
                empty.add_css_class("empty-note")
                self.main_box.append(empty)

            if p.others:
                other = self._heading("Other distros")
                other.add_css_class("catalog-heading")
                self.main_box.append(other)
                catalog = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
                for distro in p.others:
                    catalog.append(self._row(distro))
                if len(p.others) > 6:
                    scroll = Gtk.ScrolledWindow()
                    scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
                    scroll.set_min_content_height(200)
                    scroll.set_max_content_height(320)
                    scroll.set_propagate_natural_height(True)
                    scroll.set_child(catalog)
                    self.main_box.append(scroll)
                else:
                    self.main_box.append(catalog)

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

        def _card_rows(self, distros: list[Distro]) -> Gtk.Widget:
            col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
            col.set_valign(Gtk.Align.START)
            for i in range(0, len(distros), 5):
                row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
                row.set_halign(Gtk.Align.START)
                for distro in distros[i : i + 5]:
                    row.append(self._card(distro))
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

        def _row(self, distro: Distro) -> Gtk.Widget:
            btn = Gtk.Button()
            btn.add_css_class("catalog-row")
            btn.set_has_frame(False)
            btn.set_hexpand(True)
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
            row.append(self._logo_image(distro.id, 40))
            name = Gtk.Label(label=distro.name, xalign=0)
            name.add_css_class("row-name")
            name.set_hexpand(True)
            row.append(name)
            meta = Gtk.Label(label=distro.version)
            meta.add_css_class("row-meta")
            row.append(meta)
            btn.set_child(row)
            btn.connect("clicked", lambda *_: self.open_detail(distro, from_catalog=True))
            return btn

        def open_detail(self, distro: Distro, *, from_catalog: bool) -> None:
            self.shell.close_menus()
            self.detail_distro = distro
            self.detail_from_catalog = from_catalog
            self._clear(self.detail_host)

            wrap = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            wrap.set_margin_start(16)
            wrap.set_margin_end(16)

            back = Gtk.Button(label="←  Back")
            back.add_css_class("back-link")
            back.set_has_frame(False)
            back.set_halign(Gtk.Align.START)
            back.connect("clicked", lambda *_: self.close_detail())
            wrap.append(back)

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

            wrap.append(card)
            self.detail_host.append(wrap)
            self.dimmer.set_visible(True)
            self.dimmer.queue_draw()
            self.detail_host.set_visible(True)

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
            self.detail_distro = None
            self.dimmer.set_visible(False)
            self.detail_host.set_visible(False)
            self._clear(self.detail_host)

        def _act(self, distro: Distro, ed: Edition) -> None:
            if ed.on_disk:
                self._toast(
                    f"Install is not available yet ({distro.name} {ed.name})."
                )
            else:
                self._toast(
                    f"Download is not available yet ({distro.name} {ed.name})."
                )

        def _toast(self, text: str) -> None:
            self.toasts.add_toast(Adw.Toast.new(text))

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
            open_catalog,
            open_menu,
            light,
        ).run(None)
    )


def _power(action: str) -> None:
    cmd = ["systemctl", action]
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
        "--catalog-detail",
        action="store_true",
        help="open --open as an Other distros popover (DE rows)",
    )
    parser.add_argument(
        "--menu",
        choices=("qs", "network", "apps", "power"),
        help="open a shell menu (host/CI screenshots)",
    )
    parser.add_argument(
        "--light",
        action="store_true",
        help="start in the light style",
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
        open_catalog=args.catalog_detail,
        open_menu=args.menu,
        light=args.light,
    )


if __name__ == "__main__":
    raise SystemExit(main())
