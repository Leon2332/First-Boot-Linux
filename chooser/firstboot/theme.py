"""Session color-scheme and default browser for spawned GNOME apps."""

from __future__ import annotations

import os

INTERFACE_SCHEMA = "org.gnome.desktop.interface"
EPIPHANY_SCHEMA = "org.gnome.Epiphany"
EPIPHANY_DESKTOP = "org.gnome.Epiphany.desktop"

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
    _set_gsettings(INTERFACE_SCHEMA, "color-scheme", scheme)
    _write_gtk_settings(dark, env)


def ensure_default_browser(env: dict[str, str] | None = None) -> None:
    _set_gsettings(EPIPHANY_SCHEMA, "ask-for-default", False)
    _write_mimeapps(env)


def _set_gsettings(schema: str, key: str, value: object) -> None:
    try:
        from gi.repository import Gio
    except Exception:
        return
    try:
        source = Gio.SettingsSchemaSource.get_default()
        if source is None:
            return
        info = source.lookup(schema, True)
        if info is None:
            return
        settings = Gio.Settings.new_full(info, None, None)
        if isinstance(value, bool):
            if settings.get_boolean(key) != value:
                settings.set_boolean(key, value)
            return
        text = str(value)
        if settings.get_string(key) != text:
            settings.set_string(key, text)
    except Exception:
        return


def _write_gtk_settings(dark: bool, env: dict[str, str] | None = None) -> None:
    base = os.path.join(config_home(env), "gtk-4.0")
    try:
        os.makedirs(base, exist_ok=True)
        path = os.path.join(base, "settings.ini")
        flag = "true" if dark else "false"
        body = "[Settings]\ngtk-application-prefer-dark-theme=" + flag + "\n"
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(body)
    except OSError:
        return


def _write_mimeapps(env: dict[str, str] | None = None) -> None:
    base = config_home(env)
    try:
        os.makedirs(base, exist_ok=True)
        path = os.path.join(base, "mimeapps.list")
        lines = ["[Default Applications]\n"]
        for mime, desktop in MIME_DEFAULTS:
            lines.append(f"{mime}={desktop}\n")
        with open(path, "w", encoding="utf-8") as fh:
            fh.writelines(lines)
    except OSError:
        return
