# OS install drivers

First Boot Linux copies a staged ISO’s kernel and initrd onto `FBL-SYS`,
injects a seed, and reboots into that installer. This directory is those
seeds. Shop USB→disk copy is `firstboot/install.py`, not here.

## Layout

| File | Catalog `"install"` | Installer |
| --- | --- | --- |
| `ubuntu_2604.py` | `ubuntu-2604` | Subiquity autoinstall |
| `mint_223.py` | `mint-223` | Ubiquity preseed (all Mint DEs) |
| `fedora_44_plasma.py` | `fedora-44-plasma` | Anaconda kickstart + liveimg |

`__init__.py` is the trampoline: plan, verify ISO, copy kernel/initrd,
inject the last cpio, rewrite GRUB, reboot. Do not put distro logic there.

Older sticks may still say `ubuntu-autoinstall`, `mint`, or
`fedora-kickstart`. Those are aliases on the driver objects. Keep them.

## Adding a distro

1. Copy `_template.py` to `<id>.py` (underscores in the filename).
2. Set `ID` to the hyphenated catalog id. Implement `boot_files`,
   `kernel_args`, `seed_files`. `after_prepare` is optional (Fedora shim).
3. Append the module to `_DRIVER_MODULES` in `__init__.py`.
4. Add a row to `schemas/official-catalog.json` with pinned ISO
   (`url`, `sha256`, `size_bytes`) and `"install": "<id>"`.
5. Add `<id>` to the `install` enum in both JSON schemas and to
   `INSTALL_DRIVERS` in `chooser/firstboot/payload.py`.
6. Add `chooser/tests/test_osinstall_<id>.py`.

The desktop environment is an **edition** in the catalog (which ISO),
not a Python file, unless that desktop needs a different installer.

## New version of the same distro (26.04 → 26.10)

If Subiquity/autoinstall (or Ubiquity, or Anaconda) is unchanged:
update `version`, `filename`, `url`, `sha256`, `size_bytes` in
`official-catalog.json` only. Keep `"install": "ubuntu-2604"`.

If the installer changed: copy `ubuntu_2604.py` → `ubuntu_2610.py`,
point `"install"` at `ubuntu-2610`, keep the old file until that ISO
is dropped from the catalog.
