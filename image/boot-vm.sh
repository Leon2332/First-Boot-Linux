#!/usr/bin/env bash
# Boot build/fbl-live.img in a UEFI QEMU/KVM VM.
# Uses host qemu-system-x86_64 + OVMF when present; otherwise a Docker image.
set -euo pipefail

IMAGE_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_DIR=$(cd "$IMAGE_DIR/.." && pwd)

IMG=${FBL_LIVE_IMG:-$REPO_DIR/build/fbl-live.img}
MEM=${FBL_VM_MEM:-2G}
SMP=${FBL_VM_SMP:-2}
QEMU_IMAGE=${FBL_QEMU_IMAGE:-firstboot-qemu:26.04}
VARS=$REPO_DIR/build/OVMF_VARS.fd
SERIAL_LOG=$REPO_DIR/build/fbl-vm-serial.log

WRITE=0
SMOKE=0
DISPLAY_MODE=auto   # auto | gtk | none
SMOKE_TIMEOUT=${FBL_SMOKE_TIMEOUT:-180}

usage() {
  cat <<EOF
Usage: $0 [options]

  --img FILE       raw disk (default: build/fbl-live.img)
  --mem SIZE       RAM (default: 2G)
  --smp N          vCPUs (default: 2)
  --write          run image/write-live.sh first
  --display gtk|none
  --smoke          headless boot; succeed if serial shows a live session
  --smoke-timeout N   seconds for --smoke (default: 180)
EOF
}

while [[ $# -gt 0 ]]; do
  case $1 in
    --img) IMG=$(readlink -f "$2"); shift 2 ;;
    --mem) MEM=$2; shift 2 ;;
    --smp) SMP=$2; shift 2 ;;
    --write) WRITE=1; shift ;;
    --display) DISPLAY_MODE=$2; shift 2 ;;
    --smoke) SMOKE=1; DISPLAY_MODE=none; shift ;;
    --smoke-timeout) SMOKE_TIMEOUT=$2; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "error: unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

log() { printf '==> %s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

if [[ $WRITE -eq 1 ]]; then
  bash "$IMAGE_DIR/write-live.sh"
fi

[[ -f $IMG ]] || die "no image at $IMG (run image/write-live.sh, or pass --write)"

if [[ $DISPLAY_MODE == auto ]]; then
  if [[ -n ${DISPLAY:-} || -n ${WAYLAND_DISPLAY:-} ]]; then
    DISPLAY_MODE=gtk
  else
    DISPLAY_MODE=none
  fi
fi

find_ovmf() {
  local d
  for d in /usr/share/OVMF /usr/share/ovmf /usr/share/qemu; do
    if [[ -f $d/OVMF_CODE_4M.fd ]]; then
      OVMF_CODE=$d/OVMF_CODE_4M.fd
      OVMF_VARS_TEMPLATE=$d/OVMF_VARS_4M.fd
      return 0
    fi
    if [[ -f $d/OVMF_CODE.fd ]]; then
      OVMF_CODE=$d/OVMF_CODE.fd
      OVMF_VARS_TEMPLATE=$d/OVMF_VARS.fd
      return 0
    fi
  done
  return 1
}

qemu_args() {
  local code=$1 vars=$2
  QEMU_ARGS=(
    -enable-kvm
    -machine q35,smm=off
    -m "$MEM"
    -smp "$SMP"
    -drive if=pflash,format=raw,unit=0,readonly=on,file="$code"
    -drive if=pflash,format=raw,unit=1,file="$vars"
    -drive file="$IMG",format=raw,if=none,id=bootdisk
    -device virtio-blk-pci,drive=bootdisk,bootindex=0
    -device virtio-vga
    -netdev user,id=net0
    -device virtio-net-pci,netdev=net0
    -serial file:"$SERIAL_LOG"
  )
  case $DISPLAY_MODE in
    gtk) QEMU_ARGS+=(-display gtk) ;;
    none) QEMU_ARGS+=(-display none) ;;
    *) die "unknown --display $DISPLAY_MODE" ;;
  esac
}

prepare_vars() {
  local template=$1
  mkdir -p "$(dirname "$VARS")"
  if [[ ! -f $VARS || $WRITE -eq 1 ]]; then
    cp -a "$template" "$VARS"
    if [[ -n ${HOST_UID:-} ]]; then
      chown "${HOST_UID}:${HOST_GID:-$HOST_UID}" "$VARS" 2>/dev/null || true
    elif [[ $(id -u) -ne 0 ]]; then
      :
    fi
  fi
}

