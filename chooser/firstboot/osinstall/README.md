# OS install drivers

Official ISOs install **inside** the First Boot session: unpack the live
filesystem, configure, health-check, drop First Boot, reboot. Catalog
rows that are not on disk are fetched onto `payload/images/` first
(`install-os --fetch`), then the same path. Shop USB→disk copy is
`firstboot/install.py`, not here.

Do not reboot into Subiquity, Calamares, Ubiquity, or Anaconda.

## Layout

| File | Catalog `"install"` | Kind |
| --- | --- | --- |
| `ubuntu_2604_gnome.py` | `ubuntu-2604-gnome` | Native casper-layered (Ubuntu 26.04 GNOME). **Official catalog.** |
| `mint_223_cinnamon.py` | `mint-223-cinnamon` | Native casper-single (Linux Mint 22.3 Cinnamon). **Official catalog.** |
| `mint_223_mate.py` | `mint-223-mate` | Native casper-single (Linux Mint 22.3 MATE). **Official catalog.** |
| `mint_223_xfce.py` | `mint-223-xfce` | Native casper-single (Linux Mint 22.3 Xfce). **Official catalog.** |

Official `official-catalog.json` currently lists **Ubuntu GNOME** and **Mint Cinnamon / MATE / Xfce**. Do not add flavors / Fedora back until each has a native file.

`__init__.py` is the trampoline. Native drivers (`unpack_kind`) run
`pipeline.py`. Shop packs still use the legacy `boot_files` /
`kernel_args` / `seed_files` API.

Older sticks may still say `ubuntu-autoinstall`, `ubuntu-2604`, `mint`,
`mint-223`, or `fedora-kickstart`. Those ids are reserved (no baked-in
driver). Ubuntu GNOME on a **new** stick is `ubuntu-2604-gnome`. Mint
editions are `mint-223-cinnamon`, `mint-223-mate`, and `mint-223-xfce`.

## Adding an official ISO

1. Copy `ubuntu_2604_gnome.py` (or the closest native file) to `<id>.py`
   (underscores in the filename). Do not subclass a family driver.
2. Set `ID` to the hyphenated catalog id for **that edition**. Set
   `unpack_kind`, `display_manager`, `live_usernames`. Implement
   `unpack`, `configure`, `bootloader`, `health_check` (call shared
   steps in `common.py` / `casper.py`).
3. Append the module to `_DRIVER_MODULES` in `__init__.py`.
4. Add a row to `schemas/official-catalog.json` with pinned ISO and
   `"install": "<id>"` on the distro (optional `install` on the edition).
5. Add `<id>` to `INSTALL_DRIVERS` in `chooser/firstboot/payload.py`
   and to the official-catalog `install` enum.
6. Add `chooser/tests/test_osinstall_<id>.py`.

A shop that will not merge into this tree ships a `.zip` pack instead
(`schemas/custom-driver.schema.json`). Pack `driver.py` still uses the
legacy `boot_files` / `kernel_args` / `seed_files` API until shop packs
are decided. Do not register those modules here.

The desktop environment is an **edition** and a **Python file** (one
file per ISO). Mint Cinnamon and Mint MATE are two files even if they
start identical.

## New version of the same distro (26.04 → 26.10)

A new point release of the **same** ISO (hash/size only) is catalog-only.

A new version (`26.04` → `26.10`) is a **new file**. Copy the old one;
do not overwrite it.
