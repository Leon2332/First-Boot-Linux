"""Copy this file to ``<id>.py`` (underscores) and fill it in.

Catalog ``install`` must equal ``ID`` (hyphens). Example: file
``deepin_25.py`` → ``ID = "deepin-25"`` → official-catalog.json
``"install": "deepin-25"``.

For an official distro: add ``ID`` to the official-catalog install enum
and to ``chooser/firstboot/payload.py`` ``INSTALL_DRIVERS``, pin the ISO
on ``official-catalog.json``, add ``tests/test_osinstall_<id>.py``, and
register the module in ``osinstall/__init__.py`` ``_DRIVER_MODULES``.

For a shop pack: put this file in a zip as ``driver.py`` with a
``manifest.json`` (see ``schemas/custom-driver.schema.json``). Do not add
it to the official catalog. ``ID`` must match the pack id. The live
session loads it from ``payload/custom/<id>/driver.py``.

A new ISO of the *same* installer (same YAML/preseed/kickstart) is
catalog-only — do not copy this file. New file only when the installer
changed.
"""

from __future__ import annotations

from firstboot.installlocale import InstallLocale
from firstboot.osinstall.common import (
    OsIdentity,
    OsInstallError,
    OsInstallPlan,
    casper_boot_files,
    casper_kernel_args,
)

ID = "example-1"
ALIASES: tuple[str, ...] = ()


class Example:
    id = ID
    aliases = ALIASES
    default_hostname = "example"

    def boot_files(self, iso_mnt: str) -> tuple[str, str]:
        # Paths to the installer kernel and initrd on the mounted ISO.
        return casper_boot_files(iso_mnt)

    def kernel_args(self, iso_rel: str, *, toram: bool, iso_path: str = "") -> str:
        extra = "your-installer-flags"
        return casper_kernel_args(iso_rel, toram=toram, extra=extra)

    def seed_files(
        self,
        identity: OsIdentity,
        target_path: str,
        serial: str,
        locale: InstallLocale | None = None,
    ) -> dict[str, str | bytes]:
        # Files injected into the last cpio of the installer initrd.
        # Keys are paths relative to the initrd root.
        raise OsInstallError(f"{ID} is a template, not an installer.")

    def after_prepare(
        self,
        iso_mnt: str,
        plan: OsInstallPlan,
        sys_uuid: str,
        label: str,
        linux_args: str,
    ) -> None:
        return


DRIVER = Example()
