"""CachyOS desktop 260809 KDE Plasma — FBL-native unpack.

Catalog ``install``: ``cachyos-260809-plasma``.
Do not reuse this file for Handheld, other desktops, or a later ISO
that changes unpack or bootloader. Live identity is ``liveuser``; the
customer form is the installed user. Display manager is plasmalogin.
Bootloader is systemd-boot (Limine is not on the offline ISO).
Secure Boot is off (no Microsoft-signed chain).
"""

from __future__ import annotations

from collections.abc import Callable

from firstboot.installlocale import InstallLocale
from . import cachyos
from .common import InstalledDisk, InstallLog, OsIdentity

ID = "cachyos-260809-plasma"
ALIASES: tuple[str, ...] = ()


class CachyOS260809Plasma:
    id = ID
    aliases = ALIASES
    default_hostname = "cachyos"
    display_name = "CachyOS Plasma"
    unpack_kind = "archiso-airootfs"
    display_manager = "plasmalogin"
    live_usernames = ("liveuser", "cachyos")
    bootloader_id = "cachyos"
    nvram_label = "CachyOS"

    def partition(
        self, disk_path: str, work: str, log: InstallLog | None = None
    ) -> InstalledDisk:
        return cachyos.partition_cachyos_disk(disk_path, work, log=log)

    def squashfs_relpaths(self, iso_mnt: str) -> list[str]:
        return cachyos.cachyos_live_relpaths(iso_mnt)

    def iso_extras(self, iso_mnt: str) -> dict[str, str]:
        return cachyos.iso_extras(iso_mnt)

    def unpack(
        self,
        iso_mnt: str,
        target_root: str,
        on_progress: Callable[[int], None] | None = None,
        log: InstallLog | None = None,
    ) -> None:
        cachyos.unpack_cachyos(
            iso_mnt, target_root, on_progress=on_progress, log=log
        )

    def configure(
        self,
        target_root: str,
        identity: OsIdentity,
        locale: InstallLocale,
        disk: InstalledDisk,
        timezone_minutes: int | None = None,
        extras_dir: str = "",
        log: InstallLog | None = None,
    ) -> None:
        cachyos.configure_cachyos(
            target_root,
            identity,
            locale,
            disk,
            display_manager=self.display_manager,
            live_usernames=self.live_usernames,
            timezone_minutes=timezone_minutes,
            extras_dir=extras_dir,
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
        return cachyos.install_cachyos_bootloader(
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
        return cachyos.health_check_cachyos(
            target_root,
            efi_mp,
            identity,
            disk,
            display_manager=self.display_manager,
            boot_log=boot_log,
        )


DRIVER = CachyOS260809Plasma()
