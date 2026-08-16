package ui

import (
	"os"
	"path/filepath"
	"testing"
)

func TestFindHelperPrefersAppDir(t *testing.T) {
	dir := t.TempDir()
	want := filepath.Join(dir, "usr", "bin", "firstboot-write-usb")
	if err := os.MkdirAll(filepath.Dir(want), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(want, []byte("helper"), 0o755); err != nil {
		t.Fatal(err)
	}
	t.Setenv("APPDIR", dir)
	got := findHelper()
	if got != want {
		t.Fatalf("got %s want %s", got, want)
	}
}

func TestMaterializeHelperCopiesOnce(t *testing.T) {
	dir := t.TempDir()
	src := filepath.Join(dir, "usr", "bin", "firstboot-write-usb")
	if err := os.MkdirAll(filepath.Dir(src), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(src, []byte("helper-v1"), 0o755); err != nil {
		t.Fatal(err)
	}
	cache := filepath.Join(dir, "cache")
	t.Setenv("APPDIR", dir)
	t.Setenv("XDG_CACHE_HOME", cache)

	dest, err := materializeHelper()
	if err != nil {
		t.Fatal(err)
	}
	want := filepath.Join(cache, "firstboot", "bin", "firstboot-write-usb")
	if dest != want {
		t.Fatalf("got %s want %s", dest, want)
	}
	raw, err := os.ReadFile(dest)
	if err != nil {
		t.Fatal(err)
	}
	if string(raw) != "helper-v1" {
		t.Fatalf("copied %q", raw)
	}

	again, err := materializeHelper()
	if err != nil {
		t.Fatal(err)
	}
	if again != dest {
		t.Fatalf("second copy %s", again)
	}

	if err := os.WriteFile(src, []byte("helper-v2"), 0o755); err != nil {
		t.Fatal(err)
	}
	updated, err := materializeHelper()
	if err != nil {
		t.Fatal(err)
	}
	raw, err = os.ReadFile(updated)
	if err != nil {
		t.Fatal(err)
	}
	if string(raw) != "helper-v2" {
		t.Fatalf("updated %q", raw)
	}
}
