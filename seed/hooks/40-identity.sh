#!/usr/bin/env bash
# First Boot identity. Ubuntu remains ID_LIKE so apt still works.
set -euo pipefail

version=$(tr -d '[:space:]' < /etc/firstboot/version)
suite=$(tr -d '[:space:]' < /etc/firstboot/suite)

rm -f /etc/os-release
cat > /etc/os-release <<EOF
PRETTY_NAME="First Boot Linux ${version}"
NAME="First Boot Linux"
VERSION_ID="${version}"
VERSION="${version}"
VERSION_CODENAME=seed
ID=firstboot
ID_LIKE="ubuntu debian"
HOME_URL="https://leon2332.github.io/First-Boot-Linux/"
SUPPORT_URL="https://github.com/Leon2332/First-Boot-Linux"
BUG_REPORT_URL="https://github.com/Leon2332/First-Boot-Linux/issues"
UBUNTU_CODENAME=${suite}
EOF

cat > /etc/firstboot-release <<EOF
FIRSTBOOT_VERSION=${version}
FIRSTBOOT_SUITE=${suite}
EOF
