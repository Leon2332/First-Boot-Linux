"""Pop!_OS shop pack — casper live ISO (COSMIC 24.04).

Catalog ``install``: ``pop-os``. This is a retailer driver, not a First Boot
Linux official module. Replace seed_files() with your unattended installer
(distinst / pop-installer) if you have one. This copy boots the live ISO
with casper so Pop's own installer can run, and drops FBL-DATA after toram
so that installer can take the disk.

Pop's live kernel is unsigned. Canonical GRUB (and Pop's own ISO GRUB)
refuse it when Secure Boot is on: "bad shim signature" / "you need to
load the kernel first". That is not a damaged ISO. Refuse here instead
of handing off. With Secure Boot off, BootNext Pop's shim like Fedora.
"""

from __future__ import annotations

import os

from firstboot.installlocale import InstallLocale
from firstboot.osinstall.common import (
    OsIdentity,
    OsInstallError,
    OsInstallPlan,
    install_vendor_shim,
    secure_boot_enabled,
)

ID = "pop-os"
ALIASES: tuple[str, ...] = ()
BOOTNEXT_LABEL = "Install Pop!_OS"
UNSIGNED_KERNEL = (
    "Pop!_OS cannot install while Secure Boot is on. "
    "The installer kernel is not signed, so boot stops at a shim signature error."
)

DROP_FBL_DATA = """#!/bin/sh
PREREQ=""
prereqs() { echo "$PREREQ"; }
case $1 in
prereqs) prereqs; exit 0 ;;
esac

mkdir -p /root/var/log
log=/root/var/log/firstboot-pop-os.log
echo "cmdline: $(cat /proc/cmdline 2>/dev/null)" > "$log"

if grep -qw toram /proc/cmdline; then
  if command -v losetup >/dev/null; then
    losetup -ln -O NAME,BACK-FILE 2>/dev/null | while read -r _name _back; do
      [ -n "$_name" ] || continue
      case "$_back" in
        *isodevice*|*FBL-DATA*)
          umount -l "$_name" 2>/dev/null || true
          losetup -d "$_name" 2>/dev/null || true
          ;;
      esac
    done
  fi
  for _mp in /isodevice /root/isodevice /run/payload; do
    umount -l "$_mp" 2>/dev/null || true
  done
  _dev=$(blkid -L FBL-DATA 2>/dev/null) || true
  if [ -n "$_dev" ]; then
    umount -l "$_dev" 2>/dev/null || true
  fi
  swapoff -a 2>/dev/null || true
fi
exit 0
"""


def pop_casper_dir(iso_mnt: str) -> str:
    """Pop ISOs put casper files in casper_pop-os_* ; casper is a symlink."""
    found: list[str] = []
    try:
        names = os.listdir(iso_mnt)
    except OSError as exc:
        raise OsInstallError("This image is not a Pop!_OS live ISO.") from exc
    for name in names:
        if not name.startswith("casper"):
            continue
        path = os.path.join(iso_mnt, name)
        if not os.path.isdir(path):
            continue
        for kern in ("vmlinuz.efi", "vmlinuz"):
            if os.path.isfile(os.path.join(path, kern)):
                found.append(os.path.realpath(path))
                break
    if not found:
        raise OsInstallError("This image is not a Pop!_OS live ISO.")
    for path in found:
        if os.path.basename(path) != "casper":
            return path
    return found[0]


class PopOS:
    id = ID
    aliases = ALIASES
    default_hostname = "pop-os"

    def __init__(self) -> None:
        self._casper_name = "casper"

    def boot_files(self, iso_mnt: str) -> tuple[str, str]:
        if secure_boot_enabled() is True:
            raise OsInstallError(UNSIGNED_KERNEL)
        casper = pop_casper_dir(iso_mnt)
        self._casper_name = os.path.basename(casper)
        vmlinuz = ""
        for name in ("vmlinuz.efi", "vmlinuz"):
            path = os.path.join(casper, name)
            if os.path.isfile(path):
                vmlinuz = path
                break
        initrd = ""
        for name in ("initrd.gz", "initrd.lz", "initrd"):
            path = os.path.join(casper, name)
            if os.path.isfile(path):
                initrd = path
                break
        if vmlinuz and initrd:
            return vmlinuz, initrd
        raise OsInstallError("This image is not a Pop!_OS live ISO.")

    def kernel_args(self, iso_rel: str, *, toram: bool, iso_path: str = "") -> str:
        extra = "hostname=pop-os username=pop-os"
        blob = f"{iso_rel} {iso_path}".lower()
        if "nvidia" in blob:
            extra += " modules_load=nvidia nvidia-drm.modeset=1"
        flag = "toram " if toram else ""
        casper = self._casper_name or "casper"
        return (
            f"boot=casper iso-scan/filename={iso_rel} live-media-path=/{casper} "
            f"ignore_uuid nopersistent noprompt {flag}{extra}"
        ).rstrip()

    def seed_files(
        self,
        identity: OsIdentity,
        target_path: str,
        serial: str,
        locale: InstallLocale | None = None,
    ) -> dict[str, str | bytes]:
        _ = identity, target_path, serial, locale
        return {
            "scripts/casper-bottom/29fbl-pop": DROP_FBL_DATA,
        }

    def after_prepare(
        self,
        iso_mnt: str,
        plan: OsInstallPlan,
        sys_uuid: str,
        label: str,
        linux_args: str,
    ) -> None:
        install_vendor_shim(
            iso_mnt,
            plan,
            sys_uuid,
            label,
            linux_args,
            bootnext_label=BOOTNEXT_LABEL,
        )


DRIVER = PopOS()
