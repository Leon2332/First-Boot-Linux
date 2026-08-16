package ui

import (
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"

	"github.com/Leon2332/First-Boot-Linux/creator/internal/assets"
	"github.com/Leon2332/First-Boot-Linux/creator/internal/cache"
)

func findHelper() string {
	var cands []string
	if d := assets.AppDir(); d != "" {
		cands = append(cands,
			filepath.Join(d, "usr", "bin", "firstboot-write-usb"),
			filepath.Join(d, "firstboot-write-usb"),
		)
	}
	if exe, err := os.Executable(); err == nil {
		dir := filepath.Dir(exe)
		cands = append(cands,
			filepath.Join(dir, "firstboot-write-usb"),
			filepath.Join(dir, "bin", "firstboot-write-usb"),
		)
	}
	for _, p := range cands {
		if assets.FileExists(p) {
			return p
		}
	}
	if p, err := exec.LookPath("firstboot-write-usb"); err == nil {
		return p
	}
	return ""
}

func helperCachePath() string {
	dir, err := os.UserCacheDir()
	if err != nil {
		return filepath.Join(os.TempDir(), "firstboot", "bin", "firstboot-write-usb")
	}
	return filepath.Join(dir, "firstboot", "bin", "firstboot-write-usb")
}

// materializeHelper copies firstboot-write-usb to ~/.cache so pkexec is not
// asked to run a file from a FUSE AppImage mount (often noexec /tmp).
func materializeHelper() (string, error) {
	src := findHelper()
	if src == "" {
		return "", fmt.Errorf("firstboot-write-usb is not next to this program")
	}
	dest := helperCachePath()
	if samePath(src, dest) {
		return dest, nil
	}
	if err := os.MkdirAll(filepath.Dir(dest), 0o755); err != nil {
		return "", err
	}
	if assets.FileExists(dest) {
		if eq, err := sameContent(src, dest); err == nil && eq {
			return dest, nil
		}
	}
	tmp := dest + ".new"
	if err := copyExec(src, tmp); err != nil {
		_ = os.Remove(tmp)
		return "", fmt.Errorf("prepare write helper: %w", err)
	}
	if err := os.Rename(tmp, dest); err != nil {
		_ = os.Remove(tmp)
		return "", fmt.Errorf("prepare write helper: %w", err)
	}
	return dest, nil
}

func samePath(a, b string) bool {
	as, err := os.Stat(a)
	if err != nil {
		return false
	}
	bs, err := os.Stat(b)
	if err != nil {
		return false
	}
	return os.SameFile(as, bs)
}

func sameContent(a, b string) (bool, error) {
	sa, err := os.Stat(a)
	if err != nil {
		return false, err
	}
	sb, err := os.Stat(b)
	if err != nil {
		return false, err
	}
	if sa.Size() != sb.Size() {
		return false, nil
	}
	ha, err := cache.HashFile(a)
	if err != nil {
		return false, err
	}
	hb, err := cache.HashFile(b)
	if err != nil {
		return false, err
	}
	return ha == hb, nil
}

func copyExec(src, dest string) error {
	in, err := os.Open(src)
	if err != nil {
		return err
	}
	defer in.Close()
	out, err := os.OpenFile(dest, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0o755)
	if err != nil {
		return err
	}
	if _, err := io.Copy(out, in); err != nil {
		out.Close()
		return err
	}
	if err := out.Chmod(0o755); err != nil {
		out.Close()
		return err
	}
	return out.Close()
}
