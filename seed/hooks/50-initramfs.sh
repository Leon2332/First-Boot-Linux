#!/usr/bin/env bash
# Rebuild initrd after overlay so casper.conf is what the live boot sees.
set -euo pipefail

update-initramfs -u
