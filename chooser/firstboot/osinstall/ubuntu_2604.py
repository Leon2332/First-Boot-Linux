"""Ubuntu 26.04 LTS — Subiquity autoinstall.

Catalog ``install``: ``ubuntu-2604``. Alias ``ubuntu-autoinstall`` (older sticks).
Do not feed this YAML to Mint or Fedora.
"""

from __future__ import annotations

from firstboot.installlocale import InstallLocale
from firstboot.osinstall.common import (
    OsIdentity,
    casper_boot_files,
    casper_kernel_args,
    kernel_disk_path,
    yaml_str,
)

ID = "ubuntu-2604"
ALIASES = ("ubuntu-autoinstall",)
LINUX_EXTRA = "autoinstall subiquity.autoinstallpath=/autoinstall.yaml"

FREE_ISO_BACKING = r"""
free_iso_backing() {
  _log=${1:-/dev/null}
  {
    echo "=== free_iso_backing ==="
    cat /proc/cmdline 2>/dev/null
    losetup -a 2>/dev/null
    findmnt 2>/dev/null
    lsblk -o NAME,LABEL,MOUNTPOINT,TYPE 2>/dev/null
  } >> "$_log" 2>&1

  mkdir -p /run/fbl-casper /media/filesystem
  _sq=
  for _p in /cdrom/casper/filesystem.squashfs /root/cdrom/casper/filesystem.squashfs /run/casper/filesystem.squashfs; do
    if [ -f "$_p" ]; then
      _sq=$_p
      break
    fi
  done
  if [ -n "$_sq" ] && [ ! -f /run/fbl-casper/filesystem.squashfs ]; then
    cp -a "$_sq" /run/fbl-casper/filesystem.squashfs >> "$_log" 2>&1 || true
  fi
  if [ -f /run/fbl-casper/filesystem.squashfs ]; then
    umount -l /media/filesystem 2>/dev/null || true
    mount -t squashfs -o loop,ro /run/fbl-casper/filesystem.squashfs /media/filesystem >> "$_log" 2>&1 || true
  fi

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

  if command -v blkid >/dev/null; then
    _dev=$(blkid -L FBL-DATA 2>/dev/null) || true
    if [ -n "$_dev" ]; then
      umount -l "$_dev" 2>/dev/null || true
      if command -v findmnt >/dev/null; then
        findmnt -n -o TARGET "$_dev" 2>/dev/null | while read -r _t; do
          umount -l "$_t" 2>/dev/null || true
        done
      fi
    fi
  fi

  swapoff -a 2>/dev/null || true
  udevadm settle 2>/dev/null || true

  {
    echo "=== after ==="
    losetup -a 2>/dev/null
    findmnt 2>/dev/null
    lsblk -o NAME,LABEL,MOUNTPOINT,TYPE 2>/dev/null
    ls -l /media/filesystem /run/fbl-casper 2>/dev/null
  } >> "$_log" 2>&1
}
"""

CASPER_BOTTOM = (
    """#!/bin/sh
PREREQ=""
prereqs() { echo "$PREREQ"; }
case $1 in
prereqs) prereqs; exit 0 ;;
esac

mkdir -p /root/var/log /root/var/lib/cloud/seed/nocloud
log=/root/var/log/firstboot-autoinstall.log
{
  echo "cmdline: $(cat /proc/cmdline 2>/dev/null)"
  ls -l /autoinstall.yaml /user-data /scripts/casper-bottom/29fbl-autoinstall 2>&1
} > "$log"

if [ -f /autoinstall.yaml ]; then
  cp /autoinstall.yaml /root/autoinstall.yaml
  chmod 644 /root/autoinstall.yaml
fi
if [ -f /user-data ]; then
  cp /user-data /root/var/lib/cloud/seed/nocloud/user-data
  printf '%s\\n' "instance-id: nocloud" > /root/var/lib/cloud/seed/nocloud/meta-data
  chmod 644 /root/var/lib/cloud/seed/nocloud/user-data
  chmod 644 /root/var/lib/cloud/seed/nocloud/meta-data
fi

"""
    + FREE_ISO_BACKING
    + """
if grep -qw toram /proc/cmdline; then
  free_iso_backing "$log"
  cp "$log" /root/var/log/firstboot-autoinstall.log 2>/dev/null || true
fi

echo "live_autoinstall=$(test -f /root/autoinstall.yaml && echo yes || echo no)" >> "$log"
exit 0
"""
)


