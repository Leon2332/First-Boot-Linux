# Live disk image

Turns `build/seed/` plus a dummy payload into a bootable GPT disk, then boots it in a UEFI VM.

This is the daily test loop. It is not a shop USB and does not flash a stick.

```text
GPT
├── p1  FBL-ESP   FAT32   512 MiB   shim + gcdx64
├── p2  FBL-SYS   ext4      2 GiB   casper/ + squashfs
└── p3  FBL-DATA  ext4       rest   dummy retailer.conf
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

Otherwise the same QEMU line runs in Docker (`--device /dev/kvm`). Cage needs a DRM node; the VM gets `virtio-vga`, not serial-only.

```bash
./image/boot-vm.sh --write --display gtk
./image/boot-vm.sh --smoke          # headless; watch serial for a live session
```

Serial goes to `build/fbl-vm-serial.log`. Ctrl+Alt+F2 in the guest is a debug TTY.

`--smoke` is a success when serial shows a live session (`Welcome to First Boot Linux`, `FBL-DATA` mounted at `/run/payload`, `getty@tty1`). The last console on the kernel command line is `ttyS0` so systemd prints there; tty1 still gets the kiosk.

## Dummy payload

`dummy-payload/` is a valid empty shop catalog (no staged ISOs). Wallpapers are copied from `docs/assets/Wallpaper/` at write time. Casper mounts `LABEL=FBL-DATA` at `/run/payload`.
