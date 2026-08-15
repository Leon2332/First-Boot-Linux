package writeusb

import (
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/Leon2332/First-Boot-Linux/creator/internal/devices"
)

func Write(image, device string, progress func(got, total int64)) error {
	if os.Geteuid() != 0 {
		return fmt.Errorf("must run as root")
	}
	st, err := os.Stat(image)
	if err != nil {
		return fmt.Errorf("image: %w", err)
	}
	if !st.Mode().IsRegular() {
		return fmt.Errorf("image must be a regular file")
	}
	if st.Size() < 8<<20 {
		return fmt.Errorf("image is too small to be a First Boot disk")
	}

	dev, err := os.Stat(device)
	if err != nil {
		return fmt.Errorf("device: %w", err)
	}
	if dev.Mode()&os.ModeDevice == 0 {
		return fmt.Errorf("%s is not a block device", device)
	}
	sys, err := systemDisk()
	if err == nil && sys != "" && sameDisk(device, sys) {
		return fmt.Errorf("refusing to write the system disk (%s)", sys)
	}
	if mounted, err := hasMountedChildren(device); err != nil {
		return err
	} else if mounted {
		return fmt.Errorf("%s has mounted partitions; unmount them first", device)
	}

	devSize, err := deviceSize(device)
	if err != nil {
		return err
	}
	if devSize < st.Size() {
		return fmt.Errorf("device is %d bytes; image is %d", devSize, st.Size())
	}

	in, err := os.Open(image)
	if err != nil {
		return err
	}
	defer in.Close()
	out, err := os.OpenFile(device, os.O_RDWR, 0)
	if err != nil {
		return err
	}
	defer out.Close()

	buf := make([]byte, 4<<20)
	var got int64
	last := time.Now()
	for {
		n, readErr := in.Read(buf)
		if n > 0 {
			if _, err := out.Write(buf[:n]); err != nil {
				return err
			}
			got += int64(n)
			if progress != nil && time.Since(last) > 100*time.Millisecond {
				progress(got, st.Size())
				last = time.Now()
			}
		}
		if readErr == io.EOF {
			break
		}
		if readErr != nil {
			return readErr
		}
	}
	if err := out.Sync(); err != nil {
		return err
	}
	if progress != nil {
		progress(got, st.Size())
	}
	return nil
}

func deviceSize(path string) (int64, error) {
	f, err := os.Open(path)
	if err != nil {
		return 0, err
	}
	defer f.Close()
	return f.Seek(0, io.SeekEnd)
}

func systemDisk() (string, error) {
	list, err := devices.List()
	if err != nil {
		return "", err
	}
	for _, d := range list {
		if d.System {
			return d.Path, nil
		}
	}
	return "", nil
}

func sameDisk(a, b string) bool {
	a = filepath.Clean(a)
	b = filepath.Clean(b)
	if a == b {
		return true
	}
	// /dev/sda vs /dev/sda1
	if strings.HasPrefix(a, b) || strings.HasPrefix(b, a) {
		return true
	}
	return false
}

func hasMountedChildren(device string) (bool, error) {
	f, err := os.Open("/proc/mounts")
	if err != nil {
		return false, err
	}
	defer f.Close()
	raw, err := io.ReadAll(f)
	if err != nil {
		return false, err
	}
	dev := filepath.Clean(device)
	for _, line := range strings.Split(string(raw), "\n") {
		fields := strings.Fields(line)
		if len(fields) < 2 {
			continue
		}
		src := fields[0]
		if src == dev || strings.HasPrefix(src, dev) {
			return true, nil
		}
	}
	return false, nil
}

func IsRoot() bool { return os.Geteuid() == 0 }
