#!/usr/bin/env bash
# Frozen image: no unattended apt, no motd news. Root stays locked.
set -euo pipefail

systemctl mask apt-daily.timer apt-daily.service \
  apt-daily-upgrade.timer apt-daily-upgrade.service \
  2>/dev/null || true

systemctl mask motd-news.timer motd-news.service 2>/dev/null || true

# Frozen live disk: do not re-read the squashfs on every boot, and do not
# prompt to "remove the installation medium" on reboot (this is a disk).
systemctl mask casper-md5check.service casper-md5check.timer 2>/dev/null || true
systemctl mask casper.service 2>/dev/null || true

passwd -l root >/dev/null
