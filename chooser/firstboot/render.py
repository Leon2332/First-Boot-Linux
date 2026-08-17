"""Pick GSK / wlroots renderers. Software on virtio / unknown; GPU on i915 etc."""

from __future__ import annotations

import os

SOFTWARE_DRIVERS = frozenset(
    {
        "virtio_gpu",
        "virtio-gpu",
        "bochs-drm",
        "qxl",
        "vmwgfx",
        "vboxvideo",
        "simple-framebuffer",
        "simpledrm",
        "vkms",
    }
)
HARDWARE_DRIVERS = frozenset(
    {
        "i915",
        "xe",
        "amdgpu",
        "radeon",
        "nouveau",
        "nvidia",
        "nvidia-drm",
    }
)
SYS_DRM = "/sys/class/drm"


def drm_card_names(sys_drm: str = SYS_DRM) -> list[str]:
    if not os.path.isdir(sys_drm):
        return []
    names: list[str] = []
    try:
        entries = os.listdir(sys_drm)
    except OSError:
        return []
    for name in sorted(entries):
        if not name.startswith("card"):
            continue
        rest = name[4:]
        if rest.isdigit():
            names.append(name)
    return names


def drm_driver(card: str, sys_drm: str = SYS_DRM) -> str:
    link = os.path.join(sys_drm, card, "device", "driver")
    try:
        return os.path.basename(os.path.realpath(link))
    except OSError:
        return ""


def drm_drivers(sys_drm: str = SYS_DRM) -> list[str]:
    out: list[str] = []
    for card in drm_card_names(sys_drm):
        name = drm_driver(card, sys_drm)
        if name and name not in out:
            out.append(name)
    return out


def force_software(env: dict[str, str] | None = None) -> bool | None:
    raw = (env if env is not None else os.environ).get("FIRSTBOOT_SOFTWARE_RENDER", "")
    val = raw.strip().lower()
    if val in {"1", "yes", "true", "on"}:
        return True
    if val in {"0", "no", "false", "off"}:
        return False
    return None


def use_software_render(
    drivers: list[str] | None = None,
    env: dict[str, str] | None = None,
) -> bool:
    forced = force_software(env)
    if forced is not None:
        return forced
    if drivers is None:
        drivers = drm_drivers()
    # Unknown / virtio / firmware FB stay software. Only known GPUs get GLES.
    return not any(d in HARDWARE_DRIVERS for d in drivers)


def renderer_env(
    drivers: list[str] | None = None,
    env: dict[str, str] | None = None,
) -> dict[str, str]:
    src = env if env is not None else os.environ
    out: dict[str, str] = {}
    software = use_software_render(drivers, src)
    if not src.get("GSK_RENDERER"):
        out["GSK_RENDERER"] = "cairo" if software else "ngl"
    if not src.get("WLR_RENDERER"):
        out["WLR_RENDERER"] = "pixman" if software else "gles2"
    return out


def emit_session_env() -> None:
    for key, val in renderer_env().items():
        print(f"export {key}={val}")
