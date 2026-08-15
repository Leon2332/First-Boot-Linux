"""NetworkManager via nmcli. Local vs download later uses this same snapshot."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass

SKIP_IFACE_PREFIXES = (
    "lo",
    "veth",
    "docker",
    "br-",
    "virbr",
    "tun",
    "tap",
    "wg",
    "tailscale",
    "zt",
)
SKIP_TYPES = frozenset(
    {"loopback", "bridge", "bond", "tun", "tap", "dummy", "vlan", "team", "macvlan"}
)


class NmError(Exception):
    """nmcli failed or NetworkManager is missing."""


@dataclass(frozen=True)
class Device:
    name: str
    type: str
    state: str
    connection: str


@dataclass(frozen=True)
class WifiAP:
    ssid: str
    signal: int
    security: str
    in_use: bool
    bssid: str = ""

    @property
    def open(self) -> bool:
        return self.security in ("", "--", "none")


@dataclass(frozen=True)
class Ethernet:
    device: str | None
    plugged: bool
    connected: bool
    connection: str | None
    connecting: bool = False


@dataclass(frozen=True)
class WifiRadio:
    device: str | None
    hardware: bool
    enabled: bool
    connected: bool
    ssid: str | None
    connecting: bool = False


@dataclass(frozen=True)
class NetSnapshot:
    ethernet: Ethernet
    wifi: WifiRadio
    access_points: tuple[WifiAP, ...]
    available: bool = True

    @property
    def connected(self) -> bool:
        return self.ethernet.connected or self.wifi.connected

    @property
    def kind(self) -> str:
        if self.ethernet.connected:
            return "wired"
        if self.wifi.connected:
            return "wifi"
        return "offline"

    @property
    def icon(self) -> str:
        return {
            "wired": "network-wired-symbolic.svg",
            "wifi": "network-wireless-symbolic.svg",
            "offline": "network-offline-symbolic.svg",
        }[self.kind]

    @property
    def label(self) -> str:
        if self.ethernet.connected:
            return "Wired"
        if self.wifi.connected and self.wifi.ssid:
            return self.wifi.ssid
        return "Network"

    @property
    def sub(self) -> str:
        if self.connected:
            return "Connected"
        if self.ethernet.connecting or self.wifi.connecting:
            return "Connecting…"
        return "Not connected"

    @property
    def tooltip(self) -> str:
        return {
            "wired": "Ethernet",
            "wifi": self.wifi.ssid or "Wi-Fi",
            "offline": "Offline",
        }[self.kind]


def split_nmcli(line: str) -> list[str]:
    """Split one `nmcli -t` row. `:` is the field sep; `\\` escapes."""
    out: list[str] = []
    buf: list[str] = []
    esc = False
    for ch in line:
        if esc:
            buf.append(ch)
            esc = False
        elif ch == "\\":
            esc = True
        elif ch == ":":
            out.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    if esc:
        buf.append("\\")
    out.append("".join(buf))
    return out


def normalize_state(raw: str) -> str:
    text = (raw or "").strip().lower()
    if "externally" in text:
        return "external"
    if text.startswith("connected"):
        return "connected"
    if text.startswith("connecting"):
        return "connecting"
    if text.startswith("disconnected"):
        return "disconnected"
    if text.startswith("unavailable"):
        return "unavailable"
    if text.startswith("unmanaged"):
        return "unmanaged"
    return text or "unknown"


def is_virtual_iface(name: str) -> bool:
    return any(name == p or name.startswith(p) for p in SKIP_IFACE_PREFIXES)


def parse_device_status(text: str) -> list[Device]:
    devices: list[Device] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        parts = split_nmcli(line)
        if len(parts) < 3:
            continue
        name, typ = parts[0], parts[1]
        state = normalize_state(parts[2])
        conn = parts[3].strip() if len(parts) > 3 else ""
        devices.append(
            Device(name=name, type=typ, state=state, connection=conn or "")
        )
    return devices


def parse_wifi_list(text: str) -> list[WifiAP]:
    aps: list[WifiAP] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        parts = split_nmcli(line)
        if len(parts) < 3:
            continue
        in_use = parts[0].strip() == "*"
        ssid = parts[1].strip()
        if not ssid:
            continue
        try:
            signal = int(parts[2])
        except ValueError:
            signal = 0
        security = parts[3].strip() if len(parts) > 3 else ""
        bssid = parts[4].strip() if len(parts) > 4 else ""
        aps.append(
            WifiAP(
                ssid=ssid,
                signal=max(0, min(100, signal)),
                security=security,
                in_use=in_use,
                bssid=bssid,
            )
        )
    return merge_access_points(aps)


def merge_access_points(aps: list[WifiAP]) -> list[WifiAP]:
    best: dict[str, WifiAP] = {}
    for ap in aps:
        cur = best.get(ap.ssid)
        if cur is None or ap.signal > cur.signal or (ap.in_use and not cur.in_use):
            if cur is not None and cur.in_use and not ap.in_use:
                ap = WifiAP(
                    ssid=ap.ssid,
                    signal=max(ap.signal, cur.signal),
                    security=ap.security or cur.security,
                    in_use=True,
                    bssid=cur.bssid or ap.bssid,
                )
            elif cur is not None and ap.in_use:
                ap = WifiAP(
                    ssid=ap.ssid,
                    signal=max(ap.signal, cur.signal),
                    security=ap.security or cur.security,
                    in_use=True,
                    bssid=ap.bssid or cur.bssid,
                )
            best[ap.ssid] = ap
        elif cur is not None and ap.in_use:
            best[ap.ssid] = WifiAP(
                ssid=cur.ssid,
                signal=max(cur.signal, ap.signal),
                security=cur.security or ap.security,
                in_use=True,
                bssid=ap.bssid or cur.bssid,
            )
    return sorted(best.values(), key=lambda a: (-a.signal, a.ssid.casefold()))


def parse_radio(text: str) -> tuple[bool, bool]:
    """Return (hardware_present, software_enabled) from `nmcli -t -f WIFI-HW,WIFI radio`."""
    line = ""
    for raw in text.splitlines():
        if raw.strip():
            line = raw.strip()
            break
    if not line:
        return False, False
    parts = split_nmcli(line)
    hw = parts[0].strip().lower() if parts else ""
    sw = parts[1].strip().lower() if len(parts) > 1 else ""
    hardware = hw in {"enabled", "disabled"}
    enabled = sw == "enabled"
    return hardware, enabled


def pick_ethernet(devices: list[Device]) -> Ethernet:
    cands = [
        d
        for d in devices
        if d.type == "ethernet"
        and d.state not in {"external", "unmanaged"}
        and not is_virtual_iface(d.name)
    ]
    if not cands:
        return Ethernet(device=None, plugged=False, connected=False, connection=None)
    rank = {"connected": 0, "connecting": 1, "disconnected": 2, "unavailable": 3}
    cands.sort(key=lambda d: (rank.get(d.state, 9), d.name))
    d = cands[0]
    return Ethernet(
        device=d.name,
        plugged=d.state != "unavailable",
        connected=d.state == "connected",
        connection=d.connection or None,
        connecting=d.state == "connecting",
    )


def pick_wifi(devices: list[Device], hardware: bool, enabled: bool) -> WifiRadio:
    cands = [
        d
        for d in devices
        if d.type == "wifi"
        and d.state not in {"external", "unmanaged"}
        and not is_virtual_iface(d.name)
    ]
    if not cands:
        return WifiRadio(
            device=None,
            hardware=hardware,
            enabled=enabled and hardware,
            connected=False,
            ssid=None,
        )
    rank = {"connected": 0, "connecting": 1, "disconnected": 2, "unavailable": 3}
    cands.sort(key=lambda d: (rank.get(d.state, 9), d.name))
    d = cands[0]
    ssid = d.connection if d.state == "connected" and d.connection else None
    return WifiRadio(
        device=d.name,
        hardware=True,
        enabled=enabled and d.state != "unavailable",
        connected=d.state == "connected",
        ssid=ssid,
        connecting=d.state == "connecting",
    )


def empty_snapshot(*, available: bool = True) -> NetSnapshot:
    return NetSnapshot(
        ethernet=Ethernet(
            device=None, plugged=False, connected=False, connection=None
        ),
        wifi=WifiRadio(
            device=None, hardware=False, enabled=False, connected=False, ssid=None
        ),
        access_points=(),
        available=available,
    )


def snapshot_from_text(
    devices_text: str, radio_text: str, wifi_text: str
) -> NetSnapshot:
    devices = parse_device_status(devices_text)
    hardware, enabled = parse_radio(radio_text)
    ethernet = pick_ethernet(devices)
    wifi = pick_wifi(devices, hardware, enabled)
    aps = parse_wifi_list(wifi_text) if wifi.device and wifi.enabled else []
    if wifi.connected and wifi.ssid:
        aps = [
            WifiAP(
                ssid=ap.ssid,
                signal=ap.signal,
                security=ap.security,
                in_use=ap.in_use or ap.ssid == wifi.ssid,
                bssid=ap.bssid,
            )
            for ap in aps
        ]
        if not any(ap.ssid == wifi.ssid for ap in aps):
            aps.insert(
                0,
                WifiAP(ssid=wifi.ssid, signal=100, security="", in_use=True),
            )
    return NetSnapshot(
        ethernet=ethernet, wifi=wifi, access_points=tuple(aps), available=True
    )


def ethernet_detail(eth: Ethernet) -> tuple[str, str | None]:
    """(status line, button label or None if no action)."""
    if eth.device is None:
        return "No Ethernet adapter", None
    if eth.connecting:
        return "Connecting…", None
    if eth.connected:
        return "Connected", "Disconnect"
    if eth.plugged:
        return "Cable detected", "Connect"
    return "Cable unplugged", None


def run_nmcli(args: list[str], *, timeout: float = 12, write: bool = False) -> str:
    if not shutil.which("nmcli"):
        raise NmError("NetworkManager is not available")
    cmd = ["nmcli", *args]
    try:
        proc = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise NmError("NetworkManager is not available") from exc
    except subprocess.TimeoutExpired as exc:
        raise NmError("NetworkManager timed out") from exc
    if proc.returncode == 0:
        return proc.stdout
    err = (proc.stderr or proc.stdout or "nmcli failed").strip()
    if write and _permission_error(err, proc.returncode) and shutil.which("sudo"):
        try:
            proc2 = subprocess.run(
                ["sudo", "-n", *cmd],
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise NmError(err) from exc
        if proc2.returncode == 0:
            return proc2.stdout
        err = (proc2.stderr or proc2.stdout or err).strip()
    raise NmError(err.splitlines()[0] if err else "nmcli failed")


def _permission_error(err: str, code: int) -> bool:
    low = err.lower()
    return code in {3, 4, 8} or any(
        s in low
        for s in (
            "not authorized",
            "insufficient privileges",
            "permission denied",
            "authorization failed",
            "not allowed",
        )
    )


def snapshot() -> NetSnapshot:
    if not shutil.which("nmcli"):
        return empty_snapshot(available=False)
    try:
        devices = run_nmcli(["-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device", "status"])
        radio = run_nmcli(["-t", "-f", "WIFI-HW,WIFI", "radio"])
    except NmError:
        return empty_snapshot(available=False)
    wifi_text = ""
    try:
        wifi_text = run_nmcli(
            ["-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY,BSSID", "device", "wifi", "list", "--rescan", "no"],
            timeout=8,
        )
    except NmError:
        wifi_text = ""
    return snapshot_from_text(devices, radio, wifi_text)


def request_scan() -> None:
    try:
        run_nmcli(["device", "wifi", "rescan"], write=True, timeout=8)
    except NmError:
        pass


def connect_ethernet(device: str) -> None:
    run_nmcli(["device", "connect", device], write=True, timeout=25)


def disconnect_device(device: str) -> None:
    run_nmcli(["device", "disconnect", device], write=True, timeout=15)


def set_wifi_radio(enabled: bool) -> None:
    run_nmcli(["radio", "wifi", "on" if enabled else "off"], write=True, timeout=8)


def connect_wifi(ssid: str, password: str | None = None) -> None:
    args = ["device", "wifi", "connect", ssid]
    if password:
        args.extend(["password", password])
    run_nmcli(args, write=True, timeout=35)
