"""Fedora 44 KDE Plasma — Anaconda kickstart from the live ISO.

Catalog ``install``: ``fedora-44-plasma``. Alias ``fedora-kickstart`` (older sticks).
Do not feed Fedora autoinstall YAML or a casper cmdline.

Official liveinst rejects kickstart on its argv and pkexecs as liveuser
(auth_admin, blank password). That is a desktop app, not an unattended
installer. Run Anaconda as root from systemd on multi-user.target with
kickstart liveimg. Do not wrap liveinst, do not pkexec, do not start Plasma.
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

LINK_SQUASH = """#!/bin/bash
# Alias the live image so kickstart liveimg cannot DNF.
# Same-disk boots use rd.live.ram=1; F44 dmsquash then copies to
# /run/initramfs/squashed.img. Never symlink: the source may sit on
# FBL-DATA, which %pre unmounts and clearpart wipes.
root=${FBL_LIVE_ROOT:-}
log="${FBL_LIVE_LOG:-$root/var/log/firstboot-fedora.log}"
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
if [ -z "$sq" ]; then
  echo "no live image found" >> "$log"
  exit 1
fi
if [ -e "$dest" ] && [ -s "$dest" ]; then
  echo "already present $dest" >> "$log"
  exit 0
fi
rm -f "$dest"
if ln "$sq" "$dest" 2>/dev/null; then
  echo "hardlinked $sq -> $dest" >> "$log"
  exit 0
fi
if cp -f --reflink=auto "$sq" "$dest" 2>/dev/null; then
  echo "copied $sq -> $dest" >> "$log"
  exit 0
fi
echo "failed to place live image at $dest (no symlink: source may be on the target disk)" >> "$log"
exit 1
"""

ANACONDA_SCRIPT = """#!/bin/bash
# Root installer, run in place of getty@tty1. Official liveinst
# pkexecs as liveuser (auth_admin, blank password). That cannot run
# unattended. Live-OS payload mode would rsync this overlay onto the
# disk. Payload is kickstart liveimg. Cmdline mode needs no compositor.
# Never exit: a failed oneshot lets getty paint a login prompt that
# looks like the install finished. Stay on this tty with the log.
log=/var/log/firstboot-fedora.log
mkdir -p /var/log /run
{
  echo "=== fbl anaconda ==="
  date
  echo "uid=$(id -u) tty=$(tty 2>/dev/null || true) WAYLAND_DISPLAY=${WAYLAND_DISPLAY-} DISPLAY=${DISPLAY-}"
  cat /proc/cmdline 2>/dev/null
  ls -l /ks.cfg /run/fbl-squashfs.img /usr/bin/anaconda /usr/sbin/anaconda \\
    /usr/bin/liveinst /usr/libexec/fbl-link-squashfs 2>/dev/null
} >> "$log" 2>&1

fail() {
  echo "FAILED: $*" | tee -a "$log"
  echo
  echo "==== /var/log/firstboot-fedora.log ===="
  cat "$log" 2>/dev/null || true
  echo
  echo "Installer did not finish. This shell is root; tty2 is also a getty."
  exec /bin/bash
}

if [ "$(id -u)" -ne 0 ]; then
  fail "not root; refusing (do not escalate)"
fi

if [ -x /usr/sbin/setenforce ]; then
  /usr/sbin/setenforce 0 >> "$log" 2>&1 || true
fi
if command -v plymouth >/dev/null; then
  plymouth quit >> "$log" 2>&1 || true
fi

for i in raid0 raid1 raid5 raid6 raid456 raid10 dm-mod dm-zero dm-mirror \\
         dm-snapshot dm-multipath dm-round-robin vfat dm-crypt cbc sha256 \\
         lrw xts iscsi_tcp iscsi_ibft; do
  /sbin/modprobe "$i" 2>/dev/null || true
done

link=/usr/libexec/fbl-link-squashfs
if [ -x "$link" ]; then
  "$link" >> "$log" 2>&1 || true
