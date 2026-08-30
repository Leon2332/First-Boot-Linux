#!/usr/bin/env bash
# Build examples/custom/pop-os-fbl.zip from the Pop!_OS pack sources.
set -euo pipefail
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
SRC=$HERE/pop-os
OUT=${1:-$HERE/pop-os-fbl.zip}
LOGO=$HERE/../../docs/assets/distros/pop-os.png
[[ -f $SRC/manifest.json ]] || { echo "missing $SRC/manifest.json" >&2; exit 1; }
[[ -f $SRC/driver.py ]] || { echo "missing $SRC/driver.py" >&2; exit 1; }
[[ -f $LOGO ]] || { echo "missing $LOGO" >&2; exit 1; }
cp -a "$LOGO" "$SRC/logo.png"
rm -f "$OUT"
rm -f "$OUT"
(cd "$SRC" && zip -q -9 "$OUT" manifest.json driver.py logo.png)
if compgen -G "$SRC/locale/*.po" >/dev/null; then
  (cd "$SRC" && zip -q -9 "$OUT" locale/*.po)
fi
echo "$OUT"
