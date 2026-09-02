"""FBL-native customer install pipeline.

The trampoline owns the tick list. Each official ISO file supplies unpack,
configure, bootloader, and health_check.
"""

from __future__ import annotations

import ctypes
import errno
import os
import shutil
import subprocess
from collections.abc import Callable

from firstboot.disk import LIVE_MOUNTS, PAYLOAD_MOUNT, emit, format_size, map_range
from firstboot.i18n import _
from firstboot.install import collected_mounts, unmount_error
from firstboot.installlocale import payload_install_locale
from firstboot.osinstall.common import (
    RAM_DIR,
    TARGET_LOG_REL,
    TORAM_HEADROOM,
    InstalledDisk,
    InstallLog,
    OsIdentity,
    OsInstallError,
    OsInstallPlan,
    copy_file_progress,
    detach_loops_on_disk,
    mount_iso,
    partition_disk,
    retarget_casper_loops,
    run_checked,
    umount_path,
)
from firstboot.timezone import load_timezone_minutes

# Tick copy is the chooser list. Keep in sync with fbl-installers.md §5.
TICK_CHECKING = "Checking the image"
TICK_RAM = "Copying First Boot to memory"
TICK_DISK = "Preparing the disk"
TICK_UNPACK = "Installing the system"
TICK_SETUP = "Setting up the computer"
TICK_BOOT = "Installing the bootloader"
TICK_HEALTH = "Checking the install"
TICK_DROP = "Removing First Boot"
TICK_REBOOT = "Restarting"

PIPELINE_TICKS = (
    TICK_CHECKING,
    TICK_RAM,
    TICK_DISK,
    TICK_UNPACK,
    TICK_SETUP,
    TICK_BOOT,
    TICK_HEALTH,
    TICK_DROP,
    TICK_REBOOT,
)


def mem_available_bytes() -> int:
    try:
        text = open("/proc/meminfo", encoding="ascii").read()
    except OSError:
        return 0
    avail = 0
    free = 0
    for line in text.splitlines():
        if line.startswith("MemAvailable:"):
            avail = int(line.split()[1]) * 1024
        elif line.startswith("MemFree:"):
            free = int(line.split()[1]) * 1024
    return avail or free


def emit_ticks() -> None:
    emit("TICKS", "|".join(_(label) for label in PIPELINE_TICKS))


def emit_tick(index: int, status: str, *, step: bool = False) -> None:
    emit("TICK", index, status)
    if step and 1 <= index <= len(PIPELINE_TICKS):
        emit("STEP", _(PIPELINE_TICKS[index - 1]))


def find_live_squashfs() -> str:
    for mp in LIVE_MOUNTS:
        for rel in (
            os.path.join("casper", "filesystem.squashfs"),
            os.path.join("live", "filesystem.squashfs"),
        ):
            path = os.path.join(mp, rel)
            if os.path.isfile(path):
                return path
    return ""


def already_on_ram_overlay() -> bool:
    """True after a successful same-disk pivot_root (retry this boot)."""
    lower = overlay_fields().get("lowerdir") or ""
    return RAM_DIR.rstrip("/") in lower


