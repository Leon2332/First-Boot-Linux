package assets

import (
	"os"
	"path/filepath"
	"testing"
)

func TestOfficialCatalogPrefersAppDir(t *testing.T) {
	dir := t.TempDir()
	want := filepath.Join(dir, "usr", "share", "firstboot", "official-catalog.json")
	if err := os.MkdirAll(filepath.Dir(want), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(want, []byte(`{"schema_version":1}`), 0o644); err != nil {
		t.Fatal(err)
	}
	t.Setenv("FIRSTBOOT_OFFICIAL_CATALOG", "")
	t.Setenv("APPDIR", dir)
	got, err := OfficialCatalog()
	if err != nil {
		t.Fatal(err)
	}
	if got != want {
		t.Fatalf("got %s want %s", got, want)
	}
}

func TestDefaultWallpaperRepoSources(t *testing.T) {
	t.Setenv("APPDIR", "")
	dark, err := DefaultWallpaper("dark")
	if err != nil {
		t.Fatal(err)
	}
	if filepath.Base(dark) != "felix-mittermeier-L4-16dmZ-1c-unsplash.jpg" {
		t.Fatalf("dark source %s", dark)
	}
	light, err := DefaultWallpaper("light")
	if err != nil {
		t.Fatal(err)
	}
	if filepath.Base(light) != "sarah-barr-zYPCi2V6Ig4-unsplash.jpg" {
		t.Fatalf("light source %s", light)
	}
}

func TestDefaultWallpaperPrefersAppDir(t *testing.T) {
	dir := t.TempDir()
	want := filepath.Join(dir, "usr", "share", "firstboot", "wallpapers", "dark.jpg")
	if err := os.MkdirAll(filepath.Dir(want), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(want, []byte("dark"), 0o644); err != nil {
		t.Fatal(err)
	}
	t.Setenv("APPDIR", dir)
	got, err := DefaultWallpaper("dark")
	if err != nil {
		t.Fatal(err)
	}
	if got != want {
		t.Fatalf("got %s want %s", got, want)
	}
}

func TestCatalogPOPrefersAppDir(t *testing.T) {
	dir := t.TempDir()
	want := filepath.Join(dir, "usr", "share", "firstboot", "locale", "af.po")
	if err := os.MkdirAll(filepath.Dir(want), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(want, []byte(`msgid "Network"`+"\n"+`msgstr "Netwerk"`+"\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	t.Setenv("FIRSTBOOT_LOCALE", "")
	t.Setenv("APPDIR", dir)
	got, err := CatalogPO("af")
	if err != nil {
		t.Fatal(err)
	}
	if got != want {
		t.Fatalf("got %s want %s", got, want)
	}
}

func TestAppImageDir(t *testing.T) {
	t.Setenv("APPIMAGE", "/shop/FirstBoot.AppImage")
	if got := AppImageDir(); got != "/shop" {
		t.Fatalf("got %s", got)
	}
	t.Setenv("APPDIR", "")
	if AppDir() != "" {
		t.Fatal("empty APPDIR should be ignored")
	}
}
