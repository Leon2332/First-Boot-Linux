#!/usr/bin/env bash
# Write build/fbl-live.img — GPT: FBL-ESP + FBL-SYS + FBL-DATA.
# Requires root. Prefer this script on a workstation (it re-execs in Docker).
set -euo pipefail

IMAGE_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_DIR=$(cd "$IMAGE_DIR/.." && pwd)

SEED=${FBL_SEED:-$REPO_DIR/build/seed}
OUT=${FBL_LIVE_IMG:-$REPO_DIR/build/fbl-live.img}
PAYLOAD=${FBL_PAYLOAD:-$IMAGE_DIR/dummy-payload}
SIZE=${FBL_IMG_SIZE:-4G}
ESP_MIB=${FBL_ESP_MIB:-512}
SYS_MIB=${FBL_SYS_MIB:-2048}
WRITER_IMAGE=${FBL_WRITER_IMAGE:-firstboot-image-writer:26.04}

CLEAN=0

usage() {
  cat <<EOF
Usage: $0 [options]

  --seed DIR       seed artifacts (default: build/seed)
  --out FILE       raw disk image (default: build/fbl-live.img)
  --payload DIR    payload tree to copy onto FBL-DATA (default: image/dummy-payload)
  --size SIZE      image size, truncate(1) syntax (default: 4G)
  --esp-mib N      FBL-ESP size in MiB (default: 512)
  --sys-mib N      FBL-SYS size in MiB (default: 2048)
  --clean          delete the output image first
EOF
}

while [[ $# -gt 0 ]]; do
  case $1 in
    --seed) SEED=$(readlink -f "$2"); shift 2 ;;
    --out) OUT=$(readlink -f "$2"); shift 2 ;;
    --payload) PAYLOAD=$(readlink -f "$2"); shift 2 ;;
    --size) SIZE=$2; shift 2 ;;
    --esp-mib) ESP_MIB=$2; shift 2 ;;
    --sys-mib) SYS_MIB=$2; shift 2 ;;
    --clean) CLEAN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "error: unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

