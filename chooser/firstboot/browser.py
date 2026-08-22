"""In-kiosk WebKitGTK browser. Support tool, not a desktop."""

from __future__ import annotations

import base64
import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from html import escape
from typing import Any

BROWSER_BIN = "firstboot-browser"

WEBKIT_API = "6.0"
BROWSER_WIDTH = 760
BROWSER_HEIGHT = 500
BROWSER_LEFT = 72
BROWSER_TOP = 64
BROWSER_LOG = "firstboot-browser.log"

# Skia CPU keeps i915 from using the GPU Skia path. Do not set
# WEBKIT_DISABLE_DMABUF_RENDERER or WEBKIT_DISABLE_COMPOSITING_MODE here:
# either one SIGSEGVs WebKit on youtube.com/watch (seed 0.6.29 laptop).
WEBKIT_SAFE_ENV = {
    "GSK_RENDERER": "cairo",
    "WEBKIT_SKIA_ENABLE_CPU_RENDERING": "1",
}
WEBKIT_UNSET_ENV = (
    "WEBKIT_DISABLE_DMABUF_RENDERER",
    "WEBKIT_DMABUF_RENDERER_FORCE_SHM",
    "WEBKIT_DISABLE_COMPOSITING_MODE",
)
HELPER_ENV = {
    **WEBKIT_SAFE_ENV,
    "LIBGL_ALWAYS_SOFTWARE": "1",
    "PYTHONUNBUFFERED": "1",
}


def drop_process_caps() -> None:
    """Clear process capabilities.

    firstboot-kiosk.service uses PAMName=login; pam_systemd raises ambient
    CAP_WAKE_ALARM. bubblewrap then exits: "Unexpected capabilities but not
    setuid". WebKit aborts the helper (SIGABRT). SSH has no ambient cap, so
    bwrap works there.
    """
    try:
        import ctypes
        import ctypes.util
    except Exception:
        return
    libname = ctypes.util.find_library("c")
    if not libname:
        return
    libc = ctypes.CDLL(libname, use_errno=True)
    PR_CAP_AMBIENT = 47
    PR_CAP_AMBIENT_CLEAR_ALL = 4
    libc.prctl(PR_CAP_AMBIENT, PR_CAP_AMBIENT_CLEAR_ALL, 0, 0, 0)

    class _CapHeader(ctypes.Structure):
        _fields_ = [("version", ctypes.c_uint32), ("pid", ctypes.c_int)]

    class _CapData(ctypes.Structure):
        _fields_ = [
            ("effective", ctypes.c_uint32),
            ("permitted", ctypes.c_uint32),
            ("inheritable", ctypes.c_uint32),
        ]

    header = _CapHeader(0x20080522, 0)
    data = (_CapData * 2)()
    libc.capset(ctypes.byref(header), data)


START_TITLE = "First Boot Linux"
START_URIS = frozenset({"", "about:blank", "about:start"})
SEARCH_ENGINES = (
    ("google", "Google", "https://www.google.com/", "google.png"),
    ("brave", "Brave", "https://search.brave.com/", "brave.png"),
    ("duckduckgo", "DuckDuckGo", "https://duckduckgo.com/", "duckduckgo.png"),
)


def start_html() -> str:
    from firstboot.assets import find_search_icon

    tiles: list[str] = []
    for _ident, name, url, icon in SEARCH_ENGINES:
        path = find_search_icon(icon)
        src = ""
        if path:
            with open(path, "rb") as fh:
                src = "data:image/png;base64," + base64.b64encode(fh.read()).decode(
                    "ascii"
                )
        tiles.append(
            '<a class="epi-engine" href="'
            + escape(url, quote=True)
            + '">'
            + '<img src="'
            + src
            + '" alt="">'
            + "<span>"
            + escape(name)
            + "</span></a>"
        )
    return (
        """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>First Boot Linux</title>
<style>
  html, body {
    margin: 0;
    height: 100%;
    overflow: hidden;
    background: #1c1c1c;
    color: #eef1f6;
    font-family: Cantarell, sans-serif;
  }
  body {
    display: flex;
    align-items: center;
    justify-content: center;
  }
  @media (prefers-color-scheme: light) {
    html, body { background: #f0f2f5; color: #1c1c1c; }
    p { color: #5e6772 !important; }
    .epi-engine:hover, .epi-engine:focus-visible { background: rgba(0,0,0,0.06); }
  }
  .epi-start {
    max-width: 420px;
    width: 100%;
    margin: 0 auto;
    padding: 12px 20px 28px;
    text-align: center;
  }
  p { margin: 0; color: #9aa3b2; line-height: 1.5; font-size: 0.95rem; }
  .epi-engines {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 6px 8px;
    margin: 28px 0 0;
  }
  .epi-engine {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 8px;
    min-width: 0;
    padding: 10px 4px 12px;
    border-radius: 16px;
    color: inherit;
    text-decoration: none;
  }
  .epi-engine:hover, .epi-engine:focus-visible {
    background: rgba(255,255,255,0.1);
  }
  .epi-engine img {
    width: 72px;
    height: 72px;
    object-fit: contain;
  }
  .epi-engine span {
    font-size: 0.75rem;
    font-weight: 500;
    line-height: 1.25;
  }
</style>
</head>
<body>
  <div class="epi-start">
    <p>Search or type an address.</p>
    <div class="epi-engines">"""
        + "".join(tiles)
        + """</div>
  </div>
</body>
</html>
"""
    )


