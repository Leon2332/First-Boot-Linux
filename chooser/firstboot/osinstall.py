"""Customer OS install from a staged ISO.

The helper verifies the ISO, copies the installer kernel plus initrd
onto FBL-SYS (GRUB-readable; FBL-DATA is not), injects the installer
seed into the initrd's main archive, and rewrites GRUB so the next boot
is that installer. Same-disk installs copy the live image to RAM.
kexec is not used (lockdown).

Ubuntu (driver `ubuntu-autoinstall`) is Subiquity + autoinstall.yaml.
Mint 22.3 (driver `mint`) is Ubiquity + preseed.cfg. Do not feed Mint
an autoinstall YAML. Fedora Plasma (driver `fedora-kickstart`) is
Anaconda from the KDE live ISO + a kickstart. Do not feed Fedora
autoinstall YAML or a casper cmdline. Live `liveinst` rejects
`inst.ks` — pass `liveinst` without it and replace `/usr/sbin/liveinst`
so livesys-late starts Anaconda with the kickstart.
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
DRIVER_MINT = "mint"
DRIVER_FEDORA = "fedora-kickstart"
DRIVERS_READY = frozenset({DRIVER_UBUNTU, DRIVER_MINT, DRIVER_FEDORA})
OSINSTALL_REL = "boot/osinstall"
UBUNTU_LINUX_EXTRA = "autoinstall subiquity.autoinstallpath=/autoinstall.yaml"
MINT_LINUX_EXTRA = "username=mint hostname=mint automatic-ubiquity"
FEDORA_LIVE_LABEL = "Fedora-KDE-Live-44"
FEDORA_LINUX_FLAG = "fbl.install"
FEDORA_BOOTNEXT_LABEL = "Install Fedora"
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

MINT_EFI_CLEANUP = """#!/bin/sh
for n in $(efibootmgr 2>/dev/null | sed -n 's/^Boot\\([0-9A-Fa-f]\\{4\\}\\).*First Boot Linux.*/\\1/p'); do
  efibootmgr -b "$n" -B || true
done
exit 0
"""

MINT_CASPER_BOTTOM = """#!/bin/sh
PREREQ=""
prereqs() { echo "$PREREQ"; }
case $1 in
prereqs) prereqs; exit 0 ;;
esac

mkdir -p /root/var/log /root/usr/lib
log=/root/var/log/firstboot-mint.log
{
  echo "cmdline: $(cat /proc/cmdline 2>/dev/null)"
  cat /root/etc/hostname 2>/dev/null
  ls -l /preseed.cfg /scripts/casper-bottom/29fbl-mint 2>&1
  lsblk -o NAME,LABEL,MOUNTPOINT,TYPE 2>/dev/null
} > "$log"

if [ -f /preseed.cfg ]; then
  cp /preseed.cfg /root/preseed.cfg
  chmod 644 /root/preseed.cfg
fi

if [ -f /usr/lib/firstboot-efi-cleanup ]; then
  cp /usr/lib/firstboot-efi-cleanup /root/usr/lib/firstboot-efi-cleanup
  chmod 755 /root/usr/lib/firstboot-efi-cleanup
fi

if grep -qw toram /proc/cmdline; then
  {
    echo "=== drop FBL-DATA after toram ==="
    findmnt 2>/dev/null
    losetup -a 2>/dev/null
  } >> "$log" 2>&1
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
  _dev=$(blkid -L FBL-DATA 2>/dev/null) || true
  if [ -n "$_dev" ]; then
    umount -l "$_dev" 2>/dev/null || true
  fi
  swapoff -a 2>/dev/null || true
  {
    echo "=== after ==="
    findmnt 2>/dev/null
    losetup -a 2>/dev/null
    lsblk -o NAME,LABEL,MOUNTPOINT,TYPE 2>/dev/null
  } >> "$log" 2>&1
fi

echo "live_preseed=$(test -f /root/preseed.cfg && echo yes || echo no)" >> "$log"
exit 0
"""

FEDORA_LIVEINST_WRAPPER = """#!/bin/bash
# livesys-late runs this. Official liveinst rejects inst.ks on Live media.
log=/var/log/firstboot-fedora.log
{
  echo "=== fbl liveinst wrapper ==="
  date
  cat /proc/cmdline 2>/dev/null
  ls -l /ks.cfg /usr/sbin/anaconda /usr/bin/anaconda /usr/sbin/liveinst.real 2>/dev/null
} >> "$log" 2>&1
ana=
for p in /usr/sbin/anaconda /usr/bin/anaconda /usr/libexec/anaconda/anaconda; do
  if [ -x "$p" ]; then
    ana=$p
    break
  fi
