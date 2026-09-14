"""CachyOS live-ISO unpack (archiso ``arch/x86_64/airootfs.sfs``).

Follow CachyOS *offline* Calamares: unpack the live squashfs, do not
pacstrap, do not reboot into Calamares. Layout is ESP at ``/boot`` and
btrfs subvolumes ``@`` ``@home`` ``@root`` ``@srv`` ``@cache`` ``@tmp``
``@log``. Limine is not on the desktop ISO; offline unpack uses
systemd-boot. Pin a dated desktop ISO; do not ``pacman -Syu`` during
install.

Plasma is the live ISO desktop. Do not reuse this file for Handheld or
other CachyOS snapshots that change unpack or bootloader.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from collections.abc import Callable

from firstboot.disk import part_path
from firstboot.i18n import _
from firstboot.install import blkid_uuid, wait_dev
from firstboot.installlocale import InstallLocale
from firstboot.osinstall.casper import unpack_squashfs
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
    new_machine_id,
    read_text,
    run_checked,
    set_graphical_target,
    umount_path,
    unbind_chroot,
    write_hostname,
)

CACHYOS_ESP_MIB = 4096
BTRFS_ROOT_OPTS = "subvol=/@,compress=zstd:1,noatime"
BTRFS_COMPRESS = "compress=zstd:1,noatime"
MKINITCPIO_TIMEOUT = 1800

# CachyOS Calamares mount.conf btrfsSubvolumes (Limine default).
SUBVOLUMES = (
    ("@", "/"),
    ("@home", "/home"),
    ("@root", "/root"),
    ("@srv", "/srv"),
    ("@cache", "/var/cache"),
    ("@tmp", "/var/tmp"),
    ("@log", "/var/log"),
)

LIVE_DESKTOPS = (
    "calamares.desktop",
    "calamares-install-cachyos.desktop",
)
LIVE_UNITS = (
    "pacman-init.service",
    "livecd.service",
    "calamares.service",
    "etc-pacman.d-gnupg.mount",
)
LIVE_SUDOERS = ("live", "liveuser", "00-live", "g_wheel")
LIVE_POLKIT = (
    "49-nopasswd_global.rules",
    "49-nopasswd-calamares.rules",
)
# Calamares users.conf defaultGroups plus live-ISO extras that exist on 260809.
CACHYOS_USER_GROUPS = (
    "wheel",
    "rfkill",
    "sys",
    "users",
    "lp",
    "video",
    "network",
    "storage",
    "audio",
    "power",
    "optical",
    "adm",
)
SUDOERS_INSTALLER = "10-installer"
SUDOERS_WHEEL_LINE = "%wheel ALL=(ALL) ALL\n"
PACMAN_KEY_TIMEOUT = 300
# Desktop ISO ships nvidia-open for both kernels so the live session can
# boot NVIDIA boxes. Calamares removeun drops them when chwd sees no card.
NVIDIA_PCI_VENDOR = "0x10de"
NVIDIA_LIVE_PACKAGES = (
    "linux-cachyos-nvidia-open",
    "linux-cachyos-lts-nvidia-open",
    "nvidia-utils",
    "opencl-nvidia",
    "lib32-nvidia-utils",
    "lib32-opencl-nvidia",
    "nvidia-settings",
    "egl-wayland",
)

_SDDM_AUTOLOGIN_RE = re.compile(r"(?im)^(User|Session|Relogin)\s*=.*\n?")

INSTALLED_HOOKS = (
    "base systemd autodetect microcode kms modconf block "
    "keyboard sd-vconsole filesystems fsck"
)


def _live_hint(iso_mnt: str) -> str:
    arch = os.path.join(iso_mnt, "arch", "x86_64")
    if not os.path.isdir(arch):
        return "No arch/x86_64 directory on the image."
    try:
        names = sorted(os.listdir(arch))
    except OSError:
        names = []
    shown = ", ".join(names[:8])
    extra = "" if len(names) <= 8 else f" (+{len(names) - 8} more)"
    return f"arch/x86_64/ has {shown}{extra}."


def cachyos_live_relpaths(iso_mnt: str) -> list[str]:
    """Offline Calamares unpackfs source. Do not unpack a bootstrap tarball."""
    rel = os.path.join("arch", "x86_64", "airootfs.sfs")
    if os.path.isfile(os.path.join(iso_mnt, rel)):
        return [rel]
    raise OsInstallError("This image is not a live ISO. " + _live_hint(iso_mnt))


def iso_extras(iso_mnt: str) -> dict[str, str]:
    """Kernels and microcode live next to airootfs, not inside it."""
    extra: dict[str, str] = {}
    boot = os.path.join(iso_mnt, "arch", "boot")
    x86 = os.path.join(boot, "x86_64")
    if os.path.isdir(x86):
        try:
            names = os.listdir(x86)
        except OSError:
            names = []
        for name in names:
            if not name.startswith("vmlinuz"):
                continue
            path = os.path.join(x86, name)
            if os.path.isfile(path):
                extra[os.path.join("arch", "boot", "x86_64", name)] = path
    if os.path.isdir(boot):
        for name in ("intel-ucode.img", "amd-ucode.img"):
            path = os.path.join(boot, name)
            if os.path.isfile(path):
                extra[os.path.join("arch", "boot", name)] = path
    return extra


def partition_cachyos_disk(
    disk_path: str, work: str, log: InstallLog | None = None
) -> InstalledDisk:
    """CachyOS Limine layout: 4 GiB ESP at /boot, btrfs with snapper subvolumes."""
    leftover = casper_loops_on_disk(disk_path)
    if leftover:
        if log:
            log.write("casper loop still on disk: " + " ".join(leftover))
        raise disk_busy_error()
    subprocess.run(["swapoff", "-a"], check=False, capture_output=True)
    if log:
        log.write(f"wipe {disk_path} (CachyOS ESP@/boot + btrfs)")
    run_checked(["wipefs", "-a", "-f", disk_path], what=f"wipe {disk_path}")
    run_checked(["sgdisk", "--zap-all", disk_path], what="clear GPT")
    run_checked(
        [
            "sgdisk",
            f"--new=1:1M:+{CACHYOS_ESP_MIB}M",
            "--typecode=1:EF00",
            "--change-name=1:EFI",
            "--new=2:0:0",
            "--typecode=2:8300",
            "--change-name=2:cachyos",
            disk_path,
        ],
        what="create CachyOS partitions",
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
        ["mkfs.btrfs", "-f", "-q", "-L", "cachyos", root_dev],
        what="format btrfs",
    )
    top = os.path.join(work, "btrfs")
    root_mp = os.path.join(work, "root")
    os.makedirs(top, exist_ok=True)
    os.makedirs(root_mp, exist_ok=True)
    run_checked(["mount", root_dev, top], what="mount btrfs")
    try:
        for name, _mp in SUBVOLUMES:
            run_checked(
                ["btrfs", "subvolume", "create", os.path.join(top, name)],
                what=f"create btrfs subvolume {name}",
            )
    finally:
        umount_path(top)
    run_checked(
        ["mount", "-o", BTRFS_ROOT_OPTS, root_dev, root_mp],
        what="mount btrfs root",
    )
    for name, mp in SUBVOLUMES:
        if mp == "/":
            continue
        dest = os.path.join(root_mp, mp.lstrip("/"))
        os.makedirs(dest, exist_ok=True)
        run_checked(
            [
                "mount",
                "-o",
                f"subvol=/{name},{BTRFS_COMPRESS}",
                root_dev,
                dest,
            ],
            what=f"mount btrfs {mp}",
        )
    root_dir = os.path.join(root_mp, "root")
    try:
        os.chmod(root_dir, 0o750)
    except OSError:
        pass
    tmp_dir = os.path.join(root_mp, "var", "tmp")
    try:
        os.chmod(tmp_dir, 0o1777)
    except OSError:
        pass
    boot_mp = os.path.join(root_mp, "boot")
    os.makedirs(boot_mp, exist_ok=True)
    run_checked(["mount", esp_dev, boot_mp], what="mount ESP at /boot")
    if log:
        log.write(f"partitioned {disk_path} esp={esp_dev} root={root_dev}")
    return InstalledDisk(
        disk=disk_path,
        esp_dev=esp_dev,
        root_dev=root_dev,
        esp_uuid=blkid_uuid(esp_dev),
        root_uuid=blkid_uuid(root_dev),
        esp_mp=boot_mp,
        root_mp=root_mp,
        boot_mp=boot_mp,
        root_fstype="btrfs",
        root_fsopts=BTRFS_ROOT_OPTS,
    )


def unpack_cachyos(
    iso_mnt: str,
    target_root: str,
    *,
    on_progress: Callable[[int], None] | None = None,
    log: InstallLog | None = None,
) -> None:
    rels = cachyos_live_relpaths(iso_mnt)
    paths = [os.path.join(iso_mnt, rel) for rel in rels]
    if log:
        log.write("unpack " + " ".join(os.path.basename(p) for p in paths))
    unpack_squashfs(paths[0], target_root, on_progress=on_progress, log=log)
    _copy_iso_boot_files(iso_mnt, target_root, log=log)
    copy_module_kernels(target_root, log=log)
    if on_progress:
        on_progress(100)


def _copy_iso_boot_files(
    iso_mnt: str, target_root: str, log: InstallLog | None = None
) -> None:
    boot = os.path.join(target_root, "boot")
    os.makedirs(boot, exist_ok=True)
    extras = iso_extras(iso_mnt)
    for rel, src in extras.items():
        dest = os.path.join(boot, os.path.basename(src))
        try:
            shutil.copy2(src, dest)
            if log:
                log.write(f"copied {rel} into /boot")
        except OSError as exc:
            if log:
                log.write(f"could not copy {rel}: {exc}")


def write_cachyos_fstab(root: str, disk: InstalledDisk) -> None:
    path = os.path.join(root, "etc", "fstab")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    lines = [
        "# /etc/fstab: static file system information.",
        f"UUID={disk.root_uuid} / btrfs {BTRFS_ROOT_OPTS} 0 0",
    ]
    for name, mp in SUBVOLUMES:
        if mp == "/":
            continue
        lines.append(
            f"UUID={disk.root_uuid} {mp} btrfs subvol=/{name},{BTRFS_COMPRESS} 0 0"
        )
    lines.append(f"UUID={disk.esp_uuid} /boot vfat defaults,umask=0077 0 2")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def root_kargs(disk: InstalledDisk) -> str:
    return (
        f"root=UUID={disk.root_uuid} rootfstype=btrfs "
        f"rootflags={BTRFS_ROOT_OPTS} rw quiet nowatchdog"
    )


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
    enable_locale_gen(root, locale.glibc)


def enable_locale_gen(root: str, glibc: str) -> None:
    """Uncomment glibc in locale.gen. Arch ships every locale commented."""
    if not glibc:
        return
    gen = os.path.join(root, "etc", "locale.gen")
    text = read_text(gen) if os.path.isfile(gen) else ""
    lines = text.splitlines() if text else []
    found = False
    out: list[str] = []
    for line in lines:
        stripped = line.lstrip("# ").strip()
        if stripped.startswith(glibc):
            out.append(f"{glibc} UTF-8")
            found = True
        else:
            out.append(line)
    if not found:
        out.append(f"{glibc} UTF-8")
    os.makedirs(os.path.dirname(gen), exist_ok=True)
    with open(gen, "w", encoding="utf-8") as fh:
        fh.write("\n".join(out).rstrip() + "\n")


def locale_gen_enabled(root: str, glibc: str) -> bool:
    if not glibc:
        return False
    for line in read_text(os.path.join(root, "etc", "locale.gen")).splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or not stripped:
            continue
        if stripped.startswith(glibc):
            return True
    return False


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


def _strip_autologin_file(path: str) -> None:
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    new = _SDDM_AUTOLOGIN_RE.sub("", text)
    if new != text:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(new)


def _strip_dm_dropins(root: str, rel_conf: str, rel_drop: str) -> None:
    _strip_autologin_file(os.path.join(root, rel_conf))
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
        if "live" in lower or "autologin" in lower:
            try:
                os.unlink(path)
            except OSError:
                pass
        else:
            _strip_autologin_file(path)


def strip_live_session(root: str, log: InstallLog | None = None) -> None:
    for conf, drop in (
        (os.path.join("etc", "sddm.conf"), os.path.join("etc", "sddm.conf.d")),
        (os.path.join("etc", "plasmalogin.conf"), os.path.join("etc", "plasmalogin.conf.d")),
        (os.path.join("etc", "plasma-login.conf"), os.path.join("etc", "plasma-login.conf.d")),
    ):
        _strip_dm_dropins(root, conf, drop)
    autostart = os.path.join(root, "etc", "xdg", "autostart")
    apps = os.path.join(root, "usr", "share", "applications")
    for folder in (autostart, apps):
        if not os.path.isdir(folder):
            continue
        try:
            names = os.listdir(folder)
        except OSError:
            names = []
        for name in names:
            lower = name.lower()
            if name in LIVE_DESKTOPS or "calamares" in lower:
                try:
                    os.unlink(os.path.join(folder, name))
                except OSError:
                    pass
    calamares = os.path.join(root, "etc", "calamares")
    if os.path.isdir(calamares):
        shutil.rmtree(calamares, ignore_errors=True)
    drop = os.path.join(root, "etc", "sudoers.d")
    if os.path.isdir(drop):
        try:
            names = os.listdir(drop)
        except OSError:
            names = []
        for name in names:
            lower = name.lower()
            if name in LIVE_SUDOERS or "live" in lower:
                try:
                    os.unlink(os.path.join(drop, name))
                    if log:
                        log.write(f"removed sudoers.d/{name}")
                except OSError:
                    pass
    strip_live_polkit(root, log=log)
    if log:
        log.write("stripped CachyOS live session")


def strip_live_polkit(root: str, log: InstallLog | None = None) -> None:
    """Live ISO gives wheel every polkit action with no password. Calamares deletes it."""
    drop = os.path.join(root, "etc", "polkit-1", "rules.d")
    if not os.path.isdir(drop):
        return
    try:
        names = os.listdir(drop)
    except OSError:
        return
    for name in names:
        lower = name.lower()
        if name in LIVE_POLKIT or "nopasswd" in lower:
            try:
                os.unlink(os.path.join(drop, name))
                if log:
                    log.write(f"removed polkit-1/rules.d/{name}")
            except OSError:
                pass


def write_sudoers_wheel(root: str, log: InstallLog | None = None) -> None:
    """Calamares users sudoersGroup=wheel → /etc/sudoers.d/10-installer.

    Arch /etc/sudoers leaves %wheel commented. Live g_wheel is NOPASSWD and
    must not survive; this password-required rule is the installed grant.
    """
    drop = os.path.join(root, "etc", "sudoers.d")
    os.makedirs(drop, exist_ok=True)
    path = os.path.join(drop, SUDOERS_INSTALLER)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(SUDOERS_WHEEL_LINE)
    try:
        os.chmod(path, 0o440)
    except OSError:
        pass
    if log:
        log.write(f"wrote sudoers.d/{SUDOERS_INSTALLER}")


def add_user_groups(
    root: str,
    username: str,
    groups: tuple[str, ...],
    log: InstallLog | None = None,
) -> None:
    if not username or not groups:
        return
    group_path = os.path.join(root, "etc", "group")
    present: set[str] = set()
    for line in read_text(group_path).splitlines():
        name = line.split(":", 1)[0]
        if name:
            present.add(name)
    extra_set = {name for name in groups if name in present}
    if not extra_set:
        return
    out: list[str] = []
    added: list[str] = []
    for line in read_text(group_path).splitlines():
        parts = line.split(":")
        if len(parts) < 4:
            out.append(line)
            continue
        members = [m for m in parts[3].split(",") if m]
        if parts[0] in extra_set and username not in members:
            members.append(username)
            added.append(parts[0])
        parts[3] = ",".join(members)
        out.append(":".join(parts))
    with open(group_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(out) + "\n")
    if log and added:
        log.write("groups " + ",".join(added))


def group_has_user(root: str, group: str, username: str) -> bool:
    for line in read_text(os.path.join(root, "etc", "group")).splitlines():
        parts = line.split(":")
        if len(parts) < 4 or parts[0] != group:
            continue
        return username in [m for m in parts[3].split(",") if m]
    return False


def sudoers_wheel_ok(root: str) -> bool:
    path = os.path.join(root, "etc", "sudoers.d", SUDOERS_INSTALLER)
    if not os.path.isfile(path):
        return False
    for line in read_text(path).splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or not stripped:
            continue
        if stripped.startswith("%wheel") and "ALL" in stripped and "NOPASSWD" not in stripped:
            return True
    return False


def pci_has_nvidia(sysfs: str = "/sys") -> bool:
    """True if any PCI device reports NVIDIA's vendor id."""
    devices = os.path.join(sysfs, "bus", "pci", "devices")
    if not os.path.isdir(devices):
        return False
    try:
        names = os.listdir(devices)
    except OSError:
        return False
    for name in names:
        path = os.path.join(devices, name, "vendor")
        try:
            with open(path, encoding="ascii") as fh:
                vendor = fh.read().strip().lower()
        except OSError:
            continue
        if vendor == NVIDIA_PCI_VENDOR:
            return True
    return False