smoke_watch() {
  local deadline=$((SECONDS + SMOKE_TIMEOUT))
  local qemu_pid=$1
  log "smoke: waiting up to ${SMOKE_TIMEOUT}s (serial $SERIAL_LOG)"
  while (( SECONDS < deadline )); do
    if ! kill -0 "$qemu_pid" 2>/dev/null; then
      wait "$qemu_pid" || true
      echo "error: qemu exited before a live session appeared" >&2
      tail -n 40 "$SERIAL_LOG" >&2 || true
      return 1
    fi
    if grep -Eq 'Unable to find a medium containing a live file system' "$SERIAL_LOG" 2>/dev/null; then
      kill "$qemu_pid" 2>/dev/null || true
      wait "$qemu_pid" || true
      echo "error: casper did not find FBL-SYS" >&2
      tail -n 40 "$SERIAL_LOG" >&2 || true
      return 1
    fi
    if grep -Eq 'Reached target ([Gg]raphical|[Mm]ulti-[Uu]ser)|Welcome to First Boot|firstboot login|Started .+[Gg]etty|firstboot-session|Starting cage' "$SERIAL_LOG" 2>/dev/null; then
      log "smoke: live session reached"
      kill "$qemu_pid" 2>/dev/null || true
      wait "$qemu_pid" || true
      return 0
    fi
    sleep 2
  done
  kill "$qemu_pid" 2>/dev/null || true
  wait "$qemu_pid" || true
  echo "error: smoke timed out after ${SMOKE_TIMEOUT}s" >&2
  tail -n 60 "$SERIAL_LOG" >&2 || true
  return 1
}

run_host() {
  find_ovmf || return 1
  command -v qemu-system-x86_64 >/dev/null || return 1
  [[ -e /dev/kvm ]] || die "/dev/kvm missing"
  prepare_vars "$OVMF_VARS_TEMPLATE"
  qemu_args "$OVMF_CODE" "$VARS"
  log "qemu host  display=$DISPLAY_MODE  img=$IMG"
  : > "$SERIAL_LOG"
  if [[ $SMOKE -eq 1 ]]; then
    qemu-system-x86_64 "${QEMU_ARGS[@]}" &
    smoke_watch $!
    return
  fi
  exec qemu-system-x86_64 "${QEMU_ARGS[@]}"
}

run_docker() {
  command -v docker >/dev/null || die "qemu-system-x86_64/ovmf not installed, and docker is missing"
  [[ -e /dev/kvm ]] || die "/dev/kvm missing"
  log "qemu image $QEMU_IMAGE"
  docker build -t "$QEMU_IMAGE" -f "$IMAGE_DIR/Dockerfile.qemu" "$IMAGE_DIR"

  local code_c=/usr/share/OVMF/OVMF_CODE_4M.fd
  local vars_c=/src/build/OVMF_VARS.fd
  local img_c=/src/${IMG#"$REPO_DIR"/}
  local serial_c=/src/build/fbl-vm-serial.log

  # Seed VARS from the image on first run (container copies if missing).
  mkdir -p "$REPO_DIR/build"
  local docker_display=( -display none )
  local extra=( )
  if [[ $DISPLAY_MODE == gtk && -n ${DISPLAY:-} ]]; then
    docker_display=( -display gtk )
    extra+=(
      -e "DISPLAY=$DISPLAY"
      -v /tmp/.X11-unix:/tmp/.X11-unix
    )
    if [[ -n ${XAUTHORITY:-} && -f $XAUTHORITY ]]; then
      extra+=( -e "XAUTHORITY=$XAUTHORITY" -v "$XAUTHORITY:$XAUTHORITY" )
    fi
    if command -v xhost >/dev/null; then
      xhost +SI:localuser:root >/dev/null 2>&1 || xhost +local: >/dev/null 2>&1 || true
    fi
  fi

  local cmd=(
    qemu-system-x86_64
    -enable-kvm
    -machine q35,smm=off
    -m "$MEM"
    -smp "$SMP"
    -drive if=pflash,format=raw,unit=0,readonly=on,file="$code_c"
    -drive if=pflash,format=raw,unit=1,file="$vars_c"
    -drive file="$img_c",format=raw,if=none,id=bootdisk
    -device virtio-blk-pci,drive=bootdisk,bootindex=0
    -device virtio-vga
    -netdev user,id=net0
    -device virtio-net-pci,netdev=net0
    -serial file:"$serial_c"
    "${docker_display[@]}"
  )

  local run=(
    docker run --rm
    --device /dev/kvm
    -v "$REPO_DIR:/src"
    -w /src
    "${extra[@]}"
    "$QEMU_IMAGE"
    bash -c 'set -euo pipefail
      tmpl=/usr/share/OVMF/OVMF_VARS_4M.fd
      [[ -f $tmpl ]] || tmpl=/usr/share/OVMF/OVMF_VARS.fd
      if [[ ! -f /src/build/OVMF_VARS.fd ]]; then
        cp -a "$tmpl" /src/build/OVMF_VARS.fd
      fi
      exec "$@"'
    bash
    "${cmd[@]}"
  )

  log "qemu docker  display=$DISPLAY_MODE  img=$IMG"
  : > "$SERIAL_LOG"
  if [[ $SMOKE -eq 1 ]]; then
    "${run[@]}" &
    smoke_watch $!
    return
  fi
  exec "${run[@]}"
}

if command -v qemu-system-x86_64 >/dev/null && find_ovmf; then
  run_host
  exit
fi
log "host qemu/OVMF not installed — using Docker"
run_docker
