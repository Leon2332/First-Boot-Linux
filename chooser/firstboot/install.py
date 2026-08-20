"""Copy First Boot from the USB onto the internal disk."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable

from firstboot.disk import (
    ESP_MIB_DEFAULT,
    SLACK_BYTES,
    SYS_MIB_DEFAULT,
    Disk,
    InstallPlan,
    bytes_to_mib,
    emit,
    live_plan,
    map_range,
    parse_helper_line,
    part_path,
    plan_install,
    rsync_percent,
)

HELPER = "/usr/libexec/firstboot/install-disk"

# Recent mkfs.ext4 enables orphan_file / metadata_csum_seed. gcdx64 then
# cannot see FBL-SYS and drops to a grub> prompt (USB still boots because
# the creator formatted that ext4 on the shop PC, not in this live image).
EXT4_GRUB_OPTS = "^orphan_file,^metadata_csum_seed"

ESP_GRUB = """# First Boot ESP stub. Prefer this disk's FBL-SYS UUID; label if that misses.
search --no-floppy --set=root --fs-uuid {uuid}
if [ ! -f /boot/grub/grub.cfg ]; then
	search --no-floppy --set=root --label FBL-SYS
fi
set prefix=($root)/boot/grub
configfile $prefix/grub.cfg
"""

SYS_GRUB = """# First Boot live system — FBL-SYS /boot/grub/grub.cfg
set default=0
set timeout=2
set timeout_style=menu

search --no-floppy --set=root --fs-uuid {uuid}
if [ ! -f /casper/vmlinuz ]; then
	search --no-floppy --set=root --label FBL-SYS
fi

menuentry "First Boot Linux" {{
    linux /casper/vmlinuz boot=casper live-media=/dev/disk/by-uuid/{uuid} live-media-path=casper ignore_uuid nopersistent noprompt console=tty1 console=ttyS0,115200n8 ---
    initrd /casper/initrd
}}