fi
if [ ! -e /run/fbl-squashfs.img ] || [ ! -s /run/fbl-squashfs.img ]; then
  echo "squashfs link missing; refusing to start (would DNF)" >> "$log"
  ls -la /run/initramfs /run/initramfs/live /run/initramfs/live/LiveOS \\
    /run/initramfs/isoscan 2>> "$log" || true
  fail "squashfs link missing; refusing to start (would DNF)"
fi
if [ ! -f /ks.cfg ]; then
  fail "ks.cfg missing"
fi

if command -v anaconda-cleanup >/dev/null; then
  anaconda-cleanup >> "$log" 2>&1 || true
fi

ana=
for p in /usr/bin/anaconda /usr/sbin/anaconda; do
  if [ -x "$p" ]; then
    ana=$p
    break
  fi
done
if [ -z "$ana" ]; then
  fail "anaconda missing"
fi

echo "exec $ana --kickstart=/ks.cfg --cmdline" >> "$log"
exec "$ana" --kickstart=/ks.cfg --cmdline
fail "anaconda exited"
"""

# Replaces getty@tty1. A separate oneshot that Conflicts with getty lost
# the console (0.6.40 and 0.6.53 hardware: localhost-live login).
ANACONDA_SERVICE = """[Unit]
Description=First Boot Linux Fedora installer
ConditionKernelCommandLine=fbl.install
After=systemd-user-sessions.service plymouth-quit-wait.service local-fs.target
After=getty-pre.target
Conflicts=rescue.service display-manager.service
Before=rescue.service getty.target

[Service]
Type=idle
TimeoutSec=infinity
Environment=HOME=/root LANG=en_US.UTF-8
WorkingDirectory=/root
ExecStartPre=-/usr/sbin/setenforce 0
ExecStartPre=-/usr/bin/plymouth quit
ExecStart=/usr/libexec/fbl-anaconda
StandardInput=tty
StandardOutput=tty
StandardError=tty
TTYPath=/dev/tty1
TTYReset=yes
TTYVHangup=yes
TTYVTDisallocate=no
Restart=no

[Install]
WantedBy=getty.target
"""

GENERATOR = """#!/bin/sh
# systemd generator: write getty@tty1 as the installer into /run.
# Overlay copies under /etc can be unlabeled; generators still run
# when the kernel has enforcing=0.
normal="${1:-/run/systemd/generator}"
grep -qw fbl.install /proc/cmdline 2>/dev/null || exit 0
[ -x /usr/libexec/fbl-anaconda ] || exit 0
mkdir -p "$normal"
ln -sfn /dev/null "$normal/display-manager.service"
ln -sfn /dev/null "$normal/sddm.service"
unit="$normal/getty@tty1.service"
cat > "$unit" <<'EOF'
""" + ANACONDA_SERVICE + """EOF
chmod 644 "$unit"
exit 0
"""

DRACUT_HOOK = """#!/bin/sh
# Overlay kickstart + getty@tty1 installer onto the live root.
# Do not wrap liveinst. Fedora dracut *sources* pre-pivot hooks
# (lib/dracut-lib.sh source_hook) — do not exit, that aborts cleanup.
# Fedora dracut keeps hooks in var/lib/dracut/hooks
# (lib/dracut/hooks is a symlink).
root="${NEWROOT:-/sysroot}"
log="$root/var/log/firstboot-fedora.log"
mkdir -p "$root/var/log" "$root/usr/libexec" \\
  "$root/etc/systemd/system" \\
  "$root/etc/systemd/system-generators"
{
  echo "=== fbl fedora pre-pivot ==="
  cat /proc/cmdline 2>/dev/null
  ls -l /ks.cfg /usr/libexec/fbl-link-squashfs /usr/libexec/fbl-anaconda \\
    /etc/systemd/system/getty@tty1.service \\
    /etc/systemd/system-generators/fbl-anaconda-gen \\
    /var/lib/dracut/hooks/pre-pivot 2>/dev/null
} > "$log" 2>&1
if [ -f /ks.cfg ]; then
  cp /ks.cfg "$root/ks.cfg"
  chmod 644 "$root/ks.cfg"
fi
if [ -f /usr/libexec/fbl-anaconda ]; then
  cp /usr/libexec/fbl-anaconda "$root/usr/libexec/fbl-anaconda"
  chmod 755 "$root/usr/libexec/fbl-anaconda"