def autoinstall_yaml(
    identity: OsIdentity,
    target_path: str,
    serial: str = "",
    locale: InstallLocale | None = None,
) -> str:
    loc = locale or InstallLocale()
    path = kernel_disk_path(target_path)
    if serial:
        match = (
            "      match:\n"
            f"        - serial: {yaml_str(serial)}\n"
            f"        - path: {yaml_str(path)}\n"
        )
    else:
        match = "      match:\n" f"        path: {yaml_str(path)}\n"
    packs = ""
    if loc.langpack and loc.langpack != "en":
        packs = (
            "    - curtin in-target -- apt-get install -y "
            f"language-pack-{loc.langpack} language-pack-gnome-{loc.langpack} "
            "|| true\n"
        )
    return (
        "autoinstall:\n"
        "  version: 1\n"
        f"  locale: {loc.glibc}\n"
        "  keyboard:\n"
        f"    layout: {loc.keyboard}\n"
        "  identity:\n"
        f"    hostname: {yaml_str(identity.hostname)}\n"
        f"    realname: {yaml_str(identity.realname)}\n"
        f"    username: {yaml_str(identity.username)}\n"
        f"    password: {yaml_str(identity.password_hash)}\n"
        "  storage:\n"
        "    layout:\n"
        "      name: direct\n"
        + match
        + "  early-commands:\n"
        "    - |\n"
        "        mkdir -p /run/fbl-casper /media/filesystem\n"
        "        sq=\n"
        "        for p in /cdrom/casper/filesystem.squashfs /run/casper/filesystem.squashfs; do\n"
        "          [ -f \"$p\" ] && sq=$p && break\n"
        "        done\n"
        "        if [ -n \"$sq\" ] && [ ! -f /run/fbl-casper/filesystem.squashfs ]; then\n"
        "          cp -a \"$sq\" /run/fbl-casper/filesystem.squashfs || true\n"
        "        fi\n"
        "        if [ -f /run/fbl-casper/filesystem.squashfs ]; then\n"
        "          umount -l /media/filesystem 2>/dev/null || true\n"
        "          mount -t squashfs -o loop,ro /run/fbl-casper/filesystem.squashfs /media/filesystem || true\n"
        "        fi\n"
        "        losetup -ln -O NAME,BACK-FILE 2>/dev/null | while read name back; do\n"
        "          case \"$back\" in\n"
        "            *isodevice*|*FBL-DATA*) umount -l \"$name\" 2>/dev/null || true; losetup -d \"$name\" 2>/dev/null || true ;;\n"
        "          esac\n"
        "        done\n"
        "        umount -l /isodevice /run/payload 2>/dev/null || true\n"
        "        dev=$(blkid -L FBL-DATA 2>/dev/null) || true\n"
        "        [ -n \"$dev\" ] && umount -l \"$dev\" 2>/dev/null || true\n"
        "        swapoff -a 2>/dev/null || true\n"
        "        udevadm settle 2>/dev/null || true\n"
        "  late-commands:\n"
        "    - |\n"
        "        for n in $(efibootmgr 2>/dev/null | sed -n 's/^Boot\\([0-9A-Fa-f]\\{4\\}\\).*First Boot Linux.*/\\1/p'); do\n"
        "          efibootmgr -b \"$n\" -B || true\n"
        "        done\n"
        + packs
        + "  apt:\n"
        "    fallback: offline-install\n"
        "    geoip: false\n"
        "  shutdown: reboot\n"
    )


def cloud_config_user_data(
    identity: OsIdentity,
    target_path: str,
    serial: str = "",
    locale: InstallLocale | None = None,
) -> str:
    return "#cloud-config\n" + autoinstall_yaml(
        identity, target_path, serial=serial, locale=locale
    )


class Ubuntu2604:
    id = ID
    aliases = ALIASES
    default_hostname = "ubuntu"

    def boot_files(self, iso_mnt: str) -> tuple[str, str]:
        return casper_boot_files(iso_mnt)

    def kernel_args(self, iso_rel: str, *, toram: bool, iso_path: str = "") -> str:
        return casper_kernel_args(iso_rel, toram=toram, extra=LINUX_EXTRA)

    def seed_files(
        self,
        identity: OsIdentity,
        target_path: str,
        serial: str,
        locale: InstallLocale | None = None,
    ) -> dict[str, str | bytes]:
        return {
            "autoinstall.yaml": autoinstall_yaml(
                identity, target_path, serial=serial, locale=locale
            ),
            "user-data": cloud_config_user_data(
                identity, target_path, serial=serial, locale=locale
            ),
            "scripts/casper-bottom/29fbl-autoinstall": CASPER_BOTTOM,
        }

    def after_prepare(
        self,
        iso_mnt: str,
        plan: object,
        sys_uuid: str,
        label: str,
        linux_args: str,
    ) -> None:
        return


DRIVER = Ubuntu2604()
