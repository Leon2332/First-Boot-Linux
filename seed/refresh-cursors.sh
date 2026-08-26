#!/usr/bin/env bash
# Copy SVG sources from the First Boot Cursor repo into seed/cursors/.
# Does not install a host cursor theme (do not run gsettings here).
set -euo pipefail

SEED_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_DIR=$(cd "$SEED_DIR/.." && pwd)
DEST="$SEED_DIR/cursors"
SRC=${FIRSTBOOT_CURSOR:-$(cd "$REPO_DIR/../First Boot Cursor" && pwd)}

[[ -f $SRC/src/svg/left_ptr.svg ]] || {
  echo "error: no First Boot Cursor sources at $SRC" >&2
  exit 1
}

mkdir -p "$DEST/configs" "$DEST/src"
cp -a "$SRC/LICENSE" "$DEST/LICENSE"
cp -a "$SRC/configs/x.build.toml" "$DEST/configs/x.build.toml"
rm -rf "$DEST/src/svg"
cp -a "$SRC/src/svg" "$DEST/src/svg"

echo "refreshed $DEST from $SRC"
if [[ "${1:-}" != "--no-mockup" ]]; then
  python3 "$DEST/export_mockup.py"
fi
