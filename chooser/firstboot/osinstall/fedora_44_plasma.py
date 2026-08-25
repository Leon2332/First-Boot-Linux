"""Fedora 44 KDE Plasma — Anaconda kickstart from the live ISO.

Catalog ``install``: ``fedora-44-plasma``. Alias ``fedora-kickstart`` (older sticks).
Do not feed Fedora autoinstall YAML or a casper cmdline. Official liveinst
rejects inst.ks. Keep official liveinst; liveimg so Anaconda cannot DNF.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile

from firstboot.osinstall.common import (
    OsIdentity,
    OsInstallError,
    OsInstallPlan,
    efi_part_number,
    iso_volume_id,
    kernel_disk_path,
    kickstart_disk_id,
    kickstart_gecos,
    run_checked,
)

ID = "fedora-44-plasma"
ALIASES = ("fedora-kickstart",)
LIVE_LABEL = "Fedora-KDE-Live-44"
LINUX_FLAG = "fbl.install"
BOOTNEXT_LABEL = "Install Fedora"
SQUASH_LINK = "/run/fbl-squashfs.img"

LIVEINST_WRAPPER = """#!/bin/bash
# Session front door. Official liveinst pkexecs $0 (this path — the
# polkit rule is /usr/bin/liveinst). Do not exec anaconda here (0.6.41:
# no display, then DNF). LIVECMD does not survive pkexec — pre-pivot
# patches liveinst.real's ANACONDA default.
#
# 0.6.44 ran the linker as liveuser via sudo -n / pkexec of the helper.
# Polkit allows liveinst, not fbl-link-squashfs, so that failed and
# zenity fired before we ever became root. Become root first, then link.
log=/var/log/firstboot-fedora.log
link=/usr/libexec/fbl-link-squashfs
wayland_socket=/tmp/anaconda-wldisplay
mkdir -p /var/log /run
{
  echo "=== fbl liveinst wrapper ==="
  date
  echo "uid=$(id -u) WAYLAND_DISPLAY=${WAYLAND_DISPLAY-} DISPLAY=${DISPLAY-} PKEXEC_UID=${PKEXEC_UID-}"
  cat /proc/cmdline 2>/dev/null
  ls -l /ks.cfg /usr/bin/liveinst /usr/bin/liveinst.real /usr/sbin/liveinst.real /run/fbl-squashfs.img "$link" 2>/dev/null
} >> "$log" 2>&1

ensure_link() {
  if [ -e /run/fbl-squashfs.img ] && [ -s /run/fbl-squashfs.img ]; then
    return 0
  fi
  if [ ! -x "$link" ]; then
    echo "fbl-link-squashfs missing" >> "$log"
    return 1
  fi
  if [ "$(id -u)" -ne 0 ]; then
    echo "ensure_link skipped; not root" >> "$log"
    return 1
  fi
  "$link" >> "$log" 2>&1 || true
  [ -e /run/fbl-squashfs.img ] && [ -s /run/fbl-squashfs.img ]
}

# liveinst.real restores WAYLAND_DISPLAY from this file after pkexec.
if [ -n "${WAYLAND_DISPLAY:-}" ]; then
  rm -f "$wayland_socket"
  echo "${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/${WAYLAND_DISPLAY}" > "$wayland_socket"
fi

# Polkit exec.path is /usr/bin/liveinst. pkexec that path, not the linker.
if [ "$(id -u)" -ne 0 ]; then
  echo "pkexec $0 (not root)" >> "$log"
  pkexec /usr/bin/liveinst "$@"
  rc=$?
  echo "pkexec returned $rc" >> "$log"
  exit $rc
fi

# livesys-late may still call us as root before SDDM. Make the liveimg
# alias now; do not start Anaconda without a compositor.
if [ -z "${PKEXEC_UID:-}" ] && [ -z "${WAYLAND_DISPLAY:-}" ] && [ -z "${DISPLAY:-}" ]; then
  ensure_link || true
  echo "root without display; session autostart will start liveinst" >> "$log"
  exit 0
fi