def remove_live_nvidia_packages(
    root: str,
    log: InstallLog | None = None,
    *,
    sysfs: str = "/sys",
) -> None:
    """Calamares ``removeun``: drop live ISO nvidia pkgs when there is no GPU."""
    if pci_has_nvidia(sysfs):
        if log:
            log.write("NVIDIA GPU present; keeping live nvidia packages")
        return
    if os.geteuid() != 0 or not shutil.which("chroot"):
        if log:
            log.write("skip nvidia package removal (not root)")
        return
    if not os.path.isfile(os.path.join(root, "usr", "bin", "pacman")):
        return
    if log:
        log.write("no NVIDIA GPU; removing live ISO nvidia packages")
    for name in NVIDIA_LIVE_PACKAGES:
        chroot_run(
            root,
            ["pacman", "-Rsnc", "--noconfirm", "--noprogressbar", name],
            log=log,
            timeout=180,
        )


def init_pacman_keyring(root: str, log: InstallLog | None = None) -> None:
    """Populate gnupg in the chroot. Unpack is airootfs.sfs, not the live overlay."""
    systemd = os.path.join(root, "etc", "systemd", "system")
    mount = os.path.join(systemd, "etc-pacman.d-gnupg.mount")
    try:
        os.unlink(mount)
        if log:
            log.write("removed etc-pacman.d-gnupg.mount")
    except OSError:
        pass
    if os.geteuid() != 0 or not shutil.which("chroot"):
        if log:
            log.write("skip pacman-key (not root)")
        return
    if not os.path.isfile(os.path.join(root, "usr", "bin", "pacman-key")):
        return
    code, _out = chroot_run(
        root, ["pacman-key", "--init"], log=log, timeout=PACMAN_KEY_TIMEOUT
    )
    if code != 0:
        if log:
            log.write("pacman-key --init failed")
        return
    code, _out = chroot_run(
        root, ["pacman-key", "--populate"], log=log, timeout=PACMAN_KEY_TIMEOUT
    )
    if code != 0 and log:
        log.write("pacman-key --populate failed")


