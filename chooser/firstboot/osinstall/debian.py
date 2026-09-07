"""Debian live-ISO unpack (live-boot ``live/filesystem.squashfs``).

Debian live images are not casper. Do not reboot into Calamares or
debian-installer. Copy Debian's signed shim + grub, not Canonical GRUB.
GNOME and later desktops each have their own ISO file; they call these
steps.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from collections.abc import Callable

from firstboot.i18n import _
from firstboot.installlocale import InstallLocale
from . import casper
from .common import (
    RAM_DIR,
    InstalledDisk,
    InstallLog,
    OsIdentity,
    OsInstallError,
    add_user,
    bind_chroot,
    chroot_run,
    delete_users,
    health_check as tree_health_check,
    new_machine_id,
    set_graphical_target,
    unbind_chroot,
    write_fstab,
    write_grub_default,
    write_hostname,
)

LIVE_PACKAGES = (
    "live-boot",
    "live-boot-initramfs-tools",
    "live-config",
    "live-config-systemd",
    "live-tools",
    "calamares",
    "calamares-settings-debian",
    "debian-installer-launcher",
    "live-installer",
)
LIVE_DESKTOPS = (
    "calamares.desktop",
    "calamares-install-debian.desktop",
    "debian-installer-launcher.desktop",
    "install-debian.desktop",
)
LIVE_UNITS = (
    "live-config.service",
    "live-tools.service",
    "calamares.service",
)
GNOME_INITIAL_SETUP_DESKTOPS = (
    "gnome-initial-setup-first-login.desktop",
    "gnome-welcome-tour.desktop",
    "org.gnome.InitialSetup.desktop",
)

DEBIAN_SOURCES = """Types: deb
URIs: https://deb.debian.org/debian
Suites: trixie trixie-updates
Components: main contrib non-free-firmware
Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg

