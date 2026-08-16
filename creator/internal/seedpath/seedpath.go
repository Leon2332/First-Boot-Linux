package seedpath

import (
	"fmt"
	"os"
	"path/filepath"

	"github.com/Leon2332/First-Boot-Linux/creator/internal/assets"
)

type Seed struct {
	Dir      string
	Version  string
	Squashfs string
	Vmlinuz  string
	Initrd   string
	Size     string
	Manifest string
	EFI      EFI
}

type EFI struct {
	BOOTX64 string
	GRUB    string
	Shim    string
	MOK     string
}

func Locate(explicit string) (*Seed, error) {
	var candidates []string
	if explicit != "" {
		candidates = append(candidates, explicit)
	}
	if env := os.Getenv("FIRSTBOOT_SEED"); env != "" {
		candidates = append(candidates, env)
	}
	if imgDir := assets.AppImageDir(); imgDir != "" {
		candidates = append(candidates, filepath.Join(imgDir, "seed"))
	} else if appDir := assets.AppDir(); appDir != "" {
		// Extracted AppDir (no APPIMAGE): seed/ sits next to squashfs-root/.
		candidates = append(candidates, filepath.Join(filepath.Dir(appDir), "seed"))
	}
	exe := assets.ExecutableDir()
	candidates = append(candidates,
		filepath.Join(exe, "seed"),
		filepath.Join(exe, "data", "seed"),
	)
	if repo, err := assets.RepoRoot(""); err == nil {
		candidates = append(candidates, filepath.Join(repo, "build", "seed"))
	}
	var tried []string
	for _, c := range candidates {
		if c == "" {
			continue
		}
		tried = append(tried, c)
		s, err := Open(c)
		if err == nil {
			return s, nil
		}
	}
	hint := "Unpack firstboot-seed-*.tar into a seed/ directory next to this program, or set FIRSTBOOT_SEED"
	if _, err := assets.RepoRoot(""); err == nil {
		hint = "Build it with ./seed/build-in-docker.sh"
	}
	return nil, fmt.Errorf("no First Boot seed found (looked in %s). %s", join(tried), hint)
}

func Open(dir string) (*Seed, error) {
	st, err := os.Stat(dir)
	if err != nil || !st.IsDir() {
		return nil, fmt.Errorf("seed directory %s not found", dir)
	}
	s := &Seed{
		Dir:      dir,
		Squashfs: filepath.Join(dir, "filesystem.squashfs"),
		Vmlinuz:  filepath.Join(dir, "vmlinuz"),
		Initrd:   filepath.Join(dir, "initrd"),
		Size:     filepath.Join(dir, "filesystem.size"),
		Manifest: filepath.Join(dir, "filesystem.manifest"),
	}
	for _, p := range []string{s.Squashfs, s.Vmlinuz, s.Initrd} {
		if !assets.FileExists(p) {
			return nil, fmt.Errorf("seed missing %s", filepath.Base(p))
		}
	}
	s.Version = readVersion(dir)
	efiDir := filepath.Join(dir, "efi")
	bootx64 := filepath.Join(efiDir, "BOOTX64.EFI")
	grub := filepath.Join(efiDir, "grubx64.efi")
	if !assets.FileExists(bootx64) || !assets.FileExists(grub) {
		return nil, fmt.Errorf("seed missing signed EFI files under efi/")
	}
	s.EFI.BOOTX64 = bootx64
	s.EFI.GRUB = grub
	shim := filepath.Join(efiDir, "shimx64.efi")
	if assets.FileExists(shim) {
		s.EFI.Shim = shim
	} else {
		s.EFI.Shim = bootx64
	}
	mok := filepath.Join(efiDir, "mmx64.efi")
	if assets.FileExists(mok) {
		s.EFI.MOK = mok
	}
	return s, nil
}

func (s *Seed) CasperBytes() int64 {
	var n int64
	for _, p := range []string{s.Squashfs, s.Vmlinuz, s.Initrd} {
		if st, err := os.Stat(p); err == nil {
			n += st.Size()
		}
	}
	return n
}

func readVersion(dir string) string {
	osr := filepath.Join(dir, "os-release")
	if raw, err := os.ReadFile(osr); err == nil {
		for _, line := range splitLines(string(raw)) {
			if len(line) > 11 && line[:11] == "VERSION_ID=" {
				v := line[11:]
				if len(v) >= 2 && v[0] == '"' {
					v = v[1 : len(v)-1]
				}
				return v
			}
		}
	}
	if repo, err := assets.RepoRoot(dir); err == nil {
		if raw, err := os.ReadFile(filepath.Join(repo, "seed", "VERSION")); err == nil {
			return trim(string(raw))
		}
	}
	return "unknown"
}

func splitLines(s string) []string {
	var out []string
	start := 0
	for i := 0; i < len(s); i++ {
		if s[i] == '\n' {
			out = append(out, s[start:i])
			start = i + 1
		}
	}
	if start < len(s) {
		out = append(out, s[start:])
	}
	return out
}

func trim(s string) string {
	for len(s) > 0 && (s[0] == ' ' || s[0] == '\n' || s[0] == '\r' || s[0] == '\t') {
		s = s[1:]
	}
	for len(s) > 0 && (s[len(s)-1] == ' ' || s[len(s)-1] == '\n' || s[len(s)-1] == '\r' || s[len(s)-1] == '\t') {
		s = s[:len(s)-1]
	}
	return s
}

func join(s []string) string {
	if len(s) == 0 {
		return "(none)"
	}
	out := s[0]
	for i := 1; i < len(s); i++ {
		out += ", " + s[i]
	}
	return out
}
