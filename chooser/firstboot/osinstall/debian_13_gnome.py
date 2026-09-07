"""Debian 13 GNOME — FBL-native unpack.

Catalog ``install``: ``debian-13-gnome``.
Do not reuse this file for Debian KDE, Xfce, or later Debian versions.
Live identity is ``user``; the customer form is the installed user.
Copy Debian's shim, not Canonical GRUB.
"""

from __future__ import annotations

from collections.abc import Callable

from firstboot.installlocale import InstallLocale
from . import debian
from .common import InstalledDisk, InstallLog, OsIdentity

ID = "debian-13-gnome"
ALIASES: tuple[str, ...] = ()


class Debian13Gnome:
    id = ID
    aliases = ALIASES
    default_hostname = "debian"
    display_name = "Debian 13 GNOME"
    unpack_kind = "live-single"
    display_manager = "gdm"
    live_usernames = ("user",)
    bootloader_id = "debian"
    nvram_label = "Debian"

    def squashfs_relpaths(self, iso_mnt: str) -> list[str]:
        return debian.debian_live_relpaths(iso_mnt)

    def iso_extras(self, iso_mnt: str) -> dict[str, str]:
        return debian.iso_extras(iso_mnt)

    def unpack(
        self,
        iso_mnt: str,
        target_root: str,
        on_progress: Callable[[int], None] | None = None,
        log: InstallLog | None = None,
    ) -> None:
        debian.unpack_debian(
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
        debian.configure_debian(
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
        return debian.install_debian_bootloader(
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
        return debian.health_check_debian(
            target_root,
            efi_mp,
            identity,
            disk,
            display_manager=self.display_manager,
            boot_log=boot_log,
        )


DRIVER = Debian13Gnome()