def disable_live_units(root: str, log: InstallLog | None = None) -> None:
    systemd = os.path.join(root, "etc", "systemd", "system")
    if not os.path.isdir(systemd):
        return
    for dirpath, _dirnames, filenames in os.walk(systemd):
        if not dirpath.endswith(".wants"):
            continue
        for name in filenames:
            if name in LIVE_UNITS or name.startswith("live"):
                try:
                    os.unlink(os.path.join(dirpath, name))
                except OSError:
                    pass
    for name in LIVE_UNITS:
        path = os.path.join(systemd, name)
        try:
            os.unlink(path)
        except OSError:
            pass
    getty = os.path.join(systemd, "getty@tty1.service.d")
    if os.path.isdir(getty):
        shutil.rmtree(getty, ignore_errors=True)
    if log:
        log.write("disabled CachyOS live units")


def enable_units(root: str, units: tuple[str, ...], log: InstallLog | None = None) -> None:
    for unit in units:
        base = unit if unit.endswith(".service") or unit.endswith(".timer") else f"{unit}.service"
        present = False
        for rel in (
            os.path.join("usr", "lib", "systemd", "system", base),
            os.path.join("lib", "systemd", "system", base),
        ):
            if os.path.isfile(os.path.join(root, rel)):
                present = True
                break
        if not present:
            continue
        wants = os.path.join(root, "etc", "systemd", "system", "multi-user.target.wants")
        os.makedirs(wants, exist_ok=True)
        dest = os.path.join(wants, base)
        if not os.path.exists(dest):
            try:
                os.symlink(os.path.join("/usr/lib/systemd/system", base), dest)
            except OSError:
                pass
        if log:
            log.write(f"enabled {base}")


