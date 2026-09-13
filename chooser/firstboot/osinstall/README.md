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
| `ubuntu_2604_cinnamon.py` | `ubuntu-2604-cinnamon` | Native casper-layered (Ubuntu 26.04 Cinnamon, LightDM). Unpack is `minimal` + `standard` only. Those layers already have the kernel and **dracut**; build the initrd with `dracut --no-hostonly`. Do not copy the live layer, do not apt-install initramfs-tools (Conflicts with dracut). **Official catalog.** Ubuntu edition, not a separate distro. |
| `ubuntu_2604_budgie.py` | `ubuntu-2604-budgie` | Native casper-layered (Ubuntu 26.04 Budgie, SDDM). Unpack is `minimal` + `standard` only. Those layers already have the kernel and **dracut**; build the initrd with `dracut --no-hostonly`. Do not copy the live layer (seeds `ubuntu-desktop-bootstrap` rev 589 and a systemd snap mount that dies with `Can't lookup blockdev`). **Official catalog.** Ubuntu edition, not a separate distro. |
| `ubuntu_2404_mate.py` | `ubuntu-2404-mate` | Native casper-layered (Ubuntu MATE 24.04.4 LTS, LightDM). Unpack is `minimal` + `standard` only. Kernel / firmware / signed GRUB are live-only — `dpkg -i` those pool debs (the ISO is not a working apt repo). Extract 24.04 `grub2-common` / `grub-efi-amd64-bin` / `-signed` with `dpkg-deb -x`; do not apt-install grub (postinst needs a mounted ESP). **Official catalog.** Ubuntu edition; there is no 26.04 ISO. |
| `mint_223_cinnamon.py` | `mint-223-cinnamon` | Native casper-single (Linux Mint 22.3 Cinnamon). **Official catalog.** |
| `mint_223_mate.py` | `mint-223-mate` | Native casper-single (Linux Mint 22.3 MATE). **Official catalog.** |
| `mint_223_xfce.py` | `mint-223-xfce` | Native casper-single (Linux Mint 22.3 Xfce). **Official catalog.** |
| `fedora_44_plasma.py` | `fedora-44-plasma` | Native fedora-erofs (Fedora 44 KDE Plasma: Anaconda live copy, ESP+/boot+btrfs, plasmalogin). **Official catalog.** |
| `fedora_44_gnome.py` | `fedora-44-gnome` | Native fedora-erofs (Fedora 44 Workstation GNOME: same unpack, GDM). **Official catalog.** |
| `debian_13_gnome.py` | `debian-13-gnome` | Native live-single (Debian 13 GNOME: live-boot `live/filesystem.squashfs`, GDM, live user `user`). **Official catalog.** |
| `debian_13_plasma.py` | `debian-13-plasma` | Native live-single (Debian 13 KDE Plasma: same unpack, SDDM). **Official catalog.** |
| `debian_13_cinnamon.py` | `debian-13-cinnamon` | Native live-single (Debian 13 Cinnamon: same unpack, LightDM). **Official catalog.** |
| `debian_13_mate.py` | `debian-13-mate` | Native live-single (Debian 13 MATE: same unpack, LightDM). **Official catalog.** |

Official `official-catalog.json` currently lists **Ubuntu GNOME / Cinnamon / Budgie / MATE**, **Mint Cinnamon / MATE / Xfce**, **Fedora Plasma / GNOME**, and **Debian GNOME / Plasma / Cinnamon / MATE**. Cinnamon, Budgie, and MATE are Ubuntu editions (Ubuntu logo + DE name), not independent distros. Kubuntu / Lubuntu / Xubuntu stay out until each has a native file.

`__init__.py` is the trampoline. Native drivers (`unpack_kind`) run
`pipeline.py`. If the disk was already wiped and the install fails, the
error overlay offers **Restore First Boot Linux** (`restore.py`): rewrite
ESP + FBL-SYS + FBL-DATA from the RAM snapshot (seed + shop files, no
ISOs). Shop packs still use the legacy `boot_files` /
`kernel_args` / `seed_files` API.

Older sticks may still say `ubuntu-autoinstall`, `ubuntu-2604`, `mint`,
`mint-223`, or `fedora-kickstart`. Those ids belong to shipped distros
(no baked-in driver). Ubuntu GNOME on a **new** stick is
`ubuntu-2604-gnome`. Ubuntu Cinnamon is `ubuntu-2604-cinnamon`. Ubuntu
Budgie is `ubuntu-2604-budgie`. Ubuntu MATE is `ubuntu-2404-mate`.
Mint editions are `mint-223-cinnamon`, `mint-223-mate`, and
`mint-223-xfce`. Fedora Plasma is `fedora-44-plasma`. Fedora GNOME is
`fedora-44-gnome`. Debian GNOME is `debian-13-gnome`. Debian Plasma is
`debian-13-plasma`. Debian Cinnamon is `debian-13-cinnamon`. Debian
MATE is `debian-13-mate`. Do not reserve ids we do not ship (`nobara`,
`windows`, `freebsd`, `ubuntu-calamares-2604`, `debian-preseed`); a
shop pack may use them.

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
