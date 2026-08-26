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
      python3 \
      python3-gi \
      python3-gi-cairo \
      python3-cairo \
      python3-pil \
      gir1.2-rsvg-2.0 \
      libcairo2 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /src
ENTRYPOINT ["bash", "seed/build-seed.sh"]
