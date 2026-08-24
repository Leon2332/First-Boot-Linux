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
# Session front door. Official liveinst does pkexec + WAYLAND_DISPLAY.
# Do not exec anaconda here (0.6.41: no display, then DNF). LIVECMD does
# not survive pkexec — pre-pivot patches liveinst.real's ANACONDA default.
log=/var/log/firstboot-fedora.log
mkdir -p /var/log /run
{
  echo "=== fbl liveinst wrapper ==="
  date
  echo "uid=$(id -u) WAYLAND_DISPLAY=${WAYLAND_DISPLAY-} DISPLAY=${DISPLAY-} PKEXEC_UID=${PKEXEC_UID-}"
  cat /proc/cmdline 2>/dev/null
  ls -l /ks.cfg /usr/sbin/liveinst.real /run/fbl-squashfs.img 2>/dev/null
} >> "$log" 2>&1

# livesys-late may still call us as root before SDDM. Leave it to autostart.
if [ "$(id -u)" -eq 0 ] && [ -z "${PKEXEC_UID:-}" ] && [ -z "${WAYLAND_DISPLAY:-}" ] && [ -z "${DISPLAY:-}" ]; then
  echo "root without display; session autostart will start liveinst" >> "$log"
  exit 0
fi

if [ ! -e /run/fbl-squashfs.img ]; then
  echo "squashfs link missing; refusing to start (would DNF)" >> "$log"
  if command -v zenity >/dev/null 2>&1 && [ -n "${WAYLAND_DISPLAY:-}${DISPLAY:-}" ]; then
    zenity --error --no-markup --text="First Boot Linux could not find the Fedora live image." || true
  fi
  exit 1
fi

if [ ! -x /usr/sbin/liveinst.real ]; then
  echo "liveinst.real missing" >> "$log"
  exit 1
fi

exec /usr/sbin/liveinst.real "$@"
"""

LINK_SQUASH = """#!/bin/bash
# Root oneshot: alias squashfs.img so kickstart liveimg cannot DNF.
log=/var/log/firstboot-fedora.log
mkdir -p /var/log /run
sq=
for p in \\
  /run/initramfs/live/LiveOS/squashfs.img \\
  /run/initramfs/live/LiveOS/rootfs.img \\
  /run/initramfs/live/squashfs.img \\
  /run/live/medium/LiveOS/squashfs.img \\
  /run/initramfs/squashfs.img
do
  if [ -f "$p" ]; then
    sq=$p
    break
  fi
done
if [ -z "$sq" ]; then
  sq=$(find /run/initramfs /run/live /mnt -name squashfs.img -type f 2>/dev/null | head -n 1)
fi
{
  echo "=== fbl link squashfs ==="
  date
  echo "squashfs=${sq:-missing}"
  findmnt /run/initramfs/live 2>/dev/null
  ls -l /run/initramfs/live/LiveOS 2>/dev/null
} >> "$log" 2>&1
if [ -n "$sq" ]; then
  ln -sfn "$sq" /run/fbl-squashfs.img
fi
exit 0
"""

LINK_SERVICE = """[Unit]
Description=First Boot Linux Fedora live image
DefaultDependencies=no
After=local-fs.target
Before=display-manager.service

[Service]
Type=oneshot
ExecStart=/usr/libexec/fbl-link-squashfs
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
"""

AUTOSTART_DESKTOP = """[Desktop Entry]
Type=Application
Name=Install Fedora
Comment=First Boot Linux unattended installer
Exec=/usr/sbin/liveinst
X-KDE-autostart-phase=2
X-GNOME-Autostart-enabled=true
OnlyShowIn=KDE;
"""

DRACUT_HOOK = """#!/bin/sh
# Overlay kickstart + official liveinst (patched) onto the live root.
# Fedora dracut keeps hooks in var/lib/dracut/hooks (lib/dracut/hooks is a symlink).
root="${NEWROOT:-/sysroot}"
log="$root/var/log/firstboot-fedora.log"
mkdir -p "$root/var/log" "$root/usr/sbin" "$root/usr/libexec" \\
  "$root/etc/xdg/autostart" "$root/etc/systemd/system/multi-user.target.wants"
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
  if [ -e "$root/usr/sbin/liveinst" ] && [ ! -L "$root/usr/sbin/liveinst" ] \\
      && [ ! -e "$root/usr/sbin/liveinst.real" ]; then
    mv "$root/usr/sbin/liveinst" "$root/usr/sbin/liveinst.real" || true
  fi
  if [ -f "$root/usr/sbin/liveinst.real" ] \\
      && ! grep -q -- '--kickstart=/ks.cfg' "$root/usr/sbin/liveinst.real"; then
    sed -i 's|anaconda --liveinst --graphical|anaconda --liveinst --graphical --kickstart=/ks.cfg|' \\
      "$root/usr/sbin/liveinst.real" || true
  fi
  cp /fbl-liveinst "$root/usr/sbin/liveinst"
  chmod 755 "$root/usr/sbin/liveinst"
  if [ -f "$root/usr/bin/liveinst" ] && [ ! -L "$root/usr/bin/liveinst" ]; then
    ln -sfn ../sbin/liveinst "$root/usr/bin/liveinst"
  fi
fi
if [ -f /usr/libexec/fbl-link-squashfs ]; then
  cp /usr/libexec/fbl-link-squashfs "$root/usr/libexec/fbl-link-squashfs"
  chmod 755 "$root/usr/libexec/fbl-link-squashfs"
fi
if [ -f /etc/systemd/system/fbl-link-squashfs.service ]; then
  cp /etc/systemd/system/fbl-link-squashfs.service \\
    "$root/etc/systemd/system/fbl-link-squashfs.service"
  ln -sfn /etc/systemd/system/fbl-link-squashfs.service \\
    "$root/etc/systemd/system/multi-user.target.wants/fbl-link-squashfs.service"
fi
if [ -f /etc/xdg/autostart/fbl-liveinst.desktop ]; then
  cp /etc/xdg/autostart/fbl-liveinst.desktop \\
    "$root/etc/xdg/autostart/fbl-liveinst.desktop"
fi
if command -v restorecon >/dev/null; then
  restorecon -F "$root/ks.cfg" "$root/usr/sbin/liveinst" \\
    "$root/usr/sbin/liveinst.real" "$root/usr/libexec/fbl-link-squashfs" \\
    2>/dev/null || true
fi
echo "ks=$(test -f "$root/ks.cfg" && echo yes || echo no) liveinst=$(test -x "$root/usr/sbin/liveinst" && echo yes || echo no) real=$(test -f "$root/usr/sbin/liveinst.real" && echo yes || echo no)" >> "$log"
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
            "etc/systemd/system/fbl-link-squashfs.service": LINK_SERVICE,
            "etc/xdg/autostart/fbl-liveinst.desktop": AUTOSTART_DESKTOP,
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
