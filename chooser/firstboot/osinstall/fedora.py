"""Fedora live-ISO unpack (EROFS ``LiveOS/squashfs.img``).

Follow Anaconda's live-image path: rsync the EROFS, Fedora's default
partition layout (ESP + /boot + btrfs), kernel-install + grub2-mkconfig,
dracut, then ``/.autorelabel``. Copy Fedora's shim, not Canonical GRUB.
GNOME and Plasma each have their own ISO file; they call these steps.
"""

from __future__ import annotations

import os
import re
import shutil
import struct
import subprocess
from collections.abc import Callable

from firstboot.disk import part_path, rsync_percent
from firstboot.i18n import _
from firstboot.install import InstallError, blkid_uuid, wait_dev
from firstboot.installlocale import InstallLocale
from firstboot.osinstall.common import (
    InstalledDisk,
    InstallLog,
    OsIdentity,
    OsInstallError,
    add_user,
    bind_chroot,
    casper_loops_on_disk,
    chroot_run,
    delete_users,
    detach_loops_on_disk,
    disk_busy_error,
    health_check as tree_health_check,
    kernel_files,
    new_machine_id,
    run_checked,
    set_graphical_target,
    umount_path,
    unbind_chroot,
    write_fstab,
    write_hostname,
)

EROFS_MAGIC = 0xE0F5E1E2
SQUASHFS_MAGIC = b"hsqs"

# Fedora 43+ Anaconda automatic partitioning (UEFI).
FEDORA_ESP_MIB = 600
FEDORA_BOOT_MIB = 2048
BTRFS_ROOT_OPTS = "subvol=root,compress=zstd:1"

LIVE_UNITS = (
    "livesys.service",
    "livesys-late.service",
    "anaconda.service",
    "liveinst.service",
    "initial-setup.service",
    "initial-setup-reconfiguration.service",
    "gnome-initial-setup.service",
)
LIVE_DESKTOPS = (
    "liveinst.desktop",
    "anaconda.desktop",
    "plasma-setup.desktop",
    "org.fedoraproject.AnacondaInstaller.desktop",
    "gnome-initial-setup-first-login.desktop",
    "gnome-welcome-tour.desktop",
    "org.gnome.InitialSetup.desktop",
)

# Anaconda live_image InstallFromImageTask, including the KIWI xattr split.
ANACONDA_RSYNC_EXCLUDES = (
    "/dev/",
    "/proc/",
    "/tmp/*",
    "/sys/",
    "/run/",
    "/boot/*rescue*",
    "/boot/loader/",
    "/boot/efi/",
    "/boot/grub2/",
    "/etc/sysconfig/",
    "/usr/lib/grub/",
    "/etc/machine-id",
    "/etc/machine-info",
)
KIWI_RECOPY = ("boot/grub2", "etc/sysconfig", "usr/lib/grub")

LIVE_DRACUT_OMIT = (
    "dmsquash-live",
    "dmsquash-live-autooverlay",
    "dmsquash-live-ntfs",
    "livenet",
)

# Anaconda uses hostonly only when dracut runs on the installed OS.
# We chroot from Ubuntu: /proc is FBL. dracut(8): if chrooted to another
# root, use --fstab. Image installs use -N --persistent-policy by-uuid.
DRACUT_CONF = (
    'hostonly="no"\n'
    'persistent_policy="by-uuid"\n'
    'omit_dracutmodules+=" ' + " ".join(LIVE_DRACUT_OMIT) + ' "\n'
)

CLEAR_ENFORCING0 = """#!/bin/bash
# After fixfiles -F onboot, drop the one-time enforcing=0 karg.
# RHEL 10: unlabeled trees must boot enforcing=0 for relabel, then return
# to the mode in /etc/selinux/config.
set -e
[ -e /.autorelabel ] && exit 0
changed=0
for f in /boot/loader/entries/*.conf /etc/kernel/cmdline /etc/kernel/cmdline.d/*.conf; do
    [ -f "$f" ] || continue
    grep -q 'enforcing=0' "$f" || continue
    sed -i 's/[[:space:]]*enforcing=0//g' "$f"
    changed=1
done
exit 0
"""

CLEAR_ENFORCING0_UNIT = """[Unit]
Description=Remove one-time SELinux relabel kernel argument
After=selinux-autorelabel.service
Before=display-manager.service
ConditionPathExists=!/.autorelabel

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/libexec/selinux/clear-relabel-kargs

[Install]
WantedBy=graphical.target
"""


def _hint(iso_mnt: str) -> str:
    live = os.path.join(iso_mnt, "LiveOS")
    if not os.path.isdir(live):
        return "No LiveOS directory on the image."
    try:
        names = sorted(os.listdir(live))
    except OSError:
        names = []
    return "LiveOS/ has " + (", ".join(names[:8]) if names else "nothing") + "."


def fedora_live_relpaths(iso_mnt: str) -> list[str]:
    """Live filesystem image on the ISO. F44 KDE is ``LiveOS/squashfs.img``."""
    for rel in (
        os.path.join("LiveOS", "squashfs.img"),
        os.path.join("LiveOS", "rootfs.img"),
        os.path.join("liveos", "squashfs.img"),
    ):
        if os.path.isfile(os.path.join(iso_mnt, rel)):
            return [rel]
    raise OsInstallError("This image is not a Fedora live ISO. " + _hint(iso_mnt))


def fedora_boot_files(iso_mnt: str) -> tuple[str, str]:
    candidates = (
        ("boot/x86_64/loader/linux", "boot/x86_64/loader/initrd"),
        ("images/pxeboot/vmlinuz", "images/pxeboot/initrd.img"),
    )
    for vrel, irel in candidates:
        vmlinuz = os.path.join(iso_mnt, vrel)
        initrd = os.path.join(iso_mnt, irel)
        if os.path.isfile(vmlinuz) and os.path.isfile(initrd):
            return vmlinuz, initrd
    return "", ""


