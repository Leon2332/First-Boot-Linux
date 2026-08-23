"""System details probe, in-kiosk window, and standalone helper."""

from __future__ import annotations

import os
import re
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from firstboot.disk import Disk, Partition, live_lsblk
from firstboot.render import drm_card_names

if TYPE_CHECKING:
    from gi.repository import Gtk

    from firstboot.payload import Retailer

INFO_WIDTH = 640
INFO_HEIGHT = 560
INFO_TOP = 48
WORDMARK_WIDTH = 260
WORDMARK_HEIGHT = 52
PCI_IDS_CANDIDATES = (
    "/usr/share/misc/pci.ids",
    "/usr/share/hwdata/pci.ids",
)
DMI_PLACEHOLDERS = frozenset(
    {
        "none",
        "n/a",
        "na",
        "not specified",
        "not applicable",
        "default string",
        "default",
        "to be filled by o.e.m.",
        "to be filled by oem",
        "system product name",
        "system version",
        "system manufacturer",
        "chassis version",
        "chassis manufacturer",
        "invalid",
        "unknown",
        "unset",
    }
)
VENDOR_SHORT = {
    0x1002: "AMD",
    0x1022: "AMD",
    0x8086: "Intel",
    0x10DE: "NVIDIA",
    0x1414: "Microsoft",
    0x15AD: "VMware",
    0x1A03: "ASPEED",
    0x1AF4: "Virtio",
    0x1234: "QEMU",
}
PREFERRED_MOUNTS = ("/", "/run/payload", "/home", "/cdrom")
SKIP_FSTYPE = frozenset({"vfat", "swap", "iso9660"})
_VERSION_RE = re.compile(r"^v?\d+(\.\d+)*[a-z]?$", re.I)
_SKU_RE = re.compile(r"^[A-Z0-9][A-Z0-9._-]{1,12}$", re.I)
_CONN_RE = re.compile(r"^card\d+-.+")
_MODE_RE = re.compile(r"(\d+)x(\d+)", re.I)
_CPU_AT_RE = re.compile(r"\s+CPU\s+@\s+\S+", re.I)

_pci_cache: dict[str, "PciDb"] = {}


@dataclass(frozen=True)
class Field:
    label: str
    value: str


@dataclass(frozen=True)
class Display:
    width: int
    height: int
    refresh_hz: int | None = None

    def format(self) -> str:
        text = f"{self.width}\u00d7{self.height}"
        if self.refresh_hz:
            return f"{text} @ {self.refresh_hz} Hz"
        return text


@dataclass(frozen=True)
class ProbePaths:
    sys_dmi: str = "/sys/class/dmi/id"
    sys_drm: str = "/sys/class/drm"
    meminfo: str = "/proc/meminfo"
    cpuinfo: str = "/proc/cpuinfo"
    os_release: str = "/etc/os-release"
    pci_ids: str | None = None


@dataclass(frozen=True)
class PciDb:
    vendors: dict[int, str]
    devices: dict[tuple[int, int], str]

    def lookup(self, vendor: int, device: int) -> tuple[str | None, str | None]:
        return self.vendors.get(vendor), self.devices.get((vendor, device))