def overlay_fields() -> dict[str, str]:
    try:
        with open("/proc/self/mountinfo", encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return {}
    for line in lines:
        if " - " not in line:
            continue
        left, right = line.split(" - ", 1)
        fields = left.split()
        if len(fields) < 5:
            continue
        mountpoint = fields[4].replace("\\040", " ")
        if mountpoint != "/":
            continue
        rfields = right.split()
        if len(rfields) < 3 or rfields[0] != "overlay":
            continue
        out: dict[str, str] = {}
        for part in rfields[2].split(","):
            if "=" in part:
                key, value = part.split("=", 1)
                out[key] = value
        return out
    return {}


def _need_ram_bytes(squashfs_paths: list[str]) -> int:
    need = TORAM_HEADROOM
    for path in squashfs_paths:
        try:
            need += os.path.getsize(path)
        except OSError:
            pass
    live = find_live_squashfs()
    if live:
        try:
            need += os.path.getsize(live)
        except OSError:
            pass
    return need


def mount_ram_tmpfs(need_bytes: int, log: InstallLog | None = None) -> None:
    """Dedicated tmpfs so the copy is not capped by /run's 10% default."""
    os.makedirs(RAM_DIR, exist_ok=True)
    size = max(int(need_bytes), 256 * 1024 * 1024)
    opts = f"size={size},mode=0755"
    if os.path.ismount(RAM_DIR):
        proc = subprocess.run(
            ["mount", "-o", f"remount,{opts}", RAM_DIR],
            check=False,
            capture_output=True,
            text=True,
        )
        if proc.returncode == 0:
            if log:
                log.write(f"remounted tmpfs {RAM_DIR} size={size}")
            return
    proc = subprocess.run(
        ["mount", "-t", "tmpfs", "-o", opts, "tmpfs", RAM_DIR],
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode == 0:
        if log:
            log.write(f"mounted tmpfs {RAM_DIR} size={size}")
        return
    subprocess.run(
        ["mount", "-o", "remount,size=90%", "/run"],
        check=False,
        capture_output=True,
    )
    if log:
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()
        log.write(
            "tmpfs "
            + RAM_DIR
            + " failed; using /run"
            + (f" ({tail[-1]})" if tail else "")
        )


def _ram_copy_error() -> OsInstallError:
    return OsInstallError(
        _("Could not copy First Boot into memory. Plug in a First Boot USB and try again.")
    )


def _make_rprivate(path: str, log: InstallLog | None = None) -> None:
    """Drop MS_SHARED so pivot_root is allowed.

    systemd makes ``/`` shared:1. pivot_root then fails with EINVAL
    (Lenovo 0.7.1.6). Recursive private on ``/`` also covers new_root.
    """
    proc = subprocess.run(
        ["mount", "--make-rprivate", path],
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode == 0:
        if log:
            log.write(f"mount --make-rprivate {path}")
        return
    if log:
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()
        log.write(
            "mount --make-rprivate "
            + path
            + " failed"
            + (f" ({tail[-1]})" if tail else "")
        )


def do_pivot_root(
    new_root: str, put_old: str, log: InstallLog | None = None
) -> None:
    """Make new_root the filesystem root.

    Ubuntu 26.04's Python 3.14 is built without ``os.pivot_root``
    (``HAVE_PIVOT_ROOT`` is unset). glibc still exports the syscall.
    """
    new_root = os.path.abspath(new_root)
    put_old = os.path.abspath(put_old)
    if not os.path.isdir(new_root) or not os.path.isdir(put_old):
        raise _ram_copy_error()
    _make_rprivate("/", log)
    _make_rprivate(new_root, log)
    os.chdir(new_root)
    rel_old = os.path.relpath(put_old, new_root)
    if rel_old.startswith(".."):
        raise _ram_copy_error()
    encoded_old = os.fsencode(rel_old)
    fn = getattr(os, "pivot_root", None)
    if callable(fn):
        try:
            fn(".", rel_old)
            if log:
                log.write("pivot_root via os")
            return
        except OSError as exc:
            if log:
                log.write(f"os pivot_root failed: {exc}")
    try:
        libc = ctypes.CDLL("libc.so.6", use_errno=True)
        pivot = getattr(libc, "pivot_root", None)
        if pivot is not None:
            pivot.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
            pivot.restype = ctypes.c_int
            ctypes.set_errno(0)
            rc = pivot(b".", encoded_old)
            if rc == 0:
                if log:
                    log.write("pivot_root via libc")
                return
            err = ctypes.get_errno()
            if log:
                log.write(
                    "libc pivot_root failed: " + os.strerror(err) + f" ({err})"
                )
    except OSError as exc:
        if log:
            log.write(f"libc pivot_root failed: {exc}")
    for argv in (
        ["pivot_root", ".", rel_old],
        ["/usr/sbin/pivot_root", ".", rel_old],
        ["/usr/bin/pivot_root", ".", rel_old],
        ["/usr/lib/klibc/bin/pivot_root", ".", rel_old],
    ):
        if argv[0].startswith("/") and not os.path.isfile(argv[0]):
            continue
        if not argv[0].startswith("/") and not shutil.which(argv[0]):
            continue
        proc = subprocess.run(argv, check=False, capture_output=True, text=True)
        if proc.returncode == 0:
            if log:
                log.write(f"pivot_root via {argv[0]}")
            return
        if log:
            tail = (proc.stderr or proc.stdout or "").strip().splitlines()
            log.write(
                f"{argv[0]} pivot_root failed"
                + (f" ({tail[-1]})" if tail else f" rc={proc.returncode}")
            )
    raise _ram_copy_error()


def copy_live_to_ram(
    squashfs_paths: list[str],
    extra: dict[str, str],
    *,
    on_progress: Callable[[int], None] | None,
    log: InstallLog,
    need_bytes: int = 0,
) -> list[str]:
    """Copy the live squashfs + target squashfs onto tmpfs and pivot_root."""
    try:
        return _copy_live_to_ram(
            squashfs_paths,
            extra,
            on_progress=on_progress,
            log=log,
            need_bytes=need_bytes,
        )
    except OsInstallError:
        raise
    except OSError as exc:
        log.write(f"RAM copy OSError: {exc}")
        if exc.errno == errno.ENOSPC:
            raise OsInstallError(
                _(
                    "This computer needs about {size} of memory to install {name} from the internal disk."
                ).format(
                    size=format_size(need_bytes or _need_ram_bytes(squashfs_paths)),
                    name="the system",
                )
            ) from exc
        raise _ram_copy_error() from exc


def _existing_ram_layers(n: int, log: InstallLog) -> list[str]:
    dest_layers: list[str] = []
    for i in range(n):
        dest = os.path.join(RAM_DIR, f"layer{i}.squashfs")
        if not os.path.isfile(dest):
            log.write(f"RAM overlay missing {dest}")
            raise _ram_copy_error()
        dest_layers.append(dest)
    live_dest = os.path.join(RAM_DIR, "live.squashfs")
    if not os.path.isfile(live_dest):
        log.write("RAM overlay missing live.squashfs")
        raise _ram_copy_error()
    return dest_layers


def _copy_live_to_ram(
    squashfs_paths: list[str],
    extra: dict[str, str],
    *,
    on_progress: Callable[[int], None] | None,
    log: InstallLog,
    need_bytes: int = 0,
) -> list[str]:
    if already_on_ram_overlay():
        dest_layers = _existing_ram_layers(len(squashfs_paths), log)
        log.write("already on RAM overlay; skip copy and pivot")
        if on_progress:
            on_progress(100)
        return dest_layers
    mount_ram_tmpfs(need_bytes or _need_ram_bytes(squashfs_paths), log=log)
    dest_layers: list[str] = []
    n = max(1, len(squashfs_paths) + (1 if find_live_squashfs() else 0))
    for i, src in enumerate(squashfs_paths):
        dest = os.path.join(RAM_DIR, f"layer{i}.squashfs")

        def prog(pct: int, i=i) -> None:
            if on_progress:
                on_progress(map_range(pct, i * 80 // n, (i + 1) * 80 // n))

        copy_file_progress(src, dest, on_progress=prog, log=log)
        dest_layers.append(dest)
    extra_dir = os.path.join(RAM_DIR, "iso")
    for rel, src in extra.items():
        dest = os.path.join(extra_dir, rel)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        if os.path.isdir(src):
            shutil.copytree(src, dest, dirs_exist_ok=True)
        elif os.path.isfile(src):
            shutil.copy2(src, dest)
    live_src = find_live_squashfs()
    live_dest = os.path.join(RAM_DIR, "live.squashfs")
    if live_src:
        copy_file_progress(
            live_src,
            live_dest,
            on_progress=(lambda p: on_progress(map_range(p, 80, 90)) if on_progress else None),
            log=log,
        )
    if not os.path.isfile(live_dest):
        raise _ram_copy_error()
    new_rofs = os.path.join(RAM_DIR, "rofs")
    os.makedirs(new_rofs, exist_ok=True)
    run_checked(
        ["mount", "-t", "squashfs", "-o", "loop,ro", live_dest, new_rofs],
        what="mount First Boot from memory",
    )
    fields = overlay_fields()
    new_upper = os.path.join(RAM_DIR, "upper")
    new_work = os.path.join(RAM_DIR, "work")
    merged = os.path.join(RAM_DIR, "merged")
    os.makedirs(new_upper, exist_ok=True)
    os.makedirs(new_work, exist_ok=True)
    os.makedirs(merged, exist_ok=True)
    old_upper = fields.get("upperdir") or ""
    if old_upper and os.path.isdir(old_upper):
        subprocess.run(
            ["rsync", "-aH", "--numeric-ids", old_upper.rstrip("/") + "/", new_upper + "/"],
            check=False,
            capture_output=True,
        )
    run_checked(
        [
            "mount",
            "-t",
            "overlay",
            "overlay",
            "-o",
            f"lowerdir={new_rofs},upperdir={new_upper},workdir={new_work}",
            merged,
        ],
        what="run First Boot from memory",
    )
    put_old = os.path.join(merged, "oldroot")
    os.makedirs(put_old, exist_ok=True)
    # Before rbind of /run: a shared / would propagate this overlay into
    # systemd PrivateMounts namespaces (resolved, NetworkManager, …).
    _make_rprivate("/", log)
    for name in ("dev", "proc", "sys", "run", "tmp"):
        dest = os.path.join(merged, name)
        os.makedirs(dest, exist_ok=True)
        subprocess.run(
            ["mount", "--rbind", "/" + name, dest],
            check=False,
            capture_output=True,
        )
        subprocess.run(
            ["mount", "--make-rslave", dest],
            check=False,
            capture_output=True,
        )
    log.write("pivot_root to RAM overlay")
    do_pivot_root(merged, put_old, log=log)
    os.chdir("/")
    for mp in (
        "/oldroot/cdrom",
        "/oldroot/rofs",
        "/oldroot/cow",
        "/oldroot/run/live/medium",
        "/oldroot",
    ):
        subprocess.run(["umount", "-l", mp], check=False, capture_output=True)
    subprocess.run(
        ["systemctl", "stop", "run-payload.mount"],
        check=False,
        capture_output=True,
    )
    subprocess.run(
        ["systemctl", "mask", "--runtime", "run-payload.mount"],
        check=False,
        capture_output=True,
    )
    umount_path(PAYLOAD_MOUNT)
    if on_progress:
        on_progress(100)
    log.write("pivot_root to RAM overlay complete")
    return dest_layers


def _mnt_namespace_pids() -> list[str]:
    seen: set[str] = set()
    pids: list[str] = []
    try:
        names = os.listdir("/proc")
    except OSError:
        return []
    for name in names:
        if not name.isdigit():
            continue
        try:
            ident = os.readlink(os.path.join("/proc", name, "ns", "mnt"))
        except OSError:
            continue
        if ident in seen:
            continue
        seen.add(ident)
        pids.append(name)
    return pids


def umount_in_all_namespaces(
    paths: list[str], log: InstallLog | None = None
) -> None:
    """Lazy-umount in every mount namespace (systemd PrivateMounts).

    After pivot_root the helper no longer has /cdrom, but resolved / udevd /
    NetworkManager still do. wipefs then fails EBUSY (Lenovo 0.7.1.7).
    """
    nsenter = "/usr/bin/nsenter"
    if not os.path.isfile(nsenter):
        nsenter = shutil.which("nsenter") or ""
    for path in paths:
        subprocess.run(["umount", "-l", path], check=False, capture_output=True)
        n = 0
        if nsenter:
            for pid in _mnt_namespace_pids():
                proc = subprocess.run(
                    [nsenter, "-t", pid, "-m", "--", "umount", "-l", path],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                if proc.returncode == 0:
                    n += 1
        if log:
            log.write(f"umount {path} in {n} mount namespaces")


def release_disk_holders(disk_path: str, log: InstallLog | None = None) -> None:
    """Drop leftover casper mounts/loops so the target disk can be wiped."""
    # Retarget before umount: labwc/chooser keep mmap fds on casper loop0.
    # Do not umount `/` in other namespaces and do not kill bwrap/glycin —
    # labwc `-S` dies with the chooser.
    retarget_casper_loops(
        disk_path, os.path.join(RAM_DIR, "live.squashfs"), log=log
    )
    umount_in_all_namespaces(
        [PAYLOAD_MOUNT, "/cdrom", "/run/live/medium", "/rofs", "/filesystem.squashfs"],
        log=log,
    )
    detach_loops_on_disk(disk_path, log)


def _ensure_payload_mounted(plan: OsInstallPlan, log: InstallLog) -> None:
    """Remount FBL-DATA if a same-disk retry already dropped /run/payload."""
    if plan.iso_path and os.path.isfile(plan.iso_path):
        return
    if plan.target is None:
        return
    part = plan.target.part_named("FBL-DATA")
    if part is None:
        return
    os.makedirs(PAYLOAD_MOUNT, exist_ok=True)
    if os.path.ismount(PAYLOAD_MOUNT):
        return
    proc = subprocess.run(
        ["mount", part.path, PAYLOAD_MOUNT],
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()
        log.write(
            "mount payload failed" + (f" ({tail[-1]})" if tail else "")
        )
        return
    log.write(f"mounted payload {part.path} at {PAYLOAD_MOUNT}")


def unmount_target(plan: OsInstallPlan, log: InstallLog) -> None:
    if plan.target is None:
        return
    if plan.same_disk:
        # /cdrom is FBL-SYS on the target after a RAM pivot, not live USB.
        release_disk_holders(plan.target.path, log)
    protected = ("/",) if plan.same_disk else ("/", "/cdrom", "/run/live/medium")
    for mp in collected_mounts(plan.target, extra=[PAYLOAD_MOUNT]):
        err = unmount_error(mp, plan.target.path)
        if err and mp in protected:
            log.write(f"skip unmount {mp}: {err}")
            continue
        if err and not (plan.same_disk and mp in ("/cdrom", "/run/live/medium")):
            raise OsInstallError(err)
        if plan.same_disk and mp in ("/cdrom", "/run/live/medium"):
            log.write(f"unmount {mp} on target")
        subprocess.run(["umount", "-R", mp], check=False, capture_output=True)
        subprocess.run(["umount", "-l", mp], check=False, capture_output=True)
    for part in plan.target.parts:
        subprocess.run(["umount", "-R", part.path], check=False, capture_output=True)
        subprocess.run(["umount", "-l", part.path], check=False, capture_output=True)
    subprocess.run(["udevadm", "settle"], check=False, capture_output=True)


def _iso_extras(iso_mnt: str) -> dict[str, str]:
    extra: dict[str, str] = {}
    for a in ("EFI", "efi"):
        path = os.path.join(iso_mnt, a)
        if os.path.isdir(path):
            extra[a] = path
            break
    casper = os.path.join(iso_mnt, "casper")
    if os.path.isdir(casper):
        for name in ("vmlinuz", "initrd", "initrd.lz", "initrd.gz"):
            path = os.path.join(casper, name)
            if os.path.isfile(path):
                extra[os.path.join("casper", name)] = path
    return extra


def ram_iso_mnt() -> str:
    return os.path.join(RAM_DIR, "iso")


def timezone_from_payload(payload_root: str | None) -> int | None:
    root = payload_root or PAYLOAD_MOUNT
    retailer_tz = None
    conf = os.path.join(root, "retailer.conf")
    if os.path.isfile(conf):
        try:
            from firstboot.payload import parse_retailer_conf

            with open(conf, encoding="utf-8") as fh:
                raw = parse_retailer_conf(fh.read())
            retailer_tz = raw.get("timezone")
        except (OSError, Exception):
            retailer_tz = None
    try:
        return load_timezone_minutes(root, retailer_tz)
    except Exception:
        return None


def install_native(
    plan: OsInstallPlan,
    identity: OsIdentity,
    drv: object,
    *,
    payload_root: str | None = None,
    on_progress: Callable[[int], None] | None = None,
) -> None:
    if not plan.available or plan.target is None or plan.live is None:
        raise OsInstallError(plan.reason or _("Cannot install."))
    if os.geteuid() != 0:
        raise OsInstallError("must run as root")

    def prog(n: int) -> None:
        n = max(0, min(100, int(n)))
        if on_progress:
            on_progress(n)
        else:
            emit("PROGRESS", n)

    log = InstallLog()
    log.write(
        f"native install driver={getattr(drv, 'id', '')} "
        f"iso={plan.iso_path} target={plan.target.path} same_disk={plan.same_disk}"
    )
    emit_ticks()
    locale = payload_install_locale(payload_root)
    tz_minutes = timezone_from_payload(payload_root)
    iso_mnt = ""
    ram_layers: list[str] = []
    ram_layer_rels: list[str] = []
    disk: InstalledDisk | None = None
    boot_log = ""
    wiped = False
    try:
        emit_tick(1, "current", step=True)
        prog(2)
        from firstboot.osinstall import verify_iso

        if plan.same_disk:
            _ensure_payload_mounted(plan, log)
        on_ram = already_on_ram_overlay()
        rels_path = os.path.join(RAM_DIR, "squashfs-layers.txt")
        if on_ram and os.path.isfile(os.path.join(RAM_DIR, "live.squashfs")):
            log.write("already on RAM overlay; skip image check")
            emit_tick(1, "done")
            prog(8)
        else:
            verify_iso(
                plan.iso_path,
                plan.sha256,
                plan.size_bytes,
                on_progress=lambda p: prog(map_range(p, 2, 8)),
            )
            emit_tick(1, "done")
            prog(8)

        if plan.same_disk:
            emit_tick(2, "current", step=True)
            if on_ram and os.path.isfile(rels_path):
                with open(rels_path, encoding="utf-8") as fh:
                    rels = [ln.strip() for ln in fh if ln.strip()]
                ram_layer_rels = list(rels)
                ram_layers = _existing_ram_layers(len(rels), log)
                log.write("already on RAM overlay; skip copy and pivot")
                iso_mnt = ram_iso_mnt()
                emit_tick(2, "done")
            else:
                iso_mnt = mount_iso(plan.iso_path)
                rels = drv.squashfs_relpaths(iso_mnt) if callable(
                    getattr(drv, "squashfs_relpaths", None)
                ) else ["casper/filesystem.squashfs"]
                src_layers = [os.path.join(iso_mnt, rel) for rel in rels]
                missing = [p for p in src_layers if not os.path.isfile(p)]
                if missing:
                    raise OsInstallError("This image is not a live ISO.")
                log.write("squashfs layers: " + " ".join(rels))
                ram_layer_rels = list(rels)
                try:
                    os.makedirs(RAM_DIR, exist_ok=True)
                    with open(rels_path, "w", encoding="utf-8") as fh:
                        fh.write("\n".join(rels) + "\n")
                except OSError:
                    pass
                need = _need_ram_bytes(src_layers)
                have = mem_available_bytes()
                # First attempt already occupies the RAM tmpfs (Shmem). A retry
                # must not treat that as missing headroom.
                if have < need and not on_ram:
                    raise OsInstallError(
                        _(
                            "This computer needs about {size} of memory to install {name} from the internal disk."
                        ).format(
                            size=format_size(need),
                            name=plan.distro_name or "the system",
                        )
                    )
                extras = _iso_extras(iso_mnt)
                ram_layers = copy_live_to_ram(
                    src_layers,
                    extras,
                    on_progress=lambda p: prog(map_range(p, 8, 18)),
                    log=log,
                    need_bytes=need,
                )
                umount_path(iso_mnt)
                shutil.rmtree(iso_mnt, ignore_errors=True)
                iso_mnt = ram_iso_mnt()
                emit_tick(2, "done")
        else:
            emit_tick(2, "skip")
            iso_mnt = mount_iso(plan.iso_path)
        prog(18)

        emit_tick(3, "current", step=True)
        unmount_target(plan, log)
        work = os.path.join(RAM_DIR, "mnt")
        os.makedirs(work, exist_ok=True)
        disk = partition_disk(plan.target.path, work, log=log)
        wiped = True
        emit_tick(3, "done")
        prog(24)

        emit_tick(4, "current", step=True)
        unpack_mnt = iso_mnt
        if ram_layers:
            unpack_mnt = os.path.join(RAM_DIR, "live-tree")
            os.makedirs(os.path.join(unpack_mnt, "casper"), exist_ok=True)
            for rel, layer in zip(ram_layer_rels, ram_layers):
                dest = os.path.join(unpack_mnt, rel)
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                if not os.path.exists(dest):
                    os.symlink(layer, dest)
            iso_extra = ram_iso_mnt()
            if os.path.isdir(iso_extra):
                for name in os.listdir(iso_extra):
                    src = os.path.join(iso_extra, name)
                    dest = os.path.join(unpack_mnt, name)
                    if os.path.isdir(src) and not os.path.exists(dest):
                        os.symlink(src, dest)
                    elif os.path.isfile(src) and not os.path.exists(dest):
                        os.symlink(src, dest)
        drv.unpack(
            unpack_mnt,
            disk.root_mp,
            on_progress=lambda p: prog(map_range(p, 24, 70)),
            log=log,
        )
        emit_tick(4, "done")
        prog(70)

        emit_tick(5, "current", step=True)
        drv.configure(
            disk.root_mp,
            identity,
            locale,
            disk,
            timezone_minutes=tz_minutes,
            log=log,
        )
        emit_tick(5, "done")
        prog(82)

        emit_tick(6, "current", step=True)
        boot_log = drv.bootloader(
            disk.root_mp, disk.esp_mp, disk, unpack_mnt, log=log
        ) or ""
        emit_tick(6, "done")
        prog(90)

        emit_tick(7, "current", step=True)
        failures = drv.health_check(
            disk.root_mp, disk.esp_mp, identity, disk, boot_log=boot_log
        )
        log.copy_to(os.path.join(disk.root_mp, TARGET_LOG_REL))
        if failures:
            for item in failures:
                log.write("health: " + item)
            emit_tick(7, "failed")
            raise OsInstallError(
                _("The install could not be checked.")
                + " "
                + failures[0]
            )
        emit_tick(7, "done")
        prog(94)

        emit_tick(8, "current", step=True)
        # Disk already holds the new OS. Drop leftover FBL NVRAM labels.
        from firstboot.osinstall.common import efi_loader_path, register_os_efi

        label = getattr(drv, "nvram_label", None) or plan.distro_name or "Linux"
        boot_id = getattr(drv, "bootloader_id", None) or "ubuntu"
        loader = efi_loader_path(disk.esp_mp, boot_id)
        register_os_efi(disk, label, loader, log=log)
        emit_tick(8, "done")
        prog(98)

        emit_tick(9, "current", step=True)
        emit("STEP", _("Restarting"))
        os.sync()
        emit_tick(9, "done")
        prog(100)
        if os.environ.get("FIRSTBOOT_OSINSTALL_NO_REBOOT") == "1":
            emit("DONE")
            return
        emit("REBOOT")
        subprocess.run(["systemctl", "reboot"], check=False)
    except Exception as exc:
        log.write(f"error: {exc}")
        if disk is not None:
            try:
                log.copy_to(os.path.join(disk.root_mp, TARGET_LOG_REL))
            except Exception:
                pass
        if wiped:
            log.write("failed after disk wipe; FBL partitions are gone")
        raise
    finally:
        if iso_mnt and os.path.ismount(iso_mnt) and iso_mnt != ram_iso_mnt():
            umount_path(iso_mnt)
            shutil.rmtree(iso_mnt, ignore_errors=True)
        log.close()
