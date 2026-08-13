# Golden live seed

Ubuntu 26.04 LTS (Resolute) **minbase**, built upward. This is the frozen First Boot system that later lives on `FBL-SYS` as `casper/filesystem.squashfs`.

It is not a desktop, not a shop remaster, and not bootable by itself. The kiosk session is step 3. The three-partition USB is step 4.

## What is in it

| Keep | Drop |
| --- | --- |
| Kernel (`linux-image-generic`) + full `linux-firmware` + microcode | GNOME / `ubuntu-desktop` |
| systemd, udev, casper, initramfs | snapd (apt-pinned out) |
| NetworkManager, `wpasupplicant`, systemd-resolved | unattended-upgrades, update-notifier |
| Mesa libraries (no compositor) | Ubuntu Pro / `cloud-init` / apport |
| Disk tools: parted, gdisk, ntfs-3g, lvm2, cryptsetup, rsync | App Center, ubiquity |
| `apt` / `dpkg` (hidden from the future UI) | |

`apt` stays so we can build and so a shop machine can be inspected in the field. Nothing in this image offers updates or a software store.

Retailer files (`catalog.json`, wallpapers, staged ISOs) are **not** here. They go on `FBL-DATA`.

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
./seed/build-in-docker.sh --skip-debootstrap   # reuse build/seed/rootfs
./seed/build-in-docker.sh --squashfs-only
./seed/build-in-docker.sh --clean
```

A first build downloads the archive and takes a while. Artifacts land in `build/seed/` (gitignored). The Docker wrapper builds the chroot in `/var/tmp` inside the container so `/` in the squashfs is root-owned (Snap Docker remaps bind-mount uids).

## Output

```text
build/seed/
  filesystem.squashfs     live root (casper)
  filesystem.size
  filesystem.manifest     package + version
  vmlinuz                 copied next to the squashfs for step 4
  initrd
  os-release
  BUILDINFO
  SHA256SUMS
  rootfs/                 chroot left in place for iteration
```

Check the package set without root:

```bash
./seed/check-packages.sh              # names exist on this Ubuntu
./seed/audit.sh build/seed/filesystem.manifest
```

## Layout of this directory

| Path | Role |
| --- | --- |
| `VERSION` | First Boot version stamped into `/etc/os-release` |
| `packages/keep.list` | Installed with `--no-install-recommends` |
| `packages/forbid.list` | Apt pin −1, then audited out of the manifest |
| `overlay/` | Copied into the rootfs as-is |
| `hooks/` | Run in the chroot after packages. `50-initramfs.sh` rebuilds the initrd so `casper.conf` is what live boot sees. |
| `build-seed.sh` | Real builder (root) |
| `build-in-docker.sh` | Same builder inside `ubuntu:26.04` |

Change the package lists, do not start from Ubuntu Desktop and uninstall.

Default squashfs compression is zstd. `FBL_COMP=xz` if you want a smaller, slower image.