START_HTML = start_html()


def apply_webkit_env() -> None:
    os.environ.update(WEBKIT_SAFE_ENV)
    for key in WEBKIT_UNSET_ENV:
        os.environ.pop(key, None)


def browser_command() -> str | None:
    here = os.path.dirname(os.path.abspath(__file__))
    sibling = os.path.abspath(os.path.join(here, "..", BROWSER_BIN))
    for cmd in (shutil.which(BROWSER_BIN), "/usr/bin/firstboot-browser", sibling):
        if cmd and os.path.isfile(cmd) and os.access(cmd, os.X_OK):
            return cmd
    return None


def browser_log_path(src: dict[str, str] | None = None) -> str:
    env = os.environ if src is None else src
    runtime = env.get("XDG_RUNTIME_DIR") or "/tmp"
    return os.path.join(runtime, BROWSER_LOG)


def launch_env(src: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ if src is None else src)
    env.update(HELPER_ENV)
    env.setdefault("GDK_BACKEND", "wayland")
    env.setdefault("GTK_USE_PORTAL", "0")
    env.setdefault("GSETTINGS_BACKEND", "memory")
    for key in WEBKIT_UNSET_ENV:
        env.pop(key, None)
    return env


def launch_browser(
    *, dark: bool = True, env: dict[str, str] | None = None
) -> tuple[str | None, subprocess.Popen | None]:
    cmd = browser_command()
    if not cmd:
        return "Web browser is not on this image yet.", None
    argv = [cmd]
    if not dark:
        argv.append("--light")
    log_file = None
    try:
        log_file = open(browser_log_path(env), "ab", buffering=0)
    except OSError:
        log_file = None
    try:
        proc = subprocess.Popen(
            argv,
            env=launch_env(env),
            stdin=subprocess.DEVNULL,
            stdout=log_file if log_file is not None else subprocess.DEVNULL,
            stderr=log_file if log_file is not None else subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as exc:
        return (exc.strerror or str(exc), None)
    finally:
        if log_file is not None:
            log_file.close()
    print(
        f"firstboot-chooser: spawned {cmd} pid={proc.pid} log={browser_log_path(env)}",
        file=sys.stderr,
        flush=True,
    )
    return None, proc


def webkit_available() -> bool:
    apply_webkit_env()
    try:
        import gi

        gi.require_version("WebKit", WEBKIT_API)
        from gi.repository import WebKit  # noqa: F401
    except (ImportError, ValueError):
        return False
    return True


def is_start_uri(uri: str | None) -> bool:
    if uri is None:
        return True
    return uri.strip() in START_URIS


def normalize_url(text: str) -> str | None:
    raw = (text or "").strip()
    if not raw or is_start_uri(raw):
        return None
    if "://" in raw or raw.startswith("about:"):
        return raw
    return "https://" + raw


def url_bar_text(uri: str | None) -> str:
    if is_start_uri(uri):
        return ""
    return uri or ""


def new_ephemeral_session():
    from gi.repository import WebKit

    session = WebKit.NetworkSession.new_ephemeral()
    session.set_persistent_credential_storage_enabled(False)
    return session


def make_webkit_view(session):
    from gi.repository import WebKit

    apply_webkit_env()
    settings = WebKit.Settings()
    settings.set_hardware_acceleration_policy(WebKit.HardwareAccelerationPolicy.NEVER)
    settings.set_enable_webgl(False)
    settings.set_enable_2d_canvas_acceleration(False)
    settings.set_enable_offline_web_application_cache(False)
    settings.set_enable_dns_prefetching(False)
    return WebKit.WebView(network_session=session, settings=settings)


def _action_uri(action: Any) -> str:
    if action is None:
        return ""
    try:
        req = action.get_request()
    except Exception:
        return ""
    if req is None:
        return ""
    return req.get_uri() or ""


class BrowserWindow:
    def __init__(
        self,
        *,
        get_window: Callable | None = None,
        on_toast: Callable[[str], None] | None = None,
        layer=None,
        host_window=None,
    ) -> None:
        self.get_window = get_window or (lambda: host_window)
        self.on_toast = on_toast or (lambda _t: None)
        self.layer = layer
        self.win = host_window
        self.frame = None
        self.view = None
        self.url = None
        self.title_lab = None
        self._close_img = None
        self._session = None
        self._toasts = None
        self._maxed = False
        self._placed = False
        self._started = False
        self._url_lock = False
        self._x = BROWSER_LEFT
        self._y = BROWSER_TOP
        self._header_drag = None

    @property
    def visible(self) -> bool:
        return bool(self.frame is not None and self.frame.get_visible())

    def build(self):
        from gi.repository import Gdk, Gtk, Pango

        from firstboot.assets import find_app_icon, find_status, symbolic_pixbuf
        from firstboot.floatlayer import HeaderDrag

        self.frame = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.frame.add_css_class("epi-window")
        if self.win is not None:
            self.frame.add_css_class("toplevel")
            self.frame.set_hexpand(True)
            self.frame.set_vexpand(True)
            self.frame.set_visible(True)
        else:
            self.frame.set_halign(Gtk.Align.START)
            self.frame.set_valign(Gtk.Align.START)
            self.frame.set_hexpand(False)
            self.frame.set_vexpand(False)
            self.frame.set_visible(False)
        self.frame.set_size_request(BROWSER_WIDTH, BROWSER_HEIGHT)
        self.frame.set_overflow(Gtk.Overflow.HIDDEN)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        header.add_css_class("term-headerbar")
        header.set_hexpand(True)

        title_wrap = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        title_wrap.add_css_class("term-title-wrap")
        title_wrap.set_hexpand(True)
        icon = Gtk.Image()
        icon.set_pixel_size(18)
        path = find_app_icon("epiphany.png")
        if path:
            icon.set_from_file(path)
        title_wrap.append(icon)
        self.title_lab = Gtk.Label(label=START_TITLE, xalign=0)
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

        if self.win is None:
            self._header_drag = HeaderDrag(self)
            self._header_drag.attach(header)
        else:
            self._attach_toplevel_drag(header)
        dbl = Gtk.GestureClick()
        dbl.connect("pressed", self._on_header_press)
        header.add_controller(dbl)

        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        toolbar.add_css_class("epi-toolbar")
        toolbar.set_hexpand(True)
        self.url = Gtk.Entry()
        self.url.add_css_class("epi-url")
        self.url.set_placeholder_text("Enter address")
        self.url.set_hexpand(True)
        self.url.set_input_purpose(Gtk.InputPurpose.URL)
        self.url.connect("activate", self._on_url_activate)
        toolbar.append(self.url)
        self.frame.append(toolbar)

        if webkit_available():
            self._session = new_ephemeral_session()
            self.view = make_webkit_view(self._session)
            self.view.add_css_class("epi-page")
            self.view.set_hexpand(True)
            self.view.set_vexpand(True)
            self.view.connect("notify::title", self._on_title)
            self.view.connect("notify::uri", self._on_uri)
            self.view.connect("create", self._on_create)
            self.view.connect("decide-policy", self._on_policy)
            self.view.connect("authenticate", self._on_authenticate)
            self.view.connect("permission-request", self._on_permission)
            self.view.connect("run-file-chooser", self._on_file_chooser)
            self.view.connect("web-process-terminated", self._on_web_process_terminated)
            self.frame.append(self.view)
        else:
            miss = Gtk.Label(label="Web browser is not on this image yet.")
            miss.add_css_class("term-missing")
            miss.set_hexpand(True)
            miss.set_vexpand(True)
            miss.set_valign(Gtk.Align.CENTER)
            self.frame.append(miss)
        if self.win is not None:
            from gi.repository import Adw

            self._toasts = Adw.ToastOverlay()
            self._toasts.set_child(self.frame)
            self.win.set_child(self._toasts)
        elif self.layer is not None:
            self.layer.place(self.frame, self._x, self._y)
        return self.frame

    def open(self) -> None:
        if self.frame is None:
            return
        if self.win is not None:
            if self.view is not None and not self._started:
                self._load_start()
                self._started = True
            self.win.present()
            self._focus()
            return
        if not self._placed:
            self._place_default()
            self._placed = True
        self.frame.set_visible(True)
        if self.layer is not None:
            self.layer.raise_child(self.frame)
        if self.view is not None and not self._started:
            self._load_start()
            self._started = True
        self._focus()

    def close(self) -> None:
        if self.win is not None:
            self.win.close()
            return
        if self.frame is None:
            return
        self.frame.set_visible(False)

    def toggle_max(self) -> None:
        if self.win is not None:
            if self.win.is_maximized():
                self.win.unmaximize()
                if self.frame is not None:
                    self.frame.remove_css_class("maximized")
            else:
                self.win.maximize()
                if self.frame is not None:
                    self.frame.add_css_class("maximized")
            self._focus()
            return
        if self.frame is None:
            return
        self._maxed = not self._maxed
        if self._maxed:
            self.frame.add_css_class("maximized")
            self.frame.set_hexpand(False)
            self.frame.set_vexpand(False)
            pw, ph = self._layer_size()
            self.frame.set_size_request(pw, ph)
            self._move(0, 0)
        else:
            self.frame.remove_css_class("maximized")
            self.frame.set_halign(Gtk.Align.START)
            self.frame.set_valign(Gtk.Align.START)
            self.frame.set_hexpand(False)
            self.frame.set_vexpand(False)
            self.frame.set_size_request(BROWSER_WIDTH, BROWSER_HEIGHT)
            self._move(self._x, self._y)
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
        from firstboot.floatlayer import clamp_pos

        pw, ph = self._layer_size()
        self._x, self._y = clamp_pos(BROWSER_LEFT, BROWSER_TOP, BROWSER_WIDTH, pw, ph)
        self._move(self._x, self._y)

    def _move(self, x: int, y: int) -> None:
        if self.frame is None:
            return
        if self.layer is not None:
            self.layer.place(self.frame, x, y)
            return
        self.frame.set_margin_start(x)
        self.frame.set_margin_top(y)

    def _layer_size(self) -> tuple[int, int]:
        if self.layer is not None:
            w, h = self.layer.get_width(), self.layer.get_height()
            if w > 0 and h > 0:
                return w, h
        parent = self.frame.get_parent() if self.frame is not None else None
        if parent is not None:
            w, h = parent.get_width(), parent.get_height()
            if w > 0 and h > 0:
                return w, h
        return 1280, 800

    def _focus(self) -> None:
        if self.view is not None and not is_start_uri(self.view.get_uri()):
            self.view.grab_focus()
            return
        if self.url is not None:
            self.url.grab_focus()

    def _load_start(self) -> None:
        if self.view is None:
            return
        self.view.load_html(start_html(), "about:blank")
        self._set_title(START_TITLE)
        self._set_url_bar("")

    def _load(self, uri: str) -> None:
        if self.view is None:
            return
        self.view.load_uri(uri)

    def _set_title(self, title: str) -> None:
        if self.title_lab is None:
            return
        self.title_lab.set_label(title or START_TITLE)

    def _set_url_bar(self, text: str) -> None:
        if self.url is None:
            return
        if self.url.has_focus():
            return
        if self.url.get_text() == text:
            return
        self._url_lock = True
        self.url.set_text(text)
        self._url_lock = False

    def _on_url_activate(self, entry) -> None:
        uri = normalize_url(entry.get_text())
        if uri is None:
            self._load_start()
            return
        self._load(uri)

    def _on_title(self, view, *_pspec) -> None:
        title = view.get_title() or START_TITLE
        if is_start_uri(view.get_uri()):
            title = START_TITLE
        self._set_title(title)

    def _on_uri(self, view, *_pspec) -> None:
        self._set_url_bar(url_bar_text(view.get_uri()))

    def _on_create(self, _view, action) -> None:
        uri = _action_uri(action)
        if uri:
            self._load(uri)
        return None

    def _on_policy(self, view, decision, decision_type) -> bool:
        from gi.repository import WebKit

        if decision_type == WebKit.PolicyDecisionType.NEW_WINDOW_ACTION:
            action = None
            if isinstance(decision, WebKit.NavigationPolicyDecision):
                action = decision.get_navigation_action()
            uri = _action_uri(action)
            if uri:
                self._load(uri)
            decision.ignore()
            return True
        if decision_type == WebKit.PolicyDecisionType.RESPONSE:
            if isinstance(decision, WebKit.ResponsePolicyDecision):
                if not decision.is_mime_type_supported():
                    decision.ignore()
                    self._notify("Downloads are not saved on this image.")
                    return True
        return False

    def _on_authenticate(self, _view, request) -> bool:
        request.cancel()
        return True

    def _on_permission(self, _view, request) -> bool:
        request.deny()
        return True

    def _on_file_chooser(self, _view, request) -> bool:
        request.cancel()
        return True

    def _on_web_process_terminated(self, _view, reason) -> None:
        from gi.repository import WebKit

        print(
            f"firstboot-browser: web process terminated reason={int(reason)}",
            file=sys.stderr,
            flush=True,
        )
        if reason == WebKit.WebProcessTerminationReason.CRASHED:
            self._notify("Web page stopped unexpectedly.")

    def _notify(self, text: str) -> None:
        if self._toasts is not None:
            from gi.repository import Adw

            self._toasts.add_toast(Adw.Toast.new(text))
            return
        self.on_toast(text)

    def _attach_toplevel_drag(self, header) -> None:
        from gi.repository import Gdk, Gtk

        drag = Gtk.GestureDrag()
        drag.set_button(1)

        def begin(gesture, x: float, y: float) -> None:
            widget = gesture.get_widget()
            if widget is not None:
                picked = widget.pick(x, y, Gtk.PickFlags.DEFAULT)
                cur = picked
                while cur is not None and cur is not widget:
                    if cur.has_css_class("term-wc"):
                        gesture.set_state(Gtk.EventSequenceState.DENIED)
                        return
                    cur = cur.get_parent()
            if self.win is not None and self.win.is_maximized():
                gesture.set_state(Gtk.EventSequenceState.DENIED)
                return
            native = self.win.get_native() if self.win is not None else None
            surface = native.get_surface() if native is not None else None
            device = gesture.get_device()
            event = gesture.get_current_event()
            stamp = event.get_time() if event is not None else Gdk.CURRENT_TIME
            sx, sy = x, y
            if event is not None:
                ok, px, py = event.get_position()
                if ok:
                    sx, sy = px, py
            if isinstance(surface, Gdk.Toplevel) and device is not None:
                surface.begin_move(device, 1, sx, sy, stamp)

        drag.connect("drag-begin", begin)
        header.add_controller(drag)

    def _on_header_press(self, _g, n_press: int, *_xy) -> None:
        if n_press == 2:
            self.toggle_max()


def run_browser(argv: list[str] | None = None) -> int:
    os.environ.update(HELPER_ENV)
    apply_webkit_env()

    argv = list(sys.argv[1:] if argv is None else argv)
    light = "--light" in argv

    import gi

    gi.require_version("Gdk", "4.0")
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gdk, Gtk

    from firstboot.style import CSS

    class BrowserApp(Adw.Application):
        def __init__(self) -> None:
            super().__init__(application_id="org.firstboot.Browser")
            self.light = light
            self.connect("activate", self.on_activate)

        def on_activate(self, *_app) -> None:
            existing = self.get_active_window()
            if existing is not None:
                existing.present()
                return
            Adw.StyleManager.get_default().set_color_scheme(
                Adw.ColorScheme.FORCE_LIGHT if self.light else Adw.ColorScheme.FORCE_DARK
            )
            provider = Gtk.CssProvider()
            provider.load_from_data(CSS)
            display = Gdk.Display.get_default()
            if display is not None:
                Gtk.StyleContext.add_provider_for_display(
                    display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
                )
            win = Gtk.ApplicationWindow(application=self, title="Web browser")
            win.add_css_class("firstboot")
            if self.light:
                win.add_css_class("light")
            win.set_decorated(False)
            win.set_default_size(BROWSER_WIDTH, BROWSER_HEIGHT)
            page = BrowserWindow(host_window=win)
            page.build()
            page.apply_theme(not self.light)
            page.open()
            print("firstboot-browser: window presented", file=sys.stderr, flush=True)

    print("firstboot-browser: run", file=sys.stderr, flush=True)
    return int(BrowserApp().run(None))
