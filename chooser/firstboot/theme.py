"""Session color-scheme and default browser for spawned GNOME apps."""

from __future__ import annotations

import os
import subprocess
import sys

INTERFACE_SCHEMA = "org.gnome.desktop.interface"
CONSOLE_SCHEMA = "org.gnome.Console"
EPIPHANY_SCHEMA = "org.gnome.Epiphany"
EPIPHANY_DESKTOP = "org.gnome.Epiphany.desktop"
CURSOR_THEME = "First Boot Cursor"
CURSOR_SIZE = 24

MIME_DEFAULTS = (
    ("text/html", EPIPHANY_DESKTOP),
    ("application/xhtml+xml", EPIPHANY_DESKTOP),
    ("x-scheme-handler/http", EPIPHANY_DESKTOP),
    ("x-scheme-handler/https", EPIPHANY_DESKTOP),
)


def config_home(env: dict[str, str] | None = None) -> str:
    src = os.environ if env is None else env
    explicit = src.get("XDG_CONFIG_HOME")
    if explicit:
        return explicit
    home = src.get("HOME") or os.path.expanduser("~")
    return os.path.join(home, ".config")


def apply_session_theme(dark: bool, env: dict[str, str] | None = None) -> None:
    """Publish light/dark so libadwaita apps follow the QS Dark Style tile."""
    scheme = "prefer-dark" if dark else "prefer-light"
    _set_gsettings(INTERFACE_SCHEMA, "color-scheme", scheme, env)
    _write_gtk_settings(dark, env)
    apply_gtk_interface_scheme(dark)
    if os.environ.get("FIRSTBOOT_KIOSK"):
        apply_gtk_cursor()


def ensure_default_browser(env: dict[str, str] | None = None) -> None:
    from firstboot.browser import (
        DEFAULT_SEARCH_ENGINE,
        START_PAGE_URI,
        search_engine_providers_variant,
    )

    _set_gsettings(EPIPHANY_SCHEMA, "ask-for-default", False, env)
    _set_gsettings(EPIPHANY_SCHEMA, "homepage-url", START_PAGE_URI, env)
    _set_gsettings(EPIPHANY_SCHEMA, "default-search-engine", DEFAULT_SEARCH_ENGINE, env)
    _set_gsettings(
        EPIPHANY_SCHEMA, "incognito-search-engine", DEFAULT_SEARCH_ENGINE, env
    )
    _set_gsettings_variant(EPIPHANY_SCHEMA, "restore-session-policy", "crashed", env)
    _set_gsettings_variant(
        EPIPHANY_SCHEMA,
        "search-engine-providers",
        search_engine_providers_variant(),
        env,
    )
    _write_mimeapps(env)


def ensure_console_follows_system(env: dict[str, str] | None = None) -> None:
    # Schema default is night (Dark). QS Dark Style is the session control.
    _set_gsettings(CONSOLE_SCHEMA, "theme", "auto", env)


def apply_gtk_interface_scheme(dark: bool) -> None:
    """Push light/dark into Gtk.Settings so Adwaita CSD restyles with QS."""
    settings = _gtk_settings()
    if settings is None:
        return
    if settings.find_property("gtk-interface-color-scheme") is None:
        return
    try:
        from gi.repository import Gtk

        value = (
            Gtk.InterfaceColorScheme.DARK if dark else Gtk.InterfaceColorScheme.LIGHT
        )
        if settings.get_property("gtk-interface-color-scheme") != value:
            settings.set_property("gtk-interface-color-scheme", value)
    except Exception:
        return


def apply_gtk_cursor() -> None:
    settings = _gtk_settings()
    if settings is None:
        return
    try:
        if settings.find_property("gtk-cursor-theme-name") is not None:
            if settings.get_property("gtk-cursor-theme-name") != CURSOR_THEME:
                settings.set_property("gtk-cursor-theme-name", CURSOR_THEME)
        if settings.find_property("gtk-cursor-theme-size") is not None:
            if int(settings.get_property("gtk-cursor-theme-size") or 0) != CURSOR_SIZE:
                settings.set_property("gtk-cursor-theme-size", CURSOR_SIZE)
    except Exception:
        return


