"""Live-session timezone as a UTC offset. NTP stays on; only the zone changes."""

from __future__ import annotations

import datetime as dt
import os
import shutil
import struct
import subprocess
import time

TZ_MINUTES_MIN = -12 * 60
TZ_MINUTES_MAX = 14 * 60
TZ_MINUTES_STEP = 30
HELPER = "/usr/libexec/firstboot/set-timezone"
ZONEINFO_NAME = "FirstBoot/Offset"
TIMEZONE_FILE = "timezone"
DEFAULT_TZ_LABEL = "UTC+0000"


def snap_tz_minutes(minutes: int) -> int:
    stepped = int(round(minutes / TZ_MINUTES_STEP) * TZ_MINUTES_STEP)
    return max(TZ_MINUTES_MIN, min(TZ_MINUTES_MAX, stepped))


def format_tz_offset(minutes: int) -> str:
    minutes = snap_tz_minutes(minutes)
    sign = "-" if minutes < 0 else "+"
    abs_m = abs(minutes)
    return f"UTC{sign}{abs_m // 60:02d}{abs_m % 60:02d}"


def parse_tz_offset(text: str) -> int | None:
    raw = text.strip().upper().replace(" ", "")
    if raw.startswith("UTC"):
        raw = raw[3:]
    if len(raw) < 2 or raw[0] not in "+-":
        if raw in {"0", "00", "0000"}:
            return 0
        return None
    sign = -1 if raw[0] == "-" else 1
    digits = raw[1:].replace(":", "")
    if not digits.isdigit():
        return None
    if len(digits) <= 2:
        hours, mins = int(digits), 0
    elif len(digits) == 3:
        hours, mins = int(digits[0]), int(digits[1:])
    elif len(digits) == 4:
        hours, mins = int(digits[:2]), int(digits[2:])
    else:
        return None
    if mins not in (0, 30):
        return None
    total = sign * (hours * 60 + mins)
    if total < TZ_MINUTES_MIN or total > TZ_MINUTES_MAX:
        return None
    return total


def posix_tz(minutes: int) -> str:
    minutes = snap_tz_minutes(minutes)
    if minutes == 0:
        return "UTC0"
    sign = "+" if minutes > 0 else "-"
    abs_m = abs(minutes)
    hh, mm = divmod(abs_m, 60)
    name = f"{sign}{hh:02d}{mm:02d}"
    psign = "-" if minutes > 0 else "+"
    offset = f"{psign}{hh}" if mm == 0 else f"{psign}{hh}:{mm:02d}"
    return f"<{name}>{offset}"


def iana_zone(minutes: int) -> str | None:
    minutes = snap_tz_minutes(minutes)
    if minutes == 0:
        return "UTC"
    if minutes % 60:
        return None
    hours = minutes // 60
    sign = "-" if hours > 0 else "+"
    return f"Etc/GMT{sign}{abs(hours)}"


def tzif_bytes(minutes: int) -> bytes:
    """Minimal TZif v2 with a single constant offset (no DST)."""
    minutes = snap_tz_minutes(minutes)
    utoff = minutes * 60
    posix = posix_tz(minutes)

    def block() -> bytes:
        counts = struct.pack(">6I", 0, 0, 0, 0, 1, 1)
        ttinfo = struct.pack(">ibB", utoff, 0, 0)
        return counts + ttinfo + b"\x00"

    header = b"TZif2" + bytes(15)
    return header + block() + header + block() + b"\n" + posix.encode("ascii") + b"\n"


