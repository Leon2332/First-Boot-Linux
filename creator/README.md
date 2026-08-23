# Shop USB creator

Payload composer and USB writer for the retailer’s Linux PC.

It is not a remaster. Picking Mint instead of Fedora does not rebuild the live squashfs. The frozen seed stays in `../seed/`; this tool writes `retailer.conf`, shop `catalog.json` (ticked → recommended and staged; other installable distros → Other options as downloads), wallpapers, staged ISOs, and a three-partition disk (same layout as `../image/write-live.sh`). Contracts: [`../schemas/README.md`](../schemas/README.md), [`../USB-LAYOUT.md`](../USB-LAYOUT.md).

```bash
make
./bin/firstboot-creator                 # shop GUI (opens a local page)
./bin/firstboot-creator estimate        # stick / PC size
./bin/firstboot-creator compose --help
```

Needs a built seed (`../seed/build-in-docker.sh`) and `mke2fs` from e2fsprogs. Official ISOs are downloaded into `~/.cache/firstboot/images/` and checked against `../schemas/official-catalog.json`.

The GUI never runs as root. It writes a disk image first. Putting that image on `/dev/sdX` is `bin/firstboot-write-usb`, via `pkexec` or `sudo`.

Shop wrap is one AppImage (`../scripts/package-appimage.sh`). The binaries here are already one file each, no GTK. The seed is not inside the AppImage.

## Same repository

This directory stays in the First Boot Linux tree. The creator is a different program from the live kiosk, not a different product. It has to emit the same GPT labels and payload files the chooser already reads, and a `FBL-SYS` that matches the seed built here. A second repo would copy those contracts and drift.

Do not import `../chooser/`. That stack is the live session (Python + GTK4 on the Ubuntu seed).

Split to another git later only if release cycle or maintainers actually diverge. AppImage does not need its own repository.
