#!/usr/bin/env bash
# Confirm keep.list names exist on this host's Ubuntu archive (no root).
set -euo pipefail

SEED_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

if ! command -v apt-cache >/dev/null; then
  echo "error: apt-cache not found (run on Ubuntu or skip this check)" >&2
  exit 2
fi

fail=0
while read -r pkg; do
  ver=$(apt-cache policy "$pkg" 2>/dev/null | awk '/Candidate:/ {print $2; exit}')
  if [[ -z $ver || $ver == '(none)' ]]; then
    echo "MISSING  $pkg"
    fail=1
  else
    echo "ok       $pkg  $ver"
  fi
done < <(grep -vE '^[[:space:]]*(#|$)' "$SEED_DIR/packages/keep.list" | awk '{print $1}')

exit "$fail"