if ! ensure_link; then
  echo "squashfs link missing; refusing to start (would DNF)" >> "$log"
  ls -la /run/initramfs /run/initramfs/live /run/initramfs/live/LiveOS /run/initramfs/isoscan 2>> "$log" || true
  if command -v zenity >/dev/null 2>&1 && [ -n "${WAYLAND_DISPLAY:-}${DISPLAY:-}" ]; then
    zenity --error --no-markup --text="First Boot Linux could not find the Fedora live image." || true
  fi
  exit 1
fi

if [ -x /usr/libexec/fbl-selinux ]; then
  /usr/libexec/fbl-selinux >> "$log" 2>&1 || true
fi

real=
for p in /usr/bin/liveinst.real /usr/sbin/liveinst.real; do
  if [ -x "$p" ]; then
    real=$p
    break
  fi
done
if [ -z "$real" ]; then
  echo "liveinst.real missing" >> "$log"
  exit 1
fi

exec "$real" "$@"
"""

LINK_SQUASH = """#!/bin/bash
# Alias the live image so kickstart liveimg cannot DNF.
# Same-disk boots use rd.live.ram=1; F44 dmsquash then copies to
# /run/initramfs/squashed.img. 0.6.43 only looked for squashfs.img and
# waited for a systemd oneshot. 0.6.44 still zenity-failed: the wrapper
# ran the linker as liveuser (polkit denies it) and never created the
# alias in pre-pivot, while /run still had the image. Run this from
# pre-pivot (initramfs /run survives switch_root) and again as root.
root=${FBL_LIVE_ROOT:-}
log="$root/var/log/firstboot-fedora.log"
dest="$root/run/fbl-squashfs.img"
mkdir -p "$root/var/log" "$root/run"
sq=

is_image() {
  [ -f "$1" ] && [ -s "$1" ]
}

for p in \\
  "$root/run/initramfs/squashed.img" \\
  "$root/run/initramfs/live/LiveOS/squashfs.img" \\
  "$root/run/initramfs/live/LiveOS/rootfs.img" \\
  "$root/run/initramfs/live/squashfs.img" \\
  "$root/run/initramfs/rootfs.img" \\
  "$root/run/initramfs/squashfs.img" \\
  "$root/run/live/medium/LiveOS/squashfs.img" \\
  "$root/run/rootfsbase"
do
  if is_image "$p"; then
    sq=$p
    break
  fi
done
if [ -z "$sq" ]; then
  for p in "$root"/run/initramfs/isoscan/images/*.iso \\
           "$root"/run/initramfs/isoscan/*.iso \\
           "$root"/run/initramfs/isoscan/*/*.iso; do
    if is_image "$p"; then
      sq=$p
      break
    fi
  done
fi
if [ -z "$sq" ] && command -v losetup >/dev/null; then
  while IFS= read -r back; do
    [ -z "$back" ] && continue
    if is_image "$back"; then
      sq=$back
      break
    fi
  done <<EOF
$(losetup -ln -O BACK-FILE 2>/dev/null)
EOF
fi
if [ -z "$sq" ] && command -v findmnt >/dev/null; then
  src=$(findmnt -n -o SOURCE /run/rootfsbase 2>/dev/null || true)
  if [ -n "$src" ] && command -v losetup >/dev/null; then
    back=$(losetup -n -O BACK-FILE "$src" 2>/dev/null || true)
    if is_image "$back"; then
      sq=$back
    fi
  fi
fi
if [ -z "$sq" ]; then
  sq=$(find "$root/run/initramfs" "$root/run/live" "$root/mnt" -type f \\
    \\( -name squashfs.img -o -name squashed.img -o -name rootfs.img -o -name '*.iso' \\) \\
    2>/dev/null | head -n 1)
fi
{
  echo "=== fbl link squashfs ==="
  date
  echo "squashfs=${sq:-missing}"
  cat /proc/cmdline 2>/dev/null
  ls -la "$root/run/initramfs" "$root/run/initramfs/live" \\
    "$root/run/initramfs/live/LiveOS" "$root/run/initramfs/isoscan" \\
    "$root/run/initramfs/isoscan/images" 2>/dev/null
  findmnt /run/initramfs/live /run/initramfs/isoscan /run/rootfsbase 2>/dev/null
  losetup -a 2>/dev/null
} >> "$log" 2>&1
if [ -n "$sq" ]; then
  rm -f "$dest"
  if ln "$sq" "$dest" 2>/dev/null; then
    echo "hardlinked $sq -> $dest" >> "$log"
  elif cp -f --reflink=auto "$sq" "$dest" 2>/dev/null; then
    echo "copied $sq -> $dest" >> "$log"
  else
    ln -sfn "$sq" "$dest"
    echo "symlinked $sq -> $dest" >> "$log"
  fi