log() { printf '==> %s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

path_in_repo() {
  case $1 in
    "$REPO_DIR"|"$REPO_DIR"/*) return 0 ;;
    *) return 1 ;;
  esac
}

to_src() {
  printf '/src%s\n' "${1#"$REPO_DIR"}"
}

if [[ $(id -u) -ne 0 ]]; then
  command -v docker >/dev/null || die "run as root, or install docker"
  SEED=$(readlink -f "$SEED")
  OUT=$(readlink -f "$OUT")
  PAYLOAD=$(readlink -f "$PAYLOAD")
  path_in_repo "$SEED" || die "docker writer --seed must be under the repo ($REPO_DIR)"
  path_in_repo "$OUT" || die "docker writer --out must be under the repo ($REPO_DIR)"
  path_in_repo "$PAYLOAD" || die "docker writer --payload must be under the repo ($REPO_DIR)"
  log "writer image $WRITER_IMAGE"
  docker build -t "$WRITER_IMAGE" -f "$IMAGE_DIR/Dockerfile" "$IMAGE_DIR"
  mkdir -p "$(dirname "$OUT")"
  docker_args=(
    --seed "$(to_src "$SEED")"
    --out "$(to_src "$OUT")"
    --payload "$(to_src "$PAYLOAD")"
    --size "$SIZE"
    --esp-mib "$ESP_MIB"
    --sys-mib "$SYS_MIB"
  )
  [[ $CLEAN -eq 1 ]] && docker_args+=(--clean)
  exec docker run --rm --privileged \
    -e HOST_UID="$(id -u)" \
    -e HOST_GID="$(id -g)" \
    -v "$REPO_DIR:/src" \
    -w /src \
    "$WRITER_IMAGE" \
    "${docker_args[@]}"
fi

need() { command -v "$1" >/dev/null || die "$1 not installed"; }
need sgdisk
need mkfs.vfat
need mkfs.ext4
need losetup

# Snap Docker exposes host loop-control but only some /dev/loopN nodes.
# losetup --find then picks e.g. loop85, which is missing, and the setup fails.
ensure_loop_nodes() {
  local n
  [[ -e /dev/loop-control ]] || die "/dev/loop-control missing (need privileged Docker)"
  for n in $(seq 0 127); do
    if [[ ! -b /dev/loop$n ]]; then
      mknod /dev/loop$n b 7 "$n" 2>/dev/null || true
    fi
  done
}

detach_image_loops() {
  local img=$1 line dev
  # Kernel may show the bind-mount path as /src/build/... or /build/...
  while read -r line; do
    dev=${line%%:*}
    [[ -n $dev ]] || continue
    log "detach leftover $dev"
    umount "$dev" 2>/dev/null || true
    losetup -d "$dev" 2>/dev/null || true
  done < <(losetup -a | grep -F "$img" || true)
}

ensure_loop_nodes
detach_image_loops "$OUT"
detach_image_loops "fbl-live.img"

[[ -f $SEED/filesystem.squashfs ]] || die "no squashfs at $SEED/filesystem.squashfs (build the seed first)"
[[ -f $SEED/vmlinuz ]] || die "no vmlinuz in $SEED"
[[ -f $SEED/initrd ]] || die "no initrd in $SEED"
[[ -d $PAYLOAD ]] || die "no payload at $PAYLOAD"

casper_need=$((32 * 1024 * 1024))
for f in filesystem.squashfs vmlinuz initrd; do
  casper_need=$((casper_need + $(stat -c %s "$SEED/$f")))
done
casper_cap=$((SYS_MIB * 1024 * 1024))
if (( casper_need >= casper_cap )); then
  die "casper files need ${casper_need} bytes; FBL-SYS is ${SYS_MIB}MiB"
fi

VERSION=unknown
if [[ -f $SEED/os-release ]]; then
  VERSION=$(awk -F= '/^VERSION_ID=/{gsub(/"/,"",$2); print $2}' "$SEED/os-release")
elif [[ -f $REPO_DIR/seed/VERSION ]]; then
  VERSION=$(tr -d '[:space:]' < "$REPO_DIR/seed/VERSION")
fi

resolve_efi() {
  if [[ -f $SEED/efi/BOOTX64.EFI && -f $SEED/efi/grubx64.efi ]]; then
    EFI_BOOTX64=$SEED/efi/BOOTX64.EFI
    EFI_GRUB=$SEED/efi/grubx64.efi
    EFI_SHIM=$SEED/efi/BOOTX64.EFI
    [[ -f $SEED/efi/shimx64.efi ]] && EFI_SHIM=$SEED/efi/shimx64.efi
    EFI_MOK=$SEED/efi/mmx64.efi
    log "efi from $SEED/efi"
    return 0
  fi
  if [[ -e /usr/lib/shim/shimx64.efi.signed ]]; then
    EFI_BOOTX64=/usr/lib/shim/shimx64.efi.signed
    EFI_SHIM=/usr/lib/shim/shimx64.efi.signed
    EFI_MOK=/usr/lib/shim/mmx64.efi
    EFI_GRUB=/usr/lib/grub/x86_64-efi-signed/gcdx64.efi.signed
    [[ -f $EFI_GRUB ]] || die "no gcdx64.efi.signed (install grub-efi-amd64-signed)"
    log "efi from host shim-signed / grub-efi-amd64-signed"
    return 0
  fi
  die "no EFI binaries (rebuild the seed, or install shim-signed and grub-efi-amd64-signed)"
}

sector_field() {
  # sgdisk -i N: "First sector: 2048 (at 1024.0 KiB)"
  LC_ALL=C sgdisk -i "$1" "$OUT" | awk -F: -v key="$2" '
    $1 ~ key { gsub(/^[ \t]+/, "", $2); split($2, a, / /); print a[1]; exit }
  '
}

attach_part() {
  local part=$1 start last size loop
  start=$(sector_field "$part" "First sector")
  last=$(sector_field "$part" "Last sector")
  [[ -n $start && -n $last ]] || die "could not read GPT partition $part"
  size=$((last - start + 1))
  loop=$(losetup --find --show --offset $((start * 512)) --sizelimit $((size * 512)) "$OUT")
  LOOPS+=("$loop")
  printf '%s\n' "$loop"
}

MNT=
LOOPS=()
cleanup() {
  if [[ -n $MNT ]]; then
    for m in esp sys data; do
      if [[ -d $MNT/$m ]] && mountpoint -q "$MNT/$m" 2>/dev/null; then
        umount "$MNT/$m" || umount -l "$MNT/$m" || true
      fi
    done
    rm -rf "$MNT"
  fi
  local l
  for l in "${LOOPS[@]+"${LOOPS[@]}"}"; do
    losetup -d "$l" 2>/dev/null || true
  done
}
trap cleanup EXIT

resolve_efi

if [[ $CLEAN -eq 1 && -e $OUT ]]; then
  log "remove $OUT"
  rm -f "$OUT"
fi

mkdir -p "$(dirname "$OUT")"
log "image $OUT ($SIZE, ESP ${ESP_MIB}MiB, SYS ${SYS_MIB}MiB)"
truncate -s "$SIZE" "$OUT"

sgdisk --zap-all "$OUT" >/dev/null
sgdisk \
  --new=1:1M:+"${ESP_MIB}"M --typecode=1:EF00 --change-name=1:FBL-ESP \
  --new=2:0:+"${SYS_MIB}"M --typecode=2:8300 --change-name=2:FBL-SYS \
  --new=3:0:0 --typecode=3:8300 --change-name=3:FBL-DATA \
  "$OUT" >/dev/null

log "format partitions"
LOOP_ESP=$(attach_part 1)
LOOP_SYS=$(attach_part 2)
LOOP_DATA=$(attach_part 3)
[[ -b $LOOP_ESP && -b $LOOP_SYS && -b $LOOP_DATA ]] \
  || die "loop devices missing ($LOOP_ESP $LOOP_SYS $LOOP_DATA)"

mkfs.vfat -F 32 -n FBL-ESP "$LOOP_ESP" >/dev/null
mkfs.ext4 -F -q -L FBL-SYS -m 0 "$LOOP_SYS"
mkfs.ext4 -F -q -L FBL-DATA -m 0 "$LOOP_DATA"

MNT=$(mktemp -d)
mkdir -p "$MNT"/{esp,sys,data}
mount "$LOOP_ESP" "$MNT/esp"
mount "$LOOP_SYS" "$MNT/sys"
mount "$LOOP_DATA" "$MNT/data"

log "ESP (shim + gcdx64)"
install -d -m 0755 \
  "$MNT/esp/EFI/BOOT" \
  "$MNT/esp/EFI/firstboot" \
  "$MNT/esp/EFI/ubuntu"
install -m 0644 "$EFI_BOOTX64" "$MNT/esp/EFI/BOOT/BOOTX64.EFI"
install -m 0644 "$EFI_GRUB" "$MNT/esp/EFI/BOOT/grubx64.efi"
if [[ -n ${EFI_MOK:-} && -f $EFI_MOK ]]; then
  install -m 0644 "$EFI_MOK" "$MNT/esp/EFI/BOOT/mmx64.efi"
fi
install -m 0644 "$IMAGE_DIR/efi-grub.cfg" "$MNT/esp/EFI/BOOT/grub.cfg"
install -m 0644 "$EFI_SHIM" "$MNT/esp/EFI/firstboot/shimx64.efi"
install -m 0644 "$EFI_GRUB" "$MNT/esp/EFI/firstboot/grubx64.efi"
install -m 0644 "$IMAGE_DIR/efi-grub.cfg" "$MNT/esp/EFI/firstboot/grub.cfg"
install -m 0644 "$IMAGE_DIR/efi-grub.cfg" "$MNT/esp/EFI/ubuntu/grub.cfg"

log "FBL-SYS (casper $VERSION)"
install -d -m 0755 \
  "$MNT/sys/.disk" \
  "$MNT/sys/casper" \
  "$MNT/sys/boot/grub"
printf 'First Boot Linux %s\n' "$VERSION" > "$MNT/sys/.disk/info"
printf 'firstboot\n' > "$MNT/sys/.disk/ubuntu_dist_channel"
install -m 0644 "$IMAGE_DIR/grub.cfg" "$MNT/sys/boot/grub/grub.cfg"
install -m 0644 "$SEED/vmlinuz" "$MNT/sys/casper/vmlinuz"
install -m 0644 "$SEED/initrd" "$MNT/sys/casper/initrd"
cp -a "$SEED/filesystem.squashfs" "$MNT/sys/casper/filesystem.squashfs"
if [[ -f $SEED/filesystem.size ]]; then
  install -m 0644 "$SEED/filesystem.size" "$MNT/sys/casper/filesystem.size"
fi
if [[ -f $SEED/filesystem.manifest ]]; then
  install -m 0644 "$SEED/filesystem.manifest" "$MNT/sys/casper/filesystem.manifest"
fi
: > "$MNT/sys/casper/filesystem.manifest-remove"
(
  cd "$MNT/sys"
  find . -type f -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS
  find . -type f ! -name md5sum.txt -print0 | sort -z | xargs -0 md5sum > md5sum.txt
)

log "FBL-DATA (dummy payload)"
if command -v rsync >/dev/null; then
  rsync -a --exclude '.git' "$PAYLOAD"/ "$MNT/data/"
else
  cp -a "$PAYLOAD"/. "$MNT/data/"
fi
install -d -m 0755 "$MNT/data/wallpapers" "$MNT/data/images"
wall_src=$REPO_DIR/docs/assets/Wallpaper
if [[ -d $wall_src ]]; then
  if [[ ! -f $MNT/data/wallpapers/dark.jpg && -f $wall_src/annie-spratt-nJGaLopCqJk-unsplash.jpg ]]; then
    install -m 0644 "$wall_src/annie-spratt-nJGaLopCqJk-unsplash.jpg" \
      "$MNT/data/wallpapers/dark.jpg"
  fi
  if [[ ! -f $MNT/data/wallpapers/light.jpg && -f $wall_src/ands-mahardika--MRPyzpWsh0-unsplash.jpg ]]; then
    install -m 0644 "$wall_src/ands-mahardika--MRPyzpWsh0-unsplash.jpg" \
      "$MNT/data/wallpapers/light.jpg"
  fi
fi
(
  cd "$MNT/data"
  {
    [[ -f retailer.conf ]] && sha256sum retailer.conf
    [[ -f catalog.json ]] && sha256sum catalog.json
    if [[ -d wallpapers ]]; then
      find wallpapers -type f -print0 | sort -z | xargs -0 -r sha256sum
    fi
    if [[ -d images ]]; then
      find images -type f -print0 | sort -z | xargs -0 -r sha256sum
    fi
  } > checksums.sha256
)

sync
umount "$MNT/esp" "$MNT/sys" "$MNT/data"
rmdir "$MNT"/{esp,sys,data}
rmdir "$MNT"
MNT=
for l in "${LOOPS[@]}"; do
  losetup -d "$l"
done
LOOPS=()

if [[ -n ${HOST_UID:-} ]]; then
  chown "${HOST_UID}:${HOST_GID:-$HOST_UID}" "$OUT"
fi

log "partitions"
LC_ALL=C sgdisk -p "$OUT"
log "wrote $OUT"
du -h "$OUT" | awk '{print}'
if command -v stat >/dev/null; then
  log "allocated $(stat -c %s "$OUT" | awk '{printf "%.1fG logical\n", $1/1024/1024/1024}') / $(stat -c %b "$OUT" | awk '{printf "%.1fG on disk\n", $1*512/1024/1024/1024}')"
fi