fi
if [ -f /etc/systemd/system/getty@tty1.service ]; then
  # Regular file replaces a live-image mask (symlink to /dev/null).
  rm -f "$root/etc/systemd/system/getty@tty1.service"
  cp /etc/systemd/system/getty@tty1.service \\
    "$root/etc/systemd/system/getty@tty1.service"
  chmod 644 "$root/etc/systemd/system/getty@tty1.service"
fi
if [ -f /etc/systemd/system-generators/fbl-anaconda-gen ]; then
  cp /etc/systemd/system-generators/fbl-anaconda-gen \\
    "$root/etc/systemd/system-generators/fbl-anaconda-gen"
  chmod 755 "$root/etc/systemd/system-generators/fbl-anaconda-gen"
fi
if [ -f /usr/libexec/fbl-link-squashfs ]; then
  cp /usr/libexec/fbl-link-squashfs "$root/usr/libexec/fbl-link-squashfs"
  chmod 755 "$root/usr/libexec/fbl-link-squashfs"
  # Initramfs /run survives switch_root. Create the liveimg alias now,
  # while squashed.img / LiveOS / isoscan are still visible. Do this
  # after the small copies: a full-image copy onto tmpfs must not
  # ENOSPC the unit files.
  FBL_LIVE_LOG="$log" /usr/libexec/fbl-link-squashfs >> "$log" 2>&1 || true
  ls -l /run/fbl-squashfs.img >> "$log" 2>&1 || true
fi
if command -v chcon >/dev/null; then
  chcon -t systemd_unit_file_t \\
    "$root/etc/systemd/system/getty@tty1.service" 2>/dev/null || true
  chcon -t bin_t \\
    "$root/usr/libexec/fbl-anaconda" \\
    "$root/usr/libexec/fbl-link-squashfs" \\
    "$root/etc/systemd/system-generators/fbl-anaconda-gen" 2>/dev/null || true
fi
# Leave official /usr/bin/liveinst alone. Do not ln sbin→bin on usr-merge.
echo "ks=$(test -f "$root/ks.cfg" && echo yes || echo no) anaconda=$(test -x "$root/usr/libexec/fbl-anaconda" && echo yes || echo no) getty=$(test -f "$root/etc/systemd/system/getty@tty1.service" && echo yes || echo no) liveinst=$(test -x "$root/usr/bin/liveinst" && echo yes || echo no)" >> "$log"
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


# Chrooted on the installed system. Anaconda copies leftover live
# cmdline into BLS; systemd.unit=multi-user.target and systemd.mask=sddm
# then boot a getty instead of Plasma.
STRIP_INSTALLER_CMDLINE_PY = r"""
import glob, pathlib, re, sys
DROP_EXACT = {"inst.cmdline", "fbl.install", "enforcing=0", "---"}
DROP_PFX = (
    "systemd.unit=",
    "systemd.mask=",
    "iso-scan/",
    "root=live:",
    "rd.live.",
)

def keep(tok):
    if tok in DROP_EXACT:
        return False
    return not tok.startswith(DROP_PFX)

def clean(s):
    toks = [t for t in s.split() if keep(t)]
    if "rhgb" not in toks:
        toks.append("rhgb")
    if "quiet" not in toks:
        toks.append("quiet")
    return " ".join(toks)

def patch_text(text):
    def grub_repl(m):
        return f"{m.group(1)}={m.group(2)}{clean(m.group(3))}{m.group(2)}"
    text = re.sub(
        r'^(GRUB_CMDLINE_LINUX(?:_DEFAULT)?)=([\"\'])(.*)\2\s*$',
        grub_repl,
        text,
        flags=re.M,
    )
    out = []
    for line in text.splitlines(True):
        if line.startswith("options "):
            nl = "\n" if line.endswith("\n") else ""
            out.append("options " + clean(line[len("options "):].strip()) + nl)
        else:
            out.append(line)
    return "".join(out)
"""