done
if [ -z "$ana" ]; then
  echo "anaconda missing" >> "$log"
  if [ -x /usr/sbin/liveinst.real ]; then
    exec /usr/sbin/liveinst.real "$@"
  fi
  exit 1
fi
exec "$ana" --liveinst --kickstart=/ks.cfg --graphical "$@"
"""

FEDORA_DRACUT_HOOK = """#!/bin/sh
# Overlay kickstart + liveinst wrapper onto the live root.
# Fedora dracut keeps hooks in var/lib/dracut/hooks (lib/dracut/hooks is a symlink).
root="${NEWROOT:-/sysroot}"
log="$root/var/log/firstboot-fedora.log"
mkdir -p "$root/var/log" "$root/usr/sbin"
{
  echo "=== fbl fedora pre-pivot ==="
  cat /proc/cmdline 2>/dev/null
  ls -l /ks.cfg /fbl-liveinst /var/lib/dracut/hooks/pre-pivot 2>/dev/null
} > "$log" 2>&1
if [ -f /ks.cfg ]; then
  cp /ks.cfg "$root/ks.cfg"
  chmod 644 "$root/ks.cfg"
fi
if [ -f /fbl-liveinst ]; then
  if [ -e "$root/usr/sbin/liveinst" ] && [ ! -e "$root/usr/sbin/liveinst.real" ]; then
    mv "$root/usr/sbin/liveinst" "$root/usr/sbin/liveinst.real" || true
  fi
  cp /fbl-liveinst "$root/usr/sbin/liveinst"
  chmod 755 "$root/usr/sbin/liveinst"
fi
if command -v restorecon >/dev/null; then
  restorecon -F "$root/ks.cfg" "$root/usr/sbin/liveinst" 2>/dev/null || true
fi
echo "ks=$(test -f "$root/ks.cfg" && echo yes || echo no) liveinst=$(test -x "$root/usr/sbin/liveinst" && echo yes || echo no)" >> "$log"
exit 0
"""

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

FEDORA_SHIM_GRUB = """# First Boot Linux — Fedora shim (Secure Boot)
set default=0
set timeout=2

search --no-floppy --set=root --fs-uuid {sys_uuid}
if [ ! -f /boot/osinstall/vmlinuz ]; then
	search --no-floppy --set=root --label FBL-SYS
fi

