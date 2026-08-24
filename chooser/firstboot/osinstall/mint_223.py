"""Linux Mint 22.3 — Ubiquity preseed.

Catalog ``install``: ``mint-223``. Alias ``mint`` (older sticks).
All three DEs (Cinnamon / MATE / Xfce) share this installer.
Do not feed Mint an autoinstall YAML. Do not pass only-ubiquity.
"""

from __future__ import annotations

from firstboot.osinstall.common import (
    OsIdentity,
    casper_boot_files,
    casper_kernel_args,
    kernel_disk_path,
)

ID = "mint-223"
ALIASES = ("mint",)
LINUX_EXTRA = "username=mint hostname=mint automatic-ubiquity"

EFI_CLEANUP = """#!/bin/sh
for n in $(efibootmgr 2>/dev/null | sed -n 's/^Boot\\([0-9A-Fa-f]\\{4\\}\\).*First Boot Linux.*/\\1/p'); do
  efibootmgr -b "$n" -B || true
done
exit 0
"""

CASPER_BOTTOM = """#!/bin/sh
PREREQ=""
prereqs() { echo "$PREREQ"; }
case $1 in
prereqs) prereqs; exit 0 ;;
esac

mkdir -p /root/var/log /root/usr/lib
log=/root/var/log/firstboot-mint.log
{
  echo "cmdline: $(cat /proc/cmdline 2>/dev/null)"
  cat /root/etc/hostname 2>/dev/null
  ls -l /preseed.cfg /scripts/casper-bottom/29fbl-mint 2>&1
  lsblk -o NAME,LABEL,MOUNTPOINT,TYPE 2>/dev/null
} > "$log"

if [ -f /preseed.cfg ]; then
  cp /preseed.cfg /root/preseed.cfg
  chmod 644 /root/preseed.cfg
fi

if [ -f /usr/lib/firstboot-efi-cleanup ]; then
  cp /usr/lib/firstboot-efi-cleanup /root/usr/lib/firstboot-efi-cleanup
  chmod 755 /root/usr/lib/firstboot-efi-cleanup
fi

if grep -qw toram /proc/cmdline; then
  {
    echo "=== drop FBL-DATA after toram ==="
    findmnt 2>/dev/null
    losetup -a 2>/dev/null
  } >> "$log" 2>&1
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
  {
    echo "=== after ==="
    findmnt 2>/dev/null
    losetup -a 2>/dev/null
    lsblk -o NAME,LABEL,MOUNTPOINT,TYPE 2>/dev/null
  } >> "$log" 2>&1
fi

echo "live_preseed=$(test -f /root/preseed.cfg && echo yes || echo no)" >> "$log"
exit 0
"""


def preseed_line(owner: str, key: str, kind: str, value: str) -> str:
    return f"{owner} {key} {kind} {value}"


