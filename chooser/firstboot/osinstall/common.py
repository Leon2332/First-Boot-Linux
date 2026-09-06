"""Shared types and helpers for OS install drivers.

Native unpack/configure steps live here. ISO-specific files call them.
Do not put Ubuntu GNOME vs Mint vs Fedora branching here.
"""

from __future__ import annotations

import errno
import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass

from firstboot.disk import ESP_MIB_DEFAULT, Disk, part_path
from firstboot.i18n import _
from firstboot.install import (
    EXT4_GRUB_OPTS,
    InstallError,
    blkid_uuid,
    efi_ids_for_label,
    wait_dev,
)

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


LOG_PATH = "/run/firstboot/osinstall.log"
TARGET_LOG_REL = "var/log/firstboot-install.log"
RAM_DIR = "/run/fbl-install"
FORBIDDEN_CMDLINE = (
    "fbl.install",
    "toram",
    "iso-scan/",
    "systemd.unit=",
    "systemd.mask=",
    "rd.live.",
    "inst.cmdline",
)
DM_UNITS = {
    "gdm": ("gdm.service", "gdm3.service"),
    "sddm": ("sddm.service",),
    "plasmalogin": ("plasmalogin.service",),
    "lightdm": ("lightdm.service",),
}
USER_GROUPS = (
    "adm",
    "cdrom",
    "sudo",
    "wheel",
    "dip",
    "plugdev",
    "lpadmin",
    "lxd",
    "sambashare",
    "users",
    "video",
    "render",
    "audio",
    "input",
    "dialout",
)


@dataclass(frozen=True)
class InstalledDisk:
    disk: str
    esp_dev: str
    root_dev: str
    esp_uuid: str
    root_uuid: str
    esp_mp: str
    root_mp: str
    boot_dev: str = ""
    boot_uuid: str = ""
    boot_mp: str = ""
    root_fstype: str = "ext4"
    root_fsopts: str = ""


class InstallLog:
    """File + stderr log. Helper stdout stays STEP/TICK/PROGRESS only."""

    def __init__(self, path: str = LOG_PATH) -> None:
        self.path = path
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._fh = open(path, "a", encoding="utf-8")

    def write(self, msg: str) -> None:
        line = msg if msg.endswith("\n") else msg + "\n"
        stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        text = f"{stamp} {line}"
        try:
            self._fh.write(text)
            self._fh.flush()
        except OSError:
            pass
        try:
            print(text, end="", file=sys.stderr, flush=True)
        except BrokenPipeError:
            pass
        except OSError as exc:
            if exc.errno != errno.EPIPE:
                raise

    def copy_to(self, dest: str) -> None:
        try:
            self._fh.flush()
        except OSError:
            pass
        os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
        try:
            shutil.copy2(self.path, dest)
        except OSError as exc:
            self.write(f"could not copy log to {dest}: {exc}")

    def close(self) -> None:
        try:
            self._fh.close()
        except OSError:
            pass


def is_native_driver(drv: object | None) -> bool:
    if drv is None:
        return False
    kind = getattr(drv, "unpack_kind", None)
    return bool(kind) and callable(getattr(drv, "unpack", None)) and callable(
        getattr(drv, "configure", None)
    )


def kernel_files(root: str) -> list[str]:
    boot = os.path.join(root, "boot")
    found: list[str] = []
    if not os.path.isdir(boot):
        return found
    try:
        names = os.listdir(boot)
    except OSError:
        return found
    for name in names:
        lower = name.lower()
        path = os.path.join(boot, name)
        if not os.path.isfile(path) and not os.path.islink(path):
            continue
        if lower.startswith("vmlinuz") or lower.startswith("initrd"):
            found.append(name)
        elif lower.startswith("initramfs") and lower.endswith(".img"):
            found.append(name)
    bls = os.path.join(boot, "loader", "entries")
    if os.path.isdir(bls):
        try:
            if any(n.endswith(".conf") for n in os.listdir(bls)):
                found.append("loader/entries")
        except OSError:
            pass
    return found


def read_text(path: str) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return ""


