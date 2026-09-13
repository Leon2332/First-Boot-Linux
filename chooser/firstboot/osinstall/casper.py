"""Casper live-ISO unpack and configure (Ubuntu family).

Ubuntu desktop ISOs are layered squashfs. Canonical's installer
(ubuntu-desktop-bootstrap → subiquity → curtin) reads
``casper/install-sources.yaml`` and extracts the default
``fsimage-layered`` source — ``minimal.squashfs`` plus
``minimal.standard.squashfs``. It never copies
``minimal.standard.live.squashfs``. That live layer is the Try-Ubuntu
session: casper, live-settings, the bootstrap snap, and it whiteouts
the desktop metapackage. Copying it onto the disk is how you get a
Plymouth hang (casper initrd waiting for live media) or a leftover
Ubuntu user.

GNOME's minimal layer already ships a versioned initrd, so skipping
live is enough there. Cinnamon and Budgie 26.04 *install* layers already
contain ``linux-image`` / ``linux-modules`` and **dracut** (not
initramfs-tools). initramfs-tools lives only in the live layer, for
casper. After unpack, build the initrd with ``dracut --no-hostonly``.
Do not apt-install initramfs-tools (it Conflicts with dracut) and do
not copy the live layer. Pin ``/proc/cmdline`` while dracut runs so FBL
casper tokens are not baked in.

The live layer also seeds ``ubuntu-desktop-bootstrap`` rev 589 and a
systemd mount unit (``snap-ubuntu\\x2ddesktop\\x2dbootstrap-589.mount``).
First boot then dies with ``Can't lookup blockdev`` on that snap file.

Ubuntu MATE 24.04.4 is the same *layers* (curtin never copies live) but
the kernel, ``linux-firmware``, and ``grub-efi-amd64-signed`` live only
in the live overlay — LP: #2026225, older ISO. After unpack, apt-install
``linux-generic-hwe-24.04`` plus matching ``grub-efi-amd64-bin`` /
``grub-efi-amd64-signed`` / ``shim-signed`` from ``file:/cdrom``. Do not
overlay First Boot's 26.04 ``grubx64.efi.signed`` onto 24.04 modules
(``grub_efi_set_text_mode not found``).
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
    "ubuntucinnamon-live-settings",
    "budgie-live-settings",
    "ubuntu-mate-live-settings",
)

# Live overlay seeds the Subiquity/desktop-bootstrap snap. First boot then
# recreates a user named Ubuntu next to the customer account.
LIVE_INSTALLER_SNAPS = ("ubuntu-desktop-bootstrap", "subiquity")

# Live overlay turns the initrd into a casper image. Drop these before
# update-initramfs or the installed kernel still cannot mount root.
CASPER_INITRAMFS_CONFS = (
    "etc/initramfs-tools/conf.d/casperize.conf",
    "etc/initramfs-tools/conf.d/default-layer.conf",
)
CASPER_INITRAMFS_DIRS = (
    "usr/share/initramfs-tools/scripts",
    "usr/share/initramfs-tools/hooks",
    "etc/initramfs-tools/scripts",
    "etc/initramfs-tools/hooks",
)
LIVE_DESKTOPS = (
    "ubiquity.desktop",
    "ubiquity-gtkui.desktop",
    "ubuntu-desktop-bootstrap.desktop",
    "calamares.desktop",
    "debian-installer-launcher.desktop",
)

# debs curtin pulls for a desktop kernel. Not linux-firmware (already in
# the install layers; copying it blows the same-disk RAM budget).
KERNEL_POOL_NEEDLES = (
    "linux-image-",
    "linux-modules-",
    "linux-headers-",
    "linux-generic-hwe",
    "linux-image-generic",
    "linux-main-modules-zfs-",
    "initramfs-tools",
    "busybox-initramfs",
    "klibc-utils",
    "libklibc",
    "linux-base_",
    "finalrd_",
    "kmod_",
    "intel-microcode",
    "amd64-microcode",
)

KERNEL_PACKAGE_FALLBACKS = (
    "linux-generic-hwe-26.04",
    "linux-image-generic-hwe-26.04",
    "linux-generic-hwe-24.04",
    "linux-image-generic-hwe-24.04",
    "linux-generic",
    "linux-image-generic",
)

# Signed EFI + grub-install for 24.04 MATE (those packages are live-only).
BOOTLOADER_POOL_PREFIXES = (
    "grub-efi-amd64-signed_",
    "grub-efi-amd64-bin_",
    "grub-efi-amd64_",
    "grub2-common_",
    "shim-signed_",
    "shim-helpers-amd64-signed_",
)

# dpkg-deb -x these (no postinst). Do not extract grub-efi-amd64_ —
# that package's postinst runs grub-install and needs a mounted ESP.
BOOTLOADER_EXTRACT_PREFIXES = (
    "grub-efi-amd64-signed_",
    "grub-efi-amd64-bin_",
    "grub2-common_",
    "shim-signed_",
    "shim-helpers-amd64-signed_",
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


def casper_squashfs_relpaths(
    iso_mnt: str, lang: str | None = "en", include_live: bool = False
) -> list[str]:
    """Live filesystem layers, lower first. Skip enhanced-secureboot.

    Skip ``*.live.squashfs`` unless *include_live*. Official install never
    includes that layer; Cinnamon and Budgie already have the kernel in
    the install layers and rebuild the initrd with dracut.
    """
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
    if include_live:
        live = os.path.join("casper", "minimal.standard.live.squashfs")
        if os.path.isfile(os.path.join(iso_mnt, live)):
            rels.append(live)
    if rels:
        return rels
    raise OsInstallError("This image is not a live ISO. " + _casper_hint(iso_mnt))


def squashfs_abs(iso_mnt: str, relpaths: list[str]) -> list[str]:
    paths = [os.path.join(iso_mnt, rel) for rel in relpaths]
    missing = [p for p in paths if not os.path.isfile(p)]
    if missing:
        raise OsInstallError("This image is not a live ISO. " + _casper_hint(iso_mnt))
    return paths


def parse_install_sources(iso_mnt: str) -> dict[str, str]:
    """Read casper/install-sources.yaml (curtin/subiquity catalog).

    Returns kernel package name and the default source path
    (``minimal.standard.squashfs`` on a full desktop install).
    """
    path = os.path.join(iso_mnt, "casper", "install-sources.yaml")
    result = {"kernel": "", "path": ""}
    if not os.path.isfile(path):
        return result
    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return result
    section = ""
    item: dict[str, str] = {}
    items: list[dict[str, str]] = []

    def flush() -> None:
        nonlocal item
        if item:
            items.append(item)
            item = {}

    for line in lines:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        stripped = line.strip()
        if indent == 0 and stripped.endswith(":") and not stripped.startswith("-"):
            flush()
            section = stripped[:-1]
            continue
        if section == "kernel" and stripped.startswith("default:"):
            result["kernel"] = stripped.split(":", 1)[1].strip()
            continue
        if section != "sources":
            continue
        if stripped.startswith("- "):
            flush()
            rest = stripped[2:]
            if ":" in rest:
                key, value = rest.split(":", 1)
                item[key.strip()] = value.strip()
            continue
        if ":" in stripped:
            key, value = stripped.split(":", 1)
            item[key.strip()] = value.strip()
    flush()
    for entry in items:
        if entry.get("default", "").lower() in ("true", "yes"):
            result["path"] = entry.get("path", "")
            break
    return result


def iso_apt_suite(iso_mnt: str) -> str:
    dists = os.path.join(iso_mnt, "dists")
    if not os.path.isdir(dists):
        return "stable"
    try:
        names = sorted(
            n for n in os.listdir(dists) if os.path.isdir(os.path.join(dists, n))
        )
    except OSError:
        return "stable"
    for name in names:
        binary = os.path.join(dists, name, "main", "binary-amd64")
        if os.path.isfile(os.path.join(binary, "Packages")) or os.path.isfile(
            os.path.join(binary, "Packages.gz")
        ):
            return name
    return names[0] if names else "stable"


def pool_deb_names(iso_mnt: str) -> list[str]:
    names: list[str] = []
    pool = os.path.join(iso_mnt, "pool")
    if not os.path.isdir(pool):
        return names
    for dirpath, _dirnames, filenames in os.walk(pool):
        for name in filenames:
            if name.endswith(".deb"):
                names.append(name)
    return names


def _deb_is_package(filename: str, package: str) -> bool:
    return filename.startswith(package + "_")


def iso_kernel_package(iso_mnt: str) -> str:
    """Package curtin would install: catalog kernel.default, else pool HWE."""
    wanted = parse_install_sources(iso_mnt).get("kernel") or ""
    debs = pool_deb_names(iso_mnt)
    if wanted and any(_deb_is_package(name, wanted) for name in debs):
        return wanted
    for pkg in KERNEL_PACKAGE_FALLBACKS:
        if any(_deb_is_package(name, pkg) for name in debs):
            return pkg
    return wanted


def kernel_pool_extras(iso_mnt: str) -> dict[str, str]:
    """ISO pool + dists needed to apt-install the kernel after a same-disk RAM copy."""
    extra: dict[str, str] = {}
    dists = os.path.join(iso_mnt, "dists")
    if os.path.isdir(dists):
        extra["dists"] = dists
    extra.update(
        _pool_deb_extras(iso_mnt, needles=KERNEL_POOL_NEEDLES, include_firmware=False)
    )
    return extra


def _pool_deb_extras(
    iso_mnt: str,
    *,
    needles: tuple[str, ...],
    include_firmware: bool,
    prefixes: tuple[str, ...] = (),
) -> dict[str, str]:
    extra: dict[str, str] = {}
    pool = os.path.join(iso_mnt, "pool")
    if not os.path.isdir(pool):
        return extra
    for dirpath, _dirnames, filenames in os.walk(pool):
        for name in filenames:
            if not name.endswith(".deb"):
                continue
            if name.startswith("shim-signed-common"):
                continue
            if "linux-firmware" in name:
                if include_firmware:
                    abs_path = os.path.join(dirpath, name)
                    extra[os.path.relpath(abs_path, iso_mnt)] = abs_path
                continue
            if prefixes and name.startswith(prefixes):
                abs_path = os.path.join(dirpath, name)
                extra[os.path.relpath(abs_path, iso_mnt)] = abs_path
                continue
            if needles and any(needle in name for needle in needles):
                abs_path = os.path.join(dirpath, name)
                extra[os.path.relpath(abs_path, iso_mnt)] = abs_path
    return extra


def bootloader_pool_extras(iso_mnt: str) -> dict[str, str]:
    """24.04 MATE: grub/shim signed debs live in pool/, not the install layers."""
    return _pool_deb_extras(
        iso_mnt, needles=(), include_firmware=False, prefixes=BOOTLOADER_POOL_PREFIXES
    )


def firmware_pool_extras(iso_mnt: str) -> dict[str, str]:
    """24.04 MATE: linux-firmware is live-layer only; curtin apt-installs it."""
    return _pool_deb_extras(iso_mnt, needles=(), include_firmware=True)


def mate_iso_extras(iso_mnt: str) -> dict[str, str]:
    extra = kernel_pool_extras(iso_mnt)
    extra.update(bootloader_pool_extras(iso_mnt))
    extra.update(firmware_pool_extras(iso_mnt))
    return extra


def disable_overlayroot(root: str, log: InstallLog | None = None) -> None:
    path = os.path.join(root, "etc", "overlayroot.local.conf")
    if not os.path.isfile(path):
        return
    try:
        os.rename(path, path + ".old")
    except OSError:
        return
    if log:
        log.write("disabled overlayroot.local.conf")


def _installer_snap_unit_name(name: str) -> bool:
    """True for systemd units that mount or run a live installer snap."""
    for snap in LIVE_INSTALLER_SNAPS:
        if snap in name:
            return True
        if snap.replace("-", r"\x2d") in name:
            return True
    return False


def casper_leftovers(root: str) -> list[str]:
    """Live-session files that must not be on an installed root."""
    fails: list[str] = []
    casperize = os.path.join(
        root, "etc", "initramfs-tools", "conf.d", "casperize.conf"
    )
    if os.path.isfile(casperize):
        fails.append("Live casper initramfs config is still present.")
    overlay = os.path.join(root, "etc", "overlayroot.local.conf")
    if os.path.isfile(overlay):
        fails.append("overlayroot is still enabled.")
    snaps_dir = os.path.join(root, "var", "lib", "snapd", "snaps")
    if os.path.isdir(snaps_dir):
        try:
            names = os.listdir(snaps_dir)
        except OSError:
            names = []
        for name in names:
            if name.split("_", 1)[0] in LIVE_INSTALLER_SNAPS:
                fails.append("Live installer snap is still present.")
                break
    systemd = os.path.join(root, "etc", "systemd", "system")
    if os.path.isdir(systemd):
        try:
            walker = os.walk(systemd)
        except OSError:
            walker = []
        for _dirpath, _dirnames, filenames in walker:
            if any(_installer_snap_unit_name(n) for n in filenames):
                fails.append("Live installer snap mount is still present.")
                break
    return fails


def kernel_dpkg_debs(iso_mnt: str) -> list[str]:
    """Kernel/firmware debs to ``dpkg -i``, dependency-friendly order.

    Ubuntu live ISOs are not a working apt repo: ``Release`` sets
    ``Acquire-By-Hash: yes`` but ships no ``by-hash/`` files, and the pool
    omits packages already in the squashfs (kmod, linux-base). ``apt-get
    update`` from ``file:/cdrom`` fails. Install the pool debs with dpkg.
    Skip headers / the ``linux-generic-hwe-*`` metapackage (pulls headers).
    """
    buckets: dict[str, list[str]] = {
        "firmware": [],
        "microcode": [],
        "modules": [],
        "modules_extra": [],
        "image": [],
        "image_meta": [],
    }
    pool = os.path.join(iso_mnt, "pool")
    if not os.path.isdir(pool):
        return []
    for dirpath, _dirnames, filenames in os.walk(pool):
        for name in filenames:
            if not name.endswith(".deb"):
                continue
            path = os.path.join(dirpath, name)
            if "linux-firmware" in name:
                buckets["firmware"].append(path)
            elif "intel-microcode" in name or "amd64-microcode" in name:
                buckets["microcode"].append(path)
            elif name.startswith("linux-modules-extra-"):
                buckets["modules_extra"].append(path)
            elif name.startswith("linux-modules-"):
                buckets["modules"].append(path)
            elif name.startswith("linux-image-generic-hwe-") or name.startswith(
                "linux-image-generic_"
            ):
                buckets["image_meta"].append(path)
            elif name.startswith("linux-image-"):
                buckets["image"].append(path)
    out: list[str] = []
    for key in (
        "firmware",
        "microcode",
        "modules",
        "modules_extra",
        "image",
        "image_meta",
    ):
        out.extend(sorted(buckets[key]))
    return out


def dpkg_install_kernel_from_iso(
    root: str, iso_mnt: str, log: InstallLog | None = None
) -> None:
    debs = kernel_dpkg_debs(iso_mnt)
    if not debs:
        raise OsInstallError(_("Could not build the boot files."))
    if log:
        log.write(
            "dpkg -i kernel debs: " + " ".join(os.path.basename(d) for d in debs)
        )
    cdrom = os.path.join(root, "cdrom")
    os.makedirs(cdrom, exist_ok=True)
    already = os.path.ismount(cdrom)
    if not already:
        run_checked(
            ["mount", "--bind", iso_mnt, cdrom],
            what="mount the image for kernel packages",
        )
    rels = ["/cdrom/" + os.path.relpath(d, iso_mnt) for d in debs]
    try:
        code, _out = chroot_run(
            root,
            ["env", "DEBIAN_FRONTEND=noninteractive", "dpkg", "-i", *rels],
            log=log,
            timeout=600,
        )
        if code != 0:
            chroot_run(
                root,
                ["env", "DEBIAN_FRONTEND=noninteractive", "dpkg", "--configure", "-a"],
                log=log,
                timeout=300,
            )
        if not kernel_versions(root):
            raise OsInstallError(_("Could not build the boot files."))
    finally:
        if not already:
            umount_path(cdrom)


def apt_install_from_iso(
    root: str,
    iso_mnt: str,
    packages: tuple[str, ...] | list[str],
    log: InstallLog | None = None,
) -> None:
    """apt-get install from the ISO pool (curtin file:/cdrom).

    Ubuntu live ISOs often cannot ``apt-get update`` (Acquire-By-Hash
    without by-hash files). Prefer ``dpkg_install_kernel_from_iso``.
    """
    pkgs = [p for p in packages if p]
    if not pkgs:
        return
    if not iso_mnt or not os.path.isdir(iso_mnt):
        raise OsInstallError(_("Could not build the boot files."))
    if log:
        log.write("apt from ISO pool: " + " ".join(pkgs))
    cdrom = os.path.join(root, "cdrom")
    os.makedirs(cdrom, exist_ok=True)
    already = os.path.ismount(cdrom)
    if not already:
        run_checked(
            ["mount", "--bind", iso_mnt, cdrom],
            what="mount the image for kernel packages",
        )
    list_dir = os.path.join(root, "etc", "apt", "sources.list.d")
    os.makedirs(list_dir, exist_ok=True)
    list_path = os.path.join(list_dir, "fbl-cdrom.list")
    suite = iso_apt_suite(iso_mnt)
    with open(list_path, "w", encoding="utf-8") as fh:
        fh.write(f"deb [trusted=yes] file:/cdrom {suite} main restricted universe\n")
    apt_opts = [
        "-o",
        "Dir::Etc::sourcelist=/etc/apt/sources.list.d/fbl-cdrom.list",
        "-o",
        "Dir::Etc::sourceparts=/nonexistent",
        "-o",
        "APT::Get::List-Cleanup=0",
    ]
    try:
        code, _out = chroot_run(
            root,
            ["env", "DEBIAN_FRONTEND=noninteractive", "apt-get", "update", *apt_opts],
            log=log,
            timeout=180,
        )
        if code != 0:
            raise OsInstallError(_("Could not build the boot files."))
        code, _out = chroot_run(
            root,
            [
                "env",
                "DEBIAN_FRONTEND=noninteractive",
                "apt-get",
                "install",
                "-y",
                "--no-install-recommends",
                *apt_opts,
                "-o",
                "Dpkg::Options::=--force-confold",
                *pkgs,
            ],
            log=log,
            timeout=600,
        )
        if code != 0:
            raise OsInstallError(_("Could not build the boot files."))
    finally:
        try:
            os.unlink(list_path)
        except OSError:
            pass
        if not already:
            umount_path(cdrom)


def install_kernel_from_iso(
    root: str,
    iso_mnt: str,
    log: InstallLog | None = None,
    extra_packages: tuple[str, ...] = (),
) -> None:
    """Install the ISO's kernel package from pool/, like curtin curthooks.

    Desktop flavor squashfs often has no versioned initrd (the kernel lives
    in the live layer). Official install never copies that layer; it apt
    installs ``kernel.default`` from file:/cdrom. *extra_packages* is the
    matching 24.04 grub/shim set so we do not overlay First Boot 26.04 GRUB.
    """
    if installed_kernel_ok(root):
        return
    if kernel_versions(root):
        # Image is already in the squashfs (Cinnamon / Budgie 26.04). The
        # initrd is built by rebuild_initramfs with dracut. Do not
        # apt-install initramfs-tools: it Conflicts with dracut.
        if log:
            log.write("kernel image present; initrd via dracut/update-initramfs")
        return
    if extra_packages:
        # Bootloader debs are dpkg-deb -x'd in install_casper_bootloader.
        # Never apt-install grub-efi-amd64-signed here: its postinst runs
        # grub-install and fails without a mounted ESP (Could not build
        # the boot files).
        if log:
            log.write("kernel extra packages deferred to signed-EFI extract")
    dpkg_install_kernel_from_iso(root, iso_mnt, log=log)


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
    include_live: bool = False,
    copy_kernel: bool = True,
) -> None:
    rels = casper_squashfs_relpaths(
        iso_mnt, lang=lang, include_live=include_live
    )
    paths = squashfs_abs(iso_mnt, rels)
    if log:
        log.write("unpack layers " + " ".join(os.path.basename(p) for p in paths))
    unpack_layered_squashfs(paths, target_root, on_progress=on_progress, log=log)
    if on_progress:
        on_progress(100)
    if copy_kernel:
        _copy_casper_kernel(iso_mnt, target_root, log=log)


def unpack_casper_single(
    iso_mnt: str,
    target_root: str,
    *,
    on_progress: Callable[[int], None] | None = None,
    log: InstallLog | None = None,
) -> None:
    unpack_casper(iso_mnt, target_root, on_progress=on_progress, log=log)


def kernel_versions(root: str) -> list[str]:
    """Installed ``vmlinuz-*`` versions (real files, not dangling links)."""
    boot = os.path.join(root, "boot")
    if not os.path.isdir(boot):
        return []
    try:
        names = os.listdir(boot)
    except OSError:
        return []
    versions: list[str] = []
    for name in names:
        if not name.startswith("vmlinuz-") or name.endswith(".old"):
            continue
        path = os.path.join(boot, name)
        if os.path.isfile(path):
            versions.append(name[len("vmlinuz-") :])
    return versions


def installed_kernel_ok(root: str) -> bool:
    """True when GRUB's 10_linux will find a real vmlinuz-* and initrd.img-*.

    Unversioned ``vmlinuz`` / dangling ``initrd.img -> initrd.img-<ver>`` are
    not enough: GRUB skips them, or the kernel panics without an initrd.
    """
    boot = os.path.join(root, "boot")
    for ver in kernel_versions(root):
        for n in (
            f"initrd.img-{ver}",
            f"initrd-{ver}.img",
            f"initramfs-{ver}.img",
        ):
            path = os.path.join(boot, n)
            if os.path.isfile(path):
                return True
    return False


def _target_executable(root: str, rels: tuple[str, ...]) -> str:
    for rel in rels:
        path = os.path.join(root, rel.lstrip("/"))
        if os.path.isfile(path):
            return "/" + rel.lstrip("/")
    return ""


def strip_casper_initramfs(root: str, log: InstallLog | None = None) -> None:
    """Stop update-initramfs from baking the live overlay into the initrd."""
    for rel in CASPER_INITRAMFS_CONFS:
        path = os.path.join(root, rel)
        try:
            os.unlink(path)
        except OSError:
            continue
        if log:
            log.write(f"removed {rel}")
    for folder in CASPER_INITRAMFS_DIRS:
        base = os.path.join(root, folder)
        if not os.path.isdir(base):
            continue
        try:
            names = os.listdir(base)
        except OSError:
            continue
        for name in names:
            lower = name.lower()
            if "casper" not in lower and lower not in ("live", "live-boot"):
                continue
            path = os.path.join(base, name)
            if os.path.isdir(path):
                shutil.rmtree(path, ignore_errors=True)
            else:
                try:
                    os.unlink(path)
                except OSError:
                    pass
            if log:
                log.write(f"removed {folder}/{name}")


def pin_proc_cmdline(
    root: str, cmdline: str, log: InstallLog | None = None
) -> str:
    """Cover chroot ``/proc/cmdline`` so dracut does not bake FBL casper args."""
    if not cmdline.strip():
        return ""
    fake = os.path.join(root, "run", "fbl-proc-cmdline")
    os.makedirs(os.path.dirname(fake), exist_ok=True)
    with open(fake, "w", encoding="ascii") as fh:
        fh.write(cmdline.strip() + "\n")
    dest = os.path.join(root, "proc", "cmdline")
    if not os.path.isfile(dest):
        return ""
    proc = subprocess.run(
        ["mount", "--bind", fake, dest],
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return ""
    if log:
        log.write(f"pinned /proc/cmdline: {cmdline.strip()}")
    return dest


def rebuild_initramfs(root: str, log: InstallLog | None = None) -> None:
    """Create a disk-root initrd.

    Ubuntu GNOME / Mint ship initramfs-tools (``update-initramfs``).
    Ubuntu Cinnamon / Budgie 26.04 install layers ship **dracut** instead;
    initramfs-tools is only in the live layer (casper). ``-u`` is a no-op
    when no initrd exists yet.
    """
    update = _target_executable(
        root, ("usr/sbin/update-initramfs", "usr/bin/update-initramfs")
    )
    dracut = _target_executable(root, ("usr/bin/dracut", "usr/sbin/dracut"))
    if update:
        chroot_run(
            root, [update, "-u", "-k", "all"], log=log, timeout=300
        )
        if not installed_kernel_ok(root):
            chroot_run(
                root, [update, "-c", "-k", "all"], log=log, timeout=300
            )
    elif dracut:
        versions = kernel_versions(root)
        if not versions:
            raise OsInstallError(_("Could not build the boot files."))
        for ver in versions:
            dest = f"/boot/initrd.img-{ver}"
            code, _out = chroot_run(
                root,
                [
                    dracut,
                    "--force",
                    "--no-hostonly",
                    "--omit",
                    "dmsquash-live livenet casper",
                    dest,
                    ver,
                ],
                log=log,
                timeout=600,
            )
            if code != 0 and log:
                log.write(f"dracut {ver} failed ({code})")
    if not installed_kernel_ok(root):
        raise OsInstallError(_("Could not build the boot files."))


def _copy_casper_kernel(iso_mnt: str, target_root: str, log: InstallLog | None = None) -> None:
    boot = os.path.join(target_root, "boot")
    os.makedirs(boot, exist_ok=True)
    has_vmlinuz = any(
        name.startswith("vmlinuz-")
        for name in (os.listdir(boot) if os.path.isdir(boot) else [])
        if os.path.isfile(os.path.join(boot, name))
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


_LIGHTDM_AUTOLOGIN_RE = re.compile(
    r"(?im)^(autologin-user|autologin-user-timeout|autologin-guest|"
    r"autologin-session)\s*=.*\n?"
)


def _strip_lightdm_autologin_file(path: str) -> None:
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    new = _LIGHTDM_AUTOLOGIN_RE.sub("", text)
    if new != text:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(new)


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
    _strip_lightdm_autologin_file(
        os.path.join(root, "etc", "lightdm", "lightdm.conf")
    )
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
        lightdm_drop = "lightdm" in folder.replace("\\", "/")
        for name in names:
            lower = name.lower()
            path = os.path.join(folder, name)
            if "casper" in lower or "autologin" in lower or "live" in lower:
                try:
                    os.unlink(path)
                except OSError:
                    pass
            elif lightdm_drop:
                _strip_lightdm_autologin_file(path)
            elif "sddm" in folder.replace("\\", "/"):
                if not os.path.isfile(path):
                    continue
                with open(path, encoding="utf-8") as fh:
                    text = fh.read()
                new = re.sub(
                    r"(?im)^(AutomaticLoginEnable|AutomaticLogin)\s*=.*\n?",
                    "",
                    text,
                )
                new = re.sub(r"(?im)^User\s*=.*\n?", "", new)
                new = re.sub(r"(?im)^Session\s*=.*\n?", "", new)
                if new != text:
                    with open(path, "w", encoding="utf-8") as fh:
                        fh.write(new)
    autostart = os.path.join(root, "etc", "xdg", "autostart")
    if os.path.isdir(autostart):
        for name in LIVE_DESKTOPS:
            try:
                os.unlink(os.path.join(autostart, name))
            except OSError:
                pass


def filter_snap_seed(text: str, drop: set[str]) -> str:
    """Drop named snaps from snapd ``seed.yaml``."""
    match = re.search(r"^snaps:\s*$", text, re.M)
    if not match:
        return text
    head = text[: match.end()]
    rest = text[match.end() :]
    chunks = re.split(r"\n  -", rest)
    kept: list[str] = []
    for i, chunk in enumerate(chunks):
        if i == 0 and not chunk.strip():
            continue
        name_m = re.search(r"^\s*name:\s*(\S+)", chunk, re.M)
        if name_m and name_m.group(1) in drop:
            continue
        kept.append(chunk)
    if not kept:
        return head + "\n"
    return head + "".join("\n  -" + c for c in kept)


def strip_installer_snaps(root: str, log: InstallLog | None = None) -> None:
    """Remove live-session installer snaps so first boot cannot recreate them."""
    drop = set(LIVE_INSTALLER_SNAPS)
    seed = os.path.join(root, "var", "lib", "snapd", "seed", "seed.yaml")
    if os.path.isfile(seed):
        with open(seed, encoding="utf-8") as fh:
            text = fh.read()
        new = filter_snap_seed(text, drop)
        if new != text:
            with open(seed, "w", encoding="utf-8") as fh:
                fh.write(new)
            if log:
                log.write("stripped installer snaps from seed.yaml")
    for folder in (
        os.path.join(root, "var", "lib", "snapd", "snaps"),
        os.path.join(root, "var", "lib", "snapd", "seed", "snaps"),
        os.path.join(root, "var", "lib", "snapd", "seed", "assertions"),
    ):
        if not os.path.isdir(folder):
            continue
        try:
            names = os.listdir(folder)
        except OSError:
            continue
        for name in names:
            stem = name.split("_", 1)[0]
            if stem not in drop:
                continue
            try:
                os.unlink(os.path.join(folder, name))
            except OSError:
                continue
            if log:
                log.write(f"removed live snap {name}")
    snap_root = os.path.join(root, "snap")
    if os.path.isdir(snap_root):
        for name in drop:
            shutil.rmtree(os.path.join(snap_root, name), ignore_errors=True)
    systemd = os.path.join(root, "etc", "systemd", "system")
    if os.path.isdir(systemd):
        try:
            walker = list(os.walk(systemd, topdown=False))
        except OSError:
            walker = []
        for dirpath, dirnames, filenames in walker:
            for name in filenames:
                if not _installer_snap_unit_name(name):
                    continue
                path = os.path.join(dirpath, name)
                try:
                    os.unlink(path)
                except OSError:
                    continue
                if log:
                    log.write(f"removed live snap unit {name}")
            for name in dirnames:
                if not _installer_snap_unit_name(name):
                    continue
                shutil.rmtree(os.path.join(dirpath, name), ignore_errors=True)


CINNAMON_GENERIC_FACE = "usr/share/cinnamon/faces/user-generic.png"


def ensure_user_icon(
    root: str, username: str, log: InstallLog | None = None
) -> None:
    """Give the customer a face so slick-greeter does not use debian-logo.png.

    Ubuntu Cinnamon ships Debian's desktop-base; the greeter falls back to
    debian-logo.png unless AccountsService Icon is set. Prefer Cinnamon's
    generic face (``/usr/share/cinnamon/faces/user-generic.png``).
    """
    generic = os.path.join(root, CINNAMON_GENERIC_FACE)
    candidates = (
        generic,
        os.path.join(root, "usr", "share", "cinnamon", "faces", "4_cinnamon.jpg"),
        os.path.join(
            root, "usr", "share", "icons", "hicolor", "256x256", "apps", "ubuntu-logo-icon.png"
        ),
        os.path.join(root, "usr", "share", "pixmaps", "ubuntu-logo-icon.png"),
        os.path.join(root, "usr", "share", "pixmaps", "ubuntu-logo.png"),
    )
    src = ""
    for path in candidates:
        if os.path.isfile(path):
            src = path
            break
    if not src:
        return
    if src == generic:
        icon = "/" + CINNAMON_GENERIC_FACE
    else:
        icons = os.path.join(root, "var", "lib", "AccountsService", "icons")
        os.makedirs(icons, exist_ok=True)
        shutil.copy2(src, os.path.join(icons, username))
        icon = f"/var/lib/AccountsService/icons/{username}"
    home_face = os.path.join(root, "home", username, ".face")
    if not os.path.isfile(home_face):
        os.makedirs(os.path.dirname(home_face), exist_ok=True)
        shutil.copy2(src, home_face)
    acc_user = os.path.join(root, "var", "lib", "AccountsService", "users", username)
    os.makedirs(os.path.dirname(acc_user), exist_ok=True)
    with open(acc_user, "w", encoding="utf-8") as fh:
        fh.write(f"[User]\nSystemAccount=false\nIcon={icon}\n")
    if log:
        log.write(f"user icon {username} {icon}")


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
    iso_mnt: str = "",
    kernel_from_iso: bool = False,
    iso_packages: tuple[str, ...] = (),
) -> None:
    write_fstab(target_root, disk)
    write_hostname(target_root, identity.hostname)
    new_machine_id(target_root)
    write_locale(target_root, locale)
    write_timezone(target_root, timezone_minutes, log=log)
    delete_users(target_root, live_usernames, log=log)
    add_user(target_root, identity, log=log)
    ensure_user_icon(target_root, identity.username, log=log)
    set_graphical_target(target_root, display_manager, log=log)
    write_grub_default(target_root)
    disable_overlayroot(target_root, log=log)
    strip_live_autologin(target_root)
    strip_installer_snaps(target_root, log=log)
    strip_casper_initramfs(target_root, log=log)
    mounted = bind_chroot(target_root)
    try:
        if kernel_from_iso:
            install_kernel_from_iso(
                target_root, iso_mnt, log=log, extra_packages=iso_packages
            )
        elif iso_packages:
            apt_install_from_iso(target_root, iso_mnt, iso_packages, log=log)
        purge_live_packages(target_root, log=log)
        strip_casper_initramfs(target_root, log=log)
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
        pinned = pin_proc_cmdline(
            target_root,
            f"root=UUID={disk.root_uuid} ro quiet splash",
            log=log,
        )
        try:
            rebuild_initramfs(target_root, log=log)
        finally:
            if pinned:
                umount_path(pinned)
    finally:
        unbind_chroot(mounted)


def ensure_grub_efi_modules(
    root: str, iso_mnt: str = "", log: InstallLog | None = None
) -> None:
    """Ubuntu live layers often omit grub-efi-amd64-bin.

    Prefer the *ISO* modules (same series as that distro's signed grubx64)
    over First Boot's 26.04 tree. Mixing 26.04 grubx64 with 24.04 modules
    prints ``grub_efi_set_text_mode not found``.
    """
    dest = os.path.join(root, "usr", "lib", "grub", "x86_64-efi")
    if os.path.isfile(os.path.join(dest, "modinfo.sh")):
        return
    candidates: list[str] = []
    if iso_mnt:
        candidates.extend(
            (
                os.path.join(iso_mnt, "boot", "grub", "x86_64-efi"),
                os.path.join(iso_mnt, "usr", "lib", "grub", "x86_64-efi"),
            )
        )
    candidates.append("/usr/lib/grub/x86_64-efi")
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


def extract_signed_efi_debs(
    iso_mnt: str, target_root: str, log: InstallLog | None = None
) -> None:
    """Unpack 24.04 grub/shim debs from the ISO pool into *target* (no postinst).

    Includes ``grub2-common`` (``grub-install``) and ``grub-efi-amd64-bin``
    (modules). Does not unpack ``grub-efi-amd64`` — that postinst runs
    ``grub-install`` and fails without a mounted ESP.
    """
    if not iso_mnt or not os.path.isdir(iso_mnt):
        return
    pool = os.path.join(iso_mnt, "pool")
    if not os.path.isdir(pool):
        return
    debs: list[str] = []
    for dirpath, _dirnames, filenames in os.walk(pool):
        for name in filenames:
            if not name.endswith(".deb"):
                continue
            if name.startswith("shim-signed-common"):
                continue
            if name.startswith(BOOTLOADER_EXTRACT_PREFIXES):
                debs.append(os.path.join(dirpath, name))
    debs.sort()
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


def signed_efi_paths(root: str = "") -> tuple[str, str, str]:
    """Microsoft shim + Canonical *installed* grubx64.efi.signed + MokManager.

    Prefer the *target* tree's signed GRUB so 24.04 MATE is not overlaid
    with First Boot's 26.04 grubx64 (``grub_efi_set_text_mode not found``).
    Never return the live ISO's EFI/BOOT/grubx64.efi: that file is gcdx64
    (prefix /boot/grub). Shim loads it, GRUB finds no EFI/ubuntu config, grub>.
    """
    triples: list[tuple[str, str, str]] = []
    if root:
        triples.append(
            (
                os.path.join(root, "usr", "lib", "shim", "shimx64.efi.signed"),
                os.path.join(
                    root, "usr", "lib", "grub", "x86_64-efi-signed", "grubx64.efi.signed"
                ),
                os.path.join(root, "usr", "lib", "shim", "mmx64.efi.signed"),
            )
        )
        triples.append(
            (
                os.path.join(root, "usr", "lib", "shim", "shimx64.efi.signed"),
                os.path.join(
                    root, "usr", "lib", "grub", "x86_64-efi-signed", "grubx64.efi.signed"
                ),
                os.path.join(root, "usr", "lib", "shim", "mmx64.efi"),
            )
        )
    triples.append(
        (
            os.path.join(SIGNED_EFI_DIR, "shimx64.efi"),
            os.path.join(SIGNED_EFI_DIR, "grubx64.efi"),
            os.path.join(SIGNED_EFI_DIR, "mmx64.efi"),
        )
    )
    triples.append(
        (
            "/usr/lib/shim/shimx64.efi.signed",
            "/usr/lib/grub/x86_64-efi-signed/grubx64.efi.signed",
            "/usr/lib/shim/mmx64.efi",
        )
    )
    for shim, grub, mm in triples:
        if os.path.isfile(shim) and os.path.isfile(grub):
            return shim, grub, mm if os.path.isfile(mm) else ""
    return "", "", ""


def copy_signed_esp_binaries(
    efi_mp: str,
    bootloader_id: str,
    log: InstallLog | None = None,
    root: str = "",
) -> None:
    """Put Secure Boot shim + installed grubx64 on the ESP. Not live gcdx64.

    ``EFI/BOOT/`` is the removable fallback. Lenovo firmware launches every
    ``.efi`` in that folder as a *first-stage* loader. Canonical-signed
    ``grubx64.efi`` and ``mmx64.efi`` are not in the firmware db — only
    Microsoft-signed shim is. Putting them next to ``BOOTX64.EFI`` prints
    ``Error: Prohibited by secure boot policy.`` twice, then the NVRAM
    shim entry boots. GRUB and MokManager live under ``EFI/<id>/`` so
    shim loads them.
    """
    src_shim, src_grub, src_mm = signed_efi_paths(root)
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
            f"copied signed shim to EFI/BOOT and shim+grubx64.efi into EFI/{bootloader_id}"
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
    signed_grub = os.path.join(
        target_root, "usr", "lib", "grub", "x86_64-efi-signed", "grubx64.efi.signed"
    )
    grub_install = _target_executable(
        target_root, ("usr/sbin/grub-install", "usr/bin/grub-install")
    )
    if iso_mnt and (not os.path.isfile(signed_grub) or not grub_install):
        extract_signed_efi_debs(iso_mnt, target_root, log=log)
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
    copy_signed_esp_binaries(efi_mp, bootloader_id, log=log, root=target_root)
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
    fails = tree_health_check(
        target_root,
        efi_mp,
        identity,
        disk,
        display_manager=display_manager,
        boot_log=boot_log,
    )
    if not installed_kernel_ok(target_root):
        fails.append("No kernel + initrd under /boot.")
    fails.extend(casper_leftovers(target_root))
    seen: set[str] = set()
    out: list[str] = []
    for item in fails:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out
