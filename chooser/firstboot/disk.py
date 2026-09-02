"""Shop-install disk discovery. USB → internal copy (step 8)."""

from __future__ import annotations

import errno
import json
import os
import re
import subprocess
from dataclasses import dataclass, field

from firstboot.i18n import _

SKIP_PREFIXES = ("loop", "ram", "sr", "zram", "fd", "md", "dm-")
LIVE_MOUNTS = ("/cdrom", "/run/live/medium", "/lib/live/mount/medium")
PAYLOAD_MOUNT = "/run/payload"
ESP_MIB_DEFAULT = 512
SYS_MIB_DEFAULT = 2048
SLACK_BYTES = 64 * 1024 * 1024
MIB = 1024 * 1024


@dataclass(frozen=True)
class Partition:
    path: str
    size: int
    label: str = ""
    partlabel: str = ""
    fstype: str = ""
    mountpoints: tuple[str, ...] = ()

    def named(self, *names: str) -> bool:
        want = {n.lower() for n in names}
        return self.label.lower() in want or self.partlabel.lower() in want


@dataclass(frozen=True)
class Disk:
    path: str
    size: int
    model: str = ""
    removable: bool = False
    usb: bool = False
    transport: str = ""
    parts: tuple[Partition, ...] = ()

    @property
    def name(self) -> str:
        return os.path.basename(self.path)

    def part_named(self, *names: str) -> Partition | None:
        for part in self.parts:
            if part.named(*names):
                return part
        return None

    def is_install_media(self) -> bool:
        if os.environ.get("FIRSTBOOT_SHOP_INSTALL") == "1":
            return True
        return self.usb or self.removable


@dataclass(frozen=True)
class InstallPlan:
    available: bool
    reason: str = ""
    source: Disk | None = None
    target: Disk | None = None
    esp_bytes: int = ESP_MIB_DEFAULT * MIB
    sys_bytes: int = SYS_MIB_DEFAULT * MIB
    data_need_bytes: int = 0

    @property
    def need_bytes(self) -> int:
        return self.esp_bytes + self.sys_bytes + self.data_need_bytes + SLACK_BYTES

    def as_dict(self) -> dict:
        return {
            "available": self.available,
            "reason": self.reason,
            "source": self.source.path if self.source else "",
            "target": self.target.path if self.target else "",
            "source_model": self.source.model if self.source else "",
            "target_model": self.target.model if self.target else "",
            "target_size": self.target.size if self.target else 0,
            "need_bytes": self.need_bytes,
            "esp_bytes": self.esp_bytes,
            "sys_bytes": self.sys_bytes,
            "data_need_bytes": self.data_need_bytes,
        }


def skip_name(name: str) -> bool:
    base = name.rsplit("/", 1)[-1]
    return any(base == p or base.startswith(p) for p in SKIP_PREFIXES)


def parent_disk_name(dev: str) -> str:
    base = os.path.basename(dev)
    if base.startswith(("nvme", "mmcblk", "loop", "nbd")):
        i = base.rfind("p")
        if i > 0 and base[i + 1 :].isdigit():
            return base[:i]
        return base
    for i in range(len(base) - 1, -1, -1):
        if not base[i].isdigit():
            return base[: i + 1]
    return base


def part_path(disk: str, n: int) -> str:
    name = os.path.basename(disk)
    if name and name[-1].isdigit():
        return f"{disk}p{n}"
    return f"{disk}{n}"


def format_size(n: int) -> str:
    gib = 1024 * 1024 * 1024
    if n >= gib:
        return f"{n / gib:.1f} GB"
    mib = 1024 * 1024
    if n >= mib:
        return f"{n / mib:.0f} MB"
    return f"{n} B"