menuentry "First Boot Linux (safe graphics)" {{
    linux /casper/vmlinuz boot=casper live-media=/dev/disk/by-uuid/{uuid} live-media-path=casper ignore_uuid nopersistent noprompt nomodeset console=tty1 console=ttyS0,115200n8 ---
    initrd /casper/initrd
}}
"""


class InstallError(Exception):
    """A shop-install failure the chooser can show."""


def helper_path() -> str:
    if os.path.isfile(HELPER) and os.access(HELPER, os.X_OK):
        return HELPER
    here = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "firstboot-install-disk"))
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
    raise InstallError("Cannot gain permission to write the disk.")


def apply_cmd(target: str) -> list[str]:
    return [*privilege_prefix(), helper_path(), "--apply", "--target", target]


def run_apply(
    target: str,
    on_event: Callable[..., None] | None = None,
) -> None:
    cmd = apply_cmd(target)
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
    except OSError as exc:
        raise InstallError(str(exc)) from exc
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
        raise InstallError(err)
    if status != 0:
        raise InstallError(f"Install failed ({status}).")


def rewrite_grub(esp_mnt: str, sys_mnt: str, sys_uuid: str) -> None:
    if not sys_uuid:
        raise InstallError("missing FBL-SYS UUID")
    cfg = ESP_GRUB.format(uuid=sys_uuid)
    for rel in (
        "EFI/BOOT/grub.cfg",
        "EFI/firstboot/grub.cfg",
        "EFI/ubuntu/grub.cfg",
    ):
        path = os.path.join(esp_mnt, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(cfg)
    sys_cfg = os.path.join(sys_mnt, "boot", "grub", "grub.cfg")
    os.makedirs(os.path.dirname(sys_cfg), exist_ok=True)
    with open(sys_cfg, "w", encoding="utf-8") as fh:
        fh.write(SYS_GRUB.format(uuid=sys_uuid))


def run_checked(cmd: list[str], *, what: str) -> None:
    try:
        proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
    except OSError as exc:
        raise InstallError(f"{what}: {exc}") from exc
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip().splitlines()
        tail = detail[-1] if detail else f"exit {proc.returncode}"
        raise InstallError(f"{what}: {tail}")


def blkid_uuid(dev: str) -> str:
    proc = subprocess.run(
        ["blkid", "-p", "-s", "UUID", "-o", "value", dev],
        check=False,
        capture_output=True,
        text=True,
    )
    uuid = (proc.stdout or "").strip().splitlines()
    uuid = uuid[-1].strip() if uuid else ""
    if not uuid:
        proc = subprocess.run(
            ["tune2fs", "-l", dev],
            check=False,
            capture_output=True,
            text=True,
        )
        for line in (proc.stdout or "").splitlines():
            if line.lower().startswith("filesystem uuid:"):
                uuid = line.split(":", 1)[1].strip()
                break
    if not uuid:
        raise InstallError(f"could not read UUID of {dev}")
    return uuid


def wait_dev(path: str, timeout: float = 20.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if os.path.exists(path):
            return
        time.sleep(0.1)
    raise InstallError(f"partition {path} did not appear")


# Live-session mounts we never drop. /run/payload is not in this set: a
# previous shop install leaves LABEL=FBL-DATA on the internal disk, and
# casper's fstab may bind that old partition at /run/payload (item 19).
# Reinstall has to unmount it before wipefs.
PROTECTED_MOUNTS = frozenset({"/", "/cdrom", "/run/live/medium"})
PAYLOAD_UNIT = "run-payload.mount"


def unmount_error(mp: str, disk_path: str) -> str | None:
    if mp in PROTECTED_MOUNTS:
        return f"refusing to unmount {mp} on {disk_path}"
    return None


def _mountpoints_of(dev: str) -> list[str]:
    proc = subprocess.run(
        ["findmnt", "-n", "-o", "TARGET", dev],
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return []
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def collected_mounts(disk: Disk, extra: list[str] | None = None) -> list[str]:
    mps: list[str] = []
    for part in disk.parts:
        mps.extend(part.mountpoints)
        mps.extend(_mountpoints_of(part.path))
    mps.extend(_mountpoints_of(disk.path))
    if extra:
        mps.extend(extra)
    seen: set[str] = set()
    uniq: list[str] = []
    for mp in mps:
        if not mp or mp in seen:
            continue
        seen.add(mp)
        uniq.append(mp)
    uniq.sort(key=len, reverse=True)
    return uniq


def _unmount(mp: str) -> None:
    if mp == "/run/payload":
        subprocess.run(
            ["systemctl", "stop", PAYLOAD_UNIT],
            check=False,
            capture_output=True,
        )
        subprocess.run(
            ["systemctl", "mask", "--runtime", PAYLOAD_UNIT],
            check=False,
            capture_output=True,
        )
    subprocess.run(["umount", "-R", mp], check=False, capture_output=True)
    if _mountpoints_of(mp) or os.path.ismount(mp):
        subprocess.run(["umount", "-l", mp], check=False, capture_output=True)


def unmount_disk(disk: Disk) -> None:
    for mp in collected_mounts(disk):
        err = unmount_error(mp, disk.path)
        if err:
            raise InstallError(err)
        _unmount(mp)


def _release_payload_unit() -> None:
    subprocess.run(
        ["systemctl", "unmask", "--runtime", PAYLOAD_UNIT],
        check=False,
        capture_output=True,
    )


def copy_tree(
    src: str,
    dst: str,
    *,
    fat: bool = False,
    on_percent: Callable[[int], None] | None = None,
) -> None:
    cmd = ["rsync", "-a", "--numeric-ids", "--info=progress2", "--exclude=lost+found"]
    if not fat:
        cmd.append("-H")
    cmd.extend([src.rstrip("/") + "/", dst.rstrip("/") + "/"])
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
    except OSError as exc:
        raise InstallError(f"copy: {exc}") from exc
    assert proc.stderr is not None
    for line in proc.stderr:
        pct = rsync_percent(line)
        if pct is not None and on_percent is not None:
            on_percent(pct)
    if proc.wait() != 0:
        raise InstallError("copy failed")


def _progress(n: int) -> None:
    emit("PROGRESS", max(0, min(100, int(n))))


def apply_plan(plan: InstallPlan) -> None:
    if not plan.available or plan.source is None or plan.target is None:
        raise InstallError(plan.reason or "No internal disk to install to.")
    if os.geteuid() != 0:
        raise InstallError("must run as root")
    source, target = plan.source, plan.target
    if source.path == target.path:
        raise InstallError("source and target are the same disk")
    if not os.path.exists(target.path):
        raise InstallError(f"{target.path} is missing")

    src_esp = source.part_named("FBL-ESP")
    src_sys = source.part_named("FBL-SYS")
    src_data = source.part_named("FBL-DATA")
    if src_esp is None or src_sys is None or src_data is None:
        raise InstallError("This USB does not look like a First Boot install drive.")

    emit("STEP", "Preparing the disk…")
    _progress(4)
    try:
        unmount_disk(target)
        _apply_formatted(plan, source, target)
    finally:
        _release_payload_unit()


def _apply_formatted(plan: InstallPlan, source: Disk, target: Disk) -> None:
    src_esp = source.part_named("FBL-ESP")
    src_sys = source.part_named("FBL-SYS")
    src_data = source.part_named("FBL-DATA")
    if src_esp is None or src_sys is None or src_data is None:
        raise InstallError("This USB does not look like a First Boot install drive.")
    run_checked(["wipefs", "-a", target.path], what=f"wipe {target.path}")
    run_checked(["sgdisk", "--zap-all", target.path], what="clear GPT")
    esp_mib = bytes_to_mib(plan.esp_bytes) if plan.esp_bytes else ESP_MIB_DEFAULT
    sys_mib = bytes_to_mib(plan.sys_bytes) if plan.sys_bytes else SYS_MIB_DEFAULT
    run_checked(
        [
            "sgdisk",
            f"--new=1:1M:+{esp_mib}M",
            "--typecode=1:EF00",
            "--change-name=1:FBL-ESP",
            f"--new=2:0:+{sys_mib}M",
            "--typecode=2:8300",
            "--change-name=2:FBL-SYS",
            "--new=3:0:0",
            "--typecode=3:8300",
            "--change-name=3:FBL-DATA",
            target.path,
        ],
        what="create partitions",
    )
    subprocess.run(["partprobe", target.path], check=False, capture_output=True)
    subprocess.run(["udevadm", "settle"], check=False, capture_output=True)
    dst_esp = part_path(target.path, 1)
    dst_sys = part_path(target.path, 2)
    dst_data = part_path(target.path, 3)
    for p in (dst_esp, dst_sys, dst_data):
        wait_dev(p)
    run_checked(["mkfs.vfat", "-F", "32", "-n", "FBL-ESP", dst_esp], what="format ESP")
    run_checked(
        ["mkfs.ext4", "-F", "-q", "-L", "FBL-SYS", "-m", "0", "-O", EXT4_GRUB_OPTS, dst_sys],
        what="format FBL-SYS",
    )
    run_checked(["mkfs.ext4", "-F", "-q", "-L", "FBL-DATA", "-m", "0", dst_data], what="format FBL-DATA")
    _progress(12)

    work = tempfile.mkdtemp(prefix="fbl-install-")
    mounts: list[str] = []
    try:
        def mount(dev: str, dest: str, opts: str = "") -> str:
            existing = _mountpoints_of(dev)
            if existing:
                return existing[0]
            os.makedirs(dest, exist_ok=True)
            cmd = ["mount"]
            if opts:
                cmd.extend(["-o", opts])
            cmd.extend([dev, dest])
            run_checked(cmd, what=f"mount {dev}")
            mounts.append(dest)
            return dest

        src_esp_mnt = mount(src_esp.path, os.path.join(work, "src-esp"), "ro")
        src_sys_mnt = mount(src_sys.path, os.path.join(work, "src-sys"), "ro")
        src_data_mnt = mount(src_data.path, os.path.join(work, "src-data"), "ro")
        dst_esp_mnt = mount(dst_esp, os.path.join(work, "dst-esp"))
        dst_sys_mnt = mount(dst_sys, os.path.join(work, "dst-sys"))
        dst_data_mnt = mount(dst_data, os.path.join(work, "dst-data"))

        emit("STEP", "Copying boot files…")
        _progress(13)

        def on_esp(pct: int) -> None:
            _progress(map_range(pct, 13, 34))

        copy_tree(src_esp_mnt, dst_esp_mnt, fat=True, on_percent=on_esp)
        _progress(34)

        emit("STEP", "Copying First Boot…")

        def on_sys(pct: int) -> None:
            _progress(map_range(pct, 35, 58))

        copy_tree(src_sys_mnt, dst_sys_mnt, on_percent=on_sys)
        _progress(58)

        emit("STEP", "Copying recommended systems…")

        def on_data(pct: int) -> None:
            _progress(map_range(pct, 59, 96))

        copy_tree(src_data_mnt, dst_data_mnt, on_percent=on_data)
        _progress(96)

        emit("STEP", "Finishing…")
        sys_uuid = blkid_uuid(dst_sys)
        rewrite_grub(dst_esp_mnt, dst_sys_mnt, sys_uuid)
        os.sync()
        _register_efi(target.path)
        _progress(100)
        emit("STEP", "Complete")
        emit("DONE")
    finally:
        for dest in reversed(mounts):
            subprocess.run(["umount", dest], check=False, capture_output=True)
        shutil.rmtree(work, ignore_errors=True)


EFI_LABEL = "First Boot Linux"
# Ghost NVRAM labels from OSes this disk used to hold. Firmware keeps them
# after wipefs. Do not delete hardware entries (ATA HDD, PXE, CD).
STALE_EFI_LABELS = (
    EFI_LABEL,
    "Ubuntu",
    "Fedora",
    "fedora",
    "Windows Boot Manager",
    "debian",
    "Linux Mint",
    "linuxmint",
)
EFI_BOOT_RE = re.compile(r"^Boot([0-9A-Fa-f]{4})\*?\s+(.*)$")


def efi_ids_for_label(text: str, label: str) -> list[str]:
    """Boot#### ids whose description equals label (before the HD() path)."""
    found: list[str] = []
    for line in text.splitlines():
        match = EFI_BOOT_RE.match(line)
        if not match:
            continue
        desc = match.group(2).split("\t", 1)[0].strip()
        if desc == label:
            found.append(match.group(1).upper())
    return found