KICKSTART_POST_DESKTOP = (
    "python3 - <<'PY' || true\n"
    + STRIP_INSTALLER_CMDLINE_PY
    + r"""
paths = [
    "/etc/default/grub",
    "/etc/kernel/cmdline",
    *glob.glob("/boot/loader/entries/*.conf"),
    *glob.glob("/boot/efi/loader/entries/*.conf"),
]
for path in paths:
    p = pathlib.Path(path)
    if not p.is_file():
        continue
    old = p.read_text(encoding="utf-8", errors="replace")
    new = patch_text(old)
    if path.endswith("cmdline") and "\n" not in old.strip():
        new = clean(old.strip()) + "\n"
    if new != old:
        p.write_text(new, encoding="utf-8")
        print("cleaned", path, file=sys.stderr)
PY
if command -v grubby >/dev/null; then
  grubby --update-kernel=ALL --remove-args="systemd.unit=multi-user.target systemd.mask=display-manager.service systemd.mask=sddm.service inst.cmdline fbl.install enforcing=0 rd.live.image rd.live.ram=1 rd.live.overlay.overlayfs" 2>/dev/null || true
  grubby --update-kernel=ALL --args="rhgb quiet" 2>/dev/null || true
fi
if command -v grub2-mkconfig >/dev/null && [ -d /boot/grub2 ]; then
  grub2-mkconfig -o /boot/grub2/grub.cfg 2>/dev/null || true
fi
ln -sfn /usr/lib/systemd/system/graphical.target /etc/systemd/system/default.target
if [ -L /etc/systemd/system/sddm.service ] && [ "$(readlink /etc/systemd/system/sddm.service)" = /dev/null ]; then
  rm -f /etc/systemd/system/sddm.service
fi
if [ -L /etc/systemd/system/display-manager.service ] && [ "$(readlink /etc/systemd/system/display-manager.service)" = /dev/null ]; then
  rm -f /etc/systemd/system/display-manager.service
fi
rm -f /etc/systemd/system-generators/fbl-anaconda-gen \
  /usr/libexec/fbl-anaconda /usr/libexec/fbl-link-squashfs /ks.cfg \
  /etc/systemd/system/multi-user.target.wants/fbl-anaconda.service
if [ -f /etc/systemd/system/getty@tty1.service ] && grep -q fbl-anaconda /etc/systemd/system/getty@tty1.service; then
  rm -f /etc/systemd/system/getty@tty1.service
fi
if [ -f /usr/lib/systemd/system/sddm.service ]; then
  ln -sfn /usr/lib/systemd/system/sddm.service /etc/systemd/system/display-manager.service
  mkdir -p /etc/systemd/system/graphical.target.wants
  ln -sfn /usr/lib/systemd/system/sddm.service /etc/systemd/system/graphical.target.wants/sddm.service
fi
"""
)


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
        "cmdline\n"
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
        f"bootloader --location=mbr --boot-drive={drive} --append=\"rhgb quiet\"\n"
        "selinux --enforcing\n"
        "services --enabled=sddm,NetworkManager\n"
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
        # Installer cmdline (multi-user, mask sddm) must not stick on
        # the installed kernel. Overlay copies of getty@tty1 must go.
        + KICKSTART_POST_DESKTOP
        + "%end\n"
    )


def fedora_kernel_args(iso_rel: str, label: str, *, toram: bool) -> str:
    ram = "rd.live.ram=1 " if toram else ""
    vol = (label or LIVE_LABEL).strip() or LIVE_LABEL
    return (
        f"root=live:CDLABEL={vol} rd.live.image iso-scan/filename={iso_rel} "
        f"{ram}rd.live.overlay.overlayfs enforcing=0 "
        f"systemd.unit=multi-user.target "
        f"systemd.mask=display-manager.service systemd.mask=sddm.service "
        f"inst.cmdline {LINUX_FLAG}"
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
            "usr/libexec/fbl-link-squashfs": LINK_SQUASH,
            "usr/libexec/fbl-anaconda": ANACONDA_SCRIPT,
            "etc/systemd/system/getty@tty1.service": ANACONDA_SERVICE,
            "etc/systemd/system-generators/fbl-anaconda-gen": GENERATOR,
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
