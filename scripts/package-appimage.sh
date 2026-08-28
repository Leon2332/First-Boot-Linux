#!/usr/bin/env bash
# Wrap firstboot-creator as a type-2 AppImage. Does not include the seed.
set -euo pipefail

REPO_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
VERSION=$(tr -d '[:space:]' < "$REPO_DIR/seed/VERSION")
OUT=${FBL_APPIMAGE_OUT:-$REPO_DIR/build/release}
TOOLS=${FBL_APPIMAGE_TOOLS:-$REPO_DIR/build/tools}
RUNTIME_URL=${FBL_APPIMAGE_RUNTIME_URL:-https://github.com/AppImage/type2-runtime/releases/download/continuous/runtime-x86_64}

log() { printf '==> %s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

usage() {
  cat <<EOF
Usage: $(basename "$0") [--out DIR|FILE]

Build firstboot-creator-\$VERSION-x86_64.AppImage. The seed stays a separate
tarball — put seed/ next to the AppImage or set FIRSTBOOT_SEED.

Needs mksquashfs and a network fetch of the type-2 runtime (cached under
build/tools/). FUSE is not required to build.
EOF
}

while [[ $# -gt 0 ]]; do
  case $1 in
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
[[ $(uname -m) == x86_64 ]] || die "AppImage wrap is amd64 only"
command -v mksquashfs >/dev/null || die "mksquashfs not found (install squashfs-tools)"
command -v make >/dev/null || die "make not found"

fetch() {
  local url=$1 dest=$2
  if command -v curl >/dev/null; then
    curl -fL --retry 3 -o "$dest" "$url"
  elif command -v wget >/dev/null; then
    wget -O "$dest" "$url"
  else
    die "need curl or wget to fetch the AppImage runtime"
  fi
}

log "creator linux-amd64"
make -C "$REPO_DIR/creator" all
[[ -x $REPO_DIR/creator/bin/firstboot-creator ]] || die "creator binary missing"
[[ -x $REPO_DIR/creator/bin/firstboot-write-usb ]] || die "write-usb binary missing"

if [[ $OUT == *.AppImage ]]; then
  appimage=$OUT
  mkdir -p "$(dirname "$appimage")"
else
  mkdir -p "$OUT"
  appimage=$OUT/firstboot-creator-$VERSION-x86_64.AppImage
fi

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
appdir=$work/FirstBootUSBCreator.AppDir
share=$appdir/usr/share/firstboot

mkdir -p \
  "$appdir/usr/bin" \
  "$appdir/usr/share/applications" \
  "$appdir/usr/share/icons/hicolor/256x256/apps" \
  "$share/boot" \
  "$share/wallpapers" \
  "$share/logos"

cp -a "$REPO_DIR/creator/bin/firstboot-creator" "$appdir/usr/bin/"
cp -a "$REPO_DIR/creator/bin/firstboot-write-usb" "$appdir/usr/bin/"
cp -a "$REPO_DIR/schemas/official-catalog.json" "$share/"
cp -a "$REPO_DIR/po/languages.json" "$share/"
cp -a "$REPO_DIR/po/keyboards.json" "$share/"
mkdir -p "$share/locale"
for po in "$REPO_DIR/po/"*.po; do
  [[ -f $po ]] || continue
  cp -a "$po" "$share/locale/"
done
cp -a "$REPO_DIR/image/grub.cfg" "$share/boot/"
cp -a "$REPO_DIR/image/efi-grub.cfg" "$share/boot/"
cp -a "$REPO_DIR/docs/assets/Wallpaper/felix-mittermeier-L4-16dmZ-1c-unsplash.jpg" \
  "$share/wallpapers/dark.jpg"
cp -a "$REPO_DIR/docs/assets/Wallpaper/sarah-barr-zYPCi2V6Ig4-unsplash.jpg" \
  "$share/wallpapers/light.jpg"
cp -a "$REPO_DIR/docs/assets/distros/"*.png "$share/logos/"
cp -a "$REPO_DIR/docs/Logo/First Boot Linux.png" "$share/icon.png"
cp -a "$REPO_DIR/docs/Logo/First Boot Linux.png" "$appdir/firstboot-creator.png"
cp -a "$REPO_DIR/docs/Logo/First Boot Linux.png" "$appdir/.DirIcon"
cp -a "$REPO_DIR/docs/Logo/First Boot Linux.png" \
  "$appdir/usr/share/icons/hicolor/256x256/apps/firstboot-creator.png"

cat > "$appdir/firstboot-creator.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=First Boot USB Creator
Comment=Write a branded First Boot USB
Exec=firstboot-creator
Icon=firstboot-creator
Categories=Utility;System;
Terminal=false
X-AppImage-Version=$VERSION
EOF
cp -a "$appdir/firstboot-creator.desktop" "$appdir/usr/share/applications/"

cat > "$appdir/AppRun" <<'EOF'
#!/bin/sh
HERE=$(dirname "$(readlink -f "$0")")
export APPDIR="${APPDIR:-$HERE}"
export PATH="$HERE/usr/bin:${PATH:-}"

if [ "$(id -u)" = 0 ]; then
  echo "Do not run the First Boot USB Creator as root." >&2
  echo "The write step will ask for permission." >&2
  exit 1
fi

exec "$HERE/usr/bin/firstboot-creator" "$@"
EOF
chmod 0755 "$appdir/AppRun"

mkdir -p "$TOOLS"
runtime=$TOOLS/runtime-x86_64
if [[ ! -s $runtime ]]; then
  log "fetch type-2 runtime"
  fetch "$RUNTIME_URL" "$runtime.partial"
  chmod 0755 "$runtime.partial"
  mv "$runtime.partial" "$runtime"
fi
[[ -s $runtime ]] || die "AppImage runtime missing at $runtime"

squash=$work/appdir.squashfs
log "squashfs"
mksquashfs "$appdir" "$squash" -root-owned -noappend -all-root -comp gzip >/dev/null

tmp=$appimage.partial
rm -f "$tmp"
cat "$runtime" "$squash" > "$tmp"
chmod 0755 "$tmp"
mv "$tmp" "$appimage"

log "AppImage $appimage"
ls -lh "$appimage"
