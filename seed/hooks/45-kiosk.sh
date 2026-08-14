#!/usr/bin/env bash
# Live user + tty1 autologin. Casper uses the same username; skip if it exists.
set -euo pipefail

if ! getent passwd firstboot >/dev/null; then
  useradd --create-home --shell /bin/bash --comment "First Boot" firstboot
fi

for g in audio video render input plugdev netdev sudo cdrom dip users; do
  if getent group "$g" >/dev/null; then
    usermod -aG "$g" firstboot
  fi
done

passwd -d firstboot >/dev/null

install -o firstboot -g firstboot -m 0644 /dev/null /home/firstboot/.hushlogin

chmod 440 /etc/sudoers.d/firstboot
systemctl enable getty@tty1.service
