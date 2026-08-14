FROM ubuntu:26.04

ENV DEBIAN_FRONTEND=noninteractive

# Privileged writer: GPT + FAT/ext4 + signed shim/GRUB onto a raw disk image.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates \
      dosfstools \
      e2fsprogs \
      gdisk \
      mount \
      rsync \
      shim-signed \
      grub-efi-amd64-signed \
      udev \
      util-linux \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /src
ENTRYPOINT ["bash", "image/write-live.sh"]
