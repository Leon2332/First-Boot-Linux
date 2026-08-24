"""Shared types and helpers for OS install drivers.

Distro-specific installers live in sibling modules. Do not put Ubuntu,
Mint, or Fedora logic here.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass

from firstboot.disk import Disk
from firstboot.install import InstallError

HELPER = "/usr/libexec/firstboot/install-os"
OSINSTALL_REL = "boot/osinstall"
MIN_TARGET_BYTES = 16 * 1024 * 1024 * 1024
TORAM_HEADROOM = 2 * 1024 * 1024 * 1024
USER_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
HOST_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")
ISO_REL_RE = re.compile(r"^/images/[A-Za-z0-9._+-]+\.iso$")
ITOA64 = "./0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
_SHA512_ROUNDS = 5000


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


def yaml_str(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def kernel_disk_path(dev: str) -> str:
    """DEVNAME-style path. match.path does not resolve /dev/disk/by-id."""
    if not dev:
        return dev
    try:
        real = os.path.realpath(dev)
    except OSError:
        real = dev
    return real


def kickstart_disk_id(dev: str) -> str:
    return os.path.basename(kernel_disk_path(dev))


def kickstart_gecos(realname: str) -> str:
    cleaned = realname.replace('"', " ").replace("'", " ").replace("\n", " ").strip()
    return " ".join(cleaned.split())


def casper_boot_files(iso_mnt: str) -> tuple[str, str]:
    vmlinuz = os.path.join(iso_mnt, "casper", "vmlinuz")
    for name in ("initrd", "initrd.lz", "initrd.gz"):
        initrd = os.path.join(iso_mnt, "casper", name)
        if os.path.isfile(vmlinuz) and os.path.isfile(initrd):
            return vmlinuz, initrd
    raise OsInstallError("This image is not a live ISO.")


def casper_kernel_args(
    iso_rel: str, *, toram: bool, extra: str | None = None
) -> str:
    flag = "toram " if toram else ""
    args = extra if extra is not None else ""
    return (
        f"boot=casper iso-scan/filename={iso_rel} live-media-path=casper "
        f"ignore_uuid nopersistent noprompt {flag}{args}"
    ).rstrip()


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


def run_checked(cmd: list[str], *, what: str) -> None:
    try:
        proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
    except OSError as exc:
        raise OsInstallError(f"{what}: {exc}") from exc
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip().splitlines()
        tail = detail[-1] if detail else f"exit {proc.returncode}"
        raise OsInstallError(f"{what}: {tail}")


def iso_relpath(file_rel: str) -> str:
    rel = file_rel.strip()
    if rel.startswith("images/"):
        rel = "/" + rel
    if not rel.startswith("/"):
        rel = "/" + rel
    return rel
