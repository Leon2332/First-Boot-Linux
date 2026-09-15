"""Ubuntu 26.04 LTS Plasma — FBL-native unpack.

Catalog ``install``: ``ubuntu-2604-plasma``.
Do not reuse this file for Ubuntu GNOME, Cinnamon, Budgie, MATE, or
other flavors. The ISO is Canonical's Kubuntu image
(``kubuntu-26.04-desktop-amd64.iso``); it is an Ubuntu edition, not an
independent distro.

Live casper identity is ``kubuntu``; the customer form is the installed
user. Display manager is SDDM. Single ``casper/filesystem.squashfs``
(Calamares live, not layered ubuntu-desktop-bootstrap). Unpack that
squashfs, then do what Calamares does after unpackfs: purge the live
greeter and Calamares itself, never reboot into Calamares.

Kubuntu has no install-sources.yaml. The squashfs *is* the Try/Install
session: SDDM autologins (casper 15autologin) into
``kubuntu-live-environment.desktop`` → ``kwin_wayland`` +
``kubuntu-installer-prompt`` (Try Kubuntu / Install Kubuntu). Official
Calamares ``packages.conf`` removes ``kubuntu-installer-prompt``,
``calamares*``, ``libcalamaresui3.3``, and ``cifs-utils``. Leaving the
prompt first-boots that greeter instead of the installed Plasma login.
"""

from __future__ import annotations

from collections.abc import Callable

from firstboot.installlocale import InstallLocale
from . import casper
from .common import InstalledDisk, InstallLog, OsIdentity

ID = "ubuntu-2604-plasma"
ALIASES: tuple[str, ...] = ()


class Ubuntu2604Plasma:
    id = ID
    aliases = ALIASES
    default_hostname = "ubuntu"
    display_name = "Ubuntu 26.04 Plasma"
    unpack_kind = "casper-single"
    display_manager = "sddm"
    live_usernames = ("kubuntu",)
    bootloader_id = "ubuntu"
    nvram_label = "Ubuntu"
    extra_live_packages = casper.KUBUNTU_EXTRA_LIVE_PACKAGES
    sddm_session = "plasma"

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
            extra_live_packages=self.extra_live_packages,
        )
        casper.write_sddm_session(target_root, self.sddm_session, log=log)

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


DRIVER = Ubuntu2604Plasma()
