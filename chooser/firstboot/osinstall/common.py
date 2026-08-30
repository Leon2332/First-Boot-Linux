"""Shared types and helpers for OS install drivers.

Distro-specific installers live in sibling modules. Do not put Ubuntu,
Mint, or Fedora logic here.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass

from firstboot.disk import Disk
from firstboot.install import InstallError

HELPER = "/usr/libexec/firstboot/install-os"
OSINSTALL_REL = "boot/osinstall"
MIN_TARGET_BYTES = 16 * 1024 * 1024 * 1024
TORAM_HEADROOM = 2 * 1024 * 1024 * 1024
USER_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
HOST_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")
ISO_REL_RE = re.compile(r"^/images/[A-Za-z0-9._+-]+\.(iso|img)$")
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


def secure_boot_enabled() -> bool | None:
    """True / False when the firmware reports it; None if unknown.

    Tests may set FIRSTBOOT_SECURE_BOOT=1 or 0.
    """
    forced = os.environ.get("FIRSTBOOT_SECURE_BOOT", "").strip().lower()
    if forced in ("1", "true", "yes", "on"):
        return True
    if forced in ("0", "false", "no", "off"):
        return False
    if not os.path.isdir("/sys/firmware/efi"):
        return False
    efi = "/sys/firmware/efi/efivars"
    if not os.path.isdir(efi):
        return None
    try:
        names = os.listdir(efi)
    except OSError:
        return None
    for name in names:
        if not name.startswith("SecureBoot-"):
            continue
        try:
            with open(os.path.join(efi, name), "rb") as fh:
                data = fh.read()
        except OSError:
            return None
        if len(data) >= 5:
            return data[4] == 1
        return None
    return None


VENDOR_SHIM_GRUB = """# First Boot Linux — vendor shim (Secure Boot)
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


def find_iso_efi(iso_mnt: str) -> tuple[str, str, str]:
    """Shim, GRUB, and optional MokManager on a live ISO. Empty strings if missing."""
    dirs: list[str] = []
    for a in ("EFI", "efi"):
        for b in ("BOOT", "boot"):
            path = os.path.join(iso_mnt, a, b)
            if os.path.isdir(path):
                dirs.append(path)
    shim = grub = mm = ""
    for folder in dirs:
        try:
            names = os.listdir(folder)
        except OSError:
            continue
        by_lower = {n.lower(): os.path.join(folder, n) for n in names}
        if not shim:
            for key in ("bootx64.efi", "shimx64.efi"):
                path = by_lower.get(key, "")
                if path and os.path.isfile(path):
                    shim = path
                    break
        if not grub:
            path = by_lower.get("grubx64.efi", "")
            if path and os.path.isfile(path):
                grub = path
        if not mm:
            path = by_lower.get("mmx64.efi", "")
            if path and os.path.isfile(path):
                mm = path
        if shim and grub:
            return shim, grub, mm
    return shim, grub, mm


def install_vendor_shim(
    iso_mnt: str,
    plan: OsInstallPlan,
    sys_uuid: str,
    name: str,
    linux_args: str,
    *,
    bootnext_label: str,
) -> bool:
    """Copy the ISO's Microsoft-signed shim to FBL-ESP and BootNext it.

    Canonical GRUB will not load a non-Canonical kernel with Secure Boot on.
    Returns True when the files were copied.
    """
    if plan.live is None:
        return False
    esp_part = plan.live.part_named("FBL-ESP")
    if esp_part is None:
        return False
    src_shim, src_grub, src_mm = find_iso_efi(iso_mnt)
    if not src_shim or not src_grub:
        return False
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
        if src_mm:
            shutil.copy2(src_mm, os.path.join(dest, "mmx64.efi"))
        with open(os.path.join(dest, "grub.cfg"), "w", encoding="utf-8") as fh:
            fh.write(
                VENDOR_SHIM_GRUB.format(
                    sys_uuid=sys_uuid, name=name, linux_args=linux_args
                )
            )
    finally:
        if mounted:
            subprocess.run(["umount", esp_mp], check=False, capture_output=True)
            shutil.rmtree(esp_mp, ignore_errors=True)
    if not shutil.which("efibootmgr"):
        return True
    partnum = efi_part_number(esp_part.path)
    from firstboot.install import efi_ids_for_label

    def _efi_list() -> str:
        proc = subprocess.run(
            ["efibootmgr"], check=False, capture_output=True, text=True
        )
        return proc.stdout or ""

    for bootnum in efi_ids_for_label(_efi_list(), bootnext_label):
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
            bootnext_label,
            "--loader",
            r"\EFI\osinstall\shimx64.efi",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    created = efi_ids_for_label(_efi_list(), bootnext_label)
    if created:
        subprocess.run(
            ["efibootmgr", "--bootnext", created[-1]],
            check=False,
            capture_output=True,
            text=True,
        )
    return True
