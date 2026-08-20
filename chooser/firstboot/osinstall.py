"""Customer OS install. Step 9 is Ubuntu autoinstall from a staged ISO.

Subiquity is not on this live image. The helper verifies the ISO, copies
the signed kernel plus Ubuntu's initrd onto FBL-SYS (GRUB-readable),
injects autoinstall.yaml into the initrd's main archive, and rewrites
GRUB so the next boot is Ubuntu's installer with `autoinstall` and, when
the ISO lives on the target disk, `toram`. Secure Boot stays on
Canonical's chain; kexec is not used (lockdown).
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass

from firstboot.disk import (
    LIVE_MOUNTS,
    PAYLOAD_MOUNT,
    Disk,
    disk_for_device,
    emit,
    find_source_disk,
    find_target_disk,
    format_size,
    live_lsblk,
    live_mounts,
    parse_helper_line,
)
from firstboot.install import InstallError, blkid_uuid
from firstboot.payload import Distro, Edition

HELPER = "/usr/libexec/firstboot/install-os"
DRIVER_UBUNTU = "ubuntu-autoinstall"
OSINSTALL_REL = "boot/osinstall"
MIN_TARGET_BYTES = 16 * 1024 * 1024 * 1024
TORAM_HEADROOM = 2 * 1024 * 1024 * 1024
USER_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
HOST_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")
ISO_REL_RE = re.compile(r"^/images/[A-Za-z0-9._+-]+\.iso$")
ITOA64 = "./0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
_SHA512_ROUNDS = 5000

# Casper iso-scan + toram leaves the ISO loop on FBL-DATA (LP#684280).
# Drop that backing so curtin can O_EXCL the disk, but keep a RAM copy of
# filesystem.squashfs mounted at /media/filesystem — Subiquity configure_apt
# overlay-mounts that as lowerdir (0.6.13 unmounted /cdrom and apt failed).
FREE_ISO_BACKING = r"""
free_iso_backing() {
  _log=${1:-/dev/null}
  {
    echo "=== free_iso_backing ==="
    cat /proc/cmdline 2>/dev/null
    losetup -a 2>/dev/null
    findmnt 2>/dev/null
    lsblk -o NAME,LABEL,MOUNTPOINT,TYPE 2>/dev/null
  } >> "$_log" 2>&1

  mkdir -p /run/fbl-casper /media/filesystem
  _sq=
  for _p in /cdrom/casper/filesystem.squashfs /root/cdrom/casper/filesystem.squashfs /run/casper/filesystem.squashfs; do
    if [ -f "$_p" ]; then
      _sq=$_p
      break
    fi
  done
  if [ -n "$_sq" ] && [ ! -f /run/fbl-casper/filesystem.squashfs ]; then
    cp -a "$_sq" /run/fbl-casper/filesystem.squashfs >> "$_log" 2>&1 || true
  fi
  if [ -f /run/fbl-casper/filesystem.squashfs ]; then
    umount -l /media/filesystem 2>/dev/null || true
    mount -t squashfs -o loop,ro /run/fbl-casper/filesystem.squashfs /media/filesystem >> "$_log" 2>&1 || true
  fi

  if command -v losetup >/dev/null; then
    losetup -ln -O NAME,BACK-FILE 2>/dev/null | while read -r _name _back; do
      [ -n "$_name" ] || continue
      case "$_back" in
        *isodevice*|*FBL-DATA*)
          umount -l "$_name" 2>/dev/null || true
          losetup -d "$_name" 2>/dev/null || true
          ;;
      esac
    done
  fi

  for _mp in /isodevice /root/isodevice /run/payload; do
    umount -l "$_mp" 2>/dev/null || true
  done

  if command -v blkid >/dev/null; then
    _dev=$(blkid -L FBL-DATA 2>/dev/null) || true
    if [ -n "$_dev" ]; then
      umount -l "$_dev" 2>/dev/null || true
      if command -v findmnt >/dev/null; then
        findmnt -n -o TARGET "$_dev" 2>/dev/null | while read -r _t; do
          umount -l "$_t" 2>/dev/null || true
        done
      fi
    fi
  fi

  swapoff -a 2>/dev/null || true
  udevadm settle 2>/dev/null || true

  {
    echo "=== after ==="
    losetup -a 2>/dev/null
    findmnt 2>/dev/null
    lsblk -o NAME,LABEL,MOUNTPOINT,TYPE 2>/dev/null
    ls -l /media/filesystem /run/fbl-casper 2>/dev/null
  } >> "$_log" 2>&1
}
"""

CASPER_BOTTOM = (
    """#!/bin/sh
