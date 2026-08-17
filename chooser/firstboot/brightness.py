"""Screen brightness via sysfs backlight. Memory fallback on the host."""

from __future__ import annotations

import os
from dataclasses import dataclass

from firstboot.volume import clamp_level

SYS_BACKLIGHT = "/sys/class/backlight"


@dataclass
class BrightnessState:
    level: int
    available: bool = True

    @property
    def icon(self) -> str:
        return "display-brightness-symbolic.svg"


class Brightness:
    def get(self) -> BrightnessState:
        raise NotImplementedError

    def set_level(self, level: int) -> BrightnessState:
        raise NotImplementedError


class MemoryBrightness(Brightness):
    def __init__(self, level: int = 100, available: bool = False) -> None:
        self._level = clamp_level(level)
        self._available = available

    def get(self) -> BrightnessState:
        return BrightnessState(self._level, self._available)

    def set_level(self, level: int) -> BrightnessState:
        self._level = clamp_level(level)
        return self.get()


class SysfsBrightness(Brightness):
    def __init__(self, root: str) -> None:
        self.root = root
        self._max = _read_int(os.path.join(root, "max_brightness")) or 1

    def get(self) -> BrightnessState:
        raw = _read_int(os.path.join(self.root, "actual_brightness"))
        if raw is None:
            raw = _read_int(os.path.join(self.root, "brightness")) or 0
        return BrightnessState(raw_to_level(raw, self._max), True)

    def set_level(self, level: int) -> BrightnessState:
        n = clamp_level(level)
        path = os.path.join(self.root, "brightness")
        value = level_to_raw(n, self._max)
        with open(path, "w", encoding="ascii") as fh:
            fh.write(str(value))
        return BrightnessState(n, True)


def raw_to_level(raw: int, maximum: int) -> int:
    if maximum <= 0:
        return 0
    return clamp_level(round(100 * max(0, raw) / maximum))


def level_to_raw(level: int, maximum: int) -> int:
    if maximum <= 0:
        return 0
    return max(0, min(maximum, round(clamp_level(level) * maximum / 100)))


def pick_backlight(sys_backlight: str = SYS_BACKLIGHT) -> str | None:
    if not os.path.isdir(sys_backlight):
        return None
    try:
        names = sorted(os.listdir(sys_backlight))
    except OSError:
        return None
    preferred = [n for n in names if n.startswith("intel_backlight")]
    order = preferred + [n for n in names if n not in preferred]
    for name in order:
        root = os.path.join(sys_backlight, name)
        if _read_int(os.path.join(root, "max_brightness")):
            return root
    return None


def get_brightness_backend() -> Brightness:
    root = pick_backlight()
    if root is None:
        return MemoryBrightness()
    bright = os.path.join(root, "brightness")
    if not os.access(bright, os.W_OK):
        return MemoryBrightness()
    try:
        backend = SysfsBrightness(root)
        backend.get()
        return backend
    except OSError:
        return MemoryBrightness()


def _read_int(path: str) -> int | None:
    try:
        with open(path, encoding="ascii") as fh:
            return int(fh.read().strip())
    except (OSError, ValueError):
        return None