Types: deb
URIs: https://deb.debian.org/debian-security
Suites: trixie-security
Components: main contrib non-free-firmware
Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg
"""


def _live_hint(iso_mnt: str) -> str:
    folder = os.path.join(iso_mnt, "live")
    if not os.path.isdir(folder):
        return "No live directory on the image."
    try:
        names = sorted(n for n in os.listdir(folder) if n.endswith(".squashfs"))
    except OSError:
        names = []
    if not names:
        return "live/ has no squashfs."
    shown = ", ".join(names[:8])
    extra = "" if len(names) <= 8 else f" (+{len(names) - 8} more)"
    return f"live/ has {shown}{extra}."


def debian_live_relpaths(iso_mnt: str) -> list[str]:
    """Single live-boot squashfs. Do not unpack debian-installer."""
    single = os.path.join("live", "filesystem.squashfs")
    if os.path.isfile(os.path.join(iso_mnt, single)):
        return [single]
    raise OsInstallError("This image is not a live ISO. " + _live_hint(iso_mnt))


def unpack_debian(
    iso_mnt: str,
    target_root: str,
    *,
    on_progress: Callable[[int], None] | None = None,
    log: InstallLog | None = None,
) -> None:
    rels = debian_live_relpaths(iso_mnt)
    paths = [os.path.join(iso_mnt, rel) for rel in rels]
    if log:
        log.write("unpack " + " ".join(os.path.basename(p) for p in paths))
    casper.unpack_layered_squashfs(paths, target_root, on_progress=on_progress, log=log)
    if on_progress:
        on_progress(100)
    _copy_live_kernel(iso_mnt, target_root, log=log)


def _copy_live_kernel(iso_mnt: str, target_root: str, log: InstallLog | None = None) -> None:
    boot = os.path.join(target_root, "boot")
    os.makedirs(boot, exist_ok=True)
    has_vmlinuz = any(
        name.startswith("vmlinuz")
        for name in (os.listdir(boot) if os.path.isdir(boot) else [])
    )
    if has_vmlinuz:
        return
    folders = [os.path.join(iso_mnt, "live"), os.path.join(RAM_DIR, "iso", "live")]
    vmlinuz = ""
    initrd = ""
    for live in folders:
        cand = os.path.join(live, "vmlinuz")
        if not vmlinuz and os.path.isfile(cand):
            vmlinuz = cand
        for name in ("initrd.img", "initrd", "initrd.gz"):
            cand = os.path.join(live, name)
            if not initrd and os.path.isfile(cand):
                initrd = cand
                break
    if vmlinuz:
        shutil.copy2(vmlinuz, os.path.join(boot, "vmlinuz"))
        if log:
            log.write("copied live/vmlinuz into /boot")
    if initrd:
        shutil.copy2(initrd, os.path.join(boot, "initrd.img"))
        if log:
            log.write(f"copied {os.path.basename(initrd)} into /boot")


_GDM_AUTOLOGIN_RE = re.compile(
    r"(?im)^(AutomaticLoginEnable|AutomaticLogin|TimedLoginEnable|TimedLogin)\s*=.*\n?"
)


def _strip_gdm_autologin_file(path: str) -> None:
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    new = _GDM_AUTOLOGIN_RE.sub("", text)
    if new != text:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(new)


def strip_live_autologin(root: str) -> None:
    casper.strip_live_autologin(root)
    gdm3 = os.path.join(root, "etc", "gdm3")
    _strip_gdm_autologin_file(os.path.join(gdm3, "daemon.conf"))
    _strip_gdm_autologin_file(os.path.join(gdm3, "custom.conf"))
    drop = os.path.join(gdm3, "daemon.conf.d")
    if os.path.isdir(drop):
        try:
            names = os.listdir(drop)
        except OSError:
            names = []
        for name in names:
            path = os.path.join(drop, name)
            lower = name.lower()
            if "live" in lower or "autologin" in lower:
                try:
                    os.unlink(path)
                except OSError:
                    pass
            else:
                _strip_gdm_autologin_file(path)
    autostart = os.path.join(root, "etc", "xdg", "autostart")
    apps = os.path.join(root, "usr", "share", "applications")
    for folder in (autostart, apps):
        if not os.path.isdir(folder):
            continue
        for name in LIVE_DESKTOPS + GNOME_INITIAL_SETUP_DESKTOPS:
            try:
                os.unlink(os.path.join(folder, name))
            except OSError:
                pass


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


def disable_live_units(root: str, log: InstallLog | None = None) -> None:
    systemd = os.path.join(root, "etc", "systemd", "system")
    if not os.path.isdir(systemd):
        return
    for dirpath, _dirnames, filenames in os.walk(systemd):
        if not dirpath.endswith(".wants"):
            continue
        for name in filenames:
            if name in LIVE_UNITS or name.startswith("live-"):
                try:
                    os.unlink(os.path.join(dirpath, name))
                except OSError:
                    pass
    if log:
        log.write("disabled Debian live units")


def strip_live_sudoers(root: str, log: InstallLog | None = None) -> None:
    drop = os.path.join(root, "etc", "sudoers.d")
    if not os.path.isdir(drop):
        return
    try:
        names = os.listdir(drop)
    except OSError:
        return
    for name in names:
        if "live" not in name.lower():
            continue
        try:
            os.unlink(os.path.join(drop, name))
            if log:
                log.write(f"removed sudoers.d/{name}")
        except OSError:
            pass


def write_apt_sources(root: str, log: InstallLog | None = None) -> None:
    """Drop live-medium apt sources so first boot talks to Debian, not the ISO."""
    lists = os.path.join(root, "etc", "apt")
    os.makedirs(lists, exist_ok=True)
    sources = os.path.join(lists, "sources.list")
    if os.path.isfile(sources):
        with open(sources, encoding="utf-8", errors="replace") as fh:
            lines = fh.read().splitlines()
        kept = []
        for line in lines:
            stripped = line.split("#", 1)[0].strip().lower()
            if "cdrom:" in stripped or "file:" in stripped or "/run/live" in stripped:
                continue
            kept.append(line)
        with open(sources, "w", encoding="utf-8") as fh:
            fh.write("\n".join(kept).rstrip() + ("\n" if kept else ""))
    drop = os.path.join(lists, "sources.list.d")
    os.makedirs(drop, exist_ok=True)
    try:
        names = os.listdir(drop)
    except OSError:
        names = []
    for name in names:
        path = os.path.join(drop, name)
        lower = name.lower()
        if "live" in lower or "cdrom" in lower or "medium" in lower:
            try:
                os.unlink(path)
            except OSError:
                pass
            continue
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError:
            continue
        low = text.lower()
        if "cdrom:" in low or "file:" in low or "/run/live" in low:
            try:
                os.unlink(path)
            except OSError:
                pass
    dest = os.path.join(drop, "debian.sources")
    if not os.path.isfile(dest):
        with open(dest, "w", encoding="utf-8") as fh:
            fh.write(DEBIAN_SOURCES)
        if log:
            log.write("wrote /etc/apt/sources.list.d/debian.sources")


def purge_live_packages(root: str, log: InstallLog | None = None) -> None:
    present: list[str] = []
    st = os.path.join(root, "var", "lib", "dpkg", "status")
    text = ""
    if os.path.isfile(st):
        with open(st, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    for pkg in LIVE_PACKAGES:
        if f"Package: {pkg}\n" in text:
            present.append(pkg)
    if not present:
        return
    code, out = chroot_run(
        root,
        ["dpkg", "--purge", *present],
        log=log,
        timeout=300,
    )
    if code != 0 and log:
        log.write(f"dpkg --purge failed ({code}); continuing")
        if out:
            log.write(out[-2000:])


def configure_debian(
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
    casper.write_locale(target_root, locale)
    casper.write_timezone(target_root, timezone_minutes, log=log)
    delete_users(target_root, live_usernames, log=log)
    add_user(target_root, identity, log=log)
    set_graphical_target(target_root, display_manager, log=log)
    write_grub_default(target_root)
    strip_live_autologin(target_root)
    skip_gnome_initial_setup(target_root, log=log)
    disable_live_units(target_root, log=log)
    strip_live_sudoers(target_root, log=log)
    write_apt_sources(target_root, log=log)
    mounted = bind_chroot(target_root)
    try:
        purge_live_packages(target_root, log=log)
        chroot_run(target_root, ["locale-gen"], log=log, timeout=180)
        chroot_run(
            target_root, ["update-initramfs", "-u", "-k", "all"], log=log, timeout=300
        )
    finally:
        unbind_chroot(mounted)


SIGNED_DEB_PREFIXES = (
    "grub-efi-amd64-signed_",
    "shim-signed_",
    "shim-helpers-amd64-signed_",
)


def find_pool_debs(iso_mnt: str) -> list[str]:
    """Signed EFI .debs on the live ISO. Not in the squashfs (Calamares installs them)."""
    pool = os.path.join(iso_mnt, "pool")
    found: list[str] = []
    if not os.path.isdir(pool):
        return found
    for dirpath, _dirnames, filenames in os.walk(pool):
        for name in filenames:
            if not name.endswith(".deb"):
                continue
            if name.startswith("shim-signed-common"):
                continue
            if name.startswith(SIGNED_DEB_PREFIXES):
                found.append(os.path.join(dirpath, name))
    found.sort()
    return found


def iso_extras(iso_mnt: str) -> dict[str, str]:
    extra: dict[str, str] = {}
    for deb in find_pool_debs(iso_mnt):
        extra[os.path.relpath(deb, iso_mnt)] = deb
    mods = os.path.join(iso_mnt, "boot", "grub", "x86_64-efi")
    if os.path.isdir(mods) and os.path.isfile(os.path.join(mods, "modinfo.sh")):
        extra[os.path.join("boot", "grub", "x86_64-efi")] = mods
    return extra


def extract_signed_efi_debs(
    iso_mnt: str, target_root: str, log: InstallLog | None = None
) -> None:
    debs = find_pool_debs(iso_mnt)
    if not debs:
        if log:
            log.write("no Debian signed EFI debs on the image")
        return
    for deb in debs:
        proc = subprocess.run(
            ["dpkg-deb", "-x", deb, target_root],
            check=False,
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            if log:
                log.write(f"dpkg-deb -x {os.path.basename(deb)} failed")
            continue
        if log:
            log.write(f"extracted {os.path.basename(deb)}")


def debian_signed_efi_paths(
    root: str, iso_mnt: str = ""
) -> tuple[str, str, str]:
    """Debian shim + *installed* grubx64.efi.signed. Never live EFI/BOOT/grubx64.

    The live ISO's EFI/boot/grubx64.efi is removable GRUB (prefix /boot/grub).
    Canonical GRUB will not load a Debian kernel with Secure Boot on.
    The live squashfs has grub-common only; signed files come from pool debs.
    """
    shim_cands = [
        os.path.join(root, "usr", "lib", "shim", "shimx64.efi.signed"),
        os.path.join(root, "usr", "lib", "shim", "shimx64.efi"),
    ]
    grub_cands = [
        os.path.join(root, "usr", "lib", "grub", "x86_64-efi-signed", "grubx64.efi.signed"),
    ]
    mm_cands = [
        os.path.join(root, "usr", "lib", "shim", "mmx64.efi.signed"),
        os.path.join(root, "usr", "lib", "shim", "mmx64.efi"),
    ]
    if iso_mnt:
        for a, b in (("EFI", "boot"), ("efi", "boot"), ("EFI", "BOOT")):
            bootx = os.path.join(iso_mnt, a, b, "bootx64.efi")
            if os.path.isfile(bootx):
                shim_cands.append(bootx)
                break
            bootx = os.path.join(iso_mnt, a, b, "BOOTX64.EFI")
            if os.path.isfile(bootx):
                shim_cands.append(bootx)
                break
    shim = next((p for p in shim_cands if os.path.isfile(p)), "")
    grub = next((p for p in grub_cands if os.path.isfile(p)), "")
    mm = next((p for p in mm_cands if os.path.isfile(p)), "")
    return shim, grub, mm


def copy_debian_esp_binaries(
    efi_mp: str,
    target_root: str,
    bootloader_id: str,
    log: InstallLog | None = None,
    iso_mnt: str = "",
) -> None:
    """Put Debian's Microsoft-signed shim + Debian grubx64 on the ESP.

    ``EFI/BOOT/`` is shim only — extra ``.efi`` there is a first-stage
    loader on Lenovo/Phoenix firmware. Do not copy the live ISO grubx64
    (gcdx64).
    """
    src_shim, src_grub, src_mm = debian_signed_efi_paths(target_root, iso_mnt=iso_mnt)
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
            f"copied Debian shim to EFI/BOOT and shim+grubx64.efi into EFI/{bootloader_id}"
        )


def _boot_kernel_paths(root: str) -> tuple[str, str]:
    boot = os.path.join(root, "boot")
    vers: list[str] = []
    try:
        names = os.listdir(boot) if os.path.isdir(boot) else []
    except OSError:
        names = []
    for name in names:
        if name.startswith("vmlinuz-") and not name.endswith(".old"):
            vers.append(name[len("vmlinuz-") :])
    vers.sort()
    ver = vers[-1] if vers else ""
    linux = f"/boot/vmlinuz-{ver}" if ver else "/boot/vmlinuz"
    initrd = f"/boot/initrd.img-{ver}" if ver else "/boot/initrd.img"
    if not os.path.isfile(os.path.join(root, linux.lstrip("/"))):
        if os.path.isfile(os.path.join(boot, "vmlinuz")):
            linux = "/boot/vmlinuz"
    if not os.path.isfile(os.path.join(root, initrd.lstrip("/"))):
        for name in ("initrd.img", "initrd"):
            if os.path.isfile(os.path.join(boot, name)):
                initrd = f"/boot/{name}"
                break
    return linux, initrd


def write_debian_grub_cfg(
    root: str, disk: InstalledDisk, log: InstallLog | None = None
) -> None:
    """Installed menu. Live squashfs has no grub-install / update-grub."""
    linux, initrd = _boot_kernel_paths(root)
    uuid = disk.root_uuid
    grub_dir = os.path.join(root, "boot", "grub")
    os.makedirs(grub_dir, exist_ok=True)
    text = (
        "set default=0\n"
        "set timeout=5\n"
        "insmod all_video\n"
        "insmod gzio\n"
        "insmod part_gpt\n"
        "insmod ext2\n"
        f"search --no-floppy --fs-uuid --set=root {uuid}\n"
        'menuentry "Debian GNU/Linux" {\n'
        f"    search --no-floppy --fs-uuid --set=root {uuid}\n"
        f"    linux {linux} root=UUID={uuid} ro quiet splash\n"
        f"    initrd {initrd}\n"
        "}\n"
    )
    path = os.path.join(grub_dir, "grub.cfg")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    if log:
        log.write(f"wrote /boot/grub/grub.cfg linux={linux}")


def ensure_debian_grub_modules(
    root: str, iso_mnt: str = "", log: InstallLog | None = None
) -> None:
    """Debian live squashfs has no grub-efi-amd64-bin. Use the ISO's modules."""
    dest = os.path.join(root, "usr", "lib", "grub", "x86_64-efi")
    if os.path.isfile(os.path.join(dest, "modinfo.sh")):
        return
    src = ""
    if iso_mnt:
        cand = os.path.join(iso_mnt, "boot", "grub", "x86_64-efi")
        if os.path.isfile(os.path.join(cand, "modinfo.sh")):
            src = cand
    if not src:
        return
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    shutil.copytree(src, dest, dirs_exist_ok=True)
    if log:
        log.write(f"copied Debian grub x86_64-efi modules from {src}")


