"""Laptop battery from sysfs. Hidden when the machine has no pack."""

from __future__ import annotations

import os
from dataclasses import dataclass

from firstboot.i18n import _
from firstboot.volume import clamp_level

SYS_POWER = "/sys/class/power_supply"
LOW_PERCENT = 20
CRITICAL_PERCENT = 10
COLOR_LOW = "#f6d32d"
COLOR_CRITICAL = "#e01b24"
AC_TYPES = frozenset({"Mains", "USB", "BrickID", "Wireless"})

_FILL_X = 2.25
_FILL_Y = 6.25
_FILL_H = 3.5
_FILL_MAX_W = 9.0


@dataclass(frozen=True)
class BatteryState:
    present: bool = False
    percent: int = 0
    status: str = "unknown"
    on_ac: bool = False

    @property
    def charging(self) -> bool:
        if self.status == "discharging":
            return False
        return self.status in {"charging", "full", "not charging"} or self.on_ac

    @property
    def full(self) -> bool:
        return self.status == "full" or (self.charging and self.percent >= 100)

    @property
    def low(self) -> bool:
        return self.present and not self.charging and self.percent <= LOW_PERCENT

    @property
    def critical(self) -> bool:
        return self.present and not self.charging and self.percent <= CRITICAL_PERCENT

    @property
    def color(self) -> str | None:
        if self.critical:
            return COLOR_CRITICAL
        if self.low:
            return COLOR_LOW
        return None

    @property
    def label(self) -> str:
        if not self.present:
            return ""
        return f"{self.percent}%"

    def tooltip(self) -> str:
        if not self.present:
            return ""
        if self.full:
            return _("Fully charged")
        if self.charging:
            return _("Charging — {n}%").format(n=self.percent)
        if self.low:
            return _("Battery low — {n}%").format(n=self.percent)
        return _("Battery {n}%").format(n=self.percent)


def battery_svg(*, percent: int, charging: bool) -> str:
    """16×16 symbolic: horizontal pack, fill by percent, bolt cutout when charging."""
    pct = clamp_level(percent)
    fill_w = _FILL_MAX_W * pct / 100
    parts: list[str] = []
    if fill_w >= 0.35:
        parts.append(
            f"M{_FILL_X} {_FILL_Y}h{fill_w:.2f}v{_FILL_H}h{-fill_w:.2f}z"
        )
    if charging:
        parts.append("M9.05 6.15 6.55 8.45h1.7L7.15 9.85 9.7 7.5H8z")
    body = ""
    if parts:
        body = f'<path fill-rule="evenodd" d="{" ".join(parts)}"/>'
    return (
        '<svg viewBox="0 0 16 16" xmlns="http://www.w3.org/2000/svg">'
        '<g fill="gray">'
        '<path fill-rule="evenodd" d="M1.5 4.5h11A1.5 1.5 0 0 1 14 6v4a1.5 '
        "1.5 0 0 1-1.5 1.5h-11A1.5 1.5 0 0 1 0 10V6a1.5 1.5 0 0 1 1.5-1.5zm1 "
        "1.5h9a.5.5 0 0 1 .5.5v3a.5.5 0 0 1-.5.5h-9a.5.5 0 0 1-.5-.5v-3a.5.5 "
        '0 0 1 .5-.5z"/>'
        '<rect x="14" y="6.5" width="2" height="3" rx="0.7"/>'
        f"{body}"
        "</g></svg>"
    )


def parse_fake_battery(text: str) -> BatteryState:
    raw = (text or "").strip().lower()
    if not raw or raw in {"none", "off", "no"}:
        return BatteryState()
    status = "discharging"
    on_ac = False
    num = raw
    if "," in raw:
        num, rest = raw.split(",", 1)
        rest = rest.strip()
        if rest in {"charging", "charge"}:
            status = "charging"
            on_ac = True
        elif rest == "full":
            status = "full"
            on_ac = True
        elif rest in {"ac", "plugged"}:
            status = "not charging"
            on_ac = True
    try:
        percent = clamp_level(int(num.strip()))
    except ValueError:
        return BatteryState()
    return BatteryState(True, percent, status, on_ac)


def read_battery(
    sys_power: str = SYS_POWER,
    env: dict[str, str] | None = None,
) -> BatteryState:
    src = os.environ if env is None else env
    fake = src.get("FIRSTBOOT_FAKE_BATTERY")
    if fake is not None:
        return parse_fake_battery(fake)
    if not os.path.isdir(sys_power):
        return BatteryState()
    try:
        names = sorted(os.listdir(sys_power))
    except OSError:
        return BatteryState()
    percents: list[int] = []
    statuses: list[str] = []
    on_ac = False
    for name in names:
        root = os.path.join(sys_power, name)
        kind = (_read(os.path.join(root, "type")) or "").strip()
        if kind in AC_TYPES:
            if (_read(os.path.join(root, "online")) or "").strip() == "1":
                on_ac = True
            continue
        if kind != "Battery":
            continue
        if (_read(os.path.join(root, "present")) or "1").strip() == "0":
            continue
        percent = _capacity(root)
        if percent is None:
            continue
        percents.append(percent)
        statuses.append((_read(os.path.join(root, "status")) or "Unknown").strip())
    if not percents:
        return BatteryState()
    percent = int(round(sum(percents) / len(percents)))
    return BatteryState(True, clamp_level(percent), _combine_status(statuses), on_ac)


def _combine_status(statuses: list[str]) -> str:
    folded = [s.lower() for s in statuses]
    if any(s == "charging" for s in folded):
        return "charging"
    if folded and all(s == "full" for s in folded):
        return "full"
    if any(s == "discharging" for s in folded):
        return "discharging"
    if any(s == "not charging" for s in folded):
        return "not charging"
    return folded[0] if folded else "unknown"


def _capacity(root: str) -> int | None:
    cap = _read_int(os.path.join(root, "capacity"))
    now = _read_int(os.path.join(root, "energy_now"))
    if now is None:
        now = _read_int(os.path.join(root, "charge_now"))
    full = _read_int(os.path.join(root, "energy_full"))
    if full is None:
        full = _read_int(os.path.join(root, "charge_full"))
    if now is not None and full and full > 0:
        from_energy = clamp_level(round(100 * max(0, now) / full))
        if cap is None or cap <= 0:
            return from_energy
    if cap is not None:
        return clamp_level(cap)
    return None


def _read_int(path: str) -> int | None:
    text = _read(path)
    if text is None:
        return None
    try:
        return int(text.strip().split()[0])
    except (ValueError, IndexError):
        return None


def _read(path: str) -> str | None:
    try:
        with open(path, encoding="ascii", errors="replace") as fh:
            text = fh.read().strip()
    except OSError:
        return None
    return text or None