def bytes_to_mib(n: int) -> int:
    return max(1, (n + MIB - 1) // MIB)


def dir_bytes(path: str) -> int:
    total = 0
    if not path or not os.path.isdir(path):
        return 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            fp = os.path.join(root, name)
            try:
                total += os.path.getsize(fp)
            except OSError:
                pass
    return total


def parse_mountinfo(text: str) -> dict[str, str]:
    """mountpoint → source device (last wins, like the kernel)."""
    out: dict[str, str] = {}
    for raw in text.splitlines():
        if " - " not in raw:
            continue
        left, right = raw.split(" - ", 1)
        lparts = left.split()
        rparts = right.split()
        if len(lparts) < 5 or len(rparts) < 2:
            continue
        mp = lparts[4].replace("\\040", " ")
        src = rparts[1]
        out[mp] = src
    return out


def parse_lsblk(data: dict) -> list[Disk]:
    disks: list[Disk] = []
    for raw in data.get("blockdevices") or []:
        disk = _parse_disk(raw)
        if disk is not None:
            disks.append(disk)
    return disks


def _parse_disk(raw: dict) -> Disk | None:
    if raw.get("type") not in (None, "disk"):
        return None
    path = raw.get("path") or raw.get("name") or ""
    if not path.startswith("/"):
        path = "/dev/" + path
    name = os.path.basename(path)
    if skip_name(name):
        return None
    try:
        size = int(raw.get("size") or 0)
    except (TypeError, ValueError):
        size = 0
    if size <= 0:
        return None
    tran = (raw.get("tran") or "").lower()
    rm = _truthy(raw.get("rm"))
    usb = tran == "usb" or _sys_is_usb(name)
    parts = tuple(
        p
        for child in raw.get("children") or []
        if (p := _parse_part(child)) is not None
    )
    model = (raw.get("model") or "").strip()
    return Disk(
        path=path,
        size=size,
        model=model,
        removable=rm,
        usb=usb,
        transport=tran,
        parts=parts,
    )


def _parse_part(raw: dict) -> Partition | None:
    if raw.get("type") not in (None, "part"):
        return None
    path = raw.get("path") or raw.get("name") or ""
    if not path.startswith("/"):
        path = "/dev/" + path
    try:
        size = int(raw.get("size") or 0)
    except (TypeError, ValueError):
        size = 0
    mps = raw.get("mountpoints")
    if mps is None:
        mp = raw.get("mountpoint")
        mountpoints = (mp,) if mp else ()
    else:
        mountpoints = tuple(m for m in mps if m)
    return Partition(
        path=path,
        size=size,
        label=(raw.get("label") or "").strip(),
        partlabel=(raw.get("partlabel") or "").strip(),
        fstype=(raw.get("fstype") or "").strip(),
        mountpoints=mountpoints,
    )


def _truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes"}
    return False


def _sys_is_usb(name: str) -> bool:
    link = os.path.join("/sys/block", name, "device")
    try:
        target = os.path.realpath(link)
    except OSError:
        return False
    return "/usb" in target


def disk_for_device(disks: list[Disk], dev: str) -> Disk | None:
    if not dev or not dev.startswith("/dev/"):
        return None
    parent = parent_disk_name(dev)
    for disk in disks:
        if disk.name == parent or os.path.basename(disk.path) == parent:
            return disk
        if disk.path == dev:
            return disk
    return None


def live_media_from_cmdline(cmdline: str) -> str | None:
    for tok in cmdline.split():
        if tok.startswith("live-media="):
            val = tok.split("=", 1)[1]
            return val or None
    return None


def payload_fstab_spec(
    sys_dev: str | None, data_parts: list[tuple[str, str]]
) -> str:
    """fstab source for /run/payload. Prefer FBL-DATA on the live SYS disk."""
    if sys_dev:
        parent = parent_disk_name(sys_dev)
        for path, uuid in data_parts:
            if parent_disk_name(path) == parent and uuid:
                return f"UUID={uuid}"
    return "LABEL=FBL-DATA"


def find_usb_fbl(disks: list[Disk]) -> Disk | None:
    """Shop stick: removable/USB with FBL-SYS + FBL-DATA."""
    for disk in disks:
        if not disk.is_install_media():
            continue
        if disk.part_named("FBL-SYS") is None or disk.part_named("FBL-DATA") is None:
            continue
        return disk
    return None


def find_source_disk(disks: list[Disk], mounts: dict[str, str]) -> Disk | None:
    # Prefer a plugged-in FBL USB. After a shop install both disks have
    # FBL-SYS; casper's by-label live-media often binds /cdrom to the
    # *internal* copy, which hid the install row.
    usb = find_usb_fbl(disks)
    if usb is not None:
        return usb
    for mp in (*LIVE_MOUNTS, PAYLOAD_MOUNT):
        src = mounts.get(mp)
        disk = disk_for_device(disks, src or "")
        if disk is not None:
            return disk
    return None


def find_target_disk(
    disks: list[Disk], source: Disk, need_bytes: int
) -> tuple[Disk | None, str]:
    candidates: list[Disk] = []
    for disk in disks:
        if disk.path == source.path:
            continue
        if disk.usb or disk.removable:
            continue
        if disk.size < need_bytes:
            continue
        candidates.append(disk)
    if not candidates:
        others = [d for d in disks if d.path != source.path]
        if not others:
            return None, _("No internal disk to install to.")
        biggest = max(others, key=lambda d: d.size)
        if biggest.usb or biggest.removable:
            return None, _("No internal disk to install to.")
        return None, (
            _("Internal disk is too small ({have}; need {need}).").format(
                have=format_size(biggest.size),
                need=format_size(need_bytes),
            )
        )
    candidates.sort(key=lambda d: d.size, reverse=True)
    return candidates[0], ""


def plan_sizes(source: Disk, payload_used: int) -> tuple[int, int, int]:
    esp = source.part_named("FBL-ESP")
    sys = source.part_named("FBL-SYS")
    data = source.part_named("FBL-DATA")
    esp_bytes = esp.size if esp and esp.size > 0 else ESP_MIB_DEFAULT * MIB
    sys_bytes = sys.size if sys and sys.size > 0 else SYS_MIB_DEFAULT * MIB
    if payload_used > 0:
        data_need = payload_used
    elif data is not None:
        data_need = data.size
    else:
        data_need = 0
    return esp_bytes, sys_bytes, data_need


def plan_install(
    disks: list[Disk],
    mounts: dict[str, str],
    payload_used: int = 0,
) -> InstallPlan:
    source = find_source_disk(disks, mounts)
    if source is None:
        return InstallPlan(False, _("Not running from a First Boot USB."))
    if not source.is_install_media():
        return InstallPlan(
            False,
            _("Install to this device is only available when booted from USB."),
            source=source,
        )
    if source.part_named("FBL-SYS") is None or source.part_named("FBL-DATA") is None:
        return InstallPlan(
            False,
            _("This USB does not look like a First Boot install drive."),
            source=source,
        )
    esp_bytes, sys_bytes, data_need = plan_sizes(source, payload_used)
    draft = InstallPlan(
        True,
        "",
        source=source,
        esp_bytes=esp_bytes,
        sys_bytes=sys_bytes,
        data_need_bytes=data_need,
    )
    target, reason = find_target_disk(disks, source, draft.need_bytes)
    if target is None:
        return InstallPlan(
            False,
            reason,
            source=source,
            esp_bytes=esp_bytes,
            sys_bytes=sys_bytes,
            data_need_bytes=data_need,
        )
    return InstallPlan(
        True,
        "",
        source=source,
        target=target,
        esp_bytes=esp_bytes,
        sys_bytes=sys_bytes,
        data_need_bytes=data_need,
    )


def read_lsblk_json(text: str) -> dict:
    return json.loads(text)


def live_lsblk() -> list[Disk]:
    try:
        proc = subprocess.run(
            [
                "lsblk",
                "-J",
                "-b",
                "-p",
                "-o",
                "NAME,PATH,TYPE,SIZE,RM,TRAN,MODEL,LABEL,PARTLABEL,FSTYPE,MOUNTPOINTS",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return []
    if proc.returncode != 0 or not proc.stdout.strip():
        return []
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return []
    return parse_lsblk(data)


def live_mounts() -> dict[str, str]:
    try:
        with open("/proc/self/mountinfo", encoding="utf-8") as fh:
            return parse_mountinfo(fh.read())
    except OSError:
        return {}


def live_plan(payload_root: str = PAYLOAD_MOUNT) -> InstallPlan:
    disks = live_lsblk()
    mounts = live_mounts()
    used = 0
    if payload_root and os.path.isdir(payload_root):
        src = mounts.get(os.path.abspath(payload_root)) or mounts.get(payload_root)
        if src and src.startswith("/dev/"):
            used = dir_bytes(payload_root)
    return plan_install(disks, mounts, used)


_RSYNC_PCT = re.compile(r"(?:^|\s)(\d+)%(?:\s|$)")


def rsync_percent(line: str) -> int | None:
    match = _RSYNC_PCT.search(line.replace(",", ""))
    if not match:
        return None
    pct = int(match.group(1))
    if 0 <= pct <= 100:
        return pct
    return None


def map_range(pct: int, lo: int, hi: int) -> int:
    if pct <= 0:
        return lo
    if pct >= 100:
        return hi
    return lo + (hi - lo) * pct // 100


@dataclass
class HelperEvent:
    kind: str
    text: str = ""
    progress: int | None = None
    tick: int | None = None
    tick_status: str | None = None
    ticks: tuple[str, ...] | None = None


def parse_helper_line(line: str) -> HelperEvent | None:
    text = line.strip()
    if not text:
        return None
    if text == "DONE":
        return HelperEvent("done", progress=100)
    if text == "REBOOT":
        return HelperEvent("reboot", progress=100)
    if text.startswith("ERROR"):
        msg = text[5:].lstrip(" :")
        return HelperEvent("error", text=msg or "Install failed.")
    if text.startswith("STEP"):
        return HelperEvent("step", text=text[4:].lstrip(" :"))
    if text.startswith("PROGRESS"):
        rest = text[8:].strip()
        try:
            return HelperEvent("progress", progress=int(rest.split()[0]))
        except (ValueError, IndexError):
            return None
    if text.startswith("TICKS"):
        rest = text[5:].lstrip(" :")
        labels = tuple(part for part in rest.split("|") if part)
        return HelperEvent("ticks", ticks=labels)
    if text.startswith("TICK"):
        parts = text.split()
        if len(parts) >= 3:
            try:
                return HelperEvent(
                    "tick", tick=int(parts[1]), tick_status=parts[2].lower()
                )
            except ValueError:
                return None
        return None
    return None


def emit(kind: str, *parts: object) -> None:
    try:
        if parts:
            print(kind, *parts, flush=True)
        else:
            print(kind, flush=True)
    except BrokenPipeError:
        pass
    except OSError as exc:
        if exc.errno != errno.EPIPE:
            raise
