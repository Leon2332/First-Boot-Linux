"""Customer OS install from a staged ISO.

Native drivers (``unpack_kind``) unpack the live filesystem in this
session, health-check, then drop First Boot. Official catalog is Ubuntu
26.04 GNOME (``ubuntu_2604_gnome.py``), Linux Mint 22.3 Cinnamon,
MATE, and Xfce (``mint_223_cinnamon.py``, ``mint_223_mate.py``,
``mint_223_xfce.py``), and Fedora 44 Plasma (``fedora_44_plasma.py``).
Shop packs still use the legacy ``boot_files`` / ``kernel_args`` /
``seed_files`` API.

See README.md in this directory. kexec is not used (lockdown).
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import traceback
from collections.abc import Callable

from firstboot.disk import (
    LIVE_MOUNTS,
    PAYLOAD_MOUNT,
    HelperEvent,
    disk_for_device,
    emit,
    find_source_disk,
    find_target_disk,
    format_size,
    live_lsblk,
    live_mounts,
    parse_helper_line,
)
from firstboot.isodownload import DownloadError, dest_is_payload_image, download_iso
from firstboot.install import blkid_uuid
from firstboot.i18n import _, apply_payload_language
from firstboot.installlocale import payload_install_locale
from firstboot.payload import (
    DEFAULT_PAYLOAD,
    Distro,
    Edition,
    ID_RE,
    custom_driver_path,
    last_payload_root,
)

from . import (
    fedora_44_plasma,
    mint_223_cinnamon,
    mint_223_mate,
    mint_223_xfce,
    ubuntu_2604_gnome,
)
from .common import (
    HELPER,
    HOST_RE,
    ISO_REL_RE,
    ITOA64,
    MIN_TARGET_BYTES,
    OSINSTALL_REL,
    TORAM_HEADROOM,
    USER_RE,
    OsIdentity,
    OsInstallError,
    OsInstallPlan,
    _SHA512_ROUNDS,
    casper_boot_files,
    casper_kernel_args,
    is_native_driver,
    iso_relpath,
    iso_volume_id,
    run_checked,
)

_DRIVER_MODULES = (
    ubuntu_2604_gnome,
    mint_223_cinnamon,
    mint_223_mate,
    mint_223_xfce,
    fedora_44_plasma,
)


def _register_drivers() -> dict[str, object]:
    by_id: dict[str, object] = {}
    for mod in _DRIVER_MODULES:
        drv = mod.DRIVER
        by_id[drv.id] = drv
        for alias in drv.aliases:
            by_id[alias] = drv
    return by_id


DRIVERS = _register_drivers()
DRIVERS_READY = frozenset(DRIVERS)
DRIVER_UBUNTU_GNOME = ubuntu_2604_gnome.ID
DRIVER_MINT_CINNAMON = mint_223_cinnamon.ID
DRIVER_MINT_MATE = mint_223_mate.ID
DRIVER_MINT_XFCE = mint_223_xfce.ID
DRIVER_FEDORA_PLASMA = fedora_44_plasma.ID

_casper_boot_files = casper_boot_files
_CUSTOM_DRIVERS: dict[str, object] = {}


def _payload_roots(payload_root: str | None) -> list[str]:
    roots: list[str] = []
    for item in (payload_root, last_payload_root(), os.environ.get("FIRSTBOOT_PAYLOAD"), DEFAULT_PAYLOAD):
        if item and item not in roots:
            roots.append(item)
    return roots


def get_driver(driver_id: str, payload_root: str | None = None):
    """Return the driver object for a catalog install id, old alias, or shop pack."""
    drv = DRIVERS.get(driver_id)
    if drv is not None:
        return drv
    if not isinstance(driver_id, str) or not ID_RE.fullmatch(driver_id):
        return None
    for root in _payload_roots(payload_root):
        path = custom_driver_path(root, driver_id)
        if not path:
            continue
        cached = _CUSTOM_DRIVERS.get(path)
        if cached is not None:
            return cached
        spec = importlib.util.spec_from_file_location(
            f"firstboot_custom_{driver_id.replace('-', '_')}", path
        )
        if spec is None or spec.loader is None:
            continue
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        try:
            spec.loader.exec_module(mod)
        except Exception:
            sys.modules.pop(spec.name, None)
            continue
        loaded = getattr(mod, "DRIVER", None)
        if loaded is None or getattr(loaded, "id", None) != driver_id:
            sys.modules.pop(spec.name, None)
            continue
        for name in ("boot_files", "kernel_args", "seed_files"):
            if not callable(getattr(loaded, name, None)):
                sys.modules.pop(spec.name, None)
                loaded = None
                break
        if loaded is None:
            continue
        _CUSTOM_DRIVERS[path] = loaded
        return loaded
    return None


def canonical_driver_id(driver_id: str) -> str:
    drv = get_driver(driver_id)
    return drv.id if drv is not None else driver_id


OSINSTALL_GRUB = """# First Boot Linux — one-shot customer OS install
set default=0
set timeout=2
set timeout_style=menu