fi
exit 0
"""

LINK_SERVICE = """[Unit]
Description=First Boot Linux Fedora live image
After=local-fs.target
Before=display-manager.service

[Service]
Type=oneshot
# Labeled Fedora binaries first: unlabeled copies AVC if we exec them
# while still enforcing. Official liveinst also setenforce 0.
ExecStart=-/usr/sbin/setenforce 0
ExecStart=-/usr/sbin/restorecon -F /ks.cfg /usr/bin/liveinst /usr/bin/liveinst.real /usr/sbin/liveinst /usr/sbin/liveinst.real /usr/libexec/fbl-link-squashfs /usr/libexec/fbl-selinux /etc/systemd/system/fbl-link-squashfs.service /etc/xdg/autostart/fbl-liveinst.desktop /var/log/firstboot-fedora.log
ExecStart=/usr/libexec/fbl-link-squashfs
ExecStart=/usr/libexec/fbl-selinux
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
WantedBy=graphical.target
"""

FBL_SELINUX = """#!/bin/bash
# Live overlay only — liveimg copies squashfs.img, not this layer.
# Pre-pivot cp leaves unlabeled_t. restorecon in the initramfs used
# /sysroot/usr/bin/liveinst, which matches no file_contexts rule, so
# pkexec liveinst and Anaconda liveimg AVC'd. 0.6.45: setroubleshoot
# balloon on Plasma. Relabel after pivot; setenforce 0 like official
# liveinst; hide the applet so leftover AVCs stay off the desktop.
log=/var/log/firstboot-fedora.log
mkdir -p /var/log /etc/xdg/autostart /etc/systemd/system
{
  echo "=== fbl selinux ==="
  date
  echo "uid=$(id -u) getenforce=$(getenforce 2>/dev/null || echo missing)"
  ls -Z /ks.cfg /usr/bin/liveinst /usr/bin/liveinst.real \\
    /usr/libexec/fbl-link-squashfs /run/fbl-squashfs.img 2>/dev/null || true
} >> "$log" 2>&1

if [ -x /usr/sbin/setenforce ]; then
  /usr/sbin/setenforce 0 >> "$log" 2>&1 || true
fi

if command -v restorecon >/dev/null; then
  restorecon -F /ks.cfg \\
    /usr/bin/liveinst /usr/bin/liveinst.real \\
    /usr/sbin/liveinst /usr/sbin/liveinst.real \\
    /usr/libexec/fbl-link-squashfs /usr/libexec/fbl-selinux \\
    /etc/systemd/system/fbl-link-squashfs.service \\
    /etc/xdg/autostart/fbl-liveinst.desktop \\
    /var/log/firstboot-fedora.log >> "$log" 2>&1 || true
fi

if [ -e /run/fbl-squashfs.img ]; then
  ref=
  for p in /run/initramfs/squashed.img \\
           /run/initramfs/live/LiveOS/squashfs.img \\
           /run/initramfs/live/LiveOS/rootfs.img; do
    if [ -e "$p" ]; then
      ref=$p
      break
    fi
  done
  if [ -n "$ref" ]; then
    chcon --reference="$ref" /run/fbl-squashfs.img >> "$log" 2>&1 || true
  else
    chcon -t iso9660_t /run/fbl-squashfs.img >> "$log" 2>&1 || true
  fi
fi

for name in sealertauto setroubleshoot seapplet setroubleshoot-applet \\
            org.fedorahosted.setroubleshoot org.fedoraproject.setroubleshoot; do
  printf '%s\\n' '[Desktop Entry]' 'Hidden=true' > "/etc/xdg/autostart/${name}.desktop"
done
ln -sfn /dev/null /etc/systemd/system/setroubleshootd.service
if command -v systemctl >/dev/null; then
  systemctl mask setroubleshootd.service >> "$log" 2>&1 || true