def write_mkinitcpio_conf(root: str, log: InstallLog | None = None) -> None:
    """Drop archiso live presets. Keep the ISO's installed HOOKS line."""
    path = os.path.join(root, "etc", "mkinitcpio.conf")
    text = read_text(path)
    lines = text.splitlines() if text else []
    out: list[str] = []
    seen = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("HOOKS="):
            seen = True
            if "archiso" in stripped:
                out.append(f"HOOKS=({INSTALLED_HOOKS})")
            else:
                out.append(line)
        else:
            out.append(line)
    if not seen:
        out.append(f"HOOKS=({INSTALLED_HOOKS})")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(out).rstrip() + "\n")
    drop = os.path.join(root, "etc", "mkinitcpio.conf.d")
    if os.path.isdir(drop):
        try:
            names = os.listdir(drop)
        except OSError:
            names = []
        for name in names:
            lower = name.lower()
            if "archiso" in lower or "live" in lower:
                try:
                    os.unlink(os.path.join(drop, name))
                    if log:
                        log.write(f"removed mkinitcpio.conf.d/{name}")
                except OSError:
                    pass
    presets = os.path.join(root, "etc", "mkinitcpio.d")
    if os.path.isdir(presets):
        try:
            names = os.listdir(presets)
        except OSError:
            names = []
        for name in names:
            path_p = os.path.join(presets, name)
            if not os.path.isfile(path_p):
                continue
            body = read_text(path_p).lower()
            if "archiso" in body or "archiso" in name.lower():
                try:
                    os.unlink(path_p)
                    if log:
                        log.write(f"removed mkinitcpio.d/{name}")
                except OSError:
                    pass
    if log:
        log.write("stripped archiso mkinitcpio presets")


