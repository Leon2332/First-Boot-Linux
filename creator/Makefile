GO ?= $(HOME)/sdk/go/bin/go
ifeq ($(wildcard $(GO)),)
GO := go
endif

export PATH := $(dir $(GO)):$(PATH)
export CGO_ENABLED := 0

.PHONY: all test creator writer

all: creator writer

creator:
	$(GO) build -o bin/firstboot-creator ./cmd/firstboot-creator

writer:
	$(GO) build -o bin/firstboot-write-usb ./cmd/firstboot-write-usb

test:
	$(GO) test ./internal/...