fi
pkill -x seapplet >/dev/null 2>&1 || true

# liveuser has a blank password; auth_admin cannot complete unattended.
mkdir -p /etc/polkit-1/rules.d /usr/share/polkit-1/rules.d
if [ -f /etc/polkit-1/rules.d/00-fbl-liveinst.rules ]; then
  cp -f /etc/polkit-1/rules.d/00-fbl-liveinst.rules \\
    /usr/share/polkit-1/rules.d/00-fbl-liveinst.rules 2>/dev/null || true
fi
pol=/usr/share/polkit-1/actions/org.fedoraproject.pkexec.liveinst.policy
if [ -f "$pol" ]; then
  sed -i \\
    -e 's|<allow_any>auth_admin</allow_any>|<allow_any>yes</allow_any>|' \\
    -e 's|<allow_inactive>auth_admin</allow_inactive>|<allow_inactive>yes</allow_inactive>|' \\
    -e 's|<allow_active>auth_admin</allow_active>|<allow_active>yes</allow_active>|' \\
    "$pol" >> "$log" 2>&1 || true
fi
if command -v restorecon >/dev/null; then
  restorecon -F /etc/polkit-1/rules.d/00-fbl-liveinst.rules \\
    /usr/share/polkit-1/rules.d/00-fbl-liveinst.rules "$pol" >> "$log" 2>&1 || true
fi
if command -v systemctl >/dev/null; then
  systemctl reload polkit.service >> "$log" 2>&1 \\
    || systemctl reload polkitd.service >> "$log" 2>&1 || true
fi

{
  echo "getenforce=$(getenforce 2>/dev/null || echo missing)"
  ls -Z /ks.cfg /usr/bin/liveinst /usr/libexec/fbl-link-squashfs \\
    /run/fbl-squashfs.img 2>/dev/null || true
} >> "$log" 2>&1
exit 0
"""

AUTOSTART_DESKTOP = """[Desktop Entry]
Type=Application
Name=Install Fedora
Comment=First Boot Linux unattended installer
Exec=/usr/bin/liveinst
X-KDE-autostart-phase=2
X-GNOME-Autostart-enabled=true
OnlyShowIn=KDE;
"""

POLKIT_RULE = """// First Boot Linux — unattended liveinst. Overlay only.
// Official policy is auth_admin; liveuser has a blank password, so
// pkexec shows "Authentication is required to run the installer"
// (0.6.46). Allow this action without a prompt.
polkit.addRule(function(action, subject) {
    if (action.id == "org.fedoraproject.pkexec.liveinst") {
        return polkit.Result.YES;
    }
});
"""

DRACUT_HOOK = """#!/bin/sh
# Overlay kickstart + official liveinst (patched) onto the live root.
# Fedora dracut keeps hooks in var/lib/dracut/hooks (lib/dracut/hooks is a symlink).
root="${NEWROOT:-/sysroot}"
log="$root/var/log/firstboot-fedora.log"
mkdir -p "$root/var/log" "$root/usr/sbin" "$root/usr/libexec" \\
  "$root/etc/xdg/autostart" \\
  "$root/etc/polkit-1/rules.d" \\
  "$root/usr/share/polkit-1/rules.d" \\
  "$root/etc/systemd/system/multi-user.target.wants" \\
  "$root/etc/systemd/system/graphical.target.wants"
{
  echo "=== fbl fedora pre-pivot ==="
  cat /proc/cmdline 2>/dev/null
  ls -l /ks.cfg /fbl-liveinst /usr/libexec/fbl-link-squashfs \\
    /var/lib/dracut/hooks/pre-pivot 2>/dev/null
} > "$log" 2>&1
if [ -f /ks.cfg ]; then
  cp /ks.cfg "$root/ks.cfg"
  chmod 644 "$root/ks.cfg"
