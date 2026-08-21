# Live disk image

Turns `build/seed/` plus a dummy payload into a bootable GPT disk, then boots it in a UEFI VM.

This is the daily test loop. It is not a shop USB and does not flash a stick.

```text
GPT
├── p1  FBL-ESP   FAT32   512 MiB   shim + gcdx64
├── p2  FBL-SYS   ext4      2 GiB   casper/ + squashfs
└── p3  FBL-DATA  ext4       rest   dummy retailer.conf + catalog.json
```

## Write

Needs a seed (`./seed/build-in-docker.sh`). Then:

```bash
./image/write-live.sh
```

No host `sudo`: the script builds a privileged Ubuntu 26.04 container and writes `build/fbl-live.img` (sparse, 4G). Pass `--clean` to replace an existing image.

## Boot

```bash
./image/boot-vm.sh
```

`--write` rebuilds the image first. Host `qemu-system-x86_64` + `ovmf` are used when installed:

```bash
sudo apt-get install qemu-system-x86 qemu-system-gui ovmf
```

Otherwise the same QEMU line runs in Docker (`--device /dev/kvm`). labwc needs a DRM node; the VM gets `virtio-vga`, not serial-only.

```bash
./image/boot-vm.sh --write --display gtk
./image/boot-vm.sh --smoke          # headless; watch serial for a live session
./image/boot-vm.sh --secure-boot --smoke   # same, with firmware Secure Boot on
```

Serial goes to `build/fbl-vm-serial.log`. Ctrl+Alt+F2 in the guest is a debug TTY.

`--smoke` succeeds only when serial shows `/run/payload` mounted **and** `getty@tty1` started. Multi-user.target or serial-getty alone is not enough. The last console on the kernel command line is `ttyS0` so systemd prints there; tty1 still gets the kiosk. `--write` rebuilds the image at `--img` / `FBL_LIVE_IMG`.

`--secure-boot` is the step 6 gate. It uses `OVMF_CODE_4M.secboot.fd` and a vars file cloned from `OVMF_VARS_4M.ms.fd` (Microsoft keys enrolled, Secure Boot on). That approximates a shop PC; it is not a hardware result. The ESP already carries Ubuntu’s Microsoft-signed shim and Canonical-signed gcdx64. Combined with `--smoke`, serial must also show `firstboot-sb: SecureBoot=1`. `./seed/check-secureboot.sh` checks the seed signatures without booting.

## Dummy payload

`dummy-payload/` is a valid shop catalog (Ubuntu + Mint, no staged ISOs). The chooser treats missing `images/` files as downloads. Missing wallpapers are filled from the mockup photos at write time: annie-spratt → `dark.jpg`, ands-mahardika → `light.jpg`. Casper mounts `LABEL=FBL-DATA` at `/run/payload`. Host chrome check: `chooser/firstboot-chooser --payload image/dummy-payload --screenshot /tmp/fbl.png` (add `--menu qs` / `--light` / `--menu terminal` / `--shop progress` / `--catalog`); the dummy dir has no wallpapers until write time. `--shop` is the USB → disk overlay; it does not write a disk. `--menu terminal` opens the in-kiosk VTE window. `--catalog` opens the Other options popover.
