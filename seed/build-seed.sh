#!/usr/bin/env bash
# Golden First Boot live seed: Ubuntu 26.04 minbase + appliance packages.
# Requires root. Prefer seed/build-in-docker.sh on a workstation.
set -euo pipefail

SEED_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_DIR=$(cd "$SEED_DIR/.." && pwd)
VERSION=$(tr -d '[:space:]' < "$SEED_DIR/VERSION")

SUITE=${FBL_SUITE:-resolute}
ARCH=${FBL_ARCH:-amd64}
MIRROR=${FBL_MIRROR:-http://archive.ubuntu.com/ubuntu}
SECURITY_MIRROR=${FBL_SECURITY_MIRROR:-http://security.ubuntu.com/ubuntu}
COMP=${FBL_COMP:-zstd}
WORK=${FBL_WORK:-$REPO_DIR/build/seed}
OUT=${FBL_OUT:-}

SKIP_DEBOOTSTRAP=0
SQUASHFS_ONLY=0
AUDIT_ONLY=0
CLEAN=0

usage() {
  cat <<EOF
Usage: $0 [options]

  --work DIR           chroot work directory (default: build/seed)
  --out DIR            artifact directory (default: same as --work)
  --mirror URL         Ubuntu archive (default: $MIRROR)
  --security-mirror URL
  --suite NAME         debootstrap suite (default: $SUITE)
  --comp xz|zstd       squashfs compression (default: $COMP)
  --skip-debootstrap   reuse an existing rootfs
  --squashfs-only      remake squashfs from an existing rootfs
  --audit-only         audit rootfs or filesystem.manifest, then exit
  --clean              delete work directory first
EOF
}

while [[ $# -gt 0 ]]; do
  case $1 in
    --work) WORK=$(readlink -f "$2"); shift 2 ;;
    --out) OUT=$(readlink -f "$2"); shift 2 ;;
    --mirror) MIRROR=$2; shift 2 ;;
    --security-mirror) SECURITY_MIRROR=$2; shift 2 ;;
    --suite) SUITE=$2; shift 2 ;;
    --comp) COMP=$2; shift 2 ;;
    --skip-debootstrap) SKIP_DEBOOTSTRAP=1; shift ;;
    --squashfs-only) SQUASHFS_ONLY=1; shift ;;
    --audit-only) AUDIT_ONLY=1; shift ;;
    --clean) CLEAN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "error: unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

ROOTFS=$WORK/rootfs
[[ -n $OUT ]] || OUT=$WORK
MOUNTED=0