def install_debian_bootloader(
    target_root: str,
    efi_mp: str,
    disk: InstalledDisk,
    iso_mnt: str,
    *,
    bootloader_id: str = "debian",
    nvram_label: str = "Debian",
    log: InstallLog | None = None,
) -> str:
    os.makedirs(efi_mp, exist_ok=True)
    extract_signed_efi_debs(iso_mnt, target_root, log=log)
    ensure_debian_grub_modules(target_root, iso_mnt=iso_mnt, log=log)
    write_debian_grub_cfg(target_root, disk, log=log)
    log_text: list[str] = []
    grub_install = os.path.join(target_root, "usr", "sbin", "grub-install")
    if os.path.isfile(grub_install) or os.path.isfile(
        os.path.join(target_root, "sbin", "grub-install")
    ):
        mounted = bind_chroot(target_root)
        try:
            _code, out = chroot_run(
                target_root,
                [
                    "grub-install",
                    "--target=x86_64-efi",
                    "--efi-directory=/boot/efi",
                    f"--bootloader-id={bootloader_id}",
                    "--uefi-secure-boot",
                    "--recheck",
                    "--no-nvram",
                ],
                log=log,
                timeout=180,
            )
            log_text.append(out)
            code2, out2 = chroot_run(
                target_root, ["update-grub"], log=log, timeout=180
            )
            log_text.append(out2)
            if code2 != 0 and log:
                log.write("update-grub failed")
        finally:
            unbind_chroot(mounted)
        write_debian_grub_cfg(target_root, disk, log=log)
    elif log:
        log.write("live image has no grub-install; using signed EFI from the ISO pool")
    copy_debian_esp_binaries(
        efi_mp, target_root, bootloader_id, log=log, iso_mnt=iso_mnt
    )
    casper.write_esp_grub_stub(efi_mp, bootloader_id, disk.root_uuid, log=log)
    return "\n".join(t for t in log_text if t)


def health_check_debian(
    target_root: str,
    efi_mp: str,
    identity: OsIdentity,
    disk: InstalledDisk,
    *,
    display_manager: str,
    boot_log: str = "",
) -> list[str]:
    return tree_health_check(
        target_root,
        efi_mp,
        identity,
        disk,
        display_manager=display_manager,
        boot_log=boot_log,
    )
