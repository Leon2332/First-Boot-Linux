# USB install drive layout

How a First Boot Linux **shop USB** is laid out after the creator writes it.

This is a partitioned disk, not a single ISO9660 image. The UI may still say “write ISO.” On the stick it is GPT + three partitions. The same layout is copied onto the PC’s internal disk when the shop installs First Boot.

The normative v1 example below is a shop that staged Ubuntu GNOME. Official catalog is Ubuntu 26.04 GNOME only (FBL-native). Flavors, Mint, and Fedora stay out until they have native installers. The `docs/` mockup still shows a larger set; that is vision, not the creator menu.

## Partitions

```text
GPT
├── p1  ESP       FAT32   ~512 MB   EFI System, Secure Boot
├── p2  fbl       ext4    ~2 GB     golden First Boot live system
└── p3  payload   ext4    rest      retailer config + staged ISOs
```

| Partition | Label   | FS    | Role | Live mount | Changes per retailer |
| --------- | ------- | ----- | ---- | ---------- | -------------------- |
| p1        | `FBL-ESP` | FAT32 | EFI System (shim + gcdx64) | not mounted | No (same signed boot) |
| p2        | `FBL-SYS` | ext4  | Casper live medium (squashfs + kernel) | casper (`/cdrom` or equivalent), not `/run/fbl` | No (golden base) |
| p3        | `FBL-DATA` | ext4 | Shop payload | `/run/payload` (by label) | Yes |

- GPT + UEFI is the v1 path. Optional BIOS `bios_grub` partition later if shops still need CSM.
- `payload` is ext4 so files can be larger than 4 GB. Do not use FAT32 for ISOs.
- Stick size is driven by `payload/images/`. Three to five recommended ISOs usually wants **32 GB**; a larger set wants **64 GB**.

## File tree

```text
USB
│
├── ESP                         (p1, FBL-ESP, FAT32)
│   └── EFI
│       ├── BOOT
│       │   ├── BOOTX64.EFI     Ubuntu shim, Microsoft-signed
│       │   ├── grubx64.efi     gcdx64 (searches disks for /boot/grub/grub.cfg)
│       │   ├── grub.cfg        stub: search FBL-SYS, load /boot/grub/grub.cfg
│       │   └── mmx64.efi       MokManager, recovery only
│       ├── firstboot
│       │   ├── grub.cfg        stub: search FBL-SYS, load /boot/grub/grub.cfg
│       │   ├── shimx64.efi
│       │   └── grubx64.efi
│       └── ubuntu
│           └── grub.cfg        same stub (firmware that looks for EFI/ubuntu)
│
├── fbl                         (p2, FBL-SYS, ext4)
│   ├── .disk
│   │   ├── info                "First Boot Linux <version>"
│   │   └── ubuntu_dist_channel
│   ├── casper
│   │   ├── vmlinuz
│   │   ├── initrd
│   │   ├── filesystem.squashfs     read-only live root
│   │   ├── filesystem.size
│   │   ├── filesystem.manifest
│   │   └── filesystem.manifest-remove
│   ├── boot
│   │   └── grub
│   │       └── grub.cfg
│   ├── md5sum.txt
│   └── SHA256SUMS              sums for this partition only
│
└── payload                     (p3, FBL-DATA, ext4)
    ├── retailer.conf
    ├── language                optional live language id (customer choice)
    ├── keyboard                optional shop keyboard layout (xkb id)
    ├── timezone                optional live UTC offset (customer choice)
    ├── catalog.json
    ├── checksums.sha256        sums for this partition
    ├── wallpapers
    │   ├── dark.jpg
    │   └── light.jpg
    ├── logos                   optional; shop-pack PNG copies as <id>.png
    ├── custom                  optional; one folder per retailer pack
    │   └── pop-os
    │       ├── manifest.json
    │       ├── driver.py
    │       ├── logo.png
    │       └── locale
    │           └── af.po
    └── images
        ├── ubuntu-26.04-desktop-amd64.iso
        ├── linuxmint-22.3-cinnamon-64bit.iso
        ├── linuxmint-22.3-mate-64bit.iso
        └── linuxmint-22.3-xfce-64bit.iso
```

`images/` only contains redistributable ISOs this retailer staged (official downloads, plus shop-pack ISOs). Recommended can include a download-only row (official `redistributable: false`) with nothing under `images/`. Distros the shop did not tick, but that already have an install driver, go in `catalog.json` `catalog` (Other options, Download). Official ticks still require `can_stage`, `redistributable`, and `install` (Ubuntu, Linux Mint, Fedora Plasma). Shop packs are extra recommended rows; their driver lives under `custom/<id>/`, not in the squashfs. Basenames for official ISOs come from `schemas/official-catalog.json` `filename` fields; pack ISO basenames come from the pack `manifest.json` `editions[].filename`.

## What each payload file is

### `retailer.conf`

Shop-facing strings and paths. Full contract: [`schemas/README.md`](schemas/README.md). Example:

```ini
schema_version = 1
name = Example Computers
support = support@example.com  /  012 345 6789
wallpaper_dark = wallpapers/dark.jpg
wallpaper_light = wallpapers/light.jpg
language = en-us
keyboard = us
timezone = UTC+0000
```