def current_tz_minutes() -> int:
    off = dt.datetime.now().astimezone().utcoffset()
    if off is None:
        return 0
    return snap_tz_minutes(int(off.total_seconds() // 60))


def timezone_file_path(payload_root: str) -> str:
    return os.path.join(payload_root, TIMEZONE_FILE)


def read_timezone_file(payload_root: str) -> int | None:
    path = timezone_file_path(payload_root)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            for raw in fh:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                return parse_tz_offset(line)
    except OSError:
        return None
    return None


def load_timezone_minutes(
    payload_root: str, retailer_timezone: str | None = None
) -> int | None:
    if payload_root:
        from_file = read_timezone_file(payload_root)
        if from_file is not None:
            return snap_tz_minutes(from_file)
    parsed = parse_tz_offset(retailer_timezone or "")
    if parsed is not None:
        return snap_tz_minutes(parsed)
    return None


def write_timezone_file(payload_root: str, minutes: int) -> None:
    minutes = snap_tz_minutes(minutes)
    os.makedirs(payload_root, exist_ok=True)
    path = timezone_file_path(payload_root)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(format_tz_offset(minutes) + "\n")
    os.replace(tmp, path)


def persist_timezone(payload_root: str, minutes: int) -> bool:
    minutes = snap_tz_minutes(minutes)
    try:
        write_timezone_file(payload_root, minutes)
        return True
    except OSError:
        return False


def clock_in_offset(
    tz_minutes: int, when: dt.datetime | None = None
) -> dt.datetime:
    if when is None:
        when = dt.datetime.now(dt.timezone.utc)
    elif when.tzinfo is None:
        when = when.replace(tzinfo=dt.timezone.utc)
    zone = dt.timezone(dt.timedelta(minutes=snap_tz_minutes(tz_minutes)))
    return when.astimezone(zone)


def apply_process_tz(minutes: int) -> None:
    os.environ["TZ"] = posix_tz(minutes)
    time.tzset()


def apply_tz_minutes(minutes: int) -> bool:
    """Set the process TZ. Persist via the privileged helper when present."""
    minutes = snap_tz_minutes(minutes)
    apply_process_tz(minutes)
    helper = HELPER if os.path.isfile(HELPER) else ""
    if not helper:
        return False
    sudo = shutil.which("sudo")
    if sudo is None:
        return False
    try:
        proc = subprocess.run(
            [sudo, "-n", helper, str(minutes)],
            check=False,
            capture_output=True,
            timeout=8,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


def apply_as_root(minutes: int, *, zoneinfo_root: str = "/usr/share/zoneinfo") -> None:
    """Install the offset as the system timezone. Must run as root."""
    minutes = snap_tz_minutes(minutes)
    named = iana_zone(minutes)
    dest = os.path.join(zoneinfo_root, *ZONEINFO_NAME.split("/"))
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "wb") as fh:
        fh.write(tzif_bytes(minutes))
    if named:
        src = os.path.join(zoneinfo_root, *named.split("/"))
        if os.path.isfile(src):
            _link_localtime(src)
            _write_timezone_name(named)
            _timedatectl_ntp()
            _timedatectl_timezone(named)
            _persist_payload_tz(minutes)
            return
    _link_localtime(dest)
    _write_timezone_name(ZONEINFO_NAME)
    _timedatectl_ntp()
    _timedatectl_timezone(ZONEINFO_NAME)
    _persist_payload_tz(minutes)


def _persist_payload_tz(minutes: int) -> None:
    if os.path.isdir("/run/payload"):
        try:
            write_timezone_file("/run/payload", minutes)
        except OSError:
            pass


def _link_localtime(src: str) -> None:
    os.makedirs("/etc", exist_ok=True)
    tmp = "/etc/localtime.tmp"
    try:
        os.unlink(tmp)
    except FileNotFoundError:
        pass
    try:
        os.symlink(src, tmp)
        os.replace(tmp, "/etc/localtime")
    except OSError:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        shutil.copyfile(src, "/etc/localtime")


def _write_timezone_name(name: str) -> None:
    with open("/etc/timezone", "w", encoding="ascii") as fh:
        fh.write(name + "\n")


def _timedatectl_ntp() -> None:
    subprocess.run(
        ["timedatectl", "set-ntp", "true"],
        check=False,
        capture_output=True,
        timeout=5,
    )


def _timedatectl_timezone(name: str) -> None:
    subprocess.run(
        ["timedatectl", "set-timezone", name],
        check=False,
        capture_output=True,
        timeout=5,
    )
