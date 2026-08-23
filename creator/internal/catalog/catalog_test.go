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
	if u == nil || !u.Redistributable || !u.Stageable() {
		t.Fatalf("ubuntu should be redistributable and stageable")
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
	if f == nil || !f.Stageable() {
		t.Fatalf("fedora should be stageable")
	}
	if f.Install == nil || *f.Install != "fedora-kickstart" {
		t.Fatalf("fedora install %v", f.Install)
	}
	if f.SuggestedDefault {
		t.Fatalf("fedora should not be a suggested default")
	}
	ed := f.DefaultEdition()
	if ed == nil || ed.Filename != "Fedora-KDE-Desktop-Live-44-1.7.x86_64.iso" {
		t.Fatalf("fedora plasma filename %+v", ed)
	}
	if ed.SizeBytes == nil || *ed.SizeBytes != 3368683520 {
		t.Fatalf("fedora size %v", ed.SizeBytes)
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
	if len(shop.Recommended) != 2 {
		t.Fatalf("got rec=%d", len(shop.Recommended))
	}
	if len(shop.Catalog) != 1 || shop.Catalog[0].ID != "fedora" {
		t.Fatalf("unticked fedora should be catalog, got %+v", shop.Catalog)
	}
	if shop.Catalog[0].Editions[0].Local || shop.Catalog[0].Editions[0].URL == "" {
		t.Fatalf("catalog fedora must be download-only: %+v", shop.Catalog[0].Editions)
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

	if _, err := BuildShop(cat, []string{"fedora"}); err != nil {
		t.Fatalf("fedora should be allowed: %v", err)
	}
	if _, err := BuildShop(cat, nil); err == nil {
		t.Fatalf("empty selection must be rejected")
	}
}

func TestBuildShopUntickedGoesToCatalog(t *testing.T) {
	cat, err := LoadOfficial("")
	if err != nil {
		t.Fatal(err)
	}
	shop, err := BuildShop(cat, []string{"linux-mint", "fedora"})
	if err != nil {
		t.Fatal(err)
	}
	if len(shop.Recommended) != 2 {
		t.Fatalf("recommended %d", len(shop.Recommended))
	}
	if shop.Recommended[0].ID != "linux-mint" || shop.Recommended[1].ID != "fedora" {
		t.Fatalf("recommended ids %s %s", shop.Recommended[0].ID, shop.Recommended[1].ID)
	}
	if !shop.Recommended[0].Editions[0].Local || !shop.Recommended[1].Editions[0].Local {
		t.Fatal("ticked mint and fedora should be staged")
	}
	if len(shop.Catalog) != 1 || shop.Catalog[0].ID != "ubuntu" {
		t.Fatalf("ubuntu should be the download catalog, got %+v", shop.Catalog)
	}
	ub := shop.Catalog[0].Editions[0]
	if ub.Local || ub.File != "" || ub.URL == "" {
		t.Fatalf("ubuntu catalog edition must be download-only: %+v", ub)
	}
	if ub.URL != "https://releases.ubuntu.com/26.04/ubuntu-26.04-desktop-amd64.iso" {
		t.Fatalf("ubuntu url %s", ub.URL)
	}
}

func TestBuildShopDownloadOnlyRecommended(t *testing.T) {
	url := "https://example.invalid/windows.iso"
	sum := "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
	size := int64(6 << 30)
	install := "windows"
	off := &Official{
		SchemaVersion: 1,
		Distros: []Distro{
			{
				ID: "ubuntu", Name: "Ubuntu", Version: "26.04 LTS",
				Tagline: "t", Description: "d", Family: "ubuntu",
				Redistributable: true, Install: strp("ubuntu-autoinstall"),
				CanStage: true, SuggestedDefault: true,
				Editions: []Edition{{
					ID: "gnome", Name: "GNOME", Default: true,
					Filename: "ubuntu.iso", URL: &url, SHA256: &sum, SizeBytes: &size,
				}},
			},
			{
				ID: "ms-windows", Name: "MS Windows", Version: "11",
				Tagline: "t", Description: "d", Family: "windows",
				Redistributable: false, Install: &install,
				CanStage: false, SuggestedDefault: false,
				Editions: []Edition{{
					ID: "windows-11", Name: "Windows 11", Default: true,
					Filename: "windows.iso", URL: &url, SHA256: &sum, SizeBytes: &size,
				}},
			},
		},
	}
	if off.Distro("ms-windows").Stageable() {
		t.Fatal("windows must not be stageable")
	}
	if !off.Distro("ms-windows").Offerable() {
		t.Fatal("windows should be offerable as download-only")
	}
	shop, err := BuildShop(off, []string{"ubuntu", "ms-windows"})
	if err != nil {
		t.Fatal(err)
	}
	if len(shop.Recommended) != 2 {
		t.Fatalf("recommended %d", len(shop.Recommended))
	}
	win := shop.Recommended[1]
	if win.ID != "ms-windows" || win.Install != "windows" || win.Family != "windows" {
		t.Fatalf("windows row %+v", win)
	}
	if len(win.Editions) != 1 || win.Editions[0].Local || win.Editions[0].File != "" || win.Editions[0].URL == "" {
		t.Fatalf("windows must be download-only: %+v", win.Editions)
	}
	if !shop.Recommended[0].Editions[0].Local {
		t.Fatal("ubuntu should still be local")
	}
	if len(shop.LocalEditions()) != 1 {
		t.Fatalf("local editions %d", len(shop.LocalEditions()))
	}
}

func strp(s string) *string { return &s }

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
