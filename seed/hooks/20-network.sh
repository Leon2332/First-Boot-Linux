#!/usr/bin/env bash
# NetworkManager owns the live stack. systemd-networkd stays off.
set -euo pipefail

# netplan 1.x refuses world-readable YAML
if [[ -f /etc/netplan/00-network-manager.yaml ]]; then
  chmod 600 /etc/netplan/00-network-manager.yaml
fi

systemctl enable NetworkManager.service
systemctl enable systemd-resolved.service
systemctl enable systemd-timesyncd.service
systemctl disable systemd-networkd.service 2>/dev/null || true
systemctl disable systemd-networkd.socket 2>/dev/null || true
systemctl disable systemd-networkd-wait-online.service 2>/dev/null || true

# casper will recreate this; leave a resolved stub for a real boot.
ln -sfn ../run/systemd/resolve/stub-resolv.conf /etc/resolv.conf
