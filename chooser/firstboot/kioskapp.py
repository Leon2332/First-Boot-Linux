"""Spawn kiosk tools as separate Wayland clients."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

from firstboot.browser import drop_process_caps

WEB_BINS = ("epiphany", "epiphany-browser")
CONSOLE_BINS = ("kgx",)
SYSINFO_BIN = "firstboot-sysinfo"

# GNOME Web SIGSEGVs youtube.com/watch if it inherits the old kiosk
# DMA-BUF-off + GSK ngl pair. Leave GTK's default renderer.
WEBKIT_CHILD_UNSET = (
    "WEBKIT_DISABLE_DMABUF_RENDERER",
    "WEBKIT_DMABUF_RENDERER_FORCE_SHM",
    "WEBKIT_DISABLE_COMPOSITING_MODE",
    "WEBKIT_SKIA_ENABLE_CPU_RENDERING",
    "LIBGL_ALWAYS_SOFTWARE",
    "GSK_RENDERER",
)


def resolve_command(*names: str) -> str | None:
    here = os.path.dirname(os.path.abspath(__file__))
    sibling_dir = os.path.abspath(os.path.join(here, ".."))
    for name in names:
        sibling = os.path.join(sibling_dir, name)
        for cmd in (sibling, f"/usr/bin/{name}", shutil.which(name)):
            if not cmd:
                continue
            if "/snap/" in cmd:
                continue
            if os.path.isfile(cmd) and os.access(cmd, os.X_OK):
                return cmd
    return None


def child_env(*, unset: tuple[str, ...] = ()) -> dict[str, str]:
    env = dict(os.environ)
    env.setdefault("GDK_BACKEND", "wayland")
    env.setdefault("GTK_A11Y", "none")
    env.setdefault("NO_AT_BRIDGE", "1")
    env["GTK_USE_PORTAL"] = "0"
    env["PYTHONUNBUFFERED"] = "1"
    # dconf so Dark Style and default-browser settings reach GNOME apps.
    env.pop("GSETTINGS_BACKEND", None)
    for key in unset:
        env.pop(key, None)
    return env


def spawn_app(
    argv: list[str],
    *,
    env: dict[str, str] | None = None,
    log_name: str = "firstboot-app.log",
) -> tuple[str | None, subprocess.Popen | None]:
    runtime = os.environ.get("XDG_RUNTIME_DIR") or "/tmp"
    log_path = os.path.join(runtime, log_name)
    log_file = None
    try:
        log_file = open(log_path, "ab", buffering=0)
    except OSError:
        log_file = None
    try:
        proc = subprocess.Popen(
            argv,
            env=env if env is not None else child_env(),
            stdin=subprocess.DEVNULL,
            stdout=log_file if log_file is not None else subprocess.DEVNULL,
            stderr=log_file if log_file is not None else subprocess.DEVNULL,
            start_new_session=True,
            preexec_fn=drop_process_caps,
        )
    except OSError as exc:
        return (exc.strerror or str(exc), None)
    finally:
        if log_file is not None:
            log_file.close()
    print(
        f"firstboot-chooser: spawned {argv[0]} pid={proc.pid} log={log_path}",
        file=sys.stderr,
        flush=True,
    )
    return None, proc


def launch_web() -> tuple[str | None, subprocess.Popen | None]:
    cmd = resolve_command(*WEB_BINS)
    if not cmd:
        return "Web browser is not on this image yet.", None
    return spawn_app(
        [cmd],
        env=child_env(unset=WEBKIT_CHILD_UNSET),
        log_name="firstboot-web.log",
    )


def launch_console() -> tuple[str | None, subprocess.Popen | None]:
    cmd = resolve_command(*CONSOLE_BINS)
    if not cmd:
        return "Terminal is not on this image yet.", None
    return spawn_app([cmd], log_name="firstboot-console.log")


def launch_sysinfo(*, dark: bool = True) -> tuple[str | None, subprocess.Popen | None]:
    del dark  # libadwaita follows org.gnome.desktop.interface color-scheme
    cmd = resolve_command(SYSINFO_BIN)
    if not cmd:
        return "System details is not on this image yet.", None
    return spawn_app([cmd], log_name="firstboot-sysinfo.log")
