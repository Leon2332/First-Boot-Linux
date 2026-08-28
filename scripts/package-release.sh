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

Pack firstboot-seed-\$VERSION.tar, firstboot-creator-\$VERSION-linux-amd64.tar.gz,
and firstboot-creator-\$VERSION-x86_64.AppImage into build/release/ (gitignored).
Upload those files plus SHA256SUMS and README.md as the GitHub Release assets.
Version comes from seed/VERSION.

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

readme_src=$REPO_DIR/scripts/release-README.md
[[ -f $readme_src ]] || die "missing $readme_src"

rm -rf "$OUT"
mkdir -p "$OUT"

seed_tar=firstboot-seed-$VERSION.tar
creator_tar=firstboot-creator-$VERSION-linux-amd64.tar.gz

log "README.md"
sed "s/@VERSION@/$VERSION/g" "$readme_src" > "$OUT/README.md"

log "pack $seed_tar"
tar -C "$SEED" -cf "$OUT/$seed_tar" \
  "${SEED_FILES[@]}" \
  efi

stage=$(mktemp -d)
trap 'rm -rf "$stage"' EXIT
mkdir -p "$stage/boot" "$stage/wallpapers"
cp -a "$REPO_DIR/creator/bin/firstboot-creator" "$stage/"
cp -a "$REPO_DIR/creator/bin/firstboot-write-usb" "$stage/"
cp -a "$REPO_DIR/schemas/official-catalog.json" "$stage/"
cp -a "$REPO_DIR/image/grub.cfg" "$stage/boot/"
cp -a "$REPO_DIR/image/efi-grub.cfg" "$stage/boot/"
cp -a "$REPO_DIR/docs/assets/Wallpaper/felix-mittermeier-L4-16dmZ-1c-unsplash.jpg" \
  "$stage/wallpapers/dark.jpg"
cp -a "$REPO_DIR/docs/assets/Wallpaper/sarah-barr-zYPCi2V6Ig4-unsplash.jpg" \
  "$stage/wallpapers/light.jpg"
cp -a "$OUT/README.md" "$stage/"

log "pack $creator_tar"
tar -C "$stage" -czf "$OUT/$creator_tar" \
  firstboot-creator \
  firstboot-write-usb \
  official-catalog.json \
  boot \
  wallpapers \
  README.md

creator_appimage=firstboot-creator-$VERSION-x86_64.AppImage
log "AppImage $creator_appimage"
bash "$REPO_DIR/scripts/package-appimage.sh" --out "$OUT/$creator_appimage"

log "checksums"
(
  cd "$OUT"
  sha256sum "$seed_tar" "$creator_tar" "$creator_appimage" > SHA256SUMS
)

log "release assets in $OUT"
ls -lh "$OUT"
cat "$OUT/SHA256SUMS"
