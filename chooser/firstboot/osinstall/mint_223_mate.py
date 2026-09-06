"""Linux Mint 22.3 MATE — FBL-native unpack.

Catalog ``install``: ``mint-223-mate``.
Do not reuse this file for Mint Cinnamon, Xfce, or Ubuntu.
Live casper identity is ``mint``; the customer form is the installed user.
"""

from __future__ import annotations

from collections.abc import Callable

from firstboot.installlocale import InstallLocale
from . import casper
from .common import InstalledDisk, InstallLog, OsIdentity

ID = "mint-223-mate"
ALIASES: tuple[str, ...] = ()


class Mint223Mate:
    id = ID
    aliases = ALIASES
    default_hostname = "mint"
    display_name = "Linux Mint 22.3 MATE"
    unpack_kind = "casper-single"
    display_manager = "lightdm"
    live_usernames = ("mint",)
    # Canonical signed grubx64.efi.signed prefixes /EFI/ubuntu. Do not use
    # linuxmint here or shim loads GRUB with no config (grub>).
    bootloader_id = "ubuntu"
    nvram_label = "Linux Mint"

    def squashfs_relpaths(self, iso_mnt: str) -> list[str]:
        return casper.casper_squashfs_relpaths(iso_mnt)

    def unpack(
        self,
        iso_mnt: str,
        target_root: str,
        on_progress: Callable[[int], None] | None = None,
        log: InstallLog | None = None,
    ) -> None:
        casper.unpack_casper_single(
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
        casper.configure_casper(
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


DRIVER = Mint223Mate()
