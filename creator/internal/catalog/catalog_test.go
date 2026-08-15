package catalog

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestLoadOfficialAndStageable(t *testing.T) {
	cat, err := LoadOfficial("")
	if err != nil {
		t.Fatalf("load: %v", err)
	}
	u := cat.Distro("ubuntu")
	if u == nil || !u.Stageable() {
		t.Fatalf("ubuntu should be stageable")
	}
	if u.DefaultEdition() == nil || u.DefaultEdition().SHA256 == nil {
		t.Fatalf("ubuntu default edition not pinned")
	}
	if *u.DefaultEdition().SizeBytes != 6518974464 {
		t.Fatalf("ubuntu size %v", u.DefaultEdition().SizeBytes)
	}
	m := cat.Distro("linux-mint")
	if m == nil || !m.Stageable() {
		t.Fatalf("mint should be stageable")
	}
	if !m.SuggestedDefault || !u.SuggestedDefault {
		t.Fatalf("ubuntu and mint should be suggested defaults")
	}
	f := cat.Distro("fedora")
	if f == nil || f.Stageable() {
		t.Fatalf("fedora must not be stageable")
	}
	if f.Install != nil {
		t.Fatalf("fedora install should be null")
	}
}

func TestBuildShop(t *testing.T) {
	cat, err := LoadOfficial("")
	if err != nil {
		t.Fatal(err)
	}
	shop, err := BuildShop(cat, []string{"ubuntu", "linux-mint"})
	if err != nil {
		t.Fatal(err)
	}
	if len(shop.Recommended) != 2 || len(shop.Catalog) != 0 {
		t.Fatalf("got rec=%d cat=%d", len(shop.Recommended), len(shop.Catalog))
	}
	ub := shop.Recommended[0]
	if !ub.Editions[0].Local || ub.Editions[0].File != "images/ubuntu-26.04-desktop-amd64.iso" {
		t.Fatalf("ubuntu edition %+v", ub.Editions[0])
	}
	if ub.Install != "ubuntu-autoinstall" {
		t.Fatalf("install %s", ub.Install)
	}
	mint := shop.Recommended[1]
	var local, remote int
	for _, e := range mint.Editions {
		if e.Local {
			local++
			if e.File == "" {
				t.Fatalf("local edition missing file")
			}
		} else {
			remote++
			if e.URL == "" {
				t.Fatalf("download edition missing url")
			}
		}
		if len(e.SHA256) != 64 {
			t.Fatalf("hash %s", e.SHA256)
		}
	}
	if local != 1 || remote != 2 {
		t.Fatalf("mint editions local=%d remote=%d", local, remote)
	}

	if _, err := BuildShop(cat, []string{"fedora"}); err == nil {
		t.Fatalf("fedora must be rejected")
	}
	if _, err := BuildShop(cat, nil); err == nil {
		t.Fatalf("empty selection must be rejected")
	}
}

func TestRetailerFile(t *testing.T) {
	dir := t.TempDir()
	dark := filepath.Join(dir, "d.jpg")
	light := filepath.Join(dir, "l.jpg")
	if err := os.WriteFile(dark, []byte("x"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(light, []byte("y"), 0o644); err != nil {
		t.Fatal(err)
	}
	r := Retailer{Name: "Example Computers", Support: "support@example.com", WallpaperDark: dark, WallpaperLight: light}
	if err := ValidateRetailer(r); err != nil {
		t.Fatal(err)
	}
	got := RetailerFile(r)
	for _, want := range []string{
		"schema_version = 1",
		"name = Example Computers",
		"support = support@example.com",
		"wallpaper_dark = wallpapers/dark.jpg",
		"wallpaper_light = wallpapers/light.jpg",
	} {
		if !strings.Contains(got, want) {
			t.Fatalf("missing %q in %s", want, got)
		}
	}
	if err := ValidateRetailer(Retailer{Name: "", Support: "x", WallpaperDark: dark, WallpaperLight: light}); err == nil {
		t.Fatalf("empty name should fail")
	}
}

func TestStickSuggestion(t *testing.T) {
	if g := StickSuggestion(6 << 30); g != 16 {
		t.Fatalf("6G → %d", g)
	}
	if g := StickSuggestion(12 << 30); g != 32 {
		t.Fatalf("12G → %d", g)
	}
	if FormatBytes(6518974464) == "" {
		t.Fatal("format")
	}
}
