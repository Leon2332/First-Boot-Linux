#!/usr/bin/env bash
# Confirm seed EFI + kernel are Ubuntu's Secure Boot chain.
# Microsoft-signed shim, Canonical-signed gcdx64 / MokManager / vmlinuz.
set -euo pipefail

SEED_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_DIR=$(cd "$SEED_DIR/.." && pwd)
SEED=${FBL_SEED:-$REPO_DIR/build/seed}

usage() {
  cat <<EOF
Usage: $0 [--seed DIR]

  --seed DIR   seed artifacts (default: build/seed)
EOF
}

while [[ $# -gt 0 ]]; do
  case $1 in
    --seed) SEED=$(readlink -f "$2"); shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "error: unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

die() { printf 'error: %s\n' "$*" >&2; exit 1; }

command -v sbverify >/dev/null || die "sbverify not installed (apt install sbsigntool)"

need() { [[ -f $1 ]] || die "missing $1 (build the seed first)"; }

need "$SEED/efi/BOOTX64.EFI"
need "$SEED/efi/shimx64.efi"
need "$SEED/efi/grubx64.efi"
need "$SEED/efi/mmx64.efi"
need "$SEED/vmlinuz"

sb_list() {
  # shim's PE layout prints a "gaps between PE/COFF sections" warning.
  sbverify --list "$1" 2>/dev/null || true
}

require_issuer() {
  local file=$1 needle=$2
  local out
  out=$(sb_list "$file")
  grep -Fq "signature 1" <<<"$out" || die "$file: no PE/COFF signature"
  grep -Fq "$needle" <<<"$out" || die "$file: expected issuer containing: $needle"
  printf 'ok  %s  (%s)\n' "${file#"$SEED/"}" "$needle"
}

require_issuer "$SEED/efi/BOOTX64.EFI" "Microsoft Corporation UEFI CA 2011"
require_issuer "$SEED/efi/shimx64.efi" "Microsoft Corporation UEFI CA 2011"
require_issuer "$SEED/efi/grubx64.efi" "Canonical Ltd. Master Certificate Authority"
require_issuer "$SEED/efi/mmx64.efi" "Canonical Ltd."
require_issuer "$SEED/vmlinuz" "Canonical Ltd. Master Certificate Authority"

CA=/usr/share/grub/canonical-uefi-ca.crt
if [[ -f $CA ]]; then
  pem=$CA
  cleanup_pem=
  if ! openssl x509 -in "$CA" -noout >/dev/null 2>&1; then
    pem=$(mktemp)
    cleanup_pem=$pem
    openssl x509 -inform DER -in "$CA" -out "$pem"
  fi
  for f in "$SEED/efi/grubx64.efi" "$SEED/efi/mmx64.efi" "$SEED/vmlinuz"; do
    if sbverify --cert "$pem" "$f" >/dev/null 2>&1; then
      printf 'ok  %s  (Canonical UEFI CA)\n' "${f#"$SEED/"}"
    else
      [[ -n $cleanup_pem ]] && rm -f "$cleanup_pem"
      die "$f: sbverify against Canonical UEFI CA failed"
    fi
  done
  [[ -n $cleanup_pem ]] && rm -f "$cleanup_pem"
else
  printf 'skip cryptographic Canonical check (no %s)\n' "$CA"
fi

printf 'secure boot artifacts ok\n'