fi
if [ -f /fbl-liveinst ]; then
  # F44 anaconda-live ships /usr/bin/liveinst. Fedora 42+ usr-merge makes
  # /usr/sbin a symlink to bin, so those two paths are one file. 0.6.42
  # replaced bin/liveinst with a symlink to ../sbin/liveinst — circular.
  # KDE: "Could not find the program 'liveinst'".
  bin="$root/usr/bin/liveinst"
  sbin="$root/usr/sbin/liveinst"
  mkdir -p "$root/usr/bin"
  if [ -f "$bin" ] && [ ! -L "$bin" ] && [ ! -e "$bin.real" ]; then
    mv "$bin" "$bin.real" || true
  fi
  if [ -f "$sbin" ] && [ ! -L "$sbin" ] && [ ! -e "$sbin.real" ]; then
    mv "$sbin" "$sbin.real" || true
  fi
  for real in "$bin.real" "$sbin.real"; do
    if [ -f "$real" ] && ! grep -q -- '--kickstart=/ks.cfg' "$real"; then
      sed -i 's|anaconda --liveinst --graphical|anaconda --liveinst --graphical --kickstart=/ks.cfg|' \\
        "$real" || true
    fi
  done
  cp /fbl-liveinst "$bin"
  chmod 755 "$bin"
  if [ -d "$root/usr/sbin" ] && [ ! "$root/usr/sbin" -ef "$root/usr/bin" ]; then
    if [ ! -e "$sbin" ] || [ -L "$sbin" ]; then
      ln -sfn ../bin/liveinst "$sbin"
    fi
  fi
fi
if [ -f /usr/libexec/fbl-link-squashfs ]; then
  cp /usr/libexec/fbl-link-squashfs "$root/usr/libexec/fbl-link-squashfs"
  chmod 755 "$root/usr/libexec/fbl-link-squashfs"
  # Initramfs /run survives switch_root. Create the liveimg alias now,
  # while squashed.img / LiveOS / isoscan are still visible. 0.6.44 waited
  # for a systemd oneshot + liveuser sudo and still zenity-failed.
  /usr/libexec/fbl-link-squashfs >> "$log" 2>&1 || true
  ls -l /run/fbl-squashfs.img >> "$log" 2>&1 || true
fi
if [ -f /usr/libexec/fbl-selinux ]; then
  cp /usr/libexec/fbl-selinux "$root/usr/libexec/fbl-selinux"
  chmod 755 "$root/usr/libexec/fbl-selinux"
fi
if [ -f /etc/systemd/system/fbl-link-squashfs.service ]; then
  cp /etc/systemd/system/fbl-link-squashfs.service \\
    "$root/etc/systemd/system/fbl-link-squashfs.service"
  ln -sfn /etc/systemd/system/fbl-link-squashfs.service \\
    "$root/etc/systemd/system/multi-user.target.wants/fbl-link-squashfs.service"
  ln -sfn /etc/systemd/system/fbl-link-squashfs.service \\
    "$root/etc/systemd/system/graphical.target.wants/fbl-link-squashfs.service"
fi
if [ -f /etc/xdg/autostart/fbl-liveinst.desktop ]; then
  cp /etc/xdg/autostart/fbl-liveinst.desktop \\
    "$root/etc/xdg/autostart/fbl-liveinst.desktop"
fi
if [ -f /etc/polkit-1/rules.d/00-fbl-liveinst.rules ]; then
  cp /etc/polkit-1/rules.d/00-fbl-liveinst.rules \\
    "$root/etc/polkit-1/rules.d/00-fbl-liveinst.rules"
  cp /etc/polkit-1/rules.d/00-fbl-liveinst.rules \\
    "$root/usr/share/polkit-1/rules.d/00-fbl-liveinst.rules"
  chmod 644 "$root/etc/polkit-1/rules.d/00-fbl-liveinst.rules" \\
    "$root/usr/share/polkit-1/rules.d/00-fbl-liveinst.rules"
fi
pol="$root/usr/share/polkit-1/actions/org.fedoraproject.pkexec.liveinst.policy"
if [ -f "$pol" ]; then
  sed -i \\
    -e 's|<allow_any>auth_admin</allow_any>|<allow_any>yes</allow_any>|' \\
    -e 's|<allow_inactive>auth_admin</allow_inactive>|<allow_inactive>yes</allow_inactive>|' \\
    -e 's|<allow_active>auth_admin</allow_active>|<allow_active>yes</allow_active>|' \\
    "$pol" >> "$log" 2>&1 || true