def cmdline_files(root: str) -> list[str]:
    paths = [
        os.path.join(root, "etc", "default", "grub"),
        os.path.join(root, "boot", "grub", "grub.cfg"),
        os.path.join(root, "boot", "grub2", "grub.cfg"),
        os.path.join(root, "etc", "kernel", "cmdline"),
        os.path.join(root, "etc", "cmdline"),
    ]
    bls = os.path.join(root, "boot", "loader", "entries")
    if os.path.isdir(bls):
        try:
            for name in os.listdir(bls):
                if name.endswith(".conf"):
                    paths.append(os.path.join(bls, name))
        except OSError:
            pass
    return paths


def leftover_cmdline(root: str) -> list[str]:
    hits: list[str] = []
    for path in cmdline_files(root):
        text = read_text(path)
        if not text:
            continue
        for token in FORBIDDEN_CMDLINE:
            if token in text:
                hits.append(f"{os.path.relpath(path, root)}:{token}")
    return hits


def default_target(root: str) -> str:
    link = os.path.join(root, "etc", "systemd", "system", "default.target")
    try:
        dest = os.readlink(link)
    except OSError:
        dest = ""
    base = os.path.basename(dest) if dest else ""
    if base:
        return base
    proc = subprocess.run(
        ["systemctl", f"--root={root}", "get-default"],
        check=False,
        capture_output=True,
        text=True,
    )
    return (proc.stdout or "").strip()


def dm_unit_names(display_manager: str) -> tuple[str, ...]:
    return DM_UNITS.get(display_manager, (f"{display_manager}.service",))


def unit_is_masked(root: str, unit: str) -> bool:
    for rel in (
        os.path.join("etc", "systemd", "system", unit),
        os.path.join("usr", "lib", "systemd", "system", unit),
        os.path.join("lib", "systemd", "system", unit),
    ):
        path = os.path.join(root, rel)
        try:
            if os.path.islink(path) and os.path.realpath(path) == "/dev/null":
                return True
        except OSError:
            continue
    return False


def unit_exists(root: str, unit: str) -> bool:
    for rel in (
        os.path.join("etc", "systemd", "system", unit),
        os.path.join("usr", "lib", "systemd", "system", unit),
        os.path.join("lib", "systemd", "system", unit),
        os.path.join("usr", "lib", "systemd", "system", unit + ".wants"),
    ):
        path = os.path.join(root, rel)
        if os.path.isfile(path) or os.path.islink(path):
            return True
    return False


def esp_bootloader_ok(efi_mp: str) -> bool:
    bootx64 = os.path.join(efi_mp, "EFI", "BOOT", "BOOTX64.EFI")
    if os.path.isfile(bootx64):
        return True
    efi = os.path.join(efi_mp, "EFI")
    if not os.path.isdir(efi):
        return False
    try:
        vendors = os.listdir(efi)
    except OSError:
        return False
    for vendor in vendors:
        folder = os.path.join(efi, vendor)
        if not os.path.isdir(folder):
            continue
        for name in ("grubx64.efi", "shimx64.efi", "BOOTX64.EFI", "bootx64.efi"):
            if os.path.isfile(os.path.join(folder, name)):
                return True
    return False


def fstab_uuid_ok(root: str, disk: InstalledDisk) -> list[str]:
    text = read_text(os.path.join(root, "etc", "fstab"))
    fails: list[str] = []
    if not text.strip():
        return ["fstab is missing"]
    if disk.root_uuid and disk.root_uuid not in text:
        fails.append("fstab does not mention the root UUID")
    if disk.esp_uuid and disk.esp_uuid not in text:
        fails.append("fstab does not mention the ESP UUID")
    if disk.boot_uuid and disk.boot_uuid not in text:
        fails.append("fstab does not mention the boot UUID")
    return fails


def passwd_has_user(root: str, username: str) -> bool:
    for line in read_text(os.path.join(root, "etc", "passwd")).splitlines():
        if line.startswith(username + ":"):
            return True
    return False


def shadow_has_user(root: str, username: str) -> bool:
    for line in read_text(os.path.join(root, "etc", "shadow")).splitlines():
        if line.startswith(username + ":"):
            parts = line.split(":")
            if len(parts) > 1 and parts[1] and parts[1] not in ("*", "!", "!!"):
                return True
    return False


