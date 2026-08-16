package seedpath

import (
	"os"
	"path/filepath"
	"testing"
)

func TestLocateNextToAppImage(t *testing.T) {
	dir := t.TempDir()
	seedDir := filepath.Join(dir, "seed")
	mustTinySeed(t, seedDir)
	t.Setenv("FIRSTBOOT_SEED", "")
	t.Setenv("APPIMAGE", filepath.Join(dir, "firstboot-creator.AppImage"))
	t.Setenv("APPDIR", "")

	s, err := Locate("")
	if err != nil {
		t.Fatal(err)
	}
	if s.Dir != seedDir {
		t.Fatalf("got %s want %s", s.Dir, seedDir)
	}
}

func mustTinySeed(t *testing.T, dir string) {
	t.Helper()
	for _, d := range []string{dir, filepath.Join(dir, "efi")} {
		if err := os.MkdirAll(d, 0o755); err != nil {
			t.Fatal(err)
		}
	}
	write := func(name, body string) {
		if err := os.WriteFile(filepath.Join(dir, name), []byte(body), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	write("filesystem.squashfs", "squash")
	write("vmlinuz", "vmlinuz")
	write("initrd", "initrd")
	write("os-release", "VERSION_ID=\"test\"\n")
	write("efi/BOOTX64.EFI", "efi-boot")
	write("efi/grubx64.efi", "efi-grub")
}
