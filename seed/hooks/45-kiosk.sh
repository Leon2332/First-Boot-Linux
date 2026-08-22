#!/usr/bin/env bash
# Live user + tty1 autologin. Casper uses the same username; skip if it exists.
set -euo pipefail

if ! getent passwd firstboot >/dev/null; then
  useradd --create-home --shell /bin/bash --comment "First Boot" firstboot
fi
mkdir -p /home/firstboot
chown firstboot:firstboot /home/firstboot
chmod 0755 /home/firstboot

for g in audio video render input plugdev netdev sudo cdrom dip users tty dialout; do
  if getent group "$g" >/dev/null; then
    usermod -aG "$g" firstboot
  fi
done

passwd -d firstboot >/dev/null

install -o firstboot -g firstboot -m 0644 /dev/null /home/firstboot/.hushlogin

install -d -m 700 -o firstboot -g firstboot /home/firstboot/.ssh
if [[ -f /usr/share/firstboot/ssh/authorized_keys ]]; then
  install -o firstboot -g firstboot -m 600 \
    /usr/share/firstboot/ssh/authorized_keys \
    /home/firstboot/.ssh/authorized_keys
fi

if command -v glib-compile-schemas >/dev/null; then
  glib-compile-schemas /usr/share/glib-2.0/schemas
fi

chmod 440 /etc/sudoers.d/firstboot
systemctl enable firstboot-kiosk.service
systemctl enable firstboot-ssh-keys.service
# Package postinst prefers ssh.socket. Always-on ssh.service is simpler
# for field debug (port 22 is open without a first connection).
systemctl disable ssh.socket 2>/dev/null || true
systemctl unmask ssh.service 2>/dev/null || true
systemctl enable ssh.service
systemctl mask getty@tty1.service
