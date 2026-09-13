"""Ubuntu 26.04 LTS Cinnamon — FBL-native unpack.

Catalog ``install``: ``ubuntu-2604-cinnamon``.
Do not reuse this file for Ubuntu GNOME, Budgie, MATE, or other flavors.
Live casper identity is ``ubuntu``; the customer form is the installed user.
Display manager is LightDM (slick-greeter).

Match Canonical's installer, not the live session. ``install-sources.yaml``
default source is ``fsimage-layered://casper/minimal.standard.squashfs``
(minimal + standard). The live layer is Try-Ubuntu only: casper,
``ubuntucinnamon-live-settings``, and it whiteouts ``ubuntucinnamon-desktop``.
Copying it hangs first boot on Plymouth.

The install layers already contain ``linux-image-7.0.0-14-generic`` and
**dracut** (not initramfs-tools — that package is live/casper only and
Conflicts with dracut). After unpack, build ``/boot/initrd.img-*`` with
``dracut --no-hostonly``.
"""

from __future__ import annotations

from collections.abc import Callable

from firstboot.installlocale import InstallLocale
from . import casper
from .common import InstalledDisk, InstallLog, OsIdentity

ID = "ubuntu-2604-cinnamon"
ALIASES: tuple[str, ...] = ()


class Ubuntu2604Cinnamon:
    id = ID
    aliases = ALIASES
    default_hostname = "ubuntu"
    display_name = "Ubuntu 26.04 Cinnamon"
    unpack_kind = "casper-layered"
    display_manager = "lightdm"
    live_usernames = ("ubuntu",)
    bootloader_id = "ubuntu"
    nvram_label = "Ubuntu"

    def squashfs_relpaths(self, iso_mnt: str) -> list[str]:
        return casper.casper_squashfs_relpaths(iso_mnt)

    def iso_extras(self, iso_mnt: str) -> dict[str, str]:
        return casper.kernel_pool_extras(iso_mnt)

    def unpack(
        self,
        iso_mnt: str,
        target_root: str,
        on_progress: Callable[[int], None] | None = None,
        log: InstallLog | None = None,
    ) -> None:
        self._iso_mnt = iso_mnt
        casper.unpack_casper(
            iso_mnt,
            target_root,
            on_progress=on_progress,
            log=log,
            copy_kernel=False,
        )

    def configure(
        self,
        target_root: str,
        identity: OsIdentity,
        locale: InstallLocale,
        disk: InstalledDisk,
        timezone_minutes: int | None = None,
        log: InstallLog | None = None,
    ) -> None:
        casper.configure_casper(
            target_root,
            identity,
            locale,
            disk,
            display_manager=self.display_manager,
            live_usernames=self.live_usernames,
            timezone_minutes=timezone_minutes,
            log=log,
            iso_mnt=getattr(self, "_iso_mnt", "") or "",
            kernel_from_iso=True,
        )

    def bootloader(
        self,
        target_root: str,
        efi_mp: str,
        disk: InstalledDisk,
        iso_mnt: str,
        log: InstallLog | None = None,
    ) -> str:
        return casper.install_casper_bootloader(
            target_root,
            efi_mp,
            disk,
            iso_mnt,
            bootloader_id=self.bootloader_id,
            nvram_label=self.nvram_label,
            log=log,
        )

    def health_check(
        self,
        target_root: str,
        efi_mp: str,
        identity: OsIdentity,
        disk: InstalledDisk,
        boot_log: str = "",
    ) -> list[str]:
        return casper.health_check_casper(
            target_root,
            efi_mp,
            identity,
            disk,
            display_manager=self.display_manager,
            boot_log=boot_log,
        )


DRIVER = Ubuntu2604Cinnamon()
