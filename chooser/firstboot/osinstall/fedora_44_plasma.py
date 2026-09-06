"""Fedora 44 KDE Plasma — FBL-native unpack.

Catalog ``install``: ``fedora-44-plasma``.
Do not reuse this file for Fedora GNOME or later Fedora versions.
Live identity is ``liveuser``; the customer form is the installed user.
Copy Fedora's shim, not Canonical GRUB.
"""

from __future__ import annotations

from collections.abc import Callable

from firstboot.installlocale import InstallLocale
from . import fedora
from .common import InstalledDisk, InstallLog, OsIdentity

ID = "fedora-44-plasma"
ALIASES: tuple[str, ...] = ()


class Fedora44Plasma:
    id = ID
    aliases = ALIASES
    default_hostname = "fedora"
    display_name = "Fedora 44 Plasma"
    unpack_kind = "fedora-erofs"
    # Fedora 44 KDE ships Plasma Login Manager, not SDDM.
    display_manager = "plasmalogin"
    live_usernames = ("liveuser",)
    bootloader_id = "fedora"
    nvram_label = "Fedora"

    def partition(
        self, disk_path: str, work: str, log: InstallLog | None = None
    ) -> InstalledDisk:
        return fedora.partition_fedora_disk(disk_path, work, log=log)

    def squashfs_relpaths(self, iso_mnt: str) -> list[str]:
        return fedora.fedora_live_relpaths(iso_mnt)

    def unpack(
        self,
        iso_mnt: str,
        target_root: str,
        on_progress: Callable[[int], None] | None = None,
        log: InstallLog | None = None,
    ) -> None:
        fedora.unpack_fedora(
            iso_mnt, target_root, on_progress=on_progress, log=log
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
        fedora.configure_fedora(
            target_root,
            identity,
            locale,
            disk,
            display_manager=self.display_manager,
            live_usernames=self.live_usernames,
            timezone_minutes=timezone_minutes,
            log=log,
        )

    def bootloader(
        self,
        target_root: str,
        efi_mp: str,
        disk: InstalledDisk,
        iso_mnt: str,
        log: InstallLog | None = None,
    ) -> str:
        return fedora.install_fedora_bootloader(
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
        return fedora.health_check_fedora(
            target_root,
            efi_mp,
            identity,
            disk,
            display_manager=self.display_manager,
            boot_log=boot_log,
        )


DRIVER = Fedora44Plasma()
