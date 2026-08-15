# USB install drive layout

How a First Boot Linux **shop USB** is laid out after the creator writes it.

This is a partitioned disk, not a single ISO9660 image. The UI may still say “write ISO.” On the stick it is GPT + three partitions. The same layout is copied onto the PC’s internal disk when the shop installs First Boot.

The normative v1 example below is a shop that staged Ubuntu and Linux Mint. The `docs/` mockup still shows a larger recommended set (Fedora, Pop!_OS, Bazzite, …); those are not `can_stage` until an install driver exists.

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
    ├── catalog.json
    ├── checksums.sha256        sums for this partition
    ├── wallpapers
    │   ├── dark.jpg
    │   └── light.jpg
    └── images
        ├── ubuntu-26.04-desktop-amd64.iso
        └── linuxmint-22.3-cinnamon-64bit.iso
```

`images/` only contains redistributable ISOs this retailer staged. Recommended can include a download-only row (official `redistributable: false`) with nothing under `images/`. Distros that are catalog-only are also not on the stick; the chooser downloads those later. v1 may stage only distros with official `can_stage`, `redistributable`, and `install` (Ubuntu, then Mint). Basenames come from `schemas/official-catalog.json` `filename` fields.

## What each payload file is

### `retailer.conf`

Shop-facing strings and paths. Full contract: [`schemas/README.md`](schemas/README.md). Example:

```ini
schema_version = 1
name = Example Computers
support = support@example.com  /  012 345 6789
wallpaper_dark = wallpapers/dark.jpg
wallpaper_light = wallpapers/light.jpg
```


### `catalog.json`

Full contract and JSON Schema: [`schemas/`](schemas/). Each edition is either local (`file` under `images/`) or download (`url`). Example (v1: Ubuntu + Mint staged) — same bytes as [`schemas/examples/catalog.json`](schemas/examples/catalog.json):

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
      "install": "ubuntu-autoinstall",
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
    },
    {
      "id": "linux-mint",
      "name": "Linux Mint",
      "version": "22.3",
      "tagline": "Familiar and easy",
      "description": "A stable desktop that feels at home for people coming from Windows. Multimedia and drivers work out of the box.",
      "family": "mint",
      "install": "mint",
      "editions": [
        {
          "id": "cinnamon",
          "name": "Cinnamon",
          "default": true,
          "local": true,
          "file": "images/linuxmint-22.3-cinnamon-64bit.iso",
          "sha256": "0000000000000000000000000000000000000000000000000000000000000000",
          "size_bytes": 2800000000
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

Official upstream ISOs (or later, disk images) named as in the official catalog.

### `checksums.sha256`

SHA-256 of `retailer.conf`, `catalog.json`, wallpapers, and every file in `images/`. Verified when the creator writes the USB, and again before a customer install.

## Boot and mount

1. Firmware loads `ESP/EFI/BOOT/BOOTX64.EFI` (Ubuntu’s Microsoft-signed shim), which loads `EFI/BOOT/grubx64.efi` (Canonical-signed gcdx64). Shop PCs with Secure Boot on do not enroll a First Boot key. Initrd is unsigned (same as Ubuntu).
2. The ESP `grub.cfg` stubs (`EFI/BOOT`, `EFI/firstboot`, `EFI/ubuntu`) search for label `FBL-SYS` and `configfile` `/boot/grub/grub.cfg`. The casper kernel command line lives on **FBL-SYS**, not on the ESP.
3. Casper boots `filesystem.squashfs` from the live medium (`live-media=/dev/disk/by-label/FBL-SYS`). FBL-SYS is not mounted at `/run/fbl`. The ESP is not mounted at `/boot/efi` in the live session.
4. `casper-bottom/27payload` appends `LABEL=FBL-DATA` → `/run/payload` to `/etc/fstab` (casper’s `12fstab` overwrites fstab first).
5. Chooser reads `/run/payload/catalog.json` and `/run/payload/retailer.conf`. First Boot’s own version is `/etc/os-release` in the squashfs (also `fbl/.disk/info` on the partition).


## Shop install onto a PC

The USB installer copies the three partitions onto the internal disk (same labels, same trees). After that, the machine first-boots from its own disk with the same payload already present.

When the customer picks a distro, the install backend uses the matching file under `payload/images/` (or a download), then **deletes First Boot and leftover ISOs** so the disk is a normal install of the chosen OS.
