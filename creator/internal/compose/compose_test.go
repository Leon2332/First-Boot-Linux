package compose

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"os"
	"os/exec"
	"path/filepath"
	"testing"

	"github.com/Leon2332/First-Boot-Linux/creator/internal/cache"
	"github.com/Leon2332/First-Boot-Linux/creator/internal/catalog"
	"github.com/Leon2332/First-Boot-Linux/creator/internal/seedpath"
)

func TestWriteTinyImage(t *testing.T) {
	if _, err := exec.LookPath("mke2fs"); err != nil {
		t.Skip("mke2fs not installed")
	}
	oldE, oldS, oldD := ESPMiB, SYSMiB, minDataBytes
	ESPMiB, SYSMiB, minDataBytes = 64, 64, 32<<20
	t.Cleanup(func() {
		ESPMiB, SYSMiB, minDataBytes = oldE, oldS, oldD
	})

	dir := t.TempDir()
	seedDir := filepath.Join(dir, "seed")
	mustTinySeed(t, seedDir)
	seed, err := seedpath.Open(seedDir)
	if err != nil {
		t.Fatal(err)
	}

	iso := filepath.Join(dir, "tiny.iso")
	payload := []byte("tiny-iso-payload-for-creator-test\n")
	if err := os.WriteFile(iso, payload, 0o644); err != nil {
		t.Fatal(err)
	}
	sum := sha256.Sum256(payload)
	hexSum := hex.EncodeToString(sum[:])
	size := int64(len(payload))
	url := "file://" + iso

	off := &catalog.Official{
		SchemaVersion: 1,
		Distros: []catalog.Distro{{
			ID: "ubuntu", Name: "Ubuntu", Version: "26.04 LTS",
			Tagline: "t", Description: "d", Family: "ubuntu",
			Install: strp("ubuntu-autoinstall"), CanStage: true, SuggestedDefault: true,
			Editions: []catalog.Edition{{
				ID: "gnome", Name: "GNOME", Default: true,
				Filename: "tiny.iso", URL: &url, SHA256: &hexSum, SizeBytes: &size,
			}},
		}},
	}
	shop, err := catalog.BuildShop(off, []string{"ubuntu"})
	if err != nil {
		t.Fatal(err)
	}

	cacheDir := filepath.Join(dir, "cache")
	if err := os.MkdirAll(cacheDir, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(cacheDir, "tiny.iso"), payload, 0o644); err != nil {
		t.Fatal(err)
	}

	dark := filepath.Join(dir, "dark.jpg")
	light := filepath.Join(dir, "light.jpg")
	_ = os.WriteFile(dark, []byte("dark"), 0o644)
	_ = os.WriteFile(light, []byte("light"), 0o644)

	out := filepath.Join(dir, "out.img")
	err = Write(context.Background(), Request{
		Retailer: catalog.Retailer{
			Name: "Test Shop", Support: "test@example.com",
			WallpaperDark: dark, WallpaperLight: light,
		},
		Shop:     shop,
		Official: off,
		Seed:     seed,
		Cache:    cache.New(cacheDir),
		Out:      out,
		Password: "test-pass-9",
	})
	if err != nil {
		t.Fatal(err)
	}
	st, err := os.Stat(out)
	if err != nil {
		t.Fatal(err)
	}
	if st.Size() < 80<<20 {
		t.Fatalf("image too small: %d", st.Size())
	}
	raw, err := os.ReadFile(out)
	if err != nil {
		t.Fatal(err)
	}
	if raw[510] != 0x55 || raw[511] != 0xAA {
		t.Fatalf("not a GPT disk")
	}
	if !containsName(raw, "FBL-SYS") {
		t.Fatalf("missing FBL-SYS")
	}
}

func containsName(raw []byte, name string) bool {
	enc := make([]byte, 0, len(name)*2)
	for i := 0; i < len(name); i++ {
		enc = append(enc, name[i], 0)
	}
	return bytesIndex(raw, enc)
}

func bytesIndex(hay, needle []byte) bool {
	if len(needle) == 0 || len(hay) < len(needle) {
		return false
	}
	for i := 0; i <= len(hay)-len(needle); i++ {
		ok := true
		for j := 0; j < len(needle); j++ {
			if hay[i+j] != needle[j] {
				ok = false
				break
			}
		}
		if ok {
			return true
		}
	}
	return false
}

func strp(s string) *string { return &s }

func mustTinySeed(t *testing.T, dir string) {
	t.Helper()
	for _, d := range []string{dir, filepath.Join(dir, "efi")} {
		if err := os.MkdirAll(d, 0o755); err != nil {
			t.Fatal(err)
		}
	}
	write := func(name string, b []byte) {
		if err := os.WriteFile(filepath.Join(dir, name), b, 0o644); err != nil {
			t.Fatal(err)
		}
	}
	write("filesystem.squashfs", []byte("squash"))
	write("vmlinuz", []byte("vmlinuz"))
	write("initrd", []byte("initrd"))
	write("os-release", []byte("VERSION_ID=\"test\"\n"))
	write("efi/BOOTX64.EFI", []byte("efi-boot"))
	write("efi/grubx64.efi", []byte("efi-grub"))
	write("efi/shimx64.efi", []byte("efi-shim"))
	write("efi/mmx64.efi", []byte("efi-mok"))
}