def _gtk_settings():
    try:
        import gi

        gi.require_version("Gtk", "4.0")
        from gi.repository import Gtk
    except Exception:
        return None
    return Gtk.Settings.get_default()


def _gsettings_env(env: dict[str, str] | None) -> dict[str, str]:
    out = dict(os.environ if env is None else env)
    out.pop("GSETTINGS_BACKEND", None)
    return out


def _set_gsettings(
    schema: str,
    key: str,
    value: object,
    env: dict[str, str] | None = None,
) -> None:
    try:
        from gi.repository import Gio
    except Exception:
        Gio = None
    if Gio is not None:
        try:
            source = Gio.SettingsSchemaSource.get_default()
            if source is not None:
                info = source.lookup(schema, True)
                if info is not None:
                    settings = Gio.Settings.new_full(info, None, None)
                    if isinstance(value, bool):
                        if settings.get_boolean(key) != value:
                            settings.set_boolean(key, value)
                    else:
                        text = str(value)
                        if settings.get_string(key) != text:
                            settings.set_string(key, text)
                    Gio.Settings.sync()
        except Exception:
            pass
    if isinstance(value, bool):
        cli_val = "true" if value else "false"
    else:
        text = str(value)
        cli_val = "'" + text.replace("\\", "\\\\").replace("'", "\\'") + "'"
    _gsettings_set(schema, key, cli_val, env)


def _set_gsettings_variant(
    schema: str,
    key: str,
    gvariant_text: str,
    env: dict[str, str] | None = None,
) -> None:
    try:
        from gi.repository import Gio, GLib
    except Exception:
        Gio = None
        GLib = None
    if Gio is not None and GLib is not None:
        try:
            source = Gio.SettingsSchemaSource.get_default()
            if source is not None:
                info = source.lookup(schema, True)
                if info is not None:
                    settings = Gio.Settings.new_full(info, None, None)
                    parsed = GLib.Variant.parse(None, gvariant_text, None, None)
                    if settings.get_value(key) != parsed:
                        settings.set_value(key, parsed)
                    Gio.Settings.sync()
        except Exception:
            pass
    _gsettings_set(schema, key, gvariant_text, env)


def _gsettings_set(
    schema: str,
    key: str,
    cli_val: str,
    env: dict[str, str] | None = None,
) -> None:
    try:
        subprocess.run(
            ["gsettings", "set", schema, key, cli_val],
            check=False,
            capture_output=True,
            text=True,
            timeout=4,
            env=_gsettings_env(env),
        )
    except (OSError, subprocess.TimeoutExpired):
        return


def _write_gtk_settings(dark: bool, env: dict[str, str] | None = None) -> None:
    flag = "true" if dark else "false"
    scheme = "dark" if dark else "light"
    body = (
        "[Settings]\n"
        "gtk-application-prefer-dark-theme=" + flag + "\n"
        "gtk-interface-color-scheme=" + scheme + "\n"
        "gtk-cursor-theme-name=" + CURSOR_THEME + "\n"
        "gtk-cursor-theme-size=" + str(CURSOR_SIZE) + "\n"
    )
    home = config_home(env)
    for sub in ("gtk-4.0", "gtk-3.0"):
        base = os.path.join(home, sub)
        try:
            os.makedirs(base, mode=0o700, exist_ok=True)
            path = os.path.join(base, "settings.ini")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(body)
            os.chmod(path, 0o644)
        except OSError as exc:
            print(
                f"firstboot-chooser: gtk settings {base}: {exc}",
                file=sys.stderr,
                flush=True,
            )


def _write_mimeapps(env: dict[str, str] | None = None) -> None:
    base = config_home(env)
    try:
        os.makedirs(base, mode=0o700, exist_ok=True)
        path = os.path.join(base, "mimeapps.list")
        lines = ["[Default Applications]\n"]
        for mime, desktop in MIME_DEFAULTS:
            lines.append(f"{mime}={desktop}\n")
        with open(path, "w", encoding="utf-8") as fh:
            fh.writelines(lines)
        os.chmod(path, 0o644)
    except OSError:
        return