@dataclass(frozen=True)
class SysInfo:
    model: str | None = None
    memory: str | None = None
    processor: str | None = None
    graphics: tuple[str, ...] = ()
    displays: tuple[Display, ...] = ()
    disks: tuple[Field, ...] = ()
    os: str | None = None
    os_type: str | None = None
    windowing: str | None = None
    kernel: str | None = None
    firmware: str | None = None

    def hardware_fields(self) -> tuple[Field, ...]:
        rows: list[Field] = []
        if self.model:
            rows.append(Field("Model", self.model))
        if self.memory:
            rows.append(Field("Memory", self.memory))
        if self.processor:
            rows.append(Field("Processor", self.processor))
        for i, name in enumerate(self.graphics):
            label = "Graphics" if i == 0 else f"Graphics {i}"
            rows.append(Field(label, name))
        for i, disp in enumerate(self.displays):
            label = "Display" if i == 0 else f"Display {i}"
            rows.append(Field(label, disp.format()))
        rows.extend(self.disks)
        return tuple(rows)

    def software_fields(self) -> tuple[Field, ...]:
        rows: list[Field] = []
        if self.os:
            rows.append(Field("Operating System", self.os))
        if self.os_type:
            rows.append(Field("OS Type", self.os_type))
        if self.windowing:
            rows.append(Field("Windowing System", self.windowing))
        if self.kernel:
            rows.append(Field("Kernel Version", self.kernel))
        if self.firmware:
            rows.append(Field("Firmware Version", self.firmware))
        return tuple(rows)


def paths_from_root(root: str) -> ProbePaths:
    return ProbePaths(
        sys_dmi=os.path.join(root, "sys", "class", "dmi", "id"),
        sys_drm=os.path.join(root, "sys", "class", "drm"),
        meminfo=os.path.join(root, "proc", "meminfo"),
        cpuinfo=os.path.join(root, "proc", "cpuinfo"),
        os_release=os.path.join(root, "etc", "os-release"),
        pci_ids=os.path.join(root, "pci.ids"),
    )


def collect(
    *,
    paths: ProbePaths | None = None,
    disks: list[Disk] | None = None,
    machine: str | None = None,
    kernel: str | None = None,
    env: dict[str, str] | None = None,
) -> SysInfo:
    paths = paths or ProbePaths()
    if machine is None or kernel is None:
        uname = os.uname()
        if machine is None:
            machine = uname.machine or None
        if kernel is None:
            kernel = uname.release or None
    if disks is None:
        try:
            disks = live_lsblk()
        except Exception:
            disks = []
    pci = load_pci_ids(find_pci_ids(paths.pci_ids))
    os_name = read_os_name(_read_text(paths.os_release) or "")
    return SysInfo(
        model=read_model(paths.sys_dmi),
        memory=read_memory(_read_text(paths.meminfo) or ""),
        processor=read_cpu(_read_text(paths.cpuinfo) or ""),
        graphics=read_graphics(paths.sys_drm, pci),
        displays=read_displays(paths.sys_drm),
        disks=disk_fields(disks),
        os=os_name,
        os_type=machine or None,
        windowing=windowing_system(env),
        kernel=format_kernel(kernel),
        firmware=_dmi_value(_read_text(os.path.join(paths.sys_dmi, "bios_version"))),
    )


def find_pci_ids(explicit: str | None = None) -> str | None:
    if explicit and os.path.isfile(explicit):
        return explicit
    for path in PCI_IDS_CANDIDATES:
        if os.path.isfile(path):
            return path
    return None


def load_pci_ids(path: str | None) -> PciDb | None:
    if not path:
        return None
    try:
        st = os.stat(path)
    except OSError:
        return None
    key = f"{path}:{st.st_mtime_ns}:{st.st_size}"
    cached = _pci_cache.get(key)
    if cached is not None:
        return cached
    db = parse_pci_ids(_read_text(path) or "")
    _pci_cache.clear()
    _pci_cache[key] = db
    return db


def parse_pci_ids(text: str) -> PciDb:
    vendors: dict[int, str] = {}
    devices: dict[tuple[int, int], str] = {}
    vendor: int | None = None
    for raw in text.splitlines():
        if not raw or raw.startswith("#"):
            continue
        if raw.startswith("\t\t"):
            continue
        if raw.startswith("\t"):
            if vendor is None:
                continue
            parts = raw.strip().split(None, 1)
            if len(parts) < 2:
                continue
            dev = parse_hex(parts[0])
            if dev is None:
                continue
            devices[(vendor, dev)] = parts[1].strip()
            continue
        parts = raw.split(None, 1)
        if len(parts) < 2:
            continue
        vid = parse_hex(parts[0])
        if vid is None:
            continue
        vendor = vid
        vendors[vid] = parts[1].strip()
    return PciDb(vendors, devices)