def _pin_proc_cmdline(root: str, cmdline: str, log: InstallLog | None = None) -> str:
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


def copy_module_kernels(root: str, log: InstallLog | None = None) -> list[str]:
    """Copy pkgbase vmlinuz files onto /boot (ESP). Presets expect those names."""
    boot = os.path.join(root, "boot")
    os.makedirs(boot, exist_ok=True)
    mods = os.path.join(root, "usr", "lib", "modules")
    copied: list[str] = []
    if not os.path.isdir(mods):
        return copied
    try:
        versions = os.listdir(mods)
    except OSError:
        return copied
    for ver in versions:
        pkgbase_path = os.path.join(mods, ver, "pkgbase")
        src = os.path.join(mods, ver, "vmlinuz")
        if not os.path.isfile(src) or not os.path.isfile(pkgbase_path):
            continue
        name = read_text(pkgbase_path).strip()
        if not name:
            continue
        dest = os.path.join(boot, f"vmlinuz-{name}")
        try:
            shutil.copy2(src, dest)
            copied.append(name)
            if log:
                log.write(f"copied {ver} vmlinuz to /boot/vmlinuz-{name}")
        except OSError as exc:
            if log:
                log.write(f"could not copy {ver} vmlinuz: {exc}")
    return copied


def mkinitcpio_presets(root: str) -> list[str]:
    folder = os.path.join(root, "etc", "mkinitcpio.d")
    if not os.path.isdir(folder):
        return []
    try:
        names = os.listdir(folder)
    except OSError:
        return []
    out: list[str] = []
    for name in sorted(names):
        if not name.endswith(".preset"):
            continue
        if "archiso" in name.lower():
            continue
        out.append(name[: -len(".preset")])
    return out