def health_check(
    target_root: str,
    efi_mp: str,
    identity: OsIdentity,
    disk: InstalledDisk,
    *,
    display_manager: str,
    boot_log: str = "",
) -> list[str]:
    """Return human-readable failures. Empty means the tree looks installed."""
    fails: list[str] = []
    if not os.path.isdir(target_root) or not os.path.isdir(efi_mp):
        fails.append("Root and ESP are not mounted where we think they are.")
        return fails
    if os.path.exists(disk.root_dev) and not os.path.ismount(target_root):
        fails.append("Root and ESP are not mounted where we think they are.")
    if os.path.exists(disk.esp_dev) and not os.path.ismount(efi_mp):
        fails.append("Root and ESP are not mounted where we think they are.")
    fails.extend(fstab_uuid_ok(target_root, disk))
    if not kernel_files(target_root):
        fails.append("No kernel + initrd under /boot.")
    if not esp_bootloader_ok(efi_mp):
        fails.append("ESP is missing that distro's bootloader.")
    if not passwd_has_user(target_root, identity.username):
        fails.append("The customer account is missing from passwd.")
    if not shadow_has_user(target_root, identity.username):
        fails.append("The customer account is missing from shadow.")
    target = default_target(target_root)
    if target and target != "graphical.target":
        fails.append(f"Default boot target is {target}, not graphical.target.")
    if not target:
        fails.append("Default boot target is not graphical.target.")
    leftover = leftover_cmdline(target_root)
    if leftover:
        fails.append("Installed cmdline still has installer tokens.")
    units = dm_unit_names(display_manager)
    present = [u for u in units if unit_exists(target_root, u)]
    if not present:
        fails.append(f"Display manager {display_manager} is missing.")
    else:
        if all(unit_is_masked(target_root, u) for u in present):
            fails.append(f"Display manager {display_manager} is masked.")
    if boot_log:
        lower = boot_log.lower()
        # grub-install often fails in the live chroot (no grub-efi modules);
        # casper then copies shim from the ISO. That is success if the ESP
        # already has BOOTX64.EFI.
        if ("grub-install: error" in lower or "fatal:" in lower) and not esp_bootloader_ok(
            efi_mp
        ):
            fails.append("Bootloader install logged an error.")
    # unique, keep order
    seen: set[str] = set()
    out: list[str] = []
    for item in fails:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def write_fstab(root: str, disk: InstalledDisk) -> None:
    path = os.path.join(root, "etc", "fstab")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fstype = disk.root_fstype or "ext4"
    opts = disk.root_fsopts or (
        "errors=remount-ro" if fstype == "ext4" else "defaults"
    )
    passno = "0 0" if fstype == "btrfs" else "0 1"
    lines = [
        "# /etc/fstab: static file system information.",
        f"UUID={disk.root_uuid} / {fstype} {opts} {passno}",
    ]
    if disk.boot_uuid:
        lines.append(f"UUID={disk.boot_uuid} /boot ext4 defaults 1 2")
    esp_opts = "umask=0077,shortname=winnt" if fstype == "btrfs" else "umask=0077"
    esp_pass = "0 2" if disk.boot_uuid else "0 1"
    lines.append(f"UUID={disk.esp_uuid} /boot/efi vfat {esp_opts} {esp_pass}")
    if fstype == "btrfs" and "subvol=root" in opts:
        home_opts = opts.replace("subvol=root", "subvol=home")
        lines.append(f"UUID={disk.root_uuid} /home btrfs {home_opts} 0 0")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def write_hostname(root: str, hostname: str) -> None:
    with open(os.path.join(root, "etc", "hostname"), "w", encoding="utf-8") as fh:
        fh.write(hostname + "\n")
    hosts = os.path.join(root, "etc", "hosts")
    lines = read_text(hosts).splitlines()
    out: list[str] = []
    seen_local = False
    for line in lines:
        stripped = line.split("#", 1)[0].strip()
        if stripped.startswith("127.0.1.1"):
            out.append(f"127.0.1.1\t{hostname}")
            seen_local = True
            continue
        out.append(line)
    if not seen_local:
        if out and out[-1] != "":
            out.append("")
        out.append(f"127.0.1.1\t{hostname}")
    if not any(l.split("#", 1)[0].strip().startswith("127.0.0.1") for l in out):
        out.insert(0, "127.0.0.1\tlocalhost")
    with open(hosts, "w", encoding="utf-8") as fh:
        fh.write("\n".join(out).rstrip() + "\n")


def _rewrite_table(path: str, drop: set[str], add: str | None = None) -> None:
    lines = []
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    kept = [ln for ln in lines if ln.split(":", 1)[0] not in drop]
    if add:
        kept.append(add.rstrip("\n"))
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(kept) + ("\n" if kept else ""))


