# First Boot Linux @VERSION@

Write a branded First Boot USB. The seed is the live system. The creator builds the stick and writes it.

## Checksums

```bash
sha256sum -c SHA256SUMS
```

## Requirements

- Linux x86_64
- e2fsprogs (`mke2fs`)
- `pkexec` or `sudo` (write step only)

## Setup

```bash
mkdir firstboot && cd firstboot
chmod +x firstboot-creator-@VERSION@-x86_64.AppImage
mkdir seed
tar -xf firstboot-seed-@VERSION@.tar -C seed
```

Put `seed/` next to the AppImage. You can also set `FIRSTBOOT_SEED` to that directory.

If the AppImage does not start (FUSE disabled):

```bash
./firstboot-creator-@VERSION@-x86_64.AppImage --appimage-extract-and-run
```

A tarball of the same binaries is also on the release if you would rather not use an AppImage.

## Write a USB

```bash
./firstboot-creator-@VERSION@-x86_64.AppImage
```

A local page opens in your browser. Set shop name, support contact, live-user password, wallpapers, and recommended distros. Writing formats the chosen disk.

Do not run the GUI as root. The write step will ask for permission.

Official ISOs are cached in `~/.cache/firstboot/images/`.

## Command line

```bash
./firstboot-creator-@VERSION@-x86_64.AppImage estimate
./firstboot-creator-@VERSION@-x86_64.AppImage compose --name "Shop" --support "shop@example.com" --out shop.img
```

The AppImage copies `firstboot-write-usb` into `~/.cache/firstboot/bin/` before `pkexec`. From the tarball:

```bash
sudo ./firstboot-write-usb --image shop.img --device /dev/sdX
```

## Boot

UEFI-boot the PC from the USB. The buyer picks a distro. First Boot installs it and replaces itself.