def rebuild_initramfs(
    root: str, disk: InstalledDisk, log: InstallLog | None = None
) -> None:
    write_mkinitcpio_conf(root, log=log)
    copy_module_kernels(root, log=log)
    if os.geteuid() != 0:
        if log:
            log.write("skip mkinitcpio (not root)")
        return
    if not shutil.which("chroot"):
        raise OsInstallError(_("Could not build the boot files."))
    presets = mkinitcpio_presets(root)
    if not presets:
        raise OsInstallError(_("Could not build the boot files."))
    cmdline = root_kargs(disk)
    pinned = _pin_proc_cmdline(root, cmdline, log=log)
    ok = 0
    last_out = ""
    try:
        for preset in presets:
            code, out = chroot_run(
                root,
                ["mkinitcpio", "-p", preset],
                log=log,
                timeout=MKINITCPIO_TIMEOUT,
            )
            last_out = out
            if code == 0:
                ok += 1
            elif log:
                log.write(f"mkinitcpio -p {preset} failed")
    finally:
        if pinned:
            subprocess.run(["umount", pinned], check=False, capture_output=True)
    if ok == 0:
        if log:
            log.write(last_out[-2000:] if last_out else "mkinitcpio failed")
        raise OsInstallError(_("Could not build the boot files."))


def find_systemd_boot_efi(root: str) -> str:
    for rel in (
        os.path.join("usr", "lib", "systemd", "boot", "efi", "systemd-bootx64.efi"),
        os.path.join("usr", "lib", "systemd", "boot", "efi", "systemd-bootx64.efi.signed"),
    ):
        path = os.path.join(root, rel)
        if os.path.isfile(path):
            return path
    return ""


def write_loader_entries(
    efi_mp: str,
    disk: InstalledDisk,
    log: InstallLog | None = None,
    kernel_dir: str = "",
) -> None:
    boot = kernel_dir or efi_mp
    kernels: list[str] = []
    initrds: list[str] = []
    ucode: list[str] = []
    try:
        names = os.listdir(boot)
    except OSError:
        names = []
    for name in sorted(names):
        lower = name.lower()
        path = os.path.join(boot, name)
        if not os.path.isfile(path):
            continue
        if lower.startswith("vmlinuz"):
            kernels.append(name)
        elif lower.startswith("initramfs") and lower.endswith(".img"):
            initrds.append(name)
        elif lower.endswith("-ucode.img"):
            ucode.append(name)
    if not kernels:
        return
    entries = os.path.join(efi_mp, "loader", "entries")
    os.makedirs(entries, exist_ok=True)
    cmdline = root_kargs(disk)
    default = ""
    for kernel in kernels:
        stem = kernel.replace("vmlinuz-", "")
        ident = stem.replace("linux-", "") or "cachyos"
        title = "CachyOS LTS" if "lts" in kernel.lower() else "CachyOS"
        initrd = f"initramfs-{stem}.img"
        if initrd not in initrds:
            initrd = next((c for c in initrds if stem and stem in c), "")
            if not initrd and initrds:
                initrd = initrds[0]
        lines = [f"title {title}", f"linux /{kernel}"]
        for u in ucode:
            lines.append(f"initrd /{u}")
        if initrd:
            lines.append(f"initrd /{initrd}")
        lines.append(f"options {cmdline}")
        path = os.path.join(entries, f"{ident}.conf")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
        if not default and "lts" not in kernel.lower():
            default = f"{ident}.conf"
    if not default and kernels:
        default = os.path.basename(os.listdir(entries)[0]) if os.listdir(entries) else ""
    loader_dir = os.path.join(efi_mp, "loader")
    os.makedirs(loader_dir, exist_ok=True)
    with open(os.path.join(loader_dir, "loader.conf"), "w", encoding="utf-8") as fh:
        fh.write("timeout 5\nconsole-mode keep\n")
        if default:
            fh.write(f"default {default}\n")
    if log:
        log.write(f"wrote systemd-boot entries kernels={','.join(kernels)}")