menuentry "Install {name}" {{
    linux /boot/osinstall/vmlinuz {linux_args} ---
    initrd /boot/osinstall/initrd
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
    if distro.install not in DRIVERS_READY:
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


def preseed_line(owner: str, key: str, kind: str, value: str) -> str:
    return f"{owner} {key} {kind} {value}"


def mint_preseed(identity: OsIdentity, target_path: str) -> str:
    """Ubiquity preseed for Mint 22.3. Not Subiquity autoinstall."""
    disk = kernel_disk_path(target_path)
    lines = [
        preseed_line("d-i", "debian-installer/locale", "string", "en_US.UTF-8"),
        preseed_line("d-i", "debian-installer/language", "string", "en"),
        preseed_line("d-i", "debian-installer/country", "string", "US"),
        preseed_line("d-i", "localechooser/languagelist", "string", "en"),
        preseed_line("d-i", "languagechooser/language-name", "string", "English"),
        preseed_line("d-i", "countrychooser/shortlist", "select", "US"),
        preseed_line(
            "d-i", "localechooser/supported-locales", "multiselect", "en_US.UTF-8"
        ),
        preseed_line("d-i", "keyboard-configuration/layoutcode", "string", "us"),
        preseed_line("d-i", "keyboard-configuration/xkb-keymap", "select", "us"),
        preseed_line("d-i", "keyboard-configuration/modelcode", "string", "pc105"),
        preseed_line("d-i", "console-setup/ask_detect", "boolean", "false"),
        preseed_line("d-i", "console-setup/layoutcode", "string", "us"),
        preseed_line("d-i", "time/zone", "string", "UTC"),
        preseed_line("d-i", "clock-setup/utc", "boolean", "true"),
        preseed_line("d-i", "clock-setup/ntp", "boolean", "false"),
        preseed_line("d-i", "netcfg/get_hostname", "string", identity.hostname),
        preseed_line("d-i", "passwd/user-fullname", "string", identity.realname),
        preseed_line("d-i", "passwd/username", "string", identity.username),
        preseed_line(
            "d-i", "passwd/user-password-crypted", "password", identity.password_hash
        ),
        preseed_line("d-i", "passwd/auto-login", "boolean", "false"),
        preseed_line("d-i", "user-setup/allow-password-weak", "boolean", "true"),
        preseed_line("d-i", "user-setup/encrypt-home", "boolean", "false"),
        preseed_line("d-i", "partman-auto/method", "string", "regular"),
        preseed_line("d-i", "partman-auto/disk", "string", disk),
        preseed_line(
            "d-i", "partman-auto/init_automatically_partition", "select", "regular"
        ),
        preseed_line("d-i", "partman-auto/choose_recipe", "select", "atomic"),
        preseed_line("d-i", "partman-auto/purge_lvm_from_device", "boolean", "true"),
        preseed_line("d-i", "partman-lvm/device_remove_lvm", "boolean", "true"),
        preseed_line("d-i", "partman-md/device_remove_md", "boolean", "true"),
        preseed_line("d-i", "partman-lvm/confirm", "boolean", "true"),
        preseed_line("d-i", "partman-md/confirm", "boolean", "true"),
        preseed_line("d-i", "partman-lvm/confirm_nooverwrite", "boolean", "true"),
        preseed_line(
            "d-i", "partman-partitioning/confirm_write_new_label", "boolean", "true"
        ),
        preseed_line("d-i", "partman/choose_partition", "select", "finish"),
        preseed_line("d-i", "partman/confirm", "boolean", "true"),
        preseed_line("d-i", "partman/confirm_nooverwrite", "boolean", "true"),
        preseed_line("d-i", "partman/confirm_write_new_label", "boolean", "true"),
        preseed_line("d-i", "grub-installer/only_debian", "boolean", "true"),
        preseed_line("d-i", "grub-installer/with_other_os", "boolean", "false"),
        preseed_line("ubiquity", "ubiquity/use_nonfree", "boolean", "false"),
        preseed_line("ubiquity", "ubiquity/download_updates", "boolean", "false"),
        preseed_line("ubiquity", "ubiquity/partman-skip-unmount", "boolean", "true"),
        preseed_line("ubiquity", "ubiquity/summary", "string", ""),
        preseed_line("ubiquity", "ubiquity/reboot", "boolean", "true"),
        preseed_line("ubiquity", "ubiquity/reboot_on_failure", "boolean", "false"),
        preseed_line(
            "ubiquity",
            "ubiquity/success_command",
            "string",
            "/usr/lib/firstboot-efi-cleanup",
        ),
    ]
    return "\n".join(lines) + "\n"


def kickstart_disk_id(dev: str) -> str:
    return os.path.basename(kernel_disk_path(dev))


def kickstart_gecos(realname: str) -> str:
    cleaned = realname.replace('"', " ").replace("'", " ").replace("\n", " ").strip()
    return " ".join(cleaned.split())


def fedora_kickstart(identity: OsIdentity, target_path: str) -> str:
    """Anaconda kickstart for Fedora 44 KDE Live. Not Ubiquity, not autoinstall."""
    disk = kernel_disk_path(target_path)
    drive = kickstart_disk_id(target_path)
    gecos = kickstart_gecos(identity.realname or identity.username)
    user = identity.username
    host = identity.hostname
    hashed = identity.password_hash
    return (
        "#version=F44\n"
        "# First Boot Linux — Fedora Plasma live install\n"
        "graphical\n"
        "lang en_US.UTF-8\n"
        "keyboard --vckeymap=us --xlayouts='us'\n"
        "timezone UTC\n"
        f"network --hostname={host}\n"
        "rootpw --lock\n"
        f'user --name={user} --gecos="{gecos}" --password="{hashed}" '
        "--iscrypted --groups=wheel\n"
        "firstboot --disable\n"
        f"ignoredisk --only-use={drive}\n"
        "zerombr\n"
        f"clearpart --all --initlabel --disklabel=gpt --drives={drive}\n"
        "autopart --type=btrfs\n"
        f"bootloader --location=mbr --boot-drive={drive}\n"
        "reboot\n"
        "%addon com_redhat_kdump --disable\n"
        "%end\n"
        "%pre --interpreter=/bin/bash\n"
        f"disk={disk}\n"
        "log=/tmp/firstboot-fedora-pre.log\n"
        "{\n"
        "  echo '=== fbl fedora pre ==='\n"
        "  date\n"
        "  cat /proc/cmdline 2>/dev/null\n"
        "  lsblk -o NAME,LABEL,MOUNTPOINT,TYPE 2>/dev/null\n"
        "  findmnt 2>/dev/null\n"
        "  losetup -a 2>/dev/null\n"
        "} > \"$log\" 2>&1\n"
        "if command -v losetup >/dev/null; then\n"
        "  losetup -ln -O NAME,BACK-FILE 2>/dev/null | while read -r name back; do\n"
        "    case \"$back\" in\n"
        "      *isodevice*|*FBL-DATA*) umount -l \"$name\" 2>/dev/null || true; "
        "losetup -d \"$name\" 2>/dev/null || true ;;\n"
        "    esac\n"
        "  done\n"
        "fi\n"
        "if [ -b \"$disk\" ]; then\n"
        "  lsblk -ln -o PATH,MOUNTPOINT \"$disk\" 2>/dev/null | while read -r path mp; do\n"
        "    [ -n \"$mp\" ] && [ \"$mp\" != \"/\" ] && umount -l \"$mp\" 2>/dev/null || true\n"
        "  done\n"
        "fi\n"
        "umount -l /isodevice /run/payload 2>/dev/null || true\n"
        "dev=$(blkid -L FBL-DATA 2>/dev/null) || true\n"
        "[ -n \"$dev\" ] && umount -l \"$dev\" 2>/dev/null || true\n"
        "swapoff -a 2>/dev/null || true\n"
        "udevadm settle 2>/dev/null || true\n"
        "{\n"
        "  echo '=== after ==='\n"
        "  lsblk -o NAME,LABEL,MOUNTPOINT,TYPE 2>/dev/null\n"
        "  findmnt 2>/dev/null\n"
        "  losetup -a 2>/dev/null\n"
        "} >> \"$log\" 2>&1\n"
        "%end\n"
        "%post --interpreter=/bin/bash\n"
        "for n in $(efibootmgr 2>/dev/null | "
        "sed -n 's/^Boot\\([0-9A-Fa-f]\\{4\\}\\).*\\(First Boot Linux\\|Install Fedora\\).*/\\1/p');\n"
        "do\n"
        "  efibootmgr -b \"$n\" -B || true\n"
        "done\n"
        f"if ! getent passwd {user} >/dev/null 2>&1; then\n"
        f"  useradd -m -G wheel -c '{gecos}' {user} || true\n"
        f"  echo '{user}:{hashed}' | chpasswd -e || true\n"
        "fi\n"
        "systemctl disable --global plasma-setup.service 2>/dev/null || true\n"
        "rm -f /etc/xdg/autostart/plasma-setup*.desktop "
        "/usr/lib/systemd/user/plasma-setup.service 2>/dev/null || true\n"
        "mkdir -p /var/lib/plasma-setup\n"
        "touch /var/lib/plasma-setup/completed\n"
        "%end\n"
    )


def fedora_kernel_args(iso_rel: str, label: str, *, toram: bool) -> str:
    ram = "rd.live.ram=1 " if toram else ""
    vol = (label or FEDORA_LIVE_LABEL).strip() or FEDORA_LIVE_LABEL
    return (
        f"root=live:CDLABEL={vol} rd.live.image iso-scan/filename={iso_rel} "
        f"{ram}{FEDORA_LINUX_FLAG} liveinst"
    )


def casper_kernel_args(
    iso_rel: str, *, toram: bool, extra: str | None = None
) -> str:
    flag = "toram " if toram else ""
    args = extra if extra is not None else UBUNTU_LINUX_EXTRA
    return (
        f"boot=casper iso-scan/filename={iso_rel} live-media-path=casper "
        f"ignore_uuid nopersistent noprompt {flag}{args}"
    )


def osinstall_grub(
    sys_uuid: str,
    iso_rel: str,
    name: str,
    *,
    toram: bool,
    extra: str | None = None,
    linux_args: str | None = None,
) -> str:
    args = linux_args or casper_kernel_args(iso_rel, toram=toram, extra=extra)
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
            or rel.endswith("firstboot-efi-cleanup")
            or rel.endswith("fbl-liveinst")
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
    """Add files to the last (main) cpio of a concatenated casper initrd.

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


def _casper_boot_files(iso_mnt: str) -> tuple[str, str]:
    vmlinuz = os.path.join(iso_mnt, "casper", "vmlinuz")
    for name in ("initrd", "initrd.lz", "initrd.gz"):
        initrd = os.path.join(iso_mnt, "casper", name)
        if os.path.isfile(vmlinuz) and os.path.isfile(initrd):
            return vmlinuz, initrd
    raise OsInstallError("This image is not a live ISO.")


def _fedora_boot_files(iso_mnt: str) -> tuple[str, str]:
    candidates = (
        ("boot/x86_64/loader/linux", "boot/x86_64/loader/initrd"),
        ("images/pxeboot/vmlinuz", "images/pxeboot/initrd.img"),
    )
    for vrel, irel in candidates:
        vmlinuz = os.path.join(iso_mnt, vrel)
        initrd = os.path.join(iso_mnt, irel)
        if os.path.isfile(vmlinuz) and os.path.isfile(initrd):
            return vmlinuz, initrd
    raise OsInstallError("This image is not a Fedora live ISO.")


def _installer_boot_files(driver: str, iso_mnt: str) -> tuple[str, str]:
    if driver == DRIVER_FEDORA:
        return _fedora_boot_files(iso_mnt)
    return _casper_boot_files(iso_mnt)


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


def iso_volume_id(path: str) -> str:
    try:
        with open(path, "rb") as fh:
            fh.seek(32768 + 40)
            raw = fh.read(32)
    except OSError:
        return ""
    return raw.decode("ascii", "replace").strip(" \x00")


def efi_part_number(part: str) -> str:
    base = os.path.basename(part)
    if "p" in base and base.rsplit("p", 1)[-1].isdigit():
        return base.rsplit("p", 1)[-1]
    i = len(base)
    while i and base[i - 1].isdigit():
        i -= 1
    return base[i:] if i < len(base) else "1"


def _seed_files(
    plan: OsInstallPlan, identity: OsIdentity, serial: str
) -> tuple[dict[str, str | bytes], str]:
    if plan.target is None:
        raise OsInstallError("Cannot install.")
    if plan.driver == DRIVER_UBUNTU:
        yaml = autoinstall_yaml(identity, plan.target.path, serial=serial)
        user_data = cloud_config_user_data(
            identity, plan.target.path, serial=serial
        )
        return (
            {
                "autoinstall.yaml": yaml,
                "user-data": user_data,
                "scripts/casper-bottom/29fbl-autoinstall": CASPER_BOTTOM,
            },
            UBUNTU_LINUX_EXTRA,
        )
    if plan.driver == DRIVER_MINT:
        return (
            {
                "preseed.cfg": mint_preseed(identity, plan.target.path),
                "usr/lib/firstboot-efi-cleanup": MINT_EFI_CLEANUP,
                "scripts/casper-bottom/29fbl-mint": MINT_CASPER_BOTTOM,
            },
            MINT_LINUX_EXTRA,
        )
    if plan.driver == DRIVER_FEDORA:
        return (
            {
                "ks.cfg": fedora_kickstart(identity, plan.target.path),
                "fbl-liveinst": FEDORA_LIVEINST_WRAPPER,
                "var/lib/dracut/hooks/pre-pivot/90-fbl-ks.sh": FEDORA_DRACUT_HOOK,
            },
            FEDORA_LINUX_FLAG,
        )
    raise OsInstallError(f"{plan.driver} is not available yet.")


def _install_fedora_shim(
    iso_mnt: str,
    plan: OsInstallPlan,
    sys_uuid: str,
    name: str,
    linux_args: str,
) -> None:
    """Copy Fedora's Microsoft-signed shim to FBL-ESP and BootNext it.

    Canonical GRUB will not load a Fedora kernel with Secure Boot on.
    Firmware BootNext of Fedora shim is the signed path.
    """
    if plan.live is None:
        return
    esp_part = plan.live.part_named("FBL-ESP")
    if esp_part is None:
        return
    src_shim = os.path.join(iso_mnt, "EFI", "BOOT", "BOOTX64.EFI")
    src_grub = os.path.join(iso_mnt, "EFI", "BOOT", "grubx64.efi")
    if not os.path.isfile(src_shim) or not os.path.isfile(src_grub):
        return
    mounted = False
    esp_mp = ""
    if esp_part.mountpoints:
        esp_mp = esp_part.mountpoints[0]
    else:
        esp_mp = tempfile.mkdtemp(prefix="fbl-esp-")
        run_checked(["mount", esp_part.path, esp_mp], what="mount the EFI partition")
        mounted = True
    try:
        dest = os.path.join(esp_mp, "EFI", "osinstall")
        os.makedirs(dest, exist_ok=True)
        shutil.copy2(src_shim, os.path.join(dest, "shimx64.efi"))
        shutil.copy2(src_grub, os.path.join(dest, "grubx64.efi"))
        mm = os.path.join(iso_mnt, "EFI", "BOOT", "mmx64.efi")
        if os.path.isfile(mm):
            shutil.copy2(mm, os.path.join(dest, "mmx64.efi"))
        with open(os.path.join(dest, "grub.cfg"), "w", encoding="utf-8") as fh:
            fh.write(
                FEDORA_SHIM_GRUB.format(
                    sys_uuid=sys_uuid, name=name, linux_args=linux_args
                )
            )
    finally:
        if mounted:
            subprocess.run(["umount", esp_mp], check=False, capture_output=True)
            shutil.rmtree(esp_mp, ignore_errors=True)
    if not shutil.which("efibootmgr"):
        return
    partnum = efi_part_number(esp_part.path)
    from firstboot.install import efi_ids_for_label

    def _efi_list() -> str:
        proc = subprocess.run(
            ["efibootmgr"], check=False, capture_output=True, text=True
        )
        return proc.stdout or ""

    for bootnum in efi_ids_for_label(_efi_list(), FEDORA_BOOTNEXT_LABEL):
        subprocess.run(
            ["efibootmgr", "--bootnum", bootnum, "--delete-bootnum"],
            check=False,
            capture_output=True,
            text=True,
        )
    subprocess.run(
        [
            "efibootmgr",
            "--create",
            "--disk",
            plan.live.path,
            "--part",
            partnum,
            "--label",
            FEDORA_BOOTNEXT_LABEL,
            "--loader",
            r"\EFI\osinstall\shimx64.efi",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    created = efi_ids_for_label(_efi_list(), FEDORA_BOOTNEXT_LABEL)
    if created:
        subprocess.run(
            ["efibootmgr", "--bootnext", created[-1]],
            check=False,
            capture_output=True,
            text=True,
        )


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

    label = plan.distro_name or "the system"
    emit("STEP", f"Preparing {label}…")
    iso_mnt = tempfile.mkdtemp(prefix="fbl-iso-")
    mounted = False
    try:
        run_checked(
            ["mount", "-o", "loop,ro", plan.iso_path, iso_mnt],
            what=f"mount the {label} image",
        )
        mounted = True
        vmlinuz, initrd = _installer_boot_files(plan.driver, iso_mnt)
        squash_size = _live_image_size(iso_mnt, plan.size_bytes)
        need = squash_size + TORAM_HEADROOM
        have = mem_available()
        toram = have >= need
        if plan.same_disk and not toram:
            raise OsInstallError(
                "This computer needs about "
                f"{format_size(need)} of memory to install {label} from the internal disk."
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
        files, extra = _seed_files(plan, identity, serial)
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
        if plan.driver == DRIVER_FEDORA:
            vol = iso_volume_id(plan.iso_path) or FEDORA_LIVE_LABEL
            linux_args = fedora_kernel_args(plan.iso_rel, vol, toram=toram)
        else:
            linux_args = casper_kernel_args(plan.iso_rel, toram=toram, extra=extra)
        grub = osinstall_grub(
            sys_uuid,
            plan.iso_rel,
            label,
            toram=toram,
            extra=extra,
            linux_args=linux_args,
        )
        grub_path = os.path.join(sys_mp, "boot", "grub", "grub.cfg")
        os.makedirs(os.path.dirname(grub_path), exist_ok=True)
        with open(grub_path, "w", encoding="utf-8") as fh:
            fh.write(grub)
        if plan.driver == DRIVER_FEDORA:
            _install_fedora_shim(iso_mnt, plan, sys_uuid, label, linux_args)
        os.sync()
        prog(100)
        emit("STEP", f"Restarting to install {plan.distro_name or label}…")
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
    if args.driver not in DRIVERS_READY:
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
