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
	if u.SuggestedDefault || m.SuggestedDefault {
		t.Fatalf("nothing should be a suggested default")
	}
	if cat.Distro("linux-mint-mate") != nil || cat.Distro("linux-mint-xfce") != nil {
		t.Fatal("mint DEs are editions, not separate distros")
	}
	if len(m.Editions) != 3 {
		t.Fatalf("mint editions %d", len(m.Editions))
	}
	if m.Edition("mate") == nil || m.Edition("mate").Filename != "linuxmint-22.3-mate-64bit.iso" {
		t.Fatalf("mint mate %+v", m.Edition("mate"))
	}
	if m.Edition("xfce") == nil || m.Edition("xfce").Filename != "linuxmint-22.3-xfce-64bit.iso" {
		t.Fatalf("mint xfce %+v", m.Edition("xfce"))
	}
	if !m.CanStageEdition(*m.Edition("cinnamon")) || !m.CanStageEdition(*m.Edition("mate")) {
		t.Fatal("mint editions should be stageable")
	}
	f := cat.Distro("fedora")
	if f == nil || !f.Stageable() {
		t.Fatalf("fedora should be stageable")
	}
	if f.Install == nil || *f.Install != "fedora-44-plasma" {
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
	if got := shopIDs(shop.Catalog); len(got) != 1 || got[0] != "fedora" {
		t.Fatalf("unticked fedora should be catalog, got %+v", got)
	}
	if shop.Catalog[0].Editions[0].Local || shop.Catalog[0].Editions[0].URL == "" {
		t.Fatalf("catalog fedora must be download-only: %+v", shop.Catalog[0].Editions)
	}
	ub := shop.Recommended[0]
	if !ub.Editions[0].Local || ub.Editions[0].File != "images/ubuntu-26.04-desktop-amd64.iso" {
		t.Fatalf("ubuntu edition %+v", ub.Editions[0])
	}
	if ub.Install != "ubuntu-2604" {
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
	if got := shopIDs(shop.Catalog); len(got) != 1 || got[0] != "ubuntu" {
		t.Fatalf("ubuntu should be the download catalog, got %+v", got)
	}
	ub := shop.Catalog[0].Editions[0]
	if ub.Local || ub.File != "" || ub.URL == "" {
		t.Fatalf("ubuntu catalog edition must be download-only: %+v", ub)
	}
	if ub.URL != "https://releases.ubuntu.com/26.04/ubuntu-26.04-desktop-amd64.iso" {
		t.Fatalf("ubuntu url %s", ub.URL)
	}
}

func TestBuildShopMintEditions(t *testing.T) {
	cat, err := LoadOfficial("")
	if err != nil {
		t.Fatal(err)
	}
	shop, err := BuildShop(cat, []string{"linux-mint:mate", "linux-mint:xfce"})
	if err != nil {
		t.Fatal(err)
	}
	if got := shopIDs(shop.Recommended); len(got) != 1 || got[0] != "linux-mint" {
		t.Fatalf("recommended %+v", got)
	}
	mint := shop.Recommended[0]
	if mint.Install != "mint-223" {
		t.Fatalf("install %s", mint.Install)
	}
	byID := map[string]ShopEdition{}
	for _, e := range mint.Editions {
		byID[e.ID] = e
	}
	if byID["cinnamon"].Local || byID["cinnamon"].Default {
		t.Fatalf("unticked cinnamon %+v", byID["cinnamon"])
	}
	if !byID["mate"].Local || byID["mate"].File != "images/linuxmint-22.3-mate-64bit.iso" {
		t.Fatalf("mate %+v", byID["mate"])
	}
	if !byID["xfce"].Local || byID["xfce"].File != "images/linuxmint-22.3-xfce-64bit.iso" {
		t.Fatalf("xfce %+v", byID["xfce"])
	}
	if !byID["mate"].Default || byID["xfce"].Default {
		t.Fatalf("featured should be first ticked (mate): %+v", mint.Editions)
	}
	if mint.Editions[0].ID != "mate" || mint.Editions[1].ID != "xfce" || mint.Editions[2].ID != "cinnamon" {
		t.Fatalf("ticked editions should come first: %+v", mint.Editions)
	}
	if got := shopIDs(shop.Catalog); len(got) != 2 || got[0] != "ubuntu" || got[1] != "fedora" {
		t.Fatalf("catalog %+v", got)
	}
}

func TestBuildShopMateXfceFedora(t *testing.T) {
	cat, err := LoadOfficial("")
	if err != nil {
		t.Fatal(err)
	}
	shop, err := BuildShop(cat, []string{"linux-mint:mate", "linux-mint:xfce", "fedora:plasma"})
	if err != nil {
		t.Fatal(err)
	}
	if got := shopIDs(shop.Recommended); len(got) != 2 || got[0] != "linux-mint" || got[1] != "fedora" {
		t.Fatalf("recommended %+v", got)
	}
	mint := shop.Recommended[0]
	byID := map[string]ShopEdition{}
	for _, e := range mint.Editions {
		byID[e.ID] = e
	}
	if byID["cinnamon"].Local || byID["cinnamon"].File != "" {
		t.Fatalf("unticked cinnamon must not be staged: %+v", byID["cinnamon"])
	}
	if byID["cinnamon"].URL == "" {
		t.Fatalf("cinnamon should stay a download: %+v", byID["cinnamon"])
	}
	if !byID["mate"].Local || byID["mate"].File != "images/linuxmint-22.3-mate-64bit.iso" {
		t.Fatalf("mate %+v", byID["mate"])
	}
	if !byID["xfce"].Local || byID["xfce"].File != "images/linuxmint-22.3-xfce-64bit.iso" {
		t.Fatalf("xfce %+v", byID["xfce"])
	}
	if !shop.Recommended[1].Editions[0].Local {
		t.Fatal("fedora plasma should be staged")
	}
	locals := shop.LocalEditions()
	if len(locals) != 3 {
		t.Fatalf("local editions %d %+v", len(locals), locals)
	}
	if got := shopIDs(shop.Catalog); len(got) != 1 || got[0] != "ubuntu" {
		t.Fatalf("catalog %+v", got)
	}
}

func TestParseStagedAndNameMatches(t *testing.T) {
	did, eid, err := ParseStaged("linux-mint:cinnamon")
	if err != nil || did != "linux-mint" || eid != "cinnamon" {
		t.Fatalf("got %s %s %v", did, eid, err)
	}
	did, eid, err = ParseStaged("ubuntu")
	if err != nil || did != "ubuntu" || eid != "" {
		t.Fatalf("bare %s %s %v", did, eid, err)
	}
	if !nameMatches("Linux Mint", "mint") || !nameMatches("Linux Mint", "Linux  mint") {
		t.Fatal("mint should match")
	}
	if nameMatches("Linux Mint", "mate") || nameMatches("Ubuntu", "gnome") {
		t.Fatal("edition names must not match")
	}
	if nameMatches("Fedora", "windows") {
		t.Fatal("unrelated")
	}
}

func shopIDs(ds []ShopDistro) []string {
	out := make([]string, len(ds))
	for i, d := range ds {
		out[i] = d.ID
	}
	return out
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
		"language = en-us",
		"keyboard = us",
		"timezone = UTC+0000",
	} {
		if !strings.Contains(got, want) {
			t.Fatalf("missing %q in %s", want, got)
		}
	}
	if err := ValidateRetailer(Retailer{Name: "", Support: "x", WallpaperDark: dark, WallpaperLight: light}); err == nil {
		t.Fatalf("empty name should fail")
	}
}

