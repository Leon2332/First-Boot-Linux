#!/usr/bin/env bash
# Audit a dpkg-query -W manifest (or a rootfs) against keep/forbid lists.
set -euo pipefail

SEED_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

usage() {
  cat <<EOF
Usage: $0 <manifest-or-rootfs>

  manifest   file from dpkg-query -W --showformat='\${Package} \${Version}\\n'
  rootfs     directory containing var/lib/dpkg/status
EOF
}

[[ ${1:-} ]] || { usage >&2; exit 2; }

list_pkgs() {
  grep -vE '^[[:space:]]*(#|$)' "$1" | awk '{print $1}'
}

installed_from_manifest() {
  awk '{print $1}' "$1"
}

installed_from_rootfs() {
  dpkg-query --root="$1" -W -f='${db:Status-Abbrev} ${Package}\n' \
    | awk '$1 ~ /^ii/ {print $2}'
}

target=$1
if [[ -d $target ]]; then
  mapfile -t installed < <(installed_from_rootfs "$target" | sort -u)
elif [[ -f $target ]]; then
  mapfile -t installed < <(installed_from_manifest "$target" | sort -u)
else
  echo "error: not a file or directory: $target" >&2
  exit 2
fi

declare -A have=()
for p in "${installed[@]}"; do
  have[$p]=1
done

fail=0

echo "== forbid (must be absent) =="
while read -r pkg; do
  if [[ -n ${have[$pkg]+x} ]]; then
    echo "FAIL  $pkg"
    fail=1
  else
    echo "ok    $pkg"
  fi
done < <(list_pkgs "$SEED_DIR/packages/forbid.list")

echo
echo "== keep (must be present) =="
while read -r pkg; do
  if [[ -z ${have[$pkg]+x} ]]; then
    echo "FAIL  $pkg"
    fail=1
  else
    echo "ok    $pkg"
  fi
done < <(list_pkgs "$SEED_DIR/packages/keep.list")

echo
if [[ $fail -ne 0 ]]; then
  echo "audit failed"
  exit 1
fi
echo "audit passed (${#installed[@]} packages)"