`language` is the shop default (`en-us`, `en-gb`, `en-za`, `af`, …). Optional; missing means English (US). Old sticks that say `en` still mean English (US). `keyboard` is the shop keyboard layout (xkb id: `us`, `gb`, `de`, …). Optional; missing means `us`. It is not derived from language. `timezone` is the shop default UTC offset (`UTC+0000`, `UTC+0200`, …). Optional; missing means the live session stays on the seed’s UTC until the customer sets the clock. The live chooser may also write `payload/language` and `payload/timezone` when the customer changes those; they are the current choice and are not in `checksums.sha256`. Compose also writes `payload/keyboard` from the shop default.


### `catalog.json`

Full contract and JSON Schema: [`schemas/`](schemas/). Each edition is either local (`file` under `images/`) or download (`url`). Example (v1: Ubuntu GNOME staged) — same bytes as [`schemas/examples/catalog.json`](schemas/examples/catalog.json):

```json
{
  "schema_version": 1,
  "recommended": [
    {
      "id": "ubuntu",
      "name": "Ubuntu",
      "version": "26.04 LTS",
      "tagline": "Popular and well-supported",
      "description": "A polished desktop with excellent hardware support and a large software library. A safe default for most laptops.",
      "family": "ubuntu",
      "install": "ubuntu-2604-gnome",
      "secure_boot": true,
      "editions": [
        {
          "id": "gnome",
          "name": "GNOME",
          "default": true,
          "local": true,
          "file": "images/ubuntu-26.04-desktop-amd64.iso",
          "sha256": "0000000000000000000000000000000000000000000000000000000000000000",
          "size_bytes": 5900000000
        }
      ]
    }
  ],
  "catalog": []
}
```

`local: true` means the file must exist on this partition. The creator writes that flag only after the ISO is copied and verified. The creator menu (what shops may tick) is `schemas/official-catalog.json`, not this file.

### `wallpapers/`

Two images from the creator: dark and light. The live session switches with the Dark Style toggle.

### `images/`

Official upstream ISOs (or later, disk images) named as in the official catalog, plus ISOs from shop packs.

### `custom/`

One folder per retailer pack (`<id>/manifest.json`, `driver.py`, `logo.png`, optional `locale/<lang>.po`). The chooser loads `driver.py` when `catalog.json` `install` equals that id and it is not a baked-in driver. Pack `.po` files merge into the live language catalogue without replacing First Boot chrome. Empty when the shop used only the official list.

### `logos/`

Optional copies of shop-pack PNGs as `<id>.png`. Official logos stay in the squashfs.

### `checksums.sha256`

SHA-256 of `retailer.conf`, `catalog.json`, wallpapers, every file in `images/`, `custom/`, and `logos/`. Verified when the creator writes the USB, and again before a customer install.

## Boot and mount

1. Firmware loads `ESP/EFI/BOOT/BOOTX64.EFI` (Ubuntu’s Microsoft-signed shim), which loads `EFI/BOOT/grubx64.efi` (Canonical-signed gcdx64). Shop PCs with Secure Boot on do not enroll a First Boot key. Initrd is unsigned (same as Ubuntu).
2. The ESP `grub.cfg` stubs (`EFI/BOOT`, `EFI/firstboot`, `EFI/ubuntu`) search for label `FBL-SYS` and `configfile` `/boot/grub/grub.cfg`. The casper kernel command line lives on **FBL-SYS**, not on the ESP.
3. Casper boots `filesystem.squashfs` from the live medium (`live-media=/dev/disk/by-label/FBL-SYS`). FBL-SYS is not mounted at `/run/fbl`. The ESP is not mounted at `/boot/efi` in the live session.
4. `casper-bottom/27payload` appends `LABEL=FBL-DATA` → `/run/payload` to `/etc/fstab` (casper’s `12fstab` overwrites fstab first).
5. Chooser reads `/run/payload/catalog.json` and `/run/payload/retailer.conf`. First Boot’s own version is `/etc/os-release` in the squashfs (also `fbl/.disk/info` on the partition).


## Shop install onto a PC

The USB installer **recreates the GPT** on the internal disk (same labels, same trees) and copies the three filesystems. `FBL-DATA` grows to fill the rest of the disk. A whole-disk `dd` is not used — shop PCs are larger than the stick.

The chooser offers this only when the live session was booted from USB and there is a large enough non-USB disk. Confirm, then `firstboot-install-disk` (root via sudoers / pkexec) wipes the target, formats ESP + SYS + DATA, and rsyncs the trees from the USB mounts. Source and target are device paths, never `/dev/disk/by-label` (those names collide while the stick is still plugged in).

The copy written to the PC rewrites GRUB to find `FBL-SYS` by filesystem UUID first, then by label. `FBL-SYS` is formatted without `orphan_file` / `metadata_csum_seed` so gcdx64 can read it (the live image’s default `mkfs.ext4` is not GRUB-safe). Firmware that prefers the USB will boot the stick again; the done screen says to remove it.

After that, the machine first-boots from its own disk with the same payload already present.

When the customer picks Ubuntu, `firstboot-install-os` verifies the staged ISO, copies Ubuntu’s kernel and initrd onto **FBL-SYS** `/boot/osinstall/`, injects autoinstall.yaml into that initrd’s main archive, and rewrites `boot/grub/grub.cfg` so the next boot is Ubuntu autoinstall (`iso-scan/filename=` + `autoinstall`, `toram` when the ISO is on the same disk). Casper’s `/isodevice` mount of FBL-DATA is dropped after toram so curtin can take the disk. Subiquity then wipes the disk (ESP + root) and reboots into Ubuntu. Mint and other drivers are not implemented.