search --no-floppy --set=root --fs-uuid {sys_uuid}
if [ ! -f /boot/osinstall/vmlinuz ]; then
	search --no-floppy --set=root --label FBL-SYS
fi

menuentry "Install {name}" {{
    linux /boot/osinstall/vmlinuz {linux_args} ---
    initrd /boot/osinstall/initrd
}}

menuentry "First Boot Linux" {{
    linux /casper/vmlinuz boot=casper live-media=/dev/disk/by-uuid/{sys_uuid} live-media-path=casper ignore_uuid nopersistent noprompt console=tty1 console=ttyS0,115200n8 ---
    initrd /casper/initrd
}}
"""


def helper_path() -> str:
    if os.path.isfile(HELPER) and os.access(HELPER, os.X_OK):
        return HELPER
    here = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "firstboot-install-os")
    )
    if os.path.isfile(here):
        return here
    return HELPER


def privilege_prefix() -> list[str]:
    if os.geteuid() == 0:
        return []
    sudo = shutil.which("sudo")
    if sudo:
        probe = subprocess.run(
            [sudo, "-n", helper_path(), "--plan"],
            check=False,
            capture_output=True,
            text=True,
        )
        err = (probe.stderr or "").lower()
        if "password" not in err and probe.returncode in (0, 1):
            return [sudo, "-n"]
    pkexec = shutil.which("pkexec")
    if pkexec:
        return [pkexec]
    raise OsInstallError(_("Cannot gain permission to install."))


def suggest_username(realname: str) -> str:
    out: list[str] = []
    for ch in realname.strip().lower():
        if ch.isascii() and ch.isalnum():
            out.append(ch)
        elif ch in " -._" and out and out[-1] != "-":
            out.append("-")
    name = "".join(out).strip("-")
    if not name or not name[0].isalpha():
        name = "user" + re.sub(r"[^a-z0-9]", "", name)
    if not name or not name[0].isalpha():
        name = "user"
    return name[:32]


def suggest_hostname(username: str) -> str:
    host = re.sub(r"[^a-z0-9-]", "", username.lower())
    host = host.strip("-") or "ubuntu"
    return host[:63]


def validate_identity(hostname: str, username: str, realname: str, password: str) -> str | None:
    realname = realname.strip()
    if not realname or len(realname) > 64 or ":" in realname or "\n" in realname:
        return _("Enter a name.")
    if not USER_RE.fullmatch(username):
        return _("Username must start with a letter and use only a–z, 0–9, _ or -.")
    if not HOST_RE.fullmatch(hostname):
        return _("Computer name must be letters, numbers, and hyphens.")
    if len(password) < 6:
        return _("Password must be at least 6 characters.")
    if "\n" in password or "\r" in password:
        return _("Password cannot contain line breaks.")
    return None


def sha512_crypt(password: str, salt: str | None = None, rounds: int = _SHA512_ROUNDS) -> str:
    """glibc SHA-512 crypt ($6$)."""
    if salt is None:
        salt = "".join(ITOA64[b % 64] for b in os.urandom(16))
    elif salt.startswith("$6$"):
        rest = salt[3:]
        if rest.startswith("rounds="):
            rpart, rest = rest.split("$", 1)
            rounds = int(rpart.split("=", 1)[1])
        salt = rest.split("$", 1)[0]
    salt = salt[:16]
    password_b = password.encode("utf-8")
    salt_b = salt.encode("ascii")
    a = hashlib.sha512()
    a.update(password_b)
    a.update(salt_b)
    b = hashlib.sha512()
    b.update(password_b)
    b.update(salt_b)
    b.update(password_b)
    digest_b = b.digest()
    pw_len = len(password_b)
    n = pw_len
    while n > 64:
        a.update(digest_b)
        n -= 64
    a.update(digest_b[:n])
    n = pw_len
    while n > 0:
        if n & 1:
            a.update(digest_b)
        else:
            a.update(password_b)
        n >>= 1
    digest_a = a.digest()
    dp = hashlib.sha512()
    for _ in range(pw_len):
        dp.update(password_b)
    p_bytes = (dp.digest() * ((pw_len + 63) // 64))[:pw_len]
    ds = hashlib.sha512()
    for _ in range(16 + digest_a[0]):
        ds.update(salt_b)
    s_bytes = (ds.digest() * ((len(salt_b) + 63) // 64))[: len(salt_b)]
    digest = digest_a
    for i in range(rounds):
        c = hashlib.sha512()
        if i & 1:
            c.update(p_bytes)
        else:
            c.update(digest)
        if i % 3:
            c.update(s_bytes)
        if i % 7:
            c.update(p_bytes)
        if i & 1:
            c.update(digest)
        else:
            c.update(p_bytes)
        digest = c.digest()
    seq = (
        (0, 21, 42),
        (22, 43, 1),
        (44, 2, 23),
        (3, 24, 45),
        (25, 46, 4),
        (47, 5, 26),
        (6, 27, 48),
        (28, 49, 7),
        (50, 8, 29),
        (9, 30, 51),
        (31, 52, 10),
        (53, 11, 32),
        (12, 33, 54),
        (34, 55, 13),
        (56, 14, 35),
        (15, 36, 57),
        (37, 58, 16),
        (59, 17, 38),
        (18, 39, 60),
        (40, 61, 19),
        (62, 20, 41),
    )

    def b64(v: int, n: int) -> str:
        out = []
        for _ in range(n):
            out.append(ITOA64[v & 63])
            v >>= 6
        return "".join(out)

    chunks = [
        b64(digest[c] | (digest[b] << 8) | (digest[a] << 16), 4) for a, b, c in seq
    ]
    chunks.append(b64(digest[63], 2))
    if rounds != 5000:
        return f"$6$rounds={rounds}${salt}${''.join(chunks)}"
    return f"$6${salt}${''.join(chunks)}"


def persistent_disk_path(dev: str) -> str:
    by_id = "/dev/disk/by-id"
    if not os.path.isdir(by_id):
        return dev
    try:
        real = os.path.realpath(dev)
    except OSError:
        return dev
    found: list[str] = []
    try:
        names = os.listdir(by_id)
    except OSError:
        return dev
    for name in names:
        if "-part" in name:
            continue
        path = os.path.join(by_id, name)
        try:
            if os.path.realpath(path) == real:
                found.append(path)
        except OSError:
            continue
    order = ("wwn-", "nvme-", "ata-", "scsi-", "virtio-", "usb-")

    def rank(path: str) -> int:
        base = os.path.basename(path)
        for i, prefix in enumerate(order):
            if base.startswith(prefix):
                return i
        return 99

    found.sort(key=rank)
    return found[0] if found else dev


def mem_available() -> int:
    try:
        text = open("/proc/meminfo", encoding="ascii").read()
    except OSError:
        return 0
    avail = 0
    free = 0
    for line in text.splitlines():
        if line.startswith("MemAvailable:"):
            parts = line.split()
            avail = int(parts[1]) * 1024
        elif line.startswith("MemFree:"):
            parts = line.split()
            free = int(parts[1]) * 1024
    return avail or free


def find_os_live_disk(disks, mounts: dict[str, str]):
    """Disk we are booted from — GRUB rewrite goes here, not a plugged-in USB."""
    for mp in LIVE_MOUNTS:
        disk = disk_for_device(disks, mounts.get(mp) or "")
        if disk is not None:
            return disk
    disk = disk_for_device(disks, mounts.get(PAYLOAD_MOUNT) or "")
    if disk is not None:
        return disk
    return find_source_disk(disks, mounts)


def plan_os_target(disks, live) -> tuple:
    if live.usb or live.removable:
        target, reason = find_target_disk(disks, live, MIN_TARGET_BYTES)
        return target, reason
    if live.size < MIN_TARGET_BYTES:
        return None, (
            _("This disk is too small ({have}; need {need}).").format(
                have=format_size(live.size),
                need=format_size(MIN_TARGET_BYTES),
            )
        )
    return live, ""


def plan_os_install(
    disks,
    mounts: dict[str, str],
    payload_root: str,
    distro: Distro,
    edition: Edition,
) -> OsInstallPlan:
    if not edition.on_disk or not edition.file:
        return OsInstallPlan(False, "This edition is not on disk.")
    driver_id = distro.install_for(edition)
    if get_driver(driver_id, payload_root) is None:
        return OsInstallPlan(
            False,
            f"{distro.name} install is not available yet.",
            driver=driver_id,
        )
    iso_rel = iso_relpath(edition.file)
    if not ISO_REL_RE.fullmatch(iso_rel):
        return OsInstallPlan(False, "The image path is not a staged ISO.")
    iso_path = os.path.join(payload_root, edition.file)
    if not os.path.isfile(iso_path):
        return OsInstallPlan(False, "The image file is missing.")
    live = find_os_live_disk(disks, mounts)
    if live is None:
        return OsInstallPlan(False, "Could not find the disk First Boot is running from.")
    target, reason = plan_os_target(disks, live)
    if target is None:
        return OsInstallPlan(False, reason, driver=driver_id, live=live)
    same = live.path == target.path
    return OsInstallPlan(
        True,
        "",
        driver=driver_id,
        live=live,
        target=target,
        iso_path=os.path.abspath(iso_path),
        iso_rel=iso_rel,
        sha256=edition.sha256,
        size_bytes=edition.size_bytes,
        same_disk=same,
        distro_name=distro.name,
        edition_name=edition.name,
    )


def _remount_payload(disks, payload_root: str) -> None:
    """Put FBL-DATA back at /run/payload after a RAM pivot dropped it."""
    os.makedirs(payload_root, exist_ok=True)
    if os.path.ismount(payload_root):
        return
    for disk in disks:
        part = disk.part_named("FBL-DATA")
        if part is None:
            continue
        subprocess.run(
            ["sudo", "-n", "mount", part.path, payload_root],
            check=False,
            capture_output=True,
        )
        return


def live_os_plan(payload_root: str, distro: Distro, edition: Edition) -> OsInstallPlan:
    disks = live_lsblk()
    mounts = live_mounts()
    iso_path = os.path.join(payload_root, edition.file) if edition.file else ""
    if iso_path and not os.path.isfile(iso_path):
        _remount_payload(disks, payload_root)
        disks = live_lsblk()
        mounts = live_mounts()
    return plan_os_install(disks, mounts, payload_root, distro, edition)


def verify_iso(
    path: str,
    sha256: str,
    size_bytes: int = 0,
    on_progress: Callable[[int], None] | None = None,
) -> None:
    if not os.path.isfile(path):
        raise OsInstallError(_("The image file is missing."))
    try:
        total = os.path.getsize(path)
    except OSError as exc:
        raise OsInstallError(f"Cannot read the image: {exc}") from exc
    if size_bytes and total != size_bytes:
        raise OsInstallError(
            f"The image is {format_size(total)}; the catalog says {format_size(size_bytes)}."
        )
    digest = hashlib.sha256()
    n = 0
    try:
        with open(path, "rb") as fh:
            while True:
                chunk = fh.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
                n += len(chunk)
                if on_progress and total:
                    on_progress(min(100, n * 100 // total))
    except OSError as exc:
        raise OsInstallError(f"Cannot read the image: {exc}") from exc
    got = digest.hexdigest()
    want = sha256.strip().lower()
    if got != want:
        raise OsInstallError(_("The image is damaged. It does not match the checksum."))


def disk_udev_serial(dev: str) -> str:
    """ID_SERIAL from udev. Subiquity match.path is /dev/sdX, not by-id/wwn."""
    if not dev:
        return ""
    proc = subprocess.run(
        ["udevadm", "info", "--query=property", "--name", dev],
        check=False,
        capture_output=True,
        text=True,
    )
    serial = ""
    short = ""
    for line in (proc.stdout or "").splitlines():
        if line.startswith("ID_SERIAL="):
            serial = line.split("=", 1)[1].strip()
        elif line.startswith("ID_SERIAL_SHORT="):
            short = line.split("=", 1)[1].strip()
    if serial:
        return serial
    if short:
        return short
    proc = subprocess.run(
        ["lsblk", "-ndo", "SERIAL", dev],
        check=False,
        capture_output=True,
        text=True,
    )
    out = (proc.stdout or "").strip().splitlines()
    return out[0].strip() if out else ""


def osinstall_grub(
    sys_uuid: str,
    iso_rel: str,
    name: str,
    *,
    toram: bool,
    extra: str | None = None,
    linux_args: str | None = None,
) -> str:
    args = linux_args or casper_kernel_args(
        iso_rel,
        toram=toram,
        extra=extra if extra is not None else "",
    )
    return OSINSTALL_GRUB.format(
        sys_uuid=sys_uuid, name=name, linux_args=args
    )


CPIO_MAGIC = (b"070701", b"070702")
ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"
GZIP_MAGIC = b"\x1f\x8b"
XZ_MAGIC = b"\xfd7zXZ\x00"


def _cpio_archive_end(data: bytes, start: int) -> int:
    """Byte offset after one newc archive (TRAILER!!! + 4-byte pad)."""
    off = start
    n = len(data)
    while off + 110 <= n:
        if data[off : off + 6] not in CPIO_MAGIC:
            raise OsInstallError("initrd is not a cpio archive")
        namesize = int(data[off + 94 : off + 102], 16)
        filesize = int(data[off + 54 : off + 62], 16)
        name_off = off + 110
        name_end = name_off + namesize
        if name_end > n:
            raise OsInstallError("truncated initrd")
        name = data[name_off : name_end].split(b"\0", 1)[0]
        hdr_end = (name_end + 3) & ~3
        data_end = hdr_end + filesize
        off = (data_end + 3) & ~3
        if name == b"TRAILER!!!":
            return off
    raise OsInstallError("truncated initrd")


def split_initrd(data: bytes) -> list[bytes]:
    """Split concatenated cpio / compressed-cpio members."""
    parts: list[bytes] = []
    off = 0
    n = len(data)
    while off < n:
        while off < n and data[off] == 0:
            off += 1
        if off >= n:
            break
        if (
            data[off : off + 4] == ZSTD_MAGIC
            or data[off : off + 2] == GZIP_MAGIC
            or data[off : off + 6] == XZ_MAGIC
        ):
            parts.append(data[off:])
            break
        if data[off : off + 6] in CPIO_MAGIC:
            end = _cpio_archive_end(data, off)
            parts.append(data[off:end])
            off = end
            continue
        raise OsInstallError("unrecognised initrd encoding")
    if not parts:
        raise OsInstallError("empty initrd")
    return parts


def _decompress_member(blob: bytes) -> tuple[str, bytes]:
    if blob.startswith(ZSTD_MAGIC):
        proc = subprocess.run(
            ["zstd", "-d", "-c"],
            input=blob,
            check=False,
            capture_output=True,
        )
        if proc.returncode != 0:
            raise OsInstallError("could not decompress installer initrd (zstd)")
        return "zstd", proc.stdout
    if blob.startswith(GZIP_MAGIC):
        return "gzip", gzip.decompress(blob)
    if blob.startswith(XZ_MAGIC):
        proc = subprocess.run(
            ["xz", "-d", "-c"],
            input=blob,
            check=False,
            capture_output=True,
        )
        if proc.returncode != 0:
            raise OsInstallError("could not decompress installer initrd (xz)")
        return "xz", proc.stdout
    if blob[:6] in CPIO_MAGIC:
        return "cpio", blob
    raise OsInstallError("unrecognised initrd compression")


def _compress_member(kind: str, blob: bytes) -> bytes:
    if kind == "zstd":
        proc = subprocess.run(
            ["zstd", "-1", "-c"],
            input=blob,
            check=False,
            capture_output=True,
        )
        if proc.returncode != 0:
            raise OsInstallError("could not recompress installer initrd (zstd)")
        return proc.stdout
    if kind == "gzip":
        return gzip.compress(blob, compresslevel=6)
    if kind == "xz":
        proc = subprocess.run(
            ["xz", "-1", "-c"],
            input=blob,
            check=False,
            capture_output=True,
        )
        if proc.returncode != 0:
            raise OsInstallError("could not recompress installer initrd (xz)")
        return proc.stdout
    return blob


def _unpack_cpio_blob(blob: bytes, dest: str) -> None:
    os.makedirs(dest, exist_ok=True)
    proc = subprocess.run(
        ["cpio", "-id", "--no-absolute-filenames"],
        cwd=dest,
        input=blob,
        check=False,
        capture_output=True,
    )
    if proc.returncode != 0:
        err = (proc.stderr or b"").decode("utf-8", "replace").strip()
        raise OsInstallError(err or "could not unpack installer initrd")


def _pack_cpio_tree(src: str) -> bytes:
    listing = subprocess.run(
        ["find", ".", "-print0"],
        cwd=src,
        check=False,
        capture_output=True,
    )
    if listing.returncode != 0:
        raise OsInstallError("could not list initrd files")
    proc = subprocess.run(
        ["cpio", "-o", "-H", "newc", "--null"],
        cwd=src,
        input=listing.stdout,
        check=False,
        capture_output=True,
    )
    if proc.returncode != 0:
        err = (proc.stderr or b"").decode("utf-8", "replace").strip()
        raise OsInstallError(err or "could not pack installer initrd")
    return proc.stdout


def _write_tree_files(root: str, files: dict[str, str | bytes]) -> None:
    order_lines: list[str] = []
    for rel, content in files.items():
        rel = rel.lstrip("/")
        dest = os.path.join(root, rel)
        os.makedirs(os.path.dirname(dest) or root, exist_ok=True)
        if isinstance(content, bytes):
            with open(dest, "wb") as fh:
                fh.write(content)
        else:
            with open(dest, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(content)
        executable = (
            "casper-bottom" in rel
            or "dracut/hooks/" in rel
            or "system-generators" in rel
            or rel.endswith("firstboot-efi-cleanup")
            or rel.endswith("fbl-liveinst")
            or rel.endswith("fbl-link-squashfs")
            or rel.endswith("fbl-anaconda")
            or rel.endswith("fbl-anaconda-gen")
            or rel.endswith("fbl-selinux")
            or rel.endswith("fbl-calamares")
            or rel.endswith("fbl-calamares-gen")
            or rel.endswith("/liveinst")
        )
        os.chmod(dest, 0o755 if executable else 0o644)
        if rel.startswith("scripts/casper-bottom/") and not rel.endswith("/ORDER"):
            order_lines.append("/" + rel)
    order = os.path.join(root, "scripts", "casper-bottom", "ORDER")
    if os.path.isfile(order) and order_lines:
        with open(order, encoding="ascii") as fh:
            existing = fh.read()
        with open(order, "a", encoding="ascii") as fh:
            for line in order_lines:
                if line not in existing:
                    fh.write(line + "\n")


def inject_into_initrd(path: str, files: dict[str, str | bytes]) -> None:
    """Add files to the last (main) cpio of a concatenated casper initrd."""
    with open(path, "rb") as fh:
        data = fh.read()
    parts = split_initrd(data)
    kind, raw = _decompress_member(parts[-1])
    work = tempfile.mkdtemp(prefix="fbl-initrd-")
    try:
        _unpack_cpio_blob(raw, work)
        _write_tree_files(work, files)
        packed = _pack_cpio_tree(work)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    parts[-1] = _compress_member(kind, packed)
    with open(path, "wb") as fh:
        fh.write(b"".join(parts))


def write_cpio(path: str, files: dict[str, str | bytes]) -> None:
    """Write an uncompressed newc cpio. GRUB loads this as a second initrd."""
    if not shutil.which("cpio"):
        raise OsInstallError("cpio is missing from this image.")
    work = tempfile.mkdtemp(prefix="fbl-cpio-")
    try:
        rels: list[str] = []
        for rel, content in files.items():
            rel = rel.lstrip("/")
            dest = os.path.join(work, rel)
            os.makedirs(os.path.dirname(dest) or work, exist_ok=True)
            if isinstance(content, bytes):
                with open(dest, "wb") as fh:
                    fh.write(content)
            else:
                with open(dest, "w", encoding="utf-8", newline="\n") as fh:
                    fh.write(content)
            mode = 0o755 if "casper-bottom" in rel else 0o644
            os.chmod(dest, mode)
            rels.append(rel)
        listing = "".join(r + "\n" for r in sorted(rels))
        proc = subprocess.run(
            ["cpio", "-o", "-H", "newc"],
            cwd=work,
            input=listing.encode("utf-8"),
            check=False,
            capture_output=True,
        )
        if proc.returncode != 0:
            err = (proc.stderr or b"").decode("utf-8", "replace").strip()
            raise OsInstallError(err or "failed to pack autoinstall into the installer")
        with open(path, "wb") as fh:
            fh.write(proc.stdout)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def append_cpio(initrd_path: str, files: dict[str, str | bytes]) -> None:
    """Append a newc cpio (tests / fallback). Prefer write_cpio + a second initrd."""
    tmp = initrd_path + ".seed"
    write_cpio(tmp, files)
    try:
        with open(tmp, "rb") as src, open(initrd_path, "ab") as dst:
            dst.write(src.read())
    finally:
        os.unlink(tmp)


def _progress(n: int) -> None:
    emit("PROGRESS", max(0, min(100, int(n))))


def _sys_mountpoint(mounts: dict[str, str] | None = None) -> str | None:
    mounts = mounts if mounts is not None else live_mounts()
    for mp in LIVE_MOUNTS:
        if os.path.isdir(os.path.join(mp, "casper")):
            return mp
        if mounts.get(mp):
            return mp
    return None


def _remount_rw(mp: str) -> None:
    proc = subprocess.run(
        ["mount", "-o", "remount,rw", mp],
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise OsInstallError(_("Could not write the boot partition."))


def _live_image_size(iso_mnt: str, fallback: int) -> int:
    for rel in (
        os.path.join("casper", "filesystem.squashfs"),
        os.path.join("LiveOS", "squashfs.img"),
        os.path.join("LiveOS", "rootfs.img"),
    ):
        path = os.path.join(iso_mnt, rel)
        if os.path.isfile(path):
            return os.path.getsize(path)
    return fallback


def prepare_os(
    plan: OsInstallPlan,
    identity: OsIdentity,
    *,
    on_progress: Callable[[int], None] | None = None,
    payload_root: str | None = None,
) -> None:
    if not plan.available or plan.target is None or plan.live is None:
        raise OsInstallError(plan.reason or _("Cannot install."))
    if os.geteuid() != 0:
        raise OsInstallError("must run as root")
    drv = get_driver(plan.driver, payload_root)
    if drv is None:
        raise OsInstallError(f"{plan.driver} is not available yet.")
    if is_native_driver(drv):
        from .pipeline import install_native

        install_native(
            plan, identity, drv, payload_root=payload_root, on_progress=on_progress
        )
        return

    def prog(n: int) -> None:
        if on_progress:
            on_progress(n)
        else:
            _progress(n)

    emit("STEP", _("Checking the image…"))
    prog(2)
    verify_iso(
        plan.iso_path,
        plan.sha256,
        plan.size_bytes,
        on_progress=lambda p: prog(2 + p * 48 // 100),
    )
    prog(50)

    label = plan.distro_name or "the system"
    emit("STEP", _("Preparing {name}…").format(name=label))
    iso_mnt = tempfile.mkdtemp(prefix="fbl-iso-")
    mounted = False
    try:
        run_checked(
            ["mount", "-o", "loop,ro", plan.iso_path, iso_mnt],
            what=f"mount the {label} image",
        )
        mounted = True
        vmlinuz, initrd = drv.boot_files(iso_mnt)
        squash_size = _live_image_size(iso_mnt, plan.size_bytes)
        need = squash_size + TORAM_HEADROOM
        have = mem_available()
        toram = have >= need
        if plan.same_disk and not toram:
            raise OsInstallError(
                _(
                    "This computer needs about {size} of memory to install {name} from the internal disk."
                ).format(size=format_size(need), name=label)
            )
        prog(58)

        sys_mp = _sys_mountpoint()
        if not sys_mp:
            raise OsInstallError(_("Could not find the First Boot system partition."))
        _remount_rw(sys_mp)
        dest = os.path.join(sys_mp, OSINSTALL_REL)
        os.makedirs(dest, exist_ok=True)
        shutil.copy2(vmlinuz, os.path.join(dest, "vmlinuz"))
        shutil.copy2(initrd, os.path.join(dest, "initrd"))
        os.chmod(os.path.join(dest, "vmlinuz"), 0o644)
        os.chmod(os.path.join(dest, "initrd"), 0o644)
        prog(78)

        serial = disk_udev_serial(plan.target.path)
        loc = payload_install_locale(payload_root)
        files = drv.seed_files(identity, plan.target.path, serial, locale=loc)
        seed_copy = (
            files.get("autoinstall.yaml")
            or files.get("preseed.cfg")
            or files.get("ks.cfg")
        )
        if isinstance(seed_copy, str):
            if "autoinstall.yaml" in files:
                seed_name = "autoinstall.yaml"
            elif "preseed.cfg" in files:
                seed_name = "preseed.cfg"
            else:
                seed_name = "ks.cfg"
            with open(os.path.join(dest, seed_name), "w", encoding="utf-8") as fh:
                fh.write(seed_copy)
        inject_into_initrd(os.path.join(dest, "initrd"), files)
        prog(88)

        sys_part = plan.live.part_named("FBL-SYS")
        sys_dev = sys_part.path if sys_part else ""
        if not sys_dev:
            from firstboot.disk import live_mounts as _lm
            from firstboot.disk import parent_disk_name

            for mp, src in _lm().items():
                if mp in LIVE_MOUNTS and parent_disk_name(src) == plan.live.name:
                    sys_dev = src
                    break
        if not sys_dev:
            raise OsInstallError("Could not find FBL-SYS.")
        sys_uuid = blkid_uuid(sys_dev)
        if plan.edition_name:
            label = f"{plan.distro_name} ({plan.edition_name})"
        linux_args = drv.kernel_args(
            plan.iso_rel, toram=toram, iso_path=plan.iso_path
        )
        grub = osinstall_grub(
            sys_uuid,
            plan.iso_rel,
            label,
            toram=toram,
            linux_args=linux_args,
        )
        grub_path = os.path.join(sys_mp, "boot", "grub", "grub.cfg")
        os.makedirs(os.path.dirname(grub_path), exist_ok=True)
        with open(grub_path, "w", encoding="utf-8") as fh:
            fh.write(grub)
        after = getattr(drv, "after_prepare", None)
        if callable(after):
            after(iso_mnt, plan, sys_uuid, label, linux_args)
        os.sync()
        prog(100)
        emit("STEP", _("Restarting to install {name}…").format(name=plan.distro_name or label))
        emit("REBOOT")
    finally:
        if mounted:
            subprocess.run(["umount", iso_mnt], check=False, capture_output=True)
        shutil.rmtree(iso_mnt, ignore_errors=True)


def prepare_ubuntu(
    plan: OsInstallPlan,
    identity: OsIdentity,
    *,
    on_progress: Callable[[int], None] | None = None,
    payload_root: str | None = None,
) -> None:
    prepare_os(plan, identity, on_progress=on_progress, payload_root=payload_root)


def run_os_install(
    plan: OsInstallPlan,
    identity: OsIdentity,
    on_event: Callable[..., None] | None = None,
) -> None:
    if not plan.available or plan.target is None:
        raise OsInstallError(plan.reason or _("Cannot install."))
    cmd = [
        *privilege_prefix(),
        helper_path(),
        "--apply",
        "--iso",
        plan.iso_path,
        "--iso-rel",
        plan.iso_rel,
        "--sha256",
        plan.sha256,
        "--size",
        str(plan.size_bytes),
        "--driver",
        plan.driver,
        "--target",
        plan.target.path,
        "--live",
        plan.live.path if plan.live else "",
        "--hostname",
        identity.hostname,
        "--username",
        identity.username,
        "--realname",
        identity.realname,
        "--password-hash",
        identity.password_hash,
        "--name",
        plan.distro_name,
        "--edition",
        plan.edition_name,
    ]
    if plan.same_disk:
        cmd.append("--same-disk")
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
    except OSError as exc:
        raise OsInstallError(str(exc)) from exc
    assert proc.stdout is not None
    err: str | None = None
    reboot = False
    for raw in proc.stdout:
        event = parse_helper_line(raw)
        if event is None:
            continue
        if event.kind == "error":
            err = event.text
        if event.kind == "reboot":
            reboot = True
        if on_event is not None:
            on_event(event)
    status = proc.wait()
    if err:
        raise OsInstallError(err)
    if status != 0:
        raise OsInstallError(f"Install failed ({status}).")
    if reboot and on_event is not None:
        return


def _plan_from_args(args: argparse.Namespace) -> OsInstallPlan:
    disks = live_lsblk()
    mounts = live_mounts()
    live = disk_for_device(disks, args.live) if args.live else find_os_live_disk(disks, mounts)
    target = disk_for_device(disks, args.target) if args.target else None
    if live is None:
        raise OsInstallError("unknown live disk")
    if target is None:
        raise OsInstallError("unknown target disk")
    return OsInstallPlan(
        True,
        "",
        driver=args.driver,
        live=live,
        target=target,
        iso_path=os.path.abspath(args.iso),
        iso_rel=args.iso_rel,
        sha256=args.sha256,
        size_bytes=int(args.size or 0),
        same_disk=bool(args.same_disk) or live.path == target.path,
        distro_name=args.name or "Ubuntu",
        edition_name=args.edition or "",
    )


def fetch_iso(
    url: str,
    dest: str,
    sha256: str,
    size_bytes: int,
    payload_root: str,
    *,
    on_progress: Callable[[int], None] | None = None,
) -> None:
    if not dest_is_payload_image(payload_root, dest):
        raise OsInstallError(_("The image path is not a staged ISO."))
    emit("STEP", _("Downloading…"))

    def prog(n: int) -> None:
        if on_progress:
            on_progress(n)
        else:
            emit("PROGRESS", n)

    try:
        download_iso(url, dest, sha256, size_bytes, on_progress=prog)
    except DownloadError as exc:
        raise OsInstallError(str(exc)) from exc
    emit("STEP", _("Ready"))
    emit("DONE")


def run_iso_fetch(
    url: str,
    dest: str,
    sha256: str,
    size_bytes: int,
    payload_root: str,
    on_event: Callable[..., None] | None = None,
) -> None:
    dest = os.path.abspath(dest)
    parent = os.path.dirname(dest)
    try:
        os.makedirs(parent, exist_ok=True)
    except OSError:
        pass
    if os.access(parent, os.W_OK):
        def prog(n: int) -> None:
            if on_event is not None:
                on_event(HelperEvent("progress", progress=n))

        try:
            if on_event is not None:
                on_event(HelperEvent("step", text=_("Downloading…")))
            download_iso(url, dest, sha256, size_bytes, on_progress=prog)
            if on_event is not None:
                on_event(HelperEvent("done", progress=100))
            return
        except DownloadError as exc:
            raise OsInstallError(str(exc)) from exc
        except PermissionError:
            pass
    cmd = [
        *privilege_prefix(),
        helper_path(),
        "--fetch",
        "--url",
        url,
        "--iso",
        dest,
        "--sha256",
        sha256,
        "--size",
        str(size_bytes),
        "--payload",
        payload_root,
    ]
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
    except OSError as exc:
        raise OsInstallError(str(exc)) from exc
    assert proc.stdout is not None
    err: str | None = None
    for raw in proc.stdout:
        event = parse_helper_line(raw)
        if event is None:
            continue
        if event.kind == "error":
            err = event.text
        if on_event is not None:
            on_event(event)
    status = proc.wait()
    if err:
        raise OsInstallError(err)
    if status != 0:
        raise OsInstallError(f"Download failed ({status}).")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install a staged OS onto this computer")
    parser.add_argument("--plan", action="store_true", help="print a JSON stub (privilege probe)")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--url")
    parser.add_argument("--payload", default=PAYLOAD_MOUNT)
    parser.add_argument("--iso")
    parser.add_argument("--iso-rel")
    parser.add_argument("--sha256")
    parser.add_argument("--size", default="0")
    parser.add_argument("--driver", default=DRIVER_UBUNTU_GNOME)
    parser.add_argument("--target")
    parser.add_argument("--live")
    parser.add_argument("--hostname")
    parser.add_argument("--username")
    parser.add_argument("--realname")
    parser.add_argument("--password-hash")
    parser.add_argument("--name", default="Ubuntu")
    parser.add_argument("--edition", default="")
    parser.add_argument("--same-disk", action="store_true")
    args = parser.parse_args(argv)
    apply_payload_language(args.payload)
    if args.fetch:
        if not args.url or not args.iso or not args.sha256:
            emit("ERROR", "missing --url / --iso / --sha256")
            return 2
        try:
            fetch_iso(
                args.url,
                args.iso,
                args.sha256,
                int(args.size or 0),
                args.payload or PAYLOAD_MOUNT,
            )
        except OsInstallError as exc:
            emit("ERROR", str(exc))
            return 1
        except Exception as exc:
            emit("ERROR", str(exc) or type(exc).__name__)
            return 1
        return 0
    if args.plan and not args.apply:
        print(json.dumps({"available": False, "reason": "pass --apply to install"}))
        return 1
    if not args.apply:
        parser.error("need --plan, --apply, or --fetch")
    for key in ("iso", "iso_rel", "sha256", "driver", "target", "hostname", "username", "password_hash"):
        if not getattr(args, key.replace("-", "_")):
            emit("ERROR", f"missing --{key.replace('_', '-')}")
            return 2
    if get_driver(args.driver, args.payload) is None:
        emit("ERROR", f"{args.driver} is not available yet.")
        return 2
    if not ISO_REL_RE.fullmatch(args.iso_rel):
        emit("ERROR", "bad --iso-rel")
        return 2
    if not USER_RE.fullmatch(args.username) or not HOST_RE.fullmatch(args.hostname):
        emit("ERROR", "invalid user or computer name")
        return 2
    if not args.password_hash.startswith("$6$"):
        emit("ERROR", "password hash must be SHA-512 crypt")
        return 2
    identity = OsIdentity(
        hostname=args.hostname,
        username=args.username,
        realname=(args.realname or args.username).strip(),
        password_hash=args.password_hash,
    )
    try:
        plan = _plan_from_args(args)
        prepare_os(plan, identity, payload_root=args.payload)
    except OsInstallError as exc:
        emit("ERROR", str(exc))
        return 1
    except Exception as exc:
        try:
            os.makedirs("/run/firstboot", exist_ok=True)
            with open("/run/firstboot/osinstall.log", "a", encoding="utf-8") as fh:
                fh.write(traceback.format_exc())
        except OSError:
            pass
        emit("ERROR", str(exc) or type(exc).__name__)
        return 1
    return 0