fi
# restorecon on /sysroot/usr/bin/liveinst matches no file_contexts rule
# (0.6.45 unlabeled_t → setroubleshoot). setfiles -r NEWROOT uses the
# live policy. After pivot the oneshot restorecon's again.
fc="$root/etc/selinux/targeted/contexts/files/file_contexts"
sf=
for p in "$root/usr/sbin/setfiles" "$root/sbin/setfiles"; do
  if [ -x "$p" ]; then
    sf=$p
    break
  fi
done
if [ -n "$sf" ] && [ -f "$fc" ]; then
  LD_LIBRARY_PATH="$root/usr/lib64:$root/lib64${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" \\
    "$sf" -F -r "$root" "$fc" \\
    "$root/ks.cfg" "$root/usr/bin/liveinst" "$root/usr/bin/liveinst.real" \\
    "$root/usr/sbin/liveinst" "$root/usr/sbin/liveinst.real" \\
    "$root/usr/libexec/fbl-link-squashfs" "$root/usr/libexec/fbl-selinux" \\
    "$root/etc/systemd/system/fbl-link-squashfs.service" \\
    "$root/etc/xdg/autostart/fbl-liveinst.desktop" \\
    "$root/etc/polkit-1/rules.d/00-fbl-liveinst.rules" \\
    "$root/usr/share/polkit-1/rules.d/00-fbl-liveinst.rules" \\
    "$root/usr/share/polkit-1/actions/org.fedoraproject.pkexec.liveinst.policy" \\
    "$root/var/log/firstboot-fedora.log" >> "$log" 2>&1 || true
fi
mkdir -p "$root/etc/xdg/autostart" "$root/etc/systemd/system"
for name in sealertauto setroubleshoot seapplet setroubleshoot-applet \\
            org.fedorahosted.setroubleshoot org.fedoraproject.setroubleshoot; do
  printf '%s\\n' '[Desktop Entry]' 'Hidden=true' > "$root/etc/xdg/autostart/${name}.desktop"
done
ln -sfn /dev/null "$root/etc/systemd/system/setroubleshootd.service"
echo "ks=$(test -f "$root/ks.cfg" && echo yes || echo no) liveinst=$(test -x "$root/usr/bin/liveinst" && echo yes || echo no) real=$(test -f "$root/usr/bin/liveinst.real" -o -f "$root/usr/sbin/liveinst.real" && echo yes || echo no)" >> "$log"
exit 0
"""

SHIM_GRUB = """# First Boot Linux — Fedora shim (Secure Boot)
set default=0
set timeout=2

search --no-floppy --set=root --fs-uuid {sys_uuid}
if [ ! -f /boot/osinstall/vmlinuz ]; then
	search --no-floppy --set=root --label FBL-SYS
fi

