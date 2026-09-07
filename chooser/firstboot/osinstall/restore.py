"""Rewrite First Boot onto the disk after a failed customer install.

The customer has no USB. After step 3 the target is already wiped, so a
failed health check would brick the machine on reboot. Restore writes a
minimal First Boot (seed + shop files, no distro ISOs) from the RAM copy
taken before the wipe, or from a still-mounted live medium.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable

from firstboot.disk import (
    ESP_MIB_DEFAULT,
    LIVE_MOUNTS,
    PAYLOAD_MOUNT,
    SYS_MIB_DEFAULT,
    emit,
    live_lsblk,
    part_path,
)
from firstboot.i18n import _
from firstboot.install import (
    EXT4_GRUB_OPTS,
    _register_efi,
    blkid_uuid,
    rewrite_grub,
    run_checked,
    wait_dev,
)
from firstboot.osinstall.common import (
    RAM_DIR,
    InstallLog,
    OsInstallError,
    copy_file_progress,
    umount_path,
)

RESCUE_DIR = os.path.join(RAM_DIR, "rescue")
RESCUE_SQUASH = os.path.join(RAM_DIR, "live.squashfs")
SIGNED_EFI_DIR = "/usr/share/firstboot/signed-efi"
GCDX64 = "/usr/lib/grub/x86_64-efi-signed/gcdx64.efi.signed"

TICK_DISK = "Preparing the disk"
TICK_SYS = "Copying First Boot…"
TICK_DATA = "Copying shop files"
TICK_BOOT = "Installing the bootloader"

RESTORE_TICKS = (TICK_DISK, TICK_SYS, TICK_DATA, TICK_BOOT)

PAYLOAD_SKIP = frozenset({"images", "lost+found"})


def emit_restore_ticks() -> None:
    emit("TICKS", "|".join(_(label) for label in RESTORE_TICKS))


def emit_tick(index: int, status: str, *, step: bool = False) -> None:
    emit("TICK", index, status)
    if step and 1 <= index <= len(RESTORE_TICKS):
        emit("STEP", _(RESTORE_TICKS[index - 1]))


def _copy_file(src: str, dest: str) -> None:
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    shutil.copy2(src, dest)


def live_casper_dir() -> str:
    for mp in LIVE_MOUNTS:
        folder = os.path.join(mp, "casper")
        if os.path.isdir(folder):
            return folder
    rescue = os.path.join(RESCUE_DIR, "casper")
    if os.path.isdir(rescue):
        return rescue
    return ""


def find_live_squashfs() -> str:
    if os.path.isfile(RESCUE_SQUASH):
        return RESCUE_SQUASH
    dest = os.path.join(RESCUE_DIR, "filesystem.squashfs")
    if os.path.isfile(dest):
        return dest
    for mp in LIVE_MOUNTS:
        for rel in (
            os.path.join("casper", "filesystem.squashfs"),
            os.path.join("live", "filesystem.squashfs"),
        ):
            path = os.path.join(mp, rel)
            if os.path.isfile(path):
                return path
    return ""


def find_casper_kernel() -> tuple[str, str]:
    vmlinuz = os.path.join(RESCUE_DIR, "casper", "vmlinuz")
    initrd = os.path.join(RESCUE_DIR, "casper", "initrd")
    if os.path.isfile(vmlinuz) and os.path.isfile(initrd):
        return vmlinuz, initrd
    folder = live_casper_dir()
    if not folder:
        return "", ""
    vmlinuz = os.path.join(folder, "vmlinuz")
    for name in ("initrd", "initrd.lz", "initrd.gz"):
        initrd = os.path.join(folder, name)
        if os.path.isfile(vmlinuz) and os.path.isfile(initrd):
            return vmlinuz, initrd
    return "", ""


def rescue_ready() -> bool:
    squash = find_live_squashfs()
    vmlinuz, initrd = find_casper_kernel()
    return bool(squash and vmlinuz and initrd)


def snapshot_rescue(
    payload_root: str | None = None, log: InstallLog | None = None
) -> None:
    """Keep the files a same-disk restore needs after FBL-DATA is gone."""
    os.makedirs(os.path.join(RESCUE_DIR, "casper"), exist_ok=True)
    folder = ""
    for mp in LIVE_MOUNTS:
        cand = os.path.join(mp, "casper")
        if os.path.isdir(cand):
            folder = cand
            break
    if folder:
        for name in ("vmlinuz", "initrd", "initrd.lz", "initrd.gz", "filesystem.size"):
            src = os.path.join(folder, name)
            if not os.path.isfile(src):
                continue
            dest_name = "initrd" if name.startswith("initrd") else name
            dest = os.path.join(RESCUE_DIR, "casper", dest_name)
            if dest_name == "initrd" and os.path.isfile(
                os.path.join(RESCUE_DIR, "casper", "initrd")
            ):
                continue
            _copy_file(src, dest)
        hash_src = os.path.join(os.path.dirname(folder), "firstboot", "live-user.hash")
        if os.path.isfile(hash_src):
            dest = os.path.join(RESCUE_DIR, "live-user.hash")
            _copy_file(hash_src, dest)
    root = payload_root or PAYLOAD_MOUNT
    if os.path.isdir(root):
        dest = os.path.join(RESCUE_DIR, "payload")
        os.makedirs(dest, exist_ok=True)
        try:
            names = os.listdir(root)
        except OSError:
            names = []
        for name in names:
            if name in PAYLOAD_SKIP or name.startswith("."):
                continue
            src = os.path.join(root, name)
            out = os.path.join(dest, name)
            try:
                if os.path.isdir(src):
                    shutil.copytree(src, out, dirs_exist_ok=True)
                elif os.path.isfile(src):
                    shutil.copy2(src, out)
            except OSError:
                continue
    if log:
        log.write("snapshotted First Boot rescue files")


def _seed_version() -> str:
    path = "/etc/os-release"
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("VERSION_ID="):
                    return line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return "seed"


def _gcdx64() -> str:
    if os.path.isfile(GCDX64):
        return GCDX64
    grub = os.path.join(SIGNED_EFI_DIR, "grubx64.efi")
    return grub if os.path.isfile(grub) else ""


def _shim() -> tuple[str, str]:
    shim = os.path.join(SIGNED_EFI_DIR, "shimx64.efi")
    mm = os.path.join(SIGNED_EFI_DIR, "mmx64.efi")
    if os.path.isfile(shim):
        return shim, mm if os.path.isfile(mm) else ""
    shim2 = "/usr/lib/shim/shimx64.efi.signed"
    mm2 = "/usr/lib/shim/mmx64.efi"
    if os.path.isfile(shim2):
        return shim2, mm2 if os.path.isfile(mm2) else ""
    return "", ""


def write_fbl_esp(efi_mp: str, log: InstallLog | None = None) -> None:
    """Shim in EFI/BOOT plus gcdx64 so removable/NVRAM shim can load GRUB."""
    shim, mm = _shim()
    grub = _gcdx64()
    if not shim or not grub:
        raise OsInstallError(_("Could not write the boot partition."))
    boot = os.path.join(efi_mp, "EFI", "BOOT")
    vendor = os.path.join(efi_mp, "EFI", "firstboot")
    os.makedirs(boot, exist_ok=True)
    os.makedirs(vendor, exist_ok=True)
    shutil.copy2(shim, os.path.join(boot, "BOOTX64.EFI"))
    shutil.copy2(grub, os.path.join(boot, "grubx64.efi"))
    shutil.copy2(shim, os.path.join(vendor, "shimx64.efi"))
    shutil.copy2(grub, os.path.join(vendor, "grubx64.efi"))
    if mm:
        shutil.copy2(mm, os.path.join(vendor, "mmx64.efi"))
    if log:
        log.write("wrote First Boot ESP (shim + gcdx64)")


def write_fbl_sys(
    sys_mnt: str,
    sys_uuid: str,
    *,
    on_progress: Callable[[int], None] | None = None,
    log: InstallLog | None = None,
) -> None:
    squash = find_live_squashfs()
    vmlinuz, initrd = find_casper_kernel()
    if not squash or not vmlinuz or not initrd:
        raise OsInstallError(_("Could not restore First Boot Linux."))
    casper = os.path.join(sys_mnt, "casper")
    disk = os.path.join(sys_mnt, ".disk")
    grub = os.path.join(sys_mnt, "boot", "grub")
    os.makedirs(casper, exist_ok=True)
    os.makedirs(disk, exist_ok=True)
    os.makedirs(grub, exist_ok=True)
    version = _seed_version()
    with open(os.path.join(disk, "info"), "w", encoding="utf-8") as fh:
        fh.write(f"First Boot Linux {version}\n")
    with open(os.path.join(disk, "ubuntu_dist_channel"), "w", encoding="utf-8") as fh:
        fh.write("firstboot\n")
    copy_file_progress(
        vmlinuz, os.path.join(casper, "vmlinuz"), log=log
    )
    copy_file_progress(
        initrd, os.path.join(casper, "initrd"), log=log
    )
    copy_file_progress(
        squash,
        os.path.join(casper, "filesystem.squashfs"),
        on_progress=on_progress,
        log=log,
    )
    size_src = os.path.join(RESCUE_DIR, "casper", "filesystem.size")
    if os.path.isfile(size_src):
        _copy_file(size_src, os.path.join(casper, "filesystem.size"))
    hash_src = os.path.join(RESCUE_DIR, "live-user.hash")
    if os.path.isfile(hash_src):
        dest = os.path.join(sys_mnt, "firstboot", "live-user.hash")
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        _copy_file(hash_src, dest)
        try:
            os.chmod(dest, 0o600)
        except OSError:
            pass
    # rewrite_grub wants the sys tree for boot/grub/grub.cfg.
    grub_cfg = os.path.join(sys_mnt, "boot", "grub", "grub.cfg")
    os.makedirs(os.path.dirname(grub_cfg), exist_ok=True)
    from firstboot.install import SYS_GRUB

    with open(grub_cfg, "w", encoding="utf-8") as fh:
        fh.write(SYS_GRUB.format(uuid=sys_uuid))


def write_fbl_data(data_mnt: str, log: InstallLog | None = None) -> None:
    os.makedirs(os.path.join(data_mnt, "images"), exist_ok=True)
    os.makedirs(os.path.join(data_mnt, "wallpapers"), exist_ok=True)
    src = os.path.join(RESCUE_DIR, "payload")
    if not os.path.isdir(src) and os.path.isdir(PAYLOAD_MOUNT):
        src = PAYLOAD_MOUNT
    if not os.path.isdir(src):
        if log:
            log.write("no shop payload to restore")
        return
    try:
        names = os.listdir(src)
    except OSError:
        names = []
    for name in names:
        if name in PAYLOAD_SKIP or name.startswith("."):
            continue
        from_path = os.path.join(src, name)
        dest = os.path.join(data_mnt, name)
        try:
            if os.path.isdir(from_path):
                shutil.copytree(from_path, dest, dirs_exist_ok=True)
            elif os.path.isfile(from_path):
                shutil.copy2(from_path, dest)
        except OSError as exc:
            if log:
                log.write(f"payload {name}: {exc}")
    if log:
        log.write(f"restored shop files from {src}")


def _unmount_target_disk(disk_path: str, log: InstallLog | None = None) -> None:
    from firstboot.disk import disk_for_device
    from firstboot.install import collected_mounts, unmount_error

    disks = live_lsblk()
    disk = disk_for_device(disks, disk_path)
    if disk is not None:
        for mp in collected_mounts(disk, extra=[PAYLOAD_MOUNT]):
            if mp in ("/", "/run"):
                continue
            err = unmount_error(mp, disk_path)
            if err and mp in ("/",):
                continue
            subprocess.run(["umount", "-R", mp], check=False, capture_output=True)
            subprocess.run(["umount", "-l", mp], check=False, capture_output=True)
    work = os.path.join(RAM_DIR, "mnt")
    if os.path.isdir(work):
        for dirpath, dirnames, _files in os.walk(work, topdown=False):
            if os.path.ismount(dirpath):
                umount_path(dirpath)
        for name in ("root", "esp", "boot", "btrfs"):
            umount_path(os.path.join(work, name))
    subprocess.run(["udevadm", "settle"], check=False, capture_output=True)
    if log:
        log.write(f"unmounted leftover target mounts on {disk_path}")


def restore_fbl(
    disk_path: str,
    *,
    on_progress: Callable[[int], None] | None = None,
    log: InstallLog | None = None,
) -> None:
    """Recreate FBL-ESP + FBL-SYS + FBL-DATA and copy the live seed back."""
    if os.geteuid() != 0:
        raise OsInstallError("must run as root")
    if not disk_path or not os.path.exists(disk_path):
        raise OsInstallError(_("Could not restore First Boot Linux."))
    if not rescue_ready():
        raise OsInstallError(_("Could not restore First Boot Linux."))

    def prog(n: int) -> None:
        n = max(0, min(100, int(n)))
        if on_progress:
            on_progress(n)
        else:
            emit("PROGRESS", n)

    own_log = log is None
    if log is None:
        log = InstallLog()
    try:
        emit_restore_ticks()
        emit_tick(1, "current", step=True)
        prog(4)
        _unmount_target_disk(disk_path, log=log)
        subprocess.run(["swapoff", "-a"], check=False, capture_output=True)
        run_checked(["wipefs", "-a", "-f", disk_path], what=f"wipe {disk_path}")
        run_checked(["sgdisk", "--zap-all", disk_path], what="clear GPT")
        run_checked(
            [
                "sgdisk",
                f"--new=1:1M:+{ESP_MIB_DEFAULT}M",
                "--typecode=1:EF00",
                "--change-name=1:FBL-ESP",
                f"--new=2:0:+{SYS_MIB_DEFAULT}M",
                "--typecode=2:8300",
                "--change-name=2:FBL-SYS",
                "--new=3:0:0",
                "--typecode=3:8300",
                "--change-name=3:FBL-DATA",
                disk_path,
            ],
            what="create First Boot partitions",
        )
        subprocess.run(["partprobe", disk_path], check=False, capture_output=True)
        subprocess.run(["udevadm", "settle"], check=False, capture_output=True)
        esp_dev = part_path(disk_path, 1)
        sys_dev = part_path(disk_path, 2)
        data_dev = part_path(disk_path, 3)
        wait_dev(esp_dev)
        wait_dev(sys_dev)
        wait_dev(data_dev)
        run_checked(
            ["mkfs.vfat", "-F", "32", "-n", "FBL-ESP", esp_dev], what="format ESP"
        )
        run_checked(
            [
                "mkfs.ext4",
                "-F",
                "-q",
                "-L",
                "FBL-SYS",
                "-m",
                "0",
                "-O",
                EXT4_GRUB_OPTS,
                sys_dev,
            ],
            what="format FBL-SYS",
        )
        run_checked(
            ["mkfs.ext4", "-F", "-q", "-L", "FBL-DATA", "-m", "0", data_dev],
            what="format FBL-DATA",
        )
        emit_tick(1, "done")
        prog(16)

        work = os.path.join(RAM_DIR, "restore")
        os.makedirs(work, exist_ok=True)
        esp_mp = os.path.join(work, "esp")
        sys_mp = os.path.join(work, "sys")
        data_mp = os.path.join(work, "data")
        os.makedirs(esp_mp, exist_ok=True)
        os.makedirs(sys_mp, exist_ok=True)
        os.makedirs(data_mp, exist_ok=True)
        run_checked(["mount", esp_dev, esp_mp], what="mount ESP")
        run_checked(["mount", sys_dev, sys_mp], what="mount FBL-SYS")
        run_checked(["mount", data_dev, data_mp], what="mount FBL-DATA")
        try:
            sys_uuid = blkid_uuid(sys_dev)
            emit_tick(2, "current", step=True)
            write_fbl_sys(
                sys_mp,
                sys_uuid,
                on_progress=lambda p: prog(16 + p * 50 // 100),
                log=log,
            )
            emit_tick(2, "done")
            prog(70)
            emit_tick(3, "current", step=True)
            write_fbl_data(data_mp, log=log)
            emit_tick(3, "done")
            prog(86)
            emit_tick(4, "current", step=True)
            write_fbl_esp(esp_mp, log=log)
            rewrite_grub(esp_mp, sys_mp, sys_uuid)
            os.sync()
            _register_efi(disk_path)
            emit_tick(4, "done")
            prog(100)
            emit("STEP", _("Complete"))
            emit("DONE")
        finally:
            for mp in (data_mp, sys_mp, esp_mp):
                umount_path(mp)
            shutil.rmtree(work, ignore_errors=True)
    finally:
        if own_log:
            log.close()
