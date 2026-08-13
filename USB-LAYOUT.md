# USB install drive layout

How a First Boot Linux **shop USB** is laid out after the creator writes it.

This is a partitioned disk, not a single ISO9660 image. The UI may still say “write ISO.” On the stick it is GPT + three partitions. The same layout is copied onto the PC’s internal disk when the shop installs First Boot.

Example below is one retailer who staged Ubuntu, Linux Mint, Fedora, Pop!_OS, and Bazzite.

## Partitions

```text
GPT
├── p1  ESP       FAT32   ~512 MB   EFI System, Secure Boot
├── p2  fbl       ext4    ~2 GB     golden First Boot live system
└── p3  payload   ext4    rest      retailer config + staged ISOs
```

| Partition | Label   | FS    | Mount (live)     | Changes per retailer |
| --------- | ------- | ----- | ---------------- | -------------------- |
| p1        | `FBL-ESP` | FAT32 | `/boot/efi`    | No (same signed boot) |
| p2        | `FBL-SYS` | ext4  | `/run/fbl`     | No (golden base)      |
| p3        | `FBL-DATA` | ext4 | `/run/payload` | Yes                   |

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
│       │   ├── BOOTX64.EFI     shim (Secure Boot first stage)
│       │   ├── grubx64.efi
│       │   └── mmx64.efi       MokManager, recovery only
│       └── firstboot
│           ├── grub.cfg        points kernel at FBL-SYS
│           ├── shimx64.efi
│           └── grubx64.efi
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
        ├── linuxmint-22.3-cinnamon-64bit.iso
        ├── Fedora-KDE-Live-x86_64-44.iso
        ├── pop-os_24.04_amd64_intel_20.iso
        └── bazzite-stable-amd64.iso
```

`images/` only contains what this retailer marked recommended / on-disk. Distros that are catalog-only are not on the stick; the chooser downloads those later. v1 install support is Ubuntu then Mint, so a first shop USB may only have those two files even though this tree shows a larger set.

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

First Boot’s version is not here. It lives on the `fbl` partition.

### `catalog.json`

Chooser source of truth for this shop. Full contract and JSON Schema: [`schemas/`](schemas/). Each edition is either local (`file` under `images/`) or download (`url`). Example (v1: Ubuntu + Mint staged):

```json
{
  "schema_version": 1,
  "recommended": [
    {
      "id": "ubuntu",
      "name": "Ubuntu",
      "version": "26.04 LTS",
      "tagline": "Popular and well-supported",
      "description": "A polished desktop with excellent hardware support and a large software library.",
      "family": "ubuntu",
      "install": "ubuntu-autoinstall",
      "editions": [
        {
          "id": "gnome",
          "name": "GNOME",
          "default": true,
          "local": true,
          "file": "images/ubuntu-26.04-desktop-amd64.iso",
          "sha256": "…",
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

Exactly two images from the creator: dark and light. The live session switches with the Dark Style toggle.

### `images/`

Official upstream ISOs (or later, disk images) named as in the official catalog. No random shop-dropped ISOs in v1.

### `checksums.sha256`

SHA-256 of `retailer.conf`, `catalog.json`, wallpapers, and every file in `images/`. Verified when the creator writes the USB, and again before a customer install.

## Boot and mount

1. Firmware loads `ESP/EFI/BOOT/BOOTX64.EFI` (shim).
2. GRUB reads `EFI/firstboot/grub.cfg`, kernel + initrd from `fbl/casper/`.
3. Casper boots `filesystem.squashfs`.
4. Session mounts `FBL-DATA` at `/run/payload` (by label, not by device name).
5. Chooser reads `/run/payload/catalog.json` and `/run/payload/retailer.conf`.

The squashfs does not contain retailer files. Swapping Mint for Bazzite never remasters `fbl`.

## Shop install onto a PC

The USB installer copies the three partitions onto the internal disk (same labels, same trees). After that, the machine first-boots from its own disk with the same payload already present.

When the customer picks a distro, the install backend uses the matching file under `payload/images/` (or a download), then **deletes First Boot and leftover ISOs** so the disk is a normal install of the chosen OS.