log() { printf '==> %s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

need_root() {
  [[ $(id -u) -eq 0 ]] || die "run as root, or use seed/build-in-docker.sh"
}

list_pkgs() {
  grep -vE '^[[:space:]]*(#|$)' "$1" | awk '{print $1}'
}

unmount_rootfs() {
  [[ -d $ROOTFS ]] || return 0
  local mp
  # Longest path first. /proc/mounts encodes spaces as \040.
  mapfile -t mps < <(awk -v p="$ROOTFS" '
    {
      m = $2
      gsub(/\\040/, " ", m)
      if (m == p || index(m, p "/") == 1) print length(m), m
    }
  ' /proc/mounts | sort -nr | cut -d" " -f2-)
  for mp in "${mps[@]+"${mps[@]}"}"; do
    umount -l "$mp" 2>/dev/null || true
  done
  MOUNTED=0
}

cleanup() {
  unmount_rootfs
}
trap cleanup EXIT

mount_rootfs() {
  mkdir -p "$ROOTFS"/{dev,dev/pts,proc,sys,run}
  mount -t proc proc "$ROOTFS/proc"
  mount -t sysfs sys "$ROOTFS/sys"
  mount --bind /dev "$ROOTFS/dev"
  mount -t devpts devpts "$ROOTFS/dev/pts"
  # Private tmpfs: a bind of host /run lets chroot systemctl talk to the
  # workstation's PID 1 (enable/disable/mask).
  mount -t tmpfs -o mode=755 tmpfs "$ROOTFS/run"
  mkdir -p "$ROOTFS/run/lock" "$ROOTFS/run/systemd"
  MOUNTED=1
}

chroot_run() {
  DEBIAN_FRONTEND=noninteractive LC_ALL=C.UTF-8 chroot "$ROOTFS" "$@"
}

write_sources() {
  mkdir -p "$ROOTFS/etc/apt/sources.list.d"
  rm -f "$ROOTFS/etc/apt/sources.list"
  cat > "$ROOTFS/etc/apt/sources.list.d/ubuntu.sources" <<EOF
Types: deb
URIs: ${MIRROR}
Suites: ${SUITE} ${SUITE}-updates ${SUITE}-backports
Components: main restricted universe multiverse
Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg

Types: deb
URIs: ${SECURITY_MIRROR}
Suites: ${SUITE}-security
Components: main restricted universe multiverse
Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg
EOF
}

write_forbid_pins() {
  local dest=$ROOTFS/etc/apt/preferences.d/firstboot-forbid
  mkdir -p "$(dirname "$dest")"
  : > "$dest"
  while read -r pkg; do
    cat >> "$dest" <<EOF
Package: ${pkg}
Pin: release *
Pin-Priority: -1

EOF
  done < <(list_pkgs "$SEED_DIR/packages/forbid.list")
}

write_policy_rcd() {
  cat > "$ROOTFS/usr/sbin/policy-rc.d" <<'EOF'
#!/bin/sh
exit 101
EOF
  chmod 755 "$ROOTFS/usr/sbin/policy-rc.d"
}

copy_apt_early() {
  # Apt policy only. Package-owned conffiles go on after install (see copy_overlay).
  mkdir -p "$ROOTFS/etc/apt/apt.conf.d"
  cp -a "$SEED_DIR/overlay/etc/apt/apt.conf.d/00firstboot" \
    "$ROOTFS/etc/apt/apt.conf.d/00firstboot"
}

copy_overlay() {
  # Do not preserve host uid: overlay files live in the user's tree.
  # xcursor-themes points default/index.theme at /etc/alternatives (often dangling).
  if [[ -L $ROOTFS/usr/share/icons/default ]]; then
    rm -f "$ROOTFS/usr/share/icons/default"
  elif [[ -L $ROOTFS/usr/share/icons/default/index.theme ]]; then
    rm -f "$ROOTFS/usr/share/icons/default/index.theme"
  fi
  cp -a --no-preserve=ownership "$SEED_DIR/overlay/." "$ROOTFS/"
  mkdir -p "$ROOTFS/etc/firstboot"
  printf '%s\n' "$VERSION" > "$ROOTFS/etc/firstboot/version"
  printf '%s\n' "$SUITE" > "$ROOTFS/etc/firstboot/suite"
  chown root:root "$ROOTFS"
  # Only files this function just copied. A whole-rootfs `find ! -user 0`
  # on --skip-debootstrap rewrites /home/firstboot (uid 1000) to root.
  local rel
  while IFS= read -r -d '' rel; do
    chown root:root "$ROOTFS/$rel"
  done < <(cd "$SEED_DIR/overlay" && find . -print0)
  chmod 440 "$ROOTFS/etc/sudoers.d/firstboot"
  if [[ -f $ROOTFS/etc/sudoers.d/firstboot-install ]]; then
    chmod 440 "$ROOTFS/etc/sudoers.d/firstboot-install"
  fi
  if [[ -f $ROOTFS/etc/sudoers.d/firstboot-osinstall ]]; then
    chmod 440 "$ROOTFS/etc/sudoers.d/firstboot-osinstall"
  fi
  if [[ -f $ROOTFS/etc/sudoers.d/firstboot-timezone ]]; then
    chmod 440 "$ROOTFS/etc/sudoers.d/firstboot-timezone"
  fi
  chmod 755 "$ROOTFS/usr/share/initramfs-tools/scripts/casper-bottom/27payload"
  if [[ -f $ROOTFS/usr/share/initramfs-tools/scripts/casper-bottom/28livepass ]]; then
    chmod 755 "$ROOTFS/usr/share/initramfs-tools/scripts/casper-bottom/28livepass"
  fi
  if [[ -f $ROOTFS/usr/share/initramfs-tools/scripts/casper-bottom/29sshkeys ]]; then
    chmod 755 "$ROOTFS/usr/share/initramfs-tools/scripts/casper-bottom/29sshkeys"
  fi
  if [[ -f $ROOTFS/usr/libexec/firstboot/print-secureboot ]]; then
    chmod 755 "$ROOTFS/usr/libexec/firstboot/print-secureboot"
  fi
  if [[ -f $ROOTFS/usr/libexec/firstboot/install-disk ]]; then
    chmod 755 "$ROOTFS/usr/libexec/firstboot/install-disk"
  fi
  if [[ -f $ROOTFS/usr/libexec/firstboot/install-os ]]; then
    chmod 755 "$ROOTFS/usr/libexec/firstboot/install-os"
  fi
  if [[ -f $ROOTFS/usr/libexec/firstboot/set-timezone ]]; then
    chmod 755 "$ROOTFS/usr/libexec/firstboot/set-timezone"
  fi
  if [[ -f $ROOTFS/usr/share/firstboot/labwc/autostart ]]; then
    chmod 755 "$ROOTFS/usr/share/firstboot/labwc/autostart"
  fi
  if [[ -f $ROOTFS/usr/bin/firstboot-login ]]; then
    chmod 755 "$ROOTFS/usr/bin/firstboot-login"
  fi
}

install_chooser() {
  install -D -m 0755 "$REPO_DIR/chooser/firstboot-chooser" \
    "$ROOTFS/usr/bin/firstboot-chooser"
  install -D -m 0755 "$REPO_DIR/chooser/firstboot-browser" \
    "$ROOTFS/usr/bin/firstboot-browser"
  install -D -m 0755 "$REPO_DIR/chooser/firstboot-sysinfo" \
    "$ROOTFS/usr/bin/firstboot-sysinfo"
  install -D -m 0755 "$REPO_DIR/chooser/firstboot-session" \
    "$ROOTFS/usr/bin/firstboot-session"
  install -D -m 0755 "$REPO_DIR/chooser/firstboot-install-disk" \
    "$ROOTFS/usr/libexec/firstboot/install-disk"
  install -D -m 0755 "$REPO_DIR/chooser/firstboot-install-os" \
    "$ROOTFS/usr/libexec/firstboot/install-os"
  install -D -m 0755 "$REPO_DIR/chooser/firstboot-set-timezone" \
    "$ROOTFS/usr/libexec/firstboot/set-timezone"
  install -d -m 0755 \
    "$ROOTFS/usr/share/firstboot/python" \
    "$ROOTFS/usr/share/firstboot/distros" \
    "$ROOTFS/usr/share/firstboot/status" \
    "$ROOTFS/usr/share/firstboot/apps" \
    "$ROOTFS/usr/share/firstboot/search-engines"
  # dest must not already exist: `cp -a src dest` then nests dest/firstboot/.
  rm -rf "$ROOTFS/usr/share/firstboot/python/firstboot"
  cp -a "$REPO_DIR/chooser/firstboot" "$ROOTFS/usr/share/firstboot/python/firstboot"
  find "$ROOTFS/usr/share/firstboot/python" -depth -type d -name __pycache__ -exec rm -rf {} +
  local logo="$REPO_DIR/docs/Logo/First Boot Linux.png"
  local logo_dark="$REPO_DIR/docs/Logo/First Boot Linux - dark mode.png"
  local logo_light="$REPO_DIR/docs/Logo/First Boot Linux- light mode.png"
  if [[ -f $logo ]]; then
    install -D -m 0644 "$logo" "$ROOTFS/usr/share/firstboot/logo.png"
  fi
  if [[ -f $logo_dark ]]; then
    install -D -m 0644 "$logo_dark" "$ROOTFS/usr/share/firstboot/logo-wordmark-dark.png"
  fi
  if [[ -f $logo_light ]]; then
    install -D -m 0644 "$logo_light" "$ROOTFS/usr/share/firstboot/logo-wordmark-light.png"
  fi
  if [[ -d $REPO_DIR/docs/assets/distros ]]; then
    cp -a "$REPO_DIR/docs/assets/distros/." "$ROOTFS/usr/share/firstboot/distros/"
  fi
  if [[ -d $REPO_DIR/docs/assets/status ]]; then
    cp -a "$REPO_DIR/docs/assets/status/." "$ROOTFS/usr/share/firstboot/status/"
  fi
  if [[ -d $REPO_DIR/docs/assets/apps ]]; then
    cp -a "$REPO_DIR/docs/assets/apps/." "$ROOTFS/usr/share/firstboot/apps/"
  fi
  if [[ -d $REPO_DIR/docs/assets/search-engines ]]; then
    local icon
    for icon in google.png brave.png duckduckgo.png; do
      if [[ -f $REPO_DIR/docs/assets/search-engines/$icon ]]; then
        install -m 0644 "$REPO_DIR/docs/assets/search-engines/$icon" \
          "$ROOTFS/usr/share/firstboot/search-engines/$icon"
      fi
    done
  fi
  PYTHONPATH="$REPO_DIR/chooser${PYTHONPATH:+:$PYTHONPATH}" python3 -c \
    "from firstboot.browser import write_start_page; write_start_page('$ROOTFS/usr/share/firstboot/start.html')"
  chown -R root:root "$ROOTFS/usr/share/firstboot"
  find "$ROOTFS/usr/share/firstboot" -type d -exec chmod 755 {} +
  find "$ROOTFS/usr/share/firstboot" -type f -exec chmod 644 {} +
}

install_cursors() {
  local builder="$SEED_DIR/cursors/build_theme.py"
  local svg="$SEED_DIR/cursors/src/svg/left_ptr.svg"
  local dest="$ROOTFS/usr/share/icons/First Boot Cursor"
  [[ -f $builder ]] || die "cursor theme builder missing ($builder)"
  [[ -f $svg ]] || die "cursor SVGs missing ($svg)"
  command -v python3 >/dev/null || die "python3 required to build the cursor theme"
  log "cursor theme"
  mkdir -p "$WORK/cursor-theme"
  FIRSTBOOT_CURSOR_BUILD="$WORK/cursor-theme/First Boot Cursor" \
    FIRSTBOOT_CURSOR_BITMAPS="$WORK/cursor-theme/bitmaps" \
    python3 "$builder" --prefix "$ROOTFS/usr"
  if [[ -f $SEED_DIR/cursors/LICENSE ]]; then
    install -m 0644 "$SEED_DIR/cursors/LICENSE" "$dest/LICENSE"
  fi
  [[ -f $dest/cursors/left_ptr ]] || die "cursor theme build produced no left_ptr"
}

apt_get() {
  chroot_run apt-get \
    -o Dpkg::Options::=--force-confdef \
    -o Dpkg::Options::=--force-confold \
    "$@"
}

preseed() {
  chroot_run debconf-set-selections <<'EOF'
tzdata tzdata/Areas select Etc
tzdata tzdata/Zones/Etc select UTC
locales locales/locales_to_be_generated multiselect C.UTF-8 UTF-8, en_US.UTF-8 UTF-8
locales locales/default_environment_locale select C.UTF-8
keyboard-configuration keyboard-configuration/layoutcode string us
keyboard-configuration keyboard-configuration/modelcode string pc105
keyboard-configuration keyboard-configuration/variantcode string
console-setup console-setup/charmap47 select UTF-8
console-setup console-setup/codeset47 select Guess optimal character set
EOF
}

run_hooks() {
  mkdir -p "$ROOTFS/tmp/fbl-hooks"
  cp -a "$SEED_DIR/hooks/." "$ROOTFS/tmp/fbl-hooks/"
  chmod +x "$ROOTFS/tmp/fbl-hooks"/*.sh
  for hook in "$ROOTFS/tmp/fbl-hooks"/*.sh; do
    log "hook $(basename "$hook")"
    chroot_run bash "/tmp/fbl-hooks/$(basename "$hook")"
  done
}

write_buildinfo() {
  local git_commit=unknown
  if [[ -n ${FBL_GIT_COMMIT:-} ]]; then
    git_commit=$FBL_GIT_COMMIT
  elif command -v git >/dev/null && git -C "$REPO_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    git_commit=$(git -C "$REPO_DIR" rev-parse HEAD)
  fi
  cat > "$OUT/BUILDINFO" <<EOF
firstboot_version=${VERSION}
suite=${SUITE}
arch=${ARCH}
mirror=${MIRROR}
security_mirror=${SECURITY_MIRROR}
compression=${COMP}
built_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
git_commit=${git_commit}
builder=$(uname -n) $(uname -m)
EOF
}

export_kernel() {
  local k init
  k=$(ls -1 "$ROOTFS/boot"/vmlinuz-* 2>/dev/null | grep -v '\.efi\.signed$' | sort -V | tail -n1) \
    || die "no vmlinuz in $ROOTFS/boot"
  init=$(ls -1 "$ROOTFS/boot"/initrd.img-* 2>/dev/null | sort -V | tail -n1) \
    || die "no initrd in $ROOTFS/boot"
  cp -a "$k" "$OUT/vmlinuz"
  cp -a "$init" "$OUT/initrd"
  chmod 644 "$OUT/vmlinuz" "$OUT/initrd"
  log "kernel $(basename "$k")"
  log "initrd $(basename "$init")"
}

write_manifests() {
  chroot_run dpkg-query -W --showformat='${Package} ${Version}\n' \
    | sort > "$OUT/filesystem.manifest"
  du -sx --block-size=1 "$ROOTFS" | awk '{print $1}' > "$OUT/filesystem.size"
  cp -a "$ROOTFS/etc/os-release" "$OUT/os-release"
}

make_squashfs() {
  # Compression flags must come before -e: mksquashfs treats everything after
  # -e as exclude paths.
  local args=(
    "$ROOTFS" "$OUT/filesystem.squashfs"
    -noappend -no-recovery
    -wildcards
  )
  case $COMP in
    zstd) args+=(-comp zstd -Xcompression-level 15 -b 1M) ;;
    xz)   args+=(-comp xz -b 1M -Xdict-size 100%) ;;
    *)    die "unknown --comp $COMP (use zstd or xz)" ;;
  esac
  args+=(
    -e proc/*
    -e sys/*
    -e dev/*
    -e run/*
    -e tmp/*
    -e tmp/.*
    -e var/cache/apt/archives/*
    -e root/.bash_history
    -e boot/vmlinuz-*
    -e boot/initrd.img-*
    -e boot/*.old
  )
  rm -f "$OUT/filesystem.squashfs"
  mksquashfs "${args[@]}"
}

export_efi() {
  # Signed removable-media boot files for the ESP. Not installed in the live
  # root: shim/grub live on FBL-ESP, not in the squashfs.
  local tmp shim_src grub_src
  tmp=$(mktemp -d)
  mkdir -p "$OUT/efi"

  if [[ -e /usr/lib/shim/shimx64.efi.signed ]]; then
    shim_src=/usr/lib/shim
    grub_src=/usr/lib/grub/x86_64-efi-signed
  else
    log "download shim-signed grub-efi-amd64-signed for ESP"
    apt-get update -qq
    (cd "$tmp" && apt-get download shim-signed grub-efi-amd64-signed)
    dpkg-deb -x "$tmp"/shim-signed_*.deb "$tmp/shim"
    dpkg-deb -x "$tmp"/grub-efi-amd64-signed_*.deb "$tmp/grub"
    shim_src=$tmp/shim/usr/lib/shim
    grub_src=$tmp/grub/usr/lib/grub/x86_64-efi-signed
  fi

  [[ -e $shim_src/shimx64.efi.signed ]] || die "no shimx64.efi.signed"
  [[ -f $grub_src/gcdx64.efi.signed ]] || die "no gcdx64.efi.signed"
  [[ -f $shim_src/mmx64.efi ]] || die "no mmx64.efi"

  # Follow the alternatives symlink (shimx64.efi.signed → signed.latest).
  cp -L "$shim_src/shimx64.efi.signed" "$OUT/efi/BOOTX64.EFI"
  cp -L "$shim_src/shimx64.efi.signed" "$OUT/efi/shimx64.efi"
  cp -a "$shim_src/mmx64.efi" "$OUT/efi/mmx64.efi"
  # gcdx64 searches disks for /boot/grub/grub.cfg (live / removable).
  cp -a "$grub_src/gcdx64.efi.signed" "$OUT/efi/grubx64.efi"
  chmod 644 "$OUT/efi"/*
  rm -rf "$tmp"
  log "efi $(ls -1 "$OUT/efi" | tr '\n' ' ')"
  if command -v sbverify >/dev/null; then
    bash "$SEED_DIR/check-secureboot.sh" --seed "$OUT"
  else
    log "skip signature check (no sbverify)"
  fi
}

checksums() {
  (
    cd "$OUT"
    sha256sum filesystem.squashfs filesystem.manifest filesystem.size \
      vmlinuz initrd os-release BUILDINFO > SHA256SUMS
    if [[ -d efi ]]; then
      sha256sum efi/* >> SHA256SUMS
    fi
  )
}

chown_out() {
  if [[ -n ${HOST_UID:-} ]]; then
    chown -R "${HOST_UID}:${HOST_GID:-$HOST_UID}" "$OUT"
  fi
}

need_root
command -v debootstrap >/dev/null || die "debootstrap not installed"
command -v mksquashfs >/dev/null || die "squashfs-tools not installed"

if [[ $CLEAN -eq 1 ]]; then
  log "clean $WORK"
  unmount_rootfs
  rm -rf "$WORK"
  if [[ $OUT != "$WORK" ]]; then
    rm -rf "$OUT"
  fi
fi

mkdir -p "$WORK" "$OUT"

if [[ $AUDIT_ONLY -eq 1 ]]; then
  if [[ -d $ROOTFS && -f $ROOTFS/var/lib/dpkg/status ]]; then
    exec bash "$SEED_DIR/audit.sh" "$ROOTFS"
  fi
  [[ -f $OUT/filesystem.manifest ]] || die "nothing to audit"
  exec bash "$SEED_DIR/audit.sh" "$OUT/filesystem.manifest"
fi

if [[ $SQUASHFS_ONLY -eq 1 ]]; then
  [[ -d $ROOTFS ]] || die "no rootfs at $ROOTFS"
  log "squashfs only"
  make_squashfs
  checksums
  chown_out
  log "wrote $OUT/filesystem.squashfs"
  exit 0
fi

if [[ $SKIP_DEBOOTSTRAP -eq 0 ]]; then
  if [[ -e $ROOTFS/usr/bin/apt-get ]]; then
    die "rootfs already exists at $ROOTFS (use --skip-debootstrap or --clean)"
  fi
  log "debootstrap $SUITE $ARCH minbase → $ROOTFS"
  debootstrap \
    --arch="$ARCH" \
    --variant=minbase \
    --components=main,restricted,universe,multiverse \
    "$SUITE" "$ROOTFS" "$MIRROR"
  chown root:root "$ROOTFS"
else
  [[ -e $ROOTFS/usr/bin/apt-get ]] || die "no rootfs at $ROOTFS"
  log "reusing $ROOTFS"
fi

if [[ -f $ROOTFS/etc/resolv.conf || -L $ROOTFS/etc/resolv.conf ]]; then
  rm -f "$ROOTFS/etc/resolv.conf"
fi
if [[ -r /etc/resolv.conf ]]; then
  cp -a /etc/resolv.conf "$ROOTFS/etc/resolv.conf"
else
  printf 'nameserver 1.1.1.1\nnameserver 8.8.8.8\n' > "$ROOTFS/etc/resolv.conf"
fi

copy_apt_early
write_sources
write_forbid_pins
write_policy_rcd

# initctl diversion: some maintainer scripts still talk to upstart
if [[ ! -e $ROOTFS/sbin/initctl.distrib ]]; then
  chroot_run dpkg-divert --local --rename --add /sbin/initctl
  ln -sfn /bin/true "$ROOTFS/sbin/initctl"
fi

mount_rootfs
preseed

log "apt update + upgrade"
apt_get update
apt_get -y dist-upgrade

mapfile -t pkgs < <(list_pkgs "$SEED_DIR/packages/keep.list")
log "install ${#pkgs[@]} packages (no recommends)"
apt_get -y install --no-install-recommends "${pkgs[@]}"

log "overlay"
copy_overlay
install_chooser
install_cursors
run_hooks

# drop chroot-only guards before the image is frozen
rm -f "$ROOTFS/usr/sbin/policy-rc.d"
if [[ -L $ROOTFS/sbin/initctl && $(readlink "$ROOTFS/sbin/initctl") == /bin/true ]]; then
  rm -f "$ROOTFS/sbin/initctl"
  chroot_run dpkg-divert --rename --remove /sbin/initctl || true
fi

write_manifests
unmount_rootfs

log "audit"
bash "$SEED_DIR/audit.sh" "$OUT/filesystem.manifest"

export_kernel
export_efi
write_buildinfo
make_squashfs
checksums
chown_out

log "seed $VERSION ready in $OUT"
du -h "$OUT/filesystem.squashfs" "$OUT/vmlinuz" "$OUT/initrd"
