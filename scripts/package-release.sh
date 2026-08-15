#!/usr/bin/env bash
# Assemble GitHub Release assets into build/release/. Does not build the seed.
set -euo pipefail

REPO_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
SEED=${FBL_SEED:-$REPO_DIR/build/seed}
OUT=${FBL_RELEASE:-$REPO_DIR/build/release}
VERSION=$(tr -d '[:space:]' < "$REPO_DIR/seed/VERSION")

SEED_FILES=(
  filesystem.squashfs
  filesystem.size
  filesystem.manifest
  vmlinuz
  initrd
  os-release
  BUILDINFO
  SHA256SUMS
)

log() { printf '==> %s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

usage() {
  cat <<EOF
Usage: $(basename "$0") [--seed DIR] [--out DIR]

Pack firstboot-seed-\$VERSION.tar and firstboot-creator-\$VERSION-linux-amd64.tar.gz
into build/release/ (gitignored). Upload those files plus SHA256SUMS as the
GitHub Release assets. Version comes from seed/VERSION.

Does not run the seed builder. Rebuild the squashfs first when VERSION changes.
EOF
}

while [[ $# -gt 0 ]]; do
  case $1 in
    --seed)
      SEED=$2
      shift 2
      ;;
    --out)
      OUT=$2
      shift 2
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    *)
      die "unknown argument: $1"
      ;;
  esac
done

[[ -n $VERSION ]] || die "seed/VERSION is empty"
command -v sha256sum >/dev/null || die "sha256sum not found"
command -v tar >/dev/null || die "tar not found"
command -v make >/dev/null || die "make not found"

[[ -d $SEED ]] || die "seed not found at $SEED (build it with ./seed/build-in-docker.sh)"
for f in "${SEED_FILES[@]}"; do
  [[ -e $SEED/$f ]] || die "seed missing $f"
done
[[ -d $SEED/efi ]] || die "seed missing efi/"

seed_ver=$(awk -F= '/^VERSION_ID=/{gsub(/"/,"",$2); print $2}' "$SEED/os-release")
[[ $seed_ver == "$VERSION" ]] || die \
  "seed os-release is $seed_ver, seed/VERSION is $VERSION — rebuild the squashfs"

log "creator linux-amd64"
make -C "$REPO_DIR/creator" all
[[ -x $REPO_DIR/creator/bin/firstboot-creator ]] || die "creator binary missing"
[[ -x $REPO_DIR/creator/bin/firstboot-write-usb ]] || die "write-usb binary missing"

rm -rf "$OUT"
mkdir -p "$OUT"

seed_tar=firstboot-seed-$VERSION.tar
creator_tar=firstboot-creator-$VERSION-linux-amd64.tar.gz

log "pack $seed_tar"
tar -C "$SEED" -cf "$OUT/$seed_tar" \
  "${SEED_FILES[@]}" \
  efi

log "pack $creator_tar"
tar -C "$REPO_DIR/creator/bin" -czf "$OUT/$creator_tar" \
  firstboot-creator \
  firstboot-write-usb

log "checksums"
(
  cd "$OUT"
  sha256sum "$seed_tar" "$creator_tar" > SHA256SUMS
)

log "release assets in $OUT"
ls -lh "$OUT"
cat "$OUT/SHA256SUMS"
