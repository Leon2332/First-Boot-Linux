"""Ubuntu MATE 24.04.4 LTS — FBL-native unpack.

Catalog ``install``: ``ubuntu-2404-mate``.
Ubuntu MATE skipped 26.04 (releases go 25.10 → 26.10). Pin the 24.04.4 LTS
ISO as an Ubuntu edition, not a separate distro.
Do not reuse this file for Ubuntu GNOME, Cinnamon, Budgie, or later MATE.
Live casper identity is ``ubuntu``; the customer form is the installed user.
Display manager is LightDM (slick-greeter).

Match Canonical's installer, not the live session. ``install-sources.yaml``
default source is ``fsimage-layered://casper/minimal.standard.squashfs``
(``id: ubuntu-mate-desktop``). The live layer is Try-Ubuntu only: casper,
``ubuntu-mate-live-settings``, ``subiquity``, and
``ubuntu-desktop-bootstrap``. Copying it is not an installed MATE.

Unlike Cinnamon / Budgie 26.04, this 24.04 ISO keeps the kernel,
``linux-firmware``, and ``grub-efi-amd64-signed`` in the live overlay
(LP: #2026225). After unpack, ``dpkg -i`` the kernel/firmware debs from
the ISO pool (the live ISO is not a working apt repo: ``Release`` has
``Acquire-By-Hash: yes`` but no ``by-hash/`` files). Extract 24.04
``grub-efi-amd64-bin`` / ``grub2-common`` / ``grub-efi-amd64-signed`` /
``shim-signed`` with ``dpkg-deb -x`` — do not apt-install them (postinst
runs ``grub-install`` without a mounted ESP). Install layers already
have **initramfs-tools** (not dracut). Do not overlay First Boot's 26.04
``grubx64.efi.signed`` onto 24.04 modules —
``grub_efi_set_text_mode not found``.
"""

from __future__ import annotations

from collections.abc import Callable

from firstboot.installlocale import InstallLocale
from . import casper
from .common import InstalledDisk, InstallLog, OsIdentity

ID = "ubuntu-2404-mate"
ALIASES: tuple[str, ...] = ()


class Ubuntu2404Mate:
    id = ID
    aliases = ALIASES
    default_hostname = "ubuntu"
    display_name = "Ubuntu 24.04 MATE"
    unpack_kind = "casper-layered"
    display_manager = "lightdm"
    live_usernames = ("ubuntu",)
    bootloader_id = "ubuntu"
    nvram_label = "Ubuntu"

    def squashfs_relpaths(self, iso_mnt: str) -> list[str]:
        return casper.casper_squashfs_relpaths(iso_mnt)

    def iso_extras(self, iso_mnt: str) -> dict[str, str]:
        return casper.mate_iso_extras(iso_mnt)

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


DRIVER = Ubuntu2404Mate()