func TestLoadLanguages(t *testing.T) {
	langs, err := LoadLanguages("")
	if err != nil {
		t.Fatal(err)
	}
	ids := map[string]bool{}
	for _, lang := range langs {
		ids[lang.ID] = true
	}
	if !ids["en-us"] || !ids["en-gb"] || !ids["en-za"] || !ids["af"] {
		t.Fatalf("expected en-us, en-gb, en-za, and af, got %#v", langs)
	}
	if ids["en"] {
		t.Fatal("bare en should not be listed")
	}
	if ValidLanguage("de", langs) {
		t.Fatal("de is not shipped")
	}
	if !ValidLanguage("en", langs) {
		t.Fatal("en should alias to en-us")
	}
	if NormalizeRetailerLanguage("", langs) != "en-us" {
		t.Fatal("empty language should be en-us")
	}
	if NormalizeRetailerLanguage("EN", langs) != "en-us" {
		t.Fatal("EN should normalize to en-us")
	}
	if NormalizeRetailerLanguage("AF", langs) != "af" {
		t.Fatal("AF should normalize to af")
	}
	if NormalizeRetailerLanguage("en-GB", langs) != "en-gb" {
		t.Fatal("en-GB should stay en-gb")
	}
}

func TestLoadKeyboards(t *testing.T) {
	boards, err := LoadKeyboards("")
	if err != nil {
		t.Fatal(err)
	}
	ids := map[string]bool{}
	for _, kb := range boards {
		ids[kb.ID] = true
	}
	if !ids["us"] || !ids["gb"] {
		t.Fatalf("expected us and gb, got %#v", boards)
	}
	if ValidKeyboard("nope", boards) {
		t.Fatal("nope is not a layout")
	}
	if NormalizeRetailerKeyboard("", boards) != "us" {
		t.Fatal("empty keyboard should be us")
	}
	if NormalizeRetailerKeyboard("GB", boards) != "gb" {
		t.Fatal("GB should normalize to gb")
	}
}

func TestTimezone(t *testing.T) {
	if got := FormatTZ(0); got != "UTC+0000" {
		t.Fatalf("0 → %s", got)
	}
	if got := FormatTZ(330); got != "UTC+0530" {
		t.Fatalf("330 → %s", got)
	}
	if got := FormatTZ(-300); got != "UTC-0500" {
		t.Fatalf("-300 → %s", got)
	}
	if m, ok := ParseTZ("UTC+0530"); !ok || m != 330 {
		t.Fatalf("parse +0530: %d %v", m, ok)
	}
	if m, ok := ParseTZ("utc-0500"); !ok || m != -300 {
		t.Fatalf("parse -0500: %d %v", m, ok)
	}
	if _, ok := ParseTZ("Europe/Paris"); ok {
		t.Fatal("named zone should fail")
	}
	if NormalizeRetailerTimezone("") != "UTC+0000" {
		t.Fatal("empty tz")
	}
	if NormalizeRetailerTimezone("UTC+2") != "UTC+0200" {
		t.Fatal("UTC+2")
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
