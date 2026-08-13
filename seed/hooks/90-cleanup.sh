#!/usr/bin/env bash
# Drop build leftovers. machine-id must be empty so each boot gets its own.
set -euo pipefail

apt-get clean
rm -rf /var/lib/apt/lists/*
rm -f /var/cache/apt/pkgcache.bin /var/cache/apt/srcpkgcache.bin

rm -rf /tmp/* /var/tmp/* /root/.bash_history /root/.cache
find /var/log -type f -exec truncate -s 0 {} +

rm -f /etc/ssh/ssh_host_* 2>/dev/null || true

: > /etc/machine-id
rm -f /var/lib/dbus/machine-id
ln -sf /etc/machine-id /var/lib/dbus/machine-id

rm -rf /tmp/fbl-hooks
