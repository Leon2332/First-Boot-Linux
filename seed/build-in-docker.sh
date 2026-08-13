#!/usr/bin/env bash
# Build the live seed in a privileged Ubuntu 26.04 container (no host sudo).
set -euo pipefail

SEED_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_DIR=$(cd "$SEED_DIR/.." && pwd)
IMAGE=${FBL_BUILD_IMAGE:-firstboot-seed-builder:26.04}

command -v docker >/dev/null || { echo "error: docker not found" >&2; exit 1; }

log() { printf '==> %s\n' "$*"; }

log "builder image $IMAGE"
docker build -t "$IMAGE" -f "$SEED_DIR/Dockerfile" "$SEED_DIR"

mkdir -p "$REPO_DIR/build/seed"

# Chroot lives on the container overlay (real root). Snap Docker maps bind-mount
# files to the host uid, which would make squashfs "/" owned by 1000.
log "build seed"
exec docker run --rm --privileged \
  -e DEBIAN_FRONTEND=noninteractive \
  -e HOST_UID="$(id -u)" \
  -e HOST_GID="$(id -g)" \
  -e FBL_SUITE="${FBL_SUITE:-}" \
  -e FBL_MIRROR="${FBL_MIRROR:-}" \
  -e FBL_SECURITY_MIRROR="${FBL_SECURITY_MIRROR:-}" \
  -e FBL_COMP="${FBL_COMP:-}" \
  -e FBL_GIT_COMMIT="$(git -C "$REPO_DIR" rev-parse HEAD 2>/dev/null || true)" \
  -e http_proxy="${http_proxy:-}" \
  -e https_proxy="${https_proxy:-}" \
  -e no_proxy="${no_proxy:-}" \
  -v "$REPO_DIR:/src" \
  -w /src \
  "$IMAGE" \
  --work /var/tmp/fbl-seed \
  --out /src/build/seed \
  "$@"
