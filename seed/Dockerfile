FROM ubuntu:26.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      debootstrap \
      squashfs-tools \
      ca-certificates \
      wget \
      ubuntu-keyring \
      shim-signed \
      grub-efi-amd64-signed \
      sbsigntool \
      grub-common \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /src
ENTRYPOINT ["bash", "seed/build-seed.sh"]