def _group_ids(root: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for line in read_text(os.path.join(root, "etc", "group")).splitlines():
        parts = line.split(":")
        if len(parts) >= 3:
            found[parts[0]] = parts[2]
    return found


def delete_users(root: str, names: tuple[str, ...], log: InstallLog | None = None) -> None:
    drop = {n for n in names if n}
    if not drop:
        return
    homes: list[str] = []
    for line in read_text(os.path.join(root, "etc", "passwd")).splitlines():
        parts = line.split(":")
        if len(parts) >= 6 and parts[0] in drop:
            homes.append(parts[5])
    _rewrite_table(os.path.join(root, "etc", "passwd"), drop)
    _rewrite_table(os.path.join(root, "etc", "shadow"), drop)
    group_path = os.path.join(root, "etc", "group")
    gshadow = os.path.join(root, "etc", "gshadow")
    _rewrite_table(group_path, drop)
    if os.path.isfile(gshadow):
        _rewrite_table(gshadow, drop)
    lines = []
    for line in read_text(group_path).splitlines():
        parts = line.split(":")
        if len(parts) < 4:
            lines.append(line)
            continue
        members = [m for m in parts[3].split(",") if m and m not in drop]
        parts[3] = ",".join(members)
        lines.append(":".join(parts))
    with open(group_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + ("\n" if lines else ""))
    for home in homes:
        if home.startswith("/home/") and home.count("/") == 2:
            shutil.rmtree(os.path.join(root, home.lstrip("/")), ignore_errors=True)
    if log:
        log.write("deleted live users: " + ", ".join(sorted(drop)))


def shadow_lastchg_days() -> int:
    """Days since 1970-01-01 for /etc/shadow lastchg. 0 expires the password."""
    return max(1, int(time.time()) // 86400)


def add_user(root: str, identity: OsIdentity, log: InstallLog | None = None) -> None:
    passwd = os.path.join(root, "etc", "passwd")
    shadow = os.path.join(root, "etc", "shadow")
    used = set()
    for line in read_text(passwd).splitlines():
        parts = line.split(":")
        if len(parts) >= 3 and parts[2].isdigit():
            used.add(int(parts[2]))
    uid = 1000
    while uid in used:
        uid += 1
    groups = _group_ids(root)
    gid = int(groups.get("users") or groups.get(identity.username) or uid)
    extra = [name for name in USER_GROUPS if name in groups]
    gecos = identity.realname.replace(":", " ").replace("\n", " ").strip() or identity.username
    home = f"/home/{identity.username}"
    _rewrite_table(
        passwd,
        {identity.username},
        f"{identity.username}:x:{uid}:{gid}:{gecos}:{home}:/bin/bash",
    )
    _rewrite_table(
        shadow,
        {identity.username},
        f"{identity.username}:{identity.password_hash}:{shadow_lastchg_days()}:0:99999:7:::",
    )
    group_path = os.path.join(root, "etc", "group")
    lines = read_text(group_path).splitlines()
    have_user_group = False
    out: list[str] = []
    extra_set = set(extra)
    for line in lines:
        parts = line.split(":")
        if len(parts) < 4:
            out.append(line)
            continue
        name = parts[0]
        if name == identity.username:
            have_user_group = True
        members = [m for m in parts[3].split(",") if m]
        if name in extra_set and identity.username not in members:
            members.append(identity.username)
        parts[3] = ",".join(members)
        out.append(":".join(parts))
    if not have_user_group:
        out.append(f"{identity.username}:x:{gid}:")
    with open(group_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(out) + "\n")
    dest_home = os.path.join(root, home.lstrip("/"))
    skel = os.path.join(root, "etc", "skel")
    if not os.path.isdir(dest_home):
        if os.path.isdir(skel):
            shutil.copytree(skel, dest_home, dirs_exist_ok=True)
        else:
            os.makedirs(dest_home, exist_ok=True)
    try:
        os.chown(dest_home, uid, gid)
        for dirpath, dirnames, filenames in os.walk(dest_home):
            for name in dirnames + filenames:
                os.lchown(os.path.join(dirpath, name), uid, gid)
    except OSError:
        pass
    if log:
        log.write(f"added user {identity.username} uid={uid}")


def set_graphical_target(root: str, display_manager: str, log: InstallLog | None = None) -> None:
    systemd = os.path.join(root, "etc", "systemd", "system")
    os.makedirs(systemd, exist_ok=True)
    graphical = "../graphical.target"
    for cand in (
        os.path.join(root, "usr", "lib", "systemd", "system", "graphical.target"),
        os.path.join(root, "lib", "systemd", "system", "graphical.target"),
    ):
        if os.path.isfile(cand):
            graphical = os.path.relpath(cand, systemd)
            break
    dest = os.path.join(systemd, "default.target")
    try:
        if os.path.islink(dest) or os.path.exists(dest):
            os.unlink(dest)
    except OSError:
        pass
    os.symlink(graphical, dest)
    units = dm_unit_names(display_manager)
    chosen = ""
    for unit in units:
        if unit_exists(root, unit) and not unit_is_masked(root, unit):
            chosen = unit
            break
    if not chosen and units:
        chosen = units[0]
    if chosen:
        dm_link = os.path.join(systemd, "display-manager.service")
        try:
            if os.path.islink(dm_link) or os.path.exists(dm_link):
                os.unlink(dm_link)
        except OSError:
            pass
        os.symlink(chosen, dm_link)
        wants = os.path.join(systemd, "graphical.target.wants")
        os.makedirs(wants, exist_ok=True)
        want_link = os.path.join(wants, chosen)
        if not os.path.exists(want_link):
            try:
                os.symlink(os.path.join("/usr/lib/systemd/system", chosen), want_link)
            except OSError:
                pass
        for unit in units:
            masked = os.path.join(systemd, unit)
            try:
                if os.path.islink(masked) and os.path.realpath(masked) == "/dev/null":
                    os.unlink(masked)
            except OSError:
                pass
    if log:
        log.write(f"graphical.target display-manager={chosen or display_manager}")


def write_grub_default(root: str) -> None:
    path = os.path.join(root, "etc", "default", "grub")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    existing = read_text(path)
    lines = existing.splitlines() if existing else []
    wanted = {
        "GRUB_CMDLINE_LINUX_DEFAULT": '"quiet splash"',
        "GRUB_CMDLINE_LINUX": '""',
        "GRUB_TIMEOUT": "5",
    }
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        key = line.split("=", 1)[0].strip()
        if key in wanted:
            out.append(f"{key}={wanted[key]}")
            seen.add(key)
        else:
            out.append(line)
    for key, value in wanted.items():
        if key not in seen:
            out.append(f"{key}={value}")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(out).rstrip() + "\n")


def new_machine_id(root: str) -> None:
    etc_id = os.path.join(root, "etc", "machine-id")
    dbus_id = os.path.join(root, "var", "lib", "dbus", "machine-id")
    for path in (etc_id, dbus_id):
        try:
            if os.path.islink(path) or os.path.isfile(path):
                os.unlink(path)
        except OSError:
            pass
    ident = os.urandom(16).hex()
    os.makedirs(os.path.dirname(etc_id), exist_ok=True)
    with open(etc_id, "w", encoding="ascii") as fh:
        fh.write(ident + "\n")
    os.makedirs(os.path.dirname(dbus_id), exist_ok=True)
    try:
        os.symlink("/etc/machine-id", dbus_id)
    except OSError:
        with open(dbus_id, "w", encoding="ascii") as fh:
            fh.write(ident + "\n")


def mount_iso(iso_path: str) -> str:
    iso_mnt = tempfile.mkdtemp(prefix="fbl-iso-")
    run_checked(["mount", "-o", "loop,ro", iso_path, iso_mnt], what="mount the image")
    return iso_mnt


def umount_path(path: str) -> None:
    subprocess.run(["umount", path], check=False, capture_output=True)
    if os.path.ismount(path):
        subprocess.run(["umount", "-l", path], check=False, capture_output=True)


def bind_chroot(root: str) -> list[str]:
    mounted: list[str] = []
    pairs = (
        ("/dev", "dev", True),
        ("/proc", "proc", False),
        ("/sys", "sys", True),
        ("/run", "run", True),
    )
    for src, rel, rbind in pairs:
        dest = os.path.join(root, rel)
        os.makedirs(dest, exist_ok=True)
        cmd = ["mount", "--rbind" if rbind else "--bind", src, dest]
        proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
        if proc.returncode == 0:
            mounted.append(dest)
            if rbind:
                subprocess.run(
                    ["mount", "--make-rslave", dest],
                    check=False,
                    capture_output=True,
                )
    efi_src = "/sys/firmware/efi/efivars"
    efi_dst = os.path.join(root, "sys", "firmware", "efi", "efivars")
    if os.path.isdir(efi_src):
        os.makedirs(efi_dst, exist_ok=True)
        proc = subprocess.run(
            ["mount", "-t", "efivarfs", "efivarfs", efi_dst],
            check=False,
            capture_output=True,
        )
        if proc.returncode == 0:
            mounted.append(efi_dst)
    return mounted


def unbind_chroot(mounted: list[str]) -> None:
    for dest in reversed(mounted):
        subprocess.run(["umount", "-l", dest], check=False, capture_output=True)


def chroot_run(
    root: str, argv: list[str], *, log: InstallLog | None = None, timeout: int = 600
) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            ["chroot", root, *argv],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        if log:
            log.write(f"$ chroot {' '.join(argv)} -> timeout")
        return 1, "timeout"
    out = ((proc.stdout or "") + (proc.stderr or "")).strip()
    if log:
        log.write(f"$ chroot {' '.join(argv)} -> {proc.returncode}")
        if out:
            log.write(out[-4000:])
    return proc.returncode, out


def copy_file_progress(
    src: str,
    dest: str,
    *,
    on_progress: Callable[[int], None] | None = None,
    log: InstallLog | None = None,
) -> None:
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    total = os.path.getsize(src)
    n = 0
    with open(src, "rb") as infh, open(dest, "wb") as outfh:
        while True:
            chunk = infh.read(1024 * 1024)
            if not chunk:
                break
            outfh.write(chunk)
            n += len(chunk)
            if on_progress and total:
                on_progress(min(100, n * 100 // total))
    shutil.copystat(src, dest, follow_symlinks=True)
    if log:
        log.write(f"copied {src} -> {dest} ({n} bytes)")


# linux/loop.h LOOP_CHANGE_FD — switch backing file of a bound RO loop.
LOOP_CHANGE_FD = 0x4C06


def disk_busy_error() -> OsInstallError:
    return OsInstallError(
        _("This computer could not stop using the disk. Restart and try again.")
    )


def disk_holder_nums(disk_path: str) -> set[tuple[int, int]]:
    """Major/minor of the disk and its partitions."""
    nums: set[tuple[int, int]] = set()
    try:
        st = os.stat(disk_path)
        nums.add((os.major(st.st_rdev), os.minor(st.st_rdev)))
    except OSError:
        return nums
    base = os.path.basename(disk_path)
    sysdir = os.path.join("/sys/block", base)
    try:
        for name in os.listdir(sysdir):
            if not name.startswith(base):
                continue
            try:
                pst = os.stat(os.path.join("/dev", name))
            except OSError:
                continue
            nums.add((os.major(pst.st_rdev), os.minor(pst.st_rdev)))
    except OSError:
        pass
    return nums


def list_loop_devices() -> list[tuple[str, tuple[int, int], str]]:
    """Return (name, backing maj:min, backing file) for bound loop devices."""
    proc = subprocess.run(
        ["losetup", "-l", "-n", "-O", "NAME,BACK-MAJ:MIN,BACK-FILE"],
        check=False,
        capture_output=True,
        text=True,
    )
    out: list[tuple[str, tuple[int, int], str]] = []
    for line in (proc.stdout or "").splitlines():
        parts = line.split()
        if len(parts) < 2 or ":" not in parts[1]:
            continue
        name, majmin = parts[0], parts[1]
        back = " ".join(parts[2:]) if len(parts) > 2 else ""
        try:
            maj_s, min_s = majmin.split(":", 1)
            pair = (int(maj_s), int(min_s))
        except ValueError:
            continue
        out.append((name, pair, back))
    return out


def is_casper_loop(loopdev: str, back_file: str, live_squashfs: str) -> bool:
    """True if this loop is the live casper squashfs (not an ISO)."""
    base = os.path.basename(back_file.rstrip("/"))
    if base == "filesystem.squashfs":
        return True
    if "/casper/" in back_file.replace("\\", "/"):
        return True
    if not live_squashfs:
        return False
    try:
        live_size = os.path.getsize(live_squashfs)
    except OSError:
        return False
    sys_size = os.path.join("/sys/block", os.path.basename(loopdev), "size")
    try:
        with open(sys_size, encoding="ascii") as fh:
            sectors = int(fh.read().strip() or "0")
    except (OSError, ValueError):
        return False
    return sectors * 512 == live_size


def casper_loops_on_disk(disk_path: str, live_squashfs: str = "") -> list[str]:
    nums = disk_holder_nums(disk_path)
    live = live_squashfs or os.path.join(RAM_DIR, "live.squashfs")
    return [
        name
        for name, pair, back in list_loop_devices()
        if pair in nums and is_casper_loop(name, back, live)
    ]


def loop_change_fd(loopdev: str, new_path: str) -> None:
    """Point a bound read-only loop at a same-size backing file."""
    try:
        lfd = os.open(loopdev, os.O_RDWR)
    except OSError:
        lfd = os.open(loopdev, os.O_RDONLY)
    try:
        nfd = os.open(new_path, os.O_RDONLY)
        try:
            fcntl.ioctl(lfd, LOOP_CHANGE_FD, nfd)
        finally:
            os.close(nfd)
    finally:
        os.close(lfd)


def retarget_casper_loops(
    disk_path: str, live_squashfs: str, log: InstallLog | None = None
) -> None:
    """Switch casper loop backing to the RAM squashfs copy.

    pivot_root does not retarget existing mmap fds. losetup -d is a no-op
    while those fds remain. LOOP_CHANGE_FD keeps the device readable after
    the disk is wiped.
    """
    if not os.path.isfile(live_squashfs):
        raise OsInstallError(
            _(
                "Could not copy First Boot into memory. Plug in a First Boot USB and try again."
            )
        )
    nums = disk_holder_nums(disk_path)
    for name, pair, back in list_loop_devices():
        if pair not in nums:
            continue
        if not is_casper_loop(name, back, live_squashfs):
            continue
        try:
            loop_change_fd(name, live_squashfs)
        except OSError as exc:
            if log:
                log.write(f"LOOP_CHANGE_FD {name} -> {live_squashfs} failed: {exc}")
            raise disk_busy_error() from exc
        if log:
            log.write(f"retarget {name} -> {live_squashfs}")
    leftover = casper_loops_on_disk(disk_path, live_squashfs)
    if leftover:
        if log:
            log.write("casper loop still on disk: " + " ".join(leftover))
        raise disk_busy_error()


def detach_loops_on_disk(disk_path: str, log: InstallLog | None = None) -> None:
    """Detach loop devices whose backing file lives on the target disk.

    Keep loops already retargeted onto the RAM tmpfs (live.squashfs).
    """
    nums = disk_holder_nums(disk_path)
    if not nums:
        return
    for name, pair, _back in list_loop_devices():
        if pair not in nums:
            continue
        proc = subprocess.run(
            ["losetup", "-d", name],
            check=False,
            capture_output=True,
            text=True,
        )
        if log:
            majmin = f"{pair[0]}:{pair[1]}"
            if proc.returncode != 0:
                tail = (proc.stderr or proc.stdout or "").strip().splitlines()
                log.write(
                    f"detach {name} failed"
                    + (f" ({tail[-1]})" if tail else "")
                )
            else:
                log.write(f"detach {name} ({majmin} on {disk_path})")


def partition_disk(disk_path: str, work: str, log: InstallLog | None = None) -> InstalledDisk:
    leftover = casper_loops_on_disk(disk_path)
    if leftover:
        if log:
            log.write("casper loop still on disk: " + " ".join(leftover))
        raise disk_busy_error()
    subprocess.run(["swapoff", "-a"], check=False, capture_output=True)
    if log:
        log.write(f"wipe {disk_path}")
    run_checked(["wipefs", "-a", "-f", disk_path], what=f"wipe {disk_path}")
    run_checked(["sgdisk", "--zap-all", disk_path], what="clear GPT")
    esp_mib = ESP_MIB_DEFAULT
    run_checked(
        [
            "sgdisk",
            f"--new=1:1M:+{esp_mib}M",
            "--typecode=1:EF00",
            "--change-name=1:EFI",
            "--new=2:0:0",
            "--typecode=2:8300",
            "--change-name=2:root",
            disk_path,
        ],
        what="create partitions",
    )
    subprocess.run(["partprobe", disk_path], check=False, capture_output=True)
    subprocess.run(["udevadm", "settle"], check=False, capture_output=True)
    detach_loops_on_disk(disk_path, log=log)
    esp_dev = part_path(disk_path, 1)
    root_dev = part_path(disk_path, 2)
    wait_dev(esp_dev)
    wait_dev(root_dev)
    run_checked(["mkfs.vfat", "-F", "32", "-n", "EFI", esp_dev], what="format ESP")
    run_checked(
        [
            "mkfs.ext4",
            "-F",
            "-q",
            "-L",
            "root",
            "-m",
            "0",
            "-O",
            EXT4_GRUB_OPTS,
            root_dev,
        ],
        what="format root",
    )
    esp_mp = os.path.join(work, "esp")
    root_mp = os.path.join(work, "root")
    os.makedirs(esp_mp, exist_ok=True)
    os.makedirs(root_mp, exist_ok=True)
    run_checked(["mount", root_dev, root_mp], what="mount root")
    os.makedirs(os.path.join(root_mp, "boot", "efi"), exist_ok=True)
    run_checked(["mount", esp_dev, os.path.join(root_mp, "boot", "efi")], what="mount ESP")
    efi_mp = os.path.join(root_mp, "boot", "efi")
    if log:
        log.write(f"partitioned {disk_path} esp={esp_dev} root={root_dev}")
    return InstalledDisk(
        disk=disk_path,
        esp_dev=esp_dev,
        root_dev=root_dev,
        esp_uuid=blkid_uuid(esp_dev),
        root_uuid=blkid_uuid(root_dev),
        esp_mp=efi_mp,
        root_mp=root_mp,
    )


def register_os_efi(disk: InstalledDisk, label: str, loader: str, log: InstallLog | None = None) -> None:
    if not shutil.which("efibootmgr"):
        if log:
            log.write("efibootmgr missing; skip NVRAM")
        return
    from firstboot.install import STALE_EFI_LABELS

    proc = subprocess.run(
        ["efibootmgr", "-v"], check=False, capture_output=True, text=True
    )
    text = proc.stdout or ""
    from firstboot.install import efi_ids_for_unshimmed_loaders

    labels = list(STALE_EFI_LABELS) + [label]
    seen: set[str] = set()
    drop = []
    for name in labels:
        drop.extend(efi_ids_for_label(text, name))
    drop.extend(efi_ids_for_unshimmed_loaders(text))
    for bootnum in drop:
        if bootnum in seen:
            continue
        seen.add(bootnum)
        subprocess.run(
            ["efibootmgr", "--bootnum", bootnum, "--delete-bootnum"],
            check=False,
            capture_output=True,
            text=True,
        )
    partnum = "1"
    base = os.path.basename(disk.esp_dev)
    if "p" in base and base.rsplit("p", 1)[-1].isdigit():
        partnum = base.rsplit("p", 1)[-1]
    else:
        i = len(base)
        while i and base[i - 1].isdigit():
            i -= 1
        if i < len(base):
            partnum = base[i:]
    proc = subprocess.run(
        [
            "efibootmgr",
            "--create",
            "--disk",
            disk.disk,
            "--part",
            partnum,
            "--label",
            label,
            "--loader",
            loader,
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()
        if log:
            log.write(
                "efibootmgr --create failed"
                + (f" ({tail[-1]})" if tail else f" rc={proc.returncode}")
            )
        raise OsInstallError(_("Could not write the boot partition."))
    listed = proc.stdout or ""
    created = efi_ids_for_label(listed, label)
    if not created:
        listed = subprocess.run(
            ["efibootmgr"], check=False, capture_output=True, text=True
        ).stdout or ""
        created = efi_ids_for_label(listed, label)
    if created:
        subprocess.run(
            ["efibootmgr", "--bootnext", created[-1]],
            check=False,
            capture_output=True,
            text=True,
        )
    elif log:
        log.write(f"efibootmgr created {label} but the entry was not listed")
    if log:
        log.write(f"efibootmgr {label} {loader}")


def efi_loader_path(efi_mp: str, bootloader_id: str) -> str:
    shim = os.path.join(efi_mp, "EFI", bootloader_id, "shimx64.efi")
    if os.path.isfile(shim):
        return rf"\EFI\{bootloader_id}\shimx64.efi"
    vendor_grub = os.path.join(efi_mp, "EFI", bootloader_id, "grubx64.efi")
    if os.path.isfile(vendor_grub):
        return rf"\EFI\{bootloader_id}\grubx64.efi"
    return r"\EFI\BOOT\BOOTX64.EFI"