def mint_preseed(identity: OsIdentity, target_path: str) -> str:
    """Ubiquity preseed for Mint 22.3. Not Subiquity autoinstall."""
    disk = kernel_disk_path(target_path)
    lines = [
        preseed_line("d-i", "debian-installer/locale", "string", "en_US.UTF-8"),
        preseed_line("d-i", "debian-installer/language", "string", "en"),
        preseed_line("d-i", "debian-installer/country", "string", "US"),
        preseed_line("d-i", "localechooser/languagelist", "string", "en"),
        preseed_line("d-i", "languagechooser/language-name", "string", "English"),
        preseed_line("d-i", "countrychooser/shortlist", "select", "US"),
        preseed_line(
            "d-i", "localechooser/supported-locales", "multiselect", "en_US.UTF-8"
        ),
        preseed_line("d-i", "keyboard-configuration/layoutcode", "string", "us"),
        preseed_line("d-i", "keyboard-configuration/xkb-keymap", "select", "us"),
        preseed_line("d-i", "keyboard-configuration/modelcode", "string", "pc105"),
        preseed_line("d-i", "console-setup/ask_detect", "boolean", "false"),
        preseed_line("d-i", "console-setup/layoutcode", "string", "us"),
        preseed_line("d-i", "time/zone", "string", "UTC"),
        preseed_line("d-i", "clock-setup/utc", "boolean", "true"),
        preseed_line("d-i", "clock-setup/ntp", "boolean", "false"),
        preseed_line("d-i", "netcfg/get_hostname", "string", identity.hostname),
        preseed_line("d-i", "passwd/user-fullname", "string", identity.realname),
        preseed_line("d-i", "passwd/username", "string", identity.username),
        preseed_line(
            "d-i", "passwd/user-password-crypted", "password", identity.password_hash
        ),
        preseed_line("d-i", "passwd/auto-login", "boolean", "false"),
        preseed_line("d-i", "user-setup/allow-password-weak", "boolean", "true"),
        preseed_line("d-i", "user-setup/encrypt-home", "boolean", "false"),
        preseed_line("d-i", "partman-auto/method", "string", "regular"),
        preseed_line("d-i", "partman-auto/disk", "string", disk),
        preseed_line(
            "d-i", "partman-auto/init_automatically_partition", "select", "regular"
        ),
        preseed_line("d-i", "partman-auto/choose_recipe", "select", "atomic"),
        preseed_line("d-i", "partman-auto/purge_lvm_from_device", "boolean", "true"),
        preseed_line("d-i", "partman-lvm/device_remove_lvm", "boolean", "true"),
        preseed_line("d-i", "partman-md/device_remove_md", "boolean", "true"),
        preseed_line("d-i", "partman-lvm/confirm", "boolean", "true"),
        preseed_line("d-i", "partman-md/confirm", "boolean", "true"),
        preseed_line("d-i", "partman-lvm/confirm_nooverwrite", "boolean", "true"),
        preseed_line(
            "d-i", "partman-partitioning/confirm_write_new_label", "boolean", "true"
        ),
        preseed_line("d-i", "partman/choose_partition", "select", "finish"),
        preseed_line("d-i", "partman/confirm", "boolean", "true"),
        preseed_line("d-i", "partman/confirm_nooverwrite", "boolean", "true"),
        preseed_line("d-i", "partman/confirm_write_new_label", "boolean", "true"),
        preseed_line("d-i", "grub-installer/only_debian", "boolean", "true"),
        preseed_line("d-i", "grub-installer/with_other_os", "boolean", "false"),
        preseed_line("ubiquity", "ubiquity/use_nonfree", "boolean", "false"),
        preseed_line("ubiquity", "ubiquity/download_updates", "boolean", "false"),
        preseed_line("ubiquity", "ubiquity/partman-skip-unmount", "boolean", "true"),
        preseed_line("ubiquity", "ubiquity/summary", "string", ""),
        preseed_line("ubiquity", "ubiquity/reboot", "boolean", "true"),
        preseed_line("ubiquity", "ubiquity/reboot_on_failure", "boolean", "false"),
        preseed_line(
            "ubiquity",
            "ubiquity/success_command",
            "string",
            "/usr/lib/firstboot-efi-cleanup",
        ),
    ]
    return "\n".join(lines) + "\n"


class Mint223:
    id = ID
    aliases = ALIASES
    default_hostname = "mint"

    def boot_files(self, iso_mnt: str) -> tuple[str, str]:
        return casper_boot_files(iso_mnt)

    def kernel_args(self, iso_rel: str, *, toram: bool, iso_path: str = "") -> str:
        return casper_kernel_args(iso_rel, toram=toram, extra=LINUX_EXTRA)

    def seed_files(
        self, identity: OsIdentity, target_path: str, serial: str
    ) -> dict[str, str | bytes]:
        return {
            "preseed.cfg": mint_preseed(identity, target_path),
            "usr/lib/firstboot-efi-cleanup": EFI_CLEANUP,
            "scripts/casper-bottom/29fbl-mint": CASPER_BOTTOM,
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


DRIVER = Mint223()