PREREQ=""
prereqs() { echo "$PREREQ"; }
case $1 in
prereqs) prereqs; exit 0 ;;
esac

mkdir -p /root/var/log /root/var/lib/cloud/seed/nocloud
log=/root/var/log/firstboot-autoinstall.log
{
  echo "cmdline: $(cat /proc/cmdline 2>/dev/null)"
  ls -l /autoinstall.yaml /user-data /scripts/casper-bottom/29fbl-autoinstall 2>&1
} > "$log"

if [ -f /autoinstall.yaml ]; then
  cp /autoinstall.yaml /root/autoinstall.yaml
  chmod 644 /root/autoinstall.yaml
fi
if [ -f /user-data ]; then
  cp /user-data /root/var/lib/cloud/seed/nocloud/user-data
  printf '%s\\n' "instance-id: nocloud" > /root/var/lib/cloud/seed/nocloud/meta-data
  chmod 644 /root/var/lib/cloud/seed/nocloud/user-data
  chmod 644 /root/var/lib/cloud/seed/nocloud/meta-data
fi

"""
    + FREE_ISO_BACKING
    + """
if grep -qw toram /proc/cmdline; then
  free_iso_backing "$log"
  cp "$log" /root/var/log/firstboot-autoinstall.log 2>/dev/null || true
fi

echo "live_autoinstall=$(test -f /root/autoinstall.yaml && echo yes || echo no)" >> "$log"
exit 0
"""
)

OSINSTALL_GRUB = """# First Boot Linux — one-shot Ubuntu autoinstall
set default=0
set timeout=2
set timeout_style=menu

search --no-floppy --set=root --fs-uuid {sys_uuid}
if [ ! -f /boot/osinstall/vmlinuz ]; then
	search --no-floppy --set=root --label FBL-SYS
fi

menuentry "Install {name}" {{
    linux /boot/osinstall/vmlinuz boot=casper iso-scan/filename={iso_rel} live-media-path=casper ignore_uuid nopersistent noprompt {toram}autoinstall subiquity.autoinstallpath=/autoinstall.yaml ---
    initrd /boot/osinstall/initrd
}}

