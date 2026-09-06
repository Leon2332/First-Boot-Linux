# Golden live seed

Ubuntu 26.04 LTS (Resolute) **minbase**, built upward. This is the frozen First Boot system that later lives on `FBL-SYS` as `casper/filesystem.squashfs`.

It is not a desktop and not a shop remaster. The squashfs is the live root on `FBL-SYS`. `../image/write-live.sh` turns `build/seed/` into a bootable three-partition disk.

## What is in it

| Keep | Drop |
| --- | --- |
| Kernel (`linux-image-generic`) + full `linux-firmware` + microcode | GNOME / `ubuntu-desktop` |
| systemd, udev, casper, initramfs | snapd (apt-pinned out) |
| NetworkManager, `wpasupplicant`, systemd-resolved | unattended-upgrades, update-notifier |
| Mesa libraries | Ubuntu Pro / `cloud-init` / apport |
| labwc + GTK4 chooser (tty1 autologin; GNOME-like panel / QS, not a desktop) + GNOME Console + GNOME Web + System details helper + First Boot Cursor | App Center, ubiquity |
| Disk tools: parted, gdisk, ntfs-3g, lvm2, cryptsetup, rsync, `grub-efi-amd64-bin` (modules for native OS install) | |
| `apt` / `dpkg` (hidden from the future UI) | |
| OpenSSH server (field debug; key + live-user password) | |

`apt` stays so we can build and so a shop machine can be inspected in the field. Nothing in this image offers updates or a software store.

Retailer files (`catalog.json`, wallpapers, staged ISOs) are **not** here. They go on `FBL-DATA`.

The live session is not a desktop. `firstboot-kiosk.service` runs `firstboot-session` as `firstboot` on tty1 (`getty@tty1` is masked). That starts `labwc -S firstboot-chooser`. Ctrl+Alt+F2 is a debug TTY. `sshd` listens on port 22 (field debug). Host keys are generated at boot (`90-cleanup.sh` strips the build-chroot keys). The `fbl-audit` pubkey is in `/home/firstboot/.ssh/authorized_keys`. Empty live-user password cannot log in over SSH; a shop password can. The chooser paints the mockup chrome (top bar, quick settings, NetworkManager Ethernet/Wi-Fi, power) and reads `/run/payload/catalog.json`, `retailer.conf`, and the two wallpapers. On the live kiosk the 32px top bar and its menus are a separate layer-shell panel (always on top); the chooser stays always-on-bottom. Local vs download is whether the edition file exists under `images/`. USB-boot only: the app grid offers **Install to this device**, which copies ESP + `fbl` + payload onto the internal disk (`firstboot-install-disk`). Official Ubuntu GNOME, Mint, and Fedora Plasma unpack inside this session (`firstboot-install-os`): casper squashfs or Fedora EROFS, configure, Fedora/Canonical shim on the ESP, health check, then drop First Boot. Do not reboot into Subiquity, Ubiquity, or Anaconda. Fedora uses Fedora’s shim (Canonical GRUB cannot load a Fedora kernel with Secure Boot on). Drivers live in `chooser/firstboot/osinstall/`. The app-grid **Terminal** opens **GNOME Console** (`kgx`). **System details** opens `firstboot-sysinfo` (hardware from sysfs/DMI/PCI, software from os-release). **Web browser** opens **GNOME Web** (`epiphany-browser`, private of gnome-keyring / yelp). All three are separate Wayland clients above the always-on-bottom chooser and cannot move into the panel exclusive zone. `gstreamer1.0-plugins-bad` + `gstreamer1.0-libav` + `gstreamer1.0-gtk4` for media. The Boulder Dash package `epiphany` stays forbidden.

Casper overwrites `/etc/fstab`. `casper-bottom/27payload` appends `LABEL=FBL-DATA` → `/run/payload` so the shop partition is mounted by label after live boot. `28livepass` reads `firstboot/live-user.hash` from FBL-SYS (written by the creator) and applies it to the `firstboot` account. Missing file keeps the empty VM password.

## Build

On this repo, with Docker (no host `sudo`):

```bash
./seed/build-in-docker.sh
```

On an Ubuntu 26.04 host as root:

```bash
sudo apt-get install debootstrap squashfs-tools
sudo ./seed/build-seed.sh
```

Useful flags (both wrappers pass them through):

```bash
./seed/build-in-docker.sh --mirror http://na.archive.ubuntu.com/ubuntu
./seed/build-in-docker.sh --skip-debootstrap   # reuse the Docker work volume
./seed/build-in-docker.sh --squashfs-only
./seed/build-in-docker.sh --clean
```

A first build downloads the archive and takes a while. Artifacts land in `build/seed/` (gitignored). The Docker wrapper keeps the chroot in the named volume `firstboot-seed-work` (override with `FBL_SEED_VOLUME`) mounted at `/var/tmp/fbl-seed`, so `/` in the squashfs is root-owned (Snap Docker remaps bind-mount uids) and `--skip-debootstrap` / `--squashfs-only` reuse that volume. Host `sudo ./seed/build-seed.sh` leaves `build/seed/rootfs/` on disk instead. `--clean` deletes the work directory (volume contents or `build/seed/rootfs`).

## Output

```text
build/seed/
  filesystem.squashfs     live root (casper)
  filesystem.size
  filesystem.manifest     package + version
  vmlinuz                 copied next to the squashfs for the live disk
  initrd
  efi/                    Microsoft-signed shim + Canonical-signed gcdx64 for FBL-ESP
  os-release
  BUILDINFO
  SHA256SUMS
  rootfs/                 host-root builds only; Docker keeps this in the work volume
```

Check the package set without root:

```bash
./seed/check-packages.sh              # names exist on this Ubuntu
./seed/check-secureboot.sh            # Microsoft shim + Canonical GRUB/kernel
./seed/audit.sh build/seed/filesystem.manifest
```

## Layout of this directory

| Path | Role |
| --- | --- |
| `VERSION` | First Boot version stamped into `/etc/os-release` |
| `packages/keep.list` | Installed with `--no-install-recommends` |
| `packages/forbid.list` | Apt pin −1, then audited out of the manifest |
| `overlay/` | Copied into the rootfs as-is |
| `cursors/` | First Boot Cursor SVG sources. `build-seed.sh` rasterizes them into `/usr/share/icons/First Boot Cursor`. |
| `hooks/` | Run in the chroot after packages. `45-kiosk.sh` creates the live user. `50-initramfs.sh` rebuilds the initrd so `casper.conf` and `casper-bottom/27payload` are what live boot sees. |
| `build-seed.sh` | Real builder (root). Also installs `../chooser/` into `/usr/bin`. |
| `build-in-docker.sh` | Same builder inside `ubuntu:26.04` |

Change the package lists, do not start from Ubuntu Desktop and uninstall.

Default squashfs compression is zstd. `FBL_COMP=xz` if you want a smaller, slower image.