def copy_systemd_esp(
    efi_mp: str,
    target_root: str,
    bootloader_id: str,
    log: InstallLog | None = None,
) -> None:
    src = find_systemd_boot_efi(target_root)
    if not src:
        raise OsInstallError(_("Could not write the boot partition."))
    boot = os.path.join(efi_mp, "EFI", "BOOT")
    vendor = os.path.join(efi_mp, "EFI", bootloader_id)
    systemd = os.path.join(efi_mp, "EFI", "systemd")
    os.makedirs(boot, exist_ok=True)
    os.makedirs(vendor, exist_ok=True)
    os.makedirs(systemd, exist_ok=True)
    shutil.copy2(src, os.path.join(boot, "BOOTX64.EFI"))
    shutil.copy2(src, os.path.join(vendor, "systemd-bootx64.efi"))
    shutil.copy2(src, os.path.join(systemd, "systemd-bootx64.efi"))
    for name in list(os.listdir(boot)):
        if name.lower() == "bootx64.efi":
            continue
        if name.lower().endswith(".efi"):
            try:
                os.unlink(os.path.join(boot, name))
            except OSError:
                pass
    if log:
        log.write(f"copied systemd-boot to EFI/{bootloader_id} and EFI/BOOT")


def install_cachyos_bootloader(
    target_root: str,
    efi_mp: str,
    disk: InstalledDisk,
    iso_mnt: str,
    *,
    bootloader_id: str = "cachyos",
    nvram_label: str = "CachyOS",
    log: InstallLog | None = None,
) -> str:
    del iso_mnt, nvram_label
    os.makedirs(efi_mp, exist_ok=True)
    copy_module_kernels(target_root, log=log)
    copy_systemd_esp(efi_mp, target_root, bootloader_id, log=log)
    write_loader_entries(
        efi_mp,
        disk,
        log=log,
        kernel_dir=os.path.join(target_root, "boot"),
    )
    mounted = bind_chroot(target_root)
    log_text: list[str] = []
    try:
        if (
            shutil.which("chroot")
            and os.geteuid() == 0
            and os.path.isfile(os.path.join(target_root, "usr", "bin", "bootctl"))
        ):
            code, out = chroot_run(
                target_root,
                [
                    "bootctl",
                    "install",
                    "--esp-path=/boot",
                    "--no-variables",
                ],
                log=log,
                timeout=120,
            )
            log_text.append(out)
            if code != 0:
                copy_systemd_esp(efi_mp, target_root, bootloader_id, log=log)
    finally:
        unbind_chroot(mounted)
    write_loader_entries(
        efi_mp,
        disk,
        log=log,
        kernel_dir=os.path.join(target_root, "boot"),
    )
    return "\n".join(t for t in log_text if t)


PKG_SUFFIXES = (".pkg.tar.zst", ".pkg.tar.xz")


def staged_package_files(extras_dir: str) -> list[str]:
    if not extras_dir or not os.path.isdir(extras_dir):
        return []
    try:
        names = os.listdir(extras_dir)
    except OSError:
        return []
    out: list[str] = []
    for name in sorted(names):
        if not name.endswith(PKG_SUFFIXES):
            continue
        path = os.path.join(extras_dir, name)
        if os.path.isfile(path):
            out.append(path)
    return out


