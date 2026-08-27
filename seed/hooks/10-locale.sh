#!/usr/bin/env bash
# Timezone UTC, C.UTF-8 default, generate en_US.UTF-8.
set -euo pipefail

echo UTC > /etc/timezone
ln -sfn /usr/share/zoneinfo/UTC /etc/localtime

if [[ -f /usr/share/i18n/SUPPORTED ]]; then
  mkdir -p /etc/locale.gen.d
  printf 'C.UTF-8 UTF-8\nen_US.UTF-8 UTF-8\naf_ZA.UTF-8 UTF-8\n' > /etc/locale.gen
  locale-gen
fi

update-locale LANG=C.UTF-8 LC_ALL=C.UTF-8 2>/dev/null || true