def parse_hex(text: str | None) -> int | None:
    if not text:
        return None
    raw = text.strip().lower()
    if raw.startswith("0x"):
        raw = raw[2:]
    try:
        return int(raw, 16)
    except ValueError:
        return None


def format_gib(n: int) -> str:
    return f"{n / (1024 ** 3):.1f} GiB"


def format_kernel(release: str | None) -> str | None:
    if not release:
        return None
    if release.lower().startswith("linux"):
        return release
    return f"Linux {release}"


def windowing_system(env: dict[str, str] | None = None) -> str:
    src = os.environ if env is None else env
    session = (src.get("XDG_SESSION_TYPE") or "").strip().lower()
    if session == "wayland" or src.get("WAYLAND_DISPLAY"):
        return "Wayland"
    if session == "x11" or src.get("DISPLAY"):
        return "X11"
    return "Wayland"


def tidy_cpu(name: str) -> str:
    text = (
        name.replace("(R)", "")
        .replace("(TM)", "")
        .replace("(C)", "")
        .replace("\u00ae", "")
        .replace("\u2122", "")
    )
    text = _CPU_AT_RE.sub("", text)
    return " ".join(text.split())


def parse_os_release(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        out[key] = value
    return out


def read_os_name(text: str) -> str | None:
    data = parse_os_release(text)
    pretty = (data.get("PRETTY_NAME") or "").strip()
    if pretty:
        return pretty
    bits = [data.get("NAME") or "", data.get("VERSION_ID") or ""]
    joined = " ".join(b for b in bits if b).strip()
    return joined or None


def read_memory(meminfo: str) -> str | None:
    for line in meminfo.splitlines():
        if not line.lower().startswith("memtotal:"):
            continue
        parts = line.split()
        if len(parts) < 2:
            return None
        try:
            kb = int(parts[1])
        except ValueError:
            return None
        if kb <= 0:
            return None
        return format_gib(kb * 1024)
    return None


def read_cpu(cpuinfo: str) -> str | None:
    hardware: str | None = None
    for line in cpuinfo.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().lower()
        value = value.strip()
        if not value:
            continue
        if key == "model name":
            return tidy_cpu(value) or None
        if key == "hardware" and hardware is None:
            hardware = value
        elif key == "processor" and hardware is None and not value.isdigit():
            hardware = value
    return tidy_cpu(hardware) if hardware else None


def _is_sku(name: str) -> bool:
    return bool(_SKU_RE.fullmatch(name))


def _is_marketing_version(version: str) -> bool:
    if not re.search(r"[A-Za-z]", version) or _VERSION_RE.fullmatch(version):
        return False
    if " " in version:
        return True
    return len(version) >= 8 and not re.search(r"\d", version)


def read_model(sys_dmi: str) -> str | None:
    vendor = _dmi_value(_read_text(os.path.join(sys_dmi, "sys_vendor")))
    name = _dmi_value(_read_text(os.path.join(sys_dmi, "product_name")))
    version = _dmi_value(_read_text(os.path.join(sys_dmi, "product_version")))
    family = _dmi_value(_read_text(os.path.join(sys_dmi, "product_family")))
    if version and _is_marketing_version(version) and (not name or _is_sku(name)):
        if vendor and vendor.lower() not in version.lower():
            return f"{vendor} {version}"
        return version
    if name:
        if vendor and vendor.lower() not in name.lower():
            return f"{vendor} {name}"
        return name
    if family:
        if vendor and vendor.lower() not in family.lower():
            return f"{vendor} {family}"
        return family
    return vendor


def gpu_label(vendor: int, device: int, pci: PciDb | None) -> str:
    vname, dname = (None, None)
    if pci is not None:
        vname, dname = pci.lookup(vendor, device)
    short = VENDOR_SHORT.get(vendor)
    if not short and vname:
        short = _bracket_or_first(vname)
        if short.upper() in {"AMD/ATI", "ATI"}:
            short = "AMD"
    pretty = _bracket_or_full(dname) if dname else ""
    if pretty and short:
        if pretty.lower().startswith(short.lower()):
            return pretty
        return f"{short} {pretty}"
    if pretty:
        return pretty
    if short:
        return f"{short} Device {device:04x}"
    return f"PCI {vendor:04x}:{device:04x}"


def read_graphics(sys_drm: str, pci: PciDb | None) -> tuple[str, ...]:
    out: list[str] = []
    seen: set[tuple[int, int]] = set()
    for card in drm_card_names(sys_drm):
        vendor = parse_hex(
            _read_text(os.path.join(sys_drm, card, "device", "vendor"))
        )
        device = parse_hex(
            _read_text(os.path.join(sys_drm, card, "device", "device"))
        )
        if vendor is None or device is None:
            continue
        key = (vendor, device)
        if key in seen:
            continue
        seen.add(key)
        out.append(gpu_label(vendor, device, pci))
    return tuple(out)


def parse_mode(text: str) -> tuple[int, int] | None:
    match = _MODE_RE.match(text.strip())
    if match is None:
        return None
    return int(match.group(1)), int(match.group(2))


def read_displays(sys_drm: str) -> tuple[Display, ...]:
    if not os.path.isdir(sys_drm):
        return ()
    try:
        entries = os.listdir(sys_drm)
    except OSError:
        return ()
    out: list[Display] = []
    for name in sorted(entries):
        if not _CONN_RE.match(name):
            continue
        if "writeback" in name.lower():
            continue
        root = os.path.join(sys_drm, name)
        status = (_read_text(os.path.join(root, "status")) or "").lower()
        if status != "connected":
            continue
        modes = _read_text(os.path.join(root, "modes")) or ""
        first = modes.splitlines()[0] if modes.splitlines() else ""
        parsed = parse_mode(first)
        if parsed is None:
            continue
        out.append(Display(parsed[0], parsed[1]))
    return tuple(out)


def apply_monitor_refresh(
    info: SysInfo,
    modes: list[tuple[int, int, int | None]],
) -> SysInfo:
    if not modes:
        return info
    if not info.displays:
        displays = tuple(
            Display(w, h, hz) for w, h, hz in modes if w > 0 and h > 0
        )
        return replace(info, displays=displays) if displays else info
    used = [False] * len(modes)
    updated: list[Display] = []
    for disp in info.displays:
        hz = disp.refresh_hz
        for i, (width, height, rate) in enumerate(modes):
            if used[i] or width != disp.width or height != disp.height:
                continue
            used[i] = True
            if rate:
                hz = rate
            break
        updated.append(Display(disp.width, disp.height, hz))
    return replace(info, displays=tuple(updated))


def transport_label(tran: str) -> str:
    key = (tran or "").strip().lower()
    if key == "nvme":
        return "NVMe"
    if key in {"sata", "ata", "ide"}:
        return "SATA"
    if key == "usb":
        return "USB"
    if key == "virtio":
        return "virtio"
    return key.upper() if key else ""


def primary_part(disk: Disk) -> Partition | None:
    for mount in PREFERRED_MOUNTS:
        for part in disk.parts:
            if mount in part.mountpoints:
                return part
    mounted = [p for p in disk.parts if p.mountpoints]
    if mounted:
        return max(mounted, key=lambda p: p.size)
    usable = [
        p
        for p in disk.parts
        if p.fstype and p.fstype.lower() not in SKIP_FSTYPE
    ]
    if usable:
        return max(usable, key=lambda p: p.size)
    return None


def disk_label(disk: Disk, part: Partition | None) -> str:
    if part is not None:
        if "/" in part.mountpoints:
            return "Disk (/)"
        for mount in part.mountpoints:
            if mount:
                return f"Disk ({mount})"
        if part.label:
            return f"Disk ({part.label})"
    return "Disk"


def unique_disk_label(label: str, disk: Disk, used: set[str]) -> str:
    if label not in used:
        used.add(label)
        return label
    alt = f"Disk ({os.path.basename(disk.path)})"
    if alt not in used:
        used.add(alt)
        return alt
    alt = f"Disk ({disk.path})"
    used.add(alt)
    return alt


def disk_value(disk: Disk, part: Partition | None) -> str:
    bits: list[str] = []
    tran = transport_label(disk.transport)
    if tran:
        bits.append(tran)
    size = format_gib(disk.size)
    if part is not None and part.fstype:
        bits.append(f"{size} ({part.fstype})")
    else:
        bits.append(size)
    return " - ".join(bits)


def disk_fields(disks: list[Disk]) -> tuple[Field, ...]:
    used: set[str] = set()
    rows: list[Field] = []
    for disk in disks:
        if disk.size <= 0:
            continue
        part = primary_part(disk)
        label = unique_disk_label(disk_label(disk, part), disk, used)
        rows.append(Field(label, disk_value(disk, part)))
    return tuple(rows)


def gdk_monitor_modes() -> list[tuple[int, int, int | None]]:
    try:
        from gi.repository import Gdk
    except ImportError:
        return []
    display = Gdk.Display.get_default()
    if display is None:
        return []
    monitors = display.get_monitors()
    out: list[tuple[int, int, int | None]] = []
    for i in range(monitors.get_n_items()):
        mon = monitors.get_item(i)
        if mon is None:
            continue
        geo = mon.get_geometry()
        raw = mon.get_refresh_rate()
        hz = round(raw / 1000) if raw else None
        if hz is not None and hz <= 0:
            hz = None
        out.append((geo.width, geo.height, hz))
    return out


def _read_text(path: str) -> str | None:
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            text = fh.read().strip()
    except OSError:
        return None
    return text or None


def _dmi_value(text: str | None) -> str | None:
    if text is None:
        return None
    folded = " ".join(text.split()).lower()
    if folded in DMI_PLACEHOLDERS:
        return None
    return " ".join(text.split())


def _bracket_or_first(name: str) -> str:
    match = re.search(r"\[([^\]]+)\]", name)
    if match:
        return match.group(1).split("/")[0].strip() or name.split()[0]
    return name.split(",")[0].split()[0]


def _bracket_or_full(name: str) -> str:
    match = re.search(r"\[([^\]]+)\]", name)
    if match:
        return match.group(1).strip()
    return name.strip()


class SysinfoWindow:
    def __init__(
        self,
        *,
        get_window: Callable | None = None,
        retailer: Retailer | None = None,
        layer=None,
        host_window=None,
    ) -> None:
        self.get_window = get_window or (lambda: host_window)
        self.retailer = retailer
        self.layer = layer
        self.win = host_window
        self.frame = None
        self._close_img = None
        self._cog_img = None
        self._brand = None
        self._hw_box = None
        self._sw_box = None
        self._retailer_box = None
        self._retailer_value = None
        self._dark = True
        self._maxed = False
        self._placed = False
        self._x = 0
        self._y = INFO_TOP
        self._header_drag = None
        self._gen = 0
        self._info: SysInfo | None = None

    @property
    def visible(self) -> bool:
        return bool(self.frame is not None and self.frame.get_visible())

    def build(self):
        from gi.repository import Gtk

        scroll = self._build_body_scroll()
        if self.win is not None:
            return self._build_adw_window(scroll)
        return self._build_kiosk_frame(scroll)

    def _build_body_scroll(self):
        from gi.repository import Gtk

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_hexpand(True)
        scroll.set_vexpand(True)

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        body.add_css_class("info-body")
        cols = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=28)
        cols.add_css_class("info-cols")
        cols.set_homogeneous(True)
        cols.set_hexpand(True)
        cols.set_size_request(INFO_WIDTH - 40, -1)

        hw = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        hw_h = Gtk.Label(label="Hardware Information", xalign=0)
        hw_h.add_css_class("info-heading")
        hw.append(hw_h)
        self._hw_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        hw.append(self._hw_box)
        cols.append(hw)

        sw = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        sw_h = Gtk.Label(label="Software Information", xalign=0)
        sw_h.add_css_class("info-heading")
        sw.append(sw_h)
        self._brand = Gtk.Picture()
        self._brand.add_css_class("info-sw-brand")
        self._brand.set_can_shrink(True)
        self._brand.set_content_fit(Gtk.ContentFit.CONTAIN)
        self._brand.set_halign(Gtk.Align.START)
        self._brand.set_valign(Gtk.Align.START)
        self._brand.set_hexpand(False)
        self._brand.set_vexpand(False)
        self._brand.set_size_request(WORDMARK_WIDTH, WORDMARK_HEIGHT)
        sw.append(self._brand)
        self._sw_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        sw.append(self._sw_box)
        self._retailer_box, self._retailer_value = self._make_field(
            "Configured by", ""
        )
        self._retailer_box.set_visible(False)
        sw.append(self._retailer_box)
        cols.append(sw)

        body.append(cols)
        scroll.set_child(body)
        return scroll

    def _build_adw_window(self, scroll):
        from gi.repository import Adw, Gtk

        header = Adw.HeaderBar()
        title = Gtk.Label(label="System details")
        title.add_css_class("title")
        header.set_title_widget(title)
        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(header)
        toolbar.set_content(scroll)
        self.frame = toolbar
        self.frame.set_visible(True)
        self._paint_brand()
        self._paint_retailer()
        if hasattr(self.win, "set_content"):
            self.win.set_content(self.frame)
        else:
            self.win.set_child(self.frame)
        return self.frame

    def _build_kiosk_frame(self, scroll):
        from gi.repository import Gtk, Pango

        from firstboot.assets import find_status
        from firstboot.floatlayer import HeaderDrag

        self.frame = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.frame.add_css_class("info-window")
        self.frame.set_halign(Gtk.Align.START)
        self.frame.set_valign(Gtk.Align.START)
        self.frame.set_hexpand(False)
        self.frame.set_vexpand(False)
        self.frame.set_visible(False)
        self.frame.set_size_request(INFO_WIDTH, INFO_HEIGHT)
        self.frame.set_overflow(Gtk.Overflow.HIDDEN)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        header.add_css_class("term-headerbar")
        header.set_hexpand(True)

        title_wrap = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        title_wrap.add_css_class("term-title-wrap")
        title_wrap.set_hexpand(True)
        self._cog_img = Gtk.Image()
        self._cog_img.set_pixel_size(18)
        cog = find_status("cog-wheel-symbolic.svg")
        if cog:
            self._cog_img.set_from_file(cog)
        title_wrap.append(self._cog_img)
        title = Gtk.Label(label="System details", xalign=0)
        title.add_css_class("term-title")
        title.set_ellipsize(Pango.EllipsizeMode.END)
        title.set_hexpand(True)
        title_wrap.append(title)
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
        close_btn.set_child(self._close_img)
        close_btn.connect("clicked", lambda *_: self.close())
        controls.append(max_btn)
        controls.append(close_btn)
        header.append(controls)
        self.frame.append(header)

        self._header_drag = HeaderDrag(self)
        self._header_drag.attach(header)
        dbl = Gtk.GestureClick()
        dbl.connect("pressed", self._on_header_press)
        header.add_controller(dbl)

        self.frame.append(scroll)
        self._paint_chrome()
        self._paint_brand()
        self._paint_retailer()
        if self.layer is not None:
            self.layer.place(self.frame, self._x, self._y)
        return self.frame

    def open(self) -> None:
        if self.frame is None:
            return
        if self.win is not None:
            if not self._placed:
                self._probe()
                self._placed = True
            self.win.present()
            return
        if not self._placed:
            self._place_default()
            self._placed = True
        was = self.frame.get_visible()
        self.frame.set_visible(True)
        if self.layer is not None:
            self.layer.raise_child(self.frame)
        if not was:
            self._probe()

    def close(self) -> None:
        if self.win is not None:
            self.win.close()
            return
        if self.frame is None:
            return
        self.frame.set_visible(False)

    def toggle_max(self) -> None:
        from gi.repository import Gtk

        if self.win is not None:
            if self.win.is_maximized():
                self.win.unmaximize()
                if self.frame is not None:
                    self.frame.remove_css_class("maximized")
            else:
                self.win.maximize()
                if self.frame is not None:
                    self.frame.add_css_class("maximized")
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
            self.frame.set_size_request(INFO_WIDTH, INFO_HEIGHT)
            self.frame.set_overflow(Gtk.Overflow.HIDDEN)
            self._move(self._x, self._y)

    def apply_theme(self, dark: bool) -> None:
        self._dark = dark
        from firstboot.theme import apply_gtk_interface_scheme

        apply_gtk_interface_scheme(dark)
        if self.win is not None:
            if dark:
                self.win.remove_css_class("light")
            else:
                self.win.add_css_class("light")
            self.win.queue_draw()
        self._paint_chrome()
        self._paint_brand()

    def _probe(self) -> None:
        self._gen += 1
        gen = self._gen

        def work() -> None:
            from gi.repository import GLib

            try:
                info = collect()
            except Exception:
                info = SysInfo()
            GLib.idle_add(self._apply, gen, info)

        threading.Thread(target=work, daemon=True).start()

    def _apply(self, gen: int, info: SysInfo) -> bool:
        if gen != self._gen:
            return False
        self._info = apply_monitor_refresh(info, gdk_monitor_modes())
        self._paint_info()
        return False

    def _paint_info(self) -> None:
        info = self._info or SysInfo()
        self._fill(self._hw_box, info.hardware_fields())
        self._fill(self._sw_box, info.software_fields())
        self._paint_retailer()

    def _fill(self, box: Gtk.Box | None, fields: tuple[Field, ...]) -> None:
        if box is None:
            return
        child = box.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            box.remove(child)
            child = nxt
        for field in fields:
            widget, _val = self._make_field(field.label, field.value)
            box.append(widget)

    def _make_field(self, label: str, value: str):
        from gi.repository import Gtk, Pango

        wrap = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        wrap.add_css_class("info-field")
        lab = Gtk.Label(label=label, xalign=0)
        lab.add_css_class("info-field-label")
        val = Gtk.Label(label=value, xalign=0)
        val.add_css_class("info-field-value")
        val.set_wrap(True)
        val.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        val.set_max_width_chars(28)
        val.set_hexpand(True)
        if hasattr(val, "set_natural_wrap_mode"):
            val.set_natural_wrap_mode(Gtk.NaturalWrapMode.NONE)
        wrap.append(lab)
        wrap.append(val)
        return wrap, val

    def _paint_retailer(self) -> None:
        if self._retailer_box is None or self._retailer_value is None:
            return
        if self.retailer is None or not self.retailer.name:
            self._retailer_box.set_visible(False)
            return
        text = self.retailer.name
        if self.retailer.support:
            text = f"{self.retailer.name}\n{self.retailer.support}"
        self._retailer_value.set_label(text)
        self._retailer_box.set_visible(True)

    def _paint_brand(self) -> None:
        import gi

        gi.require_version("GdkPixbuf", "2.0")
        from gi.repository import Gdk, GdkPixbuf

        from firstboot.assets import find_brand_wordmark

        if self._brand is None:
            return
        path = find_brand_wordmark(self._dark) or find_brand_wordmark(True)
        if not path:
            self._brand.set_paintable(None)
            self._brand.set_visible(False)
            return
        pb = None
        try:
            pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(
                path, WORDMARK_WIDTH, WORDMARK_HEIGHT, True
            )
        except Exception:
            pb = None
        if pb is not None:
            self._brand.set_paintable(Gdk.Texture.new_for_pixbuf(pb))
            self._brand.set_size_request(pb.get_width(), pb.get_height())
        else:
            self._brand.set_filename(path)
            self._brand.set_size_request(WORDMARK_WIDTH, WORDMARK_HEIGHT)
        self._brand.set_visible(True)

    def _paint_chrome(self) -> None:
        from gi.repository import Gdk

        from firstboot.assets import find_status, symbolic_pixbuf

        color = "#f6f5f4" if self._dark else "#1c1c1c"
        if self._close_img is not None:
            path = find_status("window-close-symbolic.svg")
            if path:
                pb = symbolic_pixbuf(path, color, 14)
                if pb is not None:
                    self._close_img.set_from_paintable(
                        Gdk.Texture.new_for_pixbuf(pb)
                    )
                else:
                    self._close_img.set_from_file(path)
        if self._cog_img is not None:
            path = find_status("cog-wheel-symbolic.svg")
            if path:
                pb = symbolic_pixbuf(path, color, 18)
                if pb is not None:
                    self._cog_img.set_from_paintable(
                        Gdk.Texture.new_for_pixbuf(pb)
                    )
                else:
                    self._cog_img.set_from_file(path)

    def _place_default(self) -> None:
        parent = self.frame.get_parent() if self.frame is not None else None
        pw = parent.get_width() if parent is not None else 0
        if pw <= 0:
            win = self.get_window()
            pw = win.get_width() if win is not None else 0
        if pw <= 0:
            pw = 1280
        self._x = max(24, (pw - INFO_WIDTH) // 2)
        self._y = INFO_TOP
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

    def _on_header_press(self, _g, n_press: int, *_xy) -> None:
        if n_press == 2:
            self.toggle_max()


def run_sysinfo(argv: list[str] | None = None) -> int:
    del argv

    import gi

    gi.require_version("Gdk", "4.0")
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gdk, Gtk

    from firstboot.payload import load_payload
    from firstboot.style import SYSINFO_CSS

    payload_root = os.environ.get("FIRSTBOOT_PAYLOAD") or "/run/payload"
    try:
        retailer = load_payload(payload_root).retailer
    except Exception:
        retailer = None

    class SysinfoApp(Adw.Application):
        def __init__(self) -> None:
            super().__init__(application_id="org.firstboot.Sysinfo")
            self.connect("activate", self.on_activate)

        def on_activate(self, *_app) -> None:
            existing = self.get_active_window()
            if existing is not None:
                existing.present()
                return
            Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.DEFAULT)
            provider = Gtk.CssProvider()
            provider.load_from_data(SYSINFO_CSS)
            display = Gdk.Display.get_default()
            if display is not None:
                Gtk.StyleContext.add_provider_for_display(
                    display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
                )
            win = Adw.ApplicationWindow(application=self, title="System details")
            win.set_default_size(INFO_WIDTH, INFO_HEIGHT)
            page = SysinfoWindow(host_window=win, retailer=retailer)
            page.build()
            mgr = Adw.StyleManager.get_default()
            page.apply_theme(mgr.get_dark())
            mgr.connect("notify::dark", lambda m, *_: page.apply_theme(m.get_dark()))
            page.open()
            print("firstboot-sysinfo: window presented", file=sys.stderr, flush=True)

    print("firstboot-sysinfo: run", file=sys.stderr, flush=True)
    return int(SysinfoApp().run(None))