def _efibootmgr_output() -> str:
    proc = subprocess.run(
        ["efibootmgr"],
        check=False,
        capture_output=True,
        text=True,
    )
    return proc.stdout or ""


def _delete_efi_labels(*labels: str) -> None:
    text = _efibootmgr_output()
    seen: set[str] = set()
    for label in labels:
        for bootnum in efi_ids_for_label(text, label):
            if bootnum in seen:
                continue
            seen.add(bootnum)
            subprocess.run(
                ["efibootmgr", "--bootnum", bootnum, "--delete-bootnum"],
                check=False,
                capture_output=True,
                text=True,
            )


def _register_efi(disk: str) -> None:
    if not shutil.which("efibootmgr"):
        return
    _delete_efi_labels(*STALE_EFI_LABELS)
    subprocess.run(
        [
            "efibootmgr",
            "--create",
            "--disk",
            disk,
            "--part",
            "1",
            "--label",
            EFI_LABEL,
            "--loader",
            r"\EFI\BOOT\BOOTX64.EFI",
        ],
        check=False,
        capture_output=True,
        text=True,
    )


def _apply_cli(target: str, source: str | None) -> int:
    from firstboot.disk import (
        dir_bytes,
        disk_for_device,
        find_target_disk,
        live_lsblk,
        live_mounts,
        plan_sizes,
    )

    disks = live_lsblk()
    mounts = live_mounts()
    if source:
        os.environ["FIRSTBOOT_SHOP_INSTALL"] = "1"
        mounts = dict(mounts)
        src_disk = disk_for_device(disks, source)
        if src_disk is None:
            emit("ERROR", f"unknown source {source}")
            return 2
        sys_part = src_disk.part_named("FBL-SYS")
        if sys_part is not None:
            mounts.setdefault("/cdrom", sys_part.path)
    plan = plan_install(disks, mounts, 0)
    if plan.source is None:
        emit("ERROR", plan.reason or "Not running from a First Boot USB.")
        return 2
    used = 0
    payload = plan.source.part_named("FBL-DATA")
    if payload is not None:
        for mp in payload.mountpoints:
            used = dir_bytes(mp)
            if used:
                break
    esp_b, sys_b, data_b = plan_sizes(plan.source, used)
    chosen = disk_for_device(disks, target)
    if chosen is None:
        emit("ERROR", f"unknown target {target}")
        return 2
    if chosen.path == plan.source.path:
        emit("ERROR", "source and target are the same disk")
        return 2
    need = esp_b + sys_b + data_b + SLACK_BYTES
    if chosen.size < need:
        _tgt, reason = find_target_disk(disks, plan.source, need)
        emit("ERROR", reason or f"{target} is too small")
        return 2
    plan = InstallPlan(
        True,
        "",
        source=plan.source,
        target=chosen,
        esp_bytes=esp_b,
        sys_bytes=sys_b,
        data_need_bytes=data_b,
    )
    try:
        apply_plan(plan)
    except InstallError as exc:
        emit("ERROR", str(exc))
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install First Boot Linux onto a disk")
    parser.add_argument("--plan", action="store_true", help="print the install plan as JSON")
    parser.add_argument("--apply", action="store_true", help="write the target disk (root)")
    parser.add_argument("--target", help="target disk (for --apply)")
    parser.add_argument("--source", help="source disk override")
    args = parser.parse_args(argv)
    if args.apply:
        if not args.target:
            emit("ERROR", "--apply needs --target")
            return 2
        return _apply_cli(args.target, args.source)
    import json

    plan = live_plan()
    print(json.dumps(plan.as_dict(), indent=2))
    return 0 if plan.available else 1


if __name__ == "__main__":
    raise SystemExit(main())
