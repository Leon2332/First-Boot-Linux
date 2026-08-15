package devices

import (
	"bufio"
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"
)

type Disk struct {
	Name      string
	Path      string
	Size      int64
	Model     string
	Removable bool
	USB       bool
	System    bool
}

func (d Disk) Label() string {
	size := formatSize(d.Size)
	kind := "disk"
	if d.USB {
		kind = "USB"
	} else if d.Removable {
		kind = "removable"
	}
	model := strings.TrimSpace(d.Model)
	if model == "" {
		model = d.Name
	}
	s := fmt.Sprintf("%s — %s (%s)", model, size, kind)
	if d.System {
		s += " · system disk"
	}
	return s
}

func List() ([]Disk, error) {
	entries, err := os.ReadDir("/sys/block")
	if err != nil {
		return nil, err
	}
	sysDev := systemDisk()
	var out []Disk
	for _, e := range entries {
		name := e.Name()
		if skipName(name) {
			continue
		}
		base := filepath.Join("/sys/block", name)
		size := readInt(filepath.Join(base, "size")) * 512
		if size <= 0 {
			continue
		}
		d := Disk{
			Name:      name,
			Path:      "/dev/" + name,
			Size:      size,
			Model:     readTrim(filepath.Join(base, "device", "model")),
			Removable: readTrim(filepath.Join(base, "removable")) == "1",
			USB:       isUSB(base),
			System:    sysDev != "" && (name == sysDev || strings.HasPrefix(sysDev, name)),
		}
		if d.Model == "" {
			d.Model = readTrim(filepath.Join(base, "device", "name"))
		}
		out = append(out, d)
	}
	return out, nil
}

func skipName(name string) bool {
	for _, p := range []string{"loop", "ram", "sr", "zram", "fd", "md", "dm-"} {
		if name == p || strings.HasPrefix(name, p) {
			return true
		}
	}
	return false
}

func isUSB(sysBlock string) bool {
	link, err := filepath.EvalSymlinks(filepath.Join(sysBlock, "device"))
	if err != nil {
		return false
	}
	return strings.Contains(link, "/usb")
}

func systemDisk() string {
	src := findmntSource("/")
	if src == "" {
		src = mountSource("/")
	}
	if src == "" {
		return ""
	}
	base := filepath.Base(src)
	// nvme0n1p2 → nvme0n1 ; sda2 → sda ; mmcblk0p1 → mmcblk0
	if strings.HasPrefix(base, "nvme") || strings.HasPrefix(base, "mmcblk") || strings.HasPrefix(base, "loop") {
		if i := strings.LastIndex(base, "p"); i > 0 {
			return base[:i]
		}
	}
	for i := len(base) - 1; i >= 0; i-- {
		if base[i] < '0' || base[i] > '9' {
			return base[:i+1]
		}
	}
	return base
}

func findmntSource(target string) string {
	f, err := os.Open("/proc/self/mountinfo")
	if err != nil {
		return ""
	}
	defer f.Close()
	sc := bufio.NewScanner(f)
	for sc.Scan() {
		line := sc.Text()
		// ... mountpoint ... - fstype source super
		parts := strings.Split(line, " - ")
		if len(parts) != 2 {
			continue
		}
		left := strings.Fields(parts[0])
		right := strings.Fields(parts[1])
		if len(left) < 5 || len(right) < 2 {
			continue
		}
		if left[4] == target {
			return right[1]
		}
	}
	return ""
}

func mountSource(target string) string {
	f, err := os.Open("/proc/mounts")
	if err != nil {
		return ""
	}
	defer f.Close()
	sc := bufio.NewScanner(f)
	for sc.Scan() {
		fields := strings.Fields(sc.Text())
		if len(fields) >= 2 && fields[1] == target {
			return fields[0]
		}
	}
	return ""
}

func readTrim(path string) string {
	b, err := os.ReadFile(path)
	if err != nil {
		return ""
	}
	return strings.TrimSpace(string(b))
}

func readInt(path string) int64 {
	s := readTrim(path)
	n, err := strconv.ParseInt(s, 10, 64)
	if err != nil {
		return 0
	}
	return n
}

func formatSize(n int64) string {
	const gib = 1024 * 1024 * 1024
	if n >= gib {
		return fmt.Sprintf("%.1f GB", float64(n)/float64(gib))
	}
	const mib = 1024 * 1024
	return fmt.Sprintf("%d MB", n/mib)
}
