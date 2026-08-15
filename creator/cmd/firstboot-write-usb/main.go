package main

import (
	"flag"
	"fmt"
	"os"

	"github.com/Leon2332/First-Boot-Linux/creator/internal/writeusb"
)

func main() {
	image := flag.String("image", "", "raw disk image to copy")
	device := flag.String("device", "", "whole-disk destination (for example /dev/sdb)")
	flag.Parse()
	if *image == "" || *device == "" {
		fmt.Fprintln(os.Stderr, "usage: firstboot-write-usb --image FILE --device /dev/sdX")
		os.Exit(2)
	}
	err := writeusb.Write(*image, *device, func(got, total int64) {
		if total > 0 {
			fmt.Fprintf(os.Stderr, "\rwriting %d%%", got*100/total)
		}
	})
	fmt.Fprintln(os.Stderr)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