menuentry "Install {name}" {{
    linux /boot/osinstall/vmlinuz {linux_args} ---
    initrd /boot/osinstall/initrd
}}
"""


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
    raise OsInstallError("This image is not a Fedora live ISO.")


def fedora_kickstart(identity: OsIdentity, target_path: str) -> str:
    """Anaconda kickstart for Fedora 44 KDE Live. Not Ubiquity, not autoinstall."""
    disk = kernel_disk_path(target_path)
    drive = kickstart_disk_id(target_path)
    gecos = kickstart_gecos(identity.realname or identity.username)
    user = identity.username
    host = identity.hostname
    hashed = identity.password_hash
    return (
        "#version=F44\n"
        "# First Boot Linux — Fedora Plasma live install\n"
        "graphical\n"
        f"liveimg --url=file://{SQUASH_LINK}\n"
        "lang en_US.UTF-8\n"
        "keyboard --vckeymap=us --xlayouts='us'\n"
        "timezone UTC\n"
        f"network --hostname={host}\n"
        "rootpw --lock\n"
        f'user --name={user} --gecos="{gecos}" --password="{hashed}" '
        "--iscrypted --groups=wheel\n"
        "firstboot --disable\n"
        f"ignoredisk --only-use={drive}\n"
        "zerombr\n"
        f"clearpart --all --initlabel --disklabel=gpt --drives={drive}\n"
        "autopart --type=btrfs\n"
        f"bootloader --location=mbr --boot-drive={drive}\n"
        "reboot\n"
        "%addon com_redhat_kdump --disable\n"
        "%end\n"
        "%pre --interpreter=/bin/bash\n"
        f"disk={disk}\n"
        "log=/tmp/firstboot-fedora-pre.log\n"
        "{\n"
        "  echo '=== fbl fedora pre ==='\n"
        "  date\n"
        "  cat /proc/cmdline 2>/dev/null\n"
        "  lsblk -o NAME,LABEL,MOUNTPOINT,TYPE 2>/dev/null\n"
        "  findmnt 2>/dev/null\n"
        "  losetup -a 2>/dev/null\n"
        "} > \"$log\" 2>&1\n"
        "if command -v losetup >/dev/null; then\n"
        "  losetup -ln -O NAME,BACK-FILE 2>/dev/null | while read -r name back; do\n"
        "    case \"$back\" in\n"
        "      *isodevice*|*FBL-DATA*) umount -l \"$name\" 2>/dev/null || true; "
        "losetup -d \"$name\" 2>/dev/null || true ;;\n"
        "    esac\n"
        "  done\n"
        "fi\n"
        "if [ -b \"$disk\" ]; then\n"
        "  lsblk -ln -o PATH,MOUNTPOINT \"$disk\" 2>/dev/null | while read -r path mp; do\n"
        "    [ -n \"$mp\" ] && [ \"$mp\" != \"/\" ] && umount -l \"$mp\" 2>/dev/null || true\n"
        "  done\n"
        "fi\n"
        "umount -l /isodevice /run/payload 2>/dev/null || true\n"
        "dev=$(blkid -L FBL-DATA 2>/dev/null) || true\n"
        "[ -n \"$dev\" ] && umount -l \"$dev\" 2>/dev/null || true\n"
        "swapoff -a 2>/dev/null || true\n"
        "udevadm settle 2>/dev/null || true\n"
        "{\n"
        "  echo '=== after ==='\n"
        "  lsblk -o NAME,LABEL,MOUNTPOINT,TYPE 2>/dev/null\n"
        "  findmnt 2>/dev/null\n"
        "  losetup -a 2>/dev/null\n"
        "} >> \"$log\" 2>&1\n"
        "%end\n"
        "%post --interpreter=/bin/bash\n"
        "for n in $(efibootmgr 2>/dev/null | "
        "sed -n 's/^Boot\\([0-9A-Fa-f]\\{4\\}\\).*\\(First Boot Linux\\|Install Fedora\\).*/\\1/p');\n"
        "do\n"
        "  efibootmgr -b \"$n\" -B || true\n"
        "done\n"
        f"if ! getent passwd {user} >/dev/null 2>&1; then\n"
        f"  useradd -m -G wheel -c '{gecos}' {user} || true\n"
        f"  echo '{user}:{hashed}' | chpasswd -e || true\n"
        "fi\n"
        "systemctl disable --global plasma-setup.service 2>/dev/null || true\n"
        "rm -f /etc/xdg/autostart/plasma-setup*.desktop "
        "/usr/lib/systemd/user/plasma-setup.service 2>/dev/null || true\n"
        "mkdir -p /var/lib/plasma-setup\n"
        "touch /var/lib/plasma-setup/completed\n"
        "%end\n"
    )


def fedora_kernel_args(iso_rel: str, label: str, *, toram: bool) -> str:
    ram = "rd.live.ram=1 " if toram else ""
    vol = (label or LIVE_LABEL).strip() or LIVE_LABEL
    return (
        f"root=live:CDLABEL={vol} rd.live.image iso-scan/filename={iso_rel} "
        f"{ram}{LINUX_FLAG}"
    )


def install_fedora_shim(
    iso_mnt: str,
    plan: OsInstallPlan,
    sys_uuid: str,
    name: str,
    linux_args: str,
) -> None:
    """Copy Fedora's Microsoft-signed shim to FBL-ESP and BootNext it."""
    if plan.live is None:
        return
    esp_part = plan.live.part_named("FBL-ESP")
    if esp_part is None:
        return
    src_shim = os.path.join(iso_mnt, "EFI", "BOOT", "BOOTX64.EFI")
    src_grub = os.path.join(iso_mnt, "EFI", "BOOT", "grubx64.efi")
    if not os.path.isfile(src_shim) or not os.path.isfile(src_grub):
        return
    mounted = False
    esp_mp = ""
    if esp_part.mountpoints:
        esp_mp = esp_part.mountpoints[0]
    else:
        esp_mp = tempfile.mkdtemp(prefix="fbl-esp-")
        run_checked(["mount", esp_part.path, esp_mp], what="mount the EFI partition")
        mounted = True
    try:
        dest = os.path.join(esp_mp, "EFI", "osinstall")
        os.makedirs(dest, exist_ok=True)
        shutil.copy2(src_shim, os.path.join(dest, "shimx64.efi"))
        shutil.copy2(src_grub, os.path.join(dest, "grubx64.efi"))
        mm = os.path.join(iso_mnt, "EFI", "BOOT", "mmx64.efi")
        if os.path.isfile(mm):
            shutil.copy2(mm, os.path.join(dest, "mmx64.efi"))
        with open(os.path.join(dest, "grub.cfg"), "w", encoding="utf-8") as fh:
            fh.write(
                SHIM_GRUB.format(
                    sys_uuid=sys_uuid, name=name, linux_args=linux_args
                )
            )
    finally:
        if mounted:
            subprocess.run(["umount", esp_mp], check=False, capture_output=True)
            shutil.rmtree(esp_mp, ignore_errors=True)
    if not shutil.which("efibootmgr"):
        return
    partnum = efi_part_number(esp_part.path)
    from firstboot.install import efi_ids_for_label

    def _efi_list() -> str:
        proc = subprocess.run(
            ["efibootmgr"], check=False, capture_output=True, text=True
        )
        return proc.stdout or ""

    for bootnum in efi_ids_for_label(_efi_list(), BOOTNEXT_LABEL):
        subprocess.run(
            ["efibootmgr", "--bootnum", bootnum, "--delete-bootnum"],
            check=False,
            capture_output=True,
            text=True,
        )
    subprocess.run(
        [
            "efibootmgr",
            "--create",
            "--disk",
            plan.live.path,
            "--part",
            partnum,
            "--label",
            BOOTNEXT_LABEL,
            "--loader",
            r"\EFI\osinstall\shimx64.efi",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    created = efi_ids_for_label(_efi_list(), BOOTNEXT_LABEL)
    if created:
        subprocess.run(
            ["efibootmgr", "--bootnext", created[-1]],
            check=False,
            capture_output=True,
            text=True,
        )


class Fedora44Plasma:
    id = ID
    aliases = ALIASES
    default_hostname = "fedora"

    def boot_files(self, iso_mnt: str) -> tuple[str, str]:
        return fedora_boot_files(iso_mnt)

    def kernel_args(self, iso_rel: str, *, toram: bool, iso_path: str = "") -> str:
        vol = iso_volume_id(iso_path) if iso_path else ""
        return fedora_kernel_args(iso_rel, vol or LIVE_LABEL, toram=toram)

    def seed_files(
        self, identity: OsIdentity, target_path: str, serial: str
    ) -> dict[str, str | bytes]:
        return {
            "ks.cfg": fedora_kickstart(identity, target_path),
            "fbl-liveinst": LIVEINST_WRAPPER,
            "usr/libexec/fbl-link-squashfs": LINK_SQUASH,
            "usr/libexec/fbl-selinux": FBL_SELINUX,
            "etc/systemd/system/fbl-link-squashfs.service": LINK_SERVICE,
            "etc/xdg/autostart/fbl-liveinst.desktop": AUTOSTART_DESKTOP,
            "etc/polkit-1/rules.d/00-fbl-liveinst.rules": POLKIT_RULE,
            "var/lib/dracut/hooks/pre-pivot/90-fbl-ks.sh": DRACUT_HOOK,
        }

    def after_prepare(
        self,
        iso_mnt: str,
        plan: OsInstallPlan,
        sys_uuid: str,
        label: str,
        linux_args: str,
    ) -> None:
        install_fedora_shim(iso_mnt, plan, sys_uuid, label, linux_args)


DRIVER = Fedora44Plasma()
