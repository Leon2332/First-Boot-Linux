"""Casper live-ISO unpack and configure (Ubuntu family).

Ubuntu 26.04 desktop is layered (minimal + standard), not
``filesystem.squashfs``. Do not unpack ``*.live.squashfs`` (live session).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from collections.abc import Callable

from firstboot.i18n import _
from firstboot.install import InstallError, copy_tree
from firstboot.installlocale import InstallLocale
from firstboot.osinstall.common import (
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
    run_checked,
    set_graphical_target,
    umount_path,
    unbind_chroot,
    write_fstab,
    write_grub_default,
    write_hostname,
)

# Installed-OS GRUB, not live-ISO gcdx64. See write_esp_grub_stub.
SIGNED_EFI_DIR = "/usr/share/firstboot/signed-efi"

LIVE_PACKAGES = (
    "casper",
    "lupin-casper",
    "ubiquity",
    "ubiquity-frontend-gtk",
    "ubiquity-ubuntu-artwork",
    "ubuntu-desktop-bootstrap",
    "subiquity",
    "subiquity-tools",
    "live-installer",
    "calamares",
    "calamares-settings-ubuntu",
    "calamares-settings-lubuntu",
    "calamares-settings-kubuntu",
)
LIVE_DESKTOPS = (
    "ubiquity.desktop",
    "ubiquity-gtkui.desktop",
    "ubuntu-desktop-bootstrap.desktop",
    "calamares.desktop",
    "debian-installer-launcher.desktop",
)


def _casper_hint(iso_mnt: str) -> str:
    folder = os.path.join(iso_mnt, "casper")
    if not os.path.isdir(folder):
        return "No casper directory on the image."
    try:
        names = sorted(n for n in os.listdir(folder) if n.endswith(".squashfs"))
    except OSError:
        names = []
    if not names:
        return "casper/ has no squashfs."
    shown = ", ".join(names[:8])
    extra = "" if len(names) <= 8 else f" (+{len(names) - 8} more)"
    return f"casper/ has {shown}{extra}."


def casper_squashfs_relpaths(iso_mnt: str, lang: str | None = "en") -> list[str]:
    """Live filesystem layers, lower first. Skip live and enhanced-secureboot."""
    single = os.path.join("casper", "filesystem.squashfs")
    if os.path.isfile(os.path.join(iso_mnt, single)):
        return [single]
    base = os.path.join("casper", "minimal.squashfs")
    standard = os.path.join("casper", "minimal.standard.squashfs")
    rels: list[str] = []
    if os.path.isfile(os.path.join(iso_mnt, base)):
        rels.append(base)
        if lang:
            lang_layer = os.path.join("casper", f"minimal.{lang}.squashfs")
            if os.path.isfile(os.path.join(iso_mnt, lang_layer)):
                rels.append(lang_layer)
    if os.path.isfile(os.path.join(iso_mnt, standard)):
        rels.append(standard)
        if lang:
            std_lang = os.path.join("casper", f"minimal.standard.{lang}.squashfs")
            if os.path.isfile(os.path.join(iso_mnt, std_lang)):
                rels.append(std_lang)
    if rels:
        return rels
    raise OsInstallError("This image is not a live ISO. " + _casper_hint(iso_mnt))


def squashfs_abs(iso_mnt: str, relpaths: list[str]) -> list[str]:
    paths = [os.path.join(iso_mnt, rel) for rel in relpaths]
    missing = [p for p in paths if not os.path.isfile(p)]
    if missing:
        raise OsInstallError("This image is not a live ISO. " + _casper_hint(iso_mnt))
    return paths


def unpack_layered_squashfs(
    paths: list[str],
    dest: str,
    *,
    on_progress: Callable[[int], None] | None = None,
    log: InstallLog | None = None,
) -> None:
    """Mount casper layers as one overlay (later layers on top), then rsync once.

    Sequential rsync -H of language packs onto minimal.squashfs dies with
    rsync code 13 (hardlink / directory vs file). Overlay merge is how
    casper itself stacks the layers.
    """
    if len(paths) == 1:
        unpack_squashfs(paths[0], dest, on_progress=on_progress, log=log)
        return
    sqmnts: list[str] = []
    merged = dest + ".ovl"
    try:
        for i, path in enumerate(paths):
            mnt = f"{dest}.sq{i}"
            os.makedirs(mnt, exist_ok=True)
            run_checked(
                ["mount", "-t", "squashfs", "-o", "loop,ro", path, mnt],
                what=f"mount live layer {os.path.basename(path)}",
            )
            sqmnts.append(mnt)
        os.makedirs(merged, exist_ok=True)
        lower = ":".join(reversed(sqmnts))
        run_checked(
            ["mount", "-t", "overlay", "overlay", "-o", f"lowerdir={lower}", merged],
            what="merge live filesystem layers",
        )
        copy_tree(merged, dest, on_percent=on_progress)
        if log:
            log.write(f"rsync {len(paths)} squashfs layers -> {dest}")
    except InstallError as exc:
        raise OsInstallError(str(exc)) from exc
    finally:
        umount_path(merged)
        shutil.rmtree(merged, ignore_errors=True)
        for mnt in reversed(sqmnts):
            umount_path(mnt)
            shutil.rmtree(mnt, ignore_errors=True)


def unpack_squashfs(
    squashfs: str,
    dest: str,
    *,
    on_progress: Callable[[int], None] | None = None,
    log: InstallLog | None = None,
) -> None:
    os.makedirs(dest, exist_ok=True)
    if os.geteuid() == 0:
        mnt = dest + ".sq"
        os.makedirs(mnt, exist_ok=True)
        try:
            run_checked(
                ["mount", "-t", "squashfs", "-o", "loop,ro", squashfs, mnt],
                what="mount the live filesystem",
            )
            copy_tree(mnt, dest, on_percent=on_progress)
        except InstallError as exc:
            raise OsInstallError(str(exc)) from exc
        finally:
            umount_path(mnt)
            shutil.rmtree(mnt, ignore_errors=True)
        if log:
            log.write(f"rsync {squashfs} -> {dest}")
        return
    cmd = ["unsquashfs", "-f", "-d", dest, squashfs]
    proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip().splitlines()
        tail = err[-1] if err else f"exit {proc.returncode}"
        raise OsInstallError(f"unpack the live filesystem: {tail}")
    if on_progress:
        on_progress(100)
    if log:
        log.write(f"unsquashfs {squashfs} -> {dest}")


def unpack_casper(
    iso_mnt: str,
    target_root: str,
    *,
    on_progress: Callable[[int], None] | None = None,
    log: InstallLog | None = None,
    lang: str | None = "en",
) -> None:
    rels = casper_squashfs_relpaths(iso_mnt, lang=lang)
    paths = squashfs_abs(iso_mnt, rels)
    if log:
        log.write("unpack layers " + " ".join(os.path.basename(p) for p in paths))
    unpack_layered_squashfs(paths, target_root, on_progress=on_progress, log=log)
    if on_progress:
        on_progress(100)
    _copy_casper_kernel(iso_mnt, target_root, log=log)


def unpack_casper_single(
    iso_mnt: str,
    target_root: str,
    *,
    on_progress: Callable[[int], None] | None = None,
    log: InstallLog | None = None,
) -> None:
    unpack_casper(iso_mnt, target_root, on_progress=on_progress, log=log)


def _copy_casper_kernel(iso_mnt: str, target_root: str, log: InstallLog | None = None) -> None:
    boot = os.path.join(target_root, "boot")
    os.makedirs(boot, exist_ok=True)
    has_vmlinuz = any(
        name.startswith("vmlinuz")
        for name in (os.listdir(boot) if os.path.isdir(boot) else [])
    )
    if has_vmlinuz:
        return
    casper = os.path.join(iso_mnt, "casper")
    vmlinuz = os.path.join(casper, "vmlinuz")
    initrd = ""
    for name in ("initrd", "initrd.lz", "initrd.gz"):
        cand = os.path.join(casper, name)
        if os.path.isfile(cand):
            initrd = cand
            break
    if os.path.isfile(vmlinuz):
        shutil.copy2(vmlinuz, os.path.join(boot, "vmlinuz"))
        if log:
            log.write("copied casper/vmlinuz into /boot")
    if initrd:
        shutil.copy2(initrd, os.path.join(boot, "initrd.img"))
        if log:
            log.write(f"copied {os.path.basename(initrd)} into /boot")


def write_locale(root: str, locale: InstallLocale) -> None:
    default = os.path.join(root, "etc", "default", "locale")
    os.makedirs(os.path.dirname(default), exist_ok=True)
    with open(default, "w", encoding="utf-8") as fh:
        fh.write(f"LANG={locale.glibc}\n")
    gen = os.path.join(root, "etc", "locale.gen")
    text = ""
    if os.path.isfile(gen):
        with open(gen, encoding="utf-8") as fh:
            text = fh.read()
    needle = locale.glibc
    lines = text.splitlines() if text else []
    found = False
    out: list[str] = []
    for line in lines:
        stripped = line.lstrip("# ").strip()
        if stripped.startswith(needle):
            out.append(f"{needle} UTF-8")
            found = True
        else:
            out.append(line)
    if not found:
        out.append(f"{needle} UTF-8")
    with open(gen, "w", encoding="utf-8") as fh:
        fh.write("\n".join(out).rstrip() + "\n")
    kbd = os.path.join(root, "etc", "default", "keyboard")
    with open(kbd, "w", encoding="utf-8") as fh:
        fh.write(
            'XKBMODEL="pc105"\n'
            f'XKBLAYOUT="{locale.keyboard}"\n'
            'XKBVARIANT=""\n'
            'XKBOPTIONS=""\n'
            "BACKSPACE=guess\n"
        )


def write_timezone(root: str, minutes: int | None, log: InstallLog | None = None) -> None:
    if minutes is None:
        return
    from firstboot.timezone import iana_zone, snap_tz_minutes, tzif_bytes

    minutes = snap_tz_minutes(minutes)
    zone = iana_zone(minutes)
    localtime = os.path.join(root, "etc", "localtime")
    tzpath = os.path.join(root, "etc", "timezone")
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
            with open(tzpath, "w", encoding="ascii") as fh:
                fh.write(zone + "\n")
            if log:
                log.write(f"timezone {zone}")
            return
    os.makedirs(os.path.dirname(localtime), exist_ok=True)
    with open(localtime, "wb") as fh:
        fh.write(tzif_bytes(minutes))
    with open(tzpath, "w", encoding="ascii") as fh:
        fh.write("UTC\n")
    if log:
        log.write(f"timezone offset {minutes} minutes")


def strip_live_autologin(root: str) -> None:
    files = [
        os.path.join(root, "etc", "gdm3", "custom.conf"),
        os.path.join(root, "etc", "gdm", "custom.conf"),
        os.path.join(root, "etc", "sddm.conf"),
    ]
    for path in files:
        if not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        text = re.sub(
            r"(?im)^(AutomaticLoginEnable|AutomaticLogin)\s*=.*\n?", "", text
        )
        text = re.sub(r"(?im)^User\s*=.*\n?", "", text)
        text = re.sub(r"(?im)^Session\s*=.*\n?", "", text)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
    drop_dirs = [
        os.path.join(root, "etc", "lightdm", "lightdm.conf.d"),
        os.path.join(root, "etc", "sddm.conf.d"),
        os.path.join(root, "usr", "share", "lightdm", "lightdm.conf.d"),
    ]
    for folder in drop_dirs:
        if not os.path.isdir(folder):
            continue
        try:
            names = os.listdir(folder)
        except OSError:
            continue
        for name in names:
            lower = name.lower()
            if "casper" in lower or "autologin" in lower or "live" in lower:
                try:
                    os.unlink(os.path.join(folder, name))
                except OSError:
                    pass
    autostart = os.path.join(root, "etc", "xdg", "autostart")
    if os.path.isdir(autostart):
        for name in LIVE_DESKTOPS:
            try:
                os.unlink(os.path.join(autostart, name))
            except OSError:
                pass


def purge_live_packages(root: str, log: InstallLog | None = None) -> None:
    present: list[str] = []
    for pkg in LIVE_PACKAGES:
        st = os.path.join(root, "var", "lib", "dpkg", "status")
        text = ""
        if os.path.isfile(st):
            with open(st, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
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


def configure_casper(
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
    strip_live_autologin(target_root)
    mounted = bind_chroot(target_root)
    try:
        purge_live_packages(target_root, log=log)
        chroot_run(target_root, ["locale-gen"], log=log, timeout=180)
        if locale.langpack and locale.langpack != "en":
            chroot_run(
                target_root,
                [
                    "apt-get",
                    "install",
                    "-y",
                    f"language-pack-{locale.langpack}",
                    f"language-pack-gnome-{locale.langpack}",
                ],
                log=log,
                timeout=180,
            )
        chroot_run(
            target_root, ["update-initramfs", "-u", "-k", "all"], log=log, timeout=300
        )
    finally:
        unbind_chroot(mounted)


def ensure_grub_efi_modules(
    root: str, iso_mnt: str = "", log: InstallLog | None = None
) -> None:
    """Ubuntu live layers often omit grub-efi-amd64-bin. Copy from FBL or the ISO."""
    dest = os.path.join(root, "usr", "lib", "grub", "x86_64-efi")
    if os.path.isfile(os.path.join(dest, "modinfo.sh")):
        return
    candidates = ["/usr/lib/grub/x86_64-efi"]
    if iso_mnt:
        candidates.extend(
            (
                os.path.join(iso_mnt, "boot", "grub", "x86_64-efi"),
                os.path.join(iso_mnt, "usr", "lib", "grub", "x86_64-efi"),
            )
        )
    src = ""
    for path in candidates:
        if os.path.isfile(os.path.join(path, "modinfo.sh")):
            src = path
            break
    if not src:
        if log:
            log.write("no grub x86_64-efi modules on the live system")
        return
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    shutil.copytree(src, dest, dirs_exist_ok=True)
    if log:
        log.write(f"copied grub x86_64-efi modules from {src}")


def write_esp_grub_stub(
    efi_mp: str, bootloader_id: str, root_uuid: str, log: InstallLog | None = None
) -> None:
    """Installed grubx64.efi.signed loads EFI/<id>/grub.cfg. Without it: grub>."""
    if not root_uuid:
        return
    text = (
        f"search.fs_uuid {root_uuid} root\n"
        "set prefix=($root)'/boot/grub'\n"
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
        log.write(f"wrote EFI/{bootloader_id}/grub.cfg stub uuid={root_uuid}")


def signed_efi_paths() -> tuple[str, str, str]:
    """Microsoft shim + Canonical *installed* grubx64.efi.signed + MokManager.

    Never return the live ISO's EFI/BOOT/grubx64.efi: that file is gcdx64
    (prefix /boot/grub). Shim loads it, GRUB finds no EFI/ubuntu config, grub>.
    """
    shim = os.path.join(SIGNED_EFI_DIR, "shimx64.efi")
    grub = os.path.join(SIGNED_EFI_DIR, "grubx64.efi")
    mm = os.path.join(SIGNED_EFI_DIR, "mmx64.efi")
    if os.path.isfile(shim) and os.path.isfile(grub):
        return shim, grub, mm if os.path.isfile(mm) else ""
    shim2 = "/usr/lib/shim/shimx64.efi.signed"
    grub2 = "/usr/lib/grub/x86_64-efi-signed/grubx64.efi.signed"
    mm2 = "/usr/lib/shim/mmx64.efi"
    if os.path.isfile(shim2) and os.path.isfile(grub2):
        return shim2, grub2, mm2 if os.path.isfile(mm2) else ""
    return "", "", ""


def copy_signed_esp_binaries(
    efi_mp: str, bootloader_id: str, log: InstallLog | None = None
) -> None:
    """Put Secure Boot shim + installed grubx64 on the ESP. Not live gcdx64."""
    src_shim, src_grub, src_mm = signed_efi_paths()
    if not src_shim or not src_grub:
        raise OsInstallError(_("Could not write the boot partition."))
    boot = os.path.join(efi_mp, "EFI", "BOOT")
    vendor = os.path.join(efi_mp, "EFI", bootloader_id)
    os.makedirs(boot, exist_ok=True)
    os.makedirs(vendor, exist_ok=True)
    shutil.copy2(src_shim, os.path.join(boot, "BOOTX64.EFI"))
    shutil.copy2(src_shim, os.path.join(vendor, "shimx64.efi"))
    shutil.copy2(src_grub, os.path.join(boot, "grubx64.efi"))
    shutil.copy2(src_grub, os.path.join(vendor, "grubx64.efi"))
    if src_mm:
        shutil.copy2(src_mm, os.path.join(vendor, "mmx64.efi"))
        shutil.copy2(src_mm, os.path.join(boot, "mmx64.efi"))
    if log:
        log.write(
            f"copied signed shim+grubx64.efi into EFI/BOOT and EFI/{bootloader_id}"
        )


def install_casper_bootloader(
    target_root: str,
    efi_mp: str,
    disk: InstalledDisk,
    iso_mnt: str,
    *,
    bootloader_id: str = "ubuntu",
    nvram_label: str = "Ubuntu",
    log: InstallLog | None = None,
) -> str:
    """Install GRUB + shim. Returns combined command log for the health check."""
    os.makedirs(efi_mp, exist_ok=True)
    ensure_grub_efi_modules(target_root, iso_mnt=iso_mnt, log=log)
    mounted = bind_chroot(target_root)
    log_text: list[str] = []
    try:
        code, out = chroot_run(
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
    # grub-install without grub-efi-amd64-signed writes unsigned grubx64.efi
    # (PXE). The live ISO's EFI/BOOT/grubx64.efi is gcdx64 (grub>). Overlay
    # Canonical's *installed* grubx64.efi.signed + Microsoft shim.
    copy_signed_esp_binaries(efi_mp, bootloader_id, log=log)
    write_esp_grub_stub(efi_mp, bootloader_id, disk.root_uuid, log=log)
    return "\n".join(t for t in log_text if t)


def health_check_casper(
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