menuentry "First Boot Linux" {{
    linux /casper/vmlinuz boot=casper live-media=/dev/disk/by-uuid/{sys_uuid} live-media-path=casper ignore_uuid nopersistent noprompt console=tty1 console=ttyS0,115200n8 ---
    initrd /casper/initrd
}}
"""


class OsInstallError(InstallError):
    """A customer-install failure the chooser can show."""


@dataclass(frozen=True)
class OsIdentity:
    hostname: str
    username: str
    realname: str
    password_hash: str


@dataclass(frozen=True)
class OsInstallPlan:
    available: bool
    reason: str = ""
    driver: str = ""
    live: Disk | None = None
    target: Disk | None = None
    iso_path: str = ""
    iso_rel: str = ""
    sha256: str = ""
    size_bytes: int = 0
    same_disk: bool = False
    distro_name: str = ""
    edition_name: str = ""

    def as_dict(self) -> dict:
        return {
            "available": self.available,
            "reason": self.reason,
            "driver": self.driver,
            "live": self.live.path if self.live else "",
            "target": self.target.path if self.target else "",
            "iso_path": self.iso_path,
            "iso_rel": self.iso_rel,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "same_disk": self.same_disk,
        }


def helper_path() -> str:
    if os.path.isfile(HELPER) and os.access(HELPER, os.X_OK):
        return HELPER
    here = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "firstboot-install-os")
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
    raise OsInstallError("Cannot gain permission to install.")


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
        return "Enter a name."
    if not USER_RE.fullmatch(username):
        return "Username must start with a letter and use only a–z, 0–9, _ or -."
    if not HOST_RE.fullmatch(hostname):
        return "Computer name must be letters, numbers, and hyphens."
    if len(password) < 6:
        return "Password must be at least 6 characters."
    if "\n" in password or "\r" in password:
        return "Password cannot contain line breaks."
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


def yaml_str(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


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


def iso_relpath(file_rel: str) -> str:
    rel = file_rel.strip()
    if rel.startswith("images/"):
        rel = "/" + rel
    if not rel.startswith("/"):
        rel = "/" + rel
    return rel


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


def find_os_live_disk(disks: list[Disk], mounts: dict[str, str]) -> Disk | None:
    """Disk we are booted from — GRUB rewrite goes here, not a plugged-in USB."""
    for mp in LIVE_MOUNTS:
        disk = disk_for_device(disks, mounts.get(mp) or "")
        if disk is not None:
            return disk
    disk = disk_for_device(disks, mounts.get(PAYLOAD_MOUNT) or "")
    if disk is not None:
        return disk
    return find_source_disk(disks, mounts)


def plan_os_target(disks: list[Disk], live: Disk) -> tuple[Disk | None, str]:
    if live.usb or live.removable:
        target, reason = find_target_disk(disks, live, MIN_TARGET_BYTES)
        return target, reason
    if live.size < MIN_TARGET_BYTES:
        return None, (
            f"This disk is too small "
            f"({format_size(live.size)}; need {format_size(MIN_TARGET_BYTES)})."
        )
    return live, ""


def plan_os_install(
    disks: list[Disk],
    mounts: dict[str, str],
    payload_root: str,
    distro: Distro,
    edition: Edition,
) -> OsInstallPlan:
    if not edition.on_disk or not edition.file:
        return OsInstallPlan(False, "This edition is not on disk.")
    if distro.install != DRIVER_UBUNTU:
        return OsInstallPlan(
            False,
            f"{distro.name} install is not available yet.",
            driver=distro.install,
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
        return OsInstallPlan(False, reason, driver=distro.install, live=live)
    same = live.path == target.path
    return OsInstallPlan(
        True,
        "",
        driver=distro.install,
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


def live_os_plan(payload_root: str, distro: Distro, edition: Edition) -> OsInstallPlan:
    return plan_os_install(live_lsblk(), live_mounts(), payload_root, distro, edition)


def verify_iso(
    path: str,
    sha256: str,
    size_bytes: int = 0,
    on_progress: Callable[[int], None] | None = None,
) -> None:
    if not os.path.isfile(path):
        raise OsInstallError("The image file is missing.")
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
        raise OsInstallError("The image is damaged. It does not match the checksum.")


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


def kernel_disk_path(dev: str) -> str:
    """DEVNAME-style path. match.path does not resolve /dev/disk/by-id."""
    if not dev:
        return dev
    try:
        real = os.path.realpath(dev)
    except OSError:
        real = dev
    return real


def autoinstall_yaml(
    identity: OsIdentity, target_path: str, serial: str = ""
) -> str:
    path = kernel_disk_path(target_path)
    if serial:
        match = (
            "      match:\n"
            f"        - serial: {yaml_str(serial)}\n"
            f"        - path: {yaml_str(path)}\n"
        )
    else:
        match = "      match:\n" f"        path: {yaml_str(path)}\n"
    return (
        "autoinstall:\n"
        "  version: 1\n"
        "  locale: en_US.UTF-8\n"
        "  keyboard:\n"
        "    layout: us\n"
        "  identity:\n"
        f"    hostname: {yaml_str(identity.hostname)}\n"
        f"    realname: {yaml_str(identity.realname)}\n"
        f"    username: {yaml_str(identity.username)}\n"
        f"    password: {yaml_str(identity.password_hash)}\n"
        "  storage:\n"
        "    layout:\n"
        "      name: direct\n"
        + match
        + "  early-commands:\n"
        "    - |\n"
        "        mkdir -p /run/fbl-casper /media/filesystem\n"
        "        sq=\n"
        "        for p in /cdrom/casper/filesystem.squashfs /run/casper/filesystem.squashfs; do\n"
        "          [ -f \"$p\" ] && sq=$p && break\n"
        "        done\n"
        "        if [ -n \"$sq\" ] && [ ! -f /run/fbl-casper/filesystem.squashfs ]; then\n"
        "          cp -a \"$sq\" /run/fbl-casper/filesystem.squashfs || true\n"
        "        fi\n"
        "        if [ -f /run/fbl-casper/filesystem.squashfs ]; then\n"
        "          umount -l /media/filesystem 2>/dev/null || true\n"
        "          mount -t squashfs -o loop,ro /run/fbl-casper/filesystem.squashfs /media/filesystem || true\n"
        "        fi\n"
        "        losetup -ln -O NAME,BACK-FILE 2>/dev/null | while read name back; do\n"
        "          case \"$back\" in\n"
        "            *isodevice*|*FBL-DATA*) umount -l \"$name\" 2>/dev/null || true; losetup -d \"$name\" 2>/dev/null || true ;;\n"
        "          esac\n"
        "        done\n"
        "        umount -l /isodevice /run/payload 2>/dev/null || true\n"
        "        dev=$(blkid -L FBL-DATA 2>/dev/null) || true\n"
        "        [ -n \"$dev\" ] && umount -l \"$dev\" 2>/dev/null || true\n"
        "        swapoff -a 2>/dev/null || true\n"
        "        udevadm settle 2>/dev/null || true\n"
        "  late-commands:\n"
        "    - |\n"
        "        for n in $(efibootmgr 2>/dev/null | sed -n 's/^Boot\\([0-9A-Fa-f]\\{4\\}\\).*First Boot Linux.*/\\1/p'); do\n"
        "          efibootmgr -b \"$n\" -B || true\n"
        "        done\n"
        "  apt:\n"
        "    fallback: offline-install\n"
        "    geoip: false\n"
        "  shutdown: reboot\n"
    )


def cloud_config_user_data(
    identity: OsIdentity, target_path: str, serial: str = ""
) -> str:
    return "#cloud-config\n" + autoinstall_yaml(identity, target_path, serial=serial)


def osinstall_grub(sys_uuid: str, iso_rel: str, name: str, *, toram: bool) -> str:
    flag = "toram " if toram else ""
    return OSINSTALL_GRUB.format(
        sys_uuid=sys_uuid, iso_rel=iso_rel, name=name, toram=flag
    )


CPIO_MAGIC = (b"070701", b"070702")
ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"
GZIP_MAGIC = b"\x1f\x8b"


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
        if data[off : off + 4] == ZSTD_MAGIC or data[off : off + 2] == GZIP_MAGIC:
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
            raise OsInstallError("could not decompress Ubuntu initrd (zstd)")
        return "zstd", proc.stdout
    if blob.startswith(GZIP_MAGIC):
        return "gzip", gzip.decompress(blob)
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
            raise OsInstallError("could not recompress Ubuntu initrd (zstd)")
        return proc.stdout
    if kind == "gzip":
        return gzip.compress(blob, compresslevel=6)
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
        raise OsInstallError(err or "could not unpack Ubuntu initrd")


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
        raise OsInstallError(err or "could not pack Ubuntu initrd")
    return proc.stdout


def _write_tree_files(root: str, files: dict[str, str | bytes]) -> None:
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
        os.chmod(dest, 0o755 if "casper-bottom" in rel else 0o644)
    order = os.path.join(root, "scripts", "casper-bottom", "ORDER")
    if os.path.isfile(order):
        with open(order, "a", encoding="ascii") as fh:
            fh.write("/scripts/casper-bottom/29fbl-autoinstall\n")


def inject_into_initrd(path: str, files: dict[str, str | bytes]) -> None:
    """Add files to the last (main) cpio of a concatenated Ubuntu initrd.

    Trailing extra archives after a zstd member are ignored by the kernel —
    that is why append / a second GRUB initrd never reached casper-bottom.
    """
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


def run_checked(cmd: list[str], *, what: str) -> None:
    try:
        proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
    except OSError as exc:
        raise OsInstallError(f"{what}: {exc}") from exc
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip().splitlines()
        tail = detail[-1] if detail else f"exit {proc.returncode}"
        raise OsInstallError(f"{what}: {tail}")


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
        raise OsInstallError("Could not write the boot partition.")


def prepare_ubuntu(
    plan: OsInstallPlan,
    identity: OsIdentity,
    *,
    on_progress: Callable[[int], None] | None = None,
) -> None:
    if not plan.available or plan.target is None or plan.live is None:
        raise OsInstallError(plan.reason or "Cannot install.")
    if os.geteuid() != 0:
        raise OsInstallError("must run as root")

    def prog(n: int) -> None:
        if on_progress:
            on_progress(n)
        else:
            _progress(n)

    emit("STEP", "Checking the image…")
    prog(2)
    verify_iso(
        plan.iso_path,
        plan.sha256,
        plan.size_bytes,
        on_progress=lambda p: prog(2 + p * 48 // 100),
    )
    prog(50)

    emit("STEP", "Preparing Ubuntu…")
    iso_mnt = tempfile.mkdtemp(prefix="fbl-iso-")
    mounted = False
    try:
        run_checked(
            ["mount", "-o", "loop,ro", plan.iso_path, iso_mnt],
            what="mount the Ubuntu image",
        )
        mounted = True
        vmlinuz = os.path.join(iso_mnt, "casper", "vmlinuz")
        initrd = os.path.join(iso_mnt, "casper", "initrd")
        squash = os.path.join(iso_mnt, "casper", "filesystem.squashfs")
        if not os.path.isfile(vmlinuz) or not os.path.isfile(initrd):
            raise OsInstallError("This image is not an Ubuntu live ISO.")
        squash_size = os.path.getsize(squash) if os.path.isfile(squash) else plan.size_bytes
        need = squash_size + TORAM_HEADROOM
        have = mem_available()
        toram = have >= need
        if plan.same_disk and not toram:
            raise OsInstallError(
                "This computer needs about "
                f"{format_size(need)} of memory to install Ubuntu from the internal disk."
            )
        prog(58)

        sys_mp = _sys_mountpoint()
        if not sys_mp:
            raise OsInstallError("Could not find the First Boot system partition.")
        _remount_rw(sys_mp)
        dest = os.path.join(sys_mp, OSINSTALL_REL)
        os.makedirs(dest, exist_ok=True)
        shutil.copy2(vmlinuz, os.path.join(dest, "vmlinuz"))
        shutil.copy2(initrd, os.path.join(dest, "initrd"))
        os.chmod(os.path.join(dest, "vmlinuz"), 0o644)
        os.chmod(os.path.join(dest, "initrd"), 0o644)
        prog(78)

        serial = disk_udev_serial(plan.target.path)
        yaml = autoinstall_yaml(identity, plan.target.path, serial=serial)
        user_data = cloud_config_user_data(
            identity, plan.target.path, serial=serial
        )
        with open(os.path.join(dest, "autoinstall.yaml"), "w", encoding="utf-8") as fh:
            fh.write(yaml)
        inject_into_initrd(
            os.path.join(dest, "initrd"),
            {
                "autoinstall.yaml": yaml,
                "user-data": user_data,
                "scripts/casper-bottom/29fbl-autoinstall": CASPER_BOTTOM,
            },
        )
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
        label = plan.distro_name
        if plan.edition_name:
            label = f"{plan.distro_name} ({plan.edition_name})"
        grub = osinstall_grub(sys_uuid, plan.iso_rel, label, toram=toram)
        grub_path = os.path.join(sys_mp, "boot", "grub", "grub.cfg")
        os.makedirs(os.path.dirname(grub_path), exist_ok=True)
        with open(grub_path, "w", encoding="utf-8") as fh:
            fh.write(grub)
        os.sync()
        prog(100)
        emit("STEP", "Restarting to install Ubuntu…")
        emit("REBOOT")
    finally:
        if mounted:
            subprocess.run(["umount", iso_mnt], check=False, capture_output=True)
        shutil.rmtree(iso_mnt, ignore_errors=True)


def run_os_install(
    plan: OsInstallPlan,
    identity: OsIdentity,
    on_event: Callable[..., None] | None = None,
) -> None:
    if not plan.available or plan.target is None:
        raise OsInstallError(plan.reason or "Cannot install.")
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install a staged OS onto this computer")
    parser.add_argument("--plan", action="store_true", help="print a JSON stub (privilege probe)")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--iso")
    parser.add_argument("--iso-rel")
    parser.add_argument("--sha256")
    parser.add_argument("--size", default="0")
    parser.add_argument("--driver", default=DRIVER_UBUNTU)
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
    if args.plan and not args.apply:
        print(json.dumps({"available": False, "reason": "pass --apply to install"}))
        return 1
    if not args.apply:
        parser.error("need --plan or --apply")
    for key in ("iso", "iso_rel", "sha256", "driver", "target", "hostname", "username", "password_hash"):
        if not getattr(args, key.replace("-", "_")):
            emit("ERROR", f"missing --{key.replace('_', '-')}")
            return 2
    if args.driver != DRIVER_UBUNTU:
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
        prepare_ubuntu(plan, identity)
    except OsInstallError as exc:
        emit("ERROR", str(exc))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