def image_fstype(path: str) -> str:
    """``erofs`` or ``squashfs`` from on-disk magic. Empty if unknown."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(2048)
    except OSError:
        return ""
    if head.startswith(SQUASHFS_MAGIC):
        return "squashfs"
    if len(head) >= 1028:
        magic = struct.unpack_from("<I", head, 1024)[0]
        if magic == EROFS_MAGIC:
            return "erofs"
    return ""


def partition_fedora_disk(
    disk_path: str, work: str, log: InstallLog | None = None
) -> InstalledDisk:
    """Fedora automatic layout: ESP, ext4 /boot, btrfs root+home subvolumes."""
    leftover = casper_loops_on_disk(disk_path)
    if leftover:
        if log:
            log.write("casper loop still on disk: " + " ".join(leftover))
        raise disk_busy_error()
    subprocess.run(["swapoff", "-a"], check=False, capture_output=True)
    if log:
        log.write(f"wipe {disk_path} (Fedora ESP+/boot+btrfs)")
    run_checked(["wipefs", "-a", "-f", disk_path], what=f"wipe {disk_path}")
    run_checked(["sgdisk", "--zap-all", disk_path], what="clear GPT")
    run_checked(
        [
            "sgdisk",
            f"--new=1:1M:+{FEDORA_ESP_MIB}M",
            "--typecode=1:EF00",
            "--change-name=1:EFI",
            f"--new=2:0:+{FEDORA_BOOT_MIB}M",
            "--typecode=2:8300",
            "--change-name=2:boot",
            "--new=3:0:0",
            "--typecode=3:8300",
            "--change-name=3:fedora",
            disk_path,
        ],
        what="create Fedora partitions",
    )
    subprocess.run(["partprobe", disk_path], check=False, capture_output=True)
    subprocess.run(["udevadm", "settle"], check=False, capture_output=True)
    detach_loops_on_disk(disk_path, log=log)
    esp_dev = part_path(disk_path, 1)
    boot_dev = part_path(disk_path, 2)
    root_dev = part_path(disk_path, 3)
    wait_dev(esp_dev)
    wait_dev(boot_dev)
    wait_dev(root_dev)
    run_checked(["mkfs.vfat", "-F", "32", "-n", "EFI", esp_dev], what="format ESP")
    run_checked(
        ["mkfs.ext4", "-F", "-q", "-L", "boot", boot_dev],
        what="format /boot",
    )
    run_checked(
        ["mkfs.btrfs", "-f", "-q", "-L", "fedora", root_dev],
        what="format btrfs",
    )
    top = os.path.join(work, "btrfs")
    root_mp = os.path.join(work, "root")
    os.makedirs(top, exist_ok=True)
    os.makedirs(root_mp, exist_ok=True)
    run_checked(["mount", root_dev, top], what="mount btrfs")
    try:
        run_checked(
            ["btrfs", "subvolume", "create", os.path.join(top, "root")],
            what="create btrfs subvolume root",
        )
        run_checked(
            ["btrfs", "subvolume", "create", os.path.join(top, "home")],
            what="create btrfs subvolume home",
        )
    finally:
        umount_path(top)
    run_checked(
        ["mount", "-o", BTRFS_ROOT_OPTS, root_dev, root_mp],
        what="mount btrfs root",
    )
    os.makedirs(os.path.join(root_mp, "home"), exist_ok=True)
    os.makedirs(os.path.join(root_mp, "boot"), exist_ok=True)
    run_checked(
        [
            "mount",
            "-o",
            "subvol=home,compress=zstd:1",
            root_dev,
            os.path.join(root_mp, "home"),
        ],
        what="mount btrfs home",
    )
    run_checked(
        ["mount", boot_dev, os.path.join(root_mp, "boot")],
        what="mount /boot",
    )
    os.makedirs(os.path.join(root_mp, "boot", "efi"), exist_ok=True)
    run_checked(
        ["mount", esp_dev, os.path.join(root_mp, "boot", "efi")],
        what="mount ESP",
    )
    efi_mp = os.path.join(root_mp, "boot", "efi")
    boot_mp = os.path.join(root_mp, "boot")
    if log:
        log.write(
            f"partitioned {disk_path} esp={esp_dev} boot={boot_dev} root={root_dev}"
        )
    return InstalledDisk(
        disk=disk_path,
        esp_dev=esp_dev,
        root_dev=root_dev,
        esp_uuid=blkid_uuid(esp_dev),
        root_uuid=blkid_uuid(root_dev),
        esp_mp=efi_mp,
        root_mp=root_mp,
        boot_dev=boot_dev,
        boot_uuid=blkid_uuid(boot_dev),
        boot_mp=boot_mp,
        root_fstype="btrfs",
        root_fsopts=BTRFS_ROOT_OPTS,
    )


def _rsync_with_progress(
    argv: list[str],
    *,
    on_percent: Callable[[int], None] | None,
    what: str,
) -> int:
    try:
        proc = subprocess.Popen(
            argv,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
    except OSError as exc:
        raise OsInstallError(f"{what}: {exc}") from exc
    assert proc.stderr is not None
    errors: list[str] = []
    for line in proc.stderr:
        pct = rsync_percent(line)
        if pct is not None and on_percent is not None:
            on_percent(pct)
            continue
        text = line.strip()
        if text:
            errors.append(text)
    rc = proc.wait()
    if rc not in (0, 23):
        tail = errors[-1] if errors else f"rsync {rc}"
        raise OsInstallError(f"{what}: {tail}")
    return rc


def copy_fedora_tree(
    src: str,
    dst: str,
    *,
    on_percent: Callable[[int], None] | None = None,
    log: InstallLog | None = None,
) -> None:
    """Anaconda ``InstallFromImageTask`` rsync, including the KIWI two-pass."""
    os.makedirs(dst, exist_ok=True)
    argv = [
        "rsync",
        "-pogAXtlHrDx",
        "--info=progress2",
        "--no-inc-recursive",
    ]
    for excl in ANACONDA_RSYNC_EXCLUDES:
        argv.extend(["--exclude", excl])
    argv.extend([src.rstrip("/") + "/", dst.rstrip("/") + "/"])
    rc = _rsync_with_progress(argv, on_percent=on_percent, what="copy the Fedora system")
    if log and rc == 23:
        log.write("rsync 23 copying xattrs (expected on a non-SELinux host)")
    for rel in KIWI_RECOPY:
        src_dir = os.path.join(src, rel)
        if not os.path.exists(src_dir):
            continue
        dest_dir = os.path.join(dst, rel)
        os.makedirs(dest_dir, exist_ok=True)
        recopy = [
            "rsync",
            "-rx",
            "--no-inc-recursive",
            os.path.normpath(src_dir) + "/",
            dest_dir.rstrip("/") + "/",
        ]
        proc = subprocess.run(recopy, check=False, capture_output=True, text=True)
        if proc.returncode not in (0, 23):
            tail = (proc.stderr or proc.stdout or "").strip().splitlines()
            raise OsInstallError(
                "copy the Fedora system: "
                + (tail[-1] if tail else f"rsync {proc.returncode}")
            )
        if log:
            log.write(f"rsync -rx {rel}")


def unpack_fedora(
    iso_mnt: str,
    target_root: str,
    *,
    on_progress: Callable[[int], None] | None = None,
    log: InstallLog | None = None,
) -> None:
    rels = fedora_live_relpaths(iso_mnt)
    img = os.path.join(iso_mnt, rels[0])
    fstype = image_fstype(img) or "erofs"
    if log:
        log.write(f"unpack {rels[0]} fstype={fstype}")
    os.makedirs(target_root, exist_ok=True)
    mnt = target_root.rstrip("/") + ".liveimg"
    nested_mnt = target_root.rstrip("/") + ".rootfs"
    os.makedirs(mnt, exist_ok=True)
    inner = mnt
    try:
        subprocess.run(
            ["modprobe", fstype], check=False, capture_output=True
        )
        run_checked(
            ["mount", "-t", fstype, "-o", "loop,ro", img, mnt],
            what="mount the Fedora live filesystem",
        )
        nested = os.path.join(mnt, "LiveOS", "rootfs.img")
        if os.path.isfile(nested):
            os.makedirs(nested_mnt, exist_ok=True)
            nest_type = image_fstype(nested)
            argv = ["mount", "-o", "loop,ro", nested, nested_mnt]
            if nest_type:
                argv = ["mount", "-t", nest_type, "-o", "loop,ro", nested, nested_mnt]
            run_checked(argv, what="mount the Fedora root image")
            inner = nested_mnt
            if log:
                log.write(f"nested LiveOS/rootfs.img fstype={nest_type or 'auto'}")
        copy_fedora_tree(inner, target_root, on_percent=on_progress, log=log)
        if log:
            log.write(f"rsync live tree {img} -> {target_root}")
    except InstallError as exc:
        raise OsInstallError(str(exc)) from exc
    finally:
        if inner != mnt:
            umount_path(nested_mnt)
            shutil.rmtree(nested_mnt, ignore_errors=True)
        umount_path(mnt)
        shutil.rmtree(mnt, ignore_errors=True)
    copy_live_kernel(iso_mnt, target_root, log=log)
    if on_progress:
        on_progress(100)


def module_versions(root: str) -> list[str]:
    mods = os.path.join(root, "usr", "lib", "modules")
    if not os.path.isdir(mods):
        return []
    try:
        names = os.listdir(mods)
    except OSError:
        return []
    out: list[str] = []
    for name in sorted(names):
        if name.startswith("."):
            continue
        path = os.path.join(mods, name)
        if os.path.isdir(path) and not name.endswith("+debug"):
            out.append(name)
    return out


def copy_live_kernel(
    iso_mnt: str, target_root: str, log: InstallLog | None = None
) -> None:
    """ISO kernel lives under ``boot/x86_64/loader``, not always in the EROFS."""
    boot = os.path.join(target_root, "boot")
    os.makedirs(boot, exist_ok=True)
    if kernel_files(target_root):
        return
    vmlinuz, initrd = fedora_boot_files(iso_mnt)
    if not vmlinuz:
        return
    vers = module_versions(target_root)
    ver = vers[-1] if vers else ""
    dest_v = os.path.join(boot, f"vmlinuz-{ver}" if ver else "vmlinuz")
    dest_i = os.path.join(boot, f"initramfs-{ver}.img" if ver else "initramfs.img")
    shutil.copy2(vmlinuz, dest_v)
    if initrd:
        shutil.copy2(initrd, dest_i)
    if log:
        log.write(f"copied live kernel to {os.path.basename(dest_v)}")


def write_locale(root: str, locale: InstallLocale) -> None:
    conf = os.path.join(root, "etc", "locale.conf")
    os.makedirs(os.path.dirname(conf), exist_ok=True)
    with open(conf, "w", encoding="utf-8") as fh:
        fh.write(f"LANG={locale.glibc}\n")
    vconsole = os.path.join(root, "etc", "vconsole.conf")
    with open(vconsole, "w", encoding="utf-8") as fh:
        fh.write(f"KEYMAP={locale.keyboard}\nFONT=eurlatgr\n")
    xdir = os.path.join(root, "etc", "X11", "xorg.conf.d")
    os.makedirs(xdir, exist_ok=True)
    with open(os.path.join(xdir, "00-keyboard.conf"), "w", encoding="utf-8") as fh:
        fh.write(
            'Section "InputClass"\n'
            '    Identifier "system-keyboard"\n'
            '    MatchIsKeyboard "on"\n'
            f'    Option "XkbLayout" "{locale.keyboard}"\n'
            "EndSection\n"
        )


def write_timezone(root: str, minutes: int | None, log: InstallLog | None = None) -> None:
    if minutes is None:
        return
    from firstboot.timezone import iana_zone, snap_tz_minutes, tzif_bytes

    minutes = snap_tz_minutes(minutes)
    zone = iana_zone(minutes)
    localtime = os.path.join(root, "etc", "localtime")
    try:
        if os.path.islink(localtime) or os.path.isfile(localtime):
            os.unlink(localtime)
    except OSError:
        pass
    if zone:
        src = os.path.join(root, "usr", "share", "zoneinfo", zone)
        if os.path.isfile(src):
            os.makedirs(os.path.dirname(localtime), exist_ok=True)
            os.symlink(os.path.join("/usr/share/zoneinfo", zone), localtime)
            if log:
                log.write(f"timezone {zone}")
            return
    os.makedirs(os.path.dirname(localtime), exist_ok=True)
    with open(localtime, "wb") as fh:
        fh.write(tzif_bytes(minutes))
    if log:
        log.write(f"timezone offset {minutes} minutes")


_SDDM_AUTOLOGIN_RE = re.compile(
    r"(?im)^(User|Session|Relogin)\s*=.*\n?"
)
_GDM_AUTOLOGIN_RE = re.compile(
    r"(?im)^(AutomaticLoginEnable|AutomaticLogin|TimedLoginEnable|TimedLogin)\s*=.*\n?"
)


def _strip_sddm_file(path: str) -> None:
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    new = _SDDM_AUTOLOGIN_RE.sub("", text)
    if new != text:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(new)


def _strip_gdm_file(path: str) -> None:
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    new = _GDM_AUTOLOGIN_RE.sub("", text)
    if new != text:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(new)


def _strip_dm_dropins(
    root: str, rel_conf: str, rel_drop: str, *, gdm: bool = False
) -> None:
    strip = _strip_gdm_file if gdm else _strip_sddm_file
    strip(os.path.join(root, rel_conf))
    drop = os.path.join(root, rel_drop)
    if not os.path.isdir(drop):
        return
    try:
        names = os.listdir(drop)
    except OSError:
        return
    for name in names:
        path = os.path.join(drop, name)
        lower = name.lower()
        if "live" in lower or "autologin" in lower or "livesys" in lower:
            try:
                os.unlink(path)
            except OSError:
                pass
        else:
            strip(path)


def skip_gnome_initial_setup(root: str, log: InstallLog | None = None) -> None:
    """Customer identity is already on the form; do not run GNOME first-login."""
    homes = os.path.join(root, "home")
    if os.path.isdir(homes):
        try:
            names = os.listdir(homes)
        except OSError:
            names = []
        for name in names:
            if name.startswith("."):
                continue
            home = os.path.join(homes, name)
            if not os.path.isdir(home):
                continue
            cfg = os.path.join(home, ".config")
            os.makedirs(cfg, exist_ok=True)
            marker = os.path.join(cfg, "gnome-initial-setup-done")
            with open(marker, "w", encoding="ascii") as fh:
                fh.write("yes\n")
            try:
                st = os.stat(home)
                os.chown(cfg, st.st_uid, st.st_gid)
                os.chown(marker, st.st_uid, st.st_gid)
            except OSError:
                pass
    if log:
        log.write("skipped gnome-initial-setup")


def strip_live_session(root: str, log: InstallLog | None = None) -> None:
    for conf, drop in (
        (os.path.join("etc", "sddm.conf"), os.path.join("etc", "sddm.conf.d")),
        (os.path.join("etc", "plasmalogin.conf"), os.path.join("etc", "plasmalogin.conf.d")),
        (os.path.join("etc", "plasma-login.conf"), os.path.join("etc", "plasma-login.conf.d")),
    ):
        _strip_dm_dropins(root, conf, drop)
    _strip_dm_dropins(
        root,
        os.path.join("etc", "gdm", "custom.conf"),
        os.path.join("etc", "gdm", "custom.conf.d"),
        gdm=True,
    )
    skip_gnome_initial_setup(root, log=log)
    autostart = os.path.join(root, "etc", "xdg", "autostart")
    apps = os.path.join(root, "usr", "share", "applications")
    for folder in (autostart, apps):
        if not os.path.isdir(folder):
            continue
        for name in LIVE_DESKTOPS:
            try:
                os.unlink(os.path.join(folder, name))
            except OSError:
                pass
    for rel in (
        os.path.join("etc", "sysconfig", "livesys"),
        os.path.join("etc", "rc.d", "init.d", "livesys"),
        os.path.join("etc", "rc.d", "init.d", "livesys-late"),
    ):
        try:
            os.unlink(os.path.join(root, rel))
        except OSError:
            pass
    systemd = os.path.join(root, "etc", "systemd", "system")
    for dirpath, _dirnames, filenames in os.walk(systemd):
        if not dirpath.endswith(".wants"):
            continue
        for name in filenames:
            if name in LIVE_UNITS or name.startswith("livesys"):
                try:
                    os.unlink(os.path.join(dirpath, name))
                except OSError:
                    pass
    setup = os.path.join(root, "var", "lib", "plasma-setup")
    os.makedirs(setup, exist_ok=True)
    try:
        open(os.path.join(setup, "completed"), "a", encoding="utf-8").close()
    except OSError:
        pass
    if log:
        log.write("stripped Fedora live session leftover")


def _root_kargs(disk: InstalledDisk) -> str:
    """Installed cmdline. enforcing=0 is required while /.autorelabel is queued."""
    parts = [f"root=UUID={disk.root_uuid}", "ro"]
    opts = disk.root_fsopts or ""
    for opt in opts.split(","):
        if opt.startswith("subvol="):
            parts.append(f"rootflags={opt}")
            break
    parts.extend(["rhgb", "quiet", "enforcing=0"])
    return " ".join(parts)


def write_kernel_cmdline(root: str, disk: InstalledDisk) -> None:
    text = _root_kargs(disk) + "\n"
    path = os.path.join(root, "etc", "kernel", "cmdline")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    extra = os.path.join(root, "etc", "kernel", "cmdline.d")
    os.makedirs(extra, exist_ok=True)
    with open(os.path.join(extra, "root.conf"), "w", encoding="utf-8") as fh:
        fh.write(text)


def write_grub_default(root: str) -> None:
    path = os.path.join(root, "etc", "default", "grub")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(
            'GRUB_TIMEOUT=5\n'
            'GRUB_DISTRIBUTOR="Fedora Linux"\n'
            "GRUB_DEFAULT=saved\n"
            "GRUB_DISABLE_SUBMENU=true\n"
            'GRUB_CMDLINE_LINUX="rhgb quiet"\n'
            'GRUB_CMDLINE_LINUX_DEFAULT=""\n'
            "GRUB_DISABLE_RECOVERY=true\n"
            "GRUB_ENABLE_BLSCFG=true\n"
        )


def _vmlinuz_version(root: str) -> str:
    vers = module_versions(root)
    if vers:
        return vers[-1]
    boot = os.path.join(root, "boot")
    if not os.path.isdir(boot):
        return ""
    try:
        names = os.listdir(boot)
    except OSError:
        return ""
    for name in sorted(names):
        if name.startswith("vmlinuz-") and not name.endswith(".old"):
            return name[len("vmlinuz-") :]
    return ""


def write_bls_entry(root: str, disk: InstalledDisk, log: InstallLog | None = None) -> None:
    """BLS paths are relative to the /boot filesystem (Anaconda / kernel-install)."""
    ver = _vmlinuz_version(root)
    linux = f"/vmlinuz-{ver}" if ver else "/vmlinuz"
    initrd = f"/initramfs-{ver}.img" if ver else "/initramfs.img"
    boot = os.path.join(root, "boot")
    if not os.path.isfile(os.path.join(boot, linux.lstrip("/"))):
        if os.path.isfile(os.path.join(boot, "vmlinuz")):
            linux = "/vmlinuz"
        else:
            return
    if not os.path.isfile(os.path.join(boot, initrd.lstrip("/"))):
        if os.path.isfile(os.path.join(boot, "initramfs.img")):
            initrd = "/initramfs.img"
        elif os.path.isfile(os.path.join(boot, "initrd.img")):
            initrd = "/initrd.img"
    entries = os.path.join(boot, "loader", "entries")
    os.makedirs(entries, exist_ok=True)
    try:
        for name in os.listdir(entries):
            if name.endswith(".conf"):
                os.unlink(os.path.join(entries, name))
    except OSError:
        pass
    ident = ver or "fedora"
    path = os.path.join(entries, f"{ident}.conf")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(
            "title Fedora Linux\n"
            f"version {ver or '1'}\n"
            f"linux {linux}\n"
            f"initrd {initrd}\n"
            f"options {_root_kargs(disk)}\n"
        )
    if log:
        log.write(f"wrote BLS {os.path.basename(path)}")


def _boot_kernel_paths(root: str) -> tuple[str, str]:
    """Paths relative to the /boot filesystem (separate volume on Fedora)."""
    ver = _vmlinuz_version(root)
    linux = f"/vmlinuz-{ver}" if ver else "/vmlinuz"
    initrd = f"/initramfs-{ver}.img" if ver else "/initramfs.img"
    boot = os.path.join(root, "boot")
    if not os.path.isfile(os.path.join(boot, linux.lstrip("/"))):
        if os.path.isfile(os.path.join(boot, "vmlinuz")):
            linux = "/vmlinuz"
    if not os.path.isfile(os.path.join(boot, initrd.lstrip("/"))):
        if os.path.isfile(os.path.join(boot, "initramfs.img")):
            initrd = "/initramfs.img"
        elif os.path.isfile(os.path.join(boot, "initrd.img")):
            initrd = "/initrd.img"
    return linux, initrd


def write_grub2_cfg(root: str, disk: InstalledDisk, log: InstallLog | None = None) -> None:
    """Bootable menuentry if grub2-mkconfig cannot run in the Ubuntu chroot.

    Paths are relative to the /boot filesystem. Do not call blscfg here:
    Fedora's blscfg needs load_video from 00_header (Lenovo 0.7.1.20).
    """
    grub_dir = os.path.join(root, "boot", "grub2")
    os.makedirs(grub_dir, exist_ok=True)
    uuid = disk.boot_uuid or disk.root_uuid
    linux, initrd = _boot_kernel_paths(root)
    kargs = _root_kargs(disk)
    text = (
        "set default=0\n"
        "set timeout=5\n"
        "insmod all_video\n"
        "insmod gzio\n"
        "insmod part_gpt\n"
        "insmod ext2\n"
        f"search --no-floppy --fs-uuid --set=root {uuid}\n"
        'menuentry "Fedora Linux" {\n'
        f"    search --no-floppy --fs-uuid --set=root {uuid}\n"
        f"    linux {linux} {kargs}\n"
        f"    initrd {initrd}\n"
        "}\n"
    )
    with open(os.path.join(grub_dir, "grub.cfg"), "w", encoding="utf-8") as fh:
        fh.write(text)
    if log:
        log.write(f"wrote /boot/grub2/grub.cfg linux={linux}")


def strip_live_dracut_conf(root: str, log: InstallLog | None = None) -> None:
    """Drop live-image dracut snippets so the installed initramfs is not a LiveOS image."""
    for rel in (
        os.path.join("etc", "dracut.conf.d"),
        os.path.join("usr", "lib", "dracut", "dracut.conf.d"),
    ):
        folder = os.path.join(root, rel)
        if not os.path.isdir(folder):
            continue
        try:
            names = os.listdir(folder)
        except OSError:
            continue
        for name in names:
            lower = name.lower()
            if "live" not in lower and "livenet" not in lower:
                continue
            path = os.path.join(folder, name)
            if os.path.isdir(path):
                continue
            try:
                os.unlink(path)
                if log:
                    log.write(f"removed live dracut {rel}/{name}")
            except OSError:
                pass
    dest_dir = os.path.join(root, "etc", "dracut.conf.d")
    os.makedirs(dest_dir, exist_ok=True)
    with open(os.path.join(dest_dir, "99-fbl.conf"), "w", encoding="utf-8") as fh:
        fh.write(DRACUT_CONF)


def _pin_proc_cmdline(root: str, cmdline: str, log: InstallLog | None = None) -> str:
    """Stop dracut copying FBL's casper cmdline into the installed initramfs."""
    overlay = os.path.join(root, "run", "fbl-kernel-cmdline")
    os.makedirs(os.path.dirname(overlay), exist_ok=True)
    with open(overlay, "w", encoding="ascii") as fh:
        fh.write(cmdline.strip() + "\n")
    dest = os.path.join(root, "proc", "cmdline")
    if not os.path.isfile(dest):
        return ""
    proc = subprocess.run(
        ["mount", "--bind", overlay, dest],
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        if log:
            log.write("could not pin /proc/cmdline")
        return ""
    if log:
        log.write("pinned chroot /proc/cmdline")
    return dest


def initramfs_contains_live(root: str) -> bool:
    ver = _vmlinuz_version(root)
    names = []
    if ver:
        names.append(f"initramfs-{ver}.img")
    names.extend(["initramfs.img", "initrd.img"])
    path = ""
    for name in names:
        cand = os.path.join(root, "boot", name)
        if os.path.isfile(cand):
            path = cand
            break
    if not path:
        return False
    try:
        if os.path.getsize(path) < 64:
            return False
        with open(path, "rb") as fh:
            blob = fh.read()
    except OSError:
        return False
    data = blob
    if blob.startswith(b"\x28\xb5\x2f\xfd"):
        proc = subprocess.run(
            ["zstd", "-d", "-c"], input=blob, check=False, capture_output=True
        )
        if proc.returncode == 0 and proc.stdout:
            data = proc.stdout
    elif blob[:2] == b"\x1f\x8b":
        import gzip

        try:
            data = gzip.decompress(blob)
        except OSError:
            pass
    return b"dmsquash-live" in data or b"rd.live" in data


def _module_vmlinuz(root: str, ver: str) -> str:
    for rel in (
        os.path.join("lib", "modules", ver, "vmlinuz"),
        os.path.join("usr", "lib", "modules", ver, "vmlinuz"),
        os.path.join("boot", f"vmlinuz-{ver}"),
    ):
        if os.path.isfile(os.path.join(root, rel)):
            return "/" + rel
    return f"/lib/modules/{ver}/vmlinuz"


def rebuild_initramfs(
    root: str, disk: InstalledDisk, log: InstallLog | None = None
) -> None:
    """kernel-install + grub2-mkconfig + dracut, as Anaconda does on hardware."""
    ver = _vmlinuz_version(root)
    if not ver:
        if log:
            log.write("no kernel version for dracut")
        if os.geteuid() == 0:
            raise OsInstallError(_("Could not build the boot files."))
        return
    strip_live_dracut_conf(root, log=log)
    cmdline = _root_kargs(disk)
    pinned = _pin_proc_cmdline(root, cmdline, log=log)
    try:
        vmlinuz = _module_vmlinuz(root, ver)
        code, _out = chroot_run(
            root,
            ["kernel-install", "add", ver, vmlinuz],
            log=log,
            timeout=300,
        )
        if code != 0 and log:
            log.write("kernel-install add failed; keeping written BLS")
        dest = os.path.join("/boot", f"initramfs-{ver}.img")
        code, _out = chroot_run(
            root,
            [
                "dracut",
                "--force",
                "--no-hostonly",
                "--persistent-policy",
                "by-uuid",
                "--fstab",
                "--kver",
                ver,
                "--kernel-cmdline",
                cmdline,
                "--omit",
                ",".join(LIVE_DRACUT_OMIT),
                dest,
            ],
            log=log,
            timeout=300,
        )
        if code != 0:
            if log:
                log.write("dracut failed")
            if os.geteuid() == 0:
                raise OsInstallError(_("Could not build the boot files."))
            return
        code, _out = chroot_run(
            root,
            ["grub2-mkconfig", "-o", "/etc/grub2.cfg"],
            log=log,
            timeout=120,
        )
        if code != 0:
            chroot_run(
                root,
                ["grub2-mkconfig", "-o", "/boot/grub2/grub.cfg"],
                log=log,
                timeout=120,
            )
    finally:
        if pinned:
            subprocess.run(["umount", pinned], check=False, capture_output=True)
    abs_dest = os.path.join(root, "boot", f"initramfs-{ver}.img")
    if not os.path.isfile(abs_dest) and os.geteuid() == 0:
        raise OsInstallError(_("Could not build the boot files."))
    if os.geteuid() == 0 and initramfs_contains_live(root):
        if log:
            log.write("initramfs still contains dmsquash-live")
        raise OsInstallError(_("Could not build the boot files."))


def mark_autorelabel(root: str, log: InstallLog | None = None) -> None:
    """Queue Fedora's first-boot relabel (fixfiles -F onboot).

    First Boot is Ubuntu: the kernel cannot store ``security.selinux``.
    Anaconda copies labels on a Fedora live kernel. RHEL 10 requires
    ``enforcing=0`` on that first boot so unlabeled files do not block
    systemd before ``selinux-autorelabel.service``.
    """
    path = os.path.join(root, ".autorelabel")
    with open(path, "w", encoding="ascii") as fh:
        fh.write("-F\n")
    script = os.path.join(root, "usr", "libexec", "selinux", "clear-relabel-kargs")
    os.makedirs(os.path.dirname(script), exist_ok=True)
    with open(script, "w", encoding="utf-8") as fh:
        fh.write(CLEAR_ENFORCING0)
    try:
        os.chmod(script, 0o755)
    except OSError:
        pass
    unit_dir = os.path.join(root, "etc", "systemd", "system")
    os.makedirs(unit_dir, exist_ok=True)
    unit = os.path.join(unit_dir, "clear-selinux-relabel-kargs.service")
    with open(unit, "w", encoding="utf-8") as fh:
        fh.write(CLEAR_ENFORCING0_UNIT)
    wants = os.path.join(unit_dir, "graphical.target.wants")
    os.makedirs(wants, exist_ok=True)
    link = os.path.join(wants, "clear-selinux-relabel-kargs.service")
    try:
        if os.path.lexists(link):
            os.unlink(link)
        os.symlink(
            "/etc/systemd/system/clear-selinux-relabel-kargs.service", link
        )
    except OSError:
        pass
    if log:
        log.write("queued SELinux relabel (/.autorelabel -F, enforcing=0)")


def disable_live_units(root: str, log: InstallLog | None = None) -> None:
    proc = subprocess.run(
        ["systemctl", f"--root={root}", "disable", "--now", *LIVE_UNITS],
        check=False,
        capture_output=True,
        text=True,
    )
    if log and proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()
        log.write(
            "systemctl disable livesys"
            + (f" ({tail[-1]})" if tail else f" rc={proc.returncode}")
        )


def configure_fedora(
    target_root: str,
    identity: OsIdentity,
    locale: InstallLocale,
    disk: InstalledDisk,
    *,
    display_manager: str,
    live_usernames: tuple[str, ...],
    timezone_minutes: int | None = None,
    log: InstallLog | None = None,
) -> None:
    write_fstab(target_root, disk)
    write_hostname(target_root, identity.hostname)
    new_machine_id(target_root)
    write_locale(target_root, locale)
    write_timezone(target_root, timezone_minutes, log=log)
    delete_users(target_root, live_usernames, log=log)
    add_user(target_root, identity, log=log)
    set_graphical_target(target_root, display_manager, log=log)
    write_grub_default(target_root)
    write_kernel_cmdline(target_root, disk)
    write_bls_entry(target_root, disk, log=log)
    write_grub2_cfg(target_root, disk, log=log)
    strip_live_session(target_root, log=log)
    disable_live_units(target_root, log=log)
    strip_live_dracut_conf(target_root, log=log)
    mounted = bind_chroot(target_root)
    try:
        rebuild_initramfs(target_root, disk, log=log)
        write_bls_entry(target_root, disk, log=log)
        write_grub2_cfg(target_root, disk, log=log)
        mark_autorelabel(target_root, log=log)
    finally:
        unbind_chroot(mounted)


def fedora_efi_paths(iso_mnt: str) -> tuple[str, str, str]:
    """Fedora shim + installed grubx64 + MokManager. Never gcdx64."""
    shim = grub = mm = ""
    pairs = (
        (
            os.path.join(iso_mnt, "EFI", "fedora", "shimx64.efi"),
            os.path.join(iso_mnt, "EFI", "fedora", "grubx64.efi"),
            os.path.join(iso_mnt, "EFI", "fedora", "mmx64.efi"),
        ),
        (
            os.path.join(iso_mnt, "EFI", "BOOT", "BOOTX64.EFI"),
            os.path.join(iso_mnt, "EFI", "BOOT", "grubx64.efi"),
            os.path.join(iso_mnt, "EFI", "BOOT", "mmx64.efi"),
        ),
        (
            os.path.join(iso_mnt, "efi", "fedora", "shimx64.efi"),
            os.path.join(iso_mnt, "efi", "fedora", "grubx64.efi"),
            os.path.join(iso_mnt, "efi", "fedora", "mmx64.efi"),
        ),
    )
    for cand_shim, cand_grub, cand_mm in pairs:
        if os.path.isfile(cand_shim) and os.path.isfile(cand_grub):
            shim, grub = cand_shim, cand_grub
            if os.path.isfile(cand_mm):
                mm = cand_mm
            break
    return shim, grub, mm


def write_esp_grub_stub(
    efi_mp: str,
    bootloader_id: str,
    root_uuid: str,
    log: InstallLog | None = None,
    boot_uuid: str = "",
) -> None:
    uuid = boot_uuid or root_uuid
    if not uuid:
        return
    if boot_uuid:
        text = (
            f"search.fs_uuid {boot_uuid} root\n"
            "set prefix=($root)/grub2\n"
            "configfile $prefix/grub.cfg\n"
        )
    else:
        text = (
            f"search.fs_uuid {root_uuid} root\n"
            "set prefix=($root)'/boot/grub2'\n"
            "configfile $prefix/grub.cfg\n"
        )
    for rel in (
        os.path.join("EFI", bootloader_id, "grub.cfg"),
        os.path.join("EFI", "BOOT", "grub.cfg"),
    ):
        path = os.path.join(efi_mp, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
    if log:
        log.write(f"wrote EFI/{bootloader_id}/grub.cfg stub uuid={uuid}")


def copy_fedora_esp_binaries(
    efi_mp: str,
    iso_mnt: str,
    bootloader_id: str,
    log: InstallLog | None = None,
) -> None:
    """Put Fedora's Microsoft-signed shim + Fedora grubx64 on the ESP.

    Canonical GRUB will not load a Fedora kernel with Secure Boot on.
    ``EFI/BOOT/`` is shim only — extra ``.efi`` there is a first-stage
    loader on Lenovo/Phoenix firmware.
    """
    src_shim, src_grub, src_mm = fedora_efi_paths(iso_mnt)
    if not src_shim or not src_grub:
        raise OsInstallError(_("Could not write the boot partition."))
    boot = os.path.join(efi_mp, "EFI", "BOOT")
    vendor = os.path.join(efi_mp, "EFI", bootloader_id)
    os.makedirs(boot, exist_ok=True)
    os.makedirs(vendor, exist_ok=True)
    shutil.copy2(src_shim, os.path.join(boot, "BOOTX64.EFI"))
    shutil.copy2(src_shim, os.path.join(vendor, "shimx64.efi"))
    shutil.copy2(src_grub, os.path.join(vendor, "grubx64.efi"))
    if src_mm:
        shutil.copy2(src_mm, os.path.join(vendor, "mmx64.efi"))
    for name in list(os.listdir(boot)):
        if name.lower() == "bootx64.efi":
            continue
        if name.lower().endswith(".efi"):
            try:
                os.unlink(os.path.join(boot, name))
            except OSError:
                pass
    if log:
        log.write(
            f"copied Fedora shim to EFI/BOOT and shim+grubx64.efi into EFI/{bootloader_id}"
        )


def install_fedora_bootloader(
    target_root: str,
    efi_mp: str,
    disk: InstalledDisk,
    iso_mnt: str,
    *,
    bootloader_id: str = "fedora",
    nvram_label: str = "Fedora",
    log: InstallLog | None = None,
) -> str:
    os.makedirs(efi_mp, exist_ok=True)
    write_bls_entry(target_root, disk, log=log)
    write_grub2_cfg(target_root, disk, log=log)
    mounted = bind_chroot(target_root)
    log_text: list[str] = []
    try:
        code, out = chroot_run(
            target_root,
            [
                "grub2-install",
                "--target=x86_64-efi",
                "--efi-directory=/boot/efi",
                f"--bootloader-id={bootloader_id}",
                "--recheck",
                "--no-nvram",
            ],
            log=log,
            timeout=180,
        )
        log_text.append(out)
        if code != 0 and log:
            log.write("grub2-install failed; using Fedora shim from the ISO")
        pinned = _pin_proc_cmdline(target_root, _root_kargs(disk), log=log)
        try:
            code, out = chroot_run(
                target_root,
                ["grub2-mkconfig", "-o", "/etc/grub2.cfg"],
                log=log,
                timeout=120,
            )
            log_text.append(out)
            if code != 0:
                chroot_run(
                    target_root,
                    ["grub2-mkconfig", "-o", "/boot/grub2/grub.cfg"],
                    log=log,
                    timeout=120,
                )
        finally:
            if pinned:
                subprocess.run(["umount", pinned], check=False, capture_output=True)
    finally:
        unbind_chroot(mounted)
    write_kernel_cmdline(target_root, disk)
    write_grub_default(target_root)
    write_bls_entry(target_root, disk, log=log)
    write_grub2_cfg(target_root, disk, log=log)
    copy_fedora_esp_binaries(efi_mp, iso_mnt, bootloader_id, log=log)
    write_esp_grub_stub(
        efi_mp,
        bootloader_id,
        disk.root_uuid,
        log=log,
        boot_uuid=disk.boot_uuid,
    )
    return "\n".join(t for t in log_text if t)


def health_check_fedora(
    target_root: str,
    efi_mp: str,
    identity: OsIdentity,
    disk: InstalledDisk,
    *,
    display_manager: str,
    boot_log: str = "",
) -> list[str]:
    fails = tree_health_check(
        target_root,
        efi_mp,
        identity,
        disk,
        display_manager=display_manager,
        boot_log=boot_log,
    )
    grub_cfg = os.path.join(target_root, "boot", "grub2", "grub.cfg")
    try:
        with open(grub_cfg, encoding="utf-8") as fh:
            grub = fh.read()
    except OSError:
        grub = ""
    has_entry = "blscfg" in grub or (
        "menuentry" in grub and "linux /vmlinuz" in grub
    )
    if not has_entry:
        fails.append("GRUB does not have a Fedora kernel entry.")
    bls_dir = os.path.join(target_root, "boot", "loader", "entries")
    bls_ok = False
    try:
        names = [n for n in os.listdir(bls_dir) if n.endswith(".conf")]
    except OSError:
        names = []
    for name in names:
        try:
            with open(os.path.join(bls_dir, name), encoding="utf-8") as fh:
                bls = fh.read()
        except OSError:
            continue
        if "linux /vmlinuz" in bls and "rd.live." not in bls:
            bls_ok = True
            break
    if not bls_ok:
        fails.append("No BLS entry for the installed kernel.")
    if initramfs_contains_live(target_root):
        fails.append("Initramfs still has the live image modules.")
    if not os.path.isfile(os.path.join(target_root, ".autorelabel")):
        fails.append("SELinux relabel is not queued.")
    else:
        labeled_ok = False
        for name in names:
            try:
                with open(os.path.join(bls_dir, name), encoding="utf-8") as fh:
                    if "enforcing=0" in fh.read():
                        labeled_ok = True
                        break
            except OSError:
                continue
        cmdline = os.path.join(target_root, "etc", "kernel", "cmdline")
        try:
            with open(cmdline, encoding="utf-8") as fh:
                if "enforcing=0" in fh.read():
                    labeled_ok = True
        except OSError:
            pass
        if not labeled_ok:
            fails.append("SELinux relabel is queued without enforcing=0.")
    return fails