def install_staged_packages(
    target_root: str,
    extras_dir: str,
    log: InstallLog | None = None,
) -> None:
    files = staged_package_files(extras_dir)
    if not files:
        if log:
            log.write(f"no extra packages in {extras_dir or '(none)'}")
        raise OsInstallError(_("Could not install extra packages."))
    if os.geteuid() != 0 or not shutil.which("chroot"):
        if log:
            log.write("skip staged packages (not root)")
        return
    pacman = os.path.join(target_root, "usr", "bin", "pacman")
    if not os.path.isfile(pacman):
        raise OsInstallError(_("Could not install extra packages."))
    dest = os.path.join(target_root, "var", "cache", "fbl-pkgs")
    os.makedirs(dest, exist_ok=True)
    proc = subprocess.run(
        ["mount", "--bind", extras_dir, dest],
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        if log:
            err = (proc.stderr or proc.stdout or "").strip()
            log.write(f"bind extras failed: {err or proc.returncode}")
        raise OsInstallError(_("Could not install extra packages."))
    try:
        names = [
            os.path.join("/var/cache/fbl-pkgs", os.path.basename(path)) for path in files
        ]
        if log:
            log.write("pacman -U " + " ".join(os.path.basename(p) for p in files))
        code, _out = chroot_run(
            target_root,
            ["pacman", "-U", "--noconfirm", "--needed", "--noprogressbar", *names],
            log=log,
            timeout=600,
        )
        if code != 0:
            raise OsInstallError(_("Could not install extra packages."))
    finally:
        subprocess.run(["umount", dest], check=False, capture_output=True)
        subprocess.run(["umount", "-l", dest], check=False, capture_output=True)


def configure_cachyos(
    target_root: str,
    identity: OsIdentity,
    locale: InstallLocale,
    disk: InstalledDisk,
    *,
    display_manager: str,
    live_usernames: tuple[str, ...],
    timezone_minutes: int | None = None,
    extras_dir: str = "",
    log: InstallLog | None = None,
) -> None:
    write_cachyos_fstab(target_root, disk)
    write_hostname(target_root, identity.hostname)
    new_machine_id(target_root)
    write_locale(target_root, locale)
    write_timezone(target_root, timezone_minutes, log=log)
    delete_users(target_root, live_usernames, log=log)
    add_user(target_root, identity, log=log)
    add_user_groups(target_root, identity.username, CACHYOS_USER_GROUPS, log=log)
    set_graphical_target(target_root, display_manager, log=log)
    strip_live_session(target_root, log=log)
    write_sudoers_wheel(target_root, log=log)
    disable_live_units(target_root, log=log)
    enable_units(
        target_root,
        ("NetworkManager", "systemd-timesyncd", "fstrim.timer", "bluetooth"),
        log=log,
    )
    if log:
        log.write(f"extras_dir={extras_dir or '(none)'}")
    mounted = bind_chroot(target_root)
    try:
        if os.geteuid() == 0:
            code, _out = chroot_run(
                target_root, ["locale-gen"], log=log, timeout=120
            )
            if code != 0:
                raise OsInstallError(_("Could not set the language."))
        install_staged_packages(target_root, extras_dir, log=log)
        remove_live_nvidia_packages(target_root, log=log)
        init_pacman_keyring(target_root, log=log)
        rebuild_initramfs(target_root, disk, log=log)
    finally:
        unbind_chroot(mounted)


def health_check_cachyos(
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
    fstab = read_text(os.path.join(target_root, "etc", "fstab"))
    if "subvol=/@" not in fstab and "subvol=@" not in fstab:
        fails.append("fstab is missing the CachyOS btrfs root subvolume.")
    if disk.esp_uuid and "/boot " not in fstab.replace("\t", " "):
        fails.append("fstab does not mount the ESP at /boot.")
    mk = read_text(os.path.join(target_root, "etc", "mkinitcpio.conf"))
    if "archiso" in mk:
        fails.append("mkinitcpio.conf still has archiso hooks.")
    locale_conf = read_text(os.path.join(target_root, "etc", "locale.conf"))
    lang = ""
    for line in locale_conf.splitlines():
        if line.startswith("LANG="):
            lang = line.split("=", 1)[1].strip().strip('"')
            break
    if lang and not locale_gen_enabled(target_root, lang):
        fails.append("locale.gen does not enable the installed language.")
    if not sudoers_wheel_ok(target_root):
        fails.append("sudoers is missing the wheel rule.")
    if os.path.isfile(os.path.join(target_root, "etc", "sudoers.d", "g_wheel")):
        fails.append("Live NOPASSWD sudoers is still present.")
    if os.path.isfile(
        os.path.join(
            target_root, "etc", "polkit-1", "rules.d", "49-nopasswd_global.rules"
        )
    ):
        fails.append("Live polkit NOPASSWD rule is still present.")
    if identity.username and not group_has_user(
        target_root, "wheel", identity.username
    ):
        fails.append("The customer account is not in the wheel group.")
    sd = os.path.join(efi_mp, "EFI", "systemd", "systemd-bootx64.efi")
    vendor = os.path.join(efi_mp, "EFI", "cachyos", "systemd-bootx64.efi")
    bootx = os.path.join(efi_mp, "EFI", "BOOT", "BOOTX64.EFI")
    if not os.path.isfile(sd) and not os.path.isfile(vendor) and not os.path.isfile(bootx):
        fails.append("ESP is missing systemd-boot.")
    entries = os.path.join(efi_mp, "loader", "entries")
    has_entry = False
    if os.path.isdir(entries):
        try:
            names = os.listdir(entries)
        except OSError:
            names = []
        for name in names:
            if not name.endswith(".conf"):
                continue
            has_entry = True
            text = read_text(os.path.join(entries, name))
            if "archisobasedir" in text or "fbl.install" in text:
                fails.append("Installed cmdline still has installer tokens.")
                break
    if not has_entry:
        fails.append("ESP is missing a systemd-boot loader entry.")
    seen: set[str] = set()
    out: list[str] = []
    for item in fails:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out
